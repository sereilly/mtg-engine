"""What a card is printed with, and the copiable values every layer starts from.

Two readers of one parse. **Off the battlefield** CR 613 does not apply, so
"what types does this card have?" is the printed line (``printed_shape``,
``printed_supertypes``) — a card in a hand, a graveyard, a library or on the
stack, with the CDA that works in every zone (CR 604.3: "is every creature
type") folded in. **On the battlefield** the same parse of the permanent's
effective card (layers 1 and 3 applied) is the seed the layer system starts
from (``seed_characteristics``, CR 613.2c): types, supertypes, colours, P/T and
the printed abilities (``_printed_abilities``, the keywords its own text gives
it, so a layer-6 removal has something to take away).

``COPIABLE_VALUE`` is where in a layer something that is part of the copiable
values sits when it is recorded as an effect rather than folded into the seed.

Split out of ``engine/layer_bridge.py`` at the size band (round kg3), with
``engine/type_layer.py``; both sit below it, and it reads them.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING

from .oracle_types import compilation_cache
from .banding import band_quality
from .continuous import Characteristics
from .landwalk import landwalk_requirement
from .object_creature_types import (every_creature_type_subtypes,
                                    restore_struck_every_creature_type)

if TYPE_CHECKING:
    from .models import Permanent


#: The place in a layer of something that is part of the object's **copiable
#: values** but is recorded as an effect rather than folded into the seed: what
#: an "as this enters" choice made the permanent (Primal Clay's body — a
#: layer-1 copiable effect by CR 613.2a). Copiable values are where every later
#: layer *starts* (CR 613.2c, CR 707.2), so such a contribution applies before
#: every effect the clock has stamped — the same number an unstamped record
#: reads as, and a different claim: this one is first by rule, that one by
#: omission.
COPIABLE_VALUE = 0


@lru_cache(maxsize=None)
def _printed_shape(
    type_line: str, name: str, oracle_text: str, keywords: tuple[str, ...]
) -> tuple[frozenset[str], frozenset[str]]:
    """A card's printed types and subtypes, parsed once per distinct card.

    Seeding runs on every characteristic read — ``is_creature`` alone is called
    in tight state-based-action and combat loops — so the text parsing behind it
    is cached on the same immutable fields ``compile_card_oracle`` keys on.
    """
    lowered = type_line.lower()
    card_types = frozenset(
        word for word in ("artifact", "creature", "enchantment", "instant", "land", "planeswalker", "sorcery")
        if word in lowered
    )
    subtypes: frozenset[str] = frozenset()
    if "—" in type_line or "-" in type_line:
        tail = type_line.replace("—", "-").split("-", 1)[-1]
        subtypes = frozenset(word.lower() for word in tail.split() if word)
    # "…is every creature type" (Mistform Ultimus): a CDA works in every zone
    # (CR 604.3), so it is in the one parse the off-battlefield answer and the
    # layer seed share — applied before every layer-4 effect (CR 613.3).
    return card_types, every_creature_type_subtypes(
        card_types, subtypes, oracle_text, name
    )


def _seed_shape(perm: Permanent, card) -> tuple[frozenset[str], frozenset[str]]:
    """``_printed_shape`` of *card*, *perm*'s effective card, with a type CDA
    layer 6 struck put back (``restore_struck_every_creature_type``)."""
    card_types, subtypes = _printed_shape(
        card.type_line, card.name, card.oracle_text, card.keywords
    )
    return card_types, restore_struck_every_creature_type(
        perm, card, card_types, subtypes
    )


@lru_cache(maxsize=None)
def printed_supertypes(type_line: str) -> frozenset[str]:
    """The supertypes printed on *type_line* — "legendary", "basic", "snow".

    Its own reader rather than a third return value from ``_printed_shape``,
    because it answers for two different kinds of object and one of them is a
    ``Permanent``: a supertype is not something layers 4 or 6 compute here, so
    the answer is whatever line the object *effectively* has (a copy's, a text
    change's) and there is no computed accessor to defer to. Callers pass the
    line they mean and the difference stays visible at the call site.

    Read against the vocabulary rather than a literal list, so a set printing a
    new supertype needs ``fetch_vocabulary.py`` and nothing else.
    """
    from .grammar.vocabulary import TYPE_LINE_SUPERTYPES

    head = type_line.replace("—", "-").split("-", 1)[0].lower()
    return frozenset(word for word in head.split() if word in TYPE_LINE_SUPERTYPES)


def printed_shape(card) -> tuple[frozenset[str], frozenset[str]]:
    """The card types and subtypes *card* is printed with.

    The answer for an object **outside** the battlefield — a card in a hand, a
    graveyard or a library — where CR 613 does not apply at all and there is no
    permanent to ask ``has_type``. On the battlefield this is only the seed;
    layers 4 and 6 may have moved it since, so a caller holding a ``Permanent``
    wants ``has_type`` and never this.
    """
    return _printed_shape(card.type_line, card.name, card.oracle_text, card.keywords)


def seed_characteristics(perm: Permanent) -> Characteristics:
    """An object's copiable values — where layer application starts (613.2c).

    Every field reads the *same* card: ``effective_card`` is layer 1 (the copy)
    and then layer 3 (the text change), and CR 613.2c says the result of layer 1
    **is** the copiable values. While copies were stamped as overrides this
    function could not do that — colour had to seed from ``perm.card`` so
    Vesuvan Doppelganger's blue survived, and P/T had to seed from ``perm.card``
    so the copy's ``absolute_power`` stamp did not get counted twice in 7b. Both
    of those were the stamped model showing through the seam; layer 1 puts the
    exception where it belongs, in the copy effect.

    ``None`` power/toughness means the printed value is variable ("*"), so a
    characteristic-defining ability in 7a supplies it. That is the distinction
    the old code could not make, having no value for "not a number".
    """
    card = perm.effective_card
    card_types, subtypes = _seed_shape(perm, card)
    return Characteristics(
        card_types=set(card_types),
        subtypes=set(subtypes),
        # CR 205.4a's half of the line, seeded here for the reason every other
        # field is: a supertype an effect adds or removes (Arcum's Weathervane,
        # Melting) is a layer-4 change like any other, and a channel that starts
        # empty could only ever *add*. ``Characteristics.supertypes`` and
        # ``add_types``' keyword had been here since the layer system was
        # written with nothing seeding them and nothing reading them back — a
        # channel built at both ends and connected at neither.
        supertypes=set(printed_supertypes(card.type_line)),
        colors=set(card.colors),
        abilities=_printed_abilities(card),
        power=card.base_power,
        toughness=card.base_toughness,
    )


# Keywords the engine recognizes on a card's own text. Kept here rather than as
# a fallback *after* layer 6, because a printed ability is part of the object's
# copiable values: it has to be in the seed so a removal in layer 6 can take it
# away. Consulted after the parsed `keywords` field so a card whose keyword only
# appears in its oracle text still has it.
_TEXT_KEYWORDS = (
    "flying", "first strike", "double strike", "trample", "vigilance", "haste",
    "defender", "reach", "banding", "fear", "deathtouch", "islandwalk",
    "mountainwalk", "swampwalk", "forestwalk", "plainswalk", "desertwalk",
    "indestructible", "menace", "prowess", "flash",
    # "rampage" is the word alone, and the printed line is "Rampage 2" — so the
    # ingested keywords field seeds "rampage 2" and nothing asking for the
    # *ability* found it. CR 702.23c counts instances of rampage, which is what
    # "does it have rampage" means (Rapid Fire's "if it doesn't have rampage"),
    # and the number is the instance's parameter rather than part of the name.
    # A substring scan is safe here for the reason it is not for hexproof:
    # there is no narrower keyword whose name contains this one.
    "rampage",
    # …and "flanking", for the same two reasons: it is what a *granted* line
    # (Agility) puts back into the ability set, and it is what the next
    # flanker's own "without flanking" filter asks. The substring scan is safe
    # here on the same test — no narrower keyword's name contains this word.
    "flanking",
    # …and "provoke" (CR 702.39), line-derived like flanking and granted the
    # same way — by a lord (Hunter Sliver), whose granted "Provoke" line is
    # what puts the word back in the set. The substring test holds: no
    # narrower keyword's name contains this word.
    "provoke",
    # …and "phasing", which a card can carry as a printed line alone: Teferi's
    # Curse grants it as a keyword and Shimmer as a board-wide static, and the
    # untap step reads the word off this set. Same substring test as the two
    # above — no narrower keyword's name contains it.
    "phasing",
    # "hexproof" is deliberately absent: this is a substring scan, and bare
    # hexproof is a *stronger* keyword than "hexproof from <colour>" — matching
    # the word inside the phrase would upgrade Sporeweb Weaver's blue-only
    # shield to a full one. Printed hexproof arrives through the ingested
    # keywords field, which the seed consults first.
)


#: "<qualifier> <type>walk" as it is printed inside a keyword line. The
#: qualifier is captured and handed to `landwalk_requirement`, which decides
#: whether it is a real one — so this pattern is deliberately permissive.
_QUALIFIED_WALK = r"(\w+) %s\b"


def _text_keywords_in(value: str) -> set[str]:
    """The keywords printed in one keyword line.

    A substring scan, and the one place its hazard is answered rather than
    assumed. ``_TEXT_KEYWORDS``' own comment says a bare word is safe "for the
    reason it is not for hexproof: there is no narrower keyword whose name
    contains this one" — Ice Age is where that stopped being true. "Snow
    forestwalk" (Rime Dryad, Legions of Lim-Dul) *contains* "forestwalk", and
    the containing phrase is the **narrower** ability: seeded as plain
    forestwalk, Rime Dryad was unblockable against any Forest at all, which is a
    strictly better creature than the one printed.

    So a walk word is dropped when the printed text qualifies it, and the
    qualified ability takes its place. Which qualifiers count is asked of
    ``landwalk_requirement`` — the reader that *enforces* the ability — rather
    than of a list here, so a supertype the vocabulary gains later is covered
    the day it is fetched, and a word that is not a real qualifier leaves the
    bare ability alone.
    """
    found = {word for word in _TEXT_KEYWORDS if word in value}
    for word in list(found):
        if not word.endswith("walk"):
            continue
        for match in re.finditer(_QUALIFIED_WALK % word, value):
            if landwalk_requirement(f"{match.group(1)} {word}") is not None:
                found.discard(word)
                found.add(f"{match.group(1)} {word}")
    return found


def _printed_abilities(card) -> set[str]:
    return set(_printed_abilities_cached(
        card.name, card.type_line, card.oracle_text, card.keywords
    ))


@compilation_cache
@lru_cache(maxsize=None)
def _printed_abilities_cached(
    name: str, type_line: str, oracle_text: str, keywords: tuple[str, ...]
) -> frozenset[str]:
    """Printed keywords, including any the compiler only finds in oracle text.

    Cached per distinct card: this reads every keyword line for every known
    keyword, and it runs on each characteristic read.
    """
    from .keyword_lines import _is_supported_keyword_line, keyword_part_ability
    from .line_normalization import normalize_creature_line
    from .line_rewrites import expand_ability_lines
    from .models import CardDefinition

    card = CardDefinition(
        name=name, mana_cost="", cmc=0.0, type_line=type_line, oracle_text=oracle_text,
        colors=(), color_identity=(), keywords=keywords, produced_mana=(), raw={},
    )
    abilities = {kw.lower() for kw in keywords}
    hexproof_from_printed = bare_hexproof_printed = False
    # Every keyword line the card states, normalized, in printed order: the
    # lines the compiler's keyword-line classifier admits, off the rewritten
    # lines every reader of a card's lines starts from (CLAUDE.md). Read off
    # the *lines* rather than the compiled program's ``keyword_line``
    # instructions because only the creature front end emits those — the
    # non-creature one claims a keyword line and emits nothing
    # (``line_classification``), so an enchantment's or an artifact's keywords
    # were known only from the ingested field, and a line granted to one
    # (Balduvian Shaman's enchantment) from nowhere at all. Both front ends ask
    # this classifier, so what is read here is exactly what either admitted.
    stated_lines = [
        normalize_creature_line(line)
        for line in expand_ability_lines(
            oracle_text, card_name=name, legendary=card.is_legendary
        ).splitlines()
        if line.strip() and _is_supported_keyword_line(line)
    ]
    for value in stated_lines:
        # **A keyword line, and nothing else.** "Does this line give *this
        # permanent* this keyword?" is a question about the line's subject, and
        # the compiler's line classifier has already answered it: a line that
        # states the object's own keyword abilities is a keyword line
        # (CR 702), one that gives them to it on a condition is a
        # ``conditional_static`` and one that gives them to a class of
        # permanents is a ``lord_buff`` -- the last two contributed in layer 6
        # by their own readers, with the condition and the class enforced.
        #
        # A ``static_line`` is what is left: a sentence some text-keyed table
        # claimed and no instruction carries. This scan used to read those too,
        # and a word search has no subject, so it seeded whatever keyword the
        # sentence *mentioned*: Gliding Licid flew because it says "enchanted
        # creature has flying", Guardian Beast was indestructible because the
        # artifacts beside it are, Rootwater Shaman had flash because Auras may
        # be cast "as though they had flash", and Gosta Dirk had the islandwalk
        # his own text switches off. Faerie Squadron ("…and with flying", for a
        # *kicked* one) was the first found and was skipped by pattern; a skip
        # per sentence is a deny-list of a table that names no legitimate
        # entry. Over both manifest roles the pool carries 199 static lines, 18
        # of them mention a keyword, and not one of the 18 gives it to the
        # permanent printing it
        # (``tests/engine/test_printed_keyword_seed.py``).
        abilities.update(_text_keywords_in(value))
        # A printed "bands with other [quality]" line (CR 702.22b) — the Wolves
        # of the Hunt token Master of the Hunt makes carries one. It cannot ride
        # the word scan above: the ability's name *is* the printed quality, so
        # there is no word to look for. Each comma-joined part is asked
        # separately, exactly as the keyword-line gate admits them.
        for part in value.split(","):
            part = part.strip()
            # **Every keyword the part names by a word**, through the reader
            # that admitted it (``keyword_lines.keyword_part_ability``): the
            # implemented word itself, or the keyword without the number or
            # cost it carries. The substring scan above holds a list of the
            # words somebody had needed back, and a keyword outside it was
            # had only by a card whose *ingested field* named it — so a line
            # an effect granted (CR 613.1f) gave the behaviour and not the
            # keyword: Balduvian Shaman's "Cumulative upkeep {1}" charged the
            # enchantment every upkeep and left it a legal target for "that
            # doesn't have cumulative upkeep". Over both manifest roles the
            # field already names every word this adds for a printed card
            # (``tests/engine/test_kg5_layers_granted_keywords.py``).
            named = keyword_part_ability(part)
            if named is not None:
                abilities.add(named)
            if band_quality(part) is not None:
                abilities.add(part)
            # "Legendary landwalk" (Livonya Silone) — the same shape, and it
            # cannot ride the word scan above either: CR 702.14a builds the
            # ability's name out of the printed quality, so there is no fixed
            # word to look for. The ingested keywords field usually carries it,
            # but a fixture card built from oracle text alone has only this.
            if landwalk_requirement(part) is not None:
                abilities.add(part)
            # "Hexproof from blue" (Sporeweb Weaver, CR 702.11d): the ability
            # is named by its quality, one per colour, which is the word
            # ``_can_be_targeted`` asks for ("hexproof from blue"). The same
            # split the keyword-line gate admits it by
            # (``keyword_lines``: colour words joined by "and" / "and from").
            if part.startswith("hexproof from "):
                hexproof_from_printed = True
                for quality in re.split(
                    r"\band from\b|\band\b", part[len("hexproof from "):]
                ):
                    if quality.strip():
                        abilities.add(f"hexproof from {quality.strip()}")
            elif part == "hexproof":
                bare_hexproof_printed = True
    # **The ingested field names the family, not the ability.** Scryfall lists
    # a "hexproof from blue" creature under both "Hexproof from" and
    # "Hexproof" — CR 702.11d's last sentence, "a 'hexproof from [quality]'
    # ability is a hexproof ability" — and seeded as written that "Hexproof"
    # was bare hexproof (CR 702.11b): Sporeweb Weaver and Garruk's Harbinger
    # could be targeted by no spell or ability an opponent controlled, of any
    # colour, while the shield their text prints was never in the set at all.
    # Dropped only where the text prints the narrower ability and not the
    # bare one beside it.
    if hexproof_from_printed and not bare_hexproof_printed:
        abilities.discard("hexproof")
        abilities.discard("hexproof from")
    return frozenset(abilities)


__all__ = ["seed_characteristics"]
