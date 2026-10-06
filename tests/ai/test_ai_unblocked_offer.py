"""A seat nobody asks answers "as though it weren't blocked" on its merits.

"You may have this creature assign its combat damage as though it weren't
blocked." (Lone Wolf, Thorn Elemental, Rhox, Pride of Lions; Garruk, Savage
Herald's −7 grants it.) A person at the table has been able to give either
answer since the round before this one. Every seat that is *not* asked — an AI
seat, a headless game — took the offer, always: the default was a constant,
supplied at three places (`advance_combat_phase`'s auto-resolve,
`ai_combat.run_ai_combat_phase`, the web layer's `_ai_assign_combat_damage`).
So a Thorn Elemental walked past the Grizzly Bears in front of it for seven of
a healthy opponent's twenty life, and the Bears lived to block it again.

One function answers at all three now
(`ai_combat.choose_combat_damage_assignment`): the damage stays on the
blockers where one of them would die and the player would not, or where the
damage would not reach the player at all; it goes past them where it ends the
game, and otherwise — the stated default it always was.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_combat import choose_combat_damage_assignment, run_ai_combat_phase
from engine.card_loader import load_cards, manifest_set_paths
from engine.combat_assignment import AS_THOUGH_UNBLOCKED_LOG, MAY_ASSIGN_AS_UNBLOCKED
from engine.faces import compilation_units
from engine.handlers.prevention import apply_prevention_shield
from engine.models import Permanent
from tests.helpers import _mk_creature_card

OFFER = "you may have this creature assign its combat damage as though it weren't blocked"

_POOL: dict = {}
for _card in load_cards(manifest_set_paths(include_measured=True)):
    _POOL.setdefault(_card.name, _card)


def _offered_cards() -> list:
    """Every card in the pool printing the sentence."""
    return sorted(
        (
            card for card in compilation_units(_POOL.values())
            if card.primary_type == "creature" and any(
                line.strip().lower().rstrip(".") == OFFER
                for line in (card.oracle_text or "").splitlines()
            )
        ),
        key=lambda card: card.name,
    )


def _granted():
    """An ordinary creature under Garruk's grant: the offer as a mark."""
    return _mk_creature_card("Granted Beast", 4, 4)


def _combat(attacker_card, blockers, *, life: int = 40, shield: int = 0, granted=False):
    """*attacker_card* attacking for seat 0 into *blockers* (``(power,
    toughness)`` each), neither seat interactive, stopped at the last point a
    declaration is owed: blocks declared, combat damage not yet entered."""
    game = Game(players=[PlayerState(name="Me"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[0].life = 40
    game.players[1].life = life
    attacker = Permanent(card=attacker_card)
    game._put_permanent_onto_battlefield(0, attacker, None)
    attacker.metadata["summoning_sickness_turn"] = -99
    if granted:
        attacker.metadata[MAY_ASSIGN_AS_UNBLOCKED] = True
    walls = []
    for number, (power, toughness) in enumerate(blockers):
        wall = Permanent(card=_mk_creature_card(f"Blocker {number}", power, toughness))
        game._put_permanent_onto_battlefield(1, wall, None)
        walls.append(wall)
    if shield:
        apply_prevention_shield(game, game.players[1], None, shield)
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    ok, why = game.declare_attackers(0, [0], defending_player_index=1)
    assert ok, (attacker_card.name, why)
    game.advance_combat_phase()
    ok, why = game.declare_blockers(1, {slot: 0 for slot in range(len(blockers))})
    assert ok, (attacker_card.name, why)
    return game, attacker, walls


def _finish(game, site: str) -> None:
    """Deal the damage through one of the default sites."""
    if site == "engine":
        # One blocker: `advance_combat_phase` resolves the step as it enters it.
        game.advance_combat_phase()
    else:
        # Two blockers: the engine stops for a division, and the driver the
        # simulator runs supplies it.
        run_ai_combat_phase(game, 0)
    assert game.combat_damage_resolved or game.current_turn_phase != "combat"


def _took_the_offer(game) -> bool:
    return any(AS_THOUGH_UNBLOCKED_LOG in line for line in game.log)


#: ``(blockers, defender's life as a multiple of the attacker's power, a
#: shield on the defender?) -> is the offer taken``. Written out by hand: this
#: is the valuation, stated, and the census holds every default to it.
_SCENARIOS = {
    "a blocker that would die, a player who would not": ("dies", 10, False, False),
    "a blocker that would live": ("lives", 10, False, True),
    "lethal to the player": ("dies", 1, False, True),
    "damage the player is shielded from": ("lives", 10, True, False),
}


def _population():
    return [(card, False) for card in _offered_cards()] + [(_granted(), True)]


@pytest.mark.parametrize("site", ["engine", "driver"])
def test_every_default_answers_the_offer_as_the_valuation_says(site):
    """Every card with the offer (and a creature it is granted to) through
    each scenario, at the engine's own auto-resolve (one blocker) and at the
    simulator's driver (two). Before: the offer taken in all of them — the two
    declining scenarios wrong for every card at every site."""
    examined, wrong = 0, []
    cards = _population()
    assert len(cards) >= 4, [card.name for card, _ in cards]
    for card, granted in cards:
        power = int(card.raw.get("power") or 0)
        assert power > 0, card.name
        for label, (fate, lives, shielded, taken) in _SCENARIOS.items():
            toughness = 1 if fate == "dies" else 99
            blockers = [(0, toughness)] if site == "engine" else [(0, toughness), (0, 99)]
            life = power * lives
            game, attacker, walls = _combat(
                card, blockers, life=life, shield=power if shielded else 0, granted=granted,
            )
            _finish(game, site)
            examined += 1
            got = _took_the_offer(game)
            if got != taken:
                wrong.append((card.name, label, "taken" if got else "declined"))
                continue
            defender = game.players[1]
            if taken:
                assert defender.life == life - power, (card.name, label)
                assert all(wall.damage_marked == 0 for wall in walls if game.is_on_battlefield(wall))
            else:
                assert defender.life == life, (card.name, label, game.log[-6:])
                if fate == "dies":
                    assert not game.is_on_battlefield(walls[0]), (card.name, label)
                    assert any(c.name == "Blocker 0" for c in defender.graveyard)
                else:
                    assert walls[0].damage_marked > 0, (card.name, label)
    assert wrong == [], wrong
    assert examined >= 16, examined


def test_the_announcement_names_the_answer_it_gives():
    """Taken, the creature is named by id (`as_though_unblocked`); declined, it
    has a division among its blockers and is not named — the two answers the
    engine's API has, rather than an absence read as a yes."""
    card = _mk_creature_card("Slipping Beast", 5, 5, OFFER.capitalize() + ".")
    game, beast, _ = _combat(card, [(1, 9)])
    game._set_phase_and_step("combat", "combat_damage")
    division, named = choose_combat_damage_assignment(game)
    assert named == [beast.permanent_id] and 0 not in division

    game, beast, (wall,) = _combat(card, [(1, 4)])
    game._set_phase_and_step("combat", "combat_damage")
    division, named = choose_combat_damage_assignment(game)
    assert named == [] and division == {0: {0: 5}}
    assert any("keeps its combat damage on the creatures blocking it" in line for line in game.log)


def test_unblocked_attackers_beside_it_count_toward_lethal():
    """Five more from an unblocked attacker and the beast's five are the
    defender's ten life: it goes past its blocker, though the blocker would
    die and five alone would not kill."""
    card = _mk_creature_card("Slipping Beast", 5, 5, OFFER.capitalize() + ".")
    game = Game(players=[PlayerState(name="Me"), PlayerState(name="Opp")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.players[1].life = 10
    for attacker_card in (card, _mk_creature_card("Plain Bear", 5, 5)):
        attacker = Permanent(card=attacker_card)
        game._put_permanent_onto_battlefield(0, attacker, None)
        attacker.metadata["summoning_sickness_turn"] = -99
    wall = Permanent(card=_mk_creature_card("Blocker", 0, 1))
    game._put_permanent_onto_battlefield(1, wall, None)
    game.active_player_index = 0
    for _ in range(4):
        game.advance_combat_phase()
        if game.current_step == "declare_attackers":
            break
    assert game.declare_attackers(0, [0, 1], defending_player_index=1)[0]
    game.advance_combat_phase()
    assert game.declare_blockers(1, {0: 0})[0]
    game.advance_combat_phase()

    assert game.players[1].life == 0, game.log[-6:]
    assert game.is_on_battlefield(wall) and wall.damage_marked == 0
