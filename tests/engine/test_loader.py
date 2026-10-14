import json

from engine import load_cards
from engine.card_loader import manifest_set_paths


def test_loader_has_required_core_fields(all_cards):
    sample = all_cards[0]
    assert sample.name
    assert sample.type_line
    assert isinstance(sample.cmc, float)


def _scratch_set(path, name):
    card = {
        "name": name, "mana_cost": "{1}{G}", "cmc": 2,
        "type_line": "Creature — Bear", "set": "tst",
    }
    path.write_text(json.dumps([card]), encoding="utf-8")
    return path


def test_two_loads_of_the_same_files_share_their_card_objects():
    """One catalog per list of files (``load_cards``'s docstring has the
    measurement): collecting this suite made 928 loads, and each whole-manifest
    one was a 27 MB copy of objects nothing may mutate."""
    first = load_cards(manifest_set_paths())
    second = load_cards(manifest_set_paths())
    assert len(first) > 5000
    assert all(one is other for one, other in zip(first, second))


def test_the_list_a_load_returns_is_the_callers_own():
    """The cards are shared; the list is not. A caller that sorts, shuffles or
    appends to its pool must not be editing the next caller's."""
    first = load_cards(manifest_set_paths())
    size = len(first)
    first.clear()
    assert len(load_cards(manifest_set_paths())) == size


def test_a_file_rewritten_in_place_is_read_again(tmp_path):
    """Keyed by size and modification time as well as path, so an ingest that
    rewrites a set file, or a test's scratch set, is not answered from the
    earlier read."""
    path = _scratch_set(tmp_path / "scratch.json", "Scratch Bear")
    assert [card.name for card in load_cards(path)] == ["Scratch Bear"]
    _scratch_set(path, "A Longer Scratch Wolf")
    assert [card.name for card in load_cards(path)] == ["A Longer Scratch Wolf"]


def test_a_single_set_load_does_not_borrow_the_whole_pools_printings(tmp_path):
    """The share is per *list of files*: a card's ``printings`` depend on which
    sets were loaded together, so a one-set load is its own catalog."""
    paths = manifest_set_paths()
    alone = {card.name: card for card in load_cards(paths[0])}
    together = {card.name: card for card in load_cards(paths)}
    assert alone["Black Lotus"].printings == ("lea",)
    assert len(together["Black Lotus"].printings) > 1
    assert alone["Black Lotus"] is not together["Black Lotus"]
