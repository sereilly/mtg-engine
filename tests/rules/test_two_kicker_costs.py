"""Rules tests earned by Planeshift wave 1, group 2 — two kicker costs on one
card (CR 702.33b) and the abilities linked to each of them (CR 702.33f).

Every card here is invented. That is the point: the five Battlemages are the
only printings, and what is being held is the rule — "Kicker [cost 1] and/or
[cost 2]" on any card, "kicked with its [A] kicker" in any sentence, on a
permanent or on a spell — rather than five names. The cards themselves are
played in ``tests/sets/test_pls_creatures.py``; the pool-wide censuses are in
``tests/engine/test_two_kickers.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.cast_costs import (KICKED, KICKED_WITH, kicked, kicker_costs,
                               unlinked_kicker_question)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card, resolve_stack

#: A creature with two kickers and one entry trigger linked to each.
_TWINMAGE = _mk_card(
    name="W1G2 Twinmage", mana_cost="{1}{W}", type_line="Creature - Wizard",
    power=2, toughness=2,
    oracle_text=(
        "Kicker {R} and/or {1}{U}\n"
        "When this creature enters, if it was kicked with its {R} kicker, "
        "it deals 3 damage to any target.\n"
        "When this creature enters, if it was kicked with its {1}{U} kicker, "
        "draw a card."
    ),
)

#: The same two questions asked by a *spell* of itself as it resolves.
_TWINSPELL = _mk_card(
    name="W1G2 Twinspell", mana_cost="{W}", type_line="Sorcery",
    oracle_text=(
        "Kicker {1}{R} and/or {G}\n"
        "You gain 1 life. If this spell was kicked with its {1}{R} kicker, it "
        "deals 2 damage to any target. If this spell was kicked with its {G} "
        "kicker, draw a card."
    ),
)

#: Two entry triggers that each choose a target, one per kicker.
_TWINBLADE = _mk_card(
    name="W1G2 Twinblade", mana_cost="{1}{B}", type_line="Creature - Wizard",
    power=2, toughness=2,
    oracle_text=(
        "Kicker {R} and/or {G}\n"
        "When this creature enters, if it was kicked with its {R} kicker, "
        "destroy target land.\n"
        "When this creature enters, if it was kicked with its {G} kicker, "
        "destroy target artifact."
    ),
)

_NAYSAY = _mk_card(
    name="W1G2 Naysay", mana_cost="{U}", type_line="Instant",
    oracle_text="Counter target spell if it was kicked.",
)

_LAND = _mk_card(name="W1G2 Field", type_line="Land")
_RELIC = _mk_card(name="W1G2 Relic", type_line="Artifact")


def _w1g2_game(*hand, their_hand=(), theirs=(), mine=(), humans=()) -> Game:
    filler = _mk_card(name="W1G2 Filler", type_line="Land")
    game = Game(players=[
        PlayerState("A", library=[filler] * 10, hand=list(hand)),
        PlayerState("B", library=[filler] * 10, hand=list(their_hand)),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(humans)
    for seat in (0, 1):
        for symbol in "WUBRG":
            game.players[seat].mana_pool[symbol] = 9
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            game._put_permanent_onto_battlefield(seat, Permanent(card=card), None)
    return game


def _w1g2_floating(game) -> int:
    return sum(game.players[0].mana_pool.values())


def _w1g2_cast(game, card, kick=(), **announced):
    result = game.queue_from_hand(
        0, card.name,
        optional_cost_payments={key: 1 for key in kick} or None, **announced,
    )
    assert result.supported, result
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    return next((p for p in game.controlled_by(0) if p.card is card), None)


@pytest.mark.cr("702.33b", "601.2b")
def test_w1g2_702_33b_and_or_is_two_kicker_costs_each_paid_or_not():
    """"Kicker [cost 1] and/or [cost 2]" means "Kicker [cost 1], kicker
    [cost 2]": two optional additional costs. Each combination is a legal
    announcement and charges exactly the costs it takes."""
    assert kicker_costs(_TWINMAGE.oracle_text) == ("{R}", "{1}{U}")
    spent = {}
    for taken in ((), ("{R}",), ("{1}{U}",), ("{R}", "{1}{U}")):
        game = _w1g2_game(_TWINMAGE)
        before = _w1g2_floating(game)
        assert _w1g2_cast(game, _TWINMAGE, kick=taken) is not None
        spent[taken] = before - _w1g2_floating(game)
    assert spent == {
        (): 2, ("{R}",): 3, ("{1}{U}",): 4, ("{R}", "{1}{U}"): 5,
    }


@pytest.mark.cr("702.33b")
def test_w1g2_702_33b_a_pair_this_cannot_tell_apart_is_refused_not_guessed():
    """Two runs spelling one cost would share a key, so "which kicker" has no
    answer; a third cost is a sentence the rule does not define; an {X} in
    either would need an announcement of its own. Each is a card reported
    unsupported for a cost nothing charges — never one cast unkickable."""
    for printed in (
        "Kicker {1}{U} and/or {U}{1}",
        "Kicker {1} and/or {2} and/or {3}",
        "Kicker {X} and/or {2}",
    ):
        card = _mk_card(
            name="W1G2 Misprint", mana_cost="{U}", type_line="Creature - Wizard",
            oracle_text=f"{printed}\nFlying",
        )
        program = compile_card_oracle(card)
        assert not program.supported, printed
        assert "printed cost nothing charges" in program.reason, printed
        assert kicker_costs(card.oracle_text) == (), printed


@pytest.mark.cr("702.33d")
def test_w1g2_702_33d_any_one_kicker_cost_makes_the_spell_kicked():
    """"If a spell's controller declares the intention to pay **any** of that
    spell's kicker costs, that spell has been 'kicked.'" A spell that paid
    only its second cost is countered by "counter target spell if it was
    kicked"; one that paid neither is not."""
    for taken, countered in (
        ((), False), (("{R}",), True), (("{1}{U}",), True),
        (("{R}", "{1}{U}"), True),
    ):
        game = _w1g2_game(_TWINMAGE, their_hand=[_NAYSAY])
        assert game.queue_from_hand(
            0, _TWINMAGE.name,
            optional_cost_payments={key: 1 for key in taken} or None,
        ).supported
        item = game.stack[-1]
        assert kicked(_TWINMAGE, item.choices) is bool(taken)
        assert game.queue_from_hand(
            1, _NAYSAY.name, target_stack_index=len(game.stack) - 1
        ).supported
        resolve_stack(game)
        game.auto_resolve_pending_choices()
        on_board = [p.card.name for p in game.controlled_by(0)]
        assert (on_board == []) is countered, taken
        assert ([c.name for c in game.players[0].graveyard] == [_TWINMAGE.name]) is countered


@pytest.mark.cr("702.33f", "603.4")
def test_w1g2_702_33f_each_linked_trigger_answers_to_its_own_cost():
    """"If it was kicked with its [A] kicker" is linked to that kicker alone:
    paying {R} deals the damage and draws nothing, paying {1}{U} draws and
    deals nothing, and an intervening "if" that is false means the ability
    never triggers (CR 603.4)."""
    outcomes = {}
    for taken in ((), ("{R}",), ("{1}{U}",), ("{R}", "{1}{U}")):
        game = _w1g2_game(_TWINMAGE)
        named = {"target_player_index": 1} if "{R}" in taken else {}
        mage = _w1g2_cast(game, _TWINMAGE, kick=taken, **named)
        assert tuple(mage.metadata.get(KICKED_WITH) or ()) == taken
        assert bool(mage.metadata.get(KICKED)) is bool(taken)
        outcomes[taken] = (game.players[1].life, len(game.players[0].hand))
    assert outcomes == {
        (): (20, 0),
        ("{R}",): (17, 0),
        ("{1}{U}",): (20, 1),
        ("{R}", "{1}{U}"): (17, 1),
    }


@pytest.mark.cr("702.33f", "608.2c")
def test_w1g2_702_33f_a_spell_asks_the_same_two_questions_of_itself():
    """The linked ability on an instant or sorcery reads the resolving spell's
    own record: "if this spell was kicked with its {1}{R} kicker" and "…with
    its {G} kicker" are two branches of one resolution."""
    outcomes = {}
    for taken in ((), ("{1}{R}",), ("{G}",), ("{1}{R}", "{G}")):
        game = _w1g2_game(_TWINSPELL)
        named = {"target_player_index": 1} if "{1}{R}" in taken else {}
        _w1g2_cast(game, _TWINSPELL, kick=taken, **named)
        outcomes[taken] = (
            game.players[0].life, game.players[1].life, len(game.players[0].hand),
        )
    assert outcomes == {
        (): (21, 20, 0),
        ("{1}{R}",): (21, 18, 0),
        ("{G}",): (21, 20, 1),
        ("{1}{R}", "{G}"): (21, 18, 1),
    }


@pytest.mark.cr("702.33f")
def test_w1g2_702_33f_a_question_about_a_cost_the_card_does_not_list_is_refused():
    """The ability is linked to one of "the first and second kicker costs
    listed on the card". A sentence naming any other cost can never be true,
    so the card is unsupported rather than supported with a trigger that never
    fires. The comparison is of costs, not spellings: {U}{1} is {1}{U}."""
    def card(question: str):
        return _mk_card(
            name="W1G2 Stranger", mana_cost="{U}", type_line="Creature - Wizard",
            oracle_text=(
                "Kicker {1}{G} and/or {1}{U}\n"
                f"When this creature enters, if it was kicked with its "
                f"{question} kicker, draw a card."
            ),
        )

    stranger = card("{5}")
    assert unlinked_kicker_question(stranger.oracle_text) == "{5}"
    program = compile_card_oracle(stranger)
    assert not program.supported
    assert "kicker cost this card does not print" in program.reason

    for listed in ("{1}{G}", "{1}{U}", "{U}{1}"):
        assert unlinked_kicker_question(card(listed).oracle_text) is None
        assert compile_card_oracle(card(listed)).supported, listed


@pytest.mark.cr("702.33g", "601.2c")
def test_w1g2_702_33g_a_target_is_chosen_only_for_the_kicker_that_buys_it():
    """"…the spell's controller chooses those targets only if that spell was
    kicked" — with two kickers, only if it was kicked with the one whose
    ability has the target. The picker asks for a target under {1}{R} and for
    none under {G} or under nothing."""
    game = _w1g2_game(_TWINSPELL)
    kinds = {
        taken: game.cast_target_spec(
            0, _TWINSPELL, optional_cost_payments={key: 1 for key in taken}
        )["kind"]
        for taken in ((), ("{1}{R}",), ("{G}",), ("{1}{R}", "{G}"))
    }
    assert kinds == {
        (): "none", ("{1}{R}",): "any", ("{G}",): "none", ("{1}{R}", "{G}"): "any",
    }


@pytest.mark.cr("603.3d", "601.2c")
def test_w1g2_603_3d_two_kicked_triggers_each_choose_their_own_target():
    """Two triggered abilities are two objects on the stack, each choosing its
    own target as it is put there. A cast that named the first trigger's land
    does not hand it to the second: "destroy target artifact" asks for an
    artifact, and nothing is destroyed until it is answered — nor, both being
    on the stack (CR 603.3), until each resolves, the first printed first."""
    game = _w1g2_game(
        _TWINBLADE, theirs=[_LAND, _RELIC], mine=[_RELIC], humans=(0,)
    )
    land, their_relic = game.controlled_by(1)
    (my_relic,) = game.controlled_by(0)
    assert game.queue_from_hand(
        0, _TWINBLADE.name, optional_cost_payments={"{R}": 1, "{G}": 1},
        target_permanent_ids=[land.permanent_id],
    ).supported
    assert game.resolve_top_of_stack()

    assert len(game.stack) == 2 and all(item.is_ability for item in game.stack)
    assert game.is_on_battlefield(land), "its trigger is on the stack, unresolved"
    assert game.is_on_battlefield(their_relic) and game.is_on_battlefield(my_relic)
    (asked,) = game.pending_choices
    assert asked.kind == "trigger_target"
    assert sorted(t["permanent_id"] for t in asked.data["targets"]) == sorted(
        [their_relic.permanent_id, my_relic.permanent_id]
    )
    assert game.confirm_trigger_target(0, permanent_id=their_relic.permanent_id)

    assert game.resolve_top_of_stack()
    assert not game.is_on_battlefield(land)
    assert game.is_on_battlefield(their_relic) and game.is_on_battlefield(my_relic)

    resolve_stack(game)
    assert not game.is_on_battlefield(their_relic)
    assert game.is_on_battlefield(my_relic)


@pytest.mark.cr("400.7", "702.33d")
def test_w1g2_400_7_a_permanent_nothing_cast_was_kicked_with_nothing():
    """A permanent put onto the battlefield without being cast is a new object
    with no cast behind it: neither linked trigger triggers."""
    game = _w1g2_game()
    mage = Permanent(card=_TWINMAGE)
    game._put_permanent_onto_battlefield(0, mage, None)
    assert not mage.metadata.get(KICKED) and not mage.metadata.get(KICKED_WITH)
    assert game.stack == [] and game.pending_choices == []
    assert (game.players[1].life, len(game.players[0].hand)) == (20, 0)
