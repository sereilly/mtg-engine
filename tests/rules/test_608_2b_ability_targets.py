"""CR 608.2b asked of an **ability**: its targets, checked again as it resolves.

    "If the spell or ability specifies targets, it checks whether the targets
    are still legal. A target that's no longer in the zone it was in when it
    was targeted is illegal. Other changes to the game state may cause a
    target to no longer be legal; for example, its characteristics may have
    changed … If all its targets, for every instance of the word 'target,' are
    now illegal, the spell or ability doesn't resolve. … Otherwise, the spell
    or ability will resolve normally. Illegal targets, if any, won't be
    affected by parts of a resolving spell's effect for which they're illegal."

``legality_resolution.illegal_targets_refusal`` asked this of instants and sorceries and
declined every ability. An **activated** ability's targets are an announcement
like a spell's — chosen by a player (CR 602.2b), held to the picker's list
before a cost is paid, recorded on the stack object — and so are a **triggered**
ability's where its own picker chose them (CR 603.3d). Both are asked now; a
target a fire site merely stamped is not (``legality.announced_by_a_choice``).

Every card here is invented, so nothing in this file can pass against a table
keyed by a name. The pool-wide census is
``tests/engine/test_ability_target_resolution_census.py``.

Its own file per SET_PLAYBOOK's block convention — a group's rules tests do not
share a file, so a mechanical union has nothing to splice.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.keywords import grant_keyword
from engine.models import CardDefinition, Permanent
from tests.helpers import _mk_card, resolve_stack

_W2G3_REMOVED = "every target is illegal (608.2b)"


def _w2g3_card(name: str, type_line: str, text: str = "", *, colors=(), power=2, toughness=2):
    return _mk_card(
        name=name, type_line=type_line, oracle_text=text, colors=colors,
        power=power, toughness=toughness,
    )


def _w2g3_put(game, seat: int, card) -> Permanent:
    permanent = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, permanent, None)
    permanent.metadata["summoning_sickness_turn"] = -99
    return permanent


def _w2g3_table() -> Game:
    filler = _w2g3_card("W2G3 Filler", "Land")
    game = Game(players=[
        PlayerState(name="P0", library=[filler] * 6),
        PlayerState(name="P1", library=[filler] * 6),
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    return game


def _w2g3_leave(game, permanent) -> None:
    seat = game.controller_index_of(permanent)
    game.remove_from_battlefield(permanent)
    game.players[seat].graveyard.append(permanent.card)


_W2G3_BEAR = _w2g3_card("W2G3 Bear", "Creature - Bear")
_W2G3_OX = _w2g3_card("W2G3 Ox", "Creature - Ox", power=1, toughness=4)
_W2G3_ELK = _w2g3_card("W2G3 Elk", "Creature - Elk", power=3, toughness=3)

#: A targeted sentence with an untargeted one printed behind it.
_W2G3_TOTEM = _w2g3_card(
    "W2G3 Totem", "Artifact",
    "{T}: Target creature gets +2/+2 until end of turn. You gain 2 life.",
)


@pytest.mark.cr("608.2b")
def test_an_activated_ability_whose_only_target_left_does_not_resolve():
    """The whole-object half. The targeted sentence does nothing, the sentence
    printed behind it does not happen, nothing is done to the creature beside
    the one that left, and the cost stays paid."""
    game = _w2g3_table()
    totem = _w2g3_put(game, 0, _W2G3_TOTEM)
    bear = _w2g3_put(game, 0, _W2G3_BEAR)
    ox = _w2g3_put(game, 0, _W2G3_OX)

    queued = game.queue_permanent_ability(
        0, _W2G3_TOTEM.name, target_permanent_ids=[bear.permanent_id],
    )
    assert queued.supported and queued.details == "queued", queued
    _w2g3_leave(game, bear)
    resolve_stack(game)

    assert any(_W2G3_REMOVED in line for line in game.log), game.log[-4:]
    assert game.players[0].life == 20, "the sentence behind the target did not happen"
    assert (ox.effective_power, ox.effective_toughness) == (1, 4), "nor did a bystander get it"
    assert totem.tapped, "CR 608.2b refunds nothing"
    assert not game.stack


@pytest.mark.cr("608.2b", "702.18a")
def test_a_target_that_gained_shroud_is_illegal_though_it_is_still_there():
    """"Other changes to the game state may cause a target to no longer be
    legal." Shroud gained in response: the creature is on the battlefield and
    is still a creature, which is everything a handler's own re-check asked."""
    game = _w2g3_table()
    _w2g3_put(game, 0, _W2G3_TOTEM)
    bear = _w2g3_put(game, 0, _W2G3_BEAR)

    assert game.queue_permanent_ability(
        0, _W2G3_TOTEM.name, target_permanent_ids=[bear.permanent_id],
    ).supported
    grant_keyword(bear, "shroud")
    resolve_stack(game)

    assert any(_W2G3_REMOVED in line for line in game.log), game.log[-4:]
    assert (bear.effective_power, bear.effective_toughness) == (2, 2)
    assert game.players[0].life == 20


@pytest.mark.cr("608.2b", "702.16b")
def test_a_target_that_gained_protection_from_the_source_is_illegal():
    """The rule's own example, for an ability: protection from the quality of
    the ability's **source** (CR 702.16b), gained while the ability waits."""
    pinger = _w2g3_card(
        "W2G3 Pinger", "Creature - Wizard",
        "{T}: This creature deals 1 damage to target creature. Draw a card.",
        colors=("R",), power=1, toughness=1,
    )
    game = _w2g3_table()
    _w2g3_put(game, 0, pinger)
    ox = _w2g3_put(game, 1, _W2G3_OX)

    assert game.queue_permanent_ability(
        0, pinger.name, target_permanent_ids=[ox.permanent_id],
    ).supported
    ox.metadata["protection_from_red"] = True
    resolve_stack(game)

    assert any(_W2G3_REMOVED in line for line in game.log), game.log[-4:]
    assert ox.damage_marked == 0
    assert game.players[0].hand == [], "no card: the ability did not resolve"


@pytest.mark.cr("608.2b", "702.18a")
def test_a_player_who_gained_shroud_is_an_illegal_target_of_an_ability():
    """CR 702.18a: "This permanent **or player** can't be the target of spells
    or abilities." The named player gains shroud in response and loses no
    life."""
    drain = _w2g3_card("W2G3 Leech", "Artifact", "{T}: Target player loses 1 life.")
    mask = _w2g3_card("W2G3 Mask", "Enchantment", "You have shroud.")
    game = _w2g3_table()
    _w2g3_put(game, 0, drain)

    assert game.queue_permanent_ability(0, drain.name, target_player_index=1).supported
    _w2g3_put(game, 1, mask)
    resolve_stack(game)

    assert any(_W2G3_REMOVED in line for line in game.log), game.log[-4:]
    assert game.players[1].life == 20


@pytest.mark.cr("608.2b")
def test_an_ability_whose_target_is_still_legal_resolves_in_full():
    """The control: nothing in response, so nothing is removed and both
    printed sentences happen."""
    game = _w2g3_table()
    _w2g3_put(game, 0, _W2G3_TOTEM)
    bear = _w2g3_put(game, 0, _W2G3_BEAR)

    assert game.queue_permanent_ability(
        0, _W2G3_TOTEM.name, target_permanent_ids=[bear.permanent_id],
    ).supported
    resolve_stack(game)

    assert (bear.effective_power, bear.effective_toughness) == (4, 4)
    assert game.players[0].life == 22
    assert not any("608.2b" in line for line in game.log)


@pytest.mark.cr("608.2b", "602.2b")
def test_a_bare_activation_is_judged_by_the_target_it_was_given():
    """A bare activation — the headless caller's convention — is given the
    first entry of its picker's list as it is announced
    (``engine/bare_announcements.py``), here the Bear, so it has a target like
    any named one. Removing the Bear in response leaves every target illegal:
    the ability does nothing at all, and no handler's pick puts the +2/+2 on
    the Ox instead."""
    game = _w2g3_table()
    _w2g3_put(game, 0, _W2G3_TOTEM)
    bear = _w2g3_put(game, 0, _W2G3_BEAR)
    ox = _w2g3_put(game, 0, _W2G3_OX)

    assert game.queue_permanent_ability(0, _W2G3_TOTEM.name).supported
    assert game.stack[-1].target_permanent_id == [bear.permanent_id] or (
        game.stack[-1].target_permanent_id == bear.permanent_id
    ), game.stack[-1].target_permanent_id
    _w2g3_leave(game, bear)
    resolve_stack(game)

    assert any("608.2b" in line for line in game.log), game.log[-4:]
    assert (ox.effective_power, ox.effective_toughness) == (1, 4), game.log[-4:]
    assert game.players[0].life == 20


@pytest.mark.cr("608.2b")
def test_one_illegal_target_of_two_is_left_alone_and_nothing_takes_its_place():
    """"Otherwise, the spell or ability will resolve normally. Illegal
    targets, if any, won't be affected." Two creatures named, one given shroud
    in response: the ability resolves for the other, the shrouded one is not
    tapped, and the third creature on that battlefield is not tapped in its
    stead."""
    net = _w2g3_card("W2G3 Net", "Artifact", "{T}: Tap up to two target creatures.")
    game = _w2g3_table()
    _w2g3_put(game, 0, net)
    bear = _w2g3_put(game, 1, _W2G3_BEAR)
    ox = _w2g3_put(game, 1, _W2G3_OX)
    elk = _w2g3_put(game, 1, _W2G3_ELK)

    assert game.queue_permanent_ability(
        0, net.name, target_permanent_ids=[bear.permanent_id, ox.permanent_id],
    ).supported
    grant_keyword(bear, "shroud")
    resolve_stack(game)

    assert not bear.tapped, "the illegal target is not affected"
    assert ox.tapped, game.log[-4:]
    assert not elk.tapped, "and no creature is tapped in its place"
    assert not any(_W2G3_REMOVED in line for line in game.log)


@pytest.mark.cr("608.2b")
def test_one_departed_target_of_two_does_not_hand_its_slot_to_a_bystander():
    """The same announcement, the first target gone instead. Its battlefield
    slot now holds the third creature — which the index beside the recorded id
    would have named — and that creature is not tapped."""
    net = _w2g3_card("W2G3 Net", "Artifact", "{T}: Tap up to two target creatures.")
    game = _w2g3_table()
    _w2g3_put(game, 0, net)
    bear = _w2g3_put(game, 1, _W2G3_BEAR)
    elk = _w2g3_put(game, 1, _W2G3_ELK)
    ox = _w2g3_put(game, 1, _W2G3_OX)

    assert game.queue_permanent_ability(
        0, net.name, target_player_index=1, target_permanent_index=[0, 2],
    ).supported
    _w2g3_leave(game, bear)
    resolve_stack(game)

    assert ox.tapped, game.log[-4:]
    assert not elk.tapped, "the creature that slid into slot 0 was never named"


@pytest.mark.cr("608.2b", "603.3d")
def test_a_trigger_whose_chosen_target_became_illegal_does_not_resolve():
    """CR 603.3d chooses a triggered ability's target as it is put on the
    stack; CR 608.2b then asks about it as it resolves. The entry trigger's
    picker chooses the one creature there is, that creature gains shroud in
    response, and it is not destroyed."""
    reaper = _w2g3_card(
        "W2G3 Reaper", "Creature - Horror",
        "When this creature enters, destroy target creature an opponent controls.",
    )
    game = _w2g3_table()
    bear = _w2g3_put(game, 1, _W2G3_BEAR)
    _w2g3_put(game, 0, reaper)
    (item,) = game.stack
    assert item.targets_chosen and item.target_permanent_id == bear.permanent_id

    grant_keyword(bear, "shroud")
    resolve_stack(game)

    assert any(_W2G3_REMOVED in line for line in game.log), game.log[-4:]
    assert game.is_on_battlefield(bear)


@pytest.mark.cr("608.2b", "603.3d")
def test_a_trigger_whose_chosen_target_is_still_legal_resolves():
    reaper = _w2g3_card(
        "W2G3 Reaper", "Creature - Horror",
        "When this creature enters, destroy target creature an opponent controls.",
    )
    game = _w2g3_table()
    bear = _w2g3_put(game, 1, _W2G3_BEAR)
    _w2g3_put(game, 0, reaper)

    resolve_stack(game)

    assert not game.is_on_battlefield(bear)
    assert not any("608.2b" in line for line in game.log)


@pytest.mark.cr("608.2b")
def test_a_blanked_slot_keeps_its_place_in_the_announcement():
    """"If part of the effect requires information about an illegal target,
    it fails to determine any such information." The illegal slot is rewritten
    in place, never removed: a reader that asks for slot 0 and slot 1 by
    position gets nothing for the first and the second creature for the second
    — not the second creature under the first one's number. An effect that
    compares its two targets depends on exactly that to find it has nothing to
    compare, rather than acting on the survivor alone."""
    from engine.game_types import OracleExecutionContext, StackItem
    from engine.handlers._targets import (resolve_target_permanents,
                                          resolve_target_slots)
    from engine.stack_targets import ChosenTarget, blank_illegal_targets, illegal_target_id

    game = _w2g3_table()
    bear = _w2g3_put(game, 1, _W2G3_BEAR)
    ox = _w2g3_put(game, 1, _W2G3_OX)
    item = StackItem(
        card=_W2G3_TOTEM, caster_index=0, target_player_index=1,
        target_permanent_index=[0, 1], x_value=None,
        target_permanent_id=[bear.permanent_id, ox.permanent_id],
    )

    blanked = blank_illegal_targets(
        item, [ChosenTarget("permanent", permanent_id=bear.permanent_id, position=0)],
    )

    assert blanked == 1
    assert item.target_permanent_id == [illegal_target_id(bear.permanent_id), ox.permanent_id]
    assert item.target_permanent_index == [None, 1]
    assert game.permanent_by_id(item.target_permanent_id[0]) is None, "it names nothing"
    context = OracleExecutionContext(
        caster=game.players[0], target=game.players[1], card=_W2G3_TOTEM,
        target_permanent_index=item.target_permanent_index,
        target_permanent_id=item.target_permanent_id,
    )
    assert resolve_target_slots(game, context, 2) == [None, ox]
    assert resolve_target_permanents(game, context) == [ox]
    # Blanking twice changes nothing.
    assert blank_illegal_targets(
        item, [ChosenTarget("permanent", permanent_id=bear.permanent_id, position=0)],
    ) == 1
    assert item.target_permanent_id == [illegal_target_id(bear.permanent_id), ox.permanent_id]
