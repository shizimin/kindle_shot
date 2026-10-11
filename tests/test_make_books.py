"""scripts/make_books.py のテスト（蔵書ダンプ + 選書定義 → batch 用 books.json）

生成した books.json が core/pipeline.load_batch_file の検証をそのまま通る
（= batch --books に渡せる）ことを含めて固定する。
"""

import importlib.util
import json
import os

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "make_books.py")
_spec = importlib.util.spec_from_file_location("make_books", _SCRIPT)
make_books = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(make_books)


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def make_dump(tmp_path, items, wrap=True):
    data = {"fetchedAt": "2026-07-29T00:00:00Z", "count": len(items),
            "items": items} if wrap else items
    return write_json(tmp_path / "library.json", data)


# ------------------------------------------------------------
# 部品
# ------------------------------------------------------------

def test_sanitize_title_removes_invalid_filename_chars():
    assert make_books.sanitize_title('本: 上/下 <完全版>?') == "本 上 下 完全版"
    assert make_books.sanitize_title("末尾ピリオド.") == "末尾ピリオド"


def test_volume_number_prefers_last_number_fullwidth():
    assert make_books.volume_number("名探偵コナン（３５）") == 35
    assert make_books.volume_number("Python2年生 体験編（２）") == 2
    assert make_books.volume_number("巻数なし") is None


def test_load_library_tolerates_field_variants_and_dedupes(tmp_path):
    path = make_dump(tmp_path, [
        {"asin": "B001", "title": "本A"},
        {"ASIN": "B002", "productTitle": "本B"},  # 別名フィールド
        {"asin": "B001", "title": "本A重複"},      # asin 重複 → 先勝ち
        {"asin": "B003"},                          # title なし → 無視
        {"asin": "B004", "title": "AI &amp; TECHNOLOGY"},  # HTMLエスケープ解除
    ])
    books = make_books.load_library(path)
    assert [(b["asin"], b["title"]) for b in books] == [
        ("B001", "本A"), ("B002", "本B"), ("B004", "AI & TECHNOLOGY"),
    ]


def test_load_library_accepts_plain_array(tmp_path):
    path = make_dump(tmp_path, [{"asin": "B001", "title": "本A"}], wrap=False)
    assert len(make_books.load_library(path)) == 1


# ------------------------------------------------------------
# 選書（match / sort / take / defaults）
# ------------------------------------------------------------

def _library():
    return [
        {"asin": "B010", "title": "名探偵コナン（１０）"},
        {"asin": "B002", "title": "名探偵コナン（２）"},
        {"asin": "B001", "title": "名探偵コナン（１）"},
        {"asin": "B100", "title": "緋色の研究 新訳シャーロック・ホームズ全集"},
    ]


def test_select_group_volume_sort_and_take(tmp_path):
    groups = make_books.load_selection(write_json(tmp_path / "sel.json", {
        "groups": [{
            "output": "a.json", "match": "^名探偵コナン",
            "sort": "volume", "take": 2,
            "defaults": {"format": "image_pdf"},
        }],
    }))
    books, matched = make_books.select_group(_library(), groups[0])
    assert matched == 3
    # 全角の巻数で数値ソート → 1, 2 巻が採用（文字列順の 1, 10 ではない）
    assert [b["asin"] for b in books] == ["B001", "B002"]
    assert all(b["format"] == "image_pdf" for b in books)


def test_select_group_title_replace(tmp_path):
    groups = make_books.load_selection(write_json(tmp_path / "sel.json", {
        "groups": [{
            "output": "b.json", "match": "緋色の研究",
            "title_replace": [[" 新訳シャーロック・ホームズ全集$", ""]],
        }],
    }))
    books, _ = make_books.select_group(_library(), groups[0])
    assert books[0]["title"] == "緋色の研究"


def test_load_selection_rejects_unknown_key_and_bad_defaults(tmp_path):
    import pytest
    with pytest.raises(ValueError, match="未知のキー"):
        make_books.load_selection(write_json(tmp_path / "s1.json", {
            "groups": [{"output": "a.json", "match": "x", "mach": "typo"}],
        }))
    with pytest.raises(ValueError, match="asin"):
        make_books.load_selection(write_json(tmp_path / "s2.json", {
            "groups": [{"output": "a.json", "match": "x",
                        "defaults": {"asin": "B0"}}],
        }))


# ------------------------------------------------------------
# main（生成物が batch の検証を通ること）
# ------------------------------------------------------------

def test_main_writes_batch_compatible_json(tmp_path, capsys):
    from core.pipeline import load_batch_file
    lib = make_dump(tmp_path, _library())
    sel = write_json(tmp_path / "sel.json", {"groups": [
        {"name": "A群", "output": "books_a.json", "match": "^名探偵コナン",
         "sort": "volume", "take": 2, "defaults": {"format": "image_pdf"}},
        {"name": "B群", "output": "books_b.json", "match": "緋色の研究",
         "defaults": {"format": "markdown", "split_words": 450000}},
    ]})
    out_dir = tmp_path / "out"

    code = make_books.main(["--library", lib, "--select", sel,
                            "--out-dir", str(out_dir)])
    assert code == make_books.EXIT_OK

    # 生成物が batch --books の検証をそのまま通る
    books, err = load_batch_file(str(out_dir / "books_a.json"),
                                 lambda *a, **k: None)
    assert err is None
    assert [b["asin"] for b in books] == ["B001", "B002"]
    assert books[0]["fmt"] == "image_pdf"

    books, err = load_batch_file(str(out_dir / "books_b.json"),
                                 lambda *a, **k: None)
    assert err is None
    assert books[0]["split_words"] == 450000


def test_main_no_match_returns_error(tmp_path, capsys):
    lib = make_dump(tmp_path, _library())
    sel = write_json(tmp_path / "sel.json", {"groups": [
        {"output": "x.json", "match": "存在しない本"},
    ]})
    code = make_books.main(["--library", lib, "--select", sel,
                            "--out-dir", str(tmp_path / "out")])
    assert code == make_books.EXIT_BAD_ARGS
    assert not (tmp_path / "out" / "x.json").exists()


def test_main_dry_run_writes_nothing(tmp_path, capsys):
    lib = make_dump(tmp_path, _library())
    sel = write_json(tmp_path / "sel.json", {"groups": [
        {"output": "a.json", "match": "^名探偵コナン"},
    ]})
    out_dir = tmp_path / "out"
    code = make_books.main(["--library", lib, "--select", sel,
                            "--out-dir", str(out_dir), "--dry-run"])
    assert code == make_books.EXIT_OK
    assert not out_dir.exists()
    assert "名探偵コナン" in capsys.readouterr().out
