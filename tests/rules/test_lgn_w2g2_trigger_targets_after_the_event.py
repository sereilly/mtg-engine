"""CR 603.3d / 117.5 — a triggered ability chooses its targets as it is put on
the stack, which is after the event that set it off has finished and after
state-based actions have been performed.

Driven on the two Legions cards whose rulings say so, and on two shipped cards
the census (``tests/engine/test_lgn_w2g2_trigger_choice_after_the_event_census.py``)
names: Scion of Darkness may target the blocker it trampled over and killed
(2004-10-04); Celestial Gatekeeper dying to Wrath of God may return a Cleric
the same Wrath destroyed after it, and may name itself (2004-10-04); Pitchburn
Devils in a sweep is offered the players and not the creatures the sweep
destroyed; Spark Mage is not offered the blocker lethal damage is killing.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import declare_attack, resolve_stack


def _table(set_pool, *, hand=(), interactive=(0,)) -> Game:
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("A", library=[lea["Plains"]] * 10, hand=list(hand)),
        PlayerState("B", library=[lea["Plains"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    game.start_turn(0)
    game._close_current_priority_step()
    game._set_phase_and_step("precombat_main", "main")
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    return permanent


def _prompt(game, name):
    return next(
        choice for choice in game.pending_choices_of("trigger_target")
        if choice.data["card_name"] == name
    )


def _offers(choice) -> list[tuple]:
    return [(entry["kind"], entry.get("seat"), entry["name"]) for entry in choice.data["targets"]]


def _through_combat_damage(game, item_name):
    for _ in range(6):
        if any(
            choice.data["card_name"] == item_name
            for choice in game.pending_choices_of("trigger_target")
        ) or game.current_step in ("end_of_combat", "postcombat_main"):
            return
        if game.trample_assignments_to_ask(0):
            # A trampler blocked by one creature asks the interactive attacker
            # where its excess goes (CR 702.19b; kg3 wire): answered here the
            # way the step used to answer it unasked — lethal to the blocker,
            # the rest to the player.
            ok, why = game.resolve_combat_damage(
                0, attacker_damage=game._build_auto_damage_assignment()
            )
            assert ok, why
            continue
        game.advance_combat_phase()


@pytest.mark.cr("603.3d", "117.5")
def test_scion_of_darkness_may_target_the_blocker_it_trampled_over_and_killed(set_pool):
    """"Whenever this creature deals combat damage to a player, you may put
    target creature card from that player's graveyard onto the battlefield
    under your control." Ruling (2004-10-04): "If this card destroys a
    creature in combat and at the same time (using its Trample ability) it
    damages a player, you will be able to target the destroyed creature."
    The Grizzly Bears dies to the state-based check after the damage; the
    trigger goes on the stack after that and offers it beside the Hill Giant
    already there — and returning it puts it under Scion's controller."""
    lgn, lea = set_pool("LGN"), set_pool("LEA")
    game = _table(set_pool)
    game.players[1].graveyard.append(lea["Hill Giant"])
    scion = _put(game, 0, lgn["Scion of Darkness"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    declare_attack(game, 0, blocks={
        game.battlefield_index_of(bears): game.battlefield_index_of(scion),
    })
    _through_combat_damage(game, "Scion of Darkness")

    assert game.players[1].life == 20 - (6 - 2)
    assert not game.is_on_battlefield(bears)
    choice = _prompt(game, "Scion of Darkness")
    assert sorted(_offers(choice)) == [
        ("graveyard", 1, "Grizzly Bears"), ("graveyard", 1, "Hill Giant"),
    ]
    slot = [card.name for card in game.players[1].graveyard].index("Grizzly Bears")
    assert game.confirm_trigger_target(0, seat=1, graveyard_index=slot)
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    back = [p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears"]
    assert len(back) == 1
    assert [card.name for card in game.players[1].graveyard] == ["Hill Giant"]


@pytest.mark.cr("603.3d", "117.5")
def test_celestial_gatekeeper_returns_a_cleric_the_same_sweep_destroyed_after_it(set_pool):
    """"When this creature dies, exile it, then return up to two target Bird
    and/or Cleric permanent cards from your graveyard to the battlefield."
    Gatekeeper is first on its battlefield, so Wrath of God destroys it before
    the Daru Healer; the trigger chooses once the sweep is over, so the Healer
    is offered — and so is Gatekeeper itself (ruling 2004-10-04: "You can
    choose to target this card as one of the two … If you do, it gets exiled
    and does not get returned to the battlefield")."""
    lgn, ons, lea = set_pool("LGN"), set_pool("ONS"), set_pool("LEA")
    game = _table(set_pool, hand=[lea["Wrath of God"]])
    _put(game, 0, lgn["Celestial Gatekeeper"])
    _put(game, 0, ons["Daru Healer"])
    assert game.queue_from_hand(0, "Wrath of God").supported
    game.resolve_top_of_stack()

    choice = _prompt(game, "Celestial Gatekeeper")
    assert sorted(_offers(choice)) == [
        ("graveyard", 0, "Celestial Gatekeeper"), ("graveyard", 0, "Daru Healer"),
    ]
    yard = [card.name for card in game.players[0].graveyard]
    assert game.confirm_trigger_target(
        0, seat=0, graveyard_indices=[
            yard.index("Celestial Gatekeeper"), yard.index("Daru Healer"),
        ],
    )
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert [p.card.name for p in game.controlled_by(0)] == ["Daru Healer"]
    assert [card.name for card in game.players[0].exile] == ["Celestial Gatekeeper"]


@pytest.mark.cr("603.3d", "117.5")
def test_celestial_gatekeeper_unasked_returns_the_cleric_too(set_pool):
    """A seat nobody asks takes the picker's default off the same list: the
    Cleric the sweep destroyed after Gatekeeper comes back."""
    lgn, ons, lea = set_pool("LGN"), set_pool("ONS"), set_pool("LEA")
    game = _table(set_pool, hand=[lea["Wrath of God"]], interactive=())
    _put(game, 0, lgn["Celestial Gatekeeper"])
    _put(game, 0, ons["Daru Healer"])
    assert game.queue_from_hand(0, "Wrath of God").supported
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)

    assert "Daru Healer" in [p.card.name for p in game.controlled_by(0)]


@pytest.mark.cr("603.3d", "117.5")
def test_pitchburn_devils_in_a_sweep_is_offered_the_players_alone(set_pool):
    """"When this creature dies, it deals 3 damage to any target." Dying to
    Wrath of God beside two creatures, a seat that was asked was offered all
    three creatures the sweep was destroying, itself included, beside the two
    players. The sweep is one event: the trigger chooses after it, and only
    the players are left. (A seat nobody asks took the opposing player on
    both trees — the default prefers a seat for damage — and still does.)"""
    lea, m21 = set_pool("LEA"), set_pool("M21")
    game = _table(set_pool, hand=[lea["Wrath of God"]])
    _put(game, 0, m21["Pitchburn Devils"])
    _put(game, 0, lea["Grizzly Bears"])
    _put(game, 1, lea["Hill Giant"])
    assert game.queue_from_hand(0, "Wrath of God").supported
    game.resolve_top_of_stack()

    choice = _prompt(game, "Pitchburn Devils")
    assert sorted(_offers(choice)) == [("player", 0, "A"), ("player", 1, "B")]

    unasked = _table(set_pool, hand=[lea["Wrath of God"]], interactive=())
    _put(unasked, 0, m21["Pitchburn Devils"])
    _put(unasked, 0, lea["Grizzly Bears"])
    _put(unasked, 1, lea["Hill Giant"])
    assert unasked.queue_from_hand(0, "Wrath of God").supported
    resolve_stack(unasked)
    assert unasked.players[1].life == 17


@pytest.mark.cr("603.3d", "117.5", "704.3")
def test_spark_mage_is_not_offered_the_blocker_lethal_damage_is_killing(set_pool):
    """"Whenever this creature deals combat damage to a player, you may have
    this creature deal 1 damage to target creature that player controls." The
    Grizzly Bears blocking the Hill Giant beside it takes lethal damage in the
    same step and dies to the state-based check that follows; the trigger goes
    on the stack after that, so only the Ornithopter is offered."""
    ody, lea = set_pool("ODY"), set_pool("LEA")
    game = _table(set_pool)
    _put(game, 0, ody["Spark Mage"])
    giant = _put(game, 0, lea["Hill Giant"])
    bears = _put(game, 1, lea["Grizzly Bears"])
    _put(game, 1, set_pool("ATQ")["Ornithopter"])
    declare_attack(game, 0, blocks={
        game.battlefield_index_of(bears): game.battlefield_index_of(giant),
    })
    _through_combat_damage(game, "Spark Mage")

    assert not game.is_on_battlefield(bears)
    choice = _prompt(game, "Spark Mage")
    assert _offers(choice) == [("permanent", 1, "Ornithopter")]
