"""CR 605.1a's fourth criterion, held over the pool.

    605.1a An activated ability is a mana ability if it meets all of the
    following criteria: it doesn't require a target (see rule 115.6), it could
    add mana to a player's mana pool when it resolves, it's not a loyalty
    ability (see rule 606, "Loyalty Abilities"), and its cost and effect don't
    move any card to or from a library. Do not take into account replacement
    effects that may apply, other than self-replacement effects, when
    evaluating these criteria.

The last clause arrived in the September 2026 edition. The engine first met it
as a Scryfall ruling (Millikin, 2026-08-05) while the rules file in the repo
was April's, and held it to the one cost that ruling named. ``engine/
mana_payment.is_mana_ability`` asks the whole of it now, and asks the effect
half **fail-closed**: a zone-moving step beside an add-mana step is presumed to
move a library card unless it has been read and does not
(``LIBRARY_SAFE_ZONE_KINDS``).

A presumption is only honest while somebody reads what it presumes about. So
this file holds every zone-moving step a mana-producing ability carries, in
either manifest role, to a verdict a person gave it - a card ingested tomorrow
with a step nobody has read fails here rather than being quietly presumed.

The rules themselves are ``tests/rules/test_mana_abilities_and_libraries.py``.
"""
from __future__ import annotations

from functools import lru_cache

from engine import mana_payment
from engine.card_loader import load_cards, manifest_set_paths
from engine.faces import compilation_units
from engine.grammar.lowering.categories import INSTRUCTION_CATEGORIES
from engine.mana_payment import (LIBRARY_MOVING_COSTS, LIBRARY_SAFE_ZONE_KINDS,
                                 MANA_PRODUCING_KINDS, _every_nested_step,
                                 is_mana_ability, steps_carried_out_now)
from engine.oracle import compile_card_oracle

#: Every zone-moving step that rides beside an add-mana step in the pool, and
#: what reading the card said about libraries. ``True`` moves a card to or from
#: one; ``False`` was read and does not (and so must be on the engine's safe
#: list); a string is a step whose verdict nothing turns on, with the reason.
_READ = {
    # "Add one mana of any color. Draw a card." - Chromatic Sphere and the five
    # Eggs. A draw is a card leaving a library (CR 121.1).
    "draw_controller_cards": True,
    # Gemstone Mine and the five storage lands: "…If there are no mining
    # counters on this land, sacrifice it." Battlefield to graveyard.
    "sacrifice_self": False,
    # Undiscovered Paradise: "During your next untap step, as you untap your
    # permanents, return this land to its owner's hand." Battlefield to hand.
    "return_self_instead_of_untapping": False,
    # Metalworker: "Reveal any number of artifact cards in your hand. Add
    # {C}{C} for each card revealed this way." Nothing changes zone.
    "reveal_cards_from_hand": False,
    # Chandra, Heart of Fire's -9 searches a graveyard and a library and adds
    # six {R}. A loyalty ability is not a mana ability whatever else it does
    # (the third criterion), so neither step's verdict is ever asked.
    "search_and_exile_matching": "a loyalty ability's step (Chandra, Heart of Fire)",
    "grant_cast_permission": "a loyalty ability's step (Chandra, Heart of Fire)",
}


@lru_cache(maxsize=1)
def _mana_producing_abilities() -> tuple:
    """``(card name, index, ability)`` for every activated ability in either
    manifest role whose effect has an add-mana step."""
    found, seen = [], set()
    for card in compilation_units(load_cards(manifest_set_paths(include_measured=True))):
        if card.name in seen:
            continue
        seen.add(card.name)
        for index, ability in enumerate(compile_card_oracle(card).activated_abilities):
            instruction = ability.instruction
            if instruction is None:
                continue
            steps = (instruction, *_every_nested_step(instruction))
            if any(step.kind in MANA_PRODUCING_KINDS for step in steps):
                found.append((card.name, index, ability))
    return tuple(found)


def _zone_steps(ability) -> set[str]:
    return {
        step.kind for step in steps_carried_out_now(ability.instruction)
        if INSTRUCTION_CATEGORIES.get(step.kind) == "zones"
    }


def test_every_zone_moving_step_beside_a_mana_step_has_been_read():
    rows = _mana_producing_abilities()
    assert len(rows) >= 380, len(rows)

    carried: dict[str, list[str]] = {}
    for name, _index, ability in rows:
        for kind in _zone_steps(ability):
            carried.setdefault(kind, []).append(name)

    unread = {kind: sorted(names) for kind, names in carried.items() if kind not in _READ}
    assert not unread, (
        "a mana-producing ability carries a zone-moving step nobody has read; "
        "it is being presumed to move a library card (CR 605.1a). Read the card, "
        f"then give the step a verdict here and on the engine's safe list: {unread}"
    )
    # The safe list is exactly what was read and found safe - an entry there
    # with no card behind it, or a card read as safe and left off it, is the
    # list and the reading disagreeing.
    assert {kind for kind, verdict in _READ.items() if verdict is False} == set(
        LIBRARY_SAFE_ZONE_KINDS
    )
    assert set(_READ) <= set(carried), sorted(set(_READ) - set(carried))


def test_the_abilities_the_fourth_criterion_excludes_are_the_ones_that_were_read():
    """Named, both halves: what a library-moving **cost** excludes and what a
    library-moving **effect** does - and the two cards a delayed draw leaves
    alone (CR 603.7: the delayed ability is another ability)."""
    by_cost, by_effect, verdicts = set(), set(), {}
    for name, index, ability in _mana_producing_abilities():
        verdicts[(name, index)] = is_mana_ability(ability)
        if any(getattr(ability.cost, field, 0) for field in LIBRARY_MOVING_COSTS):
            by_cost.add(name)
        elif getattr(ability.cost, "loyalty", None) is None and mana_payment.moves_a_library_card(
            ability.instruction
        ):
            by_effect.add(name)

    assert by_cost == {"Millikin", "Charmed Pendant"}
    assert by_effect == {
        "Chromatic Sphere", "Darkwater Egg", "Mossfire Egg", "Shadowblood Egg",
        "Skycloud Egg", "Sungrass Egg",
    }
    for name in by_cost | by_effect:
        assert not verdicts[(name, 0)], name
    for name in ("Barbed Sextant", "Astrolabe", "Undiscovered Paradise", "Metalworker",
                 "Gemstone Mine", "Sol Ring", "Adarkar Wastes"):
        assert verdicts[(name, 0)], name
    assert sum(verdicts.values()) >= 370, sum(verdicts.values())


def test_the_criterion_is_what_decides_these(monkeypatch):
    """Backwards, both ways. With every zone step called safe the six that
    draw are mana abilities again - the reading this repo shipped on the April
    rules. With nothing called safe, the lands that sacrifice or return
    themselves stop being mana abilities, which is what the safe list is for."""
    rows = {name: ability for name, index, ability in _mana_producing_abilities() if index == 0}

    zones = frozenset(kind for kind, cat in INSTRUCTION_CATEGORIES.items() if cat == "zones")
    monkeypatch.setattr(mana_payment, "LIBRARY_SAFE_ZONE_KINDS", zones)
    assert is_mana_ability(rows["Chromatic Sphere"]) and is_mana_ability(rows["Darkwater Egg"])
    assert not is_mana_ability(rows["Millikin"]), "its cost mills: the cost half still answers"

    monkeypatch.setattr(mana_payment, "LIBRARY_SAFE_ZONE_KINDS", frozenset())
    assert not is_mana_ability(rows["Gemstone Mine"])
    assert not is_mana_ability(rows["Undiscovered Paradise"])
    assert not is_mana_ability(rows["Metalworker"])
    assert is_mana_ability(rows["Sol Ring"])
