@echo off
cd /d "%~dp0.."

if not exist logs mkdir logs

python scripts\run_close.py >> logs\daily.log 2>&1
echo %date% %time% done >> logs\daily.log