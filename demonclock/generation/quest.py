"""The Quest agent (SPEC.md §7 step 4): turns a Situation (story.py) into a
concrete task -- a `pool.GeneratedItem` carrying a `PreconditionManifest`
built EXCLUSIVELY from `canon.RequirementKind`'s existing enum (SPEC.md §8:
the AI proposes references, the manifest is structured booleans, never
prose). Emits exactly the shape `pool.commit_or_repair` already knows how to
validate/commit -- nothing new to plumb into Step 4's machinery.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ..canon import PreconditionManifest, RequirementKind
from ..llm.registry import LLMRegistry
from ..pool import GeneratedItem
from .story import Situation

if TYPE_CHECKING:
    from ..canon import RequirementResult

_REQUIREMENT_KINDS = ", ".join(kind.value for kind in RequirementKind)

# Root-cause fix for a real, live, repeatable bug (see updates.md's "Open
# TODOs"): the prompt used to name only the legal `kind` values, never each
# kind's expected `target` KEYS -- `target`'s own JSON schema is just
# `{"type": "object"}` (the hand-rolled validator can't express "these keys
# are required, conditional on kind"), so nothing structurally stopped the
# model from emitting e.g. a NODE_STATE requirement with no `node_id`.
# canon.py's `_check_one` degrades that gracefully now (a malformed target is
# just a failed requirement, not a crash), but a malformed requirement still
# means the quest never survives commit/pull -- fewer usable quests than
# intended. Each shape below must mirror `canon._check_one`'s own
# `req.target.get(...)` calls exactly; kept as a plain dict (not derived by
# reflection) since it's prompt text, not executable validation -- the
# assertion below only guards against a NEW RequirementKind being added here
# without also documenting its shape.
_REQUIREMENT_TARGET_SHAPES: dict[RequirementKind, str] = {
    RequirementKind.NODE_STATE: '{"node_id": <node id>, "state": <expected node state string>}',
    RequirementKind.LINK_STATUS: '{"from_id": <node id>, "to_id": <node id>, "status": <expected link status string>}',
    RequirementKind.PLAYER_HAS_ITEM: '{"item_id": <item id>, "expected": <true if the player must have it, false if they must NOT>}',
    RequirementKind.PLAYER_HAS_SKILL: '{"skill_id": <skill id>, "expected": <true if the player must know it, false if they must NOT>}',
    RequirementKind.PLAYER_GOLD_AT_LEAST: '{"amount": <minimum gold, a number>}',
    RequirementKind.PLAYER_NOT_CAPTURED: '{} (no target keys needed)',
    RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST: '{"item_id": <item id>, "amount": <minimum quantity, a number>}',
    RequirementKind.FACTION_STANDING_AT_LEAST: '{"faction_id": <faction id>, "tier": one of "hostile"|"unfriendly"|"neutral"|"friendly"|"allied"}',
}
assert set(_REQUIREMENT_TARGET_SHAPES) == set(RequirementKind), (
    "a RequirementKind was added/removed in canon.py without updating "
    "_REQUIREMENT_TARGET_SHAPES to match -- the Quest prompt would silently "
    "go back to not documenting that kind's target shape"
)
_REQUIREMENT_TARGET_SHAPES_TEXT = "; ".join(
    f"{kind.value} needs target {shape}" for kind, shape in _REQUIREMENT_TARGET_SHAPES.items()
)

SYSTEM_PROMPT = (
    "You are the Quest agent for a text RPG's content-generation batch. "
    "Given a situation, turn it into ONE concrete quest: a title, a "
    "description of the task, a gold reward, a precondition manifest, and a "
    "completion manifest. The precondition manifest is a list of structured "
    "requirements (never prose) that must still hold for this quest to make "
    f"sense whenever a player eventually draws it. "
    f"Every requirement's `kind` MUST be one of: {_REQUIREMENT_KINDS}. "
    f"Each kind's `target` object MUST include exactly the keys it needs -- "
    f"a requirement with a missing or empty target key is treated as "
    f"malformed and discarded: {_REQUIREMENT_TARGET_SHAPES_TEXT}. "
    "The completion manifest is the same shape but describes the actual "
    "objective the player must achieve to turn the quest in -- e.g. "
    "PLAYER_HAS_ITEM_QUANTITY_AT_LEAST for 'bring me N of something', or "
    "NODE_STATE for 'until this place is no longer occupied'. The two "
    "manifests answer different questions at different times: precondition "
    "gates whether this quest is still valid to OFFER, completion is "
    "whether it's actually DONE -- do not confuse them (e.g. a gold-reward "
    "quest's completion should never just restate its own precondition). "
    "Reference entities ONLY by id, never by name, and only ids that "
    "actually appear in the situation/context you were given -- never "
    "invent a new entity in either manifest. If completing this quest would "
    "plausibly need a place that doesn't exist on the map yet (e.g. an "
    "abandoned mine, a smuggler's cove), set needs_new_place to true and "
    "place_hint to a short plain-language description of it -- do NOT "
    "invent that place's id yourself; a separate agent will name and place "
    "it on the map. Leave needs_new_place false for an ordinary quest set at "
    "an existing node. Likewise, if completing this quest would plausibly "
    "need an NPC who doesn't exist on the map yet (e.g. a specific merchant, "
    "a named guard captain), set needs_new_npc to true and npc_hint to a "
    "short plain-language description -- do NOT invent that NPC's id "
    "yourself; a separate agent will name and place them. Leave "
    "needs_new_npc false for an ordinary quest involving no new NPC. If "
    "turning this quest in should plausibly move the player's standing with "
    "an existing faction (e.g. doing a favor for a faction named in the "
    "context's known_factions list), set faction_standing_delta to "
    "{faction_id, tiers}, where faction_id is one of known_factions' own "
    "ids (never invent one, and never set this if known_factions is empty) "
    "and tiers is a small integer -- usually 1, rarely 2 -- positive to "
    "move standing toward friendlier tiers, negative toward more hostile "
    "ones. Omit faction_standing_delta entirely for an ordinary quest with "
    "no faction impact. The "
    "context's player.derived_role_hint is a short "
    "phrase describing who the player is becoming (e.g. 'trade-focused, "
    "combat-averse') -- let it color the title's and description's word "
    "choice/tone, never reward_gold, needs_new_place, needs_new_npc, "
    "faction_standing_delta, or any requirement in either manifest, all of "
    "which must stay strictly determined by the situation and existing "
    "world truth."
)

_MANIFEST_SCHEMA = {
    "type": "object",
    "properties": {
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [kind.value for kind in RequirementKind]},
                    "target": {"type": "object"},
                },
                "required": ["kind", "target"],
            },
        },
    },
    "required": ["requirements"],
}

QUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "reward_gold": {"type": "integer"},
        "needs_new_place": {"type": "boolean"},
        "place_hint": {"type": "string"},
        # Step 10 Stage 3: the same optional extension pattern as
        # needs_new_place/place_hint, but for generation/npc.py.
        "needs_new_npc": {"type": "boolean"},
        "npc_hint": {"type": "string"},
        # Step 10 Stage 4 follow-up: the first live trigger that actually
        # moves faction standing (see factions.adjust_standing/quests.
        # turn_in) -- optional, same pattern as needs_new_place/needs_new_npc
        # above. faction_id must come from context's known_factions (see
        # context.py); quests.turn_in silently skips applying this rather
        # than failing turn-in if faction_id doesn't resolve to a real
        # World.factions entry, same "never crash on a dangling AI-proposed
        # reference" posture as canon.py's own checks.
        "faction_standing_delta": {
            "type": "object",
            "properties": {
                "faction_id": {"type": "string"},
                "tiers": {"type": "integer"},
            },
            "required": ["faction_id", "tiers"],
        },
        # The precondition manifest (SPEC.md §8): gates whether this quest is
        # still valid to OFFER. pool.commit_or_repair/pool.pull are the only
        # things that ever read this one.
        "manifest": _MANIFEST_SCHEMA,
        # Step 10 Stage 2: the completion manifest -- the actual objective,
        # checked only at turn-in (quests.check_completion), never at
        # commit/pull time. Same shape as `manifest` but a structurally
        # separate field since the two answer different questions at
        # different times (see SYSTEM_PROMPT above).
        "completion": _MANIFEST_SCHEMA,
    },
    "required": ["id", "title", "description", "reward_gold", "manifest", "completion"],
}


def run_quest(registry: LLMRegistry, context: dict, situation: Situation) -> GeneratedItem:
    payload = {"situation": _situation_payload(situation), "context": context}
    data = registry.generate("quest", SYSTEM_PROMPT, json.dumps(payload), QUEST_SCHEMA)
    return _item_from_dict(data)


def run_quest_repair(
    registry: LLMRegistry,
    context: dict,
    situation: Situation,
    item: GeneratedItem,
    failures: list[RequirementResult],
) -> GeneratedItem:
    """SPEC.md §8: "prefer repair over rejection" -- re-prompts the Quest
    agent with the SPECIFIC failing requirements (never the whole DB, never
    a from-scratch regeneration) for a targeted patch. The caller
    (pipeline.py's repair_fn closure) re-validates the result against the
    manifest before trusting it, via pool.commit_or_repair's existing
    "a repair is never trusted blindly" behavior -- this function does not
    special-case that; it just produces another candidate item."""
    payload = {
        "situation": _situation_payload(situation),
        "context": context,
        "previous_attempt": item.payload,
        "failing_requirements": [
            {"kind": failure.requirement.kind.value, "target": failure.requirement.target, "reason": failure.reason}
            for failure in failures
        ],
    }
    repair_prompt = SYSTEM_PROMPT + (
        " A previous attempt at this quest failed some of its own "
        "requirements -- fix ONLY those, keep everything else that already "
        "worked."
    )
    data = registry.generate("quest", repair_prompt, json.dumps(payload), QUEST_SCHEMA)
    return _item_from_dict(data)


def _situation_payload(situation: Situation) -> dict:
    return {
        "id": situation.id, "title": situation.title,
        "description": situation.description, "node_id": situation.node_id,
        "stream": situation.stream,
    }


def _item_from_dict(data: dict) -> GeneratedItem:
    manifest = PreconditionManifest.from_dict(data["manifest"])
    payload = {key: value for key, value in data.items() if key != "manifest"}
    return GeneratedItem(id=data["id"], payload=payload, manifest=manifest)
