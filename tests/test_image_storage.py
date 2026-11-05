"""圖片改存二進位、相同圖片只存一份：題庫檔（.oes 第 3 版）與作答紀錄（history.db 第 2 版）。"""
import base64
import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oes.core import exam as E
from oes.core import question_types as C
from oes.core import session as S
from oes.storage import blobs
from oes.storage.exam_file import FILE_VERSION, load_exam, save_exam
from oes.storage.history import HISTORY_VERSION, HistoryStore
from tests.helpers import fx

# 兩張不同的 PNG（同一張圖重複使用時應只存一份）
PNG_A = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
PNG_B = PNG_A + b"\x00" * 3000  # 尾端多餘資料不影響解碼，用來做出較大的圖片


def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def question_with(images, qid):
    q = fx("demoYesNo")
    q["id"] = qid
    q["status"] = "ready"
    q["prompt"] = "看圖：\n" + "\n".join("{{image:%s}}" % image["id"] for image in images)
    q["images"] = images
    return q


def image_exam():
    exam = E.new_exam("圖片題庫")
    shared = {"id": "img1", "mime": "image/png", "data": b64(PNG_B), "width": 300}
    exam["questions"].append({"sectionId": None, "question": question_with([dict(shared)], "q1")})
    exam["questions"].append({"sectionId": None, "question": question_with(
        [dict(shared), {"id": "img2", "mime": "image/webp", "data": b64(PNG_A)}], "q2")})
    case = E.add_case_study(exam, "案例")
    case["text"] = "{{image:img1}}"
    case["images"] = [dict(shared)]
    exam["questions"][0]["caseStudyId"] = case["id"]
    return exam


class BlobTests(unittest.TestCase):
    def test_externalize_roundtrip_and_dedupe(self):
        exam = image_exam()
        original = copy.deepcopy(exam)
        found = {}
        stored = blobs.externalize(exam, found)
        self.assertEqual(exam, original)  # 不修改原物件
        self.assertEqual(len(found), 2)   # img1 出現 3 次只存一份
        text = json.dumps(stored)
        self.assertNotIn(b64(PNG_B), text)
        self.assertEqual(len(blobs.blob_refs(stored)), 2)
        restored = blobs.internalize(stored, lambda refs: {d: found[d][1] for d in refs})
        self.assertEqual(restored, original)
        self.assertEqual(list(restored["questions"][1]["question"]["images"][1]), ["id", "mime", "data"])

    def test_missing_blob_becomes_empty(self):
        stored = blobs.externalize({"images": [{"id": "i", "mime": "image/png", "data": b64(PNG_A)}]}, {})
        restored = blobs.internalize(stored, lambda refs: {})
        self.assertEqual(restored, {"images": [{"id": "i", "mime": "image/png", "data": ""}]})

    def test_invalid_base64_left_alone(self):
        value = {"images": [{"id": "i", "mime": "image/png", "data": "not base64!!"}]}
        self.assertEqual(blobs.externalize(value, {}), value)

    def test_webp_mime_accepted(self):
        q = question_with([{"id": "img1", "mime": "image/webp", "data": b64(PNG_A)}], "q1")
        self.assertEqual(C.validate(q), [])


class ExamFileImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "圖片.oes"

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_stores_each_image_once(self):
        exam = image_exam()
        save_exam(self.path, exam)
        con = sqlite3.connect(self.path)
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], FILE_VERSION)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM images").fetchone()[0], 2)
            raw = dict(con.execute("SELECT mime, data FROM images WHERE length(data) > 100").fetchall())
            self.assertEqual(raw["image/png"], PNG_B)  # 二進位，不是 base64
            for (data,) in con.execute("SELECT data FROM questions"):
                self.assertNotIn('"data"', data)
            meta = dict(con.execute("SELECT key, value FROM meta"))
            self.assertNotIn('"data"', meta["caseStudies"])
        finally:
            con.close()
        loaded = load_exam(self.path)
        self.assertEqual(loaded["questions"], exam["questions"])
        self.assertEqual(loaded["caseStudies"], exam["caseStudies"])
        self.assertEqual(E.validate_exam(loaded, strict_questions=True), [])

    def test_smaller_than_inline_base64(self):
        exam = image_exam()
        big = b64(PNG_A + os.urandom(300_000))  # 約 300 KB 的截圖，三個地方使用
        for images in ([e["question"]["images"][0] for e in exam["questions"]] + [exam["caseStudies"][0]["images"][0]]):
            images["data"] = big
        save_exam(self.path, exam)
        size = self.path.stat().st_size
        self.assertLess(size, 360_000)  # 舊格式要存三份 base64，約 1.2 MB
        self.assertGreater(len(json.dumps(exam)), 1_150_000)

    def test_updated_at_kept_when_unchanged(self):
        exam = image_exam()
        save_exam(self.path, exam)
        con = sqlite3.connect(self.path)
        first = dict(con.execute("SELECT id, updated_at FROM questions"))
        con.close()
        save_exam(self.path, load_exam(self.path))
        con = sqlite3.connect(self.path)
        self.assertEqual(dict(con.execute("SELECT id, updated_at FROM questions")), first)
        con.close()

    def test_reads_version_2_inline_images(self):
        exam = image_exam()
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE sections (id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, name TEXT NOT NULL);
            CREATE TABLE questions (id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, section_id TEXT,
                case_study_id TEXT, type TEXT NOT NULL, status TEXT NOT NULL, title TEXT NOT NULL,
                data TEXT NOT NULL, updated_at TEXT NOT NULL);
            PRAGMA user_version = 2;
        """)
        meta = {"format": E.EXAM_FORMAT, "schemaVersion": E.EXAM_SCHEMA_VERSION, "id": exam["id"],
                "title": exam["title"], "caseStudies": exam["caseStudies"]}
        con.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v)) for k, v in meta.items()])
        for i, entry in enumerate(exam["questions"]):
            q = entry["question"]
            con.execute("INSERT INTO questions VALUES (?,?,?,?,?,?,?,?,?)",
                        (q["id"], i, None, entry.get("caseStudyId"), q["type"], q["status"], "",
                         json.dumps(q), "2026-01-01"))
        con.commit()
        con.close()
        loaded = load_exam(self.path)
        self.assertEqual(loaded["questions"], exam["questions"])
        self.assertEqual(loaded["caseStudies"], exam["caseStudies"])


class HistoryImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "history.db"

    def tearDown(self):
        self.tmp.cleanup()

    def count(self, table):
        con = sqlite3.connect(self.path)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            con.close()

    def test_sessions_share_images(self):
        store = HistoryStore(self.path)
        exam = image_exam()
        first = S.build_session(exam)
        second = S.build_session(exam)
        store.save(first)
        store.save(second)
        store.save(first)  # 自動存檔重複寫入
        self.assertEqual(self.count("images"), 2)
        con = sqlite3.connect(self.path)
        for (data,) in con.execute("SELECT data FROM sessions"):
            self.assertNotIn(b64(PNG_B), data)
        con.close()
        self.assertEqual(store.load(first["id"]), json.loads(json.dumps(first)))
        store.delete(first["id"])
        self.assertEqual(self.count("images"), 2)  # 第二次作答仍在使用
        self.assertEqual(store.load(second["id"]), json.loads(json.dumps(second)))
        store.delete(second["id"])
        self.assertEqual(self.count("images"), 0)

    def test_migrates_old_history(self):
        session = S.build_session(image_exam())
        con = sqlite3.connect(self.path)
        con.executescript("""
            CREATE TABLE sessions (id TEXT PRIMARY KEY, exam_id TEXT, exam_title TEXT NOT NULL,
                candidate TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, finished_at TEXT, percent REAL, passed INTEGER, data TEXT NOT NULL);
        """)
        con.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (session["id"], session.get("examId"), "t", "", "exam", session["status"],
                     session["startedAt"], session["updatedAt"], None, None, None, json.dumps(session)))
        con.commit()
        con.close()
        store = HistoryStore(self.path)
        con = sqlite3.connect(self.path)
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], HISTORY_VERSION)
            data = con.execute("SELECT data FROM sessions").fetchone()[0]
        finally:
            con.close()
        self.assertNotIn(b64(PNG_B), data)
        self.assertEqual(self.count("images"), 2)
        self.assertEqual(store.load(session["id"]), json.loads(json.dumps(session)))
        HistoryStore(self.path)  # 再次開啟不會重複轉換
        self.assertEqual(store.load(session["id"]), json.loads(json.dumps(session)))


if __name__ == "__main__":
    unittest.main()
