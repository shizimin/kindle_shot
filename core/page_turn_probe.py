"""ページ送りキーの自動判定（画面仕様書 §6-3）

候補キーを順に試し、そのキーで実際にページが送られるかどうかで
ページ送りキーを特定する。2026-08 のサイト別プロファイル実機検証で確立した
「候補キーごとに `--max-pages 3` の短いキャプチャを実行して判定する」手順を
関数化したもの。GUI の「自動で調べる」ボタンと、将来の CLI から共通で使う。

先頭ページから始める前提で、逆方向キーは無反応になるため誤検出しない
（検証記録 §5 の知見）。判定に使ったキャプチャ画像は著作物なので、
試行ごとに一時フォルダごと削除する。

キャプチャ実行部（Win32 依存）は capture_fn / rewind_fn として差し替えられる。
候補キーの順序・成功判定・戻し回数の計算は純ロジックとしてテストしている。

emit / 終了コードの規約は core.pipeline のモジュール docstring を参照。

効かないキー1つあたり約35秒から約12秒へ短縮する。2026-08-29 の実機確認で、
コミックシーモアの縦読み設定では正解の down が最後になり約3分かかったため。
"""

import tempfile
import time

from core.capture_profiles import CaptureProfile, reverse_page_turn_key
from core.pipeline import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_WINDOW_NOT_FOUND,
    emit_error,
    null_emit,
)

# 試す順番（画面仕様書 §6-3・2026-08-26 ユーザー確定で全6キー）。
# ページ送りキーは本によってかなり変わるため、右綴じで多い left から順に全部試す。
PROBE_KEY_ORDER = ("left", "right", "pagedown", "pageup", "up", "down")

# 1キーあたりのキャプチャ枚数の上限（この枚数で止まれば「送れた」）
PROBE_MAX_PAGES = 3

# 判定専用設定で、効かないキーの待ち時間を約35秒から約12秒へ短縮する。
# 2026-08-29、コミックシーモアの縦読みで正解の down が最後になり約3分かかったため。
PROBE_TIMEOUT_SECONDS = 3.0
PROBE_MAX_RETRIES = 1

# F11 全画面化は1キー目の待機中に済むため、2キー目以降は開始前待機を短縮する。
PROBE_FOLLOWUP_FULLSCREEN_WAIT = 1.0

# 一時フォルダ内に作られるサブフォルダ名（run_capture の title 引数）
PROBE_TITLE = "page_turn_probe"

# 戻しキーを連打するときの間隔（秒）
REWIND_INTERVAL = 0.2


def probe_profile_for(profile, *, first):
    """元の設定を変更せず、ページ送りキー判定専用のプロファイルを返す。"""
    probe_profile = CaptureProfile.from_dict(profile.to_dict())
    probe_profile.timeout_seconds = PROBE_TIMEOUT_SECONDS
    probe_profile.max_retries = PROBE_MAX_RETRIES
    if not first:
        probe_profile.fullscreen_wait = PROBE_FOLLOWUP_FULLSCREEN_WAIT
    return probe_profile


def is_page_turn_detected(pages_captured):
    """そのキーでページが送られたと判定できるか。

    1枚しか撮れずに timeout 停止した場合は「画面が変化しなかった」＝不発。
    2枚以上撮れていれば、キーによって次ページが表示されたということ。
    """
    return pages_captured >= 2


def rewind_press_count(pages_captured):
    """先頭ページへ戻すために逆方向キーを押す回数。

    CaptureEngine は「1ページ目を撮る → キー送信 → 2ページ目を撮る → …」の
    順で動き、max_pages で止まるときも最後のページを撮った直後にキーを1回
    送る。そのため撮れた枚数と同じ回数だけ前へ進んでいる。
    """
    if pages_captured < 1:
        return 0
    return pages_captured


def _capture_probe_pages(profile, key, *, max_pages=PROBE_MAX_PAGES,
                         stop_event=None, strict_process=True):
    """一時フォルダへ短いキャプチャを実行し、(終了コード, 撮れた枚数) を返す。

    画像は一時フォルダごと削除する（著作物を残さない）。受け取った判定専用の
    profile も複製し、run_capture による変更が呼び出し側へ波及しないようにする。
    """
    from core.capture_runner import run_capture

    pages = 0

    def count_emit(event, human=None, **fields):
        nonlocal pages
        if event == "page":
            pages += 1

    # profile を書き換えられても呼び出し側に影響しないよう複製して渡す
    # （run_capture は page_turn を profile へ反映する）
    probe_profile = CaptureProfile.from_dict(profile.to_dict())
    with tempfile.TemporaryDirectory(prefix="kindle_shot_probe_") as tmp_dir:
        code = run_capture(
            probe_profile, PROBE_TITLE, tmp_dir,
            page_turn=key, max_pages=max_pages, overwrite=True,
            stop_event=stop_event, strict_process=strict_process,
            emit=count_emit,
        )
    return code, pages


def _press_key(key, times, interval=REWIND_INTERVAL):
    """キーを times 回送る（戻し用の既定実装）。"""
    if times <= 0:
        return
    import pyautogui as pag

    for _ in range(times):
        pag.keyDown(key)
        pag.keyUp(key)
        time.sleep(interval)


def probe_page_turn_key(profile, *, keys=None, max_pages=PROBE_MAX_PAGES,
                        stop_event=None, strict_process=True,
                        capture_fn=None, rewind_fn=None, emit=null_emit):
    """候補キーを順に試してページ送りキーを特定する。

    本の先頭ページを表示した状態で呼ぶこと。成功したキーで進んだ分は
    逆方向キーで戻す（ベストエフォート。失敗しても result イベントの
    rewound=False で通知するだけで、判定結果は返す）。

    Args:
        profile: CaptureProfile（page_turn_key は候補キーで上書きされる）
        keys: 試す候補キー（既定は PROBE_KEY_ORDER）
        max_pages: 1キーあたりのキャプチャ枚数の上限
        stop_event: 外部からの中止要求 (threading.Event)
        strict_process: プロセス名不一致を拒否するか (find_verified_window 参照)
        capture_fn: キャプチャ実行の差し替え (profile, key, max_pages=,
            stop_event=, strict_process=) -> (終了コード, 撮れた枚数)
        rewind_fn: 戻しキー送信の差し替え (key, times)
        emit: イベントコールバック
            probe_key_start / probe_key_result / probe_rewind / result

    Returns:
        判定できたキー名。全キー不発・中止・エラー時は None
    """
    keys = tuple(keys) if keys else PROBE_KEY_ORDER
    capture_fn = capture_fn or _capture_probe_pages
    rewind_fn = rewind_fn or _press_key
    tried = []

    def finish(ok, key, exit_code, **fields):
        emit(
            "result",
            human=(
                f"ページ送りキーを特定しました: {key}" if ok
                else "ページ送りキーを特定できませんでした"
            ),
            ok=ok, page_turn_key=key, exit_code=exit_code, tried=tried, **fields,
        )
        return key if ok else None

    for index, key in enumerate(keys):
        if stop_event is not None and stop_event.is_set():
            emit_error(emit, "ページ送りキーの判定を中止しました")
            return finish(False, None, EXIT_ERROR)

        emit("probe_key_start", human=f"「{key}」を試しています...", key=key)
        probe_profile = probe_profile_for(profile, first=(index == 0))
        code, pages = capture_fn(
            probe_profile, key, max_pages=max_pages, stop_event=stop_event,
            strict_process=strict_process,
        )
        detected = is_page_turn_detected(pages)
        tried.append(key)
        emit(
            "probe_key_result",
            human=(
                f"「{key}」: {pages}ページ送られました" if detected
                else f"「{key}」: 変化なし"
            ),
            key=key, pages=pages, detected=detected, exit_code=code,
        )

        if code == EXIT_WINDOW_NOT_FOUND:
            emit_error(
                emit,
                f"対象ウィンドウが見つかりません: {profile.window_title_keyword}",
            )
            return finish(False, None, EXIT_WINDOW_NOT_FOUND)

        if not detected:
            continue

        presses = rewind_press_count(pages)
        rewind_key = reverse_page_turn_key(key)
        rewound = True
        try:
            rewind_fn(rewind_key, presses)
        except Exception as e:  # 戻しは best effort（判定結果は捨てない）
            rewound = False
            emit(
                "probe_rewind",
                human=f"先頭ページへ戻せませんでした（手動で戻してください）: {e}",
                ok=False, key=rewind_key, presses=presses, message=str(e),
            )
        else:
            emit(
                "probe_rewind",
                human=f"「{rewind_key}」を{presses}回送って先頭ページへ戻しました",
                ok=True, key=rewind_key, presses=presses,
            )
        return finish(True, key, EXIT_OK, pages=pages,
                      rewind_key=rewind_key, rewind_presses=presses,
                      rewound=rewound)

    emit_error(emit, "どの候補キーでもページが送られませんでした")
    return finish(False, None, EXIT_ERROR)
