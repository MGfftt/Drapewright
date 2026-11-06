import bpy, os, math
from mathutils import Vector, Euler
REPO = r"C:\Users\41239\Desktop\科研\ChatGarment-main"
GLB = os.path.join(REPO, "studio", "runs", "addon_test", "sim", "sim.glb")
OUT = os.path.join(REPO, "studio", "runs", "addon_test")
SHOT = os.path.join(REPO, "studio", "runs", "blender_panel_final.png")
bpy.ops.preferences.addon_enable(module="gcstudio")
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.import_scene.gltf(filepath=GLB)
s = bpy.context.scene.gcstudio
s.repo = REPO; s.design = os.path.join(REPO, "cases", "rc_dress", "design.json"); s.out = OUT
s.status = "验收演示：已载入 sim.glb"

def frame_views():
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) / 2
    dist = (hi - lo).length * 1.15
    print("BBOX", tuple(round(v,3) for v in lo), tuple(round(v,3) for v in hi))
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for sp in area.spaces:
                if sp.type != "VIEW_3D":
                    continue
                sp.show_region_ui = True
                sp.shading.type = "SOLID"
                r3d = sp.region_3d
                r3d.view_perspective = "ORTHO"
                r3d.view_location = ctr
                r3d.view_distance = dist
                r3d.view_rotation = Euler((math.radians(90), 0, 0), "XYZ").to_quaternion()
                print("VIEW set", area.width, area.height, r3d.view_distance)
    return 1.0

def popup():
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            if area.type != "VIEW_3D":
                continue
            for region in area.regions:
                if region.type != "WINDOW":
                    continue
                try:
                    with bpy.context.temp_override(window=win, area=area, region=region):
                        print("CALL_PANEL", bpy.ops.wm.call_panel(name="VIEW3D_PT_gcstudio"))
                except Exception as e:
                    print("CALL_PANEL_FAIL", type(e).__name__, e)
                return 0.6
    return 0.6

def capture():
    bpy.ops.screen.screenshot(filepath=SHOT)
    print("SHOT", SHOT)
    bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(frame_views, first_interval=1.5)
bpy.app.timers.register(popup, first_interval=3.0)
bpy.app.timers.register(capture, first_interval=5.0)