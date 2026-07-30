from demonclock.parser import ActionType, parse


def test_go_north_parses_to_move_with_target():
    action = parse("go north")
    assert action.type is ActionType.MOVE
    assert action.target == "north"


def test_verb_aliases_map_to_same_action():
    assert parse("walk east").type is ActionType.MOVE
    assert parse("travel south").type is ActionType.MOVE
    assert parse("inv").type is ActionType.INVENTORY
    assert parse("sleep").type is ActionType.REST
    assert parse("journal").type is ActionType.JOURNAL
    assert parse("recap").type is ActionType.JOURNAL


def test_bare_i_is_not_a_shorthand_for_inventory():
    # "i" collides with the pronoun "I" -- the overwhelmingly common opening
    # word of a first-person free-text sentence ("I attack the wolf"), which
    # this shorthand used to silently swallow as an inventory check.
    action = parse("i decided to shovel the snow")
    assert action.type is ActionType.UNRECOGNIZED


def test_look_with_no_target():
    action = parse("look")
    assert action.type is ActionType.LOOK
    assert action.target is None


def test_look_check_l_alone_still_match_deterministically():
    assert parse("look").type is ActionType.LOOK
    assert parse("check").type is ActionType.LOOK
    assert parse("l").type is ActionType.LOOK
    assert parse("LOOK").type is ActionType.LOOK  # case-insensitive, same as every other verb


def test_look_with_trailing_text_falls_through_to_unrecognized():
    # Regression test: "look"/"check" have no redundant full-word alias
    # like "i" had ("inv"/"inventory"), so instead of dropping them
    # entirely, they now only match deterministically standing alone --
    # actions._resolve_look never reads a target, so trailing text here is
    # always either nothing lost (bare "look") or an ordinary sentence
    # continuing past the verb ("Look, I really don't want to fight..."),
    # never a real argument.
    assert parse("look around").type is ActionType.UNRECOGNIZED
    assert parse("look, i really don't want to fight").type is ActionType.UNRECOGNIZED
    assert parse("check this out").type is ActionType.UNRECOGNIZED
    assert parse("l around").type is ActionType.UNRECOGNIZED


def test_case_insensitive():
    action = parse("GO North")
    assert action.type is ActionType.MOVE
    assert action.target == "north"


def test_unrecognized_verb_carries_helpful_message():
    action = parse("xyzzy the frobnicator")
    assert action.type is ActionType.UNRECOGNIZED
    assert "xyzzy" in action.message


def test_empty_input_is_unrecognized():
    action = parse("   ")
    assert action.type is ActionType.UNRECOGNIZED
    assert action.message


# -- Step 12 Chunk A: the 8 new deterministic verbs -------------------------

def test_fight_verb_aliases_map_to_fight():
    assert parse("fight").type is ActionType.FIGHT
    assert parse("attack the wolf").type is ActionType.FIGHT


def test_trade_verb_aliases_map_to_trade():
    assert parse("trade").type is ActionType.TRADE
    assert parse("buy grain").type is ActionType.TRADE
    assert parse("sell pelt").type is ActionType.TRADE


def test_talk_verb_aliases_map_to_talk_and_carries_the_target():
    action = parse("talk to hana")
    assert action.type is ActionType.TALK
    assert action.target == "to hana"
    assert parse("speak").type is ActionType.TALK


def test_craft_verb_maps_to_craft():
    assert parse("craft bread").type is ActionType.CRAFT


def test_skills_atlas_quests_ask_around_verbs():
    assert parse("skills").type is ActionType.SKILLS
    assert parse("atlas").type is ActionType.ATLAS
    assert parse("map").type is ActionType.ATLAS
    assert parse("quests").type is ActionType.QUESTS
    assert parse("quest").type is ActionType.QUESTS
    assert parse("rumors").type is ActionType.ASK_AROUND
    assert parse("gossip").type is ActionType.ASK_AROUND
