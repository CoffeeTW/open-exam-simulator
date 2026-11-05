"""PyInstaller 打包用的進入點（等同 python -m oes）。"""
from oes.ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
