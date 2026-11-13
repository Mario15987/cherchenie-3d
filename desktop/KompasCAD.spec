# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_submodules

datas = [('assets/icon.ico', 'assets'), ('assets/icon.png', 'assets')]
hiddenimports = ['OpenGL.platform.win32']
datas += collect_data_files('pyqtgraph')
hiddenimports += collect_submodules('OpenGL.arrays')
hiddenimports += collect_submodules('pyqtgraph.opengl')
hiddenimports += collect_submodules('anthropic')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtPdf'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='KompasCAD',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KompasCAD',
)

# Копия под новым именем программы: та же папка _internal и тот же config.json рядом.
import os, shutil  # noqa: E401
shutil.copy2(os.path.join(DISTPATH, 'KompasCAD', 'KompasCAD.exe'), os.path.join(DISTPATH, 'KompasCAD', 'Черчение 3D.exe'))
