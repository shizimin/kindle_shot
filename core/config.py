"""設定管理モジュール

config.json の読み書きを行い、アプリケーション全体の設定を管理する。
設定ファイルが存在しない場合はデフォルト値で自動生成する。
"""

import copy
import json
import os

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "capture": {
        "active_profile": "kindle",
        # ビルトインプロファイルの正本は core/capture_profiles.py のみ。
        # ここには複製を置かない (config はビルトインへの差分上書きとして効く)。
        # ユーザーのカスタムプロファイルだけがこの dict に入る。
        "profiles": {},
    },
    "gui": {
        # 前回の保存先フォルダ（キャプチャ設定画面の初期値・作業用フォルダ）
        "last_save_folder": "",
        # 前回の書き出し先フォルダ（書き出し画面の初期値・成果物の置き場）
        "last_output_folder": "",
    },
    "trim": {
        "left_margin": 0,
        "right_margin": 0,
        "top_margin": 0,
        "bottom_margin": 0,
    },
    "ocr": {
        "reflow_paragraphs": True,
        # ndlocr-lite の並列プロセス数。CPU 推論は 1 プロセスで全コアを使うため
        # 通常は 1 が最速 (実測: Ryzen 6800U で 2 以上は逆に遅い)
        "workers": 1,
        "preprocess": {
            "enabled": True,
            "upscale": 1.5,
            "enhance_contrast": True,
            "binarize": False,
            "binarize_threshold": 180,
        },
        "replacements": {
            "enabled": True,
            "path": "",
        },
        "chapter_bookmarks": {
            "enabled": True,
        },
        "markdown": {
            # "notebooklm": ページまたぎ結合・マーカー除去 (CLI と同じ既定)
            # "faithful":  ページ忠実型 (<!-- page --> と --- を残す従来形式)
            "style": "notebooklm",
            "embed_images": False,
        },
    },
}


def _deep_merge(base, override):
    """base を override で再帰的にマージする（base を変更せず新しい dict を返す）。

    返り値は base / override のどちらの入れ子オブジェクトとも参照を共有しない。
    これにより、呼び出し側が返り値を破壊的に変更してもモジュールグローバルの
    DEFAULT_CONFIG が汚染されない。
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config():
    """設定ファイルを読み込む。存在しない場合はデフォルト値を返す。"""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            user_config = json.load(f)
        return _deep_merge(DEFAULT_CONFIG, user_config)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(config):
    """設定を JSON ファイルに保存する。"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
