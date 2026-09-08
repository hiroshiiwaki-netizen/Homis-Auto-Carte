@echo off
REM ============================================================
REM Copy program files to C:\HomisKarteWriter (v2.1.3)
REM ASCII only. Do not save as UTF-8 with BOM.
REM Run this on the Tarumi PC, from the shared HomisKarteWriter folder.
REM Does NOT copy config.json / heartbeat / logs.
REM ============================================================

setlocal
set "SRC=%~dp0"
set "DST=C:\HomisKarteWriter"
set "BAK=%DST%\_backup"

if not exist "%DST%" mkdir "%DST%"
if not exist "%BAK%" mkdir "%BAK%"
if not exist "%DST%\templates" mkdir "%DST%\templates"

echo Backing up then copying program files to %DST%
echo config.json is left as-is.

for %%F in (
  shared_log.py
  paths.py
  watcher.py
  template_engine.py
  gui.py
  launch_gui.py
  browser_actions.py
  clipboard_utils.py
  homis_writer.py
  chat_notifier.py
  gas_api.py
  watchdog.bat
  start_gui.vbs
) do (
  if exist "%DST%\%%F" copy /Y "%DST%\%%F" "%BAK%\%%F" >NUL
  if exist "%SRC%%%F" (
    copy /Y "%SRC%%%F" "%DST%\%%F" >NUL
    echo   OK %%F
  ) else (
    echo   SKIP %%F (not in source)
  )
)

if exist "%DST%\templates\xray_karte.yaml" copy /Y "%DST%\templates\xray_karte.yaml" "%BAK%\xray_karte.yaml" >NUL
if exist "%SRC%templates\xray_karte.yaml" (
  copy /Y "%SRC%templates\xray_karte.yaml" "%DST%\templates\xray_karte.yaml" >NUL
  echo   OK templates\xray_karte.yaml
)

echo.
echo Done. Check C:\HomisKarteWriter\gui.py date is today.
echo Do not copy config.json.
pause
endlocal
