"""Chunk A of "faction standing: combat trigger" (updates.md, resolved
2026-07-31): the archetype-to-stat-block foundation, tested in isolation --
no UI, no killing, no standing changes exist yet (Chunks B/C)."""
from demonclock.combat import Combatant
from demonclock.models import NPC
from demonclock.npc_combat import NPCArchetype, archetype_for, combatant_for_npc


def make_npc(**kwargs) -> NPC:
    defaults = dict(id="test_npc", name="Test NPC", location_id="village", tags=[])
    defaults.update(kwargs)
    return NPC(**defaults)


# -- archetype_for -----------------------------------------------------------

def test_archetype_for_defaults_to_civilian_when_untagged():
    assert archetype_for(make_npc(tags=[])) is NPCArchetype.CIVILIAN


def test_archetype_for_defaults_to_civilian_for_flavor_only_tags():
    # "villager"/"retired" are real seed.py/generation tags but not
    # archetypes -- must not accidentally match anything.
    assert archetype_for(make_npc(tags=["villager", "retired"])) is NPCArchetype.CIVILIAN


def test_archetype_for_matches_merchant_tag():
    assert archetype_for(make_npc(tags=["villager", "merchant"])) is NPCArchetype.MERCHANT


def test_archetype_for_matches_guard_tag():
    assert archetype_for(make_npc(tags=["guard"])) is NPCArchetype.GUARD


def test_archetype_for_matches_warrior_tag():
    assert archetype_for(make_npc(tags=["warrior"])) is NPCArchetype.WARRIOR


def test_archetype_for_prefers_the_stronger_archetype_when_multiple_tags_match():
    assert archetype_for(make_npc(tags=["merchant", "guard"])) is NPCArchetype.GUARD
    assert archetype_for(make_npc(tags=["guard", "warrior"])) is NPCArchetype.WARRIOR


# -- combatant_for_npc ---------------------------------------------------

def test_combatant_for_npc_returns_a_full_hp_combatant_named_after_the_npc():
    npc = make_npc(name="Old Miller", tags=["guard"])
    combatant = combatant_for_npc(npc)

    assert isinstance(combatant, Combatant)
    assert combatant.name == "Old Miller"
    assert combatant.hp == combatant.hp_max


def test_combatant_for_npc_uses_civilian_stats_for_an_untagged_npc():
    civilian = combatant_for_npc(make_npc(tags=[]))
    assert civilian.hp_max == 15
    assert civilian.strength == 3


def test_combatant_for_npc_stats_scale_with_archetype_strength():
    civilian = combatant_for_npc(make_npc(tags=[]))
    merchant = combatant_for_npc(make_npc(tags=["merchant"]))
    guard = combatant_for_npc(make_npc(tags=["guard"]))
    warrior = combatant_for_npc(make_npc(tags=["warrior"]))

    assert civilian.hp_max < merchant.hp_max < guard.hp_max < warrior.hp_max
    assert civilian.strength < merchant.strength < guard.strength < warrior.strength


def test_combatant_for_npc_never_crits_by_default():
    # Same "start rough" status every enemy/boss/add already has (Step 9) --
    # an NPC never has an explicit luck stat set here either.
    assert combatant_for_npc(make_npc(tags=["warrior"])).luck == 0


def test_combatant_for_npc_starts_with_no_learned_skills():
    # usable_skills(combatant) is therefore always [BASIC_ATTACK], same as
    # every other enemy/boss/add today (Step 10 Stage 6).
    assert combatant_for_npc(make_npc(tags=["guard"])).skills == []


def test_two_calls_for_the_same_npc_return_independent_combatants():
    npc = make_npc(tags=["guard"])
    first = combatant_for_npc(npc)
    second = combatant_for_npc(npc)

    first.hp = 1
    assert second.hp == second.hp_max  # mutating one must not affect the other
