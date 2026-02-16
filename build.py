"""
Build script for FromSoftware Troubleshooter.

Linux:  python build.py            -> dist/fromsoftware-troubleshooter (onefile)
        python build.py --appimage -> dist/FromSoftware-Troubleshooter.AppImage
Windows: python build.py           -> dist/FromSoftware Troubleshooter/ (onedir)

Requires: pyinstaller, appimagetool (Linux AppImage only, auto-downloaded if missing)
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

DIST = Path("dist")
BUILD = Path("build")
APP_NAME = "FromSoftware Troubleshooter"
EXE_NAME = "fromsoftware-troubleshooter"
VERSION = "1.0.0"


def run(cmd: list[str]) -> None:
    print(f"+ {' '.join(str(c) for c in cmd)}")
    subprocess.run(cmd, check=True)


def build_linux(appimage: bool = False) -> None:
    run([
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "fromsoftware_troubleshooter_linux.spec",
    ])

    binary = DIST / EXE_NAME
    if not binary.exists():
        sys.exit(f"Build failed: {binary} not found")

    print(f"\nLinux binary: {binary} ({binary.stat().st_size // 1024} KB)")

    if appimage:
        _make_appimage(binary)


def _make_appimage(binary: Path) -> None:
    appdir = DIST / "AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)

    # AppDir structure
    (appdir / "usr" / "bin").mkdir(parents=True)
    (appdir / "usr" / "share" / "applications").mkdir(parents=True)
    (appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps").mkdir(parents=True)

    # Copy binary
    dest = appdir / "usr" / "bin" / EXE_NAME
    shutil.copy2(binary, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IEXEC)

    # AppRun
    apprun = appdir / "AppRun"
    apprun.write_text(f'#!/bin/sh\nexec "${{APPDIR}}/usr/bin/{EXE_NAME}" "$@"\n')
    apprun.chmod(0o755)

    # .desktop
    desktop = appdir / "usr" / "share" / "applications" / f"{EXE_NAME}.desktop"
    desktop.write_text(
        f"[Desktop Entry]\n"
        f"Name={APP_NAME}\n"
        f"Exec={EXE_NAME}\n"
        f"Icon={EXE_NAME}\n"
        f"Type=Application\n"
        f"Categories=Utility;\n"
    )
    # Also at AppDir root (required by appimagetool)
    shutil.copy2(desktop, appdir / f"{EXE_NAME}.desktop")

    # Placeholder icon (appimagetool requires one)
    icon_src = Path("assets") / "icon.png"
    icon_dst = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps" / f"{EXE_NAME}.png"
    if icon_src.exists():
        shutil.copy2(icon_src, icon_dst)
        shutil.copy2(icon_src, appdir / f"{EXE_NAME}.png")
    else:
        # Minimal 1x1 PNG so appimagetool doesn't abort
        _write_minimal_png(icon_dst)
        shutil.copy2(icon_dst, appdir / f"{EXE_NAME}.png")

    # Get appimagetool
    tool = _get_appimagetool()

    out = DIST / f"{APP_NAME.replace(' ', '-')}-{VERSION}-x86_64.AppImage"
    env = os.environ.copy()
    env["ARCH"] = "x86_64"
    run([str(tool), str(appdir), str(out)])
    out.chmod(out.stat().st_mode | stat.S_IEXEC)
    print(f"\nAppImage: {out} ({out.stat().st_size // (1024*1024)} MB)")


def _get_appimagetool() -> Path:
    tool = Path("appimagetool-x86_64.AppImage").resolve()
    if tool.exists():
        return tool
    url = "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    print(f"Downloading appimagetool from {url}")
    urllib.request.urlretrieve(url, tool)
    # Ensure file is fully written to disk before chmod/return
    with open(tool, "ab") as f:
        f.flush()
        os.fsync(f.fileno())
    tool.chmod(0o755)
    return tool


def _write_minimal_png(path: Path) -> None:
    # Minimal valid 1x1 transparent PNG
    import base64
    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )
    path.write_bytes(data)


def build_windows() -> None:
    run([
        sys.executable, "-m", "PyInstaller",
        "--clean", "--noconfirm",
        "fromsoftware_troubleshooter_windows.spec",
    ])

    outdir = DIST / APP_NAME
    if not outdir.exists():
        sys.exit(f"Build failed: {outdir} not found")

    size_mb = sum(f.stat().st_size for f in outdir.rglob("*") if f.is_file()) // (1024 * 1024)
    print(f"\nWindows build: {outdir}/ ({size_mb} MB)")
    print("Distribute the entire folder or wrap with Inno Setup / NSIS.")


def main() -> None:
    appimage = "--appimage" in sys.argv
    system = platform.system()

    if system == "Linux":
        build_linux(appimage=appimage)
    elif system == "Windows":
        if appimage:
            print("--appimage is Linux only, building Windows onedir instead")
        build_windows()
    else:
        sys.exit(f"Unsupported platform: {system}")


if __name__ == "__main__":
    main()