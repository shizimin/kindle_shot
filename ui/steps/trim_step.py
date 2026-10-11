"""S2 余白を整える（画面仕様書 §3 S2）

ステップに入った時点で全ページ走査の自動検出を自動実行する（ボタンを押させない）。
検出後は before/after プレビューを見ながら 4 辺の値を増やして寄せる。
"""

import os
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

from core.boundary_detector import detect_margins_folder, variation_applied
from core.image_files import list_images
from core.pipeline import EXIT_OK, relax_margins, run_trim
from core.trimmer import trim_margins
from ui import theme
from ui.tab_utils import GuiEmitter, make_progress_cb, run_in_thread
from ui.widgets import ProgressPanel, SpinBox
from ui.wizard import STEP_CONVERT, STEP_HOME, STEP_TRIM, WizardStep

# プレビュー領域の高さ。ボディがスクロールするので自動では広がらないため、
# ウィンドウの高さに追従して明示的に設定する（下限は PREVIEW_MIN_HEIGHT）。
PREVIEW_MIN_HEIGHT = 300
# ボディの余白・スクロール枠など、子ウィジェットの高さに現れない分の見込み
PREVIEW_LAYOUT_MARGIN = 40

MARGIN_HELP = (
    "切れないよう少し余裕を持たせた値が入っています。"
    "「トリミング前」に引いた赤い線が切り取り位置です。"
    "プレビューを見ながら数値を増やすと余白を詰められます。"
)

# core の phase 名を進捗表示の日本語ラベルへ読み替える（GuiEmitter に渡す）
TRIM_PHASE_LABELS = {
    "detect": "余白を検出中",
    "ui_bands": "ビューアのUI帯を確認中",
    "check": "全面表示のページを確認中",
    "trim": "トリミング中",
}

# スピンボックスの上限を画像サイズのこの割合にする。
# 片側でこれ以上削ると本文がほぼ残らないため、入力ミスの歯止めにする。
MAX_MARGIN_RATIO = 0.45

# 切り取り位置を示すガイド線（プレビューの「トリミング前」に重ねる）
GUIDE_COLOR = "#ff3b30"
GUIDE_WIDTH = 2


class TrimStep(WizardStep):
    heading = "余白を整える"
    description = "ページの余白を自動で調べています。値を調整してからトリミングします。"

    def build(self):
        self._detected_folder = None   # 自動検出済みのフォルダ（再入場時の再実行を防ぐ）
        self._running = False
        self._preview_files = []
        self._preview_index = 0
        self._original_pil = None
        self._trimmed_pil = None
        self._redraw_job = None

        # --- 余白の数値 ---
        margin_row = ctk.CTkFrame(self, fg_color="transparent")
        margin_row.pack(fill="x", padx=theme.PAD_X)

        self.spins = {}
        for name, label in (("left", "左"), ("right", "右"),
                            ("top", "上"), ("bottom", "下")):
            spin = SpinBox(margin_row, label=label, value=0,
                           command=self._schedule_preview_refresh)
            spin.pack(side="left", padx=(0, theme.PAD_X))
            self.spins[name] = spin

        self.redetect_btn = ctk.CTkButton(
            margin_row, text="再検出", width=100, command=self._start_detect,
        )
        self.redetect_btn.pack(side="left")

        ctk.CTkLabel(
            self, text=MARGIN_HELP, text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=860,
        ).pack(fill="x", padx=theme.PAD_X, pady=(4, 0))

        self.ui_band_label = ctk.CTkLabel(
            self, text="", text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=860,
        )
        self.ui_band_label.pack(fill="x", padx=theme.PAD_X)

        self.outlier_label = ctk.CTkLabel(
            self, text="", text_color=theme.MUTED_COLOR,
            anchor="w", justify="left", wraplength=860,
        )
        self.outlier_label.pack(fill="x", padx=theme.PAD_X)

        # --- 進捗 ---
        # プレビューより前に置く。プレビューは残りの高さをすべて使うので、
        # 進捗を後ろに置くと画面外へ押し出されて見えなくなる。
        self.progress = ProgressPanel(self, show_log=False)
        self.progress.pack(fill="x", padx=theme.PAD_X, pady=(theme.PAD_SMALL, 0))

        # --- プレビュー（before / after）---
        # 子は grid 配置なので、固定高さを効かせるのは grid_propagate(False)。
        # pack_propagate(False) では伝播が止まらず、フレームが内容サイズまで
        # 潰れて画像が極小になっていた。
        self.preview = preview = ctk.CTkFrame(self, height=PREVIEW_MIN_HEIGHT)
        preview.pack(fill="x", padx=theme.PAD_X, pady=theme.PAD_Y)
        preview.grid_propagate(False)
        preview.grid_rowconfigure(1, weight=1)
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(preview, text="トリミング前").grid(row=0, column=0, pady=(4, 0))
        ctk.CTkLabel(preview, text="トリミング後").grid(row=0, column=1, pady=(4, 0))

        # 画像表示は tk.Label のまま (ImageTk.PhotoImage との相性が良い)。
        # customtkinter のテーマに追従しないので背景色は自前で合わせる。
        bg = theme.frame_bg()
        # before/after は同じ倍率で描くので、after は枠内で中央寄せにする
        # （削れた分だけ小さく表示され、切り取り量が目で分かる）
        self.original_label = tk.Label(preview, bg=bg, bd=0, highlightthickness=0,
                                       anchor="center")
        self.original_label.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.trimmed_label = tk.Label(preview, bg=bg, bd=0, highlightthickness=0,
                                      anchor="center")
        self.trimmed_label.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)

        nav = ctk.CTkFrame(preview, fg_color="transparent")
        nav.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        nav.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(nav, text="◀ 前へ", width=90,
                      command=lambda: self._change_preview(-1)).grid(row=0, column=0)
        self.filename_label = ctk.CTkLabel(nav, text="", text_color=theme.MUTED_COLOR)
        self.filename_label.grid(row=0, column=1, sticky="ew")
        ctk.CTkButton(nav, text="次へ ▶", width=90,
                      command=lambda: self._change_preview(1)).grid(row=0, column=2)

        preview.bind("<Configure>", lambda _e: self._redraw_preview())

        # ウィンドウのリサイズにプレビューの高さを追従させる
        self._preview_height = PREVIEW_MIN_HEIGHT
        self.winfo_toplevel().bind(
            "<Configure>", lambda _e: self._update_preview_height(), add="+")

    def build_footer(self):
        # 行き先は on_enter で入力源のステップに差し替える
        self.back_btn = self.add_back_button(STEP_HOME)
        self.trim_btn = self.add_action_button(
            "この余白でトリミング", self._run_trim)
        self.skip_btn = self.add_action_button(
            "トリミングせずに進む", self._skip_trim, primary=False, width=180)

    # --- 進入時 ---

    def on_enter(self):
        # 「戻る」の行き先は入力源のステップ（キャプチャ or PDF）
        self.back_btn.configure(command=lambda: self.goto(self.wizard.source_step))
        self.after_idle(self._update_preview_height)
        folder = self.wizard.image_folder
        if not folder:
            self.progress.status_var.set("取り込んだ画像がありません")
            return
        if folder != self._detected_folder:
            self._reset_preview()
            self._start_detect()

    def on_reset(self):
        self._detected_folder = None
        self._reset_preview()
        self.progress.reset()

    # --- 自動検出 ---

    def _start_detect(self):
        folder = self.wizard.image_folder
        if not folder or not os.path.isdir(folder):
            messagebox.showerror("エラー", f"画像フォルダが見つかりません:\n{folder}")
            return

        self._set_running(True)
        self.progress.reset("余白を検出中...")

        root = self.winfo_toplevel()
        on_progress = make_progress_cb(
            root, self.progress.progress_bar, self.progress.status_var,
            fmt="余白を検出中 {current}/{total} ページ",
        )
        # UI 帯の走査は別フェーズなので、何を見ているか分かる文言にする
        on_variation_progress = make_progress_cb(
            root, self.progress.progress_bar, self.progress.status_var,
            fmt="ビューアのUI帯を確認中 {current}/{total} ページ",
        )

        def thread():
            try:
                margins, report = detect_margins_folder(
                    folder, on_progress=on_progress,
                    on_variation_progress=on_variation_progress)
            except Exception:
                margins, report = None, None
            root.after(0, lambda: self._on_detect_done(folder, margins, report))

        run_in_thread(thread)

    def _on_detect_done(self, folder, margins, report):
        self._set_running(False)
        if report is None:
            self.progress.status_var.set("検出失敗: エラーが発生しました")
            messagebox.showerror("エラー", "余白の検出中にエラーが発生しました。")
            return
        if report["pages_total"] == 0:
            self.progress.status_var.set("検出失敗: 画像ファイルがありません")
            messagebox.showerror("エラー", "画像ファイルが見つかりません。")
            return
        if margins is None:
            self.progress.status_var.set("検出失敗: 余白を検出できませんでした")
            messagebox.showerror("エラー", "余白を検出できませんでした。")
            return

        # 手入力の上限を画像サイズに合わせる（既定の 10000 は画像と無関係で、
        # 画像より大きい値を入れられてしまう）。値を入れる前に効かせる
        self._apply_spin_bounds(folder)

        # ユーザの「ギリギリを攻めず、そこから狭めていく」運用に合わせ、
        # 検出値より小さい値を入れて外側に余白を残す (CLI と同じ式・同じ既定値)。
        left, right, top, bottom = relax_margins(margins)
        for name, value in (("left", left), ("right", right),
                            ("top", top), ("bottom", bottom)):
            self.spins[name].set(value)

        self._detected_folder = folder
        self.progress.status_var.set(
            f"検出完了: 左={left}, 右={right}, 上={top}, 下={bottom}"
            f"（全 {report['pages_total']} ページを走査）"
        )

        self._show_ui_band_note(report, margins)

        outliers = report.get("outliers") or []
        if outliers:
            self.outlier_label.configure(
                text=f"全面表示のページ {len(outliers)} 件は、"
                     "余白を適用せず無加工のままコピーします。"
            )
        else:
            self.outlier_label.configure(text="")

        self._load_preview_files(folder)

    def _apply_spin_bounds(self, folder):
        """1 枚目の画像サイズからスピンボックスの上限を決める。

        画像が読めなければ従来どおり（既定の上限のまま）にする。
        """
        try:
            files = list_images(folder)
            with Image.open(os.path.join(folder, files[0])) as im:
                width, height = im.size
        except (OSError, IndexError, FileNotFoundError):
            return
        for name in ("left", "right"):
            self.spins[name].set_bounds(0, int(width * MAX_MARGIN_RATIO))
        for name in ("top", "bottom"):
            self.spins[name].set_bounds(0, int(height * MAX_MARGIN_RATIO))

    def _show_ui_band_note(self, report, combined_margins):
        """ページ間変化で UI 帯を削った辺があれば、その旨を出す。"""
        variation_report = report.get("variation") or {}
        if variation_report.get("reason") == "too_few_pages":
            self.ui_band_label.configure(
                text="ページ数が少ないため、ビューアのUI帯の自動検出は行っていません"
            )
            return
        content = report.get("content_margins")
        variation = report.get("variation_margins")
        if not content or not variation:
            self.ui_band_label.configure(text="")
            return
        labels = ("左", "右", "上", "下")
        applied = variation_applied(content, variation, combined_margins)
        removed = [f"{label}={v}px"
                   for label, v, is_applied in zip(labels, variation, applied,
                                                   strict=True)
                   if is_applied]
        if not removed:
            self.ui_band_label.configure(text="")
            return
        self.ui_band_label.configure(
            text="ページ間で絵が変わらない部分（ビューアのヘッダー・フッター等）を"
                 f"除いて余白を決めました（{', '.join(removed)}）。"
                 "ビューアの表示が残っている場合は、その辺の数値を増やしてください。"
        )

    def _set_running(self, running):
        self._running = running
        state = "disabled" if running else "normal"
        for btn in (self.trim_btn, self.skip_btn, self.back_btn, self.redetect_btn):
            btn.configure(state=state)

    # --- プレビュー ---

    def _update_preview_height(self):
        """ウィンドウの高さからプレビュー領域の高さを決める。

        ボディの見えている高さから、この画面の他のウィジェットが使う分を
        引いた残りをプレビューに割り当てる。

        小刻みな変動でレイアウトが振動しないよう、8px 単位に丸めたうえで
        差が 16px 以上のときだけ適用する（自分の configure が誘発する
        再レイアウト → 再計算のループを断つ）。
        """
        # トップレベルの <Configure> に add="+" で相乗りしているため、
        # ウィンドウ破棄中にも呼ばれる。破棄済みなら winfo_children() が
        # TclError (bad window path name) を投げるので先に抜ける
        if not self.winfo_exists():
            return
        # 構築中・他ステップ表示中は何もしない
        if getattr(self.app, "current_step_id", None) != STEP_TRIM:
            return
        body_height = self.app.body.winfo_height()
        if body_height <= 1:   # まだレイアウトが確定していない
            return
        used = sum(child.winfo_height() for child in self.winfo_children()
                   if child is not self.preview)
        height = max(PREVIEW_MIN_HEIGHT,
                     body_height - used - PREVIEW_LAYOUT_MARGIN)
        height -= height % 8
        if abs(height - self._preview_height) < 16:
            return
        self._preview_height = height
        self.preview.configure(height=height)

    def _reset_preview(self):
        self._preview_files = []
        self._preview_index = 0
        self._original_pil = None
        self._trimmed_pil = None
        for label in (self.original_label, self.trimmed_label):
            label.configure(image="")
            label.image = None
        self.filename_label.configure(text="")
        self.outlier_label.configure(text="")
        self.ui_band_label.configure(text="")

    def _load_preview_files(self, folder):
        try:
            self._preview_files = list_images(folder)
        except FileNotFoundError:
            self._preview_files = []
        self._preview_index = 0
        if self._preview_files:
            self._load_preview_image()

    def _margins(self):
        return tuple(self.spins[name].get()
                     for name in ("left", "right", "top", "bottom"))

    def _schedule_preview_refresh(self):
        """スピンボックスの連続操作でプレビューを作り直しすぎないよう間引く。"""
        if self._redraw_job is not None:
            self.after_cancel(self._redraw_job)
        self._redraw_job = self.after(250, self._load_preview_image)

    def _load_preview_image(self):
        self._redraw_job = None
        if not self._preview_files:
            return
        folder = self.wizard.image_folder
        filename = self._preview_files[self._preview_index]
        filepath = os.path.join(folder, filename)
        left, right, top, bottom = self._margins()
        try:
            with Image.open(filepath) as img:
                self._original_pil = img.copy()
                self._trimmed_pil = trim_margins(img, left, right, top, bottom)
        except OSError:
            self.filename_label.configure(text=f"画像を開けません: {filename}")
            return
        self.filename_label.configure(
            text=f"{filename}（{self._preview_index + 1}/{len(self._preview_files)}）")
        self._redraw_preview()

    def _draw_guides(self, img, scale):
        """トリミング位置を示す赤線を 4 辺に引いた複製を返す。

        縮小後の画像に描くので、倍率によらず線の太さは一定。元画像は変えない。
        """
        left, right, top, bottom = self._margins()
        w, h = img.size
        x0 = max(0, min(w - 1, round(left * scale)))
        x1 = max(0, min(w - 1, w - 1 - round(right * scale)))
        y0 = max(0, min(h - 1, round(top * scale)))
        y1 = max(0, min(h - 1, h - 1 - round(bottom * scale)))
        out = img.convert("RGB")
        draw = ImageDraw.Draw(out)
        for x in (x0, x1):
            draw.line([(x, 0), (x, h)], fill=GUIDE_COLOR, width=GUIDE_WIDTH)
        for y in (y0, y1):
            draw.line([(0, y), (w, y)], fill=GUIDE_COLOR, width=GUIDE_WIDTH)
        return out

    def _redraw_preview(self):
        if not self.winfo_exists():
            return
        if not self._original_pil or not self._trimmed_pil:
            return
        max_w = max(40, self.original_label.winfo_width() - 8)
        max_h = max(40, self.original_label.winfo_height() - 8)
        # before / after を**同じ倍率**で描く。それぞれ枠いっぱいに拡大縮小
        # (thumbnail) すると、いくら削っても見た目の大きさが変わらず、
        # 「余白を変えてもプレビューが変わらない」ように見えてしまう。
        orig_w, orig_h = self._original_pil.size
        scale = min(max_w / orig_w, max_h / orig_h, 1.0)
        for pil_img, label, guides in (
            (self._original_pil, self.original_label, True),
            (self._trimmed_pil, self.trimmed_label, False),
        ):
            size = (max(1, round(pil_img.width * scale)),
                    max(1, round(pil_img.height * scale)))
            img = pil_img.resize(size, Image.Resampling.LANCZOS)
            if guides:
                img = self._draw_guides(img, scale)
            photo = ImageTk.PhotoImage(img)
            label.configure(image=photo)
            label.image = photo

    def _change_preview(self, delta):
        if not self._preview_files:
            return
        new_index = self._preview_index + delta
        if 0 <= new_index < len(self._preview_files):
            self._preview_index = new_index
            self._load_preview_image()

    # --- 実行 ---

    def _skip_trim(self):
        """トリミングせず、原画像フォルダのまま書き出しへ進む。"""
        self.wizard.work_folder = self.wizard.image_folder
        self.goto(STEP_CONVERT)

    def _run_trim(self):
        input_folder = self.wizard.image_folder
        if not input_folder:
            messagebox.showerror("エラー", "取り込んだ画像がありません。")
            return
        output_folder = input_folder.rstrip("\\/") + "_trimmed"

        self._set_running(True)
        self.progress.reset("トリミングを開始します...")

        root = self.winfo_toplevel()
        emitter = GuiEmitter(root, progress_bar=self.progress.progress_bar,
                             status_var=self.progress.status_var,
                             phase_labels=TRIM_PHASE_LABELS)
        margins = self._margins()

        def thread():
            # プレビューで人間が確認してから実行するので clipped 検証では中止しない。
            # passthrough=True で、共通マージンでは内容が切れるページ（全面表示の
            # 表紙・購入画面）を無加工コピーする。再実行時に前回の残骸が混ざらない
            # よう overwrite=True。
            try:
                code = run_trim(
                    input_folder, output_folder, margins=margins,
                    no_check=True, passthrough=True, overwrite=True, emit=emitter,
                )
            except Exception as e:
                emitter("error", human=f"エラー: {e}", message=str(e))
                code = -1
            root.after(0, lambda: self._on_trim_done(code, output_folder, emitter))

        run_in_thread(thread)

    def _on_trim_done(self, code, output_folder, emitter):
        self._set_running(False)
        if code != EXIT_OK:
            self.progress.status_var.set("エラー")
            messagebox.showerror("エラー", emitter.final_message or "トリミングに失敗しました。")
            return
        self.progress.status_var.set("トリミング完了")
        self.wizard.work_folder = output_folder
        self.goto(STEP_CONVERT)
