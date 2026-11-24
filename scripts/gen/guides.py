"""품질 점검표(A)와 형식 예시(B)를 문항 생성·AI 점검 프롬프트에 넣는다.

- 점검표: data/quality_rules_math.json  (docu 자료에서 뽑은 작성 원칙. 교과서 분석(C) 후 보강)
- 예시: data/examples/guide_examples_math1.json + data/examples/item_example.json(부채꼴 판단 문항)
"""
import json
import pathlib
import zlib

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"
VERSION = "A1B1"     # 점검표·예시를 바꾸면 올린다(생성 결과에 기록해 전후 비교에 쓴다)
CONTENT_KEYS = ("subQuestions", "solutionMethods", "scoringNotes", "teacherChecks", "feedbackNotes", "unitPolicy")


def _load(rel):
    return json.load(open(DATA / rel, encoding="utf-8"))


def rules():
    return _load("quality_rules_math.json")


def _fmt(r, with_examples=True):
    s = f"- [{r['id']}·{r['area']}] {r['rule']}"
    if with_examples:
        s += f"\n    나쁜 예: {r['bad']} / 좋은 예: {r['good']}"
    return s


def g3_rules():
    """소문항 작성(G3) 프롬프트에 넣는 작성 원칙."""
    q = rules()
    by = {r["id"]: r for r in q["rules"]}
    lines = [_fmt(by[i]) for i in q["g3Order"] if i in by]
    return ("[문항 작성 원칙 - 경기도교육청 논술형 평가 길라잡이 등 자료에서 뽑은 것. 코드는 이 항목들을 확인하지 못하므로 스스로 지킨다]\n"
            + "\n".join(lines))


def review_checklist():
    """AI 점검 프롬프트에 넣는 점검표(짧게)."""
    q = rules()
    by = {r["id"]: r for r in q["rules"]}
    lines = [_fmt(by[i], with_examples=False) for i in q["reviewFocus"] if i in by]
    return "\n".join(lines)


def _sector_card():
    ex = _load("examples/item_example.json")
    return {
        "id": "ex_sector_judge",
        "domain": ex.get("domain", "도형과 측정"),
        "taskPatterns": ["judge_claim", "context_compute_judge"],
        "situation": "부채꼴 모양 조각의 호의 길이와 넓이를 구한 뒤, 친구의 주장(반지름이 2배이면 넓이도 2배)이 옳은지 판단한다.",
        "learn": ["값 구하기(4점) 뒤에 주장 판단(6점)을 두고, 판단 소문항의 채점 요소를 '넓이 구하기'와 '판단과 근거 설명하기'로 나눈다."],
        "content": {k: ex[k] for k in CONTENT_KEYS},
    }


def cards():
    return _load("examples/guide_examples_math1.json")["cards"] + [_sector_card()]


def pick_examples(design, std, n=2):
    """과제 패턴·영역이 비슷한 예시 1개 + 다른 영역·패턴 예시 1개를 고른다(한 예시의 스타일에 쏠리지 않게).
    같은 성취기준에 대한 선택은 항상 같다(재현 가능)."""
    pat, dom, code = design.get("taskPattern"), std.get("domain"), std["code"]
    pool = cards()
    rot = zlib.crc32(code.encode("utf-8"))

    def key(i_c):
        i, c = i_c
        return ((3 if pat in c["taskPatterns"] else 0) + (2 if c.get("domain") == dom else 0), -((i + rot) % len(pool)))

    ordered = sorted(enumerate(pool), key=key, reverse=True)
    chosen = [ordered[0][1]]
    rest = [c for _, c in ordered[1:]]
    other = [c for c in rest if c.get("domain") != chosen[0].get("domain") and not set(c["taskPatterns"]) & set(chosen[0]["taskPatterns"])]
    other = other or [c for c in rest if c.get("domain") != chosen[0].get("domain")] or rest
    if n > 1 and other:                 # 두 번째는 성취기준마다 돌려 가며 골라 특정 예시가 대비용으로 반복되지 않게 한다
        chosen += [other[rot % len(other)]]
    return [{"예시": c["id"], "상황": c["situation"], "이 예시에서 배울 점": c["learn"], "형식": c["content"]} for c in chosen]
