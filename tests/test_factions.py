from demonclock.factions import DEFAULT_STANDING, STANDING_TIERS, adjust_standing, meets_standing, standing_of
from demonclock.player import new_player


def test_standing_tiers_are_ordered_hostile_to_allied():
    assert STANDING_TIERS == ("hostile", "unfriendly", "neutral", "friendly", "allied")


def test_standing_of_defaults_to_neutral_for_an_unrecorded_faction():
    player = new_player(name="Hero", location_id="village")
    assert standing_of(player, "merchants") == DEFAULT_STANDING == "neutral"


def test_standing_of_returns_the_recorded_tier_when_present():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "friendly"
    assert standing_of(player, "merchants") == "friendly"


def test_meets_standing_passes_when_exactly_at_the_required_tier():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "neutral"
    assert meets_standing(player, "merchants", "neutral")


def test_meets_standing_passes_when_above_the_required_tier():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "allied"
    assert meets_standing(player, "merchants", "friendly")


def test_meets_standing_fails_when_below_the_required_tier():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "unfriendly"
    assert not meets_standing(player, "merchants", "neutral")


def test_meets_standing_uses_the_default_neutral_for_an_unrecorded_faction():
    player = new_player(name="Hero", location_id="village")
    assert meets_standing(player, "raiders", "neutral")
    assert not meets_standing(player, "raiders", "friendly")


# -- adjust_standing (Step 10 Stage 4 follow-up: the first live trigger) ---

def test_adjust_standing_moves_up_from_the_default_neutral():
    player = new_player(name="Hero", location_id="village")
    new_tier = adjust_standing(player, "merchants", 1)
    assert new_tier == "friendly"
    assert player.faction_standing["merchants"] == "friendly"


def test_adjust_standing_moves_down_from_a_recorded_tier():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "friendly"
    assert adjust_standing(player, "merchants", -1) == "neutral"


def test_adjust_standing_clamps_at_the_top_of_the_scale():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "allied"
    assert adjust_standing(player, "merchants", 5) == "allied"


def test_adjust_standing_clamps_at_the_bottom_of_the_scale():
    player = new_player(name="Hero", location_id="village")
    player.faction_standing["merchants"] = "hostile"
    assert adjust_standing(player, "merchants", -5) == "hostile"
