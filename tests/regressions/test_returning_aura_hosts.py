"""An Aura card a mass return puts onto the battlefield enchants something.

CR 303.4f: an Aura put onto the battlefield by an effect that names no host is
attached, as it enters, to an object its controller chooses that it could
legally enchant; CR 303.4g: with no such object it stays in its zone. Both
printings that reach this are sweeps of a graveyard — Replenish ("Return all
enchantment cards from your graveyard to the battlefield. (Auras with nothing
to enchant remain in your graveyard.)") and Cleansing Meditation's threshold
arm — and their shared rulings (2004-10-04, 2005-08-01) add the two halves
the rule leaves to the effect: placing the Aura "does not target the
permanent", and it "can only enchant something that was already on the
battlefield", never an enchantment returning beside it.

Found by Torment's wave 1 driving Cleansing Meditation: every returned Aura
entered attached to nothing and CR 704.5m put it straight back. Replenish had
shipped that way since Urza's Destiny — its reminder text names the case and
nothing read it.

The host is chosen for every seat by ``ai_policy.choose_returning_aura_host``;
asking an interactive seat is a prompt this round did not build.
"""

from __future__ import annotations

import pytest

from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


@pytest.fixture
def pool(set_pool):
    return {**set_pool("LEA"), **set_pool("UDS"), **set_pool("TOR")}


def _table(pool, *, hand0=(), gy0=(), bf0=(), bf1=()):
    game = Game(players=[
        PlayerState(
            name="P0", hand=[pool[n] for n in hand0],
            graveyard=[pool[n] for n in gy0], library=[pool["Forest"]] * 5,
        ),
        PlayerState(name="P1", library=[pool["Forest"]] * 5),
    ])
    game.enforce_mana_costs = False
    for seat, names in enumerate((bf0, bf1)):
        for name in names:
            game._put_permanent_onto_battlefield(seat, Permanent(card=pool[name]), None)
    return game


def _replenish(game):
    assert game.cast_from_hand(0, "Replenish").supported
    resolve_stack(game)
    game.check_state_based_actions()


def _hosts(game):
    """Each Aura on the battlefield, by name, with the name of what it enchants."""
    return sorted(
        (perm.card.name, getattr(perm.metadata.get("attached_to"), "card", None).name)
        for perm in game.all_permanents()
        if perm.metadata.get("attached_to") is not None
    )


def test_replenish_attaches_each_aura_by_what_it_does_to_its_host(pool):
    """A beneficial Aura goes on its controller's creature and a harmful one on
    an opponent's — the cast chooser's preference, asked of a choice that is
    not a target."""
    game = _table(
        pool, hand0=["Replenish"], gy0=["Holy Strength", "Paralyze"],
        bf0=["Grizzly Bears"], bf1=["Hill Giant"],
    )
    _replenish(game)
    assert _hosts(game) == [
        ("Holy Strength", "Grizzly Bears"), ("Paralyze", "Hill Giant"),
    ]
    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    assert (bears.effective_power, bears.effective_toughness) == (3, 4)
    assert game.players[0].graveyard == [pool["Replenish"]]


def test_an_aura_with_nothing_to_enchant_stays_in_the_graveyard(pool):
    """CR 303.4g, which Replenish's own reminder text spells out. Protection is
    a bar (CR 702.16c: Black Knight "can't be enchanted by Auras that have" the
    quality white) where shroud would not be: placing the Aura targets
    nothing."""
    game = _table(
        pool, hand0=["Replenish"], gy0=["Holy Strength", "Castle"],
        bf1=["Black Knight"],
    )
    _replenish(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Castle"]
    assert [c.name for c in game.players[0].graveyard] == ["Holy Strength", "Replenish"]
    assert any(
        "Holy Strength has nothing it could enchant" in line for line in game.log
    )


def test_a_returning_aura_cannot_enchant_another_card_returning_with_it(pool):
    """The rulings' second half: "An Enchant Enchantment returning to the
    battlefield can't be placed on an enchantment that is also in the process
    of returning." With only the Castle beside it, Feedback stays; with an
    enchantment already out, it goes there."""
    game = _table(pool, hand0=["Replenish"], gy0=["Feedback", "Castle"])
    _replenish(game)
    assert [p.card.name for p in game.controlled_by(0)] == ["Castle"]
    assert "Feedback" in [c.name for c in game.players[0].graveyard]

    game = _table(
        pool, hand0=["Replenish"], gy0=["Feedback", "Castle"], bf1=["Crusade"],
    )
    _replenish(game)
    assert _hosts(game) == [("Feedback", "Crusade")]


def test_cleansing_meditation_puts_its_returned_auras_back_on_creatures(pool):
    """Cleansing Meditation's threshold arm returns the caster's destroyed
    enchantments, Auras included — onto creatures that survived the sweep."""
    game = _table(
        pool, hand0=["Cleansing Meditation"], gy0=["Forest"] * 7,
        bf0=["Grizzly Bears"], bf1=["Hill Giant"],
    )
    from engine.auras import attach_aura

    bears = next(p for p in game.controlled_by(0) if p.card.name == "Grizzly Bears")
    strength = Permanent(card=pool["Holy Strength"])
    game._put_permanent_onto_battlefield(0, strength, None)
    attach_aura(strength, bears)
    resolve_stack(game)

    assert game.cast_from_hand(0, "Cleansing Meditation").supported
    resolve_stack(game)
    game.check_state_based_actions()
    assert _hosts(game) == [("Holy Strength", "Grizzly Bears")]
    assert strength not in list(game.all_permanents()), "a new object (CR 400.7)"
