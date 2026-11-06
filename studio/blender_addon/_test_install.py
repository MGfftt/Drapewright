import bpy, os, sys, traceback
zip_path = r"C:\Users\41239\Desktop\科研\ChatGarment-main\studio\blender_addon\dist\gcstudio-0.1.0.zip"
print("BLENDER", bpy.app.version_string)
try:
    print("install:", bpy.ops.preferences.addon_install(filepath=zip_path))
except Exception as e:
    print("INSTALL_FAIL", type(e).__name__, e)
try:
    bpy.ops.preferences.addon_enable(module="gcstudio")
    print("ENABLE_OK")
except Exception as e:
    print("ENABLE_FAIL", type(e).__name__, e)
    traceback.print_exc()
import addon_utils
mods = [m.__name__ for m in addon_utils.modules() if "gcstudio" in m.__name__]
print("MODULES", mods)
print("OPS_BUILD", hasattr(bpy.ops.gcstudio, "build"))
print("PANEL_CLASS", hasattr(bpy.types, "VIEW3D_PT_gcstudio"))
scn = bpy.context.scene
print("PROPS", hasattr(scn, "gcstudio"), getattr(getattr(scn, "gcstudio", None), "status", None))
U = bpy.types.VIEW3D_PT_gcstudio
print("PANEL_CATEGORY", U.bl_category, U.bl_label)