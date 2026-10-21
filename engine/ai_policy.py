from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from itertools import combinations, product
from dataclasses import dataclass, replace
import re

from .ai_valuation import (
    Rehearsal,
    deliberating,
    has_a_creature_to_fight_with,
    priced_by_the_fight,
    permanent_worth,
    rehearse,
    rehearsing,
    OFFER_ALTERS,
    OFFER_KICKS,
    OFFER_RETURNS_SPELL,
    SPELL_TYPES,
    CastOffer,
    PermittedCast,
    cast_offers,
    cast_weighed,
    caster_chooses_a_mode,
    casting_under,
    considering_mode,
    hand_waiver,
    mode_considered,
    permitted_casts,
    spell_text,
    activation_target_side,
    entry_sacrifice_is_unavoidable,
    entry_self_return_gate,
    entry_trigger_seat_side,
    entry_trigger_target_side,
    entry_triggers_bought,
    ability_denies_its_target,
    ability_role_target_sides,
    ability_seat_side,
    ability_target_side,
    cards_drawn_by_controller,
    caster_sacrifice_steps,
    castable_commanders,
    divided_shape,
    exiles_a_graveyard_target,
    foreign_activation_use,
    graveyard_denial_order,
    hand_entry_steps,
    harms_its_own_source,
    named_counter_marks_for_harm,
    instruction_target_side,
    is_mana_ability,
    mana_ability_amount,
    mana_ability_symbols,
    offer_buys_a_drawback_to_its_source,
    offer_trade,
    planned_mana_yield,
    role_target_sides,
    several_target_slot_sides,
    source_becomes_an_aura,
    source_toughness_change,
    spell_denies_its_own_target,
    spell_hand_pick_entry_filters,
    spell_seat_side,
    spell_target_side,
    TollLoss,
    toll_branch_loss,
)
from .activation_permissions import activation_permission_denial
from .activation_prohibitions import activation_prohibition
from .activation_restrictions import activation_denial, global_activation_ban
from .cast_costs import additional_costs, cast_announces_x
from .cast_prohibitions import cast_prohibition
from .cast_restrictions import check_cast_timing
from .divided_damage import EACH
from .cost_modifiers import (CostReduction, cost_reduction_for_cast,
                             keyword_cost_modifiers, reduce_cost,
                             sacrifice_taxes, spell_cost_tax, spell_symbol_tax)
from .classifier import classify_card
from .faces import castable_faces, spell_named
from .game import Game
from .mana_payment import (COLOR_SYMBOLS, PIP_SYMBOLS, _match_colored,
                           may_pay_pip, plan_payment)
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
from .targeting import (GRAVEYARD_TARGET_KIND, SINGLE_GRAVEYARD,
                        announced_mode_instructions, bounce_subject_filter,
                        cast_target_slot, derive_activation_spec,
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
    # already speaks (`_cast_onto_stack`'s `from_zone`). "command" is a
    # commander cast (CR 903.8); "graveyard" / "exile" / "library" a cast an
    # effect permits (CR 601.3: flashback, Yawgmoth's Will, an Elkin Bottle's
    # card — `ai_valuation.permitted_casts`). Every executor forwards it
    # unchanged and finds the card through `zone_being_cast_from`.
    from_zone: str = "hand"
    # CR 118.9: pay an alternative cost rather than the spell's mana cost.
    # True on the one shape built from an unpayable mana cost (a printed
    # alternative cost this board can pay — `_alternative_cost_is_payable`)
    # and on a cast made under a permission that *requires* one (CR 118.9b,
    # CR 702.34a: flashback), where it is also what tells the cast path which
    # permission is meant (`PermittedCast.alternative_cost`).
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
    # CR 601.2b's other announcement: which mode of a "Choose one —" spell
    # this cast names, in the engine's own spelling (`queue_from_hand`'s
    # ``mode_index``, which becomes `StackItem.chosen_mode_index`). None for a
    # spell with no mode to choose and for one whose mode an opponent chooses
    # (CR 700.2e). The field did not exist, so every modal spell an AI seat
    # cast was announced with no mode, which the engine resolves as the first
    # bullet: 34 of the pool's 88 modes were reachable, and a Charm whose first
    # bullet had nothing to point at was a card the seat held all game. See
    # `_cast_candidate`.
    mode_index: int | None = None
    # ...and the same announcement for a "Choose one **or more** —" spell that
    # takes several (Sublime Epiphany), in the shape `queue_from_hand`'s
    # ``mode_choices`` takes them: one dict per chosen mode, each carrying its
    # own seat and slot. None for every cast naming a single mode, which is
    # every other one -- the engine reads one entry exactly as it reads
    # ``mode_index``, so a single mode is never spelled this way.
    mode_choices: list[dict] | None = None
    # The spell on the stack this cast names (CR 601.2c), as the engine's own
    # bottom-first index (`queue_from_hand`'s ``target_stack_index``). None is
    # "name nothing", which is every cast this policy made before and still
    # every cast whose effect is not guarded by a condition on that spell: the
    # engine then answers with the spell on top. Set where which spell matters
    # — "Counter target spell **if it's blue**" (`_guarded_stack_target`).
    target_stack_index: int | None = None
    # Whose copy of ``from_zone`` ``hand_index`` indexes into, when that is not
    # the caster's own: "Search target opponent's library for a card and exile
    # it. … you may play that card" (Grinning Totem) leaves the card in the
    # *searched* player's exile pile (this engine keeps one per owner). None
    # is the caster's own, which is every other cast. **Not an announcement**
    # — the cast path finds the pile for itself, by the permission — so
    # `cast_announcement` does not carry it; it is for the executor, which
    # reads the card off the zone (`zone_being_cast_from`).
    zone_seat: int | None = None


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


def cast_announcement(action: CastAction) -> dict:
    """Everything *action* announces (CR 601.2b–d), as the keywords
    ``Game.queue_from_hand`` / ``cast_from_hand`` take it by.

    **The one place a `CastAction` becomes a cast.** There are five executors
    — the simulator's main phase, and in ``web/game_flow`` the AI step's two
    arms, the priority response and the declare-blockers instant — and each
    spelled the forwarding out for itself, so a field added to the action was
    five places to remember it. They had drifted: the two instant executors
    forwarded neither an optional cost nor an alternative one. The mode is the
    field that made five copies one function, because a mode dropped by an
    executor is not refused — it is quietly cast as the first bullet, aimed at
    the target chosen for another.

    The card's name is not here: the spell is `spell_being_cast`'s, which
    reads the zone.
    """
    return {
        "target_player_index": action.target_player_index,
        "target_permanent_index": action.target_permanent_index,
        "target_permanent_ids": action.target_permanent_ids,
        "x_value": action.x_value,
        "from_zone": action.from_zone,
        # CR 118.9. Dropped, the cast falls back to a mana cost the policy has
        # already established this seat cannot pay, and is refused.
        "alternative_cost": action.alternative_cost,
        # CR 601.2d: the division is part of the announcement, and a cast that
        # drops it is refused now that the gate asks for one.
        "divided_targets": action.divided_targets,
        # CR 601.2b's optional costs (a kicker): the plan tapped the lands for
        # them, and a cast that drops the announcement pays the printed cost
        # and leaves the rest in the pool.
        "optional_cost_payments": action.optional_cost_payments,
        # CR 601.2b's mode. See `CastAction.mode_index`.
        "mode_index": action.mode_index,
        "mode_choices": action.mode_choices,
        "target_stack_index": action.target_stack_index,
    }


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
    # The game's own answer (``Game.land_mana_ability_for``): the engine's
    # payer for a cost an effect collects asks the same question, and it is
    # not a policy.
    return game.land_mana_ability_for(land, color)


def tap_planned_lands(game: Game, seat: int, action):
    """Tap the mana sources *action*'s plan names into *seat*'s pool, each for
    the colour the plan counted on and through the mana ability that makes it
    — and return *action* **as it reads once that is done**.

    **The AI's payment**, shared by every executor — the simulator's and the
    web app's AI seat — so the two pay the same way: the policy plans the taps
    (`_plan_land_taps`), this fills the pool, and the cast or activation that
    follows spends it (CR 601.2g-h). Every slot is resolved to its permanent
    before the first tap and tapped **by id**, so a tap that moved anything
    cannot shift a later slot onto a different permanent.

    A **land** goes through the engine's tap seam. A **non-land** source the
    plan counted (`_nonland_mana_source`: Sol Ring, a Mox, Llanowar Elves, and
    Black Lotus) has no seam — CR 605.1a makes its "{T}: Add …" an activated
    ability like any other — so it is activated, which for a mana ability
    resolves inline (CR 605.3b) and leaves the mana in the pool exactly as a
    land's tap does.

    **The returned action is the one to announce.** A `CastAction` and an
    `ActivationAction` name their targets — and an activation its own source —
    by battlefield **slot**, and a source that pays by leaving ("{T}, Sacrifice
    this artifact: Add three mana of any one color") renumbers every slot
    behind it (CR 400.7: what is in slot 4 afterwards is a different object).
    That is why no such source was ever planned: a Giant Growth announced at
    slot 3 and paid for with the Lotus in slot 1 would have landed on whatever
    slid into slot 3. So every slot the action names is bound to its permanent
    before the first tap and read back afterwards (`_bind_action_slots`,
    `_rebound_action`); an executor announces what this returns, never the
    action it handed in. When nothing moved the same object comes back.
    """
    bound = _bind_action_slots(game, seat, action)
    before = _battlefield_order(game)
    planned = [game.permanent_at(seat, index) for index in action.land_tap_indices]
    for position, land in enumerate(planned):
        permanent_id = game.permanent_id_of(land)
        if permanent_id is None:
            continue
        color = planned_tap_color(action, position)
        source = _nonland_mana_source(game, seat, land, may_sacrifice=True)
        if source is not None:
            slot = game.battlefield_index_of(land)
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
        # A source whose mana ability costs mana ("{1}, {T}: Add {U}{B}.", the
        # Odyssey filter lands; Mana Cylix). The plan put the tap that pays
        # for it immediately in front of it (`_plan_through_a_priced_source`),
        # so the pool holds its price now; activated like the non-land source
        # above, and for the same reason — the tap seam runs only an ability
        # whose whole cost is {T}.
        priced = _priced_mana_source(game, seat, land)
        if priced is not None:
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
                ability_index=priced.ability_index,
                mana_color=color if color in ("W", "U", "B", "R", "G") else None,
            )
            continue
        game.tap_land_for_mana(
            seat, land.card.name,
            chosen_color=color,
            permanent_id=permanent_id,
            ability_index=planned_tap_ability(game, land, color),
        )
    if _battlefield_order(game) == before:
        return action
    return _rebound_action(game, action, bound)


def _battlefield_order(game: Game) -> list[list[int]]:
    """Which object is in which slot, per seat — by identity, so a look-alike
    that slid into a vacated slot reads as the change it is."""
    return [
        [id(permanent) for permanent in game.controlled_by(seat)]
        for seat in range(len(game.players))
    ]


def _bind_action_slots(game: Game, seat: int, action) -> dict:
    """Every battlefield slot *action* names, as the permanent that is in it
    now — the half of `tap_planned_lands`' re-binding taken before a payment.

    One reader for the three places an action keeps a slot: a cast's or an
    activation's ``target_permanent_index`` (one slot or several, counted into
    ``target_player_index``'s battlefield), a divided announcement's
    ``(seat, slot[, share])`` entries, a several-mode cast's per-mode slot —
    and an activation's own ``permanent_index``, counted into
    ``source_controller_index``'s battlefield when it names one. A field the
    action does not have is simply not bound, so the three action shapes need
    no arm each.
    """
    bound: dict = {}
    target_seat = getattr(action, "target_player_index", None)
    slots = getattr(action, "target_permanent_index", None)
    if isinstance(slots, int):
        bound["target"] = game.permanent_at(target_seat, slots)
    elif slots:
        bound["targets"] = [game.permanent_at(target_seat, slot) for slot in slots]
    divided = getattr(action, "divided_targets", None)
    if divided:
        bound["divided"] = [
            game.permanent_at(entry[0], entry[1]) if entry[1] is not None else None
            for entry in divided
        ]
    modes = getattr(action, "mode_choices", None)
    if modes:
        bound["modes"] = [
            game.permanent_at(
                choice.get("target_player_index"), choice.get("target_permanent_index")
            )
            if choice.get("target_permanent_index") is not None else None
            for choice in modes
        ]
    if getattr(action, "permanent_index", None) is not None:
        source_seat = getattr(action, "source_controller_index", None)
        bound["source"] = game.permanent_at(
            seat if source_seat is None else source_seat, action.permanent_index
        )
    return bound


def _rebound_action(game: Game, action, bound: dict):
    """*action* with every slot `_bind_action_slots` took read back off the
    battlefield as it stands now.

    A permanent that has left has no slot: a single target reads None (the
    announcement names no object and the engine's own gate answers), and it is
    dropped from a list. The plan never spends a permanent the action names
    (`choose_cast_action`), so that is the engine's answer to a board something
    else moved rather than a path this policy takes.
    """
    changes: dict = {}
    if "target" in bound:
        changes["target_permanent_index"] = game.battlefield_index_of(bound["target"])
    if "targets" in bound:
        changes["target_permanent_index"] = [
            slot for slot in (
                game.battlefield_index_of(permanent) for permanent in bound["targets"]
            )
            if slot is not None
        ]
    if "divided" in bound:
        changes["divided_targets"] = [
            entry if permanent is None
            else (entry[0], game.battlefield_index_of(permanent), *entry[2:])
            for entry, permanent in zip(action.divided_targets, bound["divided"])
        ]
    if "modes" in bound:
        changes["mode_choices"] = [
            choice if permanent is None
            else {**choice, "target_permanent_index": game.battlefield_index_of(permanent)}
            for choice, permanent in zip(action.mode_choices, bound["modes"])
        ]
    if "source" in bound:
        slot = game.battlefield_index_of(bound["source"])
        if slot is not None:
            changes["permanent_index"] = slot
    return replace(action, **changes) if changes else action


@dataclass(frozen=True)
class _PricedManaSource:
    """A mana ability that costs mana, as the payment plan counts it — see
    `_priced_mana_source`."""

    #: Which of the permanent's usable abilities.
    ability_index: int
    #: The generic mana one activation costs, beside the tap.
    price: int
    #: Every symbol one activation may be asked for, the unasked one first.
    symbols: tuple[str, ...]
    #: How many mana of the asked symbol.
    amount: int
    #: A fixed run of different symbols ("{U}{B}"), or None.
    run: "dict[str, int] | None" = None

    def outputs(self) -> "list[tuple[str, dict[str, int]]]":
        """``(symbol to ask for, what that activation adds)``, one per answer."""
        if self.run is not None:
            return [(self.symbols[0], dict(self.run))]
        return [(symbol, {symbol: self.amount}) for symbol in self.symbols]


def _priced_mana_source(
    game: Game, seat: int, permanent: "Permanent | None"
) -> "_PricedManaSource | None":
    """The mana ability of a permanent *seat* controls whose cost is **generic
    mana and {T}** and which is the only mana that permanent makes — or None.

    "{1}, {T}: Add {U}{B}." (Darkwater Catacombs and the other four Odyssey
    filter lands), "{1}, {T}: Add one mana of any color." (Mana Cylix,
    Helionaut), "{2}, {T}: …" (Celestial Prism). **A land of this kind was a
    land that made nothing for an AI seat**: the tap seam runs only an ability
    whose whole cost is {T} (`land_mana_tap_refusal` answers
    ``priced_mana_ability``), so the planner left it out and the seat counted
    one land fewer than it controlled — ten filter lands were played in a
    ten-game seeded Odyssey run and not one was ever activated (W1G2 saw the
    same in six).

    The cheap half of ROADMAP's "costed and sacrifice mana sources": a price
    paid in mana renumbers nothing, where a sacrifice during payment moves the
    battlefield under an announcement made by index. What it needs instead is
    an *input* — a unit of mana from another source, in the pool before this
    one is activated — which is `_plan_through_a_priced_source`'s to arrange.

    Narrow on purpose, each clause a shape this cannot plan:

    * **only generic mana in the price** — "{G}, {T}: Add {R}." (Fire Sprites)
      needs a coloured input, a second matching problem;
    * **only with {T}** — "{1}: Add {B}." (Bog Initiate) may be activated any
      number of times, and how many is a search, not a tap;
    * **no other mana ability on the permanent** — a land that also taps for
      mana on its own (the Homelands tri-lands, Crystal Quarry) is already the
      free planner's, and one slot in a plan cannot say which ability it means;
    * **a yield the payload states** (`ai_valuation.planned_mana_yield`), with
      no rider.

    And only one the activation path will accept, by the gates
    `_nonland_mana_source` asks: untapped, not a summoning-sick creature, not
    under a ban or a permission that closes it to this seat.
    """
    import dataclasses

    from .activation_restrictions import prints_activation_restriction
    from .mana_payment import carries_an_offer
    from .mana_payment import is_mana_ability as is_cr_mana_ability
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .spell_prohibitions import permanent_activations_forbidden

    if permanent is None or permanent.tapped:
        return None
    if game.land_mana_tap_refusal(permanent) not in (
        "priced_mana_ability", "not_an_untapped_land",
    ):
        # A land the seam taps (None), or one it refuses for a reason that is
        # not about the price: summoning sick, forbidden, stripped.
        return None
    if game._is_summoning_sick(permanent):
        return None
    usable = game.usable_abilities_of(permanent)
    found: "_PricedManaSource | None" = None
    for index, ability in enumerate(usable):
        if is_tap_alone_mana_ability(ability):
            return None
        if not is_cr_mana_ability(ability):
            continue
        if found is not None:
            # Two priced mana abilities: which one a plan's slot means is not
            # something a slot can say.
            return None
        cost = ability.cost
        mana = {symbol: int(amount or 0) for symbol, amount in cost.mana.items()}
        generic = mana.get("generic", 0)
        if generic < 1 or any(amount for symbol, amount in mana.items() if symbol != "generic"):
            return None
        if cost != dataclasses.replace(
            type(cost)(mana={symbol: 0 for symbol in cost.mana}),
            requires_tap=True, mana=cost.mana,
        ):
            return None
        line = ability.source_line or ""
        if prints_activation_restriction(line) or carries_an_offer(ability.instruction):
            return None
        produced = planned_mana_yield(ability.instruction)
        if produced is None or produced.board_narrowed or produced.from_chosen_color:
            return None
        if not produced.symbols:
            return None
        if (
            permanent_activations_forbidden(game, permanent)
            or global_activation_ban(game, permanent) is not None
            or activation_denial(game, seat, permanent, line)
            or activation_permission_denial(game, seat, permanent, line)
            or aura_restriction_active(permanent, "all_activated_abilities_shut_off")
        ):
            return None
        found = _PricedManaSource(
            ability_index=index,
            price=generic,
            symbols=produced.symbols,
            amount=produced.amount,
            run=dict(produced.run) if produced.run else None,
        )
    return found


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
    #: Whether the activation **sacrifices the source** ("{T}, Sacrifice this
    #: artifact: Add three mana of any one color"). Mana a plan may count only
    #: under `_may_sacrifice_for` — see `_nonland_mana_source`.
    sacrifices: bool = False


def _sacrifices_only_itself(cost) -> bool:
    """Whether *cost* is "Sacrifice this permanent", with or without {T}, and
    **nothing else** — no mana, no card, no counter, no life, no other
    permanent.

    Compared against a default cost rather than by listing what must be empty,
    for `turn_management._is_free_beyond_tapping`'s reason: a list would start
    ignoring any cost component added later, and ignoring one here is the AI
    paying a price it never weighed.
    """
    empty = type(cost)(mana={symbol: 0 for symbol in cost.mana})
    return bool(cost.sacrifice_self) and replace(cost, requires_tap=False) == replace(
        empty, sacrifice_self=True
    )


def _nonland_mana_source(
    game: Game, seat: int, permanent: "Permanent | None", *, may_sacrifice: bool = False,
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

    **An ability whose whole cost is {T}** (`is_tap_alone_mana_ability`, the
    tap seam's own predicate — which also excludes a printed "Activate only …"
    and an ability that asks another player something) is the free mana, and
    the only kind this answers with unless asked for more.

    ***may_sacrifice* asks for the other kind the plan can price: a source
    that pays by sacrificing itself** — "{T}, Sacrifice this artifact: Add
    three mana of any one color" (Black Lotus, Lotus Petal), "Sacrifice this
    creature: Add {B}" (Blood Pet, Basal Thrull, Tinder Wall, Morgue Toad).
    Returned with ``sacrifices`` set, and never for a permanent that also has a
    free mana ability: Eye of Ramos' "Sacrifice this artifact: Add {U}" beside
    its "{T}: Add {U}" would trade a mana every turn for one mana now. Whether
    a plan may *count* one is `_may_sacrifice_for`'s question, not this
    function's — this says what the ability is. An untapped permanent is asked
    for only where the ability taps ({T} in the cost is CR 302.6's as well),
    so a tapped or summoning-sick Blood Pet is still a mana.

    Everything else stays out, and that is the stated limit of what the AI
    will give up for mana: **never another permanent** ("Sacrifice a
    creature", Ashnod's Altar, Phyrexian Altar; "Sacrifice a land", Squandered
    Resources), **never a card** (Bog Witch, Skirge Familiar, Lion's Eye
    Diamond's whole hand, Cadaverous Bloom), **never a counter or life** (the
    Mana Batteries, Iceberg, Phyrexian Lens) — each is a choice of *which* or
    *how many* that this plan has no valuation for. A source that costs mana
    to make mana ("{1}, {T}: Add one mana of any color", Mana Cylix; the
    Odyssey filter lands) is not this function's either: it is counted apart,
    as a last resort and behind the tap that pays for it
    (`_priced_mana_source`), and one that also sacrifices itself ("{1},
    Sacrifice this creature: Add {U}{B}{R}", the Attendants) stays out.

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
    from .activation_restrictions import prints_activation_restriction
    from .mana_could_produce import ability_colors_on_offer
    from .mana_payment import carries_an_offer
    from .mixins.turn_management import is_tap_alone_mana_ability
    from .spell_prohibitions import permanent_activations_forbidden

    if permanent is None:
        return None
    if permanent.has_type("land") or (
        not permanent.tapped
        and game.land_mana_tap_refusal(permanent) != "not_an_untapped_land"
    ):
        # A land (the seam's own reading of which permanents are its) — the
        # land half of the plan answers for it, whatever it answers.
        return None
    # The permanent's own list: a Sol Ring under Titania's Song has lost its
    # mana ability, and planning its mana planned a cast the pool cannot pay.
    usable = game.usable_abilities_of(permanent)
    taps_alone = any(is_tap_alone_mana_ability(ability) for ability in usable)
    if not taps_alone and not may_sacrifice:
        return None
    ready = not permanent.tapped and not game._is_summoning_sick(permanent)
    for index, ability in enumerate(usable):
        if taps_alone:
            if not ready:
                return None
            if not is_tap_alone_mana_ability(ability):
                continue
        else:
            # A source that pays by leaving. Asked only of a permanent with no
            # free mana ability, and held to the two things the tap seam's
            # predicate holds a free one to.
            if ability.instruction is None or not _sacrifices_only_itself(ability.cost):
                continue
            if ability.cost.requires_tap and not ready:
                continue
            if prints_activation_restriction(
                ability.source_line or ""
            ) or carries_an_offer(ability.instruction):
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
            sacrifices=not taps_alone,
        )
    return None


@dataclass(frozen=True)
class _PaymentContext:
    """What the payment plan being drawn up is **for**, where its caller knows.

    A context variable rather than a parameter, for `_OFFERS_ANNOUNCED`'s
    reason: `_plan_land_taps` is reached through the cast candidates'
    builders, which take a card and a board and know nothing of where the card
    is or what its cast will be charged. Set around the one call that builds a
    candidate (`choose_cast_action`); None is every other plan — an ability's
    cost, a toll, an instant in combat — and reads exactly as plans always
    did.
    """

    #: The spell being cast. What a "spend this mana only to cast …" land's
    #: mana may pay for (CR 106.6), and what a permanent given up for mana is
    #: weighed against (`_may_sacrifice_for`). What the cast is *charged* is
    #: not here: a waiver or a flashback cost is the permission's
    #: (`ai_valuation.casting_under`), read by `_cost_for`.
    spell: "CardDefinition | None" = None


_PAYING_FOR: ContextVar["_PaymentContext | None"] = ContextVar(
    "ai_paying_for", default=None
)


@contextmanager
def _paying_for(spell: "CardDefinition | None"):
    """Run a block in which every plan drawn up is the payment for *spell*."""
    token = _PAYING_FOR.set(_PaymentContext(spell=spell))
    try:
        yield
    finally:
        _PAYING_FOR.reset(token)


def _may_sacrifice_for(spell: "CardDefinition | None", permanent: Permanent) -> bool:
    """Whether a plan paying for *spell* may count mana *permanent* makes by
    being sacrificed.

    **What the AI will give up for mana, stated once.** Only to cast a spell —
    never to activate an ability, pay a toll or keep a permanent, where the
    plan is told of no spell and this answers no. And only for a spell **worth
    more than the permanent, measured in mana value** (CR 202.3): Black Lotus
    and Lotus Petal (0) for anything that costs; Blood Pet and Tinder Wall (1)
    for a two-drop or better; Basal Thrull (2) for a three-drop; never a
    creature for a spell no bigger than itself. Which *kinds* of source are
    asked at all is `_nonland_mana_source`'s half (itself, and nothing with a
    free mana ability); that they are reached for last, and as few as pay, is
    `_plan_land_taps`'.
    """
    if spell is None or spell.primary_type == "land":
        return False
    return float(permanent.effective_card.cmc or 0) < float(spell.cmc or 0)


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

#: What a cast under a permission that **ends** is worth over the same cast
#: from hand ("until end of turn, you may play that card": an Elkin Bottle's
#: card, a graveyard under Yawgmoth's Will). The same net card, for the mirror
#: reason: a hand card not cast this turn is still in hand next turn, and this
#: one is not castable at all — so it goes first. **Not** given to a permission
#: that lasts as long as the card stays put (flashback, CR 702.34a; Yawgmoth's
#: Agenda): that cast will be there next turn, and it competes with the hand
#: on what the spell does — a seat with five lands should not flash a Firebolt
#: back for {4}{R} while it holds a five-drop. A tie between the two goes to
#: the hand (`_is_better_cast`).
EXPIRING_PERMISSION_BONUS = COMMAND_ZONE_CAST_BONUS


def _zone_seat(player_index: int, under: "PermittedCast | None") -> "int | None":
    """`CastAction.zone_seat` for a cast made under *under*: the pile's owner
    when that is not the caster (Grinning Totem), None otherwise."""
    if under is None or under.owner_seat == player_index:
        return None
    return under.owner_seat


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


def zone_being_cast_from(game: Game, seat: int, action: "CastAction") -> list:
    """The pile ``action.hand_index`` indexes: *seat*'s hand for an ordinary
    cast, and otherwise whatever ``action.from_zone`` names — the command zone
    (CR 903.8), or a graveyard, an exile or a library an effect has opened
    (CR 601.3), which is the caster's own unless ``action.zone_seat`` says
    whose.

    **The one place an executor finds the card a `CastAction` proposes**, for
    `cast_announcement`'s reason. Each of the five executors picked the zone
    for itself — "the command zone for a commander cast, the hand for
    everything else" — so a cast proposed from a graveyard would have been
    read off the *hand* at the graveyard's index and cast as whatever card sat
    there.
    """
    player = game.players[seat if action.zone_seat is None else action.zone_seat]
    if action.from_zone == "command":
        return player.command_zone
    if action.from_zone in ("graveyard", "exile", "library"):
        return getattr(player, action.from_zone)
    return player.hand


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    """The cast this seat makes now, out of everything it may cast — its hand,
    its commander, and whatever an effect has opened to it — or None.

    **One deliberation for the whole decision** (``ai_valuation.deliberating``).
    Every card weighed here is weighed against the same table with nothing
    cast, and reading that table costs a copy of the game run out to the end of
    its turn; each card took its own (`_cast_candidate`), so a hand of seven
    read the one table seven times. Nothing is decided differently: the reading
    is a function of the game, which no chooser moves, and a rehearsal is kept
    under everything that tells two of them apart (`_rehearse_announcement`).
    """
    with deliberating():
        return _choose_cast_action(game, player_index)


def _choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    """`choose_cast_action`, inside its deliberation."""
    best: CastAction | None = None
    for hand_index, card in hand_spells(game.players[player_index]):
        # The plan is told what it pays for (`_paying_for`): the spell, which
        # is what a permanent given up for mana is weighed against and what
        # restricted mana may be spent on. Whether an effect has made the cast
        # free (Aluren) is the waiver the candidate is weighed under
        # (`ai_valuation.hand_waiver`).
        candidate = _priced_candidate(game, player_index, card, hand_index)
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    # CR 601.3: the casts an *effect* allows from outside the hand — a
    # flashback card in the seat's graveyard (CR 702.34a), a graveyard opened
    # by Yawgmoth's Will or Yawgmoth's Agenda, a card an Elkin Bottle exiled,
    # the top of a library under a Temporal Aperture. **No AI seat had ever
    # made one**: this loop walked the hand and the command zone, so the
    # second half of every flashback card was text no simulated game and no AI
    # opponent reached (W1G3: 61 hand casts of eight pinned flashback cards
    # over eighteen games, none from a graveyard). The list is the engine's
    # (`ai_valuation.permitted_casts`, over the seam the browser's zone badges
    # read), each entry is built by the same candidate builder a hand card is
    # — the same gates, the same target, mode and division choosers — and what
    # differs is carried by the entry: where the card is and what the cast is
    # charged.
    for permitted in permitted_casts(game, player_index):
        candidate = _priced_candidate(
            game, player_index, permitted.spell, permitted.index,
            from_zone=permitted.zone, under=permitted,
        )
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    # CR 903.8: the seat's commander is castable from the command zone, and an
    # AI seat that never read that zone sat its commander there for the whole
    # game. Which casts are on offer is `ai_valuation.castable_commanders` —
    # the engine's own seam, empty outside a Commander game — and the tax
    # arrives as extra generic in the cost, the same way the cast path charges
    # it, so affordability is judged against what will actually be paid.
    for zone_index, card, tax in castable_commanders(game, player_index):
        candidate = _priced_candidate(
            game, player_index, card, zone_index,
            from_zone="command", extra_generic=tax,
        )
        if candidate is not None and _is_better_cast(candidate, best):
            best = candidate

    return best


def _priced_candidate(
    game: Game, seat: int, spell: CardDefinition, zone_index: int, *,
    from_zone: str = "hand", extra_generic: int = 0,
    under: "PermittedCast | None" = None,
) -> "CastAction | None":
    """`_cast_candidate` with the plan told what it pays for (`_paying_for`),
    or None where the payment would spend a permanent the cast names."""
    with _paying_for(spell):
        candidate = _cast_candidate(
            game, seat, spell, zone_index, from_zone=from_zone,
            extra_generic=extra_generic, under=under,
        )
    if candidate is None or _plan_spends_what_it_names(game, seat, candidate):
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
    best_value: tuple[int, ...] | None = None
    for hand_index, card in enumerate(game.players[player_index].hand):
        if card.primary_type != "land":
            continue
        if entry_sacrifice_is_unavoidable(game, player_index, card):
            continue
        candidate = _cast_candidate(game, player_index, card, hand_index)
        if candidate is None:
            continue
        value = (*_land_drop_value(game, player_index, card), 0)
        if best_value is None or value > best_value:
            best, best_value = candidate, value
    # CR 305.1 from outside the hand: "you may **play** that card" (an Elkin
    # Bottle's land), "you may play lands … from your graveyard" (Yawgmoth's
    # Will, Yawgmoth's Agenda). After the hand and only strictly better, so a
    # seat with no such permission drops exactly the land it always did. The
    # last term breaks a tie toward a land whose permission **ends**
    # (`PermittedCast.expires`): the hand's land is still there next turn and
    # the Bottle's is not.
    for permitted in permitted_casts(game, player_index):
        card = permitted.spell
        if card.primary_type != "land":
            continue
        if entry_sacrifice_is_unavoidable(game, player_index, card):
            continue
        candidate = _cast_candidate(
            game, player_index, card, permitted.index,
            from_zone=permitted.zone, under=permitted,
        )
        if candidate is None:
            continue
        value = (
            *_land_drop_value(game, player_index, card),
            1 if permitted.expires else 0,
        )
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


def _announced_mode(card: CardDefinition) -> int | None:
    """CR 601.2b's *mode* answer for the candidate being built: the mode
    *card* is being weighed in, or None for a spell that names none.

    The mode's twin of `_OFFERS_ANNOUNCED`, and it lives one module down
    (`ai_valuation.considering_mode`) because the valuation readers there need
    it too. **Every engine question a cast chooser asks about a spell takes
    this beside the offers** — the spec, the picker's list, the
    no-legal-target gate, the steps the announcement will run — and
    `tests/ai/test_ai_mode_chooser.py` fails a call in this module that asks
    one of them without it, so a chooser added later cannot read mode 0 by
    leaving a keyword out.
    """
    return mode_considered(card)


def _announced_steps(card: CardDefinition, program) -> tuple:
    """The steps the candidate being built will resolve: the weighed mode's
    for a modal spell (`_announced_mode`), *program*'s own otherwise.

    For the choosers that walk instructions rather than ask for a spec.
    ``program.instructions`` is mode 0's for a modal card, which is what each
    of them read.
    """
    return announced_mode_instructions(program, _announced_mode(card))


def _cast_zone(card: CardDefinition) -> str:
    """The zone the candidate being built would be cast from: "hand", or the
    zone of the permission *card* is being weighed under
    (`ai_valuation.casting_under`).

    The zone's twin of `_announced_mode`, and held to the same rule by
    `tests/ai/test_ai_zone_casts.py`: **every engine question a cast chooser
    asks that takes a ``from_zone`` is passed this one.** A spell cast out of a
    graveyard is not a card in that graveyard by the time its targets are
    chosen (CR 601.2a), so a Morgue Theft weighed from the graveyard with the
    hand's spec would count itself as the creature card it may return; a
    prohibition may bind one zone; an additional cost may be printed for one.
    """
    weighed = cast_weighed(card)
    return "hand" if weighed is None else weighed.zone


def _cast_spec(card: CardDefinition, program):
    """`derive_cast_spec` for the candidate being built (see
    `_OFFERS_ANNOUNCED`, `_announced_mode` and `_cast_zone`)."""
    return derive_cast_spec(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
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
        if other.primary_type == "land" or cast_announces_x(other, from_zone="hand"):
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


#: What an instant or sorcery scores before anything it does is counted. The
#: sum the old weights made of "a card" (1.5) and "a spell" (2.0).
SPELL_BASE_SCORE = 3.5
#: The most a measured swing moves a score either way: a cast that wins the
#: game outranks everything, and by a number that still adds and compares.
SWING_CAP = 60.0
#: A cast measured to leave its caster this much worse off is not proposed:
#: half a life. Not zero, so that a measure a hair under nothing (a point of
#: power lent to an opposing blocker for a turn) does not hold a card for
#: ever; and no lower, because the casts between here and a life and a half
#: were all the same cast — a sweep or a shrink landing on the caster alone.
HARM_FLOOR = -0.5
#: How many distinct targets one cast is rehearsed at. A rehearsal is a cast,
#: and a board of forty permanents is not forty questions worth asking.
TARGETS_WEIGHED = 8


#: The mana of each kind a rehearsed cast is lent to pay for itself: more
#: than any spell in the pool can ask for at any X the planner sizes.
_REHEARSAL_MANA = 40

#: Set while a card is being weighed **in the abstract** — what is this one
#: worth to hold — rather than as a cast to make now (`_score_tutor_choice`).
#: The question is asked by a search part-way through its own resolution, a
#: moment no cast can be rehearsed in, and it is not about that moment: the
#: rehearsal runs on a copy that owes nothing (``ai_valuation.rehearse``'s
#: ``detach="abstract"``).
_IN_THE_ABSTRACT: ContextVar[bool] = ContextVar("ai_in_the_abstract", default=False)


#: Set by `_cast_candidate_announcing` when the candidate it was building
#: was dropped because nothing the cast does outlasts the turn
#: (``Rehearsal.fleeting``) — for `_cast_candidate_offering`, which has other
#: announcements of the same spell still to try and need not try them.
_HELD_AS_FLEETING: ContextVar[bool] = ContextVar("ai_held_as_fleeting", default=False)

#: Set by `_cast_candidate_sized` while it builds a candidate at one size of
#: an X paid in life: the X `_pick_x_value` announces in place of the largest
#: the seat's reserve allows.
_LIFE_X_ASKED: ContextVar["tuple | None"] = ContextVar("ai_life_x_asked", default=None)


def _held_as(player, card: CardDefinition) -> "CardDefinition | None":
    """The card in *player*'s hand that *card* is a spell of — itself, or the
    split card it is one half of (CR 709.3) — or None when the hand holds no
    such card."""
    return next(
        (
            held for held in player.hand
            for face in castable_faces(held)
            if face is card or face == card
        ),
        None,
    )


def _announcement(
    card: CardDefinition,
    *,
    target: int,
    caster: int,
    permanent_index: "int | list[int] | None" = None,
    permanent_ids: "list[int] | None" = None,
    x_value: int | None = None,
) -> dict:
    """What a cast of the candidate being built announces when it names
    *target* (and the permanent given), in `cast_announcement`'s own shape —
    so a rehearsal of a half-built candidate and of the finished `CastAction`
    are one question asked once.

    **Out of the zone being weighed** (`ai_valuation.cast_weighed`), and
    under the permission that opens it, as the finished cast is made: a
    target chosen for a flashback card was rehearsed as the same card put in
    the hand and cast from there, which arrives in a graveyard it never left
    — a change every time — so its targets were weighed by a different
    reading from the one its cast then got (``_rehearse_announcement``'s
    *spell_zone*)."""
    offers = _OFFERS_ANNOUNCED.get()
    under = cast_weighed(card)
    return cast_announcement(CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=(),
        score=0.0,
        hand_index=0,
        target_permanent_index=permanent_index,
        target_permanent_ids=permanent_ids,
        optional_cost_payments=(
            dict(offers) if _announces_any_offer(card, offers) else None
        ),
        mode_index=_announced_mode(card),
        from_zone=_cast_zone(card),
        zone_seat=_zone_seat(caster, under),
        alternative_cost=under is not None and under.alternative_cost,
    ))


def _rehearse_announcement(
    game: Game, seat: int, card: CardDefinition, announcement: dict,
    *, planned: "CastAction | None" = None, through_combat: bool = False,
) -> Rehearsal | None:
    """What casting *card* with *announcement* would do, carried out on a
    scratch copy of the game (``ai_valuation.rehearse``) — or None when no
    rehearsal can be run.

    The cast is the executors' own: ``queue_from_hand`` with the keywords
    `cast_announcement` produces, and the copy then resolves it. A card the
    seat does not hold (a chooser asked about a spell in the abstract) is put
    in the copy's hand first, and then its leaving is not a card the cast
    cost.

    **The mana is the executors' too, once there is a plan.** *planned* is
    the finished `CastAction`: its lands are tapped on the copy for the
    colours it planned (`tap_planned_lands`) and the cast pays out of them,
    which is every executor's two lines — so what the caster has left to
    spend while the spell resolves is what it will really have left. Chain
    Stasis is the card that notices: its copies are paid for one after
    another until the mana runs out, and one mana more is a creature left
    tapped instead of untapped.

    Before there is a plan — a target is weighed before any land is — the
    spell's own mana is **lent**: the copy's caster is handed a pool to pay
    out of and has it taken back the moment the spell is on the stack.
    Either way mana stays enforced for everything the resolution then asks
    anyone to pay.

    *through_combat* runs the turn out with its combat fought, on the cast
    and on the table it is compared with (``ai_valuation.rehearse``) — the
    second reading `_weighed_through_the_fight` asks for.
    """
    if rehearsing():
        return None
    from_hand = announcement.get("from_zone", "hand") == "hand"
    in_hand = _held_as(game.players[seat], card) if from_hand else None
    held = not from_hand or in_hand is not None
    # The name the card goes by in a hand and a graveyard, which for a half
    # of a split card is the whole card's (CR 709.4).
    zone_name = in_hand.name if in_hand is not None else card.name

    def perform(table):
        player = table.players[seat]
        if not held:
            table.put_card_into_hand(player, card)
        if planned is not None:
            tap_planned_lands(table, seat, planned)
            return table.queue_from_hand(seat, card.name, **announcement)
        floating = dict(player.mana_pool)
        for symbol in _MANA_SYMBOLS:
            player.mana_pool[symbol] = int(floating.get(symbol, 0) or 0) + _REHEARSAL_MANA
        try:
            return table.queue_from_hand(seat, card.name, **announcement)
        finally:
            player.mana_pool.clear()
            player.mana_pool.update(floating)

    def paid_for(table, _carried) -> None:
        # The table the planned cast is compared with: the same lands
        # tapped, and the mana they made let go — so a tapped land, and
        # whatever tapping it set off, is on both sides and is not read as
        # something the spell did.
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, planned)
        pool.clear()
        pool.update(floating)

    taps = planned is not None and bool(planned.land_tap_indices)
    return rehearse(
        game, seat, perform, spell_name=zone_name,
        leaves_hand=from_hand and held,
        # Cast out of a zone a permission opens (CR 601.3): its trip out of
        # that zone is the cast's own, as a hand card's is.
        spell_zone=None if from_hand else announcement.get("from_zone"),
        # ...in the pile's owner's zones (the permission being weighed says
        # whose; an announcement does not carry it).
        spell_seat=(
            None if from_hand or cast_weighed(card) is None
            else cast_weighed(card).owner_seat
        ),
        # Everything that tells two rehearsals of one decision apart: the
        # announcement, and — once there is one — the plan that pays for it.
        # One card priced twice (a free cast that takes a kicker is priced
        # again as an ordinary one, `_priced_candidate`) announces the same
        # thing over two different payments, and the lands left untapped are
        # part of what the resolution has to spend.
        key=(
            seat, card.name, held,
            (planned.land_tap_indices, planned.land_tap_colors)
            if planned is not None else None,
            repr(sorted(announcement.items())), through_combat,
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", planned.land_tap_indices, planned.land_tap_colors)
            if taps else None
        ),
        detach="abstract" if _IN_THE_ABSTRACT.get() else False,
        through_combat=through_combat,
    )


def _names_an_unweighed_seat(
    game: Game, seat: int, card: CardDefinition
) -> bool:
    """Whether a cast nobody could rehearse would name a player out of
    several with nothing having weighed which.

    "Target player discards two cards" has no side to read off its program:
    which player is `_choose_target_for_spell`'s rehearsal of each seat, and
    with no rehearsal to be had (the table is part-way through a resolution;
    the copy raised) every seat scores alike and the tie is the caster's.
    Such a cast is held for a moment it can be measured in. A spell that
    names an object, or nobody, is aimed by what its program says and is
    proposed unmeasured, as it always was.
    """
    return len(_seats_the_cast_may_name(game, seat, card)) > 1


def _worth_proposing(rehearsal: Rehearsal | None) -> bool:
    """Whether a rehearsed cast is one to propose: the engine took it, it
    changed something **that outlasts the turn**, and it did not leave its
    caster plainly worse off.

    A cast whose every trace is gone by the end of the turn
    (``Rehearsal.fleeting``) changed something and bought nothing: a pump on
    a creature that then did not fight, a shield nothing came for, a Fog in
    its caster's own main phase with no attack to stop — each was proposed,
    at ``SPELL_BASE_SCORE``, and cast whenever nothing scored higher. Mana is
    the exception (``made_mana``): it is gone by the end of the turn *because
    it is spent*, on a cast this rehearsal is not a rehearsal of — and so is
    a cast it opens (``opened_a_cast``: Yawgmoth's Will, Recoup).

    A cast nobody could rehearse (None) is proposed as it always was.
    """
    if rehearsal is None:
        return True
    if not (rehearsal.accepted and rehearsal.changed):
        return False
    if _leaves_nothing(rehearsal):
        return False
    return rehearsal.swing >= HARM_FLOOR


def _weighed_through_the_fight(
    game: Game, seat: int, card: CardDefinition, announcement: dict,
    rehearsal: Rehearsal | None, *, planned: "CastAction | None" = None,
) -> Rehearsal | None:
    """*rehearsal* — of casting *card* with *announcement* (paid for as
    *planned*, once there is a plan), a cast made before the turn's combat —
    read again **with that combat fought**, where the first reading cannot
    price it; otherwise *rehearsal* as it is.

    A rehearsal runs its copy to the end of the turn with nothing declared on
    the way, so what a precombat cast does *to the fight* is not in it: a
    Giant Growth is a quarter of a +3/+3 whether the creature then attacks
    for three more or stays home, Hatred is the life it cost, and a Fog in
    its caster's own main phase — which stops the caster's own attack — is a
    cast that harmed nobody. The second reading plays the attack, the blocks
    and the damage on both copies (``ai_valuation.rehearse``'s
    *through_combat*) and what it measures is what is left when the turn is
    over: the damage that got through, the creature that died or did not.

    Asked only where it can change the answer, because it is a whole combat
    on two copies: the seat's own precombat main phase
    (``Rehearsal.combat_ahead``: or a postcombat one in which the cast adds
    a combat), and a cast some of whose good is gone by
    the end of the turn — all of it (``fleeting``), or more of it than is
    left (``now`` above ``lasting``). A removal spell, a draw, a discard are
    priced by what they leave and are not asked twice.

    Asked by the cast being built and by the choosers that pick its target
    (`_best_target`, `_better_than_the_seat`), because which creature a
    shield or a pump goes on is a question about the fight too: "prevent the
    next 3 damage that would be dealt to any target this turn" on the 2/2
    about to trade is a creature saved, and on its controller is nothing.
    """
    if (
        rehearsal is None
        or not rehearsal.accepted
        or not rehearsal.changed
        or rehearsal.through_combat
        # A fight still to come once the cast has resolved — the turn's own,
        # or one the cast added (CR 500.8: Relentless Assault).
        or not rehearsal.combat_ahead
    ):
        return rehearsal
    if not priced_by_the_fight(rehearsal.now, rehearsal.lasting, rehearsal.fleeting):
        return rehearsal
    if (rehearsal.made_mana or rehearsal.opened_a_cast) and not priced_by_the_fight(
        rehearsal.now, rehearsal.lasting, False,
    ):
        # A ritual: what it left is mana, and no fight spends it. One that
        # also lends something for the turn — "gain control of target
        # creature until end of turn … add two mana" (Traitorous Greed) — is
        # the creature it attacks with, and is read with the fight.
        return rehearsal
    if not has_a_creature_to_fight_with(game, seat):
        # Nothing to attack with: the fight is the turn as already read.
        return rehearsal
    fought = _rehearse_announcement(
        game, seat, card, announcement, planned=planned, through_combat=True,
    )
    return rehearsal if fought is None else fought


def _leaves_nothing(rehearsal: Rehearsal) -> bool:
    """Whether a rehearsed cast that changed something left none of it by the
    end of the turn — mana aside, which is gone because it is spent, and a
    cast it opened, for the same reason (`_worth_proposing`'s reading, for a
    chooser comparing targets)."""
    return (
        rehearsal.fleeting and not rehearsal.made_mana
        and not rehearsal.opened_a_cast
    )


def choose_trigger_mode(game: Game, choice, stated: int) -> int:
    """Which offered mode of a **modal triggered ability** a seat nobody asks
    takes (CR 700.2b): the one measured to do most, or *stated* — the
    registry's standing answer, the first mode that is not a price — when
    nothing measures more than it or no rehearsal can be run.

    The valuation the cast chooser weighs a spell's bullets with, asked of a
    trigger's: each offered mode is answered on a scratch copy of the game
    (``Game._resolve_mode_choice``, which records the mode and its default
    target on the ability), the ability resolves there, and the swings are
    compared (``ai_valuation.rehearse``). So Trufflesnout takes four life at
    three life and the counter at twenty, and Elder Gargaroth draws when a
    Beast is worth less to it than a card — where each took its first bullet
    whatever the board.

    The choice is made as the ability goes on the stack (CR 603.3c), which
    for an entry trigger is while the permanent's own spell is still
    resolving; the copy is cut loose from that (``detach``) and carries out
    the ability alone. "Nothing done" is the ability taken off the stack,
    which is what CR 700.2b does to one with no mode chosen.
    """
    item = choice.data.get("_trigger_item")
    options = tuple(choice.data.get("_options") or ())
    if item is None or len(options) < 2 or rehearsing():
        return stated

    def without(table, prompt) -> None:
        ability = prompt.data.get("_trigger_item")
        table.stack = [queued for queued in table.stack if queued is not ability]

    class _Answered:
        def __init__(self, supported: bool) -> None:
            self.supported = supported
            self.details = "" if supported else "the mode could not be chosen"

    best, best_swing = stated, None
    with deliberating():
        order = [stated, *(index for index in range(len(options)) if index != stated)]
        for index in order:
            rehearsal = rehearse(
                game, choice.player_index,
                lambda table, prompt, index=index: _Answered(
                    bool(table._resolve_mode_choice(prompt, index))
                ),
                leaves_hand=False, carried=choice, detach=True, without=without,
                label=(
                    f"{getattr(getattr(item, 'card', None), 'name', None) or 'a trigger'}"
                    f" (its triggered ability's mode {index})"
                ),
            )
            if rehearsal is None:
                return stated
            if not rehearsal.accepted:
                continue
            if best_swing is None or rehearsal.swing > best_swing + 1e-9:
                best, best_swing = index, rehearsal.swing
    return best


def _cast_candidate(
    game: Game,
    player_index: int,
    card: CardDefinition,
    hand_index: int,
    *,
    from_zone: str = "hand",
    extra_generic: int = 0,
    under: "PermittedCast | None" = None,
) -> CastAction | None:
    """`_cast_candidate_in_each_mode` inside one deliberation: every mode,
    offer and target of *card* this decision weighs is measured against one
    reading of the table with nothing cast (``ai_valuation.deliberating``)."""
    with deliberating():
        return _cast_candidate_in_each_mode(
            game, player_index, card, hand_index,
            from_zone=from_zone, extra_generic=extra_generic, under=under,
        )


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
    allows it (CR 601.3, `ai_valuation.permitted_casts`): where the card is,
    and what the cast is charged — a flashback cost (CR 702.34a), nothing, or
    the card's own mana cost. None for the hand and the command zone, whose
    permission is a rule; a **hand** cast is still asked whether a waiver
    covers it (`ai_valuation.hand_waiver`: Aluren), because the cast path
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
    if under is None and from_zone == "hand":
        hand = game.players[player_index].hand
        if 0 <= hand_index < len(hand):
            under = hand_waiver(game, player_index, hand[hand_index], card, hand_index)
    best: CastAction | None = None
    built: list[CastAction] = []
    for mode_index in _modes_weighed(game, player_index, card):
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
        return _every_mode_worth_casting(built, best) or best
    return best


#: What each further mode of a "choose one or more" spell adds to the score of
#: the best one. Tuning: the modes share one cost, so every one after the first
#: is an effect for no mana — worth having, and never worth more than a spell.
EXTRA_MODE_SCORE = 1.0


def _every_mode_worth_casting(
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
        slot = candidate.target_permanent_index
        if slot is not None and not isinstance(slot, int):
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
            "target_permanent_index": slot,
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


def _pays_x_in_life(card: CardDefinition) -> bool:
    """Whether *card*'s X is announced as life to pay (CR 107.3a, CR 119.4):
    "As an additional cost to cast this spell, pay X life." """
    return any(cost.pay_life_x for cost in additional_costs(card))


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
    x_value = _pick_x_value(
        game, player, card, extra_generic, hand_index=spell_hand_index,
    )
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
        return None
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
        return None
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
        return None
    target = _choose_target_for_spell(card, player_index, game, x_value)
    target_permanent_index: int | list[int] | None = None
    target_permanent_ids: list[int] | None = None
    divided_targets: list[tuple] | None = None
    # The spell a **stack role** names (see `_choose_role_targets`); None for
    # every cast whose announcement has no such role.
    role_stack_index: int | None = None
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
            (
                target, target_permanent_index, target_permanent_ids,
                role_stack_index,
            ) = roles
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
                single = _choose_single_object_target(
                    game, player_index, card, target, x_value=x_value,
                )
                if single == ():
                    # The side the effect wants holds no legal target, so the
                    # cast would resolve doing nothing — or doing it to the
                    # caster's own permanent. Skipped rather than proposed.
                    return None
                if single is not None:
                    target, target_permanent_index, target_permanent_ids = single
    # "Exile target card from a graveyard" (Coffin Purge): whose graveyard,
    # named — see `_graveyard_denial_target`. Only where nothing above named
    # an object, which for a spell whose one target is a graveyard card is
    # always.
    if target_permanent_index is None and divided_targets is None:
        buried = _cast_graveyard_denial(game, player_index, card)
        if buried is not None:
            target, target_permanent_index = buried
    # "…that player must choose at least one Flagbearer on the battlefield if
    # able" (Standard Bearer): the announcement chosen above, held to what an
    # opponent's permanent demands of it — re-aimed where this seat can obey on
    # the board it already chose, not proposed where it cannot.
    aimed = _aimed_under_target_requirements(
        game, player_index, card, from_zone,
        target, target_permanent_index, target_permanent_ids, divided_targets,
    )
    if aimed is None:
        return None
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
    if not _caster_holds_a_hand_pick_entrant(
        game, player_index, card, spell_hand_index
    ):
        # "Each player chooses a card in their hand. … The owner of each
        # creature card revealed this way with the lowest mana value puts it
        # onto the battlefield." With no creature card of its own to pick, the
        # caster's Stronghold Gambit can only hand the opponent a free one.
        return None
    tap_indices: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()

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
                return None
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
            # CR 118.9d: the cost increases in force are "applied to that
            # alternative cost", so a pitch spell under Sphere of Resistance
            # owes {1} beside its card and its life. Planned here for the
            # reason the mana cost above is — the cast spends the pool, and a
            # proposal with nothing tapped behind it is refused, the same card
            # every turn — and through the one reader the offer's `payable`
            # and the castable highlight price the same announcement with.
            plan = _alternative_cost_tap_plan(
                game, player_index, card, extra_generic=extra_generic,
            )
            if plan is None:
                return None
            tap_indices, tap_colors = plan
            alternative_cost = True
        else:
            tap_indices, tap_colors = plan

    action = CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=tap_indices,
        score=0.0,
        hand_index=hand_index,
        target_permanent_index=target_permanent_index,
        target_permanent_ids=target_permanent_ids,
        from_zone=from_zone,
        zone_seat=_zone_seat(player_index, under),
        alternative_cost=alternative_cost,
        divided_targets=divided_targets,
        land_tap_colors=tap_colors,
        optional_cost_payments=dict(offers) if announces_offer else None,
        mode_index=_announced_mode(card),
        target_stack_index=role_stack_index,
    )
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
    rehearsal = None
    if card.primary_type in SPELL_TYPES:
        rehearsal = _rehearse_announcement(
            game, player_index, card, cast_announcement(action), planned=action,
        )
        # ...and, for a cast made before the fight whose good is this turn's
        # only, what it does to the fight.
        rehearsal = _weighed_through_the_fight(
            game, player_index, card, cast_announcement(action), rehearsal,
            planned=action,
        )
        if not _worth_proposing(rehearsal):
            if rehearsal is not None and rehearsal.accepted and rehearsal.fleeting:
                _HELD_AS_FLEETING.set(True)
            return None
        if rehearsal is None and _names_an_unweighed_seat(game, player_index, card):
            return None
    score = _score_cast(game, player_index, card, target, x_value, rehearsal)
    if from_zone == "command":
        score += COMMAND_ZONE_CAST_BONUS
    elif under is not None and under.zone != "hand" and under.expires:
        score += EXPIRING_PERMISSION_BONUS
    return replace(action, score=score)


def _graveyard_denial_target(
    game: Game, player_index: int, legal
) -> "tuple[int, int] | None":
    """``(pile's seat, slot)`` — the card an "exile target card from a
    graveyard" is aimed at — or None to name nothing.

    *legal* is the picker's own list for the announcement (``valid_targets``).
    A card in **another seat's** pile, the ones its owner could still cast
    from there first (`ai_valuation.graveyard_denial_order`), then seat and
    pile order. None when no other seat's pile holds a legal card: the
    announcement is then what it always was — a seat and no slot, which the
    handler answers.

    **Why the policy names it at all.** A bare announcement falls to the
    handler's scan, "the first graveyard with a card in it, in seat order" —
    so the seat in chair 0 exiled a card of its own with Coffin Purge, Cremate,
    Headstone, Crypt Creeper, Steamclaw, Grave Robbers and Scavenging Ooze,
    and the seat in chair 1 exiled its opponent's, off one board. A graveyard
    card is announced as a seat and a slot in that seat's pile, the spelling
    the cast and activation gates check (`targeting.GRAVEYARD_TARGET_KIND`).
    """
    by_seat: dict[int, list[int]] = {}
    for entry in legal or ():
        if entry.get("kind") != "graveyard":
            continue
        seat = int(entry["seat"])
        if seat != player_index:
            by_seat.setdefault(seat, []).append(int(entry["index"]))
    for seat in sorted(by_seat):
        ordered = graveyard_denial_order(game, seat, by_seat[seat])
        if not ordered:
            continue
        # One card, not "up to three": among the cards its owner could no
        # longer cast anyway, the one of greatest mana value — what a
        # recursion would most want back, and what an exile that pays its
        # source for the card (Scavenging Ooze's creature) is worth most
        # against. The castable ones stay first, whatever they cost.
        from .flashback import has_flashback

        pile = game.players[seat].graveyard
        first = ordered[0]
        if not has_flashback(pile[first], game=game, owner_seat=seat):
            first = max(
                ordered,
                key=lambda slot: (float(getattr(pile[slot], "cmc", 0) or 0), -slot),
            )
        return seat, first
    return None


def _cast_graveyard_denial(
    game: Game, player_index: int, card: CardDefinition
) -> "tuple[int, int] | None":
    """`_graveyard_denial_target` for the cast candidate being built: the
    spell's own spec and steps (its mode, its offers, the zone it leaves),
    and the picker's list for that announcement."""
    program = compile_card_oracle(card)
    if not _one_graveyard_card_is_denied(
        _cast_spec(card, program), _announced_steps(card, program)
    ):
        return None
    legal = game.cast_target_spec(
        player_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
    ).get("valid_targets") or []
    return _graveyard_denial_target(game, player_index, legal)


def _cast_life_price(
    card: CardDefinition, from_zone: str, x_value: "int | None",
    offers: "dict[str, int] | None", under: "PermittedCast | None",
) -> int:
    """The life the announcement being built pays **as a cost** (CR 601.2h):
    every printed additional cost that applies to a cast from *from_zone* and
    is mandatory or taken (`optional_cost_taken`, the cast path's own reader),
    at the announced X, plus what a required alternative cost asks
    (`PermittedCast.cost`: a flashback cost printed with "Pay 3 life")."""
    from .mixins.stack.casting import optional_cost_taken

    total = 0
    for cost in additional_costs(card):
        if cost.from_zone not in (None, from_zone):
            continue
        if not optional_cost_taken(cost, offers):
            continue
        total += int(cost.life_charged(x_value) or 0)
    if under is not None and under.cost is not None:
        total += int(getattr(under.cost, "pay_life", 0) or 0)
    return total


def _one_graveyard_card_is_denied(spec, instructions) -> bool:
    """Whether an announcement described by *spec* names exactly **one card in
    a graveyard** and the steps behind it exile that card — the shape
    `_graveyard_denial_target` answers."""
    return (
        isinstance(spec, dict)
        and spec.get("kind") == GRAVEYARD_TARGET_KIND
        and not spec_roles(spec)
        and not spec_is_a_cost(spec)
        and not spec.get("max_targets")
        and not spec.get("x_targets")
        and exiles_a_graveyard_target(instructions)
    )


def _aimed_under_target_requirements(
    game: Game, player_index: int, card: CardDefinition, from_zone: str,
    target, target_permanent_index, target_permanent_ids, divided_targets,
):
    """The announcement ``(seat, slot, ids, division)`` as the cast gate will
    accept it under a requirement an opponent's permanent prints about it
    ("…that player must choose at least one Flagbearer on the battlefield if
    able", ``engine/target_requirements.py``) — unchanged where nothing binds
    it or it already obeys, **re-aimed** where it can, None where this seat
    should not make it at all.

    Asked of the engine's own gate (`Game.cast_target_requirement_refusal`)
    for the reason every gate in the candidate builders is: a cast the engine
    will refuse costs nothing, and the seat re-proposes it every turn —
    `refused_casts`, for as long as the Flagbearer lives.

    The re-aim is onto a required permanent **on the board the policy already
    chose**, which is what keeps it a decision about the rule and not about
    the card: removal and burn pointed at the opponent land on the opponent's
    Flagbearer, and a Giant Growth pointed at this seat's own creature is not
    turned into a gift — with no Flagbearer of its own to put it on, the seat
    holds the card. One slot, or the first entry of a division; an
    announcement of several objects or of roles is not rebuilt here.
    """
    from .target_requirements import one_slot

    mode_index = _announced_mode(card)
    offers = _OFFERS_ANNOUNCED.get()
    standing = (target, target_permanent_index, target_permanent_ids, divided_targets)
    if game.cast_target_requirement_refusal(
        player_index, card,
        announcements=[
            (mode_index, target, target_permanent_index, target_permanent_ids, None)
        ],
        divided_targets=divided_targets,
        from_zone=from_zone,
        optional_cost_payments=offers,
    ) is None:
        return standing
    spec = game.cast_target_spec(
        player_index, card, from_zone=from_zone,
        optional_cost_payments=offers, mode_index=mode_index,
    )
    wanted = [
        entry for entry in spec.get("required_targets") or ()
        if entry.get("seat") == target
    ]
    if not wanted:
        return None
    pick = wanted[0]
    if divided_targets:
        first = tuple(divided_targets[0])
        return (
            target, target_permanent_index, target_permanent_ids,
            [(pick["seat"], pick["index"], *first[2:]), *divided_targets[1:]],
        )
    if not one_slot(spec):
        return None
    return pick["seat"], pick["index"], [pick["id"]], None


def _required_activation_target(
    game: Game, player_index: int, permanent_index: int, target
) -> int | None:
    """The slot on seat *target* a one-target ability must be aimed at for
    its activation to obey a target requirement in force, or None when there
    is none there. `_aimed_under_target_requirements` for an activation: the
    picker's own ``required_targets``, on the board the policy already chose.
    """
    from .target_requirements import one_slot

    spec = game.activation_target_spec(player_index, permanent_index, ability_index=0)
    if not one_slot(spec):
        return None
    return next(
        (
            entry["index"] for entry in spec.get("required_targets") or ()
            if entry.get("seat") == target
        ),
        None,
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


def _alternative_cost_tap_plan(
    game: Game, player_index: int, card: CardDefinition, *, extra_generic: int = 0,
) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
    """The taps that pay the **mana** an alternative-cost cast of *card* still
    owes (CR 118.9d), or None when the board cannot pay it.

    The amount is the engine's (`Game.alternative_cost_mana`): nothing on an
    untaxed board, which plans no tap at all and is every such cast this policy
    made before the cast path charged the increases.

    A plan that would tap the creature the cost itself must tap ("you may tap
    an untapped creature you control rather than pay this spell's mana cost",
    Lashknife, with a Llanowar Elves the only creature) is no plan: the mana
    would be made and the cast refused for want of an untapped creature.
    """
    printed = game.applicable_alternative_costs(player_index, card)
    if len(printed) != 1:
        return None
    cost = printed[0]
    owed = game.alternative_cost_mana(
        player_index, card, cost, extra_generic=extra_generic,
    )
    plan = _plan_land_taps(game, game.players[player_index], owed)
    if plan is None or not cost.tap_count:
        return plan
    planned = [game.permanent_at(player_index, index) for index in plan[0]]
    left = [
        permanent
        for permanent in game._additional_cost_candidates(
            player_index, cost, giving_up="tap"
        )
        if not any(permanent is tapped for tapped in planned)
    ]
    return plan if len(left) >= cost.tap_count else None


def choose_activation_action(game: Game, player_index: int) -> ActivationAction | None:
    from .targeting import GRAVEYARD_TARGET_KIND

    player = game.players[player_index]

    best: ActivationAction | None = None
    set_aside = _ACTIVATIONS_SET_ASIDE.get()
    for permanent_index, permanent in enumerate(player.battlefield):
        if permanent.tapped or permanent.card.primary_type == "land":
            continue
        if game._is_summoning_sick(permanent):
            continue
        # One the instant-speed chooser has rehearsed and turned down this
        # time it was asked (`choose_instant_speed_activation`), so the
        # next-best is the one proposed.
        if permanent.permanent_id in set_aside:
            continue

        # A permanent an effect stripped of its abilities ("loses all
        # abilities", CR 305.7) has none to propose: the engine refuses every
        # one, so naming one is a turn spent on a refusal, every turn.
        if game.lost_abilities_refusal(permanent) is not None:
            continue
        # **What the permanent has, not what its card prints** — the engine's
        # own list (`Game.usable_abilities_of`), which is the one the
        # activation path indexes into and the browser shows a person. It
        # compiles the permanent's *effective* card: CR 613's layer 1 gives a
        # copy the copied object's abilities and layer 6 gives an enchanted
        # permanent the ones its Aura quotes. This compiled ``permanent.card``,
        # so a Clone of a Prodigal Sorcerer never pinged in an AI's hands and
        # a creature wearing Hermetic Study was a creature wearing nothing
        # (`tests/ai/test_ai_activation_effective_card_census.py`: of 931
        # cards whose printed self the seat activates, a copy of none).
        #
        # The shared reader, not a third copy of its predicate: it carries
        # CR 113.6's zone read, so a cycling creature's "{2}, Discard this card:
        # Draw a card." is not on this list at all. Open-coded, the policy
        # proposed it every main phase and the engine ran it — a free repeatable
        # draw for a card that was never discarded, on eight of Urza's Saga's
        # creatures. It is also the list `activation_target_spec` narrows by,
        # which the `ability_index=0` below already assumes.
        ability = next(iter(game.usable_abilities_of(permanent)), None)
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
        # CR 602.5 as **one question** (``engine/activation_prohibitions.py``):
        # the table the activation path refuses with. The two checks around
        # this one are three of its ten rows; the other seven this chooser
        # never asked — City of Solitude's "…activate abilities only during
        # their own turns", Hand to Hand's "during combat", an Abeyance, an
        # Interdict, Faith's Fetters, Volrath's Curse, Katabatic Winds — so it
        # proposed the ability and the engine refused it, the seat's only
        # activation of the turn, every turn.
        if activation_prohibition(game, player_index, permanent, ability) is not None:
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
        target_permanent_index: int | list[int] | None = None
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
            # "{T}: Untap **two** target lands" (Argothian Elder), "Choose two
            # target blocked attacking creatures" (General Jarkeld): a printed
            # count names that many (CR 601.2c), and the engine refuses an
            # activation naming fewer. All on the chosen permanent's seat,
            # because this action carries one seat beside its slots — the
            # strongest there first, the order the single pick takes.
            wanted = spec.get("max_targets")
            if spec.get("exact_targets") and isinstance(wanted, int) and wanted > 1:
                beside = sorted(
                    (t for t in perms if t["seat"] == target),
                    key=_power, reverse=True,
                )
                if len(beside) < wanted:
                    continue
                target_permanent_index = [t["index"] for t in beside[:wanted]]

        # "{G}: Exile target card from a graveyard." (Scavenging Ooze.) A card
        # in a graveyard is a target like any other (CR 115.1c), and this
        # chooser named none: the block above reads battlefield kinds, so the
        # announcement went out bare and the engine's default answered it —
        # the picker's first card, which is a stated default for a script and
        # not a choice. The seat's own pick instead: the pile the effect's
        # side wants (`_activation_target_side`), and within it the card with
        # the greatest mana value. Where the effect reads as neither side's —
        # the Ooze's exile is one — an opposing pile is taken before the
        # seat's own, which is the order an unnamed target is looked for in
        # everywhere else. Skipped when nothing on the wanted side is legal,
        # for the battlefield block's reason — and for the two shapes a block
        # below names: several cards out of a single pile (``SINGLE_GRAVEYARD``)
        # and a card exiled to deny it (`_graveyard_denial_target`: an
        # opponent's pile, the cards its owner could still cast first).
        if (
            target_permanent_index is None
            and spec is not None
            and spec.get("kind") == GRAVEYARD_TARGET_KIND
            and not spec_is_a_cost(spec)
            and not spec.get("source_of_choice")
            and not spec.get(SINGLE_GRAVEYARD)
            and not _one_graveyard_card_is_denied(spec, (ability.instruction,))
        ):
            cards = [
                t for t in game.activation_target_spec(
                    player_index, permanent_index, ability_index=0,
                ).get("valid_targets") or []
                if t.get("kind") == "graveyard"
            ]
            side = _activation_target_side(permanent, ability.instruction)
            if side == "you":
                cards = [t for t in cards if t["seat"] == player_index]
            elif side == "opponent":
                cards = [t for t in cards if t["seat"] != player_index]
            if not cards:
                continue

            def _mana_value(t):
                pile = game.players[t["seat"]].graveyard
                held = pile[t["index"]] if 0 <= t["index"] < len(pile) else None
                return float(getattr(held, "cmc", 0) or 0)

            if side is None and any(t["seat"] != player_index for t in cards):
                cards = [t for t in cards if t["seat"] != player_index]
            chosen = max(cards, key=_mana_value)
            target = chosen["seat"]
            target_permanent_index = chosen["index"]

        # "{2}{B}, {T}: Exile up to three target cards from a single
        # graveyard." (Carrion Beetles, Famished Ghoul.) The cards are announced
        # (CR 602.2b), so an activation that names none is the legal "up to"
        # announcement and exiles nothing — a cost paid for no effect, which is
        # what this seat did with every one of them once the handler stopped
        # picking for it. Named here the way the cast side names them
        # (`_choose_several_targets`): the maximum, out of one opponent's pile,
        # and skipped when no opponent has a card to take.
        if (
            spec is not None
            and spec.get(SINGLE_GRAVEYARD)
            and target_permanent_index is None
            and not target_role_refs
        ):
            piles: dict[int, list[int]] = {}
            for entry in game.activation_target_spec(
                player_index, permanent_index, ability_index=0,
            ).get("valid_targets") or []:
                if entry.get("kind") == "graveyard" and entry.get("seat") != player_index:
                    piles.setdefault(int(entry["seat"]), []).append(int(entry["index"]))
            if not piles:
                continue
            target = min(piles)
            target_permanent_index = piles[target][: int(spec.get("max_targets") or 1)]
        # "{3}, {T}: Exile target card from a graveyard." (Steamclaw; Crypt
        # Creeper, Grave Robbers, Scavenging Ooze.) Whose graveyard, named —
        # the cast side's answer (`_graveyard_denial_target`) over this
        # ability's own picker. Named nothing, the handler took the first pile
        # in seat order: the activator's own, from chair 0.
        if (
            target_permanent_index is None
            and not target_role_refs
            and _one_graveyard_card_is_denied(spec, (ability.instruction,))
        ):
            buried = _graveyard_denial_target(
                game, player_index,
                game.activation_target_spec(
                    player_index, permanent_index, ability_index=0,
                ).get("valid_targets") or [],
            )
            if buried is not None:
                target, target_permanent_index = buried

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
        # …and what an opponent's Flagbearer demands of that announcement
        # (`Game.activation_target_requirement_refusal`): a seat named alone
        # for an "any target" ability is re-aimed at the Flagbearer on that
        # seat, and anything else the gate would refuse is not proposed.
        if game.activation_target_requirement_refusal(
            player_index, permanent, ability,
            target_player_index=target,
            target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs,
        ) is not None:
            required_slot = (
                _required_activation_target(game, player_index, permanent_index, target)
                if target_permanent_index is None and not target_role_refs
                else None
            )
            if required_slot is None:
                continue
            target_permanent_index = required_slot

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


#: Permanents `choose_activation_action` passes over, by ``permanent_id``:
#: the ones `choose_instant_speed_activation` has rehearsed and turned down in
#: the one decision it is making.
_ACTIVATIONS_SET_ASIDE: ContextVar[frozenset] = ContextVar(
    "ai_activations_set_aside", default=frozenset(),
)

#: How many of the main-phase chooser's proposals one instant-speed decision
#: rehearses before it passes: each is a copy of the game run out to the end
#: of its turn, and the engine offers priority dozens of times a turn.
INSTANT_ACTIVATIONS_WEIGHED = 3


def choose_instant_speed_activation(
    game: Game, player_index: int,
) -> ActivationAction | None:
    """The ability this seat activates **now** — given priority in response to
    another seat's object, in the declare-blockers step, or in the opponent's
    end step — or None.

    The main-phase chooser proposes (`choose_activation_action`: every gate
    the engine refuses with, CR 602.5's timing among them, the cost planned,
    the target chosen), and a rehearsal disposes: the activation carried out
    on a copy against the same table with nothing activated — the object on
    the stack resolving, the declared combat dealt — and made only where what
    it does outlasts the turn, as `_combat_instant_candidate` asks of a cast.
    That chooser prices every non-damage ability alike, so its pick is a
    proposal and not a decision: a regeneration shield in front of a burn
    spell is worth a creature, the same shield with nothing coming is worth
    nothing, and only carrying it out tells the two apart. A proposal turned
    down is set aside and the next-best asked for, up to
    `INSTANT_ACTIVATIONS_WEIGHED` of them.
    """
    set_aside: set[int] = set(_ACTIVATIONS_SET_ASIDE.get())
    with deliberating():
        for _ in range(INSTANT_ACTIVATIONS_WEIGHED):
            token = _ACTIVATIONS_SET_ASIDE.set(frozenset(set_aside))
            try:
                action = choose_activation_action(game, player_index)
            finally:
                _ACTIVATIONS_SET_ASIDE.reset(token)
            if action is None:
                return None
            rehearsal = _rehearse_activation(game, player_index, action)
            if (
                rehearsal is not None
                and _worth_proposing(rehearsal)
                and rehearsal.lasting > 0.0
            ):
                return action
            permanent = game.permanent_at(player_index, action.permanent_index)
            if permanent is None:
                return None
            set_aside.add(permanent.permanent_id)
    return None


def _rehearse_activation(
    game: Game, seat: int, action: ActivationAction,
) -> Rehearsal | None:
    """What activating *action* would do, carried out on a scratch copy of
    the game (``ai_valuation.rehearse``) the way `activate_chosen_ability`
    carries it out — the planned lands tapped, the ability put on the stack —
    against the same copy with the same lands tapped and nothing activated."""

    def perform(table):
        return _queue_activation(table, seat, action)

    def paid_for(table, _carried) -> None:
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, action)
        pool.clear()
        pool.update(floating)

    taps = bool(action.land_tap_indices)
    return rehearse(
        game, seat, perform, spell_name=None, leaves_hand=False,
        label=f"{action.permanent_name}'s ability",
        key=(
            "activation", seat, action.permanent_name, action.permanent_index,
            action.ability_index, action.target_player_index,
            repr(action.target_permanent_index), repr(action.target_role_refs),
            action.land_tap_indices, action.land_tap_colors,
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", action.land_tap_indices, action.land_tap_colors)
            if taps else None
        ),
    )


def _queue_activation(table: Game, seat: int, action: ActivationAction):
    """*action* paid for and put on *table*'s stack — the queue form, which
    leaves it there for the table to answer (CR 117.3c)."""
    planned = tap_planned_lands(table, seat, action)
    return table.queue_permanent_ability(
        seat,
        planned.permanent_name,
        target_player_index=planned.target_player_index,
        permanent_index=planned.permanent_index,
        target_permanent_index=planned.target_permanent_index,
        target_role_refs=planned.target_role_refs,
        ability_index=planned.ability_index,
    )


def activate_chosen_ability(game: Game, seat: int, action: ActivationAction):
    """Carry out `choose_instant_speed_activation`'s *action* on *game*: the
    engine's result."""
    return _queue_activation(game, seat, action)


def holds_an_ability_it_could_activate(game: Game, player_index: int) -> bool:
    """Whether `choose_activation_action` has anything to look at: an
    untapped permanent *player_index* controls that is not summoning sick,
    whose first usable ability is not a mana ability — the chooser's own first
    gates, asked before it is. (The chooser also passes over lands; asked
    here, a land whose first ability is not a mana ability only sends the
    question on to it.)"""
    for permanent in game.controlled_by(player_index):
        if permanent.tapped:
            continue
        if game._is_summoning_sick(permanent):
            continue
        ability = next(iter(game.usable_abilities_of(permanent)), None)
        if (
            ability is not None
            and ability.instruction is not None
            and not is_mana_ability(ability.instruction)
        ):
            return True
    return False


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
    # "{T}: Put a fuse counter on target creature." (Bomb Squad.) A named
    # counter reads as a gift by category, and the card's own state trigger
    # says this one is a death sentence — the Licids' case again: which board
    # the target belongs on is what the card's *other* text does with it.
    if named_counter_marks_for_harm(permanent.effective_card, instruction):
        return "opponent"
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
    # **One side per role, not one for the chain** — the derivation the cast
    # side asks (`ai_valuation.role_target_sides`), over this ability's own
    # roles. "Target creature with the chosen ability loses it and **another
    # target creature** gains it" (Phyrexian Splicer) is two roles on two
    # boards, and a single side — or none, the first option at each level —
    # named two of the activator's own creatures: the seat paid {2} to move
    # its own flying from one of its creatures to another. *side* stays the
    # answer for a role the derivation gives none (the three seat-role
    # chains it was written for).
    #
    # The permanent as it **is** (``effective_card``), which is the card the
    # picker three lines up compiled: read off the printed one, a Clone of a
    # Splicer was offered the Splicer's two roles and given a side for neither.
    source = game.permanent_at(player_index, permanent_index)
    said = source.effective_card if source is not None else None
    ability = (
        next(iter(usable_activated_abilities(compile_card_oracle(said))), None)
        if said is not None else None
    )
    sides = ability_role_target_sides(said, ability) if ability is not None else ()

    def ref_of(pick: dict) -> "dict | None":
        if pick.get("kind") == "player":
            return {"seat": pick.get("seat")}
        if pick.get("kind") == "graveyard":
            return {
                "graveyard_seat": pick.get("seat"),
                "graveyard_index": pick.get("index"),
            }
        permanent_id = game.permanent_id_of(
            game.permanent_at(pick.get("seat"), pick.get("index"))
        )
        return {"permanent_id": permanent_id} if isinstance(permanent_id, int) else None

    def chain(level: list[dict], position: int) -> "list[dict] | None":
        """The first chain from *level* on whose every role is on the board
        its step wants. Backtracks, because a side makes a first pick able to
        strand a later role the unfiltered walk had an answer for."""
        wanted = (sides[position] if position < len(sides) else None) or side
        if wanted in ("you", "opponent") and any(
            option.get("kind") == "permanent" for option in level
        ):
            level = [
                option for option in level
                if option.get("kind") != "permanent"
                or (option.get("seat") == player_index) == (wanted == "you")
            ]
        for pick in level:
            ref = ref_of(pick)
            if ref is None:
                continue
            rest = pick.get("next") or []
            if not rest:
                return [ref]
            tail = chain(rest, position + 1)
            if tail is not None:
                return [ref, *tail]
        return None

    return chain(options, 0) if options else None


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
        if global_activation_ban(game, permanent):
            continue
        # ``usable_abilities_of``: empty for a permanent that lost its
        # abilities — "loses all abilities", which this asked inline, and a
        # land whose type was set (CR 305.7), which it did not.
        for ability_index, ability in enumerate(game.usable_abilities_of(permanent)):
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
    if game.activation_target_requirement_refusal(
        player_index, permanent, ability,
        target_player_index=target,
        target_permanent_index=target_permanent_index,
    ) is not None:
        # An opponent's Flagbearer demands a target this announcement does not
        # name. Not proposed: the gate would refuse it with nothing paid.
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
    """The instant this seat casts **now** — in response to what is on the
    stack, or in the declare-blockers step — or None.

    The answer to priority of both callers that play a seat nobody asks: the
    web AI's (`web/game_flow._ai_respond_to_priority`) and the AI
    simulator's (`ai_simulator`'s `Game.priority_driver`), each through
    `cast_chosen_instant`. **Every mode of a modal instant is weighed here as
    it is in the main phase** (`_cast_candidate`): this is the one moment a
    mode whose target is a spell on the stack can be announced at all, and
    with no mode named Dromar's Charm never countered anything and Treva's
    Charm never exiled an attacker.
    """
    offered = _instant_speed_offers(game, player_index)
    best: CastAction | None = None
    # One deliberation for the whole hand: every instant weighed here answers
    # the same stack and the same combat, so each is measured against one
    # reading of how that goes with nothing cast.
    with deliberating():
        for hand_index, card, under in offered:
            if card.primary_type != "instant":
                continue
            built: list[CastAction] = []
            chosen: CastAction | None = None
            for mode_index in _modes_weighed(game, player_index, card):
                with considering_mode(card, mode_index), casting_under(under):
                    candidate = _combat_instant_candidate(
                        game, player_index, card, hand_index
                    )
                if candidate is None:
                    continue
                built.append(candidate)
                # Strictly better only: equal modes of one card keep printed order.
                if chosen is None or candidate.score > chosen.score:
                    chosen = candidate
            if len(built) > 1 and compile_card_oracle(card).modes_at_least:
                # "Choose one or more —": every mode worth casting, in one cast.
                chosen = _every_mode_worth_casting(built, chosen) or chosen
            if chosen is not None and _is_better_cast(chosen, best):
                best = chosen

    return best


def _instant_speed_offers(
    game: Game, player_index: int,
) -> "list[tuple[int, CardDefinition, PermittedCast | None]]":
    """What `choose_combat_instant_cast_action` weighs: ``(zone index, spell,
    the permission it is cast under)`` for each instant *player_index* may
    cast now.

    The hand's instants, then the instants an effect lets the seat cast from
    somewhere else (CR 601.3; `ai_valuation.permitted_casts`) — a flashback
    instant in its graveyard (Moment's Peace, Sylvan Might), which is
    castable in this window exactly as the hand's are. A hand card is weighed
    under the waiver that covers it, if one does (`hand_waiver`), as the
    main-phase chooser weighs it.
    """
    player = game.players[player_index]
    offered: "list[tuple[int, CardDefinition, PermittedCast | None]]" = [
        (
            hand_index, card,
            hand_waiver(game, player_index, player.hand[hand_index], card, hand_index),
        )
        for hand_index, card in hand_spells(player)
        if card.primary_type == "instant"
    ]
    offered += [
        (permitted.index, permitted.spell, permitted)
        for permitted in permitted_casts(game, player_index)
        if permitted.spell.primary_type == "instant"
    ]
    return offered


def holds_an_instant_it_could_pay_for(game: Game, player_index: int) -> bool:
    """Whether `choose_combat_instant_cast_action` could propose anything at
    all: *player_index* holds an instant (or may cast one from elsewhere)
    whose mana its board can pay, by the chooser's own gates — the X it would
    announce (`_pick_x_value`; an X of 0 is never proposed), the cost it
    would be charged (`_cost_for`, under the permission being weighed) and the
    tap plan (`_plan_land_taps`).

    **The cheap question asked before the dear one.** The chooser rehearses
    every instant it weighs on a copy of the game, and a table that gives
    priority before every resolution and at every step's end asks it dozens
    of times a turn; most of those asks are of a seat holding no instant, or
    tapped out. Every candidate the chooser builds passes these same gates,
    so a False here is a None there, never a different answer. True with
    mana costs unenforced, where the chooser asks no plan.
    """
    player = game.players[player_index]
    for _index, card, under in _instant_speed_offers(game, player_index):
        if not game.enforce_mana_costs:
            return True
        with casting_under(under):
            x_value = _pick_x_value(game, player, card)
            if x_value == 0:
                continue
            required = _cost_for(game, player, card, x_value)
            if _plan_land_taps(game, player, required) is not None:
                return True
    return False


def cast_chosen_instant(
    game: Game, seat: int, action: CastAction,
) -> "tuple[CardDefinition, SimulationResult]":
    """Carry out `choose_combat_instant_cast_action`'s *action*: the spell
    out of the zone the action names (`zone_being_cast_from`: the hand, or a
    graveyard holding a flashback instant), the planned lands tapped
    (`tap_planned_lands`), and the whole announcement (`cast_announcement`)
    put on the stack — the **queue** form, which leaves it there for the
    table to answer (CR 117.3c). ``(the spell, the engine's result)``.

    The executor both callers of the chooser share, as `tap_planned_lands`
    is for every other AI action: the web AI seat's answer to priority and
    the simulator's.
    """
    card = spell_being_cast(zone_being_cast_from(game, seat, action), action)
    action = tap_planned_lands(game, seat, action)
    return card, game.queue_from_hand(seat, card.name, **cast_announcement(action))


def _combat_instant_candidate(
    game: Game, player_index: int, card: CardDefinition, hand_index: int
) -> CastAction | None:
    """`choose_combat_instant_cast_action` for one instant, in the mode being
    weighed (`_announced_mode`) and under the permission being weighed
    (`ai_valuation.cast_weighed`: a flashback instant in the graveyard) — or
    None when it is not worth casting now. *hand_index* indexes the zone that
    permission names, the hand where there is none."""
    player = game.players[player_index]
    under = cast_weighed(card)
    if not _can_cast_with_targets(game, player_index, card):
        return None
    if (
        under is not None
        and under.cost is not None
        and game._unpayable_alternative_cost(
            player_index, card, under.cost,
            spell_hand_index=hand_index if under.zone == "hand" else None,
        ) is not None
    ):
        # What a required alternative cost asks beside its mana — see
        # `_cast_candidate_announcing`.
        return None
    # "Counter target spell **if it's red**": which spell, or no cast at all
    # when the guard holds for none of them (`_guarded_stack_target`).
    stack_target = _guarded_stack_target(game, player_index, card)
    if stack_target == ():
        return None

    target = _choose_target_for_spell(card, player_index, game)
    x_value = _pick_x_value(game, player, card)
    if x_value == 0:
        return None
    # CR 601.2d, for the same reason `_cast_candidate` asks it: Pyrokinesis
    # and Contagion are instants with an alternative cost, so this is the
    # chooser that offers them during combat — and a divided spell proposed
    # with no division is refused at announcement.
    divided = choose_divided_targets(game, player_index, card, x_value)
    if divided is not None and not divided:
        return None
    # The same "would the resolution do anything" questions the main-phase
    # chooser asks (`_cast_candidate`), for the same reasons: a one-object
    # spell names its permanent on the side the effect wants or is not
    # cast, and a spell that sacrifices what its caster lacks is not cast.
    target_permanent_index: int | None = None
    target_permanent_ids: list[int] | None = None
    tap_indices: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()

    # The mana before the target, for `_cast_candidate_announcing`'s reason:
    # weighing a target is a rehearsal apiece, and a spell the lands cannot
    # pay for has none worth weighing.
    if game.enforce_mana_costs:
        required = _cost_for(game, player, card, x_value)
        plan = _plan_land_taps(game, player, required)
        if plan is None:
            return None
        tap_indices, tap_colors = plan
    if stack_target is None:
        # A spell targeting a spell with no guard to choose by: which one, by
        # rehearsal, where there is more than one (`_chosen_stack_target`).
        stack_target = _chosen_stack_target(game, player_index, card, target)
        if stack_target == ():
            return None
    # A spell naming several **roles** is answered role by role, as the
    # main-phase chooser answers it (`_choose_role_targets`). This chooser asked
    # only the one-object question, which a roles spell answers "not mine" —
    # so an instant with two differently-restricted targets (Shower of Sparks,
    # Fiery Justice's kin) was proposed here naming neither, refused by the
    # cast gate for "requires 2 targets", and proposed again at the next
    # window. With a role on the stack (Suffocating Blast) this is also the
    # only chooser that ever sees a spell to name.
    roles = _choose_role_targets(game, player_index, card) if divided is None else None
    if roles is not None:
        if roles == ():
            return None
        target, target_permanent_index, target_permanent_ids, role_stack = roles
        if role_stack is not None:
            stack_target = role_stack
    elif divided is None:
        single = _choose_single_object_target(
            game, player_index, card, target, x_value=x_value,
        )
        if single == ():
            return None
        if single is not None:
            target, target_permanent_index, target_permanent_ids = single
    # ...and the same graveyard a denial is aimed at (`_cast_graveyard_denial`).
    if target_permanent_index is None and divided is None:
        buried = _cast_graveyard_denial(game, player_index, card)
        if buried is not None:
            target, target_permanent_index = buried
    # The same hold the main-phase chooser applies (`_cast_candidate`): what an
    # opponent's Flagbearer demands of this announcement.
    aimed = _aimed_under_target_requirements(
        game, player_index, card, _cast_zone(card),
        target, target_permanent_index, target_permanent_ids,
        list(divided) if divided else None,
    )
    if aimed is None:
        return None
    target, target_permanent_index, target_permanent_ids, held_division = aimed
    if divided:
        divided = held_division
    if not _caster_can_make_its_sacrifices(game, player_index, card):
        return None

    candidate = CastAction(
        card_name=card.name,
        target_player_index=target,
        x_value=x_value,
        land_tap_indices=tap_indices,
        score=0.0,
        hand_index=hand_index,
        target_permanent_index=target_permanent_index,
        target_permanent_ids=target_permanent_ids,
        divided_targets=list(divided) if divided else None,
        land_tap_colors=tap_colors,
        mode_index=_announced_mode(card),
        target_stack_index=stack_target,
        # Where the card is and which permission the cast names — "hand" and
        # no alternative cost for every candidate this chooser built before.
        from_zone=_cast_zone(card),
        zone_seat=_zone_seat(player_index, under),
        alternative_cost=under is not None and under.alternative_cost,
    )
    # What casting it **now** would do, measured against what happens with
    # nothing cast: the spell on the stack resolving, the declared combat
    # dealing its damage (`ai_valuation.rehearse`). That comparison is the
    # whole of what the words "damage", "destroy", "prevent" and "tap" in a
    # card's text used to stand for here — a counterspell is worth the spell
    # it stops, a pump is worth the blocker it saves and the attacker that
    # dies to it — and a response that changes nothing is not made.
    rehearsal = _rehearse_announcement(
        game, player_index, card, cast_announcement(candidate), planned=candidate,
    )
    if not _worth_proposing(rehearsal):
        return None
    if rehearsal is None and _names_an_unweighed_seat(game, player_index, card):
        return None
    if rehearsal is not None and rehearsal.lasting <= 0.0:
        # Nothing it does outlasts the turn: a pump with no fight to decide,
        # a shield with nothing coming, a tap of something already tapped.
        # The seat's own main phase is where such a card is still worth a
        # cast; a response is held for a moment it changes.
        return None
    score = _score_cast(game, player_index, card, target, x_value, rehearsal)
    score += _stack_response_bonus(game, player_index)
    if score < 2.0:
        return None

    return replace(candidate, score=score)


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
    from .search_filters import (landing_seat, name_key, search_slots,
                                 slot_assignment)

    # The zone the search looks in, which is not always the chooser's own —
    # see `searched_seat`. An AI reading its own graveyard for a card the
    # effect takes from someone else's would answer with an index the resolver
    # then refuses, which is the fail-to-find.
    player = game.players[searched_seat(data, player_index)]
    working = dict(data)
    picks: list[dict] = []
    taken: set[tuple[str, int]] = set()
    # **Whose hand the finds are for.** A seat choosing cards that go to
    # somebody else's hand (Guided Passage: "an opponent chooses … you put the
    # chosen cards into your hand"; Jester's Mask's refilled hand) is choosing
    # what its opponent gets, and wants the *least* of what the phrase admits.
    # Read off the prompt's own seats rather than off a card: the finds land
    # where `landing_seat` says, and that is the whole of the question. A find
    # taken out of another seat's library for any other place — exile (Jester's
    # Cap), the chooser's own battlefield (Bribery) — is still the best card.
    destinations = list(working.get("destinations") or ()) or [
        working.get("destination", "hand")
    ]
    handing_over = (
        landing_seat(working, player_index) != player_index
        and all(place == "hand" for place in destinations)
    )
    sign = -1.0 if handing_over else 1.0
    if search_slots(working):
        # "a land card **of each basic land type**" (Gaea's Balance): one find
        # per printed description. Best card first, each kept only while the
        # cards kept so far can still all be given a description of their own
        # — `slot_assignment`, the resolver's own question, so this is an
        # answer it admits. Taking the best that still fits is exact here (the
        # sets that can be assigned are a matroid), so it is also as many
        # finds as the zones allow, which is what a floor asks for.
        entries = [
            (zone, index, card)
            for zone in tuple(working.get("zones", ("library",)))
            for index, card in enumerate(
                player.library if zone == "library" else player.graveyard
            )
            if search_matches(card, working)
        ]
        entries.sort(
            key=lambda entry: -sign * _score_tutor_choice(game, player_index, entry[2])
        )
        kept: list[tuple] = []
        for entry in entries:
            if len(kept) >= count:
                break
            trial = kept + [entry]
            if None not in slot_assignment(
                [card for _zone, _index, card in trial], working
            ):
                kept = trial
        return [{"zone": zone, "index": index} for zone, index, _card in kept]
    for _ in range(count):
        best: tuple[str, int] | None = None
        best_score = float("-inf")
        for zone in tuple(working.get("zones", ("library",))):
            cards = player.library if zone == "library" else player.graveyard
            for index, card in enumerate(cards):
                if (zone, index) in taken or not search_matches(card, working):
                    continue
                score = sign * _score_tutor_choice(game, player_index, card)
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


#: `_score_tutor_choice`'s answers for one position: ``{"at": stamp, (seat,
#: card name): score}``. A search weighs every card it may find, a library is
#: mostly repeats, and weighing a spell is a rehearsal — so each card is
#: weighed once for as long as the position stands.
_TUTOR_SCORES: dict = {}


def _score_tutor_choice(game: Game, player_index: int, card: CardDefinition) -> float:
    """What *card* is worth to *player_index* to have: the score casting it
    would get, in the abstract (`_IN_THE_ABSTRACT`), with what the seat's
    lands say about when.

    For the choosers that pick a card rather than cast one — a search, a
    scry, a library rearranged. A spell's worth is what a rehearsal of it
    measures on this board; it was the cast scorer's probes on the card's
    text, which went when the cast scorer stopped reading text.
    """
    stamp = (
        id(game), len(game.log), game.turn,
        tuple((seat.life, len(seat.hand), len(seat.battlefield)) for seat in game.players),
    )
    if _TUTOR_SCORES.get("at") != stamp:
        _TUTOR_SCORES.clear()
        _TUTOR_SCORES["at"] = stamp
    key = (player_index, card.name)
    if key not in _TUTOR_SCORES:
        token = _IN_THE_ABSTRACT.set(True)
        try:
            with deliberating():
                _TUTOR_SCORES[key] = _tutor_score(game, player_index, card)
        finally:
            _IN_THE_ABSTRACT.reset(token)
    return _TUTOR_SCORES[key]


def _tutor_score(game: Game, player_index: int, card: CardDefinition) -> float:
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


def _stack_response_bonus(game: Game, caster_index: int) -> float:
    """What answering the object on top of the stack adds to an instant's
    score, beyond what the instant was measured to do.

    One rule, and it is about whose object that is: a seat does not spend a
    reaction on its own spell. Everything this used to add — six for a
    counterspell that could name the top spell, more for the words "prevent",
    "gain … life" and "destroy" in the card's text — was a guess at what the
    response would be worth, and the candidate's score is now that worth,
    measured (`_combat_instant_candidate`).
    """
    if not game.stack:
        return 0.0
    if game.stack[-1].caster_index == caster_index:
        return -0.5
    return 0.0


def _is_better_cast(candidate: CastAction, current: CastAction | None) -> bool:
    if current is None:
        return True
    if candidate.score > current.score:
        return True
    if candidate.score < current.score:
        return False
    # Equal scores: the hand before any other zone, then the lower slot. A
    # card and its own copy in the graveyard score alike — the score is what
    # the spell does — and the hand's is the cheaper cast (Firebolt's {R}
    # against its {4}{R} flashback), which leaves the other for the lands that
    # are left. Two hand cards compare as they always did.
    if (candidate.from_zone == "hand") != (current.from_zone == "hand"):
        return candidate.from_zone == "hand"
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
    if cast_prohibition(
        game, caster_index, card, from_zone=_cast_zone(card)
    ) is not None:
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

    program = compile_card_oracle(card)
    # The steps of the mode being weighed (`_announced_steps`): these arms are
    # keyed on the *first* kind they meet, and for a modal card that was
    # always mode 0's.
    for instruction in _announced_steps(card, program):
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
                # "Is there something on the opponent's board this may
                # destroy" — the engine's own list of what the announcement
                # may name, filtered to that seat. It was a matcher of this
                # arm's own over two payload keys, comparing the permanent's
                # *printed, collapsed* type word to the filter: an artifact
                # creature is "creature", so Shatter was never cast at one, and
                # a filter naming several types ("Destroy target artifact or
                # land", Pillage; Creeping Mold, Fissure, Eliminate) is a list,
                # which equals no word at all — those spells were never cast.
                return _a_legal_target_is_controlled_by(
                    game, caster_index, card, choose_attack_target(game, caster_index)
                )

        if kind in {"pump_target_creature_until_eot", "grant_regeneration_to_target_creature",
                    "grant_target_flying_until_eot", "berserk_pump"}:
            # A gift wants one of the caster's own creatures to land on — and
            # a pump is not always a gift. "Target creature gets -2/-2 until
            # end of turn" is this same kind, so the arm asked a seat casting
            # a kill spell whether it had a creature *of its own* to shrink,
            # and held the card until it did. Which board is the effect's own
            # reading (`spell_target_side`: the sign of the change), and what
            # is on it is the engine's list.
            wanted = (
                choose_attack_target(game, caster_index)
                if spell_target_side(card) == "opponent" else caster_index
            )
            return _a_legal_target_is_controlled_by(game, caster_index, card, wanted)

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
    mode_index = _announced_mode(card)
    if game.no_legal_cast_target_refusal(
        caster_index, card, optional_cost_payments=announced,
        mode_index=mode_index, from_zone=_cast_zone(card),
    ) is not None:
        return True
    # What follows is **preference and remainder**, and is deliberately wider
    # than the rule: the shape the engine's predicate leaves to another gate
    # (a target on the stack), and the casts that are legal and buy nothing —
    # "X target creatures" at an X of zero, "any number of target" at none, a
    # *source of your choice* with no source in play. Declining those is this
    # policy's business; refusing them is not the engine's.
    program = compile_card_oracle(card)
    # **A modal spell is asked about the mode being weighed** (`_announced
    # _mode`), and so is every question above and below. It was asked about
    # mode 0, because this policy named no mode and that is what the engine
    # resolves a cast naming none as: Blue Elemental Blast's first bullet
    # counters a red spell, so with an empty stack the whole card was
    # uncastable to an AI seat while its second bullet had a red permanent to
    # destroy. A mode whose target is **on the stack** is not this function's
    # (`_NOT_OBJECT_SPECS`): the modes weighed are the engine's own list of
    # the announceable ones, and that list has asked the stack gate already.
    spec = _cast_spec(card, program)
    if spec is None or spec.get("kind") in ("none", "modal") or spec_roles(spec):
        # No spec, no target; roles are `_choose_role_targets`' question and it
        # already declines an unfillable chain.
        return False
    if _targets_are_optional(_announced_steps(card, program)):
        # "Up to one target" is castable with none (CR 601.2c).
        return False
    return not game._enumerate_targets(
        caster_index, card, spec, for_cast=True, optional_cost_payments=announced,
        mode_index=mode_index,
    )


def _a_legal_target_is_controlled_by(
    game: Game, caster_index: int, card: CardDefinition, seat: int
) -> bool:
    """Whether the candidate being built could name a permanent *seat*
    controls: the engine's own enumeration for the announcement (the list a
    human's picker is built from), read for one battlefield.

    For a preference arm that wants its target on a particular board. True
    when the announcement names roles instead — `_choose_role_targets` picks a
    side per role and declines an unfillable chain — or nothing a picker lists.
    """
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec_roles(spec):
        return True
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    return any(
        entry.get("kind") == "permanent" and entry.get("seat") == seat
        for entry in legal
    )


def _targets_are_optional(instructions) -> bool:
    """True when every ``targets`` quantifier *instructions* carry is an
    "up to". The caller hands the steps of the candidate being built
    (`_announced_steps`), so a modal spell is asked about the mode weighed."""
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

    for instruction in instructions:
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

    And one that is not a policy at all: **an "each of up to N targets" list
    is filled** (Shower of Coals). Nothing there is divided — every target
    takes the whole printed amount (``divided_damage.EACH``) — so the reason
    damage concentrates does not apply to it, and a slot left unnamed is
    damage the card printed and nobody received.
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
    # ...and its mode (`_announced_mode`): a division printed in one bullet is
    # a division only of a cast that chose it, and the game's spec for a modal
    # card asked with no mode is "modal" — no division to read at all.
    mode_index = _announced_mode(card)
    shape = divided_shape(
        program,
        instructions_as_announced(card, program, offers or {}, mode_index=mode_index),
    )
    if shape is None:
        return None
    spec = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers, mode_index=mode_index,
        from_zone=_cast_zone(card),
    )
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
    if exact is not None and len(shape.slot_sides) == exact:
        # The targets are not interchangeable (Captain's Maneuver: the first is
        # spared, the second takes the damage), so each is taken from the board
        # its own slot names — `ai_valuation.DividedShape.slot_sides`. Which
        # candidate on that board is this module's weight, and it is the one
        # every divided spell has: the first the enumeration offers, a player's
        # face where the printed noun admits one. So the caster's own face is
        # what is spared and an opponent's is where the damage goes.
        picked = _divided_slot_picks(candidates, shape.slot_sides, caster_index)
        return [] if picked is None else [
            (entry["seat"], entry.get("index")) for entry in picked
        ]
    if exact is not None:
        return (
            [] if len(wanted) < exact
            else [(entry["seat"], entry.get("index")) for entry in wanted[:exact]]
        )
    ceiling = spec.get("max_targets")
    if spec.get("division") == EACH and isinstance(ceiling, int):
        # "…deals 2 damage to **each of up to three targets**" (Shower of
        # Coals, the pool's first EACH list under a ceiling rather than a
        # printed count — Firestorm and Magma Burst print how many, and are
        # answered by `exact` above). It reached the threshold arm below and
        # named one target of its three, which is a third of the card: a share
        # is measured against a toughness only where there is a share.
        return [
            (entry["seat"], entry.get("index")) for entry in wanted[:max(1, ceiling)]
        ]
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


def _divided_slot_picks(candidates, slot_sides, caster_index: int):
    """One enumerated target per printed slot, each from the board its slot
    names ("you" the caster's, "opponent" anybody else's, None either), no
    target twice — or None when some slot has nothing to name, which is no
    legal announcement (CR 601.2c) rather than one to fill from the wrong
    board."""
    picked: list = []
    for side in slot_sides:
        offered = [
            entry for entry in candidates
            if not any(entry is taken for taken in picked)
            and (
                side is None
                or (_divided_candidate_seat(entry) == caster_index) == (side == "you")
            )
        ]
        if not offered:
            return None
        picked.append(offered[0])
    return picked


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
    # ...and under the mode being weighed (`_announced_mode`): asked with no
    # mode the game answers "modal" and walks no chain, which is why Reign of
    # Chaos — two bullets, both of them roles — was never cast by an AI seat.
    options = game.cast_target_spec(
        caster_index, card, optional_cost_payments=offers,
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
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
    #
    # A **stack** role's answer ("Counter target spell and … deals 3 damage to
    # target creature", Suffocating Blast) is held the same way and for the
    # same reason: the spell travels on ``target_stack_index``, the one field
    # a cast names a stack object on.
    off_board = ("player", "stack")
    ids = [
        None if pick.get("kind") in off_board
        else game.permanent_id_of(game.permanent_at(pick["seat"], pick["index"]))
        for pick in picks
    ]
    if not all(value is None or isinstance(value, int) for value in ids):
        return ()
    seats = [pick["seat"] for pick in picks if pick.get("kind") == "player"]
    spells = [
        len(game.stack) - 1 - pick["stack_index"]
        for pick in picks if pick.get("kind") == "stack"
    ]
    if len(seats) > 1 or len(spells) > 1:
        # Two player roles would be one seat sent twice, which the resolution
        # refuses on the other side of the same fact — and two stack roles one
        # spell. Skipped rather than cast.
        return ()
    # The seat is still sent for every other roles spell too, because every cast
    # carries one; the *ids* are what address the two boards a roles spell may
    # span (CR 400.7).
    seat = seats[0] if seats else next(
        (pick["seat"] for pick in picks if pick.get("kind") not in off_board),
        caster_index,
    )
    indices = [
        None if pick.get("kind") in off_board else pick["index"] for pick in picks
    ]
    return seat, indices, ids, (spells[0] if spells else None)


def _names_x_targets(card: CardDefinition) -> bool:
    """Whether *card*'s cast names "**X** target …" for an X its caster
    announces — the spec's ``x_targets`` on a slot printed as an exact count
    (Winter Blast), not "up to X" (Reap, whose X is counted off the board and
    answered by ``Game.announced_cast_x``)."""
    program = compile_card_oracle(card)
    slot = cast_target_slot(
        card, program, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
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
    elif options[0].get("kind") == "stack":
        # A spell role is answered with a spell somebody else controls: every
        # step in the pool that spends one counters it, and a seat that
        # countered its own spell to deal the damage beside it has paid for
        # two cards to get half of one. Topmost first, the engine's own order.
        depth = len(game.stack)
        candidates = [
            option for option in options
            if 0 <= depth - 1 - option["stack_index"] < depth
            and game.stack[depth - 1 - option["stack_index"]].caster_index
            != caster_index
        ]
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
        game.announced_cast_x(caster_index, card, mode_index=_announced_mode(card))
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
        caster_index, card, optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card), from_zone=_cast_zone(card),
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

    if sized_by_x or announced is not None:
        # **…and "up to X target creatures, where X is one plus the number of
        # cards named Aether Burst in all graveyards"** (`announced`): the same
        # one printed instance of the word, with its X counted off the board
        # instead of paid for. It fell through to the several-slot default at
        # the bottom of this function — "the caster's own board, because every
        # card carrying the template gives a benefit per target" — which for
        # this one is a bounce: the seat returned its own creatures to its own
        # hand. (Reap, the other card on this branch, names cards in its
        # caster's graveyard and has no second board to land on.)
        #
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
        program,
        instructions_as_announced(
            card, program, _OFFERS_ANNOUNCED.get() or {},
            mode_index=_announced_mode(card),
        ),
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
    game: Game, caster_index: int, card: CardDefinition, preferred_seat: int,
    *, x_value: int | None = None,
):
    """Name the one permanent a one-object-target spell is cast at:
    ``(seat, index, [permanent_id])``, ``()`` when the side the effect wants
    holds no legal target, or None when *card* is not such a spell.

    **Which permanent is the one the cast does most at.** Every legal target
    on the side the effect wants is a different cast, so each is rehearsed
    (`_best_target`) and the largest swing named: the creature a -2/-2 kills
    rather than the one it only shrinks, the dearest thing a destroy may
    take, the body a pump does most on. This named the first legal permanent
    in battlefield order — whichever the seat happened to play first.

    A spell that may name **a player or a permanent** ("any target") is
    weighed the same way against the seat it would otherwise be aimed at:
    three damage is worth a creature it kills more often than it is worth
    three life (`_better_than_the_seat`).

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
    # "Target spell **or permanent**" (the five Laces): on a battlefield the
    # answer is a permanent like any other, and a cast that named only a seat
    # left the handler to find one on it — the caster's own, which with
    # nothing of the caster's there was a cast that did nothing.
    spell_or_permanent = isinstance(spec, dict) and spec.get("kind") == "spell_or_permanent"
    if (
        not isinstance(spec, dict)
        or (spec.get("kind") in _NOT_OBJECT_SPECS and not spell_or_permanent)
        or spec_roles(spec)
        or _targets_are_optional(_announced_steps(card, program))
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
        # ...and the mode (CR 601.2b): the probe reads the chosen mode's own
        # instruction, so a list asked with none is mode 0's list.
        mode_index=_announced_mode(card),
    )
    if spell_or_permanent:
        # The spells on offer are `_guarded_stack_target`'s and the engine's.
        legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if not legal:
        return None
    # A seat among the answers: "any target", "target player or planeswalker".
    names_a_seat = any(entry.get("kind") != "permanent" for entry in legal)
    legal = [entry for entry in legal if entry.get("kind") == "permanent"]
    if names_a_seat:
        if not legal or card.primary_type not in SPELL_TYPES:
            return None
        return _better_than_the_seat(
            game, caster_index, card, legal, preferred_seat, x_value
        )
    if spell_denies_its_own_target(card):
        # "Return target permanent you control to its owner's hand"
        # (Scapegoat): a denial the printed words aim at the caster's own
        # board, which this policy has no rescue to time it for.
        return ()
    if spec.get("source_of_choice"):
        return _choose_damage_source(game, caster_index, legal)
    # "Destroy target permanent **if it's blue**" (Pyroblast): every permanent
    # is a legal target and only a blue one is destroyed. Named from the ones
    # the effect would reach, and not cast when it would reach none and do
    # nothing else (`_reached_by_the_effect`).
    legal = _reached_by_the_effect(game, caster_index, card, legal)
    if not legal:
        return ()
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
    candidates = _target_candidates(game, legal, order)
    if not candidates:
        return ()
    return _best_target(game, caster_index, card, candidates, x_value)


def _target_candidates(game: Game, legal: list[dict], order: list[int]) -> list[tuple]:
    """*legal* — one-object candidates off the engine's own list — as
    ``(seat, index, [permanent_id])``, the seats in *order* and each seat's
    permanents as the enumeration lists them."""
    candidates: list[tuple] = []
    for seat in order:
        for entry in legal:
            if entry.get("seat") != seat:
                continue
            permanent_id = game.permanent_id_of(game.permanent_at(seat, entry["index"]))
            if isinstance(permanent_id, int):
                candidates.append((seat, entry["index"], [permanent_id]))
    return candidates


def _distinct_targets(game: Game, candidates: list[tuple]) -> list[tuple]:
    """*candidates* with look-alikes dropped — two untapped Forests are one
    question — and at most `TARGETS_WEIGHED` of them kept: the first in
    order, then the dearest (``ai_valuation.permanent_worth``) and the
    frailest, since the target a spell does most at is as often the one it
    can just kill as the one worth most."""
    seen: set = set()
    distinct: list[tuple] = []
    for candidate in candidates:
        permanent = game.permanent_by_id(candidate[2][0])
        if permanent is None:
            continue
        creature = bool(permanent.is_creature)
        look = (
            candidate[0], permanent.card.name, permanent.tapped,
            creature and permanent.effective_power,
            creature and permanent.effective_toughness,
            permanent.damage_marked, permanent.attacking, permanent.blocked,
            tuple(sorted(permanent.metadata)),
        )
        if look in seen:
            continue
        seen.add(look)
        distinct.append((candidate, permanent, creature))
    if len(distinct) <= TARGETS_WEIGHED:
        return [candidate for candidate, _permanent, _creature in distinct]
    kept: list[int] = [0]
    by_worth = sorted(
        range(len(distinct)),
        key=lambda slot: (-permanent_worth(distinct[slot][1]), slot),
    )
    by_frailty = sorted(
        (slot for slot in range(len(distinct)) if distinct[slot][2]),
        key=lambda slot: (distinct[slot][1].effective_toughness, slot),
    )
    for dear, frail in zip(by_worth, by_frailty + by_worth):
        for slot in (dear, frail):
            if slot not in kept and len(kept) < TARGETS_WEIGHED:
                kept.append(slot)
    return [distinct[slot][0] for slot in sorted(kept)]


def _best_target(
    game: Game, caster_index: int, card: CardDefinition, candidates: list[tuple],
    x_value: int | None,
):
    """The candidate whose cast does most (``ai_valuation.rehearse``), the
    earlier one on a tie — or ``()`` when every one of them is a cast the
    engine refuses or that changes nothing.

    One candidate is not rehearsed here: there is nothing to choose, and the
    cast built from it is rehearsed where it is scored. Neither is anything
    when no rehearsal can be run; the first candidate is then the answer it
    always was.
    """
    distinct = _distinct_targets(game, candidates)
    if len(distinct) <= 1:
        return distinct[0] if distinct else candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    for seat, index, ids in distinct:
        # "Destroy target artifact with mana value X": the target fixes X.
        implied = (
            game._x_implied_by_target(card, seat, index, None)
            if x_value is not None else None
        )
        announcement = _announcement(
            card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value if implied is None else implied,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else distinct[0]


def _better_than_the_seat(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict],
    preferred_seat: int, x_value: int | None,
):
    """For a spell that may name a player **or** a permanent: the permanent
    whose cast is measured to do more than naming the seat alone, or None to
    keep the seat.

    The permanents weighed are on the side the seat choice already says the
    effect is for — an opponent's when the seat is one (damage), the
    caster's own when it is the caster's (a shield).
    """
    hostile = preferred_seat != caster_index
    seats = [
        seat for seat in range(len(game.players))
        if (seat != caster_index) == hostile
    ]
    order = [preferred_seat] + [seat for seat in seats if seat != preferred_seat]
    candidates = _distinct_targets(game, _target_candidates(game, legal, order))
    if not candidates:
        return None
    at_seat = _announcement(
        card, target=preferred_seat, caster=caster_index, x_value=x_value,
    )
    at_the_seat = _weighed_through_the_fight(
        game, caster_index, card, at_seat,
        _rehearse_announcement(game, caster_index, card, at_seat),
    )
    if at_the_seat is None:
        return None
    if (
        at_the_seat.accepted and at_the_seat.fleeting
        and game.current_turn_phase != "combat"
        and not (
            at_the_seat.combat_ahead
            and has_a_creature_to_fight_with(game, caster_index)
        )
    ):
        # Aimed at the player it is over with the turn, and with no combat
        # still to come this reading has no damage in it for it to stop or to
        # add to: what may name "any target" is damage, which a player keeps,
        # or a shield — and a shield with nothing coming is as much nothing
        # on a creature as on its controller. So the permanents are not each
        # rehearsed to learn that, and the seat stands. Before the caster's
        # own fight they are: the 2/2 about to trade is what a shield is for.
        return None
    best = None
    best_swing = (
        at_the_seat.swing
        if at_the_seat.accepted and not _leaves_nothing(at_the_seat) else None
    )
    for seat, index, ids in candidates:
        announcement = _announcement(
            card, target=seat, caster=caster_index, permanent_index=index,
            permanent_ids=ids, x_value=x_value,
        )
        rehearsal = _weighed_through_the_fight(
            game, caster_index, card, announcement,
            _rehearse_announcement(game, caster_index, card, announcement),
        )
        if (
            rehearsal is None or not rehearsal.accepted or not rehearsal.changed
            or _leaves_nothing(rehearsal)
        ):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = (seat, index, ids), rehearsal.swing
    return best


#: `if_then` conditions that are a property of **the permanent the spell
#: targets** — the clause is on the effect, not on the target phrase, so the
#: engine's picker rightly offers every permanent (CR 608.2b reads the printed
#: target phrase, and Pyroblast's says no colour) and a target that fails it
#: is one the spell does nothing to.
#:
#: Named, where "evaluate whatever condition is there" would be shorter,
#: because a condition about something *else* (was this spell kicked, did a
#: creature die this turn) cannot be asked before the cast exists, and
#: answering it early would withhold spells for a reason that is not true. A
#: kind left off costs the old behaviour and nothing more.
_TARGET_GUARDS = frozenset({
    "target_is_color", "target_shares_most_common_color",
    # "Counter target spell **if it was kicked**" (Ertai's Trickery): CR
    # 702.33d's fact about the *targeted* spell, which is on the stack to be
    # asked. Not `was_kicked`, which is about this one.
    "target_was_kicked",
    # "Destroy target nonland permanent **if another permanent with the same
    # name is on the battlefield**" (Winnow) — `_is_a_target_guard` admits the
    # kind only in that spelling; "a card with the same name as that spell"
    # (Bazaar of Wonders) is about a spell some trigger fired on.
    "same_named_object",
    # "Counter target spell if it shares a color with a creature you control."
    # (Jaded Response.) A property of the spell the cast names, read against
    # the caster's own board as it stands — askable before the cast exists.
    "target_shares_color_with_matching",
})


def _is_a_target_guard(condition) -> bool:
    """Whether *condition* is a `_TARGET_GUARDS` clause about the object the
    spell targets."""
    if not isinstance(condition, dict) or condition.get("kind") not in _TARGET_GUARDS:
        return False
    if condition.get("kind") == "same_named_object":
        return condition.get("same_name_as") == "target"
    return True


def _reached_by_the_effect(
    game: Game, caster_index: int, card: CardDefinition, legal: list[dict]
) -> list[dict]:
    """The entries of *legal* — one-object candidates, off the engine's own
    list — that the candidate being built would actually **do something to**.

    All of them, for every spell whose effect is not guarded by a condition on
    its target (`_TARGET_GUARDS`). For one that is: the permanents the guard
    holds for, asked of the engine's own evaluator
    (`control_flow.evaluate_condition`) with that permanent as the target — so
    the policy and the resolution cannot disagree about what "if it's blue"
    means, layers and all. When the guard holds for none of them the answer
    is empty only if the guarded step is the whole spell; where the spell
    does something else as well ("…Draw a card at the beginning of the next
    turn's upkeep", Soul Rend) the candidates stand, because the cast is not
    nothing.

    This surfaced with the mode chooser and was true before it: an AI seat
    holding Hydroblast or Pyroblast in its main phase now weighs "Destroy
    target permanent if it's red", and across ten seeded Ice Age games it
    cast that at ten permanents of the wrong colour — a legal cast and a card
    spent on nothing. Soul Rend and Barrin's Unmaking, which print no mode,
    were aimed the same way all along.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=False)
    if not guards:
        return legal

    def reached(entry: dict) -> bool:
        permanent = game.permanent_at(entry["seat"], entry["index"])
        if permanent is None:
            return False
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[entry["seat"]],
            card=card,
            target_permanent_index=entry["index"],
            target_permanent_id=game.permanent_id_of(permanent),
        )
        return any(evaluate_condition(game, context, guard) for guard in guards)

    kept = [entry for entry in legal if reached(entry)]
    if kept or whole_spell:
        return kept
    return legal


def _target_guards(card: CardDefinition, *, on_a_spell: bool) -> "tuple[list[dict], bool]":
    """``(conditions, whole_spell)``: the `_TARGET_GUARDS` conditions that
    guard the candidate being built's steps, for a target on the stack
    (*on_a_spell*) or on the battlefield — and whether those guarded steps
    are **everything** the spell does, so that a target every guard fails for
    is a cast that does nothing at all.

    A guard with an ``else`` arm is not one: the spell does something either
    way, and which is better is a valuation this does not make.
    """
    steps = _announced_steps(card, compile_card_oracle(card))
    guards = [
        condition
        for step in steps
        if step.kind == "if_then"
        and not (step.payload or {}).get("else")
        and _is_a_target_guard(condition := (step.payload or {}).get("condition"))
        and (condition.get("target") == "spell") == on_a_spell
    ]
    return guards, bool(guards) and len(guards) == len(steps)


def _guarded_stack_target(game: Game, caster_index: int, card: CardDefinition):
    """The spell on the stack a cast whose effect is guarded by a condition
    on **that spell** should name — its engine (bottom-first) stack index;
    ``()`` when the guard holds for no spell the cast may name and the guarded
    step is the whole spell; None for every other cast, which names nothing
    and is answered by the engine as it always was.

    `_reached_by_the_effect` for the other zone a target can be in. "Counter
    target spell **if it's blue**" (Pyroblast, Hydroblast, Burnout) may be
    announced at any spell, and the web AI's priority response announced it at
    whatever was on top: a Pyroblast spent on a green creature spell, on the
    tree before the mode chooser and after it. The topmost spell the guard
    holds for, off the engine's own list of what the announcement may name.
    """
    from .game_types import OracleExecutionContext
    from .handlers.control_flow import evaluate_condition

    guards, whole_spell = _target_guards(card, on_a_spell=True)
    if not guards:
        return None
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    reached: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if not 0 <= index < depth:
            continue
        item = game.stack[index]
        context = OracleExecutionContext(
            caster=game.players[caster_index],
            target=game.players[item.caster_index],
            card=card,
            stack_target=item,
        )
        if any(evaluate_condition(game, context, guard) for guard in guards):
            reached.append(index)
    if reached:
        return max(reached)
    return () if whole_spell else None


def _chosen_stack_target(
    game: Game, caster_index: int, card: CardDefinition, target_seat: int,
):
    """Which spell on the stack a cast whose target **is** a spell names, where
    `_guarded_stack_target` has no guard to choose by: its engine
    (bottom-first) stack index, ``()`` when no candidate is worth casting at,
    or None for a cast that targets no spell.

    **Each candidate is a different cast, so each is rehearsed** and the
    largest swing named, as `_best_target` does for a permanent. With one
    candidate there is nothing to choose and it is named as it is. This left
    the choice to the engine's default for a bare announcement — the first
    entry of the picker's list, with the caster's own seat's first — which
    was harmless while a seat answered only one spell, and became a
    misplay the day it could answer a response: a seat whose spell was met
    by a Confound cast Gainsay ("Counter target blue spell") at **its own**
    blue Aura beneath it, and the Confound fizzled over a spell that was
    gone anyway.
    """
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") != "stack":
        return None
    depth = len(game.stack)
    candidates: list[int] = []
    for entry in game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    ):
        top_first = entry.get("stack_index")
        if entry.get("kind") != "stack" or not isinstance(top_first, int):
            continue
        index = depth - 1 - top_first
        if 0 <= index < depth and index not in candidates:
            candidates.append(index)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    best = None
    best_swing = None
    rehearsed = False
    # Topmost first, so a tie names the spell most recently cast.
    for index in sorted(candidates, reverse=True):
        announcement = {
            **_announcement(card, target=target_seat, caster=caster_index),
            "target_stack_index": index,
        }
        rehearsal = _rehearse_announcement(game, caster_index, card, announcement)
        if rehearsal is None:
            continue
        rehearsed = True
        if not rehearsal.accepted or not rehearsal.changed or _leaves_nothing(rehearsal):
            continue
        if best_swing is None or rehearsal.swing > best_swing:
            best, best_swing = index, rehearsal.swing
    if best is not None:
        return best
    return () if rehearsed else max(candidates)


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
    # program says (`ai_valuation.spell_target_side`). Asked first, and it is
    # an answer in its own right: the side is a claim about what the effect
    # does to its target, never about which card printed it, and it costs no
    # rehearsal. "Target creature can't attack or block this turn" is aimed
    # across the table because the kind hampers what it names.
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
    # No side to read: a spell that names a **player** ("target player draws
    # three cards", "…loses 4 life and you gain 4 life", "…discards a card").
    # Each seat the announcement may name is weighed (`_score_spell_target`)
    # and the best one taken. This was a set of
    # probes on the card's text — "draw" for the caster, "damage" for an
    # opponent — and a sentence outside them tied, which is how the caster
    # came to discard to its own Mind Rot.
    seats = _seats_the_cast_may_name(game, caster_index, card)
    if len(seats) < 2:
        return seats[0] if seats else caster_index
    # Where the seats measure alike, the one the effect's family says
    # (`ai_valuation.spell_seat_side`): the opponent's, for anything that is
    # not a gift.
    favoured = (
        caster_index if spell_seat_side(card) == "you"
        else choose_attack_target(game, caster_index)
    )
    best_seat, best_score = favoured, None
    for seat in sorted(seats, key=lambda seat: (seat != favoured, seat)):
        score = _score_spell_target(card, caster_index, seat, game, x_value)
        if best_score is None or score > best_score:
            best_seat, best_score = seat, score
    return best_seat


#: Cast specs whose announcement names a **seat**: a player, or a pile of
#: cards that is one player's (a graveyard, a hand).
_SEAT_NAMING_SPECS = frozenset({
    "player", "player_or_planeswalker", "any", "opponent",
    "graveyard_creature", "hand_card",
})


def _seats_the_cast_may_name(
    game: Game, caster_index: int, card: CardDefinition
) -> list[int]:
    """The seats a cast of the candidate being built may name, off the
    engine's own enumeration — empty for a card whose announcement names no
    seat (a permanent, an untargeted spell, one aimed at an object).

    For a spell only: a permanent's instruction list mirrors its *abilities*
    (``ai_valuation.SPELL_TYPES``), and the seat a creature spell carries is
    its entry trigger's, which `_choose_target_for_spell` reads before this.
    """
    if card.primary_type not in SPELL_TYPES:
        return []
    spec = _cast_spec(card, compile_card_oracle(card))
    if not isinstance(spec, dict) or spec.get("kind") not in _SEAT_NAMING_SPECS:
        return []
    if spec_roles(spec):
        return []
    legal = game._enumerate_targets(
        caster_index, card, spec, for_cast=True,
        optional_cost_payments=_OFFERS_ANNOUNCED.get(),
        mode_index=_announced_mode(card),
    )
    seats = {
        int(entry["seat"]) for entry in legal
        if entry.get("kind") != "permanent" and isinstance(entry.get("seat"), int)
    }
    return sorted(seats)


def _score_spell_target(
    card: CardDefinition,
    caster_index: int,
    target_index: int,
    game: Game,
    x_value: int | None = None,
) -> float:
    """What casting *card* at seat *target_index* is worth to its caster: the
    swing a rehearsal of that cast measures (``ai_valuation.rehearse``), in
    the standing's own units.

    A seat-only announcement — the engine picks the object for a spell that
    names one, as it does for any cast that names none. A cast the engine
    refuses there scores far below any it accepts, and one that changes
    nothing scores nothing.

    This was eight probes on the card's text and three on its program: the
    word "draw" was worth five, "gain" and "life" a share of the life lost,
    "target opponent" three, a destroy two plus one and a half per permanent
    the seat happened to control. A sentence outside them scored zero for
    both seats.
    """
    if card.primary_type not in SPELL_TYPES:
        # A permanent: the seat is its own controller's unless an entry
        # trigger says otherwise, which the caller has already read.
        return 1.0 if target_index == caster_index else 0.0
    rehearsal = _rehearse_announcement(
        game, caster_index, card,
        _announcement(card, target=target_index, caster=caster_index, x_value=x_value),
    )
    if rehearsal is None:
        return 0.0
    if not rehearsal.accepted:
        return -SWING_CAP
    return max(-SWING_CAP, min(SWING_CAP, rehearsal.swing))


def _score_cast(
    game: Game, caster_index: int, card: CardDefinition, target_index: int,
    x_value: int | None, rehearsal: Rehearsal | None = None,
) -> float:
    """What a cast is worth against the other casts the seat could make.

    **A spell is worth what it does**: `SPELL_BASE_SCORE` and the swing its
    rehearsal measured (*rehearsal*; a spell nobody could rehearse scores the
    base alone). **A permanent is worth what it is**: its type and, for a
    creature, its printed body — weights, and tuning like every other number
    in this module.
    """
    caster = game.players[caster_index]

    if card.primary_type == "land":
        untapped_lands = sum(
            1
            for perm in game.controlled_by(caster)
            if perm.card.primary_type == "land" and not perm.tapped
        )
        return 1.0 if untapped_lands < 4 else 0.2

    if card.primary_type in SPELL_TYPES:
        score = SPELL_BASE_SCORE
        if rehearsal is not None and rehearsal.accepted:
            score += max(-SWING_CAP, min(SWING_CAP, rehearsal.swing))
        elif rehearsal is None:
            # Nobody has measured it: a card being weighed where it lies (a
            # search's pick, the top of a library) rather than as a cast.
            score += _score_spell_target(card, caster_index, target_index, game, x_value)
    else:
        score = 1.5
        if card.primary_type == "creature":
            score += 1.2
            score += _creature_stat(card, "power") * 0.7
            score += _creature_stat(card, "toughness") * 0.4
            if target_index == caster_index:
                score += 1.0
        if card.primary_type in {"artifact", "enchantment"}:
            score += 0.8
        if x_value is not None:
            score += min(4.0, x_value * 0.6)

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
        game, player_index, penalty_steps, self_recipients, source, context
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


def offer_buys_own_drawback(game: Game, player_index: int, entry: dict) -> bool:
    """Whether a seat nobody asks would, by taking this offer, buy the
    drawback its **own** permanent prints.

    "Whenever this creature attacks or blocks, any player may exile a card
    from their graveyard. If a player does, this creature assigns no combat
    damage this turn." (Carrion Rats.) The offer goes to every seat in turn
    and what it buys is a loss for whoever controls the source — so that seat
    declines, whatever the price, and every other seat is left to the standing
    policy. Exiling a card from one's own graveyard reads as no payment
    (``offered_action_is_a_payment``), so before this the attacker took the
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


#: The printed actors that put one offer to every seat of a set
#: (``handlers/control_flow._offered_seats``) — "any player may …" reaches the
#: AST as ``each_player``.
_SEAT_SET_OFFERS = frozenset({"each_player", "each_opponent"})


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
    if getattr(context, "caster", None) is not game.players[player_index]:
        return False
    if game.active_player_index != player_index:
        return True
    return not _hand_could_use_mana(game, player_index)


def _hand_could_use_mana(game: Game, player_index: int) -> bool:
    """Whether a spell in *player_index*'s hand could be cast with the mana
    its board makes — the question a gift or a toll paid on the seat's **own**
    turn asks ("lands nothing in its hand could use").

    Not `_cast_candidate`, which this asked until the policy began to
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
    # A gift names its own seat: "target player gains 3 life", "target player
    # draws a card", "prevent the next 1 damage that would be dealt to any
    # target". *Which* effects those are is `ai_valuation.ability_seat_side`'s
    # reading of the compiled program — this line used to name three kinds, two
    # of which nothing compiles, so a life gain and every shield went to an
    # opponent.
    if ability_seat_side(instruction) == "you":
        return caster_index
    # "deal_damage"/"destroy_target"/etc., and the fallback for any other
    # proactive effect: target an opponent (MVP heuristic, see
    # choose_attack_target — lowest life among living opponents).
    return choose_attack_target(game, caster_index)


def _extract_damage(card: CardDefinition) -> int:
    program = compile_card_oracle(card)
    for instruction in _announced_steps(card, program):
        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount")
            if isinstance(amount, int):
                return amount
    match = re.search(r"deals? (\d+) damage", spell_text(card))
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

    **What is charged in the mana cost's place** is the permission's, when
    the cast being weighed is made under one (`_charged_in_place_of_mana_cost`):
    a flashback cost (CR 702.34a), or nothing for a waiver. CR 118.9d then
    applies the same increases and reductions to *that* total — "start with
    the mana cost or alternative cost you're paying, add any cost increases,
    then apply any cost reductions" — which is the order below and the one
    ``_cast_onto_stack`` pays in.
    """
    seat = next((i for i, seated in enumerate(game.players) if seated is player), 0)
    mana_cost, keyword = _charged_in_place_of_mana_cost(card)
    tax, _names = spell_cost_tax(game, seat, card)
    tax += max(0, extra_generic)
    # The coloured half of the same taxes (Derelor). Asked here too, because the
    # AI prices a spell to decide whether it can cast it — priced without the
    # pip it proposes a cast the rules then refuse, every turn, forever.
    pips, _pip_names = spell_symbol_tax(game, seat, card)
    reduction, _reducers = cost_reduction_for_cast(game, seat, card)
    # "Flashback costs you pay cost {2} less." (Catalyst Stone.) CR 601.2f
    # over the keyword's cost, through the reader the cast path charges with;
    # nothing for a cost that is the price of no keyword.
    more, less, _by = keyword_cost_modifiers(game, seat, keyword)
    if more or less:
        tax += more
        reduction = CostReduction(reduction.generic + less, reduction.colored)
    # The best split of X among the colours the card allows, which is the one
    # the cast path will try first (`casting._x_color_allocations`). The AI is
    # sizing the cost, so it wants the payment that will actually be attempted;
    # a split the cast would not choose prices a different spell.
    allocation = game._x_color_allocations(
        x_spend_colors_from_text(card.oracle_text), max(0, x_value or 0)
    )[0]
    return reduce_cost(
        game._parse_mana_cost(
            mana_cost,
            x_value=x_value,
            extra_generic=tax,
            x_allocation=allocation,
            extra_pips=pips,
        ),
        reduction,
    )


def _charged_in_place_of_mana_cost(card: CardDefinition) -> "tuple[str, str | None]":
    """``(mana symbols, keyword)`` — the run of mana a cast of *card* is
    charged where its mana cost would be, and the keyword that run is the
    price of.

    The card's own mana cost and no keyword for every ordinary cast. Under the
    permission being weighed (`ai_valuation.cast_weighed`), what the cast path
    charges for it: the **required alternative cost's** mana (CR 118.9b;
    ``CastPermission.cost`` — "Flashback {4}{R}"), which may be none where that
    cost is paid in something else; or **nothing** under a waiver ("without
    paying its mana cost", CR 118.9). A permission that names no price — a
    card played out of exile, a graveyard under Yawgmoth's Will — charges the
    mana cost like any cast.

    Read off the permission, never recomputed: the price of a flashback is
    whatever `flashback_permission` / `granted_cost` built, so a flashback
    cost "equal to its mana cost" (Recoup) and a printed one are one reading.
    """
    under = cast_weighed(card)
    if under is None:
        return card.mana_cost, None
    if under.cost is not None:
        return under.cost.mana or "", under.cost.keyword
    if under.waives_mana_cost:
        return "", None
    return card.mana_cost, None


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
        if not cast_announces_x(card, from_zone=_cast_zone(card)):
            return None
        seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), 0
        )
        bound = game._additional_cost_x_ceiling(
            seat, card, from_zone=_cast_zone(card), spell_hand_index=hand_index,
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
        if _pays_x_in_life(card):
            bound = min(bound, max(0, player.life - X_LIFE_RESERVE))
            # A smaller size asked for by `_cast_candidate_sized`, which
            # weighs each one.
            asked = _LIFE_X_ASKED.get()
            if asked is not None and asked[0] is card and 0 < asked[1] < bound:
                return asked[1]
        return bound

    if "{X}" not in _charged_in_place_of_mana_cost(card)[0].upper():
        # CR 107.3b: "If a player is casting a spell that has an {X} in its
        # mana cost, the value of X isn't defined by the text of that spell,
        # and an effect lets that player cast that spell while paying neither
        # its mana cost nor an alternative cost that includes X, then the only
        # legal choice for X is 0." A flashback cost with no X in it, a waiver.
        # The cast path resolves exactly that; the caller does not propose an
        # X of nothing.
        return 0
    max_x = _max_affordable_x(game, player, card, extra_generic)
    return max_x


def _max_affordable_x(
    game: Game, player: PlayerState, card: CardDefinition, extra_generic: int = 0
) -> int:
    # Through the tap planner rather than a summed preview pool: the preview
    # counted each land as one fixed symbol, so a dual or a swapped land could
    # only ever pay for the first colour it listed, and the X it sized was the
    # X a board of single-colour lands would afford.
    # One reading of the board for all sixteen sizes: what the sources make
    # does not depend on the X being priced.
    planner = _PaymentPlanner(game, player)
    for x_value in range(15, -1, -1):
        required = _cost_for(game, player, card, x_value, extra_generic=extra_generic)
        if planner.plan(required) is not None:
            return x_value
    return 0


@dataclass(frozen=True)
class _TapOption:
    """One way one tap of a mana source can come out, as the plan counts it.

    ``units`` is one entry per mana, each the symbols that mana may be — the
    shape `board_payment.TapYield` has and `mana_payment.plan_payment` matches
    over. ``ask`` is the colour an executor asks the source for to get this
    outcome, where the outcome fixes one ("three mana of any one color", as
    {R}); None where the pip the plan assigns decides (`_asked_color`).
    """

    units: "tuple[frozenset[str], ...]"
    ask: "str | None" = None


@dataclass(frozen=True)
class _ManaSource:
    """One permanent a payment plan may tap, with every way its tap comes out."""

    #: Its battlefield slot — what a plan names it by.
    slot: int
    options: "tuple[_TapOption, ...]"
    #: Reached for in this order: 0 a land, 1 a non-land source that only
    #: taps, 2 a source that is sacrificed.
    rank: int
    #: The symbol it makes unasked — what a generic pip is paid with.
    default: str


#: The most ways of tapping the sources that are tried one by one. Past it
#: each source is read as its largest outcome alone (`board_payment` keeps the
#: same bound for the same reason).
_MAX_TAP_COMBINATIONS = 3125

#: The most sacrificed sources one plan may count.
_MAX_SACRIFICED_FOR_MANA = 3

#: A mark every unit carries so the matching counts it toward a generic cost
#: (`mana_payment.plan_payment` spends on generic only a source that makes
#: something). No pip is spelled this way.
_ANY_PIP = "*"


def _unit_pays(player: PlayerState, symbols, reading: str | None = None) -> frozenset[str]:
    """The pips one mana that may be any of *symbols* can pay for *player*.

    CR 609.4's spending permissions, asked per unit the way
    `board_payment.board_can_pay` asks them of the same matching: Chromatic
    Orrery's "as though it were mana of any color" (every unit pays a coloured
    pip, and {C} still wants colourless), a CR 106.6 permission
    (`mana_payment.may_pay_pip` — Celestial Dawn), Sunglasses of Urza's
    white-as-red. *reading* is a one-spell grant being tried (North Star):
    "any_type" or "any_color".
    """
    if reading == "any_type":
        return frozenset(PIP_SYMBOLS) | {"C", _ANY_PIP}
    pays: set[str] = {_ANY_PIP}
    if "C" in symbols:
        pays.add("C")
    if reading == "any_color" or player.spends_mana_as_any_color:
        return frozenset(pays | set(PIP_SYMBOLS))
    if player.mana_spending_is_general:
        permissions = player.mana_spending_permissions
        pays.update(
            pip for pip in PIP_SYMBOLS
            if any(may_pay_pip(permissions, symbol, pip) for symbol in symbols)
        )
        return frozenset(pays)
    pays.update(symbol for symbol in symbols if symbol in PIP_SYMBOLS)
    if player.can_spend_white_as_red and "W" in symbols:
        pays.add("R")
    return frozenset(pays)


def _land_tap_options(game: Game, land: Permanent, purpose) -> "tuple[_TapOption, ...]":
    """Every way one tap of *land* comes out, read off
    `board_payment.land_tap_yields` — **the reading the castable highlight
    takes**, so the card that glows and the card the AI casts are judged on
    one account of what a land makes.

    This planner kept its own (`_land_symbols`, `_land_mana_amount`,
    `_land_mixed_run`), and the two had come apart: Ancient Tomb's "{T}: Add
    {C}{C}. This land deals 2 damage to you." is a two-step effect whose pips
    the amount reader did not open, so the AI counted one mana where the
    highlight counted two (8 of 14,626 land-and-cost pairs), and a land whose
    amount the board decides — Gaea's Cradle — was left out of every plan.

    The outcomes that are **one** mana fold into a single unit offering every
    symbol any of them makes (a painland's {C} and its two colours), which is
    the choice the executor makes with the colour it asks for; a shared colour
    ("two mana of any one color") is one option per colour.
    """
    from .board_payment import land_tap_yields

    singles: set[str] = set()
    options: list[_TapOption] = []
    for found in land_tap_yields(game, land, purpose):
        units = tuple(found.units)
        if found.one_color and len(units) > 1:
            shared = set.intersection(*(set(unit) for unit in units))
            options.extend(
                _TapOption(tuple(frozenset({symbol}) for _ in units), ask=symbol)
                for symbol in _MANA_SYMBOLS if symbol in shared
            )
        elif len(units) == 1:
            singles |= set(units[0])
        elif units:
            options.append(_TapOption(units))
    if singles:
        options.insert(0, _TapOption((frozenset(singles),)))
    return tuple(dict.fromkeys(options))


def _nonland_tap_options(source: _NonlandManaSource) -> "tuple[_TapOption, ...]":
    """`_land_tap_options` for a non-land source: a fixed run of symbols, one
    mana of a choice of symbols, or several of one chosen symbol."""
    if source.run:
        return (_TapOption(tuple(
            frozenset({symbol}) for symbol, count in source.run.items() for _ in range(count)
        )),)
    if source.amount <= 1:
        return (_TapOption((frozenset(source.symbols),)),)
    return tuple(
        _TapOption(tuple(frozenset({symbol}) for _ in range(source.amount)), ask=symbol)
        for symbol in source.symbols
    )


class _PaymentPlanner:
    """`_plan_land_taps` with the board read once.

    What the sources make does not depend on the cost being asked about, and
    a caller sizing an X asks sixteen costs of one board (`_max_affordable_x`).
    """

    def __init__(
        self, game: Game, player: PlayerState, *,
        paying_for: "Permanent | None" = None,
        without: "frozenset[int]" = frozenset(),
    ):
        from .restricted_mana import ACTIVATE, CAST, PaymentPurpose, spendable_restricted_mana

        self.game = game
        self.player = player
        context = _PAYING_FOR.get()
        self.spell = context.spell if context is not None else None
        # What the payment is for decides what restricted mana counts toward
        # it (CR 106.6) — Mishra's Workshop's {C}{C}{C} for an artifact spell
        # and for nothing else. With no purpose none of it counts, which is
        # what this planner assumed of all of it.
        if self.spell is not None:
            purpose = PaymentPurpose(CAST, card=self.spell)
        elif paying_for is not None:
            purpose = PaymentPurpose(ACTIVATE, source=paying_for)
        else:
            purpose = None
        self.purpose = purpose
        held = {symbol: int(player.mana_pool.get(symbol, 0) or 0) for symbol in _MANA_SYMBOLS}
        for symbol, amount in spendable_restricted_mana(player, purpose).items():
            held[symbol] = held.get(symbol, 0) + int(amount)
        #: Mana already floating, one unit each. Spent first: it is there.
        self.floating = [
            frozenset({symbol})
            for symbol in _MANA_SYMBOLS for _ in range(max(0, held.get(symbol, 0)))
        ]
        self.seat = next(
            (i for i, seated in enumerate(game.players) if seated is player), None
        )
        self.sources: list[_ManaSource] = []
        #: Sources that pay by being sacrificed, in board order — counted only
        #: when everything above cannot pay (`plan`).
        self.sacrificed: list[_ManaSource] = []
        if self.seat is None:
            return
        # Only a land the tap seam will make mana from, and only what it will
        # make (`land_tap_yields` asks `land_mana_tap_refusal`, the seam's own
        # gate): an untapped land is not a mana. A storage land with no
        # counter, a Bazaar of Baghdad or a summoning-sick land creature
        # counted as one here, the executor's tap of it made nothing, and the
        # cast it was planned for was refused "insufficient mana" — the same
        # spell every turn, once the simulator enforced costs (5ED: Sand
        # Silos, 14 refusals a run).
        #
        # **Rhystic Cave is the land that must never be here**: "Activate only
        # as an instant" means its mana needs priority (CR 304.5), which
        # nobody has while a cost is being paid, and any player may deny it.
        # The seam's gate reads `_land_mana_abilities`, whose answer for the
        # Cave is "cannot be run inside a payment" — the same reading
        # `mana_payment.taps_for_payment` gives the optional-pay planner.
        #
        # Then the non-land sources (`_nonland_mana_source`: the Moxen, Sol
        # Ring, Llanowar Elves), ranked after every land because a land is the
        # source that costs nothing to tap: a Mana Vault stays tapped, an
        # Elves of Deep Shadow deals its controller a damage, and a creature
        # tapped for mana does not attack.
        #
        # Never the permanent whose own ability is being paid for
        # (*paying_for*): its {T} may be that ability's cost, and one tap
        # cannot pay both. *without* is the slots a caller has already spoken
        # for — the two halves of `_plan_through_a_priced_source` plan against
        # disjoint sources.
        for slot, permanent in enumerate(game.controlled_by(player)):
            if permanent is paying_for or slot in without:
                continue
            if permanent.has_type("land"):
                if permanent.tapped:
                    continue
                options = _land_tap_options(game, permanent, purpose)
                if options:
                    self.sources.append(_ManaSource(
                        slot, options, 0, _land_symbols(game, permanent)[0],
                    ))
                continue
            source = _nonland_mana_source(game, self.seat, permanent, may_sacrifice=True)
            if source is None:
                continue
            entry = _ManaSource(
                slot, _nonland_tap_options(source), 2 if source.sacrifices else 1,
                source.symbols[0],
            )
            if not source.sacrifices:
                self.sources.append(entry)
            elif _may_sacrifice_for(self.spell, permanent):
                self.sacrificed.append(entry)
        # The order the matching reaches for them in: lands before non-lands,
        # and within each the source with the fewest colours to offer first —
        # a Forest pays the {G} and the Taiga beside it is still there for
        # either colour the next spell wants. Board order breaks ties, so a
        # board of basics is planned as it always was.
        self.sources.sort(key=lambda source: (source.rank, self._breadth(source), source.slot))

    def _breadth(self, source: _ManaSource) -> int:
        offered = frozenset().union(*(unit for option in source.options for unit in option.units))
        return len(_unit_pays(self.player, offered) & set(PIP_SYMBOLS))

    def _readings(self) -> "list[str | None]":
        """CR 609.4's one-spell grants (North Star), tried only where the
        ordinary reading cannot pay — the order the payment spends them in."""
        from .restricted_mana import CAST

        readings: "list[str | None]" = [None]
        if self.purpose is not None and self.purpose.kind == CAST:
            for grant in self.player.spend_mana_as_though_grants:
                if int(grant.get("spells", 0)) > 0:
                    readings.append("any_type" if grant.get("any_type") else "any_color")
                    break
        return readings

    def plan(self, required: dict[str, int]) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
        """``(slots, colours)`` in tap order, or None — see `_plan_land_taps`."""
        found = self._plan_with(self.sources, required)
        if found is not None or not self.sacrificed:
            return found
        # **A permanent given up for mana is the last thing reached for**, and
        # as few of them as pay: every plan the lands and the tap-only sources
        # can make has been tried and refused before the first is counted.
        extras = self.sacrificed[:_MAX_SACRIFICED_FOR_MANA]
        for count in range(1, len(extras) + 1):
            for chosen in combinations(extras, count):
                found = self._plan_with([*self.sources, *chosen], required)
                if found is not None:
                    return found
        return None

    def _plan_with(self, sources, required):
        owed = sum(max(0, int(required.get(key, 0) or 0)) for key in (*_MANA_SYMBOLS, "generic"))
        most = len(self.floating) + sum(
            max(len(option.units) for option in source.options) for source in sources
        )
        if most < owed:
            return None
        choices = [source.options for source in sources]
        ways = 1
        for options in choices:
            ways *= len(options)
        if ways > _MAX_TAP_COMBINATIONS:
            choices = [(max(options, key=lambda option: len(option.units)),) for options in choices]
        for reading in self._readings():
            for picked in product(*choices):
                found = self._match(sources, picked, required, reading)
                if found is not None:
                    return found
        return None

    def _match(self, sources, picked, required, reading):
        """The exact matching (`mana_payment.plan_payment`, the one the
        optional-pay planner and the castable highlight ask) over the floating
        mana and every unit *picked* would add; then which sources it used and
        the colour to ask each for."""
        units: list[frozenset[str]] = list(self.floating)
        owner: "list[int | None]" = [None] * len(units)
        for position, option in enumerate(picked):
            for unit in option.units:
                units.append(unit)
                owner.append(position)
        pays = [_unit_pays(self.player, unit, reading) for unit in units]
        payment = plan_payment({}, range(len(units)), required, produces=pays.__getitem__)
        if payment is None:
            return None
        used = sorted(payment.tapped)
        # Which pip each used unit pays. `plan_payment` says which units and
        # not which pip, and the colour to ask a land for is the pip: the
        # matching again, over the units it chose.
        pips = [
            symbol for symbol in COLOR_SYMBOLS
            for _ in range(max(0, int(required.get(symbol, 0) or 0)))
        ]
        assigned = _match_colored(pips, [(index, pays[index]) for index in used]) if pips else {}
        if assigned is None:
            return None
        tapped: dict[int, list] = {}
        for index in used:
            if owner[index] is not None:
                tapped.setdefault(owner[index], [])
        if not tapped:
            return (), ()
        for position in tapped:
            first = owner.index(position)
            tapped[position] = [
                assigned.get(first + offset) for offset in range(len(picked[position].units))
            ]
        # Tap order: the sources paying a coloured pip first, in pip order,
        # then the ones paying generic — the order this plan has always been
        # reported in.
        def pip_rank(position: int) -> int:
            ranks = [COLOR_SYMBOLS.index(pip) for pip in tapped[position] if pip is not None]
            return min(ranks) if ranks else len(COLOR_SYMBOLS)

        order = sorted(tapped, key=lambda position: (pip_rank(position), position))
        return (
            tuple(sources[position].slot for position in order),
            tuple(
                _asked_color(self.player, sources[position], picked[position], tapped[position], reading)
                for position in order
            ),
        )


def _asked_color(
    player: PlayerState, source: _ManaSource, option: _TapOption, unit_pips, reading,
) -> str:
    """The colour an executor asks *source* for, to get *option* with the mana
    the matching assigned (*unit_pips*, one entry per unit; None is a unit
    spent on generic or not spent).

    The option's own colour where it fixes one. Otherwise the first unit that
    offers a choice decides: the symbol **it** can be that pays the pip it was
    given — under Sunglasses of Urza a Plains pays {R} and is still asked for
    {W} — and for a unit spent on generic, what the source makes unasked (a
    painland's painless {C}).
    """
    if option.ask is not None:
        return option.ask
    for unit, pip in zip(option.units, unit_pips):
        if len(unit) <= 1:
            continue
        if pip is not None:
            for symbol in _MANA_SYMBOLS:
                if symbol in unit and pip in _unit_pays(player, frozenset({symbol}), reading):
                    return symbol
        if source.default in unit:
            return source.default
        return next(symbol for symbol in _MANA_SYMBOLS if symbol in unit)
    return next(iter(option.units[0]))


def _plan_land_taps(
    game: Game, player: PlayerState, required: dict[str, int],
    *, paying_for: "Permanent | None" = None,
    without: "frozenset[int]" = frozenset(),
    through_priced: bool = True,
) -> tuple[tuple[int, ...], tuple[str, ...]] | None:
    """Which untapped mana sources to tap for *required*, and **which colour
    to ask each one for**: ``(slots, colours)`` in tap order, or None when the
    board cannot pay.

    **An exact matching, and the engine's own** — `mana_payment.plan_payment`,
    the augmenting-path assignment of pips to sources the optional-pay planner
    was written around and the castable highlight asks
    (`board_payment.board_can_pay`). This was a greedy pass: each coloured pip
    took the first land that could make it and never gave it back, so a
    Reflecting Pool spent on the {B} left a Swamp and a Forest unable to find
    the second {G} of a {B}{G}{G} spell they could pay between them — a card
    held and never cast, where the highlight over the same board glowed. One
    matching now answers "can this be paid" for the engine, the highlight and
    this policy, over one reading of what a land's tap makes
    (`_land_tap_options`).

    What a land can make is the engine's answer, not the printed summary's
    first symbol, which is what this once read. That one symbol was wrong
    three ways, measured at NEM: under a seat-wide swap (Deep Water, Harvest
    Mage) a Forest makes {U} or a colour of the tapper's choice; a land
    carrying a granted ability (Overlaid Terrain's "{T}: Add two mana of any
    one color") was still the colour it was printed; and a dual land could
    only ever pay its first colour.

    The colour travels with the plan because the tap seam asks for one
    (``tap_land_for_mana``'s ``chosen_color``) and the executors sent the
    default "G" for every land — so a Taiga the plan counted as {R} made {G}.

    Sources are reached for in a fixed order (`_PaymentPlanner`): floating
    mana, lands, non-land sources that only tap, and — only for a spell, only
    where those cannot pay and only under `_may_sacrifice_for` — a source that
    is sacrificed. And when even those cannot pay, **a source whose mana costs
    mana** (a filter land, Mana Cylix: `_plan_through_a_priced_source`), with
    the taps that pay its price in front of it.
    """
    found = _PaymentPlanner(
        game, player, paying_for=paying_for, without=without,
    ).plan(required)
    if found is None and through_priced and not without:
        return _plan_through_a_priced_source(game, player, required, paying_for)
    return found


def _plan_through_a_priced_source(
    game: Game, player: PlayerState, required: dict[str, int],
    paying_for: "Permanent | None",
) -> "tuple[tuple[int, ...], tuple[str, ...]] | None":
    """`_plan_land_taps` for a cost the free sources cannot pay, through **one**
    source whose mana costs mana (`_priced_mana_source`: "{1}, {T}: Add
    {U}{B}.") — or None.

    Three parts, in the order they are tapped:

    1. the free sources that pay the source's **price**;
    2. the source itself;
    3. the free sources that pay what is left of *required* once the source's
       output is counted — its symbols against the pips they match, any
       surplus against the generic part.

    **The order is the plan.** The executor taps a plan's slots in sequence
    (`tap_planned_lands`), so with the price tapped immediately in front of
    the source, the pool holds exactly that price when the source is activated
    and there is no choice of which unit pays it. Tapped all together first,
    the engine could pay the {1} with the one green mana the spell's {G} was
    counting on. For the same reason this plans nothing while mana is already
    floating: which floating unit a generic price would take is not this
    planner's to say.

    One priced source per plan. Two filter lands feeding one another is a
    longer chain than this walks.
    """
    if any(int(player.mana_pool.get(symbol, 0) or 0) for symbol in _MANA_SYMBOLS):
        return None
    seat = next((i for i, seated in enumerate(game.players) if seated is player), None)
    if seat is None:
        return None
    for index, permanent in enumerate(game.controlled_by(player)):
        if permanent is paying_for:
            continue
        source = _priced_mana_source(game, seat, permanent)
        if source is None:
            continue
        for asked, made in source.outputs():
            rest = _plan_land_taps(
                game, player, _less_mana(required, made), paying_for=paying_for,
                without=frozenset({index}), through_priced=False,
            )
            if rest is None:
                continue
            price = _plan_land_taps(
                game, player, {"generic": source.price}, paying_for=paying_for,
                without=frozenset({index, *rest[0]}), through_priced=False,
            )
            if price is None:
                continue
            return (
                (*price[0], index, *rest[0]),
                (*price[1], asked, *rest[1]),
            )
    return None


def _less_mana(required: dict[str, int], made: dict[str, int]) -> dict[str, int]:
    """*required* with the mana *made* already in the pool: each symbol against
    the pips it matches, and whatever is left over against the generic part.

    A copy in *required*'s own key order — the planner walks the dict it is
    handed, and a simulated game has to reproduce from its seed.
    """
    left = {symbol: int(amount or 0) for symbol, amount in required.items()}
    spare = 0
    for symbol, count in made.items():
        used = min(int(count), left.get(symbol, 0))
        if used:
            left[symbol] -= used
        spare += int(count) - used
    if spare and left.get("generic", 0):
        left["generic"] = max(0, left["generic"] - spare)
    return left


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
    None for every other land, whose tap is a number of one symbol.

    Not read by `_plan_land_taps` any more, which counts a land through
    `board_payment.land_tap_yields`; kept as the statement of what a mixed
    land's tap makes that `tests/ai/test_ai_land_mana_plans.py` holds the tap
    seam to.

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
    """Whether the mana *land*'s default tap makes is **restricted** ("Spend
    this mana only …", CR 106.6 — the ``spend_only`` the add-mana handler
    files it under) or **board-dependent** (`_BOARD_DEPENDENT_MANA_KEYS`).

    This was the planner's exclusion list: such a land was left out of every
    plan rather than guessed at. `_plan_land_taps` no longer asks it — it
    counts a land through `board_payment.land_tap_yields`, which reads a
    restriction against what the payment is for and a board-counted amount
    off the board — so a Gaea's Cradle beside three creatures is three mana
    and Mishra's Workshop pays for an artifact spell. Kept because three test
    files read it as the description of which lands those are.
    """
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
