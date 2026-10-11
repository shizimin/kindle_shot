"""kindle_shot CLI — キャプチャ済み画像のトリミング・変換をコマンドラインから実行する

エージェントやバッチスクリプトからの無人運用を想定した設計:
- ダイアログを一切出さない（すべて引数・終了コード・標準出力で完結）
- --json で進捗と結果を JSON Lines として出力（1行1イベント）
- 意味のある終了コードを返す

使い方:
    python cli.py run --asin B0XXXXXXXX --title 本のタイトル --out <保存先フォルダ>
    python cli.py batch --books books.json --out <保存先フォルダ>
    python cli.py open --asin B0XXXXXXXX
    python cli.py capture --profile kindle --title 本のタイトル --out <保存先フォルダ>
    python cli.py pdf --in <PDFファイル> --out <画像フォルダ> --dpi 200
    python cli.py trim --in <画像フォルダ> --out <出力フォルダ> --auto
    python cli.py trim --in <画像フォルダ> --out <出力フォルダ> --margins 100,100,80,120
    python cli.py convert --in <画像フォルダ> --out <出力フォルダ> --format searchable_pdf --name 本のタイトル
    python cli.py validate --in <画像フォルダ> --expect-pages 300
    python cli.py check --profile kindle
    python cli.py profiles

キャプチャの前提: 対象ビューアで本を開き、先頭ページを表示しておくこと。
キャプチャ中は前面ウィンドウとマウスを占有するため PC の他の操作はできない。

終了コード:
    0: 成功
    1: 処理中のエラー
    2: 引数・入力の不正
    3: キャプチャ対象ウィンドウが見つからない / プロセス名不一致
    4: OCR エンジンが利用不可
    5: 画像が見つからない / 0ページ
    6: トリミングで内容が切れるページがある（--force で強行可）
    7: validate で検証エラー
"""

# --- DPI 認識は他のどの import よりも先に確定させる ---------------------------
# pyautogui は import された時点で SetProcessDPIAware()（System Aware）を呼ぶ。
# DPI 認識はプロセスで最初の設定だけが有効なので、core.capture_* 経由で
# pyautogui がロードされたあとでは Per-Monitor に切り替えられない。
# System Aware のままだと拡大率の異なるモニタ上でウィンドウ矩形が仮想化され、
# 物理ピクセルを返す ImageGrab とズレてキャプチャ範囲が欠ける。
from core.dpi import enable_per_monitor_dpi_awareness

enable_per_monitor_dpi_awareness()

import argparse
import json
import os
import sys

from PIL import Image

# ページめくりキーの候補は core/capture_profiles.py が唯一の定義
from core.capture_profiles import PAGE_TURN_KEYS

# 終了コードは cli の公開契約なので、cli.EXIT_* として全て再エクスポートする
from core.pipeline import (  # noqa: F401
    EXIT_BAD_ARGS,
    EXIT_ERROR,
    EXIT_NO_IMAGES,
    EXIT_OCR_UNAVAILABLE,
    EXIT_OK,
    EXIT_VALIDATION,
    EXIT_WINDOW_NOT_FOUND,
    EXIT_WOULD_CLIP,
    FORMATS,
)

Image.MAX_IMAGE_PIXELS = 200_000_000


class Reporter:
    """進捗・結果の出力。--json なら JSON Lines、それ以外は人間向けテキスト。"""

    def __init__(self, as_json):
        self.as_json = as_json

    def event(self, event, human=None, **fields):
        if self.as_json:
            print(json.dumps({"event": event, **fields}, ensure_ascii=False),
                  flush=True)
        elif human:
            print(human, flush=True)

    def error(self, message):
        self.event("error", human=f"エラー: {message}", message=message)

    def progress(self, phase):
        """on_progress コールバック (current, total, filename) を生成する。"""
        def cb(current, total, filename):
            self.event(
                "progress",
                human=f"[{phase}] {current}/{total} {filename}",
                phase=phase, current=current, total=total, file=filename,
            )
        return cb


def _setup_stdio():
    """パイプ経由の呼び出し（エージェント等）で日本語が壊れないよう UTF-8 に固定する。

    コンソール直結 (tty) のときは WriteConsoleW 経由で日本語が表示できるため
    触らない。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ============================================================
# trim コマンド
# ============================================================

def _parse_margins(text):
    """"L,R,T,B" 形式を (left, right, top, bottom) にパースする。不正なら None。"""
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        values = tuple(int(p.strip()) for p in parts)
    except ValueError:
        return None
    if any(v < 0 for v in values):
        return None
    return values


def cmd_trim(args, rep):
    from core.pipeline import check_input_folder, run_trim

    # 入力検証 → 引数パース の順序を保つため、フォルダ検証を先に行う
    # (run_trim 内でも同じ検証が走るが冪等)
    input_folder = os.path.abspath(args.input)
    code = check_input_folder(input_folder, rep.event)
    if code is not None:
        return code

    margins = None
    if args.margins:
        margins = _parse_margins(args.margins)
        if margins is None:
            rep.error(f"--margins は L,R,T,B の4整数で指定してください: {args.margins}")
            return EXIT_BAD_ARGS
    min_margins = None
    if args.min_margins:
        min_margins = _parse_margins(args.min_margins)
        if min_margins is None:
            rep.error(f"--min-margins は L,R,T,B の4整数で指定してください: {args.min_margins}")
            return EXIT_BAD_ARGS

    return run_trim(
        input_folder, args.output,
        margins=margins, safety=args.safety, min_margins=min_margins,
        no_check=args.no_check, force=args.force,
        overwrite=args.overwrite, dry_run=args.dry_run,
        passthrough=args.passthrough, threshold=args.threshold,
        ui_bands=args.ui_bands,
        emit=rep.event,
    )


# ============================================================
# convert コマンド
# ============================================================

def _build_preprocess_opts(cfg, args):
    pp = dict(cfg.get("ocr", {}).get("preprocess", {}))
    if args.no_preprocess:
        pp["enabled"] = False
    if args.upscale is not None:
        pp["upscale"] = args.upscale
    return pp


def _build_replacements_opts(cfg, args):
    rp = dict(cfg.get("ocr", {}).get("replacements", {}))
    if args.no_replacements:
        rp["enabled"] = False
    if args.replacements_path:
        rp["path"] = args.replacements_path
    return rp


def cmd_convert(args, rep):
    from core.config import load_config
    from core.pipeline import run_convert

    cfg = load_config()
    return run_convert(
        args.input, args.output, args.format, name=args.name, config=cfg,
        preprocess_opts=_build_preprocess_opts(cfg, args),
        replacements_opts=_build_replacements_opts(cfg, args),
        ocr_workers=args.ocr_workers,
        no_bookmarks=args.no_bookmarks,
        no_reflow=args.no_reflow,
        faithful=args.faithful,
        no_cleanup=args.no_cleanup,
        source=args.source,
        embed_images=args.embed_images,
        split_words=args.split_words,
        emit=rep.event,
    )


# ============================================================
# capture コマンド
# ============================================================

def cmd_capture(args, rep):
    from core.capture_profiles import get_profile
    from core.capture_runner import run_capture
    from core.config import load_config

    config = load_config()
    profile = get_profile(args.profile, config)
    if profile is None:
        rep.error(f"プロファイルが見つかりません: {args.profile}（profiles コマンドで一覧表示）")
        return EXIT_BAD_ARGS

    return run_capture(
        profile, args.title, args.output,
        profile_key=args.profile,
        page_turn=args.page_turn, page_wait=args.page_wait,
        max_pages=args.max_pages, overwrite=args.overwrite,
        emit=rep.event,
    )


# ============================================================
# pdf コマンド (外部PDF → 画像展開)
# ============================================================

def cmd_pdf(args, rep):
    """外部PDF（自炊スキャン・購入済PDF）を1ページずつ画像に展開する。

    キャプチャの代わりとなる「もうひとつの入力源」。出力フォルダは
    そのまま trim / convert に流せる（GUI の PDF読込タブと同じ処理）。
    """
    from core.image_files import list_images
    from core.pdf_extractor import extract_pdf_to_images
    from core.pipeline import clear_output_images

    pdf_path = os.path.abspath(args.input)
    if not os.path.isfile(pdf_path):
        rep.error(f"PDFファイルが見つかりません: {pdf_path}")
        return EXIT_BAD_ARGS
    if args.dpi <= 0:
        rep.error(f"--dpi は正の整数で指定してください: {args.dpi}")
        return EXIT_BAD_ARGS

    # 既定の出力先は GUI の PDF読込タブと同じ <PDF名>_pages
    output = os.path.abspath(
        args.output
        or os.path.join(
            os.path.dirname(pdf_path),
            os.path.splitext(os.path.basename(pdf_path))[0] + "_pages",
        )
    )

    # 前回の残骸画像が後段の PDF/OCR に紛れ込まないよう、capture と同じ検査を通す
    code = clear_output_images(output, args.overwrite, rep.event)
    if code is not None:
        return code

    ok, result = extract_pdf_to_images(
        pdf_path, output, dpi=args.dpi, image_format=args.format,
        on_progress=rep.progress("pdf"),
    )
    if not ok:
        rep.error(result)
        return EXIT_ERROR

    pages = len(list_images(output))
    rep.event(
        "result",
        human=f"展開完了: {pages}ページ → {output}",
        ok=True, output=output, pages=pages,
    )
    return EXIT_OK


# ============================================================
# open コマンド
# ============================================================

def cmd_open(args, rep):
    """Kindle Cloud Reader で本を開き、全画面化して先頭ページに合わせる。

    注意: 先頭ページへの巻き戻しは Kindle の読書位置 (Whispersync) を動かす。
    """
    from core.capture_profiles import get_profile
    from core.config import load_config
    from core.reader_navigator import open_book

    config = load_config()
    profile = get_profile(args.profile, config)
    if profile is None:
        rep.error(f"プロファイルが見つかりません: {args.profile}")
        return EXIT_BAD_ARGS

    return open_book(
        profile, asin=args.asin, url=args.url, page_turn=args.page_turn,
        no_fullscreen=args.no_fullscreen, no_rewind=args.no_rewind,
        max_rewind=args.max_rewind, load_wait=args.load_wait,
        emit=rep.event,
    )


# ============================================================
# run コマンド (1冊通し実行)
# ============================================================

def cmd_run(args, rep):
    from core.pipeline import run_book

    min_margins = None
    if args.min_margins:
        min_margins = _parse_margins(args.min_margins)
        if min_margins is None:
            rep.error(f"--min-margins は L,R,T,B の4整数で指定してください: {args.min_margins}")
            return EXIT_BAD_ARGS

    return run_book(
        title=args.title, output=args.output, profile_key=args.profile,
        asin=args.asin, url=args.url, fmt=args.format,
        page_turn=args.page_turn, page_wait=args.page_wait,
        expect_pages=args.expect_pages, max_pages=args.max_pages,
        max_rewind=args.max_rewind, load_wait=args.load_wait,
        no_rewind=args.no_rewind, safety=args.safety, min_margins=min_margins,
        ui_bands=args.ui_bands,
        overwrite=args.overwrite, ocr_workers=args.ocr_workers,
        faithful=args.faithful, no_cleanup=args.no_cleanup,
        split_words=args.split_words,
        emit=rep.event,
    )


# ============================================================
# batch コマンド (複数冊を一括実行)
# ============================================================

def cmd_batch(args, rep):
    from core.config import load_config
    from core.pipeline import load_batch_file, run_batch

    min_margins = None
    if args.min_margins:
        min_margins = _parse_margins(args.min_margins)
        if min_margins is None:
            rep.error(f"--min-margins は L,R,T,B の4整数で指定してください: {args.min_margins}")
            return EXIT_BAD_ARGS

    books, code = load_batch_file(args.books, rep.event)
    if code is not None:
        return code

    # CLI フラグはバッチ全体の既定。本ごとの JSON 設定がこれを上書きする
    defaults = {
        "profile_key": args.profile,
        "fmt": args.format,
        "page_turn": args.page_turn,
        "page_wait": args.page_wait,
        "expect_pages": args.expect_pages,
        "max_pages": args.max_pages,
        "max_rewind": args.max_rewind,
        "load_wait": args.load_wait,
        "no_rewind": args.no_rewind,
        "safety": args.safety,
        "min_margins": min_margins,
        "ui_bands": args.ui_bands,
        "ocr_workers": args.ocr_workers,
        "faithful": args.faithful,
        "no_cleanup": args.no_cleanup,
        "split_words": args.split_words,
    }
    return run_batch(
        books, output=args.output, defaults=defaults,
        overwrite=args.overwrite, stop_on_error=args.stop_on_error,
        config=load_config(), emit=rep.event,
    )


# ============================================================
# validate コマンド
# ============================================================

def cmd_validate(args, rep):
    from core.pipeline import run_validate

    return run_validate(
        args.input, expect_pages=args.expect_pages, strict=args.strict,
        emit=rep.event,
    )


# ============================================================
# check / profiles コマンド
# ============================================================

def cmd_check(args, rep):
    checks = []

    from core import ocr_engine
    ocr_ok, ocr_msg = ocr_engine.is_available()
    checks.append(("ocr", ocr_ok, ocr_msg))

    for mod in ("cv2", "PIL", "numpy", "reportlab", "pyautogui", "customtkinter"):
        try:
            __import__(mod)
            checks.append((f"module:{mod}", True, "OK"))
        except Exception as e:
            checks.append((f"module:{mod}", False, str(e)))

    window_code = None
    if args.profile:
        from core.capture_engine import CaptureEngine
        from core.capture_profiles import get_profile
        from core.capture_runner import find_verified_window
        from core.config import load_config

        config = load_config()
        profile = get_profile(args.profile, config)
        if profile is None:
            checks.append(("profile", False, f"プロファイルが見つかりません: {args.profile}"))
            window_code = EXIT_BAD_ARGS
        else:
            checks.append(("profile", True, f"{args.profile} ({profile.name})"))
            engine = CaptureEngine(profile, exclude_pid=os.getpid())
            hwnd, err = find_verified_window(engine, profile, rep.event)
            if err is not None:
                checks.append(("window", False, "対象ウィンドウが見つかりません"))
                window_code = err
            else:
                checks.append(("window", True, "検出OK"))

    all_ok = all(ok for _, ok, _ in checks)
    for name, ok, msg in checks:
        mark = "OK" if ok else "NG"
        rep.event("check", human=f"[{mark}] {name}: {msg}",
                  name=name, ok=ok, message=msg)
    rep.event("result", human=("環境チェック: すべてOK" if all_ok else "環境チェック: 問題あり"),
              ok=all_ok)

    if window_code is not None:
        return window_code
    if not ocr_ok:
        return EXIT_OCR_UNAVAILABLE
    return EXIT_OK if all_ok else EXIT_ERROR


def cmd_profiles(args, rep):
    from core.capture_profiles import get_all_profile_keys, get_profile
    from core.config import load_config

    config = load_config()
    for key in get_all_profile_keys(config):
        profile = get_profile(key, config)
        if profile is None:
            continue
        data = profile.to_dict()
        rep.event(
            "profile",
            human=(
                f"{key}: {data['name']} "
                f"(window='{data['window_title_keyword']}', "
                f"process='{data['process_name'] or '-'}', "
                f"page_wait={data['page_wait']})"
            ),
            key=key, **data,
        )
    return EXIT_OK


# ============================================================
# エントリポイント
# ============================================================

def build_parser():
    parser = argparse.ArgumentParser(
        prog="kindle_shot",
        description="電子書籍キャプチャ画像のトリミング・PDF/Markdown 変換 CLI",
    )
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--json", action="store_true",
        help="進捗と結果を JSON Lines で出力する（エージェント・スクリプト向け）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_open = sub.add_parser(
        "open", parents=[common],
        help="Kindle Cloud Reader で本を開き、全画面化して先頭ページに合わせる"
             "（注意: 読書位置 Whispersync が先頭に移動する）",
    )
    src = p_open.add_mutually_exclusive_group(required=True)
    src.add_argument("--asin", metavar="ASIN",
                     help="本の ASIN（read.amazon.co.jp/?asin=<ASIN> を開く）")
    src.add_argument("--url", metavar="URL", help="開く URL を直接指定")
    p_open.add_argument("--profile", default="kindle_cloud", metavar="KEY",
                        help="キャプチャプロファイル（既定: kindle_cloud）")
    p_open.add_argument("--page-turn", choices=list(PAGE_TURN_KEYS),
                        help="次ページのキー（right/left/pagedown/pageup/down/up。"
                             "ブラウザ型ビューアの上下めくりは pagedown。"
                             "巻き戻しはその逆を押す。既定はプロファイルの値）")
    p_open.add_argument("--no-fullscreen", action="store_true",
                        help="全画面化（Windows: F11 / macOS: Control+Command+F）をスキップ")
    p_open.add_argument("--no-rewind", action="store_true",
                        help="先頭ページへの巻き戻しをスキップ（現在位置から開始）")
    p_open.add_argument("--max-rewind", type=int, default=1000, metavar="N",
                        help="巻き戻しキーを押す回数の上限（既定: 1000）")
    p_open.add_argument("--load-wait", type=int, default=45, metavar="SEC",
                        help="ページ読み込み完了を待つ最大秒数（既定: 45）")
    p_open.set_defaults(func=cmd_open)

    p_run = sub.add_parser(
        "run", parents=[common],
        help="1冊を通しで実行: open → capture → validate → trim → convert",
    )
    p_run.add_argument("--title", required=True,
                       help="タイトル（保存フォルダ名・出力ファイル名になる）")
    p_run.add_argument("--out", dest="output", required=True, metavar="FOLDER",
                       help="保存先フォルダ")
    p_run.add_argument("--asin", metavar="ASIN",
                       help="指定すると Cloud Reader で本を開くところから実行")
    p_run.add_argument("--url", metavar="URL", help="開く URL を直接指定")
    p_run.add_argument("--profile", default="kindle_cloud", metavar="KEY",
                       help="キャプチャプロファイル（既定: kindle_cloud）")
    p_run.add_argument("--format", default="searchable_pdf", choices=FORMATS,
                       help="出力形式（既定: searchable_pdf）")
    p_run.add_argument("--page-turn", choices=list(PAGE_TURN_KEYS),
                       help="次ページのキー（right/left/pagedown/pageup/down/up。"
                            "ブラウザ型ビューアの上下めくりは pagedown）")
    p_run.add_argument("--page-wait", type=float, metavar="SEC",
                       help="ページ変化検出のポーリング間隔を上書き"
                            "（画像の描画が遅い場合は長めにする）")
    p_run.add_argument("--expect-pages", type=int, metavar="N",
                       help="validate で確認する期待ページ数")
    p_run.add_argument("--max-pages", type=int, metavar="N",
                       help="キャプチャの上限ページ数（暴走防止）")
    p_run.add_argument("--max-rewind", type=int, default=1000, metavar="N",
                       help="open の巻き戻し上限（既定: 1000）")
    p_run.add_argument("--load-wait", type=int, default=45, metavar="SEC",
                       help="open の読み込み待ち最大秒数（既定: 45）")
    p_run.add_argument("--no-rewind", action="store_true",
                       help="先頭ページへの巻き戻しをスキップ")
    p_run.add_argument("--safety", type=int, default=8, metavar="PX",
                       help="トリミング自動検出の安全マージン（既定: 8px）")
    p_run.add_argument("--min-margins", metavar="L,R,T,B",
                       help="トリミングで最低限削る余白（kindle_cloud の既定: 0,0,80,80。"
                            "ビューアの常時表示UIの除去用）")
    p_run.add_argument("--no-ui-bands", dest="ui_bands", action="store_false",
                       help="ページ間の変化からビューアの固定UI帯（書名ヘッダー・"
                            "ページ番号フッター）を検出して削る処理を無効にする"
                            "（既定は有効）")
    p_run.add_argument("--overwrite", action="store_true",
                       help="保存先・トリミング先の既存画像を削除してから実行")
    p_run.add_argument("--ocr-workers", type=int, metavar="N",
                       help="ndlocr-lite の並列プロセス数（既定: config の ocr.workers）")
    p_run.add_argument("--faithful", action="store_true",
                       help="--format markdown 時にページ忠実型で出力（既定は NotebookLM 最適化）")
    p_run.add_argument("--no-cleanup", action="store_true",
                       help="--format markdown 時の行内クリーニングを無効化")
    p_run.add_argument("--split-words", type=int, metavar="N",
                       help="--format markdown 時、推定 N 語を超えたら章境界優先で "
                            "<title>_1.md, _2.md… に分割（NotebookLM の1ソース"
                            "50万語制限対策。faithful 時は無効）")
    p_run.set_defaults(func=cmd_run)

    p_batch = sub.add_parser(
        "batch", parents=[common],
        help="複数冊を JSON リストから一括で通し実行する（各本を run と同じ手順で処理）",
    )
    p_batch.add_argument("--books", required=True, metavar="FILE",
                         help="本リストの JSON ファイル。"
                              "本オブジェクトの配列 [{\"asin\":..,\"title\":..}, ..] または "
                              "{\"books\": [..]} 形式。asin/url 以外に title・format・"
                              "max_pages・page_turn 等を本ごとに指定できる")
    p_batch.add_argument("--out", dest="output", required=True, metavar="FOLDER",
                         help="全本共通の保存先フォルダ（直下に <title>.pdf/.md が並ぶ）")
    p_batch.add_argument("--profile", default="kindle_cloud", metavar="KEY",
                         help="キャプチャプロファイル（全本の既定。既定: kindle_cloud）")
    p_batch.add_argument("--format", default="searchable_pdf", choices=FORMATS,
                         help="出力形式（全本の既定。既定: searchable_pdf）")
    p_batch.add_argument("--page-turn", choices=list(PAGE_TURN_KEYS),
                         help="次ページのキー（全本の既定。right/left/pagedown/"
                              "pageup/down/up。ブラウザ型ビューアの上下めくりは"
                              " pagedown）")
    p_batch.add_argument("--page-wait", type=float, metavar="SEC",
                         help="ページ変化検出のポーリング間隔（全本の既定）")
    p_batch.add_argument("--expect-pages", type=int, metavar="N",
                         help="validate で確認する期待ページ数（全本の既定）")
    p_batch.add_argument("--max-pages", type=int, metavar="N",
                         help="キャプチャの上限ページ数（全本の既定・暴走防止）")
    p_batch.add_argument("--max-rewind", type=int, default=1000, metavar="N",
                         help="open の巻き戻し上限（全本の既定。既定: 1000）")
    p_batch.add_argument("--load-wait", type=int, default=45, metavar="SEC",
                         help="open の読み込み待ち最大秒数（全本の既定。既定: 45）")
    p_batch.add_argument("--no-rewind", action="store_true",
                         help="先頭ページへの巻き戻しをスキップ（全本の既定）")
    p_batch.add_argument("--safety", type=int, default=8, metavar="PX",
                         help="トリミング自動検出の安全マージン（全本の既定。既定: 8px）")
    p_batch.add_argument("--min-margins", metavar="L,R,T,B",
                         help="トリミングで最低限削る余白（全本の既定）")
    p_batch.add_argument("--no-ui-bands", dest="ui_bands", action="store_false",
                         help="ページ間の変化からビューアの固定UI帯（書名ヘッダー・"
                              "ページ番号フッター）を検出して削る処理を無効にする"
                              "（既定は有効・全本の既定）")
    p_batch.add_argument("--ocr-workers", type=int, metavar="N",
                         help="ndlocr-lite の並列プロセス数（全本の既定）")
    p_batch.add_argument("--faithful", action="store_true",
                         help="--format markdown 時にページ忠実型で出力（全本の既定）")
    p_batch.add_argument("--no-cleanup", action="store_true",
                         help="--format markdown 時の行内クリーニングを無効化（全本の既定）")
    p_batch.add_argument("--split-words", type=int, metavar="N",
                         help="--format markdown 時、推定 N 語を超えたら章境界優先で "
                              "<title>_1.md, _2.md… に分割（全本の既定）")
    p_batch.add_argument("--overwrite", action="store_true",
                         help="完成済み（出力ファイルがある）本も再処理する。"
                              "既定は完成済みをスキップして途中から再開")
    p_batch.add_argument("--stop-on-error", action="store_true",
                         help="1冊でも失敗したらバッチを中断する（既定は続行して末尾に一覧）")
    p_batch.set_defaults(func=cmd_batch)

    p_cap = sub.add_parser(
        "capture", parents=[common],
        help="電子書籍ビューアのページを自動キャプチャする（本を開いて先頭ページを表示しておくこと）",
    )
    p_cap.add_argument("--profile", required=True, metavar="KEY",
                       help="キャプチャプロファイル（profiles コマンドで一覧表示）")
    p_cap.add_argument("--title", required=True,
                       help="タイトル（保存先のサブフォルダ名になる）")
    p_cap.add_argument("--out", dest="output", required=True, metavar="FOLDER",
                       help="保存先フォルダ（この下に <title>/ が作られる）")
    p_cap.add_argument("--page-turn", choices=list(PAGE_TURN_KEYS),
                       help="ページめくりキー（省略時はプロファイルの値。"
                            "right/left/pagedown/pageup/down/up。漫画は left、"
                            "ブラウザ型ビューアの上下めくりは pagedown）")
    p_cap.add_argument("--page-wait", type=float, metavar="SEC",
                       help="ページ変化検出のポーリング間隔を上書き")
    p_cap.add_argument("--max-pages", type=int, metavar="N",
                       help="このページ数に達したら停止する（暴走防止の上限）")
    p_cap.add_argument("--overwrite", action="store_true",
                       help="保存先の既存画像を削除してから実行する")
    p_cap.set_defaults(func=cmd_capture)

    p_pdf = sub.add_parser(
        "pdf", parents=[common],
        help="外部PDFを1ページずつ画像に展開する（trim / convert の入力を作る）",
    )
    p_pdf.add_argument("--in", dest="input", required=True, metavar="PDF",
                       help="入力PDFファイル")
    p_pdf.add_argument("--out", dest="output", metavar="FOLDER",
                       help="出力フォルダ（省略時: PDF と同じ場所の <PDF名>_pages）")
    p_pdf.add_argument("--dpi", type=int, default=200, metavar="N",
                       help="レンダリング解像度（既定: 200。OCR 目的なら 200〜300）")
    p_pdf.add_argument("--format", default="png", choices=["png", "jpg"],
                       help="画像形式（既定: png）")
    p_pdf.add_argument("--overwrite", action="store_true",
                       help="出力フォルダの既存画像を削除してから実行する")
    p_pdf.set_defaults(func=cmd_pdf)

    p_trim = sub.add_parser(
        "trim", parents=[common],
        help="画像フォルダの余白を一括トリミングする",
    )
    p_trim.add_argument("--in", dest="input", required=True, metavar="FOLDER",
                        help="入力画像フォルダ")
    p_trim.add_argument("--out", dest="output", metavar="FOLDER",
                        help="出力フォルダ（--dry-run 時は省略可）")
    group = p_trim.add_mutually_exclusive_group(required=True)
    group.add_argument("--margins", metavar="L,R,T,B",
                       help="余白ピクセルを直接指定（例: 100,100,80,120）")
    group.add_argument("--auto", action="store_true",
                       help="全ページ走査で余白を自動検出する")
    p_trim.add_argument("--safety", type=int, default=8, metavar="PX",
                        help="--auto 時に検出値から差し引く安全マージン（既定: 8px）")
    p_trim.add_argument("--min-margins", metavar="L,R,T,B",
                        help="--auto 時に最低限削る余白。ビューアの常時表示UI"
                             "（書名ヘッダー・ページ番号フッター）の除去に使う")
    p_trim.add_argument("--no-ui-bands", dest="ui_bands", action="store_false",
                        help="--auto 時に、ページ間の変化からビューアの固定UI帯"
                             "（書名ヘッダー・ページ番号フッター）を検出して削る"
                             "処理を無効にする（既定は有効）")
    p_trim.add_argument("--threshold", type=int, default=12, metavar="PX",
                        help="背景との輝度差しきい値（既定: 12）。"
                             "余白検出と全面表示ページの判定に使う")
    p_trim.add_argument("--passthrough", dest="passthrough", action="store_true",
                        default=None,
                        help="全面表示と判定したページ（本文と余白構成が大きく異なる"
                             "表紙・購入画面など）を無加工でコピーする。"
                             "既定は --auto 時 ON / --margins 時 OFF")
    p_trim.add_argument("--no-passthrough", dest="passthrough", action="store_false",
                        help="全面表示ページも共通マージンでトリミングする")
    p_trim.add_argument("--no-check", action="store_true",
                        help="--margins 指定時の「内容が切れないか」検証をスキップ")
    p_trim.add_argument("--force", action="store_true",
                        help="内容が切れるページがあっても実行する")
    p_trim.add_argument("--overwrite", action="store_true",
                        help="出力フォルダの既存画像を削除してから実行する")
    p_trim.add_argument("--dry-run", action="store_true",
                        help="マージンの決定と検証だけ行い、トリミングは実行しない")
    p_trim.set_defaults(func=cmd_trim)

    p_conv = sub.add_parser(
        "convert", parents=[common],
        help="画像フォルダを PDF / Markdown に変換する（必要に応じて OCR）",
    )
    p_conv.add_argument("--in", dest="input", required=True, metavar="FOLDER",
                        help="入力画像フォルダ")
    p_conv.add_argument("--out", dest="output", required=True, metavar="FOLDER",
                        help="出力フォルダ")
    p_conv.add_argument("--format", required=True, choices=FORMATS,
                        help="出力形式")
    p_conv.add_argument("--name", metavar="FILENAME",
                        help="出力ファイル名（省略時は入力フォルダ名）")
    p_conv.add_argument("--no-preprocess", action="store_true",
                        help="OCR 前処理（アップスケール・コントラスト強調）を無効化")
    p_conv.add_argument("--upscale", type=float, metavar="X",
                        help="OCR 前処理の拡大倍率を上書き（例: 1.5）")
    p_conv.add_argument("--no-replacements", action="store_true",
                        help="OCR 後の置換辞書適用を無効化")
    p_conv.add_argument("--replacements-path", metavar="PATH",
                        help="置換辞書 JSON のパスを上書き")
    p_conv.add_argument("--no-bookmarks", action="store_true",
                        help="章しおりの自動検出・埋め込みを無効化")
    p_conv.add_argument("--no-reflow", action="store_true",
                        help="Markdown 出力時の段落自動整形を無効化（--faithful 時のみ有効）")
    p_conv.add_argument("--faithful", action="store_true",
                        help="Markdown をページ忠実型で出力（<!-- page -->・--- を残す）。"
                             "既定は NotebookLM 最適化（ページまたぎ結合・マーカー除去・H1書名/H2章）")
    p_conv.add_argument("--no-cleanup", action="store_true",
                        help="Markdown 出力時の行内クリーニング（句読点直後の余分な空白除去等）を無効化")
    p_conv.add_argument("--source", metavar="TEXT",
                        help="Markdown フロントマターに記録する出典情報（ASIN 等）")
    p_conv.add_argument("--embed-images", action="store_true",
                        help="Markdown 出力時にページ画像を併記する（--faithful 時のみ）")
    p_conv.add_argument("--ocr-workers", type=int, metavar="N",
                        help="ndlocr-lite の並列プロセス数（既定: config の ocr.workers。"
                             "CPU 推論は 1 プロセスで全コアを使うため通常 1 が最速）")
    p_conv.add_argument("--split-words", type=int, metavar="N",
                        help="Markdown 出力時、推定 N 語を超えたら章境界優先で "
                             "<名前>_1.md, _2.md… に分割（NotebookLM の1ソース"
                             "50万語制限対策。--faithful 時は無効）")
    p_conv.set_defaults(func=cmd_convert)

    p_val = sub.add_parser(
        "validate", parents=[common],
        help="キャプチャ結果を機械検証する（白紙・重複・サイズ違い・ページ数）",
    )
    p_val.add_argument("--in", dest="input", required=True, metavar="FOLDER",
                       help="検証する画像フォルダ")
    p_val.add_argument("--expect-pages", type=int, metavar="N",
                       help="期待ページ数（実際のページ数がこれ未満ならエラー）")
    p_val.add_argument("--strict", action="store_true",
                       help="警告 (白紙・重複・サイズ違い) もエラー扱いにする")
    p_val.set_defaults(func=cmd_validate)

    p_chk = sub.add_parser(
        "check", parents=[common],
        help="環境診断（OCR エンジン・依存パッケージ・対象ウィンドウ）",
    )
    p_chk.add_argument("--profile", metavar="KEY",
                       help="指定するとキャプチャ対象ウィンドウの検出まで確認する")
    p_chk.set_defaults(func=cmd_check)

    p_prof = sub.add_parser(
        "profiles", parents=[common],
        help="利用可能なキャプチャプロファイルを一覧表示する",
    )
    p_prof.set_defaults(func=cmd_profiles)

    return parser


def main(argv=None):
    _setup_stdio()

    # DPI 認識はモジュール先頭で確定済み（冒頭のコメント参照）。ここで呼んでも
    # 手遅れになる（pyautogui のロードが先に走るため）ので呼ばない。
    parser = build_parser()
    args = parser.parse_args(argv)
    rep = Reporter(as_json=args.json)
    try:
        return args.func(args, rep)
    except KeyboardInterrupt:
        rep.error("中断されました")
        return EXIT_ERROR
    except Exception as e:
        rep.error(f"予期しないエラー: {e}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
