"""The AI's choosers: what a seat nobody is prompting does with priority, and
the front door to the rest of the policy.

**The decisions here** are the plays a seat makes when it holds priority:
the cast it makes in its main phase (:func:`choose_cast_action` — out of its
hand, its command zone and whatever an effect has opened to it, every card
weighed against one reading of the table), its land drop
(:func:`choose_land_drop`, a special action and not a cast), a madness cast
offered part-way through a resolution (:func:`choose_madness_cast`), and
what it does given priority outside its main phase — the instant it casts
(:func:`choose_combat_instant_cast_action`) or the ability it activates
(:func:`choose_instant_speed_activation`), each proposal rehearsed before it
is made. The two executors both drivers share are here too
(:func:`cast_chosen_instant`, :func:`activate_chosen_ability`), so the
simulator and the web app's AI seat carry a proposal out the same way.

**What each decision is built from is a module of its own**, and none of
them imports this one:

* ``ai_actions`` — the proposals (``CastAction`` and its twins), the one
  place a proposal becomes the engine's keywords (``cast_announcement``),
  and the candidate being built: its offers, its mode, its zone;
* ``ai_casts`` — one cast built as a candidate, in each mode, at each answer
  to its optional costs;
* ``ai_cast_gates`` — whether that cast can be made as announced;
* ``ai_targets`` and ``ai_divisions`` — what it names, and how a divided
  spell splits what it divides;
* ``ai_scoring`` — what a proposal is worth, measured by rehearsing it;
* ``ai_abilities`` — which ability to activate, on the seat's own
  permanents, another seat's, or a card in its hand;
* ``ai_declarations`` — its attackers and its blockers;
* ``ai_prompts`` — the answers it gives part-way through a resolution;
* ``ai_payment`` and ``ai_mana_sources`` — the taps that pay for all of it.

What a card *does* is not the policy's to say: the valuation modules read it
off the compiled program (``ai_valuation`` and its family), and the weights
here and beside it are tuning over those readings. The policy draws nothing
from the seeded RNG; a rehearsal restores what its copy drew.
"""

from __future__ import annotations

from dataclasses import replace
import re

from .ai_weighed_cast import (
    PermittedCast,
    cast_weighed,
    casting_under,
    considering_mode,
    hand_waiver,
    permitted_casts,
    castable_commanders,
)
from .ai_rehearsal import Rehearsal, deliberating, rehearse
from .ai_valuation import entry_sacrifice_is_unavoidable, is_mana_ability
from .faces import castable_faces
from .game import Game
from .models import CardDefinition
from .oracle import compile_card_oracle
from .ai_mana_sources import _land_symbols
from .ai_payment import tap_planned_lands, _cost_for, _plan_land_taps
from .ai_actions import (
    CastAction,
    ActivationAction,
    cast_announcement,
    _zone_seat,
    hand_spells,
    spell_being_cast,
    zone_being_cast_from,
    _announced_mode,
    _cast_zone,
)
from .ai_scoring import (
    _IN_THE_ABSTRACT,
    _rehearse_announcement,
    _names_an_unweighed_seat,
    _worth_proposing,
    _choose_target_for_spell,
    _score_cast,
    _pick_x_value,
)
from .ai_cast_gates import (
    _aimed_under_target_requirements,
    _can_cast_with_targets,
    _caster_can_make_its_sacrifices,
)
from .ai_targets import (
    _cast_graveyard_denial,
    _choose_role_targets,
    _choose_single_object_target,
    _guarded_stack_target,
    _chosen_stack_target,
)
from .ai_divisions import choose_divided_targets
from .ai_abilities import choose_activation_action, _ACTIVATIONS_SET_ASIDE
from .ai_casts import (
    _priced_candidate,
    _cast_candidate,
    _every_mode_worth_casting,
    _modes_weighed,
)


def choose_cast_action(game: Game, player_index: int) -> CastAction | None:
    """The cast this seat makes now, out of everything it may cast — its hand,
    its commander, and whatever an effect has opened to it — or None.

    **One deliberation for the whole decision** (``ai_rehearsal.deliberating``).
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
        # The plan is told what it pays for (`ai_payment._paying_for`): the spell, which
        # is what a permanent given up for mana is weighed against and what
        # restricted mana may be spent on. Whether an effect has made the cast
        # free (Aluren) is the waiver the candidate is weighed under
        # (`ai_weighed_cast.hand_waiver`).
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
    # (`ai_weighed_cast.permitted_casts`, over the seam the browser's zone badges
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
    # game. Which casts are on offer is `ai_weighed_cast.castable_commanders` —
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


def choose_madness_cast(
    game: Game, player_index: int, held: CardDefinition, permission,
) -> "CastAction | None":
    """The madness cast *player_index* makes of *held* — a card its madness
    ability has just exiled (CR 702.35a) — or None to decline it.

    The offer's permission is the one ``engine/madness.py`` granted for its
    length, requiring the madness cost (CR 118.9b), so the cast is built by
    the same candidate builder every cast out of a zone a permission opens
    is (`choose_cast_action`'s second loop): the same gates, target, mode
    and division choosers, the same plan for the mana, and the same
    rehearsal deciding whether it is worth making at all — a Psychotic Haze
    that would kill only its caster's own creatures is declined.

    **Weighed in the abstract** (`_IN_THE_ABSTRACT`), because the question is
    asked part-way through the madness trigger's own resolution, where no
    copy of the table can be taken as it stands
    (``ai_rehearsal.mid_resolution``). The copy that is taken owes nothing,
    and the permission travels with it because it is stored on the game.

    No timing gate: CR 608.2g makes the cast during a resolution, where a
    creature or a sorcery with madness is cast whatever the step.
    """
    pile = game.players[player_index].exile
    index = next((i for i, card in enumerate(pile) if card is held), None)
    if index is None or permission is None:
        return None
    best: CastAction | None = None
    token = _IN_THE_ABSTRACT.set(True)
    try:
        with deliberating():
            for spell in castable_faces(held):
                permitted = PermittedCast(
                    zone="exile", owner_seat=player_index, index=index,
                    held=held, spell=spell, permission=permission,
                    alternative_cost=True,
                )
                candidate = _priced_candidate(
                    game, player_index, spell, index,
                    from_zone="exile", under=permitted,
                )
                if candidate is not None and _is_better_cast(candidate, best):
                    best = candidate
    finally:
        _IN_THE_ABSTRACT.reset(token)
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
    the game (``ai_rehearsal.rehearse``) the way `activate_chosen_ability`
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
        cost_hand_index=planned.cost_hand_index,
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
    somewhere else (CR 601.3; `ai_weighed_cast.permitted_casts`) — a flashback
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
    (`ai_weighed_cast.cast_weighed`: a flashback instant in the graveyard) — or
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
        # `ai_casts._cast_candidate_announcing`.
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

    # The mana before the target, for `ai_casts._cast_candidate_announcing`'s reason:
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
    # dealing its damage (`ai_rehearsal.rehearse`). That comparison is the
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
