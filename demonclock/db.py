"""SQLite persistence. The save file is the single source of truth (SPEC.md §0
pillar 2) — this module is the only place that reads/writes it.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DEFAULT_SAVE_PATH = "demonclock.save.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    state TEXT NOT NULL,
    tags TEXT NOT NULL,           -- JSON list
    last_event_day INTEGER NOT NULL,
    prices TEXT NOT NULL DEFAULT '{}'  -- JSON dict: good_id -> current price
);

CREATE TABLE IF NOT EXISTS links (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    travel_days INTEGER NOT NULL,
    status TEXT NOT NULL,
    block_reason TEXT,
    one_way INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id, direction)
);

CREATE TABLE IF NOT EXISTS player (
    id INTEGER PRIMARY KEY CHECK (id = 0),  -- single row
    name TEXT NOT NULL,
    location_id TEXT NOT NULL,
    hp INTEGER NOT NULL,
    hp_max INTEGER NOT NULL,
    mana INTEGER NOT NULL,
    mana_max INTEGER NOT NULL,
    strength INTEGER NOT NULL,
    magic INTEGER NOT NULL,
    agility INTEGER NOT NULL,
    defense INTEGER NOT NULL,
    charisma INTEGER NOT NULL,
    perception INTEGER NOT NULL,
    luck INTEGER NOT NULL,
    gold INTEGER NOT NULL,
    creative_mode_used INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS inventory (
    item_id TEXT NOT NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    sort_order INTEGER NOT NULL,
    data TEXT NOT NULL   -- JSON-encoded Skill.to_dict() (learned skills only;
                         -- the universal BASIC_ATTACK is never persisted)
);

CREATE TABLE IF NOT EXISTS scheduled_events (
    sort_order INTEGER NOT NULL,
    data TEXT NOT NULL   -- JSON-encoded ScheduledEvent.to_dict()
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

SAVE_VERSION = "1"


def connect(path: str | Path = DEFAULT_SAVE_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def has_save(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT 1 FROM meta WHERE key = 'save_version'").fetchone()
    return row is not None


def save_game(conn: sqlite3.Connection, world, player, clock) -> None:
    """Serialize World + Player + Clock into the save file. Full overwrite —
    this is a save-game snapshot, not an incremental log."""
    from .models import InventoryItem  # local import avoids a cycle at module load

    conn.execute("DELETE FROM nodes")
    conn.execute("DELETE FROM links")
    conn.execute("DELETE FROM player")
    conn.execute("DELETE FROM inventory")
    conn.execute("DELETE FROM skills")
    conn.execute("DELETE FROM scheduled_events")

    for node in world.nodes.values():
        conn.execute(
            "INSERT INTO nodes (id, name, type, state, tags, last_event_day, prices) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (node.id, node.name, node.type, node.state, json.dumps(node.tags), node.last_event_day,
             json.dumps(node.prices)),
        )

    for link in world.all_links():
        conn.execute(
            "INSERT INTO links (from_id, to_id, direction, travel_days, status, "
            "block_reason, one_way) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                link.from_id,
                link.to_id,
                link.direction,
                link.travel_days,
                link.status,
                link.block_reason,
                int(link.one_way),
            ),
        )

    conn.execute(
        "INSERT INTO player (id, name, location_id, hp, hp_max, mana, mana_max, "
        "strength, magic, agility, defense, charisma, perception, luck, gold, "
        "creative_mode_used) VALUES (0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            player.name,
            player.location_id,
            player.hp,
            player.hp_max,
            player.mana,
            player.mana_max,
            player.strength,
            player.magic,
            player.agility,
            player.defense,
            player.charisma,
            player.perception,
            player.luck,
            player.gold,
            int(player.creative_mode_used),
        ),
    )
    for item in player.inventory:
        conn.execute(
            "INSERT INTO inventory (item_id, name, quantity) VALUES (?, ?, ?)",
            (item.item_id, item.name, item.quantity),
        )
    for sort_order, skill in enumerate(player.skills):
        conn.execute(
            "INSERT INTO skills (sort_order, data) VALUES (?, ?)",
            (sort_order, json.dumps(skill.to_dict())),
        )
    for sort_order, event in enumerate(world.scheduled_events):
        conn.execute(
            "INSERT INTO scheduled_events (sort_order, data) VALUES (?, ?)",
            (sort_order, json.dumps(event.to_dict())),
        )

    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('current_day', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(clock.current_day),),
    )
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('save_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (SAVE_VERSION,),
    )
    conn.commit()


def load_game(conn: sqlite3.Connection):
    """Returns (World, Player, Clock) rebuilt from the save file, or None if
    no save exists yet."""
    from .clock import Clock
    from .events import ScheduledEvent
    from .models import InventoryItem, Link, Node, Player
    from .skills import Skill
    from .world import World

    if not has_save(conn):
        return None

    world = World()
    for row in conn.execute("SELECT id, name, type, state, tags, last_event_day, prices FROM nodes"):
        world.nodes[row[0]] = Node(
            id=row[0], name=row[1], type=row[2], state=row[3],
            tags=json.loads(row[4]), last_event_day=row[5], prices=json.loads(row[6]),
        )
    for row in conn.execute(
        "SELECT from_id, to_id, direction, travel_days, status, block_reason, one_way FROM links"
    ):
        link = Link(
            from_id=row[0], to_id=row[1], direction=row[2], travel_days=row[3],
            status=row[4], block_reason=row[5], one_way=bool(row[6]),
        )
        world.links.setdefault(link.from_id, []).append(link)
    world.scheduled_events = [
        ScheduledEvent.from_dict(json.loads(r[0]))
        for r in conn.execute("SELECT data FROM scheduled_events ORDER BY sort_order")
    ]

    prow = conn.execute(
        "SELECT name, location_id, hp, hp_max, mana, mana_max, strength, magic, "
        "agility, defense, charisma, perception, luck, gold, creative_mode_used "
        "FROM player WHERE id = 0"
    ).fetchone()
    inventory = [
        InventoryItem(item_id=r[0], name=r[1], quantity=r[2])
        for r in conn.execute("SELECT item_id, name, quantity FROM inventory")
    ]
    skills = [
        Skill.from_dict(json.loads(r[0]))
        for r in conn.execute("SELECT data FROM skills ORDER BY sort_order")
    ]
    player = Player(
        name=prow[0], location_id=prow[1], hp=prow[2], hp_max=prow[3],
        mana=prow[4], mana_max=prow[5], strength=prow[6], magic=prow[7],
        agility=prow[8], defense=prow[9], charisma=prow[10], perception=prow[11],
        luck=prow[12], gold=prow[13], inventory=inventory, skills=skills,
        creative_mode_used=bool(prow[14]),
    )

    day_row = conn.execute("SELECT value FROM meta WHERE key = 'current_day'").fetchone()
    clock = Clock(current_day=int(day_row[0]) if day_row else 0)

    return world, player, clock
