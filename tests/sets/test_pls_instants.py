"""Planeshift instants.

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

Cards come from `set_pool("PLS")` / `set_cards("PLS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: non-mana kicker ---
#
# "Kicker—Sacrifice a land." on five instants, the second sentence each one
# prints about being kicked (CR 702.33d/g), Orim's Chant's cast ban, and Death
# Bomb's mandatory twin of the same cost. Imports are in this block, per the
# header's parallel-authorship convention.

import pytest as _w1g1_pytest

from engine import Game as _W1G1Game
from engine import PlayerState as _W1G1PlayerState
from engine.ai_policy import choose_cast_action as _w1g1_choose_cast_action
from engine.cast_costs import kicker_cost as _w1g1_kicker_cost
from engine.models import Permanent as _W1G1Permanent
from tests.helpers import _damage_dealt as _w1g1_damage_dealt
from tests.helpers import resolve_stack as _w1g1_resolve_stack

_W1G1_RICH = {"W": 12, "U": 12, "B": 12, "R": 12, "G": 12}


def _w1g1_card(set_pool, name):
    pls = set_pool("PLS")
    return pls[name] if name in pls else set_pool("LEA")[name]  # _w1g1_card (instants)


def _w1g1_duel(set_pool, hand, *, pool=None, their_hand=()):
    """A two-seat game that **charges mana**, seat 0 holding *hand* with *pool*
    floating; seat 1 holds *their_hand* with mana of its own."""
    forest = set_pool("LEA")["Forest"]
    mine = _W1G1PlayerState(
        "Kicker", library=[forest] * 10,
        hand=[_w1g1_card(set_pool, name) for name in hand],
    )
    theirs = _W1G1PlayerState(
        "Bystander", library=[forest] * 10,
        hand=[_w1g1_card(set_pool, name) for name in their_hand],
    )
    game = _W1G1Game(players=[mine, theirs])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(_W1G1_RICH if pool is None else pool)
    game.players[1].mana_pool.update(_W1G1_RICH)
    return game  # _w1g1_duel (instants)


def _w1g1_put(game, seat, card):
    permanent = _W1G1Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g1_put (instants)


def _w1g1_names(game, seat):
    return sorted(p.card.name for p in game.controlled_by(seat))  # _w1g1_names (instants)


def _w1g1_key(set_pool, name):
    return _w1g1_kicker_cost(set_pool("PLS")[name].oracle_text)  # _w1g1_key (instants)


# -- Falling Timber ----------------------------------------------------------


def _w1g1_timber_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Falling Timber"])
    land = _w1g1_put(game, 0, lea["Forest"])
    bears = _w1g1_put(game, 1, lea["Grizzly Bears"])
    giant = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, land, bears, giant  # _w1g1_timber_table


def test_w1g1_falling_timber_unkicked_names_one_creature_and_stops_only_it(set_pool):
    """CR 702.33g: the second target belongs to a kicked cast alone. An unkicked
    Falling Timber is a one-target spell — this was refused "requires 2
    targets", because the two targets are one roles announcement and the role
    list sat on the step *outside* the kicked arm."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Falling Timber"], optional_cost_payments={})
    assert spec["kind"] == "creature" and len(spec["valid_targets"]) == 2

    result = game.cast_from_hand(
        0, "Falling Timber", target_permanent_ids=[bears.permanent_id]
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    me = game.players[0]
    assert _w1g1_damage_dealt(game, me, 2, source=bears, combat=True) == 0
    assert _w1g1_damage_dealt(game, me, 3, source=giant, combat=True) == 3
    assert _w1g1_damage_dealt(game, me, 2, source=bears) == 2, "combat damage only"
    assert game.is_on_battlefield(land), "no kicker, no land"


def test_w1g1_falling_timber_kicked_sacrifices_the_land_and_stops_both(set_pool):
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    key = _w1g1_key(set_pool, "Falling Timber")
    assert key == "sacrifice a land"

    result = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    me = game.players[0]
    assert not game.is_on_battlefield(land)
    assert _w1g1_damage_dealt(game, me, 2, source=bears, combat=True) == 0
    assert _w1g1_damage_dealt(game, me, 3, source=giant, combat=True) == 0


def test_w1g1_falling_timbers_two_targets_are_two_and_only_when_kicked(set_pool):
    """Both directions of CR 702.33g, and the printed "another" (CR 601.2c).
    Each refusal lands before anything is paid: the land is still there."""
    key = _w1g1_key(set_pool, "Falling Timber")

    game, land, bears, giant = _w1g1_timber_table(set_pool)
    two_unkicked = game.cast_from_hand(
        0, "Falling Timber",
        target_permanent_ids=[bears.permanent_id, giant.permanent_id],
    )
    assert not two_unkicked.supported and "702.33g" in two_unkicked.details

    one_kicked = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert not one_kicked.supported and "2 targets" in one_kicked.details

    same_twice = game.cast_from_hand(
        0, "Falling Timber", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, bears.permanent_id],
        cost_permanent_ids=[land.permanent_id],
    )
    assert not same_twice.supported
    assert game.is_on_battlefield(land)
    assert [c.name for c in game.players[0].hand] == ["Falling Timber"]


def test_w1g1_an_unkicked_falling_timber_cannot_be_aimed_at_a_land(set_pool):
    """The named target of the *unkicked* cast is checked against the one-target
    spec. Read as the whole card it is a roles spell, which the named-target
    gate hands on — and the gate it hands on to no longer saw roles."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    refused = game.cast_from_hand(
        0, "Falling Timber", target_permanent_ids=[land.permanent_id]
    )
    assert not refused.supported
    assert sum(game.players[0].mana_pool.values()) == sum(_W1G1_RICH.values())


def test_w1g1_a_kicked_falling_timber_offers_the_land_it_sacrifices(set_pool):
    """The kicked spec is roles *and* a cost picker — the first such pair, and
    the roles branch returned before filling the cost's candidates, so the
    picker described a land to give up and offered none."""
    game, land, bears, giant = _w1g1_timber_table(set_pool)
    key = _w1g1_key(set_pool, "Falling Timber")
    spec = game.cast_target_spec(
        0, set_pool("PLS")["Falling Timber"], optional_cost_payments={key: 1}
    )
    assert [role["role"] for role in spec["roles"]] == ["creature", "another creature"]
    assert spec["cost_spec"]["sacrifice_cost"] and spec["cost_spec"]["kind"] == "land"
    assert [t["name"] for t in spec["cost_spec"]["valid_targets"]] == ["Forest"]
    first = spec["valid_targets"][0]
    assert first["name"] == "Grizzly Bears"
    assert [t["name"] for t in first["next"]] == ["Hill Giant"], "never the same one"


# -- Rushing River -----------------------------------------------------------


def _w1g1_river_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Rushing River"])
    island = _w1g1_put(game, 0, lea["Island"])
    bears = _w1g1_put(game, 1, lea["Grizzly Bears"])
    ring = _w1g1_put(game, 1, lea["Sol Ring"])
    their_land = _w1g1_put(game, 1, lea["Forest"])
    return game, island, bears, ring, their_land  # _w1g1_river_table


def test_w1g1_rushing_river_unkicked_bounces_one_nonland_permanent(set_pool):
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Rushing River"], optional_cost_payments={})
    assert sorted(t["name"] for t in spec["valid_targets"]) == ["Grizzly Bears", "Sol Ring"]

    assert game.cast_from_hand(
        0, "Rushing River", target_permanent_ids=[ring.permanent_id]
    ).supported
    _w1g1_resolve_stack(game)
    assert [c.name for c in game.players[1].hand] == ["Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest", "Grizzly Bears"]
    assert game.is_on_battlefield(island)


def test_w1g1_rushing_river_kicked_bounces_two_for_a_land(set_pool):
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    result = game.cast_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, ring.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert sorted(c.name for c in game.players[1].hand) == ["Grizzly Bears", "Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest"]
    assert not game.is_on_battlefield(island)


def test_w1g1_rushing_river_never_names_a_land_in_either_slot(set_pool):
    """"Nonland" is printed on both targets, and both are enforced at the
    announcement (CR 601.2c) with nothing paid."""
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    assert not game.cast_from_hand(
        0, "Rushing River", target_permanent_ids=[their_land.permanent_id]
    ).supported
    assert not game.cast_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, their_land.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    ).supported
    assert game.is_on_battlefield(island)
    assert [c.name for c in game.players[0].hand] == ["Rushing River"]


def test_w1g1_a_kicked_river_whose_first_target_left_still_bounces_the_second(set_pool):
    """CR 608.2b: one of two targets gone is a spell that still resolves, and
    the step whose object left does nothing — it must not slide onto the other
    creature, nor skip the kicked half."""
    game, island, bears, ring, their_land = _w1g1_river_table(set_pool)
    key = _w1g1_key(set_pool, "Rushing River")
    assert game.queue_from_hand(
        0, "Rushing River", optional_cost_payments={key: 1},
        target_permanent_ids=[bears.permanent_id, ring.permanent_id],
        cost_permanent_ids=[island.permanent_id],
    ).supported
    game.remove_from_battlefield(bears)
    _w1g1_resolve_stack(game)
    assert [c.name for c in game.players[1].hand] == ["Sol Ring"]
    assert _w1g1_names(game, 1) == ["Forest"]


def _w1g1_ai_table(set_pool, name, land, lands):
    """Seat 0 on its own main phase holding *name* with *lands* untapped copies
    of *land* and an empty pool, a creature on each side and an artifact."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, [name], pool={})
    for _ in range(lands):
        _w1g1_put(game, 0, lea[land])
    _w1g1_put(game, 0, lea["Grizzly Bears"])
    _w1g1_put(game, 1, lea["Hill Giant"])
    _w1g1_put(game, 1, lea["Sol Ring"])
    game.active_player_index = 0
    game.current_phase = "main"
    return game  # _w1g1_ai_table


@_w1g1_pytest.mark.parametrize(
    "name,land", [("Rushing River", "Island"), ("Falling Timber", "Forest")]
)
def test_w1g1_the_ai_casts_the_plain_spell_when_it_cannot_spare_the_kick(
    set_pool, name, land
):
    """It must not stall. With four lands the seat declines the kicker — and
    then has to be able to build the *unkicked* cast, whose one target the
    engine's enumeration probes against the unkicked spec. Probed against the
    card's every arm (two roles) no single target was ever legal, so the seat
    held both cards until it had a land to spare; and the cast it proposes is
    one the engine accepts."""
    game = _w1g1_ai_table(set_pool, name, land, lands=4)
    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == name
    assert not action.optional_cost_payments
    assert len(action.target_permanent_ids) == 1

    from engine.ai_policy import tap_planned_lands

    tap_planned_lands(game, 0, action)
    result = game.cast_from_hand(
        0, name, target_player_index=action.target_player_index,
        target_permanent_index=action.target_permanent_index,
        target_permanent_ids=action.target_permanent_ids,
    )
    assert result.supported, result.details


@_w1g1_pytest.mark.parametrize(
    "name,land", [("Rushing River", "Island"), ("Falling Timber", "Forest")]
)
def test_w1g1_the_ai_names_two_targets_for_the_spell_it_kicks(set_pool, name, land):
    """…and with nine it kicks, walking the *kicked* spec's chain of two
    roles rather than the unkicked picker's flat list."""
    game = _w1g1_ai_table(set_pool, name, land, lands=9)
    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == name
    assert action.optional_cost_payments == {_w1g1_key(set_pool, name): 1}
    assert len(set(action.target_permanent_ids)) == 2


# -- Magma Burst -------------------------------------------------------------


def _w1g1_burst_table(set_pool, mountains=3):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"])
    lands = [_w1g1_put(game, 0, lea["Mountain"]) for _ in range(mountains)]
    giant = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, lands, giant  # _w1g1_burst_table


def test_w1g1_magma_burst_unkicked_is_three_damage_to_one_target(set_pool):
    game, lands, giant = _w1g1_burst_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("PLS")["Magma Burst"], optional_cost_payments={})
    assert spec["kind"] == "any"
    assert game.cast_from_hand(0, "Magma Burst", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert game.players[1].life == 17
    assert game.is_on_battlefield(giant) and len(_w1g1_names(game, 0)) == 3


def test_w1g1_magma_burst_kicked_deals_three_to_each_of_two_targets(set_pool):
    """Kicked: two lands, and 3 damage to *each* of two different targets — a
    creature and a face here, which is why this is a cross-seat list and not
    two roles. It dealt 1 and 1: the division gate read the card's every arm,
    found no divided step under the kicked arm, stamped no share, and the
    handler fell back to the even split of 3."""
    game, lands, giant = _w1g1_burst_table(set_pool)
    key = _w1g1_key(set_pool, "Magma Burst")
    assert key == "sacrifice two lands"
    spec = game.cast_target_spec(
        0, set_pool("PLS")["Magma Burst"], optional_cost_payments={key: 1}
    )
    assert (spec["kind"], spec["division"], spec["divided_target_count"]) == (
        "divided", "each", 2,
    )
    assert spec["cost_spec"]["count"] == 2

    result = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, 0), (1, None)],
        cost_permanent_ids=[lands[0].permanent_id, lands[2].permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)

    assert game.players[1].life == 17
    assert not game.is_on_battlefield(giant), "3 damage, not a 1/1 split"
    assert [p.permanent_id for p in game.controlled_by(0)] == [lands[1].permanent_id]


def test_w1g1_magma_bursts_kicked_targets_are_exactly_two_different_ones(set_pool):
    """CR 601.2c: "another target" is a different one, and a kicked Magma Burst
    has two — not one, and not the same face twice. Each is refused before the
    lands are sacrificed."""
    game, lands, giant = _w1g1_burst_table(set_pool)
    key = _w1g1_key(set_pool, "Magma Burst")
    for announced in (
        {"divided_targets": [(1, None), (1, None)]},
        {"divided_targets": [(1, None)]},
        {"target_player_index": 1},
    ):
        refused = game.cast_from_hand(
            0, "Magma Burst", optional_cost_payments={key: 1}, **announced
        )
        assert not refused.supported, announced
    assert len(_w1g1_names(game, 0)) == 3
    assert game.players[1].life == 20

    both_faces = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, None), (0, None)],
    )
    assert both_faces.supported, both_faces.details
    _w1g1_resolve_stack(game)
    assert (game.players[0].life, game.players[1].life) == (17, 17)


def test_w1g1_magma_burst_cannot_be_kicked_with_one_land(set_pool):
    game, lands, giant = _w1g1_burst_table(set_pool, mountains=1)
    key = _w1g1_key(set_pool, "Magma Burst")
    refused = game.cast_from_hand(
        0, "Magma Burst", optional_cost_payments={key: 1},
        divided_targets=[(1, 0), (1, None)],
    )
    assert not refused.supported and "601.2h" in refused.details
    assert game.is_on_battlefield(lands[0])


def test_w1g1_the_ai_announces_two_targets_for_a_magma_burst_it_kicks(set_pool):
    """A kicked candidate is built against the kicked spec. The AI's divided
    chooser read the card's every arm (no divided step) and the unkicked
    picker, so a kicked Magma Burst went out with one bare target and was
    refused. Eight Mountains: enough to pay {3}{R} and still spare two."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"], pool={})
    for _ in range(8):
        _w1g1_put(game, 0, lea["Mountain"])
    _w1g1_put(game, 1, lea["Hill Giant"])
    game.active_player_index = 0
    game.current_phase = "main"
    key = _w1g1_key(set_pool, "Magma Burst")

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magma Burst"
    assert action.optional_cost_payments == {key: 1}
    assert len(action.divided_targets) == 2
    assert len(set(tuple(entry[:2]) for entry in action.divided_targets)) == 2


def test_w1g1_the_ai_keeps_its_lands_when_it_has_four(set_pool):
    """It must not sacrifice half its mana for a marginal kick: four lands cast
    the plain spell, kicker declined, one target named."""
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Magma Burst"], pool={})
    for _ in range(4):
        _w1g1_put(game, 0, lea["Mountain"])
    game.active_player_index = 0
    game.current_phase = "main"

    action = _w1g1_choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Magma Burst"
    assert not action.optional_cost_payments and not action.divided_targets


# -- Pollen Remedy -----------------------------------------------------------


def _w1g1_remedy_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Pollen Remedy"])
    plains = _w1g1_put(game, 0, lea["Plains"])
    bears = _w1g1_put(game, 0, lea["Grizzly Bears"])
    return game, plains, bears  # _w1g1_remedy_table


def test_w1g1_pollen_remedy_unkicked_divides_three(set_pool):
    game, plains, bears = _w1g1_remedy_table(set_pool)
    result = game.cast_from_hand(
        0, "Pollen Remedy", divided_targets=[(0, 1, 1), (0, None, 2)]
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert _w1g1_damage_dealt(game, game.players[0], 5) == 3
    assert _w1g1_damage_dealt(game, bears, 9) == 8
    assert game.is_on_battlefield(plains)


def test_w1g1_pollen_remedy_kicked_divides_six_this_way(set_pool):
    """"…prevent the next 6 damage **this way** instead." The replaced
    sentence at another size: the same targets, the same division, six where
    there were three — one shield, not three and then six."""
    game, plains, bears = _w1g1_remedy_table(set_pool)
    key = _w1g1_key(set_pool, "Pollen Remedy")
    result = game.cast_from_hand(
        0, "Pollen Remedy", optional_cost_payments={key: 1},
        divided_targets=[(0, 1, 4), (0, None, 2)],
        cost_permanent_ids=[plains.permanent_id],
    )
    assert result.supported, result.details
    _w1g1_resolve_stack(game)
    assert not game.is_on_battlefield(plains)
    assert _w1g1_damage_dealt(game, game.players[0], 5) == 3
    assert _w1g1_damage_dealt(game, bears, 9) == 5, "four prevented, not seven"


def test_w1g1_pollen_remedys_division_totals_what_this_cast_prevents(set_pool):
    """CR 601.2d: the shares total the arm that will run — three unkicked, six
    kicked — and a division of the other arm's total is refused unpaid."""
    game, plains, bears = _w1g1_remedy_table(set_pool)
    key = _w1g1_key(set_pool, "Pollen Remedy")
    six_unkicked = game.cast_from_hand(
        0, "Pollen Remedy", divided_targets=[(0, 1, 4), (0, None, 2)]
    )
    assert not six_unkicked.supported and "total 3" in six_unkicked.details
    three_kicked = game.cast_from_hand(
        0, "Pollen Remedy", optional_cost_payments={key: 1},
        divided_targets=[(0, 1, 1), (0, None, 2)],
        cost_permanent_ids=[plains.permanent_id],
    )
    assert not three_kicked.supported and "total 6" in three_kicked.details
    assert game.is_on_battlefield(plains)


# -- Orim's Chant ------------------------------------------------------------


def _w1g1_chant_table(set_pool):
    """Seat 1's turn: it holds an instant, a creature spell and a land; seat 0
    holds Orim's Chant."""
    lea = set_pool("LEA")
    game = _w1g1_duel(
        set_pool, ["Orim's Chant"],
        their_hand=["Lightning Bolt", "Grizzly Bears", "Forest"],
    )
    game.active_player_index = 1
    game.current_phase = "main"
    attacker = _w1g1_put(game, 1, lea["Hill Giant"])
    return game, attacker  # _w1g1_chant_table


def test_w1g1_orims_chant_stops_every_spell_and_no_land_drop(set_pool):
    """"Target player can't cast spells this turn." No type printed, so every
    spell — and a land is not one (CR 305.1), so the land drop goes through.
    Each refused cast costs the player nothing."""
    game, attacker = _w1g1_chant_table(set_pool)
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)

    before = sum(game.players[1].mana_pool.values())
    for name in ("Lightning Bolt", "Grizzly Bears"):
        refused = game.cast_from_hand(1, name, target_player_index=0)
        assert not refused.supported and "can't cast any spells" in refused.details
    assert sum(game.players[1].mana_pool.values()) == before
    assert game.cast_from_hand(1, "Forest").supported
    assert "Forest" in _w1g1_names(game, 1)

    # …and the caster is not bound by its own Chant.
    assert not game.spell_types_forbidden_this_turn.get(0)


def test_w1g1_orims_chant_unkicked_leaves_creatures_free_to_attack(set_pool):
    game, attacker = _w1g1_chant_table(set_pool)
    before = sum(game.players[0].mana_pool.values())
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert before - sum(game.players[0].mana_pool.values()) == 1
    assert game.can_attack(attacker, 0)


def test_w1g1_orims_chant_kicked_also_stops_every_attack(set_pool):
    """Kicker {W}: "…creatures can't attack this turn." — every creature, the
    caster's own included, and one that arrives after the Chant resolved."""
    lea = set_pool("LEA")
    game, attacker = _w1g1_chant_table(set_pool)
    mine = _w1g1_put(game, 0, lea["Grizzly Bears"])
    key = _w1g1_key(set_pool, "Orim's Chant")
    assert key == "{W}"
    before = sum(game.players[0].mana_pool.values())
    assert game.cast_from_hand(
        0, "Orim's Chant", target_player_index=1, optional_cost_payments={key: 1}
    ).supported
    _w1g1_resolve_stack(game)
    assert before - sum(game.players[0].mana_pool.values()) == 2

    assert not game.can_attack(attacker, 0)
    assert not game.can_attack(mine, 1)
    late = _w1g1_put(game, 1, lea["Grizzly Bears"])
    assert not game.can_attack(late, 0)


def test_w1g1_orims_chant_ends_with_the_turn(set_pool):
    """"This turn": the record is dropped at the turn boundary, and the player
    casts again."""
    from engine.spell_prohibitions import clear_turn_spell_prohibitions

    game, attacker = _w1g1_chant_table(set_pool)
    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    assert not game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported

    clear_turn_spell_prohibitions(game)
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported


def test_w1g1_a_seat_under_orims_chant_proposes_no_spell(set_pool):
    """A banned seat reads as unable to cast rather than being refused each
    time it tries: the AI's proposal filter asks the record the cast path
    refuses by, and still plays its land."""
    game, attacker = _w1g1_chant_table(set_pool)
    assert _w1g1_choose_cast_action(game, 1) is not None, "it had something to cast"

    assert game.cast_from_hand(0, "Orim's Chant", target_player_index=1).supported
    _w1g1_resolve_stack(game)
    proposed = _w1g1_choose_cast_action(game, 1)
    assert proposed is None or proposed.card_name == "Forest"


# -- Death Bomb --------------------------------------------------------------


def _w1g1_bomb_table(set_pool):
    lea = set_pool("LEA")
    game = _w1g1_duel(set_pool, ["Death Bomb"])
    fodder = _w1g1_put(game, 0, lea["Grizzly Bears"])
    keeper = _w1g1_put(game, 0, lea["Hill Giant"])
    victim = _w1g1_put(game, 1, lea["Hill Giant"])
    black = _w1g1_put(game, 1, lea["Drudge Skeletons"])
    return game, fodder, keeper, victim, black  # _w1g1_bomb_table


def test_w1g1_death_bomb_sacrifices_the_creature_named_and_kills_its_target(set_pool):
    """The mandatory twin of the kicker's cost: the creature the caster names
    is sacrificed as the spell is cast, the target is destroyed and cannot be
    regenerated, and its controller loses 2 life."""
    game, fodder, keeper, victim, black = _w1g1_bomb_table(set_pool)
    victim.regeneration_shield = 1
    before = sum(game.players[0].mana_pool.values())

    result = game.queue_from_hand(
        0, "Death Bomb", target_permanent_ids=[victim.permanent_id],
        cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result.details
    assert not game.is_on_battlefield(fodder), "paid on the way to the stack"
    assert before - sum(game.players[0].mana_pool.values()) == 4
    _w1g1_resolve_stack(game)

    assert not game.is_on_battlefield(victim), "the shield does not save it"
    assert game.is_on_battlefield(keeper) and game.is_on_battlefield(black)
    assert game.players[1].life == 18


def test_w1g1_death_bomb_is_refused_unpaid_without_a_creature_or_a_nonblack_target(set_pool):
    """CR 601.2h and CR 601.2c, each before any mana leaves the pool: no
    creature to sacrifice, and a black creature as the target."""
    lea = set_pool("LEA")
    full = sum(_W1G1_RICH.values())

    game = _w1g1_duel(set_pool, ["Death Bomb"])
    victim = _w1g1_put(game, 1, lea["Hill Giant"])
    unpaid = game.cast_from_hand(
        0, "Death Bomb", target_permanent_ids=[victim.permanent_id]
    )
    assert not unpaid.supported and "601.2h" in unpaid.details
    assert sum(game.players[0].mana_pool.values()) == full
    assert _w1g1_choose_cast_action(game, 0) is None, "nor does the AI propose it"

    game, fodder, keeper, victim, black = _w1g1_bomb_table(set_pool)
    at_black = game.cast_from_hand(
        0, "Death Bomb", target_permanent_ids=[black.permanent_id]
    )
    assert not at_black.supported
    assert game.is_on_battlefield(fodder) and game.is_on_battlefield(keeper)
    assert sum(game.players[0].mana_pool.values()) == full
