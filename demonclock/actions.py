"""Action resolution (SPEC.md §6): the engine decides outcomes in code. This
part covers move/look/inventory/rest only — combat resolution is a later part.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import behavior, knowledge, newspaper, setback, sim
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


def _with_flavor(message: str, state: GameState, node_id: str) -> str:
    """Appends `world.node_flavor[node_id]` (Step 7 Chunk C) if a batch has
    ever generated one -- a pure PULL, never a live AI call, so this is a
    plain dict lookup on every Move/Look/fast-travel regardless of whether
    generation is even configured. Missing entirely (no generation
    configured, or this node's never been in a batch's bounded context yet)
    just means `message` comes back unchanged, same as before this existed."""
    flavor = state.world.node_flavor.get(node_id)
    return f"{message} {flavor}" if flavor else message


def _resolve_move(action: Action, state: GameState) -> Outcome:
    if state.player.captured:
        return Outcome("You are captured and can't move until you're free.", ok=False)
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
    knowledge.observe_node(state.player.beliefs, node, state.clock.current_day)
    message = (
        f"You travel {direction} to {node.name} ({link.travel_days} day(s) pass, "
        f"now day {state.clock.current_day})."
    )
    if tick_log:
        message += "\n" + "\n".join(tick_log)
    message = _with_flavor(message, state, node.id)
    return Outcome(message)


def resolve_fast_travel(state: GameState, destination_id: str) -> Outcome:
    """Multi-hop travel to a KNOWN node in one call (SPEC.md §3/§4: the Atlas
    is what fast-travel navigates by; instant teleport is forbidden, so this
    still advances the clock by the route's full `travel_days`, same as a
    manual hop, just without stopping to look around partway). Menu-only —
    triggered from game.handle_atlas, not routed through the free-text
    parser (same shape as setback.pay_ransom being called directly rather
    than through `resolve`)."""
    player = state.player
    if player.captured:
        return Outcome("You are captured and can't travel until you're free.", ok=False)
    if destination_id == player.location_id:
        return Outcome("You're already there.", ok=False)
    if destination_id not in player.beliefs:
        return Outcome("You don't know how to get there yet.", ok=False)

    route = state.world.shortest_path(player.location_id, destination_id)
    if route is None:
        return Outcome("There's no open route there right now.", ok=False)

    state.player.location_id = destination_id
    behavior.record_location(state.player.behavior, destination_id)
    tick_log = sim.advance_time(state, route.total_days)
    node = state.world.nodes[destination_id]
    knowledge.observe_node(state.player.beliefs, node, state.clock.current_day)
    message = (
        f"You fast-travel to {node.name} ({route.total_days} day(s) pass, "
        f"now day {state.clock.current_day})."
    )
    if tick_log:
        message += "\n" + "\n".join(tick_log)
    message = _with_flavor(message, state, node.id)
    return Outcome(message)


def _resolve_look(state: GameState) -> Outcome:
    node = state.world.nodes[state.player.location_id]
    knowledge.observe_node(state.player.beliefs, node, state.clock.current_day)
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
    message = _with_flavor(message, state, node.id)
    return Outcome(message)


def _resolve_inventory(state: GameState) -> Outcome:
    if not state.player.inventory:
        items_desc = "empty"
    else:
        items_desc = ", ".join(f"{item.name} x{item.quantity}" for item in state.player.inventory)
    hint = behavior.derived_role_hint(state.player.behavior)
    return Outcome(f"Gold: {state.player.gold}. Inventory: {items_desc}. You seem: {hint}.")


def _resolve_rest(state: GameState) -> Outcome:
    # Captured BEFORE the tick, so the newspaper's "leaked while asleep" diff
    # (newspaper.leaked_since) has a true before/after pair to compare — Rest
    # is the only action that shows a newspaper at all (SPEC.md §10 frames it
    # specifically as "on wake"; Move/fast-travel keep their existing
    # tick-log narration only).
    location_id = state.player.location_id
    day_before = state.clock.current_day
    tick_log = sim.advance_time(state, 1)
    player = state.player
    # The player was physically present at their own node the whole time
    # they rested, so anything the tick changed there is directly observed
    # (unlike a remote node, which stays fogged until visited).
    knowledge.observe_node(player.beliefs, state.world.nodes[player.location_id], state.clock.current_day)
    player.hp = min(player.hp_max, player.hp + player.hp_max // 4)
    player.mana = min(player.mana_max, player.mana + player.mana_max // 4)
    message = (
        f"You rest. A day passes (day {state.clock.current_day}). "
        f"HP {player.hp}/{player.hp_max}, MANA {player.mana}/{player.mana_max}."
    )
    if tick_log:
        message += "\n" + "\n".join(tick_log)

    leaked = newspaper.leaked_since(state.world, location_id, day_before, state.clock.current_day)
    newspaper_text = newspaper.format_newspaper(
        leaked, state.generation, behavior.derived_role_hint(player.behavior),
    )
    if newspaper_text:
        message += "\n" + newspaper_text

    if player.captured:
        escape_log = setback.check_escape(player, state.clock.current_day)
        if escape_log:
            message += "\n" + "\n".join(escape_log)
        else:
            message += (
                f"\nStill captured. Ransom {player.ransom_cost} gold (you have "
                f"{player.gold}), or free by day {player.free_by_day}."
            )
    return Outcome(message)
