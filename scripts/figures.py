"""도형 구조 명세(JSON)를 SVG로 그린다 (B+ 방식: AI는 구조만 쓰고 코드가 좌표를 계산한다).

사용: from figures import render;  svg = render({"type": "circle_sector", "params": {...}})
지원: circle_sector, number_line, coordinate_plane, polygon_labeled(삼각형 SSS·직각 포함, 임의 다각형),
      angle_diagram, parallel_transversal, histogram
수치 라벨은 params의 값을 그대로 쓰고, 좌표는 params로부터 계산하므로 글과 그림이 어긋나지 않는다.
"""
import math
from xml.sax.saxutils import escape

FONT = "font-family='Malgun Gothic, sans-serif'"
INK, GRID, FILL = "#222", "#cfd4da", "#d6e6f5"


class Svg:
    def __init__(self, w, h):
        self.w, self.h, self.parts = w, h, []

    def add(self, s):
        self.parts.append(s)

    def line(self, x1, y1, x2, y2, color=INK, w=1.6, dash=None):
        d = f" stroke-dasharray='{dash}'" if dash else ""
        self.add(f"<line x1='{x1:.2f}' y1='{y1:.2f}' x2='{x2:.2f}' y2='{y2:.2f}' stroke='{color}' stroke-width='{w}'{d} stroke-linecap='round'/>")

    def text(self, x, y, s, size=14, anchor="middle", color=INK, italic=False):
        st = " font-style='italic'" if italic else ""
        self.add(f"<text x='{x:.2f}' y='{y:.2f}' font-size='{size}' text-anchor='{anchor}' fill='{color}' {FONT}{st}>{escape(str(s))}</text>")

    def dot(self, x, y, r=3.2, color=INK):
        self.add(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='{r}' fill='{color}'/>")

    def path(self, d, fill="none", stroke=INK, w=1.6):
        self.add(f"<path d='{d}' fill='{fill}' stroke='{stroke}' stroke-width='{w}' stroke-linejoin='round'/>")

    def out(self):
        return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{self.w}' height='{self.h}' viewBox='0 0 {self.w} {self.h}'>"
                f"<rect width='100%' height='100%' fill='white'/>" + "".join(self.parts) + "</svg>")


def _fmt(v):
    return str(int(v)) if float(v) == int(v) else f"{v:g}"


def _polar(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy - r * math.sin(a)


def _angle_arc(s, cx, cy, r, a1, a2, label=None, color=INK):
    """a1에서 a2(도, 반시계)까지 호를 그리고 중간에 라벨을 둔다."""
    x1, y1 = _polar(cx, cy, r, a1)
    x2, y2 = _polar(cx, cy, r, a2)
    large = 1 if (a2 - a1) % 360 > 180 else 0
    s.path(f"M{x1:.2f},{y1:.2f} A{r},{r} 0 {large} 0 {x2:.2f},{y2:.2f}", stroke=color, w=1.2)
    if label:
        mx, my = _polar(cx, cy, r + 14, (a1 + (a2 - a1) % 360 / 2))
        s.text(mx, my + 5, label, 12)


# ---------- 부채꼴 ----------
def circle_sector(p):
    R, ang = float(p["radius"]), float(p["angle"])
    labels = p.get("labels", ["O", "A", "B"])
    show = p.get("show", ["radius", "angle"])
    unit = p.get("unit", "cm")
    size = 260
    s = Svg(size, size)
    cx = cy = size / 2
    r = size / 2 - 38
    start = p.get("start", -ang / 2)           # 부채꼴이 위쪽 중앙에 오도록 기본 배치
    start = p.get("start", 90 - ang / 2)
    end = start + ang
    if p.get("full_circle", True):
        s.add(f"<circle cx='{cx}' cy='{cy}' r='{r}' fill='none' stroke='{GRID}' stroke-width='1.2' stroke-dasharray='4 3'/>")
    x1, y1 = _polar(cx, cy, r, start)
    x2, y2 = _polar(cx, cy, r, end)
    large = 1 if ang > 180 else 0
    s.path(f"M{cx},{cy} L{x1:.2f},{y1:.2f} A{r},{r} 0 {large} 0 {x2:.2f},{y2:.2f} Z", fill=FILL)
    s.dot(cx, cy)
    s.text(cx - 12, cy + 16, labels[0], 14, italic=True)
    for (x, y), name, a in ((( x1, y1), labels[1], start), ((x2, y2), labels[2], end)):
        ox, oy = _polar(cx, cy, r + 16, a)
        s.text(ox, oy + 5, name, 14, italic=True)
    if "radius" in show:                                   # 반지름 선 바깥쪽(부채꼴 반대편)에 표시
        mx, my = (cx + x1) / 2, (cy + y1) / 2
        nx, ny = math.sin(math.radians(start)), math.cos(math.radians(start))
        s.text(mx + nx * 16, my + ny * 16 + 4, f"{_fmt(R)}{unit}", 12)
    if "angle" in show:
        _angle_arc(s, cx, cy, 26, start, end, f"{_fmt(ang)}°")
    if "arc" in show and p.get("arcLabel"):
        mx, my = _polar(cx, cy, r + 22, start + ang / 2)
        s.text(mx, my, p["arcLabel"], 12)
    return s.out()


# ---------- 수직선 ----------
def number_line(p):
    lo, hi = float(p["min"]), float(p["max"])
    step = float(p.get("step", 1))
    pts = p.get("points", {})
    W, H, pad = 460, 90, 30
    s = Svg(W, H)
    y = 46
    x_of = lambda v: pad + (v - lo) / (hi - lo) * (W - 2 * pad)
    s.line(pad - 12, y, W - pad + 12, y)
    s.add(f"<polygon points='{W-pad+14},{y} {W-pad+6},{y-4} {W-pad+6},{y+4}' fill='{INK}'/>")
    v = lo
    while v <= hi + 1e-9:
        x = x_of(v)
        s.line(x, y - 5, x, y + 5, w=1.2)
        s.text(x, y + 22, _fmt(v), 12)
        v += step
    for name, val in pts.items():
        x = x_of(float(val))
        s.dot(x, y, 4.2)
        s.text(x, y - 12, name, 14, italic=True)
    return s.out()


# ---------- 좌표평면 ----------
def coordinate_plane(p):
    xmin, xmax = p.get("xmin", -5), p.get("xmax", 5)
    ymin, ymax = p.get("ymin", -5), p.get("ymax", 5)
    unit = p.get("unit", 36)
    padL, padT, padR, padB = 26, 20, 26, 26
    W = padL + padR + (xmax - xmin) * unit
    H = padT + padB + (ymax - ymin) * unit
    s = Svg(W, H)
    X = lambda x: padL + (x - xmin) * unit
    Y = lambda y: padT + (ymax - y) * unit
    if p.get("grid", True):
        for i in range(int(xmin), int(xmax) + 1):
            s.line(X(i), Y(ymin), X(i), Y(ymax), GRID, 0.8)
        for j in range(int(ymin), int(ymax) + 1):
            s.line(X(xmin), Y(j), X(xmax), Y(j), GRID, 0.8)
    s.line(X(xmin), Y(0), X(xmax) + 8, Y(0), w=1.6)
    s.line(X(0), Y(ymax) - 8, X(0), Y(ymin), w=1.6)
    s.text(X(xmax) + 14, Y(0) + 5, p.get("xlabel", "x"), 14, italic=True)
    s.text(X(0) + 12, Y(ymax) - 10, p.get("ylabel", "y"), 14, italic=True)
    s.text(X(0) - 8, Y(0) + 15, "O", 13, italic=True)
    for i in range(int(xmin), int(xmax) + 1):
        if i != 0 and (i % p.get("tick", 1) == 0):
            s.text(X(i), Y(0) + 15, i, 11)
    for j in range(int(ymin), int(ymax) + 1):
        if j != 0 and (j % p.get("tick", 1) == 0):
            s.text(X(0) - 10, Y(j) + 4, j, 11, anchor="end")
    for ln in p.get("lines", []):                      # y = a x + b
        a, b = ln.get("a", 0), ln.get("b", 0)
        pts = [(xmin, a * xmin + b), (xmax, a * xmax + b)]
        if "xrange" in ln:
            pts = [(ln["xrange"][0], a * ln["xrange"][0] + b), (ln["xrange"][1], a * ln["xrange"][1] + b)]
        s.line(X(pts[0][0]), Y(max(min(pts[0][1], ymax), ymin)), X(pts[1][0]), Y(max(min(pts[1][1], ymax), ymin)), ln.get("color", "#d9480f"), 2)
        if ln.get("label"):
            s.text(X(pts[1][0]) - 6, Y(max(min(pts[1][1], ymax), ymin)) - 6, ln["label"], 13, anchor="end", italic=True)
    for h in p.get("hyperbolas", []):                  # y = k / x
        k = h["k"]
        for sign in (1, -1):
            pts = []
            n = 160
            for i in range(1, n):
                x = sign * (abs(k) / ymax * 0.9 + i * (xmax - abs(k) / ymax * 0.9) / n)
                y = k / x
                if ymin <= y <= ymax and xmin <= x <= xmax:
                    pts.append((X(x), Y(y)))
            if len(pts) > 1:
                s.path("M" + " L".join(f"{a:.1f},{b:.1f}" for a, b in pts), stroke="#d9480f", w=2)
    for name, (x, y) in p.get("points", {}).items():
        s.dot(X(x), Y(y), 3.6, "#1c64c4")
        if not name.startswith("_"):
            s.text(X(x) + 8, Y(y) - 6, name, 13, anchor="start", italic=True)
    return s.out()


# ---------- 다각형(삼각형 SSS, 임의 다각형) ----------
def _triangle_from_sides(a, b, c):
    """변 길이 a=BC, b=CA, c=AB 로 좌표 계산 (B 왼쪽 아래, C 오른쪽 아래)."""
    if not (a + b > c and b + c > a and a + c > b):
        raise ValueError("삼각형이 만들어지지 않는 변의 길이")
    B, C = (0.0, 0.0), (a, 0.0)
    x = (c * c + a * a - b * b) / (2 * a)
    y = math.sqrt(max(c * c - x * x, 0))
    return {"A": (x, y), "B": B, "C": C}


def polygon_labeled(p):
    if "sides" in p and len(p.get("vertices", ["A", "B", "C"])) == 3:
        sd = p["sides"]
        pts = _triangle_from_sides(float(sd["BC"]), float(sd["CA"]), float(sd["AB"]))
        names = ["A", "B", "C"]
        coords = [pts[n] for n in names]
    else:
        names = p["vertices"]
        coords = [tuple(map(float, c)) for c in p["coords"]]
    W, H, pad = 320, 240, 44
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    k = min((W - 2 * pad) / (max(xs) - min(xs) or 1), (H - 2 * pad) / (max(ys) - min(ys) or 1))
    P = [(pad + (x - min(xs)) * k, H - pad - (y - min(ys)) * k) for x, y in coords]
    s = Svg(W, H)
    s.path("M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in P) + " Z", fill=p.get("fill", "#eef4fb"))
    n = len(P)
    cx, cy = sum(x for x, _ in P) / n, sum(y for _, y in P) / n
    for (x, y), nm in zip(P, names):
        dx, dy = x - cx, y - cy
        d = math.hypot(dx, dy) or 1
        s.dot(x, y, 2.8)
        s.text(x + dx / d * 14, y + dy / d * 14 + 5, nm, 14, italic=True)
    if p.get("show_sides"):
        for i in range(n):
            j = (i + 1) % n
            key = names[i] + names[j]
            val = p.get("side_labels", {}).get(key) or p.get("side_labels", {}).get(names[j] + names[i])
            if val is not None:
                mx, my = (P[i][0] + P[j][0]) / 2, (P[i][1] + P[j][1]) / 2
                dx, dy = mx - cx, my - cy
                d = math.hypot(dx, dy) or 1
                s.text(mx + dx / d * 14, my + dy / d * 14 + 4, val, 12)
    for nm, val in p.get("angle_labels", {}).items():  # 꼭짓점 안쪽에 각 크기
        i = names.index(nm)
        x, y = P[i]
        dx, dy = cx - x, cy - y
        d = math.hypot(dx, dy) or 1
        s.text(x + dx / d * 24, y + dy / d * 24 + 4, val, 12)
    ra = p.get("right_angle")
    if ra:
        i = names.index(ra)
        x, y = P[i]
        a, b = P[(i - 1) % n], P[(i + 1) % n]
        ux, uy = a[0] - x, a[1] - y
        vx, vy = b[0] - x, b[1] - y
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        t = 11
        p1 = (x + ux / lu * t, y + uy / lu * t)
        p2 = (x + vx / lv * t, y + vy / lv * t)
        p3 = (p1[0] + vx / lv * t, p1[1] + vy / lv * t)
        s.path(f"M{p1[0]:.1f},{p1[1]:.1f} L{p3[0]:.1f},{p3[1]:.1f} L{p2[0]:.1f},{p2[1]:.1f}", stroke=INK, w=1.2)
    return s.out()


# ---------- 각 ----------
def angle_diagram(p):
    vname = p.get("vertex", "O")
    rays = p.get("rays", [{"name": "A", "deg": 0}, {"name": "B", "deg": 50}])
    val = p.get("value")
    W, H = 280, 220
    s = Svg(W, H)
    cx, cy, L = 50, 160, 190
    for r in rays:
        x, y = _polar(cx, cy, L, r["deg"])
        s.line(cx, cy, x, y)
        tx, ty = _polar(cx, cy, L + 12, r["deg"])
        s.text(tx, ty + 5, r["name"], 14, italic=True)
    s.dot(cx, cy)
    s.text(cx - 10, cy + 18, vname, 14, italic=True)
    if len(rays) >= 2:
        a1, a2 = rays[0]["deg"], rays[1]["deg"]
        _angle_arc(s, cx, cy, 34, a1, a2, f"{_fmt(val)}°" if val is not None else p.get("label"))
    return s.out()


# ---------- 평행선과 한 직선 ----------
def parallel_transversal(p):
    ang = float(p.get("angle", 60))
    W, H = 320, 240
    s = Svg(W, H)
    y1, y2 = 85, 165
    s.line(20, y1, 300, y1)
    s.line(20, y2, 300, y2)
    s.text(306, y1 + 5, p.get("l", "l"), 14, anchor="start", italic=True)
    s.text(306, y2 + 5, p.get("m", "m"), 14, anchor="start", italic=True)
    t = math.tan(math.radians(ang))
    xc = 160
    x_at = lambda y: xc + (y - (y1 + y2) / 2) / t * -1
    s.line(x_at(30), 30, x_at(215), 215)
    s.text(x_at(30) - 2, 22, p.get("n", "n"), 14, italic=True)
    labels = p.get("angle_labels", {})
    pos = {"a": (-1, -1), "b": (1, -1), "c": (-1, 1), "d": (1, 1)}
    for row, yy in (("", y1), ("'", y2)):
        xx = x_at(yy)
        for key, (sx, sy) in pos.items():
            name = key if not row else {"a": "e", "b": "f", "c": "g", "d": "h"}[key]
            if name in labels:
                s.text(xx + sx * 22, yy + sy * 18 + 4, labels[name], 13)
    return s.out()


# ---------- 히스토그램 / 도수분포다각형 ----------
def histogram(p):
    classes = p["classes"]                                   # [[lo, hi], ...]
    freqs = p["freqs"]
    W, H = 380, 250
    padL, padB, padT, padR = 46, 42, 24, 20
    s = Svg(W, H)
    lo, hi = classes[0][0], classes[-1][1]
    cw0 = classes[0][1] - classes[0][0]
    if p.get("polygon"):                                   # 도수분포다각형은 양끝에 도수 0인 계급을 하나씩 더 둔다
        lo, hi = lo - cw0, hi + cw0
    ymax = p.get("ymax") or math.ceil(max(freqs) * 1.15)
    X = lambda v: padL + (v - lo) / (hi - lo) * (W - padL - padR)
    Y = lambda v: H - padB - v / ymax * (H - padB - padT)
    for j in range(0, int(ymax) + 1, p.get("ystep", 1)):
        s.line(padL, Y(j), W - padR, Y(j), GRID, 0.7)
        s.text(padL - 6, Y(j) + 4, j, 11, anchor="end")
    s.line(padL, Y(0), W - padR + 6, Y(0))
    s.line(padL, Y(0), padL, padT - 6)
    hide = set(p.get("hide_freq_idx", []))
    if p.get("bars", True):
        for i, ((a, b), f) in enumerate(zip(classes, freqs)):
            if i in hide:
                continue
            s.add(f"<rect x='{X(a):.1f}' y='{Y(f):.1f}' width='{X(b)-X(a):.1f}' height='{Y(0)-Y(f):.1f}' fill='{FILL}' stroke='{INK}' stroke-width='1.3'/>")
    edges = [c[0] for c in classes] + [classes[-1][1]]
    if p.get("polygon"):
        edges = [edges[0] - cw0] + edges + [edges[-1] + cw0]
    for v in edges:
        s.text(X(v), Y(0) + 15, _fmt(v), 11)
    if p.get("polygon"):
        mids = [((a + b) / 2, f) for (a, b), f in zip(classes, freqs)]
        w = classes[0][1] - classes[0][0]
        pts = [(classes[0][0] - w / 2, 0)] + mids + [(classes[-1][1] + w / 2, 0)]
        s.path("M" + " L".join(f"{X(x):.1f},{Y(y):.1f}" for x, y in pts), stroke="#d9480f", w=2)
        for x, y in mids:
            s.dot(X(x), Y(y), 3.2, "#d9480f")
    s.text(W / 2, H - 6, p.get("xlabel", ""), 12)
    s.text(padL - 6, padT - 10, p.get("ylabel", "(도수)"), 12, anchor="end")
    return s.out()


def figure_problems(fig):
    """그림 명세가 본문과 모순될 만한 문제(빈 그림 등)를 글로 돌려준다. 문제가 없으면 빈 목록."""
    out = []
    if fig.get("type") == "histogram":
        p = fig.get("params", {})
        n = len(p.get("classes", []))
        if len(p.get("freqs", [])) != n:
            out.append(f"계급 수({n})와 도수 수({len(p.get('freqs', []))})가 다르다")
        hide = set(p.get("hide_freq_idx", []))
        bad = sorted(i for i in hide if not (isinstance(i, int) and 0 <= i < n))
        if bad:
            out.append(f"hide_freq_idx {bad}가 계급 번호(0~{n - 1}) 범위를 벗어났다")
        shown = bool(p.get("bars", True)) and any(i not in hide for i in range(n))
        if not shown and not p.get("polygon"):
            out.append("모든 막대를 숨겨 눈금만 있는 빈 그림이 된다. 본문이 '그림에 나타나 있다/그림을 읽는다'고 하면 모순이다. 학생이 직접 그리게 할 계급만 hide_freq_idx에 넣고, 보여 줄 그림은 hide_freq_idx를 빈 배열로 둔다")
    return out


RENDERERS = {
    "circle_sector": circle_sector, "number_line": number_line, "coordinate_plane": coordinate_plane,
    "polygon_labeled": polygon_labeled, "angle_diagram": angle_diagram,
    "parallel_transversal": parallel_transversal, "histogram": histogram,
}


def render(fig):
    """그림 명세 {type, params}를 SVG 문자열로 바꾼다."""
    t = fig["type"]
    if t not in RENDERERS:
        raise ValueError(f"아직 렌더러가 없는 그림 유형: {t}")
    return RENDERERS[t](fig.get("params", {}))
