# -*- mode: python ; coding: utf-8 -*-
# Windows — onedir
# onefile is avoided on Windows: the self-extracting stub triggers AV heuristics.
# Ship the dist/fromsoftware-troubleshooter/ folder or wrap it in an NSIS/Inno installer.

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
        (str(CTK_PATH / 'assets'), 'customtkinter/assets'),
    ],
    hiddenimports=[
        'customtkinter',
        'PIL._tkinter_finder',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'xmlrpc', 'xml',
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
    [],
    exclude_binaries=True,
    name='FromSoftware Troubleshooter',
    debug=False,
    strip=False,       # don't strip on Windows — breaks some DLLs
    upx=False,         # UPX on Windows EXEs is a major AV trigger
    console=False,
    bootloader_ignore_signals=False,
    target_arch=None,
    uac_admin=False,
    icon=None,         # replace with icon='assets/icon.ico' if you have one
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='FromSoftware Troubleshooter',
)
