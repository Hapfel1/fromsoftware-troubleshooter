"""
Build script for Windows using cx_Freeze.

Usage:
    uv run python build_windows_cx.py build
"""

import sys
import warnings
from pathlib import Path

from cx_Freeze import Executable, setup


# Convert PNG to ICO if needed
def ensure_ico(png_path: Path) -> Path:
    ico_path = png_path.with_suffix(".ico")
    if not ico_path.exists():
        try:
            from PIL import Image

            img = Image.open(png_path)
            img.save(ico_path, format="ICO", sizes=[(256, 256)])
            print(f"Converted {png_path} -> {ico_path}")
        except Exception as e:
            print(f"Warning: Could not convert icon: {e}")
            return png_path
    return ico_path


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
    # Exclude unused stdlib modules
    "excludes": [
        "unittest",
        "pydoc",
        "test",
        "asyncio",
        "multiprocessing",
        "email",
        "html",
        "http.server",
        "xmlrpc",
        "distutils",
        "lib2to3",
        "numpy",
        "pandas",
        "matplotlib",
    ],
    # Exclude tcl/tk bloat directories
    "bin_path_excludes": [
        "tcl/tzdata",
        "tcl8/tzdata",
        "tcl8.6/tzdata",
        "tk/demos",
        "tk8.6/demos",
    ],
    "build_exe": f"dist/windows-{VERSION}/{APP_NAME}",
    "optimize": 2,
}

base = "gui"

icon_path = ensure_ico(Path("icon.png"))

executables = [
    Executable(
        "main.py",
        base=base,
        target_name=APP_NAME,
        icon=str(icon_path),
    )
]

setup(
    name=APP_NAME,
    version=VERSION,
    description="Standalone troubleshooter for FromSoftware games",
    options={"build_exe": build_exe_options},
    executables=executables,
)
