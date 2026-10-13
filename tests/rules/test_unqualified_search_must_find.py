"""CR 701.23d — a search "simply for a quantity of cards, such as 'a card' or
'three cards'" must find that many, "or as many as possible, if the zone
doesn't contain enough cards".

CR 701.23b is the other sentence: a search "for cards with a stated quality,
such as a card with a certain card type or color" need not find them even if
they are there — the zone is hidden, and nobody can check.

The engine enforced the floor for a counted search (Intuition's three cards)
and exempted every search for **one** card, because the single-find prompt's
decline was its one way out of a restriction the picker and the resolver might
read differently. A search for "a card" has no restriction to read, and was
exempt all the same: Demonic Tutor and Entomb offered "fail to find" and took
it (Phase 5).

Census over the pool's 129 library searches, both manifest roles: 13 name no
quality and one card, and all 13 accepted the decline — Demonic Tutor,
Diabolic Intent, Diabolic Tutor, Entomb, Extract, Gamble, Grim Tutor, Grinning
Totem, Noble Benefactor, Planar Portal, Rhystic Tutor, Rootwater Thief,
Vampiric Tutor. None does; the 90 with a stated quality and the 21 "up to"
searches still may.
"""
from __future__ import annotations

import pytest

from engine import Game, PlayerState, load_cards
from engine.card_loader import manifest_set_paths
from engine.faces import compilation_units
from engine.game_types import OracleExecutionContext
from engine.models import Permanent
from engine.oracle import compile_card_oracle
from engine.search_filters import search_matches, search_names_a_quality
from tests.helpers import resolve_stack

#: Floors, because a sweep that reaches nothing passes. 126 driven searches on
#: the day, 13 of them for one card of no stated quality.
_MIN_SEARCHES = 110
_MIN_UNQUALIFIED = 12


def _duel(catalog_by_name, *, library=None, interactive=True):
    names = ("Forest", "Grizzly Bears", "Sol Ring", "Lightning Bolt")
    deck = [catalog_by_name[name] for name in names] if library is None else library
    me = PlayerState(name="P0", life=20, library=list(deck))
    you = PlayerState(name="P1", life=20, library=list(deck))
    game = Game(players=[me, you])
    game.enforce_mana_costs = False
    if interactive:
        game.interactive_seats = {0, 1}
    return game, me, you


def _cast(game, me, card):
    me.hand = [card]
    assert game.queue_from_hand(0, card.name).supported
    resolve_stack(game)


@pytest.mark.cr("701.23d")
def test_701_23d_a_search_for_a_card_cannot_fail_to_find(catalog_by_name):
    game, me, _you = _duel(catalog_by_name)
    _cast(game, me, catalog_by_name["Demonic Tutor"])
    search = game.pending_choice_of("search_library", 0)
    assert search is not None

    assert game.decline_search_library(0) is False
    assert game.pending_choice_of("search_library", 0) is search
    assert len(me.library) == 4 and me.hand == []

    ring = next(i for i, card in enumerate(me.library) if card.name == "Sol Ring")
    assert game.confirm_search_library(0, ring)
    assert [card.name for card in me.hand] == ["Sol Ring"]


@pytest.mark.cr("701.23d")
def test_701_23d_as_many_as_possible_is_none_from_an_empty_library(catalog_by_name):
    """ "…or as many as possible, if the zone doesn't contain enough cards":
    an empty library holds none, and leaving the search is the only answer."""
    game, me, _you = _duel(catalog_by_name, library=[])
    _cast(game, me, catalog_by_name["Demonic Tutor"])

    assert game.decline_search_library(0) is True
    assert game.pending_choice_of("search_library", 0) is None


@pytest.mark.cr("701.23b")
def test_701_23b_a_search_with_a_stated_quality_may_still_fail_to_find(
    catalog_by_name,
):
    game, me, _you = _duel(catalog_by_name)
    _cast(game, me, catalog_by_name["Enlightened Tutor"])
    assert game.pending_choice_of("search_library", 0) is not None

    # A Sol Ring is right there, and nobody can check.
    assert game.decline_search_library(0) is True
    assert game.pending_choice_of("search_library", 0) is None


@pytest.mark.cr("701.23d")
def test_701_23d_a_seat_nobody_asks_finds_a_card(catalog_by_name):
    """The default answer is a find too: a policy that picked nothing falls
    back to the first card the search admits, not to the decline."""
    game, me, _you = _duel(catalog_by_name, interactive=False)
    _cast(game, me, catalog_by_name["Demonic Tutor"])
    game.auto_resolve_pending_choices()

    assert len(me.hand) == 1 and len(me.library) == 3


# -- The pool -----------------------------------------------------------------

def _walk(value):
    if hasattr(value, "kind") and hasattr(value, "payload"):
        yield value
        yield from _walk(value.payload)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item)


def _armed_searches(catalog_by_name):
    """``(card name, game, choice)`` for every ``search_library`` step in the
    pool that arms its prompt when run for an interactive seat."""
    pool = load_cards(manifest_set_paths(include_measured=True))
    deck = [
        catalog_by_name[name]
        for name in ("Forest", "Grizzly Bears", "Sol Ring", "Lightning Bolt",
                     "Island", "Disenchant")
    ] * 2
    seen: set[tuple[str, str]] = set()
    for unit in compilation_units(pool):
        program = compile_card_oracle(unit)
        if not program.supported:
            continue
        roots = list(program.instructions)
        roots += [ability.instruction for ability in program.activated_abilities]
        roots += [trigger.instruction for trigger in program.triggered_abilities]
        for root in roots:
            for step in _walk(root):
                if step.kind != "search_library" or (unit.name, repr(step)) in seen:
                    continue
                seen.add((unit.name, repr(step)))
                game, me, you = _duel(catalog_by_name, library=deck)
                source = None
                type_line = (unit.type_line or "").lower()
                if "instant" not in type_line and "sorcery" not in type_line:
                    source = Permanent(card=unit)
                    me.battlefield.append(source)
                try:
                    game._execute_oracle_instruction(step, OracleExecutionContext(
                        caster=me, target=you, card=unit,
                        source_permanent=source, trigger_context={},
                    ))
                except Exception:  # noqa: BLE001 - a step that needs its event
                    continue
                for choice in game.pending_choices_of("search_library")[:1]:
                    yield unit.name, game, choice


@pytest.mark.cr("701.23d", "701.23b")
def test_every_search_in_the_pool_may_fail_to_find_exactly_when_the_rules_say(
    catalog_by_name,
):
    pool = load_cards(manifest_set_paths(include_measured=True))
    searches = 0
    unqualified: list[str] = []
    wrong: list[str] = []
    for name, game, choice in _armed_searches(catalog_by_name):
        searches += 1
        data = choice.data
        quality = search_names_a_quality(data)
        may_stop_early = bool(data.get("up_to"))
        if not quality:
            # "Names no quality" and "admits every card" are one fact: a
            # narrowing added to the predicate and not counted there would
            # make a restricted search one that must find.
            refused = [
                card.name for card in pool
                if not search_matches(card, data, game=game, owner=choice.player_index)
            ]
            assert not refused, (name, refused[:3])
            if not may_stop_early:
                unqualified.append(name)
        declined = game.decline_search_library(choice.player_index)
        must_find = not quality and not may_stop_early
        if declined == must_find:
            wrong.append(
                f"{name}: {'no quality' if not quality else 'a stated quality'}"
                f"{', up to' if may_stop_early else ''} — decline "
                f"{'accepted' if declined else 'refused'}"
            )

    assert searches >= _MIN_SEARCHES, searches
    assert len(unqualified) >= _MIN_UNQUALIFIED, unqualified
    assert not wrong, wrong
