"""A text change rewrites the permanent that was named, not the first one.

"Change the text of target spell or permanent by replacing all instances of
one color word with another." (Sleight of Mind.) ``mark_text_modified`` read
its target as a **slot** — ``context.target_permanent_index`` — and, handed
none, took ``battlefield[0]``. An announcement made by ``permanent_id`` alone
names no slot (CR 400.7: the id is the identity, and it is how a headless
caller names a target at all), so the handler rewrote whatever stood first on
that battlefield: aimed at a Darkest Hour beside a Grizzly Bears, the log read
"Sleight of Mind changed B text to W on Grizzly Bears" and the Hour went on
saying black.

Found while driving the layer-3 half of the colour census
(``tests/rules/test_color_effects_timestamp_order.py``), which casts a Sleight
at a static that is not the first permanent on its board. The recolour handler
beside this one was moved onto ``resolve_target_permanent`` rounds ago for the
same reason; this one was left on the slot.

The census is every pool card that compiles the instruction — seven since
Torment's Alter Reality — each announced by id at the **second** of two
permanents.
"""

from __future__ import annotations

import dataclasses

import pytest

from engine import Game, PlayerState
from engine.card_loader import (load_cards, load_catalog, manifest_set_paths,
                                manifest_sets)
from engine.models import Permanent
from engine.oracle import compile_card_oracle, compiled_units
from engine.oracle_types import OracleInstruction
from tests.helpers import _mk_card, settle

KIND = "mark_text_modified"


def _instructions(value, seen=None):
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, OracleInstruction):
        yield value
        yield from _instructions(value.payload, seen)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _instructions(item, seen)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            yield from _instructions(item, seen)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            yield from _instructions(getattr(value, field.name), seen)


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


@pytest.fixture(scope="module")
def every_role():
    """Both manifest roles: a measured set's text changer is driven before it
    ships, so its rows below read the same on either side of its promotion."""
    return {
        card.name: card
        for card in load_cards(manifest_set_paths(include_measured=True))
    }


def _text_changers(pool):
    return sorted(
        card.name for card, program in compiled_units(pool.values())
        if any(step.kind == KIND for step in _instructions(program))
    )


#: The nine, pinned so a tenth has to be driven here (``_expected`` below
#: holds a measured set's to the shipped pool only once it ships). Alter Reality (TOR)
#: joined at Torment's promotion rehearsal: "Change the text of target spell
#: or permanent by replacing all instances of one color word with another."
#: and flashback {1}{U}. Driven by id at the second of two permanents from
#: hand and by flashback, it rewrites the one it named; its "spell" half is
#: refused at announcement, ROADMAP's "Text changes aimed at a spell".
#: Artificial Evolution (ONS) joined at Onslaught's: "…by replacing all
#: instances of one creature type with another. The new creature type can't
#: be Wall." Its words are asked as it resolves (CR 608.2d), so the board
#: carries a creature-type word and a Goblin to answer them by default.
#: Spectral Shift (5DN) joined at Fifth Dawn's promotion rehearsal: a modal
#: instant whose two bullets are Magical Hack's land-type change and Sleight
#: of Mind's colour-word change, with entwine. A cast naming no mode resolves
#: as its first bullet, which the shared test below drives (the Wards'
#: "plainswalk" is its land word); both bullets are driven by mode in
#: ``test_spectral_shifts_bullets_each_rewrite_the_permanent_they_named``.
#: Both are driven while the set is still measured (``every_role``).
TEXT_CHANGERS = (
    "Alter Reality", "Artificial Evolution", "Balduvian Shaman", "Crystal Spray",
    "Magical Hack", "Mind Bend", "Sleight of Mind", "Spectral Shift",
    "Whim of Volrath",
)


#: The pinned text changers a set still under ``measured`` prints, by its
#: code: in the shipped pool (``load_catalog``) only once that set is among
#: ``manifest_sets`` — after its promotion, or under ``MTG_PROMOTE``.
MEASURED_TEXT_CHANGERS = {"Spectral Shift": "5DN"}


def _expected() -> tuple[str, ...]:
    shipped = {entry["code"] for entry in manifest_sets()}
    return tuple(
        name for name in TEXT_CHANGERS
        if MEASURED_TEXT_CHANGERS.get(name, None) in (None, *shipped)
    )


def test_the_text_changers_are_the_ones_driven_here(pool):
    assert tuple(_text_changers(pool)) == _expected()
    assert len(pool) >= 4700


@pytest.mark.parametrize("name", TEXT_CHANGERS)
def test_a_text_change_announced_by_id_rewrites_the_permanent_it_named(every_role, name):
    """Two permanents on one battlefield, the *second* named by id: it is the
    one whose text is changed, and the first is left alone."""
    game = Game(players=[PlayerState(name="A", life=20), PlayerState(name="B", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    # Two white enchantments their controller controls, with no cumulative
    # upkeep — every one of the seven may legally name either (Balduvian
    # Shaman's is the narrowest phrase) — and each carrying both a colour word
    # and a land word, so whichever one a handler rewrites is marked: the mark
    # is written with the record (``text_changes._record``), and a target that
    # carried no word would read unmarked whether it was named or not.
    #
    # …and a **creature-type** word, for the changer that rewrites one of
    # those ("replacing all instances of one creature type with another",
    # Artificial Evolution): its words are asked as it resolves, and a seat
    # nobody asks replaces the first creature type written on the target with
    # its own commonest other type — the Soldier here with the Goblin beside
    # the Wards. Without both the default names no word and nothing is marked.
    warded = _mk_card(
        "Ward of the White Plains", "{W}", "Enchantment",
        "White Soldier creatures you control have plainswalk.", colors=("W",),
    )
    first = Permanent(card=warded)
    named = Permanent(card=warded)
    for perm in (first, named):
        game._put_permanent_onto_battlefield(0, perm, None)
    game._put_permanent_onto_battlefield(
        0, Permanent(card=_mk_card(
            name="Ward Goblin", mana_cost="{R}", type_line="Creature — Goblin",
        )), None,
    )

    card = every_role[name]
    if card.primary_type in ("instant", "sorcery"):
        game.players[0].hand.append(card)
        done = game.queue_from_hand(
            0, name, target_permanent_ids=[named.permanent_id],
            old_color="W", new_color="B",
        )
    else:
        source = Permanent(card=card)
        game._put_permanent_onto_battlefield(0, source, None)
        source.metadata["summoning_sickness_turn"] = -99
        index = next(
            index for index, ability in enumerate(
                compile_card_oracle(card).activated_abilities
            )
            if ability.instruction is not None
            and any(step.kind == KIND for step in _instructions(ability.instruction))
        )
        done = game.queue_permanent_ability(
            0, name, ability_index=index,
            target_permanent_ids=[named.permanent_id],
            old_color="W", mana_color="B",
        )
    assert done.supported, done.details
    settle(game)

    assert named.metadata.get("text_modified") is True, game.log[-4:]
    assert not first.metadata.get("text_modified"), (
        f"{name} was aimed at {named.card.name} and rewrote {first.card.name}"
    )


@pytest.mark.parametrize("mode_index, old_word, new_word, changed_text", [
    # "…replacing all instances of one basic land type with another." The
    # Wards' "plainswalk" names Plains (the wire addresses a land type by its
    # colour, ``W`` = Plains), so Plains becomes Swamp on the one named.
    (0, "W", "B", "swampwalk"),
    # "…replacing all instances of one color word with another." "White
    # Soldier creatures" becomes "Black Soldier creatures" on the one named.
    (1, "W", "B", "black soldier"),
])
def test_spectral_shifts_bullets_each_rewrite_the_permanent_they_named(
    every_role, mode_index, old_word, new_word, changed_text,
):
    """Spectral Shift (5DN), each bullet announced by mode and by id at the
    **second** of two identical permanents: that one's text is changed — the
    printed word replaced, read through the permanent's effective card — and
    the first keeps its own. The ruling (2005-04-01) lets an entwined cast
    name the same permanent with both bullets; each bullet alone is what this
    pins, since the identity question is asked per bullet."""
    game = Game(players=[PlayerState(name="A", life=20), PlayerState(name="B", life=20)])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    warded = _mk_card(
        "Ward of the White Plains", "{W}", "Enchantment",
        "White Soldier creatures you control have plainswalk.", colors=("W",),
    )
    first = Permanent(card=warded)
    named = Permanent(card=warded)
    for perm in (first, named):
        game._put_permanent_onto_battlefield(0, perm, None)
    game.players[0].hand.append(every_role["Spectral Shift"])

    done = game.queue_from_hand(
        0, "Spectral Shift", mode_index=mode_index,
        target_permanent_ids=[named.permanent_id],
        old_color=old_word, new_color=new_word,
    )
    assert done.supported, done.details
    settle(game)

    assert named.metadata.get("text_modified") is True, game.log[-4:]
    assert changed_text in named.effective_card.oracle_text.lower(), (
        named.effective_card.oracle_text
    )
    assert not first.metadata.get("text_modified"), (
        f"Spectral Shift was aimed at {named.card.name} and rewrote {first.card.name}"
    )
    assert first.effective_card.oracle_text == warded.oracle_text
