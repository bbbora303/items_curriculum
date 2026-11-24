@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 수학 서술형 문항 생성 도구(시험용)를 시작합니다. 이 창을 닫으면 종료됩니다.
start "" "http://127.0.0.1:8765"
python scripts\web\server.py
pause
