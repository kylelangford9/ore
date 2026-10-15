from collections import Counter
def top3(s):
    return [w for w, _ in Counter(s.lower().split()).most_common(3)]
