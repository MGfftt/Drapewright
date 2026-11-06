"""Float-path bookkeeping for GCrc designs.

A design JSON carries text fields (which garment parts, which collar, ...) and a
dict of named floats (design.shirt.length -> 0.2).  GarmentCodeRC wants a *flat,
ordered* float vector, and the order is the order in which the [SEG] slots appear
when you walk the prediction config through assets/design_params/design_used.yaml.
That is exactly what llava.garment_utils_v2.ordered_float_paths_from_pred() does,
so we reuse it instead of re-implementing the walk."""

import os
import sys

STUDIO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(STUDIO_ROOT)
GCRC_ROOT = os.path.join(REPO_ROOT, "repos", "GarmentCodeRC-main")
for _p in (REPO_ROOT, GCRC_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from llava.garment_utils_v2 import (  # noqa: E402  (needs the sys.path tweak above)
    designs_config,
    ordered_float_paths_from_pred,
)

PARTS_WHOLE = "wholebody"
PARTS_SPLIT = ("upperbody", "lowerbody")


class DesignError(Exception):
    """A design JSON that GarmentCodeRC cannot consume as written."""


def garment_parts(garment):
    """Split a design's garment dict into [(part_name, part_config), ...]."""
    if not isinstance(garment, dict):
        raise DesignError("garment must be an object")
    if "wholebody_garment" in garment:
        return [(PARTS_WHOLE, garment["wholebody_garment"])]
    if "upperbody_garment" in garment and "lowerbody_garment" in garment:
        return [("upperbody", garment["upperbody_garment"]),
                ("lowerbody", garment["lowerbody_garment"])]
    if "upperbody_garment" in garment or "lowerbody_garment" in garment:
        raise DesignError(
            "an upper/lower outfit needs BOTH upperbody_garment and lowerbody_garment; "
            "a one-piece needs wholebody_garment")
    raise DesignError(
        "garment must contain wholebody_garment, or upperbody_garment + lowerbody_garment")


def ordered_paths(garment):
    """Return {part_name: [float path, ...]} in the order GCrc will consume them."""
    out = {}
    for name, cfg in garment_parts(garment):
        out[name] = list(ordered_float_paths_from_pred(designs_config, cfg))
    return out


def ordered_float_vector(garment, floats):
    """Turn a named float dict into the flat vector GCrc expects.

    Returns (vector, report) where report is a dict with the part->paths mapping,
    so the caller can log/echo it. Raises DesignError on missing or unknown names.
    """
    if not isinstance(floats, dict):
        raise DesignError("floats must be an object keyed by design path")
    per_part = ordered_paths(garment)
    wanted, vector, missing = [], [], []
    for part, paths in per_part.items():
        for p in paths:
            wanted.append(p)
            if p in floats:
                try:
                    vector.append(float(floats[p]))
                except (TypeError, ValueError):
                    raise DesignError("float %s is not a number: %r" % (p, floats[p]))
            else:
                missing.append(p)
    unknown = sorted(set(floats) - set(wanted))
    if missing:
        raise DesignError(
            "missing %d float(s): %s" % (len(missing), ", ".join(missing[:12])) +
            (" ..." if len(missing) > 12 else ""))
    out_of_range = [p for p in wanted if not (0.0 <= float(floats[p]) <= 1.0)]
    return vector, {"per_part": per_part, "count": len(vector),
                     "unknown": unknown, "out_of_range": out_of_range}