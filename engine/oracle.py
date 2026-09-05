"""Oracle-text compiler.

Turns a card's oracle text into an OracleProgram: a set of instructions,
activated abilities, triggered abilities, and static lines the game engine
can execute. This module owns tokenizing, line classification (keyword /
triggered / activated / static), and the per-card compile cache.

Reading an effect clause is delegated, and `_line_instruction` is where the
two front ends meet, most general first:

1. ``engine/grammar/`` — a real parser over Magic's templating. Whatever it
   claims, it claims for every card printed the same way.
2. ``engine/card_hooks.py``'s ``CARD_LINE_INSTRUCTIONS`` — one printed line of
   one card, for sentences no second card could share. A production for those
   would be a whole-card substring match wearing a grammar hat.

Precedence follows from that ordering: a line the grammar learns to read stops
reaching its card hook, which is what makes a superseded hook dead rather than
wrong.

There is no third. ``engine/parsing/``'s ``@parse_rule`` registry — a flat table
of substring predicates, hand-ordered against one another, which claimed a
clause on a prefix and dropped whatever followed — is deleted. A line no front
end reads now produces no instruction, which is the loud failure the invariant
asks for: the card is reported unsupported and names the clause.
"""

from __future__ import annotations

import re
from functools import lru_cache

from .models import CardDefinition
from .oracle_types import (
    ActivatedAbilityCost,
    ModalOption,
    OracleInstruction,
    OracleProgram,
    OracleToken,
    ParsedActivatedAbility,
    ParsedTriggeredAbility,
    TriggerCondition,
    _COLOR_WORD_TO_SYMBOL,
    _MANA_TOKEN_RE,
    _NUMBER_WORDS,
    compilation_cache,
    strip_ability_word,
)
from .characteristic_defining import dynamic_pt_for
from .auras import aura_claim, unclaimed_aura_lines
from .equipment import expand_equip_lines, has_equip_ability, is_equip_line
from .alternative_costs import alternative_cost_claims_line
from .cast_costs import cast_cost_claims_line
from .combat_restrictions import combat_restriction_for
from .enter_effects import enter_effect_line
from .target_immunity import immunity_claims_line
from .effect_labels import activated_label, triggered_label
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .modal_triggers import (MODAL_INSTRUCTION_KIND,
                             modal_trigger_mode_is_derivable,
                             modal_trigger_targeting_refusal)
from .cumulative_upkeep import cumulative_upkeep_triggers
from .flanking import flanking_triggers
from .rampage import rampage_amount, rampage_triggers
from .static_bonuses import static_bonus_for
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .grammar.lowering._events import OPPONENT_CHOSE_MODE
from .grammar.postmodifiers import COST_TAPPED_REFERENT
from .grammar.vocabulary import (IMPLEMENTED_KEYWORDS,
                                 TYPE_LINE_SUPERTYPES as _TYPE_LINE_SUPERTYPES)

__all__ = [
    "ActivatedAbilityCost",
    "ModalOption",
    "OracleInstruction",
    "OracleProgram",
    "OracleToken",
    "ParsedActivatedAbility",
    "ParsedTriggeredAbility",
    "TriggerCondition",
    "compile_card_oracle",
    "lex_oracle_text",
    "normalize_creature_line",
    "parse_activated_ability_cost",
    "chargeable_sacrifice_payload",
    "trigger_condition_of_line",
]


# The keyword registry lives in `engine/grammar/vocabulary.py` and this module
# reads it. It used to be spelled out here as well — seventeen Title Case
# strings beside seventeen lowercase ones, held equal by hand, compared by
# nothing. The two gate different halves of the same question (this one admits a
# printed keyword *line*; the grammar's refuses to *lower* an unimplemented
# keyword), so a keyword added to one and not the other produces a card that is
# either admitted and inert or refused for a behaviour that exists — and a new
# set is a keyword-adding event by definition.
#
# This is the rule the comment on `_is_supported_static_creature_line` already
# states for lord buffs and combat restrictions: the gate and the dispatch must
# read the SAME table. Held by `tests/engine/test_keyword_registry.py`, which
# checks the gate's *behaviour* against the registry rather than comparing two
# lists — comparing them is something a future second copy would also pass.
# Keyword *mechanics* the engine does not model at all, named as the ingested
# `keywords` field spells them. This is not the negation of the registry above —
# "Enchant", "Regenerate" and "Landwalk" are Scryfall keyword tags whose
# behaviour lives elsewhere (`engine/auras.py`, the regeneration handler, the
# evasion table), so deriving this set from `KEYWORD_ABILITIES -
# IMPLEMENTED_KEYWORDS` would refuse every Aura in the pool.
#
# It is a *third* place a keyword's name can appear, and the one that fails
# silently in the expensive direction: an entry here outranks every line gate,
# so a keyword implemented in full still costs its cards their support until
# the word is deleted from this set. Rampage sat here through the whole of
# round 1's implementation and the seven Legends cards stayed unsupported with
# the behaviour built and tested. `tests/engine/test_keyword_registry.py`
# compiles a card carrying each implemented keyword *in its ingested field* for
# exactly that reason.
#
# **Empty since Mirage**, when phasing — its last entry — was implemented
# (CR 702.26, `Game.resolve_phasing_for`). Empty is the state to prefer: a
# keyword the engine does not model refuses at the line gate anyway, naming the
# clause, and this set is the only refusal that names nothing. Adding a word
# here again is a decision to refuse a card *before* reading it, and it needs
# the reason written down beside the word.
UNSUPPORTED_KEYWORDS: set[str] = set()

# Substrings that veto a card before any line is read. Empty, and kept empty
# deliberately: a blanket refusal on a *phrase* is the pre-grammar shape — it
# reports the whole card unsupported without naming a clause, and it goes on
# doing so after the clause is implemented. "exchange control" sat here until
# CR 701.12b's production arrived, at which point Gauntlets of Chaos compiled
# cleanly and was still refused by this line. A line the grammar cannot read
# already refuses itself, naming what it could not read; that is the refusal
# this table is not needed for.
UNSUPPORTED_PATTERNS: tuple[str, ...] = ()


#: **Empty**, and that is the whole story of this table.
#:
#: It admitted a card into the support gate on a *substring*. It held 73
#: entries; a deletion probe — remove one, recompile all 2,181 cards, count who
#: stops being supported — found that 68 of them carried nobody. They were whole
#: printed sentences from before the grammar could read them (Timetwister's,
#: Wheel of Fortune's, the landwalk grants, the ante cards), and the table never
#: reported that it had stopped being needed. Three of the rest were the bare
#: words ``deals``, ``loses`` and ``gain``, which matched any sentence
#: containing them and let six of Mirage's thirteen unimplemented sentences
#: through the gate.
#:
#: The last five were Auras, and they were the interesting ones: an Aura's
#: ``Enchant <subject>`` line is a keyword ability (CR 702.5) producing no
#: instruction, and its effects are continuous rather than instructions, so a
#: fully implemented Aura had **no evidence of support** for the gate to find.
#: ``engine/auras.py`` was a refusal and never an approval. It is both now
#: (:func:`auras.aura_claim`), asked by ``_derived_static_claims`` like every
#: other derivation table, so an Aura is supported because this engine
#: implements it rather than because its text contains two words.
#:
#: Armor of Thorns is the epitaph. Its clause reads "Enchant **nonblack**
#: creature", which the literal ``"enchant creature"`` never matched, so the
#: card was carried by ``"gets +"`` — a different substring on a different line
#: — for an Aura that worked perfectly. Support had come loose from working.
#:
#: Keep it empty. A card the engine implements has something to show for it; a
#: card that has nothing to show for it is not implemented.
SUPPORTED_SPELL_PATTERNS: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Supported trigger condition patterns
# Each entry: (kind, regex_or_substring)
# Checked in order; first match wins.
# ---------------------------------------------------------------------------

#: A run of comma-joined **negated** adjectives, for the front of a subject
#: group -- "a **nonartifact, non-Dragon** creature" (Catacomb Dragon).
#:
#: The comma bound on a subject group is load-bearing everywhere in this table:
#: a trigger condition ends at a comma, so a group bounded by ``[^,]+`` can
#: never reach into the effect clause. This is the one printed shape where a
#: comma falls *inside* the noun phrase instead of after it. The noun parser
#: reads the run perfectly well; only the delimiter could not see past the first
#: comma, so the whole condition went unread and the card was refused with every
#: one of its lines grammar-clean -- the refusal the census cannot attribute to
#: any clause.
#:
#: Admitted for a "non-" word alone, which is what keeps the bound load-bearing:
#: no effect clause begins with one, so the run still cannot cross the trigger's
#: own comma. A row adopting it is one name; rows that never print the shape
#: keep the plain bound, per this table's rule that a narrowing is listed once
#: the pool prints it.
_NEGATED_ADJECTIVE_RUN = r"(?:non-?[a-z'-]+, )*"


# "whenever" triggers
WHENEVER_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("land_dies",                   r"whenever a land is put into a graveyard from the battlefield"),
    # The same event, any permanent, narrowed by a printed noun phrase:
    # "Whenever an **artifact you control** is put into a graveyard from the
    # battlefield" (Tablet of Epityr, Urza's Miter). After the land row, which
    # keeps its own dispatcher and its own damage shape (Dingus Egg) — this one
    # is the general reading and would otherwise claim that line too.
    # The same event with CR 603.4's intervening-if about *how* it died
    # (Urza's Miter). Before the unqualified row, whose pattern is this one's
    # prefix — matched first it would drop the qualifier and the ability would
    # fire on a sacrifice the card excludes, which is a trigger working more
    # often than it prints.
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into a graveyard from the battlefield"
     r", if it (?P<dying_not_sacrificed>wasn't sacrificed)"),
    # "…is put into **your** graveyard from the battlefield" (Enduring Renewal)
    # and its mirror, "…into **an opponent's** graveyard…" (Grim Feast).
    # Whose graveyard is a narrowing the *subject* cannot carry: CR 404.1 sends
    # a permanent to its **owner's** graveyard, and who owns it is not a
    # characteristic `subject_matches` reads off a permanent. So it is its own
    # payload key, tested by the dispatcher against the observer's seat — one
    # key with two values rather than two conditions, because the dispatcher's
    # question ("is the owner this observer?") is the same one answered either
    # way round. Before the unqualified row, whose pattern would otherwise match
    # the same line with the possessive read as part of nothing and the
    # narrowing dropped — a trigger firing on every graveyard there is.
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into "
     r"(?P<dying_graveyard_owner>your|an opponent's) "
     r"graveyard from the battlefield"),
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into a graveyard from the battlefield"),
    # "Whenever **you** discard a card" (Necropotence). CR 701.9a's discard is
    # an action abilities watch, and the two discard seams announce it — the
    # random/forced one and the chosen one — so both spellings of a discard
    # reach this condition rather than only the one the first card exercised.
    ("you_discard_card",            r"whenever you discard a card"),
    ("creature_dies",               r"whenever a creature dies"),
    # "Whenever equipped creature dies" (Malefic Scythe) / "When enchanted
    # creature dies" (Creature Bond). One kind for both words: an Equipment and
    # an Aura attach the same way in this engine, and the condition is about the
    # permanent *this one is attached to* either way. Which of the two the card
    # printed is not a difference the dispatcher can act on.
    #
    # The identical row appears in the "when" table below, and the pattern
    # accepts either verb in both places rather than being split between them.
    # Two cards print two spellings of one condition, so a pattern per table
    # would leave each table's row matched by only one of them — and the guard
    # that keeps every kind reachable checks each table against *every* example.
    ("attached_creature_dies",      r"when(?:ever)? (?:equipped|enchanted) creature dies"),
    ("creature_you_control_dies",   r"whenever a creature you control dies"),
    # The mirror scope (Massacre Wurm). Its own kind rather than a payload
    # narrowing, because the dispatcher's *scoping* differs: this one fires for
    # observers who did **not** control the dead creature.
    ("creature_opponent_controls_dies",
     r"whenever a creature an opponent controls dies"),
    # The same set spelled to make the source's own death explicit (Basri's
    # Lieutenant). "This creature" is one of the creatures you control — its
    # controller is who "you" means — so the union names exactly what the
    # entry above does, and mapping both onto one kind keeps one dispatcher.
    ("creature_you_control_dies",
     r"whenever this creature or another creature you control dies"),
    # First match wins and patterns are unanchored at the end, so a pattern
    # that is a strict prefix of a later pattern's text would shadow it —
    # specific forms must precede their generic prefixes. Guarded by
    # tests/engine/test_trigger_tables.py.
    # **CR 120.4b's event, once.** "Whenever <someone> deals [combat|noncombat]
    # damage [to <someone>]" was five kinds here and two more further down, and
    # every one of them named the same thing happening — which is how each ended
    # up dispatched from wherever its card happened to be played out. The
    # unqualified reading (El-Hajjâj, Spirit Link) was announced from inside the
    # combat damage step's *player* loop, so it gained nothing for damage dealt
    # to a blocker or by an ability; Hypnotic Specter's "deals damage to an
    # opponent" was combat-only for the same reason; the two halves of Garruk's
    # Harbinger's "a player or planeswalker" had two fire sites so that the card
    # would see both.
    #
    # One row, one kind, one announcement (`damage_events._announce`), and every
    # narrowing the pool prints is a named group the dispatcher reads:
    #
    # - the **damager** — "this creature", "enchanted creature", "a source you
    #   control", or any noun phrase the noun parser reads (Hooded Blightfang's
    #   "a creature you control with deathtouch");
    # - whether the card said **combat** or **noncombat**;
    # - the **recipient** — a player, an opponent, you, a planeswalker, or the
    #   union Garruk's Harbinger prints.
    #
    # The comma bound on the subject group is load-bearing, as everywhere in
    # this table: a trigger condition ends at one, so the group can never reach
    # into the effect clause.
    ("damage_dealt",
     r"whenever (?:"
     r"(?P<damager_self>this (?:creature|artifact|enchantment|land|permanent))"
     r"|(?P<damager_attached>enchanted (?:creature|artifact|enchantment|land|permanent))"
     r"|a source (?P<damager_controller>you) control"
     # "…a red creature **or spell** deals damage" (Justice). One object, two
     # nouns: English prints the adjective once and distributes it, so the
     # subject group takes "a red creature" and the marker records that the
     # same phrase also names a *spell*. Non-greedy, so the shorter subject
     # plus the marker is preferred over the longer subject the noun parser
     # would then refuse — which is what "a red creature or spell" used to do,
     # taking the whole trigger down with it. Empty for every card that does
     # not print the union, because an absent optional group is not in the
     # match's groupdict.
     r"|(?P<damager_subject>[^,]+?)(?P<damager_includes_spells> or spell)?"
     r")"
     r" deals(?: (?P<damage_combat>combat|noncombat))? damage"
     r"(?: to (?:"
     # "…deals damage to **you or a white creature you control**" (Mangara's
     # Equity). A recipient that is a seat *or* a permanent, which no single
     # word in the list below can say: the fixed words all name a player or a
     # planeswalker, and this sentence names a player and an arbitrary noun
     # phrase. So the seat word stays a word and the object half is delimited
     # as a `_subject` group, read by the same noun parser every other narrowed
     # condition in this table goes through — a card printing "to you or a
     # creature you control" or "to an opponent or a permanent they control"
     # is the same trigger with different payload.
     #
     # First, and the ordering is this table's usual rule: "you" is a strict
     # prefix of "you or …", so the fixed list below would claim the seat word
     # and then fail the comma bound, taking the whole condition down with it.
     # That is exactly what it did — Mangara's Equity's third sentence compiled
     # to nothing at all.
     r"(?P<damage_recipient_seat>you|an opponent) or"
     r" (?P<damaged_subject>an? [^,]+)"
     r"|(?P<damage_recipient>a player or planeswalker|a player"
     r"|an opponent|a planeswalker|you)"
     r"))?(?=,|$)"),
    # "…blocks **or becomes blocked by** a non-Wall creature" (Thicket Basilisk,
    # Cockatrice), "…by a green or white creature" (Abomination), "…by a
    # creature" (Aisling Leprechaun). One printed sentence joining the two
    # events either half of it already names, and the noun phrase distributes
    # over **both** verbs — the Basilisk destroys no Wall whichever side of the
    # block it was on. So the phrase is delimited once and lands under both
    # halves' filter keys (`_PAIR_SUBJECT_GROUP_SUFFIX`), and the two general
    # dispatchers in phases/declare_blockers_step.py read it exactly as they
    # read a card that prints the halves separately (Infernal Medusa does).
    #
    # The kind used to spell the narrowing — `..._blocked_by_nonwall` — and had
    # a bespoke fire site to match, which is why Abomination's identical
    # sentence with one word changed compiled unsupported. Same lesson as the
    # land type in combat_restrictions.py and the threshold in round 14.
    # "Whenever **enchanted creature** blocks or becomes blocked by …"
    # (Infinite Authority). The same joined event about the same creature, with
    # the source's own spelling below it — which permanent's ability is watching
    # is the narrowing, and it is payload, exactly as `combatant_attached` is on
    # `creature_attacks_or_blocks`. The two combat fire sites read the key and
    # scan the combatant's attachments beside its own abilities.
    ("creature_blocks_or_blocked_by",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) blocks or becomes blocked by"
     r" (?P<block_pair_subject>(?:a|another) [^,]+)"),
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked by (?P<block_pair_subject>(?:a|another) [^,]+)"),
    # "…blocks or becomes blocked by **one or more Orcs**" (Dwarven Soldier).
    # CR 509.3e: an ability that triggers on blocking or being blocked by *at
    # least* a number of creatures triggers **once**, however many answer — the
    # opposite firing from the singular row above it, which fires once per
    # creature the phrase admits (CR 509.3b/509.3d). So the count is payload the
    # two dispatchers read, and the plural group suffix is what says the noun
    # phrase is the counted kind ("Orcs") rather than a quantified one ("an
    # Orc"). Below the singular row, which it does not collide with, and above
    # the bare row, which is its strict prefix.
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked by "
     r"(?P<block_pair_count>[a-z]+) or more (?P<block_pair_subjects>[^,]+)"),
    # The bare joined sentence (Spitting Slug). CR 509.3c/509.3d: with no noun
    # phrase it fires **once** for the block, where the narrowed rows above fire
    # once per creature the phrase admits — and the absence of the filter is
    # what both dispatchers read to tell them apart. Below the narrowed rows
    # because it is a strict prefix of them: matching it first would read
    # "by a creature that has been dealt damage this turn" as the effect clause.
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked"),
    # The same bare joined sentence watched by an Aura (Gift of the Woods).
    # Below the narrowed enchanted row above, which it is a strict prefix of —
    # matching here first would read Infinite Authority's "by a creature that
    # has been dealt damage this turn" as the effect clause. CR 509.3c/509.3d
    # give it the once-per-block firing the bare row beside it already has; the
    # only difference is `combatant_attached`, which is what sends the two
    # combat dispatchers to the combatant's attachments instead of its own card.
    ("creature_blocks_or_blocked_by",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) blocks or becomes blocked"),
    # "Whenever **enchanted creature** attacks or blocks" (Imprison). One kind
    # with the source's own spelling below it: it is the same event about the
    # same creature, and which permanent's ability watches it is the narrowing
    # — payload, exactly as `tapped_attached` is. The two combat fire sites read
    # the key and scan the attachments beside the combatant's own abilities.
    ("creature_attacks_or_blocks",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks or blocks"),
    ("creature_attacks_or_blocks",  r"whenever this creature attacks or blocks"),
    # A trigger whose *subject* is a set of objects rather than the source:
    # "whenever a creature you control with deathtouch attacks" (Hooded
    # Blightfang). Its own kind rather than a narrowing of `creature_attacks`,
    # because the scoping is the whole dispatch — that one fires the attacking
    # creature's own ability, this one fires every permanent whose filter the
    # attacker answers, and the source need not be attacking at all. The subject
    # group is read by the noun parser (see `_resolve_subject_groups`), and the
    # comma bound is load-bearing: a trigger condition ends at one, so `[^,]+`
    # can never reach into the effect clause.
    # "Whenever **a player** attacks with one or more creatures, …" (Total
    # War.) The same declaration read from every seat rather than from the
    # ability's own controller — which is a question about the event, not a
    # different event, so it shares the kind the two "you attack" rows below
    # use and says so in the payload. `engine/events.py`'s filter is what reads
    # the marker; the empty group is the `_includes_source` spelling, present
    # in the groupdict exactly when this row matched and carrying no text of
    # its own to re-read.
    #
    # **Above** the per-creature row, which it is not a prefix of but which
    # claims it anyway: "a player attacks" answers `(?:a|another) [^,]+ attacks`
    # with "player" as the noun phrase, and a phrase the noun parser cannot
    # read refuses the whole condition rather than falling through to a later
    # pattern — so ordering is the only thing that gets this line to its row.
    ("attackers_declared",
     r"whenever (?P<any_attacking_seat>)a player attacks with "
     r"(?P<attackers_count>[a-z]+) or more (?P<attacker_subjects>[^,]+)"),
    # The negative lookahead is the whole of what keeps this row honest.
    # "attacks" is unanchored here because the effect clause follows it, and
    # "whenever a creature attacks **and isn't blocked** this combat" (Melee)
    # answered the pattern with "creature" as the noun and the rest of the
    # condition left unread — a condition that fires on *every* attack where
    # the card prints one that fires on an unblocked one. Melee is a spell, so
    # it only went hollow; a permanent printing the sentence would have played
    # wider than it reads, silently. Refusing sends the line on to the delayed
    # reading (`_parse_delayed_attack_trigger`), and a permanent printing it
    # is reported unsupported naming the clause, which is the loud direction.
    # "Whenever a creature attacks **you**" (Barbed Foliage). CR 506.2's
    # defending player as a narrowing of the *subject* — the same
    # `attacking_you` field "target creature that's attacking you" already sets,
    # folded in by `_resolve_subject_groups` from the empty marker group. Above
    # the bare row, which is its strict prefix and which claimed it: matched
    # there, the "you" is left unread and the trigger fires on every attack in
    # the game, which in a two-player duel is only ever visible in the turn a
    # player attacks somebody else's planeswalker and in a multiplayer game is
    # the whole restriction gone. The same silent widening the "and isn't
    # blocked" lookahead one line down exists to stop.
    ("matching_creature_attacks",
     r"whenever (?P<attacker_subject>(?:a|another) [^,]+) attacks"
     r" (?P<attacker_attacking_you>)you(?![a-z])"),
    ("matching_creature_attacks",
     r"whenever (?P<attacker_subject>(?:a|another) [^,]+) attacks(?! and isn't blocked)"),
    # Two spellings of one event: the *declaration* (CR 508.1), which is the
    # only thing that can answer "how many creatures attacked". One kind and two
    # rows, because what differs is not the event but what the card asks about
    # it — and that is payload, the way a narrowed condition's filter is.
    # Ordered above the bare per-creature "attacks" rows below: "this creature
    # and at least …" is not a prefix of "this creature attacks", but the
    # specific-before-generic rule is what keeps that true when either is edited.
    #
    # "Whenever you attack with two or more creatures with flying …" (Tide
    # Skimmer). The count and the noun phrase are both payload: the regex
    # delimits them and the noun parser reads the phrase (round 34).
    ("attackers_declared",
     r"whenever you attack with (?P<attackers_count>[a-z]+) or more (?P<attacker_subjects>[^,]+)"),
    # "Whenever this creature and at least two other creatures attack …"
    # (Makeshift Battalion, printed under the ability word "Battalion", which
    # CR 207.2c strips before this table sees the line). The source must be
    # among the attackers, so the *others* are counted and the source is the
    # one that is not.
    ("attackers_declared",
     r"whenever this creature and at least (?P<others_count>[a-z]+) other creatures attack"),
    # "Whenever an opponent attacks with creatures, if two or more of those
    # creatures are attacking you and/or planeswalkers you control, …"
    # (Mangara, the Diplomat.) The *opponent's* declaration rather than the
    # controller's, and the intervening-if counts how many of that batch are
    # aimed at this permanent's controller — a different question from "how many
    # attacked", which is why the count is not part of the condition.
    ("opponent_attackers_declared",
     r"whenever an opponent attacks with creatures"),
    # "Whenever an opponent casts their **second** spell each turn" (Mangara).
    # Round 123's ordinal with the other seat asking: same event, same question,
    # a different player's record. Its own kind because the *fire site* differs
    # — this one is announced for every seat, that one only for the caster.
    ("opponent_casts_nth_spell_each_turn",
     r"whenever an opponent casts their (?P<spell_ordinal>[a-z]+) spell each turn"),
    # "Whenever this creature attacks and isn't blocked" (Merchant Ship). Its
    # own condition, ordered before the bare "attacks" it is a prefix of: the
    # event is the same declaration, but "isn't blocked" can only be known once
    # blockers are (CR 509.1h), so it is announced at the combat damage step
    # (engine/phases/combat_damage_step._fire_unblocked_attack_triggers) rather
    # than at declare-attackers with the generic attack triggers.
    # "Whenever **enchanted creature** attacks and isn't blocked" (Cloak of
    # Confusion), above the source's own spelling for the same reason every
    # attached row in this table sits above its unattached twin: one kind,
    # because it is one event, and which permanent's ability is watching is the
    # narrowing — payload, exactly as `combatant_attached` is on
    # `creature_attacks_or_blocks`. The declare-blockers fire site reads the key
    # and scans the attacker's attachments beside its own abilities.
    ("attacks_unblocked",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks and isn't blocked"),
    ("attacks_unblocked",           r"whenever this creature attacks and isn't blocked"),
    ("creature_attacks",            r"whenever this creature attacks"),
    # "…blocks **a creature with flying**" (Snarespinner) narrows the source's
    # own block trigger by what it blocked. Before the bare form, which is its
    # strict prefix: matching that first is what made Snarespinner compile to an
    # unnarrowed condition with its rider dropped on the floor.
    ("creature_blocks",
     r"whenever this creature blocks (?P<blocked_subject>(?:a|another) [^,]+)"),
    # "…blocks **one or more black creatures**" (Rashka the Slayer). The counted
    # spelling of the row above, arranged exactly as the joined
    # `creature_blocks_or_blocked_by` family already arranges its own: singular
    # first, counted second, bare last. CR 509.3e is what the number means — an
    # ability that triggers on blocking *at least* N creatures fires **once**,
    # however many answered, where the singular row fires once per creature
    # (CR 509.3b) — and the threshold is read by `_threshold_firings` in
    # phases/declare_blockers_step.py off the same `block_pair_count` key
    # Dwarven Soldier's joined sentence writes. One key, because it is one rule
    # about one number; a second spelling of it would be a second reader free
    # to disagree about how often the ability fires.
    #
    # Rashka is why this row is not a nicety. Its card *compiled supported*
    # without it — the keyword line above carries the card — while this sentence
    # fell through to the bare row below, so the +1/+2 fired on blocking
    # anything at all. The census cannot see that (a card is supported when any
    # of its lines is); `scripts/parse_coverage.py` named the sentence and
    # nothing else did.
    ("creature_blocks",
     r"whenever this creature blocks (?P<block_pair_count>[a-z]+) or more "
     r"(?P<blocked_subjects>[^,]+)"),
    ("creature_blocks",             r"whenever this creature blocks"),
    # "…becomes blocked by **a creature**" (Gloom Sower): once per blocking
    # creature that answers the filter (CR 509.1h), where the bare form below
    # fires once for the block itself. Same ordering rule.
    ("creature_becomes_blocked",
     r"whenever this creature becomes blocked by "
     r"(?P<blocker_subject>(?:a|another) " + _NEGATED_ADJECTIVE_RUN + r"[^,]+)"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
    # "Whenever **enchanted creature** becomes blocked" (Bestial Fury). The
    # attacking half of the pair above watched by an Aura rather than by the
    # creature — one kind, because it is one event, with `combatant_attached`
    # carrying which permanent's ability is watching. No narrowed "…by <noun>"
    # spelling is listed: none is printed in the pool, and an unlisted one is
    # refused loudly by both front ends rather than read as this bare row with
    # its noun phrase dropped.
    ("creature_becomes_blocked",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) becomes blocked"),
    # "Whenever **enchanted creature** is dealt damage, this Aura deals that
    # much damage to that creature's controller." (Binding Agony.) The same
    # event as the row below, watched by something attached to the damaged
    # creature rather than by the creature itself — one kind, with
    # `damaged_attached` saying which permanent's ability is watching, exactly
    # as `combatant_attached` does for the combat events and `tapped_attached`
    # for the tap one. A key per event family rather than one shared key: the
    # fire sites are different functions and each scans for its own, so a shared
    # spelling would have the combat scan pick up a damage trigger.
    #
    # Above the self spelling it is not a prefix of, in the order this table's
    # own note asks for.
    ("creature_dealt_damage",
     r"whenever enchanted (?P<damaged_attached>[a-z]+) is dealt damage"),
    ("creature_dealt_damage",               r"whenever this creature is dealt damage"),
    ("creature_dealt_damage_by_self_dies",  r"whenever a creature dealt damage by this creature this turn dies"),
    # "Whenever this creature becomes the target of a spell or ability an
    # opponent controls" (Warden of the Woods). Whose spell it must be is a
    # named group, so "you control" and the unnarrowed form are the same
    # condition with different data — the arrangement the tapped trigger below
    # already uses, for the same reason.
    #
    # A separate kind from the WHEN table's `becomes_target`, because a kind
    # lives in one table: that one is a one-shot wording no card in the pool
    # prints, and it still has no dispatcher.
    # Any permanent, because CR 603.2's event is about an object and Mirage
    # prints it on an enchantment (Forsaken Wastes). Which **class** of object
    # did the targeting is a named group beside whose it was, for the reason
    # this table gives everywhere else: "a spell" and "a spell or ability" are
    # one condition with different data, and a card that says only "a spell"
    # must not fire on an activated ability. Longest alternative first — the
    # match is unanchored at the end, so "a spell" listed ahead of "a spell or
    # ability" would consume the shorter reading and drop the rest.
    ("self_becomes_target",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) becomes "
     r"the target of (?P<targeted_by>a spell or ability|a spell|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    # "Whenever this creature becomes untapped" (Ghostly Pilferer). CR 701.26b's
    # event, announced by the one untap seam — which is why the seam had to
    # exist first: eleven places set the flag, and a trigger wired into one of
    # them would have missed the other ten.
    ("permanent_becomes_untapped",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) becomes untapped"),
    # "Whenever this creature phases out" / "…phases in" (Teferi's Imp, Warping
    # Wurm). CR 702.26's event, announced from the two seams that move a
    # permanent between the battlefield and its controller's holding list
    # (`Game.phase_out_permanent` / `phase_in_for`) rather than from the untap
    # step — the untap step is only one of the ways a permanent phases, and a
    # trigger wired there would miss Reality Ripple and every activated
    # phase-out in Mirage.
    ("phases_out",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) phases out"),
    ("phases_in",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) phases in"),
    # "Whenever a Forest an opponent controls becomes tapped" (Lifetap). The
    # type and the controller scope are named groups, so the restriction
    # arrives as condition-payload data and one dispatcher
    # (engine/events.py::_becomes_tapped_filter) covers every card written this
    # way.
    #
    # **One kind for every "becomes tapped" trigger, and the two that used to
    # have their own are the reason.** `enchanted_land_tapped` (Psychic Venom)
    # and `self_becomes_tapped` (City of Brass) named the same CR 701.26a event
    # about a different subject, and each was dispatched by a hand-written pass
    # inside `tap_land_for_mana` — so both fired on the *one* tapper that pass
    # sits in and on none of the other ways a land becomes tapped. That is the
    # failure `become_tapped` was built to end, and a second condition kind is
    # what let it survive the seam: an emit nobody listens for is indistinguish-
    # able from an event that never happened. The subject is payload now —
    # `tapped_attached` for the permanent this one is attached to,
    # `tapped_self` for the source itself, `tapped_subtype`/`tapped_controller`
    # for a quantified class — and the one dispatcher reads whichever is there.
    # "Whenever an artifact becomes tapped **or a player activates an
    # artifact's ability without {T} in its activation cost**" (Haunting Wind,
    # Powerleech). One printed ability with two trigger events, so it is one
    # kind announced from two sites rather than two conditions.
    #
    # **Before the bare tapped row, and this ordering is load-bearing.** That
    # row's pattern is unanchored at the end, so it matches this line's prefix
    # and silently drops the activation half: the condition compiled as a plain
    # tap trigger and the effect clause — everything from "or a player…" —
    # became unparseable, which is the only reason the truncation showed up at
    # all. Had the effect happened to parse, the card would have compiled clean
    # and fired on half the events it prints.
    # The same condition with the Aura's own attached permanent as its subject
    # (Artifact Possession). One kind, because it is one event asked about a
    # different set of permanents — the narrowing is payload, exactly as
    # `tapped_subtype` is — so both emit sites and the dispatcher are unchanged.
    # Before the quantified row: "enchanted artifact" is not "an artifact", but
    # keeping the specific subject ahead of the general one is what this table
    # does everywhere.
    # "Whenever a player activates an ability of enchanted creature **with**
    # {T} in its activation cost that isn't a mana ability" (Imprison). Not a
    # wording of the compound row below it: that one is a *tap* event with an
    # activation clause joined onto it, and this is the activation alone — so a
    # card printing it must not fire when the creature is tapped by attacking.
    #
    # Both printed narrowings are payload, the way every narrowing in this
    # table is: which side of {T} the cost falls on is one word, and the noun
    # after "enchanted" is the type the attached permanent has to be.
    ("nonmana_ability_activated",
     r"whenever (?:a player|an opponent) activates an ability of"
     r" enchanted (?P<activated_attached>[a-z]+)"
     r" (?P<activated_requires_tap>with|without) \{t\} in its activation cost"
     r" that isn't a mana ability"),
    ("permanent_tapped_or_ability_activated",
     r"whenever enchanted (?P<tapped_attached>[a-z]+) becomes tapped"
     r" or (?:a player|an opponent) activates an ability of enchanted [a-z]+"
     r" without \{t\} in its activation cost"),
    ("permanent_tapped_or_ability_activated",
     r"whenever an? (?P<tapped_subtype>[a-z]+)"
     r"(?: (?P<tapped_controller>an opponent controls|you control))? becomes tapped"
     r" or (?:a player|an opponent) activates an? [a-z']+ ability"
     r" without \{t\} in its activation cost"),
    # The two named subjects, ahead of the quantified row they are not a
    # wording of. "Enchanted <noun>" is the permanent this Aura is attached to
    # (Psychic Venom, Blight, Spirit Shackle); "this <noun>" is the source
    # itself (City of Brass). Both spellings appear in the "when" table too,
    # because Blight prints the one-shot trigger word for the same event.
    ("permanent_becomes_tapped",
     r"when(?:ever)? enchanted (?P<tapped_attached>[a-z]+) becomes tapped"),
    ("permanent_becomes_tapped",
     r"when(?:ever)? this (?P<tapped_self>creature|artifact|enchantment|land|permanent)"
     r" becomes tapped"),
    ("permanent_becomes_tapped",
     r"whenever an? (?P<tapped_subtype>[a-z]+)"
     r"(?: (?P<tapped_controller>an opponent controls|you control))? becomes tapped"),
    # "Whenever a **Swamp, Mountain, black permanent, or red permanent**
    # becomes tapped" (Royal Decree). A printed *noun phrase* rather than a
    # word -- a union across CR 205.3 subtypes and CR 105 colours, which the
    # single-word group above cannot hold and which no pair of payload keys
    # says either (they are ANDed). So it is a `_subject` group, read by the
    # noun parser into the same `any_classes` every other reader of that union
    # already tests.
    #
    # **After** the narrow rows and not beside them: this pattern's subject
    # spans commas and would otherwise claim their lines too. The word row
    # cannot claim *this* line -- its `[a-z]+` stops at the first comma -- so
    # the ordering costs nothing and keeps the commoner spellings first.
    ("permanent_becomes_tapped",
     r"whenever (?P<tapped_subject>an? .+?) becomes tapped"),
    # "Whenever a Mountain is tapped for mana" (Gauntlet of Might) narrows the
    # same condition to one land type; the unnarrowed "whenever a player taps a
    # land for mana" (Manabarbs, Mana Flare) follows it.
    #
    # ``an?`` because English chooses the article by the *next word*, not by
    # anything about the rule: "a Mountain" and "**an** Island" are the same
    # condition, and the row that read only "a " left Snowfall's whole ability
    # undispatched — the card compiled supported on its cumulative upkeep and
    # made no mana at all. The sibling row above it already spelled it this way.
    ("land_tapped_for_mana",        r"whenever an? (?P<tapped_land_subtype>[a-z]+) is tapped for mana"),
    # "Whenever a player taps a **snow** land for mana" (Winter's Night). The
    # active voice with a *supertype* narrowing, and its own group because a
    # supertype is not a type: the fire site asks ``has_type`` for
    # ``tapped_land_subtype`` (CR 613 layer 4) and ``has_supertype`` for this
    # one (CR 205.4a), and a supertype read through the type accessor answers
    # False for every land — a trigger that never fires, on a card reporting
    # itself supported.
    #
    # The alternation is built from ``TYPE_LINE_SUPERTYPES`` rather than
    # spelled out, so it is the vocabulary catalog's list and not a second copy
    # of it. A bare ``[a-z]+`` here would match "nonbasic land", which is a
    # negation no supertype accessor answers — the narrowing would be dropped
    # and the trigger would fire on every land.
    #
    # Before the bare row below, which is its prefix in everything but the
    # narrowing.
    ("land_tapped_for_mana",
     r"whenever a player taps an? (?P<tapped_land_supertype>"
     + "|".join(sorted(_TYPE_LINE_SUPERTYPES)) + r") land for mana"),
    ("land_tapped_for_mana",        r"whenever a player taps a land for mana"),
    # "Whenever a player taps a **Mountain** for mana" — the active voice with a
    # land *type*, the twin of the passive row above it. No card prints it, and
    # it is here for the reason the two front ends exist at all: the grammar
    # reads the active voice through one noun-phrase parser, so a spelling it
    # admits and this table does not is a card whose trigger compiles on one
    # side and is invisible on the other — supported, with the ability simply
    # absent. Last of the three, because "a land for mana" and "a snow land for
    # mana" are both shapes the rows above answer more exactly.
    ("land_tapped_for_mana",
     r"whenever a player taps an? (?P<tapped_land_subtype>[a-z]+) for mana"),
    # A colour-narrowed cast trigger (the Rod/Cup/Sphere cycle). The colour is
    # captured into the condition payload so one dispatcher covers every card
    # written this way; must precede the unnarrowed form below.
    ("spell_cast",                  r"whenever a player casts a (?P<color_word>white|blue|black|red|green) spell"),
    # The same narrowing on the spell's *type* rather than its colour (Urza's
    # Chalice). Written with the group name `you_cast_spell`'s rows already use,
    # so all three cast kinds ask one helper (`events._cast_narrowing_admits`)
    # rather than each growing its own type test. Must precede the bare row.
    ("spell_cast",
     r"whenever a player casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    ("spell_cast",                  r"whenever a player casts a spell"),
    # "…from anywhere other than their hand" (Ghostly Pilferer). A narrowing on
    # the *zone the spell was cast from*, which the stack item already records
    # — the field the cast-permission seam added. Longest first: the bare row
    # below is its strict prefix.
    ("opponent_casts_spell",
     r"whenever an opponent casts a spell from anywhere other than their (?P<not_from_zone>hand)"),
    # "…a creature spell **that doesn't share a color with a creature you
    # control**" (Invoke Prejudice). A narrowing that is not about the spell
    # alone: it compares the spell's colours (CR 105.2) against a *set of
    # permanents* the printed noun phrase names, so the phrase is delimited as a
    # `_subject` group and the board it describes is payload. Before the type
    # row above's twin, whose pattern is its strict prefix.
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell "
     r"that doesn't share a color with (?P<unshared_color_subject>an? [^,]+)"),
    # "…**other than the first instant spell that player casts each turn**"
    # (Ichneumon Druid). An *ordinal exclusion*: the same cast event, admitted
    # only once the player has already cast that many of them this turn. The
    # ordinal is payload — a card printed "other than the second" is this row —
    # and the repeated type word is a backreference, so a card whose two halves
    # name different types refuses the line rather than compiling one of them.
    # Before the bare type row below, which is its strict prefix and would drop
    # the exclusion entirely: an ordinal a dispatcher never sees is a trigger
    # that fires on the spell the card exempts.
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"
     r" other than the (?P<after_spell_ordinal>[a-z]+) (?P=cast_type) spell that player casts each turn"),
    # "Whenever an opponent casts an artifact spell" (Citanul Druid) — the
    # type narrowing again, on the opponent-scoped kind. Before the bare row.
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    # The colour narrowing on the opponent-scoped kind (Freyalise's Charm,
    # Leshrac's Sigil), captured into the same `color_word` payload the
    # player-scoped row above uses — one narrowing read by one helper
    # (`events._cast_narrowing_admits`), not a second spelling of the question.
    # Before the bare row, which is its strict prefix.
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<color_word>white|blue|black|red|green) spell"),
    # "…a spell **that targets you or a creature you control**"
    # (Reparations). A narrowing on the spell's *targets* rather than on the
    # spell, so it is a marker group the cast filter reads against what the
    # announcement froze. Above the bare row, which is its strict prefix and
    # which claimed it: matched there the clause was left unread and the
    # enchantment drew a card off every spell an opponent cast, which is the
    # silent widening this table is ordered longest-first to prevent.
    ("opponent_casts_spell",
     r"whenever an opponent casts a spell that targets "
     r"(?P<targets_you_or_your_creature>)you or a creature you control"),
    ("opponent_casts_spell",        r"whenever an opponent casts a spell"),
    # A colour-list narrowing ("…a spell that's white, blue, black, or red",
    # Quirion Dryad). The list is condition payload, read by the you_cast_spell
    # event filter; must precede its unnarrowed prefix below.
    ("you_cast_spell",
     r"whenever you cast a spell that's (?P<cast_colors>[a-z]+(?:, [a-z]+)*,? or [a-z]+)"),
    # A type narrowing ("…a noncreature spell", Spellgorger Weird). The word
    # list is exactly what the event filter tests against the cast card's type
    # line — a word outside it (a subtype, say) must keep refusing rather than
    # compile and fire on every spell. "enchantment" stays its own condition
    # kind ("…an enchantment spell", Verduran Enchantress) for the label's
    # sake; the article split ("a"/"an") keeps the two from colliding.
    # "…your **first** instant or sorcery spell **each turn**" (Double Vision).
    # An ordinal, so it is its own condition kind rather than a flag: the event
    # is the same cast, but the question asked of it is "is this the first one?"
    # — and a card that fired on every such spell is a different card. Longest
    # first, as this table requires.
    ("you_cast_first_spell_each_turn",
     r"whenever you cast your first (?P<cast_types>instant or sorcery) spell each turn"),
    ("you_cast_first_spell_each_turn",
     r"whenever you cast your first (?P<cast_type>noncreature|nonartifact|creature|artifact|instant|sorcery) spell each turn"),
    ("you_cast_spell",
     r"whenever you cast an (?P<cast_types>instant or sorcery) spell"),
    ("you_cast_spell",
     r"whenever you cast a (?P<cast_type>noncreature|nonartifact|creature|artifact|instant|sorcery) spell"),
    # "…a **Dog** spell" (Rin and Seri, Inseparable). A creature *subtype*
    # rather than a card type, which the row above deliberately refused: its
    # word list is exactly what the event filter tests against the type line,
    # and a subtype admitted there would have been dropped and fired on every
    # spell. Read from the vocabulary instead of a literal list, so a set adding
    # a tribe needs `fetch_vocabulary.py` and nothing here — and matched
    # case-insensitively against the *printed subtype*, not against the whole
    # type line, so "Dog" does not answer a "Dogpile".
    ("you_cast_spell",              r"whenever you cast a (?P<cast_subtype>[a-z][a-z-]+) spell"),
    ("you_cast_spell",              r"whenever you cast a spell"),
    ("enchantment_cast",            r"whenever you cast an enchantment spell"),
    # Ankh of Mishra's land entry keeps its own kind and its own fire site, so
    # it precedes the general form below — which is the ordinary
    # specific-before-general rule, with the specific one being the *older*
    # entry for once.
    ("land_enters",                 r"whenever a land enters(?: the battlefield)?"),
    # "Whenever a creature you control with power 4 or greater enters" (Garruk's
    # Uprising). `creature_enters` and `artifact_enters` used to sit here as bare
    # forms with no dispatcher and, between them, no card — Garruk's Uprising
    # reported *supported* with this line compiling to nothing at all, which is
    # the partial-implementation class round 16 wrote down. Deleted rather than
    # kept beside this one: "whenever a creature enters" is this pattern with an
    # empty narrowing, and it fires now.
    # The same set spelled to make the source's own entry explicit (Thieves'
    # Guild Enforcer). "This creature" is one of the Rogues you control — its
    # controller is who "you" means — so the union names exactly what the
    # pattern below does *plus the source*, and the difference is one word in
    # the subject: "another" excludes the source, "a" does not. Mapping both
    # onto one kind keeps one dispatcher; the subject decides the rest.
    ("matching_permanent_enters",
     r"whenever this creature or (?P<enterer_subject>another [^,]+?) enters"
     r"(?: the battlefield)?(?P<enterer_includes_source>)"),
    ("matching_permanent_enters",
     r"whenever (?P<enterer_subject>(?:a|another) [^,]+) enters(?: the battlefield)?"),
    # "Whenever **a player puts a Swamp onto the battlefield**" (Thelon's
    # Chant, Tourach's Chant) — the same event named from the player's side.
    # One kind, because it is one event: the engine announces a permanent
    # entering from the one seam every entry path passes through, and a second
    # condition would need a second fire site watching the same moment. Below
    # the two rows above rather than beside them: this pattern's subject group
    # sits after three fixed words those cannot match, so no collision, and the
    # ordering keeps the commoner spellings first.
    #
    # ``an?`` for the reason the tap-for-mana rows one table over carry it:
    # English picks the article off the *next word*, and "a Swamp" and "**an**
    # Island" are the same condition. Written "a " this row read Nature's Wrath's
    # Swamp line and not its Island line — and the half it dropped did not
    # report unsupported, because `parse_line` has a trigger production of its
    # own: the sentence lowered as a **spell** instruction on an enchantment,
    # which is an ability that fires once, on the wrong event, for the wrong
    # seat.
    ("matching_permanent_enters",
     r"whenever a player puts (?P<enterer_subject>an? [^,]+?) onto the battlefield"),
    ("one_or_more_attack",          r"whenever one or more creatures you control attack"),
    # "Whenever one or more Cats you control deal combat damage to a player"
    # (Feline Sovereign). A **batched** trigger: however many creatures dealt
    # the damage, it fires once per player damaged — which is the difference
    # from the per-attacker condition below, not a wording of it. The subject is
    # counted rather than quantified, so the plural group.
    ("one_or_more_deal_combat_damage",
     r"whenever one or more (?P<damagers_subjects>.+?) deal combat damage to a player"),
    # "…are put on another non-Hydra creature you control" (Wildwood Scourge).
    # The excluded subtype is captured as condition payload, so a card printed
    # with any other tribe needs no code; "another" and "you control" are
    # fixed, because they are what the event filter enforces — a wording
    # without them names a different set and must refuse rather than be read
    # as this one.
    ("counters_put_on_creature",
     r"whenever one or more \+1/\+1 counters are put on another "
     r"non-(?P<counters_excluded_subtype>[a-z]+) creature you control"),
    # "Whenever you gain life …" (Vito, Thorn of the Dusk Rose). The event is
    # emitted from the one life-gain seam (`Game._gain_life`) *after* the
    # replacements have had the amount, so what the trigger sees is the life
    # that actually arrived — the same reading `life_gained_this_turn` takes.
    ("you_gain_life",               r"whenever you gain life"),
    # "Whenever you lose life …" (Oath of Lim-Dûl). Announced by the
    # state-based sweep off each seat's life total rather than from a call
    # site, because life leaves a player by half a dozen routes and a list of
    # them is only ever as complete as the last card that touched it — the
    # argument `draws_card` is dispatched with, one record over.
    ("you_lose_life",               r"whenever you lose life"),
    # "Whenever you sacrifice a permanent …" (Havoc Jester). Emitted from
    # ``Game.sacrifice_permanent``, the one place CR 701.21a happens — which is
    # why this row could be added without hunting for a fire site: there are
    # thirteen sacrifices in this engine and one transition.
    #
    # Deliberately unnarrowed. Real cards also print "…sacrifice a creature" and
    # "…sacrifice an artifact", and the subject-group machinery could read them,
    # but nothing in the pool does — and a filter with no card behind it is
    # untested by construction. A narrowed row goes *above* this one when a card
    # brings it (the specific-before-generic rule), and "creature" is not a
    # prefix of "permanent", so neither shadows the other.
    ("you_sacrifice_permanent",     r"whenever you sacrifice a permanent"),
    # "Whenever you activate a loyalty ability of a Chandra planeswalker …"
    # (Keral Keep Disciples). "Chandra" is a planeswalker *subtype*
    # (data/vocabulary/planeswalker_types.json) and never a card name, so the
    # regex only delimits the noun phrase and the noun parser reads it — the
    # `_subject` group machinery, in the position where a dropped rider would
    # fire the table off every planeswalker in the format. The "of an? …" is
    # required: a wording with no subject at all names a larger set than any
    # card prints and must refuse rather than compile unnarrowed.
    ("you_activate_loyalty_ability",
     r"whenever you activate a loyalty ability of (?P<walker_subject>an? [^,]+)"),
    # CR 121.2's per-card event, with the drawing seat as the one narrowing
    # any card prints on it. Both spellings are one kind: "you" and "an
    # opponent" name the same event asked of a different seat, and the seat is
    # what the event filter reads — so a printed "an opponent" is payload, in
    # exactly the position `targeting_controller` occupies above. Underworld
    # Dreams is the second spelling; Lorescale Coatl and Burlfist Oak the
    # first, whose absent group is how a pattern says "you".
    ("draws_card",
     r"whenever (?:you draw|(?P<drawer>an opponent) draws) a card"),
    # "…your second card each turn" (Mystic Skyfish, Jolrael). Fires once per
    # turn, announced by the draw sweep in check_state_based_actions off the
    # cards_drawn_this_turn record every draw path already feeds.
    ("draws_second_card",           r"whenever you draw your second card each turn"),
    # "**Whenever** there are four or more tide counters on this creature, …"
    # (Homarid, Tidal Influence); "**When** there are four or more page
    # counters on this artifact, …" (Mazemind Tome). CR 603.8's *state*
    # trigger: it fires whenever the game state matches, not on an event — so
    # it is checked by the state-based sweep rather than announced from a call
    # site, which is where every other "no single place this happens" condition
    # already goes.
    #
    # In this table rather than the "when" one, though Mazemind Tome prints the
    # other word: a kind lives in one table (the shadowing guard's canonical
    # examples are keyed by kind), and the *whenever* table is the one both
    # words reach — a "when" line this table misses is re-asked here with the
    # word swapped, and there is no fallback the other way. Written the other
    # way round, Homarid's printing had no reader at all.
    ("counters_reach_threshold",
     r"whenever there are (?P<counter_count>[a-z]+) or more (?P<counter_kind>[a-z]+) counters on this "
     r"(?:artifact|creature|enchantment|permanent|land)"),
    # "**When** this creature's power is 7 or greater, sacrifice it."
    # (Phyrexian Devourer.) CR 603.8 again, and the first state trigger that
    # reads a *characteristic* rather than a census or a counter store — so
    # it is checked by the state-based sweep beside the other three, where a
    # layer-computed power is what answers (CR 613.1f: a creature *given*
    # power counts, exactly as a printed one does).
    #
    # In the whenever table though the card prints "when", for the reason
    # `counters_reach_threshold` above it is: a kind lives in one table and
    # this is the table both printed words reach.
    #
    # The threshold is delimited here and read by `_NUMBER_WORDS`, so a card
    # printing any other number is payload rather than a second row.
    ("source_power_at_least",
     r"whenever this creature's power is (?P<power_count>[a-z0-9]+) or greater"),
    # "**When** this creature has flying, sacrifice it." (Floodgate.) CR 603.8
    # again, reading a *keyword* off the source where the row above reads a
    # power — and read through the layers for that row's reason, so a keyword
    # granted in layer 6 counts exactly as a printed one does (CR 613.1).
    #
    # The keyword is delimited here and carried as payload, so a card printed
    # with another one is a card this row already reads. In the whenever table
    # under the "when" the card prints, like every state trigger above it: a
    # kind lives in one table, and this is the one both printed words reach.
    # "**When** this enchantment has no +1/+1 counters on it, sacrifice it."
    # (Afiya Grove.) CR 603.8's state trigger again, and the *opposite* state
    # from `counters_reach_threshold` above rather than a threshold of zero:
    # read as "zero or more" that row would fire on a permanent holding three,
    # and read as "exactly zero" it would need a comparison field no other
    # printing uses. Two states, two kinds, one sweep.
    #
    # The counter kind is payload and its character class is wider than every
    # other row's, because a P/T counter is spelled with symbols (CR 122.1a) —
    # "+1/+1" is the kind here, where "page" and "tide" are the kinds above.
    #
    # **Above `source_has_keyword`**, whose pattern is `has (?P<keyword_name>
    # [a-z]+)` with nothing after it: a creature printing this sentence would
    # otherwise trigger on "having" a keyword called "no".
    ("source_has_no_counters",
     r"whenever this (?:artifact|aura|creature|enchantment|permanent|land) "
     r"has no (?P<counter_kind>[-+/0-9a-z]+) counters? on it"),
    ("source_has_keyword",
     r"whenever this creature has (?P<keyword_name>[a-z]+)"),
    # "**When** a player doesn't pay this enchantment's cumulative upkeep, …"
    # (Thought Lash.) Not a state trigger: CR 702.24a's ability resolves and
    # *fails to be paid* at one identifiable moment, so this is announced from
    # the one place that decides it (`phases/upkeep_effects.py`) rather than
    # swept for. The seat that did not pay is frozen on the event, because "that
    # player" behind it names them and nothing on a board records who declined.
    #
    # In the whenever table under the "when" the card prints, for the reason
    # every row above it gives: a kind lives in one table, and this is the one
    # both printed words reach.
    ("cumulative_upkeep_unpaid",
     r"whenever a player doesn't pay this "
     r"(?:artifact|creature|enchantment|permanent|land)'s cumulative upkeep"),
)

# "when" triggers (enter/leave events)
WHEN_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("enters_battlefield",          r"when (?:this|.+) enters(?: the battlefield)?"),
    # "When **the token** leaves the battlefield, sacrifice this enchantment."
    # (Dance of Many.) CR 603.6c's event asked about a *different* object from
    # the one whose ability it is — the token this permanent created — which is
    # the same shape as `attached_creature_dies` below, an Aura watching its
    # host. The relation is in the kind because it is the relation the fire
    # site dispatches on; nothing about the token itself narrows it.
    #
    # Above the generic row and deliberately not folded into it: that row's
    # `.+` swallows "the token" and reports the ability as watching the
    # enchantment, which is a trigger firing on the wrong event while the card
    # compiles supported.
    ("created_token_leaves_battlefield",
     r"when the token leaves(?: the battlefield)?"),
    # "When enchanted creature leaves the battlefield, its controller
    # sacrifices a creature of their choice." (Funeral March.) CR 603.6c's
    # event asked about the permanent this one is *attached to* —
    # `attached_creature_dies` below widened from a death to any move off the
    # battlefield, so an exiled, bounced or tucked host fires it too.
    #
    # Above the generic row and deliberately not folded into it, exactly as
    # `created_token_leaves_battlefield` is: that row's `.+` swallows
    # "enchanted creature" and reports the ability as watching the **Aura**, so
    # the card would compile supported and fire when the Aura itself left. That
    # is idiom 1 in its purest form — a condition narrowed on the grammar side
    # alone, with this table quietly naming a different event.
    ("attached_creature_leaves_battlefield",
     r"when(?:ever)? (?:equipped|enchanted) creature leaves(?: the battlefield)?"),
    ("leaves_battlefield",          r"when (?:this|.+) leaves(?: the battlefield)?"),
    # "**When you lose control of this artifact**, put all cards exiled with
    # this artifact into their owner's graveyard." (Gustha's Scepter.) A CR
    # 603.10d event — it looks back in time, so the ability exists to trigger
    # even though the permanent is already gone by the time anyone asks. Its
    # own kind rather than a spelling of `leaves_battlefield`: a control change
    # is not a zone change (the permanent is still on the battlefield, under
    # somebody else), and every other card in the pool that prints these words
    # prints them as a *rider* on its own control-gaining sentence, which the
    # rider parser reads and this row must not claim.
    ("lose_control_of_source",      r"when you lose control of (?:this|it|the) ?.*"),
    ("attached_creature_dies",      r"when(?:ever)? (?:equipped|enchanted) creature dies"),
    # CR 701.26a's event with the one-shot trigger word (Blight: "**When**
    # enchanted land becomes tapped, destroy it"). Here for the reason
    # `attached_creature_dies` above is in both tables: which word a card
    # printed is not a difference the dispatcher can act on, and a table holding
    # only one of them leaves the other's cards refusing a condition the engine
    # implements. The *self* spelling has no row here — a permanent becoming
    # tapped is a repeatable event, so every printing of that one says
    # "whenever", the same argument the `you_gain_life` note below makes.
    ("permanent_becomes_tapped",
     r"when(?:ever)? enchanted (?P<tapped_attached>[a-z]+) becomes tapped"),
    # A row per event the "whenever" table already names used to live here —
    # "when this creature blocks" (Elder Land Wurm). It is gone, and so is the
    # whole idea of copying rows between the tables: `_parse_trigger_condition`
    # now falls back to the whenever table for any "when" line this one misses,
    # so **every** event is readable under both printed words. The hand-copied
    # subset was why Time Elemental's "when this creature attacks or blocks" —
    # a condition already in the whenever table, already dispatched — refused.
    ("dies",                        r"when (?:this creature|.+) dies"),
    # "you_gain_life" was here, spelled "when you gain life", with no dispatcher
    # and no card: a life gain is a repeatable event, so every printing of it is
    # "**Whenever** you gain life" — the row above in the whenever table, which
    # Vito reaches. A kind lives in one table, because the shadowing guard's
    # canonical examples are keyed by kind and an example can only be a wording
    # of one trigger word.
    # "becomes_target" was here, spelled "when (?:this|.+) becomes the target",
    # with no dispatcher and — until Mirage — no card. Skulking Ghost prints the
    # "when" wording ("When this creature becomes the target of a spell or
    # ability, sacrifice it"), which this row swallowed into a kind nothing
    # announces: the card compiled supported and never sacrificed itself.
    # CR 603.1 makes the two trigger words one ability, so the row is gone and
    # the "when" fallback carries the line to `self_becomes_target` in the
    # whenever table, which has the filter and the fire site
    # (`_announce_target_triggers`). Same fix, and the same reason, as the
    # `you_gain_life` row above.
    # "When you remove the last intervention counter from this enchantment, …"
    # (Divine Intervention.) The counter word is payload, like the threshold
    # trigger above it. Announced from the same state-based sweep and for the
    # same reason the draw triggers are: removal has four call sites, so the
    # record `named_counters.remove_counters` writes is what the sweep reads.
    ("last_counter_removed",
     r"when you remove the last (?P<counter_kind>[a-z]+) counter from this "
     r"(?:artifact|aura|creature|enchantment|permanent|land)"),
    # "When the last ore counter **is removed** from this Aura, …" (Orcish
    # Mine.) The same event in the passive voice, and it has to be the same
    # kind: CR 121.3's removal is one event however it happened, and the
    # dispatcher behind it (`mixins/game_ending.py`) reads the record
    # `named_counters.remove_counters` writes rather than any call site — which
    # is exactly why the printed voice cannot matter. Orcish Mine's counters
    # come off through its *own* trigger, so an active-voice-only table would
    # have left the card's whole payoff unreadable.
    ("last_counter_removed",
     r"when the last (?P<counter_kind>[a-z]+) counter is removed from this "
     r"(?:artifact|aura|creature|enchantment|permanent|land)"),
    # "When a spell or ability an opponent controls causes you to discard this
    # card, …" (Psychic Purge.) CR 113.6: an ability that functions from the
    # hand. The one discard seam (`Game._discard_card`) is what announces it,
    # and CR 109.5's "an opponent" is read off the seat resolving the spell or
    # ability that caused the discard.
    # "When **you cast this spell**, counter it unless you sacrifice a land."
    # (Mana Vortex.) CR 603.6d: an ability that triggers on its own object
    # being cast, so it functions from the stack rather than from the
    # battlefield the permanent has not reached yet (CR 113.6a). The cast
    # path is what announces it, over the card it is casting.
    ("self_cast",                   r"when you cast this spell"),
    ("discarded_by_opponent_effect",
     r"when a spell or ability an opponent controls causes you to discard this card"),
    # "When you control **no Islands** / **no Forests**, sacrifice this
    # creature." (Sea Serpent, Island Fish Jasconius; Gorilla Pack in Ice Age.)
    # The negative twin of `controls_matching_permanent` below, with the noun
    # delimited and read by the noun parser. It was a ``no_islands`` kind with
    # the land type welded into the name — the shape idiom 19 exists to
    # prevent — so Gorilla Pack, printing the identical sentence about Forests,
    # was a card the engine could not read.
    #
    # Ordered before the positive row for the reason that one documents in
    # reverse: "no <noun>" is not an "an? " phrase and the two cannot collide,
    # and the specific-before-generic rule holds anyway.
    ("controls_no_matching",
     r"when you control no (?P<controlled_subjects>[^,]+)"),
    # "When there are **no lands on the battlefield**, sacrifice this
    # enchantment." (Mana Vortex.) The same state trigger (CR 603.8) asked
    # about every battlefield rather than the source controller's — a
    # different set, so a different kind: a Mana Vortex whose controller has
    # no land is not sacrificed while an opponent still has one.
    ("no_lands_anywhere",           r"when there are no lands on the battlefield"),
    # "When you control a Dwarf, sacrifice this creature." (Goblins of the
    # Flarg.) A state trigger (CR 603.8) like the two above, and the *positive*
    # one: those fire while a described set is empty, this while it is not.
    # Ordered after them because "no islands" is not an `an? ` phrase and so
    # cannot reach this row — the ordering is the specific-before-generic rule
    # holding even where the two cannot currently collide.
    #
    # The noun phrase is delimited, not described: the group is read by the noun
    # parser and refused if `subject_matches` cannot test it, so a card printing
    # any other tribe is the same trigger with different payload.
    ("controls_matching_permanent",
     r"when you control (?P<controlled_subject>an? [^,]+)"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    # "each player's upkeep" / "each upkeep" / "each **opponent's** upkeep"
    # (Psychic Allergy). One event asked of a narrower set of seats, so the
    # narrowing is *payload* and not a second kind — idiom 19: a condition kind
    # is a dispatcher's address, and spelling the subject into it gives one card
    # its own fire site. `phases/upkeep_step.py` reads `upkeep_scope` to decide
    # whether this firing is one the card names.
    ("upkeep_each",         r"at the beginning of each (?:(?P<upkeep_scope>opponent|player)'s )?upkeep"),
    # Cursed Land's "enchanted land's controller" is here too: the deal_damage
    # handler (phases/upkeep_effects.py) reads `attached_to` and does not care
    # what the enchanted permanent is, so a land Aura routes through it like the
    # creature/artifact/enchantment ones. The bespoke enchant-land pass that
    # used to deal it (and the double-fire that excluding `land` guarded against)
    # are both gone.
    ("upkeep_enchanted_controller", r"at the beginning of the upkeep of enchanted (?:creature|artifact|enchantment|land)'s controller"),
    # The same clause naming the **end step** instead (Aggression). A kind of
    # its own rather than a scope on the upkeep one, because the two are
    # dispatched by different steps — CR 513 and CR 502 — and a scope the end
    # step did not read would be an Aura firing at the wrong moment.
    ("end_step_enchanted_controller", r"at the beginning of the end step of enchanted (?:creature|artifact|enchantment|land)'s controller"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    # "Your draw step" is a scope narrowing and so its own kind, exactly as
    # upkeep_self is beside upkeep_each: it fires only on its controller's draw
    # step where the bare form fires on everyone's. Must precede nothing here
    # (neither is a prefix of the other), but it is listed first to match the
    # upkeep pair's order.
    ("draw_step_self",      r"at the beginning of your draw step"),
    # "each **opponent's** draw step" (Malignant Growth) beside "each
    # player's". One event asked of a narrower set of seats, so the narrowing
    # is *payload* and not a second kind — the same shape `upkeep_scope` above
    # takes, and for its reason (idiom 19): a condition kind is a dispatcher's
    # address, and spelling the subject into it gives one card its own fire
    # site. `phases/draw_step.py` reads `draw_step_scope` to decide whether this
    # firing is one the card names.
    ("draw_step_each",      r"at the beginning of each (?:(?P<draw_step_scope>opponent|player)'s )?draw step"),
    # "At the beginning of your first main phase" (the M21 Shrine cycle) —
    # CR 505.1a's precombat main phase, which is the only one that is "first".
    # Both printed spellings, because the modern templating says "precombat".
    ("main_phase_first",    r"at the beginning of your (?:first|precombat) main phase"),
    # "Your end step" is a *scope* narrowing, exactly like combat's below and
    # upkeep_self/upkeep_each above: it fires only on its controller's own end
    # step where the bare form fires on everyone's. A separate kind because the
    # dispatch is what reads the difference — with one kind,
    # engine/phases/end_step.py had to infer a scope per instruction kind, and
    # the gated scan inferred "your" for every card that reached it.
    # Must precede its own prefix, per the ordering rule.
    ("end_step_self",       r"at the beginning of your end(?: step)?"),
    # "each **player's** end step" (Monsoon) names the same set as the bare
    # "each end step": CR 513.1 gives every turn exactly one end step, so every
    # end step is some player's. So it is a spelling and not a scope — unlike
    # upkeep_each's `upkeep_scope`, which exists because "each **opponent's**
    # upkeep" really is a narrower set and the dispatcher enforces it. A card
    # printing "each opponent's end step" refuses here rather than being
    # admitted with the narrowing dropped.
    ("end_step",            r"at the beginning of (?:the |each )?(?:player's )?end(?: step)?"),
    # "…of combat on your turn" narrows the bare form to the active player's
    # combat (Adherent of Hope); must precede its own prefix below.
    ("combat_your_turn",    r"at the beginning of combat on your turn"),
    # "At the beginning of **each** combat" (Goblin Flotilla). The same event
    # as the bare spelling below it and the same kind: CR 506.1 gives a turn one
    # combat phase per combat, and the fire site announces every one of them —
    # so "each" states what the bare wording already means rather than narrowing
    # it. Above the bare row, which is not its prefix but which the
    # specific-before-generic rule keeps it above anyway.
    ("combat",              r"at the beginning of each combat"),
    ("combat",              r"at the beginning of combat"),
    # "At end of combat, …" (The Wretched) — CR 511.1, the end of combat step.
    # Clockwork Beast's line opens the same way and stays a static line: its
    # effect clause compiles no instruction, so the classifier's static
    # fallback (step 2 of _parse_creature_program) keeps it where
    # phases/end_of_combat_step.py's text probe reads it.
    ("end_of_combat",       r"at end of combat"),
)

# "if" conditions that can appear mid-effect
IF_CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("artifact_untapped",       r"if this artifact is untapped"),
    # The same clause the other way round (Mana Vault's draw-step damage). Both
    # halves are listed because a table holding only one of a pair is how a gate
    # nothing can fail gets written.
    ("artifact_tapped",         r"if this artifact is tapped"),
    ("creature_died_this_turn", r"if a creature died this turn"),
    ("no_creatures_in_hand",    r"if you have no creatures in hand"),
    ("paid_mana",               r"if you paid? .+"),
    ("controls_island",         r"if (?:you |defending player )?controls? an? island"),
    ("controls_swamp",          r"if (?:you |defending player )?controls? an? swamp"),
    ("is_untapped",             r"if (?:this|it) is untapped"),
    ("not_playing_for_ante",    r"if you're not playing for ante"),
)


def _compile_trigger_patterns(
    patterns: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((kind, re.compile(pattern)) for kind, pattern in patterns)


# Precompiled once at import. Python's internal regex cache holds only 512
# entries, so relying on it would thrash as the pattern tables grow.
_COMPILED_WHENEVER_PATTERNS = _compile_trigger_patterns(WHENEVER_TRIGGER_PATTERNS)
_COMPILED_WHEN_PATTERNS = _compile_trigger_patterns(WHEN_TRIGGER_PATTERNS)
_COMPILED_AT_PATTERNS = _compile_trigger_patterns(AT_TRIGGER_PATTERNS)
_COMPILED_IF_PATTERNS = _compile_trigger_patterns(IF_CONDITION_PATTERNS)


class OracleLexer:
    _TOKEN_RE = re.compile(r"\{[^}]+\}|[A-Za-z']+|\d+|\n|[:.,;+/\-]")

    def tokenize(self, oracle_text: str) -> tuple[OracleToken, ...]:
        if not oracle_text:
            return ()

        tokens: list[OracleToken] = []
        for raw in self._TOKEN_RE.findall(oracle_text):
            if raw == "\n":
                tokens.append(OracleToken("newline", raw))
                continue
            if raw.startswith("{") and raw.endswith("}"):
                tokens.append(OracleToken("mana", raw.upper()))
                continue
            if raw.isdigit():
                tokens.append(OracleToken("number", raw))
                continue
            if raw == ":":
                tokens.append(OracleToken("colon", raw))
                continue
            if raw in {".", ",", ";", "+", "/", "-"}:
                tokens.append(OracleToken("symbol", raw))
                continue
            tokens.append(OracleToken("word", raw.lower()))
        return tuple(tokens)


_LEXER = OracleLexer()


def lex_oracle_text(oracle_text: str) -> tuple[OracleToken, ...]:
    return _LEXER.tokenize(oracle_text)


_WHITESPACE_RE = re.compile(r"\s+")
_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")


def _normalize_text(oracle_text: str) -> str:
    return _WHITESPACE_RE.sub(" ", oracle_text.strip().lower())


def normalize_creature_line(line: str) -> str:
    lowered = strip_ability_word(line).lower()
    lowered = _PARENTHETICAL_RE.sub("", lowered)
    lowered = lowered.replace(";", ",")
    lowered = _WHITESPACE_RE.sub(" ", lowered).strip(" .,")
    return lowered


# CR 606.2: a loyalty ability's cost is a loyalty symbol — "+1", "−2", "0",
# "−X". Scryfall prints the minus as U+2212; an ASCII hyphen is accepted too so
# hand-written fixtures behave like ingested text.
_LOYALTY_COST_RE = re.compile(r"^\s*([+\-−]?)\s*(\d+|[xX])\s*$")


def _parse_loyalty_cost(cost_part: str) -> tuple[int | None, int | None]:
    """The ``(loyalty, loyalty_x_sign)`` a cost clause spells, or ``(None, None)``.

    Matches only when the whole clause is one loyalty symbol: a planeswalker's
    cost clause is nothing else (CR 606.5 combines multiples, and no card in the
    pool prints a combined form), and anything wider must keep reading as the
    mana/prose cost it is.
    """
    match = _LOYALTY_COST_RE.match(cost_part)
    if match is None:
        return None, None
    sign = -1 if match.group(1) in ("-", "−") else 1
    magnitude = match.group(2)
    if magnitude in ("x", "X"):
        return None, sign
    return sign * int(magnitude), None


def _chargeable_sacrifice_filter(phrase: str, *, plural: bool = False) -> dict | None:
    """The filter payload a "Sacrifice <noun phrase>" cost charges, or None when
    the payment path cannot collect it.

    The two halves of a sacrifice cost — this reader, which charges it, and
    ``engine/grammar``'s ``_is_chargeable_sacrifice``, which decides whether to
    admit the line at all — must give the same answer or the pool grows a card
    the grammar accepted and nothing paid for. They give it by asking the same
    function: the noun parser for what the phrase names, and
    ``object_only_filter`` for whether the charger can test it. ``exclude_self``
    ("another") stays in the payload here, because the charger has the ability's
    source and compares by identity.
    """
    from .grammar import subject_filter_payload
    from .subject_filters import object_only_filter

    # *plural* is the "any number of **creatures you control**" tail (Sword of
    # the Ages): the count is printed in front of the phrase, so what is left is
    # a bare plural rather than the singular every other sacrifice cost names.
    # The grammar's cost side reads the same shape through ``bare_plural``, and
    # both are gated identically — the count changes how many are charged, never
    # what may pay.
    described = subject_filter_payload(phrase, plural=plural)
    if described is None:
        return None
    return chargeable_sacrifice_payload(described)


def _chargeable_counter_target(phrase: str) -> dict | None:
    """The filter payload a "put a counter on <noun phrase>" cost charges, or
    None when the payment path cannot find the permanent.

    The charging half of ``grammar/costs._is_chargeable_counter_target``, and
    the two agree by asking the same two functions the sacrifice pair asks —
    the noun parser for what the phrase names, and the charger's own reduction
    for whether it can be tested. A phrase one admitted and the other refused
    would be an ability the grammar let through and nothing charged, which is
    an ability activated for free.

    The reduction is the *sacrifice* one because the question is identical: the
    candidates come off the payer's own battlefield and are tested with
    ``subject_matches``. Only the verb differs, and a verb is not a filter.
    """
    from .grammar import subject_filter_payload

    described = subject_filter_payload(phrase)
    if described is None:
        return None
    return chargeable_sacrifice_payload(described)


def chargeable_sacrifice_payload(described: dict) -> dict | None:
    """The charger's reading of an already-parsed noun-phrase payload.

    Split out of :func:`_chargeable_sacrifice_filter` so the pool-wide guard in
    ``tests/engine/test_activation_costs.py`` can ask the same question of the
    grammar's own filter instead of re-deriving it. That guard compares what the
    grammar admitted against what this charges, and comparing a *raw* phrase
    payload against a reduced one reports a difference for every key the
    reduction legitimately drops — which is how "creatures **you control**"
    (Sword of the Ages) read as a dropped rider.

    Two keys are dropped rather than carried, and neither is a narrowing lost.
    ``controller`` is one: every path that charges a sacrifice enumerates the
    payer's own battlefield first, so "you control" restricts nothing the
    enumeration has not already done — but ``permanent_matches_filter`` has no
    observer, so a key left in would be handed over and refuse every candidate.
    ``exclude_self`` is the other, and it comes back on: the charger holds the
    ability's source and compares by identity.
    """
    from .subject_filters import object_only_filter

    carried = object_only_filter(
        described, carried_separately=frozenset({"exclude_self", "controller"})
    )
    if carried is None:
        return None
    if "exclude_self" in described:
        carried = {**carried, "exclude_self": True}
    return carried


def chargeable_exile_payload(described: dict) -> dict | None:
    """The charger's reading of an "Exile <noun phrase>" cost's noun payload.

    :func:`chargeable_sacrifice_payload` one zone wider, and shaped the same way
    for the same reason: the grammar admits the line by asking this, the
    activation path charges the cost by asking this, and the pool-wide guard in
    ``tests/engine/test_activation_costs.py`` compares the two answers.

    ``zone`` and ``zone_owner`` are dropped rather than carried - the charger
    enumerates one named zone of one named seat, so they restrict nothing the
    enumeration has not already done, and a key handed to a matcher that cannot
    test it would refuse every candidate. ``controller`` goes the same way and
    for the reason a sacrifice's does; ``exclude_self`` comes back on, because
    the charger holds the source and compares by identity.
    """
    from .subject_filters import card_only_filter, object_only_filter

    zone = described.get("zone")
    stripped = {
        key: value for key, value in described.items()
        if key not in ("zone", "zone_owner")
    }
    if zone in ("graveyard", "hand"):
        # A card in a zone has no computed characteristics (CR 613.1), so the
        # card matcher is what answers here - the same split
        # ``chargeable_card_filter`` makes for a discard cost, and a hand is
        # the zone that discard already reads.
        return card_only_filter(stripped)
    carried = object_only_filter(
        stripped, carried_separately=frozenset({"exclude_self", "controller"})
    )
    if carried is None:
        return None
    if "exclude_self" in stripped:
        carried = {**carried, "exclude_self": True}
    return carried


def _chargeable_exile_filter(phrase: str, *, plural: bool = False) -> dict | None:
    """The filter payload an "Exile <noun phrase>" cost charges, or None when the
    payment path cannot collect it. The two-halves pairing
    :func:`_chargeable_sacrifice_filter` describes, one zone wider."""
    from .grammar.phrases import parse_subject_filter

    # The noun parser directly rather than ``subject_filter_payload``: that
    # reader refuses any phrase naming a zone at all, because a *trigger*
    # subject is always a permanent - and "a creature card **from your
    # graveyard**" is exactly the shape it exists to refuse. The zone is the
    # point here, so the gate is ``chargeable_exile_payload`` alone, which is
    # also the function the grammar's own cost side asks (idiom 1).
    filt = parse_subject_filter(phrase, plural=plural)
    if filt is None:
        return None
    return chargeable_exile_payload(filt.to_payload())


def _chargeable_discard_filters(phrase: str) -> tuple[dict, ...] | None:
    """The alternatives a "Discard <noun phrase>" cost may be paid with, or None
    when the payment path cannot collect it.

    The card twin of :func:`_chargeable_sacrifice_filter`, in the same
    two-halves arrangement and for the same reason: this reader charges the
    cost, ``engine/grammar``'s ``_parse_discard_cost_alternatives`` decides
    whether to admit the line at all, and they cannot disagree because both ask
    ``chargeable_card_filter`` what the phrase names.

    An empty tuple is the unrestricted "Discard a card" — a real answer, not a
    refusal — which is why None is the refusal and why the caller reads the
    *count* off this rather than off a second regex of its own.

    **The whole phrase is offered to the noun parser before the "or" is split
    on**, and that ordering is load-bearing: Magic prints two different
    disjunctions with one word. "A land card **or** Shrine card" is two noun
    phrases, each with its own head, and only the split reads it; "a red **or**
    green card" is *one* noun phrase with two colour adjectives sharing a head,
    which the noun parser reads on its own and the split shreds into "a red"
    (nothing) and "green card". Splitting first therefore refused the second
    shape outright — and a refused cost clause is a cost the card prints and
    nothing charges.
    """
    from .grammar import card_filter_payload

    whole = card_filter_payload(phrase)
    if whole is not None:
        return (whole,) if whole else ()
    alternatives: list[dict] = []
    for side in phrase.split(" or "):
        described = card_filter_payload(side)
        if described is None:
            return None
        if described:
            alternatives.append(described)
    return tuple(alternatives)


_TAP_COST_RE = re.compile(r"\btap (\w+) ([^,:]+?)\s*(?=,|$)")


def _chargeable_tap_cost(cost_lower: str) -> tuple[int, dict] | None:
    """The ``(count, filter)`` a "Tap N <noun phrase>" cost charges, or None.

    The regex only **delimits** the number and the noun phrase, to the end of
    its comma-separated cost segment; ``_NUMBER_WORDS`` reads the one and the
    noun parser the other — the split every other prose cost in this file makes,
    and for the same reason: a regex approximating the noun parser is a second
    reader of one clause, and the direction those drift in is a cost charged
    more widely than the card prints.
    """
    from .grammar import subject_filter_payload
    from .grammar.lowering._common import chargeable_tap_filter
    from .grammar.phrases import parse_subject_filter

    match = _TAP_COST_RE.search(cost_lower)
    if match is None:
        return None
    word = match.group(1)
    count = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
    if count <= 0:
        return None
    filt = parse_subject_filter(match.group(2), plural=True)
    if filt is None:
        return None
    described = chargeable_tap_filter(filt)
    if described is None:
        return None
    return count, described


#: "**Return a Forest you control to its owner's hand**" (Quirion Ranger),
#: "**Return two Islands you control to their owner's hand**" (Flooded
#: Shoreline). One comma-separated cost segment, delimiting only: the number is
#: read by ``_NUMBER_WORDS`` and the noun phrase by the noun parser, which is
#: the split :func:`_chargeable_tap_cost` makes above and for its reason — a
#: regex approximating the noun parser is a second reader of one clause, and
#: the direction the two drift in is a cost charged more widely than the card
#: prints.
#:
#: The possessive is part of the pattern rather than trailing slack: "to its
#: owner's hand" and "to their owner's hand" are English inflection over one
#: destination, and any *other* destination is a different cost this cannot
#: charge.
_RETURN_TO_HAND_COST_RE = re.compile(
    r"\breturn (\w+) (.+?) to (?:its|their) owner's hand\s*(?=,|$)"
)


def _chargeable_return_to_hand_cost(cost_lower: str) -> tuple[int, dict] | None:
    """The ``(count, filter)`` a "Return N <noun phrase> to its owner's hand"
    cost charges, or None.

    Gated on what ``subject_filters.subject_matches`` can test, because that is
    what the charger enumerates with: a phrase reaching past it would be
    *dropped* by the matcher rather than refused, and the cost would then be
    payable off a wider set of permanents than the card names.

    The self-return ("Return **this creature** to its owner's hand",
    Ovinomancer) is ``return_self_to_hand``'s and never reaches here: its noun
    phrase is a self-reference, which the subject parser has no filter for, so
    the two readers of this printed clause cannot both claim one segment.
    """
    from .grammar.lowering._common import chargeable_tap_filter
    from .grammar.phrases import parse_subject_filter

    match = _RETURN_TO_HAND_COST_RE.search(cost_lower)
    if match is None:
        return None
    word = match.group(1)
    count = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
    if count <= 0:
        return None
    # ``plural=True`` whatever the printed count, exactly as the tap cost
    # above: the counted position is the one the noun parser wants told
    # about, and the number is read here rather than by it.
    filt = parse_subject_filter(match.group(2), plural=True)
    if filt is None:
        return None
    # The same gate the tap cost uses, which is what keeps the two chosen-cost
    # readers agreeing about which noun phrases are chargeable at all: it
    # answers None for anything ``subject_matches`` cannot test, and the
    # charger enumerates with exactly that predicate.
    described = chargeable_tap_filter(filt)
    if described is None:
        return None
    # "**you control**" is the seat the charger draws from, and the charger
    # draws from the activating player's own battlefield — so the clause is
    # honoured there and must not also ride the filter, where a second reader
    # would be free to disagree with it. A phrase naming *another* seat is a
    # cost this cannot charge and refuses outright.
    if filt.controller not in (None, "you"):
        return None
    return count, described


#: "**Untap a tapped land an opponent controls**" (Benthic Explorers). One
#: comma-separated cost segment, whole, and delimiting only — what the noun
#: phrase names is read by the noun parser below, which is the split
#: :func:`_chargeable_tap_cost` makes above and for its reason: a regex
#: approximating the noun parser is a second reader of one clause, and the
#: direction the two drift in is a cost charged more widely than the card
#: prints.
_UNTAP_COST_RE = re.compile(r"^untap (an? .+)$")


def _chargeable_untap_cost(cost_lower: str) -> dict | None:
    """The filter an "Untap a <noun phrase>" cost charges, or None.

    Gated on what ``subject_filters.subject_matches`` can test, because that is
    what the charger enumerates with: a phrase reaching past it would be
    *dropped* by the matcher rather than refused, and the cost would then be
    payable off a wider set of permanents than the card names.

    The "tapped" half of the phrase is required by the grammar's own production
    and re-read here rather than assumed — untapping an untapped permanent is
    no payment, and the two readers of this clause have to agree about that as
    much as about the noun.
    """
    from .grammar.phrases import parse_subject_filter
    from .subject_filters import untestable_filter_keys

    for segment in cost_lower.split(","):
        match = _UNTAP_COST_RE.match(segment.strip())
        if match is None:
            continue
        filt = parse_subject_filter(match.group(1))
        if filt is None or filt.tapped is not True:
            return None
        described = filt.to_payload()
        if untestable_filter_keys(described):
            return None
        return described
    return None


#: "**Tap enchanted land**: Target blocking creature gets +1/+2 until end of
#: turn." (Earthlore.) One comma-separated cost segment, whole — anchored for
#: the reason every pattern in `activation_restrictions.py` is: a rule matching
#: a prefix would charge a *narrower* cost than the card prints.
_TAP_ATTACHED_COST_RE = re.compile(r"^tap (?:enchanted|equipped) \w+$")


def _taps_the_attached_permanent(cost_lower: str) -> bool:
    """Whether a cost clause taps the permanent this Aura or Equipment is on.

    The payment is the *host*, which `{T}` cannot say: that symbol taps the
    permanent the ability is printed on, and here the ability is printed on the
    attachment. A pre-symbol templating of the same payment, so nothing else
    can pay it — there is no picker and no filter, only the attachment record.

    CR 301.5f puts "equipped" and "enchanted" on the same footing, so both
    words are read: an Equipment printing the clause charges the same cost.
    """
    return any(
        _TAP_ATTACHED_COST_RE.match(segment.strip())
        for segment in cost_lower.split(",")
    )


#: "Pay enchanted creature's mana cost" (Merseine). Anchored per cost segment
#: for :data:`_TAP_ATTACHED_COST_RE`'s reason: a rule matching a prefix would
#: charge a *narrower* cost than the card prints. The apostrophe is admitted in
#: both spellings, straight and curly, because the two readers of this clause —
#: this one and the grammar's, which sees a lexed ``'s`` token — must agree
#: about the same printed line.
_PAY_ATTACHED_MANA_COST_RE = re.compile(
    r"^pay (?:enchanted|equipped) \w+['’]s mana cost$"
)


def _pays_the_attached_permanents_mana_cost(cost_lower: str) -> bool:
    """Whether a cost clause spends the mana cost of the permanent this Aura or
    Equipment is on.

    :func:`_taps_the_attached_permanent` one payment over, and the same shape:
    the payment is the *host's*, nothing is picked, and the attachment record
    is the whole answer. What differs is that this one can be **unpayable** —
    the activator has to produce the mana — so the activation path builds the
    symbols from the host rather than reading a fixed dict.

    CR 301.5f puts "equipped" and "enchanted" on the same footing, so both
    words are read.
    """
    return any(
        _PAY_ATTACHED_MANA_COST_RE.match(segment.strip())
        for segment in cost_lower.split(",")
    )


def _life_payment_cost(cost_lower: str) -> int:
    """The life a "Pay N life" activation cost charges, or 0 for no such cost.

    The regex only **delimits** the number; ``_NUMBER_WORDS`` and ``int`` read
    it — the same split round 34 drew for a narrowed trigger's noun phrase and
    round 56 for a sacrifice cost's, and for the same reason: a second reader
    approximating the first drifts, and the direction a cost drifts in is a cost
    nobody pays. The grammar admits only a fixed positive amount, and
    ``tests/engine/test_activation_costs.py`` compares the two over the whole
    pool, so a clause the grammar admitted and this read as 0 fails there rather
    than shipping a free ability.
    """
    match = re.search(r"\bpay (\w+) life\b", cost_lower)
    if match is None:
        return 0
    word = match.group(1)
    return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)


def _life_payment_per_counter(cost_lower: str) -> str | None:
    """The counter kind a "Pay N life **for each <kind> counter on this
    <noun>**" cost multiplies by, or None when the payment is a flat amount.

    Beside :func:`_life_payment_cost` rather than folded into it because the
    two answer different questions — how much per unit, and how many units —
    and the grammar carries them as two fields for the same reason. Only the
    ability's own source is read ("on **this** <noun>"), which is the one
    permanent a cost charger has in hand.
    """
    match = re.search(
        r"\bpay \w+ life for each ([a-z+/0-9-]+) counters? on this [a-z]+\b",
        cost_lower,
    )
    return match.group(1) if match is not None else None


def activation_colon_index(line: str) -> int | None:
    """The index of the colon that separates an activated ability's cost from
    its effect — or None when the line has none.

    **A colon inside quotation marks is not one.** An Aura that grants an
    ability writes the whole ability inside quotes ("Enchanted land has \"{T}:
    Counter target spell …\"", Equinox), and that colon belongs to the granted
    ability rather than to any ability of the Aura. Split on it, the Aura reads
    as a permanent with a {T} cost and an effect of "counter target spell" —
    which is how Equinox reported an activated ability that compiled to nothing
    while its printed static line, which ``engine/auras.py`` implements in full,
    was never classified as one.

    The grammar's parser has had this rule since it learned to read a granted
    ability (``parser._split_on_colon`` over the tokens before the first
    quote); this is that rule on the string the compiler's line classifier
    reads, so the two front ends agree about where an ability begins.
    """
    in_quotes = False
    for index, character in enumerate(line):
        if character == '"':
            in_quotes = not in_quotes
        elif character == ":" and not in_quotes:
            return index
    return None


_MANA_ALTERNATIVE_RE = re.compile(
    r"\bpay \w+ life\b[^,:]*?\s+or\s+((?:\{[^}]+\})+)\s*$", re.IGNORECASE
)


def _split_mana_alternative(cost_part: str) -> tuple[str, dict[str, int] | None]:
    """*cost_part* with a trailing "… or {N}" removed, and the mana it named.

    "Pay 2 life **or {2}**" (Tidal Control) is one cost with a choice, and the
    two halves have to be told apart before anything reads either: the mana scan
    is a findall over the whole clause, so an alternative left in becomes part of
    ``required`` and the ability charges the life **and** the mana.

    Anchored to the end of the clause and to a preceding life payment, which is
    the only printed shape — a bare "or" elsewhere in a cost clause is not this,
    and returning the clause unchanged leaves whatever reads it next to refuse.
    """
    match = _MANA_ALTERNATIVE_RE.search(cost_part)
    if match is None:
        return cost_part, None
    alternative: dict[str, int] = {}
    for token in _MANA_TOKEN_RE.findall(match.group(1).upper()):
        if token.isdigit():
            alternative["generic"] = alternative.get("generic", 0) + int(token)
        elif token in {"W", "U", "B", "R", "G", "C"}:
            alternative[token] = alternative.get(token, 0) + 1
        else:
            # A symbol this cannot price ({X}, {T} inside the alternative) —
            # leave the clause whole so the ability refuses rather than being
            # charged a cost nobody can pay.
            return cost_part, None
    if not alternative:
        return cost_part, None
    return cost_part[: match.start(1)].rstrip()[: -len("or")].rstrip(), alternative


def parse_activated_ability_cost(line: str) -> ActivatedAbilityCost:
    required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    requires_tap = False
    colon = activation_colon_index(line or "")
    if colon is None:
        return ActivatedAbilityCost(required, requires_tap)

    cost_part = line[:colon]
    # "Pay 2 life **or {2}**" (Tidal Control). CR 601.2h's choice between two
    # printed payments, split off the clause *before* the mana scan below — a
    # scan that read the whole clause would put the alternative into `required`
    # beside the life and charge both halves of an "or", which is exactly what
    # this reader did until the split existed.
    cost_part, alternative_mana = _split_mana_alternative(cost_part)
    loyalty, loyalty_x_sign = _parse_loyalty_cost(cost_part)
    if loyalty is not None or loyalty_x_sign is not None:
        # A loyalty symbol is the whole cost (CR 606.4); reading the clause
        # again as prose would misread "+1" as a bare number and charge nothing.
        return ActivatedAbilityCost(
            required, False, loyalty=loyalty, loyalty_x_sign=loyalty_x_sign
        )
    for token in _MANA_TOKEN_RE.findall(cost_part.upper()):
        if token == "T":
            requires_tap = True
            continue
        if token.isdigit():
            required["generic"] += int(token)
            continue
        if token in {"W", "U", "B", "R", "G", "C"}:
            required[token] += 1
    # Non-mana additional costs written as prose in the cost clause. Only the
    # clause left of the ":" counts — "Draw a card" as an effect must not be read
    # as a cost.
    cost_lower = cost_part.lower()
    discard_last_drawn = "discard the last card you drew this turn" in cost_lower
    exile_self = bool(re.search(r"\bexile this (artifact|creature|enchantment|permanent|land)\b", cost_lower))
    # "Exile a creature you control" (City of Shadows) / "Exile a creature
    # card from your graveyard" (Necropolis) - a *chosen* object rather than
    # the source. The regex only **delimits** the noun phrase to the end of
    # its comma-separated cost segment, exactly as the sacrifice one below
    # does; what the phrase names is read by the noun parser, because a regex
    # approximating it is a second reader of one clause and the direction
    # those drift in is a cost charged more widely than the card prints.
    # "Exile **the top card of your library**" / "…the top **two** cards…"
    # (Royal Herbalist, Whirling Catapult, Phyrexian Devourer). The one exile
    # cost whose tail is not a noun phrase — the cards are named by position —
    # so it is read here rather than handed to the noun parser, and read
    # *before* the chosen-object patterns below, which would otherwise find
    # nothing at all and charge the cost as none.
    #
    # The count is delimited by the regex and read by ``_NUMBER_WORDS``, the
    # split every other counted clause in this file makes. A word that is not a
    # number leaves the cost unread, which keeps this reader and the grammar's
    # (``grammar/costs._accept_exile_top_of_library``, which admits only a fixed
    # positive count) admitting exactly the same clauses.
    exile_top_of_library = 0
    top_exile = re.search(
        r"\bexile the top (?:(\w+) cards|card) of your library\b", cost_lower
    )
    if top_exile is not None:
        word = top_exile.group(1)
        if word is None:
            exile_top_of_library = 1
        else:
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            exile_top_of_library = number if number >= 2 else 0
    chosen_exile = (
        None if exile_self or exile_top_of_library
        else re.search(r"\bexile ((?:another|an?) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    exile_filter = (
        _chargeable_exile_filter(chosen_exile.group(1)) if chosen_exile else None
    )
    # Which zone it comes out of. Read off the same phrase rather than
    # guessed: a graveyard payment enumerates cards and a battlefield one
    # enumerates permanents, and answering the wrong one exiles nothing while
    # the ability still resolves.
    # "…**from your hand**" (Cadaverous Bloom) is the third zone, read off the
    # same phrase for the same reason the graveyard is: a hand payment
    # enumerates cards the payer holds, and answering "battlefield" would look
    # for a permanent that is not there and charge nothing while the ability
    # still resolved.
    exile_zone = "battlefield"
    if chosen_exile is not None:
        phrase = chosen_exile.group(1)
        if "from your graveyard" in phrase:
            exile_zone = "graveyard"
        elif "from your hand" in phrase:
            exile_zone = "hand"
    exile_zone_owner: str | None = "you"
    exile_count = 1
    exile_same_zone = False
    # "Exile **two** creature cards **from a single graveyard**" (Night Soil).
    # The counted twin of the singular above, and the sacrifice's twin one zone
    # over: "an?" cannot match "two", so the singular pattern found nothing at
    # all and the cost was charged as none.
    #
    # "a single graveyard" is two facts in three words — the pile may be
    # anybody's, and every card must come out of the same one. The first is
    # rewritten to the phrase the noun parser already reads ("a graveyard") so
    # there is one reader of a zone tail; the second has no filter to live on
    # and is recorded beside the count.
    if exile_filter is None and not exile_self and not exile_top_of_library:
        counted_exile = re.search(
            r"\bexile (\w+) ([^,:]+?)\s*(?=,|$)", cost_lower
        )
        if counted_exile is not None:
            word = counted_exile.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            phrase = counted_exile.group(2)
            if number >= 2:
                if "from a single graveyard" in phrase:
                    phrase = phrase.replace(
                        "from a single graveyard", "from a graveyard"
                    )
                    exile_same_zone = True
                narrowed = _chargeable_exile_filter(phrase, plural=True)
                if narrowed is not None:
                    exile_filter = narrowed
                    exile_count = number
                    if "graveyard" in phrase:
                        exile_zone = "graveyard"
                        exile_zone_owner = (
                            "you" if "from your graveyard" in phrase else None
                        )
    # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman). Older
    # printings name the card instead of saying "this artifact", so accept
    # either wording.
    sacrifice_self = bool(
        re.search(
            r"\bsacrifice this (artifact|creature|enchantment|permanent|land|token)\b",
            cost_lower,
        )
    )
    # "Return this enchantment to its owner's hand" (Cycle of Life) — the same
    # shape one zone over, anchored the same way and admitting the same nouns,
    # because which word a card prints for its own type is not a difference the
    # cost has.
    return_self_to_hand = bool(
        re.search(
            r"\breturn this (artifact|creature|enchantment|permanent|land|token)"
            r" to its owner's hand\b",
            cost_lower,
        )
    )
    # "Sacrifice a creature" / "Sacrifice another creature" / "Sacrifice a
    # creature with defender" — a *chosen* permanent (Atog, Hobblefiend,
    # Portcullis Vine). The regex only **delimits** the noun phrase, to the end
    # of its comma-separated cost segment; what the phrase names is read by the
    # noun parser, exactly as a narrowed trigger condition's `_subject` group is
    # (round 34). A regex approximating the noun parser is a second reader of
    # one clause, and the direction those drift in is a cost charged more widely
    # than the card prints.
    # "Sacrifice **a creature named Feral Shadow, a creature named
    # Breathstealer, and this creature**" (Urborg Panther). An Oxford list of
    # objects under one printed verb, which the single-object delimiter below
    # cannot see at all: it stops at the first comma, so it read the Shadow,
    # missed the Breathstealer and missed the source — a cost charged as one
    # third of what the card prints, which is the direction that activates an
    # ability for less than it says.
    #
    # Found *before* that delimiter and consumed after it, so the two cannot
    # both claim the phrase. The whole match must end in "and <object>", which
    # is what keeps a comma separating two *costs* ("Sacrifice a creature, {T}:
    # …") from reading as a separator inside one. The grammar reads the same
    # shape (`costs._accept_sacrifice_list_tail`) and caps it at what these
    # three fields can hold, which is what keeps the two readers of this clause
    # from admitting different sentences.
    sacrifice_list = re.search(
        r"\bsacrifice ((?:(?:another|an?|this) [^,:]+, )+"
        r"and (?:another|an?|this) [^,:]+?)\s*(?=,|$)",
        cost_lower,
    )
    sacrifice_list_items = (
        [
            part.strip()
            for part in sacrifice_list.group(1).replace(", and ", ", ").split(", ")
            if part.strip()
        ]
        if sacrifice_list is not None
        else None
    )
    chosen_sacrifice = (
        None if sacrifice_self or sacrifice_list_items is not None
        else re.search(r"\bsacrifice ((?:another|an?) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    sacrifice_filter = (
        _chargeable_sacrifice_filter(chosen_sacrifice.group(1))
        if chosen_sacrifice
        else None
    )
    # "Sacrifice a creature **and a Swamp**" (Viscerid Drone). One printed verb
    # naming two different objects, which the delimiter above swallows whole —
    # and the noun parser then refuses "a creature and a swamp", so the cost was
    # charged as *none at all*. Split only after the whole phrase has been
    # tried, so every reading that worked before is byte-identical: a noun
    # phrase that legitimately contains "and" keeps it.
    sacrifice_also_filter = None
    if (
        sacrifice_filter is None
        and chosen_sacrifice is not None
        and " and " in chosen_sacrifice.group(1)
        and "any number of" not in chosen_sacrifice.group(1)
    ):
        first, _, second = chosen_sacrifice.group(1).partition(" and ")
        first_filter = _chargeable_sacrifice_filter(first.strip())
        second_filter = _chargeable_sacrifice_filter(second.strip())
        if first_filter is not None and second_filter is not None:
            sacrifice_filter = first_filter
            sacrifice_also_filter = second_filter
    if sacrifice_list_items is not None:
        # "…and **this creature**" is the source, which has its own flag and
        # no filter — the charger sacrifices the ability's own source rather
        # than picking a permanent that matches a phrase.
        chosen_items = [
            item for item in sacrifice_list_items if not item.startswith("this ")
        ]
        filters = [_chargeable_sacrifice_filter(item) for item in chosen_items]
        if len(chosen_items) <= 2 and all(f is not None for f in filters):
            sacrifice_self = sacrifice_self or len(chosen_items) < len(
                sacrifice_list_items
            )
            sacrifice_filter = filters[0] if filters else None
            sacrifice_also_filter = filters[1] if len(filters) > 1 else None
    # "Sacrifice this artifact **and any number of creatures you control**"
    # (Sword of the Ages). One printed cost naming two things: the source, read
    # above, and a *set* whose size the payer chooses. The same field carries
    # the noun phrase — it is the same question, "what may pay this?" — with
    # ``sacrifice_count`` saying how many, exactly as ``remove_counter_count``
    # does one cost up. Without this the tail matched nothing at all and the
    # ability sacrificed only itself, so its X was always zero.
    sacrifice_count: int | str = 1
    # "Sacrifice **two** Goblins" (Goblin Warrens). The count is printed in
    # front of the noun phrase, which leaves that phrase the bare plural
    # ``plural=True`` reads — the same split the "any number of" tail below
    # makes, with a number where that one has a choice. Read *before* the
    # singular match above could have run, which is why it is a separate regex
    # rather than a widening of it: "an?" cannot match "two", so the singular
    # pattern found nothing at all and the cost was charged as none.
    if sacrifice_filter is None and not sacrifice_self:
        counted = re.search(
            r"\bsacrifice (\w+) ([^,:]+?)\s*(?=,|$)", cost_lower
        )
        if counted is not None:
            word = counted.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            if number >= 2:
                narrowed = _chargeable_sacrifice_filter(
                    counted.group(2), plural=True
                )
                if narrowed is not None:
                    sacrifice_filter = narrowed
                    sacrifice_count = number
    any_number_sacrifice = re.search(
        r"\bsacrifice [^,:]*?\band any number of ([^,:]+?)\s*(?=,|$)", cost_lower
    )
    if sacrifice_filter is None and any_number_sacrifice is not None:
        sacrifice_filter = _chargeable_sacrifice_filter(
            any_number_sacrifice.group(1), plural=True
        )
        if sacrifice_filter is not None:
            sacrifice_count = "any"
    # "Sacrifice this creature **and a creature named Spitting Drake**" (Kyscu
    # Drake). The source and one chosen permanent under one printed verb, joined
    # by a bare "and" with no comma in front of it — which is exactly the shape
    # every reader above declines. The Oxford-list regex needs at least one
    # comma to match; the single-object delimiter is switched off entirely once
    # "sacrifice this ..." has set ``sacrifice_self``; and "any number of" reads
    # a set rather than one object. So the second half was read by nothing and
    # the ability cost the source alone — an activation cheaper than the card,
    # which is the direction that never crashes and never shows.
    #
    # Encoded the way the Oxford-list path already encodes the same facts: the
    # source in its flag, the chosen permanent in ``sacrifice_filter``. Guarded
    # on that field being empty so it runs only where every earlier reader
    # declined, which keeps Sword of the Ages' "and any number of creatures you
    # control" with the reader that understands its count.
    if sacrifice_self and sacrifice_filter is None:
        conjoined = re.search(
            r"\bsacrifice this \w+ and ((?:another|an?) [^,:]+?)\s*(?=,|$)",
            cost_lower,
        )
        if conjoined is not None:
            sacrifice_filter = _chargeable_sacrifice_filter(conjoined.group(1))
    # "Discard a card" (Seasoned Hallowblade), "Discard a land card or Shrine
    # card" (Sanctum of Shattered Heights). Jandor's Ring's history-named card is
    # read above; counting it here too would charge the Ring twice.
    #
    # The regex only **delimits** the noun phrase, to the end of its
    # comma-separated cost segment, exactly as the sacrifice one above does; what
    # the phrase names is read by the noun parser through
    # `_chargeable_discard_filters`. The count comes off that reader rather than
    # off a second regex, so a phrase it refuses charges no discard at all
    # instead of charging the unnarrowed one.
    discarded = (
        None if discard_last_drawn
        else re.search(r"\bdiscard (an? [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    # "Discard a card **at random**" (Coral Helm). Stripped from the phrase
    # before the noun parser sees it — it is not part of what the card must
    # *be*, it is how the card is chosen — and recorded so the payment path
    # draws rather than lets the payer name one. Left in, the noun parser would
    # refuse "a card at random" and the cost would silently become none at all.
    discard_phrase = discarded.group(1) if discarded else None
    discard_at_random = False
    if discard_phrase and discard_phrase.endswith(" at random"):
        discard_phrase = discard_phrase[: -len(" at random")]
        discard_at_random = True
    discard_filters = (
        _chargeable_discard_filters(discard_phrase) if discard_phrase else None
    )
    # "Tap two untapped Spirits you control" (Shacklegeist). The {T} symbol was
    # already consumed above as mana; this is the spelled-out form, which taps
    # *other* permanents.
    tap_cost = _chargeable_tap_cost(cost_lower)
    # "Return a Forest you control to its owner's hand" (Quirion Ranger).
    # The same shape one zone over, and read after the tap cost for no reason
    # but that the two never share a segment.
    return_cost = _chargeable_return_to_hand_cost(cost_lower)
    # "Discard your hand" (Subira). Matched here rather than folded into the
    # phrase above, because it is not a count: there is no card for the payer to
    # name and no filter to test, and it is payable with an empty hand.
    discard_whole_hand = bool(re.search(r"\bdiscard your hand\b", cost_lower))
    # "Discard this card" (Waker of Waves) - the card itself, from the hand.
    discard_self = bool(re.search(r"\bdiscard this card\b", cost_lower))
    # "Put a page counter on this artifact" (Mazemind Tome). The kind runs
    # ``[a-z]+`` **or** the P/T spelling, for the reason the removal regex below
    # states in full: a P/T counter is written in symbols (CR 122.1a), and a
    # cost clause that matches nothing is not a refused ability but a free one.
    counter_cost = re.search(
        r"\bput an? ([a-z]+|[+-]\d+/[+-]\d+) counter on this ", cost_lower
    )
    put_counter = counter_cost.group(1) if counter_cost else None
    # "Put a **-1/-1** counter on **a creature you control**" (Wandering Mage) —
    # the same cost aimed somewhere other than the source. The regex only
    # *delimits* the noun phrase, to the end of its cost segment, exactly as the
    # sacrifice and discard ones above do; what the phrase names is read by the
    # noun parser through ``_chargeable_counter_target``, so a phrase it refuses
    # charges no counter at all rather than charging an unnarrowed one.
    put_counter_filter = None
    if put_counter is None:
        chosen_counter = re.search(
            r"\bput an? ([a-z]+|[+-]\d+/[+-]\d+) counter on (an? [^,:]+?)\s*(?=,|:|$)",
            cost_lower,
        )
        if chosen_counter is not None:
            put_counter_filter = _chargeable_counter_target(chosen_counter.group(2))
            if put_counter_filter is not None:
                put_counter = chosen_counter.group(1)
    # "Remove a corpse counter from this creature" (Scavenging Ghoul), and the
    # ability Life Matrix grants with its own counter's word. Read out of the
    # phrase rather than listed, for the reason CR 122.1 gives: the kinds are
    # open, and a card - or a grant - may invent one.
    # A P/T counter is spelled in symbols, not letters (CR 122.1a), so
    # ``[a-z]+`` matched nothing at all for it — and an activation cost that
    # matches nothing is not a refused ability, it is a **free** one. Triskelion
    # ("Remove a +1/+1 counter from this creature: It deals 1 damage to any
    # target.") pinged for one damage per activation forever, with its three
    # counters untouched; Balduvian Hydra's "+1/+0" prevention shield did the
    # same. Both compiled clean, and nothing could have caught it but reading
    # the parsed cost.
    removal_cost = re.search(
        r"\bremove an? ([a-z]+|[+-]\d+/[+-]\d+) counter from ", cost_lower
    )
    remove_counter = removal_cost.group(1) if removal_cost else None
    remove_counter_count: int | str = 1
    if remove_counter is None:
        # "Remove **any number of** charge counters from this artifact" (the
        # five Mana Batteries). The same cost with the count left to the payer,
        # so it is the same field plus how many — not a second cost. Without
        # this row the clause matched nothing at all: the ability was activated
        # for free, forever, and its effect had no number to read.
        any_number = re.search(
            r"\bremove any number of ([a-z]+) counters from ", cost_lower
        )
        if any_number is not None:
            remove_counter = any_number.group(1)
            remove_counter_count = "any"
    if remove_counter is None:
        # "Remove **three spore** counters from this creature" (Thallid and the
        # rest of Fallen Empires' Saproling engine), "Remove **two carrion**
        # counters from this creature" (Osai Vultures). A *printed* count, and
        # the third row this pattern has needed for one reason: the singular
        # "an?" matched nothing at all, so the ability was activated for free
        # and could be activated forever -- Osai Vultures has been shipping an
        # unlimited +1/+1 since Legends was ingested, with its carrion counters
        # untouched.
        #
        # The regex only **delimits** the number; ``_NUMBER_WORDS`` reads it,
        # which is the split every other counted clause in this file makes. Read
        # after the "any number of" row above, whose opening words it would
        # otherwise have to exclude by hand.
        counted_removal = re.search(
            r"\bremove (\w+) ([a-z]+|[+-]\d+/[+-]\d+) counters from ",
            cost_lower,
        )
        if counted_removal is not None:
            word = counted_removal.group(1)
            number = int(word) if word.isdigit() else _NUMBER_WORDS.get(word, 0)
            if number >= 2:
                remove_counter = counted_removal.group(2)
                remove_counter_count = number
    return ActivatedAbilityCost(
        required, requires_tap, discard_last_drawn, exile_self, sacrifice_self,
        return_self_to_hand=return_self_to_hand,
        sacrifice_filter=sacrifice_filter,
        exile_filter=exile_filter,
        exile_zone=exile_zone,
        exile_zone_owner=exile_zone_owner,
        exile_count=exile_count,
        exile_same_zone=exile_same_zone,
        sacrifice_count=sacrifice_count,
        tap_filter=tap_cost[1] if tap_cost else None,
        tap_count=tap_cost[0] if tap_cost else 0,
        return_to_hand_filter=return_cost[1] if return_cost else None,
        return_to_hand_count=return_cost[0] if return_cost else 0,
        discard_cards=0 if discard_filters is None else 1,
        discard_filters=discard_filters or (),
        discard_at_random=discard_at_random and discard_filters is not None,
        discard_whole_hand=discard_whole_hand,
        discard_self=discard_self,
        put_counter=put_counter,
        put_counter_filter=put_counter_filter,
        sacrifice_also_filter=sacrifice_also_filter,
        remove_counter=remove_counter,
        remove_counter_count=remove_counter_count,
        pay_life=_life_payment_cost(cost_lower),
        pay_life_per_counter=_life_payment_per_counter(cost_lower),
        alternative_mana=alternative_mana,
        tap_attached=_taps_the_attached_permanent(cost_lower),
        mana_from_attached=_pays_the_attached_permanents_mana_cost(cost_lower),
        exile_top_of_library=exile_top_of_library,
        untap_filter=_chargeable_untap_cost(cost_lower),
    )


# ---------------------------------------------------------------------------
# Trigger condition parsing
# ---------------------------------------------------------------------------

# A named group ending in this holds a printed *noun phrase* rather than a
# word: "whenever a creature you control **with deathtouch** attacks". The regex
# only delimits it — what it names is read by the noun parser, so the two front
# ends of the pipeline turn one phrase into one filter instead of a regex
# approximating what the grammar does.
_SUBJECT_GROUP_SUFFIX = "_subject"

# The same idea for a printed *number*: "whenever you attack with **two** or
# more creatures with flying". The regex delimits the word and `_NUMBER_WORDS`
# reads it, so a count is data on the condition rather than a pattern per
# number.
_COUNT_GROUP_SUFFIX = "_count"

# The same noun phrase in the one position where it is **counted** rather than
# quantified: "two or more **creatures with flying**". A bare plural is the noun
# parser's sweep quantifier, which every other subject position refuses — so the
# plural spelling of the suffix is how a pattern says which reading it means.
_PLURAL_SUBJECT_GROUP_SUFFIX = "_subjects"

# The same noun phrase where one printed clause narrows **both** halves of a
# blocking pair: "blocks or becomes blocked by a non-Wall creature". English
# distributes the phrase over both verbs, and the engine already has a filter
# key per half — so the group resolves into both rather than into a third key
# nothing reads, and the two general dispatchers need no notion of a joined
# condition at all.
_PAIR_SUBJECT_GROUP_SUFFIX = "_pair_subject"

# The same joined phrase in its **counted** spelling: "blocks or becomes blocked
# by one or more **Orcs**" (Dwarven Soldier). A bare plural is the noun parser's
# sweep quantifier, exactly as it is for `_subjects` one suffix up, and the
# accompanying `_count` group is CR 509.3e's threshold — which is what makes
# this firing once rather than once per creature.
_PLURAL_PAIR_SUBJECT_GROUP_SUFFIX = "_pair_subjects"

# Which filter keys a `_pair_subject` group fans out to, in the order the two
# halves are printed. Named here rather than spelled at the fan-out below,
# because these are the keys the dispatchers read and a fourth spelling of them
# is how the two sides come apart.
_PAIR_SUBJECT_FILTER_KEYS = ("blocked_filter", "blocker_filter")

# What a ``<name>_includes_spells`` marker allows the accompanying noun phrase
# to say. The union "a red creature or spell" describes one object under two
# nouns, and only the words in front of the noun distribute over both — a spell
# on the stack is the printed card (CR 109.5), which has no controller, no
# layer-computed types and no board position to be asked about. ``type_filter``
# is the creature half's own noun (dropped for the spell half) and
# ``color_filter`` is the shared adjective; anything else refuses the condition,
# because a restriction a spell cannot be tested for is one the dispatcher would
# silently ignore on exactly half the sentence.
_SPELL_UNION_FILTER_KEYS = frozenset({"type_filter", "color_filter"})


def _match_trigger_patterns(
    text: str,
    patterns: tuple[tuple[str, re.Pattern[str]], ...],
    trigger_word: str,
) -> TriggerCondition | None:
    for kind, pattern in patterns:
        m = pattern.match(text)
        if not m:
            continue
        # Named groups become the condition's payload, so a narrowed
        # condition ("…casts a *blue* spell") carries its restriction as
        # data. Event dispatch reads it instead of needing a per-card hook.
        payload = {k: v for k, v in m.groupdict().items() if v is not None}
        payload = _resolve_subject_groups(payload)
        if payload is None:
            # The phrase is not a set of objects this engine can test. Refusing
            # the *condition* — rather than falling through to a later, wider
            # pattern — is the point: a trigger that fires on more than the card
            # prints is the silent wrongness the whole table exists to avoid.
            return None
        return TriggerCondition(
            kind=kind, trigger=trigger_word, raw_text=m.group(0), payload=payload
        )
    return None


def _resolve_subject_groups(payload: dict) -> dict | None:
    """Turn every delimited group in *payload* into the value the dispatcher
    reads, or return None if one of them says something it cannot test.

    Two suffixes, both of which mean "the regex marked this out and something
    else reads it": ``<name>_subject`` is a printed noun phrase, read by the
    noun parser; ``<name>_count`` is a printed number word, read by the same
    table every other text-keyed count uses. A number the table does not know
    refuses the whole condition rather than defaulting to one — a trigger that
    fires on one attacker where the card says three is the same silent widening
    an ignored filter would be.
    """
    from .grammar import subject_filter_payload
    from .subject_filters import TESTABLE_SUBJECT_FILTER_KEYS

    resolved = dict(payload)
    for key, word in payload.items():
        if not key.endswith(_COUNT_GROUP_SUFFIX):
            continue
        # A printed *digit* is a printed number. "When this creature's power
        # is **7** or greater" (Phyrexian Devourer) is the only spelling that
        # card uses, and `_NUMBER_WORDS` holds words alone — so without this
        # the group came back None and the whole condition refused, which is
        # the same shape `_chargeable_tap_cost` hit when "an" was missing from
        # that table. Read the same way every other counted clause in this
        # file reads one.
        text = str(word).strip()
        count = int(text) if text.isdigit() else _NUMBER_WORDS.get(text)
        if count is None:
            return None
        resolved[key] = count
    for key, phrase in payload.items():
        pair_plural = key.endswith(_PLURAL_PAIR_SUBJECT_GROUP_SUFFIX)
        if pair_plural or key.endswith(_PAIR_SUBJECT_GROUP_SUFFIX):
            described = subject_filter_payload(str(phrase), plural=pair_plural)
            if described is None or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
                return None
            del resolved[key]
            for filter_key in _PAIR_SUBJECT_FILTER_KEYS:
                resolved[filter_key] = described
            continue
        plural = key.endswith(_PLURAL_SUBJECT_GROUP_SUFFIX)
        if not plural and not key.endswith(_SUBJECT_GROUP_SUFFIX):
            continue
        suffix = _PLURAL_SUBJECT_GROUP_SUFFIX if plural else _SUBJECT_GROUP_SUFFIX
        described = subject_filter_payload(str(phrase), plural=plural)
        # The second gate is the load-bearing one: a filter the *dispatcher*
        # cannot test is refused here rather than ignored there, because an
        # ignored restriction is a trigger firing on more than the card says.
        if described is None or set(described) - TESTABLE_SUBJECT_FILTER_KEYS:
            return None
        del resolved[key]
        # "Whenever **this creature or** another Rogue you control enters"
        # (Thieves' Guild Enforcer). The phrase read above says "another", which
        # the noun parser folds into `exclude_self` — and the words in front of
        # it put the source back in. An empty named group is how a pattern says
        # so: it is present in the match's groupdict exactly when that spelling
        # matched, and it carries no text of its own to be re-read.
        stem = key[: -len(suffix)]
        if f"{stem}_includes_source" in payload:
            described = {k: v for k, v in described.items() if k != "exclude_self"}
            del resolved[f"{stem}_includes_source"]
        # "…attacks **you**" (Barbed Foliage). CR 506.2's defending player,
        # the same empty-marker-group idiom one paragraph up: present in the
        # groupdict exactly when that row matched, carrying no text of its own,
        # and folded into the filter the noun parser already built. Added after
        # the testability gate above because `attacking_you` is in
        # `TESTABLE_SUBJECT_FILTER_KEYS` — it is answered by
        # `subject_filters.subject_matches` like any other key, against the
        # trigger's own controller.
        if f"{stem}_attacking_you" in payload:
            described = {**described, "attacking_you": True}
            del resolved[f"{stem}_attacking_you"]
        if f"{stem}_includes_spells" in payload and (
            set(described) - _SPELL_UNION_FILTER_KEYS or "color_filter" not in described
        ):
            # "…a red creature **or spell**". The noun is the half that does not
            # distribute; every other word in the phrase does, and a spell is
            # the printed card (CR 109.5) with no board, no controller and no
            # layers — so a phrase saying anything a card cannot answer refuses
            # the condition rather than firing on the creature half alone. The
            # colour is required because it is the only thing left to test: a
            # bare "a creature or spell" would fire on every point of damage in
            # the game.
            return None
        resolved[stem + "_filter"] = described
    return resolved


def _parse_trigger_condition(normalized_line: str) -> tuple[TriggerCondition | None, str]:
    """Try to parse a trigger condition from the start of a normalized line.

    Returns (TriggerCondition, remainder_effect_text) or (None, original_line).
    The remainder is the effect clause after the condition, with leading
    punctuation and whitespace stripped.
    """
    if normalized_line.startswith("whenever "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHENEVER_PATTERNS, "whenever")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("when "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_WHEN_PATTERNS, "when")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder
        # CR 603.1 makes "when" and "whenever" one kind of ability: the words
        # differ in how often it triggers while it exists, never in what
        # triggers it, and no dispatcher in this engine reads the word. So a
        # "when" line this table misses is asked of the *whenever* table with
        # the one word swapped, rather than by copying rows between the two —
        # which is what the tables used to do, one card at a time, leaving every
        # event nobody had copied refusing its "when" printing while the engine
        # fired it happily for "whenever". The remainder is sliced off the
        # rewritten line because that is the string the pattern matched; the
        # condition still reports the word the card printed.
        as_whenever = "whenever " + normalized_line[len("when "):]
        cond = _match_trigger_patterns(
            as_whenever, _COMPILED_WHENEVER_PATTERNS, "when"
        )
        if cond:
            remainder = as_whenever[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    if normalized_line.startswith("at "):
        cond = _match_trigger_patterns(normalized_line, _COMPILED_AT_PATTERNS, "at")
        if cond:
            remainder = normalized_line[len(cond.raw_text):].lstrip(" ,")
            return cond, remainder

    return None, normalized_line


_TRAILING_IF_RE = re.compile(r",\s*(if .+)$")


def _extract_if_condition(effect_text: str) -> tuple[str | None, str]:
    """Strip a trailing 'if ...' clause from an effect and return (if_kind, clean_effect).

    Returns (None, original_text) if no recognized 'if' condition is present.
    """
    # Look for ", if ..." near the end of the effect text
    if_match = _TRAILING_IF_RE.search(effect_text)
    if not if_match:
        return None, effect_text

    if_clause = if_match.group(1)
    for kind, pattern in _COMPILED_IF_PATTERNS:
        if pattern.match(if_clause):
            clean = effect_text[: if_match.start()].strip()
            return kind, clean

    return None, effect_text


def trigger_condition_of_line(
    line: str, card_name: str | None = None
) -> tuple[TriggerCondition | None, str]:
    """The legacy table's reading of one printed line: ``(condition, remainder)``.

    **This is the only reading.** It used to live inline in
    ``_parse_triggered_ability``, which meant every other caller that wanted to
    know "what condition does the legacy table see here?" — the pool-wide guard
    in ``tests/engine/test_grammar_lowering.py`` most sharply — wrote the
    normalize-and-parse half and dropped the self-reference fallback below. Two
    readings of one table is the bug this project keeps finding: the guard
    reported Axelrod Gunnarson and Nicol Bolas as conditions "the legacy table
    does not name", when the table names both and only the guard could not see
    it.

    The fallback: the card's own name collapsed to "this creature", for the
    reason ``_restriction_line`` gives about the static tables. Every row is
    anchored on the modern templating, and a card that says its own name
    ("Whenever a creature dealt damage by **Axelrod Gunnarson** this turn dies")
    is printing a condition this engine already dispatches, the old way. Without
    it the row matched nothing and the card reported "text too complex" while
    the grammar — whose lexer collapses the same references — read the line. Two
    front ends disagreeing about one printed line is a card refused by the
    stricter of them.

    A *fallback* rather than the first reading, because the collapse is a
    whole-word substitution over the entire line and a card whose name is an
    ordinary word ("Fire", or a test fixture called "Player") would have its
    recipient clause rewritten out from under a row that already matched.
    Nothing this reads is text the uncollapsed pass could read.
    """
    normalized = normalize_creature_line(line)
    condition, remainder = _parse_trigger_condition(normalized)
    if condition is None and card_name:
        collapsed = _collapse_self_references(normalized, card_name, "this creature")
        if collapsed != normalized:
            condition, remainder = _parse_trigger_condition(collapsed)
    return condition, remainder


def _parse_triggered_ability(line: str, card_name: str | None = None) -> ParsedTriggeredAbility | None:
    """Parse a single oracle text line as a triggered ability.

    Returns None if the line doesn't start with a trigger word at all,
    so the caller can try other parsers. Returns a ParsedTriggeredAbility
    with supported=False if the trigger prefix is recognized but the
    condition or effect is not.
    """
    condition, remainder = trigger_condition_of_line(line, card_name)
    if condition is None:
        return None  # not a triggered ability line

    # Strip leading colon/comma that sometimes follows the condition clause
    remainder = remainder.lstrip(": ")

    # Extract any trailing "if ..." guard on the effect. The clause it strips is
    # no longer read on its own: the front ends take the whole line, so the
    # guard's only job now is the payload key attached below.
    if_kind, _clean_effect = _extract_if_condition(remainder)

    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, condition_kind=condition.kind)
    )

    if instruction is not None and if_kind is not None:
        # Attach the if-condition into the instruction payload
        instruction = OracleInstruction(
            instruction.kind,
            instruction.value,
            {**instruction.payload, "if_condition": if_kind},
        )

    supported = instruction is not None
    return ParsedTriggeredAbility(
        source_line=line,
        condition=condition,
        instruction=instruction,
        supported=supported,
        effect_kind=effect_kind if supported else "unsupported",
    )


# ---------------------------------------------------------------------------
# Grammar front end
# ---------------------------------------------------------------------------
#
# engine.grammar parses a line into a typed AST and lowers it to instructions.
# It runs on every line, and its result is used when every category it lowered
# to is switched on in engine.grammar.GRAMMAR_CATEGORIES. A line it refuses now
# reaches the name-keyed card hooks and then nothing — there is no legacy
# registry left underneath, so a category switched off is a card reported
# unsupported rather than a card quietly read by something else.


def _grammar_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    condition_kind: str | None = None,
    spell_line_only: bool = False,
    event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """The grammar's ``(instruction, effect_kind)`` for one line, or None when
    the grammar does not claim it.

    *activated* and *condition_kind* name the **position** the line occupies —
    an ability's clause, a trigger's remainder (whose condition they carry), or
    a plain effect line. They decide only the ``effect_kind`` label
    (``engine/effect_labels.py``), never the instruction.

    A multi-instruction lowering is wrapped in a single ``sequence``
    instruction, so composition becomes first-class in the IR without changing
    the one-instruction shape that ParsedActivatedAbility,
    ParsedTriggeredAbility and the stack all currently assume.

    *spell_line_only* restricts the result to plain one-shot effect lines: the
    instructions of a card whose *resolution* carries them out. For an instant
    or sorcery the stack executes every non-``spell_pattern`` instruction in
    that list, so an activated ability's effect must never enter it — the spell
    would perform the ability on resolution.

    A permanent's list is a mirror rather than a program (see
    ``_noncreature_line_instructions``), so it does hold its abilities' effects,
    exactly as ``_parse_creature_program`` has always done for creatures.
    ``_resolve_card`` puts a permanent onto the battlefield and returns without
    reaching ``_apply_spell_text``, which is the only caller that executes this
    list — so the mirror cannot fire on cast.
    """
    compiled = compile_grammar_line(line, card_name=card_name, event=event)
    if not compiled.usable:
        return None
    if isinstance(compiled.node, grammar_ast.DerivedLine):
        # A derivation table's board-wide static is a *co-effect*, collected by
        # _grammar_static_coeffects after the per-line pass rather than here.
        # See that function for why the position matters.
        return None
    if spell_line_only and not isinstance(compiled.node, grammar_ast.SpellEffectLine):
        return None

    instructions = compiled.instructions
    if len(instructions) == 1:
        instruction = instructions[0]
    else:
        # CR 603.4's gate is attached by ``lower_ability`` to every *top-level*
        # instruction the line lowered to. Wrapping them makes the wrapper the
        # new top level, and both readers of the gate — the scan in
        # engine/phases/end_step.py and the resolution re-check in
        # engine/mixins/stack/resolution.py — read the top level. So a wrapper
        # that did not carry it put the condition on a payload nothing reads,
        # and the trigger was never enqueued at all: Sabertooth Mauler's "put a
        # +1/+1 counter on this creature **and untap it**" lowers to two
        # instructions and had never once fired, while reporting supported with
        # both halves correctly gated.
        #
        # Carried only when every step agrees, because the gate is the *line's*
        # and a wrapper cannot express two different ones. Steps that disagree
        # keep their own and the wrapper stays ungated, which is the behaviour
        # before this — no card in the pool lowers that shape.
        payload: dict = {"steps": instructions}
        gate = instructions[0].payload.get("intervening_if")
        if gate is not None and all(
            step.payload.get("intervening_if") == gate for step in instructions
        ):
            payload["intervening_if"] = gate
        instruction = OracleInstruction("sequence", "", payload)
    category = next(iter(sorted(compiled.categories)), "effect")
    if condition_kind is not None:
        effect_kind = triggered_label(instruction.kind, condition_kind)
    elif activated:
        effect_kind = activated_label(instruction.kind, category)
    else:
        effect_kind = "spell_pattern"
    return instruction, effect_kind


def _grammar_static_coeffects(
    oracle_text: str, card_name: str | None
) -> tuple[OracleInstruction, ...]:
    """Board-wide continuous statics a derivation table reads off one line.

    Kormus Bell's "All Swamps are 1/1 black creatures that are still lands.",
    Conversion's "All Mountains are Plains.", Jihad's conditional anthem — each
    derived in full by an engine table (``engine/grammar/derived.py`` names
    them) and each a *co-effect*: it coexists with whatever else the card says
    rather than being the effect the card's resolution carries out.

    Collected after the per-line pass, for the reason the deleted
    ``parse_static_coeffects`` also was: a card can state one of these alongside
    a clause that already claimed the card's instruction (Conversion's upkeep
    cost, Jihad's enter-choice and sacrifice trigger). Claiming it as an
    ordinary line instruction would *suppress* the reading of those other
    sentences, which is a different program, not a better one.
    """
    coeffects: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        compiled = compile_grammar_line(line, card_name=card_name)
        if compiled.usable and isinstance(compiled.node, grammar_ast.DerivedLine):
            coeffects.extend(compiled.instructions)
    return tuple(coeffects)


def _card_hook_instruction(
    line: str,
    card_name: str | None,
    *,
    spell_line_only: bool = False,
) -> tuple[OracleInstruction, str] | None:
    """The name-keyed reading of one line, for texts that are a single card.

    The second front end, consulted only where the grammar declined. Most of
    what ``engine/parsing/`` claimed is templating and belongs in a production;
    the rest is one card's sentence bound to a handler written for it, and those
    live in ``engine/card_hooks.py`` — the one file whose subject is a card's
    name (see CARD_LINE_INSTRUCTIONS for the entry bar).

    Kept out of :func:`_grammar_instruction` on purpose, so that stubbing the
    grammar (``tests/engine/test_front_end_safety.py``) leaves the hooks
    standing; folding them in would stub those too and the guard would report
    every hooked card as a loss.

    A hook carries its own ``effect_kind``, so it never consults
    ``engine/effect_labels.py`` and the position flags do not reach it.
    """
    from .card_hooks import card_line_instruction

    found = card_line_instruction(card_name, normalize_creature_line(line))
    if found is None:
        return None
    if spell_line_only and _is_ability_line(line):
        return None
    return found.instruction, found.effect_kind


def _is_ability_line(line: str) -> bool:
    """Whether *line* is an activated or triggered ability rather than a plain
    effect the card's resolution carries out.

    The same question ``spell_line_only`` asks of the grammar's node type, asked
    of the raw text — an ability's effect must never enter an instant's or
    sorcery's instruction list, or the spell would perform the ability when it
    resolves.
    """
    normalized = normalize_creature_line(line)
    if ":" in normalized:
        return True
    return _parse_trigger_condition(normalized)[0] is not None


def _line_instruction(
    line: str,
    card_name: str | None,
    *,
    activated: bool = False,
    condition_kind: str | None = None,
    spell_line_only: bool = False,
    event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """The front ends that read one line, most general first: the grammar, then
    the name-keyed card hooks. There is no third — a line neither claims has no
    instruction, and the card is reported unsupported naming the clause."""
    found = _grammar_instruction(
        line, card_name,
        activated=activated, condition_kind=condition_kind,
        spell_line_only=spell_line_only, event=event,
    )
    if found is not None:
        return found
    return _card_hook_instruction(line, card_name, spell_line_only=spell_line_only)


def _reading(
    found: tuple[OracleInstruction, str] | None,
) -> tuple[OracleInstruction | None, str]:
    """A front end's reading, widened to the ``(instruction | None, label)`` shape
    the ability parsers return.

    This was ``_prefer_line_reading``, which took a *second* argument — the
    legacy registry's reading of the same line — and used it for two things: the
    instruction when no front end claimed the line, and the ``effect_kind``
    label whenever a legacy rule matched, even where the grammar had already
    produced the instruction. The first is gone with the registry; the second is
    ``engine/effect_labels.py``.
    """
    if found is None:
        return None, "unsupported"
    return found


def _modal_head(line: str, wrapper: type) -> "grammar_ast.ModalNode | None":
    """The modal head *line* is, read through the grammar — or None.

    *wrapper* is the ability-line node the head has to sit inside, and it is
    what tells a spell's mode list apart from an activated ability's:
    ``SpellEffectLine`` for the bare "Choose one —" a spell announces on the
    stack (CR 601.2b), ``ActivatedAbilityNode`` for the "{2}: Choose one —"
    :func:`expand_modal_activated_lines` rewrites. A head behind a *trigger*
    matches neither and is claimed by nothing here, which is right: its modes
    are chosen when the ability goes on the stack (CR 700.2b), not when the card
    is cast.

    **One reader.** Two substring matchers used to answer this — ``choose
    one\\b`` anywhere in the card's text for a spell, a mana-symbols-then-``choose
    one`` regex per line for an ability — and between them they got the count
    wrong (``choose one`` matches inside "Choose one **or more**", so Sublime
    Epiphany read as a one-mode spell), missed every count but one, and asked
    the question of the whole card rather than of a line. The grammar parses the
    count and the lowering refuses what the engine cannot carry out, so a head
    it declines is one this must not act on either — which is exactly what
    checking ``lowering_error`` says.
    """
    compiled = compile_grammar_line(line)
    if compiled.lowering_error is not None:
        return None
    node = compiled.node
    if not isinstance(node, wrapper):
        return None
    statement = getattr(node, "statement", None)
    return statement if isinstance(statement, grammar_ast.ModalNode) else None


def _mode_reading(
    label: str, card_name: str | None, *, event: str | None = None,
) -> tuple[OracleInstruction, str] | None:
    """A modal bullet's ``(instruction, effect_kind)``, or None.

    ``effect_kind`` is "spell_pattern" for every bullet the front ends claim,
    not the grammar's category label. A mode is one alternative of a spell, and
    the label is what ``SimulationResult`` and the support report bucket the
    *card* by — so it names the reading's shape, exactly as it did when the
    legacy registry produced it.

    *event* is the head's own contribution to what the bullet means: under
    "**An opponent** chooses one —" (CR 700.2e) the mode's "that player" names
    the chooser, a seat the sentence cannot see from inside the bullet. See
    ``lowering/_events.OPPONENT_CHOSE_MODE``.
    """
    found = _line_instruction(label, card_name, event=event)
    if found is None:
        return None
    return found[0], "spell_pattern"


def _bullets_after(lines: list[str], index: int) -> list[str]:
    """The run of bulleted lines immediately below *index* — a head's modes.

    Stops at the first line that is not a bullet, which is what makes this
    *grouping* rather than a scan: the old version partitioned the card's whole
    text at the first "•" and split the remainder, so a bullet list anywhere on
    the card belonged to any "choose one" anywhere else on it.

    Fewer than two is not a mode list. CR 700.2 defines a modal spell as having
    "two or more options in a bulleted list", so a lone bullet under a head is
    text this does not understand, and returning it as a one-mode spell would be
    a guess wearing the shape of a reading.
    """
    bullets: list[str] = []
    for raw in lines[index + 1:]:
        line = raw.strip()
        if not line.startswith("•"):
            break
        bullets.append(_WHITESPACE_RE.sub(" ", line.lstrip("•").strip()).strip())
    return bullets if len(bullets) >= 2 else []


def _modal_options(oracle_text: str, card_name: str | None) -> tuple[ModalOption, ...]:
    """The bullets of a "Choose one —" spell, one :class:`ModalOption` each.

    Grouping a head with the bullets below it is line classification, which is
    this module's job; *reading* each of those lines is the grammar's, on both
    halves — the head through :func:`_modal_head`, each bullet's effect through
    the same front ends an ordinary line goes to (:func:`_line_instruction`). A
    mode is supported exactly when its own clause is, which is why a card with
    one readable mode and one unreadable one still resolves the readable one.

    Modal **activated** abilities never reach here: ``expand_modal_activated_lines``
    has already rewritten them into one ordinary ability line per bullet, so a
    bullet arriving here is always one alternative of a spell. A modal
    **triggered** ability does reach here and is not claimed, because its head
    parses as a ``TriggeredAbilityNode`` rather than a spell's effect line —
    where the old whole-text substring test would have turned its modes into
    cast-time ones.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        # A pre-filter, not a second reading: both are necessary for the grammar
        # to return a head at all, so this can only skip work, never an answer.
        return ()

    lines = oracle_text.splitlines()
    # "**An opponent** chooses one —": the head is what makes the bullets'
    # "that player" mean the chooser, so the mode's lowering is told which
    # position it occupies. Computed once for the card rather than per bullet.
    mode_event = (
        OPPONENT_CHOSE_MODE if _modal_chooser(oracle_text) is not None else None
    )
    for index, raw in enumerate(lines):
        if _modal_head(raw.strip(), grammar_ast.SpellEffectLine) is None:
            continue
        bullets = _bullets_after(lines, index)
        if not bullets:
            continue
        options: list[ModalOption] = []
        for label in bullets:
            instruction, effect_kind = _reading(
                _mode_reading(label, card_name, event=mode_event)
            )
            # The original casing is kept for the UI's mode picker.
            options.append(
                ModalOption(label.rstrip("."), instruction, effect_kind, instruction is not None)
            )
        return tuple(options)
    return ()


def modal_head_line(line: str) -> bool:
    """Whether *line* is a modal head — the sentence a bulleted mode list hangs
    under (CR 700.2).

    Public because ``scripts/parse_coverage.py`` asks, and it has to ask the
    same reader this module dispatches on. It used to test the substring
    ``startswith("choose one")``, which is a second reading of the line and went
    stale the moment a head printed its chooser: "**An opponent** chooses one —"
    (CR 700.2e) compiled, carried its modes and reported its own head as text
    nothing parses.

    Both wrappers, because a head is printed bare on a spell and after a trigger
    condition, and the claim is about the *sentence* either way.
    """
    return (
        _modal_head(line, grammar_ast.SpellEffectLine) is not None
        or _modal_head(line, grammar_ast.TriggeredAbilityNode) is not None
    )


def _modal_chooser(oracle_text: str) -> str | None:
    """Who picks the mode, when the head names somebody other than the spell's
    controller — "**An opponent** chooses one —" (CR 700.2e).

    Read through the same :func:`_modal_head` the mode list and the bound are,
    for that pair's reason: three answers taken from three readings of one line
    are three answers free to disagree about which head they came from.

    None for every other modal card, which is CR 700.2a's ordinary case and the
    one the cast path already carries.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        return None
    lines = oracle_text.splitlines()
    for index, raw in enumerate(lines):
        head = _modal_head(raw.strip(), grammar_ast.SpellEffectLine)
        if head is None or not _bullets_after(lines, index):
            continue
        return head.chooser.kind if head.chooser is not None else None
    return None


def _modal_at_least(oracle_text: str) -> bool:
    """Whether the head above the bullets is "Choose one **or more** —".

    Read through the same :func:`_modal_head` the mode list is, so the bound and
    the modes cannot disagree about which head they came from — the failure the
    substring matcher had, where "choose one" matched inside "choose one or
    more" and the card read as a one-mode spell.
    """
    if "choose" not in oracle_text.lower() or "•" not in oracle_text:
        return False
    lines = oracle_text.splitlines()
    for index, raw in enumerate(lines):
        head = _modal_head(raw.strip(), grammar_ast.SpellEffectLine)
        if head is None or not _bullets_after(lines, index):
            continue
        return bool(head.at_least)
    return False


def _modal_trigger_ability(
    lines: list[str], index: int, card_name: str | None,
) -> tuple[ParsedTriggeredAbility, int] | str | None:
    """The modal triggered ability whose head sits at *index*, with how many
    bullet lines it consumed — or a refusal reason, or None.

    "When this creature enters, choose one —" plus the bullets below it
    (Trufflesnout; Elder Gargaroth's attacks-or-blocks). The head's condition
    and each bullet are read by the same front ends any other line goes to;
    the grouping alone is this module's job, exactly as it is for a modal
    spell. The assembled instruction is one ``choose_one`` carrying every
    mode, because a triggered ability triggers *once* and the controller picks
    a mode when it goes on the stack (CR 700.2b) — expanding to one trigger
    per bullet, the way modal activated abilities are rewritten, would fire
    them all.

    Returns None when the line is not a modal trigger head at all (an
    ordinary line, or a head whose count the engine cannot carry — "choose
    one or more" fails `_modal_head`'s lowering check and stays refused). A
    *recognized* head with an unreadable condition or a dead mode returns the
    refusal reason instead: the all-of gate round 20 established for modal
    spells, because a mode list with a dead entry is a card that offers a
    choice and then declines to perform it.
    """
    head = lines[index].strip()
    if _modal_head(head, grammar_ast.TriggeredAbilityNode) is None:
        return None
    bullets = _bullets_after(lines, index)
    if not bullets:
        return None
    trig = _parse_triggered_ability(head, card_name)
    if trig is None:
        return f"unsupported modal trigger condition: {head!r}"
    modes: list[dict] = []
    for label in bullets:
        found = _line_instruction(label, card_name)
        if found is None:
            return f"unsupported mode of a triggered ability: {label!r}"
        instruction = found[0]
        mode = {"label": label.rstrip("."), "instruction": instruction}
        if not modal_trigger_mode_is_derivable(mode):
            # The mode targets, and nothing can say what it targets — so the
            # picker would offer it with no candidates and CR 700.2b would then
            # make it permanently unchoosable. A card that prints two modes and
            # can only ever take one of them is worse than an unsupported one,
            # which is at least visible in the backlog.
            return f"a mode of a triggered ability targets undescribably: {label!r}"
        modes.append(mode)
    inline_refusal = modal_trigger_targeting_refusal(trig.condition.kind, tuple(modes))
    if inline_refusal is not None:
        return inline_refusal
    choose = OracleInstruction(MODAL_INSTRUCTION_KIND, "", {"modes": tuple(modes)})
    return (
        ParsedTriggeredAbility(
            source_line=" ".join([head] + [f"• {b}" for b in bullets]),
            condition=trig.condition,
            instruction=choose,
            supported=True,
            effect_kind=triggered_label("choose_one", trig.condition.kind),
        ),
        len(bullets),
    )


# ---------------------------------------------------------------------------
# Creature-line helpers
# ---------------------------------------------------------------------------

def _is_supported_keyword_line(line: str) -> bool:
    """Whether a printed keyword line names only keywords the engine implements.

    Reads `IMPLEMENTED_KEYWORDS` rather than a local copy: what may be *admitted*
    here and what the grammar will *lower* are the same claim, and two lists
    agreeing by hand is the arrangement this codebase keeps finding bugs in.
    """
    normalized = normalize_creature_line(line)
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if not parts:
        return False
    # The two parameterised keywords are admitted by prefix plus quality:
    # "protection from white and from blue" and "hexproof from blue" carry the
    # quality as payload, not as part of the keyword's identity. What may be
    # admitted is exactly what the shield machinery models — colours for both,
    # and for protection also "multicolored", "planeswalkers" and creature
    # subtypes ("Demons and from Dragons", Baneslayer Angel), the qualities
    # ``_protection_qualities`` reads. A quality it does not model keeps the
    # whole line refused with the clause named, because admitting the word
    # would ship the card and silently drop the shield.
    return all(
        part in IMPLEMENTED_KEYWORDS or _qualified_keyword_part(part)
        for part in parts
    )


def _protection_quality_word(word: str) -> bool:
    if word in _COLOR_WORD_TO_SYMBOL or word in ("multicolored", "planeswalkers", "planeswalker"):
        return True
    from .grammar.vocabulary import CREATURE_TYPES

    singular = word[:-1] if word.endswith("s") else word
    return word in CREATURE_TYPES or singular in CREATURE_TYPES


def _qualified_keyword_part(part: str) -> bool:
    # Rampage carries a number rather than a quality (CR 702.23a: "Rampage N"),
    # and the number is the whole of it — so the reader that *implements* it is
    # the one that admits it, exactly as the protection arm below admits only
    # the qualities `_protection_qualities` models.
    if rampage_amount(part) is not None:
        return True
    # Cumulative upkeep carries a cost rather than a quality (CR 702.24a), and
    # the cost is the whole of it. Same rule as rampage one line up: the reader
    # that *implements* the keyword admits it, so a cost `engine/
    # cumulative_upkeep.py` cannot charge keeps the line refused instead of
    # shipping a permanent whose upkeep is silently free.
    from .cumulative_upkeep import cumulative_upkeep_cost

    if cumulative_upkeep_cost(part) is not None:
        return True
    # "Bands with other legendary creatures" (CR 702.22b). The quality is a
    # printed noun phrase rather than a word from a list, so what admits the
    # line is the reader that *implements* it — engine/banding.py, which turns
    # the phrase into the filter payload the combat sites test. A quality the
    # noun parser cannot read, or one carrying a restriction the matcher cannot
    # answer, keeps the line refused: a band whose quality is dropped is a band
    # any creature may join.
    from .banding import is_bands_with_other, is_implemented as _band_implemented

    if is_bands_with_other(part):
        return _band_implemented(part)
    # "Legendary landwalk" (CR 702.14a's quality-first shape). Same reasoning
    # again: the ability's name is built from the printed quality, so no word
    # list can hold it — what admits the line is `engine/landwalk.py`, the
    # reader the declare-blockers step *enforces* it with. A quality that
    # reader cannot test keeps the line refused, because admitting the word
    # would ship a creature whose evasion silently never applies.
    from .landwalk import is_landwalk

    if is_landwalk(part):
        return True
    for prefix, admit in (
        ("protection from ", _protection_quality_word),
        # Hexproof stays colour-only: _can_be_targeted's hexproof branch reads
        # colour words alone.
        ("hexproof from ", lambda w: w in _COLOR_WORD_TO_SYMBOL),
    ):
        if part.startswith(prefix):
            qualities = [
                q.strip()
                for q in re.split(r",|\band from\b|\band\b", part[len(prefix):])
                if q.strip()
            ]
            return bool(qualities) and all(admit(q) for q in qualities)
    return False


def _parse_activated_ability(line: str, card_name: str | None = None) -> ParsedActivatedAbility | None:
    normalized = normalize_creature_line(line)
    # Not "is there a colon", but "is there an *activation* colon": one inside
    # quotation marks belongs to an ability the line grants, not to one the
    # permanent has. See :func:`activation_colon_index`.
    colon = activation_colon_index(normalized)
    if colon is None:
        return None

    effect_text = normalized[colon + 1:].strip()
    # "…: Until end of turn, whenever <subject> <event>, <effect>." (Subira.)
    # A delayed triggered ability created on resolution (CR 603.7), read here
    # for the same reason the loyalty path reads it: handed to the grammar, the
    # clause classifies as a triggered ability *of the permanent* and its inner
    # effect runs at once — a draw now instead of a draw when a creature
    # connects.
    delayed = _parse_delayed_attack_trigger(line.split(":", 1)[1].strip(), card_name)
    if delayed is not None:
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=effect_text,
            supported=True,
            cost=parse_activated_ability_cost(line),
            effect_kind="activated_delayed_trigger",
            instruction=delayed,
        )
    instruction, effect_kind = _reading(
        _line_instruction(line, card_name, activated=True)
    )
    cost = parse_activated_ability_cost(line)
    # "Tap enchanted creature: Target creature **other than the creature tapped
    # this way** …" (Veteran's Voice). The grammar resolved that pronoun to the
    # attached host, because a target filter is tested before the cost is paid
    # (CR 601.2h) and the cost-tap record is still empty then. That resolution is
    # true exactly while the cost is the one that taps the host — a claim about
    # the *cost*, which no target filter can see and which is checked here,
    # where both halves of the line are in hand.
    #
    # An ability printing the phrase with any other cost is refused rather than
    # read as excluding the host: the referent would be a permanent this
    # ability's cost never touched, and the card would target a set it does not
    # print.
    if COST_TAPPED_REFERENT in effect_text and not cost.tap_attached:
        instruction, effect_kind = None, "unsupported"
    supported = instruction is not None
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=effect_text,
        supported=supported,
        cost=cost,
        effect_kind=effect_kind,
        instruction=instruction,
    )


# ---------------------------------------------------------------------------
# Planeswalker program parser (CR 306, 606)
# ---------------------------------------------------------------------------

# A loyalty ability line: "+1: …", "−2: …", "0: …", "−X: …" (CR 606.2). The
# whole clause left of the colon is one loyalty symbol; anything wider is an
# ordinary activated-ability line and is read by _parse_activated_ability.
_LOYALTY_LINE_RE = re.compile(r"^\s*[+\-−]?\s*(?:\d+|[xX])\s*:")

# CR 306.5d relaxed by the card itself: "You may activate loyalty abilities of
# <name> on any player's turn any time you could cast an instant." (Teferi,
# Master of Time — a template several Teferi printings share). Stored as this
# canonical static line; the activation gate in mixins/stack/activation.py
# reads it back from OracleProgram.static_lines.
LOYALTY_ANY_TIME_STATIC = (
    "you may activate loyalty abilities of this planeswalker on any player's "
    "turn any time you could cast an instant"
)


def _self_name_forms(card_name: str | None) -> tuple[str, ...]:
    """The lowercase name forms a card may refer to itself by: the full name,
    and — for a name with a comma — the short name before it (CR 201.4c,
    "Ugin, the Spirit Dragon" says "Ugin")."""
    if not card_name:
        return ()
    full = card_name.strip().lower()
    forms = [full]
    if "," in full:
        forms.append(full.split(",", 1)[0].strip())
    return tuple(forms)


#: Words that put the name after them in a **type** position rather than a
#: self-reference position: "each other attacking **Aurochs**" is a creature
#: type, not the card talking about itself.
#:
#: Only reachable for a card whose own name *is* a creature type — four in the
#: pool, and only Aurochs uses it as a type. But the failure is the silent kind:
#: collapsed, the count reads "each other attacking **this creature**", a set of
#: one thing that excludes itself and is therefore always empty, so the pump
#: resolves for +0/+0 on a card reporting itself supported.
_TYPE_POSITION_WORDS = frozenset({
    "a", "an", "another", "any", "attacking", "blocking", "each", "every",
    "other", "target", "untapped", "tapped", "all", "no",
})


def _preceding_word(text: str, index: int) -> str:
    """The word immediately before *index*, lowercased, or "" at the start."""
    before = text[:index].rstrip()
    return before.rsplit(" ", 1)[-1].lower() if before else ""


def _collapse_self_references(normalized: str, card_name: str | None, replacement: str) -> str:
    """*normalized* with whole-word self-references replaced by *replacement*.

    A name that is also a **creature type** is left alone where the sentence
    uses it as one — see :data:`_TYPE_POSITION_WORDS`. Everywhere else it is the
    card naming itself (CR 201.4), the possessive "Lhurgoyf's power" included,
    which is the form the pool's other such cards print.
    """
    from .grammar.vocabulary import CREATURE_TYPES

    for form in _self_name_forms(card_name):
        if form.lower() in CREATURE_TYPES:
            normalized = re.sub(
                rf"\b{re.escape(form)}\b",
                lambda match, text=normalized: (
                    match.group(0)
                    if _preceding_word(text, match.start()) in _TYPE_POSITION_WORDS
                    else replacement
                ),
                normalized,
            )
            continue
        normalized = re.sub(rf"\b{re.escape(form)}\b", replacement, normalized)
    return normalized


def _planeswalker_static_line(line: str, card_name: str | None) -> str | None:
    """The canonical form of a recognized planeswalker static line, or None."""
    normalized = _collapse_self_references(
        normalize_creature_line(line), card_name, "this planeswalker"
    )
    if normalized == LOYALTY_ANY_TIME_STATIC:
        return normalized
    return None


@compilation_cache
@lru_cache(maxsize=None)
def compile_emblem_text(emblem_name: str, text: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities an emblem's quoted text carries (CR 114.4).

    Compiled through the same trigger parser every permanent's lines go
    through, once per distinct emblem text per process. A line the parser does
    not read comes back unsupported, which is what the walker's support gate
    checks before the card carrying the emblem may compile.
    """
    parsed: list[ParsedTriggeredAbility] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        trig = _parse_triggered_ability(line, emblem_name)
        if trig is None:
            return ()
        parsed.append(trig)
    return tuple(parsed)


def _emblem_texts(instruction: OracleInstruction) -> list[str]:
    """Every emblem text *instruction* creates, walking sequence steps."""
    if instruction.kind == "create_emblem":
        return [str(instruction.payload.get("text", ""))]
    if instruction.kind == "sequence":
        return [
            text
            for step in instruction.payload.get("steps", ())
            for text in _emblem_texts(step)
        ]
    return []


# A loyalty ability whose whole effect is a delayed triggered ability created
# on resolution (CR 603.7): "Whenever [one or more] [nontoken] creature(s)
# attack(s) this turn, <effect>." (Basri Ket's −2, Basri, Devoted Paladin's −1.)
# "…**this combat**" (Melee) is the same shape over a shorter window, and
# "attacks and isn't blocked" the same shape over a later moment of the same
# step. Both are payload: the event comes from `_DELAYED_EVENT_PHRASES` and the
# duration from `_DELAYED_DURATIONS`, so neither is a second regex. The event
# alternation is ordered — "attacks and isn't blocked" before the bare
# "attacks" it begins with — for the reason the narrowed pattern below states.
_DELAYED_ATTACK_RE = re.compile(
    r"^whenever (?:(?P<batch>one or more )|an? )?(?P<nontoken>nontoken )?creatures? "
    r"(?P<event>attacks and isn't blocked|attacks?|blocks?) "
    r"(?P<duration>this turn|this combat), (?P<effect>.+)$"
)

#: Which delayed-trigger lifetime each printed window names (CR 603.7b's
#: "stated duration"). Data rather than a branch, so a card printing the other
#: window is a row: `engine/delayed_triggers.py` holds both sweeps.
_DELAYED_DURATIONS: dict[str, str] = {
    "this turn": "end_of_turn",
    "this combat": "end_of_combat",
}

# The same delayed trigger with its duration printed *first* and its subject
# narrowed: "Until end of turn, whenever a creature you control with power 2 or
# less attacks, draw a card." (Subira, Tulzidi Caravanner.) The subject is a
# printed noun phrase, delimited here and read by the noun parser — the
# ``_subject`` convention this file already uses — so a card narrowing by a
# different tribe, keyword or stat needs no code.
_DELAYED_ATTACK_UNTIL_RE = re.compile(
    r"^until end of turn, whenever (?P<attacker_subject>.+?) "
    r"(?P<event>attacks and isn't blocked|attacks"
    r"|deals combat damage to a player), (?P<effect>.+)$"
)

# The same delayed trigger over a **cast** rather than a combat event: "Until
# end of turn, whenever you cast a black spell, put a +1/+1 counter on this
# creature." (Mountain Titan.) Its own row rather than a widened alternation in
# the one above, because the shape is different in the place that matters — the
# noun phrase there describes the *attacking permanent* and here it describes
# the **spell**, which is a card on the stack with no computed characteristics
# at all (CR 613.1). Two objects, two matchers, so two rows.
#
# The phrase is delimited as a `_subject` group and read by the same noun parser
# every other one is, so a card printed "an artifact spell" needs no code.
_DELAYED_CAST_UNTIL_RE = re.compile(
    r"^until end of turn, whenever you cast (?P<cast_subject>an? .+? spell), "
    r"(?P<effect>.+)$"
)


#: Which delayed-trigger event each printed phrase names. A phrase whose event
#: has no fire site has nowhere to be announced, so the clause refuses rather
#: than arming a trigger nothing will ever look at — the dispatcher question
#: round 93 wrote down, asked at the moment the trigger is *created* instead of
#: at the moment it should have fired. Which events *have* a fire site is
#: ``engine/delayed_triggers.DELAYED_EVENTS``, not a second list here.
_DELAYED_EVENT_PHRASES: dict[str, str] = {
    "attack": "creatures_attack",
    "attacks": "creatures_attack",
    # "Whenever a creature **blocks** this turn, …" (Battle Cry). One word of
    # the sentence differs, so it is a row here rather than a second regex —
    # the shape, the duration and the repetition are the attack form's.
    "block": "creature_blocks",
    "blocks": "creature_blocks",
    "deals combat damage to a player": "creature_deals_combat_damage_to_player",
    # "…**attacks and isn't blocked**" (Gaze of Pain). Read before the bare
    # "attacks" it begins with — the alternation in the pattern above is
    # ordered, and the short spelling matching first would leave "and isn't
    # blocked" in front of the comma and fail the line. Which is the safe
    # failure, and is why the ordering is the whole of the difference here.
    "attacks and isn't blocked": "creature_attacks_unblocked",
}


def _parse_delayed_attack_trigger(
    effect_clause: str, card_name: str | None
) -> OracleInstruction | None:
    """The ``create_delayed_trigger`` instruction for a delayed attack-trigger
    clause, or None when the clause is not one — including when its inner
    effect fails to parse, so the card refuses rather than arming a trigger
    that fires into nothing."""
    normalized = normalize_creature_line(effect_clause)
    cast = _DELAYED_CAST_UNTIL_RE.match(normalized)
    if cast is not None:
        from .grammar import subject_filter_payload
        from .subject_filters import card_only_filter

        described = subject_filter_payload(cast.group("cast_subject"))
        # A spell is a card on the stack, so only what is *printed* on it is
        # testable — `card_only_filter` is the list of exactly which keys that
        # comes to, and anything wider refuses rather than arming a trigger that
        # fires on a strictly larger set than the card prints.
        if described is None or card_only_filter(described) is None:
            return None
        inner = _line_instruction(cast.group("effect"), card_name, activated=True)
        if inner is None:
            return None
        return OracleInstruction(
            "create_delayed_trigger",
            "",
            {
                "event": "you_cast_spell",
                "subject_filter": described,
                "instruction": inner[0],
                # "Until end of turn, **whenever** …" — CR 603.7b's stated
                # duration, so it fires every time for as long as it lasts.
                "once": False,
                "duration": "end_of_turn",
            },
        )
    narrowed = _DELAYED_ATTACK_UNTIL_RE.match(normalized)
    if narrowed is not None:
        from .grammar import subject_filter_payload

        described = subject_filter_payload(narrowed.group("attacker_subject"))
        if described is None:
            # A phrase the matcher cannot test would arm a trigger firing on a
            # strictly larger set than the card prints — the same refusal every
            # other narrowed condition makes.
            return None
        inner = _line_instruction(narrowed.group("effect"), card_name, activated=True)
        if inner is None:
            return None
        return OracleInstruction(
            "create_delayed_trigger",
            "",
            {
                "event": _DELAYED_EVENT_PHRASES[narrowed.group("event")],
                "batch": False,
                "nontoken": False,
                "subject_filter": described,
                "instruction": inner[0],
                # "Until end of turn, **whenever** …" — CR 603.7b's "unless
                # it's stated otherwise": this one fires every time its event
                # happens for as long as it lasts.
                "once": False,
                "duration": "end_of_turn",
            },
        )
    match = _DELAYED_ATTACK_RE.match(normalized)
    if match is None:
        return None
    event = _DELAYED_EVENT_PHRASES[match.group("event")]
    batch = bool(match.group("batch"))
    if batch and event != "creatures_attack":
        # "One or more creatures" is CR 508.1's declaration read as one event,
        # which is what the attack fire site announces. The block fire site
        # announces one creature at a time (CR 509.1g), so an entry armed as a
        # batch would fire per blocker with a count nobody set. No card prints
        # it; refusing is what keeps that true rather than assumed.
        return None
    inner = _line_instruction(match.group("effect"), card_name, activated=True)
    if inner is None:
        return None
    return OracleInstruction(
        "create_delayed_trigger",
        "",
        {
            "event": event,
            "batch": batch,
            "nontoken": bool(match.group("nontoken")),
            "instruction": inner[0],
            "once": False,
            "duration": _DELAYED_DURATIONS[match.group("duration")],
        },
    )


def _parse_loyalty_ability(line: str, card_name: str | None) -> ParsedActivatedAbility | None:
    """Parse one loyalty-ability line, or None when *line* is not one.

    The cost half is the loyalty symbol (read by parse_activated_ability_cost);
    the effect half goes to the same front ends every other clause does. The
    effect clause is what is handed over — the grammar has no production for a
    loyalty symbol, and the symbol is a cost, not part of the effect's text.
    """
    if not _LOYALTY_LINE_RE.match(line):
        return None
    cost = parse_activated_ability_cost(line)
    if not cost.is_loyalty:
        return None
    effect_clause = line.split(":", 1)[1].strip()

    # A "whenever … this turn" effect clause creates a delayed trigger on
    # resolution (CR 603.7) — read here rather than by the grammar, whose
    # trigger classification would compile it as an ability of the permanent
    # and execute the inner effect immediately.
    delayed = _parse_delayed_attack_trigger(effect_clause, card_name)
    if delayed is not None:
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=normalize_creature_line(effect_clause),
            supported=True,
            cost=cost,
            effect_kind="activated_delayed_trigger",
            instruction=delayed,
        )
    if normalize_creature_line(effect_clause).startswith("whenever "):
        return ParsedActivatedAbility(
            source_line=line,
            normalized_effect=normalize_creature_line(effect_clause),
            supported=False,
            cost=cost,
            effect_kind="unsupported",
            instruction=None,
        )

    instruction, effect_kind = _reading(
        _line_instruction(effect_clause, card_name, activated=True)
    )
    # An emblem's quoted ability must itself compile (CR 114.3: the emblem has
    # only that ability, so an unreadable one is an emblem that does nothing).
    if instruction is not None:
        for text in _emblem_texts(instruction):
            emblem_name = f"{card_name} Emblem" if card_name else "Emblem"
            compiled = compile_emblem_text(emblem_name, text)
            if not compiled or not all(t.supported for t in compiled):
                return ParsedActivatedAbility(
                    source_line=line,
                    normalized_effect=normalize_creature_line(effect_clause),
                    supported=False,
                    cost=cost,
                    effect_kind="unsupported",
                    instruction=None,
                )
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=normalize_creature_line(effect_clause),
        supported=instruction is not None,
        cost=cost,
        effect_kind=effect_kind if instruction is not None else "unsupported",
        instruction=instruction,
    )


def _parse_planeswalker_program(
    oracle_text: str, card_name: str | None
) -> OracleProgram:
    """Compile a planeswalker's text (CR 306).

    The support gate is **all-of**: every loyalty line, static line and trigger
    line must be readable, or the card is unsupported naming the first clause
    that is not. A planeswalker with one dead ability would otherwise enter
    play offering three abilities and performing two — the Mazemind Tome shape,
    which the hollow-support contract exists to refuse.
    """
    normalized_text = _normalize_text(oracle_text)
    instructions: list[OracleInstruction] = []
    activated: list[ParsedActivatedAbility] = []
    triggered: list[ParsedTriggeredAbility] = []
    static_lines: list[str] = []

    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        ability = _parse_loyalty_ability(line, card_name)
        if ability is not None:
            if not ability.supported:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"planeswalker ability not implemented: {line!r}",
                    normalized_text,
                )
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        static = _planeswalker_static_line(line, card_name)
        if static is not None:
            instructions.append(OracleInstruction("static_line", static))
            static_lines.append(static)
            continue

        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            if not trig.supported:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"planeswalker ability not implemented: {line!r}",
                    normalized_text,
                )
            triggered.append(trig)
            if trig.instruction is not None:
                instructions.append(trig.instruction)
            continue

        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            continue

        return OracleProgram(
            False,
            "unsupported",
            f"planeswalker text too complex: {line!r}",
            normalized_text,
        )

    if not activated:
        # CR 306.5d: each planeswalker has loyalty abilities. Text with none
        # readable is text this parser did not actually understand.
        return OracleProgram(
            False, "unsupported", "no loyalty abilities found", normalized_text
        )

    return OracleProgram(
        True,
        "planeswalker_loyalty",
        "planeswalker support",
        normalized_text,
        tuple(instructions),
        tuple(activated),
        tuple(triggered),
        tuple(static_lines),
    )


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
        # (Leviathan.) A CR 508.1g attack cost, which is a *static* property of
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
    }
)


def _grammar_static_creature_instruction(
    line: str, card_name: str | None = None
) -> OracleInstruction | None:
    """The static contribution the grammar reads out of a creature's line.

    Carrion Grub's "gets +X/+0, where X is the greatest power among creature
    cards in your graveyard" is a layer-7c contribution whose *size* is
    computed, which no text-keyed table can express — the size is the whole
    variable part.
    """
    compiled = compile_grammar_line(normalize_creature_line(line), card_name=card_name)
    if not compiled.usable or len(compiled.instructions) != 1:
        return None
    instruction = compiled.instructions[0]
    return (
        instruction
        if instruction.kind in _GRAMMAR_STATIC_CREATURE_KINDS
        else None
    )


def _restriction_line(line: str, card_name: str | None) -> str:
    """*line* normalized with the card's own name collapsed to "this creature".

    Pre-modern templating — and modern legendary templating — writes the
    subject as the card's name: "**Gadrak** can't attack unless…". The combat
    restriction table is anchored on "this creature", so without this the clause
    matched nothing and the card reported "text too complex" for a template the
    engine implements. The lexer already collapses the same references for the
    grammar (CR 201.4c's short name included); this is that rule on the
    static-line path.

    Scoped to this one consult rather than folded into
    ``normalize_creature_line``, whose output is *stored* on the program as
    ``static_lines`` and matched on by several text-keyed readers — rewriting it
    for every card that names itself is a change with its own blast radius and
    no card asking for it.
    """
    return _collapse_self_references(
        normalize_creature_line(line), card_name, "this creature"
    )


def _is_supported_static_creature_line(line: str, card_name: str | None = None) -> bool:
    if _grammar_static_creature_instruction(line, card_name) is not None:
        return True
    normalized = normalize_creature_line(line)
    if normalized.startswith("protection from "):
        return True
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
    if prevention_claims_line(normalized):
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
        "this creature can block an additional creature each combat",
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
    from .untap_restrictions import self_untap_line

    return self_untap_line(normalized, card_name) is not None


# ---------------------------------------------------------------------------
# Creature program parser
# ---------------------------------------------------------------------------

def _parse_creature_program(
    oracle_text: str,
    card_name: str | None = None,
) -> tuple[bool, str, str, tuple[OracleInstruction, ...], tuple[ParsedActivatedAbility, ...], tuple[ParsedTriggeredAbility, ...], tuple[str, ...]]:
    text = oracle_text.strip()
    if not text:
        return True, "creature_simple", "simple creature support", (), (), (), ()

    instructions: list[OracleInstruction] = []
    activated: list[ParsedActivatedAbility] = []
    triggered: list[ParsedTriggeredAbility] = []
    static_lines: list[str] = []

    lines = text.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        index += 1
        line = raw_line.strip()
        if not line:
            continue

        # 0. Modal triggered ability — a head plus the bullet run below it,
        # consumed together so the bullets never reach the per-line steps
        # (where each would refuse as an orphaned fragment).
        modal_trigger = _modal_trigger_ability(lines, index - 1, card_name)
        if isinstance(modal_trigger, str):
            return False, "unsupported", modal_trigger, (), (), (), ()
        if modal_trigger is not None:
            trig, consumed = modal_trigger
            triggered.append(trig)
            instructions.append(trig.instruction)
            index += consumed
            continue

        # 1. Plain keyword line (e.g. "Flying, Trample")
        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            for trig in keyword_line_triggers(normalized):
                triggered.append(trig)
                instructions.append(trig.instruction)
            continue

        # 1b. An additional cost to cast this spell (CR 601.2b). Not an effect
        # and so not an instruction: it is collected and paid by
        # `queue_from_hand`, which reads the same table this asks. A creature
        # spell prints one as readily as an instant does (Goremand), and
        # without this step the line was the reason the whole card came back
        # "text too complex".
        if cast_cost_claims_line(line):
            continue

        # 1c. An **alternative** cost (CR 118.9) — "You may pay 1 life and exile
        # a blue card from your hand rather than pay this spell's mana cost."
        # The other half of the step above and read the same way, because it is
        # the same kind of sentence: a price, not an effect, collected by
        # `queue_from_hand` from the table this asks. Without this the line was
        # claimed by nothing at all, and Force of Will and Pyrokinesis reported
        # `supported` on their *other* line while the one they are famous for
        # did nothing — the population a refusal census cannot see, because the
        # card is not refused.
        if alternative_cost_claims_line(line):
            continue

        # 2. Triggered ability
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            if trig.supported:
                triggered.append(trig)
                if trig.instruction is not None:
                    instructions.append(trig.instruction)
                continue
            # Trigger condition recognized but effect is unsupported.
            # Before giving up, check if the full line is listed as a supported
            # static pattern (e.g. "at the beginning of your upkeep, unless you
            # pay …" for Demonic Hordes, or "when this creature dies …" for
            # Personal Incarnation).
            if _is_supported_static_creature_line(line):
                normalized = normalize_creature_line(line)
                instructions.append(OracleInstruction("static_line", normalized))
                static_lines.append(normalized)
                continue
            triggered.append(trig)
            continue

        # 3. Activated ability
        ability = _parse_activated_ability(line, card_name)
        if ability is not None and ability.supported:
            activated.append(ability)
            if ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # 4. Static text
        if _is_supported_static_creature_line(line, card_name):
            normalized = normalize_creature_line(line)
            grammar_static = _grammar_static_creature_instruction(line, card_name)
            if grammar_static is not None:
                instructions.append(grammar_static)
                static_lines.append(normalized)
                continue
            # Characteristic-defining P/T (CR 604.3). One instruction kind
            # carrying what to count: these were four branches matching literals
            # that embedded the card's own name, so a reprint or any
            # functionally identical card compiled as unsupported.
            if (dynamic_pt := dynamic_pt_for(normalized)) is not None:
                instructions.append(
                    OracleInstruction(dynamic_pt.kind, "", dynamic_pt.payload)
                )
            elif (bonus := static_bonus_for(_restriction_line(line, card_name))) is not None:
                instructions.append(OracleInstruction(bonus.kind, "", bonus.payload))
            elif (lord := lord_buff_for(normalized)) is not None:
                # The lord line the gate just admitted, carried as data. The
                # consumer used to re-parse `static_line`'s text with two
                # regexes of its own, which is how the gate and the dispatch came
                # to disagree about what "other " meant.
                instructions.append(
                    OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(lord))
                )
            elif (
                restriction := combat_restriction_for(
                    _restriction_line(line, card_name), card_name
                )
            ) is not None:
                # Combat restrictions are templates, derived rather than listed
                # (engine/combat_restrictions.py). The chain that used to sit
                # here matched exact strings and hardcoded Island, so a card
                # naming any other land type fell through to `static_line` and
                # attacked freely while still reporting supported.
                instructions.append(
                    OracleInstruction(restriction.kind, "", restriction.payload)
                )
            else:
                instructions.append(OracleInstruction("static_line", normalized))
            static_lines.append(normalized)
            continue

        # Name the offending line so support_report on a new set pinpoints
        # exactly which clause needs a parse rule.
        return False, "unsupported", f"creature text too complex: {line!r}", (), (), (), ()

    # **Every** trigger, not merely one of them. The gate used to ask whether
    # *any* trigger was supported, so a creature printing two of them shipped
    # as supported with the second one inert — Hazezon Tamar compiled its
    # enters-the-battlefield half, reported "simple creature support", and
    # exiled no Sand Warrior at all when it left, because nothing announced a
    # trigger whose effect had never lowered. No creature in the pool relies
    # on the looser reading; a trigger the engine cannot run is a card the
    # engine cannot play, however many others on it work.
    if any(not trig.supported for trig in triggered):
        return False, "unsupported", "unsupported triggered ability", (), (), tuple(triggered), tuple(static_lines)

    return (
        True,
        "creature_simple",
        "simple creature support",
        tuple(instructions),
        tuple(activated),
        tuple(triggered),
        tuple(static_lines),
    )



def _unread_land_text(
    oracle_text: str,
    card_name: str | None,
    abilities: tuple[Any, ...] = (),
) -> str | None:
    """A land's first printed line that nothing in the engine reads, or None.

    Reminder text (CR 305.6) is dropped first: a basic's whole "ability" is a
    parenthetical, and a dual's is too. What remains is rules text, and a land
    printing rules text no reader claims is a land that taps for mana and does
    nothing else while reporting supported.

    *abilities* are the land's parsed activated and triggered abilities, whose
    printed lines are read by definition and are skipped here. It used to be
    asked only of a land with **no** parsed ability, which is a different
    question and answered a weaker one: a land with an ability was exempt from
    the check entirely, so an unread *static* beside a working ability went
    unreported. Halls of Mist is what showed it — its cumulative upkeep was the
    unread line the old guard caught, and teaching the engine that keyword
    turned the card supported while "Creatures that attacked during their
    controller's last turn can't attack" stayed unimplemented and now invisible.
    A line is claimed or it is not; whether some *other* line on the card parsed
    is not part of that question.
    """
    from .oracle import keyword_line_triggers  # noqa: PLC0415  (self, for clarity)

    ability_lines = {
        re.sub(r"\([^)]*\)", "", ability.source_line or "").strip()
        for ability in abilities
    }
    for raw in (oracle_text or "").splitlines():
        line = re.sub(r"\([^)]*\)", "", raw).strip()
        if not line or line in ability_lines:
            continue
        # A keyword line the CR defines *as* an ability (cumulative upkeep,
        # rampage) is claimed by the rewrite that turns it into one, and reaches
        # here only when the rewrite refused it — a cost this engine cannot
        # charge. Then it is genuinely unread and naming it is the point.
        if keyword_line_triggers(normalize_creature_line(line)):
            continue
        # …and a plain keyword line, which a land can print too: Teferi's Isle
        # has phasing (CR 702.26). The creature front end classifies these and
        # this one did not, so a land whose only extra text is a keyword the
        # engine implements was reported as carrying an unread static. Through
        # the same `IMPLEMENTED_KEYWORDS` reader the creature gate uses, so what
        # is admitted here and what is admitted there cannot drift.
        if _is_supported_keyword_line(line):
            continue
        # Through the same collapse every other static reader uses: a land that
        # names itself ("Tapped Land enters tapped") is saying "this permanent",
        # and a reader anchored on the self-reference sees nothing otherwise.
        # That mismatch between a gate and a runtime reader is the bug round 18
        # found on Bartel Runeaxe, and this is the same one line lower.
        collapsed = _restriction_line(line, card_name)
        if _is_supported_static_creature_line(line, card_name):
            continue
        # The **raw** line and the card's name, never the pre-collapsed one:
        # `enter_effect_line` runs `_self_normalized` itself, and handing it a
        # line whose self-references are already rewritten costs it the printed
        # text. Sheltered Valley is what showed the difference — "each other
        # permanent **named Sheltered Valley** you control" arrives here as
        # "named this creature", so the reader that claims the line and the
        # reader that carries it out were looking at two different cards, which
        # is the exact mismatch `_self_normalized`'s own docstring warns about.
        if enter_effect_line(line, card_name) is not None:
            continue
        if _derived_static_claims(collapsed, collapsed, card_name):
            continue
        if any(pattern in collapsed for pattern in SUPPORTED_SPELL_PATTERNS):
            continue
        return line
    return None


def _parse_noncreature_abilities(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedActivatedAbility, ...]:
    abilities: list[ParsedActivatedAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line or ":" not in line:
            continue
        ability = _parse_activated_ability(line, card_name)
        if ability is not None:
            abilities.append(ability)
    return tuple(abilities)


def keyword_line_triggers(normalized_line: str) -> tuple[ParsedTriggeredAbility, ...]:
    """The triggered abilities a *keyword line* is, for every keyword whose
    rules text the CR defines as one.

    Three today — rampage (CR 702.23a), cumulative upkeep (CR 702.24a) and
    flanking (CR 702.25a) — and all are the rewrite ``engine/equipment.py``
    established for equip, one layer earlier because the grammar has no
    production for "for each creature blocking it beyond the first", for an
    escalating upkeep, or for a sentence no card outside a reminder prints.
    From here the ordinary dispatchers fire them: the becomes-blocked step and
    the upkeep step, neither of which knows the word.

    **One reader because there are two front ends.** A creature's lines and a
    non-creature permanent's are parsed by different loops, and cumulative
    upkeep was added to the creature loop alone: the six Ice Age enchantments
    that print it alongside another ability compiled *supported* with the
    keyword silently dropped, which is strictly worse than not implementing it
    — the card reads as done and plays as a better card than the one printed.
    A keyword rewrite belongs to a line rather than to a card type, so both
    loops ask here.
    """
    return (
        *rampage_triggers(normalized_line),
        *cumulative_upkeep_triggers(normalized_line),
        *flanking_triggers(normalized_line),
    )


def _parse_noncreature_triggered(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedTriggeredAbility, ...]:
    """Extract triggered abilities from non-creature oracle text.

    A **modal** trigger is a head plus the bullet run below it, consumed
    together exactly as ``_parse_creature_program`` consumes one. Reading this
    side line by line was not a missing feature but a disagreement: the Aura
    support gate asks ``_modal_trigger_ability`` whether the whole run is
    carried out, and this loop then produced an *unsupported* trigger for the
    head alone with no instruction behind it — a card admitted by one front end
    and left inert by the other. Relic Bind is the card that showed it.
    """
    abilities: list[ParsedTriggeredAbility] = []
    lines = oracle_text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        modal = _modal_trigger_ability(lines, index, card_name)
        if isinstance(modal, tuple):
            trig, consumed = modal
            abilities.append(trig)
            index += 1 + consumed
            continue
        if isinstance(modal, str):
            # A recognized modal head the engine cannot carry out. Recorded as
            # an unsupported ability rather than dropped, so the "every trigger
            # is unsupported" gate below sees the card the way the Aura gate
            # does instead of finding no trigger at all.
            abilities.append(ParsedTriggeredAbility(
                source_line=line,
                condition=TriggerCondition(kind="unsupported", trigger="when", raw_text=line),
                instruction=None,
                supported=False,
                effect_kind="unsupported",
            ))
            index += 1
            continue
        index += 1
        if not line:
            continue
        # A keyword line the CR defines *as* a triggered ability, read on this
        # side too — see `keyword_line_triggers` for why both loops ask.
        keyword_triggers = keyword_line_triggers(normalize_creature_line(line))
        if keyword_triggers:
            abilities.extend(keyword_triggers)
            continue
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            abilities.append(trig)
    return tuple(abilities)


def _by_source_line(abilities) -> dict[str, list]:
    """Parsed abilities grouped by the line they came from, in printed order.

    A list per line rather than one entry: a card may print the same line twice,
    and the assembly below consumes them in order so the second occurrence is
    not silently the first one again.
    """
    grouped: dict[str, list] = {}
    for ability in abilities:
        grouped.setdefault(ability.source_line, []).append(ability)
    return grouped


def _noncreature_line_instructions(
    oracle_text: str,
    card_name: str | None,
    activated: tuple[ParsedActivatedAbility, ...],
    triggered: tuple[ParsedTriggeredAbility, ...],
    *,
    whole_card: bool,
) -> list[OracleInstruction]:
    """The card-level instruction each line of a noncreature card contributes,
    in printed order.

    Assembled from the reading the compiler has *already* produced for that
    line. The legacy fallback this replaced collapsed the card's entire text to
    one string and kept the first rule that matched it, so an artifact whose
    activated ability the grammar reads in full still had its card-level
    instruction produced by re-reading the whole card — two front ends answering
    the same question about the same line, and only one of them per line. That
    whole-text pass is gone with the registry; a line nothing claims now
    contributes nothing, rather than borrowing a sentence from elsewhere on the
    card.

    Reusing the ability parse rather than re-running the grammar is what keeps
    the assembly per line, so a production claiming one line cannot delete the
    reading of any other.

    *whole_card* tells the list's two meanings apart. For an instant or sorcery
    it is the program that *resolves* — the stack runs every
    non-``spell_pattern`` instruction in it, in printed order, fused into one
    ``sequence`` by ``_select_executable_instruction`` — so only plain effect
    lines belong in it.
    For a permanent it is a mirror of everything the card does, scanned by kind
    by the layer bridge, the upkeep pass and the AI: the same mirror
    ``_parse_creature_program`` has always built for creatures, and which
    ``engine/ai_valuation.py``'s ``SPELL_TYPES`` gate already documents. A
    permanent's abilities keep their own entries in ``activated_abilities`` and
    ``triggered_abilities``; nothing resolves this list on its own.
    """
    acts = _by_source_line(activated) if whole_card else {}
    trigs = _by_source_line(triggered) if whole_card else {}

    instructions: list[OracleInstruction] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        # Modal bullets are alternatives collected into `modes`, not effects the
        # card performs. Letting one into the top-level list would make a
        # "Choose one" spell always resolve whichever bullet was claimed.
        if not line or line.startswith("•"):
            continue

        found = _line_instruction(line, card_name, spell_line_only=True)
        if found is not None:
            instructions.append(found[0])
            continue
        # "Whenever a creature blocks this turn, it gets +0/+1 until end of
        # turn." (Battle Cry.) A spell whose own line creates a delayed
        # triggered ability (CR 603.7) — the same clause Basri Ket's loyalty
        # ability and Subira's activated one print, and the same table, asked
        # here so the shape has one home. Read after the grammar and before the
        # ability lookup, which is where a spell's plain effect lines are read.
        #
        # Without it the sentence was claimed by nothing: the card was
        # `supported` on its *first* line and the second one silently did
        # nothing, which is what `parse_coverage.py` reports and what a
        # promotion gates on.
        delayed = _parse_delayed_attack_trigger(line, card_name)
        if delayed is not None:
            instructions.append(delayed)
            continue
        if not whole_card:
            continue

        # An ability line: take the instruction its own parse produced.
        ability = None
        for group in (trigs, acts):
            pending = group.get(line)
            if pending:
                ability = pending.pop(0)
                break
        if ability is not None:
            if ability.supported and ability.instruction is not None:
                instructions.append(ability.instruction)
            continue

        # Neither — a static ability ("Black creatures get +1/+1."), or a
        # triggered one whose condition the trigger table refuses (Cursed Land).
        # Its instruction used to arrive from the whole-text parse or from
        # parse_static_coeffects re-reading the card; it comes from this line
        # or from nowhere.
        static = _line_instruction(line, card_name)
        if static is not None:
            instructions.append(static[0])
            continue
        # A combat restriction printed on a noncreature permanent ("Creatures
        # without flying can't attack.", Moat; Arboria's whole card). The same
        # table the creature path consults, asked through the same
        # name-substituting reader, and emitting the same instruction — so the
        # enforcement site's board scan in `can_attack` reads a Moat and an
        # Evil Eye identically, and the gate and the dispatch stay one table.
        restriction = combat_restriction_for(
            _restriction_line(line, card_name), card_name
        )
        if restriction is not None:
            instructions.append(
                OracleInstruction(restriction.kind, "", restriction.payload)
            )
    return instructions


# ---------------------------------------------------------------------------
# Top-level compiler
# ---------------------------------------------------------------------------

def expand_modal_activated_lines(oracle_text: str) -> str:
    """Rewrite '{cost}: Choose one —' + bullets into one ability line per
    bullet. Text without that shape is returned unchanged. Shared with
    engine.legality so target classification sees the same lines.

    A modal ACTIVATED ability ("{2}: Choose one —" followed by bullet lines,
    e.g. Pyramids) becomes one plain activated-ability line per bullet, same
    cost, so the existing multi-ability machinery (ability_index choice,
    per-ability targeting) covers it — and so the bullets are never mistaken for
    cast-time modes or top-level spell effects.

    Whether a line *is* such a head is the grammar's answer
    (:func:`_modal_head`), not a regex's. The regex it replaced admitted mana
    symbols only, so "Sacrifice a creature: Choose one —" would have been left
    on the floor, and it hard-coded "choose one" so no other count could ever be
    read — while the grammar refuses a count the engine cannot carry out and
    that refusal reaches here as a head this declines to expand. Only the cost
    is still taken from the raw text, because this rewrites text: re-rendering a
    parsed cost would be a second spelling of it, free to differ from the one
    ``mixins/stack/activation.py`` charges.
    """
    if "choose" not in (oracle_text or "").lower():
        return oracle_text
    lines = (oracle_text or "").splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # ":" and "choose" are both necessary for the grammar to read the line
        # as an activated modal head, so testing them first only skips work.
        if ":" in line and "choose" in line.lower() and (
            _modal_head(line, grammar_ast.ActivatedAbilityNode) is not None
        ):
            bullets = _bullets_after(lines, i)
            if bullets:
                cost, _, effect = line.partition(":")
                cost = cost.strip()
                # Whatever the head line printed *after* "Choose one." rides on
                # to every expanded ability — "Activate only if there are two or
                # more hatchling counters on this artifact." (Triassic Egg). The
                # restriction is enforced off ``source_line``, so a rewrite that
                # dropped it would turn a gated ability into a free one, on
                # every mode at once. Taken from the raw text for the same
                # reason the cost is: re-rendering it would be a second
                # spelling, free to differ from the one the restriction table
                # matches.
                head, _, tail = effect.partition(".")
                tail = tail.strip()
                out.extend(
                    f"{cost}: {bullet}" + (f" {tail}" if tail else "")
                    for bullet in bullets
                )
                i += 1 + len(bullets)
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


#: "At the beginning of your upkeep **and** whenever enchanted land becomes
#: tapped, remove an ore counter from this Aura." (Orcish Mine.) CR 603.1 lets
#: one triggered ability name several trigger events; the printed shape is two
#: conditions joined by "and", one comma, then the effect they share.
#:
#: Neither condition may contain a comma, which is what pins the shape: the
#: single comma in the line is the boundary between the conditions and the
#: effect. Chaos Moon prints "…red creatures get +1/+1 **and whenever** a player
#: taps a Mountain for mana, that player adds…" and is *not* this shape — its
#: first clause ends in a comma long before the joining word, so the pattern
#: cannot reach across it.
_CONJOINED_TRIGGER_LINE = re.compile(
    r"^(?P<first>(?:at|whenever|when) [^,]+?)"
    r" and (?P<second>(?:at|whenever|when) [^,]+?), (?P<effect>.+)$",
    re.IGNORECASE,
)


def expand_conjoined_trigger_lines(oracle_text: str) -> str:
    """*oracle_text* with a two-condition trigger line rewritten as two lines.

    "At the beginning of your upkeep and whenever enchanted land becomes tapped,
    remove an ore counter from this Aura" is one ability with two trigger events
    (CR 603.1), and it triggers on each of them — which is behaviourally what
    two abilities with one event each and the same effect do. Rewriting it here
    is the ``expand_equip_lines`` move: from this point on the grammar, the
    condition table, the Aura gate, the parse-coverage census and the hook
    census all read two ordinary trigger lines that already work, and none of
    them learns a second shape.

    A representation instead — a list of conditions on ``ParsedTriggeredAbility``
    — would have to be taught to every fire site in the engine, each of which
    matches on one condition kind.

    The safety here is the full-consumption invariant, not this function's
    judgement: a split that produced a sentence the grammar cannot read leaves
    the card unsupported naming the line, which is the loud direction. What it
    must never do is *quietly* rewrite a line that was not this shape, which is
    why both conditions are comma-free and the joining word must begin a trigger
    word rather than merely appear.
    """
    if not oracle_text or " and " not in oracle_text:
        return oracle_text
    out: list[str] = []
    for line in oracle_text.splitlines():
        match = _CONJOINED_TRIGGER_LINE.match(line.strip())
        if match is None:
            out.append(line)
            continue
        effect = match.group("effect")
        second = match.group("second")
        out.append(f"{match.group('first')}, {effect}")
        out.append(f"{second[:1].upper()}{second[1:]}, {effect}")
    return "\n".join(out)


def _printed_line_for(expanded_line: str | None, printed_text: str) -> str:
    """The printed line *expanded_line* was rewritten from, or the line itself.

    An ability's ``source_line`` is the text the compiler read, which for an
    equip keyword is the CR 702.6a expansion rather than "Equip {1}". The
    Equipment gate asks which of a card's abilities *is* its equip ability, and
    the honest way to answer is to walk the printed lines through the same
    rewrite and compare — not to pattern-match the expansion's English.
    """
    if expanded_line is None:
        return ""
    wanted = expanded_line.strip()
    for line in (printed_text or "").split("\n"):
        if (expand_equip_lines(line) or "").strip() == wanted:
            return line
    return expanded_line


def expand_ability_lines(
    oracle_text: str, *, card_name: str | None = None, legendary: bool = False
) -> str:
    """Every rewrite the compiler applies to a card's text before a single line
    is classified — and therefore the text every *other* reader of a card's
    lines must start from (``engine/legality.py``, ``scripts/parse_coverage.py``,
    ``scripts/hook_reliance.py``), or it is reading a different card.

    Two rewrites today, both of them the rules' own:

    * a modal activated head and its bullets become one ability line per
      bullet (:func:`expand_modal_activated_lines`);
    * an equip keyword line becomes the activated ability CR 702.6a says it
      *means* — "[Cost]: Attach this permanent to target creature you control.
      Activate only as a sorcery." (``engine/equipment.py``). From there it is
      an ordinary activated ability to the grammar, the cost parser, the timing
      table and the target picker, none of which know the word.

    And one rewrite that is the *card's* rather than the rules': a legendary
    card's shortened self-reference written out in full
    (``engine/self_reference.py``). It belongs in this pass for exactly the
    reason the other two do — every reader of a card's lines has to see the same
    sentence, and the readers that see only the compiler's stored text have no
    name to shorten *with*. A caller that names no card gets the text unchanged,
    which is what every reader asking about a line rather than a card wants.
    """
    from .self_reference import expand_short_self_references

    oracle_text = expand_short_self_references(
        oracle_text, card_name, legendary=legendary
    )
    return expand_conjoined_trigger_lines(
        expand_equip_lines(expand_modal_activated_lines(oracle_text))
    )

def expand_card_lines(card) -> list[str]:
    """*card*'s printed lines after every rewrite :func:`expand_ability_lines`
    applies, as a list.

    The convenience the rule "every other reader of a card's lines must start
    from that same function" needs to be cheap to obey. A reader holding the
    card has no excuse to split ``oracle_text`` itself, and the one that did —
    the entry state — was reading a legendary card's shortened self-reference
    that the gate above it had already written out, so the card compiled
    supported and then entered with nothing on it.
    """
    return expand_ability_lines(
        card.oracle_text or "", card_name=card.name, legendary=card.is_legendary
    ).splitlines()


# Layouts the compiler can read straight from the top-level characteristics.
# Every other layout (split, flip, transform, modal_dfc, adventure, meld, …)
# leaves mana_cost and oracle_text empty and puts the real text in card_faces,
# so compiling one as-is would classify it a supported vanilla — a silently
# wrong answer rather than an error. Face-aware compilation is roadmap phase 3;
# until then these are explicitly unsupported.
SUPPORTED_LAYOUTS = frozenset({
    "normal", "leveler", "class", "saga", "case", "planar", "scheme", "vanguard", "token",
})


# ---------------------------------------------------------------------------
# Support derived from the text-keyed rule tables
# ---------------------------------------------------------------------------

def _activation_restrictions_readable(
    oracle_text: str, card_name: str | None = None
) -> bool:
    """Whether this card prints an "Activate only …" clause and every one of
    them is a restriction the engine enforces.

    False for a card printing none, so the claim is only made where there is
    something to claim; False also for a card printing one the table cannot
    read, which is what makes it a *gate* rather than a rubber stamp.
    """
    from .activation_restrictions import _clauses, unreadable_activation_clauses

    if not _clauses(oracle_text or "", card_name):
        return False
    return not unreadable_activation_clauses(oracle_text or "", card_name)


def _derived_static_claims(
    oracle_text: str, normalized_text: str, card_name: str | None = None
) -> list[str]:
    """Names of the rule tables that already implement this card's text.

    These tables (untap_restrictions, draw_step_modifiers, cost_modifiers,
    enter_effects) read a permanent's oracle text directly at the step that
    needs them, so they need no instruction to *work*. They were nonetheless
    absent from the support gate, which listed the same behaviours as whitelist
    literals with the table's parameters baked in — "creatures with power **3**
    or greater don't untap", "players can't untap more than **one** creature".

    That is the false-negative half of the gate/dispatch split: a card printed
    "power 4 or greater" was enforced correctly by the table and reported
    **unsupported**, because the literal named a different number. Deriving
    support from the tables that do the work means the parameter is data here
    too.
    """
    from .card_hooks import DRAW_STEP_MODIFIERS
    from .cost_modifiers import cost_modifier_claims_line
    from .cost_x_definitions import cast_x_ceiling_line, cast_x_definition_line
    from .damage_source_colors import CLAIM as DAMAGE_SOURCE_COLORS_CLAIM
    from .damage_source_colors import colorless_source_line
    from .draw_step_modifiers import (draw_step_bonus_for, draw_step_skip_for,
                                      skips_own_draw_step)
    from .enter_effects import enter_effect_line
    from .evasion_negation import negated_evasion_abilities
    from .extra_triggers import extra_triggers_for
    from .global_statics import global_static_for
    from .land_play_allowance import land_play_allowance_for
    from .life_prohibitions import life_gain_ban_line
    from .mana_spending import spending_permission_line
    from .prevention import prevention_claims_line
    from .regeneration import denies_regeneration_line, self_regeneration_line
    from .replacements import replacement_claims_line
    from .revealed_hands import revealed_hands_line
    from .target_immunity import CLAIM as TARGET_IMMUNITY_CLAIM
    from .target_immunity import immunity_claims_line
    from .untap_restrictions import untap_restriction_for

    claims: list[str] = []
    if untap_restriction_for(oracle_text) is not None:
        claims.append("untap_restrictions")
    # Extra land plays (Fastbond). The land-drop path derives the allowance from
    # the permanent's own text, so the gate has to ask the same table — a
    # wording the table cannot read must make the card unsupported rather than
    # supported-with-the-permission-missing, which is what the name-keyed count
    # this replaced produced.
    if land_play_allowance_for(oracle_text) is not None:
        claims.append("land_play_allowance")
    # CR 602.5 activation restrictions ("Activate only if a creature died this
    # turn"). The activation path reads the same table, so a clause it cannot
    # read is a card the gate must refuse rather than admit with the restriction
    # unenforced — the direction this whole arrangement exists to prevent.
    if _activation_restrictions_readable(oracle_text, card_name):
        claims.append("activation_restrictions")
    # "Activated abilities of creatures can't be activated." (Cursed Totem.)
    # The *board* half of CR 602.5, and the same shape as the two claims below
    # it: the activation path reads the sentence off the board at every
    # activation, so there is no instruction to produce — and on an artifact
    # whose whole text is this line, no instruction means the card reports
    # unsupported however well the ban works.
    from .activation_restrictions import global_activation_ban_line

    # Its **own** claim name, not "activation_restrictions": that one says
    # *when* an ability of this card may be activated, which
    # `_carries_no_behaviour` reads — rightly — as a clause about an ability
    # rather than as something the permanent does. This sentence is the
    # opposite: it is the whole of what Cursed Totem does, and it is about
    # everybody else's abilities.
    if any(
        global_activation_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("global_activation_ban")
    # "Players can't gain life." (Forsaken Wastes, CR 119.7.) The life-gain seam
    # asks this same table on every gain, so there is no instruction to produce
    # — and a permanent whose whole text is the sentence would report
    # unsupported however well the ban works. Its own claim name for the reason
    # the ban above has one: it is what the permanent *does*, and it is about
    # everybody else's life totals.
    if any(
        life_gain_ban_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("life_prohibitions")
    # CR 603.2d extra triggers (Sanctum of All). The fire site reads the
    # permanent's own text, so there is no instruction — and without this claim
    # the card would be admitted with the sentence doing nothing, which for a
    # *static* line on an enchantment is a silence the line-by-line assembly
    # cannot see: it produces no instruction and raises nothing.
    if extra_triggers_for(oracle_text) is not None:
        claims.append("extra_triggers")
    # A board-wide static (Titania's Song, Energy Flux) contributes its effects
    # through the CR 613 layer bridge and, for a granted ability, through the
    # affected permanent's effective card — so there is no instruction to
    # produce, and without this the source card would report unsupported while
    # working perfectly.
    if global_static_for(oracle_text) is not None:
        claims.append("global_statics")
    # An Aura this module implements in full. Its ``Enchant <subject>`` line is
    # a keyword ability (CR 702.5) that produces no instruction and its effects
    # are continuous, derived from the attachment — so without this the card had
    # no evidence of support at all, and the gate took it from the substring
    # "enchant creature". Asked of the same reader that *refuses* an
    # unimplemented Aura, so the approval and the refusal cannot drift apart.
    if aura_claim(
        [normalize_creature_line(line) for line in (oracle_text or "").split("\n")],
        card_name or "",
    ) is not None:
        claims.append("auras")
    # CR 113.6b: a static ability that functions while the card is a **spell on
    # the stack** (Kaervek's Torch's tax on spells that target it, the ability
    # Torrent of Lava grants each creature). Its behaviour is a cost table and
    # the affected permanents' effective cards, so there is no instruction to
    # produce — and both cards print it beside a damage line that compiles, so
    # without this claim each reported supported doing half of what it prints.
    from .stack_statics import stack_static_claims_line

    if any(
        stack_static_claims_line(line, card_name)
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("stack_statics")
    # CR 106.6 spending permissions ("You may spend white mana as though it were
    # mana of any color"). The payment paths read the seat's derived permission
    # list at the moment a cost is paid, so there is no instruction -- and on an
    # enchantment carrying this line beside two others, no instruction means one
    # third of the card reports as done by the other two. Celestial Dawn is
    # exactly that card: with only its land-type line implemented it compiled
    # green and printed three sentences.
    if spending_permission_line(oracle_text) is not None:
        claims.append("mana_spending")
    # "Creatures with mountainwalk can be blocked as though they didn't have
    # mountainwalk." (Crevasse and its four siblings.) The blockers step reads
    # the permanent's own text, so there is no instruction — and on an
    # enchantment whose *whole* text is this sentence, no instruction means the
    # card reports unsupported however well the effect works.
    if negated_evasion_abilities(oracle_text):
        claims.append("evasion_negation")
    # "Black and/or red permanents and spells are colorless sources of damage."
    # (Ghostly Flame.) The damage paths ask the board for this at the moment a
    # source's colour matters (CR 609.7b), so there is no instruction — and on
    # an enchantment whose whole text is the sentence, no instruction means the
    # card reports unsupported however well the rewrite works.
    if any(
        colorless_source_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append(DAMAGE_SOURCE_COLORS_CLAIM)
    # "X is the number of … as you cast this spell." (Spoils of War, CR 107.3c.)
    # The cast path computes it before the caster is asked, so there is no
    # instruction — and a definition no row reads must make the card unsupported
    # rather than leave the caster announcing X freely.
    if any(
        cast_x_definition_line(line) for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_x_definitions")
    # "X can't be greater than the number of snow lands you control."
    # (Winter's Chill, CR 601.2b.) The bound half of the same rule: the caster
    # still announces X and the cast path refuses one above the board's number,
    # so there is no instruction — and a bound no row can count must make the
    # card unsupported rather than leave the announcement unbounded.
    if any(
        cast_x_ceiling_line(line) is not None
        for line in (oracle_text or "").splitlines()
    ):
        claims.append("cast_x_definitions")
    if draw_step_bonus_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
    # "Skip your draw step." (Necropotence.) The draw step reads the
    # permanent's own text, so there is no instruction — and on an enchantment
    # whose other two lines are a trigger and an activated ability, no claim
    # here would leave this one silently unread.
    if skips_own_draw_step(oracle_text):
        claims.append("draw_step_modifiers")
    # "<permanent> can't be the target of Aura spells" (Bartel Runeaxe, Tetsuo
    # Umezawa). `_can_be_targeted` reads the permanent's own text at the moment
    # a target is chosen, so there is no instruction — and on a creature whose
    # only non-keyword line is this sentence, no instruction would mean the card
    # reports unsupported however well the protection works.
    if any(immunity_claims_line(line) for line in oracle_text.splitlines()):
        claims.append(TARGET_IMMUNITY_CLAIM)
    # "Players play with their hands revealed." (Revelation.) The per-seat
    # state payload derives who may see whose hand from the permanent's own
    # text (engine/revealed_hands.py), so there is no instruction — and on an
    # enchantment whose whole text is the sentence, no instruction would mean
    # the card reports unsupported however well the reveal works. The
    # library-top twin (Field of Dreams) is the `library_top` claim below.
    if any(revealed_hands_line(line) for line in oracle_text.splitlines()):
        claims.append("revealed_hands")
    # "If this creature would be destroyed, regenerate it." (Clergy of the Holy
    # Nimbus.) CR 701.19b's static form: both destruction paths derive it from
    # the permanent's own text through `engine/regeneration.py`, so there is no
    # instruction — and on a creature whose only line is this sentence, no
    # instruction would mean the card reports unsupported however well the
    # replacement works. Asked of the same reader that performs it.
    # "Creatures dealt damage by this creature this turn can't be regenerated
    # this turn." (Bone Shaman grants it.) The dealer-side twin, claimed beside
    # its neighbour because it is the same arrangement: the damage seam derives
    # it from the permanent's own text, so there is no instruction, and without
    # this the sentence would be admitted by nothing — which for a *granted*
    # ability means the grant itself refuses, since the probe compiles the
    # quoted sentence as a card of its own.
    if any(
        self_regeneration_line(line) or denies_regeneration_line(line)
        for line in oracle_text.splitlines()
    ):
        claims.append("regeneration")
    # The *name-keyed* half of the same CR 504 story (Island Sanctuary's
    # skip-your-draw-for-protection), registered in card_hooks and carried out by
    # phases/draw_step.py, phases/declare_attackers_step.py and
    # phases/untap_step.py. It has no instruction either, and until this claim it
    # had no support of its own: the card was held up by a `spell_pattern` marker
    # the whole-text fallback produced from the words "draw a card" inside a
    # sentence about *skipping* one. Deleting that fallback is what exposed it —
    # tests/engine/test_derived_support.py named the card immediately.
    if card_name in DRAW_STEP_MODIFIERS:
        claims.append("draw_step_modifiers")
    # "If you would begin your draw step, you may skip that step instead. If you
    # do, you gain 2 life." (Fasting.) The text-keyed twin of the hook above,
    # asked of the whole card because the template is two sentences: the skip
    # and the rider it buys. `draw_step_skip_for` returns None for a rider
    # phases/draw_step.py cannot carry out, so a card printing an unreadable one
    # is reported unsupported naming the clause rather than skipping its step
    # and forgetting what the skip was for.
    if draw_step_skip_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
    if any(
        cost_modifier_claims_line(normalize_creature_line(line))
        for line in oracle_text.splitlines()
    ):
        claims.append("cost_modifiers")
    # The whole entry-state registry, not two of its constants: every phrase in
    # engine/enter_effects.py is implemented by _initialize_permanent_state, so
    # naming a subset here is the same partial-list mistake one level down.
    if any(
        enter_effect_line(line, card_name) for line in oracle_text.splitlines()
    ):
        claims.append("enter_effects")
    from .named_counters import CAP_CLAIM, counter_cap_line

    if any(
        counter_cap_line(line, card_name) for line in oracle_text.splitlines()
    ):
        claims.append(CAP_CLAIM)
    # CR 614 replacement interceptors — **the seventh table, and the one this
    # list did not ask.** An interceptor self-selects off the card's own text at
    # the event it modifies, so like the six above it needs no instruction to
    # work; unlike them it was not a claim, so a permanent whose *only* ability
    # is a replacement reported unsupported however well the interceptor ran.
    # Every such card in the pool happened to print a second readable line
    # (Lich, Ali from Cairo, Library of Leng, Conclave Mentor), which is why the
    # gap waited for a card whose whole text is one replacement.
    if any(replacement_claims_line(line) for line in oracle_text.splitlines()):
        claims.append("replacements")
    # CR 615's half of the same story: a permanent's *static* prevention (Nine
    # Lives) applies from its own text at damage time and produces no
    # instruction either. Asked as the registry, for the reason the line above
    # gives — a literal copied here could claim a wording nothing intercepts.
    if any(prevention_claims_line(line) for line in oracle_text.splitlines()):
        claims.append("prevention")
    # "You have protection from the chosen card name." (Runed Halo.) A player's
    # protection, derived from the controlling permanents' own text at each of
    # the three places CR 702.16i names — so like every table above it needs no
    # instruction, and like every table above the gate has to ask it or the card
    # reports supported with the line unaccounted for.
    from .named_protection import named_protection_line

    if any(named_protection_line(line) for line in oracle_text.splitlines()):
        claims.append("named_protection")
    from .library_top import library_top_line

    if any(library_top_line(line) for line in oracle_text.splitlines()):
        claims.append("library_top")
    return claims


def _effect_handler_kinds() -> frozenset[str]:
    """Instruction kinds with a registered handler.

    Imported lazily and cached: ``engine.handlers`` imports the compiler, so a
    module-level import here would be a cycle.
    """
    global _EFFECT_HANDLER_KINDS
    if _EFFECT_HANDLER_KINDS is None:
        from .handlers import EFFECT_HANDLERS

        _EFFECT_HANDLER_KINDS = frozenset(EFFECT_HANDLERS)
    return _EFFECT_HANDLER_KINDS


_EFFECT_HANDLER_KINDS: frozenset[str] | None = None


def _carries_no_behaviour(instruction: OracleInstruction) -> bool:
    """Whether this card-level instruction is evidence the permanent does
    *nothing* on its own.

    ``spell_pattern`` is the whitelist marker the gate above was written for: it
    records that a substring matched and carries no behaviour at all.

    A ``derived_static_rule`` normally is behaviour — Howling Mine's draw-step
    modifier, Winter Orb's untap restriction, Gloom's cost tax — and thirty
    shipped cards have nothing else. **One claim is the exception**, and it is
    not a special case so much as the same rule read carefully: an
    ``activation_restrictions`` claim says *when an ability may be activated*,
    so it is a clause of that ability rather than something the permanent does.
    When no ability of the card is readable, the restriction is a rule about
    nothing. Amulet of Quoz was reported supported on exactly that evidence,
    with its whole card in one unreadable ability.
    """
    if instruction.kind == "spell_pattern":
        return True
    return (
        instruction.kind == "derived_static_rule"
        and instruction.value == "activation_restrictions"
    )


# Unbounded cache: card definitions are immutable and the pool is finite, so
# every distinct card compiles exactly once per process — even with thousands
# of cards the programs are tiny compared to recompilation cost.
@compilation_cache
@lru_cache(maxsize=None)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
    layout: str = "normal",
    legendary: bool = False,
) -> OracleProgram:
    # Pyramids-style "{cost}: Choose one —" + bullets become one activated
    # ability per bullet, and an equip keyword line becomes the activated
    # ability CR 702.6a defines it as, before any other classification runs.
    # `printed_text` is kept for the one question that is about the card as
    # printed — does it carry an equip line at all (the Equipment gate below).
    printed_text = oracle_text
    oracle_text = expand_ability_lines(
        oracle_text, card_name=name, legendary=legendary
    )
    normalized_text = _normalize_text(oracle_text)

    if layout not in SUPPORTED_LAYOUTS:
        return OracleProgram(
            False, "unsupported", f"unsupported card layout: {layout}", normalized_text
        )

    if any(keyword in keywords for keyword in UNSUPPORTED_KEYWORDS):
        return OracleProgram(False, "unsupported", "unsupported keyword", normalized_text)

    if any(pattern in normalized_text for pattern in UNSUPPORTED_PATTERNS):
        return OracleProgram(False, "unsupported", "complex oracle pattern", normalized_text)

    if primary_type == "land":
        # Mana production is driven by CardDefinition.produced_mana, not by
        # parsing oracle text (basic lands' whole ability line is reminder
        # text in parens, e.g. "({T}: Add {W}.)", which normalize_creature_line
        # strips to nothing). A land is therefore at least playable whatever
        # its text does — unlike creatures/artifacts, an unparsed *bonus*
        # ability degrades just that ability, never the land's own castability.
        # Non-reminder-text ability lines (Desert's damage ping, Bazaar of
        # Baghdad's draw-discard, …) are parsed the same way artifacts' are, so
        # lands with abilities beyond mana become activatable too.
        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)

        # **The distinction the paragraph above draws, actually drawn.** The
        # rule is about a *bonus* ability, and for a long time the code did not
        # separate one from a land whose unreadable line is the whole card:
        # every land was passed. Antiquities is where that stopped being
        # theoretical. Urza's Mine, Power Plant and Tower each print one line,
        # that line is the entire card, none of them parsed — and all three
        # reported supported, tapped for the flat {C} that `produced_mana`
        # records, and could never assemble. Mishra's Workshop is the one that
        # hides best: nothing about it looks broken, it just taps for one {C}
        # where the card prints three and spends it on anything.
        #
        # So a land that prints abilities and can read *none* of them is
        # unsupported, naming the clause — the same property the artifact and
        # enchantment gate below asks, for the same reason. A land with some
        # readable ability keeps its support and is degraded by whatever it
        # could not read, which is the documented rule and is what the coverage
        # instruments are for (Mishra's Factory taps and pumps; only its
        # animation is unread).
        #
        # A land with no printed ability at all — a basic, a dual, anything
        # whose whole text is CR 305.6 reminder text — has nothing to fail on
        # and is passed by the `abilities` check, not by an exception to it.
        abilities = (*activated_abilities, *triggered_abilities)
        if abilities and not any(
            ability.supported and ability.instruction is not None
            for ability in abilities
        ):
            return OracleProgram(
                False,
                "unsupported",
                f"no ability of this land is implemented: {abilities[0].source_line}",
                normalized_text,
            )

        # **A land can be hollow without printing an ability**, which the
        # `abilities` check above cannot see. Legends' five "…creatures you
        # control have \"bands with other …\"" lands and The Tabernacle at
        # Pendrell Vale print a *static* line: no activated ability, no
        # triggered ability, and nothing claimed it — so all six reported
        # supported, tapped for mana, and did nothing else. The comment above
        # says a land with no printed ability "has nothing to fail on", and
        # that is true only of reminder text; a static grant is text the engine
        # either implements or does not.
        #
        # Parenthetical spans are dropped first, because CR 305.6 reminder text
        # is exactly what a basic and a dual print and is not an ability.
        #
        # Asked of **every** land, not only of one with no parsed ability. The
        # guard used to be `not any((activated_abilities, triggered_abilities))`,
        # which exempted a land the moment any one of its lines became an
        # ability — so an unread static beside a working ability was invisible.
        # Halls of Mist is the card that showed it: its cumulative upkeep was
        # the unread line the old guard caught, and implementing that keyword
        # turned the land supported with "Creatures that attacked during their
        # controller's last turn can't attack" still unimplemented and now
        # unreported. The abilities are passed in instead, so their own lines
        # are skipped as read — which is the question the guard was standing in
        # for. Two ICE lands are what this newly names; no shipped card moved.
        unread = _unread_land_text(
            oracle_text, name, (*activated_abilities, *triggered_abilities)
        )
        if unread is not None:
            return OracleProgram(
                False,
                "unsupported",
                f"no static ability of this land is implemented: {unread}",
                normalized_text,
            )

        # **Passing the gate is not doing the thing.** The check above says a
        # reader claims the land's static line; this is the line being carried,
        # as the same ``lord_buff`` instruction a creature's anthem compiles to
        # (`_parse_creature_program` step 4). Without it Legends' five banding
        # lands would go back to exactly the state round 24 caught — reported
        # supported, tapping for mana, granting nothing — with the difference
        # that the gate would now agree with them.
        #
        # Only the derivations a *land* can print are read here, one table at a
        # time, rather than the whole creature chain: a land has no P/T for a
        # static bonus to change.
        #
        # It *can* restrict combat, which is what Glacial Chasm showed —
        # "Creatures you control can't attack." The comment here used to say a
        # land had no combat to restrict, and the gate above already asked
        # `combat_restriction_for` through `_is_supported_static_creature_line`,
        # so a land printing one would have been admitted with the restriction
        # nowhere: `declare_attackers_step.can_attack` scans every permanent's
        # compiled *instructions*, and this loop is the only place a land's
        # static line becomes one.
        land_statics: list[OracleInstruction] = []
        land_static_lines: list[str] = []
        for raw_line in (oracle_text or "").splitlines():
            line = _PARENTHETICAL_RE.sub("", raw_line).strip()
            if not line or ":" in line:
                continue
            normalized = normalize_creature_line(line)
            lord = lord_buff_for(normalized)
            if lord is not None:
                land_statics.append(
                    OracleInstruction(LORD_BUFF_KIND, "", lord_buff_payload(lord))
                )
                land_static_lines.append(normalized)
                continue
            restriction = combat_restriction_for(
                _restriction_line(line, name), name
            )
            if restriction is not None:
                land_statics.append(
                    OracleInstruction(restriction.kind, "", dict(restriction.payload))
                )
                land_static_lines.append(normalized)

        return OracleProgram(
            True, "land_mana", "basic land support", normalized_text,
            instructions=tuple(land_statics),
            activated_abilities=activated_abilities,
            triggered_abilities=triggered_abilities,
            static_lines=tuple(land_static_lines),
        )

    if primary_type == "creature":
        supported, effect_kind, reason, instructions, activated, triggered, static_lines = _parse_creature_program(oracle_text, name)
        return OracleProgram(supported, effect_kind, reason, normalized_text, instructions, activated, triggered, static_lines)

    if primary_type == "planeswalker":
        return _parse_planeswalker_program(oracle_text, name)

    if primary_type in {"artifact", "enchantment", "instant", "sorcery"}:
        if not normalized_text:
            return OracleProgram(True, "permanent_vanilla", "no oracle text", normalized_text)

        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)

        # Line by line — the only way it is assembled now. The legacy path that
        # stood alongside it collapsed the card's whole text to one string and
        # kept only the first rule that matched, so a second sentence ("Draw a
        # card. Each player discards a card.") was silently dropped and an
        # artifact whose activated ability the grammar reads in full still had
        # its card-level instruction produced by re-reading the card end to end.
        instructions: list[OracleInstruction] = _noncreature_line_instructions(
            oracle_text,
            name,
            activated_abilities,
            triggered_abilities,
            whole_card=primary_type in {"artifact", "enchantment"},
        )
        # "Choose one —" modal spells: parse each bullet as a selectable mode so
        # the game can resolve the player's chosen mode rather than always the
        # first. Built from the original text to keep human-readable labels.
        modes = _modal_options(oracle_text, name)

        # All-of, like the planeswalker gate and for the same reason: the UI
        # offers the whole mode list, so a card with one dead mode is offered
        # a choice it then declines to perform (the Read the Tides finding,
        # round 17 — "a modal spell needs every mode implemented or the card
        # is lying about the ones it isn't").
        dead_mode = next((m for m in modes if m.instruction is None), None)
        if dead_mode is not None:
            return OracleProgram(
                False,
                "unsupported",
                f"modal mode not implemented: {dead_mode.label!r}",
                normalized_text,
            )
        # "An opponent chooses one —" with a mode that **targets** used to be
        # refused here: CR 601.2c announces targets after CR 601.2b picks the
        # mode, and with the mode in somebody else's hands (CR 700.2e) the
        # caster could not name one while casting. There is an announcement
        # shape for it now — `mixins/stack/casting.arm_modal_mode_targets`
        # asks the caster for the mode's targets the moment the chooser
        # answers, inside the same uninterruptible window (CR 601.2i) — so the
        # gate is gone rather than widened.
        #
        # It was also blind in the direction that mattered: it read
        # ``"targets" in payload`` at the top level, and Fatal Lore's mode is a
        # ``sequence`` whose *step* targets. So it never fired on the one card
        # in the pool it was written for.
        chooser = _modal_chooser(oracle_text)

        if not instructions and modes and modes[0].instruction is not None:
            # A modal spell's card-level instruction is its *first* mode's — the
            # bullets are alternatives, so there is no other honest candidate,
            # and the stack executes this list when nothing chose a mode.
            #
            # The whole-text fallback that stood beside this is deleted with the
            # rule registry, and its removal is the last of the silent
            # partial-reads: it collapsed the card to one string, where "counter
            # target red spell. destroy target red permanent" reads as a spell
            # that does both, and where a sentence *no line* produced an
            # instruction for could still hand the card one borrowed from
            # somewhere else in its text. Four cards carried such an instruction
            # (Fastbond, Island Sanctuary, Jihad, Lich) and nothing dispatched
            # any of them.
            instructions.append(modes[0].instruction)

        # Static continuous co-effects (e.g. Conversion's "All Mountains are
        # Plains.") that follow a primary clause already claimed above and that
        # no line above claimed for itself, derived line by line by
        # engine/grammar/derived.py.
        for coeffect in _grammar_static_coeffects(oracle_text, name):
            if coeffect.kind not in {i.kind for i in instructions}:
                instructions.append(coeffect)

        # An Aura used to be classified supported by the single whitelist
        # substring "enchant creature", with nothing ever looking past the
        # enchant clause — so an Aura whose effect the engine does not
        # implement, or one with no effect line at all, entered play and did
        # nothing while reporting support. Every effect line must be claimed
        # (engine/auras.py) or the card is unsupported, with the offending line
        # named.
        aura_lines = [normalize_creature_line(line) for line in oracle_text.split("\n")]
        if any(line.startswith("enchant ") for line in aura_lines):
            unclaimed = unclaimed_aura_lines(aura_lines, name)
            if unclaimed:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"unimplemented aura effect: {unclaimed[0]}",
                    normalized_text,
                )

        # An Equipment (CR 301.5) is gated the same way, and had been gated by
        # nothing: Short Sword was supported on the substring "gets +" below,
        # its "Equipped creature gets +1/+1" never asked of engine/auras.py and
        # its equip line never compiled to anything — so it entered play and
        # could not be attached. Now the equip line has been rewritten into its
        # CR 702.6a activated ability above, and two things are required of
        # the card: that ability must have compiled to an instruction the engine
        # runs, and every *other* effect line must be claimed by the same
        # attached-effect reader an Aura's are (CR 301.5f makes "equipped
        # creature" the same reference as "enchanted creature", and the layer
        # bridge derives both off the attachment). By shape — the printed equip
        # line — because the compiler is not handed the type line, and CR 702.6a
        # makes equip an ability of Equipment cards.
        if has_equip_ability(printed_text):
            equip_abilities = [
                ability for ability in activated_abilities
                if is_equip_line(_printed_line_for(ability.source_line, printed_text))
            ]
            dead = next(
                (a for a in equip_abilities if not a.supported or a.instruction is None),
                None,
            )
            if dead is not None or not equip_abilities:
                offending = (
                    dead.source_line if dead is not None
                    else next(line for line in printed_text.split("\n") if is_equip_line(line))
                )
                return OracleProgram(
                    False,
                    "unsupported",
                    f"equip ability not implemented: {offending}",
                    normalized_text,
                )
            unclaimed = unclaimed_aura_lines(aura_lines, name)
            if unclaimed:
                return OracleProgram(
                    False,
                    "unsupported",
                    f"unimplemented equipment effect: {unclaimed[0]}",
                    normalized_text,
                )

        instructions.extend(
            OracleInstruction("derived_static_rule", claim)
            for claim in _derived_static_claims(oracle_text, normalized_text, name)
        )

        instructions.extend(
            OracleInstruction("spell_pattern", pattern)
            for pattern in SUPPORTED_SPELL_PATTERNS
            if pattern in normalized_text
        )

        # Only mark as unsupported if all triggered abilities are unsupported
        # and no spell-pattern instructions were already matched (e.g. Howling Mine).
        if triggered_abilities and all(not t.supported for t in triggered_abilities) and not instructions:
            return OracleProgram(False, "unsupported", "unsupported triggered ability", normalized_text)

        # A one-shot spell that resolves through no handler does nothing when
        # cast. `spell_pattern` is a marker recording that a whitelist substring
        # matched; it carries no behaviour, so a spell whose every instruction
        # is one is supported on the strength of a string comparison. Shahrazad
        # shipped that way, and ingesting Revised produced two more
        # (Shatterstorm, Crumble) on first contact.
        #
        # tests/engine/test_no_hollow_support.py asserted this as a property of
        # the pool; making it the compiler's own contract is what stops the next
        # set introducing another. Permanents are excluded for the same reason
        # that guard excludes them: they legitimately work through statics,
        # auras, layers and the text-keyed step tables.
        if (
            primary_type in ("instant", "sorcery")
            and instructions
            and not modes
            and not any(instruction.kind in _effect_handler_kinds() for instruction in instructions)
            and not any(a.supported for a in activated_abilities)
            and not triggered_abilities
        ):
            return OracleProgram(
                False,
                "unsupported",
                "no handler implements this spell's effect",
                normalized_text,
            )

        # The permanent half of the same contract, and the reason the exclusion
        # above is narrower than it reads. A permanent legitimately works
        # through statics, layers and the text-keyed step tables — but each of
        # those leaves a real instruction behind (``static_line``,
        # ``derived_static_rule``, an effect kind), never a bare
        # ``spell_pattern``. So a permanent whose *every* card-level instruction
        # is a whitelist marker does nothing on its own, and if every ability
        # line it prints also failed to parse it does nothing at all: Mazemind
        # Tome reported supported with both activated abilities carrying
        # ``instruction=None``, so it entered play, offered two abilities and
        # performed neither.
        #
        # The second conjunct is what keeps a permanent whose text is handled
        # somewhere this cannot see. Auras are excluded outright for that
        # reason: engine/auras.py above is their gate and it is the stricter of
        # the two — it names the first unclaimed effect line, and it knows about
        # the Aura death trigger (Creature Bond) that mixins/effects.py carries
        # with no instruction of its own.
        unreadable = [
            ability
            for ability in (*activated_abilities, *triggered_abilities)
            if not ability.supported or ability.instruction is None
        ]
        # **A line that fails earlier leaves less behind, not more.** This used
        # to require an unreadable *ability*, which reads as "something failed"
        # and is really "something failed late enough to become an object".
        # Sanctum of Stone Fangs' whole text is one triggered line the parser
        # refuses outright, so no ability was ever built, the list was empty and
        # the gate did not fire: the card entered play, reported supported, and
        # did nothing at all. Fiery Emancipation and Teferi's Ageless Insight
        # are the same shape with a replacement effect. The condition is what is
        # *absent* now — nothing supported, nothing static, only markers — and
        # the line named is the first one printed when no ability exists to
        # point at.
        #
        # Auras are excluded by shape rather than by name, and for one reason:
        # they work through engine/auras.py, which this cannot see and which is
        # the stricter gate anyway (it names the first unclaimed effect line).
        # Equipment used to be excluded beside them — Short Sword's "+1/+1" is
        # the same derived grant and left no instruction here. It no longer
        # needs the exclusion: its equip line compiles to a real activated
        # ability (CR 702.6a, above), which is the "something supported" this
        # gate already looks for, and its effect lines are gated by the
        # Equipment branch above. Keeping "equip" here would have exempted an
        # Equipment whose equip ability *failed* to compile from the very check
        # that catches a permanent doing nothing.
        attachment = any(line.startswith("enchant ") for line in aura_lines)
        # ``and instructions`` used to stand here, and it was standing in for
        # "the card produced *something*, but nothing that carries behaviour".
        # A ``spell_pattern`` marker was what usually produced that something —
        # so when the substring whitelist shrank from 73 entries to 5, a
        # permanent that produced nothing at all stopped reaching this branch
        # and fell through to the generic "effect not in basic pattern set"
        # below, losing the clause name. That is the wrong direction: the whole
        # value of refusing is naming what could not be read. The condition is
        # now the honest one — nothing here carries behaviour, vacuously true
        # for the empty case — and a card with no readable line is named rather
        # than dismissed. Everything the branch already caught is unaffected.
        if (
            primary_type in ("artifact", "enchantment")
            and not attachment
            and all(_carries_no_behaviour(instruction) for instruction in instructions)
            and not modes
            and not any(
                ability.supported and ability.instruction is not None
                for ability in (*activated_abilities, *triggered_abilities)
            )
        ):
            offending = (
                unreadable[0].source_line
                if unreadable
                else next((line for line in oracle_text.split("\n") if line.strip()), "")
            )
            return OracleProgram(
                False,
                "unsupported",
                f"no ability of this permanent is implemented: {offending}",
                normalized_text,
            )

        if instructions or any(a.supported for a in activated_abilities) or triggered_abilities:
            return OracleProgram(
                True,
                "spell_pattern",
                "pattern-supported effect",
                normalized_text,
                tuple(instructions),
                activated_abilities,
                triggered_abilities,
                modes=modes,
                modes_at_least=_modal_at_least(oracle_text),
                mode_chooser=chooser,
            )

        return OracleProgram(False, "unsupported", "effect not in basic pattern set", normalized_text)

    return OracleProgram(False, "unsupported", "unknown card type", normalized_text)


def compile_card_oracle(card: CardDefinition) -> OracleProgram:
    return _compile_card_oracle(
        card.name, card.primary_type, card.oracle_text, card.keywords, card.layout,
        card.is_legendary,
    )


def simple_card_keywords(card: CardDefinition) -> tuple[str, ...] | None:
    """The keyword abilities a card's printed text consists of entirely.

    A *simple* card either has no abilities at all — a vanilla creature, or a
    basic land whose only text is the reminder text of its intrinsic mana
    ability (CR 305.6) — or has nothing but keyword lines the engine
    implements, the same admission ``_is_supported_keyword_line`` gives a
    creature's keyword line (so protection's and hexproof's qualities are
    read as payload). Returns ``()`` for the first, the normalized keyword
    parts in printed order for the second, and ``None`` for a card with any
    other ability, or one the engine does not support.

    Read by the verification tracker (``web/verification_report.py``), which
    auto-passes a simple card: its behaviour is the engine's generic combat and
    keyword code plus the card's printed numbers, so a manual in-game check
    would exercise no ability-specific path. The decision is made from the
    printed text rather than from the compiled program's shape, because the
    text is what the claim is about — a program with no instructions is also
    what an entry-state line (``enter_effects.py``) or a replacement-only
    permanent compiles to, and neither of those is simple.
    """
    program = compile_card_oracle(card)
    if (
        not program.supported
        or program.activated_abilities
        or program.triggered_abilities
        or program.modes
    ):
        return None
    keywords: list[str] = []
    for line in card.oracle_text.splitlines():
        normalized = normalize_creature_line(line)
        if not normalized:
            continue
        if not _is_supported_keyword_line(line):
            return None
        keywords.extend(part.strip() for part in normalized.split(",") if part.strip())
    return tuple(keywords)
