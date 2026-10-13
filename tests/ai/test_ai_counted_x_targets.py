"""A spell naming "up to X target …" where X is **counted off the board** is
aimed at the side its effect wants.

"Return up to X target creatures to their owners' hands, where X is one plus
the number of cards named Aether Burst in all graveyards as you cast this
spell." (Aether Burst.) `ai_policy._choose_several_targets` had three roads
for a counted list — a printed maximum, an X the caster pays for, and an X the
game counts — and the third fell through to the several-slot default at the
bottom of the function: *the caster's own board*, on the argument that every
card carrying the template gives a benefit per target. For a bounce that is
the seat returning its own creatures to its own hand, which is what an AI seat
did with every Aether Burst it cast.

Found by the whole-pool run of
``tests/regressions/test_ody_w2g2_zone_cast_census.py``, which casts every
card on a board with creatures on both sides.
"""
from __future__ import annotations

import pytest

from engine.ai_policy import (cast_announcement, choose_cast_action,
                              spell_being_cast, tap_planned_lands,
                              zone_being_cast_from)
from engine.ai_valuation import spell_target_side
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.game import Game
from engine.models import Permanent, PlayerState
from engine.oracle import compile_card_oracle
from engine.targeting import derive_cast_spec
from tests.helpers import _nosick, resolve_stack

ME, OPP = 0, 1


@pytest.fixture(scope="module")
def pool(set_pool, catalog_by_name):
    return {**catalog_by_name, **set_pool("ODY")}


def _duel(pool, *, hand, mine=(), theirs=(), graveyard=()):
    forest = pool["Forest"]
    me = PlayerState(
        name="AI", library=[forest] * 10, hand=[pool[name] for name in hand],
        graveyard=[pool[name] for name in graveyard],
        battlefield=[_nosick(Permanent(card=pool[name])) for name in mine],
    )
    opp = PlayerState(
        name="Opp", library=[forest] * 10,
        battlefield=[_nosick(Permanent(card=pool[name])) for name in theirs],
    )
    game = Game(players=[me, opp])
    game.enforce_mana_costs = True
    game.interactive_seats = set()
    game.active_player_index = ME
    game._sync_control()
    return game


def _cast(game, action):
    spell = spell_being_cast(zone_being_cast_from(game, ME, action), action)
    tap_planned_lands(game, ME, action)
    result = game.cast_from_hand(ME, spell.name, **cast_announcement(action))
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    return result


def _creatures(game, seat) -> list[str]:
    return [perm.card.name for perm in game.controlled_by(seat) if perm.is_creature]


def test_aether_burst_returns_an_opponents_creature_not_the_casters(pool):
    game = _duel(
        pool, hand=["Aether Burst"], mine=["Island", "Island", "Grizzly Bears"],
        theirs=["Hill Giant", "Craw Wurm"],
    )

    action = choose_cast_action(game, ME)

    assert action.card_name == "Aether Burst"
    assert (action.target_player_index, action.target_permanent_index) == (OPP, [0])
    assert _cast(game, action).supported
    assert _creatures(game, ME) == ["Grizzly Bears"]
    assert _creatures(game, OPP) == ["Craw Wurm"]
    assert [card.name for card in game.players[OPP].hand] == ["Hill Giant"]


def test_the_count_is_the_boards_and_every_slot_lands_on_that_side(pool):
    """One Aether Burst already in a graveyard: X is two, and both targets
    are the opponent's."""
    game = _duel(
        pool, hand=["Aether Burst"], mine=["Island", "Island", "Grizzly Bears"],
        theirs=["Hill Giant", "Craw Wurm"], graveyard=["Aether Burst"],
    )

    action = choose_cast_action(game, ME)

    assert (action.target_player_index, action.target_permanent_index) == (OPP, [0, 1])
    assert _cast(game, action).supported
    assert _creatures(game, ME) == ["Grizzly Bears"] and _creatures(game, OPP) == []


def test_with_nothing_on_the_other_side_it_is_not_cast(pool):
    """"Up to X" may name nobody, and the only creature to name is the
    caster's own: a card held, not a creature bounced."""
    game = _duel(pool, hand=["Aether Burst"], mine=["Island", "Island", "Grizzly Bears"])

    assert choose_cast_action(game, ME) is None


def test_reap_still_names_cards_in_its_casters_own_graveyard(pool):
    """The other card on this road: "Return up to X target cards from your
    graveyard to your hand, where X is the number of black permanents target
    opponent controls". Its slots are graveyard cards and only one graveyard
    is legal, so it reads as it did."""
    game = _duel(
        pool, hand=["Reap"], mine=["Swamp", "Forest"],
        theirs=["Drudge Skeletons", "Black Knight"],
        graveyard=["Grizzly Bears", "Hill Giant", "Craw Wurm"],
    )

    action = choose_cast_action(game, ME)

    assert action.card_name == "Reap"
    assert (action.target_player_index, action.target_permanent_index) == (ME, [0, 1])
    assert _cast(game, action).supported
    assert sorted(card.name for card in game.players[ME].hand) == [
        "Grizzly Bears", "Hill Giant",
    ]


def test_the_spells_on_this_road_are_the_two_named():
    """The census, with its floor: over both manifest roles, the spells whose
    several-target count is an X the *game* announces (rather than one the
    caster pays for) — each with a side this policy can read, or with only
    its caster's graveyard to name."""
    cards = load_cards(manifest_set_paths(include_measured=True))
    forest = next(card for card in cards if card.name == "Forest")
    game = Game(players=[
        PlayerState(name="AI", library=[forest] * 5),
        PlayerState(name="Opp", library=[forest] * 5),
    ])
    found = {}
    for card in compilation_units(cards):
        if card.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(card)
        if not program.supported or program.modes:
            continue
        spec = derive_cast_spec(card, program) or {}
        if not spec.get("x_targets"):
            continue
        if game.announced_cast_x(ME, card, mode_index=None) is None:
            continue
        found[card.name] = (spec.get("kind"), spell_target_side(card))

    assert len(found) >= 2, found
    assert found["Aether Burst"] == ("creature", "opponent")
    assert found["Reap"][0] == "graveyard_creature"
    for name, (kind, side) in found.items():
        assert side is not None or kind == "graveyard_creature", (
            f"{name} counts its targets off the board and names a battlefield "
            "object with no side this policy can read"
        )
