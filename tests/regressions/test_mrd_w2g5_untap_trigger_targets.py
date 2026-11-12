"""An untap trigger's target, for a seat nobody asks (Mirrodin wave 2, W2G5).

"Whenever a player casts a red spell, you may pay {3}. If you do, untap
target permanent." (Hematite Talisman and its four siblings.) The target is
announced as the trigger goes on the stack (CR 603.3d) and the price asked as
it resolves (CR 608.2d). ``_default_trigger_target`` took the first candidate
on the side the effect wants — the Talisman itself, untapped — and the gift
rule then tapped three lands to untap it, beside a tapped Hill Giant.

Now a tapped permanent on that side is named first
(``ai_target_sides.untap_target_order``), and where nothing there is tapped
the price is declined as buying nothing
(``ai_offer_readers.offered_untap_changes_nothing``). Provoke's untap is not
this reader's: it is aimed by the fight it compels (``ai_compelled_blocks``).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import _nosick, resolve_stack


def _card(set_pool, name):
    ice = set_pool("ICE")
    return ice[name] if name in ice else set_pool("LEA")[name]


def _table(set_pool, mine, theirs, *, opponent_hand=(), active=1, interactive=()):
    """Seat 0 holds the Talisman; seat *active* is taking its turn."""
    game = Game(players=[
        PlayerState("A", library=[_card(set_pool, "Mountain")] * 10),
        PlayerState(
            "B", hand=[_card(set_pool, name) for name in opponent_hand],
            library=[_card(set_pool, "Mountain")] * 10,
        ),
    ])
    game.enforce_mana_costs = False
    placed = {0: [], 1: []}
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _nosick(Permanent(card=_card(set_pool, name)))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            placed[seat].append(permanent)
    game.start_turn(active)
    game._settle()
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    return game, placed[0], placed[1]


def _opponent_casts_a_red_spell(game):
    game.players[1].mana_pool["R"] = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()


_LANDS = ["Mountain"] * 4


def test_the_talisman_untaps_the_tapped_creature_not_itself(set_pool):
    game, (talisman, giant, bears, *lands), _ = _table(
        set_pool, ["Hematite Talisman", "Hill Giant", "Grizzly Bears", *_LANDS],
        ["Mountain"], opponent_hand=["Lightning Bolt"],
    )
    giant.tapped = True
    _opponent_casts_a_red_spell(game)
    assert "Hematite Talisman: targets Hill Giant" in game.log
    assert not giant.tapped
    # The {3} was paid out of the lands, which are idle on another seat's turn.
    assert sum(land.tapped for land in lands) == 3
    assert not talisman.tapped and not bears.tapped


def test_a_tapped_creature_comes_before_a_tapped_land(set_pool):
    game, (_talisman, giant, *lands), _ = _table(
        set_pool, ["Hematite Talisman", "Hill Giant", *_LANDS],
        ["Mountain"], opponent_hand=["Lightning Bolt"],
    )
    lands[0].tapped = True
    giant.tapped = True
    _opponent_casts_a_red_spell(game)
    assert "Hematite Talisman: targets Hill Giant" in game.log
    assert not giant.tapped


def test_with_nothing_tapped_the_price_is_declined(set_pool):
    game, (talisman, giant, *lands), _ = _table(
        set_pool, ["Hematite Talisman", "Hill Giant", *_LANDS],
        ["Mountain"], opponent_hand=["Lightning Bolt"],
    )
    _opponent_casts_a_red_spell(game)
    assert "A declined Hematite Talisman (the untap it buys changes nothing)" in game.log
    assert not any(land.tapped for land in lands)
    assert not talisman.tapped and not giant.tapped


def test_an_interactive_seat_is_still_asked_for_the_target(set_pool):
    game, (_talisman, giant, *_lands), _ = _table(
        set_pool, ["Hematite Talisman", "Hill Giant", *_LANDS],
        ["Mountain"], opponent_hand=["Lightning Bolt"], interactive={0},
    )
    giant.tapped = True
    game.players[1].mana_pool["R"] = 1
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [(choice.kind, choice.player_index) for choice in game.pending_choices] == [
        ("trigger_target", 0)
    ]
    # Nothing has been chosen for the person: the giant is still tapped.
    assert giant.tapped
