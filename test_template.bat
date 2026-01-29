@echo off
chcp 65001 > nul
echo ============================================================
echo Homis自動カルテ生成 - テンプレートテスト実行
echo ============================================================
echo.

cd /d "%~dp0src"
python template_engine.py

pause
