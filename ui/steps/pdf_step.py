"""S1b PDF選択（画面仕様書 §3 S1b）

選ぶのは PDF ファイルだけ。DPI=200・PNG 固定なので設定項目は出さない。
展開先は PDF と同じ階層の `<名前>_pages`（自動設定・表示のみ）。
"""

import os
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core.pdf_extractor import extract_pdf_to_images
from ui import theme
from ui.tab_utils import make_progress_cb, run_in_thread
from ui.widgets import ProgressPanel
from ui.wizard import STEP_HOME, STEP_TRIM, WizardStep

# 画面仕様書 §3 S1b で固定（選択 UI は置かない）
EXTRACT_DPI = 200
EXTRACT_FORMAT = "png"


class PdfStep(WizardStep):
    heading = "手持ちのPDFを取り込む"
    description = (
        "選んだPDFを1ページずつ画像に展開します（200dpi・PNG）。"
        "展開が終わると、そのまま余白調整に進みます。"
    )

    def build(self):
        self._running = False

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=theme.PAD_X)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="PDFファイル:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.pdf_var = tk.StringVar()
        ctk.CTkEntry(form, textvariable=self.pdf_var).grid(
            row=0, column=1, sticky="ew", pady=6)
        ctk.CTkButton(
            form, text="参照", width=120, command=self._browse_pdf,
        ).grid(row=0, column=2, padx=(theme.PAD_SMALL, 0), pady=6)

        ctk.CTkLabel(form, text="展開先:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=(0, theme.PAD_SMALL), pady=6)
        self.output_var = tk.StringVar()
        ctk.CTkLabel(
            form, textvariable=self.output_var, text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=680,
        ).grid(row=1, column=1, columnspan=2, sticky="w", pady=6)

        self.progress = ProgressPanel(self)
        self.progress.pack(fill="both", expand=True,
                           padx=theme.PAD_X, pady=theme.PAD_Y)

    def build_footer(self):
        self.back_btn = self.add_back_button(STEP_HOME)
        self.load_btn = self.add_action_button("読み込む", self._run_extract)

    def on_enter(self):
        self.wizard.source = "pdf"

    def on_reset(self):
        self.pdf_var.set("")
        self.output_var.set("")
        self.progress.reset()

    def _browse_pdf(self):
        path = filedialog.askopenfilename(
            title="PDFファイルを選択",
            filetypes=[("PDF", "*.pdf"), ("すべて", "*.*")],
        )
        if not path:
            return
        self.pdf_var.set(path)
        # 展開先は PDF と同階層の <名前>_pages（現行踏襲・自動設定）
        base_dir = os.path.dirname(path)
        stem = os.path.splitext(os.path.basename(path))[0]
        self.output_var.set(os.path.join(base_dir, f"{stem}_pages"))

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        self.load_btn.configure(state=state)
        self.back_btn.configure(state=state)

    def _run_extract(self):
        pdf_path = self.pdf_var.get().strip()
        if not pdf_path:
            messagebox.showerror("エラー", "PDFファイルを選んでください。")
            return
        output_folder = self.output_var.get().strip()
        if not output_folder:
            messagebox.showerror("エラー", "展開先を決められませんでした。")
            return

        self._set_running(True)
        self.progress.reset("展開中...")
        self.progress.log(f"PDF: {pdf_path}")
        self.progress.log(f"展開先: {output_folder}")

        root = self.winfo_toplevel()
        on_progress = make_progress_cb(
            root, self.progress.progress_bar, self.progress.status_var,
            fmt="展開中 {current}/{total}",
        )

        def thread():
            try:
                success, message = extract_pdf_to_images(
                    pdf_path, output_folder, dpi=EXTRACT_DPI,
                    image_format=EXTRACT_FORMAT, on_progress=on_progress,
                )
            except Exception as e:
                success, message = False, str(e)
            root.after(0, lambda: self._on_done(
                success, message, pdf_path, output_folder))

        run_in_thread(thread)

    def _on_done(self, success, message, pdf_path, output_folder):
        self._set_running(False)
        if not success:
            self.progress.status_var.set("エラー")
            self.progress.log(f"エラー: {message}")
            messagebox.showerror("エラー", message)
            return

        self.progress.status_var.set("展開完了")
        self.progress.log(f"展開完了: {message}")
        self.wizard.source = "pdf"
        self.wizard.title = os.path.splitext(os.path.basename(pdf_path))[0]
        self.wizard.save_folder = os.path.dirname(pdf_path)
        self.wizard.image_folder = output_folder
        self.goto(STEP_TRIM)
