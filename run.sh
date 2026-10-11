#!/bin/bash
# kindle_shot GUI 起動（macOS）
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ ! -x kindle_env/bin/python ]; then
    echo "========================================"
    echo "[ERROR] セットアップがまだ完了していません。先に bash setup.sh を実行してください。"
    echo "========================================"
    exit 1
fi

if ! kindle_env/bin/python app.py; then
    echo
    echo "[ERROR] アプリがエラーで終了しました。上のメッセージを確認してください。"
    exit 1
fi
