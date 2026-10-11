@echo off
cd /d "%~dp0"

REM Force UTF-8 so the app works under non-ASCII paths
REM (e.g. a Japanese Windows user name such as C:\Users\<name>\...).
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist kindle_env\Scripts\activate.bat (
    call kindle_env\Scripts\activate
    python app.py
    if errorlevel 1 (
        echo.
        echo [ERROR] アプリがエラーで終了しました。上のメッセージを確認してください。
        pause
    )
) else (
    echo ========================================
    echo [ERROR] セットアップがまだ完了していません。先に setup.bat を実行してください。
    echo ========================================
    pause
    exit /b 1
)
