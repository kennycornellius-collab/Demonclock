"""Bundles the pieces of live state a turn needs together."""
from __future__ import annotations

from dataclasses import dataclass

from .clock import Clock
from .llm.registry import LLMRegistry
from .models import Player
from .world import World


@dataclass
class GameState:
    world: World
    player: Player
    clock: Clock
    # Step 5 Chunk B: the generation pipeline's provider registry. Optional
    # and defaulted to None so every pre-Step-5 test's `GameState(world=...,
    # player=..., clock=...)` construction keeps working unchanged --
    # sim._run_batch treats a None (or a disabled) registry as the existing
    # no-op, exactly today's behavior in an unconfigured environment.
    generation: LLMRegistry | None = None
