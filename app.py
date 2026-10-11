"""kindle_shot — 電子書籍キャプチャツール

電子書籍のスクリーンキャプチャ・トリミング・PDF変換・OCRを
ウィザード形式の GUI で操作できる統合ツール。

使い方: python app.py
"""

# --- DPI 認識は他のどの import よりも先に確定させる ---------------------------
# pyautogui は import された時点で SetProcessDPIAware()（System Aware）を呼ぶ。
# DPI 認識はプロセスで最初の設定だけが有効なので、ui.main_window → core →
# pyautogui の import 連鎖が走ったあとでは Per-Monitor に切り替えられない。
# System Aware のままだと拡大率の異なるモニタ上でウィンドウ矩形が仮想化され、
# 物理ピクセルを返す ImageGrab とズレてキャプチャ範囲が欠ける（実害確認済み）。
from core.dpi import enable_per_monitor_dpi_awareness

enable_per_monitor_dpi_awareness()

import customtkinter as ctk
from PIL import Image

from ui.main_window import KindleShotApp

Image.MAX_IMAGE_PIXELS = 200_000_000


def main():
    # OS のライト/ダーク設定に追従する（画面仕様書 §7）。
    # theme 非対応の tk ウィジェット (プレビューの tk.Label) は
    # ui/theme.py の resolve_color() で色を合わせる。
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")

    app = KindleShotApp()
    app.mainloop()


if __name__ == "__main__":
    main()
