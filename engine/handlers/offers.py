"""An **offer** — "you may", "each player may", "unless <player> pays" — and
what arming one asks: who it is made to, whether they could take it, and what
it charges.

``control_flow.may`` makes the offer and ``control_flow._offer_to_seat`` arms
one seat's copy of it; both stay beside the step runner they run the offer's
branches through. What they ask is here:

* :func:`_offered_seats` — which seats a printed actor names, in the order they
  answer (CR 101.4), with the two "the player who revealed …" superlatives it
  reads (Goblin Game, Psychic Battle). It is the most-read helper the composers
  have: a dozen handler modules ask it who "each player" is.
* :func:`_action_is_takeable` and :func:`_narrow_to_takeable_actions` —
  whether the offered seat could actually perform the action now, so an offer
  with nothing to give is never made, and a ``choose_one`` mode with nothing to
  give is withdrawn.
* :func:`_resolved_cost`, :func:`_resolved_life_cost`, :func:`_derived_cost`
  and :func:`_derived_cost_is_unpayable` — what an offered cost charges, read
  at resolution, and CR 118.6's unpayable cost.

And the two offers that are instructions of their own rather than a ``may``:
``unless_player_pays`` (a chain of opponents asked in turn, the effect riding
the last decline) and ``each_player_pays_any_mana``.

Split out of ``control_flow.py`` at the 2,000-line cap's split round. Nothing
here imports ``control_flow``: the one thing an offer needs from it, the step
runner, is needed by ``_offer_to_seat`` alone, and that stayed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..exiled_records import source_object
from ..named_counters import counters_on
from ..oracle_types import (MANA_PAID_BY_SEAT, REVEALED_TOP_CARDS_BY_SEAT,
                            OracleInstruction, SECRET_NUMBERS_BY_SEAT,
                            EVENT_SPELL_MANA_COST,
                            OTHER_THAN_EVENT_SUBJECT_PLAYER,
                            STACK_TARGET_CONTROLLER)
from ..mana_payment import mana_cost_label
from ._targets import attached_host, triggering_spell
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def _revealed_fewest_seats(game: Game, context: OracleExecutionContext) -> list[int]:
    """Every seat whose secret number is the least, in turn order. ("The
    player who revealed the fewest items", Goblin Game.)

    Read off the per-seat record the hiding step wrote earlier in this same
    resolution (CR 608.2h). **Only a seat that revealed a number is in the
    comparison** — the field is the players who were asked, which is
    :func:`_revealed_mana_value_leader`'s rule one function down and for its
    reason: a player who named nothing did not reveal the fewest of anything.

    A seat still in the game is all that is asked of it. One at or below 0
    life is in the game until state-based actions are next checked (CR 704.3),
    which is not until this resolution is over — so a seat the first loss took
    to zero is still a seat the second sentence can name.

    Returns the whole set, because the card's two sentences need both
    readings of it: one member is "the player who revealed the fewest", and
    several are the players "tied for fewest".
    """
    recorded = context.results.get(SECRET_NUMBERS_BY_SEAT) or {}
    named = {
        seat: int(number)
        for seat, number in recorded.items()
        if isinstance(seat, int)
        and 0 <= seat < len(game.players)
        and not game.players[seat].lost
    }
    if not named:
        return []
    least = min(named.values())
    return [
        seat for seat in _offered_seats(game, "each_player", context)
        if named.get(seat) == least
    ]


def _revealed_mana_value_leader(
    game: Game, context: OracleExecutionContext
) -> "int | None":
    """The seat whose revealed card has strictly the greatest mana value, or
    None. ("The player who reveals the card with the greatest mana value",
    Psychic Battle.)

    Read off the per-seat record "each player reveals the top card of their
    library" wrote earlier in this same resolution (CR 608.2h), never off the
    libraries again: CR 701.20a moved nothing, but the record is what says
    which cards *this* sentence is comparing, and a second look would compare
    whatever is on top by then.

    **Only a seat that revealed a card is in the comparison.** "The player who
    reveals the card with the greatest mana value" describes a player by a card
    they revealed, so a player whose library was empty revealed nothing and
    cannot be that player — however many others tie. One revealed card among
    three seats is the greatest of the cards revealed and names its revealer;
    no revealed card at all names nobody.

    **A tie names nobody** — the card prints it ("If two or more cards are
    tied for greatest, the target or targets remain unchanged"), and it is the
    same strictness :func:`_strict_leader` gives every other superlative here.
    Written out rather than routed through that function because its field is
    every living seat, and this comparison's field is the revealers.

    Mana value is the card's own (CR 202.3): a land's is 0 (CR 202.3a), an
    ``{X}`` in a library is 0 (CR 107.3g), and a split card's is both halves
    together (CR 709.4b) — which is what the whole card's ``cmc`` already
    holds, the record being of the card in the library and never of a face.
    """
    revealed = context.results.get(REVEALED_TOP_CARDS_BY_SEAT) or {}
    values = {
        seat: int(getattr(card, "cmc", 0) or 0)
        for seat, card in revealed.items()
        if isinstance(seat, int)
        and 0 <= seat < len(game.players)
        and not game.players[seat].lost
        and card is not None
    }
    if not values:
        return None
    best = max(values.values())
    leaders = [seat for seat, value in values.items() if value == best]
    return leaders[0] if len(leaders) == 1 else None


def _exiled_cards_still_in_exile(game: Game, context) -> list:
    """The cards "that card" names behind an exile step of this same effect,
    less any that have left exile since — ``put_exiled_cards_into_zone``'s own
    two readers (the scratchpad, and the copy a delayed ability froze), so an
    offer of that step and the step itself cannot disagree about what is there.
    """
    recorded = (
        (context.trigger_context or {}).get("exiled_cards")
        or context.results.get("exiled_cards")
        or ()
    )
    return [
        card for card in recorded
        if any(held is card for player in game.players for held in player.exile)
    ]


def _own_pile_can_supply(player, payload: dict, context) -> bool:
    """Whether *player*'s own graveyard holds what an unannounced pick out of
    it owes — the **printed count** of cards the payload admits, less the one
    slot "other than this card" takes out.

    Through ``graveyard_slots_matching``, the reader the pick prompt itself
    asks, so the offer and the prompt it leads to agree on what the pile
    holds. The count is the point for Carrion Wurm's "exile **three** cards"
    — a pile of two cannot take the offer — and the exclusion is the point
    for Ichorid, whose own card is not a card it may exile. "Up to" owes one
    card, which is what this gate asked of every pick before it counted: an
    offer over a pile holding nothing it names is a question with one answer.
    """
    from ._filters import graveyard_slots_matching

    owed = 1 if payload.get("up_to") else max(1, int(payload.get("count", 1) or 1))
    return len(graveyard_slots_matching(
        payload, player.graveyard, getattr(context, "card", None)
    )) >= owed


def _action_is_takeable(
    game: Game, player, instruction: OracleInstruction, source, context=None,
) -> bool:
    """Whether *player* could actually perform this instruction right now.

    A kind is asked here because its "nothing to give" case is real and
    checkable; everything else answers True, which is what the engine did for
    all of them before this existed. A kind added here has to be one whose
    emptiness is a fact rather than a guess, because a wrongly-False answer
    withdraws an offer the card makes.

    **This is also the answer to "you may X. If you do, Y" on an empty X**, and
    it is the better half of that question rather than a second one. CR 608.2d
    offers a choice; an action nobody could take is not one of the things being
    offered, so the offer is not made, the rider does not fire, and the decline
    branch (a "…unless you pay" penalty) still applies. Asking *before* the
    prompt rather than measuring the action afterwards is what lets one rule
    serve both — and it is why this table is a registry of kinds and not a
    branch in :func:`may`.

    *context* is the resolution the offer sits inside, for the two kinds whose
    emptiness is about a zone the *event* named rather than the offered seat's
    own board. It is optional so no existing caller changes; a kind that needs
    it and does not get it answers True, which is the direction that keeps an
    offer the card makes.
    """
    from ._filters import _card_matches_filter

    if instruction.kind == "sacrifice_matching_permanent":
        exclude = source if instruction.payload.get("exclude_self") else None
        if instruction.payload.get("exclude_attached_host"):
            # "…unless they sacrifice **another** creature of their choice."
            # (Unnatural Hunger.) The permanent "another" is measured against
            # is the Aura's host, not the Aura — and this gate has to leave out
            # exactly what the charge will, or the offer is made for a price
            # the handler then refuses to take: accepted, nothing sacrificed,
            # and the printed penalty skipped. (``attached_host`` is the module
            # import: a function-local one here made the name local to the
            # whole function, and the Curse Artifact branch below raised
            # UnboundLocalError reading it.)
            exclude = attached_host(game, source)
        # The printed count, not merely "at least one": "unless you sacrifice
        # **two** Swamps" (Mold Demon) is an offer a player with one Swamp
        # cannot take, and accepting it would run the cost half-paid and skip
        # the penalty the card prints for not paying it.
        return len(game._sacrifice_candidate_indices(
            player, dict(instruction.payload.get("filter") or {}), exclude
        )) >= int(instruction.payload.get("count", 1))
    # "…unless the player **puts a -1/-1 counter on a creature they control**"
    # (Thelon's Chant, Tourach's Chant). A price paid out of the offered seat's
    # own board, so a seat with no creature cannot pay it — and accepting anyway
    # would buy off the damage for nothing, which is the same failure the
    # sacrifice above is gated on. Only the pick *from the offered seat's own
    # battlefield* is asked: a choice drawn from anywhere else is not a price
    # this player pays, and answering False for it would withdraw an offer the
    # card makes.
    if instruction.kind == "sacrifice_permanents_totalling":
        # "…unless you sacrifice any number of creatures with **total power 12
        # or greater**" (Phyrexian Dreadnought). A board that cannot reach the
        # floor is a real and checkable "nothing to give", and the whole board
        # is the most that could ever be offered — so if every candidate
        # together falls short, the offer is not made and the penalty stands.
        payload = dict(instruction.payload)
        payload["_source"] = source if payload.get("exclude_self") else None
        seat = game.players.index(player)
        every = game.aggregate_sacrifice_candidates(seat, payload)
        return game.aggregate_sacrifice_total(
            every, str(payload.get("characteristic") or "power")
        ) >= int(payload.get("at_least", 0))
    if instruction.kind == "choose_permanent":
        if instruction.payload.get("controlled_by") != "chooser":
            return True
        from ..subject_filters import subject_matches

        seat = game.players.index(player)
        described = dict(instruction.payload.get("filter") or {})
        return any(
            subject_matches(game, perm, described, observer=seat, source=source)
            for perm in game.controlled_by(seat)
        )
    # "…**unless you return two Forests you control** to their owner's hand."
    # (Bull Elephant; the Karoo land cycle, Ovinomancer and Waterspout Djinn
    # print the same price with other nouns and counts.) The plural of the pick
    # above, and the printed count is the whole point of asking: a player with
    # one Forest cannot take a two-Forest offer, and accepting it would run the
    # price half-paid and skip the sacrifice the card prints for not paying it —
    # which is Mold Demon's rule one family over, stated for a bounce.
    #
    # Only the pick from the offered seat's *own* battlefield is answered, for
    # the reason the singular states: a choice drawn from anywhere else is not a
    # price this player pays, and a wrongly-False answer withdraws an offer the
    # card makes.
    # "Exile the top card of your library. **You may put that card into your
    # hand** …" (Tainted Pact, on an empty library.) The card is the one an
    # earlier step of this effect exiled, so with none recorded — or with the
    # recorded one gone from exile since — there is nothing to take and nothing
    # to offer. The same two places ``put_exiled_cards_into_zone`` reads, so
    # what is offered and what would move are one answer.
    if instruction.kind == "put_exiled_cards_into_zone" and context is not None:
        return bool(_exiled_cards_still_in_exile(game, context))
    if instruction.kind == "choose_permanents":
        if instruction.payload.get("controlled_by") != "chooser":
            return True
        from ..subject_filters import subject_matches

        seat = game.players.index(player)
        described = dict(instruction.payload.get("filter") or {})
        owed = max(int(instruction.payload.get("at_least", 0) or 0), 1)
        return sum(
            1 for perm in game.controlled_by(seat)
            if subject_matches(game, perm, described, observer=seat, source=source)
        ) >= owed
    if instruction.kind == "exile_graveyard_position":
        # "…unless you **exile the top creature card of your graveyard**"
        # (Barrow Ghoul, Circling Vultures). A pile with no creature card in it
        # is a real and checkable "nothing to give": accepting would exile
        # nothing and still skip the sacrifice the card prints for not paying,
        # which is the same failure the sacrifice above is gated on.
        #
        # Only the offered seat's **own** pile is answered. "Target player's
        # graveyard" is not a price this player pays, and answering False for
        # it would withdraw an offer the card makes — the same narrowing
        # ``ante_top_card`` below states for its own seat.
        from ..graveyard_order import positions_named

        if instruction.payload.get("owner", "you") != "you":
            return True
        return bool(positions_named(player.graveyard, dict(instruction.payload)))
    if instruction.kind == "ante_top_card":
        # "…may **ante the top card of their library**" (Amulet of Quoz,
        # Rebirth, Timmerian Fiends). An empty library is a real and checkable
        # "nothing to give": accepting would ante nothing and still skip the
        # penalty the card prints for not anting, which is the same failure the
        # sacrifice above is gated on.
        #
        # Only the "that player" spelling is answered, because only there is the
        # anteing seat the offered seat. A sweep over every player is not a
        # price this one pays, and answering False for it would withdraw an
        # offer the card makes.
        if instruction.payload.get("players") != "that_player":
            return True
        return bool(player.library)
    if instruction.kind == "discard_controller_cards":
        described = dict(instruction.payload.get("filter") or {})
        return any(
            _card_matches_filter(card, described, game=game, owner=player)
            for card in player.hand
        )
    # "Sacrifice it **unless you return a basic land card from your graveyard to
    # your hand**." (Harvest Wurm.) The graveyard twin of the hand question
    # above, and it fails the same way: the handler returns as many as it can
    # (CR 608.2), so a graveyard with no card the phrase names returned
    # **nothing**, the price counted as paid and the sacrifice the card prints
    # for not paying it never happened — the Wurm stayed on the battlefield for
    # free. The narrowing is the whole of it here: a graveyard full of creatures
    # and no basic land is not "nothing to give" by size, only by description,
    # which is why the offered seat's pile is asked through
    # ``graveyard_card_matches`` — the one predicate the picker and the handler
    # already share, so all three agree about which cards count.
    #
    # Only the several-targets spelling is skipped: with a chosen list the
    # picker collects the slots and its own floor decides, exactly as the
    # permanent-set price one screen up leaves the count to the prompt.
    if instruction.kind == "return_creature_from_graveyard_to_hand":
        from ._filters import graveyard_card_matches

        if instruction.payload.get("targets"):
            return True
        return any(
            graveyard_card_matches(instruction.payload, card)
            for card in player.graveyard
        )
    # "You may exile a land card from your graveyard. **If you do**, …"
    # (Forgotten Harvest.) The exile twin of Harvest Wurm's price above, and
    # the same failure without it: a pile with no land card exiles nothing and
    # the rider runs anyway. Only the unannounced pick from the offered seat's
    # own pile; every other spelling keeps its offer.
    if instruction.kind == "exile_cards_from_graveyard":
        from ._filters import graveyard_card_matches

        pile_owner = instruction.payload.get("graveyard_owner")
        if pile_owner == "damaged_player" and not instruction.payload.get("up_to"):
            # "…you may exile **target card from that player's graveyard**."
            # (Zombie Cannibal.) One card out of the pile the firing event
            # named, so an empty pile is a real "nothing to exile" — there is
            # no legal target, and asking "you may?" and then offering a pick
            # with no answer is two prompts a seat has to dismiss. "Up to"
            # keeps its offer (Rysorian Badger): zero is one of its answers.
            # With no recorded seat the offer stands, the direction this
            # function's docstring names.
            seat = (
                (context.trigger_context if context is not None else None) or {}
            ).get("defending_player_index")
            if isinstance(seat, int) and 0 <= seat < len(game.players):
                return any(
                    graveyard_card_matches(instruction.payload, card)
                    for card in game.players[seat].graveyard
                )
            return True
        if (
            # "you" and the seat an offer was made to (Gravestorm) are both
            # *player* here — the offered seat picking from its own pile.
            pile_owner not in ("you", "offered_player")
            or instruction.payload.get("targets")
        ):
            return True
        return _own_pile_can_supply(player, instruction.payload, context)
    # "…sacrifice this creature unless you **put two cards from your
    # graveyard on the bottom of your library**." (Gurzigost.) The exile's
    # pick with another destination, and the same "nothing to give": a pile
    # one card short cannot cover the price, so the offer is not made and the
    # sacrifice stands.
    if instruction.kind == "put_chosen_graveyard_cards_on_library_bottom":
        return _own_pile_can_supply(player, instruction.payload, context)
    # "Target player discards a card unless they **put a card from their hand on
    # top of their library**." (Tainted Specter.) An empty hand is a real and
    # checkable "nothing to give": the handler underneath moves as many cards as
    # it can (CR 608.2), so an offer taken from an empty hand would put nothing
    # back and still skip the discard the card prints for not putting one back.
    # The printed count, for Mold Demon's reason — a hand one card short cannot
    # cover the offer either.
    #
    # Only the ``target`` spelling, which is the one whose recipient is the
    # offered seat. A put-back out of the *caster's* hand is not a price this
    # player pays, and answering False for it would withdraw an offer the card
    # makes.
    # "Sacrifice it **unless you discard a card at random**." (Balduvian Horde.)
    # The random half of the same question ``discard_controller_cards`` answers
    # above, and it was the half nobody asked: an empty hand discarded **zero
    # cards at random**, the offer counted as taken, and the Horde stayed on the
    # battlefield for free. CR 601.2h asks what a player is *able* to do, and
    # discarding a card you do not have is not one of them.
    #
    # Only the ``caster`` spelling — the seat an offer with actor "you" is made
    # to. A random discard out of somebody else's hand is not a price this
    # player pays, and answering False for it would withdraw an offer the card
    # makes. A computed count answers True for the same reason: this predicate
    # has no ``x_value``, and a wrongly-False answer is the one that costs a
    # card its ability.
    # "…unless that player **discards a card**." (Forbidden Ritual.) The
    # chosen half of the same question the random one below answers, and it was
    # missing for the same reason it was missing there: the handler discards as
    # many as it can (CR 608.2), so an empty hand discarded **nothing**, the
    # price counted as paid and the 2 life the card prints for not paying it was
    # never lost. CR 601.2h asks what a player is *able* to do.
    #
    # Only the ``target`` spelling — the one whose discarding seat is the
    # resolution's chosen player, which is the seat an offer to "that player" or
    # to "target opponent" is made to. ``who: "defending_player"`` names a seat
    # the combat froze and is somebody else's hand, so it answers True, exactly
    # as ``put_hand_cards_on_library`` above and ``discard_x_target_cards``
    # below decline the spellings that are not the offered seat's: a
    # wrongly-False answer withdraws an offer the card makes.
    if instruction.kind == "discard_target_cards":
        amount = instruction.payload.get("amount", 1)
        if instruction.payload.get("who") is not None or not isinstance(amount, int):
            return True
        return len(player.hand) >= amount
    if instruction.kind == "discard_x_target_cards":
        amount = instruction.payload.get("amount", 1)
        if instruction.payload.get("who") != "caster" or not isinstance(amount, int):
            return True
        return len(player.hand) >= amount
    # "**You may sacrifice this enchantment** and pay {2}{G}{G}." (Preferred
    # Selection.) A source that has left the battlefield cannot be sacrificed
    # (CR 701.21a), and the handler underneath treats "nothing to sacrifice" as
    # a no-op — so the offer would be takeable, the mana charged, and the card
    # taken into hand for a price half of which was never paid.
    if instruction.kind == "sacrifice_self":
        return source is not None and game.is_on_battlefield(source)
    if instruction.kind == "put_hand_cards_on_library":
        if instruction.payload.get("recipient") != "target":
            return True
        if instruction.payload.get("whole_hand"):
            return bool(player.hand)
        return len(player.hand) >= int(instruction.payload.get("amount", 1) or 1)
    # "You may remove a vitality counter from this Aura. **If you do**, you gain
    # 1 life." (Living Artifact.) With no counter there is nothing to remove, so
    # the offer is not made and the if-you-do branch never runs. The handler
    # underneath already treats removing from zero as a no-op — which is right
    # for a mandatory removal and, on its own, would have let this card gain
    # life off an empty Aura for as long as it stayed on the battlefield.
    if instruction.kind == "remove_counter_from_self":
        if source is None:
            return False
        # "…sacrifice this creature **unless you remove a +1/+1 counter from
        # it**." (Junk Golem.) A *permanent* that left while this ability
        # waited has no counter to give: CR 122.2 — counters "are not retained
        # if that object moves from one zone to another" — so the removal is
        # an action nobody can take, however many the departed object still
        # carries in memory. Without it the offer was made over a Golem in a
        # graveyard, and a Living Artifact destroyed in response to its own
        # trigger still paid out its life. Only a permanent is asked: the
        # other source this reader answers for is a card in exile (All
        # Hallow's Eve), which is where its counters are.
        if context is not None and source is context.source_permanent:
            if not game.is_on_battlefield(source):
                return False
        counter = str(instruction.payload.get("counter", "doom"))
        # The same reader the removal itself uses (``named_counters.counters_on``),
        # so the offer and the action cannot disagree about where the counters
        # are — the whole reason ``exiled_records.source_object`` exists.
        return counters_on(source, counter) > 0
    # "Each player **may** ante the top card of their library. If a player does,
    # that player's life total becomes 20." (Rebirth.) An empty library has no
    # top card, so there is no ante to offer — and taking the offer anyway would
    # run the if-you-do branch off an ante that never happened, handing a player
    # 20 life for nothing. The offered seat is the anting seat: the offer names
    # one player and the ante comes off that player's own library (CR 407.4).
    if instruction.kind == "ante_top_card":
        return bool(player.library)
    # "…unless they sacrifice that artifact" (Curse Artifact). An Aura that has
    # come unattached has nothing to give up, so the offer is not made and the
    # penalty applies — the alternative being an offer the player could accept
    # and then keep their life total *and* their artifact, because the handler
    # underneath treats "nothing attached" as a no-op. Read through the same
    # helper the handler reads, ``attached_host``: an Aura that left with its
    # trigger on the stack still names the permanent it was on (CR 608.2h), so
    # the offer stands while that permanent does.
    if instruction.kind == "sacrifice_attached_permanent":
        return attached_host(game, source) is not None
    # "**Pay 4 life** or put the card on top of your library." (Sylvan
    # Library.) CR 119.4: a player may pay life only with a life total at least
    # the amount, so at 3 life the payment is not one of the two things this
    # sentence lets its controller choose between. Asked through the handler's
    # own predicate, so the alternative that is offered and the alternative
    # that is performed are decided by one rule.
    if instruction.kind == "pay_life":
        from .life_and_game import can_pay_life

        return can_pay_life(player, int(instruction.payload.get("amount", 0)))
    # "You may put **the top creature card of defending player's graveyard**
    # onto the battlefield under your control. **If you do**, this creature
    # assigns no combat damage this turn." (Bone Dancer.) A pile with no
    # creature card in it is a real and checkable "nothing to give", and this
    # is the card a SET_PLAYBOOK.md Known-gaps entry named until this closed it:
    # accepting over an empty
    # graveyard reanimated nothing and still marked the attacker as assigning
    # no combat damage, which is the rider firing on an action that did not
    # happen. Reproduced before it was fixed.
    #
    # The pile is the one the *combat* froze (CR 506.2), read through the same
    # key and the same scan the handler uses (``graveyard_order.positions_named``)
    # — so the offer and the action cannot disagree about which card is on top.
    # Any other spelling, and a trigger that recorded no defender, answers True:
    # a wrongly-False answer withdraws an offer the card makes.
    if instruction.kind == "reanimate_graveyard_position":
        from ..graveyard_order import positions_named

        if instruction.payload.get("graveyard_owner") != "defending_player":
            return True
        seat = (getattr(context, "trigger_context", None) or {}).get(
            "trigger_defending_player_index"
        )
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return True
        return bool(
            positions_named(
                game.players[seat].graveyard, dict(instruction.payload)
            )
        )
    # "You may **exile all cards from your hand** face down. **If you do**, put
    # all other cards you own exiled with this enchantment into your hand."
    # (Duplicity.) An empty hand exiles nothing and the rider then hands the
    # whole exiled pile back for free — the card's entire price is the trade,
    # so this is the same failure as Bone Dancer's with the reward on the other
    # side of it.
    #
    # Only the "all" quantifier. "Exile **any number of** cards from your hand"
    # (Scroll Rack) legally answers zero, so an empty hand is a real answer
    # there rather than an offer nobody could take.
    if instruction.kind == "exile_hand_pile":
        if instruction.payload.get("quantifier") != "all":
            return True
        described = dict(instruction.payload.get("card_filter") or {})
        return any(
            _card_matches_filter(card, described) for card in player.hand
        )
    # "You may **exile a card from your hand**. If you do, untap this land."
    # (Forsaken City.) A hand with no eligible card has nothing to give, which
    # is the rule the handler already states for itself — "nothing eligible is
    # an offer never made rather than an offer declined" — asked here, through
    # the same candidate list its prompt offers, so the seat is not asked a
    # question whose only honest answer is no.
    if instruction.kind == "exile_chosen_card_from_hand":
        from .hand import exile_from_hand_candidates

        return bool(exile_from_hand_candidates(game, instruction.payload, player))
    return True


def _narrow_to_takeable_actions(
    game: Game, player, steps: tuple, context: OracleExecutionContext
) -> tuple[tuple, bool]:
    """*steps* with any unofferable alternative removed, and whether an offer
    remains to make at all.

    A bare step that cannot be taken makes the whole offer unmakeable, as it
    always has. A ``choose_one`` loses just the modes that cannot be taken, and
    becomes unmakeable only when it has none left.
    """
    # "The source" is a permanent or a card in exile — one reader for both, so
    # an offer made from exile is gated on the same state the action reads.
    source = source_object(context)
    narrowed = []
    for step in steps:
        if step.kind == "choose_one":
            modes = tuple(
                mode for mode in (step.payload.get("modes") or ())
                if _action_is_takeable(
                    game, player, mode["instruction"], source, context
                )
            )
            if not modes:
                return (), False
            narrowed.append(
                OracleInstruction(step.kind, step.value, {**step.payload, "modes": modes})
            )
            continue
        if not _action_is_takeable(game, player, step, source, context):
            return (), False
        narrowed.append(step)
    return tuple(narrowed), True


def _resolved_life_cost(game, printed, context: OracleExecutionContext) -> int:
    """How much life an offered life cost charges, read at resolution.

    A printed digit arrives as an int. "life equal to **its** toughness"
    (Essence Vortex) arrives as an ``object_characteristic`` spec, because
    CR 613 makes toughness computed and a creature pumped after the spell was
    announced has a different one — so the number is taken here, through the
    evaluator every other resolution-time count shares, rather than at lowering.

    Zero when the spec names an object the resolution no longer has, which is
    the honest reading: nothing is charged, and the caller's decline branch has
    nothing left to act on either.
    """
    if not printed:
        return 0
    if isinstance(printed, dict):
        from ._amounts import count_from_payload

        return max(0, count_from_payload(game, context, printed))
    return max(0, int(printed))


def _resolved_cost(printed, context: OracleExecutionContext, game=None) -> dict:
    """An offered cost with its variable amount read at resolution.

    "You may pay {X}, where X is the number of +1/+1 counters on it."
    (Primordial Ooze.) The where-clause has already become ``context.x_value``
    by the time any handler runs, so the cost is a symbol dict like every other
    — one of whose amounts is the string "x" until here. Resolved in the
    handler rather than at lowering because CR 608.2 takes the count when the
    ability *resolves*: a counter added between the trigger and its resolution
    changes the number.
    """
    printed = dict(printed or {})
    # "…unless you pay **its mana cost reduced by {2}**" (Flash). The cost is
    # not printed at all: it is the mana cost of the permanent an earlier step
    # of the same sentence put onto the battlefield, less what the card does
    # print. Read here rather than at lowering for the where-clause's reason
    # above — the object does not exist until the step in front of this one
    # resolves, and which card the seat picked is not knowable before they pick.
    key = printed.pop("cost_from", None)
    if key is not None:
        return _derived_cost(key, printed.pop("reduced_by", None), context, game)
    resolved = {}
    for symbol, amount in printed.items():
        if amount == "x":
            amount = max(0, int(context.x_value or 0))
        resolved[symbol] = int(amount)
    return {symbol: amount for symbol, amount in resolved.items() if amount}


def _derived_cost(
    key: str, reduction, context: OracleExecutionContext, game=None,
) -> dict:
    """The mana cost of the permanent recorded under *key*, less *reduction*.

    CR 601.2f's arithmetic in the one direction this engine implements it:
    a reduction applies to the **generic** part first and never takes a
    coloured pip off, which is the rule for every cost reduction in Magic
    (CR 601.2f: coloured requirements are unaffected by a generic reduction).
    Flash's "{2}" off a {3}{G} creature is {1}{G}, and off a {G}{G} creature is
    {G}{G}.

    Nothing recorded — the seat declined the offer in front of this one, or the
    permanent has left — is a cost of nothing, and the offer is not made. The
    caller then runs the decline branch, which is right either way: with no
    permanent there is nothing to sacrifice.
    """
    from ..mana_payment import mana_cost_from_symbols

    recorded = context.results.get(key)
    permanent = (
        game.permanent_by_id(recorded)
        if isinstance(recorded, int) and game is not None
        else None
    )
    if permanent is None:
        return {}
    cost = mana_cost_from_symbols(permanent.effective_card.mana_cost or "")
    if not cost:
        return {}
    cost = dict(cost)
    generic_off = int(dict(reduction or {}).get("generic", 0) or 0)
    if generic_off:
        cost["generic"] = max(0, int(cost.get("generic", 0)) - generic_off)
    return {symbol: amount for symbol, amount in cost.items() if amount}


@effect_handler("each_player_pays_any_mana")
def each_player_pays_any_mana(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Each player may pay any amount of mana." (Liege of the Hollows.)

    One ``pay_any_amount`` prompt per seat in turn order (CR 101.4), the shape
    ``each_player_discards_up_to_cards`` and ``each_player_draws_up_to_cards``
    already have one zone each over — and here for their reason: the "may" and
    the amount are one decision, since zero is a legal answer to "any amount",
    and the sentence behind the offer reads every seat's answer.

    Every seat is recorded, including one that pays nothing, because "the amount
    of mana **they** paid this way" is a number for every player and a seat the
    record never mentions has to read as zero rather than as a missing key. The
    scratchpad rides the prompt, so what is written is what the seat actually
    paid rather than what its board could have covered.
    """
    caster_index = game.players.index(context.caster)
    if instruction.payload.get("actor") == "each_opponent":
        seats = [s for s in game.opponents_of(caster_index) if not game.players[s].lost]
    else:
        # CR 101.4: the active player first, then the rest in turn order.
        count = len(game.players)
        active = game.active_player_index or 0
        seats = sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % count, i),
        )
    context.results.setdefault(MANA_PAID_BY_SEAT, {})
    for seat in seats:
        context.results[MANA_PAID_BY_SEAT][seat] = 0
        game.arm_pending_choice(
            "pay_any_amount", seat,
            card_name=context.card.name if context.card is not None else "",
            _results=context.results,
        )
        game.log.append(f"{game.players[seat].name} may pay any amount of mana")
    return True, "resolved"


def _offered_seats(
    game: Game, actor: str, context: OracleExecutionContext,
    start_seat: int | None = None,
) -> list[int]:
    """Which seats the offer is made to, in the order they answer it.

    "Each player may …" (Rebirth) is one decision per player, not one decision
    somebody makes for everybody — so the actor is a *set* of seats and
    ``control_flow.may`` arms one prompt for each. CR 101.4: the seats are asked
    in turn order starting with the active player, which is also the order the
    queue drains them in.

    A player who has already left the game is nobody (CR 800.4a).
    """
    if isinstance(actor, int):
        # A seat a **handler's own loop** is on rather than a word a card
        # printed — Tariff's paragraph builds one offer per player and names
        # the seat outright, because "each player" there is a number of *pairs*
        # of steps that only the resolution knows. A seat that has left the
        # game is nobody (CR 800.4a), exactly as below.
        return (
            [actor]
            if 0 <= actor < len(game.players) and not game.players[actor].lost
            else []
        )
    if actor == "each_player":
        count = len(game.players)
        # "**Starting with you**, each player may …" (Eureka) names the first
        # seat outright. Without it CR 101.4's default stands: the active
        # player first. The same seat for a sorcery, which is why the argument
        # exists rather than the caller simply relying on the default.
        active = (game.active_player_index or 0) if start_seat is None else start_seat
        return sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % count, i),
        )
    if actor == "each_opponent":
        return [
            i for i in game.opponents_of(game.players.index(context.caster))
            if not game.players[i].lost
        ]
    if actor == "controller":
        # "… unless **its controller** pays life equal to its toughness."
        # (Essence Vortex.) The seat is read off the permanent the sentence
        # targeted, through the control seam — never off ``context.target``,
        # which for a spell that targets a creature is not a player at all.
        # With the target gone by resolution there is nobody to offer, and the
        # caller's ``otherwise`` branch has nothing left to destroy either.
        #
        # The innermost binding, for `bound_permanent`'s stated reason: inside
        # "for each of those creatures, **its controller** may pay {1} or {2}"
        # (Winter's Chill) the possessive names the creature the iteration is
        # on, and the resolution's own target list is all of them at once.
        from ._targets import bound_permanent

        perm = bound_permanent(game, context, predicate=lambda p: True)
        if perm is None:
            return []
        seat = game.controller_index_of(perm)
        return [] if seat is None else [seat]
    if actor == "attached_controller":
        # "…**its controller** may have it deal damage…" (Farrel's Mantle).
        # The seat that controls the permanent this Aura is attached to, which
        # is the object the trigger's own condition named — read off the
        # attachment rather than off the resolution's target, which for this
        # ability is the creature being *bitten* and belongs to the other side.
        from ._targets import attached_host

        host = attached_host(game, context.source_permanent)
        seat = game.controller_index_of(host) if host is not None else None
        return [] if seat is None else [seat]
    if actor == STACK_TARGET_CONTROLLER:
        # "Counter target instant or sorcery spell unless **its controller**
        # has Molten Influence deal 4 damage to them." The controller of the
        # spell this object targeted, read off the stack object itself
        # (CR 112.2: a spell's controller is the player who cast it) rather
        # than off ``context.target``, which for an announcement that named a
        # spell and no player is whatever seat a targetless resolution
        # defaults to - the caster's opponent, even when the spell being
        # countered is the caster's own.
        #
        # The object is the one ``counter_top_stack_spell`` will counter if
        # the offer is declined, found the way that handler finds it: the
        # named spell while it is still on the stack (by identity), nothing
        # once a named spell has left (CR 608.2b - nobody is asked about a
        # counter that cannot happen), and the top of the stack for the
        # headless caller that named none.
        #
        # One reader with the recipients that name the same seat after the
        # counter has run (``_targets.stack_target_controller_seat``).
        from ._targets import stack_target_controller_seat

        seat = stack_target_controller_seat(game, context, spells_only=True)
        if seat is None or game.players[seat].lost:
            return []
        return [seat]
    if actor == "target_opponent":
        # "**Target opponent** may ante the top card of their library."
        # (Amulet of Quoz.) The seat the ability chose, held in
        # ``context.target`` — and verified rather than trusted, because
        # ``references.parse_player_ref`` gives the bare article "an opponent"
        # this same kind and that phrase chooses nobody. A recorded seat that
        # is the ability's own controller, or missing, is not an opponent this
        # ability targeted, and an offer made to nobody is the honest answer —
        # the same one the defending-player branch below gives for a combat
        # that has moved on.
        chosen = context.target
        if chosen is None or chosen is context.caster or chosen.lost:
            return []
        return [game.players.index(chosen)]
    if actor == "target_player":
        # "**Unless target player pays {3}**, …" (Rhystic Syphon.) The branch
        # above without its opponent check: any seat may be the target,
        # the caster included. Nobody chosen, or gone, is nobody offered.
        chosen = context.target
        if chosen is None or chosen not in game.players or chosen.lost:
            return []
        return [game.players.index(chosen)]
    if actor == "defending_player":
        # CR 506.2, frozen by the fire site (CR 603.10): which seat is being
        # attacked is a fact about the combat, and by the time this trigger
        # resolves the combat may have moved on. The lowering admits the word
        # only under an event that stamps it, so an absent key here is a
        # combat that ended, not a card nobody wired up — and no prompt is the
        # right answer then.
        seat = (context.trigger_context or {}).get("trigger_defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return []
        return [] if game.players[seat].lost else [seat]

    if actor == "revealed_greatest_mana_value":
        # "…**the player who reveals the card with the greatest mana value**
        # may …" (Psychic Battle.) The seat the per-seat reveal in front of
        # this offer put strictly ahead; a tie, or nothing revealed, is nobody.
        seat = _revealed_mana_value_leader(game, context)
        card_name = context.card.name if context.card is not None else "Effect"
        if seat is None:
            # Said out loud, because the reveal just showed every player's
            # card and "nothing happened" needs its reason beside it.
            game.log.append(
                f"{card_name}: no one card revealed has the greatest mana value"
            )
            return []
        game.log.append(
            f"{card_name}: {game.players[seat].name} revealed the card with "
            "the greatest mana value"
        )
        return [seat]
    if actor in ("revealed_fewest", "each_revealed_fewest"):
        # "**The player who revealed the fewest items** then loses half their
        # life, rounded up. If two or more players are tied for fewest, each
        # loses half their life, rounded up." (Goblin Game.) The described
        # seat is strict, like every superlative here — a tie names nobody —
        # and the card's tie sentence widens it to every seat holding the
        # least, which the grammar folds into the second spelling.
        holders = _revealed_fewest_seats(game, context)
        card_name = context.card.name if context.card is not None else "Effect"
        if actor == "revealed_fewest" and len(holders) != 1:
            if holders:
                game.log.append(
                    f"{card_name}: no one player revealed the fewest"
                )
            return []
        if holders:
            game.log.append(
                f"{card_name}: "
                + ", ".join(game.players[seat].name for seat in holders)
                + " revealed the fewest"
            )
        return holders
    if actor == "damaged_player":
        # "…unless they pay {2} before that step" (Sabertooth Cobra). The seat
        # the damage event froze (``defending_player_index``, stamped by
        # ``damage_events._announce`` and carried across the delay in the
        # entry's ``captured``) — the same record the poison counter behind the
        # offer reads, so the player asked for the price and the player who
        # takes the counter for refusing it are one seat. Nobody recorded means
        # nobody is offered, which is the honest outcome the branches around
        # this one already give.
        seat = (context.trigger_context or {}).get("defending_player_index")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return []
        return [] if game.players[seat].lost else [seat]
    if actor == "event_subject_player":
        # "…unless **that player** pays {4}" (Mystic Remora). The seat the
        # firing event *is about*, frozen by the fire site (CR 603.10) — one
        # step nearer than the controller branch below, which names the seat
        # that controlled an object the event was about. Nobody recorded means
        # nobody is offered.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return []
        return [] if game.players[seat].lost else [seat]
    if actor == "event_subject_controller":
        # "…unless the player puts a -1/-1 counter on a creature they control"
        # (Thelon's Chant, Tourach's Chant). The seat that controlled what the
        # firing event was about, frozen by the fire site (CR 603.10) — the same
        # read the damage recipient beside it takes, so the player offered the
        # price and the player who takes the damage for refusing it are one
        # answer. Nobody recorded means nobody is offered, which is the honest
        # outcome and the one the two branches above already give.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return []
        return [] if game.players[seat].lost else [seat]

    return [game.players.index(context.caster if actor == "you" else context.target)]


def _derived_cost_is_unpayable(printed, context: OracleExecutionContext, game) -> bool:
    """Whether an offer's cost is read off a permanent that **has no mana
    cost** — CR 118.6's unpayable cost.

    "…unless they pay that creature's mana cost" (Tariff) asked of a token or
    an animated land: CR 202.1b gives such an object no mana cost, and a cost
    based on it may not be paid at all. :func:`_derived_cost` answers that
    object with an empty dict, which every reader downstream takes for "no
    cost" — so the offer was made for free and the creature kept, the opposite
    of the rule.

    Asked through ``mana_payment.permanent_mana_cost``, the reader the upkeep
    toll of the same printed words ("unless you pay its mana cost", Pendrell
    Flux) uses, so ``{0}`` — a mana cost, and a payable one — is not caught by
    it. Nothing recorded is not this question: that is an offer with no
    permanent behind it, which keeps the answer :func:`_derived_cost` gives.
    """
    key = dict(printed or {}).get("cost_from")
    if key is None or game is None:
        return False
    recorded = context.results.get(key)
    permanent = game.permanent_by_id(recorded) if isinstance(recorded, int) else None
    if permanent is None:
        return False
    from ..mana_payment import permanent_mana_cost

    return permanent_mana_cost(permanent) is None


@effect_handler("unless_player_pays")
def unless_player_pays(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Unless an opponent pays {2}, gain control of target artifact …"
    (Scarwood Bandits.)

    An offer made to *another* seat, on the same ``optional_pay`` queue every
    other offer uses — and a chain rather than a batch: each opponent is asked
    in turn, and the ability's effect rides the **last** decline. Asking them
    all at once would arm several prompts whose answers could not see each
    other, and one payment has to stop the rest (CR 601.2b: once the cost is
    paid the clause is satisfied, and nobody else is asked).

    The chain is a prompt armed by *answering* an earlier one, which is how a
    sequence of decisions stays one resolution — the stack object is held until
    the last of them is answered (CR 608.2, CR 117.3b).

    ``paid`` is the chain with its polarity reversed — "Then **if any player
    pays {2}**, discard three cards" (Rhystic Scrying) — run by the payment
    that ends the chain, against the resolution's own context: the bare
    imperative is still the controller's, whoever paid.
    """
    payload = dict(instruction.payload)
    unpaid = tuple(payload.get("unpaid") or ())
    paid = tuple(payload.get("paid") or ())
    caster = context.caster
    if caster is None or caster not in game.players:
        return True, "resolved"
    caster_index = game.players.index(caster)
    priced_spell = None
    if dict(payload.get("cost") or {}).get("cost_from") == EVENT_SPELL_MANA_COST:
        # "…may pay **that spell's mana cost**." (Ice Cave.) Read off the spell
        # the trigger fired on, now — and on every link of the chain, since
        # each is this handler again and the spell can leave between two
        # answers. No spell left, or one with no mana cost (CR 118.6: an
        # unpayable cost), is a price nobody can pay: the chain ends as though
        # every seat had declined, which is what CR 118.6 makes of an offer no
        # player may take.
        priced_spell, cost = _event_spell_and_cost(game, context)
        if cost is None:
            for step in unpaid:
                game._execute_oracle_instruction(step, context)
            return True, "resolved"
    else:
        # "…unless any player pays {X}" (Soul Strings): the announced X, read
        # now.
        cost = _resolved_cost(payload.get("cost"), context, game)
    # Every seat the printed reference names, in the order they are asked. CR
    # 101.4 orders a multi-seat offer from the active player, so the chain
    # starts there rather than at seat 0 — the same order ``_offered_seats``
    # gives "each player may …", and the same order the queue drains.
    #
    # "**Any player** pays {3}" (Icy Prison) names the table, the ability's own
    # controller included; "an opponent pays {2}" (Scarwood Bandits) excludes
    # them. That is the only difference between the two, which is why it is a
    # payload key and not a second handler. A player who has left the game is
    # nobody (CR 800.4a), read off the engine's own state-based-action flag.
    #
    # "**Any other player** may pay …" (Ice Cave) is the third set: everyone
    # but the seat the firing event froze — the player who cast the spell —
    # which includes this ability's own controller whenever somebody else
    # cast. With no seat recorded the words are measured from nobody, and
    # nobody is asked.
    count = len(game.players)
    active = game.active_player_index or 0
    payer = payload.get("payer")
    excluded_seat = caster_index
    if payer == OTHER_THAN_EVENT_SUBJECT_PLAYER:
        excluded_seat = (context.trigger_context or {}).get("event_subject_player")
    seats = [
        index
        for index in sorted(
            range(count), key=lambda i: ((i - active) % count, i)
        )
        if not getattr(game.players[index], "lost", False)
        and (payer == "any_player" or index != excluded_seat)
        and not (
            payer == OTHER_THAN_EVENT_SUBJECT_PLAYER
            and not isinstance(excluded_seat, int)
        )
    ]
    asked = int(payload.get("asked_seats", 0))
    if asked >= len(seats):
        # Everyone declined (or there was nobody to ask), so the clause is not
        # bought off and the effect happens.
        for step in unpaid:
            game._execute_oracle_instruction(step, context)
        return True, "resolved"
    seat = seats[asked]
    # "…unless any player pays **5 life**." (Aether Rift.) CR 119.4: the prompt
    # carries the price as ``life_cost``, which is the field the payer's
    # "can you?" test and the charge both read — a seat below the amount is
    # asked and cannot say yes, and its answer is the decline that moves the
    # chain on.
    life_price = int(payload.get("life") or 0)
    game.arm_pending_choice(
        "optional_pay", seat,
        card_name=context.card.name if context.card is not None else "",
        cost=cost,
        life_cost=life_price,
        life=0,
        _source_permanent=context.source_permanent,
        # Paying ends the chain: no later seat is asked, and only what the
        # payment itself buys runs (nothing, for every toll but the reversed
        # one). ``_on_paid`` rather than ``_on_accept``, because the latter is
        # the *payer's* action and is gated on what the payer can do — and
        # Rhystic Scrying's discard is its controller's, whoever paid.
        _on_accept=(),
        _on_paid=paid,
        _on_decline=(
            OracleInstruction(
                "unless_player_pays", "", {**payload, "asked_seats": asked + 1}
            ),
        ),
        _on_reflexive=(),
        _context=context,
        # The spell a derived price was read off. An answer that arrives after
        # it has left the stack buys nothing, so it must charge nothing: the
        # offer is then one no player may take (``_optional_action_still_
        # takeable``), and its decline moves the chain on to find that out.
        **({"_priced_spell": priced_spell} if priced_spell is not None else {}),
        prompt=(
            # The derived price names the spell it was read off, so the seat
            # being asked can see what the payment is for — and a spell that
            # costs {0} is still a question ("Pay {0}?"), not a blank one.
            f"Pay {mana_cost_label(cost)} ({priced_spell.card.name}'s mana cost)?"
            if priced_spell is not None
            else f"Pay {mana_cost_label(cost)}?" if cost
            else f"Pay {life_price} life?" if life_price else "Pay?"
        ),
    )
    return True, "resolved"


def _event_spell_and_cost(game: Game, context: OracleExecutionContext):
    """``(stack item, cost)`` for "that spell's mana cost" under a cast
    trigger, or ``(None, None)`` when there is nothing payable to read.

    The spell is the one the trigger fired on, found on the stack by the
    object the event recorded — the lookup "counter it" one handler over makes
    (``_targets.triggering_spell``), so the price and the counter behind it are
    read off one object, and off *that* object: two Fireballs cast for
    different X are one card and two prices. The cost is
    ``mana_payment.spell_mana_cost``: printed symbols, the announced X, None
    for a spell with no mana cost.
    """
    from ..mana_payment import spell_mana_cost

    spell = triggering_spell(game, context)
    if spell is None:
        return None, None
    cost = spell_mana_cost(spell)
    return (None, None) if cost is None else (spell, cost)
