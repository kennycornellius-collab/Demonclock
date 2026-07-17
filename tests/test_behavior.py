import pytest

from demonclock.behavior import (
    BehaviorProfile,
    DECAY_FACTOR,
    derived_role_hint,
    record_combat_action,
    record_crafting_action,
    record_dialogue_action,
    record_location,
    record_trade_action,
    tick,
)


def test_record_functions_increment_their_own_counter_only():
    profile = BehaviorProfile()
    record_combat_action(profile)

    assert profile.combat_actions == 1.0
    assert profile.trade_actions == 0.0
    assert profile.dialogue_actions == 0.0
    assert profile.crafting_actions == 0.0


def test_record_trade_dialogue_crafting_actions_increment():
    profile = BehaviorProfile()
    record_trade_action(profile)
    record_dialogue_action(profile)
    record_crafting_action(profile)

    assert profile.trade_actions == 1.0
    assert profile.dialogue_actions == 1.0
    assert profile.crafting_actions == 1.0


def test_record_location_appends_new_locations():
    profile = BehaviorProfile()
    record_location(profile, "village")
    record_location(profile, "road")

    assert profile.recent_locations == ["village", "road"]


def test_record_location_does_not_pad_on_repeat_of_the_same_node():
    profile = BehaviorProfile()
    record_location(profile, "village")
    record_location(profile, "village")

    assert profile.recent_locations == ["village"]


def test_record_location_keeps_only_the_most_recent_entries():
    profile = BehaviorProfile()
    for node_id in ["a", "b", "c", "d", "e", "f", "g"]:
        record_location(profile, node_id)

    assert profile.recent_locations == ["c", "d", "e", "f", "g"]


def test_tick_decays_every_action_counter_by_the_decay_factor():
    profile = BehaviorProfile(
        trade_actions=10.0, combat_actions=10.0, dialogue_actions=10.0, crafting_actions=10.0,
    )

    tick(profile, current_gold=0)

    assert profile.trade_actions == pytest.approx(10.0 * DECAY_FACTOR)
    assert profile.combat_actions == pytest.approx(10.0 * DECAY_FACTOR)
    assert profile.dialogue_actions == pytest.approx(10.0 * DECAY_FACTOR)
    assert profile.crafting_actions == pytest.approx(10.0 * DECAY_FACTOR)


def test_tick_snaps_a_near_zero_counter_to_exactly_zero():
    profile = BehaviorProfile(combat_actions=0.001)

    tick(profile, current_gold=0)

    assert profile.combat_actions == 0.0


def test_tick_sets_gold_trend_rising_when_gold_increased_since_last_tick():
    profile = BehaviorProfile(last_gold=10)
    tick(profile, current_gold=20)
    assert profile.gold_trend == "rising"
    assert profile.last_gold == 20


def test_tick_sets_gold_trend_falling_when_gold_decreased_since_last_tick():
    profile = BehaviorProfile(last_gold=10)
    tick(profile, current_gold=5)
    assert profile.gold_trend == "falling"
    assert profile.last_gold == 5


def test_tick_sets_gold_trend_flat_when_gold_is_unchanged():
    profile = BehaviorProfile(last_gold=10, gold_trend="rising")
    tick(profile, current_gold=10)
    assert profile.gold_trend == "flat"


def test_derived_role_hint_defaults_to_a_neutral_phrase_for_a_fresh_profile():
    assert derived_role_hint(BehaviorProfile()) == "still finding their way"


def test_derived_role_hint_tags_combat_focused_above_threshold():
    profile = BehaviorProfile(combat_actions=3.0)
    assert derived_role_hint(profile) == "combat-focused"


def test_derived_role_hint_does_not_tag_unimplemented_systems_below_threshold():
    # trade/dialogue/crafting have no gameplay hook yet and sit at 0 forever
    # until those systems land — this must read as neutral, not "averse".
    profile = BehaviorProfile(trade_actions=0.0, dialogue_actions=0.0, crafting_actions=0.0)
    assert derived_role_hint(profile) == "still finding their way"


def test_derived_role_hint_combines_multiple_tags():
    profile = BehaviorProfile(combat_actions=5.0, trade_actions=4.0, gold_trend="falling")
    hint = derived_role_hint(profile)
    assert "combat-focused" in hint
    assert "trade-focused" in hint
    assert "financially strained" in hint


def test_derived_role_hint_prospering_on_rising_gold():
    profile = BehaviorProfile(gold_trend="rising")
    assert derived_role_hint(profile) == "prospering"
