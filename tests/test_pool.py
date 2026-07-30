from demonclock.canon import PreconditionManifest, Requirement, RequirementKind
from demonclock.clock import Clock
from demonclock.models import Node
from demonclock.player import new_player
from demonclock.pool import CommitOutcome, GeneratedItem, commit_or_repair, pull, pull_for_npc
from demonclock.state import GameState
from demonclock.world import World


def make_state() -> GameState:
    world = World()
    world.add_node(Node(id="a", name="A", state="peaceful"))
    world.add_node(Node(id="b", name="B", state="peaceful"))
    world.add_link("a", "b", "north", travel_days=1)
    player = new_player(name="Hero", location_id="a")
    return GameState(world=world, player=player, clock=Clock())


def passing_item(item_id: str = "item1", giver_npc_id: str | None = None) -> GeneratedItem:
    payload = {"title": "A tale"}
    if giver_npc_id is not None:
        payload["giver_npc_id"] = giver_npc_id
    return GeneratedItem(
        id=item_id, payload=payload,
        manifest=PreconditionManifest([Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "peaceful"})]),
    )


def failing_item(item_id: str = "item1") -> GeneratedItem:
    return GeneratedItem(
        id=item_id, payload={"title": "A tale"},
        manifest=PreconditionManifest([Requirement(RequirementKind.NODE_STATE, {"node_id": "a", "state": "occupied"})]),
    )


# -- commit_or_repair -------------------------------------------------------

def test_commit_or_repair_commits_a_passing_item():
    state = make_state()
    pool: list[GeneratedItem] = []
    item = passing_item()

    result = commit_or_repair(state, pool, item)

    assert result.outcome is CommitOutcome.COMMITTED
    assert result.item is item
    assert pool == [item]


def test_commit_or_repair_rejects_a_failing_item_with_no_repair_fn():
    state = make_state()
    pool: list[GeneratedItem] = []

    result = commit_or_repair(state, pool, failing_item())

    assert result.outcome is CommitOutcome.REJECTED
    assert result.item is None
    assert result.failures  # the original failing requirement(s)
    assert pool == []


def test_commit_or_repair_repairs_a_failing_item_when_repair_fn_fixes_it():
    state = make_state()
    pool: list[GeneratedItem] = []

    def repair_fn(item: GeneratedItem, failures):
        return passing_item(item.id)  # patch: swap in a manifest that now holds

    result = commit_or_repair(state, pool, failing_item(), repair_fn=repair_fn)

    assert result.outcome is CommitOutcome.REPAIRED
    assert result.item.manifest.requirements[0].target["state"] == "peaceful"
    assert pool == [result.item]


def test_commit_or_repair_rejects_when_repair_fn_gives_up():
    state = make_state()
    pool: list[GeneratedItem] = []

    result = commit_or_repair(state, pool, failing_item(), repair_fn=lambda item, failures: None)

    assert result.outcome is CommitOutcome.REJECTED
    assert pool == []


def test_commit_or_repair_rejects_when_the_repair_still_fails_its_own_manifest():
    # A repair_fn's patch is never trusted blindly -- it's re-validated,
    # and if IT still doesn't hold, that's "repair couldn't salvage it".
    state = make_state()
    pool: list[GeneratedItem] = []

    result = commit_or_repair(state, pool, failing_item(), repair_fn=lambda item, failures: failing_item(item.id))

    assert result.outcome is CommitOutcome.REJECTED
    assert result.failures
    assert pool == []


# -- pull ---------------------------------------------------------------

def test_pull_returns_none_from_an_empty_pool():
    state = make_state()
    assert pull(state, []) is None


def test_pull_returns_and_removes_the_oldest_valid_item():
    state = make_state()
    pool = [passing_item("first"), passing_item("second")]

    pulled = pull(state, pool)

    assert pulled.id == "first"
    assert [item.id for item in pool] == ["second"]


def test_pull_silently_discards_a_stale_item_and_keeps_scanning():
    state = make_state()
    pool = [passing_item("first"), passing_item("second")]

    # The world moves between commit and pull -- "first"'s precondition no
    # longer holds by the time anyone asks for it.
    state.world.nodes["a"].state = "occupied"

    pulled = pull(state, pool)

    assert pulled is None  # both items required a: peaceful, both now stale
    assert pool == []  # discarded, not left dangling for a future pull


def test_pull_returns_the_first_item_still_valid_after_discarding_stale_ones():
    state = make_state()
    stale = GeneratedItem(
        id="stale", payload={},
        manifest=PreconditionManifest([Requirement(RequirementKind.NODE_STATE, {"node_id": "b", "state": "occupied"})]),
    )
    fresh = passing_item("fresh")
    pool = [stale, fresh]

    pulled = pull(state, pool)

    assert pulled.id == "fresh"
    assert pool == []


# -- pull_for_npc (NPC-quest link follow-up) --------------------------------

def test_pull_for_npc_returns_none_from_an_empty_pool():
    state = make_state()
    assert pull_for_npc(state, [], "hana") is None


def test_pull_for_npc_returns_the_matching_item_and_removes_only_it():
    state = make_state()
    pool = [
        passing_item("unrelated"),
        passing_item("for_hana", giver_npc_id="hana"),
        passing_item("also_unrelated"),
    ]

    pulled = pull_for_npc(state, pool, "hana")

    assert pulled.id == "for_hana"
    # non-matching, still-valid items are left in place -- unlike pull(),
    # this must not silently drain quests meant for someone else / the
    # generic Quests menu.
    assert [item.id for item in pool] == ["unrelated", "also_unrelated"]


def test_pull_for_npc_returns_none_and_leaves_the_pool_untouched_when_nothing_matches():
    state = make_state()
    pool = [passing_item("a"), passing_item("b", giver_npc_id="oskar")]

    pulled = pull_for_npc(state, pool, "hana")

    assert pulled is None
    assert [item.id for item in pool] == ["a", "b"]


def test_pull_for_npc_discards_a_stale_item_encountered_before_the_match():
    state = make_state()
    stale = GeneratedItem(
        id="stale", payload={"giver_npc_id": "oskar"},
        manifest=PreconditionManifest([Requirement(RequirementKind.NODE_STATE, {"node_id": "b", "state": "occupied"})]),
    )
    match = passing_item("for_hana", giver_npc_id="hana")
    pool = [stale, match]

    pulled = pull_for_npc(state, pool, "hana")

    assert pulled.id == "for_hana"
    assert pool == []  # the stale item ahead of it was discarded, not left dangling


def test_pull_for_npc_returns_the_oldest_matching_item_when_several_match():
    state = make_state()
    pool = [passing_item("first", giver_npc_id="hana"), passing_item("second", giver_npc_id="hana")]

    pulled = pull_for_npc(state, pool, "hana")

    assert pulled.id == "first"
    assert [item.id for item in pool] == ["second"]


# -- serialization ------------------------------------------------------

def test_generated_item_round_trips_through_to_dict_and_from_dict():
    item = passing_item()
    assert GeneratedItem.from_dict(item.to_dict()) == item
