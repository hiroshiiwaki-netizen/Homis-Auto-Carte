@echo off
REM ============================================================
REM HOMISカルテライター Watchdog v2.1.1
REM ============================================================
REM 心拍の更新時刻が5分超なら再起動
REM 監視中（status=running）以外は失敗とみなす
REM - restarting / starting: 2分待ってから再判定
REM - stopped / 不明: すぐ再起動
REM ============================================================

setlocal enabledelayedexpansion

set "STATE_DIR=C:\HomisKarteWriter"
set "SCRIPT_DIR=G:\共有ドライブ\レントゲンオーダー\Homis転記実行ファイル"
set "HEARTBEAT_FILE=%STATE_DIR%\heartbeat.txt"
set "STARTUP_SCRIPT=%SCRIPT_DIR%\start_gui.vbs"
set "LOG_FILE=%STATE_DIR%\watchdog.log"
set "MAX_AGE_SECONDS=300"

if not exist "%HEARTBEAT_FILE%" (
    echo %date% %time% - Watchdog: heartbeat.txt が見つかりません。再起動します。 >> "%LOG_FILE%"
    goto :restart
)

REM running だけ正常。JSON の "running" を見る（restarting には含まれない）
findstr /c:"\"running\"" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 goto :check_age

REM 起動直後・日次リスタート中は2分待つ
findstr /i "restarting starting" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    echo %date% %time% - Watchdog: restarting/starting 検出。2分待機します。 >> "%LOG_FILE%"
    timeout /t 120 /nobreak >NUL
    if not exist "%HEARTBEAT_FILE%" (
        echo %date% %time% - Watchdog: 2分待機後も心拍がありません。再起動します。 >> "%LOG_FILE%"
        goto :restart
    )
    findstr /c:"\"running\"" "%HEARTBEAT_FILE%" >NUL 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo %date% %time% - Watchdog: 2分待っても監視中になりません。再起動します。 >> "%LOG_FILE%"
        goto :restart
    )
    goto :check_age
)

echo %date% %time% - Watchdog: プロセスは生きていますが監視中ではありません。再起動します。 >> "%LOG_FILE%"
goto :restart

:check_age
for /f %%A in ('powershell -NoProfile -Command "(New-TimeSpan -Start (Get-Item '%HEARTBEAT_FILE%').LastWriteTime -End (Get-Date)).TotalSeconds"') do set "AGE=%%A"
for /f "tokens=1 delims=." %%B in ("%AGE%") do set "AGE_INT=%%B"

if %AGE_INT% GTR %MAX_AGE_SECONDS% (
    echo %date% %time% - Watchdog: heartbeat が %AGE_INT% 秒前。閾値 %MAX_AGE_SECONDS% 秒超過。再起動します。 >> "%LOG_FILE%"
    goto :restart
) else (
    echo %date% %time% - Watchdog: 監視中OK（heartbeat %AGE_INT% 秒前） >> "%LOG_FILE%"
    goto :end
)

:restart
set "PID_FILE=%STATE_DIR%\homis_writer.pid"
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /F /PID %OLD_PID% >NUL 2>&1
    del "%PID_FILE%" >NUL 2>&1
    echo %date% %time% - Watchdog: 古いプロセス PID %OLD_PID% を終了しました。 >> "%LOG_FILE%"
)

if exist "%STARTUP_SCRIPT%" (
    start "" wscript.exe "%STARTUP_SCRIPT%"
    echo %date% %time% - Watchdog: プロセスを再起動しました。 >> "%LOG_FILE%"
) else (
    echo %date% %time% - Watchdog: ERROR - %STARTUP_SCRIPT% が見つかりません！ >> "%LOG_FILE%"
)

:end
endlocal
