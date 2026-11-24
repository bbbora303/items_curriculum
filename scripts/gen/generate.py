"""수학 서술형 문항 세트 생성 파이프라인 (프로토타입 v2).

사용 예:
  python generate.py --standard 9수03-06 --max-score 10 --difficulty medium --seed 1 --label p1
  python generate.py --standard 9수02-04 --pattern expression_then_value --auto-approve-spec --label p2
  python generate.py --standard 9수03-06 --list-patterns

단계: G0(평가 요소 후보) -> [자동 확정] -> G1(설계) -> [수치 명세 확보: 있으면 사용, 없으면 GN이 초안 -> 교사 확정]
      -> [코드] 숫자 선택 -> G2(상황·그림, 자리표시자) -> G3(소문항·채점·예시답안, 자리표시자)
      -> [코드] 숫자 채우기·검증 순환(오류는 G3에 되먹임) -> 수치 변경 시험 -> AI 점검(심각하면 1회 자동 수정) -> 저장
결정 사항(2026-10-20): 수치만 바꾸기는 템플릿 방식, 교사가 패턴 선택 가능(기본 자동), 명세 없으면 AI 초안+교사 확정,
난이도 3단계(5단계는 고도화). 교사 확정 단계는 프로토타입에서 CLI 플래그(--auto-approve-spec 등)로 대신한다.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from common import DEFAULT_MODEL, ROOT, Usage, client, extract_json, text_of  # noqa: E402
import validate_item as V  # noqa: E402
from figures import RENDERERS, render, figure_problems  # noqa: E402
import numgen  # noqa: E402
import template as T  # noqa: E402
import datatable  # noqa: E402
import guides  # noqa: E402
import scope_check  # noqa: E402
import tiering  # noqa: E402

DATA = ROOT / "data"
COMPETENCIES = V.COMPETENCIES
SAFE_FUNCS = "sqrt, abs, floor, ceil, gcd, lcm, min, max, denom, numer, coef_pi, is_int, is_square, simplify, 상수 pi, 연산 + - * / ** %, 비교, and/or/not, in (…)"

FIG_EXAMPLES = {   # 그림 params 형식 (렌더러가 읽는 키)
    "circle_sector": {"radius": 6, "angle": 120, "labels": ["O", "A", "B"], "show": ["radius", "angle"], "unit": "cm"},
    "number_line": {"min": -5, "max": 5, "step": 1, "points": {"A": -3, "B": 2}},
    "coordinate_plane": {"xmin": -1, "xmax": 6, "ymin": -1, "ymax": 6, "points": {"A": [2, 4]}, "lines": [{"a": 2, "b": 0, "label": "y=2x"}], "hyperbolas": [{"k": 6}]},
    "polygon_labeled": {"sides": {"AB": 3, "BC": 4, "CA": 5}, "show_sides": True, "side_labels": {"AB": "3 cm", "BC": "4 cm", "CA": "5 cm"}, "right_angle": "B",
                        "또는 임의 다각형": {"vertices": ["A", "B", "C", "D"], "coords": [[0, 0], [4, 0], [4, 3], [0, 3]], "angle_labels": {"A": "90°"}}},
    "angle_diagram": {"vertex": "O", "rays": [{"name": "A", "deg": 0}, {"name": "B", "deg": 50}], "value": 50},
    "parallel_transversal": {"angle": 65, "angle_labels": {"a": "∠a", "b": "∠b", "c": "∠c", "d": "∠d", "e": "∠e", "f": "∠f", "g": "∠g", "h": "∠h"}},
    "histogram": {"classes": [[3, 4], [4, 5], [5, 6]], "freqs": [5, 4, 3], "polygon": False, "bars": True, "xlabel": "가격(천 원)", "hide_freq_idx": []},
}

NOTES_LIBRARY = [
    "수와 식으로 표현한 문제해결 과정이 수학적으로 논리적이면 예시답안과 달라도 정답으로 인정한다.",
    "성취기준이 값을 구하는 것이므로 단위 표기는 평가하지 않는다.",
    "앞 소문항의 값이 틀렸더라도 그 값을 바탕으로 이후 계산·판단이 논리적이면 해당 수준 점수를 부여한다.",
    "표현 방식이 달라도 이유가 충분히 설명되었으면 정답으로 인정한다.",
    "오류가 있어도 근거에 바탕을 둔 시도가 보이면 부분 점수를 부여한다.",
    "근호·분수의 꼴을 정리하지 않아도 풀이 과정이 맞으면 정답으로 인정한다.",
    "대략 비슷한 위치에 점을 찍거나 그래프의 모양이 크게 벗어나지 않으면 정답으로 인정한다.",
]
TEACHER_CHECK_LIBRARY = [
    "π 등을 근삿값으로 계산한 답을 인정할지 사전에 협의한다.",
    "그래프에서 점 두 개만 찍어 연결한 경우의 배점을 사전에 협의한다.",
    "좌표평면에서 점이 눈금에서 살짝 벗어난 경우의 처리를 협의한다.",
    "한 문항에서 두 대상(학생 A, B 등)을 구분해 답했는지 확인한다.",
    "계산 실수와 개념 이해 오류를 구분해 채점한다.",
    "열린 과제(새 방법 제시 등)에서 다양한 답이 오류 없는지 확인한다.",
    "수학 기호와 용어를 정확히 사용했는지 확인한다.",
    "학교 상황에 맞게 배점을 조정하고 비율로 환산해 사용할 수 있다.",
]

SYSTEM = """당신은 중학교 수학 교사의 서술형·논술형 평가 문항 출제를 돕는 도구입니다.
공통 규칙:
- 출력은 지시한 JSON 하나만 쓴다. 설명 문장, 코드 블록 표시, 주석을 붙이지 않는다.
- 수식은 LaTeX를 $...$ 로 감싸서 쓴다(JSON 문자열 안에서 역슬래시는 두 번 쓴다: \\\\frac).
- 2022 개정 교육과정 중학교 1학년 수준만 쓴다. 성취기준 해설이 다루지 않는다고 한 내용은 쓰지 않는다.
- 실존 인물·기관·상표·출처가 필요한 통계는 쓰지 않는다. 가상의 인물은 이름 대신 '지민', '현우' 같은 흔한 이름을 쓴다.
- 채점기준에 감점 규칙(몇 점 감점)을 쓰지 않는다. 오류의 정도는 수준 서술로 표현한다.
"""


def load_json(rel):
    return json.load(open(DATA / rel, encoding="utf-8"))


def js(x):
    return json.dumps(x, ensure_ascii=False, indent=1)


TEACHER_ELEMENTS = []        # 교사가 고른 평가 요소(글자 그대로 채점기준에 들어가야 한다). main()에서 지정
NL_ = chr(10)
MAX_TOKENS_CAP = 100000      # 모델의 출력 상한(12.8만)보다 낮게 둔 안전 상한. 스트리밍이라 크게 잡아도 요청 시간 초과가 나지 않는다
G3_MAX_TOKENS = 48000       # 로그 103회 기준 G3 출력 중앙값 1.6만, 90%가 2.6만 이하, 최대 3.2만(한도)에서 잘림 -> 1.5배로 여유(잘리면 자동으로 두 배까지 재시도)
RAW_DIR = None   # main()에서 출력 폴더로 지정: JSON 파싱 실패 시 응답 원문을 저장한다


def call(cl, usage, stage, user, model, max_tokens=14000, system=SYSTEM, bump=True):
    last_err = None
    for attempt in range(2):
        prompt = user if attempt == 0 else (
            user + f"\n\n[주의] 직전 출력이 JSON 문법 오류였다({last_err}). 문자열 안의 따옴표·역슬래시·줄바꿈을 모두 이스케이프한 올바른 JSON 객체 하나만 출력한다.")
        t0 = time.time()
        # 스트리밍으로 받는다: 출력 한도(생각 토큰 포함)를 2만 넘게 잡으면 SDK가 비스트리밍 요청을 거부한다
        with cl.messages.stream(model=model, max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": prompt}]) as stream:
            resp = stream.get_final_message()
        usage.add(stage + ("" if attempt == 0 else "(재시도)"), resp)
        txt = text_of(resp)
        print(f"  [{stage}] {time.time()-t0:.0f}s, 입력 {resp.usage.input_tokens} 출력 {resp.usage.output_tokens}, stop={resp.stop_reason}", flush=True)
        if resp.stop_reason == "max_tokens":
            if RAW_DIR is not None:
                (RAW_DIR / f"raw_{stage}_truncated.txt").write_text(txt, encoding="utf-8")
            if bump and max_tokens < MAX_TOKENS_CAP:           # 생각 토큰이 길어져 잘린 경우: 한도를 두 배(상한까지)로 올려 한 번 더 시도한다
                bigger = min(MAX_TOKENS_CAP, max_tokens * 2)
                print(f"    출력이 {max_tokens}토큰에서 잘려 한도를 {bigger}로 올려 다시 시도한다", flush=True)
                return call(cl, usage, stage + "(한도 상향)", user, model, bigger, system, bump=False)
            raise RuntimeError(f"{stage}: 출력이 max_tokens({max_tokens})에서 잘렸습니다")
        try:
            return extract_json(txt)
        except Exception as e:
            last_err = str(e)[:120]
            if RAW_DIR is not None:
                (RAW_DIR / f"raw_{stage}_{attempt}.txt").write_text(txt, encoding="utf-8")
            print(f"    JSON 파싱 실패({last_err}) — 원문 저장, {'재시도' if attempt == 0 else '중단'}", flush=True)
    raise RuntimeError(f"{stage}: JSON 파싱 실패 ({last_err})")


def with_feedback(user, feedback, prev, what="시도"):
    if not feedback:
        return user
    return f"{user}\n\n[이전 {what}의 문제 - 고칠 것]\n{js(feedback)}\n이전 출력:\n{js(prev)}\n문제만 고쳐서 전체 JSON을 다시 출력한다."


# ================================================================ G0
def g0(cl, usage, model, std, book=None):
    gb = scope_check.goals_block(std['code'], book)
    user = f"""성취기준 [{std['code']}] {std['text']}
영역: {std['domain']} / 소영역: {std.get('subunit')}
성취기준 해설·제한 사항: {std.get('commentary') or '(없음)'}
성취수준(A~E): {js(std['achievementLevels'])}
{gb}

위 성취기준으로 서술형 문항을 만들려고 합니다. 평가 요소 후보를 만드세요.
- 평가 요소는 '~하기'로 끝나는 짧은 구(예: '부채꼴의 호의 길이 구하기')이며, 성취기준 범위를 넘지 않는다.
- 서로 겹치지 않는 후보 4개. 지식을 확인하는 요소, 과정을 설명하는 요소, 판단·적용하는 요소가 고르게 섞이게 한다.
- 교과 역량 후보는 {COMPETENCIES} 중에서 2~3개.
출력 JSON: {{"evaluationElementCandidates":[{{"text":"...하기","kind":"지식|과정|판단","levelBasis":"근거가 되는 성취수준 문장 요약","fromGoal":"근거로 삼은 교과서 학습 목표 문장(없으면 빈 문자열)"}}],"competencyCandidates":["추론","문제해결"]}}"""
    return call(cl, usage, "G0", user, model, 6000)


# ================================================================ G1
def pattern_pool(std_code):
    pats = load_json("task_patterns_math.json")["patterns"]
    out = []
    for p in pats:
        if "level" not in p or std_code in p.get("standardsExamples", []):
            out.append({k: p[k] for k in ("id", "name", "structure", "subQuestions", "figures", "numberGen") if k in p})
    return out


def find_numspec(std_code):
    d = DATA / "numspecs"
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".json"):
            s = json.load(open(d / fn, encoding="utf-8"))
            if std_code in s.get("standards", []) and s.get("status") != "retired":
                return s
    return None


def g1(cl, usage, model, args, std, elements, comps, patterns, spec, feedback=None, prev=None):
    figs = list(RENDERERS)
    spec_txt = (js({'id': spec['id'], 'description': spec['description'], 'variables': spec['variables'], 'derived': list(spec['derived']), 'taskPatterns': spec.get('taskPatterns')})
                if spec else "없음 - 설계가 끝나면 코드·AI가 이 설계에 맞는 수치 명세를 따로 만든다(숫자를 직접 정하지 않는다)")
    forced = f"- 과제 패턴은 반드시 {args.pattern} 를 쓴다.\n" if args.pattern != "auto" else ""
    themes = scope_check.pick_themes(std['code'], args.textbook, args.seed) if args.textbook not in (None, 'none') else []
    theme_rule = (f"- **소재**: 선택한 교과서가 이 단원에서 쓰는 소재 후보는 {js(themes)} 이다. 과제 패턴과 소문항 구성은 이 중 하나의 소재 안에서 자연스럽게 성립하는 것으로 정하고, theme에 그 소재를 쓴다. "
                  "기존 수치 명세가 있어 그 명세가 가정하는 상황(요금, 도형 등)이 어느 후보와도 맞지 않으면 theme을 빈 문자열로 하고 themeFit에 이유를 쓴다. 소재 때문에 수학 내용이나 난이도를 바꾸지 않는다.\n") if themes else ""
    user = f"""성취기준 [{std['code']}] {std['text']} (해설: {std.get('commentary') or '없음'})
확정된 평가 요소: {js([e['text'] for e in elements])}
확정된 교과 역량: {comps}
총점 {args.max_score}점 / 응답 유형 {args.response_type} / 난이도 {args.difficulty}(쉬움·보통·어려움) / 평가 맥락 {args.context}

사용할 수 있는 과제 패턴 목록:
{js(patterns)}

기존 수치 명세: {spec_txt}
그릴 수 있는 그림 유형: {figs}

문항 세트를 설계하세요. 규칙:
- 과제 패턴 하나를 고른다(목록의 id).
- 소문항은 2~4개. 번호는 '1-1','1-2','2-1' 형식. 쉬운 계산 -> 설명·과정 서술 -> 판단·논술 순서로 난이도를 올린다. 판단·논술·일반화 소문항의 배점은 단순 계산 소문항보다 같거나 크게 하되, 배점 분배는 과제에 맞게 다양하게 하고 매번 같은 비율(예: 2·3·5)로 나누지 않는다(실제 문항의 배점 구성 예: 4·2·4, 4·4·8·4, 2·4·4, 3·3·5).
- 소문항 배점(maxScore)의 합이 정확히 {args.max_score}점이어야 한다. 소문항 배점은 2점 이상.
- 소문항마다 겨냥하는 성취수준(targetLevels, A~E 중)을 정한다: 쉬운 소문항은 D·E·C, 마지막 판단 소문항은 A·B.
- 앞 소문항의 결과를 뒤 소문항에서 쓰면 dependsOn에 앞 소문항 번호를 넣는다.
- answerType은 값/식/서술/그림/표 중 하나.
- 확정된 평가 요소 모두가 어느 소문항에서 평가되도록 elementIndexes(0부터)에 연결한다.
- 그림이 꼭 필요한 경우에만 figuresNeeded에 유형을 쓴다(없으면 빈 배열). 기존 수치 명세가 있고 패턴에 맞으면 useNumSpec을 true로 한다.
- 배점 3점 이상 소문항은 풀이 방법을 2가지 이상 인정할 수 있게 solutionMethodsPlan에 방법 이름을 2개 쓴다.
- needsDataset: 표·자료 목록(점수 20개 같은 자료, 도수분포표 전체 등)이 문항의 핵심이면 true, 숫자 몇 개로 정해지는 문제면 false.
{forced}{theme_rule}- 소문항 번호는 반드시 '1-1', '1-2', '2-1' 같은 형식이고, 빈 소문항이나 자리표시 항목을 만들지 않는다.
- intent(출제 의도)는 교사가 읽는 문장이다. 소문항별 겨냥 성취수준과 평가하려는 능력만 쓰고, 코드·AI·수치 명세 같은 도구 이야기와 정답 값은 쓰지 않는다.
출력 JSON: {{"taskPattern":"id","rationale":"한 문장","theme":"소재 후보 중 하나 또는 빈 문자열","themeFit":"소재를 고른 이유 한 문장","useNumSpec":true,"needsDataset":false,"intent":"출제 의도","subQuestions":[{{"no":"1-1","role":"...","answerType":"값","maxScore":4,"targetLevels":["D","E"],"dependsOn":[],"elementIndexes":[0]}}],"figuresNeeded":["circle_sector"],"solutionMethodsPlan":[{{"id":"M1","name":"공식 이용"}},{{"id":"M2","name":"비례식 이용"}}]}}"""
    return call(cl, usage, "G1" + ("-재시도" if feedback else ""), with_feedback(user, feedback, prev, "설계"), model, 12000)


def design_errors(design, total, pattern_ids):
    errs = []
    subs = design.get("subQuestions", [])
    if design.get("taskPattern") not in pattern_ids:
        errs.append(f"taskPattern {design.get('taskPattern')}은(는) 목록에 없다")
    if not 2 <= len(subs) <= 4:
        errs.append(f"소문항은 2~4개여야 한다 (현재 {len(subs)})")
    if sum(q.get("maxScore", 0) for q in subs) != total:
        errs.append(f"소문항 배점의 합이 {total}점이어야 한다 (현재 {sum(q.get('maxScore', 0) for q in subs)})")
    for q in subs:
        if not V.SUB_NO.match(str(q.get("no"))):
            errs.append(f"소문항 번호 형식 오류: {q.get('no')}")
        if q.get("maxScore", 0) < 2:
            errs.append(f"{q.get('no')}: 소문항 배점은 2점 이상이어야 한다")
    return errs


# ================================================================ GN (수치 명세 초안)
def spec_errors(spec):
    """AI가 만든 명세를 코드로 시험한다. 오류 목록을 돌려준다."""
    errs = []
    for k in ("id", "description", "variables", "derived", "constraints", "difficulty"):
        if k not in spec:
            errs.append(f"키 {k}가 없다")
    if errs:
        return errs
    try:
        dom = numgen.domain(spec)
        total = 1
        for n, vs in dom.items():
            total *= len(vs)
        if total > 20000:
            errs.append(f"변수 조합이 너무 많다({total}). 범위를 줄여라(2만 이하)")
            return errs
        cands = numgen.candidates(spec)
    except Exception as ex:
        return [f"명세 계산 오류: {ex}"]
    if len(cands) < 6:
        errs.append(f"제약을 만족하는 후보가 {len(cands)}개뿐이다(6개 이상 필요). 제약을 완화하거나 변수 범위를 넓혀라")
        return errs
    for lv in ("easy", "medium", "hard"):
        if lv not in spec["difficulty"]:
            errs.append(f"difficulty에 {lv}가 없다")
            continue
        try:
            n = len(numgen.candidates(spec, lv))
        except Exception as ex:
            errs.append(f"difficulty.{lv} 식 오류: {ex}")
            continue
        if n < 1:
            errs.append(f"difficulty.{lv} 조건을 만족하는 후보가 없다(현재 전체 후보 {len(cands)}개)")
    return errs


def gn(cl, usage, model, std, design, feedback=None, prev=None):
    example = load_json("numspecs/sector_arc_area.json")
    dataset_mode = bool(design.get("needsDataset")) or std.get("domain") == "자료와 가능성"
    ds_example = ""
    if dataset_mode:
        ex2 = load_json("examples/numspec_dataset_example.json")
        ds_example = NL_ + "자료(통계) 문항 형식 예: " + js({k: ex2[k] for k in ("id", "description", "variables", "derived", "constraints", "difficulty")})
    example = {k: example[k] for k in ("id", "description", "variables", "derived", "constraints", "difficulty")}
    user = f"""성취기준 [{std['code']}] {std['text']}
확정된 문항 설계(소문항 골격): {js({k: design.get(k) for k in ('taskPattern','intent','subQuestions')})}

이 설계의 문항에 쓸 '수치 구조 명세'를 만드세요. 코드가 이 명세에서 숫자 조합 후보를 고르고, 문항 본문과 예시답안은 그 숫자로 채워집니다.
- variables: 문항의 숫자 변수와 후보 값. {{"r":{{"range":[3,12]}}, "theta":{{"values":[30,60,90]}}}} 처럼 range(+step) 또는 values.
- derived: 정답·중간값 공식(위에서 아래로 순서대로 계산). 소문항에서 구하는 값과 비교·판단에 필요한 값을 모두 포함한다.
- constraints: 모두 참이어야 하는 조건. 답이 깔끔하게 떨어지게 한다(정수 해, 단순한 분수, π 계수가 정수 등). 학생이 중1 수준에서 암산·손계산이 가능해야 한다. 서로 같은 값이 되어 문제가 무의미해지는 경우를 제외한다.
- difficulty: easy/medium/hard 각각 추가 조건(식). 세 수준 모두 후보가 1개 이상 남아야 한다.
- 식에는 {SAFE_FUNCS} 만 쓴다. 파이썬 문법이며 소수는 쓰지 않고 분수(1/3)로 쓴다.
- 변수 조합은 2만 개 이하, 조건을 만족하는 후보는 6개 이상.
- description은 한 문장.
- plainSummary는 수학 교사가 읽고 확인할 수 있는 쉬운 말 설명이다. **최대 3문장, 전체 150자 이내**로 짧게 쓴다. 1문장: 바꾸는 숫자(예: "한 변의 길이와 개수"). 2문장: 답이 깔끔하게 떨어지도록 거는 조건 한 가지(풀이 과정을 길게 설명하지 않는다). 3문장: 쉬움과 어려움의 차이. 수식·변수 기호·문항 풀이 내용은 쓰지 않는다.
{DATASET_GN_RULES if dataset_mode else "- 문항에 표·자료 목록 전체(점수 20개, 줄기와 잎 그림 등)가 필요하면 지원하지 않는다: supported를 false로 하고 reason에 이유를 쓴다."}
형식 예(내용은 복사하지 말고 형식만): {js(example)}{ds_example}
출력 JSON: {{"supported":true,"reason":"","plainSummary":"...","spec":{{"id":"...","description":"...","variables":{{}},"derived":{{}},"constraints":[],"difficulty":{{"easy":"...","medium":"...","hard":"..."}}}}}}"""
    return call(cl, usage, "GN" + ("-재시도" if feedback else ""), with_feedback(user, feedback, prev, "명세"), model, 20000)


def obtain_spec(cl, usage, args, std, design):
    """수치 명세를 확보한다. (spec, status) status: existing | approved | pending | unsupported"""
    spec_id = f"m1_{std['code'].replace('수', 's')}_{design['taskPattern']}_v1"
    path_conf = DATA / "numspecs" / f"{spec_id}.json"
    if path_conf.exists():
        return json.load(open(path_conf, encoding="utf-8")), "existing"
    draft_path0 = DATA / "numspecs_draft" / f"{spec_id}.json"
    if args.approve_spec == spec_id and draft_path0.exists():
        spec = json.load(open(draft_path0, encoding="utf-8"))
        spec["status"] = "confirmed"
        spec["approvedBy"] = "teacher"
        spec["approvedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
        path_conf.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  교사가 확인한 수치 명세 초안을 확정해 저장했다:", path_conf.name)
        return spec, "approved"
    out = None
    fb = prev = None
    for _ in range(3):
        out = gn(cl, usage, args.model, std, design, fb, prev)
        if not out.get("supported", True):
            print("  수치 명세를 만들 수 없는 문항:", out.get("reason"))
            return None, "unsupported"
        spec = out["spec"]
        spec["id"] = spec_id
        errs = spec_errors(spec)
        if not errs:
            break
        print("  명세 오류:", errs)
        fb, prev = errs, out
    else:
        print("  수치 명세 초안이 검증을 통과하지 못해 템플릿 없이 진행한다")
        return None, "unsupported"
    spec["standards"] = [std["code"]]
    spec["taskPatterns"] = [design["taskPattern"]]
    spec["status"] = "draft"
    spec["plainSummary"] = out.get("plainSummary", "")
    (DATA / "numspecs_draft").mkdir(exist_ok=True)
    if args.provisional and not (args.auto_approve_spec or args.approve_spec == spec_id):
        # 문항 아래에서 교사가 고치고 확정한다: 이 문항 전용 임시 명세로 바로 진행
        spec["baseId"] = spec_id
        spec["id"] = f"{spec_id}__{args.label}"
        spec["status"] = "provisional"
        (DATA / "numspecs_draft" / f"{spec['id']}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
        print("  수치 명세 초안을 이 문항 전용 임시 규칙으로 쓴다(문항 아래에서 고치고 확정할 수 있다):", spec["id"])
        return spec, "provisional"
    draft_path = DATA / "numspecs_draft" / f"{spec_id}.json"
    cands = numgen.candidates(spec)
    spec["candidateCount"] = len(cands)
    spec["samples"] = [{k: (int(e[k]) if e[k].is_Integer else str(e[k])) for k in spec["variables"]} for e in cands[:4]]
    draft_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n  ── 수치 명세 초안: 교사 확인 필요 ──")
    print("  ", spec["plainSummary"])
    print(f"   후보 {len(cands)}개, 예시:")
    for env in cands[:3]:
        print("    ", {k: int(env[k]) if env[k].is_Integer else str(env[k]) for k in spec["variables"]})
    approved = args.auto_approve_spec or args.approve_spec == spec_id
    if not approved:
        print(f"\n  확인 후 이 명세로 진행하려면 --approve-spec {spec_id} 를 붙여 다시 실행하세요. (초안: {draft_path})")
        return spec, "pending"
    spec["status"] = "confirmed"
    spec["approvedBy"] = "test(auto)" if args.auto_approve_spec else "teacher"
    spec["approvedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    path_conf.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    print("   명세를 확정해 저장했다:", path_conf.name)
    return spec, "approved"


# ================================================================ G2
def fig_errors(stimulus):
    errs = []
    for f in stimulus.get("figures", []):
        if f.get("type") not in RENDERERS:
            errs.append(f"그림 {f.get('id')}: 지원하지 않는 유형 {f.get('type')} (지원: {list(RENDERERS)})")
            continue
        for msg in figure_problems(f):
            errs.append(f"그림 {f.get('id')} ({f.get('type')}): {msg}")
        try:
            render(f)
        except Exception as ex:
            errs.append(f"그림 {f.get('id')} ({f.get('type')}): params를 읽지 못함 - 키 {ex} 누락 또는 형식 오류. params 바로 안에 해당 유형의 키를 써야 한다(유형 이름으로 한 번 더 감싸지 말 것)")
    return errs


DATASET_G2_RULE = """- **이 문항의 자료는 수치 명세의 data(코드가 만든 자료)이다. 표의 숫자를 직접 쓰지 말고 tables의 각 표에 autoTable을 쓴다**(코드가 자료로 표를 그린다):
  {\"id\":\"T1\",\"caption\":\"[표 1] 학생 {{n}}명의 점수(점)\",\"autoTable\":{\"kind\":\"raw_row\",\"data\":\"data\",\"itemLabel\":\"학생\",\"valueLabel\":\"점수(점)\"}}  (자료를 그대로 나열)
  kind 종류: raw_row(자료 나열), stem_leaf(줄기와 잎 그림, stemUnit 기본 10), freq_table(도수분포표: start·width·count, unit 예 \"명\"), rel_freq_table(도수와 상대도수).
  start 등 숫자는 \"{{lo}}\" 같은 자리표시자나 정수로 쓴다. caption의 숫자도 자리표시자로 쓴다. 본문에 자료 값을 나열해야 하면 {{sorted(data)}}(오름차순)나 {{data}}를 쓴다.
  표가 문항의 풀이 대상(예: 줄기와 잎 그림을 보고 구하기)이면 제시문 표에 자료를 주고, 도수분포표 같은 정리된 표는 소문항에서 학생이 만들게 하려면 제시문에 넣지 않는다."""


def spec_brief(spec, env):
    """프롬프트용: 변수·파생값 이름과 지금 선택된 예시 값."""
    vars_ = {k: {"meaning": v.get("meaning", ""), "unit": v.get("unit", ""), "now": str(env[k])} for k, v in spec["variables"].items()}
    derived = {k: {"formula": expr, "now": str(env[k])} for k, expr in spec["derived"].items()}
    return js({"variables": vars_, "derived": derived})


DATASET_GN_RULES = """- **이 문항은 표·자료가 핵심이다. 자료는 '자료 묶음 번호'로 코드가 만든다**(자료를 직접 쓰지 않는다):
  · variables에 s(자료 묶음 번호, range [1, 300], meaning '자료 묶음 번호(바꾸면 표의 자료가 달라짐)'), n(자료 개수), lo·hi(값의 범위)를 둔다. n, lo, hi는 values로 하나만 두어도 된다.
  · derived의 첫 줄: \"data\": \"dataset(s, n, lo, hi)\" (같은 s면 항상 같은 자료). 이후 파생값에 자료 함수를 쓴다.
  · 자료 함수(자료 data에 적용): len, sum, sorted, mean, median, mode(최빈값; 여러 개면 가장 작은 값), n_modes(최빈값의 개수), mode_freq(최빈값의 도수), count(data, x), count_between(data, lo, hi)(lo 이상 hi 미만의 개수=계급의 도수), rel_freq(data, lo, hi)(상대도수), data_range, distinct(서로 다른 값의 개수), item(data, i)(0번부터), min(data), max(data).
  · 답이 깔끔하도록 constraints를 건다: 최빈값이 하나(n_modes(data) == 1), 중앙값이 정수(is_int(median(data)))나 n을 홀수로, 모든 계급에 도수가 있게 count_between(...) >= 1, distinct(data) >= 10, 최솟값·최댓값이 범위 안. 상대도수가 깔끔하도록 n은 10, 20, 25, 40, 50 중에서 고른다.
  · 난이도(difficulty)는 자료의 흩어진 정도(data_range)나 최빈값의 도수 같은 식으로 나눈다.
  · 조합은 s(최대 300) x 나머지 변수의 값 수이므로 2만 이하로 유지한다."""
NL_ = chr(10)


TEMPLATE_RULES = """[자리표시자 규칙 - 매우 중요]
- 이 문항의 숫자는 코드가 바꿔 끼울 수 있어야 한다. 변수·파생값에서 나오는 모든 숫자는 {{식}} 자리표시자로 쓴다.
  예: 반지름이 {{r}} cm / 호의 길이는 ${{arc|latex}}$ cm / 2배한 반지름은 {{2*r}} / 비는 {{area2/area}}배 / 분수 {{theta/360}}
- 식 안에는 위 변수·파생값 이름과 안전한 식만 쓴다. $...$ 수식 안의 숫자도 자리표시자로 쓴다(예: ${{r}}^2$).
- {{식|latex}} 는 π나 분수를 LaTeX로 쓸 때(예: 8\\\\pi, \\\\frac{1}{3}), 그냥 {{식}} 은 정수·분수를 글자로 쓸 때.
- 그림 params의 숫자도 "{{r}}" 처럼 문자열 전체를 자리표시자 하나로 쓰면 숫자 값으로 채워진다. 단위가 붙는 라벨은 "{{r}} cm".
- 자리표시자가 아닌 '고정 숫자'로 써도 되는 것: 문제 구조에 속하는 상수(2배, 중심각 360°, 3점 같은 배점, 소문항 번호). 변수나 계산 결과로 바뀌는 숫자를 고정 숫자로 쓰면 숫자를 바꿀 때 틀린다.
- 자리표시자 {{...}} 바로 옆에 LaTeX 중괄호를 붙이지 않는다. 지수는 ^{{a}}나 ^{{{a}}}처럼 쓰지 말고 ^{ {{a}} } 처럼 중괄호 안쪽에 공백을 둔다(겹치면 채우기가 실패한다).
- 문장이 숫자에 따라 어색해지지 않게 쓴다(예: '1시간'과 '2시간' 모두 자연스러운 표현)."""


def g2(cl, usage, model, design, spec, env, std, feedback=None, prev=None, book=None, seed=1):
    dataset_spec = bool(spec) and any("dataset(" in str(e) for e in spec.get("derived", {}).values())
    figs = [{"id": "F1", "type": t, "params": FIG_EXAMPLES[t], "caption": "..."} for t in design.get("figuresNeeded", []) if t in FIG_EXAMPLES]
    if spec:
        nb = f"수치 명세(변수와 파생값, now는 지금 선택된 값):\n{spec_brief(spec, env)}\n{TEMPLATE_RULES}"
    else:
        nb = "수치 명세가 없으므로 숫자를 직접 정하되, 정답이 깔끔하게 떨어지고 중1 수준의 계산이 되게 한다. 정한 숫자를 numbers에 모두 적는다."
    user = f"""성취기준 [{std['code']}] {std['text']}
문항 설계: {js({k: design[k] for k in ('taskPattern','intent','subQuestions')})}
{nb}
{scope_check.prompt_block(std['code'], book, compact_other=False)}
{scope_check.theme_block(std['code'], book, seed, design.get('theme'), no_fit=bool(spec) and not design.get('theme') and bool(design.get('themeFit')))}
그림 객체 형식(type과 params 키 이름을 그대로 지킬 것, params 안에 유형 이름을 다시 쓰지 않는다): {js(figs) if figs else '그림 없음'}

문항의 공통 상황(제시문)을 쓰세요.
- 학생이 실생활에서 만날 만한 짧은 상황(3~5문장). 문제 풀이에 필요한 정보는 모두 본문 또는 그림에 있어야 하고, 정답을 알려 주면 안 된다.
- 히스토그램(histogram) 그림: hide_freq_idx는 **학생이 직접 그리게 할 계급 번호**(0부터)이며 그 계급의 막대는 그려지지 않는다. 본문이 '그림에 ~가 나타나 있다·그림을 읽는다'고 하면 hide_freq_idx를 빈 배열로 둔다(모든 막대를 숨겨 빈 그림이 되게 하지 않는다). 도수분포다각형은 polygon을 true로 해서 꺾은선을 겹치거나, bars를 false로 해서 꺾은선만 그린다.
- 그림이 필요하면 figures에 위 형식의 객체를 쓴다. params의 숫자는 본문의 숫자와 같아야 한다.
{DATASET_G2_RULE if dataset_spec else ''}- 표(도수분포표, 줄기와 잎 그림, x-y 대응표 등)가 필요하면 tables에 {{"id":"T1","caption":"...","headers":[...],"rows":[[...]]}} 로 쓴다. 줄기와 잎 그림은 headers ["줄기","잎"], 잎은 공백으로 구분한 문자열.
- 본문에서 '그림', '표', '자료'를 언급하면 그것이 반드시 figures 또는 tables에 있어야 한다. 본문의 모든 수학적 진술(용어 사용 포함)은 참이어야 한다. 예: 기본요금이 있는 요금은 정비례가 아니다.
- 소문항의 발문은 여기서 쓰지 않는다.
출력 JSON: {{"stimulus":{{"text":"...","figures":[],"tables":[]}},"numbers":{{"변수":값}}}}"""
    return call(cl, usage, "G2" + ("-재시도" if feedback else ""), with_feedback(user, feedback, prev), model, 10000)


# ================================================================ G3
TEMPLATED_MODEL_ANSWER_EXAMPLE = [{
    "subNo": "1-1",
    "methods": [{"methodId": "M1", "text": "호의 길이는 $2\\\\pi \\\\times {{r}} \\\\times \\\\frac{{{{theta}}}}{360} = {{arc|latex}}$ (cm)이다.",
                 "checks": [{"label": "호의 길이", "expr": "2*pi*r*theta/360", "expected": "arc"}]}]}]


def g3_prompt(design, stimulus, spec, env, elements, std, example, feedback=None, prev=None, book=None):
    templated = spec is not None
    ds_rule = (NL_ + "[자료 문항] 자료는 수치 명세의 data이다. 예시답안·채점기준에서 자료 값·중앙값·도수를 말할 때는 {{sorted(data)}}, {{median(data)}}, {{count_between(data, 60, 70)}}, {{mode(data)}} 같은 자리표시자로 쓰고(계급 경계가 변수에서 나오면 변수로), checks의 expr에도 같은 식(median(data) 등)을 쓴다. 자료를 숫자로 직접 나열하지 않는다.") if (spec and any("dataset(" in str(e) for e in spec.get("derived", {}).values())) else ""
    nb = (f"수치 명세(변수와 파생값, now는 지금 선택된 값):\n{spec_brief(spec, env)}\n{TEMPLATE_RULES}{ds_rule}" if templated
          else f"사용 숫자: {js(stimulus.get('numbers', {}))}")
    if templated:
        checks_rule = f"""- **checks는 코드가 다시 계산해 확인하는 검산 식이다.** 예시답안에 나오는 모든 핵심 계산 결과마다 하나씩 만든다. 형식: {{"label":"설명","expr":"변수·파생값 식","expected":"기대값 식"}}.
  vars는 쓰지 않는다(변수는 코드가 채운다). 숫자를 직접 쓰지 말고 변수·파생값 이름으로 쓴다. 예: expr "2*pi*r*theta/360", expected "arc". 식에는 {SAFE_FUNCS} 만 쓴다. 서술만 있는 소문항은 checks를 비워도 된다.
  예시답안 text 속 숫자도 모두 자리표시자: {js(TEMPLATED_MODEL_ANSWER_EXAMPLE)}"""
    else:
        checks_rule = """- **checks는 코드가 다시 계산해 확인하는 검산 식이다.** 형식: {"label":"설명","expr":"파이썬식","vars":{"변수":값},"expected":"기대값 식"}. 식에는 +,-,*,/,**,pi,sqrt()만 쓰고 vars에 숫자를 정수로 넣는다. 서술만 있는 소문항은 checks를 비워도 된다."""
    if isinstance(example, dict):          # 예전 호출 방식(예시 하나)
        example = [{"예시": "ex", "형식": example}]
    TB_METHOD_RULE = (" 선택한 교과서 목록이 있으므로 각 solutionMethod에 textbookItems(그 방법이 근거로 삼는 교과서 목록의 항목 번호 배열)를 반드시 쓴다. "
                      "목록의 성질·공식만으로 설명되지 않거나 목록에 없는 개념(예: 조합·경우의 수 계산)이 필요한 방법은 기본 풀이로 쓰지 말고 tier를 \"확장\"으로 표시한다(확장 풀이는 textbookItems를 비워도 된다)."
                      if scope_check.basis_block(std['code'], book) else "")
    TEACHER_ELEMENTS_RULE = (NL_ + "  교사가 직접 고른 평가 요소는 다음 문구를 **글자 그대로** 어느 소문항의 evaluationElements[].text에 넣는다(고른 요소를 모두 평가해야 한다. 설계상 필요하면 요소를 더 추가해도 된다): " + js([e["text"] for e in TEACHER_ELEMENTS])) if TEACHER_ELEMENTS else ""
    TIER_RULE = f"""
  · **기본 풀이**: 위 '중1 범위'(교과서를 골랐으면 그 교과서)에서 배운 내용만으로 풀 수 있는 풀이. 풀이 방법 중 첫 번째는 반드시 기본 풀이다. 3점 이상 소문항은 기본 풀이를 가능하면 2개 이상 만든다.
  · **확장 풀이**: 중2 이상에서 배우는 개념·공식·기법(예: 조합 n(n-1)/2, 이차식 인수분해)이 풀이에 꼭 필요한 풀이. 기본 풀이로 2개를 만들 수 없을 때에 한해 기본 1개 + 확장 1개까지 허용한다. 확장 풀이에는 extendedTag를 다음 목록 중 하나로 정확히 붙인다: {js(scope_check.later_tags())}. 기본 풀이에는 extendedTag를 쓰지 않는다.
  · 확장 풀이를 억지로 만들지는 않는다. 기본 풀이로 충분하면 모두 기본 풀이로 둔다. 풀이가 중1 범위 밖 개념에 기대는데 tier를 \"기본\"으로 쓰면 안 된다.
  · 채점 수준 서술은 풀이 방법에 중립으로 쓴다(\"식을 바르게 세워 구함\"처럼). 확장 풀이를 위한 별도 채점 유의점·교사 확인 사항은 만들지 않는다."""
    base = f"""성취기준 [{std['code']}] {std['text']}
성취수준: {js(std['achievementLevels'])}
확정된 평가 요소: {js([e['text'] for e in elements])}
문항 설계(소문항 골격): {js({k: design[k] for k in ('taskPattern','intent','subQuestions','solutionMethodsPlan')})}
제시문과 그림: {js({k: v for k, v in stimulus.items() if k != 'numbers'})}
{nb}

소문항별 발문·채점기준·예시답안을 완성하세요. 지켜야 할 규칙:
[구조]
- subQuestions는 설계의 no, answerType, maxScore, targetLevels, dependsOn을 그대로 유지하고 prompt, conditions, evaluationElements를 채운다.
- evaluationElements[].text는 '~하기'로 끝난다. standardCodes는 ["{std['code']}"].{TEACHER_ELEMENTS_RULE}
- evaluationElements[].scoringElements[]마다 text, maxScore, levels[{{score, descriptors[]}}]를 쓴다. 한 소문항의 모든 scoringElements maxScore 합 = 그 소문항 maxScore.
- levels는 2~5개, 점수가 위에서 아래로 엄격히 감소, 첫 수준 점수 = 그 scoringElement의 maxScore, **마지막(최하) 수준 점수는 반드시 1점**. 0점 수준은 쓰지 않는다.
- 수준 서술은 한 문장 이내로 '정확하게 구함 / 일부 오류가 있음 / 부분적으로 구함 / 어려움이 있음' 계열 표현을 쓰고 감점 규칙은 쓰지 않는다. 수준 서술에 정답 값을 고정해 쓰지 말고 '식을 바르게 세워 구함'처럼 쓴다(값은 자리표시자로 쓰거나 예시답안에만 둔다).
- 서술 소문항에는 <조건>을 conditions[{{id:'C1',text}}]로 줄 수 있다. 조건을 주면 반드시 어느 scoringElement의 conditionRefs에 그 id를 넣는다.
[풀이·예시답안]
- solutionMethods는 설계의 계획대로 id, name, summary를 쓰고 tier("기본" 또는 "확장")를 붙인다.{TIER_RULE}{TB_METHOD_RULE}
- modelAnswers는 소문항마다 {{subNo, methods:[{{methodId, text, checks:[...]}}]}}. 배점 3점 이상인 소문항은 방법 2개 이상(서로 다른 풀이).
- 예시답안 text에는 풀이 과정과 최종 답을 수식과 함께 쓴다.
{checks_rule}
[기타]
- scoringNotes: 아래 목록에서 이 문항에 맞는 것 2~4개를 골라 다듬어 쓴다. {js(NOTES_LIBRARY)}
- unitPolicy: 단위를 채점에서 평가하면 "평가함", 아니면 "평가하지 않음".
- teacherChecks: [{{"id":"T1","text":"...","subNos":["1-1"]}}] 형식, 1~3개. 아래 목록에서 이 문항에 해당하는 것을 고르고 문항에 맞게 구체화한다. 제시문이 이미 지시한 내용과 겹치면 고르지 않는다. {js(TEACHER_CHECK_LIBRARY)}
- feedbackNotes: 피드백 시 유의점 2~3개.

{guides.g3_rules()}

{scope_check.prompt_block(std['code'], book)}
{scope_check.hints_block(std['code'])}
{scope_check.basis_block(std['code'], book)}

형식 참고 예시 {len(example)}개(실제 중1 문항의 구조를 새로 쓴 것. 내용·숫자·소재는 복사하지 말고, 조건을 쓰는 방식과 수준 서술의 구체성, 방법별 풀이의 형식만 참고한다. 소문항 수와 배점 구성은 예시를 따르지 말고 위 '문항 설계'를 따른다):
{js(example)}

출력 JSON: {{"unitPolicy":"...","subQuestions":[...],"solutionMethods":[...],"modelAnswers":[...],"scoringNotes":[...],"teacherChecks":[...],"feedbackNotes":[...]{',"textbookBasis":[교과서 목록에서 예시답안이 실제 쓴 항목 번호]' if scope_check.basis_block(std['code'], book) else ''}}}"""
    if feedback:
        base += f"""

[이전 시도의 문제 - 반드시 고칠 것]
{js(feedback)}
이전 출력:
{js(prev)}
위 문제만 고쳐서 전체 JSON을 다시 출력한다. 검산 불일치는 코드가 계산한 값이 맞으므로 예시답안과 checks를 코드 값에 맞춘다. '수치 변경 시험' 오류는 변수 값에 따라 바뀌는 숫자를 고정 숫자로 썼거나 checks를 변수 식이 아닌 고정 값으로 썼다는 뜻이다."""
    return base


# ================================================================ 조립·검증
def assemble(args, std, comps, design, g2out, g3out, label):
    """템플릿 문항(자리표시자 포함)을 만든다."""
    core = scope_check._core(std["code"], args.textbook) or {"statements": [], "goals": []}
    used = []
    for i in g3out.get("textbookBasis") or []:
        try:
            used.append(core["statements"][int(i) - 1]["text"])
        except (ValueError, IndexError, TypeError):
            pass
    return {
        "schemaVersion": "math-0.1", "id": label, "level": "중학교", "grade": 1, "domain": std["domain"],
        "standardCodes": [std["code"]], "assessmentContext": args.context, "responseType": args.response_type,
        "taskPattern": design["taskPattern"], "competencies": comps, "maxScore": args.max_score,
        "unitPolicy": g3out.get("unitPolicy", "평가하지 않음"), "intent": design.get("intent", ""),
        "stimulus": {k: v for k, v in g2out["stimulus"].items()},
        "subQuestions": g3out["subQuestions"], "solutionMethods": g3out["solutionMethods"],
        "modelAnswers": g3out["modelAnswers"], "scoringNotes": g3out.get("scoringNotes", []),
        "teacherChecks": g3out.get("teacherChecks"), "feedbackNotes": g3out.get("feedbackNotes", []),
        "review": {"status": "unreviewed", "reviewedBy": None},
        "generationMeta": {"model": args.model, "difficulty": args.difficulty, "seed": args.seed, "guides": guides.VERSION, "textbook": args.textbook or "none",
                           "generatedAt": datetime.datetime.now().isoformat(timespec="seconds"), "theme": design.get("theme", ""), "chosenElements": [e["text"] for e in TEACHER_ELEMENTS], "textbookBasis": used, "textbookBasisOffered": bool(core["statements"]), "textbookBasisList": [x["text"] for x in core["statements"]], "textbookGoals": core["goals"][:12] if args.textbook not in (None, "none") else []},
    }


def run_validate(item):
    stds = load_json("standards.json")["standards"]
    figs = load_json("figure_types_math1.json")["figureTypes"]
    pats = {p["id"] for p in load_json("task_patterns_math.json")["patterns"]}
    return V.validate(item, stds, figs, pats, str(DATA / "numspecs"))


def item_text(item):
    parts = [item["stimulus"].get("text", "")] + [q.get("prompt", "") for q in item["subQuestions"]]
    for a in item.get("modelAnswers", []):
        parts += [m.get("text", "") for m in a.get("methods", [])]
    for t in item["stimulus"].get("tables", []):
        parts += [str(c) for r in t.get("rows", []) for c in r]
    return " ".join(parts)


COMMON_CONSTS = {1, 2, 3, 4, 5, 6, 10, 60, 90, 100, 180, 360}


def hardcode_suspects(rendered_a, vals_a, rendered_b, vals_b, env_b):
    """A값으로 만든 숫자가 B값으로 채운 문항에 그대로 남아 있으면 고정 숫자로 쓴 것으로 의심한다(경고)."""
    text_b = item_text(rendered_b)
    ints_b = {int(v) for v in env_b.values() if isinstance(v, T.sp.Basic) and v.is_Integer}
    out = []
    for k, va in vals_a.items():
        if vals_b.get(k) == va or va in COMMON_CONSTS or va in ints_b:
            continue
        if re.search(rf"(?<![\d.]){re.escape(str(va))}(?![\d.])", text_b):
            out.append(f"변수 {k}의 값 {va}이(가) 숫자를 바꾼 뒤에도 본문·예시답안에 그대로 남아 있다(고정 숫자로 쓴 것으로 의심)")
    return out


def change_test(template_item, spec, vals, difficulty, seed, n=2):
    """수치 변경 시험: 다른 숫자로 채워 검증이 통과하는지 확인한다. 오류 목록을 돌려준다."""
    errs, seen = [], [vals]
    rendered_a = T.render_item(template_item, spec, vals)
    for i in range(n):
        v2 = T.pick_values(spec, seed + 101 + i, difficulty, exclude=seen)
        if v2 is None:
            break
        seen.append(v2)
        try:
            r2 = T.render_item(template_item, spec, v2)
        except Exception as ex:
            errs.append(f"수치 변경 시험({v2}): 채우기 실패 - {ex}")
            continue
        e2, w2 = run_validate(r2)
        errs += [f"수치 변경 시험({v2}): {e}" for e in e2]
        env_b, _ = T.binding_env(spec, v2)
        errs += [f"수치 변경 시험({v2}): {w}" for w in hardcode_suspects(rendered_a, vals, r2, v2, env_b or {})]
    return errs


def explain_errors(errs, item):
    """검증 오류를 '어떻게 고치는지'까지 알려 주는 문장으로 바꾼다(되먹임용)."""
    out = []
    subs = {q["no"]: q for q in item.get("subQuestions", [])}
    for e in errs:
        m = re.match(r"M23 (\S+): 조건 (\S+)가", e)
        if m and m.group(1) in subs:
            no, cid = m.group(1), m.group(2)
            q = subs[no]
            ses = [se["text"] for el in q["evaluationElements"] for se in el["scoringElements"]]
            out.append(f"{e} -> 해결: 소문항 {no}의 채점 요소({ses}) 중 조건 {cid}를 평가하는 요소의 conditionRefs 배열에 \"{cid}\"를 넣고, 그 요소의 levels[].descriptors에 '{cid} 조건을 지켰는지'가 드러나게 쓴다. "
                       f"조건이 채점 요소보다 많으면 한 요소의 conditionRefs에 여러 조건 id를 함께 넣거나, 불필요한 조건을 줄인다.")
        elif e.startswith("M22") or e.startswith("M9"):
            out.append(e + " -> 해결: 각 채점 요소의 maxScore를 더한 값이 소문항 maxScore와 같도록 조정한다(소문항 maxScore는 설계 값 유지).")
        else:
            out.append(e)
    return out


# ================================================================ AI 점검
def _basis_review_rule(item):
    """풀이의 기본/확장 판정은 전용 호출(tiering.py)이 맡는다. 일반 점검에는 넣지 않는다."""
    return ""


def run_tiering(cl, usage, model, template_item, item):
    """풀이의 기본/확장을 전용 호출로 판정하고, 범위 밖 풀이를 확장으로 고친다(템플릿과 채워진 문항 모두). 막힌 풀이를 돌려준다."""
    try:
        flags = tiering.classify(call, cl, usage, model, item)
    except Exception as ex:
        print("  풀이 판정 실패(문항은 그대로 둔다):", ex)
        return []
    if not flags:
        print("  풀이 판정: 범위 밖 풀이 없음")
        return []
    changed, blocked = tiering.apply([template_item, item], flags)
    for f in flags:
        print(f"  풀이 판정: {f['id']} -> {'확장으로 변경' if f['id'] in changed else '변경 불가(기본 풀이가 없어짐)'} | {f['laterTag']} | '{f['quote'][:50]}'")
    return blocked


def review(cl, usage, model, item):
    user = f"""아래 서술형 문항 세트를 점검하세요. 점검 관점:
1. 발문이 모호하거나 정답이 둘 이상 나올 여지가 있는가
2. 수준 서술이 서로 구별되고 일관된가(상위·하위 수준 차이가 분명한가)
3. 예시답안의 서술에 수학적 오류가 있는가(계산 결과는 코드가 이미 검산했으니 서술·논리만)
4. 성취기준 범위와 중1 수준을 벗어나는 내용이 있는가
5. 제시문만으로 풀이에 필요한 정보가 충분한가
6. 제시문·발문의 모든 수학적 진술과 용어 사용이 참인가(예: 기본요금이 있는 요금을 '정비례'라고 쓰는 것 같은 오용)
7. 제시문이나 발문이 언급한 그림·표·자료가 stimulus.figures 또는 stimulus.tables에 실제로 있는가
8. 출제 의도(intent)에 코드·AI·수치 명세 같은 내부 도구 이야기가 섞여 있는가
10. 중1 교과서가 다루지 않는 수학 내용이 있는가(아래 '중1 범위' 참고. 예시답안과 채점기준 포함). 있으면 rule을 "SCOPE"로 쓴다.
{scope_check.prompt_block(item['standardCodes'][0], scope_check.book_of(item), compact_other=False, include_style=False)}
{_basis_review_rule(item)}
9. 아래 작성 원칙(경기도교육청 논술형 평가 길라잡이 등에서 뽑은 것)을 어긴 곳이 있는가. 특히 조건이 정답을 암시하는지(C2), 조건이 채점 수준에 반영됐는지(C4), 수준 서술이 대상 없이 정도만 쓴 모호한 표현인지(R1)와 인접 수준이 구별되는지(R2, R3)를 본다.
{guides.review_checklist()}
문항: {js(item)}
출력 JSON: {{"verdict":"양호|수정 권고","issues":[{{"severity":"심각|보통|경미","rule":"어긴 작성 원칙의 id(예: C2, 해당 없으면 빈 문자열)","where":"소문항 번호 또는 제시문","problem":"...","suggestion":"..."}}]}}
심각은 학생이 풀 수 없거나(필요한 자료 누락 포함) 채점이 불가능하거나 수학적으로 틀린 진술이 있는 경우에만 쓴다. 이슈는 중요한 것부터 최대 6개, problem과 suggestion은 각각 두 문장 이내로 쓴다. 문제가 없으면 issues를 빈 배열로 둔다."""
    return call(cl, usage, "AI점검", user, model, 20000)


# ================================================================ 출력
def to_markdown(item, errs, warns, rv, usage_total=None):
    L = []
    s = item["stimulus"]
    L.append(f"# 중1 수학 서술형 문항 ({item['id']}) — 총 {item['maxScore']}점\n")
    L.append(f"- 성취기준: {', '.join(item['standardCodes'])} / 역량: {', '.join(item['competencies'])} / 과제 패턴: {item['taskPattern']}\n- 출제 의도: {item['intent']}")
    if item.get("numberBinding"):
        L.append(f"- 사용 숫자: {item['numberBinding']['values']} (수치 명세 {item['numberBinding']['specId']}, 템플릿 방식 — 숫자만 바꾸기 가능)\n")
    L.append("## 평가 문항\n")
    L.append(s["text"] + "\n")
    for f in s.get("figures", []):
        L.append(f"![{f.get('caption','')}]({f['id']}.svg)\n")
    for t in s.get("tables", []):
        L.append(f"**{t.get('caption', '')}**\n")
        L.append("| " + " | ".join(str(h) for h in t["headers"]) + " |")
        L.append("|" + "---|" * len(t["headers"]))
        for r in t["rows"]:
            L.append("| " + " | ".join(str(c) for c in r) + " |")
        L.append("")
    for q in item["subQuestions"]:
        L.append(f"**{q['no']}.** {q['prompt']} [{q['maxScore']}점]\n")
        for c in q.get("conditions", []):
            L.append(f"> 〈조건〉 {c['text']}\n")
    L.append("## 채점기준표\n")
    L.append("| 문항 | 평가 요소 | 채점 요소 | 배점 | 수행 수준 |\n|---|---|---|---|---|")
    for q in item["subQuestions"]:
        for e in q["evaluationElements"]:
            for se in e["scoringElements"]:
                for lv in se["levels"]:
                    L.append(f"| {q['no']} | {e['text']} | {se['text']} | {lv['score']} | {' '.join(lv['descriptors'])} |")
    L.append("\n## 예시답안\n")
    ms = {m['id']: m['name'] + (f" — 확장 풀이, {scope_check.tag_label(m['extendedTag'])}" + (f" (AI 점검: '{m['tierNote']['quote'][:40]}')" if m.get('tierNote') else '') if m.get('tier') == '확장' and m.get('extendedTag') else '') for m in item["solutionMethods"]}
    for a in item["modelAnswers"]:
        for m in a["methods"]:
            L.append(f"- **{a['subNo']}** ({ms.get(m['methodId'], m['methodId'])}): {m['text']}")
    L.append("\n## 채점 시 유의점\n" + "\n".join(f"- {x}" for x in item["scoringNotes"]))
    L.append(f"\n- 단위: {item['unitPolicy']}")
    L.append("\n## 교사 확인 사항\n" + "\n".join(f"- ({t['id']}, {', '.join(t.get('subNos', []))}) {t['text']}" for t in item.get("teacherChecks") or []))
    L.append("\n## 피드백 시 유의점\n" + "\n".join(f"- {x}" for x in item["feedbackNotes"]))
    L.append(f"\n## 검증 결과\n- 오류 {len(errs)}개, 경고 {len(warns)}개")
    L += [f"  - 오류: {e}" for e in errs] + [f"  - 경고: {w}" for w in warns]
    if rv:
        L.append(f"\n## AI 점검 의견 ({rv.get('verdict')})")
        L += [f"- [{i['severity']}] {i['where']}: {i['problem']} -> {i['suggestion']}" for i in rv.get("issues", [])]
    if usage_total:
        L.append(f"\n---\n사용량: 호출 {usage_total['calls']}회, 입력 {usage_total['in']} 토큰, 출력 {usage_total['out']} 토큰, 추정 비용 약 ${usage_total['estUSD']} (단가는 추정)")
    return "\n".join(L)


def write_outputs(out_dir, item, template_item, errs, warns, rv, usage_total):
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in item["stimulus"].get("figures", []):
        try:
            (out_dir / f"{f['id']}.svg").write_text(render(f), encoding="utf-8")
        except Exception as ex:
            print("  그림 렌더 실패:", f.get("id"), ex)
    (out_dir / "item.json").write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    if template_item is not None:
        (out_dir / "item.template.json").write_text(json.dumps(template_item, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "item.md").write_text(to_markdown(item, errs, warns, rv, usage_total), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps({"errors": errs, "warnings": warns, "aiReview": rv, "usage": usage_total}, ensure_ascii=False, indent=1), encoding="utf-8")


# ================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--standard", required=True)
    ap.add_argument("--max-score", type=int, default=10)
    ap.add_argument("--difficulty", default="medium", choices=["easy", "medium", "hard"])
    ap.add_argument("--response-type", default="서술형")
    ap.add_argument("--context", default="수행평가")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--elements", type=int, default=3, help="G0 후보 중 자동 확정할 평가 요소 수")
    ap.add_argument("--label", default="run")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--max-retry", type=int, default=3)
    ap.add_argument("--pattern", default="auto", help="과제 패턴 id 또는 auto(AI 선택, 기본)")
    ap.add_argument("--list-patterns", action="store_true", help="이 성취기준에서 고를 수 있는 과제 패턴을 보여 주고 종료")
    ap.add_argument("--approve-spec", default=None, help="교사가 확인한 수치 명세 초안의 id")
    ap.add_argument("--auto-approve-spec", action="store_true", help="(시험용) 명세 초안을 교사 확인 없이 확정")
    ap.add_argument("--textbook", default="none", help="교과서 id(data/textbook_registry.json) 또는 none(미선택=중립, 기본). 분석된 책만 선택할 수 있다")
    ap.add_argument("--provisional", action="store_true", help="명세 초안을 이 문항 전용 임시 규칙으로 쓰고 끝까지 진행(웹: 문항 아래에서 고치고 확정)")
    ap.add_argument("--g0-only", action="store_true", help="평가 요소 후보(G0)만 만들어 JSON으로 출력하고 종료(웹: 평가 요소 고르기)")
    ap.add_argument("--elements-file", default=None, help="교사가 고른 평가 요소 JSON 파일({elements:[{text,kind,fromGoal}], competencies:[]}). 있으면 G0를 건너뛴다")
    args = ap.parse_args()
    args.textbook = scope_check.norm_book(args.textbook) or "none"       # 분석 안 된 책이면 여기서 중단(오류)

    stds = {s["code"]: s for s in load_json("standards.json")["standards"]}
    std = stds[args.standard]
    if args.g0_only:
        cl0, usage0 = client(), Usage()
        c0 = g0(cl0, usage0, args.model, std, args.textbook)
        core = scope_check._core(args.standard, args.textbook) or {}
        print("G0JSON:" + json.dumps({"candidates": c0["evaluationElementCandidates"], "competencies": [c for c in c0["competencyCandidates"] if c in COMPETENCIES], "goals": core.get("goals", [])}, ensure_ascii=False))
        print("사용량:", usage0.total())
        return
    pool = pattern_pool(args.standard)
    if args.list_patterns:
        print(f"{args.standard} 에서 고를 수 있는 과제 패턴 (기본 auto = AI가 선택):")
        for p in pool:
            print(f"  {p['id']:28s} {p['name']} — {p['structure'][:60]}")
        return
    if args.pattern != "auto" and args.pattern not in {p["id"] for p in pool}:
        raise SystemExit(f"알 수 없는 과제 패턴 {args.pattern}. --list-patterns 로 확인하세요.")
    pats = pool if args.pattern == "auto" else [p for p in pool if p["id"] == args.pattern]

    out_dir = ROOT / "output" / "pilot" / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    global RAW_DIR
    RAW_DIR = out_dir
    cl, usage = client(), Usage()

    print(f"== {args.label}: {args.standard} {std['text']} | 교과서: {scope_check.label_of(args.textbook) if args.textbook != 'none' else '미선택(중립)'}")
    if args.elements_file:                      # 교사가 화면에서 고른 평가 요소: G0(AI) 호출 없이 그대로 쓴다
        ef = json.load(open(args.elements_file, encoding="utf-8"))
        elements = [{"text": e["text"].strip(), "kind": e.get("kind", ""), "fromGoal": e.get("fromGoal", "")} for e in ef["elements"] if e.get("text", "").strip()]
        if not elements:
            raise SystemExit("평가 요소 파일에 사용할 요소가 없다")
        comps = [c for c in ef.get("competencies", []) if c in COMPETENCIES][:3] or ["문제해결"]
        global TEACHER_ELEMENTS
        TEACHER_ELEMENTS = elements
        print("  평가 요소(교사 선택):", [e["text"] for e in elements], "| 역량:", comps)
    else:
        c0 = g0(cl, usage, args.model, std, args.textbook)
        cands = c0["evaluationElementCandidates"]
        elements = ([e for e in cands if e["text"].strip().endswith("하기")] or cands)[:args.elements]
        comps = [c for c in c0["competencyCandidates"] if c in COMPETENCIES][:3] or ["문제해결"]
        print("  평가 요소(자동 확정):", [e["text"] for e in elements], "| 역량:", comps)
    if any(e.get("fromGoal") for e in elements):
        print("  └ 근거 학습 목표:", [e.get("fromGoal") for e in elements])

    spec0 = find_numspec(args.standard)
    design = g1(cl, usage, args.model, args, std, elements, comps, pats, spec0)
    for _ in range(2):
        de = design_errors(design, args.max_score, {p["id"] for p in pats})
        if not de:
            break
        print("  설계 오류:", de)
        design = g1(cl, usage, args.model, args, std, elements, comps, pats, spec0, de, design)
    if args.textbook not in (None, 'none'):
        th_c = scope_check.pick_themes(std['code'], args.textbook, args.seed)
        if design.get('theme') not in th_c:
            design['theme'] = ''                  # 후보 밖이거나 비어 있으면 제시문 단계(G2)가 후보 중에서 고른다
        print('  소재(설계 단계):', design.get('theme') or '(없음: 제시문 단계에서 후보 중 선택)', '|', design.get('themeFit', ''))
    print("  패턴:", design["taskPattern"], "| 소문항:", [(q["no"], q["maxScore"]) for q in design["subQuestions"]], "| 자료 필요:", design.get("needsDataset"))
    example = guides.pick_examples(design, std)      # 패턴·영역이 비슷한 예시 + 다른 영역 예시
    print("  형식 예시:", [e["예시"] for e in example], "| 점검표", guides.VERSION)

    # ---- 수치 명세 확보 (있으면 사용, 없으면 AI 초안 + 교사 확정)
    spec, spec_status = None, "none"
    if False:                                   # 자료형 문항도 이제 자료 생성기(dataset 함수)로 숫자 규칙을 만든다. 만들 수 없을 때만 obtain_spec이 unsupported를 돌려준다
        spec_status = "unsupported"
    elif spec0 and design.get("useNumSpec") and design["taskPattern"] in spec0.get("taskPatterns", [design["taskPattern"]]):
        spec, spec_status = spec0, "existing"
    else:
        spec, spec_status = obtain_spec(cl, usage, args, std, design)
        if spec_status == "pending":
            (out_dir / "stages.json").write_text(json.dumps({"g0": c0, "g1": design}, ensure_ascii=False, indent=1), encoding="utf-8")
            print("  교사 확인 대기로 중단 (비용:", usage.total(), ")")
            sys.exit(2)
        if spec_status == "unsupported":
            spec = None

    vals = env = None
    if spec:
        pick = T.pick_values(spec, args.seed, args.difficulty)
        if pick is None:
            raise SystemExit("수치 명세에서 조건을 만족하는 숫자를 고르지 못함")
        vals = pick
        env, _ = T.binding_env(spec, vals)
        print(f"  수치 선택({args.difficulty}, 시드 {args.seed}): {vals}")

    if args.textbook not in (None, 'none'):
        print('  소재 후보(코드 지정):', scope_check.pick_themes(std['code'], args.textbook, args.seed))
    g2out = g2(cl, usage, args.model, design, spec, env, std, book=args.textbook, seed=args.seed)
    for attempt in range(3):
        try:
            filled = T.fill(g2out["stimulus"], env) if spec else g2out["stimulus"]
            fe = fig_errors(filled)
            if spec and not fe:                  # 자료형 문항: 표(autoTable)가 자료를 제대로 덮는지 미리 시험한다
                try:
                    import copy as _cp
                    datatable.expand_tables({"stimulus": _cp.deepcopy(filled)}, env)
                except Exception as ex_t:
                    fe = [f"표(autoTable) 오류: {ex_t}. autoTable의 kind·data·start·width·count를 점검하고, 계급이 자료 범위(수치 명세의 min/max 제약)를 덮게 한다."]
        except Exception as ex:      # 제시문의 자리표시자가 잘못 쓰인 경우(예: LaTeX 중괄호와 겹침)도 G2에 되먹임한다(예전에는 여기서 생성이 중단됐다)
            fe = [f"제시문(stimulus)의 자리표시자 오류: {ex}. 숫자 자리표시자는 {{{{식}}}} 형태(여는 중괄호 2개, 닫는 중괄호 2개)로만 쓰고, LaTeX의 지수·분수 중괄호와 붙어 겹치지 않게 한다. 예: ${{{{p}}}}^{{ {{{{a}}}} }}$ 처럼 바깥 중괄호 안쪽에 공백을 둔다."]
        if not fe:
            break
        if attempt == 2:
            raise SystemExit("상황·그림(G2) 오류가 두 번 고쳐도 남았다: " + "; ".join(fe)[:300])
        print("  G2 오류:", fe)
        g2out = g2(cl, usage, args.model, design, spec, env, std, fe, g2out, book=args.textbook, seed=args.seed)

    feedback, prev, prev_errs, repeat, prev_w11 = None, None, None, 0, None
    template_item = item = None
    errs, warns = [], []
    for attempt in range(1, args.max_retry + 2):
        prompt = g3_prompt(design, g2out["stimulus"], spec, env, elements, std, example, feedback, prev, book=args.textbook)
        g3out = call(cl, usage, f"G3-{attempt}", prompt, args.model, G3_MAX_TOKENS)
        template_item = assemble(args, std, comps, design, g2out, g3out, args.label)
        errs, warns = [], []
        try:
            if spec:
                errs += T.placeholder_errors(template_item, spec, vals)
                item = T.render_item(template_item, spec, vals) if not errs else None
            else:
                item = template_item
        except Exception as ex:
            errs.append(f"템플릿 채우기 실패: {ex}")
            item = None
        if item is not None:
            e1, w1 = run_validate(item)
            errs += e1
            warns += w1
            if spec and not errs:
                errs += [e for e in change_test(template_item, spec, vals, args.difficulty, args.seed) if "고정 숫자" not in e]
                warns += [e for e in change_test(template_item, spec, vals, args.difficulty, args.seed) if "고정 숫자" in e]
        print(f"  검증 {attempt}회차: 오류 {len(errs)}, 경고 {len(warns)}", flush=True)
        for e in errs:
            print("    오류:", e)
        if not errs and not [w for w in warns if "고정 숫자" in w or w.startswith(("W11", "W13", "W14", "W15"))] or attempt > args.max_retry:
            break
        fixable = [e for e in errs if not e.startswith(("M28", "M29"))]
        if errs and not fixable:
            print("    G3로 고칠 수 없는 오류(그림·수치 명세)만 남아 재시도를 중단한다")
            break
        repeat = repeat + 1 if (errs and prev_errs == errs) else 0
        if repeat >= 2:
            print("    같은 오류가 두 번 더 반복되어 재시도를 중단한다")
            break
        prev_errs = errs
        w11 = [w for w in warns if w.startswith("W11")]
        if not errs and w11 and w11 == prev_w11:            # 범위 경고만 남고 같은 경고가 되풀이되면 더 호출하지 않고 경고를 남긴 채 저장한다
            print("    중1 범위 경고가 그대로여서 재시도를 중단한다(경고는 문항에 남는다)")
            break
        prev_w11 = w11
        w13 = [w for w in warns if w.startswith(("W13", "W14", "W15"))]
        feedback = (explain_errors(fixable, template_item) + [w for w in warns if w.startswith("W4") or "고정 숫자" in w]
                    + [w + " -> 해결: 해당 표현을 쓰지 말고 중1 용어와 중1 풀이로 바꿔 쓴다(예시답안이면 풀이 방식을 바꾼다)." for w in w11]
                    + [w + " -> 해결: 그 풀이 방법을 교과서 목록의 성질·공식으로 설명되는 방법으로 바꾸고 textbookItems에 번호를 쓴다." for w in w13])
        prev = g3out

    if item is None:
        raise SystemExit("문항을 만들지 못했다: " + "; ".join(errs[:3]))
    write_outputs(out_dir, item, template_item if spec else None, errs, warns, None, usage.total())
    rv = None
    tier_blocked = []
    if not errs:
        tier_blocked = run_tiering(cl, usage, args.model, template_item if spec else None, item)
        try:
            rv = review(cl, usage, args.model, item)
        except Exception as ex:
            print("  AI 점검 실패(문항은 저장됨):", ex)
            rv = {"verdict": "점검 실패", "issues": []}
        severe = [i for i in rv.get("issues", []) if i["severity"] == "심각"] + [tiering.blocked_issue(b) for b in tier_blocked]
        print(f"  AI 점검: {rv.get('verdict')}, 이슈 {len(rv.get('issues', []))}개(심각 {len(severe)})")
        if severe:
            prompt = g3_prompt(design, g2out["stimulus"], spec, env, elements, std, example, severe, prev or g3out, book=args.textbook)
            g3out = call(cl, usage, "G3-자동수정", prompt, args.model, G3_MAX_TOKENS)
            t2 = assemble(args, std, comps, design, g2out, g3out, args.label)
            try:
                i2 = T.render_item(t2, spec, vals) if spec else t2
                e2, w2 = run_validate(i2)
                if spec and not e2:
                    e2 += [e for e in change_test(t2, spec, vals, args.difficulty, args.seed) if "고정 숫자" not in e]
            except Exception as ex:
                e2, w2, i2 = [str(ex)], [], None
            print(f"  자동 수정 후 검증: 오류 {len(e2)}")
            if not e2:
                template_item, item, errs, warns = t2, i2, e2, w2
                run_tiering(cl, usage, args.model, template_item if spec else None, item)
                rv = review(cl, usage, args.model, item)
    write_outputs(out_dir, item, template_item if spec else None, errs, warns, rv, usage.total())
    (out_dir / "usage.json").write_text(json.dumps({"rows": usage.rows, "total": usage.total()}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  저장:", out_dir)
    print("  사용량:", usage.total())
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
