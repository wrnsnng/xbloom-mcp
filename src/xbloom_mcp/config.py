"""Where settings and data live on each OS, and loading the settings file."""

from __future__ import annotations

import os
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"

if WINDOWS:
    _base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "xbloom-mcp"
    CONFIG_DIR = _base
    DATA_DIR = _base / "data"
    LOG_DIR = _base / "logs"
else:
    CONFIG_DIR = Path.home() / ".config/xbloom-mcp"
    DATA_DIR = Path.home() / ".local/share/xbloom-mcp"
    LOG_DIR = Path.home() / ("Library/Logs" if MACOS else ".local/state/xbloom-mcp")

ENV_FILE = CONFIG_DIR / "env"
PORT = 8787


def read_settings() -> dict[str, str]:
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() and not key.startswith("#"):
            out[key.strip()] = value.strip()
    return out


def write_settings(settings: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ENV_FILE.write_text("".join(f"{k}={v}\n" for k, v in settings.items()), encoding="utf-8")
    if not WINDOWS:  # %APPDATA% is already private to the user on Windows
        ENV_FILE.chmod(0o600)


def load_settings_into_env() -> None:
    """Fill os.environ from the settings file without overriding anything already set."""
    for key, value in read_settings().items():
        os.environ.setdefault(key, value)
