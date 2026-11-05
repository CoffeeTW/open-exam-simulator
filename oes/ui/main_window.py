"""題庫編輯器主視窗。"""
from __future__ import annotations

from ..i18n import tr

import re
from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QUrl
from PySide6.QtGui import QAction, QActionGroup, QBrush, QColor, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (QApplication, QCheckBox, QFileDialog, QFormLayout, QGroupBox, QSizePolicy, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
                               QMenu, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget, QTabWidget,
                               QVBoxLayout, QWidget)

from ..core import exam as E
from ..core import question_types as qt
from ..storage.exam_file import FILE_EXTENSION, ExamFileError, load_exam, save_exam
from ..storage.history import HistoryStore, resource_dir
from .dialogs import HistoryDialog, NewQuestionDialog, StartExamDialog
from .editors import QuestionEditor
from .prompt_editor import ImagePool, PromptEditor, recompress_exam, webp_supported
from .exam_window import run_session
from .renderers import QuestionView
from . import settings, theme
from ..i18n import LANGUAGES, get_language, set_language
from .i18n import install_translations
from .theme import COLORS, THEME_LABELS, icon, set_role

_WINDOWS: list = []  # 切換語言時建立的新主視窗（保留參考避免被回收）
from .widgets import BAD_COLOR, MUTED_COLOR, OK_COLOR, plain_label

FILE_FILTER = f"Open Exam Simulator 題庫 (*{FILE_EXTENSION})"
JSON_FILTER = "JSON 檔 (*.json)"
SAMPLE_PATH = resource_dir() / "samples" / "示範題庫.oes"


def _size_text(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


def question_state(question: dict) -> str:
    if qt.validate(question):
        return "error"
    if qt.validate(question, require_answer_key=True):
        return "draft"
    return "ready" if question.get("status") == "ready" else "keyed_draft"


STATE_ICON = {"error": "dot-error", "draft": "dot-draft", "keyed_draft": "dot-draft", "ready": "dot-ok"}
STATE_TIP = {
    "error": "格式有誤，請修正",
    "draft": "草稿：尚未設定完整正解，不會出題",
    "keyed_draft": "草稿：正解已完整，改為「可使用」後才會出題",
    "ready": "可使用",
}


class ExamPropertiesPage(QWidget):
    """題庫屬性與章節管理。"""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.main = window
        self.layout_ = QVBoxLayout(self)

    def load(self, exam: dict) -> None:
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            if item.widget():
                item.widget().hide()
                item.widget().deleteLater()
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(12)
        title = plain_label(tr('題庫屬性與章節'), selectable=False)
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        states = [question_state(e["question"]) for e in exam["questions"]]
        stats = QHBoxLayout()
        for text, name in ((tr('共 {0} 題', len(states)), "pill"), (tr('可出題 {0}', states.count('ready')), "pill"),
                           (tr('草稿 {0}', states.count('draft') + states.count('keyed_draft')), "pill"),
                           (tr('格式有誤 {0}', states.count('error')), "pillWarn" if states.count("error") else "pill")):
            chip = QLabel(text)
            chip.setObjectName(name)
            stats.addWidget(chip)
        stats.addStretch(1)
        layout.addLayout(stats)
        hint = plain_label(tr('只有狀態為「可使用」且正解完整的題目會出題。'), selectable=False)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        basic = QGroupBox(tr('基本資料'))
        basic_layout = QVBoxLayout(basic)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for key, label in (("title", tr('標題：')), ("number", tr('編號：')), ("version", tr('版本：'))):
            edit = QLineEdit(exam[key])
            edit.textEdited.connect(lambda t, k=key: self._set(k, t))
            form.addRow(label, edit)
        passing = QSpinBox()
        passing.setRange(0, 100)
        passing.setSuffix(" %")
        passing.setValue(int(exam["passingScore"]))
        passing.valueChanged.connect(lambda v: self._set("passingScore", v))
        form.addRow(tr('及格分數：'), passing)
        limit = QSpinBox()
        limit.setRange(0, 10_000)
        limit.setSpecialValueText(tr('不限時'))
        limit.setSuffix(tr(' 分鐘'))
        limit.setValue(int(exam["timeLimitMinutes"]))
        limit.valueChanged.connect(lambda v: self._set("timeLimitMinutes", v))
        form.addRow(tr('預設時間限制：'), limit)
        show = QCheckBox(tr('開始作答前顯示說明'))
        show.setChecked(exam["showDescription"])
        show.toggled.connect(lambda v: self._set("showDescription", v))
        form.addRow("", show)
        description = QPlainTextEdit(exam["description"])
        description.setTabChangesFocus(True)
        description.setFixedHeight(110)
        description.textChanged.connect(lambda: self._set("description", description.toPlainText()))
        form.addRow(tr('說明：'), description)
        basic_layout.addLayout(form)
        layout.addWidget(basic)

        section_box = QGroupBox(tr('章節'))
        section_layout = QVBoxLayout(section_box)
        section_layout.addWidget(plain_label(tr('章節用來分組題目；成績報告會列出各章節分數。在題目編輯頁選擇題目所屬章節。'),
                                             color=MUTED_COLOR, selectable=False))
        row = QHBoxLayout()
        self.sections = QListWidget()
        self.sections.setMaximumHeight(160)
        counts: dict[str | None, int] = {}
        for entry in exam["questions"]:
            counts[entry.get("sectionId")] = counts.get(entry.get("sectionId"), 0) + 1
        for section in exam["sections"]:
            item = QListWidgetItem(tr('{0}（{1} 題）', section['name'], counts.get(section['id'], 0)))
            item.setData(Qt.ItemDataRole.UserRole, section["id"])
            self.sections.addItem(item)
        row.addWidget(self.sections, 1)
        buttons = QVBoxLayout()
        for text, slot in ((tr('新增'), self._add_section), (tr('重新命名'), self._rename_section), (tr('刪除'), self._delete_section)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            if text == tr('刪除'):
                set_role(button, "danger")
            buttons.addWidget(button)
        buttons.addStretch(1)
        row.addLayout(buttons)
        section_layout.addLayout(row)
        layout.addWidget(section_box)

        case_box = QGroupBox(tr('案例研究'))
        case_layout = QVBoxLayout(case_box)
        case_layout.addWidget(plain_label(tr('一段情境說明搭配多題。作答時這些題目會出現「案例研究…」按鈕。在題目編輯頁選擇題目所屬的案例研究。'), color=MUTED_COLOR, selectable=False))
        case_row = QHBoxLayout()
        self.cases = QListWidget()
        self.cases.setMaximumHeight(130)
        case_counts: dict[str | None, int] = {}
        for entry in exam["questions"]:
            case_counts[entry.get("caseStudyId")] = case_counts.get(entry.get("caseStudyId"), 0) + 1
        for case in exam.setdefault("caseStudies", []):
            item = QListWidgetItem(tr('{0}（{1} 題）', case['name'], case_counts.get(case['id'], 0)))
            item.setData(Qt.ItemDataRole.UserRole, case["id"])
            self.cases.addItem(item)
        case_row.addWidget(self.cases, 1)
        case_buttons = QVBoxLayout()
        for text, slot in ((tr('新增'), self._add_case), (tr('重新命名'), self._rename_case), (tr('刪除'), self._delete_case)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            if text == tr('刪除'):
                set_role(button, "danger")
            case_buttons.addWidget(button)
        case_buttons.addStretch(1)
        case_row.addLayout(case_buttons)
        case_layout.addLayout(case_row)
        self.case_editor_box = QVBoxLayout()
        case_layout.addLayout(self.case_editor_box)
        layout.addWidget(case_box)
        self.cases.currentItemChanged.connect(lambda current, _prev: self._show_case(current))
        if self.cases.count():
            self.cases.setCurrentRow(0)

        layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(container)
        self.layout_.addWidget(scroll)

    def _set(self, key: str, value) -> None:
        self.main.exam[key] = value
        self.main.mark_dirty()

    def _selected_section(self) -> str | None:
        item = self.sections.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _add_section(self) -> None:
        name, ok = QInputDialog.getText(self, tr('新增章節'), tr('章節名稱：'))
        if ok and name.strip():
            E.add_section(self.main.exam, name.strip())
            self.main.mark_dirty()
            self.load(self.main.exam)

    def _rename_section(self) -> None:
        section_id = self._selected_section()
        section = next((s for s in self.main.exam["sections"] if s["id"] == section_id), None)
        if section is None:
            return
        name, ok = QInputDialog.getText(self, tr('重新命名章節'), tr('章節名稱：'), text=section["name"])
        if ok and name.strip():
            section["name"] = name.strip()
            self.main.mark_dirty()
            self.load(self.main.exam)

    def _delete_section(self) -> None:
        section_id = self._selected_section()
        if section_id is None:
            return
        if QMessageBox.question(self, tr('刪除章節'), tr('確定刪除此章節？章節內的題目會保留，但不再屬於任何章節。')) \
                == QMessageBox.StandardButton.Yes:
            E.remove_section(self.main.exam, section_id)
            self.main.mark_dirty()
            self.load(self.main.exam)


    # ------------------------------------------------------------ 案例研究
    def _selected_case(self) -> dict | None:
        item = self.cases.currentItem()
        return E.case_study(self.main.exam, item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _show_case(self, item) -> None:
        while self.case_editor_box.count():
            child = self.case_editor_box.takeAt(0)
            if child.widget():
                child.widget().hide()
                child.widget().deleteLater()
        case = E.case_study(self.main.exam, item.data(Qt.ItemDataRole.UserRole)) if item else None
        if case is None:
            return
        pool = ImagePool(case.get("images"))
        editor = PromptEditor(case.get("text", ""), pool, height_key="case")
        editor.edit.setPlaceholderText(tr('案例研究內容（情境、需求等）；可貼上圖片'))
        editor.edit.setMinimumHeight(260)

        def changed(text: str, case=case, pool=pool) -> None:
            case["text"] = text
            images = pool.collect(qt.image_refs(text))
            if images:
                case["images"] = images
            else:
                case.pop("images", None)
            self.main.mark_dirty()

        editor.changed.connect(changed)
        self.case_editor_box.addWidget(plain_label(tr('「{0}」的內容：', case['name']), selectable=False))
        self.case_editor_box.addWidget(editor)

    def _add_case(self) -> None:
        name, ok = QInputDialog.getText(self, tr('新增案例研究'), tr('案例名稱：'))
        if ok and name.strip():
            E.add_case_study(self.main.exam, name.strip())
            self.main.mark_dirty()
            self.load(self.main.exam)
            self.cases.setCurrentRow(self.cases.count() - 1)

    def _rename_case(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        name, ok = QInputDialog.getText(self, tr('重新命名案例研究'), tr('案例名稱：'), text=case["name"])
        if ok and name.strip():
            case["name"] = name.strip()
            self.main.mark_dirty()
            self.load(self.main.exam)

    def _delete_case(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        if QMessageBox.question(self, tr('刪除案例研究'), tr('確定刪除「{0}」？題目會保留，但不再屬於這個案例。', case['name'])) \
                == QMessageBox.StandardButton.Yes:
            E.remove_case_study(self.main.exam, case["id"])
            self.main.mark_dirty()
            self.load(self.main.exam)


class QuestionPage(QWidget):
    """單一題目的「編輯」與「預覽」分頁。"""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.main = window
        self.entry: dict | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.edit_scroll = QScrollArea()
        self.edit_scroll.setWidgetResizable(True)
        self.tabs.addTab(self.edit_scroll, tr('編輯題目與正解'))
        preview = QWidget()
        preview_layout = QVBoxLayout(preview)
        bar = QHBoxLayout()
        for text, slot in ((tr('評分（預覽）'), self.preview_grade), (tr('顯示答案'), self.preview_reveal),
                           (tr('清除作答'), self.preview_clear)):
            button = QPushButton(text)
            button.clicked.connect(slot)
            if slot == self.preview_grade:
                set_role(button, "primary")
            bar.addWidget(button)
        bar.addStretch(1)
        preview_layout.addLayout(bar)
        self.preview_result = plain_label("", wrap=True)
        preview_layout.addWidget(self.preview_result)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        preview_layout.addWidget(self.preview_scroll, 1)
        self.tabs.addTab(preview, tr('作答預覽'))
        self.tabs.currentChanged.connect(lambda i: i == 1 and self.build_preview())
        layout.addWidget(self.tabs)
        self.preview_view: QuestionView | None = None

    def load(self, entry: dict) -> None:
        self.entry = entry
        editor = QuestionEditor(entry, self.main.exam["sections"], cases=self.main.exam.setdefault("caseStudies", []))
        editor.changed.connect(self.main.question_changed)
        editor.message.connect(lambda m: self.main.statusBar().showMessage(m, 8000))
        self.edit_scroll.setWidget(editor)
        if self.tabs.currentIndex() == 1:
            self.build_preview()

    def build_preview(self) -> None:
        self.preview_result.setText("")
        self.preview_view = None
        if self.entry is None:
            return
        question = self.entry["question"]
        try:
            dto = qt.for_candidate(question)
        except ValueError as exc:
            message = plain_label(tr('題目格式有誤，無法預覽：\n') + str(exc), color=BAD_COLOR)
            self.preview_scroll.setWidget(message)
            return
        case = E.case_study(self.main.exam, self.entry.get("caseStudyId"))
        self.preview_view = QuestionView(dto, heading=tr('題目{0}', self.main.current_index() + 1), case=case)
        self.preview_view.answersChanged.connect(lambda: self.preview_result.setText(""))
        self.preview_scroll.setWidget(self.preview_view)

    def preview_grade(self) -> None:
        if self.preview_view is None or self.entry is None:
            return
        question = self.entry["question"]
        result = qt.grade(question, self.preview_view.answers())
        status = result["status"]
        if status == "unconfigured":
            text, color = tr('尚未設定完整正解或題目格式有誤，無法評分。'), BAD_COLOR
        elif status == "invalid":
            text, color = tr('作答資料不合法。'), BAD_COLOR
        elif status == "incomplete":
            text, color = tr('尚有 {0} 個項目未作答，請完成後再評分。', len(result['unansweredIds'])), BAD_COLOR
        else:
            text = (tr('得分 {0:g} ／ {1:g}，答對 {2}／{3} 項（{4}）', result['score'], result['maxScore'], result['correctCount'], result['totalParts'], tr(qt.MODE_LABELS[question['scoring']['mode']])))
            color = OK_COLOR if result["score"] >= result["maxScore"] else BAD_COLOR
            self.preview_view.show_review(question, result)
        self.preview_result.setText(text)
        self.preview_result.setStyleSheet(f"color: {color};")

    def preview_reveal(self) -> None:
        if self.preview_view is None or self.entry is None:
            return
        question = self.entry["question"]
        result = qt.grade(question, self.preview_view.answers(), allow_incomplete=True)
        if result["status"] == "unconfigured":
            self.preview_result.setText(tr('尚未設定完整正解，沒有答案可以顯示。'))
            self.preview_result.setStyleSheet(f"color: {BAD_COLOR};")
            return
        self.preview_view.show_review(question, result if result["status"] == "graded" else None)

    def preview_clear(self) -> None:
        self.build_preview()


class MainWindow(QMainWindow):
    def __init__(self, store: HistoryStore | None = None):
        super().__init__()
        self.store = store or HistoryStore()
        self.exam: dict = E.new_exam()
        self.path: Path | None = None
        self.dirty = False
        self.resize(1200, 800)

        self.listing = QListWidget()
        self.listing.setMinimumWidth(260)
        self.listing.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.listing.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.listing.currentRowChanged.connect(self._row_changed)
        self.stack = QStackedWidget()
        self.properties = ExamPropertiesPage(self)
        self.question_page = QuestionPage(self)
        self.empty = QLabel("")
        self.stack.addWidget(self.properties)
        self.stack.addWidget(self.question_page)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(10, 10, 4, 10)
        left_layout.setSpacing(8)
        header = QHBoxLayout()
        list_title = plain_label(tr('題目清單'), selectable=False)
        list_title.setObjectName("sectionTitle")
        header.addWidget(list_title)
        header.addStretch(1)
        self.count_chip = QLabel(tr('0 題'))
        self.count_chip.setObjectName("pill")
        header.addWidget(self.count_chip)
        left_layout.addLayout(header)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr('搜尋題目（Ctrl+F）'))
        self.search.setClearButtonEnabled(True)
        self.search.setToolTip(tr('搜尋題目內容、選項、解析與題目 ID；多個關鍵字以空白分隔，須全部符合'))
        self.search.textChanged.connect(lambda _t: self.apply_search())
        self.search.installEventFilter(self)
        left_layout.addWidget(self.search)
        self.search_info = plain_label("", color=MUTED_COLOR, selectable=False)
        self.search_info.setVisible(False)
        left_layout.addWidget(self.search_info)
        self.listing.setObjectName("questionList")
        self.listing.setIconSize(QSize(16, 16))
        left_layout.addWidget(self.listing, 1)
        legend = QHBoxLayout()
        for kind, text in (("dot-ok", tr('可使用')), ("dot-draft", tr('草稿')), ("dot-error", tr('格式有誤'))):
            dot = QLabel()
            dot.setPixmap(icon(kind).pixmap(14, 14))
            legend.addWidget(dot)
            label = QLabel(text)
            label.setObjectName("hint")
            legend.addWidget(label)
            legend.addSpacing(6)
        legend.addStretch(1)
        left_layout.addLayout(legend)
        splitter.addWidget(left)
        splitter.addWidget(self.stack)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 940])
        self.stack.setContentsMargins(0, 6, 8, 6)
        self.setCentralWidget(splitter)
        self._build_actions()
        self.statusBar()
        self.refresh_all()

    # ------------------------------------------------------------ 動作
    def _action(self, text: str, slot, shortcut: str | QKeySequence.StandardKey | None = None, tip: str = "") -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setStatusTip(tip)
        action.triggered.connect(slot)
        return action

    def _build_actions(self) -> None:
        a = self._action
        self.act_new = a(tr('新增題庫'), self.new_exam, QKeySequence.StandardKey.New)
        self.act_open = a(tr('開啟題庫…'), self.open_exam, QKeySequence.StandardKey.Open)
        self.act_save = a(tr('儲存'), self.save, QKeySequence.StandardKey.Save)
        self.act_save_as = a(tr('另存新檔…'), self.save_as, QKeySequence.StandardKey.SaveAs)
        self.act_import = a(tr('匯入 JSON…'), self.import_json, None, tr('匯入題庫 JSON，或把題目 JSON 加入目前題庫'))
        self.act_export = a(tr('匯出題庫 JSON…'), self.export_exam_json)
        self.act_export_q = a(tr('匯出目前題目 JSON…'), self.export_question_json)
        self.act_export_pdf = a(tr('匯出 PDF…'), self.export_pdf, "Ctrl+P",
                                tr('把題庫輸出成 PDF，可選擇是否包含正確答案與解析'))
        self.act_sample = a(tr('開啟示範題庫'), self.open_sample)
        self.act_compress = a(tr('壓縮題庫圖片'), self.compress_images, None,
                              tr('把題庫中的 PNG 圖片改存成較小的無失真格式，畫質不變'))
        self.act_quit = a(tr('結束'), self.close, QKeySequence.StandardKey.Quit)
        self.act_add = a(tr('新增題目…'), self.add_question, "Ctrl+Shift+N")
        self.act_dup = a(tr('複製題目'), self.duplicate_question, "Ctrl+D")
        self.act_del = a(tr('刪除題目'), self.delete_question)
        self.act_up = a(tr('上移題目'), lambda: self.move_question(-1), "Alt+Up")
        self.act_down = a(tr('下移題目'), lambda: self.move_question(1), "Alt+Down")
        self.act_start = a(tr('開始作答…'), self.start_exam, "F5")
        self.act_history = a(tr('成績與作答紀錄…'), self.show_history, "Ctrl+H")
        self.act_about = a(tr('關於'), self.about)
        self.act_search = a(tr('搜尋題目'), self.focus_search, QKeySequence.StandardKey.Find)
        self.addAction(self.act_search)
        # Delete 只在題目清單有焦點時作用，避免和文字編輯衝突
        self.act_del.setShortcut(QKeySequence(QKeySequence.StandardKey.Delete))
        self.act_del.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.listing.addAction(self.act_del)

        menu = self.menuBar()
        file_menu = menu.addMenu(tr('檔案(&F)'))
        for action in (self.act_new, self.act_open, self.act_save, self.act_save_as, None, self.act_import,
                       self.act_export, self.act_export_q, self.act_export_pdf, None, self.act_compress, None, self.act_sample, None,
                       self.act_quit):
            file_menu.addSeparator() if action is None else file_menu.addAction(action)
        question_menu = menu.addMenu(tr('題目(&Q)'))
        for action in (self.act_add, self.act_dup, self.act_del, None, self.act_up, self.act_down, None,
                       self.act_search):
            question_menu.addSeparator() if action is None else question_menu.addAction(action)
        exam_menu = menu.addMenu(tr('考試(&E)'))
        exam_menu.addAction(self.act_start)
        exam_menu.addAction(self.act_history)
        view_menu = menu.addMenu(tr('檢視(&V)'))
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_actions: dict[str, QAction] = {}
        for name, label in THEME_LABELS.items():
            action = QAction(tr(label), self)
            action.setCheckable(True)
            action.triggered.connect(lambda _=False, n=name: self.set_theme(n))
            self.theme_group.addAction(action)
            view_menu.addAction(action)
            self.theme_actions[name] = action
        view_menu.addSeparator()
        self.act_toggle_theme = self._action(tr('切換深色／淺色'), self.toggle_theme, "Ctrl+Shift+T")
        view_menu.addAction(self.act_toggle_theme)
        view_menu.addSeparator()
        language_menu = view_menu.addMenu("語言 / Language")
        self.language_group = QActionGroup(self)
        self.language_group.setExclusive(True)
        self.language_actions: dict[str, QAction] = {}
        for code, label in LANGUAGES.items():  # 語言名稱以各自的語言顯示，不翻譯
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(code == get_language())
            action.triggered.connect(lambda _=False, c=code: self.set_language(c))
            self.language_group.addAction(action)
            language_menu.addAction(action)
            self.language_actions[code] = action
        help_menu = menu.addMenu(tr('說明(&H)'))
        help_menu.addAction(self.act_about)

        toolbar = self.addToolBar(tr('主要工具列'))
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        for action in (self.act_new, self.act_open, self.act_save, None, self.act_start, self.act_history):
            toolbar.addSeparator() if action is None else toolbar.addAction(action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)
        toolbar.addAction(self.act_toggle_theme)
        self._sync_theme_ui()

        # 題目操作改由題目清單的滑鼠右鍵選單提供
        self.listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.listing.customContextMenuRequested.connect(self.show_list_menu)

    # ------------------------------------------------------------ 主題
    def _sync_theme_ui(self) -> None:
        """依目前主題更新圖示與選單勾選。"""
        for action, kind, color in ((self.act_new, "new", None), (self.act_open, "open", None),
                                    (self.act_save, "save", None), (self.act_add, "plus", None),
                                    (self.act_start, "play", COLORS["accent"]), (self.act_history, "history", None)):
            action.setIcon(icon(kind, color))
        dark = theme.current_theme == "dark"
        self.act_toggle_theme.setIcon(icon("sun" if dark else "moon"))
        self.act_toggle_theme.setText(tr('淺色主題') if dark else tr('深色主題'))
        self.act_toggle_theme.setToolTip(tr('切換為淺色主題（Ctrl+Shift+T）') if dark else tr('切換為深色主題（Ctrl+Shift+T）'))
        self.theme_actions[theme.current_theme].setChecked(True)

    def set_theme(self, name: str, remember: bool = True) -> None:
        app = QApplication.instance()
        name = theme.apply_theme(app, name)
        if remember:
            settings.save({"theme": name})
        self._sync_theme_ui()
        # 重建清單與目前頁面，讓建立時設定顏色的元件也換成新主題
        self.refresh_all()

    def set_language(self, language: str) -> "MainWindow":
        """切換介面語言：重新建立主視窗（保留目前題庫、檔案路徑、未儲存狀態與選取的題目）。"""
        if language == get_language():
            return self
        app = QApplication.instance()
        old_default = E.default_title()
        set_language(language)
        if self.exam.get("title") == old_default:  # 尚未改過的預設標題跟著換成新語言
            self.exam["title"] = E.default_title()
        install_translations(app, language)
        settings.save({"language": language})
        replacement = MainWindow(self.store)
        replacement.set_exam(self.exam, self.path, self.dirty)
        replacement.refresh_all(self.listing.currentRow())
        replacement.restoreGeometry(self.saveGeometry())
        _WINDOWS.append(replacement)
        if self.isVisible():
            replacement.show()
        self._replaced = True
        self.close()
        return replacement

    def toggle_theme(self) -> None:
        self.set_theme("light" if theme.current_theme == "dark" else "dark")

    def list_menu(self, pos) -> QMenu:
        """建立題目清單的右鍵選單；在題目上按右鍵會先選取該題。"""
        item = self.listing.itemAt(pos)
        if item is not None:
            self.listing.setCurrentItem(item)
        menu = QMenu(self.listing)
        menu.addAction(self.act_add)
        if self.current_index() >= 0:
            for action in (self.act_dup, self.act_del, None, self.act_up, self.act_down):
                menu.addSeparator() if action is None else menu.addAction(action)
        return menu

    def show_list_menu(self, pos) -> None:
        self.list_menu(pos).exec(self.listing.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------ 清單與狀態
    def refresh_all(self, select_row: int | None = None) -> None:
        current = self.listing.currentRow() if select_row is None else select_row
        self.listing.blockSignals(True)
        self.listing.clear()
        root = QListWidgetItem(icon("exam", COLORS["accent"]), tr('題庫屬性與章節'))
        self.listing.addItem(root)
        for index in range(len(self.exam["questions"])):
            self.listing.addItem(QListWidgetItem())
            self._update_item(index)
        self.listing.blockSignals(False)
        self.count_chip.setText(tr('{0} 題', len(self.exam['questions'])))
        if hasattr(self, "search"):
            self._update_search_info()
        current = min(max(current, 0), self.listing.count() - 1)
        self.listing.setCurrentRow(current)
        self._row_changed(current)
        self._update_title()

    def _update_item(self, index: int) -> None:
        entry = self.exam["questions"][index]
        question = entry["question"]
        state = question_state(question)
        try:
            type_label = tr(qt.get_type(question["type"]).label)
        except ValueError:
            type_label = tr('不支援的題型')
        item = self.listing.item(index + 1)
        # 清單只顯示依目前順序編號的「題目N」；標題、題型與狀態放在滑鼠提示。
        # 搜尋時顯示符合的片段，不符合的題目隱藏（正在編輯的題目一律保留）。
        query = self.search.text() if hasattr(self, "search") else ""
        text = qt.search_text(question)
        if query.strip():
            matched = qt.search_matches(text, query)
            snippet = qt.search_snippet(text, query) if matched else ""
            item.setText(tr('題目{0}', index + 1) + (f"\u3000{snippet}" if snippet else ""))
            self.listing.setRowHidden(index + 1, not matched and self.listing.currentRow() != index + 1)
        else:
            item.setText(tr('題目{0}', index + 1))
            self.listing.setRowHidden(index + 1, False)
        item.setIcon(icon(STATE_ICON[state]))
        item.setToolTip(f"{type_label}\n{tr(STATE_TIP[state])}")
        if state == "error":
            item.setForeground(QBrush(QColor(str(BAD_COLOR))))
        else:
            item.setData(Qt.ItemDataRole.ForegroundRole, None)

    def apply_search(self) -> None:
        """依搜尋框篩選題目清單，並顯示符合的題數。"""
        for index in range(len(self.exam["questions"])):
            self._update_item(index)
        self._update_search_info()

    def _update_search_info(self) -> None:
        query = self.search.text()
        if not query.strip():
            self.search_info.setVisible(False)
            return
        found = sum(1 for e in self.exam["questions"] if qt.search_matches(qt.search_text(e["question"]), query))
        self.search_info.setText(tr('找到 {0} 題', found) if found else tr('找不到符合的題目'))
        self.search_info.setVisible(True)

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    def eventFilter(self, watched, event):  # noqa: N802
        if watched is getattr(self, "search", None) and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape and self.search.text():
                self.search.clear()
                return True
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._select_first_match()
                return True
        return super().eventFilter(watched, event)

    def _select_first_match(self) -> None:
        for row in range(1, self.listing.count()):
            if not self.listing.isRowHidden(row):
                self.listing.setCurrentRow(row)
                self.listing.setFocus()
                return

    def _row_changed(self, row: int) -> None:
        if row <= 0:
            self.properties.load(self.exam)
            self.stack.setCurrentWidget(self.properties)
        else:
            self.question_page.load(self.exam["questions"][row - 1])
            self.stack.setCurrentWidget(self.question_page)
        has_question = row > 0
        for action in (self.act_dup, self.act_del, self.act_export_q):
            action.setEnabled(has_question)
        self.act_up.setEnabled(row > 1)
        self.act_down.setEnabled(0 < row < len(self.exam["questions"]))

    def question_changed(self) -> None:
        row = self.listing.currentRow()
        if row > 0:
            self._update_item(row - 1)
            self._update_search_info()
        self.mark_dirty()

    def mark_dirty(self) -> None:
        if not self.dirty:
            self.dirty = True
            self._update_title()

    def _update_title(self) -> None:
        name = self.path.name if self.path else tr('未儲存的題庫')
        self.setWindowTitle(tr('{0}{1} — Open Exam Simulator 題庫編輯器', '*' if self.dirty else '', name))

    # ------------------------------------------------------------ 題目操作
    def current_index(self) -> int:
        return self.listing.currentRow() - 1

    def add_question(self) -> None:
        dialog = NewQuestionDialog(self)
        if not dialog.exec():
            return
        index = self.current_index() + 1 if self.current_index() >= 0 else len(self.exam["questions"])
        section = self.exam["questions"][self.current_index()].get("sectionId") if self.current_index() >= 0 else None
        E.add_question(self.exam, dialog.selected_type(), section, index)
        self.mark_dirty()
        self.refresh_all(index + 1)
        self.question_page.tabs.setCurrentIndex(0)

    def duplicate_question(self) -> None:
        index = self.current_index()
        if index < 0:
            return
        entry = qt.clone(self.exam["questions"][index])
        entry["question"]["id"] = E.new_question_id(E.question_ids(self.exam))
        self.exam["questions"].insert(index + 1, entry)
        self.mark_dirty()
        self.refresh_all(index + 2)

    def delete_question(self) -> None:
        index = self.current_index()
        if index < 0:
            return
        if QMessageBox.question(self, tr('刪除題目'), tr('確定刪除「題目{0}」？', index + 1)) != QMessageBox.StandardButton.Yes:
            return
        del self.exam["questions"][index]
        self.mark_dirty()
        self.refresh_all(min(index + 1, len(self.exam["questions"])))

    def move_question(self, delta: int) -> None:
        index = self.current_index()
        if index < 0:
            return
        new_index = qt.move(self.exam["questions"], index, delta)
        if new_index != index:
            self.mark_dirty()
            self.refresh_all(new_index + 1)

    # ------------------------------------------------------------ 檔案
    def confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        box = self.discard_box()
        box.exec()
        clicked = box.clickedButton()
        if clicked is box.button(QMessageBox.StandardButton.Save):
            return self.save()
        return clicked is box.button(QMessageBox.StandardButton.Discard)

    def discard_box(self) -> QMessageBox:
        box = QMessageBox(QMessageBox.Icon.Question, tr('尚未儲存'), tr('題庫有尚未儲存的變更，要先儲存嗎？'),
                          QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                          | QMessageBox.StandardButton.Cancel, self)
        for button, text in ((QMessageBox.StandardButton.Save, tr('儲存')), (QMessageBox.StandardButton.Discard, tr('不儲存')),
                             (QMessageBox.StandardButton.Cancel, tr('取消'))):
            box.button(button).setText(text)
        box.setDefaultButton(QMessageBox.StandardButton.Save)
        return box

    def set_exam(self, exam: dict, path: Path | None, dirty: bool = False) -> None:
        self.exam = exam
        self.path = path
        self.dirty = dirty
        if hasattr(self, "search"):
            self.search.blockSignals(True)  # 換題庫時清除搜尋
            self.search.clear()
            self.search.blockSignals(False)
        self.refresh_all(0)

    def new_exam(self) -> None:
        if self.confirm_discard():
            self.set_exam(E.new_exam(), None)

    def open_exam(self) -> None:
        if not self.confirm_discard():
            return
        name, _ = QFileDialog.getOpenFileName(self, tr('開啟題庫'), str(self.path.parent if self.path else Path.home()),
                                              tr(FILE_FILTER))
        if name:
            self.open_path(Path(name))

    def open_path(self, path: Path) -> bool:
        try:
            exam = load_exam(path)
        except ExamFileError as exc:
            QMessageBox.critical(self, tr('無法開啟'), str(exc))
            return False
        problems = E.validate_exam(exam)
        if problems:
            QMessageBox.warning(self, tr('題庫有問題'), tr('題庫已開啟，但有下列問題需要修正：\n') + qt.format_errors(problems[:20]))
        self.set_exam(exam, path)
        self.statusBar().showMessage(tr('已開啟 {0}', path), 5000)
        return True

    def open_sample(self) -> None:
        if not SAMPLE_PATH.is_file():
            QMessageBox.warning(self, tr('找不到示範題庫'), tr('找不到 {0}', SAMPLE_PATH))
            return
        if self.confirm_discard() and self.open_path(SAMPLE_PATH):
            # 示範題庫以未儲存的新題庫開啟，避免直接改到範例檔
            self.path = None
            self.dirty = True
            self._update_title()

    def save(self) -> bool:
        if self.path is None:
            return self.save_as()
        return self._write(self.path)

    def save_as(self) -> bool:
        start = str(self.path) if self.path else str(Path.home() / f"{self.exam['title'] or tr('題庫')}{FILE_EXTENSION}")
        name, _ = QFileDialog.getSaveFileName(self, tr('儲存題庫'), start, tr(FILE_FILTER))
        if not name:
            return False
        path = Path(name)
        if path.suffix.lower() != FILE_EXTENSION:
            path = path.with_suffix(FILE_EXTENSION)
        return self._write(path)

    def _write(self, path: Path) -> bool:
        problems = E.validate_exam(self.exam)
        if problems:
            QMessageBox.warning(self, tr('無法儲存'), tr('題庫屬性有誤，請先修正：\n') + qt.format_errors(problems[:20]))
            return False
        try:
            save_exam(path, self.exam)
        except OSError as exc:
            QMessageBox.critical(self, tr('儲存失敗'), tr('無法寫入 {0}：\n{1}', path, exc))
            return False
        self.path = path
        self.dirty = False
        self._update_title()
        states = [question_state(e["question"]) for e in self.exam["questions"]]
        note = ""
        skipped = len(states) - states.count("ready")
        if skipped:
            note = tr('（{0} 題為草稿或格式有誤，不會出題）', skipped)
        self.statusBar().showMessage(tr('已儲存 {0}{1}', path, note), 8000)
        return True

    def import_json(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, tr('匯入 JSON'), str(Path.home()), tr(JSON_FILTER))
        if not name:
            return
        try:
            kind, data = E.parse_import(Path(name).read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.critical(self, tr('匯入失敗'), tr('無法讀取檔案：{0}', exc))
            return
        except E.ImportErrorWithDetails as exc:
            QMessageBox.critical(self, tr('匯入失敗'), str(exc))
            return
        if kind == "exam":
            if self.confirm_discard():
                self.set_exam(data, None, dirty=True)
                self.statusBar().showMessage(tr('已匯入題庫；請另存為 .oes 檔。'), 8000)
            return
        renamed = E.merge_questions(self.exam, data)
        self.mark_dirty()
        self.refresh_all(len(self.exam["questions"]) - len(data) + 1)
        message = tr('已加入 {0} 題。', len(data))
        if renamed:
            message += tr('\n下列題目 ID 與現有題目重複，已改用新 ID：\n') + "\n".join(f"{a} → {b}" for a, b in renamed)
        QMessageBox.information(self, tr('匯入完成'), message)

    def export_exam_json(self) -> None:
        name, _ = QFileDialog.getSaveFileName(self, tr('匯出題庫 JSON'),
                                              str(Path.home() / f"{self.exam['title'] or 'exam'}.json"), tr(JSON_FILTER))
        if name:
            self._write_text(Path(name), E.export_exam_json(self.exam))

    def export_question_json(self) -> None:
        index = self.current_index()
        if index < 0:
            return
        question = self.exam["questions"][index]["question"]
        name, _ = QFileDialog.getSaveFileName(self, tr('匯出題目 JSON'), str(Path.home() / f"{question['id']}.json"),
                                              tr(JSON_FILTER))
        if name:
            self._write_text(Path(name), E.export_question_json(question))

    def export_pdf(self) -> None:
        from .pdf_export import PdfExportDialog, export_pdf
        dialog = PdfExportDialog(self)
        if not dialog.exec():
            return
        include_answers = dialog.answers.isChecked()
        base = re.sub(r'[<>:"/\\|?*]', "_", self.exam.get("title") or tr('題庫')).strip() or tr('題庫')
        suffix = tr('（含答案）') if include_answers else ""
        start = (self.path.parent if self.path else Path.home()) / f"{base}{suffix}.pdf"
        name, _ = QFileDialog.getSaveFileName(self, tr('匯出 PDF'), str(start), tr('PDF 檔 (*.pdf)'))
        if not name:
            return
        path = Path(name)
        if path.suffix.lower() != ".pdf":
            path = path.with_suffix(".pdf")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            pages = export_pdf(self.exam, path, include_answers=include_answers,
                               only_ready=dialog.ready.isChecked())
        except Exception as exc:  # noqa: BLE001 - 匯出失敗時告知使用者，不讓程式結束
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tr('匯出失敗'), str(exc))
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(tr('已匯出 {0}（{1} 頁）', path, pages), 8000)
        answer = QMessageBox.question(self, tr('匯出 PDF'), tr('已匯出 {0}（{1} 頁）。\n要開啟這個檔案嗎？', path, pages))
        if answer == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def compress_images(self) -> None:
        if not webp_supported():
            QMessageBox.warning(self, tr('壓縮題庫圖片'), tr('找不到 WebP 圖片元件，無法壓縮。'))
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            changed, before, after = recompress_exam(self.exam)
        finally:
            QApplication.restoreOverrideCursor()
        if not changed:
            QMessageBox.information(self, tr('壓縮題庫圖片'), tr('沒有可以再縮小的圖片。'))
            return
        self.mark_dirty()
        self.refresh_all(self.listing.currentRow())
        QMessageBox.information(
            self, tr('壓縮題庫圖片'),
            tr('已壓縮 {0} 張圖片：{1} → {2}（減少 {3}%），畫質不變。\n儲存題庫後生效。', changed, _size_text(before),
               _size_text(after), round((before - after) * 100 / before) if before else 0))

    def _write_text(self, path: Path, text: str) -> None:
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, tr('匯出失敗'), str(exc))
            return
        self.statusBar().showMessage(tr('已匯出 {0}（含正解，請勿直接提供給考生）', path), 8000)

    # ------------------------------------------------------------ 考試
    def start_exam(self) -> None:
        dialog = StartExamDialog(self.exam, self)
        if dialog.exec() and dialog.session is not None:
            run_session(dialog.session, self.store, self)

    def show_history(self) -> None:
        HistoryDialog(self.store, self.exam.get("id"), self).exec()

    def about(self) -> None:
        from .about import AboutDialog
        AboutDialog(self.store.path, self).exec()

    def closeEvent(self, event):  # noqa: N802
        if getattr(self, "_replaced", False):  # 切換語言時由新視窗接手，不詢問是否儲存
            if self in _WINDOWS:
                _WINDOWS.remove(self)
            event.accept()
            return
        if self.confirm_discard():
            event.accept()
        else:
            event.ignore()
