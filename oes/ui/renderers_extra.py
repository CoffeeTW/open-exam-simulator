"""排序題、拖放題、熱區題的作答元件，以及案例研究顯示視窗。"""
from __future__ import annotations

from ..i18n import tr

from PySide6.QtCore import QByteArray, QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import question_types as qt
from . import renderers as R
from .hot_area_canvas import HotAreaCanvas
from .theme import COLORS
from .widgets import BAD_COLOR, MUTED_COLOR, OK_COLOR, code_font, plain_label

SOURCE_MIME = "application/x-oes-source"


def _images(dto: dict) -> dict[str, dict]:
    return {image["id"]: image for image in dto.get("images", [])}


def _qimage(images: dict[str, dict], image_id: str | None) -> QImage | None:
    if not image_id or image_id not in images:
        return None
    image = QImage()
    try:
        image.loadFromData(QByteArray(qt.image_bytes(images[image_id])))
    except ValueError:
        return None
    return None if image.isNull() else image


def _set_review(label: QLabel, text: str, color: str) -> None:
    label.setText(text)
    label.setStyleSheet(f"color: {color};")
    label.setVisible(bool(text))


def _verdict(row: dict | None) -> tuple[str, str]:
    if row is None or row["selection"] is None:
        return tr('○ 未作答'), BAD_COLOR
    return (tr('✔ 正確'), OK_COLOR) if row["isCorrect"] else (tr('✘ 錯誤'), BAD_COLOR)


# ---------------------------------------------------------------- 排序題
class BuildListWidget(R.AnswerWidget):
    """左側選項、右側答案區；可拖放、雙擊或用按鈕移動。「只需重新排序」時只有一個清單。"""

    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        self.images = _images(dto)
        self.reorder_only = dto["reorderOnly"]
        self.texts = {c["id"]: c["text"] for c in dto["choices"]}
        self.order = [c["id"] for c in dto["choices"]]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        hint = (tr('拖曳或用 ▲▼ 把項目排成正確順序。') if self.reorder_only else
                tr('把需要的項目移到右側（拖曳、雙擊或按 ▶），再用 ▲▼ 排出順序。'))
        outer.addWidget(plain_label(hint, color=MUTED_COLOR, selectable=False))
        row = QHBoxLayout()
        self.source = self._make_list()
        self.target = self._make_list()
        if not self.reorder_only:
            left = QVBoxLayout()
            left.addWidget(plain_label(dto["choicesTitle"] or tr('選項'), bold=True, selectable=False))
            left.addWidget(self.source)
            row.addLayout(left, 1)
            middle = QVBoxLayout()
            middle.addStretch(1)
            self.add_button = self._button("▶", tr('移到答案區'), self.add_selected)
            self.remove_button = self._button("◀", tr('移回選項'), self.remove_selected)
            middle.addWidget(self.add_button)
            middle.addWidget(self.remove_button)
            middle.addStretch(1)
            row.addLayout(middle)
            self.source.itemActivated.connect(lambda _i: self.add_selected())
            self.target.itemActivated.connect(lambda _i: self.remove_selected())
        else:
            self.source.hide()
        right = QVBoxLayout()
        right.addWidget(plain_label(dto["answerTitle"] or tr('答案區'), bold=True, selectable=False))
        right.addWidget(self.target)
        row.addLayout(right, 1)
        order = QVBoxLayout()
        order.addStretch(1)
        order.addWidget(self._button("▲", tr('上移'), lambda: self.move_selected(-1)))
        order.addWidget(self._button("▼", tr('下移'), lambda: self.move_selected(1)))
        order.addStretch(1)
        row.addLayout(order)
        outer.addLayout(row)
        self.review = plain_label("", parent=self)
        self.review.setVisible(False)
        outer.addWidget(self.review)
        for widget in (self.source, self.target):
            model = widget.model()
            model.rowsInserted.connect(lambda *_: self._emit())
            model.rowsRemoved.connect(lambda *_: self._emit())
            model.rowsMoved.connect(lambda *_: self._emit())
        self.set_answers({})

    def _make_list(self) -> QListWidget:
        widget = QListWidget(self)
        widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove if self.reorder_only
                               else QAbstractItemView.DragDropMode.DragDrop)
        widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        widget.setWordWrap(True)
        widget.setIconSize(QSize(120, 80))
        widget.setMinimumHeight(160)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        return widget

    def _button(self, text: str, tip: str, slot) -> QToolButton:
        button = QToolButton(self)
        button.setText(text)
        button.setToolTip(tip)
        button.setAccessibleName(tip)
        button.clicked.connect(slot)
        return button

    def _item(self, choice_id: str) -> QListWidgetItem:
        text = self.texts[choice_id]
        item = QListWidgetItem(qt.strip_images(text, "").strip() or tr('（圖片）'))
        item.setData(Qt.ItemDataRole.UserRole, choice_id)
        item.setToolTip(qt.strip_images(text))
        refs = qt.image_refs(text)
        image = _qimage(self.images, refs[0]) if refs else None
        if image is not None:
            item.setIcon(QIcon(QPixmap.fromImage(image)))
        return item

    @staticmethod
    def _ids(widget: QListWidget) -> list[str]:
        return [widget.item(i).data(Qt.ItemDataRole.UserRole) for i in range(widget.count())]

    def answers(self) -> dict:
        sequence = self._ids(self.target)
        return {"sequence": sequence} if sequence else {}

    def _apply(self, answers: dict) -> None:
        sequence = [s for s in answers.get("sequence") or [] if s in self.texts]
        if self.reorder_only:
            sequence = sequence + [c for c in self.order if c not in sequence]
        self.source.clear()
        self.target.clear()
        for choice_id in sequence:
            self.target.addItem(self._item(choice_id))
        for choice_id in self.order:
            if choice_id not in sequence:
                self.source.addItem(self._item(choice_id))

    def add_selected(self) -> None:
        row = self.source.currentRow()
        if row < 0 or self._read_only:
            return
        item = self.source.takeItem(row)
        self.target.addItem(item)
        self.target.setCurrentItem(item)

    def remove_selected(self) -> None:
        row = self.target.currentRow()
        if row < 0 or self._read_only or self.reorder_only:
            return
        choice_id = self.target.takeItem(row).data(Qt.ItemDataRole.UserRole)
        self.source.clear()
        sequence = self._ids(self.target)
        for cid in self.order:
            if cid not in sequence:
                self.source.addItem(self._item(cid))
        self.source.setCurrentRow(next((i for i in range(self.source.count())
                                        if self.source.item(i).data(Qt.ItemDataRole.UserRole) == choice_id), -1))

    def move_selected(self, delta: int) -> None:
        row = self.target.currentRow()
        new = row + delta
        if row < 0 or not 0 <= new < self.target.count() or self._read_only:
            return
        item = self.target.takeItem(row)
        self.target.insertItem(new, item)
        self.target.setCurrentRow(new)

    def set_read_only(self, read_only: bool) -> None:
        super().set_read_only(read_only)
        mode = QAbstractItemView.DragDropMode.NoDragDrop if read_only else (
            QAbstractItemView.DragDropMode.InternalMove if self.reorder_only else QAbstractItemView.DragDropMode.DragDrop)
        for widget in (self.source, self.target):
            widget.setDragDropMode(mode)

    def show_review(self, question: dict | None, result: dict | None) -> None:
        row = (result or {}).get("items", [None])[0] if result else None
        verdict, color = _verdict(row)
        key = (question or {}).get("correctAnswer") or []
        texts = {c["id"]: qt.strip_images(c["text"]) for c in (question or {}).get("choices", [])}
        order_note = "" if (question or {}).get("orderMatters", True) else tr('（順序不計分）')
        _set_review(self.review, tr('{0}\u3000正確答案{1}：{2}', verdict, order_note, ' → '.join((texts.get(k, k) for k in key))), color)


# ---------------------------------------------------------------- 拖放題
class SourceTile(QFrame):
    """可拖曳的值。"""

    def __init__(self, source: dict, images: dict[str, dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.source_id = source["id"]
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setObjectName("sourceTile")
        self.setStyleSheet(f"#sourceTile {{ border: 1px solid {COLORS['tile_border']}; border-radius: 6px; "
                           f"background: {COLORS['surface']}; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        R.add_rich(layout, source["text"], images, self, selectable=False, zoomable=False, max_image_width=200)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip(tr('拖到右側的空格；或點右側空格選擇'))
        self.setAccessibleName(qt.strip_images(source["text"]))
        self._press = None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press is None or not self.isEnabled():
            return
        if (event.position().toPoint() - self._press).manhattanLength() < 6:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(SOURCE_MIME, QByteArray(self.source_id.encode("utf-8")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        self._press = None
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)


class DropSlot(QFrame):
    """答案區的空格：可接受拖放，點擊時跳出選單選值。"""

    valueChanged = Signal()

    def __init__(self, owner: "DragDropWidget", target_id: str, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.owner = owner
        self.target_id = target_id
        self.value: str | None = None
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(tr('空格：{0}', label))
        self.setObjectName("dropSlot")
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(6, 4, 4, 4)
        self.content = QWidget(self)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.layout_.addWidget(self.content, 1)
        self.clear_button = QToolButton(self)
        self.clear_button.setText("✕")
        self.clear_button.setToolTip(tr('清除此空格'))
        self.clear_button.setAutoRaise(True)
        self.clear_button.clicked.connect(lambda: self.set_value(None))
        self.layout_.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignTop)
        self._refresh()

    def set_value(self, source_id: str | None, notify: bool = True) -> None:
        self.value = source_id
        self._refresh()
        if notify:
            self.valueChanged.emit()

    def _refresh(self) -> None:
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        if self.value is None:
            self.content_layout.addWidget(plain_label(tr('（拖放到這裡，或點一下選擇）'), color=MUTED_COLOR,
                                                      selectable=False, parent=self.content))
            style = "dashed"
        else:
            R.add_rich(self.content_layout, self.owner.texts[self.value], self.owner.images, self.content,
                       selectable=False, zoomable=False, max_image_width=200)
            style = "solid"
        self.setStyleSheet(f"#dropSlot {{ border: 1px {style} {COLORS['tile_border']}; border-radius: 6px; }}")
        self.clear_button.setVisible(self.value is not None and not self.owner._read_only)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(SOURCE_MIME) and not self.owner._read_only:
            event.acceptProposedAction()

    def dropEvent(self, event):  # noqa: N802
        source_id = event.mimeData().data(SOURCE_MIME).data().decode("utf-8")
        if source_id in self.owner.texts:
            self.owner.place(self.target_id, source_id)
            event.acceptProposedAction()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_menu()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.open_menu()
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            if not self.owner._read_only:
                self.set_value(None)
        else:
            super().keyPressEvent(event)

    def open_menu(self) -> None:
        if self.owner._read_only:
            return
        menu = QMenu(self)
        for source_id in self.owner.order:
            action = menu.addAction(qt.strip_images(self.owner.texts[source_id]).strip() or source_id)
            action.setEnabled(self.owner.available(source_id, self.target_id))
            action.triggered.connect(lambda _=False, s=source_id: self.owner.place(self.target_id, s))
        if self.value is not None:
            menu.addSeparator()
            menu.addAction(tr('清除')).triggered.connect(lambda: self.set_value(None))
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))


def _title_label(text: str, parent: QWidget) -> QLabel:
    """區塊標題：一律使用介面字型（不受程式碼字型影響）。"""
    label = plain_label(text, bold=True, selectable=False, parent=parent)
    font = QFont(QApplication.font())
    font.setBold(True)
    label.setFont(font)
    return label


class DragDropWidget(R.AnswerWidget):
    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        self.images = _images(dto)
        self.reuse = dto["reuseSources"]
        if dto.get("codeFont"):
            self.setFont(code_font(self.font()))  # 值、空格與前後文字都改用等寬字
        self.texts = {s["id"]: s["text"] for s in dto["sources"]}
        self.order = [s["id"] for s in dto["sources"]]
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        title = (dto.get("sourcesTitle") or "").strip() or tr('值')
        left.addWidget(_title_label(title, self))
        hint = tr('可以重複使用') if self.reuse else tr('每個值只能用一次')
        left.addWidget(plain_label(hint, color=MUTED_COLOR, selectable=False))
        self.tiles: dict[str, SourceTile] = {}
        for source in dto["sources"]:
            tile = SourceTile(source, self.images, self)
            self.tiles[source["id"]] = tile
            left.addWidget(tile)
        left.addStretch(1)
        outer.addLayout(left, 2)
        right = QGridLayout()
        # 空格前／後文字可多行：前文字除最後一行、後文字除第一行，各自成為獨立一行（例如固定不需作答的步驟）
        has_suffix = any((t.get("suffix") or "").split("\n")[0].strip() for t in dto["targets"])
        right.setColumnStretch(2 if has_suffix else 1, 1)  # 有空格後文字時，空格固定寬度、文字佔滿其餘空間
        right.addWidget(_title_label(tr('答案區'), self), 0, 0, 1, 3)
        self.slots: dict[str, DropSlot] = {}
        self.reviews: dict[str, QLabel] = {}
        line = 1

        def full_line(text: str) -> None:
            nonlocal line
            right.addWidget(plain_label(text, parent=self), line, 0, 1, 3)
            line += 1

        for index, target in enumerate(dto["targets"]):
            before = target["label"].split("\n")
            after = (target.get("suffix") or "").split("\n")
            for text in before[:-1]:
                full_line(text)
            inline = before[-1]
            label = plain_label(inline, parent=self)
            label.setMaximumWidth(280)
            label.setVisible(bool(inline.strip()))
            name = inline.strip() or after[0].strip() or tr('空格 {0}', index + 1)
            slot = DropSlot(self, target["id"], name, self)
            if has_suffix:
                slot.setMinimumWidth(220)
                slot.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            slot.valueChanged.connect(self._slot_changed)
            review = plain_label("", parent=self)
            review.setVisible(False)
            right.addWidget(label, line, 0, Qt.AlignmentFlag.AlignVCenter)
            right.addWidget(slot, line, 1)
            if after[0].strip():
                suffix = plain_label(after[0], parent=self)
                suffix.setObjectName(f"suffix:{target['id']}")
                right.addWidget(suffix, line, 2, Qt.AlignmentFlag.AlignVCenter)
            right.addWidget(review, line + 1, 1, 1, 2)
            line += 2
            for text in after[1:]:
                full_line(text)
            self.slots[target["id"]] = slot
            self.reviews[target["id"]] = review
        right.setRowStretch(line, 1)
        outer.addLayout(right, 3)

    def available(self, source_id: str, target_id: str) -> bool:
        if self.reuse:
            return True
        return all(slot.value != source_id for tid, slot in self.slots.items() if tid != target_id)

    def place(self, target_id: str, source_id: str) -> None:
        if self._read_only:
            return
        if not self.reuse:
            for tid, slot in self.slots.items():
                if tid != target_id and slot.value == source_id:
                    slot.set_value(None, notify=False)  # 不能重複使用時，改放到新空格
        self.slots[target_id].set_value(source_id)

    def _slot_changed(self) -> None:
        self._update_tiles()
        self._emit()

    def _update_tiles(self) -> None:
        used = {slot.value for slot in self.slots.values()}
        for source_id, tile in self.tiles.items():
            tile.setEnabled(self.reuse or source_id not in used)

    def answers(self) -> dict:
        return {tid: slot.value for tid, slot in self.slots.items() if slot.value is not None}

    def _apply(self, answers: dict) -> None:
        for tid, slot in self.slots.items():
            value = answers.get(tid)
            slot.set_value(value if value in self.texts else None, notify=False)
        self._update_tiles()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        for slot in self.slots.values():
            slot._refresh()
        for tile in self.tiles.values():
            tile.setEnabled(not read_only)

    def show_review(self, question: dict | None, result: dict | None) -> None:
        rows = {r["id"]: r for r in (result or {}).get("items", [])}
        texts = {s["id"]: qt.strip_images(s["text"]) for s in (question or {}).get("sources", [])}
        targets = {t["id"]: t for t in (question or {}).get("targets", [])}
        for tid, label in self.reviews.items():
            verdict, color = _verdict(rows.get(tid))
            target = targets.get(tid, {})
            text = tr('{0}\u3000正解：{1}', verdict, texts.get(target.get('correctAnswer'), ''))
            if target.get("explanation"):
                text += tr('\n解析：{0}', target['explanation'])
            _set_review(label, text, color)


# ---------------------------------------------------------------- 熱區題
class HotAreaWidget(R.AnswerWidget):
    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(plain_label(tr('點選圖片中正確的區域（可選多個；再點一次取消）。'), color=MUTED_COLOR,
                                     selectable=False))
        image = _qimage(_images(dto), dto.get("background"))
        self.canvas = HotAreaCanvas(image, [dict(a) for a in dto["areas"]], editable=False, parent=self)
        self.canvas.changed.connect(self._emit)
        layout.addWidget(self.canvas)
        self.review = plain_label("", parent=self)
        self.review.setVisible(False)
        layout.addWidget(self.review)

    def answers(self) -> dict:
        order = [a["id"] for a in self.canvas.areas]
        selected = [a for a in order if a in self.canvas.selected]
        return {"selected": selected} if selected else {}

    def _apply(self, answers: dict) -> None:
        ids = {a["id"] for a in self.canvas.areas}
        self.canvas.selected = [s for s in answers.get("selected") or [] if s in ids]
        self.canvas.update()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        self.canvas.read_only = read_only

    def show_review(self, question: dict | None, result: dict | None) -> None:
        row = (result or {}).get("items", [None])[0] if result else None
        self.canvas.correct = set((question or {}).get("correctAnswer") or [])
        self.canvas.review = True
        self.canvas.update()
        verdict, color = _verdict(row)
        _set_review(self.review, tr('{0}\u3000綠框為正確區域，紅框為選錯的區域。', verdict), color)


R.RENDERERS.update({"build_list": BuildListWidget, "drag_drop": DragDropWidget, "hot_area": HotAreaWidget})


# ---------------------------------------------------------------- 案例研究
class CaseStudyDialog(QDialog):
    def __init__(self, case: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr('案例研究：{0}', case.get('name', '')))
        self.resize(820, 640)
        layout = QVBoxLayout(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.addWidget(plain_label(case.get("name", ""), bold=True, point_delta=2, parent=body))
        R.add_rich(body_layout, case.get("text", ""), {i["id"]: i for i in case.get("images", [])}, body)
        body_layout.addStretch(1)
        area.setWidget(body)
        layout.addWidget(area)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def case_button(case: dict | None, parent: QWidget) -> QPushButton:
    button = QPushButton(tr('案例研究…'), parent)
    button.setToolTip(tr('開啟此題的案例研究內容'))
    button.setVisible(case is not None)
    if case is not None:
        button.clicked.connect(lambda: CaseStudyDialog(case, parent).exec())
    return button
