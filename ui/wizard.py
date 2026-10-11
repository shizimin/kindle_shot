"""ウィザードの共通土台（画面仕様書 §2）

- WizardState: ステップをまたいで持ち回る入力・成果物のパス
- WizardStep: 各ステップ画面の基底クラス（ボディとフッターをセットで持つ）

ステップは自分のフッター（アクションバー）を自分で組み立てる。メインウィンドウは
ステップ切り替え時にボディとフッターを同時に差し替えるだけなので、主ボタンは
常にウィンドウ下端に見え続ける（ボディがどれだけ縦に伸びても隠れない）。
"""

import customtkinter as ctk

from ui import theme

# ステップ ID（メインウィンドウのレジストリキー）
STEP_HOME = "home"
STEP_CAPTURE = "capture"
STEP_PDF = "pdf"
STEP_TRIM = "trim"
STEP_CONVERT = "convert"
STEP_DONE = "done"

# ヘッダーのステップインジケータ（表示名とそこに属するステップ）
PHASES = (
    ("① 本を取り込む", (STEP_CAPTURE, STEP_PDF)),
    ("② 余白を整える", (STEP_TRIM,)),
    ("③ 書き出す", (STEP_CONVERT,)),
)


class WizardState:
    """ウィザード全体で共有する状態。

    タブ間イベント通知（旧 ui/state.py の AppState）ではなく、
    値そのものをここに置いて各ステップが読み書きする。
    """

    def __init__(self):
        self.reset()

    def reset(self):
        # 入力源: "capture"（画面キャプチャ） | "pdf"（手持ちPDF）
        self.source = None
        # 本のタイトル（保存フォルダ名・出力ファイル名の初期値）
        self.title = ""
        # 保存先フォルダ（この下に <title>/ が作られる）
        self.save_folder = ""
        # 取り込んだ原画像のフォルダ
        self.image_folder = ""
        # 書き出しの入力フォルダ（トリミング済み、スキップ時は原画像フォルダ）
        self.work_folder = ""
        # 書き出し結果
        self.output_path = ""
        self.output_folder = ""
        self.output_format = "image_pdf"
        self.stats_human = ""

    @property
    def source_step(self):
        """入力源のステップ ID（S2 の「戻る」先）。"""
        return STEP_PDF if self.source == "pdf" else STEP_CAPTURE


class WizardStep(ctk.CTkFrame):
    """ウィザード 1 画面分の基底クラス。

    サブクラスは build() でボディを、build_footer() でフッターを組み立てる。
    on_enter() はその画面が表示されるたびに呼ばれる。
    """

    #: ボディ上部に出す見出し（空なら見出しを出さない）
    heading = ""
    #: 見出しの下に出す説明文
    description = ""

    def __init__(self, master, app, footer_master):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.wizard = app.wizard_state
        self.config_data = app.config_data
        # フッターはメインウィンドウのアクションバーの子として作る
        self.footer = ctk.CTkFrame(footer_master, fg_color="transparent")
        self._build_heading()
        self.build()
        self.build_footer()

    # --- サブクラスが実装する ---

    def build(self):
        """ボディの中身を組み立てる。"""

    def build_footer(self):
        """フッター（アクションバー）の中身を組み立てる。"""

    def on_enter(self):
        """この画面が表示されるたびに呼ばれる。"""

    def on_leave(self):
        """この画面から離れるときに呼ばれる。"""

    def on_reset(self):
        """「次の本へ」で状態をクリアするときに呼ばれる。

        本ごとに変わる入力（タイトル・PDF パス・プレビュー等）を初期化する。
        保存先フォルダのように覚えておきたい値はここでは消さない。
        """

    # --- 共通ヘルパー ---

    def _build_heading(self):
        if not self.heading:
            return
        ctk.CTkLabel(
            self, text=self.heading,
            font=ctk.CTkFont(size=theme.FONT_SIZE_HEADING, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=theme.PAD_X, pady=(theme.PAD_Y, 2))
        if self.description:
            ctk.CTkLabel(
                self, text=self.description, text_color=theme.MUTED_COLOR,
                anchor="w", justify="left", wraplength=860,
            ).pack(fill="x", padx=theme.PAD_X, pady=(0, theme.PAD_Y))

    def goto(self, step_id):
        """別のステップへ移動する。"""
        self.app.show_step(step_id)

    def add_left_button(self, text, command, *, width=110):
        """フッター左端にサブ導線のボタンを置く（「戻る」と同じ見た目）。"""
        btn = ctk.CTkButton(
            self.footer, text=text, width=width,
            fg_color="transparent", border_width=1,
            text_color=theme.text_color(), command=command,
        )
        btn.pack(side="left", padx=(0, theme.PAD_SMALL))
        return btn

    def add_back_button(self, step_id, text="戻る"):
        """フッター左端に「戻る」ボタンを置く。"""
        return self.add_left_button(text, lambda: self.goto(step_id))

    def add_action_button(self, text, command, *, primary=True, width=190):
        """フッター右端に主ボタン（または副ボタン）を置く。

        右端から順に積むので、主ボタンを最初に追加すると右端に来る。
        """
        kwargs = {}
        if not primary:
            kwargs = {
                "fg_color": "transparent", "border_width": 1,
                "text_color": theme.text_color(),
            }
        btn = ctk.CTkButton(
            self.footer, text=text, width=width, height=36,
            command=command, **kwargs,
        )
        btn.pack(side="right", padx=(theme.PAD_SMALL, 0))
        return btn
