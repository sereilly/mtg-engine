"""Apocalypse instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and nine branches editing nine disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("APC")` / `set_cards("APC")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ============================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ========================================================


# ==== W1G2 ============================================================
# W1G2's tests go between this line and the "end W1G2" line.
import pytest as _w1g2_pytest

from engine import Game as _W1G2Game
from engine import PlayerState as _W1G2PlayerState
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import resolve_stack as _w1g2_resolve_stack


def _w1g2_table(set_pool, hand=(), mana=None, opp_hand=(), opp_mana=None):
    """A two-seat game with mana costs enforced. *hand* names Apocalypse cards
    (or Alpha ones, for a caster who holds a Lightning Bolt beside its spell);
    *opp_hand* is Alpha."""
    lea, apc = set_pool("LEA"), set_pool("APC")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[apc[name] if name in apc else lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (instants)


def _w1g2_put(game, set_pool, seat, name, code="LEA"):
    """*name* onto *seat*'s battlefield, able to act this turn."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (instants)


def _w1g2_slot(game, seat, permanent):
    """*permanent*'s slot on *seat*'s battlefield — a ``divided_targets``
    entry is ``(seat, slot)``, which is how that announcement names a
    permanent; the cast path stamps the id."""
    return list(game.controlled_by(seat)).index(permanent)  # _w1g2_slot (instants)


def _w1g2_stats(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # _w1g2_stats (instants)


# Strength of Night ----------------------------------------------------------


@_w1g2_pytest.mark.parametrize("kicked, zombies, spare_mana", [
    (False, (3, 3), 1),
    (True, (5, 5), 0),
])
def test_w1g2_strength_of_night_gives_zombies_the_additional_pump_only_when_kicked(
    set_pool, kicked, zombies, spare_mana,
):
    """"Creatures you control get +1/+1 until end of turn. If this spell was
    kicked, Zombie creatures you control get an additional +2/+2 until end of
    turn." Unkicked, every creature of the caster's is +1/+1 and nothing more;
    kicked for {B}, the Zombie is +3/+3 in all and the Bears still +1/+1. The
    opponent's own Zombie gets neither."""
    game = _w1g2_table(set_pool, ["Strength of Night"], {"G": 3, "B": 1})
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    mine = _w1g2_put(game, set_pool, 0, "Scathe Zombies")
    theirs = _w1g2_put(game, set_pool, 1, "Scathe Zombies")

    result = game.cast_from_hand(
        0, "Strength of Night",
        optional_cost_payments={"{B}": 1} if kicked else None,
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert _w1g2_stats(bears) == (3, 3)
    assert _w1g2_stats(mine) == zombies
    assert _w1g2_stats(theirs) == (2, 2)
    assert sum(game.players[0].mana_pool.values()) == spare_mana
    assert [card.name for card in game.players[0].graveyard] == ["Strength of Night"]


# Orim's Thunder -------------------------------------------------------------


def _w1g2_thunder_table(set_pool):
    """Orim's Thunder in hand with {R} for the kicker; across the table a
    Jayemdae Tome (mana value 4), a Crusade (2) and a Hill Giant (3/3)."""
    game = _w1g2_table(set_pool, ["Orim's Thunder"], {"W": 3, "R": 1})
    tome = _w1g2_put(game, set_pool, 1, "Jayemdae Tome")
    crusade = _w1g2_put(game, set_pool, 1, "Crusade")
    giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    return game, tome, crusade, giant  # _w1g2_thunder_table


def test_w1g2_orims_thunder_unkicked_destroys_and_names_one_target(set_pool):
    """Unkicked it is a Disenchant: one target, the artifact goes, the {R} is
    still in the pool, and the picker offers the artifact and the enchantment
    and no creature (CR 702.33g: the kicked-only target is not chosen)."""
    game, tome, crusade, giant = _w1g2_thunder_table(set_pool)
    spec = game.cast_target_spec(0, set_pool("APC")["Orim's Thunder"])
    assert sorted(target["name"] for target in spec["valid_targets"]) == [
        "Crusade", "Jayemdae Tome",
    ]

    result = game.cast_from_hand(
        0, "Orim's Thunder", target_permanent_ids=[tome.permanent_id],
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert not game.is_on_battlefield(tome)
    assert game.is_on_battlefield(crusade) and game.is_on_battlefield(giant)
    assert giant.damage_marked == 0
    assert game.players[0].mana_pool["R"] == 1


@_w1g2_pytest.mark.parametrize("victim, damage", [("Crusade", 2), ("Jayemdae Tome", 4)])
def test_w1g2_orims_thunder_kicked_deals_the_destroyed_permanents_mana_value(
    set_pool, victim, damage,
):
    """"If this spell was kicked, it deals damage equal to that permanent's
    mana value to target creature." The number is the destroyed permanent's —
    2 for the Crusade, which a 3/3 survives, and 4 for the Tome, which it does
    not — read after the permanent has left (CR 608.2h)."""
    game, tome, crusade, giant = _w1g2_thunder_table(set_pool)
    chosen = crusade if victim == "Crusade" else tome

    result = game.cast_from_hand(
        0, "Orim's Thunder",
        target_permanent_ids=[chosen.permanent_id, giant.permanent_id],
        optional_cost_payments={"{R}": 1},
    )
    _w1g2_resolve_stack(game)

    assert result.supported, result.details
    assert not game.is_on_battlefield(chosen)
    assert giant.damage_marked == damage
    assert f"Orim's Thunder dealt {damage} damage to Hill Giant" in game.log
    game.check_state_based_actions()
    assert game.is_on_battlefield(giant) is (damage < 3)
    assert sum(game.players[0].mana_pool.values()) == 0


def test_w1g2_orims_thunder_announcement_is_held_to_the_kicker(set_pool):
    """CR 702.33g at the announcement, both ways: a kicked cast owes the
    creature target and an unkicked one may not name it. And each slot is held
    to its own noun — a creature is no artifact or enchantment, an enchantment
    no creature. Every refusal leaves the card in hand and the mana unspent."""
    game, tome, crusade, giant = _w1g2_thunder_table(set_pool)
    kicked = {"{R}": 1}
    attempts = [
        ([tome.permanent_id], kicked),
        ([tome.permanent_id, giant.permanent_id], None),
        ([giant.permanent_id, giant.permanent_id], kicked),
        ([tome.permanent_id, crusade.permanent_id], kicked),
    ]

    for ids, payments in attempts:
        result = game.cast_from_hand(
            0, "Orim's Thunder", target_permanent_ids=ids,
            optional_cost_payments=payments,
        )
        assert not result.supported, (ids, payments)

    assert [card.name for card in game.players[0].hand] == ["Orim's Thunder"]
    assert sum(game.players[0].mana_pool.values()) == 4
    assert not game.stack
    assert game.is_on_battlefield(tome) and giant.damage_marked == 0


def test_w1g2_orims_thunder_cannot_measure_a_permanent_that_left(set_pool):
    """The card's ruling: "If Orim's Thunder is kicked, but the artifact or
    enchantment is an illegal target as Orim's Thunder tries to resolve, [it]
    won't be able to determine the artifact or enchantment's mana value. No
    damage will be dealt to the target creature … If only the creature has
    become an illegal target, the artifact or enchantment will still be
    destroyed." (CR 608.2b.)"""
    game, tome, _crusade, giant = _w1g2_thunder_table(set_pool)
    game.queue_from_hand(
        0, "Orim's Thunder",
        target_permanent_ids=[tome.permanent_id, giant.permanent_id],
        optional_cost_payments={"{R}": 1},
    )
    game.remove_from_battlefield(tome)
    _w1g2_resolve_stack(game)
    assert giant.damage_marked == 0 and game.is_on_battlefield(giant)

    game, tome, _crusade, giant = _w1g2_thunder_table(set_pool)
    game.queue_from_hand(
        0, "Orim's Thunder",
        target_permanent_ids=[tome.permanent_id, giant.permanent_id],
        optional_cost_payments={"{R}": 1},
    )
    game.remove_from_battlefield(giant)
    _w1g2_resolve_stack(game)
    assert not game.is_on_battlefield(tome)
    assert "Jayemdae Tome" in [card.name for card in game.players[1].graveyard]


# Captain's Maneuver ---------------------------------------------------------


def _w1g2_maneuver_table(set_pool, x):
    """Captain's Maneuver in hand with exactly {X}{R}{W}; the caster holds a
    Hill Giant, the opponent Grizzly Bears, a Mountain and three red mana for
    the Lightning Bolts in hand."""
    game = _w1g2_table(
        set_pool, ["Captain's Maneuver"], {"R": 1 + x, "W": 1},
        opp_hand=["Lightning Bolt", "Lightning Bolt"], opp_mana={"R": 3},
    )
    giant = _w1g2_put(game, set_pool, 0, "Hill Giant")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    mountain = _w1g2_put(game, set_pool, 1, "Mountain")
    return game, giant, bears, mountain  # _w1g2_maneuver_table


def _w1g2_bolt(game, permanent=None, seat=0):
    """The opponent's Lightning Bolt at *permanent*, or at *seat*'s face."""
    result = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=seat,
        **({"target_permanent_ids": [permanent.permanent_id]} if permanent else {}),
    )
    assert result.supported, result.details
    game.check_state_based_actions()  # _w1g2_bolt


def test_w1g2_captains_maneuver_offers_two_any_targets_and_no_land(set_pool):
    """Two instances of "target creature, planeswalker, or player" (CR 115.4):
    the picker asks for exactly two, offers both faces and both creatures, and
    does not offer the Mountain. X is announced."""
    game, giant, bears, _mountain = _w1g2_maneuver_table(set_pool, 3)

    spec = game.cast_target_spec(0, set_pool("APC")["Captain's Maneuver"])

    assert spec["kind"] == "divided" and spec["divided_target_count"] == 2
    assert spec["announces_x"]
    offered = sorted(
        (target["kind"], target["seat"], target.get("name") or "")
        for target in spec["valid_targets"]
    )
    assert offered == [
        ("permanent", 0, "Hill Giant"), ("permanent", 1, "Grizzly Bears"),
        ("player", 0, ""), ("player", 1, ""),
    ]


def test_w1g2_captains_maneuver_moves_the_next_x_damage_to_the_other_target(set_pool):
    """X = 3, the caster's Hill Giant protected and the opponent's Bears to
    take it. The Bolt aimed at the Giant is dealt to the Bears instead: the
    Giant is unmarked, the Bears die, and the caster has spent X plus {R}{W}."""
    game, giant, bears, _mountain = _w1g2_maneuver_table(set_pool, 3)

    result = game.cast_from_hand(
        0, "Captain's Maneuver", x_value=3,
        divided_targets=[
            (0, _w1g2_slot(game, 0, giant)), (1, _w1g2_slot(game, 1, bears)),
        ],
    )
    assert result.supported, result.details
    assert sum(game.players[0].mana_pool.values()) == 0
    assert (
        "Captain's Maneuver: the next 3 damage that would be dealt to Hill "
        "Giant this turn is dealt to Grizzly Bears instead" in game.log
    )

    _w1g2_bolt(game, giant)

    assert giant.damage_marked == 0 and game.is_on_battlefield(giant)
    assert not game.is_on_battlefield(bears)
    assert "Grizzly Bears" in [card.name for card in game.players[1].graveyard]


def test_w1g2_captains_maneuver_is_a_pool_of_x_points_between_two_players(set_pool):
    """Both targets may be players, and X is a point pool (CR 615.7's shape
    with CR 614.9's verb): at X = 2 a Bolt at the caster deals 2 to the
    opponent and 1 to the caster, and the next Bolt lands in full."""
    game, _giant, _bears, _mountain = _w1g2_maneuver_table(set_pool, 2)

    result = game.cast_from_hand(
        0, "Captain's Maneuver", x_value=2, divided_targets=[(0, None), (1, None)],
    )
    assert result.supported, result.details
    _w1g2_bolt(game)
    assert [player.life for player in game.players] == [19, 18]

    _w1g2_bolt(game)
    assert [player.life for player in game.players] == [16, 18]


def test_w1g2_captains_maneuver_spends_its_pool_across_events(set_pool):
    """X = 5 from the Giant to the opponent's face. The first Bolt moves 3 and
    leaves 2 in the pool; the second moves those 2 and marks the last point on
    the Giant."""
    game, giant, _bears, _mountain = _w1g2_maneuver_table(set_pool, 5)
    game.cast_from_hand(
        0, "Captain's Maneuver", x_value=5,
        divided_targets=[(0, _w1g2_slot(game, 0, giant)), (1, None)],
    )

    _w1g2_bolt(game, giant)
    assert (giant.damage_marked, game.players[1].life) == (0, 17)
    _w1g2_bolt(game, giant)
    assert (giant.damage_marked, game.players[1].life) == (1, 15)


def test_w1g2_captains_maneuver_refuses_an_announcement_that_is_not_two_targets(
    set_pool,
):
    """CR 601.2c: exactly two, and "another" means different. One target, the
    same creature twice, one player twice, a land, three targets and the old
    single-target channel are each refused with the card in hand and the mana
    unspent."""
    game, giant, bears, mountain = _w1g2_maneuver_table(set_pool, 3)
    mine = (0, _w1g2_slot(game, 0, giant))
    attempts = [
        [mine],
        [mine, mine],
        [(0, None), (0, None)],
        [mine, (1, _w1g2_slot(game, 1, mountain))],
        [(0, None), (1, None), (1, _w1g2_slot(game, 1, bears))],
        [],
    ]

    for divided in attempts:
        result = game.cast_from_hand(
            0, "Captain's Maneuver", x_value=3, divided_targets=divided,
        )
        assert not result.supported, divided
    assert not game.cast_from_hand(
        0, "Captain's Maneuver", x_value=3, target_player_index=1,
    ).supported

    assert [card.name for card in game.players[0].hand] == ["Captain's Maneuver"]
    assert sum(game.players[0].mana_pool.values()) == 5
    assert not game.stack


def test_w1g2_captains_maneuver_does_nothing_once_an_end_is_gone(set_pool):
    """The card's two rulings, and CR 614.9 behind them. A taker that leaves
    after the spell resolved: "the damage is dealt to the first target as if
    this spell was not cast". An end that left before it resolved: nothing is
    armed, and the survivor is never the taker of anything."""
    game, giant, bears, _mountain = _w1g2_maneuver_table(set_pool, 3)
    ends = [(0, _w1g2_slot(game, 0, giant)), (1, _w1g2_slot(game, 1, bears))]
    game.cast_from_hand(0, "Captain's Maneuver", x_value=3, divided_targets=ends)
    game.remove_from_battlefield(bears)
    _w1g2_bolt(game, giant)
    assert not game.is_on_battlefield(giant), "the Bolt landed where it was aimed"

    game, giant, bears, _mountain = _w1g2_maneuver_table(set_pool, 3)
    ends = [(0, _w1g2_slot(game, 0, giant)), (1, _w1g2_slot(game, 1, bears))]
    game.queue_from_hand(0, "Captain's Maneuver", x_value=3, divided_targets=ends)
    game.remove_from_battlefield(giant)
    _w1g2_resolve_stack(game)
    assert "Captain's Maneuver: one of its targets is gone, nothing is redirected" in game.log
    _w1g2_bolt(game, seat=0)
    assert game.is_on_battlefield(bears) and bears.damage_marked == 0
    assert game.players[0].life == 17


# Jilt -----------------------------------------------------------------------


@_w1g2_pytest.mark.parametrize("kicked", [False, True])
def test_w1g2_jilt_bounces_and_when_kicked_burns_another_creature(set_pool, kicked):
    """"Return target creature to its owner's hand. If this spell was kicked,
    it deals 2 damage to another target creature." Unkicked: one target, the
    Wurm goes home, {1}{R} stays in the pool. Kicked: the Wurm goes home and
    the Bears take 2 and die."""
    game = _w1g2_table(set_pool, ["Jilt"], {"U": 2, "R": 2})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")

    result = game.cast_from_hand(
        0, "Jilt",
        target_permanent_ids=(
            [wurm.permanent_id, bears.permanent_id] if kicked else [wurm.permanent_id]
        ),
        optional_cost_payments={"{1}{R}": 1} if kicked else None,
    )
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert [card.name for card in game.players[1].hand] == ["Craw Wurm"]
    assert game.is_on_battlefield(bears) is (not kicked)
    assert sum(game.players[0].mana_pool.values()) == (0 if kicked else 2)
    assert ("Jilt dealt 2 damage to Grizzly Bears" in game.log) is kicked


def test_w1g2_jilt_holds_its_targets_to_the_kicker_and_to_another(set_pool):
    """A kicked Jilt may not burn the creature it bounces ("another"), owes
    both targets, and an unkicked one may name only the first."""
    game = _w1g2_table(set_pool, ["Jilt"], {"U": 2, "R": 2})
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    kicked = {"{1}{R}": 1}

    for ids, payments in (
        ([wurm.permanent_id, wurm.permanent_id], kicked),
        ([wurm.permanent_id], kicked),
        ([wurm.permanent_id, bears.permanent_id], None),
    ):
        assert not game.cast_from_hand(
            0, "Jilt", target_permanent_ids=ids, optional_cost_payments=payments,
        ).supported, (ids, payments)

    assert [card.name for card in game.players[0].hand] == ["Jilt"]
    assert sum(game.players[0].mana_pool.values()) == 4


# Consume Strength -----------------------------------------------------------


def test_w1g2_consume_strength_pumps_one_creature_and_shrinks_another(set_pool):
    """"Target creature gets +2/+2 until end of turn. Another target creature
    gets -2/-2 until end of turn." The Bears are 4/4 and the 2/1 Lions die of
    toughness -1 (CR 704.5f)."""
    game = _w1g2_table(set_pool, ["Consume Strength"], {"B": 2, "G": 1})
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    lions = _w1g2_put(game, set_pool, 1, "Savannah Lions")

    result = game.cast_from_hand(
        0, "Consume Strength",
        target_permanent_ids=[bears.permanent_id, lions.permanent_id],
    )
    _w1g2_resolve_stack(game)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert _w1g2_stats(bears) == (4, 4)
    assert not game.is_on_battlefield(lions)
    assert "Savannah Lions" in [card.name for card in game.players[1].graveyard]


def test_w1g2_consume_strength_owes_both_of_its_targets(set_pool):
    """Two printed instances of the word "target" are two targets (CR 601.2c).
    Naming one made the card a +2/+2 with its drawback optional; naming one
    creature twice is "another" refused; and with one creature on the whole
    table the spell cannot be cast at all."""
    game = _w1g2_table(set_pool, ["Consume Strength"], {"B": 2, "G": 1})
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    card = set_pool("APC")["Consume Strength"]
    assert game.no_legal_cast_target_refusal(0, card) is not None

    lions = _w1g2_put(game, set_pool, 1, "Savannah Lions")
    assert game.no_legal_cast_target_refusal(0, card) is None
    spec = game.cast_target_spec(0, card)
    assert spec["exact_targets"] and spec["max_targets"] == 2

    for ids in ([bears.permanent_id], [bears.permanent_id, bears.permanent_id], []):
        assert not game.cast_from_hand(
            0, "Consume Strength", target_permanent_ids=ids,
        ).supported, ids
    assert _w1g2_stats(bears) == (2, 2) and game.is_on_battlefield(lions)
    assert sum(game.players[0].mana_pool.values()) == 3


def test_w1g2_consume_strength_keeps_each_slot_to_its_own_creature(set_pool):
    """CR 608.2b: with the first target gone the second still shrinks — and
    does not slide into the first slot and take the +2/+2 instead."""
    game = _w1g2_table(set_pool, ["Consume Strength"], {"B": 2, "G": 1})
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    game.queue_from_hand(
        0, "Consume Strength",
        target_permanent_ids=[bears.permanent_id, wurm.permanent_id],
    )
    game.remove_from_battlefield(bears)

    _w1g2_resolve_stack(game)

    assert _w1g2_stats(wurm) == (4, 2)

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================
