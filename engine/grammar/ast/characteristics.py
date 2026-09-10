"""What a permanent *is*: P/T, keywords, colour, printed text, counters.

CR 613 layers 5, 6 and 7 — pump and base-P/T setting, keyword grants and
losses, colour replacement, the printed-text swaps, and counters.

Counters are here rather than with the board for the reason the parsing side
puts them here: what a counter does is change a characteristic, and where it
sits is incidental.

Each of these carries a `Duration`, and it is a field rather than an assumption:
an effect with no duration is a continuous one, which lowering routes somewhere
else entirely.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
    CountOfMillsThisWay,
    Duration,
    Fixed,
    PlayerRef,
    ObjectFilter,
    Recipient,
)


@dataclass(frozen=True)
class Pump:
    subject: Recipient
    power: Amount
    toughness: Amount
    duration: Duration = field(default_factory=Duration)
    # "gets -2/-2": the sign is carried here rather than in the Amount so
    # "+X/+0" and "-X/-0" share one quantity vocabulary.
    power_negative: bool = False
    toughness_negative: bool = False
    # "gets -X/-X …, where X is the number of cards in your graveyard"
    # (Liliana, Waker of the Dead) — what the Var in power/toughness counts.
    # None when X is announced (a cast cost) rather than defined by the text.
    x_definition: Amount | None = None
    # "gets +1/+1 until end of turn **for each creature tapped this way**"
    # (Siege Striker). A back-reference to what an earlier sentence of the same
    # effect did, not a count of the board — the creatures it counts are the ones
    # that sentence tapped, and a board count would include every creature that
    # was already tapped. A flag rather than an `ObjectFilter`, because the set
    # is not describable: only the sentence in front of it knows which ones.
    per_each_tapped_this_way: bool = False
    # "gets +1/+0 until end of turn **for each creature card put into your
    # graveyard this way**" (Song of Blood). The flag above with a noun phrase
    # on it, and the phrase is why it is a node rather than a second boolean:
    # the record holds the *cards* a mill put there, so how many of them count
    # is a question the sentence asks and a flag has nowhere to put.
    per_each_milled: "CountOfMillsThisWay | None" = None
    # "gets +2/+2 **for each Aura attached to it**" (Rabid Wombat). A count of
    # the board rather than a back-reference, so unlike the flag above the set
    # *is* describable and the noun phrase describes it. The printed P/T is the
    # size of one repetition, not the whole bonus: the delta is that number
    # times the count.
    per_each: "ObjectFilter | None" = None
    # "…for each creature blocking it **beyond the first**" (Johtull Wurm, and
    # the reminder text CR 702.23a gives rampage). The count is one less than
    # the set's size, which is a property of the *count* and not of the objects
    # in it — so it rides here beside the noun phrase it modifies rather than
    # on the filter, where no matcher could answer it. A flag rather than a
    # number: "beyond the first" is the only offset Magic prints on this
    # clause, and a free integer would invite a lowering to invent one.
    per_each_beyond_first: bool = False


@dataclass(frozen=True)
class SetBasePT:
    subject: Recipient
    power: Amount | None
    toughness: Amount | None
    duration: Duration = field(default_factory=Duration)
    #: "…has base power 1 **or** base toughness 1." (Vhati il-Dal.) The other
    #: half of a sentence that offers its controller a choice between two
    #: rewrites of one creature.
    #:
    #: **Not CR 700.2's modality**, which that rule defines as a bulleted list
    #: preceded by "Choose one —": there are no bullets here, so the mode is not
    #: chosen as the ability is activated. It is CR 608.2d — a choice the effect
    #: offers, announced while the effect is applied — which is the same rule
    #: "gains your choice of deathtouch or lifelink" (Alchemist's Gift) is read
    #: under, and it lowers through the same ``choose_one`` seam.
    #:
    #: Recorded as a whole sibling node rather than as a flag, because the two
    #: options are two *different payloads*: one sets power and leaves the
    #: printed toughness, the other the reverse. A flag would have to be turned
    #: back into the second payload by whoever read it, which is a second
    #: reading of the sentence.
    alternative: "SetBasePT | None" = None


@dataclass(frozen=True)
class ChangeBasePT:
    """``Change <subject>'s base [power and] toughness to <value> [duration].``

    CR 613.4b: a resolving ability that *sets* base power and/or toughness —
    layer 7b, so later 7c modifications still apply on top. Legends prints the
    template four ways (Sentinel, Wall of Tombstones, Halfdane, Brine Hag) and
    "(This effect lasts indefinitely.)" is reminder text for the absent
    duration, which for a rewrite means CR 611.2a's "permanently".

    Distinct from :class:`SetBasePT` ("has base power …"): that is the shape
    whose value is a printed number and whose lowering demands an end-of-turn
    duration; this one's value is usually computed at resolution — a count, a
    chosen creature's power, or both stats of one chosen creature
    (*from_pt_of*, Halfdane) — and its duration is usually absent. Folding the
    two together would make each form's refusals the other's.
    """
    subject: Recipient
    power: Amount | None = None
    toughness: Amount | None = None
    # "to the power and toughness of target creature other than ~" (Halfdane):
    # both stats are read off one chosen creature when the ability resolves.
    from_pt_of: Recipient | None = None
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class GainKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)
    # "gains **your choice of** deathtouch or lifelink" (Alchemist's Gift) — the
    # keywords are *alternatives*, not a list. Same words as "gains deathtouch
    # and lifelink" once the conjunction is read, so the difference has to be
    # recorded here or the card grants both.
    choose_one: bool = False
    # "gains **landwalk of each of the land types of the sacrificed land**"
    # (Excavator). The granted word is not printed anywhere on the card: CR
    # 702.14a builds a landwalk's name out of a land type, and *which* land
    # type is only known once the cost has been paid. So ``keywords`` is empty
    # and this names the **record** the words are built from — a value rather
    # than a flag, because a second card reading a different record ("of target
    # land", "of the land you control") adds a word here and no field.
    landwalk_from: str | None = None
    # "…another target creature **gains it**" (Phyrexian Splicer). The pronoun
    # names an *ability* rather than an object — the one the activation chose
    # (CR 601.2b) — so, like ``landwalk_from`` above it, ``keywords`` is empty
    # and this says where the word comes from. A boolean rather than a record
    # name because there is one place an activation's choice is kept, on the
    # ability's own source, and naming it here would be a second spelling of
    # ``handlers/_common.CHOSEN_ABILITY``.
    chosen_ability: bool = False


@dataclass(frozen=True)
class GainAbilityText:
    """``<subject> gains "<ability>"[ and "<ability>"] [duration].``

    (Life Matrix, Glyph of Delusion, Johan.) The sibling of :class:`GainKeyword`
    for the case CR 113.3 makes different in kind: what is granted is a whole
    *printed ability*, not a word the layer system can hold.

    The text rides as printed rather than being read into a described effect,
    for the reason the emblem node states one file over — the compiler is the
    engine's one reader of a printed ability, and paraphrasing the sentence here
    would be this module deciding what "regenerate this creature" means. Whether
    the compiler can read it is asked at lowering time
    (``engine/granted_abilities.py``), so a grant the engine cannot perform
    refuses the line instead of shipping an ability that does nothing.
    """

    subject: Recipient
    abilities: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)
    #: The name the quoted text calls itself by, when it calls itself anything —
    #: "**Johan** can't attack". Read off the SELF token the lexer already made
    #: of it, and used for one thing: the support probe has to compile the
    #: sentence on a card by that name or the self-reference is an unknown noun.
    #: None for the ordinary spelling ("this creature"), which reads the same
    #: whoever holds it — and the difference is a lowering gate, because a
    #: self-naming ability granted to some *other* permanent is a sentence that
    #: stops compiling the moment it arrives.
    self_name: str | None = None
    #: "**If it doesn't have** "<ability>," it gains that ability." (Musician.)
    #: The grant happens only where the permanent does not already say the
    #: sentence. Recorded rather than dropped, because CR 611.2c lets a
    #: permanent hold the same ability twice and Musician's whole point is that
    #: it does not: a second copy would ask for the upkeep payment twice.
    only_if_absent: bool = False


@dataclass(frozen=True)
class LoseKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)
    # "…target creature with the chosen ability **loses it**" (Phyrexian
    # Splicer). See :class:`GainKeyword`'s field of the same name: the two
    # halves of that sentence are one move, and the pronoun is the same pronoun.
    chosen_ability: bool = False
    # "Until end of turn, target creature **loses all abilities** and has base
    # power and toughness 0/1." (Humble; Soul Sculptor prints the same clause
    # after a type change.) CR 613.1f's blanket removal aimed at one permanent.
    #
    # A field on this node rather than a node of its own, because what the
    # sentence *is* is unchanged: a subject, a duration, and a set of abilities
    # to take away. The set is simply "every one", which no tuple of keywords
    # can spell — an empty ``keywords`` already means "the chosen one" under the
    # flag above, and would mean "nothing at all" here.
    all_abilities: bool = False
    # "Target creature **loses your choice of** flying, first strike, or
    # trample until end of turn." (Walking Sponge.) The mirror of
    # :class:`GainKeyword`'s field of the same name, and it exists for the
    # reason that one does: CR 608.2d makes the pick an announcement while the
    # effect is applied, so "loses A, B, or C" takes **one** of them away and
    # "loses A, B, and C" takes all three. One word apart and two different
    # cards — and without the field the parser normalised both into the same
    # tuple, which is a removal of three abilities where the card removes one.
    choose_one: bool = False


@dataclass(frozen=True)
class PutCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))
    up_to: bool = False
    # "…, then double the number of +1/+1 counters on that creature."
    # (Invigorating Surge.) A rider rather than a second statement: "that
    # creature" is the one this placement just chose, and reading it as its own
    # sentence would leave the doubling looking for a target nobody picked.
    then_double: bool = False
    # "This ability can't cause the total number of +1/+0 counters on this
    # creature to be greater than **seven**." (Clockwork Beast; Clockwork Avian
    # prints four.) A rider on the placement rather than a sentence of its own:
    # it says nothing the game does, it bounds what the sentence in front of it
    # may do. Parsed apart it would be an effect nothing performs, and the
    # ability would put counters on without limit.
    cap: int | None = None
    # "**Distribute** X +1/+1 counters among any number of target creatures."
    # (Spoils of War.) The counters go on several targets in shares the caster
    # announces (CR 601.2d), exactly as a divided damage spell's do — so this
    # is the counter half of ``DamageRiders.divided`` and travels to the same
    # ``divided_targets`` list on the stack item. ``subject`` is then the noun
    # the shares are divided *among* rather than one permanent.
    distributed: bool = False
    # "…put a +1/+1 counter on target creature **of defending player's
    # choice**." (Erithizon.) Who *picks* the permanent, which is not a property
    # of any candidate and is not the ability's controller — so it is lifted off
    # the noun phrase and carried here, exactly as ``ChoosePermanent.chooser``
    # carries it for the sentence that says "<player> chooses" outright. None on
    # every card that prints no rider, which is the reading CR 601.2c gives:
    # the announcing player chooses.
    chooser: "PlayerRef | None" = None


@dataclass(frozen=True)
class DoublePower:
    """``Double the power of <subject> until end of turn.`` (Unleash Fury.)

    Its own node rather than a :class:`Pump` whose amount is "the subject's
    power": a pump's amount is fixed when the effect is created, and this one
    reads the power *at resolution*. Writing it as a Pump would need an Amount
    that means "ask the board later", which is a bigger idea than one card
    needs — and the two would then be indistinguishable in the IR.
    """
    subject: Recipient
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class RemoveCounter:
    subject: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class MoveCounter:
    """``Move a +1/+1 counter from this enchantment onto target creature.``
    (Afiya Grove.)

    **One effect, not a removal followed by a placement.** CR 122.5 makes a
    move a single action that does nothing at all when the first object has no
    such counter — so written as two steps in a sequence, an empty source would
    still put a counter on the destination, which is a card strictly better
    than the printed one.

    *source* and *destination* are both recipients, because the printed
    sentence names both ends; every card in this pool prints the ability's own
    permanent on the first end, and the lowering is what says so rather than
    this node pinning it.
    """
    source: Recipient
    destination: Recipient
    counter: str = "+1/+1"
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class PlayerGetsCounters:
    """``<player> gets [a|N] <kind> counter(s).`` (CR 122.1 counters on a
    *player* — Pit Scorpion's poison.)

    Its own node rather than a :class:`PutCounter` whose subject is a player,
    because the two sentences answer to different machinery end to end: a
    permanent's counters live on the object and die with it (CR 122.2), a
    player's ride the seat for the whole game, and the only rules meaning any
    player counter in this pool has is CR 122.1f's ten-poison loss. The kind is
    carried as printed — which kinds have a store is the lowering's question,
    so "gets an energy counter" fails by name there rather than failing to
    parse.
    """
    player: PlayerRef
    counter: str
    count: Amount = field(default_factory=lambda: Fixed(1))


@dataclass(frozen=True)
class ChangeText:
    """``Change the text of <subject> by replacing all instances of one <mode>
    with another.`` (CR 612 — Magical Hack, Sleight of Mind.)

    *mode* names which vocabulary is swapped, because that is the whole
    difference between the two printings and the only thing the handler reads.
    It is a closed set: a wording naming some other vocabulary is a text change
    the engine's substitution does not implement, and must fail to parse rather
    than arrive here as a mode nothing knows.

    *duration* is CR 612's other axis, and it defaults to the permanent one
    every card printed before Tempest has: Magical Hack, Sleight of Mind and
    Mind Bend all say "This effect lasts indefinitely" in their reminder text.
    **Whim of Volrath** is the first card in the pool to print a duration on
    one ("…until end of turn"), and it needs the field rather than a separate
    node because what differs is when the record is dropped, not what the
    record says.
    """

    subject: Recipient
    mode: str
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class BecomeCreature:
    """"…becomes a 3/3 Sphinx creature with flying **in addition to its other
    types** until end of turn." (Riddleform, CR 205.1b / CR 613 layer 4.) /
    "…becomes a 2/2 Assembly-Worker artifact creature until end of turn.
    **It's still a land.**" (Mishra's Factory.)

    An *addition*, not a replacement, which is the difference between this and
    :class:`BecomeColor` below and the difference the printed words state: the
    enchantment is still an enchantment while it is a creature, so anything that
    destroys enchantments still reaches it. The phrase is required rather than
    defaulted, because a card that replaced its types would be a different card
    and the words are the only thing that says which.

    The duration is **read**, never defaulted by the production: a sentence
    that prints "until end of turn" and one that prints nothing differ by
    everything that happens after the turn ends, so the word decides
    ``until_end_of_turn`` and the two lower to different instruction kinds.
    Mishra's Groundbreaker's "Target land becomes a 3/3 artifact creature
    that's still a land" is the second: CR 611.2a's default duration, stated by
    saying nothing, and the printed reminder ("This effect lasts indefinitely")
    is a parenthetical the lexer has already dropped.
    """
    subject: Recipient
    #: The printed size, or the string ``"x"`` where the card prints one —
    #: "{X}: This artifact becomes an **X/X** Construct artifact creature until
    #: end of turn." (Chimeric Staff.) The type is *widened* rather than
    #: repurposed: every node built before this held an int and still does, so
    #: no golden and no ratchet entry moves. ``handlers/_common.resolve_amount``
    #: is what turns the word into the number the activation paid, exactly as it
    #: does for every other amount a card spells with an X.
    power: "int | str"
    toughness: "int | str"
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    #: Card types the animation adds *besides* creature — "becomes a 2/2
    #: Assembly-Worker **artifact** creature" (Mishra's Factory). Recorded
    #: rather than collapsed into "creature", because an animated land that is
    #: not also an artifact is a different permanent: Shatter reaches one and
    #: not the other.
    card_types: tuple[str, ...] = ()
    #: The colours the animation *sets* — "…becomes a 2/2 **green** creature
    #: that's still a land" (Quirion Druid). Mana symbols, the spelling every
    #: other colour channel in the engine uses. A separate field from
    #: :class:`BecomeColor` rather than a second node, because one printed
    #: sentence says both things at once and CR 613 puts them in different
    #: layers: the creature body is layer 4 plus layer 7b, the colour is
    #: layer 5, and a card that named a colour and produced only the body
    #: would animate a *colourless* land — which Circle of Protection: Green
    #: does not stop and the card says it should.
    colors: tuple[str, ...] = ()
    #: Whether the animation ends at cleanup. False is "the effect lasts
    #: indefinitely" (Mishra's Groundbreaker) — CR 611.2a's default duration,
    #: which a printed sentence states by saying nothing. Defaulted True because
    #: that is what every other printing in the pool says out loud, and because
    #: a node built without the field must keep meaning what it used to.
    until_end_of_turn: bool = True
    #: Whether the animation ends at **end of combat** instead (Jade Statue,
    #: Clockwork Steed's cousin printings). A third state rather than a second
    #: meaning for the flag above, because the two windows are cleared by two
    #: different sweeps and a turn may hold two combats: a record swept at
    #: cleanup would leave the Statue a creature through the whole postcombat
    #: main phase, which is exactly the difference the card's own activation
    #: restriction ("only during combat") is printed to make matter.
    #:
    #: Defaulted False so every node built before this field existed means
    #: what it always did, and read only where the words are printed.
    until_end_of_combat: bool = False
    #: Whether the sentence printed **none** of CR 205.1b's retention clauses,
    #: which makes it CR 205.1a's default: the new card types *replace* the
    #: printed ones. "…it becomes a 2/2 Gargoyle creature with flying." (Opal
    #: Gargoyle) — the enchantment stops being an enchantment, which is the
    #: whole mechanism of the Hidden / Opal / Veiled cycle, since its own
    #: intervening-if asks whether it still is one.
    #:
    #: Its own field rather than ``not until_end_of_turn``-style inference from
    #: the others, and defaulted False so every node built before it existed
    #: keeps meaning what it did: the retention clauses are the ones the pool
    #: printed until now, and the addition is what those nodes claim.
    replaces_types: bool = False
    #: Whole printed abilities the body grants **in quotation marks** — "…a 4/4
    #: Serpent creature with "This creature can't attack unless defending
    #: player controls an Island."" (Veiled Serpent), "…with flying and "At the
    #: beginning of your upkeep, sacrifice this creature unless you pay
    #: {1}{U}."" (Veiled Apparition).
    #:
    #: The *lines*, not a parse of them, for ``CreateEmblem``'s reason one
    #: family over: an ability is what a line compiles to, and the channel that
    #: carries it (`engine/keywords.grant_ability_line`) is read back through
    #: the compiler — so a granted trigger reaches the upkeep step exactly as a
    #: printed one does. The production checks that each line parses before
    #: admitting the card, so nothing here grants text no reader claims.
    granted_ability_lines: tuple[str, ...] = ()
    #: "…an Illusion creature with **power and toughness each equal to that
    #: spell’s mana value**." (Veiled Sentry.) The size is not on the card at
    #: all: it is a characteristic of the spell the trigger fired on, so
    #: :attr:`power` and :attr:`toughness` carry nothing and the handler reads
    #: the trigger’s frozen record. CR 208.2’s "defined by an effect" rather
    #: than CR 604.3’s characteristic-defining ability — the number is fixed
    #: as the ability resolves and does not track the spell afterwards.
    pt_from_triggering_spell: bool = False
    #: "…a 4/4 Giant creature with **protection from each of that spell’s
    #: colors**." (Opal Titan.) CR 702.16g’s shorthand for one protection
    #: ability per colour, and which colours the same frozen record answers —
    #: a flag rather than a keyword string for that reason: the words are not
    #: on the card.
    protection_from_triggering_spell: bool = False


#: The colour an effect does not name because CR 608.2d makes the choice part of
#: resolving it — "becomes **the color of your choice**" (Alchor's Tomb). It
#: rides :attr:`BecomeColor.color` rather than a second boolean field, for the
#: reason ``PROTECTION_FROM_CHOSEN_COLOR`` rides the keyword string beside it: a
#: node with both a colour and a "no, ask" flag has a state where the two
#: disagree, and nothing to say which one the handler should believe.
CHOSEN_COLOR = "chosen_color"

#: The plural of it — "becomes **the color or colors** of your choice" (Dream
#: Coat). A different sentinel rather than a flag beside the singular, for the
#: reason the singular is a sentinel at all: what the card offers is a *set* of
#: colours where Alchor's Tomb offers one, and a reader that could not tell them
#: apart would silently answer the wider offer with the narrower one.
CHOSEN_COLORS = "chosen_colors"

#: "…becomes **colorless** until end of turn." (Raging Spirit, Ersatz Gnomes.)
#: Not a colour word — CR 105.2c makes colourless the *absence* of colour, so it
#: cannot ride ``COLOR_WORDS``, whose values are mana symbols. A sentinel on the
#: same field for the same reason the two above are: what the object becomes is
#: one fact about the sentence, and a second field for "and also nothing" would
#: be a second thing every reader has to remember.
COLORLESS = "colorless"

#: The basic land type an effect does not name, for the same CR 608.2d reason —
#: "becomes **the basic land type of your choice** until end of turn" (Jinx).
#: It rides :attr:`ChangeLandType.land_type` exactly as the two above ride
#: ``BecomeColor.color``, and for the identical reason: a node carrying both a
#: named type and a "no, ask" flag has a state where the two disagree and
#: nothing to say which one the handler should believe.
CHOSEN_LAND_TYPE = "chosen_land_type"


@dataclass(frozen=True)
class BecomeCopy:
    """"…this creature becomes a copy of that creature, except it has this
    ability." (Unstable Shapeshifter, CR 707.2.)

    A **layer 1** effect, which is what separates it from every other branch of
    the ``becomes`` production beside it: those change a characteristic over the
    object's copiable values, and this one *replaces* the copiable values every
    later layer starts from (CR 613.2c). So it lowers onto
    ``engine/copies.py``'s recorded contribution rather than onto a continuous
    effect, and nothing it does is a stamp.

    ``of`` is the object copied. Today it is always a back-reference to what the
    firing event was about ("that creature"), which the lowering requires: an
    unbound reading would copy whatever the resolution happened to be holding.

    ``keeps_own_ability`` is CR 707.9a's "except it has this ability" — the copy
    is granted the printed line this node came from, which is what makes the
    Shapeshifter copy again next time. Its own field rather than a value of the
    exception vocabulary in ``copies.copy_exceptions``: that table reads
    exceptions off the *copier's* text at the copy, and this is a clause of the
    sentence being lowered.
    """

    subject: Recipient
    of: Recipient
    keeps_own_ability: bool = False


@dataclass(frozen=True)
class BecomeColor:
    """"Target spell or permanent becomes red." (the Lace cycle, CR 105.)

    ``color`` is a mana symbol, or :data:`CHOSEN_COLOR` when the card prints
    "the color of your choice" and the word is not known until resolution.

    A colour *replacement*, not an addition — the object becomes that colour
    instead of its own. Mana symbols are unaffected, which is reminder text the
    lexer already strips.

    The Lace cycle prints no duration and the change is indefinite; the five
    Legends colour spells print "until end of turn". Both are this node, because
    the sentence is the same one with a clause on the end — and carrying the
    duration is what stops the parser consuming those four words and dropping
    them, which would have made Sylvan Paradise a permanent lace.
    """
    subject: Recipient
    color: str
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class GainType:
    """``<subject> becomes an artifact in addition to its other types.``
    (Ashnod's Transmogrant) / ``…becomes an artifact creature with power and
    toughness each equal to its mana value.`` (Xenic Poltergeist.)

    Distinct from :class:`BecomeCreature`, which names a printed P/T and a
    creature body. This one names *types* and, optionally, a P/T defined by the
    permanent's own mana value — so the two cannot share a node without one of
    them carrying a field the other must not set.

    ``duration`` with no kind means permanently, which is what Ashnod's
    Transmogrant prints: the creature stays an artifact after the Transmogrant
    is long gone.
    """
    subject: Recipient
    card_types: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)
    pt_from_mana_value: bool = False
    #: Whether the sentence printed **no** retention clause at all — "…becomes
    #: an enchantment." (Opal Acrolith.) CR 205.1a's default, so the types are
    #: *set* rather than joined and the node stops being a "gain" in anything
    #: but its name. Its own field for :attr:`BecomeCreature.replaces_types`'
    #: reason and defaulted the same way round: the two cards in the pool that
    #: predate it print the clause, and their nodes must keep meaning what they
    #: did.
    replaces_types: bool = False


@dataclass(frozen=True)
class BecomeAura:
    """``It becomes an Aura with "enchant creature put onto the battlefield
    with <this permanent>."`` (Necromancy.)

    CR 613 layer 4 and layer 6 in one printed sentence: the permanent gains the
    Aura subtype, and it gains the enchant ability (CR 702.5) that says which
    permanent it may legally be attached to. Its own node rather than a
    :class:`GainType` carrying a rider, because the enchant clause is not a
    type — it is the restriction CR 704.5m re-checks on every state-based pass,
    and a node that could not state it would be a type change with a dropped
    sentence behind it.

    ``noun`` is the enchant clause's head noun ("creature"), the same word
    ``mixins/stack/casting.permanent_matches_enchant_noun`` matches a host
    against everywhere else in this engine.

    ``origin_is_source`` is the clause's rider — "put onto the battlefield
    **with this permanent**", CR 201.5's self-reference, which the lexer has
    already collapsed to one token by the time this is built. It is carried
    rather than dropped because it is the whole point of the sentence: the Aura
    may enchant *that* creature and no other, so an effect that moves it
    (Enchantment Alteration) finds no legal host. A quality naming anything
    else refuses in the parse — the engine has no way to test it, and an
    untestable restriction admitted here is one the CR 704.5m sweep would
    silently ignore.

    ``card_types`` is the rest of the type line the sentence sets. Necromancy
    says only "an Aura", which is a subtype the enchantment already has; a
    Licid says "an **Aura enchantment**" and it is a *creature* saying it, so
    CR 205.1a's replacement is the difference between a permanent that is now
    an enchantment and one that is a creature wearing an Aura's subtype. Empty
    means the sentence named no card type, which is Necromancy's reading and
    not "no types".

    ``loses_own_ability`` is the Licid clause in front of the verb — "This
    creature **loses this ability** and becomes …" (CR 613 layer 6). One node
    for both halves, for the reason the enchant clause is on this node: the
    sentence is one thing the permanent becomes, and a permanent that had
    changed type while still carrying the ability that changed it could be
    activated again from the Aura it had turned into.
    """
    noun: str
    origin_is_source: bool = False
    card_types: tuple[str, ...] = ()
    loses_own_ability: bool = False


@dataclass(frozen=True)
class ChangeSupertype:
    """``<subject> becomes snow.`` / ``<subject> is no longer snow.``
    (Arcum's Weathervane, both of its abilities.)

    CR 205.4a's half of the type line, changed in CR 613 layer 4 like any other
    type. One node for both directions rather than a pair, because what differs
    between the Weathervane's two abilities is a single word and the effect,
    the layer, the channel and the handler are otherwise identical — the same
    reason ``combat_restrictions`` carries its polarity as payload beside the
    noun it applies to.

    A supertype needs no "in addition to its other types" tail the way
    :class:`GainType` does: CR 205.4a puts supertypes in front of the card
    types and adding one never displaces anything, so the printed sentence has
    nothing more to say.

    ``duration`` with no kind means permanently, which is what both printed
    abilities mean: the land stays thawed after the Weathervane is gone.
    """
    subject: Recipient
    supertype: str
    gained: bool = True
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class SwitchPT:
    """``Switch <subject>'s power and toughness [duration].`` (Transmutation.)

    CR 613.4d layer 7d, which the engine already applies — the switch is
    recorded as a flag through the characteristic group so two switches cancel
    and the swap acts on the values as they stand after 7c. What was missing
    was any way for a printed line to say it.

    Its own node rather than a :class:`Pump` with mirrored amounts: a pump's
    deltas are fixed when the effect is created, and a switch is not a delta at
    all — it reads both stats at every recompute, so a creature switched to 4/1
    and then given a +1/+1 counter is 5/2 rather than 4/1 plus a stale
    correction.
    """
    subject: Recipient
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class ChangeLandType:
    """``Target land becomes a Swamp until its controller's next untap step.``
    (Orcish Farmer.)

    CR 305.7's *replacement* of a land's basic land types (CR 613 layer 4):
    the land is a Swamp **instead of** whatever it was, and it loses the
    abilities its old types gave it. Distinct from :class:`GainType`, which
    adds a card type and takes nothing away, and from :class:`ChangeSupertype`,
    which changes the word in front of them.

    ``land_type`` is one basic land type, singular and lowercase — payload,
    because a card printed about a Forest is this sentence with one word
    changed. ``duration`` with no kind is CR 611.2's "indefinitely", which is
    what Evil Presence's targeted cousins print.
    """
    subject: Recipient
    land_type: str
    duration: Duration = field(default_factory=Duration)


@dataclass(frozen=True)
class LandTypeSwap:
    """``Choose a land type and a basic land type. Each land of the first
    chosen type becomes the second chosen type until end of turn.``
    (Vision Charm's third mode.)

    **Two printed sentences, one node**, for the reason the upkeep paragraphs
    are one each: neither half is a sentence on its own. The first produces no
    effect at all and the second names its parameters by ordinal — "the first
    chosen type" is a phrase with no referent outside the sentence in front of
    it — so a production that read them separately would have to invent a
    channel to join them and a reader to refuse the second one alone.

    Both catalogs are payload. ``first_basic`` / ``second_basic`` say whether
    each chosen type must be one of CR 205.3i's *basic* land types or may be any
    of them, which is exactly what the printed adjective says — Vision Charm
    asks for any type and then a basic one, and a card printing "two basic land
    types" is this sentence with one word changed.

    The duration is read rather than defaulted, for :class:`ChangeLandType`'s
    reason: without the words the change would last as long as the game does
    (CR 611.2), which is a different card.
    """

    first_basic: bool
    second_basic: bool
    duration: Duration = field(default_factory=Duration)
