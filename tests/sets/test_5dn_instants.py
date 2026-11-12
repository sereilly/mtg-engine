"""Fifth Dawn instants.

Opened on `main` before the wave-1 fan-out with one marked section per
group. **A group writes only between its own markers and puts its imports
at the top of its own section**, never at the top of the file: a
self-contained section cannot lose an import to a merge, can be moved whole
when the file nears its size cap, and parallel branches editing disjoint
regions merge without a conflict. Every module-level helper, constant and
import alias in a section carries that group's `_w<wave>g<n>_` prefix — the
sections share one module namespace.

Cards come from `set_pool("5DN")` / `set_cards("5DN")` — never a new
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
from engine import Game as _W1G4Game, PlayerState as _W1G4PlayerState
from engine.equipment import equipped_creature as _w1g4_equipped
from engine.models import Permanent as _W1G4Permanent
from engine.oracle import compile_card_oracle as _w1g4_compile
from tests.helpers import settle as _w1g4_settle


def _w1g4_theft_table(set_pool):
    """Seat 0 holds Magnetic Theft on its first main phase."""
    island = set_pool("LEA")["Island"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(
            name="P0", library=[island] * 20,
            hand=[set_pool("5DN")["Magnetic Theft"]],
        ),
        _W1G4PlayerState(name="P1", library=[island] * 20),
    ])
    game.enforce_mana_costs = False
    game.start_turn(0)
    return game


def _w1g4_put(game, card, seat):
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g4_settle(game)
    return permanent


def _w1g4_cast_theft(game, equipment, creature):
    return game.cast_from_hand(
        0, "Magnetic Theft",
        target_permanent_ids=[equipment.permanent_id, creature.permanent_id],
    )


def test_w1g4_magnetic_theft_moves_an_equipment_onto_another_players_creature(set_pool):
    """"Attach target Equipment to target creature. (Control of the Equipment
    doesn't change.)" Its 2004-12-01 ruling: it "can cause an Equipment one
    player controls to be attached to a creature another player controls"
    (CR 301.5d). The picker asks for the Equipment, then the creature, and
    offers both players' creatures."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    spec = game.cast_target_spec(0, set_pool("5DN")["Magnetic Theft"])
    assert [role["role"] for role in spec["roles"]] == ["equipment", "creature"]
    (first,) = spec["valid_targets"]
    assert first["name"] == "Bonesplitter"
    assert {(entry["seat"], entry["name"]) for entry in first["next"]} == {
        (0, "Grizzly Bears"), (1, "Grizzly Bears"),
    }

    result = _w1g4_cast_theft(game, splitter, theirs)
    assert result.supported, result.details
    _w1g4_settle(game)

    assert _w1g4_equipped(splitter) is theirs
    assert theirs.effective_power == 4 and mine.effective_power == 2
    assert game.controller_index_of(splitter) == 0


def test_w1g4_a_stolen_equipment_stays_its_owners_to_equip_back(set_pool):
    """The other half of the same ruling: "The controller of the Equipment can
    pay the equip cost to move the Equipment to a creature they control (but
    only any time that player could cast a sorcery)." Magnetic Theft puts the
    opponent's Bonesplitter on the caster's creature; on its controller's own
    turn the equip ability brings it home."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 1)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    _w1g4_cast_theft(game, splitter, mine)
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is mine
    assert game.controller_index_of(splitter) == 1
    assert mine.effective_power == 4

    game.start_turn(1)
    result = game.activate_permanent_ability(
        1, splitter.card.name,
        permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[theirs.permanent_id],
    )
    assert result.supported, result.details
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is theirs
    assert mine.effective_power == 2


def test_w1g4_magnetic_theft_does_nothing_once_its_creature_is_gone(set_pool):
    """CR 608.2b in response: the creature leaves before Magnetic Theft
    resolves, and the Equipment stays exactly where it was rather than falling
    off or landing on something nobody chose."""
    mirrodin, alpha = set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    mine = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    theirs = _w1g4_put(game, alpha["Grizzly Bears"], 1)
    game.activate_permanent_ability(
        0, splitter.card.name, permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[mine.permanent_id],
    )
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is mine

    assert game.queue_from_hand(
        0, "Magnetic Theft",
        target_permanent_ids=[splitter.permanent_id, theirs.permanent_id],
    ).supported
    assert game.stack
    game.sacrifice_permanent(theirs)
    _w1g4_settle(game)

    assert not game.is_on_battlefield(theirs)
    assert _w1g4_equipped(splitter) is mine
    assert mine.effective_power == 4
    assert any("no longer legal" in line for line in game.log)


def test_w1g4_magnetic_theft_onto_goblin_brawler_leaves_the_equipment_in_place(set_pool):
    """Goblin Brawler is a legal target for "target creature" — it is not
    protected from anything — and the Equipment fails to move onto it
    (CR 301.5b, 701.3b): it stays on the creature it was equipping."""
    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_theft_table(set_pool)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 1)
    game.activate_permanent_ability(
        0, splitter.card.name, permanent_index=game.battlefield_index_of(splitter),
        target_permanent_ids=[bears.permanent_id],
    )
    _w1g4_settle(game)

    assert _w1g4_compile(fifth["Magnetic Theft"]).supported
    assert _w1g4_cast_theft(game, splitter, brawler).supported
    _w1g4_settle(game)
    assert _w1g4_equipped(splitter) is bears
    assert brawler.effective_power == 2
    assert any("can't be equipped" in line for line in game.log)

# ==== end w1g4 ======================================================


# ==== w1g5 ==========================================================
# w1g5's tests go between this line and the "end w1g5" line.

# ==== end w1g5 ======================================================


# ==== w1g6 ==========================================================
# w1g6's tests go between this line and the "end w1g6" line.

# ==== end w1g6 ======================================================


# ==== w1g7 ==========================================================
# w1g7's tests go between this line and the "end w1g7" line.

# ==== end w1g7 ======================================================
