"""Censuses for the delayed abilities a step announces from a mark (CR 603.7)
and for who makes a delayed sacrifice (CR 701.21a).

1. **Every mark a step reads is announced as a stack object.** The end step
   and the end of combat step carried the marks out inline, before anybody had
   priority. Each mark the two steps act on is written through its one writer
   (``destruction_events.mark_delayed_destruction``) by seat 1, the step
   begins, and the census asks for a ``carry_out_delayed_mark`` object on the
   stack under seat 1 with the permanent still on the battlefield. Backwards:
   on 59f133e63 every row is a permanent already gone and an empty stack.
   The cleanup step's row (Mirage's flash-Aura sacrifice, kg5/cleanup) is read
   where CR 514.3a gives the active player priority; on e245e624c a sweep
   sacrificed the permanent as the step began and nobody was offered
   priority.

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

3. **Each creation is its own delayed ability** (kg5/cleanup). A mark is a
   kind of delayed ability, and a permanent can be named by several: "if you
   activate Dragon Whelp's ability five times, for example, two different
   delayed triggered abilities will trigger at the beginning of the next end
   step" (its ruling, 2022-09-09). Every mark is written twice on one
   permanent by two resolutions and its step begins; the census asks for two
   objects. Backwards: on e245e624c every row is one object — the mark was a
   flag with one cause beside it, and the second creation overwrote the
   first. The Whelp and two Thicket Basilisks against one regeneration shield
   are the boards.
"""

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine import delayed_triggers
from engine.cast_timing import CAST_AT_INSTANT_SPEED
from engine.destruction_events import mark_delayed_destruction
from engine.faces import compilation_units
from engine.legality import _iter_instruction_tree
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.turn_state import DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY, seats_next_turn_window

from tests.helpers import declare_attack, drive_combat, settle

#: Read off the module rather than imported, so the census runs - and fails
#: row by row - on a tree from before the kind existed.
CARRY_OUT_DELAYED_MARK = getattr(
    delayed_triggers, "CARRY_OUT_DELAYED_MARK", "carry_out_delayed_mark"
)


#: Every mark the three steps act on, with the step that announces it.
_MARKS = (
    ("destroy_at_end_of_combat", "end of combat"),
    ("destroy_at_next_end_step", "end step"),
    ("destroy_if_did_not_attack_eot", "end step"),
    (DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY, "end step"),
    ("destroy_if_attacked_eot", "end step"),
    ("sacrifice_at_next_end_step", "end step"),
    ("bounce_at_next_end_step", "end step"),
    # "…the controller of the permanent it becomes sacrifices it at the
    # beginning of the next cleanup step" (Mirage's flash Auras; kg5/cleanup).
    # On e245e624c a sweep sacrificed it as the step began: no object, and
    # nobody had priority.
    (CAST_AT_INSTANT_SPEED, "cleanup"),
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


def _announced(game) -> list:
    return [
        item for item in game.stack
        if item.ability_instruction is not None
        and item.ability_instruction.kind == CARRY_OUT_DELAYED_MARK
    ]


def _mark_and_begin_its_step(game, bears, mark, step, creations=1):
    """*mark* written on *bears* by *creations* resolutions of seat 1's, then
    the step it names begun: the delayed-mark objects it announced, and
    whether *bears* was still on the battlefield when they were.

    The cleanup step settles what it puts on the stack before it returns
    (nobody at this table holds priority through it), so that step is read
    where CR 514.3a gives the active player priority — the first time the
    table's ``priority_driver`` is asked, with the objects on the stack."""
    if mark == DESTROY_IF_DID_NOT_ATTACK_ON_SEAT_TURN_KEY:
        # "…at the beginning of **that turn's** end step" names the turn
        # being taken.
        game.seat_turn_counts[0] = 1
        value = {"seat": 0, "seat_turn": 1}
        assert seats_next_turn_window(game, 0)["seat_turn"] == 2
    else:
        value = True
    for _ in range(creations):
        game.resolving_seats.append(1)
        try:
            mark_delayed_destruction(game, bears, mark, value)
        finally:
            game.resolving_seats.pop()

    if step == "end of combat":
        game._set_phase_and_step("combat", "end_of_combat")
        with game.putting_triggers_on_stack():
            game._fire_end_of_combat_triggers()
    elif step == "cleanup":
        offered = []

        def first_offer(table, seat):
            if not offered:
                offered.append((_announced(table), table.is_on_battlefield(bears)))
            return False

        game.priority_driver = first_offer
        game.resolve_cleanup_step(0)
        return offered[0] if offered else ([], game.is_on_battlefield(bears))
    else:
        game.resolve_end_step(0)
    return _announced(game), game.is_on_battlefield(bears)


@pytest.mark.parametrize("mark,step", _MARKS, ids=[mark for mark, _ in _MARKS])
def test_every_mark_is_announced_as_a_stack_object(pool, mark, step):
    game, bears = _game(pool)
    announced, present = _mark_and_begin_its_step(game, bears, mark, step)

    assert present, f"{mark}: carried out before anyone had priority"
    assert [(item.caster_index, item.ability_instruction.payload["mark"])
            for item in announced] == [(1, mark)], game.log[-6:]
    assert mark not in bears.metadata, "CR 603.7b: the mark is spent as it triggers"


@pytest.mark.parametrize("mark,step", _MARKS, ids=[mark for mark, _ in _MARKS])
def test_two_creations_of_one_mark_are_two_delayed_abilities(pool, mark, step):
    """CR 603.7: each resolution that creates a delayed ability creates one —
    two writes of one mark are two objects on the stack, each naming the
    permanent, and the announcement spends the mark and its record."""
    game, bears = _game(pool)
    announced, _present = _mark_and_begin_its_step(game, bears, mark, step, creations=2)

    assert [
        (item.caster_index, item.ability_instruction.payload["mark"],
         tuple(item.trigger_context[delayed_triggers.DELAYED_MARK_PERMANENT_IDS]))
        for item in announced
    ] == [(1, mark, (bears.permanent_id,))] * 2, game.log[-6:]
    assert not any(key.startswith(mark) for key in bears.metadata), bears.metadata


def test_a_creation_never_rides_on_a_swept_mark(pool):
    """The cleanup step sweeps "this turn"'s marks with the turn
    (``_EOT_METADATA_KEYS``) without announcing them when the end step never
    came; a later creation is then the only one."""
    game, bears = _game(pool)
    game.resolving_seats.append(1)
    try:
        mark_delayed_destruction(game, bears, "destroy_if_attacked_eot")
        bears.metadata.pop("destroy_if_attacked_eot")   # the cleanup's sweep
        mark_delayed_destruction(game, bears, "destroy_if_attacked_eot")
    finally:
        game.resolving_seats.pop()
    game.resolve_end_step(0)
    assert len(_announced(game)) == 1, game.log[-6:]


def _whelp_table(pool, activations):
    island = pool["Island"]
    game = Game(players=[
        PlayerState("P1", library=[island] * 10),
        PlayerState("P2", library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    whelp = Permanent(card=pool["Dragon Whelp"])
    game._put_permanent_onto_battlefield(0, whelp, None)
    for _ in range(activations):
        result = game.activate_permanent_ability(
            0, "Dragon Whelp",
            source_permanent_index=game.players[0].battlefield.index(whelp),
        )
        assert result.supported, result.details
        settle(game)
    return game, whelp


@pytest.mark.parametrize("activations,abilities", [(3, 0), (4, 1), (5, 2), (6, 3)])
def test_dragon_whelp_makes_one_delayed_sacrifice_per_activation_after_the_third(
    pool, activations, abilities,
):
    """"If this ability has been activated four or more times this turn,
    sacrifice this creature at the beginning of the next end step." The fourth
    activation and each one after it create a delayed triggered ability (the
    card's rulings, 2022-09-09 and 2022-12-08), so the end step announces one
    object per activation past the third — and the second finds nothing."""
    game, whelp = _whelp_table(pool, activations)
    assert whelp.effective_power == 2 + activations

    game.resolve_end_step(0)
    assert [(item.caster_index, item.card.name) for item in _announced(game)] == (
        [(0, "Dragon Whelp")] * abilities
    ), game.log[-8:]
    settle(game)

    assert game.is_on_battlefield(whelp) is (abilities == 0)
    assert sum("sacrificed Dragon Whelp at end step" in line for line in game.log) == (
        1 if abilities else 0
    )
    assert sum(
        "Dragon Whelp: nothing to sacrifice at end step" in line for line in game.log
    ) == max(0, abilities - 1)


def test_two_basilisks_destroy_twice_and_one_regeneration_answers_one(pool):
    """Two Thicket Basilisks block Drudge Skeletons: each block trigger creates
    its own "destroy that creature at end of combat" (CR 603.7), so the
    Skeletons are destroyed twice at end of combat. Fog keeps the combat damage
    off, and one regeneration shield (CR 701.19) answers only the first
    destruction. On e245e624c the second creation overwrote the first, one
    destruction was announced and the shield saved the creature."""
    island = pool["Island"]
    skeletons = Permanent(card=pool["Drudge Skeletons"])
    basilisks = [Permanent(card=pool["Thicket Basilisk"]) for _ in range(2)]
    game = Game(players=[
        PlayerState("P1", battlefield=[skeletons], hand=[pool["Fog"]],
                    library=[island] * 10),
        PlayerState("P2", battlefield=basilisks, library=[island] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.start_turn(0)
    declare_attack(game, 0, blocks={0: 0, 1: 0})
    settle(game)
    assert game.cast_from_hand(0, "Fog").supported
    settle(game)
    assert game.activate_permanent_ability(
        0, "Drudge Skeletons",
        source_permanent_index=game.players[0].battlefield.index(skeletons),
    ).supported
    settle(game)
    assert skeletons.regeneration_shield == 1
    drive_combat(game, through="declare_blockers")
    assert game.resolve_combat_damage(0)[0]
    drive_combat(game)

    assert not game.is_on_battlefield(skeletons)
    assert "Drudge Skeletons regenerated" in game.log
    assert "Drudge Skeletons was destroyed at end of combat" in game.log
    assert game.log.index("Drudge Skeletons regenerated") < game.log.index(
        "Drudge Skeletons was destroyed at end of combat"
    )


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
