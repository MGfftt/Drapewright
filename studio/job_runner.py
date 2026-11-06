"""Turn one approved design.json into a 3D package + drape preview.

    ./.venv/Scripts/python.exe -m studio.job_runner <job_id> [--no-sim] [--frames 96]

Steps (each writes into the job folder, so a crash never loses the paper pattern):
    design.json -> validate -> package/ (pattern svg, obj, sidecar, groups)
                -> package/sim/ (glb + 3 orthographic renders)
                -> result.json

Exit codes: 0 ok, 2 bad design, 3 pattern rejected, 4 simulation failed.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import traceback

from studio import jobs as jobstore
from studio import config
from studio.core import build as builder
from studio.core import design as designmod


def log(job_id, msg):
    jobstore.log(job_id, msg)
    print(f"[job] {msg}", flush=True)


def stitch_views(sim_dir):
    """Combine the three Blender renders into one contact sheet (PIL lives in the venv)."""
    try:
        from PIL import Image
    except ImportError:
        return None
    names = ["sim_front.png", "sim_side.png", "sim_back.png"]
    paths = [os.path.join(sim_dir, n) for n in names]
    if not all(os.path.isfile(p) for p in paths):
        return None
    imgs = [Image.open(p).convert("RGB") for p in paths]
    h = max(i.height for i in imgs)
    w = sum(i.width for i in imgs)
    sheet = Image.new("RGB", (w, h), (18, 20, 24))
    x = 0
    for img in imgs:
        sheet.paste(img, (x, 0))
        x += img.width
    out = os.path.join(sim_dir, "sim_views.png")
    sheet.save(out)
    return out


def run_sim(job_id, package_dir, frames, quality, timeout=1200):
    blender = config.find_blender()
    if not blender:
        raise RuntimeError("Blender not found; set GCSTUDIO_BLENDER to blender.exe")
    sim_dir = os.path.join(package_dir, "sim")
    script = os.path.join(config.REPO_ROOT, "studio", "sim", "cloth_setup.py")
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1",
           "--python", script, "--",
           "--package", package_dir, "--out", sim_dir,
           "--frames", str(frames), "--quality", str(quality), "--save-blend"]
    log(job_id, "blender: " + " ".join(cmd[1:4]) +
        f" --package {os.path.basename(package_dir)} --frames {frames} --quality {quality}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", cwd=config.REPO_ROOT, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            "the drape did not finish within %ds; a hanging solve usually means the "
            "garment started deeply self-intersecting - rebuild with --quality 5 "
            "--frames 48, or simplify the design (fewer panels)" % timeout)
    tail = "\n".join((proc.stdout or "").splitlines()[-25:])
    for line in (proc.stdout or "").splitlines():
        if line.startswith("[cloth]"):
            log(job_id, "sim " + line)
    if proc.returncode != 0:
        err = (proc.stderr or tail)[-1500:]
        raise RuntimeError(f"blender exited {proc.returncode}\n{err}")
    sim_json = os.path.join(sim_dir, "sim.json")
    if not os.path.isfile(sim_json):
        raise RuntimeError("blender produced no sim.json\n" + tail)
    sheet = stitch_views(sim_dir)
    info = json.load(open(sim_json, encoding="utf-8"))
    info["contact_sheet"] = sheet
    # store paths relative to the package so the result is portable
    for key in ("glb", "blend"):
        val = info.get(key)
        if val:
            try:
                info[key] = os.path.relpath(val, package_dir).replace("\\", "/")
            except ValueError:
                pass
    if info.get("exploded"):
        raise RuntimeError(info.get("error") or "the cloth simulation exploded")
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description="build + drape one Garment Studio job")
    ap.add_argument("job_id")
    ap.add_argument("--no-sim", action="store_true")
    ap.add_argument("--frames", type=int, default=96)
    ap.add_argument("--quality", type=int, default=8)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args(argv)

    job_id = args.job_id
    jdir = jobstore._job_dir(job_id)
    if not os.path.isdir(jdir):
        print(f"no such job: {job_id}", file=sys.stderr)
        return 2

    t0 = time.time()
    design_path = os.path.join(jdir, "design.json")
    result = {"schema": "gcstudio/result/1", "job_id": job_id, "status": "failed", "steps": {}}

    try:
        if not os.path.isfile(design_path):
            raise designmod.DesignError("design.json is missing")
        des = designmod.load(design_path)
        parts = sorted(des["report"]["per_part"])
        log(job_id, f"design ok: {len(des['floats'])} floats, parts {parts}")

        package_dir = os.path.join(jdir, "package")
        tb = time.time()
        pkg = builder.build(design_path, package_dir, tag=args.tag or job_id.split("-")[-1],
                            render=True, clean=True)
        sidecar = json.load(open(os.path.join(package_dir, pkg["files"]["sidecar"]), encoding="utf-8"))
        counts = sidecar.get("counts") or {}
        result["steps"]["build"] = {"seconds": round(time.time() - tb, 1),
                                    "pattern": pkg["files"]["pattern"],
                                    "counts": counts}
        log(job_id, f"package built in {result['steps']['build']['seconds']}s "
                    f"({counts.get('vertices')} verts, {counts.get('stitches')} stitches)")

        if not args.no_sim:
            ts = time.time()
            verts = counts.get("vertices") or 0
            frames, quality = args.frames, args.quality
            if verts > 15000:
                # a 24k-vertex garment at quality 8 / 96 frames takes many minutes; the
                # drape quality barely changes, so trade solver quality for wall clock
                frames, quality = min(frames, 72), min(quality, 6)
                log(job_id, f"heavy mesh ({verts} verts) -> frames {frames}, quality {quality}")
            sim = run_sim(job_id, package_dir, frames, quality)
            result["steps"]["sim"] = {"seconds": round(time.time() - ts, 1),
                                      "pin_sources": sim.get("pin_sources"),
                                      "bake_seconds": sim.get("bake_seconds"),
                                      "glb": sim.get("glb"),
                                      "blend": sim.get("blend"),
                                      "glb_bytes": sim.get("glb_bytes"),
                                      "blend_bytes": sim.get("blend_bytes")}
            log(job_id, f"drape baked in {sim.get('bake_seconds')}s "
                        f"(pins {sim.get('pin_count')})")
            for w in sim.get("warnings") or []:
                result.setdefault("warnings", []).append(w)
                log(job_id, "WARNING " + w)

        result["status"] = "ok"
        result["seconds"] = round(time.time() - t0, 1)
    except designmod.DesignError as exc:
        result["error"] = {"kind": "design", "message": str(exc)}
        log(job_id, f"FAILED design: {exc}")
    except builder.BuildError as exc:
        result["error"] = {"kind": "pattern", "message": str(exc)}
        log(job_id, f"FAILED pattern: {exc}")
    except Exception as exc:  # noqa: BLE001
        result["error"] = {"kind": "sim", "message": str(exc),
                           "traceback": traceback.format_exc()[-2000:]}
        log(job_id, f"FAILED sim: {exc}")

    jobstore._write_json(os.path.join(jdir, "result.json"), result)
    print(json.dumps({"status": result["status"], "job": job_id,
                      "seconds": result.get("seconds"), "error": result.get("error")},
                     ensure_ascii=False), flush=True)
    if result["status"] == "ok":
        return 0
    return {"design": 2, "pattern": 3}.get(result["error"]["kind"], 4)


if __name__ == "__main__":
    raise SystemExit(main())
