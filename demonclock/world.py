"""The graph map. SPEC.md §3: nodes + directional links, no coordinates.

Two invariants enforced HERE (not by convention — see tests/test_world.py):
  - add_link always writes both directional rows unless one_way=True.
  - block_link always flips both directional rows unless directional_block=True.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

from .events import ScheduledEvent
from .history import LogEntry
from .models import OPPOSITE_DIRECTION, Link, Node
from .pool import GeneratedItem


class WorldError(ValueError):
    pass


@dataclass
class Route:
    links: list[Link]
    total_days: int


class World:
    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.links: dict[str, list[Link]] = {}  # from_id -> outgoing Links
        self.scheduled_events: list[ScheduledEvent] = []  # SPEC.md §3/§12 step 2
        # Append-only history log (SPEC.md §9) — grows forever, only ever
        # appended to via history.record, never pruned like scheduled_events.
        self.event_log: list[LogEntry] = []
        # Generated-content pool (SPEC.md §7/§8) — mutated via pool.py's
        # commit_or_repair (append) and pull (pop). Nothing writes to this
        # yet (Step 5); the list exists now so persistence is already
        # correct once a real generator does.
        self.content_pool: list[GeneratedItem] = []
        # Which node the demon-king invasion (sim._apply_invasion_spread)
        # originates from — set by content (seed.py), never inferred by the
        # engine. Once the whole graph has fallen, that node is retagged
        # "demon_king" (see sim._reveal_demon_king), making the boss fight
        # reachable via game.py's Interact. None means "no invasion origin
        # configured" — the reveal step is then a no-op, so a minimal/test
        # world with no invasion content is unaffected.
        self.invasion_origin_id: str | None = None
        # Ambient per-node flavor lines (SPEC.md §2/§10, Step 7 Chunk C) --
        # AI-generated atmosphere, refreshed for whichever nodes a batch's
        # bounded context covered (generation/flavor.py), PULLED by
        # actions.py's look/arrival narration rather than generated live.
        # Purely cosmetic: never a fact, never validated by the canon check
        # (nothing here implies a state change), so a stale or missing entry
        # for any given node is harmless -- the caller just shows nothing
        # extra, same as before this existed.
        self.node_flavor: dict[str, str] = {}

    # -- construction --------------------------------------------------

    def add_node(self, node: Node) -> Node:
        self.nodes[node.id] = node
        return node

    def add_link(
        self,
        from_id: str,
        to_id: str,
        direction: str,
        travel_days: int,
        *,
        one_way: bool = False,
    ) -> Link:
        """Bidirectional-by-construction link (SPEC.md §3). Writes from->to,
        and unless one_way, atomically writes the reverse to->from too.

        KNOWN SIMPLIFICATION (found in a caveat sweep, not yet fixed): this
        enforces "has a known opposite" and "travel_days >= 1" but does NOT
        check whether `from_id` already has an outgoing link in the same
        `direction`. Two links sharing a direction from one node are
        silently both stored; `actions._resolve_move` matches by direction
        string and always takes the first one found, so the second becomes
        permanently unreachable via ordinary Move (though still reachable
        via `shortest_path`/fast-travel, which doesn't key off direction) —
        with no error anywhere. `generation/places.py`'s `materialize` is a
        real caller that can trigger this (a proposed direction colliding
        with the anchor node's existing link) and does not currently guard
        against it either. Revisit by having `add_link` reject (or
        `materialize` pre-check) a direction collision at `from_id` before
        this becomes a live, AI-generated dead end."""
        if from_id not in self.nodes:
            raise WorldError(f"unknown node id: {from_id!r}")
        if to_id not in self.nodes:
            raise WorldError(f"unknown node id: {to_id!r}")
        if travel_days < 1:
            raise WorldError("travel_days must be >= 1")

        forward = Link(from_id, to_id, direction, travel_days, one_way=one_way)
        self.links.setdefault(from_id, []).append(forward)

        if not one_way:
            opposite = OPPOSITE_DIRECTION.get(direction)
            if opposite is None:
                raise WorldError(
                    f"no known opposite for direction {direction!r}; "
                    "pass one_way=True for a deliberate one-way link"
                )
            reverse = Link(to_id, from_id, opposite, travel_days, one_way=one_way)
            self.links.setdefault(to_id, []).append(reverse)

        return forward

    def schedule_event(self, event: ScheduledEvent) -> ScheduledEvent:
        """The one insertion point for queuing a scheduled event — later
        world-simulation stages (invasion, price shifts) schedule through
        here too, same rationale as add_link being the one place a link gets
        created."""
        self.scheduled_events.append(event)
        return event

    # -- queries ---------------------------------------------------------

    def all_links(self) -> list[Link]:
        return [link for links in self.links.values() for link in links]

    def get_link(self, from_id: str, to_id: str) -> Link | None:
        for link in self.links.get(from_id, []):
            if link.to_id == to_id:
                return link
        return None

    def open_links_from(self, node_id: str) -> list[Link]:
        return [link for link in self.links.get(node_id, []) if link.status == "open"]

    def links_from(self, node_id: str) -> list[Link]:
        """All links regardless of status — lets callers explain WHY a
        direction is unavailable (blocked with a reason) instead of just
        saying it doesn't exist."""
        return list(self.links.get(node_id, []))

    # -- state flips -------------------------------------------------------

    def block_link(
        self,
        from_id: str,
        to_id: str,
        reason: str,
        *,
        directional_block: bool = False,
    ) -> None:
        """Flips the from->to link to blocked. Unless directional_block, also
        flips the reverse to->from row atomically (SPEC.md §3/§13)."""
        forward = self.get_link(from_id, to_id)
        if forward is None:
            raise WorldError(f"no link {from_id!r} -> {to_id!r}")
        forward.status = "blocked"
        forward.block_reason = reason

        if not directional_block:
            reverse = self.get_link(to_id, from_id)
            if reverse is not None:
                reverse.status = "blocked"
                reverse.block_reason = reason

    def unblock_link(
        self,
        from_id: str,
        to_id: str,
        *,
        directional_block: bool = False,
    ) -> None:
        forward = self.get_link(from_id, to_id)
        if forward is None:
            raise WorldError(f"no link {from_id!r} -> {to_id!r}")
        forward.status = "open"
        forward.block_reason = None

        if not directional_block:
            reverse = self.get_link(to_id, from_id)
            if reverse is not None:
                reverse.status = "open"
                reverse.block_reason = None

    # -- pathfinding ---------------------------------------------------

    def shortest_path(self, start_id: str, goal_id: str) -> Route | None:
        """Dijkstra over OPEN links, cost = sum of travel_days (SPEC.md §3/§4:
        travel_days is the real distance metric, hop count is not)."""
        if start_id == goal_id:
            return Route(links=[], total_days=0)

        best_cost: dict[str, int] = {start_id: 0}
        best_link_in: dict[str, Link] = {}
        prev: dict[str, str] = {}
        frontier: list[tuple[int, str]] = [(0, start_id)]
        visited: set[str] = set()

        while frontier:
            cost, node_id = heapq.heappop(frontier)
            if node_id in visited:
                continue
            visited.add(node_id)
            if node_id == goal_id:
                break
            for link in self.open_links_from(node_id):
                new_cost = cost + link.travel_days
                if new_cost < best_cost.get(link.to_id, float("inf")):
                    best_cost[link.to_id] = new_cost
                    best_link_in[link.to_id] = link
                    prev[link.to_id] = node_id
                    heapq.heappush(frontier, (new_cost, link.to_id))

        if goal_id not in best_cost:
            return None

        route: list[Link] = []
        node_id = goal_id
        while node_id != start_id:
            link = best_link_in[node_id]
            route.append(link)
            node_id = prev[node_id]
        route.reverse()
        return Route(links=route, total_days=best_cost[goal_id])
