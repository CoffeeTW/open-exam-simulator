"""排序題、拖放題、熱區題與案例研究的介面測試（需要 PySide6，offscreen 執行）。"""
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QDropEvent, QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from tests.test_more_types import build_list, drag_drop

APP = None


def setUpModule():  # noqa: N802
    global APP
    if QApplication is None:
        raise unittest.SkipTest("未安裝 PySide6，略過介面測試")
    APP = QApplication.instance() or QApplication([])


def big_image_b64():
    from oes.ui.prompt_editor import encode_image
    image = QImage(200, 100, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    return encode_image(image)


def hot_area_question():
    mime, data = big_image_b64()
    q = C.new_question("hot_area", "ha")
    q.update(status="ready", prompt="點選", background="img1", images=[{"id": "img1", "mime": mime, "data": data}],
             areas=[{"id": "a1", "x": 10, "y": 10, "w": 40, "h": 40},
                    {"id": "a2", "x": 100, "y": 10, "w": 40, "h": 40}],
             correctAnswer=["a2"])
    return q


def renderer(q):
    from oes.ui.renderers import create_renderer
    return create_renderer(C.for_candidate(q))


class BuildListUiTests(unittest.TestCase):
    def test_build_and_reorder(self):
        w = renderer(build_list())
        self.assertEqual(w.answers(), {})
        self.assertEqual(w.source.count(), 4)
        hits = []
        w.answersChanged.connect(lambda: hits.append(1))
        for choice in ("c3", "c1", "c2"):
            row = [w.source.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.source.count())].index(choice)
            w.source.setCurrentRow(row)
            w.add_selected()
        self.assertEqual(w.answers(), {"sequence": ["c3", "c1", "c2"]})
        self.assertTrue(hits)
        w.target.setCurrentRow(0)
        w.move_selected(1)
        self.assertEqual(w.answers(), {"sequence": ["c1", "c3", "c2"]})
        w.target.setCurrentRow(2)
        w.remove_selected()
        self.assertEqual(w.answers(), {"sequence": ["c1", "c3"]})
        self.assertEqual([w.source.item(i).data(Qt.ItemDataRole.UserRole) for i in range(w.source.count())],
                         ["c2", "c4"])

    def test_restore_and_reorder_only(self):
        w = renderer(build_list())
        w.set_answers({"sequence": ["c2", "c4"]})
        self.assertEqual(w.answers(), {"sequence": ["c2", "c4"]})
        q = build_list(reorderOnly=True, correctAnswer=["c4", "c3", "c2", "c1"])
        w = renderer(q)
        self.assertEqual(w.answers(), {"sequence": ["c1", "c2", "c3", "c4"]})
        self.assertTrue(w.source.isHidden())

    def test_editor_sets_key(self):
        from oes.ui.editors import QuestionEditor
        q = build_list(correctAnswer=None, status="draft")
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        key = editor.body.key_widget
        for _ in range(2):
            key.source.setCurrentRow(0)
            key.add_selected()
        self.assertEqual(q["correctAnswer"], ["c1", "c2"])
        editor.body._reorder_toggled(True)
        self.assertIsNone(q["correctAnswer"])
        editor.body.key_widget.target.setCurrentRow(3)
        editor.body.key_widget.move_selected(-1)
        self.assertEqual(q["correctAnswer"], ["c1", "c2", "c4", "c3"])
        self.assertEqual(C.validate(q), [])


class DragDropUiTests(unittest.TestCase):
    def test_place_and_no_reuse(self):
        w = renderer(drag_drop())
        self.assertEqual(w.answers(), {})
        w.place("t1", "v2")
        self.assertEqual(w.answers(), {"t1": "v2"})
        self.assertFalse(w.tiles["v2"].isEnabled())
        w.place("t2", "v2")
        self.assertEqual(w.answers(), {"t2": "v2"})
        w.slots["t2"].set_value(None)
        self.assertEqual(w.answers(), {})

    def test_script_layout(self):
        from PySide6.QtWidgets import QLabel
        from tests.test_more_types import DragDropScriptTests
        q = DragDropScriptTests().script()
        w = renderer(q)
        w.resize(900, 400)
        w.show()
        QApplication.processEvents()
        texts = [label.text() for label in w.findChildren(QLabel)]
        self.assertIn("Cmdlets", texts)
        suffix = [label for label in w.findChildren(QLabel) if label.objectName() == "suffix:t1"][0]
        self.assertEqual(suffix.text(), "-Name 'Group1' -GroupScope Global")
        # 背景測試模式沒有字型檔，只檢查程式要求的字型（不檢查實際解析結果）
        for widget in (suffix, w.tiles["v1"], w.slots["t1"]):
            self.assertTrue(widget.font().fixedPitch())
            self.assertEqual(widget.font().families()[0], "Consolas")
        titles = [label for label in w.findChildren(QLabel) if label.text() == "Cmdlets"]
        self.assertFalse(titles[0].font().fixedPitch())  # 標題維持介面字型
        slot = w.slots["t1"]
        self.assertLess(slot.geometry().right(), suffix.geometry().left())  # 空格在左、文字在右
        self.assertEqual(slot.accessibleName(), "空格：-Name 'Group1' -GroupScope Global")
        w.place("t1", "v3")
        w.place("t2", "v3")
        self.assertEqual(w.answers(), {"t1": "v3", "t2": "v3"})
        plain = renderer(drag_drop())
        self.assertEqual(plain.font(), QApplication.font())  # 未勾選程式碼字型時維持一般字型
        self.assertFalse([label for label in plain.findChildren(QLabel) if label.objectName().startswith("suffix:")])

    def test_script_editor(self):
        from PySide6.QtWidgets import QCheckBox, QLineEdit
        from oes.ui.editors import QuestionEditor
        q = drag_drop()
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        boxes = {b.text(): b for b in editor.body.findChildren(QCheckBox)}
        [b for t, b in boxes.items() if "程式碼字型" in t][0].setChecked(True)
        edits = editor.body.findChildren(QLineEdit)
        title = [e for e in edits if "Cmdlets" in e.placeholderText()][0]
        title.textEdited.emit("Cmdlets")
        from oes.ui.editors import AroundText
        around = editor.body.findChildren(AroundText)[0]
        around.before.setText("Step 1:")
        around.before.textEdited.emit("Step 1:")
        around.below.setPlainText("Step 2: 固定步驟")  # 下方文字行：自成一行，不會接在空格右邊
        self.assertEqual((q["codeFont"], q["sourcesTitle"], q["targets"][0]["label"], q["targets"][0]["suffix"]),
                         (True, "Cmdlets", "Step 1:", "\nStep 2: 固定步驟"))
        around.below.setPlainText("")
        title.textEdited.emit("")
        self.assertNotIn("suffix", q["targets"][0])
        self.assertNotIn("sourcesTitle", q)
        self.assertEqual(C.validate(q), [])

    def test_fixed_step_lines(self):
        from PySide6.QtWidgets import QApplication, QLabel
        q = C.new_question("drag_drop", "steps")
        q.update(status="ready", prompt="依序排列", reuseSources=True,
                 sources=[{"id": "v1", "text": "部署服務"}, {"id": "v2", "text": "建立同步群組"},
                          {"id": "v3", "text": "新增伺服器端點"}],
                 targets=[{"id": "t1", "label": "Step 1:", "suffix": "\nStep 2: 安裝並註冊代理程式",
                           "correctAnswer": "v1", "explanation": ""},
                          {"id": "t3", "label": "Step 3:", "correctAnswer": "v2", "explanation": ""},
                          {"id": "t4", "label": "Step 4:", "correctAnswer": "v3", "explanation": ""}])
        self.assertEqual(C.validate(q), [])
        w = renderer(q)
        w.resize(900, 400)
        w.show()
        QApplication.processEvents()
        labels = {lab.text(): lab for lab in w.findChildren(QLabel) if lab.isVisible()}
        step2 = labels["Step 2: 安裝並註冊代理程式"]
        self.assertGreater(step2.geometry().top(), w.slots["t1"].geometry().bottom())   # 在 Step 1 下方
        self.assertLess(step2.geometry().bottom(), w.slots["t3"].geometry().top())      # 在 Step 3 上方
        self.assertFalse([lab for lab in w.findChildren(QLabel) if lab.objectName() == "suffix:t1"])
        self.assertEqual(w.slots["t1"].accessibleName(), "空格：Step 1:")
        for tid, value in (("t1", "v1"), ("t3", "v2"), ("t4", "v3")):
            w.place(tid, value)
        self.assertEqual(C.grade(q, w.answers())["score"], 1)

    def test_reuse_allowed(self):
        w = renderer(drag_drop(reuseSources=True))
        w.place("t1", "v1")
        w.place("t2", "v1")
        self.assertEqual(w.answers(), {"t1": "v1", "t2": "v1"})

    def test_drop_event(self):
        from oes.ui.renderers_extra import SOURCE_MIME
        w = renderer(drag_drop())
        mime = QMimeData()
        mime.setData(SOURCE_MIME, b"v3")
        event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
                           Qt.KeyboardModifier.NoModifier)
        w.slots["t1"].dropEvent(event)
        self.assertEqual(w.answers(), {"t1": "v3"})

    def test_restore_review_readonly(self):
        q = drag_drop()
        w = renderer(q)
        w.set_answers({"t1": "v2", "t2": "v1"})
        w.set_read_only(True)
        w.place("t2", "v4")
        self.assertEqual(w.answers(), {"t1": "v2", "t2": "v1"})
        w.show_review(q, C.grade(q, w.answers()))
        self.assertIn("正解", w.reviews["t2"].text())

    def test_editor(self):
        from oes.ui.editors import QuestionEditor
        q = drag_drop()
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        editor.body.key_combos[1].setCurrentIndex(3)
        self.assertEqual(q["targets"][1]["correctAnswer"], "v3")
        editor.body._delete_source(q["sources"][1])
        self.assertIsNone(q["targets"][0]["correctAnswer"])
        self.assertEqual(q["status"], "draft")


class HotAreaUiTests(unittest.TestCase):
    def test_click_and_keyboard(self):
        w = renderer(hot_area_question())
        w.resize(400, 300)
        w.show()
        QApplication.processEvents()
        canvas = w.canvas
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas.point_of("a2"))
        self.assertEqual(w.answers(), {"selected": ["a2"]})
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, canvas.point_of("a2"))
        self.assertEqual(w.answers(), {})
        canvas.setFocus()
        canvas.focus_index = 0
        QTest.keyClick(canvas, Qt.Key.Key_Space)
        self.assertEqual(w.answers(), {"selected": ["a1"]})

    def test_scaled_click(self):
        w = renderer(hot_area_question())
        w.resize(100, 200)
        w.show()
        QApplication.processEvents()
        self.assertLess(w.canvas._scale(), 1)
        QTest.mouseClick(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, w.canvas.point_of("a2"))
        self.assertEqual(w.answers(), {"selected": ["a2"]})

    def test_editor_background_areas_key(self):
        from oes.ui.editors import QuestionEditor
        q = C.new_question("hot_area", "ha")
        editor = QuestionEditor({"sectionId": None, "question": q}, [])
        editor.resize(900, 900)
        editor.show()
        body = editor.body
        image = QImage(300, 150, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        body._set_background_image(image)
        self.assertEqual(q["background"], "img1")
        self.assertEqual([i["id"] for i in q["images"]], ["img1"])
        canvas = body.canvas
        QApplication.processEvents()
        self.assertEqual(canvas._scale(), 1.0)
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
        QTest.mouseMove(canvas, QPoint(60, 50))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 50))
        self.assertEqual(len(q["areas"]), 1)
        self.assertEqual((q["areas"][0]["x"], q["areas"][0]["y"]), (10, 10))
        body._toggle_key(q["areas"][0]["id"], True)
        q["prompt"] = "點選"
        q["status"] = "ready"
        self.assertEqual(C.validate(q), [])
        body._delete(q["areas"][0]["id"])
        self.assertEqual(q["areas"], [])
        self.assertIsNone(q["correctAnswer"])


class CaseStudyUiTests(unittest.TestCase):
    def test_view_has_case_button(self):
        from oes.ui.renderers import QuestionView
        view = QuestionView(C.for_candidate(drag_drop()), heading="題目1", case={"name": "示範公司", "text": "情境"})
        self.assertFalse(view.case_button.isHidden())
        from oes.ui.renderers_extra import CaseStudyDialog
        dialog = CaseStudyDialog({"name": "示範公司", "text": "情境說明"})
        self.assertIn("示範公司", dialog.windowTitle())

    def test_main_window_case_editing_and_exam(self):
        from oes.storage.history import HistoryStore
        from oes.ui.exam_window import ExamWindow
        from oes.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            store = HistoryStore(Path(tmp) / "h.db")
            win = MainWindow(store)
            case = E.add_case_study(win.exam, "示範公司")
            win.exam["questions"].append({"sectionId": None, "caseStudyId": case["id"], "question": build_list()})
            win.exam["questions"].append({"sectionId": None, "question": drag_drop()})
            win.refresh_all(0)
            self.assertEqual(win.properties.cases.count(), 1)
            win.listing.setCurrentRow(1)
            self.assertEqual(win.question_page.edit_scroll.widget().case.currentIndex(), 1)
            path = Path(tmp) / "c.oes"
            self.assertTrue(win._write(path))
            session = S.build_session(win.exam)
            window = ExamWindow(session, store)
            self.assertFalse(window.view.case_button.isHidden())
            window.view.set_answers({"sequence": ["c3", "c1", "c2"]})
            window.view.answer_widget.answersChanged.emit()
            window.go(1)
            window.view.answer_widget.place("t1", "v2")
            window.view.answer_widget.place("t2", "v4")
            window._finish(confirmed=True)
            self.assertEqual(session["report"]["score"], 2)
            win.dirty = False

    def test_new_question_dialog_lists_new_types(self):
        from oes.ui.dialogs import NewQuestionDialog
        dialog = NewQuestionDialog()
        types = [dialog.listing.item(i).data(Qt.ItemDataRole.UserRole) for i in range(dialog.listing.count())]
        for t in ("build_list", "drag_drop", "hot_area"):
            self.assertIn(t, types)


def screenshot_image(alpha=False):
    """像截圖的測試圖片：白底、色塊與文字。"""
    from PySide6.QtGui import QFont, QPainter
    fmt = QImage.Format.Format_ARGB32 if alpha else QImage.Format.Format_RGB32
    image = QImage(480, 320, fmt)
    image.fill(QColor(0, 0, 0, 0) if alpha else QColor("white"))
    painter = QPainter(image)
    painter.fillRect(20, 20, 200, 60, QColor(0, 120, 212))
    painter.fillRect(240, 120, 180, 120, QColor(240, 240, 240))
    painter.setPen(QColor("black"))
    painter.setFont(QFont("Arial", 11))
    for row in range(8):
        painter.drawText(30, 110 + row * 24, f"Virtual machine VM{row} - Standard_D2s_v3 - East US")
    painter.end()
    return image


class WebPImageTests(unittest.TestCase):
    def test_lossless_webp_smaller_and_identical(self):
        from PySide6.QtCore import QByteArray
        from oes.ui.prompt_editor import _same_pixels, _save, lossless_encode, webp_supported
        self.assertTrue(webp_supported())
        for alpha in (False, True):
            with self.subTest(alpha=alpha):
                image = screenshot_image(alpha)
                mime, data = lossless_encode(image)
                self.assertEqual(mime, "image/webp")
                self.assertLess(len(data), len(_save(image, "PNG")))
                decoded = QImage()
                self.assertTrue(decoded.loadFromData(QByteArray(data)))
                self.assertTrue(_same_pixels(image, decoded))

    def test_encode_image_and_files(self):
        from oes.ui.prompt_editor import encode_image, load_image_file
        image = screenshot_image()
        mime, data = encode_image(image)
        self.assertEqual(mime, "image/webp")
        with tempfile.TemporaryDirectory() as tmp:
            png = Path(tmp) / "shot.png"
            jpg = Path(tmp) / "photo.jpg"
            image.save(str(png))
            image.save(str(jpg), "JPEG", 80)
            self.assertEqual(load_image_file(png)[0], "image/webp")
            import base64
            self.assertEqual(load_image_file(jpg), ("image/jpeg", base64.b64encode(jpg.read_bytes()).decode()))

    def test_recompress_exam(self):
        import base64
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from oes.ui.prompt_editor import _same_pixels, recompress_exam
        image = screenshot_image()
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        png = base64.b64encode(bytes(buffer.data())).decode()
        exam = E.new_exam("t")
        q = drag_drop()
        q["prompt"] = "看圖：\n{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": png, "width": 200}]
        exam["questions"].append({"sectionId": None, "question": q})
        case = E.add_case_study(exam, "c")
        case["images"] = [{"id": "img1", "mime": "image/png", "data": png}]
        case["text"] = "{{image:img1}}"
        changed, before, after = recompress_exam(exam)
        self.assertEqual(changed, 2)
        self.assertLess(after, before)
        image_entry = q["images"][0]
        self.assertEqual((image_entry["mime"], image_entry["width"]), ("image/webp", 200))
        decoded = QImage()
        decoded.loadFromData(QByteArray(base64.b64decode(image_entry["data"])))
        self.assertTrue(_same_pixels(image, decoded))
        self.assertEqual(C.validate(q), [])
        self.assertEqual(recompress_exam(exam)[0], 0)  # 已是最小，不再改動

    def test_compress_menu_action(self):
        import base64
        from unittest import mock
        from PySide6.QtCore import QBuffer, QIODevice
        from oes.storage.history import HistoryStore
        from oes.ui.main_window import MainWindow
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        screenshot_image().save(buffer, "PNG")
        exam = E.new_exam("t")
        q = drag_drop()
        q["prompt"] = "看圖：\n{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": base64.b64encode(bytes(buffer.data())).decode()}]
        exam["questions"].append({"sectionId": None, "question": q})
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(HistoryStore(Path(tmp) / "h.db"))
            window.set_exam(exam, None)
            window.listing.setCurrentRow(1)
            with mock.patch("oes.ui.main_window.QMessageBox.information") as info:
                window.act_compress.trigger()
            self.assertIn("1", info.call_args[0][2])
            self.assertEqual(window.exam["questions"][0]["question"]["images"][0]["mime"], "image/webp")
            self.assertTrue(window.dirty)
            window.dirty = False
            window.close()


class GoalSolutionUiTests(unittest.TestCase):
    def setUp(self):
        from tests.test_goal_solution import goal, mc
        self.goal, self.mc = goal, mc

    def view(self, q):
        from oes.ui.renderers import QuestionView
        view = QuestionView(C.for_candidate(q))
        return view

    def test_view_note_solution_and_answers(self):
        from PySide6.QtWidgets import QFrame, QLabel
        from oes.i18n_en import EN
        from oes.ui import renderers as R
        for text in (R.SERIES_NOTE, R.NO_RETURN_NOTE, R.GOAL_QUESTION):
            self.assertIn(text, EN)
        view = self.view(self.goal(key=False))
        texts = " ".join(label.text() for label in view.findChildren(QLabel))
        self.assertIn(R.SERIES_NOTE, texts)
        self.assertIn(R.NO_RETURN_NOTE, texts)
        self.assertIn("解決方案：在伺服器上執行某個命令。", texts)
        self.assertIn(R.GOAL_QUESTION, texts)
        self.assertEqual(len([f for f in view.findChildren(QFrame) if f.objectName() == "seriesNote"]), 1)
        widget = view.answer_widget
        self.assertEqual(view.answers(), {})
        widget.buttons[False].click()
        self.assertEqual(view.answers(), {"answer": False})
        view.set_answers({"answer": True})
        self.assertTrue(widget.buttons[True].isChecked())
        q = self.goal(key=False)
        view.show_review(q, C.grade(q, view.answers()))
        self.assertIn("錯誤", widget.review.text())
        self.assertIn("正解", widget.marks[False].text())
        plain = self.view(self.goal(no_return=False))
        texts = " ".join(label.text() for label in plain.findChildren(QLabel))
        self.assertNotIn(R.NO_RETURN_NOTE, texts)

    def test_exam_window_locks_after_leaving(self):
        from unittest import mock
        from PySide6.QtWidgets import QMessageBox
        from oes.core import session as S
        from oes.storage.history import HistoryStore
        from oes.ui.exam_window import ExamWindow
        exam = E.new_exam("t")
        for q in (self.goal("g1"), self.goal("g2"), self.mc("m1")):
            exam["questions"].append({"sectionId": None, "question": q})
        session = S.build_session(exam)
        with tempfile.TemporaryDirectory() as tmp:
            window = ExamWindow(session, HistoryStore(Path(tmp) / "h.db"))
            self.assertFalse(window.mark.isEnabled())
            window.view.answer_widget.buttons[True].click()
            window.step(1)
            self.assertEqual(window.index, 1)
            self.assertEqual(session["locked"], ["g1"])
            self.assertFalse(window.prev_button.isEnabled())
            window.go(0)
            self.assertEqual(window.index, 1)  # 已鎖定的題目不能前往
            # 尚未作答就離開：取消時留在本題，確定才鎖定
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                window.step(1)
            self.assertEqual((window.index, session["locked"]), (1, ["g1"]))
            with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                window.step(1)
            self.assertEqual((window.index, session["locked"]), (2, ["g1", "g2"]))
            self.assertTrue(window.mark.isEnabled())
            self.assertFalse(window.prev_button.isEnabled())
            self.assertFalse(window.next_button.isEnabled())
            window._closing_ok = True
            window.close()

    def test_practice_mode_allows_return(self):
        from oes.core import session as S
        from oes.storage.history import HistoryStore
        from oes.ui.exam_window import ExamWindow
        exam = E.new_exam("t")
        for q in (self.goal("g1"), self.mc("m1")):
            exam["questions"].append({"sectionId": None, "question": q})
        session = S.build_session(exam, mode="practice")
        with tempfile.TemporaryDirectory() as tmp:
            window = ExamWindow(session, HistoryStore(Path(tmp) / "h.db"))
            window.step(1)
            window.step(-1)
            self.assertEqual((window.index, session["locked"]), (0, []))
            window._closing_ok = True
            window.close()

    def test_editor(self):
        from PySide6.QtWidgets import QCheckBox, QComboBox
        from oes.ui.editors import QuestionEditor
        q = C.new_question("goal_solution", "g1")
        entry = {"sectionId": None, "question": q}
        editor = QuestionEditor(entry, [])
        editor.prompt.edit.setPlainText("情境")
        editor.body.solution.edit.setPlainText("方案 A")
        combo = [c for c in editor.body.findChildren(QComboBox) if c.count() == 3][0]
        combo.setCurrentIndex(2)
        box = editor.body.findChildren(QCheckBox)[0]
        self.assertFalse(box.isChecked())  # 預設可返回上一題
        box.setChecked(True)
        self.assertEqual((q["solution"], q["correctAnswer"], q["noReturn"]), ("方案 A", False, True))
        q["status"] = "ready"
        self.assertEqual(C.validate(q), [])


class PdfExportTests(unittest.TestCase):
    def test_export_sample_bank(self):
        from oes.storage.exam_file import load_exam
        from oes.ui.pdf_export import export_pdf
        root = Path(__file__).resolve().parents[1]
        exam = load_exam(root / "samples" / "示範題庫.oes")
        with tempfile.TemporaryDirectory() as tmp:
            for answers in (True, False):
                path = Path(tmp) / f"示範題庫{answers}.pdf"
                pages = export_pdf(exam, path, include_answers=answers)
                self.assertGreaterEqual(pages, 2)
                data = path.read_bytes()
                self.assertTrue(data.startswith(b"%PDF"))
                self.assertGreater(len(data), 5000)

    def test_hot_area_overlay(self):
        import base64
        from PySide6.QtCore import QBuffer, QIODevice
        from oes.ui.pdf_export import render_image
        image = QImage(60, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        data = {"id": "img1", "mime": "image/png", "data": base64.b64encode(bytes(buffer.data())).decode()}
        areas = [{"id": "a1", "x": 0, "y": 0, "w": 20, "h": 20}, {"id": "a2", "x": 40, "y": 0, "w": 20, "h": 20}]
        result = render_image({"image": data, "areas": areas, "correct": ["a2"]})
        inside_correct = result.pixelColor(50, 10)
        inside_other = result.pixelColor(10, 10)
        self.assertGreater(inside_correct.green(), inside_correct.red())   # 正確區域填綠色
        self.assertEqual(inside_other.name(), "#ffffff")                  # 其他區域只畫框
        self.assertIsNone(render_image({"image": {"id": "x", "mime": "image/png", "data": "bad"}}))

    def test_menu_action(self):
        from unittest import mock
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from oes.storage.history import HistoryStore
        from oes.ui.main_window import MainWindow
        from oes.ui.pdf_export import PdfExportDialog
        exam = E.new_exam("PDF: 測試/題庫")
        exam["questions"].append({"sectionId": None, "question": drag_drop()})
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "out"
            window = MainWindow(HistoryStore(Path(tmp) / "h.db"))
            window.set_exam(exam, None)
            with mock.patch.object(PdfExportDialog, "exec", return_value=1), \
                    mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(target), "")) as save, \
                    mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
                window.act_export_pdf.trigger()
            suggested = Path(save.call_args[0][2]).name
            self.assertEqual(suggested, "PDF_ 測試_題庫（含答案）.pdf")
            self.assertTrue((Path(tmp) / "out.pdf").read_bytes().startswith(b"%PDF"))
            window.dirty = False
            window.close()


class SearchUiTests(unittest.TestCase):
    def test_filter_question_list(self):
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest
        from oes.storage.history import HistoryStore
        from oes.ui.main_window import MainWindow
        exam = E.new_exam("搜尋")
        for qid, prompt in (("q1", "設定 Azure File Sync 代理程式"), ("q2", "建立 AD 群組"), ("q3", "Azure 虛擬機器")):
            q = drag_drop()
            q.update(id=qid, prompt=prompt)
            exam["questions"].append({"sectionId": None, "question": q})
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(HistoryStore(Path(tmp) / "h.db"))
            window.set_exam(exam, None)
            window.listing.setCurrentRow(0)
            window.search.setText("azure")
            hidden = [window.listing.isRowHidden(r) for r in range(1, 4)]
            self.assertEqual(hidden, [False, True, False])
            self.assertEqual(window.search_info.text(), "找到 2 題")
            self.assertIn("Azure File Sync", window.listing.item(1).text())
            self.assertTrue(window.listing.item(1).text().startswith("題目1"))
            self.assertTrue(window.listing.item(3).text().startswith("題目3"))  # 保留原本編號
            window.search.setText("azure sync")
            self.assertEqual([window.listing.isRowHidden(r) for r in range(1, 4)], [False, True, True])
            window.search.setText("找不到的字")
            self.assertEqual(window.search_info.text(), "找不到符合的題目")
            window.search.setText("群組")
            QTest.keyClick(window.search, Qt.Key.Key_Return)
            self.assertEqual(window.listing.currentRow(), 2)
            window.search.setText("azure")
            self.assertFalse(window.listing.isRowHidden(2))  # 正在編輯的題目不隱藏
            QTest.keyClick(window.search, Qt.Key.Key_Escape)
            self.assertEqual(window.search.text(), "")
            self.assertFalse(any(window.listing.isRowHidden(r) for r in range(1, 4)))
            self.assertFalse(window.search_info.isVisible())
            self.assertEqual(window.listing.item(1).text(), "題目1")
            window.search.setText("azure")
            window.set_exam(E.new_exam("新題庫"), None)
            self.assertEqual(window.search.text(), "")
            window.act_search.trigger()
            window.dirty = False
            window.close()


class AboutDialogTests(unittest.TestCase):
    def test_contents_and_copy(self):
        import platform
        from unittest import mock
        from oes import __version__
        from oes.ui.about import AboutDialog, about_text
        history = Path(tempfile.gettempdir()) / "oes-about" / "history.db"
        text = about_text(history)
        for expected in (__version__, platform.python_version(), str(history), "LGPL v3", "GPL-3.0-or-later",
                         "Copyright (C) 2026 CoffeeTW", "https://github.com/CoffeeTW/open-exam-simulator",
                         "解決方案評估題（是否達成目標）", "第 3 版"):
            self.assertIn(expected, text)
        dialog = AboutDialog(history)
        self.assertEqual(dialog.value_labels["程式版本"].text(), __version__)
        with mock.patch("oes.ui.about.QGuiApplication.clipboard") as clipboard:
            dialog.copy_info()
        clipboard.return_value.setText.assert_called_once_with(text)
        self.assertEqual(dialog.copy_button.text(), "已複製")

    def test_menu_opens_dialog(self):
        from unittest import mock
        from oes.storage.history import HistoryStore
        from oes.ui.about import AboutDialog
        from oes.ui.main_window import MainWindow
        with tempfile.TemporaryDirectory() as tmp:
            window = MainWindow(HistoryStore(Path(tmp) / "h.db"))
            with mock.patch.object(AboutDialog, "exec", return_value=0) as shown:
                window.act_about.trigger()
            shown.assert_called_once()
            window.dirty = False
            window.close()


if __name__ == "__main__":
    unittest.main()
