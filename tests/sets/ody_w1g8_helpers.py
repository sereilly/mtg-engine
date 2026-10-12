"""Board-building helpers shared by W1G8's sections of the Odyssey test files.

Not a test module (pytest collects ``test_*.py`` only). The group's cards span
four printed types and a driven-cards file of their own, so the five sections
import the one definition instead of each carrying a copy — ``lea_helpers``'
arrangement, for the same reason.

Every game here is headless: Odyssey is a measured set, and no path in the
running app can put one of its cards on a board (SET_PLAYBOOK.md, Phase 3).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

#: Where a card named by a W1G8 test is looked up, in order. Odyssey first, so
#: a name the set prints is always the set's own card; the rest are the sets
#: whose cards these tests stand beside the group's.
_SETS = ("ODY", "LEA", "7ED", "TMP", "ICE", "M21", "LEG", "DRK", "MMQ")


def card(set_pool, name):
    """*name* as a ``CardDefinition`` — a definition passes straight through,
    so a test may hand over a card it invented."""
    if not isinstance(name, str):
        return name
    for code in _SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(f"{name!r} is in none of {_SETS}")


def table(set_pool, hand=(), their_hand=(), interactive=(), enforce=False):
    """Two seats with Forests to draw; costs unenforced unless *enforce*;
    *interactive* names the seats that are asked rather than defaulted."""
    forest = set_pool("LEA")["Forest"]
    game = Game(players=[
        PlayerState(
            "P1", library=[forest] * 20,
            hand=[card(set_pool, name) for name in hand],
        ),
        PlayerState(
            "P2", library=[forest] * 20,
            hand=[card(set_pool, name) for name in their_hand],
        ),
    ])
    game.enforce_mana_costs = enforce
    game.interactive_seats = set(interactive)
    return game


def put(game, set_pool, seat, name, sick=False):
    """*name* onto *seat*'s battlefield through the entry path (so "enters
    with" counters are there), able to act this turn unless *sick*."""
    permanent = Permanent(card=card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def leave(game, permanent):
    """*permanent* to its controller's graveyard — "killed in response"."""
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game._permanent_to_graveyard(game.players[seat], permanent)


def settle(game):
    """Drain the stack, take every default still owed, run state-based
    actions — the end of a headless step."""
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game.check_state_based_actions()


def upkeep(game, seat=0):
    """*seat*'s upkeep step, settled."""
    game.active_player_index = seat
    game.resolve_upkeep(seat)
    settle(game)


def names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def pile(game, seat, zone="graveyard"):
    return [found.name for found in getattr(game.players[seat], zone)]


def pt(permanent):
    return (permanent.effective_power, permanent.effective_toughness)


def owed(game):
    """The prompts still owed, as ``(kind, seat)`` pairs."""
    return [(choice.kind, choice.player_index) for choice in game.pending_choices]
