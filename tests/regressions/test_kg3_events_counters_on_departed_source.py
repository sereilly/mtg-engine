"""Counters put "on this creature" by an ability whose source has left the
battlefield land on nothing (CR 400.7).

A permanent that leaves the battlefield becomes a new object with no memory
of the old one, so the resolving ability's "this creature" names nothing.
Blood Hound, dealt lethal damage while its controller was dealt combat damage,
logged "Blood Hound gets 3 +1/+1 counters" from its graveyard as its "whenever
you're dealt damage" trigger resolved, the counters written onto the detached
object (SET_PLAYBOOK's Known-gaps entry). ``add_loyalty_counters`` and
``move_all_counters_to_self`` asked already; the five placements onto the
source did not.

The census is every registered handler that puts counters onto the ability's
own source (by its registered kind), each run with a source that has left —
no counters, and a line saying why rather than one claiming them. Validated
backwards: on 753c241a all five placed their counters on the departed object.
"""

from __future__ import annotations

import re

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.handlers.registry import EFFECT_HANDLERS
from engine.models import CardDefinition, Permanent
from engine.named_counters import counters_on
from engine.oracle import OracleInstruction, compile_card_oracle
from tests.helpers import resolve_stack

_UNITS = {}
for _card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
    _UNITS.setdefault(_card.name, _card)

#: A handler that puts counters onto the ability's own source, by its kind.
_ONTO_SELF = re.compile(r"^add_\w*counters?\w*(?:_to_self|_for_each_creature_died)$")
_KINDS_FLOOR = 5


def _instructions(value):
    if isinstance(value, OracleInstruction):
        yield value
        for sub in (value.payload or {}).values():
            yield from _instructions(sub)
    elif isinstance(value, (tuple, list)):
        for sub in value:
            yield from _instructions(sub)


def _example(kind: str):
    """A pool card and its first instruction of *kind*, or None."""
    for name, card in sorted(_UNITS.items()):
        program = compile_card_oracle(card)
        roots = list(program.instructions)
        roots += [a.instruction for a in program.activated_abilities if a.instruction]
        roots += [t.instruction for t in program.triggered_abilities if t.instruction]
        for found in _instructions(roots):
            if found.kind == kind:
                return card, found
    return None


def _creature(name: str, power: int, toughness: int) -> CardDefinition:
    return CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line="Creature — Test",
        oracle_text="", colors=(), color_identity=(), keywords=(), produced_mana=(),
        raw={"name": name, "type_line": "Creature — Test",
             "power": str(power), "toughness": str(toughness)},
    )


def _table() -> Game:
    game = Game(players=[
        PlayerState(f"P{seat}", library=[_UNITS["Island"]] * 10) for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    return game


def _put(game: Game, seat: int, card: CardDefinition) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _held(permanent: Permanent, word: str) -> dict:
    """Every counter a placement onto *permanent* could have written."""
    return {
        word: counters_on(permanent, word),
        "+1/+1": counters_on(permanent, "+1/+1"),
        "+1/+0": counters_on(permanent, "+1/+0"),
        "corpse": int(permanent.metadata.get("corpse_counters", 0) or 0),
    }


def test_no_placement_onto_a_departed_source():
    kinds = sorted(kind for kind in EFFECT_HANDLERS if _ONTO_SELF.match(kind))
    assert len(kinds) >= _KINDS_FLOOR, kinds
    driven, wrong = 0, []
    for kind in kinds:
        example = _example(kind)
        if example is None:
            continue
        card, instruction = example
        game = _table()
        source = _put(game, 0, card)
        resolve_stack(game)
        game.pending_choices.clear()
        word = str((instruction.payload or {}).get("counter", "+1/+1"))
        before = _held(source, word)
        game.remove_from_battlefield(source)
        mark = len(game.log)
        context = OracleExecutionContext(
            card=card, caster=game.players[0], target=game.players[0],
            source_permanent=source, x_value=2,
            trigger_context={"count": 2, "amount": 2, "damage_dealt": 2},
        )
        game._execute_oracle_instruction(instruction, context)
        driven += 1
        lines = game.log[mark:]
        if _held(source, word) != before or not any("CR 400.7" in line for line in lines):
            wrong.append((kind, card.name, before, _held(source, word), lines))
    assert driven >= _KINDS_FLOOR, driven
    assert wrong == [], (
        "a placement onto the ability's own source put counters on a "
        f"permanent that had left the battlefield: {wrong}"
    )


def test_blood_hound_dead_in_the_fight_gets_nothing():
    """The entry's board: Blood Hound blocks a 3/3 and dies while three 1/1s
    hit its controller. Its trigger, for 3, resolves after the state-based
    check has put it in the graveyard; answered yes, it places nothing and
    says so."""
    game = _table()
    game.interactive_seats = {1}
    hound = _put(game, 1, _UNITS["Blood Hound"])
    big = _put(game, 0, _creature("Big", 3, 3))
    others = [_put(game, 0, _creature(f"Small {i}", 1, 1)) for i in range(3)]
    game._sync_control()
    game._set_phase_and_step("combat", "declare_attackers")
    attackers = [big, *others]
    assert game.declare_attackers(
        0, [game.battlefield_index_of(a) for a in attackers], defending_player_index=1,
    )[0]
    game._set_phase_and_step("combat", "declare_blockers")
    assert game.declare_blockers(
        1, {game.battlefield_index_of(hound): [game.battlefield_index_of(big)]},
    )[0]
    game._set_phase_and_step("combat", "combat_damage")
    assert game.resolve_all_combat_damage(0)[0]
    assert not game.is_on_battlefield(hound)
    resolve_stack(game)
    answered = 0
    while game.pending_choice_of("optional_pay", 1) is not None:
        answered += 1
        assert game.resolve_pending_choice("optional_pay", 1, accept=True)
        resolve_stack(game)
    assert answered == 1
    assert counters_on(hound, "+1/+1") == 0
    assert not any(
        line.startswith("Blood Hound gets") for line in game.log
    ), game.log
    assert any(
        line.startswith("Blood Hound: this permanent has left the battlefield")
        for line in game.log
    ), game.log
