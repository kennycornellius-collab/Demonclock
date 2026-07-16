from demonclock import db
from demonclock.clock import Clock
from demonclock.events import EventKind, ScheduledEvent
from demonclock.player import add_item, new_player
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
