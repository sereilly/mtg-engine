"""The rows of the text-keyed combat-restriction table (CR 506, 508, 509).

``_PATTERNS`` is every printed template
``combat_restrictions.combat_restriction_for`` reads, in the order it tries
them, each mapped to the instruction kind (or kinds) the combat steps dispatch
on. The comment above it names where each kind is enforced. One table in one
module, because its order is behaviour: the first row that matches a line is
the reading.

Split out of ``engine/combat_restrictions.py`` at the 2,000-line cap, where the
table alone was over half the module. The reader, the conditional riders it
takes off a line first and the per-declaration checks stay there.
"""

from __future__ import annotations

import re


# Basic land types a "controls a <type>" clause can name. Five, because a regex
# has to name what it matches — **not** because the engine can only enforce
# those: the check reads a filter through `subject_matches` now, and the
# grammar's production of the same kind reads any printed noun phrase.
_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")


# (pattern, kind) — enforced by:
#   cant_attack_unless_defender_controls  phases/attack_legality.can_attack
#   cant_attack_without_controlled_count  phases/attack_legality.can_attack
#   cant_attack                     phases/attack_legality.can_attack
#   controlled_creatures_cant_attack  phases/attack_legality.can_attack
#   creatures_cant_attack           phases/attack_legality.can_attack
#   cant_attack_if_attacked_last_turn  phases/attack_legality.can_attack
#   cant_attack_unless_defender_acted  phases/attack_legality.can_attack
#   cant_attack_unless_you_cast     phases/attack_legality.can_attack
#   cant_attack_unless_pay          phases/attack_legality.can_attack
#                                   + declare_attackers (the charge)
#   creatures_cant_attack_you_unless_pay
#                                   phases/attack_legality.can_attack
#                                   + declare_attackers (the charge)
#   creatures_cant_attack_you       phases/attack_legality.can_attack
#   subject_cant_block_subject_unless_pay_life
#                                   phases/block_legality._can_block_attacker
#                                   + declare_blockers (the charge)
#   cant_block                      phases/block_legality
#   creatures_cant_block            phases/block_legality
#   must_attack_each_combat         phases/attack_legality._must_attack_if_able
#   creatures_must_attack           phases/attack_legality._must_attack_if_able
#                                   (a board scan)
#   creatures_must_attack_if_partner_attacks
#                                   phases/attack_legality._must_attack_beside
#                                   (a board scan over the declaration)
#   creatures_must_attack_if_source_attacks
#                                   phases/attack_legality._must_attack_beside
#                                   (the same scan, asking identity)
#   must_block_each_combat          phases/declare_blockers_step.declare_blockers
#   creatures_must_block            phases/block_legality._board_compels_block
#                                   (a board scan)
#   attacker_chooses_blocks         phases/combat_phase.block_chooser_index
#                                   (the declaration, CR 509.1c)
#   must_attack_if_partner_attacks  phases/declare_attackers_step.declare_attackers
#                                   (the declaration, not the creature)
#   attacks_as_though_hasty_unless_it_entered
#                                   phases/attack_legality.can_attack
#   subject_ignores_defender        phases/attack_legality._ignores_defender
#   cant_be_blocked_while_attacking_alone
#                                   phases/block_legality
#   cant_be_blocked_by              phases/block_legality
#   cant_be_blocked_except_by       phases/block_legality
#   cant_block_subject              phases/block_legality
#                                   (also the first half of "can't block or be
#                                   blocked by", whose second half is
#                                   cant_be_blocked_by above)
#   cant_block_power_n_or_greater_unless_pay  phases/declare_blockers_step
#                                   + declare_blockers (the charge)
#   creatures_that_attacked_last_turn_cant_attack
#                                   phases/attack_legality.can_attack
#   can_block_only_with_keyword     phases/block_legality
#   subject_can_block_only          phases/block_legality (a board scan)
#   must_be_blocked                 phases/declare_blockers_step
#   must_be_blocked_by_all_able     phases/declare_blockers_step
#   max_attackers_each_combat       phases/declare_attackers_step.declare_attackers
#   max_attackers_on_you_each_combat  phases/declare_attackers_step.declare_attackers
#   max_blockers_each_combat        phases/block_legality.block_declaration_refusal
#   cant_attack_unless_others_attack  phases/attack_legality.attack_declaration_refusal
#   cant_block_unless_others_block  phases/block_legality.block_declaration_refusal
#   cant_attack_unless_greater_power_attacks
#                                   phases/attack_legality.attack_declaration_refusal
#   cant_block_unless_greater_power_blocks
#                                   phases/block_legality.block_declaration_refusal
#   cant_attack_unless_subject_attacks
#                                   phases/attack_legality.attack_declaration_refusal
_PATTERNS: tuple[tuple[re.Pattern[str], "str | tuple[str, ...]"], ...] = (
    (
        # "No more than two creatures can attack **you** each combat."
        # (Crawlspace.) The row below narrowed to one **defending player**, and
        # its own kind rather than a payload flag on it, because the two count
        # different things: that one caps the declaration entire (Caverns of
        # Despair stops the third attacker whoever it is aimed at) and this caps
        # the attackers aimed at *one seat*. A flag the counting branch ignored
        # would make Crawlspace a Caverns — three attackers split two-and-one
        # across two opponents is legal under this card and illegal under that
        # one, and reading either as the other is a shipped card stricter or
        # looser than it prints.
        #
        # "You" is the controller of the permanent printing it (CR 109.5),
        # exactly as it is on ``creatures_cant_attack_you`` further down, which
        # is the other row in this file scoped to a defender. And "attack you"
        # is the *player*: an attack at a planeswalker its controller has is not
        # an attack at them (CR 508.1b), so the enforcement counts only the
        # attackers that named the seat itself — the same distinction Arboria's
        # row records one screen down.
        #
        # The number is payload for the row below's reason, and the plural is
        # optional for the same one.
        re.compile(
            r"^no more than (?P<count>\w+) creatures? can attack you each combat$"
        ),
        "max_attackers_on_you_each_combat",
    ),
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
    (
        # "This creature can't attack unless you control **more lands than
        # defending player**." (Monstrous Hound.) The row above asks whether one
        # board holds a described permanent; this asks whether one board holds
        # *more* of them than another, which is a different question and so a
        # different kind — the comparison needs both seats, and the row above's
        # enforcement scans one.
        #
        # The counted noun is payload (`.+` read by
        # `combat_restrictions._printed_noun` and refused when it is a phrase
        # `subject_matches` cannot test), so a card printing "more creatures
        # than" is this rule over a different set. The two *seats* are not
        # payload: CR 506.2 makes "you" the attacking player and the other one
        # the defending player, so the printed words are what the enforcement
        # step already knows — they stay in the pattern because a regex has to
        # name what it matches, and a sentence naming the other seat would be a
        # different card that has to earn its own row rather than borrow this
        # one's enforcement.
        re.compile(
            r"^this creature can't attack unless you control more "
            r"(?P<outnumbered_board>.+) than defending player$"
        ),
        "cant_attack_unless_you_control_more",
    ),
    (
        # Monstrous Hound's second line, and the mirror of the row above in
        # both directions: the seat compared against is the *attacking* player
        # (CR 508.1a: the active player, the only seat that declares attackers)
        # and the step that enforces it is the declare-blockers one. Its own
        # kind for the reason `creatures_cant_attack` and `creatures_cant_block`
        # are two: one kind answered at two steps is a kind one of them would
        # forget.
        re.compile(
            r"^this creature can't block unless you control more "
            r"(?P<outnumbered_board>.+) than attacking player$"
        ),
        "cant_block_unless_you_control_more",
    ),
    # "Enchanted creature can't attack unless its controller pays {3}."
    # (Brainwash.) CR 508.1h: an additional *cost* to attack, paid as attackers
    # are declared — the mana twin of Leviathan's "unless you sacrifice two
    # Islands", which the grammar reads because its cost is a parsed noun
    # phrase. This one's cost is a printed symbol run, which is exactly what a
    # derivation table can hold.
    #
    # Both spellings of the payer, and they are one seat rather than two: CR
    # 508.1a lets only the active player declare attackers, so the creature's
    # controller *is* "you" for any card that could print the other wording.
    # Whose text the sentence is on is the difference between Brainwash and a
    # creature printing it about itself —
    # `aura_restrictions.aura_combat_restriction` rewrites the subject and asks
    # this same table (idiom 14).
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
        # CR 508.1h cost read from the *defending* side: the row above is
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
        #
        # "…pays **{X}** for each creature they control that's attacking you,
        # **where X is the number of basic land types among lands you
        # control**." (Collective Restraint.) The same toll with a counted
        # price, and one row rather than two for the reason the narrowed
        # subject is one: what the clause defines is data. The definition is
        # read by the grammar's own where-clause reader
        # (``grammar.board_count_spec_for``) and evaluated at the declaration
        # for the toll's controller (CR 109.5: a static ability's "you"), so
        # the price follows the board up to the declaration and is then the
        # total CR 508.1h locks in — computed at the one reader both the gate
        # and the charge go through.
        re.compile(
            r"^(?P<attack_pay_subject>[a-z' -]*creatures) can't attack you "
            r"unless their controller pays "
            r"(?P<attack_mana>(?:\{[^}]+\})+) for each creature they control "
            r"that's attacking you"
            r"(?:, where x is (?P<attack_x_definition>.+))?$"
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
        #
        # "Creatures **of the chosen color without flying** can't attack you."
        # (Teferi's Moat.) The same row with the narrowing printed *behind* the
        # noun: English puts a colour word in front and "of the chosen color" /
        # "without flying" after, and the noun reader (`_printed_noun`) reads
        # either. So the subject runs to the verb rather than stopping at
        # "creatures" — a phrase the reader cannot read whole, or cannot test,
        # still refuses the line. The chosen colour is answered against the
        # permanent that prints the sentence (CR 614.1c's record,
        # `subject_matches`' ``source``) and the keyword through layer 6.
        re.compile(
            r"^(?P<attack_you_subject>[a-z' -]*creatures(?: [a-z' -]+?)?) "
            r"can't attack you$"
        ),
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
        # "This creature can't attack or block unless you tap an untapped
        # creature you control not declared as an attacking or blocking
        # creature this combat." (Hollow Warrior.) CR 508.1h / CR 509.1d: a
        # *cost* to attack and a cost to block, paid as the declaration is
        # made — Leviathan's sacrifice and Brainwash's mana with a third
        # currency, a tap. One sentence, two kinds (``also_kinds``), because
        # the two costs are charged at two different steps.
        #
        # The noun phrase is payload — "an untapped Golem you control" would be
        # the same cost over a narrower set — and "you control" is written into
        # the pattern rather than read: the plan draws only on the declaring
        # seat's own board, which is what the words say. "Not declared as an
        # attacking or blocking creature" is not payload either: it is the
        # exclusion every declaration-cost plan in this engine already makes
        # of the creatures being declared, read once there.
        re.compile(
            r"^this creature can't attack or block unless you tap "
            r"(?P<tap_cost>an? .+?) you control not declared as an attacking "
            r"or blocking creature this combat$"
        ),
        ("cant_attack_unless_tap", "cant_block_unless_tap"),
    ),
    (
        # "This creature can't attack or block **if an enchantment is on the
        # battlefield**." (Wirecat.) One sentence, two prohibitions, one
        # subject — ``CombatRestriction.also_kinds`` again, and here on the
        # *self-referential* subject rather than on a plural one, which is why
        # it is a row of its own rather than a reading of the board-wide pair
        # above: those carry a noun phrase the two gates test against every
        # creature, and this one is about the permanent printing it.
        #
        # No payload at all, and the qualifier is what makes the card playable:
        # with an empty board the Cat attacks and blocks freely, and a row that
        # dropped the clause would be a 2/2 for {4} that never fights. Both
        # kinds are in ``CONDITIONAL_RESTRICTION_KINDS``, which is what the
        # attachment is gated on.
        re.compile(r"^this creature can't attack or block$"),
        ("cant_attack", "cant_block"),
    ),
    (
        # "This creature can only attack alone." CR 506.5, as a restriction on
        # the *declaration* rather than on the creature: it may attack only
        # where it is the sole attacker. Printed on a creature here and on an
        # Aura in `engine/aura_restrictions.py`'s restriction table, both read
        # by the same check in the declare-attackers step.
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
        # "Black creatures can't attack or block." (Light of Day; Dread of
        # Night's cycle-mate spelling.) The row above with its third clause
        # unprinted — one sentence, two prohibitions, one subject — so it is
        # the same ``also_kinds`` union over the same payload rather than two
        # rows in two files.
        #
        # **Anchored on the plural head noun**, like `board_attack_subject`'s
        # row below and for its reason: `_printed_noun` answers
        # ``{"type_filter": "creature"}`` for "this creature" and for "enchanted
        # creature" alike, so a `.+` subject here would read a self-reference as
        # a ban on every creature on the board. The `.+` in the Katabatic row
        # above is safe only because the tail it requires is a whole further
        # clause no self-reference prints.
        re.compile(
            r"^(?P<board_attack_subject>(?:[a-z'-]+ )*creatures) "
            r"can't attack or block$"
        ),
        ("creatures_cant_attack", "creatures_cant_block"),
    ),
    (
        # "**Creatures that are enchanted** can't attack or block." (Song of
        # Serenity.) The row above with the narrowing printed as a relative
        # clause *behind* the head noun instead of as adjectives in front of
        # it, so the plural anchor cannot reach it — the same split the
        # "creatures with …" row below makes for exactly this reason.
        #
        # Anchored on "creatures that are" rather than left as a `.+` subject,
        # which is the discipline that row states: `_printed_noun` answers
        # ``{"type_filter": "creature"}`` for "this creature" and for
        # "enchanted creature" alike, so a bare `.+` here would read a
        # self-reference as a ban on every creature in the game. The tail is
        # payload — the noun parser reads it and refuses a key
        # ``subject_matches`` cannot test — so a card printing "creatures that
        # are tapped" would arrive here as the same rule over a different set,
        # or be refused rather than swept wider than it prints.
        re.compile(
            r"^(?P<board_attack_subject>creatures that are .+) "
            r"can't attack or block$"
        ),
        ("creatures_cant_attack", "creatures_cant_block"),
    ),
    (
        # "Creatures without flying can't attack." (Moat.) A restriction over a
        # *described set* of creatures on any battlefield — the subject filter
        # is payload, tested by `subject_matches` at declaration, so a creature
        # that gains flying mid-game escapes it and one that loses flying is
        # caught, with nothing re-derived. The keyword is validated by
        # `combat_restriction_for`: an
        # unimplemented word would make `_has_keyword` answer no for every
        # creature, "without" would then match all of them, and the enchantment
        # would silently forbid every attack — over-restriction, but exactly as
        # silent as the widening this file refuses everywhere else.
        re.compile(r"^creatures without (?P<without_keyword>[a-z]+) can't attack$"),
        "creatures_cant_attack",
    ),
    (
        # "Creatures **with power greater than the number of cards in your
        # hand** can't attack." (Ensnaring Bridge.) The same restriction with
        # the narrowing printed *after* the head noun — the shape the comment
        # on the bare row below says each such tail has to earn its own anchor
        # for, and this is that anchor: the phrase must **open** on "creatures
        # with", which is what a `.+` subject could not require and what keeps
        # the two self-references ("this creature", "enchanted creature") out.
        #
        # `_printed_noun` reads the whole tail and refuses a key
        # `subject_matches` cannot test, so this row buys "creatures with
        # flying", "creatures with power 3 or greater" and every other printed
        # postmodifier at the same time — and refuses, rather than dropping, one
        # the matcher would ignore.
        re.compile(
            r"^(?P<board_attack_subject>creatures with .+) can't attack$"
        ),
        "creatures_cant_attack",
    ),
    (
        # "Creatures can't attack." (Peacekeeper.) The unnarrowed member of the
        # family — Moat's sentence with the exclusion deleted — and the one
        # printing that a bare `creatures_cant_attack` row could not previously
        # produce, so the card reported "text too complex" for a kind the
        # declaration step has enforced since Moat landed.
        #
        # **The subject must end in the plural head noun, and that is the
        # gate rather than a style choice.** `_printed_noun` answers
        # ``{"type_filter": "creature"}`` for "this creature" *and* for
        # "enchanted creature" — the two self-references — so a row capturing
        # any `.+` before "can't attack" would read a restriction printed about
        # one creature as a ban on every creature on the board. Requiring the
        # plural is what tells a board-wide prohibition from a self-reference in
        # the printed words, and it still buys "Red creatures can't attack" and
        # "Nonartifact creatures can't attack" for nothing. A narrowing printed
        # *after* the head noun ("creatures with flying can't attack") ends the
        # phrase somewhere else and keeps refusing — the three rows above are
        # where each such tail has earned its own anchor, and widening this one
        # to reach them is exactly what would re-admit the two self-references.
        #
        # Below the three narrowed rows above, whose subjects end in "control",
        # a keyword or a subtype and so cannot reach this pattern.
        re.compile(r"^(?P<board_attack_subject>(?:[a-z'-]+ )*creatures) can't attack$"),
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
        # one enforcement site reads both. The subtype is validated by
        # `combat_restriction_for`: a
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
    (
        # "This creature can't attack unless you've cast a creature spell this
        # turn." (Mogg Conscripts.) CR 506.1's restriction asked of a *window*
        # rather than of a board — which is what makes it different from the
        # defending-player row above and from the controlled-count one: what it
        # asks about is gone by the time it is asked, since the spell it names
        # has resolved, been countered or is still on the stack, and none of
        # those states is on any battlefield.
        #
        # It needs no record of its own. `PlayerState.spells_cast_this_turn` has
        # held every cast of the turn beside the seat that made it since
        # Stormwing Entity's ordinal, and `turn_management` empties it at the
        # turn boundary — which is the half that matters, because a record that
        # outlived its turn would be a restriction that stopped applying.
        #
        # The noun phrase is payload, like every other noun in this file, and it
        # is read by **`cast_restrictions.cast_spell_filter`** rather than by
        # `combat_restrictions._printed_noun`: what this names is a *spell*,
        # not a permanent (CR 613.1 gives it no computed characteristics), and
        # it is the same phrase Skyshroud Condor's casting gate reads. One
        # reader, so the two tables cannot come to disagree about what "a
        # creature spell" is.
        re.compile(
            r"^this creature can't attack unless you(?:'ve|’ve| have) cast "
            r"(?P<attack_after_cast>.+) this turn$"
        ),
        "cant_attack_unless_you_cast",
    ),
    # "This **token** can't block" (the Pirate Pursued Whale makes). A token is
    # a creature and "this token" is the same self-reference "this creature" is
    # — the word differs only because the card printing it is a token. Both
    # spellings, rather than normalizing one to the other, because the normalizer
    # would have to know which cards are tokens.
    (re.compile(r"^this (?:creature|token) can't block$"), "cant_block"),
    (
        # "Creatures can't block." (Bedlam.) The blocking twin of
        # `creatures_cant_attack`'s unnarrowed row above — Moat's sentence with
        # the exclusion deleted, one step to the right — and its own kind for
        # the reason that pair is always two: the two prohibitions are answered
        # at two different steps, and one kind read at both is a kind one of
        # them forgets. `block_legality._can_block_attacker` has scanned
        # the board for this kind since Katabatic Winds, whose sentence names
        # both halves at once; nothing had ever printed the blocking half on
        # its own, so the row that produces it was missing while the
        # enforcement was not.
        #
        # **The subject must end in the plural head noun**, which is the same
        # gate the attack row states and holds for the same reason:
        # `_printed_noun` answers ``{"type_filter": "creature"}`` for "this
        # creature" *and* for "enchanted creature", so a row capturing any `.+`
        # before "can't block" would read the row directly above this one — a
        # restriction on one permanent — as a ban on every creature on the
        # board. Requiring the plural tells the two apart in the printed words,
        # and it still buys "Red creatures can't block" for nothing.
        #
        # Below the singular row above, which cannot reach this pattern
        # ("creature" is not "creatures"), and below the narrowed blocking rows,
        # whose sentences do not end here.
        re.compile(r"^(?P<board_attack_subject>(?:[a-z'-]+ )*creatures) can't block$"),
        "creatures_cant_block",
    ),
    (re.compile(r"^this creature attacks each combat if able$"), "must_attack_each_combat"),
    # "This creature blocks each combat if able." (Watchdog.) CR 509.1c's
    # requirement, the mirror of the attack one above and a *separate kind*
    # rather than a payload on it: the two are checked at different steps by
    # different predicates, and one kind read at both would have to be told
    # which half it meant at every site.
    #
    # It is the weakest blocking requirement in this file. "Must be blocked"
    # (Canopy Stalker) compels somebody to block *this attacker*; Lure compels
    # everybody able; this compels *this creature* to block **something** — any
    # one attacker it can legally block. Folding it into either of those would
    # take away a legal declaration the card does not touch.
    (
        re.compile(r"^this creature blocks each combat if able$"),
        "must_block_each_combat",
    ),
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
    (
        # "Wall creatures can attack as though they didn't have defender."
        # (Rolling Stones.) CR 609.4's "as though" over a *described set*
        # printed on somebody else's permanent — the board-reaching twin of
        # Animate Wall's Aura permission and Wall of Wonder's one-turn flag,
        # and read at the same one site (`_ignores_defender`) so the three
        # spellings cannot disagree about what the word lifts.
        #
        # The noun phrase is payload for this file's standing reason: a card
        # printing "Creatures you control can attack as though they didn't have
        # defender" is this rule with nothing added. "Defender" is written into
        # the pattern rather than captured, because it is the only keyword that
        # stops an attack by itself — the same refusal
        # ``lowering/combat._lower_attack_as_though`` makes by name, and a
        # captured word would be a clause matched and then acted on by nobody.
        re.compile(
            r"^(?P<board_attack_subject>(?:[a-z'-]+ )*creatures) can attack "
            r"as though they didn't have defender$"
        ),
        "subject_ignores_defender",
    ),
    (
        # "This creature can't be blocked." (Phantom Warrior.) The unnarrowed
        # member of the "can't be blocked" family below: no blocker class, no
        # count and no price, so nothing may block it at all (CR 509.1b).
        #
        # **The kind already had two enforcement sites and no producer.**
        # `phases/block_legality._can_block_attacker` refuses every
        # blocker on it and `legality.is_unblockable` reads it for the UI's
        # fade, both keyed on ``cant_be_blocked``, and nothing in the engine
        # ever emitted one — the grammar's `_lower_cant_be` refuses a
        # restriction with no duration and there was no static table row. So the
        # card that prints the sentence was reported unsupported while the
        # behaviour behind it was complete.
        #
        # Anchored at both ends and **above** the general "can't be blocked by
        # <noun>" row, which the sentence does not reach — it requires " by " —
        # but which is where a widened pattern here would collide.
        re.compile(r"^this creature can't be blocked$"),
        "cant_be_blocked",
    ),
    (
        # "This creature can't be blocked **as long as it's attacking alone**."
        # (Dream Prowler.) The row above under CR 506.5's condition, and a row
        # of its own rather than a qualifier on it: the two qualifiers this
        # file composes (`_AS_LONG_AS`, `_IF_ON_BATTLEFIELD`) both describe a
        # *board*, and this describes the declaration the creature is in —
        # a different question with a different reader, and one no noun phrase
        # parameterizes. Nothing here is payload because nothing here is
        # printed as a parameter: no noun, no count, no colour.
        #
        # ``CONDITIONAL_RESTRICTION_KINDS`` is deliberately not widened for it.
        # That set says which kinds have an enforcement site that *asks about a
        # condition payload*; this kind's condition is inside its own name, so
        # a card printing "…as long as you control an Island" on top of it must
        # keep refusing rather than have the board clause dropped.
        re.compile(
            r"^this creature can't be blocked as long as it's attacking alone$"
        ),
        "cant_be_blocked_while_attacking_alone",
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
        # "Each creature you control can't be blocked by more than one
        # creature." (Familiar Ground.) The row above printed on a *permanent*
        # about somebody else's creatures rather than on the attacker itself, so
        # it is its own kind: that one is read off the attacker's own program
        # and this one has to be found by scanning the board, and a payload flag
        # on one kind would leave whichever enforcement site did not read it
        # applying the ceiling to the wrong creatures.
        #
        # The subject is a printed noun phrase (`_printed_noun`) and the number
        # is payload, for the reasons every other noun and number on this page
        # is: a card printing "Each Wall you control…" or "…more than two
        # creatures" is this restriction and needs nothing here.
        #
        # "Each" is stripped by the pattern rather than read by the noun parser,
        # which refuses the quantified phrase in full — and the singular head
        # noun that follows it is what the parser wants anyway.
        re.compile(
            r"^each (?P<blocked_more_subject>.+) can't be blocked by more than "
            r"(?P<count>\w+) creatures?$"
        ),
        "matching_cant_be_blocked_by_more_than",
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
    (
        # "**If a creature with a magnet counter on it attacks**, all creatures
        # with magnet counters on them attack if able." (Magnetic Web.)
        # Ekundu Cyclops' sentence with both halves widened from "this
        # creature" to a set: CR 508.1d's requirement with a condition about
        # the *declaration being made* rather than about the board, which is
        # why it cannot ride the unconditional row below it — that one is
        # answered by a per-creature predicate with no way to see who else was
        # named.
        #
        # Two noun phrases and two payload keys, because the sentence really
        # does name two sets: who has to be attacking, and who is then
        # compelled. They are the same phrase on this card and there is no
        # reason a card could not print them different.
        #
        # Its own kind rather than `must_attack_if_partner_attacks` with a
        # subject, for `creatures_must_attack`'s reason one row up: that one is
        # read off the attacker's own program and this has to be found on
        # somebody else's permanent, which is a second scan.
        # The article on each half is consumed by the pattern rather than by
        # the noun parser: `_printed_noun` reads a bare noun phrase and refuses
        # a quantifier, so "**all** creatures with magnet counters on them"
        # comes back None and the whole line refuses — the row's own words
        # taking its card away, which is a false negative rather than a silent
        # widening but a refusal all the same.
        re.compile(
            r"^if an? (?P<attack_condition>.+) attacks, "
            r"(?:all |each )?(?P<must_attack_subject>.+) attack if able$"
        ),
        "creatures_must_attack_if_partner_attacks",
    ),
    (
        # "**If this creature attacks**, all creatures you control attack if
        # able." (Viashino Bey.) The row above with its condition naming the
        # permanent itself rather than a set — and its own kind rather than that
        # row's payload with an empty ``condition_subject``, because an empty
        # filter is what ``subject_matches`` answers **True** for: the
        # requirement would fire on every declaration anybody made, compelling a
        # whole board to attack whenever any creature did.
        #
        # The compelled set is payload for this file's standing reason — a card
        # printing "all Lizards you control" is this rule — and "you control"
        # means the Bey's controller (CR 109.5), which the enforcement site
        # supplies as the observer.
        #
        # Its condition really is about identity rather than about a filter:
        # what has to be attacking is *this permanent*, and no noun phrase
        # names it. So the enforcement asks ``is`` over the declaration, which
        # is the only comparison that tells two Beys apart (idiom #11) — and
        # unlike Ekundu Cyclops' "also", nothing here excludes the Bey from its
        # own compelled set: it is already attacking, so the requirement it
        # places on itself is one the declaration has met.
        re.compile(
            r"^if this creature attacks, "
            r"(?:all |each )?(?P<must_attack_subject>.+) attack if able$"
        ),
        "creatures_must_attack_if_source_attacks",
    ),
    (
        # "**Creatures you control** attack each combat if able." (the Pirate
        # token Pursued Whale gives each opponent.) CR 508.1d's requirement
        # printed on one permanent about a *set* of others, so it is enforced
        # by a board scan in `_must_attack_if_able` rather than read off the
        # attacker's own program — the exact arrangement `creatures_cant_attack`
        # beside it already has for the restriction that says the opposite.
        #
        # Its own kind rather than `must_attack_each_combat` with a subject:
        # that one is read off the attacker itself and this one has to be found
        # on somebody else's permanent, which is two different scans, and one
        # kind read at both sites would have to be told which it meant.
        #
        # The plural verb is what keeps the two apart. "This creature
        # **attacks** each combat if able" is the row below; a set **attack**.
        # The noun phrase is payload like every other in this file, so a card
        # printed about Goblins or about creatures with flying needs no row.
        #
        # Until this existed the line compiled to a bare `static_line`: the
        # token reported supported, could not block (its first line *is*
        # enforced), and was under no obligation to attack at all — a granted
        # ability that does nothing, which is the failure only a line-by-line
        # read of a compiled program finds.
        re.compile(
            r"^(?:all |each )?(?P<must_attack_subject>.+) attack each combat if able$"
        ),
        "creatures_must_attack",
    ),
    (
        # "All creatures block each combat if able." (Invasion Plans.) The
        # blocking twin of the row above, in the same relation to
        # ``must_block_each_combat`` that one is in to
        # ``must_attack_each_combat``: printed on one permanent about a *set* of
        # others, so it is enforced by a board scan in the declare-blockers step
        # rather than read off the blocker's own program.
        #
        # The plural verb keeps the two apart, exactly as it does on the attack
        # side. "This creature **blocks** each combat if able" (Watchdog) is the
        # per-creature row; a set **block**.
        #
        # And it is the *weak* requirement, not Lure's: it compels each creature
        # the phrase names to block **something**, where "all creatures able to
        # block this creature do so" compels a particular attacker to be
        # blocked. Reading either as the other changes which declarations are
        # legal.
        re.compile(
            r"^(?:all |each )?(?P<must_block_subject>.+) block each combat if able$"
        ),
        "creatures_must_block",
    ),
    (
        # "The attacking player chooses how each creature blocks each combat."
        # (Invasion Plans.) CR 509.1a's chooser substituted by a *static*
        # ability, where Melee substitutes it with a one-shot — so the seat is
        # not stored on the game, it is derived at the declaration from whoever
        # is attacking. ``Game.block_chooser_index`` is the one reader, which is
        # what keeps the engine, the AI stepper and the web layer from each
        # answering "who is asked?" for themselves.
        #
        # Nothing is payload because nothing is printed as a parameter: the
        # sentence names no noun phrase, no count and no seat but the one the
        # turn already names.
        re.compile(
            r"^the attacking player chooses how each creature blocks each combat$"
        ),
        "attacker_chooses_blocks",
    ),
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
        # "This creature can't block **or be blocked by** creatures with power 2
        # or greater." (Sneaky Homunculus.) Two prohibitions over one printed
        # noun phrase, and they are the two rows on either side of this one read
        # at once: what this creature may not block (``cant_block_subject``,
        # Ironclaw Orcs) and what may not block it (``cant_be_blocked_by``,
        # Juggernaut). ``CombatRestriction.also_kinds`` is exactly that shape —
        # one sentence, one subject read once — and the phrase is parsed once
        # by `_blocker_union` and handed to **both** payload keys, so the two
        # enforcement sites cannot come to disagree about which creatures it
        # names.
        #
        # Above the ``cant_block_subject`` row, whose `.+` would otherwise take
        # "or be blocked by …" as its noun phrase — which `_blocker_union`
        # refuses, the safe direction but not the reading.
        re.compile(r"^this creature can't block or be blocked by (?P<block_either>.+)$"),
        ("cant_block_subject", "cant_be_blocked_by"),
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
        # "This creature can block creatures with shadow as though it had
        # shadow." (Heartwood Dryad, Wall of Diffusion.) The **permission**
        # mirror of the two rows above: those narrow what this creature may
        # block, this widens it — CR 609.4's "as though", which applies only to
        # the stated effect. The Dryad does not gain shadow: it still blocks the
        # ground creatures it is printed to stop, and CR 702.28b's *other*
        # prohibition ("a creature with shadow can't be blocked by creatures
        # without shadow") is the only one lifted.
        #
        # The keyword is captured twice and both halves must name the same one
        # (checked in `combat_restriction_for`), exactly as
        # `evasion_negation._TEMPLATE` requires: a line reading "…with shadow as
        # though it had flying" is not a card this table has ever seen, and
        # matching it on the first half alone would lift the wrong restriction.
        re.compile(
            r"^this creature can block creatures with "
            r"(?P<as_though_keyword>[a-z]+) as though it had "
            r"(?P<as_though_repeat>[a-z]+)$"
        ),
        "can_block_as_though_it_had",
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
