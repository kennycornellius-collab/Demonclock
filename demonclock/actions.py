"""Action resolution (SPEC.md §6): the engine decides outcomes in code. This
part covers move/look/inventory/rest only — combat resolution is a later part.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import behavior, sim
from .parser import Action, ActionType
from .state import GameState


@dataclass
class Outcome:
    message: str
    ok: bool = True


def resolve(action: Action, state: GameState) -> Outcome:
    if action.type is ActionType.MOVE:
        return _resolve_move(action, state)
    if action.type is ActionType.LOOK:
        return _resolve_look(state)
    if action.type is ActionType.INVENTORY:
        return _resolve_inventory(state)
    if action.type is ActionType.REST:
        return _resolve_rest(state)
    if action.type is ActionType.HELP:
        return Outcome("Try: go <direction>, look, inventory, rest, help.")
    return Outcome(action.message or "I don't understand that.", ok=False)


def _resolve_move(action: Action, state: GameState) -> Outcome:
    if not action.target:
        return Outcome("Go where? Try 'go north'.", ok=False)

    direction = action.target
    candidates = [
        link for link in state.world.links_from(state.player.location_id)
        if link.direction == direction
    ]
    if not candidates:
        return Outcome(f"There's no path {direction} from here.", ok=False)

    link = candidates[0]
    if link.status != "open":
        reason = link.block_reason or "blocked"
        return Outcome(f"The way {direction} is blocked ({reason}).", ok=False)

    state.player.location_id = link.to_id
    behavior.record_location(state.player.behavior, link.to_id)
    tick_log = sim.advance_time(state, link.travel_days)
    node = state.world.nodes[link.to_id]
    message = (
        f"You travel {direction} to {node.name} ({link.travel_days} day(s) pass, "
        f"now day {state.clock.current_day})."
    )
    if tick_log:
        message += "\n" + "\n".join(tick_log)
    return Outcome(message)


def _resolve_look(state: GameState) -> Outcome:
    node = state.world.nodes[state.player.location_id]
    exits = state.world.open_links_from(state.player.location_id)
    if exits:
        exit_desc = ", ".join(
            f"{link.direction} -> {state.world.nodes[link.to_id].name}" for link in exits
        )
    else:
        exit_desc = "none"
    message = f"{node.name} ({node.type}, {node.state}). Exits: {exit_desc}."
    if node.prices:
        price_desc = ", ".join(f"{good} {price}g" for good, price in node.prices.items())
        message += f" Prices: {price_desc}."
    return Outcome(message)


def _resolve_inventory(state: GameState) -> Outcome:
    if not state.player.inventory:
        items_desc = "empty"
    else:
        items_desc = ", ".join(f"{item.name} x{item.quantity}" for item in state.player.inventory)
    hint = behavior.derived_role_hint(state.player.behavior)
    return Outcome(f"Gold: {state.player.gold}. Inventory: {items_desc}. You seem: {hint}.")


def _resolve_rest(state: GameState) -> Outcome:
    tick_log = sim.advance_time(state, 1)
    player = state.player
    player.hp = min(player.hp_max, player.hp + player.hp_max // 4)
    player.mana = min(player.mana_max, player.mana + player.mana_max // 4)
    message = (
        f"You rest. A day passes (day {state.clock.current_day}). "
        f"HP {player.hp}/{player.hp_max}, MANA {player.mana}/{player.mana_max}."
    )
    if tick_log:
        message += "\n" + "\n".join(tick_log)
    return Outcome(message)
