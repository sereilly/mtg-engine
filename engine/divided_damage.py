"""How much of a divided effect each of its targets gets (CR 601.2d).

Two printed sentences, two divisions:

* "Fireball deals X damage **divided evenly, rounded down**, among any number of
  targets." Nobody chooses; the game divides.
* "Pyrotechnics deals 4 damage **divided as you choose** among any number of
  targets." CR 601.2d: *"the player announces the division"*, as part of
  announcing the spell — before targets are checked and before costs are paid,
  and locked in from then on (CR 608.2: the division is not re-chosen at
  resolution).

The engine did the first one for both. ``DamageRiders.divided_evenly`` was set
by the parser, copied by the rider merger, asserted by one grammar test — and
read by no lowering, no handler and no payload, so Pyrotechnics, Meteor Shower,
Fiery Justice and Fire Covenant were all played as ``damage // len(targets)``.
Four cards strictly weaker than printed, with nothing failing.

**The amount rides the target.** A divided spell's chosen targets travel as one
positional list on ``StackItem.choices["divided_targets"]``, so the announced
share belongs in the same entry rather than in a second list beside it: two
parallel lists are two things to keep in step, and the one that goes stale is
the one nothing dispatches on. An entry is therefore ``(seat, index)`` where no
division was announced and ``(seat, index, amount)`` where one was — read
through :func:`divided_entry`, never by destructuring, because the shorter form
is what every non-interactive caller (the AI, a test, an evenly-divided spell)
still sends and what CR 601.2d does not ask them for.
"""

from __future__ import annotations

#: The ``StackItem.choices`` key the whole family travels under. Named here
#: because the wire writes it, the casting path validates it, two handlers read
#: it and the serializer renders it — five spellings of a string is how they
#: come apart.
DIVIDED_TARGETS = "divided_targets"

#: What a ``targets`` description's ``division`` says about who divides. The
#: default is "evenly" and that is deliberate: a description written before this
#: existed carries no key, and the even split is what it meant.
EVENLY = "evenly"
CHOSEN = "chosen"


def divided_entry(entry) -> tuple[int, int | None, int | None]:
    """One ``divided_targets`` entry as ``(seat, index, announced amount)``.

    The one reader of the two shapes, so no call site has to know there are two.
    ``index`` is None for a player's face; ``amount`` is None when the caster
    announced no division, which is every evenly-divided spell and every seat
    that cannot be asked.
    """
    seat, index = entry[0], entry[1]
    amount = entry[2] if len(entry) > 2 else None
    return seat, index, amount


def announced_division(entries) -> list[int] | None:
    """The amounts *entries* announce, or None if they announce none.

    All or nothing: a partial announcement is not a division (CR 601.2d asks
    for the whole one), and honouring half of it would hand some targets a
    chosen share and the rest an even one.
    """
    amounts = [divided_entry(entry)[2] for entry in entries]
    if any(amount is None for amount in amounts):
        return None
    return [int(amount) for amount in amounts]


def division_refusal(
    total: int, entries, *, division: str, max_targets: int | None = None,
) -> str | None:
    """Why *entries*' announced division is illegal, or None (CR 601.2d).

    Asked at announcement, beside the target check and before any cost is paid,
    for the reason ``legality.cast_target_refusal`` is: an illegal announcement
    returns the game to the moment before the spell was proposed (CR 601.2e),
    and a division checked at resolution would already have spent the mana.

    An *absent* division is never a refusal. Every evenly-divided spell has
    none by definition, and a chosen-division spell cast by a seat with no way
    to be asked (the AI, a test, a scripted duel) falls back to the even split
    — the same shape a ``ChoiceSpec`` gives a non-interactive seat, and the
    behaviour every such caller had before this existed.

    *max_targets* is the printed ceiling on a variable target count — "among
    **one or two** target creatures" (Contagion), "among **one, two, or
    three**" (Bounty of the Hunt) — and is checked **before** the division,
    because it is CR 601.2c rather than CR 601.2d: the number of targets is
    announced first and a division of a lawful total over three creatures is
    still an illegal announcement when the card allows two. A seat that
    announced no shares is checked too, which is why this is not folded in with
    the amounts below: an even split over too many targets is the same illegal
    proposal, and the fallback that excuses an absent division must not excuse
    an over-long list.
    """
    if not entries:
        return None
    if max_targets is not None and len(entries) > max_targets:
        return (
            f"this spell has at most {max_targets} targets "
            f"({len(entries)} named, CR 601.2c)"
        )
    amounts = announced_division(entries)
    if amounts is None:
        return None
    if division != CHOSEN:
        return "this spell's damage is divided evenly, not as you choose"
    if any(amount < 1 for amount in amounts):
        return "each target must be assigned at least 1 (CR 601.2d)"
    if sum(amounts) != total:
        return f"the division must total {total} (CR 601.2d)"
    return None


def divide(total: int, entries, *, division: str) -> list[tuple[int, int | None, int]]:
    """*entries* with each one's share of *total*.

    The announced division when there is one, and otherwise the even split the
    printed word asks for — "divided evenly, **rounded down**", which is what
    ``//`` is and why a remainder simply disappears (Fireball for 5 among two
    targets deals 2 and 2).
    """
    normalized = [divided_entry(entry) for entry in entries]
    amounts = announced_division(entries)
    if amounts is None or division != CHOSEN:
        share = total // len(normalized) if normalized else 0
        amounts = [share] * len(normalized)
    return [
        (seat, index, amount)
        for (seat, index, _announced), amount in zip(normalized, amounts)
    ]


def divided_description(instructions) -> tuple[dict, dict] | None:
    """``(payload, targets description)`` of a program's divided step, or None.

    Walks a ``sequence`` (Fiery Justice divides its damage in step 0 and gives
    life in step 1), because the division belongs to the *card* and the caster
    announces it once for the spell.

    Here rather than in the casting path so the announcement gate and the
    handler read the same description — a gate that found the division a
    different way is a gate that can pass an announcement the handler then
    divides differently.
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            found = divided_description(instruction.payload.get("steps") or ())
            if found is not None:
                return found
            continue
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") == "divided":
            return instruction.payload, targets
    return None


__all__ = [
    "CHOSEN", "DIVIDED_TARGETS", "EVENLY", "announced_division", "divide",
    "divided_description", "divided_entry", "division_refusal",
]
