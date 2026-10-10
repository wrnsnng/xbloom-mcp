#!/bin/zsh
# Removes the bridge app, login item and tunnel service. Keeps your recipes
# (~/.local/share/xbloom-mcp) and settings (~/.config/xbloom-mcp) unless --all.
launchctl bootout gui/$(id -u)/local.xbloom-tunnel 2>/dev/null
rm -f ~/Library/LaunchAgents/local.xbloom-tunnel.plist
pkill -f xbloom-bridge 2>/dev/null; pkill -f "bin/xbloom-mcp" 2>/dev/null
osascript -e 'tell application "System Events" to delete (every login item whose name is "xBloom Bridge")' >/dev/null 2>&1
rm -rf ~/Applications/"xBloom Bridge.app"
if [[ $1 == --all ]]; then
  rm -rf ~/.config/xbloom-mcp ~/.local/share/xbloom-mcp
  print "Removed everything. To delete the tunnel too: cloudflared tunnel delete xbloom-mcp"
else
  print "Removed. Recipes and settings kept (run with --all to delete them)."
fi
