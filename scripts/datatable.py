"""자료(통계) 문항의 표를 코드가 그린다 — 자료 생성기의 표 부분.

문항 틀(item.template.json)의 stimulus.tables 에 이렇게 쓰면, 숫자를 채울 때 코드가 자료(수치 명세의 dataset 값)로 표를 만든다:
  {"id":"T1","caption":"[표 1] 학생 20명의 수학 점수(점)","autoTable":{"kind":"raw_row","data":"data","itemLabel":"학생","valueLabel":"점수(점)"}}
  {"id":"T2","caption":"...","autoTable":{"kind":"stem_leaf","data":"data"}}
  {"id":"T3","caption":"...","autoTable":{"kind":"freq_table","data":"data","start":"{{lo}}","width":10,"count":6,"total":true,"unit":"명"}}
  {"id":"T4","caption":"...","autoTable":{"kind":"rel_freq_table","data":"data","start":"{{lo}}","width":10,"count":6}}
종류:
  raw_row        자료를 그대로 나열한 표(번호 위, 값 아래). 개수가 perRow(기본 10)를 넘으면 줄을 나눈다.
  stem_leaf      줄기와 잎 그림(줄기=값//stemUnit, 잎=값%stemUnit, 잎은 작은 수부터). 줄기는 비어 있어도 모두 쓴다.
  freq_table     도수분포표(계급 start이상 start+width미만 ... , 도수, 합계). start/count를 생략하면 자료에 맞게 정한다.
  rel_freq_table 도수·상대도수(소수, 나누어떨어지지 않으면 분수) 표.
data 는 수치 명세에서 계산한 자료(정수 목록)의 이름이다.
"""
import math

import sympy as sp


def _vals(env, name):
    d = env.get(name)
    if not isinstance(d, tuple) or not d:
        raise ValueError(f"표의 자료 '{name}'을(를) 찾을 수 없다(수치 명세에서 dataset으로 만든 변수 이름이어야 한다)")
    return [int(v) for v in d]


def _classes(vals, spec):
    width = int(spec.get("width", 10))
    if width < 1:
        raise ValueError("계급의 크기는 1 이상이어야 한다")
    start = int(spec["start"]) if spec.get("start") not in (None, "") else (min(vals) // width) * width
    count = int(spec["count"]) if spec.get("count") not in (None, "") else math.ceil((max(vals) + 1 - start) / width)
    if start > min(vals) or start + width * count <= max(vals):
        raise ValueError(f"계급이 자료 전체를 덮지 못한다(자료 {min(vals)}~{max(vals)}, 계급 {start}~{start + width * count})")
    return [(start + i * width, start + (i + 1) * width) for i in range(count)]


def _dec(frac):
    """상대도수: 나누어떨어지면 소수, 아니면 분수 글자."""
    f = sp.Rational(frac)
    q = f.q
    for p in (2, 5):
        while q % p == 0:
            q //= p
    return str(float(f)).rstrip("0").rstrip(".") if q == 1 else f"{f.p}/{f.q}"


def build(spec, env):
    kind = spec.get("kind")
    vals = _vals(env, spec.get("data", "data"))
    n = len(vals)
    if kind == "raw_row":
        per = int(spec.get("perRow", 10))
        item_label = spec.get("itemLabel", "번호")
        value_label = spec.get("valueLabel", "값")
        headers = [item_label] + [f"{i + 1}번" for i in range(min(n, per))] if n <= per else ["번호"] + [str(i + 1) for i in range(per)]
        if n <= per:
            return headers, [[value_label] + [str(v) for v in vals]]
        rows = []
        for b in range(0, n, per):
            chunk = vals[b:b + per]
            rows.append([f"{b + 1}~{b + len(chunk)}번"] + [str(v) for v in chunk] + [""] * (per - len(chunk)))
        return ["번호(열 순서대로)"] + [str(i + 1) for i in range(per)], rows
    if kind == "stem_leaf":
        unit = int(spec.get("stemUnit", 10))
        stems = {}
        for v in sorted(vals):
            stems.setdefault(v // unit, []).append(v % unit)
        rows = [[str(s), " ".join(str(x) for x in stems.get(s, []))] for s in range(min(stems), max(stems) + 1)]
        return ["줄기", "잎"], rows
    if kind in ("freq_table", "rel_freq_table"):
        cls = _classes(vals, spec)
        counts = [sum(1 for v in vals if a <= v < b) for a, b in cls]
        if sum(counts) != n:
            raise ValueError("도수의 합이 자료 개수와 다르다")
        unit = spec.get("unit", "")
        if kind == "freq_table":
            rows = [[f"{a}이상 ~ {b}미만", str(c)] for (a, b), c in zip(cls, counts)]
            if spec.get("total", True):
                rows.append(["합계", str(n)])
            return ["계급", f"도수({unit})" if unit else "도수"], rows
        rows = [[f"{a}이상 ~ {b}미만", str(c), _dec(sp.Rational(c, n))] for (a, b), c in zip(cls, counts)]
        if spec.get("total", True):
            rows.append(["합계", str(n), "1"])
        return ["계급", f"도수({unit})" if unit else "도수", "상대도수"], rows
    raise ValueError(f"알 수 없는 표 종류: {kind}")


def expand_tables(item, env):
    """item.stimulus.tables 중 autoTable 이 있는 표를 실제 표(headers, rows)로 바꾼다. 바꾼 표 수를 돌려준다."""
    n = 0
    for t in (item.get("stimulus", {}).get("tables") or []):
        spec = t.pop("autoTable", None)
        if not spec:
            continue
        t["headers"], t["rows"] = build(spec, env)
        n += 1
    return n
