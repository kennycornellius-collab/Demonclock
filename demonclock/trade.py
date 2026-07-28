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
"""
from __future__ import annotations

from . import behavior
from .player import add_item, remove_item
from .state import GameState

TRADE_IMPACT_PER_UNIT = 1
TRADE_IMPACT_CAP = 5
MIN_PRICE = 1


def _impact(quantity: int) -> int:
    return min(quantity * TRADE_IMPACT_PER_UNIT, TRADE_IMPACT_CAP)


def buy(state: GameState, node_id: str, good_id: str, quantity: int) -> list[str]:
    """Never mutates state on failure (bad quantity, untracked good, not
    enough gold)."""
    if quantity < 1:
        return ["Quantity must be at least 1."]
    node = state.world.nodes[node_id]
    if good_id not in node.prices:
        return [f"{good_id.title()} isn't traded here."]

    price = node.prices[good_id]
    total_cost = price * quantity
    player = state.player
    if player.gold < total_cost:
        return [f"That costs {total_cost} gold; you only have {player.gold}."]

    player.gold -= total_cost
    add_item(player, good_id, good_id.title(), quantity)
    node.prices[good_id] = price + _impact(quantity)
    behavior.record_trade_action(player.behavior)
    return [f"You buy {quantity} {good_id.title()} for {total_cost} gold."]


def sell(state: GameState, node_id: str, good_id: str, quantity: int) -> list[str]:
    """Never mutates state on failure (bad quantity, untracked good, not
    enough of the good on hand)."""
    if quantity < 1:
        return ["Quantity must be at least 1."]
    node = state.world.nodes[node_id]
    if good_id not in node.prices:
        return [f"{good_id.title()} isn't traded here."]

    player = state.player
    if not remove_item(player, good_id, quantity):
        return [f"You don't have {quantity} {good_id.title()} to sell."]

    price = node.prices[good_id]
    total_gain = price * quantity
    player.gold += total_gain
    node.prices[good_id] = max(price - _impact(quantity), MIN_PRICE)
    behavior.record_trade_action(player.behavior)
    return [f"You sell {quantity} {good_id.title()} for {total_gain} gold."]
