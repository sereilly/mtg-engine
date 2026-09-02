"""Paying an upkeep cost from the board — CR 605.3a for a cost asked "in the
middle of resolving an ability".

An upkeep's "unless you pay {U}" is collected inside the trigger's resolution,
with no priority window in which the payer could tap for mana first; CR 605.3a
is what lets them tap *while* paying. The engine's answer is
``mana_payment.plan_payment``, the same one every "you may pay" and every
counterspell toll asks — and until this file the upkeep pair asked it only for
the **generic** part, covering the coloured pips from floating mana alone. So
every coloured upkeep in the pool (Stasis, Glaciers, Demonic Hordes, eleven
cumulative upkeeps, both FEM Chants) was sacrificed on the first upkeep of an AI
or headless game however many of the right lands stood untapped, and the three
handlers that never asked the pair at all honoured a human "pay" against an
empty pool for free.

These drive the real upkeep step over real pool cards, because the bug was in
which question the step asked rather than in any one card.
"""

from __future__ import annotations

import pytest

from engine import Game
from engine.models import Permanent, PlayerState


def _board(catalog_by_name, *names: str, pool: dict[str, int] | None = None):
    """Seat 0 holding *names* on an upkeep of its own, with real costs on.

    The first permanent is the subject; the rest are its lands. Returned as
    ``(game, seat, subject, lands)`` so a test can read the tapped state off
    the very objects it placed — the step empties the pool when it ends
    (CR 500.4), so a tapped land is the observable that survives.
    """
    perms = [Permanent(card=catalog_by_name[name]) for name in names]
    p1 = PlayerState(
        name="P1", battlefield=perms, mana_pool=dict(pool or {}),
        library=[catalog_by_name["Plains"]] * 5, life=20,
    )
    p2 = PlayerState(name="P2", library=[catalog_by_name["Plains"]] * 5, life=20)
    game = Game(players=[p1, p2])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game.turn = 2
    game._sync_control()
    return game, p1, perms[0], perms[1:]


def _on_board(game: Game, perm: Permanent) -> bool:
    return any(other is perm for other in game.all_permanents())


def _tapped(lands: list[Permanent]) -> list[str]:
    return [land.card.name for land in lands if land.tapped]


@pytest.mark.cr("605.3a", "503.1a")
def test_605_3a_a_coloured_upkeep_cost_is_paid_by_tapping_a_land(catalog_by_name):
    """Stasis, "sacrifice unless you pay {U}", an Island untapped and nothing
    floating: the Island is tapped and Stasis stays."""
    game, _seat, stasis, lands = _board(catalog_by_name, "Stasis", "Island")

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert _on_board(game, stasis), game.log
    assert _tapped(lands) == ["Island"]


@pytest.mark.cr("605.3a", "601.2h")
def test_605_3a_a_land_that_cannot_make_the_colour_does_not_pay(catalog_by_name):
    """The same Stasis over a Plains alone: {U} is unpayable, so the card is
    sacrificed and the Plains is left untapped — a land tapped for a cost it
    cannot cover would be a cost charged for nothing."""
    game, _seat, stasis, lands = _board(catalog_by_name, "Stasis", "Plains")

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert not _on_board(game, stasis), game.log
    assert _tapped(lands) == []


@pytest.mark.cr("605.3a")
def test_605_3a_two_coloured_pips_are_matched_against_the_lands(catalog_by_name):
    """Glaciers' {W}{U} over an Island and a Tundra.

    A greedy pass that spent the Tundra on the {U} would strand the {W} and
    report the cost unpayable; the matching finds Island→{U}, Tundra→{W}.
    """
    game, _seat, glaciers, lands = _board(catalog_by_name, "Glaciers", "Island", "Tundra")

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert _on_board(game, glaciers), game.log
    assert sorted(_tapped(lands)) == ["Island", "Tundra"]


@pytest.mark.cr("605.3a")
def test_605_3a_floating_mana_is_spent_before_a_land_is_tapped(catalog_by_name):
    """With {U} already in the pool the Island is left alone: floating mana is
    spent-in-advance and a land kept untapped is worth more."""
    game, seat, stasis, lands = _board(catalog_by_name, "Stasis", "Island", pool={"U": 1})

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert _on_board(game, stasis), game.log
    assert _tapped(lands) == []
    assert seat.mana_pool.get("U", 0) == 0


@pytest.mark.cr("605.3a", "702.24a")
def test_605_3a_a_coloured_cumulative_upkeep_taps_a_land(catalog_by_name):
    """Cumulative upkeep goes through the same pair, so Illusionary Wall's
    first {U} is paid off an untapped Island rather than sacrificing the Wall
    on the turn it is cast."""
    game, _seat, wall, lands = _board(catalog_by_name, "Illusionary Wall", "Island")

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert _on_board(game, wall), game.log
    assert _tapped(lands) == ["Island"]


@pytest.mark.cr("605.3a")
def test_605_3a_an_untap_toll_taps_the_lands_that_pay_it(catalog_by_name):
    """Island Fish Jasconius, "you may pay {U}{U}{U}. If you do, untap it":
    three Islands pay, and the fish untaps for the turn."""
    game, _seat, fish, lands = _board(
        catalog_by_name, "Island Fish Jasconius", "Island", "Island", "Island"
    )
    fish.tapped = True

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert not fish.tapped, game.log
    assert len(_tapped(lands)) == 3


@pytest.mark.cr("605.3a", "601.2h")
def test_601_2h_a_human_accept_is_refused_when_the_board_cannot_cover_it(catalog_by_name):
    """Force of Nature, "unless you pay {G}{G}{G}{G}, it deals 8 damage to
    you": a human who chooses to pay with one Forest and an empty pool has not
    paid, and takes the 8 — choosing "pay" is not paying."""
    game, seat, _force, lands = _board(catalog_by_name, "Force of Nature", "Forest")

    game.resolve_upkeep(0, human_choices={"Force of Nature": True})
    game.auto_resolve_pending_choices()

    assert seat.life == 12, game.log
    assert _tapped(lands) == []


@pytest.mark.cr("605.3a")
def test_605_3a_a_handler_with_its_own_pool_read_now_taps_lands(catalog_by_name):
    """Demonic Hordes' {B}{B}{B} went through a hand-rolled pool read rather
    than the shared pair, so three untapped Swamps could not pay it and the
    Hordes tapped and ate a land every upkeep. Same seam, same answer."""
    game, seat, hordes, lands = _board(
        catalog_by_name, "Demonic Hordes", "Swamp", "Swamp", "Swamp"
    )

    game.resolve_upkeep(0)
    game.auto_resolve_pending_choices()

    assert not hordes.tapped, game.log
    assert len(_tapped(lands)) == 3
    assert all(_on_board(game, land) for land in lands), "no land was sacrificed"
