"""Apocalypse sorceries.

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

# ==== end W1G2 ========================================================


# ==== W1G3 ============================================================
# W1G3's tests go between this line and the "end W1G3" line.

# ==== end W1G3 ========================================================


# ==== W1G4 ============================================================
# W1G4's tests go between this line and the "end W1G4" line.

# ==== end W1G4 ========================================================


# ==== W1G5 ============================================================
# W1G5's tests go between this line and the "end W1G5" line.

from engine import Game as _w1g5s_Game, PlayerState as _w1g5s_Player
from engine import faces as _w1g5s_faces
from engine.models import Permanent as _w1g5s_Permanent
from tests.helpers import _mk_card as _w1g5s_mk_card
from tests.helpers import resolve_stack as _w1g5s_resolve_stack


def _w1g5s_duel(mine=(), theirs=(), *, hand0=(), graveyard0=(), graveyard1=()):
    """Two boards placed and unsick, seat 0's turn begun."""
    board0 = [_w1g5s_Permanent(card=card) for card in mine]
    board1 = [_w1g5s_Permanent(card=card) for card in theirs]
    filler = _w1g5s_mk_card(name="Filler", type_line="Creature - Wall", power=0, toughness=1)
    game = _w1g5s_Game(players=[
        _w1g5s_Player(name="P0", battlefield=board0, hand=list(hand0),
                      library=[filler] * 10, graveyard=list(graveyard0)),
        _w1g5s_Player(name="P1", battlefield=board1, library=[filler] * 10,
                      graveyard=list(graveyard1)),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for permanent in board0 + board1:
        permanent.metadata["summoning_sickness_turn"] = -99
    game.start_turn(0)
    game._settle()
    return game, board0, board1  # W1G5 sorceries: the duel


def _w1g5s_half(card, name):
    return next(face for face in _w1g5s_faces.face_cards(card) if face.name == name)  # W1G5


def test_life_makes_its_casters_lands_creatures_that_are_still_lands(set_pool):
    """Life // Death, the Life half {G}: "All lands you control become 1/1
    creatures until end of turn. They're still lands." The caster's Forests
    are 1/1 creatures and still Forests; the opponent's is untouched; a land
    played afterwards is not animated (CR 611.2c); and at cleanup they are
    lands and nothing else."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, mine, theirs = _w1g5s_duel(
        [lea["Forest"], lea["Forest"], lea["Grizzly Bears"]], [lea["Forest"]], hand0=[card],
    )
    assert game.cast_target_spec(0, _w1g5s_half(card, "Life"))["kind"] == "none"
    assert game.cast_from_hand(0, "Life").supported
    for forest in mine[:2]:
        assert forest.is_creature and forest.has_type("land") and forest.has_type("forest")
        assert (forest.effective_power, forest.effective_toughness) == (1, 1)
    assert (mine[2].effective_power, mine[2].effective_toughness) == (2, 2)
    assert not theirs[0].is_creature
    late = _w1g5s_Permanent(card=lea["Forest"])
    game._put_permanent_onto_battlefield(0, late, None)
    assert not late.is_creature
    game.resolve_cleanup_step(0)
    assert not any(forest.is_creature for forest in mine[:2])
    assert all(forest.has_type("forest") for forest in mine[:2])


def test_death_returns_a_creature_card_and_charges_its_mana_value_in_life(set_pool):
    """The Death half {1}{B}: "Return target creature card from your graveyard
    to the battlefield. You lose life equal to its mana value." The Craw Wurm
    (mana value 6) comes back under its owner's control and the caster is at
    14. Only a creature card, only the caster's own graveyard: a Bolt there and
    a creature in the opponent's are neither offered nor accepted, and with
    nothing to return the spell cannot be cast."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    card = apc["Life // Death"]
    game, _mine, _theirs = _w1g5s_duel(
        hand0=[card], graveyard0=[lea["Lightning Bolt"], lea["Craw Wurm"]],
        graveyard1=[lea["Grizzly Bears"]],
    )
    offered = game.cast_target_spec(0, _w1g5s_half(card, "Death"))["valid_targets"]
    assert [(entry["seat"], entry["name"]) for entry in offered] == [(0, "Craw Wurm")]
    for announcement in (
        {"target_player_index": 0, "target_permanent_index": 0},   # the Bolt
        {"target_player_index": 1, "target_permanent_index": 0},   # their Bears
    ):
        refused = game.queue_from_hand(0, "Death", **announcement)
        assert not refused.supported, refused
    assert game.players[0].hand == [card]

    assert game.cast_from_hand(
        0, "Death", target_player_index=0, target_permanent_index=1
    ).supported
    wurm = next(iter(game.controlled_by(0)))
    assert wurm.card.name == "Craw Wurm"
    assert game.players[0].life == 14 and game.players[1].life == 20
    assert sorted(c.name for c in game.players[0].graveyard) == ["Life // Death", "Lightning Bolt"]

    empty, _mine, _theirs = _w1g5s_duel(hand0=[card], graveyard0=[lea["Lightning Bolt"]])
    refused = empty.queue_from_hand(0, "Death")
    assert not refused.supported and "no valid target" in refused.details


def test_vindicate_destroys_whatever_permanent_it_names(set_pool):
    """Vindicate {1}{W}{B}: "Destroy target permanent." A land, an artifact,
    an enchantment, a creature — each named by id and each in its owner's
    graveyard afterwards, with the rest of the board where it was."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], lea["Sol Ring"], lea["Crusade"], lea["Grizzly Bears"]],
        hand0=[vindicate] * 4,
    )
    offered = game.cast_target_spec(0, vindicate)
    assert offered["kind"] == "permanent"
    assert [entry["name"] for entry in offered["valid_targets"]] == [
        "Forest", "Sol Ring", "Crusade", "Grizzly Bears",
    ]
    for victim in theirs:
        before = [p.card.name for p in game.controlled_by(1)]
        assert game.cast_from_hand(
            0, "Vindicate", target_permanent_ids=[victim.permanent_id]
        ).supported
        before.remove(victim.card.name)
        assert [p.card.name for p in game.controlled_by(1)] == before
    assert sorted(c.name for c in game.players[1].graveyard) == [
        "Crusade", "Forest", "Grizzly Bears", "Sol Ring",
    ]
    assert game.players[1].life == 20


def test_vindicate_has_to_be_spent_on_a_flagbearer(set_pool):
    """Under Standard Bearer the land Vindicate was held for is not a legal
    announcement while the Bearer can be named; with the Bearer destroyed the
    next one takes the land."""
    apc, lea = set_pool("APC"), set_pool("LEA")
    vindicate = apc["Vindicate"]
    game, _mine, theirs = _w1g5s_duel(
        [], [lea["Forest"], apc["Standard Bearer"]], hand0=[vindicate, vindicate],
    )
    forest, bearer = theirs
    refused = game.queue_from_hand(0, "Vindicate", target_permanent_ids=[forest.permanent_id])
    assert not refused.supported and "must be chosen as a target if able" in refused.details
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[bearer.permanent_id]
    ).supported
    assert game.cast_from_hand(
        0, "Vindicate", target_permanent_ids=[forest.permanent_id]
    ).supported
    assert list(game.controlled_by(1)) == []

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
