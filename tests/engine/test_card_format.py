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
import pathlib
import sys
from pathlib import Path

import pytest

from engine.card_loader import (
    MANIFEST_PATH,
    load_cards,
    load_catalog,
    manifest_set_paths,
)
from engine.models import CardDefinition, CardFace
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


# Cards in the pool the engine does not implement, each with the reason the
# compiler gives. This is a ratchet, not a wish: a card may only appear here
# deliberately, and a card *disappearing* from the pool's unsupported set is
# progress that should shrink this list.
#
# Empty, and that is the point: a card only earns an entry here by being
# deliberately left unimplemented, and it loses the entry the moment it works.
# Ingesting Revised put six cards here; implementing them emptied it again, and
# the assertion below is what forced the list to be cleaned up rather than left
# as a stale excuse.
KNOWN_UNSUPPORTED: set[str] = set()


def test_whole_catalog_still_compiles_as_supported():
    """No card loses support silently.

    A card that stops compiling is either a regression or a deliberate
    reclassification; either way it has to be named here, so the diff shows it.
    """
    unsupported = {
        card.name: compile_card_oracle(card).reason
        for card in load_catalog()
        if not compile_card_oracle(card).supported
    }
    regressions = {n: r for n, r in unsupported.items() if n not in KNOWN_UNSUPPORTED}
    assert not regressions, f"cards became unsupported: {regressions}"

    # Only cards actually in the pool: the list names cards from a set that may
    # not be ingested yet, and an entry for an absent card is not "fixed".
    in_pool = {card.name for card in load_catalog()}
    fixed = (KNOWN_UNSUPPORTED & in_pool) - set(unsupported)
    assert not fixed, (
        "these are supported now — remove them from KNOWN_UNSUPPORTED so the "
        f"list keeps meaning 'not implemented': {sorted(fixed)}"
    )


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
    """Named for what it asserted before split cards (CR 709) were admitted;
    what it holds now is that every layout the shipped pool carries is one the
    compiler reads — the single-face ones, plus the layouts whose faces
    ``engine/faces.py`` derives as cards of their own."""
    assert {card.layout for card in load_catalog()} <= SUPPORTED_LAYOUTS


@pytest.mark.parametrize("layout", ["flip", "transform", "modal_dfc", "adventure", "meld"])
def test_multi_face_layouts_are_explicitly_unsupported(layout):
    """A multi-face card carries empty top-level mana_cost/oracle_text with the
    real text in card_faces. Compiling it as-is would classify it a supported
    vanilla — a wrong answer with no error. It must refuse instead, naming the
    layout so support_report points at the actual gap.

    ``split`` left this list when CR 709 was implemented; the faces are given
    here so the refusal is about the *layout* and not about a card with no
    faces to read (the test below)."""
    faces = (
        CardFace("Front", "{1}", "Instant", "Draw a card."),
        CardFace("Back", "{1}", "Instant", "Draw a card."),
    )
    card = _card(
        name=f"Test {layout}", mana_cost="", oracle_text="", layout=layout, faces=faces,
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert layout in program.reason


def test_a_split_card_with_no_faces_is_still_refused():
    """The original guard, for the one way a split card can still arrive blank:
    a card file whose ``card_faces`` was dropped (``ingest_set.py`` keeps it,
    and this is what notices if it stops). With no halves there is nothing to
    compile, and reading the empty top-level text as a supported vanilla is the
    silently wrong answer the layout gate exists for."""
    card = _card(name="Test split", mana_cost="", oracle_text="", layout="split")
    program = compile_card_oracle(card)
    assert not program.supported
    assert "split" in program.reason


def _split(**halves_text) -> CardDefinition:
    (left, left_text), (right, right_text) = halves_text.items()
    return _card(
        name=f"{left} // {right}", mana_cost="{R} // {3}{G}", cmc=5.0,
        type_line="Sorcery // Sorcery", oracle_text="", colors=("G", "R"),
        layout="split",
        faces=(
            CardFace(left, "{R}", "Sorcery", left_text),
            CardFace(right, "{3}{G}", "Sorcery", right_text),
        ),
    )


def test_a_split_card_compiles_one_program_per_half():
    """CR 709.3a: only the chosen half is evaluated, so the *whole* card has no
    instructions of its own — its verdict is its halves' — and each half
    compiles as the normal-layout card ``engine/faces.py`` derives, under its
    own name (so "Left deals 2 damage" is a self-reference to the half)."""
    from engine.oracle import MULTI_FACE_EFFECT_KIND, compiled_faces, face_programs

    card = _split(
        Left="Left deals 2 damage to any target.",
        Right="Create a 3/3 green Elephant creature token.",
    )
    whole = compile_card_oracle(card)
    assert whole.supported and whole.effect_kind == MULTI_FACE_EFFECT_KIND
    assert whole.instructions == ()
    programs = face_programs(card)
    assert [face.name for face, _ in programs] == ["Left", "Right"]
    assert [program.instructions[0].kind for _, program in programs] == [
        "deal_damage", "create_token",
    ]
    assert compiled_faces(card) == programs
    # ...and a single-face card is its own one-entry list, so an instrument
    # loops over `compiled_faces` without asking which kind it holds.
    bolt = _card(name="Test Bolt", oracle_text="Test Bolt deals 3 damage to any target.")
    assert [face for face, _ in compiled_faces(bolt)] == [bolt]


def test_a_split_card_is_supported_only_when_every_half_is():
    """A card is supported when *any* of its lines is, which is the census
    weakness a two-spell card would inherit as "one half works". It does not:
    a split card with one unreadable half is unsupported, and the reason names
    the half."""
    card = _split(
        Left="Left deals 2 damage to any target.",
        Right="Frobnicate the gribble until morning.",
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert program.reason.startswith("Right: ")


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
    # Pool-relative: the set of CDA creatures grows with the manifest, and
    # pinning the exact names made this fail on the first ingested set rather
    # than on a real change. What matters is that every variable-P/T card is
    # one the engine actually computes a value for.
    from engine.characteristic_defining import dynamic_pt_for
    from engine.oracle import normalize_creature_line

    for name in flagged:
        card = next(c for c in load_catalog() if c.name == name)
        from engine.enter_effects import choosable_bodies

        # Two legitimate sources of a variable printed P/T: a
        # characteristic-defining rule that counts something, or a body chosen
        # as the permanent enters (Primal Clay). Either way the engine produces
        # a number; what must not happen is a `*` with nothing behind it.
        computed = bool(choosable_bodies(card.oracle_text)) or any(
            dynamic_pt_for(normalize_creature_line(line)) is not None
            for line in card.oracle_text.splitlines()
        )
        program = compile_card_oracle(card)
        assert computed or not program.supported, (
            f"{name} has variable P/T, no characteristic-defining rule computes "
            "it, and it still reports supported — it would enter play as 0/0"
        )


# ---------------------------------------------------------------------------
# Reprints and printing identity
# ---------------------------------------------------------------------------


def test_reprints_collapse_to_one_card_recording_every_printing():
    catalog = load_catalog()
    bolt = next(card for card in catalog if card.name == "Lightning Bolt")
    # Read from the manifest rather than hardcoded: this test is about reprints
    # collapsing to one card, and pinning the exact set list made it fail the
    # moment a reprint set was appended — which is the case it exists to cover.
    import json

    from engine.card_loader import MANIFEST_PATH

    manifest = json.loads(pathlib.Path(MANIFEST_PATH).read_text(encoding="utf-8"))
    # Every set that actually contains the card, in manifest order.
    expected = tuple(
        entry["code"].lower()
        for entry in manifest["sets"]
        if any(
            c["name"] == "Lightning Bolt"
            for c in json.loads(
                (pathlib.Path("cards") / entry["file"]).read_text(encoding="utf-8")
            )
        )
    )
    assert bolt.printings == expected
    assert bolt.original_printing == "lea"
    assert len(set(bolt.printings)) == len(bolt.printings), "a set listed twice"


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
