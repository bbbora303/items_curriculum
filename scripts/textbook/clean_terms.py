"""용어 목록에 종류 라벨을 붙인다(원본은 지우지 않는다). 결과: data/textbook_analysis/<id>/term_kinds.json

쪽 단위 분석이 용어로 잡은 것에는 수학 개념 말고도 활동 소재(골 득실 차, 점묘법), 계산 주제 소제목(유리수의 덧셈)이 섞여 있다.
라벨: 개념용어(정의·성질·기호·방법의 이름) / 계산주제(계산·절 소제목) / 소재·활동(실생활·예술·활동 이야기) / 기타
사용: python clean_terms.py [--book 천재(김동재)]
"""
import argparse
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
import sys as _sys
_sys.path.insert(0, str(HERE))
import books  # noqa: E402
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
from common import DEFAULT_MODEL, client, extract_json  # noqa: E402

SYSTEM = """당신은 중학교 1학년 수학 교과서의 용어 목록을 정리하는 도우미입니다. 각 항목이 어떤 종류인지 라벨을 붙입니다. 출력은 JSON 한 개만 씁니다.
라벨: "개념용어"(수학 개념·정의·성질·기호·방법·도형·수의 이름), "계산주제"(계산이나 절의 소제목, 예: 유리수의 덧셈, 단항식을 수로 나누기), "소재·활동"(실생활·예술·활동에 나온 말, 예: 점묘법, 픽셀, 인포그래픽), "기타".
성질의 이름(교환법칙 등)과 도형·입체의 이름(삼각뿔대 등)은 개념용어다. 판단이 애매하면 정의 문장을 보고 정한다. 모든 항목에 라벨을 하나씩 붙인다."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="천재(김동재)")
    a = ap.parse_args()
    bk = books.resolve(a.book)
    a.book, bid = bk["unitsKey"], bk["id"]      # --book은 id·차례 이름 모두 받는다
    g = json.load(open(ROOT / "data" / f"grade1_terms_{bid}.json", encoding="utf-8"))
    items = [{"term": t["term"], "def": (t.get("definition") or "")[:80], "chapter": t["chapter"]} for t in g["defined"]]
    items += [{"term": t, "def": "", "chapter": "(정의 없이 쓰임)"} for t in g["assumedFromEarlier"]]
    cl = client()
    kinds, usage = {}, {"in": 0, "out": 0}
    for i in range(0, len(items), 130):
        chunk = items[i:i + 130]
        user = ("다음 항목에 라벨을 붙이세요. 출력 형식: {\"labels\": {\"용어\": \"라벨\"}}\n" + json.dumps(chunk, ensure_ascii=False))
        with cl.messages.stream(model=DEFAULT_MODEL, max_tokens=16000, system=SYSTEM, messages=[{"role": "user", "content": user}]) as s:
            r = s.get_final_message()
        usage["in"] += r.usage.input_tokens
        usage["out"] += r.usage.output_tokens
        txt = "".join(b.text for b in r.content if b.type == "text")
        kinds.update(extract_json(txt)["labels"])
        print(f"  {min(i + 130, len(items))}/{len(items)}", flush=True)
    missing = [x["term"] for x in items if x["term"] not in kinds]
    out = ROOT / "data" / "textbook_analysis" / bid / "term_kinds.json"
    out.write_text(json.dumps({"kinds": kinds, "missing": missing}, ensure_ascii=False, indent=1), encoding="utf-8")
    cost = usage["in"] / 1e6 * 3 + usage["out"] / 1e6 * 15
    import collections
    print("라벨 분포:", dict(collections.Counter(kinds.values())), "| 빠진 항목", len(missing), f"| 추정 ${cost:.2f}")


if __name__ == "__main__":
    main()
