@echo off
chcp 65001 >nul
echo ============================================================
echo  Homis自動カルテ生成 - タスクスケジューラ登録
echo ============================================================
echo.
echo  毎朝8:00にHomis自動カルテ生成を自動起動するタスクを登録します。
echo  （月曜～金曜のみ）
echo.
echo  ※ 管理者権限が必要です
echo.
pause

REM タスク名
set TASK_NAME=HomisAutoChart

REM 実行するバッチファイルのパス
set SCRIPT_PATH=%~dp0start_gui.bat

REM 既存のタスクを削除（エラーは無視）
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1

REM タスクを作成（月～金の8:00に実行）
schtasks /create ^
    /tn "%TASK_NAME%" ^
    /tr "\"%SCRIPT_PATH%\"" ^
    /sc weekly ^
    /d MON,TUE,WED,THU,FRI ^
    /st 08:00 ^
    /rl HIGHEST ^
    /f

if %ERRORLEVEL% equ 0 (
    echo.
    echo ============================================================
    echo  ✅ タスクの登録が完了しました！
    echo  タスク名: %TASK_NAME%
    echo  スケジュール: 月～金 08:00
    echo  実行ファイル: %SCRIPT_PATH%
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo  ❌ タスクの登録に失敗しました
    echo  管理者権限で再度実行してください
    echo ============================================================
)

echo.
pause
