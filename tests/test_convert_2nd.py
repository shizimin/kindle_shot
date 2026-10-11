"""scripts/convert_2nd.py のテスト（トリミング済み画像から2形式目を作る）

スキップ判定（出力済み・_trimmed なし）が batch 本体と揃っていること、
cli.py convert に渡す引数、失敗時の終了コードを固定する。
実際の OCR / PDF 生成は走らせない（convert_one をモックする）。
"""

import importlib.util
import json
import os

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "convert_2nd.py")
_spec = importlib.util.spec_from_file_location("convert_2nd", _SCRIPT)
convert_2nd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(convert_2nd)


def write_books(tmp_path, books):
    path = tmp_path / "books.json"
    path.write_text(json.dumps(books, ensure_ascii=False), encoding="utf-8")
    return str(path)


def make_out(tmp_path, trimmed=(), outputs=()):
    """保存先フォルダを作り、<書名>_trimmed と完成済み出力を置く。"""
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    for title in trimmed:
        (out / f"{title}_trimmed").mkdir()
    for name in outputs:
        (out / name).write_bytes(b"x")
    return out


# ------------------------------------------------------------
# plan（実行対象とスキップの振り分け）
# ------------------------------------------------------------

def test_plan_skips_missing_trimmed_and_existing_output(tmp_path):
    out = make_out(tmp_path, trimmed=["本A", "本B"], outputs=["本B.md"])
    books = [{"title": "本A"}, {"title": "本B"}, {"title": "本C"}]
    rows = convert_2nd.plan(books, str(out), "markdown")
    assert [r[3] for r in rows] == [None, "出力済み", "トリミング画像がありません"]


def test_plan_uses_extension_of_target_format(tmp_path):
    """1形式目が .pdf でも、2形式目が markdown なら .md の有無で判定する。"""
    out = make_out(tmp_path, trimmed=["本A"], outputs=["本A.pdf"])
    rows = convert_2nd.plan([{"title": "本A"}], str(out), "markdown")
    assert rows[0][3] is None  # .pdf があっても markdown はまだ無いので実行対象
    rows = convert_2nd.plan([{"title": "本A"}], str(out), "searchable_pdf")
    assert rows[0][3] == "出力済み"


def test_plan_treats_split_markdown_as_done(tmp_path):
    """split_words で <書名>_1.md に分割された本も出力済みとみなす（batch と同じ）。"""
    out = make_out(tmp_path, trimmed=["本A"], outputs=["本A_1.md"])
    rows = convert_2nd.plan([{"title": "本A"}], str(out), "markdown")
    assert rows[0][3] == "出力済み"


# ------------------------------------------------------------
# main（引数の組み立て・終了コード）
# ------------------------------------------------------------

def test_main_passes_asin_as_source_and_skips_done(tmp_path, monkeypatch, capsys):
    out = make_out(tmp_path, trimmed=["本A", "本B"], outputs=["本B.md"])
    books = write_books(tmp_path, [
        {"asin": "B001", "title": "本A"},
        {"asin": "B002", "title": "本B"},
    ])

    calls = []

    def fake_convert(trimmed, out_dir, fmt, title, source, log):
        calls.append((os.path.basename(trimmed), fmt, title, source))
        (tmp_path / "out" / f"{title}.md").write_bytes(b"x")
        return 0

    monkeypatch.setattr(convert_2nd, "convert_one", fake_convert)
    code = convert_2nd.main(["--books", books, "--out", str(out),
                             "--format", "markdown"])
    assert code == convert_2nd.EXIT_OK
    # 本B は出力済みなので呼ばれない。本A は asin が --source に渡る
    assert calls == [("本A_trimmed", "markdown", "本A", "B001")]
    assert "スキップ（出力済み）: 本B" in capsys.readouterr().out


def test_main_returns_error_when_a_book_fails(tmp_path, monkeypatch):
    out = make_out(tmp_path, trimmed=["本A"])
    books = write_books(tmp_path, [{"asin": "B001", "title": "本A"}])
    monkeypatch.setattr(convert_2nd, "convert_one",
                        lambda *a, **k: convert_2nd.EXIT_ERROR)
    assert convert_2nd.main(["--books", books, "--out", str(out),
                             "--format", "markdown"]) == convert_2nd.EXIT_ERROR


def test_main_returns_error_when_output_missing_despite_exit_zero(tmp_path, monkeypatch):
    """exit 0 でも出力ファイルが無ければ失敗として数える。"""
    out = make_out(tmp_path, trimmed=["本A"])
    books = write_books(tmp_path, [{"asin": "B001", "title": "本A"}])
    monkeypatch.setattr(convert_2nd, "convert_one", lambda *a, **k: 0)
    assert convert_2nd.main(["--books", books, "--out", str(out),
                             "--format", "markdown"]) == convert_2nd.EXIT_ERROR


def test_main_dry_run_does_not_convert(tmp_path, monkeypatch, capsys):
    out = make_out(tmp_path, trimmed=["本A"])
    books = write_books(tmp_path, [{"asin": "B001", "title": "本A"}])

    def boom(*a, **k):
        raise AssertionError("dry-run で変換してはいけない")

    monkeypatch.setattr(convert_2nd, "convert_one", boom)
    code = convert_2nd.main(["--books", books, "--out", str(out),
                             "--format", "markdown", "--dry-run"])
    assert code == convert_2nd.EXIT_OK
    assert "実行予定: 本A" in capsys.readouterr().out


def test_main_rejects_bad_books_file_and_missing_out(tmp_path, capsys):
    out = make_out(tmp_path, trimmed=["本A"])
    # asin も url も無い本 → load_batch_file が弾く
    bad = write_books(tmp_path, [{"title": "本A"}])
    assert convert_2nd.main(["--books", bad, "--out", str(out),
                             "--format", "markdown"]) == convert_2nd.EXIT_BAD_ARGS

    good = write_books(tmp_path, [{"asin": "B001", "title": "本A"}])
    assert convert_2nd.main(["--books", good, "--out", str(tmp_path / "nope"),
                             "--format", "markdown"]) == convert_2nd.EXIT_BAD_ARGS


def test_main_rejects_unknown_format(tmp_path):
    out = make_out(tmp_path, trimmed=["本A"])
    books = write_books(tmp_path, [{"asin": "B001", "title": "本A"}])
    with pytest.raises(SystemExit):
        convert_2nd.main(["--books", books, "--out", str(out),
                          "--format", "docx"])
