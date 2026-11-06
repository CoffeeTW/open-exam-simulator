"""執行全部測試，並以測試結果作為結束代碼。

用法（於專案根目錄）：python tools/run_tests.py [-v]

測試結束後直接以 os._exit 結束，略過 Python 關閉時對 Qt 物件的清理：在 Windows 的無視窗（offscreen）
模式下，這個清理偶爾會在測試全部通過之後才出錯，讓結束代碼變成非 0。
"""
import faulthandler
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    faulthandler.enable()
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    verbosity = 2 if "-v" in sys.argv[1:] else 1
    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
