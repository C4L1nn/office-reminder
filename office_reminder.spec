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
        "tkinter",
        "pytest",
        "unittest",
    ],
    noarchive=False,
)

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
