"""UI 共通ユーティリティ

ログ追記・フォルダ選択・進捗コールバック・スレッド起動を各画面で
コピペしないよう、ここに集約する（旧4タブ時代からの共有資産）。

GuiEmitter は core.pipeline / core.capture_runner の run_* に渡す
emit 互換 callable。イベントをログ・進捗バー・ステータスへ写像する。
"""

import threading
from tkinter import filedialog


def append_log(textbox, message):
    """読み取り専用 CTkTextbox にログを 1 行追記して末尾へスクロールする。"""
    textbox.configure(state="normal")
    textbox.insert("end", message + "\n")
    textbox.see("end")
    textbox.configure(state="disabled")


def clear_log(textbox):
    """読み取り専用 CTkTextbox の内容を消去する。"""
    textbox.configure(state="normal")
    textbox.delete("1.0", "end")
    textbox.configure(state="disabled")


def browse_folder_into(var):
    """フォルダ選択ダイアログを開き、選択されたパスを var にセットする。"""
    folder = filedialog.askdirectory()
    if folder:
        var.set(folder)


def run_in_thread(work):
    """work() をデーモンスレッドで実行する。

    UI 更新は work 側で root.after(0, ...) を使ってマーシャリングすること。
    """
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def make_progress_cb(root, progress_bar, status_var, fmt="{current}/{total}"):
    """core の on_progress(current, total, filename) 互換コールバックを作る。

    進捗バーとステータス文字列を root.after で UI スレッドから更新する。
    fmt には {current} {total} {filename} が使える。
    """
    def cb(current, total, filename):
        ratio = current / total if total else 0
        text = fmt.format(current=current, total=total, filename=filename)
        root.after(0, lambda: progress_bar.set(ratio))
        root.after(0, lambda: status_var.set(text))
    return cb


class GuiEmitter:
    """core の run_* に渡す emit(event, human=None, **fields) 互換 callable。

    ワーカースレッドから呼ばれる前提で、UI 更新はすべて root.after(0, ...) で
    UI スレッドへマーシャリングする。イベントの写像:

    - progress      → 進捗バー + ステータス
    - page          → ログ + ステータス「キャプチャ中... Page N」
    - error         → 保持 (error_human) + ログ
    - result        → 保持 (result_human / result_fields) + ログ
    - markdown_stats→ 保持 (stats_human) + ログ
    - その他        → human があればログへ (前方互換)

    完了後、呼び出し側は error_human / result_human / result_fields を
    ダイアログや結果表示に使う。
    """

    def __init__(self, root, *, log=None, progress_bar=None, status_var=None,
                 phase_labels=None):
        self.root = root
        self.log = log
        self.progress_bar = progress_bar
        self.status_var = status_var
        # core の phase 名 (英語) を画面に出す日本語へ読み替える対応表。
        # 省略時は phase 名をそのまま [] 付きで出す (従来動作)。
        self.phase_labels = phase_labels or {}
        self.result_fields = {}
        self.result_human = None
        self.error_human = None
        self.stats_human = None

    def _ui(self, fn):
        self.root.after(0, fn)

    def __call__(self, event, human=None, **fields):
        if event == "progress":
            current, total = fields.get("current", 0), fields.get("total", 0)
            ratio = current / total if total else 0
            if self.progress_bar is not None:
                self._ui(lambda: self.progress_bar.set(ratio))
            if self.status_var is not None:
                phase = fields.get("phase")
                prefix = (
                    f"{self.phase_labels.get(phase, f'[{phase}]')} "
                    if phase else ""
                )
                text = f"{prefix}{current}/{total} ({fields.get('file', '')})"
                self._ui(lambda: self.status_var.set(text))
            return  # 進捗はログに流さない (量が多い)

        if event == "page" and self.status_var is not None:
            page = fields.get("page")
            self._ui(lambda: self.status_var.set(f"キャプチャ中... Page {page}"))
        elif event == "error":
            self.error_human = human or fields.get("message", "")
        elif event == "result":
            self.result_fields = fields
            self.result_human = human
        elif event == "markdown_stats":
            self.stats_human = human

        if human and self.log is not None:
            self._ui(lambda m=human: append_log(self.log, m))

    @property
    def final_message(self):
        """完了ダイアログ用のメッセージ (result の human、なければ error)。"""
        return self.result_human or self.error_human or ""
