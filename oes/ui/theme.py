"""介面主題：配色、全域樣式表與程式繪製的線條圖示。

所有顏色集中在 COLORS；樣式表以 Fusion 風格為基礎，讓 Windows 10/11 外觀一致。
圖示以 QPainter 繪製（不依賴外部圖檔），可隨主題顏色調整。
"""
from __future__ import annotations

import sys
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication

THEMES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f3f5f8", "surface": "#ffffff", "surface_alt": "#f8fafc", "border": "#d9dee5",
        "border_strong": "#b8c1cc", "text": "#1f2933", "muted": "#66717f", "placeholder": "#98a2ae",
        "accent": "#2563eb", "accent_hover": "#1d4fd8", "accent_soft": "#e7efff", "pressed": "#d6e3ff",
        "ok": "#1a7f37", "ok_soft": "#e6f4ea", "ok_border": "#a9d8b6",
        "warn": "#b26a00", "warn_soft": "#fff4e0",
        "bad": "#c62828", "bad_soft": "#fdecec", "bad_border": "#f0b3b3", "danger_border": "#e7a6a6",
        "scroll": "#c3cad3", "scroll_hover": "#9aa5b1", "tooltip_bg": "#1f2933", "tooltip_text": "#ffffff",
        "tile_border": "#7a8ca5", "canvas_hint": "#888888",
    },
    "dark": {
        "bg": "#1b1f24", "surface": "#242a31", "surface_alt": "#2b323a", "border": "#38414b",
        "border_strong": "#4d5866", "text": "#e5e9ee", "muted": "#9aa5b2", "placeholder": "#6f7b88",
        "accent": "#5b9bff", "accent_hover": "#7aaeff", "accent_soft": "#22344f", "pressed": "#2b4166",
        "ok": "#4cc27a", "ok_soft": "#1d3528", "ok_border": "#2f6b45",
        "warn": "#f0a43a", "warn_soft": "#3b2e17",
        "bad": "#ff7070", "bad_soft": "#3e2326", "bad_border": "#7a3a3f", "danger_border": "#8a4046",
        "scroll": "#4a545f", "scroll_hover": "#606b78", "tooltip_bg": "#e5e9ee", "tooltip_text": "#1b1f24",
        "tile_border": "#6b7d96", "canvas_hint": "#9aa5b2",
    },
}
THEME_LABELS = {"light": "淺色主題", "dark": "深色主題"}
COLORS: dict[str, str] = dict(THEMES["light"])  # 目前主題的顏色（切換主題時就地更新）
current_theme = "light"


class ThemeColor:
    """隨目前主題變化的顏色；用在 f-string 與 QColor(str(...))。"""

    def __init__(self, key: str):
        self.key = key

    def __str__(self) -> str:
        return COLORS[self.key]

    def __format__(self, spec: str) -> str:
        return format(COLORS[self.key], spec)

    def __repr__(self) -> str:
        return f"ThemeColor({self.key!r})"


FONT_FAMILY = "Microsoft JhengHei UI" if sys.platform == "win32" else ""


# ---------------------------------------------------------------- 圖示
def _pen(color: str, width: float = 2.0) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def icon(kind: str, color: str | ThemeColor | None = None, size: int = 32) -> QIcon:
    """依目前主題繪製圖示；color 省略時使用主題文字色。"""
    return _icon(kind, str(color) if color is not None else COLORS["text"], size)


@lru_cache(maxsize=256)
def _icon(kind: str, color: str, size: int) -> QIcon:
    """繪製簡潔的線條圖示。kind：new、open、save、play、history、plus、dot-ok、dot-draft、dot-error、exam、arrow-down、arrow-up。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 32.0
    p.scale(s, s)
    p.setPen(_pen(color, 2.2))
    if kind == "new":
        path = QPainterPath()
        path.moveTo(9, 4); path.lineTo(19, 4); path.lineTo(25, 10); path.lineTo(25, 28); path.lineTo(9, 28)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(17, 14), QPointF(17, 22)); p.drawLine(QPointF(13, 18), QPointF(21, 18))
    elif kind == "open":
        path = QPainterPath()
        path.moveTo(4, 9); path.lineTo(12, 9); path.lineTo(14, 12); path.lineTo(26, 12); path.lineTo(26, 26)
        path.lineTo(4, 26); path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(4, 16), QPointF(26, 16))
    elif kind == "save":
        p.drawRoundedRect(QRectF(5, 5, 22, 22), 3, 3)
        p.drawRect(QRectF(10, 5, 11, 7))
        p.drawRoundedRect(QRectF(10, 17, 12, 10), 1.5, 1.5)
    elif kind == "play":
        path = QPainterPath()
        path.moveTo(10, 6); path.lineTo(26, 16); path.lineTo(10, 26); path.closeSubpath()
        p.setBrush(QColor(color))
        p.drawPath(path)
    elif kind == "history":
        p.drawEllipse(QRectF(5, 5, 22, 22))
        p.drawLine(QPointF(16, 10), QPointF(16, 16)); p.drawLine(QPointF(16, 16), QPointF(21, 19))
    elif kind == "plus":
        p.drawLine(QPointF(16, 7), QPointF(16, 25)); p.drawLine(QPointF(7, 16), QPointF(25, 16))
    elif kind == "exam":
        p.drawRoundedRect(QRectF(6, 4, 20, 24), 3, 3)
        for y in (11, 16, 21):
            p.drawLine(QPointF(11, y), QPointF(21, y))
    elif kind in ("arrow-down", "arrow-up"):
        p.setPen(_pen(color, 2.6))
        if kind == "arrow-down":
            p.drawPolyline([QPointF(9, 12), QPointF(16, 20), QPointF(23, 12)])
        else:
            p.drawPolyline([QPointF(9, 20), QPointF(16, 12), QPointF(23, 20)])
    elif kind == "moon":
        path = QPainterPath()
        path.addEllipse(QRectF(6, 6, 20, 20))
        cut = QPainterPath()
        cut.addEllipse(QRectF(12, 2, 20, 20))
        p.setBrush(QColor(color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path.subtracted(cut))
    elif kind == "sun":
        p.setBrush(QColor(color))
        p.drawEllipse(QRectF(11, 11, 10, 10))
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (0.7, 0.7), (-0.7, 0.7), (0.7, -0.7), (-0.7, -0.7)):
            p.drawLine(QPointF(16 + dx * 9, 16 + dy * 9), QPointF(16 + dx * 13, 16 + dy * 13))
    elif kind.startswith("dot-"):
        fill = {"dot-ok": COLORS["ok"], "dot-draft": COLORS["warn"], "dot-error": COLORS["bad"]}[kind]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(fill))
        p.drawEllipse(QRectF(10, 10, 12, 12))
    p.end()
    return QIcon(pixmap)


def _arrow_files() -> dict[str, str]:
    """樣式表的下拉、上下箭頭需要圖檔路徑；在暫存資料夾產生一次。"""
    folder = Path(tempfile.gettempdir()) / "oes-theme" / current_theme
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    for kind in ("arrow-down", "arrow-up"):
        for state, color in (("", COLORS["muted"]), ("-disabled", COLORS["border_strong"])):
            path = folder / f"{kind}{state}.png"
            icon(kind, color, 32).pixmap(32, 32).save(str(path), "PNG")
            paths[kind + state] = path.as_posix()
    return paths


# ---------------------------------------------------------------- 樣式表
def stylesheet() -> str:
    c = COLORS
    a = _arrow_files()
    return f"""
QWidget {{ color: {c['text']}; }}
QMainWindow, QDialog {{ background: {c['bg']}; }}
QToolTip {{ background: {c['tooltip_bg']}; color: {c['tooltip_text']}; border: none; padding: 5px 8px; border-radius: 4px; }}

/* 工具列與選單 */
QToolBar {{ background: {c['surface']}; border: none; border-bottom: 1px solid {c['border']}; padding: 4px 8px; spacing: 4px; }}
QToolBar::separator {{ background: {c['border']}; width: 1px; margin: 6px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 5px 9px; background: transparent; }}
QToolButton:hover {{ background: {c['accent_soft']}; border-color: {c['accent_soft']}; }}
QToolButton:pressed {{ background: {c['pressed']}; }}
QToolButton:disabled {{ color: {c['border_strong']}; }}
QMenuBar {{ background: {c['surface']}; border-bottom: 1px solid {c['border']}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 5px; background: transparent; }}
QMenuBar::item:selected {{ background: {c['accent_soft']}; }}
QMenu {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 6px 26px 6px 14px; border-radius: 5px; }}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QMenu::item:disabled {{ color: {c['border_strong']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}
QStatusBar {{ background: {c['surface']}; border-top: 1px solid {c['border']}; color: {c['muted']}; }}

/* 按鈕 */
QPushButton {{ background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 6px;
              padding: 6px 14px; min-height: 18px; }}
QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}
QPushButton:pressed {{ background: {c['accent_soft']}; }}
QPushButton:disabled {{ color: {c['border_strong']}; border-color: {c['border']}; background: {c['surface_alt']}; }}
QPushButton:flat {{ border: none; background: transparent; padding: 4px 6px; }}
QPushButton[role="primary"] {{ background: {c['accent']}; border-color: {c['accent']}; color: white; font-weight: bold; }}
QPushButton[role="primary"]:hover {{ background: {c['accent_hover']}; border-color: {c['accent_hover']}; color: white; }}
QPushButton[role="danger"] {{ color: {c['bad']}; border-color: {c['danger_border']}; }}
QPushButton[role="danger"]:hover {{ background: {c['bad_soft']}; border-color: {c['bad']}; color: {c['bad']}; }}

/* 輸入元件 */
QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {c['surface']}; border: 1px solid {c['border_strong']}; border-radius: 6px; padding: 4px 6px;
    selection-background-color: {c['accent']}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border: 1px solid {c['accent']}; }}
QLineEdit:disabled, QComboBox:disabled {{ background: {c['surface_alt']}; color: {c['muted']}; }}
QComboBox {{ padding-right: 24px; min-height: 20px; }}
QComboBox::drop-down {{ border: none; width: 22px; subcontrol-origin: padding; subcontrol-position: center right; }}
QComboBox::down-arrow {{ image: url("{a['arrow-down']}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{a['arrow-down-disabled']}"); }}
QComboBox QAbstractItemView {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 6px;
    selection-background-color: {c['accent_soft']}; selection-color: {c['accent']}; padding: 4px; outline: none; }}
QSpinBox, QDoubleSpinBox {{ padding-right: 20px; min-height: 20px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px;
    border: none; background: transparent; }}
QSpinBox::down-button, QDoubleSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right;
    width: 18px; border: none; background: transparent; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url("{a['arrow-up']}"); width: 10px; height: 10px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url("{a['arrow-down']}"); width: 10px; height: 10px; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}

/* 群組卡片與分頁 */
QGroupBox {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px;
            margin-top: 14px; padding: 14px 12px 10px 12px; font-weight: bold; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 12px; padding: 0 6px;
                   color: {c['text']}; background: transparent; }}
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton, QGroupBox QPushButton {{ font-weight: normal; }}
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 10px; background: {c['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; margin-right: 2px; border: none;
               border-bottom: 2px solid transparent; color: {c['muted']}; }}
QTabBar::tab:selected {{ color: {c['accent']}; border-bottom: 2px solid {c['accent']}; font-weight: bold; }}
QTabBar::tab:hover:!selected {{ color: {c['text']}; }}

/* 清單與表格 */
QListWidget, QTableWidget, QTreeWidget {{ background: {c['surface']}; border: 1px solid {c['border']};
    border-radius: 8px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; margin: 1px 3px; }}
QListWidget::item:hover {{ background: {c['surface_alt']}; }}
QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['accent']}; }}
QListWidget#questionList::item {{ padding: 8px 10px; }}
QTableWidget {{ gridline-color: {c['border']}; selection-background-color: {c['accent_soft']}; selection-color: {c['text']}; }}
QHeaderView::section {{ background: {c['surface_alt']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 6px 8px; font-weight: bold; color: {c['muted']}; }}

/* 捲軸 */
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {c['scroll']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['scroll_hover']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['scroll']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: transparent; width: 6px; }}

/* 進度列 */
QProgressBar {{ background: {c['border']}; border: none; border-radius: 4px; height: 8px; text-align: center;
               color: transparent; max-height: 8px; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}

/* 自訂區塊 */
QWidget#questionCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#card {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QFrame#seriesNote {{ background: {c['accent_soft']}; border-left: 4px solid {c['accent']}; border-radius: 6px; }}
QFrame#examHeader {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QLabel#pill {{ background: {c['accent_soft']}; color: {c['accent']}; border-radius: 10px; padding: 3px 10px;
              font-weight: bold; }}
QLabel#pillWarn {{ background: {c['bad_soft']}; color: {c['bad']}; border-radius: 10px; padding: 3px 10px;
                  font-weight: bold; }}
QLabel#sectionTitle {{ font-weight: bold; font-size: 11pt; }}
QLabel#pageTitle {{ font-weight: bold; font-size: 15pt; }}
QLabel#hint {{ color: {c['muted']}; }}
QFrame#scoreCard {{ border-radius: 12px; border: 1px solid {c['border']}; background: {c['surface']}; }}
QFrame#scoreCard[result="pass"] {{ background: {c['ok_soft']}; border-color: {c['ok_border']}; }}
QFrame#scoreCard[result="fail"] {{ background: {c['bad_soft']}; border-color: {c['bad_border']}; }}
"""


def apply_theme(app: QApplication, name: str = "light") -> str:
    """套用主題（light／dark），回傳實際套用的名稱。可在程式執行中重複呼叫切換。"""
    global current_theme
    name = name if name in THEMES else "light"
    current_theme = name
    COLORS.clear()
    COLORS.update(THEMES[name])
    app.setStyle("Fusion")
    palette = QPalette()
    c = COLORS
    for role, color in ((QPalette.ColorRole.Window, c["bg"]), (QPalette.ColorRole.Base, c["surface"]),
                        (QPalette.ColorRole.AlternateBase, c["surface_alt"]), (QPalette.ColorRole.Text, c["text"]),
                        (QPalette.ColorRole.WindowText, c["text"]), (QPalette.ColorRole.Button, c["surface"]),
                        (QPalette.ColorRole.ButtonText, c["text"]), (QPalette.ColorRole.Highlight, c["accent"]),
                        (QPalette.ColorRole.HighlightedText, "#ffffff"), (QPalette.ColorRole.ToolTipBase, c["tooltip_bg"]),
                        (QPalette.ColorRole.ToolTipText, c["tooltip_text"]), (QPalette.ColorRole.Link, c["accent"]),
                        (QPalette.ColorRole.PlaceholderText, c["placeholder"]), (QPalette.ColorRole.Light, c["surface_alt"]),
                        (QPalette.ColorRole.Mid, c["border"]), (QPalette.ColorRole.Dark, c["border_strong"])):
        palette.setColor(role, QColor(color))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(c["border_strong"]))
    app.setPalette(palette)
    if FONT_FAMILY:
        app.setFont(QFont(FONT_FAMILY, 10))
    app.setStyleSheet(stylesheet())
    return name


def set_role(button, role: str) -> None:
    """設定按鈕外觀角色：primary（主要動作）、danger（刪除、結束等）。"""
    button.setProperty("role", role)
    button.style().unpolish(button)
    button.style().polish(button)
