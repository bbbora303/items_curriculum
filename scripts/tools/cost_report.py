"""파일에 남은 사용량 기록으로 API 비용을 다시 계산한다 (API 호출 없음).

  python cost_report.py

- 생성 문항: output/pilot/*/usage.json 의 토큰 수(저장된 문항만; 저장 못 한 실패 호출은 빠진다)
- 교과서 쪽 분석·전사: data/textbook_analysis/<책>/pages*/, transcripts/ 의 쪽별 _usage 토큰 수
  배치(50% 할인)로 돌린 책은 batch_state*.json 이 있으면 반값으로 계산한다.
단가는 scripts/gen/common.py 의 PRICE_PER_MTOK(공식 가격: claude-sonnet-5-5 입력 $2, 출력 $10 / 100만 토큰)이다.
2026-10-23 이전 문서에 적힌 비용은 옛 추정 단가($3/$15)로 계산해 실제의 약 1.5배다 (같은 토큰이면 옛 값 x 2/3).
토큰 수를 콘솔의 사용량과 대조하면 이 계산이 맞는지 확인할 수 있다. 실제 청구액은 Anthropic 콘솔에서 확인한다.
"""
import collections
import datetime
import os
import pathlib
import sys

import json

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
from common import OLD_PRICE_PER_MTOK, PRICE_PER_MTOK  # noqa: E402


def cost(tin, tout, price=PRICE_PER_MTOK):
    return tin / 1e6 * price["in"] + tout / 1e6 * price["out"]


def gen_rows():
    rows = []
    for f in (ROOT / "output").rglob("usage.json"):         # glob은 폴더 이름의 [math]를 문자 모음으로 읽어 쓰지 않는다
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        tot = d.get("total") or {}
        day = datetime.datetime.fromtimestamp(os.path.getmtime(f)).date().isoformat()
        rows.append((day, f.parent.name, tot.get("in", 0), tot.get("out", 0)))
    return rows


def page_tokens(folder):
    n = tin = tout = 0
    for f in folder.glob("p*.json"):
        try:
            u = json.load(open(f, encoding="utf-8")).get("_usage") or {}
        except Exception:
            continue
        tin += u.get("in", 0)
        tout += u.get("out", 0)
        n += 1
    return n, tin, tout


def main():
    rows = gen_rows()
    by = collections.defaultdict(lambda: [0, 0, 0])
    for d, _, i, o in rows:
        by[d][0] += 1
        by[d][1] += i
        by[d][2] += o
    print(f"단가: 입력 ${PRICE_PER_MTOK['in']}/출력 ${PRICE_PER_MTOK['out']} (100만 토큰당, 공식). 옛 추정 ${OLD_PRICE_PER_MTOK['in']}/${OLD_PRICE_PER_MTOK['out']}")
    print("[생성 문항] 날짜별(저장된 문항만)")
    gi = go = 0
    for d, (n, i, o) in sorted(by.items()):
        gi += i
        go += o
        print(f"  {d}: {n}건 입력 {i:,} 출력 {o:,} 토큰 → ${cost(i, o):.2f} (옛 단가 ${cost(i, o, OLD_PRICE_PER_MTOK):.2f})")
    print(f"  합계 {len(rows)}건 → ${cost(gi, go):.2f}")
    print("[교과서 쪽 분석·전사] (배치로 돌렸으면 반값이 실제 청구)")
    total = 0.0
    ti, to = 0, 0
    for bp in sorted((ROOT / "data" / "textbook_analysis").iterdir()):
        if not bp.is_dir():
            continue
        for sub in sorted(x for x in bp.iterdir() if x.is_dir()):
            n, i, o = page_tokens(sub)
            if n:
                batch = sub.name.startswith("pages_batch") or (sub.name == "pages" and list(bp.glob("batch_state.json")))
                real = cost(i, o) * (0.5 if batch else 1.0)
                total += real
                ti += i
                to += o
                print(f"  {bp.name}/{sub.name}: {n}쪽 입력 {i:,} 출력 {o:,} → ${real:.2f}" + (" (배치 반값)" if batch else ""))
    print(f"  합계 ${total:.2f}")
    print(f"[기록으로 확인되는 총액] ${cost(gi, go) + total:.2f}  (입력 {gi + ti:,} / 출력 {go + to:,} 토큰, 배치 할인 전 토큰 기준)")
    print("그 밖의 지출(용어 라벨, 풀이 판정 시험, 저장 못 한 실패 호출)은 이 기록에 없다. 인수인계.md 4-10의 표를 본다.")


if __name__ == "__main__":
    main()
