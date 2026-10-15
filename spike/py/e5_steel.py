WT = {"W8x10": 10, "W10x22": 22, "W12x26": 26}
def tons(csv):
    lbs = {}
    for line in csv.splitlines()[1:]:
        _, shape, ft, qty = line.split(",")
        lbs[shape] = lbs.get(shape, 0) + WT[shape] * float(ft) * int(qty)
    return {k: v / 2000 for k, v in lbs.items()}
