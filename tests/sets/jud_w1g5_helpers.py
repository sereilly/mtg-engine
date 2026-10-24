"""Board-building helpers shared by W1G5's sections of the Judgment test files.

Not a test module (pytest collects ``test_*.py`` only). The group's cards span
four printed types — three sorceries, a creature, two enchantments and an
instant — so the sections import the one definition instead of each carrying a
copy, ``ody_w1g8_helpers``' arrangement and for its reason.

Every game here is headless: Judgment is a measured set, and no path in the
running app can put one of its cards on a board (SET_PLAYBOOK.md, Phase 3).
"""

from __future__ import annotations

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack

#: Where a card named by a W1G5 test is looked up, in order. Judgment first, so
#: a name the set prints is always the set's own card.
_SETS = ("JUD", "LEA", "ODY", "TOR", "ICE", "7ED")


def card(set_pool, name):
    """*name* as a ``CardDefinition``; a definition passes straight through."""
    if not isinstance(name, str):
        return name
    for code in _SETS:
        pool = set_pool(code)
        if name in pool:
            return pool[name]
    raise KeyError(f"{name!r} is in none of {_SETS}")


def table(set_pool, hands=((), ()), interactive=(), library="Forest"):
    """One seat per entry of *hands*, each with twenty cards to draw; mana
    costs unenforced; *interactive* names the seats that are asked rather
    than defaulted."""
    filler = card(set_pool, library)
    game = Game(players=[
        PlayerState(
            f"P{seat + 1}", library=[filler] * 20,
            hand=[card(set_pool, name) for name in hand],
        )
        for seat, hand in enumerate(hands)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def put(game, set_pool, seat, name, sick=False):
    """*name* onto *seat*'s battlefield through the entry path, able to act
    this turn unless *sick*."""
    permanent = Permanent(card=card(set_pool, name))
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def settle(game):
    """Drain the stack, take every default still owed, run state-based
    actions — the end of a headless step."""
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    game.check_state_based_actions()


def owed(game, kind="optional_pay"):
    """The seats owing a *kind* prompt, in queue order."""
    return [c.player_index for c in game.pending_choices if c.kind == kind]


def answer_offers(game, answers):
    """Answer every ``optional_pay`` as it arrives — *answers* maps a seat to
    its yes/no — and return the seats asked, in the order they were asked.

    One at a time, because a chain arms the next seat's prompt only when the
    one before it answers."""
    asked = []
    for _ in range(12):
        pending = owed(game)
        if not pending:
            return asked
        seat = pending[0]
        asked.append(seat)
        assert game.confirm_optional_pay(seat, accept=bool(answers.get(seat)))
    raise AssertionError(f"offers never stopped: asked {asked}")


def names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def pile(game, seat, zone="graveyard"):
    return [found.name for found in getattr(game.players[seat], zone)]
