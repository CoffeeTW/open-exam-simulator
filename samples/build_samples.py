"""產生示範題庫 samples/示範題庫.oes 與 samples/示範題庫.json。

用法（於專案根目錄）：python samples/build_samples.py
所有題目皆為原創示範內容，只用來試用作答與評分；兩題「草稿範本」沒有正解，維持草稿，不會出題。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import base64  # noqa: E402
import struct  # noqa: E402
import zlib  # noqa: E402

from oes.core import exam as E  # noqa: E402
from oes.core import question_types as C  # noqa: E402
from oes.storage.exam_file import save_exam  # noqa: E402

FIXTURES = json.loads((ROOT / "tests" / "fixtures" / "fixtures.json").read_text(encoding="utf-8"))


def simple_png(width: int, height: int, boxes: list[tuple[int, int, int, int, tuple[int, int, int]]]) -> str:
    """不依賴其他套件產生 PNG（白底加上幾個色塊），回傳 base64。"""
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            color = (255, 255, 255)
            for bx, by, bw, bh, c in boxes:
                if bx <= x < bx + bw and by <= y < by + bh:
                    color = c
            row += bytes(color)
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def build() -> dict:
    exam = E.new_exam("示範題庫")
    exam.update(id="exam-demo", number="DEMO-001", passingScore=70, timeLimitMinutes=0,
                description="示範各題型的編輯、作答與評分。兩題「草稿範本」沒有正解，維持草稿，不會出題。",
                showDescription=True)
    basic = E.add_section(exam, "基本題型")["id"]
    new = E.add_section(exam, "新增題型")["id"]

    single = C.new_question("multiple_choice", "demo-single")
    single.update(status="ready", title="操作示範：單選題", prompt="下列哪一個數字是質數？",
                  options=[{"id": "o1", "text": "4"}, {"id": "o2", "text": "9"},
                           {"id": "o3", "text": "11"}, {"id": "o4", "text": "15"}],
                  correctAnswer=["o3"], shuffle=True, explanation="11 只能被 1 和自己整除。")
    multiple = C.new_question("multiple_choice", "demo-multiple")
    multiple.update(status="ready", title="操作示範：複選題", prompt="下列哪些數字是偶數？（選兩個）",
                    selectMode="multiple", checkNumberSelected=True,
                    options=[{"id": "o1", "text": "2"}, {"id": "o2", "text": "3"},
                             {"id": "o3", "text": "8"}, {"id": "o4", "text": "13"}],
                    correctAnswer=["o1", "o3"], explanation="能被 2 整除的是偶數。")
    fill = C.new_question("fill_in_blank", "demo-fill")
    fill.update(status="ready", title="操作示範：填空題", prompt="一週有幾天？請以阿拉伯數字或中文作答。",
                acceptedAnswers=["7", "七"], explanation="一週有 7 天。")
    for question in (single, multiple, fill):
        exam["questions"].append({"sectionId": basic, "question": question})
    for name in ("demoDropdown", "demoYesNo", "imageDropdown", "imageYesNo"):
        exam["questions"].append({"sectionId": new, "question": FIXTURES[name]})

    more = E.add_section(exam, "常見題型")["id"]
    case = E.add_case_study(exam, "示範案例：早餐店")
    case["text"] = ("小明開了一家早餐店，每天早上 6 點開門。\n"
                    "需求：\n1. 開門前要完成備料。\n2. 客人點餐後先收款，再製作餐點。")
    order = C.new_question("build_list", "demo-build-list")
    order.update(status="ready", title="操作示範：排序題",
                 prompt="依案例研究的需求，把客人點餐到取餐的步驟依序排入答案區（有一個多餘的選項）。",
                 choices=[{"id": "c1", "text": "製作餐點"}, {"id": "c2", "text": "收款"},
                          {"id": "c3", "text": "交給客人"}, {"id": "c4", "text": "關店打烊"},
                          {"id": "c5", "text": "客人點餐"}],
                 correctAnswer=["c5", "c2", "c1", "c3"], explanation="點餐 → 收款 → 製作 → 交付。")
    exam["questions"].append({"sectionId": more, "caseStudyId": case["id"], "question": order})

    drag = C.new_question("drag_drop", "demo-drag-drop")
    drag.update(status="ready", title="操作示範：拖放題", prompt="把每種動物拖到牠的主要棲地。",
                scoring={"mode": "per_part", "maxScore": 2},
                sources=[{"id": "v1", "text": "海洋"}, {"id": "v2", "text": "沙漠"},
                         {"id": "v3", "text": "極地"}, {"id": "v4", "text": "雨林"}],
                targets=[{"id": "t1", "label": "企鵝：", "correctAnswer": "v3", "explanation": ""},
                         {"id": "t2", "label": "駱駝：", "correctAnswer": "v2", "explanation": ""},
                         {"id": "t3", "label": "海豚：", "correctAnswer": "v1", "explanation": ""}])
    exam["questions"].append({"sectionId": more, "question": drag})

    hot = C.new_question("hot_area", "demo-hot-area")
    hot.update(status="ready", title="操作示範：熱區題", prompt="下圖有紅、綠、藍三個方塊，請點選綠色與藍色方塊。",
               background="img1",
               images=[{"id": "img1", "mime": "image/png", "data": simple_png(
                   320, 120, [(20, 30, 80, 60, (220, 40, 40)), (120, 30, 80, 60, (40, 170, 70)),
                              (220, 30, 80, 60, (40, 90, 220))])}],
               areas=[{"id": "a1", "x": 20, "y": 30, "w": 80, "h": 60},
                      {"id": "a2", "x": 120, "y": 30, "w": 80, "h": 60},
                      {"id": "a3", "x": 220, "y": 30, "w": 80, "h": 60}],
               correctAnswer=["a2", "a3"])
    exam["questions"].append({"sectionId": more, "question": hot})

    series = E.add_section(exam, "系列題")["id"]
    scenario = ("公司的檔案伺服器 FS1 上有一個共用資料夾 Reports。\n"
                "目標：業務部的使用者可以讀取 Reports 中的檔案，但不能修改。")
    for qid, solution, key, why in (
            ("demo-goal-1", "在 Reports 的共用權限與 NTFS 權限中，都只授與「業務部」群組讀取權限。", True,
             "有效權限取共用權限與 NTFS 權限中較嚴格者，兩者都是讀取，因此只能讀取。"),
            ("demo-goal-2", "把「業務部」群組加入 FS1 的本機 Administrators 群組。", False,
             "Administrators 擁有完整控制權限，使用者可以修改檔案，不符合目標。")):
        goal = C.new_question("goal_solution", qid)
        goal.update(status="ready", title="操作示範：解決方案評估題", prompt=scenario, solution=solution,
                    correctAnswer=key, explanation=why)
        exam["questions"].append({"sectionId": series, "question": goal})
    errors = E.validate_exam(exam, strict_questions=True)
    if errors:
        raise SystemExit(C.format_errors(errors))
    return exam


if __name__ == "__main__":
    exam = build()
    out = ROOT / "samples"
    save_exam(out / "示範題庫.oes", exam)
    (out / "示範題庫.json").write_text(E.export_exam_json(exam), encoding="utf-8")
    print(f"已產生 {out / '示範題庫.oes'}（{len(exam['questions'])} 題）")
