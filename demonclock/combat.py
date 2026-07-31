"""Turn-based combat (SPEC.md §6b) — skill-based since Stage 2, with Stage 3's
fair-cost check wired in: the moment the player CASTS a learned skill whose
actual cost undercuts `skills.compute_fair_cost` on any dimension, this sets
`Player.creative_mode_used` (never at authoring time — see skills.py).

Step 9 (SPEC.md §6b's RNG design, built as two chunks): an injectable
`random.Random` is threaded through `run_combat`, defaulting to a fresh
instance so real play gets it for free, but overridable (including with a
matched seed) so a fight stays exactly as reproducible as it was pre-RNG.
Chunk A wired up AGILITY-based dodge — a dodge skips damage resolution for
that hit entirely (no mitigation/shield/lifesteal), narrated as a miss, not a
0-damage hit. Chunk B adds the other two rolls, both inside the damage path
dodge gates: a LUCK-based crit (`Combatant.luck`, new this chunk) multiplies
`magnitude` by `CRIT_MULTIPLIER` before mitigation, then every surviving hit
(crit or not) gets a small multiplicative variance jitter. Only the `DAMAGE`
effect ever rolls — DOT/HEAL/SHIELD/etc. stay exactly as deterministic as
before.

Effect targeting is a fixed default: harmful effects (damage/stun/dot/debuff)
hit the opponent; beneficial effects (heal/lifesteal/shield/buff/cleanse)
apply to the caster. Step 10 Stage 6 (SPEC.md §12 build progress) gave AOE and
KNOCKBACK real implementations now that multi-enemy ordinary combat
(`run_group_combat`) exists to give them a target/mechanic: AOE makes the
skill's own damage instance also splash onto every OTHER live combatant on
the opposing side (the optional `others` param below — empty/None in a 1v1
fight, so AOE naturally has nothing extra to hit there, not a special case);
KNOCKBACK staggers the target (adds to `stun_turns`, the same field STUN
uses, just narrated differently — no separate "knockback" state needed).
TAUNT stays inert (see skills.INERT_EFFECTS for why: this game has exactly
one player-side combatant, so there's no ally for an enemy's attack to be
redirected FROM).

Step 10 Stage 6 also added `choose_enemy_skill`: enemy/boss/add turns now
pick uniformly among `usable_skills(actor)` instead of a hardcoded
`BASIC_ATTACK` — today every enemy's `.skills` list is still empty, so
`usable_skills` is always `[BASIC_ATTACK]` and this resolves to the exact
same thing every existing fight already did; the mechanism is there for
whenever a future enemy/boss actually has learned skills.
"""
from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from . import behavior, journal, setback
from .models import Player
from .skills import (
    BASIC_ATTACK,
    Effect,
    EffectKind,
    INERT_EFFECTS,
    Skill,
    StatType,
    compute_fair_cost,
    compute_grown_magnitude,
    compute_magnitude,
    is_underpriced,
)

# Placeholder tuning constants — same status as the fair-cost curve (SPEC.md
# §11: "start rough, calibrate by feel").
DOT_DURATION = 3
STUN_DURATION = 1
BUFF_DEBUFF_DURATION = 3
LIFESTEAL_FRACTION = 0.5
# A DOT reapplied while still active ADDS its damage-per-tick to the
# currently ticking total (rather than overwriting it) and refreshes the
# duration -- up to this many stacked applications. Once at the cap, a
# further reapplication still refreshes the duration (keeps the DOT alive)
# but stops adding more damage, bounding what would otherwise be an
# unbounded damage-per-tick ramp from repeated re-casting. Same "start
# rough, calibrate by feel" status as every other constant here.
MAX_DOT_STACKS = 5
# Step 10 Stage 6: KNOCKBACK staggers the target via the same stun_turns
# field STUN uses — a separate constant (rather than reusing STUN_DURATION
# directly) so the two can be tuned independently later.
KNOCKBACK_STUN_TURNS = 1

# Step 8 P4: the circuit breaker for a stalemate (e.g. a heal/shield-only
# build outpacing a weak enemy's damage) — generous enough not to truncate
# any real fight, low enough to guarantee run_combat always returns.
MAX_COMBAT_ROUNDS = 100

# Step 9 (SPEC.md §6b), "start rough, calibrate by feel" placeholders, same
# status as DOT_DURATION etc. above. Dodge is rolled on the defender, using
# the attacker's AND defender's post-buff AGILITY (effective_stat) — the same
# stat that already drives turn order, paying off again here.
BASE_DODGE = 0.05
DODGE_PER_AGI = 0.01
DODGE_CAP = 0.35

# Crit is rolled on the attacker, using raw LUCK (not effective_stat — LUCK
# isn't in skills.StatType, so it's never buffable/debuffable, unlike AGILITY
# above). Damage variance applies to every surviving (non-dodged) hit,
# crit or not.
BASE_CRIT = 0.05
CRIT_PER_LUCK = 0.01
CRIT_CAP = 0.5
CRIT_MULTIPLIER = 1.5
VARIANCE = 0.15

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


class CombatError(ValueError):
    pass


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
    # Step 9: feeds crit chance only (see BASE_CRIT/CRIT_PER_LUCK above).
    # Defaults to 0 for enemies/bosses/adds/the environment actor, none of
    # which are given an explicit luck today — they simply never crit, same
    # "start rough" status as their never casting a learned skill.
    luck: int = 0
    skills: list[Skill] = field(default_factory=list)
    shield: int = 0
    stun_turns: int = 0
    dot_damage: int = 0
    dot_turns_remaining: int = 0
    # How many DOT applications have contributed to the currently-active
    # dot_damage total (capped at MAX_DOT_STACKS) -- 0 whenever no DOT is
    # active. Not reset to 0 by tick_upkeep on natural expiry (same as
    # dot_damage/dot_turns_remaining already weren't); the DOT branch below
    # treats dot_turns_remaining > 0 as the sole "is a DOT currently active"
    # signal, so a stale dot_stacks value from an expired DOT is always
    # overwritten, not read, the next time one is applied.
    dot_stacks: int = 0
    modifiers: list[StatModifier] = field(default_factory=list)
    cooldowns: dict[str, int] = field(default_factory=dict)  # skill id -> turns left
    # Blocks ALL HP loss (direct hits and DOT ticks alike), however large the
    # incoming number — the boss-phase-gating mechanic boss.py builds on.
    # Unused by ordinary combat.run_combat; defaults False so nothing here
    # changes for existing fights.
    immune: bool = False

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
            luck=player.luck,
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


def _roll_dodge(defender: Combatant, attacker: Combatant, rng: random.Random) -> bool:
    """SPEC.md §6b: rolled on the defender before damage is computed."""
    chance = effective_stat(defender, StatType.AGILITY) - effective_stat(attacker, StatType.AGILITY)
    chance = min(DODGE_CAP, max(0.0, BASE_DODGE + chance * DODGE_PER_AGI))
    return rng.random() < chance


def _roll_crit(attacker: Combatant, rng: random.Random) -> bool:
    """SPEC.md §6b: rolled on the attacker, only once dodge has failed to
    trigger. LUCK is never negative (Player's own default/fixed attribute
    set has no floor enforcement below 0 today, but nothing authors a
    negative one either), so this chance never needs the max(0.0, ...) floor
    _roll_dodge's AGILITY-difference version does."""
    chance = min(CRIT_CAP, BASE_CRIT + attacker.luck * CRIT_PER_LUCK)
    return rng.random() < chance


def _apply_variance(magnitude: int, rng: random.Random) -> int:
    """SPEC.md §6b: every surviving (non-dodged) hit, crit or not, gets a
    small multiplicative jitter so identical stats don't always print an
    identical number. Floored at 1 — variance should never zero out a hit
    that dodge already let through."""
    return max(1, round(magnitude * rng.uniform(1 - VARIANCE, 1 + VARIANCE)))


def _magnitude(caster: Combatant, skill: Skill) -> int:
    """SPEC.md §6b damage formula, generalized: every effect on a skill draws
    from the same power budget rather than each having its own tunable
    number — keeps the schema close to what SPEC.md §6b actually specifies."""
    return compute_magnitude(skill.base_damage, skill.attribute_multiplier, effective_stat(caster, skill.attribute_type))


def _apply_damage(target: Combatant, amount: int) -> int:
    """Reduces target.hp by `amount`, respecting `Combatant.immune`. Routing
    every HP loss (direct hits here, DOT ticks in `tick_upkeep`) through this
    one guard is what makes immunity airtight — a DOT stacked before a boss
    phase went immune can't quietly bypass it. Returns the HP actually
    lost (0 while immune, regardless of how large `amount` is)."""
    if target.immune:
        return 0
    lost = min(target.hp, amount)
    target.hp -= lost
    return lost


def _deal_damage(caster: Combatant, target: Combatant, magnitude: int, skill: Skill, log: list[str]) -> int:
    mitigated = max(1, magnitude - effective_stat(target, StatType.DEFENSE))
    absorbed = min(target.shield, mitigated)
    target.shield -= absorbed
    remaining = mitigated - absorbed
    lost = _apply_damage(target, remaining)
    if absorbed:
        log.append(f"{target.name}'s shield absorbs {absorbed} damage.")
    if target.immune and remaining > 0:
        log.append(f"{caster.name}'s {skill.name} has no effect on {target.name}.")
    else:
        log.append(
            f"{caster.name} hits {target.name} with {skill.name} for {lost} damage. "
            f"({target.hp}/{target.hp_max} HP left)"
        )
    return lost


def apply_skill(
    caster: Combatant, opponent: Combatant, skill: Skill, log: list[str],
    rng: random.Random | None = None, others: list[Combatant] | None = None,
) -> None:
    """Resolves every effect on `skill` in a fixed canonical order (not
    authoring order) so cross-effect dependencies — e.g. LIFESTEAL needs
    DAMAGE's result — are always well-defined regardless of how the skill's
    effects list was composed.

    `rng` gates Step 9's dodge/crit/variance rolls (DAMAGE effect only —
    every other effect is unaffected): `None` (the default) disables them
    entirely, reproducing this function's pre-Step-9 fully deterministic
    behavior, which is what every direct `apply_skill(...)` call in the test
    suite still relies on. `run_combat`/`run_encounter` always pass a real
    `random.Random` instance.

    `others` (Step 10 Stage 6) lists every OTHER live combatant on
    `opponent`'s side, for AOE to also hit — `None`/empty (the default,
    what every 1v1 call site including `boss.run_encounter` still passes)
    means AOE naturally has nothing extra to splash onto, not a special
    case. Only `run_group_combat`'s player-turn dispatch ever passes a
    non-empty list.
    """
    # Growth (updates.md, resolved 2026-07-31) is applied here, at the
    # actual point of effect resolution -- never inside _magnitude itself,
    # which run_group_combat/boss.run_encounter's own fair-cost/
    # is_underpriced checks also call and must keep comparing against the
    # skill's UN-grown, as-authored power (see compute_grown_magnitude's
    # own docstring for why that separation matters).
    magnitude = compute_grown_magnitude(_magnitude(caster, skill), skill.use_count)
    dealt = 0
    has_damage = any(e.kind is EffectKind.DAMAGE for e in skill.effects)
    has_aoe = any(e.kind is EffectKind.AOE for e in skill.effects)

    for effect in sorted(skill.effects, key=lambda e: _EFFECT_PRIORITY[e.kind]):
        if effect.kind is EffectKind.DAMAGE:
            if rng is not None and _roll_dodge(opponent, caster, rng):
                log.append(f"{opponent.name} dodges {caster.name}'s {skill.name}!")
                dealt = 0
                hit_magnitude = magnitude  # no crit/variance rolled for a dodged hit
            else:
                hit_magnitude = magnitude
                if rng is not None:
                    if _roll_crit(caster, rng):
                        hit_magnitude = round(hit_magnitude * CRIT_MULTIPLIER)
                        log.append("Critical hit!")
                    hit_magnitude = _apply_variance(hit_magnitude, rng)
                dealt = _deal_damage(caster, opponent, hit_magnitude, skill, log)

            if has_aoe:
                for other in others or []:
                    if other.hp <= 0:
                        continue
                    if rng is not None and _roll_dodge(other, caster, rng):
                        log.append(f"{other.name} dodges {caster.name}'s {skill.name}!")
                        continue
                    _deal_damage(caster, other, hit_magnitude, skill, log)

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
            applied = max(1, magnitude // 2)
            if opponent.dot_turns_remaining <= 0:
                # No DOT currently active (fresh application, or the
                # previous one already expired) -- starts a new single stack.
                opponent.dot_damage = applied
                opponent.dot_stacks = 1
                log.append(f"{opponent.name} is afflicted with a lingering wound.")
            elif opponent.dot_stacks < MAX_DOT_STACKS:
                # Already ticking and under the cap -- stacks additively.
                opponent.dot_damage += applied
                opponent.dot_stacks += 1
                log.append(
                    f"{opponent.name}'s lingering wound deepens "
                    f"({opponent.dot_stacks}/{MAX_DOT_STACKS} stacks)."
                )
            else:
                # At the cap -- damage doesn't grow further, but the
                # reapplication (below) still refreshes the duration.
                log.append(f"{opponent.name}'s lingering wound is already at its worst.")
            opponent.dot_turns_remaining = DOT_DURATION

        elif effect.kind is EffectKind.BUFF:
            caster.modifiers.append(StatModifier(stat=effect.stat, amount=magnitude, turns_remaining=BUFF_DEBUFF_DURATION))
            log.append(f"{caster.name}'s {effect.stat.value} rises.")

        elif effect.kind is EffectKind.DEBUFF:
            opponent.modifiers.append(StatModifier(stat=effect.stat, amount=-magnitude, turns_remaining=BUFF_DEBUFF_DURATION))
            log.append(f"{opponent.name}'s {effect.stat.value} falls.")

        elif effect.kind is EffectKind.CLEANSE:
            caster.dot_damage = 0
            caster.dot_turns_remaining = 0
            caster.dot_stacks = 0
            caster.stun_turns = 0
            before = len(caster.modifiers)
            caster.modifiers = [m for m in caster.modifiers if m.amount > 0]
            if len(caster.modifiers) < before:
                log.append(f"{caster.name} shakes off the negative effects.")

        elif effect.kind is EffectKind.KNOCKBACK:
            opponent.stun_turns += KNOCKBACK_STUN_TURNS
            log.append(f"{opponent.name} is knocked back, staggering!")

        elif effect.kind is EffectKind.AOE:
            # The splash itself already happened above, folded into the
            # DAMAGE branch (AOE modifies how DAMAGE resolves rather than
            # being its own damage-dealing effect) -- this branch only
            # covers the edge case of an AOE effect with no DAMAGE effect
            # on the same skill, which has nothing to spread.
            if not has_damage:
                log.append(f"{skill.name}'s aoe has no damage to spread without a damage effect.")

        elif effect.kind in INERT_EFFECTS:
            log.append(f"{skill.name}'s {effect.kind.value} has no target here yet.")


def tick_upkeep(combatant: Combatant, log: list[str]) -> bool:
    """Runs at the start of `combatant`'s turn: DOT damage, modifier/cooldown
    countdown. Returns True if a stun consumes this turn (caller should skip
    the action)."""
    if combatant.dot_turns_remaining > 0:
        lost = _apply_damage(combatant, combatant.dot_damage)
        combatant.dot_turns_remaining -= 1
        if lost:
            log.append(
                f"{combatant.name} suffers {lost} lingering damage. "
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


def choose_enemy_skill(actor: Combatant, rng: random.Random) -> Skill:
    """Step 10 Stage 6: picks uniformly among `usable_skills(actor)` instead
    of a hardcoded BASIC_ATTACK. Implemented via `rng.random()` rather than
    `rng.choice()` deliberately: every rigged test-double `rng` in this
    codebase implements only `.random()`/`.uniform()` (never `.choice()`),
    and — more importantly — every enemy/boss/add's `.skills` list is still
    empty today, so `usable_skills` is always the single-element
    `[BASIC_ATTACK]`; this returns it directly WITHOUT consuming any `rng`
    draw in that case, so the dodge/crit/variance roll sequence every
    existing test relies on is completely undisturbed. Only once an
    enemy/boss/add actually has learned skills does this ever roll."""
    options = usable_skills(actor)
    if len(options) == 1:
        return options[0]
    index = min(len(options) - 1, int(rng.random() * len(options)))
    return options[index]


def _enemies_desc(enemies: list[Combatant]) -> str:
    """'the X' for one enemy (byte-identical to every message run_combat
    printed before Step 10 Stage 6 generalized it), 'the X and the Y' / 'the
    X, the Y, and the Z' for more — used to keep run_group_combat's
    single-enemy narration textually identical to the old run_combat."""
    named = [f"the {enemy.name}" for enemy in enemies]
    if len(named) == 1:
        return named[0]
    if len(named) == 2:
        return f"{named[0]} and {named[1]}"
    return f"{', '.join(named[:-1])}, and {named[-1]}"


GroupChooseAction = Callable[
    [Combatant, list[Combatant], list[Skill]],
    "tuple[Skill, Combatant] | None",
]


def run_group_combat(
    player: Player,
    enemies: list[Combatant],
    choose_action: GroupChooseAction,
    current_day: int = 0,
    rng: random.Random | None = None,
) -> tuple[CombatResult, list[str]]:
    """The general engine (Step 10 Stage 6) both ordinary multi-enemy combat
    and `run_combat`'s single-enemy shim rest on — same multi-combatant
    turn-order/targeting shape `boss.run_encounter` already established
    (sans phases/adds/immunity, which stay `boss.py`'s own scope, reserved
    for designated bosses), rather than a second, unrelated implementation.

    `choose_action(fighter, alive_enemies, usable_skills)` is called once
    per player turn; `alive_enemies` only lists enemies still standing.
    Returning None means flee; otherwise a `(skill, target)` pair, same
    shape as `boss.ChooseAction` — the caller only needs to prompt for a
    target when more than one enemy is alive, same precedent
    `game._handle_demon_king` already set.

    Enemies always target the player (no ally-targeting for foes this
    stage) and pick their skill via `choose_enemy_skill`. Unlike
    `boss.run_encounter`, a loss here routes through `setback.py` exactly
    like the single-enemy `run_combat` always has — an ordinary fight, never
    a game-over.

    Turn order is fixed once at the start (agility descending, ties favor
    the player — same convention `turn_order` uses for the 1-enemy case,
    reproduced here via a stable sort with the fighter listed first).
    Guaranteed to terminate (same `MAX_COMBAT_ROUNDS` circuit breaker
    `run_combat` already had) with a stalemate FLED.

    Raises `CombatError` for an empty `enemies` list rather than letting one
    reach `_enemies_desc`'s own `named[-1]` indexing at the very end of the
    fight (a confusing `IndexError` far from the actual mistake) — a fight
    with no enemies should never legitimately be started in the first place
    (every real caller builds `enemies` from a non-empty source, e.g.
    `WILD_ENEMY_BY_NODE`), so this is a fail-fast guard against a caller
    bug, not a real gameplay state to degrade gracefully."""
    if not enemies:
        raise CombatError("run_group_combat requires at least one enemy")
    rng = rng if rng is not None else random.Random()
    fighter = Combatant.from_player(player)
    log: list[str] = []
    order = sorted([fighter, *enemies], key=lambda c: -c.agility)
    rounds = 0

    while fighter.hp > 0 and any(enemy.hp > 0 for enemy in enemies):
        if rounds >= MAX_COMBAT_ROUNDS:
            player.hp = fighter.hp
            player.mana = fighter.mana
            log.append(f"The fight against {_enemies_desc(enemies)} drags on with no end in sight. You disengage.")
            return CombatResult.FLED, log
        rounds += 1

        for actor in order:
            if fighter.hp <= 0 or all(enemy.hp <= 0 for enemy in enemies):
                break
            if actor is not fighter and actor.hp <= 0:
                continue

            stunned = tick_upkeep(actor, log)
            if fighter.hp <= 0:
                break
            if stunned:
                continue

            if actor is fighter:
                alive = [enemy for enemy in enemies if enemy.hp > 0]
                choice = choose_action(fighter, alive, usable_skills(fighter))
                if choice is None:
                    player.hp = fighter.hp
                    player.mana = fighter.mana
                    log.append(f"You flee from {_enemies_desc(enemies)}.")
                    return CombatResult.FLED, log
                skill, target = choice
                behavior.record_combat_action(player.behavior)
                if skill is not BASIC_ATTACK:
                    fair = compute_fair_cost(skill.effects, _magnitude(fighter, skill))
                    if is_underpriced(skill, fair):
                        player.creative_mode_used = True
                    else:
                        # "Skills grow with use" (updates.md, resolved
                        # 2026-07-31) -- excluded for an underpriced skill
                        # (creative_mode_used territory) so the game's one
                        # deliberate exploit door doesn't also compound with
                        # a second, unrelated power source.
                        skill.use_count += 1
                fighter.mana = max(0, fighter.mana - skill.mana_cost)
                if skill.cooldown > 0:
                    fighter.cooldowns[skill.id] = skill.cooldown
                others = [enemy for enemy in alive if enemy is not target]
                apply_skill(fighter, target, skill, log, rng, others=others)
            else:
                skill = choose_enemy_skill(actor, rng)
                actor.mana = max(0, actor.mana - skill.mana_cost)
                if skill.cooldown > 0:
                    actor.cooldowns[skill.id] = skill.cooldown
                apply_skill(actor, fighter, skill, log, rng)

    player.hp = fighter.hp
    player.mana = fighter.mana

    if fighter.hp <= 0:
        # SPEC.md §11.1: losing a fight is never game-over except vs. the
        # demon king / designated bosses — an ordinary loss is a recoverable
        # setback (setback.py), never a soft-lock.
        player.hp = max(1, player.hp_max // 4)
        log.append(
            f"You are defeated by {_enemies_desc(enemies)}! You come to, battered but "
            f"alive ({player.hp}/{player.hp_max} HP)."
        )
        journal.record(player.journal, current_day, f"Defeated by {_enemies_desc(enemies)}.")
        log.extend(setback.capture_player(player, current_day))
        return CombatResult.DEFEAT, log

    log.append(f"You defeated {_enemies_desc(enemies)}!")
    journal.record(player.journal, current_day, f"Defeated {_enemies_desc(enemies)}.")
    return CombatResult.VICTORY, log


def run_combat(
    player: Player,
    enemy: Combatant,
    choose_action: Callable[[Combatant, Combatant, list[Skill]], Skill | None],
    current_day: int = 0,
    rng: random.Random | None = None,
) -> tuple[CombatResult, list[str]]:
    """Resolves a single-enemy fight to VICTORY/DEFEAT/FLED — a thin,
    backward-compatible shim (Step 10 Stage 6) over `run_group_combat`,
    the one real engine both this and ordinary multi-enemy combat now
    share, rather than a second implementation. Its own external contract
    (signature, docstring behavior, exact log wording) is unchanged from
    before Stage 6 — see `_enemies_desc`, whose 1-enemy case is
    byte-identical to what this function used to build inline.

    `choose_action(fighter, enemy, usable_skills)` is called once per player
    turn; returning None means flee, otherwise the returned Skill is cast
    (implicitly against the one enemy — no target selection needed with
    only one). The engine itself does no input()/print() — tests script the
    callback, the REPL wires it to real input. Player HP/MANA are written
    back onto `player` before returning; `enemy` is mutated in place (a
    throwaway per-encounter Combatant built by the caller).

    Combat does not advance the day clock — SPEC.md §4 reserves that for
    travel/rest, not intra-day actions. `current_day` is only needed to stamp
    a captured player's guaranteed release day (setback.py) on DEFEAT; it
    defaults to 0 since most tests don't care about the exact day.

    `rng` (Step 9, SPEC.md §6b) drives dodge/crit/variance — defaults to a
    fresh `random.Random()` so real play gets working RNG combat with no
    caller changes, but a test can inject a seeded (or rigged) instance to
    keep a fight fully reproducible; the same seed passed to two separate
    calls reproduces an identical fight.

    Guaranteed to terminate (Step 8 P4): after MAX_COMBAT_ROUNDS full rounds
    with neither side dead — e.g. a heal/shield-only build outpacing a weak
    enemy's damage — the fight is forced to a stalemate FLED, the same
    result and consequences (no capture, resettable) as the player choosing
    to flee. Harmless in practice today, since `choose_action` is always a
    human answering `input()`, but this is the engine-level circuit breaker
    that matters the moment `choose_action` is ever driven by a script or a
    future automated/AI opponent.
    """

    def adapted_choose_action(
        fighter: Combatant, alive_enemies: list[Combatant], options: list[Skill]
    ) -> "tuple[Skill, Combatant] | None":
        skill = choose_action(fighter, alive_enemies[0], options)
        return None if skill is None else (skill, alive_enemies[0])

    return run_group_combat(player, [enemy], adapted_choose_action, current_day, rng)
