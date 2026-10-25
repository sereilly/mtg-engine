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

    "…to target player **who attacked this turn**" (Fire and Brimstone); "…to
    target opponent **previously dealt damage by it**" (Diseased Vermin);
    "…each player **who tapped a land for mana this turn** sacrifices a land of
    their choice. … deals 2 damage to each player **who sacrificed a Plains
    this way**." (Desolation.)

    Every one narrows *which seats* a sentence is about by something done
    earlier — within the turn, to the ability's source, or within this very
    resolution — and this node is the one spelling of all of them: the first
    two used to be flags on :class:`PlayerRef`, each read by one branch of the
    target lowering, so a flag on the other kind was dropped and "target
    opponent who attacked this turn" offered every opponent.

    ``kind`` names the record, never the card:

    - ``attacked_this_turn`` — ``PlayerState``'s per-turn record, stamped at
      the declaration (CR 508.1).
    - ``dealt_damage_by_source`` — the record the damage seam keeps on the
      ability's own source ("by **it**").
    - ``tapped_land_for_mana_this_turn`` — ``PlayerState``'s own per-turn
      record, written at the one tap-for-mana seam.
    - ``sacrificed_this_way`` — the seat-keyed sacrifice record an earlier step
      of the *same resolution* wrote, which is why ``filter`` is required for
      it and meaningless for the others: "this way" without a producer names
      nothing at all.

    **When a kind can be answered is the kind's**, and it decides where the
    clause may live (``handlers/_filters.PLAYER_DEEDS``, the one table the
    lowering and the readers share). The first three are facts before a spell
    is cast as much as after, so on a *chosen* seat the picker enforces them
    (CR 601.2c) and the CR 608.2b re-check reads the same list; the fourth has
    no answer until the resolution has run, so on a chosen seat it refuses.

    Read only where a reader enforces it. A narrowing parsed somewhere nothing
    applies it is a sentence that acts on **every** seat — wrong in the
    caster's favour and silent.
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
    rather than another row of ``PLAYER_DEEDS`` because what it holds is a
    relation between two seats rather than a record of one: a board, a life
    total, a hand size and a graveyard counted while CR 601.2c is choosing,
    against a reference seat, in a direction, by a margin. Like the deeds that
    can be answered at announcement it is enforced in
    ``legality_enumeration``'s seat loop, the one list the picker and the
    announcement gate both read.

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
    #: "…than you do **as you activate this ability**" (the Exodus Keepers).
    #: The printed words bound *when* the clause is asked: as the target is
    #: chosen (CR 602.2b) and not again — the cards' 2009-10-01 rulings: "It is
    #: only necessary that the condition be true as you activate the ability.
    #: The ability will still resolve normally even if the condition is no
    #: longer true at that time." So CR 608.2b's re-check asks the target what
    #: it asks any "target opponent", without the comparison
    #: (``player_comparisons.comparison_at_resolution``). An Oath's clause
    #: prints no such words and stays a restriction at both moments.
    as_announced: bool = False


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
    # "target player **who attacked this turn**" (Fire and Brimstone), "each
    # player **who tapped a land for mana this turn**" (Desolation). A printed
    # restriction on which seats the sentence is about, not a kind of player —
    # so a card printing the same clause on "target opponent" needs no new
    # kind. Set only by the production that reads the words
    # (``records.accept_player_deed``), so a `PlayerRef` that never met them
    # carries None and every lowering that does not read it is untouched.
    #
    # A lowering handed one it cannot carry must **refuse**: an unenforced seat
    # narrowing is a sentence that acts on every player, which is the failure
    # direction this whole family exists to avoid. On a chosen seat that means
    # the picker's description carries it, which only a deed answerable at
    # announcement can be (see :class:`PlayerDeed`).
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
    # Where it is enforced is the picker: every comparison here is answerable
    # while the target is being chosen, so this may ride a `PlayerRef` a cast
    # or an activation announces — exactly as a `did` whose kind is answerable
    # at announcement may, and one whose record only the resolution writes may
    # not.
    compared: "PlayerComparison | None" = None
