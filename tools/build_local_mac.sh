#!/usr/bin/env bash
set -e

echo "=== MediaFlow Local macOS App & DMG Builder ==="

# 1. Ensure pyinstaller is installed in the virtual environment
echo "[1/4] Checking and installing PyInstaller..."
uv pip install pyinstaller

# 2. Clean previous build artifacts
echo "[2/4] Cleaning previous build artifacts..."
rm -rf build dist

# 3. Run PyInstaller
echo "[3/4] Packaging application with PyInstaller..."
uv run pyinstaller --noconfirm mediaflow.spec

# 4. Generate .dmg installer
echo "[4/4] Creating macOS .dmg disk image..."
ARCH=$(uname -m)
DMG_NAME="MediaFlow-macOS-${ARCH}.dmg"

hdiutil create -volname "MediaFlow" -srcfolder "dist/MediaFlow.app" -ov -format UDZO "dist/${DMG_NAME}"

echo ""
echo "=== BUILD SUCCESSFUL! ==="
echo "Application bundle: dist/MediaFlow.app"
echo "Installer image:    dist/${DMG_NAME}"
echo ""
echo "You can double click dist/${DMG_NAME} to mount and drag MediaFlow to Applications."
