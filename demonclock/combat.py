"""Turn-based combat (SPEC.md §6b) — skill-based since Stage 2, with Stage 3's
fair-cost check wired in: the moment the player CASTS a learned skill whose
actual cost undercuts `skills.compute_fair_cost` on any dimension, this sets
`Player.creative_mode_used` (never at authoring time — see skills.py).

Deterministic on purpose, still: no damage variance, no dodge, no crit. RNG
is planned for a later combat stage — see SPEC.md §6b's forward-note.

Effect targeting is a fixed default this stage (no ally/multi-enemy selection
UI exists yet): harmful effects (damage/stun/dot/debuff) hit the opponent;
beneficial effects (heal/lifesteal/shield/buff/cleanse) apply to the caster.
AOE/KNOCKBACK/TAUNT are legal but mechanically inert (see skills.INERT_EFFECTS)
until multi-enemy/positional combat exists.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from . import behavior, setback
from .models import Player
from .skills import (
    BASIC_ATTACK,
    Effect,
    EffectKind,
    INERT_EFFECTS,
    Skill,
    StatType,
    compute_fair_cost,
    compute_magnitude,
    is_underpriced,
)

# Placeholder tuning constants — same status as the fair-cost curve (SPEC.md
# §11: "start rough, calibrate by feel").
DOT_DURATION = 3
STUN_DURATION = 1
BUFF_DEBUFF_DURATION = 3
LIFESTEAL_FRACTION = 0.5

_EFFECT_ORDER = [
    EffectKind.DAMAGE, EffectKind.HEAL, EffectKind.LIFESTEAL, EffectKind.SHIELD,
    EffectKind.STUN, EffectKind.DOT, EffectKind.BUFF, EffectKind.DEBUFF,
    EffectKind.CLEANSE, EffectKind.AOE, EffectKind.KNOCKBACK, EffectKind.TAUNT,
]
_EFFECT_PRIORITY = {kind: i for i, kind in enumerate(_EFFECT_ORDER)}


class CombatResult(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    FLED = "fled"


@dataclass
class StatModifier:
    stat: StatType
    amount: int  # positive for a buff, negative for a debuff
    turns_remaining: int


@dataclass
class Combatant:
    name: str
    hp: int
    hp_max: int
    strength: int
    agility: int
    defense: int
    magic: int = 0
    mana: int = 0
    mana_max: int = 0
    skills: list[Skill] = field(default_factory=list)
    shield: int = 0
    stun_turns: int = 0
    dot_damage: int = 0
    dot_turns_remaining: int = 0
    modifiers: list[StatModifier] = field(default_factory=list)
    cooldowns: dict[str, int] = field(default_factory=dict)  # skill id -> turns left

    @classmethod
    def from_player(cls, player: Player) -> "Combatant":
        return cls(
            name=player.name,
            hp=player.hp,
            hp_max=player.hp_max,
            strength=player.strength,
            agility=player.agility,
            defense=player.defense,
            magic=player.magic,
            mana=player.mana,
            mana_max=player.mana_max,
            skills=list(player.skills),
        )


_BASE_STAT = {
    StatType.STRENGTH: lambda c: c.strength,
    StatType.MAGIC: lambda c: c.magic,
    StatType.AGILITY: lambda c: c.agility,
    StatType.DEFENSE: lambda c: c.defense,
}


def effective_stat(combatant: Combatant, stat: StatType) -> int:
    """Base stat plus any active buff/debuff modifiers, floored at 0."""
    base = _BASE_STAT[stat](combatant)
    delta = sum(m.amount for m in combatant.modifiers if m.stat is stat)
    return max(0, base + delta)


def _magnitude(caster: Combatant, skill: Skill) -> int:
    """SPEC.md §6b damage formula, generalized: every effect on a skill draws
    from the same power budget rather than each having its own tunable
    number — keeps the schema close to what SPEC.md §6b actually specifies."""
    return compute_magnitude(skill.base_damage, skill.attribute_multiplier, effective_stat(caster, skill.attribute_type))


def _deal_damage(caster: Combatant, target: Combatant, magnitude: int, skill: Skill, log: list[str]) -> int:
    mitigated = max(1, magnitude - effective_stat(target, StatType.DEFENSE))
    absorbed = min(target.shield, mitigated)
    target.shield -= absorbed
    remaining = mitigated - absorbed
    target.hp = max(0, target.hp - remaining)
    if absorbed:
        log.append(f"{target.name}'s shield absorbs {absorbed} damage.")
    log.append(
        f"{caster.name} hits {target.name} with {skill.name} for {remaining} damage. "
        f"({target.hp}/{target.hp_max} HP left)"
    )
    return remaining


def apply_skill(caster: Combatant, opponent: Combatant, skill: Skill, log: list[str]) -> None:
    """Resolves every effect on `skill` in a fixed canonical order (not
    authoring order) so cross-effect dependencies — e.g. LIFESTEAL needs
    DAMAGE's result — are always well-defined regardless of how the skill's
    effects list was composed."""
    magnitude = _magnitude(caster, skill)
    dealt = 0

    for effect in sorted(skill.effects, key=lambda e: _EFFECT_PRIORITY[e.kind]):
        if effect.kind is EffectKind.DAMAGE:
            dealt = _deal_damage(caster, opponent, magnitude, skill, log)

        elif effect.kind is EffectKind.HEAL:
            healed = min(magnitude, caster.hp_max - caster.hp)
            caster.hp += healed
            log.append(f"{caster.name} heals for {healed} HP. ({caster.hp}/{caster.hp_max})")

        elif effect.kind is EffectKind.LIFESTEAL:
            stolen = int(dealt * LIFESTEAL_FRACTION)
            if stolen > 0:
                healed = min(stolen, caster.hp_max - caster.hp)
                caster.hp += healed
                log.append(f"{caster.name} drains {healed} HP from the strike. ({caster.hp}/{caster.hp_max})")

        elif effect.kind is EffectKind.SHIELD:
            caster.shield += magnitude
            log.append(f"{caster.name} raises a shield absorbing {magnitude} damage.")

        elif effect.kind is EffectKind.STUN:
            opponent.stun_turns += STUN_DURATION
            log.append(f"{opponent.name} is stunned!")

        elif effect.kind is EffectKind.DOT:
            opponent.dot_damage = max(1, magnitude // 2)
            opponent.dot_turns_remaining = DOT_DURATION
            log.append(f"{opponent.name} is afflicted with a lingering wound.")

        elif effect.kind is EffectKind.BUFF:
            caster.modifiers.append(StatModifier(stat=effect.stat, amount=magnitude, turns_remaining=BUFF_DEBUFF_DURATION))
            log.append(f"{caster.name}'s {effect.stat.value} rises.")

        elif effect.kind is EffectKind.DEBUFF:
            opponent.modifiers.append(StatModifier(stat=effect.stat, amount=-magnitude, turns_remaining=BUFF_DEBUFF_DURATION))
            log.append(f"{opponent.name}'s {effect.stat.value} falls.")

        elif effect.kind is EffectKind.CLEANSE:
            caster.dot_damage = 0
            caster.dot_turns_remaining = 0
            caster.stun_turns = 0
            before = len(caster.modifiers)
            caster.modifiers = [m for m in caster.modifiers if m.amount > 0]
            if len(caster.modifiers) < before:
                log.append(f"{caster.name} shakes off the negative effects.")

        elif effect.kind in INERT_EFFECTS:
            log.append(f"{skill.name}'s {effect.kind.value} has no target here yet.")


def tick_upkeep(combatant: Combatant, log: list[str]) -> bool:
    """Runs at the start of `combatant`'s turn: DOT damage, modifier/cooldown
    countdown. Returns True if a stun consumes this turn (caller should skip
    the action)."""
    if combatant.dot_turns_remaining > 0:
        combatant.hp = max(0, combatant.hp - combatant.dot_damage)
        combatant.dot_turns_remaining -= 1
        log.append(
            f"{combatant.name} suffers {combatant.dot_damage} lingering damage. "
            f"({combatant.hp}/{combatant.hp_max} HP left)"
        )

    for modifier in combatant.modifiers:
        modifier.turns_remaining -= 1
    combatant.modifiers = [m for m in combatant.modifiers if m.turns_remaining > 0]

    combatant.cooldowns = {
        skill_id: turns - 1 for skill_id, turns in combatant.cooldowns.items() if turns - 1 > 0
    }

    if combatant.stun_turns > 0:
        combatant.stun_turns -= 1
        log.append(f"{combatant.name} is stunned and loses their turn.")
        return True
    return False


def usable_skills(combatant: Combatant) -> list[Skill]:
    """Basic Attack is always free and available; learned skills need
    affordable mana and to be off cooldown."""
    return [BASIC_ATTACK] + [
        skill for skill in combatant.skills
        if skill.mana_cost <= combatant.mana and skill.id not in combatant.cooldowns
    ]


def turn_order(player: Combatant, enemy: Combatant) -> list[str]:
    """AGILITY descending; ties favor the player (deterministic, no RNG this
    stage). Fixed once at the start of the fight — a mid-fight AGILITY buff
    doesn't re-order turns this stage (noted, same as the RNG deferral)."""
    return ["enemy", "player"] if enemy.agility > player.agility else ["player", "enemy"]


def run_combat(
    player: Player,
    enemy: Combatant,
    choose_action: Callable[[Combatant, Combatant, list[Skill]], Skill | None],
    current_day: int = 0,
) -> tuple[CombatResult, list[str]]:
    """Resolves a fight to VICTORY/DEFEAT/FLED.

    `choose_action(fighter, enemy, usable_skills)` is called once per player
    turn; returning None means flee, otherwise the returned Skill is cast.
    The engine itself does no input()/print() — tests script the callback,
    the REPL wires it to real input. Player HP/MANA are written back onto
    `player` before returning; `enemy` is mutated in place (a throwaway
    per-encounter Combatant built by the caller).

    Combat does not advance the day clock — SPEC.md §4 reserves that for
    travel/rest, not intra-day actions. `current_day` is only needed to stamp
    a captured player's guaranteed release day (setback.py) on DEFEAT; it
    defaults to 0 since most tests don't care about the exact day.
    """
    fighter = Combatant.from_player(player)
    log: list[str] = []
    order = turn_order(fighter, enemy)

    while fighter.hp > 0 and enemy.hp > 0:
        for side in order:
            if fighter.hp <= 0 or enemy.hp <= 0:
                break

            actor, opponent = (fighter, enemy) if side == "player" else (enemy, fighter)
            stunned = tick_upkeep(actor, log)
            if fighter.hp <= 0 or enemy.hp <= 0:
                break
            if stunned:
                continue

            if side == "player":
                skill = choose_action(fighter, enemy, usable_skills(fighter))
                if skill is None:
                    player.hp = fighter.hp
                    player.mana = fighter.mana
                    log.append(f"You flee from the {enemy.name}.")
                    return CombatResult.FLED, log
                behavior.record_combat_action(player.behavior)
                if skill is not BASIC_ATTACK:
                    fair = compute_fair_cost(skill.effects, _magnitude(fighter, skill))
                    if is_underpriced(skill, fair):
                        player.creative_mode_used = True
            else:
                skill = BASIC_ATTACK

            actor.mana = max(0, actor.mana - skill.mana_cost)
            if skill.cooldown > 0:
                actor.cooldowns[skill.id] = skill.cooldown
            apply_skill(actor, opponent, skill, log)

    player.hp = fighter.hp
    player.mana = fighter.mana

    if fighter.hp <= 0:
        # SPEC.md §11.1: losing a fight is never game-over except vs. the
        # demon king / designated bosses — an ordinary loss is a recoverable
        # setback (setback.py), never a soft-lock.
        player.hp = max(1, player.hp_max // 4)
        log.append(
            f"You are defeated by the {enemy.name}! You come to, battered but "
            f"alive ({player.hp}/{player.hp_max} HP)."
        )
        log.extend(setback.capture_player(player, current_day))
        return CombatResult.DEFEAT, log

    log.append(f"You defeated the {enemy.name}!")
    return CombatResult.VICTORY, log
