"""介面測試（需要 PySide6；以 offscreen 模式執行，不會開出視窗）。沒有 PySide6 時整組略過。"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel
except ImportError:  # pragma: no cover - 依環境而定
    QApplication = None

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from tests.helpers import CORRECT_D, CORRECT_Y, fx

APP = None


def setUpModule():  # noqa: N802
    global APP
    if QApplication is None:
        raise unittest.SkipTest("未安裝 PySide6，略過介面測試")
    APP = QApplication.instance() or QApplication([])
    from oes.ui.i18n import install_translations
    from oes.ui.theme import apply_theme
    install_translations(APP)
    apply_theme(APP)  # 介面測試在正式主題與中文翻譯下執行


class ThemeTests(unittest.TestCase):
    def test_theme_assets(self):
        from pathlib import Path as P
        from oes.ui import theme
        css = theme.stylesheet()
        self.assertNotIn("{c[", css)
        self.assertIn("questionCard", css)
        for kind in ("new", "open", "save", "play", "history", "plus", "exam", "dot-ok", "dot-draft", "dot-error"):
            self.assertFalse(theme.icon(kind).isNull(), kind)
        for path in theme._arrow_files().values():
            self.assertTrue(P(path).is_file())
        # 套用樣式表後 Qt 會把 Fusion 包在樣式表樣式裡，名稱可能是空字串；改檢查樣式表與調色盤已套用
        self.assertIn("questionCard", APP.styleSheet())
        self.assertEqual(APP.palette().color(APP.palette().ColorRole.Window).name(), theme.COLORS["bg"])

    def test_switch_dark_and_light(self):
        import os
        import tempfile as T
        from oes.storage.history import HistoryStore
        from oes.ui import settings, theme
        from oes.ui.main_window import MainWindow
        with T.TemporaryDirectory() as tmp:
            old = os.environ.get("OES_DATA_DIR")
            os.environ["OES_DATA_DIR"] = tmp
            try:
                win = MainWindow(HistoryStore(Path(tmp) / "h.db"))
                self.assertEqual(win.act_toggle_theme.text(), "深色主題")
                win.toggle_theme()
                self.assertEqual(theme.current_theme, "dark")
                self.assertEqual(theme.COLORS["bg"], theme.THEMES["dark"]["bg"])
                self.assertIn(theme.THEMES["dark"]["surface"], APP.styleSheet())
                self.assertEqual(APP.palette().color(APP.palette().ColorRole.Window).name(), theme.THEMES["dark"]["bg"])
                self.assertTrue(win.theme_actions["dark"].isChecked())
                self.assertEqual(win.act_toggle_theme.text(), "淺色主題")
                self.assertEqual(settings.load().get("theme"), "dark")
                from oes.ui.widgets import BAD_COLOR
                self.assertEqual(f"{BAD_COLOR}", theme.THEMES["dark"]["bad"])
                win.set_theme("light")
                self.assertEqual(settings.load().get("theme"), "light")
                self.assertEqual(f"{BAD_COLOR}", theme.THEMES["light"]["bad"])
                win.dirty = False
            finally:
                theme.apply_theme(APP, "light")
                if old is None:
                    os.environ.pop("OES_DATA_DIR", None)
                else:
                    os.environ["OES_DATA_DIR"] = old

    def test_standard_buttons_in_chinese(self):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtWidgets import QDialogButtonBox, QMessageBox
        tr = QCoreApplication.translate
        self.assertEqual(tr("QPlatformTheme", "Save").replace("(&S)", ""), "儲存")
        self.assertIn(tr("QPlatformTheme", "Cancel"), ("取消",))
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.assertIn("確定", box.button(QDialogButtonBox.StandardButton.Ok).text())
        self.assertIn("取消", box.button(QDialogButtonBox.StandardButton.Cancel).text())
        question = QMessageBox(QMessageBox.Icon.Question, "t", "q",
                               QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        self.assertIn("是", question.button(QMessageBox.StandardButton.Yes).text())
        self.assertIn("否", question.button(QMessageBox.StandardButton.No).text())

    def test_unsaved_dialog_buttons(self):
        import tempfile as T
        from PySide6.QtWidgets import QMessageBox
        from oes.storage.history import HistoryStore
        from oes.ui.main_window import MainWindow
        with T.TemporaryDirectory() as tmp:
            win = MainWindow(HistoryStore(Path(tmp) / "h.db"))
            box = win.discard_box()
            texts = [box.button(b).text() for b in (QMessageBox.StandardButton.Save, QMessageBox.StandardButton.Discard,
                                                    QMessageBox.StandardButton.Cancel)]
            self.assertEqual(texts, ["儲存", "不儲存", "取消"])

    def test_switch_language_rebuilds_window(self):
        import os
        import tempfile as T
        from PySide6.QtWidgets import QDialogButtonBox, QToolBar
        from oes import i18n
        from oes.storage.history import HistoryStore
        from oes.ui import settings
        from oes.ui.i18n import install_translations
        from oes.ui.main_window import MainWindow
        with T.TemporaryDirectory() as tmp:
            old = os.environ.get("OES_DATA_DIR")
            os.environ["OES_DATA_DIR"] = tmp
            try:
                win = MainWindow(HistoryStore(Path(tmp) / "h.db"))
                self.assertEqual(win.exam["title"], "未命名題庫")
                E.add_question(win.exam, "yes_no_matrix")
                win.refresh_all(1)
                win.dirty = True
                en = win.set_language("en")
                self.assertIsNot(en, win)
                self.assertEqual(i18n.get_language(), "en")
                self.assertEqual(settings.load().get("language"), "en")
                self.assertEqual([m.title() for m in (a.menu() for a in en.menuBar().actions())][0], "&File")
                self.assertIn("New exam", [a.text() for a in en.findChild(QToolBar).actions()])
                self.assertEqual(en.listing.item(1).text(), "Question 1")
                self.assertEqual(en.listing.currentRow(), 1)
                self.assertTrue(en.dirty)
                self.assertEqual(en.exam["title"], "Untitled exam")  # 未改過的預設標題跟著換語言
                self.assertIs(en.exam, win.exam)
                box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
                self.assertEqual(box.button(QDialogButtonBox.StandardButton.Ok).text().replace("&", ""), "OK")
                self.assertTrue(en.language_actions["en"].isChecked())
                zh = en.set_language("zh_TW")
                self.assertEqual(zh.listing.item(1).text(), "題目1")
                box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
                self.assertIn("確定", box.button(QDialogButtonBox.StandardButton.Ok).text())
                zh.dirty = False
            finally:
                i18n.set_language("zh_TW")
                install_translations(APP, "zh_TW")
                if old is None:
                    os.environ.pop("OES_DATA_DIR", None)
                else:
                    os.environ["OES_DATA_DIR"] = old

    def test_english_screens_build(self):
        import tempfile as T
        from oes import i18n
        from oes.storage.history import HistoryStore
        from oes.ui.editors import QuestionEditor
        from oes.ui.exam_window import ExamWindow, ReportDialog
        from oes.ui.renderers import QuestionView
        i18n.set_language("en")
        try:
            for t in C.TYPES:
                entry = {"sectionId": None, "question": C.new_question(t, "x1")}
                QuestionEditor(entry, [{"id": "sec1", "name": "A"}], cases=[{"id": "case1", "name": "C", "text": ""}])
            view = QuestionView(C.for_candidate(fx("demoYesNo")), heading="Question 1")
            texts = [l.text() for l in view.findChildren(QLabel)]
            self.assertIn("Statements", texts)
            ex = E.new_exam()
            ex["questions"].append({"sectionId": None, "question": fx("demoYesNo")})
            session = S.build_session(ex)
            with T.TemporaryDirectory() as tmp:
                store = HistoryStore(Path(tmp) / "h.db")
                window = ExamWindow(session, store)
                self.assertEqual(window.position.text(), "Question 1 / 1")
                window._finish(confirmed=True)
                ReportDialog(session, store)
        finally:
            i18n.set_language("zh_TW")

    def test_packaged_self_test_passes(self):
        import tempfile as T
        from oes import i18n
        from oes.ui import theme
        from oes.ui.i18n import install_translations
        from oes.ui.selftest import run_self_test
        with T.TemporaryDirectory() as tmp:
            out = Path(tmp) / "selftest.txt"
            try:
                code = run_self_test(str(out))
            finally:
                i18n.set_language("zh_TW")
                install_translations(APP, "zh_TW")
                theme.apply_theme(APP, "light")
            text = out.read_text(encoding="utf-8")
            self.assertEqual(code, 0, text)
            self.assertIn("RESULT: PASS", text)
            self.assertIn("開啟示範題庫", text)

    def test_settings_roundtrip(self):
        import tempfile as T
        from oes.ui import settings
        with T.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            self.assertEqual(settings.load(path), {})
            self.assertTrue(settings.save({"theme": "dark"}, path))
            self.assertTrue(settings.save({"other": 1}, path))
            self.assertEqual(settings.load(path), {"theme": "dark", "other": 1})
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(settings.load(path), {})

    def test_report_card_and_exam_header(self):
        import tempfile as T
        from oes.storage.history import HistoryStore
        from oes.ui.exam_window import ExamWindow, ReportDialog
        ex = E.new_exam()
        ex["questions"].append({"sectionId": None, "question": fx("demoYesNo")})
        session = S.build_session(ex)
        with T.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp) / "h.db")
            window = ExamWindow(session, store)
            self.assertEqual(window.progress.value(), 0)
            window.view.answer_widget.set_answers(CORRECT_Y)
            window.view.answer_widget.answersChanged.emit()
            self.assertEqual(window.progress.value(), 1)
            window._finish(confirmed=True)
            dialog = ReportDialog(session, store)
            from PySide6.QtWidgets import QFrame
            card = dialog.findChild(QFrame, "scoreCard")
            self.assertEqual(card.property("result"), "pass")


def renderer(question):
    from oes.ui.renderers import create_renderer
    return create_renderer(C.for_candidate(question))


class DropdownRendererTests(unittest.TestCase):
    def test_initially_unanswered_and_independent(self):
        w = renderer(fx("imageDropdown"))
        self.assertEqual(w.answers(), {})
        self.assertTrue(all(c.currentIndex() == 0 and c.currentText() == "請選擇答案" for c in w.combos.values()))
        self.assertEqual(w.combos["f1"].itemText(1), "每小時")
        self.assertEqual(w.combos["f2"].itemText(1), "每天")
        w.combos["f1"].setCurrentIndex(2)
        self.assertEqual(w.answers(), {"f1": "o2"})
        self.assertEqual(w.combos["f2"].currentIndex(), 0)

    def test_blank_label_hidden(self):
        q = fx("demoDropdown")
        q["items"][0]["label"] = ""
        w = renderer(q)
        w.show()
        first, second = q["items"][0]["id"], q["items"][1]["id"]
        self.assertTrue(w.combos[first].isVisible())
        self.assertEqual(w.combos[first].accessibleName(), "欄位 1")
        labels = [lab for lab in w.findChildren(QLabel) if lab.buddy() is not None]
        visible = {lab.buddy().objectName(): lab.isVisible() for lab in labels}
        self.assertFalse(visible[w.combos[first].objectName()])
        self.assertTrue(visible[w.combos[second].objectName()])

    def test_script_layout(self):
        from PySide6.QtWidgets import QApplication
        from tests.test_basic_types import script_dropdown
        w = renderer(script_dropdown())
        w.resize(900, 300)
        w.show()
        QApplication.processEvents()
        labels = {lab.text(): lab for lab in w.findChildren(QLabel) if lab.isVisible()}
        for text in ("$a = 'x'", "$b =", "Path\\To -Force", "$c = Done $b"):
            self.assertIn(text, labels)
        first, second = w.combos["item1"], w.combos["item2"]
        self.assertLess(labels["$a = 'x'"].geometry().bottom(), first.geometry().top())   # 獨立一行在選單上方
        self.assertLess(labels["$b ="].geometry().right(), first.geometry().left())        # 同一行在選單左邊
        suffix = labels["Path\\To -Force"]
        self.assertLess(second.geometry().right(), suffix.geometry().left())              # 後文字在選單右邊
        self.assertGreater(labels["$c = Done $b"].geometry().top(), second.geometry().bottom())
        self.assertEqual(second.accessibleName(), "Path\\To -Force")
        for widget in (suffix, first, labels["$a = 'x'"]):
            self.assertTrue(widget.font().fixedPitch())
        self.assertFalse(labels["$b ="].font().bold())
        first.setCurrentIndex(2)
        second.setCurrentIndex(1)
        self.assertEqual(w.answers(), {"item1": "o2", "item2": "o1"})

    def test_script_editor(self):
        from PySide6.QtWidgets import QCheckBox
        from oes.ui.editors import AroundText, QuestionEditor
        q = fx("demoDropdown")
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        [b for b in editor.body.findChildren(QCheckBox) if "程式碼字型" in b.text()][0].setChecked(True)
        around = editor.body.findChildren(AroundText)[0]
        self.assertEqual(around.before.text(), q["items"][0]["label"])
        around.above.setPlainText("$a = 1")
        around.before.setText("$b =")
        around.before.textEdited.emit("$b =")
        around.after.setText("-Force")
        around.after.textEdited.emit("-Force")
        around.below.setPlainText("$s = 1\n$t = 2")
        item = q["items"][0]
        self.assertEqual((q["codeFont"], item["label"], item["suffix"]), (True, "$a = 1\n$b =", "-Force\n$s = 1\n$t = 2"))
        around.after.setText("")
        around.after.textEdited.emit("")
        around.below.setPlainText("")
        self.assertNotIn("suffix", item)
        self.assertEqual(C.validate(q), [])

    def test_split_join_around(self):
        from oes.ui.editors import join_around, split_around
        cases = [("欄位 1", "", ("", "欄位 1", "", "")),
                 ("$a\n$b =", "-Force\n$s", ("$a", "$b =", "-Force", "$s")),
                 ("Step 1:", "\nStep 2: 固定", ("", "Step 1:", "", "Step 2: 固定")),
                 ("", "", ("", "", "", ""))]
        for label, suffix, parts in cases:
            with self.subTest(label=label, suffix=suffix):
                self.assertEqual(split_around(label, suffix), parts)
                self.assertEqual(join_around(*parts), (label, suffix))

    def test_restore_without_signal(self):
        w = renderer(fx("demoDropdown"))
        hits = []
        w.answersChanged.connect(lambda: hits.append(1))
        w.set_answers(CORRECT_D)
        self.assertEqual(w.answers(), CORRECT_D)
        self.assertEqual(hits, [])

    def test_keyboard_selects(self):
        w = renderer(fx("demoDropdown"))
        w.show()
        combo = w.combos["sum"]
        combo.setFocus()
        QTest.keyClick(combo, Qt.Key.Key_Down)
        self.assertEqual(w.answers(), {"sum": "o1"})


class YesNoRendererTests(unittest.TestCase):
    def test_rows_exclusive_and_independent(self):
        w = renderer(fx("demoYesNo"))
        self.assertEqual(w.answers(), {})
        w.no["s2"].click()
        self.assertEqual(w.answers(), {"s2": False})
        w.yes["s1"].click()
        w.yes["s2"].click()
        self.assertEqual(w.answers(), {"s1": True, "s2": True})
        self.assertFalse(w.no["s2"].isChecked())
        self.assertEqual(w.groups["s1"].objectName(), "demo-yes-no:s1")

    def test_clear_and_restore_false(self):
        w = renderer(fx("demoYesNo"))
        w.set_answers(CORRECT_Y)
        self.assertEqual(w.answers(), CORRECT_Y)
        self.assertIs(w.answers()["s2"], False)
        w.clear()
        self.assertEqual(w.answers(), {})

    def test_keyboard_space(self):
        w = renderer(fx("demoYesNo"))
        w.show()
        w.no["s3"].setFocus()
        QTest.keyClick(w.no["s3"], Qt.Key.Key_Space)
        self.assertEqual(w.answers(), {"s3": False})


class OtherRendererTests(unittest.TestCase):
    def test_multiple_choice_limit(self):
        q = C.new_question("multiple_choice", "mc")
        q.update(selectMode="multiple", checkNumberSelected=True, correctAnswer=["o1", "o2"])
        w = renderer(q)
        w.buttons["o1"].click()
        w.buttons["o3"].click()
        self.assertFalse(w.buttons["o4"].isEnabled())
        self.assertEqual(w.answers(), {"selected": ["o1", "o3"]})

    def test_single_choice(self):
        q = C.new_question("multiple_choice", "mc")
        w = renderer(q)
        w.buttons["o1"].click()
        w.buttons["o2"].click()
        self.assertEqual(w.answers(), {"selected": ["o2"]})
        w.clear()
        self.assertEqual(w.answers(), {})

    def test_fill(self):
        w = renderer(C.new_question("fill_in_blank", "f"))
        w.edit.setText("  ")
        self.assertEqual(w.answers(), {})
        w.edit.setText("abc")
        self.assertEqual(w.answers(), {"text": "abc"})

    def test_script_text_is_plain(self):
        from oes.ui.renderers import QuestionView
        q = fx("demoYesNo")
        q["prompt"] = "<script>alert(1)</script><b>粗體</b>"
        q["items"][0]["text"] = "<img src=x onerror=alert(1)>"
        view = QuestionView(C.for_candidate(q))
        labels = [l for l in view.findChildren(QLabel) if "<" in l.text()]
        self.assertGreaterEqual(len(labels), 2)
        self.assertTrue(all(l.textFormat() == Qt.TextFormat.PlainText for l in labels))


class LongTextLayoutTests(unittest.TestCase):
    """沒有空白的長字串也要依視窗寬度換行，Yes／No 欄位不能被擠出畫面。"""

    def test_long_unbroken_text_wraps(self):
        from oes.ui.renderers import QuestionView
        q = fx("demoYesNo")
        q["title"] = "a" * 120
        q["prompt"] = "s" * 400
        q["items"][0]["text"] = "x" * 400
        view = QuestionView(C.for_candidate(q))
        self.assertLess(view.minimumSizeHint().width(), 500)
        view.resize(500, 900)
        view.show()
        QApplication.processEvents()
        widget = view.answer_widget
        for button in (widget.yes["s1"], widget.no["s1"]):
            right = button.mapTo(view, button.rect().topRight()).x()
            self.assertLessEqual(right, 500)
        texts = [l.text() for l in view.findChildren(QLabel)]
        self.assertIn("x" * 400, texts)  # text() 仍回傳原文，不含零寬空白

    def test_breakable_keeps_short_words(self):
        from oes.ui.widgets import ZWSP, breakable
        self.assertEqual(breakable("short text"), "short text")
        self.assertEqual(breakable("a" * 20).replace(ZWSP, ""), "a" * 20)
        self.assertIn(ZWSP, breakable("a" * 20))


class PromptImageTests(unittest.TestCase):
    def setUp(self):
        from tests.test_images import with_image
        self.question = with_image()

    def test_load_and_serialize_roundtrip(self):
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        pool = ImagePool(self.question["images"])
        editor = PromptEditor(self.question["prompt"], pool)
        prompt = editor.edit.serialize()
        self.assertEqual(prompt, self.question["prompt"])
        self.assertEqual(pool.collect(C.image_refs(prompt)), self.question["images"])

    def test_insert_image_updates_question(self):
        from PySide6.QtGui import QColor, QImage, QTextCursor
        from oes.ui.editors import QuestionEditor
        entry = {"sectionId": None, "question": fx("demoYesNo")}
        editor = QuestionEditor(entry, [])
        image = QImage(40, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        editor.prompt.edit.moveCursor(QTextCursor.MoveOperation.End)
        image_id = editor.prompt.edit.insert_qimage(image)
        q = entry["question"]
        self.assertIn("{{image:%s}}" % image_id, q["prompt"])
        self.assertEqual([i["id"] for i in q["images"]], [image_id])
        self.assertEqual(C.validate(q), [])
        editor.prompt.edit.setPlainText("只剩文字")
        self.assertNotIn("images", q)
        self.assertEqual(q["prompt"], "只剩文字")

    def test_resize_image(self):
        from PySide6.QtGui import QColor, QImage, QTextCursor
        from oes.ui.editors import QuestionEditor
        entry = {"sectionId": None, "question": fx("demoYesNo")}
        editor = QuestionEditor(entry, [])
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        edit = editor.prompt.edit
        edit.moveCursor(QTextCursor.MoveOperation.End)
        image_id = edit.insert_qimage(image)
        edit.resize_image(image_id, 100)
        q = entry["question"]
        self.assertEqual(q["images"][0]["width"], 100)
        self.assertEqual(C.validate(q), [])
        fmt = edit._image_format(image_id)
        self.assertEqual((round(fmt.width()), round(fmt.height())), (100, 50))
        menu = edit.image_size_menu(image_id)
        labels = [a.text() for a in menu.actions()]
        self.assertTrue(any("50%" in t and a.isChecked() for t, a in zip(labels, menu.actions())))
        edit.resize_image(image_id, 400)  # 可放大超過原尺寸
        self.assertEqual(q["images"][0]["width"], 400)
        edit.resize_image(image_id, None)  # 恢復原尺寸時不存 width
        self.assertNotIn("width", q["images"][0])
        # 重新開啟時保留寬度
        q["images"][0]["width"] = 120
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        pool = ImagePool(q["images"])
        again = PromptEditor(q["prompt"], pool)
        self.assertEqual(pool.width(image_id), 120)
        self.assertEqual(round(again.edit._image_format(image_id).width()), 120)

    def test_drag_resize_image(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QColor, QImage, QMouseEvent
        from PySide6.QtWidgets import QApplication
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        pool = ImagePool()
        editor = PromptEditor("看圖：", pool)
        editor.resize(800, 500)
        editor.show()
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        edit = editor.edit
        image_id = edit.insert_qimage(image)
        QApplication.processEvents()
        rects = edit.image_rects()
        self.assertEqual(len(rects), 1)
        rect = rects[0][1]
        self.assertEqual((round(rect.width()), round(rect.height())), (200, 100))
        self.assertGreaterEqual(rect.top(), 0)
        corner = QPointF(rect.right() - 3, rect.bottom() - 3)
        self.assertEqual(edit.handle_at(corner)[2], "corner")
        self.assertIsNone(edit.handle_at(rect.center()))
        changes = []
        editor.changed.connect(changes.append)

        def send(kind, point, button=Qt.MouseButton.LeftButton):
            buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            event = QMouseEvent(kind, point, edit.viewport().mapToGlobal(point), button, buttons,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(edit.viewport(), event)

        send(QEvent.Type.MouseButtonPress, corner)
        moved = QPointF(corner.x() - 50, corner.y())
        send(QEvent.Type.MouseMove, moved, Qt.MouseButton.NoButton)
        self.assertNotIn("width", pool.images[image_id])  # 放開前只更新畫面
        send(QEvent.Type.MouseButtonRelease, moved)
        self.assertEqual(pool.width(image_id), 150)
        self.assertTrue(changes)
        self.assertEqual(round(edit.image_rects()[0][1].width()), 150)
        self.assertEqual(round(edit.image_rects()[0][1].height()), 75)
        editor.close()

    def _image_editor(self):
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        pool = ImagePool()
        editor = PromptEditor("看圖：", pool)
        editor.resize(800, 600)
        editor.show()
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        image_id = editor.edit.insert_qimage(image)
        editor.edit.insertPlainText("後面的文字")
        QApplication.processEvents()
        return editor, pool, image_id

    def test_right_click_resize_entry(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QTextCursor
        editor, pool, image_id = self._image_editor()
        edit = editor.edit
        rect = edit.image_rects()[0][1]
        on_image = rect.center().toPoint()
        self.assertEqual(edit.image_at(on_image), image_id)
        menu = edit.context_menu(on_image)
        self.assertEqual(menu.actions()[0].text(), "調整圖片大小…")
        self.assertEqual(menu.actions()[1].menu().title(), "圖片大小")
        away = QPoint(int(rect.right()) + 200, int(rect.bottom()) + 120)
        self.assertIsNone(edit.image_at(away))
        self.assertNotEqual(edit.context_menu(away).actions()[0].text(), "調整圖片大小…")
        # 先選取圖片，再在其他地方按右鍵
        cursor = QTextCursor(edit.document())
        text = edit.document().toPlainText()
        cursor.setPosition(text.index("\ufffc"))
        cursor.setPosition(text.index("\ufffc") + 1, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)
        self.assertEqual(edit.selected_image(), image_id)
        self.assertEqual(edit.context_menu(away).actions()[0].text(), "調整圖片大小…")
        editor.close()

    def test_copy_paste_images_between_editors(self):
        from PySide6.QtGui import QColor, QImage, QTextCursor
        from oes.ui.prompt_editor import CLIP_MIME, ImagePool, PromptEditor
        pool = ImagePool()
        source = PromptEditor("", pool)
        image = QImage(60, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        source.edit.insertPlainText("前")
        image_id = source.edit.insert_qimage(image)
        source.edit.resize_image(image_id, 120)
        source.edit.insertPlainText("後")
        source.edit.selectAll()
        mime = source.edit.createMimeDataFromSelection()
        self.assertTrue(mime.hasFormat(CLIP_MIME))
        self.assertEqual(mime.text().replace("\n", ""), "前後")
        target_pool = ImagePool()
        target = PromptEditor("已有文字", target_pool)
        target.edit.moveCursor(QTextCursor.MoveOperation.End)
        target.edit.insertFromMimeData(mime)
        text = target.edit.serialize()
        refs = C.image_refs(text)
        self.assertEqual(len(refs), 1)
        self.assertTrue(text.startswith("已有文字前"))
        self.assertEqual(target_pool.width(refs[0]), 120)
        self.assertEqual(target_pool.images[refs[0]]["data"], pool.images[image_id]["data"])
        # 只選取一張圖片：另附圖片本身，可貼到其他程式
        source.edit.copy_image(image_id)
        self.assertEqual(source.edit.selected_image(), image_id)
        only = source.edit.createMimeDataFromSelection()
        self.assertTrue(only.hasImage())
        self.assertTrue(only.hasFormat(CLIP_MIME))
        # 貼到選項框（不支援文字格式）也保留圖片
        from oes.ui.prompt_editor import OptionTextEdit
        option = OptionTextEdit("", target_pool)
        option.edit.insertFromMimeData(only)
        self.assertEqual(len(C.image_refs(option.edit.serialize())), 1)

    def test_copy_keeps_bold(self):
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        source = PromptEditor("一般{{b}}粗體{{/b}}", ImagePool())
        source.edit.selectAll()
        target = PromptEditor("", ImagePool())
        target.edit.insertFromMimeData(source.edit.createMimeDataFromSelection())
        self.assertEqual(target.edit.serialize(), "一般{{b}}粗體{{/b}}")

    def test_context_menu_has_copy_image(self):
        editor, pool, image_id = self._image_editor()
        rect = editor.edit.image_rects()[0][1]
        texts = [a.text() for a in editor.edit.context_menu(rect.center().toPoint()).actions()]
        self.assertIn("複製圖片", texts)
        editor.close()

    def test_resize_editor_height(self):
        from unittest import mock
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        from PySide6.QtWidgets import QApplication
        from oes.ui import prompt_editor as P
        with mock.patch("oes.ui.settings.load", return_value={"editorHeights": {"prompt": 260}}):
            editor = P.PromptEditor("文字", P.ImagePool())
        self.assertEqual(editor.edit.height(), 260)
        grip = editor.grip

        def send(kind, y):
            point = QPointF(5, 5)
            buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
            event = QMouseEvent(kind, point, point, QPointF(100, y), Qt.MouseButton.LeftButton, buttons,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(grip, event)

        with mock.patch.object(P, "remember_height") as remember:
            send(QEvent.Type.MouseButtonPress, 500)
            send(QEvent.Type.MouseMove, 620)
            self.assertEqual(editor.edit.height(), 380)
            send(QEvent.Type.MouseMove, 0)
            self.assertEqual(editor.edit.height(), P.HeightGrip.MIN_HEIGHT)  # 不會小於下限
            send(QEvent.Type.MouseMove, 540)
            send(QEvent.Type.MouseButtonRelease, 540)
        remember.assert_called_once_with("prompt", 300)
        with mock.patch("oes.ui.settings.load", return_value={"editorHeights": {"prompt": "bad"}}):
            self.assertEqual(P.saved_height("prompt", 200), 200)

    def test_image_size_dialog(self):
        from unittest import mock
        from PySide6.QtCore import QSize
        from oes.ui.prompt_editor import ImageSizeDialog
        dialog = ImageSizeDialog(QSize(200, 100), None)
        self.assertEqual((dialog.width_box.value(), dialog.height_box.value()), (200, 100))
        self.assertIsNone(dialog.result_width())
        dialog.height_box.setValue(50)
        self.assertEqual((dialog.width_box.value(), dialog.result_width()), (100, 100))
        dialog.width_box.setValue(300)
        self.assertEqual(dialog.height_box.value(), 150)
        self.assertEqual(ImageSizeDialog(QSize(200, 100), 120).width_box.value(), 120)
        editor, pool, image_id = self._image_editor()

        def fake_exec(dlg):
            dlg.height_box.setValue(25)
            return 1
        with mock.patch.object(ImageSizeDialog, "exec", fake_exec):
            editor.edit.ask_image_width(image_id)
        self.assertEqual(pool.width(image_id), 50)
        self.assertEqual(round(editor.edit.image_rects()[0][1].height()), 25)
        editor.close()

    def test_image_view_width(self):
        from PySide6.QtGui import QColor, QImage
        from oes.ui.widgets import ImageView
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("green"))
        self.assertEqual(ImageView(image).sizeHint().width(), 200)
        self.assertEqual(ImageView(image, width=80).sizeHint().height(), 40)
        self.assertEqual(ImageView(image, width=400).heightForWidth(1000), 200)  # 放大
        self.assertEqual(ImageView(image, width=400).heightForWidth(300), 150)   # 仍隨可用寬度縮小
        self.assertEqual(ImageView(image, width=400, max_width=100).heightForWidth(1000), 50)

    def test_paste_html_as_plain_text(self):
        from PySide6.QtCore import QMimeData
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        editor = PromptEditor("", ImagePool())
        mime = QMimeData()
        mime.setHtml("<b>粗體</b>")
        mime.setText("粗體")
        editor.edit.insertFromMimeData(mime)
        self.assertEqual(editor.edit.serialize(), "粗體")

    def test_no_insert_image_buttons(self):
        from PySide6.QtWidgets import QAbstractButton
        from oes.ui.editors import QuestionEditor
        q = C.new_question("multiple_choice", "mc")
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        texts = [b.text() for b in editor.findChildren(QAbstractButton)]
        self.assertNotIn("插入圖片…", texts)
        self.assertNotIn("🖼", texts)

    def test_label_renamed(self):
        from oes.ui.editors import QuestionEditor
        editor = QuestionEditor({"sectionId": None, "question": fx("demoYesNo")}, [])
        texts = [l.text() for l in editor.findChildren(QLabel)]
        self.assertIn("題目：", texts)
        self.assertNotIn("題幹：", texts)

    def test_view_shows_image_scaled(self):
        from oes.ui.renderers import QuestionView
        from oes.ui.widgets import ImageView
        view = QuestionView(C.for_candidate(self.question), heading="題目1")
        images = view.findChildren(ImageView)
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].heightForWidth(500), 1)  # 1x1 圖片不放大
        texts = [l.text() for l in view.findChildren(QLabel)]
        self.assertIn("請看下圖：", texts)
        self.assertFalse(any("{{image" in t for t in texts))


class PromptFormatTests(unittest.TestCase):
    def editor(self, text=""):
        from oes.ui.prompt_editor import ImagePool, PromptEditor
        return PromptEditor(text, ImagePool())

    def select(self, edit, start, end):
        from PySide6.QtGui import QTextCursor
        cursor = edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        edit.setTextCursor(cursor)

    def test_roundtrip(self):
        text = "前言{{b}}粗體{{/b}}中間{{size:18}}大字{{b}}又粗{{/b}}{{/size}}\n第二行"
        self.assertEqual(self.editor(text).edit.serialize(), text)

    def test_bold_and_size_on_selection(self):
        editor = self.editor("請選出正確答案")
        changes = []
        editor.changed.connect(changes.append)
        self.select(editor.edit, 2, 4)
        editor.edit.set_bold(True)
        self.assertEqual(editor.edit.serialize(), "請選{{b}}出正{{/b}}確答案")
        self.assertTrue(changes)
        self.select(editor.edit, 0, 2)
        editor.edit.set_size(20)
        self.assertEqual(editor.edit.serialize(), "{{size:20}}請選{{/size}}{{b}}出正{{/b}}確答案")
        editor.edit.set_size(None)
        self.select(editor.edit, 2, 4)
        editor.edit.set_bold(False)
        self.assertEqual(editor.edit.serialize(), "請選出正確答案")

    def test_ctrl_b_and_toolbar_sync(self):
        editor = self.editor("abcd")
        editor.show()
        self.select(editor.edit, 0, 2)
        QTest.keyClick(editor.edit, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(editor.edit.serialize(), "{{b}}ab{{/b}}cd")
        self.assertTrue(editor.bold_button.isChecked())
        editor.size_combo.setCurrentIndex(editor.size_combo.findData(24))
        editor._size_chosen(editor.size_combo.currentIndex())
        self.assertIn("{{size:24}}", editor.edit.serialize())
        self.select(editor.edit, 3, 3)
        self.assertFalse(editor.bold_button.isChecked())
        self.assertEqual(editor.size_combo.currentIndex(), 0)
        editor.close()

    def test_view_renders_safely(self):
        from oes.ui.renderers import QuestionView
        from oes.ui.widgets import RichLabel
        q = fx("demoYesNo")
        q["prompt"] = "{{b}}<script>alert(1)</script>{{/b}} 一般 {{size:20}}大{{/size}}"
        view = QuestionView(C.for_candidate(q), heading="題目1")
        labels = view.findChildren(RichLabel)
        self.assertEqual(len(labels), 1)
        html = labels[0].html().replace("\u200b", "")  # 去掉長字串換行用的零寬空白再比對
        self.assertIn("<b>&lt;script&gt;", html)
        self.assertIn("font-size:20pt", html)
        self.assertNotIn("<script>", html)
        self.assertEqual(labels[0].text(), "<script>alert(1)</script> 一般 大")

    def test_options_stay_plain(self):
        from oes.ui.prompt_editor import ImagePool, OptionTextEdit
        option = OptionTextEdit("選項", ImagePool())
        self.assertFalse(option.edit.allow_format)
        option.edit.selectAll()
        option.edit.set_bold(True)
        self.assertEqual(option.edit.serialize(), "選項")


class OptionImageTests(unittest.TestCase):
    def _question(self):
        from tests.test_images import PNG_1PX
        q = C.new_question("multiple_choice", "mc")
        q.update(status="ready", prompt="哪一張圖？", correctAnswer=["o2"])
        q["options"][1]["text"] = "第二張\n{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
        return q

    def test_insert_image_into_option_shares_pool(self):
        from PySide6.QtGui import QColor, QImage
        from oes.ui.editors import QuestionEditor
        from oes.ui.prompt_editor import OptionTextEdit
        entry = {"sectionId": None, "question": self._question()}
        editor = QuestionEditor(entry, [])
        option_edits = editor.body.findChildren(OptionTextEdit)
        self.assertEqual(len(option_edits), 4)
        self.assertEqual(option_edits[1].edit.serialize(), "第二張\n{{image:img1}}")
        image = QImage(30, 30, QImage.Format.Format_RGB32)
        image.fill(QColor("blue"))
        new_id = option_edits[2].edit.insert_qimage(image)
        self.assertEqual(new_id, "img2")  # 與題目內其他圖片共用編號，不重複
        q = entry["question"]
        self.assertIn("{{image:img2}}", q["options"][2]["text"])
        self.assertEqual([i["id"] for i in q["images"]], ["img1", "img2"])
        self.assertEqual(C.validate(q), [])
        option_edits[1].edit.setPlainText("第二張")
        self.assertEqual([i["id"] for i in q["images"]], ["img2"])

    def test_render_option_image_and_click_selects(self):
        from oes.ui.renderers import RichOption, create_renderer
        from oes.ui.widgets import ImageView
        w = create_renderer(C.for_candidate(self._question()))
        w.resize(600, 400)
        w.show()
        QApplication.processEvents()
        rich = w.findChildren(RichOption)
        self.assertEqual(len(rich), 1)
        image = rich[0].findChildren(ImageView)[0]
        QTest.mouseClick(image, Qt.MouseButton.LeftButton)
        self.assertEqual(w.answers(), {"selected": ["o2"]})
        self.assertNotIn("{{image", w.buttons["o2"].accessibleName())

    def test_summary_hides_tokens(self):
        q = self._question()
        self.assertEqual(C.summarize_selection(q, {"id": "answer"}, ["o2"]), "第二張\n［圖片］")


class EditorTests(unittest.TestCase):
    def test_delete_correct_dropdown_option(self):
        from oes.ui.editors import QuestionEditor
        entry = {"sectionId": None, "question": fx("demoDropdown")}
        editor = QuestionEditor(entry, [])
        hits = []
        editor.changed.connect(lambda: hits.append(1))
        body = editor.body
        item = entry["question"]["items"][0]
        body._delete_option(item, item["options"][1])
        self.assertIsNone(item["correctAnswer"])
        self.assertEqual(entry["question"]["status"], "draft")
        self.assertEqual(editor.status.currentIndex(), 0)
        self.assertTrue(hits)

    def test_yesno_key_editor_keeps_false(self):
        from oes.ui.editors import QuestionEditor
        entry = {"sectionId": None, "question": fx("imageYesNo")}
        editor = QuestionEditor(entry, [])
        editor.body._key(entry["question"]["items"][0], 2)
        self.assertIs(entry["question"]["items"][0]["correctAnswer"], False)

    def test_all_editors_build(self):
        from oes.ui.editors import QuestionEditor
        for t in C.TYPES:
            with self.subTest(t=t):
                entry = {"sectionId": None, "question": C.new_question(t, "x1")}
                editor = QuestionEditor(entry, [{"id": "sec1", "name": "A"}])
                editor.body.structural()
                self.assertEqual(C.validate(entry["question"]), [])


class WindowTests(unittest.TestCase):
    def setUp(self):
        from oes.storage.history import HistoryStore
        self.tmp = tempfile.TemporaryDirectory()
        self.store = HistoryStore(Path(self.tmp.name) / "h.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_edit_save_reopen(self):
        from oes.ui.main_window import MainWindow
        win = MainWindow(self.store)
        for t in C.TYPES:
            E.add_question(win.exam, t)
        win.exam["questions"].append({"sectionId": None, "question": fx("demoYesNo")})
        win.refresh_all(len(win.exam["questions"]))
        self.assertEqual(win.listing.count(), len(win.exam["questions"]) + 1)
        path = Path(self.tmp.name) / "t.oes"
        self.assertTrue(win._write(path))
        before = C.clone(win.exam)
        win2 = MainWindow(self.store)
        self.assertTrue(win2.open_path(path))
        self.assertEqual(win2.exam, before)
        for row in range(win2.listing.count()):
            win2.listing.setCurrentRow(row)
        win2.question_page.tabs.setCurrentIndex(1)
        win.dirty = win2.dirty = False

    def test_list_shows_question_numbers(self):
        from oes.ui.main_window import MainWindow
        win = MainWindow(self.store)
        for t in ("multiple_choice", "fill_in_blank", "yes_no_matrix"):
            E.add_question(win.exam, t)
        win.refresh_all(1)
        texts = [win.listing.item(i).text() for i in range(1, win.listing.count())]
        self.assertEqual(texts, ["題目1", "題目2", "題目3"])
        self.assertFalse(win.listing.item(1).icon().isNull())
        self.assertIn("選擇題", win.listing.item(1).toolTip())
        win.listing.setCurrentRow(3)
        win.move_question(-1)
        self.assertEqual(win.listing.item(2).text(), "題目2")
        self.assertIn("Yes／No", win.listing.item(2).toolTip())
        win.dirty = False

    def test_title_field_removed_and_heading_numbered(self):
        from oes.ui.editors import QuestionEditor
        from oes.ui.renderers import QuestionView
        entry = {"sectionId": None, "question": fx("demoYesNo")}
        editor = QuestionEditor(entry, [])
        texts = [l.text() for l in editor.findChildren(QLabel)]
        self.assertNotIn("標題：", texts)
        view = QuestionView(C.for_candidate(entry["question"]), heading="題目3")
        texts = [l.text() for l in view.findChildren(QLabel)]
        self.assertIn("題目3", texts)
        self.assertNotIn(entry["question"]["title"], texts)

    def test_question_actions_in_context_menu(self):
        from PySide6.QtWidgets import QToolBar
        from oes.ui.main_window import MainWindow
        win = MainWindow(self.store)
        E.add_question(win.exam, "multiple_choice")
        E.add_question(win.exam, "fill_in_blank")
        win.refresh_all(0)
        win.show()
        QApplication.processEvents()
        toolbar_texts = [a.text() for a in win.findChild(QToolBar).actions()]
        for text in ("新增題目…", "複製題目", "刪除題目", "上移題目", "下移題目"):
            self.assertNotIn(text, toolbar_texts)
        empty = win.list_menu(win.listing.viewport().rect().bottomLeft() - QPoint(0, 2))
        self.assertIn("新增題目…", [a.text() for a in empty.actions()])
        pos = win.listing.visualItemRect(win.listing.item(2)).center()
        menu = win.list_menu(pos)
        self.assertEqual(win.current_index(), 1)
        texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(texts, ["新增題目…", "複製題目", "刪除題目", "上移題目", "下移題目"])
        self.assertTrue(win.act_up.isEnabled())
        self.assertFalse(win.act_down.isEnabled())
        win.dirty = False
        win.close()

    def test_exam_window_finish(self):
        from oes.ui.exam_window import ExamWindow
        ex = E.new_exam()
        ex["questions"] += [{"sectionId": None, "question": fx("demoDropdown")},
                            {"sectionId": None, "question": fx("demoYesNo")}]
        session = S.build_session(ex)
        window = ExamWindow(session, self.store)
        window.view.set_answers(CORRECT_D)
        window.view.answer_widget.answersChanged.emit()
        window.go(1)
        window.view.answer_widget.no["s2"].click()
        window.go(0)
        self.assertEqual(window.view.answers(), CORRECT_D)
        window._finish(confirmed=True)
        self.assertEqual(session["status"], "finished")
        self.assertEqual(session["report"]["score"], 1)
        self.assertEqual(self.store.load(session["id"])["status"], "finished")
        review = ExamWindow(session, self.store, review=True)
        self.assertFalse(review.view.answer_widget.combos["sum"].isEnabled())


if __name__ == "__main__":
    unittest.main()
