"""Champions of Kamigawa creatures (legendary ones too) — the later groups' sections.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("CHK")` / `set_cards("CHK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game
from engine import PlayerState as _W1G7PlayerState
from engine.models import Permanent as _W1G7Permanent
from tests.helpers import declare_attack as _w1g7_declare_attack
from tests.helpers import drive_combat as _w1g7_drive_combat
from tests.helpers import settle as _w1g7_settle


def _w1g7_table(set_pool, *, mine=(), theirs=(), library=None, hand=(),
                interactive=()):
    """Two seats on seat 0's first main phase, costs off; *library* is seat
    0's, top first."""
    lea = set_pool("LEA")
    chk = set_pool("CHK")

    def named(name):
        return chk[name] if name in chk else lea[name]

    game = _W1G7Game(players=[
        _W1G7PlayerState(
            "P0", hand=[named(n) for n in hand],
            library=[named(n) for n in (library or ["Forest"] * 10)],
        ),
        _W1G7PlayerState("P1", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    placed = []
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = _W1G7Permanent(card=named(name))
            game._put_permanent_onto_battlefield(seat, permanent, None)
            permanent.metadata["summoning_sickness_turn"] = -99
            placed.append(permanent)
    game.start_turn(0)
    _w1g7_settle(game)
    return game, placed


_W1G7_DECEIVERS = {
    # name: (P/T before, P/T after a land, keyword gained)
    "Brutal Deceiver": ((2, 2), (3, 2), "first strike"),
    "Callous Deceiver": ((1, 3), (2, 3), "flying"),
    "Feral Deceiver": ((3, 2), (5, 4), "trample"),
    "Harsh Deceiver": ((1, 4), (2, 5), None),
    "Cruel Deceiver": ((2, 1), (2, 1), None),
}


@_w1g7_pytest.mark.parametrize("name", sorted(_W1G7_DECEIVERS))
def test_w1g7_a_deceiver_looks_at_its_top_card_privately(set_pool, name):
    """"{1}: Look at the top card of your library." — shown to its controller
    on a prompt (CR 400.2: the log is every seat's), nothing moved, nothing
    rearrangeable."""
    game, (deceiver,) = _w1g7_table(
        set_pool, mine=[name], library=["Lightning Bolt", "Forest", "Island"],
        interactive={0},
    )
    assert game.activate_permanent_ability(0, name, ability_index=0).supported
    asked = _w1g7_settle(game, defaults=False)
    assert asked is not None and asked.kind == "reorder_library"
    assert asked.player_index == 0 and asked.data["target_index"] == 0
    assert asked.data["top_count"] == 1 and asked.data["may_reorder"] is False
    assert not asked.data["may_shuffle"]
    # The card is not named where the other seat can read it.
    assert not any("Lightning Bolt" in line for line in game.log)
    _w1g7_settle(game)
    assert [c.name for c in game.players[0].library] == ["Lightning Bolt", "Forest", "Island"]


@_w1g7_pytest.mark.parametrize("name", sorted(_W1G7_DECEIVERS))
def test_w1g7_a_deceiver_reveals_a_land_once_each_turn(set_pool, name):
    before, after, keyword = _W1G7_DECEIVERS[name]
    game, (deceiver,) = _w1g7_table(set_pool, mine=[name], library=["Forest", "Lightning Bolt"])
    if name == "Harsh Deceiver":
        deceiver.tapped = True
    assert (deceiver.effective_power, deceiver.effective_toughness) == before
    assert game.activate_permanent_ability(0, name, ability_index=1).supported
    _w1g7_settle(game)
    assert any("revealed Forest" in line for line in game.log)
    assert (deceiver.effective_power, deceiver.effective_toughness) == after
    if keyword:
        assert game._has_keyword(deceiver, keyword)
    if name == "Harsh Deceiver":
        assert not deceiver.tapped
    # "Activate only once each turn."
    assert not game.activate_permanent_ability(0, name, ability_index=1).supported
    assert [c.name for c in game.players[0].library] == ["Forest", "Lightning Bolt"]
    game.resolve_cleanup_step(0)
    assert (deceiver.effective_power, deceiver.effective_toughness) == before


def test_w1g7_a_deceiver_revealing_a_nonland_does_nothing(set_pool):
    game, (deceiver,) = _w1g7_table(
        set_pool, mine=["Feral Deceiver"], library=["Lightning Bolt", "Forest"],
    )
    assert game.activate_permanent_ability(0, "Feral Deceiver", ability_index=1).supported
    _w1g7_settle(game)
    assert any("revealed Lightning Bolt" in line for line in game.log)
    assert (deceiver.effective_power, deceiver.effective_toughness) == (3, 2)
    assert not game._has_keyword(deceiver, "trample")


def test_w1g7_cruel_deceivers_granted_trigger_destroys_its_blocker(set_pool):
    game, (deceiver, wurm) = _w1g7_table(
        set_pool, mine=["Cruel Deceiver"], theirs=["Craw Wurm"],
        library=["Forest"] * 4,
    )
    assert game.activate_permanent_ability(0, "Cruel Deceiver", ability_index=1).supported
    _w1g7_settle(game)
    _w1g7_declare_attack(game, 0, blocks={0: 0})
    _w1g7_drive_combat(game)
    assert [c.name for c in game.players[1].graveyard] == ["Craw Wurm"]
    assert any("Cruel Deceiver destroyed Craw Wurm" in line for line in game.log)


def _w1g7_hisoka_against(set_pool, spell, discard, announce):
    lea = set_pool("LEA")
    game, (hisoka, wurm) = _w1g7_table(
        set_pool, mine=["Hisoka, Minamo Sensei"], theirs=["Craw Wurm"],
        hand=["Lightning Bolt", "Grizzly Bears", "Wrath of God"],
    )
    game.players[1].hand.append(lea[spell])
    game.queue_from_hand(1, spell, **announce(wurm))
    held = [card.name for card in game.players[0].hand]
    assert game.activate_permanent_ability(
        0, "Hisoka, Minamo Sensei", target_stack_index=0,
        cost_hand_index=held.index(discard),
    ).supported
    _w1g7_settle(game)
    return game, wurm


def test_w1g7_hisoka_counters_a_spell_matching_the_discarded_card(set_pool):
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Giant Growth", "Lightning Bolt",
        lambda wurm: {"target_permanent_ids": [wurm.permanent_id]},
    )
    assert [c.name for c in game.players[1].graveyard] == ["Giant Growth"]
    assert wurm.effective_power == 6                  # never pumped
    assert [c.name for c in game.players[0].graveyard] == ["Lightning Bolt"]


def test_w1g7_hisoka_does_not_counter_a_spell_of_another_mana_value(set_pool):
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Giant Growth", "Grizzly Bears",
        lambda wurm: {"target_permanent_ids": [wurm.permanent_id]},
    )
    assert wurm.effective_power == 9                  # Giant Growth resolved
    assert [c.name for c in game.players[0].graveyard] == ["Grizzly Bears"]


def test_w1g7_rag_dealer_announces_three_cards_of_a_single_graveyard(set_pool):
    """"{2}{B}, {T}: Exile up to three target cards from a single graveyard."
    The cards are targets, named as the ability is activated (CR 602.2b,
    601.2c) in one pile, and CR 608.2b judges each one: a card gone in
    response is not made up for."""
    from engine.stack_targets import chosen_targets

    game, (dealer,) = _w1g7_table(set_pool, mine=["Rag Dealer"], interactive={0, 1})
    lea = set_pool("LEA")
    game.players[0].graveyard.extend([lea["Forest"], lea["Grizzly Bears"]])
    game.players[1].graveyard.extend(
        [lea["Swamp"], lea["Hill Giant"], lea["Terror"], lea["Island"]]
    )
    spec = game.activation_target_spec(0, 0, ability_index=0)
    assert spec["single_graveyard"] and spec["max_targets"] == 3
    assert {t["seat"] for t in spec["valid_targets"]} == {0, 1}
    # Unnamed pile, a fourth slot: refused, nothing paid.
    assert not game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_permanent_index=[0, 1],
    ).supported
    assert not game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_player_index=1,
        target_permanent_index=[0, 1, 2, 3],
    ).supported
    assert not dealer.tapped
    assert game.queue_permanent_ability(
        0, "Rag Dealer", ability_index=0, target_player_index=1,
        target_permanent_index=[1, 2, 3],
    ).supported
    assert [t.stamp.card.name for t in chosen_targets(game, game.stack[-1])] == [
        "Hill Giant", "Terror", "Island",
    ]
    victim = game.players[1]
    victim.exile.append(victim.graveyard.pop(1))       # Hill Giant, in response
    _w1g7_settle(game)
    assert [c.name for c in victim.graveyard] == ["Swamp"]
    assert sorted(c.name for c in victim.exile) == ["Hill Giant", "Island", "Terror"]
    assert [c.name for c in game.players[0].graveyard] == ["Forest", "Grizzly Bears"]
    assert dealer.tapped


def test_w1g7_hisoka_reads_an_x_spells_mana_value_on_the_stack(set_pool):
    """CR 202.3e: Fireball cast for X=3 has mana value 4 on the stack."""
    game, wurm = _w1g7_hisoka_against(
        set_pool, "Fireball", "Wrath of God",
        lambda wurm: {"target_player_index": 0, "x_value": 3},
    )
    assert game.players[0].life == 20
    assert [c.name for c in game.players[1].graveyard] == ["Fireball"]

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================
