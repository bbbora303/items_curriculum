"""중1 범위 검사와 프롬프트 블록. 교과서를 고르면 그 책 기준, 고르지 않으면(미선택) 책에 치우치지 않는 중립 기준.

데이터: data/grade_scope_math1.json  (common=책과 무관한 범위, books[id]=책별 용어·단원)
        data/textbook_registry.json  (화면에서 고를 수 있는 교과서 목록)

- 미선택(book=None): 성취기준 해설 + 중2·3 주제 금지만 쓴다. 특정 책의 용어 목록은 넣지 않는다.
  교과서에서만 확인된 제한(예: 지수 0)은 재작성을 요구하지 않는 참고 경고(W12)로만 표시한다.
- 교과서 선택: 위에 더해 그 책의 새 용어·전제 용어·초등 선행 주제를 안내하고, 그 책이 다루지 않는 것(notCovered)을 W11로 검사한다.
- scan_item(item)은 문항의 generationMeta.textbook으로 모드를 정한다(다시 쓰기·숫자 바꾸기 문항도 같은 모드).
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CACHE = {}


def _read(rel):
    p = os.path.join(ROOT, rel)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def load():
    if "d" not in _CACHE:
        d = _read("data/grade_scope_math1.json")
        if d:
            for t in d["common"]["triggers"]:
                t["_re"] = re.compile(t["pattern"])
        _CACHE["d"] = d
    return _CACHE["d"]


def _standards():
    if "s" not in _CACHE:
        _CACHE["s"] = {s["code"]: s for s in (_read("data/standards.json") or {"standards": []})["standards"]}
    return _CACHE["s"]


def registry():
    return (_read("data/textbook_registry.json") or {"books": []})["books"]


def available_books():
    """화면의 선택 목록용: [{id, label, available}] — 분석이 끝난 책(범위 파일에 있는 책)만 available."""
    d = load() or {"books": {}}
    return [{"id": b["id"], "label": b["label"], "available": b["id"] in d["books"]} for b in registry()]


def label_of(book):
    for b in registry():
        if b["id"] == book:
            return b["label"]
    return book


def norm_book(book):
    """'', 'none', None → None(미선택). 분석되지 않은 책 id는 오류."""
    if not book or book == "none":
        return None
    d = load()
    if not d or book not in d["books"]:
        raise ValueError(f"분석 자료가 없는 교과서: {book}")
    return book


def book_of(item):
    try:
        return norm_book((item.get("generationMeta") or {}).get("textbook"))
    except ValueError:
        return None


def later_tags():
    """확장 풀이에 붙일 수 있는 태그 목록: '중2 · 경우의 수와 확률' 꼴(중2·3 주제 목록 기준)."""
    d = load()
    return [f"{x['grade']} · {x['item']}" for x in d["common"]["laterTopics"]] if d else []


def tag_label(tag):
    """'중2 · 경우의 수와 확률' -> '중2 경우의 수와 확률 단원에서 배울 내용'"""
    return tag.replace(" · ", " ") + " 단원에서 배울 내용"


def extended_ids(item):
    return {m.get("id") for m in item.get("solutionMethods", []) if m.get("tier") == "확장"}


def _texts(item):
    """(위치, 글) 목록. 출제 의도(intent)는 제외한다. 확장 풀이(상위 학년 내용을 쓰는 풀이로 표시된 것)의 설명·예시답안은 범위 검사에서 제외한다."""
    ext = extended_ids(item)
    out = [("제시문", item.get("stimulus", {}).get("text", ""))]
    for t in item.get("stimulus", {}).get("tables", []) or []:
        out.append(("표", " ".join(str(c) for r in t.get("rows", []) for c in r) + " " + " ".join(map(str, t.get("headers", [])))))
    for q in item.get("subQuestions", []):
        no = q.get("no", "?")
        out.append((f"{no} 발문", q.get("prompt", "")))
        for c in q.get("conditions", []) or []:
            out.append((f"{no} 조건 {c.get('id')}", c.get("text", "")))
        for e in q.get("evaluationElements", []):
            out.append((f"{no} 평가 요소", e.get("text", "")))
            for se in e.get("scoringElements", []):
                out.append((f"{no} 채점 요소", se.get("text", "")))
                for lv in se.get("levels", []):
                    out.append((f"{no} 수준 {lv.get('score')}점", " ".join(lv.get("descriptors", []))))
    for m in item.get("solutionMethods", []):
        if m.get("id") not in ext:
            out.append(("풀이 방법", f"{m.get('name', '')} {m.get('summary', '')}"))
    for a in item.get("modelAnswers", []):
        for m in a.get("methods", []):
            if m.get("methodId") in ext:
                continue
            out.append((f"{a.get('subNo')} 예시답안", m.get("text", "")))
    for k in ("scoringNotes", "feedbackNotes"):
        for x in item.get(k, []) or []:
            out.append((k, x))
    for t in item.get("teacherChecks", []) or []:
        out.append(("교사 확인 사항", t.get("text", "")))
    return out


def scan_item(item, book="auto"):
    """[(경고 코드, 금지어 이름, 학년, 위치, 걸린 글 조각)].
    W11 = 중1 밖임이 성취기준으로 확인됐거나, 선택한 교과서가 다루지 않는다고 확인된 표현(재작성 요구).
    W12 = 교과서에서만 확인된 제한이고 교과서를 고르지 않았을 때(참고, 재작성 요구 안 함)."""
    d = load()
    if not d or item.get("grade") != 1:
        return []
    b = book_of(item) if book == "auto" else norm_book(book)
    not_covered = set(d["books"][b]["notCovered"]) if b else set()
    hits, seen = [], set()
    for where, txt in _texts(item):
        for t in d["common"]["triggers"]:
            m = t["_re"].search(txt)
            if not m or (t["name"], where) in seen:
                continue
            seen.add((t["name"], where))
            code = "W11" if (t["basis"] == "standard" or t["name"] in not_covered) else "W12"
            a, z = max(0, m.start() - 12), min(len(txt), m.end() + 12)
            hits.append((code, t["name"], t["grade"], where, txt[a:z].replace("\n", " ")))
    return hits


_TERMS_CACHE = {}


def _nz(x):
    return re.sub(r"[\s·,()]", "", str(x))


def _defined_terms(book):
    """분석이 끝난 책이 새로 정의하는 개념 용어(공백 제거)."""
    if book not in _TERMS_CACHE:
        g = _read(f"data/grade1_terms_{book}.json") or {}
        _TERMS_CACHE[book] = {_nz(t["term"]) for t in g.get("defined", []) if t.get("termLabel") in ("", "개념용어")}
    return _TERMS_CACHE[book]


def _allowed_text(book, std_code):
    """이 책이 쓰는 말 전체: 모든 단원의 새 용어·전제 용어·초등 주제 + 이 성취기준의 학습 목표·교과서 진술·설명 원문(공백 제거)."""
    d = load()
    parts = []
    for c in d["books"][book]["chapters"].values():
        parts += c["newTerms"] + c["assumedTerms"]
    parts += d["books"][book].get("priorTopics", [])
    parts += list(_defined_terms(book))
    core = _core(std_code, book) or {}
    parts += core.get("goals", []) + [s["text"] for s in core.get("statements", [])] + [p["text"] for p in core.get("passages", [])]
    return _nz(" ".join(parts))


def term_leaks(item):
    """교과서를 고른 문항에서, 분석된 다른 책은 새로 정의하지만 선택한 책은 쓰지 않는 용어를 쓴 곳.
    [(용어, 위치)] - 확장 풀이로 표시된 풀이는 제외. 미선택이면 빈 목록(어느 책의 용어든 허용)."""
    b = book_of(item)
    d = load()
    if not b or not d:
        return []
    others = [(x["id"] if isinstance(x, dict) else x) for x in available_books()]
    others = [x for x in others if x != b]
    master = set()
    for o in others:
        master |= _defined_terms(o)
    mine = _defined_terms(b)
    allowed = _allowed_text(b, (item.get("standardCodes") or [""])[0])
    out, seen = [], set()
    for where, txt in _texts(item):
        if where in ("교사 확인 사항", "scoringNotes", "feedbackNotes"):
            continue
        tx = _nz(re.sub(r"\$[^$]*\$", " ", txt))
        for term in master:
            if len(term) < 4 or term in seen or term not in tx:        # 3글자 이하는 일반어와 겹쳐 오탐이 많아 제외
                continue
            if term in mine or term in allowed:
                continue
            parts = [w for w in re.split(r"의|과|와|및|을|를", term) if len(w) >= 2]
            if parts and all(w in allowed for w in parts):           # '원기둥의 부피'처럼 선택한 책이 '원기둥'과 '부피'를 따로 쓰는 말 묶음은 누수가 아니다
                continue
            seen.add(term)
            out.append((term, where))
    return out


def basis_mismatch(item):
    """풀이가 인용한 교과서 근거(textbookItems)가 틀렸는지: 목록에 없는 번호, 또는 인용한 진술과 낱말이 하나도 겹치지 않음. [(풀이 id, 이유)]"""
    gm = item.get("generationMeta") or {}
    b = book_of(item)
    if not b or not gm.get("textbookBasisOffered"):
        return []
    snap = gm.get("textbookBasisList")                 # 생성 때 실제로 보여 준 목록(교과서 자료를 다시 만들어도 번호가 어긋나지 않게 저장해 둔다)
    if not snap:                                          # 목록 저장 전에 만든 예전 문항은 번호가 지금 목록과 다를 수 있어 검사하지 않는다
        return []
    sts = [{"text": x} for x in snap]
    out = []
    for m in item.get("solutionMethods", []):
        if m.get("tier") == "확장" or not m.get("textbookItems"):
            continue
        bad = [i for i in m["textbookItems"] if not isinstance(i, int) or not (0 < i <= len(sts))]
        if bad:
            out.append((m.get("id"), f"없는 근거 번호 {bad} (목록은 1~{len(sts)})"))
            continue
        body = " ".join([str(m.get("name", "")), str(m.get("summary", ""))] + [x.get("text", "") for a in item.get("modelAnswers", []) for x in a.get("methods", []) if x.get("methodId") == m.get("id")])
        bt = set(re.findall(r"[가-힣]{2,}", re.sub(r"\$[^$]*\$", " ", body)))
        ct = set(re.findall(r"[가-힣]{2,}", " ".join(sts[i - 1]["text"] for i in m["textbookItems"])))
        # 조사만 다른 낱말도 겹친 것으로 본다(앞 두 글자 기준)
        if bt and ct and not ({w[:2] for w in bt} & {w[:2] for w in ct}):
            out.append((m.get("id"), "인용한 교과서 진술과 풀이 본문이 낱말 하나도 겹치지 않음"))
    return out


def style_block(std_code, book):
    """교과서를 고른 경우에만: 그 책의 정의 문장·소재·발문 표현·서술형 문제 원문 예(어투 참고). 자료가 없으면 빈 문자열."""
    b = norm_book(book)
    if not b:
        return ""
    st = _read(f"data/textbook_style/{b}.json")
    d = load()
    if not st or not d:
        return ""
    mine = [t for t, c in d["books"][b]["chapters"].items() if std_code in c["standards"]]
    chs = [st["chapters"][t] for t in mine if t in st["chapters"]]
    if not chs:
        return ""
    lines = [f"[교과서 문체·소재 참고 - '{label_of(b)}'. 표현·어투·형식만 참고하고, 문제의 내용·숫자·소재는 그대로 복사하지 않는다]"]
    defs = [f"{x['term']}: {x['definition'][:70]}" for c in chs for x in c["definitions"]][:18]
    if defs:
        lines.append("- 이 단원의 교과서 용어 정의(용어를 풀어 쓸 때 이 뜻과 표현을 따른다): " + " / ".join(defs))
    ctx = [x for c in chs for x in c["contexts"]][:10]
    if ctx:
        lines.append("- 이 교과서가 이 단원에서 쓰는 소재(비슷한 성격의 새 소재를 쓴다): " + ", ".join(ctx))
    if st.get("verbs"):
        lines.append("- 교과서 발문 표현(자주 쓰는 순서): " + ", ".join(st["verbs"][:10]) + " (소문항 발문은 '~시오.'로 끝낸다)")
    essay = [x for c in chs for x in c["essaySamples"]][:3]
    if essay:
        tag = "이 교과서의 서술형 문제 원문 예(이 단원, 어투·길이만 참고)"
    else:
        pool = st.get("bookEssaySamples", [])
        essay = pool[:: max(1, len(pool) // 2)][:2] if pool else []
        tag = "이 교과서의 서술형 문제 원문 예(다른 단원, 어투·길이만 참고)"
    for i, x in enumerate(essay, 1):
        lines.append(f"- {tag} {i}) {x['text'][:170]}")
    for x in [x for c in chs for x in c["activitySamples"]][:1]:
        steps = " / ".join(x["steps"][:3])
        lines.append(f"- 이 교과서의 활동 서술 방식 예: {x['title']} - {x['text'][:100]}" + (f" (순서: {steps})" if steps else ""))
    if _standards().get(std_code, {}).get("domain") == "자료와 가능성":
        for x in [x for c in chs for x in c["tableSamples"]][:1]:
            rows = "; ".join(" | ".join(str(c) for c in r) for r in x["rows"][:3])
            lines.append(f"- 이 교과서의 자료(표) 예: {x.get('caption')} ({x.get('unit')}) {rows} ... {x.get('source') or ''} - 자료의 크기·자릿수·단위·출처 표기 방식만 참고해 새 자료를 만든다")
    return "\n".join(lines)


def hints_block(std_code):
    """성취기준별로 알려진 함정 안내(data/standard_hints_math1.json). 없으면 빈 문자열."""
    d = _read("data/standard_hints_math1.json") or {}
    hs = d.get("hints", {}).get(std_code, [])
    if not hs:
        return ""
    return "[이 성취기준에서 반복해 나온 함정 - 반드시 지킨다]\n" + "\n".join(f"- {h['text']}" for h in hs)


def _core(std_code, book):
    b = norm_book(book)
    if not b:
        return None
    c = _read(f"data/textbook_style/{b}_core.json")
    return (c or {}).get("standards", {}).get(std_code)


_SKIP_THEME = ("알지오매스", "공학", "수학 집", "프로젝트", "수학과", "대화", "활동", "코너", "비유", "캐릭터")


def theme_candidates(std_code, book):
    """선택한 교과서가 이 성취기준의 단원에서 쓰는 소재 중 문항 배경으로 쓸 만한 것(빈도 순, 괄호 설명 제거)."""
    b = norm_book(book)
    st = _read(f"data/textbook_style/{b}.json") if b else None
    d = load()
    if not st or not d:
        return []
    mine = [t for t, c in d["books"][b]["chapters"].items() if std_code in c["standards"]]
    out = []
    for t in mine:
        for x in (st["chapters"].get(t) or {}).get("contexts", [])[:14]:
            x = re.sub(r"\(.*?\)", "", x).strip()
            if x and not any(k in x for k in _SKIP_THEME) and x not in out:
                out.append(x)
    return out


def pick_themes(std_code, book, seed=1, n=3):
    """시드로 소재 후보 n개를 정한다(같은 시드·책이면 같은 후보). 코드가 고르므로 책마다 소재가 달라진다."""
    c = theme_candidates(std_code, book)
    if not c:
        return []
    k = min(n, len(c))
    start = (seed * 7 + sum(ord(ch) for ch in std_code)) % len(c)
    return [c[(start + i * 3) % len(c)] for i in range(k)]


def theme_block(std_code, book, seed=1, chosen=None, no_fit=False):
    th = pick_themes(std_code, book, seed)
    if not th:
        return ""
    if no_fit:                           # G1(설계)이 '숫자 규칙(명세)의 상황과 어느 후보도 맞지 않는다'고 판단했다: 명세의 상황을 우선한다
        return (f"[소재 후보 해제 - 선택한 교과서 '{label_of(norm_book(book))}'의 소재 후보({', '.join(th)})는 이 문항의 숫자 규칙이 가정하는 상황과 맞지 않는다고 설계 단계가 판단했다] "
                "후보 소재를 억지로 쓰지 말고, 숫자 규칙이 가정하는 상황에 자연스러운 일상 소재를 쓴다. 등장인물 이름은 다양하게 정한다(지민·현우 같은 이름을 습관적으로 쓰지 않는다).")
    if chosen and chosen in th:          # G1(설계)이 이미 소재를 정했다: 제시문은 그 소재로 쓴다
        return (f"[소재 확정 - 선택한 교과서 '{label_of(norm_book(book))}'가 이 단원에서 쓰는 소재] 설계 단계에서 제시문의 배경 소재를 '{chosen}'로 정했다. 제시문은 이 소재로 쓰고 소재의 이름을 제시문에 구체적으로 드러낸다. "
                "등장인물 이름은 소재에 어울리게 다양하게 정한다(지민·현우 같은 이름을 습관적으로 쓰지 않는다).")
    return (f"[소재 지정 - 선택한 교과서 '{label_of(norm_book(book))}'가 이 단원에서 쓰는 소재] 제시문의 배경 소재는 다음 후보 중 이 수학 내용에 가장 자연스러운 하나를 반드시 고른다: "
            + ", ".join(th) + ". 어느 것도 수학적으로 맞지 않을 때만 비슷한 성격의 다른 소재를 쓴다. 후보 소재의 이름을 제시문에 구체적으로 드러내고, 등장인물 이름은 소재에 어울리게 다양하게 정한다(지민·현우 같은 이름을 습관적으로 쓰지 않는다).")


def goals_block(std_code, book):
    """G0(평가 요소 도출)용: 선택한 교과서가 이 성취기준 단원에 제시한 학습 목표. 미선택이거나 자료가 없으면 빈 문자열."""
    c = _core(std_code, book)
    if not c or not c["goals"]:
        return ""
    return (f"[선택한 교과서 '{label_of(norm_book(book))}'의 학습 목표 - 평가 요소 후보는 가능하면 이 목표 중에서 고르거나 이 목표를 쪼개고 합쳐 만든다. "
            "목표에 없는 내용을 평가 요소로 삼지 않는다]\n" + "\n".join(f"- {g}" for g in c["goals"][:12]))


def basis_block(std_code, book):
    """G3(예시답안)용: 교과서가 이 단원에서 제시한 성질·공식·법칙·정의·풀이 방법. 예시답안은 이것을 근거·방법으로 쓴다."""
    c = _core(std_code, book)
    if not c or not c["statements"]:
        return ""
    lines = [f"[선택한 교과서 '{label_of(norm_book(book))}'가 이 단원에서 제시한 성질·공식·풀이 방법 - 예시답안의 근거와 풀이 방법은 가능하면 이 목록에서 가져온다. "
             "방법 1은 교과서의 '계산·풀이 방법'을 따르고, 풀이에서 쓴 성질·공식은 이 목록의 표현을 쓴다. "
             "목록에 없는 성질·공식을 새로 끌어 쓰지 않는다. 예시답안을 쓴 뒤 출력 JSON의 textbookBasis에 실제 쓴 항목 번호를 적는다]"]
    for i, s in enumerate(c["statements"], 1):
        lines.append(f"{i}. ({s['type']}{', 이미 배운 내용' if s.get('assumed') else ''}) {s['text']}" + (f"  [{s['latex']}]" if s.get("latex") and s["latex"] != s["text"] else ""))
    ps = c.get("passages") or []
    if ps:
        lines.append("교과서 설명 원문 발췌(설명 순서·표현을 따를 때 참고하고, 문장을 그대로 베끼지 않는다):")
        lines += [f"- ({x['section']}) {x['text']}" for x in ps[:4]]
    return "\n".join(lines)


def prompt_block(std_code, book=None, compact_other=True, include_style=True):
    """생성·점검 프롬프트에 넣는 범위 안내. book=None이면 중립(교과서 용어 목록 없음)."""
    d = load()
    if not d:
        return ""
    std = _standards().get(std_code, {})
    comm = (std.get("commentary") or "").strip()
    b = norm_book(book)
    later = ", ".join(f"{x['item']}({x['grade']})" for x in d["common"]["laterTopics"])
    if b is None:
        lines = ["[중1 범위 - 교육과정 수준(교과서 미선택). 이 범위를 벗어난 수학 내용은 쓰지 않는다]",
                 f"- 성취기준 해설·제한 사항: {comm or '(없음)'}",
                 f"- 중2·중3에서 배우는 주제(쓰지 않는다): {later}",
                 "- 특정 출판사의 용어·표기·소재에 치우치지 말고, 교육과정 성취기준과 해설에 나오는 용어를 쓴다. 성취기준 해설이 다루지 않는다고 한 내용은 쓰지 않는다."]
        return "\n".join(lines)
    bk = d["books"][b]
    mine = [t for t, c in bk["chapters"].items() if std_code in c["standards"]]
    lines = [f"[중1 범위 - 선택한 교과서 '{label_of(b)}'의 분석에서 확인한 것. 이 범위를 벗어난 수학 내용은 쓰지 않는다]",
             f"- 성취기준 해설·제한 사항: {comm or '(없음)'}"]
    for t in mine:
        c = bk["chapters"][t]
        subs = ", ".join(s["title"] for s in c["subUnits"] if std_code in s["standards"]) or t
        lines.append(f"- 이 성취기준의 단원: {t} ({subs})")
        lines.append(f"  이 단원에서 새로 배우는 용어: {', '.join(c['newTerms'])}")
        if c["assumedTerms"]:
            lines.append(f"  이미 배운 것으로 전제하는 용어: {', '.join(c['assumedTerms'][:60])}")
    if compact_other:
        others = [f"{t}: {', '.join(c['newTerms'][:25])}" for t, c in bk["chapters"].items() if t not in mine and c["newTerms"]]
        lines.append("- 이 교과서의 다른 단원에서 배우는 용어(참고, 이 성취기준과 관련될 때만 쓴다): " + " / ".join(others))
    lines.append(f"- 초등학교에서 배운 주제: {', '.join(bk['priorTopics'])}")
    lines.append(f"- 중2·중3에서 배우는 주제(쓰지 않는다): {later}")
    if "지수 0" in bk["notCovered"]:
        lines.append("- 이 교과서는 지수가 0인 거듭제곱을 다루지 않는다(지수가 1인 거듭제곱까지만 정의). 쓰지 않는다.")
    lines.append("- 위 목록에 없는 수학 용어·기호·성질을 새로 끌어 쓰지 말고, 필요하면 이 교과서의 용어로 풀어 쓴다.")
    if include_style:
        sb = style_block(std_code, b)
        if sb:
            lines.append(sb)
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        it = json.load(open(p, encoding="utf-8"))
        print(p, scan_item(it))
