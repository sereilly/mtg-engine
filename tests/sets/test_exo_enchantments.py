"""Exodus enchantments.

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


# --- W1G4: an Aura whose upkeep trigger fires on somebody else's turn -------

import pytest

from engine import Game as _G4eGame, PlayerState as _G4ePlayer
from engine.auras import attach_aura as _g4e_attach
from engine.models import Permanent as _G4ePerm

from tests.helpers import resolve_stack as _g4e_resolve


def _g4e_perm(card):
    """A permanent already on the battlefield, past its summoning sickness."""
    permanent = _G4ePerm(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _g4e_paroxysm_on_an_opponents_bear(set_pool, top_card: str):
    """Paroxysm attached to P1's Grizzly Bears, P1's library topped by *top_card*."""
    exo, lea = set_pool("EXO"), set_pool("LEA")
    aura, bear = _g4e_perm(exo["Paroxysm"]), _g4e_perm(lea["Grizzly Bears"])
    p0 = _G4ePlayer(name="G4e-P0", battlefield=[aura], life=20,
                    library=[lea["Island"]] * 4)
    p1 = _G4ePlayer(name="G4e-P1", battlefield=[bear], life=20,
                    library=[lea[top_card]] + [lea["Mountain"]] * 4)
    game = _G4eGame(players=[p0, p1])
    game.enforce_mana_costs = False
    _g4e_attach(aura, bear)
    game._sync_control()
    game._refresh_dynamic_creatures()
    game.active_player_index = 1
    # The seat whose upkeep it is, and this block's own closing pair (W1G4).
    game.priority_player_index = 1
    return game, aura, bear, p0, p1


@pytest.mark.parametrize("top_card,survives", [("Forest", False), ("Grizzly Bears", True)])
def test_w1g4_paroxysm_reads_the_enchanted_players_library(set_pool, top_card, survives):
    """"At the beginning of the upkeep of enchanted creature's controller, that
    player reveals the top card of their library. If that card is a land card,
    destroy that creature. Otherwise, it gets +3/+3 until end of turn."

    Three readings that were already built and one word that was not. The
    trigger head, "destroy that creature" and "it gets +3/+3" all bind to the
    enchanted permanent already; what was missing was the *subject-verb*
    spelling of a reveal, and "that card is …" being read as the revealed
    record rather than as an exiled one.

    The library opened is the **enchanted creature's controller's**, not the
    Aura's — which is the half a compile-time check cannot see.
    """
    game, _aura, bear, _p0, p1 = _g4e_paroxysm_on_an_opponents_bear(set_pool, top_card)

    game.resolve_upkeep(1)
    game.auto_resolve_pending_choices()
    _g4e_resolve(game)
    game.check_state_based_actions()

    assert any(f"{p1.name} revealed" in line for line in game.log), game.log
    assert game.is_on_battlefield(bear) is survives
    if survives:
        assert (bear.effective_power, bear.effective_toughness) == (5, 5)
