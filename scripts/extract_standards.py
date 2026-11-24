"""2022 개정 수학과 교육과정(별책8) + 중학교 수학 성취수준 PDF에서 중학교 성취기준·해설·성취수준(A~E)을 추출한다.

사용법: python -I extract_standards.py <교육과정.pdf> <성취수준.pdf> <출력.json>
주의: PDF 텍스트 추출 시 일부 수식 기호(분수, 첨자, 특수기호)가 사라진다 -> 해설/성취수준 텍스트에 `mathGarbled` 표시.
"""
import json
import re
import sys

import pymupdf

CODE_RE = re.compile(r"^\[(9수0[1-4]-\d{2})\]\s*(.*)$")
CODE_ANY = re.compile(r"\[(9수0[1-4]-\d{2})\]")
DOMAIN_RE = re.compile(r"^\((\d)\)\s*(수와 연산|변화와 관계|도형과 측정|자료와 가능성)\s*$")
GLYPH_RE = re.compile(r"^[\U000f0000-\U000ffffd-]+\s*")  # 성취수준 PDF의 원문자 기호(사용자 정의 영역)
GLYPH_CUR = re.compile(r"^[숔숕숖숗수숙숚숛순숝숞숟술숡숢숣숤숥숦숧]\s+(?!.*(?:다|\.)\s*$)")  # 문장 끝(~다.)인 줄은 '수 있다.' 같은 본문이므로 제외  # 교육과정 PDF에서 원문자 자리에 나오는 글자
SUPPRESSED = ("공통 교육과정", "수학과 교육과정")


def clean_lines(pdf, start_marker=None):
    doc = pymupdf.open(pdf)
    lines = []
    for page in doc:
        raw = [x.rstrip() for x in page.get_text().split("\n")]
        i = 0
        while i < len(raw):
            s = raw[i].strip()
            if s in SUPPRESSED and i + 1 < len(raw) and raw[i + 1].strip().isdigit():
                i += 2
                continue
            if s.isdigit() and len(s) <= 3 and i == 0:
                i += 1
                continue
            lines.append(raw[i])
            i += 1
    return lines


def join(parts):
    text = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        text = p if not text else text + " " + p
    return re.sub(r"\s+", " ", text).strip()


def parse_curriculum(pdf):
    lines = clean_lines(pdf)
    start = next(i for i, l in enumerate(lines) if l.strip() == "[중학교 1∼3학년]")
    end = next(i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[고등학교") or lines[i].strip().startswith("3. 교수"))
    seg = lines[start:end]

    standards = {}
    order = []
    domain = None
    subunit = None
    mode = "std"  # std | commentary | considerations
    cur_code = None
    cur_parts = []
    comm = {}
    comm_code = None

    def flush():
        nonlocal cur_code, cur_parts
        if cur_code:
            standards[cur_code]["text"] = join(cur_parts)
        cur_code, cur_parts = None, []

    for raw in seg:
        s = raw.strip()
        m = DOMAIN_RE.match(s)
        if m:
            flush()
            domain = m.group(2)
            mode = "std"
            comm_code = None
            continue
        if s.startswith("(가) 성취기준 해설"):
            flush()
            mode = "commentary"
            comm_code = None
            continue
        if s.startswith("(나) 성취기준 적용 시 고려 사항"):
            flush()
            mode = "considerations"
            comm_code = None
            continue
        if mode != "std" and (CODE_RE.match(s) or (GLYPH_CUR.match(s) and len(GLYPH_CUR.sub("", s)) >= 2 and not s.startswith("•"))):
            mode = "std"
            comm_code = None
        if mode == "std":
            m = CODE_RE.match(s)
            if m:
                flush()
                cur_code = m.group(1)
                cur_parts = [m.group(2)]
                standards[cur_code] = {"code": cur_code, "domain": domain, "subunit": subunit, "text": "", "commentary": None}
                order.append(cur_code)
                continue
            if GLYPH_CUR.match(s) and len(GLYPH_CUR.sub("", s)) >= 2:
                flush()
                subunit = GLYPH_CUR.sub("", s).strip()
                continue
            if re.fullmatch(r"[숔숕숖숗수숙숚숛순숝숞숟술숡숢숣숤숥숦숧]", s) or not s:
                if not s:
                    flush()
                continue
            if cur_code:
                cur_parts.append(s)
        elif mode == "commentary":
            if s.startswith("•"):
                m = CODE_ANY.search(s)
                comm_code = m.group(1) if m else None
                if comm_code:
                    comm.setdefault(comm_code, []).append(s.lstrip("• ").strip())
                continue
            if comm_code and s and not DOMAIN_RE.match(s):
                comm[comm_code][-1] += " " + s
    flush()

    for code, parts in comm.items():
        if code in standards:
            standards[code]["commentary"] = join(parts)
    return [standards[c] for c in order]


LEVEL_LABEL = {"A", "B", "C", "D", "E"}
STOP_PREFIX = ("Ⅲ", "성취기준", "성취기준별 성취수준", "2022 개정 교육과정에 따른", "중학교 수학 성취수준")


def parse_levels(pdf):
    lines = clean_lines(pdf)
    start = next(i for i, l in enumerate(lines) if l.strip() == "성취기준별 성취수준" and i + 1 < len(lines))
    result = {}
    code = None
    std_parts = []
    level = None
    buf = []
    levels = {}

    def close_level():
        nonlocal level, buf
        if level:
            levels[level] = join(buf)
        level, buf = None, []

    def close_std():
        nonlocal code, levels, std_parts
        close_level()
        if code:
            result[code] = {"standardText": join(std_parts), "levels": levels}
        code, levels, std_parts = None, {}, []

    for raw in lines[start:]:
        s = raw.strip()
        if not s:
            continue
        m = CODE_RE.match(s)
        if m:
            close_std()
            code = m.group(1)
            std_parts = [m.group(2)]
            continue
        if code is None:
            continue
        if re.match(r"^\(\d\)\s*(수와 연산|변화와 관계|도형과 측정|자료와 가능성)", s) or GLYPH_RE.match(s) or s.startswith(STOP_PREFIX) or (s.isdigit() and len(s) <= 3):
            close_level()
            if GLYPH_RE.match(s) or s.startswith("Ⅲ"):
                continue
            continue
        if s in LEVEL_LABEL:
            close_level()
            level = s
            continue
        if level:
            buf.append(s)
        else:
            std_parts.append(s)
    close_std()
    return result


def main():
    cur_pdf, ach_pdf, out = sys.argv[1:4]
    stds = parse_curriculum(cur_pdf)
    ach = parse_levels(ach_pdf)
    missing = []
    for s in stds:
        a = ach.get(s["code"])
        if not a:
            missing.append(s["code"])
            s["achievementLevels"] = {}
        else:
            s["achievementLevels"] = {k: v for k, v in a["levels"].items() if v}
    # 중1 범위(잠정): 교과서 5종 차례(소인수분해~자료의 정리와 해석)에서 확인. 단원 대응 검수 후 확정
    grade1 = {f"9수01-0{i}" for i in range(1, 6)} | {f"9수02-0{i}" for i in range(1, 8)} \
        | {f"9수03-0{i}" for i in range(1, 9)} | {f"9수04-0{i}" for i in range(1, 5)}
    for s in stds:
        s["grade"] = 1 if s["code"] in grade1 else None  # None = 중2·3 또는 미확정
        s["gradeConfirmed"] = False
    data = {
        "curriculum": "2022 개정",
        "subject": "수학",
        "level": "중학교",
        "source": ["교육부 고시 제2022-33호 [별책 8] 수학과 교육과정", "2022 개정 교육과정에 따른 중학교 수학 성취수준"],
        "note": "PDF 텍스트 추출로 수식 기호 일부가 누락됨. 수식이 필요한 항목은 mathGarbled 플래그로 검수 필요.",
        "standards": stds,
    }
    with open(out, "w", encoding="utf-8") as w:
        json.dump(data, w, ensure_ascii=False, indent=2)
    print("standards:", len(stds), "with levels:", len(stds) - len(missing), "missing levels:", missing)


if __name__ == "__main__":
    main()
