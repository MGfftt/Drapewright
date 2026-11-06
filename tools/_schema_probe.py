import json, collections, io, sys
sys.stdout.reconfigure(encoding="utf-8")
p = "ChatGarment-main/docs/all_float_paths.json"
paths = json.load(open(p, encoding="utf-8"))
print("COUNT", len(paths))
top = collections.OrderedDict()
for i, s in enumerate(paths):
    parts = s.split(".")
    key = parts[1] if len(parts) > 1 else "?"
    top.setdefault(key, []).append((i, ".".join(parts[2:])))
for k, v in top.items():
    print("--", k, len(v))
    for i, sub in v:
        print("   [%2d] %s" % (i, sub))
