import bpy, os, math
from mathutils import Vector, Euler
REPO = r"C:\Users\41239\Desktop\科研\ChatGarment-main"
OUT = os.path.join(REPO, "studio", "jobs", "20261106-190913-验收-条纹短袖-大摆中长裙-bc68", "package")
SHOT = os.path.join(REPO, "studio", "runs", "blender_accept.png")
bpy.ops.preferences.addon_enable(module="gcstudio")
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)
s = bpy.context.scene.gcstudio
s.repo = REPO
s.design = os.path.join(OUT, "design.json")
s.out = OUT
s.status = "验收：从 job_runner 的 package 载入"
print("LOAD", bpy.ops.gcstudio.load())
print("STATUS", s.status)

def frame_views():
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) / 2
    dist = (hi - lo).length * 1.15
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
                r3d.view_rotation = Euler((math.radians(78), 0, math.radians(18)), "XYZ").to_quaternion()
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
                        bpy.ops.wm.call_panel(name="VIEW3D_PT_gcstudio")
                except Exception as exc:
                    print("CALL_PANEL_FAIL", exc)
                return 0.6
    return 0.6

def capture():
    bpy.ops.screen.screenshot(filepath=SHOT)
    print("SHOT", SHOT)
    bpy.ops.wm.quit_blender()
    return None

bpy.app.timers.register(frame_views, first_interval=1.5)
bpy.app.timers.register(popup, first_interval=2.8)
bpy.app.timers.register(capture, first_interval=4.2)