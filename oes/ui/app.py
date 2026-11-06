"""程式進入點。"""
from __future__ import annotations

from ..i18n import tr

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if "--self-test" in argv:  # 打包後的自我檢查：OpenExamSimulator.exe --self-test 結果檔
        index = argv.index("--self-test")
        output = argv[index + 1] if index + 1 < len(argv) else "selftest.txt"
        from .selftest import hard_exit, run_self_test
        hard_exit(run_self_test(output))
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(tr('找不到 PySide6。請先執行：python -m pip install -r requirements.txt'), file=sys.stderr)
        return 1
    from .main_window import MainWindow
    from .theme import apply_theme, icon

    app = QApplication(argv)
    app.setApplicationName("Open Exam Simulator")
    app.setOrganizationName("OpenExamSimulator")
    from ..i18n import set_language
    from . import settings as user_settings
    from .i18n import install_translations
    language = set_language(user_settings.load().get("language", "zh_TW"))
    install_translations(app, language)
    from . import settings
    apply_theme(app, settings.load().get("theme", "light"))
    app.setWindowIcon(icon("exam", "#2563eb", 64))
    window = MainWindow()
    window.show()
    for arg in argv[1:]:
        path = Path(arg)
        if path.suffix.lower() == ".oes" and path.is_file():
            window.open_path(path)
            break
    return app.exec()
