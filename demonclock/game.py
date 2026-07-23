"""Menu-driven REPL (SPEC.md §6): Move / Interact / Inventory / Rest /
Something else... The free-text box is the only place the parser runs.
"""
from __future__ import annotations

from . import behavior, boss, combat, db, knowledge, pool, rumors, setback, skills
from .actions import resolve, resolve_fast_travel
from .clock import Clock
from .enemies import make_enemy
from .generation.narrator import narrate_combat_outcome, reword_rumor
from .llm.config import GenerationConfig
from .llm.registry import LLMRegistry
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
7) Atlas
8) Ask around
9) Quests
10) Save & Quit
"""

# Shown instead of MENU while Player.captured is set (SPEC.md §11.1) — Move/
# Interact/Skills are unreachable from here; only the two recovery paths
# (setback.pay_ransom, waiting via the ordinary Rest handler) plus Save & Quit.
CAPTURED_MENU = """
--- Captured! (day {day}) ---
Ransom: {ransom} gold (you have {gold} gold). Free by day {free_day} regardless.
1) Pay ransom
2) Wait
3) Save & Quit
"""

# SPEC.md §11.1: the demon-king fight is the one TRUE, permanent game-over —
# checked at the top of the main loop, before MENU/CAPTURED_MENU, so a
# resolved fight never falls through to ordinary play again.
GAME_OVER_MESSAGES = {
    "victory": "*** You have slain the Demon King. The invasion ends here. Your story is done. ***",
    "defeat": "*** You have fallen before the Demon King. There is no rising from this one. Your story ends here. ***",
}


def new_game(player_name: str) -> GameState:
    world = new_default_world()
    player = new_player(name=player_name, location_id="village")
    # A fresh character already knows the ground they're standing on.
    knowledge.observe_node(player.beliefs, world.nodes[player.location_id], current_day=0)
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
    # "Bosses as situations, not HP checks" (SPEC.md §6b/§11.1), Chunk B:
    # once sim._reveal_demon_king has tagged this node (the invasion has
    # fully conquered the graph), Interact here means the real fight, not
    # the ordinary wild-foe check below.
    node = state.world.nodes[state.player.location_id]
    if "demon_king" in node.tags:
        _handle_demon_king(state)
        return

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

    result, log = combat.run_combat(state.player, enemy, choose_action, current_day=state.clock.current_day)
    for line in log:
        print(line)
    hint = behavior.derived_role_hint(state.player.behavior)
    summary = narrate_combat_outcome(state.generation, enemy.name, result.value, log, hint)
    if summary:
        print(summary)


def _handle_demon_king(state: GameState) -> None:
    """The real fight (boss.DEMON_KING_ENCOUNTER). Unlike handle_interact's
    ordinary wild-foe branch, a loss here is permanent (SPEC.md §11.1) — the
    epilogue itself is printed by run()'s game_over check next loop, not
    here, so it only ever prints once regardless of how this function
    returns."""
    print(
        "The Demon King awaits at the heart of the fallen realm. This is the real "
        "fight — there is no ransom, no timed escape, if you fall here."
    )
    choice = input("1) Confront the Demon King  2) Leave\n> ").strip()
    if choice != "1":
        return

    def choose_action(
        fighter: combat.Combatant, boss_combatant: combat.Combatant,
        active_adds: list[combat.Combatant], options: list,
    ):
        targets = [boss_combatant, *active_adds]
        print(f"Your HP: {fighter.hp}/{fighter.hp_max} MANA: {fighter.mana}/{fighter.mana_max}")
        warded = " (warded — cannot be harmed yet)" if boss_combatant.immune else ""
        print(f"  {boss_combatant.name} HP: {boss_combatant.hp}/{boss_combatant.hp_max}{warded}")
        for add in active_adds:
            print(f"  {add.name} HP: {add.hp}/{add.hp_max}")
        for i, skill in enumerate(options, start=1):
            print(f"  {i}) {skill.name} (MP {skill.mana_cost})")
        print(f"  {len(options) + 1}) Flee")
        sub_choice = input("> ").strip()
        if sub_choice == str(len(options) + 1):
            return None
        try:
            skill = options[int(sub_choice) - 1]
        except (ValueError, IndexError):
            skill = options[0]  # invalid input defaults to the first (Basic Attack)

        target = targets[0]
        if len(targets) > 1:
            print("Target:")
            for i, candidate in enumerate(targets, start=1):
                print(f"  {i}) {candidate.name}")
            target_choice = input("> ").strip()
            try:
                target = targets[int(target_choice) - 1]
            except (ValueError, IndexError):
                pass  # invalid input defaults to the boss (targets[0])
        return skill, target

    result, log = boss.run_encounter(state.player, boss.DEMON_KING_ENCOUNTER, choose_action)
    for line in log:
        print(line)
    hint = behavior.derived_role_hint(state.player.behavior)
    summary = narrate_combat_outcome(state.generation, boss.DEMON_KING_ENCOUNTER.boss.name, result.value, log, hint)
    if summary:
        print(summary)

    if result is boss.EncounterResult.VICTORY:
        state.player.game_over = "victory"
    elif result is boss.EncounterResult.DEFEAT:
        state.player.game_over = "defeat"
    # FLED: nothing to record — the Demon King remains, cultists and all,
    # for a later attempt (boss.run_encounter never mutates the stored
    # Encounter, so the fight resets to its starting state every attempt).


def handle_inventory(state: GameState) -> None:
    print(resolve(parse("inventory"), state).message)


def handle_rest(state: GameState) -> None:
    print(resolve(parse("rest"), state).message)


def handle_atlas(state: GameState) -> None:
    """Discovered-places view + the fast-travel trigger (SPEC.md §3/§10):
    lists what the player BELIEVES about each known node — last-seen state
    and day, not live world truth — then offers to walk a full route there
    in one time-costed jump."""
    beliefs = state.player.beliefs
    if not beliefs:
        print("You don't know of anywhere yet.")
        return

    entries = sorted(beliefs.items(), key=lambda kv: state.world.nodes[kv[0]].name)
    print("--- Atlas (known places) ---")
    for i, (node_id, belief) in enumerate(entries, start=1):
        name = state.world.nodes[node_id].name
        here = " (here)" if node_id == state.player.location_id else ""
        print(f"  {i}) {name}{here} — as of day {belief.last_seen_day}: {belief.state}")

    choice = input("Fast-travel to which? (number, blank to cancel) ").strip()
    if not choice:
        return
    try:
        index = int(choice)
        destination_id = entries[index - 1][0]
    except (ValueError, IndexError):
        print("Not a valid choice.")
        return

    if destination_id == state.player.location_id:
        print("You're already there.")
        return

    route = state.world.shortest_path(state.player.location_id, destination_id)
    if route is None:
        print("There's no open route there right now.")
        return

    confirm = input(
        f"This will take {route.total_days} day(s) and land you wherever the "
        f"world has moved to by then. Go? (y/N) "
    ).strip().lower()
    if confirm != "y":
        print("Cancelled.")
        return

    print(resolve_fast_travel(state, destination_id).message)


def handle_ask_around(state: GameState) -> None:
    """Pull-primary info gathering (SPEC.md §10): rumors reaching the
    player's CURRENT node, engine-derived from history.LogEntry, never
    AI-invented. Distinct from Atlas: a rumor carries its own confidence
    and may be distorted by distance, whereas Atlas beliefs are only ever
    written by direct physical observation (knowledge.observe_node)."""
    heard = rumors.rumors_reaching(state.world, state.player.location_id, state.clock.current_day)
    if not heard:
        print("No one here has heard anything worth repeating.")
        return
    print("--- Word around here ---")
    hint = behavior.derived_role_hint(state.player.behavior)
    for rumor in heard:
        text = reword_rumor(state.generation, rumor.text, rumor.confidence, hint)
        print(f"  ({rumor.confidence:.0%} sure) {text}")


def handle_quests(state: GameState) -> None:
    """Step 6 Chunk B: the first real player-facing surface for content
    generation's output (SPEC.md §7 — items are "written to a content pool
    the daytime loop pulls from," previously true only in the abstract).
    Deliberately scoped to pull + display + accept ONLY — completion/
    turn-in/reward-granting needs its own design (how does the engine know
    an objective was met?) and is an explicit future step, not this one."""
    accepted = state.player.accepted_quests
    if accepted:
        print("--- Accepted quests ---")
        for quest in accepted:
            print(f"  {quest.get('title', quest['id'])} — reward {quest.get('reward_gold', 0)} gold")
    else:
        print("You haven't accepted any quests yet.")

    item = pool.pull(state, state.world.content_pool)
    if item is None:
        print("No new leads right now.")
        return

    print("--- A new lead ---")
    print(f"  {item.payload.get('title', item.id)}")
    print(f"  {item.payload.get('description', '')}")
    print(f"  Reward: {item.payload.get('reward_gold', 0)} gold")

    choice = input("Accept this quest? (y/N) ").strip().lower()
    if choice == "y":
        # KNOWN SIMPLIFICATION (found in a caveat sweep, not yet fixed):
        # quest._item_from_dict deliberately leaves "id" INSIDE item.payload
        # too (it only strips "manifest"), so {"id": item.id, **item.payload}
        # silently lets item.payload["id"] win over item.id if they were
        # ever to diverge -- Python dict-literal merge order means a later
        # unpacked key always overwrites an earlier literal one of the same
        # name. Currently harmless (both always trace back to the same
        # `data["id"]`), but a latent fragility worth removing (e.g.
        # `{**item.payload, "id": item.id}`, literal last) if this code
        # path is ever touched again.
        state.player.accepted_quests.append({"id": item.id, **item.payload})
        print("Quest accepted.")
    else:
        # Deliberately NOT re-queued (SPEC.md §11: start rough, calibrate
        # by feel) — a declined offer disappearing rather than going back
        # into the pool for a later pull is the simplest behavior for this
        # chunk; revisit if this ever reads as too punishing in play.
        print("You let it go.")


def handle_pay_ransom(state: GameState) -> None:
    for line in setback.pay_ransom(state.player):
        print(line)


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

    # Step 5: GEMINI_API_KEY comes from a real env var, or (as a fallback) a
    # gitignored .env file in the cwd -- see .env.example. Builds a disabled,
    # empty-role registry when neither is set; sim._run_batch then no-ops,
    # exactly like before Step 5 existed. Never fails startup for a missing key.
    registry = LLMRegistry(GenerationConfig.from_env())

    loaded = db.load_game(conn)
    if loaded is not None:
        world, player, clock = loaded
        state = GameState(world=world, player=player, clock=clock, generation=registry)
        print(f"Welcome back, {player.name}. Resuming on day {clock.current_day}.")
    else:
        name = input("Name your character: ").strip() or "Hero"
        state = new_game(name)
        state.generation = registry
        print(f"A new journey begins, {state.player.name}.")

    handlers = {
        "1": handle_move,
        "2": handle_interact,
        "3": handle_inventory,
        "4": handle_rest,
        "5": handle_free_text,
        "6": handle_skills,
        "7": handle_atlas,
        "8": handle_ask_around,
        "9": handle_quests,
    }
    captured_handlers = {
        "1": handle_pay_ransom,
        "2": handle_rest,
    }

    try:
        while True:
            player = state.player
            if player.game_over:
                print(GAME_OVER_MESSAGES.get(player.game_over, "*** Game over. ***"))
                db.save_game(conn, state.world, state.player, state.clock)
                break
            if player.captured:
                print(CAPTURED_MENU.format(
                    day=state.clock.current_day, ransom=player.ransom_cost,
                    gold=player.gold, free_day=player.free_by_day,
                ))
                choice = input("> ").strip()
                if choice == "3":
                    db.save_game(conn, state.world, state.player, state.clock)
                    print("Saved. Farewell.")
                    break
                handler = captured_handlers.get(choice)
                if handler is None:
                    print("Not a valid choice.")
                    continue
                handler(state)
                continue

            node = state.world.nodes[state.player.location_id]
            print(MENU.format(node_name=node.name, day=state.clock.current_day))
            choice = input("> ").strip()

            if choice == "10":
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
