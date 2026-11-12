"""Fifth Dawn creatures (legendary ones too).

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


def _w1g4_table(set_pool, *, interactive=()):
    """Two seats on seat 0's first main phase, libraries to draw from."""
    island = set_pool("LEA")["Island"]
    game = _W1G4Game(players=[
        _W1G4PlayerState(name=f"P{seat}", library=[island] * 20)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    return game


def _w1g4_put(game, card, seat):
    """*card* onto *seat*'s battlefield through the entry seam, not sick."""
    permanent = _W1G4Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    _w1g4_settle(game)
    return permanent


def _w1g4_activate(game, seat, permanent, **targets):
    result = game.activate_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), **targets,
    )
    _w1g4_settle(game)
    return result


def test_w1g4_goblin_brawler_is_a_legal_equip_target_the_equipment_never_moves_onto(set_pool):
    """"This creature can't be equipped." Its 2004-12-01 ruling: "You can
    activate an equip ability that targets Goblin Brawler, but the Equipment
    will fail to move onto it" (CR 301.5b). So the activation is accepted and
    paid, the resolution leaves the Equipment where it was, and the same
    Equipment then equips another creature normally."""
    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    assert _w1g4_compile(fifth["Goblin Brawler"]).supported
    game = _w1g4_table(set_pool)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)

    result = _w1g4_activate(
        game, 0, splitter, target_permanent_ids=[brawler.permanent_id]
    )
    assert result.supported
    assert _w1g4_equipped(splitter) is None
    assert (brawler.effective_power, brawler.effective_toughness) == (2, 2)
    assert any("can't be equipped" in line for line in game.log)

    _w1g4_activate(game, 0, splitter, target_permanent_ids=[bears.permanent_id])
    assert _w1g4_equipped(splitter) is bears
    assert bears.effective_power == 4


def test_w1g4_the_ai_never_plans_an_equip_onto_goblin_brawler(set_pool):
    """The restriction is asked by ``equip_refusal``, the predicate the AI's
    equip planner asks too, so it never pays for an equip that cannot land:
    with the Brawler alone there is nothing to equip, and beside a Bears it
    picks the Bears."""
    from engine.ai_activation_targets import _choose_equip_target

    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_table(set_pool)
    brawler = _w1g4_put(game, fifth["Goblin Brawler"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    assert _choose_equip_target(game, 0, splitter) is None
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    chosen = _choose_equip_target(game, 0, splitter)
    assert game.players[0].battlefield[chosen] is bears
    assert brawler is not bears


def test_w1g4_auriok_windwalker_moves_its_controllers_equipment_between_their_creatures(set_pool):
    """"{T}: Attach target Equipment you control to target creature you
    control." Two roles, both narrowed to the activator: the picker offers only
    the activator's Equipment and creatures, an announcement naming either of
    the opponent's is refused before the {T} is paid (CR 602.2b), and the legal
    one moves the Equipment at instant speed."""
    from engine.targeting import derive_activation_spec

    fifth, mirrodin, alpha = set_pool("5DN"), set_pool("MRD"), set_pool("LEA")
    game = _w1g4_table(set_pool)
    walker = _w1g4_put(game, fifth["Auriok Windwalker"], 0)
    splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 0)
    bears = _w1g4_put(game, alpha["Grizzly Bears"], 0)
    their_splitter = _w1g4_put(game, mirrodin["Bonesplitter"], 1)
    their_bears = _w1g4_put(game, alpha["Grizzly Bears"], 1)

    ability = _w1g4_compile(walker.card).activated_abilities[0]
    spec = derive_activation_spec(ability)
    assert [(role["role"], role.get("own_only")) for role in spec["roles"]] == [
        ("equipment", True), ("creature", True),
    ]

    for equipment, creature in (
        (their_splitter, bears), (splitter, their_bears),
    ):
        refused = _w1g4_activate(
            game, 0, walker,
            target_permanent_ids=[equipment.permanent_id, creature.permanent_id],
        )
        assert not refused.supported
        assert not walker.tapped

    result = _w1g4_activate(
        game, 0, walker,
        target_permanent_ids=[splitter.permanent_id, bears.permanent_id],
    )
    assert result.supported, result.details
    assert walker.tapped
    assert _w1g4_equipped(splitter) is bears
    assert bears.effective_power == 4
    assert _w1g4_equipped(their_splitter) is None

# ==== end w1g4 ======================================================
