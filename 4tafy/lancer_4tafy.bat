@echo off
cd /d "%~dp0"
python -m pip install -q -U -r requirements.txt
start "" pythonw main.py
