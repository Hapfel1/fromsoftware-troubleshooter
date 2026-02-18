#!/bin/sh
set -e
# Build script for fromsoftware-troubleshooter

VERSION=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)

if [ "$(uname)" = "Linux" ]; then
    echo "Building Linux binary..."
    python3 -m PyInstaller --clean --noconfirm fromsoftware_troubleshooter_linux.spec
    
    if [ "$1" = "--appimage" ]; then
        echo "Creating AppImage..."
        ./build_appimage.sh
    else
        echo "Done: dist/fromsoftware-troubleshooter"
        echo "Run with --appimage to package as AppImage"
    fi
else
    echo "Building Windows binary..."
    python -m PyInstaller --clean --noconfirm fromsoftware_troubleshooter_windows.spec
    echo "Done: dist/FromSoftware Troubleshooter.exe"
fi