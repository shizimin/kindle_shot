#!/bin/bash
# kindle_shot セットアップ（macOS）
# 使い方: ターミナルで  bash setup.sh
set -u
cd "$(dirname "$0")" || exit 1

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

echo "========================================"
echo "  kindle_shot セットアップ (macOS)"
echo "========================================"
echo

if [ "$(uname)" != "Darwin" ]; then
    echo "[ERROR] このスクリプトは macOS 用です。Windows では setup.bat を使ってください。"
    exit 1
fi

# ============================================================
# 1. 対応する Python (3.11 - 3.13、tkinter 付き) を探す
#
# 固定した依存 (numpy==2.2.2, Pillow==12.1.1, opencv 4.13 ...) のビルド済み
# wheel は 3.11 - 3.13 向けだけ。macOS 付属の /usr/bin/python3 (3.9) は古すぎる。
# Homebrew の python は tkinter が別パッケージ (python-tk@3.x) なので確認する。
# ============================================================
py_ok() {
    "$1" -c 'import sys; sys.exit(0 if sys.version_info[:2] in [(3,11),(3,12),(3,13)] else 1)' >/dev/null 2>&1
}
tk_ok() {
    "$1" -c 'import tkinter' >/dev/null 2>&1
}

PY=""
NO_TK=""
for cand in \
    python3.13 python3.12 python3.11 \
    /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
    /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
    /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.11 \
    /usr/local/bin/python3.13 /usr/local/bin/python3.12 /usr/local/bin/python3.11 \
    python3; do
    if command -v "$cand" >/dev/null 2>&1 && py_ok "$cand"; then
        if tk_ok "$cand"; then
            PY="$(command -v "$cand")"
            break
        fi
        NO_TK="$cand"
    fi
done

if [ -z "$PY" ]; then
    echo "[ERROR] 対応する Python（3.11 - 3.13、tkinter 付き）が見つかりません。"
    echo
    if [ -n "$NO_TK" ]; then
        echo "Python は見つかりましたが tkinter がありません: $NO_TK"
        echo "Homebrew の Python なら次のコマンドで追加できます（3.12 の例）:"
        echo "  brew install python-tk@3.12"
        echo
    fi
    echo "次のどちらかで Python 3.12 をインストールしてから、もう一度 bash setup.sh を実行してください。"
    echo "  - python.org のインストーラ（tkinter 同梱・おすすめ）:"
    echo "      https://www.python.org/downloads/macos/"
    echo "  - Homebrew:"
    echo "      brew install python@3.12 python-tk@3.12"
    exit 1
fi
echo "[OK] Python を使います: $PY ($("$PY" --version 2>&1))"

# ============================================================
# 2. 仮想環境 kindle_env を作成
# ============================================================
if [ -x kindle_env/bin/python ]; then
    echo "[OK] 仮想環境 kindle_env はすでに存在します。"
else
    echo "仮想環境を作成しています。"
    if ! "$PY" -m venv kindle_env; then
        echo "[ERROR] 仮想環境の作成に失敗しました。"
        exit 1
    fi
fi
VPY="kindle_env/bin/python"

# ============================================================
# 3. 依存パッケージ
# ============================================================
echo
echo "依存パッケージをインストールしています。"
"$VPY" -m pip install --upgrade pip
if ! "$VPY" -m pip install -r requirements.txt; then
    echo
    echo "[ERROR] 依存パッケージのインストールに失敗しました。"
    echo "上の pip の出力で実際のエラーを確認してください。動作確認済みの Python は 3.11 - 3.13 です。"
    exit 1
fi

# ============================================================
# 4. NDLOCR-Lite（OCR エンジン）
# ============================================================
echo
if [ -f ndlocr-lite/src/ocr.py ]; then
    echo "[OK] NDLOCR-Lite はすでにインストールされています。"
else
    echo "NDLOCR-Lite を取得しています。"
    if command -v git >/dev/null 2>&1 && git --version >/dev/null 2>&1; then
        git clone https://github.com/ndl-lab/ndlocr-lite.git
    else
        echo "[INFO] git が見つからないため zip をダウンロードします。"
        curl -L -o ndlocr.zip https://github.com/ndl-lab/ndlocr-lite/archive/refs/heads/master.zip \
            && unzip -q ndlocr.zip && mv ndlocr-lite-master ndlocr-lite
        rm -f ndlocr.zip
    fi
fi

if [ -f ndlocr-lite/src/ocr.py ]; then
    if [ -f ndlocr-lite/requirements.txt ]; then
        echo "NDLOCR-Lite の依存パッケージをインストールしています。"
        if ! "$VPY" -m pip install -r ndlocr-lite/requirements.txt; then
            echo "[WARN] NDLOCR-Lite の依存パッケージをインストールできませんでした。"
            echo "OCR は使えませんが、画像 PDF への変換などは利用できます。後で再試行するには:"
            echo "  kindle_env/bin/python -m pip install -r ndlocr-lite/requirements.txt"
        fi
    fi
else
    echo "[WARN] NDLOCR-Lite の取得に失敗しました。"
    echo "OCR がなくても、キャプチャ・トリミング・画像 PDF は利用できます。後で OCR を有効にするには:"
    echo "  git clone https://github.com/ndl-lab/ndlocr-lite.git"
    echo "  kindle_env/bin/python -m pip install -r ndlocr-lite/requirements.txt"
fi

chmod +x run.sh run.command kindle_shot.sh setup.command 2>/dev/null

echo
echo "========================================"
echo "  セットアップが完了しました。"
echo "  bash run.sh でアプリが起動します。"
echo
echo "  【重要】キャプチャ機能を使うには macOS の権限が必要です。"
echo "  システム設定 > プライバシーとセキュリティ で、アプリを起動する"
echo "  ターミナル（Terminal / iTerm など）を次の 2 か所で許可してください:"
echo "    - 画面収録（画面とシステムオーディオの録音）"
echo "    - アクセシビリティ"
echo "  許可した後はターミナルを再起動してください。"
echo "========================================"
