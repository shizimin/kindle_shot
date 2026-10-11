"""core/text_stats.py のテスト"""

from core.text_stats import WORD_LIMIT, estimate, format_stats


def test_estimate_ascii_words():
    st = estimate("hello world foo")
    assert st["ascii_words"] == 3
    assert st["cjk_chars"] == 0
    assert st["words"] == 3


def test_estimate_cjk_chars():
    st = estimate("あいう漢字")
    assert st["cjk_chars"] == 5
    assert st["words"] == 5


def test_estimate_mixed_and_whitespace():
    st = estimate("これは pen です\n")
    # chars は空白・改行を除いた文字数
    assert st["chars"] == len("これはpenです")
    assert st["ascii_words"] == 1
    assert st["cjk_chars"] == 5
    assert st["bytes"] == len("これは pen です\n".encode())


def test_estimate_empty_and_none():
    assert estimate("")["words"] == 0
    assert estimate(None)["words"] == 0


def test_format_stats_warns_over_word_limit():
    st = estimate("あ")
    st["words"] = WORD_LIMIT + 1
    msg = format_stats(st)
    assert "50万語を超過" in msg


def test_format_stats_no_warning_under_limit():
    msg = format_stats(estimate("あいうえお"))
    assert "超過" not in msg
