#!/usr/bin/env python3
"""Typographically refined launcher for the certified n=14 hsep explainer."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


HELPER = (
    Path(__file__).resolve().parents[1]
    / "n14_hsep_explainer_20260803_200713"
    / "build_hsep_explainer.py"
)
spec = importlib.util.spec_from_file_location("n14_hsep_explainer_helper", HELPER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load helper: {HELPER}")
helper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = helper
spec.loader.exec_module(helper)

original_build_scene = helper.build_scene


def refined_build_scene(*args, **kwargs):
    scene = original_build_scene(*args, **kwargs)
    kept = []
    add_fact_continuation = False
    removed_callout = False
    for item in scene.items:
        if item["kind"] != "text":
            kept.append(item)
            continue
        value = item["value"]
        if value == "Ein Barnette-Graph mit 12 Hamiltonkreisen":
            item["size"] = 16
        elif value == "Hamiltonkreise insgesamt":
            item["value"] = "Hamiltonkreise"
            item["size"] = 12
            item["y"] = 445
            add_fact_continuation = True
        elif 1385 <= item["y"] <= 1445 and item["x"] == 400:
            item["size"] = 13
        elif value == "Gesamtzahl ≠ kleinstes trennendes System":
            item["size"] = 15
        elif value in {
            "Für hsep zählt nicht die Gesamtzahl aller Hamiltonkreise,",
            "sondern die kleinste vollständig trennende Auswahl.",
        }:
            removed_callout = True
            continue
        elif value.startswith("Auswahl: 1, 2"):
            item["size"] = 16
            item["y"] = 1598
        elif value == "Nicht benötigt: 6 und 9":
            item["size"] = 16
            item["y"] = 1630
        elif value == "Beispiel-Fingerabdrücke":
            item["size"] = 15
        elif item["x"] == 2552 and 845 <= item["y"] <= 1110:
            item["size"] = 14
        elif item["x"] == 1820 and 1360 <= item["y"] <= 1570:
            item["size"] = 14
        kept.append(item)
    scene.items = kept
    if add_fact_continuation:
        scene.text(605, 466, "insgesamt", size=12, color=helper.NAVY, weight=700, anchor="middle")
    if removed_callout:
        helper.add_lines(
            scene,
            1240,
            1490,
            [
                "Für hsep zählt nicht die Gesamtzahl",
                "aller Hamiltonkreise, sondern die kleinste",
                "vollständig trennende Auswahl.",
            ],
            size=16,
            color=helper.NAVY,
            weight=700,
            gap=27,
            anchor="middle",
        )
    return scene


helper.build_scene = refined_build_scene

if __name__ == "__main__":
    raise SystemExit(helper.main())
