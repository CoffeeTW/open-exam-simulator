"""題目內容的粗體與字級標記（不需要 PySide6）。"""
import unittest

from oes.core import question_types as C
from tests.helpers import fx


class FormatTests(unittest.TestCase):
    def test_segments_nested_and_across_images(self):
        segments = C.rich_segments("A {{b}}粗{{size:18}}大{{/size}}{{image:img1}}續{{/b}}尾")
        self.assertEqual(segments, [
            ("runs", [("A ", False, None), ("粗", True, None), ("大", True, 18)]),
            ("image", "img1"),
            ("runs", [("續", True, None), ("尾", False, None)]),
        ])

    def test_unbalanced_and_clamped(self):
        self.assertEqual(C.rich_segments("{{/b}}x{{/size}}"), [("runs", [("x", False, None)])])
        self.assertEqual(C.rich_segments("{{size:99}}a{{size:2}}b"), [("runs", [("a", False, 48), ("b", False, 8)])])
        self.assertEqual(C.rich_segments("{{b}}多行\n文字"), [("runs", [("多行\n文字", True, None)])])

    def test_plain_text_and_braces_untouched(self):
        self.assertEqual(C.rich_segments("價格 {{50}} 元"), [("runs", [("價格 {{50}} 元", False, None)])])
        self.assertEqual(C.strip_format("{{b}}a{{/b}}{{size:12}}b{{/size}}{{image:i}}"), "ab{{image:i}}")

    def test_ready_needs_real_text(self):
        q = fx("demoYesNo"); q["prompt"] = "{{b}} {{/b}}"
        self.assertTrue(any(e["path"] == "prompt" for e in C.validate(q)))
        q["prompt"] = "{{b}}請判斷{{/b}}以下敘述"
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.for_candidate(q)["prompt"], "{{b}}請判斷{{/b}}以下敘述")


if __name__ == "__main__":
    unittest.main()
