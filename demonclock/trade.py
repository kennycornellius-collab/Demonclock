"""Trading (SPEC.md §12 step 10, Stage 1): buy/sell against a node's tracked
Node.prices. Single price both directions -- no in-node bid/ask spread, since
profit is geographic (economy.py's threat multiplier already makes the same
good cost more near danger; a safer node's lower price is the arbitrage).

A completed trade ALSO perturbs the node's own price (supply/demand), on top
of economy.py's existing threat-driven drift: buying nudges it up, selling
nudges it down, bounded per trade by TRADE_IMPACT_CAP. This needs zero
changes to economy.apply_price_shift -- its existing
`_step_toward(current, target, PRICE_STEP)` tick already pulls any given
price back toward its threat-driven target every day, so a trade's
perturbation is naturally temporary and reverts over subsequent ticks like
any other deviation would.

No node-side inventory cap (a market has unlimited stock at its current
price) and no clock cost (trading is an instant Interact action, same
footing as Look/Inventory) -- both "start rough, calibrate by feel" choices,
same status as every other tuning constant in this codebase.

"Faction standing: trade trigger" (updates.md, resolved 2026-07-31, Chunk
D): a completed trade at a faction-affiliated node (Node.faction_id, mirrors
NPC.faction_id) nudges standing up ONE tier -- but only once a single
trade's quantity clears TRADE_STANDING_THRESHOLD. STANDING_TIERS is a
coarse, whole-tier-only scale (factions.py), so a full tier per trade
(regardless of size) would let a player grind from neutral to allied via
many tiny repeated trades -- gating on quantity keeps "nudges standing
slightly" honest: an ordinary small trade does nothing, only real bulk
trade earns goodwill. Same "start rough, calibrate by feel" status as
TRADE_IMPACT_CAP/PRICE_STEP.
"""
from __future__ import annotations

from . import behavior, factions
from .player import add_item, display_name, remove_item
from .state import GameState

TRADE_IMPACT_PER_UNIT = 1
TRADE_IMPACT_CAP = 5
MIN_PRICE = 1
TRADE_STANDING_THRESHOLD = 10
TRADE_STANDING_BONUS_TIERS = 1


def _impact(quantity: int) -> int:
    return min(quantity * TRADE_IMPACT_PER_UNIT, TRADE_IMPACT_CAP)


def _apply_trade_standing_bonus(state: GameState, node, quantity: int) -> list[str]:
    """A silent no-op (same dangling-reference posture quests.
    _apply_faction_standing_delta/game._apply_npc_standing_penalty already
    take) whenever node has no faction_id, the quantity doesn't clear the
    threshold, or faction_id doesn't resolve to a real Faction."""
    if node.faction_id is None or quantity < TRADE_STANDING_THRESHOLD:
        return []
    if node.faction_id not in state.world.factions:
        return []
    new_tier = factions.adjust_standing(state.player, node.faction_id, TRADE_STANDING_BONUS_TIERS)
    faction_name = state.world.factions[node.faction_id].name
    return [f"Your standing with {faction_name} is now {new_tier}."]


def buy(state: GameState, node_id: str, good_id: str, quantity: int) -> list[str]:
    """Never mutates state on failure (bad quantity, untracked good, not
    enough gold)."""
    if quantity < 1:
        return ["Quantity must be at least 1."]
    node = state.world.nodes[node_id]
    if good_id not in node.prices:
        return [f"{display_name(good_id)} isn't traded here."]

    price = node.prices[good_id]
    total_cost = price * quantity
    player = state.player
    if player.gold < total_cost:
        return [f"That costs {total_cost} gold; you only have {player.gold}."]

    player.gold -= total_cost
    add_item(player, good_id, display_name(good_id), quantity)
    node.prices[good_id] = price + _impact(quantity)
    behavior.record_trade_action(player.behavior)
    lines = [f"You buy {quantity} {display_name(good_id)} for {total_cost} gold."]
    lines.extend(_apply_trade_standing_bonus(state, node, quantity))
    return lines


def sell(state: GameState, node_id: str, good_id: str, quantity: int) -> list[str]:
    """Never mutates state on failure (bad quantity, untracked good, not
    enough of the good on hand)."""
    if quantity < 1:
        return ["Quantity must be at least 1."]
    node = state.world.nodes[node_id]
    if good_id not in node.prices:
        return [f"{display_name(good_id)} isn't traded here."]

    player = state.player
    if not remove_item(player, good_id, quantity):
        return [f"You don't have {quantity} {display_name(good_id)} to sell."]

    price = node.prices[good_id]
    total_gain = price * quantity
    player.gold += total_gain
    node.prices[good_id] = max(price - _impact(quantity), MIN_PRICE)
    behavior.record_trade_action(player.behavior)
    lines = [f"You sell {quantity} {display_name(good_id)} for {total_gain} gold."]
    lines.extend(_apply_trade_standing_bonus(state, node, quantity))
    return lines
