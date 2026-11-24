"""쪽별 교과서 분석(pages/*.json)을 단원별로 종합한다 (API 호출 없음).

사용: python aggregate.py [--book 천재(김동재)]
결과: data/textbook_analysis/<id>/summary.json, data/grade1_terms_<id>.json(중1 용어 목록), docs/교과서분석_<id>.md(읽는 보고서)
쪽 단위 분석은 단원·소단원이 안 보이는 쪽이 많아, 앞 쪽의 단원을 이어받아 채운다(이어받은 쪽은 inherited 표시).
"""
import argparse
import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(HERE))
import books  # noqa: E402
sys.path.insert(0, str(HERE))
import vocab  # noqa: E402
ROOT = HERE.parents[1]
DATA = ROOT / "data"


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def match_chapter(name, titles):
    n = norm(name)
    if not n:
        return ""
    for t in titles:
        if norm(t) == n:
            return t
    for t in titles:
        if norm(t) in n or n in norm(t):
            return t
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    a = ap.parse_args()
    bk = books.resolve(a.book)
    a.book, bid = bk["unitsKey"], bk["id"]      # --book은 id·차례 이름 모두 받는다
    base = DATA / "textbook_analysis" / bid
    units = json.load(open(DATA / "textbook_units_math1.json", encoding="utf-8"))["books"][a.book]["units"]
    titles = [u["title"] for u in units]
    pages = {}
    for f in sorted((base / "pages").glob("p*.json")):
        if f.name.endswith(".error.txt"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        before = json.dumps(d, ensure_ascii=False, sort_keys=True)
        vocab.normalize_page(d)                       # kind -> statementType/exampleType/problemType/figureType (원래 값은 _raw)
        if json.dumps(d, ensure_ascii=False, sort_keys=True) != before:
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        pages[d["_page"]] = d
    errors = sorted(int(re.search(r"p(\d+)", f.name).group(1)) for f in (base / "pages").glob("*.error.txt"))
    nums = sorted(pages)

    # 1) 단원 이어받기: 이름이 대단원 목록과 맞는 쪽의 값을 뒤 쪽에 이어준다
    cur = ""
    for n in nums:
        p = pages[n]
        ch = match_chapter(p["unit"].get("chapter"), titles)
        p["_chapter"], p["_inherited"] = (ch, False) if ch else (cur, True)
        if ch:
            cur = ch
    cur = ""
    for n in nums:
        p = pages[n]
        sec = (p["unit"].get("section") or "").strip()
        if p["_inherited"] and not sec:
            p["_section"] = cur
        else:
            p["_section"] = sec or cur
        if sec:
            cur = sec

    # 2) 용어: 정의된 쪽, 사용된 쪽
    terms = {}
    for n in nums:
        p = pages[n]
        for t in p.get("terms", []):
            k = norm(t.get("term"))
            if not k:
                continue
            e = terms.setdefault(k, {"term": t["term"], "defPages": [], "usePages": [], "definition": "", "notation": "", "chapter": "", "section": ""})
            if t.get("role") == "정의":
                e["defPages"].append(n)
                if not e["definition"]:
                    e["definition"], e["notation"] = t.get("definition", ""), t.get("notation", "")
                    e["chapter"], e["section"] = p["_chapter"], p["_section"]
            else:
                e["usePages"].append(n)
    kinds_path = base / "term_kinds.json"
    kinds = json.load(open(kinds_path, encoding="utf-8"))["kinds"] if kinds_path.exists() else {}
    for v in terms.values():
        v["termLabel"] = kinds.get(v["term"], "")
    defined = {k: v for k, v in terms.items() if v["defPages"]}
    assumed = {k: v for k, v in terms.items() if not v["defPages"]}   # 이 책에서는 정의하지 않고 쓰기만 한 용어 = 앞서 배운 것으로 전제
    early_use = {k: v for k, v in defined.items() if v["usePages"] and min(v["usePages"]) < min(v["defPages"])}

    # 3) 단원별 종합
    ch = {t: {"pages": [], "terms": [], "symbols": [], "statements": [], "exampleTypes": collections.Counter(), "problemTypes": collections.Counter(),
              "problemLevels": collections.Counter(), "verbs": collections.Counter(), "contexts": collections.Counter(), "figureTypes": collections.Counter(),
              "competencies": collections.Counter(), "essayProblems": [], "selfAssessment": [], "gradeLinks": None} for t in titles}
    for n in nums:
        p = pages[n]
        c = ch.get(p["_chapter"])
        if c is None:
            continue
        c["pages"].append(n)
        c["terms"] += [{"term": t["term"], "page": n, "section": p["_section"]} for t in p.get("terms", []) if t.get("role") == "정의" and kinds.get(t["term"], "개념용어") == "개념용어"]
        c["symbols"] += [{"symbol": s["symbol"], "meaning": s.get("meaning", ""), "page": n} for s in p.get("symbols", []) if s.get("role") == "정의"]
        c["statements"] += [{"statementType": s.get("statementType"), "latex": s.get("latex"), "plain": s.get("plain"), "page": n, "section": p["_section"]} for s in p.get("statements", [])]
        for e in p.get("examples", []):
            c["exampleTypes"][e.get("exampleType", "기타")] += 1
        for q in p.get("problems", []):
            c["problemTypes"][q.get("problemType", "기타")] += 1
            c["problemLevels"][q.get("level", "")] += 1
            if q.get("verb"):
                c["verbs"][q["verb"]] += 1
            if q.get("level") == "서술형" or p.get("pageType") == "서술형문제":
                c["essayProblems"].append({"page": n, "label": q.get("label"), "verb": q.get("verb"), "problemType": q.get("problemType"), "summary": q.get("summary"), "icons": q.get("competencyIcons", [])})
        for v in p.get("verbs", []):                  # 라이트 프로필: 문제 목록 대신 쪽의 발문 지시어 목록
            c["verbs"][v] += 1
        if p.get("essay") and p.get("_profile") == "lite":
            c["essayProblems"].append({"page": n, "label": "", "verb": "", "problemType": "", "summary": "(라이트 분석: 서술형 문제가 있는 쪽, 원문은 transcribe_pages로 전사)", "icons": []})
        for x in p.get("contexts", []):
            c["contexts"][x] += 1
        for f in p.get("figures", []):
            c["figureTypes"][f.get("figureType", "기타")] += 1
        for x in p.get("competencies", []):
            c["competencies"][x] += 1
        if p.get("selfAssessment"):
            c["selfAssessment"].append({"page": n, "items": p["selfAssessment"]})
    # 학년 연결: '배울 내용'이 있는 대영역 도입 쪽만 쓰고, 그 쪽의 '이 단원의 내용'에 적힌 대단원들에 각각 붙인다
    for n in nums:
        gl = pages[n].get("gradeLinks") or {}
        if pages[n].get("pageType") == "단원도입" and gl.get("later"):
            for item in gl.get("current", []):
                t = match_chapter(item, titles) or match_chapter(item.replace("도형의 기초", "기본 도형"), titles)
                if t and ch[t]["gradeLinks"] is None:
                    ch[t]["gradeLinks"] = {"prior": gl.get("prior", []), "current": gl.get("current", []), "later": gl.get("later", []), "page": n}
    for c in ch.values():
        for k in ("exampleTypes", "problemTypes", "problemLevels", "verbs", "contexts", "figureTypes", "competencies"):
            c[k] = dict(c[k].most_common())

    # 4) 전체 통계
    verbs = collections.Counter()
    icons = collections.Counter()
    ptypes = collections.Counter(p.get("pageType") for p in pages.values())
    UNSURE = re.compile(r"불확실|읽기 어렵|읽을 수 없|보이지 않|확인할 수 없|추측|애매|판독|흐릿|가려|잘려")
    uncertain = [n for n in nums if UNSURE.search(pages[n].get("notes") or "")]
    for p in pages.values():
        for v in p.get("verbs", []):
            verbs[v] += 1
        for q in p.get("problems", []):
            if q.get("verb"):
                verbs[q["verb"]] += 1
            for i in q.get("competencyIcons", []):
                icons[i] += 1
    tot = {"statementTypes": collections.Counter(), "exampleTypes": collections.Counter(), "problemTypes": collections.Counter(), "figureTypes": collections.Counter(), "figureRoles": collections.Counter()}
    for p in pages.values():
        tot["statementTypes"].update(x.get("statementType") for x in p.get("statements", []))
        tot["exampleTypes"].update(x.get("exampleType") for x in p.get("examples", []))
        tot["problemTypes"].update(x.get("problemType") for x in p.get("problems", []))
        tot["figureTypes"].update(x.get("figureType") for x in p.get("figures", []))
        tot["figureRoles"].update(x.get("role") for x in p.get("figures", []))
    usage = {"in": sum(p["_usage"]["in"] for p in pages.values()), "out": sum(p["_usage"]["out"] for p in pages.values())}
    usage["estUSD"] = round(usage["in"] / 1e6 * 3 + usage["out"] / 1e6 * 15, 2)
    summary = {"book": a.book, "analyzedPages": len(pages), "errorPages": errors, "pageTypes": dict(ptypes), "usage": usage,
               "qualityFlags": {"notesInferredPages": sum(1 for p in pages.values() if p.get("_notesInferred")),
                                "levelSuspectProblems": sum(1 for p in pages.values() for q in p.get("problems", []) if q.get("_levelSuspect")),
                                "note": "notes의 숫자 결론은 AI 추론일 수 있어 사실 자료로 쓰지 않는다. levelSuspect는 level이 '활동'으로 분류된 일반 문제일 수 있다(값은 바꾸지 않음)."},
               "typeTotals": {k: dict(v.most_common()) for k, v in tot.items()}, "verbs": dict(verbs.most_common()), "competencyIcons": dict(icons.most_common()), "pagesWithNotes": uncertain,
               "chapters": ch, "termsDefinedCount": len(defined), "termsAssumedOnly": sorted(v["term"] for v in assumed.values())}
    (base / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")

    # 5) 중1 용어 목록 (학년 판별용). 한 권만 본 단계라 confidence=single_source
    g1 = {"_note": f"{a.book} 한 권에서 '정의'로 도입된 용어(쪽 순서). 다른 교과서와 교차확인하면 신뢰도가 올라간다. 용어가 여기 없다고 중1 밖이라는 뜻은 아니다(정의 없이 쓰는 용어는 assumed에 따로 둔다).",
          "sources": [a.book], "defined": [{"term": v["term"], "definition": v["definition"], "notation": v["notation"], "chapter": v["chapter"], "section": v["section"],
                                            "page": v["defPages"][0], "termLabel": v["termLabel"], "confidence": "single_source"} for v in sorted(defined.values(), key=lambda x: x["defPages"][0])],
          "assumedFromEarlier": sorted(v["term"] for v in assumed.values() if v["termLabel"] in ("", "개념용어")),
          "excludedLabels": {"계산주제": sorted(v["term"] for v in terms.values() if v["termLabel"] == "계산주제"), "소재·활동": sorted(v["term"] for v in terms.values() if v["termLabel"] == "소재·활동")},
          "laterGradeTopics": {t: c["gradeLinks"]["later"] for t, c in ch.items() if c["gradeLinks"] and c["gradeLinks"].get("later")},
          "priorTopics": {t: c["gradeLinks"]["prior"] for t, c in ch.items() if c["gradeLinks"] and c["gradeLinks"].get("prior")}}
    (DATA / f"grade1_terms_{bid}.json").write_text(json.dumps(g1, ensure_ascii=False, indent=1), encoding="utf-8")

    # 6) 읽는 보고서
    L = [f"# 교과서 분석 보고서: {a.book}\n", f"- 분석 쪽 {len(pages)}쪽 / 실패 {len(errors)}쪽 {errors[:10]} / 불확실 메모가 있는 쪽 {len(uncertain)}쪽 / 비용 추정 약 ${usage['estUSD']} (단가 추정)",
         f"- 쪽 유형: {dict(ptypes)}", f"- 정의된 용어 {len(defined)}개(개념용어 {sum(1 for v in defined.values() if v['termLabel'] in ('', '개념용어'))}개), 이 책에서는 정의 없이 쓰기만 한 용어(앞서 배운 것으로 전제) {len(assumed)}개, 정의 전에 먼저 쓰인 용어 {len(early_use)}개",
         f"- 문제 발문 지시어 상위: {dict(list(verbs.most_common(12)))}", f"- 역량 아이콘: {dict(icons.most_common())}\n"]
    for t in titles:
        c = ch[t]
        L.append(f"## {t}  ({len(c['pages'])}쪽)")
        gl = c["gradeLinks"]
        if gl:
            L.append(f"- 배운 내용: {', '.join(gl.get('prior', []))}  →  이 단원: {', '.join(gl.get('current', []))}  →  배울 내용: {', '.join(x['item'] + '(' + x['grade'] + ')' for x in gl.get('later', []))}")
        L.append(f"- 새로 정의된 용어({len(c['terms'])}): " + ", ".join(sorted({x['term'] for x in c['terms']})))
        L.append(f"- 새 기호({len(c['symbols'])}): " + ", ".join(f"{x['symbol']}({x['meaning']})" for x in c["symbols"][:12]))
        L.append(f"- 문제 유형(problemType): {c['problemTypes']} / 수준(level): {c['problemLevels']}")
        L.append(f"- 소재: {', '.join(list(c['contexts'])[:10])}")
        L.append(f"- 그림·표 유형(figureType): {c['figureTypes']}")
        for sa in c["selfAssessment"]:
            L.append("- 자기평가(개념↔문항): " + "; ".join(f"{i['concept']}={','.join(i['problemNos'])}" for i in sa["items"]))
        if c["essayProblems"]:
            L.append(f"- 교과서 서술형 문제 {len(c['essayProblems'])}개:")
            for e in c["essayProblems"]:
                L.append(f"    - ({e['page']}쪽 {e['label']}번, {e['problemType']}, {e['verb']}) {e['summary']}")
        L.append("")
    (ROOT / "docs" / f"교과서분석_{bid}.md").write_text("\n".join(L), encoding="utf-8")
    print(f"종합 완료: 쪽 {len(pages)}, 정의 용어 {len(defined)}, 전제 용어 {len(assumed)}, 서술형 문제 {sum(len(c['essayProblems']) for c in ch.values())}개")
    print("저장:", base / "summary.json", "|", DATA / f"grade1_terms_{bid}.json", "|", ROOT / "docs" / f"교과서분석_{bid}.md")


if __name__ == "__main__":
    main()
