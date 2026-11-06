
import json, numpy as np, os
pkg='studio/runs/smoke2'
g=json.load(open(pkg+'/mesh/smoke2_groups.json'))
V=[]
for line in open(pkg+'/mesh/smoke2_garment.obj'):
    if line.startswith('v '):
        V.append([float(x) for x in line.split()[1:4]])
V=np.array(V)
for name,ids in g['panels'].items():
    P=V[ids]
    print(f"{name:14s} n={len(ids):5d} x[{P[:,0].min():7.1f},{P[:,0].max():7.1f}] y[{P[:,1].min():7.1f},{P[:,1].max():7.1f}] z[{P[:,2].min():7.1f},{P[:,2].max():7.1f}]")
# waist seam verts z
w=[]
for sid,panels in g['stitch_panels'].items():
    if any('skirt' in p for p in panels) and any('skirt' not in p for p in panels):
        w+=g['stitches'][sid]
w=sorted(set(w)); P=V[w]
print('waist seam n=',len(w),'y[',P[:,1].min(),P[:,1].max(),'] radius', np.hypot(P[:,0],P[:,2]).mean())
