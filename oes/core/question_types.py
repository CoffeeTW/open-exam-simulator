"""題型註冊、驗證、作答正規化、評分與考生展示 DTO。

本模組只使用 Python 標準函式庫，可在沒有 PySide6 的環境獨立測試。
各題型的資料格式與評分規則見 docs/file-format.md。

所有題目都是可直接序列化成 JSON 的 dict。錯誤以 {"path": ..., "message": ...} 回報。
"""
from __future__ import annotations

from ..i18n import tr

import base64
import binascii
import copy
import math
import re
import unicodedata
from typing import Any, Callable

SCHEMA_VERSION = "1.0"
MODES = ("all_or_nothing", "per_part")
MODE_LABELS = {"all_or_nothing": "全對才得分", "per_part": "分項計分"}
STATUSES = ("draft", "ready")
STATUS_LABELS = {"draft": "草稿", "ready": "可使用"}
MAX_SCORE_LIMIT = 1_000_000
COMMON_KEYS = ("schemaVersion", "id", "type", "status", "title", "prompt", "scoring", "explanation", "images")

# 題目內容（prompt）中的圖片以 {{image:圖片ID}} 標記位置，圖片資料放在選填的 images 清單：
# [{"id": "img1", "mime": "image/png", "data": "<base64>", "width": 400}]
# width 為選填的顯示寬度（像素）；未設定時依原尺寸顯示（仍會依可用寬度縮小）。
IMAGE_TOKEN_RE = re.compile(r"\{\{image:([A-Za-z0-9][A-Za-z0-9_-]{0,63})\}\}")
IMAGE_MIMES = ("image/png", "image/jpeg", "image/gif", "image/webp")
MAX_IMAGE_BYTES = 8_000_000
MIN_IMAGE_WIDTH = 16
MAX_IMAGE_WIDTH = 1600
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")

Error = dict[str, str]
AddError = Callable[[str, str], None]


# ---------------------------------------------------------------- 共用判斷
def is_id(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def has_text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def is_obj(value: Any) -> bool:
    return isinstance(value, dict)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_blank_answer(value: Any) -> bool:
    return value is None or value == ""


def _round6(value: float) -> float:
    # 與 JavaScript Math.round 相同的四捨五入（Python round 為銀行家捨入）。
    return math.floor(value * 1_000_000 + 0.5) / 1_000_000


def next_id(existing: list[str] | set[str], prefix: str) -> str:
    """產生不與現有 ID 重複的新 ID；只在新增時呼叫，不因重排或改文字而改變。"""
    used = set(existing)
    n = 1
    while f"{prefix}{n}" in used:
        n += 1
    return f"{prefix}{n}"


def _extras(obj: dict, allowed: tuple[str, ...], path: str, add: AddError) -> None:
    for key in obj:
        if key not in allowed:
            add((path + "." if path else "") + str(key), tr('未定義的欄位。'))


def _validate_options(options: Any, path: str, add: AddError, minimum: int = 2) -> set[str]:
    ids: set[str] = set()
    if not isinstance(options, list) or len(options) < minimum:
        add(path, tr('至少需要 {0} 個選項。', minimum))
    for index, option in enumerate(options if isinstance(options, list) else []):
        opath = f"{path}[{index}]"
        if not is_obj(option):
            add(opath, tr('選項須為物件。'))
            continue
        _extras(option, ("id", "text"), opath, add)
        if not is_id(option.get("id")) or option.get("id") in ids:
            add(opath + ".id", tr('選項 ID 無效或重複。'))
        if isinstance(option.get("id"), str):
            ids.add(option["id"])
        if not has_text(option.get("text")):
            add(opath + ".text", tr('選項文字不可空白。'))
    return ids


# ---------------------------------------------------------------- 題型基底
class QuestionType:
    type_id = ""
    label = ""
    short_label = ""
    description = ""
    extra_keys: tuple[str, ...] = ()

    # 作者端
    def new_question(self, question_id: str) -> dict:
        raise NotImplementedError

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        raise NotImplementedError

    def image_texts(self, q: dict) -> list[tuple[str, Any]]:
        """題目內容以外、可以含圖片標記的文字欄位：[(路徑, 文字)]。"""
        return []

    def image_ids(self, q: dict) -> list[tuple[str, str]]:
        """直接引用圖片 ID 的欄位（例如熱區題背景）：[(路徑, 圖片ID)]。"""
        return []

    # 作答端
    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        raise NotImplementedError

    def sanitize(self, q: dict, answers: Any) -> dict:
        raise NotImplementedError

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        raise NotImplementedError

    def candidate_body(self, q: dict) -> dict:
        raise NotImplementedError

    def _base(self, question_id: str, title: str, prompt: str) -> dict:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "id": question_id,
            "type": self.type_id,
            "status": "draft",
            "title": title,
            "prompt": prompt,
            "scoring": {"mode": "all_or_nothing", "maxScore": 1},
            "explanation": "",
        }


# ---------------------------------------------------------------- 單選／複選
class MultipleChoice(QuestionType):
    type_id = "multiple_choice"
    label = "選擇題（單選／複選）"
    short_label = "選擇"
    description = "從選項中選出一個或多個答案。可設定選項隨機排序與限制選取數量。"
    extra_keys = ("selectMode", "shuffle", "checkNumberSelected", "options", "correctAnswer")
    PART_ID = "answer"

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新選擇題'), "")
        q.update({
            "selectMode": "single",
            "shuffle": False,
            "checkNumberSelected": False,
            "options": [{"id": f"o{i}", "text": tr('選項 {0}', chr(64 + i))} for i in range(1, 5)],
            "correctAnswer": None,
        })
        return q

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        if q.get("selectMode") not in ("single", "multiple"):
            add("selectMode", tr('作答方式須為 single 或 multiple。'))
        for key in ("shuffle", "checkNumberSelected"):
            if not isinstance(q.get(key), bool):
                add(key, tr('須為 true 或 false。'))
        ids = _validate_options(q.get("options"), "options", add)
        if "correctAnswer" not in q:
            add("correctAnswer", tr('正解須明確設定，或設為 null。'))
            return
        key = q.get("correctAnswer")
        if key is None:
            if require_key:
                add("correctAnswer", tr('尚未設定正確答案。'))
            return
        if (not isinstance(key, list) or not key or len(set(map(str, key))) != len(key)
                or any(not isinstance(k, str) or k not in ids for k in key)):
            add("correctAnswer", tr('正解須為此題現有選項 ID 的不重複清單，或明確設為 null。'))
        elif q.get("selectMode") == "single" and len(key) != 1:
            add("correctAnswer", tr('單選題只能有一個正確答案。'))

    def image_texts(self, q: dict) -> list[tuple[str, Any]]:
        options = q.get("options") if isinstance(q.get("options"), list) else []
        return [(f"options[{i}].text", o.get("text")) for i, o in enumerate(options) if is_obj(o)]

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        bad = [f"answers.{k}" for k in answers if k != "selected"]
        selected = answers.get("selected")
        if selected is None:
            return bad
        option_ids = {o["id"] for o in q["options"]}
        if (not isinstance(selected, list) or any(not isinstance(s, str) or s not in option_ids for s in selected)
                or len(set(selected)) != len(selected)):
            return bad + ["answers.selected"]
        if q["selectMode"] == "single" and len(selected) > 1:
            bad.append("answers.selected")
        elif q["checkNumberSelected"] and len(selected) > len(q["correctAnswer"] or []):
            bad.append("answers.selected")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if not is_obj(answers) or not isinstance(answers.get("selected"), list):
            return {}
        chosen = {s for s in answers["selected"] if isinstance(s, str)}
        ordered = [o["id"] for o in q.get("options", []) if o.get("id") in chosen]
        if q.get("selectMode") == "single":
            ordered = ordered[:1]
        return {"selected": ordered} if ordered else {}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        selection = selections.get("selected")
        correct = [o["id"] for o in q["options"] if o["id"] in set(q["correctAnswer"])]
        return [{
            "id": self.PART_ID,
            "selection": selection,
            "correctAnswer": correct,
            "isCorrect": selection is not None and set(selection) == set(correct),
        }]

    def candidate_body(self, q: dict) -> dict:
        body: dict[str, Any] = {
            "selectMode": q["selectMode"],
            "options": [{"id": o["id"], "text": o["text"]} for o in q["options"]],
        }
        if q["selectMode"] == "multiple" and q["checkNumberSelected"] and q.get("correctAnswer"):
            body["selectCount"] = len(q["correctAnswer"])
        return body


# ---------------------------------------------------------------- 填空
class FillInBlank(QuestionType):
    type_id = "fill_in_blank"
    label = "填空題"
    short_label = "填空"
    description = "考生輸入文字；符合任一個可接受答案即正確。可設定大小寫與空白比對規則。"
    extra_keys = ("acceptedAnswers", "caseSensitive", "ignoreMultipleSpaces", "trimResponse")
    PART_ID = "answer"

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新填空題'), "")
        q.update({"acceptedAnswers": [], "caseSensitive": False, "ignoreMultipleSpaces": True, "trimResponse": True})
        return q

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        for key in ("caseSensitive", "ignoreMultipleSpaces", "trimResponse"):
            if not isinstance(q.get(key), bool):
                add(key, tr('須為 true 或 false。'))
        answers = q.get("acceptedAnswers")
        if not isinstance(answers, list):
            add("acceptedAnswers", tr('可接受答案須為文字清單。'))
            return
        for index, text in enumerate(answers):
            if not has_text(text):
                add(f"acceptedAnswers[{index}]", tr('可接受答案不可空白。'))
        if require_key and not answers:
            add("acceptedAnswers", tr('尚未設定可接受答案。'))

    def normalize(self, q: dict, text: str) -> str:
        text = unicodedata.normalize("NFC", text)
        if q.get("trimResponse", True):
            text = text.strip()
        if q.get("ignoreMultipleSpaces", True):
            text = re.sub(r"\s+", " ", text)
        if not q.get("caseSensitive", False):
            text = text.casefold()
        return text

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        bad = [f"answers.{k}" for k in answers if k != "text"]
        text = answers.get("text")
        if text is not None and not isinstance(text, str):
            bad.append("answers.text")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if is_obj(answers) and isinstance(answers.get("text"), str) and answers["text"].strip():
            return {"text": answers["text"]}
        return {}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        text = selections.get("text")
        accepted = {self.normalize(q, a) for a in q["acceptedAnswers"]}
        return [{
            "id": self.PART_ID,
            "selection": text,
            "correctAnswer": list(q["acceptedAnswers"]),
            "isCorrect": text is not None and self.normalize(q, text) in accepted,
        }]

    def candidate_body(self, q: dict) -> dict:
        return {}


# ---------------------------------------------------------------- 多欄位下拉
class DropdownMulti(QuestionType):
    type_id = "dropdown_multi"
    label = "多欄位下拉選單題"
    short_label = "下拉"
    description = "多個作答欄位，每欄有自己的下拉選項與單一正解。"
    extra_keys = ("items", "codeFont")
    # 選填：codeFont 以等寬字顯示（指令、程式碼題）；欄位的 label 顯示在選單前、suffix 顯示在選單後。
    # label、suffix 可多行：label 除最後一行外、suffix 除第一行外，各自成為獨立一行（放沒有選單的程式碼）。

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新下拉選單題'), "")
        q["items"] = [
            {"id": f"item{n}", "label": tr('欄位 {0}', n),
             "options": [{"id": f"o{i}", "text": tr('選項 {0}', i)} for i in range(1, 4)],
             "correctAnswer": None, "explanation": ""}
            for n in (1, 2)
        ]
        return q

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        if "codeFont" in q and not isinstance(q["codeFont"], bool):
            add("codeFont", tr('須為 true 或 false。'))
        for index, item in enumerate(q["items"]):
            path = f"items[{index}]"
            if not is_obj(item):
                continue
            _extras(item, ("id", "label", "suffix", "options", "correctAnswer", "explanation"), path, add)
            if "suffix" in item and not isinstance(item["suffix"], str):
                add(path + ".suffix", tr('欄位後文字須為字串。'))
            if not isinstance(item.get("label"), str):  # 標籤可留白（題目內容已說明各欄位時）
                add(path + ".label", tr('欄位標籤須為字串。'))
            choices = _validate_options(item.get("options"), path + ".options", add)
            key = item.get("correctAnswer", ...)
            if key is ...:
                continue
            if key is not None and (not isinstance(key, str) or key not in choices):
                add(path + ".correctAnswer", tr('正解須指向此欄位現有選項，或明確設為 null。'))
            if require_key and key is None:
                add(path + ".correctAnswer", tr('尚未設定正確答案。'))

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        ids = {i["id"] for i in q["items"]}
        bad = [f"answers.{k}" for k in answers if k not in ids]
        for item in q["items"]:
            value = answers.get(item["id"])
            if _is_blank_answer(value):
                continue
            if not any(o["id"] == value for o in item["options"]):
                bad.append(f"answers.{item['id']}")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        result: dict[str, Any] = {}
        if not is_obj(answers):
            return result
        for item in q.get("items") or []:
            value = answers.get(item.get("id"), None)
            if isinstance(value, str) and any(o.get("id") == value for o in item.get("options") or []):
                result[item["id"]] = value
        return result

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        return [{
            "id": item["id"],
            "selection": selections.get(item["id"]),
            "correctAnswer": item["correctAnswer"],
            "isCorrect": item["id"] in selections and selections[item["id"]] == item["correctAnswer"],
        } for item in q["items"]]

    def candidate_body(self, q: dict) -> dict:
        return {"codeFont": q.get("codeFont", False),
                "items": [{"id": i["id"], "label": i["label"], "suffix": i.get("suffix", ""),
                           "options": [{"id": o["id"], "text": o["text"]} for o in i["options"]]}
                          for i in q["items"]]}


# ---------------------------------------------------------------- Yes／No 判斷矩陣
class YesNoMatrix(QuestionType):
    type_id = "yes_no_matrix"
    label = "逐列 Yes／No 判斷題"
    short_label = "Yes/No"
    description = "多列敘述，每列獨立選 Yes 或 No；未作答不等於 No。"
    extra_keys = ("items",)

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新 Yes／No 判斷題'), "")
        q["items"] = [{"id": f"s{n}", "text": tr('敘述 {0}', n), "correctAnswer": None, "explanation": ""}
                      for n in (1, 2, 3)]
        return q

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        for index, item in enumerate(q["items"]):
            path = f"items[{index}]"
            if not is_obj(item):
                continue
            _extras(item, ("id", "text", "correctAnswer", "explanation"), path, add)
            if not has_text(item.get("text")):
                add(path + ".text", tr('敘述不可空白。'))
            key = item.get("correctAnswer", ...)
            if key is ...:
                continue
            if key is not None and not isinstance(key, bool):
                add(path + ".correctAnswer", tr('正解須為 true、false 或 null。'))
            if require_key and key is None:
                add(path + ".correctAnswer", tr('尚未設定 Yes／No 正解。'))

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        ids = {i["id"] for i in q["items"]}
        bad = [f"answers.{k}" for k in answers if k not in ids]
        for item in q["items"]:
            value = answers.get(item["id"])
            if not _is_blank_answer(value) and not isinstance(value, bool):
                bad.append(f"answers.{item['id']}")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if not is_obj(answers):
            return {}
        return {item["id"]: answers[item["id"]] for item in q.get("items") or []
                if is_obj(item) and isinstance(answers.get(item.get("id")), bool)}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        return [{
            "id": item["id"],
            "selection": selections.get(item["id"]),
            "correctAnswer": item["correctAnswer"],
            "isCorrect": item["id"] in selections and selections[item["id"]] is item["correctAnswer"],
        } for item in q["items"]]

    def candidate_body(self, q: dict) -> dict:
        return {"items": [{"id": i["id"], "text": i["text"]} for i in q["items"]]}


# ---------------------------------------------------------------- 解決方案評估題（Does this meet the goal?）
class GoalSolution(QuestionType):
    """同一情境的系列題：每題提出一個解決方案，考生判斷是否達成目標（Yes／No）。

    prompt 為情境與目標（系列題共用，可用「複製題目」建立下一題）；solution 為本題的解決方案。
    noReturn 預設為 false（正式考試也可返回）；設為 true 時，正式考試中離開此題後就不能再返回。
    """
    type_id = "goal_solution"
    label = "解決方案評估題（是否達成目標）"
    short_label = "評估"
    description = "系列題：同一情境提出不同解決方案，判斷是否達成目標（Yes／No）。可設定作答後無法返回。"
    extra_keys = ("solution", "noReturn", "correctAnswer")
    PART_ID = "answer"

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新解決方案評估題'), "")
        q.update({"solution": "", "noReturn": False, "correctAnswer": None})  # 預設可返回上一題
        return q

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        if not isinstance(q.get("solution"), str):
            add("solution", tr('解決方案須為字串。'))
        elif require_key and not has_text(strip_format(strip_images(q["solution"], ""))) \
                and not image_refs(q["solution"]):
            add("solution", tr('請填寫解決方案。'))
        if not isinstance(q.get("noReturn"), bool):
            add("noReturn", tr('須為 true 或 false。'))
        if "correctAnswer" not in q:
            add("correctAnswer", tr('正解須明確設定，或設為 null。'))
            return
        key = q.get("correctAnswer")
        if key is not None and not isinstance(key, bool):
            add("correctAnswer", tr('正解須為 true、false 或 null。'))
        elif require_key and key is None:
            add("correctAnswer", tr('尚未設定 Yes／No 正解。'))

    def image_texts(self, q: dict) -> list[tuple[str, Any]]:
        return [("solution", q.get("solution"))]

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        bad = [f"answers.{k}" for k in answers if k != self.PART_ID]
        value = answers.get(self.PART_ID)
        if not _is_blank_answer(value) and not isinstance(value, bool):
            bad.append(f"answers.{self.PART_ID}")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if is_obj(answers) and isinstance(answers.get(self.PART_ID), bool):
            return {self.PART_ID: answers[self.PART_ID]}
        return {}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        selection = selections.get(self.PART_ID)
        return [{"id": self.PART_ID, "selection": selection, "correctAnswer": q["correctAnswer"],
                 "isCorrect": selection is not None and selection is q["correctAnswer"]}]

    def candidate_body(self, q: dict) -> dict:
        return {"solution": q["solution"], "noReturn": q["noReturn"]}


# ---------------------------------------------------------------- 排序題（Build List and Reorder）
class BuildList(QuestionType):
    type_id = "build_list"
    label = "排序題（建立清單並排序）"
    short_label = "排序"
    description = "從選項中挑出需要的項目並排出正確順序；也可設定為「只需重新排序」。"
    extra_keys = ("choices", "reorderOnly", "orderMatters", "choicesTitle", "answerTitle", "correctAnswer")
    PART_ID = "answer"

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新排序題'), "")
        q.update({
            "choicesTitle": tr('選項'),
            "answerTitle": tr('答案區'),
            "reorderOnly": False,
            "orderMatters": True,
            "choices": [{"id": f"c{i}", "text": tr('步驟 {0}', i)} for i in range(1, 5)],
            "correctAnswer": None,
        })
        return q

    def image_texts(self, q: dict) -> list[tuple[str, Any]]:
        choices = q.get("choices") if isinstance(q.get("choices"), list) else []
        return [(f"choices[{i}].text", c.get("text")) for i, c in enumerate(choices) if is_obj(c)]

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        for key in ("reorderOnly", "orderMatters"):
            if not isinstance(q.get(key), bool):
                add(key, tr('須為 true 或 false。'))
        for key in ("choicesTitle", "answerTitle"):
            if not isinstance(q.get(key), str):
                add(key, tr('須為字串。'))
        ids = _validate_options(q.get("choices"), "choices", add)
        if "correctAnswer" not in q:
            add("correctAnswer", tr('正解須明確設定，或設為 null。'))
            return
        key = q["correctAnswer"]
        if key is None:
            if require_key:
                add("correctAnswer", tr('尚未設定正確答案。'))
            return
        if (not isinstance(key, list) or not key or any(not isinstance(k, str) or k not in ids for k in key)
                or len(set(key)) != len(key)):
            add("correctAnswer", tr('正解須為此題現有選項 ID 的不重複清單，或明確設為 null。'))
        elif q.get("reorderOnly") is True and set(key) != ids:
            add("correctAnswer", tr('「只需重新排序」時，正解必須包含全部選項。'))

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        bad = [f"answers.{k}" for k in answers if k != "sequence"]
        sequence = answers.get("sequence")
        if sequence is None:
            return bad
        ids = {c["id"] for c in q["choices"]}
        if (not isinstance(sequence, list) or any(not isinstance(s, str) or s not in ids for s in sequence)
                or len(set(sequence)) != len(sequence)):
            bad.append("answers.sequence")
        elif q["reorderOnly"] and sequence and set(sequence) != ids:
            bad.append("answers.sequence")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if not is_obj(answers) or not isinstance(answers.get("sequence"), list):
            return {}
        ids = {c.get("id") for c in q.get("choices", []) if is_obj(c)}
        seen: list[str] = []
        for s in answers["sequence"]:
            if isinstance(s, str) and s in ids and s not in seen:
                seen.append(s)
        return {"sequence": seen} if seen else {}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        sequence = selections.get("sequence")
        key = list(q["correctAnswer"])
        if sequence is None:
            correct = False
        elif q["orderMatters"]:
            correct = sequence == key
        else:
            correct = sorted(sequence) == sorted(key)
        return [{"id": self.PART_ID, "selection": sequence, "correctAnswer": key, "isCorrect": correct}]

    def candidate_body(self, q: dict) -> dict:
        return {"choices": [{"id": c["id"], "text": c["text"]} for c in q["choices"]],
                "reorderOnly": q["reorderOnly"], "choicesTitle": q["choicesTitle"], "answerTitle": q["answerTitle"]}


# ---------------------------------------------------------------- 拖放題（Select and Place）
class DragDrop(QuestionType):
    type_id = "drag_drop"
    label = "拖放題（選取並放置）"
    short_label = "拖放"
    description = "把左側的值拖到右側答案區的空格；每個空格有一個正解，可設定值能否重複使用。"
    extra_keys = ("sources", "targets", "reuseSources", "sourcesTitle", "codeFont")
    # 選填：sourcesTitle 左側標題（預設「值」）；codeFont 以等寬字顯示值與空格文字（指令、程式碼題）；
    # 空格的 label 顯示在空格前、suffix 顯示在空格後（例如 [空格] -Name 'Group1'）。

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新拖放題'), "")
        q.update({
            "reuseSources": False,
            "sources": [{"id": f"v{i}", "text": tr('值 {0}', i)} for i in range(1, 5)],
            "targets": [{"id": f"t{i}", "label": tr('空格 {0}', i), "correctAnswer": None, "explanation": ""}
                        for i in (1, 2)],
        })
        return q

    def image_texts(self, q: dict) -> list[tuple[str, Any]]:
        sources = q.get("sources") if isinstance(q.get("sources"), list) else []
        return [(f"sources[{i}].text", s.get("text")) for i, s in enumerate(sources) if is_obj(s)]

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        if not isinstance(q.get("reuseSources"), bool):
            add("reuseSources", tr('須為 true 或 false。'))
        if "sourcesTitle" in q and not isinstance(q["sourcesTitle"], str):
            add("sourcesTitle", tr('標題須為字串。'))
        if "codeFont" in q and not isinstance(q["codeFont"], bool):
            add("codeFont", tr('須為 true 或 false。'))
        source_ids = _validate_options(q.get("sources"), "sources", add, minimum=1)
        targets = q.get("targets")
        if not isinstance(targets, list) or not targets:
            add("targets", tr('至少需要一個空格。'))
            return
        ids: set[str] = set()
        used: dict[str, int] = {}
        for index, target in enumerate(targets):
            path = f"targets[{index}]"
            if not is_obj(target):
                add(path, tr('空格須為物件。'))
                continue
            _extras(target, ("id", "label", "suffix", "correctAnswer", "explanation"), path, add)
            if "suffix" in target and not isinstance(target["suffix"], str):
                add(path + ".suffix", tr('空格後文字須為字串。'))
            if not is_id(target.get("id")) or target.get("id") in ids:
                add(path + ".id", tr('空格 ID 無效或重複。'))
            if isinstance(target.get("id"), str):
                ids.add(target["id"])
            if not isinstance(target.get("label"), str):
                add(path + ".label", tr('空格說明須為字串。'))
            if "explanation" in target and not isinstance(target["explanation"], str):
                add(path + ".explanation", tr('逐項解析須為字串。'))
            if "correctAnswer" not in target:
                add(path + ".correctAnswer", tr('正解須明確設定，或設為 null。'))
                continue
            key = target["correctAnswer"]
            if key is None:
                if require_key:
                    add(path + ".correctAnswer", tr('尚未設定正確答案。'))
            elif not isinstance(key, str) or key not in source_ids:
                add(path + ".correctAnswer", tr('正解須指向現有的值，或明確設為 null。'))
            else:
                used[key] = used.get(key, 0) + 1
        if q.get("reuseSources") is False:
            for key, count in used.items():
                if count > 1:
                    add("targets", tr('值「{0}」被設為多個空格的正解；請勾選「值可以重複使用」。', key))

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        targets = {t["id"] for t in q["targets"]}
        sources = {s["id"] for s in q["sources"]}
        bad = [f"answers.{k}" for k in answers if k not in targets]
        chosen: list[str] = []
        for target in q["targets"]:
            value = answers.get(target["id"])
            if _is_blank_answer(value):
                continue
            if not isinstance(value, str) or value not in sources:
                bad.append(f"answers.{target['id']}")
            else:
                chosen.append(value)
        if not q["reuseSources"] and len(set(chosen)) != len(chosen):
            bad.append("answers")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if not is_obj(answers):
            return {}
        sources = {s.get("id") for s in q.get("sources", []) if is_obj(s)}
        result: dict[str, str] = {}
        for target in q.get("targets", []):
            value = answers.get(target.get("id")) if is_obj(target) else None
            if isinstance(value, str) and value in sources:
                if q.get("reuseSources") or value not in result.values():
                    result[target["id"]] = value
        return result

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        return [{"id": t["id"], "selection": selections.get(t["id"]), "correctAnswer": t["correctAnswer"],
                 "isCorrect": t["id"] in selections and selections[t["id"]] == t["correctAnswer"]}
                for t in q["targets"]]

    def candidate_body(self, q: dict) -> dict:
        return {"reuseSources": q["reuseSources"],
                "sourcesTitle": q.get("sourcesTitle", ""),
                "codeFont": q.get("codeFont", False),
                "sources": [{"id": s["id"], "text": s["text"]} for s in q["sources"]],
                "targets": [{"id": t["id"], "label": t["label"], "suffix": t.get("suffix", "")}
                            for t in q["targets"]]}


# ---------------------------------------------------------------- 熱區題（Hot Area）
class HotArea(QuestionType):
    type_id = "hot_area"
    label = "熱區題（在圖片上點選）"
    short_label = "熱區"
    description = "在背景圖片上框出可點選的區域，考生點選正確的一個或多個區域。"
    extra_keys = ("background", "areas", "correctAnswer")
    PART_ID = "answer"

    def new_question(self, question_id: str) -> dict:
        q = self._base(question_id, tr('新熱區題'), "")
        q.update({"background": None, "areas": [], "correctAnswer": None})
        return q

    def image_ids(self, q: dict) -> list[tuple[str, str]]:
        return [("background", q["background"])] if isinstance(q.get("background"), str) else []

    def validate_body(self, q: dict, add: AddError, require_key: bool) -> None:
        background = q.get("background", ...)
        if background is ... or (background is not None and not is_id(background)):
            add("background", tr('背景圖片須為圖片 ID，或明確設為 null。'))
        elif background is None and require_key:
            add("background", tr('尚未設定背景圖片。'))
        ids: set[str] = set()
        areas = q.get("areas")
        if not isinstance(areas, list):
            add("areas", tr('區域須為清單。'))
            areas = []
        for index, area in enumerate(areas):
            path = f"areas[{index}]"
            if not is_obj(area):
                add(path, tr('區域須為物件。'))
                continue
            _extras(area, ("id", "x", "y", "w", "h"), path, add)
            if not is_id(area.get("id")) or area.get("id") in ids:
                add(path + ".id", tr('區域 ID 無效或重複。'))
            if isinstance(area.get("id"), str):
                ids.add(area["id"])
            for key in ("x", "y", "w", "h"):
                value = area.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 100_000:
                    add(f"{path}.{key}", tr('座標與大小須為 0 以上的整數（像素）。'))
            if isinstance(area.get("w"), int) and isinstance(area.get("h"), int) and (area["w"] < 4 or area["h"] < 4):
                add(path, tr('區域太小（至少 4×4 像素）。'))
        if require_key and not areas:
            add("areas", tr('至少需要一個可點選的區域。'))
        if "correctAnswer" not in q:
            add("correctAnswer", tr('正解須明確設定，或設為 null。'))
            return
        key = q["correctAnswer"]
        if key is None:
            if require_key:
                add("correctAnswer", tr('尚未設定正確答案。'))
        elif (not isinstance(key, list) or not key or any(not isinstance(k, str) or k not in ids for k in key)
              or len(set(key)) != len(key)):
            add("correctAnswer", tr('正解須為此題現有區域 ID 的不重複清單，或明確設為 null。'))

    def invalid_answer_paths(self, q: dict, answers: dict) -> list[str]:
        bad = [f"answers.{k}" for k in answers if k != "selected"]
        selected = answers.get("selected")
        if selected is None:
            return bad
        ids = {a["id"] for a in q["areas"]}
        if (not isinstance(selected, list) or any(not isinstance(s, str) or s not in ids for s in selected)
                or len(set(selected)) != len(selected)):
            bad.append("answers.selected")
        return bad

    def sanitize(self, q: dict, answers: Any) -> dict:
        if not is_obj(answers) or not isinstance(answers.get("selected"), list):
            return {}
        chosen = {s for s in answers["selected"] if isinstance(s, str)}
        ordered = [a["id"] for a in q.get("areas", []) if is_obj(a) and a.get("id") in chosen]
        return {"selected": ordered} if ordered else {}

    def evaluate(self, q: dict, selections: dict) -> list[dict]:
        selection = selections.get("selected")
        key = [a["id"] for a in q["areas"] if a["id"] in set(q["correctAnswer"])]
        return [{"id": self.PART_ID, "selection": selection, "correctAnswer": key,
                 "isCorrect": selection is not None and set(selection) == set(key)}]

    def candidate_body(self, q: dict) -> dict:
        return {"background": q["background"],
                "areas": [{k: a[k] for k in ("id", "x", "y", "w", "h")} for a in q["areas"]]}


# ---------------------------------------------------------------- 註冊表
REGISTRY: dict[str, QuestionType] = {}


def register(question_type: QuestionType) -> None:
    REGISTRY[question_type.type_id] = question_type


for _t in (MultipleChoice(), FillInBlank(), DropdownMulti(), YesNoMatrix(), GoalSolution(), BuildList(), DragDrop(),
           HotArea()):
    register(_t)

TYPES = tuple(REGISTRY)


def get_type(type_id: str) -> QuestionType:
    try:
        return REGISTRY[type_id]
    except KeyError:
        raise ValueError(tr('不支援的題型：{0}', type_id)) from None


def new_question(type_id: str, question_id: str) -> dict:
    return get_type(type_id).new_question(question_id)


# ---------------------------------------------------------------- 驗證
def validate(question: Any, require_answer_key: bool = False) -> list[Error]:
    """回傳錯誤清單；空清單代表有效。status 為 ready 時一律要求完整正解。"""
    errors: list[Error] = []

    def add(path: str, message: str) -> None:
        errors.append({"path": path, "message": message})

    if not is_obj(question):
        return [{"path": "", "message": tr('題目必須是物件。')}]
    require_key = require_answer_key or question.get("status") == "ready"
    qtype = REGISTRY.get(question.get("type"))  # type: ignore[arg-type]
    allowed = COMMON_KEYS + (qtype.extra_keys if qtype else ())
    _extras(question, allowed, "", add)
    if "explanation" in question and not isinstance(question["explanation"], str):
        add("explanation", tr('解析須為字串。'))
    if question.get("schemaVersion") != SCHEMA_VERSION:
        add("schemaVersion", tr('只支援 schemaVersion 1.0。'))
    if not is_id(question.get("id")):
        add("id", tr('題目 ID 須為 1–64 字元的英數字、底線或連字號。'))
    if qtype is None:
        add("type", tr('不支援此題型。'))
    if question.get("status") not in STATUSES:
        add("status", tr('狀態須為 draft 或 ready。'))
    if not has_text(question.get("title")):
        add("title", tr('請填寫題目標題。'))
    if not isinstance(question.get("prompt"), str):
        add("prompt", tr('題目內容須為字串。'))
    if question.get("status") == "ready" and not has_text(strip_format(question.get("prompt") or "")):
        add("prompt", tr('可使用的題目必須填寫題目內容。'))
    _validate_images(question, add)
    scoring = question.get("scoring")
    if not is_obj(scoring) or scoring.get("mode") not in MODES:
        add("scoring.mode", tr('評分模式無效。'))
    if (not is_obj(scoring) or not is_number(scoring.get("maxScore"))
            or not 0 < scoring["maxScore"] <= MAX_SCORE_LIMIT):
        add("scoring.maxScore", tr('配分須大於 0，且不超過 1,000,000。'))
    if is_obj(scoring):
        _extras(scoring, ("mode", "maxScore"), "scoring", add)
    if qtype is None:
        return errors
    if "items" in qtype.extra_keys:
        items = question.get("items")
        if not isinstance(items, list) or not items:
            add("items", tr('至少需要一個作答欄位或敘述。'))
            return errors
        ids: set[str] = set()
        for index, item in enumerate(items):
            path = f"items[{index}]"
            if not is_obj(item):
                add(path, tr('項目須為物件。'))
                continue
            if "explanation" in item and not isinstance(item["explanation"], str):
                add(path + ".explanation", tr('逐項解析須為字串。'))
            if not is_id(item.get("id")) or item.get("id") in ids:
                add(path + ".id", tr('項目 ID 無效或重複。'))
            if isinstance(item.get("id"), str):
                ids.add(item["id"])
            if "correctAnswer" not in item:
                add(path + ".correctAnswer", tr('正解須明確設定，或設為 null。'))
    qtype.validate_body(question, add, require_key)
    return errors


def split_prompt(prompt: str) -> list[tuple[str, str]]:
    """把題目內容拆成 [("text", 文字) 或 ("image", 圖片ID)]，依出現順序。"""
    parts: list[tuple[str, str]] = []
    position = 0
    for match in IMAGE_TOKEN_RE.finditer(prompt or ""):
        if match.start() > position:
            parts.append(("text", prompt[position:match.start()]))
        parts.append(("image", match.group(1)))
        position = match.end()
    if position < len(prompt or ""):
        parts.append(("text", prompt[position:]))
    return parts


# 題目內容的文字格式：{{b}}粗體{{/b}}、{{size:18}}字級（pt）{{/size}}；可巢狀、可跨行、可包住圖片
FORMAT_TOKEN_RE = re.compile(r"\{\{(b|/b|size:(\d{1,2})|/size)\}\}")
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 48


def strip_format(text: str) -> str:
    """移除文字格式標記，只留純文字（與圖片標記）。"""
    return FORMAT_TOKEN_RE.sub("", text or "")


def has_format(text: Any) -> bool:
    return isinstance(text, str) and FORMAT_TOKEN_RE.search(text) is not None


def rich_segments(text: str) -> list[tuple]:
    """把含格式與圖片標記的文字拆成段落，依出現順序：

    ("runs", [(文字, 粗體, 字級或 None), ...]) 或 ("image", 圖片ID)。
    格式狀態會延續到圖片之後；多餘或不成對的結束標記會被忽略。
    """
    segments: list[tuple] = []
    runs: list[tuple[str, bool, int | None]] = []
    bold = 0
    sizes: list[int] = []
    pattern = re.compile(FORMAT_TOKEN_RE.pattern + "|" + IMAGE_TOKEN_RE.pattern)
    position = 0

    def flush_text(chunk: str) -> None:
        if chunk:
            runs.append((chunk, bold > 0, sizes[-1] if sizes else None))

    for match in pattern.finditer(text or ""):
        flush_text(text[position:match.start()])
        position = match.end()
        token = match.group(0)
        if token.startswith("{{image:"):
            if runs:
                segments.append(("runs", runs))
                runs = []
            segments.append(("image", IMAGE_TOKEN_RE.fullmatch(token).group(1)))
        elif token == "{{b}}":
            bold += 1
        elif token == "{{/b}}":
            bold = max(0, bold - 1)
        elif token == "{{/size}}":
            if sizes:
                sizes.pop()
        else:
            sizes.append(min(MAX_FONT_SIZE, max(MIN_FONT_SIZE, int(match.group(2)))))
    flush_text((text or "")[position:])
    if runs:
        segments.append(("runs", runs))
    return segments


def image_refs(prompt: Any) -> list[str]:
    return IMAGE_TOKEN_RE.findall(prompt) if isinstance(prompt, str) else []


def image_width(image: Any) -> int | None:
    """圖片設定的顯示寬度；未設定或無效時為 None。"""
    width = image.get("width") if isinstance(image, dict) else None
    if isinstance(width, int) and not isinstance(width, bool) and MIN_IMAGE_WIDTH <= width <= MAX_IMAGE_WIDTH:
        return width
    return None


def image_bytes(image: dict) -> bytes:
    return base64.b64decode(image["data"], validate=True)


def validate_image_list(images: Any, prefix: str, add: AddError) -> set[str]:
    """驗證圖片清單（題目或案例研究共用），回傳圖片 ID 集合。"""
    ids: set[str] = set()
    if not isinstance(images, list):
        add(prefix, tr('圖片須為清單。'))
        images = []
    for index, image in enumerate(images):
        path = f"{prefix}[{index}]"
        if not is_obj(image):
            add(path, tr('圖片須為物件。'))
            continue
        _extras(image, ("id", "mime", "data", "width"), path, add)
        if "width" in image and not (isinstance(image["width"], int) and not isinstance(image["width"], bool)
                                     and MIN_IMAGE_WIDTH <= image["width"] <= MAX_IMAGE_WIDTH):
            add(path + ".width", tr('圖片顯示寬度須為 {0}–{1} 的整數。', MIN_IMAGE_WIDTH, MAX_IMAGE_WIDTH))
        if not is_id(image.get("id")) or image.get("id") in ids:
            add(path + ".id", tr('圖片 ID 無效或重複。'))
        if isinstance(image.get("id"), str):
            ids.add(image["id"])
        if image.get("mime") not in IMAGE_MIMES:
            add(path + ".mime", tr('只支援 PNG、JPEG、GIF、WebP 圖片。'))
        data = image.get("data")
        try:
            if not isinstance(data, str) or not data:
                raise ValueError
            size = len(base64.b64decode(data, validate=True))
        except (ValueError, binascii.Error):
            add(path + ".data", tr('圖片資料不是有效的 base64。'))
            continue
        if size > MAX_IMAGE_BYTES:
            add(path + ".data", tr('圖片太大（上限 8 MB）。'))
    return ids


def _validate_images(question: dict, add: AddError) -> None:
    ids = validate_image_list(question.get("images", []), "images", add)
    for path, ref in _image_ref_fields(question):
        if ref not in ids:
            add(path, tr('引用了不存在的圖片：{0}', ref))


def _image_text_fields(question: dict) -> list[tuple[str, Any]]:
    qtype = REGISTRY.get(question.get("type"))
    return [("prompt", question.get("prompt"))] + (qtype.image_texts(question) if qtype else [])


def _image_ref_fields(question: dict) -> list[tuple[str, str]]:
    refs = [(path, ref) for path, text in _image_text_fields(question) for ref in image_refs(text)]
    qtype = REGISTRY.get(question.get("type"))
    return refs + (qtype.image_ids(question) if qtype else [])


def question_image_refs(question: dict) -> list[str]:
    """題目內容、選項與背景圖片引用的圖片 ID（依出現順序、不重複）。"""
    refs: list[str] = []
    for _path, ref in _image_ref_fields(question):
        if ref not in refs:
            refs.append(ref)
    return refs


def strip_images(text: str, placeholder: str | None = None) -> str:
    """把圖片標記換成簡短文字，用於提示、無障礙名稱與成績明細。"""
    placeholder = tr('［圖片］') if placeholder is None else placeholder
    return IMAGE_TOKEN_RE.sub(placeholder, text or "")


def format_errors(errors: list[Error]) -> str:
    return "\n".join(tr('{0}：{1}', e['path'] or tr('(題目)'), e['message']) for e in errors)


def sanitize_answers(question: dict, answers: Any) -> dict:
    """只保留指向現存項目／選項且型別正確的作答；用於題目修改後清除過時作答。"""
    qtype = REGISTRY.get(question.get("type")) if is_obj(question) else None
    return qtype.sanitize(question, answers) if qtype else {}


# ---------------------------------------------------------------- 評分
def grade(question: Any, answers: Any = None, allow_incomplete: bool = False) -> dict:
    """評分結果 status：unconfigured／invalid／incomplete／graded。只有 graded 有分數。"""
    if answers is None:
        answers = {}
    errors = validate(question, require_answer_key=True)
    if errors:
        qid = question.get("id") if is_obj(question) else None
        return {"status": "unconfigured", "questionId": qid, "score": None, "errors": errors}
    if not is_obj(answers):
        return {"status": "invalid", "questionId": question["id"], "score": None,
                "errors": [{"path": "answers", "message": tr('作答必須是物件。')}]}
    qtype = get_type(question["type"])
    bad = qtype.invalid_answer_paths(question, answers)
    if bad:
        return {"status": "invalid", "questionId": question["id"], "score": None,
                "errors": [{"path": p, "message": tr('答案指向不存在的項目、選項或使用了錯誤型別。')} for p in bad]}
    rows = qtype.evaluate(question, qtype.sanitize(question, answers))
    unanswered = [r["id"] for r in rows if r["selection"] is None]
    correct = sum(1 for r in rows if r["isCorrect"])
    result = {
        "questionId": question["id"],
        "type": question["type"],
        "maxScore": question["scoring"]["maxScore"],
        "totalParts": len(rows),
        "correctCount": correct,
        "unansweredIds": unanswered,
        "items": rows,
    }
    if unanswered and not allow_incomplete:
        return {**result, "status": "incomplete", "score": None}
    if question["scoring"]["mode"] == "all_or_nothing":
        fraction = 1.0 if correct == len(rows) else 0.0
    else:
        fraction = correct / len(rows)
    return {**result, "status": "graded", "score": _round6(fraction * question["scoring"]["maxScore"])}


def for_candidate(question: dict) -> dict:
    """建立不含正解與解析的考生展示資料。題目格式錯誤時拋出 ValueError。"""
    errors = validate(question)
    if errors:
        raise ValueError(format_errors(errors))
    dto = {
        "schemaVersion": question["schemaVersion"],
        "id": question["id"],
        "type": question["type"],
        "title": question["title"],
        "prompt": question["prompt"],
        "status": question["status"],
        "scoring": {"mode": question["scoring"]["mode"], "maxScore": question["scoring"]["maxScore"]},
    }
    refs = set(question_image_refs(question))
    if refs:
        dto["images"] = [dict(image) for image in question.get("images", []) if image["id"] in refs]
    dto.update(get_type(question["type"]).candidate_body(question))
    return dto


# ---------------------------------------------------------------- 編輯輔助
def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def move(seq: list, index: int, delta: int) -> int:
    """在清單內移動一個元素，回傳新位置；超出範圍時不動。"""
    target = index + delta
    if 0 <= index < len(seq) and 0 <= target < len(seq):
        seq[index], seq[target] = seq[target], seq[index]
        return target
    return index


def remove_option(question: dict, option_id: str, item_id: str | None = None) -> bool:
    """刪除選項。若刪除的是正解，正解改為 null（或從複選正解中移除）並回到草稿。回傳是否影響正解。"""
    if question["type"] == "multiple_choice":
        question["options"] = [o for o in question["options"] if o["id"] != option_id]
        key = question.get("correctAnswer")
        if isinstance(key, list) and option_id in key:
            key = [k for k in key if k != option_id]
            question["correctAnswer"] = key or None
            question["status"] = "draft"
            return True
        return False
    if question["type"] == "dropdown_multi":
        for item in question["items"]:
            if item["id"] == item_id:
                item["options"] = [o for o in item["options"] if o["id"] != option_id]
                if item.get("correctAnswer") == option_id:
                    item["correctAnswer"] = None
                    question["status"] = "draft"
                    return True
        return False
    if question["type"] == "build_list":
        question["choices"] = [c for c in question["choices"] if c["id"] != option_id]
        key = question.get("correctAnswer")
        if isinstance(key, list) and (option_id in key or question.get("reorderOnly")):
            key = [k for k in key if k != option_id]
            question["correctAnswer"] = key or None
            question["status"] = "draft"
            return True
        return False
    if question["type"] == "drag_drop":
        question["sources"] = [s for s in question["sources"] if s["id"] != option_id]
        affected = False
        for target in question["targets"]:
            if target.get("correctAnswer") == option_id:
                target["correctAnswer"] = None
                affected = True
        if affected:
            question["status"] = "draft"
        return affected
    if question["type"] == "hot_area":
        question["areas"] = [a for a in question["areas"] if a["id"] != option_id]
        key = question.get("correctAnswer")
        if isinstance(key, list) and option_id in key:
            question["correctAnswer"] = [k for k in key if k != option_id] or None
            question["status"] = "draft"
            return True
        return False
    raise ValueError(tr('此題型沒有可刪除的選項。'))


def set_select_mode(question: dict, mode: str) -> None:
    """切換單選／複選；改為單選時若已有多個正解，只保留第一個並回到草稿。"""
    question["selectMode"] = mode
    key = question.get("correctAnswer")
    if mode == "single":
        question["checkNumberSelected"] = False
        if isinstance(key, list) and len(key) > 1:
            question["correctAnswer"] = key[:1]
            question["status"] = "draft"


def summarize_selection(question: dict, row: dict, value: Any) -> str:
    """把作答／正解值轉成給人看的文字（成績明細與檢討使用）。"""
    qtype = question.get("type")
    if value is None:
        return tr('（未作答）')
    if qtype in ("yes_no_matrix", "goal_solution"):
        return "Yes" if value is True else "No"
    if qtype == "dropdown_multi":
        for item in question.get("items", []):
            if item["id"] == row["id"]:
                for option in item.get("options", []):
                    if option["id"] == value:
                        return option["text"]
        return str(value)
    if qtype == "multiple_choice":
        texts = {o["id"]: strip_images(o["text"]) for o in question.get("options", [])}
        return tr('；').join(texts.get(v, v) for v in value) if value else tr('（未作答）')
    if qtype == "fill_in_blank":
        return tr(' ／ ').join(value) if isinstance(value, list) else str(value)
    if qtype == "build_list":
        texts = {c["id"]: strip_images(c["text"]) for c in question.get("choices", [])}
        return " → ".join(texts.get(v, v) for v in value) if value else tr('（未作答）')
    if qtype == "drag_drop":
        texts = {s["id"]: strip_images(s["text"]) for s in question.get("sources", [])}
        return texts.get(value, str(value))
    if qtype == "hot_area":
        numbers = {a["id"]: tr('區域 {0}', i + 1) for i, a in enumerate(question.get("areas", []))}
        return tr('、').join(numbers.get(v, v) for v in value) if value else tr('（未作答）')
    return str(value)


# ---------------------------------------------------------------- 搜尋
_SEARCH_SKIP = {"images", "schemaVersion", "type", "status", "scoring", "background", "correctAnswer", "title",
                "selectMode", "areas"}


def search_text(question: Any) -> str:
    """題目中所有可搜尋的文字（題目內容、選項、解決方案、前後文字、解析、題目 ID 等），去掉格式與圖片標記。"""
    parts: list[str] = []

    def walk(value: Any, top: bool) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in _SEARCH_SKIP or (key == "id" and not top):
                    continue
                walk(child, False)
        elif isinstance(value, list):
            for child in value:
                walk(child, False)
        elif isinstance(value, str) and value.strip():
            parts.append(strip_images(strip_format(value), " "))

    walk(question, True)
    return "\n".join(parts)


def search_terms(query: str) -> list[str]:
    return [term.casefold() for term in (query or "").split() if term]


def search_matches(text: str, query: str) -> bool:
    """不分大小寫；多個關鍵字（以空白分隔）須全部出現。空白查詢視為符合。"""
    folded = (text or "").casefold()
    return all(term in folded for term in search_terms(query))


def search_snippet(text: str, query: str, width: int = 28) -> str:
    """第一個關鍵字附近的一小段文字（顯示在搜尋結果）。"""
    terms = search_terms(query)
    flat = " ".join((text or "").split())
    if not terms:
        return ""
    index = flat.casefold().find(terms[0])
    if index < 0:
        return ""
    start = max(0, index - width // 3)
    snippet = flat[start:start + width]
    return ("…" if start > 0 else "") + snippet + ("…" if start + width < len(flat) else "")
