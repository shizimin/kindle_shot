"""core/page_turn_probe.py のテスト（純ロジック部分）

キャプチャ実行部は Win32 実機依存のため、capture_fn / rewind_fn を
差し替えて候補キーの順序・成功判定・戻し回数・イベントを検証する。
"""

import threading

from core.capture_profiles import BUILTIN_PROFILES, PAGE_TURN_KEYS
from core.page_turn_probe import (
    PROBE_FOLLOWUP_FULLSCREEN_WAIT,
    PROBE_KEY_ORDER,
    PROBE_MAX_PAGES,
    PROBE_MAX_RETRIES,
    PROBE_TIMEOUT_SECONDS,
    is_page_turn_detected,
    probe_page_turn_key,
    probe_profile_for,
    rewind_press_count,
)
from core.pipeline import EXIT_ERROR, EXIT_OK, EXIT_WINDOW_NOT_FOUND


def make_profile():
    return BUILTIN_PROFILES["kobo_web"]


class Recorder:
    """emit の記録用。"""

    def __init__(self):
        self.events = []

    def __call__(self, event, human=None, **fields):
        self.events.append((event, fields))

    def names(self):
        return [name for name, _ in self.events]

    def by_name(self, name):
        return [f for n, f in self.events if n == name]


def fake_capture(results, calls=None):
    """キーごとの (終了コード, 撮れた枚数) を返す capture_fn を作る。"""
    def capture_fn(profile, key, *, max_pages, stop_event=None,
                   strict_process=True):
        if calls is not None:
            calls.append((key, max_pages))
        return results.get(key, (EXIT_OK, 1))
    return capture_fn


# ------------------------------------------------------------
# 純ロジック
# ------------------------------------------------------------

def test_probe_key_order_matches_spec():
    """全6キーを仕様どおりの順で試す（画面仕様書 §6-3）。"""
    assert PROBE_KEY_ORDER == ("left", "right", "pagedown", "pageup", "up", "down")
    # PAGE_TURN_KEYS と過不足なく一致していること（キーが増えたら追従させる）
    assert set(PROBE_KEY_ORDER) == set(PAGE_TURN_KEYS)
    assert len(PROBE_KEY_ORDER) == len(PAGE_TURN_KEYS)


def test_is_page_turn_detected():
    assert is_page_turn_detected(0) is False
    assert is_page_turn_detected(1) is False  # 1枚で timeout 停止 = 不発
    assert is_page_turn_detected(2) is True
    assert is_page_turn_detected(3) is True


def test_rewind_press_count():
    # 撮れた枚数と同じ回数だけキーを送っている（最後のページの後にも1回送る）
    assert rewind_press_count(0) == 0
    assert rewind_press_count(2) == 2
    assert rewind_press_count(3) == 3


def test_probe_profile_for_uses_fast_settings_without_mutating_original():
    profile = make_profile()
    original = profile.to_dict()

    first_profile = probe_profile_for(profile, first=True)
    followup_profile = probe_profile_for(profile, first=False)

    assert first_profile.timeout_seconds == PROBE_TIMEOUT_SECONDS
    assert first_profile.max_retries == PROBE_MAX_RETRIES
    assert first_profile.fullscreen_wait == profile.fullscreen_wait
    assert followup_profile.timeout_seconds == PROBE_TIMEOUT_SECONDS
    assert followup_profile.max_retries == PROBE_MAX_RETRIES
    assert followup_profile.fullscreen_wait == PROBE_FOLLOWUP_FULLSCREEN_WAIT
    assert profile.to_dict() == original


# ------------------------------------------------------------
# probe_page_turn_key（capture_fn 差し替え）
# ------------------------------------------------------------

def test_probe_returns_first_working_key():
    calls = []
    emit = Recorder()
    key = probe_page_turn_key(
        make_profile(), emit=emit,
        capture_fn=fake_capture({"left": (EXIT_OK, 3)}, calls),
        rewind_fn=lambda k, n: None,
    )
    assert key == "left"
    assert calls == [("left", PROBE_MAX_PAGES)]  # 成功したら以降は試さない
    res = emit.by_name("result")[0]
    assert res["ok"] is True
    assert res["page_turn_key"] == "left"
    assert res["exit_code"] == EXIT_OK
    assert res["tried"] == ["left"]
    assert res["rewind_key"] == "right"
    assert res["rewind_presses"] == 3
    assert res["rewound"] is True


def test_probe_skips_dead_keys_in_order():
    calls = []
    key = probe_page_turn_key(
        make_profile(),
        capture_fn=fake_capture({"pagedown": (EXIT_OK, 2)}, calls),
        rewind_fn=lambda k, n: None,
    )
    assert key == "pagedown"
    assert [c[0] for c in calls] == ["left", "right", "pagedown"]


def test_probe_passes_fast_profile_settings_to_capture_fn():
    original_profile = make_profile()
    captured_profiles = []

    def recording_capture(profile, key, *, max_pages, stop_event=None,
                          strict_process=True):
        captured_profiles.append(profile)
        return EXIT_OK, 1

    key = probe_page_turn_key(
        original_profile,
        capture_fn=recording_capture,
        rewind_fn=lambda k, n: None,
    )

    assert key is None
    assert len(captured_profiles) == len(PROBE_KEY_ORDER)
    assert captured_profiles[0].fullscreen_wait == original_profile.fullscreen_wait
    assert all(
        profile.fullscreen_wait == PROBE_FOLLOWUP_FULLSCREEN_WAIT
        for profile in captured_profiles[1:]
    )
    assert all(
        profile.timeout_seconds == PROBE_TIMEOUT_SECONDS
        and profile.max_retries == PROBE_MAX_RETRIES
        for profile in captured_profiles
    )


def test_probe_returns_none_when_all_keys_fail():
    emit = Recorder()
    calls = []
    key = probe_page_turn_key(
        make_profile(), emit=emit, capture_fn=fake_capture({}, calls),
    )
    assert key is None
    assert [c[0] for c in calls] == list(PROBE_KEY_ORDER)  # 全6キーを試す
    assert emit.by_name("error")
    res = emit.by_name("result")[0]
    assert res["ok"] is False
    assert res["page_turn_key"] is None
    assert res["exit_code"] == EXIT_ERROR
    assert res["tried"] == list(PROBE_KEY_ORDER)


def test_probe_aborts_on_window_not_found():
    emit = Recorder()
    calls = []
    key = probe_page_turn_key(
        make_profile(), emit=emit,
        capture_fn=fake_capture({"left": (EXIT_WINDOW_NOT_FOUND, 0)}, calls),
    )
    assert key is None
    assert [c[0] for c in calls] == ["left"]  # 2キー目は試さない
    assert emit.by_name("error")
    assert emit.by_name("result")[0]["exit_code"] == EXIT_WINDOW_NOT_FOUND


def test_probe_rewinds_with_reverse_key():
    rewinds = []
    probe_page_turn_key(
        make_profile(),
        capture_fn=fake_capture({"right": (EXIT_OK, 3)}),
        rewind_fn=lambda k, n: rewinds.append((k, n)),
    )
    assert rewinds == [("left", 3)]


def test_probe_reports_rewind_failure_but_keeps_result():
    emit = Recorder()

    def broken_rewind(key, times):
        raise RuntimeError("キー送信に失敗")

    key = probe_page_turn_key(
        make_profile(), emit=emit,
        capture_fn=fake_capture({"left": (EXIT_OK, 3)}),
        rewind_fn=broken_rewind,
    )
    assert key == "left"  # 戻し失敗でも判定結果は返す
    assert emit.by_name("probe_rewind")[0]["ok"] is False
    assert emit.by_name("result")[0]["rewound"] is False


def test_probe_emits_progress_events_per_key():
    emit = Recorder()
    probe_page_turn_key(
        make_profile(), emit=emit,
        capture_fn=fake_capture({"right": (EXIT_OK, 2)}),
        rewind_fn=lambda k, n: None,
    )
    starts = emit.by_name("probe_key_start")
    results = emit.by_name("probe_key_result")
    assert [s["key"] for s in starts] == ["left", "right"]
    assert results[0] == {"key": "left", "pages": 1, "detected": False,
                          "exit_code": EXIT_OK}
    assert results[1]["detected"] is True
    assert results[1]["pages"] == 2
    # 既存の emit 契約と同じ形（イベント名・fields）で通知する
    assert emit.names()[-1] == "result"


def test_probe_honors_stop_event():
    emit = Recorder()
    stop = threading.Event()
    stop.set()
    calls = []
    key = probe_page_turn_key(
        make_profile(), emit=emit, stop_event=stop,
        capture_fn=fake_capture({"left": (EXIT_OK, 3)}, calls),
    )
    assert key is None
    assert calls == []
    assert emit.by_name("result")[0]["exit_code"] == EXIT_ERROR


def test_probe_accepts_custom_key_list():
    calls = []
    key = probe_page_turn_key(
        make_profile(), keys=("up", "down"),
        capture_fn=fake_capture({"down": (EXIT_OK, 2)}, calls),
        rewind_fn=lambda k, n: None,
    )
    assert key == "down"
    assert [c[0] for c in calls] == ["up", "down"]


def test_probe_does_not_mutate_the_given_profile():
    profile = make_profile()
    before = profile.page_turn_key
    probe_page_turn_key(
        profile,
        capture_fn=fake_capture({"right": (EXIT_OK, 2)}),
        rewind_fn=lambda k, n: None,
    )
    assert profile.page_turn_key == before
