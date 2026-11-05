"""英文介面：對照表完整性與核心訊息翻譯（不需要 PySide6）。"""
import ast
import string
import unittest
from pathlib import Path

from oes import i18n
from oes.core import question_types as C
from oes.i18n import tr
from oes.i18n_en import EN
from tests.helpers import fx

ROOT = Path(__file__).resolve().parents[1]


def tr_keys():
    keys = set()
    for path in (ROOT / "oes").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                keys.add(node.args[0].value)
    return keys


class I18nTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("zh_TW")

    def test_every_ui_string_has_english(self):
        missing = sorted(k for k in tr_keys() if k not in EN)
        self.assertEqual(missing, [])

    def test_labels_used_through_tr_have_english(self):
        labels = list(C.MODE_LABELS.values()) + list(C.STATUS_LABELS.values())
        for t in C.REGISTRY.values():
            labels += [t.label, t.description, t.short_label]
        self.assertEqual([x for x in labels if x not in EN], [])

    def test_placeholders_match(self):
        fmt = string.Formatter()

        def fields(s):
            return sorted((f, spec) for _, f, spec, _ in fmt.parse(s) if f is not None)
        self.assertEqual([k for k, v in EN.items() if fields(k) != fields(v)], [])

    def test_no_chinese_left_in_english(self):
        import re
        cjk = re.compile(r"[一-鿿]")
        self.assertEqual([v for v in EN.values() if cjk.search(v)], [])

    def test_no_translation_in_default_arguments(self):
        # 函式預設值在載入時就固定，放 tr() 會讓文字停在載入當下的語言
        found = []
        for path in (ROOT / "oes").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for default in node.args.defaults + node.args.kw_defaults:
                        if default is not None and "tr(" in ast.unparse(default):
                            found.append(f"{path.name}:{node.lineno}")
        self.assertEqual(found, [])

    def test_new_exam_title_follows_language(self):
        from oes.core import exam as E
        self.assertEqual(E.new_exam()["title"], "未命名題庫")
        i18n.set_language("en")
        self.assertEqual(E.new_exam()["title"], "Untitled exam")
        self.assertEqual(C.strip_images("a{{image:img1}}"), "a[image]")

    def test_switch_language(self):
        self.assertEqual(tr("儲存"), "儲存")
        i18n.set_language("en")
        self.assertEqual(tr("儲存"), "Save")
        self.assertEqual(tr("第 {0} ／ {1} 題", 2, 5), "Question 2 / 5")
        q = fx("demoDropdown"); q["prompt"] = " "
        messages = [e["message"] for e in C.validate(q)]
        self.assertIn("A ready question must have question content.", messages)
        self.assertEqual(C.new_question("multiple_choice", "x")["title"], "New multiple-choice question")
        self.assertEqual(i18n.set_language("xx"), "zh_TW")


if __name__ == "__main__":
    unittest.main()
