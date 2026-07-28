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
