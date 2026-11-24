"""여러 성취기준을 한꺼번에 생성하고 요약표를 만든다 (시험용: 명세 초안은 자동 확정).

사용: python batch.py [--workers 4] [--tag b1] 코드1 코드2 ...
결과: output/pilot/<tag>_<코드>/ 와 output/pilot/_batch_<tag>.md (통과 여부, 시도 횟수, 비용, AI 점검 요약)
"""
import argparse
import concurrent.futures as cf
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "output" / "pilot"


def run_one(code, tag, extra):
    label = f"{tag}_{code.replace('수', 's')}"
    cmd = [sys.executable, str(HERE / "generate.py"), "--standard", code, "--label", label, "--auto-approve-spec"] + extra
    t0 = time.time()
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"})
    (OUT / label).mkdir(parents=True, exist_ok=True)
    (OUT / label / "run.log").write_text(p.stdout + "\n" + p.stderr, encoding="utf-8")
    return code, label, p.returncode, time.time() - t0


def summarize(rows, tag):
    L = [f"# 일괄 생성 결과 ({tag})\n", "| 성취기준 | 결과 | 시간 | 호출 | 추정 비용 | 템플릿 | 패턴 | AI 점검 | 비고 |", "|---|---|---|---|---|---|---|---|---|"]
    tot = 0.0
    for code, label, rc, sec in rows:
        d = OUT / label
        item = {}
        usage = {}
        try:
            item = json.load(open(d / "item.json", encoding="utf-8"))
            usage = json.load(open(d / "usage.json", encoding="utf-8"))["total"]
        except Exception:
            pass
        md = (d / "item.md").read_text(encoding="utf-8") if (d / "item.md").exists() else ""
        issues = md.count("\n- [")
        severe = md.count("\n- [심각]")
        verdict = "-"
        if "## AI 점검 의견" in md:
            verdict = md.split("## AI 점검 의견 (")[1].split(")")[0]
        log = (d / "run.log").read_text(encoding="utf-8") if (d / "run.log").exists() else ""
        retries = log.count("검증 ") and max([int(x.split("회차")[0].split()[-1]) for x in log.split("\n") if "회차:" in x] or [0])
        note = ""
        if rc == 2:
            note = "교사 확인 대기"
        elif rc != 0 and not item:
            note = "실패: " + (log.strip().split("\n")[-1][:80] if log else "")
        elif rc != 0:
            note = "검증 오류 남음"
        cost = usage.get("estUSD", 0)
        tot += cost or 0
        L.append(f"| {code} | {'통과' if rc == 0 else '미통과'} | {sec:.0f}초 | {usage.get('calls', '-')} | ${cost} | {'예' if item.get('templated') else '아니오'} | {item.get('taskPattern', '-')} | {verdict} (이슈 {issues}, 심각 {severe}) | 검증 {retries}회차 {note} |")
    L.append(f"\n합계 추정 비용: ${tot:.2f} (단가는 추정)")
    (OUT / f"_batch_{tag}.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--tag", default="b1")
    ap.add_argument("--textbook", default="none", help="교과서 id(data/textbook_registry.json) 또는 none(미선택)")
    ap.add_argument("--extra", nargs="*", default=[])
    a = ap.parse_args()
    a.extra = list(a.extra) + ["--textbook", a.textbook]
    with cf.ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda c: run_one(c, a.tag, a.extra), a.codes))
    summarize(rows, a.tag)


if __name__ == "__main__":
    main()
