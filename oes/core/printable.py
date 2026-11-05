"""把題庫轉成可列印的 HTML（PDF 匯出使用）。不依賴 Qt，圖片以名稱引用，由介面層載入。

所有題目文字一律先做 HTML 跳脫，只由程式加上標籤；不會解析使用者輸入的 HTML。
"""
from __future__ import annotations

import html
from datetime import date
from typing import Any

from ..i18n import tr
from . import exam as E
from . import question_types as qt
from . import session as S

CONTENT_WIDTH = 660          # 圖片最大寬度（像素，A4 直式扣除邊界）
CODE_STYLE = "font-family: Consolas, 'Courier New', monospace; white-space: pre-wrap;"
BOX = "☐"


def _esc(text: str) -> str:
    return html.escape(text or "").replace("\n", "<br>")


class PrintBuilder:
    """逐題產生 HTML；圖片請求記錄在 images：名稱 → {image, width, areas, correct}。"""

    def __init__(self, include_answers: bool):
        self.include_answers = include_answers
        self.images: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ 共用
    def image_tag(self, key: str, image: dict | None, *, max_width: int = CONTENT_WIDTH,
                  areas: list[dict] | None = None, correct: list[str] | None = None) -> str:
        if not image:
            return f"<p>{_esc(tr('［無法顯示的圖片：{0}］', key))}</p>"
        name = f"img{len(self.images) + 1}"
        self.images[name] = {"image": image, "width": qt.image_width(image), "max_width": max_width,
                             "areas": areas or [], "correct": correct or []}
        return f'<img src="{name}">'

    def rich(self, text: str, images: dict[str, dict], *, code: bool = False, max_width: int = CONTENT_WIDTH) -> str:
        """題目內容格式：粗體、字級、圖片；文字跳脫後才加上標籤。"""
        out: list[str] = []
        for kind, value in qt.rich_segments(text or ""):
            if kind == "image":
                out.append("<br>" + self.image_tag(value, images.get(value), max_width=max_width) + "<br>")
                continue
            for chunk, bold, size in value:
                piece = _esc(chunk)
                if bold:
                    piece = f"<b>{piece}</b>"
                if size:
                    piece = f'<span style="font-size:{int(size)}pt">{piece}</span>'
                out.append(piece)
        result = "".join(out)
        return f'<span style="{CODE_STYLE}">{result}</span>' if code else result

    def answer_line(self, text: str) -> str:
        return f'<p style="color:#1a7f37"><b>{_esc(tr("正確答案："))}</b>{text}</p>'

    def explain(self, label: str, text: str) -> str:
        if not self.include_answers or not (text or "").strip():
            return ""
        return f'<p style="color:#555555"><b>{_esc(label)}</b>{_esc(text)}</p>'

    @staticmethod
    def around(label: str, suffix: str) -> tuple[list[str], str, str, list[str]]:
        """欄位前後文字：（上方各行, 前文字, 後文字, 下方各行）。"""
        before = (label or "").split("\n")
        after = (suffix or "").split("\n")
        return before[:-1], before[-1], after[0], after[1:]

    # ------------------------------------------------------------ 各題型
    def body(self, q: dict) -> str:
        images = {i["id"]: i for i in q.get("images", []) if isinstance(i, dict)}
        method = getattr(self, "_" + q.get("type", ""), None)
        return method(q, images) if method else ""

    def _letter_list(self, items: list[tuple[str, bool]]) -> str:
        rows = []
        for index, (content, correct) in enumerate(items):
            mark = " ✔" if correct and self.include_answers else ""
            style = ' style="color:#1a7f37"' if correct and self.include_answers else ""
            rows.append(f"<tr><td width=\"36\" valign=\"top\">{BOX} {chr(65 + index) if index < 26 else index + 1}.</td>"
                        f"<td{style}>{content}<b>{mark}</b></td></tr>")
        return f'<table cellspacing="0" cellpadding="3">{"".join(rows)}</table>'

    def _multiple_choice(self, q: dict, images: dict) -> str:
        key = set(q.get("correctAnswer") or [])
        hint = tr('（複選）') if q.get("selectMode") == "multiple" else tr('（單選）')
        items = [(self.rich(o["text"], images, max_width=480), o["id"] in key) for o in q["options"]]
        out = f'<p style="color:#555555">{_esc(hint)}</p>' + self._letter_list(items)
        if self.include_answers:
            letters = [chr(65 + i) for i, o in enumerate(q["options"]) if o["id"] in key]
            out += self.answer_line(_esc("、".join(letters) or tr('未設定')))
        return out

    def _fill_in_blank(self, q: dict, images: dict) -> str:
        out = f"<p>{_esc(tr('答案：'))}______________________________</p>"
        if self.include_answers:
            out += self.answer_line(_esc(tr(' ／ ').join(q.get("acceptedAnswers") or [])))
        return out

    def _goal_solution(self, q: dict, images: dict) -> str:
        out = (f"<p><b>{_esc(tr('解決方案：'))}</b>{self.rich(q.get('solution', ''), images)}</p>"
               f"<p>{_esc(tr('此解決方案是否達成目標？'))}</p>")
        key = q.get("correctAnswer")
        out += self._letter_list([("Yes", key is True), ("No", key is False)])
        if self.include_answers:
            out += self.answer_line("Yes" if key is True else "No" if key is False else _esc(tr('未設定')))
        return out

    def _yes_no_matrix(self, q: dict, images: dict) -> str:
        rows = [f"<tr><th align=\"left\">{_esc(tr('敘述'))}</th><th>Yes</th><th>No</th></tr>"]
        for item in q["items"]:
            key = item.get("correctAnswer")
            yes = "✔" if self.include_answers and key is True else BOX
            no = "✔" if self.include_answers and key is False else BOX
            rows.append(f"<tr><td>{_esc(item['text'])}</td><td align=\"center\">{yes}</td>"
                        f"<td align=\"center\">{no}</td></tr>")
            if self.include_answers and (item.get("explanation") or "").strip():
                rows.append(f"<tr><td colspan=\"3\" style=\"color:#555555\">{_esc(tr('解析：'))}"
                            f"{_esc(item['explanation'])}</td></tr>")
        return f'<table border="1" cellspacing="0" cellpadding="4" width="100%">{"".join(rows)}</table>'

    def _field_rows(self, label: str, suffix: str, slot: str, code: bool) -> str:
        above, before, after, below = self.around(label, suffix)
        style = CODE_STYLE if code else ""
        lines = [f'<p style="{style}">{_esc(text)}</p>' for text in above]
        lines.append(f'<p style="{style}">{_esc(before)} {slot} {_esc(after)}</p>')
        lines += [f'<p style="{style}">{_esc(text)}</p>' for text in below]
        return "".join(lines)

    def _dropdown_multi(self, q: dict, images: dict) -> str:
        code = bool(q.get("codeFont"))
        out = []
        for index, item in enumerate(q["items"], 1):
            slot = f"<b>［ {index} ▾ ］</b>"
            out.append(self._field_rows(item.get("label", ""), item.get("suffix", ""), slot, code))
        out.append(f"<p><b>{_esc(tr('各欄位的選項：'))}</b></p>")
        for index, item in enumerate(q["items"], 1):
            key = item.get("correctAnswer")
            texts = []
            for option in item["options"]:
                text = _esc(option["text"])
                if self.include_answers and option["id"] == key:
                    text = f'<b style="color:#1a7f37">{text} ✔</b>'
                texts.append(text)
            style = CODE_STYLE if code else ""
            out.append(f'<p>［{index}］ <span style="{style}">{"／".join(texts)}</span></p>')
            out.append(self.explain(tr('解析：'), item.get("explanation", "")))
        return "".join(out)

    def _build_list(self, q: dict, images: dict) -> str:
        texts = {c["id"]: c["text"] for c in q["choices"]}
        title = q.get("choicesTitle") or tr('選項')
        out = [f"<p><b>{_esc(title)}</b></p><ul>"]
        out += [f"<li>{self.rich(c['text'], images, max_width=360)}</li>" for c in q["choices"]]
        out.append("</ul>")
        answer_title = q.get("answerTitle") or tr('答案區')
        count = len(q.get("correctAnswer") or []) or len(q["choices"])
        out.append(f"<p><b>{_esc(answer_title)}</b></p>")
        out += [f"<p>{n}. ______________________________</p>" for n in range(1, count + 1)]
        if self.include_answers:
            key = q.get("correctAnswer") or []
            tag = "ol" if q.get("orderMatters", True) else "ul"
            items = "".join(f"<li>{_esc(qt.strip_images(texts.get(k, k)))}</li>" for k in key)
            out.append(self.answer_line("") + f"<{tag}>{items}</{tag}>")
        return "".join(out)

    def _drag_drop(self, q: dict, images: dict) -> str:
        code = bool(q.get("codeFont"))
        texts = {s["id"]: s["text"] for s in q["sources"]}
        title = (q.get("sourcesTitle") or "").strip() or tr('值')
        style = CODE_STYLE if code else ""
        hint = tr('（可以重複使用）') if q.get("reuseSources") else tr('（每個值只能用一次）')
        out = [f"<p><b>{_esc(title)}</b> {_esc(hint)}</p><ul>"]
        out += [f'<li><span style="{style}">{self.rich(s["text"], images, max_width=360)}</span></li>'
                for s in q["sources"]]
        out.append(f"</ul><p><b>{_esc(tr('答案區'))}</b></p>")
        for target in q["targets"]:
            key = target.get("correctAnswer")
            if self.include_answers and key in texts:
                slot = f'<b style="color:#1a7f37">［ {_esc(qt.strip_images(texts[key]))} ］</b>'
            else:
                slot = "［ ____________________ ］"
            out.append(self._field_rows(target.get("label", ""), target.get("suffix", ""), slot, code))
            out.append(self.explain(tr('解析：'), target.get("explanation", "")))
        return "".join(out)

    def _hot_area(self, q: dict, images: dict) -> str:
        correct = (q.get("correctAnswer") or []) if self.include_answers else []
        tag = self.image_tag(q.get("background") or "", images.get(q.get("background")),
                             areas=q.get("areas") or [], correct=list(correct))
        note = tr('請在圖片中框出的區域內點選答案。')
        if self.include_answers:
            note = tr('綠色區域為正確答案。')
        return f'{tag}<p style="color:#555555">{_esc(note)}</p>'

    # ------------------------------------------------------------ 整份題庫
    def question(self, number: int, entry: dict, exam: dict) -> str:
        q = entry["question"]
        images = {i["id"]: i for i in q.get("images", []) if isinstance(i, dict)}
        meta = [tr(qt.get_type(q["type"]).label)] if q.get("type") in qt.REGISTRY else []
        section = E.section_name(exam, entry.get("sectionId"))
        if section:
            meta.append(section)
        parts = [f'<h3 style="page-break-inside: avoid">{_esc(tr("題目{0}", number))}'
                 f' <span style="font-size:9pt; font-weight:normal; color:#777777">{_esc("｜".join(meta))}</span></h3>']
        if q.get("type") == "goal_solution":
            parts.append(f'<p style="color:#555555"><i>{_esc(tr(SERIES_NOTE))}</i></p>')
        parts.append(f"<p>{self.rich(q.get('prompt', ''), images)}</p>")
        parts.append(self.body(q))
        parts.append(self.explain(tr('解析：'), q.get("explanation", "")))
        return "".join(parts) + "<hr>"

    def case_block(self, case: dict) -> str:
        images = {i["id"]: i for i in case.get("images", []) if isinstance(i, dict)}
        return (f'<table border="1" cellspacing="0" cellpadding="8" width="100%"><tr><td>'
                f"<p><b>{_esc(tr('案例研究：{0}', case.get('name', '')))}</b></p>"
                f"<p>{self.rich(case.get('text', ''), images)}</p></td></tr></table><br>")


SERIES_NOTE = ("注意：本題屬於同一情境的系列題。系列中的每一題各提出一個解決方案，可能達成、也可能無法達成所述目標。"
               "有些系列可能有不只一個正確的解決方案，有些可能沒有正確的解決方案。")


def printable_entries(exam: dict, only_ready: bool) -> list[dict]:
    if not only_ready:
        return list(exam.get("questions", []))
    usable, _excluded = S.eligible_entries(exam)
    return usable


def build_html(exam: dict, *, include_answers: bool = True, only_ready: bool = False,
               today: date | None = None) -> tuple[str, dict[str, dict[str, Any]]]:
    """回傳（HTML, 圖片請求）。圖片請求的名稱即 HTML 中 <img src> 的值。"""
    builder = PrintBuilder(include_answers)
    entries = printable_entries(exam, only_ready)
    title = exam.get("title") or tr('未命名題庫')
    info = [tr('{0} 題', len(entries)), (today or date.today()).isoformat()]
    if exam.get("number"):
        info.insert(0, exam["number"])
    info.append(tr('含正確答案與解析') if include_answers else tr('不含答案'))
    parts = [f"<h1>{_esc(title)}</h1>", f'<p style="color:#555555">{_esc("｜".join(info))}</p>']
    if exam.get("showDescription") and (exam.get("description") or "").strip():
        parts.append(f"<p>{_esc(exam['description'])}</p>")
    parts.append("<hr>")
    shown_cases: set[str] = set()
    for number, entry in enumerate(entries, 1):
        case_id = entry.get("caseStudyId")
        if case_id and case_id not in shown_cases:
            case = E.case_study(exam, case_id)
            if case:
                parts.append(builder.case_block(case))
                shown_cases.add(case_id)
        parts.append(builder.question(number, entry, exam))
    if not entries:
        parts.append(f"<p>{_esc(tr('沒有可匯出的題目。'))}</p>")
    return "".join(parts), builder.images
