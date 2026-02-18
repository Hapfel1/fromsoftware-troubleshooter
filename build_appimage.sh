#!/bin/sh
set -e
# Package fromsoftware-troubleshooter as AppImage

VERSION=$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)
BINARY="dist/fromsoftware-troubleshooter"
APPDIR="build/AppDir"
APP_NAME="FromSoftware-Troubleshooter"

if [ ! -f "$BINARY" ]; then
    echo "Binary not found: $BINARY"
    echo "Run build.sh first"
    exit 1
fi

# Download appimagetool if needed
if [ ! -f appimagetool-x86_64.AppImage ]; then
    echo "Downloading appimagetool..."
    curl -fL "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" -o appimagetool-x86_64.AppImage
    chmod +x appimagetool-x86_64.AppImage
fi

echo "Creating AppDir..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy binary
cp "$BINARY" "$APPDIR/usr/bin/"
chmod +x "$APPDIR/usr/bin/fromsoftware-troubleshooter"

# Create .desktop file
cat > "$APPDIR/usr/share/applications/fromsoftware-troubleshooter.desktop" << 'DESKTOP'
[Desktop Entry]
Name=FromSoftware Troubleshooter
Exec=fromsoftware-troubleshooter
Icon=fromsoftware-troubleshooter
Type=Application
Categories=Utility;
DESKTOP

# Copy icon
if [ -f icon.png ]; then
    cp icon.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/fromsoftware-troubleshooter.png"
else
    # Create minimal placeholder
    echo "Warning: icon.png not found, creating placeholder"
    python3 -c "from PIL import Image; img = Image.new('RGB', (256, 256), '#1e1e2e'); img.save('$APPDIR/usr/share/icons/hicolor/256x256/apps/fromsoftware-troubleshooter.png')"
fi

# Create AppRun
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/sh
exec "${APPDIR}/usr/bin/fromsoftware-troubleshooter" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# Symlinks required by appimagetool
ln -s usr/share/applications/fromsoftware-troubleshooter.desktop "$APPDIR/"
ln -s usr/share/icons/hicolor/256x256/apps/fromsoftware-troubleshooter.png "$APPDIR/"

# Build AppImage
echo "Building AppImage..."
OUTPUT="dist/${APP_NAME}-${VERSION}-x86_64.AppImage"
ARCH=x86_64 ./appimagetool-x86_64.AppImage --appimage-extract-and-run "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

echo "AppImage created: $OUTPUT"