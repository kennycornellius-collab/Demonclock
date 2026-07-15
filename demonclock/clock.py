"""In-game day clock. SPEC.md §4: days are the one canonical time unit everywhere."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Clock:
    current_day: int = 0

    def advance(self, days: int) -> int:
        if days < 0:
            raise ValueError("cannot advance a negative number of days")
        self.current_day += days
        return self.current_day
