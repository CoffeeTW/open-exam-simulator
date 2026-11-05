"""題庫、作答工作階段、SQLite 儲存與 JSON 匯入匯出。"""
import json
import random
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from oes.storage.exam_file import ExamFileError, load_exam, save_exam
from oes.storage.history import HistoryStore
from tests.helpers import CORRECT_D, CORRECT_Y, FIXTURES, fx


def sample_exam():
    ex = E.new_exam("測試題庫")
    sec = E.add_section(ex, "第一章")
    ex["questions"].append({"sectionId": sec["id"], "question": fx("demoDropdown")})
    ex["questions"].append({"sectionId": None, "question": fx("demoYesNo")})
    ex["questions"].append({"sectionId": None, "question": fx("imageDropdown")})  # 草稿、無正解
    return ex


class ExamTests(unittest.TestCase):
    def test_new_exam_valid(self):
        self.assertEqual(E.validate_exam(sample_exam(), strict_questions=True), [])

    def test_add_question_unique_ids(self):
        ex = E.new_exam()
        ids = {E.add_question(ex, t)["id"] for t in C.TYPES for _ in range(5)}
        self.assertEqual(len(ids), len(C.TYPES) * 5)

    def test_remove_section_detaches_questions(self):
        ex = sample_exam(); E.remove_section(ex, ex["sections"][0]["id"])
        self.assertIsNone(ex["questions"][0]["sectionId"])
        self.assertEqual(E.validate_exam(ex), [])

    def test_duplicate_question_id_detected(self):
        ex = sample_exam(); ex["questions"][1]["question"]["id"] = "demo-dropdown"
        self.assertTrue(E.validate_exam(ex))


class ImportExportTests(unittest.TestCase):
    def test_exam_roundtrip(self):
        ex = sample_exam()
        kind, data = E.parse_import(E.export_exam_json(ex))
        self.assertEqual(kind, "exam"); self.assertEqual(data, ex)
        self.assertIs(data["questions"][1]["question"]["items"][1]["correctAnswer"], False)

    def test_fixture_mapping_and_single_and_list(self):
        self.assertEqual(len(E.parse_import(json.dumps(FIXTURES))[1]), 4)
        self.assertEqual(len(E.parse_import(json.dumps(FIXTURES["demoYesNo"]))[1]), 1)
        self.assertEqual(len(E.parse_import(json.dumps(list(FIXTURES.values())))[1]), 4)

    def test_readable_errors(self):
        with self.assertRaises(E.ImportErrorWithDetails) as ctx:
            E.parse_import("{bad json")
        self.assertIn("不是有效的 JSON", str(ctx.exception))
        q = fx("demoYesNo"); q["items"][0]["correctAnswer"] = "false"
        with self.assertRaises(E.ImportErrorWithDetails) as ctx:
            E.parse_import(json.dumps(q))
        self.assertIn("items[0].correctAnswer", str(ctx.exception))

    def test_merge_renames_conflicting_ids(self):
        ex = sample_exam()
        renamed = E.merge_questions(ex, [fx("demoYesNo")])
        self.assertEqual(renamed[0][0], "demo-yes-no")
        self.assertEqual(E.validate_exam(ex), [])


class SessionTests(unittest.TestCase):
    def test_only_fully_keyed_questions_used(self):
        s = S.build_session(sample_exam())
        self.assertEqual(len(s["questions"]), 2); self.assertEqual(s["excludedCount"], 1)
        self.assertNotIn("correctAnswer", json.dumps([q["presented"] for q in s["questions"]]))

    def test_section_filter_and_limit(self):
        ex = sample_exam()
        s = S.build_session(ex, section_ids=[ex["sections"][0]["id"]])
        self.assertEqual([q["question"]["id"] for q in s["questions"]], ["demo-dropdown"])
        self.assertEqual(s["questions"][0]["sectionName"], "第一章")
        self.assertEqual(len(S.build_session(ex, limit=1)["questions"]), 1)

    def test_no_usable_questions(self):
        ex = E.new_exam(); ex["questions"].append({"sectionId": None, "question": fx("imageYesNo")})
        with self.assertRaises(ValueError):
            S.build_session(ex)

    def test_full_score_and_pass(self):
        s = S.build_session(sample_exam())
        S.set_answer(s, "demo-dropdown", CORRECT_D); S.set_answer(s, "demo-yes-no", CORRECT_Y)
        self.assertEqual(S.unanswered_count(s), 0)
        r = S.finish(s)
        self.assertEqual((r["score"], r["maxScore"], r["percent"], r["passed"]), (2, 2, 100.0, True))
        self.assertEqual(r["sections"][0]["name"], "第一章")
        with self.assertRaises(ValueError):
            S.set_answer(s, "demo-yes-no", {})

    def test_partial_and_unanswered(self):
        s = S.build_session(sample_exam())
        S.set_answer(s, "demo-yes-no", {"s1": True, "s3": True})
        self.assertEqual(S.question_progress(s, "demo-yes-no"), "partial")
        self.assertEqual(S.question_progress(s, "demo-dropdown"), "unanswered")
        r = S.finish(s)
        self.assertEqual(r["score"], 0); self.assertFalse(r["passed"])
        row = [q for q in r["questions"] if q["questionId"] == "demo-yes-no"][0]
        self.assertEqual(row["unansweredIds"], ["s2"])

    def test_set_answer_drops_foreign_values(self):
        s = S.build_session(sample_exam())
        S.set_answer(s, "demo-yes-no", {"s1": "true", "ghost": True, "s2": False})
        self.assertEqual(s["answers"]["demo-yes-no"], {"s2": False})

    def test_snapshot_isolated_from_exam_edits(self):
        ex = sample_exam(); s = S.build_session(ex)
        ex["questions"][0]["question"]["items"][0]["correctAnswer"] = "o1"
        S.set_answer(s, "demo-dropdown", CORRECT_D)
        self.assertEqual(S.finish(s)["questions"][0]["score"], 1)

    def test_shuffle_options_keeps_ids(self):
        q = C.new_question("multiple_choice", "mc")
        q.update(status="ready", prompt="p", shuffle=True, correctAnswer=["o3"])
        ex = E.new_exam(); ex["questions"].append({"sectionId": None, "question": q})
        s = S.build_session(ex, rng=random.Random(3))
        self.assertEqual(sorted(o["id"] for o in s["questions"][0]["presented"]["options"]), ["o1", "o2", "o3", "o4"])
        S.set_answer(s, "mc", {"selected": ["o3"]})
        self.assertEqual(S.finish(s)["score"], 1)

    def test_retake_incorrect(self):
        s = S.build_session(sample_exam())
        S.set_answer(s, "demo-dropdown", CORRECT_D); S.finish(s)
        again = S.retake(s, "incorrect")
        self.assertEqual([q["question"]["id"] for q in again["questions"]], ["demo-yes-no"])
        self.assertEqual(again["status"], "in_progress")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_save_load_roundtrip(self):
        ex = sample_exam(); ex["questions"].reverse()
        path = self.dir / "題庫.oes"
        save_exam(path, ex)
        self.assertEqual(load_exam(path), ex)
        loaded = load_exam(path)
        self.assertIs(loaded["questions"][1]["question"]["items"][1]["correctAnswer"], False)

    def test_resave_overwrites_and_keeps_order(self):
        ex = sample_exam(); path = self.dir / "a.oes"
        save_exam(path, ex)
        ex["questions"].insert(0, ex["questions"].pop())
        ex["questions"][0]["question"]["items"][0]["options"].reverse()
        save_exam(path, ex)
        self.assertEqual(load_exam(path), ex)
        self.assertEqual(list(self.dir.glob(".oes-*")), [])

    def test_updated_at_only_changes_for_modified(self):
        ex = sample_exam(); path = self.dir / "a.oes"
        save_exam(path, ex)
        con = sqlite3.connect(path); con.execute("UPDATE questions SET updated_at='old'"); con.commit(); con.close()
        ex["questions"][0]["question"]["title"] = "改了"
        save_exam(path, ex)
        con = sqlite3.connect(path)
        rows = dict(con.execute("SELECT id, updated_at FROM questions")); con.close()
        self.assertNotEqual(rows["demo-dropdown"], "old"); self.assertEqual(rows["demo-yes-no"], "old")

    def test_bad_files(self):
        with self.assertRaises(ExamFileError):
            load_exam(self.dir / "missing.oes")
        junk = self.dir / "junk.oes"; junk.write_bytes(b"not sqlite at all" * 100)
        with self.assertRaises(ExamFileError):
            load_exam(junk)

    def test_history_save_resume_and_list(self):
        store = HistoryStore(self.dir / "h.db")
        s = S.build_session(sample_exam(), candidate="王小明")
        S.set_answer(s, "demo-yes-no", {"s2": False}); s["currentIndex"] = 1
        store.save(s)
        resumed = store.load(s["id"])
        self.assertEqual(resumed, s); self.assertIs(resumed["answers"]["demo-yes-no"]["s2"], False)
        S.finish(resumed); store.save(resumed)
        rows = store.list(s["examId"])
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]["status"], "finished")
        self.assertEqual(rows[0]["passed"], 0)
        store.delete(s["id"]); self.assertEqual(store.list(), [])


if __name__ == "__main__":
    unittest.main()


class HistoryLocationTests(unittest.TestCase):
    def setUp(self):
        import os
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.saved = os.environ.pop("OES_DATA_DIR", None)

    def tearDown(self):
        import os
        if self.saved is not None:
            os.environ["OES_DATA_DIR"] = self.saved
        self.tmp.cleanup()

    def test_default_is_program_folder(self):
        from oes.storage.history import app_dir, default_history_path
        app = self.dir / "app"
        self.assertEqual(default_history_path(app, self.dir / "legacy"), app / "history.db")
        self.assertEqual(app_dir(), Path(__file__).resolve().parents[1])

    def test_copies_legacy_history_once(self):
        from oes.storage.history import default_history_path
        legacy = self.dir / "legacy"
        store = HistoryStore(legacy / "history.db")
        store.save(S.build_session(sample_exam()))
        app = self.dir / "app"
        path = default_history_path(app, legacy)
        self.assertTrue(path.is_file())
        self.assertEqual(len(HistoryStore(path).list()), 1)
        self.assertTrue((legacy / "history.db").is_file())

    def test_unwritable_program_folder_falls_back(self):
        from oes.storage.history import default_history_path
        blocker = self.dir / "not-a-folder"
        blocker.write_text("x")
        self.assertEqual(default_history_path(blocker, self.dir / "legacy"), self.dir / "legacy" / "history.db")

    def test_env_override(self):
        import os
        from oes.storage.history import default_history_path
        os.environ["OES_DATA_DIR"] = str(self.dir / "custom")
        try:
            self.assertEqual(default_history_path(self.dir / "app"), self.dir / "custom" / "history.db")
        finally:
            del os.environ["OES_DATA_DIR"]
