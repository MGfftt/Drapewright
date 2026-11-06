"""Turn a GarmentCode pattern specification into a 3D OBJ + preview PNG.

This is the "3D after GarmentCode" step without the warp physics simulation
(warp is not available on this Windows box: no CUDA toolkit / nvcc to build
NvidiaWarp-GarmentCode).  What we produce is the *box mesh*: every pattern
panel is triangulated (CGAL CDT) and placed around the body with its stitching
edges already merged into shared vertices -- i.e. the garment wrapped into a
tube around the torso/skirt volume, before cloth relaxation.

Usage:
  PYTHONPATH=repos/GarmentCodeRC-main ./.venv/Scripts/python.exe tools/spec_to_obj.py \
      --spec runs/bypass_rc/rc_dress/valid_garment_wholebody/valid_garment_wholebody_specification.json \
      --out  runs/bypass_rc/rc_dress/3d --tag rc_dress --res 1.0

Outputs (in --out):
  <tag>_garment.obj     garment box mesh, centimetres, Y up
  <tag>_body.obj        reference body (mean_all, scaled to cm) -- same frame
  <tag>_preview.png     front / side / back orthographic render (z-buffer)
  <tag>_info.json       vertex/face counts, bbox, stitch count
"""

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "repos", "GarmentCodeRC-main"))


# --------------------------------------------------------------------------- io
def read_obj(path):
    verts, faces = [], []
    with open(path, "r") as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(x.split("/")[0]) for x in line.split()[1:]]
                # fan triangulation for any polygon
                for k in range(1, len(idx) - 1):
                    faces.append([idx[0] - 1, idx[k] - 1, idx[k + 1] - 1])
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def write_obj(path, V, F, name="mesh"):
    with open(path, "w") as f:
        f.write("# %s\n" % name)
        for v in V:
            f.write("v %.4f %.4f %.4f\n" % (v[0], v[1], v[2]))
        for t in F:
            f.write("f %d %d %d\n" % (t[0] + 1, t[1] + 1, t[2] + 1))


# ------------------------------------------------------------------- rendering
def render_views(V, F, colors, out_path, body_V=None, body_F=None,
                 width=420, height=680, angles=(0.0, 90.0, 180.0)):
    """Orthographic z-buffer render.  Rotation is about the world Y axis.

    Returns the list of per-view images (PIL) and the combined image.
    """
    all_pts = V if body_V is None else np.vstack([V, body_V])
    ylo, yhi = all_pts[:, 1].min(), all_pts[:, 1].max()
    half = max(all_pts[:, 0].ptp(), all_pts[:, 2].ptp(), 1.0)
    scale = (height * 0.86) / max(yhi - ylo, 1e-6)
    cx, cy = width * 0.5, height * 0.5
    ycen = 0.5 * (ylo + yhi)

    views = []
    for ang in angles:
        th = np.deg2rad(ang)
        c, s = np.cos(th), np.sin(th)
        rot = np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])

        img = np.ones((height, width, 3), dtype=np.float32) * 0.97
        zbuf = np.full((height, width), -1e18, dtype=np.float32)

        # face order does not matter thanks to the z-buffer; draw body first
        groups = [(V, F, colors)]
        if body_V is not None:
            groups = [(body_V, body_F, (0.80, 0.80, 0.82))] + groups

        light = np.array([0.35, 0.55, 0.75])
        light = light / np.linalg.norm(light)

        for gV, gF, gcol in groups:
            W = gV @ rot.T
            sx = W[:, 0] * scale + cx
            sy = cy - (W[:, 1] - ycen) * scale
            depth = W[:, 2]
            Pt = np.stack([sx, sy, depth], axis=1)
            tri = Pt[gF]                      # (M, 3, 3)
            fn = np.cross(gV[gF[:, 1]] - gV[gF[:, 0]], gV[gF[:, 2]] - gV[gF[:, 0]])
            nl = np.linalg.norm(fn, axis=1)
            keep = nl > 1e-9
            shade = np.zeros(len(fn))
            shade[keep] = np.abs((fn[keep] / nl[keep, None]) @ light)
            shade = 0.30 + 0.70 * shade

            x0 = np.floor(tri[:, :, 0].min(1)).astype(int)
            x1 = np.ceil(tri[:, :, 0].max(1)).astype(int)
            y0 = np.floor(tri[:, :, 1].min(1)).astype(int)
            y1 = np.ceil(tri[:, :, 1].max(1)).astype(int)
            for t in range(len(gF)):
                if not keep[t]:
                    continue
                if x1[t] < 0 or y1[t] < 0 or x0[t] >= width or y0[t] >= height:
                    continue
                ax = max(x0[t], 0); bx = min(x1[t], width - 1)
                ay = max(y0[t], 0); by = min(y1[t], height - 1)
                if bx < ax or by < ay:
                    continue
                p0, p1, p2 = tri[t]
                xs = np.arange(ax, bx + 1)
                ys = np.arange(ay, by + 1)
                gx, gy = np.meshgrid(xs + 0.5, ys + 0.5)
                den = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
                if abs(den) < 1e-12:
                    continue
                w0 = ((p1[1] - p2[1]) * (gx - p2[0]) + (p2[0] - p1[0]) * (gy - p2[1])) / den
                w1 = ((p2[1] - p0[1]) * (gx - p2[0]) + (p0[0] - p2[0]) * (gy - p2[1])) / den
                w2 = 1.0 - w0 - w1
                inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
                if not inside.any():
                    continue
                d = w0 * p0[2] + w1 * p1[2] + w2 * p2[2]
                sub = zbuf[ay:by + 1, ax:bx + 1]
                upd = inside & (d > sub)
                if not upd.any():
                    continue
                sub[upd] = d[upd]
                col = np.array(gcol, dtype=np.float32) * shade[t]
                block = img[ay:by + 1, ax:bx + 1]
                block[upd] = col

        img8 = (np.clip(img, 0, 1) * 255).astype(np.uint8)
        views.append(Image.fromarray(img8))

    combined = Image.new("RGB", (width * len(views), height), (255, 255, 255))
    for i, im in enumerate(views):
        combined.paste(im, (i * width, 0))
    combined.save(out_path)
    return combined


# ------------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True, help="*_specification.json from GarmentCode")
    ap.add_argument("--out", default="./runs/bypass_rc/3d")
    ap.add_argument("--tag", default="garment")
    ap.add_argument("--res", type=float, default=1.0, help="box mesh vertex spacing in cm")
    ap.add_argument("--body", default=None, help="body obj (default mean_all)")
    ap.add_argument("--no-body", action="store_true")
    ap.add_argument("--no-preview", action="store_true")
    args = ap.parse_args()

    from pygarment.meshgen.boxmeshgen import BoxMesh

    os.makedirs(args.out, exist_ok=True)
    bm = BoxMesh(args.spec, args.res)
    bm.load()
    V = np.asarray(bm.vertices, dtype=np.float64)
    F = np.asarray(bm.faces, dtype=np.int64)
    print("[spec2obj] panels: %s" % ", ".join(bm.panelNames))
    print("[spec2obj] verts=%d faces=%d stitches=%d" % (len(V), len(F), len(bm.stitches)))

    garment_obj = os.path.join(args.out, "%s_garment.obj" % args.tag)
    write_obj(garment_obj, V, F, name="%s box mesh (cm, Y up)" % args.tag)

    body_V = body_F = None
    body_obj = args.body
    if body_obj is None and not args.no_body:
        cand = os.path.join(REPO_ROOT, "repos", "GarmentCodeRC-main", "assets", "bodies", "mean_all.obj")
        if os.path.exists(cand):
            body_obj = cand
    if body_obj and not args.no_body and os.path.exists(body_obj):
        body_V, body_F = read_obj(body_obj)
        if body_V[:, 1].max() < 5.0:      # the shipped body is in metres
            body_V = body_V * 100.0
            print("[spec2obj] body scaled m -> cm")
        body_out = body_V.copy()
        write_obj(os.path.join(args.out, "%s_body.obj" % args.tag), body_out, body_F,
                  name="mean_all body (cm, Y up)")

    if not args.no_preview:
        png = os.path.join(args.out, "%s_preview.png" % args.tag)
        render_views(V, F, (0.42, 0.55, 0.78), png, body_V=body_V, body_F=body_F)
        print("[spec2obj] preview -> %s" % png)

    # ---- semantic groups: which OBJ vertex belongs to which pattern panel / seam.
    # bm.stitch_segmentation[i] is either a panel name (non-stitch vertex) or a list of
    # "stitch_<id>" strings (a vertex welded by stitching); bm.verts_glob_loc[i] lists the
    # (panel, local id) pairs that were merged into that global vertex.
    groups = {
        "schema": "gcstudio/groups/1",
        "unit": "cm",
        "up_axis": "Y",
        "panels": {name: [] for name in bm.panelNames},   # panel -> [obj vertex ids]
        "faces": {name: [] for name in bm.panelNames},    # panel -> [obj face ids]
        "stitches": {},                                   # stitch id -> [obj vertex ids]
        "stitch_panels": {},                              # stitch id -> [panel_a, panel_b]
    }
    vertex_panels = {}
    n_stitch_verts = 0
    for i in range(len(bm.vertices)):
        seg = bm.stitch_segmentation[i]
        if isinstance(seg, str):
            names = {seg}
        else:
            n_stitch_verts += 1
            names = {p_name for p_name, _loc in bm.verts_glob_loc[i]}
            for s in seg:
                if isinstance(s, str) and s.startswith("stitch_"):
                    groups["stitches"].setdefault(s.split("_", 1)[1], []).append(i)
        vertex_panels[i] = names
        for name in names:
            groups["panels"].setdefault(name, []).append(i)

    for k, stitch in enumerate(bm.stitches):
        groups["stitch_panels"][str(k)] = [stitch.panel_1, stitch.panel_2]

    for f_idx, face in enumerate(bm.faces):
        counts = {}
        for v in face:
            for name in vertex_panels.get(int(v), ()):
                counts[name] = counts.get(name, 0) + 1
        if counts:
            groups["faces"][max(counts.items(), key=lambda kv: kv[1])[0]].append(f_idx)

    groups_path = os.path.join(args.out, "%s_groups.json" % args.tag)
    with open(groups_path, "w") as f:
        json.dump(groups, f, indent=1)
    print("[spec2obj] groups: %d stitch verts, waist seams: %s" % (
        n_stitch_verts,
        [k for k, v in groups["stitch_panels"].items()
         if any("torso" in p for p in v) and any("skirt" in p for p in v)],
    ))

    info = {
        "groups": os.path.basename(groups_path),
        "spec": os.path.abspath(args.spec),
        "panels": list(bm.panelNames),
        "n_verts": int(len(V)),
        "n_faces": int(len(F)),
        "n_stitches": int(len(bm.stitches)),
        "bbox_min": V.min(0).round(3).tolist(),
        "bbox_max": V.max(0).round(3).tolist(),
        "units": "cm",
        "up_axis": "Y",
    }
    with open(os.path.join(args.out, "%s_info.json" % args.tag), "w") as f:
        json.dump(info, f, indent=2)
    print(json.dumps(info, indent=2))


if __name__ == "__main__":
    main()
