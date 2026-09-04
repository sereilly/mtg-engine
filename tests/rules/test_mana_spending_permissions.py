"""Spending mana "as though it were mana of any [type or color]" — CR 609.4b.

The class, not one card. A spending permission is not one rule at one site:
the engine asks "can this pool pay this cost?" in four places — the payment
itself, the {X} inference that decides how big an X a caster may announce
(CR 107.3), the client's affordability display, and the AI's — and each
carried its own copy of the arithmetic. Only the payment knew about the
permissions.

Two shipped cards paid for it, and the failures are silent in both directions.
**Chromatic Orrery** ("You may spend mana as though it were mana of any
color"): an {X} spell with a coloured pip inferred X = 0 off a colourless pool,
because the inference tested {R} against red mana the pool did not have — and
the spell then *cast successfully*, spending nothing and dealing nothing. The
client greyed the same card out, and an AI seat judged every coloured spell in
hand uncastable. **North Star** ("For one spell this turn, you may spend mana
as though it were mana of any type") is the same defect with a bounded
permission in it, which makes it worse: the payment path *does* know about the
grant, so the cast went through, **spent the grant** and resolved for X = 0.

They ask ``mana_payment.fungible_colors_headroom`` and its ``_types`` sibling
now. Each answers both questions at once — payable at all, and how much is
left for an X — because they are one arithmetic read twice, and a second copy
is how the readers came to disagree.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.mana_payment import fungible_colors_headroom
from web.state_view import _can_afford_with_pool


@pytest.fixture(scope="module")
def catalog():
    return {card.name: card for card in load_catalog()}


def _cost(**symbols) -> dict[str, int]:
    base = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    base.update(symbols)
    return base


def _pool(**symbols) -> dict[str, int]:
    base = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0}
    base.update(symbols)
    return base


# ---------------------------------------------------------------------------
# The arithmetic itself
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.4b")
def test_every_unit_pays_a_coloured_pip():
    """"Mana of any color" reaches every colour, and colourless is a *source*.

    The Orrery's own five {C} are the point of the card, so a colourless pool
    pays a coloured cost outright.
    """
    assert fungible_colors_headroom(_pool(C=4), _cost(R=1)) == 3
    assert fungible_colors_headroom(_pool(G=2), _cost(W=1, U=1)) == 0
    assert fungible_colors_headroom(_pool(G=1), _cost(W=1, U=1)) is None


@pytest.mark.cr("609.4b", "105.1")
def test_a_colourless_pip_still_wants_colourless():
    """Colourless is not a colour (CR 105.1) and the permission grants colours,
    so {C} in a cost is not payable by a coloured unit — and the colourless the
    cost names has to survive whatever the pips took."""
    assert fungible_colors_headroom(_pool(C=1, G=1), _cost(C=1, R=1)) == 0
    # One colourless, and the pip has nothing else to come from: the {C} is
    # unreachable even though the totals add up.
    assert fungible_colors_headroom(_pool(C=2), _cost(C=2, R=1)) is None
    assert fungible_colors_headroom(_pool(C=2, U=1), _cost(C=2, R=1)) == 0


@pytest.mark.cr("609.4b")
def test_the_headroom_is_what_an_x_can_grow_into():
    """X is generic, and every remaining unit pays generic."""
    assert fungible_colors_headroom(_pool(C=5), _cost(R=1, generic=1)) == 3
    assert fungible_colors_headroom(_pool(C=1), _cost(R=1, generic=1)) is None


# ---------------------------------------------------------------------------
# The {X} inference — the site that did not ask
# ---------------------------------------------------------------------------


def _fireball_game(catalog, *, permission: bool):
    game = Game(players=[
        PlayerState(name="P1", hand=[catalog["Fireball"]],
                    library=[catalog["Mountain"]] * 5),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = True
    caster = game.players[0]
    caster.mana_pool = _pool(C=4)
    caster.spends_mana_as_any_color = permission
    return game, caster


@pytest.mark.cr("107.3", "609.4b")
def test_x_is_inferred_under_the_permission(catalog):
    """The reported failure, as a number. Four colourless against ``{X}{R}`` is
    X = 3, not X = 0."""
    game, caster = _fireball_game(catalog, permission=True)

    assert game._infer_x_value(caster, "{X}{R}") == 3


@pytest.mark.cr("107.3", "609.4b", "601.2h")
def test_the_spell_resolves_for_the_x_the_pool_paid_for(catalog):
    """And the whole cast, because the inference is only half of it: X = 0 was
    also a cast that *succeeded*, spending nothing and dealing nothing. A
    resolution that costs four mana and does nothing is the shape this class of
    bug takes — no crash, no missing ability, just a card that quietly does
    less than it prints."""
    game, caster = _fireball_game(catalog, permission=True)

    result = game.cast_from_hand(0, "Fireball", target_player_index=1)

    assert result.supported, result.details
    assert game.players[1].life == 17
    assert sum(caster.mana_pool.values()) == 0


@pytest.mark.cr("601.2h")
def test_without_the_permission_the_cast_is_refused(catalog):
    """The other direction, which is what makes the test above mean anything:
    the pool really cannot pay ``{X}{R}`` on its own."""
    game, _caster = _fireball_game(catalog, permission=False)

    result = game.cast_from_hand(0, "Fireball", target_player_index=1)

    assert not result.supported
    assert game.players[1].life == 20


# ---------------------------------------------------------------------------
# The third reader: what the client is told it can cast
# ---------------------------------------------------------------------------


@pytest.mark.cr("609.4b")
@pytest.mark.parametrize(
    "pool, cost",
    [
        (_pool(C=1), _cost(R=1)),
        (_pool(C=3), _cost(R=1, generic=2)),
        (_pool(G=2), _cost(W=1, U=1)),
        (_pool(C=2, U=1), _cost(C=2, R=1)),
    ],
)
def test_the_affordability_display_agrees_with_the_payment(pool, cost):
    """The client's own copy of the cascade, held to the engine's answer.

    A display that says "no" where the engine says "yes" is a card the player
    cannot click, which is indistinguishable from an unimplemented card from
    the only seat that matters.
    """
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    payer = game.players[0]
    payer.spends_mana_as_any_color = True
    payer.mana_pool = dict(pool)

    offered = _can_afford_with_pool(dict(pool), cost, payer)
    paid = game._pay_mana_cost_directly(payer, dict(cost))

    assert offered is paid is True


@pytest.mark.cr("609.4b")
def test_the_affordability_display_still_refuses_what_cannot_be_paid():
    """The ratchet on the test above: a permission read as "anything goes"
    would pass it and offer every card in the hand."""
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    payer = game.players[0]
    payer.spends_mana_as_any_color = True
    payer.mana_pool = _pool(G=1)

    assert _can_afford_with_pool(_pool(G=1), _cost(W=1, U=1), payer) is False
    assert game._pay_mana_cost_directly(payer, _cost(W=1, U=1)) is False
    # And the pool is untouched by a payment that failed (CR 601.2h: partial
    # payments are not allowed).
    assert payer.mana_pool["G"] == 1


# ---------------------------------------------------------------------------
# The bounded grant: "For one spell this turn…" (North Star)
# ---------------------------------------------------------------------------


def _grant_game(catalog, pool, grant):
    game = Game(players=[
        PlayerState(name="P1", hand=[catalog["Fireball"]],
                    library=[catalog["Mountain"]] * 5),
        PlayerState(name="P2"),
    ])
    game.enforce_mana_costs = True
    caster = game.players[0]
    caster.mana_pool = dict(pool)
    if grant is not None:
        caster.spend_mana_as_though_grants = [dict(grant)]
    return game, caster


@pytest.mark.cr("107.3", "609.4b")
@pytest.mark.parametrize("any_type", [True, False])
def test_x_is_inferred_under_a_bounded_grant(catalog, any_type):
    """North Star's grant was honoured by the payment and not by the inference,
    which is the worst possible pairing: X came out 0, the cast went through
    anyway because the payment *did* know about the grant, and the grant was
    **spent** on a Fireball that dealt nothing."""
    game, caster = _grant_game(
        catalog, _pool(U=4), {"spells": 1, "any_type": any_type}
    )

    assert game._infer_x_value(caster, "{X}{R}") == 3
    result = game.cast_from_hand(0, "Fireball", target_player_index=1)

    assert result.supported, result.details
    assert game.players[1].life == 17
    assert caster.spend_mana_as_though_grants[0]["spells"] == 0


@pytest.mark.cr("107.3", "601.2h")
def test_a_grant_the_pool_did_not_need_is_not_spent(catalog):
    """The ratchet on taking the maximum of the two answers.

    Everything but a coloured pip is payable from any unit either way, so the
    direct answer and the grant's can only differ where a pip is unpayable
    without the grant — and there the direct answer is 0 and the grant was
    going to be spent regardless. A board that can pay outright keeps it.
    """
    game, caster = _grant_game(
        catalog, _pool(R=4), {"spells": 1, "any_type": True}
    )

    assert game._infer_x_value(caster, "{X}{R}") == 3
    assert game.cast_from_hand(0, "Fireball", target_player_index=1).supported

    assert game.players[1].life == 17
    assert caster.spend_mana_as_though_grants[0]["spells"] == 1


# --- W3G-solo: the permission is a static ability, so it ends with its source ---
#
# The half W3G1 reported and left. All three permissions were **stamped** on the
# seat as the source entered and never cleared, so destroying Sunglasses of Urza
# or Chromatic Orrery left the player spending mana its way for the rest of the
# game. Nothing failed and nothing looked wrong: a stamp nobody clears reads
# exactly like a permission that is still true. They are derived from the board
# now (`engine/mana_spending.py`), which is also what let Celestial Dawn's
# narrowed form be expressed at all.

from engine import Game as _msp_Game, PlayerState as _msp_PlayerState  # noqa: E402
from engine.card_loader import (load_cards as _msp_load,  # noqa: E402
                                manifest_set_path as _msp_path)
from engine.models import Permanent as _msp_Permanent  # noqa: E402
from engine.mana_spending import mana_spending_for as _msp_for  # noqa: E402


def _msp_board(card):
    perm = _msp_Permanent(card=card)
    game = _msp_Game(players=[_msp_PlayerState(name="P1", battlefield=[perm]),
                              _msp_PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game._recompute_continuous_effects()
    return game, perm


@pytest.mark.cr("609.4b", "611.3b")
def test_609_4b_a_spending_permission_ends_with_its_source():
    """CR 611.3b: a static ability applies while its source is on the
    battlefield, and not after.

    Both shipped cards, because the two were stamped through different fields
    and a fix to one would have looked like a fix to both.
    """
    lea = {card.name: card for card in _msp_load(_msp_path("LEA"))}
    m21 = {card.name: card for card in _msp_load(_msp_path("M21"))}
    for card, field in ((lea["Sunglasses of Urza"], "can_spend_white_as_red"),
                        (m21["Chromatic Orrery"], "spends_mana_as_any_color")):
        game, perm = _msp_board(card)
        assert getattr(game.players[0], field) is True, card.name
        game.remove_from_battlefield(perm)
        game._recompute_continuous_effects()
        assert getattr(game.players[0], field) is False, (
            f"{card.name}'s permission outlived it"
        )


@pytest.mark.cr("609.4b")
def test_609_4b_the_permission_is_read_off_the_line_not_the_card_name():
    """An invented artifact with Sunglasses' template works, and one naming a
    colour pair nobody printed works too — the two colour words are payload."""
    permission = _msp_for("You may spend blue mana as though it were green mana.")
    assert permission is not None
    assert permission.fungible_colors == ("U",)
    assert permission.as_colors == ("G",)
    assert permission.may_pay("U", "G") is True
    assert permission.may_pay("U", "R") is False


@pytest.mark.cr("609.4b")
def test_609_4b_only_as_though_colorless_takes_away_the_units_own_colour():
    """Celestial Dawn's second sentence, which is most of the card.

    The obvious reading — answer the equality first, because "as though it
    were" only ever adds — leaves the seat able to cast everything its own
    lands could have cast anyway, which is exactly what the restriction is for.
    """
    permission = _msp_for(
        "You may spend white mana as though it were mana of any color. "
        "You may spend other mana only as though it were colorless mana."
    )
    assert permission is not None
    assert permission.may_pay("W", "R") is True
    assert permission.may_pay("B", "B") is False, (
        "'only as though it were colorless' is a restriction, not a permission"
    )


@pytest.mark.cr("609.4b")
def test_609_4b_a_restriction_with_no_permission_in_front_of_it_refuses():
    """Half a printed line is not a card. Read alone, the restriction would
    forbid a seat every coloured pip on the strength of a sentence that grants
    nothing — so the line refuses and its card reports unsupported."""
    assert _msp_for(
        "You may spend other mana only as though it were colorless mana."
    ) is None


@pytest.mark.cr("609.4b", "601.2h")
def test_601_2h_the_matching_is_exact_not_greedy():
    """CR 601.2h asks what a player is *able* to do, so the assignment of pool
    units to coloured pips has to be a matching rather than a first-fit walk:
    spend the white on the red pip and the white pip starves, on a pool that
    could have paid."""
    from engine.mana_payment import spend_under_permissions

    sunglasses = (_msp_for("You may spend white mana as though it were red mana."),)
    cost = {"W": 1, "R": 1, "generic": 0}
    assert spend_under_permissions({"W": 1, "R": 1}, cost, sunglasses) is not None
    assert spend_under_permissions({"W": 1}, cost, sunglasses) is None
