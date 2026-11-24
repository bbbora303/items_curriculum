"""그림 렌더러 시험: 여러 그림을 SVG로 저장하고 PNG 모음 이미지를 만든다. 사용: python render_demo.py <출력폴더>"""
import os
import sys

import pymupdf

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from figures import render  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
DEMOS = {
    "sector": {"type": "circle_sector", "params": {"radius": 6, "angle": 120, "labels": ["O", "A", "B"], "show": ["radius", "angle"]}},
    "numline": {"type": "number_line", "params": {"min": -5, "max": 5, "points": {"A": -3, "O": 0, "B": 2}}},
    "coord": {"type": "coordinate_plane", "params": {"xmin": -1, "xmax": 6, "ymin": -1, "ymax": 6, "points": {"A": [2, 4], "B": [5, 1]}, "lines": [{"a": 2, "b": 0, "label": "y=2x"}]}},
    "inverse": {"type": "coordinate_plane", "params": {"xmin": -6, "xmax": 6, "ymin": -6, "ymax": 6, "hyperbolas": [{"k": 6}], "points": {"P": [2, 3]}}},
    "tri": {"type": "polygon_labeled", "params": {"sides": {"AB": 3, "BC": 4, "CA": 5}, "show_sides": True, "side_labels": {"AB": "3 cm", "BC": "4 cm", "CA": "5 cm"}, "right_angle": "B"}},
    "pent": {"type": "polygon_labeled", "params": {"vertices": ["A", "B", "C", "D", "E"], "coords": [[1, 0], [3, 0], [3.8, 1.8], [2, 3], [0.2, 1.8]], "angle_labels": {"A": "108°", "B": "108°"}}},
    "angle": {"type": "angle_diagram", "params": {"vertex": "O", "rays": [{"name": "A", "deg": 0}, {"name": "B", "deg": 50}], "value": 50}},
    "parallel": {"type": "parallel_transversal", "params": {"angle": 65, "angle_labels": {"a": "∠a", "b": "∠b", "c": "∠c", "d": "∠d", "e": "∠e", "f": "∠f", "g": "∠g", "h": "∠h"}}},
    "hist": {"type": "histogram", "params": {"classes": [[3, 4], [4, 5], [5, 6], [6, 7], [7, 8]], "freqs": [5, 4, 3, 2, 3], "polygon": True, "xlabel": "가격(천 원)"}},
}
pix = []
for name, fig in DEMOS.items():
    svg = render(fig)
    path = os.path.join(out, name + ".svg")
    open(path, "w", encoding="utf-8").write(svg)
    page = pymupdf.open(path)[0] if False else None
    doc = pymupdf.open(path)
    p = doc.load_page(0)
    pm = p.get_pixmap(matrix=pymupdf.Matrix(1.2, 1.2))
    pix.append(pm)
cols, cw, ch = 3, max(p.width for p in pix), max(p.height for p in pix)
rows = (len(pix) + cols - 1) // cols
sheet = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, cols * cw, rows * ch), False)
sheet.set_rect(sheet.irect, (255, 255, 255))
for i, pm in enumerate(pix):
    pm = pymupdf.Pixmap(pymupdf.csRGB, pm)
    pm.set_origin((i % cols) * cw, (i // cols) * ch)
    sheet.copy(pm, pm.irect)
sheet.save(os.path.join(out, "demo_sheet.png"))
print("saved", os.path.join(out, "demo_sheet.png"), sheet.width, sheet.height)
