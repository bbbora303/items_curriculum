"""교과서 1권을 쪽마다 이미지+글자층으로 정밀 분석한다 (쪽 단위 JSON 저장, 중단 후 이어서 가능).

사용: python analyze_book.py --book 천재(김동재) --pages 1-6 --workers 3 [--max-cost 12]
결과: data/textbook_analysis/<책 id>/pages/p0001.json (쪽 번호는 PDF 쪽 순서, 인쇄된 쪽 번호는 printedPage)
비용: 쪽마다 입력(이미지+글자) 약 3천 토큰, 출력 약 1천 토큰 안팎(단가는 추정). --max-cost(달러, 추정)를 넘으면 멈춘다.
이미지가 기준이고 글자층은 보조다(글자층은 수식 기호가 깨진다).
"""
import argparse
import base64
import concurrent.futures as cf
import json
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
from common import DEFAULT_MODEL, PRICE_PER_MTOK, client, extract_json  # noqa: E402
import pymupdf  # noqa: E402

DATA = ROOT / "data"
IMG_WIDTH = 1100

SYSTEM = """당신은 한국 중학교 수학 교과서를 구조적으로 분석하는 도우미입니다. 한 쪽의 이미지(기준)와 PDF 글자층(보조, 수식 기호가 깨져 있음)을 받아 아래 JSON 한 개만 출력합니다. 설명 문장·코드 블록 표시는 쓰지 않습니다.
원칙:
- 이미지에 실제로 보이는 것만 적는다. 보이지 않는 내용을 추측해 채우지 않는다. 읽기 어렵거나 확실하지 않으면 notes에 적는다.
- 수식은 LaTeX($...$)로 옮긴다(JSON 문자열 안에서 역슬래시는 두 번: \\\\frac). 글자층의 깨진 기호(€, ‹ 같은 것)는 무시하고 이미지를 따른다.
- 교과서 문장을 길게 옮기지 말고 핵심만 짧게 요약한다(문제는 발문의 핵심과 숫자 구조만).
- 학년 판별이 목적이다: 이 쪽에서 새로 정의·도입되는 용어/기호/성질(role=정의)과, 이미 배웠다고 전제하고 쓰는 것(role=사용)을 구별한다. 단원 도입 쪽의 '배운 내용 / 이 단원의 내용 / 배울 내용(중2·중3 표시)'은 gradeLinks에 그대로 옮긴다.
- 쪽 위·아래의 단원 표시(예: '1. 소인수분해', '대단원 마무리')와 소단원 번호·제목이 보이면 unit에 적고, 보이지 않으면 빈 문자열로 둔다.
출력 JSON 형식(모든 키를 쓰고 해당 없으면 빈 배열/빈 문자열):
{"printedPage":"쪽 아래에 인쇄된 쪽 번호(없으면 빈 문자열)",
 "unit":{"chapter":"대단원 이름(예: 소인수분해)","section":"소단원 번호와 제목(예: 03 최소공배수)","area":"교재 코너명(예: 배우고 익히기, 와글와글 수학 활동, 서술형 문제, 대단원 마무리, 단원 도입, 개념 설명 등)"},
 "pageType":"표지|차례|단원도입|개념설명|예제|연습문제|탐구활동|읽기자료|서술형문제|단원마무리|자기평가|부록|기타 중 하나(여러 성격이면 가장 큰 것)",
 "terms":[{"term":"용어","role":"정의|사용","definition":"정의를 한 문장으로(role=정의일 때)","notation":"기호가 있으면 LaTeX"}],
 "symbols":[{"symbol":"LaTeX","meaning":"뜻","role":"정의|사용"}],
 "statements":[{"kind":"정의|성질|공식|법칙|방법","latex":"LaTeX 또는 짧은 문장","plain":"쉬운 한 문장 설명"}],
 "examples":[{"title":"예제/예시/보기 이름","kind":"계산|식세우기|판단|그리기|설명|기타","summary":"한 문장 요약","solutionShown":true}],
 "problems":[{"label":"문제 번호","level":"기본|심화(+표시)|서술형|활동","verb":"발문 끝 반응 지시어(구하시오, 설명하시오 등)","kind":"계산|식세우기|판단|그리기|설명|탐구|기타","summary":"발문 핵심 한 문장","competencyIcons":["아이콘 라벨(추론, 문제해결, 의사소통, 연결, 정보처리 등)"],"hasFigureOrTable":true}],
 "figures":[{"kind":"수직선|표|도형|그래프|좌표평면|모형|그림|사진|기타","role":"개념 설명|문제 자료|활동|장식","desc":"한 문장"}],
 "contexts":["실생활 소재(예: 전기 자동차, 요금, 기온)"],
 "gradeLinks":{"prior":["배운 내용"],"current":["이 단원의 내용"],"later":[{"item":"배울 내용","grade":"중2|중3|고"}]},
 "competencies":["이 쪽에 표시된 교과 역량 아이콘"],
 "selfAssessment":[{"concept":"자기평가표(예: Math Pizza)에 나온 개념 이름","problemNos":["문항 번호"]}],
 "notes":"읽기 어려웠거나 불확실한 부분, 분류가 애매한 점(없으면 빈 문자열)"}"""


def book_info(name):
    d = json.load(open(DATA / "textbook_units_math1.json", encoding="utf-8"))
    b = d["books"][name]
    return b, [u["title"] for u in b["units"]]


def render(doc, i, width=IMG_WIDTH):
    pg = doc[i]
    z = width / pg.rect.width
    png = pg.get_pixmap(matrix=pymupdf.Matrix(z, z)).tobytes("png")
    return base64.b64encode(png).decode(), pg.get_text()


def analyze_page(cl, doc, i, units, model, out_dir, ledger, lock, profile="full", width=IMG_WIDTH):
    f = out_dir / f"p{i + 1:04d}.json"
    if f.exists():
        return "skip"
    import analyze_lite
    req = analyze_lite.build_request(sys.modules[__name__], doc, i, units, profile, width)
    user_text, content = req["user_text"], req["content"]
    last = None
    for attempt in range(2):
        t0 = time.time()
        extra = {} if attempt == 0 else {"extra": 1}
        msg = content if attempt == 0 else content[:-1] + [{"type": "text", "text": user_text + f"\n[주의] 직전 출력이 올바른 JSON이 아니었다({last}). JSON 객체 하나만 출력한다."}]
        with cl.messages.stream(model=model, max_tokens=req["max_tokens"], system=req["system"], messages=[{"role": "user", "content": msg}]) as s:
            resp = s.get_final_message()
        inn, out = resp.usage.input_tokens, resp.usage.output_tokens
        with lock:
            ledger["in"] += inn
            ledger["out"] += out
        txt = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "max_tokens":
            last = "max_tokens"
            continue
        try:
            data = extract_json(txt)
        except Exception as e:
            last = str(e)[:80]
            continue
        data["_page"] = i + 1
        data["_profile"] = profile
        data["_usage"] = {"in": inn, "out": out, "sec": round(time.time() - t0, 1), "stop": resp.stop_reason}
        f.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return "ok"
    (out_dir / f"p{i + 1:04d}.error.txt").write_text(f"실패: {last}\n{txt[:3000]}", encoding="utf-8")
    return "fail"


def parse_pages(s, n):
    if not s:
        return list(range(n))
    out = []
    for part in s.split(","):
        a, _, b = part.partition("-")
        out += list(range(int(a) - 1, int(b or a)))
    return [p for p in out if 0 <= p < n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    ap.add_argument("--pages", default="", help="예: 1-6,40,100-110 (PDF 쪽 순서, 1부터). 비우면 전체")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--max-cost", type=float, default=12.0, help="추정 비용(달러)이 이 값을 넘으면 새 쪽 분석을 멈춘다")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--tag", default="", help="시험용: 결과를 pages_<tag> 폴더에 저장(기존 pages는 건드리지 않음)")
    ap.add_argument("--profile", default="full", choices=["full", "lite"], help="full=정밀(쪽당 약 $0.035), lite=이후 단계가 쓰는 항목만(출력 1/3~1/4, 미측정)")
    ap.add_argument("--width", type=int, default=IMG_WIDTH, help="이미지 폭(px). 줄이면 입력이 줄지만 작은 글자를 못 읽을 수 있다")
    a = ap.parse_args()
    import books
    bk = books.resolve(a.book)
    a.book = bk["unitsKey"]
    book, units = book_info(a.book)
    doc = pymupdf.open(ROOT / "docu" / book["pdf"])
    bid = bk["id"]
    out_dir = DATA / "textbook_analysis" / bid / (f"pages_{a.tag}" if a.tag else "pages")
    out_dir.mkdir(parents=True, exist_ok=True)
    pages = parse_pages(a.pages, len(doc))
    todo = [i for i in pages if not (out_dir / f"p{i + 1:04d}.json").exists()]
    print(f"{a.book}: 전체 {len(doc)}쪽 중 대상 {len(pages)}쪽, 새로 분석할 쪽 {len(todo)}쪽, 동시 {a.workers}", flush=True)
    cl = client()
    ledger = {"in": 0, "out": 0}
    lock = threading.Lock()
    stop = threading.Event()
    stat = {"ok": 0, "fail": 0}

    def cost():
        return ledger["in"] / 1e6 * PRICE_PER_MTOK["in"] + ledger["out"] / 1e6 * PRICE_PER_MTOK["out"]

    def work(i):
        if stop.is_set():
            return i, "stopped"
        try:
            r = analyze_page(cl, doc, i, units, a.model, out_dir, ledger, lock, a.profile, a.width)
        except Exception as e:  # 네트워크 오류 등: 다음 실행에서 이어서
            (out_dir / f"p{i + 1:04d}.error.txt").write_text(f"예외: {type(e).__name__}: {e}", encoding="utf-8")
            r = "fail"
        with lock:
            stat["ok" if r in ("ok", "skip") else "fail"] += 1
            done = stat["ok"] + stat["fail"]
        if r == "ok" and (done % 10 == 0 or done <= 3):
            print(f"  {done}/{len(todo)}쪽 | 입력 {ledger['in']} 출력 {ledger['out']} | 추정 ${cost():.2f}", flush=True)
        if cost() > a.max_cost and not stop.is_set():
            stop.set()
            print(f"!! 추정 비용 ${cost():.2f}가 한도 ${a.max_cost}를 넘어 새 쪽 분석을 멈춘다", flush=True)
        return i, r

    t0 = time.time()
    with cf.ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(work, todo))
    bad = [i + 1 for i, r in results if r == "fail"]
    left = [i + 1 for i, r in results if r == "stopped"]
    print(f"끝: 성공 {stat['ok']}쪽, 실패 {len(bad)}쪽 {bad[:20]}, 미처리 {len(left)}쪽 | 입력 {ledger['in']} 출력 {ledger['out']} | 추정 비용 ${cost():.2f} | {time.time() - t0:.0f}초")


if __name__ == "__main__":
    main()
