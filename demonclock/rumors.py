"""Deterministic rumor propagation (SPEC.md §10, last of Step 3's four
stages). Every rumor traces back to a real fact in `history.LogEntry`
(`world.event_log`, Stage 3) — never an AI-invented one (SPEC.md §13).
A deliberately authored false plant would just be another `history.record`
call; nothing in this stage builds an authoring tool for one yet.

Rumors are computed fresh on every query, not stored. Propagation and
distortion are pure functions of the graph's CURRENT open-link topology
plus elapsed days since the source event — nothing about a rumor is
persisted, so a later map change (a link reopening, a new area falling)
is reflected immediately without ever needing to reconcile stale stored
propagation state against a changed graph.

KNOWN SIMPLIFICATION (start rough, calibrate later — SPEC.md §11): because
reachability is checked against TODAY's topology rather than a full
day-by-day historical replay, a rumor that would have had time to slip
through a link before it closed is NOT surfaced once that link is
permanently blocked — hearing nothing through a since-sealed border reads
as "that region went quiet" (the intended SPEC.md §10 signal) even for
news that, strictly, should have arrived earlier. Revisit with a real
historical replay only if this ever reads as a bug in play rather than as
the intended "quiet region" tell.

Hop count, not travel_days, is the metric here — SPEC.md §3 is explicit
that hop count is "fog/rumor spread radius" flavor, distinct from
travel_days (the real distance for actual travel). ~1 hop/day, over OPEN
links only: a blocked link stops rumor flow the same way it stops an army
(sim.py's invasion spread) or a traveler — "an occupied region going quiet
is itself a signal" (SPEC.md §10).

The AI's only permitted role, per SPEC.md §10, is wording a rumor at
narration time — it never invents rumor content. No AI is wired up yet
(that's Step 5), so `_distort` below uses a small deterministic template
table instead: real content, mechanically reworded by distance, not a
generated fact.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .world import World

HOPS_PER_DAY = 1

# Placeholder tuning constants — same status as combat.py's DOT_DURATION etc.
# (SPEC.md §11: start rough, calibrate by feel).
CONFIDENCE_DECAY_PER_HOP = 0.8
MIN_CONFIDENCE = 0.1

# Indexed by hop distance (clamped to the last entry beyond this length) —
# not randomness: the SAME event, asked about from the SAME distance,
# always distorts identically. Variety comes from distance, not chance.
_DISTORTION_TEMPLATES = [
    "{desc}",
    "Word has reached here: {desc}",
    "Travelers say: {desc}",
    "It's rumored, though hard to confirm this far out: {desc}",
]


@dataclass
class Rumor:
    origin_node_id: str
    day_originated: int
    hops: int
    confidence: float
    text: str


def _hop_distance(world: World, start_id: str, goal_id: str) -> int | None:
    """BFS over OPEN links only — a blocked link stops rumor flow exactly
    like it stops an army or a traveler. Hop count, never travel_days."""
    if start_id == goal_id:
        return 0
    visited = {start_id}
    frontier = deque([(start_id, 0)])
    while frontier:
        node_id, dist = frontier.popleft()
        for link in world.open_links_from(node_id):
            if link.to_id == goal_id:
                return dist + 1
            if link.to_id not in visited:
                visited.add(link.to_id)
                frontier.append((link.to_id, dist + 1))
    return None


def _confidence_for(hops: int) -> float:
    return max(MIN_CONFIDENCE, CONFIDENCE_DECAY_PER_HOP ** hops)


def _distort(description: str, hops: int) -> str:
    index = min(hops, len(_DISTORTION_TEMPLATES) - 1)
    return _DISTORTION_TEMPLATES[index].format(desc=description)


def rumors_reaching(world: World, node_id: str, current_day: int) -> list[Rumor]:
    """Every rumor that has had time to reach `node_id` by `current_day`,
    nearest (most confident, least distorted) first. A node never gets a
    rumor about its own logged events — you'd know that directly, not
    secondhand (see knowledge.py's belief layer for that channel).

    KNOWN SIMPLIFICATION (found in a caveat sweep, not yet fixed): runs a
    fresh BFS (`_hop_distance`) from EVERY entry in `world.event_log` on
    every single call, and `world.event_log` is append-only and never
    pruned (SPEC.md §9) — this function's cost grows with the total game
    history, not with anything bounded, the same category of problem
    SPEC.md §0 pillar 5 explicitly warns against for generation ("never
    let generation reason over the entire accumulated pile"), just applied
    to a different subsystem here. `game.handle_ask_around` also prints
    every rumor returned with no cap. Fine for a small hand-seeded world;
    revisit (a recency cutoff, an index by node, or a display cap) if a
    long playthrough's event log ever makes "Ask Around" noticeably slow
    or noisy."""
    rumors: list[Rumor] = []
    for entry in world.event_log:
        if entry.node_id == node_id:
            continue
        hops = _hop_distance(world, entry.node_id, node_id)
        if hops is None:
            continue
        elapsed = current_day - entry.day
        if elapsed < hops * HOPS_PER_DAY:
            continue
        rumors.append(Rumor(
            origin_node_id=entry.node_id,
            day_originated=entry.day,
            hops=hops,
            confidence=_confidence_for(hops),
            text=_distort(entry.description, hops),
        ))
    rumors.sort(key=lambda r: r.hops)
    return rumors
