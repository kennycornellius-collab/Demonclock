"""Assembles the bounded retrieved slice every generation-pipeline agent
reads from (SPEC.md §7/§9's "generation always runs against live entities +
relevant retrieved history, never the entire accumulated content"). This is
the single place that invariant is enforced for the batch pipeline -- Director
(Chunk B), Story/Quest (Chunk C), and Places (Chunk D) all read from the dict
this builds, never from `state.world` directly.

Deliberately narrow: the player's current node + its immediate neighbors
(world TRUTH, not player belief -- the Director/generators reason over what
the world actually is, same as the canon check does; belief is a player-facing
concept, not a generation-context one), the behavior profile, and only the
last few `event_log` entries -- never the whole graph or the whole log.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..behavior import derived_role_hint
from ..models import Node

if TYPE_CHECKING:
    from ..state import GameState

# How many of the most recent world.event_log entries to include -- a small,
# fixed bound, same "start rough" status as every other placeholder constant
# in this codebase.
RECENT_EVENT_LIMIT = 5


def build_batch_context(state: GameState) -> dict:
    world = state.world
    player = state.player
    current_node = world.nodes[player.location_id]
    neighbor_nodes = [world.nodes[link.to_id] for link in world.links_from(player.location_id)]

    return {
        "day": state.clock.current_day,
        "player": {
            "location_id": current_node.id,
            "gold": player.gold,
            "derived_role_hint": derived_role_hint(player.behavior),
            "gold_trend": player.behavior.gold_trend,
        },
        "current_node": _node_truth(current_node),
        "neighbor_nodes": [_node_truth(node) for node in neighbor_nodes],
        "recent_events": [
            {
                "day": entry.day,
                "node_id": entry.node_id,
                "kind": entry.kind.value,
                "description": entry.description,
            }
            for entry in world.event_log[-RECENT_EVENT_LIMIT:]
        ],
    }


def _node_truth(node: Node) -> dict:
    return {
        "id": node.id,
        "name": node.name,
        "type": node.type,
        "state": node.state,
        "tags": list(node.tags),
        "prices": dict(node.prices),
    }
