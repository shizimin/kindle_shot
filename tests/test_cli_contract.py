"""CLI の JSON Lines イベント契約テスト（リファクタリングの最重要安全網）

cli.main() をインプロセス実行し、--json 出力を 1 行ずつ JSON としてパースして
イベント名・フィールド・終了コードを検証する。この契約はエージェント自動化が
依存しているため、リファクタリングで変更してはならない。

capture / open / run は Win32 実機依存のため対象外。
"""

import json

from conftest import make_blank_page, make_page

import cli


def run_cli(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return code, events


def by_name(events, name):
    return [e for e in events if e["event"] == name]


# ------------------------------------------------------------
# trim
# ------------------------------------------------------------

def test_trim_auto_dry_run(pages_folder, capsys):
    code, events = run_cli(
        capsys, ["trim", "--in", str(pages_folder), "--auto", "--dry-run", "--json"],
    )
    assert code == cli.EXIT_OK

    det = by_name(events, "margins_detected")[0]
    assert det["raw"] == [50, 50, 60, 60]
    assert det["margins"] == [42, 42, 52, 52]  # raw - safety(8)
    assert det["safety"] == 8
    assert det["report"]["pages_detected"] == 3
    assert det["report"]["pages_total"] == 3

    prog = by_name(events, "progress")
    assert prog
    # 3 ページでは UI 帯検出を行わず、内容の走査だけを報告する。
    assert {p["phase"] for p in prog} == {"detect"}
    detect_prog = [p for p in prog if p["phase"] == "detect"]
    assert detect_prog[-1] == {
        "event": "progress", "phase": "detect",
        "current": 3, "total": 3, "file": "page_003.png",
    }

    res = by_name(events, "result")[0]
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert res["margins"] == [42, 42, 52, 52]


def test_trim_auto_reports_ui_bands_progress_with_minimum_pages(tmp_path, capsys):
    folder = tmp_path / "pages"
    folder.mkdir()
    for i in range(1, 9):
        make_page(folder / f"page_{i:03d}.png")

    code, events = run_cli(
        capsys, ["trim", "--in", str(folder), "--auto", "--dry-run", "--json"],
    )

    assert code == cli.EXIT_OK
    prog = by_name(events, "progress")
    assert {p["phase"] for p in prog} == {"detect", "ui_bands"}
    ui_prog = [p for p in prog if p["phase"] == "ui_bands"]
    assert ui_prog[-1] == {
        "event": "progress", "phase": "ui_bands",
        "current": 8, "total": 8, "file": "page_008.png",
    }


def test_trim_auto_min_margins(pages_folder, capsys):
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(pages_folder), "--auto", "--dry-run",
         "--min-margins", "0,0,80,80", "--json"],
    )
    assert code == cli.EXIT_OK
    det = by_name(events, "margins_detected")[0]
    # 検出値-8 と min-margins の大きい方が採用される
    assert det["margins"] == [42, 42, 80, 80]


def test_trim_manual_margins_clipped_is_blocked(pages_folder, capsys):
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(pages_folder), "--margins", "60,0,0,0",
         "--dry-run", "--json"],
    )
    assert code == cli.EXIT_WOULD_CLIP
    clip = by_name(events, "clipped_pages")[0]
    assert clip["pages"][0]["filename"] == "page_001.png"
    assert clip["pages"][0]["sides"] == {"left": 10}
    assert by_name(events, "error")


def test_trim_manual_margins_clipped_force_proceeds(pages_folder, capsys):
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(pages_folder), "--margins", "60,0,0,0",
         "--dry-run", "--force", "--json"],
    )
    assert code == cli.EXIT_OK
    assert by_name(events, "clipped_pages")
    assert by_name(events, "result")[0]["dry_run"] is True


def test_trim_manual_margins_passthrough_copies_full_bleed_only(cover_folder,
                                                                tmp_path, capsys):
    """--passthrough は全面表示ページだけを無加工コピーし、本文は削る。"""
    from PIL import Image

    out = tmp_path / "out"
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(cover_folder), "--margins", "40,40,40,40",
         "--passthrough", "--out", str(out), "--json"],
    )
    assert code == cli.EXIT_OK
    assert not by_name(events, "clipped_pages")
    pt = by_name(events, "passthrough_pages")[0]
    assert pt["pages"] == ["cover.png"]
    assert by_name(events, "result")[0]["passthrough"] == 1
    with Image.open(out / "page_001.png") as im:
        assert im.size == (120, 220)  # 本文はトリミングされる
    with Image.open(out / "cover.png") as im:
        assert im.size == (200, 300)  # 表紙は元サイズのまま


def test_trim_manual_margins_passthrough_still_blocks_body_clip(cover_folder, capsys):
    """パススルー対象を除いた本文が切れるなら、従来どおり中止する。"""
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(cover_folder), "--margins", "60,0,0,0",
         "--passthrough", "--dry-run", "--json"],
    )
    assert code == cli.EXIT_WOULD_CLIP
    assert by_name(events, "passthrough_pages")[0]["pages"] == ["cover.png"]
    clipped = by_name(events, "clipped_pages")[0]["pages"]
    # 表紙はパススルー済みなので clipped の理由には含まれない
    assert [c["filename"] for c in clipped] == [
        "page_001.png", "page_002.png", "page_003.png",
    ]
    assert by_name(events, "error")


def test_trim_auto_min_margins_does_not_passthrough_body(cover_folder, tmp_path,
                                                         capsys):
    """--min-margins で本文へ意図的に食い込ませても、本文はパススルーされない。

    Google Play ブックスのリーダーUI帯を削る運用 (--auto --min-margins) が
    「全ページ無加工コピー」に化けないことの回帰テスト。
    """
    from PIL import Image

    out = tmp_path / "out"
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(cover_folder), "--auto", "--min-margins", "0,0,130,130",
         "--out", str(out), "--json"],
    )
    assert code == cli.EXIT_OK
    det = by_name(events, "margins_detected")[0]
    assert det["margins"] == [42, 42, 130, 130]  # 検出値52 < min_margins130
    assert det["report"]["outliers"] == ["cover.png"]

    pt = by_name(events, "passthrough_pages")[0]
    assert pt["pages"] == ["cover.png"]
    assert by_name(events, "result")[0]["passthrough"] == 1

    with Image.open(out / "page_001.png") as im:
        assert im.size == (200 - 84, 300 - 260)  # min_margins どおり削られる
    with Image.open(out / "cover.png") as im:
        assert im.size == (200, 300)


def test_trim_executes_and_overwrite_guard(pages_folder, tmp_path, capsys):
    out = tmp_path / "out"
    argv = ["trim", "--in", str(pages_folder), "--margins", "10,10,10,10",
            "--no-check", "--out", str(out), "--json"]

    code, events = run_cli(capsys, argv)
    assert code == cli.EXIT_OK
    res = by_name(events, "result")[0]
    assert res["ok"] is True
    assert res["margins"] == [10, 10, 10, 10]
    assert res["output"] == str(out)
    names = sorted(p.name for p in out.glob("*.png"))
    assert names == ["page_001.png", "page_002.png", "page_003.png"]

    # 2回目: 既存画像があるため --overwrite なしでは中止
    code, events = run_cli(capsys, argv)
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")

    # --overwrite で既存を消して実行、cleaned_output イベントが出る
    code, events = run_cli(capsys, argv + ["--overwrite"])
    assert code == cli.EXIT_OK
    cleaned = by_name(events, "cleaned_output")[0]
    assert cleaned["removed"] == 3


def test_trim_missing_input_folder(tmp_path, capsys):
    code, events = run_cli(
        capsys,
        ["trim", "--in", str(tmp_path / "nope"), "--auto", "--dry-run", "--json"],
    )
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")


def test_trim_empty_input_folder(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    code, events = run_cli(
        capsys, ["trim", "--in", str(empty), "--auto", "--dry-run", "--json"],
    )
    assert code == cli.EXIT_NO_IMAGES
    assert by_name(events, "error")


# ------------------------------------------------------------
# validate
# ------------------------------------------------------------

def _validate_folder(tmp_path):
    folder = tmp_path / "v"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png")  # page_001 と同一 → 近似重複
    make_blank_page(folder / "page_003.png")  # 一様 → 白紙警告
    return folder


def test_validate_reports_warnings(tmp_path, capsys):
    folder = _validate_folder(tmp_path)
    code, events = run_cli(capsys, ["validate", "--in", str(folder), "--json"])
    assert code == cli.EXIT_OK  # 警告どまり（strict でなければエラーにしない）

    res = by_name(events, "result")[0]
    assert res["ok"] is True
    assert res["pages"] == 3
    assert res["common_size"] == [200, 300]
    assert res["blank_pages"] == ["page_003.png"]
    assert len(res["near_duplicates"]) == 1
    assert res["near_duplicates"][0]["pages"] == ["page_001.png", "page_002.png"]
    assert res["size_mismatch"] == []
    assert res["warnings"] == 2
    assert res["errors"] == []


def test_validate_strict_turns_warnings_into_errors(tmp_path, capsys):
    folder = _validate_folder(tmp_path)
    code, events = run_cli(
        capsys, ["validate", "--in", str(folder), "--strict", "--json"],
    )
    assert code == cli.EXIT_VALIDATION
    res = by_name(events, "result")[0]
    assert res["ok"] is False
    assert len(res["errors"]) == 2


def test_validate_expect_pages_shortfall(tmp_path, capsys):
    folder = tmp_path / "v2"
    folder.mkdir()
    make_page(folder / "page_001.png")
    code, events = run_cli(
        capsys,
        ["validate", "--in", str(folder), "--expect-pages", "5", "--json"],
    )
    assert code == cli.EXIT_VALIDATION
    res = by_name(events, "result")[0]
    assert res["ok"] is False
    assert res["expect_pages"] == 5


def test_validate_size_mismatch(tmp_path, capsys):
    folder = tmp_path / "v3"
    folder.mkdir()
    make_page(folder / "page_001.png")
    make_page(folder / "page_002.png")
    make_page(folder / "page_003.png", size=(210, 300), box=(50, 60, 149, 239))
    code, events = run_cli(capsys, ["validate", "--in", str(folder), "--json"])
    assert code == cli.EXIT_OK
    res = by_name(events, "result")[0]
    assert res["common_size"] == [200, 300]
    assert res["size_mismatch"] == ["page_003.png"]


# ------------------------------------------------------------
# convert（OCR 不要の image_pdf のみ。OCR 系は環境依存のため対象外）
# ------------------------------------------------------------

def test_convert_image_pdf(pages_folder, tmp_path, isolated_config, capsys):
    out = tmp_path / "out"
    code, events = run_cli(
        capsys,
        ["convert", "--in", str(pages_folder), "--out", str(out),
         "--format", "image_pdf", "--name", "テスト本", "--json"],
    )
    assert code == cli.EXIT_OK
    res = by_name(events, "result")[0]
    assert res["ok"] is True
    assert res["format"] == "image_pdf"
    assert res["output"].endswith("テスト本.pdf")
    assert (out / "テスト本.pdf").exists()
    prog = by_name(events, "progress")
    assert prog
    assert all(p["phase"] == "pdf" for p in prog)


def test_convert_missing_input(tmp_path, isolated_config, capsys):
    code, events = run_cli(
        capsys,
        ["convert", "--in", str(tmp_path / "nope"), "--out", str(tmp_path),
         "--format", "image_pdf", "--json"],
    )
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")


# ------------------------------------------------------------
# profiles
# ------------------------------------------------------------

def test_profiles_lists_builtins(isolated_config, capsys):
    code, events = run_cli(capsys, ["profiles", "--json"])
    assert code == cli.EXIT_OK
    profs = {e["key"]: e for e in by_name(events, "profile")}
    assert "kindle" in profs
    assert "kindle_cloud" in profs
    assert profs["kindle"]["process_name"] == "Kindle.exe"
    assert profs["kindle_cloud"]["settle_enabled"] is True
    assert profs["kindle_cloud"]["page_turn_key"] == "left"
    # 各イベントに name / page_wait が含まれる
    for p in profs.values():
        assert "name" in p
        assert "page_wait" in p
