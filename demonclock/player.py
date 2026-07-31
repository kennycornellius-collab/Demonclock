"""Player helpers. The fixed attribute set itself lives on models.Player —
this module only adds behavior (inventory ops, defaults), never new fields."""
from __future__ import annotations

from .models import InventoryItem, Player
from .skills import starter_skills


def new_player(name: str, location_id: str, declared_intent: str | None = None) -> Player:
    return Player(
        name=name, location_id=location_id, skills=starter_skills(),
        declared_intent=declared_intent,
    )


def add_item(player: Player, item_id: str, name: str, quantity: int = 1) -> None:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    for item in player.inventory:
        if item.item_id == item_id:
            item.quantity += quantity
            return
    player.inventory.append(InventoryItem(item_id=item_id, name=name, quantity=quantity))


def remove_item(player: Player, item_id: str, quantity: int = 1) -> bool:
    """Returns True if the item was removed (had enough quantity), False otherwise."""
    for item in player.inventory:
        if item.item_id == item_id:
            if item.quantity < quantity:
                return False
            item.quantity -= quantity
            if item.quantity == 0:
                player.inventory.remove(item)
            return True
    return False


def display_name(item_id: str) -> str:
    """The fallback display name trade.py/crafting.py/economy.py/game.py all
    derive for a good/item id that has no explicit name of its own (unlike
    e.g. a Skill or NPC, which always carry a real `name` field). Plain
    `item_id.title()` mishandles a multi-word snake_case id -- surfaced by
    "economy depth" (updates.md) adding "iron_ore", where `.title()` alone
    produces "Iron_Ore" (Python's `str.title()` doesn't treat `_` as a word
    boundary) -- so the underscore is replaced with a space first."""
    return item_id.replace("_", " ").title()
