"""Token counts for the plan: each Ore example (definitions only) against its Python twin,
plus the spec card. Uses OpenAI's o200k_base BPE as a stand-in tokenizer; builder L1 re-runs
this with the Claude token counting endpoint."""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
# tiktoken is vendored outside the repo (pip install --target "D:\Build Artifacts\ore\_vendor" tiktoken)
sys.path.insert(0, os.environ.get("ORE_VENDOR", r"D:\Build Artifacts\ore\_vendor"))
import tiktoken  # noqa: E402

enc = tiktoken.get_encoding("o200k_base")
NAMES = ["e1_top3", "e2_fib", "e3_shapes", "e4_qsort", "e5_steel", "e6_catch", "e7_main", "e8_json"]


def ore_defs(path):
    keep = []
    for line in open(path, encoding="utf-8").read().splitlines():
        s = line.strip()
        if not s or s.startswith(";;") or line.startswith("test "):
            continue
        keep.append(line)
    return "\n".join(keep)


rows = []
for n in NAMES:
    o = ore_defs(os.path.join(HERE, "examples", n + ".ore"))
    p = open(os.path.join(HERE, "py", n + ".py"), encoding="utf-8").read().strip()
    to, tp = len(enc.encode(o)), len(enc.encode(p))
    rows.append({"ex": n, "ore_tok": to, "py_tok": tp, "ratio": round(to / tp, 2), "ore_chars": len(o), "py_chars": len(p)})
card = open(os.path.join(HERE, "SPEC-CARD.txt"), encoding="utf-8").read()
tot_o, tot_p = sum(r["ore_tok"] for r in rows), sum(r["py_tok"] for r in rows)
ratios = sorted(r["ratio"] for r in rows)
summary = {"total_ore": tot_o, "total_py": tot_p, "ratio_total": round(tot_o / tot_p, 2),
           "ratio_median": round((ratios[3] + ratios[4]) / 2, 2), "spec_card_tokens": len(enc.encode(card)),
           "tokenizer": "o200k_base (stand-in)"}
for r in rows:
    print(json.dumps(r))
print(json.dumps(summary))
