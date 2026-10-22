"""The "whenever" trigger-condition table (CR 603.1).

Each row is ``(kind, pattern)``: the condition kind a dispatcher is addressed
by, and a regex that **delimits** the printed condition. Its named groups are
the condition's payload, and what a group holds is read elsewhere — a
``<name>_subject`` by the noun parser, a ``<name>_count`` by the number table
(``engine/trigger_conditions.py``'s ``_resolve_subject_groups``) — never
approximated here. Rows are checked in order and the first match wins, so a
row's position is part of what it means: a narrowed row sits above the
unqualified row its pattern is a prefix of, and the comment beside each says
why it is where it is.

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
    # "Whenever **a spell or ability an opponent controls causes** a land to be
    # put into your graveyard from the battlefield" (Sacred Ground). The same
    # event with a narrowing about **what caused it** — a permanent that died
    # to a state-based action, to its own upkeep, or to a spell its owner cast
    # is not what this card watches, and the graveyard looks identical in every
    # one of those cases.
    #
    # The cause is a payload key like every other narrowing on this row, and it
    # is answered where the discard seam answers the identical question for
    # Psychic Purge: `Game.resolving_seats` is CR 109.5's controller of whatever
    # is resolving, and an empty stack means nothing caused the death at all.
    # Before the three rows below because "to be put into" is not "is put into"
    # and neither could match this sentence — the position is documentation.
    ("permanent_dies",
     r"whenever a spell or ability (?P<dying_cause>an opponent) controls causes "
     r"(?P<dying_subject>an? [^,]+?) to be put into "
     r"(?P<dying_graveyard_owner>your|an opponent's) "
     r"graveyard from the battlefield"),
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
    # "…is put into **a player's** graveyard from the battlefield" (Liability).
    # The unnarrowed reading with the owner said out loud: CR 404.1 already
    # sends a permanent to its owner's pile, so "a player's" narrows nothing
    # that "a graveyard" did not already admit. One row with the bare spelling
    # rather than a fourth `dying_graveyard_owner` value, because a value the
    # dispatcher would have to read as "no restriction" is a restriction
    # waiting to be tested by accident.
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) is put into (?:a|a player's) "
     r"graveyard from the battlefield"),
    # "Whenever **a spell or ability an opponent controls destroys** a
    # noncreature permanent you control, you may destroy target permanent that
    # opponent controls." (Karmic Justice.) CR 701.8's keyword action as an
    # event, and **not** a spelling of the death rows above it: a sacrifice
    # puts the same card in the same graveyard and is not this (CR 701.21a), a
    # creature with toughness 0 is "put into its owner's graveyard" and is not
    # this (CR 704.5f), and a destroyed permanent a replacement exiled instead
    # never died and **is** this. So it has its own kind and its own seam
    # (`engine/destruction_events.py`), which the two destroy paths announce
    # from and nothing else does.
    #
    # Two narrowings, both payload. **What** was destroyed is a `_subject`
    # group read by the noun parser, so "a creature you control", "an artifact"
    # and "a nonland permanent an opponent controls" are this row with no
    # code — asked of the permanent as it last existed on the battlefield
    # (CR 603.10a). **Who** destroyed it is `destroyed_cause`, the seat CR
    # 109.5 gives the spell or ability that did it; the event carries that
    # seat or says there is none (CR 704.5g's lethal damage is a destruction
    # no spell or ability performs, whoever dealt the damage). One printed
    # value, for this table's rule that a narrowing is listed once the pool
    # prints it.
    #
    # "**Another**" stands where the article does, as it does on the entry and
    # departure rows: the noun parser folds it into the filter's own exclusion,
    # and the watcher is then not one of the permanents it watches. The grammar
    # reads that spelling whether or not this table does, and a condition only
    # one front end names compiles to a bare instruction on a permanent — so it
    # is listed although no card prints it.
    #
    # Neither a prefix of the two "…an opponent controls **causes**…" rows nor
    # prefixed by them — the verb is the fork — so the position is
    # documentation: beside the deaths it must not be confused with.
    ("permanent_destroyed",
     r"whenever a spell or ability (?P<destroyed_cause>an opponent) controls "
     r"destroys (?P<destroyed_subject>(?:an?|another) [^,]+)"),
    # "Whenever **another card** is put into **a** graveyard **from anywhere**."
    # (Planar Void.) Not a death and not the row above it: the object is a
    # *card*, the source zone is unnamed, and the pile is anybody's — so nothing
    # on a battlefield is being watched and no permanent-shaped narrowing could
    # express it. Announced from `Game.put_card_into_graveyard`, the one seam
    # every arrival passes through, which is what makes "from anywhere" a fact
    # rather than a list of fire sites.
    #
    # After the four `permanent_dies` rows because it is the widest reading
    # here; none of them could match this line ("from the battlefield" against
    # "from anywhere"), so the position is documentation rather than a guard.
    # "another" is CR 109.5 and is enforced by the event filter, not by a
    # payload: the comparison is between the moved card and the observer.
    ("card_put_into_graveyard",
     r"whenever (?P<another_card>)another card is put into a graveyard "
     r"from anywhere"),
    # "Whenever **a black card** is put into **an opponent's** graveyard from
    # anywhere, you may draw a card." (Compost.) The same event and the same
    # seam as the two rows around it, with two more printed narrowings — what
    # the card is, and whose pile it landed in — and both ride as data for the
    # reason `_card_put_into_graveyard_filter`'s docstring already gives about
    # its own pair: two kinds here would be two names for one event.
    #
    # Above the "another card" row is unnecessary (neither is the other's
    # prefix) and it is placed here anyway, beside the sibling it shares a
    # filter with, so the three spellings of one condition read together.
    ("card_put_into_graveyard",
     r"whenever (?P<graveyard_card_subject>an? [a-z]+ card) is put into "
     r"(?P<opponent_graveyard>)an opponent's graveyard from anywhere"),
    # "Whenever **a land card** is put into **your** graveyard **from your
    # library**, you may pay {1}. If you do, draw a card." (Pedantic Learning.)
    # The same event at the same seam with a third narrowing no sibling
    # prints: the zone the card *came out of*. It rides as data like the other
    # two — ``Game.put_card_into_graveyard`` already puts the source zone on
    # the event for every caller that names one — so a mill, a search that
    # bins a card and a look that discards the rest are this condition, and a
    # discard or a death is not.
    ("card_put_into_graveyard",
     r"whenever (?P<graveyard_card_subject>an? [a-z]+ card) is put into "
     r"(?P<your_graveyard>)your graveyard (?P<from_library>)from your library"),
    # "Whenever **you** discard a card" (Necropotence) beside "whenever **an
    # opponent** discards a card" (Megrim). CR 701.9a's discard is an action
    # abilities watch, and the two discard seams announce it — the random/forced
    # one and the chosen one — so both spellings of a discard reach this
    # condition rather than only the one the first card exercised.
    #
    # The seat is the trigger's own narrowing rather than a second kind, which
    # is exactly what `land_played` and `draws_card` record further down: one
    # announcement, made where the discard happens, and the printed word decides
    # whose discard it watches. The kind is named for the *event* for that
    # reason — it was `you_discard_card` while "you" was the only spelling the
    # pool printed, which is a kind named after one of its own narrowings.
    #
    # "Whenever **a player** discards a card, you may gain 1 life."
    # (Confessor.) The third printed seat, and the widest: every discard there
    # is, the controller's own included. The same capture, because the three
    # are one question with three answers and the fire site reads the answer.
    ("discards_card",
     r"whenever (?:you discard|(?P<discarder>an opponent|a player) discards) "
     r"a card"),
    # "Whenever a spell or ability an opponent controls causes you to discard
    # **a card**, you gain 2 life and you may draw a card." (Spiritual Focus.)
    # The **second dispatch scope** for the condition the "when" table carries
    # for Psychic Purge: that one is the discarded card's own ability,
    # functioning from the hand (CR 113.6), and this is a permanent on the
    # battlefield watching its controller's discards. One kind, told apart by
    # the marker, which is this table's standing rule — the event is the same
    # discard and the same seam announces it
    # (`mixins/draws_and_discards._announce_discard_triggers`).
    #
    # **Not** the row above, whose narrowing is only *who discarded*: this one
    # additionally asks what **caused** it (CR 109.5, read off `resolving_seats`
    # the way the damage seam derives its source seat), and a discard the player
    # made themselves — a cost, a cleanup — must not fire it. Above that row
    # because neither is the other's prefix and the pairing is what the reader
    # needs to see.
    ("discarded_by_opponent_effect",
     r"whenever a spell or ability an opponent controls causes you to "
     r"discard (?P<discarded_any_card>a card)"),
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
    # "Whenever **you're dealt damage**, you may put that many +1/+1 counters on
    # this creature." (Blood Hound.) CR 120.4b's event in the passive voice,
    # which is the row below with the damager left out — and leaving it out is
    # the sentence saying *any* source, exactly what `damager_any` means there.
    # So it is the same kind, the same announcement and the same dispatcher,
    # with markers rather than captures: `damage_recipient` names the seat and
    # `damager_any` is the empty-group idiom this table uses wherever a row
    # states a narrowing by matching rather than by capturing text.
    #
    # **Above** the active row, which it is not a prefix of and which would
    # claim it anyway: `(?P<damager_subject>[^,]+?)` matches "you're" and then
    # fails on the missing "deals", and a subject group the noun parser cannot
    # read refuses the whole condition rather than falling through to a later
    # pattern — the ordering rule this table states a few rows up.
    ("damage_dealt",
     r"whenever (?P<damage_recipient>you)(?:'re| are) dealt "
     r"(?:(?P<damage_combat>combat|noncombat) )?damage(?P<damager_any>)"),
    ("damage_dealt",
     r"whenever (?:"
     r"(?P<damager_self>this (?:creature|artifact|enchantment|land|aura|permanent))"
     r"|(?P<damager_attached>enchanted (?:creature|artifact|enchantment|land|permanent))"
     r"|a source (?P<damager_controller>you) control"
     # "Whenever **a source** deals damage to this creature" (Crag Saurian).
     # The damager narrowed by nothing at all — CR 109.5's word covers a spell,
     # an ability and a permanent alike, and no `ObjectFilter` can name the
     # first two. So it is a **marker** group rather than a subject one: read
     # through the noun parser, "a source" would become a filter, and a filter
     # is a description of permanents that would silently exclude every spell
     # the card watches. Above `damager_subject`, whose `[^,]+?` would claim it.
     r"|(?P<damager_any>a source)"
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
     # freezes (`target_permanent_id`).
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
    # "…blocks **or becomes blocked by** a non-Wall creature" (Thicket Basilisk,
    # Cockatrice), "…by a green or white creature" (Abomination), "…by a
    # creature" (Aisling Leprechaun). One printed sentence joining the two
    # events either half of it already names, and the noun phrase distributes
    # over **both** verbs — the Basilisk destroys no Wall whichever side of the
    # block it was on. So the phrase is delimited once and lands under both
    # halves' filter keys (`_PAIR_SUBJECT_GROUP_SUFFIX`), and the two general
    # dispatchers in phases/block_triggers.py read it exactly as they
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
    # use and says so in the payload. `engine/event_filters.py`'s filter is what reads
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
    # "Whenever **a creature attacks or blocks**, this enchantment deals 2
    # damage to it." (Powerstone Minefield.) CR 508.1 and CR 509.1 as one
    # printed condition over the whole board — the union
    # `creature_attacks_or_blocks` is for a source and its host, watched by a
    # permanent that is neither. Its own kind for the reason those two give
    # each other: one kind, announced at both combat fire sites, so the
    # condition cannot be read as half of itself.
    #
    # Above the two per-attacker rows, which are strict prefixes of it and
    # which claimed it: matched there, " or blocks" is left as the head of the
    # *effect* and the trigger is an attack trigger that never sees a block.
    # The trailing lookahead is the bare block row's — the condition ends at
    # the comma, so "…attacks or blocks a Wall" is refused rather than read as
    # this with its partner phrase dropped.
    ("matching_creature_attacks_or_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) attacks or blocks"
     r"(?![^,])"),
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
    # "Whenever **one or more creatures attack you**." (Orim's Prayer.) The
    # declaration again, asked from CR 506.2's defending side — so the marker
    # turns off the "you are the attacking seat" test above and narrows the
    # attackers counted to the ones aimed at this permanent's controller.
    #
    # It is *not* `matching_creature_attacks`, which does read "attacks you":
    # that announcement is per attacker, so an ability reading "one or more"
    # would fire once for each of them. Orim's Prayer gains 1 life for each
    # attacking creature, so three attackers would be three triggers of three
    # life — N squared, and right on any board where exactly one creature
    # attacks. CR 509.1 makes the declaration one event and this is a card that
    # can tell the difference.
    ("attackers_declared",
     r"whenever (?P<attackers_defending_you>)one or more "
     r"(?P<attacker_subjects>[^,]+) attack you(?![a-z])"),
    # "Whenever **all** non-Wall creatures you control attack" (Mob Mentality).
    # A third question about the same declaration, and the one that is not a
    # count at all: it asks whether the set the noun phrase describes and the
    # set that attacked are the same. So it is a marker rather than an
    # `attackers_count` — "all" is not a number, and spelling it as one would
    # be a trigger that fires on any attack once you control that many.
    #
    # The empty named group is the `any_attacking_seat` idiom above: present in
    # the groupdict exactly when this row matched, carrying no text to re-read.
    # Ordered above the bare per-creature rows for the reason the two count
    # rows are — "all non-Wall creatures you control" is a noun phrase
    # `matching_creature_attacks` would happily read if it opened with "a".
    ("attackers_declared",
     r"whenever (?P<all_attackers>)all (?P<attacker_subjects>[^,]+) attack(?![a-z])"),
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
    # "**When enchanted creature attacks**, return it and this Aura to their
    # owners' hands at end of combat." (Contempt.) The declaration watched by
    # an Aura rather than by the attacker, above the source's own spelling for
    # the reason every attached row in this table sits above its unattached
    # twin: one kind, because it is one event, and which permanent's ability is
    # watching is the narrowing — payload, exactly as `combatant_attached` is on
    # `creature_attacks_or_blocks` two screens up. The declare-attackers fire
    # site reads the key and scans the attacker's attachments beside its own
    # abilities.
    #
    # Below the two `attacks_unblocked` rows, whose printed words this one is a
    # strict prefix of: matched first it would read "and isn't blocked" as the
    # effect clause, which is a trigger firing on every attack where the card
    # fires on an unblocked one.
    ("creature_attacks",
     r"whenever enchanted (?P<combatant_attached>[a-z]+) attacks"),
    # "Whenever this creature **attacks alone**, …" (Reckless Ogre; CR 506.5,
    # and the same words CR 702.83a defines exalted with). The same event as
    # the bare row below — one declaration, one announcement, the attacker's
    # own ability — narrowed by a fact about the *declaration* rather than
    # about the attacker: was it the only creature declared. So it is payload
    # on `creature_attacks` rather than a kind of its own, and
    # `_fire_creature_attacks_triggers` reads the marker against the size of
    # the declaration it was handed.
    #
    # **Above** the bare row, whose printed words this one is a strict suffix
    # of: matched first, that row consumes "whenever this creature attacks" and
    # leaves "alone" at the head of the effect clause — a trigger firing on
    # every attack where the card fires on a solo one, with the narrowing word
    # then refusing the effect. The empty named group is this table's marker
    # idiom: present in the groupdict exactly when this row matched, carrying
    # no text of its own to re-read.
    ("creature_attacks",
     r"whenever this creature attacks (?P<attacks_alone>)alone"),
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
    # phases/block_triggers.py off the same `block_pair_count` key
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
    # **The board-wide pair.** "Whenever **a creature** blocks a creature with
    # lesser power" / "…**a creature** becomes blocked by a creature with lesser
    # power" (No Quarter). The same two events the four rows around this one
    # read, watched by a permanent that is neither combatant nor attached to
    # one — so both halves of the pair are noun phrases and the *source* is in
    # no combat at all.
    #
    # Their own kinds rather than the source-scoped ones with a wider subject,
    # for `matching_creature_attacks`' reason two hundred lines up: the
    # source-scoped kinds are announced by a scan over the combatant's own card
    # and its attachments, and a permanent watching the whole board is reached
    # by the event bus instead. One kind per announcement site is what keeps a
    # trigger from firing twice or not at all.
    #
    # ``combatant_subject`` is the creature the event is *about* and the other
    # group is its partner, exactly as on the source-scoped rows — so the
    # dispatcher reads one pair of keys whichever row matched. The partner
    # phrase is the one that carries "with lesser power", and it is answered
    # against the combatant, which is what the fire site supplies as the
    # comparison's source.
    ("matching_creature_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) blocks "
     r"(?P<blocked_subject>(?:a|another) [^,]+)"),
    ("matching_creature_becomes_blocked",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) becomes blocked by "
     r"(?P<blocker_subject>(?:a|another) [^,]+)"),
    # The **bare** spellings of the same two events: "Whenever a creature
    # blocks, …" (Heat of Battle), "Whenever a Sliver becomes blocked, …"
    # (Spined Sliver). CR 509.3c/509.3d is the whole difference between these
    # rows and the two above — a condition with no partner phrase fires once for
    # the creature the event is about, however many creatures are on the other
    # side, where a narrowed one fires once per creature its phrase admits. Two
    # announcements, and ``event_filters._board_wide_block_filter`` is what keeps a
    # trigger on exactly the one its own narrowing asks for.
    #
    # Below the narrowed rows, in this table's standing specific-before-generic
    # order: each of these *is* a strict prefix of the row above it, so read
    # first it would take the partner phrase and drop it — the trigger firing on
    # every block instead of the ones the card names.
    #
    # The lookahead is `matching_creature_attacks`' "and isn't blocked" idiom:
    # "blocks or becomes blocked by …" is a *different* event
    # (`creature_blocks_or_blocked_by`), and matched here its tail would be read
    # as nothing at all.
    ("matching_creature_becomes_blocked",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) becomes blocked(?! by)"),
    ("matching_creature_blocks",
     r"whenever (?P<combatant_subject>(?:a|another) [^,]+?) blocks"
     r"(?! or becomes blocked)(?![^,])"),
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
    # "Whenever this creature is dealt **combat** damage" (Wall of Essence, Wall
    # of Souls). The same event as the row below, narrowed to the half of it a
    # combat damage step deals — payload rather than a kind, under the very key
    # `damage_dealt` records the same printed word on
    # (``event_filters._damage_dealt_filter``), because one printed word read by two
    # spellings is how the two dispatch scopes come to disagree about what it
    # means. Above the bare row it is not a prefix of, in this table's usual
    # order.
    ("creature_dealt_damage",
     r"whenever this creature is dealt (?P<damage_combat>combat) damage"),
    ("creature_dealt_damage",               r"whenever this creature is dealt damage"),
    # "Whenever **a creature** is dealt damage, destroy it." (Death Pits of
    # Rath.) The board-wide spelling of the two rows above: the observer is
    # neither the damaged creature nor attached to it, so the noun phrase is
    # delimited as a `damaged_subject` group and the damage fire site tests it
    # against the permanent that took the damage. Below the two narrower rows in
    # this table's usual order, though neither is a prefix of this one — "this"
    # and "enchanted" are not articles.
    ("creature_dealt_damage",
     r"whenever (?P<damaged_subject>an? [^,]+) is dealt damage"),
    ("creature_dealt_damage_by_self_dies",  r"whenever a creature dealt damage by this creature this turn dies"),
    # "Whenever a creature dealt damage by **enchanted creature** this turn
    # dies, put a +1/+1 counter on that creature." (Vampiric Embrace.) Sengir
    # Vampire's condition read off an attachment instead of off the ability's
    # own permanent -- which is a different *observer relationship*, not a
    # narrowing of the same one, exactly as `attached_creature_dies` is a
    # different kind from `creature_dies` and for the same reason: the fire site
    # finds the observer by a different route (`_fire_creature_dies_triggers`
    # compares the damagers against the observer for the row above and against
    # what the observer is attached to for this one), and a kind is what a fire
    # site dispatches on.
    #
    # Both attachment words (CR 301.5f): an Equipment printing the sentence is
    # the same rule, and the row that reads only one of them is the drift this
    # file's other comments keep naming.
    ("creature_dealt_damage_by_attached_dies",
     r"whenever a creature dealt damage by (?:enchanted|equipped) creature "
     r"this turn dies"),
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
    # "When **enchanted creature** becomes the target of a spell or ability,
    # destroy that creature." (Spinal Graft.) The same CR 603.2 event watched by
    # something attached to the targeted permanent rather than by the permanent
    # itself — one kind, with `targeted_attached` saying which permanent's
    # ability is watching, exactly as `damaged_attached` does for the damage
    # event and `tapped_attached` for the tap. The fire site is the same one
    # (`mixins/target_announcements._announce_targeting`); what tells the two
    # dispatch scopes apart is this group, read by
    # `event_filters._self_becomes_target_filter`.
    #
    # Above the self spelling, in the order this table's own note asks for.
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
    # "Whenever **you or a permanent you control** becomes the target of a spell
    # or ability an opponent controls, you may draw a card." (Rayne, Academy
    # Chancellor.)
    #
    # The **third dispatch scope** for one event, and the shape Death Pits of
    # Rath already forced on `creature_dealt_damage`: the two rows above watch
    # the targeted permanent itself and the thing attached to it, and this one
    # watches neither — Rayne is a third party, and what it is about is a seat's
    # whole side of the board. So it is a narrowing on the same kind rather than
    # a kind of its own, which is this table's standing rule, and
    # `event_filters._self_becomes_target_filter` is where the three scopes are told
    # apart.
    #
    # Its subject is the one thing none of the rows above can express: it spans
    # a **player** and a set of permanents at once. That is why the marker is an
    # empty group rather than a `_subject` phrase — there is no single noun
    # phrase to hand the noun parser, because half of what it names is not an
    # object at all. `targeted_seats`' twin one screen up (Reparations'
    # `targets_you_or_your_creature`) says the same thing about a *cast*.
    ("self_becomes_target",
     r"whenever (?P<targets_you_or_your_permanent>)you or a permanent you "
     r"control becomes the target of (?P<targeted_by>a spell or ability"
     r"|an aura spell|a spell|an ability)"
     r"(?: (?P<targeting_controller>an opponent controls|you control))?"),
    # "Whenever **a creature** becomes the target of a spell or ability, return
    # that creature to its owner's hand." (Cowardice.)
    #
    # The **fourth dispatch scope**, and the widest: the observer is neither the
    # targeted object, nor attached to it, nor its controller — Cowardice
    # watches every creature on every battlefield. So the subject is a printed
    # *noun phrase* delimited as a `_subject` group, exactly as the death rows
    # above delimit theirs, and `event_filters._self_becomes_target_filter` asks
    # `subject_matches` with it.
    #
    # **Last** of the four, and the position is a guard rather than
    # documentation: `an? [^,]+?` would claim "an opponent controls" out of the
    # narrowed spellings above and read the rest as a noun phrase, so a row
    # placed first would take the three narrower scopes' lines and answer them
    # through a filter instead of through the identity test each of them needs.
    #
    # "Whenever **another** permanent you control becomes the target of a spell
    # or ability an opponent controls, you may return that permanent to its
    # owner's hand." (Cloud Cover.) "Another" sits where the article does and
    # is inside the delimited phrase, so the noun parser folds it into
    # ``exclude_self`` exactly as it does for the entry rows' "another Rogue" —
    # and ``event_filters._self_becomes_target_filter`` hands ``subject_matches`` the
    # watching permanent as its source, which is what the key is tested
    # against. An alternative of the article rather than a row of its own:
    # every axis after the noun is this row's.
    ("self_becomes_target",
     r"whenever (?P<targeted_subject>(?:an?|another) [^,]+?) becomes "
     r"the target of (?P<targeted_by>a spell or ability|an aura spell|a spell"
     r"|an ability)"
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
    # (engine/event_filters.py::_becomes_tapped_filter) covers every card written this
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
    # "Whenever **an opponent** taps a Mountain for mana, you may gain 1 life."
    # (Sanctimony.) The active voice again with CR 109.5's seat printed where
    # the rows above print "a player" — so the *seat* is the narrowing and the
    # land type stays the same payload group the row above it carries. One kind,
    # two printed narrowings, which is CLAUDE.md's rule stated the usual way
    # round: a narrowing is data, not a kind.
    #
    # ``tapped_by_opponent`` is an empty named group, the spelling this table
    # already uses for a marker with nothing to capture (``another_card``,
    # ``your_graveyard``). It is tested at the tap seam against the *watching
    # permanent's* controller, never against the active player: dropped, a
    # Sanctimony would gain its controller life for their own Mountains, which
    # is a strictly better card than the one printed and one nothing in this
    # repo could see — the trigger fires, the life is gained, and every census
    # reads the card as implemented.
    ("land_tapped_for_mana",
     r"whenever an opponent(?P<tapped_by_opponent>) taps an? "
     r"(?P<tapped_land_subtype>[a-z]+) for mana"),
    # "Whenever **you** tap a land for mana, remove a +1/+1 counter from this
    # creature." (Savage Firecat.) The third seat the active voice prints, and
    # the opposite narrowing from the row above: ``tapped_by_you`` is tested at
    # the tap seam against the watching permanent's controller too, and
    # dropped it is a Firecat that shrinks every time *anybody* taps a land —
    # a trigger firing on a strictly larger set, the direction no census sees.
    #
    # The bare "a land" row first and the land-type row after it, for the
    # reason the "a player" pair above is ordered that way.
    ("land_tapped_for_mana",
     r"whenever you(?P<tapped_by_you>) tap a land for mana"),
    ("land_tapped_for_mana",
     r"whenever you(?P<tapped_by_you>) tap an? "
     r"(?P<tapped_land_subtype>[a-z]+) for mana"),
    # "Whenever **a land an opponent controls** is tapped for mana" (Mana Web).
    # The passive voice with a whole *noun phrase* where the three rows above
    # carry a single word — so it is a `_subject` group read by the noun parser,
    # exactly as `permanent_becomes_tapped` reads its own. **Last** of the four:
    # `an? [a-z]+` claims "a Mountain is tapped for mana" and this pattern would
    # too, and a subject row placed first would take the narrow rows' lines and
    # answer them through a filter where they answer through a type accessor.
    #
    # The seat rides the filter as ``controller``, which
    # ``subject_filters.subject_matches`` answers against the ability's own
    # controller (CR 109.5) — so a Mana Web whose controller taps a land does
    # not trigger, which is the whole of what the word "opponent" buys.
    ("land_tapped_for_mana",
     r"whenever (?P<tapped_land_subject>an? .+?) is tapped for mana"),
    # A colour-narrowed cast trigger (the Rod/Cup/Sphere cycle). The colour is
    # captured into the condition payload so one dispatcher covers every card
    # written this way; must precede the unnarrowed form below.
    # "Whenever a player casts a **green or white** spell" (Putrefaction). The
    # same narrowing over a *union* of colours (CR 105.2b: an object is each of
    # its colours, so any listed one answers), carried in the `cast_colors` key
    # Quirion Dryad's row below already uses rather than a second spelling of
    # the question — `cast_event_filters._cast_narrowing_admits` reads both. Before the
    # single-colour row, which is its strict prefix: matched there, "green"
    # would be read and "or white spell" left unconsumed.
    ("spell_cast",
     r"whenever a player casts a (?P<cast_colors>(?:white|blue|black|red|green)"
     r"(?:,? (?:or )?(?:white|blue|black|red|green))+) spell"),
    # "Whenever a player chooses one or more targets" (Psychic Battle).
    # CR 601.2c's choice as an event of its own, and deliberately not a
    # narrowing of the cast row below: a spell's targets, an activated
    # ability's (CR 602.2b), a triggered ability's (CR 603.3d) and a target
    # changed by an effect (CR 115.7) are all this event, and three of those
    # four are not casts. Announced by `Game.announce_targets_chosen`, the one
    # seam every way a stack object comes to have targets goes through; "one or
    # more" is CR 115.6's own wording and is what that seam asks before it
    # announces anything.
    ("player_chooses_targets",      r"whenever a player chooses one or more targets"),
    ("spell_cast",                  r"whenever a player casts a (?P<color_word>white|blue|black|red|green) spell"),
    # "Whenever a player casts a **multicolored** spell". Printed where a
    # colour word goes and not a colour (CR 105.4) — a count of them, two or
    # more (CR 105.2b) — so it is a marker group of its own rather than a sixth
    # word in the colour alternation above, which would be looked up in the
    # colour table and found to name none. One narrowing on all three cast
    # scopes, read by the one helper (`cast_event_filters._cast_narrowing_admits`).
    ("spell_cast",
     r"whenever a player casts a (?P<cast_multicolored>)multicolored spell"),
    # The same narrowing on the spell's *type* rather than its colour (Urza's
    # Chalice). Written with the group name `you_cast_spell`'s rows already use,
    # so all three cast kinds ask one helper (`cast_event_filters._cast_narrowing_admits`)
    # rather than each growing its own type test. Must precede the bare row.
    ("spell_cast",
     r"whenever a player casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    # "Whenever a player casts a spell **of the chosen color**" (Jeweled
    # Torque). CR 614.1c's choice, made as the permanent entered and recorded on
    # it, so the narrowing is a colour the sentence never names and only a
    # dispatcher holding the *source* can answer — which is why it is a marker
    # group rather than a colour word. Before the bare row below, whose pattern
    # is its strict prefix: matched there the four words were left to the effect
    # parser, which is the one thing that saved the card from firing on every
    # spell in the game.
    ("spell_cast",
     r"whenever a player casts a spell of the chosen (?P<cast_chosen_color>)color"),
    ("spell_cast",                  r"whenever a player casts a spell"),
    # "Whenever a player **kicks** a spell" (Saproling Infestation). CR 702.33d:
    # a spell is kicked when "its controller declared the intention to pay" its
    # kicker cost, which is part of casting it (CR 601.2b) -- so this is the
    # cast event narrowed by a fact about the cast, not a second event. The
    # marker group is what the dispatcher reads (`cast_event_filters._spell_cast_filter`,
    # against the ``kicked`` flag every cast announces); a row without it would
    # be the bare trigger above under another spelling, firing on every spell.
    ("spell_cast",                  r"whenever a player kicks a spell(?P<cast_kicked>)"),
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
    # "…a creature spell **with flying**" (Hidden Spider). A narrowing on an
    # *ability* of the spell rather than on its type line, so it is its own
    # payload key and `cast_event_filters._cast_narrowing_admits` reads it off the card
    # being cast. Above the bare type row below, which is its strict prefix:
    # matched there the clause would be left unread and the Spider would wake
    # for every creature an opponent cast, which is the silent widening this
    # table is ordered longest-first to prevent.
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"
     r" with (?P<cast_keyword>[a-z]+)"),
    # "Whenever an opponent casts an artifact spell" (Citanul Druid) — the
    # type narrowing again, on the opponent-scoped kind. Before the bare row.
    ("opponent_casts_spell",
     r"whenever an opponent casts an? (?P<cast_type>noncreature|nonartifact|creature|artifact|enchantment|instant|sorcery|land) spell"),
    # The colour narrowing on the opponent-scoped kind (Freyalise's Charm,
    # Leshrac's Sigil), captured into the same `color_word` payload the
    # player-scoped row above uses — one narrowing read by one helper
    # (`cast_event_filters._cast_narrowing_admits`), not a second spelling of the question.
    # Before the bare row, which is its strict prefix.
    # "Whenever an opponent casts a **blue or black** spell" (Snake Pit). The
    # colour *union* on the opponent-scoped kind, in the `cast_colors` key its
    # player-scoped twin above uses — one narrowing, one reader. Before the
    # single-colour row, whose pattern is its strict prefix.
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<cast_colors>(?:white|blue|black|red|green)"
     r"(?:,? (?:or )?(?:white|blue|black|red|green))+) spell"),
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<color_word>white|blue|black|red|green) spell"),
    # "Whenever an opponent casts a **multicolored** spell, you gain 4 life."
    # (Rewards of Diversity.) The marker its player-scoped twin above carries.
    ("opponent_casts_spell",
     r"whenever an opponent casts a (?P<cast_multicolored>)multicolored spell"),
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
    # "Whenever a spell you've cast is countered" (Multani's Presence).
    # CR 701.6a's cancel rather than CR 701.5's cast — the announcement is made
    # where a spell is taken off the stack cancelled
    # (``mixins/stack/resolution.counter_stack_object``), which is neither of
    # the two moments the cast rows above name. Below them because it shares no
    # prefix with any of them and this table is ordered longest-first only where
    # one pattern could claim another's line.
    #
    # No narrowing group: the printed seat word is the whole of the condition
    # and it is answered by the announcement's ``seat``
    # (``event_filters._SEAT_SCOPED_EVENTS``), not by a payload key — CR 109.5's "you"
    # is the watching permanent's controller, and the caster is what the event
    # already carries.
    ("your_spell_countered",        r"whenever a spell you've cast is countered"),
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
    # "Whenever you cast a **multicolored** spell". **Before the subtype row
    # below**, whose `[a-z][a-z-]+` would take the word for a creature type —
    # and a trigger narrowed to a subtype called "multicolored" compiles,
    # reports supported and never fires.
    ("you_cast_spell",
     r"whenever you cast a (?P<cast_multicolored>)multicolored spell"),
    # "Whenever you cast a **nonred** spell" (Dwarven Patrol), and the colour
    # itself beside it. **Before the subtype row below** for the multicolored
    # row's reason and a worse one: `[a-z][a-z-]+` took "nonred" for a creature
    # type, so the Patrol compiled a trigger narrowed to a subtype called
    # "nonred" that no spell has -- and only the grammar refusing the same
    # words kept it from shipping silent. The negation is its own key rather
    # than a "non" prefix on `color_word`: that key is looked up in the colour
    # table, where "nonred" names nothing and admits every spell.
    ("you_cast_spell",
     r"whenever you cast a non(?P<cast_excluded_color>white|blue|black|red|green) spell"),
    ("you_cast_spell",
     r"whenever you cast a (?P<color_word>white|blue|black|red|green) spell"),
    ("you_cast_spell",              r"whenever you cast a (?P<cast_subtype>[a-z][a-z-]+) spell"),
    ("you_cast_spell",              r"whenever you cast a spell"),
    # "When **you play a card**, sacrifice this artifact." (Juju Bubble.)
    # CR 701.18b: to play a card is to play it as a land **or** cast it as a
    # spell, so this is not the cast event with a wider name -- it is one
    # condition with two fire sites, and a version that only watched casts
    # would leave the artifact sitting through a land drop. Both halves are
    # announced in ``engine/mixins`` (the cast announcement and the land
    # branch of ``_resolve_card``); ``engine/cast_event_filters.py`` scopes it to the
    # permanent's own controller, which is what the printed "you" says.
    ("you_play_card",               r"whenever you play a card"),
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
    # "Whenever **a nontoken creature leaves the battlefield**, exile all tokens
    # with the same name as that creature." (Dual Nature.) CR 603.6c's event
    # watched across the whole board — the subject-led twin of the entry row
    # above, with the noun phrase delimited here and read by the noun parser.
    # Announced from the one transition off the battlefield
    # (`remove_all_from_battlefield`), where the subject is still on a
    # battlefield to be asked about (CR 603.10a looks back in time). The kind is
    # its own rather than a spelling of `leaves_battlefield`, which is the
    # *source's* departure and is dispatched off the source's own card.
    ("matching_permanent_leaves_battlefield",
     r"whenever (?P<leaver_subject>(?:a|an|another) [^,]+?) leaves the battlefield"),
    # "Whenever **a permanent is returned to a player's hand**, that player
    # discards a card." (Warped Devotion.) A zone change with *both* ends named:
    # the battlefield (a "permanent" is nothing else, CR 110.1) and a hand. So
    # it is not the row above, which is every departure, and it is not a card
    # reaching a hand from anywhere — a draw and a Raise Dead put a card in a
    # hand and return no permanent.
    #
    # Announced from ``Game.put_card_into_hand``, the one seam that is handed
    # both halves: the hand it is going to and, as ``from_battlefield``, the
    # permanent it is the card of. CR 603.10a makes it look back in time ("an
    # object that all players can see is put into a hand"), which is why the
    # announcement is made there, before the permanent is taken off the
    # battlefield — an enchantment returned by the same effect still sees
    # itself go.
    #
    # The noun phrase is delimited and read by the noun parser, exactly as the
    # row above delimits its own, so "a creature is returned to a player's
    # hand" is the same row with a narrower filter. "A player's" is the only
    # hand spelling read: whose hand is the *event's* (CR 400.3 — always the
    # owner's), and a card narrowing it ("to your hand") is a different trigger
    # this row refuses rather than widens.
    ("permanent_returned_to_hand",
     r"whenever (?P<returned_subject>(?:a|an|another) [^,]+?) is returned to "
     r"a player's hand"),
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
    # "Whenever you win a coin flip …" (Chance Encounter). Announced from the
    # one seam a player-won flip goes through (``handlers/_common.
    # flip_coin_for``), carrying the flipper's seat — CR 705.2: "only the
    # player who flips the coin wins or loses the flip". A flip nobody can win
    # (Mana Clash's heads-or-tails) does not go through that seam and is not
    # announced.
    ("you_win_coin_flip",           r"whenever you win a coin flip"),
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
    # "Whenever **an opponent plays a land**, put a +1/+1 counter on this
    # creature." (Dirtcowl Wurm.) CR 305.1: playing a land is a special action
    # that uses no stack, so it is neither a cast nor — necessarily — a land
    # *entering*: `land_enters` beside this one is announced for a land that
    # arrives by any route, and a land put onto the battlefield by an effect was
    # never played. Two events, and a card printing one must not fire on the
    # other.
    #
    # The seat is the trigger's own narrowing rather than a second kind, which
    # is `draws_card` below read one event over: one announcement, made where
    # the land is played, and the printed word decides whose play it watches.
    # "Whenever **a player** plays a land, that player draws a card." (Horn of
    # Greed.) The third value of the same seat axis and not a third condition:
    # unnarrowed, so every seat's land drop fires it for every watcher. Written
    # as the *absence* of the group, which is what `draws_card` below means by
    # a missing ``drawer`` — an absent optional group is not in the groupdict,
    # so "a player" and "you" would be one payload. They are not one condition,
    # so the word is captured and the filter compares it.
    # "When you play **another** land, sacrifice this land." (City of
    # Traitors.) A second narrowing on the same announcement rather than a
    # second kind, exactly as the seat above is: an *optional* group, so a card
    # printing the bare phrase carries the payload it always carried and only
    # the printing that says the word gets the key. What the word excludes is
    # the source itself, which the filter answers by comparing the played
    # permanent's id against the observer's — a `CardDefinition` identity
    # cannot, because a deck repeats one immutable definition per copy and a
    # second City of Traitors would be read as the first.
    # "When an opponent plays a **nonbasic** land" (Hidden Herd). A third
    # narrowing on the same announcement, and an *optional* group for
    # ``other_land``'s stated reason: a card printing the bare phrase carries
    # the payload it always carried, because a group that did not participate
    # never reaches the dict. CR 205.4a's supertype is what answers it, read
    # off the land that was played.
    ("land_played",
     r"whenever (?:you play|(?P<land_player>an opponent|a player) plays) "
     r"(?:a|(?P<other_land>another)) (?:(?P<played_land_supertype>nonbasic|basic) )?land"),
    # "**When the chosen player** draws a card **with the chosen name**, …"
    # (Booby Trap.) Two narrowings on the same announcement rather than a second
    # kind, which is the same reading `land_played` above records: one event,
    # and the printed words decide whose draw it watches and which card. Both
    # are answered against the *source permanent's* entry record, which is why
    # they are words here and a metadata read in `engine/event_filters.py` — nothing
    # about the payload could carry a choice made when the artifact entered.
    # "Whenever **a player** draws a card, that player loses 2 life unless they
    # pay {2}." (Phyrexian Tyranny.) The third value of the seat axis and not a
    # third condition — `land_played` above reads the same three words for the
    # same reason, and the captured word is what `event_filters._draws_card_filter`
    # compares: unnarrowed, so every seat's draw fires it for every watcher,
    # the enchantment's own controller included. Captured rather than left as
    # the absence of the group, because an absent group already means "you".
    ("draws_card",
     r"whenever (?:you draw|(?P<drawer>an opponent|a player) draws) a card"),
    # "…your second card each turn" (Mystic Skyfish, Jolrael). Fires once per
    # turn, announced by the draw sweep in check_state_based_actions off the
    # cards_drawn_this_turn record every draw path already feeds.
    ("draws_second_card",           r"whenever you draw your second card each turn"),
    # "Whenever you reveal **a basic land card** this way, draw a card."
    # (Rowen.) "This way" is the reveal the card's own first sentence asks for —
    # "reveal the first card you draw each turn" — which is why the condition
    # names the *draw* reveal and not reveals in general: a search that reveals
    # its finds is a different event, and firing on one would be a card nobody
    # printed. The noun phrase is payload (`engine/draw_reveals.py` holds the
    # static half), so a card printing "a creature card" needs no code.
    # The noun "card" is consumed literally rather than captured: a reveal is
    # always of a card (CR 701.20a), and `subject_filter_payload` reads a
    # *permanent's* noun phrase and refuses the word — so leaving it inside the
    # group refused the whole condition and left the trigger unclassified.
    ("revealed_drawn_card",
     r"whenever you reveal (?P<revealed_subject>an? [^,]+) card this way"),
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
    # "**Whenever a creature has four or more fuse counters on it**, remove all
    # fuse counters from it and destroy it. That creature deals 4 damage to its
    # controller." (Bomb Squad.) The same CR 603.8 state, asked of **another
    # permanent** — any one the noun phrase describes, on any battlefield — so
    # it is its own kind and not a subject on the row above: that row's state
    # is one fact about its source, and this one is a fact per watched
    # permanent, which is what its sweep latches on (two creatures crossing the
    # line are two triggers, and one of them leaving re-arms neither).
    #
    # The noun phrase is delimited as a ``_subject`` group and read by the noun
    # parser, so "an artifact" or "a creature you control" is payload; the
    # number and the counter kind are payload as they are one row up, with the
    # wider character class ``source_has_no_counters`` uses because a P/T
    # counter is spelled with symbols (CR 122.1a).
    #
    # No row above can claim the sentence: "there are" and "this creature's
    # power" do not open with an article, and the two "this <noun> has" rows
    # below name the source.
    ("permanent_counters_reach_threshold",
     r"whenever (?P<countered_subject>an? [^,]+?) has (?P<counter_count>[a-z0-9]+) or more "
     r"(?P<counter_kind>[-+/0-9a-z]+) counters on it"),
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
    # "**When you have 10 or less life**, if this permanent is an
    # enchantment, it becomes a 3/5 Soldier creature." (Opal Avenger.)
    # "**When an opponent has 10 or less life**, …" (Lurking Jackals.)
    # CR 603.8 asked of a **life total** — the fourth thing this family
    # reads a state off, beside a counter store, a characteristic and a
    # hand. Its own kind rather than a seat on `player_has_no_cards_in_hand`
    # below, for that row's own reason: what is counted is not the same
    # thing, and the sweep that answers it reads `player.life` rather than
    # `player.hand`.
    #
    # **The seat is payload**, the `controls_seat` idiom one row down, and
    # the kind is named for the state rather than for one of the two seats
    # that can be in it. It was `controller_life_at_most` with "you" baked
    # into the pattern and the comment here recording that as deliberate —
    # true while Opal Avenger was the only printing, and a *narrowing* the
    # moment a second one arrived: a card whose card reads "an opponent"
    # matched no row at all and refused with its effect already implemented.
    # Which seat is asked is the printed word, exactly as it is for
    # `controls_matching_permanent`, and the sweep reads it: Opal Avenger
    # wakes when its own controller is low and Lurking Jackals when anyone
    # across the table is, and the group is present in the groupdict exactly
    # when the second spelling matched.
    #
    # The threshold is delimited and read by `_NUMBER_WORDS`, so a card
    # printing another number is payload rather than a second row — and the
    # character class admits a digit because 10 is the only spelling this
    # card uses, exactly as `source_power_at_least`'s does for 7.
    #
    # In the whenever table under the "when" the card prints, like every
    # state trigger above it: a kind lives in one table, and this is the one
    # both printed words reach.
    ("life_at_most",
     r"whenever (?:you have|(?P<life_seat>an opponent) has) "
     r"(?P<life_count>[a-z0-9]+) or less life"),
    # "When **you have 20 or more life**, you lose the game." (Transcendence.)
    # The row above crossed from below: the same seat and threshold groups, so
    # the same payload, and its own kind because the comparison is the
    # question the sweep asks (the arrangement `source_power_at_least` has).
    ("life_at_least",
     r"whenever (?:you have|(?P<life_seat>an opponent) has) "
     r"(?P<life_count>[a-z0-9]+) or more life"),
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
    # "Whenever **a creature with shadow** dies, …" (Dauthi Ghoul.) CR 700.4:
    # "dies" *means* "is put into a graveyard from the battlefield", so this is
    # the `permanent_dies` rows above spelled the short way — same kind, same
    # `dying_subject` group, same board-wide fire site
    # (`_fire_permanent_dies_triggers`), which already tests the phrase through
    # `subject_matches`. Nothing else was missing: a *narrowed* death had no
    # reader at all on either front end, so "a creature with flying dies" refused
    # exactly as "a creature with shadow dies" did — the keyword was never the
    # gap.
    #
    # **Last in the table**, and that is the whole of its safety. `[^,]+` reads
    # any noun phrase, so every specific death row above — "a creature you
    # control dies", "a creature an opponent controls dies", "a creature dealt
    # damage by this creature this turn dies" — has to be offered its line
    # first; and `_match_trigger_patterns` *aborts* on a phrase the noun parser
    # refuses rather than falling through, so a row placed above them would take
    # their cards down with it rather than merely shadowing them.
    ("permanent_dies",
     r"whenever (?P<dying_subject>an? [^,]+) dies"),
)
