"""Planeshift creatures.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G6: colour ---
# Becoming a colour, being one, sharing one, and protection from one. Colour is
# read through CR 613's layer 5 everywhere below (`Game._effective_colors`),
# never off the printed card: half of these tests change a colour mid-game and
# ask the card again.
import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine import targeting as _w1g6_targeting
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_card(set_pool, name):
    """*name* from Planeshift, else Invasion, else Alpha."""
    for code in ("PLS", "INV", "LEA"):
        if name in set_pool(code):
            return set_pool(code)[name]
    raise KeyError(name)  # _w1g6_card (creatures)


def _w1g6_table(set_pool, mine=(), theirs=(), *, mana=False, interactive=(0,)):
    """Seat 0 holds *mine* and seat 1 *theirs*, nothing summoning-sick, on
    seat 0's turn. Returns the game and the two lists of permanents."""
    w1g6_game = _W1G6Game(players=[
        _W1G6PlayerState(name="A", life=20), _W1G6PlayerState(name="B", life=20),
    ])
    w1g6_game.enforce_mana_costs = mana
    w1g6_game.interactive_seats = set(interactive)
    w1g6_game.active_player_index = 0
    w1g6_sides = []
    for seat, names in ((0, mine), (1, theirs)):
        side = []
        for name in names:
            perm = _W1G6Permanent(card=_w1g6_card(set_pool, name))
            w1g6_game._put_permanent_onto_battlefield(seat, perm, None)
            perm.metadata["summoning_sickness_turn"] = -99
            side.append(perm)
        w1g6_sides.append(side)
    return w1g6_game, w1g6_sides[0], w1g6_sides[1]  # _w1g6_table (creatures)


def _w1g6_colors(game, perm):
    return sorted(game._effective_colors(perm))  # _w1g6_colors (creatures)


def _w1g6_names(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))  # _w1g6_names (creatures)


def _w1g6_ability(card, index=0):
    """The *index*-th activated ability of *card* and the picker spec the
    compiled program derives for it."""
    w1g6_ability = _w1g6_compile(card).activated_abilities[index]
    return w1g6_ability, _w1g6_targeting.derive_activation_spec(w1g6_ability)  # _w1g6_ability


def test_w1g6_disciple_of_kangee_gives_one_target_flying_and_blue_for_a_turn(set_pool):
    """"{U}, {T}: Target creature gains flying and becomes blue until end of
    turn." One target, two things said about it, one window: the red Giant
    flies and is blue (CR 105.3 — blue *instead of* red), the Bears beside it
    are untouched, the Disciple is tapped and {U} is spent, and at cleanup the
    Giant is a red ground creature again."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"], mana=True,
    )
    disciple, bears = mine
    giant = theirs[0]
    _ability, spec = _w1g6_ability(disciple.card)
    assert spec == {"kind": "creature"}

    assert not game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported, "no {U}, no ability"
    game.players[0].mana_pool["U"] = 1
    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[giant.permanent_id],
    ).supported
    assert disciple.tapped and game.players[0].mana_pool["U"] == 0
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, giant) == ["U"] and game._has_keyword(giant, "flying")
    assert _w1g6_colors(game, bears) == ["G"] and not game._has_keyword(bears, "flying")

    game.resolve_cleanup_step(0)
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")


def test_w1g6_disciple_of_kangee_may_be_aimed_at_its_controllers_own_creature(set_pool):
    """The id names a battlefield as well as an object: aimed at the Bears on
    its own side, the Bears — not the opponent's Giant — fly and turn blue."""
    game, mine, theirs = _w1g6_table(
        set_pool, ["Disciple of Kangee", "Grizzly Bears"], ["Hill Giant"],
    )
    bears, giant = mine[1], theirs[0]

    assert game.queue_permanent_ability(
        0, "Disciple of Kangee", ability_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    _w1g6_resolve_stack(game)

    assert _w1g6_colors(game, bears) == ["U"] and game._has_keyword(bears, "flying")
    assert _w1g6_colors(game, giant) == ["R"] and not game._has_keyword(giant, "flying")
