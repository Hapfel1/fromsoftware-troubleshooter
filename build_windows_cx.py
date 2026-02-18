"""
Build script for Windows using cx_Freeze.

Usage:
    uv run python build_windows_cx.py
"""

import sys
import warnings
from pathlib import Path

from cx_Freeze import Executable, setup
from cx_Freeze.finder import ModuleFinder

if sys.platform != "win32":
    sys.exit("This script must be run on Windows.")

VERSION = "1.0.0"
APP_NAME = "FromSoftware Troubleshooter"

warnings.filterwarnings("ignore", category=SyntaxWarning)

# Files to bundle
include_files = [
    ("game_file_sizes.json", "game_file_sizes.json"),
    ("icon.png", "icon.png"),
]

build_exe_options = {
    "packages": ["fromsoftware_troubleshooter"],
    "includes": ["pyperclip"],
    "include_files": include_files,
    # Compress everything except the main package and customtkinter into library.zip
    "zip_exclude_packages": ["fromsoftware_troubleshooter", "customtkinter"],
    "zip_include_packages": ["*"],
    # Exclude unused stdlib
    "excludes": ["unittest", "pydoc", "test", "asyncio", "multiprocessing"],
    "build_exe": f"dist/windows-{VERSION}/{APP_NAME}",
    "optimize": 2,
}

base = "gui"

executables = [
    Executable(
        "main.py",
        base=base,
        target_name=APP_NAME,
        icon="icon.png",
    )
]

# Monkey patch to exclude tcl/tk bloat
original_include_files = ModuleFinder.include_files


def patched_include_files(self, source_path, target_path, copy_dependent_files=True):
    source_path = Path(source_path)
    target_path = Path(target_path)

    if str(target_path).startswith("lib") and source_path.is_dir():
        if "tcl" in source_path.name or "tk" in source_path.name:
            for file_path in source_path.rglob("*"):
                if file_path.is_dir():
                    continue
                rel_path = file_path.relative_to(source_path)
                # Skip tzdata and demos
                if "tzdata" in rel_path.parts or "demos" in rel_path.parts:
                    continue
                final_target = target_path / rel_path
                original_include_files(
                    self, file_path, final_target, copy_dependent_files
                )
            return

    original_include_files(self, source_path, target_path, copy_dependent_files)


ModuleFinder.include_files = patched_include_files

setup(
    name=APP_NAME,
    version=VERSION,
    description="Standalone troubleshooter for FromSoftware games",
    options={"build_exe": build_exe_options},
    executables=executables,
)
