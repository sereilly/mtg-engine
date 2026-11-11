"""The "whenever" trigger-condition table (CR 603.1).

Each row is ``(kind, pattern)``: the condition kind a dispatcher is addressed
by, and a regex that **delimits** the printed condition. Its named groups are
the condition's payload, and what a group holds is read elsewhere — a
``<name>_subject`` by the noun parser, a ``<name>_count`` by the number table
(``engine/trigger_conditions.py``'s ``_resolve_subject_groups``) — never
approximated here. Rows are checked in order and the first match wins, so a
row's position is part of what it means: a narrowed row sits above the
unqualified row its pattern is a prefix of.

**Why each row is what it is and where it is** is
``engine/whenever_trigger_notes.py``: one note per row that had one, in this
table's own order, so "the row below" in a note still means the next row
here. The rationale was four lines in five of this module, and a table whose
order is behaviour cannot be split while its prose can — so the prose moved
and the table stayed whole. A row added here gets its note there, at the same
position (``tests/engine/test_dst_w2g3_whenever_trigger_notes.py`` holds
each note to one row and the notes to the table's order).

One ordered table, so one module. The "when", "at the beginning of" and "if"
tables, and the reader that matches all four against a line, are
``engine/trigger_conditions.py``; this one is held apart because it is most of
their length, and a table whose order is behaviour is not split across
modules. Both were ``engine/oracle.py``'s until the 2,000-line cap.
"""

from __future__ import annotations

from .grammar.vocabulary import TYPE_LINE_SUPERTYPES as _TYPE_LINE_SUPERTYPES


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

#: The source naming itself at the head of a **union** subject -- "whenever
#: **this creature or** another Rogue you control enters" (Thieves' Guild
#: Enforcer), "whenever **this artifact or** another artifact enters" (Serum
#: Tank). Every permanent noun a card calls itself, because which one it prints
#: is its card type and not a different event: written "this creature" alone,
#: Serum Tank's line matched no row and its charge counters never arrived while
#: the card reported supported on its other line. The grammar reads the same
#: nouns (``trigger_matched``'s explicit-self prefix), so the two front ends
#: agree on which lines are a union (``trigger_tables._DAMAGER_NOUNS``).
_SOURCE_UNION_HEAD = r"this (?:creature|artifact|enchantment|land|aura|permanent) or "


# "whenever" triggers
WHENEVER_TRIGGER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("land_dies",                   r"whenever a land is put into a graveyard from the battlefield"),
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into a graveyard from the battlefield"
     r", if it (?P<dying_not_sacrificed>wasn't sacrificed)"),
    ("permanent_dies",
     r"whenever a spell or ability (?P<dying_cause>an opponent) controls causes "
     r"(?P<dying_subject>an? [^,]+?) to be put into "
     r"(?P<dying_graveyard_owner>your|an opponent's) "
     r"graveyard from the battlefield"),
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into "
     r"(?P<dying_graveyard_owner>your|an opponent's) "
     r"graveyard from the battlefield"),
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into (?:a|a player's) "
     r"graveyard from the battlefield"),
    ("permanent_destroyed",
     r"whenever a spell or ability (?P<destroyed_cause>an opponent) controls "
     r"destroys (?P<destroyed_subject>(?:an?|another) [^,]+)"),
    ("card_put_into_graveyard",
     r"whenever (?P<another_card>)another card is put into a graveyard "
     r"from anywhere"),
    ("card_put_into_graveyard",
     r"whenever (?P<graveyard_card_subject>an? [a-z]+ card) is put into "
     r"(?P<opponent_graveyard>)an opponent's graveyard from anywhere"),
    ("card_put_into_graveyard",
     r"whenever (?P<graveyard_card_subject>an? [a-z]+ card) is put into "
     r"(?P<your_graveyard>)your graveyard (?P<from_library>)from your library"),
    ("discards_card",
     r"whenever (?:you discard|(?P<discarder>an opponent|a player) discards) "
     r"a card"),
    ("cycles_card",
     r"whenever (?:you cycle|(?P<cycler>an opponent|a player) cycles) a card"),
    ("discarded_by_opponent_effect",
     r"whenever a spell or ability an opponent controls causes you to "
     r"discard (?P<discarded_any_card>a card)"),
    ("creature_dies",               r"whenever a creature dies"),
    ("attached_creature_dies",      r"when(?:ever)? (?:equipped|enchanted) creature dies"),
    ("creature_you_control_dies",   r"whenever a creature you control dies"),
    ("creature_opponent_controls_dies",
     r"whenever a creature an opponent controls dies"),
    ("creature_you_control_dies",
     r"whenever this creature or another creature you control dies"),
    ("damage_dealt",
     r"whenever (?P<damage_recipient>you(?='re| are)|an opponent(?= is))"
     r"(?:'re| are| is) dealt "
     r"(?:(?P<damage_combat>combat|noncombat) )?damage(?P<damager_any>)"
     r"(?P<damage_received>)"),
    ("damage_dealt",
     r"whenever (?:"
     r"(?P<damager_self>this (?:creature|artifact|enchantment|land|aura|permanent))"
     # "equipped creature" is CR 301.5f's spelling of the same referent
     # (Mask of Memory, Worldslayer); the dispatcher reads `attached_to`.
     r"|(?P<damager_attached>enchanted (?:creature|artifact|enchantment|land|permanent)"
     r"|equipped creature)"
     # "Whenever **a source an opponent controls** deals damage to you"
     # (Farsight Mask) beside "a source you control": CR 109.5's other seat
     # word, the same seat question (``event_filters``), so it is one group
     # with two values rather than a subject the noun parser would read as a
     # description of permanents and so silently exclude every spell. Each
     # word keeps its own verb agreement, so neither spelling admits the
     # other's.
     r"|a source (?P<damager_controller>you(?= control )|an opponent(?= controls ))"
     r" controls?"
     # "…**other than this artifact**" (Talon of Pain): the source excluded by
     # identity, a marker `event_filters` tests.
     r"(?P<damager_other_than_self> other than this (?:creature|artifact|enchantment|land|permanent))?"
     # "Whenever **a source** deals damage to this creature" (Crag Saurian).
     # The damager narrowed by nothing at all — CR 120.7's word covers a spell,
     # an ability and a permanent alike, and no `ObjectFilter` can name the
     # first two. So it is a **marker** group rather than a subject one: read
     # through the noun parser, "a source" would become a filter, and a filter
     # is a description of permanents that would silently exclude every spell
     # the card watches. Above `damager_subject`, whose `[^,]+?` would claim it.
     r"|(?P<damager_any>a source)"
     # "Whenever **a spell** deals damage to this creature" (Tephraderm). The
     # damager narrowed to CR 113.3's other half of "source": a spell, never an
     # ability or a permanent. A marker for `damager_any`'s reason — a spell is
     # its printed card, which no `ObjectFilter` describes — answered by the
     # flag the one damage seam freezes (`damage_events._announce`,
     # ``damager_is_spell``). Above `damager_subject` for the same reason.
     r"|(?P<damager_spell>a spell)"
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
     # "…deals damage **to this creature**" (Crag Saurian). The ability's own
     # source on the *recipient* side, which is the one thing no branch below
     # can say: every one of them names a player, a planeswalker or a noun
     # phrase with an article, and "this creature" is a self-reference. A
     # **marker** rather than a `_subject` group for the damager's reason one
     # screen up — the noun parser refuses the words, and a filter is not what
     # "this" means anyway: it is an identity, tested as one in `event_filters.py`.
     r"(?P<damaged_self>this (?:creature|artifact|enchantment|land|aura|permanent))"
     r"|(?P<damage_recipient>a player or planeswalker|a player"
     # "…to **defending player**" (Electryte). CR 506.2's seat, printed with no
     # article — the one recipient word naming a relation to the *combat*
     # rather than to the ability's controller. Beside the others here because
     # it is a fixed word like them, and tested in `event_filters.py` against the
     # attack declaration.
     r"|an opponent|a planeswalker|defending player|you)"
     # "…deals damage **to a creature**" (Bellowing Fiend). A recipient that is
     # an *object*: none of the fixed words above can say it, because every one
     # of them names a player or a planeswalker. Delimited as a `damaged_subject`
     # group, read by the same noun parser every other narrowed condition here
     # goes through, and tested by `engine/event_filters.py`'s filter against the
     # permanent that took the damage — which the one damage seam already
     # freezes (`about_permanent_id`).
     #
     # The seat prefix is *optional* on this branch, which is what folds
     # Mangara's Equity's "to you or a white creature you control" back in: the
     # union is this same noun phrase with a seat word in front of it, and two
     # branches would need two group names for one stem.
     #
     # **Below** the fixed list, and the ordering is this table's usual rule
     # read backwards: `an? [^,]+` would happily claim "a player", so the words
     # that have a seat reading have to be offered theirs first. "you or a …"
     # still reaches here — the fixed branch matches "you", the comma bound
     # then fails, and the alternation backtracks into this one.
     r"|(?:(?P<damage_recipient_seat>you|an opponent) or )?"
     # "…deals damage to **a creature or opponent**" (Flesh Reaver). The same
     # union with the two halves printed the other way round, and English drops
     # the second article when it does — so the seat word is a bare one here
     # and the noun phrase is lazy, letting the suffix take the last "or …"
     # only when that word really is a seat. A colour disjunction inside the
     # phrase ("a green or white creature") never reaches it: the alternation
     # below names seats and nothing else, so the lookahead fails and the lazy
     # phrase simply grows.
     #
     # A second group name rather than a second use of the one above, because
     # Python forbids repeating one — `event_filters.py` folds the two spellings back
     # into a single seat before testing, so the word order is not a second
     # answer to "whose damage was this".
     r"(?P<damaged_subject>an? [^,]+?)"
     r"(?: or (?P<damage_recipient_seat_after>opponent|you))?"
     r"))?(?=,|$)"),
    ("creature_blocks_or_blocked_by",
     r"whenever (?:enchanted|equipped) (?P<combatant_attached>[a-z]+) blocks or "
     r"becomes blocked by (?P<block_pair_subject>(?:an?|another) [^,]+)"),
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked by (?P<block_pair_subject>(?:an?|another) [^,]+)"),
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked by "
     r"(?P<block_pair_count>[a-z]+) or more (?P<block_pair_subjects>[^,]+)"),
    ("creature_blocks_or_blocked_by",
     r"whenever this creature blocks or becomes blocked"),
    ("creature_blocks_or_blocked_by",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) blocks or becomes blocked"),
    ("creature_attacks_or_blocks",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks or blocks"),
    ("creature_attacks_or_blocks",  r"whenever this creature attacks or blocks"),
    ("attackers_declared",
     r"whenever (?P<any_attacking_seat>)a player attacks with "
     r"(?P<attackers_count>[a-z]+) or more (?P<attacker_subjects>[^,]+)"),
    ("matching_creature_attacks_or_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) attacks or blocks"
     r"(?![^,])"),
    ("matching_creature_attacks",
     r"whenever (?P<attacker_subject>(?:a|another) [^,]+) attacks"
     r" (?P<attacker_attacking_you>)you(?![a-z])"),
    ("matching_creature_attacks",
     r"whenever (?P<attacker_subject>(?:a|another) [^,]+) attacks(?! and isn't blocked)"),
    ("attackers_declared",
     r"whenever you attack with (?P<attackers_count>[a-z]+) or more (?P<attacker_subjects>[^,]+)"),
    ("attackers_declared",
     r"whenever (?P<attackers_defending_you>)one or more "
     r"(?P<attacker_subjects>[^,]+) attack you(?![a-z])"),
    ("attackers_declared",
     r"whenever (?P<all_attackers>)all (?P<attacker_subjects>[^,]+) attack(?![a-z])"),
    ("attackers_declared",
     r"whenever this creature and at least (?P<others_count>[a-z]+) other creatures attack"),
    ("opponent_attackers_declared",
     r"whenever an opponent attacks with creatures"),
    ("opponent_casts_nth_spell_each_turn",
     r"whenever an opponent casts their (?P<spell_ordinal>[a-z]+) spell each turn"),
    ("attacks_unblocked",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks and isn't blocked"),
    ("attacks_unblocked",           r"whenever this creature attacks and isn't blocked"),
    ("creature_attacks",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks"),
    ("creature_attacks",
     r"whenever this creature attacks (?P<attacks_alone>)alone"),
    ("creature_attacks",            r"whenever this creature attacks"),
    ("creature_blocks",
     r"whenever this creature blocks (?P<blocked_subject>(?:an?|another) [^,]+)"),
    ("creature_blocks",
     r"whenever this creature blocks (?P<block_pair_count>[a-z]+) or more "
     r"(?P<blocked_subjects>[^,]+)"),
    ("creature_blocks",             r"whenever this creature blocks"),
    ("matching_creature_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) blocks "
     r"(?P<blocked_subject>(?:an?|another) [^,]+)"),
    ("matching_creature_becomes_blocked",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) becomes blocked by "
     r"(?P<blocker_subject>(?:an?|another) [^,]+)"),
    ("matching_creature_becomes_blocked",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) becomes blocked(?! by)"),
    ("matching_creature_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) blocks"
     r"(?! or becomes blocked)(?![^,])"),
    ("creature_becomes_blocked",
     r"whenever this creature becomes blocked by "
     r"(?P<blocker_subject>(?:an?|another) " + _NEGATED_ADJECTIVE_RUN + r"[^,]+)"),
    ("creature_becomes_blocked",    r"whenever this creature becomes blocked"),
    ("creature_becomes_blocked",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) becomes blocked"),
    ("creature_dealt_damage",
     r"whenever enchanted (?P<damaged_attached>[a-z]+) is dealt damage"),
    ("creature_dealt_damage",
     r"whenever this creature is dealt (?P<damage_combat>combat) damage"),
    ("creature_dealt_damage",               r"whenever this creature is dealt damage"),
    ("creature_dealt_damage",
     r"whenever (?P<damaged_subject>an? [^,]+) is dealt damage"),
    ("creature_dealt_damage_by_self_dies",  r"whenever a creature dealt damage by this creature this turn dies"),
    ("creature_dealt_damage_by_attached_dies",
     r"whenever a creature dealt damage by (?:enchanted|equipped) creature "
     r"this turn dies"),
    ("self_becomes_target",
     r"when(?:ever)? enchanted (?P<targeted_attached>[a-z]+) becomes "
     r"the target of (?P<targeted_by>a spell or ability|an aura spell|a spell"
     r"|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    ("self_becomes_target",
     r"whenever this (?:creature|artifact|enchantment|land|aura|permanent) becomes "
     r"the target of (?P<targeted_by>a spell or ability|an aura spell|a spell"
     r"|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    ("self_becomes_target",
     r"whenever (?P<targets_you_or_your_permanent>)you or a permanent you "
     r"control becomes the target of (?P<targeted_by>a spell or ability"
     r"|an aura spell|a spell|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    ("self_becomes_target",
     r"whenever (?P<targeted_subject>(?:an?|another) [^,]+?) becomes "
     r"the target of (?P<targeted_by>a spell or ability|an aura spell|a spell"
     r"|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    ("permanent_becomes_untapped",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) becomes untapped"),
    ("permanent_becomes_untapped",
     r"whenever (?P<untapped_subject>an? .+?) becomes untapped"),
    ("phases_out",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) phases out"),
    ("phases_in",
     r"whenever this (?:creature|artifact|enchantment|land|permanent) phases in"),
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
    ("permanent_becomes_tapped",
     r"when(?:ever)? enchanted (?P<tapped_attached>[a-z]+) becomes tapped"),
    ("permanent_becomes_tapped",
     r"when(?:ever)? this (?P<tapped_self>creature|artifact|enchantment|land|permanent)"
     r" becomes tapped"),
    ("permanent_becomes_tapped",
     r"whenever an? (?P<tapped_subtype>[a-z]+)"
     r"(?: (?P<tapped_controller>an opponent controls|you control))? becomes tapped"),
    ("permanent_becomes_tapped",
     r"whenever (?P<tapped_subject>an? .+?) becomes tapped"),
    ("land_tapped_for_mana",        r"whenever an? (?P<tapped_land_subtype>[a-z]+) is tapped for mana"),
    ("land_tapped_for_mana",
     r"whenever a player taps an? (?P<tapped_land_supertype>"
     + "|".join(sorted(_TYPE_LINE_SUPERTYPES)) + r") land for mana"),
    ("land_tapped_for_mana",        r"whenever a player taps a land for mana"),
    ("land_tapped_for_mana",
     r"whenever a player taps an? (?P<tapped_land_subtype>[a-z]+) for mana"),
    ("land_tapped_for_mana",
     r"whenever an opponent(?P<tapped_by_opponent>) taps an? "
     r"(?P<tapped_land_subtype>[a-z]+) for mana"),
    ("land_tapped_for_mana",
     r"whenever you(?P<tapped_by_you>) tap a land for mana"),
    ("land_tapped_for_mana",
     r"whenever you(?P<tapped_by_you>) tap an? "
     r"(?P<tapped_land_subtype>[a-z]+) for mana"),
    ("land_tapped_for_mana",
     r"whenever (?P<tapped_land_subject>an? .+?) is tapped for mana"),
    ("spell_cast",
     r"whenever a player casts a (?P<cast_colors>(?:white|blue|black|red|green)"
     r"(?:,? (?:or )?(?:white|blue|black|red|green))+) spell"),
    ("player_chooses_targets",      r"whenever a player chooses one or more targets"),
    ("spell_or_ability_put_onto_stack",
     r"whenever a spell or ability is put onto the stack"),
    ("spell_cast",                  r"whenever a player casts a (?P<color_word>white|blue|black|red|green) spell"),
    ("spell_cast",
     r"whenever a player casts a (?P<cast_multicolored>)multicolored spell"),
    ("spell_cast",
     r"whenever a player casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    ("spell_cast",
     r"whenever a player casts a spell of the chosen (?P<cast_chosen_color>)color"),
    ("spell_cast",
     r"whenever a player casts a spell with mana value (?P<cast_mana_value>\d+) "
     r"or (?P<cast_mana_value_bound>greater|less)"),
    ("spell_cast",
     r"whenever a player casts a spell with mana value equal to the number of "
     r"(?P<cast_mana_value_source_counters>[a-z]+) counters on "
     r"this (?:artifact|creature|enchantment|land|permanent)"),
    ("spell_cast",
     r"whenever a player casts a spell that shares a color or mana value with "
     r"the exiled (?P<cast_shares_with_exiled_card>)card"),
    ("spell_cast",
     r"whenever a player casts a (?P<cast_named_like_exiled_card>)card, if it "
     r"has the same name as one of the cards exiled with this artifact"),
    ("spell_cast",                  r"whenever a player casts a spell"),
    ("spell_cast",                  r"whenever a player kicks a spell(?P<cast_kicked>)"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a spell from anywhere other than their (?P<not_from_zone>hand)"),
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell "
     r"that doesn't share a color with (?P<unshared_color_subject>an? [^,]+)"),
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"
     r" other than the (?P<after_spell_ordinal>[a-z]+) (?P=cast_type) spell that player casts each turn"),
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"
     r" with (?P<cast_keyword>[a-z]+)"),
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<cast_colors>(?:white|blue|black|red|green)"
     r"(?:,? (?:or )?(?:white|blue|black|red|green))+) spell"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<color_word>white|blue|black|red|green) spell"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<cast_multicolored>)multicolored spell"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a spell that targets "
     r"(?P<targets_you_or_your_creature>)you or a creature you control"),
    ("opponent_casts_spell",        r"whenever an opponent casts a spell"),
    ("your_spell_countered",        r"whenever a spell you've cast is countered"),
    ("you_cast_spell",
     r"whenever you cast a spell that's (?P<cast_colors>[a-z]+(?:, [a-z]+)*,? or [a-z]+)"),
    ("you_cast_first_spell_each_turn",
     r"whenever you cast your first (?P<cast_types>instant or sorcery) spell each turn"),
    ("you_cast_first_spell_each_turn",
     r"whenever you cast your first (?P<cast_type>noncreature|nonartifact|creature|artifact|instant|sorcery) spell each turn"),
    ("you_cast_spell",
     r"whenever you cast an (?P<cast_types>instant or sorcery) spell"),
    ("you_cast_spell",
     r"whenever you cast an? (?P<cast_type>noncreature|nonartifact|creature|artifact|instant|sorcery) spell"
     r" with mana value (?P<cast_mana_value>\d+) or (?P<cast_mana_value_bound>greater|less)"),
    ("you_cast_spell",
     r"whenever you cast an? (?P<cast_type>noncreature|nonartifact|creature|artifact|instant|sorcery) spell"),
    ("you_cast_spell",
     r"whenever you cast a (?P<cast_multicolored>)multicolored spell"),
    ("you_cast_spell",
     r"whenever you cast a non(?P<cast_excluded_color>white|blue|black|red|green) spell"),
    ("you_cast_spell",
     r"whenever you cast a (?P<color_word>white|blue|black|red|green) spell"),
    ("you_cast_spell",              r"whenever you cast a (?P<cast_subtype>[a-z][a-z-]+) spell"),
    ("you_cast_spell",              r"whenever you cast a spell"),
    ("you_play_card",               r"whenever you play a card"),
    ("enchantment_cast",            r"whenever you cast an enchantment spell"),
    ("land_enters",                 r"whenever a land enters(?: the battlefield)?"),
    ("matching_permanent_enters",
     r"whenever " + _SOURCE_UNION_HEAD + r"(?P<enterer_subject>another [^,]+?) enters"
     r"(?: the battlefield)?(?P<enterer_includes_source>)"),
    ("matching_permanent_enters",
     r"whenever (?P<enterer_subject>(?:an?|another) [^,]+) enters(?: the battlefield)?"),
    ("matching_permanent_enters",
     r"whenever a player puts (?P<enterer_subject>an? [^,]+?) onto the battlefield"),
    ("matching_permanent_enters",
     r"whenever (?P<enterer_subject>an? [a-z]+(?:, [a-z]+)+,? or [a-z]+)"
     r" enters(?: the battlefield)?"),
    ("matching_permanent_leaves_battlefield",
     r"whenever (?P<leaver_subject>(?:a|an|another) [^,]+?) leaves the battlefield"),
    ("permanent_returned_to_hand",
     r"whenever (?P<returned_subject>(?:a|an|another) [^,]+?) is returned to "
     r"a player's hand"),
    ("permanent_turned_face_up",
     r"whenever (?P<turned_subject>(?:a|an|another) [^,]+?) is turned face up"),
    ("one_or_more_attack",          r"whenever one or more creatures you control attack"),
    ("one_or_more_deal_combat_damage",
     r"whenever one or more (?P<damagers_subjects>.+?) deal combat damage to a player"),
    ("counters_put_on_creature",
     r"whenever one or more \+1/\+1 counters are put on another "
     r"non-(?P<counters_excluded_subtype>[a-z]+) creature you control"),
    ("you_gain_life",               r"whenever you gain life"),
    ("you_lose_life",               r"whenever you lose life"),
    ("you_win_coin_flip",           r"whenever you win a coin flip"),
    ("library_shuffled",
     r"whenever a spell or ability causes a player to shuffle their library"),
    ("you_sacrifice_permanent",     r"whenever you sacrifice a permanent"),
    ("you_activate_loyalty_ability",
     r"whenever you activate a loyalty ability of (?P<walker_subject>an? [^,]+)"),
    ("land_played",
     r"whenever (?:you play|(?P<land_player>an opponent|a player) plays) "
     r"(?:a|(?P<other_land>another)) (?:(?P<played_land_supertype>nonbasic|basic) )?land"),
    ("draws_card",
     r"whenever (?:you draw|(?P<drawer>an opponent|a player) draws) a card"),
    ("draws_second_card",           r"whenever you draw your second card each turn"),
    ("revealed_drawn_card",
     r"whenever you reveal (?P<revealed_subject>an? [^,]+) card this way"),
    ("counters_reach_threshold",
     r"whenever (?:there are |this (?:artifact|creature|enchantment|permanent|land) has )"
     r"(?P<counter_count>[a-z]+) or more (?P<counter_kind>[a-z]+) counters on "
     r"(?:this (?:artifact|creature|enchantment|permanent|land)|it)"),
    ("permanent_counters_reach_threshold",
     r"whenever (?P<countered_subject>an? [^,]+?) has (?P<counter_count>[a-z0-9]+) or more "
     r"(?P<counter_kind>[-+/0-9a-z]+) counters on it"),
    ("source_power_at_least",
     r"whenever this creature's power is (?P<power_count>[a-z0-9]+) or greater"),
    ("source_has_no_counters",
     r"whenever this (?:artifact|aura|creature|enchantment|permanent|land) "
     r"has no (?P<counter_kind>[-+/0-9a-z]+) counters? on it"),
    ("source_has_keyword",
     r"whenever this creature has (?P<keyword_name>[a-z]+)"),
    ("life_at_most",
     r"whenever (?:you have|(?P<life_seat>an opponent) has) "
     r"(?P<life_count>[a-z0-9]+) or less life"),
    ("life_at_least",
     r"whenever (?:you have|(?P<life_seat>an opponent) has) "
     r"(?P<life_count>[a-z0-9]+) or more life"),
    ("cumulative_upkeep_unpaid",
     r"whenever a player doesn't pay this "
     r"(?:artifact|creature|enchantment|permanent|land)'s cumulative upkeep"),
    ("permanent_dies",
     r"whenever " + _SOURCE_UNION_HEAD + r"(?P<dying_subject>another [^,]+?) dies"
     r"(?P<dying_includes_source>)"),
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) dies"),
)
