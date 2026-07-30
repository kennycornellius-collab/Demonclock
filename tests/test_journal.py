from demonclock.journal import JournalEntry, record


def test_record_appends_an_entry():
    entries: list[JournalEntry] = []

    record(entries, day=3, description="First visited Millhaven Village.")

    assert entries == [JournalEntry(day=3, description="First visited Millhaven Village.")]


def test_record_appends_in_order():
    entries: list[JournalEntry] = []

    record(entries, day=1, description="one")
    record(entries, day=2, description="two")

    assert [e.description for e in entries] == ["one", "two"]


def test_journal_entry_round_trips_through_dict():
    entry = JournalEntry(day=5, description="Completed quest: Bring the grain (+25 gold).")
    assert JournalEntry.from_dict(entry.to_dict()) == entry
