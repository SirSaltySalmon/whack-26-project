@echo off
rem Starts the overlay and the brain together. Arguments go to the brain, for example:
rem   run.cmd --live --debug-regions --type --off observer,voice
rem A .cmd file isn't blocked by PowerShell's execution policy, and this uses the venv's Python
rem directly, so nothing needs activating.
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\run_all.py" %*
