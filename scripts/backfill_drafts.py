"""numspecs_draft의 예전 초안에 후보 개수(candidateCount)와 예시(samples)를 채운다(한 번만 실행)."""
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numgen  # noqa: E402

d = HERE.parent / "data" / "numspecs_draft"
for f in sorted(d.glob("*.json")):
    s = json.load(open(f, encoding="utf-8"))
    if "candidateCount" in s and "samples" in s:
        continue
    cands = numgen.candidates(s)
    s["candidateCount"] = len(cands)
    s["samples"] = [{k: (int(e[k]) if e[k].is_Integer else str(e[k])) for k in s["variables"]} for e in cands[:4]]
    f.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print("채움:", f.name, len(cands), flush=True)
print("완료")
