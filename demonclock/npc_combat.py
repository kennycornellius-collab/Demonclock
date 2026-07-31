"""Chunk A of "faction standing: combat trigger" (updates.md, resolved
2026-07-31) — the foundation that makes an NPC a legitimate combat target.
No UI wiring, no killing, no standing changes yet (Chunks B/C); this is
purely the "what stats does this NPC fight with" primitive those later
chunks build on.

Mirrors enemies.py's own make_enemy shape deliberately: a small
hand-authored table, not per-instance stored data — an NPC (models.NPC)
still carries no HP/combat fields of its own. Combat stats are resolved
fresh from the archetype every time a fight starts, exactly like
enemies.make_enemy resolves a fresh full-HP Combatant from ENEMY_TEMPLATES
every time, rather than persisting mid-fight state (Step 10 Stage 6's own
respawn precedent).

Deliberately keyed off the EXISTING NPC.tags field rather than a new NPC
attribute — "merchant"/"guard" are already real tags in seed.py's starter
content (Hana the Miller, Warden Oskar), so this pays off immediately with
zero seed.py changes. generation/npc.py's schema (Chunk C) will constrain
an AI-generated NPC's archetype tag to this same enum, never free text —
same discipline skills.EffectKind/events.EventKind already enforce.
"""
from __future__ import annotations

from enum import Enum

from .combat import Combatant
from .models import NPC


class NPCArchetype(str, Enum):
    CIVILIAN = "civilian"
    MERCHANT = "merchant"
    GUARD = "guard"
    WARRIOR = "warrior"


# Hand-authored, small by design (same "start rough, calibrate by feel"
# status as enemies.py's own _ENEMY_TEMPLATES, SPEC.md §11) — CIVILIAN is
# deliberately the weakest entry, since it's also the fallback for an
# untagged/unmatched NPC below.
_ARCHETYPE_STATS: dict[NPCArchetype, dict] = {
    NPCArchetype.CIVILIAN: dict(hp_max=15, strength=3, agility=5, defense=1),
    NPCArchetype.MERCHANT: dict(hp_max=20, strength=5, agility=6, defense=2),
    NPCArchetype.GUARD: dict(hp_max=40, strength=12, agility=8, defense=6),
    NPCArchetype.WARRIOR: dict(hp_max=60, strength=18, agility=10, defense=8),
}

# Checked in this fixed strongest-first order against NPC.tags — an NPC
# hypothetically tagged with more than one archetype word (e.g. a retired
# "guard" who's now mostly a "merchant") resolves to the stronger, more
# specific archetype rather than depending on tag-list authoring order.
_ARCHETYPE_PRIORITY = [
    NPCArchetype.WARRIOR, NPCArchetype.GUARD, NPCArchetype.MERCHANT, NPCArchetype.CIVILIAN,
]


def archetype_for(npc: NPC) -> NPCArchetype:
    """Scans npc.tags for a known archetype value, strongest match first.
    An untagged NPC, or one whose tags name no real archetype (most flavor
    tags, e.g. "villager"/"retired", aren't archetypes at all), falls back
    to the weakest entry, CIVILIAN — never an error, since NPC.tags is
    ordinary free-authored flavor text most of the time."""
    tag_set = set(npc.tags)
    for archetype in _ARCHETYPE_PRIORITY:
        if archetype.value in tag_set:
            return archetype
    return NPCArchetype.CIVILIAN


def combatant_for_npc(npc: NPC) -> Combatant:
    """Builds a fresh, full-HP Combatant for `npc` from its resolved
    archetype — the same shape enemies.make_enemy already returns for a
    wild foe, so an NPC fight (Chunk B) reuses combat.run_group_combat/
    apply_skill completely unchanged, no NPC-specific combat code path.
    Luck defaults to 0 (Combatant's own default) — same "start rough"
    status as every enemy/boss/add today: an NPC never crits either."""
    stats = _ARCHETYPE_STATS[archetype_for(npc)]
    return Combatant(
        name=npc.name,
        hp=stats["hp_max"],
        hp_max=stats["hp_max"],
        strength=stats["strength"],
        agility=stats["agility"],
        defense=stats["defense"],
    )
