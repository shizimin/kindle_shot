"""OCRエンジンモジュール

NDLOCR-Lite を共通インターフェースで呼び出し、画像からテキストを抽出する。
本ツールは書籍・印刷物の OCR に対応する単一エンジン構成 (NDLOCR-Lite) で運用する。

OCR 結果は process_folder_collect() でリストとして取得し、
各種ビルダー (pdf_builder, markdown_writer) に渡して変換できる。
"""

import collections
import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading

from core import ocr_preprocess, text_replacements
from core.config import load_config
from core.image_files import OCR_IMAGE_EXTENSIONS, list_images

# ============================================================
# NDLOCR-Lite エンジン
# ============================================================

class NDLOCREngine:
    """NDLOCR-Lite エンジン (書籍・印刷物全般、レイアウト解析付き)。"""

    key = "ndlocr"
    description = "NDLOCR-Lite — 書籍・印刷物全般、レイアウト解析付き"

    # 一括モードのストール検出タイムアウト (秒)。
    # 1行も出力が進まない時間がこれを超えたらハング扱いで打ち切る。
    # 最初の1枚はモデルロード込みなので長めに取る。
    BATCH_FIRST_PAGE_TIMEOUT = 600
    BATCH_PAGE_TIMEOUT = 180

    def is_available(self):
        if shutil.which("ndlocr-lite"):
            return True, "ndlocr-lite コマンドが見つかりました"

        ndlocr_dir = self._find_dir()
        if ndlocr_dir:
            return True, f"ndlocr-lite ディレクトリが見つかりました: {ndlocr_dir}"

        return False, (
            "NDLOCR-Lite がインストールされていません。\n"
            "インストール: git clone https://github.com/ndl-lab/ndlocr-lite && "
            "cd ndlocr-lite && pip install -r requirements.txt"
        )

    def process_single(self, image_path, preprocess_opts=None):
        if not os.path.exists(image_path):
            return False, f"ファイルが見つかりません: {image_path}"

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # 前処理が有効なら、tmpdir に前処理済み画像を作って NDLOCR に渡す
                input_for_ocr = self._maybe_preprocess(image_path, tmpdir, preprocess_opts)

                use_system = bool(shutil.which("ndlocr-lite"))
                # NDLOCR の出力先は前処理画像と分けるためサブディレクトリを切る
                ocr_out = os.path.join(tmpdir, "_ocr_out")
                os.makedirs(ocr_out, exist_ok=True)
                cmd = self._build_command(input_for_ocr, ocr_out, use_system)
                result = subprocess.run(
                    cmd, capture_output=True, text=True, encoding="utf-8", timeout=120,
                )
                if result.returncode != 0:
                    return False, f"OCRエラー: {result.stderr}"
                text = self._collect_text(ocr_out)
                return True, text
            except subprocess.TimeoutExpired:
                return False, "OCR処理がタイムアウトしました（120秒）"
            except Exception as e:
                return False, f"OCR処理中にエラー: {e}"

    def process_folder(self, input_folder, image_files, preprocess_opts=None,
                       on_progress=None, workers=1):
        """フォルダ内の画像を ndlocr-lite の --sourcedir で一括 OCR する。

        ページ毎にサブプロセスを起動する方式はモデルロードを毎回やり直す
        (実測: 1ページあたりロード約19秒 + 推論約1.3秒) ため、1回の起動で
        全ページを処理する。300ページで約15倍の短縮になる。

        workers > 1 の場合はページ列を連続チャンクに分割し、チャンクごとに
        ndlocr-lite プロセスを並列起動する。モデルロードはワーカー数だけ
        重複するが、推論がコア数に応じて並列化される。

        Args:
            input_folder: 画像フォルダパス
            image_files: 処理対象のファイル名リスト (ソート済み)。
                拡張子を除いたステム名が一意であること (出力 .txt の対応付けに使う)。
            preprocess_opts: 前処理パラメータ dict
            on_progress: 進捗コールバック (current, total, filename)。
                前処理パスと OCR パスでそれぞれ 1..total を報告する。
            workers: 並列起動する ndlocr-lite プロセス数

        Returns:
            (success, results_or_error) のタプル
            成功時: results は [(filename, text), ...] のリスト
        """
        total = len(image_files)
        workers = max(1, min(int(workers or 1), total))
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                chunks = self._split_chunks(image_files, workers)
                src_dirs = self._prepare_batch_inputs(
                    input_folder, chunks, tmpdir, preprocess_opts,
                    on_progress, total,
                )
                use_system = bool(shutil.which("ndlocr-lite"))

                results_map = {}
                errors = []
                lock = threading.Lock()
                done_counter = [0]

                def run_chunk(idx):
                    chunk = chunks[idx]
                    ocr_out = os.path.join(tmpdir, f"_ocr_out_{idx}")
                    os.makedirs(ocr_out, exist_ok=True)
                    cmd = self._build_command(src_dirs[idx], ocr_out, use_system)

                    def chunk_progress(_cur, _tot, fname):
                        with lock:
                            done_counter[0] += 1
                            count = done_counter[0]
                        if on_progress:
                            on_progress(count, total, fname)

                    ok, err = self._run_batch(cmd, len(chunk), chunk, chunk_progress)
                    if not ok:
                        errors.append(err)
                        return
                    for filename in chunk:
                        stem = os.path.splitext(filename)[0]
                        text = self._read_page_text(ocr_out, stem)
                        if text is None:
                            text = "[OCRエラー: 出力が見つかりません]"
                        results_map[filename] = text

                if len(chunks) == 1:
                    run_chunk(0)
                else:
                    threads = [
                        threading.Thread(target=run_chunk, args=(i,), daemon=True)
                        for i in range(len(chunks))
                    ]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join()

                if errors:
                    return False, errors[0]
                return True, [(f, results_map[f]) for f in image_files]
            except Exception as e:
                return False, f"OCR一括処理中にエラー: {e}"

    def _split_chunks(self, image_files, workers):
        """ページ順を保ったまま連続チャンクに分割する。"""
        n = len(image_files)
        base, rem = divmod(n, workers)
        chunks = []
        start = 0
        for i in range(workers):
            size = base + (1 if i < rem else 0)
            if size:
                chunks.append(image_files[start:start + size])
            start += size
        return chunks

    def _prepare_batch_inputs(self, input_folder, chunks, tmpdir,
                              preprocess_opts, on_progress, total):
        """チャンクごとの入力フォルダを準備する。

        前処理が有効なら前処理済み画像 (<stem>.png) を、無効なら元画像への
        ハードリンク (不可ならコピー) を、チャンク別フォルダに配置する。
        前処理無効かつ 1 チャンクの場合だけは入力フォルダをそのまま使う。
        """
        enabled = bool(preprocess_opts and preprocess_opts.get("enabled"))
        if not enabled and len(chunks) == 1:
            return [input_folder]

        src_dirs = []
        done = 0
        for i, chunk in enumerate(chunks):
            chunk_dir = os.path.join(tmpdir, f"_src_{i}")
            os.makedirs(chunk_dir, exist_ok=True)
            src_dirs.append(chunk_dir)
            for filename in chunk:
                src = os.path.join(input_folder, filename)
                if enabled:
                    stem = os.path.splitext(filename)[0]
                    ocr_preprocess.preprocess_file(
                        src, os.path.join(chunk_dir, stem + ".png"),
                        upscale=float(preprocess_opts.get("upscale", 1.5)),
                        enhance_contrast=bool(preprocess_opts.get("enhance_contrast", True)),
                        binarize=bool(preprocess_opts.get("binarize", False)),
                        binarize_threshold=int(preprocess_opts.get("binarize_threshold", 180)),
                    )
                else:
                    dst = os.path.join(chunk_dir, filename)
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                done += 1
                if on_progress:
                    on_progress(done, total, f"前処理: {filename}")
        return src_dirs

    def _run_batch(self, cmd, total, image_files, on_progress):
        """一括 OCR サブプロセスを実行し、stdout を監視して進捗を中継する。

        ndlocr-lite は 1 枚処理するごとに "Total calculation time ..." を
        stdout に出すので、その行数で進捗を数える。一定時間出力が止まったら
        ハング扱いで kill する (夜間バッチで無限待ちしないため)。

        Returns:
            (success, error_message) のタプル
        """
        # 子プロセスの stdout がブロックバッファリングされると進捗行が
        # まとめて届いてストール誤検出になるため、アンバッファを強制する
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", env=env,
        )
        tail = collections.deque(maxlen=20)
        line_queue = queue.Queue()

        def _pump():
            for line in proc.stdout:
                line_queue.put(line)
            line_queue.put(None)

        threading.Thread(target=_pump, daemon=True).start()

        done = 0
        timeout = self.BATCH_FIRST_PAGE_TIMEOUT
        try:
            while True:
                try:
                    line = line_queue.get(timeout=timeout)
                except queue.Empty:
                    proc.kill()
                    return False, (
                        f"OCR処理が {timeout} 秒間応答しませんでした"
                        f"（{done}/{total} ページ完了時点）"
                    )
                if line is None:
                    break
                tail.append(line.rstrip())
                if line.startswith("Total calculation time"):
                    done += 1
                    timeout = self.BATCH_PAGE_TIMEOUT
                    if on_progress and done <= total:
                        on_progress(done, total, image_files[done - 1])
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()

        if proc.returncode != 0:
            detail = "\n".join(tail)
            return False, f"OCRエラー (exit {proc.returncode}):\n{detail}"
        return True, ""

    def _read_page_text(self, output_dir, stem):
        """一括 OCR の出力ディレクトリから 1 ページ分のテキストを読む。

        <stem>.txt 優先、無ければ <stem>.json から抽出。どちらも無ければ None。
        """
        txt_path = os.path.join(output_dir, stem + ".txt")
        if os.path.exists(txt_path):
            with open(txt_path, encoding="utf-8") as f:
                return f.read()
        json_path = os.path.join(output_dir, stem + ".json")
        if os.path.exists(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    data = json.load(f)
                return self._extract_json_text(data)
            except (json.JSONDecodeError, KeyError):
                return None
        return None

    def _maybe_preprocess(self, image_path, tmpdir, opts):
        """前処理が有効なら tmpdir に前処理済み画像を保存し、そのパスを返す。
        無効ならオリジナルパスをそのまま返す。
        """
        if not opts or not opts.get("enabled"):
            return image_path
        ext = os.path.splitext(image_path)[1].lower() or ".png"
        # NDLOCR は .jpg / .png を受け付ける。前処理後はロスレス維持で .png にする
        if ext not in (".png", ".jpg", ".jpeg"):
            ext = ".png"
        dst = os.path.join(tmpdir, "_preprocessed" + ext)
        ocr_preprocess.preprocess_file(
            image_path, dst,
            upscale=float(opts.get("upscale", 1.5)),
            enhance_contrast=bool(opts.get("enhance_contrast", True)),
            binarize=bool(opts.get("binarize", False)),
            binarize_threshold=int(opts.get("binarize_threshold", 180)),
        )
        return dst

    def _find_dir(self):
        base = os.path.dirname(os.path.abspath(__file__))
        for rel in ("ndlocr-lite", os.path.join("..", "ndlocr-lite")):
            path = os.path.join(base, rel)
            if os.path.exists(os.path.join(path, "src", "ocr.py")):
                return os.path.abspath(path)
        return None

    def _build_command(self, input_path, output_dir, use_system):
        if use_system:
            cmd = ["ndlocr-lite"]
        else:
            ndlocr_dir = self._find_dir()
            if not ndlocr_dir:
                raise RuntimeError("ndlocr-lite が見つかりません")
            cmd = [sys.executable, os.path.join(ndlocr_dir, "src", "ocr.py")]

        if os.path.isdir(input_path):
            cmd.extend(["--sourcedir", input_path])
        else:
            cmd.extend(["--sourceimg", input_path])
        cmd.extend(["--output", output_dir])
        return cmd

    def _collect_text(self, output_dir):
        # NDLOCR-Lite は同じ内容を .txt / .json / .xml で出力するため
        # .txt 優先で読み、無い場合のみ .json から抽出する
        text_parts = []
        json_fallbacks = []
        txt_seen_stems = set()
        for root, _dirs, files in os.walk(output_dir):
            for f in sorted(files):
                filepath = os.path.join(root, f)
                stem, ext = os.path.splitext(f)
                if ext == ".txt":
                    with open(filepath, encoding="utf-8") as fh:
                        text_parts.append(fh.read())
                    txt_seen_stems.add(stem)
                elif ext == ".json":
                    json_fallbacks.append((stem, filepath))

        for stem, filepath in json_fallbacks:
            if stem in txt_seen_stems:
                continue
            try:
                with open(filepath, encoding="utf-8") as fh:
                    data = json.load(fh)
                extracted = self._extract_json_text(data)
                if extracted:
                    text_parts.append(extracted)
            except (json.JSONDecodeError, KeyError):
                pass

        return "\n".join(text_parts) if text_parts else ""

    def _extract_json_text(self, data):
        texts = []
        if isinstance(data, dict):
            if "text" in data:
                texts.append(str(data["text"]))
            for key in ("children", "blocks", "lines", "words", "results"):
                if key in data and isinstance(data[key], list):
                    for item in data[key]:
                        t = self._extract_json_text(item)
                        if t:
                            texts.append(t)
        elif isinstance(data, list):
            for item in data:
                t = self._extract_json_text(item)
                if t:
                    texts.append(t)
        return "\n".join(texts)


# ============================================================
# 公開API
# ============================================================

_ENGINE = NDLOCREngine()


def get_available_engines():
    """利用可能な OCR エンジンのリストを返す (NDLOCR-Lite のみ)。"""
    available, message = _ENGINE.is_available()
    return [{
        "key": _ENGINE.key,
        "description": _ENGINE.description,
        "available": available,
        "message": message,
    }]


def is_available():
    """OCR エンジンが利用可能かチェックする。

    Returns:
        (available, message) のタプル
    """
    return _ENGINE.is_available()


def _resolve_preprocess_opts(preprocess_opts):
    """呼び出し側が opts を渡さなかったら config から読む。"""
    if preprocess_opts is not None:
        return preprocess_opts
    cfg = load_config()
    return cfg.get("ocr", {}).get("preprocess", {})


def _resolve_replacements_opts(replacements_opts):
    """呼び出し側が opts を渡さなかったら config から読む。"""
    if replacements_opts is not None:
        return replacements_opts
    cfg = load_config()
    return cfg.get("ocr", {}).get("replacements", {})


def _resolve_workers(workers):
    """呼び出し側が指定しなかったら config から読む。"""
    if workers is not None:
        return max(1, int(workers))
    cfg = load_config()
    return max(1, int(cfg.get("ocr", {}).get("workers", 1) or 1))


def _apply_replacements_to_results(results, replacements_opts):
    """results に対して置換辞書を適用する。

    無効化されていればそのまま返す。エラーメッセージはサイレントに無視する
    (UI 側で別途辞書ロードのバリデーションを行う想定)。
    """
    if not replacements_opts or not replacements_opts.get("enabled", True):
        return results
    path = replacements_opts.get("path") or text_replacements.default_path()
    new_results, _err = text_replacements.apply_to_results(results, path=path)
    return new_results


def _process_folder_per_page(input_folder, image_files, preprocess_opts, on_progress):
    """ページ毎にサブプロセスを起動する旧方式のフォルダ OCR。

    モデルロードを毎ページやり直すため遅い。一括モードが使えない場合
    (ステム名の衝突時) のフォールバック専用。
    """
    total = len(image_files)
    results = []
    for i, filename in enumerate(image_files, 1):
        filepath = os.path.join(input_folder, filename)
        success, text = _ENGINE.process_single(filepath, preprocess_opts=preprocess_opts)
        if success:
            results.append((filename, text))
        else:
            results.append((filename, f"[OCRエラー: {text}]"))
        if on_progress:
            on_progress(i, total, filename)
    return True, results


def process_folder_collect(
    input_folder, on_progress=None,
    preprocess_opts=None, replacements_opts=None, workers=None,
):
    """フォルダ内の画像を一括 OCR 処理し、結果をリストで返す。

    通常は ndlocr-lite を 1 回だけ起動する一括モードで処理する
    (モデルロードが 1 回で済み、ページ毎起動より大幅に速い)。
    拡張子違いの同名ファイルがある場合のみ、出力ファイル名が衝突するため
    ページ毎起動のフォールバックに切り替える。

    Args:
        preprocess_opts: 前処理パラメータ dict。None なら config から読む。
        replacements_opts: 置換辞書パラメータ dict。None なら config から読む。
        workers: 並列起動する ndlocr-lite プロセス数。None なら config
            (ocr.workers) から読む。

    Returns:
        (success, results_or_error) のタプル
        成功時: results は [(filename, text), ...] のリスト
    """
    available, msg = _ENGINE.is_available()
    if not available:
        return False, msg

    image_files = list_images(input_folder, OCR_IMAGE_EXTENSIONS)
    if not image_files:
        return False, "画像ファイルが見つかりません"

    opts = _resolve_preprocess_opts(preprocess_opts)

    stems = [os.path.splitext(f)[0] for f in image_files]
    if len(set(stems)) == len(stems):
        success, results = _ENGINE.process_folder(
            input_folder, image_files,
            preprocess_opts=opts, on_progress=on_progress,
            workers=_resolve_workers(workers),
        )
    else:
        success, results = _process_folder_per_page(
            input_folder, image_files, opts, on_progress,
        )
    if not success:
        return False, results

    rep_opts = _resolve_replacements_opts(replacements_opts)
    results = _apply_replacements_to_results(results, rep_opts)

    return True, results
