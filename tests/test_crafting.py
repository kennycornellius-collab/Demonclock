from demonclock.clock import Clock
from demonclock.crafting import RECIPES, craft
from demonclock.models import Node
from demonclock.player import add_item, new_player
from demonclock.state import GameState
from demonclock.world import World


def make_state(gold: int = 0) -> GameState:
    world = World()
    world.add_node(Node(id="village", name="Village", tags=["workshop"]))
    player = new_player(name="Hero", location_id="village")
    player.gold = gold
    return GameState(world=world, player=player, clock=Clock())


def test_bake_bread_recipe_exists_and_needs_three_grain():
    recipe = RECIPES["bake_bread"]
    assert recipe.inputs == {"grain": 3}
    assert recipe.output_item_id == "bread"
    assert recipe.output_quantity == 1


def test_craft_consumes_inputs_and_adds_the_output():
    state = make_state()
    add_item(state.player, "grain", "Grain", 3)

    log = craft(state, "bake_bread")

    grain = next((i for i in state.player.inventory if i.item_id == "grain"), None)
    assert grain is None  # fully consumed
    bread = next(i for i in state.player.inventory if i.item_id == "bread")
    assert bread.quantity == 1
    assert bread.name == "Bread"
    assert any("craft" in line for line in log)


def test_craft_leaves_a_partial_surplus_of_an_input():
    state = make_state()
    add_item(state.player, "grain", "Grain", 5)

    craft(state, "bake_bread")

    grain = next(i for i in state.player.inventory if i.item_id == "grain")
    assert grain.quantity == 2


def test_craft_fails_without_enough_of_an_input_and_does_not_mutate_state():
    state = make_state()
    add_item(state.player, "grain", "Grain", 2)

    log = craft(state, "bake_bread")

    grain = next(i for i in state.player.inventory if i.item_id == "grain")
    assert grain.quantity == 2  # untouched
    assert not any(i.item_id == "bread" for i in state.player.inventory)
    assert "need" in log[0].lower()


def test_craft_fails_entirely_when_no_inputs_are_owned_at_all():
    state = make_state()

    log = craft(state, "bake_bread")

    assert state.player.inventory == []
    assert "need" in log[0].lower()


def test_craft_fails_for_an_unknown_recipe():
    state = make_state()
    add_item(state.player, "grain", "Grain", 10)

    log = craft(state, "not_a_real_recipe")

    grain = next(i for i in state.player.inventory if i.item_id == "grain")
    assert grain.quantity == 10  # untouched
    assert "recipe" in log[0].lower()


def test_craft_records_a_behavior_action():
    state = make_state()
    add_item(state.player, "grain", "Grain", 3)

    craft(state, "bake_bread")

    assert state.player.behavior.crafting_actions == 1.0


def test_craft_does_not_record_a_behavior_action_on_failure():
    state = make_state()

    craft(state, "bake_bread")

    assert state.player.behavior.crafting_actions == 0.0


# -- economy depth: wool/iron_ore recipes ------------------------------------

def test_spin_cloth_recipe_exists_and_needs_two_wool():
    recipe = RECIPES["spin_cloth"]
    assert recipe.inputs == {"wool": 2}
    assert recipe.output_item_id == "cloth"
    assert recipe.output_quantity == 1


def test_smelt_iron_recipe_exists_and_needs_three_iron_ore():
    recipe = RECIPES["smelt_iron"]
    assert recipe.inputs == {"iron_ore": 3}
    assert recipe.output_item_id == "iron_ingot"
    assert recipe.output_quantity == 1


def test_craft_spin_cloth_consumes_wool_and_adds_cloth():
    state = make_state()
    add_item(state.player, "wool", "Wool", 2)

    craft(state, "spin_cloth")

    assert not any(i.item_id == "wool" for i in state.player.inventory)
    cloth = next(i for i in state.player.inventory if i.item_id == "cloth")
    assert cloth.quantity == 1


def test_craft_smelt_iron_consumes_iron_ore_and_adds_iron_ingot():
    state = make_state()
    add_item(state.player, "iron_ore", "Iron Ore", 3)

    craft(state, "smelt_iron")

    assert not any(i.item_id == "iron_ore" for i in state.player.inventory)
    ingot = next(i for i in state.player.inventory if i.item_id == "iron_ingot")
    assert ingot.quantity == 1
