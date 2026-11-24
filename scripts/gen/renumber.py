"""수치만 바꾸기 — AI 호출 없이 같은 문항 구조에 다른 숫자를 채운다.

사용: python renumber.py <문항 폴더(output/pilot/xxx)> [--seed N] [--difficulty easy|medium|hard]
읽는 파일: item.template.json (자리표시자 문항). 결과는 <문항 폴더>/renumber_<seed>/ 에 저장한다.
오류가 나면(문장이 어색하거나 검증 실패) 저장하지 않고 '전체 재생성'을 안내한다.
"""
import argparse
import json
import os
import pathlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import generate as G  # noqa: E402
import spec_plain  # noqa: E402
import template as T  # noqa: E402


MAX_COMBOS = 100000       # 값 목록(조합 수)의 상한. 후보는 무작위로 뽑고 필요할 때만 센다


def current_spec(folder):
    """이 문항 폴더에서 가장 최근에 고친 숫자 규칙(없으면 처음 생성에 쓴 규칙)."""
    folder = pathlib.Path(folder)
    cur = json.load(open(folder / "item.json", encoding="utf-8"))
    sid = cur["numberBinding"]["specId"]
    base_id = sid.split("__")[0]
    latest = G.V.find_spec(str(G.DATA / "numspecs"), f"{base_id}__{folder.name}")
    return latest or G.V.find_spec(str(G.DATA / "numspecs"), sid)


def _clean_var(old, new):
    """교사가 고친 변수 범위를 검사해 새 변수 정의를 돌려준다. 잘못되면 ValueError."""
    v = dict(old)
    if "values" in new:
        vs = [float(x) if (isinstance(x, float) and not float(x).is_integer()) else int(x) for x in new["values"]]
        if not vs:
            raise ValueError("값 목록이 비어 있습니다")
        v.pop("range", None)
        v.pop("step", None)
        v["values"] = vs
    else:
        lo, hi = int(new["range"][0]), int(new["range"][1])
        step = int(new.get("step") or v.get("step") or 1)
        if lo > hi or step < 1:
            raise ValueError("범위의 최솟값이 최댓값보다 클 수 없습니다(간격은 1 이상)")
        v.pop("values", None)
        v["range"], v["step"] = [lo, hi], step
    return v


def rebuild(folder, variables=None, values=None, seed=1, difficulty=None):
    """숫자 규칙(범위)을 고치거나 숫자를 직접 지정해 같은 문항 틀에 다시 채운다(AI 호출 없음).
    성공: {"ok":True,"label":...,"values":...} / 실패: {"ok":False,"error":...} (아무것도 저장하지 않음)."""
    import numgen
    import sympy as sp
    folder = pathlib.Path(folder)
    tpl = json.load(open(folder / "item.template.json", encoding="utf-8"))
    cur = json.load(open(folder / "item.json", encoding="utf-8"))
    spec = current_spec(folder)
    if spec is None:
        return {"ok": False, "error": "숫자 규칙을 찾을 수 없습니다"}
    spec = json.loads(json.dumps(spec))
    try:
        for name, new in (variables or {}).items():
            if name not in spec["variables"]:
                return {"ok": False, "error": f"알 수 없는 변수 {name}"}
            spec["variables"][name] = _clean_var(spec["variables"][name], new)
        total = 1                                   # 목록을 만들기 전에 개수부터 센다(범위가 아주 크면 목록 생성만으로 멈춘다)
        for v in spec["variables"].values():
            total *= len(v["values"]) if "values" in v else (v["range"][1] - v["range"][0]) // max(v.get("step", 1), 1) + 1
            if total > MAX_COMBOS:
                break
    except (ValueError, KeyError, TypeError) as ex:
        return {"ok": False, "error": f"범위를 읽지 못했습니다: {ex}"}
    if total > MAX_COMBOS:
        return {"ok": False, "error": f"숫자 조합이 너무 많습니다({total}개). 범위를 줄이거나 간격을 키워 {MAX_COMBOS}개 이하로 해 주세요"}

    diff = difficulty or cur.get("generationMeta", {}).get("difficulty")
    if values:
        try:
            vals = {k: (int(values[k]) if float(values[k]).is_integer() else float(values[k])) for k in spec["variables"]}
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "error": "모든 변수에 숫자를 넣어 주세요"}
        dom = numgen.domain(spec)
        out_of = [k for k, x in vals.items() if sp.Rational(str(x)) not in dom[k]]
        if out_of:
            lines = []
            for k in out_of:
                v = spec["variables"][k]
                allowed = ", ".join(map(str, v["values"])) if "values" in v else f"{v['range'][0]}~{v['range'][1]}(간격 {v.get('step', 1)})"
                lines.append(f"{k}({v.get('meaning', '')}) 값 {vals[k]}은(는) 허용 범위에 없습니다. 허용: {allowed}")
            return {"ok": False, "error": "위에서 정한 범위에 맞지 않는 값이 있습니다.\n" + "\n".join(lines)}
        why = spec_plain.explain_failed(spec, vals)
        if why:
            return {"ok": False, "error": "이 숫자로는 정답이 깔끔하게 떨어지지 않거나 숫자 규칙을 어깁니다.\n" + "\n".join(why)}
    else:
        vals = T.pick_values(spec, seed, diff, exclude=[cur["numberBinding"]["values"]])
        if vals is None:
            return {"ok": False, "error": "이 범위에서는 조건을 만족하는 다른 숫자 조합이 없습니다. 범위를 넓혀 주세요"}

    base_id = spec.get("baseId") or spec["id"].split("__")[0]
    new_id = f"{base_id}__{folder.name}"
    spec["baseId"], spec["id"], spec["status"] = base_id, new_id, "provisional"
    spec.pop("approvedBy", None)
    spec.pop("approvedAt", None)
    # 검증은 새 규칙을 저장해야 찾을 수 있으므로 먼저 저장하고, 실패하면 이전 내용으로 되돌린다
    draft = G.DATA / "numspecs_draft" / f"{new_id}.json"
    prev_txt = draft.read_text(encoding="utf-8") if draft.exists() else None
    draft.parent.mkdir(exist_ok=True)
    draft.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        item = T.render_item(tpl, spec, vals)
        item["id"] = f"{cur['id'].split('-renum')[0]}-renum{seed}"
        errs, warns = G.run_validate(item)
    except Exception as ex:
        errs, warns, item = [str(ex)], [], None
    if errs:
        if prev_txt is None:
            draft.unlink(missing_ok=True)
        else:
            draft.write_text(prev_txt, encoding="utf-8")
        return {"ok": False, "error": "이 숫자로 채웠더니 검증을 통과하지 못했습니다: " + "; ".join(errs[:3])}
    out = folder / f"renumber_{seed}"
    G.write_outputs(out, item, tpl, errs, warns, None, None)
    return {"ok": True, "label": f"{folder.name}/renumber_{seed}", "values": vals}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--difficulty", default=None, choices=[None, "easy", "medium", "hard"])
    a = ap.parse_args()
    folder = pathlib.Path(a.folder)
    tpl = json.load(open(folder / "item.template.json", encoding="utf-8"))
    cur = json.load(open(folder / "item.json", encoding="utf-8"))
    spec = current_spec(folder)
    if spec is None:
        raise SystemExit("수치 명세를 찾을 수 없다")
    diff = a.difficulty or cur.get("generationMeta", {}).get("difficulty")
    vals = T.pick_values(spec, a.seed, diff, exclude=[cur["numberBinding"]["values"]])
    if vals is None:
        raise SystemExit("바꿀 수 있는 다른 숫자 조합이 없다")
    item = T.render_item(tpl, spec, vals)
    item["id"] = f"{cur['id']}-renum{a.seed}"
    errs, warns = G.run_validate(item)
    print("새 숫자:", vals, "| 검증 오류", len(errs), "경고", len(warns))
    for e in errs:
        print("  오류:", e)
    if errs:
        print("검증을 통과하지 못해 저장하지 않는다. 전체 재생성을 사용하세요.")
        sys.exit(1)
    out = folder / f"renumber_{a.seed}"
    G.write_outputs(out, item, tpl, errs, warns, None, None)
    print("저장:", out)


if __name__ == "__main__":
    main()
