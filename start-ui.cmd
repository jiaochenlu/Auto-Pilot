@echo off
REM Start the AgentLoop Task Console on Windows.
REM Usage: start-ui.cmd [port]   (default port: 8765)
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8765"
if not defined PYTHON set "PYTHON=python"
if not exist ".agentloop" mkdir ".agentloop"
"%PYTHON%" -m agentloop ui --host 127.0.0.1 --port %PORT% > ".agentloop\ui-%PORT%.stdout.log" 2> ".agentloop\ui-%PORT%.stderr.log"
endlocal
