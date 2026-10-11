"""OCR 前処理モジュール

NDLOCR-Lite に渡す前段で画像を整え、OCR 精度を底上げするための処理群。

電子書籍ビューアのアンチエイリアス文字は OCR にとってノイズになりがちなので、
- Lanczos アップスケール (1.5〜2x) で文字エッジを太くする
- グレースケール化 + コントラスト強調で背景ノイズを抑える
を組み合わせると、本によっては誤認識率が体感で大きく下がる。

二値化はうまく決まると効くが、地色が抜けたページや
カラー図版で逆効果になりやすいので、デフォルトは OFF にしている。
"""

from PIL import Image, ImageOps


def preprocess_image(
    image: Image.Image,
    upscale: float = 1.5,
    enhance_contrast: bool = True,
    binarize: bool = False,
    binarize_threshold: int = 180,
) -> Image.Image:
    """OCR 用に画像を前処理する。

    Args:
        image: 入力 PIL Image
        upscale: 拡大倍率 (1.0 で拡大なし、1.5〜2.0 を推奨)
        enhance_contrast: コントラスト自動調整 (autocontrast) を行うか
        binarize: 単純しきい値で二値化するか (デフォルト False)
        binarize_threshold: 二値化のしきい値 (0..255)

    Returns:
        前処理済みの新しい PIL Image
    """
    img = image

    if upscale and upscale != 1.0:
        new_size = (int(img.width * upscale), int(img.height * upscale))
        img = img.resize(new_size, Image.LANCZOS)

    if enhance_contrast or binarize:
        # autocontrast / 二値化のためにグレースケール化する
        img = ImageOps.grayscale(img)

    if enhance_contrast:
        # 上下 1% を切って autocontrast すると、Kindle のような
        # 地色が真っ白でない本でも効きやすい
        img = ImageOps.autocontrast(img, cutoff=1)

    if binarize:
        img = img.point(lambda v: 255 if v >= binarize_threshold else 0, mode="1")
        # NDLOCR が "1" モードを受け付けない可能性があるので L に戻す
        img = img.convert("L")

    return img


def preprocess_file(
    src_path: str,
    dst_path: str,
    upscale: float = 1.5,
    enhance_contrast: bool = True,
    binarize: bool = False,
    binarize_threshold: int = 180,
) -> None:
    """ファイル to ファイルの前処理ヘルパー。

    PNG はロスレスで保存し、JPG は品質 95 で保存する。
    """
    with Image.open(src_path) as im:
        im.load()
        out = preprocess_image(
            im,
            upscale=upscale,
            enhance_contrast=enhance_contrast,
            binarize=binarize,
            binarize_threshold=binarize_threshold,
        )
        ext = dst_path.lower().rsplit(".", 1)[-1]
        if ext in ("jpg", "jpeg"):
            # 二値化後は L モードなので JPG にもそのまま保存できる
            out.convert("L" if out.mode != "L" else out.mode).save(
                dst_path, "JPEG", quality=95,
            )
        else:
            out.save(dst_path)
