"""Interactive setup and maintenance: `xbloom-mcp setup | check | rotate-key | uninstall`.

Safe to re-run: existing settings, key and tunnel are kept.
"""

from __future__ import annotations

import asyncio
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

from . import services
from .config import CONFIG_DIR, DATA_DIR, LOG_DIR, MACOS, PORT, WINDOWS, read_settings, write_settings
from .supervisor import find_cloudflared

TUNNEL_NAME = "xbloom-mcp"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
WHERE = "this Mac" if MACOS else "this PC" if WINDOWS else "this machine"


def bold(text: str) -> None:
    print(f"\033[1m{text}\033[0m")


# --- checks ----------------------------------------------------------------------------

def check_machine(secret: str) -> str:
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def run() -> str:
        http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {secret}"}, timeout=60)
        async with streamable_http_client(f"http://127.0.0.1:{PORT}/mcp", http_client=http) as (r, w, *_):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return (await s.call_tool("machine_status", {})).content[0].text

    for _ in range(10):  # the server may still be starting
        try:
            return asyncio.run(run())
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return f"Server not responding; see {LOG_DIR / 'xbloom-mcp.log'}"


def connector_info(settings: dict[str, str]) -> None:
    print(f"\n  URL:            https://{settings['XBLOOM_MCP_HOSTS']}/mcp")
    print("  Authentication: No sign-in")
    print(f"  Request header: Authorization = Bearer {settings['XBLOOM_MCP_SECRET']}\n")
    print("Treat the header value like a password: anyone with it can brew on your machine.")


def bluetooth_hint() -> str:
    if MACOS:
        return ("xBloom Bridge is allowed in System Settings → Privacy & Security → "
                "Bluetooth (then run the check again)")
    if WINDOWS:
        return "Bluetooth is on in Settings → Bluetooth & devices"
    return ("Bluetooth is on and BlueZ is running (`sudo apt install bluez`, then "
            "`bluetoothctl show`), and that your user may use it (on a Raspberry Pi: "
            "`sudo usermod -aG bluetooth $USER`, then log out and in)")


# --- steps -----------------------------------------------------------------------------

def find_address() -> str:
    from xbloom_ble.client import scan

    bold("\n1/4  Find your xBloom")
    print("Turn the xBloom on. Close the xBloom phone app and turn your phone's Bluetooth off")
    print("(the machine only accepts one connection).")
    if MACOS:
        print("If macOS asks to let Terminal use Bluetooth, click Allow.")
    input("\nPress Enter to scan… ")
    try:
        devices = asyncio.run(scan(timeout=10))
    except Exception as exc:  # noqa: BLE001 - no adapter, BlueZ not running, permission
        raise SystemExit(f"Bluetooth scan failed ({type(exc).__name__}: {exc}).\n"
                         f"Check that {bluetooth_hint()}.") from None
    if not devices:
        raise SystemExit(f"No xBloom found. Check the steps above and that {bluetooth_hint()}.")
    for d in devices:
        print(f"  found {d.name}  ({d.address})")
    print(f"Using {devices[0].address}")
    return devices[0].address


def ask_hostname() -> str:
    bold("\n2/4  Pick a web address")
    print(f"Claude reaches {WHERE} through a free Cloudflare Tunnel. You need a domain on a")
    print("(free) Cloudflare account. Pick a subdomain, e.g. coffee.example.com")
    host = input("Hostname: ").strip().lower()
    if "." not in host or "/" in host:
        raise SystemExit("That doesn't look like a hostname (example: coffee.example.com).")
    return host


def setup_tunnel(host: str) -> None:
    bold("\n3/4  Cloudflare Tunnel")
    if (CONFIG_DIR / "cloudflared.yml").exists() or (CONFIG_DIR / "tunnel-token").exists():
        print("Tunnel already configured.")
        return
    cf = find_cloudflared()
    if cf is None:
        raise SystemExit("cloudflared not found. Re-run the setup script, which installs it.")
    cert = Path.home() / ".cloudflared/cert.pem"
    if not cert.exists():
        print("A browser window opens: log in to Cloudflare and pick your domain.")
        subprocess.run([cf, "tunnel", "login"], check=True)

    info = subprocess.run([cf, "tunnel", "info", TUNNEL_NAME], capture_output=True, text=True)
    if info.returncode != 0:
        subprocess.run([cf, "tunnel", "create", TUNNEL_NAME], check=True)
        info = subprocess.run([cf, "tunnel", "info", TUNNEL_NAME], capture_output=True, text=True)
    match = UUID_RE.search(info.stdout + info.stderr)
    if not match:
        raise SystemExit("Couldn't read the tunnel ID from `cloudflared tunnel info`.")
    tid = match.group(0)
    creds = Path.home() / f".cloudflared/{tid}.json"
    if not creds.exists():
        raise SystemExit(f"Tunnel credentials {creds} are missing. Delete the tunnel "
                         f"(`cloudflared tunnel delete {TUNNEL_NAME}`) and re-run setup.")
    shutil.copy(creds, CONFIG_DIR / "tunnel-credentials.json")
    # Forward slashes work for cloudflared on every OS and avoid YAML escaping issues.
    cred_path = (CONFIG_DIR / "tunnel-credentials.json").as_posix()
    (CONFIG_DIR / "cloudflared.yml").write_text(
        f"tunnel: {tid}\ncredentials-file: {cred_path}\ningress:\n"
        f"  - hostname: {host}\n    service: http://127.0.0.1:{PORT}\n"
        f"  - service: http_status:404\n", encoding="utf-8")
    route = subprocess.run([cf, "tunnel", "route", "dns", TUNNEL_NAME, host])
    if route.returncode != 0:
        print("(The DNS record may already exist; continuing.)")


# --- commands --------------------------------------------------------------------------

def setup() -> None:
    bold("xbloom-mcp setup")
    print(f"This connects Claude to your xBloom over Bluetooth, from {WHERE}.")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    s = read_settings()
    s["XBLOOM_ADDRESS"] = s.get("XBLOOM_ADDRESS") or find_address()
    s["XBLOOM_MCP_HOSTS"] = s.get("XBLOOM_MCP_HOSTS") or ask_hostname()
    s["XBLOOM_MCP_SECRET"] = s.get("XBLOOM_MCP_SECRET") or secrets.token_hex(24)
    write_settings(s)
    setup_tunnel(s["XBLOOM_MCP_HOSTS"])

    bold(f"\n4/4  Start automatically: {services.describe()}")
    services.install()
    print("\nChecking the machine through the server…")
    if MACOS:
        print('(macOS may now ask whether "xBloom Bridge" can use Bluetooth: click Allow.)')
    result = check_machine(s["XBLOOM_MCP_SECRET"])
    print(result)

    bold("\nDone. Add a custom connector in Claude (Settings → Connectors) with:")
    connector_info(s)
    if not result.startswith("Machine reachable"):
        print(f"\nIt couldn't reach the machine yet. Check the xBloom is on, no phone app is "
              f"connected, and {bluetooth_hint()}.")


def check(rotated: bool = False) -> None:
    s = read_settings()
    if not s:
        raise SystemExit("Not set up yet; run the setup script first.")
    services.restart()
    time.sleep(4)
    print(check_machine(s["XBLOOM_MCP_SECRET"]))
    if rotated:
        print("\nNew key issued. Update the header on every Claude connector:")
    connector_info(s)


def rotate_key() -> None:
    s = read_settings()
    if not s:
        raise SystemExit("Not set up yet; run the setup script first.")
    s["XBLOOM_MCP_SECRET"] = secrets.token_hex(24)
    write_settings(s)
    check(rotated=True)


def uninstall(everything: bool) -> None:
    services.uninstall()
    if everything:
        shutil.rmtree(CONFIG_DIR, ignore_errors=True)
        shutil.rmtree(DATA_DIR, ignore_errors=True)
        print(f"Removed everything. To delete the tunnel too: cloudflared tunnel delete {TUNNEL_NAME}")
    else:
        print(f"Removed the autostart. Recipes ({DATA_DIR}) and settings ({CONFIG_DIR}) kept; "
              "uninstall --all deletes them.")
