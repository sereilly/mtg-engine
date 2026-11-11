"""Darksteel creatures (legendary ones too).

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
# Leonin Shikari's instant-speed equip, and the drive list's creatures
# (Auriok Glaivemaster, Steelshaper Apprentice, Slobad, Pteron Ghost).

from engine import Game as _W1G2Game, PlayerState as _W1G2PlayerState
from engine.equipment import equipped_creature as _w1g2_equipped
from engine.models import Permanent as _W1G2Permanent
from tests.helpers import declare_attack as _w1g2_declare_attack
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


def _w1g2_activate(game, seat, permanent, **kwargs):
    return game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **kwargs,
    )


def test_w1g2_leonin_shikari_equips_at_instant_speed(set_pool):
    """"You may activate equip abilities any time you could cast an instant."
    CR 304.5: with priority — here in the declare blockers step, onto an
    attacker (the 2004-12-01 ruling's own example). Without the Shikari the
    same activation is refused (CR 702.6a's "Activate only as a sorcery"); an
    opponent's Shikari is not "you" (CR 109.5); and a sorcery-speed ability
    that is not an equip ability stays sorcery-speed."""
    dst, mrd, lea = set_pool("DST"), set_pool("MRD"), set_pool("LEA")

    game = _w1g2_table(set_pool)
    _w1g2_put(game, dst["Leonin Shikari"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    basket = _w1g2_put(game, set_pool("6ED")["Snake Basket"], 0)
    _w1g2_declare_attack(game, 0)
    assert game.has_priority(0)
    result = _w1g2_activate(game, 0, star, target_permanent_ids=[bears.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_equipped(star) is bears
    assert bears.effective_power == 4
    refused = _w1g2_activate(game, 0, basket, x_value=1)
    assert not refused.supported
    assert "sorcery" in str(refused).lower()

    # The same table with the Shikari on the other side.
    game = _w1g2_table(set_pool)
    _w1g2_put(game, dst["Leonin Shikari"], 1)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    _w1g2_declare_attack(game, 0)
    refused = _w1g2_activate(game, 0, star, target_permanent_ids=[bears.permanent_id])
    assert not refused.supported
    assert "sorcery" in str(refused).lower()
    assert _w1g2_equipped(star) is None


def _w1g2_equip_it(game, seat, equipment, creature):
    result = _w1g2_activate(game, seat, equipment, target_permanent_ids=[creature.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert _w1g2_equipped(equipment) is creature


def test_w1g2_auriok_glaivemaster_only_while_equipped(set_pool):
    """"As long as this creature is equipped, it gets +1/+1 and has first
    strike." 1/1 bare; with a Morningstar 4/4 (its +2/+2 and its own +1/+1)
    and first strike; moved off, 1/1 again."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    glaive = _w1g2_put(game, dst["Auriok Glaivemaster"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    assert (glaive.effective_power, glaive.effective_toughness) == (1, 1)
    assert not glaive.has_keyword("first strike")
    _w1g2_equip_it(game, 0, star, glaive)
    assert (glaive.effective_power, glaive.effective_toughness) == (4, 4)
    assert glaive.has_keyword("first strike")
    _w1g2_equip_it(game, 0, star, bears)
    assert (glaive.effective_power, glaive.effective_toughness) == (1, 1)
    assert not glaive.has_keyword("first strike")


def test_w1g2_steelshaper_apprentice_finds_an_equipment(set_pool):
    """"{W}, {T}, Return this creature to its owner's hand: Search your library
    for an Equipment card, reveal that card, put it into your hand, then
    shuffle." The cost returns it; the search takes the Equipment only."""
    dst, lea = set_pool("DST"), set_pool("LEA")
    game = _w1g2_table(set_pool)
    game.players[0].library = [lea["Forest"], dst["Vulshok Morningstar"], lea["Forest"]]
    apprentice = _w1g2_put(game, dst["Steelshaper Apprentice"], 0)
    result = _w1g2_activate(game, 0, apprentice)
    assert result.supported, result
    _w1g2_settle(game)
    names = [card.name for card in game.players[0].hand]
    assert "Steelshaper Apprentice" in names and "Vulshok Morningstar" in names
    assert [card.name for card in game.players[0].library] == ["Forest", "Forest"]


def test_w1g2_slobad_saves_an_artifact_and_pteron_ghost_regenerates_one(set_pool):
    """Slobad: "Sacrifice an artifact: Target artifact gains indestructible
    until end of turn." Pteron Ghost: "Sacrifice this creature: Regenerate
    target artifact." — a *noncreature* artifact included (CR 701.19a): the
    picker used to hold "target artifact" to artifact creatures."""
    dst, lea, mrd = set_pool("DST"), set_pool("LEA"), set_pool("MRD")
    game = _w1g2_table(set_pool)
    slobad = _w1g2_put(game, dst["Slobad, Goblin Tinkerer"], 0)
    fodder = _w1g2_put(game, mrd["Ornithopter"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    result = _w1g2_activate(
        game, 0, slobad, target_permanent_ids=[star.permanent_id],
        cost_permanent_ids=[fodder.permanent_id],
    )
    assert result.supported, result
    _w1g2_settle(game)
    assert fodder not in game.controlled_by(0)
    assert star.has_keyword("indestructible")

    game = _w1g2_table(set_pool)
    ghost = _w1g2_put(game, dst["Pteron Ghost"], 0)
    star = _w1g2_put(game, dst["Vulshok Morningstar"], 0)
    bears = _w1g2_put(game, lea["Grizzly Bears"], 0)
    refused = _w1g2_activate(game, 0, ghost, target_permanent_ids=[bears.permanent_id])
    assert not refused.supported and ghost in game.controlled_by(0)
    result = _w1g2_activate(game, 0, ghost, target_permanent_ids=[star.permanent_id])
    assert result.supported, result
    _w1g2_settle(game)
    assert ghost not in game.controlled_by(0)
    game.players[0].hand = [lea["Shatter"]]
    assert game.cast_from_hand(0, "Shatter", target_permanent_ids=[star.permanent_id]).supported
    _w1g2_settle(game)
    assert star in game.controlled_by(0) and star.tapped

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
