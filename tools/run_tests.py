"""執行全部測試，並以測試結果作為結束代碼。

用法（於專案根目錄）：python tools/run_tests.py [-v]

測試結束後直接結束程序，略過 Python 與 Qt 的關閉清理：在 Windows 的無視窗（offscreen）模式下，
卸載 Qt 程式庫時可能發生存取違規，讓測試全部通過卻回傳非 0 的結束代碼。
Windows 上以 TerminateProcess 結束（不執行 DLL 卸載），其他系統用 os._exit。
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


def hard_exit(code: int) -> None:
    sys.stdout.flush()
    sys.stderr.flush()
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE      # 64 位元程式的 handle 不能當成 int 傳遞
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)


if __name__ == "__main__":
    hard_exit(main())
