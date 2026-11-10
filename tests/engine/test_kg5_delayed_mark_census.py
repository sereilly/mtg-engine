"""Censuses for the delayed abilities a step announces from a mark (CR 603.7)
and for who makes a delayed sacrifice (CR 701.21a).

1. **Every mark a step reads is announced as a stack object.** The end step
   and the end of combat step carried the marks out inline, before anybody had
   priority. Each mark the two steps act on is written through its one writer
   (``destruction_events.mark_delayed_destruction``) by seat 1, the step
   begins, and the census asks for a ``carry_out_delayed_mark`` object on the
   stack under seat 1 with the permanent still on the battlefield. Backwards:
   on 59f133e63 every row is a permanent already gone and an empty stack.

2. **"Sacrifice it" carries its actor.** Every compiled delayed sacrifice of
   a permanent other than the ability's own source — the end step's mark
   (``arm_self_action_at_next_end_step``) and the delayed abilities that name
   a bound permanent — is asked whether its card prints the sacrificer
   ("its controller sacrifices it", "that creature's controller sacrifices
   it"). The bare imperative must carry ``sacrificed_by: "you"`` (CR 701.21a:
   the ability's controller can sacrifice only what they control), and the
   spelled actor must not. Backwards: on 59f133e63 it names the nine cards
   kg5/delayed changed (Balduvian Dead, Tidal Wave, Dragon Whelp, Farrelite
   Priest, Initiates of the Ebon Hand, Krovikan Elementalist, Pyric
   Salamander, Soulshriek, Varchild's Crusader).
"""

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine import delayed_triggers
from engine.destruction_events import mark_delayed_destruction
from engine.faces import compilation_units
from engine.legality import _iter_instruction_tree
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.turn_state import DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY, seats_next_turn_window

#: Read off the module rather than imported, so the census runs - and fails
#: row by row - on a tree from before the kind existed.
CARRY_OUT_DELAYED_MARK = getattr(
    delayed_triggers, "CARRY_OUT_DELAYED_MARK", "carry_out_delayed_mark"
)


#: Every mark the two steps act on, with the step that announces it.
_MARKS = (
    ("destroy_at_end_of_combat", "end of combat"),
    ("destroy_at_next_end_step", "end step"),
    ("destroy_if_did_not_attack_eot", "end step"),
    (DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY, "end step"),
    ("destroy_if_attacked_eot", "end step"),
    ("sacrifice_at_next_end_step", "end step"),
    ("bounce_at_next_end_step", "end step"),
)


def _game(pool) -> tuple[Game, Permanent]:
    island = pool["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 10),
        PlayerState("P2", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    bears = Permanent(card=pool["Grizzly Bears"])
    game._put_permanent_onto_battlefield(0, bears, None)
    return game, bears


@pytest.fixture(scope="module")
def pool():
    return {card.name: card for card in load_catalog()}


@pytest.mark.parametrize("mark,step", _MARKS, ids=[mark for mark, _ in _MARKS])
def test_every_mark_is_announced_as_a_stack_object(pool, mark, step):
    game, bears = _game(pool)
    if mark == DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY:
        # "…at the beginning of **that turn's** end step" names the turn
        # being taken.
        game.seat_turn_counts[0] = 1
        value = {"seat": 0, "seat_turn": 1}
        assert seats_next_turn_window(game, 0)["seat_turn"] == 2
    else:
        value = True
    game.resolving_seats.append(1)
    try:
        mark_delayed_destruction(game, bears, mark, value)
    finally:
        game.resolving_seats.pop()

    if step == "end of combat":
        game._set_phase_and_step("combat", "end_of_combat")
        with game.putting_triggers_on_stack():
            game._fire_end_of_combat_triggers()
    else:
        game.resolve_end_step(0)

    assert game.is_on_battlefield(bears), f"{mark}: carried out before anyone had priority"
    announced = [
        item for item in game.stack
        if item.ability_instruction is not None
        and item.ability_instruction.kind == CARRY_OUT_DELAYED_MARK
    ]
    assert [(item.caster_index, item.ability_instruction.payload["mark"])
            for item in announced] == [(1, mark)], game.log[-6:]
    assert mark not in bears.metadata, "CR 603.7b: the mark is spent as it triggers"


_ACTOR = re.compile(r"\b(its|that creature's|their) controllers? sacrifices?\b", re.I)


def _roots(program):
    yield from program.instructions
    for ability in program.activated_abilities:
        if ability.instruction is not None:
            yield ability.instruction
    for trigger in program.triggered_abilities:
        if trigger.instruction is not None:
            yield trigger.instruction
    for mode in program.modes:
        if mode.instruction is not None:
            yield mode.instruction


def _delayed_sacrifices(program):
    """Every delayed sacrifice of a permanent other than the source, once."""
    seen = set()
    for root in _roots(program):
        for step in _iter_instruction_tree(root):
            if (
                step.kind == "arm_self_action_at_next_end_step"
                and step.payload.get("self_action") == "sacrifice"
            ):
                found = step
            elif step.kind == "create_delayed_trigger" and step.payload.get("instruction"):
                found = next(
                    (inner for inner in _iter_instruction_tree(step.payload["instruction"])
                     if inner.kind == "sacrifice_bound_permanent"),
                    None,
                )
                if found is None or not step.payload.get("event", "").startswith("next_"):
                    continue
            else:
                continue
            if id(found) not in seen:
                seen.add(id(found))
                yield found


def test_a_delayed_sacrifice_says_who_makes_it():
    examined = []
    wrong = []
    for unit in compilation_units(load_catalog()):
        program = compile_card_oracle(unit)
        for instruction in _delayed_sacrifices(program):
            examined.append(unit.name)
            spelled = bool(_ACTOR.search(unit.oracle_text or ""))
            says = instruction.payload.get("sacrificed_by")
            if spelled and says is not None:
                wrong.append(f"{unit.name}: prints its controller, carries {says!r}")
            if not spelled and says != "you":
                wrong.append(f"{unit.name}: the bare imperative, carries {says!r}")
    assert not wrong, wrong
    # Measured at kg5/delayed: 20 instructions over 20 cards.
    assert len(set(examined)) >= 18, sorted(set(examined))
