# Third-Party Notices / 第三方元件授權

Open Exam Simulator is licensed under the GNU General Public License v3.0 or later (see [LICENSE](LICENSE)).
The Windows package (`OpenExamSimulator-win64.zip`) also contains the following third-party components.

Open Exam Simulator 依 GPL v3（或更新版本）授權。Windows 打包版本另外包含下列第三方元件。

| Component / 元件 | License / 授權 | Source / 來源 |
|---|---|---|
| Qt 6 (Qt Base, Qt Image Formats and related modules) | GNU LGPL v3 | <https://www.qt.io/> · <https://code.qt.io/> |
| PySide6 / Shiboken6 (Qt for Python) | GNU LGPL v3 | <https://wiki.qt.io/Qt_for_Python> · <https://code.qt.io/cgit/pyside/pyside-setup.git/> |
| Python runtime | Python Software Foundation License | <https://www.python.org/> |
| PyInstaller bootloader | GPL v2 with a special exception that allows distribution of bundled apps | <https://pyinstaller.org/> |
| libwebp (via the Qt WebP image plugin) | BSD 3-Clause | <https://chromium.googlesource.com/webm/libwebp> |

## Qt and PySide6 (LGPL v3)

Qt and PySide6 are used under the GNU Lesser General Public License version 3. The Windows package is built in
PyInstaller's "one-folder" mode, so the Qt and PySide6 libraries are shipped as separate DLL / `.pyd` files in the
`_internal` folder. You may replace them with your own compatible builds. The source code of Qt and PySide6 is
available from the links above. The full LGPL v3 text is available at <https://www.gnu.org/licenses/lgpl-3.0.html>.

Qt 與 PySide6 依 LGPL v3 授權使用。打包版本採 PyInstaller「one-folder」模式，Qt 與 PySide6 程式庫以獨立的
DLL／`.pyd` 檔放在 `_internal` 資料夾，使用者可以自行替換成相容的版本。

## Fonts

The app uses fonts installed on your system (for example Microsoft JhengHei, Consolas). No fonts are bundled.
本程式使用系統已安裝的字型，不附帶任何字型檔。
