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
from demonclock.canon import PreconditionManifest
from demonclock.clock import Clock
from demonclock.combat import BASIC_ATTACK, Combatant, CombatResult
from demonclock.boss import EncounterResult
from demonclock.generation.free_text import ParsedAction
from demonclock.llm.config import GenerationConfig, ProviderSpec
from demonclock.llm.providers.mock import MockClient
from demonclock.llm.registry import LLMRegistry
from demonclock.models import NPC, Node, Player
from demonclock.parser import ActionType
from demonclock.pool import GeneratedItem
from demonclock.seed import new_default_world
from demonclock.skills import EffectKind, StatType
from demonclock.state import GameState
from demonclock.world import World


def make_state(**player_kwargs) -> GameState:
    defaults = dict(name="Hero", location_id="village")
    defaults.update(player_kwargs)
    return GameState(world=World(), player=Player(**defaults), clock=Clock())


def make_default_state(location_id: str = "village", **player_kwargs) -> GameState:
    """The real seeded world (village=workshop+Hana, market=trade+Oskar,
    wilds=two wolves) -- lets the Chunk C dispatch-routing tests exercise
    Fight/Trade/Talk/Craft availability against real content instead of a
    hand-built fixture per test."""
    defaults = dict(name="Hero", location_id=location_id)
    defaults.update(player_kwargs)
    return GameState(world=new_default_world(), player=Player(**defaults), clock=Clock())


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


# --- _available_context_actions -----------------------------------------

def test_available_context_actions_at_each_seeded_node():
    state = make_default_state()
    village = state.world.nodes["village"]
    market = state.world.nodes["market"]
    wilds = state.world.nodes["wilds"]
    road = state.world.nodes["road"]

    assert game._available_context_actions(state, village) == {ActionType.TALK, ActionType.CRAFT}
    assert game._available_context_actions(state, market) == {ActionType.TRADE, ActionType.TALK}
    assert game._available_context_actions(state, wilds) == {ActionType.FIGHT}
    assert game._available_context_actions(state, road) == set()


def test_available_context_actions_short_circuits_to_fight_only_at_a_demon_king_node():
    state = make_default_state()
    node = state.world.nodes["market"]  # otherwise offers TRADE + TALK
    node.tags.append("demon_king")

    assert game._available_context_actions(state, node) == {ActionType.FIGHT}


# --- Step 12 Chunk C: handle_free_text dispatch --------------------------

def test_free_text_move_dispatches_through_actions_resolve(monkeypatch, capsys):
    state = make_default_state()
    feed_inputs(monkeypatch, ["go east"])

    game.handle_free_text(state)

    assert state.player.location_id == "market"


def test_free_text_fight_dispatches_to_handle_fight_when_available(monkeypatch, capsys):
    state = make_default_state(location_id="wilds")
    feed_inputs(monkeypatch, ["fight", "2"])  # Fight, then Leave immediately

    game.handle_free_text(state)

    assert "block your path" in capsys.readouterr().out


def test_free_text_fight_gives_an_honest_message_when_unavailable(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # no wild enemy here
    feed_inputs(monkeypatch, ["fight"])

    game.handle_free_text(state)

    assert "nothing to fight here" in capsys.readouterr().out


def test_free_text_trade_dispatches_to_handle_trade_when_available(monkeypatch, capsys):
    state = make_default_state(location_id="market")
    feed_inputs(monkeypatch, ["trade", "3"])  # Trade, then Leave

    game.handle_free_text(state)

    assert "Trading at Millhaven Market" in capsys.readouterr().out


def test_free_text_trade_gives_an_honest_message_when_unavailable(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # no prices tracked here
    feed_inputs(monkeypatch, ["trade"])

    game.handle_free_text(state)

    assert "no trading to be done here" in capsys.readouterr().out


def test_free_text_craft_dispatches_to_handle_craft_when_available(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # tagged "workshop"
    feed_inputs(monkeypatch, ["craft", "99"])  # Craft, then an invalid pick to bail out

    game.handle_free_text(state)

    assert "Crafting at Millhaven Village" in capsys.readouterr().out


def test_free_text_craft_gives_an_honest_message_when_unavailable(monkeypatch, capsys):
    state = make_default_state(location_id="market")  # not a workshop
    feed_inputs(monkeypatch, ["craft"])

    game.handle_free_text(state)

    assert "nowhere to craft here" in capsys.readouterr().out


def test_free_text_talk_with_a_single_npc_present_dispatches_directly(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # only Hana is here
    feed_inputs(monkeypatch, ["talk"])

    game.handle_free_text(state)

    assert "--- Hana the Miller ---" in capsys.readouterr().out


def test_free_text_talk_with_no_npcs_present_gives_an_honest_message(monkeypatch, capsys):
    state = make_default_state(location_id="road")  # no NPCs here
    feed_inputs(monkeypatch, ["talk"])

    game.handle_free_text(state)

    assert "no one here to talk to" in capsys.readouterr().out


def _make_two_npc_state() -> GameState:
    world = World()
    world.add_node(Node(id="square", name="Town Square"))
    world.add_npc(NPC(id="anna", name="Anna", location_id="square", description=""))
    world.add_npc(NPC(id="bram", name="Bram", location_id="square", description=""))
    return GameState(world=world, player=Player(name="Hero", location_id="square"), clock=Clock())


def test_free_text_talk_with_a_target_resolves_the_right_npc_among_several(monkeypatch, capsys):
    state = _make_two_npc_state()
    feed_inputs(monkeypatch, ["talk to bram"])

    game.handle_free_text(state)

    out = capsys.readouterr().out
    assert "--- Bram ---" in out
    assert "--- Anna ---" not in out


def _npc_quest_item(item_id: str, title: str, giver_npc_id: str, reward_gold: int = 15) -> GeneratedItem:
    return GeneratedItem(
        id=item_id,
        payload={"title": title, "reward_gold": reward_gold, "giver_npc_id": giver_npc_id},
        manifest=PreconditionManifest([]),
    )


def test_handle_talk_offers_and_accepts_a_pooled_quest_tied_to_the_npc(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # Hana the Miller is "miller_hana"
    item = _npc_quest_item("deliver_flour", "Deliver Flour", "miller_hana")
    state.world.content_pool.append(item)
    feed_inputs(monkeypatch, ["talk", "y"])

    game.handle_free_text(state)

    out = capsys.readouterr().out
    assert "Deliver Flour" in out
    assert "Quest accepted." in out
    assert state.player.accepted_quests == [{**item.payload, "id": "deliver_flour"}]
    assert state.world.content_pool == []  # consumed, whether accepted or not


def test_handle_talk_declining_the_offered_quest_does_not_accept_it(monkeypatch, capsys):
    state = make_default_state(location_id="village")
    state.world.content_pool.append(_npc_quest_item("deliver_flour", "Deliver Flour", "miller_hana"))
    feed_inputs(monkeypatch, ["talk", "n"])

    game.handle_free_text(state)

    assert state.player.accepted_quests == []
    assert state.world.content_pool == []  # still not re-queued, same as handle_quests' own decline


def test_handle_talk_does_not_offer_a_quest_tied_to_a_different_npc(monkeypatch, capsys):
    state = make_default_state(location_id="village")  # only Hana is here
    other = _npc_quest_item("warden_task", "Warden's Task", "market_warden_oskar")
    state.world.content_pool.append(other)
    feed_inputs(monkeypatch, ["talk"])

    game.handle_free_text(state)

    out = capsys.readouterr().out
    assert "Warden's Task" not in out
    assert state.world.content_pool == [other]  # left in place for Oskar's own Talk (or the Quests menu)


def test_free_text_talk_with_no_target_and_several_npcs_prompts_for_a_pick(monkeypatch, capsys):
    state = _make_two_npc_state()
    feed_inputs(monkeypatch, ["talk", "2"])  # Talk, then pick the 2nd listed NPC

    game.handle_free_text(state)

    out = capsys.readouterr().out
    assert "Talk to whom?" in out


def test_free_text_skills_atlas_quests_ask_around_dispatch_to_their_own_handlers(monkeypatch, capsys):
    state = make_default_state()

    feed_inputs(monkeypatch, ["skills", "2"])  # Skills menu, then Back
    game.handle_free_text(state)
    assert "Your skills:" in capsys.readouterr().out

    feed_inputs(monkeypatch, ["atlas"])  # no beliefs yet -- returns immediately
    game.handle_free_text(state)
    assert "don't know of anywhere yet" in capsys.readouterr().out

    feed_inputs(monkeypatch, ["quests"])  # nothing accepted, empty pool -- returns immediately
    game.handle_free_text(state)
    assert "haven't accepted any quests yet" in capsys.readouterr().out

    feed_inputs(monkeypatch, ["rumors"])  # nothing in the event log -- returns immediately
    game.handle_free_text(state)
    assert "heard anything worth repeating" in capsys.readouterr().out


def test_free_text_unrecognized_with_no_registry_prints_the_honest_parser_message(monkeypatch, capsys):
    state = make_default_state()  # state.generation is None
    feed_inputs(monkeypatch, ["shovel the snow"])

    game.handle_free_text(state)

    assert "I don't understand" in capsys.readouterr().out


def test_free_text_ai_fallback_resolves_an_unrecognized_sentence_end_to_end(monkeypatch, capsys):
    # A real (offline, MockClient-backed) registry, not a monkeypatched
    # run_free_text_fallback -- exercises parser.py -> generation/
    # free_text.py -> game._dispatch_action end to end.
    config = GenerationConfig(roles={"parser": [ProviderSpec(provider="mock")]})
    registry = LLMRegistry(config, extra_clients={
        "mock": MockClient(responses=[{"action": ActionType.FIGHT.value}]),
    })
    state = make_default_state(location_id="wilds")
    state.generation = registry
    feed_inputs(monkeypatch, ["I lunge at the wolves", "2"])  # novel phrasing, then Leave

    game.handle_free_text(state)

    assert "block your path" in capsys.readouterr().out


def test_free_text_ai_fallback_result_is_still_gated_by_real_availability(monkeypatch, capsys):
    # The AI fallback's own schema can't name an action outside what was
    # available at call time (generation/free_text.py's own guarantee), but
    # this confirms the dispatcher-side gate holds too: even if a stale/
    # hypothetical response named FIGHT somewhere it isn't actually
    # available, _dispatch_action's own availability check still catches it.
    monkeypatch.setattr(
        game, "run_free_text_fallback",
        lambda registry, text, available: ParsedAction(action=ActionType.FIGHT, target=None),
    )
    config = GenerationConfig(roles={"parser": [ProviderSpec(provider="mock")]})
    state = make_default_state(location_id="village")  # no wild enemy here
    state.generation = LLMRegistry(config, extra_clients={"mock": MockClient(responses=[])})
    feed_inputs(monkeypatch, ["I lunge at something"])

    game.handle_free_text(state)

    assert "nothing to fight here" in capsys.readouterr().out
