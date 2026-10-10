#!/bin/zsh
# One-time setup for xbloom-mcp on a Mac near your xBloom Studio.
# Safe to re-run: it keeps your existing secret and settings unless you change them.
set -e
cd "${0:A:h}"
REPO=$PWD
CFG=~/.config/xbloom-mcp
ENV=$CFG/env
TUNNEL_LABEL=local.xbloom-tunnel

bold() { print -P "%B$1%b"; }
ask() { local a; read "a?$1 "; print -r -- "$a"; }
setting() { [[ -f $ENV ]] && grep -E "^$1=" $ENV | cut -d= -f2- || true; }

check_machine() {
  uv run python - "$(setting XBLOOM_MCP_SECRET)" <<'PY' || print "Server not responding; see ~/Library/Logs/xbloom-mcp.log"
import asyncio, sys
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
async def main():
    async with streamable_http_client(f"http://127.0.0.1:8787/{sys.argv[1]}/mcp") as (r, w, *_):
        async with ClientSession(r, w) as s:
            await s.initialize()
            print((await s.call_tool("machine_status", {})).content[0].text)
asyncio.run(main())
PY
}

# ./setup.sh check — restart the bridge and test the machine connection.
if [[ $1 == check ]]; then
  set +e
  pkill -f run-server.sh; pkill -f "bin/xbloom-mcp"; sleep 1
  open "$HOME/Applications/xBloom Bridge.app"; sleep 6
  check_machine
  print "Connector URL: https://$(setting XBLOOM_MCP_HOSTS)/$(setting XBLOOM_MCP_SECRET)/mcp"
  exit 0
fi

bold "xbloom-mcp setup"
print "This connects Claude to your xBloom over Bluetooth, from this Mac.\n"

# 1. Tools
for tool in uv cloudflared; do
  if ! command -v $tool >/dev/null; then
    if command -v brew >/dev/null; then
      print "Installing $tool…"; brew install $tool
    else
      print "Please install Homebrew (https://brew.sh), then re-run ./setup.sh"; exit 1
    fi
  fi
done
command -v clang >/dev/null || { print "Run: xcode-select --install   (then re-run ./setup.sh)"; exit 1; }
uv sync --frozen -q

# 2. Find the machine
umask 077; mkdir -p $CFG
ADDRESS=$(setting XBLOOM_ADDRESS)
if [[ -z $ADDRESS ]]; then
  bold "\n1/4  Find your xBloom"
  print "Turn the xBloom on. Close the xBloom phone app and turn your phone's Bluetooth off"
  print "(the machine only accepts one connection). If macOS asks to let Terminal use"
  print "Bluetooth, click Allow.\n"
  ask "Press Enter to scan…" >/dev/null
  uv run xbloom scan --timeout 10 | tee /tmp/xbloom-scan.txt
  ADDRESS=$(grep -Eo '^  [0-9A-F-]{17,}' /tmp/xbloom-scan.txt | head -1 | tr -d ' ')
  [[ -n $ADDRESS ]] || { print "No machine found. Check the steps above and re-run."; exit 1; }
  print "Using $ADDRESS"
fi

# 3. Domain
HOST=$(setting XBLOOM_MCP_HOSTS)
if [[ -z $HOST ]]; then
  bold "\n2/4  Pick a web address"
  print "Claude reaches this Mac through a free Cloudflare Tunnel. You need a domain on"
  print "a (free) Cloudflare account. Pick a subdomain, e.g. coffee.example.com"
  HOST=$(ask "Hostname:")
  [[ $HOST == *.* ]] || { print "That doesn't look like a hostname."; exit 1; }
fi

SECRET=$(setting XBLOOM_MCP_SECRET)
[[ -n $SECRET ]] || SECRET=$(openssl rand -hex 24)
cat > $ENV <<EOF
XBLOOM_ADDRESS=$ADDRESS
XBLOOM_MCP_HOSTS=$HOST
XBLOOM_MCP_SECRET=$SECRET
EOF

# 4. Tunnel
bold "\n3/4  Cloudflare Tunnel"
if [[ -f $CFG/cloudflared.yml || -f $CFG/tunnel-token ]]; then
  print "Tunnel already configured."
else
  [[ -f ~/.cloudflared/cert.pem ]] || { print "A browser window opens: log in and pick your domain."; cloudflared tunnel login; }
  cloudflared tunnel info xbloom-mcp >/dev/null 2>&1 || cloudflared tunnel create xbloom-mcp
  TID=$(cloudflared tunnel info xbloom-mcp 2>/dev/null | grep -Eo '[0-9a-f]{8}-[0-9a-f-]{27}' | head -1)
  cp ~/.cloudflared/$TID.json $CFG/tunnel-credentials.json
  cat > $CFG/cloudflared.yml <<EOF
tunnel: $TID
credentials-file: $CFG/tunnel-credentials.json
ingress:
  - hostname: $HOST
    service: http://127.0.0.1:8787
  - service: http_status:404
EOF
  cloudflared tunnel route dns xbloom-mcp $HOST || print "(DNS record may already exist; continuing)"
fi

PLIST=~/Library/LaunchAgents/$TUNNEL_LABEL.plist
cat > $PLIST <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$TUNNEL_LABEL</string>
  <key>ProgramArguments</key><array><string>$REPO/deploy/run-tunnel.sh</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$HOME/Library/Logs/xbloom-tunnel.log</string>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/xbloom-tunnel.log</string>
</dict></plist>
EOF
launchctl bootout gui/$(id -u)/$TUNNEL_LABEL 2>/dev/null || true
launchctl bootstrap gui/$(id -u) $PLIST

# 5. Bridge app
bold "\n4/4  xBloom Bridge app"
./deploy/build-app.sh
APP="$HOME/Applications/xBloom Bridge.app"
osascript -e "tell application \"System Events\" to delete (every login item whose name is \"xBloom Bridge\")" >/dev/null 2>&1 || true
osascript -e "tell application \"System Events\" to make login item at end with properties {path:\"$APP\", hidden:true}" >/dev/null \
  && print "Added to Login Items (starts automatically)."
open "$APP"
sleep 5

print "\nChecking the machine through the server (macOS may now ask whether"
print "\"xBloom Bridge\" can use Bluetooth: click Allow)…"
check_machine

bold "\nDone. Add this as a custom connector in Claude (Settings → Connectors):"
print "\n  https://$HOST/$SECRET/mcp\n"
print "Treat that URL like a password: anyone with it can brew on your machine."
print "If the check above said it couldn't reach the machine, allow xBloom Bridge in"
print "System Settings → Privacy & Security → Bluetooth, then run: ./setup.sh check"
