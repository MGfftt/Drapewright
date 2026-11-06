import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
bpy.ops.wm.read_factory_settings(use_empty=True)
def imp(p):
    b=set(bpy.data.objects); bpy.ops.wm.obj_import(filepath=p, forward_axis="NEGATIVE_Z", up_axis="Y")
    return [o for o in bpy.data.objects if o not in b][0]
b=imp("studio/runs/smoke2/mesh/smoke2_body.obj")
b.scale=(0.01,)*3
bpy.context.view_layer.objects.active=b; b.select_set(True); bpy.ops.object.transform_apply(scale=True)
dg=bpy.context.evaluated_depsgraph_get()
ev=b.evaluated_get(dg)
me=ev.to_mesh()
print("BODY verts", len(me.vertices), "polys", len(me.polygons), "matrix_world", [round(x,3) for x in b.matrix_world.translation])
bvh=BVHTree.FromObject(b, dg)
for z in (1.0, 0.9, 0.85):
    hit=bvh.ray_cast(Vector((0.0,z,0.0)), Vector((1.0,0.0,0.0)), 3.0)
    print("ray", z, hit[0], hit[3])
hit2=bvh.find_nearest(Vector((0.0,1.0,0.25)))
print("nearest", hit2[0], hit2[3])
ev.to_mesh_clear()
