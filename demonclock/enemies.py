"""Small hand-authored enemy table — mirrors seed.py's pattern. Real enemy
content is generated later (SPEC.md §12 steps 4-5); this is just enough to
fight something in this build stage.
"""
from __future__ import annotations

from .combat import Combatant

_ENEMY_TEMPLATES: dict[str, dict] = {
    "bramblewood_wolf": dict(name="Bramblewood Wolf", hp_max=30, strength=8, agility=12, defense=2),
}


def make_enemy(enemy_id: str) -> Combatant:
    template = _ENEMY_TEMPLATES[enemy_id]
    return Combatant(
        name=template["name"],
        hp=template["hp_max"],
        hp_max=template["hp_max"],
        strength=template["strength"],
        agility=template["agility"],
        defense=template["defense"],
    )
