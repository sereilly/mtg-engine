"""A graveyard return's payment spares what the card it brings back wants
(``mana_wants.bringing_back``, set by ``ai_graveyard_activations._candidate``).

"{3}{W}{W}: Return this card from your graveyard to your hand. Activate only
during your upkeep." (Eternal Dragon.) While the payment is planned the card
is in the graveyard, where no want reads it, so the plan paid the generic
part with Plains too: four Plains and an Island tapped, seven Islands left,
and the Dragon it had just bought back uncastable. Hammer of Bogardan's
{2}{R}{R}{R} return left no Mountain for its {1}{R}{R}.
"""

from __future__ import annotations

from functools import lru_cache

from engine import faces
from engine.ai_graveyard_activations import (_candidate, _returns_its_card_to,
                                             activate_chosen_graveyard_ability,
                                             choose_graveyard_activation_action,
                                             graveyard_abilities)
from engine.ai_policy import choose_cast_action
from engine.board_payment import board_can_pay
from engine.card_loader import load_catalog
from engine.game import Game
from engine.mana_payment import mana_cost_from_symbols
from engine.models import Permanent, PlayerState

from tests.helpers import _nosick, settle

_BASIC = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _table(graveyard: str, lands: list[str], hand=()) -> Game:
    catalog = _catalog()
    game = Game(players=[
        PlayerState(name="A", graveyard=[catalog[graveyard]], hand=[catalog[n] for n in hand],
                    library=[catalog["Island"]] * 10),
        PlayerState(name="B", library=[catalog["Island"]] * 10),
    ])
    game.enforce_mana_costs = True
    for name in lands:
        permanent = Permanent(card=catalog[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game.start_turn(0)
    settle(game)
    game._set_phase_and_step("beginning", "upkeep")
    return game


def _returners_to_hand() -> list:
    """Every shipped card with a mana-costed ability that returns it from its
    graveyard to its hand, with that ability's cost: ``(card, cost)``."""
    found = []
    cards = sorted(_catalog().values(), key=lambda each: each.name)
    probe = _table("Island", [])
    for unit in faces.compilation_units(cards):
        probe.players[0].graveyard = [unit]
        for _index, card, _ability_index, ability in graveyard_abilities(probe, 0):
            mana = {k: v for k, v in dict(ability.cost.mana).items() if v}
            if mana and _returns_its_card_to(ability) == "hand":
                found.append((card, mana))
    return found


def _lands_for(return_cost: dict, cast_cost: dict) -> "list[str] | None":
    """The basics of the card's colours its two costs' pips need, first (where
    the planner's board order reaches for them first), then an off-colour
    basic for each generic: a board that pays both only if the return's
    generic goes on the off-colour lands."""
    colours = {s for s in (*return_cost, *cast_cost) if s in _BASIC}
    off = next((symbol for symbol in "UBGWR" if symbol not in colours), None)
    if off is None or set(return_cost) - set(_BASIC) - {"generic"}:
        return None
    lands = [
        _BASIC[symbol]
        for symbol in sorted(colours)
        for _ in range(int(return_cost.get(symbol, 0)) + int(cast_cost.get(symbol, 0)))
    ]
    generic = int(return_cost.get("generic", 0)) + int(cast_cost.get("generic", 0))
    return lands + [_BASIC[off]] * generic


def test_every_return_to_hand_is_paid_so_the_card_can_be_cast_after():
    """The census: every shipped card whose graveyard ability returns it to
    the hand for mana, on a board that can pay the return and then cast the
    card only if the return's generic is paid off-colour — the chosen plan
    leaves the card castable. Validated backwards: on 59f133e63 Eternal
    Dragon, Hammer of Bogardan and Undead Gladiator were left uncastable."""
    returners = _returners_to_hand()
    assert len(returners) >= 4, [card.name for card, _cost in returners]
    weighed, stranded = 0, []
    for card, cost in returners:
        cast = mana_cost_from_symbols(card.mana_cost or "") or {}
        lands = _lands_for(cost, cast)
        if lands is None:
            continue
        game = _table(card.name, lands, hand=["Grizzly Bears"])
        entries = [entry for entry in graveyard_abilities(game, 0) if _returns_its_card_to(entry[3]) == "hand"]
        index, held, ability_index, ability = entries[0]
        candidate = _candidate(game, 0, index, held, ability_index, ability, lasting_only=False)
        if candidate is None:
            continue
        weighed += 1
        activate_chosen_graveyard_ability(game, 0, candidate)
        settle(game)
        assert any(c.name == card.name for c in game.players[0].hand), card.name
        if not board_can_pay(game, 0, cast):
            stranded.append(card.name)
    assert weighed >= 3, weighed
    assert stranded == []


def test_eternal_dragon_is_returned_in_the_upkeep_and_cast_that_turn():
    """The board the Known-gaps entry names, driven: four Plains and eight
    Islands, Eternal Dragon in the graveyard. The upkeep's chooser returns it
    paying {3}{W}{W} with two Plains and three Islands, and the main phase's
    cast chooser casts it from the seven lands left."""
    game = _table("Eternal Dragon", ["Plains"] * 4 + ["Island"] * 8)
    action = choose_graveyard_activation_action(game, 0)
    assert action is not None and action.card_name == "Eternal Dragon"
    activate_chosen_graveyard_ability(game, 0, action)
    settle(game)
    assert [c.name for c in game.players[0].hand] == ["Eternal Dragon"]
    untapped = sorted(p.card.name for p in game.controlled_by(game.players[0]) if not p.tapped)
    assert untapped.count("Plains") == 2 and untapped.count("Island") == 5
    game._set_phase_and_step("precombat_main", "precombat_main")
    cast = choose_cast_action(game, 0)
    assert cast is not None and cast.card_name == "Eternal Dragon"
