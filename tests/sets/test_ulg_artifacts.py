"""Urza's Legacy artifacts.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("ULG")` / `set_cards("ULG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: a quantity the sentence that spends it produced ---
#
# Angel's Trumpet — "All creatures have vigilance. At the beginning of each
# player's end step, tap all untapped creatures that player controls that
# didn't attack this turn. This artifact deals damage to the player equal to
# the number of creatures tapped this way."
#
# The card read *supported* before this round on its vigilance line alone: the
# trigger compiled an ability part with no instruction behind it, which is what
# `support_report --hollow-lines` and `parse_coverage --set ULG` were both
# reporting about the same sentence.

from engine import Game, PlayerState
from engine.models import Permanent

from tests.helpers import resolve_stack as _g1a_resolve


def _g1a_table(set_pool, *, mine=(), theirs=()):
    """Angel's Trumpet under seat 0, the named creatures on each board.

    ``_g1a_`` prefixed and ending on ``return game, game.players[0], game.players[1]``
    — SET_PLAYBOOK.md's note about a union splicing one helper onto another.
    """
    seat0 = PlayerState(
        name="G1A-A",
        battlefield=[Permanent(card=set_pool("ULG")["Angel's Trumpet"])] + list(mine),
    )
    seat1 = PlayerState(name="G1A-B", battlefield=list(theirs))
    game = Game(players=[seat0, seat1])
    game.enforce_mana_costs = False
    return game, game.players[0], game.players[1]


def _g1a_bear(set_pool, *, tapped=False, attacked=False):
    """One Grizzly Bears in the state the sentence's two narrowings care about.
    Ends on ``return bear`` so no union can graft another helper onto it."""
    bear = Permanent(card=set_pool("LEA")["Grizzly Bears"])
    bear.tapped = tapped
    if attacked:
        bear.metadata["attacked_this_turn"] = True
    return bear


def test_g1_angels_trumpet_damages_for_what_it_tapped(set_pool):
    """CR 603.10 freezes whose end step this is; the damage is the count the tap
    in front of it recorded, not the board's tally of tapped creatures."""
    game, mine, theirs = _g1a_table(
        set_pool,
        mine=[_g1a_bear(set_pool)],
        theirs=[_g1a_bear(set_pool), _g1a_bear(set_pool)],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 18, "two untapped creatures tapped, two damage"
    assert mine.life == 20, "it is not their end step"
    assert all(p.tapped for p in game.controlled_by(1))
    assert not any(
        p.tapped for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"
    )


def test_g1_angels_trumpet_counts_only_the_creatures_it_tapped(set_pool):
    """"…tapped **this way**." One of the three was already tapped and one
    attacked, so the board holds three tapped creatures afterwards and the
    damage is one — the board's count is the wrong number, always the larger."""
    game, mine, theirs = _g1a_table(
        set_pool,
        theirs=[
            _g1a_bear(set_pool),
            _g1a_bear(set_pool, tapped=True),
            _g1a_bear(set_pool, attacked=True),
        ],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 19
    assert len([p for p in game.controlled_by(1) if p.tapped]) == 2, (
        "the attacker keeps its vigilance-untapped state and is not tapped here"
    )


def test_g1_angels_trumpet_deals_nothing_when_it_taps_nothing(set_pool):
    """A seat whose only creature attacked has nothing the sweep may turn, so
    the count is zero and CR 120.8 makes that no damage at all."""
    game, mine, theirs = _g1a_table(
        set_pool, theirs=[_g1a_bear(set_pool, attacked=True)],
    )
    game.active_player_index = 1

    game.resolve_end_step(1)
    _g1a_resolve(game)
    game._settle()

    assert theirs.life == 20


def test_g1_angels_trumpet_still_grants_vigilance(set_pool):
    """The card's other line, asserted because it was the only reason the card
    reported supported before this round — a change to the trigger must not have
    taken it with it."""
    game, _mine, _theirs = _g1a_table(set_pool, mine=[_g1a_bear(set_pool)])
    game._settle()

    bear = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert game._has_keyword(bear, "vigilance"), (
        "CR 613 layer 6, which is the only accessor that sees a board-wide grant"
    )
