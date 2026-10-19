"""CR 608.2b: a target that changed controller is still the target, unless its
description says otherwise.

"A target that's no longer in the zone it was in when it was targeted is
illegal. Other changes to the game state may cause a target to no longer be
legal …" A battlefield is one zone however many players control what is on
it, so a permanent that changes hands while a spell or ability waits is still
a legal target wherever its printed description admits it on its new
controller's side: "target creature" does, "target creature **an opponent
controls**" does not once its caster controls it.

This engine records an announced permanent by id **and** by the seat whose
battlefield it stood on, and its resolvers look the id up on that seat. So a
target that changed hands was "not there": Boomerang returned nothing, Terror
logged its target gone, and a triggered ability that read the slot on the old
battlefield hit whatever had slid into it. The seat is settled from the id
again as the object resolves now, where the gate judged the target still legal
(``LegalityMixin.resettle_announced_target_seats``). The census over the pool
is ``tests/regressions/test_target_changed_controller_census.py``.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.control import change_control
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import resolve_stack


class _Thief:
    """What takes control in response — one source of a layer 2 effect."""


def _table(set_pool, hand=()):
    lea = set_pool("LEA")
    game = Game(players=[
        PlayerState("Caster", library=[lea["Island"]] * 10, hand=list(hand)),
        PlayerState("Opponent", library=[lea["Island"]] * 10),
    ])
    game.enforce_mana_costs = False
    game.active_player_index = 0
    game._set_phase_and_step("precombat_main", "precombat_main")
    return game


def _put(game, seat, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _take(game, permanent, seat) -> None:
    change_control(permanent, seat, source=_Thief())
    game._sync_control()
    game._recompute_continuous_effects()


def _names(game, seat) -> list[str]:
    return sorted(permanent.card.name for permanent in game.controlled_by(seat))


@pytest.mark.cr("608.2b")
def test_boomerang_returns_the_creature_its_caster_took_in_response(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[set_pool("LEG")["Boomerang"]])
    bears = _put(game, 1, lea["Grizzly Bears"])
    _put(game, 1, lea["Hill Giant"])
    assert game.queue_from_hand(
        0, "Boomerang", target_permanent_ids=[bears.permanent_id],
    ).supported

    _take(game, bears, 0)
    resolve_stack(game)

    # Its owner's hand (CR 108.3), and nothing else moved.
    assert [card.name for card in game.players[1].hand] == ["Grizzly Bears"]
    assert _names(game, 1) == ["Hill Giant"]
    assert _names(game, 0) == []
    assert "Boomerang: nothing was returned" not in game.log


@pytest.mark.cr("608.2b")
def test_terror_destroys_a_target_that_changed_hands_and_nothing_else(set_pool):
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[lea["Terror"]])
    bears = _put(game, 1, lea["Grizzly Bears"])
    _put(game, 1, lea["Hill Giant"])
    assert game.queue_from_hand(
        0, "Terror", target_permanent_ids=[bears.permanent_id],
    ).supported

    _take(game, bears, 0)
    resolve_stack(game)

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert _names(game, 1) == ["Hill Giant"]
    assert not any("its target is gone" in line for line in game.log)


@pytest.mark.cr("608.2b")
def test_an_activation_follows_its_own_target_into_the_opponents_hands(set_pool):
    """The other direction: the activator's own creature, taken by the
    opponent in response, is still "any target"."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    sorcerer = _put(game, 0, lea["Prodigal Sorcerer"])
    elves = _put(game, 0, lea["Llanowar Elves"])
    lions = _put(game, 0, lea["Savannah Lions"])
    giant = _put(game, 1, lea["Hill Giant"])
    assert game.queue_permanent_ability(
        0, "Prodigal Sorcerer",
        permanent_index=game.battlefield_index_of(sorcerer), ability_index=0,
        target_permanent_ids=[elves.permanent_id],
    ).supported

    _take(game, elves, 1)
    resolve_stack(game)
    game.check_state_based_actions()

    assert [card.name for card in game.players[0].graveyard] == ["Llanowar Elves"]
    assert lions.damage_marked == 0 and giant.damage_marked == 0
    assert [player.life for player in game.players] == [20, 20]


@pytest.mark.cr("608.2b", "608.2h")
def test_that_creatures_controller_is_the_one_who_controls_it_now(set_pool):
    """Liquid Fire: "…deals X damage to target creature and 5 minus X damage
    to **that creature's controller**". The rider read the seat the target was
    announced on, so the creature was missed and its *old* controller took the
    5 minus X."""
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[set_pool("ODY")["Liquid Fire"]])
    wurm = _put(game, 1, lea["Craw Wurm"])
    assert game.queue_from_hand(
        0, "Liquid Fire", target_permanent_ids=[wurm.permanent_id], x_value=3,
    ).supported

    _take(game, wurm, 0)
    resolve_stack(game)

    assert wurm.damage_marked == 3
    assert [player.life for player in game.players] == [18, 20]


@pytest.mark.cr("608.2b", "603.3d")
def test_a_chosen_trigger_target_that_changed_hands_is_still_its_target(set_pool):
    """Nekrataal's entry trigger, its target chosen by its controller; control
    of that creature taken in response. It read the slot beside the id on the
    old battlefield, and destroyed the Hill Giant that had slid into it."""
    lea = set_pool("LEA")
    game = _table(set_pool)
    nekrataal = _put(game, 0, set_pool("VIS")["Nekrataal"])
    resolve_stack(game)
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    bears = _put(game, 1, lea["Grizzly Bears"])
    _put(game, 1, lea["Hill Giant"])
    trigger = compile_card_oracle(nekrataal.card).triggered_abilities[0]
    game.interactive_seats = {0}
    game._enqueue_triggered_ability(
        controller_index=0, source_permanent=nekrataal,
        instruction=trigger.instruction, effect_kind=trigger.effect_kind,
        ability_text=trigger.source_line,
    )
    assert game.confirm_trigger_target(0, permanent_id=bears.permanent_id)
    game.interactive_seats = set()

    _take(game, bears, 0)
    resolve_stack(game)

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert _names(game, 1) == ["Hill Giant"]


@pytest.mark.cr("608.2b", "603.3d")
def test_an_entry_trigger_named_as_its_creature_was_cast_follows_its_target(set_pool):
    """The other road a trigger's target is chosen by: this engine names an
    entry trigger's target as its permanent is cast, and the trigger takes the
    name as its own choice when it is put on the stack (CR 603.3d). Control of
    the named creature is taken while the creature spell waits."""
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[set_pool("VIS")["Nekrataal"]])
    bears = _put(game, 1, lea["Grizzly Bears"])
    _put(game, 1, lea["Hill Giant"])
    assert game.queue_from_hand(
        0, "Nekrataal", target_permanent_ids=[bears.permanent_id],
    ).supported

    _take(game, bears, 0)
    resolve_stack(game)

    assert [card.name for card in game.players[1].graveyard] == ["Grizzly Bears"]
    assert _names(game, 1) == ["Hill Giant"]
    assert _names(game, 0) == ["Nekrataal"]


@pytest.mark.cr("608.2b")
def test_a_target_whose_change_of_hands_left_its_description_is_not_followed(set_pool):
    """Ray of Command: "Untap target creature **an opponent controls** and
    gain control of it …". Once its caster controls the creature it is not one
    an opponent controls — the only target is illegal and the spell does not
    resolve; the seat is not re-settled onto a target the gate refused."""
    lea = set_pool("LEA")
    game = _table(set_pool, hand=[set_pool("ICE")["Ray of Command"]])
    bears = _put(game, 1, lea["Grizzly Bears"])
    bears.tapped = True
    assert game.queue_from_hand(
        0, "Ray of Command", target_permanent_ids=[bears.permanent_id],
    ).supported

    _take(game, bears, 0)
    resolve_stack(game)

    assert any("every target is illegal (608.2b)" in line for line in game.log)
    assert [card.name for card in game.players[0].graveyard] == ["Ray of Command"]
    assert bears.tapped
    assert not bears.metadata.get("haste_until_eot")
