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
