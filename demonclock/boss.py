"""Boss encounters as situations, not HP checks (SPEC.md §6b's own framing:
because skill creation is unrestricted, a boss can't be balanced as a single
HP number — trivial for a god-build, unbeatable for a legit one). An
`Encounter` is DATA: an ordered sequence of `Phase`s, each with its own
roster and a non-HP transition condition, reusing combat.py's
`Combatant`/`apply_skill`/`tick_upkeep`/`usable_skills` rather than
duplicating them.

The anti-degenerate lever is `Phase.boss_immune` + `Combatant.immune`
(combat.py): while immune, the boss takes zero HP loss from ANY source,
however large — so a one-shot-kill skill still has to clear that phase's
adds (or wait out a turn/HP-threshold gate) before the boss can be hurt at
all. Difficulty comes from the fight's structure, not a damage race.

Scope of this chunk (the first of two closing the "bosses as situations, not
HP checks" build-progress item — see CLAUDE.md): the encounter ENGINE only,
exercised against hand-built test Encounters. No wiring into the real game
yet — the actual demon-king Encounter, the invasion-complete trigger, and
game.py's Interact wiring are the next chunk.

KNOWN SIMPLIFICATION (deliberate, this chunk, same status as combat.py's
matching notes): enemy AI (boss + adds) always casts BASIC_ATTACK at the
player — the same simplification enemies.py already has for ordinary combat
("enemies don't cast learned skills yet"). Boss/add skill casting is a
future refinement, not required to prove the phase/immunity/trigger
mechanic.
"""
from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from .combat import BASIC_ATTACK, Combatant, apply_skill, tick_upkeep, usable_skills
from .models import Player
from .skills import Effect, EffectKind, Skill, StatType


# Step 8 P4: same circuit-breaker role as combat.MAX_COMBAT_ROUNDS, sized
# larger since a multi-phase encounter legitimately runs longer than one
# ordinary fight — counts rounds across the WHOLE encounter, not reset per
# phase (unlike rounds_this_phase, which trigger checking needs reset).
MAX_ENCOUNTER_ROUNDS = 200


class PhaseTriggerKind(str, Enum):
    ADDS_CLEARED = "adds_cleared"
    HP_THRESHOLD = "hp_threshold"
    TURN_COUNT = "turn_count"


@dataclass
class PhaseTrigger:
    kind: PhaseTriggerKind
    # ADDS_CLEARED: unused (None). HP_THRESHOLD: fraction of boss.hp_max
    # (0-1) — the phase ends once boss.hp falls to/below it. TURN_COUNT:
    # number of full rounds this phase lasts before advancing regardless of
    # anything else.
    value: float | int | None = None


@dataclass
class Phase:
    id: str
    name: str
    # None is only legal on the LAST phase of an Encounter — that phase ends
    # in VICTORY once the boss's HP reaches 0, the ordinary combat win
    # condition. Every earlier phase must set a real trigger (see
    # validate_encounter), or the fight can never advance past it.
    trigger: PhaseTrigger | None
    adds: list[Combatant] = field(default_factory=list)
    boss_immune: bool = False
    # Cast on the player, in list order, at the end of every round this
    # phase is active — the "terrain" piece of phases/adds/terrain.
    environment_skills: list[Skill] = field(default_factory=list)
    narrative_beat: str = ""


@dataclass
class Encounter:
    id: str
    name: str
    boss: Combatant
    phases: list[Phase]  # phases[0] is entered first


class EncounterResult(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    FLED = "fled"


class EncounterError(ValueError):
    pass


def validate_encounter(encounter: Encounter) -> None:
    """Guards the structural contract every Encounter must satisfy — not a
    balance check, same posture as skills.validate_skill/events.validate_event."""
    if not encounter.phases:
        raise EncounterError(f"{encounter.id} has no phases")
    if encounter.phases[-1].trigger is not None:
        raise EncounterError(f"{encounter.id}'s last phase must have trigger=None")
    for phase in encounter.phases[:-1]:
        if phase.trigger is None:
            raise EncounterError(
                f"{encounter.id}'s phase {phase.id!r} needs a trigger "
                "(only the last phase may omit one)"
            )


# (skill, target) to cast, or None to flee. `target` is only meaningful for a
# harmful effect — combat.py's existing targeting-default convention
# (beneficial effects always apply to the caster) is unchanged here.
ChooseAction = Callable[
    [Combatant, Combatant, list[Combatant], list[Skill]],
    "tuple[Skill, Combatant] | None",
]


def _turn_order(fighter: Combatant, boss: Combatant, adds: list[Combatant]) -> list[Combatant]:
    """AGILITY descending; ties preserve list order (fighter, then boss, then
    adds in their authored order) — deterministic, no RNG, same posture as
    combat.turn_order. Recomputed once per phase (the roster changes with
    the phase), fixed for the phase's duration otherwise."""
    return sorted([fighter, boss, *adds], key=lambda c: -c.agility)


def _trigger_met(
    trigger: PhaseTrigger, boss: Combatant, active_adds: list[Combatant], rounds_this_phase: int
) -> bool:
    if trigger.kind is PhaseTriggerKind.ADDS_CLEARED:
        return all(add.hp <= 0 for add in active_adds)
    if trigger.kind is PhaseTriggerKind.HP_THRESHOLD:
        return boss.hp <= trigger.value * boss.hp_max
    if trigger.kind is PhaseTriggerKind.TURN_COUNT:
        return rounds_this_phase >= trigger.value
    raise AssertionError(f"unhandled trigger kind: {trigger.kind}")


def run_encounter(
    player: Player,
    encounter: Encounter,
    choose_action: ChooseAction,
) -> tuple[EncounterResult, list[str]]:
    """Resolves a multi-phase boss fight to VICTORY/DEFEAT/FLED.

    `choose_action(fighter, boss, active_adds, usable_skills)` is called once
    per player turn; `active_adds` only lists adds still alive in the current
    phase. Returning None means flee; otherwise a `(skill, target)` pair.

    Unlike `combat.run_combat`, a loss here is NOT routed through
    `setback.py` — SPEC.md §11.1 reserves true, permanent game-over
    specifically for the demon king and designated bosses, and this is that
    fight. The caller is responsible for the game-over flow on DEFEAT (next
    chunk's job — nothing calls run_encounter from the real game yet).

    `encounter.boss` and every `Phase.adds` entry are deep-copied at the
    start of the call, so a stored Encounter (a module-level constant, or a
    future content-pool item) is never mutated by playing it — the same
    fight can be attempted again after a flee or a defeat.

    Guaranteed to terminate (Step 8 P4): after MAX_ENCOUNTER_ROUNDS rounds
    across the WHOLE encounter (not reset per phase — an immortal add or an
    unreachable HP_THRESHOLD would otherwise stall a phase forever), the
    fight is forced to a stalemate FLED — same consequence-free result as
    the player choosing to flee, and, like combat.run_combat, resettable on
    a later attempt.
    """
    fighter = Combatant.from_player(player)
    boss = copy.deepcopy(encounter.boss)
    environment_actor = Combatant(
        name="the environment", hp=1, hp_max=1, strength=10, agility=0, defense=0, magic=10,
    )
    log: list[str] = []

    phase_index = 0
    active_adds: list[Combatant] = []
    order: list[Combatant] = []
    rounds_this_phase = 0
    rounds_total = 0

    def enter_phase(index: int) -> None:
        nonlocal active_adds, order, rounds_this_phase
        phase = encounter.phases[index]
        boss.immune = phase.boss_immune
        active_adds = [copy.deepcopy(add) for add in phase.adds]
        order = _turn_order(fighter, boss, active_adds)
        rounds_this_phase = 0
        if phase.narrative_beat:
            log.append(phase.narrative_beat)

    enter_phase(phase_index)

    while True:
        if rounds_total >= MAX_ENCOUNTER_ROUNDS:
            player.hp, player.mana = fighter.hp, fighter.mana
            log.append(f"The battle against {encounter.name} drags on with no end in sight. You disengage.")
            return EncounterResult.FLED, log
        rounds_total += 1

        phase = encounter.phases[phase_index]

        for actor in order:
            if fighter.hp <= 0 or actor.hp <= 0:
                continue
            stunned = tick_upkeep(actor, log)
            if fighter.hp <= 0:
                break
            if stunned:
                continue

            if actor is fighter:
                choice = choose_action(
                    fighter, boss, [add for add in active_adds if add.hp > 0], usable_skills(fighter)
                )
                if choice is None:
                    player.hp, player.mana = fighter.hp, fighter.mana
                    log.append(f"You flee from {encounter.name}.")
                    return EncounterResult.FLED, log
                skill, target = choice
                fighter.mana = max(0, fighter.mana - skill.mana_cost)
                if skill.cooldown > 0:
                    fighter.cooldowns[skill.id] = skill.cooldown
                apply_skill(fighter, target, skill, log)
            else:
                apply_skill(actor, fighter, BASIC_ATTACK, log)

            if fighter.hp <= 0:
                break

        player.hp, player.mana = fighter.hp, fighter.mana
        if fighter.hp <= 0:
            return EncounterResult.DEFEAT, log

        for env_skill in phase.environment_skills:
            apply_skill(environment_actor, fighter, env_skill, log)
            player.hp = fighter.hp
            if fighter.hp <= 0:
                return EncounterResult.DEFEAT, log

        rounds_this_phase += 1

        if phase.trigger is None:
            if boss.hp <= 0:
                log.append(f"You have defeated {encounter.name}!")
                return EncounterResult.VICTORY, log
        elif _trigger_met(phase.trigger, boss, active_adds, rounds_this_phase):
            phase_index += 1
            enter_phase(phase_index)


# The real demon-king fight (Chunk B) — the one Encounter this whole module
# is scoped to (a deliberate, resolved decision: no speculative multi-boss
# framework, see CLAUDE.md's build-progress entry for this item). Same
# "start rough, calibrate by feel" status as every other tuning constant in
# this codebase (SPEC.md §11) — there's no leveling system yet, so these
# numbers aren't calibrated against anything but a fresh default Player.
DEMON_KING_ENCOUNTER = Encounter(
    id="demon_king",
    name="the Demon King",
    boss=Combatant(name="The Demon King", hp=200, hp_max=200, strength=18, agility=12, defense=8, magic=15),
    phases=[
        Phase(
            id="cultist_ward",
            name="The Cultist Ward",
            trigger=PhaseTrigger(PhaseTriggerKind.ADDS_CLEARED),
            adds=[
                Combatant(name="Bound Cultist", hp=25, hp_max=25, strength=6, agility=9, defense=1),
                Combatant(name="Bound Cultist", hp=25, hp_max=25, strength=6, agility=9, defense=1),
            ],
            boss_immune=True,
            narrative_beat=(
                "Two cultists, bound to the Demon King's will, place themselves between "
                "you and the throne. He watches, untouchable, while they still live."
            ),
        ),
        Phase(
            id="the_demon_king",
            name="The Demon King Unbound",
            trigger=None,
            boss_immune=False,
            environment_skills=[
                Skill(
                    id="throne_room_dread",
                    name="the throne room's dread",
                    description="An oppressive weight presses on you as you fight.",
                    effects=[Effect(EffectKind.DAMAGE)],
                    attribute_type=StatType.MAGIC,
                    base_damage=8,
                    attribute_multiplier=1.0,
                    mana_cost=0,
                ),
            ],
            narrative_beat="The last cultist falls. The Demon King rises from his throne.",
        ),
    ],
)
