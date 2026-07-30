from demonclock.canon import RequirementKind
from demonclock.clock import Clock
from demonclock.models import Faction, Node
from demonclock.player import add_item, new_player
from demonclock.quests import check_completion, turn_in
from demonclock.state import GameState
from demonclock.world import World


def make_state(gold: int = 0) -> GameState:
    world = World()
    world.add_node(Node(id="a", name="A", state="peaceful"))
    player = new_player(name="Hero", location_id="a")
    player.gold = gold
    return GameState(world=world, player=player, clock=Clock())


def gold_quest(quest_id: str = "quest1", reward_gold: int = 25, amount: int = 5) -> dict:
    return {
        "id": quest_id,
        "title": "Bring the grain",
        "reward_gold": reward_gold,
        "completion": {
            "requirements": [
                {
                    "kind": RequirementKind.PLAYER_HAS_ITEM_QUANTITY_AT_LEAST.value,
                    "target": {"item_id": "grain", "amount": amount},
                },
            ],
        },
    }


def test_check_completion_fails_when_objective_not_yet_met():
    state = make_state()
    result = check_completion(state, gold_quest())
    assert not result.passed


def test_check_completion_passes_once_the_objective_is_met():
    state = make_state()
    add_item(state.player, "grain", "Grain", 5)
    result = check_completion(state, gold_quest())
    assert result.passed


def test_a_quest_with_no_completion_key_is_trivially_complete():
    state = make_state()
    quest = {"id": "old_quest", "title": "Pre-Stage-2 quest", "reward_gold": 10}
    assert check_completion(state, quest).passed


def test_turn_in_fails_and_does_not_mutate_state_when_objective_not_met():
    state = make_state(gold=0)
    quest = gold_quest(reward_gold=25)
    state.player.accepted_quests.append(quest)

    log = turn_in(state, quest)

    assert state.player.gold == 0
    assert quest in state.player.accepted_quests
    assert "Not finished" in log[0]


def test_turn_in_grants_reward_and_removes_the_quest_once_objective_is_met():
    state = make_state(gold=0)
    add_item(state.player, "grain", "Grain", 5)
    quest = gold_quest(reward_gold=25)
    state.player.accepted_quests.append(quest)

    log = turn_in(state, quest)

    assert state.player.gold == 25
    assert quest not in state.player.accepted_quests
    assert any("Quest complete" in line for line in log)


def test_turn_in_records_a_journal_entry_on_success():
    state = make_state(gold=0)
    add_item(state.player, "grain", "Grain", 5)
    quest = gold_quest(reward_gold=25)
    state.player.accepted_quests.append(quest)
    state.clock.current_day = 4

    turn_in(state, quest)

    assert state.player.journal[0].day == 4
    assert "Completed quest" in state.player.journal[0].description
    assert "25 gold" in state.player.journal[0].description


def test_turn_in_does_not_record_a_journal_entry_when_objective_not_met():
    state = make_state(gold=0)
    quest = gold_quest(reward_gold=25)
    state.player.accepted_quests.append(quest)

    turn_in(state, quest)

    assert state.player.journal == []


def test_turn_in_does_not_consume_the_completion_items():
    # Design scope: completion is a CHECK, not a cost -- turning in a
    # "bring N of X" quest does not remove the items from inventory.
    state = make_state(gold=0)
    add_item(state.player, "grain", "Grain", 5)
    quest = gold_quest(reward_gold=25)
    state.player.accepted_quests.append(quest)

    turn_in(state, quest)

    item = next(i for i in state.player.inventory if i.item_id == "grain")
    assert item.quantity == 5


# -- faction_standing_delta (Step 10 Stage 4 follow-up) ---------------------

def quest_with_delta(faction_id="merchants", tiers=1) -> dict:
    quest = gold_quest(reward_gold=25)
    quest["faction_standing_delta"] = {"faction_id": faction_id, "tiers": tiers}
    return quest


def test_turn_in_applies_a_valid_faction_standing_delta():
    state = make_state(gold=0)
    state.world.add_faction(Faction(id="merchants", name="The Merchants' Guild"))
    add_item(state.player, "grain", "Grain", 5)
    quest = quest_with_delta()
    state.player.accepted_quests.append(quest)

    log = turn_in(state, quest)

    assert state.player.faction_standing["merchants"] == "friendly"
    assert any("standing" in line.lower() for line in log)


def test_turn_in_does_not_apply_a_faction_standing_delta_when_objective_not_met():
    state = make_state(gold=0)
    state.world.add_faction(Faction(id="merchants", name="The Merchants' Guild"))
    quest = quest_with_delta()
    state.player.accepted_quests.append(quest)

    turn_in(state, quest)

    assert "merchants" not in state.player.faction_standing


def test_turn_in_silently_skips_an_unknown_faction_id_in_the_delta():
    # The two manifests are canon-checked before a quest is ever committed;
    # faction_standing_delta is not, so a hallucinated faction_id must not
    # crash or block the (already-earned) reward_gold from being granted.
    state = make_state(gold=0)
    add_item(state.player, "grain", "Grain", 5)
    quest = quest_with_delta(faction_id="raiders")
    state.player.accepted_quests.append(quest)

    log = turn_in(state, quest)

    assert state.player.gold == 25
    assert "raiders" not in state.player.faction_standing
    assert not any("standing" in line.lower() for line in log)


def test_turn_in_silently_skips_a_non_numeric_tiers_value():
    state = make_state(gold=0)
    state.world.add_faction(Faction(id="merchants", name="The Merchants' Guild"))
    add_item(state.player, "grain", "Grain", 5)
    quest = quest_with_delta()
    quest["faction_standing_delta"]["tiers"] = "a lot"
    state.player.accepted_quests.append(quest)

    log = turn_in(state, quest)

    assert state.player.gold == 25
    assert "merchants" not in state.player.faction_standing
    assert not any("standing" in line.lower() for line in log)
