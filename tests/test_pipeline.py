"""core/pipeline.py のテスト

CLI 経由の統合的な検証は test_cli_contract.py が担う。ここでは
GUI からも直接呼ばれる共有ヘルパーの単体挙動を検証する。
"""

from conftest import make_page

from core.pipeline import (
    EXIT_BAD_ARGS,
    EXIT_NO_IMAGES,
    EXIT_OK,
    check_input_folder,
    clear_output_images,
    relax_margins,
    run_trim,
)


def _collect_emit(events):
    def emit(event, human=None, **fields):
        events.append({"event": event, "human": human, **fields})
    return emit


# ------------------------------------------------------------
# relax_margins（トリム緩め方の唯一の式）
# ------------------------------------------------------------

def test_relax_margins_subtracts_safety():
    assert relax_margins((50, 50, 60, 60), safety=8) == (42, 42, 52, 52)


def test_relax_margins_clamps_to_zero():
    assert relax_margins((5, 0, 60, 60), safety=8) == (0, 0, 52, 52)


def test_relax_margins_applies_min_margins():
    # 検出値-8 と min_margins の大きい方
    assert relax_margins((50, 50, 60, 60), safety=8,
                         min_margins=(0, 0, 80, 80)) == (42, 42, 80, 80)


def test_relax_margins_none_min_margins():
    assert relax_margins((50, 50, 60, 60), safety=0) == (50, 50, 60, 60)


# ------------------------------------------------------------
# check_input_folder / clear_output_images
# ------------------------------------------------------------

def test_check_input_folder_ok(pages_folder):
    events = []
    assert check_input_folder(str(pages_folder), _collect_emit(events)) is None
    assert events == []


def test_check_input_folder_missing(tmp_path):
    events = []
    code = check_input_folder(str(tmp_path / "nope"), _collect_emit(events))
    assert code == EXIT_BAD_ARGS
    assert events[0]["event"] == "error"


def test_check_input_folder_empty(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    events = []
    code = check_input_folder(str(empty), _collect_emit(events))
    assert code == EXIT_NO_IMAGES


def test_clear_output_images_blocks_without_overwrite(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    make_page(out / "old.png")
    events = []
    code = clear_output_images(str(out), False, _collect_emit(events))
    assert code == EXIT_BAD_ARGS
    assert "--overwrite" in events[0]["message"]
    assert (out / "old.png").exists()


def test_clear_output_images_removes_with_overwrite(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    make_page(out / "old.png")
    events = []
    code = clear_output_images(str(out), True, _collect_emit(events))
    assert code is None
    assert not (out / "old.png").exists()
    assert events[0]["event"] == "cleaned_output"
    assert events[0]["removed"] == 1


def test_clear_output_images_no_folder_is_ok(tmp_path):
    assert clear_output_images(str(tmp_path / "new"), False) is None


# ------------------------------------------------------------
# run_trim を GUI 相当の呼び方 (emit 省略・タプル引数) で実行
# ------------------------------------------------------------

def test_run_trim_with_explicit_margins_no_emit(pages_folder, tmp_path):
    out = tmp_path / "out"
    code = run_trim(str(pages_folder), str(out),
                    margins=(10, 10, 10, 10), no_check=True)
    assert code == EXIT_OK
    assert sorted(p.name for p in out.glob("*.png")) == [
        "page_001.png", "page_002.png", "page_003.png",
    ]


def test_run_trim_auto_detect_events(pages_folder, tmp_path):
    events = []
    code = run_trim(str(pages_folder), str(tmp_path / "out"),
                    margins=None, safety=8, emit=_collect_emit(events))
    assert code == EXIT_OK
    detected = [e for e in events if e["event"] == "margins_detected"][0]
    assert detected["margins"] == [42, 42, 52, 52]
    assert detected["min_margins"] is None
    assert detected["report"]["outliers"] == []
    assert detected["variation_applied"] == [False, False, False, False]
    assert detected["report"]["variation"]["reason"] == "too_few_pages"
    assert "ページ数が 8 枚未満のため、ビューアのUI帯の自動検出は行いません" \
        in detected["human"]
    # 切れるページがなければ passthrough イベントは出ない
    assert not [e for e in events if e["event"] == "passthrough_pages"]


def test_run_trim_reports_applied_and_rejected_variation_sides(
        tmp_path, monkeypatch):
    from core import boundary_detector

    folder = tmp_path / "pages"
    folder.mkdir()
    filenames = []
    for i in range(1, 9):
        filename = f"page_{i:03d}.png"
        make_page(folder / filename)
        filenames.append(filename)

    content = (202, 520, 202, 23)
    monkeypatch.setattr(
        boundary_detector,
        "folder_page_margins",
        lambda *_args, **_kwargs: [(name, content) for name in filenames],
    )
    monkeypatch.setattr(
        boundary_detector,
        "page_variation_margins",
        lambda *_args, **_kwargs: (
            (202, 606, 202, 721),
            {"sampled": filenames, "skipped": [], "size": [1600, 1200]},
        ),
    )

    events = []
    code = run_trim(
        str(folder), margins=None, safety=0, dry_run=True,
        emit=_collect_emit(events),
    )

    assert code == EXIT_OK
    detected = [e for e in events if e["event"] == "margins_detected"][0]
    assert detected["raw"] == [202, 606, 202, 23]
    assert detected["variation_applied"] == [False, True, False, False]
    assert detected["report"]["variation_applied"] == [False, True, False, False]
    assert "UI帯とみられる部分を除去しました (右=606)" in detected["human"]
    assert "下は検出値 721 が画面の 45% を超えるため採用せず" in detected["human"]


def test_run_trim_auto_passes_through_full_bleed_cover(cover_folder, tmp_path):
    """全面表示の表紙が混ざっても自動トリミングが成立し、表紙は無加工で出る。"""
    from PIL import Image

    out = tmp_path / "out"
    events = []
    code = run_trim(str(cover_folder), str(out), margins=None, safety=8,
                    emit=_collect_emit(events))
    assert code == EXIT_OK

    detected = [e for e in events if e["event"] == "margins_detected"][0]
    assert detected["margins"] == [42, 42, 52, 52]
    assert detected["report"]["outliers"] == ["cover.png"]

    passthrough = [e for e in events if e["event"] == "passthrough_pages"][0]
    assert passthrough["pages"] == ["cover.png"]

    result = [e for e in events if e["event"] == "result"][0]
    assert result["passthrough"] == 1

    with Image.open(out / "page_001.png") as im:
        assert im.size == (200 - 84, 300 - 104)  # 本文はトリミングされる
    with Image.open(out / "cover.png") as im:
        assert im.size == (200, 300)  # 表紙は元サイズのまま
