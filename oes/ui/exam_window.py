"""作答視窗、成績報告與檢討。"""
from __future__ import annotations

from ..i18n import tr

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import question_types as qt
from ..core import session as S
from ..storage.history import HistoryStore
from .renderers import QuestionView
from .theme import set_role
from .widgets import BAD_COLOR, MUTED_COLOR, OK_COLOR, plain_label

PROGRESS_TEXT = {"answered": "✔ 已作答", "partial": "◐ 部分作答", "unanswered": "○ 未作答"}


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:g}"


def _clock(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


class ExamWindow(QDialog):
    """作答（review=False）或檢討（review=True，唯讀並顯示正解）。"""

    finished_session = Signal(dict)

    def __init__(self, session: dict, store: HistoryStore, review: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.store = store
        self.review = review
        self.practice = session.get("mode") == "practice"
        self.view: QuestionView | None = None
        self._closing_ok = False
        self.setWindowTitle((tr('檢討：') if review else tr('作答：')) + session["examTitle"])
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.resize(980, 720)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        header = QFrame()
        header.setObjectName("examHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 12)
        top = QHBoxLayout()
        title = plain_label(session["examTitle"], selectable=False)
        title.setObjectName("sectionTitle")
        top.addWidget(title, 1)
        self.section = plain_label("", wrap=False, color=MUTED_COLOR, selectable=False)
        top.addWidget(self.section)
        top.addSpacing(8)
        self.position = QLabel()
        self.position.setObjectName("pill")
        top.addWidget(self.position)
        self.timer_label = QLabel()
        self.timer_label.setObjectName("pill")
        top.addWidget(self.timer_label)
        top.addSpacing(8)
        self.mark = QCheckBox(tr('標記此題'))
        self.mark.setEnabled(not review)
        self.mark.toggled.connect(self._mark_toggled)
        top.addWidget(self.mark)
        header_layout.addLayout(top)
        self.progress = QProgressBar()
        self.progress.setRange(0, len(session["questions"]))
        self.progress.setTextVisible(False)
        self.progress.setToolTip(tr('已完成作答的題數'))
        header_layout.addWidget(self.progress)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        layout.addWidget(self.scroll, 1)

        bottom = QHBoxLayout()
        self.prev_button = QPushButton(tr('◀ 上一題'))
        self.prev_button.clicked.connect(lambda: self.step(-1))
        self.next_button = QPushButton(tr('下一題 ▶'))
        self.next_button.clicked.connect(lambda: self.step(1))
        set_role(self.next_button, "primary")
        overview = QPushButton(tr('題目總覽'))
        overview.clicked.connect(self.show_overview)
        bottom.addWidget(self.prev_button)
        bottom.addWidget(self.next_button)
        bottom.addWidget(overview)
        if not review:
            clear = QPushButton(tr('清除本題作答'))
            clear.clicked.connect(lambda: self.view and self.view.clear())
            bottom.addWidget(clear)
        if self.practice and not review:
            self.show_answer_button = QPushButton(tr('顯示答案'))
            self.show_answer_button.clicked.connect(self.reveal_current)
            bottom.addWidget(self.show_answer_button)
        bottom.addStretch(1)
        if review:
            close = QPushButton(tr('關閉'))
            close.clicked.connect(self.accept)
            bottom.addWidget(close)
        else:
            save = QPushButton(tr('儲存並離開'))
            save.setToolTip(tr('保存目前進度，之後可從「成績與作答紀錄」繼續作答'))
            save.clicked.connect(self.save_and_leave)
            finish = QPushButton(tr('結束並評分'))
            finish.clicked.connect(self.finish_exam)
            set_role(finish, "danger")
            bottom.addWidget(save)
            bottom.addWidget(finish)
        layout.addLayout(bottom)

        for keys, delta in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda d=delta: self.step(d))

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.index = min(max(0, session.get("currentIndex", 0)), len(session["questions"]) - 1)
        self.go(self.index)
        if not review:
            self.timer.start()
        self._update_timer_label()

    # ------------------------------------------------------------ 導覽
    @property
    def entry(self) -> dict:
        return self.session["questions"][self.index]

    def _locked(self, index: int) -> bool:
        return not self.review and S.is_locked(self.session, self.session["questions"][index]["question"]["id"])

    def _neighbor(self, delta: int) -> int | None:
        """往 delta 方向最近、未鎖定的題目位置。"""
        index = self.index + delta
        while 0 <= index < len(self.session["questions"]):
            if not self._locked(index):
                return index
            index += delta
        return None

    def step(self, delta: int) -> None:
        target = self._neighbor(delta)
        if target is not None:
            self.go(target)

    def _leave_current(self) -> bool:
        """離開「無法返回」的題目前確認（尚未作答時），並鎖定該題。回傳是否可以離開。"""
        question_id = self.entry["question"]["id"]
        if self.review or not S.no_return(self.session, question_id) or S.is_locked(self.session, question_id):
            return True
        if S.question_progress(self.session, question_id) != "answered":
            answer = QMessageBox.question(self, tr('離開本題'),
                                          tr('本題尚未作答。離開後將無法返回本題，確定要離開嗎？'))
            if answer != QMessageBox.StandardButton.Yes:
                return False
        S.lock_question(self.session, question_id)
        return True

    def go(self, index: int) -> None:
        if not 0 <= index < len(self.session["questions"]) or self._locked(index):
            return
        if self.view is not None and index != self.index and not self._leave_current():
            return
        if not self.review and self.view is not None:
            self._save_progress()
        self.index = index
        if not self.review:
            self.session["currentIndex"] = index
        entry = self.entry
        question_id = entry["question"]["id"]
        self.view = QuestionView(entry["presented"], heading=tr('題目{0}', index + 1), case=entry.get("caseStudy"))
        self.view.set_answers(self.session["answers"].get(question_id, {}))
        if self.review:
            self.view.set_read_only(True)
            self.view.show_review(entry["question"], self._result_for(question_id))
        else:
            self.view.answersChanged.connect(self._answers_changed)
        self.scroll.setWidget(self.view)
        total = len(self.session["questions"])
        self.position.setText(tr('第 {0} ／ {1} 題', index + 1, total))
        self.section.setText(entry.get("sectionName") or "")
        self.mark.blockSignals(True)
        self.mark.setChecked(question_id in self.session["marked"])
        self.mark.blockSignals(False)
        no_return = not self.review and S.no_return(self.session, question_id)
        self.mark.setEnabled(not self.review and not no_return)  # 無法返回的題目不會出現在檢閱畫面，不能標記
        self.mark.setToolTip(tr('本題作答後無法返回，不能標記') if no_return else "")
        self.prev_button.setEnabled(self._neighbor(-1) is not None)
        self.next_button.setEnabled(self._neighbor(1) is not None)
        self._update_progress()

    def _update_progress(self) -> None:
        done = sum(1 for e in self.session["questions"]
                   if S.question_progress(self.session, e["question"]["id"]) == "answered")
        self.progress.setValue(done)
        self.progress.setToolTip(tr('已完成 {0} ／ {1} 題', done, len(self.session['questions'])))

    def _result_for(self, question_id: str) -> dict:
        question = S.find_question(self.session, question_id)["question"]
        return qt.grade(question, self.session["answers"].get(question_id, {}), allow_incomplete=True)

    def _answers_changed(self) -> None:
        S.set_answer(self.session, self.entry["question"]["id"], self.view.answers())
        self._update_progress()

    def _mark_toggled(self, checked: bool) -> None:
        S.toggle_mark(self.session, self.entry["question"]["id"], checked)

    def reveal_current(self) -> None:
        if self.view is not None:
            self.view.show_review(self.entry["question"], self._result_for(self.entry["question"]["id"]))

    def show_overview(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr('題目總覽'))
        dialog.resize(520, 480)
        layout = QVBoxLayout(dialog)
        layout.addWidget(plain_label(tr('雙擊題目可直接前往。'), color=MUTED_COLOR, selectable=False))
        listing = QListWidget()
        rows = {}
        if self.session.get("report"):
            rows = {r["questionId"]: r for r in self.session["report"]["questions"]}
        for i, entry in enumerate(self.session["questions"]):
            qid = entry["question"]["id"]
            if self.review and qid in rows:
                row = rows[qid]
                state = tr('得分 {0}／{1}', _fmt(row['score']), _fmt(row['maxScore']))
            else:
                state = tr(PROGRESS_TEXT[S.question_progress(self.session, qid)])
            flag = tr('\u3000🚩') if qid in self.session["marked"] else ""
            if self._locked(i):
                state = tr('🔒 已作答完畢，無法返回')
            item = QListWidgetItem(tr('題目{0}\u3000{1}{2}', i + 1, state, flag))
            item.setData(Qt.ItemDataRole.UserRole, i)
            if self._locked(i):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            listing.addItem(item)
        listing.setCurrentRow(self.index)
        listing.itemActivated.connect(lambda item: (dialog.accept(), self.go(item.data(Qt.ItemDataRole.UserRole))))
        layout.addWidget(listing)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    # ------------------------------------------------------------ 計時與保存
    def _tick(self) -> None:
        self.session["elapsedSeconds"] = int(self.session.get("elapsedSeconds", 0)) + 1
        self._update_timer_label()
        if self.session["elapsedSeconds"] % 30 == 0:
            self._save_progress()
        limit = self.session.get("timeLimitMinutes", 0) * 60
        if limit and self.session["elapsedSeconds"] >= limit:
            self.timer.stop()
            QMessageBox.information(self, tr('時間到'), tr('作答時間已到，系統將結束作答並評分。'))
            self._finish(confirmed=True)

    def _update_timer_label(self) -> None:
        elapsed = int(self.session.get("elapsedSeconds", 0))
        limit = self.session.get("timeLimitMinutes", 0) * 60
        if self.review:
            self.timer_label.setText(tr('用時 {0}', _clock(elapsed)))
        elif limit:
            remaining = limit - elapsed
            self.timer_label.setText(tr('剩餘 {0}', _clock(remaining)))
            name = "pillWarn" if remaining <= 300 else "pill"
            if self.timer_label.objectName() != name:
                self.timer_label.setObjectName(name)
                self.timer_label.style().unpolish(self.timer_label)
                self.timer_label.style().polish(self.timer_label)
        else:
            self.timer_label.setText(tr('已用 {0}', _clock(elapsed)))

    def _save_progress(self) -> None:
        if self.session["status"] == "in_progress":
            self.session["updatedAt"] = S.now_iso()
            self.store.save(self.session)

    def save_and_leave(self) -> None:
        self.timer.stop()
        self._save_progress()
        self._closing_ok = True
        QMessageBox.information(self, tr('已儲存'), tr('作答進度已儲存。可從「考試 → 成績與作答紀錄」繼續作答。'))
        self.accept()

    # ------------------------------------------------------------ 結算
    def finish_exam(self) -> None:
        self._finish(confirmed=False)

    def _finish(self, confirmed: bool) -> None:
        if not confirmed:
            missing = S.unanswered_count(self.session)
            text = tr('確定要結束作答並評分嗎？')
            if missing:
                text = tr('尚有 {0} 題未完成作答，未作答的部分以 0 分計。\n\n', missing) + text
            answer = QMessageBox.question(self, tr('結束作答'), text)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.timer.stop()
        S.finish(self.session)
        self.store.save(self.session)
        self._closing_ok = True
        self.finished_session.emit(self.session)
        self.accept()

    def closeEvent(self, event):  # noqa: N802
        if self.review or self._closing_ok or self.session["status"] != "in_progress":
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle(tr('離開作答'))
        box.setText(tr('要儲存目前進度嗎？'))
        save = box.addButton(tr('儲存並離開'), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr('繼續作答'), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is save:
            self.timer.stop()
            self._save_progress()
            event.accept()
        else:
            event.ignore()

    def reject(self):  # Esc 鍵也走離開確認
        if self.review or self._closing_ok:
            super().reject()
        else:
            self.close()


class ReportDialog(QDialog):
    """成績報告：總分、及格判定、章節分數與逐題明細；可檢討或重考。"""

    def __init__(self, session: dict, store: HistoryStore, parent: QWidget | None = None):
        super().__init__(parent)
        self.session = session
        self.store = store
        report = session["report"]
        self.setWindowTitle(tr('成績報告'))
        self.resize(860, 640)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(10)
        heading = plain_label(session["examTitle"])
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        info = []
        if session.get("examNumber"):
            info.append(tr('編號：{0}', session['examNumber']))
        if session.get("candidate"):
            info.append(tr('考生：{0}', session['candidate']))
        info.append(tr('模式：') + (tr('練習') if session.get("mode") == "practice" else tr('正式考試')))
        info.append(tr('完成時間：{0}', (session.get('finishedAt') or '')[:19].replace('T', ' ')))
        info.append(tr('用時：{0}', _clock(session.get('elapsedSeconds', 0))))
        layout.addWidget(plain_label(tr('\u3000').join(info), color=MUTED_COLOR))
        card = QFrame()
        card.setObjectName("scoreCard")
        card.setProperty("result", "pass" if report["passed"] else "fail")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(20, 14, 20, 14)
        color = OK_COLOR if report["passed"] else BAD_COLOR
        percent = plain_label(f"{report['percent']:g}%", bold=True, point_delta=18, color=color, selectable=False)
        card_layout.addWidget(percent)
        card_layout.addSpacing(18)
        details = QVBoxLayout()
        details.addWidget(plain_label(tr('通過 PASS') if report["passed"] else tr('未通過 FAIL'), bold=True, point_delta=4,
                                      color=color, selectable=False))
        details.addWidget(plain_label(
            tr('得分 {0} ／ {1} 分\u3000·\u3000及格標準 {2:g}%\u3000·\u3000完全答對 {3} ／ {4} 題', _fmt(report['score']), _fmt(report['maxScore']), report['passingScore'], report['correctQuestions'], report['totalQuestions']), selectable=False))
        card_layout.addLayout(details, 1)
        layout.addWidget(card)
        if report["sections"]:
            layout.addWidget(self._section_title(tr('章節分數')))
            table = QTableWidget(len(report["sections"]), 3)
            table.setHorizontalHeaderLabels([tr('章節'), tr('得分'), tr('百分比')])
            for r, section in enumerate(report["sections"]):
                for c, value in enumerate((section["name"], tr('{0} ／ {1}', _fmt(section['score']), _fmt(section['maxScore'])),
                                           f"{section['percent']:g}%")):
                    table.setItem(r, c, QTableWidgetItem(value))
            self._tidy(table)
            table.setMaximumHeight(36 + 30 * len(report["sections"]))
            layout.addWidget(table)
        layout.addWidget(self._section_title(tr('逐題明細')))
        table = QTableWidget(len(report["questions"]), 4)
        table.setHorizontalHeaderLabels([tr('題目'), tr('章節'), tr('得分'), tr('結果')])
        for r, row in enumerate(report["questions"]):
            if row["score"] is not None and row["score"] >= row["maxScore"]:
                result = tr('✔ 正確')
            elif len(row["unansweredIds"]) == row["totalParts"]:
                result = tr('○ 未作答')
            elif row["score"]:
                result = tr('◐ 部分正確（{0}／{1}）', row['correctCount'], row['totalParts'])
            else:
                result = tr('✘ 錯誤（{0}／{1}）', row['correctCount'], row['totalParts'])
            values = (tr('題目{0}', r + 1), row["sectionName"], tr('{0} ／ {1}', _fmt(row['score']), _fmt(row['maxScore'])),
                      result + (tr('\u3000🚩') if row["marked"] else ""))
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(value))
        self._tidy(table)
        table.doubleClicked.connect(lambda index: self.open_review(index.row()))
        layout.addWidget(table, 1)

        buttons = QHBoxLayout()
        review = QPushButton(tr('檢討答案'))
        set_role(review, "primary")
        review.clicked.connect(lambda: self.open_review(0))
        buttons.addWidget(review)
        for text, which in ((tr('重考答錯／未完成的題目'), "incorrect"), (tr('重考標記的題目'), "marked"), (tr('全部重考'), "all")):
            button = QPushButton(text)
            button.clicked.connect(lambda _=False, w=which: self.retake(w))
            buttons.addWidget(button)
        buttons.addStretch(1)
        close = QPushButton(tr('關閉'))
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _section_title(text: str) -> QLabel:
        label = plain_label(text, selectable=False)
        label.setObjectName("sectionTitle")
        return label

    @staticmethod
    def _tidy(table: QTableWidget) -> None:
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)

    def open_review(self, index: int) -> None:
        self.session["currentIndex"] = max(0, index)
        ExamWindow(self.session, self.store, review=True, parent=self).exec()

    def retake(self, which: str) -> None:
        try:
            fresh = S.retake(self.session, which)
        except ValueError as exc:
            QMessageBox.information(self, tr('重考'), str(exc))
            return
        self.store.save(fresh)
        self.accept()
        run_session(fresh, self.store, self.parentWidget())


def run_session(session: dict, store: HistoryStore, parent: QWidget | None) -> None:
    """開啟作答視窗；結算後顯示成績報告。"""
    store.save(session)
    window = ExamWindow(session, store, parent=parent)
    window.exec()
    if session["status"] == "finished":
        ReportDialog(session, store, parent).exec()
