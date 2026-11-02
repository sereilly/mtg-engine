"""Cultural Exchange, as a seat nobody asks resolves it (kg3 `aiplay`,
part 6).

"Choose any number of creatures target player controls. Choose the same
number of creatures another target player controls. Those players exchange
control of those creatures." Both players are announced (``ai`` at kg3), and
the resolution's first pick — "any number" — was answered with none by a seat
nobody asks (the payload's ``default_none``), so the rehearsal read a cast
that exchanged nothing and the AI never cast it. The pick is now the exchange
that favours the seat (``ai_prompts.exchange_picks``): its cheapest creatures
given for the other side's dearest, while each pair gains — read off the
program (``matched_by`` / ``same_number_as``), as Strongarm Tactics' discard
order is.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.card_loader import load_catalog
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack

_CARDS = {card.name: card for card in load_catalog()}


def _table(mine, theirs, *, lands=6):
    game = Game(players=[
        PlayerState(name="AI", hand=[_CARDS["Cultural Exchange"]],
                    library=[_CARDS["Island"]] * 8),
        PlayerState(name="Opp", hand=[], library=[_CARDS["Island"]] * 8),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, list(mine) + ["Island"] * lands), (1, theirs)):
        for name in names:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat) if p.is_creature)


@pytest.mark.parametrize("roles", [[{"seat": 1}, {"seat": 0}], [{"seat": 0}, {"seat": 1}]])
def test_a_seat_nobody_asks_exchanges_its_cheapest_for_the_dearest(roles):
    """Two Grizzly Bears for a Craw Wurm and a Serra Angel, whichever player
    is named first: the caster picks its own side cheapest first and the
    other dearest first, and both pairs gain it."""
    game = _table(["Grizzly Bears", "Grizzly Bears"], ["Craw Wurm", "Serra Angel"])
    game.players[0].mana_pool.update({"U": 6})
    result = game.queue_from_hand(0, "Cultural Exchange", target_role_refs=roles)
    assert result.supported, result
    resolve_stack(game)
    assert _names(game, 0) == ["Craw Wurm", "Serra Angel"], game.log[-6:]
    assert _names(game, 1) == ["Grizzly Bears", "Grizzly Bears"]


def test_only_the_pairs_that_gain_are_exchanged():
    """A Grizzly Bears and a Serra Angel against a Craw Wurm and a Llanowar
    Elves: the Bears for the Wurm gains, the Angel for the Elves does not —
    one pair."""
    game = _table(["Grizzly Bears", "Serra Angel"], ["Craw Wurm", "Llanowar Elves"])
    game.players[0].mana_pool.update({"U": 6})
    assert game.queue_from_hand(
        0, "Cultural Exchange", target_role_refs=[{"seat": 1}, {"seat": 0}],
    ).supported
    resolve_stack(game)
    assert _names(game, 0) == ["Craw Wurm", "Serra Angel"]
    assert _names(game, 1) == ["Grizzly Bears", "Llanowar Elves"]


def test_the_ai_casts_it_and_takes_the_better_creatures():
    game = _table(["Grizzly Bears", "Grizzly Bears"], ["Craw Wurm", "Serra Angel"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Cultural Exchange", action
    action = tap_planned_lands(game, 0, action)
    assert game.cast_from_hand(0, action.card_name, **cast_announcement(action)).supported
    resolve_stack(game)
    assert _names(game, 0) == ["Craw Wurm", "Serra Angel"], game.log[-8:]


def test_nothing_is_exchanged_where_nothing_gains():
    """The caster's creatures are the dearer: no pair gains it, it chooses
    none, and the AI does not cast the spell for nothing."""
    game = _table(["Craw Wurm", "Serra Angel"], ["Grizzly Bears", "Grizzly Bears"])
    action = choose_cast_action(game, 0)
    assert action is None or action.card_name != "Cultural Exchange", action
