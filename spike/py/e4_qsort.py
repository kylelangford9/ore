def qs(xs):
    if not xs:
        return []
    p, *t = xs
    return qs([x for x in t if x < p]) + [p] + qs([x for x in t if x >= p])
