"""Text-keyed combat restrictions on a creature (CR 506, 509).

"This creature can't attack unless defending player controls an Island",
"attacks each combat if able", "can't be blocked by Walls" — printed templates,
not card quirks. They are derived from oracle text here rather than listed, so a
card printed with one of these wordings needs no registration.

These used to be an ``elif`` chain of **exact string equality** inside
``engine/oracle.py``. That chain hardcoded *Island*, so a creature printed
"unless defending player controls a Mountain" fell through to a bare
``static_line``: the card reported `supported` and then attacked freely, with
the restriction silently absent. The land type is data, and is carried in the
payload — as an ordinary object filter now, so what the enforcement can test is
the printed noun phrase rather than the five basics this regex names.

Each entry names the code that enforces it, because a restriction recognized
here but dispatched nowhere is worse than one that fails to parse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grammar.vocabulary import COLOR_WORDS, CREATURE_TYPES, IMPLEMENTED_KEYWORDS
from .mana_payment import mana_cost_from_symbols

# Basic land types a "controls a <type>" clause can name. Five, because a regex
# has to name what it matches — **not** because the engine can only enforce
# those: the check reads a filter through `subject_matches` now, and the
# grammar's production of the same kind reads any printed noun phrase.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

# Colour words a blocker narrowing can name, as one alternation. Read from the
# grammar's vocabulary rather than spelled out, so this file and the parser
# cannot come to disagree about what a colour word is.
_COLOR_WORD = "|".join(sorted(COLOR_WORDS))

# Printed number words a threshold can be written with. Shared with nothing on
# purpose: the compiler's own `_NUMBER_WORDS` covers trigger counts and is a
# different table for a different clause; what they have in common is English,
# not a rule.
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


@dataclass(frozen=True)
class CombatRestriction:
    """An instruction kind the combat steps dispatch on, plus its data."""

    kind: str
    payload: dict[str, object] = field(default_factory=dict)


# (pattern, kind) — enforced by:
#   cant_attack_unless_defender_controls  phases/declare_attackers_step.can_attack
#   cant_attack_without_controlled_count  phases/declare_attackers_step.can_attack
#   cant_attack                     phases/declare_attackers_step.can_attack
#   controlled_creatures_cant_attack  phases/declare_attackers_step.can_attack
#   creatures_cant_attack           phases/declare_attackers_step.can_attack
#   cant_attack_if_attacked_last_turn  phases/declare_attackers_step.can_attack
#   cant_attack_unless_defender_acted  phases/declare_attackers_step.can_attack
#   cant_attack_unless_pay          phases/declare_attackers_step.can_attack
#                                   + declare_attackers (the charge)
#   cant_block                      phases/declare_blockers_step
#   must_attack_each_combat         phases/declare_attackers_step._must_attack_if_able
#   cant_be_blocked_by              phases/declare_blockers_step
#   cant_be_blocked_except_by       phases/declare_blockers_step
#   cant_block_power_n_or_greater   phases/declare_blockers_step
#   can_block_only_with_keyword     phases/declare_blockers_step
#   must_be_blocked                 phases/declare_blockers_step
#   must_be_blocked_by_all_able     phases/declare_blockers_step
#   max_attackers_each_combat       phases/declare_attackers_step.declare_attackers
#   max_blockers_each_combat        phases/declare_blockers_step.declare_blockers
#   cant_attack_unless_others_attack  phases/declare_attackers_step.declare_attackers
#   cant_block_unless_others_block  phases/declare_blockers_step.declare_blockers
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        # "No more than two creatures can attack each combat." (Caverns of
        # Despair.) The only entry here that restricts the **declaration** as a
        # whole rather than any one creature, so it is enforced where the
        # declaration is assembled instead of in `can_attack` — a per-creature
        # predicate cannot say "and no more of you".
        #
        # The number is payload, like every other number in this file: a card
        # printed "no more than one creature" is the same restriction, and
        # spelling two into the kind would make each printed count a new kind, a
        # new enforcement branch and a new gate entry. The noun agrees with the
        # number it follows, so the plural is optional for the same reason: "no
        # more than one **creature**" is this sentence, not another one.
        re.compile(r"^no more than (?P<count>\w+) creatures? can attack each combat$"),
        "max_attackers_each_combat",
    ),
    (
        re.compile(r"^no more than (?P<count>\w+) creatures? can block each combat$"),
        "max_blockers_each_combat",
    ),
    (
        # The payload is the printed noun as an ordinary **filter**, the same
        # shape the grammar's production emits and the same shape
        # `subject_matches` reads — so the two producers of this kind stay
        # comparable byte for byte, and the enforcing check has one reader
        # rather than a land scan of its own. The five basics stay in the
        # *pattern* because a regex has to name what it matches; what the
        # engine can then enforce is no longer limited to them.
        re.compile(
            rf"^this creature can't attack unless defending player controls "
            rf"an? (?P<defender_land>{'|'.join(_LAND_TYPES)})$"
        ),
        "cant_attack_unless_defender_controls",
    ),
    # "Enchanted creature can't attack unless its controller pays {3}."
    # (Brainwash.) CR 508.1g: an additional *cost* to attack, paid as attackers
    # are declared — the mana twin of Leviathan's "unless you sacrifice two
    # Islands", which the grammar reads because its cost is a parsed noun
    # phrase. This one's cost is a printed symbol run, which is exactly what a
    # derivation table can hold.
    #
    # Both spellings of the payer, and they are one seat rather than two: CR
    # 508.1a lets only the active player declare attackers, so the creature's
    # controller *is* "you" for any card that could print the other wording.
    # Whose text the sentence is on is the difference between Brainwash and a
    # creature printing it about itself — `auras.aura_combat_restriction`
    # rewrites the subject and asks this same table (idiom 14).
    (
        re.compile(
            r"^this creature can't attack unless (?:you pay|its controller pays) "
            r"(?P<attack_mana>(?:\{[^}]+\})+)$"
        ),
        "cant_attack_unless_pay",
    ),
    # "…unless **you** control four or more artifacts" (Gadrak). The count and
    # the type are payload for the reason the land type above is: a card printed
    # with any other number or type is the same restriction, and baking either
    # into the kind made every variation a new kind, a new handler branch and a
    # new gate entry.
    (
        re.compile(
            r"^this creature can't attack unless you control "
            r"(?P<count>\w+) or more (?P<controlled_type>[a-z]+)s$"
        ),
        "cant_attack_without_controlled_count",
    ),
    (re.compile(r"^this creature can't attack$"), "cant_attack"),
    (
        # "This creature can only attack alone." CR 506.5, as a restriction on
        # the *declaration* rather than on the creature: it may attack only
        # where it is the sole attacker. Printed on a creature here and on an
        # Aura in `engine/auras.py`'s restriction table, both read by the same
        # check in the declare-attackers step.
        re.compile(r"^this creature can only attack alone$"),
        "can_only_attack_alone",
    ),
    (
        # "Except for creatures named Akron Legionnaire and artifact creatures,
        # creatures you control can't attack." A restriction printed on one
        # permanent that reaches every creature its controller has, so it is
        # enforced by a board scan in `can_attack` rather than read off the
        # attacker's own program. The exception list is payload — a union of
        # noun-phrase filters, exactly the shape the "except by" blocker
        # whitelist carries — because a card printed with any other exceptions
        # is the same restriction. Parsed by `_blocker_union`, and a phrase it
        # cannot read refuses the line: an unreadable *exception* would make
        # the restriction reach creatures the card exempts, which for a
        # restriction is the direction that silently forbids a legal attack.
        re.compile(
            r"^except for (?P<attack_exceptions>.+), "
            r"creatures you control can't attack$"
        ),
        "controlled_creatures_cant_attack",
    ),
    (
        # "Creatures without flying can't attack." (Moat.) A restriction over a
        # *described set* of creatures on any battlefield — the subject filter
        # is payload, tested by `subject_matches` at declaration, so a creature
        # that gains flying mid-game escapes it and one that loses flying is
        # caught, with nothing re-derived. The keyword is validated below: an
        # unimplemented word would make `_has_keyword` answer no for every
        # creature, "without" would then match all of them, and the enchantment
        # would silently forbid every attack — over-restriction, but exactly as
        # silent as the widening this file refuses everywhere else.
        re.compile(r"^creatures without (?P<without_keyword>[a-z]+) can't attack$"),
        "creatures_cant_attack",
    ),
    (
        # "Creatures you control can't attack." (Glacial Chasm.) The
        # unnarrowed member of the family below — no keyword, no negated
        # subtype, nothing but the seat — and the same `subject` payload one
        # enforcement site reads. The seat is captured rather than written into
        # the assembly, because it is what the sentence narrows by: a card
        # printing the phrase without it is a different restriction and must
        # keep refusing rather than being read as this one.
        re.compile(r"^creatures (?P<attack_controller>you) control can't attack$"),
        "creatures_cant_attack",
    ),
    (
        # "Non-Eye creatures you control can't attack." (Evil Eye of
        # Orms-by-Gore.) The same restriction narrowed the other way — a
        # negated subtype plus a controller — and the same payload shape, so
        # one enforcement site reads both. The subtype is validated below: a
        # word the vocabulary has never heard of would exclude nothing, and the
        # restriction would then ground the card's own Eyes — the printed
        # exemption dropped, silently.
        re.compile(
            r"^non-(?P<excluded_subtype>[a-z' -]+) creatures you control can't attack$"
        ),
        "creatures_cant_attack",
    ),
    (
        # "This creature can't attack if it attacked during your last turn."
        # (Giant Turtle.) The condition reads the attack record
        # `declare_attackers` stamps on every attacker (which seat's turn it
        # attacked on, by that seat's own turn ordinal), so the answer belongs
        # to the permanent — a Turtle that leaves and returns is a new object
        # (CR 400.7) with no record, free to attack.
        re.compile(r"^this creature can't attack if it attacked during your last turn$"),
        "cant_attack_if_attacked_last_turn",
    ),
    (
        # "Creatures can't attack a player unless that player cast a spell or
        # put a nontoken permanent onto the battlefield during their last
        # turn." (Arboria.) The whole sentence is the template; the per-seat
        # last-own-turn record it reads is folded at each turn boundary
        # (`Game.last_own_turn_activity`, mixins/turn_management). "A player"
        # is the printed scope: an attack at a planeswalker is not an attack
        # at a player and passes untouched.
        re.compile(
            r"^creatures can't attack a player unless that player cast a spell "
            r"or put a nontoken permanent onto the battlefield during their "
            r"last turn$"
        ),
        "cant_attack_unless_defender_acted",
    ),
    # "This **token** can't block" (the Pirate Pursued Whale makes). A token is
    # a creature and "this token" is the same self-reference "this creature" is
    # — the word differs only because the card printing it is a token. Both
    # spellings, rather than normalizing one to the other, because the normalizer
    # would have to know which cards are tokens.
    (re.compile(r"^this (?:creature|token) can't block$"), "cant_block"),
    (re.compile(r"^this creature attacks each combat if able$"), "must_attack_each_combat"),
    # "…can't be blocked by **Walls**" (Invisibility's mirror, Ali Baba's
    # targets) and "…can't be blocked by **artifact creatures**" (Argothian
    # Pixies, Artifact Ward). One restriction: what differs is the noun phrase,
    # which is payload for the same reason the land type and the power
    # threshold in this file are. Two rows because a subtype and a card type
    # are different captures, not because they are different rules — both
    # produce `cant_be_blocked_by` and one enforcement site asks
    # `subject_matches` about the blocker.
    (
        # "…can't be blocked by **Walls**" (Invisibility's mirror), "…by
        # **artifact creatures**" (Argothian Pixies), "…by **red** creatures"
        # (Elder Spawn), "…by creatures with **power 3 or greater**" (Amrou
        # Kithkin), "…by creatures with **flying**" (Stone Spirit).
        #
        # **One row, and the noun phrase is read by `_blocker_union`** — the
        # same parser the whitelist form below already uses. It was four rows
        # with four capture names, each translated back into a subject filter by
        # a matching branch at the enforcement site: two vocabularies for one
        # thing, so a printed noun both parsers could read needed a fifth
        # capture, a fifth branch, and would be silently unenforced without the
        # second. Stone Spirit is the card that needed the fifth.
        #
        # The regex ends in `.+`, so the union is parsed in
        # `combat_restriction_for` and a phrase it cannot read refuses the whole
        # line — admitting the match and leaving the tail unread is the widening
        # direction, an evasion ability nobody enforces.
        re.compile(r"^this creature can't be blocked by (?P<blockers>.+)$"),
        "cant_be_blocked_by",
    ),
    (
        # "…can't be blocked **except by** Walls and/or creatures with flying"
        # (Elven Riders, Evil Eye of Orms-by-Gore). The inverse of the rows
        # above: those name what may not block, this names the only things that
        # may, and a blocker matching *any* member of the union is legal.
        #
        # Its own kind rather than a negated `cant_be_blocked_by`, because the
        # two differ in what they say about everything unnamed — "can't be
        # blocked by Walls" lets the rest of the board through, "except by
        # Walls" lets none of it through.
        re.compile(r"^this creature can't be blocked except by (?P<allowed>.+)$"),
        "cant_be_blocked_except_by",
    ),
    # A blocking *requirement* rather than a restriction (CR 509.1c), and
    # weaker than Lure's: **one** able creature must block it, not every
    # able creature. The two are enforced a dozen lines apart in the
    # blockers step and must not be folded together — "all able" on a card
    # printed "must be blocked" would forbid the defender keeping a blocker
    # back, which is a legal declaration.
    (re.compile(r"^this creature must be blocked if able$"), "must_be_blocked"),
    (
        # "All Walls able to block this creature do so." (Marble Priest.) Lure's
        # requirement (CR 509.1c) narrowed to a printed noun, and printed on the
        # creature itself rather than on an Aura — so it is a template here
        # beside the others rather than a second copy of the Aura reader. The
        # noun is payload for the reason every noun in this file is: a card
        # printed "All Zombies able to block…" is the same requirement.
        re.compile(
            rf"^all (?P<blocker_subtype>{'|'.join(sorted(CREATURE_TYPES))})s able to "
            r"block this creature do so$"
        ),
        "must_be_blocked_by_all_able",
    ),
    (
        # The unnarrowed form on a creature's own text, for the same reason.
        re.compile(r"^all creatures able to block this creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        # The threshold is data for the same reason the land type is: "power 4 or
        # greater" is the same restriction Ironclaw Orcs has, and baking 2 into
        # the instruction kind made every other number a new kind, a new handler
        # branch, and a new gate entry.
        re.compile(
            r"^this creature can't block creatures with power (?P<power>\d+) or greater$"
        ),
        "cant_block_power_n_or_greater",
    ),
    (
        # "This creature can block only creatures with flying." (Shacklegeist.)
        # The mirror of the restrictions above: those name what may *not* be
        # blocked, this names the only thing that may. The keyword is payload for
        # the reason the threshold beside it is — a card printed with any other
        # evasion word is the same restriction.
        re.compile(
            r"^this creature can block only creatures with (?P<required_keyword>[a-z]+)$"
        ),
        "can_block_only_with_keyword",
    ),
)


#: "…**as long as defending player controls a snow land**." (Arctic Foxes.)
#: A qualifier on whatever restriction precedes it, so it is stripped once here
#: rather than written into every row — the same arrangement
#: `untap_restrictions._WHILE_UNTAPPED` makes for "as long as this artifact is
#: untapped". The seat and the noun phrase are both payload: a card printed
#: "as long as you control an Island" is this clause, not another one.
_AS_LONG_AS = re.compile(
    r"^(?P<rest>.+?) as long as (?P<who>defending player|you) "
    r"(?:controls?) an? (?P<board>.+)$"
)

#: The kinds whose enforcement site **asks** about a condition. A qualifier
#: attached to any other kind would be a restriction applied unconditionally —
#: silently, and in the direction of doing more than the card says — so the line
#: refuses instead and its card is reported unsupported naming the clause. This
#: is the same claim `activation_restrictions.payload_readable` makes: a row may
#: match more sentences than it implements, and the ones it does not implement
#: must refuse rather than drop a clause.
CONDITIONAL_RESTRICTION_KINDS: frozenset[str] = frozenset({"cant_be_blocked_by"})


def _controlled_noun(phrase: str) -> dict | None:
    """The board noun phrase an "as long as … controls …" clause names.

    Read by **the grammar's noun parser**, not by `_blocker_noun` beside it.
    That reader is a hand-written mini-parser for the members of a blocker
    union, and it knows five shapes; "a snow land" is not one of them, and
    teaching it a sixth would be one more entry in the second vocabulary this
    file already keeps. The clause here is an ordinary board question — the
    same one `activation_restrictions._controlled_board_phrase` and
    `untap_restrictions._blocked_subject` ask — so it gets the same answer.

    (`_blocker_noun` is still a second reader of printed nouns, and is the
    obvious next thing to retire in this file. It is not retired here because
    its callers are unions, which the noun parser reads one member at a time.)
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    stream = TokenStream(tokenize(phrase.strip()).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload


def restriction_condition_holds(
    game, condition: dict | None, *, observer: int | None, defender: int | None
) -> bool:
    """Whether a restriction's "as long as" clause holds right now.

    ``None`` — no clause — is True: an unqualified restriction always applies.

    The seat is read from the printed words: "defending player" is the seat
    being attacked, "you" is the seat whose ability this is (CR 109.5). A seat
    the caller cannot name answers False, which keeps the restriction *on*:
    for a clause the card prints as a condition for the restriction applying,
    the safe direction is the one that does not silently widen what may block.
    """
    if not condition:
        return True
    from .subject_filters import subject_matches

    seat = defender if condition.get("who") == "defending_player" else observer
    if seat is None or not (0 <= seat < len(game.players)):
        return False
    described = condition.get("subject") or {}
    return any(
        subject_matches(game, perm, described, observer=observer)
        for perm in game.controlled_by(seat)
    )


def combat_restriction_for(
    normalized_line: str, card_name: str | None = None
) -> CombatRestriction | None:
    """The combat restriction *normalized_line* imposes, or None.

    Takes an already-normalized line (``oracle.normalize_creature_line``), which
    is what the compiler holds at the point it needs this — usually with the
    card's self-references collapsed to "this creature"
    (``oracle._restriction_line``). *card_name* is what that collapse erased:
    "creatures named **this creature**" (Akron Legionnaire's exception names
    the card itself) is resolved back to the printed name here, because the
    filter matches by *name*, never by identity — a second Akron Legionnaire
    and a token wearing the name are both excepted. A caller with no name to
    give gets a refusal for that phrase, never a filter that matches nothing.
    """
    # The trailing qualifier first, so every row below sees the sentence it is
    # written against. A clause read here and then attached to a kind nobody
    # asks about would be worse than one nobody reads, so the attachment is
    # gated on `CONDITIONAL_RESTRICTION_KINDS`.
    condition: dict | None = None
    qualifier = _AS_LONG_AS.match(normalized_line)
    if qualifier is not None:
        board = _controlled_noun(qualifier.group("board"))
        if board is None:
            return None
        condition = {"who": qualifier.group("who").replace(" ", "_"), "subject": board}
        normalized_line = qualifier.group("rest").strip()

    for pattern, kind in _PATTERNS:
        match = pattern.match(normalized_line)
        if match is None:
            continue
        if condition is not None and kind not in CONDITIONAL_RESTRICTION_KINDS:
            return None
        # Numeric captures reach handlers as ints: a payload whose type depends
        # on which regex matched is how a comparison silently becomes a string
        # compare. A printed number **word** is read here too — the regex only
        # delimits it, the way it delimits a noun phrase everywhere else — and a
        # word with no number behind it refuses the whole line rather than
        # reaching a comparison as a string, where it would compare unequal to
        # every count and quietly stop the creature attacking at all.
        payload = {}
        for key, value in match.groupdict().items():
            if value is not None and value.isdigit():
                payload[key] = int(value)
                continue
            if key == "count" and value is not None:
                number = _NUMBER_WORDS.get(value)
                if number is None:
                    return None
                payload[key] = number
                continue
            payload[key] = value
        # A captured subtype must actually be one. The blocker pattern above
        # reads any bare plural noun ("by walls"), which is what keeps it from
        # needing a 350-entry alternation — but a word the vocabulary has never
        # heard of would produce a filter matching nothing, the restriction
        # would go inert, and the creature would be blockable by anything. That
        # is the widening direction, so the line refuses instead and its card is
        # reported unsupported naming the clause.
        # The printed symbol run as the symbol dict every payment in this engine
        # reads. Converted here for the same reason a captured number becomes an
        # int here: a payload whose shape depends on which regex matched is how
        # a cost silently stops being payable. A symbol
        # `mana_cost_from_symbols` cannot spend refuses the whole line — a cost
        # read as smaller than it is charges less than the card says, and the
        # widening direction is a creature that attacks for free.
        printed_cost = payload.pop("attack_mana", None)
        if printed_cost is not None:
            cost = mana_cost_from_symbols(printed_cost)
            if cost is None:
                return None
            payload["mana"] = cost
        # "…unless defending player controls an Island." The captured land type
        # becomes the ordinary `subject` filter payload the enforcement site
        # hands to `subject_matches`, and the polarity rides beside it — the
        # same two keys the grammar's production emits for the same kind, so
        # the two producers stay comparable byte for byte. Converted here for
        # the reason every other capture on this page is: a payload whose shape
        # depends on which regex matched is how a restriction silently stops
        # being testable.
        defender_land = payload.pop("defender_land", None)
        if defender_land is not None:
            payload["subject"] = {"subtype_filter": defender_land}
            payload["required"] = True
        subtype = payload.get("blocker_subtype")
        if subtype is not None and subtype not in CREATURE_TYPES:
            return None
        # A captured colour reaches the payload as its **symbol**, converted
        # here for the reason a captured number is converted to an int here: a
        # payload whose shape depends on which regex matched is how a filter
        # silently stops matching. Every other reader of `color_filter` in this
        # engine takes a symbol.
        colour = payload.get("blocker_color")
        if colour is not None:
            payload["blocker_color"] = COLOR_WORDS[colour]
        # "…except by Walls and/or creatures with flying". The union is parsed
        # **here**, and a phrase this cannot read refuses the line — the regex
        # above ends in `.+`, so admitting the match and leaving the tail to the
        # enforcement site would be a restriction the gate accepts and nobody
        # applies. That is the widening direction: an evasion ability nothing
        # enforces makes the creature blockable by everything.
        blockers = payload.pop("blockers", None)
        if blockers is not None:
            filters = _blocker_union(blockers, card_name)
            if filters is None:
                return None
            payload["blocker_filters"] = filters
        allowed = payload.pop("allowed", None)
        if allowed is not None:
            filters = _blocker_union(allowed)
            if filters is None:
                return None
            payload["allowed_blockers"] = filters
        # "Except for <union>, creatures you control can't attack." The union
        # is parsed here for the reason "except by" is: the regex ends in `.+`,
        # and admitting the match while a member went unread would be an
        # exception nothing honours — a creature the card exempts refused its
        # attack, silently.
        exceptions = payload.pop("attack_exceptions", None)
        if exceptions is not None:
            filters = _blocker_union(exceptions, card_name)
            if filters is None:
                return None
            payload["exceptions"] = filters
        # "Creatures without <keyword> …" / "Non-<subtype> creatures you
        # control …" — both build the one `subject` filter payload the
        # enforcement site hands to `subject_matches`, and both validate their
        # captured word here for the reasons written on their rows: an
        # unvalidated word does not widen the restriction, it *over-applies*
        # it, which is just as silent and wrong in the other direction.
        without_keyword = payload.pop("without_keyword", None)
        if without_keyword is not None:
            if without_keyword not in IMPLEMENTED_KEYWORDS:
                return None
            payload["subject"] = {
                "type_filter": "creature",
                "without_keywords": [without_keyword],
            }
        # "Creatures **you** control can't attack." The seat alone, built into
        # the same one `subject` filter its two narrowed siblings build, so the
        # enforcement site reads one payload shape for all three.
        attack_controller = payload.pop("attack_controller", None)
        if attack_controller is not None:
            payload["subject"] = {
                "type_filter": "creature",
                "controller": attack_controller,
            }
        excluded_subtype = payload.pop("excluded_subtype", None)
        if excluded_subtype is not None:
            if excluded_subtype not in CREATURE_TYPES:
                return None
            payload["subject"] = {
                "type_filter": "creature",
                "exclude_subtypes": [excluded_subtype],
                "controller": "you",
            }
        if condition is not None:
            payload["condition"] = condition
        return CombatRestriction(kind, payload)
    return None


#: One member of an "except by" union, as the subject-filter payload that tests
#: it. Each entry is a whole printed noun phrase rather than a word, because
#: "creatures with flying" and "artifact creatures" are two words doing two
#: different jobs and splitting them would need the noun parser this file
#: deliberately does not have.
def _blocker_union(phrase: str, card_name: str | None = None) -> list[dict] | None:
    """The filters a noun-phrase union names, or None.

    Two rows carry one: the blocker whitelist ("can't be blocked except by
    Walls and/or creatures with flying") and the attack-exception list
    ("Except for creatures named Akron Legionnaire and artifact creatures,
    …"). One parser, because the members are the same printed vocabulary and
    a phrase readable in one union and not the other would be a fork nobody
    could find.

    None means "this file does not read that phrase", which keeps the card
    unsupported with the clause named. Returning a partial union instead would
    be an evasion ability that lets through more than the card allows — or an
    exception list that exempts fewer creatures than the card prints.
    """
    filters: list[dict] = []
    for part in re.split(r"\s*(?:and/or|and|or)\s+", phrase.strip()):
        part = part.strip()
        if not part:
            continue
        described = _blocker_noun(part, card_name)
        if described is None:
            # **A phrase the split broke may still be one noun.** "creatures
            # with power 2 or greater" contains the word "or" and is not a
            # union, so splitting it produced two members neither of which
            # reads — and the whole line refused, for a threshold this engine
            # has enforced since Amrou Kithkin.
            #
            # The retry is here, after a member fails, rather than before the
            # split: read whole-first, "creatures named Akron Legionnaire and
            # artifact creatures" fullmatches the *name* pattern greedily and
            # the union collapses into one creature nobody is named. Trying the
            # split first keeps every phrase that already worked working, and
            # this is only reached where it did not.
            whole = _blocker_noun(phrase.strip(), card_name)
            return [whole] if whole is not None else None
        filters.append(described)
    return filters or None


def _blocker_noun(part: str, card_name: str | None = None) -> dict | None:
    """One member of the union, as a subject-filter payload."""
    named = re.fullmatch(r"creatures named (.+)", part)
    if named is not None:
        # "creatures named Kobolds of Kher Keep" — the name is data, matched
        # through `name_key` by the subject matcher, so there is nothing to
        # validate it against: a token's name (Wolves of the Hunt) is a name no
        # card file lists. "this creature" is what `_restriction_line` collapsed
        # the card's own name to; only the caller knows what it was, and a
        # caller that cannot say refuses the phrase rather than carrying a
        # filter that matches nothing.
        name = named.group(1).strip()
        if name == "this creature":
            if not card_name:
                return None
            name = card_name
        return {"type_filter": "creature", "named": name}
    keyword = re.fullmatch(r"creatures with ([a-z ]+)", part)
    if keyword is not None:
        # The word has to be a keyword the engine implements, checked here for
        # the reason the subtype is checked in `combat_restriction_for`: the
        # matcher would answer "no permanent has that" for anything else, and a
        # *whitelist* whose members match nothing is a creature that cannot be
        # blocked at all. Loud refusal instead.
        word = keyword.group(1).strip()
        if word not in IMPLEMENTED_KEYWORDS:
            return None
        return {"type_filter": "creature", "with_keywords": [word]}
    power = re.fullmatch(r"creatures with power (\d+) or greater", part)
    if power is not None:
        # Against the blocker's **effective** power (CR 613 layer 7), which is
        # what `subject_matches` asks — a 2/2 that has been pumped stops being a
        # legal blocker while it is pumped. Read here rather than as its own
        # capture, so the whitelist form ("…except by creatures with power 3 or
        # greater") gets it for free and cannot disagree.
        return {"type_filter": "creature", "power": {"op": "ge", "value": int(power.group(1))}}
    colored = re.fullmatch(rf"({_COLOR_WORD}) creatures", part)
    if colored is not None:
        return {"type_filter": "creature", "color_filter": COLOR_WORDS[colored.group(1)]}
    typed = re.fullmatch(r"(artifact|enchantment|land) creatures", part)
    if typed is not None:
        return {"type_filter_all": [typed.group(1), "creature"]}
    # "non-Wall creatures" (Flow of Maggots). The negation of the typed forms
    # above, and its own branch rather than a flag on one of them: what it
    # names is every creature *except* one subtype, and the matcher has a key
    # for exactly that. A card printing "nonartifact creatures" is the same
    # sentence and is left for the card that prints it — this reads the subtype
    # form the pool has.
    negated = re.fullmatch(r"non-?([a-z]+) creatures", part)
    if negated is not None:
        subtype = negated.group(1)
        if subtype in CREATURE_TYPES:
            return {"type_filter": "creature", "exclude_subtypes": [subtype]}
        return None
    singular = part[:-1] if part.endswith("s") else part
    if singular in CREATURE_TYPES:
        return {"subtype_filter": singular}
    return None


#: A restriction *granted* for the turn rather than printed on a permanent
#: ("Target creature can't be blocked by Walls this turn", Tower of Coireall).
#: The record is a list of blocker-filter payloads, which is the vocabulary the
#: printed static forms above are enforced through too - one question asked of
#: both in the declare-blockers step, so a card printing a new noun costs
#: neither of them a branch. Swept with the turn by
#: ``mixins/_constants._EOT_METADATA_KEYS``.
GRANTED_BLOCKER_RESTRICTIONS = "cant_be_blocked_by_until_eot"


def grant_blocker_restriction(permanent, described: dict) -> None:
    """Record that *permanent* can't be blocked by creatures matching
    *described* for the rest of the turn (CR 509.1b).

    Duplicates are folded, so two resolutions of the same effect leave one
    entry - the restriction is a fact about the board, not a count.
    """
    record = [dict(entry) for entry in granted_blocker_filters(permanent)]
    if described not in record:
        record.append(dict(described))
    permanent.metadata[GRANTED_BLOCKER_RESTRICTIONS] = record


def granted_blocker_filters(permanent) -> tuple[dict, ...]:
    """Every blocker class *permanent* has been made unblockable by this turn."""
    metadata = getattr(permanent, "metadata", None)
    if not metadata:
        return ()
    return tuple(metadata.get(GRANTED_BLOCKER_RESTRICTIONS) or ())


def participation_cap(permanents, kind: str) -> int | None:
    """The cap the battlefield currently puts on how many creatures may *kind*
    (``"attack"`` / ``"block"``) this combat, or None when nothing caps it.

    The **smallest** cap wins when several permanents impose one: each is a
    restriction in its own right (CR 509.1b/508.1c), and obeying only the
    loosest would let a declaration break the tighter one. Two Caverns of
    Despair, or one beside a card printing a different number, are both
    answered by that without either card knowing the other exists.

    Takes the permanents rather than the game because this file reads text and
    nothing else; the callers are the two declaration steps, which hold the
    board already.
    """
    from .oracle import compile_card_oracle

    wanted = f"max_{kind}ers_each_combat"
    caps = [
        int(instruction.payload.get("count", 0))
        for permanent in permanents
        for instruction in compile_card_oracle(permanent.effective_card).instructions
        if instruction.kind == wanted
    ]
    return min(caps) if caps else None

def declaration_company_required(permanent, kind: str) -> int | None:
    """How many **other** creatures must *kind* alongside *permanent*, or None.

    "This creature can't attack unless at least two other creatures attack."
    (Orcish Conscripts, and its blocking twin.) The sibling of
    :func:`participation_cap` one rule over: that one is a ceiling the board
    puts on a declaration, this one is a floor a creature puts on the
    declaration it joins — and both are CR 508.1c / CR 509.1b restrictions
    asked of the declaration as a whole, which is why neither can live in the
    per-creature predicates beside them.

    The number is payload, so a card printing "at least three" is this same
    restriction. Read off ``effective_card`` like every other combat
    restriction here, so a copy or a text change is answered without a second
    reader.
    """
    from .oracle import compile_card_oracle

    wanted = f"cant_{kind}_unless_others_{kind}"
    needed = [
        int(instruction.payload.get("count", 0))
        for instruction in compile_card_oracle(permanent.effective_card).instructions
        if instruction.kind == wanted
    ]
    # The **largest** floor wins, for the mirror of the reason the smallest
    # ceiling does: each clause is a restriction in its own right, and
    # satisfying only the loosest would disobey the tighter one.
    return max(needed) if needed else None
