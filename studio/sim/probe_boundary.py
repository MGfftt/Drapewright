
import json, numpy as np
pkg='studio/runs/smoke2'
g=json.load(open(pkg+'/mesh/smoke2_groups.json'))
V=[];F=[]
for line in open(pkg+'/mesh/smoke2_garment.obj'):
    if line.startswith('v '): V.append([float(x) for x in line.split()[1:4]])
    elif line.startswith('f '): F.append([int(x.split('/')[0])-1 for x in line.split()[1:]])
V=np.array(V)
from collections import Counter
cnt=Counter()
for f in F:
    for a,b in ((f[0],f[1]),(f[1],f[2]),(f[2],f[0])):
        cnt[(min(a,b),max(a,b))]+=1
bnd={i for (a,b),c in cnt.items() if c==1 for i in (a,b)}
print('boundary verts',len(bnd))
# panel of each vertex
vp={}
for name,ids in g['panels'].items():
    for i in ids: vp.setdefault(i,set()).add(name)
rows=[]
for i in sorted(bnd):
    rows.append((V[i][1], tuple(sorted(vp.get(i,[])))))
rows.sort(reverse=True)
print('top 12 boundary verts by Y:', [(round(y,1),p) for y,p in rows[:12]])
import collections
print('by panel top:', collections.Counter([p for _,p in rows[:200]]).most_common(6))
# torso boundary verts and their z (up after import is y here)
tb=[(V[i][1],tuple(sorted(vp.get(i,[])))) for i in bnd if any('torso' in n for n in vp.get(i,[])) ]
tb.sort(reverse=True)
print('torso boundary count',len(tb),'top Y',tb[:5])
