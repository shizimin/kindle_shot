"""pdf_builder の日本語フォント埋め込みテスト

生成した PDF を pypdfium2（Edge/Chrome と同じ PDF エンジン）で読み直し、
日本語テキストが抽出できることと、TrueType フォントが埋め込まれていることを見る。
フォント候補が使えない環境では従来の HeiseiMin-W3 に落ちることも確認する。
"""

import pytest
from PIL import Image

from core import pdf_builder

SAMPLE_TEXT = "吾輩は猫である\n名前はまだ無い\nsearchable PDF test"


@pytest.fixture
def font_cache_reset(monkeypatch):
    """register_japanese_font のモジュールキャッシュを毎回まっさらにする。"""
    monkeypatch.setattr(pdf_builder, "_registered_font_name", None)


@pytest.fixture
def image_folder(tmp_path):
    """検索可能PDFの下地になる白ページ1枚のフォルダ。"""
    folder = tmp_path / "images"
    folder.mkdir()
    Image.new("RGB", (600, 800), "white").save(str(folder / "001.png"))
    return folder


def extract_text(pdf_path):
    """PDF 全ページのテキストを連結して返す。"""
    import pypdfium2

    doc = pypdfium2.PdfDocument(str(pdf_path))
    try:
        return "\n".join(page.get_textpage().get_text_bounded() for page in doc)
    finally:
        doc.close()


def test_register_japanese_font_embeds_truetype(font_cache_reset):
    """Windows 標準フォントがあれば TTF 名が返り、2回目はキャッシュから同じ名前が返る。"""
    name = pdf_builder.register_japanese_font()
    assert name == pdf_builder.EMBEDDED_FONT_NAME
    assert pdf_builder.register_japanese_font() == name


def test_register_japanese_font_falls_back(font_cache_reset, monkeypatch):
    """候補がひとつも無い環境では HeiseiMin-W3 にフォールバックする。"""
    monkeypatch.setattr(pdf_builder, "JAPANESE_FONT_CANDIDATES", [])
    assert pdf_builder.register_japanese_font() == pdf_builder.FALLBACK_FONT_NAME


def test_register_japanese_font_skips_unreadable_candidate(
    font_cache_reset, monkeypatch, tmp_path
):
    """壊れた候補は飛ばして次の候補を使う。"""
    broken = tmp_path / "broken.ttc"
    broken.write_bytes(b"not a font")
    monkeypatch.setattr(
        pdf_builder,
        "JAPANESE_FONT_CANDIDATES",
        [(str(broken), 0), *pdf_builder.JAPANESE_FONT_CANDIDATES],
    )
    assert pdf_builder.register_japanese_font() == pdf_builder.EMBEDDED_FONT_NAME


def test_searchable_pdf_text_is_extractable(font_cache_reset, image_folder, tmp_path):
    """検索可能PDFの日本語テキストが pypdfium2 で抽出できる。"""
    out = tmp_path / "searchable.pdf"
    ok, msg = pdf_builder.images_to_searchable_pdf(
        str(image_folder), [("001.png", SAMPLE_TEXT)], str(out),
    )
    assert ok, msg

    extracted = extract_text(out)
    for line in SAMPLE_TEXT.split("\n"):
        assert line in extracted


def test_searchable_pdf_embeds_font_file(font_cache_reset, image_folder, tmp_path):
    """生成PDFに TrueType 埋め込み (/FontFile2) が含まれる。"""
    out = tmp_path / "searchable.pdf"
    ok, msg = pdf_builder.images_to_searchable_pdf(
        str(image_folder), [("001.png", SAMPLE_TEXT)], str(out),
    )
    assert ok, msg
    assert b"/FontFile2" in out.read_bytes()


def test_searchable_pdf_fallback_still_builds(
    font_cache_reset, monkeypatch, image_folder, tmp_path
):
    """フォント候補が無くても検索可能PDFの生成は成功する（挙動後退なし）。"""
    monkeypatch.setattr(pdf_builder, "JAPANESE_FONT_CANDIDATES", [])
    out = tmp_path / "fallback.pdf"
    ok, msg = pdf_builder.images_to_searchable_pdf(
        str(image_folder), [("001.png", SAMPLE_TEXT)], str(out),
    )
    assert ok, msg
    assert out.exists()
    assert b"/FontFile2" not in out.read_bytes()


def test_text_pdf_text_is_extractable(font_cache_reset, tmp_path):
    """テキストPDFも日本語が抽出でき、フォントが埋め込まれる。"""
    out = tmp_path / "text.pdf"
    ok, msg = pdf_builder.text_to_pdf([("001.png", SAMPLE_TEXT)], str(out))
    assert ok, msg

    assert b"/FontFile2" in out.read_bytes()
    extracted = extract_text(out)
    assert "吾輩は猫である" in extracted


def test_text_pdf_fallback_still_builds(font_cache_reset, monkeypatch, tmp_path):
    """テキストPDFもフォント候補が無い環境で生成できる。"""
    monkeypatch.setattr(pdf_builder, "JAPANESE_FONT_CANDIDATES", [])
    out = tmp_path / "text_fallback.pdf"
    ok, msg = pdf_builder.text_to_pdf([("001.png", SAMPLE_TEXT)], str(out))
    assert ok, msg
    assert out.exists()
