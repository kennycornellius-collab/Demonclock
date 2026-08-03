#!/usr/bin/env python
"""Automated playtest bot: drives a real GameState through the real game.py
handler functions (the same code a human player's menu choices call), with
randomized decisions standing in for a human, and writes a full turn-by-turn
transcript to a log file. This is integration-level coverage the pytest
suite deliberately doesn't do -- every existing test exercises one module in
isolation; nothing plays a whole session end to end (Move/Rest/Trade/Fight/
Craft/Talk/Quests/Skills/Atlas/free-text, all together, with the generation
pipeline actually firing).

How it drives the game: it never touches the top-level menu dispatch in
game.run() (that's a 10-line dict lookup already covered by
tests/test_game.py). Instead each "turn" calls one game.handle_*() function
directly -- the equivalent of a player already having pressed a menu number
-- with `input()` monkeypatched to a decision function that inspects the
text just printed (and the prompt itself) to figure out what menu is being
shown, then picks a weighted-random valid choice (occasionally an invalid
one on purpose, to exercise the bounds-checking/reprompt paths). All
captured stdout plus every input()/response pair is written to the log.

AI generation: unchanged from real play -- GenerationConfig.from_env() picks
up the real GEMINI_API_KEY from .env, exactly like game.run() does, so a run
of this script shows up as real traffic in AI Studio. The "player" (which
menu number gets picked each turn) is a separate concern from "what
generates game content" -- only the player is randomized/bot-driven here;
generation is the same production Gemini path, untouched. (A real LLM
making the PLAYER's per-turn decisions, instead of the weighted-random Bot
below, is a plausible future mode -- deliberately not built until actually
needed, to avoid the extra complexity/cost of an LLM call per menu prompt.)

Determinism note: --seed reproduces the BOT's own decisions (which action,
which menu number, which free-text line) but NOT combat RNG or real AI
output -- game.py's own combat handlers construct their own fresh
random.Random() internally (by design, see combat.py), and this script
doesn't reach in to change that.

Usage:
    python scripts/playtest.py --days 60
    python scripts/playtest.py --days 20 --no-ai          # fast, free, offline smoke test
    python scripts/playtest.py --load scripts/playtest_output/playtest.save.sqlite --days 120

Real Gemini calls cost nothing on the free tier but ARE rate-limited (see
llm/config.py's DEFAULT_GEMINI_MODEL_CHAIN comments) -- demonclock's own
per-role provider fallback chain and per-batch graceful degradation already
handle that; this script adds no extra throttling of its own on top.
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

MENU_LINE_RE = re.compile(r"^\s*(\d+)\)\s*(.*)$", re.MULTILINE)

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
        return 0.08  # killing an NPC is permanent -- rare, not the bot's default move
    if any(k in lowered for k in ("leave", "cancel", "back", "flee", "something else")):
        return 0.35  # don't let the bot just bail on everything by default
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
        choices = MENU_LINE_RE.findall(combined)
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

ACTIONS = [
    ("move", 3.0, handle_move),
    ("rest", 3.0, handle_rest),
    ("interact", 4.0, handle_interact),
    ("atlas", 1.5, handle_atlas),
    ("ask_around", 1.5, handle_ask_around),
    ("quests", 2.5, handle_quests),
    ("skills", 0.8, handle_skills),
    ("journal", 0.5, handle_journal),
    ("free_text", 1.2, handle_free_text),
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

    # Exactly game.run()'s own setup: a real GEMINI_API_KEY (env var or
    # .env) is picked up here the same way, and a missing key just leaves
    # generation disabled, same as an unconfigured real game.
    gen_config = GenerationConfig(roles={}, api_keys={}) if args.no_ai else GenerationConfig.from_env()
    registry = LLMRegistry(gen_config)

    conn = db.connect(str(save_path))
    db.init_schema(conn)

    with open(log_path, "w", encoding="utf-8") as logf:
        ai_mode = "off (--no-ai)" if args.no_ai else ("gemini (real, via .env)" if registry.enabled else "gemini (UNCONFIGURED -- no GEMINI_API_KEY found, generation will no-op)")
        _log(logf, f"=== Demonclock automated playtest === {datetime.now(timezone.utc).isoformat()}")
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
    parser.add_argument("--save", default="scripts/playtest_output/playtest.save.sqlite", help="save file path")
    parser.add_argument("--load", default=None, help="load an existing save from this path instead of starting a new game")
    parser.add_argument("--log", default=None, help="log file path (default: timestamped under scripts/playtest_output/)")
    parser.add_argument("--no-ai", action="store_true", help="disable AI generation entirely (fast, free, offline smoke test)")
    args = parser.parse_args()

    if args.log is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        args.log = f"scripts/playtest_output/playtest_{timestamp}.log.txt"

    run_playtest(args)


if __name__ == "__main__":
    main()
