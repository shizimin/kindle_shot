"""キャプチャ結果の機械検証（純解析）

フォルダ内のページ画像を走査し、キャプチャ失敗の兆候を検出する:
- 白紙/真っ黒ページ (ロック画面や描画失敗の兆候)
- 隣接ページの近似重複 (page_wait 不足で描画途中を保存した兆候)
- サイズ不一致 (途中でウィンドウサイズが変わった兆候)

解析のみを行い、出力 (イベント発行) や終了コードの判定は呼び出し側
(cli.py / 将来的に GUI) が行う。
"""

import os

import numpy as np
from PIL import Image

from core.image_files import list_images

# 一様ページ判定: 32x32 グレースケール縮小の標準偏差がこれ未満なら白紙/真っ黒
BLANK_STD_THRESHOLD = 3.0
# 隣接ページ近似重複判定: 縮小画像の平均絶対差がこれ未満なら「ほぼ同一」
NEAR_DUPLICATE_DIFF = 1.5


class PageReadError(Exception):
    """ページ画像が読めなかったことを表す例外。"""

    def __init__(self, filename, cause):
        self.filename = filename
        self.cause = cause
        super().__init__(f"{filename} を読めません: {cause}")


def analyze_folder(input_folder, on_progress=None):
    """フォルダ内の全ページ画像を解析する。

    Args:
        input_folder: 画像フォルダパス
        on_progress: 進捗コールバック (current, total, filename)

    Returns:
        {
            "files": [ファイル名, ...] (名前順),
            "blank_pages": [白紙/真っ黒のファイル名, ...],
            "near_duplicates": [{"pages": [前ページ, 当ページ], "diff": float}, ...],
            "sizes": {ファイル名: [幅, 高さ]},
            "common_size": [幅, 高さ] (最頻サイズ。画像が無ければ None),
            "size_mismatch": [最頻サイズと異なるファイル名, ...],
        }

    Raises:
        FileNotFoundError: フォルダが存在しない場合
        PageReadError: 画像が読めない場合
    """
    files = list_images(input_folder)
    blank_pages = []
    near_duplicates = []
    sizes = {}
    prev_thumb = None
    prev_name = None
    total = len(files)

    for i, filename in enumerate(files, 1):
        path = os.path.join(input_folder, filename)
        try:
            with Image.open(path) as im:
                sizes[filename] = list(im.size)
                thumb = np.asarray(
                    im.convert("L").resize((32, 32)), dtype=np.float32,
                )
        except Exception as e:
            raise PageReadError(filename, e) from e

        # ほぼ一様なページ (白紙・真っ黒 = ロック画面や描画失敗の兆候)
        if thumb.std() < BLANK_STD_THRESHOLD:
            blank_pages.append(filename)
        # 隣接ページがほぼ同一 (page_wait 不足で描画途中を保存した兆候)
        if prev_thumb is not None:
            diff = float(np.abs(thumb - prev_thumb).mean())
            if diff < NEAR_DUPLICATE_DIFF:
                near_duplicates.append(
                    {"pages": [prev_name, filename], "diff": round(diff, 2)}
                )
        prev_thumb, prev_name = thumb, filename
        if on_progress:
            on_progress(i, total, filename)

    size_counts = {}
    for s in sizes.values():
        size_counts[tuple(s)] = size_counts.get(tuple(s), 0) + 1
    common_size = max(size_counts, key=size_counts.get) if size_counts else None
    size_mismatch = [f for f, s in sizes.items() if tuple(s) != common_size]

    return {
        "files": files,
        "blank_pages": blank_pages,
        "near_duplicates": near_duplicates,
        "sizes": sizes,
        "common_size": list(common_size) if common_size else None,
        "size_mismatch": size_mismatch if common_size else [],
    }
