"""core/text_cleanup.py のテスト（ゴールデン）"""

from core.text_cleanup import clean_line, clean_text


def test_removes_space_after_japanese_punctuation():
    assert clean_line("食いこませ、 気管") == "食いこませ、気管"
    assert clean_line("なのだ。 しかし") == "なのだ。しかし"


def test_removes_space_between_japanese_chars():
    assert clean_line("こん にちは") == "こんにちは"


def test_keeps_fullwidth_space_indent():
    # 全角スペース（段落頭の字下げ）は保持する
    assert clean_line("　これは字下げされた行") == "　これは字下げされた行"


def test_keeps_single_ascii_space():
    assert clean_line("hello world") == "hello world"


def test_compresses_multiple_ascii_spaces():
    assert clean_line("hello   world") == "hello world"


def test_strips_trailing_whitespace():
    assert clean_line("行末の空白   ") == "行末の空白"


def test_clean_text_preserves_line_structure():
    src = "一行目、 続き\n\n三行目。 続き"
    assert clean_text(src) == "一行目、続き\n\n三行目。続き"


def test_clean_text_empty():
    assert clean_text("") == ""
