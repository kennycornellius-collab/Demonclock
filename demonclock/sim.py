"""The world-simulation tick engine. Stage 1 built the
generic scheduled-event machinery (timers); Stage 2 added the demon-king
invasion as a self-rescheduling chain of `INVASION_SPREAD`
events; Stage 3 adds price shifts as a similar
self-rescheduling `PRICE_SHIFT` chain that never stops (ongoing ambient
pressure, unlike invasion's finite conquest) — delegating the actual price
math to `economy.py`. Stage 4 adds `BehaviorProfile` decay: unlike
the other three systems it isn't a `ScheduledEvent` at all — it's an ambient,
every-elapsed-day tick (`behavior.tick`) called directly from the loop below,
since it has no due-day/reschedule semantics of its own to route through
`apply_event`. `advance_time` stays the single choke point every elapsed-time
call routes through.

Zero AI in this module itself — pure code (the "golden rule": most
turns cost zero AI calls; the daytime engine tick is one of the free ones).
`_run_batch` delegates to `generation.pipeline.run_batch` (Step 5) when
`state.generation` is a configured, enabled provider registry, and stays a
no-op otherwise (no key configured — identical to its old placeholder
behavior). Either way it's still called exactly once per `advance_time` call
regardless of how many days elapsed (the "exactly ONE batch per
elapsed span" invariant, proven by `test_advance_time_calls_the_batch_placeholder_exactly_once`
before this function ever had anything real to call, and unchanged since).
"""
from __future__ import annotations

from . import behavior, economy, history
from .events import EventKind, ScheduledEvent, validate_event
from .state import GameState

# Placeholder tuning constants — same status as combat.py's DOT_DURATION etc.
# (start rough, calibrate by feel).
INVASION_SPREAD_INTERVAL_DAYS = 5
PRICE_SHIFT_INTERVAL_DAYS = 3


def apply_event(state: GameState, event: ScheduledEvent) -> list[str]:
    """Resolves one scheduled event's state change, always through World's
    existing atomic primitives (block_link/unblock_link) — never a direct row
    mutation. Returns narration line(s).

    Validates the payload's required keys (events.validate_event) before
    touching it, so a malformed event — e.g. one authored by a future
    generation step rather than hand-built content — fails fast with a clean
    EventError instead of a raw KeyError partway through a state mutation."""
    validate_event(event)
    world = state.world
    payload = event.payload

    if event.kind is EventKind.BLOCK_LINK:
        world.block_link(
            payload["from_id"], payload["to_id"], payload["reason"],
            directional_block=payload.get("directional_block", False),
        )
        description = event.description or f"{payload['from_id']} -> {payload['to_id']} is now blocked ({payload['reason']})."
        history.record(world.event_log, state.clock.current_day, payload["from_id"], event.kind, description)
        return [description]

    if event.kind is EventKind.UNBLOCK_LINK:
        world.unblock_link(
            payload["from_id"], payload["to_id"],
            directional_block=payload.get("directional_block", False),
        )
        description = event.description or f"{payload['from_id']} -> {payload['to_id']} is open again."
        history.record(world.event_log, state.clock.current_day, payload["from_id"], event.kind, description)
        return [description]

    if event.kind is EventKind.SET_NODE_STATE:
        node = world.nodes[payload["node_id"]]
        node.state = payload["state"]
        description = event.description or f"{node.name} is now {payload['state']}."
        history.record(world.event_log, state.clock.current_day, node.id, event.kind, description)
        return [description]

    if event.kind is EventKind.INVASION_SPREAD:
        return _apply_invasion_spread(state, event)

    if event.kind is EventKind.PRICE_SHIFT:
        return _apply_price_shift(state)

    raise ValueError(f"unhandled event kind: {event.kind!r}")  # unreachable given EventKind's closed enum


def _apply_price_shift(state: GameState) -> list[str]:
    """Price volatility — delegates the actual math to
    economy.apply_price_shift, then unconditionally reschedules. Unlike
    invasion, this chain never stops: price drift is an ongoing ambient
    pressure source, not a one-time conquest with a natural end."""
    log = economy.apply_price_shift(state)
    state.world.schedule_event(ScheduledEvent(
        due_day=state.clock.current_day + PRICE_SHIFT_INTERVAL_DAYS,
        kind=EventKind.PRICE_SHIFT,
    ))
    return log


def _apply_invasion_spread(state: GameState, event: ScheduledEvent) -> list[str]:
    """The demon-king invasion: a self-rescheduling chain of
    INVASION_SPREAD events. Each fire occupies every node reachable via an
    OPEN link from currently-occupied territory (an army stalls behind a
    blockage the same as a traveler or rumor would — the "blocked
    links stop rumor flow" logic applies here too) and cuts the links it
    crosses. Node-occupation and link-blocking are done via recursive
    `apply_event` calls on synthetic sub-events, reusing SET_NODE_STATE/
    BLOCK_LINK rather than a second "mutate world state" code path."""
    world = state.world
    occupied_ids = {n.id for n in world.nodes.values() if n.state == "occupied"}
    frontier_ids = sorted({
        link.to_id
        for node_id in occupied_ids
        for link in world.open_links_from(node_id)
        if link.to_id not in occupied_ids
    })

    log: list[str] = []
    for node_id in frontier_ids:
        node = world.nodes[node_id]
        log.extend(apply_event(state, ScheduledEvent(
            due_day=event.due_day, kind=EventKind.SET_NODE_STATE,
            payload={"node_id": node_id, "state": "occupied"},
            description=f"The invasion overruns {node.name}.",
        )))
    for node_id in frontier_ids:
        for link in world.links_from(node_id):
            if link.status == "open" and world.nodes[link.to_id].state == "occupied":
                log.extend(apply_event(state, ScheduledEvent(
                    due_day=event.due_day, kind=EventKind.BLOCK_LINK,
                    payload={"from_id": node_id, "to_id": link.to_id, "reason": "enemy"},
                )))

    # Reschedule unless the whole graph has fallen — deliberately NOT
    # conditioned on "did this tick make progress": a tick stalled behind an
    # unrelated temporary blockage (e.g. a blizzard) must still retry next
    # interval, or the invasion would permanently give up the first time
    # it's inconvenienced, contradicting its role as an ambient pressure
    # source rather than a one-shot event.
    if any(node.state != "occupied" for node in world.nodes.values()):
        world.schedule_event(ScheduledEvent(
            due_day=state.clock.current_day + INVASION_SPREAD_INTERVAL_DAYS,
            kind=EventKind.INVASION_SPREAD,
        ))
    else:
        log.extend(_reveal_demon_king(state))
    return log


def _reveal_demon_king(state: GameState) -> list[str]:
    """The invasion payoff ("Bosses as situations, not HP checks"): once
    the whole graph has fallen, retag `World.
    invasion_origin_id`'s node "demon_king" — game.handle_interact checks
    for that tag to offer the real fight (boss.DEMON_KING_ENCOUNTER).
    Deliberately NOT auto-triggered: this only makes the fight reachable,
    per the design conversation's resolved "seek it out" decision — a
    non-combat playthrough can let the invasion finish and never go there.

    Also reopens every link this same invasion blocked (`block_reason ==
    "enemy"`) — total conquest otherwise cuts EVERY link in the graph (see
    `_apply_invasion_spread`'s own crossed-link blocking above), which would
    leave the demon king physically unreachable via Move/Atlas fast-travel
    from anywhere the player isn't already standing. Once there's no more
    territory left to hold, the army has no reason to keep the roads
    sealed — the fallen realm's roads reopen specifically so the final
    confrontation is reachable, matching this function's own narration.
    Unrelated blocks (e.g. a blizzard's `reason="snow"`) are untouched.

    A no-op whenever no origin is configured (`invasion_origin_id is None`,
    the default for any world seed.py didn't touch, e.g. most test
    fixtures) — this step is additive content, not a required engine
    behavior. Fires exactly once: this branch is only reached the one tick
    the reschedule condition first goes false, and INVASION_SPREAD never
    fires again afterward (nothing left to reschedule it)."""
    world = state.world
    origin_id = world.invasion_origin_id
    if origin_id is None or origin_id not in world.nodes:
        return []
    node = world.nodes[origin_id]
    node.tags.append("demon_king")

    for link in world.all_links():
        if link.status == "blocked" and link.block_reason == "enemy":
            world.unblock_link(link.from_id, link.to_id)

    description = f"The Demon King now holds court at {node.name} — the roads lie open, and the way to him with them."
    history.record(world.event_log, state.clock.current_day, node.id, EventKind.SET_NODE_STATE, description)
    return [description]


def tick_day(state: GameState) -> list[str]:
    """Fires every scheduled event due by the current day (due_day <= today,
    not ==, so an event stranded past-due by a save/load gap still fires
    rather than being silently skipped), in due_day order (ties preserve
    schedule order — Python's sort is stable). Fired events are removed;
    never re-fired."""
    world = state.world
    due = sorted(
        (e for e in world.scheduled_events if e.due_day <= state.clock.current_day),
        key=lambda e: e.due_day,
    )
    log: list[str] = []
    for event in due:
        log.extend(apply_event(state, event))
        world.scheduled_events.remove(event)
    return log


def _run_batch(state: GameState) -> None:
    """The AI batch (Director -> Story -> Quest -> Places),
    delegated to generation.pipeline.run_batch (Step 5). Stays a no-op
    whenever state.generation is unset or disabled (no configured provider)
    — identical to this function's previous placeholder behavior in an
    unconfigured environment, so existing saves/tests that never set
    GameState.generation are completely unaffected."""
    if state.generation is None or not state.generation.enabled:
        return
    from .generation.pipeline import run_batch
    run_batch(state, state.generation)


def run_warm_start_batch(state: GameState) -> None:
    """The warm-start batch ("A warm-start generation batch,"
    resolved 2026-07-31): a brand-new save's Quests/Ask around both come
    back empty until `advance_time` fires its first real batch (Rest or
    travel) -- reads as blank/suffocating rather than "freedom" to a fresh
    player. `game.run()` calls this exactly once, immediately after
    building a brand-new (never-loaded) GameState, before the player's
    first real turn. Deliberately just a thin, self-documenting wrapper
    around `_run_batch` itself -- the SAME machinery an ordinary
    elapsed-time tick already calls, not a second generation path: both
    streams run unchanged (no special-casing for "no accrued behavior
    yet" -- world-driven content is deliberately player-independent by
    design, and a fresh BehaviorProfile already degrades
    gracefully to a neutral hint), and this stays a no-op whenever
    state.generation is unset/disabled, exactly like `_run_batch` always
    has. Consistent with (not an exception to) the "elapsed time
    triggers exactly one coalesced batch" invariant -- a new game
    beginning is a reasonable trigger for one batch, the same way any
    other elapsed span is."""
    _run_batch(state)


def advance_time(state: GameState, days: int) -> list[str]:
    """The coalesced choke point every elapsed-time call routes through
    (travel, rest — combat deliberately never calls this, per Combat RNG
    Stage 1). Runs one engine tick per elapsed day (cheap, pure code) but
    calls the AI batch placeholder exactly ONCE regardless of how many days
    elapsed — a 12-day journey is 12 ticks + 1 batch, not 12."""
    if days < 0:
        raise ValueError("cannot advance a negative number of days")
    if days == 0:
        return []

    log: list[str] = []
    for _ in range(days):
        state.clock.advance(1)
        behavior.tick(state.player.behavior, state.player.gold)
        log.extend(tick_day(state))
    _run_batch(state)
    return log
