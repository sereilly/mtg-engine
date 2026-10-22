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

The rows themselves, every printed template in the order
:func:`combat_restriction_for` tries them, are ``_PATTERNS`` in
``engine/combat_restriction_table.py``: split out at the 2,000-line cap, where
the table alone was over half of this module.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .grammar.vocabulary import (COLOR_WORDS, CREATURE_TYPES,
                                 IMPLEMENTED_KEYWORDS, KEYWORD_ABILITIES)
from .combat_restriction_table import _PATTERNS
from .mana_payment import mana_cost_from_symbols
from .oracle_types import X_FROM_COUNT

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
    #: The **other** kinds this one printed sentence arms, over the same
    #: payload. Katabatic Winds prints three prohibitions in one sentence over
    #: one noun phrase — can't attack, can't block, and can't activate a
    #: {T} ability — and each is answered at a different step, so each needs
    #: its own kind. One row rather than three is what the sentence is: the
    #: subject is read once and the three enforcement sites cannot come to
    #: disagree about which creatures it names.
    #:
    #: The default is empty, so every row written before this field existed
    #: produces exactly the one instruction it always did.
    also_kinds: tuple[str, ...] = ()


#: The evasion abilities the "can block … as though it had …" row above may
#: name. Shadow only, and deliberately: the enforcement site is
#: `declare_blockers_step._can_block_attacker`'s **shadow** branch, so a word
#: admitted here that it does not read would be a line this gate accepts and
#: nothing acts on — a card reported supported for a permission that never
#: applies. `engine/evasion_negation.py` made the same choice for the same
#: reason one rule over ("Flying's and fear's negations arrive with the card
#: that prints them, beside the check that enforces *them*"), and the keyword
#: stays payload rather than part of the kind so the next word costs this tuple
#: and one branch rather than a second row.
_AS_THOUGH_BLOCKABLE: tuple[str, ...] = ("shadow",)


#: Every keyword ability the printed vocabulary knows, lowercased — the gate a
#: captured keyword word has to pass. Read off ``data/vocabulary/`` through the
#: grammar's catalog rather than listed here, exactly as ``_COLOR_WORD`` above
#: is read off ``COLOR_WORDS``: a second list of keyword names is the drift this
#: file's opening docstring is about.
_KEYWORD_WORDS: frozenset[str] = frozenset(
    word.lower() for word in KEYWORD_ABILITIES
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

#: "…**if there's another creature on the battlefield**." (Shauku, Endbringer.)
#: The second printed qualifier, and it differs from the one above in the one
#: way that matters to the reader: CR 403.1 makes the battlefield a **shared**
#: zone, so "on the battlefield" is every seat's permanents and not a seat's
#: board. Written as a second qualifier rather than as a row because it is the
#: same composition — a condition on whatever restriction precedes it — and
#: because a row would have had to spell the noun phrase out.
#:
#: "Another" is captured rather than swallowed. It is the whole of what makes
#: the card playable: Shauku alone on the battlefield may attack, and reading
#: the word as an article would have grounded it permanently — the dropped
#: rider with a combat face.
_IF_ON_BATTLEFIELD = re.compile(
    r"^(?P<rest>.+?) if there's (?:(?P<other>another)|an?) (?P<board>.+) "
    r"on the battlefield$"
)

#: "…**if an enchantment is on the battlefield**." (Wirecat.) The qualifier
#: above in the other printed word order — the noun in front of the verb rather
#: than behind "there's" — and the same question in every other respect, so it
#: builds the same condition rather than a second kind of one.
#:
#: Its own pattern rather than an alternation inside that one because the two
#: place the noun on opposite sides of the copula, and a single regex reading
#: both would have to make the head optional, which is how a pattern stops
#: saying which sentence it matches. "Another" is captured here too, for that
#: pattern's reason: it is CR 109.5's exclusion of the ability's own source, and
#: a card printing "if another enchantment is on the battlefield" means
#: something the article does not.
_IF_NOUN_ON_BATTLEFIELD = re.compile(
    r"^(?P<rest>.+?) if (?:(?P<other>another)|an?) (?P<board>.+) "
    r"(?:is|are) on the battlefield$"
)

#: "This creature can't block **if you control an untapped land**." (Branded
#: Brawlers, Veteran Brawlers.) The seat-scoped qualifier above printed with
#: "if" rather than "as long as" — for a static restriction the two words ask
#: one question, re-asked at every declaration, so it builds the same
#: ``{"who": "you", "subject": …}`` condition and is answered by the same
#: ``restriction_condition_holds``.
#:
#: **"You" only, and that is the gate rather than an omission.** The defending
#: player's spelling ("…can't attack if defending player controls an untapped
#: land", the Brawlers' *other* line, and Goblin Mutant's) is read by the
#: grammar's ``cant_attack_unless_defender_controls`` production, and
#: ``test_combat_restrictions_match_the_derivation_table_exactly`` holds a line
#: both readers claim to one payload — so a table row reading that sentence as
#: ``cant_attack`` with a condition would be a second reader of a line the
#: grammar already owns, disagreeing with it.
_IF_YOU_CONTROL = re.compile(
    r"^(?P<rest>.+?) if (?P<who>you) control an? (?P<board>.+)$"
)

#: The kinds whose enforcement site **asks** about a condition. A qualifier
#: attached to any other kind would be a restriction applied unconditionally —
#: silently, and in the direction of doing more than the card says — so the line
#: refuses instead and its card is reported unsupported naming the clause. This
#: is the same claim `activation_restrictions.payload_readable` makes: a row may
#: match more sentences than it implements, and the ones it does not implement
#: must refuse rather than drop a clause.
CONDITIONAL_RESTRICTION_KINDS: frozenset[str] = frozenset(
    # ``cant_block`` joined the set with Wirecat, and the *enforcement* moved
    # with it: ``declare_blockers_step._can_block_attacker`` used to answer this
    # kind with a bare membership test over the blocker's instruction kinds,
    # which cannot see a condition at all — so listing it without changing that
    # read would have grounded the Cat for the whole game on a clause that is
    # only sometimes true. Listing a kind here is a claim that its reader asks.
    #
    # ``cant_be_blocked`` joined it with Bouncing Beebles ("…as long as
    # defending player controls an artifact"), and **two** readers had to learn
    # to ask, which is the shape this set is really about: the declare-blockers
    # gate and ``legality.is_unblockable``, the predicate the UI fades a
    # creature with. A kind listed here whose second reader still answers
    # unconditionally is a board where the picker offers no block and the step
    # would have allowed one — the two disagreeing, which that predicate's own
    # docstring says is the failure it exists to prevent.
    {"cant_be_blocked", "cant_be_blocked_by", "cant_attack", "cant_block"}
)


def _printed_noun(phrase: str) -> dict | None:
    """One printed noun phrase, as the subject-filter payload that tests it.

    **The one reader of a noun in this file.** It began as the reader for an
    "as long as … controls …" board clause — the same question
    `activation_restrictions._controlled_board_phrase` and
    `untap_restrictions._blocked_subject` ask, so it got the same answer — and
    it is now what every union member goes through too. The five hand-written
    regexes that used to read those (`_blocker_noun`) are gone: they knew
    "creatures with flying" and "red creatures" but not the two stacked
    together, so every new printed narrowing cost this file a sixth pattern and
    the enforcement site a matching branch. That was the second vocabulary the
    note here used to promise to retire.

    None means the phrase is not one the noun parser reads *in full*, or is one
    carrying a key `subject_matches` cannot test — both of which refuse the
    whole line rather than admitting a restriction nobody can apply.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import (
        unimplemented_filter_keywords, untestable_filter_keys,
    )

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
    # A keyword the engine does not implement makes the filter inert rather than
    # unreadable, which for a restriction is a silent change to what is legal —
    # the check the five retired regexes each carried, kept in the one reader
    # that replaced them.
    if unimplemented_filter_keywords(payload):
        return None
    return payload


def restriction_condition_holds(
    game,
    condition: dict | None,
    *,
    observer: int | None,
    defender: int | None,
    source=None,
) -> bool:
    """Whether a restriction's qualifying clause holds right now.

    ``None`` — no clause — is True: an unqualified restriction always applies.

    The seat is read from the printed words: "defending player" is the seat
    being attacked, "you" is the seat whose ability this is (CR 109.5). A seat
    the caller cannot name answers False, which keeps the restriction *on*:
    for a clause the card prints as a condition for the restriction applying,
    the safe direction is the one that does not silently widen what may block.

    ``"anyone"`` is not a seat at all. "…if there's another creature **on the
    battlefield**" (Shauku, Endbringer) names CR 403.1's shared zone, so the
    scan is every seat's permanents and no seat has to be nameable for the
    clause to be answered — which is why it is a scope rather than a third
    value of the seat question.

    *source* is the permanent whose printed line this is, for the "another" the
    shared-zone qualifier can carry. With no source ``subject_matches`` refuses
    the key, which leaves the condition false and the restriction off — the
    direction that lets a creature attack rather than grounding it on a clause
    nobody could read.
    """
    if not condition:
        return True
    from .subject_filters import subject_matches

    described = condition.get("subject") or {}
    if condition.get("who") == "anyone":
        return any(
            subject_matches(game, perm, described, observer=observer, source=source)
            for perm in game.all_permanents()
        )
    seat = defender if condition.get("who") == "defending_player" else observer
    if seat is None or not (0 <= seat < len(game.players)):
        return False
    return any(
        subject_matches(game, perm, described, observer=observer, source=source)
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
    qualifier = _AS_LONG_AS.match(normalized_line) or _IF_YOU_CONTROL.match(
        normalized_line
    )
    if qualifier is not None:
        board = _printed_noun(qualifier.group("board"))
        if board is None:
            return None
        condition = {"who": qualifier.group("who").replace(" ", "_"), "subject": board}
        normalized_line = qualifier.group("rest").strip()
    else:
        # The battlefield-wide qualifier, tried only where the seat-scoped one
        # did not match: a sentence carries one condition clause, and reading
        # both would let a card state two and have one enforced.
        shared = _IF_ON_BATTLEFIELD.match(normalized_line)
        if shared is None:
            # …and its other printed word order (Wirecat), tried only where the
            # first did not match, for the same reason the first is tried only
            # where the seat-scoped one did not: one sentence, one clause.
            shared = _IF_NOUN_ON_BATTLEFIELD.match(normalized_line)
        if shared is not None:
            board = _printed_noun(shared.group("board"))
            if board is None:
                return None
            if shared.group("other"):
                # "Another" is a comparison against the ability's own source
                # (CR 109.5), which is exactly what `exclude_self` means to
                # `subject_matches` — so the word becomes the key every other
                # reader of a noun phrase already tests, rather than a second
                # spelling only this file would know.
                board = {**board, "exclude_self": True}
            condition = {"who": "anyone", "subject": board}
            normalized_line = shared.group("rest").strip()

    for pattern, kind in _PATTERNS:
        match = pattern.match(normalized_line)
        if match is None:
            continue
        # Every kind the row names has to be one whose enforcement site asks
        # about a condition — including the second and third of a multi-kind
        # row. A pair used to be refused outright, which was right while
        # ``cant_block`` was asked as a bare kind test and is the wrong shape
        # now that it is not: what makes a clause safe to attach is that its
        # reader asks, and that is a question about each kind rather than about
        # how many of them one sentence prints.
        named_kinds = kind if isinstance(kind, tuple) else (kind,)
        if condition is not None and not all(
            each in CONDITIONAL_RESTRICTION_KINDS for each in named_kinds
        ):
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
        # Both spellings reach the same `mana` key: what a printed symbol run
        # means does not depend on whether the sentence was about attacking or
        # about blocking, and one key is what lets the two enforcement sites
        # share `mana_cost_label` and `plan_payment` without either knowing the
        # other's regex.
        # "…{1} for each +1/+1 counter on it." The multiplier travels beside the
        # cost under the name ``lord_buffs.LordBuff`` already gives a printed
        # "for each … counter on this <noun>" tail, so the two tables spell one
        # clause one way.
        per_counter = payload.pop("attack_per_counter", None)
        if per_counter is not None:
            payload["per_counter"] = per_counter
        printed_cost = payload.pop("attack_mana", None) or payload.pop("block_mana", None)
        # "…pays {X} …, where X is the number of <counted>." (Collective
        # Restraint.) The two halves are admitted together or not at all: an
        # {X} with no definition is a price nobody can name, and a definition
        # over a printed number defines an X nothing reads — the same pair of
        # refusals ``lowering/where_x`` makes for a sentence. The price travels
        # as ``{"generic": "x"}``, the spelling every other payable X in this
        # engine uses, with the count beside it under the shared key.
        x_definition = payload.pop("attack_x_definition", None)
        if x_definition is not None or (printed_cost or "").lower() == "{x}":
            from .grammar import board_count_spec_for

            spec = board_count_spec_for(x_definition or "")
            if spec is None or (printed_cost or "").lower() != "{x}":
                return None
            payload["mana"] = {"generic": "x"}
            payload[X_FROM_COUNT] = spec
        elif printed_cost is not None:
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
        # "All <noun phrase> able to block this creature do so." The regex ends
        # in `.+`, so a phrase admitted unread would be a *requirement* over a
        # set nobody described — and the blockers step, handed an empty filter,
        # compels the whole board, which is Lure rather than Talruum Piper.
        # Refusing is the direction that leaves the card unsupported and named.
        compelled = payload.pop("compelled_blockers", None)
        if compelled is not None:
            described = _printed_noun(compelled)
            if described is None:
                return None
            payload["blocker_filter"] = described
        # "This creature can block only creatures with **flying**." The captured
        # word must actually be a keyword ability, for the reason the captured
        # *subtype* below must be a subtype: the enforcement asks
        # ``Game._has_keyword``, which answers False for a word no card carries
        # — so a phrase the vocabulary has never heard of would make the
        # creature able to block **nothing at all** while its card reported
        # supported. That is the narrowing direction rather than the widening
        # one, and it is still a card doing something other than what it prints.
        #
        # The catalog rather than ``IMPLEMENTED_KEYWORDS``, because the question
        # here is what the *enforcement* can answer and `_has_keyword` reads the
        # printed keyword off layer 6 whether or not this engine implements the
        # behaviour behind it — Shadowstorm hit exactly the shadow creatures for
        # a whole set before shadow was implemented, for that reason.
        required_keyword = payload.get("required_keyword")
        if required_keyword is not None and required_keyword not in _KEYWORD_WORDS:
            return None
        # "…can block creatures with shadow **as though it had shadow**."
        # The keyword is captured twice and both halves must name the same
        # ability, for `evasion_negation._TEMPLATE`'s reason: the sentence
        # states the restriction it lifts and then names the ability that lifts
        # it, and matching on the first half alone would read a card that says
        # something else. And the word has to be one the enforcement site reads
        # (:data:`_AS_THOUGH_BLOCKABLE`) — a permission the blockers step never
        # consults is a line the support gate would accept for behaviour that
        # does not exist, which is the widening direction this whole file
        # refuses in.
        as_though = payload.pop("as_though_keyword", None)
        if as_though is not None:
            if payload.pop("as_though_repeat", None) != as_though:
                return None
            if as_though not in _AS_THOUGH_BLOCKABLE:
                return None
            payload["keyword"] = as_though
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
        # "This creature can't block <union>." The mirror of the clause above —
        # that one names what may not block *this*, this one names what *this*
        # may not block — so it is the same union parsed by the same reader, and
        # a phrase it cannot read refuses the line rather than admitting a
        # restriction the enforcement site would then apply to nobody.
        blockees = payload.pop("blockees", None)
        if blockees is not None:
            filters = _blocker_union(blockees, card_name)
            if filters is None:
                return None
            payload["blockee_filters"] = filters
        # "…can't block **or be blocked by** <union>." (Sneaky Homunculus.)
        # One phrase, both directions: the same union read once by the same
        # reader, written under the key each of the row's two kinds is
        # enforced through. Refused whole when the phrase is unreadable, for
        # both clauses' own reasons above.
        either = payload.pop("block_either", None)
        if either is not None:
            filters = _blocker_union(either, card_name)
            if filters is None:
                return None
            payload["blockee_filters"] = filters
            payload["blocker_filters"] = [dict(described) for described in filters]
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
        # "If **a creature you control** attacks…" — the noun the requirement
        # is conditional on, read here for the reason every other noun on this
        # page is read here: the regex ends in `.+`, and a phrase admitted
        # unread would be a requirement conditional on nothing, which fires on
        # every declaration.
        # "…unless you control more **lands** than defending player."
        # (Monstrous Hound.) The counted noun, read here for the reason every
        # other noun on this page is read here: the regex ends in `.+`, and a
        # phrase admitted unread would be a comparison over *every* permanent
        # both players control — a restriction that answers a question the card
        # never asked, and one that would let the creature attack on boards
        # where its own clause forbids it.
        outnumbered = payload.pop("outnumbered_board", None)
        if outnumbered is not None:
            described = _printed_noun(outnumbered)
            if described is None:
                return None
            payload["subject"] = described
        # "…unless you tap **an untapped creature** you control…" (Hollow
        # Warrior.) What the declaration cost taps, read here for the reason
        # every other noun on this page is: a phrase admitted unread would be a
        # cost any permanent pays — a land tapped for an attack — and the
        # article is stripped because the count is the sentence's "an", one.
        tap_cost = payload.pop("tap_cost", None)
        if tap_cost is not None:
            described = _printed_noun(tap_cost.split(" ", 1)[1])
            if described is None:
                return None
            payload["tap_filter"] = described
            payload["count"] = 1
        attack_partner = payload.pop("attack_partner", None)
        if attack_partner is not None:
            described = _printed_noun(attack_partner)
            if described is None:
                return None
            payload["subject"] = described
        # "**Creatures you control** attack each combat if able." (Pursued
        # Whale's Pirate token.) The set the requirement reaches, read here for
        # the reason every other noun on this page is: the regex ends in `.+`,
        # and a phrase admitted unread would be a requirement over *every*
        # creature on the table — which for a requirement is the direction that
        # forces attacks nobody printed.
        must_attack_subject = payload.pop("must_attack_subject", None)
        if must_attack_subject is not None:
            described = _printed_noun(must_attack_subject)
            if described is None:
                return None
            payload["subject"] = described
        # "**If a creature with a magnet counter on it attacks**, …" (Magnetic
        # Web.) The other half of the same sentence: who has to be attacking
        # for the requirement to apply. Read here beside the set it compels,
        # and refused unread for that key's reason — a condition nobody checks
        # is a requirement that applies always.
        attack_condition = payload.pop("attack_condition", None)
        if attack_condition is not None:
            described = _printed_noun(attack_condition)
            if described is None:
                return None
            payload["condition_subject"] = described
        # "…unless you've cast **a creature spell** this turn." (Mogg
        # Conscripts.) Read here for the reason every other noun on this page is
        # read here — the regex ends in `.+`, and a phrase admitted unread would
        # be a restriction conditional on nothing, which for an *unless* clause
        # means a creature that can never attack. Through the casting gate's own
        # reader, because a spell is not a permanent and because Skyshroud
        # Condor reads the identical phrase.
        after_cast = payload.pop("attack_after_cast", None)
        if after_cast is not None:
            from .cast_restrictions import cast_spell_filter

            described = cast_spell_filter(after_cast)
            if described is None:
                return None
            payload["spell_filter"] = described
        # "**Creatures with flying** can block only **creatures with
        # flying**." Both halves read here for the reason every other noun on
        # this page is read here: the regex ends in `.+`, and a phrase admitted
        # unread would be a restriction the gate accepts and the enforcement
        # applies to the wrong set -- in this direction, to *every* blocker.
        block_only_subject = payload.pop("block_only_subject", None)
        if block_only_subject is not None:
            subject = _printed_noun(block_only_subject)
            allowed = _printed_noun(payload.pop("block_only_allowed", ""))
            if subject is None or allowed is None:
                return None
            payload["subject"] = subject
            payload["allowed"] = allowed
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
        # "**Nonblack** creatures can't attack you unless…" / "**Black**
        # creatures can't attack you." Both rows delimit a printed noun phrase
        # and both read it here, through the one noun reader on this page — a
        # phrase it cannot read refuses the line rather than admitting a toll or
        # a prohibition scoped to a set nobody can test, which for a *defensive*
        # restriction is the direction that stops legal attacks.
        # "**Nonblue** creatures can't block **creatures you control** unless…"
        # Both halves are printed noun phrases and both are read here, through
        # the one noun reader on this page: the regex ends the blockee half in
        # `.+`, and a phrase admitted unread would be a toll charged for
        # blocking a set nobody described — which on this sentence is every
        # attacker at the table.
        block_pay_subject = payload.pop("block_pay_subject", None)
        if block_pay_subject is not None:
            subject = _printed_noun(block_pay_subject)
            blockees = _printed_noun(payload.pop("block_pay_blockees", ""))
            if subject is None or blockees is None:
                return None
            payload["subject"] = subject
            payload["blockee_filters"] = [blockees]
        # The printed number of life, as an int the payment reads. Converted
        # for the reason the mana run above is: a payload whose shape depends
        # on which regex matched is how a cost silently stops being charged.
        block_life = payload.pop("block_life", None)
        if block_life is not None:
            payload["life"] = int(block_life)
        for captured in ("attack_pay_subject", "attack_you_subject"):
            phrase = payload.pop(captured, None)
            if phrase is not None:
                described = _printed_noun(phrase)
                if described is None:
                    return None
                payload["subject"] = described
        # "**Creatures with flying** can't attack or block, and…" (Katabatic
        # Winds.) The one noun phrase all three of that sentence's prohibitions
        # are about, read here through the one noun reader on this page: the
        # regex ends the subject in `.+`, and a phrase admitted unread would
        # ground *every* creature on the board and shut off every tap ability
        # there is.
        cant_act_subject = payload.pop("cant_act_subject", None)
        if cant_act_subject is not None:
            described = _printed_noun(cant_act_subject)
            if described is None:
                return None
            payload["subject"] = described
        # "**Creatures** can't attack." / "**Red creatures** can't attack." The
        # whole printed subject, read by the one noun reader on this page. A
        # phrase it cannot read refuses the line: the enforcement site hands an
        # empty filter to `subject_matches`, which answers True for every
        # creature — so an unread narrowing here does not do less, it grounds
        # the whole board.
        board_attack_subject = payload.pop("board_attack_subject", None)
        if board_attack_subject is not None:
            described = _printed_noun(board_attack_subject)
            if described is None:
                return None
            payload["subject"] = described
        # "All **creatures** block each combat if able." The same reader and
        # the same refusal, and the direction of a dropped narrowing is the
        # mirror of the one above: an empty filter would compel every creature
        # on the board to block rather than the ones the card names.
        must_block_subject = payload.pop("must_block_subject", None)
        if must_block_subject is not None:
            described = _printed_noun(must_block_subject)
            if described is None:
                return None
            payload["subject"] = described
        # "Each **creature you control** can't be blocked by more than one
        # creature." Same reader and same refusal, and the direction of a
        # dropped narrowing is the same: a ceiling over an empty filter caps
        # every creature on the board rather than the ones the card names.
        blocked_more_subject = payload.pop("blocked_more_subject", None)
        if blocked_more_subject is not None:
            described = _printed_noun(blocked_more_subject)
            if described is None:
                return None
            payload["subject"] = described
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
        # A row may name several kinds (see ``CombatRestriction.also_kinds``).
        # The first is the one every existing caller reads off ``.kind``; the
        # rest ride beside it, and a caller that cannot honour them refuses
        # rather than dropping them silently.
        if isinstance(kind, tuple):
            return CombatRestriction(kind[0], payload, also_kinds=tuple(kind[1:]))
        return CombatRestriction(kind, payload)
    return None


def _blocker_union(phrase: str, card_name: str | None = None) -> list[dict] | None:
    """The filters a noun-phrase union names, or None.

    Three rows carry one: the blocker whitelist ("can't be blocked except by
    Walls and/or creatures with flying"), the attack-exception list ("Except
    for creatures named Akron Legionnaire and artifact creatures, …") and the
    blocking restriction ("can't block white creatures with power 2 or
    greater"). One parser, because the members are the same printed vocabulary
    and a phrase readable in one union and not the others would be a fork
    nobody could find.

    **Each member is read by the grammar's noun parser**, which is the second
    reader this file used to keep — five hand-written regexes that knew
    "creatures with flying" and "red creatures" but not the two stacked
    together, so Orcish Veteran's phrase needed a sixth. Retiring it is what
    this file's own note asked for; the payloads are the ones
    ``subject_matches`` already tests, so nothing downstream learned a new
    vocabulary.

    None means "the noun parser does not read that phrase", which keeps the card
    unsupported with the clause named. Returning a partial union instead would
    be an evasion ability that lets through more than the card allows — or an
    exception list that exempts fewer creatures than the card prints.
    """
    phrase = _restore_own_name(phrase.strip(), card_name)
    if phrase is None:
        return None
    # **Whole phrase first.** A union member may itself contain "or" ("creatures
    # with power 2 or greater"), and splitting first turns that into two members
    # of which the first — "creatures with power 2" — reads as an *exact* power.
    # That is the silent narrowing this ordering exists to prevent, and it is
    # safe only because the noun parser refuses a phrase it cannot consume in
    # full: "Walls and/or creatures with flying" leaves tokens over and comes
    # back None, so a real union still reaches the split below.
    whole = _printed_noun(phrase)
    if whole is not None:
        return [whole]
    filters: list[dict] = []
    for part in re.split(r"\s*(?:and/or|and|or)\s+", phrase):
        part = part.strip()
        if not part:
            continue
        described = _printed_noun(part)
        if described is None:
            return None
        filters.append(described)
    return filters or None


def _restore_own_name(phrase: str, card_name: str | None) -> str | None:
    """*phrase* with "this creature" put back to the printed card name.

    "creatures named **this creature**" is what ``oracle._restriction_line``
    collapsed Akron Legionnaire's self-naming exception to; the filter matches
    by *name* rather than by identity, so a second copy and a token wearing the
    name are both excepted. A caller with no name to give gets a refusal rather
    than a filter that matches nothing.
    """
    if "named this creature" not in phrase:
        return phrase
    if not card_name:
        return None
    return phrase.replace("named this creature", f"named {card_name}")


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


#: The **whitelist** granted for a turn — "Target creature can't be blocked
#: this turn except by Walls" (Joven's Tools). Its own record rather than a
#: polarity flag on the one above, for the reason the two static kinds are two
#: kinds: "can't be blocked by Walls" lets the rest of the board through and
#: "except by Walls" lets none of it through, so a record read as the other is
#: an evasion ability inverted rather than narrowed.
#:
#: A list **of lists**: each grant is one restriction (CR 509.1b), and a blocker
#: must satisfy every one of them separately — folding two grants into one union
#: would let a creature legal under either through both.
#: Swept with the turn by ``mixins/_constants._EOT_METADATA_KEYS``.
GRANTED_BLOCKER_WHITELISTS = "cant_be_blocked_except_by_until_eot"


def grant_blocker_whitelist(permanent, allowed: list[dict]) -> None:
    """Record that only creatures matching one of *allowed* may block
    *permanent* for the rest of the turn (CR 509.1b)."""
    record = [list(entry) for entry in granted_blocker_whitelists(permanent)]
    entry = [dict(described) for described in allowed]
    if entry not in record:
        record.append(entry)
    permanent.metadata[GRANTED_BLOCKER_WHITELISTS] = record


def granted_blocker_whitelists(permanent) -> tuple[list[dict], ...]:
    """Every blocker whitelist *permanent* has been given this turn, each one a
    union of the classes that single grant admits."""
    metadata = getattr(permanent, "metadata", None)
    if not metadata:
        return ()
    return tuple(metadata.get(GRANTED_BLOCKER_WHITELISTS) or ())


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


def defender_attack_cap(permanents) -> int | None:
    """How many creatures may attack the seat controlling *permanents*, or None.

    "No more than two creatures can attack **you** each combat." (Crawlspace.)
    :func:`participation_cap` one narrowing over, and the caller is what supplies
    the narrowing: it hands the permanents **one seat controls**, because "you"
    is the controller of the permanent printing the clause (CR 109.5) and a
    Crawlspace protects nobody else at the table.

    The **smallest** cap wins, for that function's reason exactly: each printed
    clause is a restriction in its own right (CR 508.1c), and two Crawlspaces —
    or one beside a card printing a different number — are answered without
    either card knowing the other exists.

    Its own function rather than a ``kind`` argument on the one above: that one
    is asked once of the whole board and this once per defending seat, and a
    shared body taking "which kind" would let a caller ask the global question
    with a seat's permanents, which is a cap silently applied to the wrong
    declaration.
    """
    from .oracle import compile_card_oracle

    caps = [
        int(instruction.payload.get("count", 0))
        for permanent in permanents
        for instruction in compile_card_oracle(permanent.effective_card).instructions
        if instruction.kind == "max_attackers_on_you_each_combat"
    ]
    return min(caps) if caps else None

def declaration_greater_power_required(permanent, kind: str) -> bool:
    """Whether *permanent* may only *kind* alongside a creature that outpowers it.

    "This creature can't attack unless a creature with greater power also
    attacks." (Okk, and its blocking twin one line down.) The sibling of
    :func:`declaration_company_required` beside it and the same CR 508.1c /
    CR 509.1b question — a floor a creature puts on the declaration it joins,
    which no per-creature predicate can answer because it is about who *else*
    was declared.

    A bool rather than a number because there is nothing to carry: the printed
    clause names no count and no noun beyond "a creature", and the threshold it
    compares against is this permanent's own power, which the caller reads live
    (CR 613: power is computed, so a pumped Okk needs a bigger friend).

    Read off ``effective_card`` like every other combat restriction here, so a
    copy or a text change is answered without a second reader.
    """
    from .oracle import compile_card_oracle

    wanted = f"cant_{kind}_unless_greater_power_{kind}s"
    return any(
        instruction.kind == wanted
        for instruction in compile_card_oracle(permanent.effective_card).instructions
    )


def declaration_companion_required(permanent) -> tuple[dict, ...]:
    """The noun phrase(s) another declared attacker must answer for *permanent*
    to attack — empty when it prints no such restriction.

    "This creature can't attack unless a black or green creature also
    attacks." (Scarred Puma.) :func:`declaration_greater_power_required`'s
    sibling: the same CR 508.1c floor on the declaration the creature joins,
    with a described companion where that one compares power. The filter is
    payload and is tested by ``subject_matches`` at the gate, so the companion's
    colour is read through the layers at the moment of the declaration — a
    creature a Lace has turned green escorts the Puma, and a green one turned
    white no longer does.

    A tuple because a creature may be granted the sentence twice and each
    printing is its own restriction to satisfy. Read off ``effective_card``
    like every other combat restriction here.
    """
    from .oracle import compile_card_oracle

    return tuple(
        dict(instruction.payload.get("companion") or {})
        for instruction in compile_card_oracle(permanent.effective_card).instructions
        if instruction.kind == "cant_attack_unless_subject_attacks"
    )


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


def declaration_tap_costs(permanent, kind: str) -> list[dict]:
    """What *permanent* must have tapped to *kind* (``"attack"`` / ``"block"``),
    one filter per creature owed.

    "…can't attack or block unless you tap an untapped creature you control not
    declared as an attacking or blocking creature this combat." (Hollow
    Warrior.) CR 508.1h / CR 509.1d's cost — "tapping permanents" is in both
    rules' own list — in its third currency here, beside the sacrifice
    (Leviathan) and the mana (Brainwash). A list rather than a number because
    each clause is a cost of its own and every one is paid (CR 508.1j).

    Read off ``effective_card`` like every other combat restriction here, so a
    copy or a text change is answered without a second reader; the *plan* —
    which creatures pay — needs the board and lives with the steps
    (``CombatPhaseMixin.declaration_tap_plan``).
    """
    from .oracle import compile_card_oracle

    wanted = f"cant_{kind}_unless_tap"
    owed: list[dict] = []
    for instruction in compile_card_oracle(permanent.effective_card).instructions:
        if instruction.kind != wanted:
            continue
        described = dict(instruction.payload.get("tap_filter") or {})
        owed.extend([described] * max(0, int(instruction.payload.get("count", 1))))
    return owed
