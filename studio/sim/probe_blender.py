"""Probe Blender 5.x cloth API + OBJ import, so studio/sim never guesses names.

Run:  blender -b --factory-startup --python studio/sim/probe_blender.py
"""
import json
import sys

import bpy

OUT = {}


def rna(obj, only=None):
    rows = []
    for p in obj.bl_rna.properties:
        if p.identifier in ("rna_type",):
            continue
        if only and not any(k in p.identifier for k in only):
            continue
        rows.append([p.identifier, p.name, p.type])
    return rows


OUT["version"] = bpy.app.version_string
OUT["up_container"] = sys.platform

# --- a plane with a cloth modifier ------------------------------------------
bpy.ops.mesh.primitive_plane_add(size=1.0)
ob = bpy.context.object
ob.name = "cloth_probe"
mod = ob.modifiers.new("Cloth", "CLOTH")
sett = mod.settings
OUT["cloth_settings"] = rna(sett)
OUT["cloth_collision_settings"] = rna(mod.collision_settings)
OUT["point_cache"] = rna(mod.point_cache, only=("frame", "step", "cache"))

# things whose names changed across 3.x..5.x: dump the interesting subset
INTERESTING = ("quality", "mass", "tension", "compression", "bending",
               "collision", "self_collision", "distance", "friction",
               "damping", "sew", "pin", "vertex_group", "time_scale",
               "effector_weights", "gravity")
OUT["interesting"] = sorted({p.identifier for p in sett.bl_rna.properties
                             if any(k in p.identifier.lower() for k in INTERESTING)})

# --- sewing: how do you get sewing springs in 5.x? --------------------------
OUT["mesh_ops_with_sew"] = sorted(o for o in dir(bpy.ops.mesh) if "sew" in o.lower())
OUT["obj_ops_with_sew"] = sorted(o for o in dir(bpy.ops.object) if "sew" in o.lower())
OUT["cloth_ops"] = sorted(o for o in dir(bpy.ops.cloth))

# --- collision / body side --------------------------------------------------
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.1, location=(0, 0, 0.5))
body = bpy.context.object
body.name = "body_probe"
body.modifiers.new("Collision", "COLLISION")
body.modifiers.new("Solidify", "SOLIDIFY")
OUT["collision_modifier"] = rna(body.modifiers["Collision"].settings) \
    if hasattr(body.modifiers["Collision"], "settings") else "no .settings"
OUT["solidify_props"] = sorted(p.identifier for p in body.modifiers["Solidify"].bl_rna.properties)

# --- vertex groups / pin ----------------------------------------------------
OUT["cloth_has_pin_group"] = [p.identifier for p in sett.bl_rna.properties if "pin" in p.identifier.lower()]

import os
_open = os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe_result.json")
with open(_open, "w", encoding="utf-8") as f:
    json.dump(OUT, f, indent=1)
print("CLOTH_PROBE_JSON_BEGIN")
print(json.dumps(OUT, indent=1))
print("CLOTH_PROBE_JSON_END")
