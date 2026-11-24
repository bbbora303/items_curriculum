"""수학 서술형 문항 JSON이 설계 규칙을 지키는지 검증한다.

사용법: python validate_item.py <item.json> [standards.json]
오류(errors)가 있으면 종료 코드 1, 경고(warnings)는 알리기만 한다.
규칙 번호는 docs/문항_스키마.md 의 '검증 규칙' 표와 같다.
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mathcheck import SafeEvalError, equal, safe_eval  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
MAX_SCORE = 30
MIN_SCORE = 4
LEVEL_COUNT = (2, 5)
MIN_LEVEL_SCORE = 1
MAX_STANDARDS = 3
COMPETENCIES = ["문제해결", "추론", "의사소통", "연결", "정보처리"]
CONTEXTS = ["지필평가", "수행평가"]
RESPONSE_TYPES = ["서술형", "논술형(제한)", "논술형(확장)"]
ANSWER_TYPES = ["값", "식", "서술", "그림", "표"]
ACHIEVEMENT = list("ABCDE")
UNIT_POLICY = ["평가함", "평가하지 않음"]
SUB_NO = re.compile(r"^\d+-\d+$")
VALUE_JUDGE_WORDS = ["성실", "노력", "의지가", "열심", "불성실", "성의"]


def _load(path):
    return json.load(open(os.path.join(ROOT, path), encoding="utf-8"))


def find_spec(numspec_dir, spec_id):
    """확정 명세(numspecs)에서 찾고, 없으면 같은 위치의 numspecs_draft(문항별 임시 명세)에서 찾는다."""
    draft_dir = os.path.join(os.path.dirname(os.path.abspath(numspec_dir)), "numspecs_draft")
    for d in (numspec_dir, draft_dir):
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.endswith(".json"):
                sp_ = json.load(open(os.path.join(d, fn), encoding="utf-8"))
                if sp_.get("id") == spec_id:
                    return sp_
    return None


def validate(item, standards, figure_ids, patterns, numspec_dir):
    errs, warns = [], []
    by_code = {s["code"]: s for s in standards}

    codes = item.get("standardCodes", [])
    if not 1 <= len(codes) <= MAX_STANDARDS:
        errs.append(f"M1 성취기준은 1~{MAX_STANDARDS}개여야 한다 (현재 {len(codes)})")
    for c in codes:
        s = by_code.get(c)
        if s is None:
            errs.append(f"M2 알 수 없는 성취기준 {c}")
        elif s.get("grade") and item.get("grade") and s["grade"] != item["grade"]:
            warns.append(f"W1 {c}는 중{s['grade']} 성취기준으로 표시돼 있다 (문항 학년 {item['grade']})")
    if item.get("assessmentContext") not in CONTEXTS:
        errs.append("M3 assessmentContext는 지필평가/수행평가 중 하나여야 한다")
    if item.get("responseType") not in RESPONSE_TYPES:
        errs.append(f"M3 responseType은 {RESPONSE_TYPES} 중 하나여야 한다")
    if item.get("taskPattern") not in patterns:
        errs.append(f"M4 알 수 없는 과제 패턴 {item.get('taskPattern')}")
    comps = item.get("competencies", [])
    if not 1 <= len(comps) <= 3 or any(c not in COMPETENCIES for c in comps):
        errs.append(f"M5 교과 역량은 {COMPETENCIES} 중 1~3개여야 한다")
    if item.get("unitPolicy") not in UNIT_POLICY:
        errs.append("M6 unitPolicy는 '평가함'/'평가하지 않음' 중 하나여야 한다")

    n = item.get("maxScore")
    if not isinstance(n, int) or not MIN_SCORE <= n <= MAX_SCORE:
        errs.append(f"M7 배점은 {MIN_SCORE}~{MAX_SCORE}의 정수여야 한다 (현재 {n})")
        return errs, warns

    subs = item.get("subQuestions", [])
    if not subs:
        errs.append("M8 소문항이 하나 이상 필요하다")
    if sum(q.get("maxScore", 0) for q in subs) != n:
        errs.append(f"M9 소문항 배점의 합({sum(q.get('maxScore', 0) for q in subs)})이 총점({n})과 같아야 한다")

    seen_nos = []
    cond_ids_all = set()
    for q in subs:
        no = q.get("no", "?")
        if not SUB_NO.match(str(no)):
            errs.append(f"M10 소문항 번호 형식은 '1-1'이어야 한다: {no}")
        if q.get("answerType") not in ANSWER_TYPES:
            errs.append(f"M10 {no}: answerType은 {ANSWER_TYPES} 중 하나여야 한다")
        for d in q.get("dependsOn", []):
            if d not in seen_nos:
                errs.append(f"M11 {no}: dependsOn {d}는 앞에 있는 소문항이어야 한다")
        for t in q.get("targetLevels", []):
            if t not in ACHIEVEMENT:
                errs.append(f"M12 {no}: targetLevels에 A~E 밖의 값 {t}")
        if not q.get("targetLevels"):
            warns.append(f"W2 {no}: 대상 성취수준(targetLevels)이 비어 있다")
        conds = {c["id"] for c in q.get("conditions", [])}
        if len(conds) != len(q.get("conditions", [])):
            errs.append(f"M13 {no}: 조건 id가 중복된다")
        cond_ids_all |= conds
        used_conds = set()
        # 품질 점검표(data/quality_rules_math.json)에서 코드가 확인할 수 있는 항목 - 경고만 한다
        _p = " ".join(l for l in str(q.get("prompt", "")).strip().split("\n") if not l.strip().startswith("|")).strip()   # 끝에 붙은 표 줄은 제외
        _p = re.sub(r"\s*\([^()]*\)\s*$", "", _p).strip()                                                           # 끝의 괄호 설명((단, …))은 제외
        if not re.search(r"(시오|하라|라)[.?\s]*$", _p):
            warns.append(f"W8 {no}: 발문이 반응 지시어(~시오)로 끝나지 않는다 (점검표 Q1)")
        if len(q.get("conditions", [])) > 3:
            warns.append(f"W9 {no}: 조건이 {len(q['conditions'])}개로 많다. 조건은 1~3개가 적당하다 (점검표 C3)")
        for c in q.get("conditions", []):
            if len(str(c.get("text", ""))) > 90:
                warns.append(f"W9 {no}: 조건 {c.get('id')}이(가) 길다. 요구 하나씩 나누는 것이 좋다 (점검표 C3)")
        for e in q.get("evaluationElements", []):
            for se in e.get("scoringElements", []):
                for lv_ in se.get("levels", []):
                    d = " ".join(lv_.get("descriptors", []))
                    if len(d) < 14 or any(w in d for w in VALUE_JUDGE_WORDS):
                        warns.append(f"W10 {no} '{se.get('text')}' {lv_.get('score')}점: 수준 서술이 너무 짧거나 학생의 태도를 판단하는 표현이다 (점검표 R1, R4)")

        elems = q.get("evaluationElements", [])
        if not elems:
            errs.append(f"M14 {no}: 평가 요소가 하나 이상 필요하다")
        sub_total = 0
        for e in elems:
            if not e.get("text", "").endswith("하기"):
                warns.append(f"W3 {no}: 평가 요소 '{e.get('text')}'는 '~하기' 형태가 아니다")
            for c in e.get("standardCodes", []):
                if c not in codes:
                    errs.append(f"M15 {no}: 평가 요소의 성취기준 {c}가 문항 성취기준에 없다")
            ses = e.get("scoringElements", [])
            if not ses:
                errs.append(f"M14 {no}: 평가 요소 '{e.get('text')}'에 채점 요소가 필요하다")
            for se in ses:
                top = se.get("maxScore")
                sub_total += top or 0
                lv = se.get("levels", [])
                scores = [x.get("score") for x in lv]
                if not LEVEL_COUNT[0] <= len(lv) <= LEVEL_COUNT[1]:
                    errs.append(f"M16 {no} '{se.get('text')}': 수준은 {LEVEL_COUNT[0]}~{LEVEL_COUNT[1]}개여야 한다 (현재 {len(lv)})")
                if scores and any(a <= b for a, b in zip(scores, scores[1:])):
                    errs.append(f"M17 {no} '{se.get('text')}': 수준 점수는 위에서 아래로 엄격히 감소해야 한다 {scores}")
                if scores and scores[0] != top:
                    errs.append(f"M18 {no} '{se.get('text')}': 최상 수준 점수({scores[0]})가 채점 요소 배점({top})과 달라야 하지 않다")
                if scores and scores[-1] != MIN_LEVEL_SCORE:
                    errs.append(f"M19 {no} '{se.get('text')}': 최하 수준은 {MIN_LEVEL_SCORE}점이어야 한다 (현재 {scores[-1]})")
                for x in lv:
                    if not x.get("descriptors"):
                        errs.append(f"M20 {no} '{se.get('text')}': 수준 {x.get('score')}점의 서술이 비어 있다")
                for r in se.get("conditionRefs", []):
                    if r not in conds:
                        errs.append(f"M21 {no}: conditionRefs {r}가 이 소문항의 조건에 없다")
                    used_conds.add(r)
        if sub_total != q.get("maxScore"):
            errs.append(f"M22 {no}: 채점 요소 배점의 합({sub_total})이 소문항 배점({q.get("maxScore")})과 같아야 한다")
        for c in conds - used_conds:
            errs.append(f"M23 {no}: 조건 {c}가 어떤 채점 요소의 수준 서술에도 연결되지 않았다")
        seen_nos.append(no)

    # 수치 바인딩 환경(변수와 파생값). 검산 식이 vars 없이 변수 이름을 쓸 때 사용한다
    bind_env = None
    nb0 = item.get("numberBinding")
    if nb0:
        spec0 = find_spec(numspec_dir, nb0["specId"])
        if spec0:
            from template import binding_env
            bind_env, _ = binding_env(spec0, nb0["values"])

    # 풀이 방법과 예시답안
    methods = {m["id"] for m in item.get("solutionMethods", [])}
    if not methods:
        errs.append("M24 solutionMethods가 하나 이상 필요하다")
    # 기본 풀이 / 확장 풀이(상위 학년 내용을 쓰는 풀이). tier가 없으면 기본 풀이로 본다(예전 문항)
    tiers = {m.get("id"): m.get("tier", "기본") for m in item.get("solutionMethods", [])}
    try:
        import scope_check as _sc
        tags = set(_sc.later_tags())
    except ImportError:
        tags = set()
    for m in item.get("solutionMethods", []):
        t = m.get("tier", "기본")
        if t not in ("기본", "확장"):
            errs.append(f"M30 풀이 방법 {m.get('id')}: tier는 '기본' 또는 '확장'이어야 한다({t})")
        elif t == "확장" and tags and m.get("extendedTag") not in tags:
            errs.append(f"M30 확장 풀이 {m.get('id')}: extendedTag는 '중2 · 경우의 수와 확률' 꼴의 목록 값이어야 한다({m.get('extendedTag')})")
        elif t == "기본" and m.get("extendedTag"):
            errs.append(f"M30 기본 풀이 {m.get('id')}에는 extendedTag를 붙이지 않는다")
    if item.get("solutionMethods") and tiers.get(item["solutionMethods"][0].get("id")) == "확장":
        errs.append("M30 첫 번째 풀이 방법은 기본 풀이여야 한다(확장 풀이는 뒤에 둔다)")
    answered = {}
    for a in item.get("modelAnswers", []):
        answered[a.get("subNo")] = a
    for q in subs:
        no = q.get("no")
        a = answered.get(no)
        if not a:
            errs.append(f"M25 {no}: 예시답안(modelAnswers)이 없다")
            continue
        ms = a.get("methods", [])
        for m in ms:
            if m.get("methodId") not in methods:
                errs.append(f"M24 {no}: methodId {m.get('methodId')}가 solutionMethods에 없다")
        if q.get("maxScore", 0) >= 3 and q.get("answerType") in ("값", "식", "서술") and len(ms) < 2 and not a.get("singleMethodReason"):
            warns.append(f"W4 {no}: 배점 3점 이상인데 풀이 방법이 1개뿐이다 (다양한 풀이 제공 원칙, 불가피하면 singleMethodReason 기재)")
        if q.get("maxScore", 0) >= 3 and ms and not any(tiers.get(m.get("methodId"), "기본") == "기본" for m in ms):
            errs.append(f"M30 {no}: 3점 이상 소문항에는 기본 풀이가 하나 이상 있어야 한다")
        # 코드 검산
        for m in ms:
            for chk in m.get("checks", []):
                try:
                    cenv = chk.get("vars") or bind_env
                    if cenv is None:
                        raise ValueError("vars도 numberBinding도 없어 변수 값을 알 수 없다")
                    val = safe_eval(chk["expr"], cenv)
                    exp = safe_eval(chk["expected"], cenv)
                    if not equal(val, exp):
                        errs.append(f"M26 {no} '{chk.get('label')}': 검산 불일치 ({chk['expr']} = {val}, 기대값 {exp})")
                except (SafeEvalError, ValueError, KeyError, TypeError, AttributeError) as ex:
                    errs.append(f"M26 {no} '{chk.get('label')}': 검산 식 오류 ({ex})")
    for no in answered:
        if no not in seen_nos:
            errs.append(f"M25 예시답안 {no}에 해당하는 소문항이 없다")

    # 교사 확인 사항
    tc = item.get("teacherChecks")
    if tc is None:
        errs.append("M27 teacherChecks(교사 확인 사항) 항목이 없다")
    elif not tc:
        warns.append("W5 교사 확인 사항이 비어 있다")
    else:
        for t in tc:
            for no in t.get("subNos", []):
                if no not in seen_nos:
                    errs.append(f"M27 교사 확인 사항 {t.get('id')}: 소문항 {no}가 없다")
    if not item.get("scoringNotes"):
        warns.append("W6 채점 시 유의점(scoringNotes)이 비어 있다")

    # 그림
    fig_types = {f["id"] for f in figure_ids}
    for f in item.get("stimulus", {}).get("figures", []):
        if f.get("type") not in fig_types:
            errs.append(f"M28 알 수 없는 그림 유형 {f.get('type')} (figure_types_math1.json 참고)")
        if not f.get("params"):
            errs.append(f"M28 그림 {f.get('id')}의 params가 비어 있다")
        elif f.get("type") in fig_types:
            from figures import RENDERERS, render
            from figures import figure_problems
            for msg in figure_problems(f):
                warns.append(f"W17 그림 {f.get('id')}: {msg}")
            if f["type"] in RENDERERS:
                try:
                    render(f)
                except Exception as ex:  # 렌더링 실패 = params 형식 오류
                    errs.append(f"M28 그림 {f.get('id')} 렌더링 실패: {ex}")
            else:
                warns.append(f"W7 그림 유형 {f['type']}는 아직 렌더러가 없어 그리지 못한다")

    # 중1 범위(교과서 분석 기반): 중2·3 주제나 중1 교과서가 다루지 않는 말 - 경고만 한다
    try:
        import scope_check
        for code, name, grade, where, snippet in scope_check.scan_item(item):
            if code == "W11":
                warns.append(f"W11 {where}: 중1 범위 밖으로 보이는 표현 '{name}'({grade}) - …{snippet}…")
            else:
                warns.append(f"W12 {where}: 교과서에서만 확인된 중1 범위 밖 표현 '{name}' - 교과서를 고르지 않아 참고로만 표시한다 - …{snippet}…")
    except ImportError:
        pass

    # 교과서 근거(선택한 교과서의 성질·공식·풀이 방법 목록에 근거가 없는 풀이 방법): 경고
    gm = item.get("generationMeta") or {}
    if gm.get("textbook") not in (None, "none") and gm.get("textbookBasisOffered"):
        for m in item.get("solutionMethods", []):
            if not m.get("textbookItems") and m.get("tier") != "확장":
                warns.append(f"W13 풀이 방법 {m.get('id')} '{str(m.get('name'))[:30]}': 선택한 교과서의 성질·공식·풀이 방법 목록에서 근거를 찾지 못했다 - 교과서가 다루는 내용만으로 풀 수 있는 방법인지 확인한다")

    # 교사가 고른 평가 요소가 채점기준에 들어갔는지(낱말 겹침 0.5 이상인 요소가 있어야 한다)
    chosen = (item.get("generationMeta") or {}).get("chosenElements") or []
    if chosen:
        have = [e.get("text", "") for q in item.get("subQuestions", []) for e in q.get("evaluationElements", [])]
        def _tk(x):
            return set(re.findall(r"[가-힣]{2,}", x))
        for c in chosen:
            ct = _tk(c)
            if ct and not any(len(ct & _tk(h)) / len(ct | _tk(h)) >= 0.5 for h in have):
                warns.append(f"W16 교사가 고른 평가 요소 '{c}'가 채점기준의 평가 요소에 들어 있지 않다")

    # 교과서 용어 대조(코드): 선택한 책에 없고 다른 책에만 있는 용어, 틀린 근거 번호
    try:
        import scope_check as _sc2
        for term, where in _sc2.term_leaks(item):
            warns.append(f"W14 {where}: 선택한 교과서에는 없고 다른 교과서에서 새로 정의하는 용어 '{term}'을 썼다 - 선택한 교과서의 용어로 바꿔 쓴다")
        for mid, why in _sc2.basis_mismatch(item):
            warns.append(f"W15 풀이 {mid}: 교과서 근거 표시가 맞지 않는다 - {why}")
    except ImportError:
        pass

    # 수치 명세 연결
    nb = item.get("numberBinding")
    if nb:
        spec_file = find_spec(numspec_dir, nb["specId"])
        if spec_file is None:
            errs.append(f"M29 수치 명세 {nb['specId']}를 찾을 수 없다")
        else:
            from numgen import evaluate
            import sympy as sp
            vals = {k: sp.Integer(v) if isinstance(v, int) else sp.Rational(str(v)) for k, v in nb["values"].items()}
            ok, _ = evaluate(spec_file, vals)
            if not ok:
                errs.append(f"M29 numberBinding 값 {nb['values']}이 수치 명세의 제약을 만족하지 않는다")
    return errs, warns


def main():
    item = json.load(open(sys.argv[1], encoding="utf-8"))
    std_path = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data", "standards.json")
    standards = json.load(open(std_path, encoding="utf-8"))["standards"]
    figs = _load("data/figure_types_math1.json")["figureTypes"]
    pats = {p["id"] for p in _load("data/task_patterns_math.json")["patterns"]}
    errs, warns = validate(item, standards, figs, pats, os.path.join(ROOT, "data", "numspecs"))
    for w in warns:
        print("경고:", w)
    for e in errs:
        print("오류:", e)
    print(f"오류 {len(errs)}개, 경고 {len(warns)}개")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
