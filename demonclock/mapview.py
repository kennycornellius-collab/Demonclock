"""ASCII adjacency rendering for Atlas (updates.md, surfaced 2026-07-29): a
text-art layout of discovered places over their graph links, instead of
Atlas's existing flat alphabetical list (which is accurate to SPEC.md §10's
belief model but doesn't convey "the world is a graph", CLAUDE.md §3, the
way an adjacency sketch would).

Governed by Player.beliefs the same way the rest of Atlas already is --
only nodes the player has ever seen appear at all -- but link CONNECTIVITY
itself (whether two known nodes are directly linked) is drawn from live
World.links, the same real topology fast-travel's own world.shortest_path
already crosses; this module adds no new belief layer, and deliberately
does not distinguish an open vs. blocked link on the grid (both draw the
same connector) to stay as close to "presentation over existing belief
data, not a new truth channel" as a 2D layout allows.

A simple axis-aligned grid, not a general graph-layout solver: only
north/south/east/west links (models.OPPOSITE_DIRECTION's compass pairs)
place a node relative to its neighbor -- up/down/in/out and any other
custom direction (a one-way link can carry an arbitrary string) can't be
projected onto 2 axes, so a node only ever reachable that way is listed as
a text footnote instead of drawn. A node reached a second time via a link
whose implied position conflicts with its already-assigned coordinate
(e.g. a loop that doesn't close on a 4-direction grid) simply keeps its
first-assigned position -- KNOWN SIMPLIFICATION: that link's own connector
just won't be drawn (the two nodes still show up correctly, just without a
line between them), rather than this module attempting a general planar
graph-layout solve.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GameState

_COMPASS_DELTA: dict[str, tuple[int, int]] = {
    "north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0),
}


def _placements(state: GameState, start_id: str, known_ids: set[str]) -> dict[str, tuple[int, int]]:
    """BFS over live World links, restricted to compass directions and to
    nodes the player has a belief about."""
    world = state.world
    positions: dict[str, tuple[int, int]] = {start_id: (0, 0)}
    frontier = [start_id]
    while frontier:
        next_frontier = []
        for current in frontier:
            x, y = positions[current]
            for link in world.links_from(current):
                delta = _COMPASS_DELTA.get(link.direction)
                if delta is None or link.to_id not in known_ids or link.to_id in positions:
                    continue
                positions[link.to_id] = (x + delta[0], y + delta[1])
                next_frontier.append(link.to_id)
        frontier = next_frontier
    return positions


def render(state: GameState, labels: dict[str, str]) -> str | None:
    """`labels` maps node_id -> the short marker to draw for it -- game.py
    passes the same numbers its Atlas list already assigns, so the map and
    the fast-travel picker line up 1:1. Returns None if fewer than 2 of the
    player's known nodes can be placed on the grid (nothing useful to draw,
    e.g. a fresh game that only knows its own starting node)."""
    known_ids = set(state.player.beliefs)
    if not known_ids:
        return None
    start_id = state.player.location_id if state.player.location_id in known_ids else next(iter(known_ids))
    positions = _placements(state, start_id, known_ids)
    if len(positions) < 2:
        return None

    world = state.world
    by_pos = {pos: node_id for node_id, pos in positions.items()}
    xs = [pos[0] for pos in positions.values()]
    ys = [pos[1] for pos in positions.values()]
    cell_width = max(4, max(len(labels[node_id]) for node_id in positions) + 2)

    def linked(a_id: str | None, b_id: str | None, direction: str) -> bool:
        if a_id is None or b_id is None:
            return False
        return any(link.to_id == b_id and link.direction == direction for link in world.links_from(a_id))

    lines: list[str] = []
    for y in range(max(ys), min(ys) - 1, -1):
        row: list[str] = []
        for x in range(min(xs), max(xs) + 1):
            node_id = by_pos.get((x, y))
            row.append((labels[node_id] if node_id else "").center(cell_width))
            if x < max(xs):
                east_linked = linked(node_id, by_pos.get((x + 1, y)), "east")
                row.append(("-" * (cell_width - 2)).center(cell_width) if east_linked else " " * cell_width)
        lines.append("".join(row))

        if y > min(ys):
            column: list[str] = []
            for x in range(min(xs), max(xs) + 1):
                node_id = by_pos.get((x, y))
                south_linked = linked(node_id, by_pos.get((x, y - 1)), "south")
                column.append("|".center(cell_width) if south_linked else " " * cell_width)
                if x < max(xs):
                    column.append(" " * cell_width)
            lines.append("".join(column))

    unplaced = sorted(known_ids - positions.keys(), key=lambda node_id: world.nodes[node_id].name)
    if unplaced:
        names = ", ".join(world.nodes[node_id].name for node_id in unplaced)
        lines.append("")
        lines.append(f"Also known (no direct compass route shown): {names}")

    return "\n".join(line.rstrip() for line in lines)
