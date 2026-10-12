@echo off
rem Battlefield 2142: remove the kit and restore the game
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0files\install.ps1" -Uninstall
