"""Darksteel creatures (legendary ones too) — the later groups' sections.

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


# ==== W1G6 ==========================================================
# W1G6's tests go between this line and the "end W1G6" line.

# ==== end W1G6 ======================================================


# ==== W1G7 ==========================================================
# W1G7's tests go between this line and the "end W1G7" line.

# ==== end W1G7 ======================================================


# ==== W1G8 ==========================================================
# W1G8's tests go between this line and the "end W1G8" line.
#
# Neurok Transmuter: CR 613 layer 4's removing half ("…and isn't an
# artifact", CR 205.1a) beside a layer-5 colour set, under one fronted
# duration. Every activation goes through the real activation entry point
# and every board is read after `settle`.

from engine import Game as _W1G8Game, PlayerState as _W1G8PlayerState
from engine.layer_bridge import displayed_type_line as _w1g8_type_line
from engine.models import Permanent as _W1G8Permanent
from engine.oracle import compile_card_oracle as _w1g8_compile
from engine.targeting import derive_activation_spec as _w1g8_activation_spec
from engine.type_changes import lost_types as _w1g8_lost_types
from tests.helpers import settle as _w1g8_settle


def _w1g8_table(set_pool):
    island = set_pool("LEA")["Island"]
    game = _W1G8Game(players=[
        _W1G8PlayerState(name=f"P{seat}", library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g8_put(game, card, seat=0):
    permanent = _W1G8Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    game._settle()
    return permanent


def _w1g8_transmute(game, target, ability_index=1, *, queue=False):
    """Activate one of the Transmuter's abilities at *target*; with *queue*,
    leave it on the stack (``queue_permanent_ability``) so a second can be
    activated in response."""
    activate = (
        game.queue_permanent_ability if queue else game.activate_permanent_ability
    )
    result = activate(
        0, "Neurok Transmuter", ability_index=ability_index,
        target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, (result, game.log[-4:])
    return result


def test_w1g8_neurok_transmuter_strips_the_artifact_type_until_end_of_turn(set_pool):
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    myr = _w1g8_put(game, set_pool("MRD")["Myr Enforcer"])
    assert myr.has_type("artifact") and game._effective_colors(myr) == set()

    _w1g8_transmute(game, myr)
    _w1g8_settle(game)

    # Blue, no longer an artifact, still a creature and still a Myr: the
    # artifact type goes and nothing else (the card's 2004-12-01 ruling).
    assert not myr.has_type("artifact")
    assert myr.is_creature and myr.has_type("myr")
    assert game._effective_colors(myr) == {"U"}
    assert _w1g8_type_line(myr) == "Creature — Myr"

    # CR 514.2: both halves end together at cleanup.
    game.resolve_cleanup_step(0)
    assert myr.has_type("artifact") and myr.is_creature
    assert game._effective_colors(myr) == set()
    assert not _w1g8_lost_types(myr)


def test_w1g8_neurok_transmuter_leaves_the_equipment_on(set_pool):
    """An Equipment on the creature is still attached: the creature is still a
    creature, and only the creature lost a type (CR 301.5)."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    myr = _w1g8_put(game, set_pool("MRD")["Myr Enforcer"])
    bone = _w1g8_put(game, set_pool("MRD")["Bonesplitter"])
    game.activate_permanent_ability(
        0, "Bonesplitter", target_permanent_ids=[myr.permanent_id],
    )
    _w1g8_settle(game)
    assert myr.effective_power == 6

    _w1g8_transmute(game, myr)
    _w1g8_settle(game)
    assert not myr.has_type("artifact")
    assert bone.metadata.get("attached_to") is myr
    assert myr.effective_power == 6


def test_w1g8_neurok_transmuter_under_march_leaves_no_types(set_pool):
    """The card's 2004-12-01 ruling: an artifact that is a creature only
    because of March of the Machines loses the artifact type, March no longer
    reaches it, and the permanent has no types whatsoever — and (CR 205.1a)
    no Equipment subtype either."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    _w1g8_put(game, set_pool("MRD")["March of the Machines"])
    bone = _w1g8_put(game, set_pool("MRD")["Bonesplitter"])
    _w1g8_settle(game)
    assert bone.is_creature and bone.has_type("equipment")

    _w1g8_transmute(game, bone)
    _w1g8_settle(game)

    assert game.is_on_battlefield(bone)
    assert _w1g8_type_line(bone) == ""
    assert not bone.is_creature
    assert not bone.has_type("artifact") and not bone.has_type("equipment")
    assert game._effective_colors(bone) == {"U"}

    game.resolve_cleanup_step(0)
    assert bone.is_creature and bone.has_type("equipment")


def test_w1g8_neurok_transmuter_later_effect_wins_and_retargets_are_rechecked(set_pool):
    """The first ability makes a Bears an artifact; the second, later, takes
    it away again (CR 613.7). A second activation answered in response leaves
    the first one's target illegal as it resolves (CR 608.2b), so it changes
    nothing more."""
    game = _w1g8_table(set_pool)
    _w1g8_put(game, set_pool("DST")["Neurok Transmuter"])
    bears = _w1g8_put(game, set_pool("LEA")["Grizzly Bears"], seat=1)

    _w1g8_transmute(game, bears, ability_index=0)
    _w1g8_settle(game)
    assert bears.has_type("artifact")

    # On the stack, aimed at an artifact creature, and a second in response.
    _w1g8_transmute(game, bears, queue=True)
    _w1g8_transmute(game, bears, queue=True)
    assert [item.card.name for item in game.stack] == ["Neurok Transmuter"] * 2
    _w1g8_settle(game)

    assert not bears.has_type("artifact") and bears.is_creature
    assert game._effective_colors(bears) == {"U"}
    # One removal recorded: the second resolution found no artifact creature.
    assert len(_w1g8_lost_types(bears)) == 1
    assert any("no valid target" in line or "fizzle" in line.lower()
               or "illegal" in line.lower() for line in game.log[-6:]), game.log[-6:]


def test_w1g8_neurok_transmuter_picker_offers_what_each_line_prints(set_pool):
    program = _w1g8_compile(set_pool("DST")["Neurok Transmuter"])
    assert program.supported
    first, second = program.activated_abilities
    assert _w1g8_activation_spec(first)["kind"] == "creature"
    assert _w1g8_activation_spec(second) is not None

# ==== end W1G8 ======================================================


# ==== W1G9 ==========================================================
# W1G9's tests go between this line and the "end W1G9" line.

# ==== end W1G9 ======================================================
