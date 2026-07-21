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

SYSTEM_PROMPT = (
    "You are the Quest agent for a text RPG's content-generation batch. "
    "Given a situation, turn it into ONE concrete quest: a title, a "
    "description of the task, a gold reward, and a precondition manifest -- "
    "a list of structured requirements (never prose) that must still hold "
    f"for this quest to make sense whenever a player eventually draws it. "
    f"Every requirement's `kind` MUST be one of: {_REQUIREMENT_KINDS}. "
    "Reference entities ONLY by id, never by name, and only ids that "
    "actually appear in the situation/context you were given -- never "
    "invent a new entity."
)

QUEST_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "reward_gold": {"type": "integer"},
        "manifest": {
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
        },
    },
    "required": ["id", "title", "description", "reward_gold", "manifest"],
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
