import json, sys
path = sys.argv[1]
data = json.load(open(path, encoding="utf-8"))
total = 0
rows = []
for e in data:
    if e.get("type") != "file":
        continue
    sz = e.get("size", 0) or 0
    total += sz
    rows.append((sz, e["path"]))
rows.sort(reverse=True)
for sz, p in rows:
    print(f"{sz/1e9:9.3f} GB  {p}")
print(f"\nTOTAL {total/1e9:.2f} GB  ({len(rows)} files)")
