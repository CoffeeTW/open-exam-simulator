"""排序題、拖放題、熱區題的編輯器。"""
from __future__ import annotations

from ..i18n import tr

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from ..core import question_types as qt
from . import editors as ED
from .hot_area_canvas import HotAreaCanvas
from .prompt_editor import OptionTextEdit, encode_image, load_image_file
from .renderers_extra import BuildListWidget
from .widgets import MUTED_COLOR, plain_label, tool_button


def _add_button(text: str, slot) -> QHBoxLayout:
    row = QHBoxLayout()
    button = QPushButton(text)
    button.clicked.connect(slot)
    row.addWidget(button)
    row.addStretch(1)
    return row


# ---------------------------------------------------------------- 排序題
class BuildListEditor(ED.BodyEditor):
    def build(self) -> None:
        q = self.q
        settings = QHBoxLayout()
        reorder = QCheckBox(tr('只需重新排序（全部項目都要排）'))
        reorder.setChecked(q["reorderOnly"])
        reorder.toggled.connect(self._reorder_toggled)
        settings.addWidget(reorder)
        order = QCheckBox(tr('順序必須正確'))
        order.setChecked(q["orderMatters"])
        order.setToolTip(tr('取消勾選時，只要挑對項目就算正確，不看順序'))
        order.toggled.connect(lambda v: self._set("orderMatters", v))
        settings.addWidget(order)
        settings.addStretch(1)
        self.root.addLayout(settings)
        titles = QHBoxLayout()
        titles.addWidget(QLabel(tr('選項標題：')))
        titles.addWidget(ED._line_edit(q["choicesTitle"], lambda t: self._set("choicesTitle", t)), 1)
        titles.addWidget(QLabel(tr('答案區標題：')))
        titles.addWidget(ED._line_edit(q["answerTitle"], lambda t: self._set("answerTitle", t)), 1)
        self.root.addLayout(titles)

        self.root.addWidget(plain_label(tr('選項（考生看到的初始順序）：'), selectable=False))
        count = len(q["choices"])
        for index, choice in enumerate(q["choices"]):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{index + 1}."))
            text = OptionTextEdit(choice["text"], self.pool, tr('選項文字（可貼上圖片）'))
            text.changed.connect(lambda t, c=choice: self._choice_text(c, t))
            row.addWidget(text, 1)
            row.addLayout(ED._row_buttons(lambda _=False, i=index: self._move(i, -1),
                                          lambda _=False, i=index: self._move(i, 1),
                                          lambda _=False, c=choice: self._delete(c),
                                          index > 0, index < count - 1, count > 2, tr('選項')))
            self.root.addLayout(row)
        self.root.addLayout(_add_button(tr('＋ 新增選項'), self._add))

        key_box = QGroupBox(tr('正確答案：把正確項目依序放到答案區'))
        self.key_layout = QVBoxLayout(key_box)
        self.root.addWidget(key_box)
        self._build_key()

    def _build_key(self) -> None:
        ED._clear_layout(self.key_layout)
        dto = {"choices": [dict(c) for c in self.q["choices"]], "reorderOnly": self.q["reorderOnly"],
               "choicesTitle": tr('可用項目'), "answerTitle": tr('正確順序'),
               "images": self.pool.collect(qt.question_image_refs(self.q)), "id": self.q["id"]}
        self.key_widget = BuildListWidget(dto)
        self.key_widget.set_answers({"sequence": self.q.get("correctAnswer") or []})
        self.key_widget.answersChanged.connect(self._key_changed)
        self.key_layout.addWidget(self.key_widget)
        if self.q["reorderOnly"]:
            confirm = QPushButton(tr('以目前順序作為正解'))
            confirm.clicked.connect(self._key_changed)
            self.key_layout.addLayout(_row(confirm))

    def _set(self, key: str, value) -> None:
        self.q[key] = value
        self.changed.emit()

    def _reorder_toggled(self, value: bool) -> None:
        self.q["reorderOnly"] = value
        if self.q.get("correctAnswer") is not None:
            self.q["correctAnswer"] = None
            if self.q["status"] == "ready":
                self.q["status"] = "draft"
                self.statusChanged.emit()
            self.message.emit(tr('已切換排序方式，請重新設定正確答案。'))
        self.structural()

    def _key_changed(self) -> None:
        self.q["correctAnswer"] = self.key_widget.answers().get("sequence") or None
        self.changed.emit()

    def _choice_text(self, choice: dict, text: str) -> None:
        choice["text"] = text
        self.changed.emit()
        self._build_key()

    def _move(self, index: int, delta: int) -> None:
        qt.move(self.q["choices"], index, delta)
        self.structural()

    def _add(self) -> None:
        new_id = qt.next_id([c["id"] for c in self.q["choices"]], "c")
        self.q["choices"].append({"id": new_id, "text": tr('步驟 {0}', len(self.q['choices']) + 1)})
        if self.q["reorderOnly"] and self.q.get("correctAnswer"):
            self.q["correctAnswer"] = None
            self.q["status"] = "draft"
            self.statusChanged.emit()
            self.message.emit(tr('新增了選項，「只需重新排序」的正解需要重新設定。'))
        self.structural()

    def _delete(self, choice: dict) -> None:
        if qt.remove_option(self.q, choice["id"]):
            self.statusChanged.emit()
            self.message.emit(tr('刪除的選項屬於正解，正解已更新且題目回到草稿，請重新確認。'))
        self.structural()


def _row(widget: QWidget) -> QHBoxLayout:
    row = QHBoxLayout()
    row.addWidget(widget)
    row.addStretch(1)
    return row


# ---------------------------------------------------------------- 拖放題
class DragDropEditor(ED.BodyEditor):
    def build(self) -> None:
        q = self.q
        reuse = QCheckBox(tr('值可以重複使用（同一個值可放進多個空格）'))
        reuse.setChecked(q["reuseSources"])
        reuse.toggled.connect(self._reuse_toggled)
        self.root.addLayout(_row(reuse))
        code = QCheckBox(tr('使用程式碼字型（等寬字，適合指令與程式碼）'))
        code.setChecked(bool(q.get("codeFont")))
        code.toggled.connect(lambda v: self._set_optional("codeFont", v, False))
        self.root.addLayout(_row(code))
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel(tr('左側標題：')))
        title_row.addWidget(ED._line_edit(q.get("sourcesTitle", ""), lambda t: self._set_optional("sourcesTitle", t, ""),
                                          tr('預設為「值」；例如 Cmdlets')), 1)
        self.root.addLayout(title_row)

        self.root.addWidget(plain_label(tr('值（考生拖曳的項目）：'), selectable=False))
        count = len(q["sources"])
        for index, source in enumerate(q["sources"]):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{index + 1}."))
            text = OptionTextEdit(source["text"], self.pool, tr('值的文字（可貼上圖片）'))
            text.changed.connect(lambda t, s=source, i=index: self._source_text(s, i, t))
            row.addWidget(text, 1)
            row.addLayout(ED._row_buttons(lambda _=False, i=index: self._move("sources", i, -1),
                                          lambda _=False, i=index: self._move("sources", i, 1),
                                          lambda _=False, s=source: self._delete_source(s),
                                          index > 0, index < count - 1, count > 1, tr('值')))
            self.root.addLayout(row)
        self.root.addLayout(_add_button(tr('＋ 新增值'), self._add_source))

        self.root.addWidget(plain_label(tr('答案區的空格：'), selectable=False))
        self.key_combos: list[QComboBox] = []
        targets = q["targets"]
        for index, target in enumerate(targets):
            box = QGroupBox(tr('空格 {0}（ID：{1}）', index + 1, target['id']))
            layout = QVBoxLayout(box)
            head = QHBoxLayout()
            head.addStretch(1)
            head.addLayout(ED._row_buttons(lambda _=False, i=index: self._move("targets", i, -1),
                                           lambda _=False, i=index: self._move("targets", i, 1),
                                           lambda _=False, i=index: self._delete_target(i),
                                           index > 0, index < len(targets) - 1, len(targets) > 1, tr('空格')))
            layout.addLayout(head)
            layout.addWidget(ED.AroundText(target["label"], target.get("suffix", ""),
                                           lambda label, suffix, tg=target: self._target_around(tg, label, suffix),
                                           tr('空格'), tr('同一行、空格左邊；例如 Step 1：；可留白'),
                                           tr("同一行、空格右邊；例如 -Name 'Group1' -GroupScope Global")))
            key_row = QHBoxLayout()
            key_row.addWidget(QLabel(tr('正確答案：')))
            combo = QComboBox()
            combo.addItem(tr('（尚未設定）'))
            ids = [s["id"] for s in q["sources"]]
            for source in q["sources"]:
                combo.addItem(qt.strip_images(source["text"]).strip() or tr('（圖片）'))
            combo.setCurrentIndex(ids.index(target["correctAnswer"]) + 1 if target["correctAnswer"] in ids else 0)
            combo.currentIndexChanged.connect(lambda i, tg=target: self._key(tg, i))
            self.key_combos.append(combo)
            key_row.addWidget(combo, 1)
            layout.addLayout(key_row)
            explanation = QHBoxLayout()
            explanation.addWidget(QLabel(tr('此空格解析：')))
            explanation.addWidget(ED._line_edit(target.get("explanation", ""),
                                                lambda t, tg=target: self._target_set(tg, "explanation", t), tr('選填')), 1)
            layout.addLayout(explanation)
            self.root.addWidget(box)
        self.root.addLayout(_add_button(tr('＋ 新增空格'), self._add_target))

    def _set_optional(self, key: str, value, default) -> None:
        """選填欄位：等於預設值時移除，讓舊格式的題目保持不變。"""
        if value == default:
            self.q.pop(key, None)
        else:
            self.q[key] = value
        self.changed.emit()

    def _target_around(self, target: dict, label: str, suffix: str) -> None:
        target["label"] = label
        if suffix:
            target["suffix"] = suffix
        else:
            target.pop("suffix", None)
        self.changed.emit()

    def _reuse_toggled(self, value: bool) -> None:
        self.q["reuseSources"] = value
        self.changed.emit()

    def _source_text(self, source: dict, index: int, text: str) -> None:
        source["text"] = text
        for combo in self.key_combos:
            combo.setItemText(index + 1, qt.strip_images(text).strip() or tr('（圖片）'))
        self.changed.emit()

    def _key(self, target: dict, index: int) -> None:
        target["correctAnswer"] = self.q["sources"][index - 1]["id"] if index > 0 else None
        self.changed.emit()

    def _target_set(self, target: dict, key: str, value: str) -> None:
        target[key] = value
        self.changed.emit()

    def _move(self, field: str, index: int, delta: int) -> None:
        qt.move(self.q[field], index, delta)
        self.structural()

    def _add_source(self) -> None:
        new_id = qt.next_id([s["id"] for s in self.q["sources"]], "v")
        self.q["sources"].append({"id": new_id, "text": tr('值 {0}', len(self.q['sources']) + 1)})
        self.structural()

    def _delete_source(self, source: dict) -> None:
        if qt.remove_option(self.q, source["id"]):
            self.statusChanged.emit()
            self.message.emit(tr('刪除的值是某些空格的正解，這些空格的正解改為未設定，題目回到草稿。'))
        self.structural()

    def _add_target(self) -> None:
        new_id = qt.next_id([t["id"] for t in self.q["targets"]], "t")
        self.q["targets"].append({"id": new_id, "label": tr('空格 {0}', len(self.q['targets']) + 1),
                                  "correctAnswer": None, "explanation": ""})
        self.structural()

    def _delete_target(self, index: int) -> None:
        del self.q["targets"][index]
        self.structural()


# ---------------------------------------------------------------- 熱區題
class HotAreaEditor(ED.BodyEditor):
    def build(self) -> None:
        q = self.q
        self.root.addWidget(plain_label(
            tr('背景圖片：點一下圖片區後貼上（Ctrl+V），或把圖片檔拖進來；再次貼上會更換背景。\n建立區域：在圖片上拖曳畫出方框。拖曳方框可移動，拖曳右下角可調整大小，選取後按 Delete 刪除。'),
            color=MUTED_COLOR, selectable=False))
        image = self.pool.qimage(q["background"]) if q.get("background") else None
        self.canvas = HotAreaCanvas(image, q["areas"], editable=True, parent=self)
        self.canvas.correct = set(q.get("correctAnswer") or [])
        self.canvas.areasChanged.connect(self._areas_changed)
        self.canvas.deleteRequested.connect(self._delete)
        self.canvas.imageProvided.connect(self._set_background_image)
        self.canvas.fileProvided.connect(self._set_background_file)
        self.canvas.currentChanged.connect(lambda _id: self._refresh_list())
        self.root.addWidget(self.canvas)
        box = QGroupBox(tr('區域與正確答案（勾選正確的區域，可多選）'))
        self.list_layout = QVBoxLayout(box)
        self.root.addWidget(box)
        self._refresh_list()

    def _refresh_list(self) -> None:
        ED._clear_layout(self.list_layout)
        if not self.q["areas"]:
            self.list_layout.addWidget(plain_label(tr('尚未建立區域。'), color=MUTED_COLOR, selectable=False))
            return
        key = set(self.q.get("correctAnswer") or [])
        for index, area in enumerate(self.q["areas"]):
            row = QHBoxLayout()
            name = QPushButton(tr('區域 {0}', index + 1))
            name.setFlat(True)
            name.setToolTip(tr('在圖片上標示此區域'))
            name.clicked.connect(lambda _=False, a=area["id"]: self.canvas.set_current(a))
            if area["id"] == self.canvas.current:
                name.setStyleSheet("font-weight: bold;")
            row.addWidget(name)
            row.addWidget(plain_label(f"x {area['x']}, y {area['y']}, {area['w']}×{area['h']}", color=MUTED_COLOR,
                                      wrap=False, selectable=False))
            correct = QCheckBox(tr('正確答案'))
            correct.setChecked(area["id"] in key)
            correct.toggled.connect(lambda v, a=area["id"]: self._toggle_key(a, v))
            row.addWidget(correct)
            row.addStretch(1)
            delete = tool_button("✕", tr('刪除區域'))
            delete.clicked.connect(lambda _=False, a=area["id"]: self._delete(a))
            row.addWidget(delete)
            self.list_layout.addLayout(row)

    def _areas_changed(self) -> None:
        self._refresh_list()
        self.changed.emit()

    def _toggle_key(self, area_id: str, checked: bool) -> None:
        key = [a["id"] for a in self.q["areas"]
               if (a["id"] in (self.q.get("correctAnswer") or []) and a["id"] != area_id) or (a["id"] == area_id and checked)]
        self.q["correctAnswer"] = key or None
        self.canvas.correct = set(key)
        self.canvas.update()
        self.changed.emit()

    def _delete(self, area_id: str) -> None:
        if qt.remove_option(self.q, area_id):
            self.statusChanged.emit()
            self.message.emit(tr('刪除的區域是正解之一，正解已更新且題目回到草稿。'))
        self.canvas.areas = self.q["areas"]
        self.canvas.correct = set(self.q.get("correctAnswer") or [])
        self.canvas.set_current(None)
        self._refresh_list()
        self.changed.emit()

    def set_background(self, mime: str, data: str) -> None:
        if self.q.get("background") and self.q["areas"]:
            answer = QMessageBox.question(self, tr('更換背景圖片'), tr('要更換背景圖片嗎？已建立的區域會保留。'))
            if answer != QMessageBox.StandardButton.Yes:
                return
        image_id = self.pool.add(mime, data)
        self.q["background"] = image_id
        self.canvas.set_image(self.pool.qimage(image_id))
        self.changed.emit()

    def _set_background_image(self, image: QImage) -> None:
        self.set_background(*encode_image(image))

    def _set_background_file(self, path: str) -> None:
        try:
            self.set_background(*load_image_file(Path(path)))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, tr('無法使用這張圖片'), str(exc))


ED.BODY_EDITORS.update({"build_list": BuildListEditor, "drag_drop": DragDropEditor, "hot_area": HotAreaEditor})
