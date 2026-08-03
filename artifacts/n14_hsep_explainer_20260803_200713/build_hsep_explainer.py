#!/usr/bin/env python3
"""Build the n=14 hsep explainer exclusively from the certified atlas bundle."""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import html
import json
import math
import os
from pathlib import Path
import struct
import sys
from typing import Any, Iterable, Sequence
import xml.etree.ElementTree as ET
import zlib


EXPECTED_HASH = "3b52365d8f69db960762343efece3b7510b943660d0fbd6353bb4f4cd7c0f445"
EXPECTED_SELECTED = [1, 2, 3, 4, 5, 7, 8, 10, 11, 12]
EXPECTED_UNUSED = [6, 9]
WIDTH, HEIGHT = 2800, 2000

BACKGROUND = "#F5F7FA"
PANEL = "#FFFFFF"
INK = "#18212B"
NAVY = "#17324D"
MUTED = "#5C6773"
BLUE = "#0072B2"
BLUE_SOFT = "#E8F3FA"
TEAL = "#009E73"
TEAL_SOFT = "#E5F5F0"
AMBER = "#E69F00"
AMBER_SOFT = "#FFF4D6"
GRID = "#D5DAE0"
LIGHT = "#EDF0F3"
WHITE = "#FFFFFF"
UNUSED = "#9AA3AC"
UNUSED_SOFT = "#F0F1F2"

Edge = tuple[int, int]


class BuildError(RuntimeError):
    pass


def edge(value: Iterable[int]) -> Edge:
    left, right = map(int, value)
    return (left, right) if left < right else (right, left)


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise BuildError(f"refusing to overwrite {path}") from exc


def write_json_new(path: Path, value: Any) -> None:
    write_new(path, (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))


def rgb(color: str) -> tuple[int, int, int]:
    value = color.removeprefix("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


class Scene:
    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []

    def rect(self, x: float, y: float, width: float, height: float, *, fill: str, stroke: str = "none", stroke_width: float = 0, radius: float = 0, css_class: str = "", attrs: dict[str, Any] | None = None) -> None:
        self.items.append({"kind": "rect", "x": x, "y": y, "width": width, "height": height, "fill": fill, "stroke": stroke, "stroke_width": stroke_width, "radius": radius, "class": css_class, "attrs": attrs or {}})

    def line(self, x1: float, y1: float, x2: float, y2: float, *, color: str, width: float, css_class: str = "", attrs: dict[str, Any] | None = None) -> None:
        self.items.append({"kind": "line", "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": color, "width": width, "class": css_class, "attrs": attrs or {}})

    def circle(self, x: float, y: float, radius: float, *, fill: str, stroke: str = "none", stroke_width: float = 0, css_class: str = "", attrs: dict[str, Any] | None = None) -> None:
        self.items.append({"kind": "circle", "x": x, "y": y, "radius": radius, "fill": fill, "stroke": stroke, "stroke_width": stroke_width, "class": css_class, "attrs": attrs or {}})

    def text(self, x: float, y: float, value: str, *, size: float, color: str = INK, weight: int = 400, anchor: str = "start", css_class: str = "", attrs: dict[str, Any] | None = None) -> None:
        self.items.append({"kind": "text", "x": x, "y": y, "value": value, "size": size, "color": color, "weight": weight, "anchor": anchor, "class": css_class, "attrs": attrs or {}})


def add_lines(scene: Scene, x: float, y: float, lines: Sequence[str], *, size: float, color: str = INK, weight: int = 400, gap: float | None = None, anchor: str = "start") -> None:
    spacing = gap if gap is not None else size * 1.32
    for index, value in enumerate(lines):
        scene.text(x, y + index * spacing, value, size=size, color=color, weight=weight, anchor=anchor)


def section_heading(scene: Scene, letter: str, title: str, x: float, y: float) -> None:
    scene.circle(x + 25, y - 8, 25, fill=NAVY)
    scene.text(x + 25, y, letter, size=27, color=WHITE, weight=700, anchor="middle")
    scene.text(x + 67, y, title, size=31, color=NAVY, weight=700)


def mapped_positions(source: dict[int, tuple[float, float]], x: float, y: float, width: float, height: float) -> dict[int, tuple[float, float]]:
    xs = [point[0] for point in source.values()]
    ys = [point[1] for point in source.values()]
    scale = min(width / (max(xs) - min(xs)), height / (max(ys) - min(ys)))
    used_width = (max(xs) - min(xs)) * scale
    used_height = (max(ys) - min(ys)) * scale
    left = x + (width - used_width) / 2
    top = y + (height - used_height) / 2
    return {vertex: (left + (px - min(xs)) * scale, top + (py - min(ys)) * scale) for vertex, (px, py) in source.items()}


def draw_graph(scene: Scene, *, source_positions: dict[int, tuple[float, float]], graph_edges: Sequence[Edge], cycle_edges: set[Edge], x: float, y: float, width: float, height: float, panel_id: str, cycle_index: int | None = None, selected: bool = True, labels: bool = True) -> None:
    positions = mapped_positions(source_positions, x, y, width, height)
    base_color = GRID if selected else "#D1D5D9"
    highlight_color = BLUE if selected else UNUSED
    base_width = max(1.3, width / 230)
    highlight_width = max(3.2, width / 58)
    node_radius = max(5.0, width / 34)
    for left, right in graph_edges:
        x1, y1 = positions[left]
        x2, y2 = positions[right]
        scene.line(x1, y1, x2, y2, color=base_color, width=base_width, css_class="graph-edge", attrs={"data-panel": panel_id, "data-edge": f"{left}-{right}"})
    for left, right in graph_edges:
        if (left, right) in cycle_edges:
            x1, y1 = positions[left]
            x2, y2 = positions[right]
            scene.line(x1, y1, x2, y2, color=highlight_color, width=highlight_width, css_class="cycle-edge", attrs={"data-panel": panel_id, "data-cycle-index": cycle_index if cycle_index is not None else "", "data-edge": f"{left}-{right}"})
    for vertex in sorted(positions):
        px, py = positions[vertex]
        sx, sy = source_positions[vertex]
        scene.circle(px, py, node_radius, fill=WHITE if selected else UNUSED_SOFT, stroke=INK if selected else UNUSED, stroke_width=max(1.0, width / 300), css_class="graph-vertex", attrs={"data-panel": panel_id, "data-cycle-index": cycle_index if cycle_index is not None else "", "data-vertex": vertex, "data-source-x": f"{sx:.12g}", "data-source-y": f"{sy:.12g}"})
        if labels:
            scene.text(px, py + node_radius * 0.32, str(vertex), size=max(8.0, node_radius * 0.9), color=INK if selected else MUTED, weight=700, anchor="middle")


def attr_text(attrs: dict[str, Any]) -> str:
    values = []
    for key, value in attrs.items():
        if value == "":
            continue
        values.append(f'{key}="{html.escape(str(value), quote=True)}"')
    return (" " + " ".join(values)) if values else ""


def render_svg(scene: Scene, metadata: dict[str, Any]) -> bytes:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" data-source-coordinate-sha256="{metadata["source_coordinate_sha256"]}">',
        "  <title>12 Hamiltonkreise vorhanden – 10 werden mindestens benötigt</title>",
        "  <desc>Didaktische Erklärung von hsep am eindeutigen Barnette-Graphen mit 14 Knoten: Grundgraph, Auswahl des 10-Zyklen-Primalzertifikats und Signaturmatrix der 21 Kanten.</desc>",
        f"  <metadata>{html.escape(json.dumps(metadata, ensure_ascii=False, sort_keys=True))}</metadata>",
    ]
    for item in scene.items:
        kind = item["kind"]
        klass = f' class="{item["class"]}"' if item["class"] else ""
        attrs = attr_text(item["attrs"])
        if kind == "rect":
            lines.append(f'  <rect{klass}{attrs} x="{item["x"]:.3f}" y="{item["y"]:.3f}" width="{item["width"]:.3f}" height="{item["height"]:.3f}" rx="{item["radius"]:.3f}" fill="{item["fill"]}" stroke="{item["stroke"]}" stroke-width="{item["stroke_width"]:.3f}"/>')
        elif kind == "line":
            lines.append(f'  <line{klass}{attrs} x1="{item["x1"]:.3f}" y1="{item["y1"]:.3f}" x2="{item["x2"]:.3f}" y2="{item["y2"]:.3f}" stroke="{item["color"]}" stroke-width="{item["width"]:.3f}" stroke-linecap="round"/>')
        elif kind == "circle":
            lines.append(f'  <circle{klass}{attrs} cx="{item["x"]:.3f}" cy="{item["y"]:.3f}" r="{item["radius"]:.3f}" fill="{item["fill"]}" stroke="{item["stroke"]}" stroke-width="{item["stroke_width"]:.3f}"/>')
        elif kind == "text":
            lines.append(f'  <text{klass}{attrs} x="{item["x"]:.3f}" y="{item["y"]:.3f}" fill="{item["color"]}" font-family="Inter, Segoe UI, Arial, sans-serif" font-size="{item["size"]:.3f}" font-weight="{item["weight"]}" text-anchor="{item["anchor"]}" dominant-baseline="alphabetic">{html.escape(item["value"])}</text>')
    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


class PdfCanvas:
    def __init__(self) -> None:
        self.commands: list[str] = []

    @staticmethod
    def color(value: str) -> str:
        return " ".join(f"{channel / 255:.4f}" for channel in rgb(value))

    def add_scene(self, scene: Scene) -> None:
        for item in scene.items:
            kind = item["kind"]
            if kind == "rect":
                x, y, w, h = item["x"], HEIGHT - item["y"] - item["height"], item["width"], item["height"]
                self.commands.append(f'{self.color(item["fill"])} rg {x:.3f} {y:.3f} {w:.3f} {h:.3f} re f')
                if item["stroke"] != "none" and item["stroke_width"] > 0:
                    self.commands.append(f'{self.color(item["stroke"])} RG {item["stroke_width"]:.3f} w {x:.3f} {y:.3f} {w:.3f} {h:.3f} re S')
            elif kind == "line":
                self.commands.append(f'{self.color(item["color"])} RG {item["width"]:.3f} w 1 J {item["x1"]:.3f} {HEIGHT-item["y1"]:.3f} m {item["x2"]:.3f} {HEIGHT-item["y2"]:.3f} l S')
            elif kind == "circle":
                x, y, radius = item["x"], HEIGHT - item["y"], item["radius"]
                k = 0.552284749831 * radius
                path = f'{x+radius:.3f} {y:.3f} m {x+radius:.3f} {y+k:.3f} {x+k:.3f} {y+radius:.3f} {x:.3f} {y+radius:.3f} c {x-k:.3f} {y+radius:.3f} {x-radius:.3f} {y+k:.3f} {x-radius:.3f} {y:.3f} c {x-radius:.3f} {y-k:.3f} {x-k:.3f} {y-radius:.3f} {x:.3f} {y-radius:.3f} c {x+k:.3f} {y-radius:.3f} {x+radius:.3f} {y-k:.3f} {x+radius:.3f} {y:.3f} c'
                self.commands.append(f'{self.color(item["fill"])} rg {self.color(item["stroke"] if item["stroke"] != "none" else item["fill"])} RG {item["stroke_width"]:.3f} w {path} B')
            elif kind == "text":
                value = item["value"].replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                width = len(item["value"]) * item["size"] * (0.56 if item["weight"] >= 700 else 0.51)
                x = item["x"] - (width / 2 if item["anchor"] == "middle" else width if item["anchor"] == "end" else 0)
                font = "F2" if item["weight"] >= 700 else "F1"
                self.commands.append(f'BT /{font} {item["size"]:.3f} Tf {self.color(item["color"])} rg {x:.3f} {HEIGHT-item["y"]:.3f} Td ({value}) Tj ET')

    def bytes(self) -> bytes:
        content = ("\n".join(self.commands) + "\n").encode("cp1252", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {WIDTH} {HEIGHT}] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>".encode("ascii"),
            b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]
        output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for number, obj in enumerate(objects, 1):
            offsets.append(len(output))
            output.extend(f"{number} 0 obj\n".encode("ascii"))
            output.extend(obj)
            output.extend(b"\nendobj\n")
        xref = len(output)
        output.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        output.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
        return bytes(output)


_FONT: dict[str, tuple[str, ...]] = {
    " ": ("00000",) * 7, "-": ("00000", "00000", "00000", "11111", "00000", "00000", "00000"),
    "/": ("00001", "00010", "00100", "00100", "01000", "10000", "00000"), ".": ("00000", "00000", "00000", "00000", "00000", "00110", "00110"),
    ",": ("00000", "00000", "00000", "00000", "00110", "00100", "01000"), ":": ("00000", "00110", "00110", "00000", "00110", "00110", "00000"),
    "=": ("00000", "11111", "00000", "11111", "00000", "00000", "00000"), "|": ("00100",)*7,
    "(": ("00010", "00100", "01000", "01000", "01000", "00100", "00010"), ")": ("01000", "00100", "00010", "00010", "00010", "00100", "01000"),
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"), "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"), "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"), "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "6": ("01110", "10000", "10000", "11110", "10001", "10001", "01110"), "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"), "9": ("01110", "10001", "10001", "01111", "00001", "00001", "01110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"), "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"), "D": ("11110", "10001", "10001", "10001", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"), "F": ("11111", "10000", "10000", "11110", "10000", "10000", "10000"),
    "G": ("01111", "10000", "10000", "10111", "10001", "10001", "01111"), "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"), "J": ("00111", "00010", "00010", "00010", "10010", "10010", "01100"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"), "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "M": ("10001", "11011", "10101", "10101", "10001", "10001", "10001"), "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"), "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"), "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"), "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"), "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"), "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"), "Z": ("11111", "00001", "00010", "00100", "01000", "10000", "11111"),
    "Ä": ("01010", "01110", "10001", "11111", "10001", "10001", "10001"), "Ö": ("01010", "01110", "10001", "10001", "10001", "10001", "01110"),
    "Ü": ("01010", "10001", "10001", "10001", "10001", "10001", "01110"),
}


class RasterCanvas:
    def __init__(self, factor: int = 2) -> None:
        self.factor = factor
        self.width = WIDTH * factor
        self.height = HEIGHT * factor
        self.pixels = bytearray(bytes(rgb(BACKGROUND)) * (self.width * self.height))

    def set_pixel(self, x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = 3 * (y * self.width + x)
            self.pixels[offset : offset + 3] = bytes(color)

    def rect(self, x: float, y: float, width: float, height: float, fill: str, stroke: str, stroke_width: float) -> None:
        f = self.factor
        left, top = max(0, round(x*f)), max(0, round(y*f))
        right, bottom = min(self.width, round((x+width)*f)), min(self.height, round((y+height)*f))
        fill_bytes = bytes(rgb(fill)) * max(0, right-left)
        for py in range(top, bottom):
            offset = 3 * (py*self.width+left)
            self.pixels[offset : offset+len(fill_bytes)] = fill_bytes
        if stroke != "none" and stroke_width > 0:
            sw = max(1, round(stroke_width*f)); color = rgb(stroke)
            self.rect(x, y, width, sw/f, stroke, "none", 0); self.rect(x, y+height-sw/f, width, sw/f, stroke, "none", 0)
            self.rect(x, y, sw/f, height, stroke, "none", 0); self.rect(x+width-sw/f, y, sw/f, height, stroke, "none", 0)

    def disc(self, x: float, y: float, radius: float, color: str) -> None:
        f=self.factor; cx=x*f; cy=y*f; r=radius*f; r2=r*r; value=rgb(color)
        for py in range(max(0,int(cy-r-1)), min(self.height,int(cy+r+2))):
            dy=py+0.5-cy
            for px in range(max(0,int(cx-r-1)), min(self.width,int(cx+r+2))):
                dx=px+0.5-cx
                if dx*dx+dy*dy <= r2: self.set_pixel(px,py,value)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float, color: str) -> None:
        dx,dy=x2-x1,y2-y1; steps=max(1,int(max(abs(dx),abs(dy))/max(width/3,0.8)))
        for index in range(steps+1):
            t=index/steps; self.disc(x1+dx*t,y1+dy*t,width/2,color)

    def circle(self, x: float, y: float, radius: float, fill: str, stroke: str, stroke_width: float) -> None:
        self.disc(x,y,radius,stroke if stroke != "none" else fill)
        self.disc(x,y,max(0,radius-stroke_width),fill)

    def text(self, x: float, y: float, value: str, size: float, color: str, anchor: str) -> None:
        normalized=value.upper().replace("–","-").replace("—","-").replace("ẞ","SS")
        f=self.factor; scale=max(1,round(size*f/7)); width=(6*len(normalized)-1)*scale
        start=round(x*f - (width/2 if anchor=="middle" else width if anchor=="end" else 0)); top=round(y*f-6.5*scale)
        ink=rgb(color)
        for character in normalized:
            glyph=_FONT.get(character,_FONT[" "])
            for row,bits in enumerate(glyph):
                for column,bit in enumerate(bits):
                    if bit=="1":
                        for py in range(top+row*scale,top+(row+1)*scale):
                            for px in range(start+column*scale,start+(column+1)*scale): self.set_pixel(px,py,ink)
            start += 6*scale

    def add_scene(self, scene: Scene) -> None:
        for item in scene.items:
            if item["kind"]=="rect": self.rect(item["x"],item["y"],item["width"],item["height"],item["fill"],item["stroke"],item["stroke_width"])
            elif item["kind"]=="line": self.line(item["x1"],item["y1"],item["x2"],item["y2"],item["width"],item["color"])
            elif item["kind"]=="circle": self.circle(item["x"],item["y"],item["radius"],item["fill"],item["stroke"],item["stroke_width"])
            elif item["kind"]=="text": self.text(item["x"],item["y"],item["value"],item["size"],item["color"],item["anchor"])

    def png(self) -> bytes:
        rows=bytearray(); f=self.factor; area=f*f
        for oy in range(HEIGHT):
            rows.append(0)
            for ox in range(WIDTH):
                totals=[0,0,0]
                for sy in range(f):
                    for sx in range(f):
                        offset=3*((oy*f+sy)*self.width+ox*f+sx)
                        totals[0]+=self.pixels[offset]; totals[1]+=self.pixels[offset+1]; totals[2]+=self.pixels[offset+2]
                rows.extend(round(value/area) for value in totals)
        def chunk(kind: bytes,data: bytes)->bytes:
            return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data)&0xFFFFFFFF)
        header=struct.pack(">IIBBBBB",WIDTH,HEIGHT,8,2,0,0,0)
        return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",header)+chunk(b"IDAT",zlib.compress(bytes(rows),9))+chunk(b"IEND",b"")


def build_scene(source_positions: dict[int, tuple[float, float]], graph_edges: list[Edge], cycles: list[set[Edge]], selected: list[int], signatures: dict[Edge, str]) -> Scene:
    scene=Scene()
    scene.rect(0,0,WIDTH,HEIGHT,fill=BACKGROUND)
    scene.text(1400,72,"12 Hamiltonkreise vorhanden – 10 werden mindestens benötigt",size=52,color=NAVY,weight=700,anchor="middle")
    scene.text(1400,125,"Was hsep misst: die kleinste vollständig kantentrennende Auswahl",size=29,color=MUTED,weight=400,anchor="middle")
    scene.text(1400,161,"von Hamiltonkreisen",size=29,color=MUTED,weight=400,anchor="middle")
    scene.line(70,194,2730,194,color=GRID,width=2)

    panels=[(55,225,690,1475),(780,225,920,1475),(1735,225,1010,1475)]
    for x,y,w,h in panels: scene.rect(x,y,w,h,fill=PANEL,stroke=GRID,stroke_width=2,radius=22)

    # A: graph and facts
    section_heading(scene,"A","DER GRAPH",85,280)
    scene.text(400,340,"Ein Barnette-Graph mit 12 Hamiltonkreisen",size=28,color=INK,weight=700,anchor="middle")
    facts=[("14","Knoten"),("21","Kanten"),("12","Hamiltonkreise insgesamt")]
    for index,(value,label) in enumerate(facts):
        x=90+index*210
        scene.rect(x,375,190,100,fill=BLUE_SOFT,stroke="#B7D9EC",stroke_width=1.5,radius=14)
        scene.text(x+95,418,value,size=37,color=BLUE,weight=700,anchor="middle")
        scene.text(x+95,451,label,size=18,color=NAVY,weight=700,anchor="middle")
    draw_graph(scene,source_positions=source_positions,graph_edges=graph_edges,cycle_edges=set(),x=110,y=520,width=580,height=520,panel_id="A-base",labels=True)
    scene.text(400,1085,"Zwei verschiedene Zahlen",size=27,color=NAVY,weight=700,anchor="middle")
    scene.rect(105,1120,590,150,fill=LIGHT,stroke=GRID,stroke_width=1.5,radius=14)
    scene.text(400,1172,"|H(G)| = 12",size=39,color=INK,weight=700,anchor="middle")
    scene.text(400,1215,"alle vorhandenen Hamiltonkreise",size=21,color=MUTED,anchor="middle")
    scene.rect(105,1290,590,230,fill=AMBER_SOFT,stroke=AMBER,stroke_width=2,radius=14)
    scene.text(400,1342,"hsep(G) = 10",size=40,color=NAVY,weight=700,anchor="middle")
    add_lines(scene,400,1385,["kleinste Auswahl, die für jedes geordnete", "Paar verschiedener Kanten einen Zyklus enthält,", "der die erste Kante enthält und die zweite meidet"],size=19,color=INK,gap=29,anchor="middle")
    scene.text(400,1585,"Gesamtzahl ≠ kleinstes trennendes System",size=23,color=AMBER,weight=700,anchor="middle")

    # B: 12 cycle universe with the primal selection marked
    section_heading(scene,"B","AUS 12 WERDEN 10",810,280)
    grid_x,grid_y=815,325; cell_w,cell_h=275,268; gap_x,gap_y=15,12
    selected_set=set(selected)
    for zero in range(12):
        cycle_index=zero+1; row,column=divmod(zero,3)
        x=grid_x+column*(cell_w+gap_x); y=grid_y+row*(cell_h+gap_y)
        is_selected=cycle_index in selected_set
        scene.rect(x,y,cell_w,cell_h,fill=WHITE if is_selected else UNUSED_SOFT,stroke=BLUE if is_selected else UNUSED,stroke_width=3 if is_selected else 1.5,radius=13,css_class="cycle-tile",attrs={"data-cycle-index":cycle_index,"data-selected":str(is_selected).lower()})
        scene.text(x+18,y+30,f"Zyklus {cycle_index}",size=19,color=NAVY if is_selected else MUTED,weight=700)
        if is_selected:
            scene.circle(x+247,y+24,13,fill=TEAL)
            scene.text(x+247,y+30,"+",size=20,color=WHITE,weight=700,anchor="middle")
        else:
            scene.circle(x+247,y+24,13,fill=UNUSED)
            scene.text(x+247,y+30,"-",size=20,color=WHITE,weight=700,anchor="middle")
        draw_graph(scene,source_positions=source_positions,graph_edges=graph_edges,cycle_edges=cycles[zero],x=x+18,y=y+48,width=239,height=170,panel_id=f"B-cycle-{cycle_index}",cycle_index=cycle_index,selected=is_selected,labels=True)
        scene.text(x+cell_w/2,y+249,"im Zertifikat" if is_selected else "nicht benötigt",size=17,color=TEAL if is_selected else MUTED,weight=700,anchor="middle")
    scene.rect(815,1450,850,205,fill=BLUE_SOFT,stroke="#B7D9EC",stroke_width=1.5,radius=16)
    add_lines(scene,1240,1500,["Für hsep zählt nicht die Gesamtzahl aller Hamiltonkreise,", "sondern die kleinste vollständig trennende Auswahl."],size=23,color=NAVY,weight=700,gap=34,anchor="middle")
    scene.text(1240,1595,"Auswahl: 1, 2, 3, 4, 5, 7, 8, 10, 11, 12",size=21,color=BLUE,weight=700,anchor="middle")
    scene.text(1240,1630,"Nicht benötigt: 6 und 9",size=19,color=MUTED,anchor="middle")

    # C: signature matrix and exact lower bound
    section_heading(scene,"C","WARUM 10 GENAU RICHTIG IST",1765,280)
    scene.text(1790,332,"21 Kanten × 10 ausgewählte Zyklen",size=24,color=NAVY,weight=700)
    matrix_x,matrix_y=1885,385; col_w,row_h=47,39
    scene.text(1835,372,"Kante",size=17,color=MUTED,weight=700,anchor="middle")
    for column,cycle_index in enumerate(selected):
        scene.text(matrix_x+column*col_w+col_w/2,372,f"C{cycle_index}",size=15,color=MUTED,weight=700,anchor="middle")
    for row,item in enumerate(graph_edges):
        y=matrix_y+row*row_h
        scene.text(1865,y+26,f"{item[0]}–{item[1]}",size=17,color=INK,weight=700,anchor="end")
        signature=signatures[item]
        for column,bit in enumerate(signature):
            x=matrix_x+column*col_w
            fill=BLUE if bit=="1" else LIGHT
            color=WHITE if bit=="1" else MUTED
            scene.rect(x,y,col_w-4,row_h-4,fill=fill,stroke=WHITE,stroke_width=1,radius=5,css_class="signature-cell",attrs={"data-edge":f"{item[0]}-{item[1]}","data-cycle-index":selected[column],"data-bit":bit})
            scene.text(x+(col_w-4)/2,y+25,bit,size=16,color=color,weight=700,anchor="middle")
    scene.text(2120,1230,"1 = Zyklus enthält die Kante   ·   0 = Zyklus meidet sie",size=17,color=MUTED,anchor="middle")

    ex_x=2400
    scene.rect(ex_x,345,305,395,fill=LIGHT,stroke=GRID,stroke_width=1.5,radius=14)
    scene.text(ex_x+152,385,"Beispiel-Fingerabdrücke",size=20,color=NAVY,weight=700,anchor="middle")
    examples=[(0,1),(0,2),(11,13)]
    for index,item in enumerate(examples):
        y=430+index*86; signature=signatures[item]
        scene.text(ex_x+20,y+18,f"Kante {item[0]}–{item[1]}",size=17,color=INK,weight=700)
        for column,bit in enumerate(signature):
            bx=ex_x+20+column*27
            scene.rect(bx,y+30,23,28,fill=BLUE if bit=="1" else WHITE,stroke=GRID,stroke_width=1,radius=3)
            scene.text(bx+11.5,y+51,bit,size=14,color=WHITE if bit=="1" else MUTED,weight=700,anchor="middle")
    scene.rect(ex_x,760,305,410,fill=TEAL_SOFT,stroke="#A9DCCA",stroke_width=1.5,radius=14)
    scene.text(ex_x+152,802,"Warum inkomparabel?",size=21,color=NAVY,weight=700,anchor="middle")
    add_lines(scene,ex_x+152,845,["Jede Kante erhält einen", "10-Bit-Fingerabdruck.", "", "Für zwei Kanten e und f", "brauchen wir ein Bit 1/0", "und ein anderes Bit 0/1.", "", "Darum darf keine Signatur", "in einer anderen enthalten sein."],size=17,color=INK,gap=31,anchor="middle")
    scene.text(ex_x+152,1135,"Alle 21 Signaturen sind",size=18,color=TEAL,weight=700,anchor="middle")
    scene.text(ex_x+152,1160,"paarweise inkomparabel.",size=18,color=TEAL,weight=700,anchor="middle")

    scene.rect(1780,1270,925,340,fill=AMBER_SOFT,stroke=AMBER,stroke_width=2.5,radius=16)
    scene.text(1820,1315,"Exakter Lower Bound",size=25,color=NAVY,weight=700)
    add_lines(scene,1820,1360,["Die vorhandenen Zertifikate prüfen alle 4.017 Teilmengen", "aus höchstens 9 der 12 Zyklen. Für jede Teilmenge", "ist ein ungetrenntes geordnetes Kantenpaar angegeben.", "", "Eine exakte Zertifikatsprüfung zeigt:", "Mit 9 Hamiltonkreisen ist keine vollständige starke", "Kantentrennung möglich."],size=20,color=INK,gap=34)
    scene.text(2242,1580,"Obere Schranke 10 + untere Schranke 10",size=21,color=AMBER,weight=700,anchor="middle")

    scene.rect(300,1750,2200,175,fill=NAVY,stroke=NAVY,stroke_width=1,radius=20)
    scene.text(1400,1818,"Also: hsep(G) = 10, obwohl |H(G)| = 12.",size=47,color=WHITE,weight=700,anchor="middle")
    scene.text(1400,1872,"Zehn ausgewählte Zyklen trennen alle 21 Kanten stark; neun können es zertifiziert nicht.",size=24,color="#D9EAF5",anchor="middle")
    scene.text(1400,1965,"Plantri 5.8 · kanonischer Graph-SHA-256 3b52365d…f445 · identische zertifizierte Einbettung in allen Teilgrafiken",size=17,color=MUTED,anchor="middle")
    return scene


def png_dimensions(path: Path) -> tuple[int,int]:
    data=path.read_bytes()
    if len(data)<24 or data[:8]!=b"\x89PNG\r\n\x1a\n" or data[12:16]!=b"IHDR": raise BuildError("invalid PNG")
    return struct.unpack(">II",data[16:24])


def parse_svg_verification(path: Path, selected: list[int], graph_edges: list[Edge], signatures: dict[Edge,str], source_positions: dict[int,tuple[float,float]], coordinate_hash: str) -> dict[str,Any]:
    root=ET.parse(path).getroot()
    if root.attrib.get("data-source-coordinate-sha256")!=coordinate_hash: raise BuildError("SVG coordinate hash mismatch")
    cells={}
    tile_selection={}
    vertices_checked=0
    for element in root.iter():
        kind=element.attrib.get("class")
        if kind=="signature-cell":
            item=edge(map(int,element.attrib["data-edge"].split("-")))
            cells[(item,int(element.attrib["data-cycle-index"]))]=element.attrib["data-bit"]
        elif kind=="cycle-tile": tile_selection[int(element.attrib["data-cycle-index"])]=element.attrib["data-selected"]=="true"
        elif kind=="graph-vertex":
            vertex=int(element.attrib["data-vertex"]); sx=float(element.attrib["data-source-x"]); sy=float(element.attrib["data-source-y"])
            expected=source_positions[vertex]
            if not(math.isclose(sx,expected[0],abs_tol=1e-9) and math.isclose(sy,expected[1],abs_tol=1e-9)): raise BuildError("embedded coordinate mismatch")
            vertices_checked+=1
    expected_cells={(item,cycle_index):signatures[item][column] for item in graph_edges for column,cycle_index in enumerate(selected)}
    if cells!=expected_cells: raise BuildError("SVG matrix mismatch")
    if tile_selection!={index:index in set(selected) for index in range(1,13)}: raise BuildError("SVG selection tiles mismatch")
    return {"signature_cells_checked":len(cells),"cycle_tiles_checked":len(tile_selection),"graph_vertex_instances_checked":vertices_checked,"source_coordinate_hash_matches":True}


def main(argv: list[str]|None=None)->int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--source",type=Path,required=True); parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(argv); source=args.source.resolve(); output=args.output.resolve()
    try:
        if source==output or output.is_relative_to(source): raise BuildError("output must be a distinct directory")
        output.mkdir(parents=True,exist_ok=True)
        existing=[item.name for item in output.iterdir() if item.name not in {Path(__file__).name,"__pycache__"}]
        if existing: raise BuildError(f"output already contains files: {existing}")
        cycles_doc=json.loads((source/"cycles.json").read_text(encoding="utf-8")); hsep=json.loads((source/"hsep_certificate.json").read_text(encoding="utf-8")); layout=json.loads((source/"layout.json").read_text(encoding="utf-8")); prior=json.loads((source/"independent_verification.json").read_text(encoding="utf-8"))
        graph=cycles_doc["graph"]; graph_hash=graph["canonical_graph_hash"]
        if graph_hash!=EXPECTED_HASH or len(cycles_doc["cycles"])!=12 or hsep["exact_hsep"]!=10 or not prior["success"]: raise BuildError("source atlas control values failed")
        selected=list(map(int,hsep["primal_cycle_indices_one_based"])); unused=sorted(set(range(1,13))-set(selected))
        if selected!=EXPECTED_SELECTED or unused!=EXPECTED_UNUSED: raise BuildError("unexpected primal selection")
        expected_masks={mask for mask in range(1<<12) if mask.bit_count()<10}; lower_masks={int(item["cycle_subset_bitmask"]) for item in hsep["lower_bound_entries"]}
        if lower_masks!=expected_masks or len(hsep["lower_bound_entries"])!=4017: raise BuildError("lower-bound certificate is incomplete")
        graph_edges=[edge(item) for item in graph["edges"]]; cycle_sets=[{edge(item) for item in record["canonical_edge_list"]} for record in cycles_doc["cycles"]]
        signatures={item:"".join("1" if item in cycle_sets[index-1] else "0" for index in selected) for item in graph_edges}
        incomparable=True; separated=0
        for first in graph_edges:
            for second in graph_edges:
                if first==second: continue
                if any(a=="1" and b=="0" for a,b in zip(signatures[first],signatures[second])): separated+=1
                else: incomparable=False
        if not incomparable or separated!=420 or len(set(signatures.values()))!=21: raise BuildError("selected signatures do not strongly separate every edge pair")
        source_positions={int(vertex):tuple(map(float,point)) for vertex,point in layout["normalized_svg_positions_zero_based"].items()}
        coordinate_payload=json.dumps({str(v):[round(x,6),round(y,6)] for v,(x,y) in source_positions.items()},sort_keys=True,separators=(",",":")).encode("ascii")
        if sha256_bytes(coordinate_payload)!=layout["normalized_coordinate_sha256"]: raise BuildError("source coordinate hash mismatch")

        selected_record={"schema":"barnette-n14-hsep-selected-cycles-v1","canonical_graph_hash":graph_hash,"total_undirected_hamiltonian_cycles":12,"exact_hsep":10,"selected_cycle_indices_one_based":selected,"unused_cycle_indices_one_based":unused,"source_hsep_certificate_sha256":sha256_file(source/"hsep_certificate.json"),"selected_cycles":[cycles_doc["cycles"][index-1] for index in selected]}
        write_json_new(output/"selected_10_cycles.json",selected_record)
        csv_path=output/"signature_matrix.csv"
        rows=[]
        header=["edge_u","edge_v",*[f"cycle_{index:02d}" for index in selected],"signature","ones"]
        for item in graph_edges: rows.append([item[0],item[1],*list(signatures[item]),signatures[item],signatures[item].count("1")])
        text_lines=[",".join(header)]+[",".join(map(str,row)) for row in rows]
        write_new(csv_path,("\n".join(text_lines)+"\n").encode("utf-8"))

        scene=build_scene(source_positions,graph_edges,cycle_sets,selected,signatures)
        metadata={"canonical_graph_hash":graph_hash,"total_hamiltonian_cycles":12,"exact_hsep":10,"selected_cycles":selected,"unused_cycles":unused,"source_coordinate_sha256":layout["normalized_coordinate_sha256"]}
        svg_path=output/"hsep_n14_explained.svg"; png_path=output/"hsep_n14_explained.png"; pdf_path=output/"hsep_n14_explained.pdf"
        write_new(svg_path,render_svg(scene,metadata))
        pdf=PdfCanvas(); pdf.add_scene(scene); write_new(pdf_path,pdf.bytes())
        raster=RasterCanvas(2); raster.add_scene(scene); write_new(png_path,raster.png())

        svg_checks=parse_svg_verification(svg_path,selected,graph_edges,signatures,source_positions,layout["normalized_coordinate_sha256"])
        verification={"schema":"barnette-n14-hsep-didactic-figure-verification-v1","success":True,"canonical_graph_hash":graph_hash,"source_directory":str(source),"source_files":{name:{"sha256":sha256_file(source/name),"size_bytes":(source/name).stat().st_size} for name in ("cycles.json","hsep_certificate.json","layout.json","independent_verification.json")},"primal_selection":{"matches_hsep_certificate":True,"selected_cycle_indices_one_based":selected,"unused_cycle_indices_one_based":unused},"signature_matrix":{"edge_rows":21,"selected_cycle_columns":10,"ordered_edge_pairs_separated":separated,"expected_ordered_edge_pairs":420,"all_signatures_pairwise_incomparable":incomparable,"distinct_signature_count":len(set(signatures.values())),"csv_matches_selected_cycles":True},"lower_bound":{"exact_hsep":10,"all_subsets_of_size_below_10_certified":True,"certified_subset_count":len(lower_masks),"statement_no_nine_cycle_selection_suffices_is_supported":True},"embedding":{"source_coordinate_sha256":layout["normalized_coordinate_sha256"],"all_graph_panels_derived_by_uniform_scale_and_translation_from_source_coordinates":True,**svg_checks},"outputs":{path.name:{"exists":path.is_file(),"nonempty":path.stat().st_size>0,"size_bytes":path.stat().st_size,"sha256":sha256_file(path)} for path in (svg_path,png_path,pdf_path,output/"selected_10_cycles.json",csv_path)},"png_dimensions":list(png_dimensions(png_path)),"pdf_header_valid":pdf_path.read_bytes().startswith(b"%PDF-1.4")}
        if verification["png_dimensions"]!=[WIDTH,HEIGHT] or not verification["pdf_header_valid"] or not all(item["nonempty"] for item in verification["outputs"].values()): raise BuildError("output validation failed")
        write_json_new(output/"didactic_figure_verification.json",verification)
        readme=f"""# hsep-Erklärgrafik für den Barnette-Graphen n=14

- Kanonischer Graph-SHA-256: `{graph_hash}`
- Ungerichtete Hamiltonkreise insgesamt: **12**
- Exakter Wert: **hsep(G)=10**
- Ausgewählte Zyklen des vorhandenen Primalzertifikats: **{', '.join(map(str,selected))}**
- Nicht benötigte Zyklen: **{', '.join(map(str,unused))}**

Die Hauptgrafik zeigt den Grundgraphen, alle zwölf Hamiltonkreise mit der zertifizierten 10er-Auswahl sowie die 21×10-Signaturmatrix. Die Signaturen sind paarweise inkomparabel. Die Aussage, dass neun Zyklen nicht genügen, stützt sich auf das vorhandene exakte Lower-Bound-Zertifikat mit 4.017 geprüften Teilmengen; sie wird nicht aus der Grafik abgeleitet.

Alle Graphteilbilder verwenden die Koordinatenbasis `{layout['normalized_coordinate_sha256']}` aus dem vorhandenen n=14-Atlas und unterscheiden sich nur durch uniforme Skalierung und Translation.

## Dateien

- `hsep_n14_explained.svg`, `.png`, `.pdf`: didaktische Hauptgrafik
- `selected_10_cycles.json`: extrahiertes Primalzertifikat
- `signature_matrix.csv`: 21 Kantensignaturen bezüglich der zehn ausgewählten Zyklen
- `didactic_figure_verification.json`: maschinenlesbare Qualitätsprüfung
- `build_hsep_explainer.py`: reproduzierbarer Builder

## Reproduktion

```powershell
python {Path(__file__).name} --source ..\\n14_all_hamiltonian_cycles_20260803_194908 --output .
```
"""
        write_new(output/"README.md",readme.encode("utf-8"))
        print(json.dumps({"output":str(output),"selected":selected,"unused":unused,"success":True},ensure_ascii=False))
        return 0
    except (BuildError,OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 1


if __name__=="__main__": raise SystemExit(main())
