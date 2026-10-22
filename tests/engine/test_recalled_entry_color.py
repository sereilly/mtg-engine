"""Every card that reads "the chosen color" off its source's entry record asks
for a colour as it enters.

``lowering/keywords._chosen_color_prelude`` lowers "…protection from the chosen
color" with no choosing sentence in front of it to a ``recall_chosen_color``
step: the colour the ability's source chose as it entered (CR 614.1c), read as
the source last existed (CR 608.2h). The lowering sees one line and cannot
know whether the card that prints it chose anything, so a card printing the
sentence with no entry choice would compile supported and protect from
nothing. No such card is printed; this census is what keeps it that way, the
arrangement ``lowering/mana.py``'s "add one mana of the chosen color" (Sol
Grail) relies on too.
"""

from __future__ import annotations

from engine.card_loader import load_cards, manifest_set_paths
from engine.entry_choices import CHOSEN_COLOR_KEY, entry_choices_of
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card


def _kinds(instruction):
    yield instruction.kind
    for value in instruction.payload.values():
        for inner in value if isinstance(value, (list, tuple)) else (value,):
            if hasattr(inner, "kind") and hasattr(inner, "payload"):
                yield from _kinds(inner)


def _recalls(card) -> bool:
    program = compile_card_oracle(card)
    roots = [*program.instructions]
    roots += [a.instruction for a in program.activated_abilities if a.instruction is not None]
    roots += [t.instruction for t in program.triggered_abilities if t.instruction is not None]
    return any("recall_chosen_color" in set(_kinds(root)) for root in roots)


def _asks_a_color_as_it_enters(card) -> bool:
    return any(row.key == CHOSEN_COLOR_KEY for row in entry_choices_of(card))


def _unrecorded(cards) -> list[str]:
    return sorted(
        card.name for card in cards
        if _recalls(card) and not _asks_a_color_as_it_enters(card)
    )


def test_every_card_recalling_its_entry_color_chose_one():
    cards = load_cards(manifest_set_paths(include_measured=True))
    recalling = [card.name for card in cards if _recalls(card)]
    # The floor: Floating Shield is the card the step was built for.
    assert "Floating Shield" in recalling, recalling
    assert _unrecorded(cards) == []


def test_the_census_names_a_card_that_chose_nothing():
    """Validated backwards: the same sentence on a card that asks no colour as
    it enters is named."""
    invented = _mk_card(
        "Test Hollow Shield", "{W}", "Artifact",
        "{T}, Sacrifice this artifact: Target creature gains protection from "
        "the chosen color until end of turn.",
    )
    assert _recalls(invented)
    assert _unrecorded([invented]) == ["Test Hollow Shield"]
