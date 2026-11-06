"""打包後的自我檢查（OpenExamSimulator.exe --self-test 結果檔）。

不開出視窗：載入示範題庫、建立各畫面、作答並評分、切換深色主題與英文介面，
把每一步的結果寫進結果檔。全部成功時回傳 0。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path


def run_self_test(output: str) -> int:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    lines: list[str] = []
    ok = True

    def step(name: str, func) -> object:
        nonlocal ok
        try:
            value = func()
            shown = str(value)
            if len(shown) > 120:  # 例如整份作答資料，只記摘要
                shown = f"<{type(value).__name__}，{len(shown)} 字元>"
            lines.append(f"OK    {name}: {shown}")
            return value
        except Exception:  # noqa: BLE001 - 自我檢查要記錄所有錯誤
            ok = False
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")
            return None

    try:
        from PySide6.QtWidgets import QApplication

        from .. import __version__, i18n
        from ..core import session as S
        from ..storage.history import HistoryStore, app_dir, resource_dir
        from . import theme
        from .i18n import install_translations

        app = QApplication.instance() or QApplication([sys.argv[0]])
        lines.append(f"Open Exam Simulator {__version__}  frozen={getattr(sys, 'frozen', False)}")
        lines.append(f"app_dir={app_dir()}  resource_dir={resource_dir()}")
        step("Qt 繁體中文翻譯檔", lambda: install_translations(app, "zh_TW"))
        step("套用淺色主題", lambda: theme.apply_theme(app, "light"))

        def webp_roundtrip():
            from PySide6.QtGui import QColor, QImage
            from PySide6.QtCore import QByteArray
            from .prompt_editor import _same_pixels, _save, webp_supported
            if not webp_supported():
                raise RuntimeError("Qt WebP plugin (imageformats/qwebp) not found")
            image = QImage(64, 32, QImage.Format.Format_RGB32)
            image.fill(QColor("white"))
            for x in range(0, 64, 4):
                image.setPixelColor(x, x // 2, QColor(200, 30, 30))
            data = _save(image, "WEBP", 100)
            decoded = QImage()
            if not decoded.loadFromData(QByteArray(data)) or not _same_pixels(image, decoded):
                raise RuntimeError("WebP round trip is not lossless")
            return f"{len(data)} bytes, lossless"
        step("WebP 無失真圖片", webp_roundtrip)
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["OES_DATA_DIR"] = tmp
            from .exam_window import ExamWindow, ReportDialog
            from .main_window import SAMPLE_PATH, MainWindow
            store = HistoryStore(Path(tmp) / "history.db")
            window = step("建立主視窗", lambda: MainWindow(store))
            def sample_exists():
                if not SAMPLE_PATH.is_file():
                    raise FileNotFoundError(SAMPLE_PATH)
                return SAMPLE_PATH
            step("示範題庫存在", sample_exists)
            step("開啟示範題庫", lambda: window.open_path(SAMPLE_PATH) and f"{len(window.exam['questions'])} 題")

            def walk_pages():
                for row in range(window.listing.count()):
                    window.listing.setCurrentRow(row)
                    window.question_page.tabs.setCurrentIndex(1)
                    window.question_page.tabs.setCurrentIndex(0)
                return f"{window.listing.count()} 頁"
            step("逐一開啟題目編輯與預覽", walk_pages)
            def pdf():
                from .pdf_export import export_pdf
                target = Path(tmp) / "selftest.pdf"
                pages = export_pdf(window.exam, target, include_answers=True)
                if not target.read_bytes().startswith(b"%PDF"):
                    raise RuntimeError("not a PDF file")
                return f"{pages} pages, {target.stat().st_size} bytes"
            step("匯出 PDF", pdf)
            session = step("出題", lambda: S.build_session(window.exam))

            def answer_all():
                from unittest import mock
                from PySide6.QtWidgets import QMessageBox
                exam_window = ExamWindow(session, store)
                # 系列題離開時會詢問「尚未作答，確定要離開？」：自動回答「是」
                with mock.patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                    for index in range(len(session["questions"])):
                        exam_window.go(index)
                exam_window._finish(confirmed=True)
                ReportDialog(session, store)
                return f"{session['report']['percent']}%"
            if session:
                step("作答視窗與成績報告", answer_all)
            step("切換深色主題", lambda: theme.apply_theme(app, "dark"))
            window.dirty = False

            def english():
                i18n.set_language("en")
                install_translations(app, "en")
                replacement = MainWindow(store)
                replacement.set_exam(window.exam, None)
                replacement.dirty = False
                return replacement.act_open.text()
            step("英文介面", english)
            os.environ.pop("OES_DATA_DIR", None)
    except Exception:  # noqa: BLE001
        ok = False
        lines.append("FAIL  啟動\n" + traceback.format_exc())
    lines.append("RESULT: " + ("PASS" if ok else "FAIL"))
    Path(output).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if ok else 1


def hard_exit(code: int) -> None:
    """直接結束程序（打包版的 --self-test 使用）：無視窗模式下卸載 Qt 程式庫可能發生存取違規，讓結束代碼失準。"""
    sys.stdout.flush() if sys.stdout else None
    sys.stderr.flush() if sys.stderr else None
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)
