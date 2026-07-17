"""Setback states (SPEC.md §11.1): an ordinary lost fight is a recoverable
setback, never a game-over — true game-over is reserved for the demon king
and designated bosses (not built yet). This implements one coherent "captured"
package rather than several distinct mechanical systems for the spec's
captured/kidnapped/robbed/jailed language: some gold is taken on capture (the
"robbed" flavor), and the player is held — Move is blocked (see
actions._resolve_move) — until they either pay a ransom or wait out a fixed
number of days.

Two independent recovery paths, per SPEC.md §11.1's own wording ("a payable
ransom, a timed escape event"): `pay_ransom` (needs gold) and the guaranteed
timed release checked by `check_escape` (needs nothing but waiting). The
timed release is what actually satisfies "never an unwinnable soft-lock" — it
works even for a player captured with zero gold.
"""
from __future__ import annotations

from .models import Player

# Placeholder tuning constants — same "start rough, calibrate by feel" status
# as combat.py's DOT_DURATION etc. (SPEC.md §11).
GOLD_DOCK_FRACTION = 0.5
RANSOM_COST = 50
ESCAPE_AFTER_DAYS = 3


def capture_player(player: Player, current_day: int) -> list[str]:
    """Called from combat.run_combat on an ordinary lost fight. Docks some
    gold and enters the blocking captured state. Returns narration."""
    docked = int(player.gold * GOLD_DOCK_FRACTION)
    player.gold -= docked
    player.captured = True
    player.ransom_cost = RANSOM_COST
    player.free_by_day = current_day + ESCAPE_AFTER_DAYS

    log = ["You are captured!"]
    if docked:
        log.append(f"Your captors take {docked} gold.")
    log.append(
        f"Pay a {RANSOM_COST} gold ransom to go free immediately, or wait — "
        f"you'll find a chance to slip away by day {player.free_by_day} regardless."
    )
    return log


def pay_ransom(player: Player) -> list[str]:
    """The gold-based recovery path. Never mutates state on failure."""
    if not player.captured:
        return ["You are not captured."]
    if player.gold < player.ransom_cost:
        return [f"You need {player.ransom_cost} gold to pay the ransom; you only have {player.gold}."]

    player.gold -= player.ransom_cost
    _release(player)
    return ["You pay the ransom and go free."]


def check_escape(player: Player, current_day: int) -> list[str]:
    """The guaranteed, gold-free recovery path — called whenever the captured
    player waits (Rest). Returns narration if this wait crossed the
    guaranteed release day; an empty list otherwise (still held)."""
    if not player.captured or current_day < player.free_by_day:
        return []
    _release(player)
    return ["You find a chance to slip away — you are free!"]


def _release(player: Player) -> None:
    player.captured = False
    player.ransom_cost = 0
    player.free_by_day = None
