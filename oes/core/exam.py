"""題庫（考試）模型、題庫層級驗證與 JSON 匯入匯出。

題庫是一個 dict：
{
  "format": "open-exam-simulator/exam", "schemaVersion": "1.0",
  "id", "title", "number", "version", "passingScore"(0–100 %), "timeLimitMinutes"(0=不限時),
  "description", "showDescription",
  "sections": [{"id", "name"}],
  "questions": [{"sectionId": str|None, "question": {...題目...}}]
}
章節歸屬存在題庫層級，題目本身維持題型規格定義的欄位。
"""
from __future__ import annotations

from ..i18n import tr

import json
import uuid
from typing import Any

from . import question_types as qt

EXAM_FORMAT = "open-exam-simulator/exam"
EXAM_SCHEMA_VERSION = "1.0"
EXAM_KEYS = ("format", "schemaVersion", "id", "title", "number", "version", "passingScore",
             "timeLimitMinutes", "description", "showDescription", "sections", "caseStudies", "questions")


class ImportErrorWithDetails(ValueError):
    """匯入失敗，message 為可直接顯示給使用者的說明。"""


def new_exam_id() -> str:
    return "exam-" + uuid.uuid4().hex[:12]


def new_question_id(existing: list[str] | set[str]) -> str:
    used = set(existing)
    while True:
        candidate = "q-" + uuid.uuid4().hex[:10]
        if candidate not in used:
            return candidate


def default_title() -> str:
    return tr('未命名題庫')


def new_exam(title: str | None = None) -> dict:
    # 預設標題在呼叫時才翻譯（函式預設值會在程式載入時固定，無法跟著介面語言）
    title = default_title() if title is None else title
    return {
        "format": EXAM_FORMAT,
        "schemaVersion": EXAM_SCHEMA_VERSION,
        "id": new_exam_id(),
        "title": title,
        "number": "",
        "version": "1.0",
        "passingScore": 70,
        "timeLimitMinutes": 0,
        "description": "",
        "showDescription": False,
        "sections": [],
        "caseStudies": [],
        "questions": [],
    }


def question_ids(exam: dict) -> list[str]:
    return [e["question"].get("id") for e in exam.get("questions", [])]


def section_name(exam: dict, section_id: str | None) -> str:
    for section in exam.get("sections", []):
        if section["id"] == section_id:
            return section["name"]
    return ""


def add_question(exam: dict, type_id: str, section_id: str | None = None, index: int | None = None) -> dict:
    question = qt.new_question(type_id, new_question_id(question_ids(exam)))
    entry = {"sectionId": section_id, "question": question}
    if index is None:
        exam["questions"].append(entry)
    else:
        exam["questions"].insert(index, entry)
    return question


def add_section(exam: dict, name: str) -> dict:
    section = {"id": qt.next_id([s["id"] for s in exam["sections"]], "sec"), "name": name}
    exam["sections"].append(section)
    return section


def case_study(exam: dict, case_id: str | None) -> dict | None:
    for case in exam.get("caseStudies", []):
        if case["id"] == case_id:
            return case
    return None


def add_case_study(exam: dict, name: str) -> dict:
    cases = exam.setdefault("caseStudies", [])
    case = {"id": qt.next_id([c["id"] for c in cases], "case"), "name": name, "text": ""}
    cases.append(case)
    return case


def remove_case_study(exam: dict, case_id: str) -> None:
    exam["caseStudies"] = [c for c in exam.get("caseStudies", []) if c["id"] != case_id]
    for entry in exam["questions"]:
        if entry.get("caseStudyId") == case_id:
            entry.pop("caseStudyId", None)


def remove_section(exam: dict, section_id: str) -> None:
    exam["sections"] = [s for s in exam["sections"] if s["id"] != section_id]
    for entry in exam["questions"]:
        if entry.get("sectionId") == section_id:
            entry["sectionId"] = None


def validate_exam(exam: Any, strict_questions: bool = False) -> list[dict]:
    """題庫層級驗證。strict_questions=True 時也檢查每題的格式（不要求正解）。"""
    errors: list[dict] = []

    def add(path: str, message: str) -> None:
        errors.append({"path": path, "message": message})

    if not isinstance(exam, dict):
        return [{"path": "", "message": tr('題庫必須是物件。')}]
    for key in exam:
        if key not in EXAM_KEYS:
            add(key, tr('未定義的欄位。'))
    if exam.get("format") != EXAM_FORMAT:
        add("format", tr('不是 Open Exam Simulator 題庫格式。'))
    if exam.get("schemaVersion") != EXAM_SCHEMA_VERSION:
        add("schemaVersion", tr('只支援題庫 schemaVersion 1.0。'))
    if not qt.is_id(exam.get("id")):
        add("id", tr('題庫 ID 無效。'))
    if not qt.has_text(exam.get("title")):
        add("title", tr('請填寫題庫標題。'))
    for key in ("number", "version", "description"):
        if not isinstance(exam.get(key), str):
            add(key, tr('須為字串。'))
    if not qt.is_number(exam.get("passingScore")) or not 0 <= exam["passingScore"] <= 100:
        add("passingScore", tr('及格分數須為 0–100 的百分比。'))
    limit = exam.get("timeLimitMinutes")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= 10_000:
        add("timeLimitMinutes", tr('時間限制須為 0–10000 的整數分鐘（0 表示不限時）。'))
    if not isinstance(exam.get("showDescription"), bool):
        add("showDescription", tr('須為 true 或 false。'))
    section_ids: set[str] = set()
    sections = exam.get("sections")
    if not isinstance(sections, list):
        add("sections", tr('章節須為清單。'))
        sections = []
    for i, section in enumerate(sections):
        if not isinstance(section, dict) or not qt.is_id(section.get("id")) or section.get("id") in section_ids:
            add(f"sections[{i}].id", tr('章節 ID 無效或重複。'))
            continue
        if set(section) - {"id", "name"}:
            add(f"sections[{i}]", tr('章節含未定義的欄位。'))
        if not qt.has_text(section.get("name")):
            add(f"sections[{i}].name", tr('章節名稱不可空白。'))
        section_ids.add(section["id"])
    case_ids: set[str] = set()
    cases = exam.get("caseStudies", [])
    if not isinstance(cases, list):
        add("caseStudies", tr('案例研究須為清單。'))
        cases = []
    for i, case in enumerate(cases):
        path = f"caseStudies[{i}]"
        if not isinstance(case, dict) or not qt.is_id(case.get("id")) or case.get("id") in case_ids:
            add(path + ".id", tr('案例研究 ID 無效或重複。'))
            continue
        case_ids.add(case["id"])
        if set(case) - {"id", "name", "text", "images"}:
            add(path, tr('案例研究含未定義的欄位。'))
        if not qt.has_text(case.get("name")):
            add(path + ".name", tr('案例研究名稱不可空白。'))
        if not isinstance(case.get("text"), str):
            add(path + ".text", tr('案例研究內容須為字串。'))
        image_ids = qt.validate_image_list(case.get("images", []), path + ".images", add)
        for ref in qt.image_refs(case.get("text")):
            if ref not in image_ids:
                add(path + ".text", tr('引用了不存在的圖片：{0}', ref))
    questions = exam.get("questions")
    if not isinstance(questions, list):
        add("questions", tr('題目須為清單。'))
        return errors
    seen: set[str] = set()
    for i, entry in enumerate(questions):
        path = f"questions[{i}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("question"), dict):
            add(path, tr('題目項目須包含 question 物件。'))
            continue
        if set(entry) - {"sectionId", "caseStudyId", "question"}:
            add(path, tr('題目項目含未定義的欄位。'))
        if "caseStudyId" in entry and entry["caseStudyId"] not in case_ids:
            add(path + ".caseStudyId", tr('指向不存在的案例研究。'))
        sid = entry.get("sectionId")
        if sid is not None and sid not in section_ids:
            add(path + ".sectionId", tr('指向不存在的章節。'))
        qid = entry["question"].get("id")
        if qid in seen:
            add(path + ".question.id", tr('題目 ID 重複。'))
        seen.add(qid)
        if strict_questions:
            for err in qt.validate(entry["question"]):
                add(f"{path}.question.{err['path']}".rstrip("."), err["message"])
    return errors


# ---------------------------------------------------------------- JSON
def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def export_exam_json(exam: dict) -> str:
    return to_json(exam)


def export_question_json(question: dict) -> str:
    return to_json(question)


def parse_import(text: str) -> tuple[str, Any]:
    """解析匯入的 JSON。

    回傳 ("exam", exam) 或 ("questions", [question, ...])。
    接受：完整題庫、單一題目、題目陣列、或以名稱為鍵的題目物件（如 tests/fixtures/fixtures.json）。
    任何題目格式錯誤都會拋出 ImportErrorWithDetails，訊息列出路徑與原因。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportErrorWithDetails(tr('不是有效的 JSON：第 {0} 行第 {1} 欄，{2}', exc.lineno, exc.colno, exc.msg)) from None

    if isinstance(data, dict) and data.get("format") == EXAM_FORMAT:
        errors = validate_exam(data, strict_questions=True)
        if errors:
            raise ImportErrorWithDetails(tr('題庫格式錯誤：\n') + qt.format_errors(errors[:30]))
        return "exam", data

    if isinstance(data, dict) and "type" in data and "schemaVersion" in data:
        candidates = [("", data)]
    elif isinstance(data, list):
        candidates = [(f"[{i}]", q) for i, q in enumerate(data)]
    elif isinstance(data, dict) and data and all(isinstance(v, dict) and "type" in v for v in data.values()):
        candidates = [(f"{k}", q) for k, q in data.items()]
    else:
        raise ImportErrorWithDetails(tr('無法辨識的 JSON：需要題庫、單一題目或題目清單。'))

    problems: list[str] = []
    for label, question in candidates:
        for err in qt.validate(question):
            problems.append(tr('{0}{1}：{2}', label + ' ' if label else '', err['path'] or tr('(題目)'), err['message']))
    if problems:
        raise ImportErrorWithDetails(tr('題目格式錯誤：\n') + "\n".join(problems[:30]))
    return "questions", [q for _, q in candidates]


def merge_questions(exam: dict, questions: list[dict], section_id: str | None = None) -> list[tuple[str, str]]:
    """把匯入的題目加入題庫。ID 衝突時改用新 ID，回傳 [(舊 ID, 新 ID)]。"""
    renamed: list[tuple[str, str]] = []
    for question in questions:
        question = qt.clone(question)
        if question["id"] in question_ids(exam):
            new_id = new_question_id(question_ids(exam))
            renamed.append((question["id"], new_id))
            question["id"] = new_id
        exam["questions"].append({"sectionId": section_id, "question": question})
    return renamed
