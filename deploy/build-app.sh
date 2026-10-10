#!/bin/zsh
# Builds ~/Applications/xBloom Bridge.app: a background app (no Dock icon) that holds
# the macOS Bluetooth permission and keeps the server running.
set -e
REPO="${0:A:h:h}"
APP="$HOME/Applications/xBloom Bridge.app"
pkill -f run-server.sh 2>/dev/null || true; pkill -f "bin/xbloom-mcp" 2>/dev/null || true
rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
clang -O2 -DREPO_DIR="\"$REPO\"" -o "$APP/Contents/MacOS/xbloom-bridge" "$REPO/deploy/bridge.c"
cat > "$APP/Contents/Info.plist" <<PLIST
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
codesign --force --sign - "$APP" 2>/dev/null
echo "Built $APP"
