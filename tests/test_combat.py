from demonclock.combat import Combatant, CombatResult, apply_skill, run_combat, turn_order
from demonclock.enemies import make_enemy
from demonclock.models import Player
from demonclock.skills import BASIC_ATTACK, Effect, EffectKind, Skill, StatType


def make_player(**kwargs) -> Player:
    defaults = dict(name="Hero", location_id="village")
    defaults.update(kwargs)
    return Player(**defaults)


def make_combatant(**kwargs) -> Combatant:
    defaults = dict(name="Foe", hp=10, hp_max=10, strength=5, agility=5, defense=0)
    defaults.update(kwargs)
    return Combatant(**defaults)


def test_basic_attack_applies_defense_mitigation():
    attacker = make_combatant(strength=10)
    weak_def = make_combatant(hp=100, hp_max=100, defense=0)
    strong_def = make_combatant(hp=100, hp_max=100, defense=10)

    apply_skill(attacker, weak_def, BASIC_ATTACK, [])
    apply_skill(attacker, strong_def, BASIC_ATTACK, [])

    assert (100 - strong_def.hp) < (100 - weak_def.hp)


def test_basic_attack_damage_floors_at_one():
    attacker = make_combatant(strength=1)
    tank = make_combatant(hp=100, hp_max=100, defense=9999)

    apply_skill(attacker, tank, BASIC_ATTACK, [])

    assert tank.hp == 99


def test_turn_order_faster_combatant_acts_first():
    fast = make_combatant(name="fast", agility=20)
    slow = make_combatant(name="slow", agility=5)

    assert turn_order(slow, fast) == ["enemy", "player"]
    assert turn_order(fast, slow) == ["player", "enemy"]


def test_turn_order_ties_favor_player():
    a = make_combatant(name="a", agility=10)
    b = make_combatant(name="b", agility=10)

    assert turn_order(a, b) == ["player", "enemy"]


def test_make_enemy_returns_full_health_combatant():
    enemy = make_enemy("bramblewood_wolf")
    assert enemy.hp == enemy.hp_max
    assert enemy.hp_max > 0


def test_run_combat_player_wins_against_weak_enemy():
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert result is CombatResult.VICTORY
    assert enemy.hp == 0
    assert player.hp > 0
    assert log


def test_run_combat_player_defeated_is_not_fatal():
    player = make_player(strength=1, defense=0, agility=1, hp=5, hp_max=20)
    enemy = make_combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=20, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert result is CombatResult.DEFEAT
    assert player.hp > 0  # recovered, never truly dead — no game-over on an ordinary loss
    assert any("defeated" in line.lower() for line in log)


def test_run_combat_flee_ends_immediately_when_player_is_faster():
    player = make_player(strength=1, defense=0, agility=100, hp=50, hp_max=50)
    enemy = make_combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=1, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: None)

    assert result is CombatResult.FLED
    assert player.hp == 50
    assert enemy.hp == 100


def test_run_combat_does_not_advance_anything_but_hp_and_mana():
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    location_before = player.location_id
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert player.location_id == location_before


def test_run_combat_is_deterministic():
    def make_matchup():
        return make_player(strength=15, defense=5, agility=10, hp=60, hp_max=60), make_enemy("bramblewood_wolf")

    p1, e1 = make_matchup()
    result1, log1 = run_combat(p1, e1, choose_action=lambda *_: BASIC_ATTACK)

    p2, e2 = make_matchup()
    result2, log2 = run_combat(p2, e2, choose_action=lambda *_: BASIC_ATTACK)

    assert result1 is result2
    assert log1 == log2


def test_run_combat_casts_a_learned_skill_and_deducts_mana():
    firebolt = Skill(
        id="firebolt_test",
        name="Firebolt",
        effects=[Effect(EffectKind.DAMAGE)],
        attribute_type=StatType.MAGIC,
        base_damage=50,
        attribute_multiplier=1.0,
        mana_cost=8,
    )
    player = make_player(strength=1, magic=50, defense=0, agility=100, hp=100, hp_max=100, mana=20, mana_max=20, skills=[firebolt])
    # One firebolt (100 dmg pre-mitigation) is enough to drop this enemy, so
    # the player only ever gets one turn — keeps the mana math unambiguous.
    enemy = make_combatant(name="Target", hp=50, hp_max=50, defense=0, agility=1)

    def choose_firebolt(fighter, _enemy, usable):
        return next(skill for skill in usable if skill.id == "firebolt_test")

    run_combat(player, enemy, choose_action=choose_firebolt)

    assert player.mana == 12  # 20 - 8
    assert enemy.hp == 0
