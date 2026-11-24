"""자료 생성기 시험 (무료): python scripts/test_dataset.py"""
import copy
import sys

import numgen
import template as T

SPEC = {
    "id": "t_dataset", "description": "시험용", "status": "confirmed",
    "variables": {"s": {"range": [1, 300], "meaning": "자료 묶음 번호"}, "n": {"values": [20]}, "lo": {"values": [40]}, "hi": {"values": [99]}},
    "derived": {"data": "dataset(s, n, lo, hi)", "med": "median(data)", "mo": "mode(data)", "avg": "mean(data)", "c5": "count_between(data, 60, 70)"},
    "constraints": ["n_modes(data) == 1", "is_int(med)", "mode_freq(data) >= 3", "distinct(data) >= 12"],
    "difficulty": {"easy": "data_range(data) <= 50", "medium": "data_range(data) <= 58", "hard": "data_range(data) >= 40"},
}
TPL = {"stimulus": {"text": "학생 {{n}}명의 점수 중 최빈값은 {{mo}}점이고 중앙값은 {{med}}점이다. 정렬: {{sorted(data)}}",
                    "tables": [{"id": "T1", "caption": "점수", "autoTable": {"kind": "raw_row", "data": "data", "itemLabel": "학생", "valueLabel": "점수(점)", "perRow": 10}},
                               {"id": "T2", "caption": "줄기와 잎", "autoTable": {"kind": "stem_leaf", "data": "data"}},
                               {"id": "T3", "caption": "도수", "autoTable": {"kind": "freq_table", "data": "data", "start": "{{lo}}", "width": 10, "count": 6, "unit": "명"}},
                               {"id": "T4", "caption": "상대도수", "autoTable": {"kind": "rel_freq_table", "data": "data", "start": 40, "width": 10, "count": 6, "unit": "명"}}]}}
bad = 0


def check(name, cond, extra=""):
    global bad
    bad += not cond
    print(("통과" if cond else "실패"), "-", name, extra)


vals = T.pick_values(SPEC, 5, "medium")
check("조건을 만족하는 자료를 고른다", vals is not None, str(vals))
item = T.render_item(copy.deepcopy(TPL), SPEC, vals)
t1, t2, t3, t4 = item["stimulus"]["tables"]
env, _ = T.binding_env(SPEC, vals)
data = [int(x) for x in env["data"]]
check("본문에 정렬된 자료가 들어간다", ", ".join(map(str, sorted(data))) in item["stimulus"]["text"])
check("raw_row: 20개를 2줄로 나눈다", len(t1["rows"]) == 2 and sum(1 for r in t1["rows"] for c in r[1:] if c != "") == 20, str(t1["rows"][0][:4]))
check("stem_leaf: 잎 개수 합이 20", sum(len(r[1].split()) for r in t2["rows"]) == 20, str(t2["rows"][:2]))
check("freq_table: 합계 20이고 도수 합 20", t3["rows"][-1] == ["합계", "20"] and sum(int(r[1]) for r in t3["rows"][:-1]) == 20, str(t3["rows"][:2]))
check("rel_freq_table: 상대도수 합계 1", t4["rows"][-1][2] == "1", str(t4["rows"][0]))
v2 = T.pick_values(SPEC, 6, "medium", exclude=[vals])
item2 = T.render_item(copy.deepcopy(TPL), SPEC, v2)
check("다른 값을 고르면 표가 달라진다", item2["stimulus"]["tables"][2]["rows"] != t3["rows"] or item2["stimulus"]["tables"][0]["rows"] != t1["rows"], str(v2))
check("autoTable 키는 결과에서 사라진다", all("autoTable" not in t for t in item["stimulus"]["tables"]))
for d in ("easy", "medium", "hard"):
    check(f"난이도 {d} 후보가 있다", T.pick_values(SPEC, 3, d) is not None)
print(f"\n{'모두 통과' if not bad else str(bad) + '건 실패'}")
sys.exit(1 if bad else 0)
