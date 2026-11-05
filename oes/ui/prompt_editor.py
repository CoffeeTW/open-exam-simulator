"""可插入圖片的純文字編輯框（題目內容與選擇題選項共用）。

圖片可用貼上（Ctrl+V）或拖放圖片檔加入，顯示在框內游標位置；拖曳圖片右下角或按右鍵可調整顯示大小。
儲存時文字保持純文字，圖片位置轉成 {{image:ID}} 標記；圖片資料（含選填的顯示寬度 width）放在題目的 images 清單。
同一題的所有編輯框共用一個 ImagePool，確保圖片 ID 不重複。
"""
from __future__ import annotations

from ..i18n import tr

import base64
import json
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QPointF, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (QAction, QColor, QFont, QImage, QImageReader, QImageWriter, QKeySequence, QPainter, QPen, QPixmap,
                           QTextCharFormat, QTextCursor, QTextDocument, QTextFormat, QTextImageFormat)
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QMenu, QMessageBox, QSizePolicy, QSpinBox, QTextEdit, QToolButton, QToolTip,
                               QVBoxLayout, QWidget)

from ..core import question_types as qt
from .widgets import MUTED_COLOR, plain_label

RESOURCE_PREFIX = "oesimg:"
CLIP_MIME = "application/x-open-exam-simulator-fragment"   # 程式內複製貼上（文字標記＋圖片資料）
OBJECT_CHAR = "￼"
MAX_WIDTH = 1600            # 超過此寬度的圖片會先等比例縮小
KEEP_ORIGINAL = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
                 ".webp": "image/webp"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
BOLD = 700
NORMAL = 400
FONT_SIZES = (10, 12, 14, 16, 18, 20, 24, 28, 32)
IMAGE_FILTER = "圖片 (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
IMAGE_SCALES = (25, 50, 75, 100, 150, 200)   # 右鍵選單的比例（相對原尺寸）
HANDLE = 12        # 圖片右下角拖曳控點的大小（像素）
EDGE = 6           # 圖片右邊緣可拖曳的寬度（像素）


_WEBP: bool | None = None


def webp_supported() -> bool:
    """Qt 的 WebP 外掛是否可用（PySide6 內附；缺少時改存 PNG）。"""
    global _WEBP
    if _WEBP is None:
        _WEBP = (b"webp" in [bytes(f).lower() for f in QImageWriter.supportedImageFormats()]
                 and b"webp" in [bytes(f).lower() for f in QImageReader.supportedImageFormats()])
    return _WEBP


def _save(image: QImage, fmt: str, quality: int = -1) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, fmt, quality):
        return b""
    return bytes(buffer.data())


def _same_pixels(a: QImage, b: QImage) -> bool:
    fmt = QImage.Format.Format_ARGB32_Premultiplied  # 完全透明的像素只比對透明度
    return a.size() == b.size() and a.convertToFormat(fmt) == b.convertToFormat(fmt)


def lossless_encode(image: QImage) -> tuple[str, bytes]:
    """無失真編碼：PNG 與 WebP 無失真格式中取較小者。WebP 會先解碼比對，確認每個像素都相同才採用。"""
    best = ("image/png", _save(image, "PNG"))
    if webp_supported():
        webp = _save(image, "WEBP", 100)  # Qt 的 WebP 品質 100 即為無失真模式
        if webp and len(webp) < len(best[1]):
            decoded = QImage()
            if decoded.loadFromData(QByteArray(webp)) and _same_pixels(image, decoded):
                best = ("image/webp", webp)
    return best


def encode_image(image: QImage) -> tuple[str, str]:
    """把 QImage 轉成 (mime, base64)。大圖先縮小到 1600 像素寬；之後以無失真格式（WebP 或 PNG）儲存。"""
    if image.width() > MAX_WIDTH:
        image = image.scaledToWidth(MAX_WIDTH, Qt.TransformationMode.SmoothTransformation)
    mime, data = lossless_encode(image)
    return mime, base64.b64encode(data).decode("ascii")


def load_image_file(path: Path) -> tuple[str, str]:
    """讀取圖片檔，回傳 (mime, base64)。JPEG、GIF 保留原檔；其他格式以無失真格式重新編碼（較小時才採用）。
    無法辨識時拋出 ValueError。"""
    raw = path.read_bytes()
    image = QImage()
    if not image.loadFromData(QByteArray(raw)):
        raise ValueError(tr('無法辨識的圖片：{0}', path.name))
    mime = KEEP_ORIGINAL.get(path.suffix.lower())
    fits = image.width() <= MAX_WIDTH and len(raw) <= qt.MAX_IMAGE_BYTES
    if mime and fits and mime != "image/png":
        return mime, base64.b64encode(raw).decode("ascii")
    encoded = encode_image(image)
    if mime and fits and len(raw) <= len(encoded[1]) * 3 // 4:
        return mime, base64.b64encode(raw).decode("ascii")
    return encoded


def recompress_images(images: list[dict]) -> tuple[int, int, int]:
    """把 PNG 等圖片就地改存成較小的無失真格式（像素完全不變；JPEG、GIF 不處理）。
    回傳（改存張數, 原大小, 新大小），大小以位元組計。"""
    changed = before = after = 0
    for image in images:
        if not isinstance(image, dict) or image.get("mime") not in ("image/png", "image/webp"):
            continue
        try:
            raw = qt.image_bytes(image)
        except (ValueError, KeyError):
            continue
        decoded = QImage()
        if not decoded.loadFromData(QByteArray(raw)):
            continue
        mime, data = lossless_encode(decoded)
        if len(data) < len(raw):
            image["mime"] = mime
            image["data"] = base64.b64encode(data).decode("ascii")
            changed += 1
            before += len(raw)
            after += len(data)
    return changed, before, after


def recompress_exam(exam: dict) -> tuple[int, int, int]:
    """壓縮整份題庫（題目與案例研究）的圖片，回傳（改存張數, 原大小, 新大小）。"""
    total = [0, 0, 0]
    groups = [entry["question"].get("images") for entry in exam.get("questions", [])]
    groups += [case.get("images") for case in exam.get("caseStudies", [])]
    for images in groups:
        if isinstance(images, list):
            for index, value in enumerate(recompress_images(images)):
                total[index] += value
    return total[0], total[1], total[2]


class ImagePool:
    """一題內所有編輯框共用的圖片資料。"""

    def __init__(self, images: list[dict] | None = None):
        self.images: dict[str, dict] = {}
        self.decoded: dict[str, QImage] = {}
        for image in images or []:
            if isinstance(image, dict) and isinstance(image.get("id"), str):
                self.images[image["id"]] = {k: image[k] for k in ("id", "mime", "data", "width") if k in image}

    def add(self, mime: str, data: str) -> str:
        image_id = qt.next_id(list(self.images), "img")
        self.images[image_id] = {"id": image_id, "mime": mime, "data": data}
        if self.qimage(image_id) is None:
            del self.images[image_id]
            raise ValueError(tr('無法顯示這張圖片。'))
        return image_id

    def qimage(self, image_id: str) -> QImage | None:
        if image_id not in self.decoded:
            image = QImage()
            try:
                ok = image_id in self.images and image.loadFromData(QByteArray(qt.image_bytes(self.images[image_id])))
            except ValueError:
                ok = False
            if not ok:
                return None
            self.decoded[image_id] = image
        return self.decoded[image_id]

    def width(self, image_id: str) -> int | None:
        return qt.image_width(self.images.get(image_id))

    def set_width(self, image_id: str, width: int | None) -> None:
        """設定顯示寬度；None 或等於原尺寸時移除設定（依原尺寸顯示）。"""
        image = self.images.get(image_id)
        if image is None:
            return
        natural = self.qimage(image_id)
        if width is not None:
            width = max(qt.MIN_IMAGE_WIDTH, min(qt.MAX_IMAGE_WIDTH, int(width)))
        if width is None or (natural is not None and width == natural.width()):
            image.pop("width", None)
        else:
            image["width"] = width

    def collect(self, refs: list[str]) -> list[dict]:
        return [dict(self.images[i]) for i in refs if i in self.images]


class RichTextEdit(QTextEdit):
    """純文字＋圖片的編輯框。allow_format=True 時另可設定粗體與字級（題目內容、案例研究使用）。"""

    def __init__(self, pool: ImagePool, display_width: int = 520, parent: QWidget | None = None,
                 allow_format: bool = False):
        super().__init__(parent)
        self.pool = pool
        self.display_width = display_width
        self.allow_format = allow_format
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)
        self.viewport().setMouseTracking(True)
        self._hover: str | None = None          # 滑鼠所在的圖片 ID（畫外框與控點）
        self._drag: dict | None = None          # 拖曳調整大小中的狀態

    # ------------------------------------------------------------ 文字格式
    def base_size(self) -> float:
        size = self.document().defaultFont().pointSizeF()
        return size if size > 0 else self.font().pointSizeF()

    def set_bold(self, on: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(BOLD if on else NORMAL)
        self.mergeCurrentCharFormat(fmt)
        self.textChanged.emit()

    def set_size(self, size: int | None) -> None:
        """size 為 None 時恢復預設字級。"""
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(size) if size else self.base_size())
        self.mergeCurrentCharFormat(fmt)
        self.textChanged.emit()

    def current_style(self) -> tuple[bool, int | None]:
        return self._style_of(self.currentCharFormat())

    def _style_of(self, fmt: QTextCharFormat) -> tuple[bool, int | None]:
        bold = fmt.fontWeight() >= 600
        size = None
        if fmt.hasProperty(QTextFormat.Property.FontPointSize):
            value = fmt.fontPointSize()
            if value > 0 and abs(value - self.base_size()) > 0.5:
                size = int(round(value))
        return bold, size

    def _styles(self, text: str, formats: list) -> list[tuple[bool, int | None]]:
        """每個字元的（粗體, 字級）。換行與圖片沒有自己的格式：取前後文字共同的部分，讓標記盡量精簡。"""
        styles: list[tuple[bool, int | None] | None] = [
            None if char in ("\n", OBJECT_CHAR) else self._style_of(fmt) for char, fmt in zip(text, formats)]
        result: list[tuple[bool, int | None]] = []
        for index, style in enumerate(styles):
            if style is not None:
                result.append(style)
                continue
            before = next((s for s in reversed(styles[:index]) if s is not None), (False, None))
            after = next((s for s in styles[index + 1:] if s is not None), (False, None))
            result.append((before[0] and after[0], before[1] if before[1] == after[1] else None))
        return result

    def keyPressEvent(self, event):  # noqa: N802
        if self.allow_format and event.matches(QKeySequence.StandardKey.Bold):
            self.set_bold(not self.current_style()[0])
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 讀入與輸出
    def load(self, text: str) -> None:
        self.blockSignals(True)
        try:
            self.clear()
            cursor = self.textCursor()
            for kind, value in qt.rich_segments(text or ""):
                if kind == "image":
                    if self._register(value):
                        cursor.insertImage(self._image_format(value))
                    else:
                        cursor.insertText("{{image:%s}}" % value)
                    continue
                for chunk, bold, size in value:
                    fmt = QTextCharFormat()
                    if self.allow_format and bold:
                        fmt.setFontWeight(BOLD)
                    if self.allow_format and size:
                        fmt.setFontPointSize(float(size))
                    cursor.insertText(chunk, fmt)
            cursor.setCharFormat(QTextCharFormat())
            self.document().clearUndoRedoStacks()
            self.moveCursor(QTextCursor.MoveOperation.Start)
        finally:
            self.blockSignals(False)

    def serialize(self, start: int = 0, end: int | None = None) -> str:
        """轉成儲存格式：純文字＋{{image:ID}}；allow_format 時再加上 {{b}}…{{/b}}、{{size:N}}…{{/size}}。

        start／end 指定只轉換其中一段（複製選取內容時使用）。
        """
        text = self.document().toPlainText()
        cursor = QTextCursor(self.document())
        formats = []
        for position in range(len(text)):
            cursor.setPosition(position + 1)
            formats.append(cursor.charFormat())
        styles = self._styles(text, formats) if self.allow_format else [(False, None)] * len(text)
        out: list[str] = []
        bold, size = False, None
        end = len(text) if end is None else min(end, len(text))
        for position in range(max(0, start), end):
            char = text[position]
            fmt = formats[position]
            new_bold, new_size = styles[position]
            if new_size != size:  # 字級在外層、粗體在內層，換字級時先關再開
                if bold:
                    out.append("{{/b}}")
                if size:
                    out.append("{{/size}}")
                if new_size:
                    out.append("{{size:%d}}" % new_size)
                if new_bold:
                    out.append("{{b}}")
            elif new_bold != bold:
                out.append("{{b}}" if new_bold else "{{/b}}")
            bold, size = new_bold, new_size
            if char != OBJECT_CHAR:
                out.append(char)
                continue
            name = fmt.toImageFormat().name() if fmt.isImageFormat() else ""
            image_id = name[len(RESOURCE_PREFIX):] if name.startswith(RESOURCE_PREFIX) else ""
            if image_id in self.pool.images:
                out.append("{{image:%s}}" % image_id)
        if bold:
            out.append("{{/b}}")
        if size:
            out.append("{{/size}}")
        return "".join(out)

    # ------------------------------------------------------------ 插入圖片
    def insert_image_data(self, mime: str, data: str) -> str:
        image_id = self.pool.add(mime, data)
        self._register(image_id)
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.positionInBlock() > 0:
            cursor.insertBlock()
        cursor.insertImage(self._image_format(image_id))
        cursor.insertBlock()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return image_id

    def insert_qimage(self, image: QImage) -> str:
        return self.insert_image_data(*encode_image(image))

    def insert_file(self, path: Path) -> str:
        return self.insert_image_data(*load_image_file(path))

    def choose_images(self) -> None:
        names, _ = QFileDialog.getOpenFileNames(self, tr('插入圖片'), str(Path.home()), tr(IMAGE_FILTER))
        for name in names:
            try:
                self.insert_file(Path(name))
            except (OSError, ValueError) as exc:
                QMessageBox.warning(self, tr('無法插入圖片'), str(exc))
        self.setFocus()

    def _register(self, image_id: str) -> bool:
        image = self.pool.qimage(image_id)
        if image is None:
            return False
        self.document().addResource(QTextDocument.ResourceType.ImageResource, QUrl(RESOURCE_PREFIX + image_id), image)
        return True

    def _image_format(self, image_id: str) -> QTextImageFormat:
        fmt = QTextImageFormat()
        fmt.setName(RESOURCE_PREFIX + image_id)
        image = self.pool.qimage(image_id)
        if image is None or image.width() <= 0:
            return fmt
        width = min(self.pool.width(image_id) or image.width(), self.width_limit())  # 編輯框內最多顯示到框寬
        return self._sized_format(image_id, width)

    def width_limit(self) -> int:
        return max(self.display_width, self.viewport().width() - 24)

    def _sized_format(self, image_id: str, width: int) -> QTextImageFormat:
        fmt = QTextImageFormat()
        fmt.setName(RESOURCE_PREFIX + image_id)
        image = self.pool.qimage(image_id)
        if image is None or image.width() <= 0:
            return fmt
        if width != image.width():
            fmt.setWidth(width)
            fmt.setHeight(image.height() * width / image.width())
        return fmt

    # ------------------------------------------------------------ 圖片大小
    def image_at(self, position) -> str | None:
        """滑鼠位置上的圖片 ID（沒有圖片時為 None）。以圖片實際顯示的範圍判斷（與拖曳縮放相同）。"""
        return self._image_under(QPointF(position))

    def selected_image(self) -> str | None:
        """目前選取的內容恰好是一張圖片時，回傳其 ID。"""
        cursor = self.textCursor()
        if cursor.selectionEnd() - cursor.selectionStart() != 1:
            return None
        probe = QTextCursor(self.document())
        probe.setPosition(cursor.selectionStart())
        probe.setPosition(cursor.selectionEnd(), QTextCursor.MoveMode.KeepAnchor)
        fmt = probe.charFormat()
        if probe.selectedText() != OBJECT_CHAR or not fmt.isImageFormat():
            return None
        name = fmt.toImageFormat().name()
        image_id = name[len(RESOURCE_PREFIX):] if name.startswith(RESOURCE_PREFIX) else ""
        return image_id if image_id in self.pool.images else None

    def resize_image(self, image_id: str, width: int | None) -> None:
        """設定圖片顯示寬度並更新框內顯示；width 為 None 時恢復原尺寸。"""
        self.pool.set_width(image_id, width)
        self._apply_format(image_id, self._image_format(image_id))
        self.textChanged.emit()

    def _apply_format(self, image_id: str, fmt: QTextImageFormat) -> None:
        name = RESOURCE_PREFIX + image_id
        block = self.document().begin()
        cursor = QTextCursor(self.document())
        cursor.beginEditBlock()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                current = fragment.charFormat()
                if current.isImageFormat() and current.toImageFormat().name() == name:
                    cursor.setPosition(fragment.position())
                    cursor.setPosition(fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor)
                    cursor.setCharFormat(fmt)
                it += 1
            block = block.next()
        cursor.endEditBlock()

    # ------------------------------------------------------------ 滑鼠拖曳調整大小
    def image_rects(self) -> list[tuple[str, QRectF]]:
        """框內每張圖片的（ID, 位置），座標為 viewport 座標。"""
        rects: list[tuple[str, QRectF]] = []
        offset = QPointF(self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        block = self.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                if fmt.isImageFormat():
                    name = fmt.toImageFormat().name()
                    image_id = name[len(RESOURCE_PREFIX):] if name.startswith(RESOURCE_PREFIX) else ""
                    image = self.pool.qimage(image_id) if image_id in self.pool.images else None
                    text_layout = block.layout()
                    if image is not None and text_layout is not None:
                        image_fmt = fmt.toImageFormat()
                        w = image_fmt.width() if image_fmt.width() > 0 else image.width()
                        h = image_fmt.height() if image_fmt.height() > 0 else image.height() * w / image.width()
                        for index in range(fragment.length()):
                            relative = fragment.position() + index - block.position()
                            line = text_layout.lineForTextPosition(relative)
                            if not line.isValid():
                                continue
                            origin = text_layout.position()
                            cx = line.cursorToX(relative)
                            x = origin.x() + (cx[0] if isinstance(cx, tuple) else cx)
                            y = origin.y() + line.y() + line.ascent() - h
                            rects.append((image_id, QRectF(x, y, w, h).translated(-offset)))
                it += 1
            block = block.next()
        return rects

    def handle_at(self, point: QPointF) -> tuple[str, QRectF, str] | None:
        """滑鼠位置若在圖片的右下角控點或右邊緣，回傳（ID, 位置, "corner" 或 "edge"）。"""
        for image_id, rect in self.image_rects():
            corner = QRectF(rect.right() - HANDLE, rect.bottom() - HANDLE, HANDLE + 3, HANDLE + 3)
            if corner.contains(point):
                return image_id, rect, "corner"
            edge = QRectF(rect.right() - EDGE, rect.top(), EDGE + 3, rect.height())
            if edge.contains(point):
                return image_id, rect, "edge"
        return None

    def _image_under(self, point: QPointF) -> str | None:
        for image_id, rect in self.image_rects():
            if rect.adjusted(-2, -2, 4, 4).contains(point):
                return image_id
        return None

    def mousePressEvent(self, event):  # noqa: N802
        hit = self.handle_at(event.position()) if event.button() == Qt.MouseButton.LeftButton else None
        if hit:
            image_id, rect, _kind = hit
            self._drag = {"id": image_id, "x": event.position().x(), "start": rect.width(),
                          "width": round(rect.width())}
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        point = event.position()
        if self._drag:
            width = round(self._drag["start"] + point.x() - self._drag["x"])
            width = max(qt.MIN_IMAGE_WIDTH, min(qt.MAX_IMAGE_WIDTH, self.width_limit(), width))
            if width != self._drag["width"]:
                self._drag["width"] = width
                self._apply_format(self._drag["id"], self._sized_format(self._drag["id"], width))
                self.viewport().update()
            QToolTip.showText(event.globalPosition().toPoint(), tr('{0} 像素', width), self.viewport())
            event.accept()
            return
        hit = self.handle_at(point)
        if hit:
            shape = Qt.CursorShape.SizeFDiagCursor if hit[2] == "corner" else Qt.CursorShape.SizeHorCursor
            self.viewport().setCursor(shape)
        else:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
        hover = hit[0] if hit else self._image_under(point)
        if hover != self._hover:
            self._hover = hover
            self.viewport().update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag:
            drag, self._drag = self._drag, None
            QToolTip.hideText()
            self.resize_image(drag["id"], drag["width"])
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if self._hover and not self._drag:
            self._hover = None
            self.viewport().update()
        super().leaveEvent(event)

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)
        target = self._drag["id"] if self._drag else self._hover
        if not target:
            return
        painter = QPainter(self.viewport())
        color = QColor(self.palette().highlight().color())
        for image_id, rect in self.image_rects():
            if image_id != target:
                continue
            pen = QPen(color, 1, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))
            painter.setPen(QPen(QColor("white"), 1))
            painter.setBrush(color)
            painter.drawRect(QRectF(rect.right() - HANDLE + 1, rect.bottom() - HANDLE + 1, HANDLE - 2, HANDLE - 2))
        painter.end()

    def image_size_menu(self, image_id: str, parent: QWidget | None = None) -> QMenu:
        menu = QMenu(tr('圖片大小'), parent or self)
        natural = self.pool.qimage(image_id)
        base = natural.width() if natural is not None else 0
        current = self.pool.width(image_id) or base
        for scale in IMAGE_SCALES:
            width = max(qt.MIN_IMAGE_WIDTH, min(qt.MAX_IMAGE_WIDTH, round(base * scale / 100)))
            label = tr('{0}%（{1} 像素）', scale, width) if scale != 100 else tr('原始大小（{0} 像素）', base)
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(width == current)
            action.triggered.connect(lambda _c=False, w=width: self.resize_image(image_id, w))
        return menu

    def ask_image_width(self, image_id: str) -> None:
        natural = self.pool.qimage(image_id)
        if natural is None:
            return
        dialog = ImageSizeDialog(natural.size(), self.pool.width(image_id), self)
        if dialog.exec():
            self.resize_image(image_id, dialog.result_width())

    def context_menu(self, pos) -> QMenu:
        """右鍵選單：在圖片上（或已選取一張圖片）時，最上方加入「調整圖片大小…」與比例選單。"""
        menu = self.createStandardContextMenu(pos)
        image_id = self.image_at(pos) or self.selected_image()
        if image_id:
            first = menu.actions()[0] if menu.actions() else None
            resize = QAction(tr('調整圖片大小…'), menu)
            resize.triggered.connect(lambda: self.ask_image_width(image_id))
            menu.insertAction(first, resize)
            menu.insertMenu(first, self.image_size_menu(image_id, menu))
            copy = QAction(tr('複製圖片'), menu)
            copy.triggered.connect(lambda: self.copy_image(image_id))
            menu.insertAction(first, copy)
            if first is not None:
                menu.insertSeparator(first)
        return menu

    def contextMenuEvent(self, event):  # noqa: N802
        menu = self.context_menu(event.pos())
        menu.exec(event.globalPos())
        menu.deleteLater()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        image_id = self.image_at(event.position().toPoint())
        if image_id:
            self.ask_image_width(image_id)
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------ 複製圖片
    def createMimeDataFromSelection(self) -> QMimeData:  # noqa: N802
        """複製選取內容：另附程式自己的格式（文字標記＋圖片資料），貼到其他題目框時保留圖片與大小；
        只選取一張圖片時另附圖片本身，可貼到其他程式。"""
        cursor = self.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        fragment = self.serialize(start, end)
        mime = QMimeData()
        mime.setText(qt.strip_images(qt.strip_format(fragment), "").replace(OBJECT_CHAR, ""))
        if fragment:  # 只有文字時也附上，貼回題目框時保留粗體與字級
            payload = {"text": fragment, "images": self.pool.collect(qt.image_refs(fragment))}
            mime.setData(CLIP_MIME, QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
        image_id = self.selected_image()
        if image_id:
            image = self.pool.qimage(image_id)
            if image is not None:
                mime.setImageData(image)
        return mime

    def insert_fragment(self, text: str, images: list[dict]) -> list[str]:
        """貼上程式自己複製的內容：圖片以新的 ID 加入本題（保留顯示寬度），文字與格式照原樣插入。"""
        mapping: dict[str, str] = {}
        for image in images:
            if not isinstance(image, dict) or not isinstance(image.get("id"), str):
                continue
            try:
                new_id = self.pool.add(image.get("mime", ""), image.get("data", ""))
            except ValueError:
                continue
            if qt.image_width(image):
                self.pool.set_width(new_id, qt.image_width(image))
            mapping[image["id"]] = new_id
        cursor = self.textCursor()
        cursor.beginEditBlock()
        for kind, value in qt.rich_segments(text):
            if kind == "image":
                if value in mapping and self._register(mapping[value]):
                    cursor.insertImage(self._image_format(mapping[value]))
                continue
            for chunk, bold, size in value:
                fmt = QTextCharFormat()
                fmt.setFontWeight(BOLD if self.allow_format and bold else NORMAL)
                fmt.setFontPointSize(float(size) if self.allow_format and size else self.base_size())
                cursor.insertText(chunk, fmt)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return list(mapping.values())

    def _image_position(self, image_id: str) -> int | None:
        name = RESOURCE_PREFIX + image_id
        block = self.document().begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                fragment = it.fragment()
                fmt = fragment.charFormat()
                if fmt.isImageFormat() and fmt.toImageFormat().name() == name:
                    return fragment.position()
                it += 1
            block = block.next()
        return None

    def copy_image(self, image_id: str) -> None:
        """選取這張圖片並複製到剪貼簿。"""
        position = self._image_position(image_id)
        if position is None:
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        self.setTextCursor(cursor)
        self.copy()

    # ------------------------------------------------------------ 貼上與拖放
    @staticmethod
    def _image_paths(source: QMimeData) -> list[Path]:
        if not source.hasUrls():
            return []
        return [Path(u.toLocalFile()) for u in source.urls()
                if u.isLocalFile() and u.toLocalFile().lower().endswith(IMAGE_SUFFIXES)]

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return (source.hasFormat(CLIP_MIME) or source.hasImage() or bool(self._image_paths(source))
                or source.hasText())

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source.hasFormat(CLIP_MIME):
            try:
                payload = json.loads(bytes(source.data(CLIP_MIME)).decode("utf-8"))
                if isinstance(payload, dict) and isinstance(payload.get("text"), str):
                    self.insert_fragment(payload["text"], payload.get("images") or [])
                    return
            except (ValueError, UnicodeDecodeError):
                pass
        try:
            if source.hasImage():
                data = source.imageData()
                image = data.toImage() if isinstance(data, QPixmap) else QImage(data)
                if not image.isNull():
                    self.insert_qimage(image)
                    return
            paths = self._image_paths(source)
            if paths:
                for path in paths:
                    self.insert_file(path)
                return
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('無法插入圖片'), str(exc))
            return
        if source.hasText():
            # 只貼純文字；格式與 HTML 一律捨棄
            self.insertPlainText(source.text().replace(OBJECT_CHAR, ""))


class HeightGrip(QWidget):
    """編輯框下緣的拖曳把手：上下拖曳調整框的高度，放開時記住高度。"""

    resized = Signal(int)
    MIN_HEIGHT = 80
    MAX_HEIGHT = 2000

    def __init__(self, target: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self.target = target
        self._start: tuple[float, int] | None = None
        self.setFixedHeight(10)
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(tr('上下拖曳可調整框的高度'))
        self.setAccessibleName(tr('調整框的高度'))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = (event.globalPosition().y(), self.target.height())
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._start is None:
            return
        y, height = self._start
        self.set_height(round(height + event.globalPosition().y() - y))
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._start is not None:
            self._start = None
            self.resized.emit(self.target.height())
        event.accept()

    def set_height(self, height: int) -> None:
        self.target.setFixedHeight(max(self.MIN_HEIGHT, min(self.MAX_HEIGHT, int(height))))

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        color = QColor(self.palette().mid().color())
        painter.setPen(QPen(color, 1))
        middle = self.width() // 2
        for offset in (-1, 2):  # 中間兩條短線
            y = self.height() // 2 + offset
            painter.drawLine(middle - 14, y, middle + 14, y)
        painter.end()


def saved_height(key: str, default: int) -> int:
    from . import settings
    value = settings.load().get("editorHeights", {})
    height = value.get(key) if isinstance(value, dict) else None
    if isinstance(height, int) and HeightGrip.MIN_HEIGHT <= height <= HeightGrip.MAX_HEIGHT:
        return height
    return default


def remember_height(key: str, height: int) -> None:
    from . import settings
    heights = settings.load().get("editorHeights", {})
    heights = dict(heights) if isinstance(heights, dict) else {}
    heights[key] = int(height)
    settings.save({"editorHeights": heights})


class ImageSizeDialog(QDialog):
    """輸入圖片顯示大小（像素）。寬度與高度連動、維持原比例；可恢復原始大小。"""

    def __init__(self, natural: QSize, current_width: int | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr('調整圖片大小'))
        self.natural = natural
        self.ratio = natural.height() / natural.width() if natural.width() > 0 else 1.0
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(tr('原始大小：{0} × {1} 像素', natural.width(), natural.height()),
                                     color=MUTED_COLOR, selectable=False))
        form = QFormLayout()
        self.width_box = QSpinBox(self)
        self.width_box.setRange(qt.MIN_IMAGE_WIDTH, qt.MAX_IMAGE_WIDTH)
        self.width_box.setSuffix(tr(' 像素'))
        self.height_box = QSpinBox(self)
        self.height_box.setRange(1, max(1, round(qt.MAX_IMAGE_WIDTH * self.ratio)))
        self.height_box.setSuffix(tr(' 像素'))
        form.addRow(tr('寬度：'), self.width_box)
        form.addRow(tr('高度：'), self.height_box)
        layout.addLayout(form)
        layout.addWidget(plain_label(tr('寬度與高度會依原比例連動。'), color=MUTED_COLOR, selectable=False))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('確定'))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr('取消'))
        reset = buttons.addButton(tr('原始大小'), QDialogButtonBox.ButtonRole.ResetRole)
        reset.clicked.connect(lambda: self.set_width(natural.width()))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.width_box.valueChanged.connect(self._width_changed)
        self.height_box.valueChanged.connect(self._height_changed)
        self.set_width(current_width or natural.width())
        self.width_box.setFocus()
        self.width_box.selectAll()

    def set_width(self, width: int) -> None:
        self.width_box.setValue(max(qt.MIN_IMAGE_WIDTH, min(qt.MAX_IMAGE_WIDTH, int(width))))
        self._width_changed(self.width_box.value())

    def _width_changed(self, width: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        self.height_box.setValue(max(1, round(width * self.ratio)))
        self._syncing = False

    def _height_changed(self, height: int) -> None:
        if self._syncing or self.ratio <= 0:
            return
        self._syncing = True
        self.width_box.setValue(round(height / self.ratio))
        self._syncing = False

    def result_width(self) -> int | None:
        """設定的寬度；等於原始寬度時回傳 None（不另存寬度）。"""
        width = self.width_box.value()
        return None if width == self.natural.width() else width


class PromptEditor(QWidget):
    """題目內容編輯區：工具列＋可插入圖片的文字框。changed 參數為新的題目內容文字。"""

    changed = Signal(str)

    def __init__(self, prompt: str, pool: ImagePool, parent: QWidget | None = None, placeholder: str | None = None,
                 minimum_height: int = 200, height_key: str = "prompt"):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = RichTextEdit(pool, 520, self, allow_format=True)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.bold_button = QToolButton(self)
        self.bold_button.setText("B")
        bold_font = QFont(self.bold_button.font())
        bold_font.setBold(True)
        self.bold_button.setFont(bold_font)
        self.bold_button.setCheckable(True)
        self.bold_button.setToolTip(tr('粗體（Ctrl+B）'))
        self.bold_button.setAccessibleName(tr('粗體（Ctrl+B）'))
        self.bold_button.clicked.connect(lambda checked: (self.edit.set_bold(checked), self.edit.setFocus()))
        bar.addWidget(self.bold_button)
        bar.addWidget(QLabel(tr('字級：'), self))
        self.size_combo = QComboBox(self)
        self.size_combo.addItem(tr('預設'), None)
        for size in FONT_SIZES:
            self.size_combo.addItem(str(size), size)
        self.size_combo.setToolTip(tr('選取文字後設定字級；未選取時套用到接著輸入的文字'))
        self.size_combo.activated.connect(self._size_chosen)
        bar.addWidget(self.size_combo)
        bar.addStretch(1)
        layout.addLayout(bar)
        self.edit.currentCharFormatChanged.connect(lambda _fmt: self._sync_toolbar())
        self.edit.setPlaceholderText(tr('題目內容；可使用的題目必須填寫') if placeholder is None else placeholder)
        self.edit.setFixedHeight(saved_height(height_key, minimum_height))
        self.edit.load(prompt)
        self.edit.textChanged.connect(lambda: self.changed.emit(self.edit.serialize()))
        layout.addWidget(self.edit)
        self.grip = HeightGrip(self.edit, self)
        self.grip.resized.connect(lambda height: remember_height(height_key, height))
        layout.addWidget(self.grip)
        layout.addWidget(plain_label(tr('插入圖片：在框內貼上（Ctrl+V），或把圖片檔拖進框內。調整大小：拖曳圖片右下角，或在圖片上按右鍵。'), color=MUTED_COLOR,
                                     selectable=False))
        self._sync_toolbar()

    def _size_chosen(self, index: int) -> None:
        self.edit.set_size(self.size_combo.itemData(index))
        self.edit.setFocus()

    def _sync_toolbar(self) -> None:
        bold, size = self.edit.current_style()
        self.bold_button.setChecked(bold)
        self.size_combo.blockSignals(True)
        index = self.size_combo.findData(size) if size else 0
        if index < 0:  # 不在清單中的字級（例如匯入的資料）
            self.size_combo.addItem(str(size), size)
            index = self.size_combo.count() - 1
        self.size_combo.setCurrentIndex(index)
        self.size_combo.blockSignals(False)


class OptionTextEdit(QWidget):
    """選項文字框：高度隨內容自動調整，可貼上或插入圖片。changed 參數為新的選項文字。"""

    changed = Signal(str)

    def __init__(self, text: str, pool: ImagePool, placeholder: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        placeholder = tr('選項文字') if placeholder is None else placeholder
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.edit = RichTextEdit(pool, 240, self)
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFrameShape(QFrame.Shape.StyledPanel)
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.load(text)
        self.edit.document().documentLayout().documentSizeChanged.connect(lambda _size: self._fit())
        self.edit.textChanged.connect(lambda: self.changed.emit(self.edit.serialize()))
        self.edit.setToolTip(tr('插入圖片：貼上（Ctrl+V）或把圖片檔拖進框內；拖曳圖片右下角可調整大小'))
        layout.addWidget(self.edit, 1)
        self._fit()

    def _fit(self) -> None:
        line = self.edit.fontMetrics().lineSpacing()
        height = int(self.edit.document().size().height()) + 2 * self.edit.frameWidth() + 4
        self.edit.setFixedHeight(max(line + 14, min(height, 400)))

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._fit()
