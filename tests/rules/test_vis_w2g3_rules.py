"""Rules tests earned by Visions wave 2, group 3.

Each of these is about a Comprehensive Rule rather than about a card, which is
what puts it here instead of in ``tests/sets/`` -- the cards that provoked them
(Death Watch, Vampirism, Mob Mentality, Eye of Singularity) are named in the
docstrings and have their own per-card tests beside their set.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.auras import attach_aura, detach_aura
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.models import CardDefinition, Permanent
from engine.oracle import compile_card_oracle
from engine.pt import add_pt_modifier


def _pool():
    return {card.name: card for card in load_cards(manifest_set_paths())}


def _vis():
    return {
        card.name: card
        for card in load_cards(manifest_set_path("VIS", include_measured=True))
    }


def _game():
    game = Game(players=[PlayerState(name="P1"), PlayerState(name="P2")])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    return game


def _enters(game, seat, card):
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    while game.stack:
        game.resolve_top_of_stack()
    return permanent


def _aura(text, name="Probe Aura"):
    return CardDefinition(
        name=name, mana_cost="{B}", cmc=1.0, type_line="Enchantment - Aura",
        oracle_text=text, colors=("B",), color_identity=("B",), keywords=(),
        produced_mana=(), raw={"name": name, "type_line": "Enchantment - Aura"},
    )


@pytest.mark.cr("603.10", "608.2h")
def test_603_10_an_attached_death_trigger_reads_the_numbers_the_game_had():
    """A trigger uses the information the game had when the event happened.

    "When enchanted creature dies, its controller loses life equal to its power
    and you gain life equal to its toughness" (Death Watch) resolves off the
    stack (CR 603.3), by which time the creature is a card in a graveyard with a
    printed power, no anthem on it and -- CR 108.4 -- no controller at all. So
    all three of the numbers the sentence needs have to be frozen when it died.

    Asserted with a *pumped* creature and an Aura its owner does not control,
    because those are the two readings that differ: the printed 3/3 against the
    5/7 it was, and the caster against the seat that lost the creature.
    """
    pool, vis = _pool(), _vis()
    game = _game()
    victim = _enters(game, 1, pool["Hill Giant"])
    aura = _enters(game, 0, vis["Death Watch"])
    attach_aura(aura, victim)
    game._recompute_continuous_effects()
    add_pt_modifier(victim, 2, 4, until="end_of_turn")
    game._recompute_continuous_effects()

    game._destroy_swept_permanents(game.players[1], lambda perm: perm is victim)
    while game.stack:
        game.resolve_top_of_stack()

    assert game.players[1].life == 15, "its controller lost the power it had"
    assert game.players[0].life == 27, "the Aura's controller gained the toughness"


@pytest.mark.cr("603.10")
def test_603_10_every_death_this_site_announces_carries_the_frozen_pair():
    """The freeze is a property of the **fire site**, not of the card.

    ``_fire_creature_dies_triggers`` builds one context for every death
    condition it announces, and the two characteristics were missing from it --
    while the comment on the sibling permanent-death site already claimed this
    one froze them. An invented Aura is what says the fix is about the site: no
    shipped card prints this exact sentence, and it works anyway.
    """
    pool = _pool()
    game = _game()
    victim = _enters(game, 0, pool["Grizzly Bears"])
    probe = _aura(
        "Enchant creature\n"
        "When enchanted creature dies, you gain life equal to its power."
    )
    assert compile_card_oracle(probe).supported
    aura = _enters(game, 0, probe)
    attach_aura(aura, victim)
    game._recompute_continuous_effects()
    add_pt_modifier(victim, 3, 0, until="end_of_turn")
    game._recompute_continuous_effects()

    game._destroy_swept_permanents(game.players[0], lambda perm: perm is victim)
    while game.stack:
        game.resolve_top_of_stack()

    assert game.players[0].life == 25


@pytest.mark.cr("611.3b", "613.4c")
def test_611_3b_a_counted_bonus_on_the_host_lasts_exactly_while_it_is_attached():
    """A continuous effect from an Aura applies only while it is attached, and a
    layer-7c contribution whose *size* is a count is no different.

    Derived on every recompute rather than written once and remembered, which is
    what makes detaching it free: there is no delta to subtract and nothing that
    can fall out of step with what was added. Vampirism is the card; the
    assertion is that the number moves with the board and disappears with the
    attachment.
    """
    pool, vis = _pool(), _vis()
    game = _game()
    host = _enters(game, 0, pool["Grizzly Bears"])
    _enters(game, 0, pool["Grizzly Bears"])
    aura = _enters(game, 0, vis["Vampirism"])

    attach_aura(aura, host)
    game._recompute_continuous_effects()
    assert (host.effective_power, host.effective_toughness) == (3, 3)

    detach_aura(aura, host)
    game._recompute_continuous_effects()
    # The anthem half still applies -- it is not conditioned on the attachment --
    # so what the detach took away is exactly the counted grant.
    assert (host.effective_power, host.effective_toughness) == (1, 1)


@pytest.mark.cr("201.2a")
def test_201_2a_the_same_name_is_a_comparison_of_names_not_of_card_objects():
    """Two or more objects have the same name if they have at least one name in
    common.

    Eye of Singularity's sweep compares names, so two permanents built from
    *different* card objects that print the same name are duplicates -- and a
    relation implemented as object identity, or as one entry in a catalog,
    would call them singletons and sweep neither.
    """
    vis = _vis()
    printing = CardDefinition(
        name="Grizzly Bears", mana_cost="{1}{G}", cmc=2.0,
        type_line="Creature - Bear", oracle_text="", colors=("G",),
        color_identity=("G",), keywords=(), produced_mana=(),
        raw={"name": "Grizzly Bears", "type_line": "Creature - Bear",
             "power": "2", "toughness": "2"},
    )
    game = _game()
    _enters(game, 0, _pool()["Grizzly Bears"])
    _enters(game, 1, printing)

    _enters(game, 0, vis["Eye of Singularity"])

    assert [p.card.name for p in game.players[0].battlefield] == ["Eye of Singularity"]
    assert game.players[1].battlefield == []


@pytest.mark.cr("603.2", "508.1")
def test_603_2_an_attack_declaration_trigger_is_announced_for_a_noncreature():
    """A triggered ability triggers whenever its event occurs, whatever kind of
    permanent it is printed on.

    The declaration (CR 508.1) is announced through the event bus for every
    permanent whose compiled trigger matches, not only for the creatures in the
    declaration -- which is what lets an Aura watch its controller's attack.
    Mob Mentality is the card; the assertion is that the announcement reaches a
    permanent that is not itself attacking and could not.
    """
    pool, vis = _pool(), _vis()
    game = _game()
    bear = _enters(game, 0, pool["Grizzly Bears"])
    bear.metadata["summoning_sickness_turn"] = -99
    aura = _enters(game, 0, vis["Mob Mentality"])
    attach_aura(aura, bear)
    game._recompute_continuous_effects()

    game.start_turn(0)
    game._close_current_priority_step()
    game.advance_combat_phase()
    game.advance_combat_phase()
    assert game.current_step == "declare_attackers"
    game.declare_attackers(0, [game.players[0].battlefield.index(bear)])
    while game.stack:
        game.resolve_top_of_stack()
    game._recompute_continuous_effects()

    assert bear.effective_power == 3, "the Aura's trigger was announced and resolved"
