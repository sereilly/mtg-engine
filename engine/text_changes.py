"""Single write API for text-changing effects (CR 612, CR 613 layer 3).

A text-changing effect rewrites *words* in an object's printed characteristics:
Sleight of Mind swaps a colour word, Magical Hack swaps a basic land type
"replacing all instances" of it. CR 613.1c applies them in layer 3 — before
anything reads the text — and CR 613.7 orders them by timestamp.

**Timestamps are load-bearing here, because text changes do not commute.**
Recording black -> red and then red -> black leaves every one of those words
reading "black"; the same two effects in the other order leave them all reading
"red". The engine used to merge both into one substitution table, which
produces a *third* answer — a swap — that neither order gives. One entry per
effect, applied oldest first, is what makes the question answerable at all.

Within *one* effect the substitutions are simultaneous: a single pass over one
alternation, whole words only. That is what stops an effect naming two words
from collapsing them into one, and what stops "red" rewriting the "red" inside
"requi**red**".

What a text change rewrites is the object's rules text, the text in its type
line (CR 612.1) and the keyword list parsed off them — never its name
(CR 612.2). An ability *granted* by another effect is not part of the object's
text and is not rewritten (CR 612.3); it is added in layer 6, after this.

Removal is dropping a contribution: nothing here remembers a delta, so nothing
can fall out of step with what was recorded. Reading is
``Permanent.effective_card``, which folds the contributions once — the readers
(untap restrictions, cost taxes, protection colours, lord grants) never learn
that text can change.

A spell is an object too
------------------------

"Change the text of target **spell** or permanent" (Sleight of Mind, Magical
Hack, Crystal Spray, Alter Reality, Artificial Evolution) rewrites an object on
the stack, which has no metadata and no layers. Its records are the same
dicts, kept on ``StackItem.text_change_effects`` and written by the same three
writers (each takes a permanent or a stack object). A spell's ``card`` is two
things at once — the object every reader asks what it says, and the physical
card that goes to a graveyard as it leaves the stack — so the change cannot be
written *into* it. :func:`spell_text_card` is the first half, folded: **every
reader of what a spell on the stack says** (its compiled program at resolution,
the spec CR 608.2b re-asks its targets by, a retarget's candidates, its colour
and creature types) asks it, and ``item.card`` is left for identity and zone
moves. ``tests/engine/test_kg3_textspell_spell_text_reads.py`` holds every
stack-object ``.card`` read in ``engine/`` and ``web/`` to one side of that line.

CR 400.7a is :func:`carry_spell_text_changes`: the records go onto the
permanent the spell becomes with the timestamps and durations they were created
with, as ``color_changes.carry_spell_color_change`` carries a colour. A copy
drops them (CR 707.2: "text-changing effects … are not copied") because the
copy builders construct a fresh ``StackItem`` and the field starts empty.
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Iterable, Mapping

from .continuous import next_timestamp

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .models import CardDefinition, Permanent

# Key under which a permanent's ordered text changes live.
TEXT_CHANGE_EFFECTS = "text_change_effects"

# The kinds of word a text-changing effect in this pool names.
COLOR_WORD = "color_word"
LAND_WORD = "land_word"
#: A creature type (CR 205.3m) — Artificial Evolution. Its own kind because
#: its words have their own written forms (a plural that is not always "-s")
#: and because a creature type is the one vocabulary here that card *names*
#: are made of (CR 612.2: "Relentless Rats" keeps its name).
CREATURE_WORD = "creature_word"

#: The two words of "replacing all instances of **one creature type with
#: another**" (Artificial Evolution): the word replaced and its replacement,
#: each chosen as the spell resolves (the card's 2004-10-04 ruling, "You choose
#: the words to change on resolution") by a ``choose_creature_type`` step whose
#: ``result_key`` names one of these — resolution scratchpad records, the
#: ``oracle_types.CHOSEN_CREATURE_TYPE_THIS_WAY`` shape — and both read by the
#: ``mark_text_modified`` step behind them. Two keys rather than that one
#: twice, because the second answer must not overwrite the first: "It can't
#: change a word to the same word" is asked by comparing them.
TEXT_CHANGE_OLD_CREATURE_TYPE = "text_change_old_creature_type"
TEXT_CHANGE_NEW_CREATURE_TYPE = "text_change_new_creature_type"

COLOR_WORDS: dict[str, str] = {
    "W": "white", "U": "blue", "B": "black", "R": "red", "G": "green",
}

LAND_TYPE_WORDS: dict[str, str] = {
    "W": "plains", "U": "island", "B": "swamp", "R": "mountain", "G": "forest",
}


def _plural(land_type: str) -> str:
    """Plains is spelled the same singular and plural; the rest take an "s".

    The same trap as ``static_bonuses.singular_land_type`` from the other
    direction — appending "s" unconditionally produces "plainss", a word no card
    contains, so the plural rule would silently never fire.
    """
    return land_type if land_type == "plains" else f"{land_type}s"


#: Creature types whose plural is the word itself ("Other Merfolk get +1/+1",
#: "all Djinn"), beside the ``-folk`` family, which is read off the ending.
_INVARIANT_CREATURE_PLURALS = frozenset({
    "aurochs", "bison", "deer", "djinn", "elk", "fish", "kithkin", "kor",
    "moose", "samurai", "sheep", "squid", "viashino",
})

#: Creature types English pluralises irregularly.
_IRREGULAR_CREATURE_PLURALS = {
    "child": "children", "cyclops": "cyclopes", "fungus": "fungi",
    "homunculus": "homunculi", "mouse": "mice", "ox": "oxen",
    "pegasus": "pegasi",
}


def creature_type_plural(word: str) -> str:
    """The plural a card prints for the creature type *word* — "Elves",
    "Wolves", "Sphinxes", "Harpies", "Merfolk", "Goblins".

    Only what a text change needs: the form "replacing all instances" of a
    creature type has to reach beside the singular, and the form its
    replacement is written in. A form no card prints costs nothing — the
    pattern simply never matches.
    """
    word = word.lower()
    if word in _IRREGULAR_CREATURE_PLURALS:
        return _IRREGULAR_CREATURE_PLURALS[word]
    if word in _INVARIANT_CREATURE_PLURALS or word.endswith("folk"):
        return word
    if word.endswith(("lf", "rf")):
        return word[:-1] + "ves"
    if word.endswith("y") and word[-2:-1] not in ("a", "e", "i", "o", "u"):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def _forms(kind: str, old: str, new: str) -> tuple[tuple[str, str], ...]:
    """Every written form of one word swap, longest first.

    A basic land type is used as a bare word, pluralised, and compounded into a
    landwalk keyword — "replacing all instances" means all three. ``\\b`` does
    not reach inside "swampwalk": there is no word boundary after "swamp", so
    the bare pattern simply fails there and the keyword would survive a change
    that names it. Naming the compound is what covers it, and :func:`_compile`
    offers the longer form first so the alternation cannot stop at the prefix.

    "Plains" is the one word whose written form does not say which it is, so a
    plural entry for it would be the *same key* as the singular one. It is read
    as singular, because that is the reading that appears in a type line and
    changes what the land is; a plural "All Plains are …" would come out as
    "All Mountain are …", off by a letter and by nothing that matters to the
    rules. No permanent in this pool writes that phrase.
    """
    if kind == COLOR_WORD:
        # "**non**black" is an instance of the word "black", and Mind Bend's own
        # reminder text says so: "you may change 'nonblack creature' to
        # 'nongreen creature'". ```` does not reach inside the compound —
        # there is no word boundary between "non" and "black" — so the bare
        # pattern fails there and every ``non<colour>`` in the pool survived a
        # change that names it. Naming the compound covers it, exactly as
        # "swampwalk" is named below, and ``_compile`` offers the longer form
        # first so the alternation cannot stop at the prefix.
        return (
            (f"non{old}", f"non{new}"),
            (old, new),
        )
    if kind == CREATURE_WORD:
        # The singular and the plural: "Other **Elf** creatures" and "**Elves**
        # you control" are both instances of the word. An old word that is its
        # own plural (Merfolk) is read as the singular — the type line's
        # reading, and the one that changes what the creature is — for the
        # reason "Plains" is below.
        pairs = {old: new}
        if creature_type_plural(old) != old:
            pairs[creature_type_plural(old)] = creature_type_plural(new)
        return tuple(sorted(pairs.items(), key=lambda item: (-len(item[0]), item[0])))
    pairs = {f"{old}walk": f"{new}walk"}
    if _plural(old) != old:
        pairs[_plural(old)] = _plural(new)
    pairs[old] = new
    return tuple(sorted(pairs.items(), key=lambda item: (-len(item[0]), item[0])))


#: The one duration a text change may carry. CR 612 gives none by default —
#: which is what Magical Hack, Sleight of Mind and Mind Bend mean by "This
#: effect lasts indefinitely" — and Whim of Volrath is the first card in the
#: pool to print one. Kept as a constant rather than a bare string because the
#: lowering, the record and the sweep all have to spell it the same way, and a
#: record stamped with a duration the sweep does not recognise is an effect
#: printed to end that never does.
UNTIL_END_OF_TURN = "until_end_of_turn"


def _record_list(holder) -> list:
    """Where *holder*'s text changes are recorded: a permanent's metadata key,
    or a spell's ``StackItem.text_change_effects`` (which has no metadata).

    Told apart by the ``metadata`` dict a permanent has and a stack object does
    not — the probe ``object_colors`` makes with ``effective_colors``, for its
    reason: no import of either model is needed here.
    """
    metadata = getattr(holder, "metadata", None)
    if isinstance(metadata, dict):
        return metadata.setdefault(TEXT_CHANGE_EFFECTS, [])
    return holder.text_change_effects


def _record(
    perm, kind: str, old: str, new: str, *, label: str,
    duration: str | None = None,
) -> None:
    effects = _record_list(perm)
    record = {
        "kind": kind,
        "from": old,
        "to": new,
        # 613.7b: an effect is stamped when it is created.
        "timestamp": next_timestamp(),
        "label": label,
    }
    if duration is not None:
        # Absent for a permanent one, so every record written before Whim of
        # Volrath existed is byte-identical to what it was — which is what keeps
        # `changed_words`' payload and the web state stable for the three cards
        # that print no duration.
        record["duration"] = duration
    effects.append(record)
    # "This permanent's text was changed", written by the writer and only when
    # a change is recorded. ``mark_text_modified`` wrote it as soon as it found
    # its target, whatever the change then recorded, and the AI's rehearsal
    # reads a permanent's fields (``ai_rehearsal.position_digest``): a text
    # change that rewrote nothing read as a change, so an AI seat cast Magical
    # Hack, Sleight of Mind, Mind Bend, Crystal Spray, Whim of Volrath and
    # Alter Reality at its own Island with no words named — a card spent for
    # nothing, every game it drew one. A spell has no fields of that kind: the
    # permanent it becomes is stamped by :func:`carry_spell_text_changes`.
    metadata = getattr(perm, "metadata", None)
    if isinstance(metadata, dict):
        metadata["text_modified"] = True


def change_color_word(
    perm: Permanent, old_symbol: str, new_symbol: str, *, label: str = "",
    duration: str | None = None,
) -> bool:
    """Sleight of Mind: replace one colour word with another in *perm*'s text.

    Takes the mana symbols the cast records; the words are this module's
    business. Returns False when either symbol names no colour, or when they
    name the same one (the card's ruling: "Can't change a color word to the
    same color word"). *perm* may be a spell on the stack (its
    ``StackItem``), whose record :func:`spell_text_card` folds.
    """
    old = COLOR_WORDS.get((old_symbol or "").upper())
    new = COLOR_WORDS.get((new_symbol or "").upper())
    if not old or not new or old == new:
        return False
    _record(perm, COLOR_WORD, old, new, label=label, duration=duration)
    return True


def change_land_word(
    perm: Permanent, old_type: str, new_type: str, *, label: str = "",
    duration: str | None = None,
) -> bool:
    """Magical Hack: replace one basic land type with another in *perm*'s text.

    One effect, whatever the permanent is. On a land the word being rewritten is
    in the type line, so the land's subtypes change (and with them the mana
    ability CR 305.6 gives it); on a creature it is in the rules text, so
    "swampwalk" becomes "islandwalk" — including inside a lord's grant line.
    Both used to be separate branches with separate storage.
    """
    old = (old_type or "").strip().lower()
    new = (new_type or "").strip().lower()
    basics = set(LAND_TYPE_WORDS.values())
    # "It can't change a word to the same word" (the card's ruling).
    if old not in basics or new not in basics or old == new:
        return False
    _record(perm, LAND_WORD, old, new, label=label, duration=duration)
    return True


def change_creature_word(
    perm: Permanent, old_type: str, new_type: str, *, label: str = "",
    duration: str | None = None,
) -> bool:
    """Artificial Evolution: replace one creature type with another in
    *perm*'s text (CR 612) — its rules text and its type line, so a lord's
    "Other Elf creatures" and the creature's own "— Elf" both change.

    Returns False, recording nothing, when either word is no creature type
    (CR 205.3m) or the two are the same word (the card's ruling: "It can't
    change a word to the same word").
    """
    from .grammar.vocabulary import CREATURE_TYPES

    old = (old_type or "").strip().lower()
    new = (new_type or "").strip().lower()
    if old not in CREATURE_TYPES or new not in CREATURE_TYPES or old == new:
        return False
    _record(perm, CREATURE_WORD, old, new, label=label, duration=duration)
    return True


def text_changes(perm: Permanent) -> tuple[dict, ...]:
    """The recorded text changes, oldest first (CR 613.7).

    Recorded order is timestamp order: a text change is only ever appended, and
    ends only where the card printed a duration — which until Whim of Volrath no
    card in the pool did. :func:`apply_text_changes` sorts anyway, because it is
    the fold and the fold is where the order has to be right.
    """
    return tuple(perm.metadata.get(TEXT_CHANGE_EFFECTS) or ())


def end_until_eot_text_changes(perm: Permanent) -> bool:
    """Drop *perm*'s until-end-of-turn text changes. True if any went.

    Called by the cleanup step, and shaped like the gained-type sweep beside it
    rather than like a plain ``_EOT_METADATA_KEYS`` entry, for that sweep's
    reason: the key holds records of **two** lifetimes, and popping it whole
    would end Magical Hack's permanent rewrite with the turn.

    Dropping the contribution *is* the reversion (CR 611.3b): nothing here
    remembers a delta, so what the permanent reads afterwards is whatever
    contributions remain — including a later permanent change that was stacked
    on top of the one being dropped, which is why the fold is re-run rather than
    anything being restored.
    """
    recorded = perm.metadata.get(TEXT_CHANGE_EFFECTS)
    if not recorded:
        return False
    kept = [
        change for change in recorded
        if change.get("duration") != UNTIL_END_OF_TURN
    ]
    if len(kept) == len(recorded):
        return False
    if kept:
        perm.metadata[TEXT_CHANGE_EFFECTS] = kept
    else:
        # Popped rather than left empty, so ``has_text_changes``' fast path —
        # which nearly every rules query takes — goes back to answering False.
        perm.metadata.pop(TEXT_CHANGE_EFFECTS, None)
    return True


def has_text_changes(perm: Permanent) -> bool:
    """Whether any text-changing effect applies to *perm*.

    The fast path ``effective_card`` takes on nearly every rules query.
    """
    return bool(perm.metadata.get(TEXT_CHANGE_EFFECTS))


def spell_text_changes(item) -> tuple[dict, ...]:
    """The text changes recorded on the stack object *item*, oldest first.

    Empty for an ability (CR 113.3: not a spell, so no "target spell" names
    it), a copy (CR 707.2) and every spell nothing changed.
    """
    return tuple(getattr(item, "text_change_effects", None) or ())


def spell_text_card(item) -> "CardDefinition":
    """What the stack object *item* **says** — its card with every text change
    recorded on it applied, oldest first (CR 613.1c, 613.7).

    **The one reader of a spell's text on the stack.** Its compiled program at
    resolution, the spec CR 608.2b re-asks its targets by, the candidates a
    retarget offers, its creature types and colour: every one of them asks this
    and never ``item.card``, which is also the physical card that goes to a
    graveyard and must stay the printed one. Returns ``item.card`` itself when
    nothing changed it — the common path, which allocates nothing — so an
    ability (whose ``card`` is its source's, and which carries no record) reads
    exactly what it always read.
    """
    return spell_text_of(
        getattr(item, "card", None), getattr(item, "text_change_effects", None),
    )


def spell_text_of(card, changes) -> "CardDefinition":
    """What a spell whose printed card is *card* says under the recorded
    *changes* — :func:`spell_text_card` for a caller holding the two apart
    (``Game._resolve_card``, handed the stack object's card and record rather
    than the object). *card* itself when *changes* is empty."""
    if not changes or card is None:
        return card
    return apply_text_changes(card, changes)


def carry_spell_text_changes(changes, perm: "Permanent") -> bool:
    """CR 400.7a: a text change on a permanent spell goes on applying to the
    permanent the spell becomes. Returns whether there was one to carry.

    *changes* is the resolving spell's own record
    (``StackItem.text_change_effects``), handed over where the permanent is
    built and before it enters — so whatever reads its text as it arrives (an
    entry replacement, its own entry trigger, a lord's grant) reads the text it
    arrives with. Each record keeps its **timestamp** (CR 613.7b: when the
    effect was created, not when its object changed zones) and its
    **duration**, so Crystal Spray's "until end of turn" is swept by this
    turn's cleanup on the permanent as it would have been on the spell. The
    rulings for all five cards say it: "If you change the text of a spell
    which is to become a permanent, the permanent will retain the text change
    until the effect wears off."
    """
    records = [dict(change) for change in changes or ()]
    if not records:
        return False
    perm.metadata.setdefault(TEXT_CHANGE_EFFECTS, []).extend(records)
    perm.metadata["text_modified"] = True
    return True


def current_text_card(holder) -> "CardDefinition":
    """What *holder* — a permanent or a spell on the stack — says right now.

    A permanent's is ``effective_card`` (layer 1's copy, layer 3's changes,
    layer 6's grants); a spell's is :func:`spell_text_card`. For the readers
    that may be handed either: a text change asking whether the word it
    replaces is written on its target, and the default word it offers.
    """
    if isinstance(getattr(holder, "metadata", None), dict):
        return holder.effective_card
    return spell_text_card(holder)


def _changes_of(holder) -> tuple[dict, ...]:
    """The recorded changes of a permanent (:func:`text_changes`) or a spell
    (:func:`spell_text_changes`)."""
    if isinstance(getattr(holder, "metadata", None), dict):
        return text_changes(holder)
    return spell_text_changes(holder)


# ---------------------------------------------------------------------------
# Applying the recorded changes
# ---------------------------------------------------------------------------

# One compiled alternation per set of replacements. Small and bounded — five
# colour words and five land types swap into each other — and compiling the
# alternation on every characteristic read would be pure waste.
_COMPILED: dict[frozenset, tuple[re.Pattern, dict[str, str]]] = {}

# Folded cards, keyed by the base card's own identity fields (not ``id()``,
# which a freed temporary could hand to something else) and the sequence of
# changes applied. ``effective_card`` is read on nearly every rules query, so
# rebuilding a CardDefinition each time would be a per-call allocation on a hot
# path — and ``compile_card_oracle`` caches on the text, so a stable object
# keeps a text-changed card compiling exactly once.
_CHANGED_CARDS: dict[tuple, "CardDefinition"] = {}


def _compile(replacements: Mapping[str, str]) -> tuple[re.Pattern, dict[str, str]]:
    key = frozenset(replacements.items())
    built = _COMPILED.get(key)
    if built is None:
        # Longest first: the alternation is scanned left to right, so a form
        # that is a prefix of another must not be offered first.
        forms = sorted(replacements, key=lambda word: (-len(word), word))
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(form) for form in forms) + r")\b",
            re.IGNORECASE,
        )
        built = (pattern, dict(replacements))
        _COMPILED[key] = built
    return built


def one_pass(text: str, replacements: Mapping[str, str]) -> str:
    """Apply every replacement *at once*, in a single pass over one alternation.

    This is what makes one effect's substitutions simultaneous. Running them one
    after another instead would turn every black into red and then every red —
    including the ones just written — back into black, collapsing a swap into a
    single colour. Whole words only, so "red" leaves the "red" in "requi**red**"
    alone; capitalisation follows the word being replaced.
    """
    if not text or not replacements:
        return text
    pattern, table = _compile(replacements)

    def _sub(match: "re.Match") -> str:
        word = match.group(0)
        replacement = table[word.lower()]
        return replacement.capitalize() if word[:1].isupper() else replacement

    return pattern.sub(_sub, text)


def apply_text_changes(
    card: "CardDefinition", changes: Iterable[Mapping]
) -> "CardDefinition":
    """*card* with every change in *changes* applied, oldest first (CR 613.1c).

    Returns *card* itself when there is nothing to apply — the common path, and
    the reason this never allocates for a permanent no text change touches.
    """
    ordered = tuple(sorted(changes, key=lambda entry: int(entry.get("timestamp", 0))))
    if not ordered:
        return card

    signature = tuple((c["kind"], c["from"], c["to"]) for c in ordered)
    key = (card.name, card.type_line, card.oracle_text, card.keywords, signature)
    cached = _CHANGED_CARDS.get(key)
    if cached is not None:
        return cached

    type_line, oracle_text = card.type_line, card.oracle_text
    keywords = card.keywords
    for change in ordered:
        replacements = dict(_forms(change["kind"], change["from"], change["to"]))
        # The name is deliberately absent: CR 612.2 forbids a text change from
        # rewriting a card name even when the name contains the word.
        type_line = one_pass(type_line, replacements)
        if change["kind"] == CREATURE_WORD:
            # …and a creature type is what card names are *made of*, so the
            # names written inside the rules text are kept too: the card's own
            # ("Reckless One's power …") and any "named …" phrase ("cards named
            # Relentless Rats"). Only for this kind, so a colour or land-type
            # change folds byte for byte as it always has.
            oracle_text = _one_pass_outside_names(oracle_text, replacements, card.name)
        else:
            oracle_text = one_pass(oracle_text, replacements)
        keywords = tuple(one_pass(word, replacements) for word in keywords)

    changed = dataclasses.replace(
        card, type_line=type_line, oracle_text=oracle_text, keywords=keywords
    )
    _CHANGED_CARDS[key] = changed
    return changed


#: "…cards **named Relentless Rats**", "…a card named Hall of Gemstone": the
#: name a "named" phrase spells runs to the next punctuation.
_NAMED_PHRASE = re.compile(r"\bnamed [^.,;:()\"\n]+")


def _name_spans(text: str, name: str) -> list[tuple[int, int]]:
    """Where *text* spells a card name (CR 612.2): *name* itself, and whatever
    a "named" phrase names."""
    spans = [match.span() for match in _NAMED_PHRASE.finditer(text)]
    if name:
        spans += [match.span() for match in re.finditer(re.escape(name), text)]
    return sorted(spans)


def _one_pass_outside_names(
    text: str, replacements: Mapping[str, str], name: str,
) -> str:
    """:func:`one_pass` over *text* except where it spells a card name."""
    if not text:
        return text
    spans = _name_spans(text, name)
    if not spans:
        return one_pass(text, replacements)
    pieces: list[str] = []
    cursor = 0
    for start, end in spans:
        # Overlapping spans (the name inside a "named" phrase) are one
        # protected stretch.
        start = max(start, cursor)
        if end <= cursor:
            continue
        pieces.append(one_pass(text[cursor:start], replacements))
        pieces.append(text[start:end])
        cursor = end
    pieces.append(one_pass(text[cursor:], replacements))
    return "".join(pieces)


#: Every written form of every creature type, longest first, as one
#: alternation — what :func:`creature_types_written` scans with. Built on first
#: use: the catalog is the vocabulary package's, read once.
_CREATURE_FORMS: list = []


def _creature_forms() -> "tuple[re.Pattern, dict[str, str]]":
    if not _CREATURE_FORMS:
        from .grammar.vocabulary import CREATURE_TYPES

        forms: dict[str, str] = {}
        for word in sorted(CREATURE_TYPES):
            forms.setdefault(creature_type_plural(word), word)
        for word in CREATURE_TYPES:
            forms[word] = word
        ordered = sorted(forms, key=lambda form: (-len(form), form))
        pattern = re.compile(
            r"\b(" + "|".join(re.escape(form) for form in ordered) + r")\b",
            re.IGNORECASE,
        )
        _CREATURE_FORMS.append((pattern, forms))
    return _CREATURE_FORMS[0]


def creature_types_written(card: "CardDefinition") -> tuple[str, ...]:
    """The creature types written on *card* — its type line first, then its
    rules text outside any card name — in the order they appear, each once,
    singular.

    Exactly the words a creature-type text change could rewrite (the same
    forms :func:`_forms` reaches), so a default "word to replace" read from here
    is one that changes something.
    """
    pattern, forms = _creature_forms()
    text = card.oracle_text or ""
    found: list[str] = []
    for source, spans in (
        (card.type_line or "", []), (text, _name_spans(text, card.name)),
    ):
        for match in pattern.finditer(source):
            if any(start <= match.start() < end for start, end in spans):
                continue
            word = forms[match.group(0).lower()]
            if word not in found:
                found.append(word)
    return tuple(found)


# ---------------------------------------------------------------------------
# Views over the folded result
# ---------------------------------------------------------------------------


def _net_map(perm: Permanent, kind: str, vocabulary: Iterable[str]) -> dict[str, str]:
    """What each word of *vocabulary* reads as after every change of *kind*.

    Composed by running each word through the changes in order, which is the
    same fold ``apply_text_changes`` performs — not a merge of the entries,
    which is the thing that does not commute.
    """
    changes = [c for c in _changes_of(perm) if c.get("kind") == kind]
    result = {}
    for word in vocabulary:
        current = word
        for change in changes:
            if current == change["from"]:
                current = change["to"]
        result[word] = current
    return result


def changed_words(perm: Permanent) -> list[dict]:
    """``{"from": word, "to": word}`` for every word this permanent's — or
    this spell's — text now reads differently, for the UI's
    struck-out/replacement rendering.

    Derived from the fold rather than from the entries, so two changes that
    chain (black -> red, then red -> green) are reported as the one edit a
    player actually sees.
    """
    edits: list[dict] = []
    # The **bare** pair only, deliberately, where the land branch below lists
    # every written form. This is the renderer's list, and a colour compound
    # ("nonblack") is highlighted by the bare word inside it just as well —
    # where "mountainwalk" is not, because the land word is a prefix of a longer
    # keyword rather than a suffix of a longer adjective. The *applier* rewrites
    # both forms either way (``_forms``); this is only what is struck through.
    for old, new in _net_map(perm, COLOR_WORD, COLOR_WORDS.values()).items():
        if old != new:
            edits.append({"from": old, "to": new})
    # Every written form of a land word, because the renderer highlights by
    # matching the "from" word in the text and "mountainwalk" does not contain a
    # word boundary after "mountain".
    for old, new in _net_map(perm, LAND_WORD, LAND_TYPE_WORDS.values()).items():
        if old == new:
            continue
        edits.extend(
            {"from": form_old, "to": form_new}
            for form_old, form_new in _forms(LAND_WORD, old, new)
        )
    # Creature words (Artificial Evolution): the vocabulary is the whole
    # catalog, so the net map is taken over the words the changes name rather
    # than over every creature type — the same fold, run from each "from" word.
    creature_changes = [
        change for change in _changes_of(perm) if change.get("kind") == CREATURE_WORD
    ]
    starts: list[str] = []
    for change in creature_changes:
        if change["from"] not in starts:
            starts.append(change["from"])
    for word in starts:
        current = word
        for change in creature_changes:
            if current == change["from"]:
                current = change["to"]
        if current != word:
            edits.extend(
                {"from": form_old, "to": form_new}
                for form_old, form_new in _forms(CREATURE_WORD, word, current)
            )
    return edits


__all__ = [
    "COLOR_WORD", "COLOR_WORDS", "CREATURE_WORD", "LAND_TYPE_WORDS", "LAND_WORD",
    "TEXT_CHANGE_EFFECTS", "TEXT_CHANGE_NEW_CREATURE_TYPE",
    "TEXT_CHANGE_OLD_CREATURE_TYPE", "apply_text_changes",
    "carry_spell_text_changes", "change_color_word", "change_creature_word",
    "change_land_word", "changed_words", "creature_type_plural",
    "creature_types_written", "current_text_card", "has_text_changes",
    "one_pass", "spell_text_card", "spell_text_changes", "spell_text_of",
    "text_changes",
]
