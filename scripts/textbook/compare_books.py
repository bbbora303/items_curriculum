"""분석이 끝난 교과서 두 권을 비교한다 (API 호출 없음).

사용: python compare_books.py --a cheonjae_kim_dongjae --b dong_a
결과: docs/교과서비교_<a>_vs_<b>.md (읽는 보고서) + data/textbook_analysis/compare_<a>_<b>.json
비교 항목: 단원 구성, 용어(공통/한쪽만)와 정의 문장 차이, 기호, 성질·공식·풀이 방법의 수와 종류, 소재, 발문 표현, 문제 구성,
          성취기준별 소단원 학습 목표(평가 요소 도출에 쓸 수 있는 문장).
목적: 출판사마다 **무엇이 다른지**를 확인해 문항에 반영할 대상(용어, 정의, 풀이 방식, 소재, 학습 목표 등)을 정한다.
"""
import argparse
import collections
import difflib
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import books  # noqa: E402

ROOT = HERE.parents[1]
DATA = ROOT / "data"


def nz(s):
    return re.sub(r"[\s·,()]", "", str(s))


def load_pages(bid):
    out = {}
    for f in sorted((DATA / "textbook_analysis" / bid / "pages").glob("p*.json")):
        d = json.load(open(f, encoding="utf-8"))
        out[d["_page"]] = d
    return out


def sub_unit_ranges(book):
    """[(시작쪽, 끝쪽, 대단원, 소단원, 성취기준들)] — 차례 파일의 시작쪽 기준(인쇄 쪽 번호가 아니라 PDF 쪽 순서와 다를 수 있어 오프셋을 보정한다)."""
    u = books.units_info(book)["units"]
    rows = []
    for ch in u:
        for su in ch.get("subUnits", []):
            rows.append([su.get("startPage") or 0, ch["title"], su["title"], su.get("standards", [])])
    rows.sort(key=lambda r: r[0])
    return rows


def printed_offset(pages):
    """PDF 쪽 순서와 인쇄된 쪽 번호의 차이(가장 흔한 값)."""
    diffs = collections.Counter()
    for n, d in pages.items():
        m = re.fullmatch(r"\d+", str(d.get("printedPage", "")).strip())
        if m:
            diffs[n - int(m.group())] += 1
    return diffs.most_common(1)[0][0] if diffs else 0


def goals_by_standard(book, pages):
    """성취기준 → 소단원 학습 목표 문장(교과서가 단원 도입·개념 설명 쪽에 제시한 '~할 수 있다/안다' 문장)."""
    off = printed_offset(pages)
    rows = sub_unit_ranges(book)
    out = collections.defaultdict(list)
    for n, d in sorted(pages.items()):
        if d.get("pageType") not in ("단원도입", "개념설명"):
            continue
        goals = [g for g in (d.get("gradeLinks") or {}).get("current", []) if re.search(r"(있다|안다|이해한다|설명한다|구한다|나타낸다|판단한다|인식한다|해석한다)\.?$", str(g).strip()) and len(str(g)) >= 12]
        if not goals:
            continue
        printed = n - off
        row = None
        for r in rows:
            if r[0] <= printed:
                row = r
        if not row:
            continue
        for std in row[3]:
            for g in goals:
                if g not in out[std]:
                    out[std].append(g)
    return dict(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    args = ap.parse_args()
    A, B = books.resolve(args.a), books.resolve(args.b)
    pa, pb = load_pages(A["id"]), load_pages(B["id"])
    ga = json.load(open(DATA / f"grade1_terms_{A['id']}.json", encoding="utf-8"))
    gb = json.load(open(DATA / f"grade1_terms_{B['id']}.json", encoding="utf-8"))
    sa = json.load(open(DATA / "textbook_analysis" / A["id"] / "summary.json", encoding="utf-8"))
    sb = json.load(open(DATA / "textbook_analysis" / B["id"] / "summary.json", encoding="utf-8"))
    L = [f"# 교과서 비교: {A['label']} vs {B['label']}\n", "(분석 자료 기반. AI가 쪽 이미지를 읽어 만든 자료라 사람 검수 전이다.)\n"]
    res = {}

    # 1. 구조
    L.append("## 1. 단원 구성")
    for bk, s in ((A, sa), (B, sb)):
        L.append(f"- **{bk['label']}** ({s['analyzedPages']}쪽): " + ", ".join(f"{t}({len(c['pages'])}쪽)" for t, c in s["chapters"].items()))
    res["chapters"] = {A["id"]: list(sa["chapters"]), B["id"]: list(sb["chapters"])}

    # 2. 용어
    da = {nz(t["term"]): t for t in ga["defined"] if t.get("termLabel") in ("", "개념용어")}
    db = {nz(t["term"]): t for t in gb["defined"] if t.get("termLabel") in ("", "개념용어")}
    common, only_a, only_b = sorted(set(da) & set(db)), sorted(set(da) - set(db)), sorted(set(db) - set(da))
    L.append(f"\n## 2. 새로 정의하는 용어 (개념용어만)\n- {A['label']} {len(da)}개 / {B['label']} {len(db)}개 / **공통 {len(common)}개 ({100 * len(common) // max(1, min(len(da), len(db)))}%)**")
    L.append(f"- {A['label']}에만 있는 용어({len(only_a)}): " + ", ".join(da[k]["term"] for k in only_a[:60]))
    L.append(f"- {B['label']}에만 있는 용어({len(only_b)}): " + ", ".join(db[k]["term"] for k in only_b[:60]))
    diffs = []
    for k in common:
        x, y = da[k].get("definition", ""), db[k].get("definition", "")
        if x and y:
            r = difflib.SequenceMatcher(None, nz(x), nz(y)).ratio()
            if r < 0.6:
                diffs.append((r, da[k]["term"], x, y))
    diffs.sort()
    L.append(f"\n### 공통 용어 중 정의 문장이 크게 다른 것 ({len(diffs)}개, 유사도 0.6 미만)")
    for r, t, x, y in diffs[:25]:
        L.append(f"- **{t}** (유사도 {r:.2f})\n    - {A['label']}: {x[:110]}\n    - {B['label']}: {y[:110]}")
    res["terms"] = {"common": len(common), "onlyA": [da[k]["term"] for k in only_a], "onlyB": [db[k]["term"] for k in only_b], "definitionDiffs": [{"term": t, "a": x, "b": y, "sim": round(r, 2)} for r, t, x, y in diffs]}

    # 3. 기호
    def syms(pages):
        out = {}
        for d in pages.values():
            for s in d.get("symbols", []):
                if s.get("role") == "정의":
                    out[nz(s["symbol"])] = s.get("meaning", "")
        return out
    xa, xb = syms(pa), syms(pb)
    L.append(f"\n## 3. 새로 정의하는 기호\n- {A['label']} {len(xa)}개 / {B['label']} {len(xb)}개 / 공통 {len(set(xa) & set(xb))}개")
    L.append(f"- {A['label']}에만: " + ", ".join(list(set(xa) - set(xb))[:20]))
    L.append(f"- {B['label']}에만: " + ", ".join(list(set(xb) - set(xa))[:20]))

    # 4. 성질·공식·풀이 방법
    ta, tb = sa["typeTotals"], sb["typeTotals"]
    L.append("\n## 4. 설명 방식 — 성질·공식·풀이 방법·예제")
    for key, name in (("statementTypes", "내용 성격"), ("exampleTypes", "예제 유형")):
        L.append(f"- {name}: {A['label']} {ta.get(key)} / {B['label']} {tb.get(key)}")

    # 5. 소재
    def ctx(s):
        c = collections.Counter()
        for ch in s["chapters"].values():
            c.update(ch["contexts"])
        return c
    ca, cb = ctx(sa), ctx(sb)
    L.append(f"\n## 5. 소재\n- {A['label']} 소재 {len(ca)}종 / {B['label']} {len(cb)}종 / 완전히 같은 표현 {len(set(ca) & set(cb))}개")
    L.append(f"- {A['label']} 상위: " + ", ".join(k for k, _ in ca.most_common(15)))
    L.append(f"- {B['label']} 상위: " + ", ".join(k for k, _ in cb.most_common(15)))

    # 6. 발문 표현, 문제 구성
    va, vb = sa["verbs"], sb["verbs"]
    L.append("\n## 6. 발문 표현과 문제 구성")
    L.append(f"- 발문 지시어 상위: {A['label']} {dict(list(va.items())[:8])} / {B['label']} {dict(list(vb.items())[:8])}")
    L.append(f"- 문제 유형: {A['label']} {ta.get('problemTypes')} / {B['label']} {tb.get('problemTypes')}")
    for bk, s in ((A, sa), (B, sb)):
        lv = collections.Counter()
        for ch in s["chapters"].values():
            lv.update(ch["problemLevels"])
        L.append(f"- 문제 수준: {bk['label']} {dict(lv)}")

    # 7. 학습 목표(성취기준별)
    def goals_file(bk, pages):
        f = DATA / "textbook_analysis" / bk["id"] / "goals.json"
        if not f.exists():                                      # extract_goals.py를 안 돌렸으면 쪽 분석에서 우연히 잡힌 것만 쓴다
            return goals_by_standard(bk["id"], pages)
        out = collections.defaultdict(list)
        for g in json.load(open(f, encoding="utf-8")):
            if g["kind"] == "학습목표":
                for s_ in g["standards"]:
                    if g["text"] not in out[s_]:
                        out[s_].append(g["text"])
        return dict(out)
    gla, glb = goals_file(A, pa), goals_file(B, pb)
    L.append("\n## 7. 성취기준별 소단원 학습 목표 (평가 요소 도출에 쓸 수 있는 문장)")
    std = {s["code"]: s for s in json.load(open(DATA / "standards.json", encoding="utf-8"))["standards"]}
    for code in sorted(set(gla) | set(glb)):
        L.append(f"- **{code}** {std.get(code, {}).get('text', '')[:44]}")
        L.append(f"    - {A['label']}: " + (" / ".join(gla.get(code, [])[:3]) or "(없음)"))
        L.append(f"    - {B['label']}: " + (" / ".join(glb.get(code, [])[:3]) or "(없음)"))
    res["goals"] = {A["id"]: gla, B["id"]: glb}

    out = ROOT / "docs" / f"교과서비교_{A['id']}_vs_{B['id']}.md"
    out.write_text("\n".join(L), encoding="utf-8")
    (DATA / "textbook_analysis" / f"compare_{A['id']}_{B['id']}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("저장:", out)
    print(f"공통 용어 {len(common)}/{len(da)}·{len(db)}, 정의 문장 차이 {len(diffs)}개, 학습 목표가 있는 성취기준 {len(set(gla) | set(glb))}개")


if __name__ == "__main__":
    main()
