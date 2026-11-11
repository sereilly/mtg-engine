"""Which ability an AI seat activates from a card **in its graveyard**
(CR 113.6b: "Activate only if this card is in your graveyard"; CR 113.6m:
"Return this card from your graveyard to …").

No AI seat had ever activated one: the only caller of
`Game.activate_from_graveyard` outside the tests was the web route a person
clicks, so Ashen Ghoul, Carrionette, Glory, Hammer of Bogardan, Necrosavant,
Shard Phoenix, Whiteout and Gangrenous Goliath were cards a simulated seat
put in its graveyard and left there — and nothing in a run's report said so.
`SimulationReport.activations_from_graveyard` is the count that does now.

**Which abilities those are is the engine's reading**, never a list here:
`activation_zones.ability_functions_from` over the card's printed abilities,
the gate `Game.activate_from_graveyard` itself asks. **Whether one may be
activated now is the engine's too**: `activation_prohibition` is asked first
(the printed "Activate only during your upkeep", "only if three or more
creature cards are above this card", City of Solitude's turn rule), and
everything else the door checks — a cost a graveyard cannot charge, a target
it would refuse, a sacrifice with nothing to give up — is answered by
carrying the activation out on a copy of the game (`ai_rehearsal.rehearse`),
whose refusal is a candidate not proposed. A proposal is rehearsed like a
battlefield ability's (`ai_abilities._rehearse_activation`): made only where
it changes something that outlasts the turn and leaves its seat no worse —
and, given priority outside its main phase (`ai_simulator._answer_priority`),
only where what it does lasts (``lasting_only``), as
`ai_policy.choose_instant_speed_activation` asks of a battlefield ability.

A module of its own rather than another chooser in ``ai_abilities``, beside
the action shape it builds (`ai_actions.GraveyardActivationAction`) and for
that action's reason: the engine door is its own. The hand's chooser
(``ai_hand_activations``) and another seat's (``ai_foreign_activations``)
left ``ai_abilities`` for the same reason.
"""

from __future__ import annotations

from contextlib import nullcontext

from .activation_prohibitions import activation_prohibition
from .activation_zones import GRAVEYARD, ability_functions_from
from .ai_actions import GraveyardActivationAction
from .ai_payment import _plan_land_taps, tap_planned_lands
from .ai_rehearsal import Rehearsal, deliberating, rehearse
from .ai_standing import permanent_worth
from .ai_scoring import SWING_CAP, _score_activation, _worth_proposing
from .ai_target_sides import ability_seat_side, ability_target_side
from .ai_valuation import is_mana_ability
from .mana_wants import bringing_back
from .cost_pickers import spec_is_a_cost
from .game import Game
from .oracle import compile_card_oracle
from .targeting import spec_roles
from .ai_player_control import plays_for_another

#: How many of a targeted ability's legal objects one decision rehearses: the
#: most valuable on the side its effect wants first (`_target_choices`).
TARGETS_WEIGHED = 3


def graveyard_abilities(game: Game, seat: int) -> list:
    """``(graveyard index, card, ability index, ability)`` for every ability
    a card in *seat*'s graveyard may be activated from there with — the
    engine's own zone read (`ability_functions_from`), over the printed list
    `Game.activate_from_graveyard` indexes — that is supported and is not a
    mana ability (mana made for its own sake empties at the end of the step,
    the floor every activation chooser keeps)."""
    found: list = []
    for graveyard_index, card in enumerate(game.players[seat].graveyard):
        program = compile_card_oracle(card)
        for ability_index, ability in enumerate(program.activated_abilities):
            if (
                ability.supported
                and ability.instruction is not None
                and ability_functions_from(ability) == GRAVEYARD
                and not is_mana_ability(ability.instruction)
            ):
                found.append((graveyard_index, card, ability_index, ability))
    return found


def holds_a_graveyard_ability(game: Game, seat: int) -> bool:
    """Whether *seat*'s graveyard holds an ability CR 602.5 lets it activate
    now (`activation_prohibition`) — the cheap question asked before the
    chooser's rehearsals, at every priority offer."""
    return any(
        activation_prohibition(game, seat, card, ability) is None
        for _index, card, _ability_index, ability in graveyard_abilities(game, seat)
    )


def choose_graveyard_activation_action(
    game: Game, seat: int, *, lasting_only: bool = False,
) -> GraveyardActivationAction | None:
    """The ability *seat* activates from its graveyard now, or None.

    *lasting_only* is a priority window outside the seat's own main phase:
    a proposal must leave something that outlasts the turn, as a battlefield
    ability must there (`ai_policy.choose_instant_speed_activation`) — a
    Glory raised with nothing coming is worth nothing, the same Glory in
    front of a burn spell is a creature kept.

    One deliberation: every candidate is weighed against the same table with
    nothing activated. Ties keep graveyard order, so a seeded run reproduces.
    """
    # CR 723.5: a seat another player decides for plays nothing
    # optional for itself (``ai_player_control``'s measured policy).
    if plays_for_another(game, seat):
        return None
    with deliberating():
        best: GraveyardActivationAction | None = None
        for graveyard_index, card, ability_index, ability in graveyard_abilities(game, seat):
            candidate = _candidate(
                game, seat, graveyard_index, card, ability_index, ability,
                lasting_only=lasting_only,
            )
            if candidate is not None and (best is None or candidate.score > best.score):
                best = candidate
        return best


def activate_chosen_graveyard_ability(
    game: Game, seat: int, action: GraveyardActivationAction,
):
    """Carry out *action* on *game*: the planned lands tapped
    (`tap_planned_lands`) and `Game.activate_from_graveyard` — the **queue**
    form, which leaves the ability on the stack for the table to answer
    (CR 117.3c). The engine's result. The executor every driver shares, and
    the rehearsal's own *perform*."""
    planned = tap_planned_lands(game, seat, action)
    return game.activate_from_graveyard(
        seat, planned.card_name,
        ability_index=planned.ability_index,
        graveyard_index=planned.graveyard_index,
        target_player_index=planned.target_player_index,
        target_permanent_ids=planned.target_permanent_ids,
        cost_hand_index=planned.cost_hand_index,
    )


def _candidate(
    game: Game, seat: int, graveyard_index: int, card, ability_index: int,
    ability, *, lasting_only: bool,
) -> GraveyardActivationAction | None:
    """One ability as a proposal — gated, planned, aimed by rehearsal and
    scored — or None."""
    if activation_prohibition(game, seat, card, ability) is not None:
        return None
    land_taps: tuple[int, ...] = ()
    tap_colors: tuple[str, ...] = ()
    # The cost `_activate_from_graveyard` charges: the printed mana (no
    # permanent is the source, so nothing sacrificed for mana is "paying for"
    # one).
    required = dict(ability.cost.mana)
    if game.enforce_mana_costs and any(required.values()):
        # What the ability brings back wants paying for next (an Eternal
        # Dragon returned to the hand, its {5}{W}{W}): the plan spares it
        # (``mana_wants.bringing_back``).
        returned = _returns_its_card_to(ability)
        with bringing_back(card, returned) if returned else nullcontext():
            plan = _plan_land_taps(game, game.players[seat], required)
        if plan is None:
            return None
        land_taps, tap_colors = plan
    discard = _discard_pick(game, seat, ability.cost)
    if ability.cost.discard_cards and discard is None:
        return None
    best: tuple[float, GraveyardActivationAction] | None = None
    for target_seat, target_ids in _target_choices(game, seat, card, ability):
        candidate = GraveyardActivationAction(
            card_name=card.name,
            graveyard_index=graveyard_index,
            ability_index=ability_index,
            land_tap_indices=land_taps,
            score=0.0,
            target_player_index=target_seat,
            target_permanent_ids=target_ids,
            land_tap_colors=tap_colors,
            cost_hand_index=discard,
        )
        rehearsal = _rehearse(game, seat, candidate)
        # Never proposed unweighed: an activation nobody could carry out on a
        # copy (mid-resolution, or a copy that raised — counted by the
        # rehearsal) is a guess, and a refused one is a seat doing nothing.
        if rehearsal is None or not _worth_proposing(rehearsal):
            continue
        if lasting_only and rehearsal.lasting <= 0.0:
            continue
        swing = max(-SWING_CAP, min(SWING_CAP, rehearsal.swing))
        if best is None or swing > best[0] + 1e-9:
            best = (swing, candidate)
    if best is None:
        return None
    swing, candidate = best
    aimed = candidate.target_player_index
    score = _score_activation(
        game, seat, ability.instruction, seat if aimed is None else aimed,
    ) + swing
    if score <= 0.0:
        return None
    return GraveyardActivationAction(
        card_name=candidate.card_name,
        graveyard_index=candidate.graveyard_index,
        ability_index=candidate.ability_index,
        land_tap_indices=candidate.land_tap_indices,
        score=score,
        target_player_index=candidate.target_player_index,
        target_permanent_ids=candidate.target_permanent_ids,
        land_tap_colors=candidate.land_tap_colors,
        cost_hand_index=candidate.cost_hand_index,
    )


def _returns_its_card_to(ability) -> "str | None":
    """Where *ability* — one a card activates from its graveyard — puts that
    card: ``"hand"`` or ``"battlefield"`` ("Return this card from your
    graveyard to your hand", ``return_self_from_graveyard``'s ``to``), or
    None for any other effect."""
    from .ai_weighed_cast import _effect_steps

    for step in _effect_steps(ability.instruction):
        if step.kind == "return_self_from_graveyard":
            zone = (step.payload or {}).get("to") or "hand"
            return "battlefield" if zone == "battlefield" else "hand"
    return None


def _discard_pick(game: Game, seat: int, cost) -> "int | None":
    """The hand position a "Discard a card" cost is paid with: of the payable
    cards (`Game._discard_cost_payable`, the printed phrase's), the one the
    seat least wants to lose — ``ai_prompt_picks.discard_order``, the reading
    every discard a seat chooses takes: a card whose madness cost the board
    can pay first (CR 702.35a), then the least ``discard_worth`` (a card with
    a road back from the graveyard keeps part of its worth), the earliest of
    equals — or None for a cost that discards nothing, or one the hand cannot
    pay. A rehearsal reads a card in hand as a card whatever it is
    (`ai_standing.CARD_WORTH`), so which one pays is this policy's, and the
    engine's own default is the first. It was the card of least mana value,
    so a Firebolt went before a spare seventh land."""
    if not cost.discard_cards:
        return None
    hand = game.players[seat].hand
    payable = game._discard_cost_payable(cost, game.players[seat])
    positions = [
        index for index, held in enumerate(hand)
        if any(held is card for card in payable)
    ]
    if len(positions) < cost.discard_cards:
        return None
    from .ai_prompt_picks import discard_order

    return discard_order(game, seat, positions, None)[0]


def _target_choices(game: Game, seat: int, card, ability) -> list:
    """``(seat, [permanent id] | None)`` for each announcement worth
    rehearsing: ``(None, None)`` for an ability naming no target, and for
    one the picker offers no permanent or seat for (the engine's own
    default then names it, `engine/bare_announcements.py`); otherwise the
    legal objects the ability's effect wants (`ability_target_side`), most
    valuable first (`permanent_worth`), up to `TARGETS_WEIGHED` — and each
    legal seat on the side `ability_seat_side` reads.

    The list is the engine's (`Game.graveyard_activation_target_spec`, the one
    `_activate_from_graveyard` judges a named target by). A roles
    announcement is none this chooser makes — no graveyard ability in the
    pool prints one — so it is not proposed rather than announced bare."""
    spec = game.graveyard_activation_target_spec(seat, card, ability)
    # A cost picker is not a target ("Sacrifice a creature", Necrosavant; "Tap
    # three untapped Clerics", Gangrenous Goliath): what pays is the engine's
    # deterministic pick (`default_sacrifice_pick`, the smallest), and naming
    # it here as a target would announce a target the ability does not have.
    if not spec.get("requires_target") or spec_is_a_cost(spec):
        return [(None, None)]
    if spec_roles(spec):
        return []
    options = spec.get("valid_targets") or []
    side = ability_target_side(ability.instruction)
    permanents = []
    for option in options:
        if option.get("kind") != "permanent":
            continue
        permanent = game.permanent_at(option.get("seat"), option.get("index"))
        permanent_id = game.permanent_id_of(permanent) if permanent is not None else None
        if not isinstance(permanent_id, int):
            continue
        ours = option.get("seat") == seat
        if (side == "you" and not ours) or (side == "opponent" and ours):
            continue
        permanents.append((-permanent_worth(permanent), permanent_id, option.get("seat")))
    permanents.sort()
    choices: list = [
        (owner, [permanent_id])
        for _worth, permanent_id, owner in permanents[:TARGETS_WEIGHED]
    ]
    seat_side = ability_seat_side(ability.instruction)
    for option in options:
        if option.get("kind") != "player":
            continue
        named = option.get("seat")
        if (seat_side == "you" and named != seat) or (
            seat_side == "opponent" and named == seat
        ):
            continue
        choices.append((named, None))
    if not any(option.get("kind") in ("permanent", "player") for option in options):
        return [(None, None)]
    return choices


def _rehearse(game: Game, seat: int, action: GraveyardActivationAction) -> Rehearsal | None:
    """What activating *action* would do, carried out on a scratch copy as
    every executor carries it out (`activate_chosen_graveyard_ability`) and
    resolved on defaults, against the same copy with the same lands tapped
    and nothing activated (`ai_abilities._rehearse_activation`'s shape).

    The card leaving the graveyard is the effect's (CR 608.2), read as a
    change like any other: a card back in hand is a card to the good, one
    back on the battlefield a permanent."""

    def perform(table):
        return activate_chosen_graveyard_ability(table, seat, action)

    def paid_for(table, _carried) -> None:
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, action)
        pool.clear()
        pool.update(floating)

    taps = bool(action.land_tap_indices)
    return rehearse(
        game, seat, perform, spell_name=None, leaves_hand=False,
        label=f"{action.card_name}'s ability from the graveyard",
        key=(
            "graveyard_activation", seat, action.card_name,
            action.graveyard_index, action.ability_index,
            action.target_player_index, repr(action.target_permanent_ids),
            action.cost_hand_index, action.land_tap_indices, action.land_tap_colors,
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", action.land_tap_indices, action.land_tap_colors)
            if taps else None
        ),
    )
