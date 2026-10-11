"""共通UIパーツ"""

import tkinter as tk

import customtkinter as ctk

from ui import theme
from ui.tab_utils import append_log, clear_log


class Tooltip:
    """ホバー時にテキストを表示する簡易ツールチップ。

    ウィザードでは説明を画面内テキストで出すのが基本のため現在は未使用だが、
    補助として継続使用する方針（画面仕様書 §7）なので残している。
    """

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self._tipwindow = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def update_text(self, text):
        self.text = text

    def _show(self, event=None):
        if self._tipwindow or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw, text=self.text, justify="left",
            background="#ffffe0", relief="solid", borderwidth=1,
            font=("TkDefaultFont", 9), padx=6, pady=4,
        )
        label.pack()
        self._tipwindow = tw

    def _hide(self, event=None):
        if self._tipwindow:
            self._tipwindow.destroy()
            self._tipwindow = None


class ProgressPanel(ctk.CTkFrame):
    """進捗バー + ステータス + ログの 3 点セット。

    実行中の表示はどのステップでも同じ形なので、ここに集約する。
    総ページ数が事前に分からないキャプチャでは start_indeterminate() で
    バーを流し、完了時に stop_indeterminate() で止める。
    """

    def __init__(self, master, *, log_height=140, show_log=True):
        super().__init__(master, fg_color="transparent")
        self.status_var = tk.StringVar(value="待機中")
        self._indeterminate = False

        self.progress_bar = ctk.CTkProgressBar(self)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            self, textvariable=self.status_var, anchor="w",
            text_color=theme.MUTED_COLOR,
        ).pack(fill="x")

        self.log_text = None
        if show_log:
            self.log_text = ctk.CTkTextbox(
                self, height=log_height, wrap="word", state="disabled",
            )
            self.log_text.pack(fill="both", expand=True, pady=(theme.PAD_SMALL, 0))

    def reset(self, status="待機中"):
        self.stop_indeterminate()
        self.progress_bar.set(0)
        self.status_var.set(status)
        if self.log_text is not None:
            clear_log(self.log_text)

    def log(self, message):
        if self.log_text is not None:
            append_log(self.log_text, message)

    def start_indeterminate(self):
        if self._indeterminate:
            return
        self._indeterminate = True
        self.progress_bar.configure(mode="indeterminate")
        self.progress_bar.start()

    def stop_indeterminate(self):
        if not self._indeterminate:
            return
        self._indeterminate = False
        self.progress_bar.stop()
        self.progress_bar.configure(mode="determinate")
        self.progress_bar.set(0)


class SpinBox(ctk.CTkFrame):
    """整数を増減する入力欄（customtkinter に標準が無いため自作）。

    「−」「＋」ボタンと数値入力欄の組。値が変わるたび command を呼ぶ。

    刻みの既定は 10px。4K キャプチャの余白調整では 2px 刻みだとクリック
    回数が現実的でない（93px 削るのに 47 回）ため。上下限は画像サイズに
    合わせて set_bounds() であとから変えられる。
    """

    def __init__(self, master, *, label="", value=0, step=10, minimum=0,
                 maximum=10000, width=64, command=None):
        super().__init__(master, fg_color="transparent")
        self._step = step
        self._min = minimum
        self._max = maximum
        self._command = command
        self.var = tk.StringVar(value=str(value))

        if label:
            ctk.CTkLabel(self, text=label, width=24, anchor="w").pack(side="left")
        ctk.CTkButton(
            self, text="−", width=28, command=lambda: self._nudge(-self._step),
        ).pack(side="left")
        self._entry = ctk.CTkEntry(self, textvariable=self.var, width=width,
                                   justify="center")
        self._entry.pack(side="left", padx=2)
        ctk.CTkButton(
            self, text="＋", width=28, command=lambda: self._nudge(self._step),
        ).pack(side="left")

        self.var.trace_add("write", lambda *_: self._notify())

    def get(self):
        """現在値（不正な入力は最小値として扱う）。"""
        try:
            return max(self._min, min(self._max, int(self.var.get())))
        except (TypeError, ValueError):
            return self._min

    def set(self, value):
        self.var.set(str(max(self._min, min(self._max, int(value)))))

    def set_bounds(self, minimum, maximum):
        """上下限をあとから変える（画像サイズに合わせる用途）。

        現在値が新しい範囲の外なら、範囲内へ収め直す。
        """
        self._min = minimum
        self._max = maximum
        self.set(self.get())

    def _nudge(self, delta):
        self.set(self.get() + delta)

    def _notify(self):
        if self._command is not None:
            self._command()
