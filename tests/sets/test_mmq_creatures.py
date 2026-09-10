"""Mercadian Masques creatures.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("MMQ")` / `set_cards("MMQ")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G5: control changes off a damage event ---

from engine import Game, PlayerState
from engine.handlers._common import apply_damage_to_creature
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle

from tests.helpers import resolve_stack


def _g5c_creature(name: str, power: int = 2, toughness: int = 2):
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature - Test",
        oracle_text="", colors=(), color_identity=(), keywords=(),
        produced_mana=(),
        raw={"name": name, "type_line": "Creature - Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _g5c_board(*battlefields):
    seats = [
        PlayerState(name=f"G5CP{index}", battlefield=list(permanents))
        for index, permanents in enumerate(battlefields)
    ]
    board = Game(players=seats)
    board.enforce_mana_costs = False
    for seat in board.players:
        for permanent in seat.battlefield:
            permanent.metadata["summoning_sickness_turn"] = -99
    board.start_turn(0)
    board._close_current_priority_step()
    return board


# --- Crag Saurian ----------------------------------------------------------
# "Whenever **a source** deals damage to **this creature**, **that source's
# controller** gains control of this creature." Three pieces the engine had
# separately and had never been asked for together: an unnarrowed damager (CR
# 109.5's "source" covers a spell and an ability, which no `ObjectFilter` can
# name), the ability's own permanent as the *recipient*, and the seat the damage
# seam already derives for every event.


def test_crag_saurian_changes_hands_when_an_opponents_creature_hits_it(set_pool):
    saurian = Permanent(card=set_pool("MMQ")["Crag Saurian"])
    biter = Permanent(card=_g5c_creature("G5C Biter", 2, 2))
    board = _g5c_board([saurian], [biter])

    apply_damage_to_creature(board, saurian, 1, biter)
    resolve_stack(board)

    assert board.controller_index_of(saurian) == 1
    # CR 613.1's starting point is never rewritten, which is what an ended
    # contribution reverts to (CR 108.3 reads ownership off it).
    from engine.control import BASE_CONTROLLER

    assert saurian.metadata[BASE_CONTROLLER] == 0


def test_crag_saurian_stays_put_when_its_own_controllers_source_hits_it(set_pool):
    """"That source's controller" is a seat, and the handler declines a change
    to the seat that already has it rather than re-recording a contribution."""
    saurian = Permanent(card=set_pool("MMQ")["Crag Saurian"])
    mine = Permanent(card=_g5c_creature("G5C Mine", 2, 2))
    board = _g5c_board([saurian, mine], [])

    apply_damage_to_creature(board, saurian, 1, mine)
    resolve_stack(board)

    assert board.controller_index_of(saurian) == 0


def test_crag_saurian_follows_a_spells_controller_not_the_card(set_pool):
    """A spell's source is a `CardDefinition` — shared by every copy and
    controlled by nobody — so only the seat the damage seam derives
    (`damage_source_seat`, CR 109.5) can answer."""
    saurian = Permanent(card=set_pool("MMQ")["Crag Saurian"])
    board = _g5c_board([saurian], [])
    bolt = CardDefinition(
        name="G5C Bolt", mana_cost="{R}", cmc=1.0, type_line="Instant",
        oracle_text="G5C Bolt deals 2 damage to any target.", colors=("R",),
        color_identity=("R",), keywords=(), produced_mana=(),
        raw={"name": "G5C Bolt", "type_line": "Instant"},
    )
    board.players[1].hand = [bolt]

    board.cast_from_hand(
        1, "G5C Bolt", target_permanent_ids=[saurian.permanent_id]
    )
    resolve_stack(board)

    assert board.controller_index_of(saurian) == 1


def test_crag_saurian_is_not_moved_by_damage_to_something_else(set_pool):
    """"…to **this creature**" is an identity test, not a filter: a look-alike
    on the same battlefield is a different permanent (CR 400.7)."""
    saurian = Permanent(card=set_pool("MMQ")["Crag Saurian"])
    bystander = Permanent(card=_g5c_creature("G5C Bystander", 2, 2))
    biter = Permanent(card=_g5c_creature("G5C Biter", 2, 2))
    board = _g5c_board([saurian, bystander], [biter])

    apply_damage_to_creature(board, bystander, 1, biter)
    resolve_stack(board)

    assert board.controller_index_of(saurian) == 0


def test_crag_saurian_compiles_the_damage_event_from_the_damagers_end(set_pool):
    """The kind matters: `creature_dealt_damage`'s frozen seat is the *damaged*
    creature's controller — the Saurian's own — and reading that for "that
    source's controller" would leave the card doing nothing at all."""
    program = compile_card_oracle(set_pool("MMQ")["Crag Saurian"])
    trigger = program.triggered_abilities[0]

    assert program.supported
    assert trigger.condition.kind == "damage_dealt"
    assert trigger.condition.payload["damager_any"] == "a source"
    assert trigger.condition.payload["damaged_self"] == "this creature"
    assert trigger.instruction.payload["who"] == "event_subject_controller"
