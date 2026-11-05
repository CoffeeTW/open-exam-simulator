"""產生程式圖示 .ico（打包時使用）。用法：python tools/make_icon.py 輸出路徑"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from oes.ui.theme import icon  # noqa: E402


def main(target: str) -> int:
    app = QApplication.instance() or QApplication([])
    image = QImage(256, 256, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#2563eb"))
    painter.setPen(QColor("#2563eb"))
    painter.drawRoundedRect(8, 8, 240, 240, 48, 48)
    painter.drawPixmap(40, 40, icon("exam", "#ffffff", 176).pixmap(176, 176))
    painter.end()
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    ok = image.save(target, "ICO") or image.save(str(Path(target).with_suffix(".png")), "PNG")
    del app
    print("icon:", target if ok else "failed")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "build/app.ico"))
