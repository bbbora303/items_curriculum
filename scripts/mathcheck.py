"""AI가 쓴 수식 문자열을 안전하게 계산하는 모듈 (수치 구조 명세 + 정답 검산 공용).

- 파이썬 `eval`을 쓰지 않는다. `ast`로 파싱한 뒤 허용한 노드·함수만 직접 해석한다.
- 숫자는 SymPy 정수·유리수로 정확하게 계산한다. 소수 리터럴은 유리수로 바꾼다(0.5 -> 1/2).
- 허용 연산: + - * / ** %, 비교, and/or/not, in, 튜플, 아래 FUNCS의 함수.
"""
import ast

import sympy as sp

MAX_EXP = 24
MAX_NODES = 200

_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b, ast.Pow: None, ast.Mod: lambda a, b: a % b,
        ast.FloorDiv: lambda a, b: sp.floor(a / b)}
_CMP = {ast.Eq: lambda a, b: bool(sp.simplify(a - b) == 0) if _is_num(a) and _is_num(b) else a == b,
        ast.NotEq: None, ast.Lt: lambda a, b: bool(a < b), ast.LtE: lambda a, b: bool(a <= b),
        ast.Gt: lambda a, b: bool(a > b), ast.GtE: lambda a, b: bool(a >= b),
        ast.In: lambda a, b: any(_same(a, x) for x in b), ast.NotIn: None}


def _is_num(x):
    return isinstance(x, sp.Basic)


def _same(a, b):
    return bool(sp.simplify(a - b) == 0) if _is_num(a) and _is_num(b) else a == b


def _rat(x):
    r = sp.nsimplify(x, rational=True) if not x.is_Rational else x
    if not r.is_Rational:
        raise ValueError(f"유리수가 아님: {x}")
    return r


def f_denom(x):
    return _rat(x).q


def f_numer(x):
    return _rat(x).p


def f_coef_pi(x):
    """x = (유리수) * pi 꼴일 때 유리수 계수를 돌려준다."""
    return _rat(sp.simplify(x / sp.pi))


def f_is_int(x):
    return bool(sp.simplify(x).is_Integer)


def f_is_square(n):
    n = sp.Integer(n)
    return n >= 0 and sp.integer_nthroot(int(n), 2)[1]


# ---- 자료(통계) 함수: 자료는 정수 튜플이다. dataset(씨앗, 개수, 최솟값, 최댓값[, 모양])이 같은 씨앗이면 항상 같은 자료를 만든다 ----
MAX_DATA = 60


def _seq(x):
    if not isinstance(x, tuple) or not x:
        raise SafeEvalError("자료(목록)가 필요하다")
    return x


def f_dataset(seed, n, lo, hi, shape=1):
    """씨앗으로 정수 자료를 만든다. 모양 1(기본)=가운데에 몰리는 분포(두 수의 평균), 0=고르게 흩어짐."""
    import random
    seed, n, lo, hi, shape = int(seed), int(n), int(lo), int(hi), int(shape)
    if not (1 <= n <= MAX_DATA) or lo > hi:
        raise SafeEvalError("자료 개수는 1~60, 최솟값은 최댓값 이하여야 한다")
    rng = random.Random(seed * 1000003 + n * 131 + lo * 7 + hi)
    out = []
    for _ in range(n):
        if shape:
            v = (rng.randint(lo, hi) + rng.randint(lo, hi) + 1) // 2
        else:
            v = rng.randint(lo, hi)
        out.append(sp.Integer(v))
    return tuple(out)


def f_len(d):
    return sp.Integer(len(_seq(d)))


def f_sum(d):
    return sp.Add(*_seq(d))


def f_sorted(d):
    return tuple(sorted(_seq(d), key=lambda v: float(v)))


def f_mean(d):
    return sp.Rational(f_sum(d), len(d))


def f_median(d):
    s = f_sorted(d)
    m = len(s)
    return s[m // 2] if m % 2 else sp.Rational(s[m // 2 - 1] + s[m // 2], 2)


def _modes(d):
    from collections import Counter
    c = Counter(_seq(d))
    top = max(c.values())
    return sorted((v for v, k in c.items() if k == top), key=lambda v: float(v)), top


def f_mode(d):
    """최빈값(여러 개면 가장 작은 값). 하나인지는 n_modes로 따로 확인한다."""
    return _modes(d)[0][0]


def f_n_modes(d):
    return sp.Integer(len(_modes(d)[0]))


def f_mode_freq(d):
    return sp.Integer(_modes(d)[1])


def f_count(d, x):
    return sp.Integer(sum(1 for v in _seq(d) if v == x))


def f_count_between(d, lo, hi):
    """lo 이상 hi 미만인 값의 개수(도수분포표의 한 계급)."""
    return sp.Integer(sum(1 for v in _seq(d) if lo <= v < hi))


def f_rel_freq(d, lo, hi):
    return sp.Rational(f_count_between(d, lo, hi), len(d))


def f_data_range(d):
    s = _seq(d)
    return max(s, key=float) - min(s, key=float)


def f_distinct(d):
    return sp.Integer(len(set(_seq(d))))


def f_item(d, i):
    s = _seq(d)
    i = int(i)
    if not 0 <= i < len(s):
        raise SafeEvalError("자료 번호 범위 밖")
    return s[i]


def f_dmin(d):
    return min(_seq(d), key=float)


def f_dmax(d):
    return max(_seq(d), key=float)


DATA_FUNCS = {"dataset": f_dataset, "len": f_len, "sum": f_sum, "sorted": f_sorted, "mean": f_mean, "median": f_median, "mode": f_mode,
              "n_modes": f_n_modes, "mode_freq": f_mode_freq, "count": f_count, "count_between": f_count_between, "rel_freq": f_rel_freq,
              "data_range": f_data_range, "distinct": f_distinct, "item": f_item, "dmin": f_dmin, "dmax": f_dmax}


FUNCS = {
    "sqrt": sp.sqrt, "abs": sp.Abs, "floor": sp.floor, "ceil": sp.ceiling, "gcd": sp.gcd, "lcm": sp.lcm,
    "min": lambda *a: (f_dmin(a[0]) if len(a) == 1 and isinstance(a[0], tuple) else min(*a)), "max": lambda *a: (f_dmax(a[0]) if len(a) == 1 and isinstance(a[0], tuple) else max(*a)), "denom": f_denom, "numer": f_numer, "coef_pi": f_coef_pi,
    "is_int": f_is_int, "is_square": f_is_square, "simplify": sp.simplify,
}
FUNCS.update(DATA_FUNCS)
CONSTS = {"pi": sp.pi}


class SafeEvalError(ValueError):
    pass


def _ev(node, env, count):
    count[0] += 1
    if count[0] > MAX_NODES:
        raise SafeEvalError("식이 너무 김")
    t = type(node)
    if t is ast.Expression:
        return _ev(node.body, env, count)
    if t is ast.Constant:
        v = node.value
        if isinstance(v, bool):
            return v
        if isinstance(v, int):
            return sp.Integer(v)
        if isinstance(v, float):
            return sp.Rational(str(v))
        raise SafeEvalError(f"허용하지 않는 상수: {v!r}")
    if t is ast.Name:
        if node.id in env:
            return env[node.id]
        if node.id in CONSTS:
            return CONSTS[node.id]
        raise SafeEvalError(f"알 수 없는 이름: {node.id}")
    if t is ast.Tuple or t is ast.List:
        return tuple(_ev(e, env, count) for e in node.elts)
    if t is ast.UnaryOp:
        v = _ev(node.operand, env, count)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.UAdd):
            return v
        if isinstance(node.op, ast.Not):
            return not v
        raise SafeEvalError("허용하지 않는 단항 연산")
    if t is ast.BinOp:
        a, b = _ev(node.left, env, count), _ev(node.right, env, count)
        op = type(node.op)
        if op is ast.Pow:
            if _is_num(b) and b.is_Number and abs(b) > MAX_EXP:
                raise SafeEvalError("지수가 너무 큼")
            return a ** b
        if op in _BIN:
            if op in (ast.Div, ast.Mod, ast.FloorDiv) and _is_num(b) and b == 0:
                raise SafeEvalError("0으로 나눔")
            return _BIN[op](a, b)
        raise SafeEvalError("허용하지 않는 연산")
    if t is ast.BoolOp:
        vals = [_ev(v, env, count) for v in node.values]
        return all(vals) if isinstance(node.op, ast.And) else any(vals)
    if t is ast.Compare:
        left = _ev(node.left, env, count)
        for op, comp in zip(node.ops, node.comparators):
            right = _ev(comp, env, count)
            o = type(op)
            if o is ast.NotEq:
                ok = not _CMP[ast.Eq](left, right)
            elif o is ast.NotIn:
                ok = not _CMP[ast.In](left, right)
            elif o in _CMP:
                ok = _CMP[o](left, right)
            else:
                raise SafeEvalError("허용하지 않는 비교")
            if not ok:
                return False
            left = right
        return True
    if t is ast.Call:
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS or node.keywords:
            raise SafeEvalError("허용하지 않는 함수 호출")
        return FUNCS[node.func.id](*[_ev(a, env, count) for a in node.args])
    raise SafeEvalError(f"허용하지 않는 구문: {t.__name__}")


def safe_eval(expr, env=None):
    """수식 문자열을 계산한다. env의 값은 정수·유리수·SymPy 식이어야 한다."""
    env = {k: (sp.Integer(v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in (env or {}).items()}
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise SafeEvalError(f"문법 오류: {e.msg}") from e
    return _ev(tree, env, [0])


def _is_bool(x):
    return isinstance(x, (bool, sp.logic.boolalg.BooleanAtom))


def equal(a, b):
    """두 수식 값이 같은지 (정확한 계산으로) 비교한다. 참/거짓 값은 참/거짓끼리만 비교한다."""
    if _is_bool(a) or _is_bool(b):
        return _is_bool(a) and _is_bool(b) and bool(a) == bool(b)
    return bool(sp.simplify(sp.sympify(a) - sp.sympify(b)) == 0)
