"""題目搜尋：可搜尋的文字範圍、比對規則與結果片段（不需要 PySide6）。"""
import unittest

from oes.core import question_types as C
from tests.test_basic_types import script_dropdown
from tests.test_goal_solution import goal
from tests.test_images import PNG_1PX
from tests.test_more_types import drag_drop


class SearchTests(unittest.TestCase):
    def test_text_covers_fields(self):
        q = drag_drop(sourcesTitle="Cmdlets", explanation="整題解析")
        q["prompt"] = "{{b}}粗體{{/b}}題目\n{{image:img1}}"
        q["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
        q["targets"][0].update(label="Step 1:", suffix="-Force", explanation="空格解析")
        text = C.search_text(q)
        for expected in ("dd", "粗體題目", "Cmdlets", "整題解析", "Step 1:", "-Force", "空格解析", "值 1"):
            self.assertIn(expected, text)
        for hidden in ("{{b}}", "{{image", PNG_1PX[:20], "新拖放題", "v1", "t1", "ready"):
            self.assertNotIn(hidden, text)
        self.assertIn("方案甲", C.search_text(goal(solution="方案甲")))
        self.assertIn("Get-Date", C.search_text(script_dropdown()))

    def test_matching_rules(self):
        text = C.search_text(script_dropdown())
        self.assertTrue(C.search_matches(text, "get-date"))           # 不分大小寫
        self.assertTrue(C.search_matches(text, "  GET-ITEM   force "))  # 多個關鍵字
        self.assertFalse(C.search_matches(text, "get-item nothing"))   # 須全部符合
        self.assertTrue(C.search_matches(text, ""))                    # 空白查詢

    def test_snippet(self):
        text = "第一行\n" + "前面的文字" * 5 + "關鍵字KEY在這裡" + "後面的文字" * 5
        snippet = C.search_snippet(text, "key")
        self.assertIn("KEY", snippet)
        self.assertTrue(snippet.startswith("…") and snippet.endswith("…"))
        self.assertNotIn("\n", snippet)
        self.assertEqual(C.search_snippet(text, "沒有"), "")
        self.assertEqual(C.search_snippet("短 KEY", "key"), "短 KEY")


if __name__ == "__main__":
    unittest.main()
