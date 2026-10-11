"""core/chapter_detector.py のテスト（ゴールデン）

text_patterns への正規表現集約時の差分検知を兼ねる。
"""

from core.chapter_detector import detect_chapters


def _detect_one(text, filename="page_001.png"):
    chapters = detect_chapters([(filename, text)])
    return chapters[0] if chapters else None


def test_strong_pattern_chapter():
    ch = _detect_one("第一章 出発\n本文がここから始まる。")
    assert ch is not None
    assert ch.title == "第一章 出発"
    assert ch.level == 1


def test_strong_pattern_prologue():
    ch = _detect_one("プロローグ\nその夜は静かだった。")
    assert ch is not None
    assert ch.title == "プロローグ"
    assert ch.level == 1


def test_strong_pattern_english_chapter():
    ch = _detect_one("Chapter 3\nIt was a dark night.")
    assert ch is not None
    assert ch.level == 1


def test_section_pattern_is_level2():
    ch = _detect_one("第二節\n本文が続く。")
    assert ch is not None
    assert ch.level == 2


def test_page_number_only_is_ignored():
    assert _detect_one("12") is None
    assert _detect_one("- 12 -") is None


def test_decorated_page_number_then_chapter():
    # ページ番号行を飛ばして次の行の強パターンを拾う
    ch = _detect_one("12\n第三章 帰還\n本文。")
    assert ch is not None
    assert ch.title == "第三章 帰還"


def test_sentence_line_is_not_chapter():
    assert _detect_one("彼は疲れていた。\nそれでも歩き続けた。") is None


def test_dialogue_start_is_rejected():
    assert _detect_one("「おはよう」と彼は言った\n本文。") is None


def test_decor_symbols_are_stripped_from_title():
    ch = _detect_one("▲ エピローグ\n終わりの始まり。")
    assert ch is not None
    assert ch.title == "エピローグ"


def test_numbering_joins_next_short_line():
    ch = _detect_one("一、\n出発の朝\n本文が続いていく。")
    assert ch is not None
    assert ch.title == "一、 出発の朝"


def test_long_first_line_is_body_not_heading():
    long_line = "これは章タイトルとしては長すぎる本文の続きのような一行である"
    assert _detect_one(f"{long_line}\n次の行。") is None


def test_detect_chapters_multiple_pages():
    results = [
        ("p1.png", "第一章 始まり\n本文。"),
        ("p2.png", "ただの本文が続くページである。\n続き。"),
        ("p3.png", "エピローグ\n終わり。"),
    ]
    chapters = detect_chapters(results)
    assert [c.filename for c in chapters] == ["p1.png", "p3.png"]
    assert chapters[0].page_index == 0
    assert chapters[1].page_index == 2
