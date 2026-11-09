"""Mirrodin artifacts.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("MRD")` / `set_cards("MRD")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G3 ==========================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ======================================================


# ==== W1G5 ==========================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.
#
# Counters on artifacts: fate counters as a sweep's exemption, charge counters
# as a cast's mana-value gate, remove-all-and-count, a counter removed as a cost
# from any permanent.

import pytest as _w1g6_pytest

from engine import Game as _w1g6_Game, PlayerState as _w1g6_PlayerState
from engine.models import (
    CardDefinition as _w1g6_CardDefinition, Permanent as _w1g6_Permanent,
)
from engine.named_counters import counters_on as _w1g6_counters_on
from engine.oracle import compile_card_oracle as _w1g6_compile
from tests.helpers import resolve_stack as _w1g6_resolve_stack


def _w1g6_creature(name: str, power: int = 2, toughness: int = 2,
                   type_line: str = "Creature — Test", mana_cost: str = "{1}{G}",
                   cmc: float = 2.0):
    return _w1g6_CardDefinition(
        name=name, mana_cost=mana_cost, cmc=cmc, type_line=type_line,
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": type_line,
             "power": str(power), "toughness": str(toughness)},
    )


def _w1g6_nosick(perm):
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def _w1g6_game(mine=(), theirs=(), hand=(), their_hand=()):
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=list(mine), hand=list(hand)),
        _w1g6_PlayerState(name="P2", battlefield=list(theirs),
                          hand=list(their_hand)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    return game


def test_w1g6_oblivion_stone_spares_only_what_carries_a_fate_counter(set_pool):
    """"{4}, {T}: Put a fate counter on target permanent." / "{5}, {T},
    Sacrifice this artifact: Destroy each nonland permanent without a fate
    counter on it, then remove all fate counters from all permanents."

    "Target permanent" offers every permanent — its own controller's, the
    opponent's, a land — and the sweep spares exactly the marked ones, lands
    untouched, the Stone itself sacrificed as the cost; afterwards no fate
    counter is left anywhere.
    """
    card = set_pool("MRD")["Oblivion Stone"]
    program = _w1g6_compile(card)
    assert program.supported, program.reason
    from engine.targeting import derive_activation_spec

    assert derive_activation_spec(program.activated_abilities[0]) == {
        "kind": "permanent"
    }

    stone = _w1g6_nosick(_w1g6_Permanent(card=card))
    keeper = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Keeper")))
    mine = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Mine")))
    theirs = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Theirs")))
    marked_land = _w1g6_Permanent(card=set_pool("MRD")["Island"])
    their_land = _w1g6_Permanent(card=set_pool("MRD")["Mountain"])
    game = _w1g6_game([stone, keeper, mine, marked_land], [theirs, their_land])

    placed = game.activate_permanent_ability(
        0, "Oblivion Stone", ability_index=0,
        target_permanent_ids=[keeper.permanent_id],
    )
    assert placed.supported, placed
    _w1g6_resolve_stack(game)
    assert _w1g6_counters_on(keeper, "fate") == 1

    # A land is a permanent too: the picker's "permanent" reaches it.
    stone.tapped = False
    placed = game.activate_permanent_ability(
        0, "Oblivion Stone", ability_index=0,
        target_permanent_ids=[marked_land.permanent_id],
    )
    assert placed.supported, placed
    _w1g6_resolve_stack(game)
    assert _w1g6_counters_on(marked_land, "fate") == 1

    stone.tapped = False
    swept = game.activate_permanent_ability(0, "Oblivion Stone", ability_index=1)
    assert swept.supported, swept
    _w1g6_resolve_stack(game)

    board = [p.card.name for p in game.all_permanents()]
    assert "Keeper" in board
    assert "Mine" not in board and "Theirs" not in board
    assert "Island" in board and "Mountain" in board
    assert "Oblivion Stone" not in board
    assert "Oblivion Stone" in [c.name for c in game.players[0].graveyard]
    assert _w1g6_counters_on(keeper, "fate") == 0
    assert _w1g6_counters_on(marked_land, "fate") == 0


def _w1g6_slot(game, seat, permanent):
    return next(
        index for index, candidate in enumerate(game.players[seat].battlefield)
        if candidate is permanent
    )


def test_w1g6_myr_prototype_grows_each_upkeep_and_prices_both_combat_steps(
    set_pool,
):
    """"At the beginning of your upkeep, put a +1/+1 counter on this creature."
    / "This creature can't attack or block unless you pay {1} for each +1/+1
    counter on it."

    Two upkeeps make a 4/4 whose attack costs {2}: refused with one land
    (nothing tapped), paid with two. The same pile prices its block — and a
    Prototype whose counters are gone owes nothing ("for each" at zero).
    """
    pool = set_pool("MRD")
    prototype = _w1g6_nosick(_w1g6_Permanent(card=pool["Myr Prototype"]))
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", battlefield=[prototype],
                          library=[pool["Island"]] * 10),
        _w1g6_PlayerState(name="P2", library=[pool["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for _ in range(2):
        game.start_turn(0)
        _w1g6_resolve_stack(game)
    assert prototype.metadata.get("plus_counters") == 2, game.log
    assert (prototype.effective_power, prototype.effective_toughness) == (4, 4)
    assert game._attack_mana_costs_of(prototype, 1) == [{"generic": 2}]

    land = _w1g6_Permanent(card=pool["Plains"])
    game.players[0].battlefield.append(land)
    game._sync_control()
    game.enforce_mana_costs = True
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [_w1g6_slot(game, 0, prototype)], defending_player_index=1,
    )
    assert not ok and not prototype.tapped and not land.tapped, "{2} owed, one land"

    second = _w1g6_Permanent(card=pool["Plains"])
    game.players[0].battlefield.append(second)
    game._sync_control()
    ok, why = game.declare_attackers(
        0, [_w1g6_slot(game, 0, prototype)], defending_player_index=1,
    )
    assert ok, why
    assert land.tapped and second.tapped
    assert any("paid {2} to declare attackers" in line for line in game.log)

    # The block half reads the same pile, per attacker blocked.
    attacker = _w1g6_nosick(_w1g6_Permanent(card=_w1g6_creature("Raider")))
    assert game._block_mana_costs_of(prototype, attacker) == [{"generic": 2}]
    from engine.named_counters import remove_counters

    remove_counters(prototype, "+1/+1", 2)
    assert game._block_mana_costs_of(prototype, attacker) == []
    assert game._attack_mana_costs_of(prototype, 1) == []


def _w1g6_chalice_table(set_pool, x_value, *, their_hand=(), interactive=()):
    """Chalice of the Void cast by P1 for *x_value*, paid for in full ({X}{X}
    is twice X, the 2021-03-19 ruling), resolved; P2 holds *their_hand*."""
    lea = set_pool("LEA")
    chalice = set_pool("MRD")["Chalice of the Void"]
    game = _w1g6_Game(players=[
        _w1g6_PlayerState(name="P1", hand=[chalice],
                          library=[lea["Island"]] * 10),
        _w1g6_PlayerState(name="P2", hand=list(their_hand),
                          library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    if x_value:
        game.players[0].mana_pool.update({"R": 2 * x_value - 1})
        short = game.queue_from_hand(0, "Chalice of the Void", x_value=x_value)
        assert not short.supported, "X is paid twice"
    game.players[0].mana_pool.update({"R": 2 * x_value})
    assert game.queue_from_hand(0, "Chalice of the Void", x_value=x_value).supported
    assert all(amount == 0 for amount in game.players[0].mana_pool.values())
    _w1g6_resolve_stack(game)
    (permanent,) = [
        p for p in game.all_permanents() if p.card.name == "Chalice of the Void"
    ]
    game.enforce_mana_costs = False
    return game, permanent



@_w1g6_pytest.mark.parametrize("interactive", [(), (0, 1)])
def test_w1g6_chalice_of_the_void_counters_each_spell_of_its_count(
    set_pool, interactive,
):
    """"This artifact enters with X charge counters on it." / "Whenever a
    player casts a spell with mana value equal to the number of charge counters
    on this artifact, counter that spell."

    Cast for X=1 it pays {2} and holds one counter: the opponent's Lightning
    Bolt (mana value 1) is countered, their Grizzly Bears (2) resolves, and
    its own controller's one-drop is countered too — "a player". Nothing to
    answer: an interactive table arms no prompt.
    """
    lea = set_pool("LEA")
    game, chalice = _w1g6_chalice_table(
        set_pool, 1, their_hand=[lea["Lightning Bolt"], lea["Grizzly Bears"]],
        interactive=interactive,
    )
    assert _w1g6_counters_on(chalice, "charge") == 1

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Chalice of the Void",
    ]
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 20
    assert "Lightning Bolt was countered by Chalice of the Void" in " ".join(game.log)
    assert not game.pending_choices

    assert game.queue_from_hand(1, "Grizzly Bears").supported
    assert [item.card.name for item in game.stack] == ["Grizzly Bears"]
    _w1g6_resolve_stack(game)
    assert any(p.card.name == "Grizzly Bears" for p in game.all_permanents())

    game.players[0].hand.append(lea["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported
    _w1g6_resolve_stack(game)
    assert game.players[1].life == 20, "its own controller's spell too"


def test_w1g6_chalice_reads_its_counters_only_as_the_spell_is_cast(set_pool):
    """The 2021-03-19 rulings: the count matters only when the spell is cast,
    and once the ability has triggered it counters the spell even if Chalice
    leaves the battlefield. So a Bolt cast into one counter is countered after
    the counter is removed and the Chalice destroyed in response; a Bolt cast
    after that, into no Chalice at all, resolves."""
    lea = set_pool("LEA")
    game, chalice = _w1g6_chalice_table(
        set_pool, 1,
        their_hand=[lea["Lightning Bolt"], lea["Shatter"], lea["Lightning Bolt"]],
    )
    from engine.named_counters import remove_counters

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    remove_counters(chalice, "charge", 1)
    # Shatter (mana value 2) in response, above the trigger: Chalice is gone
    # before its ability resolves.
    assert game.queue_from_hand(
        1, "Shatter", target_permanent_ids=[chalice.permanent_id],
    ).supported
    assert [item.card.name for item in game.stack] == [
        "Lightning Bolt", "Chalice of the Void", "Shatter",
    ]
    _w1g6_resolve_stack(game)
    assert not game.is_on_battlefield(chalice)
    assert game.players[0].life == 20

    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    _w1g6_resolve_stack(game)
    assert game.players[0].life == 17


def test_w1g6_chalice_for_zero_counters_the_mana_value_zero_spells(set_pool):
    """"If there are zero charge counters on Chalice of the Void, it counters
    each spell with a mana value of 0" (2021-03-19). A second Chalice cast for
    X=0 has mana value 0 on the stack (CR 202.3e) and is countered; one cast
    for X=1 has mana value 2 and is not."""
    chalice_card = set_pool("MRD")["Chalice of the Void"]
    game, chalice = _w1g6_chalice_table(
        set_pool, 0, their_hand=[chalice_card, chalice_card],
    )
    assert _w1g6_counters_on(chalice, "charge") == 0

    assert game.queue_from_hand(1, "Chalice of the Void", x_value=0).supported
    _w1g6_resolve_stack(game)
    assert [p.card.name for p in game.all_permanents()] == ["Chalice of the Void"]
    assert [c.name for c in game.players[1].graveyard] == ["Chalice of the Void"]

    assert game.queue_from_hand(1, "Chalice of the Void", x_value=1).supported
    _w1g6_resolve_stack(game)
    assert len(game.players[1].battlefield) == 1

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================
