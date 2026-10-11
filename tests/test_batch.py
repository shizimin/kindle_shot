"""batch コマンドの契約テスト（複数冊の一括実行）

Win32 実機依存の run_book はスタブに差し替え、
- load_batch_file: JSON の検証（未知キー・重複タイトル・asin/url 必須・形式）
- run_batch: スキップ再開・失敗続行・stop-on-error・本ごとの設定上書き
- cli batch: JSON Lines イベントと終了コード
を固定する。
"""

import json
import os

import cli
from core import pipeline

# ------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------

def collect_emit():
    """emit と、記録先の events リストを返す。"""
    events = []

    def emit(event, human=None, **fields):
        events.append({"event": event, **fields})

    return emit, events


def by_name(events, name):
    return [e for e in events if e["event"] == name]


def make_fake_run_book(calls, fail_titles=()):
    """run_book の代役。呼び出しを記録し、出力ファイルを作って EXIT_OK を返す。

    fail_titles に含まれるタイトルはウィンドウ未検出として失敗させる。
    """
    def fake(**kwargs):
        calls.append(kwargs)
        title = kwargs["title"]
        if title in fail_titles:
            return pipeline.EXIT_WINDOW_NOT_FOUND
        out = kwargs["output"]
        fmt = kwargs.get("fmt", "searchable_pdf")
        ext = ".md" if fmt == "markdown" else ".pdf"
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, pipeline._ensure_ext(title, ext)),
                  "w", encoding="utf-8") as f:
            f.write("x")
        return pipeline.EXIT_OK

    return fake


def write_books(tmp_path, data, name="books.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# ------------------------------------------------------------
# load_batch_file: 検証
# ------------------------------------------------------------

def test_load_valid_array_resolves_titles(tmp_path):
    path = write_books(tmp_path, [
        {"asin": "B0ABC", "title": "吾輩は猫である"},
        {"asin": "B0DEF"},  # title 省略 → asin を代用
    ])
    emit, events = collect_emit()
    books, code = pipeline.load_batch_file(path, emit)
    assert code is None
    assert [b["title"] for b in books] == ["吾輩は猫である", "B0DEF"]
    assert not by_name(events, "error")


def test_load_books_wrapper_form(tmp_path):
    path = write_books(tmp_path, {"books": [{"asin": "B0ABC", "title": "T"}]})
    books, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code is None
    assert len(books) == 1


def test_load_missing_file():
    _, code = pipeline.load_batch_file("does_not_exist.json", lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ not json", encoding="utf-8")
    emit, events = collect_emit()
    books, code = pipeline.load_batch_file(str(path), emit)
    assert books is None
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")


def test_load_empty_list(tmp_path):
    path = write_books(tmp_path, [])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_unknown_key_is_rejected(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0ABC", "max_page": 100}])
    emit, events = collect_emit()
    _, code = pipeline.load_batch_file(path, emit)
    assert code == cli.EXIT_BAD_ARGS
    assert any("max_page" in e["message"] for e in by_name(events, "error"))


def test_load_requires_asin_or_url(tmp_path):
    path = write_books(tmp_path, [{"title": "タイトルのみ"}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_url_without_title_is_rejected(tmp_path):
    path = write_books(tmp_path, [{"url": "https://example.com/book"}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_duplicate_titles_rejected(tmp_path):
    path = write_books(tmp_path, [
        {"asin": "B0ABC", "title": "同名"},
        {"asin": "B0DEF", "title": "同名"},
    ])
    emit, events = collect_emit()
    _, code = pipeline.load_batch_file(path, emit)
    assert code == cli.EXIT_BAD_ARGS
    assert any("重複" in e["message"] for e in by_name(events, "error"))


def test_load_bad_format_value(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0ABC", "format": "docx"}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_min_margins_accepts_array_and_string(tmp_path):
    path = write_books(tmp_path, [
        {"asin": "B0A", "title": "配列", "min_margins": [0, 0, 80, 80]},
        {"asin": "B0B", "title": "文字列", "min_margins": "0,0,80,80"},
    ])
    books, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code is None
    assert books[0]["min_margins"] == (0, 0, 80, 80)
    assert books[1]["min_margins"] == (0, 0, 80, 80)


def test_load_ui_bands_accepts_bool(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0A", "ui_bands": False}])
    books, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code is None
    assert books[0]["ui_bands"] is False


def test_load_ui_bands_rejects_non_bool(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0A", "ui_bands": "no"}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_bool_not_accepted_as_int(tmp_path):
    # max_pages に true を渡す → bool は整数扱いしない
    path = write_books(tmp_path, [{"asin": "B0A", "max_pages": True}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_page_turn_accepts_pagedown(tmp_path):
    # right/left 以外のページ送りキー（ブラウザ型ビューアの上下めくり）も通る
    path = write_books(tmp_path, [{"asin": "B0A", "page_turn": "pagedown"}])
    books, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code is None
    assert books[0]["page_turn"] == "pagedown"


def test_load_page_turn_rejects_unknown_key(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0A", "page_turn": "enter"}])
    _, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code == cli.EXIT_BAD_ARGS


def test_load_split_words_accepted(tmp_path):
    path = write_books(tmp_path, [{"asin": "B0A", "split_words": 450000}])
    books, code = pipeline.load_batch_file(path, lambda *a, **k: None)
    assert code is None
    assert books[0]["split_words"] == 450000


# ------------------------------------------------------------
# run_batch: 実行制御（run_book はスタブ）
# ------------------------------------------------------------

def test_run_batch_happy_path(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    books = [{"asin": "B0A", "title": "本1"}, {"asin": "B0B", "title": "本2"}]

    emit, events = collect_emit()
    code = pipeline.run_batch(books, output=str(out),
                              defaults={"fmt": "searchable_pdf"}, emit=emit)
    assert code == cli.EXIT_OK
    assert len(calls) == 2

    start = by_name(events, "batch_start")[0]
    assert start["total_books"] == 2
    assert len(by_name(events, "book_start")) == 2
    results = by_name(events, "book_result")
    assert all(r["ok"] for r in results)

    summary = by_name(events, "batch_summary")[0]
    assert summary["ok"] is True
    assert summary["succeeded"] == 2
    assert summary["failed"] == 0
    assert summary["skipped"] == 0


def test_run_batch_skips_completed_books(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    out.mkdir()
    # 本1 は既に出力済み（.pdf）→ スキップされるはず
    (out / "本1.pdf").write_text("done", encoding="utf-8")
    books = [{"asin": "B0A", "title": "本1"}, {"asin": "B0B", "title": "本2"}]

    emit, events = collect_emit()
    code = pipeline.run_batch(books, output=str(out),
                              defaults={"fmt": "searchable_pdf"}, emit=emit)
    assert code == cli.EXIT_OK
    # run_book は 本2 についてのみ呼ばれる
    assert [c["title"] for c in calls] == ["本2"]
    assert by_name(events, "book_skipped")[0]["title"] == "本1"
    summary = by_name(events, "batch_summary")[0]
    assert summary["skipped"] == 1
    assert summary["succeeded"] == 1


def test_run_batch_overwrite_reprocesses_completed(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    out.mkdir()
    (out / "本1.pdf").write_text("done", encoding="utf-8")
    books = [{"asin": "B0A", "title": "本1"}]

    emit, events = collect_emit()
    code = pipeline.run_batch(books, output=str(out), overwrite=True,
                              defaults={"fmt": "searchable_pdf"}, emit=emit)
    assert code == cli.EXIT_OK
    assert [c["title"] for c in calls] == ["本1"]  # スキップされず再処理
    assert not by_name(events, "book_skipped")


def test_run_batch_continues_on_failure(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book",
                        make_fake_run_book(calls, fail_titles={"本2"}))
    out = tmp_path / "out"
    books = [{"asin": "B0A", "title": "本1"},
             {"asin": "B0B", "title": "本2"},
             {"asin": "B0C", "title": "本3"}]

    emit, events = collect_emit()
    code = pipeline.run_batch(books, output=str(out),
                              defaults={"fmt": "searchable_pdf"}, emit=emit)
    assert code == cli.EXIT_ERROR  # 1冊失敗 → 非0
    assert len(calls) == 3  # 失敗後も続行

    summary = by_name(events, "batch_summary")[0]
    assert summary["succeeded"] == 2
    assert summary["failed"] == 1
    assert summary["unprocessed"] == 0
    failed = [r for r in summary["results"] if not r["ok"]]
    assert failed[0]["title"] == "本2"
    assert failed[0]["exit_code"] == cli.EXIT_WINDOW_NOT_FOUND


def test_run_batch_stop_on_error(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book",
                        make_fake_run_book(calls, fail_titles={"本2"}))
    out = tmp_path / "out"
    books = [{"asin": "B0A", "title": "本1"},
             {"asin": "B0B", "title": "本2"},
             {"asin": "B0C", "title": "本3"}]

    emit, events = collect_emit()
    code = pipeline.run_batch(books, output=str(out), stop_on_error=True,
                              defaults={"fmt": "searchable_pdf"}, emit=emit)
    assert code == cli.EXIT_ERROR
    assert [c["title"] for c in calls] == ["本1", "本2"]  # 本3 は未処理

    summary = by_name(events, "batch_summary")[0]
    assert summary["failed"] == 1
    assert summary["unprocessed"] == 1


def test_run_batch_per_book_overrides_defaults(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    # 全体既定は searchable_pdf、本2 だけ markdown に上書き
    books = [{"asin": "B0A", "title": "本1"},
             {"asin": "B0B", "title": "本2", "fmt": "markdown",
              "page_turn": "left"}]

    pipeline.run_batch(books, output=str(out),
                       defaults={"fmt": "searchable_pdf", "page_turn": None},
                       emit=lambda *a, **k: None)
    assert calls[0]["fmt"] == "searchable_pdf"
    assert calls[1]["fmt"] == "markdown"
    assert calls[1]["page_turn"] == "left"
    # 本2 の出力は .md
    assert (out / "本2.md").exists()


def test_run_batch_skip_uses_per_book_format_extension(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    out.mkdir()
    # markdown 指定の本は .md が既にあればスキップされる
    (out / "本M.md").write_text("done", encoding="utf-8")
    books = [{"asin": "B0M", "title": "本M", "fmt": "markdown"}]

    emit, events = collect_emit()
    pipeline.run_batch(books, output=str(out), emit=emit)
    assert calls == []
    assert by_name(events, "book_skipped")[0]["title"] == "本M"


def test_run_batch_skip_recognizes_split_markdown_output(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    out = tmp_path / "out"
    out.mkdir()
    # split_words による分割出力（<title>_1.md）でも完成済みとしてスキップされる
    (out / "本S_1.md").write_text("done", encoding="utf-8")
    books = [{"asin": "B0S", "title": "本S", "fmt": "markdown",
              "split_words": 450000}]

    emit, events = collect_emit()
    pipeline.run_batch(books, output=str(out), emit=emit)
    assert calls == []
    skipped = by_name(events, "book_skipped")[0]
    assert skipped["title"] == "本S"
    assert skipped["output"].endswith("本S_1.md")


# ------------------------------------------------------------
# cli batch: 統合（--json）
# ------------------------------------------------------------

def test_cli_batch_json(tmp_path, monkeypatch, isolated_config, capsys):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    path = write_books(tmp_path, [
        {"asin": "B0A", "title": "本1"},
        {"asin": "B0B", "title": "本2"},
    ])
    out = tmp_path / "out"

    code = cli.main(["batch", "--books", path, "--out", str(out), "--json"])
    assert code == cli.EXIT_OK

    lines = capsys.readouterr().out.splitlines()
    events = [json.loads(x) for x in lines if x.strip()]
    assert by_name(events, "batch_start")[0]["total_books"] == 2
    assert by_name(events, "batch_summary")[0]["succeeded"] == 2
    # CLI の --format 既定（searchable_pdf）が全本に渡る
    assert all(c["fmt"] == "searchable_pdf" for c in calls)


def test_cli_batch_ui_bands_default_and_flag(
        tmp_path, monkeypatch, isolated_config, capsys):
    calls = []
    monkeypatch.setattr(pipeline, "run_book", make_fake_run_book(calls))
    path = write_books(tmp_path, [{"asin": "B0A", "title": "本1"}])

    code = cli.main([
        "batch", "--books", path, "--out", str(tmp_path / "out_default"), "--json",
    ])
    assert code == cli.EXIT_OK
    assert calls[-1]["ui_bands"] is True

    code = cli.main([
        "batch", "--books", path, "--out", str(tmp_path / "out_disabled"),
        "--no-ui-bands", "--json",
    ])
    assert code == cli.EXIT_OK
    assert calls[-1]["ui_bands"] is False
    capsys.readouterr()


def test_cli_batch_bad_file_returns_bad_args(tmp_path, isolated_config, capsys):
    code = cli.main(["batch", "--books", str(tmp_path / "nope.json"),
                     "--out", str(tmp_path / "out"), "--json"])
    assert code == cli.EXIT_BAD_ARGS
    events = [json.loads(x) for x in capsys.readouterr().out.splitlines()
              if x.strip()]
    assert by_name(events, "error")
