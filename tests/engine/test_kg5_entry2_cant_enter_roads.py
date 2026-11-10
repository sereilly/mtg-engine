"""Census: every road that can carry a land out of a zone onto the
battlefield asks CR 614.17's "can't" before it takes the card — or is listed
with the reason its card is never a land out of a zone.

    614.17 Some effects state that something can't happen. These effects
    aren't replacement effects, but follow similar rules.

Worms of the Earth, "Lands can't enter the battlefield" — its ruling
(2004-10-04): "an effect that 'puts a land onto the battlefield' won't do
anything, and the land will stay where it is". The battlefield funnel
(``ZoneFunnelsMixin._begin_entry``) asks the ``cant_enter_battlefield``
registration, but by then the road has taken the card out of its zone, and on
round kg5's chain (e245e624c) a land Show and Tell, Elvish Pioneer, Untamed
Wilds or Planar Birth put down under Worms went to no zone at all. The roads
ask ``permanent_cards.stays_out_of_battlefield`` — which answers CR 400.4a and
this together — or ``cant_enter_sources``, the registration's predicates
asked purely.

``test_kg5_kindred_entry_roads.py`` holds the same callers to CR 400.4a; its
"permanent card by construction" reasons do not answer this (a land *is* a
permanent card), so this census keeps its own table: roads whose card is never
a land out of a zone, each for a stated reason, and the pool census below
holds every reason that is a claim about cards.

Validated backwards: over the chain's sources the first test names 9 of the
38 callers. The roads that already called ``stays_out_of_battlefield`` pass it
by name there, though on the chain it asked CR 400.4a alone — the predicate's
new half is held by ``tests/regressions/test_kg5_entry2_worms_roads.py``,
whose search and Planar Birth boards go through two of those roads and fail on
the chain.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from engine.card_loader import load_catalog
from engine.replacements.zone_changes import discard_to_battlefield
from engine.search_filters import card_has_any_type

ENGINE = Path(__file__).resolve().parents[2] / "engine"
FUNNEL = "_put_permanent_onto_battlefield"
ASKS = frozenset({"stays_out_of_battlefield", "cant_enter_sources"})

#: Callers whose question is asked by a function in front of them, before the
#: card leaves its zone.
ASKED_UPSTREAM = {
    "handlers/reanimation.py:_return_planned_cards":
        "handlers/reanimation.py:return_all_cards_from_graveyard",
    "mixins/stack/choices/pile_picks.py:_move_picked_pile_card":
        "mixins/stack/choices/pile_picks.py:_resolve_opponent_picks_revealed",
    "mixins/stack/choices/search.py:_place_found_card":
        "mixins/stack/choices/search.py:_resolve_search_library_picks",
    # A land play: refused before the land leaves the hand.
    "mixins/stack/resolution.py:_resolve_card":
        "mixins/stack/casting.py:_cast_onto_stack",
}

#: Callers whose card is never a land taken out of a zone, and why.
NEVER_A_LAND_FROM_A_ZONE = {
    "handlers/tokens.py:create_token":
        "a token is no card in a zone (CR 111.1); the funnel's can't means it "
        "is never created",
    "mixins/permanent_state.py:create_token_copy": "a token copy (CR 707.2)",
    "mixins/stack/choices/card_names.py:_resolve_name_and_strip": "the tokens it makes",
    "mixins/stack/choices/spells.py:_resolve_face_down_cast":
        "a face-down spell, a 2/2 creature with no land type (CR 708.2)",
    "replacements/permanents.py:_resolve_entry_discard_toll":
        "the permanent already on its way in (Mox Diamond's toll is its own "
        "entry, asked again at the funnel)",
    "handlers/stack.py:_redirect_countered_card":
        "a countered spell — a land is never a spell (CR 305.9)",
    "handlers/reanimation.py:reanimate_aura_onto_source":
        "an Aura card (census: no Aura card is a land)",
    "mixins/oracle_instructions.py:_apply_aura_effect":
        "a card whose primary type is creature (census: none is a land)",
    "replacements/zone_changes.py:discarded_onto_battlefield":
        "the discarded card's own Dodecapod sentence (census: no land prints it)",
}


def _units(tree: ast.Module):
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node
        elif isinstance(node, ast.ClassDef):
            for inner in node.body:
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield inner


def _called(unit) -> set[str]:
    names = set()
    for node in ast.walk(unit):
        if isinstance(node, ast.Call):
            func = node.func
            names.add(getattr(func, "attr", None) or getattr(func, "id", None))
    return names


@pytest.fixture(scope="module")
def engine_calls() -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for path in sorted(ENGINE.rglob("*.py")):
        rel = path.relative_to(ENGINE).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for unit in _units(tree):
            calls.setdefault(f"{rel}:{unit.name}", set()).update(_called(unit))
    return calls


def test_every_road_that_can_carry_a_land_asks_cr_614_17(engine_calls):
    callers = {key for key, names in engine_calls.items() if FUNNEL in names}
    assert len(callers) >= 30, sorted(callers)
    unanswered = []
    for key in sorted(callers):
        if engine_calls[key] & ASKS:
            continue
        upstream = ASKED_UPSTREAM.get(key)
        if upstream is not None:
            if not engine_calls.get(upstream, set()) & ASKS:
                unanswered.append(f"{key}: its upstream {upstream} asks nothing")
            continue
        if key in NEVER_A_LAND_FROM_A_ZONE:
            continue
        unanswered.append(key)
    assert not unanswered, (
        "a road onto the battlefield that never asks whether a land can enter "
        "(CR 614.17, permanent_cards.stays_out_of_battlefield) before it takes "
        "the card out of its zone — ask it, or list why its card is never a "
        "land:\n  " + "\n  ".join(unanswered)
    )


def test_the_tables_name_only_callers_that_do_not_ask(engine_calls):
    callers = {key for key, names in engine_calls.items() if FUNNEL in names}
    stale = [
        key for key in (*ASKED_UPSTREAM, *NEVER_A_LAND_FROM_A_ZONE)
        if key not in callers or engine_calls[key] & ASKS
    ]
    assert not stale, stale


def test_the_never_a_land_reasons_hold_on_the_pool():
    """The claims ``NEVER_A_LAND_FROM_A_ZONE`` makes about cards: no Aura card
    is a land, no card whose primary type is creature is a land, and no land
    prints Dodecapod's sentence (the discard event's own reader,
    ``discard_to_battlefield``). A set that ships Dryad Arbor or an Aura land turns this
    red, which is when those roads have to ask."""
    examined = {"aura": 0, "creature": 0, "dodecapod": 0}
    wrong = []
    for card in load_catalog():
        is_land = card_has_any_type(card, ("land",))
        if "Aura" in (card.type_line or ""):
            examined["aura"] += 1
            if is_land:
                wrong.append((card.name, "an Aura land"))
        if card.primary_type == "creature":
            examined["creature"] += 1
            if is_land:
                wrong.append((card.name, "a creature-primary land"))
        if any(
            discard_to_battlefield(line) is not None
            for line in (card.oracle_text or "").splitlines()
        ):
            examined["dodecapod"] += 1
            if is_land:
                wrong.append((card.name, "a land printing Dodecapod's sentence"))
    assert not wrong, wrong
    assert examined["aura"] >= 100 and examined["creature"] >= 2000, examined
    assert examined["dodecapod"] >= 1, examined
