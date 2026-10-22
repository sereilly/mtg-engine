"""A word whose meaning was **chosen**, turned into the keys every matcher reads.

"Of the chosen color", "of the chosen type", "with the chosen ability", "of
that type", "of that color", "with the same name as that spell": in each, a
printed noun phrase narrows by a value no printed word holds. It was chosen as
the permanent entered (CR 614.1c), as the ability was activated (CR 602.2b), by
an earlier step of the same resolution (CR 608.2d), or frozen by a cast
trigger's fire site, and it is recorded on the source, on the resolution's
scratchpad or on the trigger's context. Each resolver here takes a filter
carrying the narrowing and returns it with the ordinary key written in —
``color_filter``, ``subtype_filter``, ``with_keywords``, ``type_filter``,
``named`` — so the matchers in ``_filters`` ask one question whoever chose.

A resolver with nothing recorded leaves the narrowing where it is, and both
matchers refuse a filter still carrying one. That is the direction a dropped
narrowing has to fail in: a sweep or a count that ignored it would reach the
whole board.

A floor, split out of ``_common`` at the 2,000-line cap's split round, and the
lowest of the four that module was cut into: ``_filters`` reads its keys, and it
reads nothing of the handler package back.
"""

from __future__ import annotations


def _resolve_chosen_color(filt: dict, source) -> dict:
    """*filt* with a ``chosen_color`` narrowing turned into a colour key.

    The colour a card chose as it entered (CR 614.1c) is recorded on the
    permanent, not in the sentence — so a noun phrase saying "of the chosen
    color" can only be answered by a reader holding that permanent. Callers
    without one leave the key in place and ``permanent_matches_filter`` refuses
    every permanent, which is the safe direction: a dropped narrowing would
    count (or destroy) the whole board.
    """
    if not filt.get("chosen_color"):
        return filt
    color = getattr(source, "metadata", {}).get("chosen_color") if source else None
    if not color:
        return filt
    resolved = dict(filt)
    resolved.pop("chosen_color", None)
    resolved["color_filter"] = color
    return resolved


#: Where the keyword an activation chose is recorded (Phyrexian Splicer). On
#: the ability's own source, exactly where CR 614.1c's entry choices are kept,
#: because that is the object every reader of the narrowing already holds — the
#: target enumerator at announcement and the handler at resolution.
CHOSEN_ABILITY = "chosen_ability"


def _resolve_chosen_keyword(filt: dict, source) -> dict:
    """*filt* with a ``chosen_keyword`` narrowing turned into a keyword list.

    "target creature **with the chosen ability**" (Phyrexian Splicer). The word
    was announced when the ability was activated (CR 601.2b through CR 602.2b),
    which is *before* its targets were chosen — so by the time anything asks
    this question the answer exists, and it is on the source.

    ``_resolve_chosen_color``'s sibling one characteristic over, and it resolves
    the same way: into the ordinary key every matcher already reads, which for a
    keyword is ``with_keywords`` and so goes through CR 613 layer 6 like any
    other keyword question — a creature *granted* flying answers a
    chosen-flying phrase exactly as a printed flyer does.

    A caller with no source, or a source with nothing recorded, leaves the key
    in place and the pure matcher refuses every permanent. That is the safe
    direction: a dropped narrowing here would offer every creature on the board
    as a target for an ability that names one class of them.
    """
    if not filt.get("chosen_keyword"):
        return filt
    keyword = getattr(source, "metadata", {}).get(CHOSEN_ABILITY) if source else None
    if not keyword:
        return filt
    resolved = dict(filt)
    resolved.pop("chosen_keyword", None)
    resolved["with_keywords"] = list(resolved.get("with_keywords") or ()) + [
        str(keyword)
    ]
    return resolved


#: The two narrowings "of the chosen type" can be, and where each one's word is
#: recorded on the source. Both are CR 614.1c choices made as the permanent
#: entered and both resolve to ``subtype_filter``; what separates them is the
#: *catalog* the word came from, which the sentence spells in its head noun —
#: CR 205.3m's creature types for An-Zerrin Ruins, CR 205.3i's land types for
#: Shimmer. One resolver rather than two, because two would be one idea spelled
#: twice with a metadata key changed.
_CHOSEN_SUBTYPE_KEYS = ("chosen_creature_type", "chosen_land_type")


def _resolve_chosen_subtype(filt: dict, source) -> dict:
    """*filt* with a "of the chosen type" narrowing turned into a subtype key.

    The type a card chose as it entered (CR 614.1c) is recorded on the
    permanent, not in the sentence — so "of the chosen type" can only be
    answered by a reader holding that permanent. The sibling of
    :func:`_resolve_chosen_color` one characteristic over, and it resolves the
    same way: into the ordinary key every matcher already reads, which for a
    subtype is ``subtype_filter`` and so goes through CR 613 layer 4 like any
    other type question.

    Callers without a source leave the key in place and
    ``permanent_matches_filter`` refuses every permanent, which is the safe
    direction: a dropped narrowing would hold the whole board down.
    """
    for key in _CHOSEN_SUBTYPE_KEYS:
        if not filt.get(key):
            continue
        word = getattr(source, "metadata", {}).get(key) if source else None
        if not word:
            continue
        resolved = dict(filt)
        resolved.pop(key, None)
        resolved["subtype_filter"] = word
        return resolved
    return filt


#: "…**that player** chooses artifact, creature, land, or non-Aura enchantment.
#: All nontoken permanents **of that type** phase out." (Teferi's Realm.) The
#: record the first sentence writes and the second reads, on the ability's own
#: source — the same place the CR 614.1c entry choices record theirs, so one
#: reader answers both.
#:
#: A **card type** rather than a subtype, which is why it is its own key and its
#: own resolver: CR 205.2's types and CR 205.3's subtypes are different halves of
#: the type line and land in different payload keys.
CHOSEN_CARD_TYPE = "chosen_card_type"

#: The printed options that name a type **and** a subtype to exclude, mapped to
#: the subtype. "Non-Aura enchantment" is Teferi's Realm's fourth option and the
#: only one in the pool; a card offering "non-Equipment artifact" would add a
#: row and nothing else.
#:
#: A table rather than a parse of the recorded string at read time, because the
#: string is what a *player* answered with: a prompt that accepted any
#: "non-<word> <type>" would let a seat invent an option the card never offered.
_QUALIFIED_CARD_TYPE_OPTIONS: dict[str, tuple[str, str]] = {
    "non-aura enchantment": ("enchantment", "aura"),
}


def chosen_card_type_filter(word: str) -> dict | None:
    """The filter keys the printed option *word* means, or None if it is not one.

    One function, read by the choice resolver (which validates an answer) and by
    :func:`_resolve_chosen_card_type` below (which applies it) — so what a player
    may choose and what the sweep then reaches cannot disagree.
    """
    from ..grammar.vocabulary import CARD_TYPES

    word = str(word or "").strip().lower()
    qualified = _QUALIFIED_CARD_TYPE_OPTIONS.get(word)
    if qualified is not None:
        card_type, excluded = qualified
        return {"type_filter": card_type, "exclude_subtypes": [excluded]}
    if word in CARD_TYPES:
        return {"type_filter": word}
    return None


def resolve_chosen_card_type_in_resolution(described: dict, context) -> dict:
    """*described* with "of the chosen type" spent out of the **scratchpad**.

    The other end of :func:`_resolve_chosen_card_type`, and the difference is
    only where the word was written down. A permanent's ability records its
    choice on the permanent (Teferi's Realm), which that function reads; a
    *spell* has no permanent, so ``choose_card_type`` writes the word into the
    resolution its own next step runs in (Turnabout). One relation, two homes,
    and which one a card uses is a fact about the card rather than about the
    printed phrase — so the payload key stays one key and the two readings meet
    here.

    Untouched when this resolution recorded nothing, which leaves the key in the
    filter for the source reading to answer. If neither answered, the key stays
    and ``permanent_matches_filter`` refuses every permanent — the direction a
    sweep must fail in, exactly as the source reader's own docstring says.
    """
    from ..oracle_types import CHOSEN_CARD_TYPE_THIS_WAY

    if not described.get(CHOSEN_CARD_TYPE):
        return described
    word = (getattr(context, "results", None) or {}).get(CHOSEN_CARD_TYPE_THIS_WAY)
    resolved_keys = chosen_card_type_filter(word) if word else None
    if resolved_keys is None:
        return described
    resolved = dict(described)
    resolved.pop(CHOSEN_CARD_TYPE, None)
    resolved.update(resolved_keys)
    return resolved


#: "…for each permanent **of that color**" (Rith, the Awakener), "…the number of
#: creatures **of that color** that player controls" (Searing Rays), "return all
#: creatures **of that color**" (Dromar, the Banisher). The filter key a noun
#: phrase carries when the colour it narrows by was chosen by an earlier step of
#: the *same resolution* (CR 608.2d) — ``ast.ObjectFilter.color_chosen_this_way``
#: — as against ``chosen_color``, whose colour a permanent recorded as it
#: entered (CR 614.1c).
COLOR_CHOSEN_THIS_WAY_KEY = "color_chosen_this_way"


def resolve_color_chosen_in_resolution(described: dict, context) -> dict:
    """*described* with "of that color" spent out of the **scratchpad**.

    :func:`resolve_chosen_card_type_in_resolution` one characteristic over, and
    the same contract: the colour is whatever ``choose_color`` wrote into the
    resolution its own next step runs in (``CHOSEN_COLOR_THIS_WAY``), turned
    into the ordinary ``color_filter`` every matcher already reads — so it goes
    through CR 613 layer 5 on a battlefield and CR 202.2 in a hand like any
    other colour question.

    Untouched when this resolution recorded nothing, which leaves the key in
    the filter — and both matchers refuse it outright, so an unanswered choice
    counts (or sweeps) nothing rather than the whole board. That is the
    direction the key had to be given: it reached the count evaluator unread
    for three cards, and "for each permanent of that color" counted every
    permanent its controller had.
    """
    from ..oracle_types import CHOSEN_COLOR_THIS_WAY

    if not described.get(COLOR_CHOSEN_THIS_WAY_KEY):
        return described
    symbol = (getattr(context, "results", None) or {}).get(CHOSEN_COLOR_THIS_WAY)
    if not symbol:
        return described
    resolved = dict(described)
    resolved.pop(COLOR_CHOSEN_THIS_WAY_KEY, None)
    resolved["color_filter"] = str(symbol)
    return resolved


def count_spec_in_resolution(spec: dict, context) -> dict:
    """*spec* with its filter's resolution-scoped words resolved.

    The one place a count taken while an effect is applied turns "of that
    color" into a colour, asked by both readers that hold a resolution
    (:func:`count_from_payload` and :func:`per_recipient_amount`) so the
    sentence means one thing whichever channel carried it.
    """
    described = spec.get("filter")
    if not isinstance(described, dict):
        return spec
    if described.get(NAMED_FROM_KEY):
        spec = {**spec, "filter": _resolve_named_from(described, context)}
        described = spec["filter"]
    if not described.get(COLOR_CHOSEN_THIS_WAY_KEY):
        return spec
    return {**spec, "filter": resolve_color_chosen_in_resolution(described, context)}


#: The count-filter key for a name only a resolution knows — "…cards in all
#: graveyards **with the same name as that spell**" (the five Shrines) — and
#: the one referent the lowering writes under it
#: (``grammar/lowering/_amounts.NAMED_FROM_TRIGGERING_SPELL``).
NAMED_FROM_KEY = "named_from"


def _resolve_named_from(described: dict, context) -> dict:
    """*described* with "the same name as that spell" turned into ``named``.

    CR 201.2a against the spell a cast trigger fired on. The fire site froze
    its **stack object** (``cast_item``), which is what says *which* spell — a
    deck repeats one ``CardDefinition`` per copy — and whose card is the half
    that was cast for a split card (CR 709.3b). Read off the frozen object
    rather than off the stack, because CR 608.2h gives a spell that has left
    the stack by now (countered in response) its last known name: it is then a
    card in a graveyard with that very name, and counts.

    Nothing frozen leaves the key where it is, and ``_card_matches_filter``
    answers no to it — a count of no card rather than of every card.
    """
    frozen = context.trigger_context or {}
    item = frozen.get("cast_item")
    card = getattr(item, "card", None) or frozen.get("cast_card")
    name = getattr(card, "name", None)
    if not name or described.get(NAMED_FROM_KEY) != "triggering_spell":
        return described
    resolved = dict(described)
    resolved.pop(NAMED_FROM_KEY, None)
    resolved["named"] = name
    return resolved


def _resolve_chosen_card_type(filt: dict, source) -> dict:
    """*filt* with "of that type" turned into the ordinary type keys.

    The sibling of :func:`_resolve_chosen_subtype` one half of the type line
    over. Same contract in both directions: a caller with no source, or a source
    that has not chosen, leaves the key in place and ``permanent_matches_filter``
    refuses every permanent — which for a sweep that phases out the board is the
    only safe direction.
    """
    if not filt.get(CHOSEN_CARD_TYPE):
        return filt
    word = getattr(source, "metadata", {}).get(CHOSEN_CARD_TYPE) if source else None
    resolved_keys = chosen_card_type_filter(word) if word else None
    if resolved_keys is None:
        return filt
    resolved = dict(filt)
    resolved.pop(CHOSEN_CARD_TYPE, None)
    resolved.update(resolved_keys)
    return resolved
