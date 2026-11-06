import bpy, sys, json
from mathutils.bvhtree import BVHTree
bpy.ops.wm.read_factory_settings(use_empty=True)
def imp(p):
    b=set(bpy.data.objects); bpy.ops.wm.obj_import(filepath=p, forward_axis="NEGATIVE_Z", up_axis="Y")
    return [o for o in bpy.data.objects if o not in b][0]
g=imp("studio/runs/smoke1/mesh/smoke1_garment.obj"); b=imp("studio/runs/smoke1/mesh/smoke1_body.obj")
for o in (g,b):
    o.scale=(0.01,)*3
    bpy.context.view_layer.objects.active=o; o.select_set(True); bpy.ops.object.transform_apply(scale=True); o.select_set(False)
dg=bpy.context.evaluated_depsgraph_get(); bvh=BVHTree.FromObject(b,dg)
ds=[]; zs=[]
for v in g.data.vertices:
    co=g.matrix_world@v.co
    hit=bvh.find_nearest(co); ds.append(hit[3] if hit and hit[3] is not None else -1); zs.append(co.z)
ds=sorted(ds)
n=len(ds)
print("BODY_BBOX", [round(x,3) for x in (b.matrix_world@__import__('mathutils').Vector(b.bound_box[0]))], [round(x,3) for x in (b.matrix_world@__import__('mathutils').Vector(b.bound_box[6]))])
print("DIST p0/5/25/50/75/95/100", [round(ds[int(q*(n-1))],4) for q in (0,.05,.25,.5,.75,.95,1)])
print("Z range", round(min(zs),3), round(max(zs),3))
