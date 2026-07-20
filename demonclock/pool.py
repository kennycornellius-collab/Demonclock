"""The content pool + repair-or-reject loop (SPEC.md §7/§8, second of Step
4's three chunks). Generated items are never shown live — a generator
writes them to a pool and the daytime loop pulls from it later (SPEC.md
§7). Every item's precondition manifest (canon.py, Chunk A) is checked
TWICE: once here at commit time, and again at pull time, since the world
keeps moving between generation and consumption — an item valid when
generated can go stale before it's ever drawn (SPEC.md §8: "an NPC
referenced by a pooled quest can die from a world-timer event before the
player ever draws that quest").

Nothing generates real items yet (Step 5) — `GeneratedItem.payload` is a
deliberately opaque dict; this chunk only builds the pool's commit/pull
machinery and proves it correct against hand-built items and a caller-
supplied repair callback, same as canon.py did for the checker itself.
The pool is a plain `list[GeneratedItem]`, mutated in place (append on
commit, pop on pull) — the same convention `World.scheduled_events` and
`World.event_log` already use, not a wrapper class.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

from .canon import PreconditionManifest, RequirementResult, check_manifest

if TYPE_CHECKING:
    from .state import GameState


@dataclass
class GeneratedItem:
    id: str
    payload: dict
    manifest: PreconditionManifest

    def to_dict(self) -> dict:
        return {"id": self.id, "payload": self.payload, "manifest": self.manifest.to_dict()}

    @staticmethod
    def from_dict(data: dict) -> GeneratedItem:
        return GeneratedItem(
            id=data["id"], payload=data["payload"],
            manifest=PreconditionManifest.from_dict(data["manifest"]),
        )


class CommitOutcome(str, Enum):
    COMMITTED = "committed"
    REPAIRED = "repaired"
    REJECTED = "rejected"


@dataclass
class CommitResult:
    outcome: CommitOutcome
    item: GeneratedItem | None  # the item now in the pool, if COMMITTED or REPAIRED
    failures: list[RequirementResult] = field(default_factory=list)  # populated only on REJECTED


# A repair callback gets the failing item and the specific requirements
# that failed, and either hands back a patched item or gives up (None) —
# "prefer repair over rejection... reject only when repair can't salvage
# it" (SPEC.md §8). No real repair logic exists yet (that needs an actual
# generator, Step 5); tests supply a synthetic one.
RepairFn = Callable[[GeneratedItem, list[RequirementResult]], "GeneratedItem | None"]


def commit_or_repair(
    state: GameState, pool: list[GeneratedItem], item: GeneratedItem,
    repair_fn: RepairFn | None = None,
) -> CommitResult:
    """Validates `item`'s manifest against live state. Passes straight
    through to the pool if it already holds; otherwise offers `repair_fn`
    one targeted patch attempt (re-validated, never trusted blindly — a
    repair that still doesn't satisfy its own manifest is rejected, not
    silently accepted); rejects outright with no `repair_fn` at all."""
    result = check_manifest(state, item.manifest)
    if result.passed:
        pool.append(item)
        return CommitResult(CommitOutcome.COMMITTED, item)

    if repair_fn is not None:
        repaired = repair_fn(item, result.failures)
        if repaired is not None:
            repaired_result = check_manifest(state, repaired.manifest)
            if repaired_result.passed:
                pool.append(repaired)
                return CommitResult(CommitOutcome.REPAIRED, repaired)
            return CommitResult(CommitOutcome.REJECTED, None, repaired_result.failures)

    return CommitResult(CommitOutcome.REJECTED, None, result.failures)


def pull(state: GameState, pool: list[GeneratedItem]) -> GeneratedItem | None:
    """Draws the oldest item whose manifest still holds against LIVE state
    (SPEC.md §8: re-validated at pull time, not just commit time). Items
    found stale along the way are silently discarded — popped off the
    pool, never returned, never left for a later pull to trip over again;
    "a stale item must never reach the player." Returns None once the pool
    is empty or every remaining item turned out stale."""
    while pool:
        item = pool.pop(0)
        if check_manifest(state, item.manifest).passed:
            return item
    return None
