"""교과서 책 이름·id·폴더·분석 진행 상태를 한곳에서 관리한다 (기준: data/textbook_registry.json, data/textbook_units_math1.json).

모든 textbook 스크립트의 --book 은 책 id(예: dong_a)나 차례 파일의 이름(예: 동아, 천재(김동재)) 어느 쪽이든 받는다.
새 책을 추가하려면 registry에 책이 있는지 확인하고 pipeline.py로 분석한다(docs/교과서_추가_절차.md).
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def registry():
    return json.load(open(DATA / "textbook_registry.json", encoding="utf-8"))["books"]


def resolve(name):
    """id 또는 차례 파일의 이름 → registry 항목({id, label, unitsKey}). 모르는 책이면 오류로 멈춘다."""
    for b in registry():
        if name in (b["id"], b["unitsKey"], b["label"]):
            return b
    raise SystemExit(f"알 수 없는 교과서: {name} (사용 가능: " + ", ".join(f"{b['id']}({b['unitsKey']})" for b in registry()) + ")")


def units_info(book):
    """차례 파일에서 이 책의 항목(pdf 파일명, 대단원 목록)."""
    d = json.load(open(DATA / "textbook_units_math1.json", encoding="utf-8"))["books"]
    return d[resolve(book)["unitsKey"]]


def base_dir(book):
    return DATA / "textbook_analysis" / resolve(book)["id"]


def pdf_path(book):
    return ROOT / "docu" / units_info(book)["pdf"]


def page_count(book):
    import pymupdf
    return len(pymupdf.open(pdf_path(book)))


def status(book, total_pages=None):
    """분석 단계별 진행 상태(파일만 보고 판단, API 호출 없음)."""
    b = resolve(book)
    base, bid = base_dir(book), b["id"]
    pages = len(list((base / "pages").glob("p*.json"))) if (base / "pages").exists() else 0
    tr = len(list((base / "transcripts").glob("p*.json"))) if (base / "transcripts").exists() else 0
    scope = json.load(open(DATA / "grade_scope_math1.json", encoding="utf-8")) if (DATA / "grade_scope_math1.json").exists() else {"books": {}}
    return {"id": bid, "label": b["label"], "totalPages": total_pages, "analyzedPages": pages, "aggregate": (base / "summary.json").exists(),
            "termLabels": (base / "term_kinds.json").exists(), "scope": bid in scope["books"], "style": (DATA / "textbook_style" / f"{bid}.json").exists(),
            "transcribedPages": tr, "selectable": bid in scope["books"]}
