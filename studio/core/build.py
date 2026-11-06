"""design.json -> GarmentCodeRC pattern -> box mesh package."""

import datetime
import glob
import json
import os
import shutil
import subprocess
import sys

import numpy as np

from . import design as design_mod
from .paths import REPO_ROOT, DesignError

STUDIO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class BuildError(Exception):
    """The design was valid JSON but GarmentCodeRC could not turn it into a garment."""


def _now():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def build(design_path, out_dir, tag=None, render=True, clean=True):
    """Run the whole no-VLM pipeline for one design file.

    out_dir receives the package:
      manifest.json     contract for downstream tools (Blender, viewer)
      design.json       the input, copied verbatim
      sidecar.json      mesh facts (paths, units, bbox, floats per part)
      pattern/          GCrc pattern files (specification.json, pattern.svg/png)
      mesh/             <tag>_garment.obj, <tag>_body.obj, <tag>_preview.png
    """
    d = design_mod.load(design_path)
    out_dir = os.path.abspath(out_dir)
    tag = tag or os.path.basename(out_dir)
    work = os.path.join(out_dir, "pattern")
    mesh_dir = os.path.join(out_dir, "mesh")
    if clean:
        for sub in (work, mesh_dir):
            if os.path.isdir(sub):
                shutil.rmtree(sub)
    os.makedirs(work, exist_ok=True)
    os.makedirs(mesh_dir, exist_ok=True)

    # GarmentCodeRC resolves ./assets/bodies/*.yaml relative to the cwd.
    prev_cwd = os.getcwd()
    os.chdir(REPO_ROOT)
    try:
        from llava.garment_utils_v2 import run_garmentcode_parser_float50
        specs = run_garmentcode_parser_float50(
            [], d["garment"], np.asarray(d["vector"], dtype=np.float64), work)
    finally:
        os.chdir(prev_cwd)

    if not specs:
        designs = sorted(glob.glob(os.path.join(work, "*", "design.yaml")))
        raise BuildError(
            "GarmentCodeRC rejected this design, so no pattern was written "
            "(the resolved parameters are in %s). Most common cause: a length/width "
            "combination that makes a pattern edge degenerate. "
            "Nudge the neighbouring floats by ~0.05 and rebuild."
            % (designs[0] if designs else os.path.join(work, "*", "design.yaml")))

    spec = specs[0]
    shutil.copyfile(spec, os.path.join(work, "specification.json"))
    for pat in glob.glob(os.path.join(os.path.dirname(spec), "*pattern*")):
        shutil.copyfile(pat, os.path.join(work, os.path.basename(pat)))

    cmd = [sys.executable, os.path.join(REPO_ROOT, "tools", "spec_to_obj.py"),
           "--spec", spec, "--out", mesh_dir, "--tag", tag]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise BuildError("spec_to_obj.py failed (exit %d)\n%s\n%s"
                         % (proc.returncode, proc.stdout[-2000:], proc.stderr[-2000:]))

    info = {}
    info_path = os.path.join(mesh_dir, tag + "_info.json")
    if os.path.isfile(info_path):
        with open(info_path, "r", encoding="utf-8") as f:
            info = json.load(f)

    garment_obj = os.path.join(mesh_dir, tag + "_garment.obj")
    body_obj = os.path.join(mesh_dir, tag + "_body.obj")
    preview = os.path.join(mesh_dir, tag + "_preview.png")
    groups_json = os.path.join(mesh_dir, tag + "_groups.json")
    for p in (garment_obj, body_obj):
        if not os.path.isfile(p):
            raise BuildError("spec_to_obj.py did not write %s" % p)

    rel = lambda p: os.path.relpath(p, out_dir).replace("\\", "/")
    sidecar = {
        "schema": "gcstudio/sidecar/1",
        "unit": "cm",
        "up_axis": "Y",
        "garment_obj": rel(garment_obj),
        "body_obj": rel(body_obj),
        "preview_png": rel(preview) if os.path.isfile(preview) else None,
        "groups": rel(groups_json) if os.path.isfile(groups_json) else None,
        "bbox": {"min": info.get("bbox_min"), "max": info.get("bbox_max")},
        "counts": {"vertices": info.get("n_verts"),
                    "faces": info.get("n_faces"),
                    "stitches": info.get("n_stitches")},
        "panels": info.get("panels", []),
        "floats": d["floats"],
        "parts": {k: os.path.basename(os.path.dirname(spec)) for k in d["report"]["per_part"]},
    }
    with open(os.path.join(out_dir, "sidecar.json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, indent=2)

    shutil.copyfile(design_path, os.path.join(out_dir, "design.json"))
    manifest = {
        "schema": "gcstudio/package/1",
        "producer": "gcrc-studio",
        "created_at": _now(),
        "label": d["label"],
        "tag": tag,
        "kind": "pattern+mesh",
        "simulated": False,
        "files": {
            "design": "design.json",
            "sidecar": "sidecar.json",
            "spec": rel(os.path.join(work, "specification.json")),
            "pattern": [rel(p) for p in sorted(glob.glob(os.path.join(work, "*pattern*")))],
            "garment": sidecar["garment_obj"],
            "body": sidecar["body_obj"],
            "preview": sidecar["preview_png"],
            "groups": sidecar.get("groups"),
        },
        "notes": "box mesh: panels triangulated and stitched into shared vertices, "
                 "no cloth relaxation yet (run studio/sim in Blender to drape it)",
    }
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest