"""U2 full-map automatic build (validation branch). Frozen code reused unchanged: sv_b2c.b2c (lines), sv_v3.group
(logical ids), sv_lf.labels / footprint, sv_d71.fill, sv_oracle.faces / provenance, sv_oracle_v2.write / render_gpkg.

Only adapter step added here (recorded in the run JSON): B2c can return MultiLineString objects on the full map; the
frozen linker accepts LineString only, so each multi-part object is split into its parts (same geometry, same width and
colour) before grouping. Nothing else is changed. No Oracle lines, no protected masks, no manual input.

Input : runs/stitchvector/u2_full/u2_map.png  (map box [0,0,805,780] of runs/real/u2/work.png, legend excluded)
Output: runs/stitchvector/u2_full/u2_full_B2c.gpkg + experiments/STITCHVECTOR/u2_full/u2_build_run.json
"""
import hashlib, json, platform, subprocess, sys, time, traceback
from pathlib import Path
import numpy as np
from PIL import Image
HERE = Path(__file__).resolve().parent
from . import sv_lf as LF; from . import sv_b2c as C; from . import link_group as V; from . import sv_d71 as D; from . import sv_oracle as O; from . import vector_writer as O2

RUN = HERE / "disabled_standalone_run"
OUTJ = HERE / "u2_full"


def sha(p): return hashlib.sha256(open(p, "rb").read()).hexdigest()


def line_objects(img, log):
    objs = C.b2c(img)[0]; flat = []
    for o in objs:
        g = o["geom"]
        if g.geom_type == "LineString": flat.append(o)
        else:
            parts = [p for p in g.geoms if p.length > 0]; log["multipart_split"].append({"parts": len(parts), "length": round(g.length, 1)})
            flat += [{**o, "geom": p} for p in parts]
    lg, _ = V.group(img, flat); lid = {i: g["logical_id"] for g in lg for i in g["parts"]}
    return objs, [{"id": f"L{i}", "group": f"G{lid[i]}", "kind": "auto_B2c", "width": float(o["width"]), "rgb": np.asarray(o["rgb"], np.uint8),
                   "geom": o["geom"]} for i, o in enumerate(flat)]


