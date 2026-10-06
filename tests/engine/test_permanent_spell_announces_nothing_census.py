"""A permanent spell is not targeted; its entry trigger is.

CR 115.1 lists what is targeted — an instant or sorcery spell (a), an Aura
spell (b), an activated ability (c), a triggered ability (d) — and 115.1d says
when a trigger's targets are chosen: "as the ability is put on the stack". A
creature spell is none of the four.

This engine *names* an entry trigger's target as the permanent is cast, and it
used to **announce** it then too, as the spell's own. So every "becomes the
target of a spell or ability" watcher heard about a target the spell does not
have:

* at the cast, when the trigger did not exist yet;
* as targeted by "a spell" — Forsaken Wastes' and Fugitive Druid's word;
* for a spell that was then countered, whose trigger never existed;
* and for a permanent the trigger could not choose at all (protection from
  it): with Cowardice out, a White Knight named for a Nekrataal was returned
  to its owner's hand by an ability that never targeted it.

Driven for every non-Aura permanent in the pool whose cast names a permanent
for its entry trigger, with the two announcements recorded as they are made.

Validated backwards: with ``stack_targets.permanent_spell_targets_nothing``
answering False the census names every permanent it examines, on all three
counts.
"""

from __future__ import annotations

import pytest

import engine.events as events
from engine import Game, PlayerState
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: A floor, because a sweep that reaches nothing passes. 32 on the day.
_MIN_PERMANENTS = 28

_BOARD = (
    "Grizzly Bears", "Black Knight", "White Knight", "Forest", "Island", "Sol Ring",
    "Circle of Protection: Red", "Ornithopter", "Serra Angel", "Hill Giant", "Wall of Wood",
)
_ANNOUNCEMENTS = ("self_becomes_target", "player_chooses_targets")


@pytest.fixture(scope="module")
def _pool(catalog):
    pool: dict = {}
    for unit in compilation_units(catalog):
        pool.setdefault(unit.name, unit)
    return pool


@pytest.fixture
def _announced(monkeypatch):
    """Every target announcement, as ``(kind, permanent id, targeted by, by
    which stack object's card)`` in the order it was made."""
    record: list[tuple] = []
    emit = events.emit

    def recording(game, kind, *args, **kwargs):
        if kind in _ANNOUNCEMENTS:
            subject = kwargs.get("subject")
            item = kwargs.get("targets_chosen_item")
            record.append((
                kind, getattr(subject, "permanent_id", None), kwargs.get("targeted_by"),
                getattr(item, "is_ability", None),
            ))
        return emit(game, kind, *args, **kwargs)

    monkeypatch.setattr(events, "emit", recording)
    return record


def _table(pool, card, *, extra=()) -> Game:
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 12, hand=[card]),
        PlayerState("B", library=[pool["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    for seat in (0, 1):
        for name in _BOARD:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    for seat, name in extra:
        game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    return game


def _units(pool) -> list:
    """Each supported non-Aura permanent whose cast picker is its entry
    trigger's own list and offers a permanent."""
    found = []
    for card in sorted(pool.values(), key=lambda c: c.name):
        if card.primary_type in ("instant", "sorcery", "land") or "Aura" in card.type_line:
            continue
        if not compile_card_oracle(card).supported:
            continue
        game = _table(pool, card)
        if game.entry_trigger_cast_targets(0, card, optional_cost_payments={}) is None:
            continue
        offered = [
            entry for entry in game.cast_target_spec(0, card).get("valid_targets") or ()
            if entry.get("kind") == "permanent"
        ]
        if offered:
            found.append((card, offered[0]))
    return found


def _cast(pool, card, entry, **table):
    game = _table(pool, card, **table)
    target = game.permanent_at(entry["seat"], entry["index"])
    assert game.queue_from_hand(
        0, card.name, target_permanent_ids=[target.permanent_id],
    ).supported, card.name
    return game, target


def test_the_cast_announces_nothing_and_the_trigger_announces_once(_pool, _announced):
    units = _units(_pool)
    findings: list[str] = []
    for card, entry in units:
        _announced.clear()
        game, target = _cast(_pool, card, entry)
        if _announced:
            findings.append(f"{card.name}: the cast announced {_announced}")
            continue
        spell = game.stack[-1]
        assert not spell.is_ability and spell.card is card
        game.resolve_top_of_stack()
        became = [row for row in _announced if row[0] == "self_becomes_target"]
        chose = [row for row in _announced if row[0] == "player_chooses_targets"]
        if [row[1:3] for row in became] != [(target.permanent_id, "an ability")]:
            findings.append(f"{card.name}: as its trigger went on the stack, {became}")
        if [row[3] for row in chose] != [True]:
            findings.append(f"{card.name}: \"chooses targets\" announced {chose}")

    assert len(units) >= _MIN_PERMANENTS, len(units)
    assert not findings, "\n".join(findings)


def test_a_countered_permanent_spell_never_targeted_anything(_pool, _announced):
    units = _units(_pool)
    findings: list[str] = []
    for card, entry in units:
        _announced.clear()
        game, _target = _cast(_pool, card, entry)
        game.counter_stack_object(game.stack[-1])
        resolve_stack(game)
        if _announced:
            findings.append(f"{card.name}: {_announced}")

    assert len(units) >= _MIN_PERMANENTS, len(units)
    assert not findings, "\n".join(findings)


def test_a_creature_the_trigger_cannot_choose_is_not_bounced_by_cowardice(_pool):
    """"Whenever a creature becomes the target of a spell or ability, return
    that creature to its owner's hand." (Cowardice.) A Nekrataal cast naming
    the opponent's White Knight — protection from black, so only a script can
    name it and the trigger sets the name aside — never targets the Knight,
    and the Knight stays where it is."""
    nekrataal = _pool["Nekrataal"]
    game = Game(players=[
        PlayerState("A", library=[_pool["Forest"]] * 12, hand=[nekrataal]),
        PlayerState("B", library=[_pool["Forest"]] * 12),
    ])
    game.enforce_mana_costs = False
    game._put_permanent_onto_battlefield(1, Permanent(card=_pool["Cowardice"]), None)
    knight = Permanent(card=_pool["White Knight"])
    game._put_permanent_onto_battlefield(1, knight, None)

    assert game.cast_from_hand(
        0, "Nekrataal", target_permanent_ids=[knight.permanent_id],
    ).supported
    resolve_stack(game)

    assert game.is_on_battlefield(knight)
    assert game.players[1].hand == []
    assert any("can't target what was named as it was cast" in line for line in game.log)


def test_cowardice_answers_the_trigger_and_not_a_countered_spell(_pool):
    """The legal name, both ways. Man-o'-War cast at a Grizzly Bears and
    countered: the Bears was never the target of anything. Cast and resolved:
    the Bears becomes the target of the *trigger*, and Cowardice returns it."""
    man_o_war, bears_card = _pool["Man-o'-War"], _pool["Grizzly Bears"]
    for countered in (True, False):
        game = Game(players=[
            PlayerState("A", library=[_pool["Forest"]] * 12, hand=[man_o_war]),
            PlayerState("B", library=[_pool["Forest"]] * 12),
        ])
        game.enforce_mana_costs = False
        game._put_permanent_onto_battlefield(1, Permanent(card=_pool["Cowardice"]), None)
        bears = Permanent(card=bears_card)
        game._put_permanent_onto_battlefield(1, bears, None)
        assert game.queue_from_hand(
            0, "Man-o'-War", target_permanent_ids=[bears.permanent_id],
        ).supported
        assert [item.card.name for item in game.stack] == ["Man-o'-War"]
        if countered:
            game.counter_stack_object(game.stack[-1])
            resolve_stack(game)
            assert game.is_on_battlefield(bears) and game.players[1].hand == []
            continue
        resolve_stack(game)
        assert not game.is_on_battlefield(bears)
        assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
        assert any(
            "Grizzly Bears returned to" in line for line in game.log
        )
