import os
import sys
import urllib.parse

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.web.server import Handler


class handler(Handler):
    def _restore_original_path(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        if "__path" in qs:
            subpath = qs.pop("__path")[0]
            new_query = urllib.parse.urlencode(qs, doseq=True)
            self.path = f"/api/{subpath}?{new_query}" if new_query else f"/api/{subpath}"

    def do_GET(self):
        self._restore_original_path()
        super().do_GET()

    def do_POST(self):
        self._restore_original_path()
        super().do_POST()