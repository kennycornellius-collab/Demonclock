# Demonclock

*(working title — Emergent Sandbox RPG)*

A terminal, text-based RPG whose premise is **freedom**: you can pursue any role
(merchant, king, knight, chef, hermit, or something nobody planned for) and the world
keeps moving on its own timers whether or not you engage with the demon-king invasion
looming over it. There are no fixed classes and no "pick your build" screen — who you
become is read off of what you actually spend your days doing.

The engine itself is small and deterministic. The complexity lives in an optional
AI-driven layer that generates story, quests, and new places for the world's own
simulation to run through — never the other way around.

## What makes it tick

- **The simulation is the brain; the AI is the mouth.** Every outcome — combat,
  trades, quest completion — is decided by engine code. The AI only narrates results
  the engine already computed, and proposes content the engine then validates before
  it's ever shown to you.
- **No fixed classes.** Attributes (`STR`, `MAGIC`, `AGILITY`, `DEFENSE`, `CHARISMA`,
  `PERCEPTION`, `LUCK`, `HP`, `MANA`) are fixed and can't be created or deleted, but
  skills are entirely player-authored, and your "role" is just a label derived from
  what you've actually been doing lately (decaying counters, so it can change).
- **The world moves without you.** The invasion advances, prices drift, a blizzard
  closes a pass and later clears — all on their own schedule, whether or not you're
  watching.
- **Fog of war is real, not flavor.** What you *believe* about a place and what's
  *actually true* there are two separate layers. Belief only updates when you
  physically see it or hear a rumor — it never silently snaps to the truth, so
  fast-traveling toward a "safe" town on week-old information can land you somewhere
  else entirely.
- **Skill creation is never blocked.** Compose any skill you like from a fixed
  vocabulary of effects (damage, heal, stun, dot, lifesteal, shield, buff/debuff,
  cleanse, aoe, knockback, taunt). The engine computes a fair MANA/cooldown cost for
  whatever power level you ask for; undercutting it is a legitimate, visible opt-out
  (a `creative_mode` flag), not an exploit to patch.
- **Bosses are situations, not damage races.** Because player power is unbounded by
  design, the demon king can't be balanced as an HP number — the fight is phases,
  adds, and terrain instead.
- **Losing is rarely the end.** An ordinary defeat means captured/ransomed, not
  game over — every setback ships with a guaranteed way out. True game-over is
  reserved for the demon king alone.

## What's playable right now

- Explore a graph of connected places (not a coordinate grid), fast-travel to
  anywhere you've discovered, and read the world through fog of war and
  deterministically-propagated rumors.
- Turn-based combat with an injectable-RNG dodge/crit/damage-variance layer, against
  wild encounters (including real multi-enemy packs) or the demon king's own
  multi-phase fight.
- A full player-authored skill system, with a fair-cost calculator shown at
  creation time.
- Trading against nodes with live, threat-driven prices (buying and selling nudges
  the price too).
- Quests: pulled from a generated content pool, accepted, and turned in once you've
  actually met the objective.
- NPCs with hybrid dialogue — a few generated conversation options plus a free-text
  line, always flavor, never state-changing. NPCs are also real combat targets:
  attacking (or killing) one is permanent and moves your standing with their faction.
- Factions and standing — quest turn-ins, trading at a faction-affiliated node, and
  attacking/killing an affiliated NPC all move it.
- Crafting at workshop-tagged locations from a small fixed recipe table.
- A player-facing journal recapping your own story so far (places first visited,
  fights won/lost, quests completed, captures/escapes) — a pure read, no input needed.
- An optional generation layer (Director → Story → Quest → Places → Flavor agents)
  that fills the content pool and colors the world while you're away — every
  generated item is checked against live world state before it's ever shown to you,
  and again right before you pull it, since the world keeps moving in between.


## Playing it

Requires Python 3.11+. No third-party runtime dependencies.

```
python -m pip install -e ".[dev]"   # install the package + pytest, editable
python -m demonclock                # play (menu-driven REPL)
```

The save file defaults to `demonclock.save.sqlite` in the current directory and is
auto-loaded on startup if present; delete it to start a fresh game.

### Turning on AI-driven generation (optional)

The game runs perfectly well with no key configured — the generation batch simply
no-ops and every turn stays engine-only. To turn it on:

```
cp .env.example .env      # (or just copy the file by hand on Windows)
# then fill in GEMINI_API_KEY=... in .env
```

`.env` is gitignored and never committed. A real `GEMINI_API_KEY` environment
variable always takes precedence over whatever's in `.env`. Gemini is the only
provider wired up today; the provider layer is written to make adding another one
(Anthropic, OpenAI) a single new adapter file, not a redesign.

### The menu, briefly

Every turn offers: **Move** / **Interact** / **Inventory** / **Rest** /
**Something else…** / **Skills** / **Atlas** / **Ask around** / **Quests** /
**Journal** / **Save & Quit**.

- **Move** lists every exit from where you're standing — open ones by destination,
  blocked ones as `???` with the reason why.
- **Interact** offers whatever's actually present at that node: Trade, Fight, Talk to
  or Attack an NPC, Craft — a location with more than one shows a picker; one thing
  runs directly.
- **Something else…** opens free text, the one place the parser runs —
  deterministic verb matching first; if that doesn't match, an AI fallback (when
  configured) picks the closest action actually available to you right now rather
  than inventing one — it'll never claim to do something the game doesn't support,
  even if your sentence describes something plausible-sounding.
- **Atlas** and **Ask around** are how you reduce fog of war — by belief and by
  rumor, respectively — never by peeking at world truth directly.
- **Quests** shows what you've accepted and lets you turn one in once its objective
  actually holds.
- **Journal** is a pure read — your own story so far, recorded automatically as
  things happen.

## Running the tests

```
python -m pytest                                # full suite
python -m pytest tests/test_world.py            # one file
python -m pytest tests/test_world.py::test_name  # one test
```
