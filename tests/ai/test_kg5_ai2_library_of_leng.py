"""Library of Leng's "you may put it on top of your library instead" is
answered one way on every road a seat nobody asks discards by.

"If an effect causes you to discard a card, discard it, but you may put it
on top of your library instead of into your graveyard." Two seams decided it
for a seat nobody asks, and they disagreed (kg5's ``asks``, measured and
left):

* a discard the seat **chooses** — the ``discard`` prompt, whose default
  (``choices/hand._default_discard``) always answered ``to_library=False``:
  Mind Rot put the Lightning Bolt in the graveyard;
* a discard it does **not** — at random, an opponent's pick out of a revealed
  hand, an each-player discard answered inline — reaching the Library's own
  replacement (``replacements/zone_changes``), whose offer's default was the
  top for every card: Hymn to Tourach put a spare Swamp back on top, to be
  drawn again in place of a fresh card.

Both ask ``ai_prompt_picks.takes_library_top`` now: a card worth holding the
graveyard does not keep goes on top; one with a road back from there, a
payable madness cost, or nothing to offer (a spare land) goes to the
graveyard; with no library left anything goes on top.

The census casts every shipped instant and sorcery that makes a player
discard at a non-interactive Library of Leng controller holding cards worth
holding, then spare lands, and holds each discarded card's destination to the
reader. On the base 32 of its rows disagreed, in both directions.
"""

from __future__ import annotations

from collections import Counter
from functools import lru_cache

import pytest

from engine import Game, PlayerState, faces
from engine.ai_prompt_picks import takes_library_top
from engine.ai_weighed_cast import _effect_steps
from engine.card_loader import load_catalog
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from tests.helpers import _nosick, settle

#: The effect kinds that make a player discard (``handlers/discards.py``,
#: ``handlers/reveal.py``).
_DISCARD_KINDS = frozenset({
    "discard_target_cards", "discard_x_target_cards", "discard_all_matching_cards",
    "discard_hand", "each_player_discards_a_card", "each_player_discards_up_to_cards",
    "each_opponent_discards_cards", "discard_revealed_card",
    "discard_revealed_unless_pay_life", "discard_revealed_matching_unless_pay_life",
})
_WORTH_HOLDING = ("Shivan Dragon", "Lightning Bolt", "Giant Growth")
_SPARE_LANDS = ("Mountain", "Forest", "Swamp")


@lru_cache(maxsize=None)
def _catalog() -> dict:
    return {card.name: card for card in load_catalog()}


def _discard_spells() -> list:
    found = []
    for unit in faces.compilation_units(sorted(_catalog().values(), key=lambda c: c.name)):
        if unit.primary_type not in ("instant", "sorcery"):
            continue
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        kinds = {step.kind for instr in program.instructions for step in _effect_steps(instr)}
        if kinds & _DISCARD_KINDS:
            found.append(unit)
    return found


def _board(spell, hand, *, interactive=()) -> Game:
    cards = _catalog()
    leng = PlayerState(name="Leng", hand=[cards[n] for n in hand],
                       library=[cards["Island"]] * 8)
    caster = PlayerState(name="Caster", hand=[spell], library=[cards["Island"]] * 8)
    game = Game(players=[leng, caster])
    game.enforce_mana_costs = False
    game.interactive_seats = set(interactive)
    for name in ("Library of Leng", "Plains", "Plains", "Plains"):
        permanent = Permanent(card=cards[name])
        game._put_permanent_onto_battlefield(0, permanent, None)
        _nosick(permanent)
    game.active_player_index = 1
    game.priority_player_index = 1
    game.current_turn_phase = game.current_step = "precombat_main"
    game._sync_control()
    return game


def _destinations(game, hand, library_before: int) -> dict:
    """Each card of *hand* that left it, mapped to "top" or "graveyard"."""
    player = game.players[0]
    on_top = Counter(card.name for card in player.library[:len(player.library) - library_before])
    binned = Counter(card.name for card in player.graveyard)
    found = {}
    still = Counter(card.name for card in player.hand)
    for name in hand:
        if still[name]:
            still[name] -= 1
            continue
        if on_top[name]:
            on_top[name] -= 1
            found.setdefault(name, []).append("top")
        elif binned[name]:
            binned[name] -= 1
            found.setdefault(name, []).append("graveyard")
    return found


def test_every_discard_road_answers_the_library_one_way():
    """Every shipped discard spell at a seat nobody asks: each card it
    discards while the Library is still on the battlefield goes where
    ``takes_library_top`` says — whichever seam the spell's discard takes."""
    spells = _discard_spells()
    assert len(spells) >= 40, len(spells)
    rows, wrong = 0, []
    for spell in spells:
        for hand in (_WORTH_HOLDING, _SPARE_LANDS):
            game = _board(spell, hand)
            expected = {name: takes_library_top(game, 0, _catalog()[name]) for name in hand}
            library_before = len(game.players[0].library)
            if not game.cast_from_hand(1, spell.name, target_player_index=0).supported:
                continue
            settle(game)
            if not any(p.card.name == "Library of Leng" for p in game.controlled_by(0)):
                # Balancing Act sacrifices it, Void can destroy it: the
                # discards after are no offer of the Library's.
                continue
            went = _destinations(game, hand, library_before)
            if not went:
                continue
            rows += 1
            for name, places in went.items():
                for place in places:
                    if (place == "top") != expected[name]:
                        wrong.append((spell.name, name, place))
    assert rows >= 60, rows
    assert not wrong, wrong


@pytest.mark.parametrize("spell", ["Mind Rot", "Hymn to Tourach"])
def test_a_chosen_and_a_random_discard_keep_the_same_cards(spell):
    """Mind Rot's two cards are the seat's choice (the ``discard`` prompt);
    Hymn to Tourach's are at random (the Library's own offer). Out of a hand
    of a Shivan Dragon and a Lightning Bolt the seat keeps both on top either
    way; out of three spare lands it puts the discarded ones in the
    graveyard either way. On the base Mind Rot binned the spells and Hymn
    topped the lands."""
    for hand, place in ((("Shivan Dragon", "Lightning Bolt"), "top"), (_SPARE_LANDS, "graveyard")):
        game = _board(_catalog()[spell], hand)
        library_before = len(game.players[0].library)
        assert game.cast_from_hand(1, spell, target_player_index=0).supported
        settle(game)
        went = _destinations(game, hand, library_before)
        assert sum(len(places) for places in went.values()) == 2, (went, game.log[-8:])
        assert {p for places in went.values() for p in places} == {place}, (hand, went, game.log[-8:])


def test_a_person_is_still_asked_and_their_answer_stands():
    """The reader is a seat nobody asks' answer, never a person's: an
    interactive Library of Leng controller is offered the top on its own Mind
    Rot discard and its "graveyard" is what happens to the Dragon."""
    game = _board(_catalog()["Mind Rot"], ("Shivan Dragon", "Lightning Bolt"), interactive=(0,))
    assert game.cast_from_hand(1, "Mind Rot", target_player_index=0).supported
    owed = settle(game, defaults=False)
    assert owed is not None
    choice = game.pending_choice_of("discard", 0)
    assert choice is not None and choice.data.get("allow_top_of_library"), owed
    assert game.confirm_discard(0, [0, 1], to_library=False)
    settle(game)
    assert sorted(card.name for card in game.players[0].graveyard) == [
        "Lightning Bolt", "Shivan Dragon",
    ], game.log[-6:]


def test_an_empty_library_takes_the_top_whatever_the_card():
    """With nothing left to draw, a card on top is the next draw that does
    not lose the game (CR 704.5b) — a spare land included. Asked card by
    card: once one is there the seat has a draw, and Mind Rot's second spare
    land goes to the graveyard."""
    game = _board(_catalog()["Mind Rot"], _SPARE_LANDS)
    game.players[0].library.clear()
    assert takes_library_top(game, 0, _catalog()["Mountain"])
    assert game.cast_from_hand(1, "Mind Rot", target_player_index=0).supported
    settle(game)
    assert len(game.players[0].library) == 1, game.log[-6:]
    assert len(game.players[0].graveyard) == 1, game.log[-6:]
