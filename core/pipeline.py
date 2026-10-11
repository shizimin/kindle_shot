"""処理パイプライン（トリミング・変換・検証のオーケストレーション）

CLI (cli.py) と GUI (ui/) の両方から呼ばれる共通のワークフロー実装。
以前は同じ手順が CLI と GUI に別々に実装されており、挙動が食い違っていた
(トリミングの緩め方・Markdown の既定形式など)。ここに一本化する。

## emit コールバック

各 run_* 関数は ``emit(event, human=None, **fields)`` を受け取る。
- CLI は Reporter.event をそのまま渡す (JSON Lines / 人間向けテキスト)
- GUI は ui.tab_utils.GuiEmitter を渡す (ログ・進捗バーへ写像)

イベント名・フィールド・human 文字列は CLI の JSON Lines 契約
(エージェント自動化が依存) なので、変更しないこと。

## 終了コード

run_* は int の終了コードを返す。CLI はそのままプロセス終了コードに、
GUI は 0 / 非 0 で成否を判定する。
"""

import json
import os

from core.capture_profiles import PAGE_TURN_KEYS
from core.image_files import clear_images, list_images

# 終了コード (cli.py の契約。README の CLI セクション参照)
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_ARGS = 2
EXIT_WINDOW_NOT_FOUND = 3
EXIT_OCR_UNAVAILABLE = 4
EXIT_NO_IMAGES = 5
EXIT_WOULD_CLIP = 6
EXIT_VALIDATION = 7

# 出力形式の候補（CLI の choices・batch ファイルの format 検証で共有）
FORMATS = ("image_pdf", "text_pdf", "searchable_pdf", "markdown")


def null_emit(event, human=None, **fields):
    """emit 省略時の何もしないコールバック。"""


def emit_error(emit, message):
    """Reporter.error と同形の error イベントを発行する。"""
    emit("error", human=f"エラー: {message}", message=message)


def phase_progress(emit, phase):
    """Reporter.progress と同形の progress イベントを発行する on_progress を作る。"""
    def cb(current, total, filename):
        emit(
            "progress",
            human=f"[{phase}] {current}/{total} {filename}",
            phase=phase, current=current, total=total, file=filename,
        )
    return cb


def _ensure_ext(filename, ext):
    """ファイル名に拡張子がなければ付与する。"""
    if not filename.lower().endswith(ext):
        filename += ext
    return filename


def _margins_str(margins):
    """(L,R,T,B) を "L,R,T,B" 文字列にする (イベント表示用)。None はそのまま。"""
    if margins is None:
        return None
    return ",".join(str(v) for v in margins)


def relax_margins(raw, safety=8, min_margins=None):
    """検出された余白から実際に削るマージンを決める（CLI/GUI 共通の唯一の式）。

    検出値から安全マージンを差し引いて「検出できた内容はどのページでも
    切らない」ことを保証しつつ、ビューアの常時表示 UI (書名ヘッダー・
    ページ番号フッター等) は min_margins で最低限削る。

    Args:
        raw: 検出された余白 (left, right, top, bottom)
        safety: 各辺から差し引く安全マージン (px)
        min_margins: 最低限削る余白 (left, right, top, bottom)。None なら適用しない

    Returns:
        (left, right, top, bottom) のタプル
    """
    margins = tuple(max(0, v - safety) for v in raw)
    if min_margins:
        margins = tuple(max(m, mn) for m, mn in zip(margins, min_margins, strict=True))
    return margins


def check_input_folder(input_folder, emit=null_emit):
    """入力フォルダの存在と画像の有無を検証する。

    Returns:
        問題なければ None、あれば終了コード (EXIT_BAD_ARGS / EXIT_NO_IMAGES)
    """
    if not os.path.isdir(input_folder):
        emit_error(emit, f"入力フォルダが見つかりません: {input_folder}")
        return EXIT_BAD_ARGS
    if not list_images(input_folder):
        emit_error(emit, f"入力フォルダに画像がありません: {input_folder}")
        return EXIT_NO_IMAGES
    return None


def clear_output_images(folder, overwrite, emit=null_emit, *,
                        label="出力フォルダ", reason=""):
    """出力先の既存画像を検査し、overwrite 指定があれば削除する。

    前回実行の残骸画像が混ざると後段の PDF 化で古いページが紛れ込むため、
    既存画像がある場合は overwrite なしでは中止する。

    Returns:
        問題なければ None、中止なら EXIT_BAD_ARGS
    """
    if not os.path.isdir(folder):
        return None
    existing = list_images(folder)
    if not existing:
        return None
    if not overwrite:
        emit_error(
            emit,
            f"{label}に既存の画像が {len(existing)} 枚あります: {folder}"
            f"（{reason}--overwrite で消去して実行）"
        )
        return EXIT_BAD_ARGS
    removed = clear_images(folder)
    emit(
        "cleaned_output",
        human=f"{label}の既存画像 {removed} 枚を削除しました",
        removed=removed,
    )
    return None


# ============================================================
# trim
# ============================================================

def _clipped_human(clipped):
    """clipped_pages イベントの human 文面を組み立てる。"""
    return "以下のページで内容が切れます:\n" + "\n".join(
        f"  {c['filename']}: " + ", ".join(
            f"{side} {px}px 不足" for side, px in c["sides"].items()
        ) for c in clipped
    )


def run_trim(input_folder, output_folder=None, *, margins=None, safety=8,
             min_margins=None, no_check=False, force=False, overwrite=False,
             dry_run=False, passthrough=None, threshold=12, ui_bands=True,
             emit=null_emit):
    """画像フォルダの余白を一括トリミングする。

    Args:
        input_folder: 入力画像フォルダ
        output_folder: 出力フォルダ (dry_run 時は省略可)
        margins: (L,R,T,B) の直接指定。None なら全ページ走査で自動検出
        safety: 自動検出時に検出値から差し引く安全マージン (px)
        min_margins: 自動検出時に最低限削る余白 (L,R,T,B)
        no_check: 直接指定時の「内容が切れないか」検証をスキップ
        force: 内容が切れるページがあっても実行する
        overwrite: 出力フォルダの既存画像を削除してから実行する
        dry_run: マージンの決定と検証だけ行い、トリミングは実行しない
        passthrough: 全面表示と判定したページ (余白の外れ値ページ＝表紙・
            購入画面など) を無加工コピーで出力する。None なら経路ごとの既定
            (自動検出=True / margins 直接指定=False)。判定は余白の分布に
            基づくため、min_margins や手動で上げたマージン値とは独立
        threshold: 背景との輝度差しきい値 (検出・外れ値判定に共通で使う)
        ui_bands: 自動検出時に、ページ間の変化からビューアの固定 UI 帯
            (書名ヘッダー・ページ番号フッター等) を検出して併用する
        emit: イベントコールバック

    Returns:
        終了コード
    """
    from core.boundary_detector import (
        VARIATION_MAX_MARGIN_RATIO,
        aggregate_margins,
        clipped_pages_from,
        combine_margins,
        folder_page_margins,
        page_variation_margins,
        variation_applied,
    )
    from core.trimmer import process_images

    input_folder = os.path.abspath(input_folder)
    code = check_input_folder(input_folder, emit)
    if code is not None:
        return code

    if not dry_run and not output_folder:
        emit_error(emit, "--out が必要です（確認だけなら --dry-run を指定）")
        return EXIT_BAD_ARGS

    # --- マージンの決定 ---
    manual = margins is not None
    if passthrough is None:
        # 自動検出は表紙・購入画面が混ざる前提なので既定 ON。
        # 直接指定は従来どおり「切れるなら中止」を既定にする
        passthrough = not manual
    passthrough_files = set()
    pages = None  # [(filename, margins|None), ...] 走査結果 (使い回す)
    report = None

    if not manual:
        # 自動検出: 全ページ走査で共通の安全マージンを検出
        pages = folder_page_margins(
            input_folder, threshold=threshold,
            on_progress=phase_progress(emit, "detect"),
        )
        raw, report = aggregate_margins(pages)
        if raw is None:
            emit_error(emit, "余白を検出できませんでした（全ページ白紙？）")
            return EXIT_ERROR

        # ビューアの固定UI (書名ヘッダー・ページ番号フッター等) は非背景＝
        # 「内容」として検出されるため、内容ベースだけでは削れない。ページ間の
        # 画素変化を見ると、毎ページ同じ絵の UI 帯と本文を分離できる。
        content_raw = raw
        variation = None
        report["content_margins"] = list(content_raw)
        report["variation_margins"] = None
        report["variation"] = None
        applied = (False,) * 4
        if ui_bands:
            variation, vreport = page_variation_margins(
                input_folder, on_progress=phase_progress(emit, "ui_bands"),
            )
            report["variation"] = vreport
            if variation is not None:
                report["variation_margins"] = list(variation)
                raw = combine_margins(content_raw, variation, vreport["size"])
                applied = variation_applied(content_raw, variation, raw)
        report["variation_applied"] = list(applied)

        # min_margins: UI 帯検出が効かないビューア向けの保険として、
        # 最低限削る帯を明示指定できる
        margins = relax_margins(raw, safety=safety, min_margins=min_margins)
        min_margins_str = _margins_str(min_margins)
        outliers = report.get("outliers") or []
        labels = ("左", "右", "上", "下")
        applied_sides = []
        if variation is not None:
            applied_sides = [
                f"{label}={value}"
                for label, value, is_applied in zip(labels, variation, applied,
                                                     strict=True)
                if is_applied
            ]
        ui_note = ""
        if applied_sides:
            ui_note = (
                "\nページ間の変化からビューアのUI帯とみられる部分を除去しました "
                f"({', '.join(applied_sides)})"
            )
        if variation is not None:
            width, height = report["variation"]["size"]
            limits = (width, width, height, height)
            rejected = [
                f"{label}は検出値 {value} が画面の "
                f"{VARIATION_MAX_MARGIN_RATIO * 100:g}% を超えるため採用せず"
                for label, value, length in zip(labels, variation, limits, strict=True)
                if value > length * VARIATION_MAX_MARGIN_RATIO
            ]
            if rejected:
                ui_note += f"（{'、'.join(rejected)}）"
        variation_report = report.get("variation") or {}
        if variation_report.get("reason") == "too_few_pages":
            ui_note += (
                f"\nページ数が {variation_report['min_pages']} 枚未満のため、"
                "ビューアのUI帯の自動検出は行いません"
            )
        emit(
            "margins_detected",
            human=(
                f"余白を検出: 左={margins[0]}, 右={margins[1]}, "
                f"上={margins[2]}, 下={margins[3]} "
                f"(検出値から安全マージン {safety}px を差し引き"
                + (f"、最低マージン {min_margins_str} を適用" if min_margins else "")
                + f" / {report['pages_detected']}/{report['pages_total']} ページ走査"
                + (f" / 全面表示の {len(outliers)} ページを集計から除外" if outliers else "")
                + ")"
                + ui_note
            ),
            margins=list(margins), raw=list(raw),
            safety=safety, min_margins=min_margins_str,
            content_margins=list(content_raw),
            variation_margins=list(variation) if variation is not None else None,
            variation_applied=list(applied),
            report=report,
        )

    # --- パススルー対象の決定 ---
    # 「全面表示（本文と余白構成が大きく異なる）ページ」= 余白集計の外れ値。
    # マージン値そのものとは独立に決めるため、min_margins や手動で上げた
    # マージンで本文ページまで巻き込むことはない
    if passthrough:
        if pages is None:
            pages = folder_page_margins(
                input_folder, threshold=threshold,
                on_progress=phase_progress(emit, "check"),
            )
            _, report = aggregate_margins(pages)
        passthrough_files = set(report.get("outliers") or ())
        if passthrough_files:
            emit(
                "passthrough_pages",
                human="以下のページは全面表示（本文と余白構成が大きく異なる）と"
                      "判定したため無加工でコピーします:\n"
                      + "\n".join(f"  {name}" for name in sorted(passthrough_files)),
                pages=sorted(passthrough_files),
            )

    # --- 内容が切れないかの検証 ---
    # 自動検出の結果は構成上安全（外れ値を除く全ページの最小値以下）なので、
    # 直接指定時のみ検証する。パススルー対象は無加工で出るので対象外
    if manual and not no_check:
        if pages is None:
            pages = folder_page_margins(
                input_folder, threshold=threshold,
                on_progress=phase_progress(emit, "check"),
            )
        clipped = [
            c for c in clipped_pages_from(pages, margins)
            if c["filename"] not in passthrough_files
        ]
        if clipped:
            emit("clipped_pages", human=_clipped_human(clipped), pages=clipped)
            if not force:
                emit_error(emit, "内容が切れるページがあるため中止しました（--force で強行）")
                return EXIT_WOULD_CLIP
    elif not manual and not passthrough:
        # 自動検出 + パススルー無効: 外れ値ページ (表紙・購入画面) は
        # 共通マージンで切れるため、中止はせず情報として通知する
        clipped = clipped_pages_from(pages, margins)
        if clipped:
            emit("clipped_pages", human=_clipped_human(clipped), pages=clipped)

    if dry_run:
        emit(
            "result",
            human=f"dry-run: マージン 左={margins[0]}, 右={margins[1]}, "
                  f"上={margins[2]}, 下={margins[3]}（トリミングは実行していません）",
            ok=True, dry_run=True, margins=list(margins),
            passthrough=len(passthrough_files),
        )
        return EXIT_OK

    # --- 出力フォルダの安全確認 ---
    output_folder = os.path.abspath(output_folder)
    code = clear_output_images(output_folder, overwrite, emit)
    if code is not None:
        return code

    success, message = process_images(
        input_folder, output_folder, *margins,
        on_progress=phase_progress(emit, "trim"),
        passthrough_files=passthrough_files,
    )
    emit(
        "result", human=message,
        ok=success, message=message,
        margins=list(margins), output=output_folder,
        passthrough=len(passthrough_files),
    )
    return EXIT_OK if success else EXIT_ERROR


# ============================================================
# convert
# ============================================================

def run_convert(input_folder, output_folder, fmt, *, name=None, config=None,
                preprocess_opts=None, replacements_opts=None, ocr_workers=None,
                no_bookmarks=False, no_reflow=False, faithful=False,
                no_cleanup=False, source=None, embed_images=False,
                split_words=None, emit=null_emit):
    """画像フォルダを PDF / Markdown に変換する（必要に応じて OCR）。

    Args:
        input_folder: 入力画像フォルダ
        output_folder: 出力フォルダ
        fmt: "image_pdf" | "text_pdf" | "searchable_pdf" | "markdown"
        name: 出力ファイル名 (省略時は入力フォルダ名)
        config: 設定 dict (None なら load_config())
        preprocess_opts: OCR 前処理パラメータ (None なら config から解決)
        replacements_opts: 置換辞書パラメータ (None なら config から解決)
        ocr_workers: ndlocr-lite の並列プロセス数 (None なら config から解決)
        no_bookmarks: 章しおりの自動検出・埋め込みを無効化
        no_reflow: Markdown 段落自動整形を無効化 (faithful 時のみ有効)
        faithful: Markdown をページ忠実型で出力 (既定は NotebookLM 最適化)
        no_cleanup: Markdown の行内クリーニングを無効化
        source: Markdown フロントマターに記録する出典情報 (ASIN 等)
        embed_images: ページ画像を併記 (faithful 時のみ有効)
        split_words: Markdown を推定 N 語ごとに分割出力 (NotebookLM 型のみ。
            超過時に <名前>_1.md, _2.md… へ章境界優先で分割)
        emit: イベントコールバック

    Returns:
        終了コード
    """
    from core import ocr_engine
    from core.chapter_detector import detect_chapters
    from core.config import load_config
    from core.markdown_writer import write_markdown
    from core.pdf_builder import images_to_pdf, images_to_searchable_pdf, text_to_pdf

    input_folder = os.path.abspath(input_folder)
    code = check_input_folder(input_folder, emit)
    if code is not None:
        return code

    output_folder = os.path.abspath(output_folder)
    filename = name or os.path.basename(input_folder.rstrip("\\/"))
    cfg = config if config is not None else load_config()
    extra_fields = {}  # result イベントへの追加フィールド（分割出力時のみ）

    if fmt == "image_pdf":
        filename = _ensure_ext(filename, ".pdf")
        success, message = images_to_pdf(
            input_folder, output_folder, filename,
            on_progress=phase_progress(emit, "pdf"),
        )
        output_path = os.path.join(output_folder, filename)
    else:
        available, msg = ocr_engine.is_available()
        if not available:
            emit_error(emit, msg)
            return EXIT_OCR_UNAVAILABLE

        success, results = ocr_engine.process_folder_collect(
            input_folder,
            on_progress=phase_progress(emit, "ocr"),
            preprocess_opts=preprocess_opts,
            replacements_opts=replacements_opts,
            workers=ocr_workers,
        )
        if not success:
            emit_error(emit, results)
            return EXIT_ERROR

        bookmarks_enabled = bool(
            cfg.get("ocr", {}).get("chapter_bookmarks", {}).get("enabled", True)
        ) and not no_bookmarks

        # Markdown 出力時は行内クリーニング（句読点直後スペース等の除去）を
        # 章検出より前に適用し、見出しと本文の表記を揃える
        if fmt == "markdown" and not no_cleanup:
            from core.text_cleanup import clean_text
            results = [(fn, clean_text(t)) for fn, t in results]

        chapters = detect_chapters(results) if bookmarks_enabled else None

        if fmt == "text_pdf":
            filename = _ensure_ext(filename, ".pdf")
            output_path = os.path.join(output_folder, filename)
            success, message = text_to_pdf(
                results, output_path,
                on_progress=phase_progress(emit, "pdf"), chapters=chapters,
            )
        elif fmt == "searchable_pdf":
            filename = _ensure_ext(filename, ".pdf")
            output_path = os.path.join(output_folder, filename)
            success, message = images_to_searchable_pdf(
                input_folder, results, output_path,
                on_progress=phase_progress(emit, "pdf"), chapters=chapters,
            )
        else:  # markdown
            filename = _ensure_ext(filename, ".md")
            output_path = os.path.join(output_folder, filename)
            book_title = os.path.splitext(os.path.basename(filename))[0]
            if faithful:
                # ページ忠実型（原画像へ戻る導線を残す従来出力）
                reflow = bool(cfg.get("ocr", {}).get("reflow_paragraphs", True)) \
                    and not no_reflow
                success, message = write_markdown(
                    results, output_path, title=book_title,
                    reflow=reflow, chapters=chapters,
                    embed_images=embed_images,
                    image_folder=input_folder if embed_images else None,
                )
            else:
                # NotebookLM 最適化（既定）: ページまたぎ結合・マーカー除去・H1/H2
                from core.markdown_writer import write_notebooklm_markdown
                success, message, written = write_notebooklm_markdown(
                    results, output_path, title=book_title,
                    source=source, chapters=chapters, split_words=split_words,
                )
                # 分割出力時は <名前>_1.md が実体。result の output もそこを指す
                if success and written:
                    output_path = written[0]
                if success and len(written) > 1:
                    extra_fields = {"outputs": written, "parts": len(written)}

    emit(
        "result", human=message,
        ok=success, message=message,
        format=fmt, output=output_path if success else None,
        **extra_fields,
    )

    # Markdown は NotebookLM の 50万語/200MB 制限に対する分量目安を表示する
    if success and fmt == "markdown":
        from core.text_stats import estimate, format_stats
        st = estimate("\n".join(t for _, t in results))
        emit(
            "markdown_stats", human=format_stats(st),
            chars=st["chars"], words_est=st["words"], bytes=st["bytes"],
        )

    return EXIT_OK if success else EXIT_ERROR


# ============================================================
# run (1冊通し実行)
# ============================================================

def run_book(*, title, output, profile_key="kindle_cloud", asin=None, url=None,
             fmt="searchable_pdf", page_turn=None, page_wait=None,
             expect_pages=None, max_pages=None, max_rewind=1000, load_wait=45,
             no_rewind=False, safety=8, min_margins=None, ui_bands=True,
             overwrite=False, ocr_workers=None, faithful=False,
             no_cleanup=False, split_words=None, config=None, emit=null_emit):
    """1冊を通しで実行する: open → capture → validate → trim → convert。

    asin / url を指定すると Cloud Reader で本を開くところから実行する。
    各ステップの所要時間を計測し、最後に run_summary イベントで報告する。

    Args:
        title: タイトル (保存フォルダ名・出力ファイル名になる)
        output: 保存先フォルダ
        profile_key: キャプチャプロファイルのキー
        min_margins: トリミングで最低限削る余白 (L,R,T,B)。None かつ
            kindle_cloud の場合は書名ヘッダー/ページ番号フッター分 (0,0,80,80)
        ui_bands: ページ間の変化からビューアの固定 UI 帯を検出して併用する
        他の引数は open_book / run_capture / run_validate / run_trim /
        run_convert の同名引数へそのまま渡る。

    Returns:
        終了コード
    """
    import time

    from core.capture_profiles import get_profile
    from core.capture_runner import run_capture
    from core.config import load_config
    from core.reader_navigator import open_book
    from core.win32_utils import allow_sleep, prevent_sleep

    cfg = config if config is not None else load_config()
    profile = get_profile(profile_key, cfg)
    if profile is None:
        emit_error(emit, f"プロファイルが見つかりません: {profile_key}（profiles コマンドで一覧表示）")
        return EXIT_BAD_ARGS

    out = os.path.abspath(output)
    save_dir = os.path.join(out, title)
    trimmed_dir = save_dir + "_trimmed"
    total_steps = 5 if (asin or url) else 4
    step_no = 0
    t_start = time.perf_counter()
    timings = []  # [ステップ名, 開始時刻→確定後は所要秒]

    def step(name):
        nonlocal step_no
        step_no += 1
        now = time.perf_counter()
        if timings:
            timings[-1][1] = now - timings[-1][1]
        timings.append([name.split(":")[0], now])
        emit("run_step", human=f"===== [{step_no}/{total_steps}] {name} =====",
             step=name, current=step_no, total=total_steps)

    def finish(code):
        """最後のステップを確定し、所要時間サマリを出力して code を返す。"""
        now = time.perf_counter()
        if timings:
            timings[-1][1] = now - timings[-1][1]
        total_sec = now - t_start
        detail = ", ".join(f"{name}={sec:.0f}秒" for name, sec in timings)
        emit(
            "run_summary",
            human=f"所要時間: {detail} / 合計 {total_sec / 60:.1f}分",
            ok=(code == EXIT_OK),
            steps={name: round(sec, 1) for name, sec in timings},
            total_seconds=round(total_sec, 1),
        )
        return code

    # open / capture 個別の抑止に加えて、1冊の処理全体で画面消灯を抑止する。
    # trim / OCR 中に画面が消えると復帰時のサインインでセッションがロックされ、
    # 以降の open / capture が全滅するため (2026-08-01 の B群バッチで実測)
    prevent_sleep()
    try:
        if asin or url:
            step("open: 本を開いて先頭ページへ")
            code = open_book(
                profile, asin=asin, url=url, page_turn=page_turn,
                no_fullscreen=False, no_rewind=no_rewind,
                max_rewind=max_rewind, load_wait=load_wait, emit=emit,
            )
            if code != EXIT_OK:
                return finish(code)

        step("capture: ページを自動キャプチャ")
        code = run_capture(
            profile, title, out, profile_key=profile_key,
            page_turn=page_turn, page_wait=page_wait,
            max_pages=max_pages, overwrite=overwrite, emit=emit,
        )
        if code != EXIT_OK:
            return finish(code)

        step("validate: キャプチャ結果を検証")
        code = run_validate(save_dir, expect_pages=expect_pages, strict=False,
                            emit=emit)
        if code != EXIT_OK:
            return finish(code)

        step("trim: 余白を自動トリミング")
        # Cloud Reader は書名ヘッダーとページ番号フッターが常時表示されるため、
        # 上下は最低限この帯を削る (4K 全画面での実測値。min_margins で上書き可)。
        # UI 帯検出が効かない場合の保険で、合成は辺ごとの max なので害はない
        if min_margins is None and profile_key == "kindle_cloud":
            min_margins = (0, 0, 80, 80)
        code = run_trim(
            save_dir, trimmed_dir, margins=None, safety=safety,
            min_margins=min_margins, ui_bands=ui_bands,
            overwrite=overwrite, emit=emit,
        )
        if code != EXIT_OK:
            return finish(code)

        step(f"convert: {fmt} に変換")
        return finish(run_convert(
            trimmed_dir, out, fmt, name=title, config=cfg,
            ocr_workers=ocr_workers, faithful=faithful, no_cleanup=no_cleanup,
            split_words=split_words, source=(asin or None), emit=emit,
        ))
    finally:
        allow_sleep()


# ============================================================
# batch (複数冊を一括実行)
# ============================================================

def _v_str(v):
    if isinstance(v, str) and v.strip():
        return v, None
    return None, "空でない文字列を指定してください"


def _v_bool(v):
    if isinstance(v, bool):
        return v, None
    return None, "true / false を指定してください"


def _v_int(v):
    # bool は int のサブクラスなので明示的に弾く
    if isinstance(v, bool) or not isinstance(v, int):
        return None, "整数を指定してください"
    return v, None


def _v_num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, "数値を指定してください"
    return float(v), None


def _v_choice(choices):
    def check(v):
        if isinstance(v, str) and v in choices:
            return v, None
        return None, f"次のいずれかを指定してください: {', '.join(choices)}"
    return check


def _v_margins(v):
    """L,R,T,B を「4整数の配列」か「"L,R,T,B" 文字列」で受け取りタプルにする。"""
    if isinstance(v, str):
        parts = [p.strip() for p in v.split(",")]
    elif isinstance(v, (list, tuple)):
        parts = list(v)
    else:
        return None, "L,R,T,B の4整数（配列 or 文字列）で指定してください"
    if len(parts) != 4:
        return None, "L,R,T,B の4整数で指定してください"
    out = []
    for p in parts:
        if isinstance(p, bool):
            return None, "L,R,T,B は0以上の整数で指定してください"
        try:
            n = int(p)
        except (TypeError, ValueError):
            return None, "L,R,T,B は0以上の整数で指定してください"
        if n < 0:
            return None, "L,R,T,B は0以上の整数で指定してください"
        out.append(n)
    return tuple(out), None


# batch ファイルの各本で指定できるキー: (JSONキー, run_book の引数名, 検証関数)
# ここが「1冊あたりに上書きできる設定」の唯一の定義。run_book の引数と対応させる。
_BOOK_FIELDS = (
    ("asin", "asin", _v_str),
    ("url", "url", _v_str),
    ("title", "title", _v_str),
    ("format", "fmt", _v_choice(FORMATS)),
    ("profile", "profile_key", _v_str),
    ("page_turn", "page_turn", _v_choice(PAGE_TURN_KEYS)),
    ("page_wait", "page_wait", _v_num),
    ("expect_pages", "expect_pages", _v_int),
    ("max_pages", "max_pages", _v_int),
    ("max_rewind", "max_rewind", _v_int),
    ("load_wait", "load_wait", _v_int),
    ("no_rewind", "no_rewind", _v_bool),
    ("safety", "safety", _v_int),
    ("min_margins", "min_margins", _v_margins),
    ("ui_bands", "ui_bands", _v_bool),
    ("faithful", "faithful", _v_bool),
    ("no_cleanup", "no_cleanup", _v_bool),
    ("ocr_workers", "ocr_workers", _v_int),
    ("split_words", "split_words", _v_int),
)
_BOOK_ALLOWED_KEYS = frozenset(f[0] for f in _BOOK_FIELDS)


def _coerce_book(entry, human_index):
    """batch ファイルの1エントリを run_book の kwargs へ変換・検証する。

    Returns:
        (kwargs, None) または (None, エラーメッセージ)。
        kwargs には必ず "title" が入り、"asin" か "url" のどちらかを持つ。
    """
    label = f"{human_index}番目の本"
    if not isinstance(entry, dict):
        return None, f"{label}: オブジェクト（辞書）ではありません"

    unknown = set(entry) - _BOOK_ALLOWED_KEYS
    if unknown:
        return None, (
            f"{label}: 未知のキー {sorted(unknown)}"
            f"（指定可能: {sorted(_BOOK_ALLOWED_KEYS)}）"
        )

    kwargs = {}
    for jkey, kwarg, validator in _BOOK_FIELDS:
        if jkey in entry:
            value, err = validator(entry[jkey])
            if err is not None:
                return None, f"{label} '{jkey}': {err}"
            kwargs[kwarg] = value

    if not kwargs.get("asin") and not kwargs.get("url"):
        return None, f"{label}: asin か url が必要です"

    title = kwargs.get("title") or kwargs.get("asin")
    if not title:
        return None, f"{label}: url のみ指定のときは title が必要です"
    kwargs["title"] = title
    return kwargs, None


def load_batch_file(path, emit=null_emit):
    """batch ファイル（JSON）を読み込み、検証済みの本リストにして返す。

    受け付ける形式:
        - 本オブジェクトの配列: ``[{"asin": ..., "title": ...}, ...]``
        - ``{"books": [ ... ]}`` でラップした形

    ファイルの構造・型・未知キー・重複タイトルは実キャプチャの前に一括検証する
    （無人実行の途中で設定ミスに気づく事故を防ぐ）。問題があれば error イベントを
    出して終了コードを返す。

    Returns:
        (books, None) 成功時。books は run_book kwargs の dict のリスト。
        (None, exit_code) 失敗時。
    """
    if not os.path.isfile(path):
        emit_error(emit, f"batch ファイルが見つかりません: {path}")
        return None, EXIT_BAD_ARGS

    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        emit_error(emit, f"batch ファイルを読めません（JSON 不正）: {e}")
        return None, EXIT_BAD_ARGS

    if isinstance(data, dict) and "books" in data:
        data = data["books"]
    if not isinstance(data, list):
        emit_error(emit, "batch ファイルは本オブジェクトの配列、"
                         "または {\"books\": [...]} 形式にしてください")
        return None, EXIT_BAD_ARGS
    if not data:
        emit_error(emit, "batch ファイルに本が1冊もありません")
        return None, EXIT_BAD_ARGS

    books = []
    errors = []
    seen_titles = {}
    for i, entry in enumerate(data, 1):
        kwargs, err = _coerce_book(entry, i)
        if err is not None:
            errors.append(err)
            continue
        title = kwargs["title"]
        if title in seen_titles:
            errors.append(
                f"{i}番目の本: タイトルが {seen_titles[title]}番目と重複しています "
                f"（出力ファイル名が衝突します）: {title}"
            )
            continue
        seen_titles[title] = i
        books.append(kwargs)

    if errors:
        for err in errors:
            emit_error(emit, err)
        emit_error(emit, f"batch ファイルに {len(errors)} 件の問題があります: {path}")
        return None, EXIT_BAD_ARGS

    return books, None


def _batch_output_path(out, title, fmt):
    """batch のスキップ判定・報告に使う出力ファイルパスを返す。

    markdown で ``<title>.md`` がなく分割出力 ``<title>_1.md`` がある場合は
    そちらを返す（split_words による分割時も再開スキップを効かせる）。
    """
    ext = ".md" if fmt == "markdown" else ".pdf"
    path = os.path.join(out, _ensure_ext(title, ext))
    if fmt == "markdown" and not os.path.exists(path):
        part1 = os.path.join(out, _ensure_ext(f"{title}_1", ext))
        if os.path.exists(part1):
            return part1
    return path


def run_batch(books, *, output, defaults=None, overwrite=False,
              stop_on_error=False, config=None, emit=null_emit):
    """検証済みの本リストを1冊ずつ run_book で通し実行する。

    各本は ``{**defaults, **book}`` で run_book を呼ぶ（本ごとの設定が
    バッチ既定を上書きする）。既に出力ファイルがある本はスキップして再開できる。
    1冊が失敗しても既定では続行し、最後に batch_summary で成否をまとめる。

    Args:
        books: load_batch_file が返す run_book kwargs の dict リスト
            （各要素は必ず title と、asin か url を持つ）
        output: 全本共通の保存先フォルダ（この直下に <title>.pdf/.md が並ぶ）
        defaults: バッチ全体の既定 run_book kwargs（CLI フラグ由来）
        overwrite: True で完成済みの本も再処理する（既定はスキップ）
        stop_on_error: True で最初の失敗時にバッチを中断する
        config: 設定 dict（None なら load_config()）
        emit: イベントコールバック

    Returns:
        終了コード（失敗が1冊でもあれば EXIT_ERROR）
    """
    from core.config import load_config
    from core.win32_utils import allow_sleep, prevent_sleep

    cfg = config if config is not None else load_config()
    defaults = defaults or {}
    out = os.path.abspath(output)
    total = len(books)

    emit("batch_start", human=f"バッチ開始: {total} 冊 → {out}",
         total_books=total, output=out)

    # 本と本の間も含めてバッチ全体で画面消灯を抑止する (run_book と同趣旨)
    prevent_sleep()
    try:
        return _run_batch_impl(books, out, defaults, cfg, overwrite,
                               stop_on_error, emit)
    finally:
        allow_sleep()


def _run_batch_impl(books, out, defaults, cfg, overwrite, stop_on_error, emit):
    total = len(books)
    results = []
    for i, book in enumerate(books, 1):
        merged = {**defaults, **book}
        title = merged["title"]
        asin = merged.get("asin")
        ref = asin or merged.get("url")
        fmt = merged.get("fmt", "searchable_pdf")
        output_path = _batch_output_path(out, title, fmt)

        # 完成済み（出力ファイルが既にある）本はスキップして再開できる
        if not overwrite and os.path.exists(output_path):
            emit("book_skipped",
                 human=f"##### [{i}/{total}] スキップ（出力済み）: {title} #####",
                 index=i, total=total, asin=asin, title=title,
                 output=output_path, reason="exists")
            results.append({"asin": asin, "title": title, "exit_code": EXIT_OK,
                            "ok": True, "skipped": True, "output": output_path})
            continue

        emit("book_start",
             human=f"##### [{i}/{total}] {ref} {title} ({fmt}) #####",
             index=i, total=total, asin=asin, title=title, format=fmt)

        # 実行する本は「未完成」なので、途中で終わった残骸画像は消して作り直す
        # （run_book の overwrite。完成済みのスキップ判定はバッチ側で済ませている）
        try:
            code = run_book(output=out, config=cfg, emit=emit,
                            overwrite=True, **merged)
        except Exception as e:  # noqa: BLE001 - 1冊の想定外エラーでバッチを止めない
            emit_error(emit, f"予期しないエラー: {e}")
            code = EXIT_ERROR

        ok = (code == EXIT_OK)
        # 分割 Markdown 出力なら実体は <title>_1.md。実行後に取り直す
        output_path = _batch_output_path(out, title, fmt)
        results.append({"asin": asin, "title": title, "exit_code": code,
                        "ok": ok, "skipped": False,
                        "output": output_path if ok else None})
        emit("book_result",
             human=f"[{i}/{total}] {'OK' if ok else 'NG'} {title} (exit {code})",
             index=i, total=total, asin=asin, title=title,
             exit_code=code, ok=ok, output=output_path if ok else None)

        if not ok and stop_on_error:
            emit("status",
                 human="--stop-on-error によりバッチを中断します",
                 message="stop_on_error")
            break

    return _emit_batch_summary(emit, results, total)


def _emit_batch_summary(emit, results, total):
    """batch_summary イベントを出し、バッチ全体の終了コードを返す。"""
    succeeded = sum(1 for r in results if r["ok"] and not r["skipped"])
    skipped = sum(1 for r in results if r["skipped"])
    failures = [r for r in results if not r["ok"]]
    unprocessed = total - len(results)  # stop-on-error で残った本

    lines = [
        f"バッチ完了: 成功 {succeeded} / 失敗 {len(failures)} / スキップ {skipped}"
        + (f" / 未処理 {unprocessed}" if unprocessed else "")
        + f"（全 {total} 冊）"
    ]
    for r in failures:
        lines.append(f"  NG {r['asin'] or r['title']} {r['title']} "
                     f"(exit {r['exit_code']})")

    emit("batch_summary", human="\n".join(lines),
         ok=(not failures), total=total,
         succeeded=succeeded, failed=len(failures),
         skipped=skipped, unprocessed=unprocessed,
         results=results)
    return EXIT_OK if not failures else EXIT_ERROR


# ============================================================
# validate
# ============================================================

def run_validate(input_folder, *, expect_pages=None, strict=False,
                 emit=null_emit):
    """キャプチャ結果を機械検証する（白紙・重複・サイズ違い・ページ数）。

    Args:
        input_folder: 検証する画像フォルダ
        expect_pages: 期待ページ数 (実際がこれ未満ならエラー)
        strict: 警告 (白紙・重複・サイズ違い) もエラー扱いにする
        emit: イベントコールバック

    Returns:
        終了コード (問題があれば EXIT_VALIDATION)
    """
    from core.validator import PageReadError, analyze_folder

    input_folder = os.path.abspath(input_folder)
    code = check_input_folder(input_folder, emit)
    if code is not None:
        return code

    try:
        report = analyze_folder(
            input_folder, on_progress=phase_progress(emit, "validate"),
        )
    except PageReadError as e:
        emit_error(emit, str(e))
        return EXIT_ERROR

    blank_pages = report["blank_pages"]
    near_duplicates = report["near_duplicates"]
    size_mismatch = report["size_mismatch"]
    common_size = report["common_size"]

    count = len(report["files"])
    count_shortfall = (
        expect_pages is not None and count < expect_pages
    )

    warnings = []
    if blank_pages:
        warnings.append(f"一様なページ (白紙/真っ黒) {len(blank_pages)} 枚: "
                        + ", ".join(blank_pages[:10]))
    if near_duplicates:
        pairs = ", ".join("/".join(d["pages"]) for d in near_duplicates[:10])
        warnings.append(f"ほぼ同一の隣接ページ {len(near_duplicates)} 組: {pairs}")
    if size_mismatch:
        warnings.append(f"サイズが他と異なるページ {len(size_mismatch)} 枚: "
                        + ", ".join(size_mismatch[:10]))

    errors = []
    if count_shortfall:
        errors.append(f"ページ数不足: {count} < 期待 {expect_pages}")
    if strict and warnings:
        errors.extend(warnings)

    human_lines = [f"検証完了: {count} ページ (基準サイズ {common_size[0]}x{common_size[1]})"]
    human_lines += [f"警告: {w}" for w in warnings]
    human_lines += [f"エラー: {e}" for e in errors]

    emit(
        "result",
        human="\n".join(human_lines),
        ok=not errors,
        pages=count,
        expect_pages=expect_pages,
        common_size=list(common_size),
        blank_pages=blank_pages,
        near_duplicates=near_duplicates,
        size_mismatch=size_mismatch,
        warnings=len(warnings),
        errors=errors,
    )
    return EXIT_VALIDATION if errors else EXIT_OK
