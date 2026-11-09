"""A copy whose controller "may choose new targets" (CR 707.10c) is offered
them on every road, whoever controls it.

    707.10c Some effects copy a spell or ability and state that its
    controller may choose new targets for the copy. The player may leave any
    number of the targets unchanged, even if those targets would be illegal.

Two roads copy a spell on the stack and print the sentence:
``copy_triggering_spell`` (Double Vision, Mirari, the storm cards), which
offered every seat — a seat nobody asks taking the measured answer
(``ai_prompts.choose_copy_target``) — and ``copy_top_stack_spell`` (Fork,
Mischievous Quanar's turn-up trigger), which offered only a seat somebody
asks, and only for a permanent-or-player target. So a headless or AI Fork of
an opponent's Lightning Bolt aimed at the Fork's own Grizzly Bears copied the
Bolt onto those Bears, and a Forked Counterspell aimed at the copier's own
spell could not be re-aimed by anyone (kg4). Both roads now make one offer
(``spell_copies.offer_new_targets``).

The census runs every program step of the pool, both manifest roles, of a
kind that copies a spell on the stack, at a seat nobody asks — and every
copy kind the pool compiles is sorted, so a new one is not missed in
silence.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.damage_ledger import record_cast
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext, StackItem
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.stack_targets import chosen_targets
from tests.helpers import resolve_stack

#: The kinds that copy a spell on the stack and offer the copy's controller
#: new targets — the population of the census below.
CHOOSING_COPY_KINDS = frozenset({"copy_top_stack_spell", "copy_triggering_spell"})

#: Every other copy kind the pool compiles, and why the census leaves it out.
OTHER_COPY_KINDS = {
    # "they may copy this spell and may choose a new target" (the Chains):
    # the copy is of the resolving spell itself, offered under an optional
    # payment — the same offer, armed for every seat since SCG W2G3, held by
    # ``tests/engine/test_scg_p5_copy_announcement_census.py``.
    "copy_this_spell": "copies the resolving spell, under its own offer",
    # Radiate: each copy's target is assigned by the effect (CR 707.10d).
    "copy_spell_for_each_other_target": "the effect assigns each target",
    # Not copies of a spell on the stack.
    "copy_top_card_of_zone": "a permanent becomes a copy of a card",
    "become_copy_of_bound_permanent": "a permanent becomes a copy",
    "create_copy_token": "a token copy of a permanent",
    "put_exiled_card_onto_stack_as_copy": "a card put back as a copy, no new targets",
    # Isochron Scepter, Spellweaver Helix: a copy of an exiled card **cast**
    # (CR 707.12 follows 601.2a-h), so its targets are announced as the cast's
    # own (601.2c) — there are none to change — and a seat nobody asks
    # announces them through the rehearsed cast chooser
    # (``ai_policy.choose_copy_cast``). Driven below
    # (``test_a_copy_cast_from_exile_by_a_seat_nobody_asks_aims_away_from_its_side``).
    "cast_copy_of_exiled_card": "a copy cast: its caster announces targets (CR 707.12)",
}


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


def _copy_steps():
    """``(unit, step)`` for every program step of a copy kind, and the set of
    copy kinds seen."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    found = []
    kinds = set()
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [trigger.instruction for trigger in program.triggered_abilities]
        for root in roots:
            for step in _walk(root):
                if "copy" not in step.kind:
                    continue
                kinds.add(step.kind)
                if step.kind in CHOOSING_COPY_KINDS:
                    found.append((unit, step))
    return found, kinds


def _permanent(catalog_by_name, name):
    permanent = Permanent(card=catalog_by_name[name])
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _table(catalog_by_name, *, interactive=False, cast=True):
    """P0 holds Grizzly Bears; P1 a Hill Giant, and casts Lightning Bolt at
    P0's Bears — announced by id, as the web announces every target. Not
    *cast*, the Bolt is put on the stack as that announcement without a cast
    recorded, for a step that counts the turn's casts itself."""
    me = PlayerState(name="P0", library=[catalog_by_name["Mountain"]] * 5)
    you = PlayerState(name="P1", library=[catalog_by_name["Mountain"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    bears = _permanent(catalog_by_name, "Grizzly Bears")
    giant = _permanent(catalog_by_name, "Hill Giant")
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    if interactive:
        game.interactive_seats = {0}
    if not cast:
        game.stack.append(StackItem(
            card=catalog_by_name["Lightning Bolt"], caster_index=1,
            target_player_index=0, target_permanent_index=None, x_value=None,
            target_permanent_id=[bears.permanent_id],
        ))
        return game, me, you, bears, giant
    you.hand = [catalog_by_name["Lightning Bolt"]]
    assert game.queue_from_hand(
        1, "Lightning Bolt", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    return game, me, you, bears, giant


def _run_step(game, me, you, unit, step, copied):
    source = None
    if "instant" not in (unit.type_line or "").lower():
        source = Permanent(card=unit)
        game._put_permanent_onto_battlefield(0, source, None)
    if step.payload.get("for_each"):
        # Storm (CR 702.40a): the copied spell is recorded as the turn's
        # second cast, so the step makes exactly one copy.
        record_cast(game, StackItem(
            card=copied.card, caster_index=1, target_player_index=0,
            target_permanent_index=None, x_value=None,
        ))
        record_cast(game, copied)
    game._execute_oracle_instruction(step, OracleExecutionContext(
        caster=me, target=you, card=unit, source_permanent=source,
        stack_target=copied,
        trigger_context={"cast_item": copied, "cast_card": copied.card},
    ))
    return next(item for item in reversed(game.stack) if item.is_copy)


@pytest.mark.cr("707.10c")
def test_every_spell_copy_offered_new_targets_is_aimed_by_a_seat_nobody_asks(
    catalog_by_name,
):
    """The board the entry names: an opponent's burn spell aimed at the
    copier's own creature. Every copy, at a seat nobody asks, is aimed away
    from the copier's side; on the base Fork and Quanar's copies stayed on
    the copier's Bears."""
    steps, kinds = _copy_steps()
    unsorted = kinds - CHOOSING_COPY_KINDS - set(OTHER_COPY_KINDS)
    assert not unsorted, f"a copy kind the census does not sort: {sorted(unsorted)}"
    examined: dict[str, set] = {}
    for unit, step in steps:
        game, me, you, bears, _giant = _table(catalog_by_name, cast=False)
        bolt = game.stack[-1]
        copy = _run_step(game, me, you, unit, step, bolt)
        assert not game.pending_choices, unit.name
        (aim,) = chosen_targets(game, copy)
        if aim.kind == "player":
            assert aim.seat == 1, (unit.name, step.kind, "the copier's own face")
        else:
            held = game.permanent_by_id(aim.permanent_id)
            assert held is not bears, (unit.name, step.kind, "the copier's own Bears")
            assert game.controller_index_of(held) == 1, unit.name
        examined.setdefault(step.kind, set()).add(unit.name)
    # A floor on what was examined: both kinds, and both of the cards that
    # compile to Fork's (Fork, Mischievous Quanar).
    assert set(examined) == CHOOSING_COPY_KINDS, examined
    assert {"Fork", "Mischievous Quanar"} <= examined["copy_top_stack_spell"], examined
    assert len(examined["copy_triggering_spell"]) >= 3, examined


def _counterspell_table(catalog_by_name, *, interactive):
    """The stack, bottom first: P1's Hill Giant spell, P0's Giant Growth on
    P0's Bears, P1's Counterspell aimed at the Giant Growth."""
    me = PlayerState(name="P0", library=[catalog_by_name["Island"]] * 5)
    you = PlayerState(name="P1", library=[catalog_by_name["Island"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    bears = _permanent(catalog_by_name, "Grizzly Bears")
    game._put_permanent_onto_battlefield(0, bears, None)
    if interactive:
        game.interactive_seats = {0}
    you.hand = [catalog_by_name["Hill Giant"], catalog_by_name["Counterspell"]]
    me.hand = [catalog_by_name["Giant Growth"]]
    assert game.queue_from_hand(1, "Hill Giant").supported
    assert game.queue_from_hand(
        0, "Giant Growth", target_player_index=0,
        target_permanent_ids=[bears.permanent_id],
    ).supported
    assert game.queue_from_hand(1, "Counterspell", target_stack_index=1).supported
    giant_spell, growth, counterspell = game.stack
    assert counterspell.target_stack_item is growth
    return game, me, you, giant_spell, growth, counterspell


def _forks(catalog_by_name):
    steps, _kinds = _copy_steps()
    return [(unit, step) for unit, step in steps if step.kind == "copy_top_stack_spell"]


@pytest.mark.cr("707.10c", "115.7")
def test_a_copy_of_a_spell_aimed_at_a_spell_is_offered_a_new_one(catalog_by_name):
    """A Forked Counterspell aimed at the copier's own Giant Growth. A person
    is offered CR 115.7's change (``retarget_choice``, "keep" beside every
    spell the copy could have targeted); a seat nobody asks takes the
    measured answer, which is not its own Giant Growth. On the base nobody
    was offered anything, and the copy countered its own controller's spell."""
    forks = _forks(catalog_by_name)
    assert {unit.name for unit, _step in forks} >= {"Fork", "Mischievous Quanar"}
    for unit, step in forks:
        # A person.
        game, me, you, giant_spell, growth, counterspell = _counterspell_table(
            catalog_by_name, interactive=True,
        )
        copy = _run_step(game, me, you, unit, step, counterspell)
        owed = game.pending_choice_of("retarget_choice", 0)
        assert owed is not None, unit.name
        offered = [option.get("_stack_item") for option in owed.data["options"]]
        assert owed.data["options"][0]["kind"] == "keep"
        assert any(item is giant_spell for item in offered), unit.name
        pick = next(i for i, item in enumerate(offered) if item is giant_spell)
        assert game.confirm_retarget_choice(0, pick)
        assert copy.target_stack_item is giant_spell, unit.name
        assert counterspell.target_stack_item is growth

        # A seat nobody asks.
        game, me, you, giant_spell, growth, counterspell = _counterspell_table(
            catalog_by_name, interactive=False,
        )
        copy = _run_step(game, me, you, unit, step, counterspell)
        assert not game.pending_choices, unit.name
        assert copy.target_stack_item is not growth, unit.name
        assert any(copy.target_stack_item is item for item in game.stack), unit.name


@pytest.mark.cr("707.10c")
def test_a_headless_fork_of_a_bolt_at_its_own_creature_hits_the_opponent(catalog_by_name):
    """The real entry points: P1 Bolts P0's Bears, P0 casts Fork at the Bolt,
    the stack drains at a table nobody is asked at. The copy kills P1's Hill
    Giant; the Bolt still kills the Bears."""
    game, me, you, bears, giant = _table(catalog_by_name)
    me.hand = [catalog_by_name["Fork"]]
    log = len(game.log)
    assert game.queue_from_hand(0, "Fork", target_stack_index=0).supported

    resolve_stack(game)
    game.check_state_based_actions()

    assert not game.is_on_battlefield(giant)
    assert giant.card in you.graveyard
    assert not game.is_on_battlefield(bears)
    assert (me.life, you.life) == (20, 20)
    assert "Lightning Bolt (copy) targets Hill Giant" in game.log[log:]


@pytest.mark.cr("707.10c", "702.37e")
def test_a_headless_quanar_turned_up_aims_its_copy_at_the_opponent(set_pool, catalog_by_name):
    """Mischievous Quanar turned face up (the special action, CR 116.2b) in
    response to P1's Bolt at P0's Bears, at a table nobody is asked at: its
    trigger copies the Bolt, and the copy kills P1's Hill Giant rather than
    hitting the Bears a second time."""
    from engine.face_down import face_down_card
    from engine.special_actions import take_permanent_special_action

    game, me, you, bears, giant = _table(catalog_by_name)
    quanar = Permanent(card=face_down_card(set_pool("SCG")["Mischievous Quanar"]))
    quanar.metadata["summoning_sickness_turn"] = -99
    game._put_permanent_onto_battlefield(0, quanar, None)
    me.mana_pool.update({"U": 2, "C": 1})  # the morph cost, {1}{U}{U}
    game.priority_player_index = 0
    log = len(game.log)

    assert take_permanent_special_action(game, 0, quanar, "turn_face_up") is None
    resolve_stack(game)
    game.check_state_based_actions()

    assert any("Mischievous Quanar copied Lightning Bolt" in line for line in game.log[log:])
    assert not game.is_on_battlefield(giant)
    assert not game.is_on_battlefield(bears)
    assert (me.life, you.life) == (20, 20)


@pytest.mark.cr("707.12", "601.2c")
def test_a_copy_cast_from_exile_by_a_seat_nobody_asks_aims_away_from_its_side(set_pool):
    """``cast_copy_of_exiled_card``'s row above, driven: Isochron Scepter with
    Lightning Bolt imprinted, activated by a seat nobody asks that has a
    Grizzly Bears beside an opponent's Hill Giant. The copy is *cast*
    (CR 707.12), so it announces its own target (CR 601.2c) through the
    rehearsed cast chooser — at the opponent's side, never at the caster's
    Bears or face."""
    mrd, lea = set_pool("MRD"), set_pool("LEA")
    me = PlayerState(name="P0", library=[lea["Mountain"]] * 5,
                     hand=[mrd["Isochron Scepter"], lea["Lightning Bolt"]])
    you = PlayerState(name="P1", library=[lea["Mountain"]] * 5)
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    game.active_player_index = game.priority_player_index = 0
    game.current_phase = "main"
    game.current_turn_phase, game.current_step = "precombat_main", None
    bears = Permanent(card=lea["Grizzly Bears"])
    giant = Permanent(card=lea["Hill Giant"])
    game._put_permanent_onto_battlefield(0, bears, None)
    game._put_permanent_onto_battlefield(1, giant, None)
    # The imprint as a person answers it, so the exiled card is the Bolt.
    game.interactive_seats = {0}
    assert game.cast_from_hand(0, "Isochron Scepter").supported
    assert game.resolve_top_of_stack() is False
    assert game.confirm_optional_pay(0, accept=True)
    assert game.confirm_exile_from_hand_choice(0, 0)
    resolve_stack(game)
    assert [card.name for card in me.exile] == ["Lightning Bolt"]
    scepter = next(p for p in game.controlled_by(0) if p.card.name == "Isochron Scepter")
    scepter.metadata["summoning_sickness_turn"] = -99

    game.interactive_seats = set()
    log = len(game.log)
    assert game.activate_permanent_ability(
        0, "Isochron Scepter", permanent_index=game.battlefield_index_of(scepter),
        ability_index=0,
    ).supported
    resolve_stack(game)
    game.check_state_based_actions()

    assert any("cast a copy of Lightning Bolt" in line for line in game.log[log:]), game.log[log:]
    assert game.is_on_battlefield(bears)
    assert me.life == 20
    assert not game.is_on_battlefield(giant) or you.life == 17, game.log[log:]
    assert game.pending_choices == []
    assert [card.name for card in me.exile] == ["Lightning Bolt"]
