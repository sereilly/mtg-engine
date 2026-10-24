"""Regression: a creature card's characteristic-defining power, off the battlefield.

CR 604.3 / 113.6a: "Characteristic-defining abilities function in all zones."
Carrion Grub's "+X/+0, where X is the greatest power among creature cards in
your graveyard" read a "*" card's power as 0 — the counter's comment claimed CR
604.3 as the reason, which is the rule backwards — so a Lhurgoyf in the Grub's
graveyard counted 0 rather than the creature cards in all graveyards.

Found by Judgment's W1G3, whose Selfless Exorcist ("That card deals damage
equal to its power to this creature", ruling 2013-04-15: "Abilities that define
a creature's power (and toughness) apply in every zone") needed the same answer
for a card in exile: ``Game.card_power_outside_battlefield``, one reader of the
battlefield refresh's own CDA counter. Carrion Grub is the one shipped card
whose count read a graveyard card's power (``_amounts``' ``greatest_power``
aggregate over a zone).
"""
from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent


def _grub_game(set_pool, mine, theirs=()):
    m21, ice, lea = set_pool("M21"), set_pool("ICE"), set_pool("LEA")
    pool = {**lea, **ice, **m21}
    grub = Permanent(card=m21["Carrion Grub"])
    game = Game(players=[
        PlayerState(name="P1", battlefield=[grub], graveyard=[pool[n] for n in mine]),
        PlayerState(name="P2", graveyard=[pool[n] for n in theirs]),
    ])
    game.check_state_based_actions()
    return game, grub


def test_a_lhurgoyf_in_the_grubs_graveyard_counts_its_defined_power(set_pool):
    """Lhurgoyf: "power is equal to the number of creature cards in all
    graveyards". Four of them here (itself, two Elves, a Bear), so the Grub
    gets +4 — not the +1 its other card (Llanowar Elves) would give."""
    game, grub = _grub_game(
        set_pool, ["Lhurgoyf", "Llanowar Elves"], ["Llanowar Elves", "Grizzly Bears"],
    )
    assert game.card_power_outside_battlefield(game.players[0].graveyard[0], 0) == 4
    assert (grub.effective_power, grub.effective_toughness) == (4, 5)


def test_the_count_follows_the_graveyards(set_pool):
    """The CDA is continuous (CR 604.3, 611.3a): a creature card leaving any
    graveyard lowers the Lhurgoyf's power, and with it the Grub's bonus."""
    game, grub = _grub_game(
        set_pool, ["Lhurgoyf", "Llanowar Elves"], ["Llanowar Elves", "Grizzly Bears"],
    )
    game.players[1].exile.append(game.players[1].graveyard.pop())
    game.check_state_based_actions()
    assert grub.effective_power == 3


def test_a_printed_power_still_reads_as_printed(set_pool):
    game, grub = _grub_game(set_pool, ["Llanowar Elves", "Grizzly Bears"])
    assert grub.effective_power == 2


def test_a_cda_reads_its_owners_board_as_you(set_pool):
    """CR 109.5: a card with no controller has its owner as "you". Nightmare
    ("…equal to the number of Swamps you control") in P2's exile counts P2's
    Swamps, not P1's."""
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState(name="P1", battlefield=[Permanent(card=lea["Swamp"])]),
        PlayerState(
            name="P2",
            battlefield=[Permanent(card=lea["Swamp"]), Permanent(card=lea["Swamp"])],
            exile=[lea["Nightmare"]],
        ),
    ])
    assert game.card_power_outside_battlefield(lea["Nightmare"], 1) == 2
    assert game.card_power_outside_battlefield(lea["Nightmare"], 0) == 1
