"""Odyssey artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("ODY")` / `set_cards("ODY")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.

# ==== end W1G2 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G4 ==========================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(mine=(), theirs=(), yard=(), their_yard=(), library=(), hand=()):
    """Two seats, costs unenforced, nobody summoning sick. Cards are handed
    over as ``CardDefinition``s; the returned game has not started a turn."""
    def board(cards):
        permanents = [_W1G6Permanent(card=card) for card in cards]
        for permanent in permanents:
            permanent.metadata["summoning_sickness_turn"] = -99
        return permanents

    game = _W1G6Game(players=[
        _W1G6PlayerState(
            name="P1", battlefield=board(mine), graveyard=list(yard),
            library=list(library), hand=list(hand), life=20,
        ),
        _W1G6PlayerState(
            name="P2", battlefield=board(theirs), graveyard=list(their_yard),
            library=list(library), life=20,
        ),
    ])
    game.enforce_mana_costs = False
    return game  # _w1g6_game


def _w1g6_named(game, seat, name):
    return next(
        permanent for permanent in game.controlled_by(seat)
        if permanent.card.name == name
    )  # _w1g6_named


def _w1g6_names(game, seat):
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


def _w1g6_attack_with(game, seat, attacker):
    """*seat*'s turn, at declare attackers, with *attacker* declared."""
    game.start_turn(seat)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    slot = next(
        index for index, permanent in enumerate(game.controlled_by(seat))
        if permanent is attacker
    )
    declared = game.declare_attackers(seat, [slot])
    assert declared[0], declared  # _w1g6_attack_with


# --- Sandstone Deadfall -----------------------------------------------------
# "{T}, Sacrifice two lands and this artifact: Destroy target attacking
# creature." Three objects under one printed verb. The ingest's cost guard
# reported it charged one sacrifice for two; it was charged *none* — the whole
# clause reached the noun parser as "two lands and this artifact", was refused
# whole, and the ability cost {T}.

def test_w1g6_sandstone_deadfall_charges_two_lands_and_itself(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    cost = _w1g6_compile(ody["Sandstone Deadfall"]).activated_abilities[0].cost
    assert cost.requires_tap and cost.sacrifice_self
    assert cost.sacrifice_filter == {"type_filter": "land"}
    assert cost.sacrifice_count == 2

    game = _w1g6_game(
        mine=[ody["Sandstone Deadfall"], lea["Forest"], lea["Forest"], lea["Forest"]],
        theirs=[lea["Grizzly Bears"], lea["Hill Giant"]],
    )
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    _w1g6_attack_with(game, 1, bears)

    used = game.activate_permanent_ability(
        0, "Sandstone Deadfall", target_permanent_ids=[bears.permanent_id]
    )

    assert used.supported, used.details
    assert _w1g6_names(game, 0) == ["Forest"]
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Forest", "Forest", "Sandstone Deadfall",
    ]
    assert _w1g6_names(game, 1) == ["Hill Giant"]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g6_sandstone_deadfall_with_one_land_is_refused_with_nothing_paid(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Sandstone Deadfall"], lea["Forest"]],
        theirs=[lea["Grizzly Bears"]],
    )
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    _w1g6_attack_with(game, 1, bears)

    refused = game.activate_permanent_ability(
        0, "Sandstone Deadfall", target_permanent_ids=[bears.permanent_id]
    )

    assert not refused.supported
    assert "not enough lands" in refused.details
    assert _w1g6_names(game, 0) == ["Forest", "Sandstone Deadfall"]
    assert not _w1g6_named(game, 0, "Sandstone Deadfall").tapped
    assert _w1g6_names(game, 1) == ["Grizzly Bears"]


def test_w1g6_sandstone_deadfall_sacrifices_the_lands_its_payer_names(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Sandstone Deadfall"], lea["Forest"], lea["Island"], lea["Swamp"]],
        theirs=[lea["Grizzly Bears"]],
    )
    bears = _w1g6_named(game, 1, "Grizzly Bears")
    _w1g6_attack_with(game, 1, bears)
    island, swamp = _w1g6_named(game, 0, "Island"), _w1g6_named(game, 0, "Swamp")

    # The artifact is not a land, so naming it as one of the two is an
    # announcement that cannot be paid (CR 601.2h) — refused, not swapped.
    deadfall = _w1g6_named(game, 0, "Sandstone Deadfall")
    refused = game.activate_permanent_ability(
        0, "Sandstone Deadfall", target_permanent_ids=[bears.permanent_id],
        cost_permanent_ids=[deadfall.permanent_id],
    )
    assert not refused.supported and "cannot pay its cost" in refused.details
    assert len(list(game.controlled_by(0))) == 4

    used = game.activate_permanent_ability(
        0, "Sandstone Deadfall", target_permanent_ids=[bears.permanent_id],
        cost_permanent_ids=[island.permanent_id, swamp.permanent_id],
    )
    assert used.supported, used.details
    assert _w1g6_names(game, 0) == ["Forest"]


def test_w1g6_sandstone_deadfall_only_reaches_an_attacking_creature(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Sandstone Deadfall"], lea["Forest"], lea["Forest"]],
        theirs=[lea["Grizzly Bears"]],
    )
    game.start_turn(1)
    bears = _w1g6_named(game, 1, "Grizzly Bears")

    refused = game.activate_permanent_ability(
        0, "Sandstone Deadfall", target_permanent_ids=[bears.permanent_id]
    )

    assert not refused.supported
    assert _w1g6_names(game, 0) == ["Forest", "Forest", "Sandstone Deadfall"]

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
