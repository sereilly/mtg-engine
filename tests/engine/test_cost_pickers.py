"""Guard: a cost the payer chooses is a cost the payer is *asked* about.

CR 601.2b (casting) and CR 602.2b (activating) both say the announcing player
chooses how a cost is paid. This engine charges two such costs — sacrifice a
permanent, discard a card — and each needs a picker derived for it, because the
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
_COST_FLAGS = ("sacrifice_cost", "discard_cost")

# The gaps this guard found the day it was written, pinned rather than exempted:
# the test below asserts each one is *still* a gap, so the list can only shrink
# and closing one is what removes it. Every entry is an activation whose
# sacrifice cost the payer is never asked about — the same shape as the discard
# cost, and found the same way, but its fix is a round of its own because two of
# them need the client to run *two* prompts rather than one.
#
#   Atog                — no spec at all, so no prompt: the default eats the
#                         smallest, which among equal-power artifacts is decided
#                         by permanent id. On a board of Black Lotus and Mox Ruby
#                         it takes the Lotus.
#   Hobblefiend         — the same, with "another" excluding the source.
#   Witch's Cauldron    — derives {"kind": "any"} off a caster-recipient life
#                         gain, so the client opens a target picker for an
#                         ability that targets nothing, and the sacrifice is
#                         still taken by default. Asked the wrong question.
#   Dwarven Weaponsmith — the hard one, and the reason the fix is not a
#                         one-liner: its ability has a real target *and* a
#                         sacrifice cost (CR 601.2c and 601.2b), so one spec
#                         cannot carry both and the client needs a second prompt.
_PICKERLESS_ACTIVATION_COSTS = {
    ("Atog", 0),
    ("Dwarven Weaponsmith", 0),
    ("Hobblefiend", 0),
    ("Witch's Cauldron", 0),
}


def _has_cost_picker(spec: dict | None) -> bool:
    return spec is not None and any(spec.get(flag) for flag in _COST_FLAGS)


def _cast_cost_cards() -> list[str]:
    return sorted(
        name for name, card in _POOL.items()
        if any(c.sacrifice_type or c.discard_cards for c in additional_costs(card))
    )


def _activation_cost_abilities() -> list[tuple[str, int]]:
    found = []
    for name, card in sorted(_POOL.items()):
        program = compile_card_oracle(card)
        for index, ability in enumerate(program.activated_abilities):
            if not (ability.supported and ability.instruction is not None):
                continue
            cost = ability.cost
            if cost.sacrifice_type or cost.discard_cards:
                found.append((name, index))
    return found


def test_the_pool_has_costs_of_both_kinds_to_check():
    """The guard is vacuous if the enumerations come back empty, and both of
    them read the pool rather than a list — so an ingest that renames a phrase
    would quietly empty them."""
    assert _cast_cost_cards(), "no card in the pool charges a printed cast cost"
    assert _activation_cost_abilities(), "no ability in the pool charges one"


@pytest.mark.parametrize("card_name", _cast_cost_cards())
def test_every_printed_cast_cost_derives_a_picker(card_name):
    """CR 601.2b: the caster announces how they will pay, so there has to be
    somewhere to announce it."""
    card = _POOL[card_name]
    spec = derive_cast_spec(card, compile_card_oracle(card))

    assert spec is not None, (
        f"{card_name} charges a printed additional cost and derives no picker — "
        "a human seat pays it with whatever the deterministic default picks"
    )
    assert any(spec.get(flag) for flag in _COST_FLAGS), (
        f"{card_name}'s spec {spec!r} names no cost field, so the client would "
        "send the answer as a target"
    )


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
