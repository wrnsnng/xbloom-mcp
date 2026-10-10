#!/usr/bin/env bash
# xbloom-mcp setup for macOS and Linux. Installs uv and cloudflared if needed, then runs
# the interactive setup. Also: ./setup.sh check | rotate-key | uninstall [--all]
set -euo pipefail
cd "$(dirname "$0")"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

install_uv() {
  echo "Installing uv (Python tool runner)…"
  if [[ $(uname) == Darwin ]] && command -v brew >/dev/null; then
    brew install uv
  else
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
}

install_cloudflared() {
  echo "Installing cloudflared (Cloudflare Tunnel)…"
  if [[ $(uname) == Darwin ]]; then
    command -v brew >/dev/null || { echo "Install Homebrew (https://brew.sh) and re-run."; exit 1; }
    brew install cloudflared
  else
    case $(uname -m) in
      x86_64) arch=amd64 ;;
      aarch64|arm64) arch=arm64 ;;
      armv7l) arch=arm ;;
      *) echo "Unsupported CPU $(uname -m); install cloudflared manually and re-run."; exit 1 ;;
    esac
    mkdir -p "$HOME/.local/bin"
    curl -fsSL -o "$HOME/.local/bin/cloudflared" \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$arch"
    chmod +x "$HOME/.local/bin/cloudflared"
  fi
}

if [[ ${1:-setup} == setup ]]; then
  command -v uv >/dev/null || install_uv
  command -v cloudflared >/dev/null || install_cloudflared
  if [[ $(uname) == Darwin ]] && ! command -v clang >/dev/null; then
    echo "Run: xcode-select --install   (then re-run ./setup.sh)"; exit 1
  fi
fi

uv sync --frozen -q
exec uv run --frozen xbloom-mcp "${@:-setup}"
