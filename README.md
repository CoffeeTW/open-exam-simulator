# Open Exam Simulator

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Tests](https://github.com/CoffeeTW/open-exam-simulator/actions/workflows/build.yml/badge.svg)](https://github.com/CoffeeTW/open-exam-simulator/actions/workflows/build.yml)
[![Release](https://img.shields.io/github/v/release/CoffeeTW/open-exam-simulator)](https://github.com/CoffeeTW/open-exam-simulator/releases)

離線的 Windows 題庫編輯、作答與評分工具。
An offline Windows app for writing question banks, taking practice exams and scoring them.

[繁體中文](#繁體中文) ｜ [English](#english)

> **免責聲明 / Disclaimer**
> 本專案與 Avanset、Microsoft、Oracle 或任何認證機構無關，不提供、也不協助取得任何考試題目，也不讀取 `.vce` 檔。
> 請只使用您自己編寫或有權使用的題目，並遵守各認證考試的考生保密協議。
>
> This project is not affiliated with Avanset, Microsoft, Oracle or any certification body. It does not provide or help obtain
> exam questions, and it does not read `.vce` files. Only use questions you wrote yourself or have the right to use, and respect
> the candidate agreement of each certification exam.

---

## 繁體中文

### 下載與安裝

1. 到 [Releases](https://github.com/CoffeeTW/open-exam-simulator/releases) 下載最新版的 `OpenExamSimulator-win64.zip`。
2. 解壓縮到任意資料夾（例如 `D:\OpenExamSimulator`），執行 `OpenExamSimulator.exe`。不需要安裝 Python。
3. 想先看範例：選單「檔案 → 開啟示範題庫」。

**Windows 顯示「Windows 已保護您的電腦」？** 本程式沒有付費的程式碼簽章，第一次執行時 SmartScreen 可能出現警告。
請按「其他資訊」→「仍要執行」。您也可以用 PowerShell 的 `Get-FileHash OpenExamSimulator-win64.zip` 比對 Release 頁面上的
SHA-256 校驗碼，或依下方說明自行從原始碼建置。

作答紀錄（`history.db`）與設定（`settings.json`）存在程式所在資料夾；解壓縮到可寫入的位置即可（不建議放在 `Program Files`）。

### 功能

| 功能 | 說明 |
|---|---|
| 8 種題型 | 選擇題（單選／複選）、填空題、多欄位下拉選單題、逐列 Yes／No 判斷題、排序題、拖放題、熱區題、解決方案評估題（Does this meet the goal? 系列題） |
| 指令腳本版面 | 下拉選單題與拖放題可使用程式碼字型、欄位前後文字與固定文字行，適合 PowerShell 等指令填空題 |
| 題目內容 | 粗體、字級、貼上或拖放圖片；圖片可用滑鼠拖曳、右鍵輸入像素調整大小，也可複製到其他題目 |
| 案例研究 | 多題共用一段情境（含圖片），作答時可隨時開啟 |
| 作答 | 正式考試或練習模式；指定章節、題數、隨機出題、計時；標記題目、題目總覽；自動保存、可中斷後繼續 |
| 成績 | 及格判定、章節分數、逐題明細與解析；重考答錯或標記的題目 |
| 搜尋 | 依題目內容、選項、解析或題目 ID 篩選題目清單（Ctrl+F） |
| 匯出 | 匯出 PDF（可含或不含答案）、題庫 JSON、單題 JSON |
| 其他 | 繁體中文／英文介面、淺色／深色主題、圖片以 WebP 無失真格式儲存並自動去除重複 |

### 從原始碼執行

1. 安裝 [Python](https://www.python.org/downloads/) 3.10 以上版本（安裝時勾選「Add python.exe to PATH」）。
2. 雙擊 `run.bat`。第一次執行會建立 `.venv` 並安裝 PySide6，之後直接開啟。
3. 測試：雙擊 `run_tests.bat`（結果存在 `test-results.txt`）。
4. 打包 EXE：雙擊 `build.bat`，輸出 `dist\OpenExamSimulator\` 與 `dist\OpenExamSimulator-win64.zip`，並自動執行自我檢查。

手動執行：`python -m pip install -r requirements.txt`，然後 `python -m oes [題庫.oes]`。

### 檔案格式

題庫檔 `.oes` 是 SQLite 資料庫，也可以匯入／匯出 JSON。詳細格式見 [docs/file-format.md](docs/file-format.md)。

---

## English

### Download

1. Download `OpenExamSimulator-win64.zip` from [Releases](https://github.com/CoffeeTW/open-exam-simulator/releases).
2. Unzip it anywhere (for example `D:\OpenExamSimulator`) and run `OpenExamSimulator.exe`. Python is not required.
3. To see an example, choose **File → Open sample exam**. Switch the interface language under **View → 語言 / Language**.

**"Windows protected your PC"?** The app is not code-signed, so SmartScreen may warn on first launch. Click
**More info → Run anyway**. You can verify the download against the SHA-256 checksum on the Release page
(`Get-FileHash OpenExamSimulator-win64.zip` in PowerShell) or build it from source.

### Features

- 8 question types: multiple choice, fill in the blank, multi-field drop-down, Yes/No matrix, build list, drag and drop,
  hot area, and "does this solution meet the goal?" series questions.
- Script-style layouts for drop-down and drag-and-drop questions (code font, text before/after each field, fixed lines).
- Bold text, font sizes and images in questions; resize images by dragging or by entering a pixel size; copy images between questions.
- Case studies shared by several questions.
- Exam and practice modes, sections, random order, timer, marking, overview, autosave and resume.
- Score reports with section scores, per-question review and explanations; retake wrong or marked questions.
- Search (Ctrl+F), PDF export with or without answers, JSON import/export.
- Traditional Chinese and English interface, light and dark themes, lossless WebP image storage with de-duplication.

### Run from source

Requires Python 3.10+. Run `run.bat` (creates `.venv` and installs PySide6), `run_tests.bat` for the test suite,
and `build.bat` to build the Windows package with PyInstaller. See [docs/file-format.md](docs/file-format.md) for the data formats.

---

## 授權 / License

Copyright (C) 2026 CoffeeTW

本程式為自由軟體，依 [GNU General Public License v3.0](LICENSE)（或您選擇的任何更新版本）授權。
This program is free software, licensed under the [GNU General Public License v3.0](LICENSE) or (at your option) any later version.

第三方元件（Qt、PySide6 等）的授權見 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
Third-party components (Qt, PySide6 and others) are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## 回報問題 / Issues

歡迎到 [Issues](https://github.com/CoffeeTW/open-exam-simulator/issues) 回報問題或提出建議。回報時請附上
「說明 → 關於 → 複製資訊」的內容與重現步驟。**請不要貼上真實考試題目。**
Bug reports and suggestions are welcome. Please include the text from **Help → About → Copy Info**.
**Do not post real exam questions.**
