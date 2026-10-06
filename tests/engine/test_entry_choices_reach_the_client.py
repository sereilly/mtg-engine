"""What a permanent chose as it entered is on the wire.

"As this creature enters, choose a nonland card name. Spells with the chosen
name can't be cast." (Meddling Mage.) "As this creature enters, choose a color.
This creature has protection from the chosen color." (Voice of All.) The engine
recorded each choice, read it at every seam it owns — and sent the client
nothing: ``web/serialization._serialize_permanent`` carried no chosen colour,
name, type or player, so a player facing an opponent's Voice of All learned its
colour by having a spell fizzle. Forty-seven permanents across the pool make
such a choice and for most of them it is the whole of what the card does.

``enter_effects.ENTRY_CHOICES`` is the engine's table of what an entry records,
built from that module's own readers of the printed sentence, and
``chosen_as_entered`` is what the permanent payload carries
(``entry_choices``). This file holds the table to the writer **in both
directions** over the pool, because the table is a second statement of which
sentence writes which record and only a guard keeps two statements one:

* every permanent printing an "as this enters, choose / pay any amount"
  sentence is put on a battlefield with the default answer, and its serialized
  payload must carry each choice its text makes — or the card is named below
  with where its choice *is* shown;
* every permanent in the pool that mentions entering is entered, and any
  ``chosen…`` record the entry wrote must belong to a row that claims the card.

Validated backwards: with the payload field removed, the first test fails for
all 47.
"""
from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.enter_effects import (ENTRY_CHOICES, LIFE_PAID_AS_ENTERED,
                                  chosen_as_entered, entry_choices_of)
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack
from web.serialization import _serialize_permanent

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)

#: A printed sentence in which a permanent chooses, or pays an amount it
#: chooses, as it enters (CR 614.1c). Deliberately wider than the table's own
#: readers: this is what finds a sentence the table has no row for.
_ENTRY_CHOICE_LINE = re.compile(
    r"^as .*\benters\b.*\b(choose|choice|pay any amount)\b", re.I
)

#: Entry choices the payload field does not list, each with where the choice
#: is shown instead — and each proved below, so the reason cannot go stale.
_SHOWN_ANOTHER_WAY = {
    "Primal Clay": "the chosen body is its power, toughness, keyword and type",
    "Phantasmal Terrain": "the chosen type is the enchanted land's, badged on the land",
}


def _w2g3_table():
    game = Game(players=[
        PlayerState(name="Ann", library=[_POOL["Forest"]] * 5),
        PlayerState(
            name="Bob", library=[_POOL["Forest"]] * 5,
            graveyard=[_POOL["Lightning Bolt"]],
        ),
    ])
    game.players[0].battlefield = [
        Permanent(card=_POOL["Hill Giant"]), Permanent(card=_POOL["Forest"]),
    ]
    game.players[1].battlefield = [
        Permanent(card=_POOL["Grizzly Bears"]), Permanent(card=_POOL["Mountain"]),
    ]
    game._recompute_continuous_effects()
    return game


def _w2g3_entered(name: str):
    """*name* on seat 0's battlefield, having made every entry choice the way
    a seat nobody asks makes it. Returns the game and the permanent."""
    game = _w2g3_table()
    permanent = Permanent(card=_POOL[name])
    game._put_permanent_onto_battlefield(0, permanent, None)
    return game, permanent


def _w2g3_permanents(mentioning: str = "") -> list[str]:
    return sorted(
        card.name for card in compilation_units(_POOL.values())
        if card.face_of is None
        and card.primary_type not in ("instant", "sorcery")
        and mentioning in (card.oracle_text or "").lower()
        and compile_card_oracle(card).supported
    )


def _w2g3_choosers() -> list[str]:
    return [
        name for name in _w2g3_permanents("enters")
        if any(
            _ENTRY_CHOICE_LINE.search(line)
            for line in (_POOL[name].oracle_text or "").splitlines()
        )
    ]


def test_w2g3_the_sweep_reaches_the_cards_it_is_about():
    choosers = _w2g3_choosers()
    assert len(choosers) >= 49, choosers
    assert {"Meddling Mage", "Voice of All", "Shifting Sky", "Runed Halo",
            "Null Chamber", "Booby Trap", "Conspiracy", "Traveler's Cloak",
            "Alloy Golem", "Black Vise", "Jihad"} <= set(choosers)
    assert set(_SHOWN_ANOTHER_WAY) <= set(choosers)
    # Every row of the table is something a card in the pool actually records:
    # a row no card reaches is a row nothing here has shown working.
    reached = {row.key for name in choosers for row in entry_choices_of(_POOL[name])}
    assert reached == {row.key for row in ENTRY_CHOICES}
    assert len(ENTRY_CHOICES) >= 9
    assert len(_w2g3_permanents("enters")) >= 500


@pytest.mark.parametrize("name", _w2g3_choosers())
def test_w2g3_an_entry_choice_is_on_the_serialized_permanent(name):
    game, permanent = _w2g3_entered(name)
    rows = entry_choices_of(permanent.effective_card)
    if name in _SHOWN_ANOTHER_WAY:
        assert not rows, f"{name} has a row now: drop it from _SHOWN_ANOTHER_WAY"
        return
    assert rows, f"{name} chooses as it enters and no row of ENTRY_CHOICES claims it"
    payload = _serialize_permanent(permanent, game)
    shown = {entry["label"]: entry["value"] for entry in payload["entry_choices"]}
    for row in rows:
        assert row.key in permanent.metadata, (name, row.key)
        assert row.label in shown, (name, row.label, shown)
        assert isinstance(shown[row.label], str) and shown[row.label] != "", (
            name, row.label,
        )
    assert len(shown) == len(rows)


def test_w2g3_every_record_an_entry_writes_belongs_to_a_row():
    """The other direction, over every permanent that mentions entering: a
    ``chosen…`` record nothing in the table claims is a choice the client is
    not told about."""
    examined = 0
    written: dict[str, int] = {}
    unclaimed: list[tuple[str, str]] = []
    for name in _w2g3_permanents("enters"):
        _game, permanent = _w2g3_entered(name)
        examined += 1
        claimed = {row.key for row in entry_choices_of(permanent.effective_card)}
        for key in permanent.metadata:
            if not (key.startswith("chosen") or key == LIFE_PAID_AS_ENTERED):
                continue
            written[key] = written.get(key, 0) + 1
            if key not in claimed:
                unclaimed.append((name, key))
    # Primal Clay's body, which the card face shows (proved below).
    assert unclaimed == [("Primal Clay", "chosen_body")], unclaimed
    # Measured: 509 permanents mention entering, and 52 records are written.
    assert examined >= 500, examined
    assert sum(written.values()) >= 50, written
    assert set(written) - {"chosen_body"} == {row.key for row in ENTRY_CHOICES}


def test_w2g3_no_entry_choice_in_the_pool_is_hidden():
    """Everything ``entry_choices`` carries is sent to every viewer, which is
    right only while every such choice is made in the open. A sentence that
    says otherwise must stop here until the field learns who may see it."""
    for name in _w2g3_choosers():
        text = (_POOL[name].oracle_text or "").lower()
        assert "secret" not in text, name
        assert "face down" not in text and "face-down" not in text, name


def test_w2g3_the_choice_is_shown_in_a_players_words():
    """A seat is its player's name and a colour symbol is the colour."""
    game, vise = _w2g3_entered("Black Vise")
    assert chosen_as_entered(game, vise) == [{"label": "Chosen player", "value": "Bob"}]

    game, voice = _w2g3_entered("Voice of All")
    voice.metadata["chosen_color"] = "R"
    assert chosen_as_entered(game, voice) == [{"label": "Chosen color", "value": "red"}]

    game, mage = _w2g3_entered("Meddling Mage")
    assert chosen_as_entered(game, mage) == [
        {"label": "Named card", "value": "Lightning Bolt"},
    ]
    mage.metadata["chosen_card_name"] = ""
    assert chosen_as_entered(game, mage) == [{"label": "Named card", "value": "nothing"}]

    game, chamber = _w2g3_entered("Null Chamber")
    assert chosen_as_entered(game, chamber) == [
        {"label": "Named cards", "value": "Grizzly Bears, Hill Giant"},
    ]

    game, trap = _w2g3_entered("Booby Trap")
    assert chosen_as_entered(game, trap) == [
        {"label": "Chosen player", "value": "Bob"},
        {"label": "Named card", "value": "Grizzly Bears"},
    ]

    game, terrain = _w2g3_entered("Illusionary Terrain")
    (entry,) = chosen_as_entered(game, terrain)
    assert entry["label"] == "Chosen land types (first, second)"
    assert entry["value"] == ", ".join(terrain.metadata["chosen_land_types"])


def test_w2g3_a_permanent_that_chose_nothing_carries_an_empty_list():
    game, bears = _w2g3_entered("Grizzly Bears")
    assert _serialize_permanent(bears, game)["entry_choices"] == []
    # …and a record under a sentence the permanent does not print is not a
    # choice it made as it entered (the key is also written by resolving
    # "choose a color" effects).
    bears.metadata["chosen_color"] = "G"
    assert _serialize_permanent(bears, game)["entry_choices"] == []


def test_w2g3_a_copy_reports_the_choice_the_copy_made():
    """CR 707.2 and CR 614.1c: a Clone entering as a Voice of All chooses a
    colour of its own, and that — read off what the permanent *is* — is what
    it reports."""
    from engine.copies import become_copy

    game, voice = _w2g3_entered("Voice of All")
    clone = Permanent(card=_POOL["Clone"])
    game.players[0].battlefield.append(clone)
    assert chosen_as_entered(game, clone) == []
    become_copy(clone, voice)
    assert clone.effective_card.name == "Voice of All"
    clone.metadata["chosen_color"] = "B"
    assert chosen_as_entered(game, clone) == [{"label": "Chosen color", "value": "black"}]
    assert chosen_as_entered(game, voice) == [{"label": "Chosen color", "value": "green"}]


def test_w2g3_primal_clays_choice_is_its_printed_face():
    game, clay = _w2g3_entered("Primal Clay")
    body = clay.metadata["chosen_body"]
    payload = _serialize_permanent(clay, game)
    assert (payload["power"], payload["toughness"]) == (body["power"], body["toughness"])


def test_w2g3_phantasmal_terrains_choice_is_the_lands_badge():
    game = _w2g3_table()
    game.players[0].hand = [_POOL["Phantasmal Terrain"]]
    forest = next(p for p in game.controlled_by(0) if p.card.name == "Forest")
    result = game.cast_from_hand(
        0, "Phantasmal Terrain",
        target_player_index=0, target_permanent_ids=[forest.permanent_id],
    )
    assert result.supported, result.details
    resolve_stack(game)
    # Its choice is a prompt of its own kind (`land_type_choice`), answered
    # after the Aura is attached, and what it records is the *land's* type.
    assert game.confirm_land_type(0, "island")
    aura = next(p for p in game.controlled_by(0) if p.card.name == "Phantasmal Terrain")
    assert _serialize_permanent(aura, game)["entry_choices"] == []
    assert _serialize_permanent(forest, game)["land_type_override"] == "island"
