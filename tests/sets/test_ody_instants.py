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

import pytest as _w1g4_pytest

from engine import Game as _w1g4_Game, PlayerState as _w1g4_PlayerState
from engine.models import Permanent as _w1g4_Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import _mk_card as _w1g4_mk_card
from tests.helpers import resolve_stack as _w1g4_resolve_stack


def _w1g4_duel(set_pool, *, hand0=(), hand1=(), gy0=(), gy1=(), lib0=(),
               lib1=(), bf0=(), bf1=()):
    """A two-seat game with costs off, built from card names.

    Odyssey and Alpha in one pool: the Bursts count their own name, and what
    they are aimed at is furniture.
    """
    pool = {**set_pool("LEA"), **set_pool("ODY")}
    seats = [
        _w1g4_PlayerState(
            name=f"P{seat}", life=20,
            hand=[pool[n] for n in hand], graveyard=[pool[n] for n in gy],
            library=[pool[n] for n in lib],
        )
        for seat, (hand, gy, lib) in enumerate(
            ((hand0, gy0, lib0), (hand1, gy1, lib1))
        )
    ]
    game = _w1g4_Game(players=seats)
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(
                seat, _w1g4_Permanent(card=pool[name]), None
            )
    return game


def _w1g4_names(cards):
    return [card.name for card in cards]


def _w1g4_on_board(game, seat, name):
    return next(p for p in game.controlled_by(seat) if p.card.name == name)


# --- The Bursts: "N plus the number of cards named ~ in all graveyards" ------

def test_flame_burst_counts_its_name_in_every_graveyard(set_pool):
    """2 plus one in each graveyard: 4 damage, and the copy being cast is on
    the stack while the count is taken, so it is not one of them."""
    game = _w1g4_duel(
        set_pool, hand0=["Flame Burst"], gy0=["Flame Burst"],
        gy1=["Flame Burst", "Grizzly Bears"],
    )
    assert game.cast_from_hand(0, "Flame Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 16
    assert _w1g4_names(game.players[0].graveyard) == ["Flame Burst", "Flame Burst"]


def test_flame_burst_with_none_in_a_graveyard_deals_its_printed_two(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Flame Burst"], bf1=["Grizzly Bears"])
    bears = _w1g4_on_board(game, 1, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Flame Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    game.check_state_based_actions()
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert game.players[1].life == 20


def test_muscle_burst_is_three_plus_the_bursts_in_all_graveyards(set_pool):
    """The same definition Flame Burst prints, in the +X/+X position — which
    refused ("only a count or a maximum can define X here") while the damage
    form read it: one where-clause, two readers that had drifted apart."""
    game = _w1g4_duel(
        set_pool, hand0=["Muscle Burst"], gy0=["Muscle Burst"],
        gy1=["Muscle Burst", "Flame Burst"], bf0=["Grizzly Bears"],
    )
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == (7, 7)


def test_muscle_burst_needs_a_creature_to_aim_at(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Muscle Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(game, 1, "Forest")
    refused = game.cast_from_hand(
        0, "Muscle Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(game.players[0].hand) == ["Muscle Burst"]


@_w1g4_pytest.mark.parametrize("line, expected", [
    # The arithmetic the sentence form always read, now in the pump position.
    ("Target creature gets +X/+X until end of turn, where X is twice the "
     "number of cards named Vigor Burst in all graveyards minus 1.", (5, 5)),
    ("Target creature gets +X/+0 until end of turn, where X is the number of "
     "cards in your graveyard minus the number of cards in your hand.", (4, 2)),
])
def test_a_pump_reads_the_arithmetic_a_damage_where_clause_reads(
    set_pool, line, expected
):
    """An invented card, not a name: the fork was in which *sentence* could
    carry a sum, so the proof is a card nobody printed carrying one."""
    burst = _w1g4_mk_card("Vigor Burst", "{G}", "Instant", line)
    assert _w1g4_compile(burst).supported
    game = _w1g4_duel(set_pool, bf0=["Grizzly Bears"])
    game.players[0].hand.append(burst)
    game.players[0].graveyard.extend([burst, burst])
    bears = _w1g4_on_board(game, 0, "Grizzly Bears")
    assert game.cast_from_hand(
        0, "Vigor Burst", target_permanent_ids=[bears.permanent_id]
    ).supported
    _w1g4_resolve_stack(game)
    assert (bears.effective_power, bears.effective_toughness) == expected


def test_a_damage_where_clause_reads_the_maximum_a_pump_reads(set_pool):
    """The fork's other direction: "the greatest power among" defined a pump's
    X (Carrion Grub) and refused a damage's."""
    blast = _w1g4_mk_card(
        "Grave Blast", "{R}", "Instant",
        "Grave Blast deals X damage to any target, where X is the greatest "
        "power among creature cards in your graveyard.",
    )
    assert _w1g4_compile(blast).supported
    game = _w1g4_duel(set_pool, gy0=["Grizzly Bears", "Craw Wurm", "Forest"])
    game.players[0].hand.append(blast)
    assert game.cast_from_hand(0, "Grave Blast", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert game.players[1].life == 14


def test_a_continuous_x_refuses_a_count_taken_off_a_count():
    """A durationless +X/+0 is rebuilt by the CR 613 recompute, which asks the
    zone evaluator and never the resolution-time function that subtracts — so
    the shape refuses instead of dropping its subtrahend."""
    grower = _w1g4_mk_card(
        "Odd Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is the number of cards in your "
        "hand minus the number of cards in your graveyard.",
    )
    assert not _w1g4_compile(grower).supported
    steady = _w1g4_mk_card(
        "Even Grower", "{G}", "Creature — Beast",
        "This creature gets +X/+0, where X is 1 plus the number of cards in "
        "your graveyard.",
    )
    assert _w1g4_compile(steady).supported


# --- Aether Burst: an X counted as the spell is cast (CR 601.2b/601.2c) ------

def test_aether_burst_announces_its_x_and_bounds_the_picker(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    card = set_pool("ODY")["Aether Burst"]
    assert game.announced_cast_x(0, card) == 2
    spec = game.cast_target_spec(0, card)
    assert spec["defined_x"] == 2 and spec["max_targets"] == 2
    assert len(spec["valid_targets"]) == 3
    every = [p.permanent_id for p in game.all_permanents()]
    refused = game.cast_from_hand(0, "Aether Burst", target_permanent_ids=every)
    assert not refused.supported
    assert refused.details == "Aether Burst has 2 targets, not 3"
    assert _w1g4_names(game.players[0].hand) == ["Aether Burst"]


def test_aether_burst_returns_what_was_named_to_its_owners_hand(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst"],
        bf0=["Grizzly Bears"], bf1=["Craw Wurm", "Scryb Sprites"],
    )
    theirs = [p.permanent_id for p in game.controlled_by(1)]
    assert game.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=theirs
    ).supported
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Craw Wurm", "Scryb Sprites"]
    assert [p.card.name for p in game.all_permanents()] == ["Grizzly Bears"]


def test_aether_burst_may_name_nobody_and_refuses_a_land(set_pool):
    """"Up to X": naming none is a legal announcement (CR 601.2c), and what is
    named has to be a creature."""
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    assert game.cast_from_hand(0, "Aether Burst", target_permanent_ids=[]).supported
    _w1g4_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Craw Wurm"]

    again = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Forest"])
    forest = _w1g4_on_board(again, 1, "Forest")
    refused = again.cast_from_hand(
        0, "Aether Burst", target_permanent_ids=[forest.permanent_id]
    )
    assert not refused.supported
    assert _w1g4_names(again.players[0].hand) == ["Aether Burst"]


def test_aether_burst_freezes_its_x_at_the_announcement(set_pool):
    """CR 601.2c: the number of targets does not change once determined. The
    graveyards are emptied in response and one target leaves: the two that are
    left are still returned, where a count taken again would return one."""
    game = _w1g4_duel(
        set_pool, hand0=["Aether Burst"], gy1=["Aether Burst", "Aether Burst"],
        bf1=["Craw Wurm", "Scryb Sprites", "Grizzly Bears"],
    )
    ids = [p.permanent_id for p in game.controlled_by(1)]
    assert game.queue_from_hand(0, "Aether Burst", target_permanent_ids=ids).supported
    assert game.stack[-1].x_value == 3
    game.players[1].graveyard.clear()
    game.remove_from_battlefield(game.permanent_by_id(ids[0]))
    _w1g4_resolve_stack(game)
    assert sorted(_w1g4_names(game.players[1].hand)) == ["Grizzly Bears", "Scryb Sprites"]


def test_aether_burst_with_every_target_gone_does_nothing(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Aether Burst"], bf1=["Craw Wurm"])
    wurm = _w1g4_on_board(game, 1, "Craw Wurm")
    assert game.queue_from_hand(
        0, "Aether Burst", target_permanent_ids=[wurm.permanent_id]
    ).supported
    game.remove_from_battlefield(wurm)
    _w1g4_resolve_stack(game)
    assert any("608.2b" in line for line in game.log)
    assert game.players[1].hand == []


# --- Life Burst: "…for each card named ~ in each graveyard" -------------------

def test_life_burst_gains_four_then_four_per_burst_in_each_graveyard(set_pool):
    """One Life Burst in each graveyard: 4, then 8 more. "In each graveyard" is
    "in all graveyards" distributed (CR 400.1: one pile per seat), and the copy
    being cast is still on the stack."""
    game = _w1g4_duel(
        set_pool, hand0=["Life Burst"], gy0=["Life Burst"],
        gy1=["Life Burst", "Forest"],
    )
    assert game.cast_from_hand(0, "Life Burst", target_player_index=0).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (32, 20)


def test_life_burst_names_its_player_and_gives_the_plain_four(set_pool):
    game = _w1g4_duel(set_pool, hand0=["Life Burst"])
    spec = game.cast_target_spec(0, set_pool("ODY")["Life Burst"])
    assert spec["kind"] == "player" and spec["requires_target"]
    assert game.cast_from_hand(0, "Life Burst", target_player_index=1).supported
    _w1g4_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (20, 24)


# --- Entomb and Predict --------------------------------------------------------

def test_entomb_puts_the_found_card_into_its_owners_graveyard(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Entomb"], lib0=["Forest", "Craw Wurm", "Island"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Entomb").supported
    game.resolve_top_of_stack()
    prompt = next(c for c in game.pending_choices if c.kind == "search_library")
    assert prompt.data["destination"] == "graveyard" and prompt.data["count"] == 1
    assert prompt.data["card_type"] == "any" and not prompt.data["up_to"]
    game.auto_resolve_pending_choices()
    _w1g4_resolve_stack(game)
    graveyard = _w1g4_names(game.players[0].graveyard)
    assert len(graveyard) == 2 and "Entomb" in graveyard
    assert len(game.players[0].library) == 2


@_w1g4_pytest.mark.parametrize("named, drawn", [
    ("Grizzly Bears", 2),   # the card that is milled
    ("Craw Wurm", 1),       # a card that is not
    ("", 1),                # naming nothing
])
def test_predict_draws_two_for_the_right_name_and_one_otherwise(
    set_pool, named, drawn
):
    """The name is chosen as the spell resolves, before the mill, and it is
    the caster's to choose — a prompt on their seat while the spell is held."""
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
        lib1=["Grizzly Bears", "Craw Wurm"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=1).supported
    game.resolve_top_of_stack()
    prompt = game.waiting_prompt()
    assert prompt.kind == "choose_card_name" and prompt.player_index == 0
    assert game.players[1].graveyard == [], "nothing is milled before the name"
    assert game.confirm_choose_card_name(0, named)
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[1].graveyard) == ["Grizzly Bears"]
    assert len(game.players[0].hand) == drawn
    assert _w1g4_names(game.players[0].graveyard) == ["Predict"]


def test_predict_may_mill_its_own_caster(set_pool):
    game = _w1g4_duel(
        set_pool, hand0=["Predict"], lib0=["Forest", "Island", "Swamp"],
    )
    game.interactive_seats.add(0)
    assert game.queue_from_hand(0, "Predict", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.confirm_choose_card_name(0, "Forest")
    _w1g4_resolve_stack(game)
    assert _w1g4_names(game.players[0].graveyard) == ["Forest", "Predict"]
    assert _w1g4_names(game.players[0].hand) == ["Island", "Swamp"]

# ==== end W1G4 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

import pytest as _w1g6_pytest

from engine import Game as _W1G6Game
from engine import PlayerState as _W1G6PlayerState
from engine.models import Permanent as _W1G6Permanent
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_game(
    mine=(), theirs=(), yard=(), their_yard=(), library=(), their_library=(),
    hand=(), their_hand=(),
):
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
            library=list(their_library), hand=list(their_hand), life=20,
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


def _w1g6_pile(player, zone="graveyard"):
    return [card.name for card in getattr(player, zone)]


# --- Skeletal Scrying -------------------------------------------------------
# "As an additional cost to cast this spell, exile X cards from your
# graveyard. / You draw X cards and you lose X life." Refused at the support
# gate ("printed cost nothing charges"): the graveyard-exile clause reader
# admitted only a phrase naming a card type, and this one prints "cards".

def test_w1g6_skeletal_scrying_charges_x_cards_for_x_cards_and_x_life(set_pool):
    from engine.cast_costs import additional_costs

    lea, ody = set_pool("LEA"), set_pool("ODY")
    scrying = ody["Skeletal Scrying"]
    (cost,) = additional_costs(scrying)
    assert cost.exile_graveyard_filter == {} and cost.exile_graveyard_count_x

    game = _w1g6_game(
        hand=[scrying],
        yard=[lea["Forest"], lea["Lightning Bolt"], lea["Hill Giant"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)
    # The X box is capped by what the graveyard can pay.
    assert game.cast_target_spec(0, scrying)["max_x"] == 3

    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    # Paid as it is cast (CR 601.2h): two cards are gone before it resolves.
    assert len(game.players[0].exile) == 2 and len(game.players[0].graveyard) == 1
    assert not game.players[0].hand and game.players[0].life == 20
    _w1g6_resolve_stack(game)

    assert _w1g6_pile(game.players[0], "hand") == ["Island", "Island"]
    assert game.players[0].life == 18
    assert len(game.players[0].library) == 4


def test_w1g6_skeletal_scrying_cannot_announce_more_than_the_graveyard_holds(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"], lea["Lightning Bolt"]],
        library=[lea["Island"]] * 6,
    )
    game.start_turn(0)

    refused = game.queue_from_hand(0, "Skeletal Scrying", x_value=3)

    assert not refused.supported
    assert "holds 2 card(s) and its additional cost exiles 3" in refused.details
    assert _w1g6_pile(game.players[0], "hand") == ["Skeletal Scrying"]
    assert len(game.players[0].graveyard) == 2 and not game.players[0].exile


def test_w1g6_skeletal_scrying_pays_x_in_mana_as_well_as_in_cards(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Skeletal Scrying"]], yard=[lea["Forest"]] * 3,
        library=[lea["Island"]] * 6,
    )
    game.enforce_mana_costs = True
    game.start_turn(0)

    game.players[0].mana_pool["B"] = 2
    short = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert not short.supported
    assert len(game.players[0].graveyard) == 3, "a refused cast exiled nothing"

    game.players[0].mana_pool["B"] = 3
    cast = game.queue_from_hand(0, "Skeletal Scrying", x_value=2)
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 18 and len(game.players[0].hand) == 2


# --- Ghastly Demise ---------------------------------------------------------
# "Destroy target nonblack creature if its toughness is less than or equal to
# the number of cards in your graveyard." The target is legal whatever its
# toughness (Scryfall ruling 2020-11-10: "Ghastly Demise can target any
# nonblack creature. Compare the creature's toughness to the number of cards
# in your graveyard as Ghastly Demise resolves"); the comparison is CR 608.2c's
# trailing "if", against a count taken as it resolves.

def _w1g6_demise(set_pool, yard_size, target="Hill Giant"):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        hand=[ody["Ghastly Demise"]],
        theirs=[lea["Hill Giant"], lea["Drudge Skeletons"], lea["Grizzly Bears"]],
        yard=[lea["Forest"]] * yard_size,
    )
    game.start_turn(0)
    aimed = _w1g6_named(game, 1, target)
    cast = game.queue_from_hand(
        0, "Ghastly Demise", target_permanent_ids=[aimed.permanent_id]
    )
    return game, cast  # _w1g6_demise


@_w1g6_pytest.mark.parametrize(
    "yard_size, destroyed", [(3, True), (4, True), (2, False), (0, False)]
)
def test_w1g6_ghastly_demise_compares_toughness_with_the_graveyard(
    set_pool, yard_size, destroyed
):
    game, cast = _w1g6_demise(set_pool, yard_size)  # Hill Giant: toughness 3
    # Castable either way: the condition is not a targeting restriction.
    assert cast.supported, cast.details
    _w1g6_resolve_stack(game)

    assert ("Hill Giant" in _w1g6_names(game, 1)) is not destroyed
    assert ("Hill Giant" in _w1g6_pile(game.players[1])) is destroyed
    # The spell resolves and goes to the graveyard whether or not it destroyed.
    assert _w1g6_pile(game.players[0])[-1] == "Ghastly Demise"


def test_w1g6_ghastly_demise_does_not_count_itself(set_pool):
    """Ruling 2020-11-10: "Because Ghastly Demise isn't put into your graveyard
    until it's finished resolving, it won't be counted". A 2/2 against one
    card in the graveyard survives; the Demise makes two only afterwards."""
    game, cast = _w1g6_demise(set_pool, 1, target="Grizzly Bears")
    assert cast.supported
    _w1g6_resolve_stack(game)

    assert "Grizzly Bears" in _w1g6_names(game, 1)
    assert len(game.players[0].graveyard) == 2


def test_w1g6_ghastly_demise_counts_as_it_resolves(set_pool):
    lea = set_pool("LEA")
    game, cast = _w1g6_demise(set_pool, 2)
    assert cast.supported
    # A third card arrives while the spell is on the stack.
    game.players[0].graveyard.append(lea["Forest"])
    _w1g6_resolve_stack(game)

    assert "Hill Giant" not in _w1g6_names(game, 1)


def test_w1g6_ghastly_demise_cannot_be_aimed_at_a_black_creature_or_at_nothing(
    set_pool,
):
    game, refused = _w1g6_demise(set_pool, 5, target="Drudge Skeletons")
    assert not refused.supported
    assert _w1g6_pile(game.players[0], "hand") == ["Ghastly Demise"]

    lea, ody = set_pool("LEA"), set_pool("ODY")
    empty = _w1g6_game(hand=[ody["Ghastly Demise"]], yard=[lea["Forest"]] * 5)
    empty.start_turn(0)
    assert not empty.queue_from_hand(0, "Ghastly Demise").supported

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
import pytest as _w1g8_pytest

from engine.oracle import compile_card_oracle as _w1g8_compile
from tests.sets import ody_w1g8_helpers as _w1g8


# --- Blazing Salvo ----------------------------------------------------------
# "Blazing Salvo deals 3 damage to target creature unless that creature's
# controller has Blazing Salvo deal 5 damage to them." The punisher clause: the
# toll's eighth currency is damage the payer *chooses to be dealt*.
#
# Scryfall carries no ruling for this card, Lava Blister or Molten Influence
# (fetched 2026-10-12), so the Comprehensive Rules are the authority:
# CR 118.12a makes "[do something] unless [a player does something else]" the
# offer "[a player may do something else]. If [that player doesn't], [do
# something]", and CR 118.12 says that "if" checks "whether the player chose
# to pay … regardless of what events actually occurred". Vexing Devil's
# 2012-05-01 ruling says the same of the "may have it deal" spelling.

def _w1g8_salvo(set_pool, seat=1, interactive=(1,), victim="Hill Giant"):
    """Blazing Salvo cast at *victim* on *seat*'s side, resolved up to the
    point somebody is asked."""
    game = _w1g8.table(set_pool, hand=["Blazing Salvo"], interactive=interactive)
    game.start_turn(0)
    creature = _w1g8.put(game, set_pool, seat, victim)
    cast = game.queue_from_hand(
        0, "Blazing Salvo", target_permanent_ids=[creature.permanent_id]
    )
    assert cast.supported, cast.details
    return game, creature


def test_w1g8_blazing_salvo_asks_the_creatures_controller_who_may_take_five(set_pool):
    game, giant = _w1g8_salvo(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g8.owed(game) == [("optional_pay", 1)]
    assert [item.card.name for item in game.stack] == ["Blazing Salvo"], (
        "the spell waits on the stack for the answer (CR 608.2)"
    )
    assert game.confirm_optional_pay(1, accept=True)
    _w1g8.settle(game)

    assert [player.life for player in game.players] == [20, 15]
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert _w1g8.pile(game, 0) == ["Blazing Salvo"]


def test_w1g8_blazing_salvo_declined_deals_its_three_to_the_creature(set_pool):
    game, giant = _w1g8_salvo(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g8.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert _w1g8.pile(game, 1) == ["Hill Giant"]


def test_w1g8_blazing_salvo_at_the_casters_own_creature_asks_the_caster(set_pool):
    """"That creature's controller" is a seat read off the target, not "the
    opponent": aimed at its own creature the caster is the one who chooses."""
    game, giant = _w1g8_salvo(set_pool, seat=0, interactive=(0, 1))
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g8.owed(game) == [("optional_pay", 0)]
    assert game.confirm_optional_pay(0, accept=True)
    _w1g8.settle(game)
    assert [player.life for player in game.players] == [15, 20]
    assert game.is_on_battlefield(giant)


def test_w1g8_a_prevented_punisher_still_spares_the_creature(set_pool):
    """CR 118.12: the creature is spared because its controller *chose* the
    damage, whatever then happens to it. Behind a Circle of Protection: Red the
    five is prevented and the three is still not dealt."""
    game, giant = _w1g8_salvo(set_pool)
    _w1g8.put(game, set_pool, 1, "Circle of Protection: Red")
    game.players[1].mana_pool["C"] = 1
    shield = game.activate_permanent_ability(1, "Circle of Protection: Red")
    assert shield.supported, shield.details

    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=True)
    _w1g8.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert game.is_on_battlefield(giant) and giant.damage_marked == 0
    assert any("prevented 5 damage" in line for line in game.log)


def test_w1g8_the_punishers_damage_is_dealt_by_the_casters_spell(set_pool):
    """The damage the opponent takes is Blazing Salvo's, controlled by its
    caster (CR 109.5) — "a source you control" for Fiery Emancipation."""
    game, giant = _w1g8_salvo(set_pool)
    _w1g8.put(game, set_pool, 0, _w1g8.card(set_pool, "Fiery Emancipation"))
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=True)
    _w1g8.settle(game)

    assert game.players[1].life == 5, "5 damage tripled"


def test_w1g8_blazing_salvo_whose_creature_left_asks_nobody(set_pool):
    """CR 608.2b: its only target gone, the spell does not resolve — there is
    no offer to make and no five to take."""
    game, giant = _w1g8_salvo(set_pool)
    _w1g8.leave(game, giant)
    game.resolve_top_of_stack(pause_for_choices=True)
    _w1g8.settle(game)

    assert _w1g8.owed(game) == []
    assert [player.life for player in game.players] == [20, 20]
    assert any("every target is illegal" in line for line in game.log)


def test_w1g8_blazing_salvo_needs_a_creature_to_be_cast_at(set_pool):
    game = _w1g8.table(set_pool, hand=["Blazing Salvo"])
    game.start_turn(0)
    forest = _w1g8.put(game, set_pool, 1, "Forest")

    at_a_land = game.cast_from_hand(
        0, "Blazing Salvo", target_permanent_ids=[forest.permanent_id]
    )
    at_nothing = game.cast_from_hand(0, "Blazing Salvo")

    assert not at_a_land.supported and not at_nothing.supported
    assert _w1g8.pile(game, 0, "hand") == ["Blazing Salvo"]


@_w1g8_pytest.mark.parametrize(
    "life, victim, takes_five",
    [
        (20, "Hill Giant", True),      # five life for a creature: the toll is paid
        (5, "Hill Giant", False),      # …but never with the game
        (20, "Shivan Dragon", False),  # three does not kill it: nothing to buy off
    ],
)
def test_w1g8_a_seat_nobody_asks_weighs_the_five_against_the_creature(
    set_pool, life, victim, takes_five
):
    """The non-interactive answer (an AI seat, a headless game). "Pay tolls"
    used to pay this one unconditionally: a seat at 5 life took the five and
    lost the game to keep a Hill Giant."""
    game, creature = _w1g8_salvo(set_pool, interactive=(), victim=victim)
    game.players[1].life = life
    _w1g8.settle(game)

    assert game.players[1].life == (life - 5 if takes_five else life)
    assert not game.players[1].lost


# --- Molten Influence -------------------------------------------------------
# "Counter target instant or sorcery spell unless its controller has Molten
# Influence deal 4 damage to them." The same clause behind a counter, where
# "its controller" is a *spell's* — a seat neither the control seam nor the
# resolution's own target channel holds.

def _w1g8_molten(set_pool, caster=1, interactive=(0, 1)):
    """A Lightning Bolt cast by *caster* at the other seat, with seat 0's
    Molten Influence aimed at it."""
    game = _w1g8.table(
        set_pool, hand=["Molten Influence", "Lightning Bolt"],
        their_hand=["Lightning Bolt"], interactive=interactive,
    )
    game.start_turn(0)
    bolt = game.queue_from_hand(caster, "Lightning Bolt", target_player_index=1 - caster)
    assert bolt.supported, bolt.details
    counter = game.queue_from_hand(0, "Molten Influence", target_stack_index=0)
    assert counter.supported, counter.details
    return game


@_w1g8_pytest.mark.parametrize("caster", [1, 0])
def test_w1g8_molten_influence_lets_the_spells_controller_take_four(set_pool, caster):
    """The spell's controller is asked — the opponent, or the caster who aimed
    it at their own spell — and taking the four lets the spell resolve."""
    game = _w1g8_molten(set_pool, caster=caster)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert _w1g8.owed(game) == [("optional_pay", caster)]
    assert game.confirm_optional_pay(caster, accept=True)
    _w1g8.settle(game)

    life = [20, 20]
    life[caster] -= 4        # Molten Influence, by choice
    life[1 - caster] -= 3    # the Bolt, which resolved
    assert [player.life for player in game.players] == life


def test_w1g8_molten_influence_declined_counters_the_spell(set_pool):
    game = _w1g8_molten(set_pool)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_optional_pay(1, accept=False)
    _w1g8.settle(game)

    assert [player.life for player in game.players] == [20, 20]
    assert _w1g8.pile(game, 1) == ["Lightning Bolt"]
    assert any("was countered by Molten Influence" in line for line in game.log)


@_w1g8_pytest.mark.parametrize("life, countered", [(20, False), (4, True)])
def test_w1g8_a_seat_nobody_asks_answers_molten_influence_before_the_spell_resolves(
    set_pool, life, countered
):
    """Headless, the offer is answered where it stands: the spell it is about
    is the next object to resolve, and an answer drained after the stack
    emptied countered nothing. A seat the four would kill declines."""
    game = _w1g8_molten(set_pool, interactive=())
    game.players[1].life = life
    _w1g8.settle(game)

    if countered:
        assert [player.life for player in game.players] == [20, life]
        assert _w1g8.pile(game, 1) == ["Lightning Bolt"]
    else:
        assert [player.life for player in game.players] == [17, life - 4]


def test_w1g8_molten_influence_cannot_be_aimed_at_a_creature_spell_or_nothing(set_pool):
    game = _w1g8.table(
        set_pool, hand=["Molten Influence"], their_hand=["Grizzly Bears"],
    )
    game.start_turn(0)
    assert not game.cast_from_hand(0, "Molten Influence").supported, "an empty stack"

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    refused = game.queue_from_hand(0, "Molten Influence", target_stack_index=0)
    assert not refused.supported
    assert _w1g8.pile(game, 0, "hand") == ["Molten Influence"]


@_w1g8_pytest.mark.parametrize(
    "price",
    [
        "has Probe Salvo deal 5 damage to you",              # not the payer
        "has Probe Salvo deal 5 damage to them and to you",  # a second recipient
        "has target creature deal 5 damage to them",         # not this spell
    ],
)
def test_w1g8_a_damage_price_is_this_spells_damage_to_the_payer_alone(price):
    """The refusing gate's refusal test: only the ability's own source, and
    only to the seat that was asked."""
    from tests.helpers import _mk_card

    probe = _mk_card(
        "Probe Salvo", "Instant",
        "Probe Salvo deals 3 damage to target creature unless that creature's "
        f"controller {price}.",
    )
    assert not _w1g8_compile(probe).supported

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
