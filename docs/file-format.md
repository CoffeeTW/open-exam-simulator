# 檔案格式 / File Formats

本文件說明 Open Exam Simulator 0.4 的資料格式，方便撰寫匯入、轉換工具。
This document describes the data formats used by Open Exam Simulator 0.4, for anyone writing import or conversion tools.

## 題庫檔 `.oes`（第 3 版）

`.oes` 是 SQLite 資料庫（`PRAGMA user_version = 3`）：

| 資料表 | 內容 |
|---|---|
| `meta(key, value)` | 題庫屬性，value 為 JSON：`format`、`schemaVersion`、`id`、`title`、`number`、`version`、`passingScore`、`timeLimitMinutes`、`description`、`showDescription`、`caseStudies` |
| `sections(id, position, name)` | 章節與順序 |
| `questions(id, position, section_id, case_study_id, type, status, title, data, updated_at)` | 每題一列，`data` 為題目 JSON |
| `images(hash, mime, data)` | 圖片二進位資料，以 SHA-256 為鍵；相同圖片只存一份 |

題目 JSON 中的圖片以 `{"id": "img1", "mime": "image/webp", "blob": "<sha256>", "width": 400}` 引用 `images` 資料表；
讀入程式後會換回 `{"id", "mime", "data": "<base64>", "width"?}`。第 1、2 版（圖片直接以 base64 存在 JSON）仍可讀取。

儲存時先寫入同目錄的暫存檔，再整檔替換，避免寫到一半損毀。

## 題庫 JSON（匯入／匯出）

```json
{
  "format": "open-exam-simulator/exam",
  "schemaVersion": "1.0",
  "id": "exam-…", "title": "…", "number": "", "version": "", "passingScore": 70, "timeLimitMinutes": 0,
  "description": "", "showDescription": false,
  "sections": [{"id": "sec1", "name": "第一章"}],
  "caseStudies": [{"id": "case1", "name": "…", "text": "…", "images": []}],
  "questions": [{"sectionId": "sec1", "caseStudyId": "case1", "question": { … }}]
}
```

匯入也接受單一題目、題目陣列，或以名稱為鍵的題目物件。

## 題目共同欄位

| 欄位 | 說明 |
|---|---|
| `schemaVersion` | 固定 `"1.0"` |
| `id` | 1–64 字元的英數字、底線或連字號；建立後不變 |
| `type` | 題型，見下表 |
| `status` | `draft`（草稿，不出題）或 `ready`（可使用，須有完整正解） |
| `title` | 內部名稱（畫面上以「題目N」顯示） |
| `prompt` | 題目內容，可含格式與圖片標記 |
| `scoring` | `{"mode": "all_or_nothing" | "per_part", "maxScore": 數字}` |
| `explanation` | 整題解析 |
| `images` | 選填，`[{"id", "mime", "data", "width"?}]`；mime 為 PNG、JPEG、GIF、WebP |

### 文字標記

- 圖片：`{{image:圖片ID}}`
- 粗體：`{{b}}…{{/b}}`
- 字級（8–48 pt）：`{{size:18}}…{{/size}}`

使用者文字一律以純文字顯示，不解析 HTML。

## 各題型

| `type` | 專屬欄位 | 作答格式 |
|---|---|---|
| `multiple_choice` | `selectMode`（`single`／`multiple`）、`shuffle`、`checkNumberSelected`、`options[{id, text}]`、`correctAnswer`（選項 ID 陣列或 null） | `{"selected": ["o1"]}` |
| `fill_in_blank` | `acceptedAnswers[]`、`caseSensitive`、`ignoreMultipleSpaces`、`trimResponse` | `{"text": "…"}` |
| `dropdown_multi` | `items[{id, label, suffix?, options[{id, text}], correctAnswer, explanation}]`、`codeFont?` | `{"欄位ID": "選項ID"}` |
| `yes_no_matrix` | `items[{id, text, correctAnswer(true/false/null), explanation}]` | `{"列ID": true | false}` |
| `goal_solution` | `solution`、`noReturn`、`correctAnswer`（true/false/null） | `{"answer": true | false}` |
| `build_list` | `choices[{id, text}]`、`reorderOnly`、`orderMatters`、`choicesTitle`、`answerTitle`、`correctAnswer`（ID 陣列） | `{"sequence": ["c1", "c2"]}` |
| `drag_drop` | `sources[{id, text}]`、`targets[{id, label, suffix?, correctAnswer, explanation}]`、`reuseSources`、`sourcesTitle?`、`codeFont?` | `{"空格ID": "值ID"}` |
| `hot_area` | `background`（圖片 ID）、`areas[{id, x, y, w, h}]`、`correctAnswer`（區域 ID 陣列） | `{"selected": ["a1"]}` |

`label`／`suffix` 可含換行：`label` 除最後一行、`suffix` 除第一行，各自顯示為獨立一行（例如沒有作答的固定步驟或程式碼）。

## 評分

- `all_or_nothing`：所有項目都正確才得到 `maxScore`。
- `per_part`：答對項目數 ÷ 總項目數 × `maxScore`，四捨五入到小數 6 位。
- 結果狀態：`graded`（已評分）、`incomplete`（有未作答項目）、`invalid`（作答格式錯誤）、`unconfigured`（題目沒有完整正解）。

## 作答紀錄 `history.db`（第 2 版）

SQLite：`sessions`（每次作答，`data` 為工作階段 JSON，含出題當下的題目快照）、`images`、`session_images`（圖片共用與引用）。
