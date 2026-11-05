"""介面語言：繁體中文（原文）與英文。

程式中的介面文字以繁體中文撰寫，並以 tr("中文") 取得目前語言的文字；
含變數的文字使用 tr("第 {0} 題", n) 的形式。英文對照表在 i18n_en.py。
此模組不依賴 Qt，核心驗證訊息也使用它。
"""
from __future__ import annotations

LANGUAGES = {"zh_TW": "中文（繁體）", "en": "English"}
_language = "zh_TW"


def set_language(language: str) -> str:
    global _language
    _language = language if language in LANGUAGES else "zh_TW"
    return _language


def get_language() -> str:
    return _language


def tr(text: str, *args, **kwargs) -> str:
    if _language == "en":
        from .i18n_en import EN
        text = EN.get(text, text)
    return text.format(*args, **kwargs) if (args or kwargs) else text
