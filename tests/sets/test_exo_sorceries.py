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


# --- W1G5: a buyback that is a list of costs ---
#
# Flowstone Flood's "Buyback—Pay 3 life, Discard a card at random" (CR 702.27a
# over CR 601.2b), which is the first buyback in the pool whose cost is more
# than one clause. Imports are in this block, per the header's convention.

import random as _g5s_random

from engine import Game as _G5sGame
from engine.cast_costs import (additional_costs as _g5s_costs,
                               expand_buyback_line as _g5s_expand)
from engine.card_loader import load_catalog as _g5s_catalog
from engine.models import PlayerState as _G5sPlayer, Permanent as _G5sPermanent
from tests.helpers import resolve_stack as _g5s_drain

_G5S_POOL = {card.name: card for card in _g5s_catalog()}

_G5S_BUYBACK = "pay 3 life, discard a card at random"


def _g5s_flood_game(set_pool, spares=2):
    caster = _G5sPlayer(
        name="A",
        hand=[set_pool("EXO")["Flowstone Flood"]] + [_G5S_POOL["Hill Giant"]] * spares,
    )
    victim = _G5sPlayer(name="B")
    game = _G5sGame(players=[caster, victim])
    game.enforce_mana_costs = False
    victim.battlefield.append(_G5sPermanent(card=_G5S_POOL["Mountain"]))
    game._settle()
    return game, caster, victim


def test_flowstone_flood_reads_every_clause_of_its_buyback(set_pool):
    """CR 702.27a's cost is "[cost]", and Magic prints a *list* of them behind
    the em dash — capitalising each item, because each opens where a sentence
    would.

    Both facts are asserted because both were the gap: the rewrite lowercased
    only the first letter of the whole line, so "Discard" arrived capitalised in
    the middle of a sentence whose clause table is lowercase, matched nothing,
    and took the entire cost down with it by the all-or-nothing rule. A cost
    nothing reads is a spell cast for less than it prints.
    """
    printed = set_pool("EXO")["Flowstone Flood"].oracle_text.split("\n")[0]
    assert _g5s_expand(printed) == (
        "As an additional cost to cast this spell, you may "
        "pay 3 life, discard a card at random."
    )

    (cost,) = _g5s_costs(set_pool("EXO")["Flowstone Flood"])
    assert cost.optional_key == _G5S_BUYBACK
    assert cost.pay_life == 3
    assert cost.discard_cards == 1 and cost.discard_at_random


def test_flowstone_flood_charges_both_halves_and_comes_back(set_pool):
    """The life and the discard are one offer, taken whole or declined whole
    (CR 601.2b), and taking it buys the card back (CR 702.27a)."""
    _g5s_random.seed(11)
    game, caster, victim = _g5s_flood_game(set_pool)

    result = game.queue_from_hand(
        0, "Flowstone Flood", target_player_index=1, target_permanent_index=0,
        optional_cost_payments={_G5S_BUYBACK: 1},
    )
    _g5s_drain(game)

    assert result.supported, result.details
    assert caster.life == 17
    assert len(caster.graveyard) == 1, "one card, chosen by chance"
    assert victim.battlefield == [], "Destroy target land"
    assert "Flowstone Flood" in [c.name for c in caster.hand]


def test_flowstone_flood_declined_charges_neither_half(set_pool):
    """The flag is on the *cost*, not on each clause, because the sentence it
    comes from is one offer — so a caster who declines pays no life and discards
    nothing."""
    game, caster, victim = _g5s_flood_game(set_pool)

    game.queue_from_hand(
        0, "Flowstone Flood", target_player_index=1, target_permanent_index=0,
    )
    _g5s_drain(game)

    assert caster.life == 20 and caster.graveyard[-1].name == "Flowstone Flood"
    assert victim.battlefield == [], "the spell still does what it says"
# end of the W1G5 sorceries block


# --- W1G2: a per-creature toll charged to each creature's own controller ---
#
# "For each creature, its controller sacrifices a permanent of their choice
# unless they pay {1}." The sentence iterates **creatures** and charges their
# **controllers**, so a player with three creatures answers three times — and
# the seat asked is the iteration's own object's, which is the innermost
# binding (``handlers/_common.bound_permanent``) rather than anything the firing
# event or the spell's target froze.

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_path
from engine.models import Permanent
from tests.helpers import resolve_stack

_G2S_LEA = {c.name: c for c in load_cards(manifest_set_path("LEA"))}


def _g2s_duel():
    """Seat 0 active, costs off, nobody interactive — so every offer takes its
    registered default. Its own trailing line, kept unlike any other group's."""
    game = Game(players=[PlayerState(name="Alice"), PlayerState(name="Bob")])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set()
    return game, game.players[0], game.players[1]


def _g2s_put(game, seat: int, card):
    perm = Permanent(card=card)
    perm.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(perm)
    game._sync_control()
    return perm


def test_w1g2_fade_away_charges_each_creatures_own_controller(set_pool):
    """The seat is read off the creature the iteration is on, not off the
    caster: Bob's Hill Giant costs *Bob* a permanent, and Alice's Bears costs
    Alice one."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 0, _G2S_LEA["Grizzly Bears"])
    _g2s_put(game, 1, _G2S_LEA["Hill Giant"])
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert [p.card.name for p in game.controlled_by(alice)] == []
    assert [p.card.name for p in game.controlled_by(bob)] == ["Hill Giant"]


def test_w1g2_fade_away_charges_a_seat_once_per_creature(set_pool):
    """The loop is over **creatures**, not players, so two creatures is two
    tolls on one seat — which is the whole difference between this card and
    "each player sacrifices a permanent"."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 1, _G2S_LEA["Hill Giant"])
    _g2s_put(game, 1, _G2S_LEA["Grizzly Bears"])
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    _g2s_put(game, 1, _G2S_LEA["Forest"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    # Two creatures, two sacrifices out of Bob's four permanents.
    assert len(list(game.controlled_by(bob))) == 2
    assert alice.graveyard[-1].name == "Fade Away"


def test_w1g2_fade_away_over_an_empty_board_does_nothing(set_pool):
    """CR 608.2's "as much as possible": no creature is no iteration, so
    nobody is asked and nothing is sacrificed."""
    game, alice, bob = _g2s_duel()
    _g2s_put(game, 1, _G2S_LEA["Mountain"])
    alice.hand.append(set_pool("EXO")["Fade Away"])

    assert game.cast_from_hand(0, "Fade Away").supported
    game._settle()
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    game._settle()

    assert [p.card.name for p in game.controlled_by(bob)] == ["Mountain"]


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
