@echo off
cd /d "C:\Users\chenlujiao\OneDrive - Microsoft\Documents\AutoPilot"
C:\Python311\python.exe -c "from pathlib import Path; from agentloop.ui import serve; serve(Path(r'C:\Users\chenlujiao\OneDrive - Microsoft\Documents\AutoPilot'), host='127.0.0.1', port=8765)" > .agentloop\ui-8765.cmd.stdout.log 2> .agentloop\ui-8765.cmd.stderr.log
