"""S0 ホーム（画面仕様書 §3 S0）

取り込み方の2択だけを置く。設定項目はここには置かない。
"""

import customtkinter as ctk

from ui import theme
from ui.wizard import STEP_CAPTURE, STEP_PDF, WizardStep

CHOICES = (
    (
        "電子書籍を画面から取り込む",
        "Kindle などの本を自動でページ送りしながら撮影します",
        STEP_CAPTURE,
    ),
    (
        "手持ちのPDFを取り込む",
        "スキャン済みPDFなどを読み込んで、余白調整やOCRをやり直せます",
        STEP_PDF,
    ),
)


class HomeStep(WizardStep):
    heading = "取り込み方を選んでください"

    def on_enter(self):
        # 「次の本へ」で戻ってきたときに前の本の状態を残さない
        self.app.reset_wizard()

    def build(self):
        for label, description, step_id in CHOICES:
            block = ctk.CTkFrame(self, fg_color="transparent")
            block.pack(fill="x", padx=theme.PAD_X, pady=(0, theme.PAD_Y))
            ctk.CTkButton(
                block, text=label, height=60,
                font=ctk.CTkFont(size=theme.FONT_SIZE_BIG_BUTTON, weight="bold"),
                corner_radius=theme.CORNER_RADIUS,
                command=lambda s=step_id: self.goto(s),
            ).pack(fill="x")
            ctk.CTkLabel(
                block, text=description, text_color=theme.MUTED_COLOR,
                anchor="w", justify="left", wraplength=860,
            ).pack(fill="x", padx=4, pady=(4, 0))
