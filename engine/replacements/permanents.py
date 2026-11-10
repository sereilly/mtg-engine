"""A permanent's own events replaced: entering the battlefield, untapping, its
+1/+1 counters, a land's mana (CR 614.1c-d, 614.12, 502.3, 106.12b).

``would_enter_battlefield`` above all — a creature that was not cast exiled
instead, an entry cost that cannot be paid sending the permanent to the
graveyard instead, an optional discard toll, a sacrifice the permanent's entry
requires, and the "then sacrifices a land" rider an entry replacement records
(Land Equilibrium, ``apply_entry_riders``); before them all, and never one of
their contenders, ``cant_enter_battlefield`` (lands that can't enter at all,
a CR 614.17 "can't") — and
beside it the events that happen to a permanent already there: ``would_untap``
(counters removed or the permanent returned to hand instead of untapping),
``plus1_counters`` (one more, Conclave Mentor) and ``land_mana_produced``
(what a tapped land makes instead).

Split out of ``replacements.py`` at the 2,000-line cap's split round. A
permanent **leaving** — dying, or going anywhere instead of a graveyard — is
``zone_changes.py``'s.
"""

from __future__ import annotations

import re

from ..effect_ordering import source_names
from ..replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from .registry import (COUNTERS_REMOVED_INSTEAD_OF_UNTAPPING,
                       EXILE_INSTEAD_OF_ENTERING, EXTRA_PLUS1_COUNTER,
                       LANDS_CANT_ENTER, LAND_MANA_SUBSTITUTION,
                       OPTIONAL_ENTRY_DISCARD, SACRIFICE_AFTER_ENTERING, UNPAYABLE_ENTRY_COST,
                       UNPAYABLE_ENTRY_SACRIFICE, ReplacementOutcome,
                       replacement_effect)


EXTRA_PLUS1_COUNTER_TEXT = (
    "if one or more +1/+1 counters would be put on a creature you control, "
    "that many plus one +1/+1 counters are put on that creature instead"
)


def _applies_extra_plus1_counter(game, payload: dict) -> bool:
    player = payload.get("player")
    return player is not None and game._player_controls_text(
        player, EXTRA_PLUS1_COUNTER_TEXT
    )


def _extra_plus1_counter_sources(game, payload: dict) -> list:
    """The placing seat's permanents printing the sentence (Conclave Mentor).
    Pure."""
    player = payload.get("player")
    if player is None:
        return []
    return game._permanents_with_text(player, EXTRA_PLUS1_COUNTER_TEXT)


def _the_entering_permanent(game, payload: dict) -> list:
    """The permanent the event is about, for an effect its own text prints
    about itself (Frankenstein's Monster, Mox Diamond, the Alliances lands,
    Undiscovered Paradise). Pure."""
    found = payload.get("permanent")
    return [] if found is None else [found]


def _seats_printing(text: str):
    """A ``sources`` reader: every permanent on any battlefield printing
    *text*, for a sentence that names no seat ("Lands can't enter", "if a
    nontoken creature would enter"). Pure."""

    def sources(game, payload: dict) -> list:
        return [
            permanent
            for player in game.players
            for permanent in game._permanents_with_text(player, text)
        ]

    return sources


@replacement_effect(
    "plus1_counters", EXTRA_PLUS1_COUNTER, applies=_applies_extra_plus1_counter,
    sources=_extra_plus1_counter_sources,
    label="That many plus one +1/+1 counters are put on it instead",
)
def _one_more_plus1_counter(game, payload: dict) -> ReplacementOutcome | None:
    """Conclave Mentor: "If one or more +1/+1 counters would be put on a
    creature you control, that many plus one +1/+1 counters are put on that
    creature instead."

    A *modifying* replacement, not a consuming one: the event still happens,
    with a bigger number. Returning ``new_amount`` would be the shape damage
    uses, but this event's quantity is ``count`` — so the payload is written
    directly and nothing is consumed.

    **One more for each Mentor.** Each copy is its own effect and each
    applies once (CR 616.1f) — "If you control two Conclave Mentors, the
    number of +1/+1 counters put on a creature is two plus the original
    number. Three Conclave Mentors add three, and so on." (its ruling,
    2020-06-23). One registration stands for every copy, as the damage
    multipliers' does (``_multiply_damage_dealt``), so it adds one per source;
    it added one in all, and two Mentors put two counters where the card
    puts three. The copies' order changes nothing (each adds one), so there
    is no choice between them to put to anybody.
    """
    sources = _extra_plus1_counter_sources(game, payload)
    extra = max(1, len(sources))
    payload["count"] = int(payload.get("count", 0)) + extra
    permanent = payload.get("permanent")
    name = getattr(getattr(permanent, "card", None), "name", "a creature")
    by = ", ".join(source_names(sources))
    game.log.append(
        f"{name} gets {'one more +1/+1 counter' if extra == 1 else f'{extra} more +1/+1 counters'}"
        + (f" ({by})" if by else "")
    )
    return ReplacementOutcome()


EXILE_UNCAST_CREATURE_TEXT = (
    "if a nontoken creature would enter and it wasn't cast, exile it instead"
)


def _applies_exile_uncast_creature(game, payload: dict) -> bool:
    permanent = payload["permanent"]
    # Every clause of the printed sentence, asked here rather than in the body:
    # CR 616.1 counts the effects in contention before running any, so an
    # interceptor that answered by applying itself would make them uncountable.
    if payload["was_cast"] or permanent.metadata.get("is_token", False):
        return False
    if not permanent.is_creature:
        return False
    # "…would enter" is any battlefield, not just its controller's: Containment
    # Priest stops an opponent's reanimation too. ``_player_controls_text``
    # answers about one seat, so the question is asked of every seat.
    return any(
        game._player_controls_text(player, EXILE_UNCAST_CREATURE_TEXT)
        for player in game.players
    )


@replacement_effect(
    "would_enter_battlefield", EXILE_INSTEAD_OF_ENTERING,
    applies=_applies_exile_uncast_creature,
    sources=_seats_printing(EXILE_UNCAST_CREATURE_TEXT),
    label="Exile it instead of letting it enter the battlefield",
)
def _exile_instead_of_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Containment Priest: "If a nontoken creature would enter and it wasn't
    cast, exile it instead."

    The permanent never enters, so nothing that watches entering sees it — no
    enters-the-battlefield trigger, no layer contribution, no summoning-sickness
    stamp. That is the whole point of a CR 614 replacement over a
    "when it enters, exile it" trigger, which would let every one of those
    happen first.

    A token is *created* rather than put onto the battlefield from a zone, and
    ceases to exist rather than being exiled (CR 111.7), which is why the
    printed word "nontoken" is a clause of the applicability rather than an
    approximation of it.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[owner_index if owner_index is not None else payload["controller_index"]]
    game.put_card_into_exile(owner, permanent.card)
    game.log.append(
        f"{permanent.card.name} was exiled instead of entering the battlefield"
    )
    return ReplacementOutcome(replaced=True)


def _entry_exile_requirement(game, payload: dict) -> dict | None:
    """What the entering permanent's own text demands it exile, or None.

    Asked of ``engine/enter_effects.entry_exile_requirement`` - the same reader
    the entry state performs the exile with and the support gate claims the line
    with - so the sentence that refuses the entry and the sentence that carries
    it out cannot describe different cards.
    """
    from ..enter_effects import entry_exile_requirement

    permanent = payload["permanent"]
    # The **effective** card, like the two tolls beside it: the permanent as
    # it would exist on the battlefield (CR 614.12). Under a Humility the
    # creature has no such sentence, and it enters rather than being put into
    # a graveyard for a cost it was never asked to pay. This read the printed
    # card, which no effect can change.
    return entry_exile_requirement(
        permanent.effective_card, permanent.metadata.get("cast_x_value")
    )


def _applies_unpayable_entry_cost(game, payload: dict) -> bool:
    """Whether the controller cannot pay the entry cost the permanent prints.

    Pure, as CR 616.1 requires: it counts the graveyard rather than emptying it.
    "From **your** graveyard" is the seat the permanent would enter under, which
    is the payload's own ``controller_index`` - a replacement is asked about the
    event that *would* happen, and the permanent is on no battlefield yet to
    have a controller derived for it.
    """
    from ..handlers._filters import _card_matches_filter

    required = _entry_exile_requirement(game, payload)
    if required is None:
        return False
    count = int(required["count"])
    # "Exile zero cards" is something everyone can do, so the sentence below is
    # not reached - Frankenstein's Monster cast for X=0 enters as its printed
    # 0/1 with nothing exiled and no counter on it.
    if count <= 0:
        return False
    described = required["filter"]
    available = sum(
        1
        for card in game.players[payload["controller_index"]].graveyard
        if _card_matches_filter(
            card, described, game=game, owner=payload["controller_index"],
        )
    )
    return available < count


@replacement_effect(
    "would_enter_battlefield", UNPAYABLE_ENTRY_COST,
    applies=_applies_unpayable_entry_cost, sources=_the_entering_permanent,
    label="Put it into its owner's graveyard instead: its entry cost can't be paid",
)
def _graveyard_instead_of_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Frankenstein's Monster: "If you can't, put this creature into its owner's
    graveyard instead of onto the battlefield."

    A consuming replacement, and it has to be one: the permanent never enters,
    so nothing that watches entering sees it - no permanent id, no layer
    contribution, no enters-the-battlefield trigger, no summoning-sickness
    stamp. A "when it enters, sacrifice it" reading would let every one of those
    happen first and would put a *permanent* into a graveyard, which is a death
    (CR 700.4) and fires the dies triggers this card never should.

    Its owner's graveyard, not its controller's: the card is going to the zone
    CR 400.3 gives it, and the two differ for a creature cast off a Ring of
    Ma'ruf or under a control effect that changed hands before it resolved.

    The claim for this sentence lives in ``engine/enter_effects.py`` with the
    other two sentences of the same CR 614.1c effect, rather than in
    ``REPLACEMENT_LINES`` beside every other interceptor here: the three
    sentences are one paragraph and one replacement, and claiming a sentence of
    it twice is two claims free to drift. ``_entry_exile_requirement`` above
    reads that module, so this interceptor still self-selects off the card's own
    text the way every other one in this file does.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[
        owner_index if owner_index is not None else payload["controller_index"]
    ]
    game.put_card_into_graveyard(owner, permanent.card)
    game.log.append(
        f"{permanent.card.name} was put into {owner.name}'s graveyard instead of "
        f"entering the battlefield"
    )
    return ReplacementOutcome(replaced=True)


#: Marks a permanent whose optional entry toll has already been answered.
#:
#: On the permanent rather than on the game, because the question is asked of
#: one object: two Mox Diamonds entering in one turn each get their own offer,
#: and a permanent that leaves takes the answer with it (CR 400.7). Its own key
#: rather than a re-read of the battlefield, because the accepted answer
#: **re-enters the permanent** through the one entry path - and without a mark
#: the interceptor would offer the same choice again, forever.
ENTRY_TOLL_ANSWERED = "entry_toll_answered"


def _entry_discard_toll(game, payload: dict) -> dict | None:
    """The optional entry toll the entering permanent prints, or None.

    Read off the permanent's ``effective_card``, so a Clone of one has the
    sentence (CR 707.2) and one whose text was changed does not. Pure, like
    every applicability predicate in this file: ``effect_ordering`` counts the
    contenders before any of them runs.
    """
    from ..enter_effects import entry_discard_requirement

    permanent = payload["permanent"]
    if permanent.metadata.get(ENTRY_TOLL_ANSWERED):
        return None
    return entry_discard_requirement(permanent.effective_card)


def _applies_optional_entry_discard(game, payload: dict) -> bool:
    return _entry_discard_toll(game, payload) is not None


@replacement_effect(
    "would_enter_battlefield", OPTIONAL_ENTRY_DISCARD,
    applies=_applies_optional_entry_discard, sources=_the_entering_permanent,
    label="Discard as it enters, or put it into its owner's graveyard instead",
)
def _discard_or_graveyard_instead_of_entering(
    game, payload: dict
) -> ReplacementOutcome | None:
    """Mox Diamond: "If this artifact would enter, you may discard a land card
    instead. If you do, put this artifact onto the battlefield. If you don't,
    put it into its owner's graveyard."

    A consuming replacement whichever way it is answered, and it has to be one:
    the choice is made *before* the entry (CR 614.1a), so both halves of it are
    this function's business. Letting the permanent enter and charging
    afterwards would make declining put a **permanent** into a graveyard, which
    is a death (CR 700.4) with an entry, an id, layer contributions and every
    enters-the-battlefield trigger in front of it - a different card.

    That is also what separates this from the Alliances sac lands one entry up.
    Their toll is mandatory when it can be paid (CR 101.3), so their "if you
    don't" branch is reached only by a player who *cannot* pay and the entry
    state charges the rest; here the branch belongs to a player who simply
    declines, and nothing after the entry can un-enter the permanent.

    **One decision, not two.** Which card is discarded and whether to discard at
    all are asked together, because nothing is learned between them: the offer
    lists the hand cards the phrase admits, plus declining. Two prompts would be
    two chances for a seat to answer half.
    """
    from ..handlers._filters import _card_matches_filter

    permanent = payload["permanent"]
    controller_index = int(payload["controller_index"])
    player = game.players[controller_index]
    spec = _entry_discard_toll(game, payload)
    filters = spec["filter"]
    payable = [
        index
        for index, held in enumerate(player.hand)
        if _card_matches_filter(held, filters, game=game, owner=player)
    ]
    # Marked before the offer, not after: a non-interactive seat resolves inside
    # `offer_replacement_choice`, and the resolver re-enters the permanent
    # through the one entry path - which asks this replacement again.
    permanent.metadata[ENTRY_TOLL_ANSWERED] = True
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="entry_discard_toll",
            player_index=controller_index,
            # Declining last, so index 0 is the toll being paid when there is
            # anything to pay it with. A seat that cannot pay is offered only
            # the decline, which is CR 101.3's outcome written as the only
            # option rather than as a branch somewhere else.
            options=tuple(
                player.hand[index].name for index in payable
            ) + ("decline",),
            # Paying, when the hand can. The engine's rule for an unconstrained
            # choice is the one a player would make (idiom 8), and the whole
            # point of a card that asks this is that the permanent is worth the
            # card - a seat that declined by default would put every Mox Diamond
            # it ever drew straight into its graveyard.
            default_option=0,
            data={
                "permanent": permanent,
                "controller_index": controller_index,
                "hand_indices": payable,
                "was_cast": bool(payload.get("was_cast")),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} may discard a card to put "
            f"{permanent.card.name} onto the battlefield"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("entry_discard_toll")
def _resolve_entry_discard_toll(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Apply Mox Diamond's offer, either way.

    An index into the offered hand cards pays the toll and the permanent enters;
    the last option - and any answer outside the list - declines, and the card
    goes to its **owner's** graveyard, which is the zone CR 400.3 gives it and
    the one the printed sentence names.

    The hand slot is resolved to its card and removed through
    ``Game.take_card_from_hand``: a hand is a list of ``CardDefinition`` where
    every copy of a card is one object, so an identity filter would delete all
    of them where this removes exactly one.

    Returns 0 - nothing here draws.
    """
    data = choice.data
    permanent = data["permanent"]
    controller_index = int(data["controller_index"])
    player = game.players[controller_index]
    indices = list(data.get("hand_indices") or [])
    if 0 <= option_index < len(indices):
        slot = indices[option_index]
        if 0 <= slot < len(player.hand):
            discarded = player.hand[slot]
            game.take_card_from_hand(player, discarded)
            game._discard_card(player, discarded)
            game.log.append(
                f"{player.name} discarded {discarded.name} to put "
                f"{permanent.card.name} onto the battlefield"
            )
            game._put_permanent_onto_battlefield(
                controller_index, permanent, None,
                was_cast=bool(data.get("was_cast")),
            )
            return 0
    owner_index = game.owner_index_of(permanent)
    owner = game.players[
        owner_index if owner_index is not None else controller_index
    ]
    game.put_card_into_graveyard(owner, permanent.card)
    game.log.append(
        f"{permanent.card.name} was put into {owner.name}'s graveyard instead "
        "of entering the battlefield"
    )
    return 0


def _entry_sacrifice_candidates(game, payload: dict) -> list[int]:
    """Battlefield indices of the permanents that could pay the entering
    permanent's toll.

    Asked of ``Game._sacrifice_candidate_indices`` - the same reader the prompt
    that charges the toll enumerates with - so "can they pay?" and "what may
    they give up?" cannot answer about different permanents. That pairing is the
    whole point: a predicate counting more widely than the prompt offers is a
    land that enters and then charges nothing.

    "From **your** battlefield" is the seat the permanent would enter under,
    which is the payload's own ``controller_index``: a replacement is asked
    about the event that *would* happen, and the permanent is on no battlefield
    yet to have a controller derived for it.

    CR 614.13a: the permanent that is entering can never be chosen to pay for
    its own entry, so it is excluded here as well as at the prompt. It is not on
    a battlefield yet, so nothing would find it - but the exclusion is what the
    rule says and the entry state below repeats it where it *can* be found.
    """
    from ..enter_effects import entry_sacrifice_requirement

    permanent = payload["permanent"]
    required = entry_sacrifice_requirement(permanent.effective_card)
    if required is None:
        return []
    return game._sacrifice_candidate_indices(
        game.players[payload["controller_index"]], required["filter"], permanent
    )


def _entry_sacrifice_refuses_entry(game, payload: dict) -> bool:
    """Whether this permanent's toll says what happens when nothing can pay it.

    Only one of the two printed templates does. "If you don't, put it into its
    owner's graveyard" is a refusal this interceptor performs; "instead
    sacrifice each other permanent named Sheltered Valley you control, **then**
    put this land onto the battlefield" names no such branch, because an empty
    set is something every player can give up — so that card enters whatever
    the board holds and this effect is not its business at all.
    """
    from ..enter_effects import entry_sacrifice_requirement

    required = entry_sacrifice_requirement(payload["permanent"].effective_card)
    return required is not None and required["unpaid"] == "graveyard"


def _applies_unpayable_entry_sacrifice(game, payload: dict) -> bool:
    """Whether the controller has nothing the entering permanent's toll accepts.

    Pure, as CR 616.1 requires: it enumerates the battlefield rather than
    emptying it. A permanent printing no toll is not this effect's business at
    all, which is what the empty list from ``_entry_sacrifice_candidates``
    distinguishes - so the requirement is asked again here rather than inferred
    from the count.
    """
    if not _entry_sacrifice_refuses_entry(game, payload):
        return False
    # **How many the sentence asks for**, not whether the board holds one.
    # "Sacrifice **two** untapped lands instead" (Lotus Vale, Scorched Ruins) is
    # indivisible: a player with a single untapped land cannot pay it, and a
    # predicate that only asked "is there anything?" would let the land enter
    # and then charge one — a strictly cheaper card than the one printed. The
    # count comes from the same reader the prompt sizes itself from, so "can
    # they pay?" and "how many do they give up?" cannot disagree.
    from ..enter_effects import entry_sacrifice_requirement

    required = entry_sacrifice_requirement(payload["permanent"].effective_card)
    owed = int(required["count"]) if required is not None else 1
    return len(_entry_sacrifice_candidates(game, payload)) < owed


@replacement_effect(
    "would_enter_battlefield", UNPAYABLE_ENTRY_SACRIFICE,
    applies=_applies_unpayable_entry_sacrifice, sources=_the_entering_permanent,
    label="Put it into its owner's graveyard instead: there is nothing to sacrifice",
)
def _graveyard_instead_of_paying_entry_sacrifice(
    game, payload: dict
) -> ReplacementOutcome | None:
    """The Alliances sac lands: "If you don't, put it into its owner's
    graveyard."

    A consuming replacement, and it has to be one for
    ``_graveyard_instead_of_entering``'s reason: the land never enters, so
    nothing that watches entering sees it - no permanent id, no layer
    contribution, no enters-the-battlefield trigger, and no land drop spent on a
    permanent that arrived. A "when it enters, sacrifice it" reading would let
    every one of those happen first and would put a *permanent* into a
    graveyard, which is a death (CR 700.4).

    Its owner's graveyard, not its controller's: the card is going to the zone
    CR 400.3 gives it, and the printed sentence says "its owner's".

    The other half of the same printed paragraph - the sacrifice the entry is
    bought with - is performed by the entry state
    (``mixins/permanent_state._perform_entry_state``), which runs only once this
    has declined to apply, so by then the battlefield is known to hold something
    the toll accepts. That is Frankenstein's Monster's arrangement exactly, and
    the claim for all three sentences lives with it in ``engine/enter_effects.py``
    rather than in ``REPLACEMENT_LINES``: three sentences are one paragraph and
    one replacement, and claiming a sentence of it twice is two claims free to
    drift.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[
        owner_index if owner_index is not None else payload["controller_index"]
    ]
    game.put_card_into_graveyard(owner, permanent.card)
    game.log.append(
        f"{permanent.card.name} was put into {owner.name}'s graveyard instead of "
        f"entering the battlefield (nothing to sacrifice for it)"
    )
    return ReplacementOutcome(replaced=True)


#: "Lands can't enter the battlefield." (Worms of the Earth.)
LANDS_CANT_ENTER_TEXT = "lands can't enter the battlefield"


def _applies_lands_cant_enter(game, payload: dict) -> bool:
    # Layer 4, not the printed line: an animated land is still a land, and a
    # permanent that is a land as it *would* exist on the battlefield is what
    # CR 614.17d says to check.
    if not payload["permanent"].has_type("land"):
        return False
    # "Lands can't" is every battlefield, not just the source controller's —
    # the sentence names no seat at all. `_player_controls_text` answers about
    # one seat, so the question is asked of every one.
    return any(
        game._player_controls_text(player, LANDS_CANT_ENTER_TEXT)
        for player in game.players
    )


@replacement_effect(
    "cant_enter_battlefield", LANDS_CANT_ENTER,
    applies=_applies_lands_cant_enter,
    sources=_seats_printing(LANDS_CANT_ENTER_TEXT),
    label="The land doesn't enter the battlefield",
)
def _lands_cannot_enter(game, payload: dict) -> ReplacementOutcome | None:
    """Worms of the Earth: "Lands can't enter the battlefield."

    CR 614.17: a "can't" effect is not a replacement effect, but it follows the
    same rules, which is why it is registered here — this is the one place the
    engine asks "may this permanent enter?" before it does. Under its own event
    kind, ``cant_enter_battlefield``, asked before ``would_enter_battlefield``
    and never among its contenders: an event that can't happen may be replaced
    only by a self-replacement effect (614.17c), so CR 616.1e's choice is
    never put between this and Land Equilibrium or an Alliances land's toll. It is not the play
    restriction beside it on the same card: that one (CR 305.1, enforced through
    ``Game._may_play_another_land``) is about the *action* of playing a land,
    and this one is about a land arriving from anywhere at all — a reanimation,
    a search that puts one onto the battlefield, a token.

    The land does not enter and nothing that watches entering sees it: no
    permanent id, no layer contribution, no enters-the-battlefield trigger. It
    stays a card in whatever zone the caller took it from, which is why nothing
    is appended to a graveyard or an exile here — CR 614.17 removes the event
    rather than redirecting it, and a destination this rule does not name would
    be a card the effect quietly moved.
    """
    game.log.append(
        f"{payload['permanent'].card.name} can't enter the battlefield"
    )
    return ReplacementOutcome(replaced=True)


LAND_EQUILIBRIUM_TEXT = (
    "if an opponent who controls at least as many lands as you do would put a "
    "land onto the battlefield, that player instead puts that land onto the "
    "battlefield then sacrifices a land of their choice"
)

#: The metadata key an entry replacement's "then …" half is recorded under,
#: read once the permanent is actually on the battlefield.
ENTRY_SACRIFICE_KEY = "sacrifice_land_after_entering"


def _land_count(game, seat: int) -> int:
    """How many lands *seat* controls, through the control seam and layer 4 —
    so an animated land is still a land and a stolen one counts for whoever
    controls it now."""
    return sum(1 for perm in game.controlled_by(seat) if perm.has_type("land"))


def _land_equilibrium_watchers(game, payload: dict) -> list:
    """The permanents whose replacement this entry answers to.

    Every clause of the printed sentence, asked here rather than in the body,
    because CR 616.1 counts the effects in contention before running any:

    * the entering permanent is a land (layer 4, not the printed line);
    * the seat it would enter under is an **opponent** of the source's
      controller — a Land Equilibrium never taxes its own controller;
    * that opponent controls **at least as many** lands as the source's
      controller *now*, before the land arrives. A replacement effect is asked
      about the event that *would* happen (CR 614.1), and the land that would
      enter is not on the battlefield to be counted yet.

    A list rather than a boolean because two copies are two effects and each
    charges its own land, the reason ``_damage_multiplier`` counts its sources.
    """
    permanent = payload["permanent"]
    if not permanent.has_type("land"):
        return []
    entering_seat = payload["controller_index"]
    watchers = []
    for perm in game.all_permanents():
        if LAND_EQUILIBRIUM_TEXT not in (perm.effective_card.oracle_text or "").lower():
            continue
        owner_seat = game.controller_index_of(perm)
        if owner_seat is None or entering_seat not in game.opponents_of(owner_seat):
            continue
        if _land_count(game, entering_seat) >= _land_count(game, owner_seat):
            watchers.append(perm)
    return watchers


def _applies_land_equilibrium(game, payload: dict) -> bool:
    return bool(_land_equilibrium_watchers(game, payload))


@replacement_effect(
    "would_enter_battlefield",
    SACRIFICE_AFTER_ENTERING,
    applies=_applies_land_equilibrium, sources=_land_equilibrium_watchers,
    label="Its controller sacrifices a land as it enters",
)
def _sacrifice_after_entering(game, payload: dict) -> ReplacementOutcome | None:
    """Land Equilibrium: "If an opponent who controls at least as many lands as
    you do would put a land onto the battlefield, that player instead puts that
    land onto the battlefield then sacrifices a land of their choice."

    A *modifying* replacement, not a consuming one — the land still enters, and
    every enters-the-battlefield trigger and layer contribution happens
    normally. What the sentence adds is the word "then": the sacrifice comes
    after the entry, so the land that just arrived is itself a legal choice.

    The event is still in front of the entry here, so the sacrifice is recorded
    on the permanent and armed by :func:`apply_entry_riders` once the
    battlefield actually holds it. Arming it from this line would offer a
    non-interactive seat a board the new land is not on yet.
    """
    permanent = payload["permanent"]
    watchers = _land_equilibrium_watchers(game, payload)
    permanent.metadata[ENTRY_SACRIFICE_KEY] = (
        int(permanent.metadata.get(ENTRY_SACRIFICE_KEY, 0)) + len(watchers)
    )
    game.log.append(
        f"{game.players[payload['controller_index']].name} will sacrifice "
        f"{len(watchers)} land(s) for {permanent.card.name} "
        f"({watchers[0].card.name})"
    )
    return ReplacementOutcome()


def apply_entry_riders(game, permanent, controller_index: int) -> None:
    """The "…**then** X" half of an entry replacement, once the permanent is on
    the battlefield — or once a replacement applied after it took the entry
    away (CR 616.1e lets the affected player apply Land Equilibrium ahead of
    an Alliances land's unpaid toll; CR 614.6: the modified event, "puts that
    land onto the battlefield then sacrifices a land", is what the toll then
    modified, and only its entry).

    Called from the one entry path there is, for the same reason the entry
    replacement itself is asked there: a rider per caller is a rider forgotten
    by every caller that arrives later. Nothing is recorded for an ordinary
    entry, so this is a metadata read and a return.
    """
    owed = int(permanent.metadata.pop(ENTRY_SACRIFICE_KEY, 0))
    if owed <= 0:
        return
    game.arm_forced_sacrifice(
        controller_index,
        owed,
        filter={"type_filter": "land"},
        reason="Land Equilibrium",
    )



# ---------------------------------------------------------------------------
# The untap step (CR 502, CR 614)
# ---------------------------------------------------------------------------

#: "If a permanent with a wind counter on it would untap during its controller's
#: untap step, remove all wind counters from it instead." (Freyalise's Winds.)
#:
#: Matched by **shape**, like the redirect and the damage cap in
#: :func:`replacement_claims_line` (``lines.py``), because the counter's word is payload: a
#: card printing "frost counter" is the same sentence and must need no second
#: constant. The word is repeated in the pattern with a backreference, so a line
#: that puts one counter on and removes a *different* one stays unclaimed rather
#: than being read as this effect.
_COUNTERS_INSTEAD_OF_UNTAP = re.compile(
    r"^if a permanent with an? (?P<counter>[a-z][a-z' -]*) counter on it would "
    r"untap during its controller's untap step, remove all (?P=counter) "
    r"counters from it instead$"
)


def counters_instead_of_untap(line: str) -> str | None:
    """The counter word *line* removes in place of an untap, or None.

    One reader, three callers: the support gate through
    :func:`replacement_claims_line`, the applicability predicate below, and the
    interceptor. A second reader of the phrase is how a card ends up claimed by
    a gate and replaced by nobody.
    """
    normalized = " ".join((line or "").split()).strip().lower().rstrip(".")
    match = _COUNTERS_INSTEAD_OF_UNTAP.match(normalized)
    return match.group("counter") if match is not None else None


def _untap_counter_kinds(game) -> list[str]:
    """Every counter word a permanent on the battlefield says to remove instead
    of untapping.

    Every battlefield, because the sentence names no seat: "a permanent" is any
    permanent and "its controller's untap step" is whichever step that is. Read
    off ``effective_card`` so a text change (CR 612) and a granted line both
    count.
    """
    kinds: list[str] = []
    for permanent in game.all_permanents():
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            counter = counters_instead_of_untap(line)
            if counter is not None and counter not in kinds:
                kinds.append(counter)
    return kinds


def _applies_counters_instead_of_untap(game, payload: dict) -> bool:
    from ..named_counters import counters_on

    permanent = payload.get("permanent")
    if permanent is None:
        return False
    return any(
        counters_on(permanent, kind) > 0 for kind in _untap_counter_kinds(game)
    )


def _counters_instead_of_untap_sources(game, payload: dict) -> list:
    """Every permanent whose line names a counter the untapping permanent
    carries (Freyalise's Winds). Pure."""
    from ..named_counters import counters_on

    permanent = payload.get("permanent")
    if permanent is None:
        return []
    found = []
    for printer in game.all_permanents():
        for line in (printer.effective_card.oracle_text or "").splitlines():
            counter = counters_instead_of_untap(line)
            if counter is not None and counters_on(permanent, counter) > 0:
                found.append(printer)
                break
    return found


@replacement_effect(
    "would_untap", COUNTERS_REMOVED_INSTEAD_OF_UNTAPPING,
    applies=_applies_counters_instead_of_untap,
    sources=_counters_instead_of_untap_sources,
    label="Remove those counters instead of untapping",
)
def _remove_counters_instead_of_untapping(
    game, payload: dict
) -> ReplacementOutcome | None:
    """Freyalise's Winds: "If a permanent with a wind counter on it would untap
    during its controller's untap step, remove all wind counters from it
    instead."

    A genuine CR 614 replacement rather than an entry in
    ``engine/untap_restrictions.py``: that table says which permanents *do not
    untap*, and a row there would keep the permanent tapped and leave the
    counters on it forever — the card is a soft lock, not a hard one, and the
    difference is one turn per counter.
    """
    from ..named_counters import counters_on, remove_counters

    permanent = payload["permanent"]
    removed = 0
    for kind in _untap_counter_kinds(game):
        held = counters_on(permanent, kind)
        if held:
            remove_counters(permanent, kind, held)
            removed += held
    if not removed:
        return None
    game.log.append(
        f"{permanent.card.name} does not untap; {removed} counter(s) removed instead"
    )
    return ReplacementOutcome(replaced=True)


# ---------------------------------------------------------------------------
# CR 106.12b — what a land produces when it is tapped for mana
# ---------------------------------------------------------------------------


def _land_mana_tapper(game, payload: dict) -> "int | None":
    """The seat that tapped the event's land for mana — who the production
    belongs to when the land itself has left (``swapped_production``)."""
    player = payload.get("player")
    return next(
        (index for index, found in enumerate(game.players) if found is player),
        None,
    )


def _land_mana_substitutions(game, payload: dict) -> tuple:
    """The substitutions over this event's production, in the order the
    tapper's request picks (``land_mana_swaps.ordered_substitutions``) and
    resolved for it: what every reader below answers from. Pure."""
    from ..land_mana_swaps import ordered_substitutions

    return ordered_substitutions(
        game, payload["land"], payload.get("requested"),
        tapper=_land_mana_tapper(game, payload),
    )


def _applies_land_mana_substitution(game, payload: dict) -> bool:
    return bool(_land_mana_substitutions(game, payload))


def _land_mana_substitution_instances(game, payload: dict) -> list:
    """Each substitution over this production as a CR 616.1 effect of its
    own: ``(key, source)``, in the order they apply.

    CR 616.1e puts the order to the land's controller, and the event cannot
    wait for an answer — a land is tapped for mana part-way through paying a
    cost (CR 601.2g) — so the choice arrives **with the tap**: the symbol the
    tapper asked for picks the order (``ordered_substitutions``), and the
    instances are listed in it. Nothing asks between them, so CR 616.1e's
    default for an unasked round — the first of equal orders — applies them
    in that order, the last applied deciding what the land makes."""
    return [
        (substitution.key, substitution.source)
        for substitution in _land_mana_substitutions(game, payload)
    ]


def _land_mana_substitution_sources(game, payload: dict) -> list:
    """What makes the land produce something else for this event: each
    permanent whose static says so (Infernal Darkness, Pulse of Llanowar) and
    each card that armed one of the seat's records (Deep Water, Harvest Mage),
    in the order they apply — so the option names every effect it stands
    for. Pure."""
    return [
        substitution.source
        for substitution in _land_mana_substitutions(game, payload)
        if substitution.source is not None
    ]


@replacement_effect(
    "land_mana_produced", LAND_MANA_SUBSTITUTION,
    applies=_applies_land_mana_substitution,
    instances=_land_mana_substitution_instances,
    sources=_land_mana_substitution_sources,
    label="The land produces the named type of mana instead",
)
def _substitute_land_mana(
    game, payload: dict, instance: "str | None" = None,
) -> ReplacementOutcome | None:
    """"If a land is tapped for mana, it produces {B} instead of any other
    type." (Infernal Darkness, Ritual of Subdual, Contamination, Naked
    Singularity, Reality Twist, Pulse of Llanowar; the records of Deep Water,
    Pale Moon, Chaos Moon, Harvest Mage, Hall of Gemstone and False Dawn.)

    CR 106.12b: a replacement effect that applies if a permanent "is tapped for
    mana" modifies the mana production event **while the mana ability is
    resolving**. So this is not a change to what the land is or to what it
    could produce — ``effective_produced_mana`` still says what the land makes
    — it is a change to the one event, which is why the tap seam asks here
    rather than reading a stamped answer off the permanent.

    The event is not consumed: mana is still produced and the land is still
    tapped for mana, so every trigger that watches for that still fires
    (CR 106.12a). What changes is ``payload["substitutions"]`` — each applied
    effect appended in the order CR 616.1 applies them, which the seam carries
    out on what its own production put in the pool once that has run
    (``land_mana_swaps.substitute_production``, one effect after another).
    That is what makes "instead of any **other** type" mean what it says
    whether the land ran a compiled mana ability or fell through to its
    printed summary — and what makes two of them come out as the one applied
    last, which CR 616.1f says they do.

    One registration standing for every effect that prints this sentence
    (``instances``): a battlefield static and a per-seat record are both
    substitutions in ``engine/land_mana_swaps.py``, so the payment planner can
    ask what a land will make without applying a replacement to find out.
    (Quarum Trench Gnomes' per-permanent record is read inside
    ``effective_produced_mana`` instead, ahead of every one of these.)
    *instance* is the one this round applies; None (asked with no event in
    hand) applies them all.
    """
    applied = [
        substitution for substitution in _land_mana_substitutions(game, payload)
        if instance is None or substitution.key == instance
    ]
    if not applied:
        return None
    payload.setdefault("substitutions", []).extend(applied)
    return ReplacementOutcome()
