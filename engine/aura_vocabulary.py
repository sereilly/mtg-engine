"""The words an Aura's or an Equipment's printed lines are read with.

Every reader in the Aura family matches a printed line against the same few
fragments: the nouns an enchant clause can address, the word that names the
attached permanent ("enchanted" or "equipped", CR 301.5f), the five colours,
the protection qualities (CR 702.16a), the keywords an Aura may grant, and the
type-grant sentences two layers share. The support gate in ``engine/auras.py``
claims a line with them and ``aura_grants`` / ``aura_restrictions`` apply it
with them, so they are spelled once, here, beneath all three: a fragment two
readers spell separately is a gate and a grant reading two different
sentences, which is the failure this family exists to prevent.

Split out of ``engine/auras.py`` at the 2,000-line cap as the floor every
module split out of it imports. ``engine/auras.py`` imports all of those, so
left there each of their imports would be a cycle.
"""

from __future__ import annotations

import re


# The nouns an Aura's effect clause can address, from its "Enchant <noun>" line.
_NOUN = r"(?:creature|artifact|enchantment|land|wall|permanent)"

# "Enchanted creature" / "equipped creature" — the attached permanent, named by
# whichever word the card's own type uses. CR 301.5f: an ability referring to
# the "equipped creature" refers to whatever creature the permanent is attached
# to, and an Aura's "enchanted creature" is the same reference (CR 303.4). Both
# attach through the one record `attach_aura` writes, and the layer bridge
# derives the grant off the attached permanent's text either way — so every
# template in this family that describes a *continuous effect on the host*
# reads both words. The Aura-only shapes (control of the enchanted permanent, a
# land-type override, artifact animation) keep "enchanted": no Equipment prints
# them, and an Equipment that did would want its own reading, not a borrowed
# one.
_ATTACHED = r"(?:enchanted|equipped)"

_COLORS = "white|blue|black|red|green"
# Protection is restricted to the five colours on purpose. The engine's
# protection checks are colour-based, so "protection from everything" or
# "protection from Dragons" is not implemented — and a permissive
# `protection from [a-z]+` here would claim them, which is precisely the kind
# of over-broad entry that made "enchant creature" sufficient in the first
# place. Widen it when the check behind it widens, not before.
#: "protection from black **and from red**" (Mask of Law and Grace). CR 702.16g:
#: that clause is shorthand for **two** protection abilities, not one ability
#: with a compound quality -- which is why the conjunction is spelled once here
#: and split by :func:`aura_protection_colors` rather than being matched as an
#: opaque phrase.
#:
#: One alternation shared by the gate (``auras._TEMPLATES``) and the grant
#: (``aura_grants._PROTECTION_GRANT``), for this family's standing reason: the
#: sentence that decides whether the card is supported and the sentence that
#: decides what it does have to be the same sentence. Written as a name because
#: it is read from two patterns, which is exactly when a literal starts
#: drifting.
#:
#: "…protection from **each color among permanents you control**" (Pledge of
#: Loyalty). CR 702.16i: shorthand for one protection ability per colour in a
#: *set*, and here the set is read off a board — so it is a third alternative
#: beside a printed colour and a chosen one, resolved by the reader that holds
#: the Aura (:data:`AMONG_CONTROLLED_PROTECTION_COLORS`).
#:
#: "…protection from **enchantments**" (Tattoo Ward). The check behind this
#: alternation widened to every quality CR 702.16a names when the damage half
#: and the state-based sweep moved onto ``_protection_qualities``, so the four
#: permanent card types join the colours: the reader maps each printed word
#: through ``keywords.protection_qualities_named``, the one vocabulary a
#: printed line and a lord's grant are read with. Listed rather than `[a-z]+`
#: for the reason the colours were: a word nothing answers stays unclaimed.
_PROTECTION_CARD_TYPES = "artifacts|creatures|enchantments|lands"
_PROTECTION_QUALITY = (
    rf"(?:{_COLORS}|{_PROTECTION_CARD_TYPES}"
    r"|the chosen color|each color among permanents you control)"
)
_PROTECTION_QUALITIES = rf"{_PROTECTION_QUALITY}(?: and from {_PROTECTION_QUALITY})*"

_KEYWORDS = (
    r"flying|fear|first strike|double strike|trample|vigilance|haste|reach|"
    r"banding|defender|indestructible|swampwalk|forestwalk|islandwalk|"
    rf"mountainwalk|plainswalk|desertwalk|protection from (?:{_PROTECTION_QUALITIES})"
)

# "Enchanted creature gets +2/+2, has first strike, and is a Knight in addition
# to its other types." (Dub; Demonic Embrace prints the same shape.) Defined
# beneath the template table because three readers share it — the P/T, the
# keyword and the subtype each belong to a different CR 613 layer, and reading
# the line three times with three regexes is how one of the three gets dropped.
#
# The subtype alternation is the ingested vocabulary rather than `[a-z]+`, so
# the *gate* and the *grant* refuse the same words: a made-up type would
# otherwise be claimed here and then granted nothing, which is the shape this
# whole module exists to prevent.
class _LazyPattern:
    """A pattern compiled on first use rather than at import.

    ``engine.grammar.vocabulary`` is where the creature types live, and the
    grammar package reaches back into this family (``registries`` imports
    ``auras.aura_continuous_claim``, and ``auras`` imports this module) — so
    reading the vocabulary at import time is a cycle. Deferring it is the whole
    fix; nothing else about the pattern is unusual.
    """

    def __init__(self, build):
        self._build, self._compiled = build, None

    def match(self, text: str):
        if self._compiled is None:
            self._compiled = self._build()
        return self._compiled.match(text)


def _build_type_addition_grant() -> re.Pattern[str]:
    from .grammar.vocabulary import CREATURE_TYPES

    subtypes = "|".join(sorted(map(re.escape, CREATURE_TYPES), key=len, reverse=True))
    return re.compile(
        rf"^{_ATTACHED} {_NOUN} gets [+-]\d+/[+-]\d+, has (?P<keyword>{_KEYWORDS}), "
        rf"and is an? (?P<subtype>{subtypes}) in addition to its other types$"
    )


_TYPE_ADDITION_GRANT = _LazyPattern(_build_type_addition_grant)


def _build_creature_type_set() -> re.Pattern[str]:
    from .grammar.vocabulary import CREATURE_TYPES

    subtypes = "|".join(sorted(map(re.escape, CREATURE_TYPES), key=len, reverse=True))
    return re.compile(rf"^{_ATTACHED} creature is an? (?P<subtype>{subtypes})$")


#: "Enchanted creature **is a Flagbearer**." (Coalition Flag.) The sentence
#: ``_TYPE_ADDITION_GRANT`` reads minus its rider, and the rider is the whole
#: difference: CR 205.1b's "in addition to its other types" is what makes a
#: type an addition, and a sentence printing none of 205.1b's phrases *sets*
#: the subtype — CR 205.1a, "the new subtype(s) replaces any existing subtypes
#: from the appropriate set (creature types, …)". So a Human Soldier under the
#: Flag is a Flagbearer and nothing else, and stops being pumped by a Soldier
#: lord. Anchored at both ends so the additive sentence, a P/T half or a
#: condition never reads as this one; the type is held to CR 205.3m's list for
#: ``_TYPE_ADDITION_GRANT``'s reason — a made-up word would be claimed here and
#: then set nothing.
_CREATURE_TYPE_SET = _LazyPattern(_build_creature_type_set)


# Reminder text. `line_normalization.normalize_creature_line` strips it, but importing the
# compiler here would be a cycle (it imports `auras`, which imports this
# module), so the one-line
# equivalent lives here. Without it an anchored pattern silently stops matching
# every card whose printing carries a reminder — which is most of them.
_REMINDER = re.compile(r"\([^)]*\)")


def _line_text(raw_line: str) -> str:
    return " ".join(_REMINDER.sub("", raw_line).strip().lower().split()).rstrip(".")

# The keyword abilities an Aura grants while attached. Same treatment as the
# P/T grant: derived from the Aura's text on every recompute and stamped with
# its attach time, so removal is dropping a contribution rather than finding
# and undoing a recorded grant.
#
# Landwalk is included. It reaches the same layer-6 channel as every other
# keyword, so the combat check that consumes it must read *computed* abilities
# rather than the raw `has_<walk>` flag the imperative path used to stamp.
# **Derived from the engine's one keyword registry, not spelled beside it.**
# This was a hand-written tuple and it had drifted in both directions, which is
# the standing failure mode of a second copy: it listed "shadow", which nothing
# in this engine implements, so an Aura granting it would have been admitted
# with the evasion silently absent; and it omitted menace, lifelink,
# deathtouch, indestructible, flash, hexproof, prowess and rampage, so an Aura
# granting any of those was refused for a mechanic the engine has.
#
# The exclusions are the same three `lord_buffs.grantable_keywords` makes, and
# for the same reason: protection, landwalk and "bands with other" are family
# words whose printed form carries a quality ("protection from red"), which the
# comma/"and" splitting (`aura_grants._keyword_list`) would cut in half.
# Landwalk's *members*
# ("swampwalk", …) are ordinary entries and stay.
# Lazily, for the reason `_LazyPattern` above exists: the registry lives in
# `engine.grammar.vocabulary` and the grammar package imports this family
# back, so reading it at import time is a cycle.
def _grantable_keywords() -> tuple[str, ...]:
    from .lord_buffs import grantable_keywords

    # Longest first: the alternation is matched against a printed run, and
    # "first strike" must be tried before "first" could ever be.
    return tuple(sorted(grantable_keywords(), key=len, reverse=True))


def _keyword_alternation() -> str:
    return "|".join(_grantable_keywords())
