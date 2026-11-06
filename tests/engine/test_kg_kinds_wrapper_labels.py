"""A wrapper kind is labelled by its shape — and the guard that says so reads
the label every ability actually gets.

`unless_player_pays` was filed under `activated_control` after Scarwood Bandits,
the card that prompted its row, and three more cards reach it — Nakaya Shade's
pump, Barbarian Bully's pump-or-damage, Rhystic Circle's prevention — all
reported as control. It is a wrapper (its payload carries the effect behind each
answer), and CR 118.12a defines "[do something] unless [a player does something
else]" as "[a player may do something else]. If [that player doesn't], [do
something]", so it takes `may`'s shape label, `activated_optional`.

``test_a_wrapper_kind_never_borrows_a_leaf_effects_bucket`` let the old row
through only because no leaf had been filed under `activated_control`, and it
read the table's rows alone, so a kind *missing* from ``ACTIVATED_LABELS`` was
never examined. It now reads the label each grammar-read ability gets, row or
default (``test_effect_labels.activated_shapes``); the backwards validations
below put both holes back on purpose and watch it fire.

The triggered tables had the same shape in their condition-blind rows:
`unless_player_pays` read `upkeep_effect` under any condition, `choose_one`
read `triggered_pump`, `create_delayed_trigger` read `triggered_token`. Each now
names its shape or lets the condition name the moment, under a twin guard.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.activated_labels import ACTIVATED_LABELS
from engine.triggered_labels import (TRIGGERED_LABELS,
                                     TRIGGERED_LABELS_BY_CONDITION)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.engine.test_effect_labels import (activated_shapes,
                                             borrowed_buckets,
                                             triggered_shapes)
from tests.helpers import resolve_stack
from web.serialization import _serialize_stack_item

CATALOG = {card.name: card for card in load_catalog()}


def _activated_borrowings():
    return borrowed_buckets(
        (kind, label, wrapper) for _n, kind, label, wrapper in activated_shapes(load_catalog())
    )


def _triggered_borrowings():
    return borrowed_buckets(
        (kind, label, wrapper)
        for _n, _c, kind, label, wrapper, by_condition in triggered_shapes(load_catalog())
        if not (wrapper and by_condition)
    )


def _table_only_borrowings():
    """The guard as it read before the kg round: kinds the table names, by the
    table's own value — the population that could not see a defaulted kind."""
    shapes = activated_shapes(load_catalog())
    wrappers = {kind for _n, kind, _l, wrapper in shapes if wrapper and kind in ACTIVATED_LABELS}
    leaves = {kind for _n, kind, _l, wrapper in shapes if not wrapper and kind in ACTIVATED_LABELS}
    return sorted(
        kind for kind in wrappers
        if any(ACTIVATED_LABELS[leaf] == ACTIVATED_LABELS[kind] for leaf in leaves - {kind})
    )


# --- the rows -------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "Scarwood Bandits", "Nakaya Shade", "Barbarian Bully", "Rhystic Circle",
])
def test_an_offer_reports_its_shape_not_one_card_s_effect(name):
    abilities = [
        ability for ability in compile_card_oracle(CATALOG[name]).activated_abilities
        if ability.instruction is not None and ability.instruction.kind == "unless_player_pays"
    ]
    assert abilities, name
    assert {ability.effect_kind for ability in abilities} == {"activated_optional"}


def test_the_triggered_offer_takes_its_label_from_the_condition():
    assert "unless_player_pays" not in TRIGGERED_LABELS
    assert TRIGGERED_LABELS_BY_CONDITION[("upkeep_self", "unless_player_pays")] == "upkeep_effect"
    labels = {
        trig.effect_kind for trig in compile_card_oracle(CATALOG["Icy Prison"]).triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "unless_player_pays"
    }
    assert labels == {"upkeep_effect"}
    labels = {
        trig.effect_kind for trig in compile_card_oracle(CATALOG["Ice Cave"]).triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == "unless_player_pays"
    }
    # The cast moment's word since kg3 (it read the counterspell it offers):
    # ``tests/engine/test_kg3_chores_moment_labels.py``.
    assert labels == {"triggered_cast"}


@pytest.mark.parametrize("name, kind, label", [
    ("Fog Elemental", "create_delayed_trigger", "triggered_delayed_trigger"),
    ("Rukh Egg", "create_delayed_trigger", "triggered_delayed_trigger"),
    ("Gabriel Angelfire", "choose_one", "triggered_modal"),
    # A printed modal trigger, labelled through the same row by
    # ``ability_lines`` rather than by the grammar's front end.
    ("Elder Gargaroth", "choose_one", "triggered_modal"),
])
def test_a_condition_blind_wrapper_row_names_its_shape(name, kind, label):
    labels = {
        trig.effect_kind for trig in compile_card_oracle(CATALOG[name]).triggered_abilities
        if trig.instruction is not None and trig.instruction.kind == kind
    }
    assert labels == {label}, (name, labels)


# --- driven: the label is what the stack object carries and the wire says ----


def _ready(perm: Permanent) -> Permanent:
    perm.metadata["summoning_sickness_turn"] = -99
    return perm


def test_an_activated_offer_on_the_stack_is_an_activated_ability():
    """Nakaya Shade's "{B}: This creature gets +1/+1 until end of turn unless any
    player pays {2}." The activation reports the shape label, the stack object
    carries it, and the wire calls it what it is — an activated ability."""
    shade = _ready(Permanent(card=CATALOG["Nakaya Shade"]))
    p1 = PlayerState(name="P1", battlefield=[shade], library=[CATALOG["Swamp"]] * 5, life=20)
    p2 = PlayerState(name="P2", library=[CATALOG["Swamp"]] * 5, life=20)
    game = Game(players=[p1, p2])
    game.interactive_seats = set()
    p1.mana_pool["B"] = 1

    result = game.queue_permanent_ability(0, "Nakaya Shade")
    assert result.supported, result.details
    assert result.effect_kind == "activated_optional"
    item = game.stack[-1]
    assert item.ability_effect_kind == "activated_optional"
    assert _serialize_stack_item(item, game)["is_triggered"] is False

    before = shade.effective_power
    resolve_stack(game)
    # The toll is offered round the table (CR 118.12a); with no mana left
    # anywhere nobody can pay, so the default answers decline and the pump
    # happens.
    game.auto_resolve_pending_choices()
    assert not game.pending_choices
    assert shade.effective_power == before + 1, game.log
    assert "Nakaya Shade gets +1/+1 until end of turn" in game.log


# --- backwards: the guards fire on the defects they exist for ---------------


def test_the_guard_fires_on_a_wrapper_filed_under_a_leaf_bucket(monkeypatch):
    assert not _activated_borrowings()
    monkeypatch.setitem(ACTIVATED_LABELS, "unless_player_pays", "activated_pump")
    assert "unless_player_pays" in {kind for kind, *_ in _activated_borrowings()}


def test_the_old_row_was_one_control_leaf_away_from_red(monkeypatch):
    """The entry's own scenario. Restore `activated_control` and file a control
    leaf there (Jinxed Idol's give-away, the row whose note says it was kept off
    that bucket for exactly this reason): the old row borrows. Under the shape
    label the same leaf is filed there harmlessly."""
    monkeypatch.setitem(ACTIVATED_LABELS, "give_control_of_source_to_player", "activated_control")
    assert "unless_player_pays" not in {kind for kind, *_ in _activated_borrowings()}
    monkeypatch.setitem(ACTIVATED_LABELS, "unless_player_pays", "activated_control")
    assert "unless_player_pays" in {kind for kind, *_ in _activated_borrowings()}


def test_the_guard_sees_a_wrapper_missing_from_the_table(monkeypatch):
    """The hole the old population had. Take `sequence`'s row away: its
    abilities default to ``activated_<category>`` — `activated_damage` for
    Orcish Artillery's, a leaf's bucket — and the guard names it, while the
    table-only reading the guard used to take is silent on the same table."""
    monkeypatch.delitem(ACTIVATED_LABELS, "sequence")
    borrowed = _activated_borrowings()
    assert "sequence" in {kind for kind, *_ in borrowed}, borrowed
    assert "sequence" not in _table_only_borrowings()


@pytest.mark.parametrize("kind, old_label", [
    ("create_delayed_trigger", "triggered_token"),
    ("choose_one", "triggered_pump"),
])
def test_the_triggered_guard_fires_on_the_rows_it_replaced(monkeypatch, kind, old_label):
    assert not _triggered_borrowings()
    monkeypatch.setitem(TRIGGERED_LABELS, kind, old_label)
    assert kind in {found for found, *_ in _triggered_borrowings()}


def test_the_triggered_guard_fires_on_the_condition_blind_offer(monkeypatch):
    monkeypatch.delitem(TRIGGERED_LABELS_BY_CONDITION, ("upkeep_self", "unless_player_pays"))
    monkeypatch.setitem(TRIGGERED_LABELS, "unless_player_pays", "upkeep_effect")
    assert "unless_player_pays" in {found for found, *_ in _triggered_borrowings()}
