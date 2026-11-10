"""Read the Runes: the sacrifices, then the discards.

"Draw X cards. For each card drawn this way, discard a card unless you
sacrifice a permanent." Its ruling (2004-10-04, Scryfall): "You draw the
cards, then sacrifice any permanents you want to sacrifice, then discard the
required number of card from your hand. There is no chance to play any cards
in between these actions." CR 118.12a reads each repetition as "you may
sacrifice a permanent; if you don't, discard a card".

kg4 held every repetition's sacrifice for the loop's end (Fade Away's ruling:
"all the sacrifices are done at the same time"), and the discard stayed at
each answer — so the discards came first. That was filed as "log order only",
and it is not: a Library of Leng given up to the same Read the Runes still
offered its "put it on top of your library instead" to the card discarded
before it went. The penalty now waits on the loop's batch
(``SacrificeChoicesMixin.run_penalty`` / ``defer_penalty``, the loop's
``penalties_after``) and is made after the sacrifices.

Of the three loops in the pool that hold sacrifices (Fade Away, Oath of
Lim-Dûl, Read the Runes), Read the Runes is the one whose penalty is not a
sacrifice; Oath's discard is its *price*, paid at each answer as before.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import settle

_CARDS = {card.name: card for card in load_catalog()}


def _table(*, interactive: bool) -> tuple[Game, Permanent]:
    game = Game(players=[
        PlayerState(
            name="P0", life=20, library=[_CARDS["Island"]] * 6,
            hand=[_CARDS["Read the Runes"], _CARDS["Shock"], _CARDS["Grizzly Bears"]],
        ),
        PlayerState(name="P1", life=20, library=[_CARDS["Island"]] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = {0} if interactive else set()
    game.active_player_index = 0
    game.current_turn_phase = game.current_step = "precombat_main"
    leng = Permanent(card=_CARDS["Library of Leng"])
    game._put_permanent_onto_battlefield(0, leng, None)
    game._put_permanent_onto_battlefield(0, Permanent(card=_CARDS["Plains"]), None)
    return game, leng


def _line(game: Game, fragment: str) -> int:
    return next(i for i, line in enumerate(game.log) if fragment in line)


@pytest.mark.cr("118.12a", "608.2c")
def test_a_library_of_leng_given_up_is_gone_before_the_discard():
    """Decline the first toll, pay the second with the Library itself. The
    discard is made after the sacrifice, so the Library no longer offers its
    top-of-library replacement and the discarded Shock goes to the graveyard."""
    game, leng = _table(interactive=True)
    assert game.cast_from_hand(0, "Read the Runes", x_value=2).supported
    tolls = iter([False, True])
    offered_top = []
    for _ in range(12):
        owed = settle(game, defaults=False)
        if owed is None:
            break
        if owed.kind == "optional_pay":
            game.resolve_pending_choice("optional_pay", 0, accept=next(tolls))
        elif owed.kind == "sacrifice":
            game.resolve_pending_choice(
                "sacrifice", 0, indices=None, permanent_ids=[leng.permanent_id],
            )
        elif owed.kind == "discard":
            offered_top.append(bool(owed.data.get("allow_top_of_library")))
            shock = [card.name for card in game.players[0].hand].index("Shock")
            game.resolve_pending_choice(
                "discard", 0, hand_indices=[shock], to_library=True,
            )
        else:
            raise AssertionError(f"unexpected prompt {owed.kind}")
    assert not game.stack and not game.pending_choices

    assert offered_top == [False], "the Library was already gone"
    graveyard = [card.name for card in game.players[0].graveyard]
    assert "Library of Leng" in graveyard and "Shock" in graveyard, game.log[-8:]
    assert "Shock" not in [card.name for card in game.players[0].library]
    assert _line(game, "sacrificed Library of Leng") < _line(game, "discarded Shock")
    # The spell finished only once the discard was made.
    assert _line(game, "discarded Shock") < _line(game, "Read the Runes finished resolving")


@pytest.mark.cr("118.12a", "608.2c")
def test_every_toll_is_answered_before_the_first_discard_when_nobody_is_asked():
    """The default road: the seat declines every toll (the penalty is the
    smaller loss) and discards one card per card drawn — every decline made
    before the first discard, where each discard used to follow its own
    decline."""
    game, _leng = _table(interactive=False)
    assert game.cast_from_hand(0, "Read the Runes", x_value=3).supported
    settle(game)
    caster = game.players[0]
    given_up = [card.name for card in caster.graveyard if card.name != "Read the Runes"]
    # A card the seat keeps on top under the Library (``ai_prompt_picks.
    # takes_library_top``) is given up as a discard all the same.
    kept_on_top = sum("to the top of their library" in line for line in game.log)
    assert len(given_up) + kept_on_top == 3, game.log[-10:]
    declined = [i for i, line in enumerate(game.log) if "declined Read the Runes" in line]
    discarded = [i for i, line in enumerate(game.log) if " discarded " in line]
    assert len(declined) == 3 and len(discarded) == 3, game.log[-12:]
    assert max(declined) < min(discarded), game.log[-12:]


@pytest.mark.cr("118.12a", "608.2c")
def test_two_sacrifices_and_a_discard_land_sacrifices_first():
    """Pay, decline, pay: both permanents go in the one sacrifice event the
    loop holds, and the one discard owed is made after them."""
    game, leng = _table(interactive=True)
    plains = next(p for p in game.players[0].battlefield if p.card.name == "Plains")
    assert game.cast_from_hand(0, "Read the Runes", x_value=3).supported
    tolls = iter([True, False, True])
    victims = iter([leng, plains])
    for _ in range(14):
        owed = settle(game, defaults=False)
        if owed is None:
            break
        if owed.kind == "optional_pay":
            game.resolve_pending_choice("optional_pay", 0, accept=next(tolls))
        elif owed.kind == "sacrifice":
            game.resolve_pending_choice(
                "sacrifice", 0, indices=None, permanent_ids=[next(victims).permanent_id],
            )
        elif owed.kind == "discard":
            game.resolve_pending_choice("discard", 0, hand_indices=[0], to_library=False)
        else:
            raise AssertionError(f"unexpected prompt {owed.kind}")
    assert not game.stack and not game.pending_choices
    assert game.players[0].battlefield == []
    sacrificed = [i for i, line in enumerate(game.log) if " sacrificed " in line]
    discarded = [i for i, line in enumerate(game.log) if " discarded " in line]
    assert sacrificed and len(discarded) == 1, game.log[-12:]
    assert max(sacrificed) < discarded[0], game.log[-12:]
