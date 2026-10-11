"""core/image_files.py のテスト"""

import pytest
from conftest import make_page

from core.image_files import (
    IMAGE_EXTENSIONS,
    OCR_IMAGE_EXTENSIONS,
    PDF_IMAGE_EXTENSIONS,
    clear_images,
    list_images,
)


def test_list_images_sorted_and_filtered(tmp_path):
    (tmp_path / "b.png").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "c.txt").write_text("not an image")
    (tmp_path / "d.PNG").write_bytes(b"")  # 大文字拡張子も対象
    assert list_images(str(tmp_path)) == ["a.jpg", "b.png", "d.PNG"]


def test_list_images_custom_extensions(tmp_path):
    (tmp_path / "a.gif").write_bytes(b"")
    (tmp_path / "b.tiff").write_bytes(b"")
    # OCR は gif 非対応・tiff 対応
    assert list_images(str(tmp_path), OCR_IMAGE_EXTENSIONS) == ["b.tiff"]
    # PDF は png/jpg/jpeg のみ
    assert list_images(str(tmp_path), PDF_IMAGE_EXTENSIONS) == []


def test_list_images_missing_folder_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        list_images(str(tmp_path / "nope"))


def test_clear_images_removes_and_counts(tmp_path):
    for i in range(3):
        make_page(tmp_path / f"page_{i}.png")
    (tmp_path / "keep.txt").write_text("keep me")
    assert clear_images(str(tmp_path)) == 3
    assert list_images(str(tmp_path)) == []
    assert (tmp_path / "keep.txt").exists()


def test_extension_sets_are_intentionally_different():
    # 3 定数は用途別の別集合 (統一しない)。変更時はこのテストを見直すこと。
    assert ".gif" in IMAGE_EXTENSIONS
    assert ".gif" not in OCR_IMAGE_EXTENSIONS
    assert ".tiff" in OCR_IMAGE_EXTENSIONS
    assert ".bmp" not in PDF_IMAGE_EXTENSIONS
