@echo off
chcp 65001 > nul
echo ============================================================
echo Homis自動カルテ生成 - 依存パッケージインストール
echo ============================================================
echo.

cd /d "%~dp0"
pip install -r requirements.txt

echo.
echo インストール完了！
pause
