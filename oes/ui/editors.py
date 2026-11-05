"""題目編輯器。

QuestionEditor 直接修改傳入的題目 dict：文字修改只更新資料，不重建畫面（保留游標）；
新增、刪除、重排等結構變更會更新資料後重建該區塊。每次修改都會發出 changed。
ID 只在新增時產生，修改文字或重排都不會改變 ID。
"""
from __future__ import annotations

from ..i18n import tr

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                               QRadioButton, QVBoxLayout, QWidget)

from ..core import question_types as qt
from .prompt_editor import ImagePool, OptionTextEdit, PromptEditor
from .widgets import BAD_COLOR, MUTED_COLOR, plain_label, tool_button


def _plain_edit(text: str, lines: int, on_change: Callable[[str], None], placeholder: str = "") -> QPlainTextEdit:
    edit = QPlainTextEdit()
    edit.setPlainText(text)
    edit.setTabChangesFocus(True)
    edit.setPlaceholderText(placeholder)
    edit.setFixedHeight(edit.fontMetrics().lineSpacing() * lines + 16)
    edit.textChanged.connect(lambda: on_change(edit.toPlainText()))
    return edit


def _line_edit(text: str, on_change: Callable[[str], None], placeholder: str = "") -> QLineEdit:
    edit = QLineEdit(text)
    edit.setPlaceholderText(placeholder)
    edit.textEdited.connect(on_change)
    return edit


def _clear_layout(layout) -> None:
    while layout.count():
        child = layout.takeAt(0)
        if child.widget() is not None:
            child.widget().hide()
            child.widget().deleteLater()
        elif child.layout() is not None:
            _clear_layout(child.layout())


def _row_buttons(on_up, on_down, on_delete, can_up: bool, can_down: bool, can_delete: bool,
                 what: str) -> QHBoxLayout:
    box = QHBoxLayout()
    box.setSpacing(0)
    for text, tip, slot, enabled in (("↑", tr('上移{0}', what), on_up, can_up), ("↓", tr('下移{0}', what), on_down, can_down),
                                     ("✕", tr('刪除{0}', what), on_delete, can_delete)):
        button = tool_button(text, tip)
        button.setEnabled(enabled)
        button.clicked.connect(slot)
        box.addWidget(button)
    return box


def split_around(label: str, suffix: str) -> tuple[str, str, str, str]:
    """把儲存格式的 label／suffix 拆成（上方文字行, 前文字, 後文字, 下方文字行）。"""
    before = (label or "").split("\n")
    after = (suffix or "").split("\n")
    return "\n".join(before[:-1]), before[-1], after[0], "\n".join(after[1:])


def join_around(above: str, before: str, after: str, below: str) -> tuple[str, str]:
    """與 split_around 相反：組回 label 與 suffix。"""
    label = f"{above}\n{before}" if above else before
    suffix = f"{after}\n{below}" if below else after
    return label, suffix


class AroundText(QWidget):
    """作答欄位（空格或下拉選單）周圍的文字：上方文字行、前文字、後文字、下方文字行。

    資料仍存成 label（上方各行＋前文字）與 suffix（後文字＋下方各行），作答畫面依此排版。
    """

    def __init__(self, label: str, suffix: str, on_change: Callable[[str, str], None], what: str,
                 before_hint: str, after_hint: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.on_change = on_change
        above, before, after, below = split_around(label, suffix)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.above = _plain_edit(above, 2, lambda _t: self._changed(),
                                 tr('選填；每一行各自顯示在{0}上方（例如沒有作答的固定步驟或程式碼）', what))
        self.before = _line_edit(before, lambda _t: self._changed(), before_hint)
        self.after = _line_edit(after, lambda _t: self._changed(), after_hint)
        self.below = _plain_edit(below, 2, lambda _t: self._changed(),
                                 tr('選填；每一行各自顯示在{0}下方（例如沒有作答的固定步驟或程式碼）', what))
        form.addRow(tr('上方文字行：'), self.above)
        form.addRow(tr('{0}前文字：', what), self.before)
        form.addRow(tr('{0}後文字：', what), self.after)
        form.addRow(tr('下方文字行：'), self.below)

    def values(self) -> tuple[str, str]:
        return join_around(self.above.toPlainText(), self.before.text(), self.after.text(), self.below.toPlainText())

    def _changed(self) -> None:
        self.on_change(*self.values())


class BodyEditor(QWidget):
    changed = Signal()
    statusChanged = Signal()  # 編輯動作讓題目回到草稿時通知外框更新狀態
    message = Signal(str)

    def __init__(self, question: dict, parent: QWidget | None = None, pool: ImagePool | None = None):
        super().__init__(parent)
        self.q = question
        self.pool = pool or ImagePool(question.get("images"))
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.rebuild()

    def rebuild(self) -> None:
        _clear_layout(self.root)
        self.build()

    def build(self) -> None:
        raise NotImplementedError

    def structural(self) -> None:
        self.rebuild()
        self.changed.emit()


# ---------------------------------------------------------------- 選擇題
class MultipleChoiceEditor(BodyEditor):
    def build(self) -> None:
        q = self.q
        settings = QHBoxLayout()
        settings.addWidget(QLabel(tr('作答方式：')))
        mode = QComboBox()
        mode.addItems([tr('單選（一個答案）'), tr('複選（多個答案）')])
        mode.setCurrentIndex(1 if q["selectMode"] == "multiple" else 0)
        mode.currentIndexChanged.connect(self._mode_changed)
        settings.addWidget(mode)
        shuffle = QCheckBox(tr('作答時隨機排列選項'))
        shuffle.setChecked(q["shuffle"])
        shuffle.toggled.connect(lambda v: self._set("shuffle", v))
        settings.addWidget(shuffle)
        limit = QCheckBox(tr('限制選取數量為正解數'))
        limit.setChecked(q["checkNumberSelected"])
        limit.setEnabled(q["selectMode"] == "multiple")
        limit.toggled.connect(lambda v: self._set("checkNumberSelected", v))
        settings.addWidget(limit)
        settings.addStretch(1)
        self.root.addLayout(settings)

        self.root.addWidget(plain_label(tr('勾選左側方框設定正確答案。'), color=MUTED_COLOR, selectable=False))
        key = set(q.get("correctAnswer") or [])
        self.key_group = QButtonGroup(self)
        self.key_group.setExclusive(q["selectMode"] == "single")
        self.key_buttons: dict[str, object] = {}
        count = len(q["options"])
        for index, option in enumerate(q["options"]):
            row = QHBoxLayout()
            marker = QCheckBox() if q["selectMode"] == "multiple" else QRadioButton()
            marker.setToolTip(tr('設為正確答案'))
            marker.setAccessibleName(tr('選項 {0} 為正確答案', chr(65 + index) if index < 26 else index + 1))
            marker.setChecked(option["id"] in key)
            self.key_group.addButton(marker)
            self.key_buttons[option["id"]] = marker
            marker.toggled.connect(self._key_changed)
            row.addWidget(marker, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(QLabel(f"{chr(65 + index) if index < 26 else index + 1}."), 0, Qt.AlignmentFlag.AlignTop)
            text = OptionTextEdit(option["text"], self.pool, tr('選項文字（可貼上圖片）'))
            text.changed.connect(lambda t, o=option: self._option_text(o, t))
            row.addWidget(text, 1)
            row.addLayout(_row_buttons(lambda _=False, i=index: self._move(i, -1),
                                       lambda _=False, i=index: self._move(i, 1),
                                       lambda _=False, o=option: self._delete(o),
                                       index > 0, index < count - 1, count > 2, tr('選項')))
            self.root.addLayout(row)
        buttons = QHBoxLayout()
        add = QPushButton(tr('＋ 新增選項'))
        add.clicked.connect(self._add)
        buttons.addWidget(add)
        clear = QPushButton(tr('清除正解'))
        clear.clicked.connect(self._clear_key)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        self.root.addLayout(buttons)

    def _set(self, key: str, value) -> None:
        self.q[key] = value
        self.changed.emit()

    def _mode_changed(self, index: int) -> None:
        before = self.q["status"]
        qt.set_select_mode(self.q, "multiple" if index == 1 else "single")
        if before != self.q["status"]:
            self.statusChanged.emit()
            self.message.emit(tr('改為單選時只保留第一個正解，題目已回到草稿。'))
        self.structural()

    def _key_changed(self, _checked: bool) -> None:
        chosen = [o["id"] for o in self.q["options"]
                  if o["id"] in self.key_buttons and self.key_buttons[o["id"]].isChecked()]
        self.q["correctAnswer"] = chosen or None
        self.changed.emit()

    def _clear_key(self) -> None:
        self.q["correctAnswer"] = None
        self.structural()

    def _option_text(self, option: dict, text: str) -> None:
        option["text"] = text
        self.changed.emit()

    def _move(self, index: int, delta: int) -> None:
        qt.move(self.q["options"], index, delta)
        self.structural()

    def _add(self) -> None:
        new_id = qt.next_id([o["id"] for o in self.q["options"]], "o")
        self.q["options"].append({"id": new_id, "text": tr('選項 {0}', len(self.q['options']) + 1)})
        self.structural()

    def _delete(self, option: dict) -> None:
        if qt.remove_option(self.q, option["id"]):
            self.statusChanged.emit()
            self.message.emit(tr('已刪除正解選項，正解已更新且題目回到草稿，請重新確認。'))
        self.structural()


# ---------------------------------------------------------------- 填空題
class FillInBlankEditor(BodyEditor):
    def build(self) -> None:
        q = self.q
        flags = QHBoxLayout()
        for key, text in (("caseSensitive", tr('區分大小寫')), ("ignoreMultipleSpaces", tr('多個空白視為一個')),
                          ("trimResponse", tr('忽略前後空白'))):
            box = QCheckBox(text)
            box.setChecked(q[key])
            box.toggled.connect(lambda v, k=key: self._set(k, v))
            flags.addWidget(box)
        flags.addStretch(1)
        self.root.addLayout(flags)
        self.root.addWidget(plain_label(tr('可接受答案（符合任一個即正確）：'), selectable=False))
        for index, text in enumerate(q["acceptedAnswers"]):
            row = QHBoxLayout()
            row.addWidget(_line_edit(text, lambda t, i=index: self._edit(i, t), tr('答案文字')), 1)
            delete = tool_button("✕", tr('刪除此答案'))
            delete.clicked.connect(lambda _=False, i=index: self._delete(i))
            row.addWidget(delete)
            self.root.addLayout(row)
        add = QPushButton(tr('＋ 新增可接受答案'))
        add.clicked.connect(self._add)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addStretch(1)
        self.root.addLayout(row)

    def _set(self, key: str, value) -> None:
        self.q[key] = value
        self.changed.emit()

    def _edit(self, index: int, text: str) -> None:
        self.q["acceptedAnswers"][index] = text
        self.changed.emit()

    def _add(self) -> None:
        self.q["acceptedAnswers"].append("")
        self.structural()

    def _delete(self, index: int) -> None:
        del self.q["acceptedAnswers"][index]
        self.structural()


# ---------------------------------------------------------------- 多欄位下拉
class DropdownEditor(BodyEditor):
    def build(self) -> None:
        items = self.q["items"]
        code = QCheckBox(tr('使用程式碼字型（等寬字，適合指令與程式碼）'))
        code.setChecked(bool(self.q.get("codeFont")))
        code.toggled.connect(self._code_font)
        row = QHBoxLayout()
        row.addWidget(code)
        row.addStretch(1)
        self.root.addLayout(row)
        for index, item in enumerate(items):
            self.root.addWidget(self._item_box(index, item, len(items)))
        add = QPushButton(tr('＋ 新增作答欄位'))
        add.clicked.connect(self._add_item)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addStretch(1)
        self.root.addLayout(row)

    def _item_box(self, index: int, item: dict, count: int) -> QGroupBox:
        box = QGroupBox(tr('作答欄位 {0}（ID：{1}）', index + 1, item['id']))
        layout = QVBoxLayout(box)
        head = QHBoxLayout()
        head.addStretch(1)
        head.addLayout(_row_buttons(lambda _=False: self._move_item(index, -1),
                                    lambda _=False: self._move_item(index, 1),
                                    lambda _=False: self._delete_item(index),
                                    index > 0, index < count - 1, count > 1, tr('欄位')))
        layout.addLayout(head)
        layout.addWidget(AroundText(item["label"], item.get("suffix", ""),
                                    lambda label, suffix: self._around(item, label, suffix), tr('下拉選單'),
                                    tr('同一行、選單左邊；例如 欄位 1：；可留白'), tr('同一行、選單右邊；選填')))
        key = QComboBox()
        key.addItem(tr('（尚未設定）'))
        key.addItems([o["text"] for o in item["options"]])
        ids = [o["id"] for o in item["options"]]
        key.setCurrentIndex(ids.index(item["correctAnswer"]) + 1 if item["correctAnswer"] in ids else 0)
        key.currentIndexChanged.connect(lambda i: self._key(item, i))
        key_row = QHBoxLayout()
        key_row.addWidget(QLabel(tr('正確答案：')))
        key_row.addWidget(key, 1)
        layout.addLayout(key_row)
        n = len(item["options"])
        for oi, option in enumerate(item["options"]):
            row = QHBoxLayout()
            row.addSpacing(16)
            row.addWidget(QLabel(tr('選項 {0}', oi + 1)))
            row.addWidget(_line_edit(option["text"], lambda t, o=option, i=oi, c=key: self._option_text(o, t, c, i),
                                     tr('選項文字')), 1)
            row.addLayout(_row_buttons(lambda _=False, i=oi: self._move_option(item, i, -1),
                                       lambda _=False, i=oi: self._move_option(item, i, 1),
                                       lambda _=False, o=option: self._delete_option(item, o),
                                       oi > 0, oi < n - 1, n > 2, tr('選項')))
            layout.addLayout(row)
        add = QPushButton(tr('＋ 新增選項'))
        add.clicked.connect(lambda: self._add_option(item))
        row = QHBoxLayout()
        row.addSpacing(16)
        row.addWidget(add)
        row.addStretch(1)
        layout.addLayout(row)
        explanation = QHBoxLayout()
        explanation.addWidget(QLabel(tr('此欄解析：')))
        explanation.addWidget(_line_edit(item.get("explanation", ""), lambda t: self._explain(item, t), tr('選填')), 1)
        layout.addLayout(explanation)
        return box

    def _around(self, item: dict, label: str, suffix: str) -> None:
        item["label"] = label
        if suffix:
            item["suffix"] = suffix
        else:
            item.pop("suffix", None)  # 未使用時不寫入，舊格式維持不變
        self.changed.emit()

    def _code_font(self, checked: bool) -> None:
        if checked:
            self.q["codeFont"] = True
        else:
            self.q.pop("codeFont", None)
        self.changed.emit()

    def _explain(self, item: dict, text: str) -> None:
        item["explanation"] = text
        self.changed.emit()

    def _key(self, item: dict, index: int) -> None:
        item["correctAnswer"] = item["options"][index - 1]["id"] if index > 0 else None
        self.changed.emit()

    def _option_text(self, option: dict, text: str, key_combo: QComboBox, index: int) -> None:
        option["text"] = text
        key_combo.setItemText(index + 1, text)
        self.changed.emit()

    def _move_item(self, index: int, delta: int) -> None:
        qt.move(self.q["items"], index, delta)
        self.structural()

    def _delete_item(self, index: int) -> None:
        del self.q["items"][index]
        self.structural()

    def _add_item(self) -> None:
        new_id = qt.next_id([i["id"] for i in self.q["items"]], "item")
        self.q["items"].append({"id": new_id, "label": tr('欄位 {0}', len(self.q['items']) + 1),
                                "options": [{"id": "o1", "text": tr('選項 1')}, {"id": "o2", "text": tr('選項 2')}],
                                "correctAnswer": None, "explanation": ""})
        self.structural()

    def _move_option(self, item: dict, index: int, delta: int) -> None:
        qt.move(item["options"], index, delta)
        self.structural()

    def _add_option(self, item: dict) -> None:
        new_id = qt.next_id([o["id"] for o in item["options"]], "o")
        item["options"].append({"id": new_id, "text": tr('選項 {0}', len(item['options']) + 1)})
        self.structural()

    def _delete_option(self, item: dict, option: dict) -> None:
        if qt.remove_option(self.q, option["id"], item["id"]):
            self.statusChanged.emit()
            self.message.emit(tr('已刪除「{0}」的正解選項，此欄正解改為未設定，題目回到草稿。', item['label']))
        self.structural()


# ---------------------------------------------------------------- Yes／No 判斷矩陣
class YesNoEditor(BodyEditor):
    KEYS = (None, True, False)

    def build(self) -> None:
        items = self.q["items"]
        for index, item in enumerate(items):
            frame = QGroupBox(tr('第 {0} 列（ID：{1}）', index + 1, item['id']))
            layout = QVBoxLayout(frame)
            head = QHBoxLayout()
            head.addWidget(QLabel(tr('正確答案：')))
            key = QComboBox()
            key.addItems([tr('（尚未設定）'), "Yes", "No"])
            key.setCurrentIndex(self.KEYS.index(item["correctAnswer"]) if item["correctAnswer"] in (True, False) else 0)
            key.currentIndexChanged.connect(lambda i, it=item: self._key(it, i))
            head.addWidget(key)
            head.addStretch(1)
            head.addLayout(_row_buttons(lambda _=False, i=index: self._move(i, -1),
                                        lambda _=False, i=index: self._move(i, 1),
                                        lambda _=False, i=index: self._delete(i),
                                        index > 0, index < len(items) - 1, len(items) > 1, tr('敘述')))
            layout.addLayout(head)
            layout.addWidget(_plain_edit(item["text"], 3, lambda t, it=item: self._text(it, t), tr('敘述內容')))
            explanation = QHBoxLayout()
            explanation.addWidget(QLabel(tr('此列解析：')))
            explanation.addWidget(_line_edit(item.get("explanation", ""), lambda t, it=item: self._explain(it, t),
                                             tr('選填')), 1)
            layout.addLayout(explanation)
            self.root.addWidget(frame)
        add = QPushButton(tr('＋ 新增敘述'))
        add.clicked.connect(self._add)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addStretch(1)
        self.root.addLayout(row)

    def _key(self, item: dict, index: int) -> None:
        item["correctAnswer"] = self.KEYS[index]  # Yes=True、No=False、未設定=None
        self.changed.emit()

    def _text(self, item: dict, text: str) -> None:
        item["text"] = text
        self.changed.emit()

    def _explain(self, item: dict, text: str) -> None:
        item["explanation"] = text
        self.changed.emit()

    def _move(self, index: int, delta: int) -> None:
        qt.move(self.q["items"], index, delta)
        self.structural()

    def _delete(self, index: int) -> None:
        del self.q["items"][index]
        self.structural()

    def _add(self) -> None:
        new_id = qt.next_id([i["id"] for i in self.q["items"]], "s")
        self.q["items"].append({"id": new_id, "text": tr('敘述 {0}', len(self.q['items']) + 1),
                                "correctAnswer": None, "explanation": ""})
        self.structural()


class GoalSolutionEditor(BodyEditor):
    """解決方案評估題：解決方案、Yes／No 正解、作答後無法返回。情境寫在上方的「題目」。"""
    KEYS = (None, True, False)

    def build(self) -> None:
        q = self.q
        tip = plain_label(tr('上方「題目」填寫情境與目標（系列題共用）。完成一題後，在題目清單按右鍵「複製題目」，'
                             '只要修改解決方案與正解，就能建立同系列的下一題。'), color=MUTED_COLOR, selectable=False)
        self.root.addWidget(tip)
        form = QFormLayout()
        self.solution = PromptEditor(q.get("solution", ""), self.pool, self,
                                     placeholder=tr('本題的解決方案；可使用的題目必須填寫'), minimum_height=110,
                                     height_key="solution")
        self.solution.changed.connect(self._solution)
        form.addRow(tr('解決方案：'), self.solution)
        key = QComboBox()
        key.addItems([tr('（尚未設定）'), tr('Yes（達成目標）'), tr('No（未達成目標）')])
        current = q.get("correctAnswer")
        key.setCurrentIndex(self.KEYS.index(current) if current in (True, False) else 0)
        key.currentIndexChanged.connect(self._key)
        row = QHBoxLayout()
        row.addWidget(key)
        row.addStretch(1)
        form.addRow(tr('正確答案：'), row)
        lock = QCheckBox(tr('作答後無法返回（正式考試時，離開本題就不能再回來修改）'))
        lock.setChecked(bool(q.get("noReturn")))
        lock.toggled.connect(self._no_return)
        form.addRow("", lock)
        self.root.addLayout(form)

    def _solution(self, text: str) -> None:
        self.q["solution"] = text
        self.changed.emit()

    def _key(self, index: int) -> None:
        self.q["correctAnswer"] = self.KEYS[index]
        self.changed.emit()

    def _no_return(self, checked: bool) -> None:
        self.q["noReturn"] = checked
        self.changed.emit()


BODY_EDITORS = {
    "goal_solution": GoalSolutionEditor,
    "multiple_choice": MultipleChoiceEditor,
    "fill_in_blank": FillInBlankEditor,
    "dropdown_multi": DropdownEditor,
    "yes_no_matrix": YesNoEditor,
}


# ---------------------------------------------------------------- 整題編輯器
class QuestionEditor(QWidget):
    changed = Signal()
    message = Signal(str)

    def __init__(self, entry: dict, sections: list[dict], parent: QWidget | None = None,
                 cases: list[dict] | None = None):
        super().__init__(parent)
        from . import editors_extra  # noqa: F401  註冊排序、拖放、熱區題編輯器
        self.entry = entry
        self.q = entry["question"]
        q = self.q
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        type_label = plain_label(tr('{0}\u3000\u3000題目 ID：{1}', tr(qt.get_type(q['type']).label), q['id']), color=MUTED_COLOR)
        form.addRow(tr('題型：'), type_label)

        meta = QHBoxLayout()
        self.status = QComboBox()
        self.status.addItems([tr(qt.STATUS_LABELS[s]) for s in qt.STATUSES])
        self.status.setCurrentIndex(qt.STATUSES.index(q["status"]) if q["status"] in qt.STATUSES else 0)
        self.status.currentIndexChanged.connect(lambda i: self._set("status", qt.STATUSES[i]))
        meta.addWidget(self.status)
        meta.addSpacing(12)
        meta.addWidget(QLabel(tr('章節：')))
        self.section = QComboBox()
        self.section.addItem(tr('（無）'))
        section_ids = [None] + [s["id"] for s in sections]
        for s in sections:
            self.section.addItem(s["name"])
        self.section.setCurrentIndex(section_ids.index(entry.get("sectionId")) if entry.get("sectionId") in section_ids else 0)
        self.section.currentIndexChanged.connect(lambda i: self._set_section(section_ids[i]))
        meta.addWidget(self.section)
        if cases:
            meta.addSpacing(12)
            meta.addWidget(QLabel(tr('案例研究：')))
            self.case = QComboBox()
            self.case.addItem(tr('（無）'))
            case_ids = [None] + [c["id"] for c in cases]
            for c in cases:
                self.case.addItem(c["name"])
            current = entry.get("caseStudyId")
            self.case.setCurrentIndex(case_ids.index(current) if current in case_ids else 0)
            self.case.currentIndexChanged.connect(lambda i: self._set_case(case_ids[i]))
            meta.addWidget(self.case)
        meta.addSpacing(12)
        meta.addWidget(QLabel(tr('評分：')))
        mode = QComboBox()
        mode.addItems([tr(qt.MODE_LABELS[m]) for m in qt.MODES])
        mode.setCurrentIndex(qt.MODES.index(q["scoring"]["mode"]) if q["scoring"].get("mode") in qt.MODES else 0)
        mode.setToolTip(tr('全對才得分：所有項目正確才取得整題配分。\n分項計分：答對項目數 ÷ 總項目數 × 配分。'))
        mode.currentIndexChanged.connect(lambda i: self._set_scoring("mode", qt.MODES[i]))
        meta.addWidget(mode)
        meta.addSpacing(12)
        meta.addWidget(QLabel(tr('配分：')))
        score = QDoubleSpinBox()
        score.setDecimals(2)
        score.setRange(0.01, qt.MAX_SCORE_LIMIT)
        score.setValue(float(q["scoring"].get("maxScore") or 1))
        score.valueChanged.connect(lambda v: self._set_scoring("maxScore", int(v) if float(v).is_integer() else v))
        meta.addWidget(score)
        meta.addStretch(1)
        form.addRow(tr('狀態：'), meta)
        self.pool = ImagePool(q.get("images"))
        self.prompt = PromptEditor(q.get("prompt", ""), self.pool)
        self.prompt.changed.connect(self._set_prompt)
        form.addRow(tr('題目：'), self.prompt)
        layout.addLayout(form)

        self.body = BODY_EDITORS[q["type"]](q, self, self.pool)
        self.body.changed.connect(self._sync_images)
        self.body.statusChanged.connect(self._sync_status)
        self.body.message.connect(self.message)
        group = QGroupBox(tr('作答設定與正解'))
        group_layout = QVBoxLayout(group)
        group_layout.addWidget(self.body)
        layout.addWidget(group)

        explanation = QFormLayout()
        explanation.addRow(tr('整題解析：'), _plain_edit(q.get("explanation", ""), 4, lambda t: self._set("explanation", t),
                                                    tr('選填；檢討時顯示')))
        layout.addLayout(explanation)
        self.errors = plain_label("", color=BAD_COLOR)
        layout.addWidget(self.errors)
        layout.addStretch(1)
        self.changed.connect(self.refresh_errors)
        self.refresh_errors()

    def _set(self, key: str, value) -> None:
        self.q[key] = value
        self.changed.emit()

    def _set_prompt(self, prompt: str) -> None:
        self.q["prompt"] = prompt
        self._sync_images()

    def _sync_images(self) -> None:
        """題目的 images 只保留題目內容與選項實際引用的圖片。"""
        images = self.pool.collect(qt.question_image_refs(self.q))
        if images:
            self.q["images"] = images
        else:
            self.q.pop("images", None)
        self.changed.emit()

    def _set_scoring(self, key: str, value) -> None:
        self.q["scoring"][key] = value
        self.changed.emit()

    def _set_case(self, case_id: str | None) -> None:
        if case_id is None:
            self.entry.pop("caseStudyId", None)
        else:
            self.entry["caseStudyId"] = case_id
        self.changed.emit()

    def _set_section(self, section_id: str | None) -> None:
        self.entry["sectionId"] = section_id
        self.changed.emit()

    def _sync_status(self) -> None:
        self.status.blockSignals(True)
        self.status.setCurrentIndex(qt.STATUSES.index(self.q["status"]))
        self.status.blockSignals(False)

    def refresh_errors(self) -> None:
        errors = qt.validate(self.q)
        if errors:
            text = tr('需要修正：\n') + qt.format_errors(errors)
        elif qt.validate(self.q, require_answer_key=True):
            text = tr('草稿：尚未設定完整正解，不會出現在考試中。')
        elif self.q.get("status") != "ready":
            text = tr('草稿：正解已完整。確認題目內容後，把狀態改為「可使用」才會出題。')
        else:
            text = ""
        self.errors.setText(text)
        self.errors.setStyleSheet(f"color: {BAD_COLOR if errors else MUTED_COLOR};")
        self.errors.setVisible(bool(text))
