@echo off
rem Запуск бэкенда BF2142 (логин, статистика, анлоки). Остановка: Ctrl+C или закрыть окно.
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
.venv\Scripts\python.exe -m bf2142srv
pause
