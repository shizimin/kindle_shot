#!/bin/bash
# kindle_shot CLI ランチャー（macOS）
# 使い方: ./kindle_shot.sh trim --in <folder> --out <folder> --auto
#         ./kindle_shot.sh convert --in <folder> --out <folder> --format searchable_pdf
cd "$(dirname "$0")" || exit 1
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
if [ -x kindle_env/bin/python ]; then
    exec kindle_env/bin/python cli.py "$@"
else
    exec python3 cli.py "$@"
fi
