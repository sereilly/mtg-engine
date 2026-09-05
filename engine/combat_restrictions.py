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
#   creatures_cant_attack_you_unless_pay
#                                   phases/declare_attackers_step.can_attack
#                                   + declare_attackers (the charge)
#   creatures_cant_attack_you       phases/declare_attackers_step.can_attack
#   subject_cant_block_subject_unless_pay_life
#                                   phases/declare_blockers_step._can_block_attacker
#                                   + declare_blockers (the charge)
#   cant_block                      phases/declare_blockers_step
#   must_attack_each_combat         phases/declare_attackers_step._must_attack_if_able
#   must_attack_if_partner_attacks  phases/declare_attackers_step.declare_attackers
#                                   (the declaration, not the creature)
#   attacks_as_though_hasty_unless_it_entered
#                                   phases/declare_attackers_step.can_attack
#   cant_be_blocked_by              phases/declare_blockers_step
#   cant_be_blocked_except_by       phases/declare_blockers_step
#   cant_block_subject              phases/declare_blockers_step
#   cant_block_power_n_or_greater_unless_pay  phases/declare_blockers_step
#                                   + declare_blockers (the charge)
#   creatures_that_attacked_last_turn_cant_attack
#                                   phases/declare_attackers_step.can_attack
#   can_block_only_with_keyword     phases/declare_blockers_step
#   subject_can_block_only          phases/declare_blockers_step (a board scan)
#   must_be_blocked                 phases/declare_blockers_step
#   must_be_blocked_by_all_able     phases/declare_blockers_step
#   max_attackers_each_combat       phases/declare_attackers_step.declare_attackers
#   max_blockers_each_combat        phases/declare_blockers_step.declare_blockers
#   cant_attack_unless_others_attack  phases/declare_attackers_step.declare_attackers
#   cant_block_unless_others_block  phases/declare_blockers_step.declare_blockers
_PATTERNS: tuple[tuple[re.Pattern[str], "str | tuple[str, ...]"], ...] = (
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
        # "…unless you pay {1} **for each +1/+1 counter on it**." (Phyrexian
        # Marauder.) The toll above with a multiplier, and the multiplier is
        # payload for the reason the symbol run is: a card printing "{2} for
        # each charge counter" is the same restriction. The counter word is
        # resolved to its store by ``pt.pt_counter_key`` at the charge, so the
        # three P/T kinds and every invented one are counted from the pile the
        # placement actually filled.
        #
        # Optional, so this row still reads Brainwash's unmultiplied printing —
        # a second row would be one sentence with two readers, and the tail is
        # what makes the price a *reading of the board* rather than a number.
        # A creature holding none of the named counter owes nothing, which is
        # what "for each" means at zero and what Phyrexian Marauder cast for
        # X=0 is.
        re.compile(
            r"^this creature can't attack unless (?:you pay|its controller pays) "
            r"(?P<attack_mana>(?:\{[^}]+\})+)"
            r"(?: for each (?P<attack_per_counter>[+-]\d+/[+-]\d+|[a-z][a-z-]*) "
            r"counter on it)?$"
        ),
        "cant_attack_unless_pay",
    ),
    (
        # "Creatures can't attack you unless their controller pays {2} for each
        # creature they control that's attacking you." (Koskun Falls.) The same
        # CR 508.1g cost read from the *defending* side: the row above is
        # printed on the attacker (or on an Aura about it) and this one on a
        # permanent the defending player controls, so the third channel
        # ``_attack_mana_costs_of`` consults is the defender's own board.
        #
        # "**For each** creature they control that's attacking you" needs no
        # multiplier here, and that is the whole reason this is the same shape
        # as Brainwash rather than a scaling one: the declaration's cost is
        # summed per attacker already (``_declaration_mana_plan``), so a
        # per-attacker {2} *is* {2} for each attacking creature. A payload
        # carrying the multiplication would be a second way to say what the
        # summing already says, free to disagree with it.
        # The subject is a **printed noun phrase**, not the bare word: "Nonblack
        # creatures can't attack you unless…" (Elephant Grass) is the same toll
        # narrowed, and Koskun Falls' unnarrowed printing reduces to
        # "creatures", which is a filter matching every creature. One row rather
        # than two, because the narrowing is data — a card printing any other
        # colour, type or keyword needs no pattern here.
        re.compile(
            r"^(?P<attack_pay_subject>[a-z' -]*creatures) can't attack you "
            r"unless their controller pays "
            r"(?P<attack_mana>(?:\{[^}]+\})+) for each creature they control "
            r"that's attacking you$"
        ),
        "creatures_cant_attack_you_unless_pay",
    ),
    (
        # "Black creatures can't attack you." (Elephant Grass.) The row above
        # with no toll at all — a flat prohibition, and one scoped to a
        # *defender*: "you" is the permanent's controller (CR 109.5), which is
        # what separates this from `creatures_cant_attack` beside it. That kind
        # forbids the attack outright wherever it is aimed (Moat), and reading
        # this sentence as one would ground the creature against every seat at
        # the table instead of against the one the card protects.
        #
        # Below the toll row so a line printing both clauses reaches the toll:
        # the anchors already keep them apart (that sentence does not end in
        # "can't attack you"), and the order is what keeps that from being a
        # coincidence.
        re.compile(r"^(?P<attack_you_subject>[a-z' -]*creatures) can't attack you$"),
        "creatures_cant_attack_you",
    ),
    (
        # "Nonblue creatures can't block creatures you control unless their
        # controller pays 1 life for each blocking creature they control."
        # (Heat Wave.) The blocking twin of Elephant Grass' toll two rows up,
        # and the first cost in this file paid in **life** rather than mana
        # (CR 118.3b/509.1d) — which is why the capture is its own key: what a
        # printed symbol run means and what a printed number of life means are
        # two different payments, and one key would let the two enforcement
        # sites read a life total as a mana pool.
        #
        # Read here rather than by the grammar because the grammar refuses the
        # line in full: `effects/combat.py`'s "can't block <noun phrase>"
        # production has no reading for the "unless" tail, so it leaves the
        # words unconsumed and the whole line comes to this table — which is
        # the ordering CLAUDE.md requires, a parsed-but-unlowered sentence
        # would take the table's line away.
        re.compile(
            r"^(?P<block_pay_subject>[a-z' -]*creatures) can't block "
            r"(?P<block_pay_blockees>.+) unless their controller pays "
            r"(?P<block_life>\d+) life for each blocking creature they control$"
        ),
        "subject_cant_block_subject_unless_pay_life",
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
        # "Creatures with flying can't attack or block, and their activated
        # abilities with {T} in their costs can't be activated." (Katabatic
        # Winds.) **One sentence, three prohibitions, one subject** — see
        # ``CombatRestriction.also_kinds``. The noun phrase is read by
        # `_printed_noun` like every other on this page, so a card printing
        # "Red creatures can't attack or block, and…" is this rule with nothing
        # added.
        #
        # The third kind is not a combat restriction and is enforced in
        # ``mixins/stack/activation.py``, beside the Aura ban that reads Faith's
        # Fetters' identically-shaped clause. It is derived **here** anyway,
        # because it is a clause of *this* sentence: a second table matching the
        # same printed line would be free to read a different subject out of it,
        # and the one that dropped its half would leave an enchantment that
        # grounds every flier and lets their tap abilities keep working — which
        # is the silent direction this whole file exists to refuse.
        #
        # "With {T} in their costs" is the printed narrowing and it is part of
        # the kind rather than payload: what an ability's cost contains is not a
        # noun phrase `subject_matches` can answer, and the only other printing
        # in the pool ("its activated abilities can't be activated unless
        # they're mana abilities", Faith's Fetters) narrows along a different
        # axis and already has its own name.
        re.compile(
            r"^(?P<cant_act_subject>.+) can't attack or block, and their "
            r"activated abilities with \{t\} in their costs can't be activated$"
        ),
        ("creatures_cant_attack", "creatures_cant_block",
         "tap_abilities_cant_be_activated"),
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
    # "**If a creature you control attacks**, this creature also attacks if
    # able." (Ekundu Cyclops.) CR 508.1d's requirement with a condition, and
    # the condition is about the *declaration being made* rather than about the
    # board — which is why it cannot ride `must_attack_each_combat`'s
    # per-creature predicate and gets its own kind. The noun phrase is payload
    # for every other noun in this file's reason: a card printing "if a Goblin
    # you control attacks" is this rule, not a new one.
    #
    # "Also" is what says the condition excludes the creature itself: a lone
    # Cyclops is not "a creature you control" that attacked, so nothing
    # requires it to attack. The enforcement site tests the *other* declared
    # attackers, which is the only reading that does not make the requirement
    # self-satisfying.
    (
        re.compile(
            r"^if an? (?P<attack_partner>.+) attacks, "
            r"this creature also attacks if able$"
        ),
        "must_attack_if_partner_attacks",
    ),
    # "This creature can attack as though it had haste unless it entered this
    # turn." (Chaos Lord.) A *permission* rather than a restriction, and here
    # for the reason `combat_permissions.CANT_BLOCK_UNTIL_EOT` lives beside a
    # permission in its own file: this is a printed clause on a creature, read
    # by the declare-attackers step and gated by the same support gate as every
    # row around it, and which direction it points does not change any of that.
    #
    # CR 302.6 is what it lifts, and only its attack half — the creature still
    # cannot use a {T} ability the turn it changes hands, which is what makes
    # this an "as though" permission (CR 609.4) and not a haste grant.
    #
    # The exception is the whole reason the clause is on this card: Chaos Lord
    # hands itself to an opponent every upkeep, and CR 302.6 would leave the new
    # controller unable to attack with it. Reading "entered this turn" off the
    # sickness stamp would answer yes because of that very control change, so it
    # is read off `enter_effects.ENTERED_BATTLEFIELD_TURN`, which nothing
    # rewrites.
    (
        re.compile(
            r"^this creature can attack as though it had haste "
            r"unless it entered this turn$"
        ),
        "attacks_as_though_hasty_unless_it_entered",
    ),
    # "…can't be blocked by **Walls**" (Invisibility's mirror, Ali Baba's
    # targets) and "…can't be blocked by **artifact creatures**" (Argothian
    # Pixies, Artifact Ward). One restriction: what differs is the noun phrase,
    # which is payload for the same reason the land type and the power
    # threshold in this file are. Two rows because a subtype and a card type
    # are different captures, not because they are different rules — both
    # produce `cant_be_blocked_by` and one enforcement site asks
    # `subject_matches` about the blocker.
    (
        # "This creature can't be blocked by **more than one** creature."
        # (Stalking Tiger.) The ceiling to the floor above, and its own kind for
        # that reason: CR 509.1b makes every restriction apply, so a card
        # printing both would want the tighter of each and one kind carrying a
        # signed number could not say which end a value bounded.
        #
        # The number is payload like every number in this file, so "more than
        # two" is the same restriction. Checked over the finished assignment at
        # the same site the floor is, because it is a restriction on the
        # declaration as a whole rather than on any single blocker pair.
        #
        # **Above the general "can't be blocked by <noun>" row**, which reads
        # any bare noun phrase and would consume "more than one creature" as
        # one — producing a filter matching nothing, so the restriction would go
        # inert and the creature would be blockable by anything. Order is the
        # only thing that separates them, because the general row's whole point
        # is that it does not enumerate what a blocker may be.
        re.compile(
            r"^this creature can't be blocked by more than "
            r"(?P<count>\w+) creatures?$"
        ),
        "cant_be_blocked_by_more_than",
    ),
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
        # "Enchanted creature can't be blocked unless defending player pays {3}
        # **for each creature they control that's blocking it**." (Awesome
        # Presence, through the Aura subject rewrite.) CR 509.1b's restriction
        # with CR 509.1d's cost hung off it — the mirror of Brainwash's
        # ``cant_attack_unless_pay`` above, printed about the attacker and owed
        # by the *defender*.
        #
        # **The multiplier needs no payload**, for Koskun Falls' reason two
        # rows up: ``_block_mana_costs_of`` is asked once per (blocker,
        # attacker) pair and ``_block_declaration_mana_plan`` sums the pairs, so
        # a per-pair {3} already *is* "{3} for each creature blocking it". A
        # payload carrying the multiplication would be a second way to say what
        # the summing says, free to disagree with it.
        re.compile(
            r"^this creature can't be blocked unless defending player pays "
            r"(?P<block_mana>(?:\{[^}]+\})+) for each creature they control "
            r"that's blocking it$"
        ),
        "cant_be_blocked_unless_pay",
    ),
    (
        # "…can't be blocked except by **three or more creatures**" (Gorilla
        # Berserkers). Menace with the number printed out (CR 702.111a is
        # exactly the N=2 case of this sentence), so it is a *count* rather
        # than a noun union — which is why it is read here, above the union row
        # whose `.+` would otherwise swallow "three or more creatures" and hand
        # it to a noun parser that cannot read it.
        #
        # The number is payload, as every number in this file is, and the
        # enforcement site takes the largest minimum any restriction imposes:
        # CR 509.1b's restrictions all apply, so a creature with menace *and*
        # this line needs three blockers, not two.
        re.compile(
            r"^this creature can't be blocked except by "
            r"(?P<count>\w+) or more creatures$"
        ),
        "cant_be_blocked_by_fewer_than",
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
        # "All Walls able to block this creature do so." (Marble Priest) /
        # "All creatures able to block…" (Elvish Bard) / "All creatures **with
        # flying** able to block…" (Talruum Piper). Lure's requirement
        # (CR 509.1c) narrowed to a printed noun, and printed on the creature
        # itself rather than on an Aura — so it is a template here beside the
        # others rather than a second copy of the Aura reader.
        #
        # **One row reading a whole noun phrase**, where this was two rows: one
        # alternating every creature type and one spelling out the bare
        # "creatures". Talruum Piper stacks a keyword onto the noun and would
        # have been the third, because the subtype alternation cannot express
        # "creatures with flying" and the bare row is anchored. The phrase is
        # read by `_printed_noun` and tested by `subject_matches` at the
        # declaration, exactly as `cant_be_blocked_by` beside it — so a card
        # printed "All red creatures able to block…" needs nothing here.
        re.compile(r"^all (?P<compelled_blockers>.+) able to block this creature do so$"),
        "must_be_blocked_by_all_able",
    ),
    (
        # "This creature can't block creatures with power 3 or greater **unless
        # you pay {1}**." (Hipparion.) CR 509.1b's restriction with CR 509.1a's
        # cost hung off it — the blocking twin of Brainwash's
        # `cant_attack_unless_pay`, and its own kind for the reason that one is
        # not a flag on `cant_attack`: the row above forbids the block outright
        # and this one merely prices it, so a payload key meaning "and there is
        # a way out" would make every unread cost an unconditional ban.
        #
        # It must sit **before** the unconditional row: that pattern is anchored
        # and would not match this sentence, but the ordering is the thing a
        # future edit could break, and a widened `$` there would silently turn
        # Hipparion into a creature that can never block a 3-power attacker.
        #
        # The threshold and the cost are both payload, for the reasons written
        # on their unconditional siblings.
        re.compile(
            r"^this creature can't block creatures with power (?P<power>\d+) or "
            r"greater unless (?:you pay|its controller pays) "
            r"(?P<block_mana>(?:\{[^}]+\})+)$"
        ),
        "cant_block_power_n_or_greater_unless_pay",
    ),
    (
        # "…can't block **creatures with power 2 or greater**" (Ironclaw Orcs),
        # "…**white creatures with power 2 or greater**" (Orcish Veteran).
        #
        # **One row, and the noun phrase is read by `_blocker_union`** — the
        # mirror of what `cant_be_blocked_by` above already does, and taken for
        # the same reason. This was a row that captured the *threshold* alone,
        # so a card printing any other narrowing of the same sentence had to
        # earn a second capture and a second branch at the enforcement site;
        # Orcish Veteran stacks a colour on the threshold and would have been
        # the second row. The phrase is payload now, tested by
        # ``subject_matches`` against the attacker.
        #
        # Below the priced row above it, whose sentence this pattern would also
        # match: the `.+` reaches to the end of the line, so "unless you pay
        # {1}" would be read as part of the noun phrase — where `_blocker_union`
        # refuses it and the whole line refuses, which is the safe direction but
        # not the right reading.
        re.compile(r"^this creature can't block (?P<blockees>.+)$"),
        "cant_block_subject",
    ),
    (
        # "Creatures that attacked during their controller's last turn can't
        # attack." (Halls of Mist.) Giant Turtle's restriction printed about the
        # **board** instead of about itself, so it is its own kind rather than
        # the self row's payload: that one is read off the attacker's own
        # program and this one has to be found by scanning every permanent, and
        # a single kind read by both loops would ground every creature the
        # moment one Turtle was in play.
        #
        # No parameters: the sentence names no seat, no type and no number. The
        # record it reads is the attack stamp `declare_attackers` already
        # writes, asked of each attacker's own controller — which is the active
        # player for anything being declared, so "their controller" and "you"
        # coincide at the only moment the question is asked.
        re.compile(
            r"^creatures that attacked during their controller's last turn "
            r"can't attack$"
        ),
        "creatures_that_attacked_last_turn_cant_attack",
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
    (
        # "**Creatures with flying** can block only creatures with flying."
        # (Chaosphere.) The row above printed about the *board* instead of
        # about one creature, which makes it a different rule and not that
        # row's payload: that one is read off the blocker's own program, and
        # this has to be found by scanning every permanent -- a single kind read
        # by both loops would ground every blocker in the game the moment one
        # Chaosphere was in play.
        #
        # Both noun phrases are payload, read by the one noun reader on this
        # page: a card printing "creatures with shadow can block only creatures
        # with shadow" is this rule, not a new one. Placed **after** the
        # self-scoped row, per this file's ordering rule -- that one's sentence
        # begins "this creature" and could not reach here, but a general row
        # ending in `.+` above it would have claimed the specific one.
        re.compile(
            r"^(?P<block_only_subject>creatures[^:]*?) can block only "
            r"(?P<block_only_allowed>.+)$"
        ),
        "subject_can_block_only",
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

#: The kinds whose enforcement site **asks** about a condition. A qualifier
#: attached to any other kind would be a restriction applied unconditionally —
#: silently, and in the direction of doing more than the card says — so the line
#: refuses instead and its card is reported unsupported naming the clause. This
#: is the same claim `activation_restrictions.payload_readable` makes: a row may
#: match more sentences than it implements, and the ones it does not implement
#: must refuse rather than drop a clause.
CONDITIONAL_RESTRICTION_KINDS: frozenset[str] = frozenset(
    {"cant_be_blocked_by", "cant_attack"}
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
    qualifier = _AS_LONG_AS.match(normalized_line)
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
        if condition is not None and (
            isinstance(kind, tuple) or kind not in CONDITIONAL_RESTRICTION_KINDS
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
        attack_partner = payload.pop("attack_partner", None)
        if attack_partner is not None:
            described = _printed_noun(attack_partner)
            if described is None:
                return None
            payload["subject"] = described
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
