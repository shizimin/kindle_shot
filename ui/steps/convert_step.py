"""S3 書き出す（画面仕様書 §3 S3）

出力形式は3択（画像PDF / 検索できるPDF / Markdown）。OCR 前処理・置換辞書・
章しおり・Markdown 詳細は表示せず、config の既定値のまま動かす。
"""

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from core import ocr_engine
from core.pipeline import EXIT_OK, run_convert
from ui import theme
from ui.tab_utils import GuiEmitter, browse_folder_into, run_in_thread
from ui.widgets import ProgressPanel
from ui.wizard import STEP_DONE, STEP_TRIM, WizardStep

# core の phase 名を進捗表示の日本語ラベルへ読み替える（GuiEmitter に渡す）
CONVERT_PHASE_LABELS = {
    "ocr": "文字認識中",
    "pdf": "PDFを作成中",
}

# (値, ラベル, 説明, OCR が要るか)
FORMAT_CHOICES = (
    ("image_pdf", "画像PDF", "ページをそのままPDFに。いちばん速い", False),
    ("searchable_pdf", "検索できるPDF",
     "文字認識（OCR）で検索・コピーできるPDFに。時間がかかります", True),
    ("markdown", "Markdown", "NotebookLM などのAIに読ませるテキストに", True),
)

# 出力先の説明（キャプチャの保存先＝作業用フォルダとは別物であることを示す）
OUTPUT_FOLDER_HELP = "書き出したファイルの保存先を選んでください。"


class ConvertStep(WizardStep):
    heading = "書き出す"
    description = "取り込んだページをどの形式で保存するか選びます。"

    def build(self):
        self._running = False
        self._applied_title = None

        self.format_var = tk.StringVar(value="image_pdf")
        self._format_buttons = {}

        formats = ctk.CTkFrame(self, fg_color="transparent")
        formats.pack(fill="x", padx=theme.PAD_X)
        for value, label, description, _needs_ocr in FORMAT_CHOICES:
            block = ctk.CTkFrame(formats, fg_color="transparent")
            block.pack(fill="x", pady=(0, theme.PAD_SMALL))
            radio = ctk.CTkRadioButton(
                block, text=label, variable=self.format_var, value=value,
                font=ctk.CTkFont(size=theme.FONT_SIZE_BASE, weight="bold"),
            )
            radio.pack(anchor="w")
            ctk.CTkLabel(
                block, text=description, text_color=theme.MUTED_COLOR,
                anchor="w", justify="left", wraplength=820,
            ).pack(anchor="w", padx=(26, 0))
            self._format_buttons[value] = radio

        self.ocr_note = ctk.CTkLabel(
            self, text="", anchor="w", justify="left", wraplength=860,
        )
        self.ocr_note.pack(fill="x", padx=theme.PAD_X, pady=(0, theme.PAD_Y))

        # --- 出力先 ---
        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=theme.PAD_X)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="ファイル名:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.filename_var = tk.StringVar()
        ctk.CTkEntry(form, textvariable=self.filename_var).grid(
            row=0, column=1, sticky="ew", pady=6)

        ctk.CTkLabel(form, text="出力先フォルダ:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.output_var = tk.StringVar()
        ctk.CTkEntry(form, textvariable=self.output_var).grid(
            row=1, column=1, sticky="ew", pady=6)
        ctk.CTkButton(
            form, text="参照", width=120,
            command=lambda: browse_folder_into(self.output_var),
        ).grid(row=1, column=2, padx=(theme.PAD_SMALL, 0), pady=6)

        ctk.CTkLabel(
            form, text=OUTPUT_FOLDER_HELP, text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=820,
        ).grid(row=2, column=1, columnspan=2, sticky="w", pady=(0, 6))

        self.progress = ProgressPanel(self)
        self.progress.pack(fill="both", expand=True,
                           padx=theme.PAD_X, pady=theme.PAD_Y)

    def build_footer(self):
        self.back_btn = self.add_back_button(STEP_TRIM)
        self.run_btn = self.add_action_button("書き出す", self._run_convert)

    # --- 進入時 ---

    def on_enter(self):
        self._refresh_ocr_state()
        # 出力先の初期値は前回の書き出し先。初回は空にして自分で選んでもらう
        # （キャプチャの保存先は作業用フォルダなので既定にしない）
        last_output = self.config_data.get("gui", {}).get("last_output_folder", "")
        # 本が変わったらファイル名・出力先を初期値に戻す
        if self._applied_title != self.wizard.title:
            self._applied_title = self.wizard.title
            self.filename_var.set(self.wizard.title)
            self.output_var.set(last_output)
        if not self.filename_var.get():
            self.filename_var.set(self.wizard.title)
        if not self.output_var.get():
            self.output_var.set(last_output)

    def on_reset(self):
        self._applied_title = None
        self.filename_var.set("")
        self.output_var.set("")
        self.progress.reset()

    def _refresh_ocr_state(self):
        """NDLOCR-Lite が無ければ OCR 系2択を無効化して案内を出す。"""
        engines = ocr_engine.get_available_engines()
        engine = engines[0] if engines else None
        available = bool(engine and engine.get("available"))
        for value, _label, _desc, needs_ocr in FORMAT_CHOICES:
            if needs_ocr:
                self._format_buttons[value].configure(
                    state="normal" if available else "disabled")
        if available:
            self.ocr_note.configure(
                text=f"OCRエンジン: {engine.get('description', 'NDLOCR-Lite')}",
                text_color=theme.MUTED_COLOR,
            )
        else:
            self.ocr_note.configure(
                text="NDLOCR-Lite が見つからないため、文字認識が必要な2つは選べません"
                     "（導入方法は README を参照してください）。",
                text_color=theme.ERROR_COLOR,
            )
            if self.format_var.get() != "image_pdf":
                self.format_var.set("image_pdf")

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.run_btn.configure(state=state)
        self.back_btn.configure(state=state)

    # --- 実行 ---

    def _run_convert(self):
        input_folder = self.wizard.work_folder or self.wizard.image_folder
        filename = self.filename_var.get().strip()
        output_folder = self.output_var.get().strip()
        fmt = self.format_var.get()

        if not input_folder:
            messagebox.showerror("エラー", "取り込んだ画像がありません。")
            return
        if not filename:
            messagebox.showerror("エラー", "ファイル名を入力してください。")
            return
        if not output_folder:
            messagebox.showerror("エラー", "出力先フォルダを選んでください。")
            return

        self._set_running(True)
        self.progress.reset("書き出しを開始します...")

        root = self.winfo_toplevel()
        emitter = GuiEmitter(root, log=self.progress.log_text,
                             progress_bar=self.progress.progress_bar,
                             status_var=self.progress.status_var,
                             phase_labels=CONVERT_PHASE_LABELS)

        def thread():
            # OCR 前処理・置換辞書・章しおり・Markdown 形式は config の
            # 既定値で動かす（GUI からは触らせない・画面仕様書 §3 S3）。
            try:
                code = run_convert(
                    input_folder, output_folder, fmt,
                    name=filename, config=self.config_data, emit=emitter,
                )
            except Exception as e:
                emitter("error", human=f"エラー: {e}", message=str(e))
                code = -1
            root.after(0, lambda: self._on_done(code, fmt, output_folder, emitter))

        run_in_thread(thread)

    def _on_done(self, code, fmt, output_folder, emitter):
        self._set_running(False)
        message = emitter.final_message
        if code != EXIT_OK:
            self.progress.status_var.set("エラー")
            messagebox.showerror("エラー", message or "書き出しに失敗しました。")
            return

        self.progress.status_var.set("書き出し完了")
        # 次回の初期値として書き出し先を覚える
        # （実際の書き込みはウィンドウを閉じるときの save_config）
        self.config_data.setdefault("gui", {})["last_output_folder"] = output_folder
        self.wizard.output_format = fmt
        self.wizard.output_folder = output_folder
        self.wizard.output_path = emitter.result_fields.get("output") or ""
        self.wizard.stats_human = emitter.stats_human or ""
        self.goto(STEP_DONE)
