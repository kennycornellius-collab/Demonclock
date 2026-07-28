from demonclock.clock import Clock
from demonclock.models import Node
from demonclock.player import add_item
from demonclock.state import GameState
from demonclock.trade import MIN_PRICE, TRADE_IMPACT_CAP, TRADE_IMPACT_PER_UNIT, buy, sell
from demonclock.player import new_player
from demonclock.world import World


def make_world(node_id: str = "market", prices: dict | None = None) -> World:
    world = World()
    world.add_node(Node(id=node_id, name=node_id.title(), prices=prices or {}))
    return world


def make_state(world: World, gold: int = 100) -> GameState:
    player = new_player(name="Hero", location_id="market")
    player.gold = gold
    return GameState(world=world, player=player, clock=Clock())


def test_buy_deducts_gold_and_adds_inventory():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=100)

    log = buy(state, "market", "grain", 3)

    assert state.player.gold == 70
    item = next(i for i in state.player.inventory if i.item_id == "grain")
    assert item.quantity == 3
    assert item.name == "Grain"
    assert any("buy" in line for line in log)


def test_buy_pushes_the_node_price_up_bounded_by_the_cap():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=100_000)

    buy(state, "market", "grain", 2)
    assert world.nodes["market"].prices["grain"] == 10 + 2 * TRADE_IMPACT_PER_UNIT

    # A huge purchase is still bounded by TRADE_IMPACT_CAP, not unbounded.
    buy(state, "market", "grain", 500)
    assert world.nodes["market"].prices["grain"] == 10 + 2 * TRADE_IMPACT_PER_UNIT + TRADE_IMPACT_CAP


def test_buy_fails_without_enough_gold_and_does_not_mutate_state():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=5)

    log = buy(state, "market", "grain", 1)

    assert state.player.gold == 5
    assert state.player.inventory == []
    assert world.nodes["market"].prices["grain"] == 10
    assert "gold" in log[0]


def test_buy_fails_for_an_untracked_good():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=100)

    log = buy(state, "market", "iron", 1)

    assert state.player.gold == 100
    assert "isn't traded here" in log[0]


def test_buy_rejects_a_non_positive_quantity():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=100)

    log = buy(state, "market", "grain", 0)

    assert state.player.gold == 100
    assert "at least 1" in log[0]


def test_sell_adds_gold_and_removes_inventory():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=0)
    add_item(state.player, "grain", "Grain", 5)

    log = sell(state, "market", "grain", 3)

    assert state.player.gold == 30
    item = next(i for i in state.player.inventory if i.item_id == "grain")
    assert item.quantity == 2
    assert any("sell" in line for line in log)


def test_sell_pushes_the_node_price_down_floored_at_min_price():
    world = make_world(prices={"grain": 3})
    state = make_state(world, gold=0)
    add_item(state.player, "grain", "Grain", 100)

    sell(state, "market", "grain", 50)

    assert world.nodes["market"].prices["grain"] == MIN_PRICE


def test_sell_fails_without_enough_of_the_good_and_does_not_mutate_state():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=0)
    add_item(state.player, "grain", "Grain", 1)

    log = sell(state, "market", "grain", 5)

    assert state.player.gold == 0
    assert state.player.inventory[0].quantity == 1
    assert world.nodes["market"].prices["grain"] == 10
    assert "don't have" in log[0]


def test_sell_fails_for_an_untracked_good():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=0)
    add_item(state.player, "iron", "Iron", 5)

    log = sell(state, "market", "iron", 1)

    assert state.player.gold == 0
    assert "isn't traded here" in log[0]


def test_trades_record_a_behavior_action():
    world = make_world(prices={"grain": 10})
    state = make_state(world, gold=100)

    buy(state, "market", "grain", 1)

    assert state.player.behavior.trade_actions == 1.0
