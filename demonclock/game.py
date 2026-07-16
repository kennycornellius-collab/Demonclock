"""Menu-driven REPL (SPEC.md §6): Move / Interact / Inventory / Rest /
Something else... The free-text box is the only place the parser runs.
"""
from __future__ import annotations

from . import combat, db, skills
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
6) Skills
7) Save & Quit
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


def _render_skill_line(skill: skills.Skill) -> str:
    effects = ", ".join(
        e.kind.value + (f"({e.stat.value})" if e.stat else "") for e in skill.effects
    ) or "no effects"
    return f"{skill.name} — MP {skill.mana_cost}, CD {skill.cooldown}, cast {skill.cast_time} [{effects}]"


def _choose_stat(prompt: str) -> skills.StatType:
    options = list(skills.StatType)
    print(prompt)
    for i, stat in enumerate(options, start=1):
        print(f"  {i}) {stat.value}")
    raw = input("> ").strip()
    try:
        return options[int(raw) - 1]
    except (ValueError, IndexError):
        print(f"Not a valid choice, defaulting to {options[0].value}.")
        return options[0]


def _choose_effects() -> list[skills.Effect]:
    kinds = list(skills.EffectKind)
    chosen: list[skills.Effect] = []
    print("\nCompose effects from the enumerated vocabulary (SPEC.md §6b — never free text).")
    while True:
        print("Available effects:")
        for i, kind in enumerate(kinds, start=1):
            marker = " (inert this build stage)" if kind in skills.INERT_EFFECTS else ""
            print(f"  {i}) {kind.value}{marker}")
        raw = input(f"Add effect # ({len(chosen)} chosen so far, blank to finish): ").strip()
        if not raw:
            return chosen
        try:
            kind = kinds[int(raw) - 1]
        except (ValueError, IndexError):
            print("Not a valid choice.")
            continue
        stat = None
        if kind in (skills.EffectKind.BUFF, skills.EffectKind.DEBUFF):
            stat = _choose_stat(f"Which stat does {kind.value} target?")
        chosen.append(skills.Effect(kind, stat=stat))


def _prompt_int(prompt: str, default: int) -> int:
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"Not a number, using {default}.")
        return default


def _prompt_float(prompt: str, default: float) -> float:
    raw = input(prompt).strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        print(f"Not a number, using {default}.")
        return default


def _craft_skill(state: GameState) -> None:
    player = state.player
    effects = _choose_effects()
    if not effects:
        print("No effects chosen — cancelled.")
        return

    attribute_type = _choose_stat("Which attribute powers this skill?")
    name = input("Name your skill: ").strip() or "Unnamed Skill"
    base_damage = _prompt_int("Base power (0 or more): ", default=0)
    attribute_multiplier = _prompt_float("Attribute multiplier (e.g. 1.0): ", default=1.0)

    stat_value = getattr(player, attribute_type.value)
    magnitude = skills.compute_magnitude(base_damage, attribute_multiplier, stat_value)
    fair = skills.compute_fair_cost(effects, magnitude)
    print(
        f"\nEngine-computed fair cost for this power level: "
        f"{fair.mana_cost} MANA, {fair.cooldown} cooldown, {fair.cast_time} cast time."
    )

    accept = input("Accept this cost? (Y/n, 'n' sets your own — creative mode) ").strip().lower()
    if accept == "n":
        print("Anything you set below the fair cost will flag your save as")
        print("creative_mode_used the moment you actually cast this skill in combat.")
        mana_cost = _prompt_int(f"MANA cost [{fair.mana_cost}]: ", default=fair.mana_cost)
        cooldown = _prompt_int(f"Cooldown [{fair.cooldown}]: ", default=fair.cooldown)
        cast_time = _prompt_int(f"Cast time [{fair.cast_time}]: ", default=fair.cast_time)
    else:
        mana_cost, cooldown, cast_time = fair.mana_cost, fair.cooldown, fair.cast_time

    existing_ids = {s.id for s in player.skills} | {"basic_attack"}
    skill = skills.Skill(
        id=skills.generate_skill_id(name, existing_ids),
        name=name,
        effects=effects,
        attribute_type=attribute_type,
        base_damage=base_damage,
        attribute_multiplier=attribute_multiplier,
        mana_cost=mana_cost,
        cooldown=cooldown,
        cast_time=cast_time,
        computed_fair_cost=fair.mana_cost,
    )
    try:
        skills.validate_skill(skill)
    except skills.SkillError as exc:
        print(f"Could not create skill: {exc}")
        return

    player.skills.append(skill)
    print(f"Learned {skill.name}!")
    if skills.is_underpriced(skill, fair):
        print("(This undercuts the engine's fair cost — casting it will mark your save as creative mode.)")


def handle_skills(state: GameState) -> None:
    print("Your skills:")
    print("  Basic Attack — MP 0, CD 0, cast 0 [damage] (always available)")
    for skill in state.player.skills:
        print(f"  {_render_skill_line(skill)}")

    choice = input("\n1) Craft a new skill  2) Back\n> ").strip()
    if choice == "1":
        _craft_skill(state)


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
        "6": handle_skills,
    }

    try:
        while True:
            node = state.world.nodes[state.player.location_id]
            print(MENU.format(node_name=node.name, day=state.clock.current_day))
            choice = input("> ").strip()

            if choice == "7":
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
