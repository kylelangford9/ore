import json
def totals(s):
    out = {}
    for i in json.loads(s):
        out[i["code"]] = out.get(i["code"], 0) + i["qty"] * i["rate"]
    return out
