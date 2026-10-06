"""CR 610.3b: "until this leaves the battlefield", when it already has.

"If a resolving triggered ability creates the initial one-shot effect that
causes the object to change zones, and the specified event has already occurred
before that one-shot effect would occur but after that ability triggered, the
object doesn't move."

Unreachable for as long as a permanent's entry trigger was resolved inline, as
the permanent entered: nothing could remove the source between the trigger and
its effect. Planeshift's second wave made an entry trigger a stack object
(CR 603.3), and from that merge the source can be destroyed in response - at
which point each of these three cards did the worst available thing. Idol of
Endurance exiled the creature cards with nothing left to return them. Oubliette
phased a creature out for the rest of the game. And Kitesail Freebooter armed a
pick whose answer needed the departed permanent, so the prompt could never be
satisfied and the game waited on it for ever.

ROADMAP had recorded the precondition a set earlier, by name ("when enters
triggers move to the stack, `exile_graveyard_until_leaves` (Idol of Endurance)
needs an `is_on_battlefield(source)` check"). The integrator read that entry
after the merge was on `main` rather than before it; these tests are what
reading it late cost.

The cards' own rulings say the same thing the rule does (Oubliette, 2020-08-07;
Kitesail Freebooter, 2020-06-23), and are quoted in the handlers.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle


def _table(first: PlayerState, second: PlayerState) -> Game:
    game = Game(players=[first, second])
    game.enforce_mana_costs = False
    return game


def _destroy(game: Game, source: Permanent) -> None:
    """*source* leaves the battlefield for its owner's graveyard, by the two
    steps a destruction takes - so whatever watches it leave is told."""
    game.remove_from_battlefield(source)
    game._permanent_to_graveyard(game.players[0], source)


def _enter_then_lose_the_source(game: Game, source: Permanent) -> None:
    """The source enters, its entry trigger goes on the stack, and the source is
    gone before that trigger resolves - what a Disenchant in response does."""
    game._put_permanent_onto_battlefield(0, source, None)
    assert game.stack, "the entry trigger should be a stack object (CR 603.3)"
    _destroy(game, source)
    game._settle()


@pytest.mark.cr("610.3b")
def test_idol_of_endurance_exiles_nothing_once_it_has_left(catalog_by_name):
    idol = Permanent(card=catalog_by_name["Idol of Endurance"])
    owner = PlayerState(name="P1", graveyard=[
        catalog_by_name["Alpine Watchdog"], catalog_by_name["Llanowar Visionary"],
    ])
    game = _table(owner, PlayerState(name="P2"))

    _enter_then_lose_the_source(game, idol)

    assert owner.exile == [], "nothing is left to send these cards back"
    assert [card.name for card in owner.graveyard] == [
        "Alpine Watchdog", "Llanowar Visionary", "Idol of Endurance",
    ]
    assert not game.pending_choices and game.waiting_prompt() is None


@pytest.mark.cr("610.3b")
def test_idol_of_endurance_still_exiles_when_it_stays(catalog_by_name):
    """The control: the check is about a source that left, not about the card."""
    idol = Permanent(card=catalog_by_name["Idol of Endurance"])
    owner = PlayerState(name="P1", graveyard=[catalog_by_name["Alpine Watchdog"]])
    game = _table(owner, PlayerState(name="P2"))

    game._put_permanent_onto_battlefield(0, idol, None)
    game._settle()

    assert [card.name for card in owner.exile] == ["Alpine Watchdog"]
    game.remove_from_battlefield(idol)
    assert [card.name for card in owner.graveyard] == ["Alpine Watchdog"]


@pytest.mark.cr("610.3b")
def test_oubliette_phases_nothing_out_once_it_has_left(catalog_by_name):
    oubliette = Permanent(card=catalog_by_name["Oubliette"])
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game = _table(PlayerState(name="P1"), PlayerState(name="P2", battlefield=[bears]))

    _enter_then_lose_the_source(game, oubliette)

    assert game.is_on_battlefield(bears), (
        "a creature phased out by a departed Oubliette never phases back in"
    )
    assert not bears.tapped
    assert any("nothing phases out" in line for line in game.log)


@pytest.mark.cr("610.3b")
def test_oubliette_still_phases_its_target_out_when_it_stays(catalog_by_name):
    oubliette = Permanent(card=catalog_by_name["Oubliette"])
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game = _table(PlayerState(name="P1"), PlayerState(name="P2", battlefield=[bears]))

    game._put_permanent_onto_battlefield(0, oubliette, None)
    game._settle()

    assert not game.is_on_battlefield(bears)
    _destroy(game, oubliette)
    game._settle()
    assert game.is_on_battlefield(bears) and bears.tapped, (
        "and it comes back, tapped, when the Oubliette leaves"
    )


@pytest.mark.cr("610.3b", "701.20a")
def test_kitesail_freebooter_reveals_and_exiles_nothing_once_it_has_left(catalog_by_name):
    """The ruling's two halves: "the opponent will reveal their hand, but no
    card will be exiled" - and no pick is left armed for a seat to be stuck on."""
    freebooter = Permanent(card=catalog_by_name["Kitesail Freebooter"])
    opponent = PlayerState(name="P2", hand=[
        catalog_by_name["Shock"], catalog_by_name["Grizzly Bears"],
    ])
    game = _table(PlayerState(name="P1"), opponent)

    _enter_then_lose_the_source(game, freebooter)

    assert [card.name for card in opponent.hand] == ["Shock", "Grizzly Bears"]
    assert opponent.exile == []
    assert any("revealed their hand" in line for line in game.log)
    assert not game.pending_choices, "a pick armed now could never be answered"
    assert game.waiting_prompt() is None
    assert not game.stack


@pytest.mark.cr("610.3b")
def test_kitesail_freebooter_still_takes_a_card_when_it_stays(catalog_by_name):
    freebooter = Permanent(card=catalog_by_name["Kitesail Freebooter"])
    opponent = PlayerState(name="P2", hand=[
        catalog_by_name["Shock"], catalog_by_name["Grizzly Bears"],
    ])
    game = _table(PlayerState(name="P1"), opponent)

    game._put_permanent_onto_battlefield(0, freebooter, None)
    game._settle()
    (pick,) = game.pending_choices
    assert pick.kind == "revealed_hand_pick"
    assert game.confirm_revealed_hand_pick(0, 0)
    game._settle()

    assert [card.name for card in opponent.exile] == ["Shock"], (
        "the noncreature, nonland card in that hand"
    )
    _destroy(game, freebooter)
    assert [card.name for card in opponent.hand] == ["Grizzly Bears", "Shock"]


# --- a source that phased out has not left (CR 702.26d) ----------------------
#
# The other half of the same predicate, and the half a first draft of the fix
# got wrong: this engine takes a phased-out permanent off the battlefield lists,
# so "is it on the battlefield?" calls a phased-out source gone. Reality Ripple
# and Vodalian Illusionist can each do that in response to these triggers, and
# the permanent is back at its controller's next untap step.


def _enter_then_phase_the_source_out(game: Game, source: Permanent) -> None:
    game._put_permanent_onto_battlefield(0, source, None)
    assert game.stack, "the entry trigger should be a stack object (CR 603.3)"
    assert game.phase_out_permanent(source)
    game._settle()


@pytest.mark.cr("610.3b", "702.26d")
def test_idol_of_endurance_phased_out_in_response_still_exiles(catalog_by_name):
    idol = Permanent(card=catalog_by_name["Idol of Endurance"])
    owner = PlayerState(name="P1", graveyard=[catalog_by_name["Alpine Watchdog"]])
    game = _table(owner, PlayerState(name="P2"))

    _enter_then_phase_the_source_out(game, idol)

    assert [card.name for card in owner.exile] == ["Alpine Watchdog"]
    game.phase_in_for(0)
    assert game.is_on_battlefield(idol)
    assert [card.name for card in owner.exile] == ["Alpine Watchdog"], (
        "phasing in is not leaving either"
    )
    _destroy(game, idol)
    assert [card.name for card in owner.graveyard] == ["Alpine Watchdog", "Idol of Endurance"]


@pytest.mark.cr("610.3b", "702.26d")
def test_oubliette_phased_out_in_response_still_phases_its_target_out(catalog_by_name):
    oubliette = Permanent(card=catalog_by_name["Oubliette"])
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game = _table(PlayerState(name="P1"), PlayerState(name="P2", battlefield=[bears]))

    _enter_then_phase_the_source_out(game, oubliette)

    assert not game.is_on_battlefield(bears)
    game.phase_in_for(0)
    assert game.is_on_battlefield(oubliette) and not game.is_on_battlefield(bears)
    _destroy(game, oubliette)
    game._settle()
    assert game.is_on_battlefield(bears) and bears.tapped


@pytest.mark.cr("610.3b", "702.26d")
def test_kitesail_freebooter_phased_out_in_response_still_takes_a_card(catalog_by_name):
    """The pick is answered while its source is phased out, so the answer has to
    find a permanent `permanent_by_id` rightly cannot see."""
    freebooter = Permanent(card=catalog_by_name["Kitesail Freebooter"])
    opponent = PlayerState(name="P2", hand=[
        catalog_by_name["Shock"], catalog_by_name["Grizzly Bears"],
    ])
    game = _table(PlayerState(name="P1"), opponent)

    _enter_then_phase_the_source_out(game, freebooter)
    (pick,) = game.pending_choices
    assert game.confirm_revealed_hand_pick(0, 0)
    game._settle()

    assert [card.name for card in opponent.exile] == ["Shock"]
    game.phase_in_for(0)
    assert [card.name for card in opponent.exile] == ["Shock"]
    _destroy(game, freebooter)
    assert [card.name for card in opponent.hand] == ["Grizzly Bears", "Shock"]


#: A zone change or a phasing "…until this <permanent> leaves the battlefield",
#: as the pool prints it. The verb is part of the pattern on purpose: Gaea's
#: Liege prints the same duration on "target land becomes a Forest", which is a
#: continuous effect that simply ends (CR 611.2) and moves nothing that would
#: have to be moved back.
_UNTIL_THIS_LEAVES = re.compile(
    r"\b(?:exile|phases? out)\b[^.]*\buntil this \w+ leaves the battlefield\b", re.I
)

#: Every supported card printing the phrase, each with three tests above - the
#: source has left, it has not, and it has only phased out.
_HELD_TO_610_3B = {"Idol of Endurance", "Kitesail Freebooter", "Oubliette"}


@pytest.mark.cr("610.3b")
def test_every_card_that_moves_something_until_it_leaves_is_held_to_the_rule(catalog):
    """A ratchet in both directions. A new card printing the phrase is a new
    way to move something with nothing left to move it back, and it joins the
    set only with its own pair of tests; a name here that the pool no longer
    prints is an exemption nobody will re-check."""
    printing = {
        card.name
        for card in compilation_units(catalog)
        if compile_card_oracle(card).supported
        and _UNTIL_THIS_LEAVES.search(card.oracle_text or "")
    }
    assert len(list(compilation_units(catalog))) > 4_500, "the census read the wrong pool"
    assert printing == _HELD_TO_610_3B, (
        f"new: {sorted(printing - _HELD_TO_610_3B)}; "
        f"gone: {sorted(_HELD_TO_610_3B - printing)}"
    )
