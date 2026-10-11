"""core/boundary_detector.py のテスト（合成画像による余白検出）"""

import numpy as np
from conftest import make_blank_page, make_page
from PIL import Image

from core.boundary_detector import (
    EDGE_IGNORE_PX,
    VARIATION_MAX_MARGIN_RATIO,
    VARIATION_MIN_PAGES,
    FullFrameBoundary,
    ManualBoundary,
    active_runs,
    aggregate_margins,
    combine_margins,
    content_extent,
    content_extent_2d,
    create_detector,
    cross_extent,
    detect_content_box,
    detect_margins,
    detect_margins_folder,
    find_clipped_pages,
    page_variation_margins,
    variation_applied,
)


def _content_image(size=(200, 300), box=(50, 60, 149, 239)):
    from PIL import ImageDraw

    im = Image.new("L", size, 255)
    ImageDraw.Draw(im).rectangle(box, fill=0)
    return im


def _layered_image():
    """DMMブックスのウィンドウモード相当の多層背景画像。

    外周13pxの黒枠 → グレー帯(59) → 白ページ → 黒い本文ブロック2つ。
    本文ブロックの bbox は (100, 120, 251, 301)。
    """
    from PIL import ImageDraw

    im = Image.new("RGB", (400, 500), (0, 0, 0))
    draw = ImageDraw.Draw(im)
    draw.rectangle((13, 13, 386, 486), fill=(59, 59, 59))     # 台紙のグレー帯
    draw.rectangle((33, 33, 366, 466), fill=(255, 255, 255))  # 白いページ
    draw.rectangle((100, 120, 200, 200), fill=(0, 0, 0))      # 本文ブロック
    draw.rectangle((150, 220, 250, 300), fill=(0, 0, 0))
    return im


def test_detect_content_box_finds_black_rectangle():
    box = detect_content_box(_content_image())
    assert box == (50, 60, 150, 240)


def test_detect_content_box_ignores_one_pixel_noise_at_outer_edge():
    """外周の隣ページ由来ノイズを無視し、本文の左端を検出すること。"""
    from PIL import ImageDraw

    im = _content_image(box=(50, 60, 149, 239))
    ImageDraw.Draw(im).line((0, 150, 0, 299), fill=0, width=1)

    assert detect_content_box(im) == (50, 60, 150, 240)


def test_detect_content_box_keeps_thin_line_inside_ignored_edge():
    """外周より内側にある 1px 線は本文として bbox に含めること。"""
    from PIL import ImageDraw

    line_x = EDGE_IGNORE_PX + 1
    im = _content_image(box=(50, 60, 149, 239))
    ImageDraw.Draw(im).line((line_x, 100, line_x, 200), fill=0, width=1)

    assert detect_content_box(im) == (line_x, 60, 150, 240)


def test_detect_margins_full_bleed_nonuniform_starts_inside_ignored_edge():
    """縁まで内容がある非一様な画像は外周の無視幅を余白として返すこと。"""
    from PIL import ImageDraw

    im = Image.new("L", (200, 300), 255)
    ImageDraw.Draw(im).rectangle((0, 0, 199, 149), fill=0)

    assert detect_margins(im) == (EDGE_IGNORE_PX,) * 4


def test_detect_content_box_peels_layered_background():
    """黒枠→グレー帯→白ページと背景を剥がして本文まで到達すること。"""
    assert detect_content_box(_layered_image()) == (100, 120, 251, 301)


def test_detect_content_box_white_page_is_not_over_peeled():
    """白背景のページでは本文 bbox より内側を掘らないこと（現行同等）。"""
    from PIL import ImageDraw

    im = Image.new("L", (200, 300), 255)
    draw = ImageDraw.Draw(im)
    draw.rectangle((50, 60, 120, 100), fill=0)
    draw.rectangle((70, 150, 149, 239), fill=0)
    assert detect_content_box(im) == (50, 60, 150, 240)


def test_detect_content_box_blank_returns_none():
    assert detect_content_box(Image.new("L", (200, 300), 255)) is None


def test_detect_content_box_uniform_dark_returns_none():
    assert detect_content_box(Image.new("RGB", (200, 300), (59, 59, 59))) is None


def test_detect_margins_returns_four_margins():
    margins = detect_margins(_content_image())
    assert margins == (50, 50, 60, 60)


def test_detect_margins_folder_takes_minimum_per_side(tmp_path):
    folder = tmp_path / "pages"
    folder.mkdir()
    # page1: 余白 50/50/60/60、page2: 左に広い内容（余白 20/50/60/60）
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png", box=(20, 60, 149, 239))
    make_blank_page(folder / "page_003.png")  # 検出不能ページ

    margins, report = detect_margins_folder(str(folder))
    assert margins == (20, 50, 60, 60)
    assert report["pages_total"] == 3
    assert report["pages_detected"] == 2
    assert report["pages_skipped"] == ["page_003.png"]
    # 左辺の限界を決めたのは内容が左に広い page_002
    assert report["deciders"]["left"] == "page_002.png"


def test_detect_margins_folder_all_blank(tmp_path):
    folder = tmp_path / "blank"
    folder.mkdir()
    make_blank_page(folder / "page_001.png")
    margins, report = detect_margins_folder(str(folder))
    assert margins is None
    assert report["pages_detected"] == 0


def test_aggregate_margins_excludes_full_bleed_pages():
    """全面表示の表紙・購入画面は外れ値として集計から除外される。"""
    pages = [
        ("cover.png", (0, 0, 0, 0)),
        ("page_001.png", (250, 252, 300, 300)),
        ("page_002.png", (251, 250, 302, 301)),
        ("page_003.png", (249, 251, 301, 300)),
        ("buy.png", (0, 0, 0, 0)),
    ]
    margins, report = aggregate_margins(pages)
    assert margins == (249, 250, 300, 300)
    assert report["outliers"] == ["buy.png", "cover.png"]
    assert report["deciders"]["left"] == "page_003.png"
    assert report["pages_detected"] == 5


def test_aggregate_margins_small_margins_fall_back_to_minimum():
    """全ページの余白が小さいときは除外が起きず、最小値採用に退化する。"""
    pages = [
        ("page_001.png", (5, 6, 5, 5)),
        ("page_002.png", (6, 5, 6, 6)),
        ("page_003.png", (0, 5, 5, 5)),
    ]
    margins, report = aggregate_margins(pages)
    assert margins == (0, 5, 5, 5)
    assert report["outliers"] == []


def test_aggregate_margins_keeps_skipped_pages():
    pages = [("page_001.png", (50, 50, 60, 60)), ("blank.png", None)]
    margins, report = aggregate_margins(pages)
    assert margins == (50, 50, 60, 60)
    assert report["pages_skipped"] == ["blank.png"]
    assert report["outliers"] == []


def test_find_clipped_pages_reports_shortfall(tmp_path):
    folder = tmp_path / "pages"
    folder.mkdir()
    make_page(folder / "page_001.png")  # 余白 50/50/60/60

    clipped = find_clipped_pages(str(folder), (60, 0, 0, 0))
    assert len(clipped) == 1
    assert clipped[0]["filename"] == "page_001.png"
    assert clipped[0]["sides"] == {"left": 10}

    # 余白の範囲内なら切れない
    assert find_clipped_pages(str(folder), (50, 50, 60, 60)) == []


def test_create_detector_mapping():
    assert isinstance(create_detector("manual", 10, 20), ManualBoundary)
    assert isinstance(create_detector("full"), FullFrameBoundary)
    # 廃止された旧方式名は全画面にフォールバックする
    assert isinstance(create_detector("pixel_compare"), FullFrameBoundary)
    assert isinstance(create_detector("canny_edge"), FullFrameBoundary)


# ============================================================
# ページ間変化ベースの UI 帯検出
# ============================================================

def _frac(length, bands):
    """(start, end, peak) の帯を並べた変化率(%) 配列を作る（帯の外は 0）。"""
    frac = np.zeros(length)
    for start, end, peak in bands:
        frac[start:end + 1] = peak
    return frac


def test_active_runs_splits_on_wide_gap():
    frac = _frac(100, [(10, 19, 50.0), (40, 49, 30.0)])
    assert active_runs(frac) == [(10, 19), (40, 49)]


def test_active_runs_merges_narrow_gap():
    """帯の切れ目が GAP_MIN 以下なら 1 本の帯として繋げる（縦書きの行間など）。"""
    frac = _frac(100, [(10, 19, 50.0), (25, 34, 50.0)])
    assert active_runs(frac) == [(10, 34)]


def test_active_runs_ignores_faint_variation():
    """ACTIVE_PCT 以下のわずかな変化（圧縮ノイズ等）は帯にしない。"""
    assert active_runs(_frac(100, [(10, 19, 0.1)])) == []


def test_active_runs_no_variation_returns_empty():
    assert active_runs(np.zeros(100)) == []


def test_content_extent_drops_low_variation_footer():
    """実測値: 本体 93..2024 (57.63%) とフッター 2118..2132 (3.65%)。

    Kindle Cloud Reader 4K キャプチャの行方向。フッター
    (「5/232ページ」等) は本体の 6% しか変化しないので捨てる。
    """
    frac = _frac(2160, [(93, 2024, 57.63), (2118, 2132, 3.65)])
    assert content_extent(frac) == (93, 2024)


def test_content_extent_keeps_vertical_text_columns():
    """実測値: 縦書き本文が列間の隙間で 4 本に割れるが、すべて内容。

    最大変化率は 74.54 / 45.60 / 47.41 / 43.56% で本体の 6 割前後あるため、
    末尾の列も落とさず 468..3393 にまとめる。
    """
    frac = _frac(3840, [(468, 3195, 74.54), (3217, 3245, 45.60),
                        (3267, 3344, 47.41), (3366, 3393, 43.56)])
    assert content_extent(frac) == (468, 3393)


def test_content_extent_returns_none_without_variation():
    assert content_extent(np.zeros(500)) is None


def test_combine_margins_takes_max_per_side():
    # 3840x2160 では上限が左右 576px / 上下 324px なので、どの辺も採用される
    assert combine_margins((10, 20, 30, 40), (468, 446, 93, 135),
                           (3840, 2160)) == (468, 446, 93, 135)


def test_combine_margins_rejects_side_over_max_ratio():
    """辺の長さ × MAX_MARGIN_RATIO を超えた辺だけ、内容ベースへ差し戻す。"""
    size = (200, 300)
    assert VARIATION_MAX_MARGIN_RATIO * size[0] == 90
    assert VARIATION_MAX_MARGIN_RATIO * size[1] == 135
    # 左 90 と上 135 は上限内 → max。右 91 と下 136 は上限超え → 内容ベース
    assert combine_margins((10, 10, 10, 10), (90, 91, 135, 136), size) \
        == (90, 10, 135, 10)


def test_combine_margins_without_variation_keeps_content():
    assert combine_margins((10, 20, 30, 40), None, (800, 1200)) == (10, 20, 30, 40)


def test_variation_applied_reports_only_adopted_extra_margins():
    content = (202, 520, 202, 23)
    variation = (202, 606, 202, 721)
    combined = (202, 606, 202, 23)

    assert variation_applied(content, variation, combined) == (
        False, True, False, False,
    )


def test_variation_applied_rejects_unapplied_variation():
    assert variation_applied(
        (10, 10, 10, 10), (90, 91, 135, 136), (90, 10, 135, 10),
    ) == (True, False, True, False)


def test_variation_applied_returns_false_when_none_is_mixed():
    assert variation_applied((10, 10, 10, 10), None, (10, 10, 10, 10)) \
        == (False,) * 4
    assert variation_applied(
        (10, 10, 10, 10), (20, None, 20, 20), (20, 10, 20, 20),
    ) == (False,) * 4


def _make_viewer_pages(folder, count=12):
    """ビューアUI付きキャプチャを模した合成ページ群を作る。

    - 固定ヘッダー: rows 20..100（毎ページ同一＝変化しない）
    - 固定フッター: rows 1150..1180 の一部（毎ページ同一）
    - ページ番号: rows 1150..1180 / cols 380..400 に偶数ページだけ描く
      （わずかに変化する孤立帯＝捨てられる側）
    - 本文: rows 150..1099 / cols 100..699 に、ページごとに入れ替わる縞
    """
    from PIL import ImageDraw

    folder.mkdir()
    for i in range(1, count + 1):
        im = Image.new("L", (800, 1200), 255)
        draw = ImageDraw.Draw(im)
        draw.rectangle((40, 20, 759, 100), fill=0)      # 固定ヘッダー
        draw.rectangle((300, 1150, 360, 1180), fill=0)  # 固定フッター
        if i % 2 == 0:
            draw.rectangle((380, 1150, 400, 1180), fill=0)  # ページ番号相当
        for b in range(19):
            if (b + i) % 2 == 0:
                top = 150 + b * 50
                draw.rectangle((100, top, 699, top + 49), fill=0)
        im.save(str(folder / f"page_{i:03d}.png"))
    return folder


def _make_slider_viewer_pages(folder, count=12, vertical=False):
    """ページごとに動く進捗スライダー付きの合成ページ群を作る。"""
    from PIL import ImageDraw

    folder.mkdir()
    for i in range(1, count + 1):
        im = Image.new("L", (1200, 800), 255)
        draw = ImageDraw.Draw(im)

        # 本文: rows 30..729 / cols 350..849。ページごとに縞を反転する。
        for band in range(14):
            if (band + i) % 2 == 0:
                top = 30 + band * 50
                draw.rectangle((350, top, 849, top + 49), fill=0)

        # 下部ナビバー: 固定矢印、変化するページ番号、移動するつまみ。
        draw.rectangle((20, 760, 40, 789), fill=0)
        if i % 2 == 0:
            draw.rectangle((60, 760, 90, 789), fill=0)
        thumb_left = round(150 + (i - 1) * (1131 - 150) / (count - 1))
        draw.rectangle((thumb_left, 760, thumb_left + 19, 789), fill=0)

        if vertical:
            im = im.transpose(Image.Transpose.TRANSPOSE)
        im.save(str(folder / f"page_{i:03d}.png"))
    return folder


def test_cross_extent_projects_inside_row_band():
    varies = np.zeros((8, 10), dtype=bool)
    varies[2:5, 3:8] = True
    assert cross_extent(varies, (2, 4), axis=0) == (3, 7)


def test_cross_extent_projects_inside_col_band():
    varies = np.zeros((8, 10), dtype=bool)
    varies[2:6, 3:7] = True
    assert cross_extent(varies, (3, 6), axis=1) == (2, 5)


def test_cross_extent_returns_none_without_variation():
    assert cross_extent(np.zeros((8, 10), dtype=bool), (2, 4), axis=0) is None


def test_content_extent_2d_drops_band_beyond_body():
    varies = np.zeros((60, 40), dtype=bool)
    varies[5:41, 10:30] = True
    varies[50:56, :] = True

    rows, cols, info = content_extent_2d(
        varies, gap_min=5, cross_tolerance=5,
    )

    assert rows == (5, 40)
    assert cols == (10, 29)
    assert info["order"] == "rows"
    assert info["ui_bands"] == [{
        "axis": "row",
        "start": 50,
        "end": 55,
        "cross": [0, 39],
        "body": [10, 29],
    }]


def test_content_extent_2d_keeps_inner_footer():
    varies = np.zeros((60, 40), dtype=bool)
    varies[5:41, 10:30] = True
    varies[45:48, 12:28] = True

    rows, cols, info = content_extent_2d(
        varies, gap_min=2, cross_tolerance=5,
    )

    assert rows == (5, 47)
    assert cols == (10, 29)
    assert info == {"order": "rows", "ui_bands": []}


def test_content_extent_2d_symmetric_vertical_bar():
    varies = np.zeros((60, 40), dtype=bool)
    varies[5:41, 10:30] = True
    varies[50:56, :] = True

    rows, cols, info = content_extent_2d(
        varies.T, gap_min=5, cross_tolerance=5,
    )

    assert rows == (10, 29)
    assert cols == (5, 40)
    assert info["order"] == "cols"
    assert info["ui_bands"] == [{
        "axis": "col",
        "start": 50,
        "end": 55,
        "cross": [0, 39],
        "body": [10, 29],
    }]


def test_content_extent_2d_no_ui_matches_content_extent():
    varies = np.zeros((60, 40), dtype=bool)
    varies[5:41, 10:30] = True
    expected_rows = content_extent(varies.mean(axis=1) * 100)
    expected_cols = content_extent(varies.mean(axis=0) * 100)

    rows, cols, info = content_extent_2d(varies)

    assert rows == expected_rows
    assert cols == expected_cols
    assert info == {"order": "rows", "ui_bands": []}


def test_page_variation_margins_removes_fixed_ui(tmp_path):
    folder = _make_viewer_pages(tmp_path / "viewer")
    margins, report = page_variation_margins(str(folder))

    # 本文は rows 150..1099 / cols 100..699。固定ヘッダー・フッターは削られる
    assert margins == (100, 100, 150, 100)
    assert report["size"] == [800, 1200]
    # 10 枚超なので先頭 2 枚・末尾 2 枚は候補から除く
    assert report["sampled"] == [f"page_{i:03d}.png" for i in range(3, 11)]
    assert report["skipped"] == []
    # 行の帯は「本文」と「ページ番号」の 2 本。採用されるのは本文だけ
    assert [(s, e) for s, e, _peak in report["row_runs"]] \
        == [(150, 1099), (1150, 1180)]


def test_page_variation_margins_removes_moving_slider(tmp_path):
    folder = _make_slider_viewer_pages(tmp_path / "slider")
    margins, report = page_variation_margins(str(folder))

    assert margins == (350, 350, 30, 70)
    assert report["order"] == "rows"
    assert any(
        band["axis"] == "row"
        and (band["start"], band["end"]) == (760, 789)
        for band in report["ui_bands"]
    )


def test_page_variation_margins_removes_vertical_scrollbar(tmp_path):
    folder = _make_slider_viewer_pages(tmp_path / "scrollbar", vertical=True)
    margins, report = page_variation_margins(str(folder))

    assert margins == (30, 70, 350, 350)
    assert report["order"] == "cols"
    assert any(
        band["axis"] == "col"
        and (band["start"], band["end"]) == (760, 789)
        for band in report["ui_bands"]
    )


def test_page_variation_margins_ignores_size_mismatch(tmp_path):
    folder = _make_viewer_pages(tmp_path / "mixed")
    Image.new("L", (400, 600), 255).save(str(folder / "page_005b.png"))

    margins, report = page_variation_margins(str(folder))
    assert margins == (100, 100, 150, 100)
    assert report["skipped"] == ["page_005b.png"]


def test_page_variation_margins_skips_too_few_pages_without_reading(
        tmp_path, monkeypatch):
    folder = tmp_path / "few"
    folder.mkdir()
    for i in range(1, VARIATION_MIN_PAGES):
        make_page(folder / f"page_{i:03d}.png")
    seen = []
    monkeypatch.setattr(
        Image, "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("画像を読んではいけない")
        ),
    )

    margins, report = page_variation_margins(
        str(folder), on_progress=lambda *args: seen.append(args),
    )
    assert margins is None
    assert report["sampled"] == []
    assert report["size"] is None
    assert report["reason"] == "too_few_pages"
    assert report["min_pages"] == VARIATION_MIN_PAGES
    assert seen == []


def test_page_variation_margins_needs_three_readable_pages(tmp_path):
    folder = tmp_path / "unreadable"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png", box=(20, 60, 149, 239))
    for i in range(3, VARIATION_MIN_PAGES + 1):
        (folder / f"page_{i:03d}.png").write_text("not an image", encoding="utf-8")

    margins, report = page_variation_margins(str(folder))
    assert margins is None
    assert report["size"] is None
    assert report["reason"] == "too_few_readable"


def test_page_variation_margins_reports_progress(tmp_path):
    folder = _make_viewer_pages(tmp_path / "progress")
    seen = []
    page_variation_margins(str(folder), on_progress=lambda c, t, f: seen.append((c, t)))
    assert seen[0] == (1, 8)
    assert seen[-1] == (8, 8)


def test_detect_margins_folder_combines_ui_bands(tmp_path):
    """内容ベースだけでは残るビューアUI帯を、変化ベースの合成で削る。"""
    folder = _make_viewer_pages(tmp_path / "viewer")
    margins, report = detect_margins_folder(str(folder))

    # 内容ベースは固定ヘッダー(上20)・フッター(下19)を「内容」と見てしまう
    assert report["content_margins"] == [40, 40, 20, 19]
    assert report["variation_margins"] == [100, 100, 150, 100]
    assert margins == (100, 100, 150, 100)
    assert report["variation_applied"] == [True, True, True, True]
    assert report["variation"]["size"] == [800, 1200]


def test_detect_margins_folder_adopts_wide_variation_margins(tmp_path):
    folder = _make_slider_viewer_pages(tmp_path / "slider")
    margins, report = detect_margins_folder(str(folder))

    assert report["variation_margins"] == [350, 350, 30, 70]
    assert margins == (350, 350, 30, 70)


def test_detect_margins_folder_ui_bands_can_be_disabled(tmp_path):
    folder = _make_viewer_pages(tmp_path / "viewer")
    margins, report = detect_margins_folder(str(folder), ui_bands=False)
    assert margins == (40, 40, 20, 19)
    assert report["variation_margins"] is None
    assert report["variation"] is None


def test_detect_margins_folder_variation_progress_is_separate(tmp_path):
    folder = _make_viewer_pages(tmp_path / "viewer")
    content, variation = [], []
    detect_margins_folder(
        str(folder),
        on_progress=lambda c, t, f: content.append(c),
        on_variation_progress=lambda c, t, f: variation.append(c),
    )
    assert len(content) == 12   # 全ページ走査
    assert len(variation) == 8  # サンプリングした本文ページのみ
