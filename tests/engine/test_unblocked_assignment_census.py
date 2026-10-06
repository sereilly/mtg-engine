"""Pool census: every card printing or granting "assign its combat damage as
though it weren't blocked" **asks**, with one blocker and with several.

The sentence is on four creatures (Lone Wolf, Thorn Elemental, Rhox, and
Pride of Lions in a measured set), granted by one planeswalker (Garruk, Savage
Herald) and imposed without its "may" by one instant (Outmaneuver). The defect
this census was written for could not be seen by any compiled-program
instrument, because no program moved: the cards compiled, were supported, and
worked — with the *default* answer, which was the only one a person at the
table was ever given when one creature blocked, and the one they could not
give when two did.

So the population is derived twice and the two derivations are held equal:
from the **printed text** (a regular expression over every card in both
manifest roles) and from the **compiled program** (the instruction kinds the
damage step reads). A card printing the sentence under a kind this file does
not know fails the comparison instead of escaping the sweep, and the sweep
itself runs each card through the engine's own combat steps under an
interactive seat.

Each test carries a floor on how much it examined. A sweep that reaches
nothing passes, and this one is about a population of six.

Measured backwards on the tree before the fix: the "asked" half below read
``{one blocker: 0 of 4, two blockers: 4 of 4}`` — the two-blocker stop being
the ordinary multi-block division, which then demanded all the power among
the blockers.
"""

from __future__ import annotations

import re

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import may_assign_as_unblocked
from engine.game_types import OracleExecutionContext
from engine.handlers.registry import EFFECT_HANDLERS
from engine.models import Permanent
from engine.oracle import compiled_units

from tests.helpers import _mk_creature_card

#: The printed static: the offer itself, read off the creature.
OFFER_KIND = "may_assign_as_unblocked"
#: Effects that hand the offer to creatures for a while.
GRANT_KINDS = frozenset({"grant_team_assign_unblocked_until_eot"})
#: The same rewrite with no "may" — a restriction, never a question.
MUST_KINDS = frozenset({"assign_as_unblocked_until_eot"})

#: The sentence, in both grammatical numbers and with or without "this turn".
SENTENCE = re.compile(
    r"assigns? (?:its|their) combat damage (?:this turn )?"
    r"as though (?:it|they) weren't blocked"
)


def _walk(value):
    """Every instruction reachable from a compiled program, wrappers opened."""
    kind = getattr(value, "kind", None)
    payload = getattr(value, "payload", None)
    if isinstance(kind, str) and isinstance(payload, dict):
        yield value
        yield from _walk(payload)
        return
    if isinstance(value, dict):
        for inner in value.values():
            yield from _walk(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            yield from _walk(inner)
    else:
        for attribute in ("instructions", "activated_abilities",
                          "triggered_abilities", "instruction"):
            inner = getattr(value, attribute, None)
            if inner is not None and not callable(inner):
                yield from _walk(inner)


@pytest.fixture(scope="module")
def whole_pool():
    """Every card in both manifest roles, one per name. A measured set is in:
    the sentence does not become somebody else's problem while its set waits
    to be promoted (Pride of Lions is in exactly that position)."""
    by_name = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            by_name.setdefault(card.name, card)
    return by_name


@pytest.fixture(scope="module")
def units(whole_pool):
    """The pool as the ``(card, program)`` pairs a census over compiled text
    reads — a multi-face card as its faces, because the whole card's own text
    box is empty and its own program holds no instruction
    (``tests/engine/test_face_blind_guards.py``)."""
    return compiled_units(whole_pool.values())


@pytest.fixture(scope="module")
def census(units):
    """``(printed, granting, mandatory, grant_instructions)`` by card name."""
    printed, granting, mandatory = {}, {}, {}
    grant_instructions = {}
    for card, program in units:
        if not program.supported:
            continue
        instructions = list(_walk(program))
        kinds = {instruction.kind for instruction in instructions}
        if OFFER_KIND in kinds:
            printed[card.name] = card
        if kinds & GRANT_KINDS:
            granting[card.name] = card
            grant_instructions[card.name] = next(
                i for i in instructions if i.kind in GRANT_KINDS
            )
        if kinds & MUST_KINDS:
            mandatory[card.name] = card
    return printed, granting, mandatory, grant_instructions


def _wall(name: str):
    return _mk_creature_card(name, 0, 99)


def _combat(attacker_card, blocker_count: int, *, before_combat=None,
            interactive=(0,)):
    """*attacker_card* attacking for seat 0 — **interactive** unless told
    otherwise — into *blocker_count* vanilla walls, through the engine's own
    steps, stopping once combat damage has been entered."""
    me = PlayerState(name="Me")
    opp = PlayerState(name="Opp")
    game = Game(players=[me, opp])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    me.life = opp.life = 100
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    walls = []
    for number in range(blocker_count):
        wall = Permanent(card=_wall(f"Census Wall {number}"))
        game._put_permanent_onto_battlefield(1, wall, None)
        walls.append(wall)
    game.active_player_index = 0
    if before_combat is not None:
        before_combat(game)
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, (attacker_card.name, why)
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {slot: 0 for slot in range(blocker_count)})
    assert ok, (attacker_card.name, why)
    game.advance_combat_phase()
    return game, attacker, walls


def _was_asked(game, walls) -> bool:
    """The observable half, with no name from this round in it: the step is
    waiting, and not a point of damage has gone anywhere."""
    return (
        game.current_step == "combat_damage"
        and not game.combat_damage_resolved
        and game.players[1].life == 100
        and all(wall.damage_marked == 0 for wall in walls)
    )


def _both_answers(make_combat, label: str) -> None:
    """Drive the offer taken, the offer declined, and some-of-each."""
    game, attacker, walls = make_combat()
    power = attacker.effective_power
    assert power > 0, label
    ok, why = game.resolve_combat_damage(
        0, attacker_damage={}, as_though_unblocked=[attacker.permanent_id]
    )
    assert ok, (label, why)
    assert game.players[1].life == 100 - power, label
    assert all(wall.damage_marked == 0 for wall in walls), label

    game, attacker, walls = make_combat()
    division = {slot: 0 for slot in range(len(walls))}
    division[len(walls) - 1] = power
    ok, why = game.resolve_combat_damage(0, attacker_damage={0: division})
    assert ok, (label, why)
    assert game.players[1].life == 100, label
    assert [wall.damage_marked for wall in walls] == list(division.values()), label

    game, attacker, walls = make_combat()
    ok, why = game.resolve_combat_damage(
        0, attacker_damage={0: {0: 1}},
        as_though_unblocked=[attacker.permanent_id],
    )
    assert not ok, label
    assert _was_asked(game, walls), (label, "a refusal must deal nothing")


# ---------------------------------------------------------------------------
# The population
# ---------------------------------------------------------------------------


def test_the_text_and_the_program_agree_on_who_prints_the_sentence(units, census):
    """Two derivations of one population. Equal, or a card printing the
    sentence is being read by something this census cannot see."""
    printed, granting, mandatory, _ = census
    by_text = {
        unit.name for unit, _program in units
        if SENTENCE.search((unit.oracle_text or "").lower())
    }
    by_program = set(printed) | set(granting) | set(mandatory)

    assert len(units) >= 4500, "the pool was not loaded"
    assert by_text == by_program
    # Floors, on the shipped names so a measured set's promotion or removal
    # cannot move them: three creatures, one granter, one restriction.
    assert {"Lone Wolf", "Thorn Elemental", "Rhox"} <= set(printed)
    assert "Garruk, Savage Herald" in granting
    assert "Outmaneuver" in mandatory
    assert not (set(printed) & set(mandatory)), "an offer is not a restriction"


def test_no_other_card_carries_the_offer(units, census):
    """The other direction, and the promise to every path beside this one:
    exactly the census's creatures answer ``may_assign_as_unblocked``, so no
    ordinary attacker — a trampler, a bander, a plain multi-blocked creature —
    can be stopped for this question."""
    printed, _granting, _mandatory, _ = census
    examined = 0
    offered = set()
    for unit, _program in units:
        if "creature" not in (unit.type_line or "").lower():
            continue
        examined += 1
        if may_assign_as_unblocked(Permanent(card=unit)):
            offered.add(unit.name)

    assert examined >= 2000, f"only {examined} creature cards were examined"
    assert offered == set(printed)


# ---------------------------------------------------------------------------
# Every card that prints it asks
# ---------------------------------------------------------------------------


def test_each_printed_card_asks_with_one_blocker_and_with_several(census):
    """The census proper. Each creature printing the sentence attacks for an
    interactive seat into one wall and into two; the game must be **waiting**
    at combat damage with nothing dealt, and must then take either answer.

    The "asked" table is collected in full before it is asserted, so a failure
    names every card and arrangement that was not asked rather than the first.
    """
    printed, _granting, _mandatory, _ = census
    asked = {}
    for name, card in sorted(printed.items()):
        for blockers in (1, 2):
            game, _attacker, walls = _combat(card, blockers)
            asked[(name, blockers)] = _was_asked(game, walls)

    assert len(asked) >= 6, f"only {len(asked)} card-and-arrangement pairs examined"
    not_asked = sorted(key for key, was in asked.items() if not was)
    assert not not_asked, (
        "an interactive attacker was not asked how these assign: "
        f"{not_asked} (of {len(asked)})"
    )

    answered = 0
    for name, card in sorted(printed.items()):
        for blockers in (1, 2):
            _both_answers(lambda: _combat(card, blockers), f"{name} x{blockers}")
            answered += 1
    assert answered == len(asked)


def test_each_granting_card_makes_its_creatures_ask(census):
    """The grant must be the same offer. Each granting effect is resolved by
    its own handler for seat 0, and a creature with no such line of its own is
    then asked exactly as a creature printing it is.

    (Garruk's ability is also activated for real, loyalty and all, in
    ``tests/rules/test_unblocked_assignment.py``; this is the sweep, which has
    to work for a granter printed as a spell or a trigger too.)"""
    _printed, granting, _mandatory, grant_instructions = census
    plain = _mk_creature_card("Census Bear", 3, 3)
    asked = {}

    def grant_from(card):
        def resolve(game):
            context = OracleExecutionContext(
                caster=game.players[0], target=game.players[1], card=card,
            )
            instruction = grant_instructions[card.name]
            ok, why = EFFECT_HANDLERS[instruction.kind](game, instruction, context)
            assert ok, (card.name, why)
        return resolve

    for name, card in sorted(granting.items()):
        for blockers in (1, 2):
            game, attacker, walls = _combat(plain, blockers, before_combat=grant_from(card))
            assert may_assign_as_unblocked(attacker), (name, "the grant granted nothing")
            asked[(name, blockers)] = _was_asked(game, walls)

    assert len(asked) >= 2, f"only {len(asked)} grant-and-arrangement pairs examined"
    not_asked = sorted(key for key, was in asked.items() if not was)
    assert not not_asked, f"a granted offer was not asked: {not_asked} (of {len(asked)})"

    for name, card in sorted(granting.items()):
        for blockers in (1, 2):
            _both_answers(
                lambda: _combat(plain, blockers, before_combat=grant_from(card)),
                f"{name} (granted) x{blockers}",
            )

    # The control: the same creature, the same blocker, no grant — resolved on
    # entering the step, unasked, onto its blocker. Without this the loop above
    # would pass on an engine that stopped for every attacker.
    game, _attacker, (wall,) = _combat(plain, 1)
    assert game.combat_damage_resolved
    assert wall.damage_marked == 3 and game.players[1].life == 100


def test_a_seat_nobody_sits_in_is_never_stopped(census):
    """The default every non-interactive seat keeps, over the same population:
    one blocker resolves on entering the step with the offer taken. (Two
    blockers stop, as they always have, for whoever drives the game to supply
    the division — and the default it supplies is again the offer.)"""
    printed, _granting, _mandatory, _ = census
    examined = 0
    for name, card in sorted(printed.items()):
        game, beast, (wall,) = _combat(card, 1, interactive=())

        assert game.combat_damage_resolved, name
        assert game.players[1].life == 100 - beast.effective_power, name
        assert wall.damage_marked == 0, name
        examined += 1

    assert examined >= 3
