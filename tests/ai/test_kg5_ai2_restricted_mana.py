"""A non-land mana source whose mana is restricted (CR 106.6) is planned for
the payments it may make.

"{T}: Add {C}. Spend this mana only to cast an instant or sorcery spell."
(Vodalian Arcanist); "{T}: Add {C}{C}. Spend this mana only to activate
abilities of artifacts." (Soldevi Machinist.) ``ai_valuation.
planned_mana_yield`` refused any add-mana payload carrying ``spend_only``, so
the payment planner (``ai_payment._PaymentPlanner``, the AI's and the web
auto-tap's) never counted these sources: kg5's ``aicast`` measured Mana Leak
off an Island and an Arcanist as unaffordable. The land half had read a
restriction against what the payment is for since Mishra's Workshop
(``board_payment.land_tap_yields``); the non-land half now does the same —
the yield carries its restriction (``ManaYield.spend_only``) and the planner
keeps such a source only where ``restricted_mana.restriction_admits`` the
payment's purpose. Every other reader of a yield refuses a restricted one.
"""

from __future__ import annotations

from functools import lru_cache

import pytest

from engine import Game, PlayerState, faces
from engine.ai_abilities import choose_activation_action
from engine.ai_actions import activation_announcement
from engine.ai_mana_sources import _nonland_mana_source
from engine.ai_payment import _PaymentPlanner, _paying_for, tap_planned_lands
from engine.ai_policy import cast_chosen_instant, choose_cast_action
from engine.ai_valuation import planned_mana_yield
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.restricted_mana import ACTIVATE, CAST, PaymentPurpose, restriction_admits
from tests.helpers import _nosick, settle
from web.payment_plan import planned_taps


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _seat(hand=(), *, mine=(), theirs=()) -> Game:
    cards = _catalog()
    game = Game(players=[
        PlayerState(name="A", hand=[cards[n] for n in hand], library=[cards["Island"]] * 10),
        PlayerState(name="B", library=[cards["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=cards[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game.start_turn(0)
    game._settle()
    return game


def _restricted_sources() -> list:
    """Every shipped non-land permanent with a mana ability whose yield the
    planner can state and whose mana is restricted."""
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        if "Land" in (unit.type_line or "") or unit.name not in _catalog():
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        for ability in program.activated_abilities:
            produced = planned_mana_yield(ability.instruction) if ability.instruction else None
            if produced is not None and produced.spend_only:
                found.append((unit, produced))
                break
    return found


#: Payments of every kind the pool's restrictions name, each by the card or
#: the permanent it is for.
_PURPOSES = (
    ("cast", "Impulse"), ("cast", "Lightning Bolt"), ("cast", "Grizzly Bears"),
    ("cast", "Ornithopter"), ("activate", "Rod of Ruin"), ("activate", "Prodigal Sorcerer"),
)


def test_every_restricted_source_is_planned_for_the_payments_it_may_make():
    """Each restricted source alone on its seat's battlefield (beside the
    permanents an activation is for): its yield is planned for a payment of
    every purpose its restriction admits (the engine's own
    ``restriction_admits``) and for none it does not."""
    sources = _restricted_sources()
    names = {unit.name for unit, _produced in sources}
    assert {"Vodalian Arcanist", "Soldevi Machinist"} <= names, sorted(names)
    rows, wrong = 0, []
    for unit, produced in sources:
        for kind, name in _PURPOSES:
            game = _seat(mine=[unit.name, *(["Rod of Ruin", "Prodigal Sorcerer"] if kind == "activate" else [])])
            player = game.players[0]
            if _nonland_mana_source(game, 0, next(
                p for p in game.controlled_by(0) if p.card.name == unit.name
            ), may_sacrifice=True) is None:
                continue
            required = {"generic": produced.amount}
            if kind == "cast":
                purpose = PaymentPurpose(CAST, card=_catalog()[name])
                with _paying_for(_catalog()[name]):
                    plan = _PaymentPlanner(game, player).plan(required)
            else:
                paid = next(p for p in game.controlled_by(0) if p.card.name == name)
                purpose = PaymentPurpose(ACTIVATE, source=paid)
                plan = _PaymentPlanner(game, player, paying_for=paid).plan(required)
            rows += 1
            if bool(plan and plan[0]) != restriction_admits(produced.spend_only, purpose):
                wrong.append((unit.name, kind, name, plan))
    assert rows >= 10, rows
    assert not wrong, wrong


def test_an_instant_is_cast_off_an_island_and_an_arcanist():
    """aicast's board, an instant of {1}{U} for Mana Leak: Impulse with an
    Island and a Vodalian Arcanist. The plan taps both, the Arcanist's {C} goes
    into its own bucket and the cast spends it from there. On the base the
    Arcanist was never counted and the seat cast nothing."""
    game = _seat(["Impulse"], mine=["Island", "Vodalian Arcanist"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Impulse", action
    _card, result = cast_chosen_instant(game, 0, action)
    assert result.supported, result.details
    settle(game)
    assert "Impulse" in [card.name for card in game.players[0].graveyard], game.log[-6:]
    assert any("spendable only on instant_or_sorcery" in line for line in game.log)
    assert all(p.tapped for p in game.controlled_by(0)), "both sources paid"


def test_a_creature_is_not_paid_for_with_the_arcanist():
    """The restriction holds the other way: Grizzly Bears off a Forest and the
    Arcanist is not a cast the plan can make."""
    game = _seat(["Grizzly Bears"], mine=["Forest", "Vodalian Arcanist"])
    assert choose_cast_action(game, 0) is None
    with _paying_for(_catalog()["Grizzly Bears"]):
        assert _PaymentPlanner(game, game.players[0]).plan({"generic": 1, "G": 1}) is None


def test_an_artifact_ability_is_activated_off_a_soldevi_machinist():
    """Rod of Ruin's "{3}, {T}: This artifact deals 1 damage to any target",
    paid with Soldevi Machinist's {C}{C} and an Island: the activation chooser
    plans the Machinist, the executor taps it, and the Rod's ability spends
    the artifact-only mana."""
    game = _seat(mine=["Island", "Soldevi Machinist", "Rod of Ruin"])
    action = choose_activation_action(game, 0)
    assert action is not None and action.permanent_name == "Rod of Ruin", action
    action = tap_planned_lands(game, 0, action)
    result = game.activate_permanent_ability(
        0, action.permanent_name, **activation_announcement(action),
    )
    assert result.supported, result
    settle(game)
    assert game.players[1].life == 19, game.log[-6:]


@pytest.mark.parametrize("spell, planned", [("Impulse", True), ("Grizzly Bears", False)])
def test_the_web_auto_tap_plans_the_arcanist_for_what_it_may_pay(spell, planned):
    """A person's auto-tap asks the same planner with the payment's own
    purpose (``web/payment_plan.planned_taps``)."""
    lands = ["Island"] if spell == "Impulse" else ["Forest"]
    game = _seat(mine=[*lands, "Vodalian Arcanist"])
    colour = "U" if spell == "Impulse" else "G"
    found = planned_taps(
        game, 0, {"generic": 1, colour: 1}, PaymentPurpose(CAST, card=_catalog()[spell]),
    )
    assert bool(found) is planned, found
    if planned:
        arcanist = next(
            slot for slot, p in enumerate(game.controlled_by(0)) if p.card.name == "Vodalian Arcanist"
        )
        assert arcanist in found[0]
