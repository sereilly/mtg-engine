"""Permission to cast or play cards from somewhere other than the hand.

CR 601.3: a player can begin to cast a spell only if a rule or effect allows
it. The rule that allows the ordinary case is CR 601.3's reading of the hand;
everything else — "you may play cards exiled this way", "you may cast target
red instant or sorcery card from your graveyard", "you may cast spells from
your hand without paying their mana costs" — is an *effect*, and this module
is where such effects live. One :class:`CastPermission` per effect, on
``Game.cast_permissions``; the cast path asks :func:`permission_for` before it
will look outside the hand, and :func:`consume` retires a one-card grant as it
is used.

Two duration models, both CR 611.2a:

* a stated duration ("until end of turn", "this turn") ends at cleanup —
  :func:`expire_end_of_turn` is called from the cleanup step (CR 514.2);
* no stated duration lasts until end of game, bounded in practice by the card
  staying the object it was (CR 400.7): a grant names its cards by identity,
  and :func:`permission_for` only matches a card still in the granted zone, so
  the permission dies with the card's departure and never resurrects a
  look-alike that arrives later.

The ``free`` flag is CR 118.9's "without paying its mana cost": the cast path
skips the mana payment and, when the spell has {X} in its cost, the only legal
choice for X is 0 (CR 107.3b). ``exile_instead`` is the printed rider "If that
spell would be put into your graveyard, exile it instead" — stamped onto the
:class:`~engine.game_types.StackItem` at cast time so every place a spell's
card leaves the stack routes it without knowing which effect asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .search_filters import card_has_type

if TYPE_CHECKING:
    from .models import CardDefinition


# Zones a permission may open. "hand" appears because a cost waiver ("without
# paying their mana costs") is the same seam with the ordinary zone.
PERMISSION_ZONES = ("hand", "graveyard", "exile", "library")


@dataclass
class CastPermission:
    """One effect's grant. ``cards`` is the identity list of what it covers —
    None means every card the filter (if any) admits, which is how a blanket
    "spells from your hand" waiver is written."""

    player_index: int
    zone: str  # one of PERMISSION_ZONES
    # "play" covers lands and spells (CR 305.1 still charges the land drop);
    # "cast" covers spells alone — a land is never cast.
    mode: str = "cast"
    cards: list["CardDefinition"] | None = None
    # Restriction on what a card-less grant covers, tested by primary type:
    # ("instant", "sorcery") for a spells-only waiver, () for anything.
    card_types: tuple[str, ...] = ()
    free: bool = False
    exile_instead: bool = False
    # "end_of_turn" is swept at cleanup; "your_next_turn" as the granting seat's
    # next turn begins and "your_next_upkeep" one step later, at the start of
    # that seat's upkeep step; "until_source_grants_again" is retired
    # by the next grant from the same permanent; "while_exiled" is swept by
    # nothing, because ``_covers`` already re-checks that the named card is
    # still in the granted zone and that is exactly what the words say (Ice
    # Cauldron); None lasts until end of game
    # (CR 611.2a), bounded by the cards staying in the granted zone.
    duration: str | None = "end_of_turn"
    source_name: str = ""
    # Which permanent granted this, by id. "Until you exile another card with
    # **this** enchantment" (Furious Rise) is bounded by one permanent's own
    # later grant, so two Furious Rises are two independent permissions — the
    # name they share cannot say that, and a battlefield slot moves the moment
    # anything leaves (CR 400.7 gives a returning permanent a new id, which is
    # also correct here: the new object has granted nothing yet).
    source_permanent_id: int | None = None
    #: **Whose zone the cards are in**, when that is not the grantee's own.
    #: "Search target opponent's library for a card and exile it. … you may
    #: play that card." (Grinning Totem.) CR 400.3 sends the card to its
    #: *owner's* exile — the searched player's — while CR 601.3 gives the
    #: permission to the searcher, so the two seats come apart for the first
    #: time in this pool.
    #:
    #: Its own field rather than a wider ``player_index`` because they answer
    #: two different questions and collapsing them is wrong in both directions:
    #: read as the grantee, nothing would find the card, and read as the owner,
    #: the wrong player would be allowed to cast it. None means "the grantee's
    #: own", which is every other grant.
    zone_player_index: int | None = None
    #: **Where in the zone**, for a grant that names no cards. "…you may cast
    #: instant and sorcery spells from **the top of** your graveyard"
    #: (Bösium Strip) covers one card at a time, and which card it is changes
    #: as the pile does — so it cannot be resolved into ``cards`` at grant
    #: time the way every named grant is.
    #:
    #: None means the whole zone, which is what every other grant means.
    #: Leaving it off for a card that prints the phrase is not a smaller
    #: permission but a strictly larger one: the entire graveyard becomes
    #: castable.
    #:
    #: **It is also half of a compound duration**, and that is not a second
    #: meaning. "Until end of turn, **for as long as that card remains on top
    #: of your library**, … you may play that card without paying its mana
    #: cost." (Temporal Aperture.) CR 611.2a's moment is ``duration`` and the
    #: cleanup sweep ends it; CR 611.2b's state is this field, re-asked by
    #: :func:`_covers` on every read — which is what "remains on top" says, in
    #: exactly as many words. The two compose because nothing has to schedule
    #: the second, the same way ``while_exiled`` needs no sweep.
    position: str | None = None

    @property
    def zone_seat(self) -> int:
        """Which seat's copy of :attr:`zone` this grant reads."""
        return (
            self.player_index if self.zone_player_index is None
            else self.zone_player_index
        )


def grant_permission(game, **kwargs) -> CastPermission:
    permission = CastPermission(**kwargs)
    # "…until you exile another card with this enchantment." The ending event is
    # this same permanent granting again, so the retirement happens here rather
    # than in a turn step: there is no moment to sweep at, only this one. A
    # grant with no source id retires nothing, which is the safe direction — it
    # would otherwise clear every unsourced grant a player holds.
    if permission.duration == "until_source_grants_again" and permission.source_permanent_id is not None:
        # Slice assignment, not rebinding: ``expire_end_of_turn`` mutates the
        # same list in place and a caller may be holding it.
        game.cast_permissions[:] = [
            held for held in game.cast_permissions
            if not (
                held.duration == "until_source_grants_again"
                and held.source_permanent_id == permission.source_permanent_id
            )
        ]
    game.cast_permissions.append(permission)
    return permission


def _zone_cards(game, permission: CastPermission) -> list:
    player = game.players[permission.zone_seat]
    return getattr(player, permission.zone)


def _covers(game, permission: CastPermission, card, zone: str, *, as_land: bool) -> bool:
    if permission.zone != zone:
        return False
    if as_land and permission.mode != "play":
        return False
    # ``card_has_type``, not ``primary_type``: CR 205.2a gives a card **every**
    # type its line names, and ``primary_type`` picks one of them by the order
    # of a list — so an Artifact Creature card is not "an artifact" to a
    # permission naming one, and the pool holds 77 of them. Safe today only
    # because the one card that grants a typed permission names instant and
    # sorcery, which never co-occur with another type; the next one to name a
    # permanent type would have been silently narrowed. One reader for the
    # whole engine (``engine/search_filters.card_has_type``).
    if permission.card_types and not any(
        card_has_type(card, name) for name in permission.card_types
    ):
        return False
    if permission.position == "top":
        # CR 400.5 keeps a graveyard ordered, and this engine keeps the top as
        # the *end* of the list: every path that bins a card appends
        # (``handlers/zones.graveyard_top_to_library`` states the same
        # convention). A library is the other way round: its top is
        # ``library[0]``, which is what every draw, mill and reveal in this
        # engine reads — so which end "top" names is the *zone's* answer and
        # not this field's. Spelled as one expression rather than two rows, because the
        # field means one thing ("the pile's first card, from wherever that
        # pile is counted") and only the counting differs.
        #
        # Compared by identity, because a deck repeats one immutable
        # ``CardDefinition`` per copy and a value test would answer "yes" for a
        # second copy sitting anywhere in the pile.
        pile = _zone_cards(game, permission)
        if not pile:
            return False
        if (pile[0] if permission.zone == "library" else pile[-1]) is not card:
            return False
    if permission.cards is not None:
        # Identity, not name: the grant covers the copies it named, one use
        # each. The card must also still be in the granted zone — a card that
        # left is a new object (CR 400.7) and the permission does not follow it.
        if not any(entry is card for entry in permission.cards):
            return False
        if not any(entry is card for entry in _zone_cards(game, permission)):
            return False
    return True


#: "You may cast this card from your graveyard by paying 3 life and discarding a
#: card in addition to paying its other costs." (Demonic Embrace.)
#:
#: A permission the card grants **itself**, rather than one an effect handed it.
#: Every grant above is a `CastPermission` an effect put on `game.cast_permissions`
#: and something later takes away; this one is a static ability of the card
#: while it sits in the zone (CR 113.6f — an ability modifying what zones that
#: particular object may be cast from functions everywhere; the additional cost
#: riding it is CR 113.6d's half), so there is nothing to grant, nothing
#: to expire, and no state at all — it is derived from the text on demand, the
#: same shape `cast_restrictions.py` uses for a printed timing gate.
_SELF_PERMISSION = re.compile(
    r"^you may cast this card from your (?P<zone>graveyard|exile) by paying "
    r"(?P<costs>.+?) in addition to paying its other costs$"
)


def self_permission_zone(card) -> str | None:
    """The zone *card*'s own text lets it be cast from, or None.

    The additional costs are read by ``engine/cast_costs.py`` from the same
    line — two readers of one sentence, which is a thing this codebase refuses
    elsewhere and accepts here for a reason worth stating: they answer different
    questions of it. This one asks *whether the zone is open*, which the cast
    path needs before it will look outside the hand; that one asks *what must be
    paid*, which it needs after. Splitting the sentence differently would mean a
    permission with no costs attached or costs with no permission behind them,
    and the guard in ``tests/rules/test_cast_permissions.py`` holds the two to
    the same line.
    """
    for line in (getattr(card, "oracle_text", "") or "").splitlines():
        match = _SELF_PERMISSION.match(line.strip().lower().rstrip("."))
        if match is not None:
            return match.group("zone")
    return None


#: "Any player may cast creature spells with mana value 3 or less without
#: paying their mana costs and as though they had flash." (Aluren.)
#:
#: **Three permissions in one sentence**, and each is a different rule: *who*
#: may cast (any player, CR 601.3a — including on somebody else's turn), *for
#: what* (CR 118.9's cost waiver) and *when* (CR 113.6b's flash timing). All
#: three are read from this one pattern, and the line is claimed only because
#: all three are carried out — a claim for the first two would ship an
#: enchantment that gives its cheap creatures away for free and cannot flash
#: them in, which is not the card.
#:
#: Derived from the board rather than granted, exactly as
#: :func:`self_permission_zone` below and ``library_top.top_castable`` are:
#: there is nothing to expire, because the permission ends with the permanent
#: (CR 611.3a).
#:
#: The card type and the mana value are payload for this file's own reason: a
#: card printing "artifact spells with mana value 2 or less" is the same
#: sentence and must need no second row.
_BOARD_FREE_CAST = re.compile(
    r"^any player may cast (?P<type>artifact|creature|enchantment|instant"
    r"|sorcery|planeswalker|battle) spells with mana value (?P<mana_value>\d+) "
    r"or less without paying their mana costs and as though they had flash$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for ``cast_restrictions.GLOBAL_PLAY_TIMING_CLAIM``'s
#: reason: it says what this *permanent* does for everybody, not when the card
#: printing it may be cast.
BOARD_FREE_CAST_CLAIM = "board_free_cast"


def board_free_cast_line(line: str) -> dict | None:
    """``{"card_type": …, "mana_value": …}`` for *line*, or None.

    One reader, four callers — the parse claim, the support gate,
    :func:`permission_for` (the cost waiver and the zone) and
    ``cast_timing.casts_at_instant_speed`` (the timing). A second copy of the
    phrase in the timing module would be free to drift from this one, and the
    direction it drifts is a permission granted with half the sentence behind
    it.
    """
    match = _BOARD_FREE_CAST.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    return {
        "card_type": match.group("type"),
        "mana_value": int(match.group("mana_value")),
    }


def board_free_cast(game, card) -> str | None:
    """The name of a permanent on any battlefield making *card* free, or None.

    Every battlefield and no seat comparison: "**any** player" names nobody, so
    the permission is everyone's — which is the whole of what makes Aluren the
    card it is, and the half a controller check would have silently dropped.

    ``effective_card`` rather than the printed face, for
    ``cast_restrictions.global_cast_ban``'s reason: what a permanent says is
    what layers 1 and 3 have made of it (CR 707.2, CR 612.1).

    ``card_has_type``, not ``primary_type``: CR 205.2a gives a card every type
    its line names, so an artifact creature is a creature spell. The mana value
    is the card's own printed one (CR 202.3) — a cost tax changes what is paid
    and not what the card's mana value is, and this sentence asks the latter.
    """
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            described = board_free_cast_line(raw_line)
            if described is None:
                continue
            if not card_has_type(card, described["card_type"]):
                continue
            if float(getattr(card, "cmc", 0) or 0) <= described["mana_value"]:
                return permanent.card.name
    return None


#: "You may play lands and cast spells from your graveyard." (Yawgmoth's
#: Agenda.) Yawgmoth's Will's sentence with no window on it: the Will is a
#: sorcery and *grants* the permission until end of turn, where the Agenda is
#: an enchantment and has it for as long as it is on the battlefield — a static
#: ability of a permanent (CR 604.1), so it is derived from the board on demand
#: for Aluren's reason above. A stored grant would have to be taken away when
#: the enchantment leaves, and one nobody took away is a graveyard that stays
#: open for the rest of the game.
#:
#: Read whole. Both verbs are the permission (CR 305.1 plays a land, CR 601.2
#: casts a spell) and "your graveyard" is its only zone; a narrower printing —
#: a card type, "the top of" — is a different sentence and must not match.
_BOARD_GRAVEYARD_PLAY = re.compile(
    r"^you may play lands and cast spells from your graveyard$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`BOARD_FREE_CAST_CLAIM`'s reason.
BOARD_GRAVEYARD_PLAY_CLAIM = "board_graveyard_play"


def board_graveyard_play_line(line: str) -> bool:
    """Whether *line* is the static graveyard permission above.

    One reader, four callers — the parse claim, the support gate, the coverage
    channel and :func:`board_graveyard_play`, which is the enforcement. A claim
    with no enforcement behind it is an Agenda that reports supported while
    being a pure drawback: a one-spell cap and an exile, with nothing bought.
    """
    return _BOARD_GRAVEYARD_PLAY.match(line.strip().lower().rstrip(".")) is not None


def board_graveyard_play(game, player_index: int) -> str | None:
    """The name of a permanent *player_index* controls that opens their own
    graveyard to them, or None.

    The controller's battlefield only: "**you** may", CR 109.5's controller.
    Through the control seam and ``effective_card``, so an Agenda that changes
    hands opens its new controller's graveyard and closes the old one's, and a
    copy of it grants what it copies (CR 707.2).
    """
    if not 0 <= player_index < len(game.players):
        return None
    for permanent in game.controlled_by(game.players[player_index]):
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if board_graveyard_play_line(raw_line):
                return permanent.card.name
    return None


def permission_for(
    game, player_index: int, card, zone: str, *, as_land: bool = False
) -> CastPermission | None:
    """The first live grant letting *player_index* cast/play *card* from
    *zone*, or None. ``zone == "hand"`` answers only cost-waiver grants — the
    ordinary permission to cast from hand is a rule, not an effect, and the
    caller must not gate it on this seam."""
    for permission in game.cast_permissions:
        if permission.player_index != player_index:
            continue
        if _covers(game, permission, card, zone, as_land=as_land):
            return permission
    # "You may cast Goblin spells from the top of your library." (Conspicuous
    # Snoop.) A static permission of a *permanent*, read off its text for as
    # long as it is in play — so it is derived rather than stored, exactly as
    # the card's own permission below is, and for the same reason: a stored
    # grant would have to be taken away when the Snoop leaves.
    if zone == "library":
        from .library_top import top_castable

        if top_castable(game, player_index, card):
            return CastPermission(
                player_index=player_index, zone="library", mode="play",
                cards=[card], duration=None, source_name="top of library",
            )
        return None
    # "Any player may cast creature spells with mana value 3 or less without
    # paying their mana costs …" (Aluren.) A *board* permission rather than one
    # this seat was granted, so it is derived on demand for the reason the
    # Snoop's is: a stored grant would have to be taken away when the
    # enchantment leaves. The hand is the zone it opens — the ordinary
    # permission to cast from hand is a rule, and what this adds is the waiver.
    if zone == "hand" and not as_land:
        source = board_free_cast(game, card)
        if source is not None:
            return CastPermission(
                player_index=player_index, zone="hand", mode="cast",
                cards=[card], free=True, duration=None, source_name=source,
            )
    # "You may play lands and cast spells from your graveyard." (Yawgmoth's
    # Agenda.) The board permission one zone over, derived for the same
    # reason. "Play", so a land is covered (CR 305.1 still charges the land
    # drop); the seat's **own** pile and by identity, which is what "your
    # graveyard" says and what a stored grant's ``cards`` list would carry.
    if zone == "graveyard" and any(
        entry is card for entry in game.players[player_index].graveyard
    ):
        source = board_graveyard_play(game, player_index)
        if source is not None:
            return CastPermission(
                player_index=player_index, zone="graveyard", mode="play",
                cards=[card], duration=None, source_name=source,
            )
    # The card's own static permission, asked last: a granted one may waive a
    # cost or open a wider zone, and answering with this first would hide it.
    # Only for a card actually in that zone and actually this player's, which is
    # what a stored grant carries and this has to check for itself.
    if (
        zone != "hand"
        and not as_land
        and self_permission_zone(card) == zone
        and any(entry is card for entry in getattr(game.players[player_index], zone))
    ):
        return CastPermission(
            player_index=player_index, zone=zone, mode="cast", cards=[card],
            duration=None, source_name=getattr(card, "name", ""),
        )
    return None


def consume(game, permission: CastPermission, card) -> None:
    """Retire one use of *permission* for *card*: a grant naming cards loses
    one occurrence and disappears when empty; a blanket grant is unlimited."""
    if permission.cards is None:
        return
    for i, entry in enumerate(permission.cards):
        if entry is card:
            del permission.cards[i]
            break
    if not permission.cards and permission in game.cast_permissions:
        game.cast_permissions.remove(permission)


def expire_end_of_turn(game) -> None:
    """CR 514.2: "until end of turn" and "this turn" grants end at cleanup."""
    game.cast_permissions[:] = [
        permission
        for permission in game.cast_permissions
        if permission.duration != "end_of_turn"
    ]


def expire_at_turn_start(game, player_index: int) -> None:
    """"**Until your next turn**, you may play those cards." (Three Wishes.)

    CR 800.4m states the duration this ends on: an effect lasting "until that
    player's next turn" lasts until that turn *would have begun*. So the sweep
    rides the turn boundary (``Game.begin_turn_bookkeeping``, which both the
    headless flow and the web layer's step-by-step flow run) rather than the
    untap step — a seat whose untap step is skipped still begins a turn, and the
    permission has to end there.

    Its own duration rather than a spelling of ``your_next_upkeep``, which is one
    step later. The two are indistinguishable to a *player* (CR 502.4 gives
    nobody priority in the untap step, so nothing can be played between them),
    and they are not indistinguishable to the engine: ``playable_from_zones``
    answers for whatever moment it is asked about, and a permission the card
    ended is one this seam must not still be offering.
    """
    game.cast_permissions[:] = [
        permission
        for permission in game.cast_permissions
        if not (
            permission.duration == "your_next_turn"
            and permission.player_index == player_index
        )
    ]


def expire_at_upkeep(game, player_index: int) -> None:
    """"Until the beginning of your next upkeep, you may play that card."
    (Elkin Bottle.)

    Swept as that upkeep step *begins*, alongside the layer-6 grants carrying
    the same printed duration, and before this turn's upkeep triggers run — one
    of which may grant a fresh permission. Whose upkeep is the grant's own
    ``player_index``, because CR 109.5 makes "your" the controller of the
    ability that granted it.

    A permission granted *during* an upkeep survives it by construction: the
    sweep has already run by the time anything can be activated in that step,
    so the next one it meets is the next upkeep, which is what "next" says.
    """
    game.cast_permissions[:] = [
        permission
        for permission in game.cast_permissions
        if not (
            permission.duration == "your_next_upkeep"
            and permission.player_index == player_index
        )
    ]


def playable_from_zones(game, player_index: int) -> list[dict]:
    """What the seat may currently cast or play from a non-hand zone, one
    entry per (zone, index) so the web layer can badge and offer those cards.
    A hand-zone waiver is deliberately absent: those cards are already offered
    by the ordinary hand UI, which asks :func:`permission_for` about cost."""
    entries: list[dict] = []
    # Every seat's graveyard and exile, not only this one's. A grant names the
    # zone it opens *and* whose copy of it (``zone_player_index``): Grinning
    # Totem's exiled card sits in the searched player's exile because CR 400.3
    # puts it there, and the permission to play it belongs to the searcher. The
    # seat's own zones come first so the entries a client already knew are in
    # the order it already saw them.
    seats = [player_index] + [
        seat for seat in range(len(game.players)) if seat != player_index
    ]
    # The library joins them at Urza's Saga, and only ever at index 0: CR 601.3
    # permissions over a library are all about its *top* card (Conspicuous
    # Snoop's Goblins, Radha's lands, Temporal Aperture's revealed card), and
    # offering the rest would be listing a hidden zone to its owner. It was
    # absent entirely, which is why ``permission_for``'s library branch — live
    # since M21 — had no consumer at all and no card was ever offered from
    # there.
    for zone in ("graveyard", "exile", "library"):
        for owner_seat in seats:
            pile = getattr(game.players[owner_seat], zone)
            if zone == "library":
                # Its own seat's top card and nobody else's: a library is a
                # hidden zone (CR 400.2), so an entry for another player's
                # would name a card the viewer may not see even when no
                # permission covers it.
                pile = pile[:1] if owner_seat == player_index else []
            for index, card in enumerate(pile):
                as_land = card.primary_type == "land"
                permission = permission_for(
                    game, player_index, card, zone, as_land=as_land
                )
                if permission is None:
                    continue
                if permission.zone_seat != owner_seat:
                    # The same card object can sit in two seats' zones (a deck
                    # repeats one immutable definition per copy), so the grant
                    # has to agree about *which* pile before this entry names an
                    # index into one.
                    continue
                entries.append({
                    "zone": zone,
                    "index": index,
                    "name": card.name,
                    "free": permission.free,
                    "source": permission.source_name,
                    # Whose pile the index is into. The viewer's own on every
                    # grant but the cross-seat one, so a client reading only
                    # `zone`/`index` keeps working.
                    "owner_seat": owner_seat,
                })
    # CR 903.8's command zone. The question this function answers is "what may
    # this seat play from a non-hand zone right now", and a commander is one of
    # those — but by a *rule* rather than by a CastPermission, so it is asked of
    # engine/commander.py instead of of the permission seam. Listing it here is
    # what lets the browser offer it through the one zone-cast path.
    for index, card in enumerate(game.players[player_index].command_zone):
        if not game.may_cast_from_command_zone(player_index, card):
            continue
        entries.append({
            "zone": "command",
            "index": index,
            "name": card.name,
            "free": False,
            "source": "commander",
            # The command zone is the seat's own by construction — CR 903.8 lets
            # a player cast a commander **they own** — so the key every other
            # entry carries is stated here rather than left absent.
            "owner_seat": player_index,
            # CR 903.8, so the client can show what the cast will actually cost.
            "commander_tax": game.commander_tax(player_index, card),
        })
    return entries
