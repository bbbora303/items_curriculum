"""숫자 규칙 초안을 확정한다: 초안(numspecs_draft)을 확정 폴더(numspecs)로 옮기고, 대체하는 이전 규칙(supersedes)은 퇴역시킨다.

사용: python confirm_spec.py <초안 id> [--by 누가] 
- 이전 규칙 파일은 지우지 않는다(이미 만든 문항의 검증·다시 쓰기에 필요). status만 retired로 바꿔 새 생성에서 고르지 않게 한다.
- 새 규칙은 교사가 확인한 뒤에만 실행한다(웹 화면 또는 대화에서 확인).
"""
import argparse
import datetime
import json
import pathlib
import sys

DATA = pathlib.Path(__file__).resolve().parents[2] / "data"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec_id")
    ap.add_argument("--by", default="teacher")
    a = ap.parse_args()
    src = DATA / "numspecs_draft" / f"{a.spec_id}.json"
    spec = json.load(open(src, encoding="utf-8"))
    spec["status"] = "confirmed"
    spec["approvedBy"] = a.by
    spec["approvedAt"] = datetime.datetime.now().isoformat(timespec="seconds")
    (DATA / "numspecs" / f"{a.spec_id}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    old_id = spec.get("supersedes")
    if old_id:
        old = DATA / "numspecs" / f"{old_id}.json"
        if old.exists():
            o = json.load(open(old, encoding="utf-8"))
            o["status"], o["retiredBy"], o["retiredAt"] = "retired", a.spec_id, spec["approvedAt"]
            old.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")
            print("이전 규칙 퇴역:", old_id)
    print("확정:", a.spec_id, "|", spec["approvedBy"], spec["approvedAt"])


if __name__ == "__main__":
    main()
