"""キャプチャエンジン

プロファイルの設定に基づいて、任意の電子書籍アプリのページを自動キャプチャする。
"""

import os
import threading
import time

import cv2
import numpy as np
import pyautogui as pag
from PIL import ImageGrab

from .boundary_detector import create_detector
from .win32_utils import activate_window, find_window, get_window_rect

pag.FAILSAFE = False


def _changed_ratio(gray_a, gray_b, pixel_thresh=20):
    """2枚のグレースケール画像で、明るさが pixel_thresh より変わった画素の割合(%)。

    静止画同士 (ロスレスキャプチャ) ならほぼ 0%。スピナーが回転していれば
    弧の移動分だけ非ゼロになる。本物のページ遷移では大きく変わる。
    全画面平均や最大差より、細い動きと本物の変化を分離しやすい (実測で確認)。
    """
    return float((np.abs(gray_a.astype(np.float32) - gray_b.astype(np.float32))
                  > pixel_thresh).mean()) * 100.0


def _imwrite_unicode(filepath, image):
    """cv2.imwrite の Unicode パス対応版。保存成功なら True を返す。

    Windows ではアンチウイルスや同期ソフトが一時的にファイルをロックすると
    numpy.tofile が "N requested and 0 written" の OSError を送出する。
    呼び出し側でリトライできるよう例外を握り潰して False を返す。
    """
    ext = os.path.splitext(filepath)[1]
    try:
        success, buf = cv2.imencode(ext, image)
        if not success:
            return False
        # 一時ファイル経由で書き出してから rename するとロック競合に強い
        tmp_path = filepath + ".tmp"
        buf.tofile(tmp_path)
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)
        return True
    except OSError:
        try:
            if os.path.exists(filepath + ".tmp"):
                os.remove(filepath + ".tmp")
        except OSError:
            pass
        return False


class CaptureEngine:
    """ページ自動キャプチャエンジン"""

    def __init__(self, profile, on_page_captured=None, on_status=None, on_complete=None,
                 exclude_pid=None):
        """
        Args:
            profile: CaptureProfile インスタンス
            on_page_captured: ページキャプチャ時のコールバック (page_num, filename)
            on_status: ステータス更新時のコールバック (message)
            on_complete: 完了時のコールバック (total_pages, save_dir)
            exclude_pid: ウィンドウ検索時に除外するプロセスID (自アプリ除外用)
        """
        self.profile = profile
        self._on_page = on_page_captured or (lambda *a: None)
        self._on_status = on_status or (lambda *a: None)
        self._on_complete = on_complete or (lambda *a: None)
        self._running = False
        self._thread = None
        self._exclude_pid = exclude_pid
        self._target_hwnd = None
        self._target_rect = None  # (left, top, right, bottom)
        # 静止待ちの診断用: 直近ページが静止確定するまでに要したグラブ数
        self._last_settle_grabs = 0

    def set_target_window(self, hwnd):
        """キャプチャ対象ウィンドウを設定する。"""
        self._target_hwnd = hwnd
        self._target_rect = get_window_rect(hwnd)

    def _grab(self):
        """画面をキャプチャして BGR numpy 配列を返す。対象ウィンドウ設定時はその領域のみ。"""
        bbox = self._target_rect if self._target_rect else None
        # all_screens=True がないと PIL はプライマリモニタしか取得せず、
        # セカンドモニタ上のウィンドウ (bbox が x>=プライマリ幅 など) は
        # 範囲外となり真っ黒画像になる。境界検出が全行で失敗する原因。
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def find_target_window(self):
        """プロファイルのキーワードでウィンドウを検索する。"""
        return find_window(
            self.profile.window_title_keyword,
            exclude_pid=self._exclude_pid,
            process_name=self.profile.process_name or None,
        )

    def activate_target_window(self, hwnd):
        """対象ウィンドウを前面に出す。"""
        activate_window(
            hwnd,
            click_position=self.profile.click_position,
            use_bring_to_top=self.profile.use_bring_to_top,
        )

    def detect_boundaries(self, image=None):
        """画面をキャプチャして境界を検出する。

        Args:
            image: BGR 画像（None の場合は画面をキャプチャ）

        Returns:
            (left, right) のタプル
        """
        if image is None:
            image = self._grab()

        detector = create_detector(
            self.profile.boundary_method,
            manual_left=self.profile.manual_left,
            manual_right=self.profile.manual_right,
        )
        return detector.detect(image)

    def start(self, save_folder, title):
        """別スレッドでキャプチャを開始する。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop, args=(save_folder, title), daemon=True
        )
        self._thread.start()

    def stop(self):
        """キャプチャを停止する。"""
        self._running = False

    def is_running(self):
        return self._running

    def _capture_loop(self, save_folder, title):
        """メインのキャプチャループ"""
        save_dir = os.path.join(save_folder, title)
        os.makedirs(save_dir, exist_ok=True)

        try:
            # 境界検出
            self._on_status("境界を検出中...")
            image = self._grab()
            lft, rht = self.detect_boundaries(image)

            if lft is None or rht is None:
                self._on_status("エラー: 境界を検出できませんでした")
                self._on_complete(0, save_dir)
                self._running = False
                return

            self._on_status(f"境界検出完了: left={lft}, right={rht}")

            # 前面化のクリックや F11 でビューアが一時的に出す UI (ツールバー・
            # ページバー等) が1ページ目に写り込まないよう、画面が静止するまで
            # 待ってから撮り始める。settle 無効のビューア (Kindle for PC 等) は
            # 最初の「変化した」フレームを即保存するため、ここで待たないと
            # フェード中の UI ごと保存してしまう (2026-08-28 実機で確認)。
            image = self._wait_initial_still(image)

            # キャプチャ開始 — 実際の画像サイズから old 配列を初期化
            img_h = image.shape[0]
            old = np.zeros((img_h, rht - lft, 3), np.uint8)
            page = 1

            while self._running:
                filename = f"{page:03d}.png"
                filepath = os.path.join(save_dir, filename)
                start = time.perf_counter()

                # ページ変化を待つ。settle_enabled のビューアはロード完了(静止)を
                # 待つ専用ロジック、それ以外は従来の「変化したら即」ロジックを使う。
                if self.profile.settle_enabled:
                    ss, page_changed, terminated = self._wait_stable_page(
                        old, lft, rht, page, start, save_dir,
                    )
                else:
                    ss, page_changed, terminated = self._wait_changed_page(
                        old, lft, rht, page, start, save_dir,
                    )
                if terminated:
                    return
                if not page_changed:
                    break

                # 保存（一時的な書き込み失敗をリトライ）
                saved = False
                for attempt in range(1, self.profile.max_retries + 1):
                    if _imwrite_unicode(filepath, ss):
                        saved = True
                        break
                    self._on_status(
                        f"保存失敗 ({attempt}/{self.profile.max_retries}) - 0.5秒後にリトライ: {filename}"
                    )
                    time.sleep(0.5 * attempt)
                if not saved:
                    self._on_status(f"エラー: 保存に失敗しました（リトライ上限）: {filepath}")
                    self._on_complete(page - 1, save_dir)
                    self._running = False
                    return
                old = ss
                elapsed = time.perf_counter() - start
                self._on_page(page, filename)
                if self.profile.settle_enabled:
                    # 静止確定までのグラブ数を出す (少なすぎ=ロード待たず、
                    # 多い=ロードを正しく待った、の診断になる)
                    self._on_status(
                        f"Page {page} ({elapsed:.2f}秒, {self._last_settle_grabs}グラブ)"
                    )
                else:
                    self._on_status(f"Page {page} ({elapsed:.2f}秒)")

                page += 1

                # ページめくり
                pag.keyDown(self.profile.page_turn_key)
                pag.keyUp(self.profile.page_turn_key)
                time.sleep(0.1)

        except Exception as e:
            self._on_status(f"エラー: {e}")

        total = page - 1
        self._on_complete(total, save_dir)
        self._running = False

    def _wait_initial_still(self, first, timeout=6.0):
        """開始直後の画面が静止する (連続2回のグラブが一致する) まで待つ。

        ビューアの UI オーバーレイのフェードが終わるのを待つのが目的。
        timeout 秒たっても静止しない場合は最後のフレームを返して先へ進む
        (常時アニメーションのある画面で無限に待たないための保険)。
        """
        prev = first
        interval = max(self.profile.page_wait, 0.3)
        deadline = time.perf_counter() + timeout
        while self._running and time.perf_counter() < deadline:
            time.sleep(interval)
            cur = self._grab()
            if np.array_equal(prev, cur):
                return cur
            self._on_status("画面の静止を待っています...")
            prev = cur
        return prev

    def _wait_changed_page(self, old, lft, rht, page, start, save_dir):
        """従来方式: 前ページと1ピクセルでも違うフレームを検出したら即確定する。

        軽量なビューア (Kindle for PC 等) 向け。ロードが一瞬なのでロード中
        フレームを掴む心配がなく、最速でめくれる。

        Returns:
            (ss, page_changed, terminated) のタプル。
            terminated=True のときは最終ページ到達 or エラーで on_complete 済み。
        """
        retry_count = 0
        ss = None
        while self._running:
            time.sleep(self.profile.page_wait)
            try:
                ss = self._grab()
                ss = ss[:, lft:rht]

                if not np.array_equal(old, ss):
                    return ss, True, False

                if time.perf_counter() - start > self.profile.timeout_seconds:
                    if retry_count < self.profile.max_retries:
                        retry_count += 1
                        start = time.perf_counter()
                        # キー取りこぼし対策: ページめくりキーを再送する。
                        # 遷移中に送られた直前のキーが無視されると、待つだけでは
                        # 永遠に変化せず最終ページと誤判定するため再送でリカバリする。
                        if page > 1:
                            self._on_status(
                                f"ページ変化なし、めくり再送 "
                                f"({retry_count}/{self.profile.max_retries})"
                            )
                            pag.keyDown(self.profile.page_turn_key)
                            pag.keyUp(self.profile.page_turn_key)
                        continue
                    # タイムアウト → 最終ページに到達
                    self._on_status(f"キャプチャ完了: {page - 1} ページ")
                    self._on_complete(page - 1, save_dir)
                    self._running = False
                    return ss, False, True
            except Exception as e:
                retry_count += 1
                if retry_count >= self.profile.max_retries:
                    self._on_status(f"エラー: {e}")
                    self._on_complete(page - 1, save_dir)
                    self._running = False
                    return ss, False, True
                continue
        return ss, False, False

    def _wait_stable_page(self, old, lft, rht, page, start, save_dir):
        """静止待ち方式: 前ページから変化し、かつ画面が静止したフレームを確定する。

        Cloud Reader 等、ページ画像のロードに時間がかかるビューア向け。
        ロード中のスピナー画面は回転し続けて静止しないため除外され、
        画像がロードし終わって静止したフレームだけが保存される。

        Returns:
            (ss, page_changed, terminated) のタプル。
        """
        old_gray = cv2.cvtColor(old, cv2.COLOR_BGR2GRAY)
        last_gray = None
        stable = 0
        retry_count = 0
        change_start = None  # 前ページから変化を最初に検出した時刻
        grabs = 0
        ss = None
        while self._running:
            time.sleep(self.profile.page_wait)
            try:
                ss = self._grab()
                ss = ss[:, lft:rht]
                gray = cv2.cvtColor(ss, cv2.COLOR_BGR2GRAY)
                grabs += 1
                self._last_settle_grabs = grabs

                # 前ページから変化したか (スピナー画面も本物次ページも変化扱い)
                changed = (
                    _changed_ratio(old_gray, gray)
                    > self.profile.settle_change_threshold
                )

                if changed:
                    # ページは変わった。あとはロード完了 (静止) を待つ。
                    # スピナーは回転し続けるので静止せず、ここで確定しない。
                    if change_start is None:
                        change_start = time.perf_counter()
                    if last_gray is not None and (
                        _changed_ratio(gray, last_gray)
                        < self.profile.settle_threshold
                    ):
                        stable += 1
                    else:
                        stable = 0
                    last_gray = gray
                    if stable >= self.profile.settle_frames:
                        return ss, True, False
                    # 変化はしたが静止しない = ロード中。キー再送はせず待つ
                    # (再送すると、まだ表示していないこのページを飛ばしてしまう)。
                    # ロードが極端に長い場合だけ保険で打ち切る。
                    if time.perf_counter() - change_start > self.profile.settle_load_timeout:
                        self._on_status(
                            f"ロードが完了しませんでした (page {page}) — 最新フレームで確定"
                        )
                        return ss, True, False
                    continue

                # まだ前ページのまま = キー取りこぼし or 最終ページ。
                # 変化を検出済み (change_start) ならこの分岐には来ない。
                if time.perf_counter() - start > self.profile.timeout_seconds:
                    if retry_count < self.profile.max_retries:
                        retry_count += 1
                        start = time.perf_counter()
                        if page > 1:
                            self._on_status(
                                f"ページ変化なし、めくり再送 "
                                f"({retry_count}/{self.profile.max_retries})"
                            )
                            pag.keyDown(self.profile.page_turn_key)
                            pag.keyUp(self.profile.page_turn_key)
                        continue
                    # タイムアウト → 最終ページに到達
                    self._on_status(f"キャプチャ完了: {page - 1} ページ")
                    self._on_complete(page - 1, save_dir)
                    self._running = False
                    return ss, False, True
            except Exception as e:
                retry_count += 1
                if retry_count >= self.profile.max_retries:
                    self._on_status(f"エラー: {e}")
                    self._on_complete(page - 1, save_dir)
                    self._running = False
                    return ss, False, True
                continue
        return ss, False, False
