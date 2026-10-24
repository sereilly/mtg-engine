"""Ring of Ma'rûf after the Judgment Wishes gave its sentence a production.

Two things changed for the shipped card, and both are pinned here as
behaviour:

* **Its line is the grammar's now.** "The next time you would draw a card this
  turn, instead put a card you own from outside the game into your hand" was a
  ``card_hooks.CARD_LINE_INSTRUCTIONS`` entry because nothing read the inner
  sentence; the Wishes' production reads it, and the next-draw-replacement
  lowering hands exactly that unnarrowed pick to the draw interceptor that
  already implements it (``replacements/draws.py``'s ``DRAW_FROM_OUTSIDE``) —
  so the card arms the same replacement, offers the same prompt, and keeps
  the client branch it has.
* **Its pick is no longer named in the log.** The card it takes goes from a
  sideboard (private, like a hand) into a hand without being revealed, so the
  table does not learn which card it was (CR 400.2, CR 701.20a) — the rule a
  library search's find already follows (``Game.find_is_public``). The line
  read "P1 put Time Walk into their hand from outside the game (Ring of
  Ma'rûf)" for every seat and spectator; the Wishes' revealed finds are named,
  and Death Wish's, like this one, is not. One mover serves both now
  (``Game.bring_card_from_outside_game``).
"""

from __future__ import annotations

from engine.card_hooks import CARD_LINE_INSTRUCTIONS
from engine.models import Permanent
from tests.helpers import CARDS_BY_NAME as _C, _game, _nosick
from engine import PlayerState


def _ring(arn_by_name):
    return next(card for name, card in arn_by_name.items() if name.startswith("Ring of Ma"))


def _ring_game(arn_by_name, *, interactive: bool):
    ring = _ring(arn_by_name)
    p1 = PlayerState(
        name="P1",
        battlefield=[_nosick(Permanent(card=ring))],
        library=[_C["Plains"]] * 5,
        sideboard=[_C["Black Lotus"], _C["Time Walk"]],
    )
    game = _game(p1, PlayerState(name="P2"))
    game.turn = 3  # past CR 103.8a's first-turn draw skip
    game.interactive_seats = {0} if interactive else set()
    assert game.queue_permanent_ability(0, ring.name).supported
    game.resolve_top_of_stack()
    return game, p1


def test_ring_of_maruf_is_no_longer_a_card_hook_and_still_arms_its_own_replacement(arn_by_name):
    game, _p1 = _ring_game(arn_by_name, interactive=True)
    assert _ring(arn_by_name).name not in CARD_LINE_INSTRUCTIONS
    assert game.outside_game_draw_replacements == {0}
    assert game.armed_draw_replacements == []


def test_ring_of_maruf_brings_its_card_in_without_naming_it(arn_by_name):
    game, p1 = _ring_game(arn_by_name, interactive=True)
    game.resolve_draw_step(0)
    assert game.pending_outside_game_draw["card_names"] == ["Black Lotus", "Time Walk"]

    assert game.confirm_outside_game_draw(0, 1) is True
    assert [card.name for card in p1.hand] == ["Time Walk"]
    assert [card.name for card in p1.sideboard] == ["Black Lotus"]
    assert len(p1.library) == 5
    assert not any("Time Walk" in line for line in game.log), game.log
    assert (
        "P1 put a card they own from outside the game into their hand "
        "(Ring of Ma'rûf)"
    ) in game.log
    assert game.reveal_events == []


def test_a_headless_ring_of_maruf_draw_is_not_named_either(arn_by_name):
    game, p1 = _ring_game(arn_by_name, interactive=False)
    game.resolve_draw_step(0)
    assert [card.name for card in p1.hand] == ["Black Lotus"]
    assert not any("Black Lotus" in line for line in game.log), game.log
