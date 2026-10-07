"""Single write API for power/toughness channels (scoped CR 613).

``Permanent.effective_power`` / ``effective_toughness`` (engine/models.py)
read a fixed set of channels in CR-613 sublayer order. All WRITES must go
through this module so the channel vocabulary stays in one place; if a future
set ever needs per-effect timestamps or dependency ordering, only these
helpers change.

Channel → sublayer mapping:

- 7a (characteristic-defining): ``cda_power`` / ``cda_toughness``, a
  **derived** channel — :func:`set_cda_pt` writes it and the refresh that
  counts the ability clears and rebuilds it on every recompute, so a creature
  that has lost the ability has no value here at all (CR 604.3, CR 613.4a).
  It shared 7b's slot, which made a Nightmare older than a Humility a 3/3:
  the count was written where "set to 1/1" is read, and whichever was written
  last won a contest CR 613.4 never holds — 7a is applied before 7b whatever
  the timestamps say.
- 7b (set to N): ``absolute_power`` / ``absolute_toughness`` metadata, and the
  ``_until_eot`` variants cleared in the cleanup step (see
  ``_EOT_METADATA_KEYS`` in engine/mixins/_constants.py). **Each slot carries
  the timestamp it was written at** (:data:`BASE_PT_TIMESTAMP_KEY`, CR 613.7b:
  an effect a resolution creates is stamped as it is created), put there by
  :func:`set_base_pt` itself — the stamp is inside the write, as it is for a
  colour (``color_changes.change_color``) and a type (``type_changes``). So
  the two slots, an Aura's size, a board-wide static's and a land animator's
  are ordered against each other by CR 613.7 rather than by which channel
  each happened to be read from: a Humble older than a Humility loses to it.
  Two writers of *one* slot still resolve last-write-wins, which is timestamp
  order for effects a resolution creates.
- 7c (modify by +X/+Y) splits by *lifetime*, which is what keeps it correct:

  - ``power_bonus`` / ``toughness_bonus`` are **persistent** — counters and
    one-shot modifications that stay until something removes them.
    Until-end-of-turn boosts are additionally tracked in
    ``temporary_*_bonus_until_eot`` metadata so the cleanup step can subtract
    exactly what it added.
  - ``static_buff_*`` (lord passes) and ``derived_buff_*`` (conditional
    "as long as …" bonuses, Aspect of Wolf) are **derived**: cleared and
    rebuilt from the current board on every continuous-effects recompute.
    Nothing records what it contributed, because nothing has to take it back.

  A continuous effect must never write to the persistent channel. Doing so
  requires it to subtract itself later, and any mismatch compounds — CR 611.3a
  means the recompute runs constantly. Aspect of Wolf shipped that bug.
  Each derived channel is cleared by the same function that rebuilds it.
- 7d (switch): ``pt_switched`` metadata flag (cleared at cleanup).
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from .continuous import next_timestamp

if TYPE_CHECKING:
    from .models import Permanent


#: The scheduled revert of a persistent base-P/T write ("until the end of your
#: next upkeep", Halfdane): ``{"seat": <whose upkeep>, "turn": <game.turn when
#: written>}``. The draw step — the moment the upkeep has just ended — clears
#: the base override of a permanent whose stamp names that seat and an
#: *earlier* turn; a stamp written this very upkeep survives to the next one,
#: which is how the re-applying trigger keeps its own effect alive. Named here
#: because this module owns the channel vocabulary: any later persistent write
#: supersedes the scheduled revert (last-write-wins is this engine's 7b
#: timestamp order), so :func:`set_base_pt` is what removes the stamp.
BASE_PT_REVERT_KEY = "base_pt_reverts_after_upkeep"

#: Its twin one step earlier: "…**until your next upkeep**" (Cycle of Life),
#: which ends as that upkeep *begins* rather than as it ends. Same shape —
#: ``{"seat": <whose upkeep>, "turn": <game.turn when written>}`` — and swept in
#: the upkeep step's own ``your_next_upkeep`` loop, beside the keyword, type and
#: permission grants that answer to the same printed words, so one duration has
#: one moment however it is spelled.
#:
#: Two keys rather than one with a "when" field, because the two are read by two
#: different steps and neither can see the other's: a single key would make each
#: sweep test a value it does not own, which is the shape a sweep silently stops
#: honouring. The stamp's turn number is what keeps an effect applied *during*
#: an upkeep from ending in that same upkeep.
BASE_PT_UPKEEP_START_REVERT_KEY = "base_pt_reverts_at_upkeep"

#: Both scheduled reverts, for the writers that supersede whichever is standing.
_BASE_PT_REVERT_KEYS = (BASE_PT_REVERT_KEY, BASE_PT_UPKEEP_START_REVERT_KEY)

#: When a 7b slot was written (CR 613.7b) — this key for the persistent slot,
#: and with ``_until_eot`` appended for the one the cleanup step clears.
#: ``layer_bridge.collect_pt_effects`` had read this key since the layer
#: system was written and nothing had ever written it, so both slots sat at
#: two constants (1 and 2) and every *derived* 7b effect at 0: a board-wide
#: static never beat a slot, and a slot never lost to anything.
BASE_PT_TIMESTAMP_KEY = "absolute_pt_timestamp"

#: Layer 7a's channel (:func:`set_cda_pt`).
CDA_POWER_KEY = "cda_power"
CDA_TOUGHNESS_KEY = "cda_toughness"


def set_base_pt(
    perm: Permanent,
    power: int | None,
    toughness: int | None,
    *,
    until_eot: bool = False,
    reverts_at_next_upkeep_of: int | None = None,
    turn: int | None = None,
    timestamp: int | None = None,
) -> None:
    """Layer 7b: set base power and/or toughness ("becomes 0/2", an
    animation's size). Pass None for a stat to leave it untouched — Singing
    Tree's "has base power 0 until end of turn" sets only power, letting
    toughness keep tracking whatever else applies. 7c modifications still
    apply on top of the new base.

    *timestamp* is where the write sorts in layer 7b (CR 613.7). Omitted, it
    is **now** — CR 613.7b, the stamp of an effect a resolving spell or
    ability creates, which is every caller but one. The one is the body an
    "as this enters" choice gives (Primal Clay): CR 613.2a makes that a
    copiable value, where every later layer starts, so it passes
    ``layer_bridge.COPIABLE_VALUE`` and loses to a Humility however old.
    A characteristic-defining ability is not written here at all
    (:func:`set_cda_pt`).

    *reverts_at_next_upkeep_of* is the seat whose next upkeep ends this write
    ("until your next upkeep"), with *turn* the turn it was made on — the pair
    :data:`BASE_PT_UPKEEP_START_REVERT_KEY` holds. It rides the **persistent**
    channel rather than a third suffix of its own, because a duration is not a
    layer: what makes this different from Sorceress Queen's write is when
    something clears it, and a channel with no sweep is exactly the bug
    ``TEMPORARY_PT_CHANNELS`` below records.
    """
    suffix = "_until_eot" if until_eot else ""
    if power is not None:
        perm.metadata[f"absolute_power{suffix}"] = int(power)
    if toughness is not None:
        perm.metadata[f"absolute_toughness{suffix}"] = int(toughness)
    if power is not None or toughness is not None:
        perm.metadata[f"{BASE_PT_TIMESTAMP_KEY}{suffix}"] = (
            next_timestamp() if timestamp is None else int(timestamp)
        )
    if not until_eot:
        # A newer persistent write supersedes a scheduled revert: reverting
        # would clear the metadata key the newer effect just wrote, taking the
        # newer effect with it. The caller that wants a revert re-stamps after
        # writing (engine/handlers/base_pt.py) — which is what the argument
        # below does, in the one place that knows the seat and the turn.
        for key in _BASE_PT_REVERT_KEYS:
            perm.metadata.pop(key, None)
        if reverts_at_next_upkeep_of is not None:
            perm.metadata[BASE_PT_UPKEEP_START_REVERT_KEY] = {
                "seat": int(reverts_at_next_upkeep_of),
                "turn": int(turn or 0),
            }


def clear_base_pt(perm: Permanent, *, until_eot: bool = False) -> None:
    """Remove a 7b base override, restoring the printed base."""
    if until_eot:
        perm.metadata.pop("absolute_power_until_eot", None)
        perm.metadata.pop("absolute_toughness_until_eot", None)
        perm.metadata.pop(f"{BASE_PT_TIMESTAMP_KEY}_until_eot", None)
    else:
        perm.metadata.pop("absolute_power", None)
        perm.metadata.pop("absolute_toughness", None)
        perm.metadata.pop(BASE_PT_TIMESTAMP_KEY, None)
        for key in _BASE_PT_REVERT_KEYS:
            perm.metadata.pop(key, None)


def set_cda_pt(
    perm: Permanent, power: int | None, toughness: int | None
) -> None:
    """Layer 7a: what a characteristic-defining ability makes this permanent's
    power and/or toughness (CR 604.3, CR 613.4a) — Nightmare's Swamps, Plague
    Rats' Rats. None leaves a stat to its printed value (Kinetic Augur is */4).

    A **derived** channel: the pass that counts the ability calls
    :func:`clear_cda_pt` on every permanent and writes again only where the
    ability is still there, so nothing has to notice a creature losing it. No
    timestamp, because the sublayer needs none — CR 613.4 applies 7a before
    7b, and a permanent has one such ability.
    """
    if power is not None:
        perm.metadata[CDA_POWER_KEY] = int(power)
    if toughness is not None:
        perm.metadata[CDA_TOUGHNESS_KEY] = int(toughness)


def clear_cda_pt(perm: Permanent) -> None:
    """Forget the 7a value, ahead of the pass that rebuilds it."""
    perm.metadata.pop(CDA_POWER_KEY, None)
    perm.metadata.pop(CDA_TOUGHNESS_KEY, None)


def toughness_has_been_set(perm: Permanent) -> bool:
    """Whether anything has given *perm* a toughness its printed "*" lacks —
    a counted characteristic-defining ability, or a persistent 7b write.

    The one question CR 704.5f's sweep asks of this module: a creature printed
    with a variable toughness is not at 0 until its ability has been counted
    once. Here so the sweep names no channel of its own.
    """
    return (
        CDA_TOUGHNESS_KEY in perm.metadata or "absolute_toughness" in perm.metadata
    )


#: Where a *temporary* layer-7c modification records itself, one metadata pair
#: per duration, and the whole of what makes a duration implemented: a channel
#: with no sweep behind it is a pump that never ends.
#:
#: There was one channel and a boolean to reach it, so "until end of combat"
#: (Glyph of Destruction) had nowhere to be recorded and lowered onto the
#: end-of-turn kind — a pump outliving the combat it was printed for, with
#: nothing in the payload to show the word had been read. A table is what lets
#: the sweeps name their own duration instead of owning the only one.
TEMPORARY_PT_CHANNELS: dict[str, tuple[str, str]] = {
    "end_of_turn": (
        "temporary_power_bonus_until_eot",
        "temporary_toughness_bonus_until_eot",
    ),
    "end_of_combat": (
        "temporary_power_bonus_until_eoc",
        "temporary_toughness_bonus_until_eoc",
    ),
}


def add_pt_modifier(
    perm: Permanent, power: int = 0, toughness: int = 0, *, until: str | None = None
) -> None:
    """Layer 7c: add a +X/+Y modification.

    *until* names the duration's channel in :data:`TEMPORARY_PT_CHANNELS`, and
    the sweep for that duration is what removes it; both metadata keys are
    written even for a 0 delta (the sweep relies on their presence). ``None`` is
    a modification with no duration at all — a continuous effect, removed by the
    thing that contributed it ceasing to.
    """
    perm.power_bonus += power
    perm.toughness_bonus += toughness
    if until is None:
        return
    if until not in TEMPORARY_PT_CHANNELS:
        raise ValueError(f"no P/T channel for the duration {until!r}")
    power_key, toughness_key = TEMPORARY_PT_CHANNELS[until]
    perm.metadata[power_key] = int(perm.metadata.get(power_key, 0)) + power
    perm.metadata[toughness_key] = int(perm.metadata.get(toughness_key, 0)) + toughness


def remove_temporary_pt(perm: Permanent, until: str) -> None:
    """End every layer-7c modification recorded on *until*'s channel.

    The read half of :func:`add_pt_modifier`, here rather than open-coded in
    each sweep so that adding a duration is adding a row above and a call here —
    the cleanup step's pop-and-subtract was the only copy, and a second sweep
    written by hand is a second chance to subtract the wrong pair.
    """
    power_key, toughness_key = TEMPORARY_PT_CHANNELS[until]
    power = int(perm.metadata.pop(power_key, 0))
    toughness = int(perm.metadata.pop(toughness_key, 0))
    if power:
        perm.power_bonus -= power
    if toughness:
        perm.toughness_bonus -= toughness


def switch_pt(perm: Permanent) -> None:
    """Layer 7d: switch power and toughness until end of turn (the flag is
    cleared at cleanup). Two switches cancel out."""
    perm.metadata["pt_switched"] = not perm.metadata.get("pt_switched", False)


_PT_COUNTER = re.compile(r"^([+-])(\d+)/([+-])(\d+)$")

# The three kinds with a metadata key the engine already reads, kept as they
# are spelled. CR 704.5q's cancellation sweep, the web card face and "a
# creature with a +1/+1 counter on it" were written against the first two;
# Clockwork Beast's cap ("can't cause the total number of +1/+0 counters … to
# be greater than seven") reads the third, and a second spelling would make the
# cap count a different pile from the one the placement fills.
#
# Every other CR 122.1a counter is a counter like any other and lives in the
# named-counter store under the name CR 122.1 makes its identity — a "-0/-2"
# counter and a "-1/-1" counter are not interchangeable, and two -0/-2 counters
# are.
_PT_COUNTER_KEYS = {
    "+1/+1": "plus_counters",
    "-1/-1": "minus_counters",
    "+1/+0": "plus_1_0_counters",
}


def pt_counter_deltas(kind: str) -> tuple[int, int] | None:
    """CR 122.1a: what one *kind* counter adds to power and toughness, or None
    if *kind* is not a P/T counter at all.

    Derived from the name rather than looked up in a list of the kinds the pool
    happens to print. The rule is written as "+X/+Y … similarly, -X/-Y", so the
    numbers are the counter's *name* and a table of them would be a list of the
    cards printed so far — which is exactly what it was: "-0/-2" (Spirit
    Shackle) and "-0/-1" (Takklemaggot, Lesser Werewolf) were rejected as
    unsupported counter kinds while "-1/-1" beside them was admitted.
    """
    match = _PT_COUNTER.match(kind)
    if match is None:
        return None
    power_sign, power, toughness_sign, toughness = match.groups()
    return (
        int(power) * (-1 if power_sign == "-" else 1),
        int(toughness) * (-1 if toughness_sign == "-" else 1),
    )


def pt_counter_key(kind: str) -> str:
    """The metadata key *kind*'s counters are recorded under.

    Everything outside the three established keys falls through to
    ``engine/named_counters.py``'s spelling rather than a second one of this
    module's own — that file's whole opening argument is that two stores for
    one concept is how a card ends up putting counters somewhere nothing reads.
    """
    from .named_counters import counters_key

    return _PT_COUNTER_KEYS.get(kind) or counters_key(kind)


def add_pt_counters(perm: Permanent, kind: str, count: int = 1) -> None:
    """Place *count* CR 122.1a counters of *kind*: the persistent P/T channel
    plus the counter record.

    The record is not cosmetic. The 704.5q sweep cancels +1/+1 against -1/-1,
    the web layer renders counters on the card face, and "target creature with
    a +1/+1 counter on it" (Tempered Veteran) is a question about *counters*,
    which a bare P/T bonus cannot answer — a Giant Growth also writes
    power_bonus, and reading the bonus as the counter would let it qualify.
    Unstable Mutation is the other half of that: its upkeep pass wrote the two
    bonuses and no record at all, under a comment saying "the counters are real
    -1/-1 counters … 704.5q applies" — which it could not, because nothing had
    put a counter anywhere for the sweep to find.

    Every handler that places a P/T counter goes through here, so the two
    channels cannot drift.
    """
    deltas = pt_counter_deltas(kind)
    if deltas is None:
        raise ValueError(f"{kind!r} is not a power/toughness counter")
    if count <= 0:
        return
    power, toughness = deltas
    add_pt_modifier(perm, power * count, toughness * count)
    key = pt_counter_key(kind)
    perm.metadata[key] = int(perm.metadata.get(key, 0)) + count


def add_plus1_counters(perm: Permanent, count: int = 1) -> None:
    """Place *count* +1/+1 counters — :func:`add_pt_counters` with the one kind
    most of the pool prints, kept as its own name because the seam above it
    (``Game.place_plus1_counters``) and its CR 614 replacements are about that
    kind specifically."""
    add_pt_counters(perm, "+1/+1", count)


def remove_plus1_counters(perm: Permanent, count: int = 1) -> int:
    """Remove up to *count* +1/+1 counters — both channels, floored at zero.

    Returns how many actually came off, because a shield sized by counters
    (Rock Hydra's automatic prevention) may only prevent that much: asking for
    five off a creature holding two removes two, and the caller deals the
    difference.
    """
    from .named_counters import remove_counters

    have = int(perm.metadata.get("plus_counters", 0))
    removed = min(max(count, 0), have)
    if removed <= 0:
        return 0
    # Through the one removal seam, which moves both channels. It used to write
    # them here as well, which was two implementations of one rule — and the
    # seam's was the incomplete one, so a caller that reached it with a +1/+1
    # counter (Triskelion's cost) took the counter off the record and left the
    # creature 4/4.
    remove_counters(perm, "+1/+1", removed)
    return removed
