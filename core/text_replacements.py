"""OCR 誤認識の置換辞書モジュール

OCR 結果に対してユーザー定義のルールで置換を適用する。
本ごとの活字癖や、ルビ混入・特定文字の頻出誤認識を一気に潰せる。

辞書ファイル (replacements.json) の形式:
{
    "_comment": "好きにメモを書いてよい (キーが _ で始まるものは無視)",
    "literal": {
        "啦": "です",
        "゠": "ー"
    },
    "regex": [
        {"pattern": "([あ-ん])\\s+([あ-ん])", "replace": "\\1\\2"},
        {"pattern": "(?<=\\d)O(?=\\d)", "replace": "0"}
    ]
}

- ``literal``: 単純な文字列置換 (str.replace)。長いキーから順に適用する
- ``regex``: 正規表現置換。順番通りに適用する

ファイルが無ければ何もしない (no-op)。
壊れた JSON は呼び出し側にエラーメッセージを返す。
"""

from __future__ import annotations

import json
import os
import re

# プロジェクトルート直下に置く既定パス
_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "replacements.json",
)


def default_path() -> str:
    """既定の置換辞書ファイルパス (プロジェクトルート/replacements.json)。"""
    return _DEFAULT_PATH


class Replacer:
    """ロード済みの置換ルールを保持して apply() で適用する。

    ルール無しの場合 apply() は入力をそのまま返す (no-op)。
    """

    def __init__(self, literal: dict | None = None, regex: list | None = None):
        # 長いキーから先に置換しないと部分一致で取りこぼすので、長さ降順で並べる
        items = list((literal or {}).items())
        items.sort(key=lambda kv: -len(kv[0]))
        self._literal = items

        compiled = []
        for entry in (regex or []):
            try:
                pat = re.compile(entry["pattern"])
            except (KeyError, re.error):
                # 壊れたエントリは静かにスキップ。読込時にバリデートする想定
                continue
            compiled.append((pat, entry.get("replace", "")))
        self._regex = compiled

    def is_empty(self) -> bool:
        return not self._literal and not self._regex

    def apply(self, text: str) -> str:
        if not text or self.is_empty():
            return text
        out = text
        for src, dst in self._literal:
            if src:
                out = out.replace(src, dst)
        for pat, repl in self._regex:
            out = pat.sub(repl, out)
        return out


def load_replacer(path: str | None = None) -> tuple[Replacer, str | None]:
    """置換辞書をロードする。

    Returns:
        (Replacer, error_message_or_None)
        ファイルが無い場合: (空の Replacer, None) を返す (no-op で動かす)
        JSON 不正の場合: (空の Replacer, エラーメッセージ) を返す
    """
    p = path or _DEFAULT_PATH
    if not os.path.exists(p):
        return Replacer(), None
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return Replacer(), f"replacements.json のパースに失敗: {e}"
    except OSError as e:
        return Replacer(), f"replacements.json の読込に失敗: {e}"

    literal = data.get("literal") if isinstance(data, dict) else None
    regex = data.get("regex") if isinstance(data, dict) else None
    if literal is not None and not isinstance(literal, dict):
        return Replacer(), "replacements.json: 'literal' は dict である必要があります"
    if regex is not None and not isinstance(regex, list):
        return Replacer(), "replacements.json: 'regex' は list である必要があります"
    return Replacer(literal=literal, regex=regex), None


def apply_to_results(results: list, path: str | None = None) -> tuple[list, str | None]:
    """[(filename, text), ...] のリストに置換を適用して新しいリストを返す。

    Returns:
        (new_results, error_message_or_None)
    """
    replacer, err = load_replacer(path)
    if replacer.is_empty():
        return results, err
    new_results = [(name, replacer.apply(text)) for name, text in results]
    return new_results, err
