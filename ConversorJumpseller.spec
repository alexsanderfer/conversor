# -*- mode: python ; coding: utf-8 -*-

import os
import platform

# Nome do executavel: ConversorJumpseller-vX.Y.Z-Arquitetura.exe
# Ex.: ConversorJumpseller-v0.3.10-x64.exe
# __file__ nao esta definido em todos os contextos do PyInstaller, por isso
# usamos o diretorio de trabalho (onde o spec e executado).
_VER = open('VERSION.txt').read().strip()
_ARCH = 'x64' if platform.architecture()[0] == '64bit' else 'x86'
EXE_NAME = f'ConversorJumpseller-{_VER}-{_ARCH}'


a = Analysis(
    ['csv_converter_gui.py'],
    pathex=[],
    binaries=[],
    datas=[('VERSION.txt', '.')],
    hiddenimports=['tkinterdnd2', 'openpyxl', 'stripe_integration', 'updater'],
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
    version='version_info.txt',
)
