from demonclock.resolve import resolve_entity


def test_exact_match_resolves():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("Old Lord", shortlist) == "npc_001"


def test_exact_match_is_case_and_whitespace_insensitive():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("  old   LORD  ", shortlist) == "npc_001"


def test_no_match_returns_none():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("Harbor Master", shortlist) is None


def test_duplicate_exact_names_are_ambiguous_and_unresolved():
    # Exactly why identity must be an id, never a name (SPEC.md §8).
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Lord")]
    assert resolve_entity("Old Lord", shortlist) is None


def test_fuzzy_substring_match_resolves_a_loosely_worded_reference():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("the old lord", shortlist) == "npc_001"


def test_fuzzy_match_works_in_the_other_direction_too():
    shortlist = [("node_042", "Old North Road")]
    assert resolve_entity("road", shortlist) == "node_042"


def test_fuzzy_ambiguous_match_is_unresolved():
    shortlist = [("npc_001", "Old Lord"), ("npc_002", "Old Blacksmith")]
    assert resolve_entity("old", shortlist) is None


def test_never_matches_something_absent_from_the_shortlist():
    # Bounded context (SPEC.md §8): even a real, well-known name elsewhere
    # in the world must not resolve unless it's actually on the shortlist
    # the caller retrieved.
    shortlist = [("npc_002", "Merchant Guild Rep")]
    assert resolve_entity("Old Lord", shortlist) is None


def test_empty_reference_text_returns_none():
    shortlist = [("npc_001", "Old Lord")]
    assert resolve_entity("   ", shortlist) is None


def test_empty_shortlist_returns_none():
    assert resolve_entity("Old Lord", []) is None


def test_resolves_against_real_world_nodes_by_name():
    from demonclock.seed import new_default_world

    world = new_default_world()
    shortlist = [(node.id, node.name) for node in world.nodes.values()]

    assert resolve_entity("Millhaven Market", shortlist) == "market"
    assert resolve_entity("wilds", shortlist) == "wilds"  # substring of "Bramblewood Wilds"
    assert resolve_entity("Some Unrelated Place", shortlist) is None
