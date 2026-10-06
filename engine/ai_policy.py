from __future__ import annotations

from contextvars import ContextVar
from itertools import product
from dataclasses import dataclass
import re

from .ai_valuation import (
    OFFER_ALTERS,
    OFFER_KICKS,
    OFFER_RETURNS_SPELL,
    SPELL_TYPES,
    CastOffer,
    cast_offers,
    activation_target_side,
    entry_sacrifice_is_unavoidable,
    entry_self_return_gate,
    entry_trigger_seat_side,
    entry_trigger_target_side,
    entry_triggers_bought,
    ability_denies_its_target,
    ability_target_side,
    cards_drawn_by_controller,
    cards_drawn_by_target,
    caster_sacrifice_steps,
    castable_commanders,
    counters_a_spell,
    destroyed_permanent_filter,
    divided_shape,
    foreign_activation_use,
    hand_entry_steps,
    harms_its_own_source,
    instruction_target_side,
    is_mana_ability,
    mana_ability_amount,
    mana_ability_symbols,
    offer_trade,
    planned_mana_yield,
    returns_creature_to_hand,
    role_target_sides,
    several_target_slot_sides,
    source_becomes_an_aura,
    source_toughness_change,
    spell_denies_its_own_target,
    spell_hand_pick_entry_filters,
    spell_target_side,
    spell_makes_its_target_lose_life,
    TollLoss,
    toll_branch_loss,
)
from .activation_permissions import activation_permission_denial
from .activation_restrictions import activation_denial, global_activation_ban
from .cast_costs import additional_costs, cast_announces_x
from .cast_prohibitions import cast_prohibition
from .cast_restrictions import check_cast_timing
from .cost_modifiers import (cost_reduction_for_cast, reduce_cost,
                             sacrifice_taxes, spell_cost_tax, spell_symbol_tax)
from .classifier import classify_card
from .faces import castable_faces, spell_named
from .game import Game
from .handlers._common import permanent_matches_filter
from .mixins.stack import (aura_enchant_noun, enchant_noun_seat,
                           permanent_matches_enchant_noun)
from .target_restrictions import forbidden_target
from .auras import aura_restriction_active
from .combat_permissions import MUST_BLOCK_ATTACKERS_UNTIL_EOT
from .models import CardDefinition, Permanent, PlayerState
from .oracle import OracleInstruction, compile_card_oracle
from .oracle_types import cost_target_count, x_spend_colors_from_text
from .search_filters import search_matches, searched_seat
from .subject_filters import subject_matches
from .activation_zones import HAND
from .targeting import (bounce_subject_filter, cast_target_slot,
                        derive_activation_spec,
                        derive_cast_spec, derive_instruction_spec,
                        instructions_as_announced, role_is_seat,
                        spec_is_a_cost, spec_roles,
                        usable_activated_abilities)

_MANA_SYMBOLS = ("W", "U", "B", "R", "G", "C")


@dataclass(frozen=True)
class CastAction:
    card_name: str
    target_player_index: int
    x_value: int | None
    land_tap_indices: tuple[int, ...]
    score: float
    hand_index: int
    # One chosen permanent, or several for a spell that names "up to N target"
    # objects. The same shape ``queue_from_hand`` and the stack already speak, so
    # the executors in web/game_flow.py forward it unchanged.
    target_permanent_index: int | list[int] | None = None
    # The same choices as stable ids, when the slots do not all sit on one
    # battlefield. ``target_permanent_index`` is positional on
    # ``target_player_index``, so a two-board pick (Rookie Mistake's "target
    # creature … another target creature") cannot be expressed by it — the gap
    # round 40 closed on the wire, arriving here through the AI.
    target_permanent_ids: list[int] | None = None
    # Which zone ``hand_index`` indexes into, in the vocabulary the cast path
    # already speaks ("hand" / "command", `_cast_onto_stack`'s `from_zone`).
    # "command" is a commander cast (CR 903.8); every executor forwards it
    # unchanged, so an ordinary duel — where nothing but "hand" is ever
    # proposed — is untouched.
    from_zone: str = "hand"
    # CR 118.9: pay the spell's printed alternative cost rather than its mana
    # cost. False on every candidate this policy builds from a payable mana
    # cost, which is all of them but one shape — see `_alternative_cost_cast`.
    alternative_cost: bool = False
    # CR 601.2d's announcement, for a spell that divides damage or counters
    # among its targets: ``(seat, permanent index or None[, share])`` per
    # target, the same list the browser's division prompt sends. The field did
    # not exist, so **every** divided spell the AI cast announced no division at
    # all — Spoils of War, Contagion and Bounty of the Hunt resolved putting no
    # counters anywhere, and Pyrokinesis, Fire Covenant and Dwarven Catapult,
    # which name only creatures, dealt their damage to a player's face. See
    # `choose_divided_targets`.
    divided_targets: list[tuple] | None = None
    # The colour to ask each land in ``land_tap_indices`` for, position for
    # position (`_plan_land_taps`). The tap seam takes one
    # (`tap_land_for_mana(chosen_color=…)`) and every executor sent the default
    # "G", so a dual or a land under Harvest Mage made whatever that default
    # mapped to rather than what the plan had counted on. Empty means no
    # colour was planned, and an executor keeps the seam's default.
    land_tap_colors: tuple[str, ...] = ()
    # CR 601.2b's optional additional costs this cast takes, as the map the
    # cast path reads (``optional_cost_payments``: canonical symbols -> times).
    # None for every candidate that takes none. The field did not exist, so no
    # AI seat ever paid a buyback or a kicker: a kicked-only half of a card was
    # text the simulator could not reach. See `_cast_candidate`.
    optional_cost_payments: dict[str, int] | None = None


@dataclass(frozen=True)
class ActivationAction:
    permanent_name: str
    permanent_index: int
    target_player_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # The chosen permanent on `target_player_index`'s battlefield, for an
    # ability that targets one (an equip's creature). None for the abilities
    # whose handlers pick for themselves, which is every other one this policy
    # activates today.
    target_permanent_index: int | None = None
    # One chosen object per **role**, for an ability naming several targets of
    # different kinds (Goblin Welder's artifact and artifact card). The field
    # beside this one cannot carry them: they may sit on two battlefields, or —
    # here for the first time — in two different *zones*, which one seat and one
    # index cannot say. None for every other ability.
    target_role_refs: list[dict] | None = None
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()
    # Whose battlefield the permanent is on, when that is **not** the
    # activator's: "Any player may activate this ability" (CR 602.1b). None is
    # the activator's own — every action but `choose_foreign_activation_action`'s.
    # `permanent_index` counts into this seat's battlefield, which is what
    # `activate_permanent_ability(source_controller_index=…)` reads it against.
    source_controller_index: int | None = None
    # Which of the permanent's usable abilities. None is the engine's default
    # (the first one it can pay for); a foreign activation names it, because
    # the ability worth activating on an opponent's Flailing Soldier is its
    # *second* ("-1/-1"), not its first ("+1/+1").
    ability_index: int | None = None


@dataclass(frozen=True)
class HandActivationAction:
    """An ability activated from a card **in the seat's hand** (CR 113.6j).

    Cycling (CR 702.29a) is why this exists: 34 of Urza's Saga's cards compile
    to "[Cost], Discard this card: Draw a card.", and every one of them is a
    card an AI seat holds and never plays. A seat with no way to reach the hand
    is a seat doing nothing with a third of the set — the same shape a refused
    cast makes, but quieter, because nothing is even proposed.

    A separate action from :class:`ActivationAction` rather than a nullable
    field on it, because the two are executed by different engine entry points
    (``activate_from_hand`` takes no permanent, no target and no summoning
    sickness) and every existing reader of ``ActivationAction`` would have had
    to learn which shape it was holding.
    """

    card_name: str
    hand_index: int
    ability_index: int
    land_tap_indices: tuple[int, ...]
    score: float
    # See `CastAction.land_tap_colors`.
    land_tap_colors: tuple[str, ...] = ()


def planned_tap_color(action, position: int) -> str:
    """The colour an executor asks the *position*-th planned land for.

    The plan's own colour where it has one (``land_tap_colors``), and otherwise
    the tap seam's default, which is what every executor sent before the plan
    carried colours — so an action built without them taps exactly as it did.
    """
    colors = getattr(action, "land_tap_colors", ()) or ()
    return colors[position] if position < len(colors) else "G"


def planned_tap_ability(game: Game, land: Permanent, color: str) -> int | None:
    """Which of *land*'s mana abilities makes *color* — an index for
    ``tap_land_for_mana(ability_index=…)`` — or None for the seam's default.

    CR 605: each mana ability is its own ability, and the tap seam runs the
    land's **first** tap-alone one unless told which. For a painland that is
    "{T}: Add {C}", so a plan that counted a Karplusan Forest or an
    Underground River as a coloured mana tapped it for {C} and the spell was
    refused "insufficient mana" — every turn, once the simulator enforced
    costs. None whenever the default already makes the colour (a basic, a
    dual, City of Brass, a land under a swap the seam applies to any ability),
    so every land that tapped correctly taps exactly as it did.
    """
    from .mixins.turn_management import is_tap_alone_mana_ability

    free, _priced = game._land_mana_abilities(land)
    if free is None or color in mana_ability_symbols(free):
        return None
    usable = usable_activated_abilities(compile_card_oracle(game.playable_card_of(land)))
    for index, ability in enumerate(usable):
        if not is_tap_alone_mana_ability(ability):
            continue
        if color in mana_ability_symbols(ability.instruction) and (
            game.land_mana_tap_refusal(land, index) is None
        ):
            return index
    return None


def tap_planned_lands(game: Game, seat: int, action) -> None:
    """Tap the mana sources *action*'s plan names into *seat*'s pool, each for
    the colour the plan counted on and through the mana ability that makes it.

    **The AI's payment**, shared by every executor — the simulator's and the
    web app's AI seat — so the two pay the same way: the policy plans the taps
    (`_plan_land_taps`), this fills the pool, and the cast or activation that
    follows spends it (CR 601.2g-h). Every slot is resolved to its permanent
    before the first tap and tapped **by id**, so a tap that moved anything
    cannot shift a later slot onto a different permanent.

    A **land** goes through the engine's tap seam. A **non-land** source the
    plan counted (`_nonland_mana_source`: Sol Ring, a Mox, Llanowar Elves) has
    no seam — CR 605.1a makes its "{T}: Add …" an activated ability like any
    other — so it is activated, which for a mana ability resolves inline
    (CR 605.3b) and leaves the mana in the pool exactly as a land's tap does.
    """
    planned = [game.permanent_at(seat, index) for index in action.land_tap_indices]
    for position, land in enumerate(planned):
        permanent_id = game.permanent_id_of(land)
        if permanent_id is None:
            continue
        color = planned_tap_color(action, position)
        source = _nonland_mana_source(game, seat, land)
        if source is not None:
            slot = next(
                (
                    index for index, permanent in enumerate(game.controlled_by(seat))
                    if permanent is land
                ),
                None,
            )
            if slot is None:
                continue
            game.activate_permanent_ability(
                seat, land.card.name,
                permanent_index=slot,
                ability_index=source.ability_index,
                # "Any color" is one of the five (CR 105.1): a source asked for
                # the {C} a generic cost was planned at names no colour, and
                # the ability's own default answers.
                mana_color=color if color in ("W", "U", "B", "R", "G") else None,
            )
            continue
        game.tap_land_for_mana(
            seat, land.card.name,
            chosen_color=color,
            permanent_id=permanent_id,
            ability_index=planned_tap_ability(game, land, color),
        )


@dataclass(frozen=True)
class _NonlandManaSource:
    """One non-land permanent's mana ability as the payment plan counts it."""

    #: Which of the permanent's usable abilities — the index the activation
    #: path addresses one by.
    ability_index: int
    #: Every symbol one activation may be asked for, the unasked one first.
    symbols: tuple[str, ...]
    #: How many mana of the asked symbol.
    amount: int
    #: A fixed run of different symbols, or None (`_land_mixed_run`'s shape).
    run: "dict[str, int] | None" = None


def _nonland_mana_source(
    game: Game, seat: int, permanent: "Permanent | None"
) -> "_NonlandManaSource | None":
    """The mana ability of a **non-land** permanent *seat* controls that its
    payment plan may count right now, or None.

    **The AI never tapped anything but a land for mana.** `_plan_land_taps`
    asked the tap seam's gate of every permanent, and that gate's first line
    refuses a non-land — so the Moxen, Sol Ring, Llanowar Elves, Birds of
    Paradise and the rest were cast (`mana_ability_amount` scores them) and
    then sat untapped for the whole game: 64 "{T}: Add …" abilities on 63
    permanents across both manifest roles, 62 of them shipped, and in ten
    seeded Alpha games nineteen such permanents entered the battlefield and
    none made a mana.

    **Only an ability whose whole cost is {T}** (`is_tap_alone_mana_ability`,
    the tap seam's own predicate — which also excludes a printed "Activate
    only …" and an ability that asks another player something). A mana ability
    with a further cost is not free mana: "{1}, {T}: Add one mana of any
    color" (Mana Cylix) spends one to make one, "{T}, Sacrifice this artifact"
    (Black Lotus) and "Sacrifice this creature" (Morgue Toad) spend the
    permanent, and a plan that counted those would sacrifice a creature to
    cast a one-drop. They stay out until a policy prices them.

    **And only one the activation path will accept**, the non-land twin of
    `land_mana_tap_refusal`: untapped; not a summoning-sick creature (CR 302.6
    — a {T} ability is a {T} ability); not under a ban on its activated
    abilities (Interdict, Null Rod, Cursed Totem, Volrath's Curse) or a
    permission that closes it to this seat. Those are the gates
    `choose_activation_action` asks of the tables the engine enforces; asked
    here for the same reason — a source counted and then refused is a cast
    refused for insufficient mana, the same spell every turn.

    What the activation makes is `ai_valuation.planned_mana_yield`, with the
    two answers only the game has: which colours a "could produce" clause
    offers on this board (none is no source at all), and the colour a source
    chose as it entered.
    """
    from .mana_could_produce import ability_colors_on_offer
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .spell_prohibitions import permanent_activations_forbidden

    if permanent is None or permanent.tapped:
        return None
    if game.land_mana_tap_refusal(permanent) != "not_an_untapped_land":
        # A land (the seam's own reading of which permanents are its) — the
        # land half of the plan answers for it, whatever it answers.
        return None
    if game._is_summoning_sick(permanent):
        return None
    usable = usable_activated_abilities(compile_card_oracle(game.playable_card_of(permanent)))
    for index, ability in enumerate(usable):
        if not is_tap_alone_mana_ability(ability):
            continue
        produced = planned_mana_yield(ability.instruction)
        if produced is None:
            continue
        symbols = produced.symbols
        if produced.board_narrowed:
            symbols = tuple(ability_colors_on_offer(game, permanent, ability.instruction) or ())
        elif produced.from_chosen_color:
            chosen = (permanent.metadata or {}).get("chosen_color")
            symbols = (chosen,) if chosen in _MANA_SYMBOLS else ()
        if not symbols:
            continue
        line = ability.source_line or ""
        if (
            permanent_activations_forbidden(game, permanent)
            or global_activation_ban(game, permanent) is not None
            or activation_denial(game, seat, permanent, line)
            or activation_permission_denial(game, seat, permanent, line)
            or aura_restriction_active(permanent, "all_activated_abilities_shut_off")
        ):
            return None
        return _NonlandManaSource(
            ability_index=index,
            symbols=symbols,
            amount=produced.amount,
            run=dict(produced.run) if produced.run else None,
        )
    return None


def choose_attack_target(game: Game, player_index: int) -> int:
    """MVP multiplayer opponent-choice heuristic: attack/target whichever living
    opponent has the least life, tying broken by lowest seat index (deterministic
    for tests/seeded simulations). Intentionally simple — no board-state or
    threat-assessment awareness; deeper multiplayer AI tactics are future work.
    In a 2-player game this is always just the other seat."""
    opponents = game.opponents_of(player_index)
    if not opponents:
        return player_index
    return min(opponents, key=lambda idx: (game.players[idx].life, idx))


#: What casting from the command zone is worth over casting the same card from
#: hand: a net card. A command-zone cast spends nothing from hand — the
#: commander is CR 903.8's standing extra card — and `_score_cast` already
#: prices a net card at 4.0 (its draw weight), so the same number is used
#: rather than a second opinion about what a card is worth. The tax needs no
#: weight of its own: it is generic mana in the cost, so an unaffordable recast
#: is skipped by the tap planner exactly as any other unaffordable spell is.
COMMAND_ZONE_CAST_BONUS = 4.0


def hand_spells(player) -> "list[tuple[int, CardDefinition]]":
    """Every spell *player*'s hand could be cast as, with the hand position of
    the card it is on: ``(hand_index, spell)``.

    One entry per single-face card and **one per half of a split card**
    (CR 709.3 — the player chooses which half, and CR 709.3a evaluates only
    that half). So every chooser that walks a hand asking "should I cast
    this?" scores a split card as the two spells it is and proposes the better
    one, with nothing else to learn: the spell is a ``CardDefinition`` like any
    other, and its ``name`` is what the executor casts
    (:func:`spell_being_cast`).
    """
    return [
        (hand_index, spell)
        for hand_index, card in enumerate(player.hand)
        for spell in castable_faces(card)
    ]


def spell_being_cast(zone, action: "CastAction") -> CardDefinition:
    """The spell *action* proposes out of *zone* (a hand, a command zone).

    ``action.hand_index`` finds the card and ``action.card_name`` says which
    spell it is cast as — the card itself for a single-face card, the chosen
    half for a split card. Every executor reads this rather than the zone
    card's own name, which for a split card names no spell and is refused
    (CR 709.3).
    """
    held = zone[action.hand_index]
    return spell_named(held, action.card_name) or held


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    best: CastAction | None = None
    for hand_index, card in hand_spells(game.players[player_index]):
        candidate = _cast_candidate(game, player_index, card, hand_index)
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    # CR 903.8: the seat's commander is castable from the command zone, and an
    # AI seat that never read that zone sat its commander there for the whole
    # game. Which casts are on offer is `ai_valuation.castable_commanders` —
    # the engine's own seam, empty outside a Commander game — and the tax
    # arrives as extra generic in the cost, the same way the cast path charges
    # it, so affordability is judged against what will actually be paid.
    for zone_index, card, tax in castable_commanders(game, player_index):
        candidate = _cast_candidate(
            game, player_index, card, zone_index,
            from_zone="command", extra_generic=tax,
        )
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    return best


def choose_land_drop(game: Game, player_index: int) -> CastAction | None:
    """The land this seat plays now (CR 305.1), or None when it has no land
    to play or no land play left (CR 305.2).

    **A land drop is not a cast, and the two are not one choice.** Playing a
    land is a special action that uses no stack and costs no mana, and a turn
    has a land drop *and* the mana it then spends — so a seat that weighed
    its land against its spells under one score (``choose_cast_action``, where
    a land scores 1.0 and every spell at least 1.5) either played the land and
    cast nothing, or cast the spell and kept the land in hand. That was
    invisible while the simulator never enforced mana costs: a spell cost
    nothing, so the land always lost. Asked before the casts, from the same
    gates (`_cast_candidate`), so a land the cast path would refuse is never
    proposed; how many drops a turn has is `Game._may_play_another_land`, the
    one question every land-drop gate asks, so an Exploration or a Fastbond
    adds plays here exactly as it does at the table.

    Which land, when there is a choice: the one that adds a colour the hand's
    spells ask for and the seat's lands do not yet make (`_land_drop_value`).

    **Never a land its own entry would sacrifice.** "When this land enters,
    sacrifice it unless you return a non-Lair land you control to its owner's
    hand" (the Lairs; the Karoo cycle) played onto a board with no such land
    is the card and the land drop both thrown away, and `_land_drop_value`
    ranked exactly that play first on turn one — a three-colour land adds more
    wanted colours than any basic. Such a land is not a candidate until the
    price can be met (`ai_valuation.entry_sacrifice_is_unavoidable`), so the
    seat plays the basic beside it, or holds.
    """
    if not game._may_play_another_land(player_index):
        return None
    best: CastAction | None = None
    best_value: tuple[int, int] | None = None
    for hand_index, card in enumerate(game.players[player_index].hand):
        if card.primary_type != "land":
            continue
        if entry_sacrifice_is_unavoidable(game, player_index, card):
            continue
        candidate = _cast_candidate(game, player_index, card, hand_index)
        if candidate is None:
            continue
        value = _land_drop_value(game, player_index, card)
        if best_value is None or value > best_value:
            best, best_value = candidate, value
    return best


def _land_drop_value(
    game: Game, player_index: int, land: CardDefinition
) -> tuple[int, int]:
    """How much *land* helps the seat's hand: ``(colours it adds that the
    hand wants and no land the seat controls makes, colours it makes that the
    hand wants at all)``, compared as a tuple.

    The colours a card *in hand* makes are the printed summary
    (``produced_mana``) — it is not a permanent yet, so the engine's answer
    for one (`_land_symbols`) cannot be asked. A ranking, never a gate: the
    tap planner still asks the engine what each land makes once it is down.
    """
    wanted: set[str] = set()
    for card in game.players[player_index].hand:
        if card.primary_type == "land":
            continue
        for symbol in re.findall(r"\{([^}]+)\}", card.mana_cost or ""):
            wanted.update(part for part in symbol.upper().split("/") if part in "WUBRG")
    made = {
        symbol
        for permanent in game.controlled_by(player_index)
        if permanent.card.primary_type == "land"
        for symbol in _land_symbols(game, permanent)
    }
    makes = set(land.produced_mana or ()) & wanted
    return (len(makes - made), len(makes))


#: CR 601.2b's optional-cost answer the candidate *being built* would announce,
#: for the target choosers underneath `_cast_candidate`. CR 702.33g makes a
#: kicked-only part's targets depend on it, so every chooser has to read the
#: same spec the announcement will be checked against -- and they take a card,
#: not an announcement. A context variable rather than a parameter on five
#: functions: it is one fact about one candidate, set and reset around the
#: single call that builds it, and None (every card that prints no kicker)
#: reads exactly the spec those choosers read before.
_OFFERS_ANNOUNCED: ContextVar["dict[str, int] | None"] = ContextVar(
    "ai_offers_announced", default=None
)


def _cast_spec(card: CardDefinition, program):
    """`derive_cast_spec` for the candidate being built (see
    `_OFFERS_ANNOUNCED`)."""
    return derive_cast_spec(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get()
    )


#: Optional additional costs (CR 601.2b) — the tuning. *Which* offers a card
#: makes and what each buys is `ai_valuation.cast_offers`; these say how far a
#: seat goes for one.
#:
#: The most times a repeatable offer is announced ("you may pay {1}{G} any
#: number of times"). The lands bound it first; this bounds the search.
OFFER_REPEAT_CAP = 6
#: A buyback paid in life (Slaughter's 4) is taken only while the seat keeps
#: this much — the reserve `FOREIGN_ACTIVATION_LIFE_RESERVE` keeps, for the
#: same reason: life is the one resource whose last points lose the game.
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
    """
    if not game.enforce_mana_costs:
        return True
    player = game.players[player_index]
    spell = _cost_for(game, player, card, None)
    with_offer = dict(spell)
    for symbol, amount in offer.mana.cost_at(None).items():
        with_offer[symbol] = with_offer.get(symbol, 0) + amount
    for other_index, other in hand_spells(player):
        if from_zone == "hand" and other_index == hand_index:
            continue
        if other.primary_type == "land" or cast_announces_x(other):
            continue
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
    if offer.buys == OFFER_ALTERS:
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


def _cast_candidate(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
) -> CastAction | None:
    """The `CastAction` casting *card* from *from_zone* would be, or None when
    the cast is illegal, unaffordable or has nothing legal to point at.

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
    """
    announcements = _offer_announcements(game, player_index, card, hand_index, from_zone)
    if not announcements:
        return _cast_candidate_announcing(
            game, player_index, card, hand_index,
            from_zone=from_zone, extra_generic=extra_generic, offers=None,
        )
    for offers in announcements:
        token = _OFFERS_ANNOUNCED.set(offers)
        try:
            candidate = _cast_candidate_announcing(
                game, player_index, card, hand_index,
                from_zone=from_zone, extra_generic=extra_generic, offers=offers,
            )
        finally:
            _OFFERS_ANNOUNCED.reset(token)
        if candidate is not None:
            return candidate
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
    taken = derive_cast_spec(card, program, optional_cost_payments=offers)
    declined = derive_cast_spec(card, program, optional_cost_payments={})
    if taken is None or taken == declined:
        return False
    if taken.get("kind") in ("none", "modal") or spec_roles(taken):
        return False
    return not game._enumerate_targets(
        player_index, card, taken, for_cast=True, optional_cost_payments=offers,
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


def _announces_any_offer(card: CardDefinition, offers: "dict[str, int] | None") -> bool:
    """Whether *offers* takes anything *card* actually offers, mana or not."""
    if not offers:
        return False
    keys = {offer.key for offer in cast_offers(card)}
    return any(int(times or 0) > 0 and key in keys for key, times in offers.items())


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
    """`_cast_candidate` for one fixed answer to CR 601.2b's optional costs.

    One body for the hand and the command zone (CR 903.8), because everything
    it checks is about the *card* and the board rather than about the zone:
    the zone contributes only where the executor finds the card (`from_zone`,
    `hand_index`) and what the cast additionally costs (*extra_generic*, the
    commander tax).

    *offers* is the optional additional costs this candidate takes (None for a
    card that prints none): its mana is planned with the spell's, and an offer
    printing an {X} ("Kicker {X}") announces the largest X the lands can pay.
    """
    player = game.players[player_index]
    if (
        card.primary_type == "land"
        and game.enforce_mana_costs
        and not game._may_play_another_land(player_index)
    ):
        return None
    if not _can_cast_with_targets(game, player_index, card):
        return None
    # CR 601.2's printed timing gates ("Cast this spell only during an
    # opponent's turn…"), through the table the cast path itself reads.
    # Asked here for the same reason every other gate in this function is:
    # a cast the engine will refuse is a turn the AI spends on nothing, and
    # it re-proposes the same card the next turn and the next. Siren's Call
    # did exactly that for ten consecutive turns once the simulator started
    # dealing whole sets.
    if check_cast_timing(game, player_index, (card.oracle_text or "").lower()):
        return None

    # X first: an X-draw spell's target choice depends on how many cards it
    # would draw (a spell that empties your own library is aimed elsewhere),
    # so the value has to exist before the target is picked.
    x_value = _pick_x_value(game, player, card, extra_generic, hand_index=hand_index)
    if x_value == 0:
        return None

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
        return None
    target = _choose_target_for_spell(card, player_index, game, x_value)
    target_permanent_index: int | list[int] | None = None
    target_permanent_ids: list[int] | None = None
    divided_targets: list[tuple] | None = None
    if aura_enchant_noun(card) is not None:
        aura_choice = _choose_aura_target(game, player_index, card)
        if aura_choice is None:
            return None  # Aura spells require a legal target (Rule 115.1b)
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
            return None
        divided_targets = list(divided)
    else:
        roles = _choose_role_targets(game, player_index, card)
        if roles is not None:
            if roles == ():
                # A roles spell with no legal chain of targets. Skipped
                # rather than cast: CR 601.2c needs every role filled, and
                # the cast gate would refuse it — an AI turn spent on an
                # action the game then rejects.
                return None
            target, target_permanent_index, target_permanent_ids = roles
        else:
            several = _choose_several_targets(
                game, player_index, card, x_value=x_value, preferred_seat=target,
            )
            if several == ():
                # The announced count has no legal set of targets on the side
                # the effect wants (CR 601.2c). Not proposed.
                return None
            if several is not None:
                target, target_permanent_index, target_permanent_ids = several
                # --- W2G2: "X target creatures" names exactly X (CR 601.2c) ---
                # X was sized above as the most the lands could pay, before any
                # target existed; the cast gate now counts the targets against
                # it (`legality.cast_target_count_refusal`). So X is the number
                # of targets this board supplied, never more — the seat used to
                # announce X=5, name one creature and pay for five. The cost
                # below is planned against this X.
                if _names_x_targets(card):
                    x_value = len(target_permanent_index)
                # --- end W2G2 ---------------------------------------------------
            else:
                single = _choose_single_object_target(game, player_index, card, target)
                if single == ():
                    # The side the effect wants holds no legal target, so the
                    # cast would resolve doing nothing — or doing it to the
                    # caster's own permanent. Skipped rather than proposed.
                    return None
                if single is not None:
                    target, target_permanent_index, target_permanent_ids = single
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
    if not _caster_can_make_its_sacrifices(game, player_index, card):
        # "Sacrifice a creature. Rupture deals damage equal to that creature's
        # power…": with nothing to sacrifice the whole resolution is nothing.
        return None
    if _entry_gate_gives_back_more_than_it_brings(game, player_index, card):
        # "When this creature enters, return a red or green creature you
        # control to its owner's hand" with no other such creature — the cast
        # ends with the card back in hand and the mana spent — or with only a
        # dearer one to give back.
        return None
    if not _caster_holds_a_hand_pick_entrant(game, player_index, card, hand_index):
        # "Each player chooses a card in their hand. … The owner of each
        # creature card revealed this way with the lowest mana value puts it
        # onto the battlefield." With no creature card of its own to pick, the
        # caster's Stronghold Gambit can only hand the opponent a free one.
        return None
    tap_indices: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()

    alternative_cost = False
    taken_offers = _offers_taken(card, offers)
    announces_offer = _announces_any_offer(card, offers)
    if announces_offer and _paid_for_half_names_nothing(
        game, player_index, card, offers
    ):
        # The half the offer buys has a target and the board has none for it
        # (a kicked Tolarian Emissary with no enchantment anywhere). Paying is
        # legal and buys nothing, so this candidate is declined and the caller
        # falls back to the plain cast.
        return None
    if announces_offer and _paid_for_trigger_has_nothing_to_hit(
        game, player_index, card, offers
    ):
        # ...and the same for a trigger the picker does not describe: the
        # second of a Battlemage's two, whose target is chosen on the stack and
        # would have to be the caster's own permanent.
        return None
    sized_offer = next((offer for offer, _times in taken_offers if offer.x_count), None)
    if sized_offer is not None and not game.enforce_mana_costs:
        # A free X has no ceiling to size it by, and "the most the lands can
        # pay" is the only rule this policy has for one. Declined.
        return None
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
            # here, largest first, exactly as `_max_affordable_x` sizes a mana
            # cost's -- and an X of zero is not proposed, for the reason
            # `x_value == 0` is refused above: it is a price paid for nothing.
            sized = None
            for offer_x in (range(15, 0, -1) if sized_offer is not None else (None,)):
                total = dict(required)
                for offer, times in taken_offers:
                    for symbol, amount in offer.cost_at(offer_x).items():
                        total[symbol] = total.get(symbol, 0) + amount * times
                if _plan_land_taps(game, player, total) is not None:
                    sized = (offer_x, total)
                    break
            if sized is None:
                return None
            if sized_offer is not None:
                x_value = sized[0]
            required = sized[1]
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            if announces_offer:
                return None
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
            if not _alternative_cost_is_payable(game, player_index, card, hand_index):
                return None
            alternative_cost = True
        else:
            tap_indices, tap_colors = plan

    score = _score_cast(game, player_index, card, target, x_value)
    if from_zone == "command":
        score += COMMAND_ZONE_CAST_BONUS
    return CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=tap_indices,
        score=score,
        hand_index=hand_index,
        target_permanent_index=target_permanent_index,
        target_permanent_ids=target_permanent_ids,
        from_zone=from_zone,
        alternative_cost=alternative_cost,
        divided_targets=divided_targets,
        land_tap_colors=tap_colors,
        optional_cost_payments=dict(offers) if announces_offer else None,
    )


def _printed_costs_are_payable(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    from_zone: str,
    x_value: int | None,
    taken: "dict[str, int] | None" = None,
) -> bool:
    """Whether *card*'s printed additional costs (CR 601.2b) can be paid now.

    *taken* is the candidate's answer to the optional ones: a price nobody
    took is not charged and cannot make the spell uncastable, and one that
    was taken ("Buyback—Sacrifice a land") is gated like any other.

    Asked of ``_unpayable_additional_cost`` rather than re-derived, for the
    reason :func:`_alternative_cost_is_payable` beside it gives: a policy that
    judged a cost by its own reading would propose casts the cast path then
    refuses. The gate is pure — it spends nothing and moves nothing — so asking
    it here cannot leave a half-paid cost behind.

    The costs are filtered by zone first, exactly as ``queue_from_hand`` filters
    them: a cost naming a zone is a price for casting from *that* zone, so a
    hand cast must not be gated on the graveyard price of the same card
    (Demonic Embrace).
    """
    from .cast_costs import additional_costs

    printed = tuple(
        cost for cost in additional_costs(card)
        if cost.from_zone is None or cost.from_zone == from_zone
    )
    if not printed:
        return True
    return game._unpayable_additional_cost(
        player_index, card, printed,
        spell_hand_index=hand_index if from_zone == "hand" else None,
        from_zone=from_zone,
        x_value=x_value,
        taken=taken,
    ) is None


def _alternative_cost_is_payable(
    game: Game, player_index: int, card: CardDefinition, hand_index: int
) -> bool:
    """Whether *card*'s printed alternative cost (CR 118.9) can be paid now.

    Asked of the engine's own gate rather than re-derived here, for the reason
    every other affordability question in this policy is: a policy that judged
    a cost by its own reading would propose casts the cast path then refuses,
    and `refused_casts` counts exactly that.

    The gate is a pure predicate over the board — it spends nothing and moves
    nothing — so asking it here costs a lookup and cannot leave a half-paid
    cost behind.
    """
    # Printed **and** granted (Dream Halls' board-wide offer), through the one
    # reader the cast path itself asks. A policy reading only the printed half
    # would be a second answer to "what may this be paid with", and the
    # direction it fails in is a seat that holds a castable spell all game --
    # which is the shape this function was written for in the first place.
    printed = game.applicable_alternative_costs(player_index, card)
    if len(printed) != 1:
        # None to take, or more than one and CR 118.9a lets only one be
        # applied — a choice this policy has no card to make and the cast path
        # refuses outright.
        return False
    return game._unpayable_alternative_cost(
        player_index, card, printed[0], spell_hand_index=hand_index,
    ) is None


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    player = game.players[player_index]

    best: ActivationAction | None = None
    for permanent_index, permanent in enumerate(player.battlefield):
        if permanent.tapped or permanent.card.primary_type == "land":
            continue
        if game._is_summoning_sick(permanent):
            continue

        program = compile_card_oracle(permanent.card)
        # The shared reader, not a third copy of its predicate: it carries
        # CR 113.6's zone read, so a cycling creature's "{2}, Discard this card:
        # Draw a card." is not on this list at all. Open-coded, the policy
        # proposed it every main phase and the engine ran it — a free repeatable
        # draw for a card that was never discarded, on eight of Urza's Saga's
        # creatures. It is also the list `activation_target_spec` narrows by,
        # which the `ability_index=0` below already assumes.
        ability = next(iter(usable_activated_abilities(program)), None)
        if ability is None or ability.instruction is None:
            continue

        # A mana ability is activated to *pay* for something (_plan_land_taps
        # arranges that), never for its own sake: mana added here empties at the
        # end of the step, and Black Lotus sacrifices itself to add it. The set
        # this replaced named two instruction kinds that no longer exist, so the
        # skip had silently stopped happening — see MANA_ABILITY_KINDS.
        if is_mana_ability(ability.instruction):
            continue

        # "Return this creature to its owner's hand" (Quicksilver Wall),
        # "This creature loses flying until end of turn" (Ribbon Snake),
        # "Destroy this enchantment" (Volrath's Dungeon): an effect that removes
        # or hampers **its own source**. Mostly a drawback printed for an
        # opponent to pay for (CR 602.1b), otherwise a rescue that needs a
        # response window this main-phase chooser never has — and the score
        # below rates it 2.5 like anything else, so the AI bounced its own wall
        # for {4} and paid 5 life to destroy its own Dungeon. Read off the
        # compiled program (`ai_valuation.harms_its_own_source`), the reading
        # `choose_foreign_activation_action` takes the other way.
        if harms_its_own_source(ability.instruction):
            continue

        # A cost paid in permanents or cards is a trade this policy cannot
        # price: Atog's "+2/+2 until end of turn" is worth an artifact only
        # sometimes, and the score below reads the *effect* alone. Skipping is
        # the honest floor — the alternative is an AI that eats its own board
        # every main phase for a pump that wears off. Derived from the compiled
        # cost, so it reaches every card printed this way and names none.
        if ability.cost.sacrifice_filter is not None or ability.cost.discard_cards:
            # A conjoined sacrifice ("a creature **and a Swamp**", Viscerid
            # Drone) is covered by the clause above rather than by a second
            # test: the charger never fills `sacrifice_also_filter` without
            # `sacrifice_filter`, so a second condition would be unreachable
            # and would read as a claim that it is not.
            continue
        # …and the same trade imposed from outside: "Activated abilities of
        # nontoken Rebels cost an additional "Sacrifice a land"" (Brutal
        # Suppression), Drought's per-{B} Swamp. Asked of the reader the charger
        # uses, so a tax the engine would collect is a tax this policy sees.
        if sacrifice_taxes(
            game, player_index, ability.cost.mana, "activate", source=permanent,
        ):
            continue
        # "…+X/+0 until end of turn, where X is **the power of the creature
        # tapped this way**" (Keldon Battlewagon). The effect is as large as the
        # creature the cost taps, which the score below cannot see — and the
        # payment's default is the first untapped creature, which for the
        # Battlewagon is itself: +0/+0 and its own attack spent, every main
        # phase. Derived from the payload, so it names no card.
        if "cost_tap_characteristic" in (
            ability.instruction.payload.get("x_from_count") or {}
        ):
            continue

        # "Put a -1/-1 counter on a creature you control" (Wandering Mage). The
        # same trade one resource over, and the same reason the policy cannot
        # price it: the score below reads the *effect*, so a shield bought by
        # permanently shrinking a creature reads as free — and the AI would pay
        # it every main phase until its own board is gone. Derived from the
        # compiled cost, so it names no card.
        if ability.cost.put_counter_filter is not None:
            continue

        # "{1}{B}, Pay 2 life: …" (Phyrexian Reclamation). Life is the one cost
        # here the score below never weighed, so the seat paid it every main
        # phase down to 1 — and then proposed it once more, which the engine
        # refuses (CR 119.4: a player can pay life only up to their total) and
        # the simulator counts as a seat doing nothing. The reserve is the one
        # `FOREIGN_ACTIVATION_LIFE_RESERVE`, `BUYBACK_LIFE_RESERVE` and
        # `X_LIFE_RESERVE` already keep, for their reason: the last points of
        # life are the ones that lose the game.
        life_cost = int(ability.cost.pay_life or 0)
        if life_cost and player.life - life_cost < ACTIVATION_LIFE_RESERVE:
            continue

        # "Remove a +1/+1 counter from a creature you control" (Spike Rogue).
        # The same trade in the opposite direction and the same reason the
        # policy cannot price it: the score below reads the *effect*, so moving
        # a counter from one creature to another reads as a free +1/+1 — and
        # the AI would shuttle its board's counters onto the Spike every main
        # phase for no net gain. Derived from the compiled cost, so it names no
        # card. The self-referring spelling is left alone: that one is priced by
        # the source's own counters, which the score does read.
        if ability.cost.remove_counter_filter is not None:
            continue
        # …and the self-referring spelling the score does price, which still
        # has to be *payable*: "{T}, Remove a javelin counter from this
        # creature: …" (Icatian Javelineers), Elvish Farmer's spore counters,
        # Goblin Bomb's fuse counters. With none left the activation path
        # refuses it with nothing paid (CR 601.2h via CR 602.2b), and this
        # proposed it again every main phase — 43 refused activations over the
        # default seeded runs, the "costs a board cannot pay" W2G3 left. The
        # count the engine compares, read through the same counter reader.
        if ability.cost.remove_counter:
            from .named_counters import counters_on

            wanted = ability.cost.remove_counter_count
            if isinstance(wanted, int) and counters_on(
                permanent, ability.cost.remove_counter
            ) < wanted:
                continue

        # "Exile the top card of your library" (Royal Herbalist, Phyrexian
        # Devourer). The same floor one zone over, and the sharper case for it:
        # the resource spent is the seat's remaining turns (CR 704.5b — a player
        # who would draw from an empty library loses), which this policy has no
        # term for at all. Left in, a seat with two mana gains 1 life every turn
        # until it decks itself, which is a loss traded for nothing.
        if ability.cost.exile_top_of_library:
            continue

        # "Exile the top creature card of your graveyard" (Necratog, Zombie
        # Scavengers), "…the top card…" (Alms, Nature's Kiss). The same floor
        # one zone over, with a second reason the library cost does not have:
        # the cost **scans** the pile, so an activation the policy proposes
        # against a graveyard holding no matching card is refused with nothing
        # spent — and the policy would propose it again next turn, and every
        # turn after, which is the "a seat doing nothing all game" shape a
        # refused action makes. Derived from the compiled cost, so it names no
        # card.
        if ability.cost.exile_graveyard_position is not None:
            continue

        # CR 602.1a and its exceptions: a permanent whose printed permission
        # closes its ability to *its own controller* — "Only your opponents may
        # activate this ability" (Clergy of the Holy Nimbus), "Only the
        # controller of the enchanted creature…" (Merseine) — is an ability
        # this seat may not activate at all. Asked of the module that enforces
        # it rather than scored, so the answer is the engine's own; without it
        # the policy proposed the same refused activation every turn for the
        # whole game, which is the "a seat doing nothing all game" shape a
        # refused action makes.
        if activation_permission_denial(
            game, player_index, permanent, ability.source_line or ""
        ):
            continue
        # CR 602.5: the printed timing ("Activate only during your upkeep",
        # Svyelunite Priest; "…only during combat", Arcum's Sleigh) and a
        # board-wide ban ("Activated abilities of artifacts can't be
        # activated", Null Rod). This chooser runs in a main phase and asked
        # neither, so it proposed them and the engine refused them, every
        # turn, each one the seat's only activation of the turn. The default
        # seeded runs (every shipped set plus PCY) logged 184 refused
        # activations at PCY's wave 2 and 47 with this asked; what is left is
        # costs the board cannot pay (a counter, an exile). Asked of the
        # tables the engine enforces, so the answer is the engine's.
        if activation_denial(
            game, player_index, permanent, ability.source_line or ""
        ) or global_activation_ban(game, permanent):
            continue

        # "Pay enchanted creature's mana cost" (Merseine). A cost the compiled
        # program cannot state — it is whatever the attached permanent's
        # printed cost is right now — so the tap planner below has nothing to
        # plan against. Skipping is the same honest floor the cost skips above
        # take, and it is derived from the compiled cost, so it names no card.
        if ability.cost.mana_from_attached:
            continue

        target = _choose_target_for_instruction(ability.instruction, player_index, game)
        # An equip ability (CR 702.6a): the creature is chosen here, because the
        # handler declines a target it was not given rather than scanning for
        # one (a misplaced Equipment is wrong in a way a fizzled pump is not).
        # Skipped entirely when nothing is worth equipping, so the AI does not
        # pay {1} every main phase to move a sword onto the creature it is
        # already on.
        target_permanent_index: int | None = None
        if ability.instruction.kind == "attach_source_to_target":
            target_permanent_index = _choose_equip_target(game, player_index, permanent)
            if target_permanent_index is None:
                continue
        if ability.instruction.kind == "grant_banding_to_target":
            # Banding grants go to the controller's own creatures.
            target = player_index
            target_creatures = [
                perm for perm in game.controlled_by(player_index) if perm.is_creature
            ]
            if not target_creatures:
                continue

        # An object-targeted ability (Silent Dart's "deal 3 to target creature",
        # a "destroy target …") must name a legal permanent, or the activation
        # is refused with nothing paid (CR 602.2b). Derive the target the way the
        # picker does and aim it by the effect's category; skip when nothing is
        # worth (or legal) to target, so the AI does not burn a turn on an
        # ability it cannot resolve.
        spec = derive_activation_spec(ability)
        # "{X}, {T}: Untap **X target** lands." (Candelabra of Tawnos, Alexi,
        # Orcish Settlers.) CR 601.2c sizes the target list from the X the
        # activator announces, and this policy announces none — so the engine
        # reads X as zero and refuses any named target. Proposing the ability
        # anyway is a refused activation every turn; skipping it is the honest
        # floor until the policy prices an X. Read off the cost clause the way
        # the activation path counts its ``{X}`` symbols, so a *defined* X (the
        # verse cycle's "where X is …") is left to the sizing that answers it.
        #
        # And the same floor for **every** ``{X}`` in a cost, not only one that
        # sizes a target list: "{X}, {T}: This creature deals X damage to target
        # creature" (Crimson Hellkite) is an X its controller announces
        # (CR 107.3a), this policy announces none, and the engine reads that as
        # zero — a tap and a turn spent dealing nothing. It reached the score
        # below only to crash there on the payload's "x".
        if "{x}" in (ability.source_line or "").lower().split(":", 1)[0]:
            continue
        # An ability naming several targets of *different* kinds, chosen in
        # dependency order (CR 602.2b reaches CR 601.2c). Asked before the
        # single-target block below, which has no arm for it: the kind is
        # "roles", so that block leaves the announcement empty and the ability
        # goes on the stack with no targets — an activation that resolves and
        # does nothing, which is the shape `refused_casts` exists to make
        # visible one step later.
        target_role_refs: list[dict] | None = None
        if spec_roles(spec):
            target_role_refs = _choose_activation_role_targets(
                game, player_index, permanent_index,
                # A side only for a chain that announces a **seat** — the three
                # abilities this walk could not answer at all until it grew an
                # arm for one (see the function). Every other roles ability
                # keeps the first-option walk it has always had: giving those a
                # side too is the right policy and a different change, one that
                # moves what the AI does with every card already activating.
                side=(
                    _activation_target_side(permanent, ability.instruction)
                    if any(role_is_seat(role) for role in spec_roles(spec))
                    else None
                ),
            )
            if target_role_refs is None:
                # No legal chain. Skipped rather than proposed: CR 602.2b fills
                # every role or the activation is refused with nothing paid,
                # and the gate would refuse it.
                continue
        object_kinds = {"creature", "artifact", "land", "permanent", "planeswalker"}
        if (
            target_permanent_index is None
            and spec is not None
            and spec.get("kind") in object_kinds
            and not spec.get("sacrifice_cost")
            and not spec.get("discard_cost")
            # A tap-cost picker (Llanowar Behemoth) names no target either: the
            # payment is the engine's default for a seat that names nothing.
            and not spec.get("tap_cost")
            and not spec.get("return_cost")
            # …nor an untap picker over an opponent's tapped lands (Benthic
            # Explorers, PCY W3G5): read as a target, the AI would aim at the
            # land it untaps and announce a target the ability does not have.
            # The counter-cost pickers are skipped above, before this block.
            and not spec.get("untap_cost")
        ):
            # The AI activates the first usable ability (selected above), which
            # is usable_activated_abilities()[0] — the index activation_target_spec
            # narrows by.
            legal = game.activation_target_spec(
                player_index, permanent_index, ability_index=0,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            if not perms:
                continue
            # Which board, from what the effect does to its target
            # (`_activation_target_side`) — and **only** that
            # board. This fell back to "any legal permanent" when the wanted
            # side had none, which is how a destroy, a tap or a "can't block"
            # with no opposing target landed on the activator's own creature,
            # and a pump with no friendly one landed on an opponent's: an
            # activation that resolves and harms the seat that paid for it.
            side = _activation_target_side(permanent, ability.instruction)
            if spec.get("source_of_choice"):
                # "…a source of your choice…" (CR 609.7a) is not a target, so
                # no side describes it — and a shield's own category reads
                # "you", which named the activator's own largest creature as
                # the thing to be shielded *from* (Bone Mask, Dark Sphere,
                # Kithkin Armor, Pentagram of the Ages, Protective Sphere,
                # Righteous Aura). The cast side's answer, for the same phrase.
                named = _choose_damage_source(game, player_index, perms)
                if not named:
                    continue
                perms = [
                    t for t in perms if (t["seat"], t["index"]) == (named[0], named[1])
                ]
                side = None
            if side == "you" and ability_denies_its_target(ability.instruction):
                # "Destroy target … you control" (Rats of Rath), "Return target
                # land you control to its owner's hand" (Trade Routes): the
                # printed seat is the activator's and the effect is a denial,
                # so activating it for its own sake only costs the seat a
                # permanent. Before this the fallback above aimed Rats of
                # Rath at whatever it found.
                continue
            if side == "you":
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            if not perms:
                continue
            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]

        # CR 601.2d asked of an ability: a divided announcement ("…divided as
        # you choose", Serra's Hymn) is one this chooser never makes, and the
        # engine refuses an activation announced without it — so proposing one
        # is a turn spent on a refusal, every turn. Then the engine's own
        # announcement gate (CR 602.2b/601.2c) over exactly what this policy is
        # about to announce: an ability whose only legal targets are cards in
        # an empty graveyard (Rootwater Diver, Groundskeeper) passed every
        # check above, because they look only at battlefield targets, and was
        # refused with nothing paid. Neither shows in `refused_casts`, which
        # counts casts; one ten-game run each of USG, TMP and MMQ logged 44
        # refused Serra's Hymn, 21 Rootwater Diver and 15 Groundskeeper
        # activations.
        if spec is not None and spec.get("kind") == "divided":
            continue
        # "{3}, {T}: You may put a creature card of the chosen type from your
        # hand onto the battlefield." With no such card in hand the ability's
        # whole effect is nothing, and the cost is still paid: Belbe's Portal
        # spent {3} every turn of NEM's simulation to log that it had no card.
        if not _hand_entry_has_a_card(game, player_index, permanent, ability.instruction):
            continue
        if game.activation_target_refusal(
            player_index, permanent, ability,
            target_player_index=target,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
        ) is not None:
            continue

        land_taps: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()
        required = dict(ability.cost.mana)
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required, paying_for=permanent)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        score = _score_activation(game, player_index, ability.instruction, target)
        if score <= 0.0:
            continue
        candidate = ActivationAction(
            permanent_name=permanent.card.name,
            permanent_index=permanent_index,
            target_player_index=target,
            land_tap_indices=land_taps,
            score=score,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
            land_tap_colors=tap_colors,
        )
        if best is None or candidate.score > best.score:
            best = candidate

    return best


def _activation_target_side(permanent: Permanent, instruction) -> str | None:
    """Whose permanent an own-seat ability's object target should be — "you",
    "opponent", or None for no preference.

    **Read step by step** (`ai_valuation.ability_target_side`), the reading the
    foreign chooser already took. This asked `instruction_target_side` of the
    top-level instruction, and a ``sequence`` / ``may`` wrapper has no side, so
    an ability whose effect is two steps fell back to "the biggest creature on
    either board": Bullwhip pinged and Serrated Biskelion shrank the AI's own
    biggest creature, Power Matrix and Ivy Seer pumped the opponent's, and
    Wishmonger gave the opponent's protection. Measured over both manifest
    roles with a creature of each size on each board: 47 abilities aimed at
    the wrong seat in one board or the other. The top-level reading stays as
    the fallback for a leaf whose target is not a ``targets`` payload.

    An ability that turns its source into an Aura (the Licids) is aimed as
    that Aura would be cast (`_aura_harms_its_host`): its attach step reads
    "you" for an Equipment's reason, and Calming Licid's "can't attack" or
    Dominating Licid's "you control enchanted creature" belong on an
    opponent's creature.
    """
    if source_becomes_an_aura(instruction):
        return "opponent" if _aura_harms_its_host(permanent.effective_card) else "you"
    return ability_target_side(instruction) or instruction_target_side(instruction)


def _choose_activation_role_targets(
    game: Game, player_index: int, permanent_index: int,
    side: str | None = None,
) -> "list[dict] | None":
    """One object per **role** for an activated ability, or None when no legal
    chain exists.

    ``_choose_role_targets``' twin on the activation side, and it is a twin
    rather than a shared body for the reason the two specs are derived
    separately: a spell's roles come from the card and an ability's from *that
    ability* (CR 602.2b), so the walks start from different calls. What they
    share is the policy — take the first option at each level — and it is safe
    for that function's stated reason: a first choice that leaves a later role
    with nothing is not in the list ``_role_target_walk`` returns.

    The answer is in the wire's own shape (``target_role_refs``) because a role
    here may be a card in a graveyard, which has no permanent id to send.

    **A role may also be a seat**, and this walk had no arm for one: "Target
    **opponent** reveals a card at random from their hand. **Target creature**
    gets +X/+X …" (Planeswalker's Favor, Scorn), "Prevent the next 2 damage …
    to target creature. **Target opponent** may draw a card." (Soldevi
    Heretic). A pick of kind ``"player"`` is neither a permanent nor a card, so
    it fell to the permanent branch, found nothing at that seat's slot ``None``
    and answered "no legal chain" — three abilities, the only three in the pool
    that announce a seat in a roles chain, that no AI seat ever activated.

    *side* is which board the ability's object role is aimed at
    (``_activation_target_side``), and with a seat role in the chain it is no
    longer optional: the first option at the permanent level is the first
    board in seat order, so without it Scorn's -X/-X would land on the
    activator's own creature whenever the activator sits first. A level with
    no pick on the wanted side is "no legal chain", the single-target block's
    rule above and for its reason.
    """
    options = game.activation_target_spec(
        player_index, permanent_index, ability_index=0,
    ).get("valid_targets") or []
    refs: list[dict] = []
    while options:
        if side in ("you", "opponent") and any(
            option.get("kind") == "permanent" for option in options
        ):
            options = [
                option for option in options
                if option.get("kind") != "permanent"
                or (option.get("seat") == player_index) == (side == "you")
            ]
            if not options:
                return None
        pick = options[0]
        if pick.get("kind") == "player":
            refs.append({"seat": pick.get("seat")})
        elif pick.get("kind") == "graveyard":
            refs.append({
                "graveyard_seat": pick.get("seat"),
                "graveyard_index": pick.get("index"),
            })
        else:
            permanent = game.permanent_at(pick.get("seat"), pick.get("index"))
            permanent_id = game.permanent_id_of(permanent)
            if not isinstance(permanent_id, int):
                return None
            refs.append({"permanent_id": permanent_id})
        options = pick.get("next") or []
    return refs or None


# --- Abilities on a permanent another seat controls ---------------------------
#
# CR 602.1b: "Any player may activate this ability." Every activation chooser
# above walks the seat's own board, so for the life of this engine no AI seat
# ever paid to use an opponent's Volrath's Dungeon, Ribbon Snake or Task Mage
# Assembly — 23 shipped and 11 PCY cards printing a permission that admits
# a seat other than the controller (W1G5's census). The engine has let any
# player activate them since `activation_permissions` existed; this is the
# policy half. Which of them a seat *wants* is
# `ai_valuation.foreign_activation_use`, read off the compiled program.

#: Life a seat keeps back when it pays life to use an opponent's ability.
#: "Pay 5 life: Destroy this enchantment" (Volrath's Dungeon) is removal
#: bought with life, and a seat this low spends its life staying alive.
FOREIGN_ACTIVATION_LIFE_RESERVE = 10
#: …and when it pays life for an ability of its own (`choose_activation_action`).
#: The same number for the same reason; a separate name because it is a
#: separate weight, and tuning one should not move the other.
ACTIVATION_LIFE_RESERVE = 10
#: Taking an opponent's permanent off the battlefield, before what the
#: permanent itself is worth (`_permanent_value`).
FOREIGN_REMOVAL_SCORE = 3.0
#: Killing an opponent's creature with its own printed drawback.
FOREIGN_KILL_SCORE = 5.0

#: The board-target kinds a foreign "aimed" ability is chosen for. A graveyard
#: or stack target is left alone: "Return target creature card from a
#: graveyard to its owner's hand" (Endbringer's Revel) needs a pick of *whose*
#: card this policy does not make for its own copy either, and a stack target
#: has nothing to aim at in the main phase this runs in.
_FOREIGN_OBJECT_KINDS = frozenset({"creature", "artifact", "land", "permanent", "planeswalker"})


def _plain_activation_cost(cost) -> bool:
    """Whether *cost* is mana and a fixed amount of life, and nothing else.

    Every other cost a foreign ability could print — a tap, a sacrifice, a
    discard, a counter, an alternative ("Pay 2 life or {2}", Tidal Control) —
    is a trade or a choice this chooser cannot price. Asked as "equal to a
    bare cost with the same mana" rather than field by field, so a cost field
    added later is declined until someone decides otherwise.
    """
    from dataclasses import replace

    from .oracle_types import ActivatedAbilityCost

    try:
        return replace(cost, pay_life=0) == ActivatedAbilityCost(mana=dict(cost.mana))
    except (TypeError, ValueError):
        return False


def choose_foreign_activation_action(
    game: Game, player_index: int
) -> ActivationAction | None:
    """The best ability this seat may activate on a permanent **another seat
    controls** (CR 602.1b), or None.

    A separate chooser from :func:`choose_activation_action` because the two
    read one program in opposite directions: an effect that removes or hampers
    its own source is a loss to the source's controller (which that chooser now
    skips) and the whole point to anyone else. What the effect is for is
    `ai_valuation.foreign_activation_use`:

    * **removes_source** is wanted whenever it is affordable — mana from the
      board, life only above :data:`FOREIGN_ACTIVATION_LIFE_RESERVE`;
    * **shrinks_source** is wanted only when the shrink kills the creature
      outright, the one hamper that needs nothing lined up behind it;
    * **aimed** is the activator's own ability in every respect but where it
      is printed (CR 113.8), so it is targeted and scored exactly as
      :func:`choose_activation_action` would score it on this seat's board.

    Every gate the engine will ask is asked first, so a proposal is not a
    refused activation every turn: the permission (`activation_permission_
    denial`), the printed timing ("only as a sorcery", "only during their
    turn", `activation_restrictions.activation_denial`), a board-wide ban, and
    CR 602.2b's target gate.
    """
    from .activation_permissions import card_widens_activation
    from .global_statics import global_statics_applying_to

    player = game.players[player_index]
    best: ActivationAction | None = None
    for source_seat, permanent in game.permanents_with_controller():
        if source_seat == player_index or game.players[source_seat].lost:
            continue
        if not card_widens_activation(permanent.effective_card):
            continue
        permanent_index = game.battlefield_index_of(permanent)
        if permanent_index is None:
            continue
        if global_activation_ban(game, permanent) or any(
            static.removes_abilities for static in global_statics_applying_to(permanent)
        ):
            continue
        program = compile_card_oracle(game.playable_card_of(permanent))
        for ability_index, ability in enumerate(usable_activated_abilities(program)):
            candidate = _foreign_activation_candidate(
                game, player_index, player, source_seat, permanent,
                permanent_index, ability_index, ability,
            )
            if candidate is not None and (best is None or candidate.score > best.score):
                best = candidate
    return best


def _foreign_activation_candidate(
    game: Game, player_index: int, player: PlayerState, source_seat: int,
    permanent: Permanent, permanent_index: int, ability_index: int, ability,
) -> ActivationAction | None:
    """One ability on another seat's *permanent*, as an action — or None."""
    instruction = ability.instruction
    if instruction is None or not ability.supported or is_mana_ability(instruction):
        return None
    line = ability.source_line or ""
    if activation_permission_denial(game, player_index, permanent, line):
        return None
    if activation_denial(game, player_index, permanent, line):
        return None
    if not _plain_activation_cost(ability.cost):
        return None
    life_cost = int(ability.cost.pay_life or 0)
    if life_cost and player.life - life_cost < FOREIGN_ACTIVATION_LIFE_RESERVE:
        return None

    use = foreign_activation_use(ability)
    target = source_seat
    target_permanent_index: int | None = None
    if use == "removes_source":
        score = FOREIGN_REMOVAL_SCORE + _permanent_value(permanent)
    elif use == "returns_source":
        # The owner plays it again, so this is tempo rather than removal:
        # worth it when recasting costs them at least what bouncing cost us,
        # or when the permanent is an untapped creature standing in front of
        # an attack this seat can make this turn. Without the second clause a
        # {4} bounce of a three-mana wall is never worth it; without the
        # first, a seat with nobody to attack with bounced it every turn and
        # its owner recast it every turn (PCY's Quicksilver Wall, measured).
        paid = sum(int(value or 0) for value in ability.cost.mana.values())
        clears_a_blocker = (
            permanent.is_creature and not permanent.tapped
            and bool(legal_attackers(game, player_index, against=source_seat))
        )
        if float(permanent.card.cmc or 0) < paid and not clears_a_blocker:
            return None
        score = FOREIGN_REMOVAL_SCORE + float(permanent.card.cmc or 0)
    elif use == "shrinks_source":
        change = source_toughness_change(instruction) or 0
        if not permanent.is_creature or (
            permanent.effective_toughness + change > permanent.damage_marked
        ):
            return None
        score = FOREIGN_KILL_SCORE + _permanent_value(permanent)
    elif use == "aimed":
        spec = derive_activation_spec(ability) or {}
        described = ((instruction.payload or {}).get("targets") or {}).get("filter") or {}
        if described.get("controller") is not None:
            # "Target creature **you control**": the enumeration below runs
            # from the source's seat, so a printed seat would be read as the
            # wrong player's. Declined rather than mis-aimed.
            return None
        if spec.get("kind") == "player":
            target = _choose_target_for_instruction(instruction, player_index, game)
        elif spec.get("kind") in _FOREIGN_OBJECT_KINDS:
            legal = game.activation_target_spec(
                source_seat, permanent_index, ability_index=ability_index,
            ).get("valid_targets") or []
            perms = [t for t in legal if t.get("kind") == "permanent"]
            # Read step by step, so a sequence's grant is aimed by the grant
            # (`ai_valuation.ability_target_side`), and **only** a side the
            # program states: an object effect with none is a coin flip
            # between the two boards, and on another seat's ability the wrong
            # board is a gift paid for.
            side = ability_target_side(instruction)
            if side == "you":
                # Asked of the step that names the target, for the reason
                # the side is: a wrapper denies nothing.
                if ability_denies_its_target(instruction):
                    return None
                perms = [t for t in perms if t["seat"] == player_index]
            elif side == "opponent":
                perms = [t for t in perms if t["seat"] != player_index]
            else:
                return None
            if not perms:
                return None

            def _power(t):
                perm = game.permanent_at(t["seat"], t["index"])
                return perm.effective_power if perm is not None else 0

            chosen = max(perms, key=_power)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]
        else:
            return None
        score = _score_activation(game, player_index, instruction, target)
    else:
        return None

    if game.activation_target_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        return None

    land_taps: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    required = dict(ability.cost.mana)
    if game.enforce_mana_costs and any(required.values()):
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return None
        land_taps, tap_colors = plan
    if score <= 0.0:
        return None
    return ActivationAction(
        permanent_name=permanent.card.name,
        permanent_index=permanent_index,
        target_player_index=target,
        land_tap_indices=land_taps,
        score=score,
        target_permanent_index=target_permanent_index,
        land_tap_colors=tap_colors,
        source_controller_index=source_seat,
        ability_index=ability_index,
    )


def choose_hand_activation_action(
    game: Game, player_index: int
) -> HandActivationAction | None:
    """The best ability this seat can activate from its **hand**, or None.

    Cycling, and whatever else prints a cost payable only from a hand
    (CR 113.6j). Which abilities those are is not decided here — it is
    ``usable_activated_abilities(program, zone=HAND)``, the same reader
    ``Game.activate_from_hand`` gates on and the same one that keeps the ability
    off a permanent's list — so this policy names no card and no keyword.

    Called **after** the seat's cast for the turn, so the untapped lands the
    payment is planned against are the mana the cast did not want: a seat
    cycles with what is left over rather than instead of playing its spell.

    One action per call, like :func:`choose_activation_action`, and the tie-break
    is hand order — the seat cycles once a priority pass rather than emptying
    its hand in a loop, and a seeded run reproduces exactly.
    """
    player = game.players[player_index]
    best: HandActivationAction | None = None
    for hand_index, card in enumerate(player.hand):
        program = compile_card_oracle(card)
        from_hand = usable_activated_abilities(program, zone=HAND)
        if not from_hand:
            continue
        ability = from_hand[0]
        if ability.instruction is None:
            continue

        # A mana ability activated for its own sake empties at the end of the
        # step; the same floor `choose_activation_action` keeps one zone over.
        if is_mana_ability(ability.instruction):
            continue

        # Any cost beyond mana and the discard the zone read is derived from is
        # a trade this policy cannot price — the same honest floor the
        # battlefield loop takes, and derived from the compiled cost so it
        # names no card.
        cost = ability.cost
        if (
            cost.sacrifice_filter is not None
            or cost.discard_cards
            or cost.pay_life
            or cost.exile_top_of_library
        ):
            continue

        land_taps: tuple[int, ...] = ()
        # The cost as CR 601.2f computes it, through the same reader
        # ``Game.activate_from_hand`` charges: a Fluctuator on the board makes
        # a Cycling {2} free, and a policy pricing the printed cost would pass
        # over an ability the engine would let it take for nothing.
        from .mixins.stack.activation import hand_activation_cost

        tap_colors: tuple[str, ...] = ()
        required = hand_activation_cost(game, player_index, card, ability)[0]
        if game.enforce_mana_costs and any(required.values()):
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            land_taps, tap_colors = plan

        # The seat is the target: nothing activatable from a hand in the pool
        # aims anywhere else, and an ability that did would be refused at
        # announcement rather than aimed by this policy.
        score = _score_activation(game, player_index, ability.instruction, player_index)
        if score <= 0.0:
            continue
        candidate = HandActivationAction(
            card_name=card.name,
            hand_index=hand_index,
            ability_index=0,
            land_tap_indices=land_taps,
            score=score,
            land_tap_colors=tap_colors,
        )
        if best is None or candidate.score > best.score:
            best = candidate
    return best


def legal_attackers(game: Game, attacking_player_index: int, against: int | None = None) -> list[int]:
    """Return battlefield indices of every creature that may legally attack this
    turn — untapped, not summoning sick, and allowed to attack an opponent.

    When ``against`` is given, mirrors the original single-opponent behavior
    (legal against that one specific opponent). When omitted, returns creatures
    legal against ANY living opponent."""
    player = game.players[attacking_player_index]
    opponents = [against] if against is not None else game.opponents_of(attacking_player_index)
    return [
        idx
        for idx, perm in enumerate(player.battlefield)
        if perm.card.primary_type == "creature"
        and not perm.tapped
        and not game._is_summoning_sick(perm)
        and any(game.can_attack(perm, opp) for opp in opponents)
    ]


def _legal_declaration(
    game: Game, attacking_player_index: int, chosen: list[int],
    *, against: int | None = None,
) -> list[int]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 508.1c).

    `legal_attackers` above is a per-creature predicate, and a restriction can
    be about the set: "can only attack alone" (Errantry), "can't attack unless
    at least two other creatures attack" (Orcish Conscripts). Proposing a set
    that disobeys one is not a partial failure — `declare_attackers` refuses the
    **whole** declaration, so a Conscripts beside one Bear kept the Bear home
    too, and the seat attacked with nobody all game.

    The rule is asked of the engine rather than re-read here: a second copy in
    the AI would drift from the one the declaration enforces, and the direction
    it would drift is a seat that stops attacking for reasons the rules do not
    give. The engine names the offending permanent, which is what makes this a
    prune rather than a search — each pass drops exactly one creature, so it
    terminates.

    **Which one it names is the caller's business for a cap.** "No more than two
    creatures can attack" (Caverns of Despair, Crawlspace) is disobeyed by the
    set rather than by any member of it, so the engine names the *last* attacker
    in the list it was handed — a rule cannot say which creature the attacker
    would rather keep, and inventing an answer there would put AI valuation
    inside the rules engine. So the list is handed over weakest-last, and the
    surviving indices come back in their original order, which is what makes
    this a cap the AI attacks *under* rather than one it attacks *through*.

    *against* is the seat this declaration is aimed at, which the per-defender
    cap needs and the global one does not. It matters only at a table with more
    than two living players: with one opponent the engine fills it in, and with
    several it cannot guess, so a free-for-all declaration would be pruned
    against the global cap alone and then refused whole for the other.
    """
    # Through the seam (`permanent_at`), which is where an index becomes a
    # permanent: the AI carries slots because that is what the declaration takes,
    # and a raw `battlefield[i]` here would be a second place that has to be
    # right about what a slot means.
    pruned = [
        (idx, game.permanent_at(attacking_player_index, idx)) for idx in chosen
    ]
    pruned = [(idx, perm) for idx, perm in pruned if perm is not None]
    # Descending value, so the engine's "last one" is the one this seat can most
    # afford to leave home. Only the order of the *question* changes; the answer
    # is a set, and it is returned in the caller's order below.
    pruned.sort(key=lambda entry: -_permanent_value(entry[1]))
    while pruned:
        # **What the declaration costs is pruned against too, and it was not.**
        # CR 508.1h's costs are summed over the whole declaration
        # (`_declaration_mana_plan`, `_declaration_sacrifice_plan`), where
        # `legal_attackers` above can only ask "could this seat afford *this*
        # creature". So a seat with one land under a {1}-per-attacker toll
        # proposed three attackers, the declaration refused all three, and
        # `ai_combat`'s superset fallback — every legal attacker, the same
        # three — was refused for the same reason: the seat attacked with
        # nobody while it could plainly have attacked with one. Measured on
        # War Tax and true of every shipped card that prints a summed
        # declaration cost (Koskun Falls, Elephant Grass, Propaganda,
        # Brainwash, Leviathan, Flooded Woodlands, Reclamation).
        #
        # Asked of the engine's own planners rather than re-totalled here, for
        # the restriction loop's stated reason: a second copy would drift, and
        # the direction it drifts is a seat that stops attacking for reasons
        # the rules do not give. Weakest-last ordering means the creature
        # dropped is the one this seat can most afford to leave home, exactly
        # as it is for a cap.
        unaffordable = _unaffordable_attacker(
            game, attacking_player_index, [perm for _idx, perm in pruned], against
        )
        if unaffordable is not None:
            pruned = [
                (idx, perm) for idx, perm in pruned if perm is not unaffordable
            ]
            continue
        refusal = game.attack_declaration_refusal(
            [perm for _idx, perm in pruned],
            # Who this seat is aiming at, when the caller knows. Omitting it is
            # only safe at a table with one living opponent, where the engine
            # fills it in; `choose_attackers` picks a single target even in a
            # free-for-all, so a per-defender cap (Crawlspace) at *that* seat
            # would otherwise be invisible here and the whole declaration would
            # be refused again — the exact failure this prune exists to stop.
            defenders=(
                None if against is None
                else {perm.permanent_id: against for _idx, perm in pruned}
            ),
        )
        if refusal is None:
            break
        offender, _reason = refusal
        pruned = [(idx, perm) for idx, perm in pruned if perm is not offender]
    kept = {id(perm) for _idx, perm in pruned}
    return [idx for idx in chosen if id(game.permanent_at(attacking_player_index, idx)) in kept]


def _with_conditional_requirements(
    game: Game, attacking_player_index: int, chosen: list[int], legal: list[int]
) -> list[int]:
    """*chosen*, plus every legal attacker the set itself now **requires**.

    The mirror of :func:`_legal_declaration` one rule over. That one prunes
    until a restriction stops being disobeyed; this one adds until a
    *requirement* is obeyed — "If a creature you control attacks, this creature
    also attacks if able" (Ekundu Cyclops) is conditional on the rest of the
    declaration, so a set that was legal before a creature was added can stop
    being legal because of it.

    Asked of the engine rather than re-read here, for ``_legal_declaration``'s
    reason: a second copy of the rule in the AI drifts, and the direction it
    drifts is a seat whose whole declaration is refused and which therefore
    attacks with nobody all game.

    Terminates because each pass adds at least one creature out of a finite
    list, and a set that adds nothing is stable.
    """
    picked = list(chosen)
    while True:
        declared = [
            perm for perm in
            (game.permanent_at(attacking_player_index, idx) for idx in picked)
            if perm is not None
        ]
        added = [
            idx for idx in legal
            if idx not in picked
            and game._must_attack_beside(
                game.permanent_at(attacking_player_index, idx), declared
            )
        ]
        if not added:
            return picked
        picked.extend(added)


def choose_attackers(game: Game, attacking_player_index: int) -> list[int]:
    """Return indices of creatures that should attack this turn.

    MVP multiplayer behavior: picks one opponent (``choose_attack_target``) and
    decides, for each legal attacker, whether to send it at that opponent —
    splitting one attack across multiple opponents is a documented stretch goal,
    not implemented here."""
    player = game.players[attacking_player_index]
    opponent_index = choose_attack_target(game, attacking_player_index)
    opponent = game.players[opponent_index]

    legal_attackers_list = legal_attackers(game, attacking_player_index, against=opponent_index)
    if not legal_attackers_list:
        return []

    # Creatures that must attack if able (Siren's Call, Lure-style "attacks each
    # combat if able", etc.) are non-negotiable: declare_attackers rejects any
    # declaration that omits them, so they must be in the result regardless of
    # the profitability heuristic below.
    forced = [idx for idx in legal_attackers_list if game._must_attack_if_able(player.battlefield[idx])]

    # A creature enchanted with Lure ("All creatures able to block it do so") is
    # only worth attacking with if it actually gets declared. Treat it as forced
    # so the AI doesn't decline to attack with it (which would skip the defender's
    # block step entirely from the human's perspective).
    for idx in legal_attackers_list:
        if idx not in forced and aura_restriction_active(
            player.battlefield[idx], "must_be_blocked_by_all_able"
        ):
            forced.append(idx)

    opponent_blockers = [
        perm
        for perm in game.controlled_by(opponent)
        if perm.card.primary_type == "creature" and not perm.tapped
    ]
    if not opponent_blockers:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    chosen = list(forced)
    for idx in legal_attackers_list:
        if idx in chosen:
            continue
        attacker = player.battlefield[idx]
        best_defender_score = max(
            _score_block_pair(blocker, attacker) for blocker in opponent_blockers
        )
        # Attack when the best possible block is not clearly profitable for the opponent.
        if best_defender_score <= _permanent_value(attacker):
            chosen.append(idx)
    chosen = _with_conditional_requirements(
        game, attacking_player_index, chosen, legal_attackers_list
    )
    chosen = _legal_declaration(
        game, attacking_player_index, chosen, against=opponent_index
    )

    # Go all-in when lethal is on the table — through the same prune, because a
    # declaration that is refused deals no damage at all. This returned the raw
    # legal set, so under either attack cap the lethal swing was refused whole
    # and the seat attacked with nobody on the turn it could have won.
    if sum(player.battlefield[i].effective_power for i in legal_attackers_list) >= opponent.life:
        return _legal_declaration(
            game, attacking_player_index, legal_attackers_list,
            against=opponent_index,
        )

    return sorted(chosen)


def _legal_block_declaration(
    game: Game,
    defending_player_index: int,
    chosen: dict[int, int | list[int]],
) -> dict[int, int | list[int]]:
    """*chosen*, pruned until the **declaration** itself is legal (CR 509.1b).

    :func:`_legal_declaration` one step of combat over, and written from the
    identical defect. ``_can_block_attacker`` is a per-pair predicate, and a
    restriction can be about the set: "no more than two creatures can block each
    combat" (Caverns of Despair), "can't block unless at least two other
    creatures block" (Orcish Conscripts, and Mogg Flunkies' "can't block
    alone"), "can't block unless a creature with greater power also blocks"
    (Okk). Proposing a map that disobeys one is not a partial failure —
    ``declare_blockers`` refuses the **whole** declaration, so the defender
    blocked with nobody, this combat and every later one, in silence.

    The rule is asked of the engine rather than re-read here, for the attack
    side's reason exactly: a second copy in the AI would drift from the one the
    declaration enforces, and the direction it drifts is a seat that stops
    blocking for reasons the rules do not give. The engine names the offending
    permanent, which is what makes this a prune rather than a search — each pass
    drops exactly one blocker, so it terminates.

    A **map**, not a list, which is the one structural difference from the
    attack side: dropping the offender means dropping a key, and the attackers
    it was assigned go with it. Everything else about that blocker's assignment
    is left alone, because a partial block is a different declaration, not a
    smaller one.

    Only this seat's own map is pruned, and only against itself: CR 802.4b
    judges each defending player's blocks with every other player's blockers
    ignored, so a second defender declaring first cannot make this one's map
    illegal.

    Which blocker the engine names for a **cap** is this function's business,
    the way it is `_legal_declaration`'s: a cap is disobeyed by the set rather
    than by any member of it, so the engine names the *last* one it was handed.
    The list therefore goes over worst-block-last — scored by the same
    `_score_block_pair` that chose the blocks — which is what makes this a cap
    the AI blocks *under* rather than one it blocks *through*.
    """
    attacker_player = game.players[game.active_player_index]
    ordered: list[tuple[int, Permanent, float]] = []
    for blocker_idx, assigned in chosen.items():
        blocker = game.permanent_at(defending_player_index, blocker_idx)
        if blocker is None:
            continue
        attacker_indices = assigned if isinstance(assigned, list) else [assigned]
        attacker = next(
            (
                perm
                for perm in (
                    game.permanent_at(attacker_player, idx)
                    for idx in attacker_indices
                )
                if perm is not None
            ),
            None,
        )
        # The value of *the block*, not of the blocker: a cap forces the seat to
        # give one up, and the one to give up is the least useful block rather
        # than the smallest creature. With no attacker resolvable there is no
        # pair to score, so the creature's own value stands in.
        score = (
            _score_block_pair(blocker, attacker)
            if attacker is not None
            else _permanent_value(blocker)
        )
        ordered.append((blocker_idx, blocker, score))
    ordered.sort(key=lambda entry: -entry[2])

    while ordered:
        # What the declaration *costs*, pruned against for the attack side's
        # reason exactly: CR 509.1d totals the costs of every chosen blocker, so
        # a defender with one land under a {1}-per-blocker toll (War Cadence)
        # would propose two blocks, have the declaration refused whole, and fall
        # through `ai_combat`'s superset rung to blocking with nobody — while it
        # could plainly have blocked with one. True of every shipped card
        # printing a summed block cost too (Hipparion, Awesome Presence, and
        # Heat Wave's life half).
        unaffordable = _unaffordable_blocker(
            game, defending_player_index, attacker_player,
            {idx: chosen[idx] for idx, _perm, _score in ordered},
            {idx: perm for idx, perm, _score in ordered},
            [perm for _idx, perm, _score in ordered],
        )
        if unaffordable is not None:
            ordered = [
                entry for entry in ordered if entry[1] is not unaffordable
            ]
            continue
        refusal = game.block_declaration_refusal(
            [perm for _idx, perm, _score in ordered]
        )
        if refusal is None:
            break
        offender, _reason = refusal
        ordered = [
            entry for entry in ordered if entry[1] is not offender
        ]
    kept = {blocker_idx for blocker_idx, _perm, _score in ordered}
    return {
        blocker_idx: assigned
        for blocker_idx, assigned in chosen.items()
        if blocker_idx in kept
    }



def _unaffordable_attacker(game, seat, attackers, against):
    """The attacker to drop when this whole declaration cannot be paid for.

    None when it can. CR 508.1h locks in a *total* cost, so affordability is a
    property of the set rather than of any member — which means, exactly as for
    a cap, that no rule can say which creature to leave home. The weakest is
    last in the list this is handed, so naming it is the same policy the
    restriction prune already applies.

    Both halves of the cost are asked, because either can be the one that does
    not fit: mana (Koskun Falls, War Tax) and sacrifice (Flooded Woodlands,
    Leviathan). Asked of the engine's own planners, so what the AI believes it
    can afford and what the declaration will charge are one answer.
    """
    if not attackers:
        return None
    seats = None if against is None else [against] * len(attackers)
    total, plan = game._declaration_mana_plan(seat, list(attackers), seats)
    if total and plan is None:
        return attackers[-1]
    if game._declaration_sacrifice_plan(seat, list(attackers)) is None:
        return attackers[-1]
    return None



def _unaffordable_blocker(
    game, defender_seat, attacker_owner, assigned, blockers, ordered_perms
):
    """The blocker to drop when this whole block declaration cannot be paid for.

    None when it can. :func:`_unaffordable_attacker`'s twin one step of combat
    over, and every word of that docstring applies: CR 509.1d locks in a total,
    affordability is a property of the set, and no rule can say which block to
    give up — so the weakest, which is last in the list handed here, is named.

    Both currencies are asked, because either can be the one that does not fit:
    mana (Hipparion, Awesome Presence, War Cadence) and life (Heat Wave,
    CR 119.4). Through the engine's own planners, so what the AI believes it can
    afford and what the declaration will charge are one answer.
    """
    if not ordered_perms:
        return None
    plan_assignments = {
        idx: (list(a) if isinstance(a, list) else [a]) for idx, a in assigned.items()
    }
    resolved_attackers = {}
    for attacker_indices in plan_assignments.values():
        for attacker_idx in attacker_indices:
            perm = game.permanent_at(attacker_owner, attacker_idx)
            if perm is not None:
                resolved_attackers[attacker_idx] = perm
    life_owed = game._block_declaration_life(
        plan_assignments, blockers, resolved_attackers
    )
    if life_owed and game.players[defender_seat].life < life_owed:
        return ordered_perms[-1]
    total, plan = game._block_declaration_mana_plan(
        defender_seat, plan_assignments, blockers, resolved_attackers
    )
    if total and plan is None:
        return ordered_perms[-1]
    return None


def choose_combat_blockers(
    game: Game,
    defending_player_index: int,
    *,
    ignore_substitution: bool = False,
) -> dict[int, int | list[int]]:
    """The blocks an AI seat declares for *defending_player_index*.

    ``ignore_substitution`` asks for the defender's *own* best blocks even while
    another seat is choosing (see the Melee note below) — the fallback for when
    the empty declaration a substituted chooser wants is itself illegal, because
    a blocking requirement (Lure) compels a block. An illegal-but-preferred
    answer is no answer at all, and the alternative is the safety valve that
    wipes every seat's blocks.
    """
    combat = game.get_combat_state()
    if game.current_turn_phase != "combat" or game.current_step != "declare_blockers":
        return {}
    if defending_player_index not in game.combat_defending_players():
        return {}
    # "You choose which creatures block this combat and how those creatures
    # block." (Melee.) CR 509.1a's chooser is someone else, and the weights
    # below score a block for the *defender* — handed to an opponent making the
    # choice they would pick the blocks that best defend the seat they are
    # attacking. Every printing of this substitution is cast by the attacking
    # player, so the honest answer is the one the card is played for: block with
    # nothing. Asked of the seam rather than of the card, so a second printing
    # needs no weight here; if a requirement (Lure) makes the empty declaration
    # illegal, the caller falls back to the defender's own choice, which is at
    # least legal.
    chooser = game.block_chooser_index(defending_player_index)
    if (
        not ignore_substitution
        and chooser != defending_player_index
        and chooser in game.opponents_of(defending_player_index)
    ):
        return {}

    active_index = game.active_player_index
    # CR 802.4a: this defender may only block attackers aimed at them.
    attackers = [
        int(item["attacker_index"])
        for item in combat.get("attackers", [])
        if item.get("defending_player_index") == defending_player_index
    ]
    if not attackers:
        return {}

    defender = game.players[defending_player_index]
    attacker_player = game.players[active_index]

    available_blockers = [
        idx
        for idx, blocker in enumerate(defender.battlefield)
        if blocker.card.primary_type == "creature" and not blocker.tapped
    ]
    if not available_blockers:
        return {}

    legal_pairs: list[tuple[int, int, float]] = []
    # How many blockers each attacker needs at once, asked of the engine rather
    # than of the keyword: menace is the N=2 case of a printed template the
    # declaration gate reads through one helper (Gorilla Berserkers' "except by
    # three or more creatures"), and an AI that knew only the keyword would keep
    # submitting a declaration the gate bounces — which is a seat that declares
    # no blockers at all for the rest of the combat.
    minimum_blockers: dict[int, int] = {}
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        for attacker_idx in attackers:
            if attacker_idx < 0 or attacker_idx >= len(attacker_player.battlefield):
                continue
            attacker = attacker_player.battlefield[attacker_idx]
            minimum_blockers[attacker_idx] = game._minimum_blockers(attacker)
            if not game._can_block_attacker(blocker, attacker):
                continue
            legal_pairs.append((blocker_idx, attacker_idx, _score_block_pair(blocker, attacker)))

    if not legal_pairs:
        return {}

    assignments: dict[int, int] = {}
    used_blockers: set[int] = set()

    # Priority 1: prevent lethal where possible.
    incoming = _estimated_incoming_player_damage(game, defending_player_index)
    life = defender.life
    if incoming >= life:
        for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: _estimated_damage_prevented(game, defending_player_index, item[1], item[0]), reverse=True):
            if blocker_idx in used_blockers:
                continue
            prevented = _estimated_damage_prevented(game, defending_player_index, attacker_idx, blocker_idx)
            if prevented <= 0:
                continue
            assignments[blocker_idx] = attacker_idx
            used_blockers.add(blocker_idx)
            incoming -= prevented
            if incoming < life:
                break

    # Priority 2: maximize favorable trades.
    for blocker_idx, attacker_idx, _ in sorted(legal_pairs, key=lambda item: item[2], reverse=True):
        if blocker_idx in used_blockers:
            continue
        if blocker_idx in assignments:
            continue
        assignments[blocker_idx] = attacker_idx
        used_blockers.add(blocker_idx)

    # Blaze of Glory: a creature marked "blocks each attacking creature this
    # turn if able" must be assigned every attacker it can legally block —
    # declare_blockers rejects anything less.
    for blocker_idx in available_blockers:
        blocker = defender.battlefield[blocker_idx]
        if not blocker.metadata.get("must_block_all_until_eot"):
            continue
        must = [
            attacker_idx
            for attacker_idx in attackers
            if 0 <= attacker_idx < len(attacker_player.battlefield)
            and game._can_block_attacker(blocker, attacker_player.battlefield[attacker_idx])
        ]
        if must:
            assignments[blocker_idx] = must

    # "Must be blocked if able" (Canopy Stalker): declare_blockers refuses a
    # declaration that leaves such an attacker unblocked while an able creature
    # stands by, so the AI assigns one — the cheapest still-free blocker, which
    # is a stated policy and not a valuation. Blocking is compulsory here, so
    # declining is not the safe fallback it is for menace below.
    for attacker_idx in attackers:
        attacker = game.permanent_at(attacker_player, attacker_idx)
        if attacker is None:
            continue
        if not any(
            i.kind == "must_be_blocked"
            for i in compile_card_oracle(attacker.effective_card).instructions
        ):
            continue
        if any(
            attacker_idx == assigned or (isinstance(assigned, list) and attacker_idx in assigned)
            for assigned in assignments.values()
        ):
            continue
        for blocker_idx in available_blockers:
            if blocker_idx in assignments:
                continue
            blocker = game.permanent_at(defender, blocker_idx)
            if blocker is not None and game._can_block_attacker(blocker, attacker):
                assignments[blocker_idx] = attacker_idx
                break

    # CR 509.1b's minimum-blocker restrictions (menace, and Gorilla Berserkers'
    # printed spelling of the same thing): declare_blockers refuses an
    # assignment that puts fewer than N blockers on such an attacker, so the AI
    # declines those blocks rather than submitting a declaration that bounces.
    # Ganging up is a valuation question for another day; not blocking is always
    # legal.
    menace_counts: dict[int, int] = {}
    for assigned in assignments.values():
        for attacker_idx in assigned if isinstance(assigned, list) else [assigned]:
            menace_counts[attacker_idx] = menace_counts.get(attacker_idx, 0) + 1
    for attacker_idx, count in menace_counts.items():
        if count >= minimum_blockers.get(attacker_idx, 1):
            continue
        for blocker_idx in list(assignments):
            assigned = assignments[blocker_idx]
            if isinstance(assigned, list):
                remaining = [a for a in assigned if a != attacker_idx]
                if remaining:
                    assignments[blocker_idx] = remaining
                else:
                    del assignments[blocker_idx]
            elif assigned == attacker_idx:
                del assignments[blocker_idx]

    # "Target creature blocks **this creature** this turn if able."
    # (Trumpeting Armodon.) The narrowed requirement: the mark on the blocker
    # names the attackers it owes a block to, by id. Assigned before the
    # unnarrowed Watchdog rule below, because obeying this one also obeys that
    # one — the reverse order would spend the creature on the wrong attacker
    # and leave the declaration illegal.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        owed = blocker.metadata.get(MUST_BLOCK_ATTACKERS_UNTIL_EOT) or ()
        if not owed:
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or attacker.permanent_id not in owed:
                continue
            if not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # "This creature blocks each combat if able." (Watchdog.) CR 509.1c aimed
    # at the blocker: declare_blockers refuses a declaration that leaves such a
    # creature out while it could legally block something, so the AI assigns it
    # the first attacker it can block rather than submitting a declaration that
    # bounces every combat.
    #
    # **After the menace pruning above**, not before it: that loop strips
    # blocks that under-fill a minimum, and a compelled block stripped there
    # would leave the declaration illegal for the reason it was added. Which
    # is also why the minimum is checked here — CR 509.1c asks for the
    # requirement to be obeyed *without disobeying a restriction*, and joining
    # a menace attacker alone disobeys one.
    for blocker_idx in available_blockers:
        if blocker_idx in assignments:
            continue
        blocker = game.permanent_at(defender, blocker_idx)
        if blocker is None:
            continue
        if not any(
            i.kind == "must_block_each_combat"
            for i in compile_card_oracle(blocker.effective_card).instructions
        ):
            continue
        for attacker_idx in attackers:
            attacker = game.permanent_at(attacker_player, attacker_idx)
            if attacker is None or not game._can_block_attacker(blocker, attacker):
                continue
            joined = sum(
                1
                for assigned in assignments.values()
                if attacker_idx == assigned
                or (isinstance(assigned, list) and attacker_idx in assigned)
            )
            if joined + 1 < minimum_blockers.get(attacker_idx, 1):
                continue
            assignments[blocker_idx] = attacker_idx
            break

    # CR 509.1b's restrictions on the declaration as a whole, last — the mirror
    # of `_legal_declaration` at the tail of `choose_attackers`, and last for
    # its reason: every requirement above may still *add* a blocker, and a set
    # that was under the cap before one was added is not under it after.
    return _legal_block_declaration(game, defending_player_index, assignments)


def choose_combat_instant_cast_action(game: Game, player_index: int) -> CastAction | None:
    player = game.players[player_index]

    best: CastAction | None = None
    for hand_index, card in hand_spells(player):
        if card.primary_type != "instant":
            continue
        if not _can_cast_with_targets(game, player_index, card):
            continue

        target = _choose_target_for_spell(card, player_index, game)
        x_value = _pick_x_value(game, player, card)
        if x_value == 0:
            continue
        # CR 601.2d, for the same reason `_cast_candidate` asks it: Pyrokinesis
        # and Contagion are instants with an alternative cost, so this is the
        # chooser that offers them during combat — and a divided spell proposed
        # with no division is refused at announcement.
        divided = choose_divided_targets(game, player_index, card, x_value)
        if divided is not None and not divided:
            continue
        # The same "would the resolution do anything" questions the main-phase
        # chooser asks (`_cast_candidate`), for the same reasons: a one-object
        # spell names its permanent on the side the effect wants or is not
        # cast, and a spell that sacrifices what its caster lacks is not cast.
        target_permanent_index: int | None = None
        target_permanent_ids: list[int] | None = None
        if divided is None:
            single = _choose_single_object_target(game, player_index, card, target)
            if single == ():
                continue
            if single is not None:
                target, target_permanent_index, target_permanent_ids = single
        if not _caster_can_make_its_sacrifices(game, player_index, card):
            continue
        tap_indices: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()

        if game.enforce_mana_costs:
            required = _cost_for(game, player, card, x_value)
            plan = _plan_land_taps(game, player, required)
            if plan is None:
                continue
            tap_indices, tap_colors = plan

        score = _score_cast(game, player_index, card, target, x_value)
        # During declare blockers, prefer combat-relevant instants.
        if game.current_turn_phase == "combat" and game.current_step == "declare_blockers":
            lowered = card.oracle_text.lower()
            if "damage" in lowered or "destroy" in lowered or "prevent" in lowered or "tap" in lowered:
                score += 2.0
        score += _stack_response_bonus(game, player_index, card, target)
        if score < 2.0:
            continue

        candidate = CastAction(
            card_name=card.name,
            target_player_index=target,
            x_value=x_value,
            land_tap_indices=tap_indices,
            score=score,
            hand_index=hand_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            divided_targets=list(divided) if divided else None,
            land_tap_colors=tap_colors,
        )
        if _is_better_cast(candidate, best):
            best = candidate

    return best


def choose_search_card(
    game: Game, player_index: int, data: dict
) -> tuple[str, int] | None:
    """Pick the ``(zone, index)`` of the best card a search may find, or None to
    fail to find (CR 701.23b).

    Both the zones and the restriction come from the armed choice rather than
    from a second reading of the card: the AI is then offered exactly the cards
    a human seat is offered, and ``search_matches`` is the only thing deciding
    what is findable. An AI that filtered differently would be a second opinion
    about what the effect finds — the same bug class as a second parse.
    """
    picks = choose_search_cards(game, player_index, data, 1)
    if not picks:
        return None
    return picks[0]["zone"], picks[0]["index"]


def choose_search_cards(
    game: Game, player_index: int, data: dict, count: int
) -> list[dict]:
    """The counted search's answer: up to *count* distinct picks, best first,
    each ``{"zone": ..., "index": ...}`` the way the resolver reads them.

    A printed name is consumed by the find that used it, exactly as the
    resolver will consume it — an AI that kept offering a used name would
    submit an answer the engine then refuses, which is the fail-to-find.
    """
    from .search_filters import name_key

    # The zone the search looks in, which is not always the chooser's own —
    # see `searched_seat`. An AI reading its own graveyard for a card the
    # effect takes from someone else's would answer with an index the resolver
    # then refuses, which is the fail-to-find.
    player = game.players[searched_seat(data, player_index)]
    working = dict(data)
    picks: list[dict] = []
    taken: set[tuple[str, int]] = set()
    for _ in range(count):
        best: tuple[str, int] | None = None
        best_score = float("-inf")
        for zone in tuple(working.get("zones", ("library",))):
            cards = player.library if zone == "library" else player.graveyard
            for index, card in enumerate(cards):
                if (zone, index) in taken or not search_matches(card, working):
                    continue
                score = _score_tutor_choice(game, player_index, card)
                if best is None or score > best_score:
                    best = (zone, index)
                    best_score = score
        if best is None:
            break
        zone, index = best
        card = (player.library if zone == "library" else player.graveyard)[index]
        taken.add(best)
        picks.append({"zone": zone, "index": index})
        among = list((working.get("restrictions") or {}).get("named_among") or ())
        if among:
            working["restrictions"] = {
                **(working.get("restrictions") or {}),
                "named_among": [n for n in among if name_key(n) != name_key(card.name)],
            }
    return picks


#: How many cards a seat nobody asks exiles into a pile that returns **one card
#: per activation** (`ai_valuation.exiled_search_pile_comes_back_one_at_a_time`).
#: A weight: one activation a turn is the most such a pile gives back, and three
#: is about what the rest of a game has turns for.
SLOW_RETURN_PILE_SIZE = 3


def slow_pile_picks(game: Game, player_index: int, picks: list[dict]) -> list[dict]:
    """The picks a headless seat keeps of *picks* — every card an "any number"
    exile-search matched, as ``{"zone", "index"}`` — when the pile is bought
    back a card at a time: the `SLOW_RETURN_PILE_SIZE` it would most want to
    tutor for (`_score_tutor_choice`), in the order it was offered between
    equals.

    For ``_default_search_exile``. Skyship Weatherlight's default exiled every
    artifact and creature in the seat's library and then returned them at
    random for {4} each, which over a game is most of a deck's threats gone
    for good.
    """
    player = game.players[player_index]

    def card_at(pick: dict) -> CardDefinition:
        zone = player.library if pick.get("zone") == "library" else player.graveyard
        return zone[pick["index"]]

    ranked = sorted(
        enumerate(picks),
        key=lambda entry: (
            -_score_tutor_choice(game, player_index, card_at(entry[1])), entry[0],
        ),
    )
    kept = sorted(position for position, _pick in ranked[:SLOW_RETURN_PILE_SIZE])
    return [picks[position] for position in kept]


def choose_search_library_index(game: Game, player_index: int, card_type: str = "any") -> int | None:
    """Pick the library index of the best card to tutor for (e.g. Demonic Tutor).

    Returns None when no library card matches card_type (fail to find). The
    library-only view of ``choose_search_card``, kept because a caller that only
    ever searches a library should not have to spell out a zone list."""
    found = choose_search_card(game, player_index, {"card_type": card_type})
    return None if found is None else found[1]


def choose_reorder_library_order(
    game: Game, caster_index: int, target_index: int, top_count: int
) -> list[int]:
    """Decide how to rearrange the top cards of a library (e.g. Natural Selection).

    Returns a permutation of ``range(top_count)`` where element 0 is the original
    index of the card that should end up on top (the next card drawn).

    When reordering our own library we surface the most valuable card first so we
    draw it next; when reordering an opponent's library we bury their best cards by
    putting the least valuable one on top.
    """
    target = game.players[target_index]
    top = target.library[:top_count]

    # Score each card from the library owner's perspective — how good drawing it
    # would be for them.
    scored = [
        (index, _score_tutor_choice(game, target_index, card))
        for index, card in enumerate(top)
    ]
    surface_best_first = caster_index == target_index
    scored.sort(key=lambda item: item[1], reverse=surface_best_first)
    return [index for index, _ in scored]


def choose_secret_number(game: Game, player_index: int, minimum: int = 1) -> int:
    """The number a seat names in secret (Goblin Game): "Each player hides at
    least one item … Each player loses life equal to the number of items they
    revealed. The player who revealed the fewest items then loses half their
    life, rounded up."

    Every point named is a point of life, and the least pays half of what it
    has left. So there are two lines and the policy picks between them from
    the life totals, which are all a seat may know — **it never reads another
    seat's number**, and is asked before any exists:

    * **the quiet line** — name the floor. It costs the floor and, as the
      fewest or tied for it, half the rest: ``(life - floor) // 2`` is left.
    * **outbidding** — name the weakest rival's whole life total. That rival
      can only match it by naming all the life it has, so it is either the
      fewest or dead, and this seat keeps ``life - bid`` unhalved.

    Outbidding is taken only when it leaves strictly more than the quiet line
    does, which is the seat far enough ahead on life to afford it (roughly: the
    weakest rival is at half this seat's life or less). That inequality is also
    the ceiling: the answer is always below the seat's own life total wherever
    any such answer is legal, the rule ``default_sacrifice_pick`` states for
    every default here — one never picks the answer that loses the game.

    Deterministic, and a function of public state alone.
    """
    floor = max(0, int(minimum))
    life = int(game.players[player_index].life)
    rivals = [
        int(player.life)
        for seat, player in enumerate(game.players)
        if seat != player_index and not player.lost
    ]
    if not rivals:
        return floor
    bid = max(floor, min(rivals))
    quiet = max(0, life - floor) // 2
    if life - bid > quiet:
        return bid
    return floor


def choose_scry_arrangement(
    game: Game, caster_index: int, top_count: int,
    library_index: int | None = None,
) -> tuple[list[int], int]:
    """Decide a scry (CR 701.22a): the arrangement, and how many go to the bottom.

    Returns ``(card_order, bottom_count)`` in the shape ``_resolve_scry`` takes —
    a permutation of ``range(top_count)`` reading top-first, and how many of its
    trailing entries go to the bottom.

    Scored by ``_score_tutor_choice`` unchanged, because "how good would drawing
    this be for me" is exactly the scry question and a second scoring function
    would be a second opinion about the same thing. A card scoring below zero is
    worse than an unknown card, so those go to the bottom; the rest are ordered
    best-first so the best one is drawn next. Deterministic given the library,
    which the AI-behaviour regression tests require.
    """
    # Whose library is being looked through, which is not always the chooser's
    # (Coral Fighters looks at the defending player's). The score below asks
    # "how good would drawing this be **for its owner**", so over somebody
    # else's pile the answer is negated: a card that would help them is one to
    # bury, and keeping the scoring function and flipping its sign is what
    # stops this becoming a second opinion about the same question.
    owner_index = caster_index if library_index is None else int(library_index)
    sign = 1.0 if owner_index == caster_index else -1.0
    owner = game.players[owner_index]
    scored = [
        (index, sign * _score_tutor_choice(game, owner_index, card))
        for index, card in enumerate(owner.library[:top_count])
    ]
    kept = sorted((s for s in scored if s[1] >= 0.0), key=lambda item: item[1], reverse=True)
    bottomed = sorted((s for s in scored if s[1] < 0.0), key=lambda item: item[1], reverse=True)
    return [index for index, _ in kept] + [index for index, _ in bottomed], len(bottomed)


def _score_tutor_choice(game: Game, player_index: int, card: CardDefinition) -> float:
    player = game.players[player_index]
    opponent_index = choose_attack_target(game, player_index)
    opponent = game.players[opponent_index]

    # Cards the engine cannot cast would strand in hand.
    if not classify_card(card).supported:
        return -50.0

    x_value = _pick_x_value(game, player, card)
    target = _choose_target_for_spell(card, player_index, game, x_value)
    score = _score_cast(game, player_index, card, target, x_value)

    lands_available = sum(
        1 for perm in game.controlled_by(player) if perm.card.primary_type == "land"
    ) + sum(
        1 for hand_card in player.hand if hand_card.primary_type == "land"
    )
    if card.primary_type == "land":
        # Lands are only worth tutoring when mana-screwed.
        if lands_available < 3:
            score += 4.0 - lands_available
        else:
            score -= 4.0
    elif game.enforce_mana_costs:
        required = _cost_for(game, player, card, x_value if x_value is not None else 0)
        if _plan_land_taps(game, player, required) is not None:
            score += 3.0  # castable as soon as it reaches hand
        else:
            available = sum(
                player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS
            ) + sum(
                1 for permanent in game.controlled_by(player)
                if permanent.card.primary_type == "land" and not permanent.tapped
            )
            score -= min(5.0, max(0.0, float(card.cmc) - available))

    # A tutored burn spell that closes the game outranks everything else.
    damage = _extract_damage(card)
    if target == opponent_index and 0 < opponent.life <= damage:
        score += 15.0

    return score


def _stack_response_bonus(game: Game, caster_index: int, card: CardDefinition, target_index: int) -> float:
    if not game.stack:
        return 0.0

    top = game.stack[-1]
    if top.caster_index == caster_index:
        # Avoid spending reaction cards while responding to our own stack item.
        return -0.5

    lowered = card.oracle_text.lower()
    bonus = 0.0

    # Countering is only worth holding up against a spell this card may legally
    # be aimed at, which is why the profile carries the colour restriction
    # rather than the caller assuming there is none.
    counter = counters_a_spell(card)
    if counter is not None and counter.can_counter(top.card):
        bonus += 6.0

    if top.target_player_index == caster_index:
        if "prevent" in lowered and "damage" in lowered:
            bonus += 2.5
        if "gain" in lowered and "life" in lowered:
            bonus += 1.5

    if _extract_damage(card) > 0 and target_index == choose_attack_target(game, caster_index):
        bonus += 1.0

    # Removal is worth a little in response. The probes here used to be
    # ``"disenchant" in lowered or "unsummon" in lowered`` — a card's *name*
    # looked for inside its own oracle text, which no card in the pool contains,
    # so both were dead and only the generic "destroy" ever fired.
    if "destroy" in lowered or destroyed_permanent_filter(card) is not None or returns_creature_to_hand(card):
        bonus += 0.75

    return bonus


def _is_better_cast(candidate: CastAction, current: CastAction | None) -> bool:
    if current is None:
        return True
    if candidate.score > current.score:
        return True
    if candidate.score < current.score:
        return False
    return candidate.hand_index < current.hand_index


def _permanent_value(permanent: Permanent) -> float:
    return permanent.effective_power * 1.4 + permanent.effective_toughness * 1.1 + float(permanent.card.cmc)


def _score_block_pair(blocker: Permanent, attacker: Permanent) -> float:
    blocker_kills = blocker.effective_power >= attacker.effective_toughness
    attacker_kills = attacker.effective_power >= blocker.effective_toughness

    attacker_value = _permanent_value(attacker)
    blocker_value = _permanent_value(blocker)

    score = 0.0
    if blocker_kills and not attacker_kills:
        score += attacker_value + 4.0
    elif blocker_kills and attacker_kills:
        score += attacker_value - blocker_value * 0.6 + 2.0
    elif not blocker_kills and attacker_kills:
        score -= blocker_value + 2.0
    else:
        score += min(attacker.effective_power, blocker.effective_toughness) * 0.5

    # Prefer blocking higher impact attackers.
    score += attacker.effective_power * 0.3 + attacker.effective_toughness * 0.2
    return score


def _estimated_damage_prevented(game: Game, defending_player_index: int, attacker_idx: int, blocker_idx: int) -> int:
    attacker = game.players[game.active_player_index].battlefield[attacker_idx]
    blocker = game.players[defending_player_index].battlefield[blocker_idx]
    power = max(0, attacker.effective_power)
    if game._has_keyword(attacker, "trample"):
        return min(power, max(0, blocker.effective_toughness - blocker.damage_marked))
    return power


def _estimated_incoming_player_damage(game: Game, defending_player_index: int) -> int:
    combat = game.get_combat_state()
    total = 0
    for item in combat.get("attackers", []):
        if item.get("defending_player_index") != defending_player_index:
            continue
        attacker_idx = int(item.get("attacker_index", -1))
        if attacker_idx < 0 or attacker_idx >= len(game.players[game.active_player_index].battlefield):
            continue
        attacker = game.players[game.active_player_index].battlefield[attacker_idx]
        total += max(0, attacker.effective_power)
    return total


def _can_cast_with_targets(game: Game, caster_index: int, card: CardDefinition) -> bool:
    """Whether *card* has a legal target for the effect it carries out **as it
    is cast**.

    Only a spell does; see ``ai_valuation.SPELL_TYPES``. A permanent's
    instruction list mirrors its *abilities*, which choose their own targets on
    activation — so reading it here would refuse to cast Flying Carpet while the
    AI controls no creature, and refuse Pyramids while the opponent controls no
    enchantment, for permanents that are perfectly castable and simply have
    nothing to point at yet. That is the same misreading ``SPELL_TYPES`` exists
    to prevent one module over, and ``targeting.derive_cast_spec`` guards with
    the same gate for the UI's benefit.
    """
    if cast_prohibition(game, caster_index, card) is not None:
        # CR 601.3, through the predicate the cast path itself refuses with
        # (`engine/cast_prohibitions.py`): a prohibited spell is refused before
        # any cost, nothing is spent, and a seat that goes on proposing it does
        # nothing for the rest of the game — which is exactly what
        # `simulate_ai_games.py`'s `refused_casts` counts. Asked for every
        # card and not only a spell, because some prohibitions stop a land
        # being *played* too (City in a Bottle, Null Chamber, Cornered Market)
        # and the predicate knows which it was handed.
        #
        # This was seven of the cast path's thirteen bans, each added here the
        # day a simulation found a seat stuck behind it; the six it lacked
        # (Steel Golem, Arcane Laboratory, Damping Engine, City of Solitude,
        # Hand to Hand, Cornered Market) were six seats still stuck.
        return False

    if card.primary_type not in SPELL_TYPES:
        return True

    # The engine's own enumeration, asked **before** the arms below. Those arms
    # are preferences as much as legality — "is there something on the
    # opponent's board worth destroying" — and each reads one or two payload
    # keys, so a narrowing the key does not carry is invisible to it: Tunnel
    # ("destroy target Wall") reads `type_filter == "creature"` and answers yes
    # to any creature at all, then the cast path checks `wall_only` and
    # refuses. Putting the engine's answer first can only ever skip *more*
    # casts, and only ones it can prove have no legal target.
    if _no_legal_cast_target(game, caster_index, card):
        return False

    opponent = game.players[choose_attack_target(game, caster_index)]
    caster = game.players[caster_index]

    program = compile_card_oracle(card)
    for instruction in program.instructions:
        kind = instruction.kind

        if kind == "bounce_target_creature":
            # What the bounce named is payload, not the word "creature":
            # Boomerang names any permanent and Flash Flood names a Mountain,
            # and a check keyed to one card's noun would have the AI hold a
            # Boomerang while the opponent's board was all lands. The same
            # reading the cast gate uses, tested with the same matcher.
            wanted = bounce_subject_filter(instruction.payload)
            return any(
                subject_matches(game, perm, wanted, observer=caster_index)
                for perm in game.controlled_by(opponent)
            )

        if kind == "destroy_target_permanent":
            type_filter = instruction.payload.get("type_filter")
            color_filter = instruction.payload.get("color_filter")
            if type_filter or color_filter:
                text = card.oracle_text.lower()
                if "target artifact or enchantment" in text:
                    return any(
                        perm.card.primary_type in {"artifact", "enchantment"}
                        for perm in game.controlled_by(opponent)
                    )
                return any(
                    (not type_filter or perm.card.primary_type == type_filter)
                    and (not color_filter or color_filter in perm.effective_colors)
                    for perm in game.controlled_by(opponent)
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            return any(
                perm.card.primary_type == "creature" for perm in game.controlled_by(caster)
            )

    return True


def _no_legal_cast_target(game: Game, caster_index: int, card: CardDefinition) -> bool:
    """Whether *card* names a mandatory target and the board offers none.

    The chain above is an if-chain over instruction kinds, so every kind it does
    not name fell out of the bottom as "castable" — and for a spell that
    *targets*, castable-with-no-target is a turn the AI spends on an action the
    engine then refuses. It does not lose the game or break a rule (the cast
    gate declines before any mana is spent, CR 601.2c), which is why nothing
    caught it: it is silent, and it repeats. The simulator's old eight-card
    decklist could not reach it because every card in it had an arm. Random
    decks reach it immediately — Deathlace and Thoughtlace (``spell_or
    _permanent``, a kind with no arm) were chosen, refused, and chosen again
    every turn of every game, so a seat holding one never did anything else.

    Rather than adding two more arms — the next unnamed kind would just repeat
    this — ask the enumeration the picker and the cast path already use. That
    is the same move ``activation_target_refusal`` made when it replaced the
    per-kind if-chain in ``activation.py``.

    **Two layers since INV W2G7.** The first is the engine's own CR 601.2c
    predicate, so the rule has one definition; the second is this policy's
    wider preference, which also declines casts the engine *accepts* because
    they are legal and useless. "Is every quantifier an *up to*?" is the
    second layer's question now and no longer the definition of a targeted
    spell — it called "X target creatures" and "any number of target
    creatures" mandatory, which the engine does not, and that reading must not
    travel back into the cast path.
    """
    # **The engine's rule first, through the engine's predicate** (CR 601.2c,
    # `legality.no_legal_cast_target_refusal`) — the very call the cast path
    # refuses with, so a spell the engine would decline for want of a target is
    # one this policy cannot propose, by construction rather than by two
    # readers happening to agree. They did not: this function decided "needs a
    # target" from every quantifier in the program, the cast path from a
    # per-kind arm, and 182 spells sat between the two.
    #
    # Asked about the candidate being built (`_OFFERS_ANNOUNCED`): CR 702.33g
    # makes a kicked-only target a target of the kicked cast alone, so the
    # obligation — and, below, the enumeration that probes each candidate
    # against the spell's own spec — is a different one per announcement. Read
    # as the card's every arm, an unkicked Rushing River was a two-target spell
    # with one target named for it, which no list is ever legal for: the seat
    # held it until it could spare a land for the kicker.
    announced = _OFFERS_ANNOUNCED.get()
    if game.no_legal_cast_target_refusal(
        caster_index, card, optional_cost_payments=announced,
    ) is not None:
        return True
    # What follows is **preference and remainder**, and is deliberately wider
    # than the rule: the two shapes the engine's predicate leaves to another
    # gate (a target on the stack, a modal spell's mode), and the casts that
    # are legal and buy nothing — "X target creatures" at an X of zero, "any
    # number of target" at none, a *source of your choice* with no source in
    # play. Declining those is this policy's business; refusing them is not
    # the engine's.
    program = compile_card_oracle(card)
    # A modal spell is asked about **mode 0**. This policy names no mode, so
    # the spell is cast as mode 0 — and that is what the engine's gates judge
    # a cast naming no mode as, and what `derive_cast_spec` returns when it is
    # handed none. Blue Elemental Blast's mode 0 counters a red spell, so an AI
    # holding one with an empty stack offered it every turn and was refused
    # every turn. (Choosing among modes is `Game.announceable_modes`' list and
    # a chooser this policy does not have yet.)
    spec = _cast_spec(card, program)
    if spec is None or spec.get("kind") in ("none", "modal") or spec_roles(spec):
        # No spec, no target; roles are `_choose_role_targets`' question and it
        # already declines an unfillable chain.
        return False
    if _targets_are_optional(program):
        # "Up to one target" is castable with none (CR 601.2c).
        return False
    return not game._enumerate_targets(
        caster_index, card, spec, for_cast=True, optional_cost_payments=announced,
    )


def _targets_are_optional(program) -> bool:
    """True when every ``targets`` quantifier the program carries is an "up to"."""
    quantifiers: list[str] = []

    def walk(instruction) -> None:
        if instruction is None:
            return
        payload = getattr(instruction, "payload", None) or {}
        targets = payload.get("targets")
        if isinstance(targets, dict) and "quantifier" in targets:
            quantifiers.append(targets.get("quantifier"))
        for step in payload.get("steps") or ():
            walk(step)

    for instruction in program.instructions:
        walk(instruction)
    return bool(quantifiers) and all(q == "up_to" for q in quantifiers)


#: Printed phrases that make an Aura's effect a cost to whoever controls its
#: host, so it belongs on an opponent's permanent. Text probes, and tuning
#: like every other weight in this module.
_HARMFUL_AURA_MARKERS = (
    "gets -",
    "doesn't untap",
    "tap enchanted",
    "you control enchanted",
    "can't attack",
    "can't block",
)
#: …and the Auras whose whole effect is a price charged to **the host's
#: controller** rather than to the host: "this Aura deals 1 damage to that
#: player" (Wanderlust, Cursed Land, Warp Artifact), "…to that land's
#: controller" (Psychic Venom), "its controller loses life equal to its power"
#: (Death Watch). None of them printed a phrase the list above reads, so the
#: AI cast every one of them onto its **own** permanent — 21 of the 22 shipped
#: Auras printing one, measured with a host of every kind on both boards — and
#: paid the damage itself every upkeep. Read the same way from a Licid's text.
_HARMFUL_AURA_PATTERN = re.compile(
    r"damage to (?:that player|its controller|that [a-z]+'s controller)"
    r"|(?:that player|its controller) loses (?:\d+|x|life)"
)


def _aura_harms_its_host(card: CardDefinition) -> bool:
    """Whether *card*'s text, as an Aura, works against the permanent it
    enchants and that permanent's controller — so the AI puts it on an
    opponent's permanent rather than its own.

    One reader for the two ways an Aura gets a host: cast onto one
    (`_choose_aura_target`), and a permanent that *becomes* one and attaches
    itself (`ai_valuation.source_becomes_an_aura`, the Licids), where the
    activation chooser asks the same question of the same text.
    """
    text = (card.oracle_text or "").lower()
    return (
        any(marker in text for marker in _HARMFUL_AURA_MARKERS)
        or _HARMFUL_AURA_PATTERN.search(text) is not None
    )


def _choose_aura_target(game: Game, caster_index: int, card: CardDefinition) -> tuple[int, int] | None:
    """Pick (player_index, permanent_index) for an Aura's enchant target.

    Harmful auras go on an opponent's permanent, beneficial ones on the caster's.
    Returns None when the preferred player has no legal target — the Aura is
    unplayable this turn rather than cast onto a permanent that helps the enemy.
    """
    noun = aura_enchant_noun(card)
    if noun is None:
        return None
    harmful = _aura_harms_its_host(card)
    target_player_index = choose_attack_target(game, caster_index) if harmful else caster_index
    # "Enchant creature **you control**" (Cocoon): however "harmful" the text
    # reads, the clause forbids an opponent's permanent — the same gate the
    # cast path applies (CR 601.2c), asked here so the AI never spends a turn
    # on a cast the game then refuses.
    seat_clause = enchant_noun_seat(noun)
    if seat_clause == "you":
        target_player_index = caster_index
    elif seat_clause == "opponent" and target_player_index == caster_index:
        target_player_index = choose_attack_target(game, caster_index)
    for permanent_index, permanent in enumerate(game.players[target_player_index].battlefield):
        # The spell's own printed targeting restriction (CR 601.2c). Asked here
        # as well as at the cast, and through the same function: a choice only
        # the cast path refuses is an AI turn spent on an action the game then
        # rejects, and a human seat offered a target it cannot take.
        if forbidden_target(game, card, permanent, caster_index):
            continue
        # CR 702.16b: an Aura with a quality cannot be cast targeting a
        # permanent with protection from it. Asked through the cast path's own
        # function for the same reason `forbidden_target` is, one line up — and
        # it was missing, so the AI would pick a creature wearing White Ward for
        # a white Aura, be refused, and pick it again next turn. Invisible until
        # the simulator started building decks that contain both.
        if not game._can_be_targeted(permanent, card, caster_index=caster_index):
            continue
        if permanent_matches_enchant_noun(permanent, noun):
            return target_player_index, permanent_index
    return None


def _even_shares(total: int, count: int) -> list[int]:
    """*total* split *count* ways, remainder to the earliest.

    CR 601.2d wants every target to receive at least one, so the remainder is
    spread rather than dropped — the same starting division
    ``evenStartingDivision`` offers a human in the browser, which is where this
    arithmetic already lived.
    """
    base, left = divmod(total, count)
    return [base + (1 if index < left else 0) for index in range(count)]


def choose_divided_targets(
    game: Game, caster_index: int, card: CardDefinition, x_value: int | None = None
):
    """CR 601.2d's announcement for a divided spell: which targets, and each
    one's share.

    Returns None when *card* divides nothing — every other card in the pool —
    and ``()`` when it divides and no legal announcement exists, which is a
    refusal rather than an absence, the same way ``_choose_role_targets``
    answers: CR 601.2d needs one target or more, and the cast gate refuses a
    spell announced with none, so proposing it would be a turn spent on an
    action the game then rejects.

    **Which board the shares land on is derived, never named**:
    ``ai_valuation.divided_shape`` reads the sign of the counter the compiled
    program places, so Bounty of the Hunt's ``+1/+1`` goes on the caster's own
    creatures and Contagion's ``-2/-1`` on the opponent's, and a card printed
    tomorrow with either template is aimed correctly the day it is ingested.

    Three stated policies sit on top of that, and only the first is forced:

    * **Damage concentrates.** A share is measured against a toughness, so four
      damage split one apiece kills nothing; the whole total goes on the first
      candidate the enumeration offers, which is a player's face where the
      printed noun admits one. That is exactly what the engine's older
      single-target path already did for Fireball, so the four "any target"
      burn spells keep the play they had and gain only a lawful announcement.
    * **Counters spread**, as far as the total and the printed target count
      allow — every counter placed is a counter either way, and Contagion and
      Bounty of the Hunt print a target count precisely because spreading is
      the point of them.
    * **A whole-board division takes the whole board** — "…among all creatures
      target opponent controls" (Dwarven Catapult) chooses nothing, so every
      candidate on the named side is announced and the even split does the rest.
    """
    program = compile_card_oracle(card)
    # The candidate being built's own answer to CR 601.2b (`_OFFERS_ANNOUNCED`):
    # which step divides, and over how many targets, may turn on it. A kicked
    # Magma Burst divides over two where the unkicked one names a single target
    # the ordinary way, and Pollen Remedy's shares total 3 or 6 (CR 702.33g).
    # Read off the card's every arm, neither has a divided step this could find
    # — both keep it under a `was_kicked` arm — so both were proposed with one
    # bare target and refused.
    offers = _OFFERS_ANNOUNCED.get()
    shape = divided_shape(
        program, instructions_as_announced(card, program, offers or {})
    )
    if shape is None:
        return None
    spec = game.cast_target_spec(caster_index, card, optional_cost_payments=offers)
    if spec.get("kind") != "divided":
        # A modal or otherwise re-derived spec that does not describe the
        # division. Nothing to announce, and the cast gate reads the same spec.
        return None
    total = _divided_announcement_total(spec, x_value)
    candidates = [
        entry for entry in (spec.get("valid_targets") or ())
        if _divided_candidate_seat(entry) is not None
    ]
    wanted = [
        entry for entry in candidates
        if shape.side is None
        or (_divided_candidate_seat(entry) == caster_index) == (shape.side == "you")
    ] or candidates
    if not wanted or total <= 0:
        # No legal target, or nothing to divide (Spoils of War with an empty
        # opponent graveyard defines X as 0). Either way there is no lawful
        # announcement, and CR 601.2e would return the game to before the cast.
        return ()
    # "…to **each of X targets**" (Firestorm) / "…and 3 damage to **a third
    # target**" (Cone of Flame). The card prints how many, so an announcement of
    # any other length is refused at the cast (CR 601.2c) — and a policy that
    # proposed one anyway would spend every turn on a cast the engine rejects,
    # which is exactly what ``refused_casts`` is the honesty check for. A board
    # too small to fill the count is no legal announcement at all, which is what
    # `()` means here.
    exact = _card_divided_target_count(spec, x_value)
    if exact is not None:
        return (
            [] if len(wanted) < exact
            else [(entry["seat"], entry.get("index")) for entry in wanted[:exact]]
        )
    if shape.whole_board:
        chosen = wanted
    elif shape.thresholded:
        chosen = wanted[:1]
    else:
        maximum = spec.get("max_targets")
        room = total if not isinstance(maximum, int) else min(maximum, total)
        chosen = wanted[:max(1, room)]
    shares = _even_shares(total, len(chosen))
    announced = spec.get("division") == "chosen"
    return [
        # A two-tuple where the card divides *evenly*: CR 601.2d asks for an
        # announcement only from a caster who chooses the division, and
        # `division_refusal` refuses shares announced for a spell that does not.
        (entry["seat"], entry.get("index")) if not announced
        else (entry["seat"], entry.get("index"), share)
        for entry, share in zip(chosen, shares)
    ]


def _card_divided_target_count(spec: dict, x_value: int | None) -> int | None:
    """How many targets a card-dictated division prints, or None.

    None for every divided spell whose count the caster chooses, which is every
    one in the pool before Weatherlight — so the caller may ask unconditionally.

    The two spellings the description carries: a printed number, and the string
    ``"x"`` for a count announced under CR 107.3a. The policy has just chosen
    that X, so it is the value passed in — the same number
    ``casting._card_divided_target_count`` will read off the announcement, which
    is what keeps the proposal and the gate counting the same thing.
    """
    printed = spec.get("divided_target_count")
    if isinstance(printed, bool) or printed is None:
        return None
    if isinstance(printed, int):
        return printed
    return max(0, int(x_value or 0)) if printed == "x" else None


def _divided_candidate_seat(entry) -> int | None:
    """The seat one enumerated divided target sits on, or None if the entry is
    neither a permanent nor a player's face."""
    if not isinstance(entry, dict) or entry.get("kind") not in ("permanent", "player"):
        return None
    seat = entry.get("seat")
    return seat if isinstance(seat, int) else None


def _divided_announcement_total(spec: dict, x_value: int | None) -> int:
    """How much a divided spell has to divide, once X is known.

    The browser's ``dividedDivisionTotal`` in the terms this side speaks: the
    printed amount where the card prints one, the game's number where the card
    defines its own X (CR 107.3c — Spoils of War counts a graveyard, and the
    caster never announces it), and otherwise whatever X the policy picked.
    """
    bonus = int(spec.get("division_x_bonus") or 0)
    if isinstance(spec.get("division_total"), int):
        return spec["division_total"] + bonus
    if isinstance(spec.get("defined_x"), int):
        return spec["defined_x"] + bonus
    return int(x_value or 0) + bonus


def _preferred_role_option(
    options: list[dict], caster_index: int, card: CardDefinition, game: Game
) -> dict:
    """Which of one role's legal answers this seat takes.

    The first, for every role whose object is on a battlefield — the policy
    :func:`_choose_role_targets` documents, safe because the walk has already
    dropped any first choice that leaves a later role with nothing.

    **A seat is the exception, and it is a valuation rather than a policy
    weight.** "Lunge deals 2 damage to target creature and 2 damage to target
    player or planeswalker" offers every living seat for its player role, and
    the caster's own is first in the list — so taking the first burned the
    caster for two. Which seat a spell wants is a question this module already
    answers for every one-target spell (:func:`_choose_target_for_spell`,
    scoring the caster against the seat the attack policy picks), and the roles
    walk is the same question about the same card: asking it here is one
    reader of one answer rather than a second rule about who to point a spell
    at.

    The preference is applied only when that seat is one the walk offered, so
    a role narrowed to "target **opponent**" is never widened by it — and the
    first option stays the answer whenever it is not.
    """
    if not options or options[0].get("kind") != "player":
        return options[0]
    wanted = _choose_target_for_spell(card, caster_index, game)
    return next(
        (option for option in options if option.get("seat") == wanted), options[0]
    )


def _choose_role_targets(
    game: Game, caster_index: int, card: CardDefinition
):
    """Pick one target per **role** for a spell naming several kinds of target.

    ``None`` when *card* names no roles at all — every other spell in the pool —
    and ``()`` when it names them and no chain this seat would announce exists,
    which is a refusal rather than an absence: CR 601.2c fills every role or
    the spell is not cast.

    The chain comes from ``cast_target_spec``, the same walk the browser's
    picker is handed, so the AI and a human seat are offered exactly the same
    choices — a first choice leaving a later role with nothing is not in the
    list.

    **Which of a role's legal answers is a valuation, per role**
    (``ai_valuation.role_target_sides``). Taking the first option at each level
    was the whole policy, and the first option is the first board in seat
    order: Withdraw returned two of its caster's own creatures, Fumarole
    destroyed its caster's creature and land, Lunge burned its caster's
    creature — fifteen spells across both manifest roles, measured on a
    mirrored board. Each role is now answered from the side the step that
    spends it wants, and a role with no legal answer on that side is no chain
    at all: the alternative is a denial aimed at the caster's own board or a
    gift at an opponent's, the single-target chooser's rule
    (`_choose_single_object_target`) and for its reason.

    The walk backtracks, because a side makes a first pick able to strand a
    later role the unfiltered walk had an answer for ("another target
    creature" with the only other opposing creature already taken is still
    answered by the *other* order).
    """
    if not spec_roles(_cast_spec(card, compile_card_oracle(card))):
        return None
    # Under the same announcement the roles test above read (CR 702.33g): a
    # kicked Falling Timber names two creatures and an unkicked one names one,
    # and a chain walked off the other cast's spec is a list of the wrong
    # length — proposed, refused, and proposed again next turn.
    offers = _OFFERS_ANNOUNCED.get()
    options = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers,
    ).get("valid_targets") or []
    picks = _role_chain(
        options, role_target_sides(card, offers), 0, caster_index, card, game,
    )
    if not picks:
        return ()
    # A **player** role's answer is the seat itself (Donate's "target player"),
    # and it fills no slot in the positional id list — the seat travels on the
    # field every cast already carries, which is what the resolution reads back.
    # Held as ``None`` in both lists rather than dropped, because those lists
    # are positional in role order and a short one shifts every slot after it.
    ids = [
        None if pick.get("kind") == "player"
        else game.permanent_id_of(game.permanent_at(pick["seat"], pick["index"]))
        for pick in picks
    ]
    if not all(value is None or isinstance(value, int) for value in ids):
        return ()
    seats = [pick["seat"] for pick in picks if pick.get("kind") == "player"]
    if len(seats) > 1:
        # Two player roles would be one seat sent twice, which the resolution
        # refuses on the other side of the same fact. Skipped rather than cast.
        return ()
    # The seat is still sent for every other roles spell too, because every cast
    # carries one; the *ids* are what address the two boards a roles spell may
    # span (CR 400.7).
    seat = seats[0] if seats else picks[0]["seat"]
    indices = [
        None if pick.get("kind") == "player" else pick["index"] for pick in picks
    ]
    return seat, indices, ids


def _names_x_targets(card: CardDefinition) -> bool:
    """Whether *card*'s cast names "**X** target …" for an X its caster
    announces — the spec's ``x_targets`` on a slot printed as an exact count
    (Winter Blast), not "up to X" (Reap, whose X is counted off the board and
    answered by ``Game.announced_cast_x``)."""
    program = compile_card_oracle(card)
    slot = cast_target_slot(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get()
    )
    if slot is None or not slot[0].get("x_targets"):
        return False
    described = (slot[1].payload or {}).get("targets")
    return isinstance(described, dict) and described.get("quantifier") == "exactly"


def _role_chain(
    options: list[dict], sides, level: int, caster_index: int,
    card: CardDefinition, game: Game,
) -> "list[dict] | None":
    """One pick per role from *options* down, each on the side its role wants
    (``sides[level]``) — or None when no such chain exists.

    Depth-first over the engine's own tree, so every chain it can return is one
    the cast gate accepts. A level offering seats is answered by
    `_preferred_role_option` alone, as it always was; a level offering
    permanents tries each on the wanted side in the enumeration's order.
    """
    if not options:
        return []
    want = sides[level] if level < len(sides) else None
    if options[0].get("kind") == "player":
        candidates = [_preferred_role_option(options, caster_index, card, game)]
    elif want in ("you", "opponent"):
        candidates = [
            option for option in options
            if option.get("kind") != "permanent"
            or (option.get("seat") == caster_index) == (want == "you")
        ]
    else:
        candidates = options
    for pick in candidates:
        rest = _role_chain(
            pick.get("next") or [], sides, level + 1, caster_index, card, game,
        )
        if rest is not None:
            return [pick, *rest]
    return None


def _choose_several_targets(
    game: Game, caster_index: int, card: CardDefinition,
    *, x_value: int | None = None, preferred_seat: int | None = None,
) -> tuple[int, list[int], list[int] | None] | tuple[()] | None:
    """Pick ``(seat, [permanent_index, …], [permanent_id, …] | None)`` for a spell
    naming several targets, None when the card names no such choice, or ``()``
    when it names an exact number the board cannot supply.

    Which cards this reaches is *derived*, never a list of names: the compiled
    program carries the maximum (``engine/targeting.py``'s ``max_targets``), so a
    card printed with the same template is covered the day it is ingested. The
    cheap derivation is asked first and the expensive enumeration only when it
    says yes, because this runs for every card in hand on every AI decision.

    Taking the maximum is the whole policy, and it is a policy rather than a
    rule: "up to N" may legally choose fewer, but every printed card carrying
    this template gives a benefit per target, so more is better. A card that
    ever wants fewer needs a valuation, not a special case here.
    """
    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    maximum = (spec or {}).get("max_targets")
    # "Return **up to X** target cards from your graveyard to your hand, where X
    # is the number of black permanents target opponent controls **as you cast
    # this spell**." (Reap.) The count is a board count, so the card-only
    # derivation above cannot carry it — it reports ``x_targets``, "however many
    # the announced X pays for" — and a chooser that stopped there named no
    # targets at all, which is a spell that resolves every game and does
    # nothing. Asked of the game through the *same* reader the announcement gate
    # and the browser's picker use, so the AI never proposes a count CR 601.2c
    # then refuses.
    #
    # Derived, not name-keyed: any card printing the same tail is covered the
    # day it is ingested. A spell whose X the *caster* announces (Shattered
    # Crypt's {X} cost) has no answer here and keeps the behaviour it had.
    announced = (
        game.announced_cast_x(caster_index, card)
        if (spec or {}).get("x_targets") else None
    )
    # "Exile **two** target artifacts" (Dust to Dust): a printed count is the
    # number, not a ceiling (CR 601.2c) — the spec's ``exact_targets``, which
    # the browser's confirm has always waited for and the cast gate now counts
    # (`legality.cast_target_count_refusal`). Read here for every branch below;
    # it was read only for the cost-sized one, so this chooser named one
    # creature for "two target creatures" whenever one was all the side held.
    exact = bool((spec or {}).get("exact_targets"))
    sized_by_x = False
    if announced is not None:
        if announced < 1:
            # CR 601.2c: naming nothing is a legal announcement for an "up to"
            # spell, and it is what the caller does when this returns None — so
            # the honest answer at X=0 is "no several-target choice to make".
            return None
        maximum = announced
        exact = False
    elif (
        (spec or {}).get("x_targets")
        and isinstance(x_value, int) and x_value >= 1
        and _names_x_targets(card)
    ):
        # "Tap **X** target creatures" (Winter Blast): up to the X the lands
        # can pay, and the caller then announces the X this board filled. With
        # nothing to name there is no cast worth an X of one or more.
        maximum = x_value
        sized_by_x = True
    elif not isinstance(maximum, int) or maximum <= 1:
        # "Destroy target artifact. For each additional {1}{R} you paid, destroy
        # **another** target artifact…" (Primitive Justice): the count is fixed
        # by CR 601.2b's announcement — the candidate being built's own
        # (`_OFFERS_ANNOUNCED`), read through the reader the announcement gate
        # sizes it by. With nothing taken it is the base alone, and it can be
        # one. One is still a number this chooser has to answer: CR 601.2c
        # refuses an announcement that names no target
        # (`legality.cast_target_refusal`), and a several-target handler has no
        # resolution-time board scan to fall into the way a single-target one
        # does. Without this the seat re-proposes the spell every turn and is
        # refused every turn, which is exactly what `refused_casts` counts.
        maximum = cost_target_count(
            (spec or {}).get("cost_targets"), _OFFERS_ANNOUNCED.get() or {}
        ) or 0
        if maximum < 1:
            return None
        exact = bool((spec or {}).get("exact_targets"))
    # Enumerated for the announcement being built, like the spec above: the
    # game's own picker reads an unanswered offer as declined (CR 702.33g), so
    # asked without it a kicked-only several-target part -- Nightscape
    # Battlemage's "return up to two target nonblack creatures" -- had a
    # maximum of two and a candidate list of none, and fell through to the
    # one-target chooser.
    legal = game.cast_target_spec(
        caster_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get()
    ).get("valid_targets") or []
    by_seat: dict[int, list[int]] = {}
    # A graveyard card is not a permanent and has no `permanent_id`; its slots
    # are indices into one player's graveyard, so they are collected under that
    # seat and sent as indices. Same stated policy - take the maximum - because
    # the per-target benefit argument is the same.
    wanted_kind = (
        "graveyard" if (spec or {}).get("kind") == "graveyard_creature" else "permanent"
    )
    for entry in legal:
        if entry.get("kind") != wanted_kind:
            continue
        by_seat.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
    if not by_seat:
        # An X-sized list with nothing to name has no announcement at an X of
        # one or more (`()`), where every other shape hands on to the
        # one-target chooser as it always has.
        return () if sized_by_x else None

    if sized_by_x:
        # "X target …" is one printed instance of the word, so every slot wants
        # the same board — and which board is the reading the **one-target**
        # chooser has always made for these cards (`spell_target_side`, then
        # the score's seat), because until the count gate they reached that
        # chooser: the seat named one permanent for an X of five. Same seat
        # order, more of its permanents, so a tap or a destroy sized by X is
        # aimed where it was and never at the caster's own board by the
        # several-target default below.
        side = spell_target_side(card)
        others = sorted(seat for seat in by_seat if seat != caster_index)
        if side == "you":
            order = [caster_index]
        elif side == "opponent":
            order = others
        else:
            order = [
                seat for seat in dict.fromkeys(
                    [preferred_seat, caster_index, *others]
                ) if seat is not None
            ]
        seat = next((seat for seat in order if by_seat.get(seat)), None)
        if seat is None:
            return ()
        return seat, by_seat[seat][:maximum], None

    # Which board each slot wants, derived from the compiled program rather than
    # from the card's name. A card whose slots all want the same thing — every
    # one printed before Rookie Mistake — takes the single-seat path below
    # unchanged, so this is byte-identical for Basri's Acolyte and Basri's Aegis.
    sides = several_target_slot_sides(
        program, instructions_as_announced(card, program, _OFFERS_ANNOUNCED.get() or {})
    )
    if sides and len(set(sides)) > 1:
        picks: list[tuple[int, int]] = []
        # Slots that name a side first, so a slot with no preference cannot
        # take the one permanent a later slot needed (Deadshot's "another
        # target creature" with a single opposing creature on the table).
        slot_order = sorted(
            range(maximum),
            key=lambda index: (index >= len(sides) or sides[index] is None, index),
        )
        placed: dict[int, tuple[int, int]] = {}
        for index in slot_order:
            want = sides[index] if index < len(sides) else None
            if want == "you":
                order = [caster_index]
            elif want == "opponent":
                order = sorted(s for s in by_seat if s != caster_index)
            else:
                order = [caster_index] + sorted(s for s in by_seat if s != caster_index)
            chosen = next(
                (
                    (seat, slot)
                    for seat in order
                    for slot in by_seat.get(seat, [])
                    if (seat, slot) not in placed.values()
                ),
                None,
            )
            if chosen is not None:
                placed[index] = chosen
        picks = [placed[index] for index in sorted(placed)]
        if len(picks) < maximum and (
            exact or sorted(placed) != list(range(len(placed)))
        ):
            # A slot whose side holds nothing legal. The slots of such a spell
            # are different effects ("target creature gets +0/+2 and another
            # target creature gets -2/-0"), so leaving one out from the middle
            # shifts each later effect onto the wrong slot — not proposed. A
            # trailing "up to one" left empty (Primal Might with no opposing
            # creature) is still an announcement the card prints.
            return ()
        if picks:
            ids = []
            for seat, slot in picks:
                permanent = game.permanent_at(game.players[seat], slot)
                ids.append(None if permanent is None else permanent.permanent_id)
            if all(isinstance(value, int) for value in ids):
                # `target_player_index` still has to be a seat; the ids are what
                # actually address the two boards (CR 400.7), and `_stack_push`
                # respects supplied ids over a re-derivation from one seat.
                return picks[0][0], [slot for _, slot in picks], ids

    # A side every slot agrees on is still an answer, and the fallback below has
    # always assumed the caster's own board. Rookie Mistake needed slots that
    # *disagree*; a several-target tap has slots that agree on the opponent, and
    # reading only the disagreement left the AI tapping its own creatures. Still
    # one seat, so the ids stay unnecessary and every card whose slots agree on
    # "you" is byte-identical.
    if sides and set(sides) == {"opponent"}:
        opponents = sorted(seat for seat in by_seat if seat != caster_index)
        if opponents:
            if exact and len(by_seat[opponents[0]]) < maximum:
                # A count the announcement fixed and this board cannot fill
                # (a Primitive Justice paid twice with one artifact to aim
                # at): `()`, so the caller declines this announcement and
                # tries the next smaller one.
                return ()
            return opponents[0], by_seat[opponents[0]][:maximum], None
        # Every slot wants an opponent's permanent and no opponent has one. The
        # fallback below would aim them at the caster's own, which for an
        # "up to" denial (Panic Attack, Tidal Surge) is a spell spent on
        # hampering the seat that cast it.
        return ()
    if sides and set(sides) == {"you"} and caster_index not in by_seat:
        # …and the gift the other way round: every slot wants the caster's own
        # permanent and the caster has none, so the fallback below would put
        # Basri's Aegis' counters on an opponent's creatures.
        return ()

    # One seat's worth: the index list is positional on a single battlefield
    # (`target_player_index` names whose), so a cross-seat spread needs the ids
    # above. Taking the maximum from the caster's own board is the whole policy
    # where no slot names a side: "up to N" may legally choose fewer, but every
    # card carrying that template gives a benefit per target, so more is better.
    seat = caster_index if caster_index in by_seat else min(by_seat)
    if exact and len(by_seat[seat]) < maximum:
        return ()
    return seat, by_seat[seat][:maximum], None


#: Cast specs whose legal answers are not permanents on a battlefield — a
#: player, a spell, a card in a graveyard or a hand, a choice of modes. The
#: single-object chooser below has nothing to say about them.
_NOT_OBJECT_SPECS = frozenset({
    "none", "modal", "player", "stack", "graveyard_creature", "hand_card",
    "spell_or_permanent",
})


def _choose_single_object_target(
    game: Game, caster_index: int, card: CardDefinition, preferred_seat: int
):
    """Name the one permanent a one-object-target spell is cast at:
    ``(seat, index, [permanent_id])``, ``()`` when the side the effect wants
    holds no legal target, or None when *card* is not such a spell.

    The cast used to name a **seat** and leave the permanent to the handler's
    board scan — the headless convention, which W1G2 measured 156 of 182
    creature-targeting spells accepting. Two ways that resolved doing nothing,
    both measured in NEM's simulation: a handler with no scan to fall into
    (Sivvi's Valor: "its target is gone"), and a seat with no permanent the
    printed noun admits (Topple aimed at a seat whose creatures were not the
    greatest). Naming the permanent out of the engine's own enumeration — the
    list the browser's picker offers a human — answers both, and the first
    legal permanent on the seat is the one the scan would have taken.

    Which seat is ``ai_valuation.spell_target_side``: a side the effect wants
    with nothing legal on it is ``()``, because the alternative is aiming a
    denial at the caster's own board or a gift at an opponent's. With no side,
    *preferred_seat* (the score's choice) first and then any seat — a spell that
    can only do something on the other board is cast there rather than at
    nothing. A spec offering a **player** is left alone: "any target" damage is
    aimed at a face by the seat it already carries.
    """
    program = compile_card_oracle(card)
    spec = _cast_spec(card, program)
    if (
        not isinstance(spec, dict)
        or spec.get("kind") in _NOT_OBJECT_SPECS
        or spec_roles(spec)
        or _targets_are_optional(program)
        # A spell with **no target**, whose derived spec is the picker for its
        # printed cost ("…, sacrifice a creature. Draw two cards."). A payment
        # is not a target (CR 601.2b vs 601.2c): naming the creature here put
        # an id on the *target* channel for a spell that has none, which is not
        # where the cost path reads its payer from — and the permanent named is
        # the one about to leave.
        or spec_is_a_cost(spec)
    ):
        return None
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        # The announcement *spec* was derived under (CR 702.33g), so the
        # per-candidate probe judges each permanent against that same spec.
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
    )
    if not legal or any(entry.get("kind") != "permanent" for entry in legal):
        return None
    if spell_denies_its_own_target(card):
        # "Return target permanent you control to its owner's hand"
        # (Scapegoat): a denial the printed words aim at the caster's own
        # board, which this policy has no rescue to time it for.
        return ()
    if spec.get("source_of_choice"):
        return _choose_damage_source(game, caster_index, legal)
    # A permanent's entry trigger, whose target this engine names as the
    # permanent is cast: `spell_target_side` has nothing to read for it.
    side = spell_target_side(card) or entry_trigger_target_side(card)
    others = [seat for seat in range(len(game.players)) if seat != caster_index]
    if side == "you":
        order = [caster_index]
    elif side == "opponent":
        first = choose_attack_target(game, caster_index)
        order = [first] + [seat for seat in others if seat != first]
    else:
        order = [preferred_seat] + [
            seat for seat in [caster_index, *others] if seat != preferred_seat
        ]
    for seat in order:
        for entry in legal:
            if entry.get("seat") != seat:
                continue
            permanent_id = game.permanent_id_of(game.permanent_at(seat, entry["index"]))
            if isinstance(permanent_id, int):
                return seat, entry["index"], [permanent_id]
    return ()


def _choose_damage_source(game: Game, caster_index: int, legal: list[dict]):
    """Name "a source of your choice" (CR 609.7a) for a spell that shields
    against one: ``(seat, index, [permanent_id])``, or ``()`` when no source on
    the table is one this seat would want to name.

    A source is not a target, so no effect has a *side* for it
    (``spell_target_side`` is None) and the chooser above took the first legal
    permanent on the caster's own seat — its own first land. Legal, and a card
    spent on nothing: three of seven simulated Samite Ministrations, and every
    Reverse Damage, Eye for an Eye, Shadowbane, Reflect Damage and
    Invulnerability an AI seat ever cast.

    The choice is the one the engine makes for a seat that names nothing
    (``handlers/prevention.default_damage_source``, written for the activated
    half of the same phrase): the opposing source most likely to deal damage
    this turn. Asked of that function rather than restated, and then held to
    the announcement's own enumeration — where the printed phrase narrows what
    may be chosen, the same rule is applied to what it admits. With no
    opposing creature there is nothing worth shielding against and the card is
    kept for a board that has one.
    """
    from .handlers.prevention import default_damage_source

    by_id: dict[int, tuple[int, int]] = {}
    for entry in legal:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        permanent_id = game.permanent_id_of(permanent)
        if isinstance(permanent_id, int):
            by_id[permanent_id] = (entry["seat"], entry["index"])
    chosen = default_damage_source(game, caster_index)
    chosen_id = getattr(chosen, "permanent_id", None)
    if chosen_id in by_id:
        seat, index = by_id[chosen_id]
        return seat, index, [chosen_id]
    admitted = [
        permanent
        for permanent_id, (seat, _index) in by_id.items()
        if seat != caster_index
        and (permanent := game.permanent_by_id(permanent_id)) is not None
        and permanent.is_creature
    ]
    if not admitted:
        return ()
    best = max(
        admitted,
        key=lambda perm: (bool(perm.attacking), perm.effective_power, -perm.permanent_id),
    )
    seat, index = by_id[best.permanent_id]
    return seat, index, [best.permanent_id]


def _caster_can_make_its_sacrifices(
    game: Game, caster_index: int, card: CardDefinition
) -> bool:
    """Whether every sacrifice *card*'s own effect has its caster make will
    give something up (``ai_valuation.caster_sacrifice_steps``).

    Asked of the engine's own candidate list — the one the sacrifice handler
    picks from — so the policy and the resolution cannot disagree about what
    "a creature" admits. "Sacrifice **any number of** …" is answered by the
    seat's own default, which is the stated policy in
    ``_resolve_sacrifice_inline``: a seat nobody asks gives up none. So this
    seat's Renounce, Reprocess or Landslide would sacrifice nothing and the
    rest of the spell, counting what went, would do nothing — measured at
    MMQ, where skipping a self-exiling Last Breath left Renounce as the cast
    and it resolved for zero.
    """
    player = game.players[caster_index]
    for step in caster_sacrifice_steps(card):
        if step["any_number"]:
            return False
        if not game._sacrifice_candidate_indices(player, step["filter"]):
            return False
    return True


def _entry_gate_gives_back_more_than_it_brings(
    game: Game, caster_index: int, card: CardDefinition
) -> bool:
    """Whether casting *card* now is a trade down: it prints "when this
    enters, return a <noun> you control to its owner's hand"
    (``ai_valuation.entry_self_return_gate``), it is itself such a <noun>, and
    what the seat would have to give back is worth more than *card*.

    Two boards, one answer. With **no other** such permanent the pick is forced
    onto the entering one — the cast ends with the card back in hand and the
    mana spent, and the seat re-proposes it next turn and the turn after. With
    one, the seat gives back whatever `given_back_first` puts first, and when
    that costs more to replace than *card* itself the cast has shrunk the board
    (Horned Kavu returning Shivan Wurm, which then returns Horned Kavu: nine
    casts in six simulated games, each undoing the last). Not proposed in
    either, for the reason every gate in `_cast_candidate_announcing` is there.

    Both halves through the matchers the resolution itself asks —
    ``_card_matches_filter`` for the card in hand, ``subject_matches`` for the
    board (colour through the layers, so a creature turned red counts as red).
    A card its own noun does not admit is left alone: with nothing to return
    the trigger does nothing, and the permanent stays.
    """
    from .handlers._common import _card_matches_filter

    gate = entry_self_return_gate(card)
    if gate is None:
        return False
    described = dict(gate.get("filter") or {})
    player = game.players[caster_index]
    if not _card_matches_filter(card, described, game=game, owner=player):
        return False
    others = [
        permanent for permanent in game.controlled_by(caster_index)
        if subject_matches(game, permanent, described, observer=caster_index)
    ]
    if not others:
        return True
    given = given_back_first(others, None)[0]
    loss = _given_back_loss(given)
    if loss != float(card.cmc):
        return loss > float(card.cmc)
    # An even swap, which is a cast only when it is not half of a loop: the
    # permanent given back is itself a gate whose noun admits *card*, so
    # recasting it gives *card* back, and the seat spends every turn's mana
    # exchanging one for the other. Measured in six seeded Planeshift games
    # with Sawtooth Loon and Doomsday Specter pinned (both four mana, each a
    # blue creature the other's gate admits): Loon returned Specter, Specter
    # returned Loon, Loon returned Specter — the "A returns B, B returns A" of
    # the paragraph above, with nothing dearer on either side for the
    # comparison to catch. An even swap for anything else develops the board a
    # turn later and is left alone.
    answering = entry_self_return_gate(given.effective_card)
    return answering is not None and _card_matches_filter(
        card, dict(answering.get("filter") or {}), game=game, owner=player
    )


def _given_back_loss(permanent: Permanent) -> float:
    """What a seat loses by returning *permanent* to its owner's hand.

    A card comes back for its mana value. A *token* does not come back at all
    (CR 111.7), so it is priced as the body the board loses
    (`_permanent_value`) — which keeps a 1/1 token on the table beside a
    one-drop and gives it up before a six-drop.
    """
    if permanent.metadata.get("is_token"):
        return _permanent_value(permanent)
    return float(permanent.card.cmc)


def given_back_first(permanents, source) -> list:
    """*permanents* — one seat's own — in the order that seat gives them back
    to its hand when a permanent it controls makes it return one.

    For ``_default_permanent_set_choice``, and only where *source* (the
    permanent asking) is itself one of them: gating, Shrieking Drake,
    Stampeding Wildebeests. Three rules, in order:

    * **the asking permanent last** — returning it undoes the cast that asked;
    * **the smallest loss first** (`_given_back_loss`);
    * **board order** between equals, which is the determinism every default
      in the registry keeps.

    The weights are tuning and live here; that they are consulted at all is
    the registry's decision, made where the candidates are known.
    """
    ranked = sorted(
        enumerate(permanents),
        key=lambda entry: (
            entry[1] is source, _given_back_loss(entry[1]), entry[0],
        ),
    )
    return [permanent for _slot, permanent in ranked]


def _caster_holds_a_hand_pick_entrant(
    game: Game, caster_index: int, card: CardDefinition, hand_index: int | None
) -> bool:
    """Whether the caster holds — besides *card* itself, which is on the stack
    by then (CR 601.2a) — a card the spell's own "choose a card in your hand"
    pick could put onto the battlefield
    (``ai_valuation.spell_hand_pick_entry_filters``).

    Through ``_card_matches_filter``, the matcher the entering step itself asks.
    """
    from .handlers._common import _card_matches_filter

    filters = spell_hand_pick_entry_filters(card)
    if not filters:
        return True
    player = game.players[caster_index]
    held = [c for slot, c in enumerate(player.hand) if slot != hand_index]
    return all(
        any(_card_matches_filter(c, wanted, game=game, owner=player) for c in held)
        for wanted in filters
    )


def _hand_entry_has_a_card(
    game: Game, player_index: int, source: Permanent, instruction
) -> bool:
    """Whether every "put a … card from your hand onto the battlefield" step of
    an ability (``ai_valuation.hand_entry_steps``) has a card to put.

    The candidates are the engine's own (``put_from_hand_candidates``), with
    "of the chosen type" resolved off the source the way the handler resolves
    it (``_resolve_chosen_subtype``), so the policy and the resolution cannot
    disagree about which cards the step admits.
    """
    from .handlers._common import _resolve_chosen_subtype
    from .handlers.zones import put_from_hand_candidates

    player = game.players[player_index]
    for payload in hand_entry_steps(instruction):
        described = _resolve_chosen_subtype(
            dict(payload.get("card_filter") or {}), source
        )
        if not put_from_hand_candidates(
            game, {**payload, "card_filter": described}, player
        ):
            return False
    return True


def _choose_target_for_spell(
    card: CardDefinition, caster_index: int, game: Game, x_value: int | None = None
) -> int:
    # Whose permanent the spell's object target should be, when the compiled
    # program says (`ai_valuation.spell_target_side`). Asked before the score,
    # because the score below is a handful of text probes and every spell
    # outside them tied the two seats — and the tie goes to the caster, so
    # "Target creature can't attack or block this turn" kept the AI's own
    # creature home. The side is a claim about what the effect does to its
    # target, never about which card printed it.
    side = spell_target_side(card)
    if side == "you":
        return caster_index
    if side == "opponent":
        return choose_attack_target(game, caster_index)
    # A permanent spell's seat is its entry trigger's "target player" (the
    # cast names it), and the score below cannot read a trigger: its tie-break
    # hands a creature spell's seat to the caster, which is how Abyssal Horror
    # made its own controller discard two cards. Read off the trigger this
    # announcement will fire (`_OFFERS_ANNOUNCED`: a Battlemage's discard exists
    # only for a cast that paid for it).
    if entry_trigger_seat_side(card, _OFFERS_ANNOUNCED.get()) == "opponent":
        return choose_attack_target(game, caster_index)
    self_score = _score_spell_target(card, caster_index, caster_index, game, x_value)
    opponent_index = choose_attack_target(game, caster_index)
    opp_score = _score_spell_target(card, caster_index, opponent_index, game, x_value)
    if self_score >= opp_score:
        return caster_index
    return opponent_index


def _score_spell_target(
    card: CardDefinition,
    caster_index: int,
    target_index: int,
    game: Game,
    x_value: int | None = None,
) -> float:
    caster = game.players[caster_index]
    target = game.players[target_index]
    text = card.oracle_text.lower()

    score = 0.0
    if "draw" in text:
        if target_index == caster_index:
            # Drawing more cards than the library holds is a loss by CR 704.5b on
            # the next draw; redirect to the opponent instead. How many cards the
            # spell draws is read off the compiled instruction, so "Target player
            # draws X cards" is covered at the X the caster picked and not only
            # the one card printed "three".
            drawn = cards_drawn_by_target(card, x_value)
            if drawn is not None and len(caster.library) <= drawn:
                score -= 100.0
            else:
                score += 5.0
        else:
            score += 0.5
    if "gain" in text and "life" in text:
        if target_index == caster_index:
            # Scale score with how much life has been lost from the 20-life starting total.
            # At full life (20+) the gain is worthless; pressure grows as life drops.
            life_lost = max(0, 20 - caster.life)
            score += life_lost * 0.15
        else:
            score -= 2.0

    # "Target player **loses** 4 life and you gain 4 life" (Soul Feast): the
    # loss is the spell's point and it lands on the target, which the "gain …
    # life" probe above cannot see — read off the program, weighted like damage.
    # Not where the target also draws (Peer into the Abyss): there the loss is
    # the price of the cards, and the draw probe above already weighs it.
    if spell_makes_its_target_lose_life(card) and "draw" not in text:
        score += -6.0 if target_index == caster_index else 4.0

    damage = _extract_damage(card)
    if damage == 0:
        # X-damage spells (Disintegrate, Fireball, …) parse to amount 'x', so the
        # literal extractor reads 0. Estimate the damage from the most X the caster
        # can pay; without this the spell registers as dealing no damage and the
        # tie-break below points it at the caster's own face.
        damage = _estimate_x_damage(game, caster, card)
    if damage > 0:
        if target_index != caster_index:
            score += 4.0
            if target.life <= damage:
                score += 10.0
            score += (20 - target.life) * 0.05
        else:
            score -= 6.0

    # Interaction aimed at a player's board, valued by what that board offers.
    # Both used to be one card name each; the two templates they stood for are
    # printed on nine cards in this pool alone, and the seven that were not
    # named aimed themselves at the AI's own permanents.
    if returns_creature_to_hand(card):
        if target_index == caster_index:
            return -50.0
        creatures = [perm for perm in game.controlled_by(target) if perm.is_creature]
        return 2.0 + max((perm.effective_power for perm in creatures), default=0)

    destroy_filter = destroyed_permanent_filter(card)
    if destroy_filter is not None:
        if target_index == caster_index:
            return -50.0
        # The engine's own matcher, so the AI counts exactly the permanents it
        # would be allowed to choose. An unfiltered "destroy target permanent"
        # carries an empty filter and matches them all.
        destroyable = [
            perm for perm in game.controlled_by(target)
            if permanent_matches_filter(perm, destroy_filter)
        ]
        return 2.0 + len(destroyable) * 1.5

    if "target opponent" in text:
        score += 3.0 if target_index != caster_index else -10.0
    if "target player" in text and "draw" not in text and damage == 0 and "gain" not in text:
        score += 0.5 if target_index != caster_index else 0.0

    if card.primary_type == "creature" and target_index == caster_index:
        score += 1.0

    # 2-player-specific nudge: don't bother if the (only) other player already
    # lost. Not generalized for 3+ players — no single well-defined "other".
    if len(game.players) == 2:
        other = game.players[1 - target_index]
        if other.life <= 0:
            score -= 1.0

    return score


def _score_cast(game: Game, caster_index: int, card: CardDefinition, target_index: int, x_value: int | None) -> float:
    caster = game.players[caster_index]
    opponent_index = choose_attack_target(game, caster_index)
    opponent = game.players[opponent_index]

    if card.primary_type == "land":
        untapped_lands = sum(
            1
            for perm in game.controlled_by(caster)
            if perm.card.primary_type == "land" and not perm.tapped
        )
        return 1.0 if untapped_lands < 4 else 0.2

    score = 1.5
    if card.primary_type in {"instant", "sorcery"}:
        score += 2.0
    if card.primary_type == "creature":
        score += 1.2
        score += _creature_stat(card, "power") * 0.7
        score += _creature_stat(card, "toughness") * 0.4
    if card.primary_type in {"artifact", "enchantment"}:
        score += 0.8

    score += _score_spell_target(card, caster_index, target_index, game, x_value)

    if x_value is not None:
        score += min(4.0, x_value * 0.6)

    # Card advantage: the cards this spell draws, less the one spent casting it.
    # The weight is tuning; which cards it applies to is not, and it used to be
    # a flat +8.0 for one name — worth exactly 4.0 per net card at the three
    # that name draws, and nothing at all to every other draw spell.
    drawn = cards_drawn_by_target(card, x_value)
    if drawn is not None:
        score += 4.0 * (drawn - 1)
        # Never self-target a draw that outruns the library: CR 704.5b on the
        # next draw step.
        if target_index == caster_index and len(caster.library) <= drawn:
            return -100.0

    # Burn that closes the game outranks everything. The threshold used to read
    # ``card.name == "Lightning Bolt" and opponent.life <= 3`` — which is that
    # card's damage spelled out, so any other lethal burn spell got nothing.
    damage = _extract_damage(card) or _estimate_x_damage(game, caster, card)
    if damage > 0 and target_index == opponent_index and opponent.life <= damage:
        score += 12.0

    # A mana source is worth playing early when there is something to spend the
    # mana on, and worth nothing at all when mana costs are not enforced. True
    # of every Mox, Sol Ring and Basalt Monolith here; only Black Lotus was named.
    if mana_ability_amount(card) is not None:
        if game.enforce_mana_costs:
            hand_nonlands = sum(1 for hand_card in caster.hand if hand_card.primary_type != "land")
            score += 2.0 if hand_nonlands >= 2 else 0.5
        else:
            score -= 2.0

    return score


def _score_activation(
    game: Game,
    player_index: int,
    instruction: OracleInstruction,
    target_index: int,
) -> float:
    """Score one activated ability. The *source permanent* is deliberately not a
    parameter: the last thing that read it asked for its name, and everything an
    activation is worth is in the instruction it puts on the stack."""
    score = 1.0

    if instruction.kind == "deal_damage":
        # A *defined* amount ("…equal to the number of pain counters removed
        # this way", Torture Chamber) is the payload's "x", and this was
        # ``int("x")``: a ValueError out of the chooser, which killed the whole
        # simulated run — and the web app's AI step — the first time a seat
        # held one untapped in a main phase. One is the floor every other
        # unread amount here gets.
        raw_amount = instruction.payload.get("amount", 1)
        amount = (
            raw_amount if isinstance(raw_amount, int) and not isinstance(raw_amount, bool)
            else int(raw_amount) if isinstance(raw_amount, str) and raw_amount.isdigit()
            else 1
        ) or 1
        target_player = game.players[target_index]
        effective_damage = max(0, amount - target_player.damage_prevention_pool)
        if effective_damage == 0:
            return -10.0
        score += 5.0 + effective_damage
        if target_index == choose_attack_target(game, player_index) and target_player.life <= effective_damage:
            score += 10.0
    elif instruction.kind == "draw_target_cards":
        score += 5.0 if target_index == player_index else 0.0
    elif is_mana_ability(instruction):
        score += 2.5
    elif instruction.kind == "grant_banding_to_target":
        score += 0.5
    else:
        score += 1.5

    # Drawing more cards than the library holds loses the game (CR 704.5b). This
    # was ``permanent.card.name == "Jayemdae Tome" and not library`` — that card's
    # one-card draw spelled out, so Jandor's Ring drew the AI to death.
    drawn = cards_drawn_by_controller(instruction)
    if drawn is not None and len(game.players[player_index].library) < drawn:
        return -100.0

    return score


# --- What a toll's two losses are worth against each other -------------------
#
# The prices, in life-equivalents. Weights are tuning and belong here; *which
# resources a branch takes* is `ai_valuation.toll_branch_loss`'s derivation
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


def _toll_loss_price(game: Game, player_index: int, loss) -> float:
    """One branch's `ai_valuation.TollLoss`, priced in life-equivalents."""
    player = game.players[player_index]
    if loss.life and loss.life >= player.life:
        return _TOLL_LETHAL_PRICE
    price = float(loss.life)
    price += loss.cards * _TOLL_CARD_PRICE
    price += loss.milled * _TOLL_MILL_PRICE
    for permanent in loss.permanents:
        price += _TOLL_PERMANENT_FLOOR + _permanent_value(permanent)
    if loss.taps_source:
        price += _TOLL_TAP_PRICE
    return price


def toll_decline_is_smaller_loss(
    game: Game, player_index: int, entry: dict, self_recipients=()
) -> bool:
    """Whether taking this toll's printed penalty loses less than paying its
    price — the valuation behind **take gifts, pay tolls, make no trades**'
    middle word, for the seat nobody asked (`_default_optional_pay`).

    A *toll* is an offer with a printed decline consequence, so both answers
    are losses: "pay 2 life" against "sacrifice this enchantment" (Season of
    the Witch), "sacrifice that artifact" against "2 damage" (Curse Artifact).
    Both sides are derived from the compiled program by
    `ai_valuation.toll_branch_loss` and priced by the weights above; a side the
    program cannot price answers False, which keeps the standing policy — pay
    tolls — rather than comparing a number to a guess.

    Deliberately silent on a mana-priced toll: the default pays those out of
    floating mana and, since ``optional_pay_may_tap_lands``, out of untapped
    lands too — always, because a toll's other answer is a loss as well and
    the standing policy is to pay. Pricing a tapped land against the penalty
    is a weight nobody has measured a need for yet.

    *entry* is the armed `optional_pay` data and *self_recipients* the printed
    player references that resolve to the offered seat, both supplied by the
    resolution because only it knows them.
    """
    penalty_steps = tuple(entry.get("_on_decline") or ())
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
    paying = toll_branch_loss(
        game, player_index, tuple(entry.get("_on_accept") or ()),
        self_recipients, source,
    )
    if paying is None:
        return False
    life_cost = int(entry.get("life_cost", 0) or 0)
    if life_cost:
        paying = paying.plus_life(life_cost)
    declining = toll_branch_loss(
        game, player_index, penalty_steps, self_recipients, source
    )
    if declining is None:
        return False
    if legacy_damage:
        declining = declining.plus_life(legacy_damage)
    return _toll_loss_price(game, player_index, declining) < _toll_loss_price(
        game, player_index, paying
    )


def _target_change_side(game: Game, item) -> str | None:
    """Whose side the object's controller wanted its target on — "opponent"
    for an effect that hampers what it targets, "you" for one that helps —
    or None where the compiled program does not say.

    The same readers every other aiming decision here uses
    (``spell_target_side`` for a spell, ``ability_target_side`` /
    ``activation_target_side`` for an ability), so "which way does this effect
    cut" has one answer whether the seat is choosing the target or changing it.
    """
    from .ai_valuation import activation_target_side

    instruction = getattr(item, "ability_instruction", None)
    if instruction is not None:
        return ability_target_side(instruction) or activation_target_side(instruction)
    if getattr(item, "is_ability", False):
        return None
    spell = item.card
    side = spell_target_side(spell)
    if side is not None:
        return side
    # A spell whose steps carry no ``targets`` description for that reader
    # ("any target", Lightning Bolt) is still read by its instruction's family,
    # exactly as an ability of the same effect is one branch up. An instant or
    # sorcery only: a permanent spell's instructions are a mirror of what the
    # permanent does, not a program the spell runs.
    printed_types = (spell.type_line or "").lower()
    if "instant" not in printed_types and "sorcery" not in printed_types:
        return None
    executed = game._select_executable_instruction(
        spell, getattr(item, "chosen_mode_index", None)
    )
    if executed is None:
        return None
    return ability_target_side(executed) or activation_target_side(executed)


def choose_target_change(game: Game, seat: int, item, slots) -> "list | None":
    """What a non-interactive *seat* does when it "may change the target or
    targets" of *item* (Psychic Battle): the picks, one per slot, or None to
    leave them as they are.

    The stated policy, and it is one sentence: **move harm off my side, move
    help onto it, and otherwise leave it.**

    * an effect its controller aimed to *hurt* (the program's side is
      "opponent") that points at this seat or something it controls is moved —
      to the controller's own side where a legal target is there, else to any
      target that is not this seat's;
    * an effect aimed to *help* (side "you") that somebody else controls and
      that is not already on this seat's side is moved onto it;
    * everything else — an effect with no derivable side, a harmful one
      already pointing elsewhere, this seat's own helpful one — is left alone.

    **One target only.** CR 115.7a makes a change all-or-nothing, so moving a
    several-target effect means accepting a new target for every slot, and
    whether that is a gain is a trade this policy does not price — "make no
    trades", the rule ``_default_optional_pay`` already keeps.

    Deterministic: candidates are taken in the order the enumeration lists
    them, which is board order.
    """
    if len(slots) != 1:
        return None
    slot = slots[0]
    if slot.current.kind not in ("player", "permanent"):
        return None
    side = _target_change_side(game, item)
    if side is None:
        return None

    def controller_of(target) -> int | None:
        if target.kind == "player":
            return target.seat
        if target.kind != "permanent":
            return None
        permanent = game.permanent_by_id(target.permanent_id)
        return None if permanent is None else game.controller_index_of(permanent)

    candidates = [
        candidate for candidate in slot.candidates
        if candidate.kind in ("player", "permanent")
    ]
    mine = controller_of(slot.current) == seat
    if side == "opponent":
        if not mine:
            return None
        elsewhere = [c for c in candidates if controller_of(c) != seat]
        back_at_them = [c for c in elsewhere if controller_of(c) == item.caster_index]
        pick = (back_at_them or elsewhere or [None])[0]
        return None if pick is None else [pick]
    if side == "you":
        if mine or item.caster_index == seat:
            return None
        onto_mine = [c for c in candidates if controller_of(c) == seat]
        return [onto_mine[0]] if onto_mine else None
    return None


#: Lands — on the battlefield and in hand — below which a seat gives up its
#: draw step for a land card (`offer_trade_is_worth_taking`). The number the
#: tutor score already uses for "mana-screwed" is three; one more, because the
#: card bought here costs a draw rather than a tutor.
LAND_FOR_DRAW_FLOOR = 4
def offer_trade_is_worth_taking(
    game: Game, player_index: int, entry: dict
) -> "bool | None":
    """Whether a seat nobody asks takes a "you may A. If you do, B." offer
    whose two halves are a price and a purchase (`ai_valuation.offer_trade`) —
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
    """
    trade = offer_trade(entry.get("_on_accept") or ())
    if trade is None:
        return None
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


def chained_toll_declined(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asked declines one link of an "unless **any
    player** pays" chain (`handlers/control_flow.unless_player_pays`).

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
    if not unpaid:
        return player_index == controller
    loss = toll_branch_loss(
        game, controller, unpaid, {"caster"}, entry.get("_source_permanent")
    )
    unpaid_is_a_loss = loss is not None and loss != TollLoss()
    return (player_index == controller) != unpaid_is_a_loss


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
      ``choose_cast_action`` answers, asked of the same candidates.
    * **And only a gift the seat's own object offers.** An offer another
      seat's spell makes this one ("that player may pay {R}{R}. If the player
      does, they may copy this spell", Chain Lightning) is priced by a card
      somebody else chose to cast, and what accepting does is left to defaults
      this policy cannot value — the copy keeps its original target, which is
      the payer's own creature. Those keep the floating-mana rule.
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
    if entry.get("_on_decline") or int(entry.get("damage", 0) or 0) > 0:
        loss = _life_only_toll(entry)
        if loss is None or game.active_player_index != player_index:
            return True
        payer = game.players[player_index]
        if payer.life - loss < LIFE_TOLL_FLOOR:
            return True
        return not any(
            card.primary_type != "land"
            and _cast_candidate(game, player_index, card, hand_index) is not None
            for hand_index, card in hand_spells(payer)
        )
    context = entry.get("_context")
    if getattr(context, "caster", None) is not game.players[player_index]:
        return False
    if game.active_player_index != player_index:
        return True
    return not any(
        card.primary_type != "land"
        and _cast_candidate(game, player_index, card, hand_index) is not None
        for hand_index, card in hand_spells(game.players[player_index])
    )


def order_hand_pick(
    game: Game, player_index: int, candidates, payload: dict, source_card
) -> list[int]:
    """*candidates* (hand slots) in the order a seat nobody asked should pick
    them for a "choose a card in your hand" (`_default_choose_cards_in_hand`).

    Unchanged — hand order, the stated default — unless the program behind the
    pick puts the picked card onto the battlefield for its owner
    (``ai_valuation.hand_pick_entry_consumer``). Then the cards that sentence
    admits come first, and among them the one at its superlative's extreme:
    "with the **lowest** mana value" enters only the lowest, so the cheapest
    admitted card is the pick that can win the comparison. Everything else
    keeps its hand order behind them.
    """
    from .ai_valuation import hand_pick_entry_consumer
    from .handlers._common import _card_matches_filter

    order = list(candidates)
    key = str((payload or {}).get("result_key") or "chosen_hand_cards")
    consumer = hand_pick_entry_consumer(source_card, key) if source_card else None
    if consumer is None:
        return order
    player = game.players[player_index]
    admitted = [
        slot for slot in order
        if _card_matches_filter(
            player.hand[slot], consumer["card_filter"], game=game, owner=player
        )
    ]
    superlative = consumer["superlative"]
    if superlative.get("characteristic") == "mana_value":
        sign = 1 if superlative.get("extreme") == "least" else -1
        admitted.sort(key=lambda slot: (sign * int(player.hand[slot].cmc or 0), slot))
    return admitted + [slot for slot in order if slot not in admitted]


def _choose_equip_target(game: Game, player_index: int, equipment) -> int | None:
    """The battlefield index of the creature *equipment* should be moved onto,
    or None when it is already on the best one (or there is none).

    The biggest creature that can attack — power first, then toughness — among
    the ones the Equipment may legally equip, asked of the same legality the
    engine enforces (``engine/equipment.py``) so the AI never activates an
    equip the engine then refuses. Summoning-sick creatures are not excluded:
    an Equipment moved onto one now is on it when it can attack next turn, and
    the +1/+1 blocks just as well meanwhile.
    """
    from .equipment import equip_refusal, equipped_creature

    player = game.players[player_index]
    candidates = [
        (idx, perm)
        for idx, perm in enumerate(player.battlefield)
        if perm.is_creature and equip_refusal(game, equipment, perm) is None
    ]
    if not candidates:
        return None
    best_index, best = max(
        candidates,
        key=lambda pair: (pair[1].effective_power, pair[1].effective_toughness, -pair[0]),
    )
    if equipped_creature(equipment) is best:
        return None
    return best_index


def _choose_target_for_instruction(instruction: OracleInstruction, caster_index: int, game: Game) -> int:
    if is_mana_ability(instruction):
        # Mana goes to its controller's pool; the ability has no other target.
        return caster_index
    if instruction.kind == "attach_source_to_target":
        # "Target creature you control" — the equip's creature is the
        # activator's own (CR 702.6a).
        return caster_index
    if instruction.kind in {"draw_target_cards", "gain_life", "prevent_damage"}:
        return caster_index
    # "deal_damage"/"destroy_target"/etc., and the fallback for any other
    # proactive effect: target an opponent (MVP heuristic, see
    # choose_attack_target — lowest life among living opponents).
    return choose_attack_target(game, caster_index)


def _estimate_x_damage(game: Game, caster: PlayerState, card: CardDefinition) -> int:
    """Estimate the damage an X-damage spell would deal, based on the most X the
    caster can currently pay for. Returns 0 for spells that don't deal X damage."""
    program = compile_card_oracle(card)
    deals_x_damage = any(
        instruction.kind == "deal_damage"
        and str(instruction.payload.get("amount")).lower() == "x"
        for instruction in program.instructions
    )
    if not deals_x_damage:
        return 0
    return _max_affordable_x(game, caster, card)


def _extract_damage(card: CardDefinition) -> int:
    program = compile_card_oracle(card)
    for instruction in program.instructions:
        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount")
            if isinstance(amount, int):
                return amount
    match = re.search(r"deals? (\d+) damage", card.oracle_text.lower())
    if match:
        return int(match.group(1))
    return 0


def _creature_stat(card: CardDefinition, key: str) -> int:
    raw_value = str(card.raw.get(key, "0"))
    return int(raw_value) if raw_value.isdigit() else 0


def _cost_for(
    game: Game,
    player: PlayerState,
    card: CardDefinition,
    x_value: int | None,
    extra_generic: int = 0,
) -> dict[str, int]:
    """What *player* actually pays for *card* — CR 601.2f, increases then
    reductions, through the same three functions the cast path calls.

    *extra_generic* is a generic surcharge the cast will carry that no
    registered modifier states — today the commander tax (CR 903.8), which the
    cast path adds to its own ``extra_generic_tax`` the same way. Zero for
    every hand cast.

    The seat is threaded rather than assumed. This used to pass 0 with a comment
    saying no registered modifier depended on it, which was true while every one
    of them was scoped by the *card's* colour; it stopped being true the moment
    a card printed "spells **you cast** cost {1} less", and a claim about the
    pool expires without anyone editing the comment. Identity, not
    ``players.index``: PlayerState is value-compared.
    """
    seat = next((i for i, seated in enumerate(game.players) if seated is player), 0)
    tax, _names = spell_cost_tax(game, seat, card)
    tax += max(0, extra_generic)
    # The coloured half of the same taxes (Derelor). Asked here too, because the
    # AI prices a spell to decide whether it can cast it — priced without the
    # pip it proposes a cast the rules then refuse, every turn, forever.
    pips, _pip_names = spell_symbol_tax(game, seat, card)
    reduction, _reducers = cost_reduction_for_cast(game, seat, card)
    # The best split of X among the colours the card allows, which is the one
    # the cast path will try first (`casting._x_color_allocations`). The AI is
    # sizing the cost, so it wants the payment that will actually be attempted;
    # a split the cast would not choose prices a different spell.
    allocation = game._x_color_allocations(
        x_spend_colors_from_text(card.oracle_text), max(0, x_value or 0)
    )[0]
    return reduce_cost(
        game._parse_mana_cost(
            card.mana_cost,
            x_value=x_value,
            extra_generic=tax,
            x_allocation=allocation,
            extra_pips=pips,
        ),
        reduction,
    )


#: Life a seat keeps back when the X it announces is paid in life ("As an
#: additional cost to cast this spell, pay X life") — the reserve the buyback
#: and foreign-activation prices keep, for the same reason.
X_LIFE_RESERVE = 10


def _pick_x_value(
    game: Game, player: PlayerState, card: CardDefinition,
    extra_generic: int = 0, hand_index: int | None = None,
) -> int | None:
    """The X this seat announces for *card* (CR 107.3a), or None where the card
    asks for none.

    **The mana cost is only one of the four places CR 107.3a names**, and this
    asked only that one. Fire Covenant ({1}{B}{R}, "pay X life"), Infernal
    Harvest ({1}{B}, "return X Swamps") and Haunting Misery ({1}{B}{B}, "exile
    X creature cards") print no {X} anywhere, so the AI announced nothing, the
    cast fell back to the 0 an unmade CR 107.3a announcement reads as here, and
    all three shipped spells resolved
    doing precisely nothing — legal, since 0 is a choice, and invisible to both
    honesty checks: the cast is not refused and it does interact. This is the
    same one-place-short reading ``cast_announces_x`` was written for on the
    browser's side of the question, so it is the same reader that answers it.

    The ceiling is not the mana pool for those: it is a life total or a board or
    a hand, and ``_additional_cost_x_ceiling`` is what
    ``_unpayable_additional_cost`` will measure the announcement against — asked
    here so the policy announces exactly what the cast will accept.

    *hand_index* is which copy is being cast, and it matters to the ceiling: the
    spell is on the stack before its costs are paid (CR 601.2a), so it cannot be
    one of the cards discarded for Firestorm's "discard X cards". Omitted by the
    two callers that are pricing a card rather than casting one, where an X one
    too high is a bound and not an announcement.
    """
    if "{X}" not in card.mana_cost.upper():
        if not cast_announces_x(card):
            return None
        seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), 0
        )
        bound = game._additional_cost_x_ceiling(
            seat, card, from_zone="hand", spell_hand_index=hand_index,
        )
        if bound is None:
            return None
        # **The ceiling is what the cast will accept, not what a seat should
        # pay.** For "pay X life" it is the seat's whole life total (CR 119.4
        # lets a player pay all of it), so the announcement was X = 20 at 20
        # life: Fire Covenant and Hatred each paid their caster down to zero,
        # and the game was lost to the state-based check behind the spell
        # (CR 704.5a). The same reserve every other life price in this policy
        # keeps (`BUYBACK_LIFE_RESERVE`); with nothing above it the X is 0 and
        # the caller does not propose the cast.
        if any(cost.pay_life_x for cost in additional_costs(card)):
            bound = min(bound, max(0, player.life - X_LIFE_RESERVE))
        return bound

    max_x = _max_affordable_x(game, player, card, extra_generic)
    return max_x


def _max_affordable_x(
    game: Game, player: PlayerState, card: CardDefinition, extra_generic: int = 0
) -> int:
    # Through the tap planner rather than a summed preview pool: the preview
    # counted each land as one fixed symbol, so a dual or a swapped land could
    # only ever pay for the first colour it listed, and the X it sized was the
    # X a board of single-colour lands would afford.
    for x_value in range(15, -1, -1):
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        if _plan_land_taps(game, player, required) is not None:
            return x_value
    return 0


def _plan_land_taps(
    game: Game, player: PlayerState, required: dict[str, int],
    *, paying_for: "Permanent | None" = None,
) -> tuple[tuple[int, ...], tuple[str, ...]] | None:
    """Which untapped lands to tap for *required*, and **which colour to ask
    each one for**: ``(slots, colours)`` in tap order, or None when the board
    cannot pay.

    What a land can make is the engine's answer, ``Game._land_payment_colors``
    — the hook the optional-pay planner and the client's colour prompt read —
    and not the printed summary's first symbol, which is what this read. That
    one symbol was wrong three ways, measured at NEM: under a seat-wide swap
    (Deep Water, Harvest Mage) a Forest makes {U} or a colour of the tapper's
    choice, so the plan tapped it for a {G} it would not make; a land carrying
    a granted ability (Overlaid Terrain's "{T}: Add two mana of any one
    color") was still the colour it was printed; and a dual land could only
    ever pay its first colour.

    The colour travels with the plan because the tap seam asks for one
    (``tap_land_for_mana``'s ``chosen_color``) and the executors sent the
    default "G" for every land — so a Taiga the plan counted as {R} made {G},
    and a land under Harvest Mage made green whatever the plan needed.

    The greedy order is the one this function always had, so a board of
    single-colour lands is planned exactly as before: a pip is matched first
    by lands whose **first** colour it is, in battlefield order, and only then
    by a land that lists it further along; the generic remainder takes each
    land at its first colour. **How much** a tap makes is
    :func:`_land_mana_amount` — two for a land under Overlaid Terrain, which
    this counted as one and so planned a two-land board as unable to cast
    anything costing three.
    """
    pool = {symbol: player.mana_pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    # Only a land the tap seam will make mana from (`land_mana_tap_refusal`,
    # the seam's own gate): an untapped land is not a mana. A storage land with
    # no counter, a Bazaar of Baghdad or a summoning-sick land creature counted
    # as one here, the executor's tap of it made nothing, and the cast it was
    # planned for was refused "insufficient mana" — the same spell every turn,
    # once the simulator enforced costs (5ED: Sand Silos, 14 refusals a run).
    #
    # **Rhystic Cave is the land that must never be here**: "Activate only as
    # an instant" means its mana needs priority (CR 304.5), which nobody has
    # while a cost is being paid, and any player may deny it. The seam's gate
    # reads `_land_mana_abilities`, whose answer for the Cave is "cannot be
    # run inside a payment" — the same reading `mana_payment.taps_for_payment`
    # gives the optional-pay planner, so the two planners agree about it.
    #
    # Nor one whose mana is **restricted** ("Spend this mana only to cast
    # artifact spells", Mishra's Workshop): it goes into its own bucket
    # (CR 106.6), this planner is not told what the mana is for, and counted
    # as a generic mana it paid for a Priest of Yawgmoth the bucket cannot.
    # Nor one whose output the rest of the board decides (Gaea's Cradle with
    # no creature makes nothing) — `_land_mana_is_unplannable`.
    untapped_lands = [
        (index, _land_symbols(game, permanent), _land_mana_amount(game, permanent))
        for index, permanent in enumerate(game.controlled_by(player))
        if game.land_mana_tap_refusal(permanent) is None
        and not _land_mana_is_unplannable(game, permanent)
    ]
    # **And the non-land sources, after every land** (`_nonland_mana_source`:
    # the Moxen, Sol Ring, Llanowar Elves). After, because the greedy below
    # takes its matches in this list's order and a land is the source that
    # costs nothing to tap: a Mana Vault stays tapped, an Elves of Deep Shadow
    # deals its controller a damage, and a creature tapped for mana does not
    # attack. So a board whose lands pay is planned exactly as it always was,
    # and the rest is what a seat reaches for when they do not.
    #
    # Never the permanent whose own ability is being paid for (*paying_for*):
    # its {T} may be that ability's cost, and one tap cannot pay both.
    seat = next((i for i, seated in enumerate(game.players) if seated is player), None)
    nonland_runs: dict[int, dict[str, int]] = {}
    if seat is not None:
        for index, permanent in enumerate(game.controlled_by(player)):
            if permanent is paying_for:
                continue
            source = _nonland_mana_source(game, seat, permanent)
            if source is None:
                continue
            untapped_lands.append((index, source.symbols, source.amount))
            if source.run is not None:
                nonland_runs[index] = source.run
    # **What a tap of a mixed land really makes.** "{T}: Add {C}{U}." (Coral
    # Atoll and the rest of the Karoo cycle, Soldevi Excavations, Balduvian
    # Trading Post) is two mana of two *different* symbols, and `take` below
    # credited `amount` of whichever one symbol the pip loop asked for — so an
    # Atoll read as {U}{U}, a {U}{U} spell was planned on it alone, the tap
    # made {C}{U} and the cast was refused. Seven lands in the pool, measured;
    # every other land's run is one symbol and is credited as it always was.
    mixed_runs = {
        index: run
        for index, permanent in enumerate(game.controlled_by(player))
        if (run := _land_mixed_run(game, permanent)) is not None
    }
    mixed_runs.update(nonland_runs)

    if _can_pay_cost(pool, required, player):
        return (), ()

    chosen: list[int] = []
    colors: list[str] = []
    remaining = list(untapped_lands)

    def take(position: int, symbol: str) -> None:
        land_index, _symbols, amount = remaining.pop(position)
        chosen.append(land_index)
        colors.append(symbol)
        run = mixed_runs.get(land_index)
        if run is not None:
            for made, count in run.items():
                pool[made] = pool.get(made, 0) + count
            return
        pool[symbol] = pool.get(symbol, 0) + amount

    for symbol in _MANA_SYMBOLS:
        while required.get(symbol, 0) - pool.get(symbol, 0) > 0:
            match_idx = next(
                (idx for idx, (_, makes, _n) in enumerate(remaining) if makes[0] == symbol),
                None,
            )
            if match_idx is None:
                match_idx = next(
                    (idx for idx, (_, makes, _n) in enumerate(remaining) if symbol in makes),
                    None,
                )
            if match_idx is None:
                break
            take(match_idx, symbol)

    while remaining and not _can_pay_cost(pool, required, player):
        best_idx = 0
        best_benefit = -1
        for idx, (_, makes, _n) in enumerate(remaining):
            produced = makes[0]
            benefit = 2 if pool.get(produced, 0) < required.get(produced, 0) else 1
            if produced == "C" and required.get("generic", 0) == 0:
                benefit = 0
            if benefit > best_benefit:
                best_benefit = benefit
                best_idx = idx
        take(best_idx, remaining[best_idx][1][0])

    if not _can_pay_cost(pool, required, player):
        return None

    return tuple(chosen), tuple(colors)


def _can_pay_cost(
    pool: dict[str, int], required: dict[str, int], payer: PlayerState
) -> bool:
    """Whether *payer* could pay *required* out of *pool*.

    *pool* is a **preview** — the seat's floating mana plus whatever its
    untapped lands would make — so it is passed rather than read off the payer;
    the payer is here for the CR 609.4 spending permissions, which are facts
    about the seat rather than about the pool.

    Both permissions, from one argument. This took ``can_spend_white_as_red``
    as a bare bool, so the wider one beside it (Chromatic Orrery's "you may
    spend mana as though it were mana of any color") was simply not asked, and
    a seat with a colourless pool judged every coloured spell in its hand
    uncastable. Nothing breaks visibly when an AI under-reports what it can pay
    — it just never casts, which is the "a seat doing nothing all game" shape
    ``simulate_ai_games.py`` counts as a refused cast.
    """
    can_spend_white_as_red = payer.can_spend_white_as_red
    if payer.spends_mana_as_any_color:
        # Every unit pays a coloured pip and a {C} still wants colourless —
        # through the engine's own arithmetic, so the AI's answer and the
        # payment's cannot drift.
        from .mana_payment import fungible_colors_headroom

        return fungible_colors_headroom(pool, required) is not None
    if pool.get("W", 0) < required.get("W", 0):
        return False
    if pool.get("U", 0) < required.get("U", 0):
        return False
    if pool.get("B", 0) < required.get("B", 0):
        return False
    if pool.get("G", 0) < required.get("G", 0):
        return False
    if pool.get("C", 0) < required.get("C", 0):
        return False

    available_red = pool.get("R", 0)
    if can_spend_white_as_red:
        available_red += pool.get("W", 0)
    if available_red < required.get("R", 0):
        return False

    temp = {symbol: pool.get(symbol, 0) for symbol in _MANA_SYMBOLS}
    temp["W"] -= required.get("W", 0)
    temp["U"] -= required.get("U", 0)
    temp["B"] -= required.get("B", 0)
    temp["G"] -= required.get("G", 0)
    temp["C"] -= required.get("C", 0)

    red_to_pay = required.get("R", 0)
    from_red = min(temp.get("R", 0), red_to_pay)
    temp["R"] -= from_red
    red_to_pay -= from_red
    if red_to_pay > 0:
        if not can_spend_white_as_red:
            return False
        if temp.get("W", 0) < red_to_pay:
            return False
        temp["W"] -= red_to_pay

    generic = required.get("generic", 0)
    if generic <= 0:
        return True

    available_generic = sum(max(0, temp.get(symbol, 0)) for symbol in ("C", "W", "U", "B", "R", "G"))
    return available_generic >= generic


def _land_mixed_run(game: Game, permanent: Permanent) -> "dict[str, int] | None":
    """The fixed run one tap of *permanent* makes when it is **two or more
    different symbols** ("{C}{U}", Coral Atoll), as ``{symbol: count}`` — or
    None for every other land, whose tap is a number of one symbol and is
    counted by `_land_mana_amount`.

    Read off the free ability the tap seam will run and only where nothing
    else decides the output: a seat-wide swap replaces the type (and perhaps
    the amount), and a multiplier or a restriction makes the run something
    this cannot state.
    """
    from . import land_mana_swaps

    if land_mana_swaps.swapped_production(game, permanent) is not None:
        return None
    free, _priced = game._land_mana_abilities(permanent)
    payload = (getattr(free, "payload", None) or {}) if free is not None else {}
    pips = payload.get("pips")
    if not pips or len(payload) != 1:
        return None
    run = {str(symbol): int(count) for symbol, count in pips}
    return run if len(run) >= 2 else None


def _land_mana_amount(game: Game, permanent: Permanent) -> int:
    """How many mana one tap of *permanent* makes, as the planner counts it.

    The free mana ability the tap seam will run (``_land_mana_abilities``):
    its pip run ("{C}{C}", Ancient Tomb) or its any-colour count ("two mana of
    any one color", the ability Overlaid Terrain grants). One wherever that
    cannot be read off the payload — a basic, a choice between pips, an amount
    behind a condition — and one under a swap that replaces the amount ("…one
    mana of a color of your choice instead of any other type **and amount**",
    Harvest Mage). Restricted mana ("Spend this mana only to cast artifact
    spells") counts one as well: the planner cannot tell which costs it may
    pay, and one is what it always assumed.
    """
    from . import land_mana_swaps

    swapped = land_mana_swaps.swapped_production(game, permanent)
    if swapped is not None and swapped.replaces_amount:
        return 1
    free, _priced = game._land_mana_abilities(permanent)
    payload = (getattr(free, "payload", None) or {}) if free is not None else {}
    if not payload or payload.get("spend_only"):
        return 1
    pips = payload.get("pips")
    if pips:
        return max(1, sum(int(count) for _symbol, count in pips))
    any_count = payload.get("any_color_count")
    if isinstance(any_count, int) and not isinstance(any_count, bool):
        return max(1, any_count)
    return 1


#: Payload keys on a land's add-mana step that make **how much** one tap
#: produces a fact about the rest of the board rather than about the land:
#: "{G} for each creature you control" (Gaea's Cradle), "{C} for each storage
#: counter on this land" (City of Shadows). The planner counts a tap as its
#: printed pips, so these read as one mana each — on an empty board, zero.
#:
#: ``any_type_from_lands`` ("one mana of any type that a land you control could
#: produce", Reflecting Pool) was a third entry here and is not one: its amount
#: is the printed one, and *which* type is `Game.narrowed_land_mana_colors`'
#: exact answer since PLS wave 1 — the same reader that makes Meteor Crater
#: plannable below. Listed here it stayed out of every plan, so a seat with a
#: Swamp and a Reflecting Pool could not cast a two-mana spell.
_BOARD_DEPENDENT_MANA_KEYS = ("per_each", "per_each_counter_on_source")


def _land_mana_is_unplannable(game: Game, land: Permanent) -> bool:
    """Whether the mana *land*'s default tap makes is one this planner cannot
    count: **restricted** ("Spend this mana only …", CR 106.6 — the
    ``spend_only`` the add-mana handler files it under, read where
    `_land_mana_amount` reads it), or **board-dependent**
    (`_BOARD_DEPENDENT_MANA_KEYS`). Left out of the plan rather than guessed
    at: a guess counted as mana is a cast refused for insufficient mana."""
    free, _priced = game._land_mana_abilities(land)
    if free is None:
        return False
    payload = free.payload or {}
    if payload.get("spend_only"):
        return True
    if any(
        (step.payload or {}).get(key)
        for step in (free, *((payload.get("steps") or ())))
        for key in _BOARD_DEPENDENT_MANA_KEYS
        if hasattr(step, "payload")
    ):
        return True
    # A land whose *colours* the board decides and whose amount it does not
    # ("Choose a color of a permanent you control. Add one mana of that
    # color.", Meteor Crater) is plannable for exactly what that board offers
    # now — `Game._land_payment_colors` answers with it — and unplannable only
    # where it offers nothing: `_land_symbols` would fall back to "C" for a
    # land with no symbol, the tap would make no mana, and the cast would be
    # refused for the same spell every turn.
    narrowed = game.narrowed_land_mana_colors(land)
    return narrowed is not None and not narrowed


def _tap_alone_land_symbols(game: Game, land: Permanent) -> set[str]:
    """Every symbol one of *land*'s tap-alone mana abilities makes — the
    abilities the tap seam runs (`planned_tap_ability` picks among them), and
    none it refuses (`land_mana_tap_refusal`)."""
    from .mixins.turn_management import is_tap_alone_mana_ability

    found: set[str] = set()
    usable = usable_activated_abilities(compile_card_oracle(game.playable_card_of(land)))
    for index, ability in enumerate(usable):
        if is_tap_alone_mana_ability(ability) and game.land_mana_tap_refusal(land, index) is None:
            found |= mana_ability_symbols(ability.instruction)
    return found


def _land_symbols(game: Game, permanent: Permanent) -> tuple[str, ...]:
    """Every symbol tapping *permanent* for mana could put in the pool, the one
    it would make unasked first.

    ``Game._land_payment_colors`` — the engine's own answer, swaps and granted
    abilities included — and the basic land types layer 4 gives it where that
    is silent. "C" for a land that names neither, which is what this planner
    has always assumed of one.
    """
    from . import land_mana_swaps

    symbols = tuple(game._land_payment_colors(permanent))
    free, _priced = game._land_mana_abilities(permanent)
    if symbols and game.narrowed_land_mana_colors(permanent) is not None:
        # A land whose colours the board defines (Reflecting Pool, Meteor
        # Crater): `_land_payment_colors` has already answered with exactly
        # what that board offers. The reordering below would widen it back to
        # every colour the compiled ability *could* name — "any color" reads
        # as all five there — which is the summary's mistake made a second
        # time.
        return symbols
    if symbols and free is not None and not land_mana_swaps.payment_colors(game, permanent):
        # **Only what the tap can make.** ``_land_payment_colors`` is the
        # printed summary for an unswapped land, and the summary lists every
        # symbol any of the land's abilities makes — including one behind a
        # mana price the tap seam will not pay: Henge of Ramos and Castle
        # Sengir summarise to five colours and tap for {C}. Counted as
        # coloured, the plan tapped them "for" a red pip, made {C} and the
        # spell was refused. So the symbols are the tap-alone abilities' own,
        # read off the compiled program (`mana_ability_symbols`).
        #
        # And what the **default** ability makes goes first, because the
        # planner pays generic mana with a land's first symbol and the tap
        # executor runs the default ability for it (`planned_tap_ability`):
        # the summary is alphabetical, so an Underground River ("B", "C", "U")
        # paid a generic {1} with its painful {B} rather than its {C}.
        default = mana_ability_symbols(free)
        reachable = set(default) | _tap_alone_land_symbols(game, permanent)
        ordered = [symbol for symbol in symbols if symbol in default]
        ordered += [symbol for symbol in symbols if symbol in reachable and symbol not in ordered]
        ordered += [symbol for symbol in sorted(reachable) if symbol not in ordered]
        if ordered:
            return tuple(ordered)
    if symbols:
        return symbols
    # Layer 4 already knows which basic land types this permanent currently
    # has, printed or granted by a type-changing effect.
    basic = tuple(permanent.basic_land_mana)
    return basic if basic else ("C",)
