#!/usr/bin/env python3
"""Final typography launcher for the certified n=14 hsep explainer."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


PREVIOUS = (
    Path(__file__).resolve().parents[1]
    / "n14_hsep_explainer_20260803_201522"
    / "build_hsep_explainer.py"
)
spec = importlib.util.spec_from_file_location("n14_hsep_explainer_refined", PREVIOUS)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load refined builder: {PREVIOUS}")
refined = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = refined
spec.loader.exec_module(refined)

helper = refined.helper
previous_build_scene = helper.build_scene


def final_build_scene(*args, **kwargs):
    scene = previous_build_scene(*args, **kwargs)
    lower_line_positions = {1496: 1488, 1530: 1520, 1564: 1552}
    for item in scene.items:
        if item["kind"] != "text":
            continue
        if item["value"] == "hsep(G) = 10":
            item["size"] = 36
        if item["x"] == 1820 and item["y"] in lower_line_positions:
            item["y"] = lower_line_positions[item["y"]]
        if item["value"] == "Obere Schranke 10 + untere Schranke 10":
            item["y"] = 1595
            item["size"] = 14
    return scene


helper.build_scene = final_build_scene

if __name__ == "__main__":
    raise SystemExit(helper.main())
