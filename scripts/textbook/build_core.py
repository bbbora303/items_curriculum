"""교과서 1권의 '성취기준별 핵심 자료'를 만든다 (API 호출 없음).
  - 학습 목표(goals.json, extract_goals.py 결과)
  - 교과서가 제시한 성질·공식·법칙·정의·계산·풀이 방법 문장(쪽 분석의 statements)
결과: data/textbook_style/<id>_core.json = {standards: {코드: {goals:[...], statements:[{type,text,section,page}]}}}
G0(평가 요소)·G3(예시답안 근거)가 교과서를 고른 경우에만 읽는다 (scope_check.goals_block / basis_block).
사용: python build_core.py --book dong_a
"""
import argparse
import re
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import books  # noqa: E402
import compare_books as CB  # noqa: E402


def CB_jaccard(a, b):
    sys.path.insert(0, str(HERE.parents[0] / "tools"))
    import reflect_score as R
    return R.jaccard(a, b)

USE_PAGES = ("개념설명", "단원도입", "탐구활동", "예제", "읽기자료")
KEEP = ("성질", "공식", "법칙", "정의", "계산·풀이 방법", "정리", "원리")
LIMIT = {"성질": 8, "공식": 8, "법칙": 6, "정의": 6, "계산·풀이 방법": 8, "정리": 6, "원리": 4}


DROP = re.compile(r"알지오매스|정렬하기|ON으로|OFF|수학 집 짓기|모래 실험|활동 ?\(\d\)|말해 보는 활동|활동에 쓰임|도미노|^예제 ?\d|문제 ?\d+(\(\d\))?(의|에서)|풀이 예시|메시지를|빈칸 채우기|스마트폰|코딩|블록 쌓기")
META = re.compile(r"\s*\((?:[^()]*(?:이미|복습|전제|말풍선|풀이에서 사용|에서 사용|제시)[^()]*)\)")
ASSUMED = re.compile(r"이미|복습|전제|말풍선")


def clean_statement(txt):
    """AI 요약에 섞인 쪽 구성 설명을 정리한다. (정리한 글, 이미 배운 내용 여부) - 특정 활동·도구·예제 번호에 묶인 진술은 None으로 버린다."""
    if DROP.search(txt):
        return None, False
    assumed = bool(ASSUMED.search(" ".join(META.findall(txt)))) or bool(re.search(r"\(복습\)", txt))
    new = META.sub("", txt)
    new = re.sub(r"\(복습\)", "", new).strip()
    new = re.sub(r"\s{2,}", " ", new).strip(" .") + "."
    if len(new) < 10:
        return None, False
    return new, assumed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    a = ap.parse_args()
    bk = books.resolve(a.book)
    pages = CB.load_pages(bk["id"])
    off = CB.printed_offset(pages)
    rows = CB.sub_unit_ranges(bk["id"])
    out = collections.defaultdict(lambda: {"goals": [], "statements": []})
    stats = collections.Counter()
    gf = pathlib.Path(books.base_dir(bk["id"])) / "goals.json"
    if gf.exists():
        for g in json.load(open(gf, encoding="utf-8")):
            if g["kind"] == "학습목표":
                for s in g["standards"]:
                    if g["text"] not in out[s]["goals"]:
                        out[s]["goals"].append(g["text"])
    for n, d in sorted(pages.items()):
        if d.get("pageType") not in USE_PAGES:           # 연습문제·단원 마무리·부록·기타 쪽의 진술은 '풀이에서 사용' 같은 문제 풀이 설명이라 교과서가 가르치는 진술이 아니다
            continue
        sts = d.get("statements") or []
        if not sts:
            continue
        printed = n - off
        row = None
        for r in rows:
            if r[0] <= printed:
                row = r
        if not row:
            continue
        for st in sts:
            t = st.get("statementType")
            if t not in KEEP:
                continue
            txt = (st.get("plain") or st.get("latex") or "").strip()
            if len(txt) < 8:
                continue
            txt, assumed = clean_statement(txt)
            if txt is None:
                stats["dropped"] += 1
                continue
            stats["assumed"] += assumed
            for code in row[3]:
                lst = out[code]["statements"]
                if any(x["text"] == txt or CB_jaccard(x["text"], txt) >= 0.8 for x in lst):
                    stats["dup"] += 1
                    continue
                lst.append({"type": t, "text": txt[:140], "latex": (st.get("latex") or "")[:140], "section": row[2], "page": n, **({"assumed": True} if assumed else {})})
    tdir = pathlib.Path(books.base_dir(bk["id"])) / "transcripts"          # 개념 설명 쪽 원문 전사(transcribe_pages.py --targets concept)
    passages = collections.defaultdict(list)
    for f in sorted(tdir.glob("p*.json")) if tdir.exists() else []:
        if f.name.endswith(".error.txt"):
            continue
        d = json.load(open(f, encoding="utf-8"))
        if "concept" not in d.get("_why", []):
            continue
        printed = d["_page"] - off
        row = None
        for r in rows:
            if r[0] <= printed:
                row = r
        if not row:
            continue
        txt = " / ".join(" ".join(i["text"].split()) for i in d.get("items", []) if i.get("kind") in ("생각열기", "기타", "참고", "예제", "읽기자료") and i.get("text"))
        if len(txt) >= 40:
            for code in row[3]:
                passages[code].append({"section": row[2], "page": d["_page"], "text": txt[:420]})
    res = {}
    for code, v in out.items():
        cnt = collections.Counter()
        keep = []
        for s in v["statements"]:
            if cnt[s["type"]] < LIMIT[s["type"]]:
                cnt[s["type"]] += 1
                keep.append(s)
        res[code] = {"goals": v["goals"], "statements": keep, "passages": passages.get(code, [])[:8]}
    path = pathlib.Path(books.DATA) / "textbook_style" / f"{bk['id']}_core.json" if hasattr(books, "DATA") else HERE.parents[1] / "data" / "textbook_style" / f"{bk['id']}_core.json"
    path.write_text(json.dumps({"book": bk["label"], "standards": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  진술 정리: 버림 {stats['dropped']}개(특정 활동·도구·예제 번호에 묶임), 중복 {stats['dup']}개, 이미 배운 내용 표시 {stats['assumed']}개")
    print(f"{bk['label']}: 성취기준 {len(res)}개, 학습 목표 {sum(len(v['goals']) for v in res.values())}개, 교과서 진술 {sum(len(v['statements']) for v in res.values())}개 → {path}")


if __name__ == "__main__":
    main()
