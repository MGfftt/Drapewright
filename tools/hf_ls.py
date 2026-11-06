import json, sys, urllib.request

repo = sys.argv[1]
kind = sys.argv[2] if len(sys.argv) > 2 else "model"
host = "https://hf-mirror.com"
url = f"{host}/api/{'datasets/' if kind=='dataset' else ''}{repo}/tree/main?recursive=true"
data = json.load(urllib.request.urlopen(url, timeout=60))
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
