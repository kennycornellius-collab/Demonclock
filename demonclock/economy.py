"""Node price tracking (SPEC.md §4/§7/§10 — "grain prices spike" as an
ambient pressure source / fog-of-war economy tell). Stage 3 of world
simulation (SPEC.md §12 step 2).

Kept intentionally small: one good (`grain`, SPEC's own named example), no
baseline drift while nothing threatens the area — there's no RNG anywhere in
this project yet, and inventing arbitrary peacetime noise wouldn't correspond
to anything SPEC describes, so a safe node's price simply holds steady.
Movement is driven entirely by Stage 2's `occupied` node state: an occupied
node's prices spike, and so do its neighbors' — the market hears the news
before it falls. No buy/sell trading exists yet — that's a future
Interact->Trade menu (SPEC.md §6), a separate build item; this stage only
proves prices are live, drifting world state the player can read as a
signal.
"""
from __future__ import annotations

from .state import GameState
from .world import World

BASE_PRICE: dict[str, int] = {"grain": 10}

# The target price for any good with no explicit BASE_PRICE entry above —
# same "start rough, calibrate by feel" status as PRICE_STEP. Deliberate
# and documented (Step 8 P3), unlike falling back to a good's own live
# `current` price (that fallback never converges: the target recomputes off
# the same moving value every tick, so an occupied node's price for an
# untracked good drifted upward forever instead of stabilizing at a fixed
# multiple like grain does).
DEFAULT_BASE_PRICE = 10

PRICE_STEP = 1  # max change per tick, per good — same "start rough,
                # calibrate by feel" status as combat.py's tuning constants
OCCUPIED_MULTIPLIER = 2.0
NEAR_DANGER_MULTIPLIER = 1.5
SAFE_MULTIPLIER = 1.0


def _threat_multiplier(node_id: str, world: World) -> float:
    node = world.nodes[node_id]
    if node.state == "occupied":
        return OCCUPIED_MULTIPLIER
    # Any adjacency counts, not just an open link — the market doesn't need
    # an open road to hear that its neighbor fell.
    neighbor_occupied = any(
        world.nodes[link.to_id].state == "occupied"
        for link in world.links_from(node_id)
    )
    return NEAR_DANGER_MULTIPLIER if neighbor_occupied else SAFE_MULTIPLIER


def _step_toward(current: int, target: int, step: int) -> int:
    if current < target:
        return min(current + step, target)
    if current > target:
        return max(current - step, target)
    return current


def apply_price_shift(state: GameState) -> list[str]:
    """One tick of price drift across every node that has any tracked
    prices. Moves at most PRICE_STEP per good per tick toward a threat-driven
    target — never jumps straight there. Only nodes that actually moved get a
    narration line (mirrors Stages 1-2's "only narrate real change").

    Every good converges, not just ones in `BASE_PRICE` (Step 8 P3): a good
    with no explicit entry there falls back to the fixed `DEFAULT_BASE_PRICE`
    rather than its own live `current` price, so its target is stable across
    ticks instead of recomputing off a value that's itself still moving."""
    world = state.world
    log: list[str] = []
    for node in world.nodes.values():
        if not node.prices:
            continue
        multiplier = _threat_multiplier(node.id, world)
        for good_id, current in list(node.prices.items()):
            base = BASE_PRICE.get(good_id, DEFAULT_BASE_PRICE)
            target = round(base * multiplier)
            new_price = _step_toward(current, target, PRICE_STEP)
            if new_price == current:
                continue
            node.prices[good_id] = new_price
            direction = "rise" if new_price > current else "fall"
            log.append(f"{good_id.title()} prices {direction} to {new_price} gold at {node.name}.")
    return log
