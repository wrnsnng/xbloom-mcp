"""SQLite recipe library: beans plus the recipe tuned for them, with version history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    roaster     TEXT,
    bean        TEXT,
    origin      TEXT,
    process     TEXT,
    roast_level TEXT,
    tasting_notes TEXT,
    source      TEXT,
    recipe_json TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    recipe_json TEXT NOT NULL,
    change_note TEXT,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS brews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    recipe_id   INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    version     INTEGER,
    started_at  TEXT NOT NULL,
    outcome     TEXT,
    water_g     REAL,
    coffee_g    REAL,
    feedback    TEXT
);
"""

BEAN_FIELDS = ("roaster", "bean", "origin", "process", "roast_level", "tasting_notes", "source")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def _row(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        d["recipe"] = json.loads(d.pop("recipe_json"))
        return d

    def save(self, name: str, recipe: dict[str, Any], bean: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        cols = {k: bean.get(k) for k in BEAN_FIELDS}
        cur = self.db.execute(
            f"INSERT INTO recipes (name, {', '.join(cols)}, recipe_json, created_at, updated_at)"
            f" VALUES (?, {', '.join('?' * len(cols))}, ?, ?, ?)",
            (name, *cols.values(), json.dumps(recipe), now, now),
        )
        rid = cur.lastrowid
        self.db.execute(
            "INSERT INTO recipe_history (recipe_id, version, recipe_json, change_note, created_at)"
            " VALUES (?, 1, ?, 'created', ?)",
            (rid, json.dumps(recipe), now),
        )
        self.db.commit()
        return self.get(rid)  # type: ignore[return-value]

    def update(self, rid: int, recipe: dict[str, Any], change_note: str,
               bean: dict[str, Any] | None = None, name: str | None = None) -> dict[str, Any]:
        current = self.get(rid)
        if current is None:
            raise KeyError(rid)
        version = current["version"] + 1
        now = _now()
        sets = {"recipe_json": json.dumps(recipe), "version": version, "updated_at": now}
        if name:
            sets["name"] = name
        for k in BEAN_FIELDS:
            if bean and bean.get(k) is not None:
                sets[k] = bean[k]
        self.db.execute(
            f"UPDATE recipes SET {', '.join(f'{k} = ?' for k in sets)} WHERE id = ?",
            (*sets.values(), rid),
        )
        self.db.execute(
            "INSERT INTO recipe_history (recipe_id, version, recipe_json, change_note, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (rid, version, json.dumps(recipe), change_note, now),
        )
        self.db.commit()
        return self.get(rid)  # type: ignore[return-value]

    def get(self, rid: int) -> dict[str, Any] | None:
        return self._row(self.db.execute("SELECT * FROM recipes WHERE id = ?", (rid,)).fetchone())

    def delete(self, rid: int) -> bool:
        cur = self.db.execute("DELETE FROM recipes WHERE id = ?", (rid,))
        self.db.commit()
        return cur.rowcount > 0

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM recipes ORDER BY updated_at DESC").fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def search(self, query: str) -> list[dict[str, Any]]:
        """Match every word of `query` against name and bean fields (case-insensitive)."""
        words = [w for w in query.lower().split() if w]
        if not words:
            return self.list()
        hay = "lower(coalesce(name,'') || ' ' || " + " || ' ' || ".join(
            f"coalesce({k},'')" for k in BEAN_FIELDS) + ")"
        sql = "SELECT * FROM recipes WHERE " + " AND ".join(f"{hay} LIKE ?" for _ in words)
        rows = self.db.execute(sql + " ORDER BY updated_at DESC",
                               [f"%{w}%" for w in words]).fetchall()
        return [self._row(r) for r in rows]  # type: ignore[misc]

    def history(self, rid: int) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT version, change_note, created_at FROM recipe_history"
            " WHERE recipe_id = ? ORDER BY version", (rid,)).fetchall()
        return [dict(r) for r in rows]

    def log_brew(self, recipe_id: int | None, version: int | None) -> int:
        cur = self.db.execute(
            "INSERT INTO brews (recipe_id, version, started_at) VALUES (?, ?, ?)",
            (recipe_id, version, _now()))
        self.db.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def finish_brew(self, brew_id: int, outcome: str, water_g: float | None,
                    coffee_g: float | None) -> None:
        self.db.execute("UPDATE brews SET outcome = ?, water_g = ?, coffee_g = ? WHERE id = ?",
                        (outcome, water_g, coffee_g, brew_id))
        self.db.commit()

    def brew_feedback(self, brew_id: int, feedback: str) -> None:
        self.db.execute("UPDATE brews SET feedback = ? WHERE id = ?", (feedback, brew_id))
        self.db.commit()

    def recent_brews(self, recipe_id: int, limit: int = 5) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, version, started_at, outcome, water_g, coffee_g, feedback FROM brews"
            " WHERE recipe_id = ? ORDER BY id DESC LIMIT ?", (recipe_id, limit)).fetchall()
        return [dict(r) for r in rows]
