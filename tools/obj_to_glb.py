#!/usr/bin/env python
"""Combine a garment OBJ and the body OBJ into one coloured GLB for quick viewing.

Windows: double-click the .glb to open it in the built-in 3D Viewer (no install).
Blender: File -> Import -> glTF 2.0 (.glb).
The garment is tinted blue, the body light grey, so orientation is obvious.
"""
import argparse
import pathlib

import numpy as np
import trimesh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--garment', required=True)
    ap.add_argument('--body', default='')
    ap.add_argument('--out', required=True)
    ap.add_argument('--garment-color', default='0.42,0.55,0.78')
    ap.add_argument('--body-color', default='0.80,0.80,0.82')
    args = ap.parse_args()

    def colour(s):
        return [float(x) for x in s.split(',')][:3]

    scene = trimesh.Scene()
    g = trimesh.load(args.garment, process=False)
    if isinstance(g, trimesh.Scene):
        g = trimesh.util.concatenate([m for m in g.geometry.values()])
    g.visual = trimesh.visual.TextureVisuals()  # drop any mtl reference
    g.visual = trimesh.visual.ColorVisuals(mesh=g, vertex_colors=colour(args.garment_color))
    scene.add_geometry(g, geom_name='garment')
    if args.body:
        b = trimesh.load(args.body, process=False)
        if isinstance(b, trimesh.Scene):
            b = trimesh.util.concatenate([m for m in b.geometry.values()])
        b.visual = trimesh.visual.ColorVisuals(mesh=b, vertex_colors=colour(args.body_color))
        scene.add_geometry(b, geom_name='body')

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(scene.export(file_type='glb'))
    print('[glb] %d geometries -> %s (%.2f MB)' % (len(scene.geometry), out, out.stat().st_size / 1e6))


if __name__ == '__main__':
    main()