"""교과서 분석에서 '중1 범위 파일'(data/grade_scope_math1.json)을 만든다 (API 호출 없음).

- 단원별 중1 용어(개념용어만), 초등·앞 단원 전제 용어, 성취기준→단원 연결
- 중2·3 주제(교과서 '배울 내용')와, 그 주제를 알아볼 수 있는 금지어(내가 정리한 후보)
- 금지어 후보 중 이 교과서의 중1 본문(용어·기호·성질·예제·문제 요약)에 실제로 나오는 말은 자동으로 뺀다(오탐 방지). 뺀 목록은 droppedTriggers에 남는다.
사용: python build_scope.py [--book 천재(김동재)]
"""
import argparse
import collections
import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(HERE))
import books as tbooks  # noqa: E402
ROOT = HERE.parents[1]
DATA = ROOT / "data"

BOOK_ONLY_SRC = "중1 교과서는 지수 1까지만 정의"   # 성취기준에는 근거가 없고 교과서에서만 확인된 제한
# 금지어 후보: (보이는 이름, 정규식, 학년, 근거가 되는 '배울 내용' 주제)
TRIGGERS = [
    ("순환소수", r"순환소수|유한소수|순환마디", "중2", "유리수와 순환소수"),
    ("연립방정식", r"연립(일차)?방정식|연립\s*방정식", "중2", "일차부등식과 연립일차방정식"),
    ("부등식", r"부등식", "중2", "일차부등식과 연립일차방정식"),
    ("일차함수", r"일차함수|기울기|[xy]\s*절편|y절편", "중2", "일차함수와 그 그래프"),
    ("함수", r"함수", "중2", "일차함수와 그 그래프"),
    ("지수법칙", r"지수법칙", "중2", "식의 계산"),
    ("삼각형과 사각형의 성질", r"이등변삼각형|평행사변형|내심|외심|무게중심|사다리꼴의 성질", "중2", "삼각형과 사각형의 성질"),
    ("도형의 닮음", r"닮음|닮은", "중2", "도형의 닮음"),
    ("피타고라스 정리", r"피타고라스", "중2", "피타고라스 정리"),
    ("확률", r"확률", "중2", "경우의 수와 확률"),
    ("경우의 수", r"경우의 수", "중2", "경우의 수와 확률"),
    ("제곱근과 무리수", r"제곱근|근호|무리수|√|\\sqrt", "중3", "제곱근과 실수"),
    ("인수분해", r"(?<!소)인수분해", "중3", "다항식의 곱셈과 인수분해"),
    ("이차방정식", r"이차방정식|근의 공식", "중3", "이차방정식"),
    ("이차함수", r"이차함수", "중3", "이차함수와 그 그래프"),
    ("삼각비", r"삼각비|\bsin\b|\bcos\b|\btan\b|사인|코사인|탄젠트", "중3", "삼각비"),
    ("원주각", r"원주각", "중3", "원의 성질"),
    ("산포도", r"산포도|분산|표준편차|편차", "중3", "산포도"),
    ("상자그림·산점도", r"상자그림|산점도|상관관계", "중3", "상자그림과 산점도"),
    # 지수 0은 별도: 이 교과서는 '지수가 1인 거듭제곱은 밑 자신으로 정한다'(12쪽)까지만 다룬다
    ("지수 0", r"지수\s*(?:가\s*)?0(?![\d.])|0\s*제곱|[0영]\s*번\s*곱|0\s*개\s*곱|\^\s*\{?\s*0\s*\}?(?![\d.])", "중1 밖", BOOK_ONLY_SRC),
]


def norm(s):
    return re.sub(r"\s+", "", str(s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    a = ap.parse_args()
    bk = tbooks.resolve(a.book)
    a.book, bid = bk["unitsKey"], bk["id"]      # --book은 id·차례 이름 모두 받는다
    base = DATA / "textbook_analysis" / bid
    g = json.load(open(DATA / f"grade1_terms_{bid}.json", encoding="utf-8"))
    summ = json.load(open(base / "summary.json", encoding="utf-8"))
    units = json.load(open(DATA / "textbook_units_math1.json", encoding="utf-8"))["books"][a.book]["units"]
    kinds = json.load(open(base / "term_kinds.json", encoding="utf-8"))["kinds"]

    page_ch = {}
    for t, c in summ["chapters"].items():
        for p in c["pages"]:
            page_ch[p] = t
    chapters = {u["title"]: {"domain": u["domain"], "standards": sorted({s for su in u["subUnits"] for s in su.get("standards", [])}),
                             "subUnits": [{"title": su["title"], "startPage": su["startPage"], "standards": su.get("standards", [])} for su in u["subUnits"]],
                             "newTerms": [], "assumedTerms": []} for u in units}
    for t in g["defined"]:
        if t.get("termLabel") in ("", "개념용어") and t["chapter"] in chapters:
            chapters[t["chapter"]]["newTerms"].append(t["term"])
    # 전제 용어: pages/*.json에서 사용된 쪽의 단원으로 분류
    use_pages = collections.defaultdict(list)
    for f in sorted((base / "pages").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for tm in d.get("terms", []):
            if tm.get("role") == "사용":
                use_pages[tm["term"]].append(d["_page"])
    assumed = set(g["assumedFromEarlier"])
    for term in assumed:
        pgs = use_pages.get(term, [])
        ch = collections.Counter(page_ch.get(p) for p in pgs if page_ch.get(p)).most_common(1)
        if ch:
            chapters[ch[0][0]]["assumedTerms"].append(term)
    for c in chapters.values():
        c["newTerms"] = sorted(set(c["newTerms"]))
        c["assumedTerms"] = sorted(set(c["assumedTerms"]))

    # 중1 본문 텍스트(금지어 오탐 점검용): 용어·기호·성질·예제·문제 요약·자기평가 개념. 도입 쪽의 '배울 내용'과 메모는 제외
    body = []
    for f in sorted((base / "pages").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for k in ("terms", "symbols", "statements", "examples", "problems", "selfAssessment"):
            body.append((d["_page"], json.dumps(d.get(k, []), ensure_ascii=False)))
    dropped = []                                  # 이 책의 중1 본문에 실제로 나오는 말은 금지어에서 뺀다
    for name, rx, grade, src in TRIGGERS:
        pat = re.compile(rx)
        hits = [p for p, txt in body if pat.search(txt)]
        if hits:
            dropped.append({"name": name, "pattern": rx, "grade": grade, "from": src, "pagesFound": hits[:10], "count": len(hits)})

    later = []
    for t, c in summ["chapters"].items():
        gl = c.get("gradeLinks")
        if gl:
            for x in gl.get("later", []):
                later.append({"item": x["item"], "grade": x["grade"], "afterChapter": t})
    seen, later_u = set(), []
    for x in later:
        if (x["item"], x["grade"]) not in seen:
            seen.add((x["item"], x["grade"]))
            later_u.append(x)
    prior = sorted({p for c in summ["chapters"].values() if c.get("gradeLinks") for p in c["gradeLinks"].get("prior", [])})

    # 책별 범위는 books[id]에, 책과 무관한 공통 범위(중2·3 금지어)는 common에 둔다. 다른 책 항목은 그대로 보존한다.
    scope_path = DATA / "grade_scope_math1.json"
    old = json.load(open(scope_path, encoding="utf-8")) if scope_path.exists() else {}
    books = old.get("books", {})
    not_covered = [t[0] for t in TRIGGERS if t[3] == BOOK_ONLY_SRC]
    books[bid] = {"label": a.book, "source": f"{a.book} 쪽별 분석 {len(list((base / 'pages').glob('p*.json')))}쪽", "chapters": chapters, "priorTopics": prior,
                  "laterTopics": later_u, "droppedTriggers": dropped, "notCovered": not_covered}
    dropped_any = {d["name"] for b in books.values() for d in b["droppedTriggers"]}      # 어느 한 책이라도 본문에서 쓰면 공통 금지어에서 뺀다(보수적)
    std = json.load(open(DATA / "standards.json", encoding="utf-8"))["standards"]
    other = [x for x in std if x.get("grade") != 1]      # 중1로 표시된 24개 밖 성취기준(중2·3 추정 포함)
    common_triggers = []
    for name, rx, grade, src in TRIGGERS:
        if name in dropped_any:
            continue
        codes = [x["code"] for x in other if re.search(rx, x["text"])]
        common_triggers.append({"name": name, "pattern": rx, "grade": grade, "from": src, "basis": "standard" if codes else "bookOnly", "standards": codes})
    common_later = []
    seen = set()
    for b in books.values():
        for x in b["laterTopics"]:
            if (x["item"], x["grade"]) not in seen:
                seen.add((x["item"], x["grade"]))
                common_later.append({"item": x["item"], "grade": x["grade"]})
    out = {"_note": "중1 범위. common=책과 무관한 범위(중2·3 주제, 금지어. basis=standard면 성취기준 본문에서 중1 밖임이 확인된 것, bookOnly면 교과서에서만 확인된 것), books[id]=책별 용어·단원·전제 범위. 금지어는 분석된 어느 책이든 중1 본문에 나오면 빠진다. 책이 1종일 때는 그 책의 근거라 '경고'로만 쓴다.",
           "common": {"laterTopics": common_later, "triggers": common_triggers}, "books": books}
    scope_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    triggers = common_triggers
    print(f"단원 {len(chapters)}개, 공통 금지어 {len(triggers)}개(성취기준 근거 {sum(1 for t in triggers if t['basis']=='standard')}개) / 이 책 본문에 나와 제외 {len(dropped)}개")
    for d in dropped:
        print("  제외:", d["name"], f"({d['count']}쪽, 예: {d['pagesFound'][:5]})")
    print("  성취기준 근거:", [t["name"] + str(t["standards"][:2]) for t in triggers if t["basis"] == "standard"]); print("  교과서 근거만:", [t["name"] for t in triggers if t["basis"] == "bookOnly"])
    print("  배울 내용(중2·3):", [f"{x['item']}({x['grade']})" for x in later_u])
    print("  초등 선행 주제:", prior)


if __name__ == "__main__":
    main()
