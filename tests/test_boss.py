import pytest

from demonclock.boss import (
    DEMON_KING_ENCOUNTER,
    Encounter,
    EncounterError,
    EncounterResult,
    Phase,
    PhaseTrigger,
    PhaseTriggerKind,
    run_encounter,
    validate_encounter,
)
from demonclock.combat import BASIC_ATTACK, Combatant
from demonclock.models import Player
from demonclock.skills import Effect, EffectKind, Skill, StatType


def make_player(**kwargs) -> Player:
    defaults = dict(
        name="Hero", location_id="village",
        strength=50, defense=20, agility=100, hp=500, hp_max=500,
    )
    defaults.update(kwargs)
    return Player(**defaults)


def make_boss(**kwargs) -> Combatant:
    defaults = dict(name="Demon King", hp=200, hp_max=200, strength=20, agility=5, defense=5)
    defaults.update(kwargs)
    return Combatant(**defaults)


def make_add(name="Cultist", **kwargs) -> Combatant:
    defaults = dict(name=name, hp=1, hp_max=1, strength=5, agility=1, defense=0)
    defaults.update(kwargs)
    return Combatant(**defaults)


def attack_boss(fighter, boss, active_adds, usable):
    return BASIC_ATTACK, boss


def attack_adds_then_boss(fighter, boss, active_adds, usable):
    target = active_adds[0] if active_adds else boss
    return BASIC_ATTACK, target


def two_phase_encounter() -> Encounter:
    phase1 = Phase(
        id="outer_ward",
        name="Outer Ward",
        trigger=PhaseTrigger(PhaseTriggerKind.ADDS_CLEARED),
        adds=[make_add("Cultist A"), make_add("Cultist B")],
        boss_immune=True,
        narrative_beat="Two cultists shield the demon king from harm.",
    )
    phase2 = Phase(
        id="demon_king",
        name="The Demon King",
        trigger=None,
        boss_immune=False,
        narrative_beat="The wards fall -- the demon king is exposed.",
    )
    return Encounter(id="demon_king_fight", name="the Demon King", boss=make_boss(), phases=[phase1, phase2])


# --- validate_encounter -----------------------------------------------------

def test_validate_encounter_rejects_empty_phases():
    encounter = Encounter(id="e", name="Empty", boss=make_boss(), phases=[])
    with pytest.raises(EncounterError):
        validate_encounter(encounter)


def test_validate_encounter_rejects_a_last_phase_with_a_trigger():
    phase = Phase(id="p1", name="Only Phase", trigger=PhaseTrigger(PhaseTriggerKind.TURN_COUNT, value=1))
    encounter = Encounter(id="e", name="Bad", boss=make_boss(), phases=[phase])
    with pytest.raises(EncounterError):
        validate_encounter(encounter)


def test_validate_encounter_rejects_an_earlier_phase_with_no_trigger():
    phase1 = Phase(id="p1", name="First", trigger=None)
    phase2 = Phase(id="p2", name="Last", trigger=None)
    encounter = Encounter(id="e", name="Bad", boss=make_boss(), phases=[phase1, phase2])
    with pytest.raises(EncounterError):
        validate_encounter(encounter)


def test_validate_encounter_accepts_a_well_formed_encounter():
    validate_encounter(two_phase_encounter())  # does not raise


# --- immunity ----------------------------------------------------------------

def test_boss_takes_no_damage_while_immune():
    boss = make_boss(hp=200, hp_max=200, agility=1, defense=5)
    phase1 = Phase(
        id="p1", name="Immune Phase",
        trigger=PhaseTrigger(PhaseTriggerKind.TURN_COUNT, value=2), boss_immune=True,
    )
    phase2 = Phase(id="p2", name="Vulnerable Phase", trigger=None, boss_immune=False)
    encounter = Encounter(id="e", name="Test Boss", boss=boss, phases=[phase1, phase2])
    player = make_player()

    result, log = run_encounter(player, encounter, choose_action=attack_boss)

    assert result is EncounterResult.VICTORY
    assert sum("has no effect" in line for line in log) == 2  # exactly the 2 immune rounds


# --- phase transitions ---------------------------------------------------------

def test_adds_cleared_trigger_advances_once_every_add_is_dead():
    encounter = two_phase_encounter()
    player = make_player()

    result, log = run_encounter(player, encounter, choose_action=attack_adds_then_boss)

    assert result is EncounterResult.VICTORY
    assert any("shield the demon king" in line for line in log)
    assert any("wards fall" in line for line in log)


def test_turn_count_trigger_advances_after_n_rounds_regardless_of_state():
    boss = make_boss(hp=9999, hp_max=9999, agility=1)
    phase1 = Phase(
        id="p1", name="Stalling Phase",
        trigger=PhaseTrigger(PhaseTriggerKind.TURN_COUNT, value=3), boss_immune=True,
    )
    phase2 = Phase(id="p2", name="Final Phase", trigger=None, boss_immune=False, narrative_beat="Now.")
    encounter = Encounter(id="e", name="Test Boss", boss=boss, phases=[phase1, phase2])
    player = make_player()

    calls = {"n": 0}

    def chooser(fighter, boss, active_adds, usable):
        calls["n"] += 1
        if calls["n"] > 3:
            return None
        return BASIC_ATTACK, boss

    result, log = run_encounter(player, encounter, choose_action=chooser)

    assert result is EncounterResult.FLED
    assert any(line == "Now." for line in log)


def test_hp_threshold_trigger_advances_once_boss_hp_falls_to_the_fraction():
    boss = make_boss(hp=200, hp_max=200, defense=0, agility=1)
    phase1 = Phase(
        id="p1", name="First Half",
        trigger=PhaseTrigger(PhaseTriggerKind.HP_THRESHOLD, value=0.5), boss_immune=False,
    )
    phase2 = Phase(id="p2", name="Second Half", trigger=None, boss_immune=False, narrative_beat="Enraged!")
    encounter = Encounter(id="e", name="Test Boss", boss=boss, phases=[phase1, phase2])
    player = make_player()

    result, log = run_encounter(player, encounter, choose_action=attack_boss)

    assert result is EncounterResult.VICTORY
    assert any(line == "Enraged!" for line in log)


# --- environment effects -------------------------------------------------------

def test_environment_skill_damages_the_player_every_round():
    scorch = Skill(
        id="scorch", name="Scorching Ground",
        effects=[Effect(EffectKind.DAMAGE)],
        attribute_type=StatType.MAGIC, base_damage=10, attribute_multiplier=1.0, mana_cost=0,
    )
    phase = Phase(id="p1", name="Only Phase", trigger=None, boss_immune=False, environment_skills=[scorch])
    boss = make_boss(hp=9999, hp_max=9999, strength=0, agility=0, defense=19)
    encounter = Encounter(id="e", name="Test Boss", boss=boss, phases=[phase])
    player = make_player(agility=100, defense=0, hp=100, hp_max=100)

    calls = {"n": 0}

    def chooser(fighter, boss, active_adds, usable):
        calls["n"] += 1
        if calls["n"] > 1:
            return None
        return BASIC_ATTACK, boss

    result, log = run_encounter(player, encounter, choose_action=chooser)

    assert result is EncounterResult.FLED
    # boss's own attack (strength 0 -> magnitude 20, player defense 0 -> 20
    # unmitigated) + one environment tick (environment actor's hardcoded
    # magic 10 + scorch's base_damage 10 -> magnitude 20, also unmitigated)
    assert player.hp == 100 - 20 - 20


# --- terminal outcomes -----------------------------------------------------

def test_victory_when_the_boss_dies_in_the_final_phase():
    phase = Phase(id="p1", name="Only Phase", trigger=None, boss_immune=False)
    boss = make_boss(hp=5, hp_max=5, defense=0)
    encounter = Encounter(id="e", name="Weakling", boss=boss, phases=[phase])
    player = make_player()

    result, log = run_encounter(player, encounter, choose_action=attack_boss)

    assert result is EncounterResult.VICTORY
    assert any("defeated" in line.lower() for line in log)


def test_defeat_when_the_player_dies_and_is_not_captured():
    phase = Phase(id="p1", name="Only Phase", trigger=None, boss_immune=False)
    boss = make_boss(hp=9999, hp_max=9999, strength=200, agility=200, defense=0)
    encounter = Encounter(id="e", name="Overwhelming Boss", boss=boss, phases=[phase])
    player = make_player(hp=10, hp_max=10, agility=1)

    result, log = run_encounter(player, encounter, choose_action=attack_boss)

    assert result is EncounterResult.DEFEAT
    assert player.captured is False  # unlike combat.run_combat, this is NOT a recoverable setback


def test_fled_ends_immediately_when_the_player_is_faster():
    encounter = two_phase_encounter()
    player = make_player(agility=1000, hp=50, hp_max=50)

    result, log = run_encounter(player, encounter, choose_action=lambda *_: None)

    assert result is EncounterResult.FLED
    assert player.hp == 50


# --- stored-definition immutability -----------------------------------------

def test_run_encounter_never_mutates_the_stored_encounter_definition():
    encounter = two_phase_encounter()
    original_boss_hp = encounter.boss.hp
    original_add_hp = encounter.phases[0].adds[0].hp

    run_encounter(make_player(), encounter, choose_action=attack_adds_then_boss)
    run_encounter(make_player(), encounter, choose_action=attack_adds_then_boss)

    assert encounter.boss.hp == original_boss_hp
    assert encounter.phases[0].adds[0].hp == original_add_hp


def test_choose_action_can_target_an_add_distinct_from_the_boss():
    encounter = two_phase_encounter()
    player = make_player()
    seen_add_hp = {}

    def chooser(fighter, boss, active_adds, usable):
        if active_adds:
            seen_add_hp["before"] = seen_add_hp.get("before", active_adds[0].hp)
            return BASIC_ATTACK, active_adds[0]
        return BASIC_ATTACK, boss

    result, log = run_encounter(player, encounter, choose_action=chooser)

    assert result is EncounterResult.VICTORY
    assert seen_add_hp["before"] == 1  # confirms the callback really saw the add's own state


# --- the real demon-king encounter (Chunk B) --------------------------------

def test_demon_king_encounter_is_well_formed():
    validate_encounter(DEMON_KING_ENCOUNTER)  # does not raise


def test_demon_king_encounter_is_winnable_by_a_strong_player():
    player = make_player(strength=200, defense=100, agility=100, hp=1000, hp_max=1000)

    result, log = run_encounter(player, DEMON_KING_ENCOUNTER, choose_action=attack_adds_then_boss)

    assert result is EncounterResult.VICTORY
    assert any("Demon King" in line for line in log)


def test_demon_king_encounter_is_lethal_to_a_weak_player():
    player = make_player(strength=1, defense=0, agility=1, hp=5, hp_max=5)

    result, log = run_encounter(player, DEMON_KING_ENCOUNTER, choose_action=attack_adds_then_boss)

    assert result is EncounterResult.DEFEAT
    # boss.py never touches this -- assigning it is game.py's job (Chunk B's
    # wiring), so it must still be unset here.
    assert player.game_over is None


def test_demon_king_encounter_is_not_mutated_by_playing_it():
    original_boss_hp = DEMON_KING_ENCOUNTER.boss.hp
    original_add_hp = DEMON_KING_ENCOUNTER.phases[0].adds[0].hp
    player = make_player(strength=200, defense=100, agility=100, hp=1000, hp_max=1000)

    run_encounter(player, DEMON_KING_ENCOUNTER, choose_action=attack_adds_then_boss)

    assert DEMON_KING_ENCOUNTER.boss.hp == original_boss_hp
    assert DEMON_KING_ENCOUNTER.phases[0].adds[0].hp == original_add_hp
