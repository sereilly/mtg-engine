"""How much of a divided effect each of its targets gets (CR 601.2d).

Four printed sentences, four divisions — and only the first two are divisions
in the ordinary sense. What all four share is the thing this module is really
about: a spell whose targets are a **cross-seat list**, chosen in one
announcement, with a number attached to each. ``divided_targets`` is the
engine's only channel for such a list, so a sentence that names several targets
of mixed kinds arrives here whether or not it divides anything.

* "Fireball deals X damage **divided evenly, rounded down**, among any number of
  targets." Nobody chooses; the game divides.
* "Pyrotechnics deals 4 damage **divided as you choose** among any number of
  targets." CR 601.2d: *"the player announces the division"*, as part of
  announcing the spell — before targets are checked and before costs are paid,
  and locked in from then on (CR 608.2: the division is not re-chosen at
  resolution).
* "Cone of Flame deals 1 damage to any target, 2 damage to another target, and
  3 damage to **a third target**." Three targets and three printed shares
  (:data:`FIXED`).
* "Firestorm deals X damage to **each of X targets**." X targets and no
  division at all — each one takes the whole amount (:data:`EACH`).

The last two are :data:`CARD_DIVIDED`: the caster announces the targets and the
card announces the shares, so nothing is asked and the numbers are stamped onto
the announcement.

The engine did the first one for both of the first two. ``DamageRiders.divided_evenly`` was set
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
#: "Cone of Flame deals 1 damage to any target, 2 damage to another target, and
#: 3 damage to a third target." Three targets and three **printed** shares,
#: paired by the order the caster announces the targets in — CR 601.2c settles
#: every target in one announcement, and the printed order is the only thing
#: that tells the 1 from the 3.
FIXED = "fixed"
#: "Firestorm deals X damage to **each of X targets**." Not a division at all:
#: every target takes the whole amount, and X of them must be named. It lives
#: in this family for the one thing it does share with the others — a
#: cross-seat list of chosen targets, which is what ``divided_targets`` is and
#: the engine's only channel for one.
EACH = "each"

#: The divisions the **card** dictates rather than the caster. CR 601.2d asks
#: the caster for a division only where the sentence says "as you choose"; both
#: members here print their own, so the shares are stamped onto the
#: announcement (:func:`card_shares`) instead of being asked for.
#:
#: One name because three readers ask the question — the cast gate stamps, the
#: handler honours what was stamped, and the picker must not raise a division
#: prompt — and three spellings of a set membership is how they come apart.
CARD_DIVIDED = frozenset({FIXED, EACH})


def divided_entry(entry) -> tuple[int, int | None, int | None]:
    """One ``divided_targets`` entry as ``(seat, index, announced amount)``.

    The one reader of the three shapes, so no call site has to know there are
    three. ``index`` is None for a player's face; ``amount`` is None when the
    caster announced no division, which is every evenly-divided spell and every
    seat that cannot be asked.

    A fourth element, when the entry has one, is the chosen permanent's **id**
    and is read by :func:`divided_entry_id` rather than returned here — so every
    existing caller keeps the three values it unpacks, and only the callers that
    resolve a permanent have to know the id exists.
    """
    seat, index = entry[0], entry[1]
    amount = entry[2] if len(entry) > 2 else None
    return seat, index, amount


def divided_entry_id(entry) -> int | None:
    """The ``permanent_id`` *entry* was announced against, or None.

    **An index is not an address.** The battlefield renumbers as soon as
    anything leaves it, so an index held from the announcement (CR 601.2c) to
    the resolution can name a different permanent — which is not a fizzle but a
    *hit on the wrong creature*: Pyrotechnics announced 3 damage to the second
    of two creatures, the first one left in response, and the survivor slid into
    slot 0 and took the 1 that had been announced against the creature that was
    gone. Every divided spell in the pool had it, in silence, because the bounds
    check the handlers made was satisfied by the wrong permanent.

    So the cast path resolves each announced index to an id and stamps it here
    (CR 400.7: an id is one object for one stay on the battlefield), and the
    handlers resolve by id with the index as the fallback for an entry that
    predates the stamp — a test's hand-written list, most of them.

    None for a player's face, which has no permanent, and None for an entry
    written before the stamp existed.
    """
    return entry[3] if len(entry) > 3 else None


def stamped_entry(seat, index, amount, permanent_id) -> tuple:
    """The canonical ``divided_targets`` entry, with the announcement's id.

    One builder, because the tuple is positional and three files write one. The
    amount stays ``None`` where none was announced rather than becoming 0: those
    are different facts (:func:`announced_division` reads the first as "this
    caster announced no division" and would read the second as a division of
    nothing), and it is why this cannot simply be a 4-tuple literal at each
    call site.
    """
    return (seat, index, amount, permanent_id)


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


def announced_no_targets(entries, described) -> bool:
    """Whether *entries* is the announcement of **no targets at all** by a
    spell that may make one.

    "Shower of Coals deals 2 damage to each of **up to** three targets." CR
    115.6: "A spell or ability that requires targets may allow zero targets to
    be chosen." The cast path writes that announcement down as an empty list
    (``cast_target_validation._settled_cast_division``, beside :func:`division_refusal`'s arm that
    admits it), and this is the resolution's reader: an explicit ``[]`` on a
    description that is :data:`EACH` under a printed ceiling.

    Both halves are needed. ``None`` is "this channel was not used" — the
    older single-target announcement every scripted duel still makes — and an
    empty list on any other division is a caller's default, not a statement
    (Fireball named through ``target_player_index`` with ``divided_targets=[]``
    is one target, and has always resolved as one).
    """
    return (
        isinstance(entries, (list, tuple))
        and not entries
        and isinstance(described, dict)
        and described.get("division") == EACH
        and described.get("max_targets") is not None
    )


def card_shares(total: int, count: int, *, division: str, shares) -> list[int]:
    """What each of *count* targets takes when the **card** sets the shares.

    The one arithmetic for both members of :data:`CARD_DIVIDED`, because the
    two differ only in where the numbers come from: :data:`FIXED` reads them off
    the printed sentence in order, and :data:`EACH` hands every target the whole
    amount. Neither divides *total* — that is the whole of what makes them not a
    division — so ``total`` is read only by ``EACH``, where it is the printed
    amount each target is dealt.

    Short lists are padded with 0 rather than raising: an announcement of the
    wrong length is refused by :func:`division_refusal` before this runs, and a
    handler re-entering after a target has left (CR 608.2b) must still be able
    to size what it has.
    """
    printed = [int(share) for share in (shares or ())]
    if division == EACH:
        return [int(total)] * count
    return (printed + [0] * count)[:count]


def _repeats_a_target(entries) -> bool:
    """Whether *entries* name one object or player twice (CR 601.2c).

    By ``(seat, index)`` — the pair that *is* the target on this channel — with
    ``index`` None meaning that seat's face, so two entries for one player and
    two for one creature are both caught by one comparison.
    """
    named = [(seat, index) for seat, index, _share in map(divided_entry, entries)]
    return len(set(named)) != len(named)


def stamp_card_shares(entries, amounts) -> list[tuple]:
    """*entries* with *amounts* attached positionally.

    The announcement step for a :data:`CARD_DIVIDED` spell. The share has to
    ride the entry rather than be re-derived at resolution, for the reason the
    module docstring gives about parallel lists — and here for a second one that
    is specific to :data:`FIXED`: a target that has left is dropped from the
    list at resolution (CR 608.2b), so a share read by *position* after that
    would slide Cone of Flame's 3 onto the creature the card assigned 2.
    """
    return [
        stamped_entry(seat, index, int(amount), divided_entry_id(entry))
        for entry, (seat, index, _announced), amount in zip(
            entries, (divided_entry(entry) for entry in entries), amounts
        )
    ]


def division_refusal(
    total: int, entries, *, division: str, max_targets: int | None = None,
    named_targets: int = 0, exact_targets: int | None = None,
    carries_no_targets: bool = False,
) -> str | None:
    """Why *entries*' announced division is illegal, or None (CR 601.2d).

    Asked at announcement, beside the target check and before any cost is paid,
    for the reason ``legality_cast_gates.cast_target_refusal`` is: an illegal announcement
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

    An absent *target list* **is** a refusal, and that is the one thing an
    absent division is not. CR 601.2d divides "among **one or more** targets",
    so a divided spell proposed with no target at all is an illegal proposal and
    CR 601.2e returns the game to the moment before it — where it used to be
    cast, for its full cost, into a resolution with nothing to divide among.
    *named_targets* is how many targets the caller named through the engine's
    older single-target channel (``target_permanent_index``, or a player's face
    for a spell whose printed noun admits one). That channel still announces a
    lawful division — one target taking the whole amount — so it is counted
    rather than refused; naming nothing at all is what this rejects.
    """
    # "…to **each of X targets**" (Firestorm), "…to any target, 2 damage to
    # another target, and 3 damage to a third target" (Cone of Flame). The card
    # prints *how many* targets, so a list of any other length is an illegal
    # proposal under CR 601.2c and CR 601.2e returns the game to before it.
    #
    # Checked first and outside the "no entries is excused" rule below: that
    # rule exists because a caller may announce one target through the engine's
    # older single-target channel, which is a lawful announcement for a spell
    # whose target count is open. For a spell that prints its count, one target
    # is a lawful announcement only when the count is one — so the older channel
    # is *counted* here rather than excused.
    if exact_targets is not None:
        named = len(entries) or named_targets
        if named != exact_targets:
            return (
                f"this spell has exactly {exact_targets} target"
                f"{'' if exact_targets == 1 else 's'} "
                f"({named} named, CR 601.2c)"
            )
        if not entries:
            return None
    if not entries:
        if named_targets:
            return None
        if division == EACH and max_targets is not None and carries_no_targets:
            # "…to each of **up to** three targets" (Shower of Coals). A
            # ceiling on an :data:`EACH` list is the printed "up to", and CR
            # 115.6 lets such a spell choose zero: "A spell or ability that
            # requires targets may allow zero targets to be chosen." Nothing is
            # divided here (each target named takes the whole amount), so
            # CR 601.2d's "one or more targets" — the floor below — is not this
            # spell's rule. A :data:`CHOSEN` ceiling is "among one, two, or
            # three" and keeps the floor.
            #
            # **Only for a caller that says its resolution can carry the
            # announcement** (*carries_no_targets*). Admitting it is half the
            # rule: an object on the stack with no list is read by the damage
            # handler as "nothing was said" and resolved at a default target,
            # so a caller that does not write the empty list down
            # (:func:`announced_no_targets` is what reads it) must go on
            # refusing — loudly — rather than deal damage to a player nobody
            # named. The cast path writes it; the activation path does not
            # yet, and no ability in the pool prints the phrase.
            return None
        return "a divided spell must have at least one target (CR 601.2d)"
    if max_targets is not None and len(entries) > max_targets:
        return (
            f"this spell has at most {max_targets} targets "
            f"({len(entries)} named, CR 601.2c)"
        )
    if _repeats_a_target(entries):
        # The two members of this family reach the same answer by two different
        # halves of CR 601.2c, which is worth writing down because the rule's
        # default is *not* what forbids Cone of Flame's repeat.
        #
        # * :data:`EACH` is one instance of the printed word "target", made
        #   plural ("each of X **targets**"), and the rule's own sentence
        #   applies: "the same target can't be chosen multiple times for any one
        #   instance of the word 'target'".
        # * :data:`FIXED` prints the word three times, and the rule expressly
        #   *allows* one object to be chosen once per instance. What forbids it
        #   is the card: "**another** target", "a **third** target". Reading
        #   601.2c alone here would be reading it backwards.
        #
        # Asked of **every** division, which is what the rule says. It was asked
        # of these two alone for a while, on the reasoning that widening it
        # would change what every shipped divided spell accepts on a round that
        # was about two new ones — a scope argument, correct at the time and
        # never a claim that the others were exempt. The looseness it named out
        # loud ("any number of targets" is one instance of the word too, and
        # nothing here checks it) is closed by the same sentence that closes it
        # for the flat family in ``legality_abilities._repeated_target_refusal``: one
        # printed instance, however many slots it opens, may not be filled twice
        # by one object. Elven Rite and Contagion are :data:`CHOSEN` and were
        # the cards it was costing.
        return "each target must be a different one (CR 601.2c)"
    amounts = announced_division(entries)
    if amounts is None:
        return None
    if division in CARD_DIVIDED:
        # The shares are printed on the card, and `stamp_card_shares` writes
        # them onto the announcement after this gate. A caster who sent their
        # own is refused rather than overwritten: an overwrite would accept an
        # announcement the rules do not allow and then silently play a different
        # one, which is the direction this whole gate exists to refuse.
        return "this spell's shares are printed, not announced (CR 601.2d)"
    if division != CHOSEN:
        return "this spell's damage is divided evenly, not as you choose"
    if any(amount < 1 for amount in amounts):
        return "each target must be assigned at least 1 (CR 601.2d)"
    if sum(amounts) != total:
        return f"the division must total {total} (CR 601.2d)"
    return None


def spread_shares(total: int, count: int) -> list[int]:
    """*total* split *count* ways, remainder to the earliest.

    CR 601.2d wants every target to receive at least one, so the remainder is
    spread rather than dropped — the starting division the browser offers a
    person (``evenStartingDivision``), the AI's proposal for a divided spell
    (``ai_divisions._even_shares``) and a seat nobody asks for a divided trigger's
    announcement (``Game._default_trigger_division``) all start from this one.
    """
    if count <= 0:
        return []
    base, left = divmod(int(total), int(count))
    return [base + (1 if index < left else 0) for index in range(count)]


def forced_division(total: int, count: int) -> list[int] | None:
    """The one lawful CR 601.2d division of *total* over *count* targets, or
    None when the announcer has a choice to make.

    "Distribute three -1/-1 counters among one, two, or three target
    creatures" (Shambling Swarm): one target takes all three, and three
    targets take one apiece (each must be assigned at least one), so an answer
    naming either needs no division beside it — two targets is 2+1 or 1+2, and
    that is a choice nobody may make for the announcer.
    """
    if count == 1:
        return [int(total)]
    if count > 0 and count == total:
        return [1] * count
    return None


def divide(total: int, entries, *, division: str) -> list[tuple[int, int | None, int]]:
    """*entries* with each one's share of *total*.

    The announced division when there is one, and otherwise the even split the
    printed word asks for — "divided evenly, **rounded down**", which is what
    ``//`` is and why a remainder simply disappears (Fireball for 5 among two
    targets deals 2 and 2).

    A :data:`CARD_DIVIDED` spell reaches here with its shares already on the
    entries (``stamp_card_shares``, at the announcement), so it takes the same
    branch a caster's announcement does: the numbers are read off the entries
    either way, and only *who chose them* differs. Reading them positionally
    here instead would be wrong for exactly the reason they are stamped —
    a target that has left is dropped from the list first (CR 608.2b), and every
    later share would slide up one.
    """
    normalized = [divided_entry(entry) for entry in entries]
    amounts = announced_division(entries)
    if division == EACH:
        # Every target takes the whole of what the **resolving** instruction
        # deals, which is *total* — not what was stamped at the announcement.
        # The two are one number for Firestorm. They are not for "Shower of
        # Coals deals 2 damage to each of up to three targets. … deals 4
        # damage to each of those permanents and/or players instead if there
        # are seven or more cards in your graveyard": the amount is settled
        # as the spell resolves (CR 608.2h), and a stamp can only know what
        # the card would have dealt as it was cast.
        amounts = [total] * len(normalized)
    elif amounts is None or (division != CHOSEN and division not in CARD_DIVIDED):
        share = total // len(normalized) if normalized else 0
        amounts = [share] * len(normalized)
    return [
        (seat, index, amount)
        for (seat, index, _announced), amount in zip(normalized, amounts)
    ]


def divided_instruction(instructions):
    """The one instruction in *instructions* whose targets are divided, or None.

    Walks a ``sequence`` (Fiery Justice divides its damage in step 0 and gives
    life in step 1), because the division belongs to the *card* and the caster
    announces it once for the spell.

    Here rather than in the casting path so the announcement gate and the
    handler read the same description — a gate that found the division a
    different way is a gate that can pass an announcement the handler then
    divides differently. The AI reads it too, for the *kind*: which board a
    divided effect wants is a question about what the instruction does, and a
    second walk to find it would be a second answer to "which step divides".
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            found = divided_instruction(instruction.payload.get("steps") or ())
            if found is not None:
                return found
            continue
        if instruction.kind == "if_then":
            found = _divided_in_both_arms(instruction)
            if found is not None:
                return found
            continue
        targets = instruction.payload.get("targets")
        if isinstance(targets, dict) and targets.get("kind") == "divided":
            return instruction
    return None


def conditional_division(instructions):
    """``(condition, replacing arm's step, base arm's step)`` when the program's
    division is one **both arms of a resolution-time condition announce**, else
    None.

    The pair :func:`_divided_in_both_arms` reads, handed out whole for the one
    reader that must not take either arm on trust: the picker's
    ``division_total`` (``legality_cast_spec.cast_target_spec``), which says how much each
    target is dealt and can only say it of the arm the board selects *now*.
    :func:`divided_instruction` returns the replacing arm because the list is
    the same in both; the amount is not.
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            found = conditional_division(instruction.payload.get("steps") or ())
            if found is not None:
                return found
            continue
        if instruction.kind != "if_then" or _divided_in_both_arms(instruction) is None:
            continue
        payload = instruction.payload or {}
        return (
            payload.get("condition") or {},
            divided_instruction(tuple(payload.get("then") or ())),
            divided_instruction(tuple(payload.get("else") or ())),
        )
    return None


def _divided_in_both_arms(conditional):
    """The divided instruction of an ``if_then`` whose **two arms announce the
    same list**, or None.

    "Shower of Coals deals 2 damage to each of up to three targets. … deals 4
    damage to each of those permanents and/or players **instead** if there are
    seven or more cards in your graveyard." The condition is asked as the spell
    resolves, so as it is cast both arms are still in front of the caster — and
    they name one list of targets (CR 601.2c: chosen once, for whichever arm
    resolves). The replacing arm is the one returned, because it is the arm
    ``targeting.py``'s own walk reads first; what each target is *dealt* is
    the resolving arm's own amount (:func:`divide`), never this one's.

    Two refusals, each a way the answer would be about half the card:

    * **a ``was_kicked`` condition** is settled as the spell is cast
      (CR 601.2b precedes CR 601.2c), and ``targeting.instructions_as_announced``
      hands this module the one arm that cast will run. Read card-wide, a
      division printed only for the kicked cast (Magma Burst) or sized by it
      (Pollen Remedy) stays unfound, which is what every caller asking about
      the *card* has always been told;
    * **arms that describe different lists** — a division in one arm and a
      single target in the other, or two different ceilings — are two
      announcements, and nothing here can say which the caster is making.
    """
    payload = conditional.payload or {}
    condition = payload.get("condition")
    if isinstance(condition, dict) and condition.get("kind") == "was_kicked":
        return None
    then = divided_instruction(tuple(payload.get("then") or ()))
    otherwise = divided_instruction(tuple(payload.get("else") or ()))
    if then is None or otherwise is None:
        return None
    if then.payload.get("targets") != otherwise.payload.get("targets"):
        return None
    return then


def divided_description(instructions) -> tuple[dict, dict] | None:
    """``(payload, targets description)`` of a program's divided step, or None.

    :func:`divided_instruction`'s answer, unpacked for the two callers that want
    the payload and the description rather than the instruction itself.
    """
    instruction = divided_instruction(instructions)
    if instruction is None:
        return None
    return instruction.payload, instruction.payload["targets"]


__all__ = [
    "CARD_DIVIDED", "CHOSEN", "DIVIDED_TARGETS", "EACH", "EVENLY", "FIXED",
    "announced_division", "announced_no_targets", "card_shares",
    "conditional_division", "divide", "divided_description",
    "divided_entry", "divided_entry_id", "divided_instruction",
    "division_refusal", "stamp_card_shares", "stamped_entry",
]
