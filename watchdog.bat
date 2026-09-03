@echo off
REM ============================================================
REM HOMIS Karte Writer Watchdog v2.1.2
REM ASCII only. Do not save as UTF-8 with BOM.
REM ============================================================
REM Restart if heartbeat is missing, not running, or older than 5 min.
REM - restarting / starting: wait 2 min then recheck
REM - stopped / unknown: restart now
REM ============================================================

setlocal enabledelayedexpansion

set "STATE_DIR=C:\HomisKarteWriter"
set "SCRIPT_DIR=%~dp0"
set "HEARTBEAT_FILE=%STATE_DIR%\heartbeat.txt"
set "STARTUP_SCRIPT=%SCRIPT_DIR%start_gui.vbs"
set "LOG_FILE=%STATE_DIR%\watchdog.log"
set "MAX_AGE_SECONDS=300"

if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

if not exist "%HEARTBEAT_FILE%" (
    echo %date% %time% - Watchdog: heartbeat.txt not found. Restarting. >> "%LOG_FILE%"
    goto :restart
)

REM running only. quoted so restarting does not match
findstr /c:"\"running\"" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 goto :check_age

findstr /i "restarting starting" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    echo %date% %time% - Watchdog: restarting/starting. Waiting 2 min. >> "%LOG_FILE%"
    timeout /t 120 /nobreak >NUL
    if not exist "%HEARTBEAT_FILE%" (
        echo %date% %time% - Watchdog: still no heartbeat after 2 min. Restarting. >> "%LOG_FILE%"
        goto :restart
    )
    findstr /c:"\"running\"" "%HEARTBEAT_FILE%" >NUL 2>&1
    if %ERRORLEVEL% NEQ 0 (
        echo %date% %time% - Watchdog: not running after 2 min. Restarting. >> "%LOG_FILE%"
        goto :restart
    )
    goto :check_age
)

echo %date% %time% - Watchdog: process alive but not monitoring. Restarting. >> "%LOG_FILE%"
goto :restart

:check_age
set "AGE_INT=9999"
for /f %%A in ('powershell -NoProfile -Command "(New-TimeSpan -Start (Get-Item '%HEARTBEAT_FILE%').LastWriteTime -End (Get-Date)).TotalSeconds"') do set "AGE=%%A"
if defined AGE (
    for /f "tokens=1 delims=." %%B in ("%AGE%") do set "AGE_INT=%%B"
)

if %AGE_INT% GTR %MAX_AGE_SECONDS% (
    echo %date% %time% - Watchdog: heartbeat %AGE_INT%s old. Threshold %MAX_AGE_SECONDS%s. Restarting. >> "%LOG_FILE%"
    goto :restart
) else (
    echo %date% %time% - Watchdog: OK heartbeat %AGE_INT%s ago >> "%LOG_FILE%"
    goto :end
)

:restart
set "PID_FILE=%STATE_DIR%\homis_writer.pid"
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /F /PID !OLD_PID! >NUL 2>&1
    del "%PID_FILE%" >NUL 2>&1
    echo %date% %time% - Watchdog: killed old PID !OLD_PID!. >> "%LOG_FILE%"
)

if exist "%STARTUP_SCRIPT%" (
    start "" wscript.exe "%STARTUP_SCRIPT%"
    echo %date% %time% - Watchdog: start_gui.vbs launched. >> "%LOG_FILE%"
) else (
    echo %date% %time% - Watchdog: ERROR start_gui.vbs not found: %STARTUP_SCRIPT% >> "%LOG_FILE%"
)

:end
endlocal
