"""Targeting derived from the compiled program (CR 115, CR 602.2b).

`engine/legality.py` used to answer "what does this spell target?" by re-reading
the oracle text with ~40 substring predicates — a second parser of the same
text, which had to agree with the compiler forever or the UI would offer targets
the engine rejects. This module is its replacement: it reads the *compiled
program* the engine already built, so there is one parse and nothing to keep in
sync.

The answer is a whole spec, not just a kind. The kind decides which picker the
UI raises; the flags beside it decide what that picker offers — whose graveyard,
only the caster's creatures, a colour restriction on the stack. Deriving the
kind while leaving the flags to a text cascade would have left the second parser
alive for the interesting half, so both come from the same place.

Three kinds of evidence, in the order they are consulted:

1. **An Aura's ``Enchant <subject>`` line** names what it attaches to.
2. **A copy-on-enter phrase** (``engine/enter_effects.py``) means the caster
   chooses something to copy as the permanent arrives — a choice, not a target
   (CR 707.9a), but the same picker.
3. **The instructions themselves** — the kind, its ``targets`` description, or
   its ``type_filter`` payload.

:func:`derive_cast_spec` returns None when a card carries none of that, which
means "this spell chooses nothing as it is cast". Every supported card in the
pool now answers, and `tests/engine/test_targeting.py` fails if one that
mentions a target stops doing so — a parser change cannot quietly take the
evidence away.

**Activated abilities ask the same question one level down.** A spell picks its
targets once, as it is cast; an ability picks them each time it is activated,
and one card may carry several abilities that target differently (Pyramids
destroys an Aura or shields a land). So :func:`derive_activation_spec` takes an
*ability*, not a card, and runs the same instruction evidence over that
ability's own instruction — the tables below are shared, because what an
instruction kind targets does not depend on whether a spell or an ability
produced it. `legality.py` classified activation from text until this existed;
`tests/engine/test_activation_targeting.py` holds the replacement in place.
"""

from __future__ import annotations

import re

from .cast_costs import additional_costs
from .divided_damage import CHOSEN, DIVIDED_TARGETS, divided_entry
from .enter_effects import copy_on_enter_type
from .oracle_types import _COLOR_WORD_TO_SYMBOL
from .subject_filters import filter_head_noun, unimplemented_filter_keywords

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
_ENCHANT_NOUNS = ("creature", "land", "artifact", "enchantment", "wall",
                  "permanent")
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
    gate, ``auras.aura_attach_refusal`` and the CR 704.5m sweep all need it, and
    four ``" without " in noun`` tests between them is four chances to read the
    clause differently. Ask for the seat first — this is anchored at the end of
    the string and a seat clause left on would swallow the keyword.
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


# An instruction's type_filter, as a target kind. Filters naming more than one
# type fall back to the general permanent picker, which then applies the filter.
_TYPE_FILTER_TO_KIND = {
    "artifact": "artifact",
    "creature": "creature",
    "land": "land",
    "enchantment": "permanent",
    "permanent": "permanent",
    "artifact_or_enchantment": "permanent",
    # "…deals 1 damage to target planeswalker." (Sparkhunter Masticore.) Its own
    # picker rather than the general permanent one: a planeswalker is the only
    # permanent type a printed phrase names this often *without* also admitting
    # creatures, and offering every permanent would be a prompt the resolution
    # then refuses.
    "planeswalker": "planeswalker",
}


def _kind_for_type_filter(type_filter) -> str | None:
    """*type_filter* as a target kind, or None when nothing describes it.

    A filter may name a *union* of types — Icy Manipulator's "target artifact,
    creature, or land" lowers to ``["artifact", "creature", "land"]``. No single
    picker matches a union, so it takes the general permanent picker and
    ``permanent_matches_filter`` narrows it back down at enumeration time, the
    same way it does at resolution.
    """
    if isinstance(type_filter, (list, tuple)):
        return "permanent"
    return _TYPE_FILTER_TO_KIND.get(type_filter)


#: The instruction kinds whose ``type_filter`` describes **the object the
#: caster picks**, rather than the class the effect sweeps.
#:
#: The third kind-keyed evidence table in this module, beside
#: :data:`_KIND_TO_SPEC_FROM_PAYLOAD` and :data:`_KIND_TO_SPEC`, and it exists
#: because ``type_filter`` is the one payload key that means two different
#: things. "Destroy target permanent" and "destroy all black creatures" both
#: carry ``{"type_filter": "creature"}``: on the first it is the target
#: description (CR 115.1a's "target [something]"), on the second it is the
#: class the sweep affects, and the payload alone cannot tell them apart.
#:
#: :func:`_from_instruction` used to read the key on *any* kind, which is this
#: module's one guess — the thing its docstring says it does not do. Six mass
#: spells (Cleanse, Jokulhaups, Tivadar's Crusade, Riptide, Battle Cry, Reset)
#: and five more whose sweep sits on a trigger reported a target they never
#: choose, and the client refused to cast four of them at all: its picker
#: aborts a cast when the candidate list comes back empty, so "Destroy all
#: black creatures" was uncastable on a board with no creatures. Wrath of God
#: was the accidental control — "destroy all creatures" has a kind of its own
#: (``destroy_all_creatures``) with the class baked into the *name* and so no
#: filter for the reader to misread.
#:
#: One entry today, and that is the measurement rather than an oversight: every
#: other targeted line in the pool carries the lowering's own ``targets``
#: description, which is deliberate evidence and is read first. A kind that
#: needs to be here and is not answers None, and the ratchet in
#: `tests/engine/test_targeting.py` fails on the card that targets and derives
#: no prompt — the loud direction. A sweep needs no entry at all, so the defect
#: cannot come back by omission.
_TYPE_FILTER_NAMES_THE_TARGET = frozenset({
    # "Destroy target permanent", narrowed by a printed noun the lowering
    # carries as payload rather than as a `targets` description
    # (`lowering/destruction.py`). Hooded Blightfang's "destroy that
    # planeswalker" is the pool's only one; the same kind's ordinary printed
    # forms describe their target and never reach here.
    "destroy_target_permanent",
})


def _spec_from_type_filter(payload: dict) -> dict | None:
    """The picker *payload*'s ``type_filter`` describes, or None for none.

    Only reached for a kind :data:`_TYPE_FILTER_NAMES_THE_TARGET` lists. A
    filter no picker matches answers None rather than short-circuiting the
    whole derivation, so the kind's own :data:`_KIND_TO_SPEC` row still gets
    its say.
    """
    type_filter = payload.get("type_filter")
    if not type_filter:
        return None
    kind = _kind_for_type_filter(type_filter)
    if kind is None:
        return None
    return {"kind": kind, **_narrowing_flags(payload)}


def _narrowing_flags(source: dict) -> dict:
    """The picker-narrowing flags *source* (a filter or a payload) carries.

    These are the restrictions the enumerator itself applies
    (`_permanent_matches_target_kind`), as opposed to the ones it delegates to
    the instruction's own filter through `_ability_target_legal`. Both are read
    from the same compiled payload; only the vocabulary differs.
    """
    flags: dict = {}
    # `blocked_only` joined the three when General Jarkeld printed "two target
    # **blocked** attacking creatures". Left out, the word parsed, rode the
    # instruction's own filter to resolution and was dropped by the picker: the
    # ability could be activated naming an unblocked attacker, which is the
    # wider-than-printed reading CR 602.2b exists to refuse before anything is
    # paid. `unblocked_attacker` beside it in the enumerator is Forcefield's
    # spelling of the other half.
    for key in ("attacking_only", "blocked_only", "blocking_only", "flying_only"):
        if source.get(key):
            flags[key] = True
    # Carried by value, not flattened to a flag: "attacking or blocking" and
    # "tapped or blocking" are the same key with different words in it, and a
    # bare True would tell the picker a union applies without saying which one.
    any_states = source.get("any_states")
    if any_states:
        flags["any_states"] = list(any_states)
    if source.get("subtype_filter") == "wall":
        # The picker's name for a Wall subtype filter (Ali Baba, Dwarven
        # Demolition Team). Kept as a flag rather than left to the instruction
        # filter so a Wall-only prompt reads the same whether the narrowing
        # came from the ability's payload or from an Aura's "Enchant Wall".
        flags["wall_only"] = True
    color = source.get("color_filter")
    if color:
        flags["color_filter"] = color
    if source.get("controller") == "you":
        # "target creature you control". The enumerator applies this one itself
        # (it is a seat test, not a permanent test), and it has to: a picker
        # that offered an opponent's creature would let a player choose a target
        # the effect then declines to affect, with nothing on screen saying why.
        flags["own_only"] = True
    elif source.get("controller") == "opponent":
        # "target artifact **an opponent controls**" (Hyperion Blacksmith). The
        # mirror of `own_only` and a seat test for the same reason, so it is the
        # picker's job rather than the permanent matcher's. Without it the
        # narrowing had nowhere to go: `permanent_matches_filter` cannot answer
        # a controller, so the lowering refused the line outright rather than
        # let a "an opponent controls" ability untap the activator's own
        # artifact — a restriction dropped in the player's favour.
        flags["opponent_only"] = True
    elif source.get("controller") == "defending_player":
        # "target artifact **defending player controls**" (Floral Spuzzem).
        # The third seat test, and the one the enumerator cannot answer on its
        # own: "you" and "opponent" are relative to the seat choosing, while
        # this one is relative to the *combat* the ability's trigger fired in.
        # So the flag says the narrowing exists and the caller that knows the
        # attack — the trigger's announcement — supplies the seat beside it.
        # With no seat supplied the enumerator offers nothing, which is the
        # safe direction: an unanswerable narrowing must never widen to "any".
        flags["defending_player_only"] = True
    elif source.get("controller") == "that_player":
        # "up to two target creatures **that player** controls" (Fatal Lore).
        # The fourth seat test, and `defending_player_only`'s exact shape one
        # record over: the seat is not relative to whoever is choosing but to
        # something the *announcement* froze — there, the combat; here,
        # CR 700.2e's mode choice. Two flags rather than one because they are
        # two printed phrases reading two different records, and a caller that
        # can supply one usually cannot supply the other.
        #
        # With no seat beside it the enumerator offers nothing, for that flag's
        # stated reason: an unanswerable narrowing must never widen to "any",
        # and this one widens to *every creature in the game*.
        flags["that_player_only"] = True
    if source.get("enchanted_only"):
        # "destroy target **enchanted** creature" (Ramses Overdark) — the
        # positive twin of ``not_enchanted`` below, and a picker flag for the
        # same reason: the enumerator narrows with the same matcher the handler
        # re-asks at resolution, so what is offered and what is destroyed cannot
        # disagree.
        flags["enchanted_only"] = True
    if source.get("not_enchanted"):
        # "target permanent **that isn't enchanted**" (Time Elemental) —
        # CR 303.4a. A picker flag rather than a restriction left to the
        # handler, and for the reason ``own_only`` above gives: the handler
        # already refuses an enchanted permanent at resolution, so a picker that
        # offered one would let a player tap the Elemental and pay {2}{U}{U} for
        # a bounce that then returns nothing, with nothing on screen saying why.
        flags["not_enchanted"] = True
    if source.get("exclude_self"):
        # "up to two **other** target creatures you control" (Basri's Acolyte),
        # "**another** target creature" as a fight's opponent (Brash Taunter).
        # Same argument as `own_only` directly above, and it had the same gap in
        # the other direction: every handler carrying this key already refuses
        # the source at resolution (pump.py, zones.py, damage.py), so a picker
        # that omitted it offered a target the effect then declined to affect.
        # `legality.py` has honoured `exclude_source` all along — nothing read
        # the filter key into it.
        flags["exclude_source"] = True
    if source.get("exclude_attached"):
        # "…to **another** target creature" on an Aura (Farrel's Mantle). The
        # same word about a different object: the creature dealing the damage
        # is the one the Aura is attached to, so the picker excludes the host
        # rather than the source. A flag of its own because the two exclude
        # different permanents, and the Aura was never on the list anyway.
        flags["exclude_attached"] = True
    if source.get("blocked_by_source"):
        # "target creature **it's blocking**" (Goblin Snowman, Tinder Wall).
        # A relation to the ability's own source, so the enumerator applies it —
        # it holds the source, and ``permanent_matches_filter`` could not answer
        # it from the candidate alone. Without the flag the picker offered every
        # creature on the board for a ping the card aims at exactly one.
        flags["blocked_by_source"] = True
    if source.get("blocking_source"):
        # "target creature **blocking this creature**" (Barbed-Back Wurm). The
        # mirror of the flag above and the enumerator's for its reason exactly:
        # the relation is to the ability's own source, which the loop holds and
        # the candidate alone cannot answer. Without the flag the picker offers
        # every creature on the board for an ability aimed at the ones in front
        # of it.
        flags["blocking_source"] = True
    if source.get("attacking_you"):
        # "target creature **that's attacking you**" (Ice Floe, Snow Fortress).
        # A seat test like ``own_only`` — which player the creature was declared
        # against — and the enumerator's for the same reason: the seat choosing
        # is the one it is relative to.
        flags["attacking_you"] = True
    if source.get("attacked_you_this_turn"):
        # "target … creature **that attacked you this turn**" (Jabari's
        # Influence). The record behind the flag above, and carried for its
        # reason exactly: the seat choosing is the one it is relative to, and
        # a picker without it offers every creature on the board.
        flags["attacked_you_this_turn"] = True
    # A printed subtype or supertype narrowing, carried whole under ``filter``
    # — the spec form `spec_only_subtype` already reads and the enumerator
    # already applies through ``subject_matches`` (legality's own loop), so the
    # picker offers exactly what resolves. "X target **Mountains**" (Volcanic
    # Eruption) and "X target **snow** lands" (Avalanche) both rode only the
    # instruction's payload before this, which the per-candidate cast probe
    # does not ask for a several-target description — so the picker offered a
    # Forest for a spell that destroys Mountains. A Wall stays on ``wall_only``
    # above, its established spelling, rather than being said twice.
    narrowed: dict = {}
    subtype = source.get("subtype_filter")
    if isinstance(subtype, str) and subtype != "wall":
        narrowed["subtype_filter"] = subtype
    supertypes = source.get("supertypes")
    if supertypes:
        narrowed["supertypes"] = list(supertypes)
    # The negations travel with them. "Target **nonsnow** basic land" (Arcum's
    # Weathervane) is one description, and carrying the "basic" while dropping
    # the "nonsnow" offers a superset — the picker would list the snow lands
    # the ability then refuses. Both keys are in
    # ``TESTABLE_SUBJECT_FILTER_KEYS``, so the enumeration can ask them; a
    # narrowing the matcher could not test would have to stay off the spec
    # rather than ride it unenforced.
    for key in ("exclude_supertypes", "exclude_subtypes"):
        excluded = source.get(key)
        if excluded:
            narrowed[key] = list(excluded)
    if narrowed:
        flags["filter"] = narrowed
    return flags


# Instruction kinds whose whole spec is fixed by the kind itself. A lace always
# targets a spell or permanent; a graveyard-return always targets a card in a
# graveyard. `legality.py` used to read that off the card's *text*; the compiled
# program already carries it in the kind.
#
# The flags beside a kind describe the same thing the kind's *handler* does, so
# they are read off the handler rather than off the card. `reanimate_creature`
# is the worked example and also the caveat: its handler reads the caster's own
# graveyard *unless* the payload says `any_graveyard`, in which case it reads
# the graveyard of the seat the caster named. So `own_graveyard_only` belongs to
# the kind **and its payload** — never to whether the words "your graveyard"
# happen to appear, which would be the text cascade this module replaced.
#
# One table, consulted by the cast side and the activation side alike: what an
# instruction targets is a property of the instruction, not of whether a spell
# or an ability produced it. `grant_target_flying_until_eot` is Jump when a
# spell carries it and Flying Carpet's ability when a permanent does, and both
# want the same creature picker.
_KIND_TO_SPEC: dict[str, dict] = {
    "recolor_target_from_text": {"kind": "spell_or_permanent"},
    # Unsubstantiate: a spell on the stack or a creature on the battlefield —
    # the recolor picker's zones, narrowed to creatures on the permanent half.
    "return_spell_or_creature_to_hand": {
        "kind": "spell_or_permanent", "permanent_kind": "creature",
    },
    # Epitaph Golem: any card in the activator's own graveyard.
    "put_graveyard_card_on_library_bottom": {
        "kind": "graveyard_creature", "own_graveyard_only": True, "any_card": True,
    },
    "mark_text_modified": {"kind": "permanent"},
    "counter_top_stack_spell": {"kind": "stack"},
    "berserk_pump": {"kind": "creature"},
    # "Target creature **defending player controls** can block any number of
    # creatures this turn." (Blaze of Glory.) The seat was missing from this
    # row and enforced nowhere else, so the spell granted the permission to the
    # *caster's* own creature — a printed restriction that reached the picker,
    # the cast gate and the handler as nothing at all. It is a spec key rather
    # than a branch because `legality._enumerate_targets` already answers the
    # flag, and answers it for a spell now: the seat is the live combat's.
    "grant_unlimited_blocking": {"kind": "creature", "defending_player_only": True},
    "target_gains_life": {"kind": "any"},
    "remove_creature_from_combat": {"kind": "creature"},
    "grant_target_flying_until_eot": {"kind": "creature"},
    "simulacrum_redirect": {"kind": "creature"},
    "exile_creature_gain_life_equal_to_power": {"kind": "creature"},
    "bounce_target_creature": {"kind": "creature"},
    "phase_out_target_creature_until_source_leaves": {"kind": "creature"},
    "exchange_ante_with_top_library": {"kind": "none"},
    # Dream Coat: "Enchanted creature becomes the color or colors of your
    # choice." The *permanent* is not chosen — an Aura's ability acts on its
    # own host (CR 303.4) — so there is no target picker; what the activator
    # chooses is a colour, which rides `mana_color` like every other CR 609.3
    # choice. A positive "nothing to point at", not an absent derivation:
    # without the row the ability answered None and the guard could not tell
    # the two apart.
    "recolor_enchanted_chosen_color": {"kind": "none"},
    # Shyft: the same positive "nothing to point at" — the sentence names
    # the source itself, so no picker is offered and none is missing.
    "recolor_self_chosen_color": {"kind": "none"},
    "tap_or_untap_target": {"kind": "permanent"},
    "drain_target_lands_mana": {"kind": "player"},
    "tap_target_player_lands_and_drain_mana": {"kind": "player"},
    "reorder_target_library_top": {"kind": "player"},
    # "…can be the target of spells and abilities controlled by **target
    # player** as though it didn't have shroud" (Autumn Willow). The ability
    # targets a *player* while the creature carrying it cannot be targeted at
    # all, which is legal and is the whole card: CR 702.18 stops spells and
    # abilities from choosing the permanent, and says nothing about what the
    # permanent's own abilities may choose.
    "waive_shroud_for_target_player": {"kind": "player"},
    "return_all_owned_artifacts_to_hand": {"kind": "player"},
    # Word of Command looks at *target opponent's* hand: the caster's own seat is
    # not a legal choice (CR 115.4).
    "peek_hand_and_force_play": {"kind": "player", "opponents_only": True},
    # Fork copies the chosen spell and lets the caster choose new targets for the
    # copy, so the UI runs a second prompt rather than sending the cast at once.
    "copy_top_stack_spell": {
        "kind": "stack",
        "copies_spell": True,
        "stack_instant_sorcery_only": True,
    },
    # "The next time a source of your choice would deal damage to you this turn":
    # the source may be a permanent on any battlefield or a spell on the stack,
    # which `also_stack` folds into one prompt. The engine matches the chosen
    # source by identity, so no colour filter narrows it.
    "grant_reverse_damage_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Bone Mask prints the same seven words and so runs the same prompt; what
    # its shield does after absorbing is the interceptor's business, not the
    # picker's.
    "grant_exile_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Shadowbane prints the same seven words again; what its shield then covers
    # is the interceptor's business, not the picker's.
    "grant_team_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    "arm_mirror_damage": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Dark Sphere prints the same phrase and so runs the same prompt — a
    # permanent on any battlefield or a spell on the stack. What its shield then
    # does with the chosen source is the handler's business, not the picker's.
    "grant_half_prevention_shield": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # Nova Pentacle: "The next time **a source of your choice** would deal damage
    # to you this turn…". The same prompt those two run — a permanent on any
    # battlefield or a spell on the stack — because it is the same printed
    # phrase. The creature that takes the redirected damage is *not* here: an
    # opponent picks it (CR 601.2c's chooser is not always the controller), so
    # it is a prompt the resolution arms rather than one this picker runs.
    # Reflect Damage prints the same seven words a third time — the source may
    # be a permanent on any battlefield or a spell on the stack. It names no
    # recipient at all, which changes what the *record* watches and nothing
    # about what the caster is asked for.
    "redirect_damage_from_chosen_source_until_eot": {
        "kind": "permanent", "source_of_choice": True, "also_stack": True,
    },
    # "As an additional cost to cast this spell, sacrifice a creature" used to
    # be keyed here, by the instruction Sacrifice and Metamorphosis compile to.
    # It is a *cost*, so `derive_cast_spec` now reads it off `cast_costs` and
    # every card printing the phrase gets the picker — Village Rites and
    # Goremand buy nothing with it and were being offered no choice at all.
    # --- kinds that reach the picker through an activated ability -----------
    #
    # Each of these resolves through `resolve_target_permanent(game, context)` with
    # the default predicate — `p.is_creature` — so "creature" is what the code
    # that runs the ability accepts, not what the printed line says.
    "grant_banding_to_target": {"kind": "creature"},
    "grant_target_keyword_until_eot": {"kind": "creature"},
    "grant_target_ability_text": {"kind": "creature"},
    "add_named_counter_to_target": {"kind": "creature"},
    "grant_flying_and_delayed_destruction": {"kind": "creature"},
    "grant_unblockable_to_target": {"kind": "creature"},
    "steal_creature_while_tapped_and_weaker": {"kind": "creature"},
    "deny_regeneration_to_target": {"kind": "creature"},
    "pump_target_creature_until_eot": {"kind": "creature"},
    "grant_regeneration_to_target_creature": {"kind": "creature"},
    "mark_non_wall_target_to_attack": {"kind": "creature"},

    # Effects that act on a *player*: the handler reads `context.target`,
    # a seat, and never looks at the battlefield. ``mill_target_player`` is not
    # among them — it names its recipient in the payload, so it is read by
    # ``_player_recipient_spec`` rather than answered flat.
    "look_at_target_hand": {"kind": "player"},
    "look_at_target_library_top": {"kind": "player"},
    "discard_target_cards": {"kind": "player"},
    # "Search **target opponent's** graveyard, hand, and library …"
    # (Necromentia). The searched player is a target chosen as the spell is cast
    # (CR 601.2c); the *card name* is chosen on resolution and is not a target at
    # all, which is why the kind is a plain player rather than something
    # card-shaped.
    "name_and_strip": {"kind": "player"},
    "name_then_reveal_top": {"kind": "player"},
    # ``target_loses_life`` is **not** here. Like its twin above it spells the
    # recipient in the payload, so it reads it — see ``_player_recipient_spec``.
    # "Exchange life totals with target opponent." (Mirror Universe.) The other
    # seat is a target chosen as the ability is activated (CR 602.2b); the
    # controller's own half is not chosen at all.
    "exchange_life_totals": {"kind": "player"},
    # Cuombajj Witches. Its handler delegates the controller's half to
    # `deal_damage`, which takes a player or a permanent; the opponent's half is
    # a pending choice made after resolution, not a target chosen here.
    "deal_damage_and_opponent_choice": {"kind": "any"},
    # Gaea's Liege and Pyramids' second mode: both resolve through a
    # `primary_type == "land"` predicate.
    "change_target_land_type": {"kind": "land"},
    "shield_target_land_from_destruction": {"kind": "land"},
    # Cyclopean Tomb's handler refuses a Swamp outright
    # (`primary_type == "land" and not _is_swamp(p)`), so the exclusion belongs
    # to the kind rather than to the words "non-Swamp" appearing on the card.
    "add_mire_counter_to_target_land": {"kind": "land", "exclude_swamp": True},
    # Forcefield: "an unblocked creature of your choice would deal combat damage
    # to you" — the controller picks one of the attackers that got through.
    "grant_forcefield_shield": {"kind": "creature", "unblocked_attacker": True},
    # Jade Monolith picks twice: the creature it shields, and the damage source
    # whose damage is redirected. `requires_source` is what tells the UI to run
    # the second prompt.
    "jade_monolith_redirect": {"kind": "creature", "requires_source": True},
}


def _cost_picker_spec(cost) -> dict | None:
    """The picker a choosable cost needs, or None when the cost chooses nothing.

    Shared by the cast and activation sides because the *choice* is the same on
    both — CR 601.2b and CR 602.2b are the same announcement step — and only
    what is withheld from the list differs. ``sacrifice_cost`` / ``discard_cost``
    are what tell the client which field carries the answer and to say
    "sacrifice" rather than "target"; the payment is not a target, and a card
    can have both.

    The sacrifice's head noun is the kind, rather than a fixed "creature": Atog
    eats an artifact, and a picker offering creatures for it would offer nothing
    it could pay with. Anything the noun phrase says *beyond* its head noun rides
    along as ``filter`` — "a creature with defender" (Portcullis Vine) is a
    creature picker over a narrowed list, and the enumerator applies the
    narrowing with the same matcher the charger does, so what is offered and
    what is accepted cannot disagree.
    """
    if cost is None:
        return None
    if getattr(cost, "discard_cards", 0):
        spec = {
            "kind": "hand_card",
            "own_only": True,
            "discard_cost": True,
            "count": cost.discard_cards,
        }
        # "Discard a **land card or Shrine card**" (Sanctum of Shattered
        # Heights) — the printed alternatives ride along so the enumerator
        # narrows the offered hand with the same reader the charger accepts by.
        # Emitted only when there is a narrowing: an empty key would read as one
        # to anything that tests for its presence.
        alternatives = getattr(cost, "discard_filters", ()) or ()
        if alternatives:
            spec["filters"] = [dict(alt) for alt in alternatives]
        return spec
    described = getattr(cost, "exile_filter", None)
    if described is not None:
        # "Exile a creature you control" (City of Shadows) / "Exile a creature
        # card from your graveyard" (Necropolis). The sacrifice picker one zone
        # over: the *choice* is the same announcement (CR 601.2b), and only the
        # list it is made from differs. ``exile_cost`` is what tells the client
        # to send the answer on the cost field and to say "exile" rather than
        # "target" — a cost is not a target (idiom 10).
        if getattr(cost, "exile_zone", "battlefield") == "graveyard":
            spec = {
                "kind": GRAVEYARD_TARGET_KIND,
                "exile_cost": True,
            }
            # Whose pile the payer may reach into. "from **your** graveyard"
            # (Necropolis) is one seat; "from a single graveyard" (Night Soil)
            # is anybody's, and the charger really does enumerate every seat —
            # so a picker that said "your own" here would offer less than the
            # cost accepts, which is the picker/charger disagreement this file
            # exists to prevent, in the direction that hides a legal payment.
            if getattr(cost, "exile_zone_owner", "you") == "you":
                spec["own_graveyard_only"] = True
            wanted = described.get("type_filter")
            if isinstance(wanted, str):
                spec["card_type"] = wanted
            # How many the payer names. Emitted only when the printed count is
            # more than one, so every spec written before a counted cost existed
            # stays byte-identical.
            count = int(getattr(cost, "exile_count", 1) or 1)
            if count > 1:
                spec["count"] = count
            # "…from **a single** graveyard": all of them out of the same pile,
            # which is a restriction on the *set* rather than on any one card
            # and so cannot ride the filter.
            if getattr(cost, "exile_same_zone", False):
                spec["same_zone"] = True
            return spec
        spec = {
            "kind": filter_head_noun(described),
            "own_only": True,
            "exile_cost": True,
        }
        if described.get("exclude_self"):
            spec["exclude_source"] = True
        narrowing = {
            key: value
            for key, value in described.items()
            if key not in ("exclude_self", "controller")
            and not (key == "type_filter" and isinstance(value, str))
        }
        if narrowing:
            spec["filter"] = narrowing
        return spec
    described = getattr(cost, "sacrifice_filter", None)
    if described is not None:
        spec = {
            "kind": filter_head_noun(described),
            "own_only": True,
            "sacrifice_cost": True,
        }
        # "Sacrifice **another** creature" (Hobblefiend): the source is not a
        # legal payment, so a lone Hobblefiend can offer nothing and cannot
        # activate at all — which the payment path already enforces. It is
        # lifted out of the carried filter rather than left in it, because the
        # enumerator excludes by identity and a key nothing reads is a key
        # silently dropped.
        if described.get("exclude_self"):
            spec["exclude_source"] = True
        # "Sacrifice **two** Goblins" (Goblin Warrens): how many the payer
        # names. Emitted only above one, so every spec written before a counted
        # sacrifice existed is unchanged — and "any" stays off it, because that
        # cost already travels on ``cost_permanent_ids`` and has no fixed size.
        sacrifice_count = getattr(cost, "sacrifice_count", 1)
        if isinstance(sacrifice_count, int) and sacrifice_count > 1:
            spec["count"] = sacrifice_count
        # `kind` already *is* the head noun, so re-stating it in the carried
        # filter would be the same restriction written twice. A type *union* has
        # no head noun (`kind` falls back to "permanent"), so it rides along.
        narrowing = {
            key: value
            for key, value in described.items()
            # ``own_only`` above already *is* "you control", so carrying the
            # seat again would be the same restriction written twice — and the
            # second copy would reach an enumerator with no observer, which
            # refuses every candidate rather than narrowing anything.
            if key not in ("exclude_self", "controller")
            and not (key == "type_filter" and isinstance(value, str))
        }
        if narrowing:
            spec["filter"] = narrowing
        return spec
    return None


def _life_gain_spec(payload: dict) -> dict | None:
    """Who gains the life is what decides whether anything is chosen at all.

    "Target player gains 3 life" picks a player; "you gain 3 life" picks
    nothing, and **37 of the pool's 39 life gains are the second one**. One
    instruction kind serves both because only the amount and the recipient
    differ, so the kind alone could not tell them apart — and answering "any
    target" for all of them put a picker in front of spells that target nothing
    (Revitalize, Witch's Cauldron's ability). Whatever the player clicked was
    sent as a target the handler then ignored, so the prompt was not merely
    spurious: it was a question whose answer went nowhere.

    An unrecognised recipient answers None, which is the safe direction: no
    prompt in front of an effect that chooses nothing, rather than a prompt
    whose answer is discarded.

    Reading the payload here means this entry has to answer the *whole*
    question, including the half it did not come to change: a payload-keyed spec
    is authoritative in ``_from_instruction``, so returning a bare "any" for the
    targeting case would have overridden the grammar's own targets description
    and coarsened Healing Salve and Stream of Life from "target player" to
    "any target".
    """
    if payload.get("recipient") != "target":
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


#: The ``recipient`` values that mean "whoever this instruction targets".
#:
#: An **absent** key is one of them: a lowering that names no recipient is
#: spelling its kind's default, and for every "target <player> …" kind that
#: default is the target. Every other value names a seat the printed sentence
#: already fixed — the caster, each opponent, each player, the seat some
#: earlier event picked — and a fixed recipient is chosen by nobody
#: (CR 115.1a: a spell is targeted only where its ability says "target").
_CHOSEN_RECIPIENTS = frozenset({None, "target"})


def _player_recipient_spec(payload: dict) -> dict | None:
    """A seat-affecting instruction's picker, or None when the seat is fixed.

    :func:`_life_gain_spec` directly above is the same reading, written for the
    kind that needed it first; these are its twins, and they were flat
    ``{"kind": "player"}`` rows until this round — so the whole question the
    docstring above answers ("who gains the life is what decides whether
    anything is chosen at all") was never asked of who *loses* it.

    Twelve cards paid for that. "Each player loses 2 life" (Bad Deal, Pox),
    "you lose 3 life" (Grim Tutor) and "each opponent loses 2 life" (Caged
    Zombie's ability) each raised a player picker in front of an effect that
    chooses nobody, and whatever seat was clicked was sent as a target the
    handler then ignored. Carrion Grub is the same shape one kind over: an
    enters-the-battlefield mill of *its own controller's* library, which asked
    a creature spell's caster to pick a player.
    """
    if payload.get("recipient") not in _CHOSEN_RECIPIENTS:
        return None
    return _from_targets_payload(payload.get("targets")) or {"kind": "player"}


def _look_top_pick_spec(payload: dict) -> dict | None:
    """The seat this look-top pick chooses, or None for the cards choosing none.

    Two payload keys name a chosen seat, and they are the family's two printed
    shapes:

    * ``looker`` — "**Target player** looks at the top three cards of their
      library" (Ashnod's Cylix): one seat answers both questions, chosen as the
      ability is activated (CR 602.2b);
    * ``pile_owner`` — "Look at the top X cards of **target opponent's**
      library" (Sealed Fate): the pile is the chosen player's and every decision
      about it is the caster's.

    "Look at the top five cards of **your** library" (Browse, See the Truth,
    Diabolic Vision) chooses nobody, and raising a player picker in front of one
    of those would ask its controller to name a target the handler ignores — the
    twelve-card mistake ``_player_recipient_spec`` above records, which is why
    this is derived from the payload rather than declared flat for the kind.

    The ``pile_owner`` half reads the lowering's own ``targets`` description
    rather than restating it, because the narrowing is part of the answer:
    "target opponent" may not choose the caster (CR 115.4) and "target player"
    may. Restating it was never the bug, though. The bug is that this function
    is registered in ``_KIND_TO_SPEC_FROM_PAYLOAD``, which **pre-empts** the
    generic ``targets`` reading in :func:`_from_instruction` — so answering None
    for a payload carrying a real description threw that description away.
    Sealed Fate derived no picker at all, the client sent a bare cast, and the
    handler logged "no player chosen" and looked at nothing.
    """
    if payload.get("looker") == "target_player":
        return {"kind": "player"}
    if payload.get("pile_owner") is not None:
        return _from_targets_payload(payload.get("targets"))
    return None


def _counter_spec(payload: dict) -> dict:
    """A counterspell, narrowed to the colour its payload names.

    The Elemental Blasts counter one colour and Counterspell counters any, which
    is one kind with different data — exactly why the colour is payload rather
    than part of the kind.
    """
    spec: dict = {"kind": "stack"}
    color = payload.get("color_filter")
    if color:
        spec["stack_color_filter"] = color
    any_colors = payload.get("any_colors")
    if any_colors:
        # "target **red or green** spell" (Tidal Control) — the colour union,
        # handed to the picker under the key the stack enumeration already
        # reads for Circle of Protection, so the offer and the counter cannot
        # name different sets.
        spec["stack_any_colors"] = list(any_colors)
    card_types = payload.get("card_types")
    if card_types:
        # Miscast: "target instant or sorcery spell" — the same union the
        # handler tests at resolution, so the picker offers exactly what the
        # counter would counter.
        spec["stack_card_types"] = list(card_types)
    any_classes = payload.get("any_classes")
    if any_classes:
        # "target instant or Aura spell" (Avoid Fate, Ring of Immortals) — the
        # cross-axis union, handed to the picker in the same shape the handler
        # tests, so the two cannot offer and counter different sets.
        spec["stack_any_classes"] = [list(entry) for entry in any_classes]
    targets_filter = payload.get("targets_filter")
    if targets_filter:
        # "…that targets a permanent you control". Offering a spell this
        # narrowing excludes would let Ring of Immortals be activated with
        # nothing it could legally counter — the cost paid for no effect.
        spec["stack_targets_filter"] = dict(targets_filter)
    if payload.get("targets_source"):
        # "…that targets **this creature**" (Mistfolk). The picker resolves the
        # word against the ability's own permanent, which `legality` has in hand
        # and this table does not — so the flag travels and the enumeration
        # answers it. Without it the ability offers every spell on the stack and
        # then counters nothing, which is the {U} paid for no effect the
        # narrowing beside it exists to prevent.
        spec["stack_targets_source"] = True
    return spec


def _chosen_permanent_spec(payload: dict) -> dict | None:
    """Whose battlefield a mid-resolution choice is drawn from.

    "You and **target player** exchange control of the creature you each control
    with the greatest mana value" (Juxtapose). The permanents are not targets —
    they are chosen as the spell resolves (CR 601.2c chose nothing but the
    player) — but the *player* is, and this instruction's ``controlled_by``
    is the only place the compiled program records it. ``_controlled_by_seat``
    reads the same word at resolution, so the seat the picker asks for and the
    seat the exchange draws from are one answer.

    The caster's own side answers None: "you" names no choice, and a spell whose
    every step named the caster would otherwise raise a player picker for a
    choice nobody makes.
    """
    if payload.get("controlled_by") == "target" or payload.get("chooser") == "target":
        return {"kind": "player"}
    return None


def _counter_ability_spec(payload: dict) -> dict | None:
    """"Counter target activated ability from an artifact source" (Rust, Ayesha
    Tanaka) — an *ability* on the stack, not a spell.

    The same "stack" picker a counterspell raises, because the object is chosen
    from the same zone; what differs is which objects it may offer, and every
    narrowing is handed over in the shape the handler tests it in
    (``ability_kinds``, ``source_card_types``). One reading, so the ability the
    picker offers and the ability the counter would actually counter are the
    same set — an offer the handler then refuses is a tap paid for nothing.

    "Counter **that** ability" (Imprison) chooses nothing: the object is the one
    its trigger fired on, found by identity. None is the answer there, exactly
    as it is for the counterspell's "counter it".
    """
    if payload.get("bound_to_trigger"):
        return None
    spec: dict = {
        "kind": "stack",
        "stack_ability_kinds": list(payload.get("ability_kinds") or ()) or ["activated", "triggered"],
    }
    source_types = payload.get("source_card_types")
    if source_types:
        spec["stack_ability_source_types"] = list(source_types)
    return spec


def _graveyard_return_spec(payload: dict) -> dict:
    """A graveyard return, narrowed to the card type it may take.

    Regrowth takes any card, Raise Dead a creature card, Reconstruction an
    artifact card — the same instruction with different data. The handler pops
    the chosen index out of the *caster's* graveyard, so the picker is scoped to
    it.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    # "Up to two target creature cards" (Sanguine Indulgence). This kind settles
    # its own spec, so the generic `targets` reading in `_from_instruction` never
    # runs for it - the maximum has to be lifted here, or the picker collects one
    # card for a spell that names two.
    count = (payload.get("targets") or {}).get("count")
    if isinstance(count, int) and count > 1:
        spec["max_targets"] = count
    if payload.get("card_types"):
        # "target instant or sorcery card" (Shipwreck Dowser) — the union the
        # round-19 graveyard picker already tests by primary type.
        spec["card_types"] = list(payload["card_types"])
    elif payload.get("any_card"):
        spec["any_card"] = True
    elif payload.get("card_type") not in (None, "creature"):
        spec["card_type"] = payload["card_type"]
    # "target **Griffin** card" (Mtenda Griffin). Handed over in the key name
    # `graveyard_card_matches` reads, for the reason the card type beside it is:
    # a spec that dropped the subtype would offer every creature card in the
    # pile and the handler's own re-check would then decline what the picker had
    # just offered.
    if payload.get("graveyard_subtypes"):
        spec["graveyard_subtypes"] = list(payload["graveyard_subtypes"])
    return spec


def _graveyard_exile_spec(payload: dict) -> dict:
    """"Exile target card from a graveyard", narrowed to the card type it may
    take.

    Any seat's graveyard, so no ``own_graveyard_only`` — the picker is the
    reanimation one because the *choice* is identical; only where the card goes
    afterwards differs, and that is the handler's business.

    Derived from the payload rather than a fixed dict, for the reason
    :func:`_graveyard_return_spec` is: Return to Nature takes any card, Grave
    Robbers an artifact card and Eater of the Dead a creature card, and a fixed
    ``any_card`` spec would offer Grave Robbers a creature its own re-check then
    refuses. ``graveyard_card_matches`` reads the same keys in all three places.
    """
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    card_type = payload.get("card_type")
    if payload.get("any_card") or card_type is None:
        spec["any_card"] = True
    elif card_type != "creature":
        # "creature" is the enumerator's own default, so naming it changes
        # nothing; every other type is carried.
        spec["card_type"] = card_type
    return spec


def _prevention_shield_spec(payload: dict) -> dict | None:
    """A "prevent the next N damage" shield, and who is being shielded.

    One kind, five answers, and the payload settles which: the shield sits on
    the caster (Conservator), on the source permanent itself (Rock Hydra), on
    the permanent this Aura is attached to (Fylgja), on a *source of the named
    colour* the controller chooses (the Circles of Protection), or on a target
    the ability picks (Oasis, Samite Healer, Guardian Angel). The first three
    choose nothing at all, which is why this returns None rather than a spec.
    """
    if payload.get("to_self") or payload.get("to_source"):
        return None
    if payload.get("to_attached"):
        # "…that would be dealt to **enchanted creature**" (Fylgja). The fifth
        # answer, and the docstring above counted four because nothing had
        # looked: an Aura's ability acts on its own host (CR 303.4), so the
        # host is named rather than chosen and the ability raised an "any
        # target" picker whose answer the shield never read.
        return None
    if payload.get("protection_kind") == "color":
        # The chosen source may be a permanent of that colour on any
        # battlefield, or a spell of that colour on the stack; `also_stack`
        # folds both into one prompt because the engine matches the shield by
        # colour rather than by identity.
        spec = {
            "kind": "permanent",
            "color_filter": payload.get("prevention_color"),
            "also_stack": True,
        }
        colours = payload.get("prevention_colors")
        if colours:
            # "a black **or red** source of your choice". The picker narrows to
            # exactly what the shield will answer to, so the offer and the
            # recheck at damage time (CR 615.9) agree; dropping it here would
            # offer a green source for a shield that can never match one.
            spec["any_colors"] = list(colours)
        return spec
    return _from_targets_payload(payload.get("targets")) or {"kind": "any"}


def _whole_prevention_shield_spec(payload: dict) -> dict | None:
    """Pentagram of the Ages’ shield, and the one printing that chooses nothing.

    "The next time **a source of your choice** would deal damage to you this
    turn, prevent that damage" runs the prompt its four siblings above run — a
    permanent on any battlefield or a spell on the stack, matched by identity,
    so no filter narrows it. CR 609.7a is what makes them one prompt rather than
    four: the phrase names *a source of damage*, and the set a player may choose
    from is the rule’s, not the card’s.

    ``from_source`` is the other printing — "The next time **this creature**
    would deal damage to you this turn" (Mercenaries) — where the source is
    printed rather than chosen, so there is nothing to ask. That is why this is
    a payload reader and not a flat entry beside ``grant_half_prevention_shield``:
    one kind, two printings, and a flat entry would have raised a picker on the
    card that names its own source.

    Pentagram had no entry at all until Ice Age was promoted, and the omission
    was not a missing prompt but a **stronger card**: with nothing chosen the
    handler falls through to ``make_whole_charge``, a shield answering to every
    source, so the next damage from anything was prevented.
    """
    if payload.get("from_source"):
        return None
    if payload.get("recipient") == "target":
        # "…would deal damage to **any target** this turn" (Circle of Despair).
        # Two choices in one announcement, which is Jade Monolith's shape and
        # runs Jade Monolith's two-stage prompt: the *target* first — CR 115.4's
        # creature, planeswalker, battle or player — and then the damage source,
        # which ``requires_source`` is what tells the client to ask for.
        #
        # The source cannot ride ``source_of_choice`` here as it does below,
        # because that flag makes the *only* prompt a source picker and this
        # card has a real target to announce (CR 601.2c).
        return {"kind": "any", "requires_source": True}
    return {"kind": "permanent", "source_of_choice": True, "also_stack": True}


def _set_base_pt_spec(payload: dict) -> dict:
    """"Target creature ... has base power 0 until end of turn", narrowed to the
    creatures the printed line allows.

    Island of Wak-Wak reaches only fliers and Singing Tree only attackers; the
    enumerator applies both itself, so unlike a subtype or tapped restriction
    they have to reach the spec rather than being left to the instruction
    filter. Sorceress Queen's "other than this creature" does not appear here
    because `_ability_target_legal` already excludes the source.
    """
    return {"kind": "creature", **_narrowing_flags(payload)}


def _cast_permission_spec(payload: dict) -> dict | None:
    """A cast-permission grant targets only in its graveyard form ("You may
    cast target red instant or sorcery card from your graveyard", Chandra,
    Flame's Catalyst's −2); the exiled-cards and cost-waiver forms choose
    nothing as they go on the stack."""
    if not payload.get("target_graveyard_card"):
        return None
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    card_types = tuple(payload.get("card_types") or ())
    if card_types:
        spec["card_types"] = list(card_types)
    colors = tuple(payload.get("colors") or ())
    if colors:
        # Every printed colour, not the first: "white or black" is a union
        # (CR 105.2b), and offering only the first silently takes half the
        # legal choices away.
        spec["graveyard_colors"] = list(colors)
    return spec


def _reanimation_spec(payload: dict) -> dict | None:
    """"Return target creature card from your graveyard to the battlefield",
    narrowed by the colours the phrase prints (Dreams of the Dead's "white or
    black") and by **whose graveyard** the printed phrase reads.

    Derived rather than a fixed dict for :func:`_graveyard_return_spec`'s
    reason: the handler re-checks the same narrowing against the same predicate
    (``graveyard_card_matches``), so a picker that offered more would be
    offering choices the resolution then declines — and one that offered fewer
    would take a legal choice away.

    ``own_graveyard_only`` is the second half of that and was a constant here,
    which is the same failure one key over. "Put target creature card **from a
    graveyard** onto the battlefield under your control" (Hymn of Rebirth) is
    lowered with ``any_graveyard``, and its handler already reads the named
    seat's graveyard — so the flag was the derivation disagreeing with the
    program it is derived from, and the disagreement cost the card every target:
    with the only creature card in an opponent's pile, ``_enumerate_targets``
    returned nothing and the cast was refused outright. The payload is the
    evidence, exactly as the colours beside it are.

    ``from_top`` is the same reading pushed all the way: "Return **the top**
    creature card of your graveyard to the battlefield" (Shallow Grave) names
    its card by position, so nobody chooses and there is no picker to derive.
    The handler says so outright — it overwrites any index the wire carried —
    and this function claimed one anyway, which is the derivation disagreeing
    with the program it is derived from once more. The cost is the mirror of
    Hymn of Rebirth's: with an empty graveyard ``_enumerate_targets`` returns
    nothing, and a picker the client must fill from an empty list is a cast that
    cannot be made — where the card, resolving, simply finds no creature.
    """
    if payload.get("from_top"):
        return None
    spec: dict = {"kind": "graveyard_creature"}
    if not payload.get("any_graveyard"):
        spec["own_graveyard_only"] = True
    colors = tuple(payload.get("colors") or ())
    if colors:
        spec["graveyard_colors"] = list(colors)
    return spec


def _graveyard_aura_spec(payload: dict) -> dict:
    """"Return target **Aura** card from your graveyard to the battlefield"
    (Hakim, Loreweaver).

    The graveyard picker with the payload handed straight over, in the key
    names ``graveyard_card_matches`` reads — the same arrangement
    :func:`_reanimation_spec` makes and for the same reason: the handler
    re-checks the card it is given against this exact payload, so a spec that
    narrowed differently would offer an Aura the resolution then declines.
    """
    spec: dict = {"kind": "graveyard_creature", "own_graveyard_only": True}
    if payload.get("card_type"):
        spec["card_type"] = payload["card_type"]
    if payload.get("graveyard_subtypes"):
        spec["graveyard_subtypes"] = list(payload["graveyard_subtypes"])
    return spec


def _forced_sacrifice_spec(payload: dict) -> dict | None:
    """Who a "sacrifices a creature" effect asks is what decides whether it
    targets at all.

    "Sacrifice a creature" (Dire Fleet Warmonger) and "each opponent sacrifices
    a creature" (Goremand) choose nothing — the payers follow from the effect's
    own controller. "Target opponent sacrifices a creature of their choice with
    flying" (Run Afoul) chooses a player, and it may not choose the caster
    (CR 115.4). One instruction kind serves all three, so only the payload can
    tell them apart; answering "player" for every one of them would put a
    picker in front of Goremand, whose answer nothing reads.
    """
    who = payload.get("who")
    if who == "target_opponent":
        return {"kind": "player", "opponents_only": True}
    if who == "target_player":
        return {"kind": "player"}
    return None


# One kind, several specs, decided by payload.
def _graveyard_to_library_spec(payload: dict) -> dict:
    """Drafna's Restoration's picker: cards of one type, in *any* graveyard.

    Not scoped to the caster's own — the spell names a target player, and the
    graveyard the cards come from is theirs. The maximum is deliberately absent:
    "any number" prints no ceiling, so the only cap is how many legal targets
    exist, which `cast_target_spec` fills in once it has enumerated them.
    """
    spec: dict = {"kind": GRAVEYARD_TARGET_KIND}
    # Handed over in the key names ``graveyard_card_matches`` reads, so the
    # picker and the handler ask one question. "Any card" (Misinformation) and
    # a supertype (Lodestone Bauble) are narrowings that predicate already
    # knows; a spec that only ever said ``card_type`` offered the whole pile for
    # the first and every land for the second.
    if payload.get("any_card"):
        spec["any_card"] = True
    else:
        spec["card_type"] = payload.get("card_type", "artifact")
    if payload.get("supertypes"):
        spec["supertypes"] = list(payload["supertypes"])
    # "From **your** graveyard" (Reinforcements) is one pile, and the picker has
    # to say so: the enumerator walks every graveyard by default, so a picker
    # left unscoped would offer the opponent's creature cards for a spell that
    # cannot touch them — and the handler, which indexes the caster's pile,
    # would then move whatever card happened to sit at that slot.
    if payload.get("graveyard_owner") == "you":
        spec["own_graveyard_only"] = True
    # "from **an opponent's** graveyard" (Misinformation). CR 115.4's exclusion
    # with nothing chosen: the pile is not a target, but which piles the *cards*
    # may be taken from is printed, and left unscoped the picker would offer the
    # caster their own graveyard — a strictly better card than the one printed,
    # and the mirror of the mistake `own_graveyard_only` above exists to stop.
    elif payload.get("graveyard_owner") == "an_opponent":
        spec["opponent_graveyard_only"] = True
    described = payload.get("targets") or {}
    if described.get("unbounded"):
        spec["unbounded_targets"] = True
    else:
        spec["count"] = int(described.get("count") or 1)
    return spec


def _retarget_spec(payload: dict) -> dict:
    """"Target spell with a single target [if that target is you]"
    (Deflection, Reflecting Mirror — CR 115.7a, CR 115.9a).

    The same "stack" picker a counterspell raises — the object is chosen from
    the same zone — narrowed by what the card asks about it. **Two keys, and
    the first is not optional:** ``stack_single_target`` is CR 115.9a's count,
    which every card printing this sentence carries, while
    ``stack_single_target_is`` is Reflecting Mirror's extra question about
    *whose* face it is. They were one key while only one card printed the
    sentence, and that made the count vanish for the card that prints no "if":
    Deflection would have been offered every spell on the stack, including ones
    that target nothing.

    Handed over in the shape the handler tests it in, so the spells offered and
    the spells the effect could actually re-aim are the same set — an offer the
    handler then refuses is mana paid for nothing.
    """
    spec = {
        "kind": "stack",
        "stack_single_target": True,
        "stack_single_target_is": payload.get("current_target"),
    }
    # "…and **that target is a creature**" (Meddle). The object half of the
    # same question, on its own key because the two are tested with different
    # readers — a seat is compared against the caster and a permanent is asked
    # what type it is. Emitted only when the card prints it, so Deflection's and
    # Reflecting Mirror's specs stay byte-identical.
    if payload.get("current_target_type"):
        spec["stack_single_target_type"] = payload["current_target_type"]
    return spec


_KIND_TO_SPEC_FROM_PAYLOAD = {
    "choose_new_spell_target": _retarget_spec,
    "change_target_spell_target": _retarget_spec,
    "put_graveyard_cards_on_library_top": _graveyard_to_library_spec,
    "sacrifice_matching_permanent": _forced_sacrifice_spec,
    "target_gains_life": _life_gain_spec,
    "target_loses_life": _player_recipient_spec,
    "mill_target_player": _player_recipient_spec,
    "counter_top_stack_spell": _counter_spec,
    "counter_stack_ability": _counter_ability_spec,
    "choose_permanent": _chosen_permanent_spec,
    # Reverberation names a spell on the stack the same way a counter does, and
    # narrows it the same way ("target **sorcery** spell"), so it derives the
    # same picker — the spec is about what is being *chosen*, not about what is
    # then done to it.
    "redirect_damage_from_target_spell_until_eot": _counter_spec,
    "return_creature_from_graveyard_to_hand": _graveyard_return_spec,
    "reanimate_creature": _reanimation_spec,
    # Hakim, Loreweaver. The same graveyard picker, narrowed by the payload
    # the handler re-checks against — one predicate, so the Auras offered are
    # exactly the Auras the resolution will take.
    "reanimate_aura_onto_source": _graveyard_aura_spec,
    "exile_target_graveyard_card": _graveyard_exile_spec,
    "grant_prevention_shield": _prevention_shield_spec,
    "grant_whole_prevention_shield": _whole_prevention_shield_spec,
    "set_base_pt_target_until_eot": _set_base_pt_spec,
    "grant_cast_permission": _cast_permission_spec,
    "look_top_pick_to_hand": _look_top_pick_spec,
}


def _cast_cost_picker(card, from_zone: str) -> dict | None:
    """The picker a printed additional cost needs when *card* is cast from
    *from_zone*, or None when the costs charged there choose nothing.

    **Zone-scoped, exactly as the payment is.** ``queue_from_hand`` gathers the
    costs it will charge with the same test, because a cost naming a zone is a
    price for casting from *that* zone: Demonic Embrace pays 3 life and a card
    from the graveyard and nothing at all from the hand, so a picker that read
    the card alone asked a hand cast to name a discard it would never be
    charged for — and then, being a cost picker, took the place of the Aura's
    enchant target and made the card uncastable from either zone.
    """
    for cost in additional_costs(card):
        if cost.from_zone is not None and cost.from_zone != from_zone:
            continue
        cost_spec = _cost_picker_spec(cost)
        if cost_spec is not None:
            # The zone the cast leaves, carried so the enumerator can tell a
            # hand cast from a graveyard one: CR 601.2a withholds the spell
            # itself from a discard cost only when the hand is where it came
            # from, and a second copy of Demonic Embrace in hand really can pay
            # for the one in the graveyard. Emitted only for a cast from
            # somewhere else, so every spec written before a zone-scoped cost
            # existed is unchanged and "hand" stays the reader's default.
            if from_zone != "hand":
                return {**cost_spec, "cast_zone": from_zone}
            return cost_spec
    return None


def _cast_target_spec(card, program) -> dict | None:
    """What *card* announces as a **target** when it is cast (CR 601.2c), or
    None when it targets nothing. The cost half of the announcement is
    :func:`_cast_cost_picker`; :func:`derive_cast_spec` is the two together."""
    graveyard_aura = _ENCHANT_GRAVEYARD_LINE.search(program.normalized_text or "")
    if graveyard_aura is not None:
        # Animate Dead. `_apply_aura_effect` reads the chosen index out of
        # whichever graveyard the caster pointed at, so unlike the spell-side
        # `reanimate_creature` this one is not scoped to their own.
        return {"kind": "graveyard_creature"}

    enchant = card_enchant_subject(card.oracle_text)
    if enchant is not None:
        return enchant_subject_spec(enchant)

    copied = copy_on_enter_type(program.normalized_text or "")
    if copied is not None:
        # Clone / Copy Artifact / Vesuvan Doppelganger. `optional` is what tells
        # the UI to offer the choice only when there is something to copy, and
        # to let the permanent enter as itself otherwise (CR 707.9a).
        return {"kind": copied, "optional": True}

    # Only a spell picks a target as it is cast. A permanent's instructions
    # include those of its *abilities*, which choose their own targets on
    # activation — reading a filter off those would make the UI demand a target
    # for casting Royal Assassin because its tap ability destroys a tapped
    # creature. 27 cards in the pool derive a target they do not have if this
    # gate is removed, so it is measured rather than assumed.
    type_line = card.type_line.lower()
    if "instant" in type_line or "sorcery" in type_line:
        return _from_instructions(program.instructions)

    # A permanent's enters-the-battlefield trigger is the one exception: this
    # engine picks its target as the permanent is cast (Oubliette), where
    # CR 603.3d would choose it when the trigger goes on the stack. That is a
    # standing approximation, not a targeting question — but while it holds, the
    # prompt has to be raised at cast time or the trigger has no target at all.
    return _from_instructions([
        ability.instruction
        for ability in program.triggered_abilities
        if ability.supported
        and ability.instruction is not None
        and ability.condition.kind == "enters_battlefield"
    ])


def derive_cast_spec(card, program, *, from_zone: str = "hand") -> dict | None:
    """The cast-time spec of *card* cast from *from_zone*, or None when it
    chooses nothing.

    None is the answer for a permanent whose only targeting belongs to an
    activated ability — Royal Assassin picks its victim when the ability is
    activated, not when the creature is cast.

    A printed additional cost is picked as the spell is cast and belongs to the
    *cost*, so it is read from the cost table rather than from any instruction;
    ``sacrifice_cost`` / ``discard_cost`` / ``exile_cost`` are what tell the
    client to send it on the cost field and to say "sacrifice" rather than
    "target".
    """
    cost_spec = _cast_cost_picker(card, from_zone)
    target_spec = _cast_target_spec(card, program)
    if cost_spec is None:
        return target_spec
    if target_spec is None:
        return cost_spec
    # A spell whose *effect* is the payment (a forced sacrifice read off the
    # instruction) already is the cost picker, and a second one would ask twice
    # for one permanent. The same guard ``derive_activation_spec`` makes for
    # Diamond Valley, one announcement step over.
    if (
        target_spec.get("sacrifice_cost")
        or target_spec.get("discard_cost")
        or target_spec.get("exile_cost")
    ):
        return target_spec
    # Demonic Embrace, Goblin Grenade, Soul Exchange: a real target *and* a
    # cost, which CR 601.2b and CR 601.2c make two separate announcements
    # carrying two separate fields. One spec cannot be both, so the cost rides
    # beside the target under its own key and the client runs two prompts —
    # this is `derive_activation_spec`'s Dwarven Weaponsmith case on the cast
    # side, and it was missing here: the cost was returned *instead of* the
    # target, so the Aura was never asked what to enchant and the engine refused
    # the cast it had itself described.
    return {**target_spec, "cost_spec": cost_spec}


def derive_cast_target(card, program, *, from_zone: str = "hand") -> str | None:
    """The cast-time target *kind* of *card*, for callers that need no flags."""
    spec = derive_cast_spec(card, program, from_zone=from_zone)
    return spec["kind"] if spec is not None else None


def targets_mana_value_x(instructions) -> bool:
    """Whether these instructions target an object whose mana value must equal
    the cast's X — "counter target spell with mana value X" (Spell Blast),
    "destroy target artifact with mana value X" (Detonate).

    Read off the compiled program rather than the oracle text, and recursing
    through the wrappers for the reason :func:`_from_instructions` does: Detonate
    prints two sentences, so its destroy is a step of a ``sequence`` and a reader
    that stopped at the wrapper would answer no about the card that asks.
    """
    for instruction in instructions:
        if instruction.payload.get("mv_equals_x"):
            return True
        nested = _nested_steps(instruction)
        if nested and targets_mana_value_x(nested):
            return True
    return False


#: The wrapper kinds above, and the payload keys whose instructions they carry.
#: The same two ``_from_instructions`` descends into, and for the same reason
#: it gives — an effect written as two steps carries its targeting on the step
#: that targets.
#: The wrappers a targeting instruction can be *inside*, and where each keeps
#: its steps. `if_then` carries both arms for the reason `_from_instructions`
#: reads both: CR 601.2c chooses an ability's targets when it is activated,
#: whichever way the condition later falls. It was missing here while
#: `_from_instructions` handled it by hand, so the spec recursed into a
#: conditional branch and every other reader of this table stopped at the
#: wrapper — which is how Lesser Werewolf's "target creature blocking or blocked
#: by this creature" reached `legality.py` as an `if_then` with no filter.
_WRAPPER_STEP_KEYS = {
    "sequence": ("steps",),
    "may": ("action", "then"),
    "if_then": ("then", "else"),
}


def _nested_steps(instruction) -> tuple:
    """The instructions a wrapper carries, empty for anything else."""
    nested: tuple = ()
    for key in _WRAPPER_STEP_KEYS.get(instruction.kind, ()):
        nested += tuple(instruction.payload.get(key) or ())
    return nested


def derive_instruction_spec(instructions) -> dict | None:
    """The target spec a bare instruction sequence describes, or None for none.

    The entry point for a sequence that is nobody's ability line: CR 603.12's
    reflexive triggered ability is created mid-resolution and chooses its own
    targets then, so there is no `ability` object to hand
    :func:`derive_activation_spec`. Same reader underneath, so what a reflexive
    ability offers and what an activated one offers cannot disagree.
    """
    return _from_instructions(instructions)


def _from_instructions(instructions) -> dict | None:
    """The first spec any instruction in *instructions* describes.

    Recurses into `sequence` steps: an effect written as two steps carries its
    targeting on the step that targets (Psionic Blast's damage to any target,
    followed by its self-damage; Orcish Artillery's ability, the same shape),
    and stopping at the wrapper would leave an otherwise fully-described effect
    with no prompt.
    """
    for instruction in instructions:
        if instruction.kind == "sequence":
            nested = _from_instructions(instruction.payload.get("steps") or ())
            if nested is not None:
                return nested
            continue
        if instruction.kind == "if_then":
            # "If you lose the flip, counter target artifact spell you control."
            # (Goblin Artisans.) A branch that may not run still *chooses* — CR
            # 601.2c and 602.2b pick targets as the ability is activated,
            # whichever way the coin lands — so both arms are read, and an
            # ability whose only targeting sits behind a conditional gets its
            # prompt rather than the picker's silent fallback.
            nested = _from_instructions(
                tuple(instruction.payload.get("then") or ())
                + tuple(instruction.payload.get("else") or ())
            )
            if nested is not None:
                return nested
            continue
        if instruction.kind == "unless_player_pays":
            # "Unless an opponent pays {2}, gain control of **target artifact**
            # …" (Scarwood Bandits). The ability's target sits on the *unpaid*
            # branch, and CR 601.2c picks it as the ability is activated —
            # before anyone is offered the cost — so this branch is read where
            # an offer's declined branch deliberately is not.
            nested = _from_instructions(
                tuple(instruction.payload.get("unpaid") or ())
            )
            if nested is not None:
                return nested
            continue
        if instruction.kind == "choose_one":
            # A **choice made before the targets** (CR 601.2b/602.2b: modes
            # first, then targets), so the modes are read only when the choice
            # cannot change the answer.
            #
            # Barbarian Guides is why: "Choose a land type. Target creature you
            # control gains snow landwalk of the chosen type…" lowers to one
            # mode per land type, and all eighteen carry the *same* target
            # description, because the type is what varies and the creature is
            # not. Stopping at the wrapper left the whole ability with no
            # prompt — and, because the handler enforces the printed
            # "you control" against a target nobody chose, doing nothing at all.
            #
            # Non-uniform modes deliberately answer None. Essence Filter and
            # Relic Bind choose different things in each mode, and the mode is
            # settled first: the per-mode reader
            # (``graveyard_target_spec(..., mode_index=)``) is what answers
            # those, and collapsing them to the first mode's spec would offer a
            # picker for a mode the player had not chosen.
            modes = instruction.payload.get("modes") or ()
            described = [
                _from_instructions((mode.get("instruction"),))
                if isinstance(mode, dict) and mode.get("instruction") is not None
                else None
                for mode in modes
            ]
            if described and all(spec == described[0] for spec in described[1:]):
                if described[0] is not None:
                    return described[0]
            continue
        if instruction.kind == "may":
            # "**Target opponent** may ante the top card of their library."
            # (Amulet of Quoz.) The offer's own target, which is the *seat being
            # offered* rather than anything the branches name — so it is read
            # off this instruction before its branches are, the way every
            # non-wrapper instruction is read before nothing at all.
            #
            # ``actor`` cannot answer this: the reference reader spells "an
            # opponent" ``opponent`` and "target opponent" ``target_opponent``
            # precisely so the two do not share a kind, but reading the actor
            # here would put that distinction in two places. The lowering
            # attaches the ordinary ``targets`` description instead, so the
            # picker learns it the way it learns every other target.
            own = _from_targets_payload(instruction.payload.get("targets"))
            if own is not None:
                return own
            # An optional action still targets — "you may tap or untap target
            # creature" names a creature whether or not the offer is taken.
            #
            # `action` and `then` only. `otherwise` is the *declined* branch and
            # `reflexive` is a separate ability (CR 603.12) that chooses its own
            # targets when the payment creates it; reading either here would
            # report this instruction as targeting something it never picks —
            # and for the reflexive branch, at a moment when the choice has not
            # been offered yet.
            nested = _from_instructions(
                tuple(instruction.payload.get("action") or ())
                + tuple(instruction.payload.get("then") or ())
                # …and the **declined** branch, last. "Destroy target creature
                # unless its controller pays life equal to its toughness"
                # (Essence Vortex) puts the whole spell on this branch, and the
                # creature is a target of the *spell*: CR 601.2c picks it as the
                # spell is announced, before anybody is offered the payment, so
                # a picker that skipped this branch would leave the spell with
                # no prompt and the destruction pointed at nothing.
                #
                # Read after the two above rather than beside them, so an offer
                # that targets on both sides still answers with the branch it
                # takes. ``reflexive`` stays out: CR 603.12 makes it a separate
                # ability that chooses its own targets when the payment creates
                # it, which has not happened yet.
                + tuple(instruction.payload.get("otherwise") or ())
            )
            if nested is not None:
                return nested
            continue
        spec = _from_instruction(instruction)
        if spec is not None:
            return spec

    return None


def _from_instruction(instruction) -> dict | None:
    """The spec one instruction describes, or None when it describes none."""
    # A kind with several specs settles its own case first, because it is the
    # only reader that knows how to combine its payload with its `targets`
    # description — a colour-restricted counterspell carries both, and the
    # generic targets reading would drop the colour.
    from_payload = _KIND_TO_SPEC_FROM_PAYLOAD.get(instruction.kind)
    if from_payload is not None:
        return from_payload(instruction.payload)
    described = _from_targets_payload(instruction.payload.get("targets"))
    if described is not None:
        if described.get("division") == CHOSEN:
            # **How much there is to divide**, so the picker can ask for a
            # division that totals it (CR 601.2d). Read off the payload here
            # rather than copied into the `targets` description at lowering: the
            # amount is the instruction's own field, and a second copy beside
            # the target description is a second thing to keep in step.
            # ``amount`` for damage and ``count`` for a distributed counter
            # placement — CR 601.2d covers both with one sentence, and each
            # instruction family spells its quantity with the word its own
            # handler reads. A variable ("x") is no total yet: the picker learns
            # it once the caster announces X, or the card defines one.
            amount = instruction.payload.get(
                "amount", instruction.payload.get("count", 0)
            )
            if isinstance(amount, int):
                described["division_total"] = amount
            described["division_x_bonus"] = int(
                instruction.payload.get("amount_bonus", 0) or 0
            )
        return described
    # **A ``type_filter`` is only a picker for a kind that picks.** The key
    # names the class an instruction is *about*, and what that class is for
    # depends entirely on the kind holding it: "destroy target permanent"
    # narrows the one object the caster chooses, while "destroy all black
    # creatures" names every object the effect touches and chooses none of them
    # (CR 115.1a — an instant or sorcery is targeted only where its ability
    # says "target"). Read unkeyed, the two are the same payload, so the reader
    # guessed "picker" and a sweep reported a target it never chooses.
    if instruction.kind in _TYPE_FILTER_NAMES_THE_TARGET:
        spec = _spec_from_type_filter(instruction.payload)
        if spec is not None:
            return spec
    # **An instruction acting on a recorded set chooses nothing.**
    # ``permanents_from`` names what an earlier step of this same resolution
    # put in the scratchpad — the creature a ``choose_permanent`` prompt was
    # answered with, the permanents a tap recorded — and CR 601.2c chose none
    # of them: a target is announced when the spell or ability goes on the
    # stack, and these objects were not known then.
    #
    # Asked here rather than in each kind's own row because it is a property of
    # the payload and not of the kind: the very same ``add_counter_to_target``
    # is a target on Dwarven Weaponsmith and a back-reference on Thelon's
    # Chant. Read as a target, the Chant's trigger acquired one it never had —
    # and a trigger whose only target is illegal is removed from the stack
    # (CR 603.3c), which on a board with no creature to shrink is the whole
    # ability gone instead of three damage.
    #
    # After the two readings above on purpose: an instruction carrying a real
    # ``targets`` description settles on that, and none in the pool carries
    # both.
    if instruction.payload.get("permanents_from"):
        return None
    by_kind = _KIND_TO_SPEC.get(instruction.kind)
    return dict(by_kind) if by_kind is not None else None


#: The spec ``kind`` a several-**role** target description takes.
#:
#: Every other kind names one picker over one list, because every other spell in
#: the pool chooses its targets from one set: "up to two target creatures" is two
#: slots of the same kind, and ``_enumerate_targets`` answers all of them at
#: once. "Target creature that **target Wall** blocked this turn" (Glyph of
#: Delusion) is not that. The two slots have different kinds, different
#: narrowings, and — the part no flag can express — the second slot's legal set
#: is decided by what was chosen for the first.
#:
#: So a roles spec carries an ordered ``roles`` list instead of a single kind,
#: and ``engine/legality.py`` enumerates role *n* only with roles 0…n-1 settled.
#: Anything that reads ``spec["kind"]`` and does not know this name sees a kind
#: it has no branch for, which is the loud direction: a roles spec silently
#: reduced to its first role would let a spell be cast with a target no gate
#: ever checked.
ROLES_TARGET_KIND = "roles"


def roles_spec(targets: dict) -> dict | None:
    """The ordered-role spec a ``kind: "roles"`` description means.

    Each role is itself an ordinary object description, so it goes through the
    same :func:`_from_targets_payload` every one-target spell does — the picker
    flags a role carries mean exactly what they mean anywhere else, and a
    narrowing added to that reader reaches a role for free.

    ``depends_on`` is lifted out of the role's own key so every consumer asks
    one question ("which earlier role settles this one?") rather than knowing
    the vocabulary of relations. The relation *key* travels beside it, because
    the enumerator has to know not merely that there is a dependency but what
    it asks of the pair.
    """
    roles: list[dict] = []
    for entry in targets.get("roles") or ():
        if not isinstance(entry, dict):
            return None
        described = _from_targets_payload({**entry, "kind": entry.get("kind", "object")})
        if described is None:
            return None
        described["role"] = entry.get("role")
        relation, depends_on = role_dependency(entry)
        if relation is not None:
            described["relation"] = relation
            described["depends_on"] = depends_on
        roles.append(described)
    if len(roles) < 2:
        # One role is not a roles description — it is an ordinary one-target
        # spell wearing a shape nothing else reads. Refusing here rather than
        # flattening it keeps the two shapes from both being able to mean the
        # same spell.
        return None
    return {"kind": ROLES_TARGET_KIND, "roles": roles}


#: What each dependent-role relation asks of the pair, given the *earlier*
#: role's chosen permanent and a candidate for the later one.
#:
#: One table, three readers: ``engine/legality.py`` narrows the picker with it,
#: the same module's gate re-asks it over the targets a caster named, and the
#: handler re-asks it once more at resolution (CR 608.2b). A relation whose
#: picker and whose re-check were separate tables is the defect this repo keeps
#: finding; here the *only* way to add a relation is to add it where all three
#: look.
#:
#: A relation the grammar can describe and this table does not know refuses —
#: ``legality`` offers nothing for it and the re-check answers False — because
#: an unanswerable narrowing must never widen to "any".
#:
#: Each test takes ``(earlier, candidate, game)``. The game is there for the
#: relations that are not readable off the two objects: control is CR 613
#: layer 2 and only ``Game.controller_index_of`` answers it, and a relation
#: that read ``base_controller_index`` instead would be a second opinion about
#: who controls what — the thing the control seam exists to abolish. A test
#: that does not need it simply ignores the argument.
ROLE_RELATION_TESTS = {
    # "target creature that **target Wall** blocked this turn" (Glyph of
    # Delusion). The record is stamped on the blocker by the declare-blockers
    # step and read by id, never by slot: both permanents may leave and return
    # between the cast and the resolution, and CR 400.7 makes the returning one
    # a different object.
    "blocked_by_role": lambda earlier, candidate, game: (
        candidate.permanent_id
        in set(earlier.metadata.get("blocked_attacker_ids_this_turn") or ())
    ),
    # "two target blocking creatures controlled by **the same opponent**"
    # (Sorrow's Path). Which opponent is not a property of either creature —
    # each role's own filter already says "an opponent controls this one", and
    # two roles carrying that filter would admit one blocker from each of two
    # opponents in a CR 802 multi-defender combat. The relation is what makes
    # the second choice depend on the first, and it is asked of the control
    # seam because control moves (CR 613 layer 2).
    "same_controller_role": lambda earlier, candidate, game: (
        game is not None
        and game.controller_index_of(earlier) is not None
        and game.controller_index_of(earlier) == game.controller_index_of(candidate)
    ),
}


def role_dependency(role: dict) -> tuple[str | None, str | None]:
    """*role*'s dependency as ``(relation key, earlier role name)``.

    One reader for **both** shapes a role is held in: the lowering's ``targets``
    payload, where the relation *is* the key (``"blocked_by_role": "blocker"``),
    and the derived spec, which lifts it into ``relation``/``depends_on`` so a
    picker can ask one question. Written once because the CR 608.2b re-check at
    resolution holds the payload while the picker holds the spec — and a reader
    that knew only the spec's spelling answered "no dependency" about the
    payload, which is a re-check that passes whatever the board says.
    """
    relation = role.get("relation")
    if isinstance(relation, str):
        depends_on = role.get("depends_on")
        return relation, depends_on if isinstance(depends_on, str) else None
    for key, value in role.items():
        if key.endswith("_role") and isinstance(value, str):
            return key, value
    return None, None


def role_relation_holds(role: dict, earlier, candidate, game=None) -> bool:
    """Whether *candidate* satisfies *role*'s dependency on *earlier*.

    True when the role has no dependency at all — the question does not arise
    for role 0 — and False whenever it has one this engine cannot answer or the
    earlier role resolves to nothing.

    *game* is passed by both callers (the picker in ``engine/legality.py`` and
    the CR 608.2b re-check in ``engine/handlers/_common.py``) and consumed by
    the relations that need it. It defaults to None so a relation asked without
    one refuses rather than answering from a narrower reading — the same
    direction an unknown relation takes.
    """
    relation, _depends_on = role_dependency(role)
    if relation is None:
        return True
    test = ROLE_RELATION_TESTS.get(relation)
    if test is None or earlier is None or candidate is None:
        return False
    return bool(test(earlier, candidate, game))


def spec_roles(spec: dict | None) -> list[dict]:
    """The ordered roles *spec* names, empty for every one-target spec.

    The one accessor, so a caller never has to test ``kind == "roles"`` *and*
    remember the key. An empty list is the honest answer for a spell that
    chooses one thing, and every loop written over it then reads the same for
    both shapes.
    """
    if not spec or spec.get("kind") != ROLES_TARGET_KIND:
        return []
    return list(spec.get("roles") or ())


def payload_role_slot(payload: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, read straight off
    an instruction's own ``targets`` description.

    The resolution's form of :func:`role_slot`. A handler holds the payload the
    lowering wrote and not the derived spec, and re-deriving one to ask a
    question the payload already answers is the second reading this module
    exists to abolish. Same list, same order, one answer.
    """
    targets = (payload or {}).get("targets")
    if not isinstance(targets, dict) or targets.get("kind") != ROLES_TARGET_KIND:
        return None
    for index, entry in enumerate(targets.get("roles") or ()):
        if isinstance(entry, dict) and entry.get("role") == role:
            return index
    return None


def role_slot(spec: dict | None, role: str | None) -> int | None:
    """Which slot of the chosen-target list *role* occupies, or None.

    The wire, the stack item and the resolution all carry a spell's targets as
    one positional list, and for a roles spell that list is in **dependency
    order** — the order :func:`spec_roles` reports. This is the one translation
    from a role's name to its slot, so the handler that reads "the subject" and
    the where-clause that reads "the blocked creature" cannot disagree about
    which of the two the caster picked.
    """
    if role is None:
        return None
    for index, entry in enumerate(spec_roles(spec)):
        if entry.get("role") == role:
            return index
    return None


def _from_targets_payload(targets) -> dict | None:
    """The spec from a grammar-lowered ``targets`` description.

    This is the evidence the legacy rules never recorded: it is what tells
    Lightning Bolt ("any target") apart from Earthbind ("target creature with
    flying") when both compile to a bare ``deal_damage``.
    """
    if not isinstance(targets, dict):
        return None
    kind = targets.get("kind")
    if kind == "card":
        # A card in a graveyard is not a permanent (CR 115.2), and this function
        # only knows how to describe permanents, players and the stack. The
        # instruction that carries such a description settles its own spec in
        # `_KIND_TO_SPEC_FROM_PAYLOAD`; answering here would hand the picker a
        # battlefield when the effect reads a graveyard.
        return None
    if kind == "roles":
        return roles_spec(targets)
    if kind == "any":
        return {"kind": "any"}
    if kind == "divided":
        # Fireball: "X damage divided evenly … among any number of targets".
        # The UI picks the targets and X follows from how many were chosen, so
        # this is its own prompt rather than a repeated "any target".
        spec = {"kind": "divided", "division": targets.get("division", "evenly")}
        # "…among any number of **target creatures**" (Fire Covenant). The
        # printed noun, carried through so the picker offers what the card
        # names — without it the seat loop in `legality._enumerate_targets`
        # offers both players' faces, which is a legal Fire Covenant target
        # only in an engine that never read the noun.
        narrowing = targets.get("filter") or {}
        if narrowing.get("type_filter") == "creature":
            spec["creatures_only"] = True
        bound = targets.get("max_targets")
        if isinstance(bound, int):
            # "…among **one or two** target creatures" (Contagion). A divided
            # spell is otherwise unbounded, so the picker would offer a third
            # creature the casting path then refuses (CR 601.2c). Carried as
            # the same ``max_targets`` key every other picker spec uses rather
            # than a divided-only spelling — the client already reads it.
            spec["max_targets"] = bound
        return spec
    if kind == "player":
        spec = {"kind": "player"}
        if targets.get("attacked_this_turn"):
            # "target player **who attacked this turn**" (Fire and Brimstone) —
            # the printed narrowing, carried to the seat loop that enforces it.
            spec["attacked_this_turn"] = True
        if targets.get("opponents_only"):
            # "Target opponent" — the caster's own seat is not a legal answer
            # (CR 115.4). The same flag Word of Command's kind-table entry
            # carries, enforced by legality's seat check.
            spec["opponents_only"] = True
        if targets.get("damaged_by_source"):
            # "…**previously dealt damage by it**" (Diseased Vermin). Carried to
            # the same seat loop for the same reason the two flags above are: it
            # is the picker that enforces a printed narrowing, and an ability
            # whose restriction stops at the parser is one that hits anybody.
            spec["damaged_by_source"] = True
        return spec
    if kind == "player_or_planeswalker":
        # Chandra's Magmutt: player faces plus planeswalker permanents — the
        # "any" picker minus its creature half.
        spec = {"kind": "player_or_planeswalker"}
        if targets.get("opponents_only"):
            # "Target **opponent** or planeswalker" (Eternal Flame): the same
            # union with the caster's own seat struck out (CR 115.4), carried on
            # the same flag the plain player picker above reads. Legality's seat
            # loop already asks it for this kind; without it here the flag never
            # reaches the loop and the caster is offered as a legal target.
            spec["opponents_only"] = True
        return spec
    if kind == "spell":
        # A spell on the stack, which the UI picks from a different zone than
        # any permanent — "stack" is the name for that picker.
        return {"kind": "stack"}
    if kind != "object":
        return None
    filt = targets.get("filter") or {}
    # A description whose slots are *differently* restricted carries one filter
    # per slot. The picker enumerates one legal set for all of them, so a
    # narrowing may only be applied to that set when **every** slot has it —
    # otherwise the flag hides a target one slot legitimately admits, which is
    # what kept Garruk, Savage Herald's -2 from ever biting an opponent's
    # creature. Per-slot legality is the handler's, and it already enforced it.
    slot_filters = targets.get("filters")
    if isinstance(slot_filters, list) and len(slot_filters) > 1:
        per_slot = [_narrowing_flags(slot or {}) for slot in slot_filters]
        flags = {
            key: value
            for key, value in per_slot[0].items()
            if all(other.get(key) == value for other in per_slot[1:])
        }
    else:
        flags = _narrowing_flags(filt)
    # "Up to N target …", N > 1. The picker has to know the maximum, or it would
    # collect one target for a spell that names several — which is what the
    # instruction's own lowering refuses to emit until a handler reads a list.
    # Absent for every one-target description, so nothing downstream has to
    # special-case the common shape.
    count = targets.get("count")
    if isinstance(count, int) and count > 1:
        flags = {**flags, "max_targets": count}
        # "Exile **two** target artifacts" (Dust to Dust) against "Return **up
        # to two**" (Sanguine Indulgence): CR 601.2c lets the second announce
        # fewer and does not let the first, and the grammar has told the two
        # apart since it parsed them — `quantifier` is "exactly" or "up_to".
        # The spec dropped the distinction and reported both as a maximum, so
        # the picker offered "up to 2" for a card that prints a number.
        if targets.get("quantifier") == "exactly":
            flags = {**flags, "exact_targets": True}
        if targets.get("same_controller"):
            # "Choose two target creatures **controlled by the same
            # opponent**." (Retribution, CR 601.2c.) A relation over the whole
            # announcement, which is why it travels beside ``max_targets``
            # rather than inside the per-candidate filter: enumerating
            # candidates one at a time can never see it, and the gate that
            # checks what the caster *named* is where it is answered.
            flags = {**flags, "same_controller": True}
    elif isinstance(count, dict):
        # "Destroy target artifact. **For each additional {1}{R} you paid**,
        # destroy another target artifact…" (Primitive Justice). CR 601.2c fixes
        # the number of targets as the spell is announced, and here that number
        # is a function of the CR 601.2b payment announced one step earlier — so
        # there is no maximum to write down, only the arithmetic. Carried whole,
        # for the reason `x_targets` is a flag rather than a number one branch
        # down: how many the caster may name depends on what they announce, and
        # this spec is built from the card alone.
        #
        # The picker resolves it through `oracle_types.cost_target_count`, the
        # same reader `legality.cast_target_refusal` gates the announcement
        # with — a second arithmetic would be a picker offering a count the
        # engine then refuses.
        flags = {**flags, "cost_targets": count, "exact_targets": True}
        if targets.get("distinct"):
            # The printed "**another**" (CR 601.2c). Beside the count rather
            # than inside the per-candidate filter for `same_controller`'s
            # reason: it is a relation over the whole announcement, and an
            # enumeration that looks at one candidate at a time can never see
            # it.
            flags = {**flags, "distinct_targets": True}
    elif count == "x":
        # "**X** target creatures" (Part Water, Winter Blast). The count is the
        # announced X, so there is no number here to be a maximum — and saying
        # nothing at all left the picker on its one-target default, which is
        # how Winter Blast came to tap a single creature in the browser while
        # its handler had read a list since round 23. Reported as a flag rather
        # than a number: how many the caster may name depends on what they can
        # pay, which is knowable at the picker and nowhere earlier.
        flags = {**flags, "x_targets": True}
    elif targets.get("unbounded"):
        # "One or more target creatures" names no maximum. `legality.py` turns
        # this into a `max_targets` once it knows how many legal targets exist,
        # which is the same route Drafna's Restoration's "any number of" takes.
        flags = {**flags, "unbounded_targets": True}
    type_filter = filt.get("type_filter")
    if not type_filter:
        # "X target **Mountains**" (Volcanic Eruption) prints no card type at
        # all — but CR 205.3i puts every land subtype on lands and nothing
        # else, so a bare land-subtype filter is a land target and the picker
        # should offer lands, not every permanent. The subtype itself is still
        # enforced by the gate and the handler, exactly as Avalanche's snow
        # supertype is: the spec is the picker's hint, and the engine re-checks
        # the announcement against the whole filter either way.
        subtype = filt.get("subtype_filter")
        if isinstance(subtype, str):
            from .grammar.vocabulary import LAND_TYPES

            if subtype in LAND_TYPES:
                return {"kind": "land", **flags}
        # A targeted object with no type restriction is any permanent.
        return {"kind": "permanent", **flags}
    derived = _kind_for_type_filter(type_filter)
    return {"kind": derived, **flags} if derived is not None else None


def spec_only_subtype(spec: dict | None) -> str | None:
    """The one permanent subtype *spec* restricts its targets to, or None.

    "Can this spell target **only** Walls?" — the question Wall of Shadows asks
    of whatever is aiming at it (CR 115.1a: the target description is the phrase
    after "target"). It is a question about the *target description*, not about the source, so it is answered here, where the
    description was derived, rather than by a second reading of the source's
    oracle text.

    ``wall_only`` is ``_narrowing_flags``' own name for a Wall subtype filter,
    so this reads that flag rather than the payload it came from: a caller
    holding a spec holds the flag and not the filter, and inventing a second
    route to the same fact is how the picker and the restriction come to
    disagree. The generic ``filter`` branch is what a spec carrying its whole
    narrowing (``_from_instructions``' line-502 form) answers from, so a subtype
    that later grows a flag of its own needs nothing here.
    """
    if not spec:
        return None
    if spec.get("wall_only"):
        return "wall"
    described = spec.get("filter")
    if isinstance(described, dict):
        subtype = described.get("subtype_filter")
        if isinstance(subtype, str):
            return subtype
    return None


def bounce_subject_filter(payload: dict) -> dict:
    """What "Return target <noun> to its owner's hand" named, as a filter.

    One reading for the cast gate, because the payload spells the subject two
    ways and neither is the whole answer on its own: a several-target bounce
    ("up to two target creatures") describes its slots under ``targets``, while
    a one-target narrowed bounce carries ``filter``. A bare payload is
    Unsummon's, whose noun was "creature" — the default every other reader of
    this instruction kind already assumes.

    Read by the cast-time target gate and by the AI's "is this worth casting?"
    check, so neither of them re-reads the printed noun: it was ``is_creature``
    in one and ``primary_type == "creature"`` in the other, which is Unsummon's
    noun standing in for Boomerang's and Flash Flood's.
    """
    targets = payload.get("targets")
    if isinstance(targets, dict) and isinstance(targets.get("filter"), dict):
        return targets["filter"]
    described = payload.get("filter")
    if isinstance(described, dict):
        return described
    return {"type_filter": "creature"}


# The one spec kind whose chosen index is *not* a battlefield slot. Named
# rather than spelled out at each reader, because "is this index a graveyard
# index?" is asked in five places and a sixth that forgets is a spell reading a
# battlefield it never targeted.
GRAVEYARD_TARGET_KIND = "graveyard_creature"


def graveyard_target_spec(
    card, program, *, mode_index: int | None = None, instruction=None
) -> dict | None:
    """The spec of a chosen index that addresses a **graveyard**, else None.

    A card in a graveyard is not a permanent (CR 115.2) and the index that names
    it is a slot in a different list, so every reader that treats
    ``target_permanent_index`` as a battlefield slot has to ask this first. It
    used not to be asked at all: the cast-time protection check reads
    ``target.battlefield[slot]`` unconditionally, so Raise Dead naming graveyard
    slot 1 was refused because a White Knight happened to sit in battlefield
    slot 1 (CR 702.16b applied to a permanent the spell never targeted).

    Three callers, three ways of naming the same question — a spell
    (``derive_cast_spec``), one mode of a modal spell, and an ability or trigger
    that carries its own instruction. All three end at the same table, because
    what an instruction targets does not depend on what produced it.
    """
    if instruction is not None:
        spec = _from_instructions((instruction,))
    elif (
        mode_index is not None
        and program.modes
        and 0 <= mode_index < len(program.modes)
        and program.modes[mode_index].instruction is not None
    ):
        spec = _from_instructions((program.modes[mode_index].instruction,))
    else:
        spec = derive_cast_spec(card, program)
    if spec is not None and spec.get("kind") == GRAVEYARD_TARGET_KIND:
        return spec
    return None


def derive_activation_spec(ability) -> dict | None:
    """What *ability* chooses when it is activated, or None when it chooses
    nothing (CR 602.2b).

    Per ability rather than per card, and that is the whole difference from the
    cast side: a spell picks its targets once, while a permanent may carry
    several abilities that pick differently — Pyramids destroys an Aura with
    one and shields a land with the other, and classifying the *card* can only
    give one answer to a question with two.

    None is a positive answer ("this ability targets nothing"), not an absence,
    for the same reason it is on the cast side: the guard in
    `tests/engine/test_activation_targeting.py` fails if an ability whose line
    names a target answers None, so a parser change cannot turn a missing
    derivation into a silently target-free ability.
    """
    if not getattr(ability, "supported", False):
        return None
    instruction = getattr(ability, "instruction", None)
    if instruction is None:
        return None
    # A choosable cost is announced at CR 602.2b and the *instruction* cannot
    # describe it: the instruction is the effect, and the payment comes from
    # somewhere no effect here names. So it is derived from the cost and the two
    # answers are combined rather than one shadowing the other.
    cost_spec = _cost_picker_spec(getattr(ability, "cost", None))
    target_spec = _from_instructions((instruction,))
    if cost_spec is None:
        return target_spec
    # Diamond Valley's effect *is* its cost — the handler performs the sacrifice
    # — so the instruction's own spec already is the cost picker, and adding a
    # second would ask twice for one creature.
    if target_spec is not None and (
        target_spec.get("sacrifice_cost") or target_spec.get("discard_cost")
    ):
        return target_spec
    if target_spec is None:
        return cost_spec
    # Dwarven Weaponsmith: a real target *and* a cost, which CR 601.2c and
    # CR 601.2b make two separate announcements carrying two separate fields.
    # One spec cannot be both, so the cost rides beside the target under its own
    # key and the client runs two prompts — overloading one field is how the
    # cost came to eat the creature the ability was aimed at.
    return {**target_spec, "cost_spec": cost_spec}


def usable_activated_abilities(program):
    """The activated abilities of *program* the engine can actually run.

    An unsupported ability, or one that compiled to no instruction, is not
    activatable — so it is not offered a target prompt, and it is not counted
    when the web layer indexes a permanent's abilities. Shared so the index the
    UI sends back means the same ability the engine derived a spec for.
    """
    return [
        ability for ability in program.activated_abilities
        if ability.supported and ability.instruction is not None
    ]


# ---------------------------------------------------------------------------
# What an object already *on* the stack announced (CR 115.9)
# ---------------------------------------------------------------------------

#: The cast-spec kinds whose announced target can be a **player's face**. A
#: spell whose spec is anything else chose an object, so it is never "a spell
#: whose single target is a player" however its stack item happens to be
#: filled in.
_PLAYER_TARGET_SPEC_KINDS = frozenset({
    "player", "any", "player_or_planeswalker", "divided",
})


def stack_object_mana_value(item) -> int:
    """The mana value of a spell on the stack (CR 202.3, CR 202.3b).

    The printed cost, **plus** whatever X was announced for each ``{X}`` in it:
    CR 202.3b says that while a spell is on the stack, an X in its mana cost is
    the chosen value, so Fireball cast for X=3 has mana value 4 and not 1. That
    is the whole difference from ``handlers/zones._mana_value_of``, which asks
    about a card in a graveyard — a zone where CR 107.3g pins X at 0.

    One reader, because the number is asked by things that must agree: a cost
    the card defines from it (Reflecting Mirror) and a counter that compares it
    against a chosen X (Spell Blast).
    """
    card = getattr(item, "card", None)
    if card is None:
        return 0
    base = int(getattr(card, "cmc", 0) or 0)
    x_symbols = (getattr(card, "mana_cost", "") or "").lower().count("{x}")
    if not x_symbols:
        return base
    return base + x_symbols * int(getattr(item, "x_value", 0) or 0)


#: The cast-spec kinds whose announced target is an **object on the
#: battlefield**. Derived from the table that turns a printed type filter into
#: a picker rather than listed a second time, so a new noun phrase reaches this
#: reader for free; "any target" and "player or planeswalker" join it because
#: either may have been aimed at an object rather than at a face.
_PERMANENT_TARGET_SPEC_KINDS = frozenset(_TYPE_FILTER_TO_KIND.values()) | {
    "any", "player_or_planeswalker",
}


def _lone_permanent_target(game, item) -> int | None:
    """The single battlefield object *item* announced, **by identity**, or None.

    Identity rather than slot for CR 400.7's reason: the index recorded at cast
    time is a position in a battlefield list, and anything leaving in between
    renumbers every later slot. The id is preferred and the index is only the
    fallback for an item nothing stamped.

    A target that has since **left** still answers with its id. CR 115.9a counts
    what was chosen as the object was put on the stack, not what is still legal
    — and CR 115.7a is explicit that a target may be changed "even if the
    original target is itself illegal by then", so a spell whose creature died
    is exactly the spell a retarget is for.
    """
    ids = getattr(item, "target_permanent_id", None)
    if ids is not None:
        chosen = list(ids) if isinstance(ids, (list, tuple)) else [ids]
        if len(chosen) != 1 or not isinstance(chosen[0], int):
            return None
        return int(chosen[0])
    idxs = getattr(item, "target_permanent_index", None)
    if idxs is None:
        return None
    chosen = list(idxs) if isinstance(idxs, (list, tuple)) else [idxs]
    if len(chosen) != 1 or not isinstance(chosen[0], int):
        return None
    seat = getattr(item, "target_player_index", None)
    if seat is None or not (0 <= seat < len(game.players)):
        return None
    # The one sanctioned direction for an index: through the seam's bridge,
    # once, and carried as an id from here on.
    found = game.permanent_at(seat, chosen[0])
    return None if found is None else game.permanent_id_of(found)


def spell_targets(game, item) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Every seat and every permanent a spell on the stack chose (CR 601.2c).

    ``(seats, permanent_ids)``. :func:`single_spell_target`'s question without
    the CR 115.9a count on it: that one answers "what is this spell's *only*
    target", for a retarget that has to know there is just one, and refuses
    everything it cannot be certain about. This one answers "what did it point
    at at all", which is what a trigger watching for a spell aimed at its
    controller asks (Reparations), and it is allowed to name several.

    The two hazards are the ones that function documents, met the same way:

    * ``target_player_index`` is a **battlefield** beside a permanent index, not
      a target, so a seat is believed only when the card's compiled program says
      the spell can target a player at all. Read the field regardless and
      Reparations would draw off every removal spell pointed at anybody.
    * a **divided** spell records each of its targets separately, so both kinds
      are read out of that record rather than off the two scalar fields.

    Permanent targets are taken by id from the same stamp
    ``_announce_targeting`` reads, because a slot renumbers (CR 400.7) and the
    ids are settled before any trigger is announced.
    """
    from .oracle import compile_card_oracle

    card = getattr(item, "card", None)
    if card is None or getattr(item, "ability_instruction", None) is not None:
        return (), ()
    seats: list[int] = []
    permanents: list[int] = []
    living = range(len(game.players))

    divided = (getattr(item, "choices", None) or {}).get(DIVIDED_TARGETS)
    if divided:
        for entry in divided:
            seat, permanent_index, _share = divided_entry(entry)
            if permanent_index is None:
                if int(seat) in living and int(seat) not in seats:
                    seats.append(int(seat))
                continue
            found = game.permanent_at(int(seat), permanent_index)
            if found is not None and found.permanent_id not in permanents:
                permanents.append(found.permanent_id)
        return tuple(seats), tuple(permanents)

    ids = getattr(item, "target_permanent_id", None)
    for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
        if isinstance(permanent_id, int) and permanent_id not in permanents:
            permanents.append(permanent_id)
    if permanents:
        return (), tuple(permanents)

    seat = getattr(item, "target_player_index", None)
    if seat is None or seat not in living:
        return (), ()
    spec = derive_cast_spec(card, compile_card_oracle(card))
    if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
        return (), ()
    if spec.get("land_filter"):
        # Volcanic Eruption's "X target Mountains": the seat beside them is a
        # battlefield, exactly as it is above.
        return (), ()
    return (int(seat),), ()


def single_spell_target(game, item) -> dict | None:
    """What a spell on the stack chose as its **only** target (CR 115.9a /
    CR 115.9c), or None when it chose several, chose something this engine
    cannot re-aim, or the count cannot be established.

    ``{"kind": "player", "seat": n}`` or ``{"kind": "permanent",
    "permanent_id": n}`` — a descriptor rather than a bare seat, because the two
    answers are the same question ("what is this spell's one target?") and a
    reader that could only say "player" is a reader Deflection cannot use.

    "Target spell with a single target" is asked twice of every card that
    prints it — by the picker in front of the cast and by the handler at
    resolution — so it is one function.

    **None is a refusal, not "no".** CR 115.9a counts what was chosen as the
    object was put on the stack, and this engine's stack item cannot always
    say: a seat and a chosen player reach it through the same
    ``target_player_index`` (which is why "every target is illegal" is not
    answerable for player-targeted spells, ROADMAP), and a modal spell's
    targets belong to the mode rather than to the card. Where the count cannot
    be established the spell is simply not offered — an under-offer is a
    narrower card, while an over-offer is a card redirecting spells it was
    never allowed to.

    So every way of *not* being a lone player target is checked first, and only
    then is the seat believed:

    * an **ability** on the stack has no card and is not a spell (CR 113.7a);
    * a **graveyard** card or another **stack object** rules the question out at
      once: neither is a target this engine's retarget can offer a replacement
      for, and an under-offer is a narrower card while an over-offer is a card
      re-aiming spells it was never allowed to;
    * a **modal** spell announces its targets per mode (CR 115.8, CR 700.2), and
      ``derive_cast_spec`` answers about mode 0 alone;
    * a **divided** spell records every target it chose in ``divided_targets``,
      so the count is read there and a face is the only single answer;
    * and the card itself has to be one that *can* target the kind of thing its
      stack item is filled in with, asked of the compiled program rather than
      inferred from the field being set — a seat and a chosen player reach the
      item through the same ``target_player_index``, and beside a permanent
      index that field is a *battlefield* rather than a target.
    """
    if getattr(item, "ability_instruction", None) is not None:
        return None
    card = getattr(item, "card", None)
    if card is None:
        return None
    if getattr(item, "chosen_modes", ()) or getattr(item, "chosen_mode_index", None) is not None:
        return None
    if getattr(item, "target_graveyard_card", None) is not None:
        return None
    if getattr(item, "target_stack_item", None) is not None:
        return None

    seats = range(len(game.players))
    divided = (getattr(item, "choices", None) or {}).get(DIVIDED_TARGETS)
    if divided:
        if len(divided) != 1:
            return None
        seat, permanent_index, _share = divided_entry(divided[0])
        if permanent_index is not None:
            # A divided *object* target. CR 115.7f keeps the division, so the
            # share would have to travel to the new permanent — and the entry
            # records a battlefield slot rather than an id, which is the one
            # shape ``_lone_permanent_target`` cannot answer by identity.
            return None
        return {"kind": "player", "seat": int(seat)} if int(seat) in seats else None

    from .oracle import compile_card_oracle

    if item.target_permanent_index is not None or item.target_permanent_id is not None:
        permanent_id = _lone_permanent_target(game, item)
        if permanent_id is None:
            return None
        spec = derive_cast_spec(card, compile_card_oracle(card))
        if spec is None or spec.get("kind") not in _PERMANENT_TARGET_SPEC_KINDS:
            return None
        if spec.get("unbounded_targets") or spec.get("max_targets") not in (None, 1):
            return None
        return {"kind": "permanent", "permanent_id": permanent_id}

    seat = item.target_player_index
    if seat is None or seat not in seats:
        return None

    spec = derive_cast_spec(card, compile_card_oracle(card))
    if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
        return None
    if spec.get("land_filter"):
        # Volcanic Eruption's "X target Mountains" is a divided spell whose
        # targets are permanents; the seat beside them is a battlefield.
        return None
    if spec.get("max_targets") not in (None, 1):
        return None
    return {"kind": "player", "seat": int(seat)}


def single_player_target(game, item) -> int | None:
    """The one **player** a spell on the stack chose as its only target, or
    None (CR 115.9a / CR 115.9c).

    Reflecting Mirror's half of :func:`single_spell_target`: "if that target is
    you" is a question only a face can answer, so an object target is not "no"
    with a seat beside it — it is simply not this question's answer.
    """
    chosen = single_spell_target(game, item)
    if chosen is None or chosen.get("kind") != "player":
        return None
    return int(chosen["seat"])


#: Every printed way a card hands its caster a choice as it is cast.
#:
#: Deliberately *looser* than the target-word probes above, because the two
#: directions ask opposite questions. "This card targets — does it derive a
#: prompt?" has to be sure the word means a cast target; "this card derives a
#: prompt — is there anything on it to choose?" hands the card back to its twin
#: on any choosing word at all. A card with none of these words that still
#: derives a picker is asking a question its own text never poses.
#:
#: "of your choice" is CR 609.3's choice (Circle of Protection, Reverse
#: Damage), and "card in a graveyard" / "card from your graveyard" is a card
#: picked out of a zone (Animate Dead's CR 115.1b enchant line, Experimental
#: Overload's return) — neither is the word "target" and both are real prompts.
_CAST_CHOOSER = re.compile(
    r"\btargets?\b|\bof your choice\b|\bchoose\b|\bchosen\b"
    r"|card in a graveyard|card from your graveyard"
)


def card_names_a_chooser(card, program) -> bool:
    """Whether anything about *card* asks its caster to pick something.

    The evidence sources :func:`derive_cast_spec` consults, asked of the *card*
    rather than of the derivation, plus the printed words above. A card that
    answers False here has nothing for a cast picker to be about.

    One function with two readers, on purpose: the ratchet in
    ``tests/engine/test_targeting.py`` (no card derives a prompt its text never
    asks for) and ``scripts/picker_sweep.py`` (the same sweep runnable over a
    measured set during Phase 3). A private copy in either would let the
    script's census and the shipped-pool ratchet drift apart.
    """
    from engine.cast_costs import additional_costs
    from engine.enter_effects import copy_on_enter_type

    if _CAST_CHOOSER.search(_REMINDER_TEXT.sub("", card.oracle_text or "").lower()):
        return True
    if card_enchant_subject(card.oracle_text) is not None:
        return True                                     # CR 115.1b
    if copy_on_enter_type(program.normalized_text or "") is not None:
        return True                                     # CR 707.9a
    return any(
        _cost_picker_spec(cost) is not None for cost in additional_costs(card)
    )


# A cast line that picks a target as the spell resolves. Reminder text is
# stripped by callers first: protection's "(… can't be blocked, **targeted**,
# dealt damage …)" is describing what may not happen to the creature, not
# something the card chooses. Triggered-ability lines are excluded because
# their target is chosen when the trigger goes on the stack (CR 603.3d), not as
# the permanent is cast — Erhnam Djinn's upkeep forestwalk grant is not a
# cast-time prompt. The optional "until …," in front is a **delayed** triggered
# ability saying how long it is armed (CR 603.7a) before it says when it fires
# (Gaze of Pain). Deliberately a *prefix* and not a search: eight shipped cards
# print a trigger word mid-line after a real cast target (Berserk, Mana Drain,
# Reincarnation, the three Glyphs, Sacred Boon, Ray of Command), and every one
# of those lines opens with the cast effect that does the targeting.
_TRIGGER_PREFIX = re.compile(
    r"^\s*(?:until [^,]{1,40}, )?(when|whenever|at the beginning)\b"
)
_TARGET_WORD = re.compile(r"\btargets?\b")

# Line shapes whose target is not a *cast* target, each excluded for the reason
# the trigger prefix above is. `legality._cast_lines` cannot drop them: it
# splits on the activated-ability cost syntax, which none of these has.
#
# * A **loyalty ability** ("+1:", "−3:") is activated (CR 606.3), so its target
#   is chosen when the ability goes on the stack — `derive_activation_spec`
#   answers for it.
# * A **modal bullet** is one alternative, and a mode derives its own spec;
#   the card as a whole names no single target ("Choose one" means exactly
#   that).
# * A **static cost tax** that says "spells your opponents cast that **target**
#   this creature cost more" (Pursued Whale) uses the word about somebody
#   else's spell.
# * A **shroud-shaped restriction** ("can't be the target of Aura spells",
#   Bartel Runeaxe) says what somebody else's spell may not do.
# * A **static effect keyed on what another object targeted** — Bronze Horse's
#   "prevent all damage … by spells that target it", Wall of Shadows'
#   "abilities that can target only Walls".
_LOYALTY_PREFIX = re.compile(r"^\s*[+−-]?\s*[0-9x]+\s*:", re.I)
_MODAL_BULLET = re.compile(r"^\s*•")
_TAXES_TARGETING_SPELLS = re.compile(r"spells .*that target .*cost")
_CANT_BE_TARGETED = re.compile(r"can't be the target of")
_OTHERS_TARGETING = re.compile(r"(?:spells|abilities)[^.]*? that (?:can )?target")


def line_names_a_cast_target(line: str) -> bool:
    """Whether *line* names a target the caster chooses as the spell is cast.

    One probe with two readers: the forward ratchet in
    ``tests/engine/test_targeting.py`` (every card that targets as it is cast
    derives its own prompt) and ``scripts/picker_sweep.py``, which asks the
    same question of a measured set during Phase 3. The exclusions above are
    each a way to make the ratchet pass by looking at less, so the test also
    asserts the size of the examined set.
    """
    if not _TARGET_WORD.search(line):
        return False
    return not (
        _TRIGGER_PREFIX.match(line)
        or _LOYALTY_PREFIX.match(line)
        or _MODAL_BULLET.match(line)
        or _TAXES_TARGETING_SPELLS.search(line)
        or _CANT_BE_TARGETED.search(line)
        or _OTHERS_TARGETING.search(line)
    )


def cast_picker_expected(card, program) -> bool:
    """The forward question the picker sweep asks: should casting this card
    raise a picker?

    :func:`line_names_a_cast_target` over the cast-relevant lines, plus the
    three evidence sources that choose without the word "target" — an Aura's
    enchant subject (CR 115.1b: Roots, the card this instrument exists for,
    prints no "target" at all), a copy-on-enter phrase (CR 707.9a), and an
    additional cost with a picker. Strictly stronger than the forward ratchet's
    own composition, which reads only the printed lines — the enchant half is
    exactly what let Roots ship uncastable.
    """
    from engine.cast_costs import additional_costs
    from engine.enter_effects import copy_on_enter_type
    from engine.legality import _cast_lines

    if any(
        line_names_a_cast_target(_REMINDER_TEXT.sub("", line))
        for line in _cast_lines(card)
    ):
        return True
    if card_enchant_subject(card.oracle_text) is not None:
        return True                                     # CR 115.1b
    if copy_on_enter_type(program.normalized_text or "") is not None:
        return True                                     # CR 707.9a
    return any(
        _cost_picker_spec(cost) is not None for cost in additional_costs(card)
    )
