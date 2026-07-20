from demonclock.events import EventKind
from demonclock.history import LogEntry, record


def test_record_appends_a_new_entry():
    log: list[LogEntry] = []
    record(log, day=5, node_id="wilds", kind=EventKind.SET_NODE_STATE, description="The invasion overruns Bramblewood Wilds.")

    assert len(log) == 1
    entry = log[0]
    assert entry.day == 5
    assert entry.node_id == "wilds"
    assert entry.kind is EventKind.SET_NODE_STATE
    assert entry.description == "The invasion overruns Bramblewood Wilds."


def test_record_never_removes_or_mutates_earlier_entries():
    log: list[LogEntry] = []
    record(log, day=1, node_id="a", kind=EventKind.SET_NODE_STATE, description="first")
    record(log, day=2, node_id="b", kind=EventKind.BLOCK_LINK, description="second")

    assert [e.description for e in log] == ["first", "second"]


def test_log_entry_round_trips_through_to_dict_and_from_dict():
    entry = LogEntry(day=7, node_id="market", kind=EventKind.UNBLOCK_LINK, description="The pass reopens.")
    restored = LogEntry.from_dict(entry.to_dict())
    assert restored == entry
