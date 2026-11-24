"""교과서 반영도를 이미 만든 문항에서 측정한다 (API 호출 없음, 무료).

  python reflect_score.py                       # 측정 세트(data/eval/reflect_set.json)의 문항을 채점해 표로 보여 준다
  python reflect_score.py --labels a,b,c        # 문항 폴더 이름을 직접 지정
  python reflect_score.py --out docs/반영도_측정_결과.md   # 보고서 저장

측정 항목(모두 글자 겹침으로 계산 - 의미 판단이 아니라 '그 책의 표현이 문항에 들어갔는가'):
  책 고유 표현 반영도 = (그 책에만 있는 표현이 문항에 나온 비율) - (다른 책에만 있는 표현이 나온 비율)
      표현의 출처: 학습 목표 / 교과서 진술(성질·공식·풀이 방법) / 설명 원문 발췌.  +이면 선택한 책 쪽, 0 근처면 구분 안 됨.
      교과서를 고르지 않은 문항은 0 근처가 정상(중립)이다. 이 값이 책 선택의 실제 효과를 나타낸다.
  평가 요소 목표 일치 = 평가 요소 중 선택한 책의 학습 목표와 글자 겹침이 0.3 이상인 비율
  소재 지정 일치 = 제시문이 코드가 지정한 소재 후보의 단어를 쓴 문항인가(시드로 후보를 다시 계산)
  풀이 근거 = textbookItems를 채운 풀이 비율, 기본/확장 풀이 수
  범위 경고 = W11(재작성 대상)·W12(참고) 수
회귀 시험 용도: 같은 (성취기준, 책, 시드)로 다시 생성한 문항에서 이 값이 크게 떨어지면 반영 기능이 약해진 것이다.
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import scope_check  # noqa: E402

PILOT = ROOT / "output" / "pilot"
STOP = set("그리고 그러므로 따라서 이다 있다 한다 하는 하여 위해 이때 대한 같은 다음 각각 모두 경우 때문 또는 해당 구하 구한 구하시 쓰시 하시 사용 이용 이므로 이면 하면 에서 으로".split())
LATEX = re.compile(r"\$[^$]*\$|\\[a-zA-Z]+")


def tokens(text):
    """한글 낱말(2자 이상)에서 조사를 아주 거칠게 떼어 낸 집합."""
    out = set()
    for w in re.findall(r"[가-힣]{2,}", LATEX.sub(" ", str(text))):
        for suf in ("으로", "에서", "이다", "하다", "한다", "에는", "이고", "라고", "을", "를", "은", "는", "이", "가", "의", "과", "와", "에", "로", "도"):
            if len(w) > 2 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        if len(w) >= 2 and w not in STOP:
            out.add(w)
    return out


def item_text(it, which="all"):
    parts = []
    if which in ("all", "stimulus"):
        parts.append(it.get("stimulus", {}).get("text", ""))
    if which in ("all", "questions"):
        for q in it.get("subQuestions", []):
            parts.append(q.get("prompt", ""))
            for c in q.get("conditions", []) or []:
                parts.append(c.get("text", ""))
            for e in q.get("evaluationElements", []):
                parts.append(e.get("text", ""))
    if which in ("all", "answers"):
        for m in it.get("solutionMethods", []):
            parts.append(f"{m.get('name', '')} {m.get('summary', '')}")
        for a in it.get("modelAnswers", []):
            for x in a.get("methods", []):
                parts.append(x.get("text", ""))
    return " ".join(parts)


def book_pool(std, book, kind):
    c = scope_check._core(std, book) or {}
    if kind == "goals":
        return " ".join(c.get("goals", []))
    if kind == "statements":
        return " ".join(s["text"] for s in c.get("statements", []))
    return " ".join(p["text"] for p in c.get("passages", []))


def distinct_hit(std, own, other, kind, item_tokens):
    """own 책에만 있는 표현 중 문항에 나온 비율 - other 책에만 있는 표현 중 문항에 나온 비율."""
    a, b = tokens(book_pool(std, own, kind)), tokens(book_pool(std, other, kind))
    da, db = a - b, b - a
    if not da or not db:
        return None
    return len(da & item_tokens) / len(da) - len(db & item_tokens) / len(db)


def jaccard(a, b):
    a, b = tokens(a), tokens(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def score(label, books):
    it = json.load(open(PILOT / label / "item.json", encoding="utf-8"))
    gm = it.get("generationMeta") or {}
    book = scope_check.book_of(it)
    std = it["standardCodes"][0]
    row = {"label": label, "std": std, "book": book or "미선택", "difficulty": gm.get("difficulty"), "seed": gm.get("seed")}
    toks = tokens(item_text(it))
    ans = tokens(item_text(it, "answers") + " " + item_text(it, "questions"))
    comp = {}
    for kind, name, scope in (("goals", "목표", toks), ("statements", "진술", ans), ("passages", "원문", toks)):
        vals = []
        for own in books:
            for other in books:
                if own == other:
                    continue
                v = distinct_hit(std, own, other, kind, scope)
                if v is not None:
                    vals.append((own, v))
        # 선택한 책 기준 값, 미선택이면 두 책 값의 평균(0 근처가 정상)
        if book:
            mine = [v for o, v in vals if o == book]
            comp[name] = mine[0] if mine else None
        else:
            comp[name] = (sum(v for _, v in vals) / len(vals)) if vals else None
    row.update({"책고유_목표": comp["목표"], "책고유_진술": comp["진술"], "책고유_원문": comp["원문"]})
    if book:
        goals = (scope_check._core(std, book) or {}).get("goals", [])
        els = [e["text"] for q in it["subQuestions"] for e in q["evaluationElements"]]
        row["평가요소_목표일치"] = (sum(1 for e in els if goals and max(jaccard(e, g) for g in goals) >= 0.3) / len(els)) if els else None
        th = scope_check.pick_themes(std, book, int(gm.get("seed") or 1))
        stim = tokens(it.get("stimulus", {}).get("text", ""))
        row["소재_일치"] = any(tokens(t) & stim for t in th) if th else None
    else:
        row["평가요소_목표일치"] = row["소재_일치"] = None
    # 구조화 지표 A: 문항이 근거로 인용한 교과서 진술(textbookBasis) 중 '그 책에만 있는' 진술의 비율
    cited = gm.get("textbookBasis") or []
    row["인용진술수"] = len(cited) if book else None
    if book and cited:
        own = [s_["text"] for s_ in (scope_check._core(std, book) or {}).get("statements", [])]
        other_book = [b for b in books if b != book][0]
        other = [s_["text"] for s_ in (scope_check._core(std, other_book) or {}).get("statements", [])]
        def unique(x, pool):
            return all(jaccard(x, y) < 0.5 for y in pool)
        row["목록_고유비율"] = (sum(1 for x in own if unique(x, other)) / len(own)) if own else None
        row["인용_고유비율"] = sum(1 for x in cited if unique(x, other)) / len(cited)
    else:
        row["목록_고유비율"] = row["인용_고유비율"] = None
    ms = it.get("solutionMethods", [])
    row["풀이수"] = len(ms)
    row["풀이_근거비율"] = (sum(1 for m in ms if m.get("textbookItems")) / len(ms)) if ms and book else None
    row["확장풀이"] = sum(1 for m in ms if m.get("tier") == "확장")
    sc = scope_check.scan_item(it)
    row["W11"] = sum(1 for h in sc if h[0] == "W11")
    row["W12"] = sum(1 for h in sc if h[0] == "W12")
    return row


def pair_report(rows, books):
    """같은 (성취기준, 시드, 난이도)에서 책별 문항끼리의 차이: 풀이 이름·평가 요소 글자 겹침. 낮을수록 책에 따라 문항이 달라진 것."""
    groups = {}
    for r in rows:
        groups.setdefault((r["std"], r["seed"], r["difficulty"]), []).append(r)
    out = []
    for key, g in groups.items():
        by = {r["book"]: r for r in g}
        names = list(by)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a = json.load(open(PILOT / by[names[i]]["label"] / "item.json", encoding="utf-8"))
                b = json.load(open(PILOT / by[names[j]]["label"] / "item.json", encoding="utf-8"))
                ma = " ".join(m["name"] for m in a["solutionMethods"])
                mb = " ".join(m["name"] for m in b["solutionMethods"])
                ea = " ".join(e["text"] for q in a["subQuestions"] for e in q["evaluationElements"])
                eb = " ".join(e["text"] for q in b["subQuestions"] for e in q["evaluationElements"])
                sa, sb = a["stimulus"].get("text", ""), b["stimulus"].get("text", "")
                out.append((key, names[i], names[j], jaccard(ma, mb), jaccard(ea, eb), jaccard(sa, sb)))
    return out


def fmt(v):
    if v is None:
        return "-"
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, float):
        return f"{v:+.2f}" if abs(v) <= 1 else f"{v:.2f}"
    return str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="")
    ap.add_argument("--set", default=str(ROOT / "data" / "eval" / "reflect_set.json"))
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.labels:
        labels = a.labels.split(",")
        note = ""
    else:
        spec = json.load(open(a.set, encoding="utf-8"))
        labels, note = [x["label"] for x in spec["items"]], spec.get("note", "")
    books = [b["id"] for b in json.load(open(ROOT / "data" / "textbook_registry.json", encoding="utf-8"))["books"] if scope_check.norm_book(b["id"])] if False else ["cheonjae_kim_dongjae", "dong_a"]
    rows = [score(l, books) for l in labels]
    cols = ["label", "std", "book", "책고유_목표", "책고유_진술", "책고유_원문", "평가요소_목표일치", "소재_일치", "인용진술수", "목록_고유비율", "인용_고유비율", "풀이수", "풀이_근거비율", "확장풀이", "W11", "W12"]
    L = ["# 교과서 반영도 측정 결과", "", note, "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        L.append("| " + " | ".join(fmt(r.get(c)) for c in cols) + " |")
    # 평균(교과서 선택 vs 미선택)
    L += ["", "## 평균 (책 고유 표현 반영도: +이면 선택한 책 쪽 표현이 더 많이 들어감)", "", "| 조건 | 문항 수 | 목표 | 진술 | 원문 | 평가요소 목표일치 | 소재 일치 |", "|---|---|---|---|---|---|---|"]
    for name, cond in (("교과서 선택", lambda r: r["book"] != "미선택"), ("미선택(중립)", lambda r: r["book"] == "미선택")):
        g = [r for r in rows if cond(r)]
        def avg(k):
            v = [r[k] for r in g if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool)]
            return fmt(sum(v) / len(v)) if v else "-"
        sm = [r["소재_일치"] for r in g if r.get("소재_일치") is not None]
        L.append(f"| {name} | {len(g)} | {avg('책고유_목표')} | {avg('책고유_진술')} | {avg('책고유_원문')} | {avg('평가요소_목표일치')} | {fmt(sum(sm) / len(sm)) if sm else '-'} |")
    pr = pair_report(rows, books)
    if pr:
        L += ["", "## 같은 조건·다른 책 문항끼리의 차이 (글자 겹침, 낮을수록 책에 따라 달라짐)", "", "| 성취기준·시드 | 책 A | 책 B | 풀이 이름 | 평가 요소 | 제시문 |", "|---|---|---|---|---|---|"]
        for key, x, y, m, e, s in pr:
            L.append(f"| {key[0]} 시드{key[1]} | {x} | {y} | {m:.2f} | {e:.2f} | {s:.2f} |")
    if not a.labels and spec.get("repeats"):
        L += ["", "## 잡음 바닥: 같은 조건으로 다시 생성한 문항끼리의 글자 겹침", "", spec.get("repeatsNote", ""), "", "| 문항 쌍 | 풀이 이름 | 평가 요소 | 제시문 |", "|---|---|---|---|"]
        for x, y in spec["repeats"]:
            A = json.load(open(PILOT / x / "item.json", encoding="utf-8"))
            B = json.load(open(PILOT / y / "item.json", encoding="utf-8"))

            def parts(it):
                return (" ".join(m["name"] for m in it["solutionMethods"]), " ".join(e["text"] for q in it["subQuestions"] for e in q["evaluationElements"]), it["stimulus"].get("text", ""))
            p, q = parts(A), parts(B)
            L.append(f"| {x} vs {y} | " + " | ".join(f"{jaccard(u, v):.2f}" for u, v in zip(p, q)) + " |")
    text = "\n".join(L)
    print(text)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
        print("\n저장:", a.out)


if __name__ == "__main__":
    main()
