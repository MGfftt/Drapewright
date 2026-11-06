#!/usr/bin/env python
"""CG-WIN: render a sewing pattern from an existing design.yaml - no model, no GPU.

The eval scripts write `valid_garment_<type>/design.yaml`: the full GarmentCode
design tree with a concrete value (`v:`) for every parameter. GarmentCode needs
two inputs to build a pattern: the *structure* (which components exist) and the
*floats* (the continuous parameters). Both are already in that file, so you can
edit a number and re-render the SVG in about a second instead of re-running the
4.5-minute model load:

    # same pattern the model produced
    python tools/render_pattern.py runs/.../valid_garment_wholebody

    # tweak design.yaml (design.skirt.length.v), try a different body, ...
    python tools/render_pattern.py runs/.../valid_garment_wholebody --out /tmp/pat

The garment type comes from the directory name (`valid_garment_wholebody`,
`valid_garment_upper`, `valid_garment_lower`) or from `--type`.

Why the values are not re-normalised: design.yaml stores *denormalised* numbers
(design.shirt.width.v = 1.05 for a range of [1.0, 1.3]), so the whole design can
be fed to GarmentCode verbatim; `float_dict` therefore holds absolute values and
`invnorm_float=False`. Float values are clipped to their declared range, which
is the usual cause of GarmentCode's 'Start and end of an edge should differ'.
"""
import argparse
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import llava.garment_utils_v2 as gu  # noqa: E402

FLOAT_TYPE = 'float'


def is_leaf(node):
    return isinstance(node, dict) and isinstance(node.get('type'), str) and 'v' in node


def convert(node, path, floats, clip=True):
    """design.yaml tree -> (prediction tree with scalar leaves, {path: float}).

    llava.garment_utils_v2.recursive_change_params_1float() expects the
    *prediction* shape: plain scalars at the leaves, floats supplied separately
    through float_dict (they are the model's [SEG] outputs upstream).
    """
    if not isinstance(node, dict):
        return node
    if is_leaf(node):
        v = node['v']
        if node['type'] == FLOAT_TYPE:
            v = float(v)
            if clip and isinstance(node.get('range'), list) and len(node['range']) == 2:
                lo, hi = float(node['range'][0]), float(node['range'][1])
                if v < lo or v > hi:
                    print('[render] clip %s: %g -> %g (range [%g, %g])' % (path, v, min(max(v, lo), hi), lo, hi))
                v = min(max(v, lo), hi)
            floats[path] = v
        return v
    out = {}
    for key, sub in node.items():
        out[key] = convert(sub, key if path == '' else path + '.' + key, floats, clip)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('design_dir', help='directory holding design.yaml '
                                       '(e.g. .../valid_garment_wholebody)')
    ap.add_argument('--out', default=None, help='output directory (default: design_dir)')
    ap.add_argument('--type', default=None, choices=['wholebody', 'upper', 'lower'],
                    help='garment type (default: parsed from the directory name)')
    ap.add_argument('--body', default=None, help='body measurements yaml, e.g. '
                                                 'assets/bodies/mean_female.yaml')
    ap.add_argument('--no-clip', action='store_true', help='do not clip floats to their range')
    args = ap.parse_args(argv)

    design_dir = os.path.abspath(args.design_dir)
    design_yaml = os.path.join(design_dir, 'design.yaml')
    if not os.path.isfile(design_yaml):
        ap.error('no design.yaml in %s' % design_dir)

    garment_type = args.type
    if garment_type is None:
        base = os.path.basename(design_dir.rstrip('\\/'))
        for kind in ('wholebody', 'upper', 'lower'):
            if base.endswith(kind):
                garment_type = kind
                break
    if garment_type is None:
        ap.error('cannot tell wholebody/upper/lower from the directory name; use --type')

    with open(design_yaml, 'r', encoding='utf-8') as fh:
        design_doc = yaml.safe_load(fh)
    design = design_doc.get('design', design_doc)

    floats = {}
    pred = convert(design, 'design', floats, clip=not args.no_clip)
    print('[render] %s: %d float parameters, %d design nodes'
          % (garment_type, len(floats), len(pred)))
    # which components GarmentCode will actually build - the other parameters are
    # along for the ride (editing e.g. design.skirt.length of a PencilSkirt item
    # changes nothing; edit design.pencil-skirt.length instead)
    meta = pred.get('meta', {})
    print('[render] active components: upper=%s bottom=%s waistband=%s'
          % (meta.get('upper'), meta.get('bottom'), meta.get('wb')))

    out_dir = os.path.abspath(args.out or design_dir)
    os.makedirs(out_dir, exist_ok=True)
    body_path = args.body
    if body_path is None:
        local_body = os.path.join(design_dir, 'body_measurements.yaml')
        body_path = local_body if os.path.isfile(local_body) else None
    print('[render] body: %s' % (body_path or './assets/bodies/mean_all.yaml'))

    gu.try_generate_garments(body_path, pred, garment_type, out_dir,
                             invnorm_float=False, float_dict=floats)
    print('[render] done: %s' % out_dir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
