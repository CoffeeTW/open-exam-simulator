"""選擇題、填空題與編輯輔助函式。"""
import unittest

from oes.core import question_types as C
from tests.helpers import fx


def mc(mode="single", key=("o2",), check=False):
    q = C.new_question("multiple_choice", "mc1")
    q.update(status="ready", prompt="題幹", selectMode=mode, checkNumberSelected=check,
             correctAnswer=list(key) if key is not None else None)
    return q


def fill(answers=("Active Directory",), **flags):
    q = C.new_question("fill_in_blank", "f1")
    q.update(status="ready", prompt="題幹", acceptedAnswers=list(answers), **flags)
    return q


class MultipleChoiceTests(unittest.TestCase):
    def test_new_templates_are_valid_drafts(self):
        for t in C.TYPES:
            with self.subTest(t=t):
                q = C.new_question(t, "x1")
                self.assertEqual(q["status"], "draft")
                self.assertEqual(C.validate(q), [])
                self.assertEqual(C.grade(q, {})["status"], "unconfigured")

    def test_single_correct_and_wrong(self):
        self.assertEqual(C.grade(mc(), {"selected": ["o2"]})["score"], 1)
        self.assertEqual(C.grade(mc(), {"selected": ["o1"]})["score"], 0)

    def test_single_rejects_two_selections_and_two_keys(self):
        self.assertEqual(C.grade(mc(), {"selected": ["o1", "o2"]})["status"], "invalid")
        self.assertTrue(C.validate(mc(key=("o1", "o2"))))

    def test_multiple_requires_exact_set(self):
        q = mc("multiple", ("o1", "o3"))
        self.assertEqual(C.grade(q, {"selected": ["o3", "o1"]})["score"], 1)
        self.assertEqual(C.grade(q, {"selected": ["o1"]})["score"], 0)
        self.assertEqual(C.grade(q, {"selected": ["o1", "o3", "o4"]})["score"], 0)

    def test_check_number_selected_limits_count(self):
        q = mc("multiple", ("o1", "o3"), check=True)
        self.assertEqual(C.grade(q, {"selected": ["o1", "o2", "o3"]})["status"], "invalid")
        self.assertEqual(C.for_candidate(q)["selectCount"], 2)

    def test_empty_selection_is_unanswered(self):
        r = C.grade(mc(), {"selected": []})
        self.assertEqual(r["status"], "incomplete")
        self.assertEqual(C.grade(mc(), {}, allow_incomplete=True)["score"], 0)

    def test_bad_answers_invalid(self):
        for answers in ({"selected": ["zz"]}, {"selected": "o1"}, {"selected": ["o1", "o1"]}, {"other": 1}):
            with self.subTest(a=answers):
                self.assertEqual(C.grade(mc("multiple", ("o1",)), answers)["status"], "invalid")

    def test_candidate_hides_key(self):
        q = mc(); q["explanation"] = "secret"
        text = str(C.for_candidate(q))
        self.assertNotIn("correctAnswer", text); self.assertNotIn("secret", text)
        self.assertNotIn("selectCount", C.for_candidate(q))

    def test_delete_correct_option_returns_to_draft(self):
        q = mc()
        self.assertTrue(C.remove_option(q, "o2"))
        self.assertIsNone(q["correctAnswer"]); self.assertEqual(q["status"], "draft")
        self.assertEqual(C.validate(q), [])

    def test_delete_one_of_multiple_keys(self):
        q = mc("multiple", ("o1", "o2"))
        C.remove_option(q, "o2")
        self.assertEqual(q["correctAnswer"], ["o1"]); self.assertEqual(q["status"], "draft")

    def test_switch_to_single_trims_keys(self):
        q = mc("multiple", ("o1", "o2"))
        C.set_select_mode(q, "single")
        self.assertEqual(q["correctAnswer"], ["o1"]); self.assertEqual(C.validate(q, True), [])


class FillInBlankTests(unittest.TestCase):
    def test_default_case_insensitive_and_spaces(self):
        q = fill()
        self.assertEqual(C.grade(q, {"text": "  active   directory "})["score"], 1)

    def test_case_sensitive(self):
        q = fill(caseSensitive=True)
        self.assertEqual(C.grade(q, {"text": "active directory"})["score"], 0)
        self.assertEqual(C.grade(q, {"text": "Active Directory"})["score"], 1)

    def test_no_trim_no_space_collapse(self):
        q = fill(trimResponse=False, ignoreMultipleSpaces=False)
        self.assertEqual(C.grade(q, {"text": " Active Directory"})["score"], 0)
        self.assertEqual(C.grade(q, {"text": "Active  Directory"})["score"], 0)

    def test_any_accepted_answer(self):
        q = fill(("AD", "Active Directory"))
        self.assertEqual(C.grade(q, {"text": "ad"})["score"], 1)

    def test_blank_is_unanswered_and_type_checked(self):
        self.assertEqual(C.grade(fill(), {"text": "   "})["status"], "incomplete")
        self.assertEqual(C.grade(fill(), {"text": 5})["status"], "invalid")

    def test_ready_needs_answer(self):
        self.assertTrue(C.validate(fill(())))
        self.assertTrue(C.validate(fill(("ok", " "))))

    def test_candidate_hides_answers(self):
        self.assertNotIn("Active", str(C.for_candidate(fill())))


class DropdownLabelTests(unittest.TestCase):
    def test_blank_label_allowed(self):
        q = fx("demoDropdown")
        for label in ("", "   "):
            q["items"][0]["label"] = label
            with self.subTest(label=label):
                self.assertEqual(C.validate(q), [])
                self.assertEqual(C.for_candidate(q)["items"][0]["label"], label)

    def test_label_must_be_text(self):
        q = fx("demoDropdown")
        for bad in (None, 3):
            q["items"][0]["label"] = bad
            with self.subTest(label=bad):
                self.assertTrue(any(e["path"] == "items[0].label" for e in C.validate(q)))
        del q["items"][0]["label"]
        self.assertTrue(any(e["path"] == "items[0].label" for e in C.validate(q)))


def script_dropdown():
    """指令腳本式下拉題：多行前後文字、程式碼字型。"""
    q = C.new_question("dropdown_multi", "dd1")
    q.update(status="ready", prompt="完成指令", codeFont=True)
    first, second = q["items"]
    first.update(label="$a = 'x'\n$b =", options=[{"id": "o1", "text": "Get-Item"}, {"id": "o2", "text": "Get-Date"}],
                 correctAnswer="o2")
    second.update(label="", suffix="Path\\To -Force\n$c = Done $b",
                  options=[{"id": "o1", "text": "Set-Item"}, {"id": "o2", "text": "Out-File"}], correctAnswer="o1")
    q["scoring"] = {"mode": "per_part", "maxScore": 2}
    return q


class DropdownScriptTests(unittest.TestCase):
    def test_valid_and_candidate(self):
        q = script_dropdown()
        self.assertEqual(C.validate(q), [])
        dto = C.for_candidate(q)
        self.assertTrue(dto["codeFont"])
        self.assertEqual((dto["items"][0]["suffix"], dto["items"][1]["suffix"]), ("", "Path\\To -Force\n$c = Done $b"))
        self.assertNotIn("correctAnswer", dto["items"][0])
        self.assertEqual(C.grade(q, {"item1": "o2", "item2": "o2"})["score"], 1)

    def test_defaults_for_old_questions(self):
        dto = C.for_candidate(fx("demoDropdown"))
        self.assertFalse(dto["codeFont"])
        self.assertTrue(all(item["suffix"] == "" for item in dto["items"]))

    def test_bad_fields(self):
        q = script_dropdown()
        q["codeFont"] = "yes"
        q["items"][1]["suffix"] = 5
        paths = {e["path"] for e in C.validate(q)}
        self.assertTrue({"codeFont", "items[1].suffix"} <= paths)


class EditingHelperTests(unittest.TestCase):
    def test_dropdown_delete_correct_option(self):
        q = fx("demoDropdown")
        self.assertTrue(C.remove_option(q, "o2", "sum"))
        self.assertIsNone(q["items"][0]["correctAnswer"]); self.assertEqual(q["status"], "draft")
        self.assertEqual(C.validate(q), [])
        self.assertEqual(q["items"][1]["correctAnswer"], "o2")

    def test_dropdown_delete_other_option_keeps_key(self):
        q = fx("demoDropdown")
        self.assertFalse(C.remove_option(q, "o1", "sum"))
        self.assertEqual(q["status"], "ready")

    def test_next_id_never_reuses(self):
        self.assertEqual(C.next_id(["o1", "o2", "o4"], "o"), "o3")
        self.assertEqual(C.next_id([], "s"), "s1")

    def test_move(self):
        seq = [1, 2, 3]
        self.assertEqual(C.move(seq, 0, 1), 1); self.assertEqual(seq, [2, 1, 3])
        self.assertEqual(C.move(seq, 0, -1), 0)

    def test_summaries(self):
        y = fx("demoYesNo")
        self.assertEqual(C.summarize_selection(y, {"id": "s1"}, False), "No")
        self.assertEqual(C.summarize_selection(y, {"id": "s1"}, None), "（未作答）")
        d = fx("demoDropdown")
        self.assertEqual(C.summarize_selection(d, {"id": "sum"}, "o2"), "5")


if __name__ == "__main__":
    unittest.main()
