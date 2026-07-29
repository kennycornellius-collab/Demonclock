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

from . import factions

if TYPE_CHECKING:
    from .state import GameState


class RequirementKind(str, Enum):
    NODE_STATE = "node_state"
    LINK_STATUS = "link_status"
    PLAYER_HAS_ITEM = "player_has_item"
    PLAYER_HAS_SKILL = "player_has_skill"
    PLAYER_GOLD_AT_LEAST = "player_gold_at_least"
    PLAYER_NOT_CAPTURED = "player_not_captured"
    # Step 10 Stage 2 (quest completion/turn-in): PLAYER_HAS_ITEM's own
    # `expected: bool` semantics are deliberately untouched (a plain
    # has-it-at-all check) — this is a separate, quantity-aware kind for a
    # "bring me 5 grain" objective, mirroring PLAYER_GOLD_AT_LEAST's own
    # `amount` key rather than overloading PLAYER_HAS_ITEM's target shape.
    PLAYER_HAS_ITEM_QUANTITY_AT_LEAST = "player_has_item_quantity_at_least"
    # Step 10 Stage 4 (SPEC §8's own worked example: "faction_standing
    # (merchants): >= neutral"): target {faction_id, tier}, tier one of
    # factions.STANDING_TIERS. No live trigger moves standing yet this
    # stage — this is the checker half only, same "prove the plumbing
    # before real content wires through it" shape every other
    # RequirementKind here took.
    FACTION_STANDING_AT_LEAST = "faction_standing_at_least"


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
    raises on a dangling reference (an unknown node/link/item id) OR a
    malformed one (a target dict missing the keys this kind needs) — both
    are just a failed requirement with an explanatory reason, the same as
    any other mismatch, so a stale OR malformed manifest degrades to
    "repair or reject" rather than crashing the checker. The malformed case
    matters specifically because `target`'s JSON schema is just `{"type":
    "object"}` (the hand-rolled schema validator can't express "these keys
    are required, conditional on `kind`"), so nothing structurally stops a
    real LLM from emitting a `NODE_STATE` requirement with no `node_id` —
    confirmed live, not hypothetical (a real batch crashed the whole game
    via an uncaught `KeyError` here before this fix)."""
    return CheckResult([_check_one(state, req) for req in manifest.requirements])


def _malformed(req: Requirement) -> RequirementResult:
    return RequirementResult(req, False, f"malformed {req.kind.value} requirement target: {req.target!r}")


def _is_number(value: object) -> bool:
    """Same whole-number-float-counts leniency as `llm/schema.py`'s own
    `_is_integer` (Step 8 P6) — a provider serializing an amount as `5.0`
    is still a valid amount, but a `bool` (a Python `int` subclass) is not.
    Guards `PLAYER_GOLD_AT_LEAST`/`PLAYER_HAS_ITEM_QUANTITY_AT_LEAST`'s `>=`
    comparisons from crashing on a present-but-non-numeric `amount` — the
    same "a dangling/invalid value fails gracefully, never raises" contract
    `FACTION_STANDING_AT_LEAST`'s own `tier` check already enforces below."""
    if isinstance(value, bool):
        return False
    return isinstance(value, (int, float))


def _check_one(state: GameState, req: Requirement) -> RequirementResult:
    if req.kind is RequirementKind.NODE_STATE:
        node_id, expected = req.target.get("node_id"), req.target.get("state")
        if node_id is None or expected is None:
            return _malformed(req)
        node = state.world.nodes.get(node_id)
        if node is None:
            return RequirementResult(req, False, f"unknown node: {node_id!r}")
        passed = node.state == expected
        return RequirementResult(req, passed, f"node state is {node.state!r}, expected {expected!r}")

    if req.kind is RequirementKind.LINK_STATUS:
        from_id, to_id = req.target.get("from_id"), req.target.get("to_id")
        expected = req.target.get("status")
        if from_id is None or to_id is None or expected is None:
            return _malformed(req)
        link = state.world.get_link(from_id, to_id)
        if link is None:
            return RequirementResult(req, False, f"unknown link: {from_id!r} -> {to_id!r}")
        passed = link.status == expected
        return RequirementResult(req, passed, f"link status is {link.status!r}, expected {expected!r}")

    if req.kind is RequirementKind.PLAYER_HAS_ITEM:
        item_id, expected = req.target.get("item_id"), req.target.get("expected")
        if item_id is None or expected is None:
            return _malformed(req)
        has_item = any(item.item_id == item_id for item in state.player.inventory)
        passed = has_item == expected
        return RequirementResult(req, passed, f"player has_item={has_item}, expected {expected}")

    if req.kind is RequirementKind.PLAYER_HAS_SKILL:
        skill_id, expected = req.target.get("skill_id"), req.target.get("expected")
        if skill_id is None or expected is None:
            return _malformed(req)
        has_skill = any(skill.id == skill_id for skill in state.player.skills)
        passed = has_skill == expected
        return RequirementResult(req, passed, f"player has_skill={has_skill}, expected {expected}")

    if req.kind is RequirementKind.PLAYER_GOLD_AT_LEAST:
        amount = req.target.get("amount")
        if amount is None or not _is_number(amount):
            return _malformed(req)
        passed = state.player.gold >= amount
        return RequirementResult(req, passed, f"player has {state.player.gold} gold, needs >= {amount}")

    if req.kind is RequirementKind.PLAYER_NOT_CAPTURED:
        passed = not state.player.captured
        return RequirementResult(req, passed, f"player captured={state.player.captured}")

    if req.kind is RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST:
        item_id, amount = req.target.get("item_id"), req.target.get("amount")
        if item_id is None or amount is None or not _is_number(amount):
            return _malformed(req)
        quantity = next(
            (item.quantity for item in state.player.inventory if item.item_id == item_id), 0
        )
        passed = quantity >= amount
        return RequirementResult(req, passed, f"player has {quantity} of {item_id!r}, needs >= {amount}")

    if req.kind is RequirementKind.FACTION_STANDING_AT_LEAST:
        faction_id, tier = req.target.get("faction_id"), req.target.get("tier")
        # `tier` also needs its OWN validity check beyond "present" -- unlike
        # every other kind above, a present-but-invalid value here doesn't
        # just fail a comparison, it crashes `factions.meets_standing`
        # (`STANDING_TIERS.index(tier)` raises `ValueError` for anything not
        # one of the five real tiers) -- the schema has no `enum` on this
        # freeform `target` object to rule that out ahead of time.
        if faction_id is None or tier not in factions.STANDING_TIERS:
            return _malformed(req)
        # Unlike NODE_STATE/LINK_STATUS above, `factions.standing_of` reads
        # a PLAYER-side dict (`Player.faction_standing`) that defaults an
        # absent entry to "neutral" regardless of whether `faction_id`
        # actually names a real `Faction` -- without this explicit
        # existence check, a hallucinated faction id would silently PASS
        # ("neutral" >= "neutral") instead of being rejected as an
        # unresolved dangling reference, same as an unknown node/link id is.
        if faction_id not in state.world.factions:
            return RequirementResult(req, False, f"unknown faction: {faction_id!r}")
        current = factions.standing_of(state.player, faction_id)
        passed = factions.meets_standing(state.player, faction_id, tier)
        return RequirementResult(req, passed, f"standing with {faction_id!r} is {current!r}, needs >= {tier!r}")

    raise ValueError(f"unhandled requirement kind: {req.kind!r}")  # unreachable given RequirementKind's closed enum
