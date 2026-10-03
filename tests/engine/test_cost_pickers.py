"""Guard: a cost the payer chooses is a cost the payer is *asked* about.

CR 601.2b (casting) and CR 602.2b (activating) both say the announcing player
chooses how a cost is paid. This engine charges three such costs here —
sacrifice a permanent, discard a card, tap a permanent — and each needs a
picker derived for it, because the
picker is the only thing that carries the choice from the player to the engine.

**A missing picker does not look like a missing feature.** Both payment paths
had a deterministic fallback for a seat that names nothing, which is right for
AI and headless play and indistinguishable, from the outside, from a human seat
that was never asked: the cost was paid, the spell resolved, and the only sign
was that the card discarded was always the first one in hand. The discard
picker was missing from *both* paths for as long as the costs have existed, and
what finally surfaced it was the bug it was hiding — an index resolved against
the wrong list, which nothing could send because nothing could be asked.

So the guard is derived from the pool rather than from a list: every card whose
compiled program charges a choosable cost must answer with a spec that says so.
Adding the third such cost fails here until it has a picker too.
"""

from __future__ import annotations

import pytest

from engine.card_loader import manifest_set_paths, load_cards
from engine.cast_costs import additional_costs
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec

# The whole pool, measured sets included: a picker missing on a card nobody can
# deck yet is missing all the same, and this is exactly where it was found.
_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    for _card in load_cards(_path):
        _POOL.setdefault(_card.name, _card)

# The flag each choosable cost sets on the spec it derives. The *names* matter:
# they are what tells the client which field the answer rides, and a cost
# reported under the wrong one would be collected and then paid with something
# else.
_COST_FLAGS = ("sacrifice_cost", "discard_cost", "tap_cost")

# The gaps this guard found the day it was written are closed (round 52), so the
# list is empty. The mechanism stays: the two tests below are what force an
# entry back out again, and an empty list is the state to keep.
#
# What it caught, and why none of it looked like a missing feature: both payment
# paths fall back to a deterministic pick for a seat that names nothing, which is
# right for AI and headless play and indistinguishable from a human seat that was
# never asked. Atog's default ate the *Black Lotus* on a board that also held a
# Mox, because among equal-power permanents the tie breaks on permanent id.
_PICKERLESS_ACTIVATION_COSTS: set[tuple[str, int]] = set()


def _has_cost_picker(spec: dict | None) -> bool:
    """Whether *spec* describes the cost pick, in either of its two positions.

    A cost-only announcement reports the cost as the whole spec; an ability that
    also targets (Dwarven Weaponsmith) reports it under ``cost_spec`` beside the
    target, because CR 601.2b and CR 601.2c are two announcements carrying two
    fields. Accepting only the first would have made the guard demand that the
    target be dropped to make room for the cost.
    """
    if spec is None:
        return False
    if any(spec.get(flag) for flag in _COST_FLAGS):
        return True
    nested = spec.get("cost_spec")
    return isinstance(nested, dict) and any(nested.get(flag) for flag in _COST_FLAGS)


def _cast_cost_cards() -> list[tuple[str, str]]:
    """Every ``(card, zone)`` whose cast **from that zone** charges a choosable
    cost.

    The zone is part of the question rather than a detail of it: Demonic Embrace
    charges a discard when it is cast from the graveyard and nothing at all when
    it is cast from the hand, so asking the card alone demanded a picker for a
    cost that cast never pays — and the picker it demanded took the place of the
    Aura's own enchant target, which made the card uncastable from either zone.
    """
    found = set()
    for name, card in _POOL.items():
        for cost in additional_costs(card):
            if not _payer_chooses(cost):
                continue
            found.add((name, cost.from_zone or "hand"))
    return sorted(found)


def _payer_chooses(cost) -> bool:
    """Whether *cost* is one the announcing player picks the payment for.

    This is the question both enumerations below are asking, and it is not
    "does the cost eat a card or a permanent" — it is CR 601.2b/602.2b's
    *choice*. "Discard a card **at random**" (Coral Helm, Stormbind, Amok,
    Draconian Cylix, Canyon Drake, Mage il-Vec, Ogre Shaman; Sonic Burst and
    Flowstone Flood on the cast side) eats a card and offers no choice at all:
    the payer names nothing and the RNG picks.

    Reading it as a choosable cost is how seven shipped cards came to raise a
    hand-card picker whose answer both payment paths then **deliberately
    ignore** — the client asked which card to bin, the player chose, and a
    different card was binned. That is this file's own failure shape read
    backwards: the missing picker was a choice nobody could make, and this is a
    choice nobody has. Neither is caught by the payment working.

    "Tap an untapped creature you control" (Opposition, Earthcraft, Unerring
    Sling, Keldon Battlewagon) is the third: the charger has taken the payer's
    answer on ``cost_permanent_ids`` since the cost existed, and nothing derived
    a picker, so for sixteen shipped cards a human seat tapped whatever the
    default chose. Unerring Sling's damage *is* the tapped creature's power.
    """
    if cost.sacrifice_filter is not None:
        return True
    if getattr(cost, "tap_filter", None) is not None and getattr(cost, "tap_count", 0):
        return True
    return bool(cost.discard_cards) and not getattr(
        cost, "discard_at_random", False
    )


def _activation_cost_abilities() -> list[tuple[str, int]]:
    found = []
    for name, card in sorted(_POOL.items()):
        program = compile_card_oracle(card)
        for index, ability in enumerate(program.activated_abilities):
            if not (ability.supported and ability.instruction is not None):
                continue
            if _payer_chooses(ability.cost):
                found.append((name, index))
    return found


def test_a_random_discard_cost_raises_no_picker():
    """The other half of :func:`_payer_chooses`, asserted rather than assumed.

    An enumeration that merely *skips* these costs would also pass if the picker
    came back — and a picker for a payment nobody chooses is a prompt whose
    answer is thrown away, which is what these seven cards did. So the refusal
    is checked directly, on both sides, over every card in the pool that prints
    the clause.
    """
    from engine.targeting import _cost_picker_spec

    random_discards = [
        (name, ability.cost)
        for name, card in sorted(_POOL.items())
        for ability in compile_card_oracle(card).activated_abilities
        if getattr(ability.cost, "discard_at_random", False)
    ] + [
        (name, cost)
        for name, card in sorted(_POOL.items())
        for cost in additional_costs(card)
        if getattr(cost, "discard_at_random", False)
    ]

    assert random_discards, "no card in the pool prints a random discard cost"
    for name, cost in random_discards:
        assert _cost_picker_spec(cost) is None, (
            f"{name}'s random discard derives a picker; its payment path "
            "ignores whatever the player names, so the prompt would lie"
        )


def test_the_pool_has_costs_of_both_kinds_to_check():
    """The guard is vacuous if the enumerations come back empty, and both of
    them read the pool rather than a list — so an ingest that renames a phrase
    would quietly empty them."""
    assert _cast_cost_cards(), "no card in the pool charges a printed cast cost"
    assert _activation_cost_abilities(), "no ability in the pool charges one"


@pytest.mark.parametrize("card_name,zone", _cast_cost_cards())
def test_every_printed_cast_cost_derives_a_picker(card_name, zone):
    """CR 601.2b: the caster announces how they will pay, so there has to be
    somewhere to announce it.

    An *optional* price (Constant Mists' "Buyback—Sacrifice a land") is
    announced before the picker is asked for, so the question here is asked of
    the caster who **takes** it. A declined offer charges nothing and rightly
    derives nothing — a picker raised for it would ask a caster who is not
    buying the card back to name a land they will not lose.
    """
    card = _POOL[card_name]
    announced = {
        cost.optional_key: 1
        for cost in additional_costs(card)
        if cost.optional_key is not None
    }
    spec = derive_cast_spec(
        card, compile_card_oracle(card), from_zone=zone,
        optional_cost_payments=announced or None,
    )

    assert spec is not None, (
        f"{card_name} charges a printed additional cost when cast from the "
        f"{zone} and derives no picker — a human seat pays it with whatever the "
        "deterministic default picks"
    )
    assert _has_cost_picker(spec), (
        f"{card_name}'s spec {spec!r} for a cast from the {zone} names no cost "
        "field, so the client would send the answer as a target"
    )


def test_a_zone_scoped_cost_is_not_charged_to_a_cast_from_elsewhere():
    """The other half of the same rule, and the bug this pair was widened for.

    Demonic Embrace prints one card with two prices — {1}{B}{B} from the hand,
    and {1}{B}{B} plus 3 life plus a card from the graveyard. A picker derived
    from the card alone asked a hand cast to name a discard it would never be
    charged for, and, being a cost picker, was returned *instead of* the Aura's
    enchant target: the browser never asked what to enchant and the engine
    refused the cast for want of a target it had itself declined to describe.
    """
    card = _POOL["Demonic Embrace"]
    program = compile_card_oracle(card)

    from_hand = derive_cast_spec(card, program, from_zone="hand")
    assert from_hand == {"kind": "creature"}

    from_graveyard = derive_cast_spec(card, program, from_zone="graveyard")
    assert from_graveyard["kind"] == "creature"
    assert from_graveyard["cost_spec"]["discard_cost"] is True


@pytest.mark.parametrize(
    "card_name,ability_index",
    [pair for pair in _activation_cost_abilities() if pair not in _PICKERLESS_ACTIVATION_COSTS],
)
def test_every_activation_cost_derives_a_picker(card_name, ability_index):
    """CR 602.2b says the same of an ability, and the answer is per *ability*:
    a permanent may carry several that pay differently."""
    program = compile_card_oracle(_POOL[card_name])
    ability = program.activated_abilities[ability_index]
    spec = derive_activation_spec(ability)

    assert spec is not None, (
        f"{card_name}'s ability {ability_index} charges a choosable cost and "
        "derives no picker"
    )
    assert _has_cost_picker(spec), (
        f"{card_name}'s ability {ability_index} derives {spec!r}, which names no "
        "cost field — the picker it opens would collect a target instead"
    )


@pytest.mark.parametrize("card_name,ability_index", sorted(_PICKERLESS_ACTIVATION_COSTS))
def test_the_recorded_pickerless_costs_are_still_pickerless(card_name, ability_index):
    """The other half of the ratchet. Pinning a gap is only honest while it *is*
    one: this fails the moment a picker is derived, which is what forces the
    entry out of the list rather than leaving it to be noticed."""
    program = compile_card_oracle(_POOL[card_name])
    ability = program.activated_abilities[ability_index]

    assert not _has_cost_picker(derive_activation_spec(ability)), (
        f"{card_name}'s ability {ability_index} now derives a cost picker — drop "
        "it from _PICKERLESS_ACTIVATION_COSTS"
    )


def test_the_pinned_gaps_all_still_charge_a_cost():
    """And a card that stopped charging the cost entirely (a parse change, a
    re-ingest) must not sit in the list looking like an open gap."""
    live = set(_activation_cost_abilities())
    stale = sorted(_PICKERLESS_ACTIVATION_COSTS - live)
    assert not stale, (
        f"pinned entries that no longer charge a choosable cost: {stale} — drop "
        "them from _PICKERLESS_ACTIVATION_COSTS"
    )
