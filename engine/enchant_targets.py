"""What an Aura's "Enchant <subject>" line chooses (CR 702.5, CR 303.4a).

An Aura spell targets what its enchant keyword names (CR 303.4a, CR 115.1b),
and that line is the first evidence ``targeting.derive_cast_spec`` consults.
The subject is a **type** half and an optional **seat** half, composed rather
than listed (the note above :data:`_ENCHANT_LAND_SUBTYPES` says why), with a
negated noun, a colour and a "without <keyword>" exclusion read beside them.
:func:`enchant_line_subject` is the whole-line reader and
:func:`enchant_subject_spec` the picker the subject means. "Enchant creature
card in a graveyard" (Animate Dead) is not this: it chooses a card, and
:func:`enchant_graveyard_line` is how a reader tells the two apart.

One reading of the line for every reader of it — the cast picker, the cast
path's enchant gate (``mixins/stack/casting``), ``engine/auras.py`` and the
grammar's registry claim. Split out of ``engine/targeting.py`` at the
2,000-line cap; ``engine.targeting`` still exports the names its callers pull.
"""

from __future__ import annotations

import re

from .oracle_types import _COLOR_WORD_TO_SYMBOL
from .grammar.vocabulary import LAND_TYPES as _LAND_TYPES
from .subject_filters import unimplemented_filter_keywords


# "Enchant creature", "Enchant land", ... — but NOT "Enchant creature card in a
# graveyard" (Animate Dead), which targets a graveyard card rather than a
# permanent on the battlefield. The negative lookahead is load-bearing: without
# it Animate Dead derives "creature" and the UI would offer battlefield
# creatures for a reanimation spell.
# An "Enchant <subject>" clause is a **type** half and an optional **seat**
# half (CR 702.5's [quality]), and the two are independent: any of the five
# nouns can be printed with either seat clause. Spelling the combinations out
# as one flat alternation is what made "creature you control" have to be
# listed first — the alternation is first-match, so a plain "creature" would
# consume its prefix and leave " you control" to fail the whole-line anchor,
# which is a claim withdrawn rather than narrowed. Composing the halves
# instead means the tenth combination costs nothing, which is how "artifact an
# opponent controls" (Relic Bind — the only card in the pool printing it)
# arrived without a second entry.
#: A printed **land subtype** is one of these nouns, not a fifth composing
#: half: "Enchant Swamp" (Spreading Algae) names a different noun the way
#: "Enchant Wall" already does, rather than qualifying "land". Read out of
#: ``data/vocabulary/land_types.json`` rather than spelled here, for the reason
#: CLAUDE.md gives about every type list in this engine - and because the
#: matcher behind it (``has_type``, CR 613 layer 4) answers for every member
#: with one line, so the eighteenth subtype costs exactly what the first did.
#:
#: Longest first inside the alternation, which is first-match: a subtype that
#: is a prefix of another would otherwise consume it and leave the tail to fail
#: the whole-line anchor - the trap the seat clauses sprang once already (see
#: the note above about "creature you control").
_ENCHANT_LAND_SUBTYPES: tuple[str, ...] = tuple(
    sorted(_LAND_TYPES, key=len, reverse=True)
)
_ENCHANT_NOUNS = ("creature", "land", "artifact", "enchantment", "wall",
                  "permanent") + _ENCHANT_LAND_SUBTYPES
#: A printed **negated** noun ("Enchant non-Wall creature", Aggression). The
#: exclusion is enforced by `mixins/stack/casting.aura_enchant_noun`, which
#: reads the whole printed subject; what the picker needs from it is the head
#: noun, so the candidate list is the right *kind* and the gate then refuses
#: the excluded ones. Admitting the prefix here rather than a second noun per
#: exclusion keeps the two readers on one vocabulary.
_ENCHANT_NEGATION = r"(?:non-[a-z]+ )?"
#: "Enchant creature **without flying**" (Roots). CR 702.5's [quality] once
#: more, this time a keyword rather than a subtype, and a third *independent*
#: half of the clause — so it composes with the noun and the seat instead of
#: multiplying the rows, exactly as the negation above it does. The word is
#: payload: "Enchant creature without defender" is the same clause.
#:
#: Only the **negated** spelling. "Enchant creature with flying" refuses here
#: and leaves its card visibly unsupported, because no card in this pool prints
#: it and a filter with no card behind it is untested by construction
#: (ROADMAP.md's rule about the sacrifice trigger's narrowing). It is one
#: alternative to add beside this the day such a card arrives.
_ENCHANT_KEYWORD_EXCLUSION = r"(?: without [a-z]+)?"
_ENCHANT_SEAT_CLAUSES = {"you control": "you", "an opponent controls": "opponent"}
#: "Enchant **black** creature" (Decomposition), "Enchant **red or green**
#: creature" (Mind Harness), "Enchant **nonblack** creature" (Armor of Thorns).
#: CR 702.5's [quality] once more, and a *fourth* independent half of the
#: clause — so it composes with the noun, the seat and the keyword exclusion
#: instead of multiplying the rows, exactly as the two halves above it do.
#: The union and the negation are both printed and both read; a printed union
#: is an OR, which is how `any_colors` is already tested everywhere else.
_ENCHANT_COLOUR_WORDS = ("white", "blue", "black", "red", "green")
_ENCHANT_COLOUR = (
    rf"(?:(?:non)?(?:{'|'.join(_ENCHANT_COLOUR_WORDS)})"
    rf"(?: or (?:{'|'.join(_ENCHANT_COLOUR_WORDS)}))* )?"
)
#: "Enchant **artifact or creature**" (Teferi's Curse). A union of *nouns*, the
#: one half of the clause that cannot compose — the alternation above picks one
#: word — so it is spelled here as a second alternative rather than as a suffix
#: on the first. Two nouns is what the pool prints; a third would be another
#: repetition of the same group.
_ENCHANT_NOUN_UNION = (
    rf"(?:{'|'.join(_ENCHANT_NOUNS)})(?: or (?:{'|'.join(_ENCHANT_NOUNS)}))*"
)
_ENCHANT_SUBJECT = (
    rf"{_ENCHANT_COLOUR}"
    rf"{_ENCHANT_NEGATION}"
    rf"{_ENCHANT_NOUN_UNION}"
    rf"{_ENCHANT_KEYWORD_EXCLUSION}"
    rf"(?: (?:{'|'.join(_ENCHANT_SEAT_CLAUSES)}))?"
)
#: The colour half of a subject, split off the way the seat and keyword halves
#: are. Anchored at the start, because that is where the words are printed.
_ENCHANT_COLOUR_PREFIX = re.compile(
    rf"^(?P<colours>(?:non)?(?:{'|'.join(_ENCHANT_COLOUR_WORDS)})"
    rf"(?: or (?:{'|'.join(_ENCHANT_COLOUR_WORDS)}))*) (?P<noun>.+)$"
)


def enchant_subject_colours(subject: str) -> tuple[str, tuple[str, ...], bool]:
    """Split an enchant subject into its noun, its colours and whether they are
    **excluded**.

    ``"black creature"`` -> ``("creature", ("B",), False)``;
    ``"nonblack creature"`` -> ``("creature", ("B",), True)``;
    ``"red or green creature"`` -> ``("creature", ("R", "G"), False)``;
    a subject with no colour word -> ``(subject, (), False)``.

    The fourth half of CR 702.5's [quality] coming apart in one place, for the
    reason :func:`enchant_subject_seat` and
    :func:`enchant_subject_keyword_exclusion` each exist: the picker, the cast
    gate and the CR 704.5m sweep all need it, and three ``startswith`` tests
    between them is how they come to disagree about a card.

    A printed "non" applies to the whole run — no card prints a mixed one, and
    a mixed one would be ambiguous English rather than a shape to guess at.
    """
    match = _ENCHANT_COLOUR_PREFIX.match(subject)
    if match is None:
        return subject, (), False
    words = match.group("colours")
    excluded = words.startswith("non")
    symbols = tuple(
        _COLOR_WORD_TO_SYMBOL[word.removeprefix("non")]
        for word in words.split(" or ")
    )
    return match.group("noun"), symbols, excluded
#: The keyword half of a subject, split off the way the seat half is. Anchored
#: at the end so it is read after :func:`enchant_subject_seat` has taken the
#: seat clause off — "creature without flying you control" is not printed, but
#: splitting in that order means it would still come apart correctly.
_ENCHANT_WITHOUT = re.compile(r"^(?P<noun>.+?) without (?P<keyword>[a-z]+)$")
# Anchored at both ends, and read one printed line at a time. It used to be
# searched over the card's whole *normalized* text, which is space-joined - so
# Steal Artifact ("Enchant artifact" / "You control enchanted artifact") reads
# as one string in which "artifact you control" appears, and the clause gained
# a seat restriction the card never printed. The line structure is the only
# thing that says where the clause ends, so the reader keeps it.
_WHOLE_ENCHANT_LINE = re.compile(rf"^enchant ({_ENCHANT_SUBJECT})$")


def enchant_subject_seat(subject: str) -> tuple[str, str | None]:
    """Split an enchant subject into its noun and its seat requirement.

    ``"artifact an opponent controls"`` -> ``("artifact", "opponent")``; a bare
    noun -> ``(noun, None)``. The one place the two halves of the clause come
    apart, so the picker, the cast gate, the CR 704.5m sweep and the AI read
    one split rather than keeping four ``endswith`` tests between them.
    """
    for clause, seat in _ENCHANT_SEAT_CLAUSES.items():
        suffix = f" {clause}"
        if subject.endswith(suffix):
            return subject[: -len(suffix)].strip(), seat
    return subject, None


def enchant_subject_keyword_exclusion(subject: str) -> tuple[str, str | None]:
    """Split an enchant subject into its noun and the keyword it excludes.

    ``"creature without flying"`` -> ``("creature", "flying")``; a subject with
    no such clause -> ``(subject, None)``.

    The third half of CR 702.5's [quality], separated for exactly the reason
    :func:`enchant_subject_seat` separates the second: the picker, the cast
    gate, ``aura_attachment.aura_attach_refusal`` and the CR 704.5m sweep all
    need it, and four ``" without " in noun`` tests between them is four
    chances to read the clause differently. Ask for the seat first — this is
    anchored at the end of the string and a seat clause left on would swallow
    the keyword.
    """
    match = _ENCHANT_WITHOUT.match(subject)
    if match is None:
        return subject, None
    return match.group("noun").strip(), match.group("keyword")


# The graveyard form the scan above deliberately excludes. It is its own entry
# rather than a loosening of that pattern, because it names a different zone and
# so a different picker: `_apply_aura_effect` pops the chosen card out of
# `target_player.graveyard`, any player's, which is why `own_graveyard_only` is
# absent here and present on the spell-side reanimation below.
_ENCHANT_GRAVEYARD_LINE = re.compile(r"^enchant creature card in a graveyard\b", re.MULTILINE)

# Reminder text, stripped exactly as mixins/stack/casting.aura_enchant_noun
# strips it — "Enchant creature (Target a creature as you cast this. …)" is the
# same restriction as a bare "Enchant creature", and two consumers of one line
# must not read it differently.
_REMINDER_TEXT = re.compile(r"\([^)]*\)")


def enchant_line_subject(line: str) -> str | None:
    """What *line* attaches to, if the whole line is an ``Enchant <subject>``
    restriction (CR 702.5) — otherwise ``None``.

    The reader :func:`card_enchant_subject` runs over a card's printed
    lines, sharing its subject vocabulary so the two cannot drift. It exists so
    ``engine/grammar/registries.py`` can ask *this* module whether an Aura's
    attachment line is already accounted for, rather than copying the phrasing
    into the grammar where nothing would keep the copy honest.

    The trailing ``$`` is load-bearing: it keeps "Enchant creature card in a
    graveyard" (Animate Dead) out. Neither derivation here nor
    ``mixins/stack/casting.aura_enchant_noun`` implements that line — both
    deliberately refuse it, because it names a graveyard card rather than a
    battlefield permanent — so claiming it would report a reanimation Aura's
    attachment rule as handled while nothing handles it.

    A "without <keyword>" clause naming a keyword this engine does not
    implement is refused for the reason ``engine/combat_restrictions.py``
    refuses one: ``has_keyword`` answers no for a word nothing is registered
    under, so the exclusion would match **every** creature and the Aura would
    attach to anything while reporting the restriction implemented.
    """
    normalized = _REMINDER_TEXT.sub("", line).strip().lower().rstrip(".").strip()
    match = _WHOLE_ENCHANT_LINE.match(normalized)
    if match is None:
        return None
    subject = match.group(1)
    _noun, keyword = enchant_subject_keyword_exclusion(
        enchant_subject_seat(subject)[0]
    )
    if keyword is not None and unimplemented_filter_keywords(
        {"without_keywords": [keyword]}
    ):
        return None
    return subject


def enchant_clause_nouns(clause: str) -> tuple[str, ...]:
    """The permanent noun(s) an ``Enchant <subject>`` clause names.

    ``"red or green creature"`` -> ``("creature",)``;
    ``"artifact or creature"`` -> ``("artifact", "creature")``;
    ``"creature card in a graveyard"`` -> ``("creature card in a graveyard",)``,
    which the prefix test in :func:`engine.auras.aura_enchants` still reads as a
    creature — deliberately, because that reanimation clause is a creature Aura
    with a different picker rather than a different noun.

    The clause's four *qualities* (CR 702.5) taken off in the order they are
    printed, through the same three splitters the picker and the cast gate use.
    Written once here because widening the clause is what breaks its readers:
    Mirage added a colour half and a noun union, and `aura_enchants` — which
    asked ``clause.startswith(noun)`` — then answered no for "red or green
    creature" and *yes to the wrong branch* for "artifact or creature", so Mind
    Harness attached to nothing and Teferi's Curse looked for an artifact when
    it had enchanted a creature. Both reported supported.
    """
    noun = enchant_subject_seat(clause)[0]
    noun = enchant_subject_colours(noun)[0]
    if noun.startswith("non-"):
        noun = noun.split(" ", 1)[1] if " " in noun else noun
    return tuple(part.strip() for part in noun.split(" or "))


def enchant_graveyard_line(line: str) -> bool:
    """Whether one printed line is Animate Dead's "Enchant creature card in a
    graveyard".

    :func:`enchant_line_subject` deliberately refuses it — it names a card in a
    graveyard rather than a battlefield permanent, and so a different picker —
    but the engine *does* implement it: ``_cast_target_spec`` raises the
    graveyard picker and ``_apply_aura_effect`` spends the chosen index. So the
    Aura support gate needs to ask both readers, and this is the second one,
    read here rather than spelled again beside the gate.
    """
    normalized = _REMINDER_TEXT.sub("", line).strip().lower().rstrip(".").strip()
    return _ENCHANT_GRAVEYARD_LINE.match(normalized) is not None


def card_enchant_subject(oracle_text: str) -> str | None:
    """The "Enchant <subject>" clause *oracle_text* prints, or None.

    Per printed line, through the same :func:`enchant_line_subject` the grammar
    asks whether the line is claimed - so what the picker offers and what the
    parse-coverage gate calls accounted for are one reading. The line is
    *found*, not assumed to be the first: Capture Sphere prints "Flash" above
    it (see ``stack/casting.aura_enchant_noun``, which learned the same lesson).
    """
    for line in (oracle_text or "").splitlines():
        subject = enchant_line_subject(line)
        if subject is not None:
            return subject
    return None


_ENCHANT_NOUN_TO_SPEC: dict[str, dict] = {
    "creature": {"kind": "creature"},
    "wall": {"kind": "creature", "enchant_wall": True},
    "land": {"kind": "land"},
    "artifact": {"kind": "artifact"},
    "enchantment": {"kind": "permanent", "enchant_enchantment": True},
    # "Enchant permanent" (Faith's Fetters). The widest noun there is, so the
    # general picker with no narrowing at all - and the one enchant clause
    # whose spec needs no flag, because there is nothing to exclude.
    "permanent": {"kind": "permanent"},
    # "Enchant Swamp" (Spreading Algae). The land picker plus the subtype, in
    # exactly the shape ``enchant_wall`` above takes: the *kind* is what the
    # candidate list is built from and the flag is what narrows it, so the
    # hosts offered and the hosts ``permanent_matches_enchant_noun`` allows are
    # one reading. Both ends ask ``has_type`` (CR 613 layer 4), which is what
    # makes a Swamp turned into an Island by Phantasmal Terrain stop being a
    # legal host - and the CR 704.5m sweep then bins the Aura, exactly as it
    # already does for the keyword and colour halves.
    **{
        subtype: {"kind": "land", "enchant_land_type": subtype}
        for subtype in _ENCHANT_LAND_SUBTYPES
    },
}

# The seat half of the clause as the picker's own flag. It is a seat test, not
# a permanent test, which is why `_enumerate_targets` applies it rather than
# `permanent_matches_filter` — and the cast gate, the CR 704.5m sweep and the
# AI enforce the same half through `enchant_noun_seat`.
_ENCHANT_SEAT_TO_FLAG = {"you": "own_only", "opponent": "opponent_only"}


def enchant_subject_spec(subject: str) -> dict | None:
    """The cast-time target spec an "Enchant <subject>" clause describes.

    "Enchant creature you control" (Cocoon) and "Enchant artifact an opponent
    controls" (Relic Bind) are one noun spec plus one flag, so the
    combinations are composed here rather than enumerated.
    """
    noun, seat = enchant_subject_seat(subject)
    # "non-Wall creature" (Aggression) picks among *creatures*; the exclusion is
    # the cast gate's to enforce, and it reads the whole printed subject. A
    # picker narrowed to the head noun offers a superset and the gate refuses
    # the rest, which is the safe direction — the unsafe one would be offering
    # nothing, which is what this clause did before: no spec meant `kind: none`,
    # so the client sent no target and the engine refused the cast outright.
    if noun.startswith("non-"):
        noun = noun.split(" ", 1)[1] if " " in noun else noun
    # "creature **without flying**" (Roots). Unlike the negated subtype above,
    # this one *is* carried into the spec: `_enumerate_targets` can ask layer 6
    # for a keyword, so the picker offers exactly the legal hosts rather than a
    # superset. The gate enforces it as well, through
    # `permanent_matches_enchant_noun` and off the same split — the offered list
    # and the enforced rule are one reading, which is this clause's whole rule.
    noun, without_keyword = enchant_subject_keyword_exclusion(noun)
    # "Enchant **black** creature" / "**red or green** creature" / "**nonblack**
    # creature". Carried into the spec like the keyword exclusion above and for
    # the same reason: `_enumerate_targets` can read a permanent's colours, so
    # the picker offers exactly the legal hosts rather than a superset, and the
    # gate enforces it off this same split.
    noun, colours, colours_excluded = enchant_subject_colours(noun)
    # "Enchant **artifact or creature**" (Teferi's Curse). A union has no one
    # noun to key a spec on, so it takes the general permanent picker and the
    # gate narrows it — the safe direction, and the same one the negated-subtype
    # branch above takes.
    union = tuple(part.strip() for part in noun.split(" or ")) if " or " in noun else ()
    if union:
        if any(part not in _ENCHANT_NOUN_TO_SPEC for part in union):
            return None
        spec = {"kind": "permanent"}
    else:
        spec = _ENCHANT_NOUN_TO_SPEC.get(noun)
    if spec is None:
        return None
    spec = dict(spec)
    if colours:
        spec["exclude_colors" if colours_excluded else "any_colors"] = list(colours)
    if without_keyword is not None:
        spec["without_keyword"] = without_keyword
    flag = _ENCHANT_SEAT_TO_FLAG.get(seat)
    if flag is not None:
        spec[flag] = True
    return spec
