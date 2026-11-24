"""교과서의 문체·소재 자료(data/textbook_style/<책 id>.json)를 만든다 (API 호출 없음).

교과서를 고르면 문항 생성(G2·G3)에 들어가는 자료다:
- 단원별 정의 문장(용어 정의의 표현을 교과서와 맞춤), 단원별 소재, 교과서 발문 표현(지시어)
- 교과서 서술형 문제 원문(어투·길이 참고), 활동 원문 예, 통계 단원의 표 자료 예
입력: pages/*.json(쪽 분석), transcripts/*.json(원문 전사), summary.json, grade1_terms_<책>.json
사용: python build_style.py [--book 천재(김동재)]
"""
import argparse
import collections
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(HERE))
import books  # noqa: E402
ROOT = HERE.parents[1]
DATA = ROOT / "data"


def load_dir(d):
    out = {}
    for f in sorted(d.glob("p*.json")):
        j = json.load(open(f, encoding="utf-8"))
        out[j["_page"]] = j
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    a = ap.parse_args()
    bk = books.resolve(a.book)
    a.book, bid = bk["unitsKey"], bk["id"]      # --book은 id·차례 이름 모두 받는다
    base = DATA / "textbook_analysis" / bid
    summ = json.load(open(base / "summary.json", encoding="utf-8"))
    g = json.load(open(DATA / f"grade1_terms_{bid}.json", encoding="utf-8"))
    trans = load_dir(base / "transcripts") if (base / "transcripts").exists() else {}
    page_ch = {p: t for t, c in summ["chapters"].items() for p in c["pages"]}

    # 발문 표현: '~시오'(문제)와 '~보자'(활동) 형태만, 빈도 순
    verbs = [(v, n) for v, n in summ["verbs"].items() if re.search(r"(시오|보자)$", v) and len(v) <= 8]
    verbs = [v for v, n in sorted(verbs, key=lambda x: -x[1])][:14]

    chapters = {}
    for t, c in summ["chapters"].items():
        defs = [{"term": x["term"], "definition": x["definition"]} for x in g["defined"]
                if x["chapter"] == t and x.get("termLabel") in ("", "개념용어") and x.get("definition")]
        ctx = [k for k, n in c["contexts"].items() if 2 <= len(k) <= 24][:12]
        chapters[t] = {"definitions": defs, "contexts": ctx, "essaySamples": [], "activitySamples": [], "tableSamples": []}
    book_essay = []
    for n, tr in trans.items():
        t = page_ch.get(n)
        for it in tr.get("items", []):
            txt = (it.get("text") or "").strip()
            if it.get("kind") == "서술형문제" and len(txt) >= 25 and not re.match(r"^\[\d", txt):        # '[17~19] 다음 문제의 풀이 과정을…' 같은 안내 문구는 문제가 아니다
                row = {"page": n, "label": it.get("label"), "text": txt, "subItems": [x.get("text", "") for x in it.get("subItems", [])][:4]}
                book_essay.append({**row, "chapter": t})
                if t in chapters:
                    chapters[t]["essaySamples"].append(row)
            elif (it.get("kind") == "활동" and len(it.get("steps") or []) >= 2 and t in chapters and len(chapters[t]["activitySamples"]) < 2
                  and not re.search(r"Math ?(Pizza|Heart|Road)|자기|느낀|복습|QR", f"{it.get('label', '')} {txt}")):       # 자기평가·복습 안내는 수학 활동이 아니다
                chapters[t]["activitySamples"].append({"page": n, "title": it.get("label"), "text": txt[:300], "steps": [s[:120] for s in it.get("steps", [])][:5]})
        for tb in tr.get("tables", []):
            if t in chapters and tb.get("rows") and len(chapters[t]["tableSamples"]) < 2:
                chapters[t]["tableSamples"].append({"page": n, "caption": tb.get("caption"), "unit": tb.get("unit"), "headers": tb.get("headers"), "rows": tb["rows"][:8], "source": tb.get("source")})
    out = {"_note": f"{a.book}의 문체·소재 자료. 교과서를 선택했을 때만 G2·G3 프롬프트에 들어간다(scope_check.style_block).",
           "book": a.book, "verbs": verbs, "chapters": chapters, "bookEssaySamples": book_essay}
    (DATA / "textbook_style").mkdir(exist_ok=True)
    (DATA / "textbook_style" / f"{bid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"발문 표현 {len(verbs)}개: {verbs}")
    print(f"서술형 문제 원문 {len(book_essay)}개(전사 쪽 {len(trans)}쪽)")
    for t, c in chapters.items():
        print(f"  {t}: 정의 {len(c['definitions'])}, 소재 {len(c['contexts'])}, 서술형 {len(c['essaySamples'])}, 활동 {len(c['activitySamples'])}, 표 {len(c['tableSamples'])}")


if __name__ == "__main__":
    main()
