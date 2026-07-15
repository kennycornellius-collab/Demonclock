"""Bundles the three pieces of live state a turn needs together."""
from __future__ import annotations

from dataclasses import dataclass

from .clock import Clock
from .models import Player
from .world import World


@dataclass
class GameState:
    world: World
    player: Player
    clock: Clock
