"""画像トリミングモジュール

キャプチャした画像の余白をトリミングする処理を提供する。
"""

import os
import shutil

from PIL import Image

from core.image_files import list_images


def trim_margins(im, left_margin, right_margin, top_margin, bottom_margin):
    """指定された余白で画像をトリミングする。

    Args:
        im: PIL Image オブジェクト
        left_margin, right_margin, top_margin, bottom_margin: 各辺の余白（ピクセル）

    Returns:
        トリミングされた PIL Image
    """
    width, height = im.size
    left = max(0, left_margin)
    top = max(0, top_margin)
    right = min(width, width - right_margin)
    bottom = min(height, height - bottom_margin)

    if left >= right or top >= bottom:
        return im.copy()

    return im.crop((left, top, right, bottom))


def process_images(input_folder, output_folder, left_margin, right_margin,
                   top_margin, bottom_margin, on_progress=None,
                   passthrough_files=None):
    """指定フォルダ内の画像を一括トリミングする。

    Args:
        input_folder: 入力フォルダパス
        output_folder: 出力フォルダパス
        left_margin, right_margin, top_margin, bottom_margin: 各辺の余白（ピクセル）
        on_progress: 進捗コールバック (current, total, filename)
        passthrough_files: トリミングせず無加工でコピーするファイル名の集合。
            全面表示と判定されたページ (表紙・購入画面など、本文と余白構成が
            大きく異なるページ) を共通マージンで削らないために使う

    Returns:
        (success, message) のタプル
    """
    image_files = list_images(input_folder)

    if not image_files:
        return False, "指定されたフォルダに画像ファイルが見つかりません。"

    passthrough = set(passthrough_files or ())
    os.makedirs(output_folder, exist_ok=True)
    total_files = len(image_files)
    trimmed_count = 0
    copied_count = 0

    for i, filename in enumerate(image_files, 1):
        input_path = os.path.join(input_folder, filename)
        output_path = os.path.join(output_folder, filename)

        try:
            if filename in passthrough:
                shutil.copy2(input_path, output_path)
                copied_count += 1
            else:
                with Image.open(input_path) as img:
                    trimmed = trim_margins(img, left_margin, right_margin,
                                           top_margin, bottom_margin)
                    trimmed.save(output_path)
                trimmed_count += 1
        except Exception as e:
            return False, f"ファイル {filename} の処理中にエラー: {e}"

        if on_progress:
            on_progress(i, total_files, filename)

    message = f"完了: {total_files} ファイルを処理しました。"
    if copied_count:
        message += f"（トリミング {trimmed_count} 枚 / 無加工コピー {copied_count} 枚）"
    return True, message
