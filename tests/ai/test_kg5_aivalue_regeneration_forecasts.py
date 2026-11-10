"""The combat forecasts read a regeneration as a regeneration, not as
indestructible (CR 701.19a, CR 506.4).

A creature that regenerates is tapped, its damage removed, and **removed from
combat** — so a shielded creature that first-strike damage would destroy deals
no regular damage, and the creature it fought assigns it none (CR 510.1c-d).
The engine has played that since `regeneration._apply` learned the third
sentence; the AI's three fight readers (``ai_compelled_blocks.fight_outcome``,
``ai_declarations._kills_back`` / ``_gang_kills``) read a shield as
indestructible, so a shielded blocker "killed" the first striker it was
blocking (and nobody joined the block that would have), and a first striker
"died" blocking a shielded attacker (and stayed home).

The census fights every shipped creature that raises a shield on itself
against a first striker sized so the shield decides it, in both seats, and
holds the forecast to what the engine's combat does.
"""

from __future__ import annotations

from functools import lru_cache

from engine.ai_combat import run_ai_combat_phase
from engine.ai_compelled_blocks import (REGENERATES, STAYS, fight_outcome,
                                        survives_destruction)
from engine.ai_declarations import _gang_kills, _kills_back, choose_combat_blockers
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.regeneration import CANT_BE_REGENERATED

from tests.helpers import (_mk_creature_card, _nosick, drive_combat,
                           settle, stock_libraries)


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _card(name):
    return _catalog()[name]


def _table(mine=(), theirs=()):
    game = Game(players=[PlayerState(name="A"), PlayerState(name="B")])
    game.enforce_mana_costs = False
    stock_libraries(game)
    placed = []
    for seat, cards in ((0, mine), (1, theirs)):
        for card in cards:
            permanent = Permanent(card=card)
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
            placed.append(permanent)
    game.check_state_based_actions()
    return game, placed


def _raise_shield(game, permanent):
    """Activate *permanent*'s own "Regenerate this creature" through the
    engine and resolve it — the shield the forecasts read."""
    seat = game.controller_index_of(permanent)
    program = compile_card_oracle(permanent.card)
    index = next(
        i for i, ability in enumerate(program.activated_abilities)
        if ability.instruction is not None
        and ability.instruction.kind == "grant_regeneration_to_self"
    )
    result = game.queue_permanent_ability(
        seat, permanent.card.name,
        permanent_index=game.battlefield_index_of(permanent), ability_index=index,
    )
    assert getattr(result, "supported", False), result
    settle(game)
    assert permanent.regeneration_shield == 1


def _fight_declared(game, attacker, blocks):
    """Declare *attacker* (seat 0's only creature attacking) and *blocks*,
    then let the AI's combat driver deal the damage."""
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, why = game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=1,
    )
    assert ok, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers"


def test_a_shield_is_survival_but_not_a_seat_in_the_fight():
    """One on one, a first striker against a shielded 2/2: the shield saves
    the 2/2 and takes it out of combat, so the first striker lives — where an
    indestructible 2/2 fights on and kills it, and an unshielded one dies
    before it strikes. And a first-striking blocker of a shielded attacker
    lives the same way."""
    leeches, troll = _card("Land Leeches"), _card("Horned Troll")
    game, (striker, shielded) = _table(mine=[leeches], theirs=[troll])
    assert fight_outcome(game, striker, shielded) == (True, False)
    _raise_shield(game, shielded)
    assert survives_destruction(game, shielded, dealt_by=(striker,)) == REGENERATES
    assert fight_outcome(game, striker, shielded) == (False, False)
    assert fight_outcome(game, shielded, striker) == (False, False)
    hard = _mk_creature_card("Hard Two", 2, 2, "Indestructible")
    game, (striker, wall) = _table(mine=[leeches], theirs=[hard])
    assert survives_destruction(game, wall) == STAYS
    assert fight_outcome(game, striker, wall) == (False, True)


def test_cant_be_regenerated_and_a_denying_dealer_spend_no_shield():
    """CR 701.19c: under "can't be regenerated", or against damage from a
    creature whose damage denies it (Bone Shaman's line), a shield saves
    nothing — and the forecast says the shielded creature dies."""
    leeches, troll = _card("Land Leeches"), _card("Horned Troll")
    game, (striker, shielded) = _table(mine=[leeches], theirs=[troll])
    _raise_shield(game, shielded)
    shielded.metadata[CANT_BE_REGENERATED] = True
    assert survives_destruction(game, shielded) is None
    assert fight_outcome(game, striker, shielded) == (True, False)
    denier = _mk_creature_card(
        "Denier", 2, 2,
        "First strike\nCreatures dealt damage by this creature this turn can't be regenerated this turn.",
    )
    game, (striker, shielded) = _table(mine=[denier], theirs=[troll])
    _raise_shield(game, shielded)
    assert survives_destruction(game, shielded, dealt_by=(striker,)) is None
    assert fight_outcome(game, striker, shielded) == (True, False)


def test_a_first_striker_into_a_shield_and_a_bear_is_ganged_and_dies():
    """The board the Known-gaps entry names: Land Leeches (2/2 first strike)
    attacks into a shielded Horned Troll and a Grizzly Bears. The Troll alone
    does not kill it — the first-strike damage regenerates it out of combat —
    so the Bears joins (whichever the Leeches strikes, the other kills it),
    and in the engine's combat the Leeches dies. Read as indestructible, the
    Troll "killed" it alone, the Bears stayed back, and the Leeches lived."""
    game, (leeches, troll, bears) = _table(
        mine=[_card("Land Leeches")], theirs=[_card("Horned Troll"), _card("Grizzly Bears")],
    )
    _raise_shield(game, troll)
    assert not _gang_kills(game, leeches, [troll])
    assert _gang_kills(game, leeches, [troll, bears])
    assert _kills_back(game, leeches, [troll, bears]) == [bears]
    _fight_declared(game, leeches, {})
    blocks = choose_combat_blockers(game, 1)
    assert sorted(game.permanent_at(1, slot).card.name for slot in blocks) == [
        "Grizzly Bears", "Horned Troll",
    ]
    run_ai_combat_phase(game, 0)
    assert "Horned Troll regenerated" in game.log
    assert not game.is_on_battlefield(leeches)
    assert game.is_on_battlefield(troll)


def test_a_first_striker_blocks_a_shielded_attacker():
    """A shielded Horned Troll attacks into an untapped Land Leeches: the
    first-strike damage regenerates the Troll out of combat before it deals
    any, so the block costs nothing and stops two damage. Read as
    indestructible, the Leeches "died" to the Troll's regular damage and the
    seat took two."""
    game, (troll, leeches) = _table(mine=[_card("Horned Troll")], theirs=[_card("Land Leeches")])
    _raise_shield(game, troll)
    _fight_declared(game, troll, {})
    run_ai_combat_phase(game, 0)
    assert game.players[1].life == 20
    assert game.is_on_battlefield(leeches) and leeches.damage_marked == 0
    assert troll.tapped and "Horned Troll was removed from combat" in game.log


def _self_shielding_creatures() -> list:
    """The shipped creatures with "Regenerate this creature" — less those
    with a trigger of their own on blocking or being blocked (flanking's
    -1/-1, Pygmy Troll's +1/+1), which change the fight after the blocks and
    which no forecast here reads (a separate gap, named in kg5's report)."""
    found = []
    for card in sorted(_catalog().values(), key=lambda each: each.name):
        if "Creature" not in (card.type_line or ""):
            continue
        program = compile_card_oracle(card)
        if any("block" in trigger.condition.kind for trigger in program.triggered_abilities):
            continue
        if program.supported and any(
            ability.instruction is not None
            and ability.instruction.kind == "grant_regeneration_to_self"
            for ability in program.activated_abilities
        ):
            found.append(card)
    return found


def _observed(regenerator, *, regenerator_attacks: bool):
    """Fight *regenerator* (shield up) against a first striker it would kill
    with regular damage, sized so its first-strike damage is lethal; return
    ``(forecast, observed)`` as ``(attacker destroyed blocker, blocker
    destroyed attacker)``, or None where the pair cannot fight."""
    probe, (sized,) = _table(mine=[regenerator])
    if sized.effective_toughness <= 0:
        return None
    striker_card = _mk_creature_card(
        "First Striker", max(1, sized.effective_toughness), max(1, sized.effective_power),
        "First strike",
    )
    if regenerator_attacks:
        game, (attacker, blocker) = _table(mine=[regenerator], theirs=[striker_card])
        shielded = attacker
    else:
        game, (attacker, blocker) = _table(mine=[striker_card], theirs=[regenerator])
        shielded = blocker
    shielded.regeneration_shield = 1
    if not game.can_attack(attacker, 1) or not game._can_block_attacker(blocker, attacker):
        return None
    forecast = fight_outcome(game, attacker, blocker)
    game.active_player_index = 0
    game._set_phase_and_step("combat", "declare_attackers")
    ok, _why = game.declare_attackers(
        0, [game.battlefield_index_of(attacker)], defending_player_index=1,
    )
    if not ok:
        return None
    game.advance_combat_phase()
    if game.current_step != "declare_blockers" or not (
        game.is_on_battlefield(attacker) and game.is_on_battlefield(blocker)
    ):
        return None
    ok, _why = game.declare_blockers(
        1, {game.battlefield_index_of(blocker): game.battlefield_index_of(attacker)},
    )
    if not ok:
        return None
    drive_combat(game)
    observed = (not game.is_on_battlefield(blocker), not game.is_on_battlefield(attacker))
    return forecast, observed


def test_the_forecast_fights_every_self_shielding_creature_as_the_engine_does():
    """Every shipped creature with "Regenerate this creature", shield up,
    against a first striker its regular damage would kill — as the blocker,
    and as the attacker: the forecast is the engine's combat. Validated
    backwards: on a tree reading the shield as indestructible, every
    regenerator with power forecast a kill the engine never dealt."""
    regenerators = _self_shielding_creatures()
    assert len(regenerators) >= 60, len(regenerators)
    fought = 0
    wrong = []
    for card in regenerators:
        for attacks in (False, True):
            result = _observed(card, regenerator_attacks=attacks)
            if result is None:
                continue
            fought += 1
            forecast, observed = result
            if forecast != observed:
                wrong.append((card.name, "attacks" if attacks else "blocks", forecast, observed))
    assert fought >= 100, fought
    assert not wrong, wrong
