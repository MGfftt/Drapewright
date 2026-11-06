"""Command line for the studio core.  Run from the repo root:

  ./.venv/Scripts/python.exe -m studio.core.cli paths  --design D.json
  ./.venv/Scripts/python.exe -m studio.core.cli build  --design D.json --out pkgs/x

Exit code 0 = ok, 2 = the design file is wrong, 3 = GarmentCodeRC rejected it.
"""

import argparse
import json
import sys

from . import design as design_mod
from .build import BuildError, build
from .paths import DesignError


def _err(msg, code):
    print("error: " + msg, file=sys.stderr)
    return code


def main(argv=None):
    ap = argparse.ArgumentParser(prog="studio.core.cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("paths", help="print the float paths a design must fill")
    p.add_argument("--design", help="design.json (omit to print the template)")
    p.add_argument("--json", action="store_true")

    b = sub.add_parser("build", help="design.json -> package (pattern + mesh)")
    b.add_argument("--design", required=True)
    b.add_argument("--out", required=True, help="package directory (created)")
    b.add_argument("--tag", default=None, help="basename for the mesh files")
    b.add_argument("--no-render", action="store_true", help="skip the preview PNG")

    args = ap.parse_args(argv)

    if args.cmd == "paths":
        if not args.design:
            print(design_mod.TEMPLATE)
            return 0
        try:
            d = design_mod.load(args.design)
        except DesignError as exc:
            return _err(str(exc), 2)
        per_part = d["report"]["per_part"]
        if args.json:
            print(json.dumps(per_part, indent=2))
        else:
            for part, paths in per_part.items():
                print("%s: %d float(s)" % (part, len(paths)))
                for path in paths:
                    filled = "" if path not in d["floats"] else " = %.3f" % d["floats"][path]
                    print("  " + path + filled)
        if d["report"]["unknown"]:
            print("warning: unknown float names: %s" % ", ".join(d["report"]["unknown"]),
                  file=sys.stderr)
        return 0

    try:
        manifest = build(args.design, args.out, tag=args.tag, render=not args.no_render)
    except DesignError as exc:
        return _err(str(exc), 2)
    except BuildError as exc:
        return _err(str(exc), 3)
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())