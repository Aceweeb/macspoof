#!/usr/bin/env bash
# Install the desktop entry and icon for the macspoof GUI.
#
#   ./install-desktop.sh
#
# Installs into the user's home directory, no root required.

set -euo pipefail

PREFIX="${1:-$HOME/.local}"
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="com.github.macspoof.MacSpoof"

DESKTOP_DIR="$PREFIX/share/applications"
ICON_DIR="$PREFIX/share/icons/hicolor/scalable/apps"

mkdir -p "$DESKTOP_DIR" "$ICON_DIR"

# The desktop entry must point at the installed console script.
sed "s|^Exec=macspoof-gui|Exec=$PREFIX/bin/macspoof-gui|" \
    "$SOURCE_DIR/data/$APP_ID.desktop" > "$DESKTOP_DIR/$APP_ID.desktop"

cp "$SOURCE_DIR/data/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"
chmod +x "$DESKTOP_DIR/$APP_ID.desktop"

# Point the entry at the icon we just installed.
sed -i "s|^Icon=.*|Icon=$APP_ID|" "$DESKTOP_DIR/$APP_ID.desktop"

# Refresh the desktop database if available.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo "Installed desktop entry: $DESKTOP_DIR/$APP_ID.desktop"
echo "Installed icon:           $ICON_DIR/$APP_ID.svg"
echo
echo "The app now appears in your application menu as 'MAC Spoof'."
