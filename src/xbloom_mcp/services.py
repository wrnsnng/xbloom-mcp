"""Install, restart and remove the autostart for `xbloom-mcp run-all` on each OS.

- macOS: "xBloom Bridge.app" (built from deploy/), added to Login Items. The app is what
  holds the Bluetooth permission; a plain launchd agent can't get one.
- Linux: a systemd user service (`xbloom-mcp.service`), with lingering so it runs at boot.
- Windows: a scheduled task at logon that starts it with no console window.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

from .config import CONFIG_DIR, MACOS, WINDOWS

REPO = Path(__file__).resolve().parents[2]
APP = Path.home() / "Applications/xBloom Bridge.app"
UNIT = Path.home() / ".config/systemd/user/xbloom-mcp.service"
TASK = "xbloom-mcp"
PID_FILE = CONFIG_DIR / "supervisor.pid"


def _run(*cmd: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _uv() -> str:
    return shutil.which("uv") or "uv"


def describe() -> str:
    if MACOS:
        return "xBloom Bridge app (Login Items)"
    if WINDOWS:
        return "scheduled task 'xbloom-mcp' (runs at logon)"
    return "systemd user service 'xbloom-mcp'"


# --- install ---------------------------------------------------------------------------

def install() -> None:
    if MACOS:
        _install_macos()
    elif WINDOWS:
        _install_windows()
    else:
        _install_linux()


def _install_macos() -> None:
    # Older versions ran the tunnel as its own launchd agent; run-all owns it now.
    for label in ("local.xbloom-tunnel", "co.common-tools.xbloom-tunnel"):
        _run("launchctl", "bootout", f"gui/{os.getuid()}/{label}")
        (Path.home() / f"Library/LaunchAgents/{label}.plist").unlink(missing_ok=True)
    _run("zsh", str(REPO / "deploy/build-app.sh"), check=True)
    _login_item(add=True)
    restart()  # an already-running bridge would otherwise keep the old processes


def _login_item(add: bool) -> None:
    _run("osascript", "-e", 'tell application "System Events" to delete '
         '(every login item whose name is "xBloom Bridge")')
    if add:
        _run("osascript", "-e", 'tell application "System Events" to make login item at end '
             f'with properties {{path:"{APP}", hidden:true}}')


def _install_linux() -> None:
    UNIT.parent.mkdir(parents=True, exist_ok=True)
    UNIT.write_text(f"""[Unit]
Description=xbloom-mcp (Claude ↔ xBloom bridge and Cloudflare tunnel)
After=network-online.target bluetooth.target
Wants=network-online.target

[Service]
WorkingDirectory={REPO}
ExecStart={_uv()} run --frozen xbloom-mcp run-all
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
""", encoding="utf-8")
    _run("systemctl", "--user", "daemon-reload")
    _run("systemctl", "--user", "enable", "--now", "xbloom-mcp.service", check=True)
    _run("systemctl", "--user", "restart", "xbloom-mcp.service")
    # Keep running after logout and start at boot (may need admin rights on some distros).
    if _run("loginctl", "enable-linger", os.environ.get("USER", "")).returncode != 0:
        print("Note: couldn't enable lingering; it will start when you log in. To start at boot:\n"
              f"  sudo loginctl enable-linger {os.environ.get('USER', '$USER')}")


def _install_windows() -> None:
    # wscript runs the launcher with no window; schtasks /TR is limited to 261 chars,
    # so the full command lives in the .vbs.
    vbs = CONFIG_DIR / "start-xbloom-mcp.vbs"
    cmd = f'"{_uv()}" run --frozen --project "{REPO}" xbloom-mcp run-all'
    vbs.write_text('CreateObject("WScript.Shell").Run "' + cmd.replace('"', '""') + '", 0, False\n',
                   encoding="utf-8")
    _run("schtasks", "/Create", "/F", "/SC", "ONLOGON", "/RL", "LIMITED", "/TN", TASK,
         "/TR", f'wscript.exe "{vbs}"', check=True)
    restart()


# --- restart / uninstall ---------------------------------------------------------------

def _kill_supervisor() -> None:
    if PID_FILE.exists():
        pid = PID_FILE.read_text().strip()
        if WINDOWS:
            _run("taskkill", "/T", "/F", "/PID", pid)
        else:
            _run("kill", pid)
        PID_FILE.unlink(missing_ok=True)
    if MACOS:  # also catch anything started before the pid file existed
        _run("pkill", "-f", "run-server.sh")
        _run("pkill", "-f", "xbloom-mcp run-all")
        _run("pkill", "-f", "xbloom_mcp serve")
        _run("pkill", "-xf", ".*/bin/xbloom-mcp")  # pre-supervisor server, no arguments


def restart() -> None:
    if MACOS:
        _kill_supervisor()
        time.sleep(1)
        _run("open", str(APP))
    elif WINDOWS:
        _kill_supervisor()
        time.sleep(1)
        _run("schtasks", "/Run", "/TN", TASK)
    else:
        _run("systemctl", "--user", "restart", "xbloom-mcp.service")


def uninstall() -> None:
    if MACOS:
        _kill_supervisor()
        _login_item(add=False)
        shutil.rmtree(APP, ignore_errors=True)
        for label in ("local.xbloom-tunnel", "co.common-tools.xbloom-tunnel"):
            _run("launchctl", "bootout", f"gui/{os.getuid()}/{label}")
            (Path.home() / f"Library/LaunchAgents/{label}.plist").unlink(missing_ok=True)
    elif WINDOWS:
        _kill_supervisor()
        _run("schtasks", "/Delete", "/F", "/TN", TASK)
        (CONFIG_DIR / "start-xbloom-mcp.vbs").unlink(missing_ok=True)
    else:
        _run("systemctl", "--user", "disable", "--now", "xbloom-mcp.service")
        UNIT.unlink(missing_ok=True)
        _run("systemctl", "--user", "daemon-reload")
