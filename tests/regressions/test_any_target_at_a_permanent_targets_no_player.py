""""Any target" aimed at a permanent targets that permanent, and nobody else.

A stack object records the player it targets and the battlefield a targeted
permanent sits on in the same field. ``stack_targets`` has told the two apart
since Psychic Battle; the "becomes the target" announcement did not ask it, and
for a picker that may choose a face *or* an object ("any target", "player or
planeswalker") it announced both — the permanent that was named and the
player whose battlefield it was on.

Rayne, Academy Chancellor ("Whenever you or a permanent you control becomes
the target of a spell or ability an opponent controls, you may draw a card")
drew **twice** for one Lightning Bolt at one Grizzly Bears.

Swept over every non-modal instant and sorcery in the pool whose picker offers
both a face and a permanent, with the announcements recorded as they are made.
Found while writing ``tests/engine/
test_permanent_spell_announces_nothing_census.py``, whose three "any target"
entry triggers announced a player nobody named.
"""

from __future__ import annotations

import pytest

import engine.events as events
from engine import Game, PlayerState
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

#: A floor, because a sweep that reaches nothing passes. 50 on the day.
_MIN_SPELLS = 40


def _duel(pool, hand=()) -> Game:
    game = Game(players=[
        PlayerState("A", library=[pool["Forest"]] * 10, hand=list(hand)),
        PlayerState("B", library=[pool["Forest"]] * 10),
    ])
    game.enforce_mana_costs = False
    return game


@pytest.fixture
def _targeted_seats(monkeypatch):
    """The seat of every *player* announced as "becomes the target"."""
    seats: list[int] = []
    emit = events.emit

    def recording(game, kind, *args, **kwargs):
        if kind == "self_becomes_target" and kwargs.get("targeted_seat") is not None:
            seats.append(kwargs["targeted_seat"])
        return emit(game, kind, *args, **kwargs)

    monkeypatch.setattr(events, "emit", recording)
    return seats


def test_no_spell_aimed_at_a_permanent_announces_its_controller(
    catalog, catalog_by_name, _targeted_seats,
):
    examined = 0
    findings: list[str] = []
    for card in catalog:
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        game = _duel(catalog_by_name, hand=[card])
        bears = Permanent(card=catalog_by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)
        offered = game.cast_target_spec(0, card).get("valid_targets") or ()
        faces = any(entry.get("kind") == "player" for entry in offered)
        at_the_bears = any(
            entry.get("kind") == "permanent"
            and game.permanent_at(entry["seat"], entry["index"]) is bears
            for entry in offered
        )
        if not (faces and at_the_bears):
            continue
        _targeted_seats.clear()
        if not game.queue_from_hand(
            0, card.name, target_permanent_ids=[bears.permanent_id], x_value=1,
        ).supported:
            continue
        examined += 1
        if _targeted_seats:
            findings.append(f"{card.name}: named the Bears, announced seat(s) {_targeted_seats}")

    assert not findings, f"{len(findings)} of {examined}: " + "; ".join(findings[:12])
    assert examined >= _MIN_SPELLS, f"only {examined} spells driven"


def test_rayne_draws_once_for_a_bolt_at_a_creature_and_once_for_a_bolt_at_her_controller(
    catalog_by_name,
):
    """Both directions: the permanent named is one target, and the face named
    is one target — the fix must not have taken the second away."""
    for aim, expected_hand in (("creature", 1), ("player", 1)):
        game = _duel(catalog_by_name, hand=[catalog_by_name["Lightning Bolt"]])
        game._put_permanent_onto_battlefield(
            1, Permanent(card=catalog_by_name["Rayne, Academy Chancellor"]), None,
        )
        bears = Permanent(card=catalog_by_name["Grizzly Bears"])
        game._put_permanent_onto_battlefield(1, bears, None)
        keywords = (
            {"target_permanent_ids": [bears.permanent_id]} if aim == "creature"
            else {"target_player_index": 1}
        )
        assert game.queue_from_hand(0, "Lightning Bolt", **keywords).supported
        assert [item.card.name for item in game.stack] == [
            "Lightning Bolt", "Rayne, Academy Chancellor",
        ], aim
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        assert len(game.players[1].hand) == expected_hand, aim
        if aim == "creature":
            assert bears.damage_marked == 3 and game.players[1].life == 20
        else:
            assert bears.damage_marked == 0 and game.players[1].life == 17


def test_an_ability_with_any_target_announces_the_creature_alone(catalog_by_name):
    """Prodigal Sorcerer's "{T}: This creature deals 1 damage to any target",
    the activated twin of the same announcement."""
    game = _duel(catalog_by_name)
    game._put_permanent_onto_battlefield(
        1, Permanent(card=catalog_by_name["Rayne, Academy Chancellor"]), None,
    )
    bears = Permanent(card=catalog_by_name["Grizzly Bears"])
    game._put_permanent_onto_battlefield(1, bears, None)
    tim = Permanent(card=catalog_by_name["Prodigal Sorcerer"])
    game._put_permanent_onto_battlefield(0, tim, None)
    tim.metadata.pop("summoning_sickness_turn", None)

    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer", target_permanent_ids=[bears.permanent_id],
    ).supported

    assert [item.card.name for item in game.stack] == [
        "Prodigal Sorcerer", "Rayne, Academy Chancellor",
    ]
