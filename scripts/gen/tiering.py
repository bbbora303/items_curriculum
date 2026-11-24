"""풀이 방법의 기본/확장 판정 (선행학습 방지).

생성 AI가 스스로 붙인 tier는 믿기 어렵다(시험에서 범위 밖 풀이를 '기본'으로 표시). 그래서 풀이만 따로 판정한다.
오탐(범위 안 풀이를 확장으로 내리는 일)을 줄이는 장치:
  1. 풀이 판정 전용 호출 - 일반 점검과 분리, 입력을 풀이 본문과 범위 자료로 좁힌다.
  2. 기본값은 '범위 안'. 중2·3 주제 목록에 있는 개념이 풀이에 꼭 필요하고 자료로 설명되지 않을 때만 지적한다.
  3. 근거 인용 - 풀이 본문의 구절을 그대로 인용하고 주제를 목록에서 골라야 한다. 코드가 인용이 본문에 있는지, 주제가 목록값인지 확인한다.
  4. 2단계 확인 - 지적된 풀이만 '중1 자료 어디에서 설명되는지 찾아보라'며 반박을 시킨다. 설명되면 취소한다.
  5. 안전장치 - 3점 이상 소문항에 기본 풀이가 하나도 남지 않게 되면 내리지 않고 재작성(심각)으로 보낸다.
내린 풀이에는 tierNote(근거 인용·이유)를 남겨 교사가 확인하고 되돌릴 수 있게 한다.
"""
import json
import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import scope_check  # noqa: E402


def js(x):
    return json.dumps(x, ensure_ascii=False)


def _norm(s):
    return re.sub(r"\s+", "", str(s))


def method_payload(item):
    """풀이마다 이름·요약·예시답안 본문(소문항별)을 모은다."""
    out = []
    for m in item.get("solutionMethods", []):
        texts = []
        for a in item.get("modelAnswers", []):
            for x in a.get("methods", []):
                if x.get("methodId") == m.get("id"):
                    texts.append(f"[{a.get('subNo')}] {x.get('text', '')}"[:1100])
        out.append({"id": m.get("id"), "name": m.get("name"), "summary": m.get("summary"), "tier": m.get("tier", "기본"), "answers": texts})
    return out


def _material(item):
    gm = item.get("generationMeta") or {}
    book = gm.get("textbook")
    code = item["standardCodes"][0]
    parts = [scope_check.prompt_block(code, book if book not in (None, "none") else None, compact_other=False, include_style=False)]
    if book not in (None, "none"):
        core = scope_check._core(code, book) or {}
        sts = core.get("statements", [])
        if sts:
            parts.append("[교과서가 이 단원에서 제시한 성질·공식·풀이 방법]\n" + "\n".join(f"- ({s['type']}) {s['text']}" for s in sts))
        ps = core.get("passages", [])
        if ps:
            parts.append("[교과서 설명 원문 발췌]\n" + "\n".join(f"- {p['text']}" for p in ps))
    return "\n".join(p for p in parts if p)


def _stage1_prompt(item, payload):
    return f"""한국 중학교 1학년 수학 서술형 문항의 풀이 방법들이 중1 범위 안인지 판정합니다. 선행학습 방지가 목적입니다.
성취기준 [{item['standardCodes'][0]}] {item.get('intent', '')}

[범위 자료]
{_material(item)}

[상위 학년 주제 목록(태그 후보): {js(scope_check.later_tags())}]

[판정할 풀이]
{js(payload)}

규칙:
- 기본값은 **범위 안**이다. 의심만으로는 지적하지 않는다.
- 지적하려면 (a) 풀이의 어떤 단계가 위 '상위 학년 주제 목록' 중 한 주제의 개념·공식·기법을 꼭 필요로 하고, (b) 범위 자료(성취기준 해설, 교과서 진술·설명 원문, 전제 용어, 초등 주제)로는 그 단계를 설명할 수 없어야 한다.
- 식 정리, 그림 이용, 직접 세기·대입·약분 같은 일반적인 변형은 범위 안이다. 풀이가 교과서와 다른 방법이어도 중1 개념만 쓰면 범위 안이다.
- 지적하는 풀이는 quote에 **풀이 본문(summary 또는 answers)에 실제로 있는 구절을 그대로** 인용하고, laterTag에 위 목록의 값을 정확히 쓴다.
- explainedByMaterial: 범위 자료 중 이 단계를 설명할 수 있는 항목이 있으면 그 내용을 쓴다(있으면 범위 안으로 본다). 없으면 빈 문자열.
출력 JSON: {{"methods":[{{"id":"M1","needsLaterGrade":false,"laterTag":"","quote":"","reason":"","explainedByMaterial":""}}]}}  (모든 풀이를 한 항목씩)"""


def _stage2_prompt(item, flagged, payload):
    pm = {p["id"]: p for p in payload}
    claims = [{"id": f["id"], "claim": f"이 풀이는 '{f['quote']}' 때문에 {f['laterTag']}에서 배우는 내용이 필요하다", "method": pm.get(f["id"])} for f in flagged]
    return f"""앞선 판정이 아래 풀이를 '상위 학년 내용이 필요하다'고 지적했습니다. 당신은 **반박 담당**입니다. 이 단계가 아래 범위 자료만으로 설명될 수 있는지 최선을 다해 찾아보세요.

[범위 자료]
{_material(item)}

[지적 내용과 풀이]
{js(claims)}

- 인용된 단계가 중1(또는 초등) 개념과 범위 자료의 항목만으로 설명·계산되면 explainable=true로 하고 where에 해당 항목·개념을 쓴다.
- 정말로 상위 학년의 개념·공식(예: 경우의 수 조합, 닮음비, 피타고라스 정리, 일차함수 그래프)이 필요하면 explainable=false.
출력 JSON: {{"methods":[{{"id":"M2","explainable":false,"where":""}}]}}"""


def classify(call, cl, usage, model, item):
    """[{id, laterTag, quote, reason}] - 2단계를 모두 통과한 지적만 돌려준다. tier가 이미 '확장'인 풀이는 건너뛴다."""
    payload = method_payload(item)
    todo = [p for p in payload if p["tier"] != "확장"]
    if not todo:
        return []
    r1 = call(cl, usage, "풀이판정", _stage1_prompt(item, todo), model, 12000)
    tags = set(scope_check.later_tags())
    bodies = {p["id"]: _norm(p["name"] + p["summary"] + "".join(p["answers"])) for p in todo}
    flagged = []
    for x in r1.get("methods", []):
        if not x.get("needsLaterGrade") or x.get("explainedByMaterial"):
            continue
        if x.get("laterTag") not in tags or x.get("id") not in bodies:
            continue
        if not x.get("quote") or _norm(x["quote"]) not in bodies[x["id"]]:        # 인용이 본문에 없으면 근거 없는 지적으로 버린다
            continue
        flagged.append({"id": x["id"], "laterTag": x["laterTag"], "quote": x["quote"], "reason": x.get("reason", "")})
    if not flagged:
        return []
    r2 = call(cl, usage, "풀이판정-반박", _stage2_prompt(item, flagged, todo), model, 12000)
    refuted = {x.get("id") for x in r2.get("methods", []) if x.get("explainable")}
    return [f for f in flagged if f["id"] not in refuted]


def _apply_one(it, flag):
    for m in it.get("solutionMethods", []):
        if m.get("id") == flag["id"]:
            m["tier"] = "확장"
            m["extendedTag"] = flag["laterTag"]
            m["tierNote"] = {"by": "AI 점검", "quote": flag["quote"], "reason": flag["reason"]}
    it["solutionMethods"] = sorted(it.get("solutionMethods", []), key=lambda m: m.get("tier", "기본") == "확장")      # 기본 풀이가 앞(안정 정렬)


def apply(items, flags):
    """items: 같은 문항의 사본들(템플릿, 숫자가 채워진 문항). 반환 (바꾼 풀이 id 목록, 막힌 풀이 목록).
    3점 이상 소문항에 기본 풀이가 남지 않게 되는 풀이는 바꾸지 않고 막힌 목록으로 돌려준다(재작성 대상)."""
    changed, blocked = [], []
    base = items[0]
    tier = {m["id"]: m.get("tier", "기본") for m in base.get("solutionMethods", [])}
    for f in flags:
        trial = dict(tier)
        trial[f["id"]] = "확장"
        bad = []
        for q in base.get("subQuestions", []):
            if q.get("maxScore", 0) < 3:
                continue
            ms = next((a.get("methods", []) for a in base.get("modelAnswers", []) if a.get("subNo") == q.get("no")), [])
            if ms and not any(trial.get(m.get("methodId"), "기본") == "기본" for m in ms):
                bad.append(q.get("no"))
        if bad:
            blocked.append({**f, "subNos": bad})
            continue
        tier = trial
        changed.append(f["id"])
        for it in items:
            if it is not None:
                _apply_one(it, f)
    return changed, blocked


def blocked_issue(b):
    return {"severity": "심각", "rule": "SCOPE", "where": f"{b['id']} ({', '.join(b['subNos'])})",
            "problem": f"풀이 {b['id']}가 '{b['quote']}' 때문에 {b['laterTag']}에서 배울 내용을 필요로 하는데, 이것을 빼면 {', '.join(b['subNos'])}에 기본 풀이가 남지 않는다.",
            "suggestion": "해당 소문항에 중1 범위의 개념만으로 풀 수 있는 기본 풀이를 새로 쓰고 tier를 '기본'으로 표시한다. 기존 풀이는 tier '확장'과 extendedTag를 붙여 남겨도 된다."}
