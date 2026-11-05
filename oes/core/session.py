"""作答工作階段：出題、保存作答、結算與成績明細。

工作階段保存出題當下的題目快照（評分用）與考生展示資料（畫面用），
因此題庫之後被修改，也能還原作答並以原題目版本重算出相同結果。
"""
from __future__ import annotations

from ..i18n import tr

import random
import uuid
from datetime import datetime, timezone
from typing import Any

from . import question_types as qt
from .exam import case_study, section_name

SESSION_SCHEMA_VERSION = "1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def eligible_entries(exam: dict, section_ids: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """回傳（可出題的題目，排除的題目及原因）。只有狀態為「可使用」且正解完整的題目可出題。"""
    usable: list[dict] = []
    excluded: list[dict] = []
    for entry in exam.get("questions", []):
        question = entry["question"]
        if section_ids is not None and entry.get("sectionId") not in section_ids:
            continue
        errors = qt.validate(question, require_answer_key=True)
        if not errors and question.get("status") != "ready":
            errors = [{"path": "status", "message": tr('題目仍是草稿，改為「可使用」後才會出題。')}]
        if errors:
            excluded.append({"questionId": question.get("id"), "title": question.get("title", ""),
                             "reason": qt.format_errors(errors[:3])})
        else:
            usable.append(entry)
    return usable, excluded


def series_blocks(entries: list[dict]) -> list[list[dict]]:
    """把題目分組：相鄰、情境（題目內容）相同的解決方案評估題為一組，其他題目各自一組。"""
    blocks: list[list[dict]] = []
    for entry in entries:
        question = entry["question"]
        previous = blocks[-1][-1]["question"] if blocks else None
        if (previous is not None and question.get("type") == "goal_solution"
                and previous.get("type") == "goal_solution" and previous.get("prompt") == question.get("prompt")):
            blocks[-1].append(entry)
        else:
            blocks.append([entry])
    return blocks


def build_session(exam: dict, *, candidate: str = "", section_ids: list[str] | None = None,
                  limit: int | None = None, shuffle_questions: bool = False,
                  time_limit_minutes: int | None = None, mode: str = "exam",
                  rng: random.Random | None = None) -> dict:
    """建立新的作答工作階段。mode 為 exam（正式）或 practice（練習，可隨時看答案）。"""
    rng = rng or random.Random()
    usable, excluded = eligible_entries(exam, section_ids)
    entries = list(usable)
    if shuffle_questions:
        blocks = series_blocks(entries)
        rng.shuffle(blocks)  # 同一情境的系列題維持相鄰與原順序
        entries = [entry for block in blocks for entry in block]
    if limit is not None and limit > 0:
        entries = entries[:limit]
    if not entries:
        raise ValueError(tr('沒有可作答的題目。題目須設定完整正解，並把狀態改為「可使用」。'))
    questions = []
    for entry in entries:
        question = qt.clone(entry["question"])
        presented = qt.for_candidate(question)
        if question["type"] == "multiple_choice" and question.get("shuffle"):
            rng.shuffle(presented["options"])
        case = case_study(exam, entry.get("caseStudyId"))
        questions.append({
            "sectionId": entry.get("sectionId"),
            "sectionName": section_name(exam, entry.get("sectionId")),
            "caseStudy": qt.clone(case) if case else None,
            "question": question,
            "presented": presented,
        })
    limit_minutes = exam.get("timeLimitMinutes", 0) if time_limit_minutes is None else time_limit_minutes
    return {
        "schemaVersion": SESSION_SCHEMA_VERSION,
        "id": "sess-" + uuid.uuid4().hex[:12],
        "mode": mode,
        "examId": exam.get("id"),
        "examTitle": exam.get("title", ""),
        "examNumber": exam.get("number", ""),
        "candidate": candidate,
        "passingScore": exam.get("passingScore", 0),
        "timeLimitMinutes": max(0, int(limit_minutes or 0)),
        "startedAt": now_iso(),
        "updatedAt": now_iso(),
        "finishedAt": None,
        "status": "in_progress",
        "elapsedSeconds": 0,
        "currentIndex": 0,
        "excludedCount": len(excluded),
        "questions": questions,
        "answers": {q["question"]["id"]: {} for q in questions},
        "marked": [],
        "locked": [],
        "report": None,
    }


def find_question(session: dict, question_id: str) -> dict:
    for entry in session["questions"]:
        if entry["question"]["id"] == question_id:
            return entry
    raise KeyError(question_id)


def set_answer(session: dict, question_id: str, answers: dict) -> None:
    """保存單題作答。作答一律以項目 ID／選項 ID 記錄，並清掉不屬於此題的內容。"""
    if session["status"] != "in_progress":
        raise ValueError(tr('工作階段已結束，不能修改作答。'))
    if is_locked(session, question_id):
        raise ValueError(tr('此題已鎖定，不能修改作答。'))
    question = find_question(session, question_id)["question"]
    session["answers"][question_id] = qt.sanitize_answers(question, answers)
    session["updatedAt"] = now_iso()


def no_return(session: dict, question_id: str) -> bool:
    """正式考試中，此題是否「離開後無法返回」（練習模式不限制）。"""
    if session.get("mode") == "practice":
        return False
    return bool(find_question(session, question_id)["presented"].get("noReturn"))


def lock_question(session: dict, question_id: str) -> None:
    """離開「無法返回」的題目時鎖定，之後不能再前往或修改。"""
    if no_return(session, question_id) and question_id not in session.setdefault("locked", []):
        session["locked"].append(question_id)
        session["marked"] = [m for m in session["marked"] if m != question_id]


def is_locked(session: dict, question_id: str) -> bool:
    return question_id in session.get("locked", [])


def toggle_mark(session: dict, question_id: str, marked: bool) -> None:
    marks = [m for m in session["marked"] if m != question_id]
    if marked:
        marks.append(question_id)
    session["marked"] = marks


def question_progress(session: dict, question_id: str) -> str:
    """回傳 answered／partial／unanswered。"""
    question = find_question(session, question_id)["question"]
    result = qt.grade(question, session["answers"].get(question_id, {}))
    if result["status"] == "graded":
        return "answered"
    if result["status"] == "incomplete":
        return "partial" if len(result["unansweredIds"]) < result["totalParts"] else "unanswered"
    return "unanswered"


def unanswered_count(session: dict) -> int:
    return sum(1 for q in session["questions"] if question_progress(session, q["question"]["id"]) != "answered")


def finish(session: dict) -> dict:
    """結算。未作答的分項計 0 分（畫面需先向考生顯示未作答數並確認）。"""
    rows = []
    sections: dict[str, dict[str, Any]] = {}
    total = 0.0
    maximum = 0.0
    for entry in session["questions"]:
        question = entry["question"]
        result = qt.grade(question, session["answers"].get(question["id"], {}), allow_incomplete=True)
        score = result.get("score") or 0.0
        max_score = question["scoring"]["maxScore"]
        total += score
        maximum += max_score
        rows.append({
            "questionId": question["id"],
            "title": question["title"],
            "type": question["type"],
            "sectionName": entry.get("sectionName", ""),
            "status": result["status"],
            "score": result.get("score"),
            "maxScore": max_score,
            "correctCount": result.get("correctCount", 0),
            "totalParts": result.get("totalParts", 0),
            "unansweredIds": result.get("unansweredIds", []),
            "items": result.get("items", []),
            "marked": question["id"] in session["marked"],
        })
        if entry.get("sectionName"):
            bucket = sections.setdefault(entry["sectionName"], {"name": entry["sectionName"], "score": 0.0, "maxScore": 0.0})
            bucket["score"] += score
            bucket["maxScore"] += max_score
    for bucket in sections.values():
        bucket["score"] = qt._round6(bucket["score"])
        bucket["percent"] = round(bucket["score"] / bucket["maxScore"] * 100, 2) if bucket["maxScore"] else 0.0
    percent = round(total / maximum * 100, 2) if maximum else 0.0
    report = {
        "score": qt._round6(total),
        "maxScore": qt._round6(maximum),
        "percent": percent,
        "passingScore": session["passingScore"],
        "passed": percent >= session["passingScore"],
        "correctQuestions": sum(1 for r in rows if r["score"] is not None and r["score"] >= r["maxScore"]),
        "totalQuestions": len(rows),
        "sections": list(sections.values()),
        "questions": rows,
    }
    session["status"] = "finished"
    session["finishedAt"] = now_iso()
    session["updatedAt"] = session["finishedAt"]
    session["report"] = report
    return report


def retake(session: dict, which: str = "incorrect") -> dict:
    """以上次的題目快照重考：incorrect（答錯或未完成）、marked（標記）或 all。"""
    if session.get("report") is None:
        raise ValueError(tr('工作階段尚未結算。'))
    rows = {r["questionId"]: r for r in session["report"]["questions"]}
    picked = []
    for entry in session["questions"]:
        row = rows[entry["question"]["id"]]
        if which == "all" or (which == "marked" and row["marked"]) or \
                (which == "incorrect" and (row["score"] is None or row["score"] < row["maxScore"])):
            picked.append(qt.clone(entry))
    if not picked:
        raise ValueError(tr('沒有符合條件的題目。'))
    fresh = qt.clone(session)
    fresh.update({
        "id": "sess-" + uuid.uuid4().hex[:12],
        "startedAt": now_iso(), "updatedAt": now_iso(), "finishedAt": None,
        "status": "in_progress", "elapsedSeconds": 0, "currentIndex": 0,
        "questions": picked, "answers": {e["question"]["id"]: {} for e in picked},
        "marked": [], "locked": [], "report": None,
    })
    return fresh
