@echo off
REM ============================================================
REM HOMIS Karte Writer Watchdog v2.1.4
REM ASCII only. Do not save as UTF-8 with BOM.
REM ============================================================
REM Restart if heartbeat is missing, not running, or older than 5 min.
REM - restarting / starting: wait 2 min then recheck
REM - stopped / unknown: restart now
REM Dual log: C:\HomisKarteWriter\watchdog.log
REM           C:\HomisKarteWriter\shared_logs\watchdog.log (junction)
REM ============================================================

setlocal enabledelayedexpansion

set "STATE_DIR=C:\HomisKarteWriter"
set "SCRIPT_DIR=%~dp0"
set "HEARTBEAT_FILE=%STATE_DIR%\heartbeat.txt"
set "STARTUP_SCRIPT=%SCRIPT_DIR%start_gui.vbs"
set "LOG_FILE=%STATE_DIR%\watchdog.log"
set "SHARED_LOG=%STATE_DIR%\shared_logs\watchdog.log"
set "MAX_AGE_SECONDS=300"

if not exist "%STATE_DIR%" mkdir "%STATE_DIR%"

if not exist "%HEARTBEAT_FILE%" (
    call :log "Watchdog: heartbeat.txt not found. Restarting."
    goto :restart
)

REM Match the word running (status running). Do not use \" quotes; cmd drops them.
findstr /i /c:"running" "%HEARTBEAT_FILE%" >NUL 2>&1
if not errorlevel 1 goto :check_age

findstr /i "restarting starting" "%HEARTBEAT_FILE%" >NUL 2>&1
if %ERRORLEVEL% EQU 0 (
    call :log "Watchdog: restarting/starting. Waiting 2 min."
    timeout /t 120 /nobreak >NUL
    if not exist "%HEARTBEAT_FILE%" (
        call :log "Watchdog: still no heartbeat after 2 min. Restarting."
        goto :restart
    )
    findstr /i /c:"running" "%HEARTBEAT_FILE%" >NUL 2>&1
    if errorlevel 1 (
        call :log "Watchdog: not running after 2 min. Restarting."
        goto :restart
    )
    goto :check_age
)

call :log "Watchdog: process alive but not monitoring. Restarting."
goto :restart

:check_age
set "AGE_INT=9999"
for /f %%A in ('powershell -NoProfile -Command "(New-TimeSpan -Start (Get-Item '%HEARTBEAT_FILE%').LastWriteTime -End (Get-Date)).TotalSeconds"') do set "AGE=%%A"
if defined AGE (
    for /f "tokens=1 delims=." %%B in ("%AGE%") do set "AGE_INT=%%B"
)

if %AGE_INT% GTR %MAX_AGE_SECONDS% (
    call :log "Watchdog: heartbeat %AGE_INT%s old. Threshold %MAX_AGE_SECONDS%s. Restarting."
    goto :restart
) else (
    call :log "Watchdog: OK heartbeat %AGE_INT%s ago"
    goto :end
)

:restart
set "PID_FILE=%STATE_DIR%\homis_writer.pid"
if exist "%PID_FILE%" (
    set /p OLD_PID=<"%PID_FILE%"
    taskkill /F /PID !OLD_PID! >NUL 2>&1
    del "%PID_FILE%" >NUL 2>&1
    call :log "Watchdog: killed old PID !OLD_PID!."
)

if exist "%STARTUP_SCRIPT%" (
    start "" wscript.exe "%STARTUP_SCRIPT%"
    call :log "Watchdog: start_gui.vbs launched."
) else (
    call :log "Watchdog: ERROR start_gui.vbs not found: %STARTUP_SCRIPT%"
)

:end
endlocal
goto :eof

:log
echo %date% %time% - %~1 >> "%LOG_FILE%"
if exist "%STATE_DIR%\shared_logs\" echo %date% %time% - %~1 >> "%SHARED_LOG%"
goto :eof
