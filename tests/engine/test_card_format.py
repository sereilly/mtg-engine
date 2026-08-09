"""Guards for the card-data format and the manifest.

The card files used to be raw Scryfall dumps whose unread fields were ~two
thirds of the bytes, retained whole in ``CardDefinition.raw``. They are now
projected onto the fields the engine and web layer actually read
(``scripts/ingest_set.py``). These tests hold that line, and pin the three
data-shape behaviors that were silently wrong before:

* a non-``normal`` layout must fail loudly, not load as a blank vanilla;
* ``*`` power/toughness must not become 0;
* a reprinted card's *original* printing must stay identifiable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from engine.card_loader import (
    MANIFEST_PATH,
    load_cards,
    load_catalog,
    manifest_set_paths,
)
from engine.models import CardDefinition
from engine.oracle import SUPPORTED_LAYOUTS, compile_card_oracle

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import ingest_set  # noqa: E402


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def test_manifest_lists_existing_files_in_order():
    paths = manifest_set_paths()
    assert paths, "manifest lists no sets"
    for path in paths:
        assert path.exists(), f"manifest references a missing file: {path}"


def test_manifest_entries_are_complete():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest["sets"]:
        for key in ("code", "name", "released", "file"):
            assert entry.get(key), f"manifest entry {entry} is missing {key!r}"


def test_manifest_is_the_only_set_list(all_set_paths):
    """The pool is described in one place. Before the manifest the same ordered
    list was copy-pasted across the web app, the fixtures, and five scripts, so
    adding a set meant editing all of them and missing one was silent."""
    import web.app as web_app

    assert [Path(p) for p in web_app.CARD_PATHS] == [Path(p) for p in all_set_paths]


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


def test_no_dead_fields_survive_ingestion(all_set_paths):
    """Every key in the committed data is one something reads. A field that
    creeps back in is dead weight in memory for the whole pool."""
    allowed = set(ingest_set.KEEP_FIELDS)
    for path in all_set_paths:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in entries:
            extra = set(entry) - allowed
            assert not extra, f"{path.name} / {entry.get('name')}: unexpected fields {sorted(extra)}"


def test_required_fields_are_present(all_set_paths):
    for path in all_set_paths:
        entries = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in entries:
            for field in ("name", "mana_cost", "cmc", "type_line", "oracle_id", "set"):
                assert field in entry, f"{path.name} / {entry.get('name')}: missing {field!r}"


def test_prices_are_not_committed(all_set_paths):
    """`prices` guaranteed a full-file diff on every data refresh and was never
    read."""
    for path in all_set_paths:
        assert '"prices"' not in Path(path).read_text(encoding="utf-8")


def test_whole_catalog_still_compiles_as_supported():
    unsupported = [
        (card.name, compile_card_oracle(card).reason)
        for card in load_catalog()
        if not compile_card_oracle(card).supported
    ]
    assert not unsupported, f"cards became unsupported: {unsupported}"


# ---------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------


def _card(**kwargs) -> CardDefinition:
    base = dict(
        name="Test Card", mana_cost="{1}", cmc=1.0, type_line="Instant",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(), raw={},
    )
    base.update(kwargs)
    return CardDefinition(**base)


def test_current_pool_is_all_single_faced():
    assert {card.layout for card in load_catalog()} <= SUPPORTED_LAYOUTS


@pytest.mark.parametrize("layout", ["split", "flip", "transform", "modal_dfc", "adventure", "meld"])
def test_multi_face_layouts_are_explicitly_unsupported(layout):
    """A split card carries empty top-level mana_cost/oracle_text with the real
    text in card_faces. Compiling it as-is would classify it a supported
    vanilla — a wrong answer with no error. It must refuse instead, naming the
    layout so support_report points at the actual gap."""
    card = _card(name=f"Test {layout}", mana_cost="", oracle_text="", layout=layout)
    program = compile_card_oracle(card)
    assert not program.supported
    assert layout in program.reason


def test_normal_layout_still_compiles():
    card = _card(name="Test Bolt", oracle_text="Test Bolt deals 3 damage to any target.")
    assert compile_card_oracle(card).supported


# ---------------------------------------------------------------------------
# Variable power/toughness
# ---------------------------------------------------------------------------


def test_star_power_toughness_is_not_read_as_zero():
    """`int("*")` fails, and the old loader fell back to 0 — which makes a
    Nightmare a 0/0 that dies to state-based actions the moment it enters."""
    card = _card(
        name="Test Nightmare", type_line="Creature — Nightmare Horse",
        power="*", toughness="*",
    )
    assert card.base_power is None
    assert card.base_toughness is None
    assert card.has_variable_pt


def test_printed_digits_parse_normally():
    card = _card(name="Bear", type_line="Creature — Bear", power="2", toughness="2")
    assert (card.base_power, card.base_toughness) == (2, 2)
    assert not card.has_variable_pt


def test_negative_power_survives():
    card = _card(name="Odd", type_line="Creature — Test", power="-1", toughness="3")
    assert card.base_power == -1


def test_pool_variable_pt_cards_are_flagged():
    """These are the pool's characteristic-defining-ability creatures; each is
    served by mixins.permanent_state.DYNAMIC_PT rather than printed digits."""
    flagged = {card.name for card in load_catalog() if card.has_variable_pt}
    assert flagged == {"Gaea's Liege", "Keldon Warlord", "Nightmare", "Plague Rats"}


# ---------------------------------------------------------------------------
# Reprints and printing identity
# ---------------------------------------------------------------------------


def test_reprints_collapse_to_one_card_recording_every_printing():
    catalog = load_catalog()
    bolt = next(card for card in catalog if card.name == "Lightning Bolt")
    assert bolt.printings == ("lea", "leb", "2ed")
    assert bolt.original_printing == "lea"


def test_appending_a_set_never_changes_an_existing_original_printing(all_set_paths):
    """City in a Bottle bans cards "originally printed in Arabian Nights", so
    the answer has to survive the pool growing. Loading a prefix of the manifest
    must agree with loading all of it about every card the prefix contains —
    which is what makes it safe to append reprint sets like Revised."""
    full = {card.name: card.original_printing for card in load_cards(all_set_paths)}
    for count in range(1, len(all_set_paths)):
        prefix = {
            card.name: card.original_printing
            for card in load_cards(all_set_paths[:count])
        }
        for name, printing in prefix.items():
            assert full[name] == printing, (
                f"{name}: original printing changed from {printing!r} to "
                f"{full[name]!r} when later sets were appended"
            )


def test_a_card_reprinted_in_a_later_set_keeps_its_earlier_origin(all_set_paths):
    """Mountain appears in both Alpha and Arabian Nights. It is an Alpha card,
    so City in a Bottle must not sacrifice it."""
    catalog = load_cards(all_set_paths)
    mountain = next(card for card in catalog if card.name == "Mountain")
    assert mountain.original_printing == "lea"
    assert "arn" in mountain.printings


def test_dedupe_is_by_oracle_id(all_set_paths):
    catalog = load_catalog()
    ids = [card.oracle_id for card in catalog if card.oracle_id]
    assert len(ids) == len(set(ids)), "the same oracle_id appears twice in the catalog"


def test_every_catalog_card_knows_its_printings():
    for card in load_catalog():
        assert card.printings, f"{card.name} has no recorded printings"
        assert card.original_printing == card.printings[0]
