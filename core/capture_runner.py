"""キャプチャ実行のオーケストレーション（OS 依存部は core.platform_utils）

「対象ウィンドウを検出 → 前面化 → マウスを中央へ → 待機 → マウスを別モニタへ退避（なければ中央） →
CaptureEngine を開始 → 完了待ち → manifest.json 書き出し」の一連の手順。
以前は cli.py (cmd_capture) と ui/capture_tab.py (_capture_thread) がほぼ同じ
手順を別々に実装していた。ここに一本化し、CLI/GUI 双方から呼ぶ。

emit / 終了コードの規約は core.pipeline のモジュール docstring を参照。
"""

import datetime
import json
import os
import threading
import time

from core.capture_engine import CaptureEngine
from core.pipeline import (
    EXIT_NO_IMAGES,
    EXIT_OK,
    EXIT_WINDOW_NOT_FOUND,
    clear_output_images,
    emit_error,
    null_emit,
)


def find_verified_window(engine, profile, emit=null_emit, *, strict_process=True):
    """対象ウィンドウを検索し、プロファイルにプロセス名があれば照合する。

    strict_process=True (CLI 既定): 無人実行では誤ったウィンドウ (タイトルに
    キーワードを含むエディタ等) をめくり始める事故が致命的なので、
    プロセス名不一致は見つからなかった扱いにする。
    strict_process=False (GUI): 人間が画面を見ている前提なので、不一致でも
    警告を出して続行する。

    Returns:
        (hwnd, exit_code)。成功時は (hwnd, None)。
    """
    from core.platform_utils import (
        WINDOW_NOT_FOUND_HINT,
        get_window_process_name,
        get_window_title,
        process_name_matches,
    )

    hwnd = engine.find_target_window()
    if hwnd is None:
        emit_error(emit, f"対象ウィンドウが見つかりません: {profile.window_title_keyword}"
                         f"{WINDOW_NOT_FOUND_HINT}")
        return None, EXIT_WINDOW_NOT_FOUND

    win_title = get_window_title(hwnd)
    win_exe = get_window_process_name(hwnd)
    if not process_name_matches(win_exe, profile.process_name):
        mismatch = (
            f'ウィンドウ "{win_title}" ({win_exe}) はプロファイルの想定プロセス '
            f"{profile.process_name} と一致しません。対象アプリが起動しているか確認してください"
        )
        if strict_process:
            emit_error(emit, mismatch)
            return None, EXIT_WINDOW_NOT_FOUND
        emit("status", human=f"警告: {mismatch}", message=mismatch)

    emit(
        "window_found",
        human=f'検出ウィンドウ: "{win_title}" ({win_exe})',
        title=win_title, process=win_exe,
    )
    return hwnd, None


def waiting_message(seconds, already_fullscreen):
    """キャプチャ開始前の待機メッセージを返す。"""
    from core.platform_utils import FULLSCREEN_KEY_LABEL

    message = f"{seconds}秒待機後にキャプチャを開始します..."
    if already_fullscreen:
        return message
    return message + f"（この間にビューアを {FULLSCREEN_KEY_LABEL} で全画面にしてください）"


def choose_cursor_park_point(window_rect, monitor_rects):
    """対象ウィンドウと重ならない最初のモニタの中央を返す。

    対象ウィンドウを含まないモニタへカーソルを逃がせば、どのビューアの UI も
    ホバーに反応しない。該当するモニタがなければ None を返す。
    """
    window_left, window_top, window_right, window_bottom = window_rect
    for left, top, right, bottom in monitor_rects:
        overlap_width = min(window_right, right) - max(window_left, left)
        overlap_height = min(window_bottom, bottom) - max(window_top, top)
        if overlap_width <= 0 or overlap_height <= 0:
            return ((left + right) // 2, (top + bottom) // 2)
    return None


def run_capture(profile, title, output_folder, *, profile_key=None,
                page_turn=None, page_wait=None, max_pages=None,
                overwrite=False, stop_event=None, strict_process=True,
                emit=null_emit):
    """ページを自動キャプチャする（本を開いて先頭ページを表示しておくこと）。

    Args:
        profile: CaptureProfile (解決済み)
        title: タイトル (保存先のサブフォルダ名になる)
        output_folder: 保存先フォルダ (この下に <title>/ が作られる)
        profile_key: manifest.json に記録するプロファイルキー
        page_turn: ページめくりキーの上書き (capture_profiles.PAGE_TURN_KEYS)
        page_wait: ページ変化検出のポーリング間隔の上書き (秒)
        max_pages: このページ数に達したら停止する (暴走防止の上限)
        overwrite: 保存先の既存画像を削除してから実行する
        stop_event: 外部からの停止要求 (threading.Event)。GUI の停止ボタン用
        strict_process: プロセス名不一致を拒否するか (find_verified_window 参照)
        emit: イベントコールバック

    Returns:
        終了コード
    """
    from core.platform_utils import (
        allow_sleep,
        get_monitor_rects,
        get_window_rect,
        is_window_fullscreen,
        missing_permissions,
        prevent_sleep,
    )

    if page_turn:
        profile.page_turn_key = page_turn
    if page_wait is not None:
        profile.page_wait = page_wait

    save_folder = os.path.abspath(output_folder)
    save_dir = os.path.join(save_folder, title)
    code = clear_output_images(
        save_dir, overwrite, emit,
        label="保存先", reason="前回の残骸が混ざるのを防ぐため中止。",
    )
    if code is not None:
        return code

    done = threading.Event()
    if stop_event is None:
        stop_event = threading.Event()
    result = {"total": 0, "dir": ""}

    def on_page(page, filename):
        emit("page", human=f"Page {page}: {filename}", page=page, file=filename)
        if max_pages and page >= max_pages:
            emit(
                "max_pages_reached",
                human=f"--max-pages {max_pages} に達したため停止します",
                max_pages=max_pages,
            )
            engine.stop()

    def on_status(msg):
        emit("status", human=msg, message=msg)

    def on_complete(total, sdir):
        result["total"] = total
        result["dir"] = sdir
        done.set()

    missing = missing_permissions()
    if missing:
        warn = (
            f"警告: macOS の権限（{'・'.join(missing)}）が許可されていません。"
            "システム設定 > プライバシーとセキュリティ で、このアプリを起動した"
            "ターミナル（または Python）を許可し、アプリを再起動してください"
        )
        emit("status", human=warn, message=warn, missing_permissions=missing)

    engine = CaptureEngine(profile, on_page, on_status, on_complete,
                           exclude_pid=os.getpid())
    hwnd, err = find_verified_window(engine, profile, emit,
                                     strict_process=strict_process)
    if err is not None:
        return err

    # 前面化のために先に矩形を取るが、これは確定値ではない。待機中に全画面化
    # 全画面化されると矩形が変わるため、待機後に取り直す（下記）。
    engine.set_target_window(hwnd)
    engine.activate_target_window(hwnd)

    import pyautogui as pag
    rect = get_window_rect(hwnd)
    pag.moveTo((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
    already_fullscreen = is_window_fullscreen(hwnd)
    emit(
        "waiting",
        human=waiting_message(profile.fullscreen_wait, already_fullscreen),
        seconds=profile.fullscreen_wait,
    )
    time.sleep(profile.fullscreen_wait)

    # 待機中の全画面化を反映してキャプチャ範囲を確定させる。ここで取り直さないと
    # 全画面前のウィンドウ矩形のまま全ページを切り出してしまう。
    engine.set_target_window(hwnd)
    if not is_window_fullscreen(hwnd):
        # ウィンドウのままのキャプチャも正当な使い方なのでエラーにはしない
        not_fullscreen = (
            "対象ウィンドウは全画面ではありません"
            "（現在のウィンドウ範囲でキャプチャします）"
        )
        emit("status", human=not_fullscreen, message=not_fullscreen)

    # 中央に置いたままだと、目次などリンクの上にカーソルが来たページで Chrome が
    # 左下に URL バブルを出す。右下はスライダーのツールチップ、左右端はページ送り
    # 矢印が出るため、ウィンドウ内に安全な固定位置はない。別モニタがあればそこへ
    # 逃がし、なければ中央（従来どおり）に置く。
    rect = get_window_rect(hwnd)
    park = choose_cursor_park_point(rect, get_monitor_rects())
    if park is None:
        park = ((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        park_target = "center"
        human = "マウスの退避先になる別モニタがないため、ウィンドウ中央に置いたままキャプチャします"
    else:
        park_target = "other_monitor"
        human = "キャプチャ中はマウスを別モニタへ退避します"
    pag.moveTo(*park)
    emit("status", human=human, message=human, cursor_park=park_target)

    started = datetime.datetime.now()
    stopped_by_user = False
    prevent_sleep()
    try:
        engine.start(save_folder, title)
        while not done.wait(timeout=0.5):
            if stop_event.is_set():
                stopped_by_user = True
                engine.stop()
                done.wait(timeout=10)
                break
    except KeyboardInterrupt:
        stopped_by_user = True
        engine.stop()
        done.wait(timeout=10)
    finally:
        allow_sleep()
    finished = datetime.datetime.now()

    total = result["total"]
    save_dir = result["dir"] or save_dir
    if stopped_by_user:
        stopped_reason = "user"
    elif max_pages and total >= max_pages:
        stopped_reason = "max_pages"
    else:
        stopped_reason = "timeout"  # ページが変化しなくなった = 最終ページ到達

    if total > 0:
        manifest = {
            "tool": "kindle_shot",
            "title": title,
            "profile_key": profile_key,
            "profile": profile.to_dict(),
            "total_pages": total,
            "save_dir": save_dir,
            "stopped_reason": stopped_reason,
            "started_at": started.isoformat(timespec="seconds"),
            "finished_at": finished.isoformat(timespec="seconds"),
            "duration_seconds": round((finished - started).total_seconds(), 1),
        }
        manifest_path = os.path.join(save_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        emit(
            "result",
            human=f"キャプチャ完了: {total} ページ\n保存先: {save_dir}",
            ok=True, total_pages=total, save_dir=save_dir,
            stopped_reason=stopped_reason, manifest=manifest_path,
        )
        return EXIT_OK

    emit_error(emit, "キャプチャされたページがありません")
    return EXIT_NO_IMAGES
