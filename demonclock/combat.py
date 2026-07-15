"""Turn-based combat (SPEC.md §6b) — the loop only, this build stage. Skills,
the enumerated `effects` vocabulary, and the fair-cost calculator are later
combat stages; see CLAUDE.md "Build progress".

Deterministic on purpose for this stage: no damage variance, no dodge, no
crit. RNG (AGILITY-based dodge, LUCK-based crit, damage variance) is planned
for a later combat stage — see the forward-note in SPEC.md §6b and the entry
in progress.md for this stage.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from .models import Player

BASIC_ATTACK_BASE_DAMAGE = 20
BASIC_ATTACK_MULTIPLIER = 1.0


class CombatAction(str, Enum):
    ATTACK = "attack"
    FLEE = "flee"


class CombatResult(str, Enum):
    VICTORY = "victory"
    DEFEAT = "defeat"
    FLED = "fled"


@dataclass
class Combatant:
    name: str
    hp: int
    hp_max: int
    strength: int
    agility: int
    defense: int

    @classmethod
    def from_player(cls, player: Player) -> "Combatant":
        return cls(
            name=player.name,
            hp=player.hp,
            hp_max=player.hp_max,
            strength=player.strength,
            agility=player.agility,
            defense=player.defense,
        )


def compute_damage(attacker: Combatant, defender: Combatant) -> int:
    """total = (base * multiplier) + attacker strength, then DEFENSE mitigation
    (SPEC.md §6b). Flat-subtraction mitigation floored at 1 so a fight always
    terminates; the exact curve is a later tuning pass — same status as the
    fair-cost curve (SPEC.md §11: "start rough, calibrate by feel")."""
    raw = (BASIC_ATTACK_BASE_DAMAGE * BASIC_ATTACK_MULTIPLIER) + attacker.strength
    return max(1, int(raw) - defender.defense)


def turn_order(player: Combatant, enemy: Combatant) -> list[str]:
    """AGILITY descending; ties favor the player (deterministic, no RNG this stage)."""
    return ["enemy", "player"] if enemy.agility > player.agility else ["player", "enemy"]


def run_combat(
    player: Player,
    enemy: Combatant,
    choose_action: Callable[[Combatant, Combatant], CombatAction],
) -> tuple[CombatResult, list[str]]:
    """Resolves a fight to VICTORY/DEFEAT/FLED.

    `choose_action(fighter, enemy)` is called once per player turn, given the
    current combatant state, so the engine itself does no input()/print() —
    tests script it, the REPL wires it to real input and can print HP each
    turn from the arguments it receives. Player HP is written back onto
    `player` before returning; `enemy` is mutated in place too (it's a
    throwaway per-encounter Combatant built by the caller).

    Combat does not advance the day clock — SPEC.md §4 reserves clock
    advancement for travel/rest, not intra-day actions.
    """
    fighter = Combatant.from_player(player)
    log: list[str] = []
    order = turn_order(fighter, enemy)

    while fighter.hp > 0 and enemy.hp > 0:
        for side in order:
            if fighter.hp <= 0 or enemy.hp <= 0:
                break
            if side == "player":
                action = choose_action(fighter, enemy)
                if action is CombatAction.FLEE:
                    player.hp = fighter.hp
                    log.append(f"You flee from the {enemy.name}.")
                    return CombatResult.FLED, log
                dmg = compute_damage(fighter, enemy)
                enemy.hp = max(0, enemy.hp - dmg)
                log.append(
                    f"You hit the {enemy.name} for {dmg} damage. "
                    f"({enemy.hp}/{enemy.hp_max} HP left)"
                )
            else:
                dmg = compute_damage(enemy, fighter)
                fighter.hp = max(0, fighter.hp - dmg)
                log.append(
                    f"The {enemy.name} hits you for {dmg} damage. "
                    f"({fighter.hp}/{fighter.hp_max} HP left)"
                )

    player.hp = fighter.hp

    if fighter.hp <= 0:
        # Placeholder recovery until the real setback-state system lands
        # (SPEC.md §11.1): losing a fight is never game-over except vs. the
        # demon king / designated bosses, and a setback must never soft-lock.
        player.hp = max(1, player.hp_max // 4)
        log.append(
            f"You are defeated by the {enemy.name}! You come to, battered but "
            f"alive ({player.hp}/{player.hp_max} HP)."
        )
        return CombatResult.DEFEAT, log

    log.append(f"You defeated the {enemy.name}!")
    return CombatResult.VICTORY, log
