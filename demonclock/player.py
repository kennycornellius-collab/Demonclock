"""Player helpers. The fixed attribute set itself lives on models.Player —
this module only adds behavior (inventory ops, defaults), never new fields."""
from __future__ import annotations

from .models import InventoryItem, Player


def new_player(name: str, location_id: str) -> Player:
    return Player(name=name, location_id=location_id)


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
