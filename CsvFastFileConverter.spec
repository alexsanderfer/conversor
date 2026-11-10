# -*- mode: python ; coding: utf-8 -*-

import os
import platform

# Nome do executavel: CsvFast-FileConverter-vX.Y.Z-Arquitetura.exe
# Ex.: CsvFast-FileConverter-v0.3.57-x64.exe
# __file__ nao esta definido em todos os contextos do PyInstaller, por isso
# usamos o diretorio de trabalho (onde o spec e executado).
_VER = open('VERSION.txt').read().strip()
_ARCH = 'x64' if platform.architecture()[0] == '64bit' else 'x86'
EXE_NAME = f'CsvFast-FileConverter-{_VER}-{_ARCH}'


datas = [('VERSION.txt', '.')]
if os.path.exists('assets'):
    datas.append(('assets', 'assets'))
if os.path.exists('field_mapping_config.json'):
    datas.append(('field_mapping_config.json', '.'))

a = Analysis(
    ['gui/csv_converter_gui.py'],
    pathex=['gui', 'core'],
    binaries=[],
    datas=datas,
    hiddenimports=['tkinterdnd2', 'openpyxl', 'core.stripe_integration', 'core.updater', 'PIL', 'PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version='version_info.txt',
)
