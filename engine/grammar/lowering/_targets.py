"""What a sentence **points at**, as the payload a picker and a handler read.

The lowering mirror of ``ast/_targets.py``, and split out of ``_common`` on that
module's own stated line when it crossed the thousand-line guard. ``_common`` is
the shape a payload takes and the small values every family needs; this is the
one payload key whose shape is decided by CR 601.2's *announcement* rather than
by the effect underneath it — ``targets``.

The cut is the same one the AST package made a set earlier, under the same name
and for the same reason: what a noun phrase **describes** (``_references`` there,
``_filters`` here) against what a sentence **points at** (``_targets`` on both
sides). The two grow with different rules, which is what makes the boundary worth
having — that half with the vocabulary of printed noun phrases, this half with
CR 601.2b-d: how many objects are announced, whether the caster or the card
chooses them, how a divided spell shares one amount out, and which of several
slots is asked for first.

The predicates come with it. ``_is_target`` and ``_names_several_targets`` are
"does this phrase announce one chosen object, or several?", which is the same
question the descriptions answer and is the reason a lowering opts into
:func:`_describe_several_targets` per call site. ``_targeted_specs`` and
``_refuse_unfused_distinctness`` are CR 601.2c's distinctness, which is a fact
about a sentence's targets and about nothing else.

Every name is re-exported from ``_common``, so no family imports this module
directly and no caller changed at the split.
"""

import dataclasses

from .. import ast
from ..errors import LoweringError

from ._filters import _filter_payload


def divided_target_description(
    type_filter: str, *, max_targets: int | None = None
) -> dict[str, object]:
    """The ``targets`` description a distributed effect carries (CR 601.2d).

    Here rather than in the family that builds it because four readers share
    the shape and none of them is a lowering: the casting path's announcement
    gate, ``targeting.py``'s picker, ``divided_damage.divided_description`` and
    the handler. A second spelling of these keys is a picker that offers what
    the gate refuses.

    *max_targets* is CR 601.2c's printed ceiling on a variable target count
    ("among **one or two** target creatures") and is omitted entirely when the
    card prints "any number of" — an absent key is the unbounded sentence, so a
    reader written before the bound existed keeps meaning what it meant.
    """
    from ...divided_damage import CHOSEN

    described: dict[str, object] = {
        "quantifier": "divided",
        "kind": "divided",
        "division": CHOSEN,
        "filter": {"type_filter": type_filter},
    }
    if max_targets is not None:
        described["max_targets"] = max_targets
    return described


def card_divided_target_description(
    *, division: str, count: "int | str", shares: "tuple[int, ...] | None" = None,
) -> dict[str, object]:
    """The ``targets`` description for a list of targets the **card** sizes and
    shares out (CR 601.2c, and CR 601.2d only in the sense that it is not asked).

    "Firestorm deals X damage to each of X targets" and "Cone of Flame deals 1
    damage to any target, 2 damage to another target, and 3 damage to a third
    target" are one shape with two fillings: a cross-seat list of chosen
    targets, a printed number of them, and a printed amount for each. That is
    the ``divided`` channel — the engine's only announcement of a target list
    spanning both battlefields and the players' faces — with the two things a
    caster normally supplies taken away from them.

    Beside :func:`divided_target_description` for its stated reason, which
    applies here twice over: the casting path's announcement gate, the picker,
    ``divided_damage.divided_description`` and the handler all read these keys,
    and now so does the share stamping in between.

    ``count`` is the printed number or the string ``"x"`` — the two spellings
    ``_describe_several_targets`` writes into its own ``count`` — because
    Firestorm's is the X announced under CR 107.3a and does not exist until the
    cast. ``shares`` is omitted for :data:`~engine.divided_damage.EACH`, where
    every target takes the whole amount and a list would be a second copy of one
    number.

    **It is written under ``target_count``, not ``count``**, and the difference
    is not cosmetic. ``targets["count"]`` already means "this description names
    a list of *permanents*" to three readers that were written before a divided
    description could carry a number — ``handlers/damage``'s several-targets
    branch, ``ai_valuation._several_target_instruction`` and the graveyard
    picker — and the first of those sits above the divided branch in the same
    function, so a divided description carrying a ``count`` was silently
    resolved as an "up to N target creatures" and dealt nothing at all.
    """
    described: dict[str, object] = {
        "quantifier": "divided",
        "kind": "divided",
        "division": division,
        "target_count": count,
    }
    if shares is not None:
        described["shares"] = list(shares)
    return described


def card_divided_each_description(
    recipient: "ast.Recipient",
) -> dict[str, object] | None:
    """The description "…to **each of N targets**" means, or None.

    "Firestorm deals X damage to each of X targets." Every target takes the
    whole printed amount, so nothing is divided and nothing is announced —
    what the card supplies is the *count*, and the caster supplies the targets.

    None for the singular "any target", which is the shape every other burn
    spell in the pool prints and which the ordinary one-target description
    already reads.

    Here rather than in ``lowering/damage.py`` for the reason
    :func:`divided_target_description` is here: this description is read by the
    casting path's gate, the picker, the share stamping and the handler, and the
    module that builds it is not the module that owns any of them.
    """
    from ...divided_damage import EACH

    if not (
        isinstance(recipient, ast.TargetSpec)
        and recipient.quantifier == "any_target"
        and (recipient.count_from_x or recipient.count > 1)
    ):
        return None
    return card_divided_target_description(
        division=EACH,
        count="x" if recipient.count_from_x else recipient.count,
    )


def card_divided_shares_payload(effects) -> dict[str, object] | None:
    """The one ``deal_damage`` payload a run of same-source damage clauses with
    **printed shares** means, or None when the run is not that shape.

    "Cone of Flame deals 1 damage to any target, 2 damage to another target,
    and 3 damage to a third target." Three clauses, three amounts and three
    targets of the same kind — which CR 601.2c settles in one announcement, so
    it must be one instruction: three would raise three pickers for one printed
    choice, and only the first would reach the stack item.

    Every condition below is a way the run could mean something else, and the
    caller falls back to lowering the clauses separately when any of them fails:

    * the clauses must share a **source**, or they are not one sentence's
      damage;
    * each must name exactly one recipient, and that recipient must be
      CR 115.4's "any target" — the only recipient the ``divided_targets``
      channel can carry, because it spans both battlefields and the faces;
    * every clause after the first must print the distinctness the card states
      ("**another** target", "a **third** target"), and the first must not:
      a run of three identical "any target" clauses is a different sentence,
      and reading it as this one would refuse a legal repeat;
    * every amount must be a printed number, because the shares travel as
      numbers on the announcement (there is nowhere on the wire to put an
      unevaluated quantity);
    * no clause may carry a rider, a chooser or a per-object multiplier — each
      of those belongs to one clause, and this fuses the clauses into one
      instruction that has one of each.

    ``amount`` is the **sum**, which is what every reader that sizes a divided
    spell already asks for (``casting._divided_total``, the AI's valuation) and
    is honest: it is what the spell deals in total. The per-target numbers ride
    the ``shares`` list, and the stamping at announcement is what pins each one
    to its target.
    """
    from ...divided_damage import FIXED

    if len(effects) < 2 or not all(
        isinstance(effect, ast.DealDamage) for effect in effects
    ):
        return None
    shares: list[int] = []
    for position, clause in enumerate(effects):
        if (
            clause.source != effects[0].source
            or clause.riders != ast.DamageRiders()
            or clause.chooser is not None
            or clause.per_each is not None
            or len(clause.recipients) != 1
            or not isinstance(clause.amount, ast.Fixed)
        ):
            return None
        recipient = clause.recipients[0]
        if not (
            isinstance(recipient, ast.TargetSpec)
            and recipient.quantifier == "any_target"
            and recipient.count == 1
            and not recipient.count_from_x
            and recipient.distinct_from_prior == (position > 0)
        ):
            return None
        shares.append(int(clause.amount.value))
    return {
        "amount": sum(shares),
        "targets": card_divided_target_description(
            division=FIXED, count=len(shares), shares=tuple(shares),
        ),
    }


def _carries_x_bound(described: object) -> bool:
    """Whether *described* holds a numeric bound the announcement supplies.

    ``oracle_types``' own predicate, imported rather than re-spelled: the
    substitution and this refusal have to agree about which payloads carry one,
    and two spellings of "is there an X in here" is how they come apart.
    """
    from ...oracle_types import _carries_x_bound as carries

    return carries(described)


def _describe_targets(
    payload: dict[str, object],
    recipient: ast.Recipient,
    *,
    carried_separately: frozenset[str] = frozenset(),
    announced_x_bound: bool = False,
) -> None:
    """Record what *recipient* refers to on *payload*, if it names a target.

    *carried_separately* travels through to ``_filter_payload``: a lowering that
    lifts a narrowing out of the filter into its own key has to say so **here**
    too, or the description it builds of the same noun phrase refuses the phrase
    the instruction beside it accepts.

    *announced_x_bound* is a lowering's claim that every announcement-time
    reader of its kind resolves an X bound: the cast gate
    (``casting._validate_cast_targets``) substitutes the announced X before any
    arm reads the description and the picker probes without it, and the
    handler re-asks it through the dispatcher's substitution (CR 601.2b, then
    601.2c, then 608.2b). Only a lowering whose handler re-checks its own
    description at resolution may make it.
    """
    described = _targets_payload(recipient, carried_separately=carried_separately)
    if described is not None:
        if announced_x_bound:
            payload["targets"] = described
            return
        # "target creature with mana value **X**". The bound is resolved at the
        # dispatch point (`oracle_types.substitute_x_bounds`), which every
        # *handler* passes through — and the target picker does not: it reads
        # this description at announcement, off the compiled payload, where the
        # bound is still the string. Read there it would compare an int against
        # "x"; dropped it would offer every mana value.
        #
        # So a targeted phrase carrying one refuses, exactly as it did before
        # the bound had any payload form at all, while the sweep that has no
        # picker (Meltdown, Ugin) is read. No card in either manifest role
        # prints the targeted shape; this is the boundary that keeps it that
        # way rather than a refusal anybody is waiting on.
        if _carries_x_bound(described):
            raise LoweringError(
                "a target picker cannot read a bound the announcement supplies",
                node=recipient,
            )
        payload["targets"] = described


def _targets_only(recipient: ast.Recipient) -> dict[str, object]:
    """A payload carrying nothing but the target description — for handlers
    whose behaviour takes no filter but whose *card* still targets."""
    payload: dict[str, object] = {}
    _describe_targets(payload, recipient)
    return payload


def _describe_several_targets(payload: dict[str, object], recipient: ast.TargetSpec) -> None:
    """Record an "up to N target …" description, N > 1, on *payload*.

    Separate from :func:`_describe_targets` and opted into per call site, which
    is the whole safety of it. Most lowerings emit an instruction whose handler
    resolves exactly one permanent; if the ordinary description quietly admitted
    several, ``engine/targeting.py`` would raise a two-target picker in front of
    a one-target handler and the second choice would be collected and dropped.
    So a lowering says "my handler reads a list" by calling *this*, and
    :func:`_names_several_targets` keeps refusing everywhere else.
    """
    if not recipient.targeted:
        # "Up to four lands" (Rewind) prints no "target": nothing is chosen at
        # cast, so describing it here would raise a cast-time picker in front
        # of a choice CR says is made on resolution.
        raise LoweringError(
            "this 'up to N' names no targets; the choice belongs to resolution",
            node=recipient,
        )
    payload["targets"] = {
        "quantifier": recipient.quantifier,
        "kind": "object",
        "filter": _filter_payload(recipient.filter),
        # The maximum, not the count chosen — "up to two" may legally name one
        # or none (CR 601.2c). "X target lands" (Candelabra of Tawnos) carries
        # the string instead: the number is the announced X, resolved where
        # every other computed amount is, and a literal 0 here would show a
        # picker that offers nothing.
        "count": "x" if recipient.count_from_x else recipient.count,
    }
    if recipient.quantifier in ("one_or_more", "any_number"):
        # No printed maximum, so the cap is however many legal targets there
        # are — a number that only exists once the picker has enumerated them
        # (engine/legality.py fills it in as an ordinary `max_targets`). A
        # `count` of 0 here would otherwise read as "no targets" and show a
        # picker that offers nothing.
        #
        # Both quantifiers, because the maximum is the same question for each.
        # Their *minimum* is not — "any number of" (Energy Arc) may name none
        # and "one or more" (Heaven's Gate and its four colour siblings) may
        # not — and nothing here or downstream carries a floor: there is no
        # `min_targets` in the engine, so the five "one or more" cards already
        # shipped may legally be cast naming nothing. That is a pre-existing
        # looseness this widening inherits rather than one it introduces, and
        # it is the only shape where "any number of" is not simply the more
        # permissive twin.
        payload["targets"]["unbounded"] = True


def _describe_several_card_targets(
    payload: dict[str, object], recipient: ast.TargetSpec
) -> None:
    """Record an "up to N target <type> card(s)" description, N > 1, where the
    targets are **cards in another zone** rather than permanents.

    A sibling of :func:`_describe_several_targets` rather than a branch in it,
    because the two cannot share a body: that one describes its filter through
    :func:`_filter_payload`, which **refuses** a card or a non-battlefield zone
    outright, and for a good reason - a filter payload has no way to say "in
    your graveyard", so emitting one would point the picker at the battlefield
    for an effect that reads a graveyard.

    The shared *key* is deliberate: ``targets["count"] > 1`` is the one query
    that finds every several-target instruction in a compiled program
    (``engine/ai_valuation.py`` walks for exactly that), so a card-shaped one
    filed under a different key would be invisible to it.
    """
    if not recipient.targeted:
        raise LoweringError(
            "this 'up to N' names no targets; the choice belongs to resolution",
            node=recipient,
        )
    payload["targets"] = {
        "quantifier": recipient.quantifier,
        "kind": "card",
        # No filter, deliberately. What the cards may be is already on the
        # instruction's own payload, which is what the handler and the spec
        # function both read; a second copy here could disagree with it, and
        # nothing would say which one won.
        #
        # The maximum, not the count chosen - "up to two" may legally name one
        # or none (CR 601.2c). "up to X target cards" (Reap) carries the string
        # instead, exactly as the permanent-shaped sibling above does: the
        # number is the announced X, resolved where every other computed amount
        # is, and a literal 0 here would show a picker that offers nothing.
        "count": "x" if recipient.count_from_x else recipient.count,
    }


def _player_comparison_payload(
    comparison: "ast.PlayerComparison", node,
) -> dict[str, object]:
    """The description ``legality``'s seat loop reads for "…who controls more
    creatures than they do".

    The counted quantity goes through :func:`_amounts.count_spec` — the same
    reader every printed "the number of …" goes through — so the picker counts
    a noun phrase the way every other consumer of those words counts it, and a
    phrase the evaluator cannot take refuses the sentence instead of being
    counted as something smaller. That is the whole reason the clause carries a
    filter rather than a word out of a closed list: one table, read by the gate
    that admits the card and by the enforcement that answers it.

    **Whose pile is counted is not part of the spec.** The picker asks the
    question once per candidate seat and hands ``evaluate_count`` that seat, so
    the possessive the card prints ("their graveyard") is the candidate by
    construction and any *other* seat word would be a second answer to a
    question the loop has already settled. Read and refused here rather than
    dropped: "who has more creature cards in **an opponent's** graveyard" is a
    different card, and lowering it onto this one would count the wrong pile.

    Imported inside the function because ``_amounts`` reads ``_common``, which
    reads this module — the same call-time import ``hand.py`` makes one family
    over, and for the same reason.
    """
    from ._amounts import count_spec

    quantity = comparison.quantity
    if isinstance(quantity, str):
        # "…who has more **life** than they do" (Oath of Mages). The one
        # quantity no noun phrase describes, mapped onto the single computation
        # that is exactly it — `ast.BoardCount`'s discipline, and the miss
        # raises rather than counting nothing.
        if quantity != "life":
            raise LoweringError(
                f"no count reads a player's {quantity!r}", node=node,
            )
        count: dict[str, object] = {"board_count": "their_life"}
    else:
        zone_owner = quantity.zone_owner
        if zone_owner is not None and zone_owner.kind != "owner":
            raise LoweringError(
                "a seat comparison counts the candidate's own zone, not the "
                f"{zone_owner.kind}'s",
                node=node,
            )
        count = count_spec(
            dataclasses.replace(quantity, zone_owner=None), node
        )
        if count.get("owner") != "you":
            raise LoweringError(
                "a seat comparison counts one seat's objects, and this phrase "
                f"names the {count.get('owner')}'s",
                node=node,
            )
    described: dict[str, object] = {
        "count": count,
        "more": comparison.more,
        "margin": comparison.margin,
        "than": comparison.than,
    }
    # Omitted at its default, so a description written for a card that prints
    # only the comparison stays byte-identical to what it would have been.
    if comparison.is_opponent:
        described["is_opponent"] = True
    return described


def _with_player_comparison(
    described: dict[str, object], recipient: "ast.PlayerRef",
) -> dict[str, object]:
    """*described* plus the comparison clause *recipient* carries, if any."""
    if recipient.compared is None:
        return described
    described["compared"] = _player_comparison_payload(
        recipient.compared, recipient
    )
    return described


def _targets_payload(
    recipient: ast.Recipient,
    *,
    carried_separately: frozenset[str] = frozenset(),
) -> dict[str, object] | None:
    """A description of what *recipient* refers to, for engine/targeting.py.

    Only the shapes that name a cast-time target are described. "You" and
    "each player" are not targets at all (CR 115.10b), so they get no entry
    rather than a misleading one.
    """
    if isinstance(recipient, ast.PlayerRef):
        if recipient.compared is not None and recipient.kind not in (
            "target_player", "target_opponent"
        ):
            # A seat narrowing nothing enumerates is a sentence that acts on
            # every player, so the shapes this description cannot carry refuse
            # the line rather than losing the clause. Only a *chosen* seat has
            # a picker to enforce it: CR 115.1's announcement is where the
            # comparison is answered, and "you" or "each player" chooses
            # nobody.
            raise LoweringError(
                f"a seat comparison cannot narrow {recipient.kind!r}, which "
                "nothing chooses",
                node=recipient,
            )
        if recipient.kind == "target_player":
            if recipient.attacked_this_turn:
                # "…**who attacked this turn**" (Fire and Brimstone). Carried
                # into the description the picker reads, because the picker is
                # what enforces it (engine/legality.py's seat loop). A
                # restriction the enumerator never sees is a restriction nobody
                # applies — and unenforced, the card hits any seat at all, which
                # is wrong in the caster's favour and silent.
                return _with_player_comparison({
                    "quantifier": "target", "kind": "player",
                    "attacked_this_turn": True,
                }, recipient)
            if recipient.or_planeswalker:
                # "target player or planeswalker" — one chosen slot answered by
                # a player face or a planeswalker permanent, the "any target"
                # resolution shape minus the creature half.
                return _with_player_comparison(
                    {"quantifier": "target", "kind": "player_or_planeswalker"},
                    recipient,
                )
            return _with_player_comparison(
                {"quantifier": "target", "kind": "player"}, recipient
            )
        if recipient.kind == "target_opponent":
            # "Target opponent" is a player target the caster's own seat cannot
            # answer (CR 115.4) — the same flag the phase-out sweep and Word of
            # Command's spec carry, so every player picker reads one vocabulary.
            #
            # "…**or planeswalker**" (Eternal Flame) widens the same slot the
            # same way it widens "target player" above, and the narrowing
            # survives it: the union is "a seat that is not mine, or a
            # planeswalker". A shared `player` answer dropped the word, which
            # silently deleted the planeswalker half of the card — the picker
            # offers exactly what this describes.
            described: dict[str, object] = {
                "quantifier": "target",
                "kind": (
                    "player_or_planeswalker" if recipient.or_planeswalker
                    else "player"
                ),
                "opponents_only": True,
            }
            if recipient.damaged_by_source:
                # "…**previously dealt damage by it**" (Diseased Vermin), for
                # the reason the attack narrowing one arm up is carried: the
                # picker enforces it, and a restriction the enumerator never
                # sees lets the ability hit any opponent at all.
                described["damaged_by_source"] = True
            return _with_player_comparison(described, recipient)
        return None
    if not isinstance(recipient, ast.TargetSpec):
        return None
    if recipient.quantifier == "any_target":
        return {"quantifier": "any_target", "kind": "any"}
    if not _is_target(recipient):
        return None
    filt = recipient.filter
    if recipient.distinct_from_prior:
        # "**Another** target creature" as the *only* chosen object of its
        # sentence (Selfless Savior). The word names a distinctness — CR 601.2c
        # lets two instances of "target" name the same object unless something
        # forbids it — and the referent it must differ from is whatever the
        # sentence chose earlier. Here nothing did: this description is reached
        # only from a statement whose targets are this one, because the
        # multi-clause case is refused above it (`_refuse_unfused_distinctness`)
        # and the two lowerings that can honour a per-clause distinctness
        # (`_fused_two_target_pump`, `target_bites_target`) build their own
        # description and never call this. So the only object left in the
        # sentence for "another" to exclude is the ability's source (CR 109.5),
        # which is exactly what `other_than_source` says — the same restriction
        # printed a second way, and the spelling `parse_target_spec` already
        # produces for "up to two **other** target creatures".
        #
        # Written as a filter rewrite rather than a payload key so it goes
        # through `_filter_payload` like every other narrowing, and so the picker
        # (`_narrowing_flags` -> `exclude_source`) and the handlers read one key.
        filt = dataclasses.replace(filt, other_than_source=True)
    # The quantifier is carried rather than written as the constant "target":
    # "up to one target creature" may legally choose nothing (CR 601.2c) while
    # a plain "target" must be answered, and a picker reading this key can tell
    # them apart. Collapsing both would make the description lie.
    return {
        "quantifier": recipient.quantifier,
        "kind": "object",
        "filter": _filter_payload(filt, carried_separately=carried_separately),
    }


#: The filter keys ``destroy_target_permanent``'s several-target branch tests in
#: full, and therefore the only ones a list of destroy targets may be narrowed
#: by -- read by the plain "Destroy N target <noun>s" lowering and by the fused
#: "for each additional {1}{R} you paid, destroy another target <noun>" one.
#:
#: Named here rather than in either family because both read it and families do
#: not import each other. ``lowering/sequences.py`` had already written the
#: sentence 'named once because two readings of "what may a list of destroy
#: targets be narrowed by" is one reading too many' over its own copy --
#: while ``lowering/destruction.py`` went on spelling the same six words inline,
#: so the constant that claimed to be the single naming was the *second* of two.
#: A set that drifts here drops a narrowing from a sweep, which destroys
#: permanents the card does not name.
#:
#: ``excluded_colors`` is here because the pure matcher tests it
#: (``exclude_colors`` is in ``TESTABLE_SUBJECT_FILTER_KEYS`` and
#: ``permanent_matches_filter`` reads it off CR 202.2's printed mana cost), and
#: a key the matcher tests that this set leaves out is a *false* refusal: the
#: whole line is declined rather than narrowed, which is what left Dregs of
#: Sorrow and Reckless Spite unsupported.
SEVERAL_DESTROY_NARROWINGS = frozenset({
    "card_types", "supertypes", "subtypes", "colors", "excluded_colors",
    "controller", "other_than_source",
})


def _names_several_targets(subject: ast.Recipient) -> bool:
    """Whether *subject* names more than one chosen target.

    One definition, because "up to two" and "up to four" are the same shape and
    the number is the only thing separating Frost Breath from Twiddle. The
    lowerings that could previously read an ``up_to`` subject dropped ``count``
    on the floor and emitted a single-target instruction — so Rewind untapped
    *one* land of up to four and reported itself supported. A refusal naming
    the gap is the honest answer until a handler resolves a list of targets.
    """
    return (
        isinstance(subject, ast.TargetSpec)
        # "up to N target …" and "**N** target …" are the same shape to every
        # reader downstream; only the floor differs, and the floor is the
        # picker's business rather than the lowering's. "X target lands" has no
        # printed number at all, so its count is unknown here and it qualifies
        # on the quantifier alone.
        and (
            (subject.quantifier == "up_to"
             and (subject.count_from_x or subject.count > 1))
            or (subject.quantifier == "exactly"
                and (subject.count_from_x or subject.count > 1))
            # "One or more target creatures" prints no number at all, so it
            # qualifies on the quantifier alone — the same way "X target lands"
            # above does, and for the same reason: the count is not knowable
            # here, only that it can exceed one.
            #
            # "**Any number of** target creatures" (Energy Arc) is the same
            # shape one word over. The two differ only in their *floor* — CR
            # 601.2c lets "any number of" name none where "one or more" must
            # name one — and the floor is not what this predicate asks about.
            or subject.quantifier in ("one_or_more", "any_number")
        )
    )


def _is_target(subject: ast.Recipient) -> bool:
    """Whether *subject* names exactly **one** chosen target.

    "Up to one **target**" qualifies: it picks a single target or none, which
    is what every handler reading ``context.target_permanent_id`` already
    does. "Up to two" does not, and must not — see
    :func:`_names_several_targets`. Neither does an "up to one" that prints no
    "target" at all: the parser records the word (``TargetSpec.targeted``)
    because CR 115.1b makes the untargeted spelling a *resolution* choice, and
    answering it with a cast-time picker would be the same wider-than-printed
    reading :func:`_describe_several_targets` refuses for "up to four lands".
    """
    if not isinstance(subject, ast.TargetSpec):
        return False
    if subject.quantifier == "target":
        return True
    return (
        subject.quantifier == "up_to"
        and subject.targeted
        and not _names_several_targets(subject)
    )


def _targeted_specs(node: object) -> tuple[ast.TargetSpec, ...]:
    """Every ``TargetSpec`` in *node*'s subtree that prints the word "target".

    Written against the dataclass fields rather than a per-node list, for the
    reason ``_restrictions_beyond`` gives: a statement class added later is then
    covered by default instead of silently answering "no targets here".
    """
    found: list[ast.TargetSpec] = []
    if isinstance(node, ast.TargetSpec):
        if node.targeted:
            found.append(node)
        # A filter carries no recipients, so there is nothing below this.
        return tuple(found)
    if dataclasses.is_dataclass(node) and not isinstance(node, type):
        for field in dataclasses.fields(node):
            found.extend(_targeted_specs(getattr(node, field.name)))
    elif isinstance(node, (tuple, list)):
        for item in node:
            found.extend(_targeted_specs(item))
    return tuple(found)


def _refuse_unfused_distinctness(steps: tuple[ast.Statement, ...]) -> None:
    """Refuse a multi-clause sentence whose printed "another target" no fuser claimed.

    CR 601.2c lets two instances of the word "target" name the same object unless
    something forbids it, and ``TargetSpec.distinct_from_prior`` is that
    forbidding: "**another** target creature" must differ from the choice the
    sentence already made. Honouring it needs an instruction with a slot per
    clause — ``_fused_two_target_pump`` and ``target_bites_target`` are the two
    that have one — because every other handler resolves through ``_one_choice``
    and would read the *first* chosen permanent for both clauses.

    Reaching ``_lower_steps`` with the word still on a step therefore means two
    things at once: the clauses would land on one permanent, and
    ``_targets_payload`` would read the word as CR 109.5's source exclusion,
    which is a different restriction. Both are the wider-than-printed outcome, so
    the sentence refuses.

    Positioned **after** the fusers on purpose: a shape that grows a fused
    lowering later is claimed above this and never reaches it, so this refusal
    can only shrink as the engine learns more, never has to be edited.

    **The count that matters is of targets, not of clauses.** "This creature
    deals damage equal to its power to **another** target creature. That
    creature deals damage equal to its power to this creature." (Gargantuan
    Gorilla — Tracker's sentence with the word added.) Two clauses and *one*
    target: the second names its subject with a back-reference to what the
    first one chose, so there is no prior choice for "another" to differ from
    and the only object left in the sentence for it to exclude is the ability's
    source, which is CR 109.5 and exactly what ``_targets_payload`` turns it
    into one function above. Refusing on the clause count instead read the
    hazard off the wrong number — the hazard is two pickers reading one answer,
    which needs two printed targets to exist at all.
    """
    targeted = [spec for step in steps for spec in _targeted_specs(step)]
    if len(targeted) < 2:
        return
    for spec in targeted:
        if spec.distinct_from_prior:
            raise LoweringError(
                'a printed "another target" in a multi-clause sentence needs '
                "a lowering with a slot per clause",
                node=spec,
            )


def optional_slot_positions(specs) -> tuple[int, ...]:
    """Which of *specs* CR 601.2c lets the announcement leave empty.

    "…it fights **up to one** target creature an opponent controls" (Primal
    Might) against "…deals damage … to target creature an opponent controls"
    (Hunter's Edge). One word apart, and the multi-slot description could not
    tell them apart: every slot was flattened into one ``count``, so a reader
    deriving per-slot behaviour from it turned an optional slot into a required
    one. ``up_to`` is the quantifier the parser already records for the printed
    "up to", so this reads the fact rather than re-deriving it.

    Returned as positions rather than as a per-slot list of quantifiers, because
    what every reader wants to know is "may this slot be skipped?" — and a list
    that repeats "target" for the ordinary card is a key on every description
    instead of on the few that mean something by it.
    """
    return tuple(
        position
        for position, spec in enumerate(specs)
        if getattr(spec, "quantifier", None) == "up_to"
    )


def _optional_slot_key(specs) -> dict:
    """``{"optional_slots": [...]}`` for *specs*, or ``{}`` when none is.

    A key rather than a value so a producer can splat it into the description
    and the ordinary two-target card stays byte-identical to what it was — an
    ``optional_slots: []`` on every multi-slot description would move every one
    of their compiled programs to say nothing.
    """
    positions = optional_slot_positions(specs)
    return {"optional_slots": list(positions)} if positions else {}
