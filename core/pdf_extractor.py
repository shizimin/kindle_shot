"""PDF展開モジュール

外部から取り込んだPDFファイルを1ページずつ画像に書き出す。
出力された画像フォルダはトリミング/変換タブにそのまま流せる。

依存: pypdfium2（NDLOCR-Lite と共通の依存）
"""

import os

import pypdfium2 as pdfium


def extract_pdf_to_images(pdf_path, output_folder, dpi=200,
                          image_format="png", on_progress=None):
    """PDFの各ページを画像に書き出す。

    Args:
        pdf_path: 入力PDFファイルパス
        output_folder: 出力フォルダ（無ければ作成）
        dpi: レンダリング解像度（デフォルト200）
        image_format: "png" または "jpg"
        on_progress: (current, total, filename) を受け取るコールバック

    Returns:
        (success, message_or_folder) のタプル
    """
    if not os.path.isfile(pdf_path):
        return False, f"PDFファイルが見つかりません: {pdf_path}"

    image_format = image_format.lower()
    if image_format == "jpeg":
        image_format = "jpg"
    if image_format not in ("png", "jpg"):
        return False, f"対応していない画像形式です: {image_format}"

    try:
        os.makedirs(output_folder, exist_ok=True)
    except OSError as e:
        return False, f"出力フォルダを作成できません: {e}"

    scale = dpi / 72.0

    try:
        pdf = pdfium.PdfDocument(pdf_path)
    except Exception as e:
        return False, f"PDFを開けません: {e}"

    try:
        total = len(pdf)
        if total == 0:
            return False, "PDFにページがありません"

        digits = max(3, len(str(total)))
        ext = "png" if image_format == "png" else "jpg"

        for i in range(total):
            page = pdf[i]
            try:
                pil_image = page.render(scale=scale).to_pil()
            finally:
                page.close()

            filename = f"{str(i + 1).zfill(digits)}.{ext}"
            filepath = os.path.join(output_folder, filename)

            if image_format == "jpg":
                if pil_image.mode != "RGB":
                    pil_image = pil_image.convert("RGB")
                pil_image.save(filepath, "JPEG", quality=92)
            else:
                pil_image.save(filepath, "PNG")

            if on_progress:
                on_progress(i + 1, total, filename)
    finally:
        pdf.close()

    return True, output_folder
