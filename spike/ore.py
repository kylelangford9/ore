#!/usr/bin/env python3
"""Ore v0 spike: reference lexer, parser, name check, evaluator and core encoder.

The real toolchain is Rust (plan builders L2-L11). This file exists to prove the
surface grammar is unambiguous and that every example in the plan parses, checks
and runs with the stated results.

  python ore.py check FILE              JSON lines: diagnostics, failing tests, summary
  python ore.py run FILE [--allow io,fs,net,time,rand] [--fuel N]
  python ore.py core FILE               per-definition content hash and core size
"""
import sys, json, hashlib, difflib, math, time, random

sys.setrecursionlimit(20000)


class OreError(Exception):
    def __init__(self, code, msg, line=0, col=0, **extra):
        super().__init__(msg)
        self.code, self.msg, self.line, self.col, self.extra = code, msg, line, col, extra

    def out(self):
        d = {"k": "err", "code": self.code}
        if self.line:
            d.update(line=self.line, col=self.col)
        d["msg"] = self.msg
        d.update({k: v for k, v in self.extra.items() if v is not None})
        return d


class Fail(Exception):
    """The `fail` effect. Caught by `catch`; anything else is a hard error."""
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg


class ParseFail(Exception):
    """Speculation backtrack (lambda heads, binding heads)."""


# ---------------------------------------------------------------- lexer
OPS2 = {"..", "=>", "->", ">>", "==", "!=", "<=", ">=", "&&", "||", "++", "**", "//"}
OPS1 = set("+-*/%<>=!|?:.,;()[]{}@")
KW = {"match", "catch", "if", "type", "test"}
BINOPS = {"||", "&&", "==", "!=", "<", "<=", ">", ">=", "..", "++", "+", "-", "*", "/", "//", "%", "**"}


class Tok:
    __slots__ = ("k", "v", "line", "col")

    def __init__(s, k, v, line, col):
        s.k, s.v, s.line, s.col = k, v, line, col


def desc(t):
    if t.k == "NL":
        return "end of line"
    if t.k == "EOF":
        return "end of file"
    if t.k == "STR":
        return "a string"
    return f"'{t.v}'"


def lex(src, line0=1, col0=1):
    toks, i, n = [], 0, len(src)
    line, col = line0, col0

    def adv(k):
        nonlocal i, line, col
        for _ in range(k):
            if src[i] == "\n":
                line, col = line + 1, 1
            else:
                col += 1
            i += 1

    while i < n:
        c = src[i]
        if c == "\n":
            nl, nc = line, col
            adv(1)
            # a new item starts at column 1; indented lines continue the last item
            if i < n and src[i] not in " \t\r\n" and toks and toks[-1].k != "NL":
                toks.append(Tok("NL", "", nl, nc))
            continue
        if c in " \t\r":
            adv(1)
            continue
        if src.startswith(";;", i):
            while i < n and src[i] != "\n":
                adv(1)
            continue
        if c == '"':
            sl, sc = line, col
            adv(1)
            parts, buf = [], []
            while True:
                if i >= n or src[i] == "\n":
                    raise OreError("L002", "unclosed string", sl, sc, fix={"insert": '"', "line": line, "col": col})
                ch = src[i]
                if ch == '"':
                    adv(1)
                    break
                if ch == "\\":
                    e = src[i + 1] if i + 1 < n else ""
                    m = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "$": "$", "r": "\r", "0": "\0"}
                    if e not in m:
                        raise OreError("L003", f"unknown escape \\{e}", line, col)
                    buf.append(m[e])
                    adv(2)
                    continue
                if ch == "$" and i + 1 < n and (src[i + 1] == "{" or src[i + 1].islower()):
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    if src[i + 1] == "{":
                        el, ec = line, col + 2
                        adv(2)
                        depth, start = 1, i
                        while depth:
                            if i >= n or src[i] == "\n":
                                raise OreError("L004", "unclosed ${ in string", el, ec, fix={"insert": "}", "line": line, "col": col})
                            if src[i] == "{":
                                depth += 1
                            elif src[i] == "}":
                                depth -= 1
                            if depth:
                                adv(1)
                        parts.append(("expr", src[start:i], el, ec))
                        adv(1)
                    else:
                        el, ec = line, col + 1
                        adv(1)
                        start = i
                        while i < n and (src[i].isalnum() or src[i] == "_"):
                            adv(1)
                        parts.append(("expr", src[start:i], el, ec))
                    continue
                buf.append(ch)
                adv(1)
            if buf or not parts:
                parts.append("".join(buf))
            toks.append(Tok("STR", parts, sl, sc))
            continue
        if c.isdigit():
            sl, sc, start = line, col, i
            int_only = bool(toks) and toks[-1].k == "OP" and toks[-1].v == "."  # t.0.1 is two slots
            if src.startswith(("0x", "0X"), i):
                adv(2)
                while i < n and (src[i] in "0123456789abcdefABCDEF_"):
                    adv(1)
                toks.append(Tok("INT", int(src[start + 2:i].replace("_", ""), 16), sl, sc))
                continue
            while i < n and (src[i].isdigit() or src[i] == "_"):
                adv(1)
            isf = False
            if not int_only and i + 1 < n and src[i] == "." and src[i + 1].isdigit():
                isf = True
                adv(1)
                while i < n and (src[i].isdigit() or src[i] == "_"):
                    adv(1)
            if not int_only and i < n and src[i] in "eE":
                j = i + 1 + (1 if i + 1 < n and src[i + 1] in "+-" else 0)
                if j < n and src[j].isdigit():
                    isf = True
                    adv(j - i)
                    while i < n and src[i].isdigit():
                        adv(1)
            text = src[start:i].replace("_", "")
            toks.append(Tok("FLOAT", float(text), sl, sc) if isf else Tok("INT", int(text), sl, sc))
            continue
        if c.isalpha() or c == "_":
            sl, sc, start = line, col, i
            while i < n and (src[i].isalnum() or src[i] == "_"):
                adv(1)
            w = src[start:i]
            if w == "_":
                toks.append(Tok("OP", "_", sl, sc))
            elif w in KW:
                toks.append(Tok("KW", w, sl, sc))
            elif w[0].isupper():
                toks.append(Tok("CON", w, sl, sc))
            else:
                toks.append(Tok("NAME", w, sl, sc))
            continue
        two = src[i:i + 2]
        if two in OPS2:
            toks.append(Tok("OP", two, line, col))
            adv(2)
            continue
        if c in OPS1:
            toks.append(Tok("OP", c, line, col))
            adv(1)
            continue
        raise OreError("L001", f"unexpected character {c!r}", line, col)
    toks.append(Tok("EOF", "", line, col))
    return toks


# ---------------------------------------------------------------- parser
LEVELS = [({"||"}, "L"), ({"&&"}, "L"), ({"==", "!=", "<", "<=", ">", ">="}, "N"), ({".."}, "N"),
          ({"++"}, "R"), ({"+", "-"}, "L"), ({"*", "/", "//", "%"}, "L"), ({"**"}, "R")]


class Parser:
    def __init__(self, toks, holes=None, nh=None):
        self.t, self.p = toks, 0
        self.holes = holes if holes is not None else []   # one list per open paren group
        self.nh = nh if nh is not None else [0]
        self.nobrace = 0                                    # inside a match scrutinee

    def peek(self, k=0):
        return self.t[min(self.p + k, len(self.t) - 1)]

    def at(self, kind, v=None):
        t = self.peek()
        return t.k == kind and (v is None or t.v == v)

    def op(self, v):
        return self.at("OP", v)

    def next(self):
        t = self.t[self.p]
        if t.k != "EOF":
            self.p += 1
        return t

    def expect(self, v, opener=None):
        if self.op(v):
            return self.next()
        t = self.peek()
        extra = {}
        if v in (")", "]", "}") and t.k in ("NL", "EOF"):
            extra["fix"] = {"insert": v, "line": t.line, "col": t.col}
        where = f" to close '{opener.v}' at {opener.line}:{opener.col}" if opener else ""
        raise OreError("P002", f"expected '{v}'{where}, found {desc(t)}", t.line, t.col, **extra)

    def attempt(self, fn):
        save, marks = self.p, [len(h) for h in self.holes]
        try:
            return fn()
        except (ParseFail, OreError):
            self.p = save
            for h, m in zip(self.holes, marks):
                del h[m:]
            return None

    # -- items
    def parse_item(self):
        t = self.peek()
        if t.k == "KW" and t.v == "type":
            return self.parse_type()
        if t.k == "KW" and t.v == "test":
            self.next()
            return ("test", self.parse_seq(), t.line)
        if t.k == "NAME":
            if self.peek(1).k == "OP" and self.peek(1).v == ":":
                while not (self.at("NL") or self.at("EOF")):
                    self.next()
                return ("sig", t.v, t.line)
            self.next()
            pats = []
            while self.pat_start():
                pats.append(self.parse_pat_atom())
            guard = None
            if self.at("KW", "if"):
                self.next()
                guard = self.parse_pipe()
            self.expect("=")
            return ("def", t.v, pats, guard, self.parse_seq(), t.line, t.col)
        raise OreError("P007", f"expected a definition (name args = expr), 'type' or 'test'; found {desc(t)}", t.line, t.col)

    def parse_type(self):
        kw = self.next()
        nm = self.peek()
        if nm.k != "CON":
            raise OreError("P009", "a type name starts with a capital letter", nm.line, nm.col)
        self.next()
        while self.at("NAME"):
            self.next()
        self.expect("=")
        if self.op("{"):
            while not (self.at("NL") or self.at("EOF")):
                self.next()
            return ("type", nm.v, [], kw.line)
        cons = []
        while True:
            c = self.peek()
            if c.k != "CON":
                raise OreError("P009", f"expected a constructor (Capitalized), found {desc(c)}", c.line, c.col)
            self.next()
            arity = 0
            while not (self.op("|") or self.at("NL") or self.at("EOF")):
                self.skip_type_atom()
                arity += 1
            cons.append((c.v, arity, c.line, c.col))
            if self.op("|"):
                self.next()
                continue
            return ("type", nm.v, cons, kw.line)

    def skip_type_atom(self):
        t = self.next()
        if t.k == "OP" and t.v in ("(", "[", "{"):
            depth = 1
            while depth:
                u = self.next()
                if u.k in ("NL", "EOF"):
                    raise OreError("P002", "unclosed bracket in type", u.line, u.col)
                if u.k == "OP" and u.v in ("(", "[", "{"):
                    depth += 1
                elif u.k == "OP" and u.v in (")", "]", "}"):
                    depth -= 1
        elif t.k not in ("CON", "NAME"):
            raise OreError("P009", f"unexpected {desc(t)} in type", t.line, t.col)

    # -- expressions, loosest first
    def parse_seq(self):
        head = self.attempt(self.bind_head)
        if head is not None:
            kind, pat, params, t = head
            rhs = self.parse_lam()
            if kind == "fn":
                rhs = ("lam", params, rhs)
            if not self.op(";"):
                u = self.peek()
                raise OreError("P004", "a binding needs '; rest' after it: y = x*2; y+1", u.line, u.col)
            self.next()
            return ("letrec" if kind == "fn" else "let", pat, rhs, self.parse_seq())
        e = self.parse_lam()
        if self.op(";"):
            self.next()
            return ("seq", e, self.parse_seq())
        return e

    def bind_head(self):
        t, save = self.peek(), self.p
        try:
            pat = self.parse_pattern()
            if self.op("="):
                self.next()
                return ("val", pat, None, t)
        except (ParseFail, OreError):
            pass
        self.p = save
        if self.at("NAME"):
            nm = self.next().v
            pats = []
            while self.pat_start():
                pats.append(self.parse_pat_atom())
            if pats and self.op("="):
                self.next()
                return ("fn", ("pvar", nm), pats, t)
        raise ParseFail()

    def lam_head(self):
        pats = []
        while self.pat_start():
            pats.append(self.parse_pat_atom())
        if pats and self.op("=>"):
            self.next()
            return pats
        raise ParseFail()

    def parse_lam(self):
        pats = self.attempt(self.lam_head)
        if pats is not None:
            return ("lam", pats, self.parse_lam())
        return self.parse_catch()

    def parse_catch(self):
        e = self.parse_pipe()
        while self.at("KW", "catch"):
            self.next()
            pats = self.attempt(self.lam_head)
            if pats is not None:
                e = ("catch", e, ("lam", pats, self.parse_lam()), True)
            else:
                e = ("catch", e, self.parse_pipe(), False)
        return e

    def parse_pipe(self):
        e = self.parse_tern()
        while self.op("|") or self.op(">>"):
            o = self.next().v
            r = self.parse_tern()
            e = ("pipe", e, r) if o == "|" else ("comp", e, r)
        return e

    def parse_tern(self):
        c = self.parse_bin(0)
        if self.op("?"):
            self.next()
            a = self.parse_tern()
            self.expect(":")
            return ("if", c, a, self.parse_tern())
        return c

    def parse_bin(self, lvl):
        if lvl == len(LEVELS):
            return self.parse_unary()
        ops, assoc = LEVELS[lvl]
        left = self.parse_bin(lvl + 1)
        while self.peek().k == "OP" and self.peek().v in ops:
            o = self.next()
            if assoc == "R":
                return ("bin", o.v, left, self.parse_bin(lvl))
            right = self.parse_bin(lvl + 1)
            left = ("bin", o.v, left, right)
            if assoc == "N" and self.peek().k == "OP" and self.peek().v in ops:
                u = self.peek()
                raise OreError("P013", f"'{o.v}' does not chain; add parentheses", u.line, u.col)
        return left

    def parse_unary(self):
        if self.op("-"):
            self.next()
            return ("neg", self.parse_unary())
        if self.op("!"):
            self.next()
            return ("not", self.parse_unary())
        return self.parse_app()

    def arg_start(self):
        t = self.peek()
        if t.k in ("NAME", "CON", "INT", "FLOAT", "STR"):
            return True
        if t.k == "OP" and t.v in ("(", "[", "_"):
            return True
        return t.k == "OP" and t.v == "{" and not self.nobrace

    def parse_app(self):
        f = self.parse_post()
        args = []
        while self.arg_start():
            args.append(self.parse_post())
        return ("app", f, args) if args else f

    def parse_post(self):
        e = self.parse_atom()
        while True:
            if self.op(".") and self.peek(1).k == "NAME":
                self.next()
                e = ("field", e, self.next().v)
            elif self.op(".") and self.peek(1).k == "INT":
                self.next()
                e = ("slot", e, self.next().v)
            elif self.op("@"):
                self.next()
                if self.op("-") and self.peek(1).k == "INT":
                    self.next()
                    e = ("index", e, ("int", -self.next().v))
                else:
                    e = ("index", e, self.parse_atom())
            else:
                return e

    def parse_atom(self):
        t = self.peek()
        if t.k == "INT":
            self.next()
            return ("int", t.v)
        if t.k == "FLOAT":
            self.next()
            return ("float", t.v)
        if t.k == "STR":
            self.next()
            return self.str_node(t)
        if t.k == "NAME":
            self.next()
            return ("var", t.v, t.line, t.col)
        if t.k == "CON":
            self.next()
            return ("con", t.v, t.line, t.col)
        if t.k == "KW" and t.v == "match":
            return self.parse_match()
        if t.k == "OP":
            if t.v == "_":
                self.next()
                if not self.holes:
                    raise OreError("P010", "'_' makes a lambda only inside parentheses: (_*2)", t.line, t.col)
                nm = f"%{self.nh[0]}"
                self.nh[0] += 1
                self.holes[-1].append(nm)
                return ("var", nm, t.line, t.col)
            if t.v == "(":
                return self.parse_paren()
            if t.v == "[":
                return self.parse_list()
            if t.v == "{":
                return self.parse_obj()
        raise OreError("P001", f"expected an expression, found {desc(t)}", t.line, t.col)

    def parse_paren(self):
        o = self.next()
        if self.op(")"):
            self.next()
            return ("unit",)
        t, u = self.peek(), self.peek(1)
        if t.k == "OP" and t.v in BINOPS and u.k == "OP" and u.v == ")":
            self.next()
            self.next()
            return ("opfn", t.v)
        saved, self.nobrace = self.nobrace, 0
        self.holes.append([])
        items = [self.parse_seq()]
        while self.op(","):
            self.next()
            items.append(self.parse_seq())
        self.expect(")", o)
        hs = self.holes.pop()
        self.nobrace = saved
        e = items[0] if len(items) == 1 else ("tuple", items)
        return ("lam", [("pvar", h) for h in hs], e) if hs else e

    def parse_list(self):
        o = self.next()
        saved, self.nobrace = self.nobrace, 0
        items = []
        while not self.op("]"):
            if self.op(".."):
                self.next()
                items.append((True, self.parse_lam()))
            else:
                items.append((False, self.parse_lam()))
            if not self.op(","):
                break
            self.next()
        self.expect("]", o)
        self.nobrace = saved
        if len(items) == 1 and not items[0][0] and items[0][1][0] == "bin" and items[0][1][1] == "..":
            raise OreError("P011", "[a..b] is a list holding one range; write a..b", o.line, o.col, fix={"drop_brackets": True})
        return ("list", items)

    def parse_obj(self):
        o = self.next()
        saved, self.nobrace = self.nobrace, 0
        ents = []
        while not self.op("}"):
            t, u = self.peek(), self.peek(1)
            if self.op(".."):
                self.next()
                ents.append(("spread", None, self.parse_lam()))
            elif t.k == "NAME" and u.k == "OP" and u.v == ":":
                self.next()
                self.next()
                ents.append(("field", t.v, self.parse_lam()))
            elif t.k == "NAME" and u.k == "OP" and u.v in (",", "}"):
                self.next()
                ents.append(("field", t.v, ("var", t.v, t.line, t.col)))
            elif t.k in ("STR", "INT", "FLOAT"):
                key = self.parse_atom()
                self.expect(":")
                ents.append(("key", key, self.parse_lam()))
            else:
                raise OreError("P005", "inside braces write name: v, \"key\": v or ..spread", t.line, t.col)
            if not self.op(","):
                break
            self.next()
        self.expect("}", o)
        self.nobrace = saved
        kinds = {k for k, _, _ in ents if k != "spread"}
        if kinds == {"field", "key"}:
            raise OreError("P006", "braces hold record fields (name: v) or map keys (\"k\": v), not both", o.line, o.col)
        kind = "map" if ("key" in kinds or not ents) else ("rec" if kinds else "copy")
        return ("obj", kind, ents)

    def parse_match(self):
        kw = self.next()
        self.nobrace += 1
        scrut = self.parse_pipe()
        self.nobrace -= 1
        o = self.expect("{")
        saved, self.nobrace = self.nobrace, 0
        arms = []
        while not self.op("}"):
            pat = self.parse_pattern()
            guard = None
            if self.at("KW", "if"):
                self.next()
                guard = self.parse_pipe()
            self.expect("=>")
            arms.append((pat, guard, self.parse_seq()))
            if not self.op(","):
                break
            self.next()
        self.expect("}", o)
        self.nobrace = saved
        return ("match", scrut, arms, kw.line, kw.col)

    def str_node(self, t):
        out = []
        for part in t.v:
            if isinstance(part, str):
                out.append(part)
                continue
            _, src, l, c = part
            sub = Parser(lex(src, l, c), self.holes, self.nh)
            e = sub.parse_seq()
            if not sub.at("EOF"):
                raise OreError("P012", "could not read the expression inside ${...}", l, c)
            out.append(e)
        if all(isinstance(p, str) for p in out):
            return ("strlit", "".join(out))
        return ("str", out)

    # -- patterns
    def pat_start(self):
        t = self.peek()
        if t.k in ("NAME", "CON", "INT", "FLOAT"):
            return True
        if t.k == "STR":
            return all(isinstance(p, str) for p in t.v)
        if t.k == "OP" and t.v in ("(", "[", "{", "_"):
            return True
        return t.k == "OP" and t.v == "-" and self.peek(1).k in ("INT", "FLOAT")

    def parse_pattern(self):
        if self.at("CON"):
            t = self.next()
            args = []
            while self.pat_start():
                args.append(self.parse_pat_atom())
            return con_pat(t, args)
        return self.parse_pat_atom()

    def parse_pat_atom(self):
        t = self.peek()
        if t.k == "NAME":
            self.next()
            return ("pvar", t.v)
        if t.k == "CON":
            self.next()
            return con_pat(t, [])
        if t.k in ("INT", "FLOAT"):
            self.next()
            return ("plit", t.v)
        if t.k == "STR" and self.pat_start():
            self.next()
            return ("plit", "".join(t.v))
        if t.k == "OP":
            if t.v == "_":
                self.next()
                return ("pwild",)
            if t.v == "-":
                if self.peek(1).k not in ("INT", "FLOAT"):
                    raise ParseFail()
                self.next()
                return ("plit", -self.next().v)
            if t.v == "(":
                o = self.next()
                if self.op(")"):
                    self.next()
                    return ("punit",)
                ps = [self.parse_pattern()]
                while self.op(","):
                    self.next()
                    ps.append(self.parse_pattern())
                self.expect(")", o)
                return ps[0] if len(ps) == 1 else ("ptuple", ps)
            if t.v == "[":
                o = self.next()
                ps, rest = [], None
                while not self.op("]"):
                    if self.op(".."):
                        self.next()
                        rest = self.parse_pat_atom()
                        break
                    ps.append(self.parse_pattern())
                    if not self.op(","):
                        break
                    self.next()
                self.expect("]", o)
                return ("plist", ps, rest)
            if t.v == "{":
                o = self.next()
                fs = []
                while not self.op("}"):
                    k = self.peek()
                    if k.k != "NAME":
                        raise ParseFail()
                    self.next()
                    if self.op(":"):
                        self.next()
                        fs.append((k.v, self.parse_pattern()))
                    else:
                        fs.append((k.v, ("pvar", k.v)))
                    if not self.op(","):
                        break
                    self.next()
                self.expect("}", o)
                return ("prec", fs)
        raise ParseFail()


def con_pat(t, args):
    if t.v in ("True", "False"):
        if args:
            raise OreError("P008", f"{t.v} takes no fields", t.line, t.col)
        return ("plit", t.v == "True")
    return ("pcon", t.v, args, t.line, t.col)


# ---------------------------------------------------------------- program + name check
ALIASES = {
    "length": "len", "size": "len", "reverse": "rev", "reversed": "rev", "sorted": "sort", "sort_by": "sortby",
    "sortBy": "sortby", "reduce": "fold", "foldl": "fold", "inject": "fold", "select": "filter", "where": "filter",
    "head": "first", "concat": "flat", "flatten": "flat", "flat_map": "flatmap", "flatMap": "flatmap",
    "contains": "has", "includes": "has", "elem": "has", "toLowerCase": "lower", "lowercase": "lower",
    "toUpperCase": "upper", "uppercase": "upper", "strip": "trim", "splitlines": "lines", "toString": "str",
    "show": "str", "parseInt": "int", "parse_int": "int", "toInt": "int", "parseFloat": "float", "toFloat": "float",
    "unique": "uniq", "distinct": "uniq", "nub": "uniq", "enumerate": "enum", "groupBy": "group",
    "group_by": "group", "println": "print", "putStrLn": "print", "puts": "print", "values": "vals",
    "items": "pairs", "entries": "pairs", "insert": "put", "set": "put", "remove": "del", "delete": "del",
    "minimum": "min", "maximum": "max", "min_by": "minby", "max_by": "maxby", "minBy": "minby", "maxBy": "maxby",
    "startswith": "starts", "startsWith": "starts", "endswith": "ends", "endsWith": "ends", "error": "fail",
    "raise": "fail", "throw": "fail", "chunks": "chunk", "windows": "win", "sliding": "win", "mapValues": "mapv",
    "map_values": "mapv", "fromList": "tomap", "dict": "tomap", "to_map": "tomap", "parse": "json",
    "stringify": "tojson", "dumps": "tojson", "loads": "json", "foreach": "map", "each": "map", "product": "prod",
}


class Program:
    def __init__(self, src):
        self.src, self.lines = src, src.split("\n")
        self.errors, self.defs, self.order, self.tests = [], {}, [], []
        self.cons = {"True": 0, "False": 0}
        self.broken = set()
        try:
            toks = lex(src)
        except OreError as e:
            self.errors.append(e)
            return
        P = Parser(toks)
        while True:
            while P.at("NL"):
                P.next()
            if P.at("EOF"):
                break
            first = P.peek()
            try:
                item = P.parse_item()
                if not (P.at("NL") or P.at("EOF")):
                    t = P.peek()
                    raise OreError("P003", f"unexpected {desc(t)}; one item per line, indent to continue", t.line, t.col)
                self.add(item)
            except (OreError, ParseFail) as e:
                if isinstance(e, ParseFail):
                    t = P.peek()
                    e = OreError("P008", f"could not read a pattern at {desc(t)}", t.line, t.col)
                self.errors.append(e)
                if first.k == "NAME":
                    self.broken.add(first.v)
                while not (P.at("NL") or P.at("EOF")):
                    P.next()
        self.check_names()

    def add(self, item):
        k = item[0]
        if k == "def":
            _, nm, pats, guard, body, line, col = item
            if nm in self.defs and len(self.defs[nm][0][0]) != len(pats):
                raise OreError("D001", f"every clause of {nm} takes {len(self.defs[nm][0][0])} arguments", line, col)
            if nm in BUILTINS:
                raise OreError("D002", f"'{nm}' is a library name; pick another", line, col)
            if nm not in self.defs:
                self.defs[nm] = []
                self.order.append(nm)
            self.defs[nm].append((pats, guard, body, line, col))
        elif k == "type":
            for c, ar, line, col in item[2]:
                self.cons[c] = ar
        elif k == "test":
            self.tests.append((item[1], item[2]))

    # -- static name resolution (the real checker also infers types and effects here)
    def check_names(self):
        known = set(self.defs) | set(BUILTINS) | self.broken
        for nm in self.order:
            for pats, guard, body, line, col in self.defs[nm]:
                scope = set()
                for p in pats:
                    self.pvars(p, scope)
                if guard is not None:
                    self.walk(guard, scope, known)
                self.walk(body, scope, known)
        for e, line in self.tests:
            self.walk(e, set(), known)

    def pvars(self, p, out):
        k = p[0]
        if k == "pvar":
            out.add(p[1])
        elif k == "pcon":
            if p[1] not in self.cons:
                self.errors.append(OreError("N002", f"unknown constructor '{p[1]}'", p[3], p[4]))
            elif self.cons[p[1]] != len(p[2]):
                self.errors.append(OreError("N003", f"{p[1]} has {self.cons[p[1]]} fields; the pattern gives {len(p[2])}", p[3], p[4]))
            for q in p[2]:
                self.pvars(q, out)
        elif k == "ptuple":
            for q in p[1]:
                self.pvars(q, out)
        elif k == "plist":
            for q in p[1]:
                self.pvars(q, out)
            if p[2] is not None:
                self.pvars(p[2], out)
        elif k == "prec":
            for _, q in p[1]:
                self.pvars(q, out)
        return out

    def walk(self, n, scope, known):
        k = n[0]
        if k == "var":
            nm = n[1]
            if nm not in scope and nm not in known:
                fix = ALIASES.get(nm) or next(iter(difflib.get_close_matches(nm, list(known | scope), 1, 0.75)), None)
                msg = f"unknown name '{nm}'" + (f"; use '{fix}'" if fix else "")
                self.errors.append(OreError("N001", msg, n[2], n[3], **({"fix": {"replace": nm, "with": fix}} if fix else {})))
        elif k == "con":
            if n[1] not in self.cons:
                self.errors.append(OreError("N002", f"unknown constructor '{n[1]}'", n[2], n[3]))
        elif k == "lam":
            inner = set(scope)
            for p in n[1]:
                self.pvars(p, inner)
            self.walk(n[2], inner, known)
        elif k == "let":
            self.walk(n[2], scope, known)
            self.walk(n[3], self.pvars(n[1], set(scope)), known)
        elif k == "letrec":
            inner = self.pvars(n[1], set(scope))
            self.walk(n[2], inner, known)
            self.walk(n[3], inner, known)
        elif k == "match":
            self.walk(n[1], scope, known)
            for pat, guard, body in n[2]:
                inner = self.pvars(pat, set(scope))
                if guard is not None:
                    self.walk(guard, inner, known)
                self.walk(body, inner, known)
        elif k == "obj":
            for t, key, e in n[2]:
                if t == "key":
                    self.walk(key, scope, known)
                self.walk(e, scope, known)
        elif k == "list":
            for _, e in n[1]:
                self.walk(e, scope, known)
        elif k in ("tuple",):
            for e in n[1]:
                self.walk(e, scope, known)
        elif k == "str":
            for p in n[1]:
                if not isinstance(p, str):
                    self.walk(p, scope, known)
        elif k == "app":
            self.walk(n[1], scope, known)
            for a in n[2]:
                self.walk(a, scope, known)
        elif k in ("seq", "pipe", "comp", "index"):
            self.walk(n[1], scope, known)
            self.walk(n[2], scope, known)
        elif k == "catch":
            self.walk(n[1], scope, known)
            self.walk(n[2], scope, known)
        elif k == "if":
            for e in n[1:4]:
                self.walk(e, scope, known)
        elif k == "bin":
            self.walk(n[2], scope, known)
            self.walk(n[3], scope, known)
        elif k in ("neg", "not", "field", "slot"):
            self.walk(n[1], scope, known)


# ---------------------------------------------------------------- values
class Rec:
    __slots__ = ("d",)

    def __init__(s, d):
        s.d = d

    def __eq__(s, o):
        return isinstance(o, Rec) and s.d == o.d

    def __hash__(s):
        return hash(show(s))


class Con:
    __slots__ = ("n", "a")

    def __init__(s, n, a):
        s.n, s.a = n, a

    def __eq__(s, o):
        return isinstance(o, Con) and s.n == o.n and s.a == o.a

    def __hash__(s):
        return hash(show(s))


class Fn:
    __slots__ = ("ar", "f", "args", "nm")

    def __init__(s, ar, f, args=(), nm="fn"):
        s.ar, s.f, s.args, s.nm = ar, f, args, nm


class Env:
    __slots__ = ("v", "up")

    def __init__(s, v, up):
        s.v, s.up = v, up


def show(v, top=False):
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return v if top else json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ",".join(show(x) for x in v) + "]"
    if isinstance(v, tuple):
        return "(" + ",".join(show(x) for x in v) + ")"
    if isinstance(v, Rec):
        return "{" + ",".join(f"{k}:{show(x)}" for k, x in v.d.items()) + "}"
    if isinstance(v, dict):
        return "{" + ",".join(f"{show(k)}:{show(x)}" for k, x in v.items()) + "}"
    if isinstance(v, Con):
        return v.n + "".join(" " + (f"({show(a)})" if (isinstance(a, Con) and a.a) else show(a)) for a in v.a)
    if isinstance(v, Fn):
        return f"<fn {v.nm}/{v.ar - len(v.args)}>"
    return repr(v)


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def binop(o, a, b):
    if o in ("+", "-", "*", "/", "//", "%", "**", "<", "<=", ">", ">="):
        if o in ("<", "<=", ">", ">=") and isinstance(a, str) and isinstance(b, str):
            pass
        elif not (num(a) and num(b)):
            hint = "; join strings and lists with ++" if o == "+" and isinstance(a, (str, list)) else ""
            raise OreError("R002", f"'{o}' needs numbers, got {show(a)} and {show(b)}{hint}", fix={"replace": "+", "with": "++"} if hint else None)
    try:
        if o == "+": return a + b
        if o == "-": return a - b
        if o == "*": return a * b
        if o == "/": return a / b
        if o == "//": return a // b
        if o == "%": return a % b
        if o == "**": return a ** b
    except ZeroDivisionError:
        raise Fail("division by zero")
    if o == "==": return a == b
    if o == "!=": return a != b
    if o == "<": return a < b
    if o == "<=": return a <= b
    if o == ">": return a > b
    if o == ">=": return a >= b
    if o == "++":
        if isinstance(a, dict) and isinstance(b, dict):
            return {**a, **b}
        return a + b
    if o == "..": return list(range(a, b))
    if o == "&&": return a and b
    if o == "||": return a or b
    raise OreError("R001", f"unknown operator {o}")


# ---------------------------------------------------------------- library (data argument last)
def _nonempty(xs, nm):
    if not xs:
        raise Fail(f"{nm}: empty")
    return xs


def _idx(xs, i):
    try:
        return xs[i]
    except IndexError:
        raise Fail(f"index {i} out of range (len {len(xs)})")


def _get(I, k, m):
    try:
        return m.d[k] if isinstance(m, Rec) else m[k]
    except (KeyError, IndexError):
        raise Fail(f"get: no {show(k)}")


def _find(I, f, xs):
    for x in xs:
        if I.truth(I.apply(f, [x])):
            return x
    raise Fail("find: none")


def _fold(I, f, acc, xs):
    for x in xs:
        acc = I.apply(f, [acc, x])
    return acc


def _scan(I, f, acc, xs):
    out = []
    for x in xs:
        acc = I.apply(f, [acc, x])
        out.append(acc)
    return out


def _uniq(I, xs):
    out, seen = [], []
    for x in xs:
        if x not in seen:
            seen.append(x)
            out.append(x)
    return out


def _group(I, f, xs):
    d = {}
    for x in xs:
        d.setdefault(I.apply(f, [x]), []).append(x)
    return d


def _count(I, xs):
    d = {}
    for x in xs:
        d[x] = d.get(x, 0) + 1
    return d


def _int(I, x):
    if isinstance(x, float):
        return int(x)
    try:
        return int(x.strip())
    except (ValueError, AttributeError):
        raise Fail(f"int: not a whole number: {show(x)}")


def _float(I, x):
    try:
        return float(x.strip()) if isinstance(x, str) else float(x)
    except ValueError:
        raise Fail(f"float: not a number: {show(x)}")


def _round(I, x):
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def _sqrt(I, x):
    if x < 0:
        raise Fail("sqrt of a negative number")
    return math.sqrt(x)


def _fail(I, m):
    raise Fail(show(m, True))


def _print(I, x):
    print(show(x, True))
    return ()


def _read(I, p):
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise Fail(f"read: {e.strerror}: {p}")


def _write(I, p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)
    return ()


def _http(I, url):
    raise Fail("http: the spike host has no network; the Rust host provides ore:net/http")


def _json(I, s):
    try:
        return json.loads(s, object_hook=Rec)
    except ValueError as e:
        raise Fail(f"json: {e}")


def _plain(v):
    if isinstance(v, Rec):
        return {k: _plain(x) for k, x in v.d.items()}
    if isinstance(v, dict):
        return {show(k, True): _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, Con):
        return {"tag": v.n, "args": [_plain(x) for x in v.a]}
    return v


BUILTINS = {
    "map": (2, lambda I, f, xs: [I.apply(f, [x]) for x in xs], None),
    "filter": (2, lambda I, f, xs: [x for x in xs if I.truth(I.apply(f, [x]))], None),
    "fold": (3, _fold, None),
    "scan": (3, _scan, None),
    "sum": (1, lambda I, xs: sum(xs), None),
    "prod": (1, lambda I, xs: math.prod(xs), None),
    "len": (1, lambda I, c: len(c.d if isinstance(c, Rec) else c), None),
    "rev": (1, lambda I, c: c[::-1], None),
    "sort": (1, lambda I, xs: sorted(xs), None),
    "sortby": (2, lambda I, f, xs: sorted(xs, key=lambda x: I.apply(f, [x])), None),
    "take": (2, lambda I, k, xs: xs[:max(k, 0)], None),
    "drop": (2, lambda I, k, xs: xs[max(k, 0):], None),
    "zip": (2, lambda I, a, b: list(zip(a, b)), None),
    "enum": (1, lambda I, xs: list(enumerate(xs)), None),
    "any": (2, lambda I, f, xs: any(I.truth(I.apply(f, [x])) for x in xs), None),
    "all": (2, lambda I, f, xs: all(I.truth(I.apply(f, [x])) for x in xs), None),
    "find": (2, _find, None),
    "first": (1, lambda I, xs: _nonempty(xs, "first")[0], None),
    "last": (1, lambda I, xs: _nonempty(xs, "last")[-1], None),
    "min": (1, lambda I, xs: min(_nonempty(xs, "min")), None),
    "max": (1, lambda I, xs: max(_nonempty(xs, "max")), None),
    "minby": (2, lambda I, f, xs: min(_nonempty(xs, "minby"), key=lambda x: I.apply(f, [x])), None),
    "maxby": (2, lambda I, f, xs: max(_nonempty(xs, "maxby"), key=lambda x: I.apply(f, [x])), None),
    "uniq": (1, _uniq, None),
    "flat": (1, lambda I, xss: [x for xs in xss for x in xs], None),
    "flatmap": (2, lambda I, f, xs: [y for x in xs for y in I.apply(f, [x])], None),
    "group": (2, _group, None),
    "count": (1, _count, None),
    "chunk": (2, lambda I, k, xs: [xs[i:i + k] for i in range(0, len(xs), k)], None),
    "win": (2, lambda I, k, xs: [xs[i:i + k] for i in range(0, len(xs) - k + 1)], None),
    "join": (2, lambda I, sep, xs: sep.join(show(x, True) for x in xs), None),
    "has": (2, lambda I, x, c: x in (c.d if isinstance(c, Rec) else c), None),
    "at": (2, lambda I, i, xs: _idx(xs, i), None),
    "range": (2, lambda I, a, b: list(range(a, b)), None),
    "words": (1, lambda I, s: s.split(), None),
    "lines": (1, lambda I, s: s.splitlines(), None),
    "split": (2, lambda I, sep, s: s.split(sep), None),
    "trim": (1, lambda I, s: s.strip(), None),
    "lower": (1, lambda I, s: s.lower(), None),
    "upper": (1, lambda I, s: s.upper(), None),
    "chars": (1, lambda I, s: list(s), None),
    "str": (1, lambda I, x: show(x, True), None),
    "int": (1, _int, None),
    "float": (1, _float, None),
    "starts": (2, lambda I, p, s: s.startswith(p), None),
    "ends": (2, lambda I, p, s: s.endswith(p), None),
    "replace": (3, lambda I, a, b, s: s.replace(a, b), None),
    "keys": (1, lambda I, m: list((m.d if isinstance(m, Rec) else m).keys()), None),
    "vals": (1, lambda I, m: list((m.d if isinstance(m, Rec) else m).values()), None),
    "pairs": (1, lambda I, m: list((m.d if isinstance(m, Rec) else m).items()), None),
    "get": (2, _get, None),
    "put": (3, lambda I, k, v, m: {**m, k: v}, None),
    "del": (2, lambda I, k, m: {a: b for a, b in m.items() if a != k}, None),
    "tomap": (1, lambda I, ps: dict(ps), None),
    "mapv": (2, lambda I, f, m: {k: I.apply(f, [v]) for k, v in m.items()}, None),
    "abs": (1, lambda I, x: abs(x), None),
    "sqrt": (1, _sqrt, None),
    "floor": (1, lambda I, x: math.floor(x), None),
    "ceil": (1, lambda I, x: math.ceil(x), None),
    "round": (1, _round, None),
    "id": (1, lambda I, x: x, None),
    "fail": (1, _fail, None),
    "json": (1, _json, None),
    "tojson": (1, lambda I, v: json.dumps(_plain(v), separators=(",", ":"), ensure_ascii=False), None),
    "print": (1, _print, "io"),
    "stdin": (0, lambda I: sys.stdin.read(), "io"),
    "read": (1, _read, "fs"),
    "write": (2, _write, "fs"),
    "http": (1, _http, "net"),
    "now": (0, lambda I: time.time(), "time"),
    "rand": (0, lambda I: random.random(), "rand"),
}


# ---------------------------------------------------------------- evaluator
class Interp:
    def __init__(self, prog, allow=(), fuel=None):
        self.prog, self.allow, self.fuel = prog, set(allow), fuel
        self.globals, self.cafs = {}, {}
        for nm in prog.order:
            clauses = prog.defs[nm]
            if not clauses[0][0]:
                self.cafs[nm] = clauses[0]
            else:
                self.globals[nm] = Fn(len(clauses[0][0]), self.make_def(nm, clauses), (), nm)
        for c, ar in prog.cons.items():
            if c in ("True", "False"):
                self.globals[c] = c == "True"
            elif ar == 0:
                self.globals[c] = Con(c, [])
            else:
                self.globals[c] = Fn(ar, (lambda c: lambda *a: Con(c, list(a)))(c), (), c)

    def tick(self):
        if self.fuel is not None:
            self.fuel -= 1
            if self.fuel < 0:
                raise OreError("C002", "out of fuel; the host's step limit stopped the program")

    def cap(self, eff, nm):
        if eff and eff not in self.allow:
            raise OreError("C001", f"'{nm}' needs the {eff} capability; the host did not grant it (run with --allow {eff})")

    def truth(self, v):
        if not isinstance(v, bool):
            raise OreError("R003", f"a condition must be True or False, got {show(v)}")
        return v

    def make_def(self, nm, clauses):
        def f(*vals):
            for pats, guard, body, line, col in clauses:
                env = Env({}, None)
                if all(self.bind(p, v, env.v) for p, v in zip(pats, vals)):
                    if guard is None or self.truth(self.ev(guard, env)):
                        return self.ev(body, env)
            raise Fail(f"{nm}: no clause matches {' '.join(show(v) for v in vals)}")
        return f

    def builtin(self, nm):
        ar, fn, eff = BUILTINS[nm]

        def call(*a):
            self.cap(eff, nm)
            try:
                return fn(self, *a)
            except (TypeError, AttributeError) as e:
                raise OreError("R001", f"{nm}: wrong kind of argument ({e}); the type checker rejects this before run")
        if ar == 0:
            return call()
        f = Fn(ar, call, (), nm)
        self.globals[nm] = f
        return f

    def lookup(self, nm, env):
        e = env
        while e is not None:
            if nm in e.v:
                return e.v[nm]
            e = e.up
        if nm in self.globals:
            return self.globals[nm]
        if nm in self.cafs:
            pats, guard, body, line, col = self.cafs.pop(nm)
            v = self.globals[nm] = self.ev(body, Env({}, None))
            return v
        if nm in BUILTINS:
            return self.builtin(nm)
        raise OreError("N001", f"unknown name '{nm}'")

    def apply(self, f, args):
        args = list(args)
        while args:
            if not isinstance(f, Fn):
                raise OreError("R001", f"{show(f)} is not a function; it was given {len(args)} more argument(s)")
            need = f.ar - len(f.args)
            if len(args) < need:
                return Fn(f.ar, f.f, f.args + tuple(args), f.nm)
            self.tick()
            f, args = f.f(*(f.args + tuple(args[:need]))), args[need:]
        return f

    def bind(self, p, v, out):
        k = p[0]
        if k == "pwild":
            return True
        if k == "pvar":
            out[p[1]] = v
            return True
        if k == "plit":
            return isinstance(v, bool) == isinstance(p[1], bool) and v == p[1]
        if k == "punit":
            return v == ()
        if k == "ptuple":
            return isinstance(v, tuple) and len(v) == len(p[1]) and all(self.bind(q, x, out) for q, x in zip(p[1], v))
        if k == "pcon":
            return isinstance(v, Con) and v.n == p[1] and len(v.a) == len(p[2]) and all(self.bind(q, x, out) for q, x in zip(p[2], v.a))
        if k == "plist":
            ps, rest = p[1], p[2]
            if not isinstance(v, list):
                return False
            if rest is None:
                return len(v) == len(ps) and all(self.bind(q, x, out) for q, x in zip(ps, v))
            return len(v) >= len(ps) and all(self.bind(q, x, out) for q, x in zip(ps, v)) and self.bind(rest, v[len(ps):], out)
        if k == "prec":
            return isinstance(v, Rec) and all(f in v.d and self.bind(q, v.d[f], out) for f, q in p[1])
        raise OreError("R001", f"bad pattern {k}")

    def lam(self, pats, body, env, nm="lambda"):
        def f(*vals):
            e = Env({}, env)
            for p, v in zip(pats, vals):
                if not self.bind(p, v, e.v):
                    raise Fail(f"{nm}: argument does not match: {show(v)}")
            return self.ev(body, e)
        return Fn(len(pats), f, (), nm)

    def ev(self, n, env):
        k = n[0]
        if k in ("int", "float", "strlit"):
            return n[1]
        if k == "var":
            return self.lookup(n[1], env)
        if k == "con":
            return self.globals[n[1]]
        if k == "app":
            f = self.ev(n[1], env)
            return self.apply(f, [self.ev(a, env) for a in n[2]])
        if k == "pipe":
            x = self.ev(n[1], env)
            return self.apply(self.ev(n[2], env), [x])
        if k == "comp":
            f, g = self.ev(n[1], env), self.ev(n[2], env)
            return Fn(1, lambda x: self.apply(g, [self.apply(f, [x])]), (), "compose")
        if k == "lam":
            return self.lam(n[1], n[2], env)
        if k == "let":
            v = self.ev(n[2], env)
            e = Env({}, env)
            if not self.bind(n[1], v, e.v):
                raise Fail(f"binding does not match {show(v)}")
            return self.ev(n[3], e)
        if k == "letrec":
            e = Env({}, env)
            e.v[n[1][1]] = self.ev(n[2], e)
            return self.ev(n[3], e)
        if k == "seq":
            self.ev(n[1], env)
            return self.ev(n[2], env)
        if k == "catch":
            try:
                return self.ev(n[1], env)
            except Fail as x:
                h = self.ev(n[2], env)
                return self.apply(h, [x.msg]) if n[3] else h
        if k == "if":
            return self.ev(n[2] if self.truth(self.ev(n[1], env)) else n[3], env)
        if k == "bin":
            o = n[1]
            if o == "&&":
                return self.truth(self.ev(n[2], env)) and self.truth(self.ev(n[3], env))
            if o == "||":
                return self.truth(self.ev(n[2], env)) or self.truth(self.ev(n[3], env))
            return binop(o, self.ev(n[2], env), self.ev(n[3], env))
        if k == "neg":
            return binop("-", 0, self.ev(n[1], env))
        if k == "not":
            return not self.truth(self.ev(n[1], env))
        if k == "field":
            v = self.ev(n[1], env)
            if isinstance(v, Rec) and n[2] in v.d:
                return v.d[n[2]]
            raise OreError("R004", f"no field '{n[2]}' on {show(v)}")
        if k == "slot":
            v = self.ev(n[1], env)
            if isinstance(v, tuple) and n[2] < len(v):
                return v[n[2]]
            raise OreError("R004", f"no slot .{n[2]} on {show(v)}")
        if k == "index":
            return _idx(self.ev(n[1], env), self.ev(n[2], env))
        if k == "tuple":
            return tuple(self.ev(e, env) for e in n[1])
        if k == "unit":
            return ()
        if k == "list":
            out = []
            for spread, e in n[1]:
                v = self.ev(e, env)
                if spread:
                    out.extend(v)
                else:
                    out.append(v)
            return out
        if k == "obj":
            kind, ents = n[1], n[2]
            spreads = [self.ev(e, env) if t == "spread" else None for t, _, e in ents]
            as_map = kind == "map" or (kind == "copy" and all(isinstance(s, dict) for s in spreads if s is not None))
            d = {}
            for (t, key, e), sv in zip(ents, spreads):
                if t == "spread":
                    d.update(sv if isinstance(sv, dict) else sv.d)
                elif t == "key":
                    d[self.ev(key, env)] = self.ev(e, env)
                else:
                    d[key] = self.ev(e, env)
            return d if as_map else Rec(d)
        if k == "str":
            return "".join(p if isinstance(p, str) else show(self.ev(p, env), True) for p in n[1])
        if k == "match":
            v = self.ev(n[1], env)
            for pat, guard, body in n[2]:
                e = Env({}, env)
                if self.bind(pat, v, e.v) and (guard is None or self.truth(self.ev(guard, e))):
                    return self.ev(body, e)
            raise Fail(f"match at {n[3]}:{n[4]}: no arm for {show(v)}")
        if k == "opfn":
            return Fn(2, lambda a, b, o=n[1]: binop(o, a, b), (), n[1])
        raise OreError("R001", f"unknown node {k}")


# ---------------------------------------------------------------- core encoding (names erased, content hashed)
TAGS = {t: i for i, t in enumerate(
    "int float str interp local global self group builtin con app lam let letrec seq catch if bin neg not "
    "field slot index tuple unit list spread obj match opfn pwild pbind plit punit ptuple pcon plist prec".split())}
OPCODES = {o: i for i, o in enumerate(sorted(BINOPS | {">>"}))}
BUILTIN_IDS = {nm: i for i, nm in enumerate(BUILTINS)}


def uvar(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def svar(n):
    return uvar((n << 1) ^ (n >> 63) if n >= 0 else ((-n) << 1) - 1)


def sbytes(s):
    b = s.encode("utf-8")
    return uvar(len(b)) + b


class Encoder:
    """One definition (or one recursive group) to bytes. Locals are de Bruijn indices,
    globals point into a dependency table of 32-byte hashes, library calls are opcodes."""

    def __init__(self, prog, hashes, group):
        self.prog, self.hashes, self.group, self.deps = prog, hashes, group, []

    def ref(self, nm, scope):
        if nm in scope:
            return bytes([TAGS["local"]]) + uvar(scope[::-1].index(nm))
        if nm in self.group:
            return bytes([TAGS["self" if len(self.group) == 1 else "group"]]) + uvar(self.group.index(nm))
        if nm in self.prog.defs:
            h = self.hashes[nm]
            if h not in self.deps:
                self.deps.append(h)
            return bytes([TAGS["global"]]) + uvar(self.deps.index(h))
        return bytes([TAGS["builtin"]]) + uvar(BUILTIN_IDS[nm])

    def pat(self, p, scope):
        k = p[0]
        T = lambda t: bytes([TAGS[t]])
        if k == "pwild": return T("pwild")
        if k == "pvar":
            scope.append(p[1])
            return T("pbind")
        if k == "plit": return T("plit") + self.lit(p[1])
        if k == "punit": return T("punit")
        if k == "ptuple": return T("ptuple") + uvar(len(p[1])) + b"".join(self.pat(q, scope) for q in p[1])
        if k == "pcon": return T("pcon") + sbytes(p[1]) + uvar(len(p[2])) + b"".join(self.pat(q, scope) for q in p[2])
        if k == "plist":
            head = T("plist") + uvar(len(p[1])) + b"".join(self.pat(q, scope) for q in p[1])
            return head + (b"\x00" if p[2] is None else b"\x01" + self.pat(p[2], scope))
        if k == "prec": return T("prec") + uvar(len(p[1])) + b"".join(sbytes(f) + self.pat(q, scope) for f, q in p[1])
        raise ValueError(k)

    def lit(self, v):
        if isinstance(v, bool): return bytes([TAGS["con"]]) + sbytes("True" if v else "False")
        if isinstance(v, int): return bytes([TAGS["int"]]) + svar(v)
        if isinstance(v, float): return bytes([TAGS["float"]]) + __import__("struct").pack("<d", v)
        return bytes([TAGS["str"]]) + sbytes(v)

    def e(self, n, scope):
        T = lambda t: bytes([TAGS[t]])
        k = n[0]
        if k in ("int", "float", "strlit"): return self.lit(n[1])
        if k == "var": return self.ref(n[1], scope)
        if k == "con": return self.lit(n[1] == "True") if n[1] in ("True", "False") else T("con") + sbytes(n[1])
        if k == "app": return T("app") + uvar(len(n[2])) + self.e(n[1], scope) + b"".join(self.e(a, scope) for a in n[2])
        if k == "pipe": return T("app") + uvar(1) + self.e(n[2], scope) + self.e(n[1], scope)
        if k == "comp": return T("bin") + bytes([OPCODES[">>"]]) + self.e(n[1], scope) + self.e(n[2], scope)
        if k == "lam":
            inner = list(scope)
            ps = b"".join(self.pat(p, inner) for p in n[1])
            return T("lam") + uvar(len(n[1])) + ps + self.e(n[2], inner)
        if k == "let":
            rhs = self.e(n[2], scope)
            inner = list(scope)
            return T("let") + self.pat(n[1], inner) + rhs + self.e(n[3], inner)
        if k == "letrec":
            inner = list(scope) + [n[1][1]]
            return T("letrec") + self.e(n[2], inner) + self.e(n[3], inner)
        if k == "seq": return T("seq") + self.e(n[1], scope) + self.e(n[2], scope)
        if k == "catch": return T("catch") + bytes([n[3]]) + self.e(n[1], scope) + self.e(n[2], scope)
        if k == "if": return T("if") + b"".join(self.e(x, scope) for x in n[1:4])
        if k == "bin": return T("bin") + bytes([OPCODES[n[1]]]) + self.e(n[2], scope) + self.e(n[3], scope)
        if k in ("neg", "not"): return T(k) + self.e(n[1], scope)
        if k == "field": return T("field") + sbytes(n[2]) + self.e(n[1], scope)
        if k == "slot": return T("slot") + uvar(n[2]) + self.e(n[1], scope)
        if k == "index": return T("index") + self.e(n[1], scope) + self.e(n[2], scope)
        if k == "tuple": return T("tuple") + uvar(len(n[1])) + b"".join(self.e(x, scope) for x in n[1])
        if k == "unit": return T("unit")
        if k == "list": return T("list") + uvar(len(n[1])) + b"".join((T("spread") if s else b"") + self.e(x, scope) for s, x in n[1])
        if k == "obj":
            body = b"".join(bytes([("spread", "field", "key").index(t)]) + (sbytes(key) if t == "field" else self.e(key, scope) if t == "key" else b"") + self.e(x, scope) for t, key, x in n[2])
            return T("obj") + bytes([("map", "rec", "copy").index(n[1])]) + uvar(len(n[2])) + body
        if k == "str": return T("interp") + uvar(len(n[1])) + b"".join(self.lit(p) if isinstance(p, str) else self.e(p, scope) for p in n[1])
        if k == "match":
            arms = b""
            for pat, guard, body in n[2]:
                inner = list(scope)
                pb = self.pat(pat, inner)
                arms += pb + (b"\x00" if guard is None else b"\x01" + self.e(guard, inner)) + self.e(body, inner)
            return T("match") + uvar(len(n[2])) + self.e(n[1], scope) + arms
        if k == "opfn": return T("opfn") + bytes([OPCODES[n[1]]])
        raise ValueError(k)

    def definition(self, nm):
        out = b""
        for pats, guard, body, line, col in self.prog.defs[nm]:
            scope = []
            ps = b"".join(self.pat(p, scope) for p in pats)
            out += uvar(len(pats)) + ps + (b"\x00" if guard is None else b"\x01" + self.e(guard, scope)) + self.e(body, scope)
        return uvar(len(self.prog.defs[nm])) + out


def def_deps(prog, nm):
    found = set()

    def walk(x):
        if isinstance(x, tuple):
            if x and x[0] == "var" and x[1] in prog.defs:
                found.add(x[1])
            for y in x:
                walk(y)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(prog.defs[nm])
    return found


def sccs(prog):
    index, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def visit(v):
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(def_deps(prog, v)):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))
    for v in prog.order:
        if v not in index:
            visit(v)
    return out  # dependencies first


def core(prog):
    hashes, rows = {}, []
    for group in sccs(prog):
        encs = {}
        for nm in group:
            enc = Encoder(prog, hashes, group)
            encs[nm] = (enc.definition(nm), enc.deps)
        gh = hashlib.blake2b(b"".join(b + b"".join(d) for b, d in (encs[n] for n in group)), digest_size=32).digest()
        for i, nm in enumerate(group):
            body, deps = encs[nm]
            h = hashlib.blake2b(gh + uvar(i), digest_size=32).digest() if len(group) > 1 else \
                hashlib.blake2b(body + b"".join(deps), digest_size=32).digest()
            hashes[nm] = h
            src_lines = sorted({c[3] for c in prog.defs[nm]})
            src_bytes = sum(len(prog.lines[l - 1].encode()) for l in src_lines)
            rows.append({"name": nm, "hash": h.hex()[:16], "core_bytes": len(body), "deps": len(deps), "src_bytes": src_bytes})
    return rows


# ---------------------------------------------------------------- driver
def emit(d):
    print(json.dumps(d, ensure_ascii=False, separators=(",", ":")))


def check(prog, quiet_pass=True):
    for e in prog.errors:
        emit(e.out())
    if prog.errors:
        emit({"k": "fail", "errors": len(prog.errors)})
        return False
    I = Interp(prog)
    passed = 0
    for e, line in prog.tests:
        rec = {"k": "test", "line": line, "src": prog.lines[line - 1].strip()}
        try:
            if e[0] == "bin" and e[1] == "==":
                a, b = I.ev(e[2], None), I.ev(e[3], None)
                ok = a == b
                if not ok:
                    rec.update(left=show(a), right=show(b))
            else:
                v = I.ev(e, None)
                ok = v is True
                if not ok:
                    rec["got"] = show(v)
        except Fail as x:
            ok, rec["fail"] = False, x.msg
        except OreError as x:
            ok = False
            rec.update(code=x.code, msg=x.msg)
        rec["ok"] = ok
        passed += ok
        if not ok or not quiet_pass:
            emit(rec)
    emit({"k": "ok" if passed == len(prog.tests) else "fail", "defs": len(prog.defs), "tests": len(prog.tests), "passed": passed})
    return passed == len(prog.tests)


def main(argv):
    if len(argv) < 2 or argv[0] not in ("check", "run", "core"):
        print(__doc__)
        return 2
    cmd, path = argv[0], argv[1]
    allow, fuel = [], None
    if "--allow" in argv:
        allow = argv[argv.index("--allow") + 1].split(",")
    if "--fuel" in argv:
        fuel = int(argv[argv.index("--fuel") + 1])
    with open(path, encoding="utf-8") as f:
        prog = Program(f.read())
    if cmd == "check":
        return 0 if check(prog, quiet_pass="-v" not in argv) else 1
    if prog.errors:
        for e in prog.errors:
            emit(e.out())
        return 1
    if cmd == "core":
        for r in core(prog):
            emit(r)
        return 0
    if "main" not in prog.defs:
        emit({"k": "err", "code": "D003", "msg": "no main"})
        return 1
    try:
        Interp(prog, allow, fuel).lookup("main", None)
    except OreError as e:
        emit(e.out())
        return 1
    except Fail as x:
        emit({"k": "fail", "msg": x.msg})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
