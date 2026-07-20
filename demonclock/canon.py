"""The canon check (SPEC.md §8) — the "immune system" gating every
generated item before it's committed as real (SPEC.md §0 pillar 6: "AI
proposes, engine enforces invariants"). This stage builds only the
pure-code checker half: a precondition manifest is a tidy list of
booleans validated against the live DB, never parsed prose ("the checker
validates a tidy list of booleans against the DB — it does NOT parse
prose for hidden landmines").

`RequirementKind` is a fixed enumerated vocabulary, same "enum, never free
text" discipline as `skills.py`'s effects / `events.py`'s `EventKind`
(SPEC.md §13). It only covers the entity types that actually exist in the
engine today (nodes, links, the player) — SPEC.md §8's own worked example
`faction_standing(merchants): >= neutral` has no engine-side analog yet
(no factions exist), so it's deliberately not in this enum; extend it
when the entity type it checks actually exists, same discipline
`EventKind` has followed stage by stage.

Nothing generates real items yet (that's Step 5) — this module is
exercised with hand-built manifests until then, same "prove the plumbing
correct before there's real content to run through it" shape as
world-sim Stage 1 (timers) and knowledge Stage 1 (belief) both had.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .state import GameState


class RequirementKind(str, Enum):
    NODE_STATE = "node_state"
    LINK_STATUS = "link_status"
    PLAYER_HAS_ITEM = "player_has_item"
    PLAYER_HAS_SKILL = "player_has_skill"
    PLAYER_GOLD_AT_LEAST = "player_gold_at_least"
    PLAYER_NOT_CAPTURED = "player_not_captured"


@dataclass
class Requirement:
    kind: RequirementKind
    target: dict  # kind-specific keys, e.g. {"node_id": "wilds", "state": "occupied"}

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "target": self.target}

    @staticmethod
    def from_dict(data: dict) -> Requirement:
        return Requirement(kind=RequirementKind(data["kind"]), target=data["target"])


@dataclass
class PreconditionManifest:
    requirements: list[Requirement] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"requirements": [r.to_dict() for r in self.requirements]}

    @staticmethod
    def from_dict(data: dict) -> PreconditionManifest:
        return PreconditionManifest(
            requirements=[Requirement.from_dict(r) for r in data.get("requirements", [])]
        )


@dataclass
class RequirementResult:
    requirement: Requirement
    passed: bool
    reason: str


@dataclass
class CheckResult:
    results: list[RequirementResult]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> list[RequirementResult]:
        return [r for r in self.results if not r.passed]


def check_manifest(state: GameState, manifest: PreconditionManifest) -> CheckResult:
    """Validates every requirement's boolean against the live DB. Never
    raises on a dangling reference (an unknown node/link/item id) — that's
    just a failed requirement with an explanatory reason, the same as any
    other mismatch, so a stale manifest degrades to "repair or reject"
    rather than crashing the checker."""
    return CheckResult([_check_one(state, req) for req in manifest.requirements])


def _check_one(state: GameState, req: Requirement) -> RequirementResult:
    if req.kind is RequirementKind.NODE_STATE:
        node = state.world.nodes.get(req.target["node_id"])
        if node is None:
            return RequirementResult(req, False, f"unknown node: {req.target['node_id']!r}")
        expected = req.target["state"]
        passed = node.state == expected
        return RequirementResult(req, passed, f"node state is {node.state!r}, expected {expected!r}")

    if req.kind is RequirementKind.LINK_STATUS:
        link = state.world.get_link(req.target["from_id"], req.target["to_id"])
        if link is None:
            return RequirementResult(req, False, f"unknown link: {req.target['from_id']!r} -> {req.target['to_id']!r}")
        expected = req.target["status"]
        passed = link.status == expected
        return RequirementResult(req, passed, f"link status is {link.status!r}, expected {expected!r}")

    if req.kind is RequirementKind.PLAYER_HAS_ITEM:
        expected = req.target["expected"]
        has_item = any(item.item_id == req.target["item_id"] for item in state.player.inventory)
        passed = has_item == expected
        return RequirementResult(req, passed, f"player has_item={has_item}, expected {expected}")

    if req.kind is RequirementKind.PLAYER_HAS_SKILL:
        expected = req.target["expected"]
        has_skill = any(skill.id == req.target["skill_id"] for skill in state.player.skills)
        passed = has_skill == expected
        return RequirementResult(req, passed, f"player has_skill={has_skill}, expected {expected}")

    if req.kind is RequirementKind.PLAYER_GOLD_AT_LEAST:
        amount = req.target["amount"]
        passed = state.player.gold >= amount
        return RequirementResult(req, passed, f"player has {state.player.gold} gold, needs >= {amount}")

    if req.kind is RequirementKind.PLAYER_NOT_CAPTURED:
        passed = not state.player.captured
        return RequirementResult(req, passed, f"player captured={state.player.captured}")

    raise ValueError(f"unhandled requirement kind: {req.kind!r}")  # unreachable given RequirementKind's closed enum
