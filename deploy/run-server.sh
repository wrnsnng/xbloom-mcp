#!/bin/zsh
# Run by "xBloom Bridge.app". Restarts the server if it ever exits.
# Settings and secrets live in ~/.config/xbloom-mcp/env (written by setup.sh).
set -a; source ~/.config/xbloom-mcp/env; set +a
cd "${0:A:h:h}"
UV=$(command -v uv || echo /opt/homebrew/bin/uv)
while true; do
  "$UV" run --frozen xbloom-mcp
  sleep 5
done
