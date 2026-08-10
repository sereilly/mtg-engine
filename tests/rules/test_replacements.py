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
def test_interceptors_run_in_order_and_can_modify_amount():
    calls = []

    def first(game, payload):
        calls.append("first")
        return ReplacementOutcome(new_amount=payload["amount"] - 1)

    def second(game, payload):
        calls.append("second")
        return None

    kind = "_test_ordering"
    try:
        replacement_effect(kind, 20, applies=lambda game, payload: True)(second)
        replacement_effect(kind, 10, applies=lambda game, payload: True)(first)
        consumed, payload = apply_replacements(None, kind, {"amount": 5})
        assert not consumed
        assert payload["amount"] == 4
        # Registration order is not the running order — the declared order is,
        # so an interceptor added later can still be the one that goes first.
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
        replacement_effect(kind, 10, applies=lambda game, payload: True)(consumer)
        replacement_effect(kind, 20, applies=lambda game, payload: True)(never_reached)
        consumed, payload = apply_replacements(None, kind, {"amount": 1})
        assert consumed
        assert calls == ["consumer"]
        assert "_replaced" not in payload, (
            "the consumed marker is the loop's bookkeeping and must not escape "
            "onto the caller's payload"
        )
    finally:
        REPLACEMENTS.pop(kind, None)


@pytest.mark.cr("616.1f")
def test_616_1f_an_interceptor_is_re_asked_against_what_the_last_one_left():
    """The process repeats over the effects that are *now* applicable, so an
    interceptor whose predicate stops holding once an earlier one has run is
    never applied — the difference between this and walking a fixed list."""
    calls = []

    def halve(game, payload):
        calls.append("halve")
        return ReplacementOutcome(new_amount=payload["amount"] // 2)

    def only_above_three(game, payload):
        calls.append("only_above_three")
        return None

    kind = "_test_re_ask"
    try:
        replacement_effect(kind, 10, applies=lambda game, payload: True)(halve)
        replacement_effect(
            kind, 20, applies=lambda game, payload: payload["amount"] > 3
        )(only_above_three)
        consumed, payload = apply_replacements(None, kind, {"amount": 4})
        assert not consumed
        assert payload["amount"] == 2
        assert calls == ["halve"], "the second was re-asked after the first ran"
    finally:
        REPLACEMENTS.pop(kind, None)


@pytest.mark.cr("616.1")
def test_616_1_applicability_is_asked_without_applying_anything():
    """The predicate CR 616.1 counts contenders with must not *do* anything: an
    effect that is asked about may then not be chosen. This is the contract that
    made the rule implementable, and it is one registry-wide property rather
    than a per-interceptor one, so it is asserted over the whole table."""
    game, p1, _ = _two_player_game()
    lich = CARDS_BY_NAME["Lich"]
    p1.battlefield.append(Permanent(card=lich))
    p1.library = [CARDS_BY_NAME["Lightning Bolt"], CARDS_BY_NAME["Fireball"]]

    payload = {"player": p1, "amount": 2, "source_name": None}
    before = (p1.life, len(p1.hand), len(p1.library))
    applicable = [c.key for c in REPLACEMENTS["life_gain"] if c.applies(game, payload)]

    assert (p1.life, len(p1.hand), len(p1.library)) == before, (
        "asking whether a replacement applies applied it"
    )
    assert applicable == ["_draw_instead_of_life_gain"]


@pytest.mark.cr("616.1")
def test_616_1_a_duplicate_order_within_a_kind_is_rejected():
    """Which effect replaces the event first is rules-visible, so a tie is a
    real ambiguity and surfaces at import rather than as a rare misplay."""
    kind = "_test_duplicate"
    try:
        replacement_effect(kind, 10, applies=lambda game, payload: True)(
            lambda game, payload: None
        )
        with pytest.raises(ValueError, match="already used"):
            replacement_effect(kind, 10, applies=lambda game, payload: True)(
                lambda game, payload: None
            )
        assert len(REPLACEMENTS[kind]) == 1, (
            "a rejected registration must not be added to the table"
        )
    finally:
        REPLACEMENTS.pop(kind, None)


@pytest.mark.cr("614.1")
def test_614_1_a_replacement_that_finds_nothing_to_do_is_still_spent():
    """Aladdin's Lamp armed over a library too short to look at anything. The
    replacement is used up and the draw then happens normally (CR 614.1).

    Which means its applicability predicate answers "is this armed?", not "will
    this do something?" — the short-library case has to stay *inside* the
    effect. A predicate that checked the library would decline, and declining is
    how the charge would survive to replace a later draw.
    """
    game, p1, _ = _two_player_game()
    game.lamp_draw_replacements[0] = 3
    p1.library = []

    drawn = game._draw_with_replacements(p1, 1)

    assert game.lamp_draw_replacements == {}, "the charge was spent anyway"
    assert drawn == 0, "an empty library had nothing to draw either way"


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
