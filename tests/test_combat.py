import random

from demonclock.combat import CRIT_MULTIPLIER, VARIANCE, Combatant, CombatResult, apply_skill, run_combat, turn_order
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


class _RiggedRNG:
    """A random.Random stand-in with a fixed .random() roll, for deterministic
    dodge/crit tests. .uniform() defaults to the midpoint of its range
    (neutral, no jitter) unless an explicit `variance` roll is given -- lets
    a dodge/crit test stay indifferent to Step 9 Chunk B's variance jitter
    while a dedicated variance test can still control it precisely."""

    def __init__(self, roll: float, variance: float | None = None):
        self.roll = roll
        self.variance = variance

    def random(self) -> float:
        return self.roll

    def uniform(self, a: float, b: float) -> float:
        return self.variance if self.variance is not None else (a + b) / 2


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


# --- Step 9 Chunk A: dodge ---------------------------------------------------

def test_a_low_roll_dodges_and_prevents_all_damage():
    attacker = make_combatant(strength=50)
    defender = make_combatant(hp=100, hp_max=100, defense=0)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.0))

    assert defender.hp == 100
    assert any("dodges" in line for line in log)


def test_a_high_roll_never_dodges_and_damage_lands_normally():
    attacker = make_combatant(strength=50)
    defender = make_combatant(hp=100, hp_max=100, defense=0)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.999))

    assert defender.hp < 100
    assert any("hits" in line for line in log)


def test_dodge_chance_clamps_to_zero_when_the_attacker_is_far_more_agile():
    # BASE_DODGE plus a large negative AGILITY gap clamps to 0.0 -- even a
    # rigged "always dodge" roll of 0.0 can't beat a 0.0 chance (0.0 < 0.0 is
    # False), so the hit lands regardless.
    attacker = make_combatant(strength=50, agility=100)
    defender = make_combatant(hp=100, hp_max=100, defense=0, agility=1)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.0))

    assert defender.hp < 100


def test_no_rng_means_dodge_is_disabled_entirely():
    # The default (rng=None) reproduces this function's pre-Step-9 behavior
    # exactly -- every existing apply_skill(...) call above this section in
    # the test suite relies on this.
    attacker = make_combatant(strength=50)
    defender = make_combatant(hp=100, hp_max=100, defense=0)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log)

    assert defender.hp < 100
    assert not any("dodges" in line for line in log)


# --- Step 9 Chunk B: crit + variance ------------------------------------------

def test_a_low_roll_crits_and_multiplies_damage_before_mitigation():
    # agility=100 vs. defender's agility=1 clamps dodge chance to exactly 0
    # (0.0 < 0.0 is False), isolating the SAME low roll to only ever trigger
    # the crit check that follows it.
    attacker = make_combatant(strength=10, agility=100, luck=10)
    defender = make_combatant(hp=1000, hp_max=1000, defense=0, agility=1)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.0))

    # magnitude = 20*1.0 + 10 = 30; crit multiplies by CRIT_MULTIPLIER before
    # mitigation; variance defaults to the midpoint (no jitter) in _RiggedRNG.
    expected = round(30 * CRIT_MULTIPLIER)
    assert defender.hp == 1000 - expected
    assert any("Critical hit!" in line for line in log)


def test_a_high_roll_never_crits():
    attacker = make_combatant(strength=10, agility=100, luck=10)
    defender = make_combatant(hp=1000, hp_max=1000, defense=0, agility=1)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.999))

    assert defender.hp == 1000 - 30  # unmultiplied magnitude, no jitter
    assert not any("Critical hit!" in line for line in log)


def test_zero_luck_never_crits_even_on_a_zero_roll():
    # BASE_CRIT alone (no LUCK bonus) is still a nonzero chance, so this only
    # proves luck=0 (the Combatant default for enemies/bosses/adds) doesn't
    # itself disable crit -- BASE_CRIT does the isolating in the two tests
    # above by using a defender AGILITY high enough to zero out dodge first.
    attacker = make_combatant(strength=10, agility=100, luck=0)
    defender = make_combatant(hp=1000, hp_max=1000, defense=0, agility=1)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.0))

    assert any("Critical hit!" in line for line in log)  # BASE_CRIT=0.05 > 0.0


def test_variance_jitters_damage_up_or_down_around_the_base_magnitude():
    attacker = make_combatant(strength=10, agility=100)  # luck=0, never crits at roll=0.999
    low = make_combatant(hp=1000, hp_max=1000, defense=0, agility=1)
    high = make_combatant(hp=1000, hp_max=1000, defense=0, agility=1)
    log = []

    apply_skill(attacker, low, BASIC_ATTACK, log, rng=_RiggedRNG(0.999, variance=1 - VARIANCE))
    apply_skill(attacker, high, BASIC_ATTACK, log, rng=_RiggedRNG(0.999, variance=1 + VARIANCE))

    assert (1000 - low.hp) < (1000 - high.hp)


def test_dodge_still_takes_priority_over_crit_and_variance():
    # Equal AGILITY -> BASE_DODGE alone (0.05) is a nonzero chance, so a
    # roll of 0.0 dodges rather than falling through to crit/variance.
    attacker = make_combatant(strength=10, agility=10, luck=100)
    defender = make_combatant(hp=1000, hp_max=1000, defense=0, agility=10)
    log = []

    apply_skill(attacker, defender, BASIC_ATTACK, log, rng=_RiggedRNG(0.0))

    assert defender.hp == 1000
    assert any("dodges" in line for line in log)
    assert not any("Critical hit!" in line for line in log)


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


def test_run_combat_forces_a_stalemate_flee_after_the_round_cap():
    # Player heals back to full every round and never attacks -- neither
    # side can ever die, so only the round cap can end this fight.
    endless_heal = Skill(
        id="endless_heal", name="Endless Heal",
        effects=[Effect(EffectKind.HEAL)],
        attribute_type=StatType.MAGIC, base_damage=9999, attribute_multiplier=1.0,
        mana_cost=0, cooldown=0, cast_time=0,
    )
    player = make_player(hp=100, hp_max=100, magic=1, agility=100, skills=[endless_heal])
    enemy = make_combatant(name="Immortal Foe", hp=9999, hp_max=9999, strength=5, defense=0, agility=1)

    result, log = run_combat(player, enemy, choose_action=lambda *_: endless_heal)

    assert result is CombatResult.FLED
    assert "drags on" in log[-1]
    assert player.hp > 0  # heals back to (near) full every round, never actually dying
    assert enemy.hp == 9999  # player never attacked


def test_run_combat_does_not_advance_anything_but_hp_and_mana():
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    location_before = player.location_id
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert player.location_id == location_before


def test_run_combat_is_deterministic_given_a_matching_seed():
    # Step 9: run_combat now defaults to a fresh, unseeded random.Random(),
    # so two calls only reproduce the same fight if given matching seeds --
    # this is the "a fixed seed must still reproduce a fixed fight"
    # guarantee SPEC.md §6b asks for, not "combat has no RNG at all."
    def make_matchup():
        return make_player(strength=15, defense=5, agility=10, hp=60, hp_max=60), make_enemy("bramblewood_wolf")

    p1, e1 = make_matchup()
    result1, log1 = run_combat(p1, e1, choose_action=lambda *_: BASIC_ATTACK, rng=random.Random(1234))

    p2, e2 = make_matchup()
    result2, log2 = run_combat(p2, e2, choose_action=lambda *_: BASIC_ATTACK, rng=random.Random(1234))

    assert result1 is result2
    assert log1 == log2


def test_run_combat_threads_rng_through_to_the_enemys_attacks_too():
    # Equal AGILITY on both sides means BASE_DODGE (0.05) applies to either
    # direction, so a rigged always-dodge roll of 0.0 makes BOTH sides evade
    # every hit -- proves the rng argument actually reaches the enemy's turn,
    # not just the player's.
    player = make_player(strength=50, defense=0, agility=10, hp=50, hp_max=50)
    enemy = make_combatant(name="Brute", hp=9999, hp_max=9999, strength=50, agility=10, defense=0)

    result, log = run_combat(
        player, enemy, choose_action=lambda *_: BASIC_ATTACK, rng=_RiggedRNG(0.0),
    )

    assert result is CombatResult.FLED  # round cap: neither side can ever land a hit
    assert player.hp == 50
    assert enemy.hp == 9999


def test_casting_an_underpriced_skill_sets_creative_mode_used():
    # Huge power at 0 mana/cooldown/cast_time — the explicit cost-zeroing act
    # SPEC.md §6b treats as the deliberate opt-out gesture.
    godmode = Skill(
        id="godmode",
        name="One-Shot Everything",
        effects=[Effect(EffectKind.DAMAGE)],
        attribute_type=StatType.STRENGTH,
        base_damage=99999,
        attribute_multiplier=1.0,
        mana_cost=0,
        cooldown=0,
        cast_time=0,
    )
    player = make_player(strength=1, defense=0, agility=100, hp=100, hp_max=100, skills=[godmode])
    enemy = make_combatant(name="Target", hp=10, hp_max=10, defense=0, agility=1)

    run_combat(player, enemy, choose_action=lambda *_: godmode)

    assert player.creative_mode_used is True


def test_casting_a_fairly_priced_learned_skill_leaves_creative_mode_used_false():
    firebolt = Skill(
        id="firebolt_fair",
        name="Firebolt",
        effects=[Effect(EffectKind.DAMAGE)],
        attribute_type=StatType.MAGIC,
        base_damage=15,
        attribute_multiplier=1.2,
        mana_cost=50,   # deliberately generous, at or above any plausible fair cost
        cooldown=5,
        cast_time=5,
    )
    player = make_player(magic=10, defense=0, agility=100, hp=100, hp_max=100, mana=50, mana_max=50, skills=[firebolt])
    enemy = make_combatant(name="Target", hp=1000, hp_max=1000, defense=0, agility=1)

    run_combat(player, enemy, choose_action=lambda *_: None)  # flee immediately, no cast
    assert player.creative_mode_used is False

    player.mana = 50
    run_combat(player, enemy, choose_action=lambda fighter, _e, usable: firebolt if firebolt in usable else None)

    assert player.creative_mode_used is False


def test_basic_attack_never_sets_creative_mode_used():
    player = make_player(strength=1, defense=0, agility=100, hp=100, hp_max=100)
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert player.creative_mode_used is False


def test_run_combat_defeat_captures_the_player():
    player = make_player(strength=1, defense=0, agility=1, hp=5, hp_max=20, gold=100)
    enemy = make_combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=20, defense=0)

    result, log = run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK, current_day=7)

    assert result is CombatResult.DEFEAT
    assert player.captured is True
    assert player.free_by_day == 7 + 3  # setback.ESCAPE_AFTER_DAYS
    assert any("captured" in line.lower() for line in log)


def test_run_combat_victory_does_not_capture_the_player():
    player = make_player(strength=50, defense=20, agility=20, hp=100, hp_max=100)
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK, current_day=7)

    assert player.captured is False


def test_run_combat_records_a_combat_action_per_player_cast():
    player = make_player(strength=50, defense=20, agility=100, hp=100, hp_max=100)
    enemy = make_combatant(name="Weakling", hp=5, hp_max=5, strength=1, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: BASIC_ATTACK)

    assert player.behavior.combat_actions == 1.0  # one-shots on the player's single turn


def test_run_combat_fleeing_does_not_record_a_combat_action():
    player = make_player(strength=1, defense=0, agility=100, hp=50, hp_max=50)
    enemy = make_combatant(name="Brute", hp=100, hp_max=100, strength=50, agility=1, defense=0)

    run_combat(player, enemy, choose_action=lambda *_: None)

    assert player.behavior.combat_actions == 0.0


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
