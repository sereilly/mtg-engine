"""**Permission** sentences (CR 601.3): "you may cast", "you may play", "you may
look at".

The handler twin of ``engine/grammar/lowering/permissions.py``, and its line:
nothing here moves an object. :func:`grant_cast_permission` records a
cast-or-play permission over cards in a named zone
(``engine/cast_permissions.py`` holds the state, the cast path asks it, cleanup
expires the turn-scoped grants). The other two make a hidden card visible: a
face-down exiled card to the player who may look at it (Gustha's Scepter), and a
library's top card to everyone (Temporal Aperture). Illusionary Mask's "you may
cast that card face down" arms the choice of the card here
(``cast_face_down_creature``, from ``board_misc.py`` at the split round below);
the cast itself is the face-down cast path's.

Split out of ``zones.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exiled_records import records_for_cards
from ..linked_exile import linked_entries
from ..search_filters import card_has_type
from ._targets import frozen_that_player_seat
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("grant_look_at_exiled_cards")
def grant_look_at_exiled_cards(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may look at it for as long as it remains exiled." (Gustha's
    Scepter, the sentence after its face-down exile.)

    A card in exile face down is hidden from **every** player, its owner
    included (CR 406.3) — Knowledge Vault says nothing about looking and its
    controller cannot read its own pile. So this sentence is an effect, and
    what it changes is one seat's view of one entry.

    Written onto the linked-exile entry rather than onto the card, for
    ``link_exiled_card``'s standing reason: two copies of one card in a deck
    are the same ``CardDefinition`` object, so the record of the exiling is the
    only thing that can say which one this permission covers. The entries are
    matched by **identity** against what this resolution exiled, newest first,
    one entry per card — a value comparison would mark a different printing of
    the same card that some earlier activation put there.

    The duration needs no sweep: the permission lives on the entry, and the
    entry is drained the moment the card leaves exile.

    **A spell grants the same permission over the same cards and has no
    permanent**, so its record is the game's exile register instead (Three
    Wishes; see ``exile_top_of_library``). Both are written here rather than by
    two instructions, because the sentence is one sentence — a second kind would
    be a look permission whose reading depended on what exiled the card.
    """
    source = context.source_permanent
    exiled = list(context.results.get(instruction.payload.get("cards_from") or "exiled_cards") or ())
    if not exiled:
        # Nothing was exiled (the pick found no eligible card), so there is
        # nothing to grant — not a failure; the sentence before this one already
        # logged why.
        return True, "resolved"
    seat = game.players.index(context.caster)
    if source is None:
        granted = []
        for record in records_for_cards(game, exiled):
            if record.looker_index is None:
                record.looker_index = seat
                granted.append(record.card.name)
        if granted:
            game.log.append(
                f"{game.players[seat].name} may look at {', '.join(granted)} "
                "for as long as it remains exiled"
            )
        return True, "resolved"
    remaining = list(exiled)
    granted: list[str] = []
    for entry in reversed(linked_entries(source)):
        if not remaining:
            break
        if entry.get("looker_index") is not None:
            continue
        for position, card in enumerate(remaining):
            if entry["card"] is card:
                entry["looker_index"] = seat
                granted.append(card.name)
                del remaining[position]
                break
    if granted:
        game.log.append(
            f"{game.players[seat].name} may look at {', '.join(granted)} "
            "for as long as it remains exiled"
        )
    return True, "resolved"


#: How each permission duration reads in the log, so the line says what the
#: card said rather than what the first card to print the sentence happened to
#: say. Absent means an unbounded grant, which reads as nothing at all.
_PERMISSION_DURATION_WORDS = {
    "end_of_turn": " this turn",
    "your_next_turn": " until their next turn",
    "your_next_upkeep": " until their next upkeep",
    "until_source_grants_again": " until it exiles another card",
    "while_exiled": " for as long as it remains exiled",
}


@effect_handler("grant_top_of_library_revealed")
def grant_top_of_library_revealed(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, for as long as that card remains on top of your
    library, **play with the top card of your library revealed**." (Temporal
    Aperture.)

    CR 400.2: the top card becomes a public object. ``engine/library_top.py``
    holds the record and answers the question for every reader — the web
    payload's ``library_top`` face among them — so this handler does nothing
    but arm it.

    A grant per resolution rather than one the card keeps: activating the
    artifact twice in a turn reveals whichever card the *second* shuffle turned
    up, and the first record simply stops holding the moment its own card is no
    longer first (CR 611.2b). Nothing has to retire it, which is the whole
    reason the state half of the duration needs no sweep.
    """
    from ..library_top import END_OF_TURN, TopRevealGrant, add_reveal_grant

    payload = instruction.payload
    source_name = context.card.name if context.card is not None else ""
    revealed = context.results.get(str(payload.get("cards_from") or ""))
    if revealed is None:
        # The reveal in front of this step found an empty library, so there is
        # no card the "for as long as" clause could be about — and a grant with
        # nothing to be about is one that could never end (CR 611.2b's "if the
        # duration never starts, the effect does nothing").
        game.log.append(f"{source_name}: nothing was revealed, so nothing is shown")
        return True, "resolved"
    lifetime = str(payload.get("duration") or "")
    if lifetime != END_OF_TURN:
        # The lowering admits only "until end of turn", and this is the reason
        # rather than a second copy of that rule: END_OF_TURN is the one
        # lifetime the cleanup sweep clears, so a record arriving with any other
        # would be a reveal nothing ever ends. Refused out loud here rather than
        # stored and forgotten.
        game.log.append(
            f"{source_name}: no sweep ends a top-of-library reveal that lasts "
            f"{lifetime or 'indefinitely'}"
        )
        return True, "resolved"
    add_reveal_grant(
        context.caster,
        TopRevealGrant(card=revealed, lifetime=lifetime, source_name=source_name),
    )
    game.log.append(
        f"{context.caster.name} plays with the top card of their library "
        f"revealed for as long as {revealed.name} remains on top"
    )
    return True, "resolved"


@effect_handler("grant_cast_permission")
def grant_cast_permission(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A cast-or-play permission (CR 601.3) over cards in a named zone —
    engine/cast_permissions.py holds the state, the cast path asks it, and
    cleanup expires the turn-scoped grants. Three payload forms, matching the
    printed sentences the lowering admits.

    **Who is permitted is payload too.** "At the beginning of each player's
    upkeep, that player exiles a card at random from their hand. **The player**
    may play that card this turn." (Elkin Lair.) CR 601.3 grants the permission
    to the player the sentence names, and on this card that is a different seat
    every upkeep — never the ability's controller except on one turn in four.
    ``recipient`` carries it — the same key the mill, the discard and Thought
    Lash's library exile already spell "which seat is this instruction about" —
    read through the one reader of the printed phrase
    (``frozen_that_player_seat``), so the grant and the exile in front of it
    cannot land on two different players."""
    from ..cast_permissions import grant_permission

    caster = context.caster
    caster_index = game.players.index(caster)
    payload = instruction.payload
    duration = payload.get("duration")
    source_name = context.card.name if context.card is not None else ""
    if payload.get("recipient") == "event_subject_player":
        named = frozen_that_player_seat(game, context)
        if named is None:
            # A seat the trigger did not freeze is a permission handed to the
            # wrong player, which is worse than none at all: it would let the
            # ability's controller play a card out of somebody else's hand.
            game.log.append(
                f"{source_name}: no player was named to be given the permission"
            )
            return True, "resolved"
        grantee_index = named
    else:
        grantee_index = caster_index
    grantee = game.players[grantee_index]

    if payload.get("cards_from") == "exiled_cards":
        cards = list(context.results.get("exiled_cards") or [])
        if not cards:
            game.log.append(f"{source_name}: nothing was exiled, so there is nothing to permit")
            return True, "resolved"
        zone = payload.get("zone", "exile")
        # **Whose pile each card is in.** CR 400.3 sends an object to its
        # *owner's* zone, and a search of somebody else's library exiles a card
        # they own (Grinning Totem) — so the cards this permission names are not
        # always in the grantee's own exile, and a grant that assumed they were
        # would cover nothing at all. Read off the board rather than passed
        # down, because the step that exiled them is the only one that knew and
        # the answer is visible here.
        by_seat: dict[int | None, list] = {}
        for card in cards:
            seat = next(
                (
                    index for index, player in enumerate(game.players)
                    if any(held is card for held in getattr(player, zone, ()))
                ),
                grantee_index,
            )
            by_seat.setdefault(None if seat == grantee_index else seat, []).append(card)
        for zone_seat, held in by_seat.items():
            grant_permission(
                game, player_index=grantee_index, zone=zone,
                mode=payload.get("mode", "cast"), cards=held,
                # "…**without paying its mana cost** for as long as it remains
                # exiled." (Planeswalker's Mischief.) CR 118.9's waiver, on the
                # flag the two grants below already carry.
                free=bool(payload.get("free")),
                duration=duration, source_name=source_name,
                source_permanent_id=game.permanent_id_of(context.source_permanent),
                zone_player_index=zone_seat,
            )
        game.log.append(
            f"{grantee.name} may {payload.get('mode', 'cast')} "
            f"{', '.join(card.name for card in cards)} from exile"
            + _PERMISSION_DURATION_WORDS.get(duration, "")
        )
        return True, "resolved"

    if payload.get("cards_from") == "revealed_card":
        # "Shuffle your library, then reveal the top card. Until end of turn,
        # for as long as that card remains on top of your library, … you may
        # play that card without paying its mana cost." (Temporal Aperture.)
        #
        # The card is the one the reveal in front of this step recorded, not
        # whatever is on top now: nothing has moved, but reading the library
        # again would be a second answer to a question one step already
        # answered, and the two come apart the moment a card printing this
        # sentence draws first.
        #
        # ``position="top"`` is the *other half of the printed duration* rather
        # than a narrowing — see ``cast_permissions.CastPermission.position``.
        # It is what makes the grant end when the card stops being on top, and
        # dropping it would leave the card playable from anywhere in the
        # library for the rest of the turn.
        revealed = context.results.get("revealed_card")
        if revealed is None:
            game.log.append(
                f"{source_name}: nothing was revealed, so there is nothing to permit"
            )
            return True, "resolved"
        grant_permission(
            game, player_index=grantee_index, zone="library",
            mode=payload.get("mode", "play"), cards=[revealed],
            position=payload.get("position"), free=bool(payload.get("free")),
            duration=duration, source_name=source_name,
            source_permanent_id=game.permanent_id_of(context.source_permanent),
        )
        game.log.append(
            f"{grantee.name} may play {revealed.name} from the top of their "
            f"library"
            + _PERMISSION_DURATION_WORDS.get(duration, "")
            + " for as long as it remains on top"
        )
        return True, "resolved"

    if payload.get("cards_from") == "exiled_with_source":
        # "…from among cards exiled with this artifact" (Idol of Endurance).
        # The pile is the permanent's own linked exile, read live: a card that
        # has already been cast this turn has left the exile zone, and
        # ``_covers`` refuses it there rather than needing this list pruned.
        from ..subject_filters import card_matches_any

        source = context.source_permanent
        described = dict(payload.get("filter") or {})
        alternatives = (described,) if described else ()
        cards = [
            entry["card"] for entry in linked_entries(source)
            if int(entry.get("owner_index", -1)) == caster_index
            and card_matches_any(entry["card"], alternatives)
        ]
        if not cards:
            game.log.append(f"{source_name} has exiled nothing to cast")
            return True, "resolved"
        grant_permission(
            game, player_index=caster_index, zone="exile", mode="cast",
            cards=cards, free=bool(payload.get("free")),
            duration=duration, source_name=source_name,
            source_permanent_id=game.permanent_id_of(source),
        )
        game.log.append(
            f"{caster.name} may cast {', '.join(card.name for card in cards)} "
            f"from exile this turn"
        )
        return True, "resolved"

    if payload.get("target_graveyard_card"):
        # "target red instant or sorcery card from your graveyard" — always
        # the caster's own graveyard; the chosen index is honoured when it
        # names a legal card, else the first legal card stands in, the same
        # fallback every other stale-choice path takes.
        from ..object_colors import object_colors

        card_types = tuple(payload.get("card_types") or ())
        colors = tuple(payload.get("colors") or ())

        def _legal(card) -> bool:
            # ``card_has_type`` for ``cast_permissions._covers``' reason, and it
            # is the same question one step earlier: which card in the pile the
            # permission may name. The two disagreeing would offer a card the
            # permission then refuses.
            if card_types and not any(
                card_has_type(card, name) for name in card_types
            ):
                return False
            if colors and not any(
                color in object_colors(game, card, caster) for color in colors
            ):
                return False
            return True

        index = context.target_permanent_index
        chosen = None
        if isinstance(index, int) and 0 <= index < len(caster.graveyard):
            candidate = caster.graveyard[index]
            if _legal(candidate):
                chosen = candidate
        if chosen is None:
            chosen = next((card for card in caster.graveyard if _legal(card)), None)
        if chosen is None:
            game.log.append(f"{source_name}: no legal card in {caster.name}'s graveyard")
            return True, "resolved"
        spelling = payload.get("flashback")
        if spelling:
            # "Target sorcery card in your graveyard **gains flashback** until
            # end of turn. The flashback cost is equal to its mana cost."
            # (Recoup.) CR 702.34a's permission granted to one card: the same
            # grant as the one below with the alternative cost it *requires*
            # (CR 118.9b) and both exile riders — and scoped to "if the
            # resulting spell is an instant or sorcery spell", which is part
            # of the keyword rather than of this card's noun phrase.
            from ..flashback import granted_cost

            cost = granted_cost(chosen, str(spelling))
            if cost is None:
                # A price this cannot build is a grant at no stated price,
                # which would be a free cast. Refused out loud instead.
                game.log.append(
                    f"{source_name}: no flashback cost is spelled {spelling!r}"
                )
                return True, "resolved"
            grant_permission(
                game, player_index=caster_index, zone="graveyard", mode="cast",
                cards=[chosen], duration=duration, exile_instead=True,
                card_types=("instant", "sorcery"), cost=cost,
                source_name=source_name,
            )
            game.log.append(
                f"{chosen.name} gains flashback "
                f"{cost.mana or '(no mana cost)'} until end of turn"
            )
            return True, "resolved"
        grant_permission(
            game, player_index=caster_index, zone="graveyard", mode="cast",
            cards=[chosen], duration=duration,
            exile_instead=bool(payload.get("exile_instead")),
            source_name=source_name,
        )
        game.log.append(f"{caster.name} may cast {chosen.name} from their graveyard")
        return True, "resolved"

    if payload.get("blanket"):
        # "Until end of turn, you may cast instant and sorcery spells from the
        # top of your graveyard." (Bösium Strip.) No card is named, so
        # ``cards`` stays None and what the grant covers is re-asked of the
        # board on every read — which is what the printed sentence means: the
        # top of a graveyard is whatever is on top *now*, and a card resolved
        # at grant time would go on being castable after something else was
        # binned on top of it.
        grant_permission(
            game, player_index=caster_index, zone=payload.get("zone", "graveyard"),
            mode=payload.get("mode", "cast"), cards=None,
            card_types=tuple(payload.get("card_types") or ()),
            position=payload.get("position"),
            exile_instead=bool(payload.get("exile_instead")),
            duration=duration, source_name=source_name,
        )
        game.log.append(
            f"{caster.name} may cast "
            + " and ".join(payload.get("card_types") or ("any",))
            + " spells from the top of their graveyard this turn"
        )
        return True, "resolved"

    if payload.get("free"):
        grant_permission(
            game, player_index=caster_index, zone=payload.get("zone", "hand"),
            mode=payload.get("mode", "cast"), cards=None, free=True,
            duration=duration, source_name=source_name,
        )
        game.log.append(
            f"{caster.name} may cast spells from their hand without paying "
            "their mana costs this turn"
        )
        return True, "resolved"

    game.log.append(f"{source_name}: unrecognized cast permission payload")
    return True, "resolved"


@effect_handler("cast_face_down_creature")
def cast_face_down_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Illusionary Mask: arm a pending choice for the controller to pick a creature
    card in hand whose mana cost X could pay (cmc <= X), to cast face down as a 2/2.
    The actual cast happens in confirm_face_down_cast; the choice is optional."""
    caster = context.caster
    card = context.card
    controller_index = game.players.index(caster)
    max_cmc = max(0, int(context.x_value or 0))
    eligible = [c for c in caster.hand if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc]
    if not eligible:
        game.log.append(f"{card.name}: no eligible creature in hand to cast face-down (X={max_cmc})")
        return True, "resolved"
    game.arm_pending_choice(
        "face_down_cast", controller_index, max_cmc=max_cmc, card_name=card.name
    )
    game.log.append(f"{card.name}: choose a creature (mana value <= {max_cmc}) to cast face down")
    return True, "resolved"
