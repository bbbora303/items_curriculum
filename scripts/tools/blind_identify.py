"""블라인드 식별 시험: 책 이름을 가린 문항 한 쌍을 AI에게 보여 주고 '어느 쪽이 어느 교과서용인가'를 맞히게 한다.

  python blind_identify.py --dry-run      # 쌍 목록과 예상 비용만 (API 호출 없음)
  python blind_identify.py --yes          # 실행 (유료, 쌍 x 2회[순서 바꿔서])

해석: 맞힌 비율이 우연(50%)보다 확실히 높아야 '교과서 선택이 문항을 바꾼다'고 말할 수 있다.
  - 쌍은 같은 성취기준·같은 시드의 천재 문항과 동아 문항(생성 시점의 코드 버전은 다를 수 있음).
  - 각 쌍을 A/B 순서를 바꿔 2번 묻는다(위치 편향 제거). 같은 문항이 여러 쌍에 쓰여 쌍들은 독립이 아니다.
  - AI는 두 교과서의 자료(학습 목표·성질·공식·풀이 방법 목록)를 받는다. 문항에서 책 이름·id·근거 번호·tier 표시는 지운다.
결과: docs/블라인드식별_결과.md
"""
import argparse
import itertools
import json
import math
import pathlib
import random
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
import scope_check  # noqa: E402

PILOT = ROOT / "output" / "pilot"
BOOKS = {"cheonjae_kim_dongjae": "천재교육(김동재)", "dong_a": "동아출판"}
# (성취기준, 천재 문항들, 동아 문항들) - 같은 시드·보통 난이도
GROUPS = [
    ("9수03-05", ["cheonjae_v2"], ["dong_a_check", "dong_a_v2", "z_0305_dong_a", "y_0305_dong_a"]),
    ("9수02-04", ["x90204_cheonjae_kim_dongjae", "y_0204_cheonjae"], ["x90204_dong_a"]),
    ("9수03-08", ["x90308_cheonjae_kim_dongjae", "w_0308_cheonjae"], ["x90308_dong_a"]),
]


def js(x):
    return json.dumps(x, ensure_ascii=False)


def blind_view(label):
    """책을 알려 주는 표시를 지운 문항 내용."""
    it = json.load(open(PILOT / label / "item.json", encoding="utf-8"))
    return {
        "제시문": it["stimulus"].get("text", ""),
        "소문항": [{"번호": q["no"], "배점": q["maxScore"], "발문": q["prompt"], "조건": [c["text"] for c in q.get("conditions", []) or []],
                  "평가요소": [e["text"] for e in q["evaluationElements"]]} for q in it["subQuestions"]],
        "풀이방법": [{"이름": m["name"], "요약": m["summary"]} for m in it["solutionMethods"]],
        "예시답안": [{"소문항": a["subNo"], "답": [x["text"][:700] for x in a["methods"]]} for a in it["modelAnswers"]],
    }


def book_material(std):
    out = {}
    for b, name in BOOKS.items():
        c = scope_check._core(std, b) or {}
        out[name] = {"학습 목표": c.get("goals", [])[:10], "성질·공식·풀이 방법": [f"({s['type']}) {s['text']}" for s in c.get("statements", [])[:14]]}
    return out


def prompt(std, a_label, b_label):
    s = scope_check._standards()[std]
    return f"""한국 중학교 1학년 수학 서술형 문항 두 개(문항 A, 문항 B)가 있습니다. 하나는 '{BOOKS['cheonjae_kim_dongjae']}' 교과서를 반영해 만든 것이고, 다른 하나는 '{BOOKS['dong_a']}' 교과서를 반영해 만든 것입니다. 어느 문항이 어느 교과서용인지 맞히세요.
성취기준 [{std}] {s['text']}

[두 교과서가 이 성취기준 단원에서 제시하는 내용]
{js(book_material(std))}

[문항 A]
{js(blind_view(a_label))}

[문항 B]
{js(blind_view(b_label))}

- 교과서가 가르치는 학습 목표, 성질·공식·풀이 방법의 표현과 순서, 용어, 소재가 문항에 어떻게 드러나는지를 근거로 판단한다.
- 어느 쪽으로도 판단할 근거가 없으면 confidence를 "낮음"으로 하고 그래도 하나를 고른다.
출력 JSON: {{"A는":"천재|동아","confidence":"높음|보통|낮음","근거":"두 문장 이내"}}"""


def build_pairs():
    pairs = []
    for std, cj, da in GROUPS:
        for c, d in itertools.product(cj, da):
            pairs.append((std, c, d))
    return pairs


def binom_p(k, n):
    """우연(0.5)일 때 n번 중 k번 이상 맞힐 확률(한쪽 검정)."""
    return sum(math.comb(n, i) for i in range(k, n + 1)) / 2 ** n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args()
    pairs = build_pairs()
    jobs = []
    for std, c, d in pairs:
        jobs.append((std, c, d, "cj_first"))    # A=천재, B=동아
        jobs.append((std, d, c, "da_first"))    # A=동아, B=천재
    est_in = sum(len(prompt(s, x, y)) for s, x, y, _ in jobs) * 0.9      # 글자 ≈ 토큰 0.9 (한글 위주 거친 추정)
    print(f"쌍 {len(pairs)}개 x 2(순서 교환) = 호출 {len(jobs)}회, 입력 약 {int(est_in):,} 토큰, 예상 비용 약 ${est_in * 3 / 1e6 + len(jobs) * 300 * 15 / 1e6:.2f} (추정)")
    for p in pairs:
        print("  ", p)
    if a.dry_run or not a.yes:
        return
    import generate as G
    from common import DEFAULT_MODEL, Usage, client
    cl, usage = client(), Usage()
    res = []
    for std, x, y, order in jobs:
        out = G.call(cl, usage, "블라인드식별", prompt(std, x, y), DEFAULT_MODEL, 6000)
        first = out.get("A는", "")
        truth_a = "천재" if order == "cj_first" else "동아"
        res.append({"std": std, "A": x, "B": y, "order": order, "답": first, "정답": truth_a, "맞음": first.startswith(truth_a), "confidence": out.get("confidence"), "근거": out.get("근거", "")})
        print(("맞음" if res[-1]["맞음"] else "틀림"), std, x, "vs", y, "|", out.get("confidence"), flush=True)
    n, k = len(res), sum(1 for r in res if r["맞음"])
    L = ["# 블라인드 식별 시험 결과", "", f"전체 {n}회 중 **{k}회 정답({100 * k / n:.0f}%)**. 우연(50%)이라면 이 이상 맞힐 확률 p = {binom_p(k, n):.3f} (한쪽 검정; 쌍이 문항을 공유해 독립이 아니므로 참고용).", "",
         "| 성취기준 | 문항 A | 문항 B | 순서 | AI 답(A는) | 정답 | 결과 | 확신 | 근거 |", "|---|---|---|---|---|---|---|---|---|"]
    for r in res:
        L.append(f"| {r['std']} | {r['A']} | {r['B']} | {r['order']} | {r['답']} | {r['정답']} | {'맞음' if r['맞음'] else '틀림'} | {r['confidence']} | {r['근거']} |")
    by = {}
    for r in res:
        by.setdefault(r["std"], []).append(r["맞음"])
    L += ["", "성취기준별 정답률: " + ", ".join(f"{s} {sum(v)}/{len(v)}" for s, v in by.items()), "", f"사용량(추정): {usage.total()}"]
    (ROOT / "docs" / "블라인드식별_결과.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:3]))
    print("저장: docs/블라인드식별_결과.md")


if __name__ == "__main__":
    main()
