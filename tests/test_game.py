"""game.py's menu/REPL layer -- previously untested (verified only via
scripted manual REPL runs, per the module's own history). This file's first
job is regression coverage for the "0"-selects-the-last-item bug and the
combat-menu silent-default-substitution bug, both fixed together since they
shared the exact same code (see updates.md/CLAUDE.md build-progress entries).

Combat sites are tested by monkeypatching combat.run_group_combat/
boss.run_encounter to a stub that calls the real `choose_action` closure
once against controlled inputs, rather than playing out a whole (RNG-driven,
many-round) fight -- isolates the callback's own input-handling logic, which
is what these bugs actually lived in.
"""
from demonclock import game
from demonclock.clock import Clock
from demonclock.combat import BASIC_ATTACK, Combatant, CombatResult
from demonclock.boss import EncounterResult
from demonclock.models import Player
from demonclock.skills import EffectKind, StatType
from demonclock.state import GameState
from demonclock.world import World


def make_state(**player_kwargs) -> GameState:
    defaults = dict(name="Hero", location_id="village")
    defaults.update(player_kwargs)
    return GameState(world=World(), player=Player(**defaults), clock=Clock())


def feed_inputs(monkeypatch, values: list[str]):
    queue = iter(values)

    def fake_input(*_args):
        try:
            return next(queue)
        except StopIteration:
            raise AssertionError("input() called more times than the test scripted") from None

    monkeypatch.setattr("builtins.input", fake_input)


# --- _select -----------------------------------------------------------------

def test_select_rejects_zero_negative_out_of_range_and_non_numeric():
    items = ["a", "b", "c"]
    assert game._select(items, "0") is None  # the actual bug: used to wrap to items[-1] == "c"
    assert game._select(items, "-1") is None
    assert game._select(items, "4") is None
    assert game._select(items, "abc") is None
    assert game._select(items, "") is None


def test_select_returns_the_item_for_a_valid_one_based_choice():
    items = ["a", "b", "c"]
    assert game._select(items, "1") == "a"
    assert game._select(items, "3") == "c"


# --- combat menus: reprompt instead of silently substituting -----------------

def test_handle_fight_reprompts_on_an_invalid_skill_choice_instead_of_defaulting(monkeypatch, capsys):
    state = make_state()
    captured = {}

    def fake_run_group_combat(player, enemies, choose_action, current_day=0, rng=None):
        captured["result"] = choose_action(Combatant.from_player(player), enemies, [BASIC_ATTACK])
        return CombatResult.FLED, ["stub log"]

    monkeypatch.setattr(game.combat, "run_group_combat", fake_run_group_combat)
    monkeypatch.setattr(
        game, "make_enemy",
        lambda enemy_id: Combatant(name="Wolf", hp=30, hp_max=30, strength=8, agility=12, defense=2),
    )
    # Fight, then two invalid skill picks (the "0"-wraparound shape and a
    # non-numeric one), then Flee (option "2" since there's only one usable
    # skill) -- proves the callback reprompts rather than defaulting to
    # Basic Attack on either bad input.
    feed_inputs(monkeypatch, ["1", "0", "abc", "2"])

    game._handle_fight(state, ["bramblewood_wolf"])

    out = capsys.readouterr().out
    assert out.count("Not a valid choice.") == 2
    assert captured["result"] is None  # None == fled, not a silently-defaulted Basic Attack


def test_handle_fight_reprompts_on_an_invalid_target_choice_instead_of_defaulting(monkeypatch, capsys):
    state = make_state()
    captured = {}

    def fake_run_group_combat(player, enemies, choose_action, current_day=0, rng=None):
        captured["enemies"] = enemies
        captured["result"] = choose_action(Combatant.from_player(player), enemies, [BASIC_ATTACK])
        return CombatResult.FLED, ["stub log"]

    monkeypatch.setattr(game.combat, "run_group_combat", fake_run_group_combat)
    monkeypatch.setattr(
        game, "make_enemy",
        lambda enemy_id: Combatant(name="Wolf", hp=30, hp_max=30, strength=8, agility=12, defense=2),
    )
    # Fight, Basic Attack, an invalid target pick ("0" -- the wraparound
    # shape that used to silently pick the FIRST enemy instead of rejecting
    # the input), then a valid pick of the second enemy.
    feed_inputs(monkeypatch, ["1", "1", "0", "2"])

    game._handle_fight(state, ["bramblewood_wolf", "bramblewood_wolf"])

    out = capsys.readouterr().out
    assert "Not a valid choice." in out
    skill, target = captured["result"]
    assert skill is BASIC_ATTACK
    assert target is captured["enemies"][1]  # the SECOND enemy, not silently defaulted to the first


def test_handle_demon_king_reprompts_on_an_invalid_skill_choice_instead_of_defaulting(monkeypatch, capsys):
    state = make_state()
    captured = {}

    def fake_run_encounter(player, encounter, choose_action, rng=None):
        boss_combatant = Combatant(name="The Demon King", hp=200, hp_max=200, strength=18, agility=12, defense=8)
        captured["result"] = choose_action(Combatant.from_player(player), boss_combatant, [], [BASIC_ATTACK])
        return EncounterResult.FLED, ["stub log"]

    monkeypatch.setattr(game.boss, "run_encounter", fake_run_encounter)
    feed_inputs(monkeypatch, ["1", "0", "abc", "2"])  # Confront, invalid, invalid, Flee

    game._handle_demon_king(state)

    out = capsys.readouterr().out
    assert out.count("Not a valid choice.") == 2
    assert captured["result"] is None
    assert state.player.game_over is None  # FLED must never set game_over


def test_handle_demon_king_reprompts_on_an_invalid_target_choice_instead_of_defaulting(monkeypatch, capsys):
    state = make_state()
    captured = {}
    cultist = Combatant(name="Bound Cultist", hp=25, hp_max=25, strength=6, agility=9, defense=1)

    def fake_run_encounter(player, encounter, choose_action, rng=None):
        boss_combatant = Combatant(name="The Demon King", hp=200, hp_max=200, strength=18, agility=12, defense=8)
        captured["boss"] = boss_combatant
        captured["result"] = choose_action(Combatant.from_player(player), boss_combatant, [cultist], [BASIC_ATTACK])
        return EncounterResult.FLED, ["stub log"]

    monkeypatch.setattr(game.boss, "run_encounter", fake_run_encounter)
    # Confront, Basic Attack, an invalid target pick, then target "2" (the
    # cultist, targets[1]) -- used to silently default to targets[0] (the
    # boss) on invalid input instead of rejecting it.
    feed_inputs(monkeypatch, ["1", "1", "0", "2"])

    game._handle_demon_king(state)

    out = capsys.readouterr().out
    assert "Not a valid choice." in out
    skill, target = captured["result"]
    assert target is cultist
    assert target is not captured["boss"]
