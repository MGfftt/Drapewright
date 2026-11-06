# SPDX-License-Identifier: MIT
# gcstudio — Blender side panel for the Garment Studio pipeline.
#
# Design rule: this addon never generates geometry itself. It only shells out to the
# existing pipeline (repo/.venv python builds the pattern, a *second* headless Blender
# drapes it) and loads the result. Everything it writes stays under the output folder you
# pick, and uninstalling is "remove this folder + disable the addon" — no registry, no
# global packages, no user config outside Blender's own addon directory.
bl_info = {
    "name": "Garment Studio",
    "author": "local",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > GC Studio",
    "description": "Create a GarmentCodeRC pattern, drape it with cloth sim, load the result",
    "category": "Fashion",
}

import os
import subprocess
import sys
import time

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty
from bpy.types import Operator, Panel, PropertyGroup

STATE = {"proc": None, "kind": "", "out": "", "log": "", "t0": 0.0}

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


# --------------------------------------------------------------------------- helpers
def repo_root(scene):
    """Locate the chatgarment repo: env var, then ancestors of the .blend, then the field."""
    cands = []
    env = os.environ.get("GCSTUDIO_ROOT")
    if env:
        cands.append(env)
    if bpy.data.filepath:
        d = os.path.dirname(os.path.abspath(bpy.data.filepath))
        while d and os.path.dirname(d) != d:
            cands.append(d)
            d = os.path.dirname(d)
    cands.append(scene.gcstudio.repo)
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "studio", "core", "cli.py")):
            return os.path.abspath(c)
    return ""


def venv_python(root):
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        p = os.path.join(root, ".venv", *rel)
        if os.path.isfile(p):
            return p
    return ""


def read_tail(path, n=12):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        return "cannot read log: %s" % exc
    return "\n".join(lines[-n:])


def spawn(cmd, cwd, log_path):
    fh = open(log_path, "wb")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=fh, stderr=subprocess.STDOUT,
                            creationflags=CREATE_NO_WINDOW)
    proc._gcstudio_log_fh = fh  # keep the handle alive with the process object
    return proc


def finish(ok, message):
    scene = bpy.context.scene
    scene.gcstudio.busy = False
    scene.gcstudio.status = ("完成：" if ok else "失败：") + message
    if STATE.get("log"):
        scene.gcstudio.log = read_tail(STATE["log"])
    STATE["proc"] = None
    for area in getattr(bpy.context.screen, "areas", []) or []:
        area.tag_redraw()
    return None  # unregister the timer


def poll():
    proc = STATE.get("proc")
    if proc is None:
        return None
    rc = proc.poll()
    scene = bpy.context.scene
    if rc is None:
        scene.gcstudio.status = "%s 运行中 %.0fs …" % (STATE.get("kind") or "任务",
                                                     time.time() - STATE.get("t0", time.time()))
        if STATE.get("log"):
            scene.gcstudio.log = read_tail(STATE["log"], 6)
        for area in getattr(bpy.context.screen, "areas", []) or []:
            area.tag_redraw()
        return 0.4
    try:
        proc._gcstudio_log_fh.close()
    except Exception:  # noqa: BLE001 - handle already gone
        pass
    if rc == 0:
        return finish(True, "%s 成功（%s）" % (STATE.get("kind"), os.path.basename(STATE.get("out", ""))))
    hint = ""
    if STATE.get("kind") == "纸样":
        hint = "  (退出码 2=设计不合法，3=GCrc 拒绝该组合；日志里有原因)"
    return finish(False, "%s 退出码 %d%s" % (STATE.get("kind"), rc, hint))


def start(kind, cmd, cwd, out_dir, log_name):
    scene = bpy.context.scene
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, log_name)
    STATE.update(kind=kind, out=out_dir, log=log_path, t0=time.time())
    try:
        STATE["proc"] = spawn(cmd, cwd, log_path)
    except OSError as exc:
        scene.gcstudio.status = "启动失败：%s" % exc
        return
    scene.gcstudio.busy = True
    scene.gcstudio.status = kind + " 已启动 …"
    scene.gcstudio.log = ""
    if not bpy.app.timers.is_registered(poll):
        bpy.app.timers.register(poll, first_interval=0.4)


def resolve_out(scene):
    root = repo_root(scene)
    out = bpy.path.abspath(scene.gcstudio.out or "")
    if not out:
        stem = os.path.splitext(os.path.basename(scene.gcstudio.design or "design"))[0]
        base = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else root
        out = os.path.join(base, "gcstudio_runs", stem or "design")
    return out


# --------------------------------------------------------------------------- operators
class GCSTUDIO_OT_pick_design(Operator):
    """Choose a design.json (the named-float garment spec)"""
    bl_idname = "gcstudio.pick_design"
    bl_label = "选择 design.json"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        context.scene.gcstudio.design = self.filepath
        return {"FINISHED"}


class GCSTUDIO_OT_build(Operator):
    """Build the 2D pattern + mesh package from design.json (runs the repo venv, ~10-18 s)"""
    bl_idname = "gcstudio.build"
    bl_label = "1. 生成纸样"
    bl_options = {"REGISTER"}

    def execute(self, context):
        s = context.scene.gcstudio
        root = repo_root(context.scene)
        if not root:
            self.report({"ERROR"}, "找不到仓库根目录（先在上面填 ChatGarment-main 的路径）")
            return {"CANCELLED"}
        py = venv_python(root)
        if not py:
            self.report({"ERROR"}, "找不到 .venv python")
            return {"CANCELLED"}
        design = bpy.path.abspath(s.design or "")
        if not os.path.isfile(design):
            self.report({"ERROR"}, "design.json 不存在：%s" % design)
            return {"CANCELLED"}
        out = resolve_out(context.scene)
        cmd = [py, "-m", "studio.core.cli", "build", "--design", design, "--out", out]
        start("纸样", cmd, root, out, "_addon_build.log")
        return {"FINISHED"}


class GCSTUDIO_OT_sim(Operator):
    """Drape the built package with Blender's cloth solver (headless, 40-200 s)"""
    bl_idname = "gcstudio.sim"
    bl_label = "2. 布料仿真"
    bl_options = {"REGISTER"}

    def execute(self, context):
        s = context.scene.gcstudio
        root = repo_root(context.scene)
        if not root:
            self.report({"ERROR"}, "找不到仓库根目录")
            return {"CANCELLED"}
        out = resolve_out(context.scene)
        if not os.path.isfile(os.path.join(out, "manifest.json")):
            self.report({"ERROR"}, "先点「1. 生成纸样」：%s 里没有 manifest.json" % out)
            return {"CANCELLED"}
        blender = bpy.app.binary_path
        script = os.path.join(root, "studio", "sim", "cloth_setup.py")
        sim_dir = os.path.join(out, "sim")
        cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1",
               "--python", script, "--",
               "--package", out, "--out", sim_dir,
               "--frames", str(s.frames), "--quality", str(s.quality),
               "--save-blend"]
        start("仿真", cmd, root, out, "_addon_sim.log")
        return {"FINISHED"}


class GCSTUDIO_OT_load(Operator):
    """Import the draped mesh (sim.glb) into this scene"""
    bl_idname = "gcstudio.load"
    bl_label = "3. 载入结果"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        out = resolve_out(context.scene)
        glb = os.path.join(out, "sim", "sim.glb")
        if not os.path.isfile(glb):
            blend = os.path.join(out, "sim", "sim_drape.blend")
            if os.path.isfile(blend):
                bpy.ops.wm.open_mainfile(filepath=blend)
                return {"FINISHED"}
            self.report({"ERROR"}, "还没有仿真结果：%s" % glb)
            return {"CANCELLED"}
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=glb)
        imported = [o for o in bpy.data.objects if o not in before]
        for obj in imported:
            obj.name = "GC_" + obj.name
            obj.select_set(False)
        self.report({"INFO"}, "导入 %d 个对象" % len(imported))
        return {"FINISHED"}


class GCSTUDIO_OT_open_out(Operator):
    """Open the output folder (this runs inside Blender's own desktop session)"""
    bl_idname = "gcstudio.open_out"
    bl_label = "打开输出文件夹"
    bl_options = {"REGISTER"}

    def execute(self, context):
        out = resolve_out(context.scene)
        os.makedirs(out, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(out)  # noqa: S606 - opening our own output folder
            else:
                subprocess.Popen(["xdg-open", out])
        except OSError as exc:
            self.report({"ERROR"}, "打不开：%s" % exc)
            return {"CANCELLED"}
        return {"FINISHED"}


class GCSTUDIO_OT_clear(Operator):
    """Remove the objects this addon imported (keeps the files on disk)"""
    bl_idname = "gcstudio.clear"
    bl_label = "清空导入对象"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        victims = [o for o in bpy.data.objects if o.name.startswith("GC_")]
        for obj in victims:
            bpy.data.objects.remove(obj, do_unlink=True)
        self.report({"INFO"}, "删除了 %d 个对象" % len(victims))
        return {"FINISHED"}


# --------------------------------------------------------------------------- properties
class GCStudioProps(PropertyGroup):
    repo: StringProperty(
        name="仓库根目录",
        description="ChatGarment-main 的绝对路径（留空则从 .blend 所在目录向上找）",
        default="",
        subtype="DIR_PATH",
    )
    design: StringProperty(
        name="design.json",
        description="命名浮点设计文件（studio.agent template 可以生成骨架）",
        default="",
        subtype="FILE_PATH",
    )
    out: StringProperty(
        name="输出目录",
        description="纸样/网格/仿真产物都写在这里；留空则用 <blend 目录>/gcstudio_runs/<design 名>",
        default="",
        subtype="DIR_PATH",
    )
    frames: IntProperty(name="帧数", default=96, min=8, max=240)
    quality: IntProperty(name="质量", default=8, min=1, max=15)
    status: StringProperty(name="状态", default="就绪")
    log: StringProperty(name="日志", default="")
    busy: BoolProperty(name="运行中", default=False)


# --------------------------------------------------------------------------- panel
class VIEW3D_PT_gcstudio(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GC Studio"
    bl_label = "Garment Studio"

    def draw(self, context):
        layout = self.layout
        s = context.scene.gcstudio
        root = repo_root(context.scene)

        col = layout.column(align=True)
        col.prop(s, "repo", text="仓库")
        if not root:
            col.label(text="找不到 studio/core/cli.py", icon="ERROR")
        elif not venv_python(root):
            col.label(text="缺 .venv/python", icon="ERROR")
        else:
            col.label(text=root, icon="CHECKMARK")

        layout.separator()
        row = layout.row(align=True)
        row.prop(s, "design", text="设计")
        row.operator("gcstudio.pick_design", text="", icon="FILEBROWSER")

        row = layout.row(align=True)
        row.prop(s, "out", text="输出")
        if not s.out:
            row.label(text="(默认)")
        layout.prop(s, "frames")
        layout.prop(s, "quality")

        layout.separator()
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.enabled = not s.busy
        col.operator("gcstudio.build", icon="MOD_CLOTH")
        col.operator("gcstudio.sim", icon="PHYSICS")
        col.operator("gcstudio.load", icon="IMPORT")
        row = layout.row(align=True)
        row.operator("gcstudio.open_out", text="打开输出文件夹", icon="FILE_FOLDER")
        row.operator("gcstudio.clear", text="", icon="TRASH")

        layout.separator()
        box = layout.box()
        box.label(text=s.status, icon="TIME" if s.busy else "INFO")
        if s.log:
            for line in s.log.splitlines()[-8:]:
                box.label(text=line[:110])
        box.label(text="日志：_addon_build.log / _addon_sim.log", icon="TEXT")


# --------------------------------------------------------------------------- register
CLASSES = (
    GCStudioProps,
    GCSTUDIO_OT_pick_design,
    GCSTUDIO_OT_build,
    GCSTUDIO_OT_sim,
    GCSTUDIO_OT_load,
    GCSTUDIO_OT_open_out,
    GCSTUDIO_OT_clear,
    VIEW3D_PT_gcstudio,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.gcstudio = bpy.props.PointerProperty(type=GCStudioProps)


def unregister():
    if bpy.app.timers.is_registered(poll):
        bpy.app.timers.unregister(poll)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:  # noqa: BLE001 - already gone after a hot reload
            pass
    try:
        del bpy.types.Scene.gcstudio
    except Exception:  # noqa: BLE001
        pass


if __name__ == "__main__":
    register()
