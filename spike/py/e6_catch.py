def safe(s):
    try:
        return int(s)
    except ValueError:
        return 0
def pos(n):
    if n > 0:
        return n
    raise ValueError("not positive")
