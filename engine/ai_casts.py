"""One cast, built as a candidate: the ``CastAction`` casting a card would be,
in each of its modes, at each answer to its optional costs.

:func:`_cast_candidate` is the builder every cast chooser asks — for the
hand, the command zone (CR 903.8) and every zone an effect opens (CR 601.3),
in a seat's own main phase and **at instant speed** alike (its *speed*,
``ai_actions._SPEED_WEIGHED``: until kg5 the instant-speed chooser was a
thinner builder of its own, with none of the variants below and half the
gates) — inside one deliberation (``ai_rehearsal.deliberating``). It works
inward:

* each **mode** the caster may announce (:func:`_cast_candidate_in_each_mode`,
  CR 700.2), and for "choose one or more" every mode worth casting at once
  (:func:`_every_mode_worth_casting`);
* each size of an X paid in **life** (:func:`_cast_candidate_sized`);
* each answer to CR 601.2b's **optional costs** — a kicker, a buyback, an
  offer repeated — most paid first (:func:`_cast_candidate_offering`), by what
  each buys and whether the seat can spare its price
  (:func:`_times_worth_taking`);
* and, for one fixed answer, the **announcement** itself
  (:func:`_cast_candidate_announcing`): its gates (``ai_cast_gates``), its
  targets (``ai_targets``, ``ai_slot_targets``, ``ai_divisions``), its X,
  its payment (``ai_payment``), and the rehearsal that decides whether it is
  worth proposing (``ai_scoring``) — read, at instant speed, as that moment
  reads it (``ai_scoring.read_at_instant_speed``, ``held_at_instant_speed``,
  ``ai_cast_score.kept_above_the_floor``).

:func:`_priced_candidate` is a candidate with its plan told what it pays for,
refused where the payment would spend a permanent the cast itself names.
Which of all these casts to make is ``ai_policy``'s.
"""

from __future__ import annotations

from contextvars import ContextVar
from itertools import combinations, product
from dataclasses import replace

from . import ai_cast_trace as cast_trace
from .ai_cast_score import finished_cast_candidate, kept_above_the_floor
from .ai_weighed_cast import (
    SPELL_TYPES,
    PermittedCast,
    cast_weighed,
    caster_chooses_a_mode,
    casting_under,
    considering_mode,
    hand_waiver,
)
from .ai_target_sides import activation_target_side, ability_target_side
from .ai_rehearsal import deliberating
from .ai_entwine import entwined_cast
from .ai_valuation import (
    OFFER_ALTERS,
    OFFER_ENTWINES,
    OFFER_KICKS,
    OFFER_RETURNS_SPELL,
    CastOffer,
    cast_offers,
    entry_may_remove_itself,
    entry_triggers_bought,
)
from .ai_graveyard_returns import cast_graveyard_return
from .cast_costs import additional_costs, cast_announces_x
from .cast_restrictions import check_cast_timing
from .face_down import cast_announces_morph
from .game import Game
from .mixins.stack import aura_enchant_noun
from .models import CardDefinition
from .oracle import compile_card_oracle
from .targeting import derive_cast_spec, derive_instruction_spec, spec_roles
from .ai_mana_sources import _nonland_mana_source
from .ai_payment import (
    _bind_action_slots,
    _paying_for,
    _cost_for,
    _plan_land_taps,
)
from .ai_actions import (
    CastAction,
    cast_announcement,
    _zone_seat,
    hand_spells,
    weighed_at_instant_speed,
    _OFFERS_ANNOUNCED,
    _SPEED_WEIGHED,
    _announced_mode,
    _announced_steps,
    _cast_zone,
    _announces_any_offer,
    target_keywords,
)
from .target_keywords import cast_target_zone
from .ai_scoring import (
    _LIFE_X_ASKED,
    _arrives_to_stay,
    arrival_needs_the_board,
    body_needs_the_board,
    _rehearse_announcement,
    _names_an_unweighed_seat,
    _worth_proposing,
    _weighed_through_the_fight,
    _pays_x_in_life,
    _choose_target_for_spell,
    _pick_x_value,
    held_at_instant_speed,
    not_worth_proposing,
    read_at_instant_speed,
)
from .ai_cast_gates import (
    _cast_life_price,
    _aimed_under_target_requirements,
    _printed_costs_are_payable,
    _alternative_cost_is_payable,
    _alternative_cost_tap_plan,
    cheaper_mana_alternative_indices,
    payable_alternative_indices,
    permission_leaves_the_price,
    _can_cast_with_targets,
    _caster_can_make_its_sacrifices,
    _entry_gate_gives_back_more_than_it_brings,
    _caster_holds_a_hand_pick_entrant,
    _exchange_shrinks_the_library,
)
from .ai_targets import (
    _cast_graveyard_denial,
    _choose_aura_target,
    _NOT_OBJECT_SPECS,
    _choose_single_object_target,
    _chosen_stack_target,
    _guarded_stack_target,
)
from .ai_slot_targets import (
    _choose_role_targets,
    _names_x_targets,
    _choose_several_targets,
)
from .ai_divisions import choose_divided_targets
from .ai_imprint import held_for_an_imprint
from .ai_sacrifice_victims import (
    cast_naming_its_sacrifices,
    sacrifices_weighed_provisionally,
)
from .ai_text_changes import choose_object_or_spell


def _priced_candidate(
    game: Game, seat: int, spell: CardDefinition, zone_index: int, *,
    from_zone: str = "hand", extra_generic: int = 0,
    under: "PermittedCast | None" = None, speed: str = "main",
) -> "CastAction | None":
    """`_cast_candidate` with the plan told what it pays for (`_paying_for`),
    or None where the payment would spend a permanent the cast names.

    **What both cast choosers ask**, at either *speed* (``"main"`` or
    ``"instant"``, `_cast_candidate`'s): the main phase's and the one that
    answers priority (``ai_policy.choose_combat_instant_cast_action``). The
    instant-speed chooser planned without being told what it paid for until
    kg5, so restricted mana ("Spend this mana only to cast an instant or
    sorcery spell", Vodalian Arcanist) and a source that pays by being
    sacrificed (Lotus Petal) never counted toward a response."""
    with _paying_for(spell):
        candidate = _cast_candidate(
            game, seat, spell, zone_index, from_zone=from_zone,
            extra_generic=extra_generic, under=under, speed=speed,
        )
    if candidate is None:
        return None
    if _plan_spends_what_it_names(game, seat, candidate):
        cast_trace.withdrawn(
            game, candidate, "its payment sacrifices a permanent the cast names",
        )
        return None
    return candidate


def _plan_spends_what_it_names(game: Game, seat: int, candidate: "CastAction") -> bool:
    """Whether *candidate*'s payment sacrifices a permanent the cast itself
    names as a target.

    The plan is drawn up after the targets are chosen and is not told them,
    so this is asked of the finished candidate: a Giant Growth aimed at the
    seat's own Blood Pet and paid for by sacrificing that Blood Pet is a spell
    cast at nothing. Not proposed, rather than proposed and fizzled.
    """
    spent = [
        permanent for permanent in (
            game.permanent_at(seat, slot) for slot in candidate.land_tap_indices
        )
        if permanent is not None and (
            (source := _nonland_mana_source(game, seat, permanent, may_sacrifice=True))
            is not None and source.sacrifices
        )
    ]
    if not spent:
        return False
    bound = _bind_action_slots(game, seat, candidate)
    named = [bound.get("target"), *bound.get("targets", ()), *bound.get("divided", ()),
             *bound.get("modes", ())]
    named += [
        game.permanent_by_id(permanent_id)
        for permanent_id in (candidate.target_permanent_ids or ())
        if isinstance(permanent_id, int)
    ]
    return any(permanent is other for permanent in spent for other in named if other is not None)


#: Optional additional costs (CR 601.2b) — the tuning. *Which* offers a card
#: makes and what each buys is `ai_valuation.cast_offers`; these say how far a
#: seat goes for one.
#:
#: The most times a repeatable offer is announced ("you may pay {1}{G} any
#: number of times"). The lands bound it first; this bounds the search.
OFFER_REPEAT_CAP = 6
#: A buyback paid in life (Slaughter's 4) is taken only while the seat keeps
#: this much — the reserve `ai_foreign_activations.FOREIGN_ACTIVATION_LIFE_RESERVE`
#: keeps, for the same reason: life is the one resource whose last points
#: lose the game.
BUYBACK_LIFE_RESERVE = 10
#: A buyback paid in permanents ("Buyback—Sacrifice a land") is taken only by
#: a seat that still controls this many of them afterwards: enough lands to
#: cast everything a limited deck holds.
BUYBACK_PERMANENTS_KEPT = 6
#: A buyback paid in cards is taken only from a hand already over its maximum
#: size (CR 402.2), where the cards it costs were going to cleanup anyway.
BUYBACK_HAND_KEPT = 7


def _mana_value_of(cost: dict[str, int]) -> int:
    return sum(int(amount or 0) for amount in cost.values())


def _buyback_mana_is_spare(
    game: Game, player_index: int, card: CardDefinition, hand_index: int,
    offer: CastOffer, from_zone: str,
) -> bool:
    """Whether paying *offer* costs this seat no other spell this turn.

    A buyback buys the *next* cast of this card, with mana that could have
    cast something now. So the rule is the one a player uses: take it with
    mana nothing else in hand wants. Concretely — if some other spell in hand
    could be cast *alongside* this one, and could not once the buyback is
    paid too, the mana is not spare and the offer is declined.

    Free mana (a game not enforcing costs) is always spare.

    **At instant speed the other spells are the ones castable now**
    (``cast_timing.casts_at_instant_speed``, the engine's question): at an
    opponent's end step a sorcery in hand cannot be cast beside this one,
    and the lands untap before it can be cast at all, so it spends none of
    the mana a buyback would.
    """
    from .cast_timing import casts_at_instant_speed

    if not game.enforce_mana_costs:
        return True
    player = game.players[player_index]
    spell = _cost_for(game, player, card, None)
    with_offer = dict(spell)
    for symbol, amount in offer.mana.cost_at(None).items():
        with_offer[symbol] = with_offer.get(symbol, 0) + amount
    at_instant_speed = weighed_at_instant_speed()
    for other_index, other in hand_spells(player):
        if from_zone == "hand" and other_index == hand_index:
            continue
        if other.primary_type == "land" or cast_announces_x(other, from_zone="hand"):
            continue
        if at_instant_speed and not casts_at_instant_speed(other, game, player_index):
            continue
        # A card in *hand*, priced as one: a deck repeats one definition per
        # copy, so the hand's copy of the spell being weighed from a graveyard
        # is the same object and would otherwise read that cast's price.
        with casting_under(None):
            beside = _cost_for(game, player, other, None)
        both = dict(spell)
        every = dict(with_offer)
        for symbol, amount in beside.items():
            both[symbol] = both.get(symbol, 0) + amount
            every[symbol] = every.get(symbol, 0) + amount
        if (
            _plan_land_taps(game, player, both) is not None
            and _plan_land_taps(game, player, every) is None
        ):
            return False
    return True


def _buyback_price_is_worth_paying(
    game: Game, player_index: int, card: CardDefinition, hand_index: int,
    offer: CastOffer, from_zone: str,
) -> bool:
    """Whether a buyback whose price is not mana is worth its price now.

    Three resources, three reserves (the constants above), and a price asking
    for several is taken only when every one is spare — Flowstone Flood's "Pay
    3 life, Discard a card at random" is both.
    """
    price = offer.price
    player = game.players[player_index]
    if price.pay_life_x or price.discard_count_x or price.return_count_x:
        return False
    if price.pay_life and player.life - price.pay_life < BUYBACK_LIFE_RESERVE:
        return False
    cards_asked = (
        price.discard_cards + len(price.discard_filters)
        + (len(player.hand) if price.discard_whole_hand else 0)
    )
    if cards_asked:
        held = len(player.hand) - (1 if from_zone == "hand" else 0)
        if held - cards_asked < BUYBACK_HAND_KEPT:
            return False
    for giving_up, filter_, count in (
        ("sacrifice", price.sacrifice_filter, max(1, price.sacrifice_count)),
        ("return", price.return_filter, max(1, price.return_count)),
    ):
        if filter_ is None:
            continue
        # The engine's own list of what could pay — the one its gate counts.
        available = game._additional_cost_candidates(
            player_index, price, giving_up=giving_up
        )
        if len(available) - count < BUYBACK_PERMANENTS_KEPT:
            return False
    if price.sacrifice_all_filter is not None or price.exile_filter is not None:
        return False
    if price.exile_graveyard_filter is not None and price.exile_graveyard_count_x:
        return False
    return True


def _times_worth_taking(
    game: Game, player_index: int, card: CardDefinition, hand_index: int,
    offer: CastOffer, from_zone: str,
) -> int:
    """The most times this seat would pay *offer* on this cast — 0 to decline.

    **The policy, by what the offer buys** (`ai_valuation.CastOffer.buys`):

    * *kicked* and *more_effect* — taken whenever the lands can pay for it,
      a repeatable one as many times as they can. That was the kicker rule;
      it is every mana offer's now, because "the spell does more" is the same
      purchase whichever keyword sells it. Whether the lands **can** is not
      decided here: each announcement is built as a whole candidate, and one
      the board cannot pay or cannot aim falls back to the next.
    * *returns_spell* (buyback) — taken with mana nothing else in hand wants
      (`_buyback_mana_is_spare`), or with a non-mana price the seat can spare
      (`_buyback_price_is_worth_paying`). A seat that always bought back would
      spend its turn's mana re-buying one spell while its hand sat uncast; one
      that never did left half of 28 cards unreachable, which is where this
      started.
    * *other_effect* — declined. The paid spell is a different spell rather
      than a larger one (Undergrowth's paid Fog spares every red creature),
      and nothing here can tell which the board wants. One shipped card.
    """
    if offer.from_zone not in (None, from_zone):
        return 0
    if offer.buys in (OFFER_ALTERS, OFFER_ENTWINES):
        # …and an entwine (CR 702.42a), which is no larger version of the mode
        # being weighed: it chooses every mode, and is weighed as a cast of its
        # own once each mode is built (`ai_entwine.entwined_cast`).
        return 0
    if offer.price is not None:
        # A price that is not mana: a buyback's ("Buyback—Sacrifice a land")
        # or a kicker's ("Kicker—Sacrifice two lands", "Kicker—Pay 3 life").
        # One test for both, because it asks about the *resource* and not
        # about what it buys: a land, a creature, a card or life is spare when
        # the reserve still stands after it is spent, whichever keyword is
        # selling. That is deliberately the conservative end for a kicker — a
        # seat with four lands does not give up two of them to make Magma
        # Burst hit a second target — and a seat that cannot spare the price
        # simply casts the spell unkicked: the announcements run down to `{}`,
        # so declining here is never a card left in hand.
        if offer.buys not in (OFFER_RETURNS_SPELL, OFFER_KICKS):
            return 0
        return 1 if _buyback_price_is_worth_paying(
            game, player_index, card, hand_index, offer, from_zone
        ) else 0
    if offer.buys == OFFER_RETURNS_SPELL and not _buyback_mana_is_spare(
        game, player_index, card, hand_index, offer, from_zone
    ):
        return 0
    if not offer.repeatable:
        return 1
    if not game.enforce_mana_costs:
        # Free mana has no ceiling to size "any number of times" by; once.
        return 1
    each = _mana_value_of(offer.mana.cost_at(None))
    if each <= 0:
        return 1
    untapped = sum(
        1 for permanent in game.controlled_by(player_index)
        if permanent.has_type("land") and not permanent.tapped
    )
    return max(0, min(OFFER_REPEAT_CAP, untapped // each))


def _offer_announcements(
    game: Game, player_index: int, card: CardDefinition, hand_index: int,
    from_zone: str,
) -> list[dict[str, int]]:
    """Every answer to CR 601.2b's offers this seat would give, best first.

    Empty for a card that makes no offer. Otherwise the announcements run from
    everything worth taking, as many times as worth taking, down to ``{}`` —
    most payments first, so the first one that builds a legal, affordable
    candidate is the most the board can actually pay for.
    """
    if card.primary_type == "land":
        return []
    offers = cast_offers(card)
    if not offers:
        return []
    wanted = [
        (offer, times) for offer in offers
        if (times := _times_worth_taking(
            game, player_index, card, hand_index, offer, from_zone
        )) > 0
    ]
    combinations = sorted(
        product(*(range(times, -1, -1) for _offer, times in wanted)),
        key=lambda counts: -sum(counts),
    )
    return [
        {offer.key: count for (offer, _times), count in zip(wanted, counts) if count}
        for counts in combinations
    ]


#: Set by `_cast_candidate_announcing` when the candidate it was building
#: was dropped because nothing the cast does outlasts the turn
#: (``Rehearsal.fleeting``) — for `_cast_candidate_offering`, which has other
#: announcements of the same spell still to try and need not try them.
_HELD_AS_FLEETING: ContextVar[bool] = ContextVar("ai_held_as_fleeting", default=False)


def _cast_candidate(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
    under: "PermittedCast | None" = None,
    speed: str = "main",
) -> CastAction | None:
    """`_cast_candidate_in_each_mode` inside one deliberation: every mode,
    offer and target of *card* this decision weighs is measured against one
    reading of the table with nothing cast (``ai_rehearsal.deliberating``).

    *speed* is the moment the cast is weighed at (``ai_actions._SPEED_WEIGHED``):
    ``"main"``, or ``"instant"`` for a cast made with priority anywhere else.
    The same builder either way — every gate, every variant loop, every target
    chooser below — and the speed only changes how the finished cast is read
    (`_announced_candidate`'s last step)."""
    if speed not in ("main", "instant"):
        raise ValueError(f"speed is 'main' or 'instant', not {speed!r}")
    token = _SPEED_WEIGHED.set(speed)
    try:
        with deliberating():
            return _cast_candidate_in_each_mode(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic, under=under,
            )
    finally:
        _SPEED_WEIGHED.reset(token)


def _cast_candidate_in_each_mode(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
    under: "PermittedCast | None" = None,
) -> CastAction | None:
    """The `CastAction` casting *card* from *from_zone* would be, or None when
    the cast is illegal, unaffordable or has nothing legal to point at.

    *under* is the permission the cast would be made under when an effect
    allows it (CR 601.3, `ai_weighed_cast.permitted_casts`): where the card is,
    and what the cast is charged — a flashback cost (CR 702.34a), nothing, or
    the card's own mana cost. None for the hand and the command zone, whose
    permission is a rule; a **hand** cast is still asked whether a waiver
    covers it (`ai_weighed_cast.hand_waiver`: Aluren), because the cast path
    applies one unasked and a seat that planned the mana cost under it held a
    free creature until it could pay for it. Everything underneath reads the
    permission being weighed (`_cast_zone`, `_cost_for`), as it reads the
    mode.

    **CR 601.2b's optional additional costs are decided here** — kicker
    (CR 702.33), buyback (CR 702.27) and the unnamed "you may pay … any number
    of times" alike, by what each buys rather than by what it is called
    (`_times_worth_taking`). Each answer is tried as a whole candidate, most
    paid first, because two answers are two different announcements: a
    different price, and by CR 702.33g and CR 601.2c a different set of targets
    (an unkicked Benalish Emissary names no land; a Primitive Justice paid
    twice names three artifacts). So an attempt that cannot be afforded, or
    whose paid-for half has nothing legal to point at, falls back to the next
    and finally to the plain spell rather than leaving the card in hand.

    **And CR 601.2b's mode, one level out.** A "Choose one —" spell is as many
    spells as it has bullets (CR 700.2a), so each mode the engine says has a
    legal announcement right now (`Game.announceable_modes`, the list the mode
    prompt offers a human) is built as a whole candidate of its own — its own
    targets on the side *its* effect wants, its own score — and the best one is
    the cast. Everything underneath reads the mode being weighed
    (`_announced_mode`), so no gate, chooser or weight had to learn the word.
    This loop did not exist: the cast named no mode, the engine resolved the
    first bullet, and Crosis's Charm only ever bounced.
    """
    # A card an imprint on the seat's own board would take this turn, and
    # whose free cast every upkeep is worth something (Panoptic Mirror):
    # held from the main phase's cast, which comes before the activation
    # that imprints it (`ai_imprint.held_for_an_imprint`).
    imprint_hold = (
        held_for_an_imprint(game, player_index, card)
        if under is None and from_zone == "hand" and _SPEED_WEIGHED.get() == "main"
        else None
    )
    if under is None and from_zone == "hand":
        hand = game.players[player_index].hand
        if 0 <= hand_index < len(hand):
            under = hand_waiver(game, player_index, hand[hand_index], card, hand_index)
    with cast_trace.entry(
        game, player_index, card, from_zone=from_zone, zone_index=hand_index,
        permission=under, extra_generic=extra_generic, speed=_SPEED_WEIGHED.get(),
    ) as traced:
        if imprint_hold is not None:
            cast_trace.note(imprint_hold)
            return traced.returns(None)
        return traced.returns(_best_of_the_modes(
            game, player_index, card, hand_index,
            from_zone=from_zone, extra_generic=extra_generic, under=under,
        ))


def _best_of_the_modes(
    game: Game, player_index: int, card: CardDefinition, hand_index: int, *,
    from_zone: str, extra_generic: int, under: "PermittedCast | None",
) -> CastAction | None:
    """`_cast_candidate_in_each_mode`'s choice, under the permission it
    settled on: the best single mode, every mode at once for "choose one or
    more", or the entwined cast where it beats the best mode."""
    best: CastAction | None = None
    built: list[CastAction] = []
    modes = _modes_weighed(game, player_index, card)
    _note_modes_not_weighed(card, modes)
    for mode_index in modes:
        with considering_mode(card, mode_index), casting_under(under):
            candidate = _cast_candidate_sized(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic,
            )
        if candidate is None:
            continue
        built.append(candidate)
        # Strictly better only, so equal modes keep printed order — which is
        # also what keeps a seed's run reproducible.
        if best is None or candidate.score > best.score:
            best = candidate
    if len(built) > 1 and compile_card_oracle(card).modes_at_least:
        return _every_mode_worth_casting(built, best, game=game, seat=player_index) or best
    if built:
        # CR 702.42a: every mode for the entwine on top, cast only where its
        # rehearsal beats the best single mode (`ai_entwine.entwined_cast`).
        # Weighed under the permission the single modes were (CR 601.3): the
        # price (`ai_payment._cost_for`: nothing under a waiver, so only the
        # entwine is planned), the rehearsal's trip out of the pile and whose
        # pile it is, and the zone's bonus (`ai_cast_score`) all read it.
        with casting_under(under):
            entwined = entwined_cast(
                game, player_index, card, built, best,
                from_zone=from_zone, extra_generic=extra_generic,
            )
        if entwined is not None and entwined.score > best.score:
            return entwined
    return best


#: What each further mode of a "choose one or more" spell adds to the score of
#: the best one. Tuning: the modes share one cost, so every one after the first
#: is an effect for no mana — worth having, and never worth more than a spell.
EXTRA_MODE_SCORE = 1.0


def _every_mode_worth_casting(
    built: "list[CastAction]", best: CastAction, *,
    game: "Game | None" = None, seat: int = 0,
) -> CastAction | None:
    """`_one_cast_of_every_mode`, recorded (``ai_cast_trace``) as the
    candidate it is when *game* is the table being listened to."""
    with cast_trace.attempt(game, seat, None, variant="every mode"):
        combined = _one_cast_of_every_mode(built, best)
        if combined is None:
            return cast_trace.dropped(
                "the modes do not share one announcement (several targets, a"
                " division, an offer, or a different price or X)"
            )
        cast_trace.scored_from(game, combined, best, [
            ("extra modes", EXTRA_MODE_SCORE * (len(built) - 1)),
        ], combined.score)
        return combined


def _one_cast_of_every_mode(
    built: "list[CastAction]", best: CastAction
) -> CastAction | None:
    """One cast naming **every** mode in *built* — "Choose one **or more** —"
    (Sublime Epiphany, CR 700.2d) — or None when they cannot share one
    announcement.

    Each entry of *built* is a mode this policy would cast on its own: it has a
    legal announcement, a target on the side its effect wants and a payable
    cost. The modes of one spell share one cost, so taking them all is every
    one of those effects for the price of the best — which is the whole reason
    the head is printed, and a seat that named one bullet paid six mana for a
    cantrip. The announcement is `queue_from_hand`'s ``mode_choices``: each
    mode beside its own seat and slot.

    None, and the caller keeps the single best mode, when a mode's targets do
    not fit that shape (it carries one seat and one battlefield slot — several
    targets, a division or a cross-board list do not travel in it) or when the
    modes were not priced alike.
    """
    choices: list[dict] = []
    for candidate in built:
        if (
            len(candidate.target_permanent_ids or ()) > 1
            or len(candidate.target_graveyard_indices or ()) > 1
        ):
            return None
        if (
            candidate.divided_targets
            or candidate.optional_cost_payments
            or candidate.alternative_cost != best.alternative_cost
            or candidate.x_value != best.x_value
            or candidate.land_tap_indices != best.land_tap_indices
            or candidate.land_tap_colors != best.land_tap_colors
        ):
            return None
        choices.append({
            "index": candidate.mode_index,
            "target_player_index": candidate.target_player_index,
            "target_permanent_ids": candidate.target_permanent_ids,
            "target_graveyard_indices": candidate.target_graveyard_indices,
            "target_stack_index": candidate.target_stack_index,
        })
    return CastAction(
        card_name=best.card_name,
        target_player_index=best.target_player_index,
        x_value=best.x_value,
        land_tap_indices=best.land_tap_indices,
        score=best.score + EXTRA_MODE_SCORE * (len(choices) - 1),
        hand_index=best.hand_index,
        from_zone=best.from_zone,
        zone_seat=best.zone_seat,
        alternative_cost=best.alternative_cost,
        land_tap_colors=best.land_tap_colors,
        mode_choices=choices,
    )


def _modes_weighed(
    game: Game, player_index: int, card: CardDefinition
) -> "tuple[int | None, ...]":
    """The modes *card* is weighed in as a cast: ``(None,)`` for a spell with
    no mode for its caster to choose — every card but the modal instants and
    sorceries, and the three whose mode an opponent picks (CR 700.2e) — and
    otherwise each mode with a legal announcement right now, in printed order.

    The list is the engine's (`Game.announceable_modes`: the gates the cast
    path runs, with nothing named), so a mode this policy weighs is one some
    cast of it will not be refused for want of a target. Empty when no mode
    can be announced, which is a card not proposed rather than one proposed
    and refused.
    """
    if not caster_chooses_a_mode(card):
        return (None,)
    return tuple(game.announceable_modes(player_index, card))


def _note_modes_not_weighed(card: CardDefinition, modes: "tuple[int | None, ...]") -> None:
    """Tell whoever is listening (``ai_cast_trace``) which of *card*'s modes
    `_modes_weighed` left out: those with no legal announcement now."""
    if cast_trace.silent() or not caster_chooses_a_mode(card):
        return
    left = [
        index for index in range(len(compile_card_oracle(card).modes))
        if index not in modes
    ]
    if left:
        cast_trace.note(
            f"mode{'s' if len(left) > 1 else ''} {', '.join(map(str, left))} not"
            " weighed: no legal announcement now (Game.announceable_modes)"
        )


def _life_x_sizes(bound: int) -> list[int]:
    """The sizes of an X paid in life a cast is built at: the largest the
    reserve allows, and each half of it down to one, smallest first."""
    sizes: set[int] = set()
    size = bound
    while size >= 1:
        sizes.add(size)
        size //= 2
    return sorted(sizes)


def _cast_candidate_sized(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
) -> CastAction | None:
    """`_cast_candidate_offering` — and, for a spell whose X is **life**, the
    best of it built at each of a few sizes (`_life_x_sizes`), smallest first
    so that a tie keeps the life.

    The X used to be the largest the seat's reserve allows (`_pick_x_value`),
    which is the right answer for no board but the one where every point is
    damage that finishes the game. Hatred at ten paid ten life to put a 2/2
    through a 0/4 Wall it needed two more power to kill, measured as the loss
    it was, and was held; at two it kills the Wall. What each size is worth
    is the rehearsal's answer, the turn's fight fought where the cast is made
    before it (`_weighed_through_the_fight`), as for every other cast.
    """
    if not _pays_x_in_life(card):
        return _cast_candidate_offering(
            game, player_index, card, hand_index,
            from_zone=from_zone, extra_generic=extra_generic,
        )
    bound = _pick_x_value(
        game, game.players[player_index], card, extra_generic,
        hand_index=hand_index if from_zone == "hand" else None,
    )
    best: CastAction | None = None
    for size in _life_x_sizes(bound or 0) or [bound]:
        token = _LIFE_X_ASKED.set((card, size))
        try:
            candidate = _cast_candidate_offering(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic,
            )
        finally:
            _LIFE_X_ASKED.reset(token)
        if candidate is not None and (best is None or candidate.score > best.score):
            best = candidate
    return best


def _cast_candidate_offering(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
) -> CastAction | None:
    """`_cast_candidate` for the mode being weighed: CR 601.2b's optional
    costs, each answer tried as a whole candidate, most paid first."""
    announcements = _offer_announcements(game, player_index, card, hand_index, from_zone)
    if not announcements:
        return _cast_candidate_announcing(
            game, player_index, card, hand_index,
            from_zone=from_zone, extra_generic=extra_generic, offers=None,
        )
    for offers in announcements:
        token = _OFFERS_ANNOUNCED.set(offers)
        held = _HELD_AS_FLEETING.set(False)
        try:
            candidate = _cast_candidate_announcing(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic, offers=offers,
            )
            fleeting = _HELD_AS_FLEETING.get()
        finally:
            _HELD_AS_FLEETING.reset(held)
            _OFFERS_ANNOUNCED.reset(token)
        if candidate is not None:
            return candidate
        if fleeting:
            # Held because nothing it does outlasts the turn, with everything
            # paid for. The announcements still to try pay for less of the
            # same spell — a part of what was just found to leave nothing —
            # and each is a target weighed and a turn rehearsed: "Kicker {1}.
            # Prevent the next 2 damage … if this spell was kicked, prevent
            # the next 4 damage instead" (Orim's Touch) was read twice, every
            # decision of every turn it sat in a hand.
            cast_trace.note(
                f"offers {offers} left nothing by the end of the turn: the"
                " smaller answers were not tried"
            )
            return None
    return None


def _paid_for_half_names_nothing(
    game: Game, player_index: int, card: CardDefinition, offers: "dict[str, int]"
) -> bool:
    """Whether taking *offers* adds a target the board cannot supply.

    CR 702.33g gives a kicked-only part its targets only when the spell is
    kicked, so the two announcements have different specs -- and when the
    kicked one asks for something and the engine's own enumeration (the list a
    human's picker is built from) is empty, the kicker's whole effect is one
    that cannot happen.
    """
    program = compile_card_oracle(card)
    mode_index = _announced_mode(card)
    taken = derive_cast_spec(
        card, program, optional_cost_payments=offers, mode_index=mode_index,
        from_zone=_cast_zone(card),
    )
    declined = derive_cast_spec(
        card, program, optional_cost_payments={}, mode_index=mode_index,
        from_zone=_cast_zone(card),
    )
    if taken is None or taken == declined:
        return False
    if taken.get("kind") in ("none", "modal") or spec_roles(taken):
        return False
    return not game._enumerate_targets(
        player_index, card, taken, for_cast=True, optional_cost_payments=offers,
        mode_index=mode_index,
    )


def _paid_for_trigger_has_nothing_to_hit(
    game: Game, player_index: int, card: CardDefinition, offers: "dict[str, int]"
) -> bool:
    """Whether *offers* buys an entry trigger with no target on the side its
    effect wants.

    `_paid_for_half_names_nothing`'s question asked of **every** trigger an
    offer buys, not only of the one the cast's picker describes. A permanent
    printing two kickers (CR 702.33b) gates one entry trigger on each, and the
    second one's target is chosen when it is put on the stack (CR 603.3d) --
    where the choice is mandatory. So a Nightscape Battlemage that pays {2}{R}
    while only its own seat controls a land **must** destroy its own land, and
    a Thornscape Battlemage that pays {W} with one artifact on the table, its
    own, destroys that. Paying is legal and buys a loss; the announcement is
    declined and the caller falls back to the one without that cost.

    The side is the reading a seat nobody asks already gets on the stack
    (`_default_trigger_target_side`): `ability_target_side`, then the kind's
    family. The candidates are the engine's own enumeration. A trigger whose
    target is a player always has one, and one with no side has no wrong
    board to land on -- both are left to the cast.
    """
    for instruction in entry_triggers_bought(card, offers):
        spec = derive_instruction_spec([instruction])
        if (
            not isinstance(spec, dict)
            or spec.get("kind") in _NOT_OBJECT_SPECS
            or spec_roles(spec)
        ):
            continue
        side = ability_target_side(instruction) or activation_target_side(instruction)
        if side is None:
            continue
        legal = game._enumerate_targets(
            player_index, card, spec, for_cast=True,
            ability_instruction=instruction, triggered=True,
        )
        if any(entry.get("kind") != "permanent" for entry in legal):
            continue
        wanted = (
            {player_index} if side == "you"
            else {seat for seat in range(len(game.players)) if seat != player_index}
        )
        if not any(entry.get("seat") in wanted for entry in legal):
            return True
    return False


def _with_offer_payment(
    total: dict[str, int], payment: dict[str, int], times: int
) -> dict[str, int]:
    """*total* plus one way of paying an optional cost, *times* over.

    A copy, in *total*'s own key order with the payment's new symbols after
    it: the tap planner walks the dict it is handed, and a simulated game has
    to reproduce from its seed.
    """
    merged = dict(total)
    for symbol, amount in payment.items():
        merged[symbol] = merged.get(symbol, 0) + amount * times
    return merged  # _with_offer_payment


def _offers_taken(card: CardDefinition, offers: "dict[str, int] | None"):
    """``(offer, times)`` for every optional **mana** offer *offers* takes.

    Read back off ``additional_costs`` -- the table the cast path charges from
    -- so the mana planned here is the mana the cast will ask for. A non-mana
    price (``optional_key``) is not in this list: it is paid out of permanents,
    cards or life, and `_printed_costs_are_payable` asks the engine's gate
    about it.
    """
    taken = []
    for cost in additional_costs(card):
        for offer in cost.optional_mana:
            times = int((offers or {}).get(offer.symbols, 0) or 0)
            if times > 0:
                taken.append((offer, times))
    return taken


def _better_alternative(
    game: Game, player_index: int, card: CardDefinition, action: "CastAction",
    alternatives: list[tuple],
) -> "CastAction":
    """*action* taking whichever of *alternatives* — ``(taps, colours,
    alternative_cost_index)``, each a payable CR 118.9 alternative — its
    rehearsal measures more, the first on a tie, or the first when none can
    be rehearsed.

    A permanent's cast is worth what it puts on the battlefield, which is
    what the rehearsal reads — the face-down 2/2 a morph's {3} makes against
    the face-up creature a Dream Halls discard makes, less the card the
    discard spends — so it is asked of every card, not only a spell."""
    best, best_swing = None, None
    for taps, colours, index in alternatives:
        variant = replace(
            action, land_tap_indices=taps, land_tap_colors=colours,
            alternative_cost_index=index,
        )
        rehearsal = _rehearse_announcement(
            game, player_index, card, cast_announcement(variant), planned=variant,
        )
        rehearsal = _weighed_through_the_fight(
            game, player_index, card, cast_announcement(variant), rehearsal,
            planned=variant,
        )
        if rehearsal is None or not rehearsal.accepted:
            cast_trace.note(f"alternative cost {index}: not rehearsed or refused")
            continue
        cast_trace.note(f"alternative cost {index}: swing {rehearsal.swing:+.2f}")
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = variant, rehearsal.swing
    return best if best is not None else action


def _cast_naming_its_discards(
    game: Game, player_index: int, card: CardDefinition, action: "CastAction",
    offers: "dict[str, int] | None",
) -> "CastAction":
    """*action* naming the hand cards its printed additional discard is paid
    with (CR 601.2b: "As an additional cost to cast this spell, discard X
    cards", the Dreams; "discard a red or green card", Surge of Strength; a
    buyback taken, Forbid's) — or *action* as it is, for a cast charging no
    discard the payer chooses.

    The cards the seat least wants to lose, by the reading every discard it
    chooses takes (``ai_prompt_picks.discard_order``: a card whose madness
    cost the board can pay first, then the least ``discard_worth``), out of
    the engine's own payers (``Game._discard_cost_payers``, the spell's own
    slot left out) and as many as the announced X owes. Named nothing, the
    cast paid with the first cards the phrase names in hand order. A discard
    at random or of the whole hand is nobody's choice; only the first charged
    discard is named, which is every card in the pool."""
    from .ai_prompt_picks import discard_order

    taken = set(offers or ())
    charged = [
        cost for cost in additional_costs(card)
        if (cost.from_zone is None or cost.from_zone == action.from_zone)
        and (cost.optional_key is None or cost.optional_key in taken)
        and cost.discard_cards
    ]
    if not charged or charged[0].discard_at_random or charged[0].discard_whole_hand:
        return action
    cost = charged[0]
    spell_slot = action.hand_index if action.from_zone == "hand" else None
    payers = game._discard_cost_payers(player_index, cost, spell_hand_index=spell_slot)
    hand = game.players[player_index].hand
    slots = [
        position for position, held in enumerate(hand)
        if position != spell_slot and any(held is payer for payer in payers)
    ]
    owed = cost.discarded_count(action.x_value)
    if owed <= 0 or len(slots) < owed:
        return action
    chosen = discard_order(game, player_index, slots, None)[:owed]
    return replace(
        action, cost_hand_index=chosen[0], cost_other_hand_indices=chosen[1:] or None,
    )


def _cast_naming_its_sacrifice(
    game: Game, player_index: int, card: CardDefinition, action: "CastAction",
    offers: "dict[str, int] | None",
) -> "CastAction":
    """*action* naming the permanent its additional sacrifice is paid with,
    where the spell's effect reads what the sacrifice ate — or *action* as it
    is.

    "…sacrifice an artifact. Put X +1/+1 counters on target creature, where X
    is the sacrificed artifact's mana value." (Forge Armor.) Named nothing,
    the cast pays with the engine's deterministic pick, the smallest power
    first, and Forge Armor gave up a Great Furnace for no counter at all. So
    each distinct reading the board offers (``ai_sacrifice_victims``: one
    permanent per value, the cheapest to lose) is rehearsed as a cast of its
    own, the turn's fight read through it as for every cast, and the best one
    the engine takes is named — the cheapest on a tie. Not a permanent the
    cast names as a target: a sacrifice paid with its own target is a spell
    cast at nothing.

    Only a cast whose chosen-permanent price is that one sacrifice
    (``Game._chosen_cast_cost_demands``): a name is the whole announcement of
    what pays (CR 601.2h), so a second price beside it is left to the
    default rather than named for half.
    """
    from .ai_sacrifice_victims import (characteristic_read_off_the_sacrifice,
                                       victims_to_weigh)

    if card.primary_type not in SPELL_TYPES:
        return action
    characteristic = characteristic_read_off_the_sacrifice(
        _announced_steps(card, compile_card_oracle(card))
    )
    if characteristic is None:
        return action
    costs = tuple(
        cost for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == action.from_zone
    )
    demands = game._chosen_cast_cost_demands(costs, x_value=action.x_value, taken=offers)
    if len(demands) != 1 or demands[0][0] != "sacrifice" or demands[0][2] != 1:
        return action
    bound = _bind_action_slots(game, player_index, action)
    named = [bound.get("target"), *bound.get("targets", ()), *bound.get("divided", ())]
    named += [
        game.permanent_by_id(permanent_id)
        for permanent_id in (action.target_permanent_ids or ())
        if isinstance(permanent_id, int)
    ]
    candidates = [
        permanent
        for permanent in game._additional_cost_candidates(player_index, demands[0][1])
        if not any(permanent is other for other in named if other is not None)
    ]
    best, best_swing = action, None
    for victim in victims_to_weigh(candidates, characteristic, game.sacrifice_preference_key):
        variant = replace(action, cost_permanent_ids=[victim.permanent_id])
        rehearsal = _rehearse_announcement(
            game, player_index, card, cast_announcement(variant), planned=variant,
        )
        rehearsal = _weighed_through_the_fight(
            game, player_index, card, cast_announcement(variant), rehearsal,
            planned=variant,
        )
        if rehearsal is None or not _worth_proposing(rehearsal):
            cast_trace.note(f"sacrifice {victim.card.name}: not worth proposing")
            continue
        cast_trace.note(f"sacrifice {victim.card.name}: swing {rehearsal.swing:+.2f}")
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = variant, rehearsal.swing
    return best


def _cast_candidate_announcing(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
    offers: "dict[str, int] | None" = None,
) -> CastAction | None:
    """`_announced_candidate`, as one attempt of the decision's trace
    (``ai_cast_trace.attempt``): the mode, the offers and the size of an X
    paid in life it is built at are the ones being weighed — and an "any
    number of" sacrifice's provisional victims, for its target choosers
    (``ai_sacrifice_victims.sacrifices_weighed_provisionally``)."""
    with sacrifices_weighed_provisionally(game, player_index, card, from_zone, offers):
        if cast_trace.silent():
            return _announced_candidate(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic, offers=offers,
            )
        asked = _LIFE_X_ASKED.get()
        with cast_trace.attempt(
            game, player_index, card, mode_index=_announced_mode(card),
            offers=offers if _announces_any_offer(card, offers) else None,
            life_x=asked[1] if asked is not None and asked[0] is card else None,
            from_zone=from_zone, zone_index=hand_index,
        ):
            return _announced_candidate(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic, offers=offers,
            )


def _announced_candidate(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
    offers: "dict[str, int] | None" = None,
) -> CastAction | None:
    """`_cast_candidate` for one fixed answer to CR 601.2b's optional costs.

    One body for the hand, the command zone (CR 903.8) and every zone an
    effect opens (CR 601.3), because almost everything it checks is about the
    *card* and the board rather than about the zone. The zone contributes
    where the executor finds the card (`from_zone`, `hand_index`), what the
    cast additionally costs (*extra_generic*, the commander tax) and — for a
    cast an effect permits — what it is charged *instead* and which
    announcement says so: the permission being weighed, read where the price
    is (`_cost_for`, `_pick_x_value`) and where a gate takes a zone
    (`_cast_zone`).

    *offers* is the optional additional costs this candidate takes (None for a
    card that prints none): its mana is planned with the spell's, and an offer
    printing an {X} ("Kicker {X}") announces the largest X the lands can pay.
    """
    player = game.players[player_index]
    # The permission this cast would be made under, or None (see
    # `_cast_candidate`), and *hand_index* as a position **in the hand** —
    # which it is only for a hand cast. It indexes whatever zone the card is
    # in, and three readers below mean "the spell's own slot in hand, which
    # cannot pay for the spell" (CR 601.2a): a graveyard's index handed to
    # them would spare some unrelated hand card instead.
    under = cast_weighed(card)
    spell_hand_index = hand_index if from_zone == "hand" else None
    if (
        card.primary_type == "land"
        and game.enforce_mana_costs
        and not game._may_play_another_land(player_index)
    ):
        return cast_trace.dropped(
            "a land, and the seat has no land play left (CR 305.2)"
        )
    if not _can_cast_with_targets(game, player_index, card):
        return cast_trace.dropped(
            "no legal announcement: the engine's cast gates refuse it "
            "(_can_cast_with_targets)"
        )
    # CR 601.2's printed timing gates ("Cast this spell only during an
    # opponent's turn…"), through the table the cast path itself reads.
    # Asked here for the same reason every other gate in this function is:
    # a cast the engine will refuse is a turn the AI spends on nothing, and
    # it re-proposes the same card the next turn and the next. Siren's Call
    # did exactly that for ten consecutive turns once the simulator started
    # dealing whole sets.
    if check_cast_timing(game, player_index, (card.oracle_text or "").lower()):
        return cast_trace.dropped(
            "its printed timing forbids casting it now "
            "(cast_restrictions.check_cast_timing)"
        )
    # "Counter target spell **if it's red**": which spell, or no cast at all
    # when the guard holds for none of them (`_guarded_stack_target`). A
    # spell on the stack is only there to name at instant speed, or under a
    # cast a resolution offers (a madness counterspell); with none on it the
    # engine's gate above has already said no.
    stack_target = _guarded_stack_target(game, player_index, card) if game.stack else None
    if stack_target == ():
        return cast_trace.dropped("no spell on the stack meets its guard")

    # X first: an X-draw spell's target choice depends on how many cards it
    # would draw (a spell that empties your own library is aimed elsewhere),
    # so the value has to exist before the target is picked.
    x_value = _pick_x_value(
        game, player, card, extra_generic, hand_index=spell_hand_index,
    )
    if x_value == 0:
        return cast_trace.dropped("its X would be 0: a price paid for nothing")

    # CR 601.2h's printed **additional** costs, asked of the engine's own gate
    # for the reason every gate above is asked here: the cast path refuses a
    # spell whose additional cost the board cannot pay, nothing is spent, and
    # the AI re-proposes the same card every turn — which is precisely what
    # `simulate_ai_games.py`'s `refused_casts` counts.
    #
    # Below the X pick, because one of those costs is measured in X (Fire
    # Covenant's "pay X life") and asking before the announcement would gate on
    # a number nobody had chosen — the same ordering the cast path itself makes,
    # and for the same reason.
    #
    # This gap predates the narrowed discard that surfaced it: Village Rites
    # with no creature to sacrifice had the same shape and was refused ten turns
    # running. What made it visible was Surge of Strength, whose "discard a red
    # or green card" became payable-or-not the moment the clause was read at all.
    if not _printed_costs_are_payable(
        game, player_index, card, hand_index, from_zone, x_value, taken=offers
    ):
        return cast_trace.dropped(
            "its printed additional cost cannot be paid (CR 601.2h)"
        )
    # ...and what a required alternative cost asks beside its mana (CR 118.9b:
    # "Flashback—{1}{G}, Pay 3 life"), through the gate the cast path refuses
    # with. A cost that is only mana passes it, and its mana is the plan's
    # (`_cost_for`).
    if (
        under is not None
        and under.cost is not None
        and game._unpayable_alternative_cost(
            player_index, card, under.cost, spell_hand_index=spell_hand_index,
        ) is not None
    ):
        return cast_trace.dropped(
            "the permission's alternative cost cannot be paid beside its mana"
            " (CR 118.9b)"
        )
    # **A cost paid in life is not paid with the seat's last point.** CR 119.4
    # lets a player pay life equal to their total, the gates above accept it,
    # and the cast then ends its caster's game (CR 704.5a): "You may cast this
    # card from your graveyard by paying 3 life and discarding a card"
    # (Demonic Embrace) at three life, the moment a seat could cast from a
    # graveyard at all — and "As an additional cost to cast this spell, pay 3
    # life" (Fumarole, Withering Boon) from hand before that. Not a reserve:
    # a mandatory price is the spell's own, and a seat at four may still judge
    # it worth one. Just never the last.
    if _cast_life_price(card, from_zone, x_value, offers, under) >= player.life > 0:
        return cast_trace.dropped(
            "a cost paid in life would spend the seat's last point (CR 119.4, 704.5a)"
        )
    # Whether the mana is there at all, asked **before** any target is
    # weighed. The plan below asks it again with the offers' mana on top and
    # is what the cast is built from; this is the same question about the
    # printed cost alone, which every announcement of the card has to pay, so
    # a card it stops here is one the plan would have stopped anyway — and
    # weighing a target is a rehearsal apiece (`_choose_single_object_target`).
    if (
        game.enforce_mana_costs
        and card.primary_type != "land"
        and _plan_land_taps(
            game, player,
            _cost_for(game, player, card, x_value, extra_generic=extra_generic),
        ) is None
        and (
            _announces_any_offer(card, offers)
            or not _alternative_cost_is_payable(game, player_index, card, hand_index)
        )
    ):
        return cast_trace.dropped(
            "unaffordable: the lands cannot pay the printed cost (with offers "
            "announced, or with no alternative cost payable)"
        )
    target = _choose_target_for_spell(card, player_index, game, x_value)
    target_permanent_index: int | list[int] | None = None
    target_permanent_ids: list[int] | None = None
    divided_targets: list[tuple] | None = None
    # The spell a **stack role** names (see `_choose_role_targets`); None for
    # every cast whose announcement has no such role.
    role_stack_index: int | None = None
    # …and the roles announcement itself, one answer per role
    # (`CastAction.target_role_refs`); None for a spell naming no roles.
    role_refs: list[dict] | None = None
    # A text change's two words (`CastAction.old_color` / ``new_color``).
    text_words: tuple = (None, None)
    if aura_enchant_noun(card) is not None:
        aura_choice = _choose_aura_target(game, player_index, card)
        if aura_choice is None:
            # Aura spells require a legal target (Rule 115.1b)
            return cast_trace.dropped("an Aura with no legal object to enchant (CR 303.4a)")
        target, target_permanent_index = aura_choice
    elif (divided := choose_divided_targets(game, player_index, card, x_value)) is not None:
        # CR 601.2d, and it is the *whole* target choice for a divided spell —
        # asked before the two choosers below rather than beside them, because
        # Contagion and Bounty of the Hunt print a target count and so reach
        # `_choose_several_targets`, which would put a second, unrelated list of
        # targets on the same cast. The division is what the handler reads.
        if not divided:
            # No lawful announcement exists (CR 601.2d wants one target or
            # more). Skipped rather than cast: the cast gate refuses it, and a
            # seat that re-proposes a refused card every turn is what
            # `simulate_ai_games.py`'s `refused_casts` counts.
            return cast_trace.dropped(
                "a divided spell with no lawful division (CR 601.2d)"
            )
        divided_targets = list(divided)
    else:
        roles = _choose_role_targets(game, player_index, card)
        if roles is not None:
            if roles == ():
                # A roles spell with no legal chain of targets. Skipped
                # rather than cast: CR 601.2c needs every role filled, and
                # the cast gate would refuse it — an AI turn spent on an
                # action the game then rejects.
                return cast_trace.dropped(
                    "a spell naming roles with no legal chain of targets (CR 601.2c)"
                )
            (
                target, target_permanent_index, target_permanent_ids,
                role_stack_index, role_refs,
            ) = roles
        else:
            several = _choose_several_targets(
                game, player_index, card, x_value=x_value, preferred_seat=target,
            )
            if several == ():
                # The announced count has no legal set of targets on the side
                # the effect wants (CR 601.2c). Not proposed.
                return cast_trace.dropped(
                    "no legal set of targets on the side the effect wants for the "
                    "announced count (CR 601.2c)"
                )
            if several is not None:
                target, target_permanent_index, target_permanent_ids = several
                # --- W2G2: "X target creatures" names exactly X (CR 601.2c) ---
                # X was sized above as the most the lands could pay, before any
                # target existed; the cast gate now counts the targets against
                # it (`legality_cast_gates.cast_target_count_refusal`). So X is the number
                # of targets this board supplied, never more — the seat used to
                # announce X=5, name one creature and pay for five. The cost
                # below is planned against this X.
                if _names_x_targets(card):
                    x_value = len(target_permanent_index)
                # --- end W2G2 ---------------------------------------------------
            elif (chosen := choose_object_or_spell(
                game, player_index, card, target, x_value=x_value,
            )) is not None:
                # "Target spell or permanent" (a Lace, a text change) and a
                # text change's words: the object and the words weighed
                # together (`ai_text_changes`), or nothing worth the card.
                if chosen == ():
                    return cast_trace.dropped(
                        "no spell or permanent worth naming, or no words worth changing"
                        " (ai_text_changes)"
                    )
                target = chosen.seat
                target_permanent_index = chosen.permanent_index
                target_permanent_ids = chosen.permanent_ids
                role_stack_index = chosen.stack_index
                text_words = (chosen.old_color, chosen.new_color)
            else:
                single = _choose_single_object_target(
                    game, player_index, card, target, x_value=x_value,
                )
                if single == ():
                    # The side the effect wants holds no legal target, so the
                    # cast would resolve doing nothing — or doing it to the
                    # caster's own permanent. Skipped rather than proposed.
                    return cast_trace.dropped(
                        "no legal target on the side the effect wants"
                    )
                if single is not None:
                    target, target_permanent_index, target_permanent_ids = single
    # "Exile target card from a graveyard" (Coffin Purge): whose graveyard,
    # named — see `ai_targets._graveyard_denial_target`. Only where nothing above named
    # an object, which for a spell whose one target is a graveyard card is
    # always.
    if target_permanent_index is None and divided_targets is None:
        buried = _cast_graveyard_denial(game, player_index, card)
        if buried is not None:
            target, target_permanent_index = buried
        # …and a card it returns ("Return target creature card from your
        # graveyard to the battlefield"): the one worth most back that can
        # arrive there (`ai_graveyard_returns.cast_graveyard_return`). Named
        # nothing, the handler took the first card in the pile.
        elif (returned := cast_graveyard_return(game, player_index, card)) is not None:
            target, target_permanent_index = returned
    # The spell a cast whose target **is** a spell names: a role's or a
    # "spell or permanent"'s choice above, the guard's, or — with no guard to
    # choose by — the one whose answer its rehearsal measures most
    # (`_chosen_stack_target`). After the mana is known to be there, because
    # each candidate spell is a rehearsal.
    if role_stack_index is not None:
        stack_target = role_stack_index
    elif stack_target is None and game.stack:
        stack_target = _chosen_stack_target(game, player_index, card, target)
        if stack_target == ():
            return cast_trace.dropped("no spell on the stack worth naming")
    # "…that player must choose at least one Flagbearer on the battlefield if
    # able" (Standard Bearer): the announcement chosen above, held to what an
    # opponent's permanent demands of it — re-aimed where this seat can obey on
    # the board it already chose, not proposed where it cannot.
    aimed = _aimed_under_target_requirements(
        game, player_index, card, from_zone,
        target, target_permanent_index, target_permanent_ids, divided_targets,
    )
    if aimed is None:
        return cast_trace.dropped(
            "it cannot obey what an opponent's permanent demands of its targets "
            "(Standard Bearer)"
        )
    target, target_permanent_index, target_permanent_ids, divided_targets = aimed
    # "Destroy target artifact **with mana value X**" (Detonate): the target
    # fixes X, and the cast gate refuses an X that does not match it. X was
    # sized above as the most the lands could pay, before any target existed,
    # so the AI announced X=5 at a one-mana artifact and was refused — a
    # refusal free mana made rare and enforced costs made routine. The X is
    # the target's (`_x_implied_by_target`, the gate's own reading), and the
    # cost below is planned against that X, so an unaffordable target is a
    # cast not proposed rather than one refused.
    if x_value is not None and isinstance(target_permanent_index, int):
        implied = game._x_implied_by_target(card, target, target_permanent_index, None)
        if implied is not None:
            x_value = implied
    elif x_value is not None and isinstance(stack_target, int) and 0 <= stack_target < len(game.stack):
        # ...and "Counter target spell with mana value X" (Spell Blast): the
        # spell named fixes it, read off the same gate.
        implied = game._x_implied_by_target(card, target, None, game.stack[stack_target])
        if implied is not None:
            x_value = implied
    if not _caster_can_make_its_sacrifices(game, player_index, card):
        # "Sacrifice a creature. Rupture deals damage equal to that creature's
        # power…": with nothing to sacrifice the whole resolution is nothing.
        return cast_trace.dropped(
            "it cannot make the sacrifice its own resolution asks for"
        )
    if _entry_gate_gives_back_more_than_it_brings(game, player_index, card):
        # "When this creature enters, return a red or green creature you
        # control to its owner's hand" with no other such creature — the cast
        # ends with the card back in hand and the mana spent — or with only a
        # dearer one to give back.
        return cast_trace.dropped(
            "its entry gives back more than it brings (a creature returned to hand)"
        )
    if not _caster_holds_a_hand_pick_entrant(
        game, player_index, card, spell_hand_index
    ):
        # "Each player chooses a card in their hand. … The owner of each
        # creature card revealed this way with the lowest mana value puts it
        # onto the battlefield." With no creature card of its own to pick, the
        # caster's Stronghold Gambit can only hand the opponent a free one.
        return cast_trace.dropped(
            "the caster holds no creature card to pick for the hand-pick entry"
        )
    if _exchange_shrinks_the_library(game, player_index, card):
        # "Exchange your graveyard and library." With fewer cards in the
        # graveyard than in the library the cast is turns given away.
        return cast_trace.dropped(
            "exchanging graveyard and library would shrink the library"
        )
    tap_indices: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    # CR 118.9a, where several alternatives apply: each payable one as
    # ``(taps, colours, its index)`` — weighed against each other below, by
    # rehearsal, once the cast they would make is built.
    alternatives: list[tuple] = []

    # CR 601.2b: a cast made under a permission that requires an alternative
    # cost announces it (`PermittedCast.alternative_cost`) — that is what the
    # cast path picks the permission by, and so what it charges.
    alternative_cost = under is not None and under.alternative_cost
    taken_offers = _offers_taken(card, offers)
    announces_offer = _announces_any_offer(card, offers)
    if announces_offer and _paid_for_half_names_nothing(
        game, player_index, card, offers
    ):
        # The half the offer buys has a target and the board has none for it
        # (a kicked Tolarian Emissary with no enchantment anywhere). Paying is
        # legal and buys nothing, so this candidate is declined and the caller
        # falls back to the plain cast.
        return cast_trace.dropped(
            "the half the offers buy names nothing the board has (CR 702.33g)"
        )
    if announces_offer and _paid_for_trigger_has_nothing_to_hit(
        game, player_index, card, offers
    ):
        # ...and the same for a trigger the picker does not describe: the
        # second of a Battlemage's two, whose target is chosen on the stack and
        # would have to be the caster's own permanent.
        return cast_trace.dropped(
            "a trigger the offers buy would have to hit the caster's own permanent"
        )
    sized_offer = next((offer for offer, _times in taken_offers if offer.x_count), None)
    if sized_offer is not None and not game.enforce_mana_costs:
        # A free X has no ceiling to size it by, and "the most the lands can
        # pay" is the only rule this policy has for one. Declined.
        return cast_trace.dropped(
            "an offer's X has no ceiling with mana costs unenforced"
        )
    if game.enforce_mana_costs and card.primary_type != "land":
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) The
        # mana clause of a price that is not only mana, which `_offers_taken`
        # does not list — it is one clause of an offer, not an offer. Planned
        # with the spell's own mana for the reason the offers below are: the
        # cast folds it into the one payment, so a plan without it taps three
        # lands for a six-mana announcement and is refused.
        for cost in additional_costs(card):
            if (
                cost.mana_symbols
                and cost.from_zone in (None, from_zone)
                and int((offers or {}).get(cost.optional_key, 0) or 0) > 0
            ):
                required = dict(required)
                for symbol, amount in cost.mana_cost.items():
                    required[symbol] = required.get(symbol, 0) + amount
        if taken_offers:
            # The offers' mana on top of the spell's, planned as one payment
            # because it is paid as one (`casting.queue_from_hand` folds an
            # optional cost into the same mana) — each offer as many times as
            # it is announced. For an offer printing an {X} the X is sized
            # here, largest first, exactly as `ai_payment._max_affordable_x` sizes a mana
            # cost's -- and an X of zero is not proposed, for the reason
            # `x_value == 0` is refused above: it is a price paid for nothing.
            #
            # Each offer through ``payments_at``, every way it may be paid at
            # that X: Emblazoned Golem's X is one mana of each of X colours,
            # so the plan has to be for coloured pips the lands can make, and
            # an X no choice of colours pays is passed over for a smaller one.
            sized = None
            for offer_x in (range(15, 0, -1) if sized_offer is not None else (None,)):
                totals = [dict(required)]
                for offer, times in taken_offers:
                    totals = [
                        _with_offer_payment(total, payment, times)
                        for total in totals
                        for payment in offer.payments_at(offer_x)
                    ]
                total = next(
                    (
                        candidate for candidate in totals
                        if _plan_land_taps(game, player, candidate) is not None
                    ),
                    None,
                )
                if total is not None:
                    sized = (offer_x, total)
                    break
            if sized is None:
                return cast_trace.dropped(
                    "unaffordable with the offers' mana on top (no X the lands can pay)"
                )
            if sized_offer is not None:
                x_value = sized[0]
            required = sized[1]
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            if announces_offer or under is not None:
                # *under*: the price planned was already the permission's — a
                # flashback cost, a waiver, a card played out of another zone
                # — and CR 118.9a allows no second alternative cost beside
                # one. (A printed alternative cost taken from an opened
                # graveyard is a cast this policy does not make.)
                return cast_trace.dropped(
                    "unaffordable: the planned price was already the offers' or the"
                    " permission's, and no second alternative cost is allowed"
                    " (CR 118.9a)"
                )
            # CR 118.9: the mana cost is not the only price. A spell whose
            # printed alternative cost this board *can* pay is castable right
            # now, and a seat that only ever asked the mana question sat on
            # Force of Will all game — the same "does nothing for the rest of
            # the game" shape `refused_casts` counts, one step earlier, where
            # nothing is even proposed.
            #
            # Asked only when the mana cost cannot be paid, which is the
            # conservative reading of CR 118.9b's "generally optional": paying a
            # life and exiling a card is a real price, and a seat that took it
            # while holding the mana would be spending two resources to save
            # none.
            # CR 118.9d: the cost increases in force are "applied to that
            # alternative cost", so a pitch spell under Sphere of Resistance
            # owes {1} beside its card and its life. Planned here for the
            # reason the mana cost above is — the cast spends the pool, and a
            # proposal with nothing tapped behind it is refused, the same card
            # every turn — and through the one reader the offer's `payable`
            # and the castable highlight price the same announcement with.
            #
            # **Each applicable alternative that can be paid** (CR 118.9a
            # applies one, the caster's choice): a morph card's face-down {3}
            # beside Dream Halls' discard is two casts, and the one made is
            # the one its rehearsal measures more (below). Named by index
            # where several apply, or the cast path refuses the cast.
            several = len(game.applicable_alternative_costs(player_index, card)) > 1
            for index in payable_alternative_indices(game, player_index, card, hand_index):
                plan = _alternative_cost_tap_plan(
                    game, player_index, card, extra_generic=extra_generic,
                    index=index if several else None,
                )
                if plan is not None:
                    alternatives.append((*plan, index if several else None))
            if not alternatives:
                return cast_trace.dropped(
                    "unaffordable: neither the mana cost nor any alternative cost can "
                    "be paid (CR 118.9)"
                )
            tap_indices, tap_colors, _named = alternatives[0]
            alternative_cost = True
        else:
            tap_indices, tap_colors = plan
            # "You may pay {W}{U}{B}{R}{G} rather than pay this spell's mana
            # cost" (the Bringers, Fist of Suns): an alternative price in
            # **mana alone**, and less of it, is taken even with the mana cost
            # payable — the same resource, fewer of it, and the lands it
            # leaves are the turn's next spell. Not beside an offer or a
            # permission's price (CR 118.9a: one alternative cost), nor for an
            # X the caster sized (CR 107.3b: X would be 0). Out of a graveyard
            # Yawgmoth's Will opened as out of the hand (the zone-cast census'
            # claim: what a seat announces from its hand it announces there).
            if (
                not announces_offer and not x_value
                and permission_leaves_the_price(game, player_index, under)
            ):
                several = len(game.applicable_alternative_costs(player_index, card)) > 1
                for index in cheaper_mana_alternative_indices(
                    game, player_index, card,
                    hand_index if from_zone == "hand" else None, required,
                    extra_generic=extra_generic,
                ):
                    cheaper = _alternative_cost_tap_plan(
                        game, player_index, card, extra_generic=extra_generic,
                        index=index if several else None,
                    )
                    if cheaper is not None:
                        alternatives.append((*cheaper, index if several else None))
                if alternatives:
                    tap_indices, tap_colors, _named = alternatives[0]
                    alternative_cost = True

    action = CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=tap_indices,
        score=0.0,
        hand_index=hand_index,
        **target_keywords(
            game, cast_target_zone(card, mode_index=_announced_mode(card)),
            player_index, target, target_permanent_index, target_permanent_ids,
        ),
        from_zone=from_zone,
        zone_seat=_zone_seat(player_index, under),
        alternative_cost=alternative_cost,
        divided_targets=divided_targets,
        land_tap_colors=tap_colors,
        optional_cost_payments=dict(offers) if announces_offer else None,
        mode_index=_announced_mode(card),
        target_stack_index=stack_target,
        target_role_refs=role_refs,
        old_color=text_words[0],
        new_color=text_words[1],
        alternative_cost_index=alternatives[0][2] if alternatives else None,
    )
    if len(alternatives) > 1:
        action = _better_alternative(game, player_index, card, action, alternatives)
    # "…where X is the sacrificed artifact's mana value" (Forge Armor): the
    # victim weighed, where the effect reads what the sacrifice ate.
    action = _cast_naming_its_sacrifice(game, player_index, card, action, offers)
    # …how many an "any number of" sacrifice eats, where the effect counts them.
    action = cast_naming_its_sacrifices(game, player_index, card, action, offers)
    # …and the hand cards a printed discard is paid with.
    action = _cast_naming_its_discards(game, player_index, card, action, offers)
    # **What the cast would do, asked of the engine** — for a spell, whose
    # whole worth is its resolution. The finished announcement is carried out
    # on a scratch copy of the game (`_rehearse_announcement`) and three
    # things are read off it: whether the engine takes the cast at all,
    # whether the resolution changes anything, and how far it moves this seat
    # against the table. A cast that fails any of them is not proposed —
    # which is every "legal and useless" cast this function used to make one
    # gate at a time: a discard at an empty hand, a sweeper with nothing to
    # sweep, a guard that cannot hold, a removal spell whose only target is
    # the caster's own. The swing is the score.
    #
    # **At instant speed a permanent is rehearsed too**, and the reading is
    # the moment's (`ai_scoring.read_at_instant_speed`): measured against what
    # happens with nothing cast — the spell on the stack resolving, the
    # declared combat dealing its damage — which is the whole of what a
    # counterspell, a pump in a block or a creature flashed in at an end step
    # is worth; and nothing is cast whose every trace is gone by the end of
    # the turn (`held_at_instant_speed`), or that scores under the floor
    # (`ai_cast_score.kept_above_the_floor`). The seat's own main phase is
    # where such a card is still worth a cast.
    rehearsal = None
    instant = weighed_at_instant_speed()
    if card.primary_type in SPELL_TYPES or instant:
        rehearsal = _rehearse_announcement(
            game, player_index, card, cast_announcement(action), planned=action,
        )
        # ...and, for a cast made before the fight whose good is this turn's
        # only, what it does to the fight.
        rehearsal = _weighed_through_the_fight(
            game, player_index, card, cast_announcement(action), rehearsal,
            planned=action,
        )
        if instant:
            rehearsal, held = read_at_instant_speed(
                game, player_index, card, action, rehearsal,
            )
            if held is not None:
                return cast_trace.dropped(held)
        if (refused := not_worth_proposing(rehearsal)) is not None:
            if rehearsal is not None and rehearsal.accepted and rehearsal.fleeting:
                _HELD_AS_FLEETING.set(True)
            return cast_trace.dropped(refused)
        if rehearsal is None and _names_an_unweighed_seat(game, player_index, card):
            return cast_trace.dropped(
                "no rehearsal could be run, and the cast would name one seat of several"
                " unweighed"
            )
        if instant and (held := held_at_instant_speed(rehearsal)) is not None:
            return cast_trace.dropped(held)
    elif (
        (body_needs_the_board(card) or entry_may_remove_itself(card))
        and not cast_announces_morph(game, player_index, card, action)
    ) or arrival_needs_the_board(game, card):
        # ...and for a creature whose toughness a characteristic-defining
        # ability fills in (CR 604.3), whether it **survives its arrival**:
        # the board sizes it, and an empty one makes Ancient Ooze a 0/0 that
        # dies as it enters (CR 704.5f) — cast so twice in seed 4242 (W1G4),
        # because a permanent's score is what it is and nothing asked what
        # the board would make of it. Not asked of a face-down cast, whose
        # body is the 2/2 (CR 708.2a). The same question of a **printed**
        # toughness under a board-wide static that lowers it — or of a
        # permanent that carries one (`arrival_needs_the_board`, kg4). And of
        # a permanent whose own entry trigger can sacrifice it unless a price
        # is paid (`ai_valuation.entry_may_remove_itself`): an 8/8 Primeval
        # Force cast with two Forests, or a Phyrexian Dreadnought beside no
        # creature, is a card gone as it arrives (8ED). A face-down cast has
        # no such trigger (CR 708.2a).
        if not _arrives_to_stay(_rehearse_announcement(
            game, player_index, card, cast_announcement(action), planned=action,
        )):
            return cast_trace.dropped(
                "the rehearsed permanent is refused, or does not survive its arrival"
            )
    return kept_above_the_floor(
        finished_cast_candidate(game, player_index, card, action, rehearsal)
    )
