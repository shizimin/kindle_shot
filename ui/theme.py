"""GUI の見た目（フォント・テーマ・余白）の一元管理（画面仕様書 §7）

customtkinter は続投し、フォントだけを日本語向けに差し替える。
CTkFont はテーマ辞書の "CTkFont" を既定値として読むため、ルート生成直後に
ここを書き換えれば family 指定なしの全ウィジェットへ一括で効く。

余白・角丸の定数もここに集約し、全画面で同じ値を使う。
"""

import tkinter.font as tkfont

import customtkinter as ctk

# 第一候補 → フォールバックの順。存在しなければ customtkinter の既定のまま。
FONT_CANDIDATES = ("Yu Gothic UI", "Meiryo UI", "Meiryo")

# 余白・角丸（全画面で共通）
PAD_X = 16
PAD_Y = 10
PAD_SMALL = 6
CORNER_RADIUS = 8

# フォントサイズ
FONT_SIZE_BASE = 13
FONT_SIZE_SMALL = 12
FONT_SIZE_HEADING = 17
FONT_SIZE_BIG_BUTTON = 16

# 補助テキストの色（ライト/ダーク）
MUTED_COLOR = ("gray35", "gray70")
ERROR_COLOR = ("#b00020", "#ff6b6b")


def resolve_font_family(root=None):
    """利用可能な日本語 UI フォント名を返す（無ければ既定 family）。

    tkinter.font.families() は Tk ルートが必要なため、ルート生成後に呼ぶこと。
    """
    try:
        families = set(tkfont.families(root))
    except Exception:
        families = set()
    for family in FONT_CANDIDATES:
        if family in families:
            return family
    return ctk.ThemeManager.theme["CTkFont"]["family"]


def apply_font_theme(root=None):
    """テーマ既定のフォントファミリを日本語 UI フォントへ差し替える。

    ウィジェット生成前に呼ぶこと。返り値は実際に採用された family 名。
    """
    family = resolve_font_family(root)
    ctk.ThemeManager.theme["CTkFont"]["family"] = family
    ctk.ThemeManager.theme["CTkFont"]["size"] = FONT_SIZE_BASE
    return family


def resolve_color(color):
    """(light, dark) の色指定を現在の外観モードの単一色へ解決する。

    tk.Label など customtkinter のテーマに追従しないウィジェットの
    背景色を合わせるために使う。
    """
    if isinstance(color, list | tuple):
        index = 0 if ctk.get_appearance_mode() == "Light" else 1
        return color[index]
    return color


def frame_bg():
    """CTkFrame の背景色（現在の外観モード）。"""
    return resolve_color(ctk.ThemeManager.theme["CTkFrame"]["fg_color"])


def text_color():
    """CTkLabel の文字色（現在の外観モード）。"""
    return resolve_color(ctk.ThemeManager.theme["CTkLabel"]["text_color"])
