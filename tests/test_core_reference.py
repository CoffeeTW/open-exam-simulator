"""下拉選單與 Yes／No 判斷題的 40 項核心參考測試。"""
import json
import math
import unittest

from oes.core import question_types as C
from tests.helpers import CORRECT_D, CORRECT_Y, FIXTURES, fx


class ReferenceCoreTests(unittest.TestCase):
    def test_01_fixtures_valid(self):
        for name in FIXTURES:
            with self.subTest(name=name):
                self.assertEqual(C.validate(fx(name)), [])

    def test_02_image_dropdown_has_no_invented_key(self):
        q = fx("imageDropdown")
        self.assertTrue(all(i["correctAnswer"] is None for i in q["items"]))
        self.assertEqual(C.grade(q, {})["status"], "unconfigured")

    def test_03_image_yesno_has_no_invented_key(self):
        q = fx("imageYesNo")
        self.assertTrue(all(i["correctAnswer"] is None for i in q["items"]))
        self.assertIsNone(C.grade(q, {})["score"])

    def test_04_dropdown_all_correct(self):
        self.assertEqual(C.grade(fx("demoDropdown"), CORRECT_D)["score"], 1)

    def test_05_dropdown_all_or_nothing_one_wrong(self):
        self.assertEqual(C.grade(fx("demoDropdown"), {"sum": "o1", "product": "o2"})["score"], 0)

    def test_06_dropdown_per_part_half(self):
        q = fx("demoDropdown"); q["scoring"].update(mode="per_part", maxScore=10)
        self.assertEqual(C.grade(q, {"sum": "o1", "product": "o2"})["score"], 5)

    def test_07_unanswered_is_incomplete_not_zero(self):
        r = C.grade(fx("demoDropdown"), {"sum": "o2"})
        self.assertEqual(r["status"], "incomplete"); self.assertIsNone(r["score"])
        self.assertEqual(r["unansweredIds"], ["product"])

    def test_08_allow_incomplete_scores_blank_zero(self):
        q = fx("demoDropdown"); q["scoring"]["mode"] = "per_part"
        self.assertEqual(C.grade(q, {"sum": "o2"}, allow_incomplete=True)["score"], 0.5)

    def test_09_false_is_valid_no(self):
        r = C.grade(fx("demoYesNo"), CORRECT_Y)
        self.assertEqual(r["status"], "graded"); self.assertEqual(r["score"], 1)
        self.assertEqual(r["unansweredIds"], [])

    def test_10_unanswered_is_not_no(self):
        r = C.grade(fx("demoYesNo"), {"s1": True, "s3": True})
        self.assertEqual(r["status"], "incomplete"); self.assertEqual(r["unansweredIds"], ["s2"])

    def test_11_yesno_per_part(self):
        q = fx("demoYesNo"); q["scoring"].update(mode="per_part", maxScore=3)
        self.assertEqual(C.grade(q, {"s1": True, "s2": True, "s3": True})["score"], 2)

    def test_12_string_false_is_invalid(self):
        self.assertEqual(C.grade(fx("demoYesNo"), {**CORRECT_Y, "s2": "false"})["status"], "invalid")

    def test_13_zero_is_not_false(self):
        self.assertEqual(C.grade(fx("demoYesNo"), {**CORRECT_Y, "s2": 0})["status"], "invalid")

    def test_14_unknown_item_invalid(self):
        self.assertEqual(C.grade(fx("demoDropdown"), {**CORRECT_D, "ghost": "o1"})["status"], "invalid")

    def test_15_unknown_option_invalid(self):
        self.assertEqual(C.grade(fx("demoDropdown"), {"sum": "removed", "product": "o2"})["status"], "invalid")

    def test_16_item_reorder_keeps_ids(self):
        q = fx("demoDropdown"); q["items"].reverse()
        self.assertEqual(C.grade(q, CORRECT_D)["score"], 1)

    def test_17_option_reorder_keeps_key(self):
        q = fx("demoDropdown"); q["items"][0]["options"].reverse()
        self.assertEqual(C.grade(q, CORRECT_D)["score"], 1)

    def test_18_same_text_still_by_id(self):
        q = fx("demoDropdown"); q["items"][0]["options"][0]["text"] = q["items"][0]["options"][1]["text"]
        self.assertEqual(C.grade(q, {"sum": "o1", "product": "o2"})["score"], 0)

    def test_19_deleting_selected_option_clears_stale_answer(self):
        q = fx("demoDropdown"); q["items"][0]["options"] = [o for o in q["items"][0]["options"] if o["id"] != "o2"]
        self.assertEqual(C.sanitize_answers(q, CORRECT_D), {"product": "o2"})

    def test_20_text_edit_keeps_id_and_key(self):
        q = fx("demoDropdown"); q["items"][0]["options"][1]["text"] = "五"
        self.assertEqual(C.grade(q, CORRECT_D)["score"], 1)

    def test_21_duplicate_item_id_rejected(self):
        q = fx("demoDropdown"); q["items"][1]["id"] = "sum"
        self.assertTrue(any(e["path"].endswith(".id") for e in C.validate(q)))

    def test_22_duplicate_option_id_rejected(self):
        q = fx("demoDropdown"); q["items"][0]["options"][0]["id"] = "o2"
        self.assertTrue(C.validate(q))

    def test_23_columns_may_share_local_option_ids(self):
        self.assertEqual(C.validate(fx("demoDropdown")), [])

    def test_24_missing_key_option_rejected(self):
        q = fx("demoDropdown"); q["items"][0]["correctAnswer"] = "deleted"
        self.assertTrue(C.validate(q))

    def test_25_ready_requires_key(self):
        q = fx("demoYesNo"); q["items"][0]["correctAnswer"] = None
        self.assertTrue(C.validate(q))

    def test_26_draft_may_store_null_key(self):
        self.assertEqual(C.validate(fx("imageYesNo")), [])

    def test_27_bad_max_scores(self):
        for n in (0, -1, math.nan, math.inf, 1000001, True):
            with self.subTest(n=n):
                q = fx("demoDropdown"); q["scoring"]["maxScore"] = n
                self.assertTrue(C.validate(q))

    def test_28_empty_items_blank_title_bad_id(self):
        for mutate in (lambda q: q.update(items=[]), lambda q: q.update(title=" "),
                       lambda q: q["items"][0].update(id="bad id")):
            q = fx("demoDropdown"); mutate(q)
            self.assertTrue(C.validate(q))

    def test_29_at_least_two_options(self):
        q = fx("demoDropdown"); q["items"][0]["options"] = q["items"][0]["options"][:1]
        self.assertTrue(C.validate(q))

    def test_30_ready_prompt_not_blank(self):
        q = fx("demoDropdown"); q["prompt"] = " "
        self.assertTrue(C.validate(q))

    def test_31_json_roundtrip_keeps_false_and_ids(self):
        q = json.loads(json.dumps(fx("demoYesNo"))); a = json.loads(json.dumps(CORRECT_Y))
        self.assertIs(a["s2"], False)
        self.assertEqual(C.grade(q, a)["score"], 1)

    def test_32_candidate_dto_hides_keys_and_explanations(self):
        q = fx("demoYesNo"); q["explanation"] = "secret"; q["items"][0]["explanation"] = "secret"
        dto = C.for_candidate(q); text = json.dumps(dto, ensure_ascii=False)
        self.assertNotIn("correctAnswer", text); self.assertNotIn("secret", text)
        self.assertEqual(len(dto["items"]), 3)

    def test_33_grade_does_not_mutate(self):
        q = fx("demoDropdown"); a = dict(CORRECT_D); before = json.dumps([q, a])
        C.grade(q, a)
        self.assertEqual(json.dumps([q, a]), before)

    def test_34_unknown_field_rejected(self):
        q = fx("demoDropdown"); q["unknown"] = "x"
        self.assertTrue(C.validate(q))

    def test_35_draft_key_must_be_explicit_null(self):
        q = fx("imageDropdown"); del q["items"][0]["correctAnswer"]
        self.assertTrue(C.validate(q))

    def test_36_six_decimal_rounding(self):
        q = fx("demoYesNo"); q["scoring"]["mode"] = "per_part"
        self.assertEqual(C.grade(q, {"s1": True, "s2": True, "s3": False})["score"], 0.333333)

    def test_37_null_and_empty_string_are_unanswered(self):
        self.assertEqual(C.grade(fx("demoDropdown"), {"sum": None, "product": ""})["status"], "incomplete")


if __name__ == "__main__":
    unittest.main()
