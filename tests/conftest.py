"""pytest 共通フィクスチャ・ヘルパー

- 合成ページ画像（白地に黒矩形）の生成
- ユーザーの core/config.json を汚さない設定ファイルの分離
"""

import pytest
from PIL import Image, ImageDraw


def make_page(path, size=(200, 300), box=(50, 60, 149, 239), bg=255, fg=0):
    """白地(bg)に黒矩形(fg)を描いたページ画像を保存する。

    box は PIL の inclusive 座標 (left, top, right, bottom)。
    既定値では余白が 左50 / 右50 / 上60 / 下60 px になる。
    """
    im = Image.new("L", size, bg)
    if box is not None:
        draw = ImageDraw.Draw(im)
        draw.rectangle(box, fill=fg)
    im.save(str(path))
    return path


def make_blank_page(path, size=(200, 300), color=255):
    """一様なページ画像（白紙相当）を保存する。"""
    Image.new("L", size, color).save(str(path))
    return path


@pytest.fixture
def pages_folder(tmp_path):
    """既定の黒矩形ページ3枚が入ったフォルダを返す。"""
    folder = tmp_path / "pages"
    folder.mkdir()
    for i in range(1, 4):
        make_page(folder / f"page_{i:03d}.png")
    return folder


@pytest.fixture
def cover_folder(tmp_path):
    """本文3枚（余白 50/50/60/60）＋全面表示の表紙1枚が入ったフォルダ。

    表紙は内容が四辺の端まで届くため余白 0/0/0/0 になり、余白集計では
    外れ値（全面表示ページ）として扱われる。
    """
    folder = tmp_path / "with_cover"
    folder.mkdir()
    for i in range(1, 4):
        make_page(folder / f"page_{i:03d}.png")
    make_page(folder / "cover.png", box=(0, 0, 199, 149))
    return folder


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """core.config の CONFIG_FILE を一時ファイルへ差し替える。

    テストがユーザーの実設定 (core/config.json) を読んだり
    書き換えたりしないようにする。
    """
    from core import config as config_mod

    cfg_file = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_file))
    return cfg_file
