"""A card the ability names by reference, put back onto the battlefield.

The handler half of ``engine/grammar/lowering/_bound_returns.py`` that lands on
the battlefield. The firing event recorded the card ("put **that card** onto
the battlefield under your control": Seraph, Krovikan Vampire, Scrounge's pick,
Abduction's "under its owner's control"), or it is the ability's own source
("return **this card** to the battlefield": Takklemaggot, Ivory Gargoyle,
Traveling Plague, Bogardan Phoenix, Anurid Brushhopper out of exile, Screams
from Within; and out of its graveyard or exile, Silversmote Ghoul, Sand Golem,
Shifty Doppelganger and the Scourge Dragon Auras, with Whiteout's "to your
hand" as the same handler's other destination).

The object was fixed before the sentence ran, so nothing is matched and
nothing is targeted: each handler finds where that object is *now*, by identity
in the zone it moves out of (CR 603.6, 400.7), and asks CR 400.4a and 614.17
(``permanent_cards.stays_out_of_battlefield``) — and for an Aura, CR 303.4g/i —
before the card leaves it. A card the ability **targets** or **describes** (a
target, a position, a sweep) is ``reanimation.py``'s, and so is the record
every reanimation writes (:data:`~engine.handlers.reanimation.REANIMATED_PERMANENTS`);
the twins of these returns that land in a hand are ``returns.py``'s.

Split out of ``reanimation.py`` at the pre-Fifth-Dawn split round.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..entry_awaiting import entry_happened
from ..models import Permanent
from ..permanent_cards import stays_out_of_battlefield
from .reanimation import REANIMATED_PERMANENTS
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


@effect_handler("reanimate_bound_card")
def reanimate_bound_card(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Put that card onto the battlefield under your control." (Seraph,
    Krovikan Vampire.)

    ``return_bound_card_to_owners_hand`` with a different destination, and the
    same three reasons for every line of it: the bound object is the card of the
    creature whose death fired the trigger, the fire site froze the card itself
    (CR 603.10) because by resolution nothing else could name it, and it is
    located by identity and removed with ``pop`` at the found index — a name
    match finds the wrong entry in a graveyard holding two copies.

    Under **your** control, which CR 400.3 lets an effect say; ownership does
    not move, so the card goes back to its owner's graveyard when it next dies.
    ``control="owner"`` is the other seat the phrase can name — "return that
    card to the battlefield **under its owner's control**" (Abduction), where
    the Aura took the creature while it lived and gives it back when it dies.
    Absent, the payload means CR 110.2a's default, which is this seat.

    "Sacrifice the creature when you lose control of this creature" is the same
    sentence's second half, and it is recorded here rather than lowered as a
    step of its own: the rider names a permanent that does not exist until this
    instruction makes one. ``engine/linked_sacrifice.py`` holds the record and
    the state-based sweep re-checks it.
    """
    from ..damage_deaths import creatures_it_damaged_that_died
    from ..linked_sacrifice import link_sacrifice_to_source
    from ..models import Permanent

    if instruction.payload.get("from_damage_deaths"):
        # Krovikan Vampire's "that card" is the one its own intervening-if
        # found. **Every** one of them, when the ledger holds several: the
        # trigger fires once per end step and its condition asks whether *a*
        # creature died, so with two deaths the sentence names two cards and
        # nothing in it says which one to prefer. Reanimating the first would be
        # a choice the card never offers anybody.
        cards = creatures_it_damaged_that_died(context.source_permanent)
    elif instruction.payload.get("card_from"):
        # Scrounge's "that card": the card an earlier step's pick recorded
        # (``oracle_types.CHOSEN_GRAVEYARD_CARD``), None when it found none.
        card = context.results.get(str(instruction.payload["card_from"]))
        cards = [card] if card is not None else []
    else:
        card = (context.trigger_context or {}).get("dead_card")
        cards = [card] if card is not None else []
    context.results["reanimated_bound_card"] = False
    # What this step put onto the battlefield, by id, for the sentence behind
    # it ("Attach this Equipment to **that creature**", Scythe of the
    # Wretched) — declared in ``lowering/_records._PRODUCES``. Written
    # unconditionally and filled as each card arrives, so a step that brought
    # nothing back leaves a record that says so.
    context.results[REANIMATED_PERMANENTS] = ()
    if not cards:
        game.log.append(
            f"{context.card.name}: no recorded card to put onto the battlefield"
        )
        return True, "resolved"
    controller_seat = game.players.index(context.caster)
    to_owner = instruction.payload.get("control") == "owner"
    # Every card the sentence names, in one event (CR 603.6a).
    with game.entering_together():
        for card in cards:
            for player in game.players:
                found = next(
                    (i for i, held in enumerate(player.graveyard) if held is card), None
                )
                if found is None:
                    continue
                owner_seat = game.players.index(player)
                # CR 404.1 put the card in its *owner's* graveyard, so the seat
                # holding it is the owner — which is what "under its owner's
                # control" names, found here rather than passed in because it is
                # the graveyard scan that discovers it.
                seat = owner_seat if to_owner else controller_seat
                # An animated land that died is a land card in the graveyard,
                # and a "can't" (Worms of the Earth, CR 614.17) leaves it there.
                if stays_out_of_battlefield(game, card, player, "graveyard", seat=seat):
                    break
                player.graveyard.pop(found)
                permanent = Permanent(card=card)
                # CR 400.3: "under your control" moves control, never ownership, so
                # the card goes to its **owner's** graveyard when it next leaves.
                # Recorded on the permanent for the reason Animate Dead's
                # reanimation records it: the base controller is the owner
                # everywhere else in this pool, and here the two differ by
                # construction.
                if owner_seat != seat:
                    permanent.metadata["owner_player_index"] = owner_seat

                # The entry's ``then`` (CR 614.12a: at the answer, when an "as it
                # enters" choice keeps it on its way).
                def arrived(permanent=permanent, seat=seat, card=card) -> None:
                    # Only for an entry that happened (a replacement wrote its own line).
                    if not entry_happened(permanent):
                        return
                    context.results["reanimated_bound_card"] = True
                    context.results[REANIMATED_PERMANENTS] = (
                        *context.results.get(REANIMATED_PERMANENTS, ()),
                        permanent.permanent_id,
                    )
                    if instruction.payload.get("sacrifice_when_control_lost"):
                        source = context.source_permanent
                        if source is not None:
                            link_sacrifice_to_source(permanent, source, seat)
                    game.log.append(
                        f"{card.name} entered the battlefield under "
                        f"{game.players[seat].name}'s control ({context.card.name})"
                    )

                game._put_permanent_onto_battlefield(seat, permanent, None, then=arrived)
                break
            else:
                # CR 603.6: the ability looks for the object in the zone it moves it
                # out of. Exiled in response, or already reanimated by an earlier
                # firing of this same ability.
                game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("return_source_card_to_battlefield")
def return_source_card_to_battlefield(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card to the battlefield under your control [attached to
    that creature] [as a non-Aura enchantment]." (Takklemaggot.)

    The ability's own source, printed with no source zone — the same reach
    ``return_source_card_to_owners_hand`` makes, and for its reason: by the time
    an Aura's death trigger resolves the CR 704.5m sweep has usually already put
    the card in a graveyard, but a caller that resolves the stack without an
    intervening priority pass finds it still on the battlefield, and a handler
    that looked in one zone would silently do nothing in the other.

    Every rider is payload, and each is recorded on the permanent as a *layer*
    contribution rather than applied: the lost subtype is layer 4
    (``type_changes.lose_types``), the lost and gained ability lines are layer 6
    (``keywords``), and both are read back by ``Permanent.effective_card`` and
    ``computed_types``. So the CR 704.5m sweep, the UI and the compiler all get
    one answer to "what is this permanent now?" — which is the whole reason the
    non-Aura half is not a flag the sweep checks for itself.
    """
    from ..aura_attachment import attach_aura, aura_attach_refusal
    from ..keywords import grant_ability_line, remove_ability_line
    from ..type_changes import lose_types

    card = context.card
    source = context.source_permanent
    seat = game.seat_index(context.caster)
    # "…under **its owner's** control." (Ivory Gargoyle.) CR 400.3's seat, which
    # is not the ability's controller for a creature that changed hands before
    # it died. Read off the *permanent* while there still is one and off the
    # graveyard that held the card once there is not — CR 404.3 puts a card in
    # its owner's graveyard, so the pile that had it names the owner. An absent
    # payload key is every card written before the phrase existed and keeps
    # meaning "you".
    owners_control = instruction.payload.get("control") == "owner"
    if instruction.payload.get("control") == "event_subject_controller":
        # "…**that creature's controller** returns this Aura … to the
        # battlefield." (Traveling Plague.) CR 110.2a: an object a player is
        # instructed to put onto the battlefield enters under that player's
        # control, and that is the seat the departing host's fire site froze — never re-derived,
        # because the host has no controller any more. With no seat recorded
        # nobody puts it anywhere.
        frozen = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(frozen, int) or not 0 <= frozen < len(game.players):
            game.log.append(f"{card.name}: no controller was recorded to return it")
            return True, "resolved"
        seat = frozen
    chosen_control = instruction.payload.get("control") == "chosen"
    if chosen_control:
        # "Choose target opponent. **That player** puts this card from its
        # owner's graveyard onto the battlefield under their control at the
        # beginning of the next end step." (Endless Whispers.) CR 110.2a's
        # player who puts it, which is the seat the creating ability chose —
        # frozen into the delayed ability with its scratchpad (CR 603.7c) and
        # read back under the one key a chosen seat is written to. Nobody
        # recorded, or a seat that has left the game (CR 800.4a: nothing comes
        # under the control of a player who left), and nobody puts it anywhere:
        # the ability's own controller is the one seat the card says it is not.
        chosen = context.results.get("chosen_player")
        if (
            not isinstance(chosen, int) or not 0 <= chosen < len(game.players)
            or game.players[chosen].lost
        ):
            game.log.append(f"{card.name}: no player was chosen to put it onto the battlefield")
            return True, "resolved"
        seat = chosen
    if owners_control and source is not None:
        from ..control import base_controller

        # CR 108.3's answer, which this engine reads off the seat the permanent
        # *entered* under — never off where it currently sits, which is the
        # thief's side and the whole reason the card names the owner.
        owner = base_controller(source)
        if isinstance(owner, int):
            seat = owner
    host_key = instruction.payload.get("attached_to")

    def stays_where_it_is(entering_seat, owner=None, zone: str = "") -> bool:
        """CR 303.4g, asked **before** the card moves: "If an Aura is entering
        the battlefield and there is no legal object or player for it to
        enchant, the Aura remains in its current zone." A host nobody could
        choose (Infectious Rage with no creature it can enchant — "You can't
        return this card to the battlefield onto something it can't enchant",
        2004-10-04), or one that stopped being legal while this resolution ran,
        leaves the card where it is. Moving it first and refusing the attach
        afterwards put it onto the battlefield attached to nothing for
        CR 704.5m to bin, which is a second zone change the rules never make.
        The card-shaped half of the one enchant predicate, under the seat it
        would enter under — what ``legal_host_for_source`` asked when the host
        was picked."""
        from ..aura_attachment import enchant_card_refusal

        # CR 400.4a and 614.17 first, asked of the card in *owner*'s *zone*
        # (``permanent_cards``): a card that can't enter stays there too.
        if owner is not None and stays_out_of_battlefield(
            game, card, owner, zone, seat=entering_seat,
        ):
            return True
        if not host_key:
            return False
        host = game.permanent_by_id(context.results.get(host_key))
        refusal = (
            "nothing was chosen for it to enchant" if host is None
            else enchant_card_refusal(game, card, entering_seat, host)
        )
        if refusal is None:
            return False
        game.log.append(
            f"{card.name} has nothing it could enchant and stays where it is "
            f"({refusal})"
        )
        return True

    # The seat whose graveyard held the card, when that is where it came from
    # (below); None for every other zone.
    pile_seat = None
    if instruction.payload.get("from") == "exile":
        # "Exile this creature. Return it to the battlefield under its owner's
        # control at the beginning of the next end step." (Anurid
        # Brushhopper.) The lowering names the zone because the step in front
        # of this one put the card there: CR 400.3 put it in its **owner's**
        # exile, which is the only pile asked, and by identity through the
        # departure seam (``take_card_from_exile``). A card that has left
        # exile since is a new object (CR 400.7) and nothing is returned.
        from ..control import base_controller

        owner_seat = base_controller(source) if source is not None else None
        if not isinstance(owner_seat, int):
            owner_seat = seat
        if stays_where_it_is(
            owner_seat if owners_control else seat,
            game.players[owner_seat], "exile",
        ):
            return True, "resolved"
        if not game.take_card_from_exile(owner_seat, card):
            game.log.append(f"{card.name} was no longer in exile")
            return True, "resolved"
        if owners_control:
            seat = owner_seat
    elif (
        instruction.payload.get("from") != "graveyard"
        and source is not None and game.is_on_battlefield(source)
    ):
        # The unzoned spelling ("return it to the battlefield") reaches the
        # card wherever the sweep left it; "…**from its owner's graveyard**"
        # names the one zone (``from: graveyard``), so a source still on the
        # battlefield is not what the sentence moves.
        if stays_where_it_is(seat):
            return True, "resolved"
        game.remove_from_battlefield(source)
    else:
        # "…from **your** graveyard" (Screams from Within): the controller's
        # pile alone (its 2004-12-01 ruling).
        piles = (
            [game.players[seat]] if instruction.payload.get("from_controller_graveyard")
            else game.players
        )
        found = next(
            (
                (player, index)
                for player in piles
                for index, held in enumerate(player.graveyard)
                if held is card
            ),
            None,
        )
        if found is None:
            # CR 603.6: the ability looks for the object in the zone it moves it
            # out of. Gone means the ability does nothing, rather than making a
            # second copy of the card.
            game.log.append(f"{card.name} was no longer in a graveyard")
            return True, "resolved"
        player, index = found
        if owners_control:
            seat = game.seat_index(player)
        # CR 404.1 put the card in its owner's graveyard, so the pile that held
        # it names the owner — kept for the permanent below.
        pile_seat = game.seat_index(player)
        if stays_where_it_is(seat, player, "graveyard"):
            return True, "resolved"
        player.graveyard.pop(index)

    payload = instruction.payload
    permanent = Permanent(card=card)
    for subtype in payload.get("losing_subtypes") or ():
        lose_types(permanent, subtypes=[str(subtype)], source=card.name)
    for line in payload.get("losing_abilities") or ():
        remove_ability_line(permanent, line)
    for line in payload.get("gaining_abilities") or ():
        grant_ability_line(permanent, line[:1].upper() + line[1:])
    # Whose upkeep the granted trigger watches and who it hits: the seat this
    # resolution asked to choose. Recorded on the permanent because the ability
    # it was granted is compiled from the *permanent's* text, with no memory of
    # the resolution that granted it — the same channel Storm World's chosen
    # player already uses.
    #
    # Not when the chosen seat is the one it enters *under* (Endless
    # Whispers): there it names the controller, which the battlefield already
    # says, and a stamp would hand the returned card a "chosen player" its own
    # text never asked for.
    chosen_seat = context.results.get("chosen_player")
    if isinstance(chosen_seat, int) and not chosen_control:
        permanent.metadata["chosen_player_index"] = chosen_seat
    # CR 400.3: "under <someone>'s control" moves control and never ownership,
    # so the card goes back to its **owner's** graveyard when it next leaves.
    # Recorded on the permanent for the reason ``reanimate_bound_card`` records
    # it: the base controller is the owner everywhere else in this pool, and
    # here the two differ by construction.
    if isinstance(pile_seat, int) and pile_seat != seat:
        permanent.metadata["owner_player_index"] = pile_seat

    # Once it is there — the entry's ``then``, run at the answer when an "as
    # it enters" choice keeps it on its way (CR 614.12a).
    def arrived() -> None:
        # Only for an entry that happened (a replacement wrote its own line).
        if not entry_happened(permanent):
            return
        # "…return it to the battlefield under your control **and put a death
        # counter on it**." (Bogardan Phoenix.) The permanent this step
        # created, recorded by id for the sentence behind it — CR 400.7 makes
        # it a *new object*, so "it" cannot mean the one that died, and every
        # other reader in the resolution is still holding the dead one. The
        # reanimation's own channel, because the question is the
        # reanimation's question asked of the ability's own source.
        context.results.setdefault(REANIMATED_PERMANENTS, []).append(
            permanent.permanent_id
        )
        game.log.append(
            f"{card.name} returned to the battlefield under {game.players[seat].name}'s control"
        )

        host_key = payload.get("attached_to")
        if host_key:
            host = game.permanent_by_id(context.results.get(host_key))
            # CR 303.4j asked one more time at the move itself, over the same
            # predicate the picker used: a host chosen legally may have
            # stopped being one while the rest of this resolution ran.
            refusal = aura_attach_refusal(game, permanent, host)
            if refusal is None:
                attach_aura(permanent, host)
                game.log.append(f"{card.name} attached to {host.card.name}")
            else:
                game.log.append(f"{card.name} could not attach: {refusal}")

    game._put_permanent_onto_battlefield(seat, permanent, None, then=arrived)
    return True, "resolved"


@effect_handler("return_self_from_graveyard")
def return_self_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card from your graveyard to the battlefield [tapped]."
    (Silversmote Ghoul; CR 113.6m.)

    The object is the ability's own source, so nothing is chosen and there is no
    target index to read. CR 108.4a decides whose graveyard is searched: a card
    in a graveyard has no controller, so the ability's "your" is its owner's seat
    — the seat the fire site enqueued it under.

    Located by **identity**, not by name and not by index. A graveyard is a list
    of ``CardDefinition`` and two copies of one card are the same immutable
    object, so a name match finds the wrong entry and a list-comprehension
    rebuild removes *both* — which is exactly what the Nether Shadow scan in
    ``phases/upkeep_step.py`` does today. ``pop`` at an identity-found index
    removes one.
    """
    caster = context.caster
    card = context.card
    # "{3}{U}, **Exile this creature**: … return this card to the battlefield."
    # (Shifty Doppelganger.) The zone is payload: the ability's own cost put
    # the source in exile, so that is the pile it comes back out of. Absent
    # means the graveyard, which is what every other card printing the
    # sentence means. Never both — a card that is not where its ability left
    # it is a new object (CR 400.7) and is not looked for anywhere else.
    zone = "exile" if instruction.payload.get("from") == "exile" else "graveyard"
    pile = caster.exile if zone == "exile" else caster.graveyard
    found = next(
        (index for index, held in enumerate(pile) if held is card), None
    )
    if found is None:
        # CR 603.6: the ability looks for the object in the zone it moves it out
        # of. Gone (exiled in response, shuffled away) means the ability does
        # nothing, rather than conjuring a second copy of the card.
        game.log.append(
            f"{card.name} was no longer in "
            + ("exile" if zone == "exile" else "the graveyard")
        )
        return True, "resolved"
    # "…to the battlefield **attached to that creature**." (The Scourge Dragon
    # Auras.) The host is the object the firing event was about, frozen by id
    # at the entry seam — never re-found on the board, because a creature that
    # left and came back is a new object (CR 400.7). Asked **before** the card
    # moves: CR 303.4i says an Aura an effect would put onto the battlefield
    # attached to something it can't legally enchant, or to something
    # undefined, "remains in its current zone". The question is the one every
    # host chooser asks (``enchant_card_refusal``: the enchant ability, "can't
    # be enchanted", protection), under the seat it would enter under; it is
    # not a target (CR 115.1), so shroud is no bar.
    host = None
    if instruction.payload.get("attached_to") == "event_subject":
        from ..aura_attachment import enchant_card_refusal

        host = game.permanent_by_id(
            (context.trigger_context or {}).get("event_subject_permanent_id")
        )
        refusal = (
            "that creature has left the battlefield"
            if host is None or not game.is_on_battlefield(host)
            else enchant_card_refusal(game, card, game.seat_index(caster), host)
        )
        if refusal is not None:
            game.log.append(
                f"{card.name} cannot be attached and stays in the {zone} "
                f"({refusal})"
            )
            return True, "resolved"
    if instruction.payload.get("to") != "hand" and stays_out_of_battlefield(
        game, card, caster, zone,
    ):
        # CR 614.17 (and 400.4a), before the card leaves its zone.
        return True, "resolved"
    pile.pop(found)
    # "…to your **hand**." (Whiteout.) The destination is payload rather than a
    # second handler, because everything above it — the object is the ability's
    # own source, found by identity in the graveyard the ability functions from
    # — is the same work either way. Absent means the battlefield, which is what
    # every payload written before the hand spelling existed says.
    if instruction.payload.get("to") == "hand":
        # Through the write seam, so CR 903.9b rides it like every other
        # put-into-a-hand.
        if game.put_card_into_hand(caster, card):
            game.log.append(f"{card.name} returned from the graveyard to hand")
        return True, "resolved"
    tapped = bool(instruction.payload.get("tapped"))
    arrived = Permanent(card=card, tapped=tapped)

    # Once it is there — the entry's ``then``, run at the answer when an "as
    # it enters" choice keeps it on its way (CR 614.12a).
    def returned() -> None:
        # Only for an entry that happened (a replacement wrote its own line).
        if not entry_happened(arrived):
            return
        game.log.append(
            f"{card.name} returned from "
            + ("exile" if zone == "exile" else "the graveyard")
            + " to the battlefield"
            + (" tapped" if tapped else "")
        )
        # "…**with a +1/+1 counter on it**." (Sand Golem.) CR 121.2 puts the
        # counters on as the permanent arrives, so they go on *this* object
        # rather than on whatever a later step might find — the permanent is
        # new (CR 400.7) and no target names it.
        #
        # Through the placement seams rather than by poking metadata, so the
        # P/T pair reaches layer 7d and the CR 704.5q sweep can find it: a
        # counter placed by hand is a counter nothing can take off.
        for kind, count in (instruction.payload.get("counters") or {}).items():
            if str(kind) == "+1/+1":
                game.place_plus1_counters(arrived, int(count))
            else:
                game.place_pt_counters(arrived, str(kind), int(count))
            game.log.append(f"{card.name} enters with {count} {kind} counter(s)")
        if host is not None:
            from ..aura_attachment import attach_aura, aura_attach_refusal

            # CR 303.4i asked once more of the permanent itself, for the host
            # that may have stopped being legal while the entry waited on an
            # "as it enters" answer (CR 614.12a); the CR 704.5m sweep would
            # bin an Aura that arrived attached to nothing, so it is asked now
            # rather than at the next one.
            refusal = aura_attach_refusal(game, arrived, host)
            if refusal is None:
                attach_aura(arrived, host)
                game.log.append(f"{card.name} attached to {host.card.name}")
            else:
                game.log.append(f"{card.name} could not attach: {refusal}")
            game.check_state_based_actions()

    game._put_permanent_onto_battlefield(
        game.players.index(caster), arrived, None, from_zone=zone,
        then=returned,
    )
    return True, "resolved"
