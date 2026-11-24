"""쪽 분석을 배치 API로 실행한다 (비용 50% 할인, 결과는 보통 수 분~수 시간 뒤에 받는다).

  python analyze_batch.py submit  --book dong_a [--profile lite] [--width 1100] [--pages 1-100] [--chunk 60] [--dry-run]
  python analyze_batch.py status  --book dong_a        # 배치 진행 상태(비용 없음)
  python analyze_batch.py collect --book dong_a        # 끝난 배치의 결과를 쪽 JSON으로 저장(비용 없음, 완료된 것만)

- 쪽 JSON은 analyze_book.py(실시간)와 같은 형식이라 이후 단계(aggregate 등)는 그대로 쓴다. 이미 있는 쪽은 건너뛴다.
- --dry-run: 요청을 만들어 크기만 계산하고 호출하지 않는다(비용 없음).
- 실패·형식 오류 쪽은 error 파일로 남으므로, 그 쪽만 analyze_book.py로 다시 하면 된다.
⚠ 이 스크립트의 submit/collect는 아직 실제 API로 시험하지 않았다(시험용 3쪽 배치 권장).
"""
import argparse
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
import analyze_book as AB  # noqa: E402
import analyze_lite  # noqa: E402
import books  # noqa: E402
from common import DEFAULT_MODEL, PRICE_PER_MTOK, client, extract_json  # noqa: E402
import pymupdf  # noqa: E402

BATCH_FACTOR = 0.5


def state_path(bid, tag=""):
    return ROOT / "data" / "textbook_analysis" / bid / (f"batch_state_{tag}.json" if tag else "batch_state.json")


def load_state(bid, tag=""):
    p = state_path(bid, tag)
    return json.load(open(p, encoding="utf-8")) if p.exists() else {"batches": []}


def cmd_submit(a, bk):
    book, units = AB.book_info(bk["unitsKey"])
    doc = pymupdf.open(ROOT / "docu" / book["pdf"])
    out_dir = ROOT / "data" / "textbook_analysis" / bk["id"] / (f"pages_{a.tag}" if a.tag else "pages")
    out_dir.mkdir(parents=True, exist_ok=True)
    st = load_state(bk["id"], a.tag)
    pending = {p for b in st["batches"] for p in b["pages"]}
    todo = [i for i in AB.parse_pages(a.pages, len(doc)) if not (out_dir / f"p{i + 1:04d}.json").exists() and (i + 1) not in pending]
    print(f"{bk['label']}: 대상 {len(todo)}쪽(이미 분석됨/배치 진행 중인 쪽 제외), 프로필 {a.profile}, 폭 {a.width}px, 묶음 {a.chunk}쪽", flush=True)
    if not todo:
        return
    cl = None if a.dry_run else client()
    for k in range(0, len(todo), a.chunk):
        part = todo[k:k + a.chunk]
        reqs, size = [], 0
        for i in part:
            r = analyze_lite.build_request(AB, doc, i, units, a.profile, a.width)
            size += len(json.dumps(r["content"], ensure_ascii=False))
            reqs.append({"custom_id": f"p{i + 1:04d}", "params": {"model": a.model, "max_tokens": r["max_tokens"], "system": r["system"],
                                                                 "messages": [{"role": "user", "content": r["content"]}]}})
        print(f"  묶음 {k // a.chunk + 1}: {len(reqs)}쪽, 요청 크기 약 {size / 1e6:.1f}MB", flush=True)
        if a.dry_run:
            continue
        b = cl.messages.batches.create(requests=reqs)
        st["batches"].append({"id": b.id, "pages": [i + 1 for i in part], "profile": a.profile, "width": a.width, "model": a.model, "submitted": time.time()})
        state_path(bk["id"], a.tag).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    제출: {b.id}", flush=True)
    print("끝. status/collect 로 확인하세요." if not a.dry_run else "dry-run 끝(호출 없음).")


def cmd_status(a, bk):
    st, cl = load_state(bk["id"], a.tag), client()
    for b in st["batches"]:
        r = cl.messages.batches.retrieve(b["id"])
        c = r.request_counts
        print(f"{b['id']} | {len(b['pages'])}쪽 | 상태 {r.processing_status} | 성공 {c.succeeded} 오류 {c.errored} 처리중 {c.processing} 취소 {c.canceled} 만료 {c.expired}")


def cmd_collect(a, bk):
    st, cl = load_state(bk["id"], a.tag), client()
    out_dir = ROOT / "data" / "textbook_analysis" / bk["id"] / (f"pages_{a.tag}" if a.tag else "pages")
    ledger = {"in": 0, "out": 0, "ok": 0, "fail": 0}
    for b in st["batches"]:
        if b.get("collected"):
            continue
        r = cl.messages.batches.retrieve(b["id"])
        if r.processing_status != "ended":
            print(f"{b['id']}: 아직 {r.processing_status} — 나중에 다시 collect 하세요")
            continue
        for ent in cl.messages.batches.results(b["id"]):
            n = int(ent.custom_id[1:])
            f = out_dir / f"p{n:04d}.json"
            if ent.result.type != "succeeded":
                (out_dir / f"p{n:04d}.error.txt").write_text(f"배치 결과: {ent.result.type}", encoding="utf-8")
                ledger["fail"] += 1
                continue
            msg = ent.result.message
            txt = "".join(x.text for x in msg.content if x.type == "text")
            try:
                d = extract_json(txt)
            except Exception as e:
                (out_dir / f"p{n:04d}.error.txt").write_text(f"JSON 오류: {e}\n{txt[:2000]}", encoding="utf-8")
                ledger["fail"] += 1
                continue
            d["_page"], d["_profile"] = n, b["profile"]
            d["_usage"] = {"in": msg.usage.input_tokens, "out": msg.usage.output_tokens, "sec": 0, "stop": msg.stop_reason, "batch": True}
            f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
            ledger["in"] += msg.usage.input_tokens
            ledger["out"] += msg.usage.output_tokens
            ledger["ok"] += 1
        b["collected"] = True
        state_path(bk["id"], a.tag).write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    cost = (ledger["in"] / 1e6 * PRICE_PER_MTOK["in"] + ledger["out"] / 1e6 * PRICE_PER_MTOK["out"]) * BATCH_FACTOR
    print(f"저장 {ledger['ok']}쪽, 실패 {ledger['fail']}쪽 | 입력 {ledger['in']} 출력 {ledger['out']} | 배치 할인 적용 추정 ${cost:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["submit", "status", "collect"])
    ap.add_argument("--book", required=True)
    ap.add_argument("--profile", default="lite", choices=["full", "lite"])
    ap.add_argument("--width", type=int, default=AB.IMG_WIDTH)
    ap.add_argument("--pages", default="")
    ap.add_argument("--chunk", type=int, default=60)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tag", default="", help="시험용: 결과를 pages_<tag>에 저장하고 상태 파일도 따로 둔다")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    bk = books.resolve(a.book)
    {"submit": cmd_submit, "status": cmd_status, "collect": cmd_collect}[a.cmd](a, bk)


if __name__ == "__main__":
    main()
