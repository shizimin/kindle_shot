"""S1a キャプチャ設定（画面仕様書 §3 S1a）

入力は最大5項目（サイト / 本のタイトルの一部 / 保存する本のタイトル /
保存先フォルダ / ページ送り）。待機時間・プロセス名・取り込み範囲などの
生の設定は表示せず、プロファイルの値をそのまま使う。
"""

import os
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core.capture_runner import run_capture
from core.image_files import list_images
from core.page_turn_probe import probe_page_turn_key
from core.pipeline import EXIT_OK
from core.win32_utils import sanitize_folder_name
from ui import theme
from ui.profile_choices import build_profile_choices, resolve_profile
from ui.tab_utils import GuiEmitter, browse_folder_into, run_in_thread
from ui.widgets import ProgressPanel
from ui.wizard import STEP_HOME, STEP_TRIM, WizardStep

# ページ送りキーのドロップダウン（説明付きラベル）。
# 並びは自動判定の試行順（core.page_turn_probe.PROBE_KEY_ORDER）に合わせる。
PAGE_TURN_CHOICES = (
    ("left", "← 左（漫画・小説）"),
    ("right", "→ 右（横書きの本）"),
    ("pagedown", "PageDown（スクロール型のビューア）"),
    ("pageup", "PageUp"),
    ("up", "↑ 上"),
    ("down", "↓ 下"),
)
_LABEL_BY_KEY = dict(PAGE_TURN_CHOICES)
_KEY_BY_LABEL = {label: key for key, label in PAGE_TURN_CHOICES}

# 開始前の手順（画面内に常時表示する）
START_GUIDE = (
    "1. 本をビューアで開いて先頭ページを表示する\n"
    "2. 「キャプチャ開始」を押すとビューアが前面に出ます\n"
    "3. 待機中（数秒）に F11 で全画面にする（すでに全画面ならそのまま待つ）\n"
    "4. 待機が終わるとキャプチャが始まります"
    "（終わるまでビューアの画面を操作しないでください）"
)

# 自動判定の注意
PROBE_NOTE = (
    "「自動で調べる」は本の先頭ページを開いた状態で実行してください。"
    "候補のキーで数ページめくって試し、終わったら自動で先頭ページへ戻します。"
    "戻せなかった場合は手動で先頭ページに戻してください。"
)

# 保存先フォルダの説明（この画面の保存先は作業用フォルダで、成果物の置き場ではない）
SAVE_FOLDER_HELP = (
    "この中に「タイトル」名のフォルダを作って画像を保存します。"
    "作業用フォルダのため、書き出した PDF の保存先は最後の画面で選べます。"
)


def default_save_folder():
    """保存先フォルダの初期値（前回値が無いときに使う）。"""
    return os.path.join(os.path.expanduser("~"), "Documents", "kindle_shot")


# プロファイル固有の注意（キー → 追加表示する文言）
PROFILE_NOTES = {
    "google_play_web": (
        "リーダーのヘッダーなどが一緒に写りますが、次の「余白を整える」で消せます。"
    ),
}


class CaptureStep(WizardStep):
    heading = "キャプチャ設定"
    description = "本を開いているビューアを選んで、保存先とページ送りを決めます。"

    def build(self):
        self._running = False
        self._stop_event = None
        self._choices = []
        self._countdown_job = None
        self._countdown_left = 0

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=theme.PAD_X)
        form.grid_columnconfigure(1, weight=1)

        # 1. サイト
        ctk.CTkLabel(form, text="サイト:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.profile_label_var = tk.StringVar()
        self.profile_combo = ctk.CTkComboBox(
            form, variable=self.profile_label_var, values=[""],
            state="readonly", command=self._on_profile_changed,
        )
        self.profile_combo.grid(row=0, column=1, columnspan=2, sticky="ew", pady=6)

        # 2. 本のタイトルの一部（書名依存プロファイルのときだけ表示）
        self.keyword_label = ctk.CTkLabel(form, text="本のタイトルの一部:", anchor="w")
        self.keyword_var = tk.StringVar()
        self.keyword_entry = ctk.CTkEntry(
            form, textvariable=self.keyword_var,
            placeholder_text="ビューアのウィンドウ名に出ている書名の一部",
        )
        self.keyword_hint = ctk.CTkLabel(
            form,
            text="このビューアは本ごとにウィンドウ名が変わるため、対象の本を特定する言葉が要ります。",
            text_color=theme.MUTED_COLOR, anchor="w", justify="left", wraplength=820,
        )
        self._keyword_widgets = (
            (self.keyword_label, {"row": 1, "column": 0, "sticky": "w",
                                  "padx": (0, theme.PAD_SMALL), "pady": 6}),
            (self.keyword_entry, {"row": 1, "column": 1, "columnspan": 2,
                                  "sticky": "ew", "pady": 6}),
            (self.keyword_hint, {"row": 2, "column": 1, "columnspan": 2,
                                 "sticky": "w", "pady": (0, 6)}),
        )

        # 3. 保存する本のタイトル
        ctk.CTkLabel(form, text="保存する本のタイトル:", anchor="w").grid(
            row=3, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.title_var = tk.StringVar()
        ctk.CTkEntry(form, textvariable=self.title_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", pady=6)

        # 4. 保存先フォルダ
        ctk.CTkLabel(form, text="保存先フォルダ:", anchor="w").grid(
            row=4, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.folder_var = tk.StringVar()
        ctk.CTkEntry(form, textvariable=self.folder_var).grid(
            row=4, column=1, sticky="ew", pady=6)
        ctk.CTkButton(
            form, text="参照", width=170,
            command=lambda: browse_folder_into(self.folder_var),
        ).grid(row=4, column=2, padx=(theme.PAD_SMALL, 0), pady=6)

        ctk.CTkLabel(
            form, text=SAVE_FOLDER_HELP, text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=820,
        ).grid(row=5, column=1, columnspan=2, sticky="w", pady=(0, 6))

        # 5. ページ送り
        ctk.CTkLabel(form, text="ページ送り:", anchor="w").grid(
            row=6, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.page_turn_label_var = tk.StringVar(value=_LABEL_BY_KEY["right"])
        self.page_turn_combo = ctk.CTkComboBox(
            form, variable=self.page_turn_label_var,
            values=[label for _, label in PAGE_TURN_CHOICES], state="readonly",
        )
        self.page_turn_combo.grid(row=6, column=1, sticky="ew", pady=6)
        self.probe_btn = ctk.CTkButton(
            form, text="自動で調べる", width=170, command=self._start_probe,
        )
        self.probe_btn.grid(row=6, column=2, padx=(theme.PAD_SMALL, 0), pady=6)

        ctk.CTkLabel(
            form, text=PROBE_NOTE, text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=820,
        ).grid(row=7, column=1, columnspan=2, sticky="w", pady=(0, 6))

        # 開始前ガイダンス（実行中は隠してログ欄に高さを譲る。_set_running 参照）
        self.guide = guide = ctk.CTkFrame(self, corner_radius=theme.CORNER_RADIUS)
        self._guide_pack = dict(fill="x", padx=theme.PAD_X, pady=(theme.PAD_Y, 0))
        guide.pack(**self._guide_pack)
        ctk.CTkLabel(
            guide, text=START_GUIDE, anchor="w", justify="left", wraplength=840,
        ).pack(fill="x", padx=theme.PAD_X, pady=(theme.PAD_SMALL, 2))
        self.profile_note = ctk.CTkLabel(
            guide, text="", text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=840,
        )
        self.profile_note.pack(fill="x", padx=theme.PAD_X, pady=(0, theme.PAD_SMALL))

        # 進捗・ログ
        self.progress = ProgressPanel(self)
        self.progress.pack(fill="both", expand=True,
                           padx=theme.PAD_X, pady=theme.PAD_Y)

    def build_footer(self):
        self.back_btn = self.add_back_button(STEP_HOME)
        self.start_btn = self.add_action_button("キャプチャ開始", self._start_capture)
        self.stop_btn = self.add_action_button(
            "停止", self._stop_capture, primary=False, width=110)
        self.stop_btn.configure(state="disabled")

    # --- 表示更新 ---

    def on_enter(self):
        self.wizard.source = "capture"
        self._refresh_profiles()
        if not self.folder_var.get():
            last = self.config_data.get("gui", {}).get("last_save_folder", "")
            self.folder_var.set(
                self.wizard.save_folder or last or default_save_folder())

    def on_reset(self):
        # 保存先フォルダは覚えておき、本ごとに変わる値だけ消す
        self.title_var.set("")
        self.keyword_var.set("")
        self.progress.reset()

    def _refresh_profiles(self):
        """サイト一覧を作り直す（config のカスタムプロファイル追加に追従）。"""
        selected = self._selected_key()
        self._choices = build_profile_choices(self.config_data)
        labels = [label for _key, label in self._choices]
        self.profile_combo.configure(values=labels)
        if not labels:
            return
        keys = [key for key, _label in self._choices]
        if selected not in keys:
            selected = self.config_data.get("capture", {}).get(
                "active_profile", keys[0])
            if selected not in keys:
                selected = keys[0]
        self.profile_label_var.set(labels[keys.index(selected)])
        self._on_profile_changed()

    def _selected_key(self):
        label = self.profile_label_var.get()
        for key, choice_label in self._choices:
            if choice_label == label:
                return key
        return None

    def _on_profile_changed(self, _value=None):
        key = self._selected_key()
        if key is None:
            return
        profile = resolve_profile(key, self.config_data)
        self._set_page_turn(profile.page_turn_key)
        self.profile_note.configure(text=PROFILE_NOTES.get(key, ""))

        # 書名依存プロファイルのときだけ「本のタイトルの一部」を出す
        if profile.title_keyword_is_book_title:
            for widget, opts in self._keyword_widgets:
                widget.grid(**opts)
        else:
            for widget, _opts in self._keyword_widgets:
                widget.grid_remove()

    def _set_page_turn(self, key):
        self.page_turn_label_var.set(_LABEL_BY_KEY.get(key, key))

    def _page_turn_key(self):
        label = self.page_turn_label_var.get()
        return _KEY_BY_LABEL.get(label, label)

    # --- プロファイル組み立て・入力検証 ---

    def _build_profile(self):
        """選択中のサイトと画面の入力から (キー, CaptureProfile) を作る。

        上書きするのはページ送りキーと（書名依存のときだけ）ウィンドウ名の
        キーワードのみ。待機時間などはプロファイルの値をそのまま使う。
        """
        key = self._selected_key()
        if key is None:
            messagebox.showerror("エラー", "サイトを選択してください。")
            return None, None
        overrides = {"page_turn_key": self._page_turn_key()}
        profile = resolve_profile(key, self.config_data)
        if profile.title_keyword_is_book_title:
            keyword = self.keyword_var.get().strip()
            if not keyword:
                messagebox.showerror(
                    "エラー",
                    "このビューアでは「本のタイトルの一部」の入力が必要です。\n"
                    "ビューアのウィンドウ名に出ている書名の一部を入力してください。",
                )
                return None, None
            overrides["window_title_keyword"] = keyword
        return key, resolve_profile(key, self.config_data, overrides)

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.start_btn.configure(state=state)
        self.probe_btn.configure(state=state)
        self.back_btn.configure(state=state)
        self.stop_btn.configure(state="normal" if running else "disabled")
        # 既定ウィンドウサイズではフォーム＋ガイドで高さを使い切り、ログ欄が
        # 数行（書名入力行が出るプロファイルでは1行未満）に潰れる。ガイドは
        # 開始前にしか要らないので、実行中は外してログ欄に高さを譲る。
        if running:
            self.guide.pack_forget()
        elif not self.guide.winfo_manager():
            self.guide.pack(before=self.progress, **self._guide_pack)

    # --- ページ送りキーの自動判定 ---

    def _start_probe(self):
        _key, profile = self._build_profile()
        if profile is None:
            return

        self._stop_event = threading.Event()
        self._set_running(True)
        self.progress.reset("ページ送りキーを調べています...")
        self.progress.start_indeterminate()
        self.progress.log("ページ送りキーの自動判定を開始します")

        root = self.winfo_toplevel()
        emitter = GuiEmitter(root, log=self.progress.log_text,
                             status_var=self.progress.status_var)

        def thread():
            try:
                found = probe_page_turn_key(
                    profile, stop_event=self._stop_event,
                    strict_process=False, emit=emitter,
                )
            except Exception as e:
                emitter("error", human=f"エラー: {e}", message=str(e))
                found = None
            root.after(0, lambda: self._on_probe_done(found, emitter))

        run_in_thread(thread)

    def _on_probe_done(self, found, emitter):
        self._set_running(False)
        self.progress.stop_indeterminate()
        if found:
            self._set_page_turn(found)
            self.progress.status_var.set(
                f"ページ送りキーを {_LABEL_BY_KEY.get(found, found)} に設定しました")
        else:
            self.progress.status_var.set("ページ送りキーを特定できませんでした")
            messagebox.showwarning(
                "自動判定",
                emitter.error_human
                or "ページ送りキーを特定できませんでした。手動で選んでください。",
            )

    # --- キャプチャ実行 ---

    def _start_capture(self):
        # タイトルは保存フォルダ名になるため、使えない文字 (\/:*?"<>| 等) を
        # 全角に置き換えてから使う（入力欄にも反映する）
        title = sanitize_folder_name(self.title_var.get())
        self.title_var.set(title)
        save_folder = self.folder_var.get().strip()
        if not title:
            messagebox.showerror("エラー", "保存する本のタイトルを入力してください。")
            return
        if not save_folder:
            messagebox.showerror("エラー", "保存先フォルダを選んでください。")
            return

        key, profile = self._build_profile()
        if profile is None:
            return

        # 初期値の %USERPROFILE%\Documents\kindle_shot は普通まだ存在しないので作る
        try:
            os.makedirs(save_folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror(
                "エラー", f"保存先フォルダを作成できません:\n{save_folder}\n{e}")
            return

        # 前回の残骸が混ざるのを防ぐため、既存画像がある場合は確認してから消す
        save_dir = os.path.join(save_folder, title)
        overwrite = False
        if os.path.isdir(save_dir):
            existing = list_images(save_dir)
            if existing:
                if not messagebox.askyesno(
                    "確認",
                    f"保存先に既存の画像が {len(existing)} 枚あります:\n{save_dir}\n\n"
                    "前回の残骸が混ざるのを防ぐため、削除してから開始しますか？",
                ):
                    return
                overwrite = True

        # 次回の初期値として保存先と、最後に使ったサイトを覚える
        # （実際の書き込みはウィンドウを閉じるときの save_config）
        self.config_data.setdefault("gui", {})["last_save_folder"] = save_folder
        self.config_data.setdefault("capture", {})["active_profile"] = key

        self._stop_event = threading.Event()
        self._set_running(True)
        self.progress.reset("キャプチャを開始します...")
        self.progress.start_indeterminate()
        self.progress.log("キャプチャを開始します")
        # core 側の待機（fullscreen_wait）中は無音になるので、残り秒数と
        # 「今のうちに F11」をここで表示する（core の emit と多少重複してよい）
        self._start_wait_countdown(profile.fullscreen_wait)

        root = self.winfo_toplevel()
        emitter = GuiEmitter(root, log=self.progress.log_text,
                             status_var=self.progress.status_var)

        def thread():
            # GUI は人間が画面を見ている前提なのでプロセス名照合は警告のみ
            # (strict_process=False)。manifest.json とスリープ抑止は CLI と共通。
            try:
                code = run_capture(
                    profile, title, save_folder,
                    profile_key=key, overwrite=overwrite,
                    stop_event=self._stop_event, strict_process=False,
                    emit=emitter,
                )
            except Exception as e:
                emitter("error", human=f"エラー: {e}", message=str(e))
                code = -1
            root.after(0, lambda: self._on_capture_done(code, title,
                                                        save_folder, emitter))

        run_in_thread(thread)

    # --- 全画面化の待機カウントダウン ---

    def _start_wait_countdown(self, seconds):
        self._cancel_wait_countdown()
        self._countdown_left = int(round(seconds))
        if self._countdown_left > 0:
            self._tick_wait_countdown()

    def _tick_wait_countdown(self):
        self._countdown_job = None
        if not self._running or self._countdown_left <= 0:
            return
        self.progress.status_var.set(
            f"{self._countdown_left}秒後にキャプチャを開始します — "
            "この間にビューアを F11 で全画面にしてください"
        )
        self._countdown_left -= 1
        self._countdown_job = self.after(1000, self._tick_wait_countdown)

    def _cancel_wait_countdown(self):
        if self._countdown_job is not None:
            self.after_cancel(self._countdown_job)
            self._countdown_job = None
        self._countdown_left = 0

    def _stop_capture(self):
        if self._stop_event is not None:
            self._stop_event.set()
        self._cancel_wait_countdown()
        self.progress.log("停止リクエストを送信しました...")

    def _on_capture_done(self, code, title, save_folder, emitter):
        self._cancel_wait_countdown()
        self._set_running(False)
        self.progress.stop_indeterminate()
        message = emitter.final_message
        if code != EXIT_OK:
            self.progress.status_var.set("エラー / 中断")
            messagebox.showerror("中断", message or "キャプチャを中断しました。")
            return

        self.progress.status_var.set("キャプチャ完了")
        self.wizard.source = "capture"
        self.wizard.title = title
        self.wizard.save_folder = save_folder
        self.wizard.image_folder = emitter.result_fields.get(
            "save_dir", os.path.join(save_folder, title))
        self.goto(STEP_TRIM)
