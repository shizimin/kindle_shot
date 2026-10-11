"""段落整形モジュール

OCR 結果のテキストには、ページ幅の都合で文の途中に大量の改行が混入する。
このモジュールは LLM を使わず、機械的なルールだけで改行を間引き、
1つの文章として読める段落に組み直す。

ルール (日本語/英語の両方を想定):
- 行末が句点 (。．.!?！？) や閉じ括弧で終わる行は段落の終わり候補
- そうでない行は次の行と結合する (日本語は無空白、英語は半角スペース挟む)
- 英文行末のハイフン分割 (例: ``inter-`` + ``national``) は結合してハイフンを除去
- 空行は段落区切りとしてそのまま残す
- 見出し (Markdown の ``#``)、箇条書き (``- `` ``* `` ``1. ``)、表の罫線、
  HTML コメント、コードフェンス、フロントマター (``---``) は整形対象外
- 連続する空行は 1 行にまとめる

公開 API:
- ``reflow_text(text)``: 純粋なテキストを整形
- ``reflow_markdown(md)``: Markdown を構造を維持しつつ整形
"""

from __future__ import annotations

import re

# 行末が「文の終端」とみなせる文字
_SENT_END_CHARS = "。．！？!?…」』）)】〕》>"
# 英文の文末
_EN_SENT_END = ".!?"

_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_LIST_RE = re.compile(r"^\s*([-*+・]|\d+[.)）、])\s+")
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
_HTML_COMMENT_RE = re.compile(r"^\s*<!--.*-->\s*$")
_HR_RE = re.compile(r"^\s*(---|\*\*\*|___)\s*$")
_CODE_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# 行頭が「次行と必ず結合してはいけない」と判定する記号
_BLOCK_LEADING_RE = re.compile(r"^[\s　]*[（(「『【〔《<]")

# ASCII (英語) 行と判定するための閾値
_ASCII_THRESHOLD = 0.7

# 短い行 (見出し・章番号・節タイトル等の可能性) を独立行と見なす閾値
# 句点なしでこの長さ以下なら、次行と結合せず段落を切る。
# chapter_detector._SHORT_LINE_THRESHOLD (=20) とは別チューニング (統合しない)
_SHORT_LINE_THRESHOLD = 15

# 名簿リスト行: ……(2点リーダ以上連続) を含む行は独立項目とみなす
_LIST_ITEM_RE = re.compile(r"…{2,}|・{2,}|\.{3,}")


def _is_ascii_dominant(line: str) -> bool:
    """行の大半が ASCII 文字なら英文行とみなす。"""
    s = line.strip()
    if not s:
        return False
    ascii_count = sum(1 for c in s if ord(c) < 128)
    return ascii_count / len(s) >= _ASCII_THRESHOLD


def _visible_length(line: str) -> int:
    """空白を除いた可視文字数を返す (見出し判定用)。"""
    return len(line.strip().replace(" ", "").replace("　", ""))


def _ends_paragraph(line: str) -> bool:
    """この行で段落を切るべきかを返す。"""
    s = line.rstrip()
    if not s:
        return True
    last = s[-1]
    if last in _SENT_END_CHARS:
        return True
    if _is_ascii_dominant(s) and last in _EN_SENT_END:
        return True
    # 短い行 (章番号・章タイトル等) は独立した塊として扱い、次行と結合しない
    if _visible_length(s) <= _SHORT_LINE_THRESHOLD:
        return True
    # 名簿/索引行 (「……」「・・・」「...」を含む行) も独立項目として扱う
    return bool(_LIST_ITEM_RE.search(s))


def _is_structural(line: str) -> bool:
    """構造行 (見出し/リスト/表/区切り等) なら True を返す。"""
    if not line.strip():
        return False
    if _HEADING_RE.match(line):
        return True
    if _LIST_RE.match(line):
        return True
    if _TABLE_LINE_RE.match(line) or _TABLE_SEP_RE.match(line):
        return True
    if _HTML_COMMENT_RE.match(line):
        return True
    return bool(_HR_RE.match(line))


def _join_lines(prev: str, curr: str) -> str:
    """前行と現在行を結合する。

    - 英文ハイフン分割 (``...inter-`` + ``national...``) は ``-`` を除去して連結
    - 前行が ASCII で末尾が ``-`` 以外なら半角スペースで連結
    - それ以外 (日本語が含まれる) は無空白で連結
    """
    p = prev.rstrip()
    c = curr.lstrip()
    if not p:
        return c
    if not c:
        return p

    # 英文ハイフン分割
    if p.endswith("-") and _is_ascii_dominant(p) and _is_ascii_dominant(c):
        # ハイフンの前の文字が英字のときだけ吸収する (例: ``well-`` の ``-`` は残したいが
        # 実用上は次の語と結合した方が自然なので削除する)
        return p[:-1] + c

    if _is_ascii_dominant(p) and _is_ascii_dominant(c):
        return p + " " + c

    return p + c


def reflow_text(text: str) -> str:
    """純粋テキストの改行を整形して 1 段落として読めるようにする。

    空行は段落区切りとして保持する。構造行 (見出し等) も保持する。
    """
    if not text:
        return text

    lines = text.splitlines()
    paragraphs: list[str] = []
    buf: list[str] = []

    def flush():
        if not buf:
            return
        # buf 内の各行を順に結合する
        merged = buf[0]
        for nxt in buf[1:]:
            merged = _join_lines(merged, nxt)
        paragraphs.append(merged)
        buf.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush()
            paragraphs.append("")
            continue
        if _is_structural(line):
            flush()
            paragraphs.append(line)
            continue

        if not buf:
            buf.append(line)
            continue

        # 直前が構造行で終わったあとの新規段落、または前行末で段落が確定済みのケース
        prev = buf[-1]
        if _ends_paragraph(prev):
            flush()
            buf.append(line)
            continue

        # 行頭の括弧で始まる行は前段落の続きとは別と見なす
        if _BLOCK_LEADING_RE.match(line):
            flush()
            buf.append(line)
            continue

        buf.append(line)

    flush()

    # 連続する空行は 1 つにまとめる
    cleaned: list[str] = []
    prev_blank = False
    for p in paragraphs:
        is_blank = (p == "")
        if is_blank and prev_blank:
            continue
        cleaned.append(p)
        prev_blank = is_blank

    # 先頭末尾の空行は削除
    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    return "\n".join(cleaned)


def reflow_markdown(md: str) -> str:
    """Markdown 全体を、フロントマター・コードブロック・表を保護しつつ整形する。"""
    if not md:
        return md

    lines = md.splitlines()
    out: list[str] = []
    i = 0
    n = len(lines)

    # フロントマター (--- で始まり --- で終わる) はそのまま通す
    if n > 0 and lines[0].strip() == "---":
        out.append(lines[0])
        i = 1
        while i < n:
            out.append(lines[i])
            if lines[i].strip() == "---":
                i += 1
                break
            i += 1

    # 残りをブロック単位で処理する
    body_buf: list[str] = []

    def flush_body():
        if not body_buf:
            return
        chunk = "\n".join(body_buf)
        out.append(reflow_text(chunk))
        body_buf.clear()

    while i < n:
        line = lines[i]
        # コードフェンス: 中身はそのまま保持
        if _CODE_FENCE_RE.match(line):
            flush_body()
            out.append(line)
            i += 1
            while i < n:
                out.append(lines[i])
                if _CODE_FENCE_RE.match(lines[i]):
                    i += 1
                    break
                i += 1
            continue

        body_buf.append(line)
        i += 1

    flush_body()

    return "\n".join(out)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="OCR テキスト/Markdown を機械的に整形し、改行を段落に組み直す",
    )
    parser.add_argument("input", help="入力ファイル (.txt / .md)")
    parser.add_argument("output", help="出力ファイル")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        src = f.read()

    result = reflow_markdown(src) if args.input.lower().endswith(".md") else reflow_text(src)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"整形しました: {args.output}")
