"""pdf コマンド（外部PDF → 画像展開）の CLI 契約テスト

test_cli_contract.py と同じ流儀: cli.main() をインプロセス実行し、
--json 出力のイベントと終了コードを検証する。
入力 PDF は PIL の PDF 書き出しで合成する（pypdfium2 で読める）。
"""

import json

import pytest
from PIL import Image

import cli


def run_cli(capsys, argv):
    code = cli.main(argv)
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return code, events


def by_name(events, name):
    return [e for e in events if e["event"] == name]


@pytest.fixture
def sample_pdf(tmp_path):
    """3ページの合成PDF（白 / 灰 / 黒）。"""
    path = tmp_path / "sample.pdf"
    pages = [Image.new("RGB", (200, 300), c) for c in (255, 128, 0)]
    pages[0].save(str(path), save_all=True, append_images=pages[1:])
    return path


def test_pdf_extracts_pages(sample_pdf, tmp_path, capsys):
    out_dir = tmp_path / "pages"
    code, events = run_cli(
        capsys,
        ["pdf", "--in", str(sample_pdf), "--out", str(out_dir), "--json"],
    )
    assert code == cli.EXIT_OK

    prog = by_name(events, "progress")
    assert [p["current"] for p in prog] == [1, 2, 3]
    assert all(p["phase"] == "pdf" for p in prog)
    assert prog[-1]["file"] == "003.png"

    res = by_name(events, "result")[0]
    assert res["ok"] is True
    assert res["pages"] == 3
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "001.png", "002.png", "003.png",
    ]


def test_pdf_default_output_is_sibling_pages_folder(sample_pdf, capsys):
    code, events = run_cli(capsys, ["pdf", "--in", str(sample_pdf), "--json"])
    assert code == cli.EXIT_OK
    res = by_name(events, "result")[0]
    expected = sample_pdf.parent / "sample_pages"
    assert res["output"] == str(expected)
    assert (expected / "001.png").exists()


def test_pdf_jpg_format(sample_pdf, tmp_path, capsys):
    out_dir = tmp_path / "pages_jpg"
    code, events = run_cli(
        capsys,
        ["pdf", "--in", str(sample_pdf), "--out", str(out_dir),
         "--format", "jpg", "--json"],
    )
    assert code == cli.EXIT_OK
    assert (out_dir / "001.jpg").exists()


def test_pdf_missing_file(tmp_path, capsys):
    code, events = run_cli(
        capsys, ["pdf", "--in", str(tmp_path / "nai.pdf"), "--json"],
    )
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")


def test_pdf_invalid_dpi(sample_pdf, capsys):
    code, events = run_cli(
        capsys, ["pdf", "--in", str(sample_pdf), "--dpi", "0", "--json"],
    )
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")


def test_pdf_existing_output_requires_overwrite(sample_pdf, tmp_path, capsys):
    out_dir = tmp_path / "pages"
    out_dir.mkdir()
    Image.new("L", (10, 10), 255).save(str(out_dir / "old.png"))

    # 残骸あり + --overwrite なし → 中止
    code, events = run_cli(
        capsys,
        ["pdf", "--in", str(sample_pdf), "--out", str(out_dir), "--json"],
    )
    assert code == cli.EXIT_BAD_ARGS
    assert by_name(events, "error")
    assert (out_dir / "old.png").exists()

    # --overwrite → 残骸を消して展開
    code, events = run_cli(
        capsys,
        ["pdf", "--in", str(sample_pdf), "--out", str(out_dir),
         "--overwrite", "--json"],
    )
    assert code == cli.EXIT_OK
    assert by_name(events, "cleaned_output")
    assert not (out_dir / "old.png").exists()
    assert (out_dir / "001.png").exists()
