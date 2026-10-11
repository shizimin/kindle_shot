"""core/trimmer.py のテスト"""

from conftest import make_page
from PIL import Image

from core.trimmer import process_images, trim_margins


def test_trim_margins_basic():
    im = Image.new("L", (200, 300), 255)
    out = trim_margins(im, 10, 20, 30, 40)
    # 幅 = 200 - 10 - 20, 高さ = 300 - 30 - 40
    assert out.size == (170, 230)


def test_trim_margins_zero_is_noop_size():
    im = Image.new("L", (200, 300), 255)
    assert trim_margins(im, 0, 0, 0, 0).size == (200, 300)


def test_trim_margins_degenerate_returns_copy():
    im = Image.new("L", (100, 100), 255)
    out = trim_margins(im, 60, 60, 0, 0)  # left >= right になる
    assert out.size == (100, 100)


def test_process_images_writes_trimmed_files(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    for i in range(1, 4):
        make_page(src / f"page_{i:03d}.png")

    success, message = process_images(str(src), str(dst), 10, 10, 20, 20)
    assert success
    outs = sorted(p.name for p in dst.glob("*.png"))
    assert outs == ["page_001.png", "page_002.png", "page_003.png"]
    with Image.open(dst / "page_001.png") as im:
        assert im.size == (180, 260)


def test_process_images_empty_folder(tmp_path):
    src = tmp_path / "empty"
    src.mkdir()
    success, message = process_images(str(src), str(tmp_path / "out"), 0, 0, 0, 0)
    assert not success


def test_process_images_reports_progress_in_name_order(tmp_path):
    """ページ順（ファイル名昇順）で処理されること。

    os.listdir は順序保証がないため、名前順ソートが必要（回帰テスト）。
    """
    src = tmp_path / "src"
    src.mkdir()
    names = [f"page_{i:03d}.png" for i in range(1, 6)]
    for name in names:
        make_page(src / name)

    seen = []
    success, _ = process_images(
        str(src), str(tmp_path / "out"), 0, 0, 0, 0,
        on_progress=lambda cur, total, fn: seen.append(fn),
    )
    assert success
    assert seen == names
