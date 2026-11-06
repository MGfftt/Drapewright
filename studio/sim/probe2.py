import json
import bpy

out = {}
# 1) every operator in every module whose name mentions sew
found = {}
for mod_name in dir(bpy.ops):
    if mod_name.startswith("_"):
        continue
    mod = getattr(bpy.ops, mod_name)
    try:
        names = [n for n in dir(mod) if "sew" in n.lower()]
    except Exception:
        continue
    if names:
        found[mod_name] = names
out["ops_with_sew"] = found

# 2) mesh edge rna props
bpy.ops.mesh.primitive_plane_add(size=1.0)
me = bpy.context.object.data
out["mesh_edge_props"] = [p.identifier for p in bpy.types.MeshEdge.bl_rna.properties]
out["mesh_attrs"] = [a.name for a in me.attributes]

# 3) does a cloth modifier accept edges tagged by a boolean attribute?
mod = bpy.context.object.modifiers.new("Cloth", "CLOTH")
out["cloth_setting_names"] = [p.name for p in mod.settings.bl_rna.properties
                              if "sew" in p.name.lower() or "sew" in p.identifier.lower()]
out["cloth_ui_hint"] = "see cloth.settings.use_sewing_springs"

print("PROBE2_BEGIN")
print(json.dumps(out, indent=1, ensure_ascii=False))
print("PROBE2_END")
