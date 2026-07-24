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

from .history import LogEntry
from .world import World

HOPS_PER_DAY = 1

# Placeholder tuning constants — same status as combat.py's DOT_DURATION etc.
# (SPEC.md §11: start rough, calibrate by feel).
CONFIDENCE_DECAY_PER_HOP = 0.8
MIN_CONFIDENCE = 0.1

# Step 8 P5: bounds rumors_reaching's cost to a recent window instead of the
# whole, never-pruned event_log (SPEC.md §0 pillar 5's "never reason over the
# entire accumulated pile," applied here too) — an event this old is already
# old news, not live gossip. Same "start rough, calibrate by feel" status as
# every other tuning constant here.
MAX_RUMOR_AGE_DAYS = 30

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


def _recent_entries(world: World, current_day: int) -> list[LogEntry]:
    """The slice of `world.event_log` within `MAX_RUMOR_AGE_DAYS` (Step 8
    P5). `event_log` is append-only and always appended in non-decreasing
    `day` order (every entry is stamped with the clock's current day at the
    moment it fires, and the clock never runs backward — see sim.py's tick
    ordering), so walking backward from the newest entry and stopping the
    instant one is too old bounds the scan to the recent window itself,
    rather than filtering the whole ever-growing list on every call."""
    recent: list[LogEntry] = []
    for entry in reversed(world.event_log):
        if current_day - entry.day > MAX_RUMOR_AGE_DAYS:
            break
        recent.append(entry)
    return recent


def rumors_reaching(world: World, node_id: str, current_day: int) -> list[Rumor]:
    """Every rumor from the last MAX_RUMOR_AGE_DAYS that has had time to
    reach `node_id` by `current_day`, nearest (most confident, least
    distorted) first. A node never gets a rumor about its own logged
    events — you'd know that directly, not secondhand (see knowledge.py's
    belief layer for that channel).

    Bounded cost (Step 8 P5): only runs a fresh BFS (`_hop_distance`) per
    entry in the recent window (`_recent_entries`), not per entry in the
    whole, never-pruned `world.event_log` — this function's cost no longer
    grows with total game history, the same "bounded retrieved slice"
    discipline `generation/context.py` already enforces for generation,
    applied here too. `newspaper.leaked_since` calls this function TWICE per
    Rest (a before/after snapshot), so this bound benefits both call sites,
    not just a manual Ask Around."""
    rumors: list[Rumor] = []
    for entry in _recent_entries(world, current_day):
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
