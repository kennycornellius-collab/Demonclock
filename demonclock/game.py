"""Menu-driven REPL (SPEC.md §6): Move / Interact / Inventory / Rest /
Something else... The free-text box is the only place the parser runs.

Step 12 Chunk C: `handle_free_text` is now the real dispatcher the free-text
box always promised -- deterministic parse first (parser.py, unchanged
zero-AI behavior), and only on UNRECOGNIZED does it build "what's actually
available right now" and try the AI fallback (generation/free_text.py) for
one of the 13 ActionTypes, before routing to whichever existing handler
(actions.resolve for the simple 5, or one of this module's own interactive
functions for the rest) already implements it -- no new interactive logic,
just a new entry point into what already exists.
"""
from __future__ import annotations

from typing import Callable

from . import behavior, boss, combat, crafting, db, knowledge, pool, quests, rumors, setback, skills, trade
from .actions import resolve, resolve_fast_travel
from .clock import Clock
from .enemies import make_enemy
from .generation.dialogue import run_dialogue_opening, run_dialogue_reply
from .generation.free_text import run_free_text_fallback
from .generation.narrator import narrate_combat_outcome, reword_rumor
from .llm.config import GenerationConfig
from .llm.registry import LLMRegistry
from .models import NPC
from .parser import Action, ActionType, parse
from .player import display_name, new_player
from .resolve import resolve_entity
from .seed import WILD_ENEMY_BY_NODE, new_default_world
from .state import GameState

# Always reachable via free text regardless of the player's current node --
# the top-level menu items with no location gating. Fight/Trade/Talk/Craft
# are node-gated (see _available_context_actions) and NOT included here.
_ALWAYS_AVAILABLE_ACTIONS = frozenset({
    ActionType.MOVE, ActionType.LOOK, ActionType.INVENTORY, ActionType.REST, ActionType.HELP,
    ActionType.SKILLS, ActionType.ATLAS, ActionType.QUESTS, ActionType.ASK_AROUND,
})

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

# Step 8 P5: caps how many rumors "Ask Around" prints — rumors.rumors_reaching
# already sorts nearest (most confident) first, so this just shows the most
# relevant handful instead of an unbounded dump of everything reachable.
MAX_RUMORS_SHOWN = 5


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


def _available_context_actions(state: GameState, node) -> set[ActionType]:
    """The context-gated actions (Fight/Trade/Talk/Craft) actually usable at
    `node` right now -- the single source of truth `handle_interact`'s own
    option-building AND the free-text dispatcher's availability check
    (Step 12 Chunk C) both read, so the two can never drift out of sync.
    Mirrors `handle_interact`'s own "demon_king short-circuits everything
    else" rule (SPEC.md §6b/§11.1)."""
    if "demon_king" in node.tags:
        return {ActionType.FIGHT}
    available: set[ActionType] = set()
    if node.prices:
        available.add(ActionType.TRADE)
    if WILD_ENEMY_BY_NODE.get(node.id):
        available.add(ActionType.FIGHT)
    if state.world.npcs_at(node.id):
        available.add(ActionType.TALK)
    if "workshop" in node.tags:
        available.add(ActionType.CRAFT)
    return available


def handle_interact(state: GameState) -> None:
    # "Bosses as situations, not HP checks" (SPEC.md §6b/§11.1), Chunk B:
    # once sim._reveal_demon_king has tagged this node (the invasion has
    # fully conquered the graph), Interact here means the real fight, not
    # any of the ordinary options below.
    node = state.world.nodes[state.player.location_id]
    if "demon_king" in node.tags:
        _handle_demon_king(state)
        return

    # Builds whatever's actually available at this node -- Trade (Step 10
    # Stage 1, any node with tracked Node.prices), Fight (a recurring wild
    # foe, see seed.WILD_ENEMY_BY_NODE), Talk (Step 10 Stage 3, one entry
    # per NPC standing here), Craft (Step 10 Stage 5, any "workshop"-tagged
    # node). A node offering exactly one thing runs it directly with no
    # menu detour (same behavior every node had before Trade/Talk/Craft
    # existed); a node offering more than one shows a picker.
    available = _available_context_actions(state, node)
    options: list[tuple[str, Callable[[], None]]] = []
    if ActionType.TRADE in available:
        options.append(("Trade", lambda: _handle_trade(state, node)))
    if ActionType.FIGHT in available:
        enemy_ids = WILD_ENEMY_BY_NODE[state.player.location_id]
        options.append(("Fight", lambda: _handle_fight(state, enemy_ids)))
    for npc in state.world.npcs_at(node.id):
        options.append((f"Talk to {npc.name}", lambda npc=npc: _handle_talk(state, npc)))
    if ActionType.CRAFT in available:
        options.append(("Craft", lambda: _handle_craft(state, node)))

    if not options:
        print("There is no one here to talk to yet.")
        return

    if len(options) == 1:
        options[0][1]()
        return

    for i, (label, _) in enumerate(options, start=1):
        print(f"  {i}) {label}")
    print(f"  {len(options) + 1}) Leave")
    choice = input("> ").strip()
    try:
        index = int(choice) - 1
    except ValueError:
        return
    if 0 <= index < len(options):
        options[index][1]()


def _handle_trade(state: GameState, node) -> None:
    """Step 10 Stage 1 (SPEC.md §6/§12): buy/sell against `node.prices`.
    Single price both directions -- see trade.py's own docstring for why
    (profit is geographic, via economy.py's threat multiplier, not an
    in-node spread)."""
    print(f"--- Trading at {node.name} ---")
    goods = list(node.prices.items())
    for i, (good_id, price) in enumerate(goods, start=1):
        owned = next(
            (item.quantity for item in state.player.inventory if item.item_id == good_id), 0
        )
        print(f"  {i}) {display_name(good_id)} — {price} gold each (you have {owned})")

    choice = input(f"Gold: {state.player.gold}\n1) Buy  2) Sell  3) Leave\n> ").strip()
    if choice not in ("1", "2"):
        return

    good_choice = input("Which good? (number) ").strip()
    selected = _select(goods, good_choice)
    if selected is None:
        print("Not a valid choice.")
        return
    good_id = selected[0]

    quantity = _prompt_int("Quantity: ", default=1)
    log = trade.buy(state, node.id, good_id, quantity) if choice == "1" else trade.sell(
        state, node.id, good_id, quantity
    )
    for line in log:
        print(line)


def _handle_talk(state: GameState, npc: NPC) -> None:
    """Step 10 Stage 3 (SPEC.md §6/§7): a live, one-call-per-conversation
    dialogue exchange — see generation/dialogue.py for why this is never
    batch-generated/pooled like Story/Quest/Places/Flavor. Every path here
    (a generated option or free text) is pure flavor, a deliberate v1 scope
    call — nothing said here can grant a quest, change gold/items, or shift
    standing."""
    print(f"--- {npc.name} ---")
    if npc.description:
        print(npc.description)

    hint = behavior.derived_role_hint(state.player.behavior)
    opening = run_dialogue_opening(state.generation, npc, hint)
    behavior.record_dialogue_action(state.player.behavior)

    if opening is None:
        print(f"{npc.name} nods at you but doesn't have much to say right now.")
        return

    print(opening.greeting)
    for i, option in enumerate(opening.options, start=1):
        print(f"  {i}) {option.label}")
    something_else = len(opening.options) + 1
    print(f"  {something_else}) Something else...")
    print(f"  {something_else + 1}) Leave")
    choice = input("> ").strip()
    try:
        index = int(choice) - 1
    except ValueError:
        return

    if 0 <= index < len(opening.options):
        print(opening.options[index].response)
        return
    if index == something_else - 1:
        message = input("What do you say? ").strip()
        if not message:
            return
        reply = run_dialogue_reply(state.generation, npc, message, hint)
        print(reply if reply else f"{npc.name} just shrugs.")


def _handle_craft(state: GameState, node) -> None:
    """Step 10 Stage 5 (SPEC.md §6/§12): craft from crafting.RECIPES's fixed
    hand-authored table at a "workshop"-tagged node."""
    print(f"--- Crafting at {node.name} ---")
    recipes = list(crafting.RECIPES.values())
    for i, recipe in enumerate(recipes, start=1):
        inputs_desc = ", ".join(
            f"{amount} {display_name(item_id)}" for item_id, amount in recipe.inputs.items()
        )
        print(f"  {i}) {recipe.name} — needs {inputs_desc} -> {recipe.output_quantity} {recipe.output_name}")

    choice = input(f"{len(recipes) + 1}) Leave\n> ").strip()
    recipe = _select(recipes, choice)
    if recipe is None:
        return

    for line in crafting.craft(state, recipe.id):
        print(line)


def _handle_fight(state: GameState, enemy_ids: list[str]) -> None:
    """Step 10 Stage 6: reuses combat.run_group_combat's multi-combatant
    turn-order/targeting (the same shape boss.py's _handle_demon_king
    already established) instead of a second implementation — target
    selection only prompts when more than one enemy is still alive."""
    enemies = [make_enemy(enemy_id) for enemy_id in enemy_ids]
    if len(enemies) == 1:
        print(f"A {enemies[0].name} blocks your path! (HP {enemies[0].hp}/{enemies[0].hp_max})")
    else:
        print(f"{', '.join(e.name for e in enemies)} block your path!")
    choice = input("1) Fight  2) Leave\n> ").strip()
    if choice != "1":
        return

    def choose_action(
        fighter: combat.Combatant, alive_enemies: list[combat.Combatant], options: list
    ):
        print(f"Your HP: {fighter.hp}/{fighter.hp_max} MANA: {fighter.mana}/{fighter.mana_max}")
        for foe in alive_enemies:
            print(f"  {foe.name} HP: {foe.hp}/{foe.hp_max}")
        for i, skill in enumerate(options, start=1):
            print(f"  {i}) {skill.name} (MP {skill.mana_cost})")
        print(f"  {len(options) + 1}) Flee")
        while True:
            sub_choice = input("> ").strip()
            if sub_choice == str(len(options) + 1):
                return None
            skill = _select(options, sub_choice)
            if skill is not None:
                break
            print("Not a valid choice.")

        target = alive_enemies[0]
        if len(alive_enemies) > 1:
            print("Target:")
            for i, candidate in enumerate(alive_enemies, start=1):
                print(f"  {i}) {candidate.name}")
            while True:
                target_choice = input("> ").strip()
                target = _select(alive_enemies, target_choice)
                if target is not None:
                    break
                print("Not a valid choice.")
        return skill, target

    result, log = combat.run_group_combat(state.player, enemies, choose_action, current_day=state.clock.current_day)
    for line in log:
        print(line)
    hint = behavior.derived_role_hint(state.player.behavior)
    opponent_desc = enemies[0].name if len(enemies) == 1 else ", ".join(e.name for e in enemies)
    summary = narrate_combat_outcome(state.generation, opponent_desc, result.value, log, hint)
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
        while True:
            sub_choice = input("> ").strip()
            if sub_choice == str(len(options) + 1):
                return None
            skill = _select(options, sub_choice)
            if skill is not None:
                break
            print("Not a valid choice.")

        target = targets[0]
        if len(targets) > 1:
            print("Target:")
            for i, candidate in enumerate(targets, start=1):
                print(f"  {i}) {candidate.name}")
            while True:
                target_choice = input("> ").strip()
                target = _select(targets, target_choice)
                if target is not None:
                    break
                print("Not a valid choice.")
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
    selected = _select(entries, choice)
    if selected is None:
        print("Not a valid choice.")
        return
    destination_id = selected[0]

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
    written by direct physical observation (knowledge.observe_node). Shows
    at most MAX_RUMORS_SHOWN (Step 8 P5) — rumors.rumors_reaching already
    sorts nearest/most-confident first, so this caps display, not relevance."""
    heard = rumors.rumors_reaching(state.world, state.player.location_id, state.clock.current_day)
    if not heard:
        print("No one here has heard anything worth repeating.")
        return
    print("--- Word around here ---")
    hint = behavior.derived_role_hint(state.player.behavior)
    for rumor in heard[:MAX_RUMORS_SHOWN]:
        text = reword_rumor(state.generation, rumor.text, rumor.confidence, hint)
        print(f"  ({rumor.confidence:.0%} sure) {text}")


def handle_quests(state: GameState) -> None:
    """Step 6 Chunk B: the first real player-facing surface for content
    generation's output (SPEC.md §7 — items are "written to a content pool
    the daytime loop pulls from," previously true only in the abstract).
    Step 10 Stage 2 adds turn-in: check each accepted quest's own
    `completion` manifest (quests.check_completion) against LIVE state and
    let the player collect the reward once it holds — no physical-location
    requirement, since no NPC exists yet to turn a quest in to."""
    accepted = state.player.accepted_quests
    if accepted:
        print("--- Accepted quests ---")
        for i, quest in enumerate(accepted, start=1):
            done = "done!" if quests.check_completion(state, quest).passed else "in progress"
            print(f"  {i}) {quest.get('title', quest['id'])} — reward {quest.get('reward_gold', 0)} gold ({done})")

        choice = input("Turn in which quest? (number, blank to skip) ").strip()
        if choice:
            target = _select(accepted, choice)
            if target is None:
                print("Not a valid choice.")
            else:
                for line in quests.turn_in(state, target):
                    print(line)
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
        # item.id is the authoritative id; literal last so it always wins
        # over item.payload["id"] (quest._item_from_dict leaves "id" inside
        # the payload too, only "manifest" is stripped).
        state.player.accepted_quests.append({**item.payload, "id": item.id})
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
    selected = _select(options, raw)
    if selected is None:
        print(f"Not a valid choice, defaulting to {options[0].value}.")
        return options[0]
    return selected


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
        kind = _select(kinds, raw)
        if kind is None:
            print("Not a valid choice.")
            continue
        stat = None
        if kind in (skills.EffectKind.BUFF, skills.EffectKind.DEBUFF):
            stat = _choose_stat(f"Which stat does {kind.value} target?")
        chosen.append(skills.Effect(kind, stat=stat))


def _select(items: list, choice: str):
    """Resolves a 1-based menu `choice` string to the selected item, or
    `None` if `choice` isn't a valid selection. Centralizes the fix for a
    long-standing bug: Python allows negative list indices, so a bare
    `items[int(choice) - 1]` silently resolves "0" to the LAST item instead
    of correctly rejecting it as invalid -- every numbered-menu site in this
    module now goes through this one bounds-checked helper instead of
    repeating the same off-by-one-prone indexing."""
    try:
        index = int(choice) - 1
    except ValueError:
        return None
    return items[index] if 0 <= index < len(items) else None


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

    action = parse(text)
    if action.type is ActionType.UNRECOGNIZED:
        fallback = _fallback_parse(state, text)
        if fallback is not None:
            action = fallback

    _dispatch_action(state, action)


def _fallback_parse(state: GameState, text: str) -> Action | None:
    """Only reached once parser.py's own deterministic VERB_TABLE has
    already failed to match `text`'s first word (parser.py itself stays
    100% deterministic/AI-free). Builds "what's actually available right
    now" -- the always-available top-level actions plus whatever Fight/
    Trade/Talk/Craft this specific node currently offers -- and asks the
    AI fallback (generation/free_text.py) which of those the sentence most
    likely means. Returns None (never a placeholder) whenever unconfigured,
    the call fails, or the model can't confidently place it -- the caller
    then falls back to parser.py's own honest UNRECOGNIZED message, exactly
    as if this fallback had never been attempted."""
    node = state.world.nodes[state.player.location_id]
    available = _ALWAYS_AVAILABLE_ACTIONS | _available_context_actions(state, node)
    parsed = run_free_text_fallback(state.generation, text, list(available))
    if parsed is None:
        return None
    return Action(parsed.action, target=parsed.target, raw_text=text)


def _dispatch_action(state: GameState, action: Action) -> None:
    """Routes a resolved Action (from either parser.parse or the AI
    fallback) to whatever already implements it -- actions.resolve for the
    original 5 (Move/Look/Inventory/Rest/Help), or one of this module's own
    interactive handlers for the rest (Step 12 Chunk C: these previously
    ONLY existed behind game.py's menus). No new interactive logic here --
    free text is just a new entry point into what already exists."""
    if action.type in (ActionType.MOVE, ActionType.LOOK, ActionType.INVENTORY, ActionType.REST, ActionType.HELP):
        print(resolve(action, state).message)
        return
    if action.type is ActionType.SKILLS:
        handle_skills(state)
        return
    if action.type is ActionType.ATLAS:
        handle_atlas(state)
        return
    if action.type is ActionType.QUESTS:
        handle_quests(state)
        return
    if action.type is ActionType.ASK_AROUND:
        handle_ask_around(state)
        return

    node = state.world.nodes[state.player.location_id]

    if action.type is ActionType.FIGHT:
        if "demon_king" in node.tags:
            _handle_demon_king(state)
            return
        enemy_ids = WILD_ENEMY_BY_NODE.get(state.player.location_id)
        if not enemy_ids:
            print("There's nothing to fight here.")
            return
        _handle_fight(state, enemy_ids)
        return

    if action.type is ActionType.TRADE:
        if not node.prices:
            print("There's no trading to be done here.")
            return
        _handle_trade(state, node)
        return

    if action.type is ActionType.CRAFT:
        if "workshop" not in node.tags:
            print("There's nowhere to craft here.")
            return
        _handle_craft(state, node)
        return

    if action.type is ActionType.TALK:
        npcs = state.world.npcs_at(node.id)
        if not npcs:
            print("There's no one here to talk to.")
            return
        npc = _resolve_talk_target(state, npcs, action.target)
        if npc is not None:
            _handle_talk(state, npc)
        return

    print(action.message or "I don't understand that.")


def _resolve_talk_target(state: GameState, npcs: list[NPC], target: str | None) -> NPC | None:
    """Resolves TALK's optional target phrase (e.g. "hana" from "talk to
    hana") to a specific NPC among those actually present. A single NPC
    present with no target given is talked to directly (matches
    handle_interact's own "one option, no menu detour" behavior). A given
    target is resolved via resolve.py's resolve_entity against the
    present NPCs' own (id, name) pairs -- the same entity-resolution
    machinery Step 4 Chunk D already built, not a second implementation.
    Multiple NPCs present with no target given prompts for a pick."""
    if len(npcs) == 1 and not target:
        return npcs[0]

    if target:
        shortlist = [(npc.id, npc.name) for npc in npcs]
        resolved_id = resolve_entity(target, shortlist, state.generation)
        if resolved_id is not None:
            return next(npc for npc in npcs if npc.id == resolved_id)
        print(f"Not sure who {target!r} refers to here.")
        return None

    print("Talk to whom?")
    for i, npc in enumerate(npcs, start=1):
        print(f"  {i}) {npc.name}")
    choice = input("> ").strip()
    selected = _select(npcs, choice)
    if selected is None:
        print("Not a valid choice.")
    return selected


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
