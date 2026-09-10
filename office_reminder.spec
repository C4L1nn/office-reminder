# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for Office Reminder (onedir, windowed).

Only read-only assets are bundled: migrations, the GİB seed calendar and the
application icon. The runtime database, logs, backups and downloaded official
snapshots live under %LOCALAPPDATA%\\OfficeReminder and are never packaged, so a
build made on a developer machine carries none of that machine's data.
"""

from pathlib import Path

project_root = Path(SPECPATH)

# Everything the app must be able to read at runtime, as (source, dest-in-bundle).
# Qt's own translation of standard dialog buttons ("Yes" -> "Evet").
from PySide6.QtCore import QLibraryInfo as _QtLibInfo

_qt_translations = Path(_QtLibInfo.path(_QtLibInfo.LibraryPath.TranslationsPath))
_qtbase_tr = _qt_translations / "qtbase_tr.qm"

datas = [
    (str(project_root / "database" / "migrations"), "database/migrations"),
    (str(project_root / "resources" / "seed"), "resources/seed"),
]
icon_path = project_root / "resources" / "icon.ico"
if icon_path.exists():
    datas.append((str(icon_path), "resources"))
if _qtbase_tr.exists():
    datas.append((str(_qtbase_tr), "PySide6/translations"))

a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "PySide6.QtSvg",   # themed icons are rendered from SVG at runtime
        "PySide6.QtPdf",   # SGK announcement attachments are read as PDF text
        "openpyxl",        # .xlsx export
        "openpyxl.styles",
        "openpyxl.utils",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Qt modules the app never touches; excluding them keeps the bundle lean and
    # avoids shipping a web engine with a local desktop tool.
    excludes=[
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick3D",
        "PySide6.QtMultimedia",
        "PySide6.Qt3DCore",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtBluetooth",
        "PySide6.QtSql",
        "PySide6.QtTest",
        # Saf QtWidgets uygulaması: QML çalışma zamanı hiç kullanılmıyor.
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuickWidgets",
        "PySide6.QtQuickControls2",
        "tkinter",
        "pytest",
        "unittest",
        # Aşağıdakileri uygulama hiçbir yerde import etmiyor. Temiz bir sanal
        # ortamda zaten yoklar; liste, geliştirici makinesinin genel Python
        # ortamında derleme yapıldığında paketin 60 MB fazlalık taşımasını
        # önler. 1.0.0 paketi tam olarak böyle şişmişti: numpy + OpenBLAS,
        # PIL'in AVIF kodeki ve pywin32'nin MFC katmanı boşuna geliyordu.
        "numpy",
        "scipy",
        "pandas",
        "matplotlib",
        "PIL",
        "cv2",
        "torch",
        "sklearn",
        "skimage",
        "customtkinter",
        "win32com",
        "Pythonwin",
        "IPython",
    ],
    noarchive=False,
)

# Qt'nin ekran klavyesi eklentisi tek başına 13 MB'lık bir QML çalışma zamanı
# getiriyor: Qt6VirtualKeyboard -> Qt6Quick -> Qt6Qml + QmlMeta/QmlModels/
# QmlWorkerScript. `excludes` bunu durduramaz, çünkü zincir Python importu
# değil ikili bağımlılık; PE import tablosundan doğrulandı. Uygulama saf
# QtWidgets ve gerçek klavyesi olan masaüstü makinelerinde çalışıyor; Qt'nin
# sanal klavyesi yüklenmediğinde Windows kendi dokunmatik klavyesini sunar.
_DROP_BINARIES = {
    "qt6virtualkeyboard.dll",
    "qt6quick.dll",
    "qt6qml.dll",
    "qt6qmlmeta.dll",
    "qt6qmlmodels.dll",
    "qt6qmlworkerscript.dll",
    "qtvirtualkeyboardplugin.dll",
}
a.binaries = [b for b in a.binaries if Path(b[0]).name.lower() not in _DROP_BINARIES]

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OfficeReminder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX-packed Qt DLLs trip antivirus heuristics on office machines
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OfficeReminder",
)
