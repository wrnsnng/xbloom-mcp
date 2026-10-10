"""`xbloom-mcp run-all`: run the server and the Cloudflare tunnel, restarting either if it exits.

This is the one thing each OS's autostart launches (Bridge.app on macOS, a systemd user
service on Linux, a logon task on Windows).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from .config import CONFIG_DIR, LOG_DIR, WINDOWS

RESTART_DELAY_S = 5


def find_cloudflared() -> str | None:
    found = shutil.which("cloudflared")
    if found:
        return found
    candidates = (
        [Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
         Path(r"C:\Program Files\cloudflared\cloudflared.exe")]
        if WINDOWS else
        [Path("/opt/homebrew/bin/cloudflared"), Path("/usr/local/bin/cloudflared"),
         Path.home() / ".local/bin/cloudflared"]
    )
    return next((str(p) for p in candidates if p.exists()), None)


def tunnel_command() -> list[str] | None:
    exe = find_cloudflared()
    if exe is None:
        return None
    base = [exe, "tunnel", "--no-autoupdate"]
    if (CONFIG_DIR / "cloudflared.yml").exists():
        return [*base, "--config", str(CONFIG_DIR / "cloudflared.yml"), "run"]
    if (CONFIG_DIR / "tunnel-token").exists():
        return [*base, "run", "--token-file", str(CONFIG_DIR / "tunnel-token")]
    return None


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pid_file = CONFIG_DIR / "supervisor.pid"
    pid_file.write_text(str(os.getpid()))
    flags = subprocess.CREATE_NO_WINDOW if WINDOWS else 0
    specs = {"server": [sys.executable, "-m", "xbloom_mcp", "serve"]}
    tunnel = tunnel_command()
    if tunnel:
        specs["tunnel"] = tunnel
    else:
        print("No tunnel configured (or cloudflared missing); running the server only.", flush=True)

    logs = {name: open(LOG_DIR / f"xbloom-{'mcp' if name == 'server' else name}.log", "a")
            for name in specs}
    procs: dict[str, subprocess.Popen] = {}
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while not stopping:
        for name, cmd in specs.items():
            p = procs.get(name)
            if p is None or p.poll() is not None:
                if p is not None:
                    print(f"{name} exited ({p.returncode}); restarting", flush=True)
                    time.sleep(RESTART_DELAY_S)
                procs[name] = subprocess.Popen(cmd, stdout=logs[name], stderr=subprocess.STDOUT,
                                               creationflags=flags)
        time.sleep(1)

    pid_file.unlink(missing_ok=True)
    for p in procs.values():
        p.terminate()
    for p in procs.values():
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
