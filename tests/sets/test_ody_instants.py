"""Odyssey instants.

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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_duel(set_pool, hand, *, graveyard=0):
    """A two-seat game with costs off, seat 0 holding *hand* (card names from
    Odyssey) with *graveyard* cards in its graveyard."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState(
            "Caster", library=[lea["Forest"]] * 10, hand=[ody[name] for name in hand],
        ),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.players[0].graveyard.extend([lea["Grizzly Bears"]] * graveyard)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game  # _w1g2_duel


def _w1g2_put(game, seat, card):
    permanent = _w1g2_Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.tapped = False
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put


# ---------------------------------------------------------------------------
# Thermal Blast
# ---------------------------------------------------------------------------

@_w1g2_pytest.mark.parametrize("graveyard, dealt", [(0, 3), (6, 3), (7, 5), (9, 5)])
def test_thermal_blast_deals_three_or_five_never_eight(set_pool, graveyard, dealt):
    """"Thermal Blast deals 3 damage to target creature. / Threshold — Thermal
    Blast deals 5 damage **instead** if there are seven or more cards in your
    graveyard." One effect printed as two paragraphs (CR 608.2c): exactly one
    amount is dealt. The Blast itself is still on the stack as it resolves
    (CR 608.2n puts it in the graveyard last), so cast with six cards it
    deals 3 — it does not count itself."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Thermal Blast"], graveyard=graveyard)
    giant = _w1g2_put(game, 1, lea["Hill Giant"])
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])

    assert game.queue_from_hand(
        0, "Thermal Blast", target_permanent_ids=[wurm.permanent_id],
    ).supported
    assert len(game.players[0].graveyard) == graveyard, "the spell is on the stack"
    _w1g2_resolve_stack(game)
    game._settle()

    assert f"Thermal Blast dealt {dealt} damage to Craw Wurm" in game.log
    assert sum("Thermal Blast dealt" in line for line in game.log) == 1
    assert game.is_on_battlefield(wurm) is (dealt < 4)
    assert game.is_on_battlefield(giant), "one target, whichever amount"
    assert len(game.players[0].graveyard) == graveyard + 1


def test_thermal_blast_counts_a_card_that_arrives_in_response(set_pool):
    """Threshold is read as the spell resolves (CR 608.2h), not as it is
    cast: a seventh card put into the graveyard while the Blast is on the
    stack makes it 5."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Thermal Blast"], graveyard=6)
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    assert game.queue_from_hand(
        0, "Thermal Blast", target_permanent_ids=[wurm.permanent_id],
    ).supported

    game.players[0].graveyard.append(lea["Grizzly Bears"])
    _w1g2_resolve_stack(game)
    game._settle()

    assert not game.is_on_battlefield(wurm)

    game = _w1g2_duel(set_pool, ["Thermal Blast"], graveyard=7)
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    assert game.queue_from_hand(
        0, "Thermal Blast", target_permanent_ids=[wurm.permanent_id],
    ).supported
    del game.players[0].graveyard[0]
    _w1g2_resolve_stack(game)
    game._settle()
    assert game.is_on_battlefield(wurm), "six cards as it resolves: 3 damage"


def test_thermal_blast_targets_a_creature_and_nothing_else(set_pool):
    """One target, announced once for both amounts (CR 601.2c): the picker
    offers creatures only, and the cast is refused at a player, at an artifact
    and at an empty board, with the card still in hand."""
    lea = set_pool("LEA")
    card = set_pool("ODY")["Thermal Blast"]
    game = _w1g2_duel(set_pool, ["Thermal Blast"], graveyard=7)
    ring = _w1g2_put(game, 1, lea["Sol Ring"])

    assert not game.queue_from_hand(0, "Thermal Blast").supported
    assert not game.queue_from_hand(0, "Thermal Blast", target_player_index=1).supported
    assert not game.queue_from_hand(
        0, "Thermal Blast", target_permanent_ids=[ring.permanent_id],
    ).supported
    assert game.players[0].hand == [card] and game.stack == []

    bears = _w1g2_put(game, 1, lea["Grizzly Bears"])
    spec = game.cast_target_spec(0, card)
    assert [entry["name"] for entry in spec["valid_targets"]] == ["Grizzly Bears"]
    assert game.cast_from_hand(
        0, "Thermal Blast", target_permanent_ids=[bears.permanent_id],
    ).supported
    assert not game.is_on_battlefield(bears) and game.players[1].life == 20


def test_thermal_blast_does_nothing_when_its_target_is_gone(set_pool):
    """CR 608.2b: with its only target gone the spell is removed from the
    stack and neither amount is dealt to anything."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Thermal Blast"], graveyard=7)
    wurm = _w1g2_put(game, 1, lea["Craw Wurm"])
    bystander = _w1g2_put(game, 1, lea["Grizzly Bears"])
    assert game.queue_from_hand(
        0, "Thermal Blast", target_permanent_ids=[wurm.permanent_id],
    ).supported

    game.remove_from_battlefield(wurm)
    _w1g2_resolve_stack(game)
    game._settle()

    assert game.is_on_battlefield(bystander)
    assert not any("Thermal Blast dealt" in line for line in game.log)


# ---------------------------------------------------------------------------
# Demoralize
# ---------------------------------------------------------------------------

def _w1g2_attack_and_block(game, attacker, blockers):
    """Declare *attacker* for seat 0 and try each of *blockers* (seat 1) in
    one declaration; return what the declaration said."""
    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    return game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)]
        for blocker in blockers
    })  # _w1g2_attack_and_block


def test_demoralize_gives_every_creature_menace(set_pool):
    """"All creatures gain menace until end of turn." Both boards. Below
    threshold blocking is still allowed — by two or more creatures, never by
    one (CR 702.111b)."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Demoralize"], graveyard=5)
    attacker = _w1g2_put(game, 0, lea["Grizzly Bears"])
    first, second = (_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2))

    assert game.cast_from_hand(0, "Demoralize").supported
    assert len(game.players[0].graveyard) == 6
    assert all(game._has_keyword(perm, "menace") for perm in (attacker, first, second))

    alone = _w1g2_attack_and_block(game, attacker, [first])
    assert alone[0] is False, alone
    together = game.declare_blockers(1, {
        game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)]
        for blocker in (first, second)
    })
    assert together[0] is True, together


def test_demoralize_at_threshold_stops_every_block(set_pool):
    """"Threshold — If there are seven or more cards in your graveyard,
    creatures can't block this turn." An addition, not a replacement (no
    "instead"): the menace is still granted. Two creatures that could have
    double-blocked through menace may not block at all, and after cleanup
    they may again."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Demoralize"], graveyard=7)
    attacker = _w1g2_put(game, 0, lea["Grizzly Bears"])
    first, second = (_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2))

    assert game.cast_from_hand(0, "Demoralize").supported
    assert game._has_keyword(first, "menace")

    refused = _w1g2_attack_and_block(game, attacker, [first, second])
    assert refused[0] is False, refused
    assert not game.creatures_blocking(attacker)

    game.resolve_cleanup_step(0)
    assert game.blocking_restrictions_until_eot == []
    assert not game._has_keyword(first, "menace")


def test_demoralize_reads_threshold_as_it_resolves(set_pool):
    """Six cards and the Demoralize on the stack is six cards (CR 608.2n):
    cast as the seventh it grants menace and stops no block."""
    lea = set_pool("LEA")
    game = _w1g2_duel(set_pool, ["Demoralize"], graveyard=6)
    attacker = _w1g2_put(game, 0, lea["Grizzly Bears"])
    first, second = (_w1g2_put(game, 1, lea["Grizzly Bears"]) for _ in range(2))

    assert game.cast_from_hand(0, "Demoralize").supported
    assert len(game.players[0].graveyard) == 7, "in the graveyard only afterwards"

    allowed = _w1g2_attack_and_block(game, attacker, [first, second])
    assert allowed[0] is True, allowed


def test_both_threshold_instants_compile_every_printed_sentence(set_pool):
    """Neither card is supported on its first line alone: each compiles to a
    program with a conditional in it, and the condition is the graveyard
    count, with the printed seven as payload."""
    ody = set_pool("ODY")
    for name in ("Thermal Blast", "Demoralize"):
        program = _w1g2_compile(ody[name])
        assert program.supported, name
        (gate,) = [i for i in program.instructions if i.kind == "if_then"]
        assert gate.payload["condition"] == {
            "kind": "cards_in_zones",
            "count": {"zone": "graveyard", "owner": "you", "filter": {}},
            "op": "ge", "value": 7,
        }
    blast = _w1g2_compile(ody["Thermal Blast"]).instructions
    assert [i.kind for i in blast] == ["if_then"], "the 3 is an arm, not a second step"

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
