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
    strip_ability_word,
)
from .characteristic_defining import dynamic_pt_for
from .auras import unclaimed_aura_lines
from .cast_costs import cast_cost_claims_line
from .combat_restrictions import combat_restriction_for
from .effect_labels import activated_label, triggered_label
from .lord_buffs import LORD_BUFF_KIND, lord_buff_for, lord_buff_payload
from .static_bonuses import static_bonus_for
from .grammar import ast as grammar_ast, compile_line as compile_grammar_line
from .grammar.vocabulary import IMPLEMENTED_KEYWORDS

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
UNSUPPORTED_KEYWORDS = {
    "Rampage",
    "Cumulative upkeep",
    "Phasing",
}

UNSUPPORTED_PATTERNS = (
    "exchange control",
)


SUPPORTED_SPELL_PATTERNS = (
    "target player draws",
    "draws x cards",
    "deals",
    "deals x damage",
    "destroy target",
    "destroy all",
    "counter target",
    "gets +",
    "creatures get +",
    "target player discards",
    "loses",
    "target player loses the game",
    "you win the game",
    "the game is a draw",
    "regenerate target",
    "tap target",
    "untap target",
    "target creature with power 2 or less can't be blocked this turn",
    "prevent the next",
    "would deal damage to you this turn, prevent that damage",
    "from your graveyard to your hand",
    "from your graveyard to the battlefield",
    "from a graveyard onto the battlefield",
    "return target creature to its owner's hand",
    "each player discards their hand, then draws seven cards",
    "each player shuffles their hand and graveyard into their library, then draws seven cards",
    "search your library for a card, put that card into your hand, then shuffle",
    "take an extra turn after this one",
    # "as an additional cost to cast this spell, sacrifice a creature" was here.
    # A marker instruction with no handler is the wrong shape for a *cost*: it
    # made Village Rites report supported and cast for free. It is now read by
    # engine/cast_costs.py and paid by queue_from_hand.
    "becomes red",
    "becomes black",
    "becomes blue",
    "becomes green",
    "becomes white",
    "prevent all combat damage that would be dealt this turn",
    "look at target player's hand",
    "draw a card",
    "add three mana of any one color",
    "at the beginning of your upkeep, sacrifice this enchantment unless you pay",
    "this artifact becomes a 3/6 golem artifact creature until end of combat",
    "create a 1/1 colorless insect artifact creature token with flying named wasp",
    "enchant wall",
    "whenever a land enters",
    "at the beginning of the chosen player's upkeep",
    "enchant creature",
    "enchant land",
    "target creature gains flying until end of turn",
    "enchant artifact",
    "has swampwalk",
    "has forestwalk",
    "has islandwalk",
    "has mountainwalk",
    "has plainswalk",
    "add one mana",
    "add {",
    "gain",
    "each player chooses a number of lands they control equal to the number of lands controlled by the player who controls the fewest",
    "the next time an unblocked creature of your choice would deal combat damage to you this turn, prevent all but 1 of that damage",
    "look at the top three cards of target player's library, then put them back in any order",
    "you may have that player shuffle",
    "change the text of target spell or permanent by replacing all instances of one basic land type with another",
    "change the text of target spell or permanent by replacing all instances of one color word with another",
    "look at target opponent's hand and choose a card from it",
    "target creature defending player controls can block any number of creatures this turn",
    "this turn, instead of declaring blockers",
    "put a mire counter on target non-swamp land",
    "remove target creature defending player controls from combat",
    "whenever one or more creatures you control attack, each defending player divides all creatures without flying",
    "target creature gains banding until end of turn",
    "copy target instant or sorcery spell",
    "remove this card from your deck before playing if you're not playing for ante",
    "discard your hand, ante the top card of your library, then draw seven cards",
    "you own target card in the ante. exchange that card with the top card of your library",
    "each player antes the top card of their library",
)


# ---------------------------------------------------------------------------
# Supported trigger condition patterns
# Each entry: (kind, regex_or_substring)
# Checked in order; first match wins.
# ---------------------------------------------------------------------------

# "whenever" triggers
WHENEVER_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("land_dies",                   r"whenever a land is put into a graveyard from the battlefield"),
    ("creature_dies",               r"whenever a creature dies"),
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
    # "…to a player **or planeswalker**" (Garruk's Harbinger). Its own kind
    # rather than a widening of the row below, because the two fire in different
    # places: damage to a player comes from the player-damage path, damage to a
    # planeswalker from the loyalty-removal one, and a card naming only the
    # first must not start firing on the second. Longest first, as the note
    # above requires.
    ("creature_deals_combat_damage_to_player_or_walker",
     r"whenever this creature deals combat damage to a player or planeswalker"),
    ("creature_deals_combat_damage",r"whenever this creature deals combat damage to a player"),
    ("creature_deals_damage_to_opponent", r"whenever this creature deals damage to an opponent"),
    ("deals_damage_to_player",      r"whenever .+ deals damage to a player"),
    ("creature_deals_damage",       r"whenever this creature deals damage"),
    ("creature_blocks_or_blocked_by_nonwall", r"whenever this creature blocks or becomes blocked by a non-wall creature"),
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
    # The same subject over a damage event (Hooded Blightfang's second line).
    # `deals_damage_to_player` above does not shadow it: "planeswalker" and
    # "player" share four letters and diverge at the fifth, so the two recipients
    # are disjoint literals rather than a prefix pair — which the shadowing
    # guard checks rather than this comment asserting it.
    ("matching_creature_damages_planeswalker",
     r"whenever (?P<damager_subject>(?:a|another) [^,]+) deals damage to a planeswalker"),
    ("matching_creature_attacks",
     r"whenever (?P<attacker_subject>(?:a|another) [^,]+) attacks"),
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
    ("creature_attacks",            r"whenever this creature attacks"),
    # "…blocks **a creature with flying**" (Snarespinner) narrows the source's
    # own block trigger by what it blocked. Before the bare form, which is its
    # strict prefix: matching that first is what made Snarespinner compile to an
    # unnarrowed condition with its rider dropped on the floor.
    ("creature_blocks",
     r"whenever this creature blocks (?P<blocked_subject>(?:a|another) [^,]+)"),
    ("creature_blocks",             r"whenever this creature blocks"),
    # "…becomes blocked by **a creature**" (Gloom Sower): once per blocking
    # creature that answers the filter (CR 509.1h), where the bare form below
    # fires once for the block itself. Same ordering rule.
    ("creature_becomes_blocked",
     r"whenever this creature becomes blocked by (?P<blocker_subject>(?:a|another) [^,]+)"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
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
    ("self_becomes_target",
     r"whenever this creature becomes the target of a spell or ability"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    ("enchanted_land_tapped",       r"whenever enchanted land becomes tapped"),
    ("self_becomes_tapped",         r"whenever this land becomes tapped"),
    # "Whenever a Forest an opponent controls becomes tapped" (Lifetap). The
    # type and the controller scope are named groups, so the restriction
    # arrives as condition-payload data and one dispatcher
    # (engine/events.py::_becomes_tapped_filter) covers every card written this
    # way. Must follow the two specific forms above, which name their subject
    # ("enchanted land", "this land") rather than quantifying it.
    ("permanent_becomes_tapped",
     r"whenever an? (?P<tapped_subtype>[a-z]+)"
     r"(?: (?P<tapped_controller>an opponent controls|you control))? becomes tapped"),
    # "Whenever a Mountain is tapped for mana" (Gauntlet of Might) narrows the
    # same condition to one land type; the unnarrowed "whenever a player taps a
    # land for mana" (Manabarbs, Mana Flare) follows it.
    ("land_tapped_for_mana",        r"whenever a (?P<tapped_land_subtype>[a-z]+) is tapped for mana"),
    ("land_tapped_for_mana",        r"whenever a player taps a land for mana"),
    # A colour-narrowed cast trigger (the Rod/Cup/Sphere cycle). The colour is
    # captured into the condition payload so one dispatcher covers every card
    # written this way; must precede the unnarrowed form below.
    ("spell_cast",                  r"whenever a player casts a (?P<color_word>white|blue|black|red|green) spell"),
    ("spell_cast",                  r"whenever a player casts a spell"),
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
    # "Whenever a source you control deals noncombat damage to an opponent …"
    # (Chandra's Pyreling, Chandra's Incinerator). "A source you control" is the
    # seat that controls the damage's source (CR 109.5), which a damage event
    # could not answer until it started carrying one: what the damage paths hold
    # for a spell is its printed card, and no player controls a printed card.
    # Announced from `_deal_damage_to_player`, which is the noncombat seam —
    # the combat damage step reaches players by its own path, so "noncombat" is
    # a property of the fire site rather than a flag it has to remember.
    ("source_you_control_damages_opponent",
     r"whenever a source you control deals noncombat damage to an opponent"),
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
    ("draws_card",                  r"whenever you draw a card"),
    # "…your second card each turn" (Mystic Skyfish, Jolrael). Fires once per
    # turn, announced by the draw sweep in check_state_based_actions off the
    # cards_drawn_this_turn record every draw path already feeds.
    ("draws_second_card",           r"whenever you draw your second card each turn"),
)

# "when" triggers (enter/leave events)
WHEN_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("enters_battlefield",          r"when (?:this|.+) enters(?: the battlefield)?"),
    ("leaves_battlefield",          r"when (?:this|.+) leaves(?: the battlefield)?"),
    ("dies",                        r"when (?:this creature|.+) dies"),
    # "you_gain_life" was here, spelled "when you gain life", with no dispatcher
    # and no card: a life gain is a repeatable event, so every printing of it is
    # "**Whenever** you gain life" — the row above in the whenever table, which
    # Vito reaches. A kind lives in one table, because the shadowing guard's
    # canonical examples are keyed by kind and an example can only be a wording
    # of one trigger word.
    ("becomes_target",              r"when (?:this|.+) becomes the target"),
    ("no_islands",                  r"when you control no islands"),
    ("no_lands",                    r"when you control no lands"),
)

# "at the beginning of" triggers
AT_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("upkeep_self",         r"at the beginning of your upkeep"),
    ("upkeep_each",         r"at the beginning of each (?:player's )?upkeep"),
    # Deliberately excludes `land`: Cursed Land's upkeep damage is already dealt
    # by the enchant-land upkeep pass in phases/upkeep_step.py. Adding `land`
    # here compiles a *second* trigger and the card deals its damage twice —
    # caught by test_cursed_land_deals_upkeep_damage_to_land_controller.
    ("upkeep_enchanted_controller", r"at the beginning of the upkeep of enchanted (?:creature|artifact|enchantment)'s controller"),
    ("upkeep_chosen",       r"at the beginning of the chosen player's upkeep"),
    ("draw_step_each",      r"at the beginning of each player's draw step"),
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
    ("end_step",            r"at the beginning of (?:the |each )?end(?: step)?"),
    # "…of combat on your turn" narrows the bare form to the active player's
    # combat (Adherent of Hope); must precede its own prefix below.
    ("combat_your_turn",    r"at the beginning of combat on your turn"),
    ("combat",              r"at the beginning of combat"),
)

# "if" conditions that can appear mid-effect
IF_CONDITION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("artifact_untapped",       r"if this artifact is untapped"),
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


def _chargeable_sacrifice_filter(phrase: str) -> dict | None:
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

    described = subject_filter_payload(phrase)
    if described is None:
        return None
    # A sacrifice cost is paid from the payer's own battlefield, so "you
    # control" would be no narrowing at all — but nothing here checks it, and a
    # phrase the charger silently agrees with is still a phrase it did not read.
    carried = object_only_filter(described, carried_separately=frozenset({"exclude_self"}))
    if carried is None:
        return None
    if "exclude_self" in described:
        carried = {**carried, "exclude_self": True}
    return carried


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
    """
    from .grammar import card_filter_payload

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


def parse_activated_ability_cost(line: str) -> ActivatedAbilityCost:
    required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 0}
    requires_tap = False
    if not line or ":" not in line:
        return ActivatedAbilityCost(required, requires_tap)

    cost_part = line.split(":", 1)[0]
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
    # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman). Older
    # printings name the card instead of saying "this artifact", so accept
    # either wording.
    sacrifice_self = bool(
        re.search(
            r"\bsacrifice this (artifact|creature|enchantment|permanent|land|token)\b",
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
    chosen_sacrifice = (
        None if sacrifice_self
        else re.search(r"\bsacrifice ((?:another|an?) [^,:]+?)\s*(?=,|$)", cost_lower)
    )
    sacrifice_filter = (
        _chargeable_sacrifice_filter(chosen_sacrifice.group(1))
        if chosen_sacrifice
        else None
    )
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
    discard_filters = (
        _chargeable_discard_filters(discarded.group(1)) if discarded else None
    )
    # "Tap two untapped Spirits you control" (Shacklegeist). The {T} symbol was
    # already consumed above as mana; this is the spelled-out form, which taps
    # *other* permanents.
    tap_cost = _chargeable_tap_cost(cost_lower)
    # "Discard your hand" (Subira). Matched here rather than folded into the
    # phrase above, because it is not a count: there is no card for the payer to
    # name and no filter to test, and it is payable with an empty hand.
    discard_whole_hand = bool(re.search(r"\bdiscard your hand\b", cost_lower))
    return ActivatedAbilityCost(
        required, requires_tap, discard_last_drawn, exile_self, sacrifice_self,
        sacrifice_filter,
        tap_filter=tap_cost[1] if tap_cost else None,
        tap_count=tap_cost[0] if tap_cost else 0,
        discard_cards=0 if discard_filters is None else 1,
        discard_filters=discard_filters or (),
        discard_whole_hand=discard_whole_hand,
        pay_life=_life_payment_cost(cost_lower),
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
        count = _NUMBER_WORDS.get(str(word).strip())
        if count is None:
            return None
        resolved[key] = count
    for key, phrase in payload.items():
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


def _parse_triggered_ability(line: str, card_name: str | None = None) -> ParsedTriggeredAbility | None:
    """Parse a single oracle text line as a triggered ability.

    Returns None if the line doesn't start with a trigger word at all,
    so the caller can try other parsers. Returns a ParsedTriggeredAbility
    with supported=False if the trigger prefix is recognized but the
    condition or effect is not.
    """
    normalized = normalize_creature_line(line)

    condition, remainder = _parse_trigger_condition(normalized)
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
    compiled = compile_grammar_line(line, card_name=card_name)
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
) -> tuple[OracleInstruction, str] | None:
    """The front ends that read one line, most general first: the grammar, then
    the name-keyed card hooks. There is no third — a line neither claims has no
    instruction, and the card is reported unsupported naming the clause."""
    found = _grammar_instruction(
        line, card_name,
        activated=activated, condition_kind=condition_kind,
        spell_line_only=spell_line_only,
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


def _mode_reading(label: str, card_name: str | None) -> tuple[OracleInstruction, str] | None:
    """A modal bullet's ``(instruction, effect_kind)``, or None.

    ``effect_kind`` is "spell_pattern" for every bullet the front ends claim,
    not the grammar's category label. A mode is one alternative of a spell, and
    the label is what ``SimulationResult`` and the support report bucket the
    *card* by — so it names the reading's shape, exactly as it did when the
    legacy registry produced it.
    """
    found = _line_instruction(label, card_name)
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
    for index, raw in enumerate(lines):
        if _modal_head(raw.strip(), grammar_ast.SpellEffectLine) is None:
            continue
        bullets = _bullets_after(lines, index)
        if not bullets:
            continue
        options: list[ModalOption] = []
        for label in bullets:
            instruction, effect_kind = _reading(_mode_reading(label, card_name))
            # The original casing is kept for the UI's mode picker.
            options.append(
                ModalOption(label.rstrip("."), instruction, effect_kind, instruction is not None)
            )
        return tuple(options)
    return ()


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
        if "targets" in instruction.payload:
            # The mode picker resolves at trigger resolution; nothing collects
            # a target after a mode is chosen, so a targeted mode would run
            # against a target nobody picked.
            return f"a targeted mode of a triggered ability has no picker: {label!r}"
        modes.append({"label": label.rstrip("."), "instruction": instruction})
    choose = OracleInstruction("choose_one", "", {"modes": tuple(modes)})
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
    if ":" not in normalized:
        return None

    effect_text = normalized.split(":", 1)[1].strip()
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
    supported = instruction is not None
    return ParsedActivatedAbility(
        source_line=line,
        normalized_effect=effect_text,
        supported=supported,
        cost=parse_activated_ability_cost(line),
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


def _collapse_self_references(normalized: str, card_name: str | None, replacement: str) -> str:
    """*normalized* with whole-word self-references replaced by *replacement*."""
    for form in _self_name_forms(card_name):
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
_DELAYED_ATTACK_RE = re.compile(
    r"^whenever (?:(?P<batch>one or more )|an? )?(?P<nontoken>nontoken )?creatures? attacks?"
    r" this turn, (?P<effect>.+)$"
)

# The same delayed trigger with its duration printed *first* and its subject
# narrowed: "Until end of turn, whenever a creature you control with power 2 or
# less attacks, draw a card." (Subira, Tulzidi Caravanner.) The subject is a
# printed noun phrase, delimited here and read by the noun parser — the
# ``_subject`` convention this file already uses — so a card narrowing by a
# different tribe, keyword or stat needs no code.
_DELAYED_ATTACK_UNTIL_RE = re.compile(
    r"^until end of turn, whenever (?P<attacker_subject>.+?) "
    r"(?P<event>attacks|deals combat damage to a player), (?P<effect>.+)$"
)

#: Which fire site each delayed-trigger event belongs to. A phrase whose event
#: is not here has nowhere to be announced, so the clause refuses rather than
#: arming a trigger nothing will ever look at — the dispatcher question round 93
#: wrote down, asked at the moment the trigger is *created* instead of at the
#: moment it should have fired.
_DELAYED_EVENTS: dict[str, str] = {
    "attacks": "creatures_attack",
    "deals combat damage to a player": "creature_deals_combat_damage_to_player",
}


def _parse_delayed_attack_trigger(
    effect_clause: str, card_name: str | None
) -> OracleInstruction | None:
    """The ``create_delayed_trigger`` instruction for a delayed attack-trigger
    clause, or None when the clause is not one — including when its inner
    effect fails to parse, so the card refuses rather than arming a trigger
    that fires into nothing."""
    normalized = normalize_creature_line(effect_clause)
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
                "event": _DELAYED_EVENTS[narrowed.group("event")],
                "batch": False,
                "nontoken": False,
                "attacker_filter": described,
                "instruction": inner[0],
                "duration": "end_of_turn",
            },
        )
    match = _DELAYED_ATTACK_RE.match(normalized)
    if match is None:
        return None
    inner = _line_instruction(match.group("effect"), card_name, activated=True)
    if inner is None:
        return None
    return OracleInstruction(
        "create_delayed_trigger",
        "",
        {
            "event": "creatures_attack",
            "batch": bool(match.group("batch")),
            "nontoken": bool(match.group("nontoken")),
            "instruction": inner[0],
            "duration": "end_of_turn",
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
_GRAMMAR_STATIC_CREATURE_KINDS = frozenset({"dynamic_pt_bonus"})


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
    if static_bonus_for(normalized) is not None:
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
    if combat_restriction_for(_restriction_line(line, card_name)) is not None:
        return True
    # A lord's continuous buff to other creatures. The gate used to admit the
    # bare prefix "other ", which is a template in disguise: "Other Goblins
    # glimmer uncontrollably." compiled as supported and did nothing. It asks
    # the derivation table the consumer dispatches on, so an unimplemented
    # keyword, an unrecognized granted ability or an unmodelled condition is now
    # reported unsupported rather than admitted and dropped.
    if lord_buff_for(normalized) is not None:
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

    if land_play_line(normalized) == "allowance":
        return True
    # "As this creature enters, it becomes your choice of <body>, …"
    # (Primal Clay). Carried out by _initialize_permanent_state, which reads the
    # bodies from this same parser — so what is claimed here and what is applied
    # cannot describe different cards.
    from .enter_effects import choosable_bodies

    if choosable_bodies(normalized):
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
    from .replacements import replacement_claims_line

    if replacement_claims_line(normalized):
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
        # Old Man of the Sea: a pure player option with no forced game-state
        # consequence if unused (the untap step already defaults to
        # untapping); its actual gameplay hook is the linked-duration control
        # ability, which cares about the CURRENT tapped state, not this line.
        "you may choose not to untap this creature during your untap step",
    )
    return any(normalized.startswith(pattern) for pattern in static_patterns)


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

    any_supported_trigger = False
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
            any_supported_trigger = True
            instructions.append(trig.instruction)
            index += consumed
            continue

        # 1. Plain keyword line (e.g. "Flying, Trample")
        if _is_supported_keyword_line(line):
            normalized = normalize_creature_line(line)
            instructions.append(OracleInstruction("keyword_line", normalized))
            static_lines.append(normalized)
            continue

        # 1b. An additional cost to cast this spell (CR 601.2b). Not an effect
        # and so not an instruction: it is collected and paid by
        # `queue_from_hand`, which reads the same table this asks. A creature
        # spell prints one as readily as an instant does (Goremand), and
        # without this step the line was the reason the whole card came back
        # "text too complex".
        if cast_cost_claims_line(line):
            continue

        # 2. Triggered ability
        trig = _parse_triggered_ability(line, card_name)
        if trig is not None:
            if trig.supported:
                triggered.append(trig)
                any_supported_trigger = True
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
            elif (bonus := static_bonus_for(normalized)) is not None:
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
                    _restriction_line(line, card_name)
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

    if triggered and not any_supported_trigger:
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


def _parse_noncreature_triggered(
    oracle_text: str, card_name: str | None = None
) -> tuple[ParsedTriggeredAbility, ...]:
    """Extract triggered abilities from non-creature oracle text."""
    abilities: list[ParsedTriggeredAbility] = []
    for raw_line in oracle_text.splitlines():
        line = raw_line.strip()
        if not line:
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
                cost = line.partition(":")[0].strip()
                out.extend(f"{cost}: {bullet}" for bullet in bullets)
                i += 1 + len(bullets)
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)

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
    from .draw_step_modifiers import draw_step_bonus_for
    from .enter_effects import enter_effect_line
    from .global_statics import global_static_for
    from .land_play_allowance import land_play_allowance_for
    from .replacements import replacement_claims_line
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
    # A board-wide static (Titania's Song, Energy Flux) contributes its effects
    # through the CR 613 layer bridge and, for a granted ability, through the
    # affected permanent's effective card — so there is no instruction to
    # produce, and without this the source card would report unsupported while
    # working perfectly.
    if global_static_for(oracle_text) is not None:
        claims.append("global_statics")
    if draw_step_bonus_for(oracle_text) is not None:
        claims.append("draw_step_modifiers")
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
    if any(
        cost_modifier_claims_line(normalize_creature_line(line))
        for line in oracle_text.splitlines()
    ):
        claims.append("cost_modifiers")
    # The whole entry-state registry, not two of its constants: every phrase in
    # engine/enter_effects.py is implemented by _initialize_permanent_state, so
    # naming a subset here is the same partial-list mistake one level down.
    if any(enter_effect_line(line) for line in oracle_text.splitlines()):
        claims.append("enter_effects")
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


# Unbounded cache: card definitions are immutable and the pool is finite, so
# every distinct card compiles exactly once per process — even with thousands
# of cards the programs are tiny compared to recompilation cost.
@lru_cache(maxsize=None)
def _compile_card_oracle(
    name: str,
    primary_type: str,
    oracle_text: str,
    keywords: tuple[str, ...],
    layout: str = "normal",
) -> OracleProgram:
    # Pyramids-style "{cost}: Choose one —" + bullets become one activated
    # ability per bullet before any other classification runs.
    oracle_text = expand_modal_activated_lines(oracle_text)
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
        # strips to nothing). A land is therefore ALWAYS at least playable —
        # unlike creatures/artifacts, an unparsed bonus ability degrades just
        # that ability, never the land's own castability. Non-reminder-text
        # ability lines (Desert's damage ping, Bazaar of Baghdad's draw-
        # discard, …) are parsed the same way artifacts' are, so lands with
        # abilities beyond mana become activatable too.
        activated_abilities = _parse_noncreature_abilities(oracle_text, name)
        triggered_abilities = _parse_noncreature_triggered(oracle_text, name)
        return OracleProgram(
            True, "land_mana", "basic land support", normalized_text,
            activated_abilities=activated_abilities,
            triggered_abilities=triggered_abilities,
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
        # Auras **and Equipment** are excluded by shape rather than by name, and
        # for one reason: both work through engine/auras.py, which this cannot
        # see and which is the stricter gate anyway (it names the first
        # unclaimed effect line). Short Sword's "+1/+1" is an
        # `aura_static_pt_grant` that leaves no instruction here, so without the
        # equip exclusion the widening would refuse two Equipment that work.
        attachment = any(
            line.startswith("enchant ") or line.startswith("equip")
            for line in aura_lines
        )
        if (
            primary_type in ("artifact", "enchantment")
            and not attachment
            and instructions
            and all(instruction.kind == "spell_pattern" for instruction in instructions)
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
            )

        return OracleProgram(False, "unsupported", "effect not in basic pattern set", normalized_text)

    return OracleProgram(False, "unsupported", "unknown card type", normalized_text)


def compile_card_oracle(card: CardDefinition) -> OracleProgram:
    return _compile_card_oracle(
        card.name, card.primary_type, card.oracle_text, card.keywords, card.layout
    )
