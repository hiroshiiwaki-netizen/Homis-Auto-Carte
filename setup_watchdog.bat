@echo off
REM ============================================================
REM HOMISカルテライター v2.0.1 — タスクスケジューラ登録
REM ============================================================
REM 以下の2つのタスクを登録します:
REM   1. HomisKarteWriter_AutoStart  — ログオン時に自動起動
REM   2. HomisKarteWriter_Watchdog   — 5分おきに死活監視
REM
REM コードは共有ドライブ、状態ファイルはローカル C:\HomisKarteWriter
REM 実行方法: 管理者権限で実行してください
REM ============================================================

setlocal

REM 共有ドライブ（コード・起動スクリプト）
set "SCRIPT_DIR=G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル"
set "STARTUP_SCRIPT=%SCRIPT_DIR%\start_gui.vbs"
set "WATCHDOG_SCRIPT=%SCRIPT_DIR%\watchdog.bat"

REM === 既存タスクを削除（エラーは無視）===
echo [1/4] 既存タスクを削除中...
schtasks /Delete /TN "HomisAutoChart" /F >NUL 2>&1
schtasks /Delete /TN "HomisKarteWriter_AutoStart" /F >NUL 2>&1
schtasks /Delete /TN "HomisKarteWriter_Watchdog" /F >NUL 2>&1
echo       完了

REM === ログオン時自動起動（7日24時間対応）===
echo [2/4] ログオン時自動起動タスクを登録中...
schtasks /Create ^
    /TN "HomisKarteWriter_AutoStart" ^
    /TR "wscript.exe \"%STARTUP_SCRIPT%\"" ^
    /SC ONLOGON ^
    /RL HIGHEST ^
    /F
echo       完了

REM === Watchdog（5分おき・毎日）===
echo [3/4] Watchdog タスクを登録中...
schtasks /Create ^
    /TN "HomisKarteWriter_Watchdog" ^
    /TR "\"%WATCHDOG_SCRIPT%\"" ^
    /SC MINUTE /MO 5 ^
    /RL HIGHEST ^
    /F
echo       完了

REM === 確認 ===
echo [4/4] 登録済みタスク一覧:
echo.
schtasks /Query /TN "HomisKarteWriter_AutoStart" /FO LIST 2>NUL
echo.
schtasks /Query /TN "HomisKarteWriter_Watchdog" /FO LIST 2>NUL
echo.

echo ============================================================
echo 登録完了！
echo   - 旧タスク HomisAutoChart は削除済み
echo   - ログオン時に自動起動します
echo   - 5分おきに死活監視します
echo ============================================================

pause
endlocal
