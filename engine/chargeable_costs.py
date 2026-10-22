"""The charger's reading of a prose cost: what the payment path can collect.

A printed cost has two readers — the grammar's cost side, which decides
whether to admit the line (``engine/grammar/chargeable.py``), and the charger,
which collects the payment — and they must give one answer, or the pool grows
an ability the grammar let through and nothing paid for. They give it by
being one function: the grammar's gates call these readers, and so do the
activation cost parser (``engine/activation_costs.py``) and the additional-,
alternative- and upkeep-cost tables (``cast_costs``, ``alternative_costs``,
``upkeep_costs``).

Each reader **delimits** a cost segment with a regex and reads it with the
noun parser and ``_NUMBER_WORDS`` — "Sacrifice <noun>", "Exile <noun>",
"Discard <noun>", "Tap N <noun>", "Return <noun> to its owner's hand", "Untap
<noun>", "put a counter on <noun>" — then reduces the phrase to the keys the
charger can test. A key it cannot test refuses the cost rather than being
dropped, and a phrase naming a permanent the payer does not control is not a
payable cost at all (CR 701.21a).

Split out of ``engine/oracle.py`` at the 2,000-line cap; ``engine.oracle``
still exports :func:`chargeable_sacrifice_payload`, which is in its
``__all__``.
"""

from __future__ import annotations

import re

from .oracle_types import _NUMBER_WORDS


def _chargeable_sacrifice_filter(phrase: str, *, plural: bool = False) -> dict | None:
    """The filter payload a "Sacrifice <noun phrase>" cost charges, or None when
    the payment path cannot collect it.

    The two halves of a sacrifice cost — this reader, which charges it, and
    ``engine/grammar``'s ``_is_chargeable_sacrifice``, which decides whether to
    admit the line at all — must give the same answer or the pool grows a card
    the grammar accepted and nothing paid for. They give it by asking the same
    function: the noun parser for what the phrase names, and
    ``object_only_filter`` for whether the charger can test it. ``exclude_self``
    ("another") stays in the payload here, because the charger has the ability's
    source and compares by identity.
    """
    from .grammar import subject_filter_payload
    from .subject_filters import object_only_filter

    # *plural* is the "any number of **creatures you control**" tail (Sword of
    # the Ages): the count is printed in front of the phrase, so what is left is
    # a bare plural rather than the singular every other sacrifice cost names.
    # The grammar's cost side reads the same shape through ``bare_plural``, and
    # both are gated identically — the count changes how many are charged, never
    # what may pay.
    described = subject_filter_payload(phrase, plural=plural)
    if described is None:
        return None
    return chargeable_sacrifice_payload(described)


def _chargeable_counter_target(phrase: str) -> dict | None:
    """The filter payload a "put a counter on <noun phrase>" cost charges, or
    None when the payment path cannot find the permanent.

    The charging half of ``grammar/costs._is_chargeable_counter_target``, and
    the two agree by asking the same two functions the sacrifice pair asks —
    the noun parser for what the phrase names, and the charger's own reduction
    for whether it can be tested. A phrase one admitted and the other refused
    would be an ability the grammar let through and nothing charged, which is
    an ability activated for free.

    The reduction is the *sacrifice* one because the question is identical: the
    candidates come off the payer's own battlefield and are tested with
    ``subject_matches``. Only the verb differs, and a verb is not a filter.
    """
    from .grammar import subject_filter_payload

    described = subject_filter_payload(phrase)
    if described is None:
        return None
    return chargeable_sacrifice_payload(described)


def chargeable_sacrifice_payload(described: dict) -> dict | None:
    """The charger's reading of an already-parsed noun-phrase payload.

    Split out of :func:`_chargeable_sacrifice_filter` so the pool-wide guard in
    ``tests/engine/test_activation_costs.py`` can ask the same question of the
    grammar's own filter instead of re-deriving it. That guard compares what the
    grammar admitted against what this charges, and comparing a *raw* phrase
    payload against a reduced one reports a difference for every key the
    reduction legitimately drops — which is how "creatures **you control**"
    (Sword of the Ages) read as a dropped rider.

    Two keys are dropped rather than carried, and neither is a narrowing lost.
    ``controller`` is one: every path that charges a sacrifice enumerates the
    payer's own battlefield first, so "you control" restricts nothing the
    enumeration has not already done — but ``permanent_matches_filter`` has no
    observer, so a key left in would be handed over and refuse every candidate.
    ``exclude_self`` is the other, and it comes back on: the charger holds the
    ability's source and compares by identity.

    **That first reason holds for "you control" and for nothing else**, and the
    dropped key used to be dropped whatever it said. "Sacrifice all lands your
    opponents control" therefore read as *your own* lands: the narrowing was
    removed on the premise that the enumeration already made it, and the
    enumeration makes the opposite one. CR 701.21a settles it -- "a player
    can't sacrifice ... a permanent they don't control" -- so a phrase naming
    anyone else's permanent is not a payable cost at all, and refusing the line
    is what leaves the card unsupported instead of charging a price nobody
    printed. No card in either manifest role prints one; the reader is what
    would have admitted the first.
    """
    from .subject_filters import object_only_filter

    if described.get("controller") not in (None, "you"):
        return None
    carried = object_only_filter(
        described, carried_separately=frozenset({"exclude_self", "controller"})
    )
    if carried is None:
        return None
    if "exclude_self" in described:
        carried = {**carried, "exclude_self": True}
    return carried


def chargeable_exile_payload(described: dict) -> dict | None:
    """The charger's reading of an "Exile <noun phrase>" cost's noun payload.

    :func:`chargeable_sacrifice_payload` one zone wider, and shaped the same way
    for the same reason: the grammar admits the line by asking this, the
    activation path charges the cost by asking this, and the pool-wide guard in
    ``tests/engine/test_activation_costs.py`` compares the two answers.

    ``zone`` and ``zone_owner`` are dropped rather than carried - the charger
    enumerates one named zone of one named seat, so they restrict nothing the
    enumeration has not already done, and a key handed to a matcher that cannot
    test it would refuse every candidate. ``controller`` goes the same way and
    for the reason a sacrifice's does; ``exclude_self`` comes back on, because
    the charger holds the source and compares by identity.

    And it is refused for anyone but the payer, for the reason
    :func:`chargeable_sacrifice_payload` states one function up: the seat the
    enumeration names is the payer's, so "a creature **an opponent controls**"
    would have the narrowing dropped and the payer's own creature charged.
    """
    from .subject_filters import card_only_filter, object_only_filter

    if described.get("controller") not in (None, "you"):
        return None
    zone = described.get("zone")
    stripped = {
        key: value for key, value in described.items()
        if key not in ("zone", "zone_owner")
    }
    if zone in ("graveyard", "hand"):
        # A card in a zone has no computed characteristics (CR 613.1), so the
        # card matcher is what answers here - the same split
        # ``chargeable_card_filter`` makes for a discard cost, and a hand is
        # the zone that discard already reads.
        return card_only_filter(stripped)
    carried = object_only_filter(
        stripped, carried_separately=frozenset({"exclude_self", "controller"})
    )
    if carried is None:
        return None
    if "exclude_self" in stripped:
        carried = {**carried, "exclude_self": True}
    return carried


def cost_object_is_chargeable(carried: dict | None) -> bool:
    """Whether the payment path can collect a cost described by this *reduced*
    payload.

    The one reader of a question three cost tables were each answering with
    their own spelling: ``grammar/costs._is_chargeable_sacrifice`` asked
    ``card_types or subtypes or named``, ``_is_chargeable_exile`` asked
    ``card_types or subtypes``, and ``cast_cost_clauses._chargeable_object``
    asked ``type_filter or subtype_filter``. Three answers to one question is
    the second-copy shape this repo refuses, and here the copies had already
    drifted: "Sacrifice a token named Wood" (Jungle Patrol) was chargeable as
    an *activation* cost and would have been refused as an additional one, on
    a phrase that pins the object harder than any type could.

    It was called ``cost_object_is_named`` and asked ``bool(carried)`` — the
    reduction must carry *something* — on the ground that an **unnamed** cost
    would let the payment eat the cheapest thing the payer owns, a land
    included. Urza's Saga prints two costs whose noun phrase is exactly "a
    permanent" (Barrin, Master Wizard; Claws of Gix), and for those the land is
    what the card says may pay: the widest printed noun is still a printed
    noun, and refusing it cost both cards their support rather than protecting
    anything.

    What the old rule was really guarding is a narrowing the reduction
    **lost**, and that cannot happen here: ``object_only_filter`` returns
    ``None`` for any key the matcher cannot test rather than dropping it, and
    the two keys it does drop are carried by the caller —
    :func:`chargeable_sacrifice_payload` re-adds ``exclude_self`` and refuses a
    ``controller`` that is not the payer's own. So the honest question left is
    the one this now asks, and the empty reduction is a real answer: "any
    permanent you control", which is what both cards print and what
    ``filter_head_noun`` already logs and pickers as "permanent".

    It takes the reduction rather than the raw phrase payload deliberately: a
    key the charger *drops* is not a narrowing the payment can be held to.
    """
    return carried is not None


def _chargeable_exile_filter(phrase: str, *, plural: bool = False) -> dict | None:
    """The filter payload an "Exile <noun phrase>" cost charges, or None when the
    payment path cannot collect it. The two-halves pairing
    :func:`_chargeable_sacrifice_filter` describes, one zone wider."""
    from .grammar.phrases import parse_subject_filter

    # The noun parser directly rather than ``subject_filter_payload``: that
    # reader refuses any phrase naming a zone at all, because a *trigger*
    # subject is always a permanent - and "a creature card **from your
    # graveyard**" is exactly the shape it exists to refuse. The zone is the
    # point here, so the gate is ``chargeable_exile_payload`` alone, which is
    # also the function the grammar's own cost side asks (idiom 1).
    filt = parse_subject_filter(phrase, plural=plural)
    if filt is None:
        return None
    return chargeable_exile_payload(filt.to_payload())


def _chargeable_discard_filters(phrase: str) -> tuple[dict, ...] | None:
    """The alternatives a "Discard <noun phrase>" cost may be paid with, or None
    when the payment path cannot collect it.

    The card twin of :func:`_chargeable_sacrifice_filter`, in the same
    two-halves arrangement and for the same reason: this reader charges the
    cost, ``engine/grammar``'s ``_parse_discard_cost_alternatives`` decides
    whether to admit the line at all, and they cannot disagree because both ask
    ``chargeable_card_filter`` what the phrase names.

    An empty tuple is the unrestricted "Discard a card" — a real answer, not a
    refusal — which is why None is the refusal and why the caller reads the
    *count* off this rather than off a second regex of its own.

    **The whole phrase is offered to the noun parser before the "or" is split
    on**, and that ordering is load-bearing: Magic prints two different
    disjunctions with one word. "A land card **or** Shrine card" is two noun
    phrases, each with its own head, and only the split reads it; "a red **or**
    green card" is *one* noun phrase with two colour adjectives sharing a head,
    which the noun parser reads on its own and the split shreds into "a red"
    (nothing) and "green card". Splitting first therefore refused the second
    shape outright — and a refused cost clause is a cost the card prints and
    nothing charges.
    """
    from .grammar import card_filter_payload

    whole = card_filter_payload(phrase)
    if whole is not None:
        return (whole,) if whole else ()
    alternatives: list[dict] = []
    for side in phrase.split(" or "):
        described = card_filter_payload(side)
        if described is None:
            return None
        if described:
            alternatives.append(described)
    return tuple(alternatives)


_TAP_COST_RE = re.compile(r"\btap (\w+) ([^,:]+?)\s*(?=,|$)")


def _chargeable_tap_cost(cost_lower: str) -> tuple[int, dict] | None:
    """The ``(count, filter)`` a "Tap N <noun phrase>" cost charges, or None.

    The regex only **delimits** the number and the noun phrase, to the end of
    its comma-separated cost segment; ``_NUMBER_WORDS`` reads the one and the
    noun parser the other — the split every other prose cost in this file makes,
    and for the same reason: a regex approximating the noun parser is a second
    reader of one clause, and the direction those drift in is a cost charged
    more widely than the card prints.
    """
    from .grammar import subject_filter_payload
    from .grammar.lowering._common import chargeable_tap_filter
    from .grammar.phrases import parse_subject_filter

    match = _TAP_COST_RE.search(cost_lower)
    if match is None:
        return None
    word = match.group(1)
    count = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
    if count <= 0:
        return None
    filt = parse_subject_filter(match.group(2), plural=True)
    if filt is None:
        return None
    described = chargeable_tap_filter(filt)
    if described is None:
        return None
    return count, described


#: "**Return a Forest you control to its owner's hand**" (Quirion Ranger),
#: "**Return two Islands you control to their owner's hand**" (Flooded
#: Shoreline). One comma-separated cost segment, delimiting only: the number is
#: read by ``_NUMBER_WORDS`` and the noun phrase by the noun parser, which is
#: the split :func:`_chargeable_tap_cost` makes above and for its reason — a
#: regex approximating the noun parser is a second reader of one clause, and
#: the direction the two drift in is a cost charged more widely than the card
#: prints.
#:
#: The possessive is part of the pattern rather than trailing slack: "to its
#: owner's hand" and "to their owner's hand" are English inflection over one
#: destination, and any *other* destination is a different cost this cannot
#: charge.
_RETURN_TO_HAND_COST_RE = re.compile(
    r"\breturn (\w+) (.+?) to (?:its|their) owner's hand\s*(?=,|$)"
)


def _chargeable_return_to_hand_cost(cost_lower: str) -> tuple[int, dict] | None:
    """The ``(count, filter)`` a "Return N <noun phrase> to its owner's hand"
    cost charges, or None.

    Gated on what ``subject_filters.subject_matches`` can test, because that is
    what the charger enumerates with: a phrase reaching past it would be
    *dropped* by the matcher rather than refused, and the cost would then be
    payable off a wider set of permanents than the card names.

    The self-return ("Return **this creature** to its owner's hand",
    Ovinomancer) is ``return_self_to_hand``'s and never reaches here: its noun
    phrase is a self-reference, which the subject parser has no filter for, so
    the two readers of this printed clause cannot both claim one segment.
    """
    from .grammar.lowering._common import chargeable_tap_filter
    from .grammar.phrases import parse_subject_filter

    match = _RETURN_TO_HAND_COST_RE.search(cost_lower)
    if match is None:
        return None
    word = match.group(1)
    count = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
    if count <= 0:
        return None
    # ``plural=True`` whatever the printed count, exactly as the tap cost
    # above: the counted position is the one the noun parser wants told
    # about, and the number is read here rather than by it.
    filt = parse_subject_filter(match.group(2), plural=True)
    if filt is None:
        return None
    # The same gate the tap cost uses, which is what keeps the two chosen-cost
    # readers agreeing about which noun phrases are chargeable at all: it
    # answers None for anything ``subject_matches`` cannot test, and the
    # charger enumerates with exactly that predicate.
    described = chargeable_tap_filter(filt)
    if described is None:
        return None
    # "**you control**" is the seat the charger draws from, and the charger
    # draws from the activating player's own battlefield — so the clause is
    # honoured there and must not also ride the filter, where a second reader
    # would be free to disagree with it. A phrase naming *another* seat is a
    # cost this cannot charge and refuses outright.
    if filt.controller not in (None, "you"):
        return None
    return count, described


#: "**Untap a tapped land an opponent controls**" (Benthic Explorers). One
#: comma-separated cost segment, whole, and delimiting only — what the noun
#: phrase names is read by the noun parser below, which is the split
#: :func:`_chargeable_tap_cost` makes above and for its reason: a regex
#: approximating the noun parser is a second reader of one clause, and the
#: direction the two drift in is a cost charged more widely than the card
#: prints.
_UNTAP_COST_RE = re.compile(r"^untap (an? .+)$")


def _chargeable_untap_cost(cost_lower: str) -> dict | None:
    """The filter an "Untap a <noun phrase>" cost charges, or None.

    Gated on what ``subject_filters.subject_matches`` can test, because that is
    what the charger enumerates with: a phrase reaching past it would be
    *dropped* by the matcher rather than refused, and the cost would then be
    payable off a wider set of permanents than the card names.

    The "tapped" half of the phrase is required by the grammar's own production
    and re-read here rather than assumed — untapping an untapped permanent is
    no payment, and the two readers of this clause have to agree about that as
    much as about the noun.
    """
    from .grammar.phrases import parse_subject_filter
    from .subject_filters import untestable_filter_keys

    for segment in cost_lower.split(","):
        match = _UNTAP_COST_RE.match(segment.strip())
        if match is None:
            continue
        filt = parse_subject_filter(match.group(1))
        if filt is None or filt.tapped is not True:
            return None
        described = filt.to_payload()
        if untestable_filter_keys(described):
            return None
        return described
    return None
