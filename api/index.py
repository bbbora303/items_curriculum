import os
import sys

# 프로젝트 최상단 루트 경로를 파이썬 모듈 검색 경로에 추가
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from scripts.web.server import Handler

class handler(Handler):
    pass