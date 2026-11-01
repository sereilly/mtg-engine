"""Census: a triggered ability chooses its target from the board CR 603.3d
chooses from — once the event that set it off has finished and state-based
actions have been performed (CR 117.5, CR 704.3) — not from the board at its
fire site.

CR 603.3 puts a triggered ability on the stack "the next time a player would
receive priority"; CR 117.5 performs state-based actions first and *then* puts
triggered abilities on the stack; CR 603.3d chooses the targets as it goes
there. This engine pushed the object at its fire site and chose there, with the
event still under way. Two shapes, driven for every supported targeted trigger
of a creature in the shipped pool whose condition is a death or combat damage
to a player:

* **a sweep** — the trigger's source dies to Wrath of God beside a creature on
  each side; the sweep's deaths are one event, so the trigger chooses among
  what the sweep left (none of the creatures);
* **combat damage that kills** — the source attacks unblocked beside a Hill
  Giant whose blocker, a Grizzly Bears, takes lethal damage in the same
  combat damage step and dies to the state-based check that follows it.

For each, the target prompt a seat that is asked is shown is compared with the
picker's own list asked again once the step or the resolution is over — the
list CR 603.3d means. Where that list is empty the ability must have been
removed from the stack instead (CR 603.3d), and was.

Validated backwards: with ``TargetAnnouncementsMixin._trigger_choice_waits``
answering False (the tree before LGN W2G2) this names nineteen sweep drives on
ten cards — nine offering the creatures Wrath of God destroyed, the source
itself among them (Blazing Effigy, Bogardan Firefiend, Disease Carriers,
Festering Goblin, Hunting Moa and Marker Beetles with nothing else legal, so
CR 603.3d should have removed them; Goblin Arsonist and Pitchburn Devils
beside the players; Reliquary Monk beside the Ornithopter), and Sylvan
Hierophant, first on its battlefield, missing the Grizzly Bears the same
sweep put in its graveyard after it — and seven combat damage triggers
offering the dying blocker (Cephalid Constable, Riptide Entrancer, Skirk
Commando, Snapping Thragg, Somnophore, Spark Mage, Thalakos Dreamsower). With
Legions shipped, Scion of Darkness missing it from the damaged player's
graveyard is the eighth, and Celestial Gatekeeper's twin of Sylvan
Hierophant's is driven in ``tests/rules/test_lgn_w2g2_trigger_targets_after_
the_event.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.modal_triggers import modal_trigger_modes
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import names_a_target
from tests.helpers import declare_attack, resolve_stack

#: Floors, because a census that reaches nothing passes. On the day, over the
#: shipped pool before Legions: 18 sweep rows, each driven twice (source first
#: and last on its battlefield), 34 drives reached (Body Snatcher exiles itself
#: as it enters, so it never dies to the sweep), and 13 combat rows, 12 reached
#: (Chandra's Incinerator watches noncombat damage).
_MIN_SWEEP = 14
_MIN_COMBAT = 10

_SWEEP_CONDITIONS = frozenset({"dies", "enters_or_dies", "leaves_battlefield"})
_COMBAT_CONDITIONS = frozenset({"damage_dealt", "one_or_more_deal_combat_damage"})


@pytest.fixture(scope="module")
def _pool(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


def _rows(pool, conditions) -> list:
    """``(card, trigger)`` for every supported trigger of a creature whose
    line prints "target", whose target the trigger picker chooses, and whose
    condition is one of *conditions*."""
    probe = Game(players=[PlayerState("A"), PlayerState("B")])
    found = []
    for card in sorted(pool.values(), key=lambda c: c.name):
        if "Creature" not in (card.type_line or ""):
            continue
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trigger in program.triggered_abilities:
            step = trigger.instruction
            if (
                step is None or not trigger.supported
                or trigger.condition.kind not in conditions
                or modal_trigger_modes(step)
                or not names_a_target(trigger.source_line)
                or not probe._entry_trigger_chooses_a_target(step, trigger.source_line)
            ):
                continue
            found.append((card, trigger))
    return found


def _table(pool, *, hand=()) -> Game:
    game = Game(players=[
        PlayerState("A", library=[pool["Plains"]] * 10, hand=list(hand),
                    graveyard=[pool["Craw Wurm"]]),
        PlayerState("B", library=[pool["Plains"]] * 10, graveyard=[pool["Air Elemental"]]),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _settle_entries(game) -> None:
    """Resolve whatever the board's own entries put on the stack, unasked."""
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)


def _object(game, trigger):
    return next(
        (item for item in game.stack if item.ability_instruction is trigger.instruction), None
    )


def _offered(game, item) -> "set | None":
    prompt = next(
        (
            choice for choice in game.pending_choices_of("trigger_target")
            if choice.data["_trigger_item"] is item
        ),
        None,
    )
    if prompt is None:
        return None
    found = set()
    for entry in prompt.data["targets"]:
        if entry["kind"] in ("permanent", "graveyard"):
            found.add((entry["kind"], entry["name"], entry["seat"]))
        elif entry["kind"] == "player":
            found.add(("player", entry["seat"]))
    return found


def _rule_list(game, item) -> "set | None":
    """The picker's own list, asked of the board as it stands now."""
    offer = game._trigger_target_candidates(item)
    if offer is None:
        return None
    _spec, _chooser, candidates = offer
    found = set()
    for entry in candidates:
        if entry.get("kind") == "permanent":
            permanent = game.permanent_at(entry["seat"], entry["index"])
            if permanent is not None:
                found.add(("permanent", permanent.card.name, entry["seat"]))
        elif entry.get("kind") == "graveyard":
            card = game.players[entry["seat"]].graveyard[entry["index"]]
            found.add(("graveyard", card.name, entry["seat"]))
        elif entry.get("kind") == "player":
            found.add(("player", entry["seat"]))
    return found


def _judge(game, card, trigger, label, findings) -> bool:
    """Whether the row was reached (its object is on the stack, or CR 603.3d
    removed it). Appends what disagrees."""
    item = _object(game, trigger)
    if item is None:
        removed = any(
            card.name in line and "603.3d" in line for line in game.log[-12:]
        )
        return removed
    offered = _offered(game, item)
    rule = _rule_list(game, item)
    if offered is None and rule is None:
        return False
    if offered != rule:
        findings.append(f"{label}: offered {sorted(offered or ())}, the rule's list {sorted(rule or ())}")
    if not rule:
        findings.append(f"{label}: nothing legal, and the ability is still on the stack (603.3d)")
    return True


def test_a_trigger_set_off_by_a_sweep_chooses_from_what_the_sweep_left(_pool):
    examined = 0
    findings: list[str] = []
    rows = _rows(_pool, _SWEEP_CONDITIONS)
    for card, trigger in rows:
        for order in ("first", "last"):
            label = f"{card.name} [{order}]"
            game = _table(_pool, hand=[_pool["Wrath of God"]])
            # Something for an artifact, an enchantment and a land to name.
            for name in ("Ornithopter", "Mox Pearl", "Crusade"):
                _put(game, 1, _pool[name])
            if order == "first":
                _put(game, 0, card)
            _put(game, 0, _pool["Grizzly Bears"])
            _put(game, 1, _pool["Hill Giant"])
            if order == "last":
                _put(game, 0, card)
            _settle_entries(game)
            game.interactive_seats = {0}
            game.players[0].hand = [_pool["Wrath of God"]]
            assert game.queue_from_hand(0, "Wrath of God").supported, label
            game.resolve_top_of_stack()
            game.check_state_based_actions()
            examined += _judge(game, card, trigger, label, findings)

    assert examined >= 2 * _MIN_SWEEP, f"only {examined} sweep drives reached ({len(rows)} rows)"
    assert not findings, "\n".join(findings)


def test_a_combat_damage_trigger_chooses_after_the_state_based_check(_pool):
    examined = 0
    findings: list[str] = []
    for card, trigger in _rows(_pool, _COMBAT_CONDITIONS):
        line = trigger.source_line.lower()
        if not any(
            words in line for words in ("to a player", "to an opponent", "defending player")
        ):
            continue
        game = _table(_pool)
        _put(game, 0, card)
        giant = _put(game, 0, _pool["Hill Giant"])
        bears = _put(game, 1, _pool["Grizzly Bears"])
        for name in ("Ornithopter", "Crusade", "Plains"):
            _put(game, 1, _pool[name])
        _settle_entries(game)
        game.interactive_seats = {0}
        declare_attack(game, 0, blocks={
            game.battlefield_index_of(bears): game.battlefield_index_of(giant),
        })
        for _ in range(6):
            if _object(game, trigger) is not None or game.current_step in (
                "end_of_combat", "postcombat_main",
            ):
                break
            game.advance_combat_phase()
        assert not game.is_on_battlefield(bears), card.name
        examined += _judge(game, card, trigger, card.name, findings)

    assert examined >= _MIN_COMBAT, f"only {examined} combat drives reached"
    assert not findings, "\n".join(findings)
