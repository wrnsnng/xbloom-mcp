#!/bin/zsh
# Builds ~/Applications/xBloom Bridge.app: a background app (no Dock icon) that holds
# the macOS Bluetooth permission and keeps the server running.
#
# Skips the rebuild when nothing changed: a re-signed app can lose the Bluetooth
# permission macOS granted to the previous build.
set -e
REPO="${0:A:h:h}"
APP="$HOME/Applications/xBloom Bridge.app"
REF="$HOME/.config/xbloom-mcp/bridge-build"   # unsigned copy of the last build
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

clang -O2 -DREPO_DIR="\"$REPO\"" -o "$TMP/xbloom-bridge" "$REPO/deploy/bridge.c"
cat > "$TMP/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>local.xbloom-bridge</string>
  <key>CFBundleName</key><string>xBloom Bridge</string>
  <key>CFBundleExecutable</key><string>xbloom-bridge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSUIElement</key><true/>
  <key>NSBluetoothAlwaysUsageDescription</key><string>Talks to the xBloom coffee machine so Claude can brew.</string>
</dict></plist>
PLIST

# Compare the unsigned binary (codesign rewrites the installed one) and the plist.
if [[ -d "$APP" ]] && cmp -s "$TMP/xbloom-bridge" "$REF/xbloom-bridge" \
   && cmp -s "$TMP/Info.plist" "$APP/Contents/Info.plist"; then
  echo "xBloom Bridge.app is up to date."
  exit 0
fi

rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
mkdir -p "$REF"; cp "$TMP/xbloom-bridge" "$REF/xbloom-bridge"
cp "$TMP/xbloom-bridge" "$APP/Contents/MacOS/xbloom-bridge"
cp "$TMP/Info.plist" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP" 2>/dev/null
echo "Built $APP (if macOS asks again, allow it to use Bluetooth)."
