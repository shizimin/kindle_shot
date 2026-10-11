"""同じ本から2つ目の形式を作る（キャプチャをやり直さない）

`batch` で1冊を処理すると、出力先にトリミング済み画像が ``<書名>_trimmed`` として
残る。これを入力に ``cli.py convert`` を回せば、キャプチャ・トリミングを飛ばして
別形式（検索可能PDF ⇄ Markdown 等）をもう1つ作れる。

`batch` のリスト（books.json）は同じタイトルを2回書けない（出力ファイル名が衝突
するため load_batch_file が弾く）ので、2形式目はこのスクリプトで回す。

この工程は画面を使わない（OCR と PDF 生成だけ）ので、キャプチャと違って PC を
占有しない。日中に裏で流せる。

使い方:
    python scripts\\convert_2nd.py --books books_c.json ^
        --out C:\\books --format markdown ^
        --log C:\\books\\logs\\convert_2nd.jsonl

    --books      batch に渡したのと同じ本リスト（asin / title を読む）
    --out        batch の --out と同じ保存先フォルダ
    --format     2つ目に作りたい形式（1形式目とは別のものを指定する）
    --log        cli.py の JSON Lines を追記するファイル（省略時は標準出力へ）
    --dry-run    実行する本・スキップする本の一覧だけ出す

既に出力ファイルがある本と、``<書名>_trimmed`` が無い本はスキップするので、
途中で止めても同じコマンドを流し直せば残りだけが処理される。
"""

import argparse
import contextlib
import os
import subprocess
import sys

# リポジトリ直下を import パスに足す（scripts/ から core を使うため）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# 出力ファイルの決め方とスキップ判定は batch 本体と同じものを使う
# （生成側に書き写すと「batch はスキップするのにこちらは作り直す」というズレが出る）
from core.pipeline import FORMATS, _batch_output_path, load_batch_file  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_BAD_ARGS = 2

_CLI = os.path.join(_REPO_ROOT, "cli.py")


def plan(books, out, fmt):
    """各本について「実行する / スキップする」を決める。

    Args:
        books: load_batch_file が返す run_book kwargs の dict リスト
        out: 保存先フォルダ（絶対パス）
        fmt: 2つ目に作る出力形式

    Returns:
        [(book, trimmed_dir, output_path, skip_reason), ...]
        skip_reason が None なら実行対象。
    """
    rows = []
    for book in books:
        title = book["title"]
        trimmed = os.path.join(out, f"{title}_trimmed")
        output = _batch_output_path(out, title, fmt)
        if not os.path.isdir(trimmed):
            reason = "トリミング画像がありません"
        elif os.path.exists(output):
            reason = "出力済み"
        else:
            reason = None
        rows.append((book, trimmed, output, reason))
    return rows


def convert_one(trimmed, out, fmt, title, source, log):
    """1冊分の cli.py convert を実行し、終了コードを返す。"""
    cmd = [
        sys.executable, _CLI, "convert",
        "--in", trimmed,
        "--out", out,
        "--format", fmt,
        "--name", title,
        "--json",
    ]
    if source:
        cmd += ["--source", source]
    proc = subprocess.run(
        cmd, cwd=_REPO_ROOT, stdout=log, stderr=subprocess.STDOUT, text=True,
    )
    return proc.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="トリミング済み画像から2つ目の出力形式を作る"
                    "（キャプチャ・トリミングをやり直さない）",
    )
    parser.add_argument("--books", required=True, metavar="FILE",
                        help="batch に渡したのと同じ本リスト JSON")
    parser.add_argument("--out", required=True, metavar="FOLDER",
                        help="batch の --out と同じ保存先フォルダ")
    parser.add_argument("--format", required=True, choices=FORMATS,
                        help="2つ目に作る出力形式")
    parser.add_argument("--log", metavar="FILE",
                        help="cli.py の JSON Lines を追記するファイル"
                             "（省略時は標準出力へ）")
    parser.add_argument("--dry-run", action="store_true",
                        help="実行する本・スキップする本の一覧だけ出す")
    args = parser.parse_args(argv)

    errors = []
    books, code = load_batch_file(
        args.books, lambda event, human=None, **f: (
            errors.append(f.get("message", human)) if event == "error" else None
        ),
    )
    if code is not None:
        for msg in errors:
            print(f"エラー: {msg}", file=sys.stderr)
        return EXIT_BAD_ARGS

    out = os.path.abspath(args.out)
    if not os.path.isdir(out):
        print(f"エラー: 保存先フォルダがありません: {out}", file=sys.stderr)
        return EXIT_BAD_ARGS

    rows = plan(books, out, args.format)
    targets = [r for r in rows if r[3] is None]
    print(f"{len(books)} 冊中 {len(targets)} 冊を {args.format} に変換します")
    for book, _, _, reason in rows:
        if reason:
            print(f"  スキップ（{reason}）: {book['title']}")
    if args.dry_run:
        for book, *_ in targets:
            print(f"  実行予定: {book['title']}")
        print("\n（dry-run のため変換していません）")
        return EXIT_OK

    with contextlib.ExitStack() as stack:
        log = None
        if args.log:
            os.makedirs(os.path.dirname(os.path.abspath(args.log)), exist_ok=True)
            log = stack.enter_context(open(args.log, "a", encoding="utf-8"))

        failed = []
        for i, (book, trimmed, output, _) in enumerate(targets, 1):
            title = book["title"]
            print(f"[{i}/{len(targets)}] {title}", flush=True)
            rc = convert_one(trimmed, out, args.format, title,
                             book.get("asin"), log)
            if rc != EXIT_OK or not os.path.exists(output):
                failed.append((title, rc))
                print(f"  NG {title} (exit {rc})", file=sys.stderr)

    print(f"\n完了: 成功 {len(targets) - len(failed)} / 失敗 {len(failed)}"
          f" / スキップ {len(rows) - len(targets)}")
    for title, rc in failed:
        print(f"  NG {title} (exit {rc})", file=sys.stderr)
    return EXIT_ERROR if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
