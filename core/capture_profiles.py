"""キャプチャプロファイル定義

各電子書籍アプリ向けの設定をプロファイルとして管理する。
ビルトインプロファイルは 6 種（すべて実機検証済み）: ブラウザ版 5 種
（Kindle Cloud Reader, 楽天Kobo, Google Play ブックス, DMMブックス,
コミックシーモア）と PC アプリ版 1 種（Kindle）。
これに加えてユーザーがカスタムプロファイルを作成・保存できる。

ブラウザ版4種（kobo_web / google_play_web / dmm_web / cmoa_web）の値は
docs/作業記録_2026-08-16_サイト別プロファイル検証.md の manifest 実証値。
Kindle PC アプリは 2026-08-27 にユーザーが実機確認した。

未検証だった PC アプリ版5種（google_play / rakuten_kobo / bookwalker /
dmm_books / kinoppy）は 2026-08-27 に削除した（設計値のままで動作未確認
だったため。必要なら config.json のカスタムプロファイルとして追加できる）。
"""

from dataclasses import asdict, dataclass

# ページめくりに使えるキー (pyautogui キー名) と逆方向キー。
# CLI の --page-turn / batch の page_turn / GUI のドロップダウンが
# ここを唯一の定義として参照する。
PAGE_TURN_KEYS = ("right", "left", "pagedown", "pageup", "down", "up")
_REVERSE_KEYS = {"right": "left", "left": "right",
                 "pagedown": "pageup", "pageup": "pagedown",
                 "down": "up", "up": "down"}


def reverse_page_turn_key(key):
    """巻き戻しに使う逆方向キー。未知キーは従来動作の "left" に落とす。"""
    return _REVERSE_KEYS.get(key, "left")


@dataclass
class CaptureProfile:
    """キャプチャ設定のプロファイル"""
    name: str = ""
    # GUI に出す日本語表示名。空なら name (さらに空ならキー) にフォールバックする。
    # 既存の name は CLI 出力・manifest の互換のため残す。
    display_name: str = ""
    # 実機検証済みマーク (GUI が「動作確認済み」バッジを出す)
    verified: bool = False
    # True のとき window_title_keyword は「本のタイトルの一部」を意味する
    # (ウィンドウタイトルに書名しか入らないビューア用。本ごとに入力が要る)
    title_keyword_is_book_title: bool = False
    window_title_keyword: str = ""
    page_turn_key: str = "right"
    fullscreen_wait: float = 5.0
    page_wait: float = 0.5
    boundary_method: str = "full"  # "full"(全画面・既定) | "manual"(手動クロップ)
    # 手動境界 (boundary_method="manual" のときに使用)。ウィンドウ相対の左右ピクセル座標。
    # 注: 旧設定に残る l_margin/r_margin (廃止済み) は from_dict が無視する。
    manual_left: int = 0
    manual_right: int = 0
    click_position: str = "center"  # "center" | "top_left"
    use_bring_to_top: bool = False
    process_name: str = ""  # プロセス名フィルタ (例: "Kindle.exe"、空欄なら無効)
    timeout_seconds: float = 5.0
    max_retries: int = 3
    # 静止待ちキャプチャ: ページ画像のロードに時間がかかりロード中の
    # スピナー画面を撮ってしまうビューア (Kindle Cloud Reader 等) 向け。
    # 有効時は「前ページから変化し、かつ連続 settle_frames フレーム静止した」
    # フレームだけを保存する (スピナーは回転し続けるので静止せず除外される)。
    settle_enabled: bool = False
    settle_frames: int = 2          # 連続でこの回数静止したらロード完了とみなす
    # しきい値は「変化ピクセル率(%)」。実測: 静止画同士≈0%、スピナー回転≈0.001-0.007%、
    # 本物のページ遷移≧0.58%。静止は0.0005%未満、変化は0.1%超で判定。
    settle_threshold: float = 0.0005        # これ未満なら静止とみなす
    settle_change_threshold: float = 0.1    # これ超で前ページから変化したとみなす
    settle_load_timeout: float = 20.0  # 変化後、静止しないまま待てる上限秒 (ロード失敗の保険)

    def to_dict(self):
        return asdict(self)

    def display_label(self, profile_key=""):
        """GUI 表示用の名前。display_name → name → キー の順にフォールバックする。"""
        return self.display_name or self.name or profile_key

    @classmethod
    def from_dict(cls, data):
        # 未知のキーを無視して安全にインスタンス化
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# ビルトインプロファイル
BUILTIN_PROFILES = {
    "kindle": CaptureProfile(
        name="Kindle for PC",
        display_name="Kindle（PCアプリ）",
        verified=True,  # 2026-08-27 ユーザー実機確認
        window_title_keyword="kindle",
        page_wait=0.15,
        boundary_method="full",
        click_position="top_left",
        process_name="Kindle.exe",
    ),
    # Kindle Cloud Reader (https://read.amazon.co.jp/?asin=<ASIN> で本を開き、
    # F11 でブラウザ全画面にしてから使う。2026-07-02 に Chrome で動作検証済み)
    "kindle_cloud": CaptureProfile(
        name="Kindle Cloud Reader (Chrome)",
        display_name="Kindle Cloud Reader（ブラウザ）",
        verified=True,
        window_title_keyword="Kindle",
        page_turn_key="left",  # 縦書き(右綴じ)本の次ページは←。横書き本は right に変更
        page_wait=0.3,
        boundary_method="full",
        # クリックするとリーダーUIがトグル表示されてキャプチャに写り込むため、
        # クリックなしで前面化する (キー入力は前面化だけで届く)
        click_position="none",
        process_name="chrome.exe",
        timeout_seconds=6.0,
        # マンガ等の重い画像はページ遷移中にロード中(スピナー)画面が写るため、
        # 画面が静止してから保存する。2026-07-04 に実データで確認して導入。
        settle_enabled=True,
    ),
    # --- ブラウザ版 (2026-08-16 実機検証済み。kindle_cloud 雛形のまま
    #     window_title_keyword と page_turn_key だけがサイトごとに異なる) ---
    "kobo_web": CaptureProfile(
        name="楽天Kobo ブラウザ版 (Chrome)",
        display_name="楽天Kobo（ブラウザ）",
        verified=True,
        window_title_keyword="Kobo Reader",
        page_turn_key="left",
        page_wait=0.3,
        boundary_method="full",
        click_position="none",
        process_name="chrome.exe",
        timeout_seconds=6.0,
        settle_enabled=True,
    ),
    "google_play_web": CaptureProfile(
        name="Google Play ブックス ブラウザ版 (Chrome)",
        display_name="Google Play ブックス（ブラウザ）",
        verified=True,
        window_title_keyword="Google Play ブックス",
        page_turn_key="right",
        page_wait=0.3,
        boundary_method="full",
        click_position="none",
        process_name="chrome.exe",
        timeout_seconds=6.0,
        settle_enabled=True,
    ),
    # DMM のブラウザビューアはウィンドウタイトルに書名しか入らないため、
    # window_title_keyword は本ごとに入力する (既定値を持たせない)
    "dmm_web": CaptureProfile(
        name="DMMブックス ブラウザ版 (Chrome)",
        display_name="DMMブックス（ブラウザ）",
        verified=True,
        title_keyword_is_book_title=True,
        window_title_keyword="",
        page_turn_key="left",
        page_wait=0.3,
        boundary_method="full",
        click_position="none",
        process_name="chrome.exe",
        timeout_seconds=6.0,
        settle_enabled=True,
    ),
    "cmoa_web": CaptureProfile(
        name="コミックシーモア ブラウザ版 (Chrome)",
        display_name="コミックシーモア（ブラウザ）",
        verified=True,
        window_title_keyword="シーモア",
        page_turn_key="left",
        page_wait=0.3,
        boundary_method="full",
        click_position="none",
        process_name="chrome.exe",
        timeout_seconds=6.0,
        settle_enabled=True,
    ),
}

# GUI のサイト選択に出す表示順 (画面仕様書 §6-1)。
# ブラウザ版 → PC アプリ版 (Kindle) の順。カスタムは末尾に付く。
PROFILE_DISPLAY_ORDER = (
    "kindle_cloud",
    "kobo_web",
    "google_play_web",
    "dmm_web",
    "cmoa_web",
    "kindle",
)


def merge_profile_data(profile_key, config=None, overrides=None):
    """ビルトイン → config 保存値 → overrides の順で重ねたプロファイル dict を返す。

    GUI がフォーム入力からプロファイルを組み立てるときに使う。フィールドを
    列挙して個別にコピーしない (dict を重ねる) ため、CaptureProfile に
    フィールドが増えても (settle_* 等) ここから脱落しない。

    Args:
        profile_key: プロファイルキー
        config: 設定 dict (capture.profiles.<key> を上書きとして使用)
        overrides: 呼び出し側の上書き dict。値が None の項目は無視する
    """
    base = BUILTIN_PROFILES.get(profile_key, CaptureProfile())
    data = base.to_dict()
    saved = _saved_profile_data(profile_key, config)
    if saved:
        data.update(saved)
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})
    if not data.get("name"):
        data["name"] = profile_key
    return data


def _saved_profile_data(profile_key, config):
    """config に保存されたプロファイル値を返す (無ければ None)。"""
    if config and "capture" in config and "profiles" in config["capture"]:
        return config["capture"]["profiles"].get(profile_key)
    return None


def get_profile(profile_key, config=None):
    """プロファイルキーからプロファイルを取得する。

    CLI・GUI とも同じ優先順位（ビルトイン → config 保存値の差分上書き）で
    解決する (画面仕様書 §6-2)。config はビルトインへの差分として効く。
    ビルトインに無いキーは config のカスタムプロファイルから取得する。
    呼び出し側が page_turn_key 等を書き換えても BUILTIN_PROFILES が
    汚染されないよう、常に独立したインスタンスを返す。
    """
    if profile_key not in BUILTIN_PROFILES and not _saved_profile_data(
        profile_key, config
    ):
        return None
    return CaptureProfile.from_dict(merge_profile_data(profile_key, config))


def get_all_profile_keys(config=None):
    """利用可能なすべてのプロファイルキーを返す。"""
    keys = list(BUILTIN_PROFILES.keys())
    if config and "capture" in config and "profiles" in config["capture"]:
        for key in config["capture"]["profiles"]:
            if key not in keys:
                keys.append(key)
    return keys


def profile_display_order(config=None):
    """GUI 表示順に並べたプロファイルキーの一覧を返す（画面仕様書 §6-1）。

    PROFILE_DISPLAY_ORDER の順にビルトインを並べ、そこに載っていない
    ビルトイン（将来追加分）と config のカスタムキーを末尾に付ける。
    """
    keys = [k for k in PROFILE_DISPLAY_ORDER if k in BUILTIN_PROFILES]
    for key in get_all_profile_keys(config):
        if key not in keys:
            keys.append(key)
    return keys
