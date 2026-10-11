"""DPI 認識ユーティリティ

GUI (app.py) と CLI のキャプチャ系コマンドの両方から、プロセス起動直後に呼ぶ。
GetWindowRect が返すウィンドウ座標と ImageGrab.grab(all_screens=True) が撮る
物理ピクセルを一致させるのが目的。

**呼ぶ位置の罠**: pyautogui は import された時点で SetProcessDPIAware()
（System Aware）を呼ぶ。DPI 認識はプロセスで最初の設定だけが有効なので、
pyautogui（を間接的に読み込む ui / core.capture_*）より後に呼んでも効かない。
そのため app.py / cli.py では **モジュール先頭・他のどの import よりも前**に
呼ぶこと。main() の中では手遅れになる。
"""


def enable_per_monitor_dpi_awareness():
    """プロセスを Per-Monitor DPI Aware (v1) にする。

    マルチモニタ（特に外部4Kなどプライマリと拡大率が異なるディスプレイ）で、
    System Aware だと拡大率の異なるモニタ上で座標が仮想化され、キャプチャ範囲が
    位置ズレ・サイズ違いになる。

    customtkinter も CTk 生成時に同じ Per-Monitor v1 を設定するが、DPI 認識は
    プロセスで最初の呼び出しだけが有効なため、エントリポイントで先に確定させる。
    以前の SetProcessDPIAware()（System Aware）は逆に customtkinter の
    per-monitor 設定を潰していた。v2 は customtkinter が tkinter 互換性の問題で
    避けているため v1 を採用。

    pyautogui も import 時に SetProcessDPIAware() を呼ぶため、この関数は
    pyautogui より先（= モジュール先頭）で呼ばないと効かない。
    """
    import contextlib
    from ctypes import windll
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2 (Windows 8.1+)
        windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        # フォールバック: System DPI Aware (Vista+)
        with contextlib.suppress(Exception):
            windll.user32.SetProcessDPIAware()
