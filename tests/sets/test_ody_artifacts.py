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

import pytest as _w1g2_pytest

from engine import Game as _w1g2_Game, PlayerState as _w1g2_PlayerState
from engine.ai_valuation import planned_mana_yield as _w1g2_planned_mana_yield
from engine.board_payment import board_can_pay as _w1g2_board_can_pay
from engine.mana_payment import is_mana_ability as _w1g2_is_mana_ability
from engine.models import Permanent as _w1g2_Permanent
from engine.oracle import compile_card_oracle as _w1g2_compile

#: "{2}, {T}, Sacrifice this artifact: Add <two colours>. Draw a card."
_W1G2_EGGS = [
    ("Darkwater Egg", {"U": 1, "B": 1}),
    ("Mossfire Egg", {"R": 1, "G": 1}),
    ("Shadowblood Egg", {"B": 1, "R": 1}),
    ("Skycloud Egg", {"W": 1, "U": 1}),
    ("Sungrass Egg", {"G": 1, "W": 1}),
]


def _w1g2_egg_game(set_pool, name, *, pool):
    """A game that charges mana with *name* on seat 0's battlefield, entered
    this turn — an Egg is not a creature, so {T} needs no haste (CR 302.6)."""
    lea = set_pool("LEA")
    game = _w1g2_Game(players=[
        _w1g2_PlayerState("Caster", library=[lea["Forest"]] * 10),
        _w1g2_PlayerState("Bystander", library=[lea["Forest"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(pool)
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    egg = _w1g2_Permanent(card=set_pool("ODY")[name])
    game._put_permanent_onto_battlefield(0, egg, None)
    return game, egg  # _w1g2_egg_game


def _w1g2_egg_floating(game) -> dict:
    return {k: v for k, v in game.players[0].mana_pool.items() if v}  # _w1g2_egg_floating


@_w1g2_pytest.mark.parametrize("name, made", _W1G2_EGGS)
def test_an_egg_is_a_mana_ability_that_also_draws(set_pool, name, made):
    """"{2}, {T}, Sacrifice this artifact: Add {U}{B}. Draw a card." CR 605.1a
    asks only that the ability could add mana, has no target and is not a
    loyalty ability — so the draw rides a mana ability: it resolves inline
    (CR 605.3b), with a spell already on the stack, and never goes on it."""
    lea = set_pool("LEA")
    (ability,) = _w1g2_compile(set_pool("ODY")[name]).activated_abilities
    assert _w1g2_is_mana_ability(ability)

    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 2, "R": 1})
    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    result = game.queue_permanent_ability(0, name, ability_index=0)

    assert result.supported and result.details == "resolved"
    assert len(game.stack) == 1, "the Bolt alone: the Egg never used the stack"
    assert _w1g2_egg_floating(game) == made
    assert not game.is_on_battlefield(egg)
    assert [card.name for card in game.players[0].graveyard] == [name]
    assert len(game.players[0].hand) == 1 and len(game.players[0].library) == 9


@_w1g2_pytest.mark.parametrize("name, made", _W1G2_EGGS)
def test_an_egg_is_not_cracked_for_less_than_its_cost(set_pool, name, made):
    """Refused with one mana floating and refused once tapped: nothing is
    spent, nothing is sacrificed and no card is drawn (CR 601.2h)."""
    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 1})
    short = game.queue_permanent_ability(0, name, ability_index=0)
    assert not short.supported and game.is_on_battlefield(egg)
    assert _w1g2_egg_floating(game) == {"C": 1} and game.players[0].hand == []

    game, egg = _w1g2_egg_game(set_pool, name, pool={"C": 2})
    egg.tapped = True
    tapped = game.queue_permanent_ability(0, name, ability_index=0)
    assert not tapped.supported and game.is_on_battlefield(egg)
    assert _w1g2_egg_floating(game) == {"C": 2}


def test_no_automatic_payment_counts_an_egg(set_pool):
    """The three doors an Egg's mana could come through, and the two it does
    not: the castable highlight counts lands alone (an Egg is an activation
    the player makes first), and the AI's tap planner declines a source whose
    ability costs mana, sacrifices it, or does anything beside adding mana —
    an Egg is all three."""
    game, _egg = _w1g2_egg_game(set_pool, "Darkwater Egg", pool={"C": 2})
    assert not _w1g2_board_can_pay(game, 0, {"U": 1})
    assert _w1g2_board_can_pay(game, 0, {"generic": 2}), "the pool, not the Egg"

    (ability,) = _w1g2_compile(set_pool("ODY")["Darkwater Egg"]).activated_abilities
    assert _w1g2_planned_mana_yield(ability.instruction) is None


def test_an_eggs_draw_is_a_real_draw(set_pool):
    """The card comes off the top of the library through the draw seam: with
    an empty library the Egg still makes its mana and its controller has
    drawn from nothing (CR 704.5b)."""
    game, _egg = _w1g2_egg_game(set_pool, "Sungrass Egg", pool={"C": 2})
    game.players[0].library.clear()

    assert game.queue_permanent_ability(0, "Sungrass Egg", ability_index=0).supported
    game._settle()

    assert _w1g2_egg_floating(game) == {"G": 1, "W": 1}
    assert game.players[0].lost

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


# --- Millikin, Charmed Pendant ----------------------------------------------
# "{T}, Mill a card: Add {C}. (Activate only as an instant. …)" Mill as a
# cost (CR 701.17a), paid last (CR 601.2h) and unpayable from an empty library
# (CR 701.17b). **Not a mana ability**: Millikin's Scryfall ruling of
# 2026-08-05 — "Millikin's ability is not a mana ability. Players can respond
# to it, and it can't be activated in the middle of paying for a cost. A
# recent update to rule 605.1a has made any abilities that move cards to or
# from libraries no longer mana abilities." So it uses the stack, which is
# what makes the printed "only as an instant" true.

def _w1g6_pool_of(game, seat=0):
    return {
        symbol: count
        for symbol, count in game.players[seat].mana_pool.items() if count
    }


def test_w1g6_millikin_mills_then_makes_colourless_through_the_stack(set_pool):
    from engine.mana_payment import is_mana_ability

    lea, ody = set_pool("LEA"), set_pool("ODY")
    ability = _w1g6_compile(ody["Millikin"]).activated_abilities[0]
    assert ability.cost.requires_tap and ability.cost.mill_cards == 1
    assert not is_mana_ability(ability)

    game = _w1g6_game(
        mine=[ody["Millikin"]],
        library=[lea["Lightning Bolt"], lea["Forest"], lea["Forest"]],
    )
    game.start_turn(0)

    queued = game.queue_permanent_ability(0, "Millikin")

    assert queued.details == "queued"
    # The cost is paid — tapped, one card milled — and the mana is not there
    # yet: the ability is an object somebody could respond to.
    assert _w1g6_named(game, 0, "Millikin").tapped
    assert [card.name for card in game.players[0].graveyard] == ["Lightning Bolt"]
    assert len(game.players[0].library) == 2
    assert len(game.stack) == 1 and _w1g6_pool_of(game) == {}

    _w1g6_resolve_stack(game)
    assert _w1g6_pool_of(game) == {"C": 1}
    assert len(game.players[0].library) == 2, "exactly one card was milled"


def test_w1g6_a_mill_cost_cannot_be_paid_from_an_empty_library(set_pool):
    ody = set_pool("ODY")
    for name in ("Millikin", "Charmed Pendant"):
        game = _w1g6_game(mine=[ody[name]], library=[])
        game.start_turn(0)

        refused = game.activate_permanent_ability(0, name)

        assert not refused.supported and "its cost mills 1" in refused.details
        assert not _w1g6_named(game, 0, name).tapped
        assert _w1g6_pool_of(game) == {}


def test_w1g6_millikin_is_not_tapped_for_mana_like_a_mana_rock(set_pool):
    """The tap-for-mana seam is reached part-way through a payment, and this
    ability cannot be activated there (the ruling above)."""
    from engine.mixins.turn_management import is_tap_alone_mana_ability

    lea, ody = set_pool("LEA"), set_pool("ODY")
    ability = _w1g6_compile(ody["Millikin"]).activated_abilities[0]
    assert not is_tap_alone_mana_ability(ability)

    game = _w1g6_game(mine=[ody["Millikin"]], library=[lea["Forest"]] * 3)
    game.start_turn(0)
    assert not game.tap_land_for_mana(0, 0)
    assert len(game.players[0].library) == 3 and _w1g6_pool_of(game) == {}


def test_w1g6_charmed_pendant_adds_a_mana_for_each_coloured_symbol_milled(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    for top, made in (
        ("Lightning Bolt", {"R": 1}),       # {R}
        ("Shivan Dragon", {"R": 2}),        # {4}{R}{R}: the generic adds nothing
        ("Craw Wurm", {"G": 2}),            # {4}{G}{G}
        ("Sol Ring", {}),                   # {1}
        ("Forest", {}),                     # a land has no mana cost
    ):
        game = _w1g6_game(
            mine=[ody["Charmed Pendant"]], library=[lea[top], lea["Island"]],
        )
        game.start_turn(0)

        used = game.activate_permanent_ability(0, "Charmed Pendant")

        assert used.supported, (top, used.details)
        assert _w1g6_pool_of(game) == made, top
        assert [card.name for card in game.players[0].graveyard] == [top]
        assert len(game.players[0].library) == 1


def test_w1g6_charmed_pendant_reads_the_card_its_cost_milled_not_the_pile(set_pool):
    """The graveyard already holds a blue card on top; the mana comes from the
    card the cost put there, and survives that card leaving in response."""
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Charmed Pendant"]], yard=[lea["Counterspell"]],
        library=[lea["Shivan Dragon"], lea["Island"]],
    )
    game.start_turn(0)

    queued = game.queue_permanent_ability(0, "Charmed Pendant")
    assert queued.details == "queued" and _w1g6_pool_of(game) == {}
    assert [card.name for card in game.players[0].graveyard] == [
        "Counterspell", "Shivan Dragon",
    ]
    game.players[0].graveyard.clear()
    _w1g6_resolve_stack(game)

    assert _w1g6_pool_of(game) == {"R": 2}


# --- Steamclaw --------------------------------------------------------------
# Driven. "{3}, {T}: Exile target card from a graveyard. / {1}, Sacrifice this
# artifact: Exile target card from a graveyard."

def test_w1g6_steamclaw_exiles_a_card_with_either_ability(set_pool):
    lea, ody = set_pool("LEA"), set_pool("ODY")
    game = _w1g6_game(
        mine=[ody["Steamclaw"]], yard=[lea["Forest"]],
        their_yard=[lea["Grizzly Bears"], lea["Lightning Bolt"]],
    )
    game.start_turn(0)
    claw = _w1g6_named(game, 0, "Steamclaw")

    tapped = game.activate_permanent_ability(
        0, "Steamclaw", ability_index=0, target_player_index=1,
        target_permanent_index=1,
    )
    assert tapped.supported, tapped.details
    assert claw.tapped and _w1g6_names(game, 0) == ["Steamclaw"]
    assert [card.name for card in game.players[1].exile] == ["Lightning Bolt"]

    # The second ability needs no untap: it is paid with the Steamclaw itself.
    sacrificed = game.activate_permanent_ability(
        0, "Steamclaw", ability_index=1, target_player_index=0,
        target_permanent_index=0,
    )
    assert sacrificed.supported, sacrificed.details
    assert _w1g6_names(game, 0) == []
    assert [card.name for card in game.players[0].exile] == ["Forest"]
    assert [card.name for card in game.players[0].graveyard] == ["Steamclaw"]
    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]


def test_w1g6_steamclaw_with_no_card_to_exile_is_not_spent(set_pool):
    ody = set_pool("ODY")
    game = _w1g6_game(mine=[ody["Steamclaw"]])
    game.start_turn(0)

    for index in (0, 1):
        assert not game.activate_permanent_ability(
            0, "Steamclaw", ability_index=index
        ).supported
    assert _w1g6_names(game, 0) == ["Steamclaw"]
    assert not _w1g6_named(game, 0, "Steamclaw").tapped

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
