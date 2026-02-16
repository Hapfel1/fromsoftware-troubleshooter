# -*- mode: python ; coding: utf-8 -*-
# Linux — onefile, used as AppImage payload

import os
import sys
from pathlib import Path

# Locate customtkinter assets
import customtkinter
CTK_PATH = Path(customtkinter.__file__).parent

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('game_file_sizes.json', '.'),
        (str(CTK_PATH / 'assets'), 'customtkinter/assets'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'html', 'xmlrpc', 'xml',
        'unittest', 'doctest', 'pdb', 'pydoc',
        'lib2to3', 'tkinter.test', 'test',
        'multiprocessing', 'concurrent',
        'asyncio', 'ssl', 'sqlite3',
        'numpy', 'pandas', 'matplotlib',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='fromsoftware-troubleshooter',
    debug=False,
    strip=True,
    upx=True,
    upx_exclude=['vcruntime140.dll', 'python*.dll'],
    console=False,
    bootloader_ignore_signals=False,
    runtime_tmpdir=None,
    target_arch=None,
)
