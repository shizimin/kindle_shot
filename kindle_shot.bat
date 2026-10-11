@echo off
rem kindle_shot CLI ƒ‰ƒ“ƒ`ƒƒ[
rem g‚¢•û: kindle_shot.bat trim --in <folder> --out <folder> --auto
rem         kindle_shot.bat convert --in <folder> --out <folder> --format searchable_pdf
cd /d "%~dp0"
if exist kindle_env\Scripts\python.exe (
    kindle_env\Scripts\python.exe cli.py %*
) else (
    python cli.py %*
)
exit /b %ERRORLEVEL%
