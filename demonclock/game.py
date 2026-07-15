"""Menu-driven REPL (SPEC.md §6): Move / Interact / Inventory / Rest /
Something else... The free-text box is the only place the parser runs.
"""
from __future__ import annotations

from . import combat, db
from .actions import resolve
from .clock import Clock
from .enemies import make_enemy
from .parser import parse
from .player import new_player
from .seed import WILD_ENEMY_BY_NODE, new_default_world
from .state import GameState

MENU = """
--- {node_name} (day {day}) ---
1) Move
2) Interact
3) Inventory
4) Rest
5) Something else...
6) Save & Quit
"""


def new_game(player_name: str) -> GameState:
    world = new_default_world()
    player = new_player(name=player_name, location_id="village")
    return GameState(world=world, player=player, clock=Clock())


def render_exits(state: GameState) -> None:
    links = state.world.links_from(state.player.location_id)
    if not links:
        print("There are no exits from here.")
        return
    print("Exits:")
    for link in links:
        if link.status == "open":
            print(f"  {link.direction} -> {state.world.nodes[link.to_id].name}")
        else:
            print(f"  {link.direction} -> ??? ({link.block_reason or 'blocked'})")


def handle_move(state: GameState) -> None:
    render_exits(state)
    direction = input("Go which direction? (blank to cancel) ").strip()
    if not direction:
        return
    outcome = resolve(parse(f"go {direction}"), state)
    print(outcome.message)


def handle_interact(state: GameState) -> None:
    # NPCs at a node would be listed here via a DB query, no AI (SPEC.md §6).
    # A recurring wild foe on "dangerous" nodes is wired in for this combat
    # stage (see seed.WILD_ENEMY_BY_NODE) — real NPCs/encounters are content
    # generation, a later part.
    enemy_id = WILD_ENEMY_BY_NODE.get(state.player.location_id)
    if enemy_id is None:
        print("There is no one here to talk to yet.")
        return

    enemy = make_enemy(enemy_id)
    print(f"A {enemy.name} blocks your path! (HP {enemy.hp}/{enemy.hp_max})")
    choice = input("1) Fight  2) Leave\n> ").strip()
    if choice != "1":
        return

    def choose_action(
        fighter: combat.Combatant, foe: combat.Combatant, options: list
    ):
        print(f"Your HP: {fighter.hp}/{fighter.hp_max} MANA: {fighter.mana}/{fighter.mana_max}  |  {foe.name} HP: {foe.hp}/{foe.hp_max}")
        for i, skill in enumerate(options, start=1):
            print(f"  {i}) {skill.name} (MP {skill.mana_cost})")
        print(f"  {len(options) + 1}) Flee")
        sub_choice = input("> ").strip()
        if sub_choice == str(len(options) + 1):
            return None
        try:
            return options[int(sub_choice) - 1]
        except (ValueError, IndexError):
            return options[0]  # invalid input defaults to the first (Basic Attack)

    _result, log = combat.run_combat(state.player, enemy, choose_action)
    for line in log:
        print(line)


def handle_inventory(state: GameState) -> None:
    print(resolve(parse("inventory"), state).message)


def handle_rest(state: GameState) -> None:
    print(resolve(parse("rest"), state).message)


def handle_free_text(state: GameState) -> None:
    text = input("What do you do? ").strip()
    if not text:
        return
    print(resolve(parse(text), state).message)


def run(save_path: str = db.DEFAULT_SAVE_PATH) -> None:
    conn = db.connect(save_path)
    db.init_schema(conn)

    loaded = db.load_game(conn)
    if loaded is not None:
        world, player, clock = loaded
        state = GameState(world=world, player=player, clock=clock)
        print(f"Welcome back, {player.name}. Resuming on day {clock.current_day}.")
    else:
        name = input("Name your character: ").strip() or "Hero"
        state = new_game(name)
        print(f"A new journey begins, {state.player.name}.")

    handlers = {
        "1": handle_move,
        "2": handle_interact,
        "3": handle_inventory,
        "4": handle_rest,
        "5": handle_free_text,
    }

    try:
        while True:
            node = state.world.nodes[state.player.location_id]
            print(MENU.format(node_name=node.name, day=state.clock.current_day))
            choice = input("> ").strip()

            if choice == "6":
                db.save_game(conn, state.world, state.player, state.clock)
                print("Saved. Farewell.")
                break

            handler = handlers.get(choice)
            if handler is None:
                print("Not a valid choice.")
                continue
            handler(state)
    finally:
        conn.close()
