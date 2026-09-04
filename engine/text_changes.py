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

# The two kinds of word a text-changing effect in this pool names.
COLOR_WORD = "color_word"
LAND_WORD = "land_word"

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
    pairs = {f"{old}walk": f"{new}walk"}
    if _plural(old) != old:
        pairs[_plural(old)] = _plural(new)
    pairs[old] = new
    return tuple(sorted(pairs.items(), key=lambda item: (-len(item[0]), item[0])))


def _record(perm: Permanent, kind: str, old: str, new: str, *, label: str) -> None:
    effects = perm.metadata.setdefault(TEXT_CHANGE_EFFECTS, [])
    effects.append(
        {
            "kind": kind,
            "from": old,
            "to": new,
            # 613.7b: an effect is stamped when it is created.
            "timestamp": next_timestamp(),
            "label": label,
        }
    )


def change_color_word(
    perm: Permanent, old_symbol: str, new_symbol: str, *, label: str = ""
) -> bool:
    """Sleight of Mind: replace one colour word with another in *perm*'s text.

    Takes the mana symbols the cast records; the words are this module's
    business. Returns False when either symbol names no colour.
    """
    old = COLOR_WORDS.get((old_symbol or "").upper())
    new = COLOR_WORDS.get((new_symbol or "").upper())
    if not old or not new:
        return False
    _record(perm, COLOR_WORD, old, new, label=label)
    return True


def change_land_word(
    perm: Permanent, old_type: str, new_type: str, *, label: str = ""
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
    if old not in basics or new not in basics:
        return False
    _record(perm, LAND_WORD, old, new, label=label)
    return True


def text_changes(perm: Permanent) -> tuple[dict, ...]:
    """The recorded text changes, oldest first (CR 613.7).

    Recorded order is timestamp order: a text change is only ever appended, and
    never ends — nothing in CR 612 gives one a duration, and none of the cards
    that make them do either. :func:`apply_text_changes` sorts anyway, because
    it is the fold and the fold is where the order has to be right.
    """
    return tuple(perm.metadata.get(TEXT_CHANGE_EFFECTS) or ())


def has_text_changes(perm: Permanent) -> bool:
    """Whether any text-changing effect applies to *perm*.

    The fast path ``effective_card`` takes on nearly every rules query.
    """
    return bool(perm.metadata.get(TEXT_CHANGE_EFFECTS))


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
        oracle_text = one_pass(oracle_text, replacements)
        keywords = tuple(one_pass(word, replacements) for word in keywords)

    changed = dataclasses.replace(
        card, type_line=type_line, oracle_text=oracle_text, keywords=keywords
    )
    _CHANGED_CARDS[key] = changed
    return changed


# ---------------------------------------------------------------------------
# Views over the folded result
# ---------------------------------------------------------------------------


def _net_map(perm: Permanent, kind: str, vocabulary: Iterable[str]) -> dict[str, str]:
    """What each word of *vocabulary* reads as after every change of *kind*.

    Composed by running each word through the changes in order, which is the
    same fold ``apply_text_changes`` performs — not a merge of the entries,
    which is the thing that does not commute.
    """
    changes = [c for c in text_changes(perm) if c.get("kind") == kind]
    result = {}
    for word in vocabulary:
        current = word
        for change in changes:
            if current == change["from"]:
                current = change["to"]
        result[word] = current
    return result


def changed_words(perm: Permanent) -> list[dict]:
    """``{"from": word, "to": word}`` for every word this permanent's text now
    reads differently, for the UI's struck-out/replacement rendering.

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
    return edits


__all__ = [
    "COLOR_WORD", "COLOR_WORDS", "LAND_TYPE_WORDS", "LAND_WORD",
    "TEXT_CHANGE_EFFECTS", "apply_text_changes", "change_color_word",
    "change_land_word", "changed_words", "has_text_changes", "one_pass",
    "text_changes",
]
