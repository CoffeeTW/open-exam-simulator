"""「關於」視窗：版本、執行環境、檔案格式、資料位置、支援題型與第三方元件授權。"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

import PySide6
from PySide6.QtCore import QUrl, qVersion
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from .. import __copyright__, __license__, __url__, __version__
from ..core import question_types as qt
from ..core.exam import EXAM_SCHEMA_VERSION
from ..i18n import tr
from ..storage.exam_file import FILE_VERSION
from ..storage.history import HISTORY_VERSION, app_dir
from . import settings
from .widgets import MUTED_COLOR, plain_label

APP_NAME = "Open Exam Simulator"
THIRD_PARTY = (
    ("Qt 6", "LGPL v3", "https://www.qt.io/licensing/"),
    ("PySide6 (Qt for Python)", "LGPL v3", "https://doc.qt.io/qtforpython-6/licenses.html"),
    ("Python", "PSF License", "https://docs.python.org/3/license.html"),
    ("PyInstaller", "GPL v2 + bootloader exception", "https://pyinstaller.org/en/stable/license.html"),
)


def about_sections(history_path: Path) -> list[tuple[str, list[tuple[str, str]]]]:
    """（區塊標題, [(項目, 內容)]）；視窗與「複製資訊」共用。"""
    frozen = getattr(sys, "frozen", False)
    return [
        (tr('授權'), [
            (tr('版權'), __copyright__),
            (tr('授權條款'), tr('GNU 通用公眾授權條款第 3 版或更新版本（{0}）', __license__)),
            (tr('原始碼'), __url__),
            (tr('擔保'), tr('本程式不提供任何擔保。')),
        ]),
        (tr('版本'), [
            (tr('程式版本'), __version__),
            (tr('執行方式'), tr('EXE（已打包）') if frozen else tr('原始碼（Python）')),
            ("Python", platform.python_version()),
            ("PySide6 / Qt", f"{PySide6.__version__} / {qVersion()}"),
            (tr('作業系統'), platform.platform()),
        ]),
        (tr('檔案格式'), [
            (tr('題庫檔（.oes）'), tr('第 {0} 版', FILE_VERSION)),
            (tr('作答紀錄（history.db）'), tr('第 {0} 版', HISTORY_VERSION)),
            (tr('題目資料'), f"schemaVersion {EXAM_SCHEMA_VERSION}"),
        ]),
        (tr('資料位置'), [
            (tr('程式資料夾'), str(app_dir())),
            (tr('作答紀錄'), str(history_path)),
            (tr('設定檔'), str(settings.settings_path())),
        ]),
        (tr('支援題型'), [(str(index), tr(t.label)) for index, t in enumerate(qt.REGISTRY.values(), 1)]),
        (tr('第三方元件'), [(name, f"{license_name}　{url}") for name, license_name, url in THIRD_PARTY]),
    ]


def about_text(history_path: Path) -> str:
    """純文字版本（回報問題時貼上）。"""
    lines = [f"{APP_NAME} {__version__}"]
    for title, rows in about_sections(history_path):
        lines.append("")
        lines.append(f"[{title}]")
        lines += [f"{label}: {value}" for label, value in rows]
    return "\n".join(lines)


class AboutDialog(QDialog):
    def __init__(self, history_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.history_path = Path(history_path)
        self.setWindowTitle(tr('關於 {0}', APP_NAME))
        self.resize(640, 620)
        layout = QVBoxLayout(self)
        head = QHBoxLayout()
        icon = QLabel()
        app_icon = QGuiApplication.windowIcon()
        if not app_icon.isNull():
            icon.setPixmap(app_icon.pixmap(48, 48))
        head.addWidget(icon)
        titles = QVBoxLayout()
        name = plain_label(f"{APP_NAME} {__version__}", selectable=False)
        name.setObjectName("pageTitle")
        titles.addWidget(name)
        titles.addWidget(plain_label(tr('離線的 Windows 題庫編輯、作答與評分工具。'), color=MUTED_COLOR, selectable=False))
        titles.addWidget(plain_label(__copyright__, color=MUTED_COLOR, selectable=False))
        head.addLayout(titles, 1)
        layout.addLayout(head)

        area = QScrollArea()
        area.setWidgetResizable(True)
        content = QWidget()
        body = QVBoxLayout(content)
        self.value_labels: dict[str, QLabel] = {}
        for title, rows in about_sections(self.history_path):
            box = QGroupBox(title)
            form = QFormLayout(box)
            for label, value in rows:
                value_label = plain_label(value)
                self.value_labels[label] = value_label
                form.addRow(label + tr('：'), value_label)
            if title == tr('授權'):
                link = QPushButton(tr('開啟專案網頁'))
                link.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(__url__)))
                row = QHBoxLayout()
                row.addWidget(link)
                row.addStretch(1)
                form.addRow(row)
            if title == tr('資料位置'):
                buttons = QHBoxLayout()
                for text, folder in ((tr('開啟程式資料夾'), app_dir()),
                                     (tr('開啟作答紀錄資料夾'), self.history_path.parent)):
                    button = QPushButton(text)
                    button.clicked.connect(lambda _=False, f=folder: QDesktopServices.openUrl(QUrl.fromLocalFile(str(f))))
                    buttons.addWidget(button)
                buttons.addStretch(1)
                form.addRow(buttons)
            body.addWidget(box)
        body.addWidget(plain_label(tr('本程式以 PySide6（Qt for Python）開發；Qt 與 PySide6 依 LGPL v3 授權使用，'
                                      '打包版本內附的 Qt 程式庫可依 LGPL 規定自行替換。'),
                                   color=MUTED_COLOR, selectable=False))
        body.addStretch(1)
        area.setWidget(content)
        layout.addWidget(area, 1)

        buttons = QDialogButtonBox()
        self.copy_button = buttons.addButton(tr('複製資訊'), QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button.clicked.connect(self.copy_info)
        close = buttons.addButton(tr('關閉'), QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def copy_info(self) -> None:
        QGuiApplication.clipboard().setText(about_text(self.history_path))
        self.copy_button.setText(tr('已複製'))
