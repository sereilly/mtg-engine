"""The wire carries CR 601.2b's optional additional cost.

A field added to ``GameActionRequest`` and dropped in ``action_helpers`` is a
cast that resolves having quietly declined a price the caller announced — the
failure W1G4 recorded for the alternative cost, where five modules had to
forward the announcement or the cast fell back to the mana cost silently. This
pins the one forwarding hop that exists.

Driven through ``_queue_spell_from_request`` rather than the HTTP client because
this is about the *forwarding hop* and nothing else: one field, from the request
model to the cast path. Its docstring used to say the three cards printing an
optional additional cost were unreachable — "in Alliances, which is `measured`"
— which stopped being true at that set's promotion and was never revisited, so
a wire test went on explaining that it could not be an end-to-end one long after
it could. It can: Primitive Justice, Taste of Paradise and Undergrowth are in
``CARD_CATALOG``, and ``tests/ui/test_cast_cost_offers_ui_api.py`` drives the
picker that finally sends this field over the HTTP client.
"""

from __future__ import annotations

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from web.action_helpers import _queue_spell_from_request
from web.schemas import GameActionRequest

_ALL = {
    card.name: card
    for card in load_cards(manifest_set_path("ALL", include_measured=True))
}


def _seat_holding(card_name: str, green: int) -> tuple[Game, PlayerState]:
    caster = PlayerState(name="A", hand=[_ALL[card_name]])
    game = Game(players=[caster, PlayerState(name="B")])
    game.enforce_mana_costs = True
    caster.mana_pool["G"] = green
    game._settle()
    return game, caster


def test_the_announced_repeat_count_reaches_the_engine():
    """Two extra {1}{G} announced on the wire: charged out of the pool, and read
    back by the life gain that scales with it."""
    game, caster = _seat_holding("Taste of Paradise", green=8)
    request = GameActionRequest(
        seat=0, action="cast", card_name="Taste of Paradise",
        optional_cost_payments={"{1}{G}": 2},
    )

    result = _queue_spell_from_request(
        game, 0, "Taste of Paradise", request, x_value=None,
    )
    game._settle()

    assert result.supported, result.details
    assert caster.life == 29, "3, plus 3 for each of the two announced payments"
    assert sum(caster.mana_pool.values()) == 0, "{3}{G} plus two {1}{G}"


def test_a_request_that_names_no_payment_declines_the_offer():
    """The default has to be "declined": a client that has never heard of the
    field must not start paying for its users."""
    game, caster = _seat_holding("Taste of Paradise", green=4)
    request = GameActionRequest(
        seat=0, action="cast", card_name="Taste of Paradise",
    )

    result = _queue_spell_from_request(
        game, 0, "Taste of Paradise", request, x_value=None,
    )
    game._settle()

    assert result.supported, result.details
    assert caster.life == 23
    assert request.optional_cost_payments is None
