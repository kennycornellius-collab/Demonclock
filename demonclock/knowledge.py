"""World truth vs. player belief (SPEC.md §10, first of Step 3's stages).

World truth lives on `Node` itself and updates on the world's own timer
(sim.py) regardless of what the player knows. Player belief is a separate,
per-player snapshot of what that node looked like the last time the player
actually stood on it. Fog is simply the gap between the two — a node with
no belief entry has never been observed at all.

The one non-negotiable invariant (SPEC.md §13): belief is never silently
overwritten by truth. `observe_node` is the ONLY function in the codebase
allowed to write a belief entry, and it is only ever called from an
explicit act of physical observation (arriving at / looking around a node)
— never from the world-sim tick.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Node


@dataclass
class NodeBelief:
    state: str
    tags: list[str] = field(default_factory=list)
    prices: dict[str, int] = field(default_factory=dict)
    last_seen_day: int = 0

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "tags": list(self.tags),
            "prices": dict(self.prices),
            "last_seen_day": self.last_seen_day,
        }

    @staticmethod
    def from_dict(data: dict) -> NodeBelief:
        return NodeBelief(
            state=data["state"],
            tags=list(data.get("tags", [])),
            prices=dict(data.get("prices", {})),
            last_seen_day=data["last_seen_day"],
        )


def observe_node(beliefs: dict[str, NodeBelief], node: Node, current_day: int) -> None:
    """Overwrite `beliefs[node.id]` with a fresh snapshot of `node`'s current
    truth, stamped with `current_day`. Called wherever the player physically
    perceives a node (arriving via Move, looking around) — see actions.py."""
    beliefs[node.id] = NodeBelief(
        state=node.state,
        tags=list(node.tags),
        prices=dict(node.prices),
        last_seen_day=current_day,
    )
