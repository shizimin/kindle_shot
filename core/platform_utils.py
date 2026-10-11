"""OS 依存処理の窓口（Windows / macOS）

ウィンドウの検索・前面化・矩形取得、画面キャプチャ、スリープ抑止、全画面化キー、
フォルダを開く処理など、OS ごとに実装が異なる操作をここに集約する。
呼び出し側は core.win32_utils / core.macos_utils を直接 import せず、
このモジュールの関数を使うこと。

バックエンドは関数内で遅延 import する。こうしておくと、OS 非依存の定数や
sanitize_folder_name はどの OS でも（テスト環境でも）import できる。

ウィンドウの識別子 (hwnd) は、Windows では HWND、macOS では CGWindowID（整数）。
座標は Windows では物理ピクセル、macOS ではポイント（pyautogui と同じ座標系）。
"""

import os
import subprocess
import sys

IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ビューアを全画面にするキーの表示名（GUI / CLI の案内文に使う）
FULLSCREEN_KEY_LABEL = "Control+Command+F" if IS_MAC else "F11"

# 対象ウィンドウが見つからないときに添える OS 固有のヒント
WINDOW_NOT_FOUND_HINT = (
    "（macOS では「システム設定 > プライバシーとセキュリティ」の「画面収録」と"
    "「アクセシビリティ」で、このアプリを起動したターミナル（または Python）を"
    "許可してください。許可がないとウィンドウ名を取得できません）"
    if IS_MAC
    else ""
)


def _backend():
    if IS_MAC:
        from core import macos_utils as backend
    else:
        from core import win32_utils as backend
    return backend


def find_window(title_keyword, exclude_pid=None, process_name=None):
    """キーワードを含むタイトルのウィンドウを返す。見つからなければ None。"""
    return _backend().find_window(title_keyword, exclude_pid=exclude_pid, process_name=process_name)


def get_window_title(hwnd):
    return _backend().get_window_title(hwnd)


def get_window_rect(hwnd):
    """ウィンドウの矩形 (left, top, right, bottom) を返す。"""
    return _backend().get_window_rect(hwnd)


def get_monitor_rects():
    """全モニタの矩形を返す。失敗時は空リスト。"""
    return _backend().get_monitor_rects()


def is_window_fullscreen(hwnd):
    return _backend().is_window_fullscreen(hwnd)


def get_window_process_name(hwnd):
    return _backend().get_window_process_name(hwnd)


def activate_window(hwnd, click_position="center", use_bring_to_top=False):
    return _backend().activate_window(
        hwnd, click_position=click_position, use_bring_to_top=use_bring_to_top
    )


def prevent_sleep():
    """スリープ・画面消灯を抑止する（ネスト可。必ず allow_sleep() と対で呼ぶ）。

    Windows / macOS 以外（CI 等）では何もしない。変換だけの処理でも呼ばれるため。
    """
    if IS_MAC or IS_WINDOWS:
        _backend().prevent_sleep()


def allow_sleep():
    if IS_MAC or IS_WINDOWS:
        _backend().allow_sleep()


def missing_permissions():
    """不足している OS の権限名のリスト（macOS のみ。Windows では常に空）。"""
    if IS_MAC:
        from core.macos_utils import missing_permissions as mac_missing

        return mac_missing()
    return []


def grab_screen(bbox=None, scale_to_bbox=False):
    """画面（bbox 指定時はその範囲）を撮って PIL Image (RGB) を返す。

    macOS の Retina ディスプレイでは bbox（ポイント）の 2 倍などの物理ピクセルで
    返る。scale_to_bbox=True なら bbox と同じサイズに縮小して返す（画面座標と
    画像座標を一致させたいときに使う）。ロック中などで撮れない場合は OSError。
    """
    img = _backend().grab_screen(bbox)
    if scale_to_bbox and bbox is not None:
        size = (bbox[2] - bbox[0], bbox[3] - bbox[1])
        if img.size != size:
            img = img.resize(size)
    return img


def toggle_fullscreen():
    """前面のビューアの全画面表示を切り替えるキーを送る。"""
    import pyautogui as pag

    if IS_MAC:
        pag.hotkey("ctrl", "command", "f")
    else:
        pag.press("f11")


def process_name_matches(actual, expected):
    """ウィンドウのプロセス名がプロファイルの想定プロセス名と一致するか。

    プロファイルの process_name は Windows の exe 名 (例: "chrome.exe") で
    書かれているため、macOS ではアプリ名 (例: "Google Chrome") に読み替える。
    """
    if not expected:
        return True
    actual_l = (actual or "").lower()
    expected_l = expected.lower()
    if actual_l == expected_l:
        return True
    if IS_MAC:
        from core.macos_utils import mac_process_aliases

        return actual_l in mac_process_aliases(expected_l)
    return False


def open_path(path):
    """フォルダや URL を OS 既定のアプリ（エクスプローラ / Finder / ブラウザ）で開く。"""
    if IS_WINDOWS:
        os.startfile(path)  # noqa: SIM115
    elif IS_MAC:
        subprocess.run(["open", path], check=True)
    else:
        subprocess.run(["xdg-open", path], check=True)


# Windows のフォルダ名に使えない文字 → 全角（見た目を保つ）。
# macOS でも "/" と ":" は使えないため、どの OS でも同じ規則で整える
# （同じ本を Windows / Mac どちらで撮ってもフォルダ名が揃う）。
_INVALID_NAME_CHARS = {
    "\\": "￥",
    "/": "／",
    ":": "：",
    "*": "＊",
    "?": "？",
    '"': "”",
    "<": "＜",
    ">": "＞",
    "|": "｜",
}


def sanitize_folder_name(text):
    """フォルダ名として使えるように整える（不正文字を全角に置換）。"""
    cleaned = "".join(_INVALID_NAME_CHARS.get(ch, ch) for ch in text)
    # 末尾のピリオド・空白は Windows のフォルダ名として無効
    return cleaned.strip().rstrip(". 　")
