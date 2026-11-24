"""API 연결 확인 (키는 출력하지 않는다)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DEFAULT_MODEL, client, text_of  # noqa: E402

c = client()
r = c.messages.create(model=DEFAULT_MODEL, max_tokens=200, messages=[{"role": "user", "content": "한국어로 '연결 확인'이라고만 답하세요."}])
print("응답:", text_of(r).strip())
print("모델:", r.model, "| 입력", r.usage.input_tokens, "출력", r.usage.output_tokens, "| stop:", r.stop_reason)
