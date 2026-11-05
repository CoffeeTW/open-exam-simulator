"""PDF 匯出用的 HTML：各題型內容、答案顯示與否、圖片請求、跳脫（不需要 PySide6）。"""
import unittest
from datetime import date

from oes.core import exam as E
from oes.core import question_types as C
from oes.core.printable import CODE_STYLE, SERIES_NOTE, build_html
from tests.helpers import fx
from tests.test_basic_types import script_dropdown
from tests.test_goal_solution import goal
from tests.test_more_types import PNG_1PX, build_list, drag_drop, hot_area


def mc():
    q = C.new_question("multiple_choice", "mc1")
    q.update(status="ready", prompt="選出 <b>正確</b> 的 {{b}}選項{{/b}}", correctAnswer=["o3"],
             explanation="因為第三個選項正確。")
    q["options"][2]["text"] = "第三個答案"
    return q


def exam_with(*questions, case=None):
    exam = E.new_exam("列印測試")
    for q in questions:
        entry = {"sectionId": None, "question": q}
        if case:
            entry["caseStudyId"] = case
        exam["questions"].append(entry)
    return exam


class PrintableTests(unittest.TestCase):
    def test_answers_shown_or_hidden(self):
        exam = exam_with(mc())
        with_answers, _ = build_html(exam, include_answers=True, today=date(2026, 11, 5))
        without, _ = build_html(exam, include_answers=False, today=date(2026, 11, 5))
        self.assertIn("正確答案：", with_answers)
        self.assertIn("因為第三個選項正確。", with_answers)
        self.assertIn("✔", with_answers)
        for text in ("正確答案：", "因為第三個選項正確。", "✔"):
            self.assertNotIn(text, without)
        self.assertIn("第三個答案", without)
        self.assertIn("2026-11-05", without)
        self.assertIn("不含答案", without)

    def test_user_text_is_escaped(self):
        html, _ = build_html(exam_with(mc()))
        self.assertIn("&lt;b&gt;正確&lt;/b&gt;", html)
        self.assertIn("<b>選項</b>", html)  # 題目格式標記轉成粗體

    def test_images_and_widths(self):
        q = mc()
        q["prompt"] = "看圖：{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX, "width": 300}]
        html, images = build_html(exam_with(q))
        self.assertEqual(len(images), 1)
        name, request = next(iter(images.items()))
        self.assertIn(f'<img src="{name}">', html)
        self.assertEqual((request["width"], request["image"]["id"]), (300, "img1"))

    def test_hot_area_marks_correct_only_with_answers(self):
        q = hot_area()
        _, with_answers = build_html(exam_with(q), include_answers=True)
        _, without = build_html(exam_with(q), include_answers=False)
        request = next(iter(with_answers.values()))
        self.assertEqual(len(request["areas"]), len(q["areas"]))
        self.assertEqual(request["correct"], q["correctAnswer"])
        self.assertEqual(next(iter(without.values()))["correct"], [])

    def test_script_dropdown_and_drag_drop(self):
        dd = script_dropdown()
        drag = drag_drop(codeFont=True, sourcesTitle="Cmdlets")
        drag["targets"][0].update(label="Step 1:", suffix="\nStep 2: 固定步驟")
        html, _ = build_html(exam_with(dd, drag), include_answers=True)
        self.assertIn(CODE_STYLE, html)
        self.assertIn("$a = &#x27;x&#x27;", html)        # 上方文字行
        self.assertIn("［ 1 ▾ ］", html)
        self.assertIn("Get-Date ✔", html)
        self.assertIn("Cmdlets", html)
        self.assertIn("Step 2: 固定步驟", html)
        self.assertLess(html.index("Step 1:"), html.index("Step 2: 固定步驟"))
        without, _ = build_html(exam_with(dd, drag), include_answers=False)
        self.assertNotIn("Get-Date ✔", without)
        self.assertIn("［ ____________________ ］", without)

    def test_other_types(self):
        html, _ = build_html(exam_with(goal(key=False), fx("demoYesNo"), build_list(),
                                       C.new_question("fill_in_blank", "f1") | {"acceptedAnswers": ["七"]}))
        self.assertIn(SERIES_NOTE, html)
        self.assertIn("解決方案：", html)
        self.assertIn("Yes", html)
        self.assertIn("<ol>", html)       # 排序題正解依序列出
        self.assertIn("七", html)
        self.assertEqual(html.count("<hr>"), 1 + 4)

    def test_case_study_once_and_ready_filter(self):
        exam = E.new_exam("t")
        case = E.add_case_study(exam, "早餐店")
        case["text"] = "案例內容"
        draft = mc() | {"id": "draft", "status": "draft"}
        for q in (mc() | {"id": "a"}, mc() | {"id": "b"}, draft):
            exam["questions"].append({"sectionId": None, "caseStudyId": case["id"], "question": q})
        html, _ = build_html(exam)
        self.assertEqual(html.count("案例研究：早餐店"), 1)
        self.assertLess(html.index("案例內容"), html.index("題目1"))
        self.assertIn("題目3", html)
        ready, _ = build_html(exam, only_ready=True)
        self.assertNotIn("題目3", ready)
        self.assertIn("2 題", ready)

    def test_series_note_matches_screen(self):
        from oes.i18n_en import EN
        self.assertIn(SERIES_NOTE, EN)


if __name__ == "__main__":
    unittest.main()
