"""Pool-wide: what a kicked permanent *enters with*, and the X it was kicked for.

``tests/engine/test_kicker.py`` and ``test_two_kickers.py`` hold the cost half
of CR 702.33 — one rewrite, one reader, one key per kicker. This file holds the
entry half, which is not an instruction at all: "If this creature was kicked,
it enters with …" is CR 614.1c's replacement, read off the permanent's own text
by ``enter_effects.kicked_entry`` as it arrives. Three things about it can be
wrong in silence, and each is a creature that paid for something and did not
get it, or got it without paying:

* **Which kicker.** "…kicked **with its {1}{U} kicker**" (CR 702.33f, the five
  Apocalypse Volvers) is linked to one of two costs. A reader that dropped the
  phrase would give a Volver kicked with either cost both lines' counters.
* **An X nobody sized.** "…it enters with **X** +1/+1 counters" (Emblazoned
  Golem) reads the announced X off the permanent; "Kicker {X}" is where it was
  announced.
* **A restriction nothing charges.** "Spend only colored mana on X. No more
  than one mana of each color may be spent this way." is enforced on an
  optional {X} offer and nowhere else, so a card printing it over any other X
  must be refused rather than claimed.

The readers are asked directly, with invented text, and then the pool is: a
census with a floor, because a guard over nothing passes.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_costs import (KICKED, KICKED_WITH, additional_costs,
                               cast_cost_claims_line, kicker_costs,
                               unenforced_x_spend_restriction,
                               x_one_of_each_color_line)
from engine.enter_effects import enter_effect_line, kicked_entry
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle, expand_card_lines
from tests.helpers import _mk_card

#: Apocalypse prints five Volvers, two keyed lines each.
_KEYED_ENTRY_FLOOR = 10

_RESTRICTION = (
    "Spend only colored mana on X. No more than one mana of each color may be "
    "spent this way."
)


def _creature(name: str, text: str):
    return _mk_card(
        name=name, mana_cost="{2}", type_line="Creature — Golem",
        oracle_text=text, power="1", toughness="2",
    )


# --- the reader --------------------------------------------------------------


def test_a_kicked_entry_names_the_kicker_it_is_linked_to():
    """CR 702.33f: the printed cost is data, reported as the canonical key the
    payment is recorded under — so "{U}{1}" and "{1}{U}" are one kicker."""
    entry = kicked_entry(
        "If this creature was kicked with its {1}{U} kicker, it enters with "
        "two +1/+1 counters on it and with flying."
    )
    assert entry == {
        "counters": (2, "+1/+1"), "keywords": ("flying",),
        "ability_lines": (), "kicker": "{1}{U}",
    }
    respelt = kicked_entry(
        "If this creature was kicked with its {U}{1} kicker, it enters with a "
        "+1/+1 counter on it."
    )
    assert respelt["kicker"] == "{1}{U}" and respelt["counters"] == (1, "+1/+1")


def test_a_kicked_entry_that_names_no_kicker_asks_only_whether_it_was_kicked():
    entry = kicked_entry(
        "If this creature was kicked, it enters with three +1/+1 counters on "
        "it and with trample."
    )
    assert entry["kicker"] is None and entry["keywords"] == ("trample",)


@pytest.mark.parametrize("quoted", [
    "Pay 3 life: Regenerate this creature.",
    "Whenever this creature deals damage, you gain that much life.",
])
def test_a_keyed_kicked_entry_carries_a_quoted_ability_as_printed(quoted):
    entry = kicked_entry(
        "If this creature was kicked with its {B} kicker, it enters with a "
        f'+1/+1 counter on it and with "{quoted}"'
    )
    assert entry["kicker"] == "{B}"
    assert entry["ability_lines"] == (quoted,) and entry["keywords"] == ()


def test_a_kicked_entry_sized_by_x_reads_the_announced_x():
    """"…it enters with X +1/+1 counters on it." The count is not printed: it
    is the cast's X, read off the permanent under the key the resolving spell
    stamped it with."""
    entry = kicked_entry(
        "If this creature was kicked, it enters with X +1/+1 counters on it."
    )
    assert entry["counters"] == (0, "+1/+1")
    assert entry["counters_from"] == "cast_x_value"
    assert entry["kicker"] is None


@pytest.mark.parametrize("line", [
    # a cost no payment can be recorded under: nothing can make it true
    "If this creature was kicked with its {X} kicker, it enters with a +1/+1 "
    "counter on it.",
    "If this creature was kicked with its {W/U} kicker, it enters with a +1/+1 "
    "counter on it.",
    # a word after "and with" the engine has no behaviour for
    "If this creature was kicked with its {B} kicker, it enters with a +1/+1 "
    "counter on it and with splendor.",
    # an X with a tail no card prints, and an X on a keyed line
    "If this creature was kicked, it enters with X +1/+1 counters on it and "
    "with flying.",
    "If this creature was kicked with its {B} kicker, it enters with X +1/+1 "
    "counters on it.",
    # not "kicker": a different sentence
    "If this creature was kicked with its {B} cost, it enters with a +1/+1 "
    "counter on it.",
])
def test_a_kicked_entry_the_reader_cannot_carry_out_is_refused_whole(line):
    """Every part must be read or the line is unclaimed, and an unclaimed line
    on a creature is an unsupported card — never one that paid its kicker and
    entered with the counters alone."""
    assert kicked_entry(line) is None
    assert enter_effect_line(line) is None


def test_a_card_asking_about_a_kicker_it_does_not_print_is_unsupported():
    """The keyed entry line is claimed by the reader, so the linked-cost check
    is the support gate's: "{5}" is not one of this card's kicker costs."""
    card = _creature(
        "Invented Misvolver",
        "Kicker {1}{G} and/or {W}\n"
        "If this creature was kicked with its {5} kicker, it enters with a "
        "+1/+1 counter on it.",
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert "kicker cost this card does not print" in program.reason


# --- the entry state ---------------------------------------------------------


def _both_roles() -> dict:
    cards: dict = {}
    for card in compilation_units(
        load_cards(manifest_set_paths(include_measured=True))
    ):
        cards.setdefault(card.name, card)
    return cards


def _entered_as_kicked_with(card, paid: tuple, forest):
    """*card* arriving on a battlefield stamped as a cast that paid *paid*."""
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 5),
        PlayerState("Other", library=[forest] * 5),
    ])
    permanent = Permanent(card=card)
    if paid:
        permanent.metadata[KICKED] = True
        permanent.metadata[KICKED_WITH] = paid
    game._put_permanent_onto_battlefield(0, permanent, None)
    return game, permanent


def test_every_keyed_entry_line_is_applied_for_its_own_kicker_and_no_other():
    """The census. For every supported card in both manifest roles that prints
    a "kicked with its [A] kicker" entry line, and every subset of its kicker
    costs: the permanent enters with exactly the counters, keywords and
    abilities of the lines whose cost was paid — derived from the reader, so a
    card printed the same way needs no row here."""
    cards = _both_roles()
    forest = cards["Forest"]
    examined = 0
    for card in cards.values():
        if "kicked with its" not in (card.oracle_text or "").lower():
            continue
        if not compile_card_oracle(card).supported:
            continue
        entries = [
            entry for line in expand_card_lines(card)
            if (entry := kicked_entry(line, card.name)) is not None
            and entry["kicker"] is not None
        ]
        if not entries:
            continue
        keys = kicker_costs(card.oracle_text)
        assert {entry["kicker"] for entry in entries} <= set(keys), card.name
        subsets = [()] + [(key,) for key in keys] + [tuple(keys)]
        for paid in subsets:
            game, permanent = _entered_as_kicked_with(card, paid, forest)
            mine = [entry for entry in entries if entry["kicker"] in paid]
            wanted = sum(
                entry["counters"][0] for entry in mine
                if entry["counters"][1] == "+1/+1"
            )
            assert int(permanent.metadata.get("plus_counters", 0) or 0) == wanted, (
                card.name, paid,
            )
            for entry in entries:
                granted = entry in mine
                for keyword in entry["keywords"]:
                    if keyword in {word.lower() for word in card.keywords}:
                        continue
                    assert bool(game._has_keyword(permanent, keyword)) is granted, (
                        card.name, paid, keyword,
                    )
                for line in entry["ability_lines"]:
                    text = permanent.effective_card.oracle_text.split("\n")
                    assert (line in text) is granted, (card.name, paid, line)
        examined += len(entries)
    assert examined >= _KEYED_ENTRY_FLOOR, examined


def test_the_x_a_kicked_permanent_enters_with_is_the_casts_and_needs_the_kick():
    """An invented twin of Emblazoned Golem's last line, by text rather than by
    name: stamped kicked with X = 3 it enters with three counters; the X alone,
    without the kick, places none (a mana-cost X does not kick anything)."""
    card = _creature(
        "Invented Counterbody",
        "Kicker {X}\nIf this creature was kicked, it enters with X +1/+1 "
        "counters on it.",
    )
    assert compile_card_oracle(card).supported
    forest = _both_roles()["Forest"]
    for kicked, counters in ((True, 3), (False, 0)):
        game = Game(players=[
            PlayerState("Caster", library=[forest] * 5),
            PlayerState("Other", library=[forest] * 5),
        ])
        permanent = Permanent(card=card)
        permanent.metadata["cast_x_value"] = 3
        if kicked:
            permanent.metadata[KICKED] = True
            permanent.metadata[KICKED_WITH] = ("{X}",)
        game._put_permanent_onto_battlefield(0, permanent, None)
        assert int(permanent.metadata.get("plus_counters", 0) or 0) == counters
        assert permanent.effective_power == 1 + counters


# --- "one mana of each color" on X -------------------------------------------


def test_the_x_spend_restriction_is_read_as_one_whole_line():
    """Both sentences or neither: "only colored mana" without the cap of one
    per colour is a different (and weaker) restriction, and the cap alone
    restricts nothing this table knows of."""
    assert x_one_of_each_color_line(_RESTRICTION)
    assert cast_cost_claims_line(_RESTRICTION)
    for half in (
        "Spend only colored mana on X.",
        "No more than one mana of each color may be spent this way.",
        "Spend only colored mana on X. No more than two mana of each color "
        "may be spent this way.",
        "Spend only black mana on X. No more than one mana of each color may "
        "be spent this way.",
    ):
        assert not x_one_of_each_color_line(half), half
        assert not cast_cost_claims_line(half), half


def test_the_restriction_marks_the_x_offer_of_any_card_printing_both():
    """Keyed on text: an invented card with a different name, type and base
    cost gets the same marked offer, and an offer with no X on the same card
    would not be touched."""
    card = _creature(
        "Invented Prism Golem",
        f"Kicker {{X}}{{1}}\n{_RESTRICTION}\n"
        "If this creature was kicked, it enters with X +1/+1 counters on it.",
    )
    assert compile_card_oracle(card).supported
    (cost,) = additional_costs(card)
    (offer,) = cost.optional_mana
    assert offer.x_one_of_each_color and offer.x_count == 1
    assert unenforced_x_spend_restriction(card.oracle_text, card.name) is None
    # the {1} beside the X stays generic; the X is pips of distinct colours
    assert offer.payments_at(0) == ({"generic": 1},)
    assert {"generic": 1, "W": 1, "U": 1} in offer.payments_at(2)
    assert all(
        sorted(payment.values()) == [1, 1, 1] for payment in offer.payments_at(2)
    )
    assert offer.payments_at(6) == ()

    plain = _creature(
        "Invented Plain Golem",
        "Kicker {X}\nIf this creature was kicked, it enters with X +1/+1 "
        "counters on it.",
    )
    (offer,) = additional_costs(plain)[0].optional_mana
    assert not offer.x_one_of_each_color
    assert offer.x_colorings(3) is None
    assert offer.payments_at(3) == ({"generic": 3},)


@pytest.mark.parametrize("text", [
    # no X-bearing offer at all: the sentence restricts nothing this charges
    f"Flying\n{_RESTRICTION}",
    # a kicker with no X in it
    f"Kicker {{2}}\n{_RESTRICTION}\n"
    "If this creature was kicked, it enters with two +1/+1 counters on it.",
])
def test_the_restriction_over_an_x_nothing_charges_that_way_is_unsupported(text):
    """The line is claimed by the cost table for every card type, so a card
    printing it where nothing enforces it must be refused by name rather than
    compile with the restriction dropped — the failure that is silent and in
    the caster's favour."""
    card = _creature("Invented Loose Golem", text)
    program = compile_card_oracle(card)
    assert not program.supported
    assert "restricts an X nothing charges that way" in program.reason


def test_the_restriction_cannot_ride_a_spell_whose_other_line_compiles():
    """A sorcery is supported when its effect line is — so this is the shape
    the gate exists for: "{X}" in the *mana cost*, the restriction printed, and
    a damage line that compiles. Unsupported, not castable with any mana."""
    card = _mk_card(
        name="Invented Prism Burn", mana_cost="{X}{R}", type_line="Sorcery",
        oracle_text=f"{_RESTRICTION}\nInvented Prism Burn deals X damage to any target.",
    )
    program = compile_card_oracle(card)
    assert not program.supported
    assert "restricts an X nothing charges that way" in program.reason


def test_half_of_the_restriction_leaves_the_card_unsupported():
    card = _creature(
        "Invented Half Golem",
        "Kicker {X}\nSpend only colored mana on X.\n"
        "If this creature was kicked, it enters with X +1/+1 counters on it.",
    )
    assert not compile_card_oracle(card).supported
