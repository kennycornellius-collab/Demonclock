from demonclock.player import display_name


def test_display_name_title_cases_a_single_word_id():
    assert display_name("grain") == "Grain"


def test_display_name_replaces_underscores_with_spaces_before_title_casing():
    # Regression test: plain `item_id.title()` mishandles a snake_case id --
    # Python's str.title() doesn't treat "_" as a word boundary, so
    # "iron_ore".title() produces "Iron_Ore" rather than "Iron Ore".
    assert display_name("iron_ore") == "Iron Ore"
