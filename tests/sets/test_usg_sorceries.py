"""Urza's Saga sorceries.

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

#: The three sorceries with cycling. All three reported supported before the
#: rewrite, with the keyword unclaimed — see the instants file for why that is
#: the interesting half.
_G1_CYCLING_SORCERIES = ("Lay Waste", "Hush", "Rejuvenate")


def _g1_sorcery_game(card, *, library=4):
    """Seat 0 holds *card* over a library of copies of it. Named for this block."""
    player = PlayerState(name="G1-S", hand=[card], library=[card] * library)
    return Game(players=[player, PlayerState(name="G1-T")]), player


@pytest.mark.parametrize("name", _G1_CYCLING_SORCERIES)
def test_w1g1_a_cycling_sorcery_is_discarded_for_a_card(set_pool, name):
    """Rejuvenate is the one to read: cycled, it gains no life. A rewrite that
    let the spell's own line resolve would be invisible on the other two."""
    card = set_pool("USG")[name]
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    assert [a.source_line for a in usable_activated_abilities(program, zone=HAND)] == [
        "{2}, Discard this card: Draw a card."
    ]

    game, player = _g1_sorcery_game(card)
    game.enforce_mana_costs = False
    life_before = player.life

    assert game.activate_from_hand(0, name).supported
    resolve_stack(game)

    assert [c.name for c in player.graveyard] == [name]
    assert len(player.library) == 3
    assert player.life == life_before


# --- W2G2: the graveyard as a zone — Planar Birth, Exhume, Gamble, Yawgmoth's Will ---
import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


def _g2s_cast(set_pool, name, *, seat=0):
    """Two seats, *name* in *seat*'s hand, costs off. W2G2's own sorcery helper."""
    alice, bob = PlayerState(name="G2S-A"), PlayerState(name="G2S-B")
    alice.hand = [set_pool("USG")[name]] if seat == 0 else []
    bob.hand = [set_pool("USG")[name]] if seat == 1 else []
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    return game, alice, bob


def test_w2g2_planar_birth_returns_every_seat_s_basics_tapped(set_pool):
    """"Return all basic land cards from all graveyards to the battlefield
    tapped under their owners' control."

    Four claims, one per printed word: *all graveyards* (the opponent's pile is
    swept too), *basic* (the nonbasic land stays put), *tapped*, and *their
    owners'* (each land arrives on its own owner's side, not the caster's).
    """
    pool = set_pool("USG")
    game, alice, bob = _g2s_cast(set_pool, "Planar Birth")
    alice.graveyard = [pool["Plains"], pool["Gaea's Cradle"]]
    bob.graveyard = [pool["Swamp"]]

    game.cast_from_hand(0, "Planar Birth")
    resolve_stack(game)

    mine = [p.card.name for p in game.controlled_by(0)]
    theirs = [p.card.name for p in game.controlled_by(1)]
    assert mine == ["Plains"]
    assert theirs == ["Swamp"]
    assert all(p.tapped for p in game.all_permanents())
    assert [c.name for c in alice.graveyard] == ["Gaea's Cradle", "Planar Birth"]
    assert not bob.graveyard


def test_w2g2_gamble_discards_after_the_tutor_not_before(set_pool):
    """"Search your library for a card, put that card into your hand, discard a
    card at random, then shuffle."

    The whole card is the order: the tutored card is in the hand the random
    discard reaches, which is why a hand of exactly one card — the find — must
    end up empty. A lowering that put the discard first would leave the find
    sitting in hand and the test would read as a pass with the card broken.
    """
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Gamble")
    wanted = pool["Shivan Hellkite"]
    alice.library = [wanted, wanted]

    game.cast_from_hand(0, "Gamble")
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert not alice.hand
    assert [c.name for c in alice.graveyard] == [wanted.name, "Gamble"]


def test_w2g2_gamble_leaves_a_second_card_alone(set_pool):
    """One card is discarded, not the hand: the count is data. Read over a hand
    of two so a discard that emptied it would show."""
    pool = set_pool("USG")
    game, alice, _ = _g2s_cast(set_pool, "Gamble")
    alice.hand.append(pool["Serra Zealot"])
    alice.library = [pool["Shivan Hellkite"]] * 2

    game.cast_from_hand(0, "Gamble")
    assert game.resolve_pending_choice(
        "search_library", 0, library_index=0, zone="library"
    )
    game._settle()

    assert len(alice.hand) == 1
