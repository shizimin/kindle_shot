"""GUI のサイト選択リスト（画面仕様書 §6-1）

表示順とラベルの組み立てをここに集約する。キャプチャ設定画面が使う。
"""

from core.capture_profiles import (
    BUILTIN_PROFILES,
    CaptureProfile,
    merge_profile_data,
    profile_display_order,
)

# 実機検証済みプロファイルに付けるバッジ
VERIFIED_BADGE = " ✔動作確認済み"


def build_profile_choices(config=None):
    """[(プロファイルキー, 表示ラベル), ...] を表示順で返す。

    ビルトインは日本語表示名（検証済みならバッジ付き）、config のカスタムは
    「カスタム: <名前>」。ラベルが衝突する場合はキーを添えて一意にする
    （コンボボックスはラベルで値を識別するため）。
    """
    choices = []
    used = set()
    saved_profiles = (config or {}).get("capture", {}).get("profiles", {}) or {}
    for key in profile_display_order(config):
        builtin = BUILTIN_PROFILES.get(key)
        if builtin is not None:
            label = builtin.display_label(key)
            if builtin.verified:
                label += VERIFIED_BADGE
        else:
            saved = saved_profiles.get(key, {})
            name = saved.get("display_name") or saved.get("name") or key
            label = f"カスタム: {name}"
        if label in used:
            label = f"{label}（{key}）"
        used.add(label)
        choices.append((key, label))
    return choices


def resolve_profile(profile_key, config=None, overrides=None):
    """キーと上書き値から CaptureProfile を組み立てる。

    ビルトイン → config 保存値 → overrides の優先順位（画面仕様書 §6-2）。
    """
    return CaptureProfile.from_dict(
        merge_profile_data(profile_key, config, overrides)
    )
