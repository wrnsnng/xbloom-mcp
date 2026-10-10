#!/bin/zsh
# Run by "xBloom Bridge.app" (macOS), which holds the Bluetooth permission.
# run-all supervises the server and tunnel; this loop restarts run-all itself.
cd "${0:A:h:h}"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
while true; do
  uv run --frozen xbloom-mcp run-all
  sleep 5
done
