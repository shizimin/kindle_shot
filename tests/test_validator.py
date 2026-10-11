"""core/validator.py のテスト（合成画像による解析）"""

import pytest
from conftest import make_blank_page, make_page

from core.validator import PageReadError, analyze_folder


def test_analyze_detects_blank_and_duplicates(tmp_path):
    folder = tmp_path / "v"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png")  # page_001 と同一 → 近似重複
    make_blank_page(folder / "page_003.png")  # 一様 → 白紙

    report = analyze_folder(str(folder))
    assert report["files"] == ["page_001.png", "page_002.png", "page_003.png"]
    assert report["blank_pages"] == ["page_003.png"]
    assert len(report["near_duplicates"]) == 1
    assert report["near_duplicates"][0]["pages"] == ["page_001.png", "page_002.png"]
    assert report["common_size"] == [200, 300]
    assert report["size_mismatch"] == []


def test_analyze_detects_size_mismatch(tmp_path):
    folder = tmp_path / "v"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png")
    make_page(folder / "page_003.png", size=(210, 300), box=(50, 60, 149, 239))

    report = analyze_folder(str(folder))
    assert report["common_size"] == [200, 300]
    assert report["size_mismatch"] == ["page_003.png"]


def test_analyze_reports_progress(tmp_path):
    folder = tmp_path / "v"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png", box=(20, 60, 149, 239))

    seen = []
    analyze_folder(str(folder), on_progress=lambda c, t, f: seen.append((c, t, f)))
    assert seen == [(1, 2, "page_001.png"), (2, 2, "page_002.png")]


def test_analyze_raises_page_read_error_for_corrupt_image(tmp_path):
    folder = tmp_path / "v"
    folder.mkdir()
    (folder / "page_001.png").write_bytes(b"not a real png")

    with pytest.raises(PageReadError) as exc_info:
        analyze_folder(str(folder))
    assert exc_info.value.filename == "page_001.png"
    assert "page_001.png を読めません" in str(exc_info.value)


def test_analyze_empty_folder(tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    report = analyze_folder(str(folder))
    assert report["files"] == []
    assert report["common_size"] is None
