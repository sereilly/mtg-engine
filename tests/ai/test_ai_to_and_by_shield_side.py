"""Whose creature a "dealt to **and dealt by**" combat shield is aimed at.

"Untap target attacking creature. Prevent all combat damage that would be
dealt to and dealt by that creature this turn." (Foxfire, and Maze of Ith's
land.) "Untap any number of target creatures. Prevent all combat damage that
would be dealt to and dealt by those creatures this turn." (Energy Arc.)

The AI read whose creature to name off the untap alone - an untap is a second
use of something, so "you" (``ai_target_sides._OWN_KINDS``) - and never read
the shield, which names its object by pronoun and so carries no target of its
own. Energy Arc went to the caster's own creature with the opposing twin
measuring four times as much (found by ``test_ai_idle_cast_census.py`` once
Judgment's promotion moved its sample onto the card), and Foxfire could be
cast only at the caster's own attacker: on the opponent's turn the side the
untap wanted held nothing.

The shield is a denial as well as a gift - a creature that deals no combat
damage is ``prevent_damage_by_target_until_eot``'s case - and where a gift and
a denial meet on one object the denial wins (``spell_target_side``). A printed
seat still outranks it.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.ai_actions import cast_announcement
from engine.ai_policy import choose_cast_action, choose_combat_instant_cast_action
from engine.ai_target_sides import ability_target_side, spell_target_side
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool() -> dict:
    cards: dict = {}
    for card in compilation_units(load_cards(manifest_set_paths())):
        cards.setdefault(card.name, card)
    return cards


def _table(pool, hand, mine=(), theirs=()) -> Game:
    forest = pool["Forest"]
    game = Game(players=[
        PlayerState(name="AI", hand=[pool[name] for name in hand], library=[forest] * 20),
        PlayerState(name="Opp", library=[forest] * 20),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    for seat, names in ((ME, mine), (OPP, theirs)):
        for name in names:
            permanent = Permanent(card=pool[name])
            game._put_permanent_onto_battlefield(seat, permanent, seat)
            permanent.metadata["summoning_sickness_turn"] = -99
    return game


def test_the_two_spells_read_the_shield_and_a_printed_seat_still_wins(pool):
    assert spell_target_side(pool["Energy Arc"]) == "opponent"
    assert spell_target_side(pool["Foxfire"]) == "opponent"
    # "…dealt to and dealt by target creature **you control**" (Cephalid
    # Illusionist) and "Untap target attacking creature **you control**. …"
    # (Ebony Horse): the noun phrase says whose, and the shield does not
    # overrule it.
    for name in ("Cephalid Illusionist", "Ebony Horse"):
        (ability,) = compile_card_oracle(pool[name]).activated_abilities
        assert ability_target_side(ability.instruction) == "you", name


def test_energy_arc_is_aimed_across_the_table(pool):
    """The census's mirror board, cut down: the same creatures on both sides,
    the caster's main phase. The arc goes on an opposing creature - the Hill
    Giant, the blocker that would otherwise eat the Bears."""
    board = ("Grizzly Bears", "Hill Giant")
    game = _table(pool, ["Energy Arc"], mine=board, theirs=board)
    game.start_turn(ME)
    game._close_current_priority_step()

    action = choose_cast_action(game, ME)
    assert action is not None and action.card_name == "Energy Arc"
    (named_id,) = action.target_permanent_ids
    named = game.permanent_by_id(named_id)
    assert game.controller_index_of(named) == OPP, named.card.name

    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)
    assert any(
        "dealt to and dealt by " + named.card.name in line and "(Energy Arc)" in line
        for line in game.log
    ), game.log[-6:]


def test_foxfire_fogs_the_opponents_attacker(pool):
    """The opponent attacks with a Hill Giant and nothing blocks: the seat
    holding Foxfire casts it at the Giant in the declare-blockers step, and
    the Giant's 3 damage never arrives. Read off the untap alone, the side
    held no attacking creature and the seat took the 3."""
    game = _table(pool, ["Foxfire"], theirs=("Hill Giant",))
    game.start_turn(OPP)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers", game.current_step
    declared, why = game.declare_attackers(OPP, [0], defending_player_index=ME)
    assert declared, why
    game.advance_combat_phase()
    assert game.current_step == "declare_blockers", game.current_step
    declared, why = game.declare_blockers(ME, {})
    assert declared, why

    action = choose_combat_instant_cast_action(game, ME)
    assert action is not None and action.card_name == "Foxfire"
    giant = next(iter(game.controlled_by(OPP)))
    assert action.target_permanent_ids == [giant.permanent_id]
    result = game.cast_from_hand(ME, action.card_name, **cast_announcement(action))
    assert result.supported, result.details
    resolve_stack(game)

    game.current_step = "combat_damage"
    assert game.resolve_combat_damage(OPP)[0]
    assert game.players[ME].life == 20
    assert not giant.tapped, "untapped by the spell"
