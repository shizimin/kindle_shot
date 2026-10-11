"""Markdown出力モジュール

OCR結果を .md ファイルとして出力する。
ページ区切り（---）で区分し、フロントマター付き。

reflow=True を渡すと、各ページ本文に対して text_reflow.reflow_text() を適用し、
OCR で混入した改行を結合して読みやすい段落に整形する。

chapters を渡すと、対応するページに ``## 章タイトル`` 見出しを挿入する。
embed_images=True にすると、image_folder の各ページ画像を出力 .md と同階層の
``<basename>_pages/`` にコピーし、``![p.NNN](path)`` 形式で本文先頭に併記する。
RAG / LLM に渡したときに「該当ページの図を見せて」と言われたら画像を返せる。
"""

import os
import re
import shutil
from datetime import datetime

from core.chapter_detector import chapters_by_filename
from core.text_patterns import LEAD_JUNK_RE, STANDALONE_PAGE_NUM_RE
from core.text_stats import estimate


def _copy_images(results, image_folder, output_path):
    """image_folder の各ページ画像を出力先サブフォルダにコピーし、
    {filename: relative_path} の dict を返す。
    """
    out_dir = os.path.dirname(output_path) or "."
    base = os.path.splitext(os.path.basename(output_path))[0]
    pages_dir_name = f"{base}_pages"
    pages_dir_abs = os.path.join(out_dir, pages_dir_name)
    os.makedirs(pages_dir_abs, exist_ok=True)

    rel_map = {}
    for filename, _text in results:
        src = os.path.join(image_folder, filename)
        if not os.path.exists(src):
            continue
        dst = os.path.join(pages_dir_abs, filename)
        # 既存と同一なら上書きを避ける (mtime 比較は省略、shutil.copy2 で十分)
        try:
            shutil.copy2(src, dst)
        except OSError:
            continue
        rel_map[filename] = f"{pages_dir_name}/{filename}".replace(os.sep, "/")
    return rel_map


def write_markdown(
    results, output_path, title=None, source=None, reflow=False,
    chapters=None, embed_images=False, image_folder=None,
):
    """OCR結果をMarkdownファイルとして出力する。

    Args:
        results: [(filename, text), ...] のリスト（OCR結果）
        output_path: 出力ファイルパス
        title: ドキュメントタイトル（省略時はファイル名から生成）
        source: ソース情報（省略時は空）
        reflow: True なら本文を段落整形して書き出す
        chapters: chapter_detector.Chapter のリスト。該当ページに見出しを挿入
        embed_images: True なら各ページ画像へのリンクを併記
        image_folder: 画像フォルダパス (embed_images=True のとき必須)

    Returns:
        (success, message) のタプル
    """
    if not results:
        return False, "変換するデータがありません。"

    if not output_path.lower().endswith(".md"):
        output_path += ".md"

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    if not title:
        title = os.path.splitext(os.path.basename(output_path))[0]

    if reflow:
        from .text_reflow import reflow_text

    chapter_map = chapters_by_filename(chapters)
    image_rel = {}
    if embed_images and image_folder:
        image_rel = _copy_images(results, image_folder, output_path)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            # フロントマター
            f.write("---\n")
            f.write(f"title: \"{title}\"\n")
            f.write(f"date: {datetime.now().strftime('%Y-%m-%d')}\n")
            if source:
                f.write(f"source: \"{source}\"\n")
            f.write(f"pages: {len(results)}\n")
            f.write("---\n\n")

            # 各ページの内容
            for i, (filename, text) in enumerate(results):
                if i > 0:
                    f.write("\n---\n\n")

                f.write(f"<!-- page: {filename} -->\n\n")

                # 章見出し (該当ページのみ)
                ch = chapter_map.get(filename)
                if ch is not None:
                    hashes = "#" * max(1, min(6, ch.level))
                    f.write(f"{hashes} {ch.title}\n\n")

                # 画像リンク併記
                rel = image_rel.get(filename)
                if rel:
                    page_label = os.path.splitext(filename)[0]
                    f.write(f"![p.{page_label}]({rel})\n\n")

                body = reflow_text(text) if reflow else text
                # 本文書き出し: 整形済みでも生でも、行末空白だけは落とす
                for line in body.split("\n"):
                    line = line.rstrip()
                    f.write(f"{line}\n" if line else "\n")

        return True, f"Markdownファイルを作成しました: {output_path}"

    except Exception as e:
        return False, f"Markdown生成エラー: {e}"


# ============================================================
# NotebookLM 最適化 Markdown 出力
# ============================================================

# 単独行のページ番号・章番号（「11」「- 12 -」等）。本文には不要なノイズなので落とす。
_STANDALONE_NUM_RE = STANDALONE_PAGE_NUM_RE

# 見出しと本文の重複判定で無視する行頭の装飾・記号
_LEAD_JUNK_RE = LEAD_JUNK_RE


def _looks_like_boilerplate(text):
    """Kindle ビューアの定型注意書きページかどうか。"""
    return "ご利用の端末によっては" in text or "文字サイズを大きくすると" in text


def _drop_noise_lines(body):
    """本文から単独ページ番号・章番号行を除去する。"""
    return "\n".join(
        ln for ln in body.split("\n") if not _STANDALONE_NUM_RE.match(ln.strip())
    )


def _strip_leading_title(body, title):
    """本文先頭に現れる章タイトル行を 1 つ取り除く（H2 見出しとの重複を防ぐ）。

    見出し側は装飾記号を除いたタイトルなので、本文行も装飾を無視して比較する
    （例: 見出し「エピローグ」と本文「▲ エピローグ」を同一とみなす）。
    """
    t = _LEAD_JUNK_RE.sub("", title).strip()
    out = []
    removed = False
    for ln in body.split("\n"):
        cmp = _LEAD_JUNK_RE.sub("", ln).strip()
        if not removed and cmp and cmp == t:
            removed = True
            continue
        out.append(ln)
    return "\n".join(out)


def write_notebooklm_markdown(results, output_path, title=None, source=None,
                              chapters=None, split_words=None):
    """NotebookLM 最適化 Markdown を出力する。

    ページ忠実型 (``write_markdown``) と違い、AI に読ませることに最適化する:

    - **ページをまたいで段落を結合**（見開き・改ページで文が途切れない）
    - ``<!-- page -->`` コメントやページ区切り ``---`` を出さない
    - 見出し階層は **H1=書名 / H2=章 / H3=節**（NotebookLM 推奨の 3 階層）
    - ビューアの定型注意書きページ・単独ページ番号行を除去

    行内の余分なスペース除去 (``text_cleanup``) は呼び出し側で適用済みの前提。

    Args:
        results: [(filename, text), ...]（クリーニング済み推奨）
        output_path: 出力ファイルパス
        title: 書名（省略時はファイル名から）
        source: ソース情報（ASIN 等、任意）
        chapters: chapter_detector.Chapter のリスト（H2/H3 見出しに変換）
        split_words: 推定語数がこれを超えたら章（H2）境界を優先して
            ``<名前>_1.md, _2.md, …`` に分割する（NotebookLM の 1 ソース
            50万語制限対策）。None なら分割しない

    Returns:
        (success, message, written) のタプル。written は書き出したファイル
        パスのリスト（分割なしなら 1 要素）
    """
    from .text_reflow import reflow_markdown

    if not results:
        return False, "変換するデータがありません。", []
    if not output_path.lower().endswith(".md"):
        output_path += ".md"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if not title:
        title = os.path.splitext(os.path.basename(output_path))[0]

    chapter_map = chapters_by_filename(chapters)

    body_lines = [f"# {title}", ""]
    for filename, text in results:
        body = (text or "").strip("\n")
        if not body.strip():
            continue
        if _looks_like_boilerplate(body):
            continue
        body = _drop_noise_lines(body)
        if not body.strip():
            continue
        # 表紙・扉などで書名だけが写ったページは H1 と重複するので落とす
        if body.strip() == title.strip():
            continue

        ch = chapter_map.get(filename)
        # 書名そのものを見出しにしない（半扉・扉ページの書名を章と誤検出するため）
        if ch is not None and ch.title.strip().startswith(title.strip()):
            ch = None
        if ch is not None:
            hashes = "#" * max(2, min(6, ch.level + 1))  # 章=H2, 節=H3
            body_lines.append("")
            body_lines.append(f"{hashes} {ch.title}")
            body_lines.append("")
            body = _strip_leading_title(body, ch.title)
            if not body.strip():
                continue
        body_lines.append(body)

    # reflow_markdown は見出し・区切りを保護しつつ、段落内（＝ページをまたいだ
    # 本文）の改行だけを結合する。ページ本文を空行なしで連結しているため、
    # ページ末が文の途中なら次ページ先頭と自然に結合される。
    final_body = reflow_markdown("\n".join(body_lines))

    try:
        if split_words and estimate(final_body)["words"] > split_words:
            return _write_split_parts(
                final_body, output_path, title, source, split_words,
            )
        _write_md_file(output_path, title, source, final_body)
        return True, f"Markdownファイルを作成しました: {output_path}", [output_path]
    except Exception as e:
        return False, f"Markdown生成エラー: {e}", []


# ============================================================
# 分割出力（NotebookLM の 1 ソース上限対策）
# ============================================================

def _write_md_file(path, title, source, body, part=None):
    """フロントマター付きで 1 ファイル書き出す。part は (i, n) の部番号。"""
    with open(path, "w", encoding="utf-8") as f:
        f.write("---\n")
        f.write(f'title: "{title}"\n')
        f.write(f"date: {datetime.now().strftime('%Y-%m-%d')}\n")
        if source:
            f.write(f'source: "{source}"\n')
        if part:
            f.write(f"part: {part[0]}/{part[1]}\n")
        f.write("---\n\n")
        f.write(body)
        if not body.endswith("\n"):
            f.write("\n")


def _h2_segments(body):
    """本文（H1 行を除いたもの）を H2 見出しの直前で分割する。

    先頭に H2 より前の前置き（序文等）があればそれも 1 セグメントになる。
    H3 以下は章の中身としてセグメント内に留まる。
    """
    segments, cur = [], []
    for ln in body.split("\n"):
        if ln.startswith("## ") and cur:
            segments.append("\n".join(cur).strip("\n"))
            cur = []
        cur.append(ln)
    if cur:
        segments.append("\n".join(cur).strip("\n"))
    return [s for s in segments if s.strip()]


def _chunk_by_words(pieces, split_words):
    """テキスト片の列を、順序を保ったまま推定語数 split_words 以下ずつに束ねる。

    1 片単独で上限を超える場合はそのまま 1 塊にする（片の内部では切らない）。
    """
    chunks, cur, cur_words = [], [], 0
    for piece in pieces:
        words = estimate(piece)["words"]
        if cur and cur_words + words > split_words:
            chunks.append("\n\n".join(cur))
            cur, cur_words = [], 0
        cur.append(piece)
        cur_words += words
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks


def split_body_by_words(body, split_words):
    """本文を章（H2）境界を優先して推定 split_words 語以下の部に分ける。

    章単体が上限を超える場合のみ、その章の中を段落（空行）境界で分割する。

    Returns:
        部本文（str）のリスト
    """
    atoms = []
    for seg in _h2_segments(body):
        if estimate(seg)["words"] > split_words:
            atoms.extend(_chunk_by_words(re.split(r"\n\s*\n", seg), split_words))
        else:
            atoms.append(seg)
    return _chunk_by_words(atoms, split_words)


def _write_split_parts(final_body, output_path, title, source, split_words):
    """final_body を分割して <base>_1.md, _2.md, … に書き出す。"""
    # 先頭の H1 行を外して分割し、各部に部番号つきの H1 を付け直す
    lines = final_body.split("\n")
    body = final_body
    if lines and lines[0].startswith("# "):
        body = "\n".join(lines[1:]).lstrip("\n")

    parts = split_body_by_words(body, split_words)
    n = len(parts)
    base, ext = os.path.splitext(output_path)
    written = []
    for i, part_body in enumerate(parts, 1):
        part_title = f"{title}（{i}/{n}）"
        path = f"{base}_{i}{ext}"
        _write_md_file(
            path, part_title, source,
            f"# {part_title}\n\n{part_body}", part=(i, n),
        )
        written.append(path)
    names = " / ".join(os.path.basename(p) for p in written)
    return True, f"Markdownファイルを {n} 分割で作成しました: {names}", written

