import pytest

from demonclock.clock import Clock


def test_advance_adds_days():
    clock = Clock(current_day=5)
    result = clock.advance(3)
    assert clock.current_day == 8
    assert result == 8


def test_advance_zero_is_a_noop():
    clock = Clock(current_day=5)
    clock.advance(0)
    assert clock.current_day == 5


def test_advance_negative_raises():
    clock = Clock(current_day=5)
    with pytest.raises(ValueError):
        clock.advance(-1)
