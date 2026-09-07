"""Who controls a permanent, and what puts it back (CR 613 layer 2).

The AST half of the ``control_changes`` family the parse and lowering sides
have carried since Legends, and the last of the three to split.
``tests/engine/test_grammar_layering.py`` recorded the reason it was left out —
that a near-empty ``ast/control_changes.py`` would buy back the symmetry and
cost the thing symmetry is for — and that reason expired the way
``ast/library.py``'s and ``ast/exile.py``'s did before it: the *inventory*
crossed the size guard. ``ast/board.py`` reached 977 lines with a wave about to
add a node to it, and this is the line its own docstring already draws —
"destruction, bouncing, control, sacrifice".

The seam is ``effects/control_changes.py``'s, word for word: everything here
names **which seat a permanent answers to**, and destroying, bouncing,
sacrificing or attaching one stays in ``board.py`` because those name what
happens *to* the permanent rather than who it belongs to. So the three sides
keep one seam and a template has one home per side rather than two candidates.

Both exchanges live here rather than beside the destroy they can trail, for the
same reason: CR 701.12b's exchange is a control change made atomic, and
``MutualControlOfSets`` is the two ordinary ones its own docstring argues it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._core import ObjectFilter, PlayerRef, Recipient


@dataclass(frozen=True)
class GainControl:
    """``Gain control of <subject> for as long as <duration>.`` (CR 613 layer 2.)

    *duration* is what ends the control change, and it is required rather than
    defaulting to "permanently": an untimed steal (Control Magic) and a linked
    one (Aladdin) revert under completely different circumstances, and a
    production that let the clause be absent would also let it be *deleted*
    with no change to what was lowered.

    The untimed steal now has a *name* — ``"indefinite"`` (CR 611.2a: an effect
    with no stated duration lasts until the game ends) — rather than a missing
    value, and that is the whole of why the field stayed required. ``None``
    would have been the deleted-clause value the paragraph above warns about;
    a word the production has to write cannot be produced by dropping a clause.

    *tap_when_lost* is the trailing sentence "When you lose control of the
    creature, tap it." (Ray of Command, Magus of the Unseen) — CR 603.7's
    delayed trigger, folded onto the change it watches rather than parsed as a
    step of its own, because on its own the sentence names no object at all.

    *gained_by* is who ends up controlling it, when that is **not** the effect's
    own controller: "an opponent may gain control of a creature you control of
    their choice" (Infernal Denizen). The field is what gives "their choice" an
    antecedent — "their" is the sentence's printed subject, and a node that did
    not carry the subject would have to guess which seat picks. Absent means the
    ordinary reading, the resolving object's controller (CR 109.5).

    *offered* is the "may" in front of that verb, folded onto this node rather
    than left as an enclosing :class:`May`. The offer and the pick are one
    decision made by one seat — the seat named by *gained_by*, which is also the
    seat *their_choice* names — so they are one prompt, declinable. Wrapped in a
    ``May`` instead they would be two prompts to the same player whose two
    answers could disagree, and whose two non-interactive defaults would have to
    be kept in step.
    """

    subject: Recipient
    duration: str
    tap_when_lost: bool = False
    #: Who gains control, when the sentence names them ("**target opponent**
    #: gains control of this creature", Chaos Lord; "**an opponent** may gain
    #: control of a creature you control of their choice", Infernal Denizen).
    #: ``None`` is the ability's own controller, which is what every other
    #: "gain control of …" spelling means and what every reader written before
    #: this field assumed — so the default keeps them exactly as they were.
    #:
    #: A field rather than a second node because the two sentences differ in one
    #: word: everything else about a control change — the timestamp, the
    #: contribution, what ends it — is the same rule whoever the seat is.
    #:
    #: Two parallel branches added this field in the same wave under two names
    #: (``gained_by`` and ``gainer``) for two cards. One fact, one field.
    gained_by: "PlayerRef | None" = None
    #: Whether the seat above may decline it ("**may** gain control").
    offered: bool = False


@dataclass(frozen=True)
class BidLifeForControl:
    """``Each player may bid life for control of <subject>.`` (CR 613 layer 2.)

    Illicit Auction's whole printed paragraph, read as one node because the four
    sentences after the first are the *procedure* rather than four effects: they
    say who bids first, in what order the offer goes round, when it stops and
    what the winner pays. Split into a :class:`Sequence` they would each have to
    be an effect nothing can perform alone — "the bidding ends if the high bid
    stands" describes no board change at all.

    ``starting_bid`` is the number the printed second sentence names ("You start
    the bidding with a bid of 0"), carried as data for the reason every other
    printed number in this AST is: a card opening the bidding at 3 is this
    sentence with one word changed.

    The auction's *winner* takes the permanent indefinitely (CR 611.2a — the
    printed "(This effect lasts indefinitely.)" is that default said out loud),
    so there is no duration field to get wrong: unlike :class:`GainControl`,
    this sentence has exactly one ending and it is "never".
    """

    #: Who may bid — the offer's own printed subject ("**Each player** may
    #: bid…"). Carried rather than assumed, because the sentence prints it and
    #: a card offering the auction to a narrower set of seats ("each opponent")
    #: would be a different auction with the same procedure. The lowering
    #: refuses the sets no round-robin here can walk, so the word cannot be
    #: read and then dropped.
    bidders: Recipient
    subject: Recipient
    starting_bid: int = 0


@dataclass(frozen=True)
class ExchangeControl:
    """``Exchange control of <first> and <second>.`` (CR 701.12b — Gauntlets of
    Chaos.)

    One node for both halves rather than two control changes in a
    :class:`Sequence`, for the reason CR 701.12a states: an exchange is atomic,
    so if either half cannot be completed *no part of it happens*. Written as
    two steps the first would apply and the second would not, which hands one
    player a permanent for nothing.

    ``shares_a_type`` is the printed "…that shares one of those types with it".
    It is a relation *between the two slots*, not a property of either
    permanent, so it rides here beside them exactly as the two-target pump's
    ``distinct`` does — an :class:`ObjectFilter` has nothing to compare against
    and would have to drop it.

    ``destroy_attached_auras`` is the trailing "If those permanents are
    exchanged this way, destroy all Auras attached to them." A rider on this
    node rather than a following statement, because "exchanged **this way**" is
    a question only the exchange can answer: on its own the sentence names no
    permanents at all.
    """

    first: Recipient
    second: Recipient
    shares_a_type: bool = False
    destroy_attached_auras: bool = False


@dataclass(frozen=True)
class ExchangeGreatestManaValue:
    """``You and target player exchange control of the <type> you each control
    with the greatest mana value. Then exchange control of <type>s the same
    way. If two or more permanents a player controls are tied for greatest,
    their controller chooses one of them.`` (Juxtapose.)

    A whole paragraph as one node, for the reason `paragraphs.py` states: "the
    same way" names an exchange the sentence before it described, and the
    tie-break sentence names permanents no sentence of its own has chosen. Read
    apart, the second sentence exchanges nothing and the third is about nobody.

    ``card_types`` is the printed list in printed order, so a card exchanging
    lands or enchantments the same way is this node with different words. Each
    exchange is separate and atomic (CR 701.12a): a player controlling no
    permanent of one type simply exchanges nothing *of that type*, and the
    other types still happen.
    """

    card_types: tuple[str, ...]


@dataclass(frozen=True)
class MutualControlOfSets:
    """``You and <player> each gain control of all <noun> the other controls
    <duration>.`` (Reins of Power.)

    Two seats, one printed noun phrase, and a **reciprocal** reference: "the
    other" names whichever member of the pair this half is not. That
    reciprocity is what the node *is*, which is why there is no
    :class:`PlayerRef` kind for the words — a seat reference answers "which
    seat", and "the other" has no answer until you say which half is asking.
    One node rather than two :class:`GainControl` steps under a
    :class:`Conjunction` for the reason :class:`SimultaneousUntapAndTap` is
    one: CR 611.2c fixes both sets when the effect begins, where in sequence
    the second step would read a board the first had already changed and hand
    straight back what it had just taken.

    **Not** CR 701.12's exchange (:class:`ExchangeControl`) despite swapping two
    sets: the printed verb is "each gain control of", so these are two ordinary
    control-changing effects at once rather than one atomic exchange. A
    permanent that can't change controllers (CR 614.17) stays where it is while
    the rest move, where half an exchange would have to be no exchange at all.

    ``filter`` is the printed noun both halves share, so a card printed about
    artifacts is this node with one word changed. ``duration`` is the printed
    ending, spelled as :class:`GainControl` spells its own and required for that
    field's reason — a word the production has to write cannot be produced by
    dropping a clause.
    """

    other: PlayerRef
    filter: ObjectFilter
    duration: str
