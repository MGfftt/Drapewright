"""Headless Blender cloth draping for a gcstudio package.

Usage (inside Blender):
  blender.exe -b --factory-startup --python-exit-code 1 --python studio/sim/cloth_setup.py -- \
      --package studio/runs/smoke1 --out studio/runs/smoke1/sim --frames 72

Reads <package>/sidecar.json for the garment/body OBJ paths (unit: cm, up: Y),
converts to metres + Z-up, pins the fitted top of the garment to the body,
runs the cloth solver, exports a .glb and renders 3 orthographic views.

Prints a single line "SIM_RESULT {json}" at the end (also written to sim.json).
"""
import argparse
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

CM = 0.01


# ---------------------------------------------------------------- utilities
def log(msg):
    print(f"[cloth] {msg}", flush=True)


def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--package", required=True)
    p.add_argument("--out", default=None)
    p.add_argument("--frames", type=int, default=72)
    p.add_argument("--quality", type=int, default=8)
    p.add_argument("--pin-mode", default="both", choices=["proximity", "topedge", "both"])
    p.add_argument("--pin-dist", type=float, default=0.03, help="metres")
    p.add_argument("--pin-zmin", type=float, default=0.0,
                   help="metres; 0 = auto (55%% of body height)")
    p.add_argument("--max-pin-ratio", type=float, default=0.55)
    p.add_argument("--config", default=None, help="json with cloth overrides")
    p.add_argument("--no-render", action="store_true")
    p.add_argument("--init-wrap", default="affine", choices=["affine", "radial", "none"],
                   help="pre-place the box-mesh panels near the body before the solve")
    p.add_argument("--wrap-margin", type=float, default=0.012, help="metres")
    p.add_argument("--no-bake", action="store_true", help="import + setup only (probe)")
    p.add_argument("--pin-sleeves", action="store_true",
                   help="diagnostic: weld the sleeve vertices in place (no sleeve drape)")
    p.add_argument("--save-blend", action="store_true",
                   help="also write <tag>_drape.blend (open it in Blender to inspect/edit)")
    p.add_argument("--tag", default="sim")
    return p.parse_args(argv)


def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.objects):
        for item in list(block):
            if item.users == 0:
                block.remove(item)


def import_obj(path):
    before = set(bpy.data.objects)
    bpy.ops.wm.obj_import(filepath=str(path), forward_axis="NEGATIVE_Z", up_axis="Y")
    new = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in new if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh imported from {path}")
    # merge multi-object imports into the first one
    if len(meshes) > 1:
        bpy.ops.object.select_all(action="DESELECT")
        for o in meshes:
            o.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        bpy.ops.object.join()
        meshes = [bpy.context.view_layer.objects.active]
    return meshes[0]


def apply_scale(obj, factor):
    """Uniform cm->m scale, then bake scale *and* the import rotation into the mesh.

    The OBJ importer stores the axis conversion in matrix_world, so local coordinates
    still have y = height and z = depth.  Any code that edits obj.data.vertices
    directly (wrap_affine, pin selection) must therefore work in world axes, which is
    only true after the rotation is applied too.
    """
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    obj.scale = (factor, factor, factor)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    assert obj.matrix_world == Matrix.Identity(4), "transform_apply left a non-identity matrix"


def world_bbox(obj):
    mw = obj.matrix_world
    pts = [mw @ v.co for v in obj.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


def evaluated_bbox(obj):
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = ev.to_mesh()
    mw = ev.matrix_world
    pts = [mw @ v.co for v in mesh.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ev.to_mesh_clear()
    return lo, hi


def static_copy(obj, name):
    """Snapshot the evaluated mesh (modifiers applied at the current frame).

    The glTF exporter re-evaluates the depsgraph while it writes, and for a baked
    cloth that can pick up frame 1 (the flat panels) instead of the drape we are
    looking at.  Freezing the evaluated mesh into a plain object sidesteps that: the
    copy carries no modifiers, so whatever frame the exporter touches, the geometry
    stays the drape.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(ev)
    dup = bpy.data.objects.new(name, mesh)
    dup.matrix_world = obj.matrix_world.copy()
    bpy.context.scene.collection.objects.link(dup)
    return dup


def boundary_vertex_indices(mesh):
    """Vertices on an open edge.

    mesh.edges can still be empty right after an OBJ import (Blender derives the edge
    list lazily), so count the edges from the polygons instead of trusting mesh.edges.
    """
    count = {}
    for poly in mesh.polygons:
        vs = list(poly.vertices)
        for k in range(len(vs)):
            a, b = vs[k], vs[(k + 1) % len(vs)]
            key = (a, b) if a < b else (b, a)
            count[key] = count.get(key, 0) + 1
    out = set()
    for (a, b), n in count.items():
        if n == 1:
            out.add(a)
            out.add(b)
    return out


def nearest_distances(obj, bvh):
    mw = obj.matrix_world
    out = []
    for v in obj.data.vertices:
        co = mw @ v.co
        hit = bvh.find_nearest(co)
        out.append((hit[3] if hit and hit[3] is not None else 1e9))
    return out


def torso_bvh(body, x_limit=0.26):
    """BVH of the torso only, so a snap can never land on an arm.

    Without this, the garment's top ring (which sits around 1.20-1.37 m on a
    strapless dress) snaps its highest vertices onto the deltoids and the render
    grows two spaghetti straps out of nowhere.
    """
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(body.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if abs(v.co.x) > x_limit], context="VERTS")
    verts = [v.co.copy() for v in bm.verts]
    bm.verts.index_update()
    polys = [tuple(v.index for v in f.verts) for f in bm.faces]
    bm.free()
    return BVHTree.FromPolygons(verts, polys)


def snap_vertices_to_body(garment, bvh, ids, offset=0.010):
    """Pull the given vertices onto the body surface, offset outward.

    The box mesh places each panel on a box about twice the body size, so after the
    affine shrink the garment's top opening still floats a few centimetres off the
    chest.  Left alone the solver hangs the whole sheet from that ring and the neckline
    flares into a funnel; snapping the pinned ring onto the skin fixes the silhouette
    without touching the rest of the mesh.
    """
    moved = 0
    for i in ids:
        v = garment.data.vertices[i]
        hit = bvh.find_nearest(v.co)
        if not hit or hit[0] is None:
            continue
        v.co = hit[0] + hit[1] * offset
        moved += 1
    return moved


def torso_extent(body, z_lo, z_hi, x_limit=0.30, pct=98.0):
    """Half width (x) and half depth (y) of the torso in a height band.

    Blender is Z-up after import: x = width, y = depth, z = height.  A-pose arms sit
    inside the band near the shoulders, so the extents use a percentile instead of the
    maximum -- a few stray arm vertices must not decide the garment's scale.
    """
    mw = body.matrix_world
    xs, ys = [], []
    for v in body.data.vertices:
        co = mw @ v.co
        if not (z_lo <= co.z <= z_hi):
            continue
        if abs(co.x) > x_limit:
            continue
        xs.append(abs(co.x))
        ys.append(abs(co.y))
    if not xs:
        return 0.0, 0.0, 0
    xs.sort()
    ys.sort()

    def q(arr):
        return arr[int(pct / 100.0 * (len(arr) - 1))]

    return q(xs), q(ys), len(xs)



def _principal_axis(points):
    """(mean, unit principal direction) of a point cloud, no numpy needed."""
    n = len(points)
    mean = Vector((0.0, 0.0, 0.0))
    for p in points:
        mean = mean + p
    mean = mean / n
    cov = [[0.0] * 3 for _ in range(3)]
    for p in points:
        d = p - mean
        for i in range(3):
            for j in range(3):
                cov[i][j] += d[i] * d[j]
    v = Vector((1.0, 0.35, 0.1)).normalized()
    for _ in range(80):
        w = Vector((sum(cov[i][j] * v[j] for j in range(3)) for i in range(3)))
        if w.length < 1e-12:
            return mean, Vector((1.0, 0.0, 0.0))
        v = w.normalized()
    return mean, v


def arm_profile(body, sign):
    """Fit one arm of the body: (origin, axis, radius table).

    sign = -1 for the right arm (negative x), +1 for the left.  The radius table is a
    median distance from the axis in 3 cm bins along the arm, so a sleeve can follow
    the arm instead of sitting on one constant tube.
    """
    mw = body.matrix_world
    pts = []
    for v in body.data.vertices:
        q = mw @ v.co
        if sign * q.x > 0.17 and 0.70 < q.z < 1.70:
            pts.append(q)
    if len(pts) < 400:
        return None
    o, d = _principal_axis(pts)
    if d.x * sign < 0:
        d = -d
    d = d.normalized()
    bins = {}
    for q in pts:
        rel = q - o
        t = rel.dot(d)
        r = (rel - d * t).length
        if r > 0.25:
            continue
        bins.setdefault(round(t / 0.03) * 0.03, []).append(r)
    table = []
    for t in sorted(bins):
        vals = sorted(bins[t])
        if len(vals) >= 8:
            table.append((t, vals[len(vals) // 2]))
    if not table:
        return None
    side_name = "right" if sign < 0 else "left"
    log(f"arm-profile {side_name}: origin "
        f"({o.x:.2f},{o.y:.2f},{o.z:.2f}) axis ({d.x:.2f},{d.y:.2f},{d.z:.2f}) "
        f"t {table[0][0]:.2f}..{table[-1][0]:.2f} m, radius "
        f"{min(r for _, r in table)*100:.1f}..{max(r for _, r in table)*100:.1f} cm")
    return o, d, table


def _radius_at(table, t):
    """Piecewise-linear lookup in the arm radius table."""
    if not table:
        return 0.05
    if t <= table[0][0]:
        return table[0][1]
    if t >= table[-1][0]:
        return table[-1][1]
    for (t0, r0), (t1, r1) in zip(table, table[1:]):
        if t0 <= t <= t1:
            k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
            return r0 + (r1 - r0) * k
    return table[-1][1]


def fold_sleeves(garment, body, groups, margin, ring_by_side=None):
    """Roll all of one side's sleeve/cuff panels onto that arm as one tube.

    Why: GarmentCodeRC lays the sleeve panels flat inside the same box as the torso, so
    the global x/y compression used for the body dragged the sleeve tube through the
    torso shell and the solve exploded (measured: bbox reach 207 m).  Here each side is
    mapped onto a cylinder around the measured arm, keeping its along-arm coordinate and
    rolling only its cross-arm coordinate, so the sleeve starts out already worn.

    One frame is used for the whole side (arm axis, one outward direction, one radius),
    which matters because the front/back halves and the cuffs share welded seam vertices:
    a per-panel map gave those vertices two different answers, stretched the seam edges
    12x and the solver blew up.  The armhole ring is welded to the torso, so it is not in
    any sleeve panel list; without pulling it onto the same tube the shoulder faces were
    stretched 12x, so it is included here.

    Returns (vertex ids moved, stats per side).
    """
    mw = garment.matrix_world
    moved = set()
    stats = {}
    for side, sign in (("right", -1.0), ("left", 1.0)):
        prof = arm_profile(body, sign)
        if prof is None:
            log(f"fold-sleeves {side}: no arm found, sleeves left in place")
            continue
        o, d, table = prof
        e1 = d.normalized()

        ids = set()
        panels = []
        for name, panel_ids in groups["panels"].items():
            low = name.lower()
            if not ("sleeve" in low or low.startswith("sl_")):
                continue
            if (side == "right") != ("right" in low):
                continue
            ids.update(panel_ids)
            panels.append(name)
        ring = [i for i in (ring_by_side or {}).get(side, [])]
        ids.update(ring)
        if not panels:
            continue
        ids = sorted(ids)

        pts = [mw @ garment.data.vertices[i].co for i in ids]
        ts = [(q - o).dot(e1) for q in pts]
        # the panels reach a few centimetres past the measured arm profile; unchecked they
        # put cloth inside the neck/head, and that deep overlap is what blew the solve up
        t_lo, t_hi = table[0][0] + 0.01, table[-1][0] - 0.01
        ts = [min(max(t, t_lo), t_hi) for t in ts]
        radials = [(q - o) - e1 * t for q, t in zip(pts, ts)]
        # one common frame, so two panels sharing a seam vertex agree on its new place
        n0 = Vector((0.0, 0.0, 0.0))
        for rad in radials:
            n0 = n0 + rad
        n0 = n0 - e1 * n0.dot(e1)
        if n0.length < 1e-6:
            n0 = Vector((sign, 0.0, 0.0)) - e1 * (e1.x * sign)
        n0.normalize()
        side_dir = e1.cross(n0).normalized()
        us = [rad.dot(side_dir) for rad in radials]
        u_lo, u_hi = min(us), max(us)
        span = max(u_hi - u_lo, 1e-4)
        u_mid = 0.5 * (u_lo + u_hi)
        t_mid = 0.5 * (min(ts) + max(ts))
        arm_r = _radius_at(table, t_mid) + margin
        # never let the sheet lap over itself: at most 0.9 of a turn of arc, which makes a
        # wide panel a slightly larger (looser) tube instead of a folded-over one
        # cap the wrapped arc at 170 deg: with a full turn the sheet laps over itself and
        # the overlapping layers fight each other, which is enough to blow the solve up
        r_side = max(arm_r, span / math.radians(170.0))
        for i, t, u in zip(ids, ts, us):
            theta = (u - u_mid) / r_side
            garment.data.vertices[i].co = (
                o + e1 * t
                + n0 * (r_side * math.cos(theta))
                + side_dir * (r_side * math.sin(theta))
            )
            moved.add(i)
        stats[side] = {
            "panels": len(panels),
            "verts": len(ids),
            "r": round(r_side, 4),
            "arc_deg": round(math.degrees(span / r_side), 1),
            "t": [round(min(ts), 3), round(max(ts), 3)],
            "ring": len(ring),
        }
        log(f"fold-sleeves {side}: {len(panels)} panels, {len(ids)} verts -> tube r "
            f"{r_side*100:.1f} cm (arm {_radius_at(table, t_mid)*100:.1f}), arc "
            f"{stats[side]['arc_deg']:.0f} deg, t {min(ts):.3f}..{max(ts):.3f} m, "
            f"ring {len(ring)}")
    return moved, stats


def wrap_to_body(garment, body, margin, waist_z, ref_ids=None, exclude=None):
    """Shrink the GarmentCode box mesh (about twice the body size) down to body size.

    Measured on a 7-float strapless dress: the box is 89 x 55 cm around a ~40 x 26 cm
    torso, i.e. the panels start 10-25 cm off the skin.  Cloth physics cannot close
    that gap in a few seconds, so we scale the box in x/y.  Scaling (not projecting
    each vertex onto the surface) keeps every panel flat and separated -- vertices
    never pile on top of each other -- while moving the seams to within a couple of
    millimetres of the body.

    One uniform scale for the whole garment, derived from the *torso panels* rather than
    from the whole-garment bounding box.  The bounding box is not a yardstick: a tiered
    skirt is 1.7 m wide on the box while the torso panels are 66 cm, so a box-based scale
    (0.21) squeezed the bodice into a 14 cm strip and flattened every skirt tier into a
    ribbon (measured: front/back view was a single vertical sliver).  The torso panels do
    have a stable, meaningful width, so the scale maps *them* onto the body and every other
    panel follows by the same factor -- which also keeps the gathering of a ruffled or
    tiered skirt (a 1.7 m wide skirt becomes 1.0 m of perimeter around a 0.9 m body).
    """
    g_lo, g_hi = world_bbox(garment)
    ref = [i for i in (ref_ids or ()) if 0 <= i < len(garment.data.vertices)]
    if len(ref) >= 50:
        vs = [garment.matrix_world @ garment.data.vertices[i].co for i in ref]
        box_x = max(abs(v.x) for v in vs)
        box_y = max(abs(v.y) for v in vs)
        ref_note = f"{len(ref)} torso verts"
    else:
        box_x = max(abs(g_lo.x), abs(g_hi.x))
        box_y = max(abs(g_lo.y), abs(g_hi.y))
        ref_note = "whole box (no torso panels in groups.json)"
    if box_x <= 0.02 or box_y <= 0.02:
        raise RuntimeError(f"degenerate garment bbox ({box_x}, {box_y})")

    # body half width/depth in 4 cm bands, so the scale can follow the torso
    bands = {}
    z = g_lo.z
    while z < g_hi.z + 0.04:
        hx, hy, n = torso_extent(body, z, z + 0.04)
        if n >= 40 and hx > 0.01 and hy > 0.01:
            bands[round(z, 3)] = (hx, hy)
        z += 0.04
    if not bands:
        raise RuntimeError("could not measure the body extent in any height band")

    waist_hx, waist_hy, _ = torso_extent(body, waist_z - 0.04, waist_z + 0.04)
    if waist_hx <= 0.01:
        waist_hx, waist_hy = max(b[0] for b in bands.values()), max(b[1] for b in bands.values())
    waist_key = round(min(bands), 3)

    # One width for the whole torso instead of one per 4 cm band.  The band widths are
    # not smooth: where the A-pose arms enter the band the 98th percentile jumps from the
    # chest (17 cm) to the arms (30 cm), so two neighbouring vertices got kx 0.38 and 0.70
    # and their edge was stretched 10x -- which is enough to blow the solve up.  The torso
    # is close to a constant width anyway, so a median over the bands above the waist is
    # both smoother and closer to the truth.
    torso_keys = [k for k in bands if waist_key <= k <= waist_key + 0.40]
    if not torso_keys:
        torso_keys = list(bands)

    def _median(vals):
        vals = sorted(vals)
        return vals[len(vals) // 2]

    hx_above = _median([bands[k][0] for k in torso_keys])
    hy_above = _median([bands[k][1] for k in torso_keys])

    # A single (kx, ky) for every vertex: one layout scale, so the seams stay welded and
    # the relative width of every panel is preserved.  Height-graded scales were tried and
    # dropped -- they squeezed gathered skirts onto the calves and tore edges at the waist.
    kx = (hx_above + margin) / box_x
    ky = (hy_above + margin) / box_y

    for i, v in enumerate(garment.data.vertices):
        if exclude and i in exclude:
            continue
        v.co.x *= kx
        v.co.y *= ky
    g_now = world_bbox(garment)
    log(f"wrap-to-body: torso {2*box_x*100:.1f}x{2*box_y*100:.1f} cm ({ref_note}) -> scale "
        f"x{kx:.3f} y{ky:.3f}; body {2*hx_above*100:.1f}x{2*hy_above*100:.1f} cm above the "
        f"waist; garment {2*(g_hi.x-g_lo.x)*100:.0f} -> "
        f"{2*(g_now[1].x-g_now[0].x)*100:.0f} cm wide")
    return {"mode": "torso-ref", "waist_z": round(waist_z, 4),
            "kx": round(kx, 4), "ky": round(ky, 4),
            "ref_half_x": round(box_x, 4), "ref_half_y": round(box_y, 4),
            "body_half_x": round(hx_above, 4), "body_half_y": round(hy_above, 4),
            "width_after": round(float(g_now[1].x - g_now[0].x), 4)}


def restore_skirt_flare(garment, skirt_ids, waist_z, kx, y_center, taper=0.25):
    """Undo most of the layout compression below the waist, so skirts keep their flare.

    wrap_to_body shrinks every vertex towards the body, which is right for a bodice but
    wrong for a gathered skirt: the hem ends up as wide as the hips, the pleats fold into
    each other and the cloth clings to the legs (measured: a full A-line came out as a
    straight tube).  The layout box keeps the skirt's own width, so below the waist the
    compression is faded out over `taper` metres: at the (welded) waist seam the factor is
    unchanged, 25 cm lower it is 1/kx, i.e. the hem keeps the width it had in the box.
    """
    if not skirt_ids or kx <= 0 or kx >= 1.0 or waist_z is None:
        return {}
    gain = 1.0 / kx
    moved, max_mul = 0, 1.0
    for i in skirt_ids:
        v = garment.data.vertices[i]
        t = 0.0
        if v.co.z < waist_z:
            t = min(1.0, (waist_z - v.co.z) / taper)
        mul = 1.0 + (gain - 1.0) * t
        v.co.x *= mul
        v.co.y = y_center + (v.co.y - y_center) * mul
        moved += 1
        max_mul = max(max_mul, mul)
    log(f"restore-skirt-flare: {moved} verts, width x{gain:.2f} by {taper:.2f} m below "
        f"the waist (max {max_mul:.2f})")
    return {"verts": moved, "gain": round(gain, 3), "tapers_m": taper}


def edge_pairs(obj):
    """Unique edges of the base mesh as vertex index pairs."""
    mesh = obj.data
    seen = set()
    out = []
    for poly in mesh.polygons:
        vs = list(poly.vertices)
        n = len(vs)
        for k in range(n):
            a, b = vs[k], vs[(k + 1) % n]
            key = (a, b) if a < b else (b, a)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def edge_lengths(obj, pairs=None):
    """Lengths of the given edges (default: every unique edge)."""
    mesh = obj.data
    if pairs is None:
        pairs = edge_pairs(obj)
    return [(mesh.vertices[a].co - mesh.vertices[b].co).length for a, b in pairs]


# ---------------------------------------------------------------- scene build
def main():
    args = parse_args()
    t_start = time.time()
    pkg = Path(args.package).resolve()
    out = Path(args.out).resolve() if args.out else pkg / "sim"
    out.mkdir(parents=True, exist_ok=True)

    sidecar = json.loads((pkg / "sidecar.json").read_text(encoding="utf-8"))
    garment_path = pkg / sidecar["garment_obj"]
    body_path = pkg / sidecar["body_obj"]

    cfg = {
        "mass": 0.30,
        "quality": args.quality,
        "tension_stiffness": 20.0,
        "compression_stiffness": 8.0,
        "shear_stiffness": 5.0,
        "bending_stiffness": 2.0,
        "air_damping": 1.0,
        "time_scale": 1.0,
        "pin_stiffness": 1.0,
        "collision_distance": 0.005,
        "collision_friction": 0.7,
        "self_collision": True,
        "self_distance": 0.002,
        "collision_quality": 5,
        "body_thickness": 0.004,
    }
    if args.config:
        cfg.update(json.loads(Path(args.config).read_text(encoding="utf-8")))

    reset_scene()
    log(f"importing {garment_path.name} / {body_path.name}")
    garment = import_obj(garment_path)
    body = import_obj(body_path)
    for obj, name in ((garment, "garment"), (body, "body")):
        apply_scale(obj, CM)
        obj.name = name

    g_lo, g_hi = world_bbox(garment)
    b_lo, b_hi = world_bbox(body)
    H = b_hi.z - b_lo.z
    base_edges = edge_pairs(garment)
    base_edge_len = edge_lengths(garment, base_edges)
    base_co = [v.co.copy() for v in garment.data.vertices]
    log(f"body height {H:.3f} m, garment bbox {tuple(round(x,3) for x in g_lo)}..{tuple(round(x,3) for x in g_hi)}")

    # ---- collision body
    body.data.materials.clear()
    mat_body = bpy.data.materials.new("body_mat")
    mat_body.diffuse_color = (0.62, 0.62, 0.65, 1.0)
    body.data.materials.append(mat_body)
    col = body.modifiers.new("Collision", "COLLISION")
    col.settings.thickness_outer = cfg["body_thickness"]
    col.settings.cloth_friction = 50.0
    col.settings.damping_factor = 0.5

    # ---- pin group
    depsgraph = bpy.context.evaluated_depsgraph_get()
    bvh = BVHTree.FromObject(body, depsgraph)
    dists = nearest_distances(garment, bvh)
    boundary = boundary_vertex_indices(garment.data)
    mw = garment.matrix_world
    zmin = args.pin_zmin or (b_lo.z + 0.55 * H)
    top_threshold = g_hi.z - 0.015

    # ---- semantic panel labels (needed before the wrap: they tell us where the waist is)
    groups = None
    if sidecar.get("groups"):
        gpath = pkg / sidecar["groups"]
        if gpath.is_file():
            groups = json.loads(gpath.read_text(encoding="utf-8"))

    def _z(i):
        return (garment.matrix_world @ garment.data.vertices[i].co).z

    is_skirt_name = lambda n: ("skirt" in n.lower()) or ("pants" in n.lower())
    is_sleeve_name = lambda n: "sleeve" in n.lower()
    waist, armhole = [], []
    if groups:
        for sid, pnames in groups.get("stitch_panels", {}).items():
            lower = [p for p in pnames if is_skirt_name(p)]
            upper = [p for p in pnames if not is_skirt_name(p)]
            sleeve = [p for p in pnames if is_sleeve_name(p)]
            body_side = [p for p in pnames if not is_sleeve_name(p)]
            if lower and upper:
                waist += groups["stitches"].get(sid, [])
            if sleeve and body_side:
                # armhole seam: anchors the sleeve at the shoulder so it can hang
                armhole += groups["stitches"].get(sid, [])
    waist_z_guess = sorted(_z(i) for i in waist)[len(waist) // 2] if waist else (b_lo.z + 0.58 * H)
    log(f"semantic seams: waist {len(waist)} verts @ z~{waist_z_guess:.3f} m, "
        f"armhole {len(armhole)} verts")

    # Sleeves cannot be handled by the x/y compression: their flat panels live inside
    # the same box as the torso, so compressing drags the sleeve tube through the torso
    # shell and the solve explodes (measured: bbox reach 207 m).  They are rolled onto
    # the measured arm instead (fold_sleeves), and the compression skips them.
    is_sleeve_panel = lambda n: ("sleeve" in n.lower()) or n.lower().startswith("sl_")
    sleeve_ids = set()
    if groups:
        for name, ids in groups["panels"].items():
            if is_sleeve_panel(name):
                sleeve_ids.update(ids)
    ring_by_side = {"right": set(), "left": set()}
    if groups:
        for sid, pnames in groups.get("stitch_panels", {}).items():
            if any(is_sleeve_panel(n) for n in pnames) and any(
                    not is_sleeve_panel(n) for n in pnames):
                ids = groups["stitches"].get(sid, [])
                side = "right" if any("right" in n.lower() for n in pnames) else "left"
                ring_by_side[side].update(ids)
    ring_ids = set().union(*ring_by_side.values()) if ring_by_side else set()
    # the armhole ring is welded to the torso: let the body compression move it with the
    # torso first, then the fold puts it on the sleeve tube.  Excluding it from the
    # compression instead left the shoulder faces stretched 10x.
    compress_exclude = sleeve_ids - ring_ids
    # reference width for the layout scale: the torso panels (they sit on the body, unlike
    # a 1.7 m wide tiered skirt which would make the scale meaningless)
    torso_ids = set()
    skirt_ids = set()
    if groups:
        for name, ids in groups["panels"].items():
            low = name.lower()
            if "torso" in low and not is_sleeve_panel(name):
                torso_ids.update(ids)
            if is_skirt_name(name):
                skirt_ids.update(ids)
    warnings = []
    sleeve_stats = {}
    wrap_stats = {}
    if args.init_wrap == "affine":
        wrap_stats = wrap_to_body(garment, body, args.wrap_margin, waist_z_guess,
                                  ref_ids=torso_ids, exclude=compress_exclude)
        if skirt_ids:
            torso_c = (b_lo + b_hi) * 0.5
            wrap_stats["skirt_flare"] = restore_skirt_flare(
                garment, skirt_ids, wrap_stats.get("waist_z"), wrap_stats.get("kx", 1.0),
                torso_c.y)
        bpy.context.view_layer.update()
        # vertices moved, so refresh the distances used by the pin heuristic
        dists = nearest_distances(garment, bvh)

    if sleeve_ids:
        moved, sleeve_stats = fold_sleeves(garment, body, groups, args.wrap_margin,
                                          ring_by_side=ring_by_side)
        if moved:
            sleeve_ids = moved
            bpy.context.view_layer.update()
            log(f"fold-sleeves: {len(sleeve_ids)} verts moved onto the arms")
            dists = nearest_distances(garment, bvh)
        else:
            warnings.append("sleeve panels could not be placed on the arms (arm not "
                            "measured); they stay flat next to the body")
            log("WARNING " + warnings[-1])
        # initial strain sanity check: a fold that stretches an edge 10x means two
        # panels were mapped onto the same place and the solve will blow up
        now = edge_lengths(garment, base_edges)
        # ignore degenerate edges: BoxMesh leaves a few sub-millimetre edges where seams
        # were welded, and their ratio explodes without meaning anything
        ratios = sorted(n / b for n, b in zip(now, base_edge_len) if b > 0.002)
        if ratios:
            n_bad = sum(1 for r in ratios if r > 3.0)
            rated = sorted(((n / b, a, b2) for (a, b2), n, b in
                            zip(base_edges, now, base_edge_len) if b > 0.002), reverse=True)
            wrap_stats["worst_edges"] = [[int(a), int(b2), round(float(r), 2)]
                                         for r, a, b2 in rated[:8]]
            wrap_stats["edge_stretch_max"] = round(ratios[-1], 2)
            wrap_stats["edge_stretch_p99"] = round(ratios[int(len(ratios) * 0.99)], 2)
            def _tag(i):
                tags = []
                if i in (sleeve_ids or ()):
                    tags.append("sleeve")
                if i in ring_ids:
                    tags.append("ring")
                if i in (compress_exclude or ()):
                    tags.append("nocompress")
                return ",".join(tags) or "-"
            for r, a, b2 in rated[:6]:
                pa = garment.matrix_world @ garment.data.vertices[a].co
                pb = garment.matrix_world @ garment.data.vertices[b2].co
                log(f"  strain {r:.1f}x {a}[{_tag(a)}] {tuple(round(v,3) for v in pa)} "
                    f"(base {tuple(round(v,3) for v in base_co[a])}) -- {b2}[{_tag(b2)}] "
                    f"{tuple(round(v,3) for v in pb)} "
                    f"(base {tuple(round(v,3) for v in base_co[b2])})")
            log(f"init strain: edge stretch p99 {wrap_stats['edge_stretch_p99']:.2f}x, "
                f"max {wrap_stats['edge_stretch_max']:.2f}x, {n_bad} edges over 3x")

    pins = []
    pin_sources = {}
    if groups:
        torso_verts = set()
        for name, ids in groups["panels"].items():
            if not is_skirt_name(name):
                torso_verts.update(ids)
        # The torso panels' open edge is the top opening of the garment (neckline,
        # shoulder line, or armholes on a sleeved shirt).  On a 7-float strapless
        # dress it is a slanted ring spanning 1.20..1.37 m, so an "almost at the
        # very top" test keeps only 5 vertices; keep the whole ring above the waist
        # instead -- the waist is already pinned, everything in between must hang.
        waist_z = [_z(i) for i in waist] if waist else []
        cutoff = (max(waist_z) - 0.02) if waist_z else top_threshold
        top = [i for i in torso_verts if i in boundary and _z(i) >= cutoff]
        if args.pin_mode in ("proximity", "both", "auto"):
            pins += [(i, dists[i]) for i in waist]
        if args.pin_mode in ("topedge", "both", "auto"):
            pins += [(i, dists[i]) for i in top]
        # The armhole seam is detected but NOT pinned: snapping that ring onto the torso
        # BVH folds the sleeve top through itself and the solve explodes (measured:
        # bounding box grew to 500 m).  Sleeves need arm-surface anchoring (v2).
        pin_sources = {"waist_seam": len(waist), "neck_ring": len(top),
                       "armhole_seam_unpinned": len(armhole)}
    if not pins:  # fallback: geometric heuristic
        for i, v in enumerate(garment.data.vertices):
            z = (mw @ v.co).z
            d = dists[i]
            hit = False
            if args.pin_mode in ("proximity", "both", "auto"):
                hit = (d <= args.pin_dist) and (z >= zmin)
            if not hit and args.pin_mode in ("topedge", "both", "auto"):
                hit = (i in boundary) and (z >= top_threshold) and (d <= 0.06)
            if hit:
                pins.append((i, d))
        pin_sources = {"geometric": len(pins)}
    pins = sorted(set(pins))

    if len(pins) > args.max_pin_ratio * len(garment.data.vertices):
        keep = int(args.max_pin_ratio * len(garment.data.vertices))
        pins = sorted(pins, key=lambda t: t[1])[:keep]
        log(f"pin set capped to {keep} closest vertices")
    log(f"debug: boundary={len(boundary)} torso_verts={len(torso_verts) if groups else 'n/a'} "
        f"top_threshold={top_threshold:.3f} torso_boundary_top="
        f"{max(((mw @ garment.data.vertices[i].co).z for i in torso_verts if i in boundary), default=float('nan')):.3f}")
    if getattr(args, "pin_sleeves", False) and sleeve_ids:
        pins = list(pins) + [(i, 0.0) for i in sorted(sleeve_ids)]
        pin_sources["sleeves_frozen"] = len(sleeve_ids)
    pin_ids = [i for i, _ in pins]
    # frozen sleeve vertices belong on the arms, not on the torso: snapping them to the
    # torso BVH collapses the whole sleeve onto the chest and the solve blows up
    snap_ids = [i for i in pin_ids if i not in sleeve_ids] if sleeve_ids else pin_ids
    snapped = snap_vertices_to_body(garment, torso_bvh(body), snap_ids, offset=0.010)
    log(f"pin count {len(pin_ids)} / {len(garment.data.vertices)} sources={pin_sources} "
        f"(zmin={zmin:.3f}, snapped {snapped} onto the skin)")
    info_pins = pin_sources

    vg = garment.vertex_groups.new(name="pin")
    vg.add(pin_ids, 1.0, "REPLACE")

    # ---- material
    garment.data.materials.clear()
    mat = bpy.data.materials.new("cloth_mat")
    mat.diffuse_color = (0.42, 0.55, 0.78, 1.0)
    mat.use_backface_culling = False
    garment.data.materials.append(mat)

    # ---- cloth modifier
    mod = garment.modifiers.new("Cloth", "CLOTH")
    s = mod.settings
    s.quality = cfg["quality"]
    s.mass = cfg["mass"]
    s.tension_stiffness = cfg["tension_stiffness"]
    s.compression_stiffness = cfg["compression_stiffness"]
    s.shear_stiffness = cfg["shear_stiffness"]
    s.bending_stiffness = cfg["bending_stiffness"]
    s.air_damping = cfg["air_damping"]
    s.time_scale = cfg["time_scale"]
    s.vertex_group_mass = "pin"
    s.pin_stiffness = cfg["pin_stiffness"]
    cs = mod.collision_settings
    cs.use_collision = True
    cs.distance_min = cfg["collision_distance"]
    cs.friction = cfg["collision_friction"]
    cs.use_self_collision = cfg["self_collision"]
    cs.self_distance_min = cfg["self_distance"]
    cs.collision_quality = cfg["collision_quality"]
    mod.point_cache.frame_start = 1
    mod.point_cache.frame_end = args.frames
    mod.point_cache.use_disk_cache = True

    # ---- floor (catch a falling skirt, keeps the sim bounded)
    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(0.0, 0.0, b_lo.z - 0.002))
    floor = bpy.context.object
    floor.name = "floor"
    floor.display_type = "WIRE"
    fcol = floor.modifiers.new("Collision", "COLLISION")

    # ---- shading
    for obj in (garment, body):
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.shade_smooth()

    info = {
        "ok": True,
        "package": str(pkg),
        "frames": args.frames,
        "pin_count": len(pin_ids),
        "pin_sources": info_pins,
        "wrap": wrap_stats,
        "warnings": warnings,
        "vertices": len(garment.data.vertices),
        "faces": len(garment.data.polygons),
        "body_height_m": round(H, 4),
        "garment_bbox_before": [list(map(float, g_lo)), list(map(float, g_hi))],
    }

    scn = bpy.context.scene
    scn.frame_start = 1
    scn.frame_end = args.frames

    if args.no_bake:
        info["baked"] = False
        log("probe only: skipping bake")
    else:
        t0 = time.time()
        log(f"baking {args.frames} frames ...")
        try:
            bpy.ops.ptcache.bake_all(bake=True)
        except Exception as exc:  # noqa: BLE001
            log(f"bake_all failed ({exc}); trying per-modifier bake")
            with bpy.context.temp_override(point_cache=mod.point_cache):
                bpy.ops.ptcache.bake(bake=True)
        info["bake_seconds"] = round(time.time() - t0, 2)
        log(f"bake done in {info['bake_seconds']}s, is_baked={mod.point_cache.is_baked}")
        info["baked"] = bool(mod.point_cache.is_baked)
        scn.frame_set(args.frames)
        bpy.context.view_layer.update()
        lo2, hi2 = evaluated_bbox(garment)
        info["garment_bbox_after"] = [list(map(float, lo2)), list(map(float, hi2))]
        # a healthy drape stays within a couple of metres; anything bigger is a blown-up
        # solve (deep initial self-intersection is the usual cause) and must not be
        # presented as a result
        reach = max(abs(c) for c in list(lo2) + list(hi2))
        info["exploded"] = reach > 5.0
        if info["exploded"]:
            log(f"SIMULATION EXPLODED: bbox reach {reach:.2f} m")
            info["ok"] = False
            info["error"] = ("the cloth blew up (bbox reach %.1f m); usual cause is the "
                             "garment starting deeply self-intersected - retry with a "
                             "smaller --wrap-margin, fewer panels, or --quality 5" % reach)

    # ---- export glb
    glb = out / f"{args.tag}.glb"
    frozen = []
    try:
        frozen.append(static_copy(garment, args.tag + "_garment_drape"))
        frozen.append(static_copy(body, args.tag + "_body_drape"))
        bpy.ops.object.select_all(action="DESELECT")
        for dup in frozen:
            dup.select_set(True)
        bpy.context.view_layer.objects.active = frozen[0]
        bpy.ops.export_scene.gltf(
            filepath=str(glb),
            export_format="GLB",
            use_selection=True,
            export_apply=False,
            export_yup=True,
        )
    finally:
        for dup in frozen:
            bpy.data.objects.remove(dup, do_unlink=True)
    info["glb"] = str(glb)
    info["glb_bytes"] = glb.stat().st_size
    log(f"glb written ({info['glb_bytes']} bytes)")

    # ---- save the whole scene as a .blend, so a human can open it and keep editing
    # (cloth modifiers, baked cache, camera and lights all survive; the point cache is
    # written to disk next to it only if it was baked to disk, otherwise the panel can
    # re-bake from frame 1)
    if args.save_blend:
        try:
            blend = out / f"{args.tag}_drape.blend"
            # re-saving over a previous run makes Blender write <file>.blend1 (a full
            # 34 MB backup); the panel only ever links the .blend, so drop the backup
            bpy.context.preferences.filepaths.save_version = 0
            bpy.ops.wm.save_as_mainfile(filepath=str(blend), check_existing=False,
                                        compress=True)
            stale = blend.with_name(blend.name + '1')
            if stale.exists():
                stale.unlink()
            info["blend"] = str(blend)
            info["blend_bytes"] = blend.stat().st_size
            log(f"blend written ({info['blend_bytes']} bytes)")
        except Exception:  # noqa: BLE001 - a failed save must not lose the glb we have
            info["blend_error"] = traceback.format_exc()
            log("blend save failed:\n" + info["blend_error"])

    # ---- render 3 orthographic views
    if not args.no_render:
        try:
            views = render_views(out, args.tag, g_lo, g_hi, b_lo, b_hi)
            info["views"] = views
        except Exception:  # noqa: BLE001
            info["render_error"] = traceback.format_exc()
            log("render failed:\n" + info["render_error"])

    info["seconds"] = round(time.time() - t_start, 2)
    (out / "sim.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print("SIM_RESULT " + json.dumps(info), flush=True)


def render_views(out, tag, g_lo, g_hi, b_lo, b_hi):
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.render.resolution_x = 640
    scn.render.resolution_y = 900
    scn.render.resolution_percentage = 100
    scn.render.film_transparent = False
    scn.display.shading.light = "STUDIO"
    scn.display.shading.studio_light = "Default"
    scn.display.shading.color_type = "MATERIAL"
    scn.display.shading.show_cavity = True
    scn.display.shading.show_shadows = True
    scn.world = bpy.data.worlds.new("w") if scn.world is None else scn.world
    scn.world.color = (0.9, 0.9, 0.9)

    lo = Vector((min(g_lo.x, b_lo.x), min(g_lo.y, b_lo.y), b_lo.z))
    hi = Vector((max(g_hi.x, b_hi.x), max(g_hi.y, b_hi.y), b_hi.z))
    center = (lo + hi) * 0.5
    height = hi.z - lo.z
    ortho = height * 1.12

    cam_data = bpy.data.cameras.new("cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = ortho
    cam = bpy.data.objects.new("cam", cam_data)
    scn.collection.objects.link(cam)
    scn.camera = cam
    dist = 4.0
    views = [("front", Vector((0, -1, 0))), ("side", Vector((1, 0, 0))), ("back", Vector((0, 1, 0)))]
    paths = []
    for name, direction in views:
        cam.location = center + direction * dist
        cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
        path = out / f"{tag}_{name}.png"
        scn.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        paths.append(str(path))

    # stitch side by side
    try:
        from PIL import Image
        ims = [Image.open(p) for p in paths]
        w = sum(i.width for i in ims)
        h = max(i.height for i in ims)
        sheet = Image.new("RGB", (w, h), (250, 250, 250))
        x = 0
        for im in ims:
            sheet.paste(im, (x, 0))
            x += im.width
        sheet_path = out / f"{tag}_views.png"
        sheet.save(sheet_path)
        paths.append(str(sheet_path))
    except Exception:  # noqa: BLE001
        log("PIL stitch skipped: " + traceback.format_exc().splitlines()[-1])
    return paths


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        print("SIM_ERROR " + json.dumps({"error": err}), flush=True)
        sys.exit(1)
