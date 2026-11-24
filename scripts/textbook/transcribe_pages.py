"""교과서의 일부 쪽을 요약 없이 원문 그대로 전사한다 (목적별 부분 재분석, 쪽 단위 JSON, 이어서 가능).

대상(--targets, 쉼표로 여러 개):
  essay    '서술형 문제'가 있는 쪽 (책별 형식 예시용)
  activity 탐구활동 유형 쪽 (활동 원문, 진행 방법)
  stats    통계 단원의 표·그래프 쪽 (표 값 전부, 그래프 값)
  concept  개념 설명 쪽 (성질·공식·풀이 방법의 원문)
결과: data/textbook_analysis/<책 id>/transcripts/p0061.json
쪽 분석(analyze_book.py)과 달리 문제·활동의 원문, 표의 모든 칸, 그래프·도형의 값과 표시를 빠짐없이 적는다. 읽지 못한 곳은 추측하지 않고 incomplete에 적는다.
사용: python transcribe_pages.py --targets essay,stats,activity --workers 3 --max-cost 6
"""
import argparse
import concurrent.futures as cf
import json
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
sys.path.insert(0, str(HERE))
from common import DEFAULT_MODEL, PRICE_PER_MTOK, client, extract_json  # noqa: E402
import analyze_book as AB  # noqa: E402
import pymupdf  # noqa: E402

DATA = ROOT / "data"
SYSTEM = """당신은 한국 중학교 수학 교과서의 쪽을 원문 그대로 옮겨 적는 도우미입니다. 한 쪽의 이미지(기준)와 PDF 글자층(보조, 수식 기호가 깨져 있음)을 받아 아래 JSON 한 개만 출력합니다. 설명 문장·코드 블록 표시는 쓰지 않습니다.
원칙:
- **요약하지 않는다.** 문제·활동·읽기 자료·말풍선 대화의 문장은 보이는 그대로 옮긴다. 수식은 LaTeX($...$, JSON 문자열 안에서 역슬래시는 두 번: \\\\frac).
- 표는 **모든 칸의 값**을 rows에 옮긴다. 그래프·도형·수직선·좌표평면은 눈금·값·이름·길이·각도 표시를 빠짐없이 적는다.
- 이미지에 보이는 것만 적는다. 읽기 어렵거나 가려진 부분은 추측해 채우지 말고 incomplete에 적는다. 계산해서 얻은 값, 정답, 해석을 덧붙이지 않는다(보이는 것만).
- 쪽에 있는 모든 코너(예: 서술형 문제, 와글와글 수학 활동, 생각 열기, FUN, 참고)를 items에 하나씩 넣는다. 작은 FUN 코너의 한 줄 질문도 놓치지 않는다.
출력 JSON 형식(모든 키를 쓰고 해당 없으면 빈 배열/빈 문자열):
{"printedPage":"쪽 아래 인쇄된 쪽 번호","pageType":"서술형문제|탐구활동|개념설명|연습문제|단원마무리|기타 중 하나",
 "items":[{"kind":"서술형문제|활동|문제|예제|읽기자료|생각열기|FUN|참고|기타","label":"번호 또는 코너 이름","corner":"코너명","icons":["역량 아이콘 라벨"],"level":"기본|심화(+표시)|서술형|활동|",
   "text":"원문 전체(제시문, 발문, 말풍선 포함)","subItems":[{"label":"(1)","text":"원문"}],"conditions":["<조건> 원문"],"given":"문제에 주어진 수치·자료를 있는 그대로","steps":["진행 방법·활동 순서 원문"],"answerFormat":"답안 형식(빈칸, 표, 그림 그리기, 서술 등)"}],
 "tables":[{"caption":"","unit":"","headers":[],"rows":[[]],"source":"출처 문구"}],
 "graphs":[{"type":"막대|꺾은선|히스토그램|도수분포다각형|원|띠|줄기와 잎|좌표평면|기타","title":"","xAxis":"","yAxis":"","values":"각 막대·점·계급의 값을 모두(예: 계급 40이상~50미만: 3)","note":""}],
 "figures":[{"kind":"도형|수직선|모형|좌표평면|기타","caption":"","labels":"점·변·각 이름과 길이·각도·눈금 값 전부","desc":""}],
 "incomplete":"읽지 못한 부분(없으면 빈 문자열)"}"""


def stats_chapters(book):
    """이 책에서 영역이 '자료와 가능성'인 대단원 이름들(책마다 단원 이름이 다르다)."""
    import books
    return {u["title"] for u in books.units_info(book).get("units", []) if u.get("domain") == "자료와 가능성"}


def targets(base, kinds, stat_chapters=("자료의 정리와 해석",)):
    pages = {}
    for f in (base / "pages").glob("p*.json"):
        d = json.load(open(f, encoding="utf-8"))
        pages[d["_page"]] = d
    out = {}
    if "essay" in kinds:
        for n, d in pages.items():
            if d["pageType"] == "서술형문제" or d.get("essay") or any(p.get("level") == "서술형" for p in d.get("problems", [])):
                out.setdefault(n, []).append("essay")
    if "activity" in kinds:
        for n, d in pages.items():
            if d["pageType"] == "탐구활동":
                out.setdefault(n, []).append("activity")
    if "concept" in kinds:                      # 개념 설명 쪽: 성질·공식·풀이 방법의 교과서 원문 (교과서 진술 자료의 근거)
        for n, d in pages.items():
            if d["pageType"] == "개념설명" and d.get("statements"):
                out.setdefault(n, []).append("concept")
    if "stats" in kinds:
        for n, d in pages.items():
            if d["unit"]["chapter"] in stat_chapters and d["pageType"] not in ("표지", "차례", "부록", "기타")                     and (d.get("dataFigures") or any(g.get("figureType") in ("표", "그래프") and g.get("role") != "장식" for g in d.get("figures", []))):
                out.setdefault(n, []).append("stats")
    return dict(sorted(out.items()))


def one(cl, doc, i, model, out_dir, ledger, lock, why):
    f = out_dir / f"p{i + 1:04d}.json"
    if f.exists():
        return "skip"
    b64, text = AB.render(doc, i)
    user = f"PDF 쪽 순서 {i + 1}번째 쪽입니다(목적: {','.join(why)}).\n[글자층(보조, 수식 깨짐)]\n{text[:6000]}\n\n위 이미지를 요약 없이 전사해 JSON을 출력하세요."
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}}, {"type": "text", "text": user}]
    last, txt = None, ""
    for attempt in range(2):
        t0 = time.time()
        c = content if attempt == 0 else content[:-1] + [{"type": "text", "text": user + f"\n[주의] 직전 출력이 올바른 JSON이 아니었다({last}). JSON 객체 하나만 출력한다."}]
        with cl.messages.stream(model=model, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": c}]) as s:
            r = s.get_final_message()
        with lock:
            ledger["in"] += r.usage.input_tokens
            ledger["out"] += r.usage.output_tokens
        txt = "".join(b.text for b in r.content if b.type == "text")
        if r.stop_reason == "max_tokens":
            last = "max_tokens"
            continue
        try:
            d = extract_json(txt)
        except Exception as e:
            last = str(e)[:80]
            continue
        d["_page"] = i + 1
        d["_why"] = why
        d["_usage"] = {"in": r.usage.input_tokens, "out": r.usage.output_tokens, "sec": round(time.time() - t0, 1), "stop": r.stop_reason}
        f.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        return "ok"
    (out_dir / f"p{i + 1:04d}.error.txt").write_text(f"실패: {last}\n{txt[:3000]}", encoding="utf-8")
    return "fail"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    ap.add_argument("--targets", default="essay,stats,activity")
    ap.add_argument("--only", default="", help="쉼표로 구분한 쪽 번호만 전사(시험용)")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-cost", type=float, default=6.0)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    import books
    bk = books.resolve(a.book)
    a.book, bid = bk["unitsKey"], bk["id"]
    base = DATA / "textbook_analysis" / bid
    out_dir = base / "transcripts"
    out_dir.mkdir(exist_ok=True)
    book, _ = AB.book_info(a.book)
    doc = pymupdf.open(ROOT / "docu" / book["pdf"])
    tg = targets(base, set(a.targets.split(",")), stats_chapters(a.book))
    if a.only:
        keep = {int(x) for x in a.only.split(",")}
        tg = {n: w for n, w in tg.items() if n in keep}
    todo = {n: w for n, w in tg.items() if not (out_dir / f"p{n:04d}.json").exists()}
    print(f"대상 {len(tg)}쪽(목적별: " + ", ".join(f"{k} {sum(1 for w in tg.values() if k in w)}" for k in ('essay', 'activity', 'stats')) + f"), 새로 전사할 쪽 {len(todo)}쪽", flush=True)
    cl = client()
    ledger, lock, stop, stat = {"in": 0, "out": 0}, threading.Lock(), threading.Event(), {"ok": 0, "fail": 0}

    def cost():
        return ledger["in"] / 1e6 * PRICE_PER_MTOK["in"] + ledger["out"] / 1e6 * PRICE_PER_MTOK["out"]

    def work(item):
        n, why = item
        if stop.is_set():
            return n, "stopped"
        try:
            r = one(cl, doc, n - 1, a.model, out_dir, ledger, lock, why)
        except Exception as e:
            (out_dir / f"p{n:04d}.error.txt").write_text(f"예외: {type(e).__name__}: {e}", encoding="utf-8")
            r = "fail"
        with lock:
            stat["ok" if r in ("ok", "skip") else "fail"] += 1
            done = stat["ok"] + stat["fail"]
        if done % 10 == 0 or done <= 2:
            print(f"  {done}/{len(todo)}쪽 | 입력 {ledger['in']} 출력 {ledger['out']} | 추정 ${cost():.2f}", flush=True)
        if cost() > a.max_cost and not stop.is_set():
            stop.set()
            print(f"!! 추정 비용 ${cost():.2f}가 한도 ${a.max_cost}를 넘어 새 쪽 전사를 멈춘다", flush=True)
        return n, r

    t0 = time.time()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(work, todo.items()))
    bad = [n for n, r in res if r == "fail"]
    left = [n for n, r in res if r == "stopped"]
    print(f"끝: 성공 {stat['ok']}쪽, 실패 {len(bad)}쪽 {bad[:20]}, 미처리 {len(left)}쪽 | 입력 {ledger['in']} 출력 {ledger['out']} | 추정 ${cost():.2f} | {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
