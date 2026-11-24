"""풀이 판정(tiering.classify)의 정확도를 정답을 아는 사례로 확인한다 (유료: 사례 수만큼의 소액 호출, 약 $0.3).
기대 'out' = 상위 학년 내용이 꼭 필요한 풀이(확장으로 내려야 함), 'in' = 중1 범위 안(그대로 기본이어야 함).
사용: python test_tiering.py
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from common import DEFAULT_MODEL, Usage, client  # noqa: E402
import generate as G  # noqa: E402
import tiering  # noqa: E402

PILOT = HERE.parents[1] / "output" / "pilot"


def from_output(label, keyword, expect, std):
    it = json.load(open(PILOT / label / "item.json", encoding="utf-8"))
    ms = [m for m in it["solutionMethods"] if keyword in (m["name"] + m["summary"])]
    if not ms:
        for a in it["modelAnswers"]:
            for x in a["methods"]:
                if keyword in x["text"]:
                    ms = [m for m in it["solutionMethods"] if m["id"] == x["methodId"]]
    assert ms, (label, keyword)
    m = ms[0]
    item = {"standardCodes": [std], "intent": it.get("intent", ""), "generationMeta": it["generationMeta"], "solutionMethods": [m],
            "modelAnswers": [{"subNo": a["subNo"], "methods": [x for x in a["methods"] if x["methodId"] == m["id"]]} for a in it["modelAnswers"]]}
    return (f"{label}:{m['id']} {m['name'][:30]}", item, expect)


def synthetic(name, std, book, method, texts, expect):
    item = {"standardCodes": [std], "intent": "", "generationMeta": {"textbook": book},
            "solutionMethods": [{"id": "M9", **method}], "modelAnswers": [{"subNo": "1-1", "methods": [{"methodId": "M9", "text": t} for t in texts]}]}
    return (name, item, expect)


CASES = [
    from_output("dong_a_v2", "변의 수를 빼", "out", "9수03-05"),
    from_output("z_0305_none", "변을 ", "out", "9수03-05"),
    from_output("cheonjae_v2", "한 꼭짓점 기준", "in", "9수03-05"),
    from_output("x90204_dong_a", "괄호를 먼저 전개", "in", "9수02-04"),
    from_output("x90308_dong_a", "밑넓이×높이", "in", "9수03-08"),
    from_output("x90204_cheonjae_kim_dongjae", "등식의 성질", "in", "9수02-04"),
    synthetic("합성: 피타고라스 정리로 옆면 높이", "9수03-08", "dong_a", {"name": "피타고라스 정리로 사각뿔의 옆면의 높이를 구하기", "summary": "직각삼각형에서 빗변의 제곱은 두 변의 제곱의 합이므로 옆면의 높이를 구한 뒤 겉넓이를 구한다."},
              ["사각뿔의 높이 4 cm, 밑면 한 변 6 cm이므로 옆면의 높이 h는 $h^2=4^2+3^2$에서 $h=5$ (cm)이다. 옆면 삼각형의 넓이는 $\\frac12\\times6\\times5=15$ (cm²)이다."], "out"),
    synthetic("합성: 일차함수 그래프의 교점", "9수02-04", "cheonjae_kim_dongjae", {"name": "두 요금식을 일차함수 그래프로 그려 교점으로 비교하기", "summary": "두 요금을 y=ax+b 꼴의 일차함수 그래프로 그리고 두 그래프의 교점의 x좌표를 읽는다."},
              ["회원 요금은 $y=2000x+35000$, 비회원 요금은 $y=5500x$이다. 두 일차함수의 그래프를 그리면 교점의 x좌표가 10이므로 10회 이상이면 회원이 유리하다."], "out"),
]


def main():
    cl, usage = client(), Usage()
    ok = 0
    for name, item, expect in CASES:
        flags = tiering.classify(G.call, cl, usage, DEFAULT_MODEL, item)
        got = "out" if flags else "in"
        hit = got == expect
        ok += hit
        print(("통과" if hit else "실패"), "-", name, f"| 기대 {expect}, 결과 {got}", (f"| {flags[0]['laterTag']} '{flags[0]['quote'][:40]}'" if flags else ""), flush=True)
    print(f"\n{ok}/{len(CASES)} 일치, 사용량 {usage.total()}")


if __name__ == "__main__":
    main()
