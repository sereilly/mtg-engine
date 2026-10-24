"""Judgment creatures (legendary ones too).

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("JUD")` / `set_cards("JUD")` — never a new
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
#
# Barbarian Bully: "Discard a card at random: This creature gets +2/+2 until
# end of turn unless a player has this creature deal 4 damage to them.
# Activate only once each turn." CR 118.12a's "unless [a player does
# something else]" over every seat — the deed-priced ``unless_player_pays``
# chain Browbeat's sentence also reaches, with the creature as the source.

from tests.sets import jud_w1g5_helpers as _w1g5  # noqa: E402


def _w1g5_bully(set_pool, hand=("Lightning Bolt",)):
    game = _w1g5.table(set_pool, hands=(list(hand), []), interactive=(0, 1))
    game.start_turn(0)
    bully = _w1g5.put(game, set_pool, 0, "Barbarian Bully")
    return game, bully


def test_w1g5_barbarian_bully_pumps_when_nobody_takes_the_four(set_pool):
    game, bully = _w1g5_bully(set_pool)

    activated = game.activate_permanent_ability(0, "Barbarian Bully")
    assert activated.supported, activated.details
    # The random discard is the *cost*: paid before the ability is on the stack.
    assert _w1g5.pile(game, 0) == ["Lightning Bolt"] and game.players[0].hand == []
    game.resolve_top_of_stack(pause_for_choices=True)
    assert _w1g5.answer_offers(game, {}) == [0, 1]
    _w1g5.settle(game)

    assert (bully.effective_power, bully.effective_toughness) == (4, 4)
    assert [player.life for player in game.players] == [20, 20]


def test_w1g5_barbarian_bully_taken_deals_four_to_the_taker_and_no_pump(set_pool):
    game, bully = _w1g5_bully(set_pool)

    game.activate_permanent_ability(0, "Barbarian Bully")
    game.resolve_top_of_stack(pause_for_choices=True)
    assert _w1g5.answer_offers(game, {1: True}) == [0, 1]
    _w1g5.settle(game)

    assert (bully.effective_power, bully.effective_toughness) == (2, 2)
    assert [player.life for player in game.players] == [20, 16]
    assert "Barbarian Bully dealt 4 damage to P2" in game.log


def test_w1g5_barbarian_bully_activates_only_once_each_turn(set_pool):
    game, _ = _w1g5_bully(set_pool, hand=("Lightning Bolt", "Giant Growth"))

    assert game.activate_permanent_ability(0, "Barbarian Bully").supported
    _w1g5.settle(game)
    again = game.activate_permanent_ability(0, "Barbarian Bully")

    assert not again.supported
    assert len(game.players[0].hand) == 1, "the refused activation paid nothing"


def test_w1g5_barbarian_bully_with_an_empty_hand_cannot_pay_its_discard(set_pool):
    game, bully = _w1g5_bully(set_pool, hand=())

    refused = game.activate_permanent_ability(0, "Barbarian Bully")

    assert not refused.supported
    assert game.stack == [] and _w1g5.owed(game) == []
    assert (bully.effective_power, bully.effective_toughness) == (2, 2)

# ==== end W1G5 ======================================================


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

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


# ==== W1G10 ==========================================================
# W1G10's tests go between this line and the "end W1G10" line.

# ==== end W1G10 ======================================================
