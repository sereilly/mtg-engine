"""Which side of the table an Aura's host is on, read off what its triggered
abilities do to the host (``ai_targets._aura_harms_its_host``,
``ai_target_sides.host_trigger_side``).

Kudzu — "When enchanted land becomes tapped, destroy it. That land's
controller may attach this Aura to a land of their choice." — printed no
phrase the harm markers read, so the AI cast it on its own Forest, which it
then destroyed the first time it tapped the Forest for mana. Thirteen shipped
Auras read the same way: a trigger that destroys, sacrifices or gives away
its host (Blight, Mortal Wound, Lingering Death, Fractured Loyalty, …), or
shrinks or taps it (Spirit Shackle, Imprison), beside no printed gift.
"""

from __future__ import annotations

from functools import lru_cache

from engine import faces
from engine.ai_actions import cast_announcement
from engine.ai_payment import tap_planned_lands
from engine.ai_policy import choose_cast_action
from engine.ai_target_sides import host_trigger_side
from engine.ai_targets import _HOST_GIFT, _aura_harms_its_host
from engine.aura_attachment import auras_attached_to
from engine.card_loader import load_catalog
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle

from tests.helpers import _nosick, settle, stock_libraries


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _host_losing_auras() -> list:
    """Every shipped Aura with a triggered ability that works against its
    host, and no printed gift to it."""
    found = []
    cards = sorted(_catalog().values(), key=lambda each: each.name)
    for unit in faces.compilation_units(cards):
        if "Aura" not in (unit.type_line or ""):
            continue
        if _HOST_GIFT.search((unit.oracle_text or "").lower()):
            continue
        if any(
            host_trigger_side(trigger.instruction) == "opponent"
            for trigger in compile_card_oracle(unit).triggered_abilities
        ):
            found.append(unit)
    return found


def test_every_aura_whose_trigger_works_against_its_host_goes_on_an_opponents():
    """The census: each such Aura reads harmful, so its cast-target chooser
    (and the returning-Aura chooser, and a Licid's attach) aims it at an
    opponent's permanent. Validated backwards: on 59f133e63 thirteen of them
    read as gifts, Kudzu and Blight among them."""
    auras = _host_losing_auras()
    names = {aura.name for aura in auras}
    assert len(auras) >= 12, sorted(names)
    assert {"Kudzu", "Blight", "Spirit Shackle", "Lingering Death"} <= names
    assert [aura.name for aura in auras if not _aura_harms_its_host(aura)] == []


def test_a_printed_gift_keeps_the_aura_on_its_controllers_side():
    """Spinal Graft's +3/+3 and Aggression's first strike and trample are
    what their host-destroying triggers are the price of; Unstable Mutation's
    -1/-1 counter pays for +3/+3. None of them is read as harm."""
    for name in ("Spinal Graft", "Aggression", "Unstable Mutation"):
        card = _catalog()[name]
        assert any(
            host_trigger_side(t.instruction) == "opponent"
            for t in compile_card_oracle(card).triggered_abilities
        ), name
        assert not _aura_harms_its_host(card), name


def _table(hand, mine, theirs):
    catalog = _catalog()
    game = Game(players=[
        PlayerState(name="A", hand=[catalog[name] for name in hand]),
        PlayerState(name="B"),
    ])
    stock_libraries(game)
    for seat, names in ((0, mine), (1, theirs)):
        for name in names:
            permanent = Permanent(card=catalog[name])
            game._put_permanent_onto_battlefield(seat, permanent, None)
            _nosick(permanent)
    game.start_turn(0)
    settle(game)
    return game


def test_kudzu_is_cast_on_an_opponents_land_and_destroys_it_when_tapped():
    """The board the Known-gaps entry asked to verify in a game: an AI seat
    with Kudzu and three Forests, an opponent with a Mountain and an Island.
    The real chooser casts it on the opponent's land; when that land becomes
    tapped it is destroyed, and its controller moves Kudzu on — by default
    onto a land of the caster's (``default_prefers: not_the_choosers``)."""
    game = _table(["Kudzu"], ["Forest", "Forest", "Forest"], ["Mountain", "Island"])
    action = choose_cast_action(game, 0)
    assert action is not None and action.card_name == "Kudzu"
    assert action.target_player_index == 1
    action = tap_planned_lands(game, 0, action)
    assert game.queue_from_hand(0, "Kudzu", **cast_announcement(action)).supported
    settle(game)
    host = next(
        permanent for permanent in game.controlled_by(game.players[1])
        if any(aura.card.name == "Kudzu" for aura in auras_attached_to(permanent))
    )
    land = host.card.name
    game.become_tapped(host)
    settle(game)
    assert f"Kudzu destroyed {land}" in game.log
    assert not game.is_on_battlefield(host)
    assert all(
        permanent.card.name != land for permanent in game.controlled_by(game.players[1])
    )
