"""章/見出し自動検出モジュール

OCR 結果のページ列から章タイトル候補を抽出する。
Markdown 出力時は ``#`` 見出しに、PDF 出力時はしおり (アウトライン) に変換される共通基盤。

検出戦略 (優先度順):
1. **強パターン**: 「第◯章」「第◯部」「第◯篇」「Chapter N」「Part N」
   「序章」「終章」「プロローグ」「エピローグ」「あとがき」「謝辞」「解説」「登場人物」
   などの定型語を含む行は章としてほぼ確定。
2. **節パターン**: 「第◯節」「N.M」「§N.M」など。レベル 2 (節) として扱う。
3. **ヒューリスティック (小説向け)**: ページの最初の非除外行のみを候補とする。
   セリフの切れ端や本文の続きを章扱いしてしまう誤検出を抑えるため、以下を要求する:
   - 候補行は 「『 で始まらない (セリフ続き除外)
   - 直後の非除外行が 「『 で始まらない (候補が文の切れ端である兆候)
   - 候補が極短のナンバリング (例「一、」「2」) なら、次の短い行と結合してタイトルとする

ページ番号 (純粋な数字行) や、明らかに本文の続き (句点で終わる) は除外する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core.text_patterns import DECOR_LEAD_RE, STANDALONE_PAGE_NUM_RE

# レベル 1 (章): 強い定型語
_STRONG_CHAPTER_RE = re.compile(
    r"^(?:第[〇一二三四五六七八九十百千0-9０-９]+(?:章|部|篇|編|巻)"
    r"|序章|終章|序論|結論|プロローグ|エピローグ|あとがき|訳者あとがき|はじめに|まえがき|序文|跋|凡例|目次|索引|参考文献"
    r"|謝辞|解説|解題|年譜|登場人物|主要登場人物)"
)
# 英語向け
_STRONG_CHAPTER_EN_RE = re.compile(
    r"^(?:Chapter|Part|Book|Section|Appendix|Preface|Introduction|Foreword|Prologue|Epilogue|Afterword|Acknowledg(?:e?)ments?)\b",
    re.IGNORECASE,
)

# レベル 2 (節): 節パターン
_SECTION_RE = re.compile(r"^(?:第[〇一二三四五六七八九十百千0-9０-９]+節|§\s*\d+(?:[.\-]\d+)*|\d+[.\-]\d+(?:[.\-]\d+)*\s+\S)")

# 除外: ページ番号らしき行 (1〜4 桁の数字のみ、または「- 12 -」のような飾り付き)
_PAGE_NUMBER_RE = STANDALONE_PAGE_NUM_RE

# 句点で終わる行は本文の続きとみなして除外
_SENTENCE_END_RE = re.compile(r"[。．.！？!?」』）)】〕》>]\s*$")

# セリフ・引用の開始記号 (これで始まる行は章タイトルではなくセリフの切れ端と判断)
_DIALOGUE_PREFIX = ("「", "『", "“", "‟", "〝", "❝", "❮")

# 短い行とみなす閾値 (見出し候補)。
# text_reflow._SHORT_LINE_THRESHOLD (=15) とは別チューニング (統合しない)
_SHORT_LINE_THRESHOLD = 20

# ナンバリングだけの行 (「一、」「2」「III」など) → 単独では情報不足、次行と結合する対象
_NUMERIC_ONLY_RE = re.compile(r"^[0-9０-９〇一二三四五六七八九十百千IVXLCMivxlcm]+[、.,]?$")

# タイトルとして実体のある文字 (数字・記号・空白を除いた可視文字数を測るために除外する文字集合)
_NON_SUBSTANTIVE_RE = re.compile(r"[\s\d.,、。・〇一二三四五六七八九十百千０-９,.\-_/()（）「」『』IVXLCMivxlcm]")


@dataclass
class Chapter:
    """検出された章エントリ。

    Attributes:
        page_index: ページ列における 0 始まりインデックス
        filename: そのページの画像ファイル名
        title: 章タイトル文字列
        level: 1 = 章, 2 = 節
    """
    page_index: int
    filename: str
    title: str
    level: int = 1


# 行頭の装飾記号（シーン区切りの▲■◆等）。text_patterns に集約済み
_DECOR_LEAD_RE = DECOR_LEAD_RE


def _clean(line: str) -> str:
    s = line.strip().lstrip("　 ").rstrip()
    return _DECOR_LEAD_RE.sub("", s)


def _is_excluded(line: str) -> bool:
    if not line:
        return True
    if _PAGE_NUMBER_RE.match(line):
        return True
    return bool(_SENTENCE_END_RE.search(line))


def _substantive_len(s: str) -> int:
    """記号・数字・ナンバリング以外の「実体のある文字数」を返す。"""
    return len(_NON_SUBSTANTIVE_RE.sub("", s))


def _visible_len(s: str) -> int:
    """空白を除いた可視文字数。"""
    return len(s.replace(" ", "").replace("　", ""))


def _detect_for_page(idx: int, filename: str, text: str) -> Chapter | None:
    """1 ページ分の検出を行い、Chapter (もしくは None) を返す。"""
    raw = [_clean(ln) for ln in text.split("\n")]
    raw = [ln for ln in raw if ln]
    if not raw:
        return None

    # 1) 強パターン: 先頭 5 行のうち最初の非除外行のみを評価する。
    #    強パターンは見出しの先頭に現れる前提で、深掘りしても誤検出が増えるだけ。
    for line in raw[:5]:
        if _is_excluded(line):
            continue
        if _STRONG_CHAPTER_RE.match(line) or _STRONG_CHAPTER_EN_RE.match(line):
            return Chapter(idx, filename, line, 1)
        if _SECTION_RE.match(line):
            return Chapter(idx, filename, line, 2)
        break  # 最初の非除外行が強パターンでなければ、ヒューリスティックへ

    # 2) ヒューリスティック: 最初の非除外行 1 つだけを候補とする
    first_pos = None
    for i, line in enumerate(raw[:5]):
        if not _is_excluded(line):
            first_pos = i
            break
    if first_pos is None:
        return None
    cand = raw[first_pos]

    # セリフ続き / 引用続きと思われる行は却下
    if cand.startswith(_DIALOGUE_PREFIX):
        return None

    # 行が長すぎれば見出しではなく本文
    if _visible_len(cand) > _SHORT_LINE_THRESHOLD:
        return None

    # 候補に句点が含まれていれば本文の断片 (例: 「興味深い夜だった。 ネットフリックス」)
    if re.search(r"[。．]", cand):
        return None

    # 直後の非空行を文脈確認用に取得 (除外判定はせず、純粋に「次に書かれている行」を見る)
    next_line = None
    for line in raw[first_pos + 1:first_pos + 4]:
        if line:
            next_line = line
            break

    # 直後の非空行がない (= ページ全体がほぼ空) → 単独の表紙/タイトルページとみなす
    if next_line is None:
        if _substantive_len(cand) >= 1:
            return Chapter(idx, filename, cand, 1)
        return None

    # 直後の行がセリフで始まる場合、候補は前ページからのセリフ続きの切れ端の可能性が高い
    if next_line.startswith(_DIALOGUE_PREFIX):
        return None

    # 候補がナンバリングだけ (「一、」「2」など) なら、次行と結合してタイトルにする
    if _NUMERIC_ONLY_RE.match(cand) or _substantive_len(cand) <= 1:
        if (
            _visible_len(next_line) <= _SHORT_LINE_THRESHOLD
            and not _SENTENCE_END_RE.search(next_line)
            and _substantive_len(next_line) >= 2
        ):
            return Chapter(idx, filename, f"{cand} {next_line}", 1)
        # ナンバリング単独でタイトル不明 → しおりにしても役に立たないので諦める
        return None

    # 候補に実体ある文字が 2 つ以上 → タイトル単独として採用
    if _substantive_len(cand) >= 2:
        return Chapter(idx, filename, cand, 1)
    return None


def chapters_by_filename(chapters) -> dict:
    """[Chapter, ...] を {filename: Chapter} に変換する。

    pdf_builder / markdown_writer が「そのページに対応する章」を引くのに使う。
    """
    return {c.filename: c for c in (chapters or [])}


def detect_chapters(results: list[tuple[str, str]]) -> list[Chapter]:
    """OCR 結果のページ列から章エントリを抽出する。

    Args:
        results: [(filename, text), ...] のリスト

    Returns:
        Chapter のリスト。各ページにつき最大 1 件 (最も確度の高い候補) を返す。
    """
    chapters: list[Chapter] = []
    for idx, (filename, text) in enumerate(results):
        if not text:
            continue
        ch = _detect_for_page(idx, filename, text)
        if ch is not None:
            chapters.append(ch)
    return chapters
