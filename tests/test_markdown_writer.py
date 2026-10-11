"""core/markdown_writer.py のテスト

write_markdown（ページ忠実型）と write_notebooklm_markdown（NotebookLM 最適化）
の出力構造を検証する。date 行は実行日で変わるため除いて比較する。
"""

import os

from core.chapter_detector import Chapter
from core.markdown_writer import write_markdown, write_notebooklm_markdown


def _read_without_date(path):
    lines = path.read_text(encoding="utf-8").split("\n")
    return "\n".join(ln for ln in lines if not ln.startswith("date: "))


def test_write_markdown_page_faithful_structure(tmp_path):
    out = tmp_path / "book.md"
    results = [
        ("page_001.png", "一ページ目の本文。"),
        ("page_002.png", "二ページ目の本文。"),
    ]
    chapters = [Chapter(0, "page_001.png", "第一章 出発", 1)]
    success, message = write_markdown(
        results, str(out), title="テスト本", chapters=chapters,
    )
    assert success
    content = _read_without_date(out)
    assert 'title: "テスト本"' in content
    assert "pages: 2" in content
    # ページ忠実型の特徴: page コメントとページ区切り
    assert "<!-- page: page_001.png -->" in content
    assert "<!-- page: page_002.png -->" in content
    assert "\n---\n" in content
    # 章見出し（level 1 → #）
    assert "# 第一章 出発" in content


def test_write_markdown_empty_results(tmp_path):
    success, _ = write_markdown([], str(tmp_path / "x.md"))
    assert not success


def test_write_notebooklm_markdown_structure(tmp_path):
    out = tmp_path / "book.md"
    results = [
        ("page_001.png", "ご利用の端末によっては表示が異なります。"),  # 定型注意書き → 除去
        ("page_002.png", "テスト本"),  # 書名のみのページ → 除去
        ("page_003.png", "第一章 出発\n最初の本文でありページ末で文が途切れて"),
        ("page_004.png", "いたものが次ページへ続く。\n12"),  # 単独ページ番号行 → 除去
    ]
    chapters = [Chapter(2, "page_003.png", "第一章 出発", 1)]
    success, message, written = write_notebooklm_markdown(
        results, str(out), title="テスト本", source="B000TEST", chapters=chapters,
    )
    assert success
    assert written == [str(out)]
    content = _read_without_date(out)

    # フロントマター
    assert 'title: "テスト本"' in content
    assert 'source: "B000TEST"' in content
    # H1 書名 / H2 章
    assert "# テスト本" in content
    assert "## 第一章 出発" in content
    # ページマーカー・区切りを出さない
    assert "<!-- page" not in content
    # 定型注意書き・書名のみページ・単独ページ番号行は落ちる
    assert "ご利用の端末" not in content
    body = content.split("---")[-1]
    assert "\n12\n" not in body
    # ページまたぎの文が結合される
    assert "文が途切れていたものが次ページへ続く。" in content
    # 本文先頭の章タイトル行は H2 と重複しないよう除去される
    assert content.count("第一章 出発") == 1


def test_write_notebooklm_markdown_chapter_matching_title_is_dropped(tmp_path):
    out = tmp_path / "book.md"
    results = [("page_001.png", "テスト本 上巻\n本文が始まる。")]
    # 書名で始まる章タイトルは半扉の誤検出とみなして見出しにしない
    chapters = [Chapter(0, "page_001.png", "テスト本 上巻", 1)]
    success, _, _ = write_notebooklm_markdown(
        results, str(out), title="テスト本", chapters=chapters,
    )
    assert success
    content = _read_without_date(out)
    assert "## テスト本 上巻" not in content


def test_write_notebooklm_markdown_empty_results(tmp_path):
    success, _, written = write_notebooklm_markdown([], str(tmp_path / "x.md"))
    assert not success
    assert written == []


# ------------------------------------------------------------
# 分割出力（split_words）
# ------------------------------------------------------------

def _chapter_results():
    """3章構成・各章が推定100語強のテストデータを作る。"""
    results = [
        ("page_001.png", "第一章 出発\n" + "あ" * 100),
        ("page_002.png", "第二章 航海\n" + "い" * 100),
        ("page_003.png", "第三章 帰還\n" + "う" * 100),
    ]
    chapters = [
        Chapter(0, "page_001.png", "第一章 出発", 1),
        Chapter(1, "page_002.png", "第二章 航海", 1),
        Chapter(2, "page_003.png", "第三章 帰還", 1),
    ]
    return results, chapters


def test_split_under_limit_writes_single_file(tmp_path):
    out = tmp_path / "book.md"
    results, chapters = _chapter_results()
    success, _, written = write_notebooklm_markdown(
        results, str(out), title="テスト本", chapters=chapters,
        split_words=100_000,
    )
    assert success
    assert written == [str(out)]
    assert out.exists()
    assert not (tmp_path / "book_1.md").exists()


def test_split_over_limit_splits_at_chapter_boundaries(tmp_path):
    out = tmp_path / "book.md"
    results, chapters = _chapter_results()
    # 1章≒105語なので、上限150語 → 1章ずつ3ファイルに分かれる
    success, message, written = write_notebooklm_markdown(
        results, str(out), title="テスト本", source="B000TEST",
        chapters=chapters, split_words=150,
    )
    assert success
    assert "3 分割" in message
    assert [os.path.basename(p) for p in written] == [
        "book_1.md", "book_2.md", "book_3.md",
    ]
    assert not out.exists()  # 分割時は <名前>.md は作らない

    part1 = _read_without_date(tmp_path / "book_1.md")
    # 部番号つきのフロントマターと H1
    assert 'title: "テスト本（1/3）"' in part1
    assert "part: 1/3" in part1
    assert 'source: "B000TEST"' in part1
    assert "# テスト本（1/3）" in part1
    # 章境界で切れている（第一章のみを含む）
    assert "## 第一章 出発" in part1
    assert "第二章" not in part1

    part3 = _read_without_date(tmp_path / "book_3.md")
    assert "part: 3/3" in part3
    assert "## 第三章 帰還" in part3


def test_split_two_chapters_fit_in_one_part(tmp_path):
    out = tmp_path / "book.md"
    results, chapters = _chapter_results()
    # 上限250語 → 2章 + 1章の2ファイル
    success, _, written = write_notebooklm_markdown(
        results, str(out), title="テスト本", chapters=chapters,
        split_words=250,
    )
    assert success
    assert len(written) == 2
    part1 = _read_without_date(tmp_path / "book_1.md")
    assert "## 第一章 出発" in part1
    assert "## 第二章 航海" in part1
    assert "第三章" not in part1


def test_split_oversize_chapter_falls_back_to_paragraphs(tmp_path):
    out = tmp_path / "book.md"
    # 章見出しのない本文で、段落4つ・計200語超
    body = "\n\n".join("段落" + "か" * 50 for _ in range(4))
    results = [("page_001.png", body)]
    success, _, written = write_notebooklm_markdown(
        results, str(out), title="テスト本", split_words=120,
    )
    assert success
    assert len(written) >= 2  # 段落境界でフォールバック分割される
    # 全部数を合わせると段落4つが揃っている
    joined = "".join(
        (tmp_path / f"book_{i}.md").read_text(encoding="utf-8")
        for i in range(1, len(written) + 1)
    )
    assert joined.count("段落") == 4
