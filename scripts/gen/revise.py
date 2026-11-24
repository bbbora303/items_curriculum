"""AI 점검 의견을 반영해 문항을 고친다 (원본은 그대로 두고 <폴더>_rev<N> 새 문항으로 저장).

사용: python revise.py <문항 폴더> [--min-severity 보통|심각|경미]
  심각만: 심각 / 심각+보통(기본): 보통 / 모두: 경미
과정: 점검 의견을 G3에 되먹임 -> (필요하면 제시문도 수정) -> 템플릿 채우기·검증·수치 변경 시험 -> 다시 AI 점검
"""
import argparse
import copy
import json
import os
import pathlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import generate as G  # noqa: E402
import template as T  # noqa: E402
from common import DEFAULT_MODEL, Usage, client  # noqa: E402

RANK = {"심각": 0, "보통": 1, "경미": 2}
EXTRA = """

[제시문 수정 허용]
- 위 문제 중 제시문(stimulus)을 고쳐야 해결되는 것이 있으면 출력 JSON에 "stimulus" 키(text, figures, tables 전체)를 추가해 고친 제시문을 쓴다. 고칠 필요가 없으면 stimulus 키를 쓰지 않는다.
- 제시문을 고칠 때도 자리표시자 규칙을 지킨다(숫자는 {{변수}} 로).
- 점검 의견이 서로 충돌하거나 근거가 약하면 따르지 않아도 된다. 따르지 않은 의견은 출력의 "skipped" 배열에 [{"issue":"요약","reason":"이유"}] 로 적는다."""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--min-severity", default="보통", choices=list(RANK))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    a = ap.parse_args()
    folder = pathlib.Path(a.folder)
    base = folder.name
    out_root = folder.parent
    meta = json.load(open(folder / "meta.json", encoding="utf-8")) if (folder / "meta.json").exists() else {}
    issues = [i for i in (meta.get("aiReview") or {}).get("issues", []) if RANK[i["severity"]] <= RANK[a.min_severity]]
    if not issues:
        raise SystemExit("반영할 점검 의견이 없다(AI 점검 결과가 없거나 선택한 심각도 이상의 의견이 없음)")
    tpl_path = folder / "item.template.json"
    templated = tpl_path.exists()
    cur = json.load(open(tpl_path if templated else folder / "item.json", encoding="utf-8"))
    rendered = json.load(open(folder / "item.json", encoding="utf-8"))
    spec = vals = env = None
    if templated:
        spec = G.V.find_spec(str(G.DATA / "numspecs"), rendered["numberBinding"]["specId"])
        vals = rendered["numberBinding"]["values"]
        env, _ = T.binding_env(spec, vals)
    std = {s["code"]: s for s in G.load_json("standards.json")["standards"]}[cur["standardCodes"][0]]
    design = {"taskPattern": cur["taskPattern"], "intent": cur.get("intent", ""),
              "subQuestions": [{k: q.get(k) for k in ("no", "answerType", "maxScore", "targetLevels", "dependsOn")} for q in cur["subQuestions"]],
              "solutionMethodsPlan": [{"id": m["id"], "name": m["name"]} for m in cur["solutionMethods"]]}
    elements = [{"text": e["text"]} for e in {e["text"]: e for q in cur["subQuestions"] for e in q["evaluationElements"]}.values()]
    example = G.guides.pick_examples(design, std)
    prev_g3 = {k: cur.get(k) for k in ("unitPolicy", "subQuestions", "solutionMethods", "modelAnswers", "scoringNotes", "teacherChecks", "feedbackNotes")}
    feedback = [f"[{i['severity']}] {i['where']}: {i['problem']} -> 제안: {i['suggestion']}" for i in issues]

    class A:  # assemble()가 읽는 값
        context = cur["assessmentContext"]
        response_type = cur["responseType"]
        max_score = cur["maxScore"]
        model = a.model
        difficulty = (cur.get("generationMeta") or {}).get("difficulty")
        seed = (cur.get("generationMeta") or {}).get("seed", 1)

    cl, usage = client(), Usage()
    G.RAW_DIR = out_root / base
    comps = cur["competencies"]
    new_t, item, errs, warns = None, None, [], []
    skipped = []
    for attempt in range(1, 4):
        prompt = G.g3_prompt(design, cur["stimulus"], spec, env, elements, std, example, feedback, prev_g3, book=(cur.get("generationMeta") or {}).get("textbook")) + EXTRA
        g3out = G.call(cl, usage, f"수정-{attempt}", prompt, a.model, G.G3_MAX_TOKENS)
        skipped = g3out.pop("skipped", skipped)
        new_stim = g3out.pop("stimulus", None)
        new_t = copy.deepcopy(cur)
        for k in ("unitPolicy", "subQuestions", "solutionMethods", "modelAnswers", "scoringNotes", "teacherChecks", "feedbackNotes"):
            if k in g3out:
                new_t[k] = g3out[k]
        if new_stim:
            new_t["stimulus"] = new_stim
        errs, warns = [], []
        try:
            if templated:
                errs += T.placeholder_errors(new_t, spec, vals)
                item = T.render_item(new_t, spec, vals) if not errs else None
            else:
                item = new_t
        except Exception as ex:
            errs.append(f"템플릿 채우기 실패: {ex}")
            item = None
        if item is not None:
            fe = G.fig_errors(item["stimulus"])
            errs += fe
            e1, w1 = G.run_validate(item)
            errs += e1
            warns += w1
            if templated and not errs:
                errs += [e for e in G.change_test(new_t, spec, vals, A.difficulty, A.seed) if "고정 숫자" not in e]
        print(f"  수정 검증 {attempt}회차: 오류 {len(errs)}", flush=True)
        if not errs:
            break
        feedback = G.explain_errors(errs, new_t)
        prev_g3 = g3out
    if errs or item is None:
        raise SystemExit("수정한 문항이 검증을 통과하지 못했다: " + "; ".join(errs[:3]) + " (원본은 그대로 유지)")

    n = 1
    while (out_root / f"{base}_rev{n}").exists():
        n += 1
    new_label = f"{base}_rev{n}"
    item["id"] = new_label
    item["revisedFrom"] = {"label": base, "appliedIssues": len(issues), "minSeverity": a.min_severity, "skipped": skipped}
    try:
        rv = G.review(cl, usage, a.model, item)
    except Exception as ex:
        print("  재점검 실패:", ex)
        rv = {"verdict": "점검 실패", "issues": []}
    G.write_outputs(out_root / new_label, item, new_t if templated else None, errs, warns, rv, usage.total())
    (out_root / new_label / "usage.json").write_text(json.dumps({"rows": usage.rows, "total": usage.total()}, ensure_ascii=False, indent=1), encoding="utf-8")
    left = [i for i in rv.get("issues", [])]
    print(f"저장: {new_label} | 반영한 의견 {len(issues)}개, 따르지 않은 의견 {len(skipped)}개 | 재점검: {rv.get('verdict')} (이슈 {len(left)})")
    print("사용량:", usage.total())


if __name__ == "__main__":
    main()
