"""テキスト分量の見積り（NotebookLM の 50万語 / 200MB 制限の目安表示用）

NotebookLM の 1 ソース上限は「50万語 または 200MB」（超で取込失敗）。
日本語の「語」の数え方は NotebookLM 側で非公開のため、ここでは

    推定語数 = ASCII 単語数 + CJK 文字数（漢字・かな）

を目安とする（保守的に多めに出る前提）。確定値ではないので、実際に
NotebookLM へ投入して表示される語数で補正すること。
"""

from __future__ import annotations

import re

from core.text_patterns import CJK_BASE

_WS_RE = re.compile(r"\s+")
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CJK_RE = re.compile(f"[{CJK_BASE}]")

# NotebookLM の 1 ソース上限（2026-07 時点）
WORD_LIMIT = 500_000
BYTE_LIMIT = 200 * 1024 * 1024


def estimate(text: str) -> dict:
    """テキストの分量を見積もる。

    Returns:
        {chars, words, bytes, ascii_words, cjk_chars} の dict
        - chars: 空白を除いた文字数
        - words: 推定語数（ASCII 単語 + CJK 文字）
        - bytes: UTF-8 バイト数
    """
    text = text or ""
    chars = len(_WS_RE.sub("", text))
    ascii_words = len(_ASCII_WORD_RE.findall(text))
    cjk_chars = len(_CJK_RE.findall(text))
    return {
        "chars": chars,
        "words": ascii_words + cjk_chars,
        "bytes": len(text.encode("utf-8")),
        "ascii_words": ascii_words,
        "cjk_chars": cjk_chars,
    }


def format_stats(st: dict) -> str:
    """estimate() の結果を人間向け 1 行に整形する。"""
    mb = st["bytes"] / (1024 * 1024)
    msg = (
        f"分量: {st['chars']:,}字 / 推定 {st['words']:,}語 / {mb:.1f}MB"
        f"（NotebookLM 上限 50万語・200MB）"
    )
    warns = []
    if st["words"] > WORD_LIMIT:
        warns.append("推定語数が 50万語を超過（分割が必要な可能性）")
    if st["bytes"] > BYTE_LIMIT:
        warns.append("200MB を超過")
    if warns:
        msg += " ⚠ " + " / ".join(warns)
    return msg
