"""Crafting (SPEC.md §6/§12 step 10, Stage 5): converts input items into an
output item at a "workshop"-tagged node (game.handle_interact gates the
Craft option on Node.tags the same way Fight already gates on
seed.WILD_ENEMY_BY_NODE). A hand-authored fixed recipe table for v1 --
mirrors enemies.py's own small hand-authored table / make_enemy shape, per
the resolved design. An AI-generated-recipe hook (a needs_new_recipe-shaped
extension, same family as generation/quest.py's needs_new_place/
needs_new_npc) is a natural, separate future extension, not required to
make crafting playable now.

No node-side stock (a recipe's inputs just need to be in the player's own
inventory) and no clock cost (crafting is an instant Interact action, same
footing as Look/Inventory/Trade) -- both "start rough, calibrate by feel"
choices, same status as every other tuning constant in this codebase.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import behavior
from .player import add_item, display_name, remove_item
from .state import GameState


@dataclass
class Recipe:
    id: str
    name: str
    inputs: dict[str, int]  # item_id -> quantity required
    output_item_id: str
    output_name: str
    output_quantity: int = 1


RECIPES: dict[str, Recipe] = {
    "bake_bread": Recipe(
        id="bake_bread", name="Bake Bread",
        inputs={"grain": 3}, output_item_id="bread", output_name="Bread", output_quantity=1,
    ),
    # "Economy depth" follow-up (updates.md, surfaced 2026-07-29): wool/
    # iron_ore are also tracked goods now (economy.BASE_PRICE, seed.py's
    # market) -- these two recipes give trading and crafting a second
    # connected loop, same "buy the raw good, craft it at the village
    # workshop" shape bake_bread <- grain already established.
    "spin_cloth": Recipe(
        id="spin_cloth", name="Spin Cloth",
        inputs={"wool": 2}, output_item_id="cloth", output_name="Cloth", output_quantity=1,
    ),
    "smelt_iron": Recipe(
        id="smelt_iron", name="Smelt Iron",
        inputs={"iron_ore": 3}, output_item_id="iron_ingot", output_name="Iron Ingot", output_quantity=1,
    ),
}


def _has_enough(state: GameState, inputs: dict[str, int]) -> bool:
    owned = {item.item_id: item.quantity for item in state.player.inventory}
    return all(owned.get(item_id, 0) >= amount for item_id, amount in inputs.items())


def craft(state: GameState, recipe_id: str) -> list[str]:
    """Never mutates state on failure (unknown recipe, missing inputs) --
    every input is checked BEFORE any is removed, so a recipe needing
    multiple items either crafts fully or leaves inventory untouched."""
    recipe = RECIPES.get(recipe_id)
    if recipe is None:
        return ["There's no recipe like that."]

    if not _has_enough(state, recipe.inputs):
        missing = ", ".join(f"{amount} {display_name(item_id)}" for item_id, amount in recipe.inputs.items())
        return [f"You need: {missing}."]

    player = state.player
    for item_id, amount in recipe.inputs.items():
        remove_item(player, item_id, amount)
    add_item(player, recipe.output_item_id, recipe.output_name, recipe.output_quantity)
    behavior.record_crafting_action(player.behavior)
    return [f"You craft {recipe.output_quantity} {recipe.output_name}."]
