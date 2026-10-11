"""メインウィンドウ（ウィザード）

画面仕様書 §2 の3層構造:

- ヘッダー: ステップインジケータ（現在地をハイライト）
- ボディ  : 現在ステップの内容（縦に溢れる場合はボディだけスクロールする）
- フッター: 常時表示のアクションバー（ステップごとの主ボタンを置く）

ボディだけがスクロールするため、ウィンドウをどれだけ縮めても
フッターの主ボタンは画面内に残る。
"""

import customtkinter as ctk

from core.config import load_config, save_config
from ui import theme
from ui.steps.capture_step import CaptureStep
from ui.steps.convert_step import ConvertStep
from ui.steps.done_step import DoneStep
from ui.steps.home_step import HomeStep
from ui.steps.pdf_step import PdfStep
from ui.steps.trim_step import TrimStep
from ui.wizard import (
    PHASES,
    STEP_CAPTURE,
    STEP_CONVERT,
    STEP_DONE,
    STEP_HOME,
    STEP_PDF,
    STEP_TRIM,
    WizardState,
)

STEP_CLASSES = (
    (STEP_HOME, HomeStep),
    (STEP_CAPTURE, CaptureStep),
    (STEP_PDF, PdfStep),
    (STEP_TRIM, TrimStep),
    (STEP_CONVERT, ConvertStep),
    (STEP_DONE, DoneStep),
)


class KindleShotApp(ctk.CTk):
    """ウィザード形式のメインアプリケーションウィンドウ"""

    def __init__(self):
        super().__init__()
        self.title("kindle_shot — 電子書籍キャプチャ・OCRツール")
        self.geometry("960x720")
        self.minsize(800, 600)

        # ルート生成後でないと tkinter.font.families() が使えない
        theme.apply_font_theme(self)

        self.config_data = load_config()
        # NOTE: tk.Tk / ctk.CTk は state() メソッドを持つので self.state は使わない
        self.wizard_state = WizardState()

        self._build_layout()
        self._build_steps()
        self.show_step(STEP_HOME)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- レイアウト ---

    def _build_layout(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        self._build_header(header)

        # ボディは通常フレーム。CTkScrollableFrame は使わない:
        # 内容高さが表示域の境界付近で変動すると、customtkinter のスクロールバーが
        # set → _draw → update_idletasks の無限再帰に陥り、Tk_GetPixmap
        # (CreateDIBSection) エラーで UI ごと固まる (2026-08-28 実機+再現で確認)。
        # 各ステップは表示域に収まるよう作る (S2 のプレビューは高さ追従で調整)。
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew", padx=theme.PAD_SMALL)

        self.footer_bar = ctk.CTkFrame(self, corner_radius=0)
        self.footer_bar.grid(row=2, column=0, sticky="ew")

    def _build_header(self, header):
        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=theme.PAD_X, pady=theme.PAD_Y)

        self._phase_labels = []
        for index, (label, _steps) in enumerate(PHASES):
            if index > 0:
                ctk.CTkLabel(
                    inner, text="→", text_color=theme.MUTED_COLOR,
                ).pack(side="left", padx=theme.PAD_SMALL)
            widget = ctk.CTkLabel(inner, text=label)
            widget.pack(side="left")
            self._phase_labels.append(widget)

    def _build_steps(self):
        self.steps = {}
        for step_id, cls in STEP_CLASSES:
            self.steps[step_id] = cls(self.body, self, self.footer_bar)
        self.current_step_id = None

    # --- ステップ遷移 ---

    def show_step(self, step_id):
        """指定ステップのボディとフッターを表示する。"""
        if self.current_step_id == step_id:
            self.steps[step_id].on_enter()
            return
        if self.current_step_id is not None:
            current = self.steps[self.current_step_id]
            current.on_leave()
            current.pack_forget()
            current.footer.pack_forget()

        self.current_step_id = step_id
        step = self.steps[step_id]
        step.pack(fill="both", expand=True)
        step.footer.pack(fill="x", padx=theme.PAD_X, pady=theme.PAD_Y)
        self._update_header(step_id)
        step.on_enter()

    def reset_wizard(self):
        """ウィザードの状態と各ステップの入力を初期化する（「次の本へ」）。"""
        self.wizard_state.reset()
        for step in self.steps.values():
            step.on_reset()

    def _update_header(self, step_id):
        """現在地に応じてステップインジケータの見た目を変える。"""
        current_index = None
        for index, (_label, steps) in enumerate(PHASES):
            if step_id in steps:
                current_index = index
                break

        for index, widget in enumerate(self._phase_labels):
            if step_id == STEP_DONE:
                # 完了画面では全ステップを通過済みとして表示する
                done, current = True, False
            elif current_index is None:
                done, current = False, False
            else:
                done, current = index < current_index, index == current_index
            if current:
                widget.configure(
                    font=ctk.CTkFont(size=theme.FONT_SIZE_BASE, weight="bold"),
                    text_color=ctk.ThemeManager.theme["CTkButton"]["fg_color"],
                )
            elif done:
                widget.configure(
                    font=ctk.CTkFont(size=theme.FONT_SIZE_BASE),
                    text_color=theme.text_color(),
                )
            else:
                widget.configure(
                    font=ctk.CTkFont(size=theme.FONT_SIZE_BASE),
                    text_color=theme.MUTED_COLOR,
                )

    # --- 終了 ---

    def close_app(self):
        """設定を保存してアプリを終了する（× ボタンと S4 の「終了」の共通経路）。"""
        # 設定保存に失敗してもウィンドウは必ず閉じる（権限・ディスク等で例外が出ても固まらない）。
        try:
            save_config(self.config_data)
        except Exception as e:
            print(f"[WARN] 設定の保存に失敗しました: {e}")
        self.destroy()

    def _on_close(self):
        self.close_app()
