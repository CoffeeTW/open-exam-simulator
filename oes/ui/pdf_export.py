"""匯出題庫 PDF：以 core.printable 產生的 HTML 排版，圖片（含熱區題的區域框）由這裡載入。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QSizeF, Qt, QUrl
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter,
                           QPen, QTextDocument)
from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from ..core import question_types as qt
from ..core.printable import build_html
from ..i18n import tr
from .widgets import MUTED_COLOR, plain_label

RESOLUTION = 96   # 版面以 96 DPI 計算，圖片的像素寬度與畫面上相同
STYLE = """
h1 { font-size: 18pt; margin-bottom: 2px; }
h3 { font-size: 13pt; margin-top: 14px; margin-bottom: 4px; }
p { margin-top: 3px; margin-bottom: 3px; }
th { background-color: #f0f0f0; }
"""


def render_image(request: dict) -> QImage | None:
    """解碼圖片；熱區題另外畫出各區域（正確區域填綠色）。"""
    image = QImage()
    try:
        if not image.loadFromData(QByteArray(qt.image_bytes(request["image"]))):
            return None
    except (KeyError, ValueError):
        return None
    if not request.get("areas"):
        return image
    image = image.convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    correct = set(request.get("correct") or [])
    for area in request["areas"]:
        rect = QRectF(area["x"], area["y"], area["w"], area["h"])
        if area["id"] in correct:
            painter.fillRect(rect, QColor(40, 170, 70, 90))
            painter.setPen(QPen(QColor(30, 130, 50), 3))
        else:
            painter.setPen(QPen(QColor(37, 99, 235), 2, Qt.PenStyle.DashLine))
        painter.drawRect(rect)
    painter.end()
    return image


def build_document(exam: dict, *, include_answers: bool, only_ready: bool) -> QTextDocument:
    html, requests = build_html(exam, include_answers=include_answers, only_ready=only_ready)
    document = QTextDocument()
    font = QFont(QGuiApplication.font())
    font.setPointSizeF(10.5)
    document.setDefaultFont(font)
    document.setDefaultStyleSheet(STYLE)
    for name, request in requests.items():
        tag = f'<img src="{name}">'
        image = render_image(request)
        if image is None:
            html = html.replace(tag, tr('［無法顯示的圖片：{0}］', request["image"].get("id", name)))
            continue
        document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(name), image)
        width = request.get("width") or image.width()
        width = max(1, min(width, request.get("max_width") or width))
        html = html.replace(tag, f'<img src="{name}" width="{width}" height="{round(image.height() * width / image.width())}">')
    document.setHtml(html)
    return document


def export_pdf(exam: dict, path: str | Path, *, include_answers: bool = True, only_ready: bool = False) -> int:
    """寫出 A4 直式 PDF，回傳頁數。"""
    writer = QPdfWriter(str(path))
    writer.setResolution(RESOLUTION)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    writer.setTitle(exam.get("title") or tr('未命名題庫'))
    writer.setCreator("Open Exam Simulator")
    document = build_document(exam, include_answers=include_answers, only_ready=only_ready)
    page = writer.pageLayout().paintRectPixels(RESOLUTION)
    document.setPageSize(QSizeF(page.width(), page.height()))
    document.print_(writer)
    return document.pageCount()


class PdfExportDialog(QDialog):
    """匯出前的選項：是否包含正確答案與解析、是否只匯出可使用的題目。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr('匯出 PDF'))
        layout = QVBoxLayout(self)
        self.answers = QCheckBox(tr('包含正確答案與解析'))
        self.answers.setChecked(True)
        self.ready = QCheckBox(tr('只匯出「可使用」的題目（略過草稿）'))
        layout.addWidget(self.answers)
        layout.addWidget(plain_label(tr('不勾選時，可以印出來當成考卷作答。'), color=MUTED_COLOR, selectable=False))
        layout.addWidget(self.ready)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('匯出…'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
