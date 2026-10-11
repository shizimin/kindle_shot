"""S4 完了（画面仕様書 §3 S4）

出力先を表示し、戻り導線（余白からやり直す / 別の形式でもう一度書き出す /
次の本へ）を出す。
"""

import os
from tkinter import messagebox

import customtkinter as ctk

from ui import theme
from ui.wizard import STEP_CONVERT, STEP_HOME, STEP_TRIM, WizardStep


class DoneStep(WizardStep):
    heading = "書き出しが完了しました"

    def build(self):
        self.path_label = ctk.CTkLabel(
            self, text="", anchor="w", justify="left", wraplength=860,
        )
        self.path_label.pack(fill="x", padx=theme.PAD_X, pady=(0, theme.PAD_SMALL))

        self.stats_label = ctk.CTkLabel(
            self, text="", text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=860,
        )
        self.stats_label.pack(fill="x", padx=theme.PAD_X)

    def build_footer(self):
        self.add_left_button("終了", self.app.close_app)
        self.add_action_button("出力フォルダを開く", self._open_folder, width=170)
        self.add_action_button(
            "別の形式でもう一度書き出す", lambda: self.goto(STEP_CONVERT),
            primary=False, width=210)
        self.add_action_button(
            "余白からやり直す", lambda: self.goto(STEP_TRIM),
            primary=False, width=160)
        self.add_action_button(
            "次の本へ", lambda: self.goto(STEP_HOME), primary=False, width=120)

    def on_enter(self):
        path = self.wizard.output_path or self.wizard.output_folder
        self.path_label.configure(text=f"出力先: {path}" if path else "出力先: 不明")
        self.stats_label.configure(text=self.wizard.stats_human or "")

    def _open_folder(self):
        folder = self.wizard.output_folder
        if self.wizard.output_path:
            folder = os.path.dirname(self.wizard.output_path) or folder
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("エラー", f"出力フォルダが見つかりません:\n{folder}")
            return
        try:
            os.startfile(folder)  # noqa: SIM115 (Windows のエクスプローラで開く)
        except OSError as e:
            messagebox.showerror("エラー", f"フォルダを開けません: {e}")
