"""What a printed noun phrase points at when what it points at is a **seat**.

Split out of ``_references`` when that module reached the thousand-line guard,
along the line this package has already drawn twice. ``references.py`` one layer
up states it: "CR 109 is what an object is, CR 115 is how a spell chooses one,
and a player (CR 102) is not an object at all" — so the object half
(:class:`ObjectFilter` and its comparisons) and the choice half
(:class:`TargetSpec`) stay where they were, and the two nodes that answer
*which seats* come here. It reuses the name ``lowering/_seats.py`` has carried
since it left `_common`, so the mirror re-forms rather than forking.

A floor, not a family, for ``_primitives``' reason exactly: ``_references``
reads :class:`PlayerDeed`'s filter annotation and ``_core`` re-exports both
names, so nothing imports this directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._references import ObjectFilter


@dataclass(frozen=True)
class PlayerDeed:
    """A relative clause naming **what a seat did**, not what it is.

    "…each player **who tapped a land for mana this turn** sacrifices a land of
    their choice. … deals 2 damage to each player **who sacrificed a Plains
    this way**." (Desolation.)

    Both halves narrow *which seats* a sentence is about by something they did
    earlier — one within the turn, one within this very resolution — which is
    the same shape :class:`PlayerRef`'s ``attacked_this_turn`` flag already
    carries for "target player who attacked this turn" (Fire and Brimstone).
    A node rather than a third flag because these two have a *parameter*: the
    "this way" reading names the printed noun phrase whose sacrifice counts,
    and a flag has nowhere to put it.

    ``kind`` names the record, never the card:

    - ``tapped_land_for_mana_this_turn`` — ``PlayerState``'s own per-turn
      record, written at the one tap-for-mana seam.
    - ``sacrificed_this_way`` — the seat-keyed sacrifice record an earlier step
      of the *same resolution* wrote, which is why ``filter`` is required for
      it and meaningless for the other: "this way" without a producer names
      nothing at all.

    Read only where a reader enforces it. A narrowing parsed somewhere nothing
    applies it is a sentence that acts on **every** seat — wrong in the
    caster's favour and silent — which is the reason the attack clause above is
    read beside the one lowering that honours it rather than by the shared
    recipient parser.
    """
    kind: str
    #: "…who sacrificed **a Plains** this way". The printed noun phrase the
    #: record's cards are tested against. None for a deed that names no object;
    #: a lowering that gets neither what it needs refuses rather than widening.
    filter: "ObjectFilter | None" = None


@dataclass(frozen=True)
class PlayerComparison:
    """A relative clause naming **how a seat compares with another seat**.

    "…chooses target player **who controls more creatures than they do**"
    (Oath of Druids); "Choose target opponent **who has at least two fewer
    creature cards in their graveyard than you do**" (Keeper of the Dead);
    "…**whose graveyard has fewer creature cards in it than their graveyard
    does**" (Oath of Ghouls).

    The board-state twin of :class:`PlayerDeed` beside it, and a separate node
    rather than a third row in ``_PLAYER_DEEDS`` because of the one property
    that decides where such a clause may live: **a comparison is answerable at
    announcement**. A deed is a resolution-time seat record with no cast-time
    answer, so the picker cannot enforce one and the two kinds in that table
    are enforced elsewhere; a board, a life total, a hand size and a graveyard
    can all be counted while CR 601.2c is choosing, which is what lets this
    clause be enforced where it must be — in ``legality``'s seat loop, the one
    list the picker and the announcement gate both read.

    ``quantity`` is what is counted, and it is a whole printed noun phrase
    (with its zone) rather than a word out of a closed list, so "more lands"
    and "more creature cards in their graveyard" are one clause with one phrase
    changed. A **string** covers the one quantity no noun phrase describes — a
    life total is not a pile to scan — and it is a name the lowering maps onto
    the single computation that is exactly it, refusing every other, which is
    the discipline :class:`BoardCount` states one module over. Not that node
    itself only because it lives in ``_core``, which imports *this* module.

    ``more`` is the direction and ``margin`` the printed threshold: "more" is a
    margin of one and "**at least two** more" is a margin of two, which is the
    same arithmetic with the number as data (CR 107.1). A margin spelled into
    the direction would make every other threshold a non-match.

    ``than`` is the seat compared against, as the ``PlayerRef`` kind that names
    it — "than **you** do" on an activated ability, "than **they** do" under a
    trigger whose subject the firing event froze. Carried rather than assumed,
    so a printing that compared against somebody else refuses at the lowering
    instead of quietly comparing against the chooser.

    ``is_opponent`` is the second conjoined clause the Oaths print — "…**and is
    their opponent**" (CR 102.2), relative to that same seat. On this node
    rather than beside it because both clauses hang on one antecedent and are
    answered against one reference: split apart, a reader could honour the
    comparison against the upkeep player and the opponent-ness against the
    enchantment's controller, which is two different sets.
    """
    quantity: "ObjectFilter | str"
    more: bool
    margin: int = 1
    than: str = "you"
    is_opponent: bool = False


@dataclass(frozen=True)
class PlayerRef:
    """A player or set of players."""
    kind: str  # you | each_player | each_opponent | target_player | target_opponent
               # | that_player | controller | owner | defending_player | chosen_player
               # | last_damager_controller
    # "target player or planeswalker" (Chandra's Magmutt) — one chosen target
    # that may be a player face or a planeswalker permanent (CR 115.4 without
    # the creature half). Set only by the production that read the union, so a
    # lowering that never sees the phrase never sees the flag.
    or_planeswalker: bool = False
    # "target player **who attacked this turn**" (Fire and Brimstone). A printed
    # restriction on which seats may be chosen, not a different kind of player —
    # so it rides here rather than minting a `target_player_who_attacked`, for
    # the reason every other narrowing is payload: a card printing the same
    # clause on "target opponent" needs no new kind.
    attacked_this_turn: bool = False
    # "target opponent **previously dealt damage by it**" (Diseased Vermin).
    # The same shape as the clause above — a printed restriction on which seats
    # may be chosen, not a kind of player — over a record kept on the ability's
    # own source rather than on the seat. Which is the whole reason it is a
    # second flag: "who attacked" is a fact about the player and "whom did *this
    # permanent* hurt" is a fact about the permanent, and the picker has to be
    # handed the source to answer the second.
    damaged_by_source: bool = False
    # "the controller of **the last red instant or sorcery spell that dealt
    # damage to you this turn**" (Suffocation) — the noun phrase that says
    # *which* history entry the seat is read out of, carried whole because a
    # card printed about a blue spell or an artifact source is the same
    # referent with one word changed.
    #
    # A field rather than a second kind for the reason every narrowing above is
    # one, and set only by the production that reads the phrase — so a
    # ``last_damager_controller`` without it is a shape no parse can produce
    # and the lowering refuses it rather than defaulting to "any source", which
    # would be 4 damage to whoever last pinged you with anything.
    last_damager: "ObjectFilter | None" = None
    # "each player **who tapped a land for mana this turn**" (Desolation). The
    # relative-clause narrowing above generalised: `attacked_this_turn` is one
    # printed clause spelled as a flag, and this is the clause family with its
    # record and its noun phrase as data. Set only by the productions that read
    # one, so a `PlayerRef` that never met the words carries None and every
    # existing lowering is untouched.
    #
    # A lowering handed one it cannot carry must **refuse**: an unenforced seat
    # narrowing is a sentence that acts on every player, which is the failure
    # direction this whole family exists to avoid.
    did: "PlayerDeed | None" = None
    # "each player **who controls a white creature**" (Disorder). The board-state
    # twin of `did` above and the *presence* twin of `compared` below: not what
    # the seat did and not how it compares with another seat, but simply whether
    # anything it controls answers a printed noun phrase.
    #
    # A third field rather than a `PlayerComparison` with a margin of one,
    # because that node requires a reference seat and a direction — "every word
    # is required and nothing is defaulted", its own reader says — and this
    # clause has neither. Set only by the production that reads the words, so
    # every existing `PlayerRef` carries None and no lowering moves.
    #
    # And subject to `did`'s rule exactly: a lowering handed one it cannot carry
    # must **refuse**, because an unenforced seat narrowing is a sentence that
    # acts on every player at the table.
    controls: "ObjectFilter | None" = None
    # "target player **who controls more creatures than they do and is their
    # opponent**" (the Exodus Oaths), "target opponent **who has more life than
    # you do**" (the Keepers). The relative clause above with a *board* for its
    # record instead of an event, carried here for `did`'s exact reason and
    # subject to its exact rule: a lowering handed one it cannot carry must
    # refuse, because an unenforced seat narrowing is a sentence that acts on
    # every player.
    #
    # The difference that matters is where it is enforced. `did`'s two kinds
    # are resolution-time records, so no picker can answer them; every
    # comparison here is answerable while the target is being chosen, so this
    # one *is* enforced by the picker — which is why it may ride a `PlayerRef`
    # a cast or an activation announces at all.
    compared: "PlayerComparison | None" = None
