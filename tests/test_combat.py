from demonclock.combat import CombatAction, CombatResult, Combatant, compute_damage, run_combat, turn_order
from demonclock.enemies import make_enemy
from demonclock.models import Player


def make_player(**kwargs) -> Player:
    defaults = dict(name="Hero", location_id="village")
    defaults.update(kwargs)
    return Player(**defaults)


def test_compute_damage_applies_defense_mitigation():
    attacker = Combatant(name="A", hp=10, hp_max=10, strength=10, agility=5, defense=0)
    weak_def = Combatant(name="B", hp=10, hp_max=10, strength=0, agility=5, defense=0)
    strong_def = Combatant(name="C", hp=10, hp_max=10, strength=0, agility=5, defense=10)

    assert compute_damage(attacker, strong_def) < compute_damage(attacker, weak_def)


def test_compute_damage_floors_at_one():
    attacker = Combatant(name="A", hp=10, hp_max=10, strength=1, agility=5, defense=0)
    tank = Combatant(name="B", hp=10, hp_max=10, strength=0, agility=5, defense=9999)
    assert compute_damage(attacker, tank) == 1


def test_turn_order_faster_combatant_acts_first():
    fast = Combatant(name="fast", hp=10, hp_max=10, strength=1, agility=20, defense=0)
    slow = Combatant(name="slow", hp=10, hp_max=10, strength=1, agility=5, defense=0)

    assert turn_order(slow, fast) == ["enemy", "player"]
    assert turn_order(fast, slow) == ["player", "enemy"]


def test_turn_order_ties_favor_player():
    a = Combatant(name="a", hp=10, hp_max=10, strength=1, agility=10, defense=0)
    b = Combatant(name="b", hp=10, hp_max=10, strength=1, agility=10, defense=0)

    assert turn_order(a, b) == ["player", "enemy"]


def test_make_enemy_returns_full_health_combatant():
    enemy = make_enemy("bramblewood_wolf")
    assert enemy.hp == enemy.hp_max
    assert enemy.hp_max > 0


def test_run_combat_player_wins_against_weak_enemy():
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    enemy = Combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: CombatAction.ATTACK)

    assert result is CombatResult.VICTORY
    assert enemy.hp == 0
    assert player.hp > 0
    assert log


def test_run_combat_player_defeated_is_not_fatal():
    player = make_player(strength=1, defense=0, agility=1, hp=5, hp_max=20)
    enemy = Combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=20, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: CombatAction.ATTACK)

    assert result is CombatResult.DEFEAT
    assert player.hp > 0  # recovered, never truly dead — no game-over on an ordinary loss
    assert any("defeated" in line.lower() for line in log)


def test_run_combat_flee_ends_immediately_when_player_is_faster():
    player = make_player(strength=1, defense=0, agility=100, hp=50, hp_max=50)
    enemy = Combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=1, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: CombatAction.FLEE)

    assert result is CombatResult.FLED
    assert player.hp == 50
    assert enemy.hp == 100


def test_run_combat_does_not_advance_anything_but_hp():
    # No clock is passed in at all — combat only ever touches player.hp.
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    location_before = player.location_id
    enemy = Combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: CombatAction.ATTACK)

    assert player.location_id == location_before


def test_run_combat_is_deterministic():
    def make_matchup():
        return make_player(strength=15, defense=5, agility=10, hp=60, hp_max=60), make_enemy("bramblewood_wolf")

    p1, e1 = make_matchup()
    result1, log1 = run_combat(p1, e1, choose_action=lambda *_: CombatAction.ATTACK)

    p2, e2 = make_matchup()
    result2, log2 = run_combat(p2, e2, choose_action=lambda *_: CombatAction.ATTACK)

    assert result1 is result2
    assert log1 == log2
