"""作答紀錄資料庫：保存進行中與已結束的工作階段，供還原作答與成績歷史使用。

題目快照中的圖片另存在 images 資料表（二進位、相同圖片只存一份），session_images 記錄每次作答引用哪些圖片，
刪除紀錄後沒有人引用的圖片會一併清除。
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .blobs import externalize, internalize

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    exam_id TEXT,
    exam_title TEXT NOT NULL,
    candidate TEXT NOT NULL,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT,
    percent REAL,
    passed INTEGER,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_exam ON sessions(exam_id);
CREATE TABLE IF NOT EXISTS images (
    hash TEXT PRIMARY KEY,
    mime TEXT NOT NULL,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS session_images (
    session_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    PRIMARY KEY (session_id, hash)
);
CREATE INDEX IF NOT EXISTS session_images_hash ON session_images(hash);
"""
HISTORY_VERSION = 2  # 2：圖片改存 images 資料表


HISTORY_FILE = "history.db"


def app_dir() -> Path:
    """程式所在資料夾：打包成 EXE 時為 EXE 所在位置，原始碼執行時為專案資料夾（run.bat 所在處）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def resource_dir() -> Path:
    """隨程式附帶的檔案（例如示範題庫）所在位置：打包後為 PyInstaller 的解壓資料夾。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parents[2]


def legacy_data_dir() -> Path:
    """0.2.0 以前的作答紀錄位置（使用者設定檔資料夾）。"""
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "OpenExamSimulator"
    return Path.home() / ".local" / "share" / "OpenExamSimulator"


def _writable(folder: Path) -> bool:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".oes-write-test"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def default_history_path(app_folder: Path | None = None, legacy_folder: Path | None = None) -> Path:
    """作答紀錄預設放在程式（EXE）同一個資料夾。

    - 環境變數 OES_DATA_DIR 可指定其他資料夾。
    - 程式資料夾無法寫入時（例如安裝在 Program Files），改用使用者設定檔資料夾。
    - 第一次使用新位置時，若舊位置已有紀錄，會複製過來（舊檔保留不刪）。
    """
    override = os.environ.get("OES_DATA_DIR")
    if override:
        return Path(override) / HISTORY_FILE
    app_folder = app_folder or app_dir()
    legacy = (legacy_folder or legacy_data_dir()) / HISTORY_FILE
    if not _writable(app_folder):
        return legacy
    target = app_folder / HISTORY_FILE
    if not target.exists() and legacy.is_file():
        try:
            shutil.copy2(legacy, target)
        except OSError:
            pass
    return target


class HistoryStore:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else default_history_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as con:
            con.executescript(_SCHEMA)
            version = con.execute("PRAGMA user_version").fetchone()[0]
        if version < HISTORY_VERSION:
            self._migrate()

    def _migrate(self) -> None:
        """舊版紀錄的圖片原本以 base64 存在 JSON 裡：逐筆改存到 images 資料表，再整理檔案釋放空間。"""
        changed = 0
        with self._connect() as con:
            for session_id, data in con.execute("SELECT id, data FROM sessions").fetchall():
                try:
                    session = json.loads(data)
                except json.JSONDecodeError:
                    continue
                stored = self._store_images(con, session_id, session)
                if stored != data:
                    con.execute("UPDATE sessions SET data = ? WHERE id = ?", (stored, session_id))
                    changed += 1
            con.execute(f"PRAGMA user_version = {HISTORY_VERSION}")
        if changed:
            con = sqlite3.connect(self.path)
            try:
                con.execute("VACUUM")
            except sqlite3.Error:
                pass
            finally:
                con.close()

    @staticmethod
    def _store_images(con: sqlite3.Connection, session_id: str, session: dict) -> str:
        """把圖片寫入 images 資料表，回傳不含圖片資料的 JSON 文字。"""
        blobs: dict[str, tuple[str, bytes]] = {}
        data = json.dumps(externalize(session, blobs), ensure_ascii=False)
        con.executemany("INSERT OR IGNORE INTO images(hash, mime, data) VALUES (?, ?, ?)",
                        [(digest, mime, raw) for digest, (mime, raw) in blobs.items()])
        con.execute("DELETE FROM session_images WHERE session_id = ?", (session_id,))
        con.executemany("INSERT INTO session_images(session_id, hash) VALUES (?, ?)",
                        [(session_id, digest) for digest in blobs])
        return data

    @staticmethod
    def _fetcher(con: sqlite3.Connection):
        def fetch(refs: set[str]) -> dict[str, bytes]:
            found = {}
            for digest in refs:
                row = con.execute("SELECT data FROM images WHERE hash = ?", (digest,)).fetchone()
                if row is not None:
                    found[digest] = bytes(row[0])
            return found
        return fetch

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        try:
            with con:  # 成功時 commit，例外時 rollback
                yield con
        finally:
            con.close()

    def save(self, session: dict) -> None:
        report = session.get("report") or {}
        row = (
            session["id"], session.get("examId"), session.get("examTitle", ""), session.get("candidate", ""),
            session.get("mode", "exam"), session["status"], session["startedAt"], session["updatedAt"],
            session.get("finishedAt"), report.get("percent"),
            None if not report else int(bool(report.get("passed"))),
        )
        with self._connect() as con:
            row = row + (self._store_images(con, session["id"], session),)
            con.execute(
                "INSERT INTO sessions(id, exam_id, exam_title, candidate, mode, status, started_at, updated_at,"
                " finished_at, percent, passed, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET exam_title=excluded.exam_title, candidate=excluded.candidate,"
                " mode=excluded.mode, status=excluded.status, updated_at=excluded.updated_at,"
                " finished_at=excluded.finished_at, percent=excluded.percent, passed=excluded.passed,"
                " data=excluded.data", row)

    def load(self, session_id: str) -> dict:
        with self._connect() as con:
            row = con.execute("SELECT data FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise KeyError(session_id)
            return internalize(json.loads(row[0]), self._fetcher(con))

    def list(self, exam_id: str | None = None) -> list[dict]:
        sql = ("SELECT id, exam_id, exam_title, candidate, mode, status, started_at, updated_at, finished_at,"
               " percent, passed FROM sessions")
        args: tuple = ()
        if exam_id:
            sql += " WHERE exam_id = ?"
            args = (exam_id,)
        sql += " ORDER BY updated_at DESC"
        keys = ("id", "examId", "examTitle", "candidate", "mode", "status", "startedAt", "updatedAt",
                "finishedAt", "percent", "passed")
        with self._connect() as con:
            return [dict(zip(keys, r)) for r in con.execute(sql, args)]

    def delete(self, session_id: str) -> None:
        with self._connect() as con:
            con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            con.execute("DELETE FROM session_images WHERE session_id = ?", (session_id,))
            con.execute("DELETE FROM images WHERE hash NOT IN (SELECT hash FROM session_images)")
