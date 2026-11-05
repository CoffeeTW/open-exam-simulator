"""介面翻譯：讓 Qt 內建的按鈕與對話框（是／否、確定、取消、儲存…）顯示繁體中文。

先載入 PySide6 隨附的 qtbase_zh_TW 翻譯；若找不到或缺少某些字串，改用本檔的對照表。
"""
from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator

# Qt 標準按鈕文字（context：QPlatformTheme）與常見文字編輯選單的備用翻譯
FALLBACK = {
    "QPlatformTheme": {
        "OK": "確定", "Save": "儲存", "Save All": "全部儲存", "Open": "開啟",
        "&Yes": "是(&Y)", "Yes to &All": "全部皆是(&A)", "&No": "否(&N)", "N&o to All": "全部皆否(&O)",
        "Abort": "中止", "Retry": "重試", "Ignore": "忽略", "Close": "關閉", "Cancel": "取消",
        "Discard": "捨棄", "Help": "說明", "Apply": "套用", "Reset": "重設", "Restore Defaults": "還原預設值",
        "Don't Save": "不儲存", "Close without Saving": "不儲存並關閉",
    },
    "QWidgetTextControl": {
        "&Undo": "復原(&U)", "&Redo": "重做(&R)", "Cu&t": "剪下(&T)", "&Copy": "複製(&C)",
        "Copy &Link Location": "複製連結位置(&L)", "&Paste": "貼上(&P)", "Delete": "刪除", "Select All": "全選",
    },
    "QLineEdit": {
        "&Undo": "復原(&U)", "&Redo": "重做(&R)", "Cu&t": "剪下(&T)", "&Copy": "複製(&C)", "&Paste": "貼上(&P)",
        "Delete": "刪除", "Select All": "全選",
    },
}


class FallbackTranslator(QTranslator):
    def translate(self, context, source_text, disambiguation=None, n=-1):  # noqa: D401
        return FALLBACK.get(context, {}).get(source_text, "")

    def isEmpty(self) -> bool:  # noqa: N802
        return False


_installed: list[QTranslator] = []  # 保留參考，避免被回收


def install_translations(app: QCoreApplication, language: str = "zh_TW") -> bool:
    """依介面語言安裝 Qt 內建文字的翻譯。英文介面使用 Qt 原本的英文，不安裝翻譯。

    回傳是否載入了 Qt 官方繁體中文翻譯檔（中文時備用對照表一定會安裝）。
    """
    while _installed:
        app.removeTranslator(_installed.pop())
    if language != "zh_TW":
        return False
    fallback = FallbackTranslator(app)
    app.installTranslator(fallback)  # 先安裝備用，後安裝的官方翻譯會優先使用
    _installed.append(fallback)
    official = QTranslator(app)
    path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    locale = QLocale(QLocale.Language.Chinese, QLocale.Country.Taiwan)
    loaded = official.load(locale, "qtbase", "_", path) or official.load("qtbase_zh_TW", path)
    if loaded:
        app.installTranslator(official)
        _installed.append(official)
    return loaded
