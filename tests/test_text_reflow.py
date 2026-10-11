"""core/text_reflow.py のテスト（ゴールデン）"""

from core.text_reflow import reflow_markdown, reflow_text


def test_japanese_lines_join_without_space():
    src = "これは長い文章でありページ幅の都合で\n改行されてしまった文の続きである。"
    assert reflow_text(src) == "これは長い文章でありページ幅の都合で改行されてしまった文の続きである。"


def test_sentence_end_keeps_paragraph_break():
    src = "これは一つ目の文でありきちんと句点で終わる。\nこれは二つ目の文でありこちらも句点で終わる。"
    assert reflow_text(src) == src


def test_english_lines_join_with_space():
    src = "International cooperation is one of the most\nimportant mechanisms for peace."
    out = reflow_text(src)
    assert out == ("International cooperation is one of the most "
                   "important mechanisms for peace.")


def test_english_hyphen_split_is_absorbed():
    src = "International cooperation is a primary inter-\nnational mechanism for peace."
    out = reflow_text(src)
    assert "international mechanism" in out
    assert "inter-\n" not in out


def test_short_line_stays_independent():
    # 短い行（章タイトル等）は次行と結合しない
    src = "第一章\nこれは本文でありそれなりの長さを持つ一行である"
    out = reflow_text(src)
    assert out.split("\n")[0] == "第一章"


def test_heading_and_list_are_preserved():
    src = "# 見出し\n- 項目1\n- 項目2"
    assert reflow_text(src) == src


def test_blank_lines_collapse_to_one():
    src = "段落一の本文でありこの行はそれなりに長く書いてある。\n\n\n\n段落二の本文でありこの行もそれなりに長く書いてある。"
    out = reflow_text(src)
    assert "\n\n\n" not in out
    assert out.count("\n\n") == 1


def test_roster_line_with_leaders_is_independent():
    src = "山田太郎……刑事\n佐藤花子……検事"
    assert reflow_text(src) == src


def test_reflow_markdown_preserves_frontmatter():
    src = "---\ntitle: \"本\"\ndate: 2026-07-05\n---\n\n本文の一行目でありそれなりの長さを持つ行である\n続きの行である。"
    out = reflow_markdown(src)
    lines = out.split("\n")
    assert lines[0] == "---"
    assert lines[1] == 'title: "本"'
    assert lines[2] == "date: 2026-07-05"
    assert lines[3] == "---"
    # 本文は結合される
    assert "本文の一行目でありそれなりの長さを持つ行である続きの行である。" in out


def test_reflow_markdown_preserves_code_fence():
    src = "```\ncode line 1\ncode line 2\n```"
    assert reflow_markdown(src) == src


def test_reflow_empty():
    assert reflow_text("") == ""
    assert reflow_markdown("") == ""
