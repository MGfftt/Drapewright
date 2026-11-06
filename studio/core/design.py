"""design.json: load and validate the one file the model writes."""

import json
import os

from .paths import DesignError, garment_parts, ordered_float_vector

SCHEMA = "gcstudio/design/1"

TEMPLATE = '''{
  "schema": "gcstudio/design/1",
  "label": "short comments for a human",
  "garment": {"wholebody_garment": {"meta": {"upper": "FittedShirt", "wb": null, "bottom": "Skirt2"},
               "shirt": {"strapless": true, "length": null, "width": null, "flare": null},
               "skirt": {"length": null, "rise": null, "ruffle": null, "bottom_cut": null},
               "left": {"enable_asym": false}}},
  "floats": {"design.shirt.length": 0.20, "design.shirt.width": 0.05, ...}

One-piece only: put meta.upper AND meta.bottom in the same wholebody_garment.
A split outfit (upperbody_garment + lowerbody_garment) is refused on purpose -
GarmentCodeRC would emit two patterns and v1 can only carry one.
Use 'python -m studio.agent template --file garment.json' to get every float path.
}'''


def load(path):
    if not os.path.isfile(path):
        raise DesignError("no such design file: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        try:
            doc = json.load(f)
        except json.JSONDecodeError as exc:
            raise DesignError("%s is not valid JSON: %s" % (path, exc))
    return validate(doc)


def validate(doc):
    """Return a normalised design dict or raise DesignError with an actionable message."""
    if not isinstance(doc, dict):
        raise DesignError("the design must be a JSON object")
    schema = doc.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise DesignError("unsupported schema %r (expected %r)" % (schema, SCHEMA))
    garment = doc.get("garment")
    if garment is None:
        raise DesignError("missing 'garment' (see the template in studio/core/design.py)")
    parts = garment_parts(garment)  # raises if the shape is wrong
    if len(parts) > 1:
        raise DesignError(
            "v1 only supports one-piece designs (wholebody_garment). A split outfit "
            "(upperbody_garment + lowerbody_garment) needs two GarmentCodeRC patterns and "
            "the pipeline would silently keep only the first, so it is refused instead. "
            "Express the same look as a wholebody_garment: meta.upper + meta.bottom in one "
            "block (e.g. {'upper': 'FittedShirt', 'wb': null, 'bottom': 'Skirt2'} plus a "
            "shirt/sleeve/skirt block) - see cases/rc_dress/design.json.")
    floats = doc.get("floats")
    if floats is None:
        raise DesignError("missing 'floats' (named floats, e.g. design.shirt.length)")
    vector, report = ordered_float_vector(garment, floats)
    return {
        "schema": schema,
        "label": doc.get("label", ""),
        "garment": garment,
        "floats": {k: float(v) for k, v in floats.items()},
        "vector": vector,
        "report": report,
    }