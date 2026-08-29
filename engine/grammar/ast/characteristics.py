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
    # "gets +2/+2 **for each Aura attached to it**" (Rabid Wombat). A count of
    # the board rather than a back-reference, so unlike the flag above the set
    # *is* describable and the noun phrase describes it. The printed P/T is the
    # size of one repetition, not the whole bonus: the delta is that number
    # times the count.
    per_each: "ObjectFilter | None" = None


@dataclass(frozen=True)
class SetBasePT:
    subject: Recipient
    power: Amount | None
    toughness: Amount | None
    duration: Duration = field(default_factory=Duration)


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


@dataclass(frozen=True)
class LoseKeyword:
    subject: Recipient
    keywords: tuple[str, ...]
    duration: Duration = field(default_factory=Duration)


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
    """

    subject: Recipient
    mode: str


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

    ``until_end_of_turn`` is likewise required by the production: without a
    duration this is a permanent animation, and the two differ by everything
    that happens after the turn ends.
    """
    subject: Recipient
    power: int
    toughness: int
    subtypes: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    #: Card types the animation adds *besides* creature — "becomes a 2/2
    #: Assembly-Worker **artifact** creature" (Mishra's Factory). Recorded
    #: rather than collapsed into "creature", because an animated land that is
    #: not also an artifact is a different permanent: Shatter reaches one and
    #: not the other.
    card_types: tuple[str, ...] = ()


#: The colour an effect does not name because CR 609.3 makes the choice part of
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
