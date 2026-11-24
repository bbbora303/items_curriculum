"""Claude Code 대화 기록(.jsonl)에서 사용자 메시지와 어시스턴트 답변 텍스트만 뽑아 마크다운으로 저장한다.

사용: python export_transcript.py <대화.jsonl> <출력.md> [--from "시작 표지 문구"]
- 도구 호출·도구 결과·생각(thinking)·이미지는 제외한다. <system-reminder> 블록과 자동 알림은 걷어 낸다.
- 출력에 API 키 형태(sk-ant...)가 있으면 저장하지 않고 중단한다.
"""
import argparse
import datetime
import json
import re
import sys

REMINDER = re.compile(r"<system-reminder>.*?</system-reminder>", re.S)
NOTICE_LEAD = ("This session is being continued", "[SYSTEM NOTIFICATION", "Note:", "<task-notification", "[Request interrupted")


def text_of(msg):
    c = (msg or {}).get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "\n".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
    return ""


def clean(t):
    t = REMINDER.sub("", t).strip()
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--from", dest="start", default=None, help="이 문구가 처음 나오는 사용자 메시지부터 내보낸다")
    ap.add_argument("--date", default=None, help="한국 시간(KST) 기준 이 날짜(YYYY-MM-DD)의 메시지만 내보낸다. 원본(.jsonl)을 쉼표로 여러 개 줄 수 있다")
    ap.add_argument("--max-chars", type=int, default=6000, help="한 메시지당 최대 글자 수(넘으면 줄임)")
    a = ap.parse_args()
    rows = []
    for si, src in enumerate(a.src.split(",")):
        with open(src, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    d["_src"] = si
                    rows.append(d)
                except Exception:
                    pass
    kst = datetime.timezone(datetime.timedelta(hours=9))

    def to_kst(ts):
        try:
            return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(kst)
        except Exception:
            return None
    if a.date:
        rows = [d for d in rows if (to_kst(d.get("timestamp") or "") or datetime.datetime.min.replace(tzinfo=kst)).date().isoformat() == a.date]
        first = {}
        for d in rows:
            first.setdefault(d["_src"], d.get("timestamp") or "")
        rows.sort(key=lambda d: (first[d["_src"]], d.get("timestamp") or ""))      # 세션별로 묶는다(서로 다른 대화가 섞이지 않게)
    i0 = 0
    if a.start:
        for i, d in enumerate(rows):
            if d.get("type") == "user" and a.start in text_of(d.get("message")):
                i0 = i
                break
        else:
            sys.exit("시작 문구를 찾지 못했다")
    out, n_user, n_asst, cur_src = [], 0, 0, None
    for d in rows[i0:]:
        t = d.get("type")
        if t not in ("user", "assistant"):
            continue
        txt = clean(text_of(d.get("message")))
        if not txt or txt.startswith(NOTICE_LEAD) and t == "user":
            continue
        if len(txt) > a.max_chars:
            txt = txt[: a.max_chars] + f"\n…(이하 {len(txt) - a.max_chars}자 생략)"
        if len(set(r["_src"] for r in rows)) > 1 and d["_src"] != cur_src:
            cur_src = d["_src"]
            out.append(chr(10) * 2 + "---" + chr(10) * 2 + f"# 세션 {cur_src + 1} (같은 날 별도로 열린 대화)" + chr(10))
        k = to_kst(d.get("timestamp") or "")
        ts = k.strftime("%Y-%m-%d %H:%M") if (k and a.date) else (d.get("timestamp") or "")[:16].replace("T", " ")
        if t == "user":
            n_user += 1
            out.append(f"\n## [사용자] {ts}\n\n{txt}\n")
        else:
            n_asst += 1
            out.append(f"\n### [Claude] {ts}\n\n{txt}\n")
    body = "# 수학 서술형 문항 생성 도구 — 대화 기록(텍스트만)\n\n" \
           "도구 호출·결과·이미지는 제외하고 사용자 메시지와 Claude의 답변 텍스트만 남긴 기록이다. 결정 사항의 요약은 `인수인계.md`를 먼저 볼 것.\n" + "".join(out)
    if re.search(r"sk-ant[-\w]{10,}", body):
        sys.exit("API 키 형태의 문자열이 있어 저장하지 않았다")
    open(a.out, "w", encoding="utf-8").write(body)
    print(f"사용자 {n_user}건, Claude {n_asst}건, {len(body)//1024}KB -> {a.out}")


if __name__ == "__main__":
    main()
