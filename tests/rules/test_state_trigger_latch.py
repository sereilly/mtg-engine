"""CR 603.8 — when a state-triggered ability may trigger again.

    A state-triggered ability doesn't trigger again until the ability has
    resolved, has been countered, or has otherwise left the stack. Then, if the
    object with the ability is still in the same zone and the game state still
    matches its trigger condition, the ability will trigger again.

A state has no fire site, so the state-based sweep announces these and each
remembers that it has (the *latch*, ``engine/state_triggers.py``). The latch
was released by one thing only — the state ceasing to match — so an ability
that was **countered** while its state still held never triggered again: a
Homarid whose "remove all tide counters" was countered sat at four counters
for the rest of the game. Nine shipped cards behaved that way (ODY W2G7's
census), and Bomb Squad, whose third line is the same kind of ability about
another permanent, would have been the tenth.

This file is that census, in the suite, over both manifest roles:

* every state trigger that reaches the stack is countered through the engine's
  one counter seam (``Game.counter_stack_object`` — what "Counter target
  activated or triggered ability", Sublime Epiphany, calls) and must be back on
  the stack after the next sweep;
* **validated backwards**: with the release switched off the same census must
  name every one of them, so it cannot pass by examining nothing;
* and the bound the fix deliberately keeps: an ability that *resolved* does not
  announce again, because nothing printed can observe the difference and an
  intervening "if" nobody asked at the sweep would announce for ever.

The 24 state triggers that sacrifice their source *inside* the sweep ("When you
control no Islands, sacrifice this creature") never become stack objects at
all. That is an older, stated divergence of this engine and not this file's
subject; they are counted here so the number is not lost.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState, faces
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from engine.named_counters import add_counters, counters_on, remove_counters
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier
from tests.helpers import resolve_stack

#: Every condition kind the state-based sweep announces off a *state*.
STATE_KINDS = frozenset({
    "counters_reach_threshold", "source_has_no_counters",
    "source_power_at_least", "source_has_keyword", "life_at_most",
    "player_has_no_cards_in_hand", "controls_matching_permanent",
    "controls_no_matching", "no_permanents_anywhere",
    "permanent_counters_reach_threshold",
})


@pytest.fixture(scope="module")
def pool():
    cards = {}
    for card in load_cards(manifest_set_paths(include_measured=True)):
        cards.setdefault(card.name, card)
    return cards


def _put(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _make_the_state_true(game, permanent, trig, pool):
    """Arrange *trig*'s state on a board that did not have it."""
    kind, payload = trig.condition.kind, trig.condition.payload
    if kind == "counters_reach_threshold":
        add_counters(
            permanent, str(payload["counter_kind"]), int(payload["counter_count"])
        )
    elif kind == "permanent_counters_reach_threshold":
        victim = _put(game, 1, pool["Grizzly Bears"])
        add_counters(
            victim, str(payload["counter_kind"]), int(payload["counter_count"])
        )
    elif kind == "source_has_no_counters":
        held = counters_on(permanent, str(payload["counter_kind"]))
        if held:
            remove_counters(permanent, str(payload["counter_kind"]), held)
    elif kind == "source_power_at_least":
        add_pt_modifier(permanent, int(payload["power_count"]), 0)
    elif kind == "source_has_keyword":
        from engine.keywords import grant_keyword

        grant_keyword(permanent, str(payload["keyword_name"]))
    elif kind == "life_at_most":
        seat = 1 if payload.get("life_seat") == "an opponent" else 0
        game.players[seat].life = int(payload["life_count"])
    elif kind == "player_has_no_cards_in_hand":
        game.players[1].hand.clear()
    elif kind == "controls_matching_permanent":
        seat = 1 if payload.get("controls_seat") == "an opponent" else 0
        _put(game, seat, pool["Craw Wurm"])
        _put(game, seat, pool["Dwarven Warriors"])
    else:
        # "You control no Islands", "there are no creatures on the
        # battlefield": true of a board with nothing else on it.
        game.remove_all_from_battlefield(
            [other for other in game.all_permanents() if other is not permanent]
        )


def _instances(game, permanent, trig):
    return [
        item for item in game.stack
        if item.source_permanent is permanent
        and item.ability_text == trig.source_line
    ]


def _state_triggers_on_the_stack(pool):
    """``(card, trig, game, permanent, item)`` for every state trigger in the
    pool whose state, once arranged, puts the ability on the stack — and the
    names of the ones that are carried out inside the sweep instead."""
    stacked, inline = [], []
    for card in faces.compilation_units(list(pool.values())):
        program = compile_card_oracle(card)
        if not program.supported:
            continue
        for trig in program.triggered_abilities:
            if trig.condition.kind not in STATE_KINDS:
                continue
            forest = pool["Forest"]
            game = Game(players=[
                PlayerState("P1", library=[forest] * 20, hand=[forest] * 3),
                PlayerState("P2", library=[forest] * 20, hand=[forest] * 3),
            ])
            game.enforce_mana_costs = False
            # A land and a creature each, so "no lands" and "no creatures" are
            # not true by accident before the card is looked at.
            for seat in (0, 1):
                _put(game, seat, forest)
                _put(game, seat, pool["Grizzly Bears"])
            permanent = _put(game, 0, card)
            game.check_state_based_actions()
            _make_the_state_true(game, permanent, trig, pool)
            game.check_state_based_actions()
            found = _instances(game, permanent, trig)
            if found:
                stacked.append((card, trig, game, permanent, found[-1]))
            else:
                inline.append(card.name)
    return stacked, inline


def _never_trigger_again_after_a_counter(pool) -> tuple[list[str], int, int]:
    stacked, inline = _state_triggers_on_the_stack(pool)
    stuck = []
    for card, trig, game, permanent, item in stacked:
        before = len(_instances(game, permanent, trig))
        game.counter_stack_object(item)
        assert len(_instances(game, permanent, trig)) == before - 1
        game.check_state_based_actions()
        if len(_instances(game, permanent, trig)) < before:
            stuck.append(card.name)
    return sorted(stuck), len(stacked), len(inline)


@pytest.mark.cr("603.8")
def test_a_countered_state_trigger_triggers_again_while_its_state_holds(pool):
    stuck, examined, inline = _never_trigger_again_after_a_counter(pool)
    # A sweep that measured nothing looks exactly like one that found nothing.
    assert examined >= 10, f"only {examined} state triggers reached the stack"
    assert inline >= 20, f"only {inline} state triggers were carried out inline"
    assert stuck == [], (
        "countered with its state still true, and never triggered again "
        f"(CR 603.8): {stuck}"
    )


@pytest.mark.cr("603.8")
def test_the_census_names_the_defect_when_the_release_is_switched_off(
    pool, monkeypatch
):
    """Validated backwards. Latched on the state alone — the engine this census
    was written against — every stacked state trigger is stuck, the nine
    shipped ones by name."""
    import engine.mixins.stack.resolution as resolution

    monkeypatch.setattr(resolution, "release_latch", lambda item: None)
    stuck, examined, _inline = _never_trigger_again_after_a_counter(pool)

    assert len(stuck) == examined
    assert {
        "Afiya Grove", "Hidden Predators", "Homarid", "Lurking Jackals",
        "Mazemind Tome", "Nine Lives", "Opal Avenger", "Tidal Influence",
        "Veiled Crocodile",
    } <= set(stuck)


@pytest.mark.cr("603.8", "603.4")
def test_a_state_trigger_that_resolved_does_not_announce_again(pool):
    """The bound. CR 603.8 re-arms a *resolved* ability too, and this engine
    does not: every state trigger in the pool either ends its own state as it
    resolves or prints an intervening "if" its own effect makes false
    (CR 603.4), so the difference is unobservable — and an engine that re-armed
    without asking that "if" at the sweep would announce the same do-nothing
    ability on every pass. This is the property that argument rests on: after
    the ability resolves, the board is quiet."""
    stacked, _inline = _state_triggers_on_the_stack(pool)
    assert len(stacked) >= 10
    noisy = []
    for card, trig, game, permanent, _item in stacked:
        resolve_stack(game)
        for _ in range(3):
            game.check_state_based_actions()
        if _instances(game, permanent, trig):
            noisy.append(card.name)
    assert noisy == []


@pytest.mark.cr("603.8")
def test_a_watched_permanent_that_drops_under_the_line_and_crosses_it_again(pool):
    """The half the latch always had, for the one trigger keyed per watched
    permanent: the state stops matching, and matching again is a new trigger.
    A second creature over the line is its own trigger and re-arms nothing."""
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState("P1", library=[forest] * 20),
        PlayerState("P2", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    squad = _put(game, 0, pool["Bomb Squad"])
    trig = compile_card_oracle(squad.card).triggered_abilities[-1]
    first = _put(game, 1, pool["Craw Wurm"])
    second = _put(game, 1, pool["Craw Wurm"])

    add_counters(first, "fuse", 4)
    game.check_state_based_actions()
    assert len(_instances(game, squad, trig)) == 1

    # Countered, and the counters gone by another road: nothing to announce.
    game.counter_stack_object(game.stack[-1])
    remove_counters(first, "fuse", 4)
    game.check_state_based_actions()
    assert not game.stack

    add_counters(second, "fuse", 4)
    game.check_state_based_actions()
    assert len(_instances(game, squad, trig)) == 1
    add_counters(first, "fuse", 4)
    game.check_state_based_actions()
    watched = {
        item.trigger_context["event_subject_permanent_id"]
        for item in _instances(game, squad, trig)
    }
    assert watched == {first.permanent_id, second.permanent_id}
    game.check_state_based_actions()
    assert len(game.stack) == 2
