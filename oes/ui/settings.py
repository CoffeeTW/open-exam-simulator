"""使用者偏好（例如主題），存成作答紀錄同一個資料夾的 settings.json。"""
from __future__ import annotations

import json
from pathlib import Path

from ..storage.history import default_history_path

SETTINGS_FILE = "settings.json"


def settings_path() -> Path:
    return default_history_path().parent / SETTINGS_FILE


def load(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or settings_path()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(values: dict, path: Path | None = None) -> bool:
    """合併寫入設定；寫不進去時回傳 False（不影響程式使用）。"""
    target = path or settings_path()
    data = load(target)
    data.update(values)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False
