"""OCRテキストの行内クリーニング（レイアウト由来ノイズの機械除去）

NDLOCR の出力には、日本語の句読点直後や文字と文字のあいだに半角スペースが
混入することが多い（実測: 小説1冊あたり数百箇所）。これは認識ミスではなく
レイアウト由来のノイズなので、辞書や LLM を使わず機械的に除去できる。

対象:
- 日本語の文字/記号に挟まれた半角スペースの削除
  （例「食いこませ、 気管」→「食いこませ、気管」/「なのだ。 しかし」→「なのだ。しかし」）
- 連続する半角スペースを 1 つに圧縮
- 行末の空白除去

対象外:
- 文字認識そのものの誤り（例「絞殺貝」→「絞殺具」）は機械では直せない
- ルビ（振り仮名）は NDLOCR が出力しないため考慮不要
- 全角スペース（段落頭の字下げ等に使われる）は保持する
"""

from __future__ import annotations

import re

from core.text_patterns import CJK_BASE

# 日本語とみなす文字クラス（ひらがな/カタカナ/漢字/CJK記号/全角形/長音・々〆）。
# この範囲の文字に半角スペースが挟まれていたら、OCR が挿入した無意味な空白とみなす。
# CJK_BASE (かな/漢字) に CJK 記号・全角形などを足した広い集合。
_JP = (
    r"　-〿"   # CJK 記号・句読点（、。「」『』（）等）
    + CJK_BASE
    + r"＀-￯"   # 全角英数・記号、半角カナ
    + r"々〆ヵヶ"
)

# 日本語文字に挟まれた半角スペース/タブ（＝削除対象）
_SPACE_BETWEEN_JP = re.compile(rf"(?<=[{_JP}])[ \t]+(?=[{_JP}])")

# 連続する半角スペース（英文中の 1 スペースは保持したいので 2 つ以上のみ圧縮）
_MULTI_SPACE = re.compile(r"[ \t]{2,}")


def clean_line(line: str) -> str:
    """1 行分の OCR テキストから、レイアウト由来の余分な空白を除去する。"""
    s = _SPACE_BETWEEN_JP.sub("", line)
    s = _MULTI_SPACE.sub(" ", s)
    return s.rstrip()


def clean_text(text: str) -> str:
    """複数行の OCR テキストを行ごとにクリーニングする（改行構造は保持）。"""
    if not text:
        return text
    return "\n".join(clean_line(ln) for ln in text.split("\n"))
