"""Player-authored skills + the enumerated `effects` vocabulary (SPEC.md §6b).

Effects are composed from a FIXED enumerated set — never free text, never
LLM-adjudicated (SPEC.md §13). This is the hard exploit boundary of the whole
design: a player can compose damage+dot+lifesteal, but can never invent a new
verb like "enemy can never act."

Skill creation is unrestricted BY DESIGN (§6b) — nothing here blocks a skill
from existing; a 0-mana huge-damage skill is legal, an intentional opt-out.
`validate_skill` only guards the enum boundary itself (a BUFF/DEBUFF must name
a real stat) — a structural requirement, not a balance judgement.

The runtime skill-AUTHORING UI, the fair-cost calculator, and the
`creative_mode_used` flag are Stage 3 (see CLAUDE.md "Build progress").
`Skill.computed_fair_cost` exists as a field now so persistence doesn't need
to change shape when Stage 3 fills it in.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EffectKind(str, Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    STUN = "stun"
    DOT = "dot"
    LIFESTEAL = "lifesteal"
    SHIELD = "shield"
    BUFF = "buff"
    DEBUFF = "debuff"
    CLEANSE = "cleanse"
    AOE = "aoe"
    KNOCKBACK = "knockback"
    TAUNT = "taunt"


# Mechanically inert this build stage — AOE/KNOCKBACK/TAUNT need multi-enemy or
# positional combat that doesn't exist yet. Legal to compose (never rejected);
# they just log a flavor line instead of faking a mechanic (SPEC.md §12 build
# progress / progress.md for this stage).
INERT_EFFECTS = frozenset({EffectKind.AOE, EffectKind.KNOCKBACK, EffectKind.TAUNT})


class StatType(str, Enum):
    STRENGTH = "strength"
    MAGIC = "magic"
    AGILITY = "agility"
    DEFENSE = "defense"


@dataclass
class Effect:
    kind: EffectKind
    stat: StatType | None = None  # required for BUFF/DEBUFF, unused otherwise

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "stat": self.stat.value if self.stat else None}

    @classmethod
    def from_dict(cls, data: dict) -> "Effect":
        return cls(
            kind=EffectKind(data["kind"]),
            stat=StatType(data["stat"]) if data.get("stat") else None,
        )


@dataclass
class Skill:
    id: str
    name: str
    effects: list[Effect]
    attribute_type: StatType = StatType.STRENGTH
    description: str = ""
    mana_cost: int = 0
    base_damage: int = 0
    attribute_multiplier: float = 1.0
    cooldown: int = 0
    cast_time: int = 0  # multi-turn casting — a stored field, inert this stage
    computed_fair_cost: int = 0  # filled in by Stage 3's fair-cost calculator

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "mana_cost": self.mana_cost,
            "base_damage": self.base_damage,
            "attribute_type": self.attribute_type.value,
            "attribute_multiplier": self.attribute_multiplier,
            "effects": [e.to_dict() for e in self.effects],
            "cooldown": self.cooldown,
            "cast_time": self.cast_time,
            "computed_fair_cost": self.computed_fair_cost,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Skill":
        return cls(
            id=data["id"],
            name=data["name"],
            description=data.get("description", ""),
            mana_cost=data["mana_cost"],
            base_damage=data["base_damage"],
            attribute_type=StatType(data["attribute_type"]),
            attribute_multiplier=data["attribute_multiplier"],
            effects=[Effect.from_dict(e) for e in data["effects"]],
            cooldown=data["cooldown"],
            cast_time=data["cast_time"],
            computed_fair_cost=data.get("computed_fair_cost", 0),
        )


class SkillError(ValueError):
    pass


def validate_skill(skill: Skill) -> None:
    """Guards the enum boundary — NOT a balance/power check. Skill creation is
    never blocked by power level (SPEC.md §6b); this only rejects a
    structurally malformed effect (a BUFF/DEBUFF with no target stat)."""
    for effect in skill.effects:
        if effect.kind in (EffectKind.BUFF, EffectKind.DEBUFF) and effect.stat is None:
            raise SkillError(f"{effect.kind.value} effect on {skill.name!r} requires a stat")


BASIC_ATTACK = Skill(
    id="basic_attack",
    name="Basic Attack",
    description="A plain strike. Always available, costs nothing.",
    effects=[Effect(EffectKind.DAMAGE)],
    attribute_type=StatType.STRENGTH,
    base_damage=20,
    attribute_multiplier=1.0,
    mana_cost=0,
    cooldown=0,
)


def starter_skills() -> list[Skill]:
    """A few composed examples proving the vocabulary — not balanced content,
    just enough to demonstrate composition. Returns a fresh list each call so
    callers (new_player) don't share a mutable list across players. The
    Skill objects themselves are never mutated during play, so sharing those
    instances is fine.
    """
    return [
        Skill(
            id="firebolt",
            name="Firebolt",
            description="A searing bolt that keeps burning.",
            effects=[Effect(EffectKind.DAMAGE), Effect(EffectKind.DOT)],
            attribute_type=StatType.MAGIC,
            base_damage=15,
            attribute_multiplier=1.2,
            mana_cost=8,
            cooldown=1,
        ),
        Skill(
            id="mend",
            name="Mend",
            description="Knit your wounds shut.",
            effects=[Effect(EffectKind.HEAL)],
            attribute_type=StatType.MAGIC,
            base_damage=20,
            attribute_multiplier=1.0,
            mana_cost=10,
            cooldown=2,
        ),
        Skill(
            id="guard",
            name="Guard",
            description="Brace behind a barrier of will.",
            effects=[Effect(EffectKind.SHIELD)],
            attribute_type=StatType.DEFENSE,
            base_damage=10,
            attribute_multiplier=1.0,
            mana_cost=6,
            cooldown=2,
        ),
        Skill(
            id="focus",
            name="Focus",
            description="Steel yourself for the fight ahead.",
            effects=[Effect(EffectKind.BUFF, stat=StatType.STRENGTH)],
            attribute_type=StatType.STRENGTH,
            base_damage=5,
            attribute_multiplier=1.0,
            mana_cost=5,
            cooldown=3,
        ),
    ]
