"""Darksteel enchantments, Auras included.

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
# Carry Away: an Aura on an Equipment, its entry trigger's unattach, and the
# layer-2 control change while attached.

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import (attach_equipment as _w1g2_attach,
                              equipped_creature as _w1g2_equipped)
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import settle as _w1g2_settle


def _w1g2_table(set_pool, *, interactive=()):
    island = set_pool("LEA")["Island"]
    game = _W1G2Game(players=[
        _W1G2PlayerState(name=f"P{seat}", library=[island] * 20) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g2_put(game, card, seat):
    permanent = _W1G2Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g2_settle(game)
    return permanent


def test_w1g2_carry_away_takes_and_unattaches_an_equipment(set_pool):
    """"Enchant Equipment / When this Aura enters, unattach enchanted
    Equipment. / You control enchanted Equipment." Only an Equipment is a
    legal host (CR 303.4a); on entry it comes off the creature it was on and
    stays on the battlefield (CR 701.3d), under the Aura's controller (CR 613
    layer 2), who may then equip it (2004-12-01). The Aura gone, control goes
    back — and the Equipment stays where its new controller put it (gaining or
    losing control moves nothing)."""
    from engine.targeting import derive_cast_spec
    from engine.oracle import compile_card_oracle

    dst, lea = set_pool("DST"), set_pool("LEA")
    for interactive in ((), (0, 1)):
        game = _w1g2_table(set_pool, interactive=interactive)
        ogre = _w1g2_put(game, lea["Gray Ogre"], 0)
        star = _w1g2_put(game, dst["Vulshok Morningstar"], 1)
        bears = _w1g2_put(game, lea["Grizzly Bears"], 1)
        _w1g2_attach(game, star, bears)
        carry = dst["Carry Away"]
        assert derive_cast_spec(carry, compile_card_oracle(carry)) == {
            "kind": "artifact", "filter": {"subtype_filter": "equipment"},
        }
        game.players[0].hand = [carry]
        refused = game.cast_from_hand(0, "Carry Away", target_permanent_ids=[bears.permanent_id])
        assert not refused.supported
        result = game.cast_from_hand(0, "Carry Away", target_permanent_ids=[star.permanent_id])
        assert result.supported, result
        _w1g2_settle(game)
        aura = next(p for p in game.controlled_by(0) if p.card.name == "Carry Away")
        assert aura.metadata.get("attached_to") is star
        assert game.controller_index_of(star) == 0
        assert _w1g2_equipped(star) is None
        assert (bears.effective_power, bears.effective_toughness) == (2, 2)
        assert "Vulshok Morningstar became unattached (Carry Away)" in game.log

        equip = game.activate_permanent_ability(
            0, "Vulshok Morningstar", permanent_index=game.battlefield_index_of(star),
            target_permanent_ids=[ogre.permanent_id],
        )
        assert equip.supported, equip
        _w1g2_settle(game)
        assert _w1g2_equipped(star) is ogre
        assert (ogre.effective_power, ogre.effective_toughness) == (4, 4)

        game.remove_from_battlefield(aura)
        _w1g2_settle(game)
        assert game.controller_index_of(star) == 1
        assert _w1g2_equipped(star) is ogre

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
