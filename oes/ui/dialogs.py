"""新增題目、開始作答與作答紀錄對話框。"""
from __future__ import annotations

from ..i18n import tr

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import question_types as qt
from ..core import session as S
from ..storage.history import HistoryStore
from .exam_window import ReportDialog, run_session
from .theme import set_role
from .widgets import BAD_COLOR, MUTED_COLOR, plain_label


class NewQuestionDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr('新增題目'))
        self.resize(520, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(plain_label(tr('選擇題型：'), selectable=False))
        self.listing = QListWidget()
        for type_id, question_type in qt.REGISTRY.items():
            item = QListWidgetItem(tr('{0}\n\u3000{1}', tr(question_type.label), tr(question_type.description)))
            item.setData(Qt.ItemDataRole.UserRole, type_id)
            self.listing.addItem(item)
        self.listing.setCurrentRow(0)
        self.listing.setWordWrap(True)
        self.listing.itemActivated.connect(lambda _item: self.accept())
        layout.addWidget(self.listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_type(self) -> str:
        return self.listing.currentItem().data(Qt.ItemDataRole.UserRole)


class StartExamDialog(QDialog):
    def __init__(self, exam: dict, parent: QWidget | None = None):
        super().__init__(parent)
        self.exam = exam
        self.setWindowTitle(tr('開始作答'))
        self.resize(520, 520)
        layout = QVBoxLayout(self)
        usable, excluded = S.eligible_entries(exam)
        layout.addWidget(plain_label(exam["title"], bold=True, point_delta=1))
        summary = tr('可出題 {0} 題', len(usable))
        if excluded:
            summary += tr('；{0} 題因未設定完整正解或格式有誤而不會出題', len(excluded))
        layout.addWidget(plain_label(summary, color=BAD_COLOR if excluded else MUTED_COLOR))
        if exam.get("showDescription") and exam.get("description"):
            layout.addWidget(plain_label(exam["description"]))

        form = QFormLayout()
        self.candidate = QLineEdit()
        self.candidate.setPlaceholderText(tr('選填，用於成績紀錄'))
        form.addRow(tr('考生姓名：'), self.candidate)
        mode_row = QHBoxLayout()
        self.exam_mode = QRadioButton(tr('正式考試'))
        self.exam_mode.setChecked(True)
        self.practice_mode = QRadioButton(tr('練習（可隨時顯示答案）'))
        mode_row.addWidget(self.exam_mode)
        mode_row.addWidget(self.practice_mode)
        mode_row.addStretch(1)
        form.addRow(tr('模式：'), mode_row)
        layout.addLayout(form)

        self.all_sections = QRadioButton(tr('全部題目'))
        self.all_sections.setChecked(True)
        self.some_sections = QRadioButton(tr('只考選取的章節：'))
        layout.addWidget(self.all_sections)
        layout.addWidget(self.some_sections)
        self.sections = QListWidget()
        for section in exam["sections"]:
            item = QListWidgetItem(section["name"])
            item.setData(Qt.ItemDataRole.UserRole, section["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.sections.addItem(item)
        self.sections.setMaximumHeight(120)
        self.some_sections.setEnabled(bool(exam["sections"]))
        self.sections.setEnabled(False)
        self.some_sections.toggled.connect(self.sections.setEnabled)
        layout.addWidget(self.sections)

        options = QFormLayout()
        limit_row = QHBoxLayout()
        self.use_limit = QCheckBox(tr('只出'))
        self.limit = QSpinBox()
        self.limit.setRange(1, max(1, len(usable)))
        self.limit.setValue(max(1, len(usable)))
        self.limit.setEnabled(False)
        self.use_limit.toggled.connect(self.limit.setEnabled)
        limit_row.addWidget(self.use_limit)
        limit_row.addWidget(self.limit)
        limit_row.addWidget(plain_label(tr('題'), selectable=False))
        limit_row.addStretch(1)
        options.addRow(tr('題數：'), limit_row)
        self.shuffle = QCheckBox(tr('題目隨機排序'))
        options.addRow("", self.shuffle)
        timer_row = QHBoxLayout()
        self.use_timer = QCheckBox(tr('限時'))
        self.minutes = QSpinBox()
        self.minutes.setRange(1, 10_000)
        self.minutes.setSuffix(tr(' 分鐘'))
        self.minutes.setValue(exam.get("timeLimitMinutes") or 60)
        self.use_timer.setChecked(bool(exam.get("timeLimitMinutes")))
        self.minutes.setEnabled(self.use_timer.isChecked())
        self.use_timer.toggled.connect(self.minutes.setEnabled)
        timer_row.addWidget(self.use_timer)
        timer_row.addWidget(self.minutes)
        timer_row.addStretch(1)
        options.addRow(tr('計時：'), timer_row)
        layout.addLayout(options)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr('開始'))
        set_role(buttons.button(QDialogButtonBox.StandardButton.Ok), "primary")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(usable))
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.session: dict | None = None

    def _try_accept(self) -> None:
        section_ids = None
        if self.some_sections.isChecked():
            section_ids = [self.sections.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.sections.count())
                           if self.sections.item(i).checkState() == Qt.CheckState.Checked]
            if not section_ids:
                QMessageBox.warning(self, tr('開始作答'), tr('請至少勾選一個章節。'))
                return
        try:
            self.session = S.build_session(
                self.exam, candidate=self.candidate.text().strip(), section_ids=section_ids,
                limit=self.limit.value() if self.use_limit.isChecked() else None,
                shuffle_questions=self.shuffle.isChecked(),
                time_limit_minutes=self.minutes.value() if self.use_timer.isChecked() else 0,
                mode="practice" if self.practice_mode.isChecked() else "exam")
        except ValueError as exc:
            QMessageBox.warning(self, tr('開始作答'), str(exc))
            return
        self.accept()


class HistoryDialog(QDialog):
    def __init__(self, store: HistoryStore, exam_id: str | None, parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.exam_id = exam_id
        self.setWindowTitle(tr('成績與作答紀錄'))
        self.resize(860, 480)
        layout = QVBoxLayout(self)
        self.only_current = QCheckBox(tr('只顯示目前題庫的紀錄'))
        self.only_current.setChecked(exam_id is not None)
        self.only_current.setEnabled(exam_id is not None)
        self.only_current.toggled.connect(self.reload)
        layout.addWidget(self.only_current)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([tr('開始時間'), tr('題庫'), tr('考生'), tr('模式'), tr('狀態'), tr('分數'), tr('結果')])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.doubleClicked.connect(lambda _i: self.open_selected())
        layout.addWidget(self.table, 1)
        buttons = QHBoxLayout()
        open_button = QPushButton(tr('繼續作答／查看成績'))
        open_button.clicked.connect(self.open_selected)
        delete = QPushButton(tr('刪除紀錄'))
        delete.clicked.connect(self.delete_selected)
        close = QPushButton(tr('關閉'))
        close.clicked.connect(self.accept)
        buttons.addWidget(open_button)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.rows: list[dict] = []
        self.reload()

    def reload(self) -> None:
        self.rows = self.store.list(self.exam_id if self.only_current.isChecked() else None)
        self.table.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            finished = row["status"] == "finished"
            values = (
                (row["startedAt"] or "")[:19].replace("T", " "),
                row["examTitle"], row["candidate"],
                tr('練習') if row["mode"] == "practice" else tr('正式'),
                tr('已完成') if finished else tr('進行中'),
                f"{row['percent']:g}%" if row["percent"] is not None else "—",
                (tr('通過') if row["passed"] else tr('未通過')) if finished else "—",
            )
            for c, value in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(value))

    def _selected(self) -> dict | None:
        index = self.table.currentRow()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def open_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        session = self.store.load(row["id"])
        if session["status"] == "finished":
            ReportDialog(session, self.store, self).exec()
        else:
            run_session(session, self.store, self)
        self.reload()

    def delete_selected(self) -> None:
        row = self._selected()
        if row is None:
            return
        if QMessageBox.question(self, tr('刪除紀錄'), tr('確定刪除這筆作答紀錄？此動作無法復原。')) == QMessageBox.StandardButton.Yes:
            self.store.delete(row["id"])
            self.reload()
