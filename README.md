# xbloom-mcp

Brew coffee on an **xBloom Studio** from Claude: on your phone, the web or the desktop app.

- 📷 **Snap the bag, get a recipe.** Claude reads the roaster, origin, process and roast
  level, looks for the roaster's own brew guide, and designs a recipe that fits the machine.
- ⚖️ **Tells you exactly how many grams of beans to weigh** into the grinder.
- ☕ **Brews remotely.** Claude asks you to confirm water, beans, filter and cup, then starts
  the machine and follows the brew live from its scale.
- 📚 **Shared recipe library** for everyone in the house, with version history.
- 👅 **Learns from feedback.** "Bit bitter" → Claude adjusts the grind or temperature and
  saves a new version.

> Unofficial. Uses the community reverse-engineered Bluetooth protocol from
> [xbloom-ble](https://github.com/jack-song/xbloom-ble). Verified on firmware `V12.0D.500`.
> A firmware update could break it. Not affiliated with xBloom.

## How it works

```
Claude (anywhere) ──HTTPS──▶ Cloudflare Tunnel ──▶ this server on a computer at home ──Bluetooth──▶ xBloom
```

The computer has to be within Bluetooth range of the machine (same room or next room) and
stay on. It can be a Mac, a Windows PC, or a Linux box such as a Raspberry Pi.

| | Status |
|---|---|
| macOS | Tested on a Mac mini, firmware `V12.0D.500` |
| Linux | Setup and server tested; Bluetooth not yet tested on real hardware |
| Windows | Written for, not yet tested. Reports welcome! |

## What you need

- A computer near the xBloom with Bluetooth Low Energy:
  - **macOS** 13+, with [Homebrew](https://brew.sh).
  - **Windows** 10/11, with `winget` (built in; otherwise "App Installer" from the Store).
  - **Linux** with systemd and BlueZ (Raspberry Pi OS, Ubuntu, Debian, Fedora...).
- A free [Cloudflare](https://dash.cloudflare.com/sign-up) account with a domain on it.
  You'll use a subdomain like `coffee.yourdomain.com`.
- Claude on any plan that supports custom connectors.

The setup script installs everything else (`uv` for Python, `cloudflared` for the tunnel).

## Setup (about 10 minutes)

Download the repo (`git clone https://github.com/wrnsnng/xbloom-mcp`, or **Code → Download
ZIP** and unzip it), then from inside the folder:

**macOS / Linux** (Terminal):

```bash
./setup.sh
```

**Windows** (PowerShell):

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The script walks you through four steps:

1. **Find your xBloom.** Turn the machine on, close the xBloom phone app and turn the
   phone's Bluetooth off (the machine only accepts one connection). On macOS, allow
   Terminal to use Bluetooth if asked.
2. **Pick a web address**, e.g. `coffee.yourdomain.com`.
3. **Cloudflare Tunnel.** A browser opens; log in and choose your domain. The script creates
   the tunnel and the DNS record.
4. **Start automatically.** The server and tunnel are set up to run in the background
   and start by themselves:
   - **macOS:** a tiny "xBloom Bridge" app in `~/Applications`, added to Login Items. It
     exists to hold the Bluetooth permission. When macOS asks whether **"xBloom Bridge"
     can use Bluetooth, click Allow.**
   - **Windows:** a scheduled task that starts at logon, with no window.
   - **Linux:** a systemd user service (`systemctl --user status xbloom-mcp`), set to
     start at boot.

At the end it prints your connector details:

```
URL:            https://coffee.yourdomain.com/mcp
Authentication: No sign-in
Request header: Authorization = Bearer <long-key>
```

**Treat the key like a password.** Anyone who has it can brew on your machine. If it
leaks, run `./setup.sh rotate-key` (Windows: `.\setup.ps1 rotate-key`) and update the
header on each connector.

If the final check says it can't reach the machine, it prints what to check for your OS;
fix it, then run `./setup.sh check` (Windows: `.\setup.ps1 check`).

## Add it to Claude

In Claude: **Settings → Connectors → Add custom connector**. Paste the URL, choose
**No sign-in**, then under **Request headers** click **Add header**: name `Authorization`,
value `Bearer <long-key>`. Claude stores the value securely. Do this on each person's
Claude account who should be able to brew. Then try:

> *"Here's a photo of my new beans. Make me a recipe."*
>
> *"Make me a coffee with the Ethiopian."*
>
> *"That was a bit sour, can you adjust it?"*

## Using it day to day

1. Fill the water tank, weigh the beans Claude tells you into the grinder, put a filter in
   the dripper and a cup underneath.
2. Ask Claude to brew. It confirms you're ready, then starts the machine.
3. The machine grinds for ~20 s (silently, as far as Claude can tell), then pours. A brew
   takes about 3 minutes.

The phone app and this server can't both be connected at once. If Claude says it can't
reach the machine, close the xBloom app on whoever's phone is nearby.

## Tools Claude gets

| Tool | What it does |
|---|---|
| `get_brewing_guide` | The machine's limits and how to design and adjust recipes for any bean |
| `find_recipe` / `list_recipes` / `get_recipe` | Search and view saved recipes, history and past brews |
| `save_recipe` / `update_recipe` / `delete_recipe` | Manage the library; recipes are checked against the machine's limits |
| `brew` | Start a saved recipe (refuses until the person confirms the machine is ready) |
| `brew_status` / `cancel_brew` | Follow a brew live, or stop it |
| `machine_status` | Is the machine reachable, idle, or busy? |
| `brew_feedback` | Record how it tasted |

## Files and logs

| What | macOS / Linux | Windows |
|---|---|---|
| Settings and secrets | `~/.config/xbloom-mcp/` | `%APPDATA%\xbloom-mcp\` |
| Recipe library (SQLite) | `~/.local/share/xbloom-mcp/recipes.db` | `%APPDATA%\xbloom-mcp\data\recipes.db` |
| Logs (`xbloom-mcp.log`, `xbloom-tunnel.log`) | macOS: `~/Library/Logs/`, Linux: `~/.local/state/xbloom-mcp/` | `%APPDATA%\xbloom-mcp\logs\` |

## Troubleshooting

Commands below use `./setup.sh`; on Windows use `.\setup.ps1` instead.

- **"Couldn't reach the xBloom"**: the machine is off, or a phone app is holding its one
  Bluetooth connection. Turning off Bluetooth for the xBloom app in the phone's settings
  stops that for good. On macOS, xBloom Bridge also needs the Bluetooth permission. Then
  run `./setup.sh check`.
- **Claude can't connect**: make sure the header value starts with `Bearer ` (with the
  space). Otherwise look at `xbloom-tunnel.log`, and make sure the computer doesn't go to
  sleep (macOS: System Settings → Energy; Windows: Settings → System → Power).
- **Linux: Bluetooth errors.** Install and start BlueZ (`sudo apt install bluez`); on a
  Raspberry Pi add yourself to the `bluetooth` group. `journalctl --user -u xbloom-mcp`
  shows the service's output.
- **Windows: PowerShell won't run the script.** Use the `-ExecutionPolicy Bypass` command
  above.
- **Machine says no beans / no water**: Claude will tell you; it cancels the brew.
- **After updating this repo** (`git pull`): run `./setup.sh check` to restart the server.

## Uninstall

```bash
./setup.sh uninstall          # removes the autostart; keeps recipes and settings
./setup.sh uninstall --all    # also deletes recipes and settings
```

(Windows: `.\setup.ps1 uninstall`, and `.\setup.ps1 uninstall --all`.)

## Credits

- Bluetooth protocol and machine control: [jack-song/xbloom-ble](https://github.com/jack-song/xbloom-ble) (MIT).
- Brewing guide adapted from the reference in [denull0/xbloom-agent](https://github.com/denull0/xbloom-agent) (MIT).

MIT licensed.
