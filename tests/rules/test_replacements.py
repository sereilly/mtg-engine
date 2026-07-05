"""Unit tests for the replacement-effect registry (engine/replacements.py).

The migrated Lich / Disintegrate / Jade Monolith / Personal Incarnation
behaviors keep their existing per-card tests as the regression net; these
tests cover the registry mechanics plus the migrated paths end-to-end.
"""

from __future__ import annotations

import pytest

from engine import PlayerState
from engine.models import Permanent
from engine.replacements import (
    REPLACEMENTS,
    ReplacementOutcome,
    apply_replacements,
    replacement_effect,
)
from tests.helpers import CARDS_BY_NAME, _game, _mk_creature_card


def _two_player_game():
    p1 = PlayerState(name="A", library=[], hand=[])
    p2 = PlayerState(name="B", library=[], hand=[])
    return _game(p1, p2), p1, p2


# --- registry mechanics ------------------------------------------------------

@pytest.mark.cr("616.1", "614.5")
def test_interceptors_run_in_registration_order_and_can_modify_amount():
    calls = []

    def first(game, payload):
        calls.append("first")
        return ReplacementOutcome(new_amount=payload["amount"] - 1)

    def second(game, payload):
        calls.append("second")
        return None

    kind = "_test_ordering"
    try:
        replacement_effect(kind)(first)
        replacement_effect(kind)(second)
        consumed, payload = apply_replacements(None, kind, {"amount": 5})
        assert not consumed
        assert payload["amount"] == 4
        assert calls == ["first", "second"]
    finally:
        REPLACEMENTS.pop(kind, None)


@pytest.mark.cr("614.6")
def test_consuming_interceptor_stops_the_chain():
    calls = []

    def consumer(game, payload):
        calls.append("consumer")
        return ReplacementOutcome(replaced=True)

    def never_reached(game, payload):
        calls.append("never")
        return None

    kind = "_test_consume"
    try:
        replacement_effect(kind)(consumer)
        replacement_effect(kind)(never_reached)
        consumed, _ = apply_replacements(None, kind, {"amount": 1})
        assert consumed
        assert calls == ["consumer"]
    finally:
        REPLACEMENTS.pop(kind, None)


@pytest.mark.cr("614.1")
def test_unknown_kind_is_a_no_op():
    consumed, payload = apply_replacements(None, "_no_such_kind", {"amount": 2})
    assert not consumed
    assert payload["amount"] == 2


# --- migrated LEA paths ------------------------------------------------------

@pytest.mark.cr("614.1a")
def test_lich_life_gain_draws_instead():
    game, p1, _ = _two_player_game()
    lich = CARDS_BY_NAME["Lich"]
    p1.battlefield.append(Permanent(card=lich))
    p1.library = [CARDS_BY_NAME["Lightning Bolt"], CARDS_BY_NAME["Fireball"]]
    before_life = p1.life
    game._gain_life(p1, 2)
    assert p1.life == before_life
    assert len(p1.hand) == 2


@pytest.mark.cr("614.1a")
def test_gain_life_without_lich_is_normal():
    game, p1, _ = _two_player_game()
    before = p1.life
    game._gain_life(p1, 3)
    assert p1.life == before + 3


@pytest.mark.cr("614.1a", "614.6")
def test_exile_if_dies_replacement():
    game, p1, _ = _two_player_game()
    perm = Permanent(card=_mk_creature_card("Doomed", 2, 2))
    perm.metadata["exile_if_dies_this_turn"] = True
    p1.battlefield.append(perm)
    p1.battlefield.remove(perm)
    game._permanent_to_graveyard(p1, perm)
    assert [c.name for c in p1.exile] == ["Doomed"]
    assert p1.graveyard == []


@pytest.mark.cr("614.9")
def test_personal_incarnation_style_one_point_redirect():
    game, p1, _ = _two_player_game()
    perm = Permanent(card=_mk_creature_card("Avatar", 6, 6))
    perm.metadata["redirect_one_damage_to_owner_until_eot"] = 1
    p1.battlefield.append(perm)
    before = p1.life
    dealt = game._mark_damage_on_permanent(perm, 3)
    assert dealt == 2                      # 1 of the 3 was redirected
    assert p1.life == before - 1           # ...to the owner
    assert perm.metadata["redirect_one_damage_to_owner_until_eot"] == 0
