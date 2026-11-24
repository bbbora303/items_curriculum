"""교과서 1권을 분석해 문항 생성기에서 고를 수 있게 만드는 전체 순서를 한 번에 계획·실행·점검한다.

  python pipeline.py status                         # 5종의 단계별 진행 상태(API 비용 없음)
  python pipeline.py plan --book dong_a             # 할 일과 예상 비용만 보여 줌(비용 없음)
  python pipeline.py run  --book dong_a [--yes]     # --yes 없이는 계획만 보여 주고 멈춘다. 유료 단계는 --yes 가 있어야 실행

단계(순서 고정): analyze(쪽별 분석, 유료) → aggregate(종합) → clean(용어 라벨, 유료 소액) → scope(중1 범위, 선택 목록에 열림)
                 → transcribe(원문 전사, 유료) → style(문체 자료). 완료된 쪽은 건너뛰므로 중간에 끊겨도 같은 명령을 다시 실행하면 이어서 한다.
비용은 천재(김동재) 실측으로 환산한 추정이다(단가는 추정, 실제 청구액은 콘솔에서 확인).
"""
import argparse
import os
import subprocess
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import books  # noqa: E402

# 천재(김동재) 324쪽 실측 토큰으로 계산: 분석 $0.0346/쪽, 전사 $0.056/쪽, 용어 라벨 약 $0.28 (옛 단가 $3/$15 기준) -> 공식 단가 $2/$10으로 환산(x2/3)
# 전사 대상은 책마다 달라(천재 24%, 동아 33%) 평균 30%로 본다
PER_PAGE_ANALYZE, PER_PAGE_TRANSCRIBE, TRANSCRIBE_SHARE, CLEAN_COST = 0.0346 * 2 / 3, 0.056 * 2 / 3, 0.30, 0.28 * 2 / 3
ALL_STEPS = ["analyze", "aggregate", "clean", "scope", "transcribe", "style"]
PAID = {"analyze", "clean", "transcribe"}


# 라이트 프로필: 입력은 무료 토큰 계산 실측(쪽당 폭 1100=3817, 900=3123, 800=2839 토큰), 출력은 6쪽 실측 평균 582토큰
LITE_INPUT = {1100: 3817, 900: 3123, 800: 2839}
LITE_OUTPUT = 582           # 6쪽 실측 평균(2026-10-21)
BATCH_FACTOR = 0.5


def per_page_analyze(profile="full", width=1100, batch=False):
    if profile == "full":
        c = PER_PAGE_ANALYZE
    else:
        inp = LITE_INPUT.get(width) or (3817 * width / 1100)
        c = inp * 2 / 1e6 + LITE_OUTPUT * 10 / 1e6
    return c * (BATCH_FACTOR if batch else 1.0)


def estimate(book, steps, total_pages, profile="full", width=1100, batch=False):
    st = books.status(book, total_pages)
    todo_pages = max(0, total_pages - st["analyzedPages"])
    rows = []
    if "analyze" in steps:
        how = f"{profile}, 폭 {width}px" + (", 배치(50% 할인)" if batch else "") + ("" if profile == "full" else "")
        rows.append(("analyze", f"쪽별 분석 {todo_pages}쪽 [{how}] (전체 {total_pages}쪽 중 완료 {st['analyzedPages']}쪽)", todo_pages * per_page_analyze(profile, width, batch)))
    if "aggregate" in steps:
        rows.append(("aggregate", "단원별 종합(용어 목록·단원 연결)", 0.0))
    if "clean" in steps:
        rows.append(("clean", "용어 종류 라벨 붙이기", 0.0 if st["termLabels"] else CLEAN_COST))
    if "scope" in steps:
        rows.append(("scope", "중1 범위 파일 생성 → 문항 생성기 선택 목록에 열림", 0.0))
    if "transcribe" in steps:
        n = round(total_pages * TRANSCRIBE_SHARE)
        rows.append(("transcribe", f"서술형·활동·통계 쪽 원문 전사 약 {n}쪽(분석 결과로 대상이 정해짐)", max(0, n - st["transcribedPages"]) * PER_PAGE_TRANSCRIBE))
    if "style" in steps:
        rows.append(("style", "문체·소재 자료 생성", 0.0))
    return rows


def prerequisites(book):
    info = books.units_info(book)
    problems = []
    if not info.get("units"):
        problems.append("차례 파일(textbook_units_math1.json)에 이 책의 단원 목록(units)이 없다. 먼저 차례를 정리해야 한다(scripts/build_textbook_units.py).")
    elif not any(su.get("standards") for u in info["units"] for su in u.get("subUnits", [])):
        problems.append("단원에 성취기준 연결(standards)이 없어 범위 파일을 만들 수 없다.")
    if info.get("note"):
        problems.append("차례 파일 메모: " + str(info["note"]))
    if not books.pdf_path(book).exists():
        problems.append(f"PDF 파일이 없다: {books.pdf_path(book)}")
    return problems


def cmd_status():
    print(f"{'id':<24}{'이름':<22}{'쪽 분석':>10}  종합 라벨 범위 문체 전사   선택가능")
    for b in books.registry():
        s = books.status(b["id"])
        total = ""
        try:
            total = f"/{books.page_count(b['id'])}"
        except Exception:
            pass
        mark = lambda x: "●" if x else "·"
        print(f"{b['id']:<24}{b['label']:<22}{str(s['analyzedPages']) + total:>10}   {mark(s['aggregate'])}    {mark(s['termLabels'])}    {mark(s['scope'])}    {mark(s['style'])}  {s['transcribedPages']:>4}쪽   {'예' if s['selectable'] else '아니오'}")


def cmd_plan(a, run=False):
    b = books.resolve(a.book)
    steps = [x for x in ALL_STEPS if x in a.steps.split(",")]
    total = books.page_count(b["id"])
    rows = estimate(b["id"], steps, total, a.profile, a.width, a.batch)
    print(f"== {b['label']} ({b['id']}), PDF {total}쪽")
    for name, desc, cost in rows:
        print(f"  {name:<11}{'[유료] ' if name in PAID else '[무료] '}{desc}  → 약 ${cost:.2f}")
    tot = sum(c for _, _, c in rows)
    print(f"  합계 약 ${tot:.2f} (추정 ±30%, 실제 청구액은 콘솔에서 확인)")
    probs = prerequisites(b["id"])
    for p in probs:
        print("  ⚠", p)
    return b, steps, tot, probs


def cmd_run(a):
    b, steps, tot, probs = cmd_plan(a, run=True)
    if probs and not a.force:
        print("선행 조건 문제가 있어 멈춥니다(무시하려면 --force).")
        return 1
    if any(s in PAID for s in steps) and not a.yes:
        print("유료 단계가 있어 계획만 보여 주고 멈춥니다. 진행하려면 --yes 를 붙여 다시 실행하세요.")
        return 0
    env = {**os.environ, "PYTHONUTF8": "1"}
    script = {"analyze": "analyze_book.py", "aggregate": "aggregate.py", "clean": "clean_terms.py", "scope": "build_scope.py", "transcribe": "transcribe_pages.py", "style": "build_style.py"}
    for s in steps:
        cmd = [sys.executable, str(HERE / script[s]), "--book", b["id"]]
        if s == "analyze" and a.batch:
            cmd = [sys.executable, str(HERE / "analyze_batch.py"), "submit", "--book", b["id"], "--profile", a.profile, "--width", str(a.width)]
            print(f"\n▶ analyze(배치 제출): {' '.join(cmd[1:])}", flush=True)
            r = subprocess.run(cmd, env=env)
            print("\n배치를 제출했습니다. 결과는 보통 수 분~수 시간 뒤에 나옵니다.")
            print(f"  1) python analyze_batch.py status  --book {b['id']}   (진행 확인)")
            print(f"  2) python analyze_batch.py collect --book {b['id']}   (끝난 뒤 저장)")
            print(f"  3) python pipeline.py run --book {b['id']} --steps aggregate,clean,scope,transcribe,style --yes   (나머지 단계)")
            return r.returncode
        if s == "analyze":
            cmd += ["--workers", "3", "--max-cost", str(round(a.max_cost, 2)), "--profile", a.profile, "--width", str(a.width)]
        if s == "transcribe":
            cmd += ["--workers", "3", "--max-cost", str(round(a.max_cost / 2, 2))]
        print(f"\n▶ {s}: {' '.join(cmd[1:])}", flush=True)
        r = subprocess.run(cmd, env=env)
        if r.returncode != 0:
            print(f"✖ {s} 단계가 실패해 멈춥니다(같은 명령을 다시 실행하면 이어서 합니다).")
            return r.returncode
    st = books.status(b["id"], books.page_count(b["id"]))
    print("\n완료 상태:", st)
    print("선택 가능:", "예 — 문항 생성기의 교과서 선택 목록에 나타납니다(서버 재시작 필요)." if st["selectable"] else "아니오")
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("--steps", default=",".join(ALL_STEPS))
        p.add_argument("--profile", default="full", choices=["full", "lite"], help="쪽 분석 프로필: full=정밀(실측), lite=필요한 항목만(출력량 미측정)")
        p.add_argument("--width", type=int, default=1100, help="쪽 이미지 폭(px)")
        p.add_argument("--batch", action="store_true", help="쪽 분석을 배치 API(50%% 할인, 비동기)로 제출한다(analyze_batch.py, 실제 API 미시험)")
        if name == "run":
            p.add_argument("--yes", action="store_true", help="유료 단계 실행을 승인한다")
            p.add_argument("--max-cost", type=float, default=15.0, help="쪽별 분석 단계의 추정 비용 한도(달러)")
            p.add_argument("--force", action="store_true", help="선행 조건 경고를 무시하고 진행")
    a = ap.parse_args()
    if a.cmd == "status":
        cmd_status()
    elif a.cmd == "plan":
        cmd_plan(a)
    else:
        sys.exit(cmd_run(a))


if __name__ == "__main__":
    main()
