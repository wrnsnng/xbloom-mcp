"""MCP server: design, store and brew xBloom recipes from Claude."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from xbloom_ble import Recipe, RecipeError

from . import config
from .machine import BrewState, Machine
from .store import Store

log = logging.getLogger(__name__)

GUIDE = (Path(__file__).parent / "guide.md").read_text(encoding="utf-8")
DATA_DIR = Path(os.environ.get("XBLOOM_MCP_DATA") or config.DATA_DIR)
ADDRESS = os.environ.get("XBLOOM_ADDRESS", "")

store = Store(DATA_DIR / "recipes.db")
machine = Machine(ADDRESS)
last_brew_id: int | None = None

INSTRUCTIONS = """\
Controls the household xBloom Studio coffee machine: design pour-over recipes for any \
beans, keep a shared recipe library, and brew remotely.

Workflow:
- Beans mentioned or photographed: read roaster, bean name, origin, process, roast level, \
roast date and tasting notes. Call find_recipe first; reuse a saved recipe if one matches.
- No match: if you can search the web, look for the roaster's own pour-over recipe and the \
bean's details. Then call get_brewing_guide and design a recipe. Show the recipe card and \
save it with save_recipe.
- Always state clearly how many grams of whole beans to weigh out and put in the grinder \
(that is dose_g; the machine grinds everything loaded).
- Brewing pours near-boiling water. Before calling brew, ask the person to confirm that the \
water tank is filled, the weighed beans are in the grinder, a filter is in the dripper and a \
cup is underneath. Only call brew with confirmed_ready=true after they say yes.
- After a brew, ask how it tasted. Record it with brew_feedback, and if they want changes, \
adjust with update_recipe (change one or two variables, per the guide).
"""


class Pour(BaseModel):
    ml: int = Field(description="Water for this pour, 1-127 ml.")
    temp_c: int = Field(description="Water temperature, 40-95 °C.")
    pattern: Literal["spiral", "circular", "center"] = "spiral"
    pause_s: int = Field(0, description="Wait after this pour, 0-255 s. For the bloom this is the bloom time.")
    rpm: int = Field(100, description="Pour spin speed 60-120; must be 0 for a center pour.")
    flow_ml_s: float = Field(3.0, description="Flow rate 3.0-3.5 ml/s.")
    agitation: bool = Field(False, description="Shake the dripper after this pour.")
    label: str | None = Field(None, description="e.g. 'Bloom', 'Pour 1'.")


class RecipeIn(BaseModel):
    dose_g: int = Field(description="Grams of whole beans to weigh out, 1-18.")
    grind: int = Field(description="Grind setting 1-80, lower is finer. 0 = pre-ground.")
    pours: list[Pour] = Field(description="Bloom first, then main pours. At least 2.")
    note: str | None = Field(None, description="Short reasoning / tasting intent.")


class Bean(BaseModel):
    roaster: str | None = None
    bean: str | None = Field(None, description="Coffee name as printed on the bag.")
    origin: str | None = Field(None, description="Country / region / farm.")
    process: str | None = Field(None, description="washed, natural, honey, anaerobic...")
    roast_level: str | None = Field(None, description="light, medium, dark")
    tasting_notes: str | None = None
    source: str | None = Field(None, description="Where the recipe came from, e.g. roaster URL or 'designed'.")


def _to_recipe(name: str, r: RecipeIn) -> Recipe:
    data = {
        "name": name,
        "dose_g": r.dose_g,
        "grind": r.grind,
        "note": r.note,
        "pours": [p.model_dump(exclude_none=True) for p in r.pours],
    }
    recipe = Recipe.from_dict(data)
    errors = []
    try:
        recipe.validate()
    except RecipeError as exc:
        errors.append(str(exc))
    for i, p in enumerate(r.pours, 1):
        if p.ml > 127:
            errors.append(f"pour #{i}: {p.ml} ml is over the 127 ml per-pour maximum; split it")
    if errors:
        raise ValueError("Recipe doesn't fit the machine: " + "; ".join(errors))
    return recipe


def _card(row: dict[str, Any]) -> str:
    r = row["recipe"]
    total = sum(p["ml"] for p in r["pours"])
    lines = [
        f"**{row['name']}** (recipe #{row['id']}, v{row['version']})",
        f"**Weigh out {r['dose_g']} g of whole beans** and put them in the grinder.",
        f"Grind {r['grind']} · {total} ml water · 1:{total / r['dose_g']:.1f}",
    ]
    for i, p in enumerate(r["pours"], 1):
        bits = [f"{p['ml']} ml", f"{p['temp_c']} °C", p.get("pattern", "spiral")]
        if p.get("agitation"):
            bits.append("shake")
        if p.get("pause_s"):
            bits.append(f"wait {p['pause_s']} s")
        label = f"{p['label']}: " if p.get("label") else ""
        lines.append(f"{i}. {label}{', '.join(bits)}")
    bean = ", ".join(str(row[k]) for k in ("roaster", "bean", "origin", "process", "roast_level") if row.get(k))
    if bean:
        lines.append(f"Beans: {bean}")
    if r.get("note"):
        lines.append(f"Note: {r['note']}")
    return "\n".join(lines)


def _recipe_dict(r: RecipeIn) -> dict[str, Any]:
    return r.model_dump(exclude_none=True)


mcp = MCPServer(name="xbloom", instructions=INSTRUCTIONS)


@mcp.tool()
def get_brewing_guide() -> str:
    """The machine's limits plus how to design and adjust a recipe for any bean. Read before designing or changing a recipe."""
    return GUIDE


@mcp.tool()
def find_recipe(query: str) -> str:
    """Search saved recipes by roaster, bean name, origin, process or recipe name. Use before designing a new one."""
    rows = store.search(query)
    if not rows:
        return f"No saved recipe matches '{query}'."
    return "\n\n".join(_card(r) for r in rows[:5])


@mcp.tool()
def list_recipes() -> str:
    """List every saved recipe."""
    rows = store.list()
    if not rows:
        return "No recipes saved yet."
    return "\n".join(
        f"#{r['id']} {r['name']} — {r['recipe']['dose_g']} g, grind {r['recipe']['grind']}"
        + (f" ({r['roaster']})" if r.get("roaster") else "")
        for r in rows)


@mcp.tool()
def get_recipe(recipe_id: int) -> str:
    """Show one recipe with its version history and recent brews."""
    row = store.get(recipe_id)
    if row is None:
        return f"No recipe #{recipe_id}."
    hist = "\n".join(f"v{h['version']}: {h['change_note']} ({h['created_at'][:10]})" for h in store.history(recipe_id))
    brews = "\n".join(
        f"{b['started_at'][:16]} v{b['version']}: {b['outcome'] or 'running'}"
        + (f" — \"{b['feedback']}\"" if b["feedback"] else "")
        for b in store.recent_brews(recipe_id))
    return f"{_card(row)}\n\nHistory:\n{hist}" + (f"\n\nRecent brews:\n{brews}" if brews else "")


@mcp.tool()
def save_recipe(name: str, recipe: RecipeIn, bean: Bean | None = None) -> str:
    """Validate a new recipe against the machine's limits and save it, linked to the beans it's for."""
    try:
        _to_recipe(name, recipe)
    except ValueError as exc:
        return f"Not saved. {exc}"
    row = store.save(name, _recipe_dict(recipe), (bean or Bean()).model_dump())
    return "Saved.\n\n" + _card(row)


@mcp.tool()
def update_recipe(recipe_id: int, recipe: RecipeIn, change_note: str,
                  name: str | None = None, bean: Bean | None = None) -> str:
    """Replace a saved recipe with an adjusted version (keeps history). change_note says what changed and why, e.g. 'grind 62→65, was bitter'."""
    current = store.get(recipe_id)
    if current is None:
        return f"No recipe #{recipe_id}."
    try:
        _to_recipe(name or current["name"], recipe)
    except ValueError as exc:
        return f"Not updated. {exc}"
    row = store.update(recipe_id, _recipe_dict(recipe), change_note,
                       bean.model_dump() if bean else None, name)
    return "Updated.\n\n" + _card(row)


@mcp.tool()
def delete_recipe(recipe_id: int) -> str:
    """Permanently delete a saved recipe. Confirm with the person first."""
    return "Deleted." if store.delete(recipe_id) else f"No recipe #{recipe_id}."


@mcp.tool()
async def machine_status() -> str:
    """Check whether the xBloom is reachable and what it's doing (idle, recipe loaded, brewing)."""
    s = await machine.status()
    if not s.get("reachable"):
        return s["error"]
    if s.get("brew"):
        return _brew_text(s["brew"])
    return f"Machine reachable. State: {s['state']}."


def _finish(st: BrewState) -> None:
    if last_brew_id is not None:
        store.finish_brew(last_brew_id, st.error or st.phase, st.water_g, st.coffee_g)


def _brew_text(b: dict) -> str:
    parts = [f"Brew of '{b['recipe']}': {b['phase']}"]
    if b["machine_state"]:
        parts.append(f"machine: {b['machine_state']}")
    if b["water_poured_g"] is not None:
        parts.append(f"water poured {b['water_poured_g']:g} of {b['target_water_ml']} ml")
    if b["coffee_in_cup_g"] is not None:
        parts.append(f"coffee in cup {b['coffee_in_cup_g']:g} g")
    parts.append(f"{b['elapsed_s']} s elapsed")
    text = " · ".join(parts)
    if b["machine_state"] == "awaiting_confirm" and b["elapsed_s"] > 90 and not b["done"]:
        text += "\nThe machine is waiting for confirmation: press its button to start the brew."
    if b["error"]:
        text += f"\n⚠️ {b['error']}"
    return text


@mcp.tool()
async def brew(recipe_id: int, confirmed_ready: bool) -> str:
    """Brew a saved recipe on the machine now. Pours near-boiling water.

    Only set confirmed_ready=true after the person has confirmed: water tank filled, the
    recipe's dose of whole beans weighed into the grinder, filter in the dripper, cup underneath.
    Returns immediately; call brew_status to follow progress.
    """
    global last_brew_id
    row = store.get(recipe_id)
    if row is None:
        return f"No recipe #{recipe_id}."
    dose = row["recipe"]["dose_g"]
    if not confirmed_ready:
        return (f"Not started. First ask them to confirm: water tank filled, **{dose} g of whole "
                f"beans weighed into the grinder**, filter in the dripper, cup underneath. Then "
                f"call brew again with confirmed_ready=true.")
    if not ADDRESS:
        return "XBLOOM_ADDRESS isn't configured on the server."
    if machine.busy:
        return "A brew is already running.\n" + _brew_text(machine.current.as_dict())  # type: ignore[union-attr]
    recipe = _to_recipe(row["name"], RecipeIn.model_validate(row["recipe"]))
    last_brew_id = store.log_brew(recipe_id, row["version"])
    machine.start_brew(recipe, _finish)
    return (f"Brewing '{row['name']}' ({dose} g, {recipe.total_water_ml} ml). The machine grinds "
            f"for ~20 s before pouring; the whole brew takes ~3 min. Call brew_status to follow it. "
            f"(brew #{last_brew_id})")


@mcp.tool()
async def brew_status() -> str:
    """Progress of the current or most recent brew: phase, water poured, coffee in the cup, errors."""
    if machine.current is None:
        return "No brew has been started since the server started."
    return _brew_text(machine.current.as_dict())


@mcp.tool()
async def cancel_brew() -> str:
    """Stop the machine immediately (abort a running brew or clear a loaded recipe)."""
    return await machine.cancel()


@mcp.tool()
def brew_feedback(feedback: str, brew_id: int | None = None) -> str:
    """Record how a brew tasted (defaults to the latest brew). Use it to guide update_recipe."""
    bid = brew_id or last_brew_id
    if bid is None:
        return "No brew to attach feedback to."
    store.brew_feedback(bid, feedback)
    return f"Noted on brew #{bid}."


def serve() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    secret = os.environ.get("XBLOOM_MCP_SECRET", "")
    if len(secret) < 24:
        raise SystemExit("Set XBLOOM_MCP_SECRET (24+ random chars); clients send it as a Bearer token.")
    hosts = [h.strip() for h in os.environ.get("XBLOOM_MCP_HOSTS", "").split(",") if h.strip()]
    port = int(os.environ.get("PORT", config.PORT))
    app = mcp.streamable_http_app(
        streamable_http_path="/mcp",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"127.0.0.1:{port}", f"localhost:{port}", *hosts],
            allowed_origins=["https://claude.ai", "https://claude.com"],
        ),
    )
    uvicorn.run(require_bearer(app, secret), host="127.0.0.1", port=port, log_level="warning")


def require_bearer(app, secret: str):
    """ASGI wrapper: reject any HTTP request without `Authorization: Bearer <secret>`.

    Unauthorised requests get a bare 404, so the endpoint doesn't advertise itself
    (and Claude doesn't mistake it for an OAuth server).
    """
    import hmac

    expected = f"Bearer {secret}".encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            auth = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(auth, expected):
                await send({"type": "http.response.start", "status": 404,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"Not Found"})
                return
        await app(scope, receive, send)

    return guarded
