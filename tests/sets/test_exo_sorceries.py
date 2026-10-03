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
    # Tapped, so the toll cannot be paid: a seat nobody asks pays a toll out
    # of its untapped lands (W2G4, `ai_policy.optional_pay_may_tap_lands`),
    # and this test is about whose permanent goes when it is not paid.
    _g2s_put(game, 1, _G2S_LEA["Mountain"]).tapped = True
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
    # Tapped for the reason the test above gives: unpaid tolls are the subject.
    _g2s_put(game, 1, _G2S_LEA["Mountain"]).tapped = True
    _g2s_put(game, 1, _G2S_LEA["Forest"]).tapped = True
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


# --- W2G1: keep a described set, sacrifice the rest ---

import pytest as _w2g1_pytest  # noqa: E402
from engine import Game as _W2G1_Game, PlayerState as _W2G1_PlayerState  # noqa: E402
from engine.models import Permanent as _W2G1_Permanent  # noqa: E402
from tests.helpers import resolve_stack as _w2g1_drain  # noqa: E402


def _w2g1_board(pool, lea, *names):
    return [_W2G1_Permanent(card=(pool.get(n) or lea[n])) for n in names]


def _w2g1_cataclysm_game(set_pool, mine, theirs, interactive=()):
    """Cataclysm in seat 0's hand, with both seats' boards spelled out by name.

    LEA supplies the permanents because Exodus is `measured` and its own cards
    are not what these tests are about: what is being checked is which *types*
    survive, and a board of Alpha basics, Moxen and bears says that in the
    fewest moving parts.
    """
    pool = set_pool("EXO")
    lea = set_pool("LEA")
    game = _W2G1_Game(players=[
        _W2G1_PlayerState(
            name="P1", hand=[pool["Cataclysm"]],
            battlefield=_w2g1_board(pool, lea, *mine),
        ),
        _W2G1_PlayerState(
            name="P2", battlefield=_w2g1_board(pool, lea, *theirs),
        ),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game


def _w2g1_survivors(game, seat):
    return sorted(perm.card.name for perm in game.controlled_by(seat))


def _w2g1_cast_and_settle(game, name="Cataclysm"):
    assert game.cast_from_hand(0, name).supported
    _w2g1_drain(game)
    game.auto_resolve_pending_choices()
    game._settle()


def test_cataclysm_leaves_each_seat_one_of_each_named_type(set_pool):
    """"Each player chooses from among the permanents they control an artifact,
    a creature, an enchantment, and a land, then sacrifices the rest."

    Both seats, and both halves of the sentence: what is kept is one of each of
    the four printed types, and what goes is everything else that seat
    controls. The opponent's board is one of each already, so nothing of theirs
    is taken — which is the check that the complement is per-seat rather than
    board-wide.
    """
    game = _w2g1_cataclysm_game(
        set_pool,
        mine=["Black Lotus", "Mox Pearl", "Grizzly Bears", "Hurloon Minotaur",
              "Holy Strength", "Forest", "Mountain"],
        theirs=["Icy Manipulator", "Savannah Lions", "Forest"],
    )

    _w2g1_cast_and_settle(game)

    assert _w2g1_survivors(game, 0) == [
        "Black Lotus", "Forest", "Grizzly Bears", "Holy Strength",
    ], game.log
    assert _w2g1_survivors(game, 1) == [
        "Forest", "Icy Manipulator", "Savannah Lions",
    ], game.log


@_w2g1_pytest.mark.parametrize(
    "mine, kept",
    [
        # One artifact creature fills one slot and only one: the other three
        # have nothing left to take.
        (["Clockwork Beast"], ["Clockwork Beast"]),
        # Two of them fill the artifact slot *and* the creature slot, which a
        # per-type count ("sacrifice all but one artifact, all but one
        # creature") would get wrong in the destructive direction.
        (["Clockwork Beast", "Clockwork Beast"],
         ["Clockwork Beast", "Clockwork Beast"]),
        # The pair a greedy walk gets wrong: spend the artifact slot on the
        # artifact *creature* and the plain artifact has nowhere to go. CR 609.3
        # says the effect does as much as it can, so both survive.
        (["Clockwork Beast", "Black Lotus"], ["Black Lotus", "Clockwork Beast"]),
        # And the same pair with a third permanent that competes for neither.
        (["Clockwork Beast", "Black Lotus", "Forest", "Mountain"],
         ["Black Lotus", "Clockwork Beast", "Forest"]),
    ],
)
def test_cataclysm_keeps_as_many_as_the_board_allows(set_pool, mine, kept):
    """An artifact creature can fill the artifact slot or the creature slot and
    not both (CR 608.2d), so how many survive is a **maximum matching** rather
    than a per-type count.

    The third row is the one that separates the two implementations: greedy
    assignment keeps one permanent where the card lets the player keep two, and
    it fails silently and against the player.
    """
    game = _w2g1_cataclysm_game(set_pool, mine=mine, theirs=[])

    _w2g1_cast_and_settle(game)

    assert _w2g1_survivors(game, 0) == kept, game.log


def test_cataclysm_asks_an_interactive_seat_and_refuses_a_short_answer(set_pool):
    """The prompt is a decision the seat owes, and the answer is checked.

    Keeping fewer than the board allows is not one of the answers — it would
    sacrifice permanents the card said were safe — so a short list leaves the
    prompt owed rather than being taken as a partial keep. The full answer is
    honoured exactly as sent, which is the other half: the *player* picks, not
    the engine's default.
    """
    game = _w2g1_cataclysm_game(
        set_pool,
        mine=["Black Lotus", "Mox Pearl", "Grizzly Bears", "Forest", "Mountain"],
        theirs=[],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Cataclysm").supported
    game.resolve_top_of_stack()

    owed = [choice for choice in game.pending_choices if choice.kind == "keep_permanents"]
    assert [choice.player_index for choice in owed] == [0]

    by_name = {perm.card.name: game.permanent_id_of(perm) for perm in game.controlled_by(0)}
    assert not game.confirm_keep_permanents(0, [by_name["Black Lotus"]])
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]

    assert game.confirm_keep_permanents(
        0, [by_name["Mox Pearl"], by_name["Grizzly Bears"], by_name["Mountain"]]
    )
    assert _w2g1_survivors(game, 0) == ["Grizzly Bears", "Mountain", "Mox Pearl"]


def test_cataclysm_refuses_a_keep_two_slots_cannot_hold(set_pool):
    """Two plain artifacts both want the one artifact slot.

    The count is right — the board allows two keeps, one artifact and one land —
    and the *assignment* is not, which is a different question and the one a
    ceiling alone cannot ask.
    """
    game = _w2g1_cataclysm_game(
        set_pool, mine=["Black Lotus", "Mox Pearl", "Forest"], theirs=[],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Cataclysm").supported
    game.resolve_top_of_stack()

    by_name = {perm.card.name: game.permanent_id_of(perm) for perm in game.controlled_by(0)}
    assert not game.confirm_keep_permanents(
        0, [by_name["Black Lotus"], by_name["Mox Pearl"]]
    )
    assert [c.kind for c in game.pending_choices] == ["keep_permanents"]


def test_cataclysm_takes_nothing_from_a_seat_with_an_empty_board(set_pool):
    """CR 101.3: an empty pool has an empty complement, so a seat controlling
    nothing is not asked and nothing is logged as happening to them."""
    game = _w2g1_cataclysm_game(set_pool, mine=["Forest", "Mountain"], theirs=[])

    _w2g1_cast_and_settle(game)

    assert _w2g1_survivors(game, 1) == []
    assert not any("P2 kept" in line for line in game.log), game.log


def test_cataclysm_refuses_a_keep_from_another_seats_battlefield(set_pool):
    """CR 701.21a: a player cannot sacrifice a permanent they do not control, so
    the pool a seat chooses from is its own board and no other.

    The opponent's creature is a legal *type* for the creature slot and is still
    refused, which is the check that the pool is scoped by seat rather than by
    the noun phrase alone.
    """
    game = _w2g1_cataclysm_game(
        set_pool, mine=["Grizzly Bears", "Forest"], theirs=["Savannah Lions"],
        interactive=(0,),
    )
    assert game.cast_from_hand(0, "Cataclysm").supported
    game.resolve_top_of_stack()

    theirs = next(game.permanent_id_of(p) for p in game.controlled_by(1))
    mine = next(
        game.permanent_id_of(p) for p in game.controlled_by(0)
        if p.card.name == "Forest"
    )
    assert not game.confirm_keep_permanents(0, [theirs, mine])


def test_cataclysm_compiles_to_one_instruction_carrying_pool_and_slots(set_pool):
    """The pool and the slots are separate payload keys and both are required.

    A slot list alone cannot say what "the rest" is — Cataclysm's four keeps
    name four types and its complement is *every* permanent that seat controls —
    and a pool alone cannot say what may be kept. Read off the compiled program
    because that is the only place the pair is visible; a kind-only assertion
    would pass with either half missing.
    """
    from engine.oracle import compile_card_oracle

    program = compile_card_oracle(set_pool("EXO")["Cataclysm"])
    assert program.supported
    assert [i.kind for i in program.instructions] == ["keep_chosen_sacrifice_rest"]
    payload = program.instructions[0].payload
    assert payload["pool"] == {}
    assert payload["who"] == "each_player"
    assert [(s["count"], s["filter"]["type_filter"]) for s in payload["slots"]] == [
        (1, "artifact"), (1, "creature"), (1, "enchantment"), (1, "land"),
    ]


def test_a_keep_list_with_no_complement_behind_it_refuses_the_line():
    """The tail is required in full.

    "Each player chooses an artifact they control" without "sacrifices the rest"
    is a different sentence and keeps the reading it had; and several slots with
    no printed pool refuses outright, because "the rest" would then name either
    the union of the nouns or the whole board and this production would be
    guessing. Both are checked here because a production that ends in a
    catch-all has to refuse what it cannot read.
    """
    from engine.grammar import parse_line
    from engine.grammar.errors import GrammarError
    from engine.grammar import ast as _w2g1_ast

    kept = parse_line(
        "Each player chooses two creatures they control and sacrifices the rest."
    )
    assert isinstance(kept.statement, _w2g1_ast.KeepChosenSacrificeRest)

    # The bare pick keeps its own reading rather than becoming a keep.
    bare = parse_line("Defending player chooses an untapped creature they control.")
    assert isinstance(bare.statement, _w2g1_ast.ChoosePermanent)

    with _w2g1_pytest.raises(GrammarError):
        parse_line(
            "Each player chooses an artifact and a creature, then sacrifices the rest."
        )
