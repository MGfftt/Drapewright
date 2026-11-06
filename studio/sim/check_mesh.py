import numpy as np, collections
p = r"C:/Users/41239/Desktop/科研/ChatGarment-main/studio/runs/smoke1/mesh/smoke1_garment.obj"
V, F = [], []
for line in open(p):
    if line.startswith("v "):
        V.append([float(x) for x in line.split()[1:4]])
    elif line.startswith("f "):
        idx = [int(t.split("/")[0]) - 1 for t in line.split()[1:]]
        for k in range(1, len(idx) - 1):
            F.append([idx[0], idx[k], idx[k + 1]])
V = np.array(V); F = np.array(F)
print("verts", len(V), "faces", len(F))
key = np.round(V, 4)
uniq = np.unique(key, axis=0)
print("unique positions", len(uniq), "duplicate verts", len(V) - len(uniq))
edges = collections.Counter()
for tri in F:
    for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
        edges[(min(a, b), max(a, b))] += 1
boundary = [e for e, c in edges.items() if c == 1]
print("boundary edges", len(boundary))
sel = set()
for a, b in boundary:
    sel.add(a); sel.add(b)
print("boundary verts", len(sel))
dup = sum(1 for v in sel if len(np.where((key == key[v]).all(axis=1))[0]) > 1)
print("boundary verts sharing their position with another vertex:", dup)
