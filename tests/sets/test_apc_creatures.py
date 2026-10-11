"""Apocalypse creatures.

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
    """A two-seat game with mana costs enforced. *hand* and *opp_hand* are
    Alpha cards — these creatures are put onto the battlefield, not cast."""
    lea = set_pool("LEA")
    game = _W1G2Game(players=[
        _W1G2PlayerState(
            "Caster", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in hand],
        ),
        _W1G2PlayerState(
            "Opponent", library=[lea["Forest"]] * 10,
            hand=[lea[name] for name in opp_hand],
        ),
    ])
    game.enforce_mana_costs = True
    game.players[0].mana_pool.update(mana or {})
    game.players[1].mana_pool.update(opp_mana or {})
    return game  # _w1g2_table (creatures)


def _w1g2_put(game, set_pool, seat, name, code="LEA", sick=False):
    """*name* onto *seat*'s battlefield; able to act this turn unless *sick*."""
    permanent = _W1G2Permanent(card=set_pool(code)[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    if not sick:
        permanent.metadata["summoning_sickness_turn"] = -99
    return permanent  # _w1g2_put (creatures)


def _w1g2_activate(game, permanent, **announcement):
    """Activate an ability of the caster's *permanent* and settle the stack."""
    return game.activate_permanent_ability(
        0, permanent.card.name,
        permanent_index=list(game.controlled_by(0)).index(permanent),
        **announcement,
    )  # _w1g2_activate


# The Bloodfire creatures ----------------------------------------------------


def _w1g2_bloodfire_board(set_pool, name):
    """*name* under the caster with {R} to pay, beside the caster's own Bears;
    across the table a Craw Wurm (6/4), an Air Elemental (4/4 flier) and
    Savannah Lions (2/1)."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    source = _w1g2_put(game, set_pool, 0, name, code="APC")
    board = {
        "bears": _w1g2_put(game, set_pool, 0, "Grizzly Bears"),
        "wurm": _w1g2_put(game, set_pool, 1, "Craw Wurm"),
        "air": _w1g2_put(game, set_pool, 1, "Air Elemental"),
        "lions": _w1g2_put(game, set_pool, 1, "Savannah Lions"),
    }
    return game, source, board  # _w1g2_bloodfire_board


def test_w1g2_bloodfire_colossus_deals_six_to_each_creature_and_each_player(set_pool):
    """"{R}, Sacrifice this creature: It deals 6 damage to each creature and
    each player." Everything on the table dies, and both players — its own
    controller included — are at 14."""
    game, colossus, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Colossus")

    result = _w1g2_activate(game, colossus)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert [player.life for player in game.players] == [14, 14]
    assert not list(game.all_permanents())
    assert "Bloodfire Colossus" in [card.name for card in game.players[0].graveyard]


def test_w1g2_bloodfire_dwarf_spares_the_creature_with_flying(set_pool):
    """"…It deals 1 damage to each creature without flying." One point on the
    Bears and the Wurm, the 2/1 Lions die, the Air Elemental is untouched, and
    no player is damaged."""
    game, dwarf, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Dwarf")

    result = _w1g2_activate(game, dwarf)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert (board["bears"].damage_marked, board["wurm"].damage_marked) == (1, 1)
    assert board["air"].damage_marked == 0
    assert not game.is_on_battlefield(board["lions"])
    assert [player.life for player in game.players] == [20, 20]


def test_w1g2_bloodfire_kavu_deals_two_to_each_creature(set_pool):
    """"…It deals 2 damage to each creature." Fliers included, both sides: the
    caster's own Bears and the Lions die, the Wurm and the Elemental carry 2."""
    game, kavu, board = _w1g2_bloodfire_board(set_pool, "Bloodfire Kavu")

    result = _w1g2_activate(game, kavu)
    game.check_state_based_actions()

    assert result.supported, result.details
    assert (board["wurm"].damage_marked, board["air"].damage_marked) == (2, 2)
    assert not game.is_on_battlefield(board["bears"])
    assert not game.is_on_battlefield(board["lions"])
    assert [player.life for player in game.players] == [20, 20]


@_w1g2_pytest.mark.parametrize(
    "name", ["Bloodfire Colossus", "Bloodfire Dwarf", "Bloodfire Kavu"],
)
def test_w1g2_a_bloodfire_creature_is_not_sacrificed_to_a_refused_activation(
    set_pool, name,
):
    """The sacrifice is a cost (CR 602.2b), paid with the {R} or not at all:
    with no mana the creature stays and nothing is damaged. With it, the
    ability works the turn the creature arrived — the cost has no {T}."""
    game, source, board = _w1g2_bloodfire_board(set_pool, name)
    game.players[0].mana_pool["R"] = 0

    assert not _w1g2_activate(game, source).supported
    assert game.is_on_battlefield(source)
    assert board["lions"].damage_marked == 0

    game = _w1g2_table(set_pool, mana={"R": 1})
    fresh = _w1g2_put(game, set_pool, 0, name, code="APC", sick=True)
    assert _w1g2_activate(game, fresh).supported
    assert not game.is_on_battlefield(fresh)


# Goblin Legionnaire ---------------------------------------------------------


def test_w1g2_goblin_legionnaire_red_ability_deals_two_to_any_target(set_pool):
    """"{R}, Sacrifice this creature: It deals 2 damage to any target." At a
    creature, which dies; at a face, which is at 18. The {W} is left alone."""
    game = _w1g2_table(set_pool, mana={"R": 1, "W": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    bears = _w1g2_put(game, set_pool, 1, "Grizzly Bears")
    assert _w1g2_activate(
        game, legionnaire, ability_index=0, target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert not game.is_on_battlefield(bears) and not game.is_on_battlefield(legionnaire)
    assert game.players[0].mana_pool["W"] == 1

    game = _w1g2_table(set_pool, mana={"R": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert _w1g2_activate(
        game, legionnaire, ability_index=0, target_player_index=1,
    ).supported
    assert game.players[1].life == 18


def test_w1g2_goblin_legionnaire_white_ability_prevents_the_next_two_damage(set_pool):
    """"{W}, Sacrifice this creature: Prevent the next 2 damage that would be
    dealt to any target this turn." A Lightning Bolt at the shielded Bears
    marks 1; one at the shielded player costs them 1."""
    game = _w1g2_table(
        set_pool, mana={"W": 1}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    bears = _w1g2_put(game, set_pool, 0, "Grizzly Bears")
    assert _w1g2_activate(
        game, legionnaire, ability_index=1, target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert bears.damage_marked == 1 and game.is_on_battlefield(bears)

    game = _w1g2_table(
        set_pool, mana={"W": 1}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert _w1g2_activate(
        game, legionnaire, ability_index=1, target_player_index=0,
    ).supported
    assert game.cast_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    assert game.players[0].life == 19


def test_w1g2_goblin_legionnaire_each_ability_needs_its_own_colour(set_pool):
    """The red ability cannot be paid with {W}: refused, and the Legionnaire is
    not sacrificed. Nor may it be aimed at a creature with protection from
    white — the Legionnaire is red *and* white (CR 702.16b)."""
    game = _w1g2_table(set_pool, mana={"W": 1})
    legionnaire = _w1g2_put(game, set_pool, 0, "Goblin Legionnaire", code="APC")
    assert not _w1g2_activate(
        game, legionnaire, ability_index=0, target_player_index=1,
    ).supported
    assert game.is_on_battlefield(legionnaire) and game.players[1].life == 20

    game.players[0].mana_pool.update({"W": 0, "R": 1})
    knight = _w1g2_put(game, set_pool, 1, "Black Knight")
    assert not _w1g2_activate(
        game, legionnaire, ability_index=0, target_permanent_ids=[knight.permanent_id],
    ).supported
    assert game.is_on_battlefield(legionnaire) and game.players[0].mana_pool["R"] == 1


# Minotaur Illusionist -------------------------------------------------------


def test_w1g2_minotaur_illusionist_gains_shroud_until_end_of_turn(set_pool):
    """"{1}{U}: This creature gains shroud until end of turn." A Lightning
    Bolt aimed at it afterwards is an illegal announcement and is not cast."""
    game = _w1g2_table(
        set_pool, mana={"U": 2}, opp_hand=["Lightning Bolt"], opp_mana={"R": 1},
    )
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")

    assert _w1g2_activate(game, illusionist, ability_index=0).supported
    assert game._has_keyword(illusionist, "shroud")

    bolt = game.cast_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[illusionist.permanent_id],
    )
    assert not bolt.supported
    assert [card.name for card in game.players[1].hand] == ["Lightning Bolt"]
    assert illusionist.damage_marked == 0


def test_w1g2_minotaur_illusionist_deals_the_power_it_last_had(set_pool):
    """"{R}, Sacrifice this creature: It deals damage equal to its power to
    target creature." Its printed 3 kills a Hill Giant; pumped to 6 by a Giant
    Growth it kills a Craw Wurm, the power being the one it last had on the
    battlefield (CR 608.2h) — it is in the graveyard when the ability
    resolves."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    giant = _w1g2_put(game, set_pool, 1, "Hill Giant")
    assert _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[giant.permanent_id],
    ).supported
    assert giant.damage_marked == 3
    assert "Minotaur Illusionist deals 3 damage to Hill Giant" in game.log
    assert not game.is_on_battlefield(illusionist)

    game = _w1g2_table(set_pool, hand=["Giant Growth"], mana={"R": 1, "G": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    wurm = _w1g2_put(game, set_pool, 1, "Craw Wurm")
    assert game.cast_from_hand(
        0, "Giant Growth", target_permanent_ids=[illusionist.permanent_id],
    ).supported
    _w1g2_resolve_stack(game)
    assert _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[wurm.permanent_id],
    ).supported
    game.check_state_based_actions()
    assert not game.is_on_battlefield(wurm)


def test_w1g2_minotaur_illusionist_is_not_sacrificed_at_an_illegal_target(set_pool):
    """A land is not a creature: the activation is refused before the cost is
    paid (CR 601.2c precedes 601.2h), so the Illusionist and the {R} stay."""
    game = _w1g2_table(set_pool, mana={"R": 1})
    illusionist = _w1g2_put(game, set_pool, 0, "Minotaur Illusionist", code="APC")
    forest = _w1g2_put(game, set_pool, 1, "Forest")

    result = _w1g2_activate(
        game, illusionist, ability_index=1, target_permanent_ids=[forest.permanent_id],
    )

    assert not result.supported
    assert game.is_on_battlefield(illusionist)
    assert game.players[0].mana_pool["R"] == 1


# Razorfin Hunter ------------------------------------------------------------


def test_w1g2_razorfin_hunter_taps_to_deal_one_damage_to_any_target(set_pool):
    """"{T}: This creature deals 1 damage to any target." It taps, the 2/1
    Lions are marked 1; untapped again, a face takes 1. A land is no target,
    and that refusal leaves the Hunter untapped."""
    game = _w1g2_table(set_pool)
    hunter = _w1g2_put(game, set_pool, 0, "Razorfin Hunter", code="APC")
    lions = _w1g2_put(game, set_pool, 1, "Savannah Lions")
    forest = _w1g2_put(game, set_pool, 1, "Forest")

    assert _w1g2_activate(game, hunter, target_permanent_ids=[lions.permanent_id]).supported
    assert hunter.tapped and lions.damage_marked == 1
    assert not _w1g2_activate(game, hunter, target_player_index=1).supported, "tapped"

    hunter.tapped = False
    assert _w1g2_activate(game, hunter, target_player_index=1).supported
    assert game.players[1].life == 19

    hunter.tapped = False
    assert not _w1g2_activate(
        game, hunter, target_permanent_ids=[forest.permanent_id],
    ).supported
    assert not hunter.tapped


def test_w1g2_razorfin_hunter_cannot_tap_the_turn_it_arrives(set_pool):
    """CR 302.6: a {T} ability of a creature that came under its controller's
    control this turn cannot be activated."""
    game = _w1g2_table(set_pool)
    hunter = _w1g2_put(game, set_pool, 0, "Razorfin Hunter", code="APC", sick=True)

    assert not _w1g2_activate(game, hunter, target_player_index=1).supported
    assert game.players[1].life == 20 and not hunter.tapped

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
