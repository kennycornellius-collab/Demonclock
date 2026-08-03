"""Player-authored skills + the enumerated `effects` vocabulary.

Effects are composed from a FIXED enumerated set — never free text, never
LLM-adjudicated. This is the hard exploit boundary of the whole
design: a player can compose damage+dot+lifesteal, but can never invent a new
verb like "enemy can never act."

Skill creation is unrestricted BY DESIGN (§6b) — nothing here blocks a skill
from existing; a 0-mana huge-damage skill is legal, an intentional opt-out.
`validate_skill` only guards the enum boundary itself (a BUFF/DEBUFF must name
a real stat) — a structural requirement, not a balance judgement.

`compute_fair_cost` is the Stage 3 fair-cost calculator: it turns a skill's
power dials (magnitude + composed effects) into an engine-suggested MANA/
cooldown/cast-time. Accepting it keeps a skill balanced; undercutting it on
any dimension (`is_underpriced`) is the deliberate "cost-zeroing act" that
opts a save into creative mode when the skill is actually cast (see
`combat.run_combat`) — never a rejection, since creation stays unblocked.
"""
from __future__ import annotations

import math
import re
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


# AOE and KNOCKBACK got real implementations in Step 10 Stage 6
# now that multi-enemy ordinary combat exists to give them a
# target — see combat.apply_skill. TAUNT stays here, still legal to compose
# (never rejected) but mechanically inert: this game has exactly one
# player-side combatant, so there's no ally for an enemy's attack to be
# redirected FROM — a real "force enemies to target the caster instead"
# mechanic has nothing to redirect away from, since the player is already the
# only thing any enemy can ever target. A genuine future extension (a party
# system, or enemies that can target something other than the player) would
# be what finally gives this one somewhere to go.
INERT_EFFECTS = frozenset({EffectKind.TAUNT})


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
    computed_fair_cost: int = 0  # the fair MANA cost at authoring time (see compute_fair_cost)
    # "Skills grow with use" (resolved 2026-07-31): how many
    # times this skill has been successfully cast by its owning player,
    # never an enemy/boss cast (see combat.run_group_combat/boss.
    # run_encounter, the only two places that ever increment this).
    # Magnitude-only growth reads this via compute_grown_magnitude at CAST
    # time — mana_cost/cooldown/cast_time above are never touched by it, so
    # a grown skill is only ever stronger, never cheaper to spam. Stays 0
    # forever for a skill that is_underpriced (creative_mode_used territory)
    # — see the increment call sites for why. BASIC_ATTACK (a shared
    # singleton, never persisted) never has this incremented either.
    use_count: int = 0

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
            "use_count": self.use_count,
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
            use_count=data.get("use_count", 0),
        )


class SkillError(ValueError):
    pass


def compute_magnitude(base_damage: int, attribute_multiplier: float, stat_value: int) -> int:
    """The damage formula: `(base_damage * attribute_multiplier) +
    attribute_value`. Single source of truth for "how strong is this skill" —
    both `combat.apply_skill`'s live casts and the fair-cost calculator below
    derive a skill's power from this one formula, so they can never drift."""
    return int(base_damage * attribute_multiplier) + stat_value


# "Skills grow with use" (resolved 2026-07-31): sqrt(use_count)
# gives deliberately UNCAPPED diminishing returns — the user's own framing
# was "the stronger you are, the harder it is to become even stronger," not
# a hard ceiling, so this is not clamped like CRIT_CAP/DODGE_CAP elsewhere.
# Placeholder number — same "start rough, calibrate by feel" status as
# EFFECT_POWER_WEIGHT/MANA_PER_POWER above.
GROWTH_PER_SQRT_USE = 0.05


def compute_grown_magnitude(base_magnitude: int, use_count: int) -> int:
    """Applies a skill's accumulated use-based growth bonus ON TOP OF an
    already-computed base magnitude (`compute_magnitude`'s own output) —
    called only by `combat.apply_skill` at CAST time, never by
    `compute_fair_cost`, whose whole job is pricing a skill's UN-grown,
    as-authored power. That separation is what keeps growth magnitude-only:
    a skill's mana_cost/cooldown were priced fairly against its base power
    once at creation and never get re-priced as it grows, so growth can
    only ever make a skill hit harder, never cheaper to spam.

    Multiplicative (not a flat bonus) so a powerful skill grows in absolute
    terms proportionally to a weak one, scaled by sqrt(use_count) for
    uncapped diminishing returns. use_count <= 0 (never cast, or a skill
    excluded from growth because is_underpriced was True -- see combat.py's
    increment call sites) returns base_magnitude completely unchanged."""
    if use_count <= 0:
        return base_magnitude
    return round(base_magnitude * (1.0 + GROWTH_PER_SQRT_USE * math.sqrt(use_count)))


# Relative "how strong is this effect" weights feeding the fair-cost formula.
# Placeholder numbers — same status as combat.py's DOT_DURATION/STUN_DURATION/
# etc: start rough, calibrate by feel. Control/utility effects
# (STUN, CLEANSE) don't actually scale with magnitude in combat.py today (a
# stun is a fixed duration regardless of power) — they're still priced off
# magnitude here because a caster's own stat already sets a magnitude floor,
# and a flat per-effect price would let a 0-power skill make them free.
EFFECT_POWER_WEIGHT: dict[EffectKind, float] = {
    EffectKind.DAMAGE: 1.0,
    EffectKind.HEAL: 1.0,
    EffectKind.LIFESTEAL: 0.5,
    EffectKind.SHIELD: 1.0,
    EffectKind.STUN: 1.2,
    EffectKind.DOT: 0.8,
    EffectKind.BUFF: 0.7,
    EffectKind.DEBUFF: 0.7,
    EffectKind.CLEANSE: 0.4,
    EffectKind.AOE: 0.3,
    EffectKind.KNOCKBACK: 0.2,
    EffectKind.TAUNT: 0.2,
}

MANA_PER_POWER = 0.35
COOLDOWN_PER_POWER = 0.05
CAST_TIME_PER_POWER = 0.02


@dataclass
class FairCost:
    mana_cost: int
    cooldown: int
    cast_time: int


def compute_fair_cost(effects: list[Effect], magnitude: int) -> FairCost:
    """The Stage 3 fair-cost calculator: turns a skill's power
    (its effects composed + how hard they'll hit, per `compute_magnitude`)
    into an engine-suggested MANA/cooldown/cast-time. A skill with no effects
    does nothing, so it's fairly free. This never blocks anything — it's a
    suggestion the authoring flow shows the player, who may accept it or
    undercut it (see `is_underpriced`)."""
    power = magnitude * sum(EFFECT_POWER_WEIGHT[effect.kind] for effect in effects)
    return FairCost(
        mana_cost=max(0, round(power * MANA_PER_POWER)),
        cooldown=max(0, round(power * COOLDOWN_PER_POWER)),
        cast_time=max(0, round(power * CAST_TIME_PER_POWER)),
    )


def is_underpriced(skill: Skill, fair: FairCost) -> bool:
    """True if `skill`'s actual cost undercuts the engine's fair suggestion on
    any dimension — the deliberate "cost-zeroing act" this design treats as
    the opt-out gesture into creative mode. Never a rejection: creation stays
    unblocked regardless of what this returns (see `combat.run_combat` for
    where this actually flips `Player.creative_mode_used`, at CAST time, not
    creation time)."""
    return (
        skill.mana_cost < fair.mana_cost
        or skill.cooldown < fair.cooldown
        or skill.cast_time < fair.cast_time
    )


def generate_skill_id(name: str, existing_ids: set[str]) -> str:
    """Slugifies `name` into a unique skill id, deduping against
    `existing_ids` (the caller passes the player's current skill ids plus the
    reserved `"basic_attack"` id)."""
    base = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "skill"
    candidate = base
    suffix = 2
    while candidate in existing_ids:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


def validate_skill(skill: Skill) -> None:
    """Guards the enum boundary — NOT a balance/power check. Skill creation is
    never blocked by power level; this only rejects a
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
