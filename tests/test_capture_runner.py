from core.capture_runner import choose_cursor_park_point, waiting_message

MONITOR_RECTS = [(0, 0, 2560, 1440), (2560, 0, 6400, 3600)]


def test_waiting_message_omits_f11_guidance_when_already_fullscreen():
    assert waiting_message(3, True) == "3秒待機後にキャプチャを開始します..."


def test_waiting_message_includes_f11_guidance_when_not_fullscreen():
    assert waiting_message(3, False) == (
        "3秒待機後にキャプチャを開始します..."
        "（この間にビューアを F11 で全画面にしてください）"
    )


def test_choose_cursor_park_point_uses_left_monitor_for_right_fullscreen_window():
    assert choose_cursor_park_point(
        (2560, 0, 6400, 3600), MONITOR_RECTS
    ) == (1280, 720)


def test_choose_cursor_park_point_uses_right_monitor_for_window_on_left():
    assert choose_cursor_park_point(
        (100, 100, 1000, 800), MONITOR_RECTS
    ) == (4480, 1800)


def test_choose_cursor_park_point_returns_none_for_single_monitor():
    assert choose_cursor_park_point(
        (0, 0, 2560, 1440), [(0, 0, 2560, 1440)]
    ) is None


def test_choose_cursor_park_point_returns_none_when_window_spans_monitors():
    assert choose_cursor_park_point((2000, 0, 3000, 1000), MONITOR_RECTS) is None


def test_choose_cursor_park_point_returns_none_for_empty_monitor_list():
    assert choose_cursor_park_point((0, 0, 2560, 1440), []) is None


def test_choose_cursor_park_point_treats_touching_edges_as_non_overlapping():
    assert choose_cursor_park_point(
        (2560, 0, 6400, 3600), [(0, 0, 2560, 1440)]
    ) == (1280, 720)


def test_choose_cursor_park_point_supports_negative_monitor_coordinates():
    assert choose_cursor_park_point(
        (0, 0, 2560, 1440), [(-1920, 0, 0, 1080), (0, 0, 2560, 1440)]
    ) == (-960, 540)
