"""排序題、拖放題、熱區題與案例研究。"""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from oes.storage.exam_file import load_exam, save_exam
from tests.test_images import PNG_1PX


def build_list(**kw):
    q = C.new_question("build_list", "bl")
    q.update(status="ready", prompt="排出正確步驟", correctAnswer=["c3", "c1", "c2"])
    q.update(kw)
    return q


def drag_drop(**kw):
    q = C.new_question("drag_drop", "dd")
    q.update(status="ready", prompt="把值放到正確位置")
    q["targets"][0]["correctAnswer"] = "v2"
    q["targets"][1]["correctAnswer"] = "v4"
    q.update(kw)
    return q


def hot_area():
    q = C.new_question("hot_area", "ha")
    q.update(status="ready", prompt="點選正確的區域", background="img1",
             images=[{"id": "img1", "mime": "image/png", "data": PNG_1PX}],
             areas=[{"id": "a1", "x": 0, "y": 0, "w": 10, "h": 10},
                    {"id": "a2", "x": 20, "y": 0, "w": 10, "h": 10},
                    {"id": "a3", "x": 40, "y": 0, "w": 10, "h": 10}],
             correctAnswer=["a2", "a3"])
    return q


class BuildListTests(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(C.validate(build_list()), [])

    def test_order_matters(self):
        q = build_list()
        self.assertEqual(C.grade(q, {"sequence": ["c3", "c1", "c2"]})["score"], 1)
        self.assertEqual(C.grade(q, {"sequence": ["c1", "c3", "c2"]})["score"], 0)
        self.assertEqual(C.grade(q, {"sequence": ["c3", "c1"]})["score"], 0)
        self.assertEqual(C.grade(q, {"sequence": ["c3", "c1", "c2", "c4"]})["score"], 0)

    def test_order_ignored(self):
        q = build_list(orderMatters=False)
        self.assertEqual(C.grade(q, {"sequence": ["c2", "c3", "c1"]})["score"], 1)
        self.assertEqual(C.grade(q, {"sequence": ["c2", "c3", "c1", "c4"]})["score"], 0)

    def test_unanswered_and_invalid(self):
        q = build_list()
        self.assertEqual(C.grade(q, {"sequence": []})["status"], "incomplete")
        for bad in ({"sequence": ["zz"]}, {"sequence": ["c1", "c1"]}, {"sequence": "c1"}, {"x": 1}):
            with self.subTest(bad=bad):
                self.assertEqual(C.grade(q, bad)["status"], "invalid")

    def test_reorder_only_requires_all(self):
        q = build_list(reorderOnly=True)
        self.assertTrue(C.validate(q))
        q["correctAnswer"] = ["c4", "c3", "c2", "c1"]
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.grade(q, {"sequence": ["c4", "c3"]})["status"], "invalid")
        self.assertEqual(C.grade(q, {"sequence": ["c4", "c3", "c2", "c1"]})["score"], 1)

    def test_delete_choice_in_key(self):
        q = build_list()
        self.assertTrue(C.remove_option(q, "c1"))
        self.assertEqual(q["correctAnswer"], ["c3", "c2"])
        self.assertEqual(q["status"], "draft")
        self.assertFalse(C.remove_option(q, "c4"))

    def test_candidate_and_summary(self):
        dto = C.for_candidate(build_list())
        self.assertNotIn("correctAnswer", json.dumps(dto))
        self.assertEqual(len(dto["choices"]), 4)
        self.assertEqual(C.summarize_selection(build_list(), {"id": "answer"}, ["c3", "c1"]), "步驟 3 → 步驟 1")


class DragDropTests(unittest.TestCase):
    def test_valid_and_grade(self):
        q = drag_drop()
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.grade(q, {"t1": "v2", "t2": "v4"})["score"], 1)
        q["scoring"]["mode"] = "per_part"
        self.assertEqual(C.grade(q, {"t1": "v2", "t2": "v1"})["score"], 0.5)

    def test_incomplete(self):
        r = C.grade(drag_drop(), {"t1": "v2"})
        self.assertEqual(r["status"], "incomplete"); self.assertEqual(r["unansweredIds"], ["t2"])

    def test_reuse_rules(self):
        q = drag_drop()
        self.assertEqual(C.grade(q, {"t1": "v2", "t2": "v2"})["status"], "invalid")
        q["targets"][1]["correctAnswer"] = "v2"
        self.assertTrue(C.validate(q))
        q["reuseSources"] = True
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.grade(q, {"t1": "v2", "t2": "v2"})["score"], 1)

    def test_invalid_answers(self):
        for bad in ({"t1": "zz"}, {"ghost": "v1"}, {"t1": 1}):
            with self.subTest(bad=bad):
                self.assertEqual(C.grade(drag_drop(), bad)["status"], "invalid")

    def test_delete_source_clears_key(self):
        q = drag_drop()
        self.assertTrue(C.remove_option(q, "v2"))
        self.assertIsNone(q["targets"][0]["correctAnswer"]); self.assertEqual(q["status"], "draft")

    def test_sanitize_drops_duplicates_without_reuse(self):
        self.assertEqual(C.sanitize_answers(drag_drop(), {"t1": "v1", "t2": "v1"}), {"t1": "v1"})

    def test_candidate(self):
        dto = C.for_candidate(drag_drop())
        self.assertNotIn("correctAnswer", json.dumps(dto))
        self.assertEqual([t["id"] for t in dto["targets"]], ["t1", "t2"])


class HotAreaTests(unittest.TestCase):
    def test_valid_and_grade(self):
        q = hot_area()
        self.assertEqual(C.validate(q), [])
        self.assertEqual(C.grade(q, {"selected": ["a3", "a2"]})["score"], 1)
        self.assertEqual(C.grade(q, {"selected": ["a2"]})["score"], 0)
        self.assertEqual(C.grade(q, {"selected": ["a1", "a2", "a3"]})["score"], 0)
        self.assertEqual(C.grade(q, {"selected": ["zz"]})["status"], "invalid")

    def test_background_required_and_referenced(self):
        q = hot_area(); q["background"] = None
        self.assertTrue(C.validate(q))
        q = hot_area(); del q["images"]
        self.assertTrue(any(e["path"] == "background" for e in C.validate(q)))
        self.assertEqual(C.question_image_refs(hot_area()), ["img1"])

    def test_draft_template_valid(self):
        self.assertEqual(C.validate(C.new_question("hot_area", "h")), [])

    def test_bad_area(self):
        q = hot_area(); q["areas"][0]["w"] = 2
        self.assertTrue(C.validate(q))
        q = hot_area(); q["areas"][0]["x"] = -1
        self.assertTrue(C.validate(q))

    def test_candidate_has_background_not_key(self):
        dto = C.for_candidate(hot_area())
        self.assertEqual(dto["images"][0]["id"], "img1")
        self.assertNotIn("correctAnswer", json.dumps(dto))

    def test_delete_area(self):
        q = hot_area()
        self.assertTrue(C.remove_option(q, "a2"))
        self.assertEqual(q["correctAnswer"], ["a3"])


class CaseStudyTests(unittest.TestCase):
    def exam(self):
        ex = E.new_exam()
        case = E.add_case_study(ex, "示範公司")
        case["text"] = "情境說明\n{{image:img1}}"
        case["images"] = [{"id": "img1", "mime": "image/png", "data": PNG_1PX}]
        ex["questions"].append({"sectionId": None, "caseStudyId": case["id"], "question": build_list()})
        ex["questions"].append({"sectionId": None, "question": drag_drop()})
        return ex

    def test_validate(self):
        ex = self.exam()
        self.assertEqual(E.validate_exam(ex, strict_questions=True), [])
        ex["questions"][0]["caseStudyId"] = "nope"
        self.assertTrue(E.validate_exam(ex))
        ex = self.exam(); ex["caseStudies"][0]["images"] = []
        self.assertTrue(E.validate_exam(ex))

    def test_remove_case_detaches(self):
        ex = self.exam(); E.remove_case_study(ex, "case1")
        self.assertNotIn("caseStudyId", ex["questions"][0])
        self.assertEqual(E.validate_exam(ex), [])

    def test_session_carries_case(self):
        s = S.build_session(self.exam())
        self.assertEqual(s["questions"][0]["caseStudy"]["name"], "示範公司")
        self.assertIsNone(s["questions"][1]["caseStudy"])

    def test_file_and_json_roundtrip(self):
        ex = self.exam()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.oes"
            save_exam(path, ex)
            self.assertEqual(load_exam(path), ex)
        self.assertEqual(E.parse_import(E.export_exam_json(ex))[1], ex)

    def test_old_file_without_case_column_still_opens(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.oes"
            ex = E.new_exam(); ex["questions"].append({"sectionId": None, "question": drag_drop()})
            save_exam(path, ex)
            con = sqlite3.connect(path)
            con.execute("ALTER TABLE questions DROP COLUMN case_study_id")
            con.execute("DELETE FROM meta WHERE key='caseStudies'")
            con.execute("PRAGMA user_version = 1"); con.commit(); con.close()
            loaded = load_exam(path)
            self.assertEqual(loaded["caseStudies"], [])
            self.assertEqual(loaded["questions"], ex["questions"])


class DragDropScriptTests(unittest.TestCase):
    """指令腳本式拖放：空格後文字、左側標題、程式碼字型（皆為選填）。"""

    def script(self):
        q = drag_drop(reuseSources=True, sourcesTitle="Cmdlets", codeFont=True)
        q["targets"][0].update(label="", suffix="-Name 'Group1' -GroupScope Global")
        q["targets"][1].update(label="", suffix="-Identity 'Group1' -Members 'user1'")
        return q

    def test_valid_and_candidate(self):
        q = self.script()
        self.assertEqual(C.validate(q), [])
        dto = C.for_candidate(q)
        self.assertEqual((dto["sourcesTitle"], dto["codeFont"]), ("Cmdlets", True))
        self.assertEqual(dto["targets"][0], {"id": "t1", "label": "", "suffix": "-Name 'Group1' -GroupScope Global"})
        self.assertNotIn("correctAnswer", dto["targets"][0])

    def test_old_questions_get_defaults(self):
        dto = C.for_candidate(drag_drop())
        self.assertEqual((dto["sourcesTitle"], dto["codeFont"], dto["targets"][0]["suffix"]), ("", False, ""))

    def test_bad_optional_fields(self):
        for mutate, path in ((lambda q: q.update(sourcesTitle=1), "sourcesTitle"),
                             (lambda q: q.update(codeFont="yes"), "codeFont"),
                             (lambda q: q["targets"][0].update(suffix=None), "targets[0].suffix")):
            q = self.script()
            mutate(q)
            with self.subTest(path=path):
                self.assertTrue(any(e["path"] == path for e in C.validate(q)))

    def test_per_part_scoring_with_reuse(self):
        q = self.script()
        q["scoring"] = {"mode": "per_part", "maxScore": 2}
        result = C.grade(q, {"t1": "v2", "t2": "v2"})
        self.assertEqual((result["score"], result["correctCount"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
