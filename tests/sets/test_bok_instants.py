"""Betrayers of Kamigawa instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("BOK")` / `set_cards("BOK")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== w1g1 ==========================================================
# w1g1's tests go between this line and the "end w1g1" line.

# ==== end w1g1 ======================================================


# ==== w1g2 ==========================================================
# w1g2's tests go between this line and the "end w1g2" line.

# ==== end w1g2 ======================================================


# ==== w1g3 ==========================================================
# w1g3's tests go between this line and the "end w1g3" line.

# ==== end w1g3 ======================================================


# ==== w1g4 ==========================================================
# w1g4's tests go between this line and the "end w1g4" line.

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# Damage: unpreventable damage with a life-gain replacement, damage doubling,
# redirection and two ordered dealings (CR 614, 615). Each test casts the
# spell through the engine's entry point and reads the board after `settle`.

import pytest as _w1g5_pytest

from engine import Game as _W1G5Game
from engine import PlayerState as _W1G5PlayerState
from engine.models import Permanent as _W1G5Permanent
from tests.helpers import settle as _w1g5_settle

_W1G5_SEATS = [
    _w1g5_pytest.param(set(), id="nobody-asked"),
    _w1g5_pytest.param({0, 1}, id="interactive"),
]


def _w1g5_table(set_pool, interactive=(), *, hand=(), opponent_hand=()):
    """Two seats on seat 0's first main phase, costs not enforced."""
    lea = set_pool("LEA")
    game = _W1G5Game(players=[
        _W1G5PlayerState(
            name=f"P{seat}", library=[lea["Island"]] * 20,
            hand=list(hand) if seat == 0 else list(opponent_hand),
        )
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    _w1g5_settle(game)
    return game


def _w1g5_put(game, card, seat=0):
    permanent = _W1G5Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w1g5_cast(game, seat, name, **announce):
    result = game.cast_from_hand(seat, name, **announce)
    assert result.supported, (result.details, game.log[-6:])
    _w1g5_settle(game)
    return result


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_flames_of_the_blood_hand_unpreventable_and_no_life_gain(
    set_pool, interactive,
):
    """"…deals 4 damage to target player or planeswalker. The damage can't
    be prevented. If that player or that planeswalker's controller would
    gain life this turn, that player gains no life instead." A Circle of
    Protection: Red shield is spent on nothing (CR 615.12) and the player
    takes all 4; their Healing Salve gains them nothing this turn (the
    replacement, CR 614.1a), while the caster's own gain is untouched — and
    next turn the target gains again."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Flames of the Blood Hand"]],
        opponent_hand=[lea["Healing Salve"]] * 3,
    )
    circle = _w1g5_put(game, lea["Circle of Protection: Red"], seat=1)
    result = game.activate_permanent_ability(
        1, circle.card.name, permanent_index=game.battlefield_index_of(circle),
    )
    assert result.supported
    _w1g5_settle(game)
    _w1g5_cast(game, 0, "Flames of the Blood Hand", target_player_index=1)
    assert game.players[1].life == 16, game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 16, game.log
    assert any("gains no life instead (Flames of the Blood Hand)" in line
               for line in game.log), game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=0)
    assert game.players[0].life == 23, game.log
    # CR 514.2: the record ends with the turn's cleanup step.
    game.resolve_cleanup_step(0)
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 19, game.log


def test_w1g5_flames_at_a_planeswalker_replaces_its_controllers_gains(set_pool):
    """Aimed at a planeswalker, the 4 damage is dealt to it — Garruk,
    Unleashed (loyalty 4) dies — and "that planeswalker's controller" is the
    seat whose gains are replaced."""
    bok, lea, m21 = set_pool("BOK"), set_pool("LEA"), set_pool("M21")
    game = _w1g5_table(
        set_pool, hand=[bok["Flames of the Blood Hand"]],
        opponent_hand=[lea["Healing Salve"]],
    )
    walker = _w1g5_put(game, m21["Garruk, Unleashed"], seat=1)
    _w1g5_cast(game, 0, "Flames of the Blood Hand",
               target_permanent_ids=[walker.permanent_id])
    assert game.players[1].life == 20, game.log
    assert not game.is_on_battlefield(walker), game.log
    _w1g5_cast(game, 1, "Healing Salve", target_player_index=1)
    assert game.players[1].life == 20, game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_overblaze_doubles_the_target_permanents_damage_only(
    set_pool, interactive,
):
    """"Each time target permanent would deal damage to a permanent or player
    this turn, it deals double that damage to that permanent or player
    instead." The targeted Prodigal Sorcerer pings for 2, every time this
    turn; a second Sorcerer — the same card, another object — still pings
    for 1 (CR 614). The record ends at cleanup (CR 514.2)."""
    bok, lea = set_pool("BOK"), set_pool("LEA")
    game = _w1g5_table(set_pool, interactive, hand=[bok["Overblaze"]])
    doubled = _w1g5_put(game, lea["Prodigal Sorcerer"])
    other = _w1g5_put(game, lea["Prodigal Sorcerer"])
    _w1g5_cast(game, 0, "Overblaze", target_permanent_ids=[doubled.permanent_id])

    def ping(sorcerer):
        sorcerer.tapped = False
        result = game.activate_permanent_ability(
            0, sorcerer.card.name,
            permanent_index=game.battlefield_index_of(sorcerer),
            target_player_index=1,
        )
        assert result.supported, result.details
        _w1g5_settle(game)

    ping(doubled)
    assert game.players[1].life == 18, game.log
    ping(other)
    assert game.players[1].life == 17, game.log
    ping(doubled)
    assert game.players[1].life == 15, game.log
    game.resolve_cleanup_step(0)
    ping(doubled)
    assert game.players[1].life == 14, game.log


def test_w1g5_overblaze_spliced_onto_an_arcane_spell(set_pool):
    """Spliced onto Lava Spike (CR 702.47), the spell deals its 3 and arms
    Overblaze's doubling on the permanent the splice targeted — an opposing
    Prodigal Sorcerer, whose ping then deals 2 — and Overblaze stays in
    hand."""
    bok, lea, chk = set_pool("BOK"), set_pool("LEA"), set_pool("CHK")
    game = _w1g5_table(set_pool, hand=[chk["Lava Spike"], bok["Overblaze"]])
    theirs = _w1g5_put(game, lea["Prodigal Sorcerer"], seat=1)
    _w1g5_cast(game, 0, "Lava Spike", target_player_index=1, splice_cards=[
        {"hand_index": 1, "target_permanent_ids": [theirs.permanent_id]},
    ])
    assert game.players[1].life == 17, game.log
    assert [card.name for card in game.players[0].hand] == ["Overblaze"]
    result = game.activate_permanent_ability(
        1, theirs.card.name, permanent_index=game.battlefield_index_of(theirs),
        target_player_index=0,
    )
    assert result.supported
    _w1g5_settle(game)
    assert game.players[0].life == 18, game.log


@_w1g5_pytest.mark.parametrize("interactive", _W1G5_SEATS)
def test_w1g5_aura_barbs_each_enchantment_deals_the_damage(set_pool, interactive):
    """"Each enchantment deals 2 damage to its controller, then each Aura
    attached to a creature deals 2 damage to the creature it's attached to."
    The damage is dealt by the enchantments, not by Aura Barbs (ruling
    2005-02-01): a Circle of Protection: White shield naming Holy Strength
    stops Holy Strength's 2 to its controller and nothing else — the Circle
    of Protection: Red beside it, another white source, still deals its 2 —
    and the red spell itself is no source a white Circle could ever stop.
    Holy Strength, on the opponent's Hill Giant, then deals 2 to the Giant;
    Bad Moon deals 2 to its own controller."""
    lea = set_pool("LEA")
    bok = set_pool("BOK")
    game = _w1g5_table(
        set_pool, interactive, hand=[bok["Aura Barbs"], lea["Holy Strength"]],
    )
    white_circle = _w1g5_put(game, lea["Circle of Protection: White"])
    _w1g5_put(game, lea["Circle of Protection: Red"])
    giant = _w1g5_put(game, lea["Hill Giant"], seat=1)
    _w1g5_put(game, lea["Bad Moon"], seat=1)
    _w1g5_cast(game, 0, "Holy Strength", target_permanent_ids=[giant.permanent_id])
    strength = next(
        perm for perm in game.players[0].battlefield
        if perm.card.name == "Holy Strength"
    )
    result = game.activate_permanent_ability(
        0, white_circle.card.name,
        permanent_index=game.battlefield_index_of(white_circle),
        target_permanent_ids=[strength.permanent_id],
    )
    assert result.supported, result.details
    _w1g5_settle(game)
    _w1g5_cast(game, 0, "Aura Barbs")
    # Seat 0: three white enchantments deal 2 each; the shielded one is
    # prevented. Seat 1: Bad Moon's 2.
    assert [p.life for p in game.players] == [16, 18], game.log
    assert "Circle of Protection: Red deals 2 damage to P0" in game.log
    assert "Circle of Protection: White deals 2 damage to P0" in game.log
    assert "Holy Strength deals 2 damage to P0" not in game.log
    assert giant.damage_marked == 2 and game.is_on_battlefield(giant), game.log

# ==== end w1g5 ======================================================



# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================


# ==== w1g8 ==========================================================
# w1g8's tests go between this line and the "end w1g8" line.

# ==== end w1g8 ======================================================


# ==== w1g9 ==========================================================
# w1g9's tests go between this line and the "end w1g9" line.

# ==== end w1g9 ======================================================


# ==== w1g10 ==========================================================
# w1g10's tests go between this line and the "end w1g10" line.

# ==== end w1g10 ======================================================
