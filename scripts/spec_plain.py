"""숫자 규칙을 어긴 값을 쉬운 말로 설명한다 (웹 '숫자 규칙 보기·고치기' 패널의 오류 문구용).

예) 규칙 'p < q'를 어겼을 때:
  어긋난 규칙: p < q
    · p(두 수에 모두 들어 있는 작은 소인수) = 3, q(두 수에 모두 들어 있는 큰 소인수) = 3
    · 이 규칙은 ‘3 < 3’이어야 하는데 거짓입니다.
변수의 뜻(meaning)과 지금 값을 함께 보여 준다. 규칙 파일에 derivedMeaning(파생값 이름 → 뜻)이 있으면 계산식 대신 그 뜻을 쓴다.
"""
import ast

import sympy as sp

from mathcheck import safe_eval
import numgen

SYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "=", ast.NotEq: "≠"}
FUNCS = {"min", "max", "abs", "floor", "ceil", "gcd", "lcm"}


def _num(v):
    try:
        if isinstance(v, sp.Basic) and not v.is_Integer:
            return f"{v} (약 {float(v):.3g})"
    except Exception:
        pass
    return str(v)


def _names(expr):
    out = []
    for n in ast.walk(ast.parse(expr, mode="eval")):
        if isinstance(n, ast.Name) and n.id not in FUNCS and n.id not in out:
            out.append(n.id)
    return out


def _label(spec, name, env):
    val = _num(env[name]) if name in env else "계산 불가"
    v = spec["variables"].get(name)
    if v is not None:
        unit = v.get("unit") or ""
        return f"{name}({v['meaning']}) = {val}{unit}" if v.get("meaning") else f"{name} = {val}{unit}"
    mean = (spec.get("derivedMeaning") or {}).get(name)
    if mean:
        return f"{name}({mean}) = {val}"
    d = spec.get("derived", {}).get(name)
    return f"{name}(식 {d}) = {val}" if d else f"{name} = {val}"


def _check(expr, node, env):
    """(참/거짓, 설명 문장) — 비교는 지금 값으로, 또는/그리고는 항목별로 풀어 쓴다."""
    seg = ast.get_source_segment(expr, node)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in SYM:
        left, right = ast.get_source_segment(expr, node.left), ast.get_source_segment(expr, node.comparators[0])
        lv, rv = safe_eval(left, env), safe_eval(right, env)
        truth = bool(safe_eval(seg, env))
        return truth, f"‘{seg}’ → 지금 값으로는 {_num(lv)} {SYM[type(node.ops[0])]} {_num(rv)} 이므로 {'참' if truth else '거짓'}"
    if isinstance(node, ast.BoolOp):
        subs = [_check(expr, v, env) for v in node.values]
        is_or = isinstance(node.op, ast.Or)
        truth = any(t for t, _ in subs) if is_or else all(t for t, _ in subs)
        head = "다음 중 하나 이상이 참이어야 하는데 모두 거짓입니다" if is_or else "다음이 모두 참이어야 하는데 거짓인 것이 있습니다"
        return truth, head + ": " + " / ".join(f"({i}) {d}" for i, (_, d) in enumerate(subs, 1))
    truth = bool(safe_eval(seg, env))
    return truth, f"‘{seg}’이(가) {'참' if truth else '거짓'}입니다"


def explain_constraint(spec, expr, env):
    names = [n for n in _names(expr) if n in env or n in spec["variables"] or n in spec.get("derived", {})]
    lines = [f"어긋난 규칙: {expr}"]
    if names:
        lines.append("  · " + ", ".join(_label(spec, n, env) for n in names))
    try:
        _, desc = _check(expr, ast.parse(expr, mode="eval").body, env)
        lines.append("  · " + desc)
    except Exception:
        lines.append("  · 이 규칙은 지금 값에서 만족되지 않습니다.")
    return "\n".join(lines)


def explain_failed(spec, vals):
    """vals(변수값)로 규칙을 평가해 어긴 조건을 쉬운 말로 돌려준다. 모두 만족하면 빈 목록."""
    ok, env = numgen.evaluate(spec, {k: sp.Integer(v) if isinstance(v, int) else sp.Rational(str(v)) for k, v in vals.items()})
    if ok:
        return []
    out = []
    for name, expr in spec.get("derived", {}).items():      # 파생값 계산 자체가 안 되는 경우(0으로 나눔 등)
        if name not in env:
            out.append(f"‘{name} = {expr}’을(를) 계산할 수 없습니다(0으로 나누는 등). 숫자를 바꿔 주세요.")
            break
    for c in spec.get("constraints", []):
        try:
            if not safe_eval(c, env):
                out.append(explain_constraint(spec, c, env))
        except Exception:
            out.append(f"어긋난 규칙: {c}\n  · 지금 값으로는 이 규칙을 계산할 수 없습니다.")
    return out
