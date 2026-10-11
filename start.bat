@echo off
rem Starts the roster server and shares it through ngrok. Close both windows to stop.
cd /d "%~dp0"
start "Roster server" python server.py
timeout /t 2 /nobreak >nul
rem ngrok reads your token from the NGROK_AUTHTOKEN environment variable.
rem Your public link is shown below on the "Forwarding" line.
ngrok http 8787
pause
