@echo off
rem BF2142: backend (login, stats, unlocks) + game server (Project Remaster v17)
start "BF2142 Backend" "%~dp0Backend\start_backend.bat"
timeout /t 3 /nobreak >nul
call "%~dp0GameServer\start_server.bat"
