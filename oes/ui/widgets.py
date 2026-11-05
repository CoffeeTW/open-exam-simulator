"""共用的小型介面元件。所有使用者輸入的文字一律以純文字顯示，不解析 HTML。"""
from __future__ import annotations

from ..i18n import tr

import html
import re

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QLabel, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from .theme import ThemeColor

# 隨主題切換的顏色（淺色／深色各有一組）
OK_COLOR = ThemeColor("ok")
BAD_COLOR = ThemeColor("bad")
MUTED_COLOR = ThemeColor("muted")


def code_font(base: QFont) -> QFont:
    """等寬字（指令、程式碼）；字級與一般文字相同。依序使用 Consolas、Cascadia Mono、Courier New。"""
    system = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font = QFont(base)
    font.setFamilies(["Consolas", "Cascadia Mono", "Courier New", system.family()])
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setFixedPitch(True)
    return font


def escape_mnemonic(text: str) -> str:
    """按鈕文字中的 & 會被當成快速鍵記號，顯示使用者文字前需跳脫。"""
    return text.replace("&", "&&")


ZWSP = "\u200b"
_LONG_RUN = re.compile(r"[^\s\u200b]{12,}")


def breakable(text: str) -> str:
    """在沒有空白的長字串中插入零寬空白，讓 Qt 可以在任何位置換行（畫面上看不到）。"""
    return _LONG_RUN.sub(lambda m: ZWSP.join(m.group(0)), text or "")


class WrapLabel(QLabel):
    """純文字、依寬度自動換行的標籤；連續長字串（網址、無空白文字）也能斷行。

    text() 回傳原始文字；顯示用的文字含零寬空白斷點。
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._raw = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._raw = text or ""
        super().setText(breakable(self._raw))
        self.setAccessibleName(self._raw)

    def text(self) -> str:
        return self._raw


class RichLabel(QLabel):
    """顯示含粗體、字級的文字段落。所有文字先做 HTML 跳脫，只由程式加上 <b> 與字級，不會解析使用者的 HTML。

    text() 回傳去掉格式後的純文字。
    """

    def __init__(self, runs: list[tuple[str, bool, int | None]], parent: QWidget | None = None,
                 selectable: bool = True):
        super().__init__(parent)
        self.runs = runs
        self._raw = "".join(text for text, _bold, _size in runs)
        parts = []
        for text, bold, size in runs:
            chunk = html.escape(breakable(text)).replace("\n", "<br>")
            if bold:
                chunk = f"<b>{chunk}</b>"
            if size:
                chunk = f'<span style="font-size:{int(size)}pt">{chunk}</span>'
            parts.append(chunk)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setWordWrap(True)
        super().setText("".join(parts))
        self.setAccessibleName(self._raw)
        if selectable:
            self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def text(self) -> str:
        return self._raw

    def html(self) -> str:
        return super().text()


def plain_label(text: str = "", *, wrap: bool = True, bold: bool = False, selectable: bool = True,
                point_delta: int = 0, color: str | ThemeColor | None = None, parent: QWidget | None = None) -> QLabel:
    if wrap:
        label: QLabel = WrapLabel(text, parent)
    else:
        label = QLabel(parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setText(text)
    if selectable:
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if bold or point_delta:
        font = QFont(label.font())
        font.setBold(bold)
        if point_delta:
            font.setPointSize(max(6, font.pointSize() + point_delta))
        label.setFont(font)
    if color:
        label.setStyleSheet(f"color: {color};")
    label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    return label


class ClickableLabel(WrapLabel):
    """可換行的選項文字；點擊時觸發旁邊的按鈕，讓長選項也容易點選。"""

    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt 命名)
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        super().mouseReleaseEvent(event)


def tool_button(text: str, tooltip: str, parent: QWidget | None = None) -> QToolButton:
    button = QToolButton(parent)
    button.setText(text)
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAutoRaise(True)
    return button


def push_button(text: str, tooltip: str = "", parent: QWidget | None = None) -> QPushButton:
    button = QPushButton(text, parent)
    if tooltip:
        button.setToolTip(tooltip)
    return button


def h_line(parent: QWidget | None = None) -> QFrame:
    line = QFrame(parent)
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Sunken)
    return line


class ImageView(QWidget):
    """依可用寬度等比例縮小顯示圖片；點一下開啟原尺寸檢視。

    width 為題目設定的顯示寬度（可大於原尺寸，用來放大小截圖）；未設定時以原尺寸為上限。
    """

    def __init__(self, image: QImage, description: str | None = None, parent: QWidget | None = None,
                 zoomable: bool = True, max_width: int | None = None, width: int | None = None):
        super().__init__(parent)
        description = tr('圖片') if description is None else description
        self.pixmap = QPixmap.fromImage(image)
        self.zoomable = zoomable
        self.max_width = max_width
        self.display_width = width
        self.setAccessibleName(description)
        if zoomable:
            self.setToolTip(tr('點一下以原尺寸檢視'))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _target(self, width: int) -> QSize:
        size = self.pixmap.size()
        if size.isEmpty():
            return QSize(0, 0)
        natural = self.display_width or size.width()
        w = max(1, min(width, natural, self.max_width or natural))
        return QSize(w, max(1, round(size.height() * w / size.width())))

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._target(width).height()

    def sizeHint(self) -> QSize:  # noqa: N802
        return self._target(self.display_width or self.pixmap.width())

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        smallest = min(48, self.display_width or self.pixmap.width())
        return QSize(smallest, self._target(smallest).height())

    def paintEvent(self, event):  # noqa: N802
        target = self._target(self.width())
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(0, 0, target.width(), target.height(), self.pixmap)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.height() != self.heightForWidth(self.width()):
            self.updateGeometry()

    def mousePressEvent(self, event):  # noqa: N802
        if self.zoomable:
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if not self.zoomable:
            event.ignore()  # 交給外層（例如點選項＝選取該選項）
            return
        if event.button() == Qt.MouseButton.LeftButton:
            dialog = QDialog(self)
            dialog.setWindowTitle(self.accessibleName())
            layout = QVBoxLayout(dialog)
            area = QScrollArea()
            label = QLabel()
            label.setPixmap(self.pixmap)
            area.setWidget(label)
            layout.addWidget(area)
            dialog.resize(min(self.pixmap.width() + 40, 1400), min(self.pixmap.height() + 40, 900))
            dialog.exec()
        super().mouseReleaseEvent(event)
