#!/bin/zsh
# Run by the launchd agent installed by setup.sh. Uses a local tunnel config if
# present (setup.sh creates one), otherwise a tunnel token (Cloudflare-managed tunnel).
CFG=~/.config/xbloom-mcp
CLOUDFLARED=$(command -v cloudflared || echo /opt/homebrew/bin/cloudflared)
if [[ -f $CFG/cloudflared.yml ]]; then
  exec "$CLOUDFLARED" tunnel --no-autoupdate --config $CFG/cloudflared.yml run
else
  exec "$CLOUDFLARED" tunnel --no-autoupdate run --token-file $CFG/tunnel-token
fi
