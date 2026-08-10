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


@pytest.mark.cr("616.2")
def test_616_2_a_replacement_can_become_applicable_through_another():
    """CR 616.2's own worked example, with this pool's cards: Lich turns a life
    gain into a draw, and a draw replacement applies to *that* draw even though
    the original event was not a draw at all.

    The draw an effect creates is a draw like any other. Taking the cards off
    the library directly would skip the Ring silently — the player would keep an
    armed replacement they had already spent the opportunity for."""
    game, p1, _ = _two_player_game()
    p1.battlefield.append(Permanent(card=CARDS_BY_NAME["Lich"]))
    p1.library = [CARDS_BY_NAME["Lightning Bolt"]]
    p1.sideboard = [CARDS_BY_NAME["Black Lotus"]]
    game.outside_game_draw_replacements.add(0)

    game._gain_life(p1, 1)

    assert 0 not in game.outside_game_draw_replacements, "the draw replacement applied"
    assert [c.name for c in p1.hand] == ["Black Lotus"], "taken from outside the game"
    assert [c.name for c in p1.library] == ["Lightning Bolt"], "the library was not drawn from"


@pytest.mark.cr("121.2", "614.1")
def test_121_2_each_of_several_draws_is_replaceable_on_its_own():
    """"If a player is instructed to draw multiple cards, that player performs
    that many individual card draws" — so two armed replacements take one draw
    each. The second used to be taken straight off the library, because the
    draws queued behind a replaced one bypassed the registry."""
    game, p1, _ = _two_player_game()
    p1.library = [CARDS_BY_NAME["Lightning Bolt"], CARDS_BY_NAME["Fireball"]]
    p1.sideboard = [CARDS_BY_NAME["Black Lotus"]]
    game.outside_game_draw_replacements.add(0)
    game.lamp_draw_replacements[0] = 2

    game._draw_with_replacements(p1, 2)

    assert 0 not in game.outside_game_draw_replacements, "the first draw was replaced"
    assert game.lamp_draw_replacements == {}, "and the second draw was replaced too"
    assert "Black Lotus" in [c.name for c in p1.hand]


# --- 616.1e: the affected player chooses ------------------------------------


def _two_armed_draw_replacements(interactive: bool):
    """A seat with both of this pool's draw replacements armed — Ring of Ma'rûf
    and Aladdin's Lamp — which is the reachable CR 616.1e contention."""
    game, p1, _ = _two_player_game()
    p1.library = [CARDS_BY_NAME["Lightning Bolt"], CARDS_BY_NAME["Fireball"]]
    p1.sideboard = [CARDS_BY_NAME["Black Lotus"]]
    game.outside_game_draw_replacements.add(0)
    game.lamp_draw_replacements[0] = 2
    if interactive:
        game.interactive_seats = {0}
    return game, p1


@pytest.mark.cr("616.1e")
def test_616_1e_the_affected_player_is_asked_which_effect_applies_first():
    """Two replacements are attempting to modify one draw, so the rule gives
    the choice to the player. The event suspends on the prompt."""
    game, p1 = _two_armed_draw_replacements(interactive=True)

    drawn = game._draw_with_replacements(p1, 1)

    prompts = game.pending_choices_of("effect_order", 0)
    assert len(prompts) == 1
    assert sorted(prompts[0].data["options"]) == ["Aladdin's Lamp", "Ring of Ma'rûf"]
    assert drawn == 0, "the draw waits for the answer"


@pytest.mark.cr("616.1e")
def test_616_1e_arming_the_prompt_applies_nothing():
    """The property that makes suspending safe: because every applicability
    predicate is pure, the process reaches the prompt having done *nothing*, so
    answering can re-run the event from the top rather than resume it. If
    arming the prompt spent a charge, the re-run would spend a second one."""
    game, p1 = _two_armed_draw_replacements(interactive=True)

    game._draw_with_replacements(p1, 1)

    assert 0 in game.outside_game_draw_replacements, "the Ring is still armed"
    assert game.lamp_draw_replacements == {0: 2}, "the Lamp is still armed"
    assert p1.hand == [] and len(p1.library) == 2, "no card moved"


@pytest.mark.cr("616.1e")
def test_616_1e_the_answer_decides_which_effect_is_spent():
    """Answering re-runs the draw, which reaches the same contention, finds the
    recorded answer and applies it. Picking the Lamp leaves the Ring armed —
    the opposite of the default order, so this cannot pass by accident."""
    game, p1 = _two_armed_draw_replacements(interactive=True)
    game._draw_with_replacements(p1, 1)
    lamp = next(
        i for i, o in enumerate(game.pending_choices_of("effect_order", 0)[0].data["options"])
        if o == "Aladdin's Lamp"
    )

    assert game.resolve_pending_choice("effect_order", 0, option_index=lamp) is True

    assert game.lamp_draw_replacements == {}, "the chosen effect applied"
    assert 0 in game.outside_game_draw_replacements, "the other is untouched and still armed"
    assert not game.pending_choices_of("effect_order", 0), "the prompt is answered"
    # And the event really finished rather than stalling half-done: the Lamp's
    # own "which of the top cards do you take" prompt is now the one waiting.
    assert game.pending_lamp_draw is not None
    assert game.confirm_lamp_draw(0, 0) is True
    assert [c.name for c in p1.hand] == ["Lightning Bolt"]


@pytest.mark.cr("616.1e")
def test_616_1e_the_default_reproduces_the_documented_order():
    game, p1 = _two_armed_draw_replacements(interactive=True)
    game._draw_with_replacements(p1, 1)

    game.resolve_pending_choice("effect_order", 0, option_index=0)

    assert 0 not in game.outside_game_draw_replacements, "the Ring went first"
    assert game.lamp_draw_replacements == {0: 2}, "the Lamp is still armed"


@pytest.mark.cr("616.1e")
def test_616_1e_a_non_interactive_seat_is_never_asked():
    """AI and headless play must not queue or suspend — they take the
    documented default inline, exactly as before the prompt existed."""
    game, p1 = _two_armed_draw_replacements(interactive=False)

    game._draw_with_replacements(p1, 1)

    assert not game.pending_choices_of("effect_order", 0)
    assert 0 not in game.outside_game_draw_replacements, "the default applied inline"
    assert game.effect_order_answers == {}, "and left nothing recorded"


@pytest.mark.cr("616.1e")
def test_616_1e_an_answer_does_not_outlive_its_event():
    """A recorded answer is popped once the event it was for gets through, so a
    later contention asks again instead of silently inheriting it."""
    game, p1 = _two_armed_draw_replacements(interactive=True)
    game._draw_with_replacements(p1, 1)
    game.resolve_pending_choice("effect_order", 0, option_index=0)

    assert game.effect_order_answers == {}


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
