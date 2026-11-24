"""조사 자동 처리 시험 (무료): python scripts/test_particles.py"""
import sys
import template as T

CASES = [
    ("{{a}}과 {{b}}의 합", {"a": 252, "b": 60}, "252와 60의 합"),
    ("{{a}}과 {{b}}의 합", {"a": 12, "b": 60}, "12와 60의 합"),
    ("{{a}}과 {{b}}의 합", {"a": 13, "b": 60}, "13과 60의 합"),
    ("{{a}}를 곱한다", {"a": 60}, "60을 곱한다"),
    ("{{a}}을 곱한다", {"a": 7}, "7을 곱한다"),
    ("{{a}}을 곱한다", {"a": 9}, "9를 곱한다"),
    ("답은 {{a}}이다", {"a": 9}, "답은 9이다"),                   # 이다는 건드리지 않는다
    ("{{a}}이 아니다", {"a": 9}, "9가 아니다"),
    ("{{a}}가 아니다", {"a": 10}, "10이 아니다"),
    ("{{a}}으로 나눈다", {"a": 7}, "7로 나눈다"),                    # ㄹ 받침은 '로'
    ("{{a}}로 나눈다", {"a": 3}, "3으로 나눈다"),
    ("{{a}}로 나눈다", {"a": 4}, "4로 나눈다"),
    ("${{a}}$을 쓴다", {"a": 5}, "$5$를 쓴다"),                       # 수식 닫는 달러 뒤 조사
    ("{{a}}이상이다", {"a": 4}, "4이상이다"),                          # '이상'은 조사가 아님
    ("{{a}}는데", {"a": 3}, "3는데"),                                 # 낱말의 앞부분이면 그대로
    ("{{a}}은 정수이다", {"a": -3}, "-3은 정수이다"),
    ("{{a}}는 분수", {"a": "1/3"}, "1/3은 분수") ,
]
bad = 0
for tpl, env, want in CASES:
    got = T.fill_string(tpl, {k: v for k, v in env.items()}) if not isinstance(list(env.values())[0], str) else None
    if got is None:
        import sympy as sp
        got = T.fill_string(tpl, {"a": sp.Rational(1, 3)})
    ok = got == want
    bad += not ok
    print(("통과" if ok else "실패"), "-", tpl, env, "->", got, "" if ok else f"(기대 {want})")
print(f"\n{len(CASES) - bad}/{len(CASES)} 통과")
sys.exit(1 if bad else 0)
