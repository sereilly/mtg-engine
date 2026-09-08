"""What a printed noun phrase **describes**: the set of objects it names.

Split out of ``_core`` when that module crossed the 1,000-line guard. The cut
is the one ``_core``'s own docstring already drew — quantities, then "object and
player references (``grammar/nouns.py``)", then the durations and costs that
hang off an effect — and it is the same boundary Antiquities used when
``nouns.py`` split into ``references.py``: what a noun phrase *describes*
against what it points at.

:class:`ObjectFilter` is most of those lines on its own, which is why this half
was the one to move. ``_core`` re-exports everything defined here, so no
importer outside this package changes: ``from ._core import ObjectFilter``
still resolves, and the AST package's flat ``__init__`` is untouched.

**And it crossed the guard again**, at Tempest's third wave, when the filter
gained the three keys Escaped Shapeshifter's condition needs. The cut that time
was the other half of this file's own title: :class:`TargetSpec` — what a
sentence *points at* — left for ``_targets`` beside this one, leaving only what
a noun phrase describes. The two halves grow with different rules, which is what
makes the boundary worth having: this one with the vocabulary of printed noun
phrases, that one with CR 601.2's announcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ._payloads import object_filter_payload

if TYPE_CHECKING:  # `ObjectFilter.zone_owner`'s annotation only — ``_seats``
    from ._seats import PlayerRef  # imports this module at run time, not the reverse.


@dataclass(frozen=True)
class Comparison:
    """A numeric restriction: "with power 2 or less"."""
    op: str    # "eq" | "le" | "ge" | "lt" | "gt"
    value: Amount


@dataclass(frozen=True)
class SourceRelativeComparison:
    """"…with power **equal to or greater than the enchanted creature's
    toughness**" (Ironclaw Curse).

    :class:`Comparison`'s bound is a number the line prints; this one's is a
    characteristic of the ability's **own source**, read when the question is
    asked. Its own node rather than a ``Comparison`` whose ``value`` is a
    reference, because the two are answered in different places: a printed bound
    rides the payload into ``permanent_matches_filter``, the pure matcher, and
    this one cannot — nothing there holds the source. Written as a
    ``Comparison`` it would reach that matcher, find no number, and compare
    against zero, which for "power 0 or greater" is every creature there is.

    All three words travel as data for the reason every other printed word in
    this grammar does: "toughness equal to or less than the enchanted
    creature's power" is the same sentence and must need no second node.
    """
    characteristic: str          # of the candidate: "power" | "toughness"
    op: str                      # "le" | "ge"
    source_characteristic: str   # of the ability's source


@dataclass(frozen=True)
class ObjectFilter:
    """A noun phrase describing a set of objects.

    ``to_payload`` emits the exact key set the deleted
    ``engine.parsing.common.TargetFilter`` produced, so instructions lowered
    from the grammar stayed byte-compatible with the 121 existing effect
    handlers across the migration; the newer restriction keys are additive and
    read with ``payload.get`` defaults on the handler side.
    """

    card_types: tuple[str, ...] = ()          # "creature", "artifact", ...
    # How multiple card types combine. "artifact or enchantment" is a union
    # ("any"); "artifact creature" is a single permanent that is both ("all").
    # Collapsing the two would make "destroy target artifact creature" hit every
    # artifact and every creature.
    type_match: str = "any"
    supertypes: tuple[str, ...] = ()          # "legendary", "basic", ...
    subtypes: tuple[str, ...] = ()            # "wall", "djinn", ... (from data)
    # How multiple subtypes combine, exactly as `type_match` does for card
    # types. "Djinn or Efreet" is a union ("any"); "Urza's Power-Plant" is a
    # single permanent carrying both land types ("all", CR 205.3i). Collapsing
    # them would let one Urza's Mine satisfy "an Urza's Mine and an Urza's
    # Tower" on its own.
    subtype_match: str = "any"
    # "target **instant or Aura** spell" (Avoid Fate, Ring of Immortals). A
    # union whose alternatives do not all live on one axis: "instant" is a card
    # type (CR 205.2) and "Aura" a subtype (CR 205.3), and every matcher in this
    # engine ANDs `card_types` against `subtypes` — so recording the phrase in
    # those two fields would describe an instant that is also an Aura, a set no
    # card can ever be in. Its own field for the reason `any_states` is one: a
    # union spelled into the fields it happens to straddle is a union the next
    # printed pair cannot use.
    #
    # Each alternative carries the axis it was read on ("card_type" / "subtype")
    # rather than the bare word, because the two vocabularies are not disjoint
    # in principle and a matcher guessing which one it was handed is a matcher
    # that can guess wrong.
    any_classes: tuple[tuple[str, str], ...] = ()
    colors: tuple[str, ...] = ()              # mana symbols: "W", "U", ...
    excluded_colors: tuple[str, ...] = ()     # "nonblack"
    excluded_types: tuple[str, ...] = ()      # "nonartifact"
    excluded_subtypes: tuple[str, ...] = ()
    #: "**nonsnow** land" (Hallowed Ground). A negated supertype (CR 205.4). No
    #: layer computes a supertype, so the matcher reads it off the effective
    #: type line — the negative of the ``supertypes`` key above and answered by
    #: the same reader.
    excluded_supertypes: tuple[str, ...] = ()   # "non-Wall"
    with_keywords: tuple[str, ...] = ()       # "with flying"
    without_keywords: tuple[str, ...] = ()    # "without flying"
    controller: str | None = None             # "you" | "opponent" | "that_player"
    # "target permanent you both **own** and control" (Obelisk of Undoing).
    # Ownership (CR 108.3) is a different question from control (CR 613 layer
    # 2) and the two come apart the moment anything is stolen — which is
    # precisely the case this card is printed to exclude. Its own field, so a
    # phrase naming only one of them cannot be read as naming both.
    owner: str | None = None                  # "you"
    # "Exile target permanent you **own or control**." (Telim'Tor's Edict.) The
    # *disjunction* of the two fields above, which neither of them and no pair
    # of them states: setting both would be Obelisk of Undoing's "own **and**
    # control", the exact set this card is printed to be larger than. Its own
    # field for that reason, and only "you" — no card in the pool prints the
    # union about anybody else.
    owner_or_controller: str | None = None     # "you"
    tapped: bool | None = None
    attacking: bool | None = None
    blocking: bool | None = None
    blocked: bool | None = None
    # "target **attacking or blocking** creature" (the Legends pinger cycle).
    # Its own field rather than both booleans set at once: every matcher ANDs
    # the payload keys, so `attacking=True, blocking=True` would describe a
    # creature that is somehow doing both — a set that is always empty.
    #: A union of printed state adjectives — "attacking or blocking",
    #: "tapped or blocking". The words as printed, because what each one
    #: *means* is one answer the matcher owns; a pair spelled into a
    #: boolean here made every other pair a non-match.
    any_states: tuple[str, ...] = ()
    power: Comparison | None = None
    toughness: Comparison | None = None
    mana_value: Comparison | None = None
    #: "…each artifact **with mana value less than or equal to the number of
    #: rust counters on it**" (Corrosion). A comparison between two
    #: characteristics of the *same* object, which no ``Comparison`` can carry:
    #: its bound is an :class:`Amount`, and an amount is read off the effect's
    #: own context rather than off whichever permanent the matcher is testing.
    #:
    #: The counter's name is payload, so a card printing "vitality counters"
    #: needs no code. The **operator** is in the field's name rather than beside
    #: the kind, deliberately: this is the only direction any card prints, and a
    #: general `op` here would be a comparison the matcher has to be trusted to
    #: implement in five ways nothing exercises.
    mana_value_at_most_counters: str | None = None
    #: "…each creature **with mana value equal to the number of age counters on
    #: this enchantment**" (Wave of Terror). The field above read off the
    #: ability's *source* instead of off the object being tested — a different
    #: question, so a different key, and the operator is again in the name for
    #: that field's reason. "On it" is refused by the parse and belongs to the
    #: field above: the pronoun names the candidate.
    mana_value_equals_source_counters: str | None = None
    #: "…target creature **with power less than or equal to the number of
    #: treasure counters on this enchantment**" (Legacy's Allure). The bound
    #: above one characteristic over: a count on the ability's *source*
    #: compared against the candidate's power. Its own key rather than a
    #: characteristic on the mana-value one, because which stat is compared is
    #: what the matcher has to read and CR 613 computes power through the
    #: layers where CR 202.3 reads mana value off the card. The operator is in
    #: the name for the two fields above's reason: this is the only direction
    #: printed, and a general `op` would be five comparisons nothing exercises.
    power_at_most_source_counters: str | None = None
    #: "creatures with power **greater than the number of cards in your
    #: hand**" (Ensnaring Bridge). A bound off a *hidden zone* rather than off
    #: a board — so it is neither a printed number nor a count the pure matcher
    #: can reach, and it lands on its own key like the two above it. The value
    #: is whose hand ("you"), because that is the only part the sentence
    #: parameterizes; the operator is in the name for the field above's reason.
    power_greater_than_cards_in_hand: str | None = None
    named: str | None = None
    #: "…a creature with flying **not named Escaped Shapeshifter**" — the
    #: negative of ``named``, when the excluded name is spelled out. A name
    #: rather than an identity, so a second copy of the card is excluded too
    #: (CR 201.2), which is what ``exclude_self`` cannot say.
    not_named: str | None = None
    #: The same exclusion when the name printed is the **card's own** — the
    #: only spelling any card in the pool prints. Its own field because neither
    #: front end holds a name at that point: the lexer has collapsed the words
    #: to a SELF token for the grammar, and ``oracle._restriction_line`` has
    #: rewritten them to "this creature" for the derivation tables. What the
    #: matcher compares is still the *name*, read off the ability's source.
    not_named_source: bool = False
    #: "…a creature **with protection from white**" (Escaped Shapeshifter). The
    #: word is a protection *quality* (``engine/keywords.protection_quality``),
    #: not a keyword: "protection" alone is a keyword the matcher can answer and
    #: means something strictly wider, so the quality has to ride the key.
    #: Asked of the game (``_protection_qualities``) rather than of the object,
    #: because an Aura, a lord and a metadata grant all contribute one.
    with_protection_from: str | None = None
    #: "…**with a name originally printed in the Homelands expansion**"
    #: (Apocalypse Chime, Golgothian Sylex). The set *code* the printed
    #: expansion name resolved to, read off ``original_printing`` --
    #: ``printings[0]``, the first set the card appeared in, which is the
    #: whole content of the word "originally": nineteen Antiquities cards were
    #: reprinted in Revised and the set a copy happened to be loaded from would
    #: miss every one of them. Asked of the permanent's ``effective_card``,
    #: because CR 206.3 states each of these cards as a list of **names**.
    #:
    #: A restriction on the *card*, like ``named`` above it, rather than on
    #: anything a board can answer -- so it is testable by the pure matcher and
    #: composes with any verb. It used to be spelled into one production's
    #: instruction kind, which bought exactly the one card that production read.
    original_expansion: str | None = None
    zone: str = "battlefield"
    # "target **activated or triggered ability**" (Sublime Epiphany). An ability
    # on the stack is an object (CR 113.7a/608.2) but not a spell, so it is not
    # ``zone == "stack"`` with a type line — it has no card at all. The printed
    # kinds are carried rather than collapsed to "an ability", because "counter
    # target activated ability" and "counter target triggered ability" are
    # different cards and the difference is exactly this tuple.
    ability_kinds: tuple[str, ...] = ()
    # "…activated ability **from an artifact source**" (Rust, Ayesha Tanaka).
    # A narrowing on the *permanent the ability came from*, which is the only
    # thing about an ability on the stack there is to narrow by — it has no card
    # and no type line of its own (CR 113.7a). Beside `ability_kinds` because it
    # is the same object's other adjective, and a tuple because "an artifact or
    # enchantment source" is the same sentence with one more word.
    ability_source_types: tuple[str, ...] = ()
    # Whose zone, when *zone* names one ("from **your** graveyard"). "Return
    # target creature card from your graveyard" and "…from a graveyard" are
    # different cards, and the handlers only ever look in the caster's own
    # graveyard — so the owner is recorded and checked rather than assumed.
    zone_owner: PlayerRef | None = None
    # The head noun was "card" ("target creature **card** from your graveyard").
    # CR 400.1: an object outside the battlefield is a card, not a permanent.
    # Without this the word is droppable, and "target creature card from your
    # graveyard" would lower identically to the untemplatable "target creature
    # from your graveyard" — the dropped-rider bug class.
    is_card: bool = False
    # "with a +1/+1 counter on it" (Tempered Veteran) — the object carries at
    # least one +1/+1 counter, read off the ``plus_counters`` record the
    # placing handlers keep (CR 122).
    with_plus1_counter: bool = False
    # "target creature **with a bounty counter on it**" (Bounty Hunter), "all
    # creatures **with magnet counters on them**" (Magnetic Web). A counter
    # kind out of ``engine/named_counters.py``'s open key space (CR 122.1: a
    # counter's kind is whatever word the card invents, and nothing in the
    # rules reacts to it).
    #
    # A **separate field from ``with_plus1_counter`` above**, not a widening of
    # it. CR 122.1a's +1/+1 counter has rules meaning — it is layer 7d and it
    # lives in ``engine/pt.py``'s channel, under the ``plus_counters`` key —
    # while every other kind is an inert marker in a different store. One field
    # carrying both would be one question with two places to look for the
    # answer, which is the exact failure ``named_counters.py``'s own docstring
    # records: a card put counters where nothing read them.
    with_named_counter: str | None = None
    # "nontoken" (Lich's sacrifice). CR 111.1: a token is not a card, so this is
    # neither an excluded card type nor an excluded subtype.
    nontoken: bool = False
    # "permanents **of the chosen color**" (Psychic Allergy). Not a member of
    # ``colors``: the colour was decided as the *source* entered (CR 614.1c)
    # and is stored on that permanent, so folding it in would need a sentinel
    # colour word every ``color_filter`` reader would then compare against.
    chosen_color: bool = False
    #: "target creature **with the chosen ability**" (Phyrexian Splicer). The
    #: keyword the ability's *activation* chose (CR 601.2b, through CR 602.2b),
    #: recorded on the ability's own source — so it is answered the way
    #: ``chosen_color`` is, by a reader holding that permanent, and refused by
    #: the pure matcher which holds none.
    #:
    #: A separate key from ``with_keywords`` and not a value of it, because the
    #: word is not in the sentence: a filter carrying a keyword list would have
    #: to carry a word, and there is none until the ability is announced.
    chosen_keyword: bool = False
    # "Creatures **of the chosen type**" (An-Zerrin Ruins). The creature type
    # its source recorded as it entered (CR 614.1c) — the sibling of
    # ``chosen_color`` above, one characteristic over, and its own field for
    # that field's reason: which quality was chosen decides what the phrase
    # narrows by, and one field meaning either would leave the matcher
    # guessing. Emitted, and answered only by a reader holding the source.
    chosen_creature_type: bool = False
    #: "Destroy all creatures **of the creature type of your choice**."
    #: (Extinction.) The word above is a choice the *source* made as it entered
    #: (CR 614.1c) and is read off its metadata; this one is made while the
    #: spell resolves (CR 608.2d) by whoever controls it, so there is no
    #: permanent to read and no permanent to record on. The lowering turns it
    #: into a choosing step plus a ``subtype_filter_from`` key naming the
    #: scratchpad slot that step writes.
    creature_type_of_your_choice: bool = False
    # "Each **land** of the chosen type" (Shimmer). The same CR 614.1c choice
    # a third characteristic over, and its own field for ``chosen_color``'s
    # reason rather than a value of the one above: the *catalog* the word came
    # from is what the choice recorded, and a land type stored under a creature
    # type's name is a lie the next reader trips on. Which key the noun phrase
    # produces is decided by its head noun — "land of the chosen type" is this
    # one, everything else is the creature type — because the sentence spells
    # the catalog exactly once, in the head.
    chosen_land_type: bool = False
    # "creatures **that didn't attack this turn**" / "…**that couldn't
    # attack**" (Season of the Witch): two questions about one combat, both
    # answered off the permanent's own per-turn record.
    attacked_this_turn: bool | None = None
    could_attack_this_turn: bool | None = None
    #: "target creature **you cast this turn**" (Cycle of Life). Not a state of
    #: the permanent and not a zone it came from: CR 701.5a's *cast*, which a
    #: reanimation and a token both fail while entering the same turn.
    #:
    #: Relative to the game and to the asker, like ``controlled_since_turn_start``
    #: below it: the record is a seat and a turn number, so the pure matcher has
    #: nothing to compare either against and refuses.
    cast_by_you_this_turn: bool = False
    # "…**except for creatures the player hasn't controlled continuously since
    # the beginning of the turn**" (Total War). CR 302.6's condition, printed as
    # an exception and therefore *narrowing to* the creatures that have been
    # controlled that long — the exception is what the field says, so nothing
    # downstream has to invert it.
    #
    # Relative to the game rather than to the object: the answer is a
    # comparison against the current turn, which the pure matcher has no way to
    # make. So it is answered in ``subject_matches`` beside the layer-6
    # questions, and refused by ``permanent_matches_filter``.
    controlled_since_turn_start: bool | None = None
    # "exile any number of **tokens** created with this creature" (Tetravus) —
    # the positive of ``nontoken``. Its own field rather than a tri-state,
    # because every lowering written before it exists refuses an unknown field
    # by default and would silently ignore a third value of an old one.
    token_only: bool = False
    # "…**created with this creature**" (Tetravus). Which permanent made the
    # token, and therefore *relative*: no read of the token alone can answer it,
    # exactly like ``other_than_source`` and ``attached_to``. The handler that
    # has the ability's source tests it; ``permanent_matches_filter`` is
    # deliberately not told about it.
    created_with_source: bool = False
    #: "…**put onto the battlefield with this enchantment**" (Diabolic
    #: Servitude, and the enchant clause Necromancy prints as a quoted line).
    #: The permanent this one's own ability reanimated, read off the record
    #: ``handlers/zones.reanimate_creature`` stamps.
    #:
    #: Beside ``created_with_source`` and for its reason exactly: a fact about
    #: the object's *history*, which nothing about its characteristics can
    #: answer — the reanimation's target was a card in a graveyard, and CR 400.7
    #: makes what arrived a new object with no history on the board.
    put_onto_battlefield_by_source: bool = False
    # "a creature **of their choice**" (Run Afoul) — the player performing the
    # action picks. Recorded rather than dropped, because "of *your* choice" is a
    # different sentence; a lowering accepts it only where the rule it lowers to
    # already puts the choice there (CR 701.21a for a sacrifice).
    their_choice: bool = False
    # "other than this creature" / "other Zombies" — excludes the source.
    other_than_source: bool = False
    # "this creature" / "this artifact" — the ability's own source.
    is_source: bool = False
    # "**that token**" — the token an earlier sentence of this same effect
    # created (Stangg). A referent, like ``is_source`` beside it, and not a
    # restriction: no read of a permanent alone can say whether *this*
    # resolution made it, so the id is written to the resolution scratchpad by
    # the token maker and read back by whatever sentence names it. The lowering
    # refuses the phrase when no token maker precedes it, exactly as "its
    # controller creates" refuses with no exile in front of it.
    is_created_token: bool = False
    # "enchanted creature" — the permanent this Aura is attached to.
    is_enchanted: bool = False
    # "target permanent **that isn't enchanted**" (Time Elemental) — a permanent
    # with no Aura attached to it (CR 303.4a defines "enchanted" as exactly
    # that). Not the negation of ``is_enchanted`` above, which is a different
    # question entirely: that field is a *referent* ("the permanent this Aura is
    # on"), this one is a restriction on any candidate. Two fields because two
    # phrases, and collapsing them into a tri-state would make "enchanted
    # creature" and "a creature that is enchanted" the same words to every
    # reader downstream.
    not_enchanted: bool = False
    # "destroy **target enchanted** creature" (Ramses Overdark) — a creature
    # with an Aura attached, chosen from the whole board. The third of the
    # three, and the one the printed word "target" separates from
    # ``is_enchanted`` above: on an Aura, "enchanted creature" *names* the
    # permanent that Aura is on, while a card that asks its controller to pick
    # one is describing every creature that is enchanted. `references.py`
    # rewrites the referent into this restriction at the one place the
    # quantifier is known, because the noun parser reading "enchanted creature"
    # has not seen the word in front of it yet.
    enchanted_only: bool = False
    # "all Equipment **attached to that creature**" (Turn to Slag). Which object
    # it is attached to, as a referent rather than a filter: "that creature" is
    # the spell's own target, and no read of the Equipment alone can say so.
    # ``permanent_matches_filter`` is therefore not told about it — the handler
    # that has the context resolves it, the split the ``controls`` condition
    # already makes for "another".
    attached_to: str | None = None
    # "attached to a creature or land" (Enchantment Alteration) / "Auras you own
    # **attached to permanents you control**" (Remove Enchantments) — the host
    # as a noun phrase of its own, which a read of the attachment *can* answer
    # by asking the same question of the host that is being asked of this
    # object. A nested filter rather than the tuple of card types this was:
    # "permanents you control" is a host phrase with a seat in it, and a tuple
    # of types had nowhere to put the seat, so a card printing one would have
    # had it dropped — an Aura-sweep reaching every Aura on the board.
    #
    # The nesting is what keeps that from being a new rule: the host is tested
    # through the very matcher testing the attachment, so whatever a noun phrase
    # can say about a permanent it can say about a host, once.
    attached_to_filter: "ObjectFilter | None" = None
    #: "…a card **with the same name as target nontoken creature**" (Mask of
    #: the Mimic). CR 201.2 compared against an object the *same sentence*
    #: chooses, which is why the field holds that object's own description
    #: rather than a name: the name is not knowable until the spell is cast.
    #:
    #: Its own field beside ``named`` rather than a value in it, for
    #: ``pay_life_x``'s reason one module over: every reader of ``named`` is a
    #: string comparison, and a sentinel in it would be compared as a card
    #: name — a search that finds a card literally called "target nontoken
    #: creature", which is no card at all and therefore a tutor that finds
    #: nothing while the spell reports supported.
    named_as_target: "ObjectFilter | None" = None
    # "Return all Auras attached to **target permanent you own** to their
    # owners' hands." (Scarab of the Unseen.) The host again, and neither of the
    # two fields above can say it: ``attached_to`` names a referent some earlier
    # clause already chose, and ``attached_to_filter`` is a description the
    # matcher *tests* the host against. This one is a description the spell
    # **chooses** — CR 601.2c picks it as the spell is cast — so it is the only
    # one of the three that a picker has to be told about, and it is carried as
    # the phrase rather than as a flag because that phrase is exactly what the
    # picker offers.
    #
    # Kept out of ``to_payload`` for ``attached_to``'s reason: no read of the
    # attachment alone can answer "is your host the one that was targeted?",
    # so the handler resolves the id and the lowering emits the target
    # description beside the filter.
    attached_to_target: "ObjectFilter | None" = None
    # "target creature **whose controller controls an Island**" (Seasinger).
    # A narrowing that is not about the object at all: it is about what the
    # seat holding it has elsewhere on the battlefield. A nested filter for
    # ``attached_to_filter``'s reason — whatever a noun phrase can say about a
    # permanent it can say about the one this seat has to own — and a separate
    # field because the two describe different relations: one walks an
    # attachment, the other a seat's whole board.
    controller_controls: "ObjectFilter | None" = None
    # "another permanent **of that type**" — shares a card type with what the
    # sentence's other clause named. Only a lowering knowing that object can
    # resolve it; one that does not must refuse.
    of_bound_type: bool = False
    # "that's one or more colors" (Ugin, the Spirit Dragon's −X): the object
    # has at least one color, read off its effective colors.
    colored: bool = False
    # "…that isn't the target of an ability from another creature named ~"
    # (Goblin Artisans). A restriction on the object's *situation* rather than
    # on the object: it asks what else on the stack is pointing at it. The
    # source class is not carried because the printed clause names the ability's
    # source by the asking card's own name, which the lexer has already
    # collapsed to a SELF token — so the question is "another copy of me",
    # whatever the copy is called.
    not_ability_targeted_by_same_name: bool = False
    # "…**with the same name as another permanent**" (Eye of Singularity).
    # CR 201.2's comparison, over the board rather than against a printed
    # literal — which is what makes it a different field from ``named``: that
    # one holds a word the card printed, this one holds a relation nothing
    # knows until the sweep runs. Answered by ``subject_matches``, which has
    # the game the relation needs.
    shares_name_with_another: bool = False
    # "…**with that name**" (Eye of Singularity's second line). The same
    # comparison against the object the *firing event* was about, which no
    # matcher can answer: ``subject_matches`` is handed a permanent, a seat and
    # a source, and never the trigger's context. So the key travels to the
    # handler, which resolves the name and then matches on it — the same split
    # ``attached_to`` and the blocked-pair relations already make.
    name_from_event: bool = False
    # "…**other than a basic land**" / "…**except for basic lands**" (Eye of
    # Singularity prints both, one on each line). One field for two spellings,
    # because they name the same set: a permanent that is a land with the Basic
    # supertype (CR 205.4a). Not ``excluded_supertypes`` — that excludes a
    # supertype on any card type, and the printed exemption is about the pair.
    excluded_basic_lands: bool = False
    # "…**that targets a permanent you control**" (Avoid Fate, Ring of
    # Immortals). A restriction on what the *spell* chose, not on what the spell
    # is — so it is a nested noun phrase rather than more adjectives, and it is
    # relative twice over: it needs the stack object's recorded targets and the
    # seat "you control" is measured against. Never emitted by ``to_payload``
    # and never reaches ``permanent_matches_filter``; the one lowering written
    # for it carries the inner phrase as its own payload key and the handler
    # that has the stack item asks ``subject_matches`` of each target.
    targets_object: "ObjectFilter | None" = None
    # "…**with a single target**" (Reflecting Mirror; Deflection and Divert
    # print the same words). CR 115.9a: how many times any object or player was
    # chosen as the target of that spell when it was put on the stack — a
    # question only a *spell or ability on the stack* can be asked, and one
    # that no read of a permanent can answer. So, like ``targets_object`` above
    # it, ``to_payload`` never emits it and ``permanent_matches_filter`` is
    # never told about it: the one lowering written for it carries the count as
    # its own payload key, and every other lowering refuses the phrase by name.
    #
    # A count rather than a "single" flag, because CR 115.9a's template is
    # "[spell or ability] with [a number of] targets" — the number is the
    # parameter, exactly as a colour or a card type is elsewhere here.
    target_count: int | None = None
    # "blocking or blocked by this creature" (Sentinel) — the object is in
    # combat with the ability's own source (CR 509). Relative, like
    # ``other_than_source``: no read of the object alone can answer it, so
    # ``to_payload`` never emits it and ``permanent_matches_filter`` is never
    # told about it — the one lowering that accepts it carries the relation as
    # its own payload key and the handler that has the source tests it.
    in_combat_with_source: bool = False
    # "creatures that dealt damage to it this turn" (Brine Hag) — a *history*
    # relative to the source, read off the damage record the victim carries
    # (``damaged_by_sources_this_turn``). Same discipline as the field above:
    # never emitted, so every lowering not written for it refuses the phrase
    # instead of quietly widening to every creature.
    dealt_damage_to_source_this_turn: bool = False
    # "all creatures **blocking this creature**" (The Wretched), "target green
    # creature blocking this creature" (Barbed-Back Wurm). The set of creatures
    # currently declared as blockers of the ability's own source (CR 509.1a).
    #
    # *Relative*, so no read of the blocker alone can answer it and
    # ``permanent_matches_filter`` never sees it — but emitted, and testable,
    # for exactly ``blocked_by_source``'s reason two fields down: what it needs
    # beyond the object is the ability's source, which ``subject_matches``
    # already takes. A caller with no source answers no, which refuses the
    # target rather than offering the board.
    #
    # It was unemitted for a set longer than its mirror, and the reason is worth
    # keeping: the symmetry alone was not enough. Making it emitted with no card
    # printing it as a **target** bought nothing and perturbed three shipped
    # Wurms, so it went back; Barbed-Back Wurm is the printing that pays for it.
    blocking_source: bool = False
    # "creatures blocking **target attacking creature**" (Feint) and "each
    # creature blocking **it**" (Feint's second sentence). The same relation as
    # ``blocking_source`` above with the other end moved: the creature being
    # blocked is not the ability's source but an object *this same sentence*
    # names — declared here as a nested noun phrase (``blocking_target``), or
    # referred back to as the pronoun the earlier sentence already targeted
    # (``blocking_bound_target``).
    #
    # A nested phrase rather than more adjectives, for the reason
    # ``targets_object`` above is one: the restriction is not a question about
    # the blocker at all, it is a question about *another object*, and the only
    # honest way to carry it is to carry that object's description. Both are
    # relative, so neither is emitted by ``to_payload`` and neither reaches
    # ``permanent_matches_filter`` — the lowerings written for them resolve the
    # blocked object first and read the combat maps from there, and every other
    # lowering refuses them by name.
    blocking_target: "ObjectFilter | None" = None
    blocking_bound_target: bool = False
    # "all non-Wall creatures **blocking enchanted creature**" (Coils of the
    # Medusa). The same CR 509.1a relation once more, with the blocked object
    # named as the Aura's own attachment: not the source (the source is the
    # Aura, which is not in combat at all), not a target (the sentence chooses
    # nothing), and not a nested phrase — an Aura enchants exactly one
    # permanent, so the description is the attachment record.
    #
    # Emitted and testable, on ``blocking_source``'s footing: what it needs
    # beyond the object is the ability's source, which ``subject_matches``
    # already takes, and one hop from there to the host. A caller with no
    # source answers no, which refuses the sweep rather than handing it every
    # blocker on the board.
    blocking_attached_host: bool = False
    # "each creature **that blocked or was blocked this turn**" (Heat
    # Stroke). CR 509.1a's relation with neither end named: the question
    # is whether this creature was on *either* side of a block, which is
    # readable off the permanent alone — so unlike every relation above
    # it, the pure matcher answers it and it stays in
    # ``OBJECT_ONLY_FILTER_KEYS``.
    blocked_or_was_blocked_this_turn: bool = False
    # "target creature **it's blocking**" (Goblin Snowman, Tinder Wall). The
    # mirror of ``blocking_source``: there the source is the attacker and the
    # set is its blockers, here the source is the *blocker* and the set is the
    # attackers it is blocking (CR 509.1a again, read the other way). Relative
    # like its twin, and unlike it this one *is* emitted, because
    # ``subject_matches`` can answer it: it needs the source, which that
    # function already takes.
    blocked_by_source: bool = False
    # "…all creatures **that blocked this creature this turn**" (Joven's
    # Ferrets). The same block record as ``blocked_by_bound_object`` above,
    # read off a third referent: the ability's own source. "This turn" is what
    # makes it a *history* rather than the live relation ``blocking_source``
    # carries — a turn holds several combats, and the creatures that blocked in
    # an earlier one, or died doing it, are in the set the words name while the
    # combat maps have forgotten them.
    #
    # Emitted, and testable for ``blocked_by_source``'s reason: the record
    # lives on the *candidate* (a blocker names the attackers it blocked), and
    # the only other thing needed is the ability's source, which
    # ``subject_matches`` already takes. A caller with no source answers no,
    # which refuses the sweep rather than handing it the board.
    blocked_source_this_turn: bool = False
    # "…destroy all Merfolk **tapped this turn to pay for its abilities**."
    # (Vodalian War Machine.) Narrower than "tapped this turn": a Merfolk
    # tapped to attack, or by somebody else's Icy Manipulator, is not in the
    # set. Nothing about a tapped permanent says how it came to be tapped, so
    # the phrase is answered from the record the payment path writes
    # (``engine/cost_tap_records.py``) rather than from any characteristic.
    #
    # Relative like ``blocked_by_source`` above, and emitted for the same
    # reason: what it needs is the ability's own source, which
    # ``subject_matches`` already takes. A caller with no source answers no,
    # which refuses the sweep rather than handing it the board.
    tapped_to_pay_for_source_this_turn: bool = False
    #: "…other than enchanted creature" (Kjeldoran Pride).
    other_than_attached_host: bool = False
    # "all creatures **banded with it**" (Icatian Skirmishers), "creatures
    # **banded with this creature**" (Camel). Membership of the attacking band
    # the ability's own source is in (CR 702.22e) — a relation, like
    # ``blocked_by_source`` above, and emitted for the same reason:
    # ``subject_matches`` can answer it, because it needs the source and the
    # game, which that function already takes.
    banded_with_source: bool = False
    # "target creature **that's attacking you**" (Ice Floe, Snow Fortress,
    # Giant Trap Door Spider). Not a state of the creature alone: CR 508.1a
    # makes attacking a state, but *whom* it attacks is the defending player it
    # was declared against, so the phrase is answered against the ability's
    # controller. Emitted, and testable for the same reason ``controller`` is —
    # a caller with no observer refuses rather than dropping the narrowing,
    # which would offer every attacker in a multiplayer game.
    attacking_you: bool = False
    # "target nonartifact, nonblack creature **that attacked you this turn**"
    # (Jabari's Influence). The *history* of the live relation beside it, and
    # its own field for that distinction exactly: ``attacking_you`` reads
    # ``Permanent.defending_player_index``, which end of combat clears — and
    # this card may only be cast *after* combat, so the live field is always
    # None by the time it is asked. Answered off a per-turn record the
    # declaration writes, and relative to the seat asking, which is what keeps
    # it out of the pure matcher.
    attacked_you_this_turn: bool = False
    # "…all creatures that were **blocked by that creature this turn**"
    # (Glyph of Doom). A history relative to the object a delayed triggered
    # ability was bound to, answered from the block record that creature
    # carries rather than from any characteristic of the creatures swept — so,
    # like `dealt_damage_to_source_this_turn` above it, it is a flag the one
    # lowering written for it reads and every other lowering refuses by name.
    # "This turn" is required and "that creature" is required: a turn holds
    # several combats, and without a bound object the phrase names a blocker
    # nobody recorded.
    blocked_by_bound_object: bool = False
    # "…all creatures that **blocked or were blocked by** it this turn"
    # (Venomous Breath). The two-way reading of the field above: the bound
    # object may have been the attacker or the blocker, and the sentence names
    # whichever creatures stood opposite it either way. Its own field rather
    # than a widening, because the one-way clause is a strictly smaller set and
    # a lowering written for one must not silently answer the other. Relative
    # like its sibling, so it is never emitted and every lowering not written
    # for it refuses the phrase by name.
    in_combat_with_bound_object: bool = False
    # "…all creatures that were blocked by **target Wall** this turn" (Glyph of
    # Reincarnation). The same history read against a different referent: the
    # blocker is the *spell's own target* rather than the object a delayed
    # ability was bound to, so the relation carries the filter that target had
    # to satisfy and the lowering hoists it into the instruction's `targets`
    # description. A sibling of `blocked_by_bound_object` rather than a
    # widening of it — which object the record is read off decides which seam
    # the handler asks, and one field meaning either would leave it guessing.
    blocked_by_target_object: "ObjectFilter | None" = None
    # "a creature **that has been dealt damage this turn**" (Giant Shark) — a
    # fact about the candidate alone, so it rides an ordinary payload key. Its
    # own field rather than a reading of `damage_marked`: damage marked is what
    # is *left* on the creature, and regeneration and a toughness rewrite both
    # erase it while the damage stays dealt (CR 120.3).
    was_dealt_damage_this_turn: bool = False
    # "…all creature cards in your graveyard **that were put there from the
    # battlefield this turn**" (No Rest for the Wicked). A history, and one no
    # matcher could answer by looking at the card: a card in a graveyard has a
    # printed line and nothing else (CR 613.1), and how it got there is a fact
    # the *game* wrote down as it happened
    # (``PlayerState.cards_put_into_your_graveyard_from_battlefield_this_turn``).
    #
    # So it is deliberately **not** a payload key on the filter: the card
    # matcher would have to answer it and cannot. The lowering hoists it beside
    # the filter, exactly as the sweep bounce hoists ``attached_to`` for the
    # same reason one family over, and the handler intersects the swept pile
    # with the record.
    put_there_from_battlefield_this_turn: bool = False
    # "target creature **of an opponent's choice** they control" (Preacher) —
    # who *picks* the object, which is not a property of any candidate. Never
    # emitted, so a lowering not written for it refuses the phrase instead of
    # quietly letting the ability's controller choose — which is the seat the
    # card says must not.
    chosen_by_opponent: bool = False
    #: "destroy all Plains **that weren't chosen this way by any player**"
    #: (Raiding Party). Not a characteristic and not a state: it is the
    #: complement of a set an earlier step of this same effect recorded, so no
    #: read of the board can answer it and ``to_payload`` deliberately does not
    #: emit it. The one lowering written for it carries the record's name as
    #: its own payload key; everywhere else ``_restrictions_beyond`` refuses
    #: the phrase, which is what keeps a sweep from quietly widening back to
    #: everything the noun names.
    not_chosen_this_way: bool = False
    #: "the number of green creatures **on the battlefield**" (An-Havva
    #: Constable, An-Havva Inn). CR 403.1 makes the battlefield one zone shared
    #: by every player, so the phrase is not a zone *change* — ``zone`` is
    #: already "battlefield" — it is the statement that the set is scoped to
    #: **nobody**. That matters because the absent scope is not neutral: a count
    #: whose filter names no controller is taken on the caster's own board
    #: (``lowering/_amounts.count_spec`` defaults ``owner`` to "you"), so a
    #: phrase read as though these words were not printed counts half the
    #: objects the card names.
    #:
    #: Its own field rather than a fourth ``controller`` value, because
    #: ``controller`` *is* emitted and every matcher reading it compares against
    #: "you" — a new value there would be answered by whichever branch happened
    #: to be the ``else``. Never emitted by ``to_payload`` for that reason, and
    #: listed in ``lowering/_filters.CONDITIONALLY_EMITTED_FIELDS`` so every
    #: lowering except the count refuses the phrase by name rather than quietly
    #: narrowing it to one seat. ``postmodifiers`` keeps "battlefield" out of
    #: ``_ZONE_NOUNS`` on exactly this argument — "a production that needs it
    #: should say so explicitly"; this is that explicit reading.
    on_the_battlefield: bool = False
    #: "…creatures with power **equal to or greater than the enchanted
    #: creature's toughness**" (Ironclaw Curse). A bound that is not a number
    #: but a live characteristic of the ability's own source — see
    #: :class:`SourceRelativeComparison` for why it is not a ``Comparison``.
    #: Emitted under its own payload key, which ``subject_filters`` answers
    #: before the pure matcher runs and refuses when the caller named no source.
    characteristic_vs_source: "SourceRelativeComparison | None" = None

    def to_payload(self) -> dict[str, object]:
        """Instruction-payload dict, emitting only keys that are set.

        The body is :func:`._payloads.object_filter_payload`, moved out at
        Exodus's Phase 0 when this module was three lines from the size guard.
        It stays a method because every caller in the engine speaks through the
        name; what moved is the 307 lines behind it.
        """
        return object_filter_payload(self)
