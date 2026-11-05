"""題庫檔（.oes）讀寫。

.oes 是 SQLite 資料庫：meta（題庫屬性）、sections（章節順序）、questions（題目 JSON 與順序）、
images（圖片二進位資料，以 SHA-256 為鍵；相同圖片只存一份，題目 JSON 中以 {"blob": 雜湊} 引用）。
儲存時先寫入同目錄的暫存檔再整檔替換，避免寫到一半當機而損毀原檔。
"""
from __future__ import annotations

from ..i18n import tr

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..core.exam import EXAM_FORMAT, EXAM_SCHEMA_VERSION
from .blobs import externalize, internalize

# 2：加入案例研究（meta.caseStudies、questions.case_study_id）
# 3：圖片改存 images 資料表（二進位、相同圖片只存一份）；仍可讀取 1、2 版
FILE_VERSION = 3
FILE_EXTENSION = ".oes"
_META_FIELDS = ("id", "title", "number", "version", "passingScore", "timeLimitMinutes",
                "description", "showDescription")

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sections (
    id TEXT PRIMARY KEY,
    position INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    position INTEGER NOT NULL UNIQUE,
    section_id TEXT REFERENCES sections(id),
    case_study_id TEXT,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE images (
    hash TEXT PRIMARY KEY,
    mime TEXT NOT NULL,
    data BLOB NOT NULL
);
"""


class ExamFileError(Exception):
    """題庫檔無法讀取或格式不符。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_exam(path: str | os.PathLike, exam: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    previous = _previous_questions(target)
    fd, temp_name = tempfile.mkstemp(prefix=".oes-", suffix=".tmp", dir=str(target.parent))
    os.close(fd)
    try:
        con = sqlite3.connect(temp_name)
        try:
            con.executescript(_SCHEMA)
            con.execute(f"PRAGMA user_version = {FILE_VERSION}")
            meta = {"format": EXAM_FORMAT, "schemaVersion": EXAM_SCHEMA_VERSION}
            meta.update({k: exam.get(k) for k in _META_FIELDS})
            blobs: dict[str, tuple[str, bytes]] = {}
            meta["caseStudies"] = externalize(exam.get("caseStudies", []), blobs)
            con.executemany("INSERT INTO meta(key, value) VALUES (?, ?)",
                            [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
            con.executemany("INSERT INTO sections(id, position, name) VALUES (?, ?, ?)",
                            [(s["id"], i, s["name"]) for i, s in enumerate(exam.get("sections", []))])
            now = _now()
            rows = []
            for i, entry in enumerate(exam.get("questions", [])):
                q = entry["question"]
                data = json.dumps(externalize(q, blobs), ensure_ascii=False, sort_keys=False)
                old = previous.get(q.get("id"))
                updated = old[1] if old and old[0] == data else now
                rows.append((q.get("id"), i, entry.get("sectionId"), entry.get("caseStudyId"), q.get("type", ""),
                             q.get("status", ""), q.get("title", ""), data, updated))
            con.executemany("INSERT INTO questions(id, position, section_id, case_study_id, type, status, title, data,"
                            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
            con.executemany("INSERT INTO images(hash, mime, data) VALUES (?, ?, ?)",
                            [(digest, mime, raw) for digest, (mime, raw) in blobs.items()])
            con.commit()
        finally:
            con.close()
        os.replace(temp_name, target)
    except BaseException:
        try:
            os.remove(temp_name)
        except OSError:
            pass
        raise


def _previous_questions(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return {r[0]: (r[1], r[2]) for r in con.execute("SELECT id, data, updated_at FROM questions")}
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def load_exam(path: str | os.PathLike) -> dict:
    source = Path(path)
    if not source.is_file():
        raise ExamFileError(tr('找不到題庫檔：{0}', source))
    try:
        con = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ExamFileError(tr('無法開啟題庫檔：{0}', exc)) from None
    try:
        try:
            version = con.execute("PRAGMA user_version").fetchone()[0]
            meta = {k: json.loads(v) for k, v in con.execute("SELECT key, value FROM meta")}
            sections = [{"id": r[0], "name": r[1]} for r in
                        con.execute("SELECT id, name FROM sections ORDER BY position")]
            columns = {r[1] for r in con.execute("PRAGMA table_info(questions)")}
            case_column = "case_study_id" if "case_study_id" in columns else "NULL"
            questions = []
            for section_id, case_id, data in con.execute(
                    f"SELECT section_id, {case_column}, data FROM questions ORDER BY position"):
                entry = {"sectionId": section_id, "question": json.loads(data)}
                if case_id is not None:
                    entry["caseStudyId"] = case_id
                questions.append(entry)
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

            def fetch(refs: set[str]) -> dict[str, bytes]:
                if "images" not in tables:
                    return {}
                return {digest: bytes(raw) for digest, raw in con.execute("SELECT hash, data FROM images")
                        if digest in refs}
            internalize(questions, fetch)
            internalize(meta, fetch)
        except (sqlite3.Error, json.JSONDecodeError) as exc:
            raise ExamFileError(tr('不是 Open Exam Simulator 題庫檔，或檔案已損毀：{0}', exc)) from None
    finally:
        con.close()
    if meta.get("format") != EXAM_FORMAT:
        raise ExamFileError(tr('不是 Open Exam Simulator 題庫檔。'))
    if version > FILE_VERSION:
        raise ExamFileError(tr('此題庫檔由較新版本建立，請更新程式後再開啟。'))
    exam = {"format": EXAM_FORMAT, "schemaVersion": meta.get("schemaVersion", EXAM_SCHEMA_VERSION)}
    for key in _META_FIELDS:
        exam[key] = meta.get(key)
    exam["sections"] = sections
    exam["caseStudies"] = meta.get("caseStudies") or []
    exam["questions"] = questions
    return exam
