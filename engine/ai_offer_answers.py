"""The answers an AI seat gives an **offer** part-way through a resolution —
a "you may", an "unless … pays", one link of an "unless any player pays"
chain — where the prompt's default asks for a weighed one.

``_default_optional_pay`` (``mixins/stack/choices/optional_pay``) states the
policy — take gifts, pay tolls, make no trades — and asks these wherever an
answer is worth weighing rather than stating:

* **a toll** — whether its printed penalty loses less than paying it
  (:func:`toll_decline_is_smaller_loss`, by the weights of
  :func:`_toll_loss_price`), and whether to decline one link of a chain
  (:func:`chained_toll_declined`);
* **a trade** — whether an offer's price is worth its purchase
  (:func:`offer_trade_is_worth_taking`), and whether taking it buys its own
  source's drawback, a purchase already settled against, or a returning Aura
  on the wrong side of the table;
* **a copy** — whether to take an offer that copies the resolving spell
  (:func:`copy_offer_answer`, the Chains);
* **the mana** — whether a mana-priced "you may pay" may tap lands
  (:func:`optional_pay_may_tap_lands`).

What each offer and toll *does* is ``ai_offer_readers``'; every other answer
given part-way through a resolution is ``ai_prompts``'. The resolution paths
import these from here, inside the function that asks; ``ai_special_actions``
prices a graveyard taken as a special action's cost by the toll's weights.
"""

from __future__ import annotations

from .ai_offer_readers import offer_trade, offers_a_hand_imprint, TollLoss, toll_branch_loss
from .ai_valuation import offer_buys_a_drawback_to_its_source
from .game import Game
from .ai_payment import _cost_for, _plan_land_taps
from .ai_actions import hand_spells
from .ai_scoring import _permanent_value
from .ai_cast_gates import _can_cast_with_targets


# --- What a toll's two losses are worth against each other -------------------
#
# The prices, in life-equivalents. Weights are tuning and belong here; *which
# resources a branch takes* is `ai_offer_readers.toll_branch_loss`'s derivation
# from the compiled program, and the permanents it hands back are the engine's
# own default picks, so the comparison prices exactly what would be given up.

#: A branch whose life cost meets or beats the seat's total. Never the smaller
#: loss against anything survivable, whatever the other side gives up.
_TOLL_LETHAL_PRICE = 1000.0
#: A card out of hand (a discard) or out of the game (an ante): the classic
#: two-for-one accounting — a card is worth about two life.
_TOLL_CARD_PRICE = 2.0
#: A card milled off the seat's own library: barely a loss at all, but not
#: nothing (CR 704.5b is somewhere down there).
_TOLL_MILL_PRICE = 0.25
#: What any permanent is worth just by being one — a card that reached the
#: battlefield — before `_permanent_value` adds its stats and cost. Without a
#: floor a Mox prices at 0.0 (no P/T, no cmc) and the seat gives it up to dodge
#: any damage at all.
_TOLL_PERMANENT_FLOOR = 2.5
#: Tapping the source: a turn's use of it, not the card.
_TOLL_TAP_PRICE = 1.0
#: A card exiled out of the seat's own graveyard: the mill's weight, since it
#: is the same card one zone further on — and not nothing, because threshold
#: (CR 207.2c), flashback and every "for each card in your graveyard" read
#: the pile.
_TOLL_GRAVEYARD_CARD_PRICE = _TOLL_MILL_PRICE


def _toll_loss_price(game: Game, player_index: int, loss) -> float:
    """One branch's `ai_offer_readers.TollLoss`, priced in life-equivalents."""
    player = game.players[player_index]
    if loss.life and loss.life >= player.life:
        return _TOLL_LETHAL_PRICE
    price = float(loss.life)
    price += loss.cards * _TOLL_CARD_PRICE
    price += loss.milled * _TOLL_MILL_PRICE
    price += loss.exiled_from_graveyard * _TOLL_GRAVEYARD_CARD_PRICE
    for permanent in loss.permanents:
        price += _TOLL_PERMANENT_FLOOR + _permanent_value(permanent)
    if loss.taps_source:
        price += _TOLL_TAP_PRICE
    return price


def _deed_chain_decline(entry: dict, chain_recipients):
    """``(steps, recipients, context)`` a seat's decline of one link of a
    **deed-priced** chain costs it, or None for any other entry.

    "Any player may have Breaking Point deal 6 damage to them. If no one does,
    destroy all creatures." A link's decline is printed as the *next link*
    (``handlers/offers.unless_player_pays``), which no reader can price — so
    the standing policy paid every time, and a seat with no creatures took 6
    to save a board of nothing. What declining risks is the unpaid branch:
    a later seat may still pay, but nothing lets this one count on it. It is
    priced against the resolution's own context (``_chain_context``), whose
    target is the spell's, with the player references resolved against that
    context (*chain_recipients*).
    """
    context = entry.get("_chain_context")
    links = tuple(entry.get("_on_decline") or ())
    if (
        context is None or len(links) != 1
        or getattr(links[0], "kind", None) != "unless_player_pays"
    ):
        return None
    return (
        tuple(links[0].payload.get("unpaid") or ()),
        frozenset(chain_recipients or ()),
        context,
    )


def toll_decline_is_smaller_loss(
    game: Game, player_index: int, entry: dict, self_recipients=(),
    chain_recipients=(),
) -> bool:
    """Whether taking this toll's printed penalty loses less than paying its
    price — the valuation behind **take gifts, pay tolls, make no trades**'
    middle word, for the seat nobody asked (`_default_optional_pay`).

    A *toll* is an offer with a printed decline consequence, so both answers
    are losses: "pay 2 life" against "sacrifice this enchantment" (Season of
    the Witch), "sacrifice that artifact" against "2 damage" (Curse Artifact).
    Both sides are derived from the compiled program by
    `ai_offer_readers.toll_branch_loss` and priced by the weights above; a side the
    program cannot price answers False, which keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    Deliberately silent on a mana-priced toll: the default pays those out of
    floating mana and, since ``optional_pay_may_tap_lands``, out of untapped
    lands too — always, because a toll's other answer is a loss as well and
    the standing policy is to pay. Pricing a tapped land against the penalty
    is a weight nobody has measured a need for yet.

    *entry* is the armed `optional_pay` data and *self_recipients* the printed
    player references that resolve to the offered seat, both supplied by the
    resolution because only it knows them. *chain_recipients* are the same
    references resolved against a deed-priced chain's own context, for the
    decline :func:`_deed_chain_decline` prices.
    """
    penalty_steps = tuple(entry.get("_on_decline") or ())
    decline_recipients = self_recipients
    decline_context = entry.get("_context")
    deed_decline = _deed_chain_decline(entry, chain_recipients)
    if deed_decline is not None:
        penalty_steps, decline_recipients, decline_context = deed_decline
    legacy_damage = int(entry.get("damage", 0) or 0)
    if not penalty_steps and not legacy_damage:
        return False  # not a toll; the unpriced-trade policy owns free offers
    if (
        entry.get("cost")
        or entry.get("cost_alternatives")
        or entry.get("graded_options")
    ):
        return False  # mana-priced: the floating-mana policy stands
    source = entry.get("_source_permanent")
    context = entry.get("_context")
    paying = toll_branch_loss(
        game, player_index, tuple(entry.get("_on_accept") or ()),
        self_recipients, source, context,
    )
    if paying is None:
        return False
    life_cost = int(entry.get("life_cost", 0) or 0)
    if life_cost:
        paying = paying.plus_life(life_cost)
    declining = toll_branch_loss(
        game, player_index, penalty_steps, decline_recipients, source,
        decline_context,
    )
    if declining is None:
        # **A price that kills is never paid for a penalty nobody can price.**
        # "Counter target instant or sorcery spell unless its controller has
        # Molten Influence deal 4 damage to them": what a countered spell is
        # worth is not derivable here, so the standing policy — pay tolls —
        # applied, and a seat at 4 life paid with the game. Whatever the
        # penalty is, it is not larger than the game; every survivable price
        # still goes to the standing policy, exactly as before.
        return _toll_loss_price(game, player_index, paying) >= _TOLL_LETHAL_PRICE
    if legacy_damage:
        declining = declining.plus_life(legacy_damage)
    return _toll_loss_price(game, player_index, declining) < _toll_loss_price(
        game, player_index, paying
    )


#: Lands — on the battlefield and in hand — below which a seat gives up its
#: draw step for a land card (`offer_trade_is_worth_taking`). The number the
#: tutor score already uses for "mana-screwed" is three; one more, because the
#: card bought here costs a draw rather than a tutor.
LAND_FOR_DRAW_FLOOR = 4
def offer_trade_is_worth_taking(
    game: Game, player_index: int, entry: dict
) -> "bool | None":
    """Whether a seat nobody asks takes a "you may A. If you do, B." offer
    whose two halves are a price and a purchase (`ai_offer_readers.offer_trade`) —
    True, False, or None when the offer is not one this can weigh and the
    standing policy answers.

    * **A draw step for a land card** (Elfhame Sanctuary): only while the seat
      is short of lands (`LAND_FOR_DRAW_FLOOR`). Taken every turn it is a seat
      that never draws a spell again.
    * **A card from hand for the source untapped** (Forsaken City): not taken.
      One mana is worth less than a card to a seat that can use its cards, and
      the case where it is not — a card the seat would discard at cleanup
      anyway — did not arise once in six simulated games. It is also not yet
      *payable* by a seat nobody asks: the pick behind the offer defaults to
      no card, and "If you do, untap this land" then untaps it regardless, so
      taking the offer here would be a free untap rather than a trade.
    * **The source for the permanent it targets** (Riptide Entrancer's "you
      may sacrifice it. If you do, gain control of target creature that
      player controls"): taken when what changes sides is worth more than
      what is sacrificed — the target counted twice, once off the opponent's
      standing and once onto the seat's (``ai_standing.permanent_worth``,
      read as the board will be once the turn is over) — and never for a
      target the seat already controls or that has gone.
    * **A card from hand for an imprint** (Chrome Mox, Isochron Scepter, Soul
      Foundry — ``ai_offer_readers.offers_a_hand_imprint``): taken. The
      source's linked ability is the card (CR 607.2a), and with nothing
      exiled it does nothing for the rest of the game: declining keeps one
      card and turns a permanent the seat paid for into a blank. Which card
      goes is the pick's (``_default_exile_from_hand_choice``: the lowest mana
      value the phrase admits).
    """
    if offers_a_hand_imprint(entry.get("_on_accept") or (), entry.get("_source_permanent")):
        return True
    trade = offer_trade(entry.get("_on_accept") or ())
    if trade is None:
        return None
    if (trade.price, trade.purchase) == ("source", "target_permanent"):
        from .ai_offer_readers import _offer_target_permanent
        from .ai_standing import permanent_worth

        target = _offer_target_permanent(game, entry.get("_context"))
        if target is None or game.controller_index_of(target) in (None, player_index):
            return False
        source = entry.get("_source_permanent")
        spent = (
            permanent_worth(source, now=False)
            if source is not None and game.is_on_battlefield(source) else 0.0
        )
        return 2.0 * permanent_worth(target, now=False) > spent
    player = game.players[player_index]
    if (trade.price, trade.purchase) == ("draw", "land_card"):
        lands = sum(
            1 for permanent in game.controlled_by(player_index)
            if permanent.has_type("land")
        ) + sum(1 for card in player.hand if card.primary_type == "land")
        return lands < LAND_FOR_DRAW_FLOOR
    if (trade.price, trade.purchase) == ("card", "untap_source"):
        return False
    return None


#: Condition kinds whose answer is **settled before the offer is put**: each
#: reads a record an earlier step of the same resolution wrote, and nothing
#: the offered action does can change it. "…guesses whether a card with that
#: name is in your hand. You may reveal your hand. If you do and your opponent
#: guessed wrong, draw a card." (Liar's Pendulum.) Only a kind listed here is
#: read ahead of the action — a condition about what the action itself does
#: ("if you sacrifice a Goblin this way") cannot be, and asking it early would
#: be answering a question the action has not posed yet.
_SETTLED_CONDITION_KINDS = frozenset({"named_card_guess_was"})


def offer_purchase_settled_against(game: Game, entry: dict) -> bool:
    """Whether everything a "you may A. If you do and C, B." offer buys is
    gated behind conditions already settled — and settled against.

    Liar's Pendulum's reveal buys a card only when the guess was wrong; with
    the guess right, revealing shows the hand for nothing, and "take gifts"
    read a free reveal as a gift and showed it every time. The condition is
    the guess prompt's record, written before the offer was made, so a seat
    nobody asks may read it: it is that seat's own hand and an announced
    guess. Answers False — the standing policy — for an offer with a price, a
    decline branch, or any purchase not wholly behind a settled condition.
    """
    if (
        entry.get("cost") or entry.get("life_cost")
        or entry.get("cost_alternatives") or entry.get("_on_decline")
    ):
        return False
    context = entry.get("_context")
    accept = list(entry.get("_on_accept") or ())
    purchase = accept[int(entry.get("_action_count", 0) or 0):]
    if context is None or not purchase:
        return False
    from .handlers.control_flow import evaluate_condition

    for step in purchase:
        payload = getattr(step, "payload", None) or {}
        condition = payload.get("condition") or {}
        if (
            getattr(step, "kind", None) != "if_then"
            or payload.get("else")
            or condition.get("kind") not in _SETTLED_CONDITION_KINDS
        ):
            return False
        if evaluate_condition(game, context, condition):
            return False
    return True


def offer_buys_own_drawback(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asks would, by taking this offer, buy the
    drawback its **own** permanent prints.

    "Whenever this creature attacks or blocks, any player may exile a card
    from their graveyard. If a player does, this creature assigns no combat
    damage this turn." (Carrion Rats.) The offer goes to every seat in turn
    and what it buys is a loss for whoever controls the source — so that seat
    declines, whatever the price, and every other seat is left to the standing
    policy. Exiling a card from one's own graveyard reads as no payment
    (``ai_offer_readers.offered_action_is_a_payment``), so before this the attacker took the
    offer and blanked its own Rats every combat. ``chained_toll_declined``
    makes the same call for a *chain* link's paid branch; this is the per-seat
    offer's twin, read off the compiled branch
    (``ai_valuation.offer_buys_a_drawback_to_its_source``).

    **Only an offer put to a set of seats.** "You may put the top creature
    card of defending player's graveyard onto the battlefield under your
    control. If you do, this creature assigns no combat damage this turn."
    (Bone Dancer.) Offered to its controller alone, the same drawback is the
    *price* of what the action takes, and that trade is the card — the
    reading only holds where the card lets anybody buy the drawback.
    """
    source = entry.get("_source_permanent")
    if (
        source is None
        or entry.get("_offered_actor") not in _SEAT_SET_OFFERS
        or not offer_buys_a_drawback_to_its_source(entry.get("_on_accept") or ())
    ):
        return False
    return game.controller_index_of(source) == player_index


def returned_aura_lands_on_wrong_side(
    game: Game, player_index: int, entry: dict,
) -> bool:
    """Whether a seat nobody asks would, by taking "you may return this card
    from your graveyard to the battlefield **attached to that creature**",
    put an Aura on the side of the table it works against.

    The Scourge Dragon Auras: "that creature" is whichever creature with mana
    value 6 or greater entered, under **any** player's control, and the Aura
    returns under its owner's (CR 108.4a, the trigger's seat). Every one of the
    five helps its host — haste, flying, trample, a pump — so taking the gift
    onto an opponent's Dragon hands that opponent the Aura, and "take gifts"
    took it every time. The cast chooser's question asked of a host the effect
    names (``ai_targets._aura_harms_its_host``, the one reader of which side an
    Aura belongs on): declined where the host is on the wrong side for the
    Aura's text, the standing policy everywhere else.
    """
    if not any(
        getattr(step, "kind", None) == "return_self_from_graveyard"
        and (step.payload or {}).get("attached_to") == "event_subject"
        for step in entry.get("_on_accept") or ()
    ):
        return False
    context = entry.get("_context")
    card = getattr(context, "card", None)
    frozen = getattr(context, "trigger_context", None) or {}
    host = game.permanent_by_id(frozen.get("event_subject_permanent_id"))
    if card is None or host is None or not game.is_on_battlefield(host):
        return False
    from .ai_targets import _aura_harms_its_host

    harmful = _aura_harms_its_host(card)
    return (game.controller_index_of(host) == player_index) == harmful


#: The printed actors that put one offer to every seat of a set
#: (``handlers/offers._offered_seats``) — "any player may …" reaches the
#: AST as ``each_player``.
_SEAT_SET_OFFERS = frozenset({"each_player", "each_opponent"})


def _accept_copies_this_spell(steps) -> bool:
    """Whether an offer's accept branch copies the resolving spell, at any
    depth of the offers nested inside it."""
    for step in steps or ():
        if getattr(step, "kind", None) == "copy_this_spell":
            return True
        payload = getattr(step, "payload", None) or {}
        if step.kind == "may" and _accept_copies_this_spell(
            (*(payload.get("action") or ()), *(payload.get("then") or ()))
        ):
            return True
    return False


def offer_buys_a_copy_offer(entry: dict) -> bool:
    """Whether *entry*'s accept branch copies the spell only through an offer
    of its own behind it — "…may pay {R}{R}. If the player does, they may
    copy this spell" (Chain Lightning), "…may sacrifice a land of their
    choice. If the player does, they may copy this spell" (Chain of Vapor):
    what the price buys is the copy offer that follows."""
    steps = tuple(entry.get("_on_accept") or ())
    return _accept_copies_this_spell(steps) and not any(
        getattr(step, "kind", None) == "copy_this_spell" for step in steps
    )


def copy_offer_answer(game: Game, choice) -> "tuple[bool, str] | None":
    """What a seat nobody asks answers an offer that copies the resolving
    spell (the Chains): ``(True, "")`` to take it, ``(False, why)`` to
    decline it, or None where it is no copy offer, or one nothing here
    declines, and the standing policy answers.

    Weighed where it can be (``ai_prompt_picks.copy_offer_pick``: taking it,
    price and copy, rehearsed against declining it, the copy aimed by its own
    default and the other seat's reply to it weighed too). Where nothing can
    weigh it — an interactive seat answered for, a scratch table past the
    first reply — the stated reading (:func:`copy_offer_turns_on_its_taker`)
    declines a copy whose kept target is the taker's."""
    entry = choice.data
    if not _accept_copies_this_spell(entry.get("_on_accept")):
        return None
    if not game.asks_a_person(choice.player_index):
        from .ai_prompt_picks import copy_offer_pick

        taken = copy_offer_pick(game, choice)
        if taken is not None:
            return (True, "") if taken else (
                False, "the copy is not worth what taking it costs",
            )
    if copy_offer_turns_on_its_taker(game, choice.player_index, entry):
        return False, "the copy would be aimed at them"
    return None


def copy_offer_turns_on_its_taker(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asks would, by taking "…**they may copy this
    spell** and may choose a new target for that copy", aim the copy at itself
    — read off the copy's **kept** target: the stated reading
    :func:`copy_offer_answer` falls back to where the offer cannot be weighed.

    The Onslaught Chains (Chain of Smog: "Target player discards two cards.
    That player may copy this spell …"). The copy offer is free, so the
    standing policy takes it as a gift — and a copy that keeps the original's
    target is aimed, for the player the spell was aimed at, at **that same
    player**: the AI discarded its own hand two cards at a time and was
    offered the copy again by every copy, without end. A copy whose kept
    target is the taker's own seat or a permanent it controls is declined;
    every other copy offer keeps the standing policy. Where the offer can be
    weighed, the copy's measured target decides instead
    (``ai_prompt_picks.copy_offer_pick``).
    """
    if not _accept_copies_this_spell(entry.get("_on_accept")):
        return False
    context = entry.get("_context")
    if context is None:
        return False
    from .game_types import first_target_id

    held = first_target_id(getattr(context, "target_permanent_id", None))
    if held is not None:
        permanent = game.permanent_by_id(held)
        return (
            permanent is not None
            and game.controller_index_of(permanent) == player_index
        )
    target = getattr(context, "target", None)
    return target is not None and target in game.players and (
        game.players.index(target) == player_index
    )


def chained_toll_declined(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked declines one link of an "unless **any
    player** pays" chain (`handlers/offers.unless_player_pays`).

    The chain asks every seat in turn, the effect's own controller included —
    and for that seat the standing policy, *pay tolls*, is backwards: Rhystic
    Tutor's caster paid {2} to stop its own search, and every rhystic spell
    the AI cast was countered by its own mana. Who a link's answer helps is
    whose effect it is, read off the compiled program:

    * the **unpaid** branch is what the controller cast the effect for, unless
      ``toll_branch_loss`` prices it as the controller's own loss (Icy
      Prison's "sacrifice this enchantment") — so the controller pays only to
      stop a loss, and every other seat pays only to stop a gain;
    * the **paid** branch (Rhystic Scrying's "if any player pays {2}, discard
      three cards") is the drawback the card prints, so its controller never
      buys it and every other seat does when it can afford to.

    False — the standing policy — for anything that is not a chain link.
    """
    links = tuple(entry.get("_on_decline") or ())
    if len(links) != 1 or getattr(links[0], "kind", None) != "unless_player_pays":
        return False
    caster = getattr(entry.get("_context"), "caster", None)
    if caster is None or caster not in game.players:
        return False
    controller = game.players.index(caster)
    unpaid = tuple(links[0].payload.get("unpaid") or ())
    if entry.get("_chain_context") is not None and player_index != controller:
        # A **deed-priced** link ("any player may have Breaking Point deal 6
        # damage to them"). The rule below assumes the unpaid branch hurts its
        # controller or helps them and nobody else; a sweep hurts every seat,
        # so another seat is not told to decline because the caster would
        # lose creatures too. It weighs its own loss against the deed instead
        # (``toll_decline_is_smaller_loss`` / ``_deed_chain_decline``).
        return False
    if not unpaid:
        if chain_payment_counters_the_event_spell(entry):
            # What paying buys is the *payer's*: somebody else's spell
            # countered (Ice Cave), whoever's permanent makes the offer. Not a
            # drawback its controller avoids, so no seat declines it by rule —
            # whether the mana is worth spending is
            # ``optional_pay_may_tap_lands``' question.
            return False
        return player_index == controller
    loss = toll_branch_loss(
        game, controller, unpaid, {"caster"}, entry.get("_source_permanent")
    )
    unpaid_is_a_loss = loss is not None and loss != TollLoss()
    return (player_index == controller) != unpaid_is_a_loss


def chain_payment_counters_the_event_spell(entry: dict) -> bool:
    """Whether *entry* is a link of an offer chain whose payment buys exactly
    one thing: the spell the trigger fired on, countered.

    "Whenever a player casts a spell, any other player may pay that spell's
    mana cost. If a player does, counter the spell." (Ice Cave.) Read off the
    armed link's own compiled branches — a ``paid`` branch that is a counter
    bound to the trigger and no ``unpaid`` branch at all — so it is a fact
    about the program and never about a card.

    The chain is only ever offered to seats *other* than the spell's caster,
    and this engine has no teams, so for every seat that is asked the spell is
    an opponent's: paying is a gain for the payer, at a price.
    """
    links = tuple(entry.get("_on_decline") or ())
    if len(links) != 1 or getattr(links[0], "kind", None) != "unless_player_pays":
        return False
    payload = links[0].payload
    paid = tuple(payload.get("paid") or ())
    return bool(paid) and not payload.get("unpaid") and all(
        getattr(step, "kind", None) == "counter_top_stack_spell"
        and step.payload.get("bound_to_trigger")
        for step in paid
    )


#: The life total below which a seat nobody asked starts spending its lands on
#: a life-only toll during its own turn (:func:`optional_pay_may_tap_lands`).
#: A weight, like every number in this module: half the starting total, so a
#: healthy seat keeps developing and one that has been bled to it stops
#: bleeding. The toll is paid when declining would leave the seat *under* it.
LIFE_TOLL_FLOOR = 10


def _life_only_toll(entry: dict) -> int | None:
    """The life a seat loses by declining *entry*, when losing that life is
    **all** declining does; otherwise None.

    Read off the armed offer's own decline branch, so it is a fact about the
    compiled program and never about a card: exactly one ``target_loses_life``
    carrying a printed number. Anything else — a sacrifice, damage, a counter,
    two steps, an amount only the resolution knows — is a toll this cannot
    price, and None keeps the standing policy for it (pay).
    """
    decline = tuple(entry.get("_on_decline") or ())
    if len(decline) != 1:
        return None
    step = decline[0]
    if getattr(step, "kind", None) != "target_loses_life":
        return None
    amount = step.payload.get("amount")
    return amount if isinstance(amount, int) and amount > 0 else None


def optional_pay_may_tap_lands(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked may tap its untapped lands to pay a
    mana-priced "you may pay" / "unless you pay" (`_default_optional_pay`).

    The policy that default states — **take gifts, pay tolls, make no trades** —
    had a mana half that read "never tap a land", and the offers this answers
    arrive where the pool is empty: an upkeep, a combat damage step, an
    opponent's turn. So every mana-priced toll was declined (Vaporous Djinn
    sacrificed itself with its two Islands untapped) and every mana-priced gift
    was refused (Rootwater Thief's {2}, Liliana's Devotee's {1}{B}). The
    plumbing to pay from lands was already there — ``_optional_pay_plan`` is a
    ``plan_payment`` over the untapped lands — and this is the weight that
    decides when to use it:

    * **A toll is always paid from the board when it can be.** Both answers
      are losses and the standing policy is to pay; refusing an affordable toll
      because the mana was in a land rather than in the pool was never the
      policy, only a consequence of where the pool happened to be.
    * **A gift is paid from lands only with mana nothing else will spend.** On
      another seat's turn the lands sit until this seat's untap step anyway. On
      the seat's own turn they are what it casts with, so a gift is taken only
      when no spell in hand could be cast with them now — the same question
      ``ai_policy.choose_cast_action`` answers, asked of the same candidates.
    * **And only a gift the seat's own object offers** — or a copy of another
      seat's spell. An offer another seat's spell makes this one is priced by
      a card somebody else chose to cast, and what accepting does is left to
      defaults this policy cannot value; those keep the floating-mana rule.
      A copy of the spell ("that player may pay {R}{R}. If the player does,
      they may copy this spell", Chain Lightning) is the exception: what it
      buys is weighed (``ai_prompt_picks.copy_offer_pick``), so its price is
      a gift's.
    * **A toll whose whole penalty is a little life is the one toll priced
      against the lands** (:func:`_life_only_toll`). "Whenever a player draws a
      card, that player loses 2 life unless they pay {2}" (Phyrexian Tyranny)
      asks every turn, in the draw step, before the seat has cast anything —
      and "always pay" answered it by tapping two lands a turn for the rest of
      the game: forty tolls paid out of forty in a six-game run, the seat
      under it casting with whatever was left. So on the seat's **own** turn
      such a toll is paid like a gift — with mana nothing in hand could use —
      until its life is low enough (:data:`LIFE_TOLL_FLOOR`) that the life is
      the dearer of the two. On another seat's turn the lands are idle and the
      standing answer stands: pay.
    """
    if chain_payment_counters_the_event_spell(entry):
        # **A gift at a price, to whichever seat pays it** (Ice Cave): the
        # decline branch is only the chain moving on, so refusing costs
        # nothing and this is not a toll — and what accepting buys is fully
        # known, an opponent's spell countered, so it is not the unvalued offer
        # of another seat's object either. It takes the gift rule's mana half:
        # lands that are idle (another seat's turn) always, and on the seat's
        # own turn only lands nothing in its hand could use.
        if game.active_player_index != player_index:
            return True
        return not _hand_could_use_mana(game, player_index)
    if entry.get("_on_decline") or int(entry.get("damage", 0) or 0) > 0:
        loss = _life_only_toll(entry)
        if loss is None or game.active_player_index != player_index:
            return True
        payer = game.players[player_index]
        if payer.life - loss < LIFE_TOLL_FLOOR:
            return True
        return not _hand_could_use_mana(game, player_index)
    context = entry.get("_context")
    if getattr(context, "caster", None) is not game.players[player_index] and not (
        _accept_copies_this_spell(entry.get("_on_accept"))
    ):
        return False
    if game.active_player_index != player_index:
        return True
    return not _hand_could_use_mana(game, player_index)


def _hand_could_use_mana(game: Game, player_index: int) -> bool:
    """Whether a spell in *player_index*'s hand could be cast with the mana
    its board makes — the question a gift or a toll paid on the seat's **own**
    turn asks ("lands nothing in its hand could use").

    Not `ai_casts._cast_candidate`, which this asked until the policy began to
    rehearse a cast before proposing it: that answers "is this cast worth
    proposing *now*", and asked while this very prompt is owed, the rehearsal's
    copy refuses every cast — so the whole hand read as unusable and the seat
    paid with lands it had a use for (Ice Cave, a Lightning Bolt in hand). What
    is asked here is the older question: legal to aim, and affordable.
    """
    player = game.players[player_index]
    for _hand_index, card in hand_spells(player):
        if card.primary_type == "land":
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue
        x_value = 0 if "{X}" in (card.mana_cost or "").upper() else None
        if _plan_land_taps(game, player, _cost_for(game, player, card, x_value)) is not None:
            return True
    return False
