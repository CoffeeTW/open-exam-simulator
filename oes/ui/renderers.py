"""題型作答元件。預覽、正式作答與檢討共用同一組元件，輸入資料為考生展示 DTO（不含正解）。

每個元件：
- answers() 回傳以項目 ID／選項 ID 表示的作答 dict（未作答的項目不出現）。
- set_answers() 還原作答，不觸發 answersChanged。
- show_review(question, result) 顯示對錯、正解與解析（需要作者題目與評分結果）。
"""
from __future__ import annotations

from ..i18n import tr

from typing import Any

from PySide6.QtCore import QByteArray, Qt, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QRadioButton, QSizePolicy, QVBoxLayout, QWidget)

from ..core import question_types as qt
from .widgets import BAD_COLOR, MUTED_COLOR, OK_COLOR, ClickableLabel, ImageView, RichLabel, code_font, plain_label

PLACEHOLDER = "請選擇答案"


def _letter(index: int) -> str:
    return chr(65 + index) if index < 26 else str(index + 1)


def _verdict(is_correct: bool) -> tuple[str, str]:
    return (tr('✔ 正確'), OK_COLOR) if is_correct else (tr('✘ 錯誤'), BAD_COLOR)


def _set_review_label(label: QLabel, text: str, color: str) -> None:
    label.setText(text)
    label.setStyleSheet(f"color: {color};")
    label.setVisible(bool(text))


def _rows_by_id(result: dict | None) -> dict[str, dict]:
    return {r["id"]: r for r in (result or {}).get("items", [])}


def _clear_group(group: QButtonGroup) -> None:
    exclusive = group.exclusive()
    group.setExclusive(False)
    for button in group.buttons():
        button.setChecked(False)
    group.setExclusive(exclusive)


class AnswerWidget(QWidget):
    answersChanged = Signal()

    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.dto = dto
        self._loading = False
        self._read_only = False

    def answers(self) -> dict:
        raise NotImplementedError

    def set_answers(self, answers: dict) -> None:
        self._loading = True
        try:
            self._apply(answers or {})
        finally:
            self._loading = False

    def _apply(self, answers: dict) -> None:
        raise NotImplementedError

    def clear(self) -> None:
        self.set_answers({})
        self.answersChanged.emit()

    def set_read_only(self, read_only: bool) -> None:
        self._read_only = read_only
        for widget in self.findChildren(QAbstractButton) + self.findChildren(QComboBox):
            widget.setEnabled(not read_only)
        for edit in self.findChildren(QLineEdit):
            edit.setReadOnly(read_only)

    def show_review(self, question: dict | None, result: dict | None) -> None:
        raise NotImplementedError

    def _emit(self) -> None:
        if not self._loading:
            self.answersChanged.emit()


# ---------------------------------------------------------------- 選擇題
class MultipleChoiceWidget(AnswerWidget):
    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        self.multiple = dto["selectMode"] == "multiple"
        self.limit = dto.get("selectCount")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        if self.multiple:
            hint = tr('請選擇 {0} 個答案。', self.limit) if self.limit else tr('請選擇所有正確的答案。')
        else:
            hint = tr('請選擇一個答案。')
        layout.addWidget(plain_label(hint, color=MUTED_COLOR, selectable=False))
        self.group = QButtonGroup(self)
        self.group.setExclusive(not self.multiple)
        self.buttons: dict[str, QAbstractButton] = {}
        self.marks: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setColumnStretch(2, 1)
        images = {image["id"]: image for image in dto.get("images", [])}
        for row, option in enumerate(dto["options"]):
            button: QAbstractButton = QCheckBox(self) if self.multiple else QRadioButton(self)
            button.setAccessibleName(f"{_letter(row)}. {qt.strip_images(option['text'])}")
            button.setObjectName(f"{dto['id']}:{option['id']}")
            self.group.addButton(button)
            self.buttons[option["id"]] = button
            letter = QLabel(f"{_letter(row)}.", self)
            if qt.image_refs(option["text"]):
                text = RichOption(option["text"], images, self)
            else:
                text = ClickableLabel(option["text"], self)
            text.clicked.connect(button.click)
            mark = plain_label("", selectable=False, parent=self)
            mark.setVisible(False)
            self.marks[option["id"]] = mark
            grid.addWidget(button, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(letter, row, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(text, row, 2)
            grid.addWidget(mark, row, 3, Qt.AlignmentFlag.AlignTop)
            button.toggled.connect(self._on_toggled)
        layout.addLayout(grid)
        self.review = plain_label("", parent=self)
        self.review.setVisible(False)
        layout.addWidget(self.review)

    def _on_toggled(self, _checked: bool) -> None:
        self._enforce_limit()
        self._emit()

    def _enforce_limit(self) -> None:
        if not (self.multiple and self.limit) or self._read_only:
            return
        chosen = sum(1 for b in self.buttons.values() if b.isChecked())
        for button in self.buttons.values():
            button.setEnabled(button.isChecked() or chosen < self.limit)

    def answers(self) -> dict:
        selected = [oid for oid, b in self.buttons.items() if b.isChecked()]
        return {"selected": selected} if selected else {}

    def _apply(self, answers: dict) -> None:
        _clear_group(self.group)
        for oid in answers.get("selected") or []:
            if oid in self.buttons:
                self.buttons[oid].setChecked(True)
        self._enforce_limit()

    def show_review(self, question: dict | None, result: dict | None) -> None:
        row = _rows_by_id(result).get(qt.MultipleChoice.PART_ID)
        key = set(question.get("correctAnswer") or []) if question else set()
        for oid, mark in self.marks.items():
            chosen = self.buttons[oid].isChecked()
            if oid in key:
                _set_review_label(mark, tr('✔ 正解'), OK_COLOR)
            elif chosen:
                _set_review_label(mark, tr('✘ 不應選'), BAD_COLOR)
            else:
                mark.setVisible(False)
        text, color = _verdict(bool(row and row["isCorrect"]))
        if row and row["selection"] is None:
            text, color = tr('○ 未作答'), BAD_COLOR
        _set_review_label(self.review, text, color)


# ---------------------------------------------------------------- 填空題
class FillInBlankWidget(AnswerWidget):
    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText(tr('請輸入答案'))
        self.edit.setAccessibleName(tr('填空答案'))
        self.edit.textChanged.connect(lambda _t: self._emit())
        layout.addWidget(self.edit)
        self.review = plain_label("", parent=self)
        self.review.setVisible(False)
        layout.addWidget(self.review)

    def answers(self) -> dict:
        text = self.edit.text()
        return {"text": text} if text.strip() else {}

    def _apply(self, answers: dict) -> None:
        self.edit.setText(answers.get("text") or "")

    def show_review(self, question: dict | None, result: dict | None) -> None:
        row = _rows_by_id(result).get(qt.FillInBlank.PART_ID)
        accepted = tr(' ／ ').join((question or {}).get("acceptedAnswers", []))
        if row and row["selection"] is None:
            verdict, color = tr('○ 未作答'), BAD_COLOR
        else:
            verdict, color = _verdict(bool(row and row["isCorrect"]))
        _set_review_label(self.review, tr('{0}\u3000可接受答案：{1}', verdict, accepted), color)


# ---------------------------------------------------------------- 多欄位下拉
class DropdownWidget(AnswerWidget):
    """每個欄位一列：［前文字］［下拉選單］［後文字］。前後文字可多行：
    前文字除最後一行、後文字除第一行，各自成為獨立一行（用於指令腳本中沒有選單的程式碼）。"""

    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        code = bool(dto.get("codeFont"))
        if code:
            self.setFont(code_font(self.font()))
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        has_suffix = any((item.get("suffix") or "").strip() for item in dto["items"])
        grid.setColumnStretch(2 if has_suffix else 1, 1)
        self.combos: dict[str, QComboBox] = {}
        self.reviews: dict[str, QLabel] = {}
        self.option_ids: dict[str, list[str]] = {}
        line = 0

        def full_line(text: str) -> None:
            nonlocal line
            grid.addWidget(plain_label(text, parent=self), line, 0, 1, 3)
            line += 1

        for row, item in enumerate(dto["items"]):
            before = item["label"].split("\n")
            after = (item.get("suffix") or "").split("\n")
            for text in before[:-1]:
                full_line(text)
            inline = before[-1]
            label = plain_label(inline, bold=not code, parent=self)
            label.setVisible(bool(inline.strip()))  # 標籤留白時只顯示下拉選單
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
            if not code:
                label.setMaximumWidth(260)
            combo = QComboBox(self)
            combo.setObjectName(f"{dto['id']}:{item['id']}")
            name = inline.strip() or after[0].strip() or tr('欄位 {0}', row + 1)
            combo.setAccessibleName(name)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
            combo.setSizePolicy(QSizePolicy.Policy.Preferred if has_suffix else QSizePolicy.Policy.Expanding,
                                QSizePolicy.Policy.Fixed)
            combo.addItem(tr(PLACEHOLDER))
            for option in item["options"]:
                combo.addItem(option["text"])
                combo.setItemData(combo.count() - 1, option["text"], Qt.ItemDataRole.ToolTipRole)
            view = combo.view()
            # 下拉清單寬度跟著最長選項，但不超過 640 px；更長的選項以「…」省略，完整文字見提示
            view.setTextElideMode(Qt.TextElideMode.ElideRight)
            view.setMinimumWidth(min(640, max(240, view.sizeHintForColumn(0) + 32)))
            combo.setCurrentIndex(0)
            combo.currentIndexChanged.connect(lambda _i, c=combo: self._on_changed(c))
            label.setBuddy(combo)
            grid.addWidget(label, line, 0, Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(combo, line, 1)
            if after[0].strip():
                suffix = plain_label(after[0], parent=self)
                suffix.setObjectName(f"suffix:{item['id']}")
                grid.addWidget(suffix, line, 2, Qt.AlignmentFlag.AlignVCenter)
            line += 1
            review = plain_label("", parent=self)
            review.setVisible(False)
            grid.addWidget(review, line, 1, 1, 2)
            line += 1
            for text in after[1:]:
                full_line(text)
            self.combos[item["id"]] = combo
            self.reviews[item["id"]] = review
            self.option_ids[item["id"]] = [o["id"] for o in item["options"]]

    def _on_changed(self, combo: QComboBox) -> None:
        combo.setToolTip(combo.currentText() if combo.currentIndex() > 0 else "")
        self._emit()

    def answers(self) -> dict:
        return {iid: self.option_ids[iid][c.currentIndex() - 1]
                for iid, c in self.combos.items() if c.currentIndex() > 0}

    def _apply(self, answers: dict) -> None:
        for iid, combo in self.combos.items():
            value = answers.get(iid)
            ids = self.option_ids[iid]
            combo.setCurrentIndex(ids.index(value) + 1 if value in ids else 0)
            combo.setToolTip(combo.currentText() if combo.currentIndex() > 0 else "")

    def show_review(self, question: dict | None, result: dict | None) -> None:
        rows = _rows_by_id(result)
        items = {i["id"]: i for i in (question or {}).get("items", [])}
        for iid, label in self.reviews.items():
            row = rows.get(iid)
            item = items.get(iid, {})
            correct_text = next((o["text"] for o in item.get("options", []) if o["id"] == item.get("correctAnswer")), "")
            if row and row["selection"] is None:
                verdict, color = tr('○ 未作答'), BAD_COLOR
            else:
                verdict, color = _verdict(bool(row and row["isCorrect"]))
            text = tr('{0}\u3000正解：{1}', verdict, correct_text)
            if item.get("explanation"):
                text += tr('\n解析：{0}', item['explanation'])
            _set_review_label(label, text, color)


# ---------------------------------------------------------------- Yes／No 判斷矩陣
class YesNoWidget(AnswerWidget):
    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(18)
        grid.setColumnStretch(0, 1)
        grid.addWidget(plain_label(tr('敘述（Statements）'), bold=True, selectable=False, parent=self), 0, 0)
        for col, text in ((1, "Yes"), (2, "No")):
            header = plain_label(text, bold=True, wrap=False, selectable=False, parent=self)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(header, 0, col)
        self.groups: dict[str, QButtonGroup] = {}
        self.yes: dict[str, QRadioButton] = {}
        self.no: dict[str, QRadioButton] = {}
        self.reviews: dict[str, QLabel] = {}
        for index, item in enumerate(self.dto["items"]):
            row = 1 + index * 2
            text = plain_label(item["text"], parent=self)
            text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
            group = QButtonGroup(self)
            group.setObjectName(f"{dto['id']}:{item['id']}")  # radio group 名稱含題目 ID 與列 ID
            group.setExclusive(True)
            yes = QRadioButton(self)
            no = QRadioButton(self)
            yes.setAccessibleName(tr('第 {0} 列 Yes：{1}', index + 1, item['text']))
            no.setAccessibleName(tr('第 {0} 列 No：{1}', index + 1, item['text']))
            yes.setObjectName(f"{dto['id']}:{item['id']}:yes")
            no.setObjectName(f"{dto['id']}:{item['id']}:no")
            group.addButton(yes, 1)
            group.addButton(no, 0)
            group.idToggled.connect(lambda _id, checked: checked and self._emit())
            review = plain_label("", parent=self)
            review.setVisible(False)
            grid.addWidget(text, row, 0)
            grid.addWidget(yes, row, 1, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(no, row, 2, Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(review, row + 1, 0, 1, 3)
            self.groups[item["id"]] = group
            self.yes[item["id"]] = yes
            self.no[item["id"]] = no
            self.reviews[item["id"]] = review

    def answers(self) -> dict:
        result: dict[str, Any] = {}
        for iid in self.groups:
            if self.yes[iid].isChecked():
                result[iid] = True
            elif self.no[iid].isChecked():
                result[iid] = False  # No 是有效作答，和未作答不同
        return result

    def _apply(self, answers: dict) -> None:
        for iid, group in self.groups.items():
            _clear_group(group)
            value = answers.get(iid)
            if value is True:
                self.yes[iid].setChecked(True)
            elif value is False:
                self.no[iid].setChecked(True)

    def show_review(self, question: dict | None, result: dict | None) -> None:
        rows = _rows_by_id(result)
        items = {i["id"]: i for i in (question or {}).get("items", [])}
        for iid, label in self.reviews.items():
            row = rows.get(iid)
            item = items.get(iid, {})
            key = item.get("correctAnswer")
            key_text = "Yes" if key is True else "No" if key is False else tr('未設定')
            if row and row["selection"] is None:
                verdict, color = tr('○ 未作答'), BAD_COLOR
            else:
                verdict, color = _verdict(bool(row and row["isCorrect"]))
            text = tr('{0}\u3000正解：{1}', verdict, key_text)
            if item.get("explanation"):
                text += tr('\n解析：{0}', item['explanation'])
            _set_review_label(label, text, color)


# ---------------------------------------------------------------- 解決方案評估題
SERIES_NOTE = ("注意：本題屬於同一情境的系列題。系列中的每一題各提出一個解決方案，可能達成、也可能無法達成所述目標。"
               "有些系列可能有不只一個正確的解決方案，有些可能沒有正確的解決方案。")
NO_RETURN_NOTE = "回答本題並離開後，將無法返回本題，本題也不會出現在檢閱畫面中。"
GOAL_QUESTION = "此解決方案是否達成目標？"


class GoalSolutionWidget(AnswerWidget):
    """A. Yes ／ B. No 單選；解決方案文字由 QuestionView 顯示在作答區之前。"""

    def __init__(self, dto: dict, parent: QWidget | None = None):
        super().__init__(dto, parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[bool, QRadioButton] = {}
        self.marks: dict[bool, QLabel] = {}
        grid = QGridLayout()
        grid.setColumnStretch(2, 1)
        for row, (value, text) in enumerate(((True, "Yes"), (False, "No"))):
            button = QRadioButton(self)
            button.setAccessibleName(f"{_letter(row)}. {text}")
            button.setObjectName(f"{dto['id']}:{text.lower()}")
            self.group.addButton(button)
            self.buttons[value] = button
            label = ClickableLabel(text, self)
            label.clicked.connect(button.click)
            mark = plain_label("", selectable=False, parent=self)
            mark.setVisible(False)
            self.marks[value] = mark
            grid.addWidget(button, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(QLabel(f"{_letter(row)}.", self), row, 1, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(label, row, 2)
            grid.addWidget(mark, row, 3, Qt.AlignmentFlag.AlignTop)
            button.toggled.connect(lambda checked: checked and self._emit())
        layout.addLayout(grid)
        self.review = plain_label("", parent=self)
        self.review.setVisible(False)
        layout.addWidget(self.review)

    def answers(self) -> dict:
        for value, button in self.buttons.items():
            if button.isChecked():
                return {qt.GoalSolution.PART_ID: value}
        return {}

    def _apply(self, answers: dict) -> None:
        _clear_group(self.group)
        value = answers.get(qt.GoalSolution.PART_ID)
        if isinstance(value, bool):
            self.buttons[value].setChecked(True)

    def show_review(self, question: dict | None, result: dict | None) -> None:
        row = _rows_by_id(result).get(qt.GoalSolution.PART_ID)
        key = (question or {}).get("correctAnswer")
        for value, mark in self.marks.items():
            if value is key:
                _set_review_label(mark, tr('✔ 正解'), OK_COLOR)
            elif self.buttons[value].isChecked():
                _set_review_label(mark, tr('✘ 不應選'), BAD_COLOR)
            else:
                mark.setVisible(False)
        text, color = _verdict(bool(row and row["isCorrect"]))
        if row and row["selection"] is None:
            text, color = tr('○ 未作答'), BAD_COLOR
        _set_review_label(self.review, text, color)


def add_series_note(layout: QVBoxLayout, dto: dict, parent: QWidget) -> QFrame:
    """系列題說明（作答前顯示）。"""
    frame = QFrame(parent)
    frame.setObjectName("seriesNote")
    box = QVBoxLayout(frame)
    box.setContentsMargins(12, 8, 12, 8)
    box.setSpacing(6)
    box.addWidget(plain_label(tr(SERIES_NOTE), bold=True, parent=frame))
    if dto.get("noReturn"):
        box.addWidget(plain_label(tr(NO_RETURN_NOTE), bold=True, parent=frame))
    layout.addWidget(frame)
    return frame


def add_solution(layout: QVBoxLayout, dto: dict, parent: QWidget) -> None:
    """「解決方案：…」與「此解決方案是否達成目標？」。"""
    images = {image["id"]: image for image in dto.get("images", [])}
    solution = dto.get("solution") or ""
    segments = qt.rich_segments(solution)
    if segments and segments[0][0] == "runs":  # 「解決方案：」與第一段文字接在同一行
        first = [(tr('解決方案：'), False, None)] + list(_trim_runs(segments[0][1]))
        layout.addWidget(RichLabel(first, parent))
        segments = segments[1:]
    else:
        layout.addWidget(plain_label(tr('解決方案：'), parent=parent))
    for kind, value in segments:
        _add_segment(layout, kind, value, images, parent)
    layout.addWidget(plain_label(tr(GOAL_QUESTION), parent=parent))


RENDERERS = {
    "goal_solution": GoalSolutionWidget,
    "multiple_choice": MultipleChoiceWidget,
    "fill_in_blank": FillInBlankWidget,
    "dropdown_multi": DropdownWidget,
    "yes_no_matrix": YesNoWidget,
}


def create_renderer(dto: dict, parent: QWidget | None = None) -> AnswerWidget:
    from . import renderers_extra  # noqa: F401  註冊排序、拖放、熱區題元件
    return RENDERERS[dto["type"]](dto, parent)


def add_rich(layout: QVBoxLayout, text: str, images: dict[str, dict], parent: QWidget, *,
             selectable: bool = True, zoomable: bool = True, max_image_width: int | None = None) -> None:
    """依序加入文字段落與圖片。圖片標記 {{image:ID}} 以圖片取代顯示；有粗體或字級時以格式化文字顯示。"""
    for kind, value in qt.rich_segments(text):
        _add_segment(layout, kind, value, images, parent, selectable=selectable, zoomable=zoomable,
                     max_image_width=max_image_width)


def _add_segment(layout: QVBoxLayout, kind: str, value, images: dict[str, dict], parent: QWidget, *,
                 selectable: bool = True, zoomable: bool = True, max_image_width: int | None = None) -> None:
    if kind == "runs":
        runs = _trim_runs(value)
        if not "".join(r[0] for r in runs).strip():
            return
        if any(bold or size for _t, bold, size in runs):
            layout.addWidget(RichLabel(runs, parent, selectable=selectable))
        else:
            layout.addWidget(plain_label("".join(r[0] for r in runs), selectable=selectable, parent=parent))
        return
    image = QImage()
    if value in images:
        try:
            image.loadFromData(QByteArray(qt.image_bytes(images[value])))
        except ValueError:
            pass
    if image.isNull():
        layout.addWidget(plain_label(tr('［無法顯示的圖片：{0}］', value), color=BAD_COLOR, parent=parent))
    else:
        layout.addWidget(ImageView(image, tr('圖片 {0}', value), parent, zoomable=zoomable, max_width=max_image_width,
                                   width=qt.image_width(images.get(value))))


def _trim_runs(runs: list[tuple]) -> list[tuple]:
    """去掉段落頭尾緊鄰圖片的換行（與純文字顯示相同）。"""
    runs = list(runs)
    while runs and runs[0][0].lstrip("\n") != runs[0][0]:
        text, bold, size = runs[0]
        runs[0] = (text.lstrip("\n"), bold, size)
        if not runs[0][0]:
            runs.pop(0)
    while runs and runs[-1][0].rstrip("\n") != runs[-1][0]:
        text, bold, size = runs[-1]
        runs[-1] = (text.rstrip("\n"), bold, size)
        if not runs[-1][0]:
            runs.pop()
    return runs


def add_prompt(layout: QVBoxLayout, dto: dict, parent: QWidget) -> None:
    add_rich(layout, dto["prompt"], {image["id"]: image for image in dto.get("images", [])}, parent)


class RichOption(QWidget):
    """選擇題選項內容（文字與圖片）；點擊任何位置都會選取該選項。"""

    clicked = Signal()

    def __init__(self, text: str, images: dict[str, dict], parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        add_rich(layout, text, images, self, selectable=False, zoomable=False, max_image_width=480)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def mousePressEvent(self, event):  # noqa: N802
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.clicked.emit()
        event.accept()


class QuestionView(QWidget):
    """「題目N」、題目內容（文字與圖片）與作答元件的組合；預覽、考試與檢討都使用它。"""

    answersChanged = Signal()

    def __init__(self, dto: dict, heading: str | None = None, parent: QWidget | None = None, case: dict | None = None):
        super().__init__(parent)
        heading = tr('題目') if heading is None else heading
        self.dto = dto
        self.setObjectName("questionCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(12)
        # 題目以「題目N」顯示；題目資料內的 title 欄位不在畫面上出現
        title = plain_label(heading, selectable=False, parent=self)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        if case is not None:
            from .renderers_extra import case_button
            row = QHBoxLayout()
            self.case_button = case_button(case, self)
            row.addWidget(self.case_button)
            row.addWidget(plain_label(tr('本題屬於案例研究「{0}」', case.get('name', '')), color=MUTED_COLOR,
                                      selectable=False, parent=self), 1)
            layout.addLayout(row)
        is_goal = dto.get("type") == "goal_solution"
        if is_goal:
            add_series_note(layout, dto, self)
        if dto.get("prompt"):
            add_prompt(layout, dto, self)
        if is_goal:
            add_solution(layout, dto, self)
        area = plain_label(tr('作答區（Answer Area）'), bold=True, selectable=False, color=MUTED_COLOR, parent=self)
        layout.addWidget(area)
        self.answer_widget = create_renderer(dto, self)
        self.answer_widget.answersChanged.connect(self.answersChanged)
        layout.addWidget(self.answer_widget)
        self.explanation = plain_label("", parent=self)
        self.explanation.setVisible(False)
        layout.addWidget(self.explanation)
        layout.addStretch(1)

    def answers(self) -> dict:
        return self.answer_widget.answers()

    def set_answers(self, answers: dict) -> None:
        self.answer_widget.set_answers(answers)

    def clear(self) -> None:
        self.answer_widget.clear()

    def set_read_only(self, read_only: bool) -> None:
        self.answer_widget.set_read_only(read_only)

    def show_review(self, question: dict, result: dict | None) -> None:
        self.answer_widget.show_review(question, result)
        lines = []
        if result and result.get("status") == "graded":
            lines.append(tr('本題得分：{0:g} ／ {1:g}（{2}，答對 {3}／{4} 項）', result['score'], result['maxScore'], tr(qt.MODE_LABELS[question['scoring']['mode']]), result['correctCount'], result['totalParts']))
        if question.get("explanation"):
            lines.append(tr('解析：') + question["explanation"])
        self.explanation.setText("\n".join(lines))
        self.explanation.setVisible(bool(lines))
