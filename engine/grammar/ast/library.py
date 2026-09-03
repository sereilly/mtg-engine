"""What a hidden zone's contents *are*: search, look-at, reveal-top.

The AST half of the ``library`` family the parse and lowering sides have
carried since The Dark, and the last of the three to split. It was left out on
purpose - `tests/engine/test_grammar_layering.py` recorded the reason, that a
near-empty ``ast/library.py`` would buy back the symmetry and cost the thing
symmetry is for. That reason expired the day the size guard fired on
``ast/cards.py`` itself, which is what this file is.

The line is ``effects/library.py``'s own, word for word: everything here names
a **pile being looked through**, and drawing, discarding, milling, scrying and
the hand reveals stay in ``cards.py`` because they name a *card moving*. So the
two modules keep the same seam on both sides, and a template has one home per
side rather than two candidates.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._core import (
    Amount,
    ObjectFilter,
    PlayerRef,
    Zone,
)


@dataclass(frozen=True)
class SearchPlayerLibrary:
    """``Search target player's library for three cards and exile them. Then
    that player shuffles.`` (Jester's Cap.)

    ``Search that player's library for that many cards. That player puts those
    cards into their hand, then shuffles.`` (Jester's Mask.)

    A different effect from :class:`SearchLibrary`, which that node's own
    production has said since it was written: "the engine's search flow only
    ever opens the searcher's own library, so 'search target player's
    library' is a different card, not a wording of this one". Two seats are
    involved rather than one — CR 608.2c makes the ability's controller the
    chooser and the library is somebody else's — and both have to reach the
    flow, which is what this node carries and :class:`SearchLibrary` has no
    field for.

    ``count`` is an amount rather than a number because Jester's Mask prints
    "for **that many** cards", the quantity being the size of a hand the step
    in front of it emptied. ``to`` is where every find goes: the pool's two
    printings send them all to one place, so there is one zone rather than the
    per-find list Cultivate needs.
    """
    player: PlayerRef
    count: Amount
    filter: ObjectFilter
    to: Zone

@dataclass(frozen=True)
class LookTopCycleForLife:
    """Lim-Dul's Vault's whole three-sentence effect.

    "Look at the top five cards of your library. As many times as you choose,
    you may pay 1 life, put those cards on the bottom of your library in any
    order, then look at the top five cards of your library. Then shuffle and
    put the last cards you looked at this way on top in any order."

    One node for all three sentences, the shape :class:`ExileUntilLeavesOrUntaps`
    already takes for Tawnos's Coffin: they describe one procedure and each of
    them dangles a referent the others bind. "Those cards" is what the sentence
    in front looked at, "the last cards you looked at this way" is whichever
    iteration was the last, and neither can be read by a production that only
    saw its own sentence.

    Both numbers are fields because both are printed, and a card cycling three
    cards for 2 life is this sentence rather than a second production. What is
    *not* a field is where the unwanted cards go or where the kept ones end up:
    the bottom and the top are the whole shape of the effect, and a wording that
    sorted them elsewhere would be a different card wearing this one's head.

    The shuffle is part of it and not a rider. The kept cards go on top **after**
    the library is shuffled (CR 701.24), which is the entire reason the card is
    a tutor rather than a look: shuffling first and then stacking is what makes
    the five known cards the next five draws.
    """
    count: Amount
    life_cost: Amount

@dataclass(frozen=True)
class SearchLibrary:
    player: PlayerRef
    filter: ObjectFilter
    to: Zone
    # "search your library **and/or graveyard**" — a second zone the search may
    # look in, not a wording of the first. It rides on the node rather than on
    # the filter because it says where the search happens, not what it may
    # find; the filter's `named` field carries the latter.
    graveyard: bool = False
    #: "…for **up to two** basic land cards … put **one** onto the battlefield
    #: tapped **and the other** into your hand" (Cultivate). One entry per find,
    #: in the printed order, so how many are found and where each goes are the
    #: same fact. ``to`` above is the single-find spelling and stays the first
    #: entry's zone; a card printing three destinations needs no new field.
    extra_destinations: tuple[Zone, ...] = ()
    #: Whether each find enters tapped, aligned with the destinations above.
    tapped: tuple[bool, ...] = ()
    #: "Up to" — finding fewer, none included, is a legal answer (CR 701.19b's
    #: fail-to-find is always legal, but this says so on the card).
    up_to: bool = False
    #: "…, **reveal it**, …" / "…, **reveal those cards**, …" (CR 701.20). What
    #: the word buys is the public record: a search that prints it shows the
    #: found cards' faces to every player, and the engine's reveal-event feed
    #: (``Game.record_reveal``) is that showing. A search without it — Demonic
    #: Tutor's — records nothing, so the field defaults off.
    reveal: bool = False
    #: "Then if you control four or more lands, untap that land." (Fabled
    #: Passage.) A rider on *this* search rather than a second statement,
    #: because "that land" is the card this search just found — a sentence after
    #: the search would run before the player has answered its prompt, and would
    #: have nothing to refer to. The filter is what is counted; the threshold is
    #: how many are needed.
    #: "a card named Alpine Watchdog **and/or** a card named Igneous Cur"
    #: (Alpine Houndmaster). One find per printed name, each optional — the
    #: "and/or" is what says a player may take either, both or neither. Its own
    #: field rather than a filter, because the filter carries what *one* find may
    #: be and this is a list of them.
    named_alternatives: tuple[str, ...] = ()
    untap_found_if: "Comparison | None" = None
    untap_found_filter: "ObjectFilter | None" = None

@dataclass(frozen=True)
class LookAtLibraryTop:
    """``Look at the top five cards of target player's library. You may then
    have that player shuffle that library.`` (Visions.)

    Distinct from ``LookTopPickToHand`` below, which is always about *your own*
    library and always takes a card out of it. This one takes nothing: the
    whole effect is the information, plus an offer to shuffle away the order
    the looker just learned. ``may_shuffle`` is on the node because the offer
    is about the library this sentence named — carried separately it would have
    to name a player again.
    """
    count: "Amount"
    player: PlayerRef
    may_shuffle: bool = False
    #: "…, **then put them back in any order**" (Natural Selection, Portent).
    #: The looker rearranges what they saw, which is a different effect from
    #: merely learning it — and a *different handler*, so it is a field rather
    #: than an assumption: Visions looks and never reorders, and reading the two
    #: as one would hand Visions' controller a rearrangement the card does not
    #: give them.
    may_reorder: bool = False

@dataclass(frozen=True)
class LookTopPickToHand:
    """``Look at the top three cards of your library. Put one of those cards
    into your hand and the rest on the bottom of your library in any order.
    If this spell was cast from anywhere other than your hand, put each of
    those cards into your hand instead.`` (See the Truth.)

    One node for the whole three-sentence template — the sentences share one
    set of looked-at cards, so parsed apart two of them dangle. The cast-zone
    conditional is part of the shape, not a separate statement: it reads the
    resolution context's ``cast_from_zone``, the field the stack object
    carries since the permission-seam round.

    Garruk's Harbinger prints the same shape with three differences, and each is
    a field rather than a second node because each is a *parameter* of the same
    procedure: the count is a back-reference ("that many"), the pick is optional
    and filtered ("you **may** reveal a creature card or Garruk planeswalker
    card"), and the rest go down **in a random order** rather than in any order.
    The last is a real distinction — "any order" leaves them as they lay because
    the ordering is the player's by rule, where "a random order" is a stated
    shuffle nobody may choose.
    """
    count: Amount
    #: What the taken card must be, as filter payload alternatives OR'd
    #: together. Empty means the See the Truth shape, where any of the looked-at
    #: cards may be taken.
    filters: tuple[dict, ...] = ()
    #: "You **may** reveal …" — declining is a legal answer, and not the same as
    #: an illegal one: the rest still go to the bottom.
    optional: bool = False
    #: "in a random order" vs "in any order".
    rest_order: str = "any"
    #: Where the cards *not* taken go. "Put one of them into your hand and **the
    #: other into your graveyard**" (Waker of Waves) is a different card from
    #: one that bottoms them, and the difference is invisible until the pile is
    #: looked at again — so the destination is stated rather than defaulted.
    rest_destination: str = "library_bottom"
    #: See the Truth's third sentence, which is a rider on this template rather
    #: than part of it: Diabolic Vision prints the pick and stops. Optional in
    #: the production for that reason, and carried here so a card that *does*
    #: print it cannot collapse into one that does not.
    all_to_hand_if_cast_elsewhere: bool = False
    #: Where the *taken* card goes. "Puts one of them **back on top of their
    #: library**" (Ashnod's Cylix) is this template with one word changed and a
    #: wholly different card behind it: nothing is drawn, and what the looker
    #: keeps is the card they draw next. A field for ``rest_destination``'s
    #: reason — the sentence states it, and a default would be a guess about
    #: the one thing the card is for.
    pick_destination: str = "hand"
    #: Who looks. None is the effect's own controller, which every card in this
    #: family printed until Ashnod's Cylix — "**Target player** looks at the
    #: top three cards of **their** library". The looker and the library are
    #: one seat by construction here (the possessive says "their"), so one
    #: field answers both; a card that split them would be a different node.
    looker: "PlayerRef | None" = None

@dataclass(frozen=True)
class LookTopExileRandom:
    """``Look at the top eight cards of your library. Exile four of them at
    random, then put the rest on top of your library in any order.`` (Orcish
    Librarian.)

    Its own node rather than a mode of :class:`LookTopPickToHand`, because
    nothing is *picked*: no card reaches a hand and no player chooses which
    cards go. What the two share is their tail — the rest going back on top in
    an order the player chooses — and that is shared where it is carried out,
    not by fusing the two statements that reach it.

    The exile is at random, so it is the effect rather than a decision, and it
    draws on the module RNG ``run_ai_simulation`` seeds: a given seed replays a
    given game exactly, which is the property the AI regression tests rest on.
    """
    count: Amount
    #: How many of the looked-at cards are exiled.
    exile_count: Amount
    #: Where the rest go. Only the top today — a card that bottomed them would
    #: be giving up the sorting this card is played for.
    rest_destination: str = "library_top"

@dataclass(frozen=True)
class RevealTop:
    """``Reveal the top card of your library.`` (Track Down.)

    The reveal alone. CR 701.20a makes revealing a card show it to all players
    and move it nowhere, so what this does to the game is *record what is
    there* — and the sentences after it read that record rather than the
    library, because by then a draw may have taken the card.

    Its own node beside :class:`RevealTopToHandOrBottom` rather than that one
    generalised. That template is one node for three sentences on purpose: its
    two destinations are the effect, and every word of them is required. This is
    the opposite decomposition — a reveal that records, and whatever ordinary
    conditional follows it — so folding them together would make the Garruk
    template's own docstring untrue of half its cases.

    ``player`` is **whose** library is looked at. "Reveal the top card of
    **target opponent's** library" (Prophecy) is this same effect over another
    seat's deck, and which deck is opened is the one thing about it that cannot
    be inferred: an unstated seat reads as the caster's, so a card that named
    somebody else would reveal the wrong library and record the wrong card for
    every sentence behind it. Defaulted to "you", so every reveal written
    before this keeps a byte-identical node.
    """

    player: PlayerRef = PlayerRef("you")

@dataclass(frozen=True)
class RevealTopToHandOrBottom:
    """"Reveal the top card of your library. If it's a <filter>, put it into
    your hand. Otherwise, put it on the bottom of your library." (Garruk,
    Savage Herald.) One node for the whole three-sentence template: the
    sentences reference one revealed card, so parsing them separately would
    leave two of them meaning nothing on their own."""
    filter: ObjectFilter

@dataclass(frozen=True)
class LookAtHand:
    """"Look at target player's hand." (Glasses of Urza, CR 402.3.)

    An information effect: nothing about the game state changes, so it is a
    leaf of its own rather than a flavour of ``ReturnToZone``. The player is
    modeled rather than assumed, because *whose* hand is looked at is the whole
    content of the clause.
    """
    player: PlayerRef
    #: "Look at **a card at random** in target player's hand." (Urza's Bauble.)
    #: How much of the hand is seen, which is the other half of the clause's
    #: content: one card chosen by nobody, rather than all of them. A flag and
    #: not a count because "at random" is what makes it uncountable — a card
    #: printing "two cards at random" would need the number, and would refuse
    #: here until it had it.
    random_card: bool = False
