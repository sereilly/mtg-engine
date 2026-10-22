"""A card or a permanent put somewhere other than where it was going
(CR 614.1a, 614.6): dying, leaving the battlefield, being discarded, or going
to a graveyard from anywhere.

``would_die`` — exiled instead, returned to its owner's hand instead, put on
top of its owner's library instead; ``would_leave_battlefield`` — exiled
instead of going anywhere else; ``discard`` — onto the top of the library
(Library of Leng), onto the battlefield when an opponent caused it, into exile
for madness (the third discard destination, CR 702.35a); and
``put_into_graveyard`` — exiled instead, or shuffled into its owner's library.
A discard is an *interactive* kind, so Library of Leng's offers a choice and
finishes through its resolver; a replaced discard is still a discard for every
watcher.

Split out of ``replacements.py`` at the 2,000-line cap's split round. A
permanent *entering* the battlefield, and the other events of one already
there, are ``permanents.py``'s.
"""

from __future__ import annotations

import random
import re

from ..hand_locks import lock_card_in_hand
from ..models import Permanent
from ..replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from .registry import (DISCARD_DESTINATION, DISCARD_INTO_EXILE,
                       DISCARD_TO_BATTLEFIELD, EXILE_INSTEAD_OF_DYING,
                       EXILE_INSTEAD_OF_GRAVEYARD, EXILE_INSTEAD_OF_LEAVING,
                       LIBRARY_TOP_INSTEAD_OF_DYING,
                       RETURN_TO_HAND_INSTEAD_OF_DYING,
                       SHUFFLE_INSTEAD_OF_GRAVEYARD, ReplacementOutcome,
                       replacement_effect)


def _applies_exile_instead_of_dying(game, payload: dict) -> bool:
    return bool(payload["permanent"].metadata.get("exile_if_dies_this_turn"))


@replacement_effect(
    "would_die", EXILE_INSTEAD_OF_DYING, applies=_applies_exile_instead_of_dying
)
def _exile_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Disintegrate-style: "if it would die this turn, exile it instead." The
    permanent never reaches the graveyard, so no dies-triggers fire (CR 614)."""
    permanent = payload["permanent"]
    if not permanent.metadata.get("is_token", False):
        payload["player"].exile.append(permanent.card)
    game.log.append(f"{permanent.card.name} was exiled instead of dying")
    return ReplacementOutcome(replaced=True)


#: "If the creature would leave the battlefield, exile it instead of putting it
#: anywhere else." (Dreams of the Dead.) Armed on the **permanent** the
#: reanimation created, not keyed to its card: a `CardDefinition` is shared
#: between every copy of a card in a deck, so a record keyed to one would divert
#: another copy's bounce too.
#:
#: The same shape Disintegrate's `exile_if_dies_this_turn` above has — a marker
#: a handler stamps and a pure predicate reads — and the same reason it is a
#: marker rather than a text probe: what carries the effect is the permanent,
#: and its printed text says nothing about it.
EXILE_ON_LEAVING_BATTLEFIELD = "exile_if_it_would_leave_the_battlefield"


def _applies_exile_instead_of_leaving(game, payload: dict) -> bool:
    permanent = payload["permanent"]
    if permanent.metadata.get("is_token", False):
        # CR 111.7: a token that leaves the battlefield ceases to exist, and
        # there is no card for an exile to hold. Refused here rather than in the
        # body, so the effect is not counted in a CR 616.1 contention it could
        # not carry out.
        return False
    return bool(permanent.metadata.get(EXILE_ON_LEAVING_BATTLEFIELD))


@replacement_effect(
    "would_leave_battlefield", EXILE_INSTEAD_OF_LEAVING,
    applies=_applies_exile_instead_of_leaving,
)
def _exile_instead_of_leaving(game, payload: dict) -> ReplacementOutcome | None:
    """Dreams of the Dead: "If the creature would leave the battlefield, exile
    it instead of putting it anywhere else."

    The card never reaches the destination the effect was heading for, so no
    dies-trigger, no bounce and no tuck happens (CR 614.6). Exile is CR 400.3's
    owner's exile, which is not the controller's the moment the creature was
    stolen.
    """
    permanent = payload["permanent"]
    owner_index = game.owner_index_of(permanent)
    owner = game.players[
        owner_index if owner_index is not None else game.players.index(payload["player"])
    ]
    owner.exile.append(permanent.card)
    game.log.append(
        f"{permanent.card.name} was exiled instead of being put into "
        f"{payload.get('destination', 'another zone')}"
    )
    return ReplacementOutcome(replaced=True)


RETURN_TO_HAND_INSTEAD_TEXT = (
    "if this creature would die, return it to its owner's hand instead. until "
    "that player's next turn, that player plays with that card revealed in "
    "their hand and can't play it"
)


def _applies_return_to_hand_instead(game, payload: dict) -> bool:
    permanent = payload["permanent"]
    # A token returned to a hand ceases to exist (CR 111.7) rather than being
    # held there, so the sentence has nothing to do — and the rider that
    # follows it is about a card in a hand, which a token never becomes.
    if permanent.metadata.get("is_token", False):
        return False
    text = (permanent.effective_card.oracle_text or "").lower()
    return RETURN_TO_HAND_INSTEAD_TEXT in text


@replacement_effect(
    "would_die",
    RETURN_TO_HAND_INSTEAD_OF_DYING,
    applies=_applies_return_to_hand_instead,
)
def _return_to_hand_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Firestorm Phoenix: "If this creature would die, return it to its owner's
    hand instead. Until that player's next turn, that player plays with that
    card revealed in their hand and can't play it."

    The permanent never reaches the graveyard, so nothing that watches a death
    sees one (CR 614) — no dies-trigger, and the game-wide "creatures died this
    turn" record is untouched. It goes to its **owner's** hand, not its
    controller's (CR 400.3), which is the difference a stolen Phoenix makes.

    The second sentence is not decoration and is not a second effect: it is the
    same replacement's rider, so it is applied here, in the same breath as the
    return. ``engine/hand_locks.py`` holds it, and holds it only while the card
    actually arrived — a card diverted to the command zone (CR 903.9b) is in no
    hand to be revealed in.
    """
    permanent = payload["permanent"]
    owner_seat = game.owner_index_of(permanent)
    if owner_seat is None:
        owner_seat = game.players.index(payload["player"])
    owner = game.players[owner_seat]
    if game.put_card_into_hand(owner, permanent.card, from_battlefield=permanent):
        lock_card_in_hand(game, owner_seat, permanent.card, permanent.card.name)
        game.log.append(
            f"{permanent.card.name} returned to {owner.name}'s hand instead of dying, "
            f"revealed and unplayable until their next turn"
        )
    return ReplacementOutcome(replaced=True)


TOP_OF_LIBRARY_INSTEAD_OF_DYING = (
    "if this creature would die, put it on top of its owner's library instead"
)


def _applies_top_of_library_instead_of_dying(game, payload: dict) -> bool:
    """Whether this permanent prints Gravebane Zombie's sentence.

    Pure, as CR 616.1 requires, and the token exclusion is the same one
    ``_applies_return_to_hand_instead`` makes one screen up: a token put into a
    library ceases to exist (CR 111.7), so the sentence has nothing to do and
    the creature would vanish either way — the difference between the two
    outcomes is invisible, which is exactly when a replacement should decline
    rather than fire.
    """
    permanent = payload["permanent"]
    if permanent.metadata.get("is_token", False):
        return False
    text = (permanent.effective_card.oracle_text or "").lower()
    return TOP_OF_LIBRARY_INSTEAD_OF_DYING in text


@replacement_effect(
    "would_die",
    LIBRARY_TOP_INSTEAD_OF_DYING,
    applies=_applies_top_of_library_instead_of_dying,
)
def _top_of_library_instead_of_dying(game, payload: dict) -> ReplacementOutcome | None:
    """Gravebane Zombie: "If this creature would die, put it on top of its
    owner's library instead."

    Firestorm Phoenix's replacement one zone over, and the same three
    consequences: the permanent never reaches the graveyard, so nothing that
    watches a death sees one (CR 614) — no dies-trigger and no entry in the
    game's "creatures died this turn" tally — and the card goes to its
    **owner's** library rather than its controller's (CR 400.3), which is the
    difference a stolen Zombie makes.

    Through ``Game.put_card_into_library`` rather than onto the list, because
    CR 903.9b has no single fire site and a tuck is one of the places it fires;
    ``from_battlefield`` hands it the permanent so CR 614.6's leave-the-
    battlefield replacements get their look at the same move (Dreams of the
    Dead exiles the Zombie instead, and this interceptor must not then also
    have put it in a library).
    """
    permanent = payload["permanent"]
    owner_seat = game.owner_index_of(permanent)
    if owner_seat is None:
        owner_seat = game.players.index(payload["player"])
    owner = game.players[owner_seat]
    if game.put_card_into_library(
        owner, permanent.card, position="top", from_battlefield=permanent
    ):
        game.log.append(
            f"{permanent.card.name} went on top of {owner.name}'s library "
            f"instead of dying"
        )
    return ReplacementOutcome(replaced=True)


TOP_OF_LIBRARY_DISCARD_TEXT = (
    "if an effect causes you to discard a card, discard it, but you may put it "
    "on top of your library instead"
)


def _applies_leng_discard(game, payload: dict) -> bool:
    return game._player_controls_text(payload["player"], TOP_OF_LIBRARY_DISCARD_TEXT)


@replacement_effect("discard", DISCARD_DESTINATION, applies=_applies_leng_discard)
def _top_of_library_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Library of Leng: "If an effect causes you to discard a card, discard it,
    but you may put it on top of your library instead of into your graveyard."

    The discarded card is in no zone until the choice is answered — it has left
    the hand and its destination is still undecided (CR 701.9c)."""
    player = payload["player"]
    card = payload["card"]
    suspended, _ = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="leng_discard",
            player_index=game.players.index(player),
            options=("top of library", "graveyard"),
            default_option=0,
            data={"card": card},
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} discarded {card.name} — Library of Leng: "
            "choose graveyard or top of library"
        )
    return ReplacementOutcome(replaced=True)


@replacement_choice("leng_discard")
def _resolve_leng_discard(game, choice: ReplacementChoice, option_index: int) -> int:
    player = game.players[choice.player_index]
    card = choice.data["card"]
    if option_index == 0:
        game.put_card_into_library(player, card, "top")
        game.log.append(
            f"{player.name} put discarded {card.name} on top of their library (Library of Leng)"
        )
    else:
        # The Library applied and its "you may" was declined, so the event is
        # still a discard into the graveyard — and CR 616.1f re-asks every
        # replacement that has not yet applied to it. Madness has not
        # (CR 614.5 keeps the Library itself from applying again).
        from ..madness import exile_madness_card

        if exile_madness_card(game, player, card):
            return 0
        game.put_card_into_graveyard(player, card)
        game.log.append(f"{player.name} put discarded {card.name} into their graveyard")
    return 0


# ---------------------------------------------------------------------------
# A discard that lands on the battlefield (CR 614.1a, CR 701.9a)
# ---------------------------------------------------------------------------

#: "If a spell or ability an opponent controls causes you to discard this card,
#: put it onto the battlefield **with two +1/+1 counters on it** instead of
#: putting it into your graveyard." (Dodecapod.) The counters are optional in
#: the *template* — the sentence without them is a card Magic also prints
#: (Loxodon Smiter, Wilt-Leaf Liege, Obstinate Baloth) — and what they are is
#: read by the entry reader that already knows the phrase, so a number word or
#: a counter kind that reader refuses leaves the whole line unclaimed.
_DISCARD_TO_BATTLEFIELD_RE = re.compile(
    r"^if a spell or ability an opponent controls causes you to discard this "
    r"card, put it onto the battlefield(?: (?P<counters>with [a-z]+ "
    r"\S+ counters? on it))? instead of putting it into your graveyard$"
)


def discard_to_battlefield(line: str) -> dict | None:
    """``{"counters": {kind: count}}`` for the Dodecapod sentence, or None.

    Read by the interceptor below and by ``replacement_claims_line``, so what
    is implemented and what is claimed cannot drift.
    """
    match = _DISCARD_TO_BATTLEFIELD_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    counters: dict[str, int] = {}
    if match.group("counters"):
        from ..enter_effects import enters_with_pt_counters

        placement = enters_with_pt_counters(
            f"this creature enters {match.group('counters')}"
        )
        if placement is None:
            return None
        counters[placement[1]] = placement[0]
    return {"counters": counters}


def _discard_battlefield_entry(game, player, card, cause_seat) -> dict | None:
    """The Dodecapod reading of this discard, or None when it is an ordinary
    one — the applicability predicate, pure.

    Three questions, and each is half of the printed condition. **This card**:
    the sentence is the discarded card's own, functioning from the hand because
    that is the only zone its condition can be met in (the reason
    ``_announce_discard_triggers`` gives for Psychic Purge's trigger). **A
    spell or ability causes**: there is a causing seat at all — a cleanup-step
    discard and a cost the player paid have none. **An opponent controls**: and
    that seat is not the discarding player's own (CR 109.5).
    """
    if not isinstance(cause_seat, int) or card is None:
        return None
    seat = next(
        (i for i, seated in enumerate(game.players) if seated is player), None
    )
    if seat is None or cause_seat == seat:
        return None
    if getattr(card, "primary_type", None) in ("instant", "sorcery"):
        # CR 304.4 / 307.4: an instant or sorcery can't enter the battlefield,
        # so the event is not replaced and the card goes where a discard goes.
        return None
    for line in (getattr(card, "oracle_text", "") or "").splitlines():
        spec = discard_to_battlefield(line)
        if spec is not None:
            return spec
    return None


def discarded_onto_battlefield(game, player, card, cause_seat) -> bool:
    """Put *card* onto the battlefield instead of into *player*'s graveyard, if
    its own text says a discard caused by *cause_seat* does that. Returns
    whether it did; False means the caller's default move still has to happen.

    The whole effect in one place, because a card is discarded through two
    seams and both must agree: ``Game._discard_card`` reaches this through the
    ``discard`` event below, and the chosen-discard seam
    (``handlers/discards._resolve_one_discard``) calls it directly, since that one
    offers Library of Leng's destination itself and never raises the event.

    The card has **still been discarded** (the card's ruling of 2022-12-08):
    the caller announces the discard exactly as it would have, and a sentence
    reading "the discarded card" reads this one.

    The counters go on through the placement seams as the permanent arrives —
    the arrangement ``return_self_from_graveyard`` has for Sand Golem.
    """
    spec = _discard_battlefield_entry(game, player, card, cause_seat)
    if spec is None:
        return False
    seat = next(i for i, seated in enumerate(game.players) if seated is player)
    arrival = Permanent(card=card)
    game._put_permanent_onto_battlefield(seat, arrival, None, from_zone="hand")
    game.log.append(
        f"{player.name} discarded {card.name}, which was put onto the "
        "battlefield instead of into their graveyard"
    )
    if game.is_on_battlefield(arrival):
        for kind, count in spec["counters"].items():
            if kind == "+1/+1":
                game.place_plus1_counters(arrival, int(count))
            else:
                game.place_pt_counters(arrival, kind, int(count))
            game.log.append(f"{card.name} enters with {count} {kind} counter(s)")
    return True


def _applies_discard_to_battlefield(game, payload: dict) -> bool:
    return _discard_battlefield_entry(
        game, payload.get("player"), payload.get("card"),
        payload.get("cause_seat"),
    ) is not None


@replacement_effect(
    "discard", DISCARD_TO_BATTLEFIELD, applies=_applies_discard_to_battlefield
)
def _battlefield_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Dodecapod: "If a spell or ability an opponent controls causes you to
    discard this card, put it onto the battlefield with two +1/+1 counters on
    it instead of putting it into your graveyard."

    Ordered ahead of Library of Leng's offer, which is CR 616.1's default for
    a seat nobody asks: both replace where the card goes, and a creature on the
    battlefield is the choice that leaves nothing on the table."""
    discarded_onto_battlefield(
        game, payload["player"], payload["card"], payload.get("cause_seat")
    )
    return ReplacementOutcome(replaced=True)


def _applies_madness_discard(game, payload: dict) -> bool:
    """Whether the discarded card prints a madness cost this engine can
    charge — the card's own static ability, functioning from the hand
    (CR 702.35a). Pure: asked of the printed text, which is what a card in a
    hand is."""
    from ..madness import printed_madness_cost

    card = payload.get("card")
    return card is not None and printed_madness_cost(card) is not None


@replacement_effect("discard", DISCARD_INTO_EXILE, applies=_applies_madness_discard)
def _discarded_into_exile_for_madness(game, payload: dict) -> ReplacementOutcome | None:
    """Madness: "If a player would discard this card, that player discards
    it, but exiles it instead of putting it into their graveyard" — and the
    trigger that exile sets off (``engine/madness.py``). The discard itself
    stands: ``Game._discard_card`` announces it either way."""
    from ..madness import exile_madness_card

    exile_madness_card(game, payload["player"], payload["card"])
    return ReplacementOutcome(replaced=True)


#: "If a card would be put into **your** graveyard from anywhere, exile that
#: card instead." (Forbidden Crypt.) Whose graveyard is payload for the reason
#: every parameter in this file is: "an opponent\'s graveyard" (Leyline of the
#: Void) and "a graveyard" (Rest in Peace) are the same sentence with a
#: different seat in it, and the interceptor answers all three from one
#: comparison. "That card" and "it" are the same back-reference.
#:
#: **Planar Void was named here and is not one of them.** Its Oracle text is
#: "Whenever another card is put into a graveyard from anywhere, exile that
#: card" -- a *trigger*, so the card reaches the graveyard and is exiled off
#: the stack afterwards, where this pattern requires both "would" and
#: "instead". The card is implemented as the trigger it is
#: (``card_put_into_graveyard``, announced from
#: ``Game.put_card_into_graveyard``); the claim here never matched it and
#: nothing failed, which is how a comment comes to name a card it cannot read.
_GRAVEYARD_TO_EXILE = re.compile(
    r"^if a card would be put into (?P<whose>your|an opponent\'s|a) graveyard "
    r"from anywhere, exile (?:that card|it) instead$"
)


def graveyard_exile_scope(line: str) -> str | None:
    """Whose graveyards *line* empties into exile — "you", "opponent" or
    "any" — or None when it is not that line.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is exiled and what is claimed
    cannot drift — the arrangement ``source_damage_cap`` already has.
    """
    match = _GRAVEYARD_TO_EXILE.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    if match is None:
        return None
    whose = match.group("whose")
    return "you" if whose == "your" else ("opponent" if whose != "a" else "any")


def _graveyard_exile_source(game, payload: dict):
    """The permanent whose printed line would exile this card, or None.

    Pure, like every other applicability predicate here. The scan is over every
    battlefield rather than the affected player\'s own, because the scope word
    is what says whose graveyard is meant: "your" is read relative to the
    permanent\'s controller (CR 109.5), so an opponent\'s Forbidden Crypt does
    nothing to your graveyard and a Leyline of the Void does nothing to its
    own controller\'s.
    """
    player = payload.get("player")
    if player is None:
        return None
    seat = game.players.index(player)
    for permanent in game.all_permanents():
        controller = game.controller_index_of(permanent)
        if controller is None:
            continue
        for line in (permanent.effective_card.oracle_text or "").splitlines():
            scope = graveyard_exile_scope(line)
            if scope is None:
                continue
            if scope == "any":
                return permanent
            if (seat == controller) == (scope == "you"):
                return permanent
    return None


def _graveyard_exile_armed_by_effect(payload: dict) -> bool:
    """Whether an *effect* armed this seat's graveyard exile for the turn.

    "If a card would be put into your graveyard from anywhere **this turn**,
    exile that card instead." (Yawgmoth's Will.) The unbounded spelling above
    is a static ability and is read off a permanent's text; a sorcery is on no
    battlefield when the replacement is meant to apply, so the effect leaves the
    marker and this asks for it. Pure, like every applicability predicate here.
    """
    player = payload.get("player")
    return bool(
        getattr(player, "exile_cards_bound_for_graveyard_this_turn", False)
    )


def _applies_graveyard_exile(game, payload: dict) -> bool:
    return (
        _graveyard_exile_source(game, payload) is not None
        or _graveyard_exile_armed_by_effect(payload)
    )


@replacement_effect(
    "put_into_graveyard", EXILE_INSTEAD_OF_GRAVEYARD,
    applies=_applies_graveyard_exile,
)
def _exile_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Forbidden Crypt: "If a card would be put into your graveyard from
    anywhere, exile that card instead."

    "From anywhere" is the whole sentence, and the reason
    ``Game.put_card_into_graveyard`` had to exist before this could: a death, a
    discard, a mill, a sacrifice and a spell finishing on the stack are one
    event with twenty-six spellings, and an interceptor hung on any one of them
    would be a card that works on Mondays.

    The exile is the *owner\'s*, which is the seat whose graveyard the card was
    headed for — this engine keeps exile per player, and CR 400.3 already
    decided the seat one call up.
    """
    player = payload["player"]
    card = payload["card"]
    source = _graveyard_exile_source(game, payload)
    player.exile.append(card)
    game.log.append(
        f"{card.name} was exiled instead of going to {player.name}\'s graveyard"
        + (f" ({source.card.name})" if source is not None else "")
    )
    return ReplacementOutcome(replaced=True)


#: "If <this> would be put into a graveyard from anywhere, reveal <this> and
#: shuffle it into its owner's library instead." (Legacy Weapon; Darksteel
#: Colossus, Progenitus and Blightsteel Colossus print the sentence word for
#: word.) Matched by shape because the subject is the card's own name or a
#: "this <noun>", and held to **one** subject: the back-reference makes a line
#: naming two different things refuse.
_GRAVEYARD_TO_LIBRARY = re.compile(
    r"^if (?P<subject>.+?) would be put into a graveyard from anywhere, "
    r"reveal (?P=subject) and shuffle it into its owner's library instead$"
)


def graveyard_shuffle_subject(line: str) -> str | None:
    """The subject of a printed "…would be put into a graveyard from anywhere,
    reveal … and shuffle it into its owner's library instead", or None.

    One matcher, asked by the interceptor below and by
    :func:`replacement_claims_line`, so what is shuffled away and what is
    claimed cannot drift.
    """
    match = _GRAVEYARD_TO_LIBRARY.match(
        " ".join((line or "").strip().lower().rstrip(".").split())
    )
    return None if match is None else match.group("subject")


def _shuffles_itself_instead_of_graveyard(game, payload: dict) -> bool:
    """Whether the object on its way to a graveyard prints the sentence
    **about itself**.

    The object as it last existed where it was (CR 113.6: the ability modifies
    how *that particular object* changes zones, so it works from every zone it
    could leave). Off the battlefield that is the permanent's computed text —
    ``effective_card``, so a copy of Legacy Weapon has the sentence and one that
    has lost its abilities does not — and everywhere else the card's own face,
    which is all a card in a hand, a library or on the stack has (CR 613.1).

    "Itself" is the card's own name or a ``this <noun>``; a line naming some
    other object is a different effect and is left alone. Pure, like every
    applicability predicate here.
    """
    permanent = payload.get("permanent")
    described = (
        permanent.effective_card if permanent is not None else payload.get("card")
    )
    if described is None:
        return False
    own_name = (getattr(described, "name", "") or "").strip().lower()
    for line in (getattr(described, "oracle_text", "") or "").splitlines():
        subject = graveyard_shuffle_subject(line)
        if subject is not None and (
            subject == own_name or subject.startswith("this ")
        ):
            return True
    return False


@replacement_effect(
    "put_into_graveyard", SHUFFLE_INSTEAD_OF_GRAVEYARD,
    applies=_shuffles_itself_instead_of_graveyard,
)
def _shuffle_into_library_instead_of_graveyard(game, payload: dict) -> ReplacementOutcome | None:
    """Legacy Weapon: "If Legacy Weapon would be put into a graveyard from
    anywhere, reveal Legacy Weapon and shuffle it into its owner's library
    instead."

    On ``Game.put_card_into_graveyard`` — the one seam every road to a
    graveyard passes through — because "from anywhere" is the whole sentence: a
    destruction, a sacrifice, a discard, a mill and a countered spell are one
    event here, and Forbidden Crypt's interceptor beside this one says why an
    interceptor on any single road would be a card that works on Mondays.

    The card never reaches the graveyard (CR 614.6), so nothing that watches an
    arrival there sees one and — from the battlefield — nothing died. It goes
    to its **owner's** library (CR 400.3), which is the seat the seam was
    already handed, through ``put_card_into_library`` for CR 903.9b's reason;
    the leave-the-battlefield replacements had their look at this move one
    step up (``_permanent_to_graveyard``) and CR 614.5 gives them no second,
    so the permanent is not handed on again.

    The library is shuffled whether or not the card arrived (CR 701.24c).
    """
    player = payload["player"]
    card = payload["card"]
    game.record_reveal(game.players.index(player), [card.name])
    game.put_card_into_library(player, card)
    random.shuffle(player.library)
    game.log.append(
        f"{card.name} was revealed and shuffled into {player.name}'s library "
        "instead of going to a graveyard"
    )
    return ReplacementOutcome(replaced=True)
