"""A **return** to a hand: from a graveyard, or off the battlefield (CR 400.3).

The half of ``engine/grammar/lowering/returns.py`` that lands in a hand. From a
graveyard: a target card (and every narrowing such a return may print), cards
chosen as the effect resolves (Recall), Forgotten Lore's repeated pick, the card
a dies trigger bound (Puppet Master), and each player's own pick (Ill-Gotten
Gains, whose prompt Exhume shares for the battlefield). Off the battlefield, the
bounce: a target, the subject of an event, every permanent a phrase names, a
recorded pick, an enchanted or a bound creature, the source, Unsubstantiate's
"target spell or creature", and Undiscovered Paradise's return during the next
untap step. A permanent's own move is
``_common.return_permanent_to_owners_hand``, and it lands in its **owner's**
hand.

Split out of ``zones.py`` at the 2,000-line cap's split round. A return to the
**battlefield** is ``reanimation.py``'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import Permanent
from ..oracle_types import named_no_target
from ..search_filters import card_has_type
from ._amounts import resolve_amount
from ._common import return_permanent_to_owners_hand
from ._filters import excluded_graveyard_slot, graveyard_card_matches
from ._targets import (_one_choice, _resolve_graveyard_slots,
                       frozen_that_player_seat, resolve_role_permanent,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _return_graveyard_card_to_owners_hand(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Return target creature card **from a graveyard to its owner's hand**."
    (Endbringer's Revel.)

    The pile is the announced seat's (``_run_stack_item_resolution`` writes the
    stamped card's seat back onto the item before any handler runs), and the
    hand is the same player's: a card in a graveyard is in its owner's
    (CR 404.1, 400.3), so "its owner's hand" needs no second lookup. The
    activator's own hand is reached only when the card was theirs.

    A slot that was named and no longer answers the printed noun is CR 608.2b's
    illegal target and returns nothing. An announcement naming **no** slot (an
    AI seat that announced the ability bare) takes the first matching card,
    searched the way Hymn of Rebirth's any-graveyard reanimation searches: the
    named seat, then the activator, then everyone else.
    """
    caster = context.caster

    def _eligible(card) -> bool:
        return graveyard_card_matches(instruction.payload, card)

    named = context.target if context.target in game.players else None
    index = context.target_permanent_index
    found = None
    if isinstance(index, int):
        if (
            named is not None
            and 0 <= index < len(named.graveyard)
            and _eligible(named.graveyard[index])
        ):
            found = (named, index)
    else:
        found = next(
            (
                (player, slot)
                for player in (named, caster, *game.players)
                if player is not None
                for slot, card in enumerate(player.graveyard)
                if _eligible(card)
            ),
            None,
        )
    if found is None:
        game.log.append(f"{context.card.name}: no card was returned from a graveyard")
        return True, "resolved"
    owner, slot = found
    chosen = owner.graveyard.pop(slot)
    game.put_card_into_hand(owner, chosen)
    game.log.append(
        f"{context.card.name}: returned {chosen.name} from {owner.name}'s "
        f"graveyard to {owner.name}'s hand"
    )
    return True, "resolved"


#: The payload keys that narrow *which* creature card a graveyard return may
#: take — everything ``handlers/_filters.graveyard_card_matches`` reads beyond
#: the card type. A return carrying one of them must never reach the generic
#: "first creature card" scan, which reads none of them.
_GRAVEYARD_NARROWING_KEYS = (
    "graveyard_subtypes", "graveyard_colors", "supertypes", "graveyard_mana_value",
)


@effect_handler("return_creature_from_graveyard_to_hand")
def return_creature_from_graveyard_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    if instruction.payload.get("any_graveyard"):
        return _return_graveyard_card_to_owners_hand(game, instruction, context)
    caster = context.caster
    any_card = bool(instruction.payload.get("any_card"))
    card_type = instruction.payload.get("card_type")
    card_types = tuple(instruction.payload.get("card_types") or ())

    # "Return **another** target artifact card from your graveyard to your
    # hand." (Junk Diver.) CR 113.7's source, and a *slot* rather than a kind
    # of card — so it is asked beside the predicate through the one reader the
    # picker also asks, and never folded into ``_eligible``: two copies of one
    # card in one graveyard are the same ``CardDefinition`` object, and a
    # per-card test would take both away where the sentence takes one.
    #
    # ``context.card`` is the ability's own source (CR 113.7), which for the
    # dies-trigger printing this sentence is a card sitting in the very pile
    # being searched. Without it Junk Diver returned **itself** out of an
    # otherwise empty graveyard.
    excluded = excluded_graveyard_slot(
        instruction.payload, caster.graveyard, context.card
    )

    def _eligible(card) -> bool:
        # The picker's predicate, not a third spelling of it. The payload and
        # the spec carry the same key names because one is derived from the
        # other, so there is one answer to "may this card be chosen?".
        return graveyard_card_matches(instruction.payload, card)

    def _eligible_slot(index: int) -> bool:
        """The same question asked of a *position*, which is what the printed
        "another" narrows. Every scan below goes through this rather than
        through ``_eligible`` alone."""
        return index != excluded and _eligible(caster.graveyard[index])

    # "Return up to two target creature cards from your graveyard to your hand."
    # (Sanguine Indulgence.) The several-targets description says a list was
    # collected, so every chosen slot is honoured rather than only the first.
    targets_desc = instruction.payload.get("targets") or {}
    printed_count = targets_desc.get("count") if isinstance(targets_desc, dict) else None
    # Whether the sentence's target *count* is the announced X, remembered
    # before the letter is turned into a number. Everything below the
    # conversion sees an ordinary integer, and "is this a targeted list?" is a
    # different question from "how long is it?" — conflating the two is what
    # made the ``> 1`` gate wrong (see there).
    counted_x = printed_count == "x"
    if printed_count == "x":
        # "Return **X** target creature cards from your graveyard to your hand."
        # (Shattered Crypt.) The announced X (CR 601.2b), which is not a number
        # until the spell is on the stack — so the several-slot branch reads it
        # here rather than being told a literal by the lowering.
        #
        # Gated on the string rather than left to ``isinstance(int)``, which is
        # what this branch used to ask: the Crypt's count arrived as ``'x'``,
        # failed that test, fell through to the single-card path and returned
        # **one** card of however many X paid for — while the card lost X life
        # and reported itself supported.
        printed_count = int(context.x_value or 0)
    # An X-counted list goes through the slot resolver **whatever X is**, and
    # the ``> 1`` beside it is a printed number's threshold rather than this
    # one's. Two cards were mis-resolved by sharing it:
    #
    # * Shattered Crypt cast for X=1 with a list-shaped announcement fell past
    #   the ``isinstance(idx, int)`` branch below (a one-element list is not an
    #   int) and out into the "return whatever creature is nearest" fallback —
    #   so the browser, which sends a list for every several-target picker,
    #   returned the first creature card in the pile instead of the one the
    #   caster targeted.
    # * "Return **up to X** target cards…" (Reap) counted at 0 reached the same
    #   fallback and returned a card for a spell that names none — an effect
    #   happening more often than the card allows, which is the direction that
    #   never announces itself.
    #
    # Zero picks is a legal outcome here, not a reason to guess: the sentence
    # targets (CR 601.2c), so an announcement naming nothing returns nothing.
    if counted_x or (isinstance(printed_count, int) and printed_count > 1):
        picked = _resolve_graveyard_slots(
            caster, context, printed_count, _eligible
        )
        for returned_card in picked:
            game.put_card_into_hand(caster, returned_card)
            game.log.append(
                f"Returned {returned_card.name} from graveyard to hand"
            )
        if not picked:
            game.log.append("No card was returned from the graveyard")
        return True, "resolved"

    # "Return **up to one** target creature card…" announced naming nobody
    # (Liliana, Death Mage's +1; CR 601.2c). Every branch below this line is a
    # pick somebody is owed — the named slot, then a scan of the pile — and
    # an announcement that named nobody is owed none: it returned the first
    # creature card in the graveyard for a player who had chosen zero.
    if named_no_target(context.choices):
        game.log.append("No card was returned from the graveyard")
        return True, "resolved"

    # Honor the caster's chosen graveyard card (Rule 601.2c). Regrowth
    # (any_card) accepts any type; Raise Dead only a creature card.
    idx = context.target_permanent_index
    if isinstance(idx, int) and 0 <= idx < len(caster.graveyard) and _eligible_slot(
        idx
    ):
        chosen = caster.graveyard.pop(idx)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_types:
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append(f"No {' or '.join(card_types)} card in graveyard to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    if card_type is not None and card_type != "creature":
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append(f"No {card_type} card in graveyard to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"

    # The unnarrowed creature return, and the last place the printed "another"
    # has to be honoured: with an exclusion in force the generic scan would take
    # the source itself, so the slot walk above is used instead. Without one the
    # call is left exactly as it was, so every card written before this keeps
    # its behaviour byte for byte.
    #
    # **…and the last place a printed narrowing has to be.** "Return target
    # **Zombie** card from your graveyard to your hand" (Lord of the Undead) is
    # ``card_type: "creature"`` plus ``graveyard_subtypes``, so it reaches this
    # point — and the generic scan below asks only "is it a creature card?".
    # With no slot announced (a bare activation, an AI seat, an entry trigger
    # nothing chose a target for) or with the announced card gone, the Lord
    # returned whichever creature card lay first in the pile: a Grizzly Bears.
    # Three shipped cards did the same — Mtenda Griffin a non-Griffin, Strongarm
    # Thug a non-Mercenary, Crypt Angel a green creature for "blue or red" — on
    # the ordinary cast, because nothing announces an entry trigger's target.
    #
    # The keys are the ones ``graveyard_card_matches`` reads beyond the type
    # itself, so the scan and the picker ask one predicate.
    narrowed = any(
        instruction.payload.get(key) for key in _GRAVEYARD_NARROWING_KEYS
    )
    if excluded is not None or narrowed:
        chosen_index = next(
            (i for i in range(len(caster.graveyard)) if _eligible_slot(i)), None
        )
        if chosen_index is None:
            game.log.append("No creature to return")
            return True, "resolved"
        chosen = caster.graveyard.pop(chosen_index)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    returned = game._return_creature_from_graveyard(caster)
    if not returned and any_card and caster.graveyard:
        chosen = caster.graveyard.pop(0)
        game.put_card_into_hand(caster, chosen)
        game.log.append(f"Returned {chosen.name} from graveyard to hand")
        return True, "resolved"
    game.log.append("Returned creature from graveyard" if returned else "No creature to return")
    return True, "resolved"


@effect_handler("return_chosen_cards_from_graveyard_to_hand")
def return_chosen_cards_from_graveyard_to_hand(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Return a card from your graveyard to your hand **for each card
    discarded this way**." (Recall.)

    Chosen while the spell resolves, not targeted at cast time (CR 601.2c): how
    many cards there are to return is the answer to a prompt this same
    resolution armed, so the picks could not have been named when the spell went
    on the stack. Nothing is lost by that — the cards are in the chooser's own
    graveyard, a public zone with no shroud, no protection and nothing for
    targeting to protect.

    The picker is the search prompt, pointed at the graveyard. Not a second
    prompt kind, because the question is the one that prompt already asks —
    "choose up to N cards from this zone, and here is what may be chosen" — and
    it already suspends the resolution, already has a non-interactive default and
    is already rendered. What the printed sentence adds is *where the number
    comes from*.

    Fewer cards than the number asked for is a legal outcome (CR 608.2b): the
    count is capped at what the graveyard holds, and an empty graveyard returns
    nothing rather than arming a prompt with nothing in it.
    """
    caster = context.caster
    source_key = instruction.payload.get("amount_from")
    if source_key is not None:
        amount = max(0, int(context.results.get(source_key, 0) or 0))
    else:
        amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)

    def _eligible(card) -> bool:
        return graveyard_card_matches(instruction.payload, card)

    available = sum(1 for card in caster.graveyard if _eligible(card))
    amount = min(amount, available)
    if amount <= 0:
        game.log.append(f"{caster.name} returns no cards from their graveyard")
        return True, "resolved"
    game.arm_pending_choice(
        "search_library", game.players.index(caster),
        count=amount,
        card_type=instruction.payload.get("card_type") or "any",
        zones=("graveyard",),
        restrictions={},
        destination="hand",
        # One slot per card the sentence asks for, all of them the hand. Two or
        # more slots is what puts the prompt on its counted path, where the
        # whole answer arrives at once.
        destinations=["hand"] * amount,
        tapped=[False] * amount,
        card_name=context.card.name if context.card is not None else "",
        enters_tapped=False,
        untap_found_if=None,
        up_to=False,
        reveal=False,
    )
    game.log.append(
        f"{caster.name} chooses {amount} card(s) from their graveyard to return"
    )
    return True, "resolved"


@effect_handler("return_bound_card_to_owners_hand")
def return_bound_card_to_owners_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return that card to its owner's hand." (Puppet Master.)

    The bound object — the card of the creature whose death fired the trigger,
    which CR 404.1 put in its *owner's* graveyard. The fire site froze the card
    itself (CR 603.10); by resolution nothing else could name it, because the
    permanent is gone and a graveyard holds several copies of a popular card
    under one name.

    Located by identity and removed with ``pop`` at the found index, for the
    reason ``return_self_from_graveyard`` records: a name match finds the wrong
    entry and a rebuild-from-survivors removes every copy.

    Records ``returned_bound_card`` either way — True when the card actually
    reached a hand, False when it had already left the graveyard (exiled in
    response) or was diverted (CR 903.9b). "If that card is returned to its
    owner's hand this way" is exactly that question.
    """
    card = (context.trigger_context or {}).get("dead_card")
    context.results["returned_bound_card"] = False
    if card is None:
        return True, "resolved"
    # "…to **your** hand" (Enduring Renewal) rather than "…to its owner's hand"
    # (Puppet Master). Two seats, and which one the card names is payload: on
    # Enduring Renewal they coincide, because the trigger only fires on a card
    # put into the controller's own graveyard — but reading them as one would
    # put an opponent's dead creature in the wrong hand the moment another card
    # printed the other word.
    recipient = (
        context.caster if instruction.payload.get("to_seat") == "controller" else None
    )
    # "…from **your** graveyard" (Pitchstone Wall) looks in one pile only.
    piles = (
        [context.caster] if instruction.payload.get("from_seat") == "controller"
        else game.players
    )
    for player in piles:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                lands_with = recipient if recipient is not None else player
                if game.put_card_into_hand(lands_with, card):
                    context.results["returned_bound_card"] = True
                    game.log.append(
                        f"{card.name} returned to {lands_with.name}'s hand"
                    )
                return True, "resolved"
    # CR 603.6: the ability looks for the object in the zone it moves it out of.
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


@effect_handler("return_source_card_to_owners_hand")
def return_source_card_to_owners_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return this card to its owner's hand." (Puppet Master's paid rider.)

    The ability's own source, printed with **no source zone** — so unlike
    ``return_self_from_graveyard``, whose sentence names one, this reaches
    whichever zone the object is actually in (CR 608.2). Usually the graveyard:
    an Aura whose enchanted creature has left is put there by the CR 704.5m
    sweep, which runs the next time a player would receive priority and so
    before this trigger resolves. But the sweep is not guaranteed to have run —
    a caller that resolves the stack without an intervening priority pass finds
    the Aura still on the battlefield — and a handler that looked in one zone
    would silently do nothing in the other.

    By identity, like every other graveyard reach in this module, and across
    every graveyard rather than the resolving seat's: CR 404.1 puts the card in
    its *owner's*, and an Aura its controller did not own goes to the other
    player's.

    ``from: "battlefield"`` takes that reach away, and one shape asks for it:
    the sentence as the effect of a **delayed** ability (Contempt's "…return it
    and this Aura to their owners' hands at end of combat"). A whole combat step
    later, CR 400.7 makes the card in the graveyard a different object from the
    permanent the ability was created about — so an Aura destroyed in response
    to the trigger stays dead, where the reach above would hand it back. The
    lowering decides which reading applies, from the event the sentence is
    under (``_common._source_return_reach``).
    """
    card = context.card
    source = context.source_permanent
    if source is not None and game.is_on_battlefield(source):
        # CR 108.3's seat, read the way ``control.base_controller`` says to:
        # the recorded base seat, and *where the permanent sits* when there is
        # none. The literal ``.get(..., 0)`` this replaced was a third answer —
        # seat 0 — so an Aura on a board that recorded no base controller went
        # to the wrong player's hand, which no assertion about seat 0's hand can
        # tell from the right one.
        from ..control import base_controller

        seat = base_controller(source)
        if seat is None:
            seat = game.controller_index_of(source)
        owner = game.players[seat if seat is not None else 0]
        game.remove_from_battlefield(source)
        if game.put_card_into_hand(owner, card, from_battlefield=source):
            game.log.append(f"{card.name} returned to {owner.name}'s hand")
        return True, "resolved"
    if instruction.payload.get("from") == "battlefield":
        game.log.append(f"{card.name} was no longer on the battlefield")
        return True, "resolved"
    for player in game.players:
        for index, held in enumerate(player.graveyard):
            if held is card:
                player.graveyard.pop(index)
                if game.put_card_into_hand(player, card):
                    game.log.append(f"{card.name} returned to {player.name}'s hand")
                return True, "resolved"
    game.log.append(f"{card.name} was no longer in a graveyard")
    return True, "resolved"


def _mana_value_of(card) -> int:
    """A card's mana value (CR 202.3), for the step that reads what a bounce
    returned.

    Off the printed cost, which is the only reading available: the object being
    asked about has left the battlefield, so there is no permanent to put through
    the layer system and no continuous effect that could have changed the number
    anyway (CR 202.3b — mana value is computed from the mana cost as printed).
    """
    return int(card.cmc or 0)


@effect_handler("bounce_target_creature")
def bounce_target_creature(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # "Return up to two target creatures to their owners' hands." (Read the
    # Tides' second mode.) The several-targets description says a list was
    # collected: each slot resolves strictly (a departed target is dropped,
    # CR 608.2b) and each creature goes to its own owner's hand (CR 400.3).
    targets_desc = instruction.payload.get("targets") or {}
    from ..targeting import payload_own_role

    if (
        isinstance(targets_desc, dict)
        and targets_desc.get("kind") == "roles"
        and payload_own_role(instruction.payload) is None
    ):
        # "Return target creature **and target land** to their owners' hands."
        # (Churning Eddy.) Several targeted phrases of one announcement, each
        # with its own noun — the destroy handler's Fumarole branch one zone
        # change over: each slot is resolved *by its role* and its filter
        # re-asked (a creature that stopped being one is not the thing chosen
        # for that role), and an illegal slot is skipped while the other still
        # returns (CR 608.2b). Each goes to its own owner's hand (CR 400.3).
        from ..subject_filters import subject_matches

        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        returned = []
        for role in targets_desc.get("roles") or ():
            perm = resolve_role_permanent(
                game, context, instruction.payload, role.get("role")
            )
            if perm is None or not game.is_on_battlefield(perm):
                continue
            if not subject_matches(
                game, perm, role.get("filter") or {},
                observer=observer, source=context.source_permanent,
            ):
                continue
            owner = return_permanent_to_owners_hand(game, perm, context.caster)
            returned.append(perm)
            game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        if not returned:
            game.log.append(f"{context.card.name}: nothing was returned")
        return True, "resolved"
    # ``not in (None, 1)`` and never ``isinstance(..., int) and > 1``, which is
    # what stood here: a count of ``"x"`` is exactly what a computed number
    # looks like on this key ("Return up to **X** target permanents to their
    # owners' hands", Recantation), and an int test reads it as "not several"
    # and falls through to the single-target path below — one permanent
    # returned of the X the picker collected, with nothing to see. The destroy
    # handler one family over already asks it this way.
    if isinstance(targets_desc, dict) and targets_desc.get("count") not in (None, 1):
        # The printed noun phrase, honoured rather than assumed. This branch
        # used to take every slot the picker filled: right for "up to two target
        # creatures", whose picker offers only creatures, and wrong the moment a
        # narrowing the picker cannot enforce arrives — the same asymmetry the
        # singular branch below spells out at length. Asked through
        # ``subject_matches`` for that branch's reason: a controller is a seat
        # comparison (CR 109.5) the object alone cannot answer.
        from ..subject_filters import subject_matches

        described = targets_desc.get("filter") or {}
        observer = (
            game.players.index(context.caster) if context.caster in game.players
            else None
        )
        # Handed **into** the resolver as its predicate rather than applied to
        # what it returns, and that is the whole of the fix: its default
        # predicate is ``p.is_creature``, so a bare
        # ``resolve_target_permanents(game, context)`` drops every non-creature
        # slot before this branch can see it — Recantation returned two of the
        # three permanents its picker collected and logged itself resolved.
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: subject_matches(
                game, perm, described,
                observer=observer, source=context.source_permanent,
            ),
        )
        for perm in chosen:
            owner = return_permanent_to_owners_hand(game, perm, context.caster)
            game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        if not chosen:
            game.log.append("No permanents to return")
        return True, "resolved"
    # A narrowed or widened bounce ("up to one target non-Spirit creature",
    # Roaming Ghostlight; "up to one other target creature or planeswalker",
    # Barrin) carries its filter. Resolved strictly — no fallback scan, since
    # "up to one" legally names nothing — and enforced here so a stale or
    # illegal choice bounces nothing rather than the wrong thing.
    # ``in``, not truthiness: "Return target **permanent** to its owner's hand"
    # (Boomerang) narrows nothing, so its filter is an empty dict — and an empty
    # dict read as "no filter" would drop through to the creature-only fallback
    # below and refuse to bounce the land the spell legally targeted. The key's
    # *presence* is what says the lowering described this bounce's subject.
    if "filter" in instruction.payload:
        bounce_filter = instruction.payload["filter"]
        source = context.source_permanent

        # "another target creature **you control**" (Niambi, Esteemed Speaker).
        # Through ``subject_matches`` rather than the pure matcher, because the
        # controller question is a seat comparison the object alone cannot
        # answer (CR 109.5) — and it carries ``exclude_self`` in the same call,
        # so the two narrowings are one rule instead of one here and one there.
        # Late import: ``subject_filters`` imports this package's floors,
        # so the edge is taken at call time rather than at module load.
        from ..subject_filters import subject_matches

        observer = game.players.index(context.caster)
        # "…return target creature **that player** controls" (Sigil of Sleep).
        # The seat is the firing event's, frozen in the trigger's context, and
        # the matcher cannot answer the phrase without it — it fails closed. So
        # the trigger chose a legal target as it went on the stack, this
        # re-check then refused that same target, and the card returned
        # nothing. ``scripts/unasked_narrowings.py`` had the entry
        # (``bounce_target_creature needs that_player=``); driving the card
        # through a real damage event is what showed it was not one of the
        # entries a handler answers some other way. None for every bounce
        # that prints no such phrase, which is what was passed before.
        that_player = frozen_that_player_seat(game, context)

        def _legal(perm) -> bool:
            return subject_matches(
                game, perm, bounce_filter, observer=observer, source=source,
                that_player=that_player,
            )

        perm = resolve_target_permanent(
            game, context, predicate=_legal, fallback_on_invalid_choice=False,
        )
        if perm is None:
            game.log.append(f"{context.card.name}: nothing was returned")
            return True, "resolved"
        owner = return_permanent_to_owners_hand(game, perm, context.caster)
        # "…you gain life equal to that creature's mana value" (Niambi). Read
        # here, while the permanent is still in hand, because the next step of
        # this same resolution has no way back to it — CR 400.7 makes the card in
        # the hand a new object, and the battlefield no longer holds the old one.
        # ``_PRODUCES`` names this kind as the producer, so every path of this
        # handler that returns one creature records it.
        context.results["returned_mana_value"] = _mana_value_of(perm.card)
        game.log.append(f"{perm.card.name} returned to {owner.name}'s hand")
        return True, "resolved"
    target = context.target
    # Resolved **once**, by id, and used for both the bounce and the record.
    # An earlier removal renumbers the battlefield under a recorded index
    # (CR 400.7), so the slot names whichever creature slid into the vacated
    # place — and this site used to read it twice, once here for
    # "…equal to that creature's mana value" and once inside the bounce. Two
    # reads of one choice are free to disagree: the life could be gained for a
    # creature other than the one returned.
    returned = resolve_target_permanent(game, context, player=target)
    bounced = game._bounce_target_creature(returned)
    if bounced and returned is not None:
        context.results["returned_mana_value"] = _mana_value_of(returned.card)
    game.log.append("Returned creature to hand" if bounced else "No creature to return")
    return True, "resolved"


@effect_handler("bounce_event_subject")
def bounce_event_subject(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever a creature becomes the target of a spell or ability, **return
    that creature to its owner's hand**." (Cowardice.)

    The permanent the *trigger's own event* was about, carried by id in the
    trigger's context — ``destroy_event_subject``'s twin one zone change over
    (CR 400.1; a return to a hand is no keyword action at all), reading the same
    frozen key for the same reason: nothing was chosen (CR 603.3d printed no
    target), and by resolution an index is not an identity (CR 400.7 / 603.10).

    Not routed through ``bounce_target_creature``: that one raises a picker for
    a choice this card never offered and then returns whichever permanent the
    resolution context happened to hold.

    **No re-check of the printed noun**, for that handler's stated reason: the
    event's filter already decided this permanent is what the trigger was
    about, and asking again would let a creature that stopped being one between
    the two escape a bounce the rules have already aimed at it.

    A permanent already gone is returned by nothing, which is CR 608.2b doing
    as much as it can. Cowardice's own reminder text says the spell that
    triggered it still resolves and finds nothing there.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("event_subject_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    owner = return_permanent_to_owners_hand(game, victim, context.caster)
    game.log.append(
        f"{victim.card.name} returned to {owner.name}'s hand ({context.card.name})"
    )
    return True, "resolved"


def _was_attached_to(perm, host_id: int) -> bool:
    """Whether *perm* is — or was, this resolution — attached to *host_id*.

    Both records, because a sweep that names an attachment can run after the
    host has moved: "Return target creature **and all white Auras you own
    attached to it**" (Word of Undoing) bounces the creature in the step before
    this one, and ``detach_aura`` has already cleared the live pointer by then.
    That is CR 603.10's reading — the spell chose its target while it was on the
    battlefield — and the id is what keeps it from matching a look-alike
    (CR 400.7).
    """
    host = perm.metadata.get("attached_to") or perm.metadata.get("last_attached_to")
    return host is not None and getattr(host, "permanent_id", None) == host_id


@effect_handler("return_all_matching")
def return_all_matching(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return to your hand all enchantments you both own and control…"
    (Remove Enchantments.)

    The sweep twin of ``bounce_target_creature``: no pick, every permanent the
    noun phrase names, each to *its owner's* hand (CR 400.3). One handler for
    every such phrase, because what a bounce does per object does not depend on
    which noun was printed — the noun is the payload.

    The filter is asked through ``subject_matches`` with CR 109.5's observer:
    "you control", "you own" and the host phrase inside "attached to permanents
    you control" are all seat comparisons, and the lowering admitted the line
    only because this is where they are answered.

    ``attached_to`` narrows the sweep to what is on one named permanent —
    "…and all white Auras you own **attached to it**" (Word of Undoing), where
    "it" is the creature the same spell targeted. Beside the filter rather than
    inside it, because it is a relation no read of the Aura alone can answer:
    the referent is resolved here and the hosts are compared by identity, the
    same split ``destroy_all_matching`` makes for the same key.

    The matched list is taken **before** anything moves. A permanent leaving
    detaches its Auras, so a sweep that re-read the board between removals
    would stop matching Auras it had already named — and "attached to" is
    exactly what half of this card's phrases ask about. Word of Undoing makes
    that load-bearing rather than careful: the creature is bounced by the step
    in front of this one, so by the time the sweep runs every Aura it names has
    already fallen off.
    """
    from ..subject_filters import subject_matches

    swept = instruction.payload.get("filter") or {}
    # "…all creatures **of that color**" (Dromar, the Banisher) / "…all
    # permanents **of the color of your choice**" (Wash Out). CR 608.2d's
    # colour, chosen by the step in front of this one and read out of the
    # scratchpad exactly as Persecute's discard reads it.
    #
    # **No colour means no sweep**, and it must: an unanswered choice read as
    # "no narrowing" is not a card that does less, it is one that returns every
    # permanent on the table.
    color_key = instruction.payload.get("color_filter_from")
    if color_key is not None:
        chosen_color = context.results.get(str(color_key))
        if not chosen_color:
            game.log.append(
                f"{context.card.name}: no colour was chosen, so nothing is returned"
            )
            return True, "resolved"
        swept = {**swept, "color_filter": str(chosen_color)}
    observer = (
        game.players.index(context.caster) if context.caster in game.players else None
    )
    host_id = None
    attached_to = instruction.payload.get("attached_to")
    if attached_to is not None:
        # By **id**, not by object, and that is what makes Word of Undoing work
        # at all: the step in front of this one has already bounced the
        # creature, so ``permanent_by_id`` no longer finds it while every Aura
        # still holds the record of what it was on. CR 400.7 makes the id
        # unique to that object, so a look-alike cannot answer to it.
        # Through ``_one_choice``, because the two callers hand this field
        # different shapes: a *spell* records one id (Word of Undoing) and an
        # *activated ability* records the whole announced list, even when the
        # list is one long. Read raw, an ability's `[7]` never equals any
        # permanent's id and the sweep found nothing on a host the player had
        # chosen — Scarab of the Unseen is the first ability to reach here.
        host_id = (
            _one_choice(context.target_permanent_id)
            if attached_to == "target" else None
        )
        if not isinstance(host_id, int):
            # The relation is the whole narrowing, so a referent this cannot
            # resolve ends the sweep rather than widening it to the board.
            game.log.append(
                f"{context.card.name}: nothing is attached to a permanent that is gone"
            )
            return True, "resolved"
    # "…each creature **that player** controls with power greater than the
    # number of cards in **their** hand." (Noetic Scales.) The seat the firing
    # event froze (CR 603.10) — a different player on every upkeep, and never
    # this artifact's controller except on their own turn. Read through the one
    # reader of the printed phrase, so both narrowings that name it name the
    # same player; None where nothing froze one, which the matcher answers by
    # refusing the words rather than by widening the sweep to the table.
    that_player = frozen_that_player_seat(game, context)
    matched = [
        perm for perm in game.all_permanents()
        if subject_matches(
            game, perm, swept, observer=observer, source=context.source_permanent,
            that_player=that_player,
        )
        and (host_id is None or _was_attached_to(perm, host_id))
    ]
    returned: list[str] = []
    for perm in matched:
        if not game.is_on_battlefield(perm):
            # It went with something else this same sweep removed — a token
            # ceasing to exist, an Aura falling off. Nothing left to return.
            continue
        return_permanent_to_owners_hand(game, perm, context.caster)
        returned.append(perm.card.name)
    game.log.append(
        f"{context.card.name} returned {', '.join(returned)} to hand"
        if returned else f"{context.card.name}: nothing to return"
    )
    return True, "resolved"


@effect_handler("each_player_takes_from_graveyard")
def each_player_takes_from_graveyard(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player puts a creature card from their graveyard onto the
    battlefield." (Exhume.) "…each player … returns up to three cards from
    their graveyard to their hand." (Ill-Gotten Gains.)

    One pick per seat, out of that seat's own graveyard and into that seat's own
    zone — which is why it arms a prompt per player rather than resolving a
    target: nothing is announced (CR 115.1), there is nothing for targeting to
    protect in a public zone, and the seat that chooses is not the seat that
    cast the spell. The same ``search_library`` prompt Reincarnation's graveyard
    pick already uses, with the two seats named on it, so one picker, one AI
    policy and one re-check serve every reading of "a card from a graveyard".

    How many, whether fewer is a legal answer and where they land are payload,
    because the two cards differ in nothing else: both empty a pile into a zone
    one seat at a time, and a second kind would be a second copy of arming this
    prompt.

    Offered in CR 101.4's order — the active player first — and only to a seat
    whose graveyard actually holds a card the phrase names: a prompt over a pile
    with nothing in it is a decision with one answer, and arming it would stop
    the game to ask it (``ChoiceSpec.holds_priority``). A seat that cannot takes
    nothing, which is CR 608.2's "as much as possible".
    """
    card_type = str(instruction.payload.get("card_type", "any"))
    destination = str(instruction.payload.get("destination", "battlefield"))
    count = max(1, int(instruction.payload.get("count", 1)))
    up_to = bool(instruction.payload.get("up_to"))
    total = len(game.players)
    active = game.active_player_index or 0
    seats = sorted(
        (i for i, p in enumerate(game.players) if not p.lost),
        key=lambda i: ((i - active) % total, i),
    )
    armed = 0
    for seat in seats:
        player = game.players[seat]
        available = sum(
            1 for card in player.graveyard
            if card_type == "any" or card_has_type(card, card_type)
        )
        if not available:
            game.log.append(f"{player.name} has no {card_type} card to take")
            continue
        # The printed ceiling, capped by the pile: a counted search is driven by
        # one entry per find, and a slot with nothing that could fill it is a
        # find the seat can never make.
        slots = min(count, available)
        game.arm_pending_choice(
            "search_library", seat,
            zone_seat=seat,
            battlefield_seat=seat,
            count=slots,
            card_type=card_type,
            zones=("graveyard",),
            restrictions={},
            destination=destination,
            destinations=[destination] * slots if slots > 1 else [],
            tapped=[],
            card_name=context.card.name if context.card is not None else "",
            enters_tapped=False,
            untap_found_if=None,
            up_to=up_to,
            exile_rest=False,
            reveal=False,
            record=context.results,
            record_key=None,
        )
        armed += 1
    if not armed:
        game.log.append(f"{context.card.name}: no graveyard holds one")
    return True, "resolved"


@effect_handler("return_all_owned_artifacts_to_hand")
def return_all_owned_artifacts_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hurkyl's Recall: "Return all artifacts target player owns to their hand."

    Owns, not controls. An artifact the target player owns but an opponent has
    stolen still returns, and to the *owner's* hand (CR 400.3) — which is why
    this asks ``owner_index_of`` rather than reading the battlefield it happens
    to be sitting on.
    """
    owner_index = game.players.index(context.target)
    returned = 0
    for player in game.players:
        for permanent in list(player.battlefield):
            if not permanent.has_type("artifact"):
                continue
            if game.owner_index_of(permanent) != owner_index:
                continue
            # Identity, not value: two untapped Moxen of the same name are ``==``.
            game.remove_from_battlefield(permanent)
            game.put_card_into_hand(
                owner_index, permanent.card, from_battlefield=permanent
            )
            game._remove_aura_effects(permanent)
            returned += 1
    game.log.append(f"Returned {returned} artifact(s) to {context.target.name}'s hand")
    return True, "resolved"


@effect_handler("return_spell_or_creature_to_hand")
def return_spell_or_creature_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Return target spell or creature to its owner's hand." (Unsubstantiate.)
    A chosen spell is unstacked to its owner's hand — not countered, so
    nothing is binned and no counter triggers fire; a chosen creature is the
    ordinary bounce."""
    chosen = context.stack_target
    # By identity, as every other leave-the-stack site walks it: a
    # ``StackItem`` compares by value, so two casts of one card with one target
    # are equal and ``in``/``remove`` would find whichever sits lower.
    slot = next(
        (index for index, item in enumerate(game.stack) if item is chosen), None
    )
    if chosen is not None and slot is not None:
        del game.stack[slot]
        if chosen.is_copy:
            # CR 707.10a: a copy of a spell leaving the stack ceases to exist —
            # it has no card to put in anybody's hand.
            game.log.append(
                f"{context.card.name} returned {chosen.card.name} (copy) from "
                "the stack, and it ceases to exist"
            )
            return True, "resolved"
        # "to its **owner's** hand" (CR 108.3) — the stack object's owner, who
        # is not its caster when it was cast out of another player's zone.
        owner = game.players[chosen.owner_index]
        from ..flashback import leaves_stack_to_exile

        if leaves_stack_to_exile(chosen):
            # CR 702.34a: a spell whose flashback cost was paid is exiled
            # "instead of putting it anywhere else any time it would leave the
            # stack" — a hand included.
            game._bin_spell_card(
                owner, chosen.card, exile_instead=True,
                verb=f"was returned by {context.card.name}",
            )
            return True, "resolved"
        game.put_card_into_hand(owner, chosen.card)
        game.log.append(
            f"{context.card.name} returned {chosen.card.name} from the stack "
            f"to {owner.name}'s hand"
        )
        return True, "resolved"
    bounced = game._bounce_target_creature(
        resolve_target_permanent(game, context)
    )
    game.log.append(
        "Returned creature to hand" if bounced else f"{context.card.name}: nothing was returned"
    )
    return True, "resolved"


#: Where the repeated pick keeps the cards it has already offered, on the
#: resolution's own scratchpad. Written here and read by the prompt's resolver
#: through the context it carries, because the loop spans several prompts and
#: nothing on a board records a choice.
FORGOTTEN_PICKS = "repeated_graveyard_picks"


@effect_handler("repeated_graveyard_pick")
def repeated_graveyard_pick(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Forgotten Lore: "Target opponent chooses a card in your graveyard. You
    may pay {G}. If you do, repeat this process except that opponent can't
    choose a card already chosen for Forgotten Lore. Then put the last chosen
    card into your hand."

    One round of the loop: the opponent picks, and answering that prompt offers
    the caster the cost that buys another round. The chain runs through the
    pending-choice queue rather than a Python loop, because two different seats
    answer alternately and neither answer is available when this returns.

    The exclusion set and the last pick live on ``context.results``, which every
    round of the chain shares — the `optional_pay` entry carries this same
    context, so the instruction that re-arms the prompt sees what the previous
    rounds recorded.

    Nothing left to choose ends the process, which is the other way out of it
    besides declining: the printed "repeat" cannot repeat over an empty
    graveyard, and the last card chosen is still put into the hand.
    """
    caster = context.caster
    opponent = context.target
    if opponent is None or opponent is caster:
        game.log.append(f"{context.card.name}: no opponent to choose")
        return True, "resolved"
    already = context.results.setdefault(FORGOTTEN_PICKS, [])
    legal = [
        index
        for index, card in enumerate(caster.graveyard)
        if not any(card is taken for taken in already)
    ]
    if not legal:
        _finish_repeated_graveyard_pick(game, context)
        return True, "resolved"
    game.arm_pending_choice(
        "graveyard_pick_for_price", game.players.index(opponent),
        card_name=context.card.name,
        owner_index=game.players.index(caster),
        legal_indices=legal,
        cost=dict(instruction.payload.get("cost") or {}),
        _instruction=instruction,
        _context=context,
    )
    game.log.append(
        f"{opponent.name} must choose a card in {caster.name}'s graveyard "
        f"({context.card.name})"
    )
    return True, "pending_graveyard_pick_for_price"


def _finish_repeated_graveyard_pick(game: Game, context: OracleExecutionContext) -> None:
    """"Then put the **last chosen** card into your hand." — the pick the loop
    stopped on, whichever way it stopped.

    By identity in the caster's own graveyard: a graveyard is a list of card
    definitions and two copies of a card are the same object, so a name match
    would take whichever one came first.
    """
    caster = context.caster
    picks = context.results.get(FORGOTTEN_PICKS) or []
    if not picks:
        game.log.append(f"{context.card.name}: nothing was chosen")
        return
    last = picks[-1]
    for index, held in enumerate(caster.graveyard):
        if held is last:
            caster.graveyard.pop(index)
            game.put_card_into_hand(caster, last)
            game.log.append(
                f"{caster.name} put {last.name} into their hand "
                f"({context.card.name})"
            )
            return
    game.log.append(f"{last.name} was no longer in {caster.name}'s graveyard")


@effect_handler("finish_repeated_graveyard_pick")
def finish_repeated_graveyard_pick(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Then put the last chosen card into your hand." (Forgotten Lore.)

    The decline branch of the loop's payment offer, and its own instruction
    because the loop can also end by running the graveyard out — two ways in,
    one sentence.
    """
    _finish_repeated_graveyard_pick(game, context)
    return True, "resolved"


@effect_handler("return_recorded_permanents_to_hand")
def return_recorded_permanents_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…return **a creature you control** to its owner's hand." (Shrieking
    Drake, Stampeding Wildebeests, the Karoo land cycle's price, Bull Elephant,
    Ovinomancer, Waterspout Djinn.)

    The act half of a pick-then-act pair: the ``choose_permanents`` step in
    front of this one asked the controller which of their own permanents the
    sentence names, and this returns exactly those. Nothing is targeted, so
    there is no index to read and no CR 608.2b re-check to make — only the
    record.

    A permanent that has **left** since the pick is simply not returned. It was
    a different object the moment it left (CR 400.7) and the sentence never
    named the one that came back; an empty record is a legal outcome, not an
    error.

    The record's shape is the producer's, and this reader takes all three the
    engine writes under a ``permanents_from`` key — a bare id
    (``choose_permanent``), a list of ids (the sweeps), a list of ``Permanent``
    objects (``choose_permanents``, whose resolver records the objects because
    Raiding Party's reader wants them). That the channel carries three shapes is
    SET_PLAYBOOK's standing "``permanents_from`` carries two arities" gap, now
    measurably three; normalising here is the local half of it, as
    ``handlers/pump.py`` already says of itself.
    """
    recorded = (context.results or {}).get(
        str(instruction.payload.get("permanents_from", ""))
    ) or ()
    if isinstance(recorded, int) or isinstance(recorded, Permanent):
        recorded = (recorded,)
    returned: list[str] = []
    for entry in recorded:
        perm = (
            entry if isinstance(entry, Permanent)
            else game.permanent_by_id(entry) if isinstance(entry, int)
            else None
        )
        if perm is None or not game.is_on_battlefield(perm):
            continue
        name = perm.card.name
        return_permanent_to_owners_hand(game, perm, context.caster)
        returned.append(name)
    game.log.append(
        f"{context.card.name} returned {', '.join(returned)} to hand"
        if returned else f"{context.card.name}: nothing was returned to hand"
    )
    return True, "resolved"


@effect_handler("return_bound_permanent_to_hand")
def return_bound_permanent_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Whenever this creature blocks a creature, return **that creature** to
    its owner's hand at end of combat." (Wall of Tears, CR 511.1 / CR 603.7.)

    The bounce twin of ``destroy_bound_permanent`` and ``phase_out_bound_permanent``,
    and read exactly as they are: the object is the one the ability that created
    this delay bound (CR 603.7c), carried by id in the trigger's context. By end
    of combat it may have been destroyed, removed from combat, or renumbered by
    something else leaving (CR 400.7) — so it is an id, never an index and never
    a board search.

    **No re-check of the printed noun**, for ``phase_out_bound_permanent``'s
    stated reason: the pronoun restates the trigger's own noun phrase, the
    condition already decided this creature is what the ability is about, and
    asking again at end of combat would let a creature whose type changed
    mid-combat escape a bounce CR 603.7c has already aimed at it.

    A permanent already gone is returned by nothing, which is CR 608.2b doing as
    much as it can rather than a failure.
    """
    victim = game.permanent_by_id(
        (context.trigger_context or {}).get("bound_permanent_id")
    )
    if victim is None or not game.is_on_battlefield(victim):
        game.log.append(f"{context.card.name}: the permanent it named is gone")
        return True, "resolved"
    name = victim.card.name
    owner = return_permanent_to_owners_hand(game, victim, context.caster)
    game.log.append(f"{name} returned to {owner.name}'s hand")
    return True, "resolved"


@effect_handler("return_attached_permanent_to_hand")
def return_attached_permanent_to_hand(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"{W}: Return **enchanted creature** to its owner's hand." (Sun Clasp.)

    The bounce twin of ``destroy_attached_permanent``, and read the same way:
    CR 303.4b makes "enchanted" a name for the object this Aura is already
    attached to, so nothing is chosen, nothing is targeted, and there is no
    picker answer for the resolution context to carry.

    An Aura that has come unattached bounces nothing — the window CR 303.4c's
    state-based action has not closed yet — and the source going with it is
    ``attached_host``'s CR 603.10 last-known fallback, not this handler's
    problem.
    """
    from ._targets import attached_host

    host = attached_host(game, context.source_permanent)
    if host is None or not game.is_on_battlefield(host):
        game.log.append(f"{context.card.name}: nothing attached to return")
        return True, "resolved"
    name = host.card.name
    owner = return_permanent_to_owners_hand(game, host, context.caster)
    game.log.append(f"{name} returned to {owner.name}'s hand")
    return True, "resolved"


#: Whose untap step a permanent is waiting to be returned to hand during
#: ("**During your next untap step**, as you untap your permanents, return this
#: land to its owner's hand" — Undiscovered Paradise). A seat index on the
#: permanent, written by the ability that armed it and read by the CR 614
#: ``would_untap`` replacement in `engine/replacements/permanents.py`.
#:
#: The seat is recorded rather than left implicit, unlike ``skip_next_untap``'s
#: unseated default beside it: that clause says "its controller's next untap
#: step", which the step finds by construction, and this one says **your** —
#: the ability's controller. A land that changes hands in between waits for the
#: step the card named, not for its new controller's.
RETURN_AT_NEXT_UNTAP_SEAT = "return_to_hand_at_next_untap_seat"


@effect_handler("return_self_instead_of_untapping")
def return_self_instead_of_untapping(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"During your next untap step, as you untap your permanents, return this
    land to its owner's hand." (Undiscovered Paradise.)

    This step only **arms** the effect; the return happens a step later, inside
    the untap step, through the ``would_untap`` replacement. Performing it here
    would be an ordinary self-bounce and the land would never produce the mana
    its own ability just added.

    A marker on the permanent rather than a delayed trigger, because the untap
    step gives nobody priority (CR 502.4): a delayed ability would untap the
    land, wait for the upkeep, and hand its controller a free untapped land for
    the turn — which is the one thing the card is printed to deny.

    An ability whose source has already left the battlefield arms nothing;
    CR 400.7 makes whatever comes back a different object, and this effect
    named the one that is gone.
    """
    source = context.source_permanent
    if source is None or not game.is_on_battlefield(source):
        game.log.append(f"{context.card.name}: nothing left to return at untap")
        return True, "resolved"
    source.metadata[RETURN_AT_NEXT_UNTAP_SEAT] = game.players.index(context.caster)
    game.log.append(
        f"{context.card.name} will return to its owner's hand instead of untapping"
    )
    return True, "resolved"
