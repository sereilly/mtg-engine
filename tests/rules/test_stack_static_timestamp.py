"""CR 613.7a / 613.7d: a static ability that functions on the stack has the
timestamp of the spell it is on, which is the moment that spell was put there.

    As long as Torrent of Lava is on the stack, each creature has "{T}: Prevent
    the next 1 damage that would be dealt to this creature by Torrent of Lava
    this turn."

The granted ability is a layer-6 effect like any other, so it is ordered
against "loses all abilities" by timestamp (CR 613.1f, CR 613.7): a Torrent
cast under a Humility grants its ability — the grant is the newer effect —
and a Humble cast *in response to* the Torrent takes it, because the loss is.

The refresh recorded the static the spell applies and nothing about the spell,
so the one reader that orders a grant against the loss
(``Permanent.effective_card``) had no stamp to compare and kept the grant
whatever the loss's age.

**The census is the pool.** Two cards print "As long as … is on the stack":
Kaervek's Torch, whose clause is a cost increase (CR 601.2f, no layer and no
timestamp), and Torrent of Lava. Every effect that takes all abilities and can
be applied while a spell is on the stack is tried against it, in both orders
the stack allows.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_catalog
from engine.faces import compilation_units, whole_card
from engine.global_statics import stack_statics_applying_to
from engine.models import Permanent, _abilities_stripped
from engine.stack_statics import grants_stack_static, stack_static_grants
from tests.helpers import _nosick, resolve_stack

_SHIELD = "prevent the next 1 damage"


@pytest.fixture(scope="module")
def _by_name():
    catalog = load_catalog()
    named = {card.name: card for card in catalog}
    named.update({unit.name: unit for unit in compilation_units(catalog)})
    return named


def _new_game(by_name):
    game = Game(players=[
        PlayerState(name=f"P{seat}", library=[by_name["Island"]] * 12)
        for seat in range(2)
    ])
    game.enforce_mana_costs = False
    game.interactive_seats = set()
    game.active_player_index = 0
    game.current_turn_phase = "precombat_main"
    game.current_step = "precombat_main"
    return game


def _put(game, by_name, name, seat=0):
    permanent = Permanent(card=by_name[name])
    game._put_permanent_onto_battlefield(seat, permanent, None)
    _nosick(permanent)
    game._recompute_continuous_effects()
    return permanent


def _queue(game, by_name, name, **announced):
    game.players[0].hand.append(whole_card(by_name[name]))
    result = game.queue_from_hand(0, name, **announced)
    assert result.supported, result
    game._recompute_continuous_effects()
    return game.stack[-1]


def _has_the_shield(game, permanent) -> bool:
    game._recompute_continuous_effects()
    listed = any(
        ability.instruction.kind == "grant_prevention_shield"
        for ability in game.usable_abilities_of(permanent)
    )
    printed = _SHIELD in (permanent.effective_card.oracle_text or "").lower()
    assert listed == printed, (listed, printed)
    return listed


@pytest.mark.cr("113.6b")
def test_the_pool_prints_one_static_that_grants_from_the_stack(_by_name):
    """The census's population, held: a second card printing a static that
    grants from the stack belongs in the two tests below."""
    grants = sorted(
        card.name for card in compilation_units(load_catalog())
        if grants_stack_static(card)
        and stack_static_grants(card.oracle_text or "", card.name)
    )
    assert grants == ["Torrent of Lava"]


@pytest.mark.cr("613.7a", "613.7d")
def test_a_spell_that_grants_from_the_stack_is_stamped_as_it_is_put_there(_by_name):
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    torrent = _queue(game, _by_name, "Torrent of Lava", x_value=1)

    assert torrent.timestamp is not None
    assert torrent.timestamp > bears.timestamp
    # …and that stamp is what the permanent it reaches records.
    assert [stamp for _static, stamp in stack_statics_applying_to(bears)] == [
        torrent.timestamp
    ]
    assert _has_the_shield(game, bears)

    resolve_stack(game)
    game._recompute_continuous_effects()
    assert stack_statics_applying_to(bears) == []
    assert not _has_the_shield(game, bears)

    # A spell with no such ability is ordered by nothing and is not stamped.
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    assert _queue(
        game, _by_name, "Giant Growth", target_permanent_ids=[bears.permanent_id]
    ).timestamp is None


@pytest.mark.cr("613.1f", "613.7a", "613.7d")
def test_a_torrent_cast_under_humility_grants_and_a_humble_in_response_takes(
    _by_name,
):
    # The loss, then the grant: Humility was there first, so the Torrent's
    # ability is the newer effect and every creature has it.
    game = _new_game(_by_name)
    bears = _put(game, _by_name, "Grizzly Bears")
    _put(game, _by_name, "Humility")
    assert _abilities_stripped(bears)
    assert not _has_the_shield(game, bears)
    _queue(game, _by_name, "Torrent of Lava", x_value=2)
    assert _has_the_shield(game, bears)
    # …and it works: tapped in response, the 1/1 takes one less than X.
    result = game.activate_permanent_ability(
        0, bears.card.name, permanent_index=game.battlefield_index_of(bears),
    )
    assert result.supported, result
    assert bears.tapped
    assert bears.damage_marked == 1

    # The grant, then the loss: Humble resolves while the Torrent is still on
    # the stack, so the loss is the newer effect and takes the granted ability
    # with the printed ones. It was kept.
    game = _new_game(_by_name)
    sorcerer = _put(game, _by_name, "Prodigal Sorcerer")
    bystander = _put(game, _by_name, "Grizzly Bears")
    torrent = _queue(game, _by_name, "Torrent of Lava", x_value=1)
    assert _has_the_shield(game, sorcerer)
    _queue(game, _by_name, "Humble", target_permanent_ids=[sorcerer.permanent_id])
    assert game.resolve_top_of_stack()
    assert game.stack == [torrent]
    assert _abilities_stripped(sorcerer)
    assert not _has_the_shield(game, sorcerer)
    assert game.usable_abilities_of(sorcerer) == []
    # The creature beside it was not Humbled and still has it.
    assert _has_the_shield(game, bystander)

    # …and the Torrent then deals its damage to a creature that could not
    # shield itself: the Humbled 0/1 dies to X = 1.
    resolve_stack(game)
    game.check_state_based_actions()
    assert not game.is_on_battlefield(sorcerer)
