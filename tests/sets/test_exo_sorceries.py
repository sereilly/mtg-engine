"""Exodus sorceries.

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

Cards come from `set_pool("EXO")` / `set_cards("EXO")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G4: a counted amount that announces its own seat ---------------------

from engine import Game as _G4sGame, PlayerState as _G4sPlayer
from engine.models import Permanent as _G4sPerm
from engine.oracle import compile_card_oracle as _g4s_compile
from engine.targeting import derive_cast_spec as _g4s_cast_spec

from tests.helpers import resolve_stack as _g4s_resolve


def _g4s_creature(card, *, tapped=False):
    """A creature already on the battlefield, tapped or not."""
    permanent = _G4sPerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    permanent.tapped = tapped
    return permanent


def _g4s_duel(theirs=(), hand=(), library=()):
    """P0 with a hand and a library, P1 with a board to be counted."""
    p0 = _G4sPlayer(name="G4s-P0", life=20, hand=list(hand), library=list(library))
    p1 = _G4sPlayer(name="G4s-P1", battlefield=list(theirs), life=20)
    game = _G4sGame(players=[p0, p1])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.priority_player_index = 0
    # The sync and the refresh, in this order, close this block's helper (W1G4).
    game._sync_control()
    game._refresh_dynamic_creatures()
    return game, p0, p1


def test_w1g4_theft_of_dreams_offers_a_player_picker(set_pool):
    """"Draw a card for each tapped creature **target opponent** controls."

    The set's one ``picker_sweep`` finding: the seat is announced (CR 115.4,
    CR 601.2c) and sits inside the *counted amount* rather than inside a noun
    phrase, which is the only thing separating it from Simoon's sweep. With no
    row for it the derivation offered no picker at all, the client sent a bare
    cast and the engine refused it -- a supported card no player could cast.
    """
    theft = set_pool("EXO")["Theft of Dreams"]

    spec = _g4s_cast_spec(theft, _g4s_compile(theft))

    assert spec is not None, "the cast announces a seat and must offer a picker"
    assert spec["kind"] == "player"
    assert spec.get("opponents_only") is True


def test_w1g4_theft_of_dreams_draws_one_per_tapped_creature(set_pool):
    """And the other half of the card, which a picker finding cannot see.

    ``evaluate_count`` resolves "target opponent" off the announced seat and
    the ``tapped`` narrowing is tested per permanent -- an untapped creature on
    the same board must not be counted, which is the direction a dropped
    narrowing always fails in.
    """
    exo, lea = set_pool("EXO"), set_pool("LEA")
    theirs = [_g4s_creature(lea["Grizzly Bears"], tapped=True),
              _g4s_creature(lea["Grizzly Bears"], tapped=True),
              _g4s_creature(lea["Grizzly Bears"])]
    game, p0, _p1 = _g4s_duel(theirs=theirs, hand=[exo["Theft of Dreams"]],
                              library=[lea["Mountain"]] * 8)

    assert game.cast_from_hand(0, "Theft of Dreams", target_player_index=1).supported
    _g4s_resolve(game)

    assert len(p0.hand) == 2
