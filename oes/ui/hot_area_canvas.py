"""熱區題畫布：顯示背景圖片與矩形區域。

- 作答模式：點選區域切換選取；鍵盤可用方向鍵移動焦點、空白鍵選取。
- 編輯模式：在空白處拖曳建立區域；拖曳區域移動；拖曳右下角調整大小；Delete 刪除；
  貼上（Ctrl+V）或拖入圖片檔設定背景。
區域座標一律以原圖像素儲存，畫面依可用寬度等比例縮小（不放大）。
"""
from __future__ import annotations

from ..i18n import tr

from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QKeySequence, QPainter, QPen, QTextOption
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget

from ..core import question_types as qt
from .theme import COLORS

HANDLE = 8
MIN_SIZE = 4
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")


class HotAreaCanvas(QWidget):
    changed = Signal()                # 作答選取改變
    areasChanged = Signal()           # 編輯模式：新增、移動、調整或刪除區域
    currentChanged = Signal(str)      # 編輯模式：目前選取的區域
    deleteRequested = Signal(str)     # 編輯模式：要求刪除區域（由編輯器處理正解）
    imageProvided = Signal(QImage)    # 編輯模式：貼上或拖入新背景
    fileProvided = Signal(str)        # 編輯模式：拖入圖片檔路徑

    def __init__(self, image: QImage | None, areas: list[dict], editable: bool = False,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.image = image if image is not None and not image.isNull() else None
        self.areas = areas                 # 編輯模式下直接修改題目的 areas 清單
        self.editable = editable
        self.selected: list[str] = []
        self.correct: set[str] = set()     # 編輯模式標示正解；作答檢討時顯示正解
        self.review = False
        self.read_only = False
        self.current: str | None = None
        self.hover: str | None = None
        self.focus_index = 0
        self._drag_mode: str | None = None
        self._drag_start = QPointF()
        self._drag_origin: dict | None = None
        self._new_rect: QRectF | None = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(editable)
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setAccessibleName(tr('熱區圖片'))

    # ------------------------------------------------------------ 尺寸
    def set_image(self, image: QImage | None) -> None:
        self.image = image if image is not None and not image.isNull() else None
        self.updateGeometry()
        self.update()

    def _scale(self) -> float:
        if self.image is None or self.image.width() == 0:
            return 1.0
        return min(1.0, max(1, self.width()) / self.image.width())

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        if self.image is None:
            return 180
        scale = min(1.0, width / max(1, self.image.width()))
        return max(1, round(self.image.height() * scale))

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.image.size() if self.image is not None else QSize(480, 180)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(120, 60)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self.height() != self.heightForWidth(self.width()):
            self.updateGeometry()

    def _view_rect(self, area: dict) -> QRectF:
        s = self._scale()
        return QRectF(area["x"] * s, area["y"] * s, area["w"] * s, area["h"] * s)

    def _to_image(self, point: QPointF) -> QPointF:
        s = self._scale()
        return QPointF(point.x() / s, point.y() / s)

    def area_at(self, point: QPointF) -> str | None:
        for area in reversed(self.areas):
            if self._view_rect(area).contains(point):
                return area["id"]
        return None

    def _area(self, area_id: str | None) -> dict | None:
        return next((a for a in self.areas if a["id"] == area_id), None)

    # ------------------------------------------------------------ 繪製
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self.image is None:
            painter.setPen(QPen(QColor(COLORS["canvas_hint"]), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
            text = tr('在此貼上（Ctrl+V）或拖入背景圖片') if self.editable else tr('（沒有背景圖片）')
            painter.drawText(QRectF(self.rect()), text, QTextOption(Qt.AlignmentFlag.AlignCenter))
            return
        s = self._scale()
        painter.drawImage(QRectF(0, 0, self.image.width() * s, self.image.height() * s), self.image)
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        for index, area in enumerate(self.areas):
            rect = self._view_rect(area)
            chosen = area["id"] in self.selected
            fill = None
            pen = QPen(QColor(0, 90, 180), 1.5)
            if self.editable:
                if area["id"] in self.correct:
                    fill = QColor(26, 127, 55, 70)
                    pen = QPen(QColor(26, 127, 55), 2)
                if area["id"] == self.current:
                    pen = QPen(QColor(230, 120, 0), 2.5)
            else:
                if chosen:
                    fill = QColor(0, 120, 215, 90)
                    pen = QPen(QColor(0, 90, 180), 2.5)
                elif area["id"] == self.hover and not self.read_only:
                    fill = QColor(0, 120, 215, 40)
                if self.review:
                    if area["id"] in self.correct:
                        fill = QColor(76, 175, 80, 110)  # 檢討時正確區域以綠色填滿（同常見考題的答案標示）
                        pen = QPen(QColor(26, 127, 55), 3)
                    elif chosen:
                        pen = QPen(QColor(198, 40, 40), 3)
            if fill is not None:
                painter.fillRect(rect, fill)
            painter.setPen(pen)
            painter.drawRect(rect)
            if self.editable:
                painter.drawText(rect.topLeft() + QPointF(3, 13), str(index + 1))
                if area["id"] == self.current:
                    corner = rect.bottomRight()
                    painter.fillRect(QRectF(corner.x() - HANDLE, corner.y() - HANDLE, HANDLE, HANDLE),
                                     QColor(230, 120, 0))
            if self.hasFocus() and not self.editable and index == self.focus_index:
                painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.PenStyle.DotLine))
                painter.drawRect(rect.adjusted(-3, -3, 3, 3))
        if self._new_rect is not None:
            painter.setPen(QPen(QColor(230, 120, 0), 1.5, Qt.PenStyle.DashLine))
            s = self._scale()
            r = self._new_rect
            painter.drawRect(QRectF(r.x() * s, r.y() * s, r.width() * s, r.height() * s))

    # ------------------------------------------------------------ 作答
    def toggle(self, area_id: str) -> None:
        if self.read_only or self.editable:
            return
        if area_id in self.selected:
            self.selected.remove(area_id)
        else:
            self.selected.append(area_id)
        self.update()
        self.changed.emit()

    # ------------------------------------------------------------ 滑鼠
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        self.setFocus()
        if not self.editable:
            area_id = self.area_at(pos)
            if area_id is not None:
                self.focus_index = [a["id"] for a in self.areas].index(area_id)
                self.toggle(area_id)
            return
        if self.image is None:
            return
        current = self._area(self.current)
        if current is not None:
            corner = self._view_rect(current).bottomRight()
            if abs(pos.x() - corner.x()) <= HANDLE and abs(pos.y() - corner.y()) <= HANDLE:
                self._begin_drag("resize", pos, current)
                return
        area_id = self.area_at(pos)
        if area_id is not None:
            self.set_current(area_id)
            self._begin_drag("move", pos, self._area(area_id))
            return
        self._drag_mode = "create"
        self._drag_start = self._to_image(pos)
        self._new_rect = QRectF(self._drag_start, self._drag_start)

    def _begin_drag(self, mode: str, pos: QPointF, area: dict | None) -> None:
        self._drag_mode = mode
        self._drag_start = self._to_image(pos)
        self._drag_origin = dict(area) if area else None

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position()
        if self._drag_mode is None:
            hover = self.area_at(pos)
            if hover != self.hover:
                self.hover = hover
                self.update()
            return
        point = self._clamp(self._to_image(pos))
        if self._drag_mode == "create":
            self._new_rect = QRectF(self._drag_start, point).normalized()
        elif self._drag_origin is not None:
            area = self._area(self._drag_origin["id"])
            dx = point.x() - self._drag_start.x()
            dy = point.y() - self._drag_start.y()
            if self._drag_mode == "move":
                max_x = (self.image.width() if self.image else 10_000) - area["w"]
                max_y = (self.image.height() if self.image else 10_000) - area["h"]
                area["x"] = int(min(max(0, self._drag_origin["x"] + dx), max(0, max_x)))
                area["y"] = int(min(max(0, self._drag_origin["y"] + dy), max(0, max_y)))
            else:
                area["w"] = int(max(MIN_SIZE, self._drag_origin["w"] + dx))
                area["h"] = int(max(MIN_SIZE, self._drag_origin["h"] + dy))
                if self.image is not None:
                    area["w"] = min(area["w"], self.image.width() - area["x"])
                    area["h"] = min(area["h"], self.image.height() - area["y"])
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        mode, self._drag_mode = self._drag_mode, None
        if mode == "create" and self._new_rect is not None:
            rect = self._new_rect
            self._new_rect = None
            if rect.width() >= MIN_SIZE and rect.height() >= MIN_SIZE:
                self.add_area(QRect(int(rect.x()), int(rect.y()), int(rect.width()), int(rect.height())))
            self.update()
        elif mode in ("move", "resize") and self._drag_origin is not None:
            area = self._area(self._drag_origin["id"])
            if area is not None and area != self._drag_origin:
                self.areasChanged.emit()
        self._drag_origin = None

    def leaveEvent(self, event):  # noqa: N802
        self.hover = None
        self.update()

    def _clamp(self, point: QPointF) -> QPointF:
        if self.image is None:
            return point
        return QPointF(min(max(0.0, point.x()), self.image.width()), min(max(0.0, point.y()), self.image.height()))

    # ------------------------------------------------------------ 編輯
    def add_area(self, rect: QRect) -> str:
        area_id = qt.next_id([a["id"] for a in self.areas], "a")
        self.areas.append({"id": area_id, "x": rect.x(), "y": rect.y(), "w": rect.width(), "h": rect.height()})
        self.set_current(area_id)
        self.areasChanged.emit()
        return area_id

    def set_current(self, area_id: str | None) -> None:
        self.current = area_id
        self.update()
        self.currentChanged.emit(area_id or "")

    # ------------------------------------------------------------ 鍵盤、貼上、拖放
    def keyPressEvent(self, event):  # noqa: N802
        if self.editable:
            if event.matches(QKeySequence.StandardKey.Paste):
                self._paste(QApplication.clipboard().mimeData())
                return
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.current:
                self.deleteRequested.emit(self.current)
                return
            super().keyPressEvent(event)
            return
        if not self.areas:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.focus_index = (self.focus_index + 1) % len(self.areas)
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.focus_index = (self.focus_index - 1) % len(self.areas)
        elif key in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.toggle(self.areas[self.focus_index]["id"])
        else:
            super().keyPressEvent(event)
            return
        self.update()

    def _paste(self, mime) -> bool:
        if mime is None:
            return False
        if mime.hasImage():
            data = mime.imageData()
            image = data.toImage() if hasattr(data, "toImage") else QImage(data)
            if not image.isNull():
                self.imageProvided.emit(image)
                return True
        for url in mime.urls() if mime.hasUrls() else []:
            if url.isLocalFile() and url.toLocalFile().lower().endswith(IMAGE_SUFFIXES):
                self.fileProvided.emit(str(Path(url.toLocalFile())))
                return True
        return False

    def dragEnterEvent(self, event):  # noqa: N802
        mime = event.mimeData()
        if self.editable and (mime.hasImage() or any(
                u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_SUFFIXES) for u in mime.urls())):
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        if self._paste(event.mimeData()):
            event.acceptProposedAction()

    def point_of(self, area_id: str) -> QPoint:
        """區域中心在畫面上的位置（測試與輔助用）。"""
        return self._view_rect(self._area(area_id)).center().toPoint()
