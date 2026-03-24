@echo off
REM Bouw de Infosphere Converters standalone EXE
REM Vereiste: pip install pyinstaller
pyinstaller infosphere.spec --clean
pause
