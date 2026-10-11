"""macOS ユーティリティ（core.win32_utils の macOS 版）

ウィンドウの検索・前面化・矩形取得、画面キャプチャ、スリープ抑止を
Quartz / AppKit / Accessibility API (pyobjc) と mss で実装する。
直接 import せず core.platform_utils 経由で使うこと。

- ウィンドウ識別子 (hwnd) は CGWindowID（整数）。
- 座標はポイント（グローバル座標・左上原点）。pyautogui と同じ座標系なので、
  クリック位置はそのまま渡せる。画面キャプチャは Retina では物理ピクセル
  （ポイントの 2 倍など）で返る。

必要な権限（システム設定 > プライバシーとセキュリティ）:
- 画面収録: ウィンドウ名の取得と画面キャプチャに必要
- アクセシビリティ: キー送信（ページめくり）とウィンドウの前面化に必要
どちらもアプリを起動したターミナル（または Python）に許可する。
"""

import os
import subprocess
import threading
import time

import pyautogui as pag

pag.FAILSAFE = False

# プロファイルの process_name（Windows の exe 名）→ macOS のアプリ名
_MAC_PROCESS_ALIASES = {
    "chrome.exe": ("google chrome", "google chrome beta", "google chrome canary", "chromium"),
    "msedge.exe": ("microsoft edge",),
    "firefox.exe": ("firefox",),
    "kindle.exe": ("kindle", "amazon kindle"),
}

# 通常のアプリウィンドウのレイヤ（メニューバー・Dock 等は 0 以外）
_NORMAL_WINDOW_LAYER = 0
# これより小さいウィンドウはツールチップ等の補助ウィンドウとみなして無視する
_MIN_WINDOW_SIZE = 100


def mac_process_aliases(expected_lower):
    """Windows の exe 名 (小文字) に対応する macOS のアプリ名 (小文字) の集合。"""
    aliases = set(_MAC_PROCESS_ALIASES.get(expected_lower, ()))
    if expected_lower.endswith(".exe"):
        aliases.add(expected_lower[:-4])
    return aliases


def _process_matches(actual, expected):
    actual_l = (actual or "").lower()
    expected_l = expected.lower()
    return actual_l == expected_l or actual_l in mac_process_aliases(expected_l)


# ============================================================
# ウィンドウ情報
# ============================================================


def _window_list():
    """全ウィンドウ（他スペース・最小化含む）の情報 dict のリスト。"""
    import Quartz

    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    return list(Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or [])


def _window_info(hwnd):
    """CGWindowID からウィンドウ情報 dict を返す。無ければ None。"""
    import Quartz

    infos = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionIncludingWindow, hwnd) or []
    for info in infos:
        if int(info.get(Quartz.kCGWindowNumber, -1)) == int(hwnd):
            return info
    return None


def _bounds(info):
    """ウィンドウ情報から (left, top, right, bottom) を返す。"""
    import Quartz

    b = info.get(Quartz.kCGWindowBounds) or {}
    left = int(round(b.get("X", 0)))
    top = int(round(b.get("Y", 0)))
    return (left, top, left + int(round(b.get("Width", 0))), top + int(round(b.get("Height", 0))))


def find_window(title_keyword, exclude_pid=None, process_name=None):
    """指定キーワードを含むウィンドウタイトルの CGWindowID を返す。見つからなければ None。

    スコアリングは Windows 版と同じ（タイトル末尾一致・プロセス名一致を優先）。
    画面に表示中のウィンドウは、別スペース・最小化中のものより優先する。
    """
    import Quartz

    keyword_lower = title_keyword.lower()
    candidates = []  # (score, hwnd)
    for info in _window_list():
        if info.get(Quartz.kCGWindowLayer, 0) != _NORMAL_WINDOW_LAYER:
            continue
        pid = int(info.get(Quartz.kCGWindowOwnerPID, 0))
        if exclude_pid is not None and pid == exclude_pid:
            continue
        title = info.get(Quartz.kCGWindowName) or ""
        if not title:
            continue
        title_lower = title.lower()
        if keyword_lower not in title_lower:
            continue
        left, top, right, bottom = _bounds(info)
        if right - left < _MIN_WINDOW_SIZE or bottom - top < _MIN_WINDOW_SIZE:
            continue

        score = 1
        if title_lower.endswith(keyword_lower) or title_lower == keyword_lower:
            score = 10
        elif title_lower.startswith(keyword_lower):
            score = 8
        elif f" {keyword_lower}" in title_lower or f"- {keyword_lower}" in title_lower:
            score = 5

        owner = info.get(Quartz.kCGWindowOwnerName) or ""
        if process_name and _process_matches(owner, process_name):
            score += 20
        if info.get(Quartz.kCGWindowIsOnscreen):
            score += 2

        candidates.append((score, int(info[Quartz.kCGWindowNumber])))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def get_window_title(hwnd):
    import Quartz

    info = _window_info(hwnd)
    return (info.get(Quartz.kCGWindowName) or "") if info else ""


def get_window_rect(hwnd):
    """ウィンドウの矩形 (left, top, right, bottom) をポイントで返す。"""
    info = _window_info(hwnd)
    if info is None:
        raise OSError(f"ウィンドウが見つかりません (id={hwnd})")
    return _bounds(info)


def get_window_process_name(hwnd):
    """ウィンドウの所有アプリ名 (例: "Google Chrome") を返す。"""
    import Quartz

    info = _window_info(hwnd)
    return (info.get(Quartz.kCGWindowOwnerName) or "") if info else ""


def get_monitor_rects():
    """全ディスプレイの矩形をグローバル座標（ポイント）で返す。失敗時は空リスト。"""
    try:
        import Quartz

        err, displays, count = Quartz.CGGetActiveDisplayList(32, None, None)
        if err:
            return []
        rects = []
        for display in displays[:count]:
            b = Quartz.CGDisplayBounds(display)
            left, top = int(b.origin.x), int(b.origin.y)
            rects.append((left, top, left + int(b.size.width), top + int(b.size.height)))
        return rects
    except Exception:
        return []


def is_window_fullscreen(hwnd):
    """ウィンドウがディスプレイ全面を占めているか（Control+Command+F の全画面）。

    macOS の「拡大」（緑ボタンの option クリック等）はメニューバー分だけ
    ディスプレイより小さいため、全面一致で全画面と区別できる。
    """
    try:
        left, top, right, bottom = get_window_rect(hwnd)
    except OSError:
        return False
    for m_left, m_top, m_right, m_bottom in get_monitor_rects():
        if left <= m_left and top <= m_top and right >= m_right and bottom >= m_bottom:
            return True
    return False


# ============================================================
# 前面化
# ============================================================


def _ax_raise_window(pid, title):
    """Accessibility API でアプリを最前面にし、該当タイトルのウィンドウを最小化解除して出す。

    macOS 14 以降は NSApplicationActivateIgnoringOtherApps が無視され、
    CLI（ターミナルが前面）からの activate が通らないことがあるため、
    AXFrontmost で確実に前面化する（アクセシビリティ権限が必要）。
    """
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            AXUIElementPerformAction,
            AXUIElementSetAttributeValue,
            kAXFrontmostAttribute,
            kAXMainAttribute,
            kAXMinimizedAttribute,
            kAXRaiseAction,
            kAXTitleAttribute,
            kAXWindowsAttribute,
        )
    except ImportError:
        return
    app_el = AXUIElementCreateApplication(pid)
    AXUIElementSetAttributeValue(app_el, kAXFrontmostAttribute, True)
    err, windows = AXUIElementCopyAttributeValue(app_el, kAXWindowsAttribute, None)
    if err or not windows:
        return
    for win in windows:
        err, win_title = AXUIElementCopyAttributeValue(win, kAXTitleAttribute, None)
        if err or (win_title or "") != title:
            continue
        err, minimized = AXUIElementCopyAttributeValue(win, kAXMinimizedAttribute, None)
        if not err and minimized:
            AXUIElementSetAttributeValue(win, kAXMinimizedAttribute, False)
            time.sleep(0.5)
        AXUIElementSetAttributeValue(win, kAXMainAttribute, True)
        AXUIElementPerformAction(win, kAXRaiseAction)
        return


def activate_window(hwnd, click_position="center", use_bring_to_top=False):
    """ウィンドウを前面に出す（必要ならクリックする）。

    click_position:
        'center': ウィンドウ中央をクリック
        'top_left': macOS ではクリックしない。Windows ではフォーカス奪取の
                    制限を回避するためにタイトルバーをクリックしていたが、
                    macOS はアプリの activate だけでキー入力が届く。左上は
                    信号機ボタン（閉じる/最小化/全画面）があり誤クリックが危険。
        'none': クリックしない
    use_bring_to_top は Windows 専用（macOS では常に AXRaise で最前面に出す）。
    """
    import Quartz
    from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

    info = _window_info(hwnd)
    if info is None:
        return
    pid = int(info.get(Quartz.kCGWindowOwnerPID, 0))
    title = info.get(Quartz.kCGWindowName) or ""

    app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
    if app is not None:
        if app.isHidden():
            app.unhide()
        app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
    _ax_raise_window(pid, title)
    # 別スペース（全画面）への切り替えアニメーションを待つ
    time.sleep(0.5)

    if click_position != "center":
        time.sleep(0.5)
        return

    left, top, right, bottom = get_window_rect(hwnd)
    pag.moveTo(left + (right - left) // 2, top + (bottom - top) // 2)
    pag.click()
    time.sleep(1)


# ============================================================
# 権限
# ============================================================


def missing_permissions():
    """不足している macOS の権限名のリストを返す（確認できない項目は数えない）。

    画面収録が未許可なら、OS の許可ダイアログも表示させる。
    """
    missing = []
    try:
        import Quartz

        if not Quartz.CGPreflightScreenCaptureAccess():
            Quartz.CGRequestScreenCaptureAccess()
            missing.append("画面収録")
    except (ImportError, AttributeError):
        pass
    try:
        from ApplicationServices import AXIsProcessTrusted

        if not AXIsProcessTrusted():
            missing.append("アクセシビリティ")
    except ImportError:
        pass
    return missing


# ============================================================
# 画面キャプチャ
# ============================================================

# mss のインスタンスはスレッドをまたいで使えないため、スレッドごとに持つ
_mss_local = threading.local()


def _mss():
    sct = getattr(_mss_local, "sct", None)
    if sct is None:
        import mss
        import mss.darwin

        # mss は既定で Retina をポイント解像度に縮小して返す
        # (kCGWindowImageNominalResolution)。OCR・PDF の画質を Windows（物理
        # ピクセル）と揃えるため、このフラグを外してネイティブ解像度で撮る。
        mss.darwin.IMAGE_OPTIONS &= ~mss.darwin.kCGWindowImageNominalResolution
        sct = mss.mss()
        _mss_local.sct = sct
    return sct


def grab_screen(bbox=None):
    """画面（bbox 指定時はその範囲・ポイント座標）を撮って PIL Image (RGB) を返す。

    Retina では物理ピクセル（bbox の 2 倍など）の解像度で返る。
    PIL の ImageGrab は macOS では screencapture コマンドを毎回起動するうえ
    ポイントサイズに縮小してしまうため使わない。
    """
    from PIL import Image

    try:
        sct = _mss()
        if bbox is None:
            monitor = sct.monitors[0]  # 全ディスプレイを含む仮想画面
        else:
            left, top, right, bottom = bbox
            monitor = {
                "left": int(left),
                "top": int(top),
                "width": int(right - left),
                "height": int(bottom - top),
            }
        shot = sct.grab(monitor)
    except Exception as e:
        # スクリーンロック中などは撮れない。Windows 版 (ImageGrab) と同じく OSError にする
        raise OSError(f"画面を取得できません: {e}") from e
    return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


# ============================================================
# スリープ抑止
# ============================================================

# caffeinate はプロセス全体に効くため、ネストカウンタもプロセスで1つ持つ
_sleep_lock = threading.Lock()
_sleep_count = 0
_caffeinate = None


def prevent_sleep():
    """スリープ・画面消灯を抑止する（caffeinate を起動）。ネスト可。

    終了時は必ず対で allow_sleep() を呼ぶこと。アプリが落ちても
    caffeinate -w により自プロセス終了と同時に解除される。
    """
    global _sleep_count, _caffeinate
    with _sleep_lock:
        _sleep_count += 1
        if _sleep_count == 1:
            try:
                _caffeinate = subprocess.Popen(
                    ["caffeinate", "-d", "-i", "-w", str(os.getpid())],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError:
                _caffeinate = None


def allow_sleep():
    """prevent_sleep() の抑止を解除する（ネストの最後の解除で実際に解除）。"""
    global _sleep_count, _caffeinate
    with _sleep_lock:
        _sleep_count = max(0, _sleep_count - 1)
        if _sleep_count == 0 and _caffeinate is not None:
            _caffeinate.terminate()
            _caffeinate = None
