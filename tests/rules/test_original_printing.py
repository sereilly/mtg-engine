"""Tests for Comprehensive Rules 206.3 — "a name originally printed in ...".

Three cards in the shipped pool name an expansion: City in a Bottle (CR 206.3a,
Arabian Nights), Golgothian Sylex (CR 206.3b, Antiquities) and Apocalypse Chime
(CR 206.3c, Homelands). CR 206.3 is the errata that made them answerable at all
— they used to check the *expansion symbol* on the physical card, and now they
check whether the **name** was originally printed in that set.

That distinction is the whole file. A card is in the sweep because of where its
name first appeared, not because of which printing is on the table, so:

* a permanent whose name debuted in the named set is caught even when the copy
  in play is a much later reprint (35 Arabian Nights names, 50 Antiquities names
  and 29 Homelands names in this pool have a later printing), and
* a card *reprinted into* the named set but first printed earlier is spared —
  Mountain appears in Arabian Nights and is an Alpha card.

The engine's answer is ``CardDefinition.original_printing``, which is
``printings[0]``, which is decided by the **order of cards/manifest.json**. So
these tests are also the reason that file is printing-ordered rather than
append-ordered: a set inserted in the wrong place moves a name's origin, and
these three cards are what would then read a different list.

The copy case (a permanent's name is the name it copied, CR 707.2) lives in
``tests/regressions/test_expansion_sweeps_read_the_effective_name.py``.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_POOL = {card.name: card for card in load_catalog()}


def _board(*names: str) -> tuple:
    permanents = []
    for name in names:
        permanent = Permanent(card=_POOL[name])
        permanent.metadata["summoning_sickness_turn"] = -99
        permanents.append(permanent)
    game = Game(
        players=[
            PlayerState(name="P1", battlefield=permanents),
            PlayerState(name="P2"),
        ]
    )
    game.enforce_mana_costs = False
    game._settle()
    return game, permanents


def _survivors(game) -> list[str]:
    return sorted(perm.card.name for perm in game.all_permanents())


# ---------------------------------------------------------------------------
# Rule 206.3 — the question is the name's origin, not the printing in play
# ---------------------------------------------------------------------------


@pytest.mark.cr("206.3")
def test_the_three_named_expansions_are_read_off_the_first_printing():
    """The premise every test below rests on, asserted rather than assumed: each
    subject's name debuted in the named set and was reprinted afterwards, so a
    reader that asked "which printing is this?" would answer differently from
    one that asked "where did this name start?"."""
    assert _POOL["Giant Tortoise"].printings[0] == "arn"
    assert _POOL["Xenic Poltergeist"].printings[0] == "atq"
    assert _POOL["Abbey Gargoyles"].printings[0] == "hml"
    for name in ("Giant Tortoise", "Xenic Poltergeist", "Abbey Gargoyles"):
        assert len(_POOL[name].printings) > 1, f"{name} has no later printing"


@pytest.mark.cr("206.3", "206.3a")
def test_city_in_a_bottle_takes_a_reprinted_arabian_nights_name():
    """Giant Tortoise is an Arabian Nights card that Fourth Edition printed
    again. CR 206.3a lists the name, so the later printing changes nothing."""
    game, _ = _board("City in a Bottle", "Giant Tortoise", "Grizzly Bears")
    game._settle()

    assert _survivors(game) == ["City in a Bottle", "Grizzly Bears"]


@pytest.mark.cr("206.3", "206.3a")
def test_city_in_a_bottle_spares_a_card_merely_reprinted_into_arabian_nights():
    """Mountain is in the Arabian Nights printing list and is not on CR 206.3a's
    name list, because the name is Alpha's.

    This is the assertion the pre-errata reading would fail: the expansion
    symbol on an Arabian Nights Mountain says Arabian Nights.
    """
    assert "arn" in _POOL["Mountain"].printings
    assert _POOL["Mountain"].original_printing == "lea"

    game, _ = _board("City in a Bottle", "Mountain")
    game._settle()

    assert _survivors(game) == ["City in a Bottle", "Mountain"]


@pytest.mark.cr("206.3", "206.3a")
def test_city_in_a_bottle_bans_casting_by_the_same_reading():
    """The card's other half — "Players can't cast spells or play lands with a
    name originally printed in the Arabian Nights expansion" — is a second
    reader of the same list, in a different subsystem (the cast-permission
    gate rather than the continuous sweep). Both must answer alike, or a card
    is unplayable and unpunished or the reverse."""
    blacksmith = _POOL["Repentant Blacksmith"]   # arn, then Fifth Edition
    bears = _POOL["Grizzly Bears"]               # lea
    bottle = Permanent(card=_POOL["City in a Bottle"])
    p1 = PlayerState(name="P1", hand=[blacksmith, bears], battlefield=[bottle])
    game = Game(players=[p1, PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._settle()

    refused = game.queue_from_hand(0, "Repentant Blacksmith")
    assert not refused.supported
    assert "City in a Bottle" in refused.details

    assert game.queue_from_hand(0, "Grizzly Bears").supported


@pytest.mark.cr("206.3", "206.3b")
def test_golgothian_sylex_takes_a_reprinted_antiquities_name():
    """Xenic Poltergeist is CR 206.3b's list; Fourth and Fifth Edition printed
    it again and the Sylex still takes it. Grizzly Bears is the control."""
    game, _ = _board("Golgothian Sylex", "Xenic Poltergeist", "Grizzly Bears")

    result = game.activate_permanent_ability(0, "Golgothian Sylex")
    assert result.supported, result.details
    game._settle()

    assert _survivors(game) == ["Grizzly Bears"], (
        "the Sylex sacrifices itself too — its own name is on the list"
    )


@pytest.mark.cr("206.3", "206.3c")
def test_apocalypse_chime_takes_a_reprinted_homelands_name():
    """Abbey Gargoyles is CR 206.3c's list and was reprinted in Fifth Edition.

    The Chime sacrifices itself as a cost rather than to its own sweep, which
    is why the survivor list is the same shape as the Sylex's for a different
    reason.
    """
    game, _ = _board("Apocalypse Chime", "Abbey Gargoyles", "Grizzly Bears")

    result = game.activate_permanent_ability(0, "Apocalypse Chime")
    assert result.supported, result.details
    game._settle()

    assert _survivors(game) == ["Grizzly Bears"]


@pytest.mark.cr("206.3")
def test_each_sweep_reads_only_its_own_expansion():
    """Three lists, not one "old card" list. Each sweep leaves the other two
    expansions' cards alone, which is what makes the expansion name in the
    printed sentence payload rather than decoration."""
    game, _ = _board(
        "Golgothian Sylex", "Xenic Poltergeist", "Giant Tortoise", "Abbey Gargoyles"
    )

    assert game.activate_permanent_ability(0, "Golgothian Sylex").supported
    game._settle()

    assert _survivors(game) == ["Abbey Gargoyles", "Giant Tortoise"]
