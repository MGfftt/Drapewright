"""Probe: do groups.json vertex ids still line up after the Blender OBJ import?"""
import json, sys
from pathlib import Path
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
pkg = Path(argv[0]).resolve()
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = json.loads((pkg / "sidecar.json").read_text(encoding="utf-8"))
bpy.ops.wm.obj_import(filepath=str(pkg / sc["garment_obj"]), forward_axis="NEGATIVE_Z", up_axis="Y")
obj = [o for o in bpy.context.scene.objects if o.type == "MESH"][0]
me = obj.data
g = json.loads((pkg / sc["groups"]).read_text(encoding="utf-8"))
print("n verts", len(me.vertices), "n groups max", max(max(v) for v in g["panels"].values()))
def z(idxs):
    zs = [me.vertices[i].co.z for i in idxs if i < len(me.vertices)]
    return (min(zs), max(zs)) if zs else (None, None)
allz = [v.co.z for v in me.vertices]
print("local z range", round(min(allz), 2), round(max(allz), 2))
for name, ids in g["panels"].items():
    lo, hi = z(ids)
    print(f"panel {name:15s} n={len(ids):5d} local z {lo}..{hi}")
# boundary from polygons
cnt = {}
for poly in me.polygons:
    vs = list(poly.vertices)
    for k in range(len(vs)):
        a, b = vs[k], vs[(k + 1) % len(vs)]
        key = (a, b) if a < b else (b, a)
        cnt[key] = cnt.get(key, 0) + 1
boundary = set()
for (a, b), n in cnt.items():
    if n == 1:
        boundary.update((a, b))
print("boundary verts", len(boundary), "z", round(min(me.vertices[i].co.z for i in boundary), 2),
      round(max(me.vertices[i].co.z for i in boundary), 2))
torso = set()
for name, ids in g["panels"].items():
    if "skirt" not in name:
        torso.update(ids)
inter = torso & boundary
print("torso", len(torso), "torso&boundary", len(inter), "their z",
      round(min(me.vertices[i].co.z for i in inter), 2) if inter else None,
      round(max(me.vertices[i].co.z for i in inter), 2) if inter else None)
print("matrix_world", [round(x, 4) for x in obj.matrix_world.to_scale()])
