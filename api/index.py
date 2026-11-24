import os
import sys
import urllib.parse

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.web.server import Handler


class handler(Handler):
    def _restore_original_path(self):
        # Vercel이 rewrite 시 원래 요청 경로를 담아주는 헤더나 쿼리를 확인해 self.path 복원
        orig = (
            self.headers.get("x-invoke-path")
            or self.headers.get("x-matched-path")
            or self.headers.get("x-vercel-original-path")
        )
        if orig and orig.startswith("/api/"):
            # 기존 쿼리스트링(?label=...)이 있다면 함께 유지
            parsed = urllib.parse.urlparse(self.path)
            self.path = f"{orig}?{parsed.query}" if parsed.query else orig

    def do_GET(self):
        self._restore_original_path()
        super().do_GET()

    def do_POST(self):
        self._restore_original_path()
        super().do_POST()