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

from engine.faces import compilation_units
from engine.card_loader import manifest_set_paths, load_cards
from engine.cast_costs import additional_costs
from engine.oracle import compile_card_oracle
from engine.targeting import derive_activation_spec, derive_cast_spec

# The whole pool, measured sets included: a picker missing on a card nobody can
# deck yet is missing all the same, and this is exactly where it was found.
_POOL = {}
for _path in manifest_set_paths(include_measured=True):
    # `compilation_units`: a split card is its halves, the cards whose text
    # prints a cost and whose programs hold an ability.
    for _card in compilation_units(load_cards(_path)):
        _POOL.setdefault(_card.name, _card)

# The flag each choosable cost sets on the spec it derives. The *names* matter:
# they are what tells the client which field the answer rides, and a cost
# reported under the wrong one would be collected and then paid with something
# else.
_COST_FLAGS = (
    "sacrifice_cost", "discard_cost", "tap_cost", "return_cost", "exile_cost",
    # PCY W3G5: the four costs paid with a permanent other than a sacrifice,
    # tap or return — "Untap a tapped land an opponent controls" (Benthic
    # Explorers), "Put a -1/-1 counter on a creature you control" (Wandering
    # Mage), "Remove a +1/+1 counter from a creature you control" (Spike
    # Rogue) — and the hand card "put on top of your library" (Hidden Retreat,
    # Penance).
    "untap_cost", "put_counter_cost", "remove_counter_cost", "library_top_cost",
)

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

# The cast side's twin, keyed by card name. PCY W3G5 widened the question from
# "does the spell derive *a* picker?" to "is *every* choice its costs hand the
# caster described?", and the wider question found two shipped spells whose
# cost no picker has ever described. Pinned rather than fixed, each with what
# it would take:
_PICKERLESS_CAST_COSTS: dict[str, str] = {
    # "As an additional cost to cast this spell, exile X creature cards from
    # your graveyard." The charger takes the top X of the pile and says so
    # (casting.py, "this engine has no graveyard picker on the cast path yet"):
    # there is no wire field for a set of graveyard positions on a cast, and the
    # client's X box and the picker would have to be one announcement.
    "Haunting Misery": "no cast-path graveyard set picker or wire field",
    # "As an additional cost to cast this spell, return X Swamps you control to
    # their owner's hand." The charger already honours ``cost_permanent_ids``
    # (casting.py's return branch); what is missing is the whole announcement:
    # ``_cost_picker_specs`` reads the activation spelling
    # (``return_to_hand_filter``) and not the cast one (``return_filter`` /
    # ``return_count_x``), and the cast client asks X inside the divided-damage
    # prompt, after any cost stage — so a set picker of X Swamps has nowhere to
    # learn X from. Emitting the spec alone would route it to the one-click
    # sacrifice prompt, which says "sacrifice" and answers on the wrong field.
    "Infernal Harvest": "cast-side return spelling unread; X asked after the cost stage",
}


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
    return bool(_chosen_cost_flags(cost))


def _chosen_cost_flags(cost) -> list[str]:
    """One picker flag per choice *cost* hands its payer, in no order.

    A *list*, because "does this cost choose anything?" was the wrong question
    and let five shipped cards through. Viscerid Drone's "Sacrifice a creature
    **and a Swamp**" and Urborg Panther's "Sacrifice a creature named Feral
    Shadow, a creature named Breathstealer, …" are two choices; the spec
    described the first, the guard asked for *a* picker and got one, and the
    Swamp was the engine's default for every human who ever paid it. The same
    question let the costs no flag existed for through entirely — Benthic
    Explorers' untap, Wandering Mage's -1/-1 counter, Spike Rogue's +1/+1
    counter removal, Hidden Retreat's and Penance's card put back on the
    library — because the enumeration below did not know their fields.

    Read with ``getattr`` because it is asked of both cost records — an
    activation's ``ActivatedAbilityCost`` and a cast's ``AdditionalCost`` —
    and they spell the same cost differently ("return_to_hand_filter" on one,
    "return_filter" on the other). Asking one spelling only is how Infernal
    Harvest's "return X Swamps" went unasked.
    """
    flags: list[str] = []
    if cost.sacrifice_filter is not None:
        flags.append("sacrifice_cost")
    # "Sacrifice a creature **and a Swamp**" (Viscerid Drone): the second noun
    # phrase is a second permanent and a second choice.
    if getattr(cost, "sacrifice_also_filter", None) is not None:
        flags.append("sacrifice_cost")
    if getattr(cost, "tap_filter", None) is not None and getattr(cost, "tap_count", 0):
        flags.append("tap_cost")
    # …and its one-zone-over twin, "Return a Forest you control to its owner's
    # hand" (Quirion Ranger, Flooded Shoreline) — and the cast side's spelling
    # of it, "return X Swamps you control" (Infernal Harvest).
    if getattr(cost, "return_to_hand_filter", None) is not None and getattr(
        cost, "return_to_hand_count", 0
    ):
        flags.append("return_cost")
    if getattr(cost, "return_filter", None) is not None:
        flags.append("return_cost")
    # "Exile a creature you control" (City of Shadows), "Exile a creature card
    # from your graveyard" (Necropolis), "exile X creature cards from your
    # graveyard" on the cast side (Haunting Misery).
    if getattr(cost, "exile_filter", None) is not None:
        flags.append("exile_cost")
    if getattr(cost, "exile_graveyard_filter", None) is not None:
        flags.append("exile_cost")
    if getattr(cost, "untap_filter", None) is not None:
        flags.append("untap_cost")
    if getattr(cost, "put_counter_filter", None) is not None:
        flags.append("put_counter_cost")
    if getattr(cost, "remove_counter_filter", None) is not None:
        flags.append("remove_counter_cost")
    if getattr(cost, "hand_to_library_top", 0):
        flags.append("library_top_cost")
    if (
        cost.discard_cards or getattr(cost, "discard_count_x", False)
    ) and not getattr(cost, "discard_at_random", False):
        flags.append("discard_cost")
    return flags


def _cost_head(spec: dict | None) -> dict | None:
    """The first cost picker *spec* carries, wherever it rides."""
    if spec is None:
        return None
    nested = spec.get("cost_spec")
    if isinstance(nested, dict):
        return nested
    return spec if any(spec.get(flag) for flag in _COST_FLAGS) else None


def _described_cost_flags(spec: dict | None) -> list[str]:
    """Every cost flag *spec* describes, the first picker and the ones after it
    (``more_costs``) — the list the client walks, one prompt per entry."""
    head = _cost_head(spec)
    if head is None:
        return []
    chain = [head, *(head.get("more_costs") or ())]
    return sorted(
        flag for entry in chain for flag in _COST_FLAGS if entry.get(flag)
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


@pytest.mark.parametrize(
    "card_name,zone",
    [pair for pair in _cast_cost_cards() if pair[0] not in _PICKERLESS_CAST_COSTS],
)
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


# ---------------------------------------------------------------------------
# PCY W3G5: every choice a cost hands its payer, not merely one of them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "card_name,ability_index",
    [pair for pair in _activation_cost_abilities() if pair not in _PICKERLESS_ACTIVATION_COSTS],
)
def test_every_choice_an_activation_cost_makes_is_described(card_name, ability_index):
    """CR 602.2b through CR 601.2h: each permanent or card a cost pays with is
    the payer's choice, so each needs a picker — one per choice, in the list
    the client walks (the first picker and its ``more_costs``).

    Validated backwards: on the tree before this round it names exactly six
    abilities on five cards — Benthic Explorers, Spike Rogue's second ability,
    Urborg Panther's second, Viscerid Drone's two and Wandering Mage's third —
    plus Hidden Retreat and Penance, whose "put a card from your hand on top of
    your library" the old enumeration did not know to ask about.
    """
    program = compile_card_oracle(_POOL[card_name])
    ability = program.activated_abilities[ability_index]
    expected = sorted(_chosen_cost_flags(ability.cost))
    described = _described_cost_flags(derive_activation_spec(ability))

    assert described == expected, (
        f"{card_name}'s ability {ability_index} hands its payer {expected} and "
        f"its picker describes {described} — every choice left off is paid "
        "with the engine's default for a human seat that was never asked"
    )


@pytest.mark.parametrize(
    "card_name,zone",
    [pair for pair in _cast_cost_cards() if pair[0] not in _PICKERLESS_CAST_COSTS],
)
def test_every_choice_a_cast_cost_makes_is_described(card_name, zone):
    """The cast side of the same question (CR 601.2b, 601.2h). A spell's
    picker is its first choosable additional cost; no spell in the pool prints
    two, and :func:`test_no_cast_picker_carries_a_chain` holds that — the cast
    client does not walk ``more_costs``."""
    card = _POOL[card_name]
    announced = {
        cost.optional_key: 1
        for cost in additional_costs(card)
        if cost.optional_key is not None
    }
    expected = sorted(
        flag
        for cost in additional_costs(card)
        if (cost.from_zone or "hand") == zone
        for flag in _chosen_cost_flags(cost)
    )
    spec = derive_cast_spec(
        card, compile_card_oracle(card), from_zone=zone,
        optional_cost_payments=announced or None,
    )
    described = _described_cost_flags(spec)

    assert described == expected, (
        f"{card_name} cast from the {zone} hands its caster {expected} and its "
        f"picker describes {described}"
    )


def test_no_cast_picker_carries_a_chain():
    """The cast client asks one cost picker and sends; the activation client
    walks ``more_costs``. A spell whose costs needed a chain would have the
    second choice derived here and dropped in the browser, so the first such
    spell fails this until the cast path learns the walk."""
    chained = []
    for name, card in sorted(_POOL.items()):
        for zone in {cost.from_zone or "hand" for cost in additional_costs(card)}:
            announced = {
                cost.optional_key: 1
                for cost in additional_costs(card)
                if cost.optional_key is not None
            }
            head = _cost_head(derive_cast_spec(
                card, compile_card_oracle(card), from_zone=zone,
                optional_cost_payments=announced or None,
            ))
            if head is not None and head.get("more_costs"):
                chained.append((name, zone))
    assert not chained, chained


def test_a_chained_cost_is_a_set_of_permanents():
    """What the activation client's chain can ask: a set of permanents, one
    picker after another, every answer on ``cost_permanent_ids``. A hand card
    or a graveyard card in the chain would be collected by nobody — so the
    first ability that needs one fails here rather than in a browser."""
    chained = []
    for name, card in sorted(_POOL.items()):
        for index, ability in enumerate(compile_card_oracle(card).activated_abilities):
            head = _cost_head(derive_activation_spec(ability))
            for entry in (head or {}).get("more_costs") or ():
                chained.append((name, index, entry.get("kind")))
    assert chained, "no ability in the pool carries a cost chain to check"
    unaskable = [
        entry for entry in chained
        if entry[2] in (None, "hand_card", "graveyard_creature", "none")
    ]
    assert not unaskable, unaskable


@pytest.mark.parametrize("card_name", sorted(_PICKERLESS_CAST_COSTS))
def test_the_recorded_pickerless_cast_costs_are_still_open(card_name):
    """The ratchet's other half for the cast side: pinned only while the gap is
    one, and only while the card still charges the cost."""
    card = _POOL[card_name]
    zones = {cost.from_zone or "hand" for cost in additional_costs(card) if _payer_chooses(cost)}
    assert zones, f"{card_name} no longer charges a choosable cast cost — unpin it"
    for zone in zones:
        expected = sorted(
            flag
            for cost in additional_costs(card)
            if (cost.from_zone or "hand") == zone
            for flag in _chosen_cost_flags(cost)
        )
        described = _described_cost_flags(
            derive_cast_spec(card, compile_card_oracle(card), from_zone=zone)
        )
        assert described != expected, (
            f"{card_name} now describes every cost choice — drop it from "
            "_PICKERLESS_CAST_COSTS"
        )


def test_an_exile_cost_is_picked_from_the_zone_it_names():
    """A picker over the wrong zone is a picker whose every answer is wrong.
    Cadaverous Bloom's "Exile a card **from your hand**" fell through to the
    battlefield branch and described a picker over the payer's permanents —
    the list offered was the board, and an answer would have been read as a
    hand position. Validated backwards: on the tree before PCY W3G5 this names
    Cadaverous Bloom and nothing else."""
    wrong = []
    for name, card in sorted(_POOL.items()):
        for index, ability in enumerate(compile_card_oracle(card).activated_abilities):
            cost = ability.cost
            if cost.exile_filter is None:
                continue
            head = _cost_head(derive_activation_spec(ability))
            wanted = {"hand": "hand_card", "graveyard": "graveyard_creature"}.get(
                cost.exile_zone
            )
            kind = (head or {}).get("kind")
            if wanted is not None and kind != wanted:
                wrong.append((name, index, cost.exile_zone, kind))
            if wanted is None and kind in ("hand_card", "graveyard_creature"):
                wrong.append((name, index, cost.exile_zone, kind))
    assert not wrong, wrong
