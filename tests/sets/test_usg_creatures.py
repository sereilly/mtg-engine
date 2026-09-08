"""Urza's Saga creatures.

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
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities

from tests.helpers import resolve_stack

#: The eight creatures printing cycling. Seven of them were reported
#: "creature text too complex" on the keyword line before the CR 702.29a
#: rewrite; Wild Dogs was refused for its upkeep trigger instead and still is
#: (that line belongs to another group), which is why it is not here.
_G1_CYCLING_CREATURES = (
    "Disciple of Grace",
    "Disciple of Law",
    "Shimmering Barrier",
    "Drifting Djinn",
    "Pendrell Drake",
    "Sandbar Merfolk",
    "Sandbar Serpent",
)


def _g1_creature_game(card, *, library=4):
    """Seat 0 holds *card* and has a library worth drawing from."""
    filler = card
    player = PlayerState(name="G1-A", hand=[card], library=[filler] * library)
    game = Game(players=[player, PlayerState(name="G1-B")])
    game.enforce_mana_costs = False
    return game, player


@pytest.mark.parametrize("name", _G1_CYCLING_CREATURES)
def test_w1g1_a_cycling_creature_cycles_from_hand_and_not_from_play(set_pool, name):
    """A creature with cycling is two different cards depending on the zone.

    In hand it is "{2}: draw a card"; on the battlefield it is a creature with
    no activated ability at all (CR 702.29b — the ability exists there, and
    CR 113.6j says it does not *function* there). Getting the second half wrong
    is not a missing feature: it is a free repeatable draw, on eight cards.
    """
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program)] == []
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_creature_game(card)
    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)
    assert [c.name for c in player.graveyard] == [name]
    assert len(player.hand) == 1

    game, player = _g1_creature_game(card)
    player.hand.clear()
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    player.battlefield.append(perm)
    library_before = len(player.library)
    refusal = game.activate_permanent_ability(0, name)
    assert refusal.supported is False
    assert "113.6" in refusal.details, refusal.details
    assert len(player.library) == library_before
    assert player.graveyard == []


def test_w1g1_the_keyword_creatures_keep_the_keywords_beside_it(set_pool):
    """Cycling is printed *under* a keyword line on four of them, so the rewrite
    has to leave the other lines alone. Disciple of Grace's protection from
    black and Shimmering Barrier's defender + first strike are what a rewrite
    that consumed too much would take away."""
    pool = set_pool("USG")
    assert compile_card_oracle(pool["Disciple of Grace"]).static_lines == (
        "protection from black",
    )
    assert compile_card_oracle(pool["Disciple of Law"]).static_lines == (
        "protection from red",
    )
    barrier = compile_card_oracle(pool["Shimmering Barrier"])
    assert set(barrier.static_lines) == {"defender", "first strike"}
