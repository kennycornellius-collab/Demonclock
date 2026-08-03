#!/usr/bin/env python
"""COMBAT-BIASED variant of scripts/playtest.py -- see that file's own
docstring for the shared design (how it drives game.py, AI generation stays
real Gemini, determinism scope, etc.). This copy only changes the bot's
DECISION weights, tuned to reach fights and stay in them:
  - `interact` is heavily favored over other actions, and once at a node
    with a fight available, "Flee"/"Leave" labels are weighted much lower
    than the base script's default (rarely bails mid-fight).
  - `_pick_direction` prefers a neighbor tagged "dangerous" (the seeded
    world's wilds/wild-enemy nodes) when one is known, instead of picking
    uniformly among exits -- the base bot's plain-random movement was why a
    real 60-day run found combat exactly ONCE (see update_progress.md):
    the invasion sealed the only wild-enemy node's access road before the
    unbiased bot wandered back that way.

Usage: same flags as playtest.py, e.g.
    python scripts/playtest_combat.py --days 60
"""
from __future__ import annotations

import argparse
import builtins
import io
import random
import re
import sys
import time
import traceback
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demonclock import db, sim
from demonclock.game import (
    handle_ask_around, handle_atlas, handle_free_text, handle_interact,
    handle_journal, handle_move, handle_pay_ransom, handle_quests, handle_rest,
    handle_skills, new_game,
)
from demonclock.llm.config import GenerationConfig
from demonclock.llm.registry import LLMRegistry
from demonclock.state import GameState


# === Bot decision-making ====================================================

MENU_ITEM_RE = re.compile(r"(\d+)\)\s*")


def _extract_menu_items(combined: str) -> list[tuple[str, str]]:
    markers = list(MENU_ITEM_RE.finditer(combined))
    items = []
    for i, marker in enumerate(markers):
        start = marker.end()
        end = markers[i + 1].start() if i + 1 < len(markers) else len(combined)
        label = combined[start:end].split("\n", 1)[0].strip()
        items.append((marker.group(1), label))
    return items

SKILL_NAMES = [
    "Emberlash", "Frostbite Strike", "Guardian's Ward", "Wolf's Fang",
    "Sunder", "Mender's Touch", "Verdant Coil", "Thunderclap",
]
FREE_TEXT_LINES = [
    "I look around carefully for anything unusual.",
    "I ask around about the invasion.",
    "I sharpen my blade and prepare for trouble.",
    "I check my pockets for spare coin.",
    "I try to strike up a conversation with a passerby.",
    "I study the road ahead before setting out.",
]
DETERMINISTIC_VERBS = ["look", "inventory", "rest", "help"]
DECLARED_INTENTS = [
    None, None,
    "a wandering merchant", "a knight in service to no one",
    "the greatest chef in the land", "a scholar of old ruins",
]
CHARACTER_NAMES = ["Corin", "Mira", "Tobias", "Sable", "Ezra", "Wren", "Halric", "Yara"]


def _weight_for_label(label: str) -> float:
    lowered = label.lower()
    if label.startswith("Attack "):
        return 0.08  # killing an NPC is still permanent -- rare even here
    if label == "Fight" or lowered.startswith("fight"):
        return 2.5
    if any(k in lowered for k in ("leave", "cancel", "back", "flee", "something else")):
        return 0.10  # combat bias: rarely bail out of a fight or a wild encounter
    return 1.0


class Bot:
    def __init__(self, state: GameState, rng, logf) -> None:
        self.state = state
        self.rng = rng
        self.logf = logf
        self.stdout_target = io.StringIO()
        self._last_stdout_pos = 0
        self.input_log: list[tuple[str, str]] = []

    def begin_turn(self) -> None:
        self.stdout_target = io.StringIO()
        self._last_stdout_pos = 0
        self.input_log = []

    def fake_input(self, prompt: str = "") -> str:
        since = self.stdout_target.getvalue()[self._last_stdout_pos:]
        self._last_stdout_pos = self.stdout_target.tell()
        response = self._decide_response(prompt, since + prompt)
        self.input_log.append((prompt, response))
        return response

    def _pick_menu(self, combined: str) -> str | None:
        choices = _extract_menu_items(combined)
        if not choices:
            return None
        weights = [_weight_for_label(label) for _, label in choices]
        return self.rng.choices([n for n, _ in choices], weights=weights, k=1)[0]

    def _pick_direction(self) -> str:
        links = self.state.world.links_from(self.state.player.location_id)
        if not links or self.rng.random() < 0.10:
            return ""
        if self.rng.random() < 0.08:
            return self.rng.choice(["up", "down", "sideways", "nowhere"])  # exercise the honest-rejection path
        # Combat bias: head for a "dangerous"-tagged neighbor (wild-enemy
        # territory) when one is reachable, instead of picking uniformly --
        # this is the bot metagaming with full world truth on purpose, since
        # the point here is to reliably reach fights, not simulate fog of war.
        dangerous = [link for link in links if "dangerous" in self.state.world.nodes[link.to_id].tags]
        if dangerous and self.rng.random() < 0.70:
            return self.rng.choice(dangerous).direction
        return self.rng.choice(links).direction

    def _decide_response(self, prompt: str, combined: str) -> str:
        p = prompt.lower()
        if "which direction" in p:
            return self._pick_direction()
        if "quantity:" in p:
            return "" if self.rng.random() < 0.25 else str(self.rng.randint(1, 6))
        if "name your skill" in p:
            return "" if self.rng.random() < 0.30 else self.rng.choice(SKILL_NAMES)
        if "base power" in p:
            return str(self.rng.randint(0, 80))
        if "attribute multiplier" in p:
            return self.rng.choice(["0.5", "1.0", "1.2", "1.5", "2.0"])
        if "accept this cost" in p:
            return "y" if self.rng.random() < 0.85 else "n"
        if "add effect #" in p:
            match = re.search(r"\((\d+) chosen so far", prompt)
            count = int(match.group(1)) if match else 0
            finish_chance = {0: 0.0, 1: 0.35, 2: 0.60}.get(count, 0.95)
            if self.rng.random() < finish_chance:
                return ""
            return self._pick_menu(combined) or ""
        if "what do you say" in p:
            return self.rng.choice(FREE_TEXT_LINES)
        if "what do you do" in p:
            return self.rng.choice(FREE_TEXT_LINES + DETERMINISTIC_VERBS)
        if "(y/n)" in p:
            return "y" if self.rng.random() < 0.75 else "n"

        choice = self._pick_menu(combined)
        if choice is None:
            return ""
        r = self.rng.random()
        if r < 0.05:
            return "0"  # deliberately invalid -- exercises _select's bounds check
        if r < 0.12:
            return ""  # deliberately cancels -- exercises the "blank to cancel" path
        return choice


# === The turn loop ==========================================================
# Combat-biased weights: interact (the gateway to Fight) dominates; movement
# stays present enough to actually reach a dangerous node; economy/social
# actions are deliberately rare here (that's what the other two variants are for).

ACTIONS = [
    ("move", 2.5, handle_move),
    ("rest", 1.0, handle_rest),
    ("interact", 7.0, handle_interact),
    ("atlas", 1.0, handle_atlas),
    ("ask_around", 0.3, handle_ask_around),
    ("quests", 0.5, handle_quests),
    ("skills", 1.5, handle_skills),
    ("journal", 0.2, handle_journal),
    ("free_text", 0.3, handle_free_text),
]

RELOAD_CHECK_INTERVAL_DAYS = 15


def _weighted_action(rng):
    names = [name for name, _, _ in ACTIONS]
    weights = [w for _, w, _ in ACTIONS]
    fns = {name: fn for name, _, fn in ACTIONS}
    name = rng.choices(names, weights=weights, k=1)[0]
    return name, fns[name]


def _log(logf, message: str) -> None:
    logf.write(message + "\n")
    logf.flush()


def _player_snapshot(state: GameState) -> str:
    p = state.player
    return (
        f"day={state.clock.current_day} loc={p.location_id} hp={p.hp}/{p.hp_max} "
        f"mana={p.mana}/{p.mana_max} gold={p.gold} captured={p.captured} "
        f"skills={len(p.skills)} quests={len(p.accepted_quests)} game_over={p.game_over}"
    )


def run_playtest(args) -> None:
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    save_path = Path(args.save)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    seed = args.seed if args.seed is not None else int(time.time() * 1000) % (2**31)
    rng = random.Random(seed)

    gen_config = GenerationConfig(roles={}, api_keys={}) if args.no_ai else GenerationConfig.from_env()
    registry = LLMRegistry(gen_config)

    conn = db.connect(str(save_path))
    db.init_schema(conn)

    with open(log_path, "w", encoding="utf-8") as logf:
        ai_mode = "off (--no-ai)" if args.no_ai else ("gemini (real, via .env)" if registry.enabled else "gemini (UNCONFIGURED -- no GEMINI_API_KEY found, generation will no-op)")
        _log(logf, f"=== Demonclock automated playtest [COMBAT-BIASED] === {datetime.now(timezone.utc).isoformat()}")
        _log(logf, f"seed={seed} days_target={args.days} ai_mode={ai_mode}")
        _log(logf, f"save_path={save_path} load_path={args.load or '(new game)'}")
        _log(logf, "")

        loaded = db.load_game(conn) if args.load else None
        if loaded is not None:
            world, player, clock = loaded
            state = GameState(world=world, player=player, clock=clock, generation=registry)
            _log(logf, f"Loaded existing save. {_player_snapshot(state)}")
        else:
            name = rng.choice(CHARACTER_NAMES)
            declared_intent = rng.choice(DECLARED_INTENTS)
            state = new_game(name, declared_intent)
            state.generation = registry
            _log(logf, f"New game: name={name!r} declared_intent={declared_intent!r}")
            sim.run_warm_start_batch(state)
            _log(logf, f"Warm-start batch complete. Pool size={len(state.world.content_pool)}")
        _log(logf, "")

        bot = Bot(state, rng, logf)
        real_input = builtins.input
        builtins.input = bot.fake_input

        turn = 0
        consecutive_errors = 0
        exceptions: list[tuple[int, int, str, str]] = []
        action_counts: dict[str, int] = {}
        last_reload_check_day = -1
        max_actions = max(500, args.days * 25)

        try:
            while state.clock.current_day < args.days and not state.player.game_over:
                if turn >= max_actions:
                    _log(logf, f"\n*** Hit max-action safety cap ({max_actions}) before reaching day {args.days}. Stopping. ***")
                    break

                turn += 1
                if state.player.captured:
                    action_name = "pay_ransom" if rng.random() < 0.4 else "wait"
                    fn = handle_pay_ransom if action_name == "pay_ransom" else handle_rest
                else:
                    action_name, fn = _weighted_action(rng)
                action_counts[action_name] = action_counts.get(action_name, 0) + 1

                bot.begin_turn()
                header = f"--- Turn {turn} | action={action_name} | {_player_snapshot(state)} ---"
                try:
                    with redirect_stdout(bot.stdout_target):
                        fn(state)
                except Exception:
                    tb = traceback.format_exc()
                    exceptions.append((turn, state.clock.current_day, action_name, tb))
                    consecutive_errors += 1
                    _log(logf, header)
                    _log(logf, bot.stdout_target.getvalue())
                    for prompt, response in bot.input_log:
                        _log(logf, f"    INPUT[{prompt!r}] -> {response!r}")
                    _log(logf, f"!!! EXCEPTION !!!\n{tb}")
                    if consecutive_errors >= 5:
                        _log(logf, "\n*** 5 consecutive exceptions -- something is fundamentally broken. Aborting run. ***")
                        break
                else:
                    consecutive_errors = 0
                    _log(logf, header)
                    output = bot.stdout_target.getvalue()
                    if output.strip():
                        _log(logf, output.rstrip())
                    for prompt, response in bot.input_log:
                        _log(logf, f"    INPUT[{prompt!r}] -> {response!r}")
                _log(logf, "")

                day = state.clock.current_day
                if day // RELOAD_CHECK_INTERVAL_DAYS > last_reload_check_day // RELOAD_CHECK_INTERVAL_DAYS and day > 0:
                    last_reload_check_day = day
                    _reload_sanity_check(logf, conn, state)

        finally:
            builtins.input = real_input
            db.save_game(conn, state.world, state.player, state.clock)
            _write_summary(logf, state, seed, turn, action_counts, exceptions, registry, args)
            conn.close()

    print(f"Playtest complete. Log written to {log_path}")


def _reload_sanity_check(logf, conn, state: GameState) -> None:
    db.save_game(conn, state.world, state.player, state.clock)
    reloaded = db.load_game(conn)
    if reloaded is None:
        _log(logf, f"*** RELOAD CHECK FAILED at day {state.clock.current_day}: load_game returned None after a save. ***\n")
        return
    r_world, r_player, r_clock = reloaded
    mismatches = []
    if r_player.gold != state.player.gold:
        mismatches.append(f"gold {r_player.gold} != {state.player.gold}")
    if r_clock.current_day != state.clock.current_day:
        mismatches.append(f"day {r_clock.current_day} != {state.clock.current_day}")
    if r_player.location_id != state.player.location_id:
        mismatches.append(f"location {r_player.location_id!r} != {state.player.location_id!r}")
    if len(r_player.accepted_quests) != len(state.player.accepted_quests):
        mismatches.append(f"accepted_quests count {len(r_player.accepted_quests)} != {len(state.player.accepted_quests)}")
    if len(r_player.skills) != len(state.player.skills):
        mismatches.append(f"skills count {len(r_player.skills)} != {len(state.player.skills)}")
    if mismatches:
        _log(logf, f"*** RELOAD CHECK MISMATCH at day {state.clock.current_day}: {'; '.join(mismatches)} ***\n")
    else:
        _log(logf, f"[reload check OK at day {state.clock.current_day}]\n")


def _write_summary(logf, state, seed, turn, action_counts, exceptions, registry, args) -> None:
    p = state.player
    w = state.world
    occupied = sum(1 for n in w.nodes.values() if n.state == "occupied")
    _log(logf, "\n" + "=" * 70)
    _log(logf, "SUMMARY")
    _log(logf, "=" * 70)
    _log(logf, f"seed={seed}  turns_run={turn}  final_day={state.clock.current_day}/{args.days}")
    _log(logf, f"action counts: {action_counts}")
    _log(logf, "")
    _log(logf, f"Player: {p.name} ({p.declared_intent or 'no declared intent'})")
    _log(logf, f"  HP {p.hp}/{p.hp_max}  MANA {p.mana}/{p.mana_max}  gold {p.gold}")
    _log(logf, f"  location={p.location_id}  captured={p.captured}  game_over={p.game_over}")
    _log(logf, f"  skills learned: {[s.name for s in p.skills]}")
    _log(logf, f"  creative_mode_used={p.creative_mode_used}")
    _log(logf, f"  accepted_quests={len(p.accepted_quests)}  journal_entries={len(p.journal)}")
    _log(logf, f"  faction_standing={p.faction_standing}")
    _log(logf, "")
    _log(logf, f"World: {len(w.nodes)} nodes, {occupied} occupied, content_pool={len(w.content_pool)}, "
                f"event_log={len(w.event_log)}, npcs={len(w.npcs)}")
    _log(logf, "")
    _log(logf, f"AI: {'enabled (real Gemini)' if registry.enabled else 'disabled/unconfigured'}")
    _log(logf, "")
    _log(logf, f"Exceptions caught: {len(exceptions)}")
    if exceptions:
        seen = {}
        for turn_no, day, action, tb in exceptions:
            last_line = tb.strip().splitlines()[-1]
            seen.setdefault(last_line, []).append((turn_no, day, action))
        for err, occurrences in seen.items():
            _log(logf, f"  - {err}  (turns: {occurrences})")
        _log(logf, "VERDICT: FAIL -- see exception tracebacks above.")
    else:
        _log(logf, "VERDICT: PASS -- no uncaught exceptions during the run.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=60, help="simulate until the in-game clock reaches this day (default: 60)")
    parser.add_argument("--seed", type=int, default=None, help="seed for the bot's own decisions (default: random, always logged)")
    parser.add_argument("--save", default="scripts/playtest_output/combat.save.sqlite", help="save file path")
    parser.add_argument("--load", default=None, help="load an existing save from this path instead of starting a new game")
    parser.add_argument("--log", default=None, help="log file path (default: timestamped under scripts/playtest_output/)")
    parser.add_argument("--no-ai", action="store_true", help="disable AI generation entirely (fast, free, offline smoke test)")
    args = parser.parse_args()

    if args.log is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.log = f"scripts/playtest_output/combat_{timestamp}.log.txt"

    run_playtest(args)


if __name__ == "__main__":
    main()
