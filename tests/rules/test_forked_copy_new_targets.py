"""CR 707.10c — "Some effects copy a spell … and state that its controller may
choose new targets for the copy. The player may leave any number of the
targets unchanged…"

Fork: "Copy target instant or sorcery spell, except that the copy is red. You
may choose new targets for the copy."

A person was offered the choice only through the cast's own second step: a
new *permanent* named beside the Fork. A client runs that step for a
permanent picker and cannot run it for a player at all, so a Forked Lightning
Bolt aimed at a face kept the original's target — no prompt was armed, and
nothing a seat could send re-aimed it.

Fork's handler was its own, older than the trigger's copy (Double Vision,
Mirari) and never taught what that one was: it arms the ``copy_spell_target``
prompt now, under the same condition, when the cast named no new target. And
both go through one builder of a copy (CR 707.10: "all decisions made for
it"), where Fork's had left a graveyard target and a second chosen mode
behind.

Census, both manifest roles: one card compiles to Fork's kind
(``copy_top_stack_spell``), two to the trigger's (``copy_triggering_spell``);
see ``test_every_spell_copier_...`` below.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import ChosenMode, OracleExecutionContext, StackItem
from engine.models import Permanent
from engine.color_changes import spell_color_change
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets

COPY_KINDS = ("copy_top_stack_spell", "copy_triggering_spell")


def _table(catalog_by_name, *, interactive: bool):
    me = PlayerState(name="P0", life=20, library=[catalog_by_name["Forest"]] * 5)
    you = PlayerState(name="P1", life=20, library=[catalog_by_name["Forest"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0, 1}
    bears = []
    for seat in (0, 1):
        bear = Permanent(card=catalog_by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(seat, bear, None)
        bears.append(bear)
    bolt = StackItem(
        card=catalog_by_name["Lightning Bolt"], caster_index=1,
        target_player_index=0, target_permanent_index=None, x_value=None,
    )
    game.stack.append(bolt)
    return game, me, you, bolt, bears


def _fork(game, me, catalog_by_name, **announced):
    me.hand = [catalog_by_name["Fork"]]
    engine_index = next(
        index for index, item in enumerate(game.stack)
        if item.card.name == "Lightning Bolt"
    )
    assert game.queue_from_hand(
        0, "Fork", target_stack_index=engine_index, **announced
    ).supported
    game.resolve_top_of_stack(pause_for_choices=bool(game.interactive_seats))
    copy = next(item for item in reversed(game.stack) if item.is_copy)
    return copy


def _aim(game, item) -> tuple:
    (target,) = chosen_targets(game, item)
    if target.kind == "player":
        return ("player", target.seat)
    return ("permanent", target.permanent_id)


@pytest.mark.cr("707.10c")
def test_707_10c_a_forked_spell_aimed_at_a_player_may_be_re_aimed(catalog_by_name):
    game, me, you, bolt, bears = _table(catalog_by_name, interactive=True)

    copy = _fork(game, me, catalog_by_name)

    # The copy has the original's target (CR 707.10) — and its controller is
    # asked, with the original's among the answers.
    assert _aim(game, copy) == ("player", 0)
    prompt = game.pending_choice_of("copy_spell_target", 0)
    assert prompt is not None
    offered = prompt.data["targets"]
    assert {"kind": "player", "seat": 0, "name": "P0"} in offered
    assert {"kind": "player", "seat": 1, "name": "P1"} in offered
    assert {t["permanent_id"] for t in offered if t["kind"] == "permanent"} == {
        bear.permanent_id for bear in bears
    }

    assert game.confirm_copy_spell_target(0, target_seat=1)
    assert _aim(game, copy) == ("player", 1)
    assert game.pending_choice_of("copy_spell_target", 0) is None
    # "…except that the copy is red" is untouched by any of it.
    assert tuple(spell_color_change(copy) or ()) == ("R",)


@pytest.mark.cr("707.10c")
def test_707_10c_leaving_the_target_unchanged_is_an_answer(catalog_by_name):
    """ "The player may leave any number of the targets unchanged." """
    game, me, _you, _bolt, _bears = _table(catalog_by_name, interactive=True)
    copy = _fork(game, me, catalog_by_name)

    assert game.confirm_copy_spell_target(0, target_seat=0)

    assert _aim(game, copy) == ("player", 0)
    assert game.pending_choice_of("copy_spell_target", 0) is None


@pytest.mark.cr("707.10c")
def test_707_10c_a_target_named_on_the_cast_is_the_answer_and_is_not_asked_twice(
    catalog_by_name,
):
    """The client's own second step: a new permanent named beside the Fork."""
    game, me, _you, _bolt, bears = _table(catalog_by_name, interactive=True)

    copy = _fork(
        game, me, catalog_by_name, target_player_index=1,
        target_permanent_index=game.players[1].battlefield.index(bears[1]),
    )

    (target,) = chosen_targets(game, copy)
    assert target.kind == "permanent"
    assert game.permanent_by_id(target.permanent_id) is bears[1]
    assert game.pending_choice_of("copy_spell_target", 0) is None


@pytest.mark.cr("707.10")
def test_707_10_a_seat_nobody_asks_keeps_the_originals_target(catalog_by_name):
    """Headless and AI: nothing queued, nothing logged, the copy as it was."""
    game, me, _you, _bolt, _bears = _table(catalog_by_name, interactive=False)
    log = len(game.log)

    copy = _fork(game, me, catalog_by_name)

    assert _aim(game, copy) == ("player", 0)
    assert not game.pending_choices
    assert not any("(copy) targets" in line for line in game.log[log:])


@pytest.mark.cr("707.10")
def test_707_10_a_forked_copy_carries_every_decision_made_for_the_original(
    catalog_by_name,
):
    """A card in a graveyard and the several modes of a "choose one or more"
    are decisions in channels of their own. Fork's copy left both behind."""
    game, me, _you, bolt, _bears = _table(catalog_by_name, interactive=False)
    bolt.target_graveyard_card = object()
    bolt.chosen_modes = (ChosenMode(index=0), ChosenMode(index=2))

    copy = _fork(game, me, catalog_by_name)

    assert copy.target_graveyard_card is bolt.target_graveyard_card
    assert copy.chosen_modes == bolt.chosen_modes


@pytest.mark.cr("707.10")
@pytest.mark.parametrize("spell, x_value, each", [
    # "…2 damage to each of up to three targets": every target takes it all.
    ("Shower of Coals", None, 2),
    # "…X damage divided evenly, rounded down, among any number of targets."
    ("Fireball", 4, 2),
])
def test_707_10_a_copy_resolves_at_every_target_the_original_named(
    catalog_by_name, spell, x_value, each
):
    """Carrying the decision is half of CR 707.10; the copy has to *resolve*
    with it. A spell with several targets announces them on a channel of its
    own, the copy had the list, and the copy's arm of the resolution did not
    read it - so the copy went wherever a spell with no target named goes.
    Found by a person Forking a Shower of Coals aimed at two creatures and
    watching the copy burn the opponent's face."""
    me = PlayerState(name="P0", life=20, library=[catalog_by_name["Forest"]] * 5)
    you = PlayerState(name="P1", life=20, library=[catalog_by_name["Forest"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    wurms = []
    for _ in range(2):
        wurm = Permanent(card=catalog_by_name["Scaled Wurm"])
        game._put_permanent_onto_battlefield(1, wurm, None)
        wurms.append(wurm)
    announced = {"divided_targets": [(1, 0), (1, 1)]}
    if x_value is not None:
        announced["x_value"] = x_value
    me.hand = [catalog_by_name[spell], catalog_by_name["Fork"]]
    assert game.queue_from_hand(0, spell, **announced).supported
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported

    game.resolve_top_of_stack()  # Fork: the copy goes on the stack
    copy = game.stack[-1]
    assert copy.is_copy and copy.card.name == spell
    game.resolve_top_of_stack()  # the copy

    assert [wurm.damage_marked for wurm in wurms] == [each, each]
    assert (me.life, you.life) == (20, 20)

    game.resolve_top_of_stack()  # the original
    assert [wurm.damage_marked for wurm in wurms] == [2 * each, 2 * each]
    assert (me.life, you.life) == (20, 20)


def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


@pytest.mark.cr("707.10c")
def test_every_spell_copier_asks_a_person_who_named_no_new_target(catalog_by_name):
    """The pool, both manifest roles: every program step that copies a spell
    on the stack and prints "you may choose new targets", run for a seat that
    is asked and one that is not."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    examined: dict[str, str] = {}
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [trigger.instruction for trigger in program.triggered_abilities]
        for root in roots:
            for step in _walk(root):
                if step.kind not in COPY_KINDS:
                    continue
                for interactive in (True, False):
                    game, me, you, bolt, _bears = _table(
                        catalog_by_name, interactive=interactive
                    )
                    source = None
                    if "instant" not in (unit.type_line or "").lower():
                        source = Permanent(card=unit)
                        game._put_permanent_onto_battlefield(0, source, None)
                    game._execute_oracle_instruction(step, OracleExecutionContext(
                        caster=me, target=you, card=unit, source_permanent=source,
                        stack_target=bolt,
                        trigger_context={"cast_item": bolt, "cast_card": bolt.card},
                    ))
                    copy = next(item for item in reversed(game.stack) if item.is_copy)
                    assert _aim(game, copy) == ("player", 0), unit.name
                    prompt = game.pending_choice_of("copy_spell_target", 0)
                    assert (prompt is not None) is interactive, (unit.name, interactive)
                examined[unit.name] = step.kind

    assert set(examined.values()) == set(COPY_KINDS), examined
    assert len(examined) >= 3, examined


@pytest.mark.cr("707.10c")
@pytest.mark.parametrize("bolt_caster", [0, 1])
@pytest.mark.parametrize("named_seat", [0, 1])
def test_707_10c_a_new_target_named_on_the_cast_is_the_permanent_that_was_named(
    catalog_by_name, bolt_caster, named_seat,
):
    """Whoever controls the forked spell. The named slot was counted into the
    battlefield of the *forked spell's controller* — the seat a resolution
    about a spell on the stack is given — so a Fork of one's own Bolt re-aimed
    at an opponent's creature hit one's own creature in that slot: wrong in
    the two seatings where the two differ. The cast stamps the id, and the id
    names the object and its battlefield both."""
    me = PlayerState(name="P0", life=20, library=[catalog_by_name["Forest"]] * 5)
    you = PlayerState(name="P1", life=20, library=[catalog_by_name["Forest"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    bears = []
    for seat in (0, 1):
        bear = Permanent(card=catalog_by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(seat, bear, None)
        bears.append(bear)
    game.players[bolt_caster].hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(
        bolt_caster, "Lightning Bolt", target_player_index=1 - bolt_caster,
    ).supported
    me.hand = list(me.hand) + [catalog_by_name["Fork"]]
    assert game.queue_from_hand(
        0, "Fork", target_stack_index=0, target_player_index=named_seat,
        target_permanent_index=game.players[named_seat].battlefield.index(
            bears[named_seat]
        ),
    ).supported

    game.resolve_top_of_stack()

    copy = next(item for item in reversed(game.stack) if item.is_copy)
    (target,) = chosen_targets(game, copy)
    assert target.kind == "permanent"
    assert game.permanent_by_id(target.permanent_id) is bears[named_seat]
