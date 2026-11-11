"""Census: a card dealing damage reads the keywords it prints.

Judgment's wave 1 (W1G3) measured Selfless Exorcist — "{T}: Exile target
creature card from a graveyard. That card deals damage equal to its power to
this creature." — with an exiled lifelink or deathtouch creature card: the
card's owner gained nothing (CR 702.15b: "Damage dealt by a source with
lifelink causes that source's controller, or its owner if it has no
controller, to gain that much life") and the Exorcist was not destroyed
(CR 702.2b: "a creature … that's been dealt damage by a source with
deathtouch … is destroyed"). Both checks read a keyword off a *permanent*,
and a card in exile — like a spell on the stack — reaches the damage paths as
its bare ``CardDefinition``, so both answered no for every one of them. And
the event said the damage was the Exorcist's controller's (the seat
resolving the ability) where CR 108.4a makes a card with no controller its
owner's.

The census is every creature card in the pool (both manifest roles) that
prints lifelink or deathtouch — ten today, no instant or sorcery prints
either — each exiled from its owner's graveyard by an Exorcist across the
table. On the base none gained, none destroyed, and every event named the
Exorcist's seat.
"""

from __future__ import annotations

import engine.mixins.effects as effects_module
from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.models import Permanent
from tests.helpers import resolve_stack


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            pool.setdefault(card.name, card)
    return pool


_POOL = _pool()

#: How many cards the census must examine. Ten at the time of writing (eight
#: lifelink, two deathtouch, all creatures).
_FLOOR = 10


def _prints(card, keyword: str) -> bool:
    return any(str(word).lower() == keyword for word in (card.keywords or ()))


def _subjects() -> list:
    return sorted(
        (
            card for card in _POOL.values()
            if "Creature" in card.type_line
            and (_prints(card, "lifelink") or _prints(card, "deathtouch"))
        ),
        key=lambda card: card.name,
    )


def _exorcise(card, monkeypatch):
    """The Exorcist (seat 0) exiles *card* out of seat 1's graveyard. Returns
    the game, the Exorcist and the ``source_seat`` of every damage event."""
    seats: list = []
    real = effects_module.deal_damage

    def recording(game, event, *args, **kwargs):
        outcome = real(game, event, *args, **kwargs)
        if event.get("source") is card:
            seats.append(event.get("source_seat"))
        return outcome

    monkeypatch.setattr(effects_module, "deal_damage", recording)
    game = Game(players=[
        PlayerState("Exorcist", library=[_POOL["Plains"]] * 5),
        PlayerState("Owner", library=[_POOL["Island"]] * 5, graveyard=[card]),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    exorcist = Permanent(card=_POOL["Selfless Exorcist"])
    game._put_permanent_onto_battlefield(0, exorcist, None)
    exorcist.metadata["summoning_sickness_turn"] = -99
    resolve_stack(game)
    result = game.activate_permanent_ability(
        0, "Selfless Exorcist", target_player_index=1, target_graveyard_indices=[0],
    )
    assert result.supported, result.details
    resolve_stack(game)
    game.check_state_based_actions()
    return game, exorcist, seats


def test_a_card_dealing_damage_has_the_keywords_it_prints(monkeypatch):
    subjects = _subjects()
    assert len(subjects) >= _FLOOR, [card.name for card in subjects]
    wrong = []
    for card in subjects:
        game, exorcist, seats = _exorcise(card, monkeypatch)
        owner = game.players[1]
        power = int(card.power or 0)
        assert [c.name for c in owner.exile] == [card.name], card.name
        if seats != [1]:
            wrong.append(f"{card.name}: the damage was seat {seats}'s, not its owner's (CR 108.4a)")
        if _prints(card, "lifelink") and owner.life != 20 + power:
            wrong.append(f"{card.name}: its owner is at {owner.life}, not {20 + power} (CR 702.15b)")
        if _prints(card, "deathtouch") and power > 0 and game.is_on_battlefield(exorcist):
            wrong.append(f"{card.name}: the Exorcist survived {power} deathtouch damage (CR 702.2b)")
        if not _prints(card, "lifelink") and owner.life != 20:
            wrong.append(f"{card.name}: its owner's life moved without lifelink")
    assert not wrong, "\n".join(wrong)


def test_a_card_without_the_keywords_changes_nothing(monkeypatch):
    """The other direction: a vanilla creature card's damage gains nobody
    anything and destroys only what its amount destroys."""
    game, exorcist, seats = _exorcise(_POOL["Grizzly Bears"], monkeypatch)
    assert seats == [1]
    assert [p.life for p in game.players] == [20, 20]
    assert game.is_on_battlefield(exorcist) and exorcist.damage_marked == 2
