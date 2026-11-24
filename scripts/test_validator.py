"""검증기가 규칙 위반을 실제로 잡는지 확인한다. 예시 문항을 일부러 망가뜨려 기대한 규칙 번호가 나오는지 본다."""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import validate_item as v  # noqa: E402

ROOT = v.ROOT
base = json.load(open(os.path.join(ROOT, "data", "examples", "item_example.json"), encoding="utf-8"))
standards = json.load(open(os.path.join(ROOT, "data", "standards.json"), encoding="utf-8"))["standards"]
figs = v._load("data/figure_types_math1.json")["figureTypes"]
pats = {p["id"] for p in v._load("data/task_patterns_math.json")["patterns"]}
numdir = os.path.join(ROOT, "data", "numspecs")


def run(item):
    errs, warns = v.validate(item, standards, figs, pats, numdir)
    return errs, warns


def case(name, mutate, expect):
    item = copy.deepcopy(base)
    mutate(item)
    errs, _ = run(item)
    hit = any(e.startswith(expect) for e in errs)
    print(("통과" if hit else "실패"), "-", name, f"(기대 {expect})")
    if not hit:
        print("   실제:", errs)
    return hit


ok = [run(base)[0] == []]
print("기준 문항 오류 없음:", ok[0])

lv = lambda i, q=0, e=0, s=0: i["subQuestions"][q]["evaluationElements"][e]["scoringElements"][s]["levels"]
ok += [
    case("최하 수준 0점", lambda i: lv(i)[-1].update(score=0), "M19"),
    case("점수가 감소하지 않음", lambda i: lv(i, 1, 0, 1)[1].update(score=4), "M17"),
    case("소문항 배점 합 불일치", lambda i: i["subQuestions"][0].update(maxScore=5), "M22"),
    case("총점 불일치", lambda i: i.update(maxScore=12), "M9"),
    case("배점 상한 초과", lambda i: i.update(maxScore=31), "M7"),
    case("수준이 1개뿐", lambda i: lv(i).pop(), "M16"),
    case("검산 불일치(틀린 정답)", lambda i: i["modelAnswers"][0]["methods"][0]["checks"][0].update(expected="5*pi"), "M26"),
    case("검산 식에 위험한 코드", lambda i: i["modelAnswers"][0]["methods"][0]["checks"][0].update(expr="__import__('os')"), "M26"),
    case("교사 확인 사항 없음", lambda i: i.pop("teacherChecks"), "M27"),
    case("조건이 수준에 연결 안 됨", lambda i: i["subQuestions"][1]["evaluationElements"][0]["scoringElements"][1].pop("conditionRefs"), "M23"),
    case("알 수 없는 그림 유형", lambda i: i["stimulus"]["figures"][0].update(type="unknown_fig"), "M28"),
    case("그림 params 오류(삼각형 변 길이 불가능)", lambda i: i["stimulus"]["figures"].append({"id": "F2", "type": "polygon_labeled", "params": {"sides": {"AB": 1, "BC": 1, "CA": 5}}}), "M28"),
    case("수치 명세 제약 위반(r=5, 90도 아님)", lambda i: i["numberBinding"].update(values={"r": 5, "theta": 90}), "M29"),
    case("예시답안 누락", lambda i: i["modelAnswers"].pop(), "M25"),
    case("알 수 없는 성취기준", lambda i: i.update(standardCodes=["9수99-99"]), "M2"),
    case("dependsOn이 뒤의 문항", lambda i: i["subQuestions"][0].update(dependsOn=["1-2"]), "M11"),
]


def warn_case(name, mutate, expect, absent=False):
    """경고(W) 시험: expect로 시작하는 경고가 나오는지(absent=True면 나오지 않는지) 본다."""
    item = copy.deepcopy(base)
    mutate(item)
    _, warns = run(item)
    got = any(w.startswith(expect) for w in warns)
    hit = (not got) if absent else got
    print(("통과" if hit else "실패"), "-", name, f"(기대 {expect}{' 없음' if absent else ''})")
    if not hit:
        print("   실제:", warns)
    return hit


ok += [
    warn_case("미선택: 지수 0은 참고 경고 W12", lambda i: i["modelAnswers"][0]["methods"][0].update(text="$2^0=1$이므로 ..."), "W12"),
    warn_case("미선택: 지수 0은 W11이 아님(재작성 요구 안 함)", lambda i: i["modelAnswers"][0]["methods"][0].update(text="$2^0=1$이므로 ..."), "W11", absent=True),
    warn_case("교과서 선택(천재): 지수 0은 W11", lambda i: (i["generationMeta"].update(textbook="cheonjae_kim_dongjae"), i["modelAnswers"][0]["methods"][0].update(text="$2^0=1$이므로 ...")), "W11"),
    warn_case("미선택에서도 성취기준 근거가 있는 제곱근은 W11", lambda i: i["subQuestions"][0].update(prompt="$\sqrt{2}$의 값을 구하시오."), "W11"),
    warn_case("중1 범위 밖: 발문의 제곱근(교과서 선택)", lambda i: i["subQuestions"][0].update(prompt="$\\sqrt{2}$의 값을 구하시오."), "W11"),
    warn_case("오탐 없음: 소인수분해는 중1 용어", lambda i: i["subQuestions"][0].update(prompt="360을 소인수분해하시오."), "W11", absent=True),
    warn_case("오탐 없음: 평범한 거듭제곱 $10^2$, $2^3$", lambda i: i["subQuestions"][0].update(prompt="$10^2$과 $2^3$을 계산하시오."), "W11", absent=True),
    warn_case("오탐 없음: 소수 지수 $2^{0.5}$가 아닌 지수 10", lambda i: i["subQuestions"][0].update(prompt="$3^{10}$을 계산하시오."), "W11", absent=True),
]
ok += [
    case("첫 풀이가 확장 풀이이면 M30", lambda i: i["solutionMethods"][0].update(tier="확장", extendedTag="중2 · 경우의 수와 확률"), "M30"),
    case("확장 풀이의 태그가 목록 밖이면 M30", lambda i: i["solutionMethods"][-1].update(tier="확장", extendedTag="중9 · 없는 단원"), "M30"),
    warn_case("확장 풀이 안의 중2·3 용어는 W11 아님", lambda i: (i["solutionMethods"][-1].update(tier="확장", extendedTag="중3 · 제곱근과 실수"), i["modelAnswers"][0]["methods"][-1].update(text="$\\sqrt{2}$를 이용한다.")), "W11", absent=True),
]
ok += [
    warn_case("교과서 선택(천재): 동아에만 있는 용어 W14", lambda i: (i["generationMeta"].update(textbook="cheonjae_kim_dongjae"), i["subQuestions"][0].update(prompt="공간에서 직선과 평면의 위치 관계를 설명하시오.")), "W14"),
    warn_case("미선택: 용어 대조 W14 없음", lambda i: i["subQuestions"][0].update(prompt="공간에서 직선과 평면의 위치 관계를 설명하시오."), "W14", absent=True),
    warn_case("교과서 근거 번호가 목록에 없으면 W15", lambda i: (i["generationMeta"].update(textbook="cheonjae_kim_dongjae", textbookBasisOffered=True, textbookBasisList=["가나다 라마바 사아자", "차카타 파하"]), i["solutionMethods"][0].update(textbookItems=[999])), "W15"),
]
ok += [
    warn_case("교사가 고른 평가 요소가 채점기준에 없으면 W16", lambda i: i["generationMeta"].update(chosenElements=["도형의 닮음비 구하기 설명하기"]), "W16"),
    warn_case("교사가 고른 평가 요소가 채점기준에 있으면 W16 없음", lambda i: i["generationMeta"].update(chosenElements=[i["subQuestions"][0]["evaluationElements"][0]["text"]]), "W16", absent=True),
]
HIST = lambda hide: {"id": "F1", "type": "histogram", "caption": "x", "params": {"classes": [[0, 10], [10, 20]], "freqs": [3, 4], "polygon": False, "hide_freq_idx": hide}}
ok += [
    warn_case("히스토그램 막대를 모두 숨기면 W17(빈 그림)", lambda i: i["stimulus"].update(figures=[HIST([0, 1])]), "W17"),
    warn_case("히스토그램 막대를 보이면 W17 없음", lambda i: i["stimulus"].update(figures=[HIST([])]), "W17", absent=True),
]
print(f"\n{sum(ok)}/{len(ok)} 통과")
sys.exit(0 if all(ok) else 1)
