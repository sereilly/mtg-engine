"""Madness (CR 702.35).

CR 702.35a: "'Madness [cost]' means 'If a player would discard this card, that
player discards it, but exiles it instead of putting it into their graveyard'
and 'When this card is exiled this way, its owner may cast it by paying [cost]
rather than paying its mana cost. If that player doesn't, they put this card
into their graveyard.'" CR 702.35b: the cast follows the alternative-cost rules.
CR 608.2g: a spell an effect lets a player cast during resolution is cast
there, becomes the topmost object, and the resolving ability then finishes.

The rulings every madness card carries (Scryfall, all dated 2022-12-08) that
these tests hold the engine to, quoted:

* "A card with madness that's discarded counts as having been discarded even
  though it's put into exile rather than a graveyard. If it was discarded to
  pay a cost, that cost is still paid. Abilities that trigger when a card is
  discarded will still trigger."
* "Casting a spell with madness ignores the timing rules based on the card's
  card type."
* "To determine the total cost of a spell, start with the mana cost or
  alternative cost (such as a madness cost) you're paying, add any cost
  increases, then apply any cost reductions."
* "If you discard a card with madness to pay the cost of a spell or activated
  ability, that card's madness triggered ability (and the spell that card
  becomes, if you choose to cast it) will resolve before the spell or ability
  the discard paid for."
* "Madness works independently of why you're discarding the card. You could
  discard it … because you have too many cards in your hand during your
  cleanup step."

The pool is both manifest roles: the day this file was written every card
printing the keyword was in Torment, which is still measured.
"""
from __future__ import annotations

import dataclasses
from functools import lru_cache

import pytest

from engine import Game, PlayerState
from engine.card_loader import load_cards, manifest_set_paths
from engine.cast_permissions import playable_from_zones
from engine.madness import (MADNESS_CAST_KIND, MADNESS_TRIGGER, has_madness,
                            is_madness_line, printed_madness_cost)
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, resolve_stack


@lru_cache(maxsize=None)
def _pool() -> dict:
    names: dict = {}
    for path in manifest_set_paths(include_measured=True):
        for card in load_cards(path):
            names.setdefault(card.name, card)
    return names


def _madness_cards() -> list[str]:
    return sorted(name for name, card in _pool().items() if has_madness(card))


def _card(name):
    return _pool()[name]


def _discard_from_hand(game, seat, card):
    """The discard seam, as a forced discard reaches it: out of the hand, then
    ``Game._discard_card`` (which raises the CR 614 ``discard`` event)."""
    assert game.take_card_from_hand(seat, card)
    game._discard_card(game.players[seat], card)


def _two_seats(p0_kw=None, p1_kw=None, *, interactive=(0,)):
    game = Game(players=[
        PlayerState(name="P0", **(p0_kw or {})),
        PlayerState(name="P1", **(p1_kw or {})),
    ])
    game.enforce_mana_costs = True
    game.interactive_seats = set(interactive)
    return game


@pytest.mark.cr("702.35a")
def test_702_35a_every_madness_card_in_the_pool_is_read():
    """Each card printing the keyword compiles with the trigger CR 702.35a
    defines it as, carrying its printed cost — and was not, before
    ``engine/madness.py``: four were refused and six read supported with the
    keyword dropped."""
    names = _madness_cards()
    assert len(names) >= 10, names
    for name in names:
        card = _card(name)
        program = compile_card_oracle(card)
        assert program.supported, (name, program.reason)
        triggers = [
            t for t in program.triggered_abilities
            if t.condition.kind == MADNESS_TRIGGER
        ]
        assert len(triggers) == 1, name
        assert triggers[0].instruction.kind == MADNESS_CAST_KIND
        assert triggers[0].instruction.payload["cost"] == printed_madness_cost(card)


@pytest.mark.cr("702.35a")
def test_702_35a_a_madness_cost_nothing_can_charge_refuses_the_card():
    """An {X} madness cost (printed in later sets) announces a number nothing
    asks for; read as 0 it would cast the spell for less than it prints. The
    card is refused naming the line, never admitted with the keyword dropped."""
    temper = _card("Fiery Temper")
    probe = dataclasses.replace(
        temper, name="Probe Temper",
        oracle_text="Probe Temper deals 3 damage to any target.\nMadness {X}{R}",
    )
    program = compile_card_oracle(probe)
    assert not program.supported
    assert "madness" in program.reason.lower()


@pytest.mark.cr("702.35a")
def test_702_35a_a_sentence_about_madness_costs_is_not_a_madness_line():
    assert is_madness_line("Madness {1}{R} (If you discard this card, …)")
    assert not is_madness_line("Madness costs you pay cost {2} less.")


@pytest.mark.cr("702.35a", "400.7")
@pytest.mark.parametrize("name", _madness_cards())
def test_702_35a_every_madness_card_discarded_is_exiled_and_offers_its_cast(name):
    """The census: each card in the pool, discarded through the seam, goes to
    exile rather than the graveyard, its trigger goes on the stack, and its
    owner is asked. Declined, it goes to the graveyard and the offer's
    permission is gone with the answer."""
    card = _card(name)
    game = _two_seats({"hand": [card]})
    _discard_from_hand(game, 0, card)
    assert any(held is card for held in game.players[0].exile), name
    assert card not in game.players[0].graveyard
    trigger = game.stack[-1]
    assert trigger.card is card and trigger.ability_effect_kind == "triggered_cast"
    game.resolve_top_of_stack(pause_for_choices=True)
    offer = game.pending_choice_of("madness_cast", 0)
    assert offer is not None and offer.data["cost"] == printed_madness_cost(card)
    # While it stands, the card is castable from exile for exactly that price.
    entry = next(e for e in playable_from_zones(game, 0) if e["zone"] == "exile")
    assert entry["index"] == 0
    assert game.confirm_madness_cast(0, False)
    assert game.players[0].graveyard == [card]
    assert not game.players[0].exile
    assert game.pending_choice_of("madness_cast", 0) is None
    assert not game.cast_permissions
    assert not game.stack


def _aquamoeba_board(madness_name, *, lands=("Mountain",), opponent=("Grizzly Bears",)):
    aqua = _nosick(Permanent(card=_card("Aquamoeba")))
    game = _two_seats(
        {
            "battlefield": [aqua] + [Permanent(card=_card(land)) for land in lands],
            "hand": [_card(madness_name)],
            "library": [_card("Island")] * 5,
        },
        {"battlefield": [Permanent(card=_card(name)) for name in opponent]},
    )
    return game, aqua


@pytest.mark.cr("608.2g", "702.35a")
def test_608_2g_the_madness_spell_lands_above_the_trigger_which_then_finishes():
    """Discarded to pay Aquamoeba's cost, Fiery Temper's trigger goes on the
    stack *above* the ability it paid for (the ruling quoted above). Answered,
    the spell becomes the topmost object, the trigger leaves, and the ability
    the discard paid for is still underneath — resolving last."""
    game, aqua = _aquamoeba_board("Fiery Temper")
    bears = game.players[1].battlefield[0]
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    assert [item.card.name for item in game.stack] == ["Aquamoeba", "Fiery Temper"]
    held = game.stack[-1]
    assert held.resolution_held and game.pending_choice_of("madness_cast", 0)

    # Unpaid, the cast is refused and the offer stays: CR 601.2h.
    refused: list = []
    assert not game.confirm_madness_cast(
        0, True, target_permanent_ids=[bears.permanent_id], target_player_index=1,
        outcome=refused,
    )
    assert "insufficient mana" in refused[-1].details
    assert game.pending_choice_of("madness_cast", 0) is not None
    assert any(card.name == "Fiery Temper" for card in game.players[0].exile)

    assert game.tap_land_for_mana(0, "Mountain")
    assert game.confirm_madness_cast(
        0, True, target_permanent_ids=[bears.permanent_id], target_player_index=1,
    )
    assert [item.card.name for item in game.stack] == ["Aquamoeba", "Fiery Temper"]
    assert game.stack[-1] is not held and not game.stack[-1].ability_effect_kind
    assert game.pending_choice_of("madness_cast", 0) is None
    resolve_stack(game)
    game.check_state_based_actions()
    assert [c.name for c in game.players[1].graveyard] == ["Grizzly Bears"]
    assert [c.name for c in game.players[0].graveyard] == ["Fiery Temper"]
    # The ability the discard paid for resolved last.
    assert (aqua.effective_power, aqua.effective_toughness) == (3, 1)


@pytest.mark.cr("702.35a", "701.9a")
def test_702_35a_the_discard_still_happens_for_every_watcher():
    """Megrim — "Whenever an opponent discards a card" — sees a madness discard:
    only the destination is replaced."""
    card = _card("Obsessive Search")
    game = _two_seats(
        {"hand": [card]},
        {"battlefield": [Permanent(card=_card("Megrim"))]},
        interactive=(),
    )
    _discard_from_hand(game, 0, card)
    resolve_stack(game)
    assert game.players[0].life == 18
    assert any("Megrim dealt 2 damage to P0" in line for line in game.log)


@pytest.mark.cr("616.1e", "616.1f", "702.35a")
def test_616_1_madness_and_library_of_leng_contend_for_one_discard():
    """Library of Leng and madness both replace where one discarded card goes.

    * A discard nobody is asked about takes the default — madness first, the
      order the discarding player would choose (the exile is what offers the
      cheap cast), after which the Library has no graveyard move left.
    * A chosen discard that sends the card to the top of the library has
      applied the Library first, and madness then has nothing to replace.
    * The same discard sent to the graveyard declined the Library's "you may",
      and CR 616.1f re-asks madness, which applies.
    """
    leng = _card("Library of Leng")
    search = _card("Obsessive Search")

    game = _two_seats(
        {"battlefield": [Permanent(card=leng)], "hand": [search]}, interactive=(0,),
    )
    _discard_from_hand(game, 0, search)
    assert any(held is search for held in game.players[0].exile)
    assert game.stack and game.stack[-1].card is search

    for to_library, expected in ((True, "library"), (False, "exile")):
        game = _two_seats(
            {"battlefield": [Permanent(card=leng)], "hand": [search],
             "library": [_card("Island")] * 3},
            {"battlefield": [Permanent(card=_card("Swamp")) for _ in range(2)],
             "hand": [_card("Mind Rot")]},
            interactive=(0,),
        )
        game.enforce_mana_costs = False
        game.active_player_index = 1
        assert game.queue_from_hand(1, "Mind Rot", target_player_index=0).supported
        game.resolve_top_of_stack(pause_for_choices=True)
        assert game.pending_choice_of("discard", 0) is not None
        assert game.confirm_discard(0, [0], to_library=to_library)
        if expected == "library":
            assert game.players[0].library[0] is search
            assert not game.players[0].exile
            assert game.pending_choice_of("madness_cast", 0) is None
        else:
            assert any(held is search for held in game.players[0].exile)
            assert any(item.card is search for item in game.stack)


@pytest.mark.cr("702.35a", "514.1", "514.3a")
def test_514_3a_a_madness_card_discarded_to_hand_size_is_cast_and_the_step_repeats():
    """Discarded at cleanup, Obsessive Search is cast for {U} and draws — so the
    hand is over its maximum again, and CR 514.3a's second cleanup step takes
    another card. Before, the trigger waited on the stack into the next turn."""
    search = _card("Obsessive Search")
    island = _card("Island")
    game = _two_seats(
        {"battlefield": [Permanent(card=island)],
         "hand": [search] + [island] * 7,
         "library": [_card("Mountain")] * 4},
        interactive=(),
    )
    game.active_player_index = 0
    assert game.resolve_cleanup_step(0)
    assert not game.stack
    assert any("cast Obsessive Search for its madness cost" in line for line in game.log)
    assert len(game.players[0].hand) == 7
    assert [c.name for c in game.players[0].graveyard] == ["Obsessive Search", "Island"]


@pytest.mark.cr("118.9d", "118.9c", "702.35b")
def test_118_9d_a_cost_increase_applies_to_the_madness_cost():
    """Under Sphere of Resistance ("Spells cost {1} more to cast") Fiery
    Temper's madness cost is {1}{R}: one Mountain is refused, two pay it — and
    the spell's mana value is still its printed 3 (CR 118.9c)."""
    game, _aqua = _aquamoeba_board(
        "Fiery Temper", lands=("Mountain", "Mountain"), opponent=(),
    )
    game.players[1].battlefield.append(Permanent(card=_card("Sphere of Resistance")))
    assert game.activate_permanent_ability(0, "Aquamoeba", cost_hand_index=0).supported
    game.tap_land_for_mana(0, "Mountain", permanent_index=1)
    refused: list = []
    assert not game.confirm_madness_cast(0, True, target_player_index=1, outcome=refused)
    assert "insufficient mana" in refused[-1].details
    game.tap_land_for_mana(0, "Mountain", permanent_index=2)
    assert game.confirm_madness_cast(0, True, target_player_index=1)
    assert game.stack[-1].card.cmc == 3
    resolve_stack(game)
    assert game.players[1].life == 17


@pytest.mark.cr("400.7", "702.35a")
def test_400_7_a_card_that_left_exile_is_neither_cast_nor_binned():
    """With the trigger on the stack the card leaves exile; the card that comes
    back is a new object the ability does not know — no offer, no graveyard."""
    card = _card("Fiery Temper")
    game = _two_seats({"hand": [card]})
    _discard_from_hand(game, 0, card)
    assert game.take_card_from_exile(0, card)
    game.resolve_top_of_stack(pause_for_choices=True)
    assert game.pending_choice_of("madness_cast", 0) is None
    assert not game.players[0].graveyard
    assert not game.stack
    assert any("no longer in exile" in line for line in game.log)


@pytest.mark.cr("608.2g", "702.35a")
def test_608_2g_a_madness_creature_is_cast_on_an_opponents_turn_after_the_spell_finishes():
    """Mind Rot, cast by the active player, makes the other discard Arrogant
    Wurm. The Wurm is exiled at once; its trigger waits for Mind Rot to finish
    resolving (the ruling), and the Wurm — a creature — is then cast on an
    opponent's turn for {2}{G}, timing being no part of a cast during
    resolution."""
    game = _two_seats(
        {"battlefield": [Permanent(card=_card("Forest")) for _ in range(3)],
         "hand": [_card("Arrogant Wurm"), _card("Forest")]},
        {"battlefield": [Permanent(card=_card("Swamp")) for _ in range(3)],
         "hand": [_card("Mind Rot")]},
        interactive=(),
    )
    game.active_player_index = 1
    for slot in range(3):
        game.tap_land_for_mana(1, "Swamp", permanent_index=slot)
    assert game.cast_from_hand(1, "Mind Rot", target_player_index=0).supported
    game.auto_resolve_pending_choices()
    resolve_stack(game)
    log = game.log
    bin_mind_rot = next(i for i, line in enumerate(log) if "Mind Rot resolved" in line)
    cast_wurm = next(i for i, line in enumerate(log) if "Arrogant Wurm cast for its madness cost" in line)
    assert bin_mind_rot < cast_wurm
    assert [p.card.name for p in game.players[0].battlefield].count("Arrogant Wurm") == 1
    assert all(land.tapped for land in game.players[0].battlefield if land.card.name == "Forest")
