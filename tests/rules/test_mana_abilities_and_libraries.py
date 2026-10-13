"""CR 605.1a's fourth criterion: an ability that moves a card to or from a
library is not a mana ability.

    605.1a An activated ability is a mana ability if it meets all of the
    following criteria: it doesn't require a target (see rule 115.6), it could
    add mana to a player's mana pool when it resolves, it's not a loyalty
    ability (see rule 606, "Loyalty Abilities"), and its cost and effect don't
    move any card to or from a library. Do not take into account replacement
    effects that may apply, other than self-replacement effects, when
    evaluating these criteria.

In the rules since the September 25, 2026 edition. Chromatic Sphere's ruling
of 2026-08-05 states the consequence: "Chromatic Sphere's ability is not a
mana ability. Players can respond to it, and it can't be activated in the
middle of paying for a cost."

Asked on invented cards as well as printed ones, because the criterion is
about what an ability *does* and the pool prints only three of the shapes it
reaches (a mill cost, a draw, a delayed draw). The pool-wide guard is
``tests/engine/test_mana_ability_library_criterion.py``; the wire's half -
that a payment prompt admits a mana ability and not one of these - is
``tests/ui/test_pay_prompt_refusal_ui_api.py``.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.mana_payment import is_mana_ability
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _mk_card


def _only_ability(text: str):
    card = _mk_card(name="Probe Stone", mana_cost="{1}", type_line="Artifact", oracle_text=text)
    program = compile_card_oracle(card)
    assert program.supported, program.reason
    (ability,) = program.activated_abilities
    return ability


def _pool(game, seat: int = 0) -> dict:
    return {symbol: count for symbol, count in game.players[seat].mana_pool.items() if count}


def _table(catalog_by_name, *cards):
    forest = catalog_by_name["Forest"]
    game = Game(players=[
        PlayerState("Caster", library=[forest] * 10),
        PlayerState("Bystander", library=[forest] * 10),
    ])
    game.enforce_mana_costs = True
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    permanents = []
    for name in cards:
        permanent = Permanent(card=catalog_by_name[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        permanents.append(permanent)
    return game, permanents


@pytest.mark.cr("605.1a")
@pytest.mark.parametrize("text", [
    "{T}, Mill a card: Add {C}.",
    "{T}, Exile the top card of your library: Add {C}.",
    "{T}, Put a card from your hand on top of your library: Add {G}.",
])
def test_605_1a_a_cost_that_moves_a_library_card_is_no_mana_abilitys(text):
    """From a library (milled, exiled off the top) or to one (a card put on
    top): either way the cost moves a card the rule names."""
    assert not is_mana_ability(_only_ability(text))


@pytest.mark.cr("605.1a")
@pytest.mark.parametrize("text", [
    "{T}: Add {G}. Draw a card.",
    "{T}: Add {G}. Mill a card.",
])
def test_605_1a_an_effect_that_moves_a_library_card_is_no_mana_abilitys(text):
    assert not is_mana_ability(_only_ability(text))


@pytest.mark.cr("605.1a")
@pytest.mark.parametrize("text", [
    "{T}: Add {G}.",
    "{T}: Add {C}{C}.",
    "{T}, Pay 1 life: Add {B}.",
    "{T}, Sacrifice this artifact: Add one mana of any color.",
])
def test_605_1a_the_other_three_criteria_still_make_a_mana_ability(text):
    """The control arm: nothing here goes near a library."""
    assert is_mana_ability(_only_ability(text))


@pytest.mark.cr("605.1a", "603.7")
def test_605_1a_a_draw_at_a_later_time_is_another_abilitys_draw(catalog_by_name):
    """"Add one mana of any color. Draw a card **at the beginning of the next
    turn's upkeep**." (Barbed Sextant, Astrolabe.) CR 603.7: "An effect may
    create a delayed triggered ability that can do something at a later time" -
    and it is that ability, resolving on its own a turn later, that draws. The
    cost and the effect of the Sextant's ability move no card, so it is a mana
    ability, and it resolves at once with a spell waiting on the stack."""
    for name in ("Barbed Sextant", "Astrolabe"):
        (ability,) = compile_card_oracle(catalog_by_name[name]).activated_abilities
        assert is_mana_ability(ability), name
    assert is_mana_ability(
        _only_ability("{T}: Add {G}. Draw a card at the beginning of the next turn's upkeep.")
    )

    game, (sextant,) = _table(catalog_by_name, "Barbed Sextant")
    game.players[0].mana_pool.update({"C": 1, "R": 1})
    game.players[0].hand.append(catalog_by_name["Lightning Bolt"])
    assert game.queue_from_hand(0, "Lightning Bolt", target_player_index=1).supported

    result = game.queue_permanent_ability(0, "Barbed Sextant", ability_index=0, mana_color="U")

    assert result.supported and result.details == "resolved"
    assert len(game.stack) == 1, "the Bolt alone: a mana ability does not use the stack"
    assert _pool(game) == {"U": 1}
    assert not game.is_on_battlefield(sextant)
    assert len(game.players[0].library) == 10, "nothing is drawn until the next upkeep"


@pytest.mark.cr("605.1a", "605.3b")
def test_605_1a_chromatic_sphere_uses_the_stack_and_can_be_answered(catalog_by_name):
    """"{1}, {T}, Sacrifice this artifact: Add one mana of any color. Draw a
    card." The same sentence as the Sextant's but for *when* the card is
    drawn, and that is the whole difference: this effect moves a card from a
    library as it resolves. So it goes on the stack - CR 605.3b's "doesn't go
    on the stack" is a mana ability's - the opponent may respond before any
    mana exists, and the mana and the card arrive together."""
    (ability,) = compile_card_oracle(catalog_by_name["Chromatic Sphere"]).activated_abilities
    assert not is_mana_ability(ability)

    game, (sphere,) = _table(catalog_by_name, "Chromatic Sphere")
    game.players[0].mana_pool.update({"C": 1})

    result = game.queue_permanent_ability(0, "Chromatic Sphere", ability_index=0, mana_color="U")

    assert result.supported and result.details == "queued"
    assert len(game.stack) == 1 and game.stack[-1].source_permanent is sphere
    # The cost is paid - {1}, tapped, sacrificed - and nothing has been made.
    assert not game.is_on_battlefield(sphere)
    assert _pool(game) == {}
    assert len(game.players[0].library) == 10 and game.players[0].hand == []

    # A response resolves first, with the Sphere's ability still waiting.
    game.players[1].hand.append(catalog_by_name["Lightning Bolt"])
    game.players[1].mana_pool.update({"R": 1})
    assert game.queue_from_hand(1, "Lightning Bolt", target_player_index=0).supported
    game.resolve_top_of_stack()
    assert game.players[0].life == 17 and len(game.stack) == 1 and _pool(game) == {}

    game.resolve_top_of_stack()
    assert _pool(game) == {"U": 1}
    assert len(game.players[0].hand) == 1 and len(game.players[0].library) == 9
