"""A continuous effect whose duration ends on an **event** (CR 611.2a).

CR 611.2a says a continuous effect "lasts as long as stated by the spell or
ability creating it (such as 'until end of turn')" — and what the card states
need not be a moment in the turn structure at all. Every duration this engine
had before Urza's Saga was one: the cleanup step, the end of combat, a player's
next upkeep, each ended by a sweep that step already runs.

Soul Sculptor prints the other shape: "…until a player casts a creature spell".
`engine/event_durations.py` is the registry and the sweep; these are the rules
questions that shape has to answer, asked of the engine rather than of the
table.

The set-facing tests for the card itself are in
`tests/sets/test_usg_creatures.py`; these are the ones about the *rule*.
"""

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_path, manifest_set_paths
from engine.layer_bridge import computed_types
from engine.models import Permanent

from tests.helpers import resolve_stack


def _pool() -> dict:
    pool: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards([path]):
            pool.setdefault(card.name, card)
    return pool


POOL = _pool()
SOUL_SCULPTOR = {
    card.name: card for card in load_cards(manifest_set_path("USG", include_measured=True))
}["Soul Sculptor"]


def _sculpted(*, alice_hand=(), bob_hand=()):
    """Soul Sculptor's ability resolved on seat 1's Serra Angel."""
    sculptor = Permanent(card=SOUL_SCULPTOR)
    victim = Permanent(card=POOL["Serra Angel"])
    alice = PlayerState(name="A", battlefield=[sculptor],
                        hand=[POOL[name] for name in alice_hand])
    bob = PlayerState(name="B", battlefield=[victim],
                      hand=[POOL[name] for name in bob_hand])
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    sculptor.metadata["summoning_sickness_turn"] = -99
    game.activate_permanent_ability(
        0, "Soul Sculptor", permanent_index=0,
        target_player_index=1, target_permanent_index=0,
    )
    resolve_stack(game)
    return game, alice, bob, victim


@pytest.mark.cr("611.2a", "205.1a")
def test_a_stated_duration_need_not_be_a_turn_step():
    """611.2a: the effect lasts as long as the card states — and this card
    states an event. 205.1a: what it states is a *replacement* of the type
    line, so the permanent stops being a creature until the window closes."""
    _game, _alice, bob, victim = _sculpted(bob_hand=("Grizzly Bears",))

    assert computed_types(victim)[0] == {"enchantment"}
    assert not victim.is_creature


@pytest.mark.cr("611.2a", "613.1f")
def test_the_window_closes_when_the_stated_event_happens():
    """611.2a again, from the other side, and 613.1f's blanket removal with
    it: both halves of the one sentence end at the one moment."""
    game, _alice, _bob, victim = _sculpted(bob_hand=("Grizzly Bears",))
    assert victim.effective_card.oracle_text == ""

    game.cast_from_hand(1, "Grizzly Bears")

    assert computed_types(victim)[0] == {"creature"}
    assert game._has_keyword(victim, "flying")
    resolve_stack(game)


@pytest.mark.cr("601.2i", "701.6")
def test_the_window_closes_at_the_cast_and_a_counter_does_not_reopen_it():
    """601.2i: the spell *becomes cast* once it is on the stack, and abilities
    that watch for a cast trigger then. A window that ends "until a player
    casts a creature spell" ends at that same moment — so 701.6's counter,
    which happens afterwards, gives nothing back.

    A sweep hung off *resolution* instead would pass this test's first half and
    fail its second, which is why the moment is asserted rather than assumed.
    """
    game, alice, _bob, victim = _sculpted(
        alice_hand=("Counterspell",), bob_hand=("Grizzly Bears",),
    )

    game.cast_from_hand(1, "Grizzly Bears")
    assert computed_types(victim)[0] == {"creature"}

    game.cast_from_hand(0, "Counterspell", target_stack_index=0)
    resolve_stack(game)

    assert not any(item.card.name == "Grizzly Bears" for item in game.stack)
    assert computed_types(victim)[0] == {"creature"}


@pytest.mark.cr("514.2", "611.2a")
def test_the_cleanup_step_does_not_end_a_window_it_does_not_own():
    """514.2 ends "until end of turn" and "this turn" effects and nothing
    else. A window with no event yet does not expire at a turn boundary — it
    lasts as long as the card states (611.2a), which may be the whole game."""
    game, _alice, _bob, victim = _sculpted()

    for seat in (0, 1, 0, 1):
        game.resolve_cleanup_step(seat)

    assert computed_types(victim)[0] == {"enchantment"}
    assert victim.effective_card.oracle_text == ""


@pytest.mark.cr("608.2b")
def test_one_printed_target_is_one_legality_check():
    """608.2b checks a spell or ability's targets **once**, before its
    instructions run. Soul Sculptor's first instruction stops its own target
    being a creature; the second must still reach it, because the check that
    would have declined it already happened and passed.

    Asked here rather than only through the card because the shape is general:
    any sentence whose earlier clause changes what its later clause's noun
    phrase describes has it.
    """
    _game, _alice, _bob, victim = _sculpted()

    assert not victim.is_creature          # the first instruction ran…
    assert victim.effective_card.oracle_text == ""   # …and so did the second


@pytest.mark.cr("608.2d")
def test_a_choice_an_effect_offers_is_announced_while_it_is_applied():
    """608.2d: a choice that is not part of casting is made as the effect is
    applied. Turnabout's card type and its two alternatives are both such
    choices, and the prompts arrive in the printed order — the type first,
    because the sentence that spends it is behind it."""
    turnabout = {
        card.name: card
        for card in load_cards(manifest_set_path("USG", include_measured=True))
    }["Turnabout"]
    alice = PlayerState(name="A", hand=[turnabout])
    bob = PlayerState(name="B", battlefield=[Permanent(card=POOL["Island"])])
    bob.battlefield[0].tapped = True
    game = Game(players=[alice, bob])
    game.enforce_mana_costs = False
    game.interactive_seats = {0}

    game.cast_from_hand(0, "Turnabout", target_player_index=1)

    # The type first: the sentence that spends it is printed behind it, and
    # the resolution stops here rather than sweeping on the default.
    assert [choice.kind for choice in game.pending_choices] == ["card_type_choice"]
    assert game.waiting_prompt() is game.pending_choices[0], (
        "the game waits while the choice is owed (CR 117.3b)"
    )
    assert bob.battlefield[0].tapped, "nothing has been swept yet"

    # …and answering it arms the next decision of the *same* resolution, which
    # is what keeps a chain of choices one application of one effect.
    game.confirm_card_type_choice(0, "land")
    assert [choice.kind for choice in game.pending_choices] == ["mode_choice"]
    assert bob.battlefield[0].tapped

    game.resolve_pending_choice("mode_choice", 0, mode_index=1)
    resolve_stack(game)

    assert not bob.battlefield[0].tapped
