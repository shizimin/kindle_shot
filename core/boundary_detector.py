"""境界検出アルゴリズム

キャプチャ時の左右クロップ範囲を決める。Strategy パターンで方式を切り替える。

- FullFrameBoundary: 既定。クロップせずウィンドウ全体を取り込む。
  余白のトリミングは取り込み後の専用トリミングタブで行う方針のため、
  取り込み時に自動で横方向を削ることはしない（誤検出で本文を不可逆に
  失うのを避ける）。
- ManualBoundary: ユーザーがドラッグで指定した固定座標で左右をクロップ。
  「1ページだけ取りたい」等、明示的に範囲を絞りたいとき用。

加えて、トリミングタブから呼び出す
``detect_content_box`` で、4 辺すべての余白を自動検出する関数を提供する。
``detect_content_box`` は背景を1層ずつ剥がす反復方式で、ビューアの黒枠 →
グレー帯 → 白ページ → 本文、のような多層背景でも本文まで到達する。

フォルダ全体の共通マージンを決める ``detect_margins_folder`` は、辺ごとに
中央値から大きく外れたページ (全面表示の表紙・購入画面など) を外れ値として
除外したうえで、残りページの最小値を採用する。
"""

import os
import statistics
from abc import ABC, abstractmethod

import numpy as np
from PIL import Image, ImageChops

from core.image_files import list_images

# detect_content_box: 背景を剥がす最大パス数（黒枠→グレー帯→白ページ→本文）
MAX_BG_PASSES = 4
# キャプチャ時に混入する隣ページの端など、画像外周の極細ノイズを無視する幅
EDGE_IGNORE_PX = 2

# detect_margins_folder: 辺ごとの外れ値判定。中央値の OUTLIER_RATIO 未満で、
# かつ中央値との差が OUTLIER_MIN_GAP_PX を超える値を外れ値として除外する。
# 全ページの余白がもともと小さい場合は差の条件で除外が起きず、
# 従来どおり「全ページの最小値」に退化する。
OUTLIER_RATIO = 0.5
OUTLIER_MIN_GAP_PX = 20

# ------------------------------------------------------------
# page_variation_margins: ページ間の画素変化に基づく UI 帯検出のパラメータ
#
# ビューアの固定 UI (書名ヘッダー・ページ番号フッター等) はどのページでも
# ほぼ同じ絵になり、本文はページごとに大きく変わる。サンプルページ間の
# 画素の変化を行・列ごとに集計すると、本文の帯と UI の帯を分離できる。
#
# 既定値は実データでの計測に基づく:
# - Kindle Cloud Reader の縦書き小説 (3840x2160): 行の帯は 93..2024
#   (最大変化率 57.63%) と 2118..2132 (同 3.65%) の 2 本。後者がフッター。
#   列の帯は 468..3195 / 3217..3245 / 3267..3344 / 3366..3393 の 4 本に
#   割れるが、これは縦書き本文が列間の隙間で分断されただけで、最大変化率は
#   いずれも 43〜47% と本体 (74.54%) と同水準。
# - Kindle PC アプリの雑誌 (2880x1800): 行 1 本 (91.11%) / 列 1 本 (98.89%)
#   で UI 帯なし。
# - Google Play ブックス ブラウザ版の縦長実用書 (2880x1800): 行の帯は
#   44..1687 (40.24%) と 1724..1793 (82.26%、進捗スライダーを含むナビバー)
#   の 2 本。スライダーはページごとに動くため変化率が本文より高く、落差では
#   捨てられない。列は全幅 12..2836 の 1 本に融合する。→ 2D 結合判定
#   (本体帯の外へはみ出す帯を UI とみなす) で対処。
# つまり基本は「本体の帯からの最大変化率の落差」で UI と内容を切り分け、
# 落差で切り分けられない可動 UI は 2D 結合判定 (content_extent_2d) で補う。
# ------------------------------------------------------------

# サンプリングするページ数の上限 (多すぎても判定は変わらず時間だけ増える)
VARIATION_SAMPLE_PAGES = 24
# 3 枚の合成データで本文を誤って削った実測と、検証済みの 24 枚の間の値。
# お試しキャプチャなど数枚だけの入力を UI 帯検出から除外する。
VARIATION_MIN_PAGES = 8
# ページ間で「この画素は違う」とみなす輝度差 (0..255)
VARIATION_PIXEL_DIFF = 40
# この割合(%)超の画素が変化する行/列を「変化あり」とみなす
VARIATION_ACTIVE_PCT = 0.2
# これ以上連続で「変化なし」が続いたら帯の切れ目とみなす (px)
VARIATION_GAP_MIN = 12
# 本体から離れた帯を「内容」として残す下限。本体帯の最大変化率の
# VARIATION_PEAK_RATIO 倍と VARIATION_PEAK_MIN_PCT の大きい方を使う。
# 実測ではフッター 3.65% は本体 57.63% の 6% しかなく捨てられ、
# 縦書き本文列 43〜47% は本体 74.54% の 6 割あるため残る。
VARIATION_PEAK_RATIO = 0.2
VARIATION_PEAK_MIN_PCT = 8.0
# 本体帯からの横断範囲のはみ出しを UI とみなす際の許容幅 (px)
VARIATION_CROSS_TOLERANCE_PX = 12
# 縦長ページを横長モニタ全画面で表示すると片側 25〜35% の余白になる
# (Play Books 実測: 2880 幅で左 845 = 29%) ため、15% では正解を弾く。
# 1 辺で削れるのは 45% まで＝両側合わせても最低 10% は残る安全弁とする。
VARIATION_MAX_MARGIN_RATIO = 0.45


class BoundaryDetector(ABC):
    """境界検出の基底クラス"""

    @abstractmethod
    def detect(self, image):
        """画像から左右の境界座標を返す。

        Args:
            image: BGR形式の numpy 配列

        Returns:
            (left, right) のタプル
        """
        pass


class FullFrameBoundary(BoundaryDetector):
    """クロップせず画像全体を使う（既定）。

    取り込み時に自動で左右を削ると、誤検出で本文を不可逆に失う恐れがある。
    余白の除去は取り込み後の専用トリミングタブに任せる方針のため、ここでは
    常に画像全幅 (0, width) を返す。ページ変化検出も全幅で行われる。
    """

    def detect(self, image):
        return 0, image.shape[1]


class ManualBoundary(BoundaryDetector):
    """手動指定による固定境界

    ユーザーがドラッグ操作で指定した左右の座標をそのまま使用する。
    """

    def __init__(self, left=0, right=0):
        self.left = left
        self.right = right

    def detect(self, image):
        right = self.right if self.right > 0 else image.shape[1]
        return self.left, right


def _corner_bg(rgb: Image.Image, region: tuple[int, int, int, int]) -> tuple[int, ...]:
    """region の 4 隅のピクセル中央値を背景色として返す。"""
    left, top, right, bottom = region
    corners = [rgb.getpixel((left, top)), rgb.getpixel((right - 1, top)),
               rgb.getpixel((left, bottom - 1)), rgb.getpixel((right - 1, bottom - 1))]
    return tuple(int(np.median([c[i] for c in corners])) for i in range(3))


def _content_bbox_in(rgb, region, bg, threshold):
    """region 内で背景色 bg と threshold 超の差がある領域の bbox (絶対座標)。"""
    crop = rgb.crop(region)
    bg_im = Image.new("RGB", crop.size, bg)
    diff = ImageChops.difference(crop, bg_im).convert("L")
    mask = diff.point(lambda v: 255 if v > threshold else 0)
    sub = mask.getbbox()
    if sub is None:
        return None
    return (region[0] + sub[0], region[1] + sub[1],
            region[0] + sub[2], region[1] + sub[3])


def detect_content_box(
    im: Image.Image,
    threshold: int = 12,
    padding: int = 0,
) -> tuple[int, int, int, int] | None:
    """画像のコンテンツ領域 (非背景部分) のバウンディングボックスを返す。

    4 隅のピクセル中央値を背景色とみなし、しきい値以上の差がある領域を
    コンテンツとして抽出する。これを **背景が変わらなくなるまで繰り返す**
    ことで、ビューアのウィンドウ枠 (黒) → 台紙 (グレー) → ページ (白) →
    本文、のように背景が多層になっているキャプチャでも本文まで到達する。

    隣ページの端が 1px だけ漏れるようなキャプチャノイズを内容と誤認しないため、
    初回は画像外周の EDGE_IGNORE_PX px を探索対象から外す。内側にある細線は
    通常どおり内容として検出する。

    各パスの流れ:
      1. 現在の region の 4 隅から背景色を推定
      2. 直前パスの背景色と全チャンネルで差が threshold 以下なら停止
         (同じ層＝これ以上掘ると本文を削る)
      3. region 内で背景と threshold 超の差がある領域の bbox を求め、
         それを次の region にする

    停止条件は上記に加えて「bbox が縮まない」「bbox が取れない
    (1 パス目なら None を返す / 2 パス目以降は直前の bbox を採用)」
    「MAX_BG_PASSES に到達」。

    Args:
        im: PIL Image
        threshold: 背景との輝度差しきい値 (0..255)。大きくするほど寛容
        padding: 検出領域の周囲に確保する余白 (ピクセル)

    Returns:
        (left, top, right, bottom) の絶対座標。検出失敗時は None。
    """
    if im is None:
        return None

    rgb = im.convert("RGB")
    w, h = rgb.size
    if w < 4 or h < 4:
        return (0, 0, w, h)

    if w >= 2 * EDGE_IGNORE_PX + 4 and h >= 2 * EDGE_IGNORE_PX + 4:
        region = (
            EDGE_IGNORE_PX,
            EDGE_IGNORE_PX,
            w - EDGE_IGNORE_PX,
            h - EDGE_IGNORE_PX,
        )
    else:
        # 背景推定に必要な内側領域を確保できない小画像は従来どおり全体を使う
        region = (0, 0, w, h)
    bbox = None
    prev_bg = None
    for _ in range(MAX_BG_PASSES):
        bg = _corner_bg(rgb, region)
        if prev_bg is not None and all(
            abs(a - b) <= threshold for a, b in zip(bg, prev_bg, strict=True)
        ):
            # 同じ層の背景色に戻った → これ以上掘らない
            break
        prev_bg = bg

        new_bbox = _content_bbox_in(rgb, region, bg, threshold)
        if new_bbox is None:
            # 1 パス目で取れなければ白紙。以降は直前の bbox を採用して停止
            break
        bbox = new_bbox
        if new_bbox == region:
            break
        region = new_bbox
        if region[2] - region[0] < 4 or region[3] - region[1] < 4:
            break

    if bbox is None:
        return None

    left, top, right, bottom = bbox
    if padding:
        left = max(0, left - padding)
        top = max(0, top - padding)
        right = min(w, right + padding)
        bottom = min(h, bottom + padding)
    return left, top, right, bottom


def detect_margins(
    im: Image.Image,
    threshold: int = 12,
    padding: int = 0,
) -> tuple[int, int, int, int] | None:
    """画像の余白 (左/右/上/下マージン) を自動検出して返す。

    トリミングタブの 4 マージン入力欄に直接流し込める形式で返す。

    Returns:
        (left_margin, right_margin, top_margin, bottom_margin)
        検出失敗時は None。
    """
    box = detect_content_box(im, threshold=threshold, padding=padding)
    if box is None:
        return None
    w, h = im.size
    left, top, right, bottom = box
    return left, max(0, w - right), top, max(0, h - bottom)


def folder_page_margins(input_folder, threshold=12, on_progress=None):
    """フォルダ内の全画像の余白を検出して [(filename, margins|None), ...] を返す。

    margins は (left, right, top, bottom)。コンテンツが検出できないページ
    (白紙など) や読み込めないファイルは None になる。

    Raises:
        FileNotFoundError: フォルダが存在しない場合
    """
    files = list_images(input_folder)
    pages = []
    total = len(files)
    for i, filename in enumerate(files, 1):
        try:
            with Image.open(os.path.join(input_folder, filename)) as im:
                margins = detect_margins(im, threshold=threshold)
        except Exception:
            margins = None
        pages.append((filename, margins))
        if on_progress:
            on_progress(i, total, filename)
    return pages


def _is_outlier(value, median):
    """辺の余白 value が中央値 median から大きく外れているか。

    全面表示の表紙・購入画面など「余白がほぼ 0 のページ」だけを弾き、
    もともと余白が小さい本 (中央値が数 px) では除外が起きないようにする。
    """
    return value < OUTLIER_RATIO * median and (median - value) > OUTLIER_MIN_GAP_PX


def aggregate_margins(pages):
    """ページ毎の余白から共通マージンと report を組み立てる（純粋関数）。

    辺ごとに中央値を取り、中央値から大きく外れた小さい値のページ
    (全面表示の表紙・購入画面など) を外れ値として除外したうえで、
    残りページの最小値をその辺のマージンとする。

    report["outliers"] は「本文と余白構成が大きく異なる＝全面表示」と
    判定されたページであり、パイプライン側でそのままパススルー
    (無加工コピー) の対象になる。実際に適用するマージン値 (min_margins や
    手動調整で本文へ食い込ませた値) とは独立に決まる点が重要。

    Args:
        pages: [(filename, margins|None), ...]。margins は (L,R,T,B)

    Returns:
        (margins, report) のタプル。1ページも検出できなければ (None, report)。
    """
    detected = [(f, m) for f, m in pages if m is not None]
    report = {
        "pages_total": len(pages),
        "pages_detected": len(detected),
        "pages_skipped": [f for f, m in pages if m is None],
        "deciders": {},
        "outliers": [],
    }
    if not detected:
        return None, report

    sides = ("left", "right", "top", "bottom")
    margins = []
    outliers = set()
    for idx, side in enumerate(sides):
        median = statistics.median(m[idx] for _, m in detected)
        kept = []
        for f, m in detected:
            if _is_outlier(m[idx], median):
                outliers.add(f)
            else:
                kept.append((f, m[idx]))
        # 中央値以上の値は必ず残るため kept は非空
        decider, min_margin = min(kept, key=lambda x: x[1])
        margins.append(min_margin)
        report["deciders"][side] = decider
    report["outliers"] = sorted(outliers)
    return tuple(margins), report


# ============================================================
# ページ間の変化に基づく UI 帯検出
# ============================================================

def active_runs(frac, gap_min=VARIATION_GAP_MIN, active_pct=VARIATION_ACTIVE_PCT):
    """変化率の並びを「変化のある帯」の (start, end) 列にする（純粋関数）。

    Args:
        frac: 各位置 (行 or 列) の変化率(%) の 1 次元配列
        gap_min: これ以上連続で「変化なし」が続いたら帯を区切る
        active_pct: この値を超える変化率の位置を「変化あり」とみなす

    Returns:
        [(start, end), ...]（end は含む）。変化がなければ空リスト。
    """
    idx = np.nonzero(np.asarray(frac) > active_pct)[0]
    if len(idx) == 0:
        return []
    runs = []
    start = prev = int(idx[0])
    for i in idx[1:]:
        i = int(i)
        if i - prev > gap_min:
            runs.append((start, prev))
            start = i
        prev = i
    runs.append((start, prev))
    return runs


def run_peaks(frac, runs):
    """各帯の最大変化率を付けて [(start, end, peak_pct), ...] を返す（純粋関数）。"""
    frac = np.asarray(frac)
    return [(s, e, float(frac[s:e + 1].max())) for s, e in runs]


def content_extent(frac, gap_min=VARIATION_GAP_MIN,
                   active_pct=VARIATION_ACTIVE_PCT,
                   peak_ratio=VARIATION_PEAK_RATIO,
                   peak_min_pct=VARIATION_PEAK_MIN_PCT):
    """変化率の並びから「内容が占める範囲」を (first, last) で返す（純粋関数）。

    最も長い帯を本体とみなし、他の帯は最大変化率が
    ``max(peak_min_pct, peak_ratio * 本体の最大変化率)`` 以上のものだけを
    内容として採用する。採用した帯全体の最小 start と最大 end を返すので、
    縦書き本文が列間の隙間で複数の帯に割れていても 1 つにまとまり、
    変化の乏しい固定 UI (ページ番号フッター等) は捨てられる。

    Returns:
        (first, last)。帯が 1 つも無ければ None。
    """
    runs = active_runs(frac, gap_min=gap_min, active_pct=active_pct)
    if not runs:
        return None
    frac = np.asarray(frac)
    main = max(runs, key=lambda r: r[1] - r[0])
    main_peak = float(frac[main[0]:main[1] + 1].max())
    limit = max(peak_min_pct, peak_ratio * main_peak)
    kept = [r for r in runs
            if r == main or float(frac[r[0]:r[1] + 1].max()) >= limit]
    return min(r[0] for r in kept), max(r[1] for r in kept)


def cross_extent(varies, band, axis, active_pct=VARIATION_ACTIVE_PCT):
    """帯の内側だけを使い、もう一方の軸の変化範囲を返す（純粋関数）。

    Args:
        varies: 画素がページ間で変化したかを表す bool の 2 次元配列
        band: (start, end)。end は含む
        axis: 0 なら行の帯、1 なら列の帯
        active_pct: この値を超える変化率の位置を変化ありとみなす

    Returns:
        もう一方の軸の (first, last)。変化がなければ None。
    """
    varies = np.asarray(varies, dtype=bool)
    start, end = band
    if axis == 0:
        frac = varies[start:end + 1, :].mean(axis=0) * 100
    elif axis == 1:
        frac = varies[:, start:end + 1].mean(axis=1) * 100
    else:
        raise ValueError("axis must be 0 (rows) or 1 (cols)")

    active = np.nonzero(frac > active_pct)[0]
    if len(active) == 0:
        return None
    return int(active[0]), int(active[-1])


def content_extent_2d(
    varies,
    gap_min=VARIATION_GAP_MIN,
    active_pct=VARIATION_ACTIVE_PCT,
    peak_ratio=VARIATION_PEAK_RATIO,
    peak_min_pct=VARIATION_PEAK_MIN_PCT,
    cross_tolerance=VARIATION_CROSS_TOLERANCE_PX,
):
    """2D の結合関係から UI 帯を除いた行・列範囲を返す（純粋関数）。

    行先行と列先行を両方試し、本体帯の横断範囲から大きくはみ出す別帯を
    UI として除く。得られた矩形の面積が小さい候補を採用し、同点なら
    行先行を採用する。

    Returns:
        ``(rows, cols, info)``。いずれかの軸で帯を検出できなければ None。
    """
    varies = np.asarray(varies, dtype=bool)
    if varies.ndim != 2:
        raise ValueError("varies must be a 2D array")
    row_frac = varies.mean(axis=1) * 100
    col_frac = varies.mean(axis=0) * 100
    if not active_runs(row_frac, gap_min=gap_min, active_pct=active_pct):
        return None
    if not active_runs(col_frac, gap_min=gap_min, active_pct=active_pct):
        return None

    def candidate(first_axis):
        frac = row_frac if first_axis == 0 else col_frac
        runs = active_runs(frac, gap_min=gap_min, active_pct=active_pct)
        if not runs:
            return None

        main = max(runs, key=lambda r: r[1] - r[0])
        main_peak = float(frac[main[0]:main[1] + 1].max())
        limit = max(peak_min_pct, peak_ratio * main_peak)
        body_cross = cross_extent(varies, main, first_axis, active_pct)
        if body_cross is None:
            return None

        kept = [main]
        ui_bands = []
        axis_name = "row" if first_axis == 0 else "col"
        for run in runs:
            if run == main:
                continue
            peak = float(frac[run[0]:run[1] + 1].max())
            if peak < limit:
                continue
            cross = cross_extent(varies, run, first_axis, active_pct)
            if cross is None:
                continue
            protrudes = (
                cross[0] < body_cross[0] - cross_tolerance
                or cross[1] > body_cross[1] + cross_tolerance
            )
            if protrudes:
                ui_bands.append({
                    "axis": axis_name,
                    "start": run[0],
                    "end": run[1],
                    "cross": list(cross),
                    "body": list(body_cross),
                })
            else:
                kept.append(run)

        extent1 = (min(r[0] for r in kept), max(r[1] for r in kept))
        if first_axis == 0:
            second_frac = varies[extent1[0]:extent1[1] + 1, :].mean(axis=0) * 100
        else:
            second_frac = varies[:, extent1[0]:extent1[1] + 1].mean(axis=1) * 100

        # 第2軸でははみ出し判定をしない。全長で cross_extent を取ると、
        # 第1軸で捨てた UI 帯を通過する位置まで含み、縦書き本文端などの
        # 本物の内容を UI と誤判定するため。
        extent2 = content_extent(
            second_frac,
            gap_min=gap_min,
            active_pct=active_pct,
            peak_ratio=peak_ratio,
            peak_min_pct=peak_min_pct,
        )
        if extent2 is None:
            return None

        if first_axis == 0:
            rows, cols = extent1, extent2
            order = "rows"
        else:
            rows, cols = extent2, extent1
            order = "cols"
        area = (rows[1] - rows[0] + 1) * (cols[1] - cols[0] + 1)
        return rows, cols, {"order": order, "ui_bands": ui_bands}, area

    candidates = [result for axis in (0, 1)
                  if (result := candidate(axis)) is not None]
    if not candidates:
        return None
    rows, cols, info, _area = min(candidates, key=lambda result: result[3])
    return rows, cols, info


def combine_margins(content_margins, variation_margins, size,
                    max_ratio=VARIATION_MAX_MARGIN_RATIO):
    """内容ベースと変化ベースの余白を辺ごとに合成する（純粋関数）。

    辺ごとに大きい方を採る。ただし変化ベースの値がその辺の長さ × max_ratio
    を超える辺は、誤検出で本文を大きく失う恐れがあるため内容ベースを採用する。

    Args:
        content_margins: (L,R,T,B) 内容ベースの余白。None なら変化ベースを返す
        variation_margins: (L,R,T,B) 変化ベースの余白。None なら内容ベースを返す
        size: (width, height)
        max_ratio: 1 辺で削ってよい上限 (辺の長さに対する比率)

    Returns:
        (left, right, top, bottom)
    """
    if variation_margins is None:
        return content_margins
    if content_margins is None:
        return variation_margins
    width, height = size
    limits = (width * max_ratio, width * max_ratio,
              height * max_ratio, height * max_ratio)
    return tuple(
        c if v > limit else max(c, v)
        for c, v, limit in zip(content_margins, variation_margins, limits,
                               strict=True)
    )


def variation_applied(content_margins, variation_margins, combined_margins):
    """変化ベースの余白が UI 帯除去として実際に採用された辺を返す。

    合成後の値が変化ベースの値と等しく、かつ内容ベースより大きい辺だけが
    ``True`` になる。いずれかのマージン、またはその要素に ``None`` があれば
    判定不能として全辺 ``False`` を返す。
    """
    margins = (content_margins, variation_margins, combined_margins)
    if any(values is None for values in margins):
        return (False,) * 4
    if any(len(values) != 4 for values in margins):
        return (False,) * 4
    if any(value is None for values in margins for value in values):
        return (False,) * 4
    return tuple(
        combined == variation and variation > content
        for content, variation, combined in zip(*margins, strict=True)
    )


def _sample_indices(count, sample_pages):
    """0..count-1 から最大 sample_pages 個を等間隔で選ぶ。"""
    if count <= sample_pages:
        return list(range(count))
    if sample_pages <= 1:
        return [0]
    step = (count - 1) / (sample_pages - 1)
    return sorted({int(round(i * step)) for i in range(sample_pages)})


def page_variation_margins(input_folder, sample_pages=VARIATION_SAMPLE_PAGES,
                           on_progress=None):
    """ページ間の画素変化から、ビューアの固定 UI を除いた余白を検出する。

    ビューアの固定 UI (書名ヘッダー・ページ番号フッター等) は毎ページ
    ほぼ同一で、本文はページごとに変わる。サンプルページの画素ごとの
    最大値と最小値の差を取り、行・列ごとの変化率から内容の範囲を求める。

    表紙・購入画面のような全面表示ページを避けるため、10 枚を超える場合は
    先頭 2 枚と末尾 2 枚を候補から外す。サイズの異なるページ (混在キャプチャ)
    はスキップする。

    Args:
        input_folder: 画像フォルダパス
        sample_pages: サンプリングするページ数の上限
        on_progress: 進捗コールバック (current, total, filename)

    Returns:
        (margins, report) のタプル。判定できなければ (None, report)。
        margins: (left, right, top, bottom)
        report: {
            "sampled": [サンプリングしたファイル名, ...],
            "skipped": [読めない/サイズ違いで除外したファイル名, ...],
            "size": [width, height] または None,
            "row_runs": [(start, end, peak_pct), ...],
            "col_runs": [(start, end, peak_pct), ...],
            "order": "rows" または "cols"。判定不能時は None,
            "ui_bands": はみ出しにより除外した UI 帯の情報,
        }

    Raises:
        FileNotFoundError: フォルダが存在しない場合
    """
    files = list_images(input_folder)
    # 表紙・購入画面は絵が大きく違うため、候補から外して本文だけを見る
    candidates = files[2:-2] if len(files) > 10 else files
    report = {"sampled": [], "skipped": [], "size": None,
              "row_runs": [], "col_runs": [], "order": None,
              "ui_bands": []}
    if len(candidates) < VARIATION_MIN_PAGES:
        report["reason"] = "too_few_pages"
        report["min_pages"] = VARIATION_MIN_PAGES
        return None, report

    sampled = [candidates[i]
               for i in _sample_indices(len(candidates), sample_pages)]
    report["sampled"] = sampled

    # np.stack はサンプル全枚数をメモリに載せるため使わない。
    # 累積の最大/最小の 2 枚分だけ保持すれば変化幅は求まる。
    acc_max = acc_min = None
    shape = None
    used = 0
    total = len(sampled)
    for i, filename in enumerate(sampled, 1):
        try:
            with Image.open(os.path.join(input_folder, filename)) as im:
                arr = np.asarray(im.convert("L"), dtype=np.uint8)
        except Exception:
            report["skipped"].append(filename)
            arr = None
        if arr is not None:
            if shape is None:
                shape = arr.shape
                acc_max = arr.copy()
                acc_min = arr.copy()
                used = 1
            elif arr.shape != shape:
                # サイズ違いが混ざると画素同士を比較できない
                report["skipped"].append(filename)
            else:
                np.maximum(acc_max, arr, out=acc_max)
                np.minimum(acc_min, arr, out=acc_min)
                used += 1
        if on_progress:
            on_progress(i, total, filename)

    if used < 3 or shape is None:
        # 読めない画像やサイズ違いが多く、判定材料が足りない
        report["reason"] = "too_few_readable"
        return None, report

    height, width = shape
    report["size"] = [width, height]
    varies = (acc_max.astype(np.int16) - acc_min.astype(np.int16)) > VARIATION_PIXEL_DIFF

    row_frac = varies.mean(axis=1) * 100   # 各行の変化率(%)
    col_frac = varies.mean(axis=0) * 100   # 各列の変化率(%)
    report["row_runs"] = run_peaks(row_frac, active_runs(row_frac))
    report["col_runs"] = run_peaks(col_frac, active_runs(col_frac))

    extent = content_extent_2d(varies)
    if extent is None:
        return None, report
    rows, cols, info = extent
    report.update(info)

    margins = (cols[0], max(0, width - 1 - cols[1]),
               rows[0], max(0, height - 1 - rows[1]))
    return margins, report


def detect_margins_folder(input_folder, threshold=12, on_progress=None,
                          ui_bands=True, on_variation_progress=None):
    """フォルダ内の**全ページ**を走査して、共通の安全な余白を検出する。

    各ページのコンテンツ境界を検出し、辺ごとに外れ値ページ (全面表示の
    表紙・購入画面など) を除いた最小マージンを採用する。「検出できた内容を
    切らない」ことは外れ値を除く全ページに対して保証される（外れ値ページは
    パイプライン側でパススルー＝無加工コピーの対象になる）。

    ``ui_bands=True`` のときは、さらに ``page_variation_margins`` による
    ページ間変化の走査を行い、辺ごとに大きい方を採る。ビューアの固定 UI
    (書名ヘッダー・ページ番号フッター等) は非背景＝内容として検出されるため、
    内容ベースだけでは削れないのを補う。

    Args:
        input_folder: 画像フォルダパス
        threshold: 背景との輝度差しきい値 (detect_content_box と同じ)
        on_progress: 進捗コールバック (current, total, filename)
        ui_bands: ページ間変化による UI 帯検出を併用する
        on_variation_progress: UI 帯走査用の進捗コールバック。
            None なら on_progress を使う

    Returns:
        (margins, report) のタプル。1ページも検出できなければ (None, report)。
        margins: (left_margin, right_margin, top_margin, bottom_margin)
        report: {
            "pages_total": 全画像数,
            "pages_detected": 検出に使えたページ数,
            "pages_skipped": [検出できなかったファイル名, ...],
            "deciders": {"left": 左辺の限界を決めたファイル名, "right": ..., ...},
            "outliers": [外れ値として除外したファイル名, ...],
            "content_margins": [内容ベースの余白 L,R,T,B],
            "variation_margins": [変化ベースの余白 L,R,T,B] または None,
            "variation": page_variation_margins の report または None,
            "variation_applied": UI 帯除去として採用された辺の bool 4 要素,
        }
    """
    pages = folder_page_margins(input_folder, threshold=threshold,
                                 on_progress=on_progress)
    margins, report = aggregate_margins(pages)
    report["content_margins"] = list(margins) if margins else None
    report["variation_margins"] = None
    report["variation"] = None
    report["variation_applied"] = [False] * 4
    if margins is None or not ui_bands:
        return margins, report

    variation, vreport = page_variation_margins(
        input_folder,
        on_progress=on_variation_progress or on_progress,
    )
    report["variation"] = vreport
    if variation is None:
        return margins, report
    report["variation_margins"] = list(variation)
    combined = combine_margins(margins, variation, vreport["size"])
    report["variation_applied"] = list(
        variation_applied(margins, variation, combined)
    )
    return combined, report


def clipped_pages_from(pages, margins):
    """ページ毎の余白と指定マージンを比較して、内容が切れるページを返す（純粋関数）。

    Args:
        pages: [(filename, margins|None), ...]（folder_page_margins の戻り値）
        margins: (left, right, top, bottom) の余白ピクセル

    Returns:
        [{"filename": str, "sides": {"left": 不足px, ...}}, ...]
    """
    left, right, top, bottom = margins
    wanted = {"left": left, "right": right, "top": top, "bottom": bottom}
    clipped = []
    for filename, page_margins in pages:
        if page_margins is None:
            continue
        available = dict(zip(("left", "right", "top", "bottom"), page_margins, strict=True))
        over = {
            side: wanted[side] - available[side]
            for side in wanted
            if wanted[side] > available[side]
        }
        if over:
            clipped.append({"filename": filename, "sides": over})
    return clipped


def find_clipped_pages(input_folder, margins, threshold=12, on_progress=None):
    """指定マージンでトリミングすると内容が切れるページを検出する。

    トリミング実行前の安全確認、または実行後の監査に使う。ページごとの
    コンテンツ境界と指定マージンを比較し、コンテンツ側に食い込む辺を報告する。

    Args:
        input_folder: 画像フォルダパス (トリミング**前**の画像)
        margins: (left, right, top, bottom) の余白ピクセル
        threshold: 背景との輝度差しきい値
        on_progress: 進捗コールバック (current, total, filename)

    Returns:
        [{"filename": str, "sides": {"left": 不足px, ...}}, ...] のリスト。
        空リストなら、検出できた範囲では 1 ページも内容が切れない。
    """
    pages = folder_page_margins(input_folder, threshold=threshold,
                                 on_progress=on_progress)
    return clipped_pages_from(pages, margins)


def create_detector(method, manual_left=0, manual_right=0):
    """境界検出方式に応じた検出器を生成する。

    Args:
        method: "manual" なら手動座標でクロップ。それ以外（"full" や旧来の
            "pixel_compare" / "canny_edge" 等）は全画面取り込み。
        manual_left, manual_right: 手動指定時のウィンドウ相対座標
    """
    if method == "manual":
        return ManualBoundary(manual_left, manual_right)
    return FullFrameBoundary()
