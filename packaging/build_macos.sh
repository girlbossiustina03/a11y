#!/usr/bin/env bash
# Build A11y.app and A11y-macOS.dmg on a Mac (Apple Silicon or Intel builds for its own arch).
# Optional: MACOS_SIGN_IDENTITY="Developer ID Application: …" for a real signature;
# otherwise the app is ad-hoc signed (first launch: right-click → Open).
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"

"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r requirements.txt -r packaging/requirements-build.txt
"$PYTHON" -m pip install -r requirements-voice.txt || echo "Voice packages unavailable; building without them."

"$PYTHON" packaging/make_icons.py

# Native helpers are compiled here so users never need Xcode Command Line Tools.
mkdir -p build/native-bin
xcrun swiftc -O -module-cache-path build/swift-cache native/DesktopBridge.swift -o build/native-bin/desktop-bridge
xcrun swiftc -parse-as-library -O -module-cache-path build/swift-cache native/ScreenBridge.swift -o build/native-bin/screen-bridge

"$PYTHON" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/pyinstaller packaging/a11y.spec

IDENTITY="${MACOS_SIGN_IDENTITY:--}"
if [ "$IDENTITY" = "-" ]; then
  codesign --force --deep --sign - dist/A11y.app
elif [ -n "${MACOS_SELF_SIGNED:-}" ]; then
  # Stable private certificate (not Apple-issued): same identity every build, no notarization.
  codesign --force --deep --sign "$IDENTITY" dist/A11y.app
else
  codesign --force --deep --options runtime --timestamp --entitlements packaging/entitlements.plist --sign "$IDENTITY" dist/A11y.app
fi
codesign --verify --deep --strict dist/A11y.app

STAGE="$(mktemp -d)"
cp -R dist/A11y.app "$STAGE/"
ln -s /Applications "$STAGE/Applications"
rm -f dist/A11y-macOS.dmg
hdiutil create -volname "A11y" -srcfolder "$STAGE" -ov -format UDZO dist/A11y-macOS.dmg
rm -rf "$STAGE"

if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_TEAM_ID:-}" ] && [ -n "${APPLE_APP_PASSWORD:-}" ] && [ "$IDENTITY" != "-" ]; then
  xcrun notarytool submit dist/A11y-macOS.dmg --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" \
      --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple dist/A11y-macOS.dmg
fi
echo "Built dist/A11y.app and dist/A11y-macOS.dmg"
