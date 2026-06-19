@echo off
REM ============================================================
REM HOMISカルテライター Watchdog v2.0.1
REM ============================================================
REM ハートビート方式: heartbeat.txt の更新時刻が5分超なら再起動
REM - restarting ステータスの場合は2分待つ（日次リスタート中）
REM - タスクスケジューラで5分おきに実行する
REM ============================================================

setlocal enabledelayedexpansion

REM === 設定 ===
REM 状態ファイル（heartbeat/pid/log）はローカルに保存
set "STATE_DIR=C:\HomisKarteWriter"
REM 起動スクリプトは共有ドライブ
set "SCRIPT_DIR=G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル"
set "HEARTBEAT_FILE=%STATE_DIR%\heartbeat.txt"
set "STARTUP_SCRIPT=%SCRIPT_DIR%\start_gui.vbs"
set "LOG_FILE=%STATE_DIR%\watchdog.log"
set "MAX_AGE_SECONDS=300"
REM 5分 = 300秒

REM === ハートビートファイルが存在するか ===
if not exist "%HEARTBEAT_FILE%" (
    echo %date% %time% - Watchdog: heartbeat.txt が見つかりません。再起動します。 >> "%LOG_FILE%"
    goto :restart
)

REM === v2.0.0: restarting または starting なら待機 ===
findstr /i "restarting starting" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    echo %date% %time% - Watchdog: restarting/starting 検出。2分待機します。 >> "%LOG_FILE%"
    timeout /t 120 /nobreak >NUL
    REM 2分後に再チェック
    if not exist "%HEARTBEAT_FILE%" (
        echo %date% %time% - Watchdog: 2分待機後もプロセスが復帰しません。再起動します。 >> "%LOG_FILE%"
        goto :restart
    )
)

REM === ハートビートファイルの更新時刻を確認 ===
REM PowerShellで経過秒数を計算（文字化けしない数値のみ出力）
for /f %%A in ('powershell -NoProfile -Command "(New-TimeSpan -Start (Get-Item '%HEARTBEAT_FILE%').LastWriteTime -End (Get-Date)).TotalSeconds"') do set "AGE=%%A"

REM 小数点以下を除去
for /f "tokens=1 delims=." %%B in ("%AGE%") do set "AGE_INT=%%B"

if %AGE_INT% GTR %MAX_AGE_SECONDS% (
    echo %date% %time% - Watchdog: heartbeat が %AGE_INT% 秒前。閾値 %MAX_AGE_SECONDS% 秒超過。再起動します。 >> "%LOG_FILE%"
    goto :restart
) else (
    echo %date% %time% - Watchdog: 正常稼働中（heartbeat %AGE_INT% 秒前） >> "%LOG_FILE%"
    goto :end
)

:restart
REM === v2.0.0: PIDファイルから古いプロセスを終了（二重起動防止）===
set "PID_FILE=%STATE_DIR%\homis_writer.pid"
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /F /PID %OLD_PID% >NUL 2>&1
    del "%PID_FILE%" >NUL 2>&1
    echo %date% %time% - Watchdog: 古いプロセス PID %OLD_PID% を終了しました。 >> "%LOG_FILE%"
)

REM === 再起動 ===
if exist "%STARTUP_SCRIPT%" (
    start "" wscript.exe "%STARTUP_SCRIPT%"
    echo %date% %time% - Watchdog: プロセスを再起動しました。 >> "%LOG_FILE%"
) else (
    echo %date% %time% - Watchdog: ERROR - %STARTUP_SCRIPT% が見つかりません！ >> "%LOG_FILE%"
)

:end
endlocal
