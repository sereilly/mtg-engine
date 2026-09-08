"""Urza's Saga instants.

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

Cards come from `set_pool("USG")` / `set_cards("USG")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: cycling (CR 702.29) ---
import pytest

from engine import Game, PlayerState
from engine.activation_zones import HAND
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The six instants with cycling. Five of them (all but Brand) were reported
#: **supported** before the CR 702.29a rewrite existed — a spell is supported
#: when any of its lines is, and their effect line always compiled — so the
#: keyword sat in `parse_coverage.py --set USG` as an unclaimed line and in no
#: other instrument at all. That is the population a refusal census cannot
#: reach, and it is why these tests cycle the card in a game rather than
#: asserting that it compiles.
_G1_CYCLING_INSTANTS = ("Clear", "Rescind", "Expunge", "Brand", "Scrap", "Lull")


def _g1_spell_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it."""
    player = PlayerState(name="G1-A", hand=[card], library=[card] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name", _G1_CYCLING_INSTANTS)
def test_w1g1_a_cycling_instant_is_discarded_for_a_card(set_pool, name):
    """Cycling replaces casting the spell, not part of it: the card goes to the
    graveyard, one card is drawn, and the printed effect never happens."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]
    # An instant is never on the battlefield, so it has no battlefield abilities
    # to confuse with the cycling one.
    assert usable_activated_abilities(program) == []

    game, player = _g1_spell_game(card)
    opponent_board = [p.card.name for p in game.players[1].battlefield]

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert [c.name for c in player.hand] == [name]      # the card drawn
    assert len(player.library) == 3
    assert [p.card.name for p in game.players[1].battlefield] == opponent_board
