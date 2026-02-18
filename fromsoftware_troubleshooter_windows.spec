# -*- mode: python ; coding: utf-8 -*-
# Windows — onefile

import os
import sys
from pathlib import Path

import customtkinter
CTK_PATH = Path(customtkinter.__file__).parent

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('game_file_sizes.json', '.'),
        ('icon.png', '.'),
        (str(CTK_PATH / 'assets'), 'customtkinter/assets'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'html', 'xmlrpc',
        'unittest', 'doctest', 'pdb', 'pydoc',
        'lib2to3', 'tkinter.test', 'test',
        'multiprocessing', 'concurrent',
        'asyncio', 'sqlite3',
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
    name='FromSoftware Troubleshooter',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    bootloader_ignore_signals=False,
    target_arch=None,
    uac_admin=False,
    icon='icon.png',
)
