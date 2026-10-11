"""core/config.py のテスト（deep_merge・load/save round-trip）"""

import json

from core import config as config_mod
from core.config import DEFAULT_CONFIG, _deep_merge, load_config, save_config


def test_default_config_has_no_builtin_profile_copies():
    """ビルトインの正本は capture_profiles.py のみ（画面仕様書 §6-2）。"""
    assert DEFAULT_CONFIG["capture"]["profiles"] == {}


def test_default_config_profiles_are_treated_as_diff(isolated_config):
    """config に保存されたビルトインキーは差分として効く（GUI/CLI 共通）。"""
    from core.capture_profiles import get_profile

    isolated_config.write_text(
        json.dumps({"capture": {"profiles": {"kindle": {"page_wait": 0.9}}}}),
        encoding="utf-8",
    )
    profile = get_profile("kindle", load_config())
    assert profile.page_wait == 0.9
    assert profile.process_name == "Kindle.exe"  # ビルトイン由来


def test_deep_merge_overrides_nested_values():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    override = {"a": {"b": 10}}
    merged = _deep_merge(base, override)
    assert merged == {"a": {"b": 10, "c": 2}, "d": 3}


def test_deep_merge_keeps_unknown_keys():
    base = {"a": 1}
    override = {"z": {"nested": True}}
    merged = _deep_merge(base, override)
    assert merged["a"] == 1
    assert merged["z"] == {"nested": True}


def test_deep_merge_does_not_mutate_inputs():
    base = {"a": {"b": [1, 2]}}
    override = {"a": {"c": {"d": 1}}}
    merged = _deep_merge(base, override)
    merged["a"]["b"].append(3)
    merged["a"]["c"]["d"] = 99
    assert base == {"a": {"b": [1, 2]}}
    assert override == {"a": {"c": {"d": 1}}}


def test_load_config_returns_defaults_when_missing(isolated_config):
    cfg = load_config()
    assert cfg == DEFAULT_CONFIG
    # 返り値を書き換えても DEFAULT_CONFIG が汚染されないこと
    cfg["ocr"]["workers"] = 99
    assert DEFAULT_CONFIG["ocr"]["workers"] != 99


def test_load_config_merges_partial_user_config(isolated_config):
    isolated_config.write_text(
        json.dumps({"ocr": {"workers": 4}}), encoding="utf-8"
    )
    cfg = load_config()
    # ユーザー設定が優先される
    assert cfg["ocr"]["workers"] == 4
    # 書かれていないキーはデフォルトで補完される
    assert cfg["ocr"]["preprocess"]["enabled"] is True
    assert "capture" in cfg


def test_save_and_load_round_trip(isolated_config):
    cfg = load_config()
    cfg["trim"]["left_margin"] = 123
    save_config(cfg)
    assert json.loads(isolated_config.read_text(encoding="utf-8"))["trim"]["left_margin"] == 123
    assert load_config()["trim"]["left_margin"] == 123
    assert str(isolated_config) == config_mod.CONFIG_FILE
