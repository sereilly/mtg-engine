"""A permanent's later abilities, and a rescue that removes its own source, at
instant speed (kg4 `aiact`, part 2).

**The defects.** The own-board chooser read a non-land's **first** usable
ability and nothing else (``ai_abilities._abilities_weighed``), and the
instant-speed chooser set a turned-down proposal aside by its *permanent*, so
a second or third ability was never activated by an AI seat in any window:
Morphling's shroud behind its untap, in front of the Lightning Bolt aimed at
it. And an effect that removes its own source (Quicksilver Wall's "{4}:
Return this creature to its owner's hand") was skipped everywhere
(``ai_valuation.harms_its_own_source``), so the bounce was never used as the
rescue it is in front of a removal spell.

**The fix.** Every non-mana ability of a non-land is weighed, the first
unindexed as before and each later one by its index and only where a
rehearsal says it pays; a proposal the instant-speed chooser turns down sets
aside that ability alone; and at instant speed an own-source removal is
proposed and rehearsed — taken in front of the removal, not with nothing
coming (the main phase still skips it). Each test drives a
`_SimulatedGame` built the way `run_ai_simulation` builds one, through the
priority answer every AI seat shares (``ai_priority.act_at_priority``).
"""
from __future__ import annotations

import pytest

from engine import ai_simulator
from engine.ai_abilities import _abilities_weighed, choose_activation_action
from engine.ai_policy import activate_chosen_ability, choose_instant_speed_activation
from engine.ai_priority import act_at_priority
from engine.ai_valuation import SOURCE_RETURN_KINDS
from engine.ai_weighed_cast import _effect_steps
from engine.card_loader import load_catalog
from engine.faces import compilation_units
from engine.mana_abilities import is_mana_ability as is_cr_mana_ability
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import usable_activated_abilities
from tests.helpers import _nosick, resolve_stack

_CATALOG = load_catalog()
_CARDS = {card.name: card for card in _CATALOG}
_LANDS = ("Plains", "Island", "Swamp", "Mountain", "Forest") * 3

#: The census floor: non-land permanents in the shipped pool printing two or
#: more non-mana abilities (179 at kg4).
_MULTI_ABILITY_FLOOR = 150


def _table(own, other=("Mountain",), *, active=1, step=("precombat_main", "precombat_main")):
    """Two seats as `run_ai_simulation` builds them, mana enforced, every
    permanent able to tap; seat *active*'s turn."""
    players = [
        PlayerState(name=name, library=[_CARDS["Forest"]] * 8, hand=[_CARDS["Forest"]] * 2)
        for name in ("AI-A", "AI-B")
    ]
    game = ai_simulator._SimulatedGame(
        players=players, enforce_mana_costs=True,
        prompt_driver=ai_simulator._resolve_pending_choices,
    )
    game.turn = 3
    game.active_player_index = active
    for seat, board in enumerate((own, other)):
        for name in board:
            permanent = Permanent(card=_CARDS[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game._set_phase_and_step(*step)
    return game


def _on(game, seat, name):
    return next((p for p in game.controlled_by(seat) if p.card.name == name), None)


def _aim(game, spell, colour, target):
    """Seat 1 casts *spell* at *target* (seat 0's permanent)."""
    game.players[1].mana_pool[colour] = 2
    game.players[1].hand.append(_CARDS[spell])
    result = game.queue_from_hand(
        1, spell, target_player_index=0, target_permanent_ids=[target.permanent_id],
    )
    assert result.supported, result


def _multi_ability_permanents() -> list:
    return [
        unit for unit in compilation_units(_CATALOG)
        if "Land" not in (unit.type_line or "")
        and unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and sum(
            1 for ability in usable_activated_abilities(compile_card_oracle(unit))
            if not is_cr_mana_ability(ability)
        ) >= 2
    ]


def test_every_non_mana_ability_of_a_permanent_is_weighed():
    """Pool-wide: on the battlefield, each permanent printing two or more
    non-mana abilities offers the chooser every one of them — the first
    unindexed (the engine's default), each later one by its index. The
    chooser saw the first alone."""
    examined = 0
    for unit in _multi_ability_permanents():
        game = _table((unit.name,), active=0)
        permanent = _on(game, 0, unit.name)
        usable = game.usable_abilities_of(permanent)
        wanted = [None] + [
            index for index, ability in enumerate(usable)
            if index > 0 and not is_cr_mana_ability(ability)
        ]
        assert [index for index, _ability in _abilities_weighed(game, permanent)] == wanted, unit.name
        examined += 1
    assert examined >= _MULTI_ABILITY_FLOOR, examined


def test_morphling_gains_shroud_in_front_of_the_bolt_aimed_at_it():
    """Morphling's third ability — "{U}: gains shroud until end of turn" — is
    the one that pays in front of a Lightning Bolt: its first (untap) is
    rehearsed and turned down, and the next one asked is that permanent's
    next ability, not another permanent. The Bolt's only target is illegal
    as it resolves (CR 608.2b) and Morphling lives."""
    game = _table(("Morphling", "Island", "Island"))
    morphling = _on(game, 0, "Morphling")
    _aim(game, "Lightning Bolt", "R", morphling)
    act = act_at_priority(game, 0)
    assert act is not None and act.kind == "activate", act
    assert act.action.permanent_name == "Morphling" and act.action.ability_index == 2, act.action
    resolve_stack(game)
    game.check_state_based_actions()
    assert _on(game, 0, "Morphling") is morphling
    assert any("shroud" in line for line in game.log), game.log[-8:]
    assert not any("Lightning Bolt dealt 3 damage to Morphling" in line for line in game.log)


def test_with_nothing_coming_no_later_ability_is_spent():
    """The same Morphling at the opponent's end step with nothing on the
    stack: none of its five abilities is worth its mana."""
    game = _table(("Morphling", "Island", "Island"), step=("ending", "end"))
    assert choose_instant_speed_activation(game, 0) is None


def test_quicksilver_wall_returns_to_hand_in_front_of_swords_to_plowshares():
    """The rescue: in front of Swords to Plowshares aimed at it, the Wall's
    "{4}: Return this creature to its owner's hand" is a card kept rather
    than a card exiled, and the seat takes it."""
    game = _table(("Quicksilver Wall", *_LANDS[:5]))
    wall = _on(game, 0, "Quicksilver Wall")
    _aim(game, "Swords to Plowshares", "W", wall)
    act = act_at_priority(game, 0)
    assert act is not None and act.action.permanent_name == "Quicksilver Wall", act
    resolve_stack(game)
    assert any(card.name == "Quicksilver Wall" for card in game.players[0].hand)
    assert not any(card.name == "Quicksilver Wall" for card in game.players[0].exile)


def test_a_rescue_with_nothing_coming_is_not_taken():
    """The same Wall at the opponent's end step, and in its controller's own
    main phase: a permanent traded for a card is a loss either way."""
    idle = _table(("Quicksilver Wall", *_LANDS[:5]), step=("ending", "end"))
    assert choose_instant_speed_activation(idle, 0) is None
    main = _table(("Quicksilver Wall", *_LANDS[:5]), active=0)
    assert choose_activation_action(main, 0) is None


def _rescues() -> list:
    """Every shipped non-Aura permanent printing an ability that returns its
    own source to its owner's hand or library."""
    return sorted({
        unit.name for unit in compilation_units(_CATALOG)
        if "Aura" not in (unit.type_line or "")
        and unit.primary_type not in ("instant", "sorcery")
        and compile_card_oracle(unit).supported
        and any(
            {step.kind for step in _effect_steps(ability.instruction)} & SOURCE_RETURN_KINDS
            for ability in usable_activated_abilities(compile_card_oracle(unit))
        )
    })


#: Rescues the census must see taken (kg4: 11 of the 30 the chooser's cost
#: floors let through — a discard, a land sacrificed and an upkeep-only
#: timing keep the rest out; a library-top return is a card the standing
#: does not count).
_RESCUES_TAKEN_FLOOR = 8


@pytest.mark.full
def test_the_rescue_census():
    """Each rescue's permanent, Swords to Plowshares (a creature) or
    Disenchant (anything else) aimed at it: where the chooser proposes the
    rescue, its card ends in its owner's hand; and with nothing coming none
    is proposed. On the base no rescue was ever proposed."""
    taken, examined = [], 0
    for name in _rescues():
        card = _CARDS[name]
        spell, colour = (
            ("Swords to Plowshares", "W") if "Creature" in (card.type_line or "")
            else ("Disenchant", "W")
        )
        game = _table((name, *_LANDS))
        source = _on(game, 0, name)
        game.players[1].mana_pool[colour] = 2
        game.players[1].hand.append(_CARDS[spell])
        if not game.queue_from_hand(
            1, spell, target_player_index=0, target_permanent_ids=[source.permanent_id],
        ).supported:
            continue
        examined += 1
        action = choose_instant_speed_activation(game, 0)
        idle = choose_instant_speed_activation(
            _table((name, *_LANDS), step=("ending", "end")), 0,
        )
        assert idle is None or not (
            {step.kind for step in _effect_steps(
                game.usable_abilities_of(source)[idle.ability_index or 0].instruction
            )} & SOURCE_RETURN_KINDS
        ), (name, idle)
        if action is None or action.permanent_name != name:
            continue
        ability = game.usable_abilities_of(source)[action.ability_index or 0]
        if not {step.kind for step in _effect_steps(ability.instruction)} & SOURCE_RETURN_KINDS:
            continue
        activate_chosen_ability(game, 0, action)
        resolve_stack(game)
        assert any(card.name == name for card in game.players[0].hand), name
        taken.append(name)
    assert examined >= 25, examined
    assert len(taken) >= _RESCUES_TAKEN_FLOOR, taken


#: Creatures whose later ability is proposed in front of the census's Bolt
#: (kg4: 10 — Morphling's shroud, Thornscape Master's protection, Stone
#: Kavu's toughness among them; none on the base).
_LATER_ABILITY_FLOOR = 5


@pytest.mark.full
def test_the_later_ability_census():
    """Every shipped creature printing two or more non-mana abilities, every
    colour of mana open, an opponent's Lightning Bolt aimed at it: the
    instant-speed chooser now proposes a later ability where one pays, and
    carried out the creature survives or what it bought lasts — the
    rehearsal's promise. On the base no later ability was ever proposed."""
    later, examined = [], 0
    for unit in _multi_ability_permanents():
        if "Creature" not in (unit.type_line or ""):
            continue
        game = _table((unit.name, *_LANDS))
        creature = _on(game, 0, unit.name)
        _aim(game, "Lightning Bolt", "R", creature)
        examined += 1
        action = choose_instant_speed_activation(game, 0)
        if action is None or action.ability_index is None:
            continue
        later.append(unit.name)
    assert examined >= 100, examined
    assert len(later) >= _LATER_ABILITY_FLOOR, later
    assert {"Morphling", "Thornscape Master"} <= set(later), later
