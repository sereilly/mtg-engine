"""Urza's Destiny sorceries.

Opened on `main` before the wave-1 fan-out, per SET_PLAYBOOK.md's block
convention: **every group appends a delimited block and puts its own imports at
the top of that block**, never at the top of the file. A self-contained block
cannot lose an import to a mechanical union, and every group's first write is an
append rather than a file-creation collision.

    # --- W1G3: <the group's topic> ---
    from engine import Game, PlayerState
    ...

Two things the convention does not reach, both recorded in SET_PLAYBOOK.md and
both paid for: a helper whose last lines match another group's helper's last
lines is matched by git as common context, so a union can splice one body onto
the other's signature — give a helper a `_gN_` prefix and an ending that is its
own. And a block that must run *first* (a module-level `@pytest.mark.parametrize`
reading a name imported in a later block) does not survive a file split; keep
module-level code inside the block that imports what it reads.

Cards come from `set_pool("UDS")` / `set_cards("UDS")` — never a new
`conftest.py` fixture and never a spelled-out `cards/*.json` path
(`tests/sets/README.md`). Drain the stack with `tests.helpers.resolve_stack`,
never a bare `while game.stack:` loop — that spins forever once a seat is owed
a prompt.
"""


# --- W1G1: reveal any number of cards in your hand ---
from engine import Game, PlayerState
from engine.models import Permanent
from tests.helpers import resolve_stack


def _g1_reveal_spell_duel(set_pool, catalog_by_name, spell, hand, graveyard=()):
    """Alice holding *spell* plus *hand*, with *graveyard* behind her.

    Split from the instants' own helper rather than shared, because what these
    two sorceries need is a graveyard: Rofellos's Gift returns out of one, and
    a pile that is empty and a pile that has nothing matching are two different
    answers to the same printed sentence.
    """
    alice, bob = PlayerState(name="Alice"), PlayerState(name="Bob")
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    alice.hand = [set_pool("UDS")[spell]] + [
        catalog_by_name[name] for name in hand
    ]
    alice.graveyard = [catalog_by_name[name] for name in graveyard]
    return game, alice, bob


def test_scent_of_cinder_deals_one_damage_per_red_card(set_pool, catalog_by_name):
    """"Scent of Cinder deals X damage to any target, where X is the number of
    cards revealed this way."

    The card names itself where the Seer says "this creature", which is the
    same sentence with the same where-clause — so the two share a production
    and this is the half that proves the record is not the creature's.
    """
    game, _alice, bob = _g1_reveal_spell_duel(
        set_pool, catalog_by_name, "Scent of Cinder",
        ["Lightning Bolt", "Shivan Dragon", "Disintegrate", "Giant Growth"],
    )
    bob.life = 20

    result = game.cast_from_hand(0, "Scent of Cinder", target_player_index=1)
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert bob.life == 17


def test_scent_of_cinder_showing_nothing_deals_nothing(set_pool, catalog_by_name):
    """A hand with no red card in it reveals none and deals zero. The spell
    still resolves: "any number" includes none, and CR 608.2 finishes the
    resolution rather than refusing it."""
    game, _alice, bob = _g1_reveal_spell_duel(
        set_pool, catalog_by_name, "Scent of Cinder",
        ["Giant Growth", "Healing Salve"],
    )
    bob.life = 20

    result = game.cast_from_hand(0, "Scent of Cinder", target_player_index=1)
    resolve_stack(game)

    assert result.supported, game.log[-3:]
    assert bob.life == 20


def test_rofellos_gift_returns_one_enchantment_per_green_card(
    set_pool, catalog_by_name
):
    """"Return an enchantment card from your graveyard to your hand **for each
    card revealed this way**."

    A *repeated* return rather than a multiplied number, which is the fourth
    thing this group's one record is spent on: two green cards shown bring two
    enchantments back, one at a time, out of a pile holding three.
    """
    game, alice, _bob = _g1_reveal_spell_duel(
        set_pool, catalog_by_name, "Rofellos's Gift",
        ["Giant Growth", "Llanowar Elves", "Lightning Bolt"],
        graveyard=["Regeneration", "Instill Energy", "Holy Strength"],
    )

    result = game.cast_from_hand(0, "Rofellos's Gift")
    resolve_stack(game)
    # The graveyard pick is owed with the stack already empty, which
    # ``resolve_stack`` deliberately leaves alone — see its docstring. This is
    # the headless seat taking the same default an AI would.
    game.auto_resolve_pending_choices()

    assert result.supported, game.log[-3:]
    returned = [c.name for c in alice.hand]
    assert sum(1 for name in returned if name in
               ("Regeneration", "Instill Energy", "Holy Strength")) == 2
    assert [c.name for c in alice.graveyard] == [
        "Holy Strength", "Rofellos's Gift"
    ], "one enchantment left behind, and the spell on top of it"


def test_rofellos_gift_returns_nothing_from_an_empty_graveyard(
    set_pool, catalog_by_name
):
    """The count is a ceiling on the repetitions, not a promise: a graveyard
    with no enchantment in it answers none however many cards were shown, and
    the spell still resolves."""
    game, alice, _bob = _g1_reveal_spell_duel(
        set_pool, catalog_by_name, "Rofellos's Gift",
        ["Giant Growth", "Llanowar Elves"],
        graveyard=["Grizzly Bears"],
    )

    result = game.cast_from_hand(0, "Rofellos's Gift")
    resolve_stack(game)
    game.auto_resolve_pending_choices()

    assert result.supported, game.log[-3:]
    assert [c.name for c in alice.hand] == ["Giant Growth", "Llanowar Elves"]
    assert [c.name for c in alice.graveyard] == ["Grizzly Bears", "Rofellos's Gift"]
