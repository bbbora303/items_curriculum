"""수치 구조 명세(JSON)에서 '답이 깔끔하게 떨어지는' 숫자 조합 후보를 만든다.

사용법: python numgen.py <spec.json> [개수=5] [시드=0] [난이도]
명세 형식은 docs/수치_구조_명세.md 참고. 명세의 식은 mathcheck.safe_eval로만 계산한다.
"""
import itertools
import json
import random
import sys

import sympy as sp

from mathcheck import SafeEvalError, safe_eval

MAX_COMBOS = 200_000


def domain(spec):
    """변수별 후보 값 목록."""
    out = {}
    for name, v in spec["variables"].items():
        if "values" in v:
            out[name] = [sp.Rational(str(x)) if isinstance(x, float) else sp.Integer(x) for x in v["values"]]
        else:
            lo, hi = v["range"]
            step = v.get("step", 1)
            out[name] = [sp.Integer(x) for x in range(lo, hi + 1, step)]
    return out


def evaluate(spec, values):
    """변수값으로 파생값을 계산하고 제약을 검사한다. (ok, env)"""
    env = dict(values)
    try:
        for name, expr in spec.get("derived", {}).items():
            env[name] = safe_eval(expr, env)
        for c in spec.get("constraints", []):
            if not safe_eval(c, env):
                return False, env
    except (SafeEvalError, ValueError, ZeroDivisionError, TypeError):
        return False, env
    return True, env


def _names(expr):
    import ast
    return {n.id for n in ast.walk(ast.parse(expr, mode="eval")) if isinstance(n, ast.Name)}


def candidates(spec, difficulty=None):
    dom = domain(spec)
    names = list(dom)
    total = 1
    for n in names:
        total *= len(dom[n])
    if total > MAX_COMBOS:
        raise ValueError(f"조합이 너무 많음: {total}")
    out = []
    # 변수만으로 정해지는 제약(예: p < q)은 파생값을 계산하기 전에 먼저 걸러 속도를 높인다
    varset = set(names)
    pre = [c for c in spec.get("constraints", []) if _names(c) <= varset]
    for combo in itertools.product(*[dom[n] for n in names]):
        vals = dict(zip(names, combo))
        try:
            if not all(safe_eval(c, vals) for c in pre):
                continue
        except (SafeEvalError, ValueError, ZeroDivisionError, TypeError):
            continue
        ok, env = evaluate(spec, vals)
        if not ok:
            continue
        if difficulty:
            expr = spec.get("difficulty", {}).get(difficulty)
            if expr is None or not safe_eval(expr, env):
                continue
        out.append(env)
    return out


def describe(spec, env):
    """사람이 읽는 형태(LaTeX 포함)로 바꾼다."""
    vars_ = {k: int(v) if v.is_Integer else str(v) for k, v in env.items() if k in spec["variables"]}
    derived = {k: {"value": str(v), "latex": sp.latex(v), "approx": float(v)} for k, v in env.items()
               if k in spec.get("derived", {}) and isinstance(v, sp.Basic)}
    return {"specId": spec["id"], "values": vars_, "derived": derived}


def sample(spec, n=5, seed=0, difficulty=None):
    pool = candidates(spec, difficulty)
    random.Random(seed).shuffle(pool)
    return [describe(spec, e) for e in pool[:n]], len(pool)


if __name__ == "__main__":
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    seed = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    diff = sys.argv[4] if len(sys.argv) > 4 else None
    picked, total = sample(spec, k, seed, diff)
    print(f"후보 {total}개 중 {len(picked)}개 (시드 {seed}, 난이도 {diff})")
    print(json.dumps(picked, ensure_ascii=False, indent=2))
