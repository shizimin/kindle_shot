"""core/capture_profiles.py のテスト

settle_* フィールドの round-trip はGUIの「プロファイル再構築で settle が
脱落する」バグの回帰テスト。
"""

from core.capture_profiles import (
    BUILTIN_PROFILES,
    PAGE_TURN_KEYS,
    PROFILE_DISPLAY_ORDER,
    CaptureProfile,
    get_all_profile_keys,
    get_profile,
    merge_profile_data,
    profile_display_order,
    reverse_page_turn_key,
)


def test_to_dict_from_dict_round_trip_preserves_all_fields():
    src = BUILTIN_PROFILES["kindle_cloud"]
    restored = CaptureProfile.from_dict(src.to_dict())
    assert restored == src
    # settle_* が特に脱落しないこと（GUI 再構築バグの回帰確認）
    assert restored.settle_enabled is True
    assert restored.settle_frames == src.settle_frames
    assert restored.settle_threshold == src.settle_threshold


def test_from_dict_ignores_unknown_keys():
    data = BUILTIN_PROFILES["kindle"].to_dict()
    data["unknown_future_field"] = 123
    profile = CaptureProfile.from_dict(data)
    assert profile.name == "Kindle for PC"
    assert not hasattr(profile, "unknown_future_field")


def test_kindle_cloud_builtin_has_settle_enabled():
    assert BUILTIN_PROFILES["kindle_cloud"].settle_enabled is True
    assert BUILTIN_PROFILES["kindle"].settle_enabled is False


def test_all_builtins_have_display_name():
    for key, profile in BUILTIN_PROFILES.items():
        assert profile.display_name, f"{key} に display_name がない"
        assert profile.display_label(key) == profile.display_name


def test_display_label_falls_back_to_name_then_key():
    assert CaptureProfile(name="My Viewer").display_label("my_viewer") == "My Viewer"
    assert CaptureProfile().display_label("my_viewer") == "my_viewer"
    assert CaptureProfile(name="n", display_name="D").display_label() == "D"


def test_builtins_are_the_six_verified_profiles():
    """未検証の PC アプリ版5種は 2026-08-27 に削除済み（ビルトインは6種）。"""
    assert set(BUILTIN_PROFILES) == {
        "kindle_cloud", "kobo_web", "google_play_web", "dmm_web", "cmoa_web",
        "kindle",
    }
    for key in ("google_play", "rakuten_kobo", "bookwalker",
                "dmm_books", "kinoppy"):
        assert key not in BUILTIN_PROFILES


def test_verified_flag_marks_all_builtins():
    verified = {k for k, p in BUILTIN_PROFILES.items() if p.verified}
    assert verified == set(BUILTIN_PROFILES)


def test_browser_profiles_use_kindle_cloud_template():
    """昇格4プロファイルは実証値（作業記録 §1〜4 の manifest 由来）どおりであること。"""
    expected_keys = {
        "kobo_web": ("Kobo Reader", "left"),
        "google_play_web": ("Google Play ブックス", "right"),
        "dmm_web": ("", "left"),
        "cmoa_web": ("シーモア", "left"),
    }
    for key, (keyword, page_turn) in expected_keys.items():
        p = BUILTIN_PROFILES[key]
        assert p.window_title_keyword == keyword
        assert p.page_turn_key == page_turn
        assert p.page_wait == 0.3
        assert p.click_position == "none"
        assert p.process_name == "chrome.exe"
        assert p.timeout_seconds == 6.0
        assert p.settle_enabled is True
        assert p.boundary_method == "full"


def test_dmm_web_is_the_only_book_title_keyword_profile():
    """DMM ブラウザ版だけ window_title_keyword が「本のタイトルの一部」。"""
    flagged = {
        k for k, p in BUILTIN_PROFILES.items() if p.title_keyword_is_book_title
    }
    assert flagged == {"dmm_web"}
    # 本ごとに入力させるため既定のキーワードは持たない
    assert BUILTIN_PROFILES["dmm_web"].window_title_keyword == ""


def test_new_fields_survive_round_trip():
    src = BUILTIN_PROFILES["dmm_web"]
    restored = CaptureProfile.from_dict(src.to_dict())
    assert restored == src
    assert restored.display_name == "DMMブックス（ブラウザ）"
    assert restored.verified is True
    assert restored.title_keyword_is_book_title is True


def test_profile_display_order_follows_spec():
    keys = profile_display_order()
    assert keys == list(PROFILE_DISPLAY_ORDER)
    # ブラウザ版が先頭に並び、PC アプリ版 (Kindle) はビルトインの最後
    assert keys.index("kindle_cloud") < keys.index("kindle")
    assert keys.index("cmoa_web") < keys.index("kindle")
    assert set(keys) == set(BUILTIN_PROFILES)


def test_profile_display_order_appends_custom_keys():
    config = {"capture": {"profiles": {"my_viewer": {}, "kindle": {}}}}
    keys = profile_display_order(config)
    assert keys[-1] == "my_viewer"          # カスタムは末尾
    assert keys.count("kindle") == 1        # ビルトインは重複しない
    assert keys[: len(PROFILE_DISPLAY_ORDER)] == list(PROFILE_DISPLAY_ORDER)


def test_get_profile_uses_builtin_as_base():
    """config に保存が無ければビルトインの値がそのまま出る（§6-2）。"""
    profile = get_profile("kindle_cloud", {"capture": {"profiles": {}}})
    assert profile.name == "Kindle Cloud Reader (Chrome)"
    assert profile.settle_enabled is True
    assert profile.page_turn_key == "left"


def test_get_profile_applies_config_diff_over_builtin():
    """ビルトインキーでも config の保存値が差分として効く（CLI/GUI 統一・§6-2）。"""
    config = {
        "capture": {
            "profiles": {
                "kindle_cloud": {"page_turn_key": "right", "page_wait": 1.5},
            },
        },
    }
    profile = get_profile("kindle_cloud", config)
    assert profile.page_turn_key == "right"   # config の差分が効く
    assert profile.page_wait == 1.5
    # 保存されていない項目はビルトイン由来のまま
    assert profile.settle_enabled is True
    assert profile.process_name == "chrome.exe"
    assert profile.display_name == "Kindle Cloud Reader（ブラウザ）"


def test_get_profile_matches_merge_profile_data():
    """CLI 経路 (get_profile) と GUI 経路 (merge_profile_data) が一致すること。"""
    config = {"capture": {"profiles": {"kindle": {"page_wait": 2.0}}}}
    for key in ("kindle", "kindle_cloud", "cmoa_web"):
        assert get_profile(key, config) == CaptureProfile.from_dict(
            merge_profile_data(key, config)
        )


def test_get_profile_ignores_obsolete_saved_keys():
    """旧 config に残る廃止フィールドがあっても解決できること。"""
    config = {
        "capture": {
            "profiles": {
                "kindle": {"l_margin": 1, "r_margin": 1, "page_wait": 0.9},
            },
        },
    }
    profile = get_profile("kindle", config)
    assert profile.page_wait == 0.9
    assert not hasattr(profile, "l_margin")


def test_get_profile_works_without_config():
    profile = get_profile("kobo_web")
    assert profile.window_title_keyword == "Kobo Reader"
    assert profile.verified is True


def test_get_profile_reads_custom_profile_from_config():
    config = {
        "capture": {
            "profiles": {
                "my_viewer": {"name": "My Viewer", "page_wait": 2.5},
            },
        },
    }
    profile = get_profile("my_viewer", config)
    assert profile.name == "My Viewer"
    assert profile.page_wait == 2.5


def test_get_profile_returns_none_for_unknown_key():
    assert get_profile("nope", {"capture": {"profiles": {}}}) is None
    assert get_profile("nope", None) is None


def test_get_profile_returns_independent_copy():
    """返り値を書き換えても BUILTIN_PROFILES が汚染されないこと。"""
    profile = get_profile("kindle_cloud")
    profile.page_turn_key = "right"
    assert BUILTIN_PROFILES["kindle_cloud"].page_turn_key == "left"


def test_merge_profile_data_keeps_settle_fields():
    """GUI のプロファイル再構築で settle_* が脱落していたバグの回帰テスト。"""
    data = merge_profile_data("kindle_cloud", {"capture": {"profiles": {}}},
                              overrides={"page_wait": 1.0})
    profile = CaptureProfile.from_dict(data)
    assert profile.settle_enabled is True
    assert profile.page_wait == 1.0
    assert profile.click_position == "none"


def test_merge_profile_data_layering_order():
    config = {
        "capture": {
            "profiles": {
                "kindle": {"page_wait": 2.0, "fullscreen_wait": 9.0},
            },
        },
    }
    # config がビルトインを上書きし、overrides が config を上書きする
    data = merge_profile_data("kindle", config, overrides={"page_wait": 3.0})
    assert data["page_wait"] == 3.0
    assert data["fullscreen_wait"] == 9.0
    assert data["process_name"] == "Kindle.exe"  # ビルトイン由来


def test_merge_profile_data_ignores_none_overrides():
    data = merge_profile_data("kindle", None,
                              overrides={"window_title_keyword": None})
    assert data["window_title_keyword"] == "kindle"


def test_merge_profile_data_unknown_key_uses_defaults():
    data = merge_profile_data("my_new_viewer", None)
    assert data["name"] == "my_new_viewer"
    profile = CaptureProfile.from_dict(data)
    assert profile.settle_enabled is False


def test_page_turn_keys_reverse_pairs():
    """全キーに逆方向キーがあり、2回反転すると元に戻ること。"""
    for key in PAGE_TURN_KEYS:
        rev = reverse_page_turn_key(key)
        assert rev in PAGE_TURN_KEYS, f"{key} の逆キー {rev} が候補に無い"
        assert rev != key
        assert reverse_page_turn_key(rev) == key


def test_reverse_page_turn_key_unknown_falls_back_left():
    # 手編集の config 等で未知のキーが入っても従来動作 (left) に落ちる
    assert reverse_page_turn_key("enter") == "left"
    assert reverse_page_turn_key("") == "left"
    assert reverse_page_turn_key(None) == "left"


def test_get_all_profile_keys_merges_builtin_and_config():
    config = {"capture": {"profiles": {"kindle": {}, "my_viewer": {}}}}
    keys = get_all_profile_keys(config)
    assert "kindle" in keys
    assert "kindle_cloud" in keys
    assert "my_viewer" in keys
    # 重複しない
    assert keys.count("kindle") == 1
