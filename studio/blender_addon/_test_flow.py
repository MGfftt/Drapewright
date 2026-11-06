import bpy, os, time, addon_utils
bpy.ops.preferences.addon_enable(module="gcstudio")
import gcstudio
repo = r"C:\Users\41239\Desktop\科研\ChatGarment-main"
out = os.path.join(repo, "studio", "runs", "addon_test")
s = bpy.context.scene.gcstudio
s.repo = repo
s.design = os.path.join(repo, "cases", "rc_dress", "design.json")
s.out = out
s.frames = 48
s.quality = 5

def wait(label):
    t0 = time.time()
    while gcstudio.STATE.get("proc") is not None:
        gcstudio.poll()
        time.sleep(0.5)
        if time.time() - t0 > 600:
            print("TIMEOUT", label); break
    print(label, "status=", s.status)

print("OUT", out)
print("build:", bpy.ops.gcstudio.build())
wait("BUILD")
print("MANIFEST", os.path.isfile(os.path.join(out, "manifest.json")))
print("sim:", bpy.ops.gcstudio.sim())
wait("SIM")
print("GLB", os.path.isfile(os.path.join(out, "sim", "sim.glb")))
print("BLEND", os.path.isfile(os.path.join(out, "sim", "sim_drape.blend")))
print("load:", bpy.ops.gcstudio.load())
objs = [o for o in bpy.data.objects if o.name.startswith("GC_")]
print("IMPORTED", [(o.name, o.type, len(o.data.vertices) if o.type == "MESH" else None) for o in objs])
print("LOGTAIL", (s.log or "").splitlines()[-3:])