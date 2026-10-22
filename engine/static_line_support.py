"""May a creature (or a land) carry this static line?

A creature is refused for any line nothing reads, so its static lines are
admitted one table at a time by :func:`_is_supported_static_creature_line`.
Each arm asks the table the consumer *dispatches* on — combat restrictions,
static bonuses, lord buffs, the entry-state table, the replacement and
prevention registries, the cast and activation bans, and the rest — so the
gate and the dispatch read one table, and a rider the table cannot read is
refused rather than admitted and dropped. A static the grammar lowers is
admitted through a short whitelist of kinds
(:data:`_GRAMMAR_STATIC_CREATURE_KINDS`). The guard is
``tests/engine/test_static_line_support.py``.

The noncreature side of the same gate is ``engine/derived_static_claims.py``,
and the comments below keep finding the partial-list shape between them: a
sentence the noncreature side claimed whose creature printing was "text too
complex".

Split out of ``engine/oracle.py`` at the 2,000-line cap.
"""

from __future__ import annotations

import re

from .oracle_types import OracleInstruction
from .characteristic_defining import dynamic_pt_for
from .combat_restrictions import combat_restriction_for
from .target_immunity import immunity_claims_line
from .lord_buffs import lord_buff_for
from .zone_copies import ZONE_TOP_COPY_KIND
from .static_bonuses import static_bonus_for
from .grammar import compile_line as compile_grammar_line
from .line_normalization import _PARENTHETICAL_RE, normalize_creature_line
from .self_reference import _restriction_line
from .keyword_lines import _protection_clause_modelled


# "This creature doesn't untap during your untap step." — the behavior is
# already enforced directly in phases/untap_step.py's text scan; this only
# needs to be recognized as a supported static line so the whole creature
# doesn't classify as unsupported.
_DOESNT_UNTAP_LINE = "this creature doesn't untap during your untap step"


#: The static instruction kinds a *creature's* own line may lower to through the
#: grammar. Deliberately a short list rather than "anything the grammar reads":
#: a creature's static lines have been gated by the whitelist below since the
#: compiler was written, and opening that gate to every production at once is a
#: change with its own blast radius. What is here is what the CR 613 refresh in
#: engine/mixins/permanent_state.py dispatches on.
#:
#: ``lord_buff`` joined for the anthem shapes only the grammar can read — a
#: "named <card name>" restriction (Rohgahh of Kher Keep) and an "as long as"
#: condition lowered to a payload (Ivory Guardians); the text-side derivation
#: table still reads every line the grammar refuses (Jihad's stored-choice
#: condition). Both producers emit through ``lord_buff_payload``, and the
#: pool-wide differential run when the gate widened found zero payload drift.
_GRAMMAR_STATIC_CREATURE_KINDS = frozenset(
    {
        "dynamic_pt_bonus", "lord_buff", "conditional_static",
        # "This creature can't attack unless you sacrifice two Islands."
        # (Leviathan.) A CR 508.1h attack cost, which is a *static* property of
        # the creature — `declare_attackers_step` reads the compiled
        # instruction off the card at declaration, exactly as it reads the
        # text-keyed restrictions beside it. The grammar produces it rather
        # than `combat_restrictions.py` because the noun phrase behind the cost
        # is a parsed one; without this row the whole card came back "text too
        # complex" with every one of its lines grammar-clean.
        "cant_attack_unless_sacrifice",
        # "This creature can't attack **if** defending player controls an
        # untapped creature with power 3 or greater." (Goblin Mutant.) The same
        # static property one polarity over from the clause
        # `combat_restrictions.py` derives, and here for the reason the cost
        # above is: the noun phrase behind it is a parsed one, so no regex table
        # can hold it and without this row the whole card came back "text too
        # complex" with its only unread line grammar-clean.
        "cant_attack_unless_defender_controls",
        # "…unless at least two other creatures attack/block." (Orcish
        # Conscripts.) A static property of the creature that is checked
        # against the *declaration* (CR 508.1c, CR 509.1b) — the printed
        # count is a parsed number, so the grammar reads it here.
        "cant_attack_unless_others_attack",
        "cant_block_unless_others_block",
        # "…unless a creature with greater power also attacks/blocks." (Okk.)
        # The same static property under a comparison rather than a count, and
        # here for the same reason: the declaration reads the compiled
        # instruction off the card, and without the row Okk came back "text too
        # complex" with both of its lines grammar-clean.
        "cant_attack_unless_greater_power_attacks",
        "cant_block_unless_greater_power_blocks",
        # "…unless a black or green creature also attacks." (Scarred Puma.)
        # Okk's row with a noun phrase for the companion; the declaration reads
        # the compiled instruction off the card exactly as it reads that one.
        "cant_attack_unless_subject_attacks",
        # "You may have this creature assign its combat damage as though it
        # weren't blocked." (Lone Wolf.) A static property of the creature read
        # by the combat damage step at CR 510.1's turn-based action, so — like
        # every kind above — the instruction is the *record* the consumer reads
        # rather than something a handler executes. It reaches here through the
        # grammar because the offer's subject and its absent window are what
        # say it is a static rather than the one-turn mark Outmaneuver's
        # identical verb writes, and neither is a thing a text table can see.
        "may_assign_as_unblocked",
        # "As long as the top card of your graveyard is a creature card, this
        # creature has the full text of that card…" (Volrath's Shapeshifter.)
        # A CR 613 layer 1a contribution, derived from the zone on every read
        # by `engine/copies.py` rather than dispatched — so, like every kind
        # above, the instruction is the *record* the consumer reads and not
        # something a handler executes. It reaches the grammar through
        # `engine/grammar/derived.py`, which hands over
        # `engine/zone_copies.py`'s own payload, so the gate and the dispatch
        # are the same table by construction.
        ZONE_TOP_COPY_KIND,
        # "This creature can attack as though it didn't have defender." with no
        # duration -- the ability a kicked Prison Barricade is granted in
        # quotes. A CR 609.4 permission that is a static property of the
        # creature, read off the compiled program by
        # `declare_attackers_step._ignores_defender`; like every kind above,
        # the instruction is the record the consumer reads.
        "attacks_as_though_no_defender",
    }
)


def _grammar_static_creature_instructions(
    line: str, card_name: str | None = None
) -> tuple[OracleInstruction, ...]:
    """The static contributions the grammar reads out of a creature's line.

    Carrion Grub's "gets +X/+0, where X is the greatest power among creature
    cards in your graveyard" is a layer-7c contribution whose *size* is
    computed, which no text-keyed table can express — the size is the whole
    variable part.

    **Several, not one.** The gate is a whitelist of *kinds*, and the arity was
    incidental to it: one printed sentence may carry several prohibitions over
    one subject, which is the shape ``CombatRestriction.also_kinds`` has named
    on the text-table side since Katabatic Winds. Mogg Flunkies' "can't attack
    or block alone" is the grammar's first, and with the arity check in place
    the whole card came back "text too complex" for a line both halves of which
    the engine enforces. Every instruction still has to name a whitelisted
    kind — a line that lowered to one of these *and* something else is not a
    static contribution and keeps its refusal.
    """
    # A line carrying a **quoted ability** goes to the grammar as printed:
    # 'As long as …, this creature has "{T}: Destroy target black creature."'
    # (Repentant Vampire) hands the quote over as text the compiler reads
    # again and the table shows a player, and the normalised spelling would
    # make that "{t}: destroy target black creature". The grammar strips the
    # ability word and the reminder text itself; nothing else here printed a
    # quote the grammar could read, so no other line changes spelling.
    compiled = compile_grammar_line(
        line if '"' in line else normalize_creature_line(line),
        card_name=card_name,
    )
    if not compiled.usable or not compiled.instructions:
        return ()
    if any(
        instruction.kind not in _GRAMMAR_STATIC_CREATURE_KINDS
        for instruction in compiled.instructions
    ):
        return ()
    return tuple(compiled.instructions)


#: A printed line's sentence count, ignoring the full stops inside a quoted
#: granted ability ('Enchanted creature has "{T}: Add {G}."').
_QUOTED_SPAN = re.compile(r"[\"“‘'][^\"”’']*[\"”’']")


def _one_sentence(line: str) -> bool:
    """Whether *line* is a single printed sentence.

    Asked before a table that speaks for **one** sentence is allowed to claim a
    whole line. `auras.aura_continuous_claim` is such a table — its readers
    search rather than anchor, so it answers "there is a restriction in here"
    and not "this is all restriction" — and a line with a second sentence
    behind the one it recognized would be claimed whole, with the rest silently
    unread. That is Mirage's single-whitelist-word failure exactly, and
    Volrath's Curse is the card in this pool that shows it: its restriction
    sentence is implemented and the CR 116.2d offer printed behind it is not.

    **Reminder text is not a sentence** (CR 207.2). It is parenthetical, it
    states no rule, and every reader downstream has already dropped it —
    `normalize_creature_line` strips it before the derivation tables see the
    line, so counting its full stop here asked the question of a different
    string than the one being claimed. Corrupting Licid is the card that shows
    it: "Enchanted creature has fear. (It can't be blocked except by artifact
    creatures and/or black creatures.)" is one printed sentence with a
    parenthesis behind it, `auras.aura_continuous_claim` implements it end to
    end, and the card compiled unsupported on the period inside the brackets.
    """
    outside = _PARENTHETICAL_RE.sub("", _QUOTED_SPAN.sub("", line or ""))
    return outside.strip().rstrip(".").count(".") == 0


def _is_supported_static_creature_line(line: str, card_name: str | None = None) -> bool:
    if _grammar_static_creature_instructions(line, card_name):
        return True
    normalized = normalize_creature_line(line)
    # "Protection from black" printed as a line of its own (Mountain Yeti's
    # second line, Yavimaya Scion's only one). **Every named quality has to be
    # one the shield models**, which is the same claim `_is_supported_keyword_line`
    # makes about the comma-joined spelling — this was a bare `startswith`, and
    # the gap between the two readers is a card whose printed shield does not
    # exist. Yavimaya Scion is that card: "Protection from artifacts" was
    # admitted here, compiled to a bare `static_line`, and
    # `_protection_qualities` — which asks `keywords.protection_quality` — found
    # nothing in it, so the creature blocked artifact creatures, took their
    # combat damage and could be equipped. Angelic Curator prints the identical
    # quality on a keyword line and was refused, loudly, by the reader that does
    # ask. One reader now, and the refusal is the honest half of the pair.
    if normalized.startswith("protection from "):
        return _protection_clause_modelled(normalized[len("protection from "):])
    # Through the same name-substituting reader the combat restrictions use:
    # a card that says "**Radha** has first strike" is saying "this creature",
    # and the table below is written against the self-reference. Without it a
    # legendary's own static reads as a sentence about some other permanent.
    if static_bonus_for(_restriction_line(line, card_name)) is not None:
        return True
    if normalized == _DOESNT_UNTAP_LINE:
        return True
    if dynamic_pt_for(normalized) is not None:
        return True
    # The gate and the dispatch must read the SAME table. The literals below are
    # matched by `startswith`, while `combat_restriction_for`'s patterns are
    # anchored — so a line like "this creature can't block creatures with
    # flying" was gated in by the prefix "this creature can't block", then
    # matched no anchored pattern and fell through to a bare `static_line`:
    # supported, with the restriction silently absent. Deriving the gate from
    # the dispatch table means an unrecognized rider is now reported unsupported
    # (loud) instead.
    if combat_restriction_for(_restriction_line(line, card_name), card_name) is not None:
        return True
    # "Cast this spell only if you've cast another spell this turn."
    # (Skyshroud Condor.) CR 601.3, gated by `check_cast_timing` from the cast
    # path — so, like every table above, it needs no instruction to work. What
    # it needed was this line: Skyshroud Condor is the first *creature* in the
    # pool to print one of these clauses, and a creature is refused for any
    # line nothing reads, so a card the table gates perfectly reported "text
    # too complex". Asked of the table's own reader, so a clause it cannot read
    # still refuses the card rather than admitting it with the restriction
    # unenforced.
    from .cast_restrictions import cast_timing_claims_line

    if cast_timing_claims_line(normalized):
        return True
    # "This spell can't be countered." (Scragnoth.) CR 113.6g: a static ability
    # of the object *on the stack*, so it produces no instruction for a
    # permanent — the counter path reads it off the card at CR 608.2. Asked of
    # that reader, so a card admitted here is one the counter path really
    # honours; a parsed-and-dropped "can't be countered" is worse than none,
    # because it looks like protection nobody has.
    from .counter_conditions import uncounterable_class_line, uncounterable_line

    if uncounterable_line(normalized):
        return True
    # "Creature spells can't be countered." (Gaea's Herald.) The board half of
    # the same immunity — a static of the permanent about every spell of a
    # type, read off the battlefield by the same counter path — and admitted
    # for the same reason, through the reader that path enforces it with.
    if uncounterable_class_line(normalized) is not None:
        return True
    # "<this creature> can't be the target of Aura spells" (Bartel Runeaxe,
    # Tetsuo Umezawa). Asked of the same reader `_can_be_targeted` consults, so
    # a wording the table cannot read is reported unsupported rather than
    # admitted with the protection absent — the direction every gate in this
    # function exists to prevent.
    if immunity_claims_line(_restriction_line(line, card_name)):
        return True
    # A lord's continuous buff to other creatures. The gate used to admit the
    # bare prefix "other ", which is a template in disguise: "Other Goblins
    # glimmer uncontrollably." compiled as supported and did nothing. It asks
    # the derivation table the consumer dispatches on, so an unimplemented
    # keyword, an unrecognized granted ability or an unmodelled condition is now
    # reported unsupported rather than admitted and dropped.
    if lord_buff_for(normalized) is not None:
        return True
    # "Other Bird creatures get +1/+1 for each feather counter on **Kangee**."
    # (Kangee, Aerie Keeper.) The table's counter tail is anchored on "this
    # <noun>", and a legendary card writes the same reference as its own name;
    # collapsed through the reader every other table in this function is asked
    # through, and only where the uncollapsed line found nothing, so no
    # sentence the table read before is read differently now.
    if lord_buff_for(_restriction_line(line, card_name)) is not None:
        return True
    # "Creatures with islandwalk can be blocked as though they didn't have
    # islandwalk." (Gosta Dirk, Lord Magnus, Ur-Drago print it on a creature;
    # five Legends enchantments print the same sentence.) Asked of the reader
    # the blockers step enforces with, so the claim and the enforcement are one
    # function rather than two tables held equal by hand.
    from .evasion_negation import evasion_negation_for

    if evasion_negation_for(normalized) is not None:
        return True
    # "Black and/or red permanents and spells are colorless sources of damage."
    # (Ghostly Flame.) Asked of the reader every damage-colour question goes
    # through, so a wording the table cannot read is a card reported unsupported
    # rather than one admitted with the rewrite absent — which for an
    # enchantment whose whole text is this sentence is a permanent that enters
    # play and does nothing.
    from .damage_source_colors import colorless_source_line

    if colorless_source_line(normalized) is not None:
        return True
    # "This creature can't be destroyed by lethal damage unless lethal damage
    # dealt by a single source is marked on it." (Ogre Enforcer.) CR 704.5g
    # narrowed by the creature's own text, asked of the reader the state-based
    # sweep enforces with — so the claim and the exception are one function
    # rather than two tables held equal by hand.
    from .lethal_damage import single_source_lethal_line

    if single_source_lethal_line(normalized):
        return True
    # "This token can't be enchanted." (Tetravus's Tetravites.) Asked of the
    # reader both attachment predicates use, so the claim and the enforcement
    # are one rule.
    from .auras import self_cant_be_enchanted_line

    if self_cant_be_enchanted_line(normalized):
        return True
    # "The chosen player's maximum hand size is four." (Cursed Rack.) Asked of
    # the reader the cleanup step enforces with, so what is claimed and what is
    # carried out are one table.
    from .hand_size import hand_size_line

    if hand_size_line(normalized):
        return True
    # "Reveal the first card you draw each turn." (Rowen.) Asked of the reader
    # the draw seam carries it out with, so what is claimed and what is done are
    # one table.
    from .draw_reveals import reveals_every_draw_line, reveals_first_draw_line

    if reveals_first_draw_line(normalized):
        return True
    # "The chosen player reveals each card they draw." (Booby Trap.) The
    # sentence beside it, asked of the same seam's other reader and claimed for
    # the same reason.
    if reveals_every_draw_line(normalized):
        return True
    # "Remove this card from your deck before playing if you're not playing for
    # ante." (Tempest Efreet.) Not an ability at all — CR 113.6a, an instruction
    # that functions outside the game — and its enforcement site is deck
    # construction, which `engine/ante.py` and `web/deck_legality.py` already
    # implement in full. `SUPPORTED_SPELL_PATTERNS` has claimed it for the spell
    # path all along; a creature printing the same line was reported "text too
    # complex" for the one line on it the engine handles completely, which hid
    # the card's real blocker behind a solved one. Asked of the reader that bars
    # the card from a deck, so the claim and the enforcement are one constant.
    from .ante import is_ante_deck_line

    if is_ante_deck_line(normalized):
        return True
    # "You may play two additional lands on each of your turns." (Azusa, Lost
    # but Seeking.) The land-drop path derives the allowance from every
    # controlled permanent's own text (engine/land_play_allowance.py), creatures
    # included — the noncreature classifier has asked this table since it was
    # written, and a creature printing the same template was enforced correctly
    # while reported unsupported. Only the permission clause claims: Fastbond's
    # damage rider is a trigger that table does not own, so a rider line on a
    # creature still refuses rather than compiling with the damage absent.
    from .land_play_allowance import land_play_line

    if land_play_line(normalized) in ("allowance", "prohibition"):
        return True
    # "As this creature enters, it becomes your choice of <body>, …"
    # (Primal Clay). Carried out by _initialize_permanent_state, which reads the
    # bodies from this same parser — so what is claimed here and what is applied
    # cannot describe different cards.
    from .enter_effects import choosable_bodies, enter_effect_line

    if choosable_bodies(normalized):
        return True
    # Every *other* entry-state phrase `_initialize_permanent_state` carries
    # out, asked as the whole table rather than one of its entries.
    #
    # This is the partial-list mistake again, and it had been paid for: the
    # "enters with seven +1/+0 counters" sentence was admitted by a literal
    # elsewhere while "…three +1/+1 counters" — the same rule with a different
    # number — was refused, so Clockwork Beast worked and Triskelion did not,
    # for no reason anyone had decided. Asking the table means a card printing
    # any phrase the entry state implements is admitted, and one printing a
    # phrase it does not is still refused by name.
    if enter_effect_line(normalized, card_name) is not None:
        return True
    # "Rasputin can't have more than seven dream counters on it." A maximum on
    # a CR 122.1 counter store, enforced at the single write in
    # engine/named_counters.py — so like every table above it needs no
    # instruction, and like every table above the gate asks the implementer
    # rather than keeping its own copy of the sentence.
    from .named_counters import counter_cap_line

    if counter_cap_line(normalized, card_name) is not None:
        return True
    # "If this creature would be destroyed, regenerate it." (Clergy of the Holy
    # Nimbus.) CR 701.19b: a *static* regeneration, which the two destruction
    # paths derive from the permanent's own text through
    # `engine/regeneration.py` — so there is no instruction, and like every
    # table above the gate asks the code that performs it rather than keeping a
    # literal. Anchored there, so a conditional variant keeps refusing instead
    # of being admitted and then regenerating unconditionally.
    from .regeneration import denies_regeneration_line, self_regeneration_line

    if self_regeneration_line(normalized):
        return True
    # "Creatures dealt damage by this creature this turn can't be regenerated
    # this turn." (Bone Shaman grants it to itself.) CR 701.19c from the
    # damager's end — a standing property of the creature rather than a rider
    # stamped on one event, so `damage_events._apply_dealer_riders` derives it
    # from the permanent's effective text at the one seam every damage event
    # passes through, and there is nothing here to lower.
    if denies_regeneration_line(normalized):
        return True
    # "For each basic land type among lands you control, this creature has
    # landwalk of that type." (Magnigoth Treefolk.) A static ability whose
    # granted words are named by the board, so it produces no instruction: the
    # layer-6 pass re-derives the walks from the permanent's own text on every
    # recompute through `engine/landwalk.py`. Asked of the reader that pass
    # grants through, so a set it cannot count (another player's lands) or a
    # characteristic no landwalk is built from keeps refusing instead of being
    # admitted as a creature with no evasion at all.
    from .landwalk import landwalk_per_type_spec

    if landwalk_per_type_spec(normalized) is not None:
        return True
    # "While an opponent is choosing targets as part of casting a spell they
    # control or activating an ability they control, that player must choose at
    # least one Flagbearer on the battlefield if able." (Standard Bearer,
    # Coalition Honor Guard.) A requirement on somebody else's announcement
    # (CR 601.2c), enforced off the board at the cast and activation paths —
    # no instruction, and a creature is refused for any line nothing reads.
    # Asked of the reader those paths enforce through, so a noun it cannot test
    # stays a refused card rather than a requirement that demands nothing.
    from .target_requirements import must_choose_claims_line

    if must_choose_claims_line(normalized):
        return True
    # "If this card is in a graveyard, effects from spells named Flame Burst
    # count it as a card named Flame Burst." (Pardic Firecat, Diligent
    # Farmhand.) A static that functions in the graveyard (CR 113.6b) and
    # widens what one spell's name count sees — read off the card's own text by
    # the count's name test (engine/counted_names.py), so there is no
    # instruction. Asked of the reader that test asks.
    from .counted_names import counts_as_claims_line

    if counts_as_claims_line(normalized):
        return True
    # "You can't cast creature spells." (Steel Golem.) CR 601.3a scoped to the
    # permanent's own controller, enforced off the board at every cast — so
    # like every table above it produces no instruction, and a creature whose
    # whole static half is this sentence reported "text too complex" for the one
    # line the engine could enforce end to end. Asked of the reader that
    # enforces it, so the claim cannot outlive the ban.
    from .cast_restrictions import chosen_name_ban_line, own_cast_ban_line

    if own_cast_ban_line(normalized) is not None:
        return True
    # "Spells with the chosen name can't be cast." (Meddling Mage.) The same
    # CR 601.3 prohibition keyed on a name the permanent recorded as it entered,
    # enforced off the board at every cast — no instruction, and a *creature*
    # is refused for any line nothing reads, so the first creature to print it
    # has to be admitted here by the reader that enforces it.
    if chosen_name_ban_line(normalized):
        return True
    # A CR 601.2f cost change the casting path derives from every permanent's
    # own text — "Noncreature spells cost {1} more to cast" (Vryn Wingmare),
    # "Creature spells with flying you cast cost {1} less" (Watcher of the
    # Spheres). The noncreature classifier has asked this table since it was
    # written, and Gloom is an enchantment, so a *creature* printing the same
    # template was taxed correctly while reported unsupported — the same shape
    # Azusa had against the land-play table above.
    from .cost_modifiers import cost_modifier_claims_line

    if cost_modifier_claims_line(normalized):
        return True
    # **Every** CR 614 replacement carried out by engine/replacements.py from
    # the permanent's own text, not one of them.
    #
    # This asked for Conclave Mentor's constant alone, which is the partial-list
    # mistake this file keeps finding one table at a time: the *noncreature*
    # classifier has asked `replacement_claims_line` — the whole registry —
    # since that function was written, so a creature whose static line is any
    # other implemented replacement reported unsupported however well the
    # interceptor ran. Containment Priest is the card that made it visible,
    # because its whole text is one.
    #
    # Asked as the registry rather than spelled out: an interceptor self-selects
    # on its own exact string, so a literal copied here could claim a line
    # nothing implements.
    from .prevention import prevention_claims_line
    from .replacements import replacement_claims_line

    if replacement_claims_line(normalized):
        return True
    # CR 615's shields, asked the same way and for the same reason: a creature
    # printing a static prevention line works through the interceptor and would
    # otherwise report unsupported.
    if prevention_claims_line(normalized, card_name):
        return True
    # A board-wide static contributed through the layer bridge (Titania's Song,
    # and the Pirate's "Creatures you control attack each combat if able"). The
    # *noncreature* classifier has asked this table since it was written; a
    # creature — or a token — printing the same line reported unsupported while
    # the effect worked perfectly. The same partial-list shape round 113 found
    # against the replacement registry, one table over.
    from .global_statics import global_static_for

    if global_static_for(normalized) is not None:
        return True
    # "Play with the top card of your library revealed." / "…you may cast Goblin
    # spells from the top of your library." (Conspicuous Snoop, Radha.) Static
    # permissions read off the permanent's own text while it is in play
    # (CR 113.6's default for a permanent, not one of its exceptions), so like
    # every table above they need no instruction.
    from .library_top import library_top_line

    if library_top_line(normalized):
        return True
    # "Players play with their hands revealed." (Wandering Eye.) The hand-zone
    # twin of the line above, and the same partial-list shape: the noncreature
    # classifier has claimed it through `_derived_static_claims` since Revelation,
    # and `engine/revealed_hands.py` scans every permanent's effective text
    # whatever its card type — so a *creature* printing the sentence revealed
    # every hand perfectly while reporting "text too complex". Asked of the
    # module that performs it, so the claim cannot outlive the reveal.
    from .revealed_hands import revealed_hands_line

    if revealed_hands_line(normalized):
        return True
    # "You may cast Aura spells with enchant creature as though they had flash."
    # (Rootwater Shaman.) A CR 611.1 static permission over CR 702.8a's timing,
    # derived from every permanent's own text at the two timing gates
    # (`cast_timing.board_flash_timing`) — so like every table above it produces
    # no instruction, and a creature whose whole text is this sentence reported
    # "text too complex" for a line the engine enforces end to end. Asked of the
    # table that performs it, so a class it cannot narrow still refuses the card
    # rather than admitting it with the narrowing dropped.
    from .cast_timing import static_flash_permission

    if static_flash_permission(normalized) is not None:
        return True
    # "Enchanted creature has haste." (Enraging Licid; four of the five print
    # one of these.) CR 303.4m: an ability that refers to the "enchanted
    # [object]" refers to whatever that permanent is attached to, **even if the
    # permanent with the ability isn't an Aura** — which is exactly a Licid,
    # printed as a creature and attached only once its own ability has run.
    #
    # The same partial-list shape this function keeps finding one table at a
    # time: `auras.aura_continuous_claim` has been asked for a card whose
    # printed type line says Aura since it was written, and a *creature*
    # printing the identical sentence reported "text too complex" while the
    # layer bridge derived the grant perfectly — it reads the attachment record,
    # never the attacher's type line. Asked of that table, so a grant it cannot
    # derive still refuses the card rather than admitting it with the line
    # dropped.
    from .auras import aura_continuous_claim

    if _one_sentence(line) and aura_continuous_claim(normalized) is not None:
        return True
    # "This creature can block an additional creature each combat."
    # (Two-Headed Giant of Foriys) / "…can block any number of creatures."
    # (Wall of Glare.) CR 509.1a's one-attacker default lifted by a printed
    # static, derived by the table ``_max_blocks_for`` raises the ceiling from —
    # so what is claimed and what is enforced are one reading. The first of the
    # two was a prefix row in the tuple below until Wall of Glare arrived and
    # showed what a second spelling of the same sentence costs: a scan for
    # "additional" answers zero for "any number", and the card would have been
    # admitted blocking exactly one attacker.
    from .combat_permissions import block_permission_claims_line

    if block_permission_claims_line(normalized):
        return True
    static_patterns = (
        "this creature enters with seven +1/+0 counters on it",
        "this creature enters with x +1/+1 counters on it",
        "this creature enters tapped",
        "at end of combat, if this creature attacked or blocked this combat, remove a +1/+0 counter from it",
        "for each 1 damage that would be dealt to this creature, if it has a +1/+1 counter on it, remove a +1/+1 counter from it and prevent that 1 damage",
        # "can't attack", "can't block", "can't attack unless defending player
        # controls a <type>", "attacks each combat if able" and "can't be
        # blocked by walls" are gated above by combat_restriction_for, whose
        # patterns are anchored. Listing them here too would restore the prefix
        # hole those anchors close.
        # "other " is deliberately NOT here. It was the whole support test for a
        # lord line — a prefix admitting any sentence that began with the word —
        # and it is now `lord_buff_for` above, which claims the sentence end to
        # end or not at all.
        "as long as this creature is untapped, all damage that would be dealt to you by unblocked creatures is dealt to this creature instead",
        "remove a corpse counter from this creature: regenerate this creature",
        "you may have this creature enter as a copy of any creature on the battlefield",
        # Desert Nomads / Camel: static shield against Desert lands' damage
        # ability. Handled by a replacement-effect interceptor (checked
        # against oracle text directly) rather than a compiled instruction —
        # see engine/replacements.py:_prevent_desert_damage, which also
        # covers Camel's clause extending the shield to creatures banded
        # with it.
        "prevent all damage that would be dealt to this creature by deserts",
        "as long as this creature is attacking, prevent all damage deserts would deal to this creature",
        # Ali from Cairo: a life-total-floor replacement effect (CR 614),
        # handled by engine/replacements.py:_floor_life_at_one against oracle
        # text directly rather than a compiled instruction.
        "damage that would reduce your life total to less than 1 reduces it to 1 instead",
        # Guardian Beast: static artifact protection (can't-be-enchanted,
        # indestructible, can't-gain-control) while untapped. Checked by
        # mixins/effects.py:_untapped_artifact_protector_active at each
        # relevant site rather than a compiled instruction.
        "as long as this creature is untapped, noncreature artifacts you control can't be enchanted, "
        "they have indestructible, and other players can't gain control of them",
    )
    if any(normalized.startswith(pattern) for pattern in static_patterns):
        return True
    # "This <noun> doesn't untap during your untap step." / "You may choose not
    # to untap this <noun> during your untap step." (Old Man of the Sea, and
    # Antiquities' three tapped-duration artifacts.) A literal for the *creature*
    # spelling used to sit in the list above — a second copy of a sentence
    # `engine/untap_restrictions.py` already reads, and one that named a single
    # noun, so the artifact printings were admitted by an unrelated route.
    from .untap_restrictions import self_untap_line, untap_restriction_for

    if self_untap_line(normalized, card_name) is not None:
        return True
    # "Creatures with power 3 or greater don't untap during their controllers'
    # untap steps." (Marble Titan.) The *board-wide* half of the same file, and
    # the partial-list shape this function keeps finding one table at a time —
    # Azusa against `land_play_allowance`, Gloom against `cost_modifiers`,
    # Containment Priest against the replacement registry. The line above claims
    # only what a permanent says about **itself**; `_derived_static_claims` has
    # asked the board-wide table since it was written, so Meekstone (an
    # artifact) worked and Marble Titan (a creature printing the same sentence
    # with a different number) was "text too complex" — with the untap step
    # already honouring it, because that step walks `all_permanents()` and never
    # cared which card type imposed the restriction.
    #
    # Asked of the table that performs it, so a wording it cannot read still
    # refuses the card rather than admitting it with the restriction absent.
    return untap_restriction_for(normalized) is not None
