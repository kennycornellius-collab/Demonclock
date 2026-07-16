import pytest

from demonclock.combat import Combatant, StatModifier, apply_skill, effective_stat, tick_upkeep, usable_skills
from demonclock.skills import (
    BASIC_ATTACK,
    Effect,
    EffectKind,
    FairCost,
    Skill,
    SkillError,
    StatType,
    compute_fair_cost,
    compute_magnitude,
    generate_skill_id,
    is_underpriced,
    starter_skills,
    validate_skill,
)


def make_combatant(**kwargs) -> Combatant:
    defaults = dict(
        name="Test", hp=100, hp_max=100, strength=10, agility=10, defense=5,
        magic=10, mana=50, mana_max=50,
    )
    defaults.update(kwargs)
    return Combatant(**defaults)


def make_skill(**kwargs) -> Skill:
    defaults = dict(
        id="test_skill", name="Test Skill", effects=[Effect(EffectKind.DAMAGE)],
        base_damage=10, attribute_multiplier=1.0, attribute_type=StatType.STRENGTH,
    )
    defaults.update(kwargs)
    return Skill(**defaults)


# -- validation --------------------------------------------------------------

def test_validate_skill_rejects_buff_without_stat():
    skill = make_skill(effects=[Effect(EffectKind.BUFF)])
    with pytest.raises(SkillError):
        validate_skill(skill)


def test_validate_skill_rejects_debuff_without_stat():
    skill = make_skill(effects=[Effect(EffectKind.DEBUFF)])
    with pytest.raises(SkillError):
        validate_skill(skill)


def test_validate_skill_accepts_buff_with_stat():
    skill = make_skill(effects=[Effect(EffectKind.BUFF, stat=StatType.STRENGTH)])
    validate_skill(skill)  # does not raise


def test_validate_skill_never_rejects_on_power_alone():
    # Skill creation is unrestricted by design (SPEC.md §6b) — a 0-cost,
    # absurdly powerful skill is legal; validate_skill only guards the enum
    # boundary, never balance.
    skill = make_skill(mana_cost=0, base_damage=99999)
    validate_skill(skill)


def test_skill_dict_round_trip():
    skill = make_skill(effects=[Effect(EffectKind.DEBUFF, stat=StatType.DEFENSE)])
    restored = Skill.from_dict(skill.to_dict())
    assert restored == skill


def test_starter_skills_returns_independent_lists():
    a = starter_skills()
    b = starter_skills()
    assert a == b
    assert a is not b


# -- effects -------------------------------------------------------------

def test_damage_effect_reduces_target_hp():
    caster = make_combatant(strength=20)
    target = make_combatant(defense=0)
    log = []

    apply_skill(caster, target, BASIC_ATTACK, log)

    assert target.hp < target.hp_max
    assert log


def test_heal_effect_caps_at_hp_max():
    caster = make_combatant(hp=95, hp_max=100, magic=50)
    skill = make_skill(effects=[Effect(EffectKind.HEAL)], attribute_type=StatType.MAGIC, base_damage=50)

    apply_skill(caster, make_combatant(), skill, [])

    assert caster.hp == 100


def test_lifesteal_heals_caster_from_damage_dealt():
    caster = make_combatant(hp=50, hp_max=100, strength=30)
    target = make_combatant(hp=200, hp_max=200, defense=0)
    skill = make_skill(effects=[Effect(EffectKind.DAMAGE), Effect(EffectKind.LIFESTEAL)])

    apply_skill(caster, target, skill, [])

    assert caster.hp > 50
    assert target.hp < 200


def test_lifesteal_without_damage_is_a_noop():
    caster = make_combatant(hp=50, hp_max=100)
    skill = make_skill(effects=[Effect(EffectKind.LIFESTEAL)])

    apply_skill(caster, make_combatant(), skill, [])

    assert caster.hp == 50


def test_shield_effect_grants_caster_absorb_hp():
    caster = make_combatant(shield=0)
    skill = make_skill(effects=[Effect(EffectKind.SHIELD)], base_damage=20)

    apply_skill(caster, make_combatant(), skill, [])

    assert caster.shield > 0


def test_shield_absorbs_damage_before_hp():
    target = make_combatant(hp=100, hp_max=100, shield=1000)
    attacker = make_combatant(strength=10)

    apply_skill(attacker, target, BASIC_ATTACK, [])

    assert target.hp == 100
    assert target.shield < 1000


def test_stun_effect_sets_stun_turns_on_opponent():
    caster = make_combatant()
    target = make_combatant(stun_turns=0)
    skill = make_skill(effects=[Effect(EffectKind.STUN)])

    apply_skill(caster, target, skill, [])

    assert target.stun_turns > 0


def test_tick_upkeep_consumes_stun_and_reports_turn_skipped():
    combatant = make_combatant(stun_turns=1)

    skipped = tick_upkeep(combatant, [])

    assert skipped is True
    assert combatant.stun_turns == 0


def test_dot_effect_ticks_over_its_duration_then_expires():
    caster = make_combatant(strength=20)
    target = make_combatant(hp=100, hp_max=100)
    skill = make_skill(effects=[Effect(EffectKind.DOT)])

    apply_skill(caster, target, skill, [])
    assert target.dot_turns_remaining > 0

    hp_before = target.hp
    for _ in range(target.dot_turns_remaining):
        tick_upkeep(target, [])

    assert target.hp < hp_before
    assert target.dot_turns_remaining == 0


def test_buff_effect_raises_effective_stat_then_expires():
    caster = make_combatant(strength=10)
    skill = make_skill(effects=[Effect(EffectKind.BUFF, stat=StatType.STRENGTH)], base_damage=15)

    apply_skill(caster, make_combatant(), skill, [])
    assert effective_stat(caster, StatType.STRENGTH) > 10

    for _ in range(10):
        tick_upkeep(caster, [])
    assert effective_stat(caster, StatType.STRENGTH) == 10


def test_debuff_effect_lowers_effective_stat_floored_at_zero():
    caster = make_combatant(strength=999)
    target = make_combatant(defense=5)
    skill = make_skill(effects=[Effect(EffectKind.DEBUFF, stat=StatType.DEFENSE)], base_damage=999)

    apply_skill(caster, target, skill, [])

    assert effective_stat(target, StatType.DEFENSE) == 0


def test_cleanse_strips_dot_and_debuffs_but_keeps_buffs():
    caster = make_combatant(strength=10)
    caster.dot_damage = 5
    caster.dot_turns_remaining = 3
    caster.stun_turns = 1
    caster.modifiers = [
        StatModifier(stat=StatType.STRENGTH, amount=10, turns_remaining=3),  # buff
        StatModifier(stat=StatType.DEFENSE, amount=-5, turns_remaining=3),   # debuff
    ]
    skill = make_skill(effects=[Effect(EffectKind.CLEANSE)])

    apply_skill(caster, make_combatant(), skill, [])

    assert caster.dot_turns_remaining == 0
    assert caster.stun_turns == 0
    assert len(caster.modifiers) == 1
    assert caster.modifiers[0].amount > 0


def test_inert_effects_are_declared_but_mechanically_do_nothing():
    caster = make_combatant(hp=100)
    target = make_combatant(hp=100)
    log = []

    for kind in (EffectKind.AOE, EffectKind.KNOCKBACK, EffectKind.TAUNT):
        skill = make_skill(effects=[Effect(kind)])
        apply_skill(caster, target, skill, log)

    assert caster.hp == 100
    assert target.hp == 100
    assert len(log) == 3


# -- usable_skills / cooldowns --------------------------------------------

def test_usable_skills_always_includes_basic_attack():
    combatant = make_combatant(mana=0, skills=[])
    assert BASIC_ATTACK in usable_skills(combatant)


def test_usable_skills_excludes_unaffordable_skill():
    expensive = make_skill(id="pricey", mana_cost=100)
    combatant = make_combatant(mana=5, skills=[expensive])
    assert expensive not in usable_skills(combatant)


def test_usable_skills_excludes_skill_on_cooldown():
    skill = make_skill(id="onslot", mana_cost=0, cooldown=2)
    combatant = make_combatant(mana=50, skills=[skill], cooldowns={"onslot": 2})
    assert skill not in usable_skills(combatant)


def test_cooldown_clears_after_enough_upkeep_ticks():
    combatant = make_combatant(cooldowns={"onslot": 1})
    tick_upkeep(combatant, [])
    assert "onslot" not in combatant.cooldowns


# -- fair-cost calculator (Stage 3, SPEC.md §6b) --------------------------

def test_compute_magnitude_matches_spec_formula():
    # base 100, mult 1.5, stat 10 -> (100*1.5)+10 = 160, SPEC.md §6b's example
    assert compute_magnitude(base_damage=100, attribute_multiplier=1.5, stat_value=10) == 160


def test_compute_fair_cost_matches_the_formula_for_a_single_effect():
    fair = compute_fair_cost([Effect(EffectKind.DAMAGE)], magnitude=20)
    assert fair == FairCost(mana_cost=7, cooldown=1, cast_time=0)


def test_compute_fair_cost_is_free_with_no_effects():
    fair = compute_fair_cost([], magnitude=999)
    assert fair == FairCost(mana_cost=0, cooldown=0, cast_time=0)


def test_compute_fair_cost_rises_with_more_composed_effects():
    single = compute_fair_cost([Effect(EffectKind.DAMAGE)], magnitude=50)
    stacked = compute_fair_cost([Effect(EffectKind.DAMAGE), Effect(EffectKind.DOT)], magnitude=50)
    assert stacked.mana_cost > single.mana_cost


def test_is_underpriced_true_when_any_dimension_undercuts_fair():
    fair = FairCost(mana_cost=10, cooldown=2, cast_time=1)
    assert is_underpriced(make_skill(mana_cost=0), fair) is True
    assert is_underpriced(make_skill(mana_cost=10, cooldown=0), fair) is True
    assert is_underpriced(make_skill(mana_cost=10, cooldown=2, cast_time=0), fair) is True


def test_is_underpriced_false_when_cost_meets_or_exceeds_fair_on_every_dimension():
    fair = FairCost(mana_cost=10, cooldown=2, cast_time=1)
    skill = make_skill(mana_cost=10, cooldown=2, cast_time=1)
    assert is_underpriced(skill, fair) is False


def test_generate_skill_id_slugifies_the_name():
    assert generate_skill_id("Fire Bolt!", existing_ids=set()) == "fire_bolt"


def test_generate_skill_id_dedupes_collisions():
    assert generate_skill_id("Firebolt", existing_ids={"firebolt"}) == "firebolt_2"
    assert generate_skill_id("Firebolt", existing_ids={"firebolt", "firebolt_2"}) == "firebolt_3"
