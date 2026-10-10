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
Claude (anywhere) ──HTTPS──▶ Cloudflare Tunnel ──▶ this server on a Mac at home ──Bluetooth──▶ xBloom
```

The Mac has to be within Bluetooth range of the machine (same room or next room) and stay on.

## What you need

- A Mac near the xBloom (any Mac on macOS 13+; a Mac mini that stays on is ideal).
- A free [Cloudflare](https://dash.cloudflare.com/sign-up) account with a domain on it.
  You'll use a subdomain like `coffee.yourdomain.com`.
- Claude on any plan that supports custom connectors.
- [Homebrew](https://brew.sh) (the setup script installs `uv` and `cloudflared` with it).

## Setup (about 10 minutes)

```bash
git clone <this repo> xbloom-mcp
cd xbloom-mcp
./setup.sh
```

The script walks you through four steps:

1. **Find your xBloom.** Turn the machine on, close the xBloom phone app and turn the
   phone's Bluetooth off (the machine only accepts one connection). Allow Terminal to use
   Bluetooth if macOS asks.
2. **Pick a web address**, e.g. `coffee.yourdomain.com`.
3. **Cloudflare Tunnel.** A browser opens; log in and choose your domain. The script creates
   the tunnel and the DNS record, and installs a background service for it.
4. **xBloom Bridge app.** Builds a tiny background app in `~/Applications` that holds the
   Bluetooth permission and runs the server. It's added to Login Items. When macOS asks
   whether **"xBloom Bridge" can use Bluetooth, click Allow.**

At the end it prints your connector details:

```
URL:            https://coffee.yourdomain.com/mcp
Authentication: No sign-in
Request header: Authorization = Bearer <long-key>
```

**Treat the key like a password.** Anyone who has it can brew on your machine. If it
leaks, run `./setup.sh rotate-key` and update the header on each connector.

If the final check says it can't reach the machine, turn on **xBloom Bridge** in
System Settings → Privacy & Security → Bluetooth, then run `./setup.sh check`.

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

| What | Where |
|---|---|
| Settings and secrets | `~/.config/xbloom-mcp/` |
| Recipe library (SQLite) | `~/.local/share/xbloom-mcp/recipes.db` |
| Server log | `~/Library/Logs/xbloom-mcp.log` |
| Tunnel log | `~/Library/Logs/xbloom-tunnel.log` |

## Troubleshooting

- **"Couldn't reach the xBloom"**: the machine is off, a phone app is connected, or xBloom
  Bridge lacks the Bluetooth permission (see above). Run `./setup.sh check`.
- **Claude can't connect**: make sure the header value starts with `Bearer ` (with the
  space). Otherwise check `~/Library/Logs/xbloom-tunnel.log`, and that
  the Mac is awake (System Settings → Energy → prevent automatic sleeping).
- **Machine says no beans / no water**: Claude will tell you; it cancels the brew.
- **After updating this repo** (`git pull`): run `./setup.sh check` to restart the server.

## Uninstall

```bash
./uninstall.sh          # removes the app, login item and tunnel service; keeps recipes
./uninstall.sh --all    # also deletes recipes and settings
```

## Credits

- Bluetooth protocol and machine control: [jack-song/xbloom-ble](https://github.com/jack-song/xbloom-ble) (MIT).
- Brewing guide adapted from the reference in [denull0/xbloom-agent](https://github.com/denull0/xbloom-agent) (MIT).

MIT licensed.
