from demonclock import db
from demonclock.canon import PreconditionManifest, Requirement, RequirementKind
from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.history import LogEntry
from demonclock.knowledge import NodeBelief
from demonclock.player import add_item, new_player
from demonclock.pool import GeneratedItem
from demonclock.seed import new_default_world
from demonclock.skills import Effect, EffectKind, Skill, StatType


def test_no_save_yet_returns_none(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)
    assert db.load_game(conn) is None
    conn.close()


def test_save_then_load_round_trips_world_player_clock(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    world.block_link("village", "market", reason="flooded")
    player = new_player(name="Astra", location_id="market")
    player.gold = 42
    player.hp = 77
    add_item(player, "amulet", "Tarnished Amulet", quantity=1)
    player.skills = [
        Skill(
            id="custom_bolt",
            name="Custom Bolt",
            description="A test skill exercising effect + stat round-tripping.",
            effects=[Effect(EffectKind.DAMAGE), Effect(EffectKind.DEBUFF, stat=StatType.DEFENSE)],
            attribute_type=StatType.MAGIC,
            mana_cost=7,
            base_damage=13,
            attribute_multiplier=1.5,
            cooldown=2,
        ),
    ]
    clock = Clock(current_day=13)

    db.save_game(conn, world, player, clock)

    loaded = db.load_game(conn)
    assert loaded is not None
    loaded_world, loaded_player, loaded_clock = loaded

    assert loaded_clock.current_day == 13

    assert loaded_player.name == "Astra"
    assert loaded_player.location_id == "market"
    assert loaded_player.gold == 42
    assert loaded_player.hp == 77
    assert len(loaded_player.inventory) == 1
    assert loaded_player.inventory[0].item_id == "amulet"
    assert loaded_player.inventory[0].quantity == 1

    assert loaded_player.skills == player.skills

    assert set(loaded_world.nodes.keys()) == set(world.nodes.keys())
    reloaded_link = loaded_world.get_link("village", "market")
    assert reloaded_link.status == "blocked"
    assert reloaded_link.block_reason == "flooded"
    # the atomic-block invariant should still hold after a round trip
    assert loaded_world.get_link("market", "village").status == "blocked"

    conn.close()


def test_creative_mode_used_flag_persists(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    player.creative_mode_used = True
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)
    assert loaded_player.creative_mode_used is True

    conn.close()


def test_creative_mode_used_defaults_false(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)
    assert loaded_player.creative_mode_used is False

    conn.close()


def test_scheduled_events_round_trip(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()  # already carries the seeded blizzard pair
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert [e.description for e in loaded_world.scheduled_events] == \
        [e.description for e in world.scheduled_events]
    assert loaded_world.scheduled_events[0].due_day == 4
    assert loaded_world.scheduled_events[0].kind is EventKind.BLOCK_LINK
    assert loaded_world.scheduled_events[0].payload == {"from_id": "road", "to_id": "wilds", "reason": "snow"}

    invasion_event = loaded_world.scheduled_events[2]
    assert invasion_event.due_day == 15
    assert invasion_event.kind is EventKind.INVASION_SPREAD
    assert invasion_event.payload == {}

    price_event = loaded_world.scheduled_events[3]
    assert price_event.due_day == 3
    assert price_event.kind is EventKind.PRICE_SHIFT
    assert price_event.payload == {}

    conn.close()


def test_node_prices_round_trip(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()  # market is seeded with {"grain": 10}
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert loaded_world.nodes["market"].prices == {"grain": 10}
    assert loaded_world.nodes["village"].prices == {}  # untouched nodes stay empty

    conn.close()


def test_scheduled_events_save_is_a_full_overwrite(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())
    db.save_game(conn, world, player, Clock())  # save twice

    loaded_world, _, _ = db.load_game(conn)
    assert len(loaded_world.scheduled_events) == len(world.scheduled_events)

    conn.close()


def test_starter_skills_persist_in_order(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert [s.id for s in loaded_player.skills] == [s.id for s in player.skills]
    conn.close()


def test_behavior_profile_round_trips(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    player.gold = 30
    player.behavior.trade_actions = 1.5
    player.behavior.combat_actions = 4.2
    player.behavior.dialogue_actions = 0.3
    player.behavior.crafting_actions = 2.0
    player.behavior.last_gold = 10
    player.behavior.gold_trend = "rising"
    player.behavior.recent_locations = ["village", "road", "market"]
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.behavior.trade_actions == 1.5
    assert loaded_player.behavior.combat_actions == 4.2
    assert loaded_player.behavior.dialogue_actions == 0.3
    assert loaded_player.behavior.crafting_actions == 2.0
    assert loaded_player.behavior.last_gold == 10
    assert loaded_player.behavior.gold_trend == "rising"
    assert loaded_player.behavior.recent_locations == ["village", "road", "market"]

    conn.close()


def test_behavior_profile_defaults_for_a_fresh_player(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.behavior.gold_trend == "flat"
    assert loaded_player.behavior.recent_locations == []

    conn.close()


def test_captured_state_round_trips(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    player.captured = True
    player.ransom_cost = 50
    player.free_by_day = 12
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.captured is True
    assert loaded_player.ransom_cost == 50
    assert loaded_player.free_by_day == 12

    conn.close()


def test_captured_state_defaults_for_a_fresh_player(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.captured is False
    assert loaded_player.ransom_cost == 0
    assert loaded_player.free_by_day is None

    conn.close()


def test_player_beliefs_round_trip(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    player.beliefs["village"] = NodeBelief(state="peaceful", tags=["trade-hub"], last_seen_day=0)
    player.beliefs["wilds"] = NodeBelief(state="occupied", prices={"grain": 25}, last_seen_day=20)
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.beliefs == player.beliefs

    conn.close()


def test_player_beliefs_default_to_empty_for_a_fresh_player(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, new_default_world(), player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.beliefs == {}

    conn.close()


def test_event_log_round_trips_in_order(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    world.event_log = [
        LogEntry(day=4, node_id="road", kind=EventKind.BLOCK_LINK, description="A blizzard closes the northern pass."),
        LogEntry(day=15, node_id="road", kind=EventKind.SET_NODE_STATE, description="The invasion overruns Old North Road."),
    ]
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert loaded_world.event_log == world.event_log

    conn.close()


def test_event_log_defaults_to_empty_for_a_fresh_world(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()  # no ticks have fired yet
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert loaded_world.event_log == []

    conn.close()


def test_content_pool_round_trips_in_order(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    world.content_pool = [
        GeneratedItem(
            id="quest1", payload={"title": "Lost Caravan"},
            manifest=PreconditionManifest([Requirement(RequirementKind.NODE_STATE, {"node_id": "market", "state": "peaceful"})]),
        ),
        GeneratedItem(
            id="quest2", payload={"title": "The Old Well"},
            manifest=PreconditionManifest([Requirement(RequirementKind.PLAYER_GOLD_AT_LEAST, {"amount": 5})]),
        ),
    ]
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert loaded_world.content_pool == world.content_pool

    conn.close()


def test_content_pool_defaults_to_empty_for_a_fresh_world(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    loaded_world, _, _ = db.load_game(conn)

    assert loaded_world.content_pool == []

    conn.close()


def test_accepted_quests_round_trip_in_order(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    player = new_player(name="Astra", location_id="village")
    player.accepted_quests = [
        {"id": "quest1", "title": "Lost Caravan", "description": "Find it.", "reward_gold": 10},
        {"id": "quest2", "title": "The Old Well", "description": "Clean it.", "reward_gold": 5},
    ]
    db.save_game(conn, world, player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.accepted_quests == player.accepted_quests

    conn.close()


def test_accepted_quests_default_to_empty_for_a_fresh_player(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    player = new_player(name="Astra", location_id="village")
    db.save_game(conn, world, player, Clock())

    _, loaded_player, _ = db.load_game(conn)

    assert loaded_player.accepted_quests == []

    conn.close()


def test_save_is_a_full_overwrite_not_an_accumulation(tmp_path):
    conn = db.connect(tmp_path / "save.sqlite")
    db.init_schema(conn)

    world = new_default_world()
    player = new_player(name="First", location_id="village")
    db.save_game(conn, world, player, Clock(current_day=1))

    player2 = new_player(name="Second", location_id="market")
    db.save_game(conn, world, player2, Clock(current_day=2))

    _, loaded_player, loaded_clock = db.load_game(conn)
    assert loaded_player.name == "Second"
    assert loaded_clock.current_day == 2

    conn.close()
