"""Kindle 蔵書ダンプ + 選書定義 JSON から batch 用 books.json を生成する

入力1 (--library): Kindle の蔵書ダンプ
``{"fetchedAt": ..., "count": N, "items": [...]}``（配列だけでも可）。
Amazon の「コンテンツと端末の管理」ページから書き出したもの。
各 item は ``asin``/``ASIN`` と ``title``/``productTitle`` を持てばよい。

入力2 (--select): 選書定義 JSON。グループごとにタイトルの正規表現と
batch へ渡す共通設定 (defaults) を書く:

    {
      "groups": [
        {
          "name": "A群 マンガ",
          "output": "books_a.json",
          "match": "^名探偵コナン",
          "sort": "volume",
          "take": 35,
          "defaults": { "format": "image_pdf" }
        }
      ]
    }

グループのキー:
    output   出力ファイル名（必須。--out-dir からの相対 or 絶対パス）
    match    タイトルに対する正規表現（必須。部分一致）
    exclude  除外する正規表現（任意）
    sort     "volume"（タイトル末尾側の巻数で数値ソート）/ "title" / 省略（ダンプ順）
    take     先頭 N 冊に絞る（任意。sort 適用後に切る）
    title_replace  [[pattern, repl], ...] 出力タイトルの整形（任意）
    defaults 各本にコピーされる batch 設定（format / page_turn / split_words 等）
    name     表示用グループ名（任意）

出力: グループごとに ``kindle_shot.bat batch --books`` が読む形式の JSON。
タイトルは Windows のファイル名に使えない文字を除去して収録する。
書き出し後に core/pipeline の batch 検証を通し、そのまま実行できることを保証する。

使い方:
    python scripts\\make_books.py --library kindle-library-2026-07-29.json ^
        --select selection.json --out-dir C:\\books
"""

import argparse
import html
import json
import os
import re
import sys

# リポジトリ直下を import パスに足す（scripts/ から core を使うため）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.pipeline import load_batch_file  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_ARGS = 2

# グループ定義で指定できるキー
_GROUP_KEYS = frozenset(
    ("name", "output", "match", "exclude", "sort", "take",
     "title_replace", "defaults")
)

# Windows のファイル名に使えない文字（タイトルは出力ファイル名になる）
_INVALID_FILENAME_RE = re.compile(r'[\\/:*?"<>|]')

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def sanitize_title(title):
    """タイトルをファイル名に使える形に整える。"""
    t = _INVALID_FILENAME_RE.sub(" ", title)
    t = re.sub(r"\s+", " ", t).strip()
    return t.rstrip(". ")


def volume_number(title):
    """タイトルから巻数らしい数値を取り出す（末尾側の数字列を優先）。

    「名探偵コナン（３５）」→ 35。全角数字も可。見つからなければ None。
    """
    matches = re.findall(r"[0-9０-９]+", title)
    if not matches:
        return None
    return int(matches[-1].translate(_FULLWIDTH_DIGITS))


def load_library(path):
    """蔵書ダンプを読み、[{asin, title}, ...] にして返す（asin 重複は先勝ち）。

    Raises:
        ValueError: ファイルが読めない・形式が認識できない
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except OSError as e:
        raise ValueError(f"ダンプファイルを読めません: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"ダンプファイルが JSON として不正です: {e}") from e

    if isinstance(data, dict) and isinstance(data.get("items"), list):
        items = data["items"]
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(
            "ダンプの形式が認識できません"
            "（{\"items\": [...]} または配列。Kindle の蔵書ダンプを指定）"
        )

    books = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        asin = item.get("asin") or item.get("ASIN")
        title = item.get("title") or item.get("productTitle")
        if not asin or not title:
            continue
        if asin in seen:
            continue
        seen.add(asin)
        # Amazon のダンプは HTML エスケープが残ることがある（例: AI &amp; TECHNOLOGY）
        books.append({"asin": str(asin),
                      "title": html.unescape(str(title)).strip()})
    if not books:
        raise ValueError("ダンプに本が1冊もありません")
    return books


def load_selection(path):
    """選書定義を読み、グループのリストにして返す。

    Raises:
        ValueError: 読めない・形式不正・未知キー
    """
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except OSError as e:
        raise ValueError(f"選書定義を読めません: {e}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"選書定義が JSON として不正です: {e}") from e

    if isinstance(data, dict) and "groups" in data:
        data = data["groups"]
    if not isinstance(data, list) or not data:
        raise ValueError(
            "選書定義は {\"groups\": [...]} またはグループの配列にしてください"
        )

    groups = []
    for i, g in enumerate(data, 1):
        label = f"{i}番目のグループ"
        if not isinstance(g, dict):
            raise ValueError(f"{label}: オブジェクト（辞書）ではありません")
        unknown = set(g) - _GROUP_KEYS
        if unknown:
            raise ValueError(
                f"{label}: 未知のキー {sorted(unknown)}"
                f"（指定可能: {sorted(_GROUP_KEYS)}）"
            )
        if not g.get("output") or not isinstance(g["output"], str):
            raise ValueError(f"{label}: output（出力ファイル名）が必要です")
        if not g.get("match") or not isinstance(g["match"], str):
            raise ValueError(f"{label}: match（タイトルの正規表現）が必要です")
        try:
            g["_match_re"] = re.compile(g["match"])
        except re.error as e:
            raise ValueError(f"{label}: match が正規表現として不正です: {e}") from e
        if g.get("exclude"):
            try:
                g["_exclude_re"] = re.compile(g["exclude"])
            except re.error as e:
                raise ValueError(
                    f"{label}: exclude が正規表現として不正です: {e}") from e
        if g.get("sort") not in (None, "volume", "title"):
            raise ValueError(f"{label}: sort は volume / title のいずれかです")
        take = g.get("take")
        if take is not None and (isinstance(take, bool)
                                 or not isinstance(take, int) or take < 1):
            raise ValueError(f"{label}: take は1以上の整数です")
        defaults = g.get("defaults", {})
        if not isinstance(defaults, dict):
            raise ValueError(f"{label}: defaults はオブジェクト（辞書）です")
        for key in ("asin", "url", "title"):
            if key in defaults:
                raise ValueError(
                    f"{label}: defaults に {key} は指定できません（本ごとに決まる値）")
        tr = g.get("title_replace", [])
        if tr and (not isinstance(tr, list)
                   or not all(isinstance(p, list) and len(p) == 2
                              and all(isinstance(s, str) for s in p)
                              for p in tr)):
            raise ValueError(
                f"{label}: title_replace は [[pattern, repl], ...] 形式です")
        g["name"] = g.get("name") or g["output"]
        groups.append(g)
    return groups


def select_group(library, group):
    """1グループ分の選書を行い、batch 用の本リストを返す。"""
    books = [b for b in library if group["_match_re"].search(b["title"])]
    exclude_re = group.get("_exclude_re")
    if exclude_re:
        books = [b for b in books if not exclude_re.search(b["title"])]
    matched = len(books)

    sort = group.get("sort")
    if sort == "volume":
        # 巻数が取れない本は後ろに回す（安定ソートでダンプ順を保つ）
        books.sort(key=lambda b: (volume_number(b["title"]) is None,
                                  volume_number(b["title"]) or 0))
    elif sort == "title":
        books.sort(key=lambda b: b["title"])

    take = group.get("take")
    if take is not None:
        books = books[:take]

    defaults = group.get("defaults", {})
    out = []
    for b in books:
        title = b["title"]
        for pattern, repl in group.get("title_replace", []):
            title = re.sub(pattern, repl, title)
        entry = {"asin": b["asin"], "title": sanitize_title(title), **defaults}
        out.append(entry)
    return out, matched


def _validate_output(out_path):
    """書き出した books.json を batch 本体の検証に通す。

    Returns:
        (code, errors)。code が None なら合格。
    """
    errors = []

    def collect(event, human=None, **fields):
        if event == "error":
            errors.append(fields.get("message", human))

    _, code = load_batch_file(out_path, collect)
    return code, errors


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Kindle 蔵書ダンプ + 選書定義から batch 用 books.json を生成する",
    )
    parser.add_argument("--library", required=True, metavar="FILE",
                        help="Kindle の蔵書ダンプ JSON（asin / title を含む）")
    parser.add_argument("--select", required=True, metavar="FILE",
                        help="選書定義 JSON（グループ・正規表現・defaults）")
    parser.add_argument("--out-dir", default=".", metavar="FOLDER",
                        help="出力先フォルダ（既定: カレント。グループの output を"
                             "この下に書く）")
    parser.add_argument("--dry-run", action="store_true",
                        help="選ばれる本の一覧だけ表示し、ファイルは書かない")
    args = parser.parse_args(argv)

    try:
        library = load_library(args.library)
        groups = load_selection(args.select)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return EXIT_BAD_ARGS

    print(f"蔵書ダンプ: {len(library)} 冊")

    failed = False
    asin_seen = {}
    for group in groups:
        books, matched = select_group(library, group)
        print(f"\n[{group['name']}] マッチ {matched} 冊 → 採用 {len(books)} 冊")
        if not books:
            print("  エラー: 1冊もマッチしませんでした（match を確認）",
                  file=sys.stderr)
            failed = True
            continue
        take = group.get("take")
        if take is not None and matched < take:
            print(f"  警告: take={take} に対しマッチが {matched} 冊しかありません")
        for b in books:
            print(f"  {b['asin']}  {b['title']}")
            if b["asin"] in asin_seen:
                print(f"  警告: {asin_seen[b['asin']]} にも含まれています"
                      f"（同じ本を2回キャプチャします）")
            asin_seen[b["asin"]] = group["name"]

        if args.dry_run:
            continue

        out_path = os.path.join(args.out_dir, group["output"])
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(books, f, ensure_ascii=False, indent=2)
            f.write("\n")

        # 書いたファイルを batch 本体の検証に通し、そのまま実行できることを保証する
        code, errors = _validate_output(out_path)
        if code is not None:
            for msg in errors:
                print(f"  検証エラー: {msg}", file=sys.stderr)
            failed = True
            continue
        print(f"  → {out_path}")

    if failed:
        return EXIT_BAD_ARGS
    if args.dry_run:
        print("\n（dry-run のためファイルは書いていません）")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
