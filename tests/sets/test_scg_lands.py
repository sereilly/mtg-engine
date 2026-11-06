"""Scourge lands.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("SCG")` / `set_cards("SCG")` — never a new
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
#
# Temple of the False God: "{T}: Add {C}{C}. Activate only if you control
# five or more lands." A mana ability (CR 605.1a) whose CR 602.5 clause is a
# board fact — asked at the tap seam, by the planners and by the activation
# path alike, and the land's only mana ability, so it is the bare tap.
from engine import Game as _W1G8Game
from engine.board_payment import board_can_pay as _w1g8_board_can_pay
from engine.models import Permanent as _W1G8Permanent
from engine.models import PlayerState as _W1G8PlayerState

from tests.helpers import resolve_stack as _w1g8_resolve_stack


def _w1g8_temple_table(set_pool, mountains, hand=()):
    """Seat 0 with Temple of the False God and *mountains* Mountains, mana
    costs enforced."""
    lea = set_pool("LEA")
    alice = _W1G8PlayerState(name="Alice", hand=list(hand), library=[lea["Plains"]] * 5)
    bob = _W1G8PlayerState(name="Bob", library=[lea["Island"]] * 5)
    game = _W1G8Game(players=[alice, bob])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    placed = []
    for card in [set_pool("SCG")["Temple of the False God"]] + [lea["Mountain"]] * mountains:
        perm = _W1G8Permanent(card=card)
        game._put_permanent_onto_battlefield(0, perm, None)
        perm.metadata["summoning_sickness_turn"] = -99
        placed.append(perm)
    game._sync_control()
    return game, alice, placed[0]


def test_w1g8_temple_of_the_false_god_needs_five_lands(set_pool):
    """On four lands the tap is refused at both doors — the tap seam and the
    activation path — with the printed clause as the reason, and nothing is
    tapped or added; the castable highlight's question agrees."""
    game, alice, temple = _w1g8_temple_table(set_pool, 3)
    refusal = game.tap_land_for_mana_or_refusal(
        0, temple.card.name, "C", permanent_id=temple.permanent_id,
    )
    assert refusal is not None and "five or more lands" in refusal
    assert not temple.tapped and alice.mana_pool.get("C", 0) == 0
    activated = game.activate_permanent_ability(
        0, temple.card.name, permanent_index=game.battlefield_index_of(temple),
        ability_index=0,
    )
    assert not activated.supported
    assert not temple.tapped and alice.mana_pool.get("C", 0) == 0
    assert not _w1g8_board_can_pay(game, 0, {"generic": 4, "R": 2})
    assert _w1g8_board_can_pay(game, 0, {"generic": 3})


def test_w1g8_temple_of_the_false_god_taps_for_two_on_five_lands(set_pool):
    """The Temple counts itself: with four Mountains beside it, a tap asked
    for {C} activates its one mana ability (CR 605: asking for a symbol picks
    the ability, ``land_mana_ability_for``) and adds {C}{C}; so does the
    activation path."""
    game, alice, temple = _w1g8_temple_table(set_pool, 4)
    assert game.land_mana_ability_for(temple, "C") == 0
    assert game.tap_land_for_mana(0, temple.card.name, "C", permanent_id=temple.permanent_id)
    assert temple.tapped and alice.mana_pool.get("C", 0) == 2
    game, alice, temple = _w1g8_temple_table(set_pool, 4)
    activated = game.activate_permanent_ability(
        0, temple.card.name, permanent_index=game.battlefield_index_of(temple),
        ability_index=0,
    )
    assert activated.supported, activated.details
    assert temple.tapped and alice.mana_pool.get("C", 0) == 2


def test_w1g8_temple_of_the_false_god_pays_the_ais_six_drop(set_pool):
    """The AI's planner counts the Temple's two and its executor's tap makes
    them — the payment the brief warned could strand part-way: Shivan Dragon
    ({4}{R}{R}) off the Temple and four Mountains, cast and resolved."""
    from engine.ai_payment import tap_planned_lands
    from engine.ai_policy import choose_cast_action

    lea = set_pool("LEA")
    game, alice, temple = _w1g8_temple_table(set_pool, 4, hand=[lea["Shivan Dragon"]])
    assert _w1g8_board_can_pay(game, 0, {"generic": 4, "R": 2})
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Shivan Dragon"
    assert game.battlefield_index_of(temple) in action.land_tap_indices
    action = tap_planned_lands(game, 0, action)
    assert temple.tapped
    result = game.cast_from_hand(0, "Shivan Dragon")
    assert result.supported, result.details
    _w1g8_resolve_stack(game)
    assert any(perm.card.name == "Shivan Dragon" for perm in game.controlled_by(0))


def test_w1g8_temple_of_the_false_god_is_no_six_drop_on_four_lands(set_pool):
    from engine.ai_policy import choose_cast_action

    lea = set_pool("LEA")
    game, _alice, _temple = _w1g8_temple_table(set_pool, 3, hand=[lea["Shivan Dragon"]])
    assert choose_cast_action(game, 0) is None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
