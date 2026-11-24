"""수학 생성 스크립트 공통: .env 읽기(키는 출력하지 않음), 클라이언트, 모델 설정, 사용량 집계."""
import json
import os
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]            # [math] descirive question
DEFAULT_MODEL = "claude-sonnet-5-5"
# claude-sonnet-5-5 공식 가격(100만 토큰당 달러): 입력 $2, 출력 $10, 배치는 절반 (https://platform.claude.com/docs/en/about-claude/pricing, 2026-10-23 확인).
# 2026-10-23 이전 기록·문서의 비용은 $3/$15로 계산한 값이라 실제의 약 1.5배다. 실제 청구액은 콘솔에서 확인할 것
PRICE_PER_MTOK = {"in": 2.0, "out": 10.0}
OLD_PRICE_PER_MTOK = {"in": 3.0, "out": 15.0}      # 예전 추정 단가(과거 기록 환산용)


def load_env():
    """[math] 폴더의 .env를 우선 읽고, 없으면 상위 폴더(서술형 문항 생성 도구)의 .env를 읽는다."""
    for p in (ROOT / ".env", ROOT.parent / ".env"):
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
    else:
        raise SystemExit(".env 파일을 찾을 수 없습니다(수학 폴더 또는 상위 폴더).")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key.startswith("sk-ant") or len(key) < 30:
        raise SystemExit("ANTHROPIC_API_KEY 값이 올바르지 않은 것 같습니다(sk-ant 로 시작해야 함).")


def client():
    import anthropic
    load_env()
    return anthropic.Anthropic()


def text_of(resp):
    return "".join(b.text for b in resp.content if b.type == "text")


def extract_json(s):
    s = s.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", s, re.S)
    if m:
        s = m.group(1).strip()
    i, j = s.find("{"), s.rfind("}")
    return json.loads(s[i:j + 1])


class Usage:
    def __init__(self):
        self.rows = []

    def add(self, stage, resp):
        u = resp.usage
        self.rows.append({"stage": stage, "in": u.input_tokens, "out": u.output_tokens, "stop": resp.stop_reason})

    def total(self):
        i = sum(r["in"] for r in self.rows)
        o = sum(r["out"] for r in self.rows)
        return {"calls": len(self.rows), "in": i, "out": o,
                "estUSD": round(i / 1e6 * PRICE_PER_MTOK["in"] + o / 1e6 * PRICE_PER_MTOK["out"], 3)}
