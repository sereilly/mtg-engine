"""The non-interactive answer to a CR 608.2d "A or B" asked at resolution.

Moving the choice from activation to resolution (W2G5) is what lets a default
read the board the opponent's response left. The stated policy stays printed
order among the free alternatives; it now skips an alternative that would
change nothing there (``ai_valuation.offered_alternative_changes_nothing``), so
an AI's Urborg aimed at a swampwalker takes swampwalk rather than the first
strike the creature does not have.
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import _nosick, resolve_stack


def _w2g5_ai_activates(set_pool, source, ability_index, victim):
    """Seat 0 (non-interactive) activates *source* at seat 1's *victim*."""
    mine = _nosick(Permanent(card=source))
    theirs = Permanent(card=victim)
    game = Game(players=[
        PlayerState(name="AI", battlefield=[mine]),
        PlayerState(name="P1", battlefield=[theirs]),
    ])
    game.enforce_mana_costs = False
    result = game.queue_permanent_ability(
        0, source.name, ability_index=ability_index,
        target_player_index=1, target_permanent_index=0,
    )
    assert result.supported, result.details
    resolve_stack(game)
    return game, theirs  # _w2g5_ai_activates


def test_urborg_takes_the_keyword_the_creature_has(set_pool):
    """"Target creature loses first strike **or** swampwalk." Bog Wraith has
    only swampwalk, so printed order's first strike would take nothing."""
    game, wraith = _w2g5_ai_activates(
        set_pool, set_pool("LEG")["Urborg"], 1, set_pool("LEA")["Bog Wraith"]
    )
    assert not game._has_keyword(wraith, "swampwalk")


def test_urborg_keeps_printed_order_when_both_would_do_something(set_pool):
    """No alternative is a no-op on a creature with neither — printed order
    stands, so the policy changes only where the first word would be wasted."""
    game, bears = _w2g5_ai_activates(
        set_pool, set_pool("LEG")["Urborg"], 1, set_pool("LEA")["Grizzly Bears"]
    )
    assert any('chose "first strike"' in line for line in game.log)


def test_walking_sponge_takes_trample_from_a_trampler(set_pool):
    """"…loses your choice of flying, first strike, or trample." The third
    word is the one the target holds."""
    game, dreadmaw = _w2g5_ai_activates(
        set_pool, set_pool("ULG")["Walking Sponge"], 0,
        set_pool("M21")["Colossal Dreadmaw"],
    )
    assert not game._has_keyword(dreadmaw, "trample")
