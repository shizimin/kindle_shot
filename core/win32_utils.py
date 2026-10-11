"""Win32 API ユーティリティ

ウィンドウの検索・活性化、ダイアログ表示など Windows 固有の操作を提供する。
直接 import せず core.platform_utils 経由で使うこと（macOS 版は core.macos_utils）。
"""

import os
import threading
import time
from ctypes import (
    POINTER,
    WINFUNCTYPE,
    byref,
    c_bool,
    c_int,
    create_unicode_buffer,
    pointer,
    windll,
)
from ctypes.wintypes import DWORD, RECT

import pyautogui as pag

pag.FAILSAFE = False


def _get_process_name(pid):
    """プロセスIDからプロセスのexe名を取得する。失敗時は空文字を返す。"""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    try:
        OpenProcess = windll.kernel32.OpenProcess
        CloseHandle = windll.kernel32.CloseHandle
        QueryFullProcessImageNameW = windll.kernel32.QueryFullProcessImageNameW

        handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return ""
        try:
            buf = create_unicode_buffer(1024)
            size = DWORD(1024)
            if QueryFullProcessImageNameW(handle, 0, buf, byref(size)):
                # フルパスからファイル名のみ抽出
                return os.path.basename(buf.value)
        finally:
            CloseHandle(handle)
    except Exception:
        pass
    return ""


def find_window(title_keyword, exclude_pid=None, process_name=None):
    """指定キーワードを含むウィンドウタイトルのハンドルを返す。見つからなければ None。

    Args:
        title_keyword: ウィンドウタイトルに含まれるキーワード (大文字小文字を区別しない)
        exclude_pid: 除外するプロセスID (自アプリのウィンドウを除外するために使用)
        process_name: プロセス名フィルタ (例: "Kindle.exe"、一致時にスコア加算)
    """
    EnumWindows = windll.user32.EnumWindows
    GetWindowText = windll.user32.GetWindowTextW
    GetWindowTextLength = windll.user32.GetWindowTextLengthW
    IsWindowVisible = windll.user32.IsWindowVisible
    GetWindowThreadProcessId = windll.user32.GetWindowThreadProcessId
    WNDENUMPROC = WINFUNCTYPE(c_bool, POINTER(c_int), POINTER(c_int))

    candidates = []  # (score, hwnd, title, exe_name)
    keyword_lower = title_keyword.lower()
    process_name_lower = process_name.lower() if process_name else ""

    def EnumWindowsProc(hwnd, lParam):
        if not IsWindowVisible(hwnd):
            return True

        pid = DWORD()
        GetWindowThreadProcessId(hwnd, byref(pid))

        if exclude_pid is not None and pid.value == exclude_pid:
            return True

        length = GetWindowTextLength(hwnd)
        if length == 0:
            return True
        buff = create_unicode_buffer(length + 1)
        GetWindowText(hwnd, buff, length + 1)
        title = buff.value
        title_lower = title.lower()

        if keyword_lower not in title_lower:
            return True

        # スコアリング: Kindle本体のウィンドウを優先
        score = 1
        if title_lower.endswith(keyword_lower):
            score = 10  # "書名 - Kindle" パターン
        elif title_lower == keyword_lower:
            score = 10  # "Kindle" 単体
        elif title_lower.startswith(keyword_lower):
            score = 8
        elif f" {keyword_lower}" in title_lower or f"- {keyword_lower}" in title_lower:
            score = 5  # 単語境界

        # プロセス名フィルタ: 一致すればスコア大幅加算
        exe_name = ""
        if process_name_lower:
            exe_name = _get_process_name(pid.value)
            if exe_name.lower() == process_name_lower:
                score += 20

        candidates.append((score, hwnd, title, exe_name))
        return True

    EnumWindows(WNDENUMPROC(EnumWindowsProc), 0)

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0], reverse=True)
    best = candidates[0]
    return best[1]


def get_window_title(hwnd):
    """ウィンドウハンドルからタイトルを取得する。"""
    GetWindowText = windll.user32.GetWindowTextW
    GetWindowTextLength = windll.user32.GetWindowTextLengthW
    length = GetWindowTextLength(hwnd)
    if length == 0:
        return ""
    buff = create_unicode_buffer(length + 1)
    GetWindowText(hwnd, buff, length + 1)
    return buff.value


def get_window_rect(hwnd):
    """ウィンドウの矩形座標 (left, top, right, bottom) を返す。"""
    GetWindowRect = windll.user32.GetWindowRect
    rect = RECT()
    GetWindowRect(hwnd, pointer(rect))
    return (rect.left, rect.top, rect.right, rect.bottom)


def get_monitor_rects():
    """全モニタの矩形を仮想スクリーン座標で返す。失敗時は空リストを返す。"""
    from ctypes import POINTER, WINFUNCTYPE
    from ctypes.wintypes import BOOL, HDC, HMONITOR, LPARAM

    monitor_rects = []
    callback_failed = False

    def callback(_hmonitor, _hdc, rect_ptr, _lparam):
        nonlocal callback_failed
        try:
            rect = rect_ptr.contents
            monitor_rects.append((rect.left, rect.top, rect.right, rect.bottom))
        except Exception:
            callback_failed = True
            return False
        return True

    try:
        monitor_enum_proc = WINFUNCTYPE(
            BOOL, HMONITOR, HDC, POINTER(RECT), LPARAM
        )(callback)
        enumerated = windll.user32.EnumDisplayMonitors(
            None, None, monitor_enum_proc, 0
        )
        if not enumerated or callback_failed:
            return []
    except Exception:
        return []
    return monitor_rects


def is_window_fullscreen(hwnd):
    """ウィンドウが F11 全画面等でモニタ全面を占めているかを返す。

    矩形だけで判定すると、タスクバー自動非表示のモニタでは最大化ウィンドウも
    モニタ全面を覆う（不可視ボーダー分むしろ大きい）ため全画面と誤判定する。
    全画面ウィンドウはタイトルバー（WS_CAPTION）を持たないことも条件にする。
    """
    from ctypes import Structure, sizeof

    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    style = windll.user32.GetWindowLongW(hwnd, GWL_STYLE)
    if (style & WS_CAPTION) == WS_CAPTION:
        return False

    class MONITORINFO(Structure):
        _fields_ = [
            ("cbSize", DWORD),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", DWORD),
        ]

    MONITOR_DEFAULTTONEAREST = 2
    hmon = windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    info = MONITORINFO()
    info.cbSize = sizeof(MONITORINFO)
    if not windll.user32.GetMonitorInfoW(hmon, byref(info)):
        return False
    left, top, right, bottom = get_window_rect(hwnd)
    m = info.rcMonitor
    return (left <= m.left and top <= m.top
            and right >= m.right and bottom >= m.bottom)


def get_window_process_name(hwnd):
    """ウィンドウハンドルからプロセスのexe名を取得する。"""
    GetWindowThreadProcessId = windll.user32.GetWindowThreadProcessId
    pid = DWORD()
    GetWindowThreadProcessId(hwnd, byref(pid))
    return _get_process_name(pid.value)


def activate_window(hwnd, click_position='center', use_bring_to_top=False):
    """ウィンドウを前面に出してクリックする。

    click_position:
        'center': ウィンドウ中央をクリック
        'top_left': 左上付近をクリック
        'none': クリックしない (Kindle Cloud Reader 等、クリックがリーダーUIの
                表示をトグルしてキャプチャに写り込むアプリ向け。前面化だけで
                キー入力は届くことを確認済み)
    """
    IsIconic = windll.user32.IsIconic
    ShowWindow = windll.user32.ShowWindow
    SetForegroundWindow = windll.user32.SetForegroundWindow
    GetForegroundWindow = windll.user32.GetForegroundWindow
    GetWindowRect = windll.user32.GetWindowRect
    GetWindowThreadProcessId = windll.user32.GetWindowThreadProcessId
    GetCurrentThreadId = windll.kernel32.GetCurrentThreadId
    AttachThreadInput = windll.user32.AttachThreadInput
    SetWindowPos = windll.user32.SetWindowPos

    SW_RESTORE = 9
    HWND_TOPMOST = -1
    HWND_NOTOPMOST = -2
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_SHOWWINDOW = 0x0040

    # 最小化されている場合は復元
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.3)

    # AttachThreadInput トリックで前面化の権限を取得
    foreground_hwnd = GetForegroundWindow()
    fore_tid = DWORD()
    GetWindowThreadProcessId(foreground_hwnd, byref(fore_tid))
    current_tid = GetCurrentThreadId()

    attached = False
    if fore_tid.value != current_tid:
        attached = bool(AttachThreadInput(current_tid, fore_tid.value, True))

    try:
        if use_bring_to_top:
            BringWindowToTop = windll.user32.BringWindowToTop
            BringWindowToTop(hwnd)

        SetForegroundWindow(hwnd)

        # フォールバック: TOPMOST → NOTOPMOST で確実に前面化
        time.sleep(0.1)
        if GetForegroundWindow() != hwnd:
            SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0,
                         SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
    finally:
        if attached:
            AttachThreadInput(current_tid, fore_tid.value, False)

    if click_position == 'none':
        time.sleep(1)
        return

    rect = RECT()
    GetWindowRect(hwnd, pointer(rect))

    if click_position == 'center':
        x = rect.left + (rect.right - rect.left) // 2
        y = rect.top + (rect.bottom - rect.top) // 2
    else:
        x = rect.left + 60
        y = rect.top + 10

    pag.moveTo(x, y)
    pag.click()
    time.sleep(1)


# SetThreadExecutionState のフラグ
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002


# prevent_sleep のネストカウンタ。SetThreadExecutionState はスレッド単位の
# 状態なので、カウンタもスレッドローカルに持つ（抑止と解除は同一スレッドで
# 対にして呼ぶこと。スレッド終了時は OS 側で自動解除される）
_sleep_block = threading.local()


def prevent_sleep():
    """スリープ・画面消灯を抑止する（呼び出したスレッドで有効）。

    長時間の無人キャプチャ中に画面が消えると真っ黒画像になり、さらに
    復帰時のサインインでセッションがロックされると以降の open / capture が
    全滅するため、処理の間は呼び続ける。ネスト可能（run_book 全体 → その中の
    open / capture のように重ねて呼べる）。終了時は必ず対で allow_sleep() を
    呼ぶこと。実際の解除は最後の allow_sleep() で行われる。
    """
    count = getattr(_sleep_block, "count", 0)
    _sleep_block.count = count + 1
    if count == 0:
        windll.kernel32.SetThreadExecutionState(
            _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED | _ES_DISPLAY_REQUIRED
        )


def allow_sleep():
    """prevent_sleep() の抑止を解除する（ネストの最後の解除で実際に解除）。"""
    count = max(0, getattr(_sleep_block, "count", 0) - 1)
    _sleep_block.count = count
    if count == 0:
        windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)


def grab_screen(bbox=None):
    """画面（bbox 指定時はその範囲）を撮って PIL Image を返す。

    all_screens=True がないと PIL はプライマリモニタしか取得せず、
    セカンドモニタ上のウィンドウは範囲外となり真っ黒画像になる。
    """
    from PIL import ImageGrab

    return ImageGrab.grab(bbox=bbox, all_screens=True)
