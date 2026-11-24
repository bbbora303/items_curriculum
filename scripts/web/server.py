"""수학 서술형 문항 생성 도구 — 로컬 시험용 웹 서버 (파이썬 기본 라이브러리만 사용).

실행: python scripts/web/server.py   (또는 폴더의 '실행.bat' 더블클릭)  ->  http://127.0.0.1:8765
- 내 컴퓨터(127.0.0.1)에서만 열린다. API 키는 서버(이 프로그램)만 쓰고 브라우저로 보내지 않는다.
- 문항 생성은 scripts/gen/generate.py 를 그대로 실행한다(웹은 화면 역할). 결과는 output/pilot/ 에 저장된다.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                   # [math] descirive question
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "gen"))
OUT = ROOT / "output" / "pilot"
DATA = ROOT / "data"
PORT = int(os.environ.get("PORT", 8765))
SAFE = re.compile(r"^[\w\-.]+$")

JOBS = {}
JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------- 도우미
def load_json(p):
    return json.load(open(p, encoding="utf-8"))


def safe_label(label):
    parts = [x for x in label.split("/") if x]
    if not parts or len(parts) > 2 or any(not SAFE.match(x) or x in (".", "..") for x in parts):
        raise ValueError("잘못된 문항 이름")
    return "/".join(parts)


def item_dir(label):
    return OUT / safe_label(label)


def standards_meta():
    stds = load_json(DATA / "standards.json")["standards"]
    return [{"code": s["code"], "domain": s["domain"], "subunit": s.get("subunit"), "text": s["text"]} for s in stds if s.get("grade") == 1]


def patterns_for(code):
    import generate as G
    return [{"id": p["id"], "name": p["name"], "structure": p["structure"], "numberGen": p.get("numberGen", "")} for p in G.pattern_pool(code)]


def clean_elements(raw):
    """화면에서 온 평가 요소를 점검한다: 글자가 있어야 하고 '~하기'로 끝나게 맞춘다. 1~4개."""
    out = []
    for e in (raw or [])[:4]:
        text = re.sub(r"\s+", " ", str(e.get("text", ""))).strip().rstrip(".")
        if len(text) < 4 or len(text) > 80:
            continue
        if not text.endswith("하기"):
            text += "하기" if not text.endswith("기") else ""
        out.append({"text": text, "kind": str(e.get("kind", ""))[:6], "fromGoal": str(e.get("fromGoal", ""))[:120]})
    return out


def g0_candidates(params):
    """평가 요소 후보만 만든다(AI 1회, 약 $0.01~0.02). 문항 생성 전에 교사가 고르는 단계용."""
    import scope_check
    book = scope_check.norm_book(params.get("textbook"))
    cmd = [sys.executable, str(ROOT / "scripts" / "gen" / "generate.py"), "--standard", params["standard"], "--textbook", book or "none", "--g0-only"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}, cwd=str(ROOT), timeout=180)
    for line in p.stdout.splitlines():
        if line.startswith("G0JSON:"):
            return json.loads(line[len("G0JSON:"):])
    raise RuntimeError("평가 요소 후보를 만들지 못했습니다: " + (p.stdout + p.stderr)[-400:])


# ---------------------------------------------------------------- 작업(생성) 실행
def start_job(params):
    code = params["standard"]
    label = f"w_{code.replace('수', 's')}_{time.strftime('%m%d_%H%M%S')}"
    cmd = [sys.executable, str(ROOT / "scripts" / "gen" / "generate.py"), "--standard", code, "--label", label,
           "--max-score", str(int(params.get("maxScore", 10))), "--difficulty", params.get("difficulty", "medium"),
           "--pattern", params.get("pattern", "auto"), "--seed", str(int(params.get("seed", 1))),
           "--response-type", params.get("responseType", "서술형"), "--context", params.get("context", "수행평가"),
           "--provisional"]          # 숫자 규칙 초안은 문항 아래에서 고치고 확정한다(중간에 멈추지 않음)
    if params.get("approveSpec"):
        cmd += ["--approve-spec", params["approveSpec"]]
    import scope_check
    book = scope_check.norm_book(params.get("textbook"))        # 미선택이면 None, 분석 안 된 책이면 오류(화면에서도 막는다)
    cmd += ["--textbook", book or "none"]
    els = clean_elements(params.get("elements"))                  # 교사가 화면에서 고른 평가 요소(없으면 AI가 자동으로 고른다)
    if els:
        ef = OUT / f"_elements_{label}.json"
        ef.write_text(json.dumps({"elements": els, "competencies": params.get("competencies") or []}, ensure_ascii=False), encoding="utf-8")
        cmd += ["--elements-file", str(ef)]
    job_id = f"j{int(time.time()*1000)}"
    job = {"id": job_id, "label": label, "standard": code, "params": params, "status": "running", "log": "", "started": time.time(), "spec": None, "rc": None}
    with JOBS_LOCK:
        JOBS[job_id] = job

    def run():
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
        for line in p.stdout:
            job["log"] += line
        p.wait()
        job["rc"] = p.returncode
        job["ended"] = time.time()
        if p.returncode == 2:
            try:
                job["spec"] = latest_draft(code, job["started"])      # 준비된 뒤에 상태를 바꾼다(화면이 초안 없이 멈추지 않게)
            except Exception as ex:
                job["log"] += f"\n[서버] 숫자 규칙 초안을 읽지 못했습니다: {ex}\n"
            job["status"] = "spec_pending" if job["spec"] else "failed"
        elif p.returncode == 0:
            job["status"] = "done"
        else:
            job["status"] = "done_with_errors" if (OUT / label / "item.json").exists() else "failed"

    threading.Thread(target=run, daemon=True).start()
    return job


def start_revise(params):
    base = safe_label(params["label"]).split("/")[0]
    sev = params.get("minSeverity", "보통")
    if sev not in ("심각", "보통", "경미"):
        sev = "보통"
    cmd = [sys.executable, str(ROOT / "scripts" / "gen" / "revise.py"), str(OUT / base), "--min-severity", sev]
    job_id = f"j{int(time.time()*1000)}"
    job = {"id": job_id, "label": base, "standard": "", "params": params, "status": "running", "log": "", "started": time.time(), "spec": None, "rc": None, "kind": "revise", "resultLabel": None}
    with JOBS_LOCK:
        JOBS[job_id] = job

    def run():
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", env=env, cwd=str(ROOT))
        for line in p.stdout:
            job["log"] += line
        p.wait()
        job["rc"] = p.returncode
        job["ended"] = time.time()
        m = re.search(r"저장: (\S+)", job["log"])
        job["resultLabel"] = m.group(1) if (m and p.returncode == 0) else None
        job["status"] = "done" if job["resultLabel"] else "failed"

    threading.Thread(target=run, daemon=True).start()
    return job


def latest_draft(code, since):
    d = DATA / "numspecs_draft"
    if not d.exists():
        return None
    best = None
    for fn in d.glob("*.json"):
        if fn.stat().st_mtime >= since - 2:
            s = load_json(fn)
            if code in s.get("standards", []) and (best is None or fn.stat().st_mtime > best[0]):
                best = (fn.stat().st_mtime, s)
    if not best:
        return None
    mt, s = best
    if "candidateCount" not in s or "samples" not in s:       # 예전 초안: 한 번 계산해 파일에 저장
        import numgen
        cands = numgen.candidates(s)
        s["candidateCount"] = len(cands)
        s["samples"] = [{k: (int(e[k]) if e[k].is_Integer else str(e[k])) for k in s["variables"]} for e in cands[:4]]
        (d / f"{s['id']}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"id": s["id"], "pattern": (s.get("taskPatterns") or [""])[0], "plainSummary": s.get("plainSummary", ""),
            "description": s.get("description", ""), "variables": s["variables"], "derived": s["derived"],
            "constraints": s["constraints"], "difficulty": s["difficulty"], "candidateCount": s["candidateCount"], "samples": s["samples"]}


def job_view(job):
    return {k: job.get(k) for k in ("id", "label", "standard", "status", "log", "spec", "rc", "started", "ended", "kind", "resultLabel")}


# ---------------------------------------------------------------- 문항 읽기
_PAT_NAMES = None
DIFF_KO = {"easy": "쉬움", "medium": "보통", "hard": "어려움"}


def pattern_names():
    global _PAT_NAMES
    if _PAT_NAMES is None:
        _PAT_NAMES = {p["id"]: p["name"] for p in load_json(DATA / "task_patterns_math.json")["patterns"]}
    return _PAT_NAMES


def short_pattern(name):
    """과제 유형 이름이 구조 설명처럼 길면 끝 괄호 안의 짧은 이름만 쓴다(예: '표 -> 관계식 -> … (다중 표현 변환)' -> '다중 표현 변환')."""
    import re as _re
    m = _re.search(r"\(([^()]{2,20})\)\s*$", str(name or ""))
    return m.group(1) if m and len(str(name)) > 22 else str(name or "")


def std_index():
    return {s["code"]: s for s in load_json(DATA / "standards.json")["standards"]}


def tb_short(label):
    return re.sub(r"\s+", "", (label or "").replace("교육", "").replace("출판", "").replace("교과서", "")) or "미선택"


def kind_of(label, it):
    if "/renumber_" in label:
        return "숫자 변경본"
    if it.get("revisedFrom") or re.search(r"_rev\d+$", label):
        return "AI 수정본"
    return "원본"


def auto_title(it, stds):
    import scope_check
    code = (it.get("standardCodes") or [""])[0]
    s = stds.get(code, {})
    name = s.get("subunit") or (s.get("text") or "")[:14]
    gm = it.get("generationMeta") or {}
    tb = scope_check.book_of(it)
    return f"{code} {name} · {tb_short(scope_check.label_of(tb)) if tb else '미선택'} · {DIFF_KO.get(gm.get('difficulty'), gm.get('difficulty') or '')}"


def item_title(d, it, label, stds):
    """교사가 바꾼 이름(title.txt)이 있으면 그것, 없으면 성취기준·교과서·난이도로 만든 자동 제목. (제목, 자동 제목)"""
    auto = auto_title(it, stds)
    k = kind_of(label, it)
    if k != "원본":
        auto += f" ({k})"
    f = d / "title.txt"
    custom = f.read_text(encoding="utf-8").strip() if f.exists() else ""
    return (custom or auto), auto


def created_of(d, it):
    gm = it.get("generationMeta") or {}
    if gm.get("generatedAt"):
        return gm["generatedAt"]
    return time.strftime("%Y-%m-%dT%H:%M", time.localtime(d.stat().st_ctime))


def rename_item(label, title):
    d = item_dir(label)
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if len(title) > 60:
        raise ValueError("이름은 60자 이내로 써 주세요")
    f = d / "title.txt"
    if title:
        f.write_text(title, encoding="utf-8")
    else:
        f.unlink(missing_ok=True)
    return {"ok": True, "title": title}


def ai_summary(meta):
    """목록용 AI 점검 요약: {verdict, severe, normal, minor}. 점검 전이면 None."""
    rv = (meta or {}).get("aiReview")
    if not rv:
        return None
    c = {"심각": 0, "보통": 0, "경미": 0}
    for i in rv.get("issues", []):
        c[i.get("severity", "경미")] = c.get(i.get("severity", "경미"), 0) + 1
    return {"verdict": rv.get("verdict", ""), "severe": c["심각"], "normal": c["보통"], "minor": c["경미"]}


def list_items():
    std_index_cache = {}
    rows = []
    if not OUT.exists():
        return rows
    for d in sorted(OUT.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        cands = [d] + sorted(d.glob("renumber_*"))
        for c in cands:
            f = c / "item.json"
            if not f.exists():
                continue
            try:
                it = load_json(f)
            except Exception:
                continue
            label = d.name if c == d else f"{d.name}/{c.name}"
            stds = std_index_cache["v"] if "v" in std_index_cache else std_index_cache.setdefault("v", std_index())
            meta = load_json(c / "meta.json") if (c / "meta.json").exists() else {}
            rows.append({"label": label, "standard": (it.get("standardCodes") or [""])[0], "pattern": it.get("taskPattern"),
                         "maxScore": it.get("maxScore"), "templated": bool(it.get("templated")), "mtime": f.stat().st_mtime,
                         "title": item_title(c, it, label, stds)[0], "kind": kind_of(label, it), "domain": stds.get((it.get("standardCodes") or [""])[0], {}).get("domain", ""),
                         "standardText": stds.get((it.get("standardCodes") or [""])[0], {}).get("text", ""), "patternName": short_pattern(pattern_names().get(it.get("taskPattern"), it.get("taskPattern"))),
                         "preview": re.sub(r"\s+", " ", (it.get("stimulus", {}).get("text", "") or "").replace("$", ""))[:80], "created": created_of(c, it),
                         "errors": len(meta.get("errors", [])) if meta else None, "warnings": len(meta.get("warnings", [])) if meta else None, "ai": ai_summary(meta), "reviewed": (it.get("review") or {}).get("status") == "reviewed",
                         "difficulty": (it.get("generationMeta") or {}).get("difficulty"), "textbook": (it.get("generationMeta") or {}).get("textbook") or "none", "values": (it.get("numberBinding") or {}).get("values")})
    return rows


def parse_md_review(md):
    """meta.json이 없는 예전 결과에서 AI 점검 의견과 검증 결과를 마크다운에서 읽는다."""
    rv = None
    if "## AI 점검 의견" in md:
        sec = md.split("## AI 점검 의견")[1].split("\n---")[0]
        issues = []
        for line in sec.split("\n"):
            m = re.match(r"- \[(심각|보통|경미)\] (.*?): (.*?) -> (.*)", line)
            if m:
                issues.append({"severity": m.group(1), "where": m.group(2), "problem": m.group(3), "suggestion": m.group(4)})
        rv = {"verdict": sec.split("\n")[0].strip(" ()"), "issues": issues}
    return rv


def read_item(label):
    d = item_dir(label)
    item = load_json(d / "item.json")
    meta = load_json(d / "meta.json") if (d / "meta.json").exists() else None
    if meta is None:
        import generate as G
        errs, warns = G.run_validate(item)
        md = (d / "item.md").read_text(encoding="utf-8") if (d / "item.md").exists() else ""
        meta = {"errors": errs, "warnings": warns, "aiReview": parse_md_review(md), "usage": None}
        up = d / "usage.json"
        if up.exists():
            meta["usage"] = load_json(up).get("total")
        (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")   # 다음부터 목록에 상태 표시
    import figures
    figs = {}
    for f in item.get("stimulus", {}).get("figures", []):
        try:
            figs[f["id"]] = figures.render(f)
        except Exception as ex:
            figs[f["id"]] = f"<p>그림을 그리지 못함: {ex}</p>"
    base = label.split("/")[0]
    variants = [{"label": f"{base}/{c.name}", "values": (load_json(c / 'item.json').get('numberBinding') or {}).get('values')}
                for c in sorted((OUT / base).glob("renumber_*")) if (c / "item.json").exists()]
    revisions = [c.name for c in sorted(OUT.glob(f"{base}_rev*")) if (c / "item.json").exists()]
    import scope_check
    tb = scope_check.book_of(item)
    ttl = item_title(d, item, label, std_index())
    return {"label": label, "item": item, "meta": meta, "figures": figs, "variants": variants, "revisions": revisions, "hasTemplate": (OUT / base / "item.template.json").exists(),
            "textbook": tb or "none", "textbookLabel": scope_check.label_of(tb) if tb else "미선택(중립)",
            "title": ttl[0], "autoTitle": ttl[1], "patternName": short_pattern(pattern_names().get(item.get("taskPattern"), item.get("taskPattern"))), "created": created_of(d, item), "kind": kind_of(label, item)}


def do_renumber(params):
    base = safe_label(params["label"]).split("/")[0]
    seed = int(params.get("seed", 1))
    cmd = [sys.executable, str(ROOT / "scripts" / "gen" / "renumber.py"), str(OUT / base), "--seed", str(seed)]
    if params.get("difficulty"):
        cmd += ["--difficulty", params["difficulty"]]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONUTF8": "1"}, cwd=str(ROOT))
    ok = p.returncode == 0
    return {"ok": ok, "log": p.stdout + p.stderr, "label": f"{base}/renumber_{seed}" if ok else None}


def read_scope(label):
    """문항 아래 '적용된 중1 범위' 패널용: 교과서 선택 여부, 성취기준 해설, 금지 주제, (교과서 선택 시) 단원·용어, 그리고 지금 문항에서 걸린 범위 경고."""
    import scope_check
    item = load_json(item_dir(label) / "item.json")
    book = scope_check.book_of(item)
    code = (item.get("standardCodes") or [""])[0]
    std = scope_check._standards().get(code, {})
    d = scope_check.load() or {"common": {"laterTopics": [], "triggers": []}, "books": {}}
    out = {"textbook": book or "none", "textbookLabel": scope_check.label_of(book) if book else "미선택(중립)",
           "standard": {"code": code, "text": std.get("text", ""), "commentary": (std.get("commentary") or "").strip()},
           "laterTopics": [f"{x['item']}({x['grade']})" for x in d["common"]["laterTopics"]], "book": None,
           "warnings": [{"code": c, "name": n, "grade": g, "where": w, "snippet": sn} for c, n, g, w, sn in scope_check.scan_item(item)]}
    if book:
        bk = d["books"][book]
        mine = [t for t, c in bk["chapters"].items() if code in c["standards"]]
        ch = bk["chapters"][mine[0]] if mine else None
        out["book"] = {"chapter": mine[0] if mine else "", "newTerms": ch["newTerms"] if ch else [], "assumedTerms": ch["assumedTerms"][:40] if ch else [],
                       "priorTopics": bk["priorTopics"], "notCovered": bk["notCovered"]}
    return out


def read_spec(label):
    """문항 아래 '숫자 규칙' 패널용: 가장 최근 규칙과, 지금 보는 문항이 쓴 숫자."""
    import renumber as R
    base = safe_label(label).split("/")[0]
    spec = R.current_spec(OUT / base)
    shown = load_json(item_dir(label) / "item.json")
    if spec is None:
        return {"error": "숫자 규칙을 찾을 수 없습니다"}
    confirmed = (DATA / "numspecs" / f"{spec.get('baseId') or spec['id']}.json").exists() and spec.get("status") == "confirmed"
    return {"id": spec["id"], "status": spec.get("status", "confirmed"), "plainSummary": spec.get("plainSummary", ""),
            "description": spec.get("description", ""), "variables": spec["variables"], "derived": spec.get("derived", {}),
            "constraints": spec.get("constraints", []), "difficulty": spec.get("difficulty", {}),
            "values": (shown.get("numberBinding") or {}).get("values"), "confirmed": confirmed}


def apply_spec(data):
    import renumber as R
    base = safe_label(data["label"]).split("/")[0]
    seed = int(time.time()) % 100000
    return R.rebuild(OUT / base, variables=data.get("variables"), values=data.get("values"), seed=seed, difficulty=data.get("difficulty") or None)


def confirm_spec(label):
    """이 문항의 숫자 규칙을 확정 명세로 저장한다(같은 성취기준·과제 유형은 다음부터 이 규칙을 쓴다)."""
    import renumber as R
    base = safe_label(label).split("/")[0]
    spec = R.current_spec(OUT / base)
    if spec is None:
        raise ValueError("숫자 규칙을 찾을 수 없습니다")
    bid = spec.get("baseId") or spec["id"]
    if not SAFE.match(bid):
        raise ValueError("잘못된 규칙 이름")
    out = json.loads(json.dumps(spec))
    out.pop("baseId", None)
    out["id"], out["status"] = bid, "confirmed"
    out["approvedBy"], out["approvedAt"] = "teacher(web)", time.strftime("%Y-%m-%dT%H:%M:%S")
    (DATA / "numspecs" / f"{bid}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "id": bid}


def mark_reviewed(label):
    f = item_dir(label) / "item.json"
    it = load_json(f)
    it["review"] = {"status": "reviewed", "reviewedBy": "교사(시험)", "reviewedAt": time.strftime("%Y-%m-%d %H:%M:%S")}
    f.write_text(json.dumps(it, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True}


# ---------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                b = (HERE / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)
            elif u.path == "/api/meta":
                import scope_check
                self.send_json({"standards": standards_meta(), "difficulties": ["easy", "medium", "hard"], "textbooks": scope_check.available_books()})
            elif u.path == "/api/patterns":
                self.send_json({"patterns": patterns_for(q["standard"][0])})
            elif u.path == "/api/debug/spec":
                self.send_json(latest_draft(q["standard"][0], 0) or {})
            elif u.path == "/api/scope":
                self.send_json(read_scope(q["label"][0]))
            elif u.path == "/api/spec":
                self.send_json(read_spec(q["label"][0]))
            elif u.path == "/api/items":
                self.send_json({"items": list_items()})
            elif u.path == "/api/item":
                self.send_json(read_item(q["label"][0]))
            elif u.path.startswith("/api/jobs/"):
                job = JOBS.get(u.path.rsplit("/", 1)[1])
                self.send_json(job_view(job) if job else {"error": "작업을 찾을 수 없음"}, 200 if job else 404)
            elif u.path == "/api/jobs":
                self.send_json({"jobs": [job_view(j) | {"log": ""} for j in sorted(JOBS.values(), key=lambda j: -j["started"])]})
            else:
                self.send_json({"error": "없는 주소"}, 404)
        except Exception as ex:
            self.send_json({"error": f"{type(ex).__name__}: {ex}"}, 500)

    def do_POST(self):
        try:
            data = self.body()
            if self.path == "/api/generate":
                running = [j for j in JOBS.values() if j["status"] == "running"]
                if len(running) >= 3:
                    return self.send_json({"error": "동시에 3개까지만 만들 수 있습니다. 끝난 뒤 다시 시도하세요."}, 429)
                self.send_json(job_view(start_job(data)))
            elif self.path == "/api/rename":
                self.send_json(rename_item(data["label"], data.get("title")))
            elif self.path == "/api/g0":
                self.send_json(g0_candidates(data))
            elif self.path == "/api/renumber":
                self.send_json(do_renumber(data))
            elif self.path == "/api/revise":
                running = [j for j in JOBS.values() if j["status"] == "running"]
                if len(running) >= 3:
                    return self.send_json({"error": "동시에 3개까지만 실행할 수 있습니다."}, 429)
                self.send_json(job_view(start_revise(data)))
            elif self.path == "/api/spec/apply":
                self.send_json(apply_spec(data))
            elif self.path == "/api/spec/confirm":
                self.send_json(confirm_spec(data["label"]))
            elif self.path == "/api/review":
                self.send_json(mark_reviewed(data["label"]))
            elif self.path == "/api/spec/reject":
                sid = data["specId"]
                if SAFE.match(sid):
                    (DATA / "numspecs_draft" / f"{sid}.json").unlink(missing_ok=True)
                self.send_json({"ok": True})
            else:
                self.send_json({"error": "없는 주소"}, 404)
        except Exception as ex:
            self.send_json({"error": f"{type(ex).__name__}: {ex}"}, 500)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"수학 서술형 문항 생성 도구(시험용) — http://0.0.0.0:{PORT}  (끝내려면 이 창에서 Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
