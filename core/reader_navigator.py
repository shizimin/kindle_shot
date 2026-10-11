"""Kindle Cloud Reader のナビゲーション（OS 依存部は core.platform_utils・Cloud Reader 専用）

「本を URL で開く → 読み込み待ち → 全画面化（F11 / macOS は Control+Command+F） → リーダー UI を非表示化 →
先頭ページへ巻き戻し」の一連の手順。キャプチャ開始前の準備を無人で行う。

注意: 先頭ページへの巻き戻しは Kindle の読書位置 (Whispersync) を動かす。

emit / 終了コードの規約は core.pipeline のモジュール docstring を参照。
"""

import os
import sys
import time

from core.capture_engine import CaptureEngine
from core.capture_profiles import reverse_page_turn_key
from core.pipeline import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_WINDOW_NOT_FOUND,
    emit_error,
    null_emit,
)


class ScreenLocked(Exception):
    """画面ロック・セッション切断で画面が取得できないことを表す例外。"""


def _reader_arrow_dark(hwnd):
    """左右端の中央高さ付近 (前/次ページ矢印 ‹ › が出る帯) の暗ピクセル数を返す。

    UI 表示時はここに矢印ボタンが出て暗ピクセルが増える。ただしマンガの絵が
    余白に食い込むページでは絵の暗ピクセルも混じるため、この絶対値だけでは
    UI 有無を判定できない。同一ページでのクリック前後の差分に使う (絵は不変
    なので差分が UI 分になる)。
    """
    import numpy as np

    from core.platform_utils import get_window_rect, grab_screen

    left, top, right, bottom = get_window_rect(hwnd)
    w, h = right - left, bottom - top
    y0, y1 = top + int(h * 0.45), top + int(h * 0.55)
    # scale_to_bbox: Retina でも画面座標と同じ解像度で数え、しきい値を OS 共通にする
    lb = grab_screen((left + int(w * 0.02), y0, left + int(w * 0.08), y1),
                     scale_to_bbox=True).convert("L")
    rb = grab_screen((left + int(w * 0.92), y0, left + int(w * 0.98), y1),
                     scale_to_bbox=True).convert("L")
    return int((np.asarray(lb, np.uint8) < 128).sum()) + \
        int((np.asarray(rb, np.uint8) < 128).sum())


def _find_modal_button(hwnd):
    """位置同期モーダルの確定ボタンの画面座標を返す。無ければ None。

    Cloud Reader の「前回読んでいたページ」ダイアログは背景を暗転させたモーダルで、
    キー入力も中央クリックも吸い込むためページめくりが一切効かなくなる
    (実測 2026-08-02: 1ページで打ち切られ exit 7)。

    誤検出を避けるため、次の2条件が同時に成立したときだけ検出とみなす:
      1. ページ領域の周辺 (左右の中央・下端) が一様で、白ページより暗い (=暗転)
      2. 中央付近に塗りつぶしの黒い矩形 (=確定ボタン) がある
    """
    import numpy as np

    from core.platform_utils import get_window_rect, grab_screen

    left, top, right, bottom = get_window_rect(hwnd)
    # 返す座標をクリックに使うため、画像を画面座標と同じ解像度にそろえる
    img = grab_screen((left, top, right, bottom), scale_to_bbox=True).convert("L")
    ds = 4
    arr = np.asarray(img.resize((img.width // ds, img.height // ds)), np.uint8)
    h, w = arr.shape

    # 1. 背景の暗転。ブラウザのツールバーを踏まないよう、周辺でもページ領域内
    #    (左右端の中央高さ・下端の左右) だけを見る。
    ph, pw = max(1, h // 20), max(1, w // 20)
    my = h // 2
    patches = [
        arr[my - ph:my + ph, :pw], arr[my - ph:my + ph, -pw:],
        arr[-2 * ph:-ph, :pw], arr[-2 * ph:-ph, -pw:],
    ]
    if not all(p.std() < 8 and 120 <= p.mean() <= 235 for p in patches):
        return None

    # 2. 中央の黒い塗りつぶし矩形。行ごとの黒の最長連続長を求め、それが
    #    ボタン幅以上の行がボタン高さ分続く塊を探す。
    y0, y1 = int(h * 0.25), int(h * 0.75)
    x0, x1 = int(w * 0.25), int(w * 0.75)
    dark = (arr[y0:y1, x0:x1] < 60).astype(np.int32)
    run = np.zeros_like(dark)
    run[:, 0] = dark[:, 0]
    for j in range(1, dark.shape[1]):
        run[:, j] = (run[:, j - 1] + 1) * dark[:, j]
    best = run.max(axis=1)
    end = run.argmax(axis=1)

    min_run = max(8, w // 60)
    min_rows = max(4, h // 90)
    rows = best >= min_run
    start_row = span = bs = bl = 0
    for y, ok in enumerate(rows):
        if ok:
            if span == 0:
                start_row = y
            span += 1
            if span > bl:
                bs, bl = start_row, span
        else:
            span = 0
    if bl < min_rows:
        return None

    my_row = bs + bl // 2
    cx = x0 + end[my_row] - best[my_row] // 2
    cy = y0 + my_row
    return (left + cx * ds, top + cy * ds)


def open_book(profile, *, asin=None, url=None, page_turn=None,
              no_fullscreen=False, no_rewind=False, max_rewind=1000,
              load_wait=45, emit=null_emit):
    """Kindle Cloud Reader で本を開き、全画面化して先頭ページに合わせる。

    Args:
        profile: CaptureProfile (通常 kindle_cloud)
        asin: 本の ASIN (read.amazon.co.jp/?asin=<ASIN> を開く)
        url: 開く URL の直接指定 (asin より優先)
        page_turn: 次ページのキーの上書き (巻き戻しはその逆を押す)
        no_fullscreen: 全画面化をスキップ
        no_rewind: 先頭ページへの巻き戻しをスキップ
        max_rewind: 巻き戻しキーを押す回数の上限
        load_wait: ページ読み込み完了を待つ最大秒数
        emit: イベントコールバック

    Returns:
        終了コード
    """
    from core.platform_utils import allow_sleep, prevent_sleep

    if page_turn:
        profile.page_turn_key = page_turn

    # 読み込み待ちの間はキー入力が無く画面が消灯・ロックしうる（ロック画面は
    # 真っ黒に映り「読み込み未完了」と誤判定される）。open 全体でスリープを抑止する。
    prevent_sleep()
    try:
        return _open_impl(profile, asin=asin, url=url,
                          no_fullscreen=no_fullscreen, no_rewind=no_rewind,
                          max_rewind=max_rewind, load_wait=load_wait, emit=emit)
    finally:
        allow_sleep()


def _open_impl(profile, *, asin, url, no_fullscreen, no_rewind,
               max_rewind, load_wait, emit):
    import numpy as np
    import pyautogui as pag

    from core.platform_utils import (
        WINDOW_NOT_FOUND_HINT,
        get_window_process_name,
        get_window_rect,
        get_window_title,
        grab_screen,
        is_window_fullscreen,
        missing_permissions,
        open_path,
        process_name_matches,
        toggle_fullscreen,
    )

    missing = missing_permissions()
    if missing:
        warn = (
            f"警告: macOS の権限（{'・'.join(missing)}）が許可されていません。"
            "システム設定 > プライバシーとセキュリティ で許可してください"
        )
        emit("status", human=warn, message=warn, missing_permissions=missing)

    url = url or f"https://read.amazon.co.jp/?asin={asin}"
    open_path(url)
    emit("opened", human=f"ブラウザで開いています: {url}", url=url)
    # 新しいタブがアクティブになる前に既存タブの静止画面を「読み込み完了」と
    # 誤判定しないよう、まず固定で待つ
    time.sleep(5)

    # 対象ウィンドウの出現を待つ (プロセス名も照合)
    engine = CaptureEngine(profile, exclude_pid=os.getpid())
    hwnd = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        cand = engine.find_target_window()
        if cand is not None:
            exe = get_window_process_name(cand)
            if process_name_matches(exe, profile.process_name):
                hwnd = cand
                break
        time.sleep(1)
    if hwnd is None:
        emit_error(
            emit,
            f"対象ウィンドウが見つかりません: {profile.window_title_keyword} "
            f"(プロセス: {profile.process_name or '指定なし'}){WINDOW_NOT_FOUND_HINT}"
        )
        return EXIT_WINDOW_NOT_FOUND
    emit(
        "window_found",
        human=f'検出ウィンドウ: "{get_window_title(hwnd)}"',
        title=get_window_title(hwnd), process=get_window_process_name(hwnd),
    )

    engine.activate_target_window(hwnd)

    def grab_thumb():
        try:
            img = grab_screen(get_window_rect(hwnd))
        except OSError as e:
            # ロック画面・セッション切断中は grabscreen が失敗する
            raise ScreenLocked(str(e)) from e
        return np.asarray(img.convert("L").resize((64, 64)), dtype=np.float32)

    # 開始時点でロックされていないか確認 (ロック中は真っ黒に映り誤動作するため)
    try:
        grab_thumb()
    except ScreenLocked:
        emit_error(
            emit,
            "画面がロックされています。ロックを解除してから再実行してください"
            "（無人実行ではロックされない設定にしてください）"
        )
        return EXIT_ERROR

    def wait_stable(timeout, need_content=True):
        """描画が静止する (連続2回のグラブがほぼ同一になる) まで待つ。

        need_content=True の場合、ほぼ一様な画面 (読み込み中の白画面) は
        静止していても完了とみなさない。

        キャプチャ中の静止待ち (CaptureEngine._wait_stable_page) とは別物:
        あちらはプロファイルのしきい値でページ遷移の完了を検出する。
        こちらは開いた直後の読み込み完了をゆっくり (1.2秒間隔) 監視する。
        """
        prev = grab_thumb()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            time.sleep(1.2)
            cur = grab_thumb()
            if float(np.abs(cur - prev).mean()) < 0.5 and \
                    (not need_content or cur.std() > 8):
                return True
            prev = cur
        return False

    def looks_blank_stable():
        """描画は静止しているが、ほぼ一様（=白ページで開いた）かを判定する。"""
        a = grab_thumb()
        time.sleep(1.2)
        b = grab_thumb()
        return float(np.abs(b - a).mean()) < 0.5 and b.std() <= 8

    loaded = wait_stable(load_wait)
    if not loaded and looks_blank_stable():
        # Whispersync の続き位置が章扉・奥付などほぼ白いページだと、
        # 「読み込み中の白画面」と区別できず wait_stable は永遠に通らない
        # （実測: 白ページの std は 2.5〜5、本文ページは 10 以上）。
        # 1ページめくって本文に移してから再判定する。まず進み、終端で
        # 変化しなければ戻る。この後で先頭ページへ巻き戻すため、ここで
        # 位置を動かしても結果には影響しない。
        engine.activate_target_window(hwnd)
        fwd = profile.page_turn_key
        for key in (fwd, reverse_page_turn_key(fwd)):
            emit("status",
                 human=f"ほぼ白いページで開きました。{key} キーで1ページ動かして再確認します",
                 message="blank_page_nudge", key=key)
            pag.press(key)
            time.sleep(1.5)
            if wait_stable(15):
                loaded = True
                break
    if not loaded:
        emit_error(emit, f"{load_wait}秒待ちましたが読み込みが完了しませんでした")
        return EXIT_ERROR
    emit("loaded", human="読み込み完了")

    # 位置同期ダイアログ (「前回読んでいたページ」) を閉じる。開いたままだと
    # 以降のクリック・キー入力がすべて吸われる。確定ボタンを押すと読書位置へ
    # 移動するが、この後の巻き戻しで先頭に戻るので位置は問わない。
    btn = _find_modal_button(hwnd)
    if btn is not None:
        emit("status", human="位置同期ダイアログを閉じます",
             message="position_dialog_dismiss", x=btn[0], y=btn[1])
        engine.activate_target_window(hwnd)
        pag.click(btn[0], btn[1])
        time.sleep(2)
        wait_stable(load_wait)
        if _find_modal_button(hwnd) is not None:
            emit("status",
                 human="注意: 位置同期ダイアログを閉じられなかった可能性があります",
                 message="position_dialog_remains")

    # 全画面化 (F11 / Control+Command+F はトグルなので、すでに全画面なら押さない)
    if not no_fullscreen:
        if is_window_fullscreen(hwnd):
            emit("fullscreen", human="すでに全画面表示です", entered=False)
        else:
            engine.activate_target_window(hwnd)
            toggle_fullscreen()
            # macOS は全画面スペースへの切り替えアニメーションがあるため長めに待つ
            time.sleep(3 if sys.platform == "darwin" else 2)
            wait_stable(15)
            emit("fullscreen", human="全画面にしました", entered=True)

    # リーダー UI (ツールバー・左右矢印・下部の位置バー) を隠す。中央クリックで
    # 表示/非表示がトグルする。UI が写ると絵の上下端や左右に重なる (特にマンガは
    # 全面が絵) ため、キャプチャ前に必ず消す。UI を消すと下部の位置バーも消える。
    #
    # 判定は差分方式: 同一ページはクリックしても絵が不変なので、クリック前後の
    # 矢印帯の暗ピクセル差が UI 分になる。暗ピクセルが少ない方が UI 非表示なので、
    # そちらの状態で終える。絶対値だと絵が余白に食い込むページで誤判定するため。
    rect = get_window_rect(hwnd)
    ccx, ccy = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    a = _reader_arrow_dark(hwnd)
    pag.click(ccx, ccy)
    time.sleep(1.2)
    b = _reader_arrow_dark(hwnd)
    if b > a + 15:
        # クリックで UI が出た → 今は表示状態。もう一度クリックして消す。
        pag.click(ccx, ccy)
        time.sleep(1.2)
        c = _reader_arrow_dark(hwnd)
        hidden = c <= a + 15
    else:
        # b <= a: いま暗ピクセルが少ない=UI 非表示側にいる
        hidden = True
    emit(
        "ui_bar",
        human=("リーダー UI: 非表示" if hidden else
               "注意: リーダー UI を非表示にできなかった可能性があります"),
        hidden=hidden, arrow_before=a, arrow_after=b,
    )

    # 先頭ページへ巻き戻し
    if no_rewind:
        emit("result", human="準備完了（巻き戻しなし）", ok=True, rewound=False)
        return EXIT_OK

    prev_key = reverse_page_turn_key(profile.page_turn_key)
    emit(
        "rewind_start",
        human=f"先頭ページへ巻き戻します（{prev_key} キー連打、ページが変化しなくなるまで）...",
        key=prev_key,
    )
    thumb = grab_thumb()
    presses = 0
    stable = 0
    while presses < max_rewind:
        pag.press(prev_key)
        presses += 1
        changed = False
        end = time.monotonic() + 2.5
        while time.monotonic() < end:
            time.sleep(0.15)
            cur = grab_thumb()
            if float(np.abs(cur - thumb).mean()) > 1.0:
                changed = True
                break
        if changed:
            stable = 0
            # 描画途中のフレームを基準にしないよう、少し待ってから取り直す
            time.sleep(0.5)
            thumb = grab_thumb()
        else:
            thumb = cur
            stable += 1
            if stable >= 2:
                break
        if presses % 10 == 0:
            emit("rewind", human=f"巻き戻し中... {presses} ページ", presses=presses)

    at_first = stable >= 2
    if at_first:
        emit(
            "result",
            human=f"先頭ページに到達しました（{presses} 回めくり、うち2回は終端確認）",
            ok=True, at_first_page=True, presses=presses,
        )
        return EXIT_OK
    emit(
        "result",
        human=f"--max-rewind {max_rewind} に達しましたが先頭を確認できていません",
        ok=False, at_first_page=False, presses=presses,
    )
    return EXIT_ERROR
