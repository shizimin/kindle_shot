@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ============================================================
REM 0. Force UTF-8 mode for Python / pip.
REM    The app is often extracted under a non-ASCII Windows user
REM    name (e.g. C:\Users\<name>\Downloads\...). Without UTF-8 mode
REM    Python uses the locale codepage (cp932 on Japanese Windows)
REM    and pip crashes with a UnicodeDecodeError / UnicodeEncodeError
REM    while handling those paths. Setting these makes non-ASCII paths
REM    work. Scoped to this script by setlocal, so the user's
REM    environment is intact.
REM ============================================================
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

echo ========================================
echo   kindle_shot セットアップ
echo ========================================
echo.

REM ============================================================
REM 1. Detect a usable system Python
REM
REM Requirements:
REM   * Version 3.11 - 3.13.  Pinned deps (numpy==2.2.2, Pillow==12.1.1,
REM     opencv 4.13 ...) ship wheels only for those versions; on too-new
REM     (3.14+) or too-old (<=3.10) Python pip falls back to a source build
REM     and fails.
REM   * tkinter / tcl / tk must be importable.  customtkinter is built on
REM     tkinter, so without it the GUI cannot start at all.  The Windows
REM     "embeddable" build of Python does NOT bundle tkinter, which is why
REM     we require a normal python.org installation instead of downloading
REM     the embeddable package as a fallback.
REM
REM When no usable Python is found we try to install 3.12 with winget
REM (see :auto_install) before giving up.
REM
REM PY holds the interpreter used to create the virtualenv: "python" when a
REM suitable system Python was found, or the full path to the interpreter
REM installed by winget in this run (PATH is not refreshed mid-session).
REM ============================================================
set "PY="
python --version >nul 2>&1
if errorlevel 1 goto :no_python

set "PY_VER="
set "PY_MAJOR="
set "PY_MINOR="
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
for /f "tokens=1,2 delims=." %%a in ("!PY_VER!") do (
    set "PY_MAJOR=%%a"
    set "PY_MINOR=%%b"
)

if not "!PY_MAJOR!"=="3" goto :bad_version
if !PY_MINOR! LSS 11 goto :bad_version
if !PY_MINOR! GTR 13 goto :bad_version

REM Verify tkinter is present (the embeddable build and some minimal
REM installs lack it; customtkinter would then fail to import at runtime).
python -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :no_tkinter

echo [OK] システムの Python !PY_VER! を使います。
set "PY=python"
goto :py_ready

REM ============================================================
REM Automatic Python 3.12 install (winget).
REM Reached only when no usable Python was found.  If winget is missing or
REM the install fails we fall back to the manual python.org guidance.
REM ============================================================
:no_python
echo [INFO] このシステムでは Python が見つかりませんでした。
set "KEEP_EXISTING="
goto :auto_install

:bad_version
echo [INFO] システムの Python !PY_VER! は対応範囲外です（対応版は 3.11 - 3.13）。
set "KEEP_EXISTING=1"
goto :auto_install

:auto_install
echo.
set "PY="
set "PY_VER="
for %%v in (3.13 3.12 3.11) do (
    if not defined PY (
        set "PY_CANDIDATE="
        for /f "delims=" %%i in ('py -%%v -c "import sys; print(sys.executable)" 2^>nul') do set "PY_CANDIDATE=%%i"
        if defined PY_CANDIDATE (
            "!PY_CANDIDATE!" -c "import tkinter" >nul 2>&1
            if not errorlevel 1 (
                set "PY=!PY_CANDIDATE!"
                set "PY_VER=%%v"
            )
        )
    )
)
if defined PY (
    echo [OK] インストール済みの Python !PY_VER! を使います: !PY!
    goto :py_ready
)

winget --version >nul 2>&1
if errorlevel 1 goto :winget_missing

echo このアプリには Python 3.11 - 3.13 が必要です。
echo winget を使って Python 3.12 を自動でインストールします。
if defined KEEP_EXISTING echo 現在の Python は残したまま、3.12 を追加でインストールします。
echo.
echo 実行中: winget install --id Python.Python.3.12 -e --source winget --silent
echo 数分かかることがあります。しばらくお待ちください。
echo.
winget install --id Python.Python.3.12 -e --source winget --silent --accept-package-agreements --accept-source-agreements
REM winget's failure codes are negative HRESULTs (e.g. -1978335215), which
REM "if errorlevel 1" does not catch. Treat anything but 0 as failure.
if not "!errorlevel!"=="0" (
    echo.
    echo [INFO] 通常のインストールに失敗しました（終了コード !errorlevel!）。
    echo        py ランチャーを含めない設定でもう一度試します。
    echo        別の Python の py ランチャーが全ユーザー向けに入っていると、
    echo        管理者権限なしでは 1625 で失敗するためです。
    echo.
    REM A per-machine py launcher (from another Python installed for all users)
    REM makes the bundled launcher MSI demand elevation and fail with 1625,
    REM rolling back the whole install. Retry without the launcher; python.exe
    REM is then resolved through the registry (old launcher) or the default folder.
    winget install --id Python.Python.3.12 -e --source winget --silent --accept-package-agreements --accept-source-agreements --override "/quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0"
    if not "!errorlevel!"=="0" goto :winget_failed
)

echo.
echo インストールした Python を探しています。
REM PATH is not refreshed inside an already running cmd session, so the new
REM "python" is not visible here.  Resolve the interpreter directly: first
REM through the py launcher (handles non-default install folders), then at
REM the python.org default locations for user- and machine-scope installs.
set "PY="
for /f "delims=" %%i in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%i"
if not defined PY (
    for %%q in (
        "%LocalAppData%\Programs\Python\Python312\python.exe"
        "%ProgramFiles%\Python312\python.exe"
        "%SystemDrive%\Python312\python.exe"
    ) do (
        if not defined PY if exist %%q set "PY=%%~fq"
    )
)
if not defined PY goto :relaunch_needed

"!PY!" -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3,11),(3,12),(3,13)] else 1)" >nul 2>&1
if errorlevel 1 goto :relaunch_needed

"!PY!" -c "import tkinter" >nul 2>&1
if errorlevel 1 goto :no_tkinter

echo [OK] インストールした Python が見つかりました: !PY!
goto :py_ready

:relaunch_needed
echo.
echo [INFO] winget は完了しましたが、このウィンドウからは Python 3.12 が見つかりません。
echo        インストール直後は PATH が新しく開いたウィンドウでしか更新されないためです。
echo.
echo このウィンドウを閉じ、新しいウィンドウで setup.bat をもう一度実行してください。
echo それでも同じ表示になる場合は、上の winget の出力にエラーが出ていないか確認し、
echo   https://www.python.org/downloads/ から Python 3.12.x を手動でインストールしてください。
pause
exit /b 1

:winget_missing
echo [INFO] このシステムでは winget（アプリ インストーラー）を利用できないため、
echo        Python を自動でインストールできません。
goto :manual_python

:winget_failed
echo.
echo [WARN] winget で Python 3.12 をインストールできませんでした（終了コード !errorlevel!）。
goto :manual_python

REM ============================================================
REM Error exits - guide the user to a working Python and stop.
REM ============================================================
:manual_python
echo.
echo [ERROR] 対応する Python（3.11 - 3.13）が必要です。
echo.
echo 次のサイトから Python 3.12.x をインストールしてください:
echo   https://www.python.org/downloads/
echo インストール時に "Add python.exe to PATH" にチェックを入れてください。
echo その後、setup.bat をもう一度実行してください。
echo 現在の Python は残したままで構いません。
echo.
echo 固定された依存パッケージ（numpy、Pillow、opencv など）のビルド済み wheel は、
echo Python 3.11 - 3.13 向けだけが提供されています。
echo それ以外のバージョンでは pip がソースからのビルドを試みて失敗します。
echo.
echo 注意: "embeddable" 版の Python は使わないでください。
echo       tkinter が含まれないため、このアプリの GUI を起動できません。
pause
exit /b 1

:no_tkinter
echo [ERROR] この Python には tkinter / tcl / tk がありません。
echo.
echo GUI は tkinter を必要とする customtkinter で作られています。
echo Windows の "embeddable" 版には tkinter が含まれないため、アプリを起動できません。
echo.
echo https://www.python.org/downloads/ から通常版をインストールしてください。
echo 通常版には tcl/tk が含まれます。その後、setup.bat をもう一度実行してください。
pause
exit /b 1

:py_ready

REM ============================================================
REM 2. Create / activate virtualenv
REM ============================================================
REM Create the venv with !PY! instead of a bare python command: after an
REM automatic install the new interpreter is not on this session's PATH yet.
if exist kindle_env\Scripts\activate.bat (
    echo [OK] 仮想環境 kindle_env はすでに存在します。
) else (
    echo 仮想環境を作成しています。
    "!PY!" -m venv kindle_env
    if errorlevel 1 (
        echo [ERROR] 仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
)
call kindle_env\Scripts\activate

REM ============================================================
REM 3. Install dependencies
REM ============================================================
echo.
echo 依存パッケージをインストールしています。
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] 依存パッケージのインストールに失敗しました。
    echo 主な原因は、未対応の Python またはネットワーク・プロキシ・ウイルス対策ソフトによる遮断です。
    echo 動作確認済みの Python は 3.11 - 3.13 です。現在のバージョン:
    python --version
    echo 上の pip 出力で実際のエラーを確認し、解消しない場合はその内容を添えて報告してください。
    pause
    exit /b 1
)

REM ============================================================
REM 4. Fetch NDLOCR-Lite
REM ============================================================
echo.
if exist ndlocr-lite\src\ocr.py (
    echo [OK] NDLOCR-Lite はすでにインストールされています。
    goto :install_ndlocr_deps
)

echo NDLOCR-Lite を取得しています。
where git >nul 2>&1
if not errorlevel 1 (
    git clone https://github.com/ndl-lab/ndlocr-lite.git
    if errorlevel 1 goto :ndlocr_fail
) else (
    echo [INFO] git が見つかりません。PowerShell で zip をダウンロードします。
    powershell -NoProfile -Command "Invoke-WebRequest -Uri 'https://github.com/ndl-lab/ndlocr-lite/archive/refs/heads/master.zip' -OutFile 'ndlocr.zip'"
    if errorlevel 1 goto :ndlocr_fail
    powershell -NoProfile -Command "Expand-Archive -Path 'ndlocr.zip' -DestinationPath '.' -Force"
    if errorlevel 1 goto :ndlocr_fail
    if exist ndlocr-lite-master (
        ren ndlocr-lite-master ndlocr-lite
    )
    del ndlocr.zip >nul 2>&1
)

if not exist ndlocr-lite\src\ocr.py (
    goto :ndlocr_fail
)

:install_ndlocr_deps
if exist ndlocr-lite\requirements.txt (
    echo NDLOCR-Lite の依存パッケージをインストールしています。
    python -m pip install -r ndlocr-lite\requirements.txt
    if errorlevel 1 (
        echo [WARN] NDLOCR-Lite の依存パッケージをインストールできませんでした。
        echo OCR は使えませんが、画像 PDF への変換などは利用できます。
        echo 後で次のコマンドを実行して再試行できます:
        echo   python -m pip install -r ndlocr-lite\requirements.txt
    )
)

echo.
echo ========================================
echo   セットアップが完了しました。
echo   run.bat を実行するとアプリが起動します。
echo ========================================
pause
exit /b 0


:ndlocr_fail
echo.
echo [WARN] NDLOCR-Lite の取得に失敗しました。
echo OCR がなくても、キャプチャ・トリミング・画像 PDF は利用できます。
echo 後で OCR を有効にするには、次のコマンドを実行してください:
echo   git clone https://github.com/ndl-lab/ndlocr-lite.git
echo   python -m pip install -r ndlocr-lite\requirements.txt
echo.
pause
exit /b 0
