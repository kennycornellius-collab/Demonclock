from demonclock import db
from demonclock.clock import Clock
from demonclock.player import add_item, new_player
from demonclock.seed import new_default_world


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

    assert set(loaded_world.nodes.keys()) == set(world.nodes.keys())
    reloaded_link = loaded_world.get_link("village", "market")
    assert reloaded_link.status == "blocked"
    assert reloaded_link.block_reason == "flooded"
    # the atomic-block invariant should still hold after a round trip
    assert loaded_world.get_link("market", "village").status == "blocked"

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
