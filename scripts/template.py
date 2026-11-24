"""문항 템플릿({{자리표시자}})을 숫자로 채우는 모듈 — '수치만 바꾸기'를 AI 호출 없이 하기 위한 장치.

자리표시자 형식: {{식}} 또는 {{식|latex}}
  - 식은 수치 명세의 변수·파생값 이름과 mathcheck의 안전한 식만 쓴다. 예: {{r}}, {{2*r}}, {{arc|latex}}, {{area2/area}}
  - 문자열 전체가 자리표시자 하나이고 형식 지정이 없으면(예: "{{r}}") 숫자 값 자체를 돌려준다(그림 params용).
  - |latex 는 SymPy LaTeX(예: 8 \\pi), 지정이 없으면 정수·분수는 일반 글자(예: 9, 1/3)로 쓴다.
"""
import json
import copy
import re

import sympy as sp

from mathcheck import SafeEvalError, safe_eval
import numgen
import datatable

PH = re.compile(r"\{\{\s*(.+?)\s*\}\}")
RAW_KEYS = {"expr", "expected"}          # 검산 식은 자리표시자가 아니라 변수 식이므로 건드리지 않는다

# ---- 조사 자동 처리 -------------------------------------------------------------------------------
_JOSA = {"은": ("은", "는"), "는": ("은", "는"), "이": ("이", "가"), "가": ("이", "가"), "을": ("을", "를"), "를": ("을", "를"),
         "과": ("과", "와"), "와": ("과", "와"), "으로": ("으로", "로"), "로": ("으로", "로")}
_LAST_DIGIT_HAS_BATCHIM = set("013678")       # 영·일·삼·육·칠·팔은 받침이 있다(일·칠·팔은 ㄹ 받침)
_LAST_DIGIT_RIEUL = set("178")


def _digit_reading(val):
    """채워진 값의 마지막 읽는 숫자. 정수·소수·음수·분수(분자를 마지막으로 읽는다)만 처리하고, 그 밖의 식은 None."""
    v = val.strip()
    m = re.fullmatch(r"-?(\d+)/(\d+)", v)
    if m:
        return m.group(1)[-1]                 # a/b 는 'b분의 a'로 읽으므로 분자가 마지막
    if re.fullmatch(r"-?\d+(\.\d+)?", v):
        return v[-1]
    return None


def _josa_after(val, rest):
    """val 뒤에 붙은 조사(rest의 맨 앞)가 받침에 맞지 않으면 (맞는 조사, 바꾼 글자 수)를 돌려준다."""
    d = _digit_reading(val)
    if d is None or not rest:
        return None
    for josa in ("으로", "은", "는", "이", "가", "을", "를", "과", "와", "로"):
        if rest.startswith(josa):
            after = rest[len(josa):len(josa) + 1]
            if after and "가" <= after <= "힣":      # '이상', '가격', '는데'처럼 낱말의 앞부분이면 건드리지 않는다
                return None
            has = d in _LAST_DIGIT_HAS_BATCHIM
            if josa in ("으로", "로"):
                want = "으로" if (has and d not in _LAST_DIGIT_RIEUL) else "로"
            else:
                a, b = _JOSA[josa]
                want = a if has else b
            return (want, len(josa)) if want != josa else None
    return None


def _plain(v):
    if isinstance(v, tuple):                  # 자료(목록)는 '2, 3, 3, 5'처럼 쉼표로 이어 쓴다
        return ", ".join(_plain(x) for x in v)
    v = sp.nsimplify(v) if isinstance(v, sp.Basic) else v
    if isinstance(v, sp.Basic) and v.is_Integer:
        return str(int(v))
    if isinstance(v, sp.Basic) and v.is_Rational:
        return f"{v.p}/{v.q}"
    return str(v)


def _value(expr, env):
    fmt = None
    if "|" in expr:
        expr, fmt = expr.rsplit("|", 1)
        fmt = fmt.strip()
    v = safe_eval(expr.strip(), env)
    return v, fmt


def fill_string(s, env):
    m = PH.fullmatch(s.strip())
    if m and "|" not in m.group(1):              # 값 자체가 필요한 경우(그림 params 등)
        v, _ = _value(m.group(1), env)
        if isinstance(v, tuple):
            return _plain(v)
        if isinstance(v, sp.Basic):
            return int(v) if v.is_Integer else float(v)
        return v

    def sub(mm):
        v, fmt = _value(mm.group(1), env)
        if fmt == "latex":
            return sp.latex(v)
        return _plain(v)

    # 자리표시자 바로 뒤의 조사는 채워진 숫자에 맞게 고친다('252과'가 아니라 '252와', '60를'이 아니라 '60을')
    out, pos = [], 0
    for mm in PH.finditer(s):
        out.append(s[pos:mm.start()])
        val = sub(mm)
        rest = s[mm.end():]
        tail = ""
        while rest[:1] == "$":              # 수식 닫는 달러 기호는 그대로 두고 그 뒤 조사를 본다
            tail += "$"
            rest = rest[1:]
        fixed = _josa_after(val, rest)
        if fixed:
            out.append(val + tail + fixed[0])
            pos = len(s) - len(rest) + fixed[1]
        else:
            out.append(val)
            pos = mm.end()
    out.append(s[pos:])
    return "".join(out)


def fill(obj, env, key=None):
    if key in RAW_KEYS:
        return copy.deepcopy(obj)
    if isinstance(obj, str):
        return fill_string(obj, env) if "{{" in obj else obj
    if isinstance(obj, list):
        return [fill(x, env) for x in obj]
    if isinstance(obj, dict):
        return {k: fill(v, env, k) for k, v in obj.items()}
    return obj


def binding_env(spec, values):
    """변수값으로 파생값까지 계산한 환경을 만든다. 제약을 어기면 (None, 사유)."""
    vals = {k: sp.Integer(v) if isinstance(v, int) else sp.Rational(str(v)) for k, v in values.items()}
    ok, env = numgen.evaluate(spec, vals)
    return (env, None) if ok else (None, "수치 명세의 제약을 만족하지 않는다")


def render_item(template_item, spec, values):
    """템플릿 문항을 숫자로 채운 문항으로 바꾼다."""
    env, why = binding_env(spec, values)
    if env is None:
        raise ValueError(why)
    item = fill(template_item, env)
    datatable.expand_tables(item, env)            # 자료형 문항: autoTable 표를 코드가 그린다
    item["numberBinding"] = {"specId": spec["id"], "values": {k: int(v) if sp.Rational(str(v)).is_Integer else float(v) for k, v in values.items()}}
    item["templated"] = True
    return item


def placeholder_errors(template_item, spec, values):
    """채우는 도중 오류가 나는 자리표시자를 찾는다(알 수 없는 이름, 잘못된 식)."""
    env, why = binding_env(spec, values)
    if env is None:
        return [why]
    errs = []

    def walk(o, path, key=None):
        if key in RAW_KEYS:
            return
        if isinstance(o, str):
            for m in PH.finditer(o):
                try:
                    _value(m.group(1), env)
                except (SafeEvalError, ValueError, TypeError) as ex:
                    errs.append(f"{path}: 자리표시자 {{{{{m.group(1)}}}}} 오류 ({ex})")
        elif isinstance(o, list):
            for i, x in enumerate(o):
                walk(x, f"{path}[{i}]")
        elif isinstance(o, dict):
            for k, v in o.items():
                walk(v, f"{path}.{k}", k)

    walk(template_item, "item")
    return errs


_POOL_CACHE = {}


def _all_candidates(spec, names):
    """제약을 만족하는 모든 후보 [(값 dict, 계산 환경)]. 한 번 세면 프로세스 안에서(그리고 파일로) 재사용한다.
    후보가 드문 규칙에서 난이도에 맞는 숫자를 찾는 데 쓴다."""
    import hashlib
    h = hashlib.sha1(json.dumps({k: spec.get(k) for k in ("variables", "derived", "constraints")}, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    if h in _POOL_CACHE:
        return _POOL_CACHE[h]
    import os
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "numspecs_cache")
    path = os.path.join(cache_dir, f"{h}.json")
    out = []
    if os.path.exists(path):                        # 저장해 둔 후보 값으로 계산 환경만 다시 만든다(후보를 다시 세는 것보다 훨씬 빠르다)
        for vals in json.load(open(path, encoding="utf-8")):
            ok, env = numgen.evaluate(spec, {k: sp.Integer(x) if isinstance(x, int) else sp.Rational(str(x)) for k, x in vals.items()})
            if ok:
                out.append((vals, env))
    else:
        for e in numgen.candidates(spec):
            out.append(({k: (int(e[k]) if e[k].is_Integer else float(e[k])) for k in names}, e))
        os.makedirs(cache_dir, exist_ok=True)
        json.dump([v for v, _ in out], open(path, "w", encoding="utf-8"))
    _POOL_CACHE[h] = out
    return out


def pick_values(spec, seed, difficulty=None, exclude=None):
    """다른 숫자 조합을 코드가 고른다. exclude에 든 조합은 피한다."""
    import random
    import sympy as _sp
    rng = random.Random(seed)
    dom = numgen.domain(spec)
    names = list(dom)

    def attempt(diff, tries):
        for _ in range(tries):                       # 후보 전체를 세지 않고 무작위로 시도(수천 조합을 세면 1분 넘게 걸릴 수 있다)
            vals = {n: rng.choice(dom[n]) for n in names}
            ok, env = numgen.evaluate(spec, vals)
            if not ok:
                continue
            if diff:
                expr = spec.get("difficulty", {}).get(diff)
                try:
                    if expr is None or not numgen.safe_eval(expr, env):
                        continue
                except Exception:
                    continue
            out = {k: (int(env[k]) if env[k].is_Integer else float(env[k])) for k in names}
            if exclude and out in exclude:
                continue
            return out
        return None

    got = attempt(difficulty, 400)
    if got is None and difficulty:
        # 난이도에 맞는 후보가 드문 규칙(무작위 400번으로 못 찾음)은 난이도에 맞는 후보를 모두 세어 그중에서 고른다.
        # (예전에는 여기서 난이도를 조용히 무시하고 아무 숫자나 돌려줬다)
        allc = _all_candidates(spec, names)
        expr = spec.get("difficulty", {}).get(difficulty)
        pool_d = []
        for v, e in allc:
            try:
                if expr is not None and numgen.safe_eval(expr, e) and not (exclude and v in exclude):
                    pool_d.append(v)
            except Exception:
                pass
        if pool_d:
            return rng.choice(pool_d)
    got = got or attempt(None, 400)
    if got is not None:
        return got
    pool = numgen.candidates(spec, difficulty) or numgen.candidates(spec)   # 마지막 수단: 전체 열거
    rng.shuffle(pool)
    for env in pool:
        vals = {k: (int(env[k]) if env[k].is_Integer else float(env[k])) for k in spec["variables"]}
        if exclude and vals in exclude:
            continue
        return vals
    return None
