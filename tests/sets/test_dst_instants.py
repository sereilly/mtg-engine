"""Darksteel instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("DST")` / `set_cards("DST")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Read the board after `tests.helpers.settle(game)`
(every owed prompt answered, the stack resolved, state-based actions
performed) and walk a combat with `tests.helpers.drive_combat(game)` —
never a bare `while game.stack:` loop, which spins forever once a seat is
owed a prompt. A test asserts what a game showed (boards, zones, life, the
log), not instruction kinds alone.
"""


# ==== W1G1 ==========================================================
# W1G1's tests go between this line and the "end W1G1" line.

# ==== end W1G1 ======================================================


# ==== W1G2 ==========================================================
# W1G2's tests go between this line and the "end W1G2" line.
#
# Unforge and Murderous Spoils: what a single-target destroy finds attached,
# either way round, read after the destroy (CR 608.2h).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import (attach_equipment as _w1g2_attach,
                              equipped_creature as _w1g2_equipped)
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def _w1g2_cast(game, seat, card, target, *, queue=False):
    game.players[seat].hand.append(card)
    cast = game.queue_from_hand if queue else game.cast_from_hand
    result = cast(seat, card.name, target_permanent_ids=[target.permanent_id])
    assert result.supported, result
    return result


def test_w1g2_unforge_damages_the_creature_it_was_attached_to(set_pool):
    """"Destroy target Equipment. If that Equipment was attached to a creature,
    Unforge deals 2 damage to that creature." The Equipment goes, its creature
    takes 2 (the Bears die); an unattached Equipment hurts nobody."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
    loose = _w1g2_put(game, dst["Leonin Bola"], 1)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 1)
    _w1g2_attach(game, star, bears)
    _w1g2_cast(game, 0, dst["Unforge"], star)
    _w1g2_settle(game)
    assert star not in game.controlled_by(1)
    assert bears not in game.controlled_by(1)
    assert "Grizzly Bears died (704.5g: lethal damage)" in game.log

    _w1g2_cast(game, 0, dst["Unforge"], loose)
    _w1g2_settle(game)
    assert loose not in game.controlled_by(1)
    assert ogre.damage_marked == 0


def test_w1g2_unforge_reads_where_the_equipment_was_as_it_was_destroyed(set_pool):
    """2004-12-01: "Unforge deals damage only to the creature that the
    Equipment was attached to when the Equipment was destroyed. It doesn't
    deal damage to creatures that the Equipment had previously equipped."
    Moved in response, the new host takes the damage and the first does not."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    first = _w1g2_put(game, lea["Grizzly Bears"], 1)
    second = _w1g2_put(game, lea["Hill Giant"], 1)
    _w1g2_attach(game, star, first)
    _w1g2_cast(game, 0, dst["Unforge"], star, queue=True)
    assert [item.card.name for item in game.stack] == ["Unforge"]
    _w1g2_attach(game, star, second)  # in response
    _w1g2_settle(game)
    assert star not in game.controlled_by(1)
    assert first.damage_marked == 0
    assert second.damage_marked == 2


def test_w1g2_unforge_on_an_indestructible_equipment_still_deals_damage(set_pool):
    """The condition asks where the Equipment was, not whether it died: Shield
    of Kaldra survives the destroy (indestructible), and the creature it is
    attached to is still dealt 2 — it survives too, wearing the Shield's
    indestructible."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    shield = _w1g2_put(game, dst["Shield of Kaldra"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
    _w1g2_attach(game, shield, bears)
    _w1g2_cast(game, 0, dst["Unforge"], shield)
    _w1g2_settle(game)
    assert shield in game.controlled_by(1) and _w1g2_equipped(shield) is bears
    assert bears in game.controlled_by(1)
    assert bears.damage_marked == 2


def test_w1g2_murderous_spoils_takes_the_equipment_that_were_attached(set_pool):
    """"Destroy target nonblack creature. It can't be regenerated. You gain
    control of all Equipment that were attached to it. (This effect lasts
    indefinitely.)" Both Equipment on the creature change hands for good, now
    unattached (CR 704.5n); an Equipment on another creature does not; a black
    creature is no target."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    seeker = _w1g2_put(game, dst["Heartseeker"], 1)
    elsewhere = _w1g2_put(game, dst["Leonin Bola"], 1)
    giant = _w1g2_put(game, lea["Hill Giant"], 1)
    ogre = _w1g2_put(game, lea["Gray Ogre"], 1)
    knight = _w1g2_put(game, lea["Black Knight"], 1)
    _w1g2_attach(game, star, giant)
    _w1g2_attach(game, elsewhere, ogre)

    game.players[0].hand.append(dst["Murderous Spoils"])
    refused = game.cast_from_hand(0, "Murderous Spoils", target_permanent_ids=[knight.permanent_id])
    assert not refused.supported
    game.players[0].hand.clear()

    _w1g2_attach(game, seeker, giant)
    _w1g2_cast(game, 0, dst["Murderous Spoils"], giant)
    _w1g2_settle(game)
    assert giant not in game.controlled_by(1)
    assert star in game.controlled_by(0) and seeker in game.controlled_by(0)
    assert _w1g2_equipped(star) is None and _w1g2_equipped(seeker) is None
    assert elsewhere in game.controlled_by(1) and _w1g2_equipped(elsewhere) is ogre

    # Indefinitely: still ours on the opponent's turn and after.
    game.start_turn(1)
    _w1g2_settle(game)
    game.start_turn(0)
    _w1g2_settle(game)
    assert star in game.controlled_by(0) and seeker in game.controlled_by(0)


def test_w1g2_murderous_spoils_ignores_regeneration(set_pool):
    """"It can't be regenerated." A regeneration shield does not save it."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
    ape = _w1g2_put(game, set_pool("2ED")["Wall of Brambles"], 1)
    _w1g2_attach(game, star, ape)
    result = game.activate_permanent_ability(
        1, ape.card.name, permanent_index=game.battlefield_index_of(ape),
    )
    assert result.supported, result
    _w1g2_settle(game)
    _w1g2_cast(game, 0, dst["Murderous Spoils"], ape)
    _w1g2_settle(game)
    assert ape not in game.controlled_by(1)
    assert star in game.controlled_by(0)

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

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
