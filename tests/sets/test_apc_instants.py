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

from engine import Game as _w1g3i_Game, PlayerState as _w1g3i_Player
from engine.game_types import CardDefinition as _w1g3i_CardDefinition
from engine.models import Permanent as _w1g3i_Permanent
from tests.helpers import resolve_stack as _w1g3i_resolve_stack


def _w1g3i_card(name, type_line, power="2", toughness="2"):
    return _w1g3i_CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text="",
        colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": type_line, "power": power, "toughness": toughness},
    )  # W1G3 instants: a typed card


def _w1g3i_bolt_game(set_pool, *, theirs=(), interactive=()):
    """Prophetic Bolt in seat 0's hand over a five-card library."""
    board1 = [_w1g3i_Permanent(card=card) for card in theirs]
    library = [_w1g3i_card(f"Card {n}", "Land") for n in range(1, 6)]
    game = _w1g3i_Game(players=[
        _w1g3i_Player(
            name="P0", hand=[set_pool("APC")["Prophetic Bolt"]], library=library,
        ),
        _w1g3i_Player(name="P1", battlefield=board1),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = set(interactive)
    return game, board1  # W1G3 instants: the Bolt's game


def test_w1g3_prophetic_bolt_offers_any_target_and_refuses_what_is_not_one(set_pool):
    """"Prophetic Bolt deals 4 damage to any target." The picker offers both
    players and the creature (CR 115.4) and not the artifact beside it; naming
    the artifact is refused at announcement with the card still in hand."""
    game, theirs = _w1g3i_bolt_game(set_pool, theirs=[
        _w1g3i_card("A Bear", "Creature — Bear"),
        _w1g3i_card("A Rock", "Artifact"),
    ])
    bear, rock = theirs
    bolt = set_pool("APC")["Prophetic Bolt"]

    spec = game.cast_target_spec(0, bolt)
    assert spec["requires_target"]
    offered = {
        (t["kind"], t.get("name", t["seat"])) for t in spec["valid_targets"]
    }
    assert offered == {("player", 0), ("player", 1), ("permanent", "A Bear")}

    refused = game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[rock.permanent_id],
    )
    assert not refused.supported
    assert [c.name for c in game.players[0].hand] == ["Prophetic Bolt"]
    assert game.players[1].life == 20 and game.is_on_battlefield(rock)


def test_w1g3_prophetic_bolt_kills_the_creature_then_digs_four(set_pool):
    """"…deals 4 damage to any target. Look at the top four cards of your
    library. Put one of those cards into your hand and the rest on the bottom
    of your library in any order."

    A 2/4 takes the four; the caster looks at four — the spell held on the
    stack while it chooses (CR 608.2) — keeps the one it picks, and the other
    three go under the fifth card. The fifth is not an answer: it was never
    looked at. The creature dies when the spell has finished and not before.

    The rest go down as they lay and their owner is then **asked for their
    order** (CR 401.4), as the recruiters in this set ask. This test pinned the
    opposite while the look-and-pick family laid them down unasked; wave 2
    wired the family to ``offer_library_bottom_order``
    (``tests/engine/test_look_and_pick_bottom_order_census.py``), so the spell
    stays on the stack for one more answer."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear", "2", "4")],
        interactive={0},
    )
    bear, = theirs
    me = game.players[0]

    assert game.cast_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported

    # Mid-resolution: the damage is marked and the Bear is still there, because
    # state-based actions wait for the spell to finish (CR 704.3).
    assert bear.damage_marked == 4 and game.is_on_battlefield(bear), game.log
    assert [item.card.name for item in game.stack] == ["Prophetic Bolt"]
    assert game.waiting_prompt().kind == "look_top_pick"
    assert not game.confirm_look_top_pick(0, 4), "the fifth card was never looked at"

    assert game.confirm_look_top_pick(0, 2)
    # The order of the three that went down is still owed, and the spell — and
    # the Bear — wait on it.
    assert game.waiting_prompt().kind == "reorder_library"
    assert [item.card.name for item in game.stack] == ["Prophetic Bolt"]
    assert game.is_on_battlefield(bear)
    assert game.confirm_reorder_library(0, [0, 1, 2])
    game._settle()

    assert not game.is_on_battlefield(bear), game.log
    assert [c.name for c in game.players[1].graveyard] == ["A Bear"]
    assert [c.name for c in me.hand] == ["Card 3"]
    assert [c.name for c in me.library] == ["Card 5", "Card 1", "Card 2", "Card 4"]
    assert game.stack == [] and game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_at_a_player_with_nobody_to_ask(set_pool):
    """The same spell headless: four to the face, the first card looked at is
    kept (the stated default) and the rest go down as they lay."""
    game, _ = _w1g3i_bolt_game(set_pool)
    me = game.players[0]

    assert game.cast_from_hand(0, "Prophetic Bolt", target_player_index=1).supported
    game.auto_resolve_pending_choices()
    game._settle()

    assert game.players[1].life == 16 and me.life == 20
    assert [c.name for c in me.hand] == ["Card 1"]
    assert [c.name for c in me.library] == ["Card 5", "Card 2", "Card 3", "Card 4"]
    assert game.pending_choices == []
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]


def test_w1g3_prophetic_bolt_whose_target_left_does_nothing_at_all(set_pool):
    """CR 608.2b: with its only target gone the spell is removed from the
    stack and none of it happens — the look is the rule's *second* sentence,
    not a consolation. The library is exactly as it was."""
    game, theirs = _w1g3i_bolt_game(
        set_pool, theirs=[_w1g3i_card("A Bear", "Creature — Bear")],
    )
    bear, = theirs
    me = game.players[0]

    assert game.queue_from_hand(
        0, "Prophetic Bolt", target_permanent_ids=[bear.permanent_id],
    ).supported
    game.remove_from_battlefield(bear)
    _w1g3i_resolve_stack(game)

    assert me.hand == [] and game.pending_choices == []
    assert [c.name for c in me.library] == [f"Card {n}" for n in range(1, 6)]
    assert [c.name for c in me.graveyard] == ["Prophetic Bolt"]
    assert game.players[1].life == 20

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5i_Game, PlayerState as _w1g5i_Player
from engine import faces as _w1g5i_faces
from engine.models import Permanent as _w1g5i_Permanent
from tests.helpers import _mk_card as _w1g5i_mk_card
from tests.helpers import resolve_stack as _w1g5i_resolve_stack

_W1G5I_REQUIRED = "must be chosen as a target if able"


def _w1g5i_duel(mine=(), theirs=(), *, hand0=(), hand1=(), active=0, interactive=()):
    """Two boards placed and unsick, *active*'s turn begun."""
    board0 = [_w1g5i_Permanent(card=card) for card in mine]
    board1 = [_w1g5i_Permanent(card=card) for card in theirs]
    filler = _w1g5i_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5i_Game(players=[
        _w1g5i_Player(name="P0", battlefield=board0, hand=list(hand0), library=[filler] * 10),
        _w1g5i_Player(name="P1", battlefield=board1, hand=list(hand1), library=[filler] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(active)
    game._settle()
    return game, board0, board1  # W1G5 instants: the duel


def _w1g5i_half(card, name):
    """The half of a split card named *name* (CR 709.3) — the card the picker
    and the cast path are asked about."""
    return next(face for face in _w1g5i_faces.face_cards(card) if face.name == name)  # W1G5


def _w1g5i_stats(permanent):
    return (permanent.effective_power, permanent.effective_toughness)  # W1G5 instants


def test_fire_divides_two_damage_among_one_or_two_targets(set_pool):
    """Fire // Ice, the Fire half {1}{R}: "Fire deals 2 damage divided as you
    choose among one or two targets." Cast by the half's name; one damage to a
    2/1 and one to a face; and the refusals around it — three targets, a
    division that does not total 2, no target at all, and the card's whole
    name — each with the card still in hand."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Savannah Lions"], lea["Grizzly Bears"]], hand0=[card],
    )
    lions, bears = theirs
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Fire"))
    assert (spec["kind"], spec["division"], spec["max_targets"], spec["division_total"]) == (
        "divided", "chosen", 2, 2,
    )
    for announcement, why in (
        ({"divided_targets": [(1, 0, 1), (1, 1, 1), (1, None, 0)]}, "at most 2 targets"),
        ({"divided_targets": [(1, 0, 2), (1, 1, 1)]}, "must total 2"),
        ({}, "at least one target"),
    ):
        refused = game.queue_from_hand(0, "Fire", **announcement)
        assert not refused.supported and why in refused.details, refused
    whole = game.queue_from_hand(0, "Fire // Ice", target_player_index=1)
    assert not whole.supported and "split card" in whole.details
    assert game.players[0].hand == [card] and not game.stack

    assert game.queue_from_hand(
        0, "Fire", divided_targets=[(1, game.battlefield_index_of(lions), 1), (1, None, 1)],
    ).supported
    _w1g5i_resolve_stack(game)
    game._settle()
    assert game.players[1].life == 19
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert bears.damage_marked == 0
    # CR 709.4: in the graveyard it is the whole card again, once.
    assert [c.name for c in game.players[0].graveyard] == ["Fire // Ice"]


def test_fire_must_put_one_of_its_two_targets_on_a_flagbearer(set_pool):
    """Two slots under Standard Bearer: the rule is about the announcement,
    not about each target. A division with no Flagbearer in it is refused;
    one damage to the Bearer and one to the Bears is accepted, and both die
    or bleed as dealt — the second slot is free."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel(
        [], [apc["Standard Bearer"], lea["Grizzly Bears"]], hand0=[card],
    )
    bearer, bears = theirs
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Fire"))
    assert [entry["id"] for entry in spec["required_targets"]] == [bearer.permanent_id]
    # The list is whole: a second slot may be anything Fire could target.
    assert {entry.get("name") for entry in spec["valid_targets"]} >= {
        "Standard Bearer", "Grizzly Bears",
    }
    assert any(entry["kind"] == "player" for entry in spec["valid_targets"])

    bears_slot, bearer_slot = game.battlefield_index_of(bears), game.battlefield_index_of(bearer)
    refused = game.queue_from_hand(
        0, "Fire", divided_targets=[(1, bears_slot, 1), (1, None, 1)],
    )
    assert not refused.supported and _W1G5I_REQUIRED in refused.details, refused
    assert game.queue_from_hand(
        0, "Fire", divided_targets=[(1, bearer_slot, 1), (1, bears_slot, 1)],
    ).supported
    _w1g5i_resolve_stack(game)
    assert bears.damage_marked == 1
    game._settle()
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]


def test_ice_taps_a_permanent_and_draws(set_pool):
    """The Ice half {1}{U}: "Tap target permanent. / Draw a card." Any
    permanent — a land here — and the card is drawn by the caster."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Fire // Ice"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Forest"]], hand0=[card])
    forest = theirs[0]
    library = len(game.players[0].library)
    assert game.cast_from_hand(0, "Ice", target_permanent_ids=[forest.permanent_id]).supported
    assert forest.tapped
    assert len(game.players[0].hand) == 1 and len(game.players[0].library) == library - 1
    assert len(game.players[1].hand) == 0


def test_illusion_turns_a_permanent_the_colour_its_caster_names_for_a_turn(set_pool):
    """Illusion // Reality, the Illusion half {U}: "Target spell or permanent
    becomes the color of your choice until end of turn." The colour is asked
    as the spell resolves (CR 608.2d), of its caster; the green Bears are blue
    — and nothing else — until cleanup, and green again after it."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Illusion // Reality"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Grizzly Bears"]], hand0=[card], interactive=(0,))
    bears = theirs[0]
    assert set(bears.effective_colors) == {"G"}
    assert game.queue_from_hand(0, "Illusion", target_permanent_ids=[bears.permanent_id]).supported
    game.resolve_top_of_stack()
    assert [(c.kind, c.player_index) for c in game.pending_choices] == [("color_choice", 0)]
    assert set(bears.effective_colors) == {"G"}, "nothing is recoloured before the answer"
    assert game.confirm_color_choice(0, "U")
    _w1g5i_resolve_stack(game)
    assert set(bears.effective_colors) == {"U"}
    game.resolve_cleanup_step(0)
    assert set(bears.effective_colors) == {"G"}


def test_reality_destroys_an_artifact_and_nothing_else(set_pool):
    """The Reality half {2}{G}: "Destroy target artifact." A creature named
    for it is refused at the announcement; the Sol Ring goes to its owner's
    graveyard."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Illusion // Reality"]
    game, _mine, theirs = _w1g5i_duel([], [lea["Grizzly Bears"], lea["Sol Ring"]], hand0=[card])
    bears, ring = theirs
    offered = game.cast_target_spec(0, _w1g5i_half(card, "Reality"))["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Sol Ring"]
    refused = game.queue_from_hand(0, "Reality", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and game.players[0].hand == [card]
    assert game.cast_from_hand(0, "Reality", target_permanent_ids=[ring.permanent_id]).supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Sol Ring"]


def test_night_shrinks_one_creature_for_the_turn(set_pool):
    """Night // Day, the Night half {B}: "Target creature gets -1/-1 until end
    of turn." A 2/1 dies of it; a 2/2 is a 1/1 until cleanup and a 2/2 after."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Night // Day"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Savannah Lions"], lea["Grizzly Bears"]], hand0=[card, card],
    )
    lions, bears = theirs
    assert game.cast_from_hand(0, "Night", target_permanent_ids=[lions.permanent_id]).supported
    assert [p.card.name for p in game.controlled_by(1)] == ["Grizzly Bears"]
    assert [c.name for c in game.players[1].graveyard] == ["Savannah Lions"]
    assert game.cast_from_hand(0, "Night", target_permanent_ids=[bears.permanent_id]).supported
    assert _w1g5i_stats(bears) == (1, 1)
    game.resolve_cleanup_step(0)
    assert _w1g5i_stats(bears) == (2, 2)


def test_day_pumps_the_creatures_of_the_player_it_targets_and_no_others(set_pool):
    """The Day half {2}{W}: "Creatures target player controls get +1/+1 until
    end of turn." The picker is a player picker — it derived none, so a client
    sent a bare cast — and the pump reaches that player's creatures alone: it
    used to compile as "all creatures" and pump both boards. Each seat in
    turn; gone at cleanup; a creature arriving afterwards is not pumped
    (CR 611.2c)."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Night // Day"]
    game, mine, theirs = _w1g5i_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"], lea["Grizzly Bears"]],
        hand0=[card, card],
    )
    spec = game.cast_target_spec(0, _w1g5i_half(card, "Day"))
    assert spec["kind"] == "player"
    assert [entry["seat"] for entry in spec["valid_targets"]] == [0, 1]

    assert game.cast_from_hand(0, "Day", target_player_index=0).supported
    assert _w1g5i_stats(mine[0]) == (3, 3)
    assert [_w1g5i_stats(p) for p in theirs] == [(2, 1), (2, 2)]
    late = _w1g5i_Permanent(card=lea["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert _w1g5i_stats(late) == (2, 2)

    assert game.cast_from_hand(0, "Day", target_player_index=1).supported
    assert [_w1g5i_stats(p) for p in theirs] == [(3, 2), (3, 3)]
    assert _w1g5i_stats(mine[0]) == (3, 3)
    game.resolve_cleanup_step(0)
    assert _w1g5i_stats(mine[0]) == (2, 2)
    assert [_w1g5i_stats(p) for p in theirs] == [(2, 1), (2, 2)]


def test_order_exiles_an_attacking_creature_and_only_one(set_pool):
    """Order // Chaos, the Order half {3}{W}: "Exile target attacking
    creature." Outside combat it has no legal target and is refused; once the
    Bears attack, the Bears are its only target — the Lions that stayed home
    are not offered — and are exiled."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Order // Chaos"]
    game, _mine, theirs = _w1g5i_duel(
        [], [lea["Grizzly Bears"], lea["Savannah Lions"]], hand0=[card], active=1,
    )
    bears, lions = theirs
    refused = game.queue_from_hand(0, "Order", target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and game.players[0].hand == [card]

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(1, [game.battlefield_index_of(bears)])[0]
    offered = game.cast_target_spec(0, _w1g5i_half(card, "Order"))["valid_targets"]
    assert [entry["name"] for entry in offered] == ["Grizzly Bears"]
    assert not game.queue_from_hand(
        0, "Order", target_permanent_ids=[lions.permanent_id]
    ).supported
    assert game.queue_from_hand(0, "Order", target_permanent_ids=[bears.permanent_id]).supported
    _w1g5i_resolve_stack(game)
    assert [p.card.name for p in game.controlled_by(1)] == ["Savannah Lions"]
    assert [c.name for c in game.players[1].exile] == ["Grizzly Bears"]
    assert game.players[1].graveyard == []


def test_chaos_stops_every_block_this_turn_including_a_late_arrival(set_pool):
    """The Chaos half {2}{R}: "Creatures can't block this turn." No target.
    Neither the Lions that were there nor a Bears that arrives after Chaos
    resolved may be declared as a blocker ("including ones that weren't on the
    battlefield as Chaos resolved" — ruling, 2022-12-08), and after cleanup
    they may."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Order // Chaos"]
    game, mine, theirs = _w1g5i_duel(
        [lea["Grizzly Bears"]], [lea["Savannah Lions"]], hand0=[card],
    )
    attacker, lions = mine[0], theirs[0]
    assert game.cast_target_spec(0, _w1g5i_half(card, "Chaos"))["kind"] == "none"
    assert game.cast_from_hand(0, "Chaos").supported
    late = _w1g5i_Permanent(card=lea["Grizzly Bears"])
    late.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(1, late, None)

    game._set_phase_and_step("combat", "declare_attackers")
    assert game.declare_attackers(0, [game.battlefield_index_of(attacker)])[0]
    game._set_phase_and_step("combat", "declare_blockers")
    for blocker in (lions, late):
        declared = game.declare_blockers(1, {
            game.battlefield_index_of(blocker): [game.battlefield_index_of(attacker)],
        })
        assert declared[0] is False, (blocker.card.name, declared)
    game.resolve_cleanup_step(0)
    assert game.blocking_restrictions_until_eot == []

# ==== end W1G5 ========================================================


# ==== W1G6 ============================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ========================================================


# ==== W1G7 ============================================================
# W1G7's tests go between this line and the "end W1G7" line.

import pytest as _w1g7_pytest

from engine import Game as _W1G7Game, PlayerState as _W1G7PlayerState
from engine.grammar import compile_line as _w1g7_compile_line
from engine.models import Permanent as _W1G7Permanent
from engine.oracle import compile_card_oracle as _w1g7_compile
from tests.helpers import resolve_stack as _w1g7_resolve_stack


def _w1g7_instant_duel(*, interactive=(0,)):
    """A two-seat game with costs off. Seat 0 is interactive by default, so a
    prompt one of these cards arms is *queued* rather than answered by its own
    default — a headless probe cannot tell "nobody was asked" from "nobody was
    there to ask"."""
    p0, p1 = _W1G7PlayerState(name="A"), _W1G7PlayerState(name="B")
    game = _W1G7Game(players=[p0, p1])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, p0, p1


def _w1g7_instant_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W1G7Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    return permanent


def _w1g7_bolt_at_seat_zero(game, catalog_by_name):
    """Seat 1 puts a Lightning Bolt on the stack aimed at seat 0."""
    game.players[1].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    return game.stack[-1]


# -- Evasive Action ----------------------------------------------------------


def test_evasive_action_prices_the_toll_at_one_per_basic_land_type(
    set_pool, catalog_by_name
):
    """"Domain — Counter target spell unless its controller pays {1} **for each
    basic land type among lands you control**." Three types is {3}, asked of
    the spell's controller, and a board that cannot cover it loses the spell."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(2)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    assert game.queue_from_hand(0, "Evasive Action", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)

    owed = game.pending_mana_payment
    assert owed is not None and owed["player_index"] == 1 and owed["amount"] == 3
    assert "Evasive Action: B must pay {3} or Lightning Bolt is countered" in game.log
    # Two Mountains cannot make three mana, so "pay" is not an answer this
    # seat can give (CR 118.3, CR 608.2d): it is refused and the question
    # stands. It used to be carried out as the other answer — which a person
    # holding a mana rock the engine does not tap for them had not given.
    assert game.confirm_mana_payment(1, True) is False
    assert game.pending_mana_payment is not None
    assert game.confirm_mana_payment(1, False) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 20
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert [land.tapped for land in mountains] == [False, False]
    assert any("Lightning Bolt was countered by Evasive Action" in line for line in game.log)


def test_evasive_action_lets_a_paid_spell_resolve(set_pool, catalog_by_name):
    """The other answer: {3} paid from three lands, and the Bolt lands."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in ("Island", "Plains", "Forest"):
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    mountains = [_w1g7_instant_put(game, 1, catalog_by_name["Mountain"]) for _ in range(3)]
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.confirm_mana_payment(1, True) is True
    _w1g7_resolve_stack(game)

    assert p0.life == 17
    assert all(land.tapped for land in mountains)
    assert "B paid {3}; Lightning Bolt is not countered" in game.log


@_w1g7_pytest.mark.parametrize(
    "lands, owed",
    [
        # Types, not lands: two Islands are one type, and a Tropical Island is
        # an Island and a Forest (CR 305.6) — two types among three lands.
        (("Island", "Island", "Tropical Island"), 2),
        (("Island", "Swamp", "Mountain", "Forest", "Plains", "Plains"), 5),
        (("Island",), 1),
    ],
)
def test_evasive_action_counts_basic_land_types_not_lands(
    set_pool, catalog_by_name, lands, owed
):
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    for name in lands:
        _w1g7_instant_put(game, 0, catalog_by_name[name])
    # The *spell's* controller's lands are not counted, whatever they are.
    for name in ("Swamp", "Mountain", "Forest", "Plains"):
        _w1g7_instant_put(game, 1, catalog_by_name[name])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    game.resolve_top_of_stack(pause_for_choices=True)

    assert game.pending_mana_payment["amount"] == owed


def test_evasive_action_with_no_basic_land_type_counters_nothing(
    set_pool, catalog_by_name
):
    """A domain of zero is a price of {0}, which every board covers: no prompt
    is armed and the spell resolves. A nonbasic land with no basic land type
    (Mishra's Factory) contributes nothing."""
    game, p0, p1 = _w1g7_instant_duel(interactive=(1,))
    _w1g7_instant_put(game, 0, catalog_by_name["Mishra's Factory"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Evasive Action"]]

    game.queue_from_hand(0, "Evasive Action", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert game.pending_mana_payment is None
    assert p0.life == 17
    assert "B pays {0}; Lightning Bolt is not countered by Evasive Action" in game.log


def test_evasive_action_needs_a_spell_to_name(set_pool):
    """CR 601.2c: with nothing on the stack there is no target, and the cast is
    refused with the card still in hand."""
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Evasive Action"]]

    result = game.cast_from_hand(0, "Evasive Action")

    assert not result.supported
    assert [card.name for card in p0.hand] == ["Evasive Action"]


def test_a_counted_counter_price_refuses_what_the_flow_cannot_charge():
    """The production's refusals. "Beyond the first" is a discount the payment
    never takes, and a coloured rate times a count is arithmetic the prompt
    does not do — each must leave its line unsupported rather than charge the
    wrong number."""
    discounted = _w1g7_compile_line(
        "Counter target spell unless its controller pays {1} for each creature "
        "you control beyond the first."
    )
    assert discounted.parse_error == "no counter price discounts the first counted object"

    coloured = _w1g7_compile_line(
        "Counter target spell unless its controller pays {U} for each basic "
        "land type among lands you control."
    )
    assert coloured.parsed and not coloured.usable
    assert coloured.lowering_error == "only a printed generic cost is paid per counted object"


# -- Jaded Response ----------------------------------------------------------


@_w1g7_pytest.mark.parametrize(
    "mine, theirs, countered",
    [
        # A red creature of the caster's shares red with the Bolt.
        ("Goblin Balloon Brigade", None, True),
        # A blue one shares nothing with it.
        ("Prodigal Sorcerer", None, False),
        # "A creature **you control**": the opponent's red creature is nobody's
        # business here.
        (None, "Goblin Balloon Brigade", False),
        # CR 105.2c: a colourless object shares a colour with nothing.
        ("Ornithopter", None, False),
        (None, None, False),
    ],
)
def test_jaded_response_counters_only_a_spell_sharing_a_color_with_your_creature(
    set_pool, catalog_by_name, mine, theirs, countered
):
    """"Counter target spell **if it shares a color with a creature you
    control**." Asserted on the life total: a counter that fired without its
    condition, or a condition that never held, both read wrong here."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    if mine:
        _w1g7_instant_put(game, 0, catalog_by_name[mine])
    if theirs:
        _w1g7_instant_put(game, 1, catalog_by_name[theirs])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    # "Target spell" is the whole of the targeting restriction (CR 608.2b), so
    # the Bolt is a legal target whether or not the condition will hold.
    offered = game.cast_target_spec(0, set_pool("APC")["Jaded Response"])
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Lightning Bolt"]
    assert game.cast_from_hand(0, "Jaded Response", target_stack_index=0).supported
    _w1g7_resolve_stack(game)

    assert p0.life == (20 if countered else 17)
    assert [card.name for card in p0.graveyard] == ["Jaded Response"]
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert countered == any(
        "Lightning Bolt was countered by Jaded Response" in line for line in game.log
    )


def test_jaded_response_reads_the_colors_as_it_resolves(set_pool, catalog_by_name):
    """The card's ruling: "It does not check colors until it resolves" (CR
    608.2c). The red creature that made the cast worthwhile leaves in response,
    and the Bolt is no longer a spell this counters."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    goblin = _w1g7_instant_put(game, 0, catalog_by_name["Goblin Balloon Brigade"])
    _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert game.queue_from_hand(0, "Jaded Response", target_stack_index=0).supported
    game.remove_from_battlefield(goblin)
    _w1g7_resolve_stack(game)

    assert p0.life == 17


def test_jaded_response_sees_a_spell_an_effect_recolored(set_pool, catalog_by_name):
    """The spell's colour is what it is *on the stack* (CR 613.1): a Bolt a
    Vodalian Mystic has made blue shares blue with a Prodigal Sorcerer, and no
    longer shares red with a Goblin."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    _w1g7_instant_put(game, 0, catalog_by_name["Prodigal Sorcerer"])
    bolt = _w1g7_bolt_at_seat_zero(game, catalog_by_name)
    bolt.choices["color_override"] = "U"
    p0.hand = [set_pool("APC")["Jaded Response"]]

    game.cast_from_hand(0, "Jaded Response", target_stack_index=0)
    _w1g7_resolve_stack(game)

    assert p0.life == 20


def test_jaded_response_cannot_be_cast_at_an_empty_stack(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Jaded Response"]]

    assert not game.cast_from_hand(0, "Jaded Response").supported
    assert [card.name for card in p0.hand] == ["Jaded Response"]


def test_a_shared_color_condition_is_asked_of_a_spell_and_refuses_elsewhere():
    """The lowering's refusals: the clause about a targeted *permanent* turns on
    whether an object is one of the things it is compared with, which no card
    prints to rule on; and under a trigger "it" names the event's subject."""
    on_a_permanent = _w1g7_compile_line(
        "Destroy target creature if it shares a color with a creature you control."
    )
    assert on_a_permanent.parsed and not on_a_permanent.usable
    assert "asked of a targeted spell" in on_a_permanent.lowering_error

    under_a_trigger = _w1g7_compile_line(
        "Whenever a player casts a spell, counter it if it shares a color with "
        "a creature you control."
    )
    assert not under_a_trigger.usable

    trailing = _w1g7_compile_line(
        "Counter target spell if it shares a color with a creature you control "
        "and draw a card."
    )
    assert not trailing.parsed


# -- Suffocating Blast (driven, and declined in wave 1) -----------------------
#
# W1G7's test here asserted the decline — the card refused in the lowering
# until an announcement could carry a stack slot beside a battlefield one. Wave
# 2 built that slot, so the assertion of the refusal left with it; the card's
# tests are in the W2G1 section below. The edge the refusal drew stays tested:


def test_one_target_named_once_beside_a_spell_is_still_one_announcement(catalog_by_name):
    """The refusal's edge: it fires on a spell target *beside another target*,
    never on a counterspell with a second sentence. Every shipped counter that
    goes on to do something keeps the program it had."""
    for name in ("Counterspell", "Memory Lapse", "Exclude", "Absorb", "Undermine"):
        if name in catalog_by_name:
            assert _w1g7_compile(catalog_by_name[name]).supported, name
    plain = _w1g7_compile_line("Counter target spell. Draw a card.")
    assert plain.usable


# -- Shimmering Mirage (driven) ----------------------------------------------


def test_shimmering_mirage_changes_a_land_and_draws_a_card(set_pool, catalog_by_name):
    """"Target land becomes the basic land type of your choice until end of
    turn. / Draw a card." A land is the only thing it may name, the type is
    asked as it resolves, and the turn's end gives the Forest back."""
    game, p0, p1 = _w1g7_instant_duel()
    forest = _w1g7_instant_put(game, 1, catalog_by_name["Forest"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    mirage = set_pool("APC")["Shimmering Mirage"]
    p0.hand = [mirage]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, mirage)
    assert offered["kind"] == "land"
    assert [entry["name"] for entry in offered["valid_targets"]] == ["Forest"]
    assert not game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]

    assert game.queue_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[forest.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_land_type_choice["player_index"] == 0
    assert forest.basic_land_types == ("forest",)
    assert game.confirm_land_type(0, "island") is True

    assert forest.basic_land_types == ("island",)
    assert [card.name for card in p0.hand] == ["Island"]
    assert [card.name for card in p0.graveyard] == ["Shimmering Mirage"]
    assert game.stack == []

    game.resolve_cleanup_step(0)
    assert forest.basic_land_types == ("forest",)


def test_shimmering_mirage_with_no_land_to_name_cannot_be_cast(set_pool):
    game, p0, _p1 = _w1g7_instant_duel()
    p0.hand = [set_pool("APC")["Shimmering Mirage"]]

    assert not game.cast_from_hand(0, "Shimmering Mirage").supported
    assert [card.name for card in p0.hand] == ["Shimmering Mirage"]


# -- Smash (driven) ----------------------------------------------------------


def test_smash_destroys_the_named_artifact_and_draws_a_card(set_pool, catalog_by_name):
    """"Destroy target artifact. / Draw a card." An artifact creature is an
    artifact (CR 205.2); a creature that is not one is refused at announcement
    with the card still in hand."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    bears = _w1g7_instant_put(game, 1, catalog_by_name["Grizzly Bears"])
    thopter = _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    smash = set_pool("APC")["Smash"]
    p0.hand = [smash]
    p0.library = [catalog_by_name["Island"], catalog_by_name["Swamp"]]

    offered = game.cast_target_spec(0, smash)
    assert sorted(entry["name"] for entry in offered["valid_targets"]) == [
        "Ornithopter", "Sol Ring",
    ]
    assert not game.cast_from_hand(
        0, "Smash", target_permanent_ids=[bears.permanent_id]
    ).supported
    assert [card.name for card in p0.hand] == ["Smash"]

    assert game.cast_from_hand(
        0, "Smash", target_permanent_ids=[thopter.permanent_id]
    ).supported
    _w1g7_resolve_stack(game)

    assert [perm.card.name for perm in p1.battlefield] == ["Sol Ring", "Grizzly Bears"]
    assert [card.name for card in p1.graveyard] == ["Ornithopter"]
    assert [card.name for card in p0.hand] == ["Island"]
    assert ring in p1.battlefield


def test_smash_whose_artifact_has_left_draws_nothing(set_pool, catalog_by_name):
    """CR 608.2b: with its only target gone the spell does not resolve — the
    second sentence is not a consolation prize."""
    game, p0, p1 = _w1g7_instant_duel(interactive=())
    ring = _w1g7_instant_put(game, 1, catalog_by_name["Sol Ring"])
    _w1g7_instant_put(game, 1, catalog_by_name["Ornithopter"])
    p0.hand = [set_pool("APC")["Smash"]]
    p0.library = [catalog_by_name["Island"]]

    assert game.queue_from_hand(
        0, "Smash", target_permanent_ids=[ring.permanent_id]
    ).supported
    game.remove_from_battlefield(ring)
    _w1g7_resolve_stack(game)

    assert p0.hand == []
    assert [card.name for card in p0.library] == ["Island"]
    # …and it did not go looking for the other artifact.
    assert [perm.card.name for perm in p1.battlefield] == ["Ornithopter"]

# ==== end W1G7 ========================================================


# ==== W1G8 ============================================================
# W1G8's tests go between this line and the "end W1G8" line.

# ==== end W1G8 ========================================================


# ==== W1G9 ============================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ========================================================

# ==== W2G1 ============================================================
# W2G1's tests go between this line and the "end W2G1" line.

import pytest as _w2g1_pytest

from engine import Game as _W2G1Game, PlayerState as _W2G1PlayerState
from engine import faces as _w2g1_faces
from engine.grammar import compile_line as _w2g1_compile_line
from engine.models import Permanent as _W2G1Permanent
from engine.oracle import compile_card_oracle as _w2g1_compile
from engine.targeting import derive_cast_spec as _w2g1_derive_cast_spec
from tests.helpers import resolve_stack as _w2g1_resolve_stack


def _w2g1_duel(*, interactive=()):
    """A two-seat game with costs off. Non-interactive by default, so a colour
    the resolution asks for is answered by the registry's own default; a test
    that reads the prompt names its interactive seat."""
    players = [_W2G1PlayerState(name="A"), _W2G1PlayerState(name="B")]
    game = _W2G1Game(players=players)
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    return game, players[0], players[1]


def _w2g1_put(game, seat, card):
    """Put *card* onto *seat*'s battlefield, ready to act this turn."""
    permanent = _W2G1Permanent(card=card)
    permanent.metadata["summoning_sickness_turn"] = -99
    game.players[seat].battlefield.append(permanent)
    game._sync_control()
    return permanent


def _w2g1_spell_from(game, seat, card, **announcement):
    """*seat* puts *card* on the stack; returns the stack object."""
    game.players[seat].hand.append(card)
    queued = game.queue_from_hand(seat, card.name, **announcement)
    assert queued.supported, queued.details
    return game.stack[-1]


def _w2g1_illusion(set_pool):
    """The split card and its Illusion half — the half is what compiles and
    what is cast by name (CR 709.3); the whole card is what a hand holds."""
    whole = set_pool("APC")["Illusion // Reality"]
    half = next(
        unit for unit in _w2g1_faces.compilation_units([whole])
        if unit.name == "Illusion"
    )
    return whole, half


# -- Suffocating Blast --------------------------------------------------------


def test_suffocating_blast_asks_for_a_spell_and_then_a_creature(
    set_pool, catalog_by_name
):
    """"Counter target spell and Suffocating Blast deals 3 damage to target
    creature." Two targets in two zones, announced together (CR 601.2c): the
    picker walks a spell role and then a creature role, and every announcement
    short of both is refused with the card still in hand — the four ways it
    mis-played before the stack slot existed."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    ring = _w2g1_put(game, 1, catalog_by_name["Sol Ring"])
    giant = _w2g1_put(game, 0, catalog_by_name["Hill Giant"])
    _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    blast = set_pool("APC")["Suffocating Blast"]
    p0.hand = [blast]

    offered = game.cast_target_spec(0, blast)
    assert offered["kind"] == "roles"
    assert [role["kind"] for role in offered["roles"]] == ["stack", "creature"]
    assert [(entry["kind"], entry["name"]) for entry in offered["valid_targets"]] == [
        ("stack", "Lightning Bolt"),
    ]
    assert sorted(step["name"] for step in offered["valid_targets"][0]["next"]) == [
        "Grizzly Bears", "Hill Giant",
    ]

    refused = {
        "nothing named": {},
        "the spell alone": {"target_stack_index": 0},
        "the creature alone": {"target_permanent_ids": [None, bears.permanent_id]},
        "an artifact for the creature": {
            "target_stack_index": 0,
            "target_permanent_ids": [None, ring.permanent_id],
        },
        "an id list that is not positional": {
            "target_stack_index": 0, "target_permanent_ids": [bears.permanent_id],
        },
    }
    for why, announcement in refused.items():
        assert not game.queue_from_hand(0, "Suffocating Blast", **announcement).supported, why
        assert [card.name for card in p0.hand] == ["Suffocating Blast"], why
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]
    assert giant.damage_marked == 0 and bears.damage_marked == 0


def test_suffocating_blast_counters_the_spell_and_burns_the_creature(
    set_pool, catalog_by_name
):
    """Both halves, in printed order, each on the object named for it — and on
    nothing else: the artifact and the caster's own creature are untouched."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    ring = _w2g1_put(game, 1, catalog_by_name["Sol Ring"])
    giant = _w2g1_put(game, 0, catalog_by_name["Hill Giant"])
    _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported
    _w2g1_resolve_stack(game)
    game.check_state_based_actions()

    assert p0.life == 20
    assert "Lightning Bolt was countered by Suffocating Blast and moved to graveyard" in game.log
    assert "Suffocating Blast dealt 3 damage to Grizzly Bears" in game.log
    assert sorted(card.name for card in p1.graveyard) == ["Grizzly Bears", "Lightning Bolt"]
    assert [card.name for card in p0.graveyard] == ["Suffocating Blast"]
    assert [perm.card.name for perm in p1.battlefield] == ["Sol Ring"]
    assert ring in p1.battlefield and giant.damage_marked == 0


def test_suffocating_blast_reads_back_both_of_its_targets(set_pool, catalog_by_name):
    """``stack_targets.chosen_targets`` — what "becomes the target of a spell"
    and CR 115.7's retargets ask — reads one target per role off the channel
    each travels on: the spell from the stack channel, the creature by id."""
    from engine.stack_targets import chosen_targets

    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]
    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported

    read = chosen_targets(game, game.stack[-1])

    assert [(target.kind, target.channel, target.position) for target in read] == [
        ("stack", "role", 0), ("permanent", "role", 1),
    ]
    assert read[0].stack_item is bolt
    assert read[1].permanent_id == bears.permanent_id


def test_suffocating_blast_whose_spell_has_left_still_burns_the_creature(
    set_pool, catalog_by_name
):
    """CR 608.2b: "if **all** its targets … are now illegal, the spell doesn't
    resolve" — one is not all. The counter is skipped (it does not reach for
    the spell underneath) and the damage still happens."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w2g1_spell_from(game, 1, catalog_by_name["Shock"], target_player_index=0)
    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=1,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported
    game.counter_stack_object(bolt)
    assert game.resolve_top_of_stack()

    assert bears.damage_marked == 3
    assert [item.card.name for item in game.stack] == ["Shock"]
    assert not any("countered by Suffocating Blast" in line for line in game.log)
    assert [card.name for card in p0.graveyard] == ["Suffocating Blast"]


def test_suffocating_blast_whose_creature_has_left_still_counters_the_spell(
    set_pool, catalog_by_name
):
    """The other half of the same rule: the creature is gone, so no damage is
    dealt — to it or to the creature that slid into its slot — and the spell
    is countered all the same."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _w2g1_put(game, 1, catalog_by_name["Hill Giant"])
    _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported
    game.remove_from_battlefield(bears)
    _w2g1_resolve_stack(game)

    assert p0.life == 20
    assert [card.name for card in p1.graveyard] == ["Lightning Bolt"]
    assert giant.damage_marked == 0
    assert not any("dealt 3 damage" in line for line in game.log)


def test_suffocating_blast_with_both_targets_gone_does_not_resolve(
    set_pool, catalog_by_name
):
    """CR 608.2b's first half: every target illegal, so the spell is removed
    from the stack and put into its owner's graveyard without doing anything."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    giant = _w2g1_put(game, 1, catalog_by_name["Hill Giant"])
    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported
    game.counter_stack_object(bolt)
    game.remove_from_battlefield(bears)
    _w2g1_resolve_stack(game)

    assert any("every target is illegal (608.2b)" in line for line in game.log)
    assert [card.name for card in p0.graveyard] == ["Suffocating Blast"]
    assert giant.damage_marked == 0


def test_suffocating_blast_at_an_uncounterable_spell_still_deals_its_damage(
    set_pool, catalog_by_name
):
    """"This spell can't be countered" (Urza's Rage) is not a targeting
    restriction: the Rage is a legal answer to "target spell", the counter does
    nothing, and the three damage is dealt (CR 608.2: as much as possible)."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w2g1_spell_from(game, 1, catalog_by_name["Urza's Rage"], target_player_index=0)
    p0.hand = [set_pool("APC")["Suffocating Blast"]]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    ).supported
    assert game.resolve_top_of_stack()

    assert bears.damage_marked == 3
    assert [item.card.name for item in game.stack] == ["Urza's Rage"]
    _w2g1_resolve_stack(game)
    assert p0.life == 17


def test_suffocating_blast_must_burn_an_opponents_flagbearer_if_able(
    set_pool, catalog_by_name
):
    """Standard Bearer: "While an opponent is choosing targets as part of
    casting a spell they control…, that player must choose at least one
    Flagbearer on the battlefield if able." The requirement is over the whole
    announcement, and the creature slot is the one that can obey it."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    bearer = _w2g1_put(game, 1, set_pool("APC")["Standard Bearer"])
    _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    blast = set_pool("APC")["Suffocating Blast"]
    p0.hand = [blast]

    offered = game.cast_target_spec(0, blast)
    assert [entry["name"] for entry in offered["required_targets"]] == ["Standard Bearer"]

    refused = game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bears.permanent_id],
    )
    assert not refused.supported and "Flagbearer" in refused.details
    assert [card.name for card in p0.hand] == ["Suffocating Blast"]

    assert game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, bearer.permanent_id],
    ).supported
    _w2g1_resolve_stack(game)
    assert bearer.damage_marked == 3 and bears.damage_marked == 0


def test_suffocating_blast_is_not_cast_at_a_protected_creature(
    set_pool, catalog_by_name
):
    """A target is held at the announcement like any other: Scragnoth has
    protection from blue and the Blast is blue and red, so it is not offered
    for the creature role and naming it is refused (CR 702.16b)."""
    game, p0, p1 = _w2g1_duel()
    scragnoth = _w2g1_put(game, 1, catalog_by_name["Scragnoth"])
    _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    blast = set_pool("APC")["Suffocating Blast"]
    p0.hand = [blast]

    assert game.cast_target_spec(0, blast)["valid_targets"] == []
    assert not game.queue_from_hand(
        0, "Suffocating Blast", target_stack_index=0,
        target_permanent_ids=[None, scragnoth.permanent_id],
    ).supported
    assert [card.name for card in p0.hand] == ["Suffocating Blast"]


def test_the_ai_names_both_of_suffocating_blasts_targets_or_does_not_cast_it(
    set_pool, catalog_by_name
):
    """An AI seat holding the Blast: with an empty stack it proposes nothing
    (there is no spell to name), and answering an opponent's spell it names
    that spell and an opposing creature — an announcement the engine takes."""
    from engine import ai_policy

    game, p0, p1 = _w2g1_duel()
    _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    _w2g1_put(game, 0, catalog_by_name["Hill Giant"])
    p0.hand = [set_pool("APC")["Suffocating Blast"]]
    game.active_player_index = 1

    assert ai_policy.choose_cast_action(game, 0) is None
    assert ai_policy.choose_combat_instant_cast_action(game, 0) is None

    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    action = ai_policy.choose_combat_instant_cast_action(game, 0)
    assert action is not None and action.card_name == "Suffocating Blast"
    announced = ai_policy.cast_announcement(action)
    assert game.stack[announced["target_stack_index"]] is bolt
    named = game.permanent_by_id(announced["target_permanent_ids"][1])
    assert named.card.name == "Grizzly Bears"

    assert game.queue_from_hand(0, "Suffocating Blast", **announced).supported
    _w2g1_resolve_stack(game)
    assert p0.life == 20 and named.damage_marked == 3


def test_the_ai_never_proposes_suffocating_blast_or_illusion_to_be_refused():
    """Both pinned into both decks of six simulated games. Illusion is cast
    (a floor of one); Suffocating Blast needs a spell to answer and the
    simulator casts only in its own main phases, so what is asserted of it is
    the absence the brief asks for — no proposal the cast gate refused."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    report = run_ai_simulation(
        [manifest_set_path("APC", include_measured=True)],
        games=6, seed=1337, max_turns=18,
        required_cards=["Suffocating Blast", "Illusion // Reality"],
    )
    assert report.games_completed == 6
    mine = ("Suffocating Blast", "Illusion", "Reality", "Illusion // Reality")
    assert [key for key in report.refused_casts if key.split(":")[0] in mine] == []
    cast = [
        line for line in report.log_lines
        if " cast Illusion -> resolved" in line or " cast Reality -> resolved" in line
    ]
    assert len(cast) >= 1, report.refused_casts


def test_a_spell_role_carries_what_narrows_its_spell_or_the_line_refuses():
    """The lowering: a counter keeps its narrowing on its own payload, so the
    role is stamped with the picker's own ``stack_*`` flags — and a pair the
    roles walk has no word for refuses rather than keeping its first target."""
    def compiled(line):
        return _w2g1_compile_line(line, card_name="Suffocating Blast")

    narrowed = compiled(
        "Counter target creature spell and Suffocating Blast deals 3 damage "
        "to target creature."
    )
    assert narrowed.usable
    counter = narrowed.instructions[0]
    assert counter.payload["targets"]["role"] == "spell"
    assert counter.payload["targets"]["roles"][0] == {
        "kind": "spell", "role": "spell", "stack_card_types": ["creature"],
    }

    seat = compiled(
        "Counter target spell and Suffocating Blast deals 3 damage to target player."
    )
    assert seat.usable
    roles = seat.instructions[0].payload["targets"]["roles"]
    assert [(role["role"], role["kind"]) for role in roles] == [
        ("spell", "spell"), ("player", "player"),
    ]

    # A spell beside a slot the walk cannot take is still two targets, so the
    # line refuses rather than keeping the spell-only picker.
    for line in (
        "Counter target spell and Suffocating Blast deals 3 damage to any target.",
    ):
        refused = compiled(line)
        assert not refused.usable and "announces both" in refused.lowering_error

    # A counter with a second sentence names one target once.
    plain = compiled("Counter target spell. Draw a card.")
    assert plain.usable
    assert "roles" not in str(plain.instructions[0].payload)


# -- Illusion (of Illusion // Reality) ---------------------------------------


def test_illusion_offers_a_spell_or_a_permanent_and_takes_one_of_them(
    set_pool, catalog_by_name
):
    """"Target spell or permanent becomes the color of your choice until end of
    turn." One target in one of two zones: the picker lists both, a named
    spell is recoloured — not the creature beside it, which is what a scan
    found while the union was unread — and naming one of each is refused."""
    game, p0, p1 = _w2g1_duel(interactive=(0,))
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    whole, illusion = _w2g1_illusion(set_pool)
    p0.hand = [whole]

    offered = game.cast_target_spec(0, illusion)
    assert offered["kind"] == "spell_or_permanent"
    assert sorted((entry["kind"], entry["name"]) for entry in offered["valid_targets"]) == [
        ("permanent", "Grizzly Bears"), ("stack", "Lightning Bolt"),
    ]

    both = game.queue_from_hand(
        0, "Illusion", target_stack_index=0,
        target_permanent_ids=[bears.permanent_id],
    )
    assert not both.supported and "not one of each" in both.details
    assert p0.hand == [whole]

    assert game.queue_from_hand(0, "Illusion", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="U")

    assert game._stack_item_colors(bolt) == ("U",)
    assert game._effective_colors(bears) == {"G"}
    assert "Lightning Bolt (on the stack) became U until end of turn (Illusion)" in game.log
    assert [card.name for card in p0.graveyard] == ["Illusion // Reality"]
    assert [item.card.name for item in game.stack] == ["Lightning Bolt"]


def test_illusion_asks_its_colour_as_it_resolves_and_the_spell_keeps_it_as_a_permanent(
    set_pool, catalog_by_name
):
    """CR 608.2d: the colour is chosen while the effect is applied. CR 400.7a:
    the effect goes on applying to the permanent the spell becomes — a blue
    Grizzly Bears — and ends with the turn it was created in (CR 514.2)."""
    game, p0, p1 = _w2g1_duel(interactive=(0,))
    bears_spell = _w2g1_spell_from(game, 1, catalog_by_name["Grizzly Bears"])
    whole, _illusion = _w2g1_illusion(set_pool)
    p0.hand = [whole]

    assert game.queue_from_hand(0, "Illusion", target_stack_index=0).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game._stack_item_colors(bears_spell) == ("G",)
    game.resolve_pending_choice("color_choice", 0, mana_color="U")

    assert game._stack_item_colors(bears_spell) == ("U",)
    _w2g1_resolve_stack(game)
    (bears,) = p1.battlefield
    assert game._effective_colors(bears) == {"U"}

    game.resolve_cleanup_step(1)
    assert game._effective_colors(bears) == {"G"}


def test_illusion_recolours_a_permanent_until_end_of_turn(set_pool, catalog_by_name):
    """The permanent half, which is the half it always had."""
    game, p0, p1 = _w2g1_duel(interactive=(0,))
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    whole, _illusion = _w2g1_illusion(set_pool)
    p0.hand = [whole]

    assert game.queue_from_hand(
        0, "Illusion", target_permanent_ids=[bears.permanent_id]
    ).supported
    game.resolve_top_of_stack(pause_for_choices=True)
    game.resolve_pending_choice("color_choice", 0, mana_color="B")

    assert game._effective_colors(bears) == {"B"}
    assert "Grizzly Bears became B until end of turn (Illusion)" in game.log
    game.resolve_cleanup_step(0)
    assert game._effective_colors(bears) == {"G"}


def test_illusion_whose_spell_has_left_recolours_nothing(set_pool, catalog_by_name):
    """CR 608.2b: its one target is gone, so the spell does not resolve — and
    the creature on the battlefield is not a consolation target."""
    game, p0, p1 = _w2g1_duel()
    bears = _w2g1_put(game, 1, catalog_by_name["Grizzly Bears"])
    bolt = _w2g1_spell_from(game, 1, catalog_by_name["Lightning Bolt"], target_player_index=0)
    whole, _illusion = _w2g1_illusion(set_pool)
    p0.hand = [whole]

    assert game.queue_from_hand(0, "Illusion", target_stack_index=0).supported
    game.counter_stack_object(bolt)
    _w2g1_resolve_stack(game)

    assert game._effective_colors(bears) == {"G"}
    assert not any("became" in line for line in game.log)
    assert any("every target is illegal (608.2b)" in line for line in game.log)


def test_illusion_with_nothing_to_name_cannot_be_cast(set_pool):
    game, p0, _p1 = _w2g1_duel()
    whole, illusion = _w2g1_illusion(set_pool)
    p0.hand = [whole]

    assert game.cast_target_spec(0, illusion)["valid_targets"] == []
    assert not game.cast_from_hand(0, "Illusion").supported
    assert p0.hand == [whole]


def test_a_recolour_of_a_spell_or_permanent_union_is_described_or_refuses():
    """The lowering reads the union the noun now records: the bare phrase is
    described to the picker; a narrowing of it, a colour *set* or a plural
    refuses; and a phrase that names neither a spell nor the union no longer
    falls through to the Lace cycle's spell-or-permanent picker."""
    union = _w2g1_compile_line(
        "Target spell or permanent becomes the color of your choice until end of turn."
    )
    assert union.usable
    recolour = union.instructions[1]
    assert recolour.payload == {
        "targets": {"quantifier": "target", "kind": "spell_or_object"},
        "until_eot": True,
    }
    for line in (
        "Target red spell or permanent becomes the color of your choice.",
        "Target spell or permanent becomes the color or colors of your choice.",
        "Target creature becomes red.",
        "Target red spell or permanent becomes blue.",
    ):
        assert not _w2g1_compile_line(line).usable, line
    lace = _w2g1_compile_line("Target spell or permanent becomes red.")
    assert lace.usable and "targets" not in lace.instructions[0].payload


@_w2g1_pytest.mark.parametrize(
    "name, cast_kind",
    [("Suffocating Blast", "roles"), ("Illusion", "spell_or_permanent")],
)
def test_w2g1_both_cards_compile_supported_with_the_picker_they_print(
    set_pool, name, cast_kind
):
    cards = _w2g1_faces.compilation_units(
        [set_pool("APC")["Suffocating Blast"], set_pool("APC")["Illusion // Reality"]]
    )
    card = next(unit for unit in cards if unit.name == name)
    program = _w2g1_compile(card)

    assert program.supported
    assert _w2g1_derive_cast_spec(card, program)["kind"] == cast_kind

# ==== end W2G1 ========================================================

# ==== W2G2 ============================================================
# W2G2's tests go between this line and the "end W2G2" line.
from engine import Game as _w2g2_Game, PlayerState as _w2g2_Player
from engine.models import Permanent as _w2g2_Permanent
from tests.helpers import _mk_card as _w2g2_mk_card


def test_w2g2_prophetic_bolt_s_rest_go_down_in_the_order_the_caster_chose(set_pool):
    """"…Put one of those cards into your hand and the rest on the bottom of
    your library in any order." (CR 401.4.)

    Cast at the opponent's face by a seat somebody can ask, over a library of
    seven named cards: the caster keeps the second card looked at, is asked to
    arrange the other three, reverses them — and then draws the library down.
    The three untouched cards come first, as they lay; the bottomed ones follow
    in the order that was answered, the first of the answer first."""
    library = [_w2g2_mk_card(name=f"Card {n}", type_line="Land") for n in range(1, 8)]
    game = _w2g2_Game(players=[
        _w2g2_Player(name="P0", hand=[set_pool("APC")["Prophetic Bolt"]], library=library),
        _w2g2_Player(name="P1"),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game.interactive_seats = {0}
    me = game.players[0]

    assert game.cast_from_hand(0, "Prophetic Bolt", target_player_index=1).supported
    assert game.players[1].life == 16
    assert game.confirm_look_top_pick(0, 1)

    prompt = game.pending_choice_of("reorder_library", 0)
    assert prompt is not None and prompt.data["position"] == "bottom"
    assert [c.name for c in game.reorder_library_pile(prompt)] == [
        "Card 1", "Card 3", "Card 4",
    ]
    assert [item.card.name for item in game.stack] == ["Prophetic Bolt"]
    assert game.confirm_reorder_library(0, [2, 1, 0])
    game._settle()

    assert game.stack == [] and game.pending_choices == []
    assert [c.name for c in me.hand] == ["Card 2"]
    drawn = [me.library.pop(0).name for _ in range(len(me.library))]
    assert drawn == ["Card 5", "Card 6", "Card 7", "Card 4", "Card 3", "Card 1"]


def test_w2g2_captains_maneuver_says_which_of_its_two_targets_is_which(set_pool):
    """"The next X damage that would be dealt to target … is dealt to another
    target … instead." The two targets are read by position — the first is the
    one protected — so the spec names the positions for a picker, in that
    order, in the sentence's own words."""
    maneuver = set_pool("APC")["Captain's Maneuver"]
    game = _w2g2_Game(players=[_w2g2_Player(name="P0"), _w2g2_Player(name="P1")])

    spec = game.cast_target_spec(0, maneuver)

    assert spec["kind"] == "divided" and spec["divided_target_count"] == 2
    assert spec["target_roles"] == [
        "target the damage would be dealt to",
        "target the damage is dealt to instead",
    ]
    # No per-target increase is printed, and none is reported: a picker that
    # priced the second target the way Fireball's is priced offered one X fewer
    # than the pool could pay.
    assert "per_target_tax" not in spec


def test_w2g2_captains_maneuver_protects_the_first_named_and_burdens_the_second(set_pool):
    """The order of the announcement is the whole of who is protected: the
    caster's face first and the opposing Giant second moves a Bolt aimed at
    the caster onto the Giant; the same two targets named the other way round
    would protect the Giant instead."""
    lea = set_pool("LEA")
    giant = _w2g2_Permanent(card=lea["Hill Giant"])
    game = _w2g2_Game(players=[
        _w2g2_Player(name="P0", hand=[set_pool("APC")["Captain's Maneuver"]]),
        _w2g2_Player(name="P1", hand=[lea["Lightning Bolt"]]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._put_permanent_onto_battlefield(1, giant, None)

    assert game.cast_from_hand(
        0, "Captain's Maneuver", x_value=2, divided_targets=[(0, None), (1, 0)],
    ).supported
    assert (
        "Captain's Maneuver: the next 2 damage that would be dealt to P0 this "
        "turn is dealt to Hill Giant instead" in game.log
    )

    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 19 and giant.damage_marked == 2

# ==== end W2G2 ========================================================

# ==== W2G3 ============================================================
# W2G3's tests go between this line and the "end W2G3" line.

# ==== end W2G3 ========================================================

# ==== W2G4 ============================================================
# W2G4's tests go between this line and the "end W2G4" line.
from engine import Game as _w2g4_Game
from engine import PlayerState as _w2g4_PlayerState
from engine.models import Permanent as _w2g4_Permanent
from tests.helpers import _nosick as _w2g4_nosick


def _w2g4_instant_table(set_pool, catalog_by_name, *, hand, interactive):
    """Seat 0 at its main phase holding *hand* (Apocalypse cards) with a
    Forest; its library is an Island over two Swamps. Returns ``(game,
    forest)``."""
    forest = _w2g4_nosick(_w2g4_Permanent(card=catalog_by_name["Forest"]))
    game = _w2g4_Game(players=[
        _w2g4_PlayerState(
            name="Chooser", hand=[set_pool("APC")[name] for name in hand],
            battlefield=[forest],
            library=[catalog_by_name[name] for name in ("Island", "Swamp", "Swamp")],
        ),
        _w2g4_PlayerState(name="Other", library=[catalog_by_name["Swamp"]] * 3),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._settle()
    return game, forest  # W2G4: the instant table


# -- item 4: the type is named before the card is drawn -----------------------


def test_w2g4_shimmering_mirage_draws_only_after_the_type_is_named(
    set_pool, catalog_by_name
):
    """"Target land becomes the basic land type of your choice until end of
    turn. / Draw a card." CR 608.2c: in the order written.

    A human seat was asked for the type with the card already drawn — the log
    read "choose a basic land type…", "drew 1 card", "awaiting a choice". Now
    the hand is empty and the library untouched while the prompt is owed, the
    spell is held on the stack, and the answer is what lets the draw happen.
    """
    game, forest = _w2g4_instant_table(
        set_pool, catalog_by_name, hand=["Shimmering Mirage"], interactive=(0,),
    )
    chooser = game.players[0]
    mark = len(game.log)

    assert game.cast_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[forest.permanent_id]
    ).supported

    assert game.pending_land_type_choice["player_index"] == 0
    assert chooser.hand == [] and len(chooser.library) == 3
    assert [item.card.name for item in game.stack] == ["Shimmering Mirage"]
    assert game.waiting_prompt() is not None and game.effect_suspended
    assert game.log[mark:] == [
        "Shimmering Mirage added to stack",
        "Shimmering Mirage: choose a basic land type for Forest",
        "Shimmering Mirage is resolving, awaiting a choice",
    ]

    assert game.confirm_land_type(0, "swamp") is True

    assert forest.basic_land_types == ("swamp",)
    assert [card.name for card in chooser.hand] == ["Island"]
    assert [card.name for card in chooser.graveyard] == ["Shimmering Mirage"]
    assert game.stack == [] and game.waiting_prompt() is None
    assert game.log[mark + 3:] == [
        "Shimmering Mirage: Forest becomes a Swamp",
        "Shimmering Mirage drew 1 card",
        "Shimmering Mirage resolved and moved to graveyard",
        "Shimmering Mirage finished resolving",
    ]


def test_w2g4_shimmering_mirage_for_a_seat_nobody_asks_still_does_both(
    set_pool, catalog_by_name
):
    """The kind stays queued for a seat the engine plays — its callers are
    written around that — and the queue's own default is what finishes the
    spell: the land becomes an Island, the card is drawn, in that order."""
    game, forest = _w2g4_instant_table(
        set_pool, catalog_by_name, hand=["Shimmering Mirage"], interactive=(),
    )
    chooser = game.players[0]

    assert game.cast_from_hand(
        0, "Shimmering Mirage", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert game.pending_land_type_choice is not None and chooser.hand == []

    game.auto_resolve_pending_choices()

    assert forest.basic_land_types == ("island",)
    assert [card.name for card in chooser.hand] == ["Island"]
    assert [card.name for card in chooser.graveyard] == ["Shimmering Mirage"]
    assert game.pending_choices == [] and not game.effect_suspended


# -- item 7: a two-ended redirect is announced with two sides -----------------


def _w2g4_maneuver_table(set_pool, catalog_by_name):
    """Seat 0 holds Captain's Maneuver with a Grizzly Bears; seat 1 has a Hill
    Giant and a Lightning Bolt in hand."""
    game, _forest = _w2g4_instant_table(
        set_pool, catalog_by_name, hand=["Captain's Maneuver"], interactive=(),
    )
    bears = _w2g4_nosick(_w2g4_Permanent(card=catalog_by_name["Grizzly Bears"]))
    giant = _w2g4_nosick(_w2g4_Permanent(card=catalog_by_name["Hill Giant"]))
    game._put_permanent_onto_battlefield(0, bears, 0)
    game._put_permanent_onto_battlefield(1, giant, 1)
    game.players[1].hand.append(catalog_by_name["Lightning Bolt"])
    return game, bears, giant  # W2G4: the Maneuver table


def test_w2g4_the_ai_spares_itself_and_sends_captains_maneuvers_damage_across(
    set_pool, catalog_by_name
):
    """"The next X damage that would be dealt to target creature, planeswalker,
    or player this turn is dealt to another target creature, planeswalker, or
    player instead." The announcement's first entry is spared and its second
    takes the damage. Read as one side for both, the AI named two opposing
    objects — it shielded its opponent's face and sent the damage to their
    creature. It names its own face and theirs now, and the announcement does
    what the card prints: of a Bolt aimed at the caster, two go across."""
    from engine.ai_policy import choose_divided_targets

    game, _bears, _giant = _w2g4_maneuver_table(set_pool, catalog_by_name)
    maneuver = set_pool("APC")["Captain's Maneuver"]

    announced = choose_divided_targets(game, 0, maneuver, x_value=2)
    assert announced == [(0, None), (1, None)]

    assert game.cast_from_hand(
        0, "Captain's Maneuver", x_value=2, divided_targets=announced,
    ).supported
    assert (
        "Captain's Maneuver: the next 2 damage that would be dealt to Chooser "
        "this turn is dealt to Other instead"
    ) in game.log
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert [player.life for player in game.players] == [19, 18]


def test_w2g4_captains_maneuver_is_not_proposed_with_nobody_to_send_the_damage_to(
    set_pool, catalog_by_name
):
    """A slot with nothing on its own board to name is no announcement, rather
    than one filled from the other board: with the opponent untargetable and
    no opposing permanent, the second end has no taker and the card is not
    announced at all."""
    from engine.ai_policy import choose_divided_targets

    game, _forest = _w2g4_instant_table(
        set_pool, catalog_by_name, hand=["Captain's Maneuver"], interactive=(),
    )
    ivory = _w2g4_nosick(_w2g4_Permanent(card=catalog_by_name["Ivory Mask"]))
    game._put_permanent_onto_battlefield(1, ivory, 1)
    game._recompute_continuous_effects()
    maneuver = set_pool("APC")["Captain's Maneuver"]
    offered = game.cast_target_spec(0, maneuver)["valid_targets"]
    assert not any(entry["seat"] == 1 for entry in offered), offered

    assert choose_divided_targets(game, 0, maneuver, x_value=2) == []


def test_w2g4_captains_maneuver_in_a_simulated_game_protects_its_caster():
    """Whole games with the card pinned into both decks: every Maneuver that
    resolves moves damage off the seat that cast it."""
    from engine.ai_simulator import run_ai_simulation
    from engine.card_loader import manifest_set_path

    redirects = []
    for seed in (7, 11, 1337):
        report = run_ai_simulation(
            cards_path=[manifest_set_path("APC", include_measured=True)],
            games=4, seed=seed, max_turns=18, required_cards=["Captain's Maneuver"],
        )
        assert report.ok, report.issues[:3]
        caster = None
        for line in report.log_lines:
            if " cast Captain's Maneuver" in line:
                caster = line.split(" cast ")[0].split()[-1]
            elif line.strip().startswith("Captain's Maneuver: the next "):
                spared = line.split("would be dealt to ")[1].split(" this turn")[0]
                taker = line.split("is dealt to ")[1].split(" instead")[0]
                redirects.append((caster, spared, taker))
        if redirects:
            break

    assert redirects, "no seed cast a Captain's Maneuver"
    for caster, spared, taker in redirects:
        assert spared == caster and taker != caster, redirects


# -- item 6: a private look names nothing in the log ---------------------------


def test_w2g4_prophetic_bolt_keeps_a_card_the_log_does_not_name(set_pool, catalog_by_name):
    """"Prophetic Bolt deals 4 damage to any target. Look at the top four
    cards of your library. Put one of those cards into your hand and the rest
    on the bottom of your library in any order." To look is not to reveal
    (CR 701.20e): the log, which every seat is sent, used to say "put Island
    into their hand". The card is in the hand; the line says "a card"."""
    game, _forest = _w2g4_instant_table(
        set_pool, catalog_by_name, hand=["Prophetic Bolt"], interactive=(0,),
    )
    chooser = game.players[0]
    chooser.library[:] = [
        catalog_by_name[name] for name in ("Island", "Serra Angel", "Sol Ring", "Crusade", "Swamp")
    ]
    mark = len(game.log)

    assert game.cast_from_hand(0, "Prophetic Bolt", target_player_index=1).supported
    assert game.players[1].life == 16
    assert game.pending_choice_of("look_top_pick", 0) is not None
    assert game.confirm_look_top_pick(0, 1)

    assert [card.name for card in chooser.hand] == ["Serra Angel"]
    assert [card.name for card in chooser.library] == ["Swamp", "Island", "Sol Ring", "Crusade"]
    said = game.log[mark:]
    assert "Chooser put a card into their hand and the rest away" in said
    assert not any(
        name in line for line in said for name in ("Island", "Serra Angel", "Sol Ring", "Crusade")
    ), said

# ==== end W2G4 ========================================================

# ==== W2G5 ============================================================
# W2G5's tests go between this line and the "end W2G5" line.

# ==== end W2G5 ========================================================
