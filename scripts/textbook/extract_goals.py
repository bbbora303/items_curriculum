"""교과서 PDF의 글자층에서 소단원 '학습 목표' 문장을 직접 찾는다 (API 호출 없음).

쪽 분석(AI)은 학습 목표를 전용 항목으로 기록하지 않아 일부 쪽에서만 우연히 잡혔다(천재 25쪽, 동아 11쪽).
글자층에는 '~할 수 있다', '~안다' 꼴의 목표 문장이 그대로 있으므로 이를 모아 쪽과 소단원, 성취기준에 연결한다.
v2(2026-10-23): ①'학습 목표' 표지 근처(8줄 이내)에 있거나 글머리 기호(•)로 시작하는 문장만 학습 목표로 인정한다(본문의 '~할 수 있다' 문장 제외)
  ②두 줄에 걸친 목표 문장은 이어 붙인다 ③'이 단원의 학습 목표' 목록은 성취기준 본문과 같은 문장이면 그 성취기준에 직접 연결한다.
  '나는 ~할 수 있다' 자기평가 문장은 소단원 끝 점검 목록이라 표지 없이도 인정한다.
결과: data/textbook_analysis/<id>/goals.json = [{page, text, kind(학습목표|자기평가), chapter, section, standards, how}]
사용: python extract_goals.py --book dong_a
"""
import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0]))
import books  # noqa: E402
import compare_books as CB  # noqa: E402

GOAL = re.compile(r"^[•·ㆍ▸■\-\s0-9]*?([가-힣A-Za-z][가-힣0-9A-Za-z\s,·\(\)\^/×÷\.]{8,100}(?:할 수 있다|안다|이해한다|설명한다|구한다|판단한다|인식한다|해석한다|탐구한다|나타낸다|알고 있다))\.?\s*$")
STARTER = re.compile(r"^\s*(?:[•·ㆍ▸■]|\d{1,2}\s+[가-힣]|\d{1,2}\.)")
NEAR = 8
BODY = re.compile(r"^(따라서|그러므로|이때|또한|이전|이것)|[A-Z][a-z]|[A-Z]{3,}|도미노")      # 본문 이음말·기호 설명·활동 문장


def clean(t):
    return re.sub(r"\s+", " ", t).strip(" .")


def nz(t):
    return re.sub(r"\s+", "", t)


def lines_of(page):
    raw = [re.sub(r"[\x00-\x1f  ]+", " ", l).strip() for l in page.get_text().split("\n") if l.strip()]       # 줄 앞의 제어 문자(동아의 글머리 \x07 등) 제거
    merged = []
    for l in raw:
        if merged and STARTER.match(merged[-1]) and not re.search(r"(다\.?|요\.?)$", merged[-1]) and not STARTER.match(l) and len(merged[-1]) < 70:
            merged[-1] = merged[-1] + " " + l          # 두 줄에 걸친 목표 문장
        else:
            merged.append(l)
    return merged


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    a = ap.parse_args()
    bk = books.resolve(a.book)
    pages = CB.load_pages(bk["id"])
    off = CB.printed_offset(pages)
    rows = CB.sub_unit_ranges(bk["id"])
    std = {s["code"]: s["text"] for s in json.load(open(books.DATA / "standards.json", encoding="utf-8"))["standards"] if s.get("grade") == 1} if hasattr(books, "DATA") else {}
    if not std:
        std = {s["code"]: s["text"] for s in json.load(open(HERE.parents[1] / "data" / "standards.json", encoding="utf-8"))["standards"] if s.get("grade") == 1}
    std_nz = {c: nz(t).rstrip(".") for c, t in std.items()}
    import pymupdf
    doc = pymupdf.open(books.pdf_path(bk["id"]))
    out, seen, dropped = [], set(), 0
    for n in range(len(doc)):
        pg = pages.get(n + 1, {})
        if pg.get("pageType") in ("표지", "차례", "부록", "기타", "연습문제", "단원마무리"):        # 목차·정답·문제 쪽의 문장은 제외
            continue
        lines = lines_of(doc[n])
        labels = [i for i, l in enumerate(lines) if "학습목표" in nz(l)]
        for i, line in enumerate(lines):
            m = GOAL.match(line)
            if not m or "시오" in line or len(line) > 140:
                continue
            text = clean(m.group(1))
            kind = "자기평가" if text.startswith("나는") else "학습목표"
            text = re.sub(r"^나는\s*", "", text)
            bullet = bool(re.match(r"^\s*[•·ㆍ▸■]", line))          # 천재처럼 소단원 제목 아래 '•목표 문장.' 꼴로 적는 책도 있다
            tn = nz(text).rstrip(".")
            direct = [c for c, s in std_nz.items() if tn and (tn == s or (len(tn) > 15 and (tn in s or s in tn)))]
            if kind == "학습목표" and not direct:
                if not bullet and not any(abs(i - j) <= NEAR for j in labels):
                    dropped += 1                  # '학습 목표' 표지도 글머리 표시도 없는 본문 문장
                    continue
                if len(text) > 62 or re.search(r"[A-Za-z]\s*,\s*[A-Za-z]", text) or BODY.search(text):
                    dropped += 1                  # 너무 길거나 기호 나열이 든 문장은 본문 설명이다
                    continue
            printed = n + 1 - off
            row = None
            for r in rows:
                if r[0] <= printed:
                    row = r
            key = (text, kind)
            if key in seen:
                continue
            seen.add(key)
            section, stds, how = (row[2] if row else ""), (row[3] if row else []), "쪽 위치"
            if direct:                            # 성취기준 문장과 같은 목표(단원 전체 목표 목록): 성취기준에 직접 연결
                stds, how = direct, "성취기준 본문 일치"
            out.append({"page": n + 1, "text": text, "kind": kind, "chapter": (row[1] if row else ""), "section": section, "standards": stds, "how": how})
    path = pathlib.Path(books.base_dir(bk["id"])) / "goals.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    goals = [g for g in out if g["kind"] == "학습목표"]
    stds = {s for g in goals for s in g["standards"]}
    print(f"{bk['label']}: 학습 목표 {len(goals)}개 / 자기평가 {len(out) - len(goals)}개 (본문 문장으로 제외 {dropped}개), 학습 목표가 연결된 성취기준 {len(stds)}개 → {path}")


if __name__ == "__main__":
    main()
