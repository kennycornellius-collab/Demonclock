from demonclock.player import new_player
from demonclock.setback import (
    ESCAPE_AFTER_DAYS,
    GOLD_DOCK_FRACTION,
    RANSOM_COST,
    capture_player,
    check_escape,
    pay_ransom,
)


def make_player(**kwargs):
    player = new_player(name="Hero", location_id="village")
    for key, value in kwargs.items():
        setattr(player, key, value)
    return player


def test_capture_player_sets_the_blocking_state():
    player = make_player(gold=100)

    log = capture_player(player, current_day=10)

    assert player.captured is True
    assert player.ransom_cost == RANSOM_COST
    assert player.free_by_day == 10 + ESCAPE_AFTER_DAYS
    assert any("captured" in line.lower() for line in log)


def test_capture_player_docks_a_fraction_of_gold():
    player = make_player(gold=100)

    capture_player(player, current_day=0)

    assert player.gold == 100 - int(100 * GOLD_DOCK_FRACTION)


def test_capture_player_with_zero_gold_docks_nothing_and_still_captures():
    player = make_player(gold=0)

    log = capture_player(player, current_day=0)

    assert player.gold == 0
    assert player.captured is True
    assert not any("take" in line.lower() for line in log)


def test_pay_ransom_succeeds_when_affordable():
    player = make_player(gold=100)
    capture_player(player, current_day=0)
    gold_after_capture = player.gold

    log = pay_ransom(player)

    assert player.captured is False
    assert player.ransom_cost == 0
    assert player.free_by_day is None
    assert player.gold == gold_after_capture - RANSOM_COST
    assert any("free" in line.lower() for line in log)


def test_pay_ransom_fails_when_not_enough_gold():
    player = make_player(gold=0)
    capture_player(player, current_day=0)

    log = pay_ransom(player)

    assert player.captured is True  # still held
    assert any("need" in line.lower() for line in log)


def test_pay_ransom_when_not_captured_is_a_no_op():
    player = make_player(gold=1000)

    log = pay_ransom(player)

    assert player.gold == 1000
    assert any("not captured" in line.lower() for line in log)


def test_check_escape_before_the_free_day_stays_captured():
    player = make_player(gold=0)
    capture_player(player, current_day=0)  # free_by_day = ESCAPE_AFTER_DAYS

    log = check_escape(player, current_day=ESCAPE_AFTER_DAYS - 1)

    assert log == []
    assert player.captured is True


def test_check_escape_on_the_free_day_releases_even_with_zero_gold():
    player = make_player(gold=0)
    capture_player(player, current_day=0)

    log = check_escape(player, current_day=ESCAPE_AFTER_DAYS)

    assert player.captured is False
    assert player.free_by_day is None
    assert any("free" in line.lower() for line in log)


def test_check_escape_when_not_captured_is_a_no_op():
    player = make_player()
    assert check_escape(player, current_day=999) == []
