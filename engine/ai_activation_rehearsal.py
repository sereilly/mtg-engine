"""What activating an ability of the seat's **own** would do, read on a copy.

The main-phase chooser (``ai_abilities.choose_activation_action``) proposes an
ability its flat score alone cannot price only where carrying it out on a
scratch copy of the game (``ai_rehearsal.rehearse``) says it pays: a land's
ability (:func:`_land_ability_worth`), every other ability that must move
something that lasts (:func:`_moves_something`), an X sized by what it buys
(:func:`_sized_x_activation`), a text change's two words
(:func:`_text_change_activation`) — and, before a combat, read again with the
fight fought (:func:`_read_through_the_fight`). The instant-speed chooser
(``ai_policy.choose_instant_speed_activation``) rehearses through
:func:`_rehearse_activation` and queues through :func:`_queue_activation`.

Split out of ``ai_abilities`` (kg5) by subject: that module gates and aims a
proposal, this one measures it.
"""

from __future__ import annotations

from .ai_actions import ActivationAction, activation_announcement
from .ai_payment import _plan_land_taps, tap_planned_lands
from .ai_rehearsal import Rehearsal, rehearse
from .ai_scoring import _leaves_nothing, _worth_proposing
from .ai_text_changes import WORTH_FLOOR, ability_text_change_worth
from .ai_valuation import source_becomes_an_aura
from .game import Game


def _rehearse_activation(
    game: Game, seat: int, action: ActivationAction,
    *, through_combat: bool = False, cost_neutral: bool = False,
) -> Rehearsal | None:
    """What activating *action* would do, carried out on a scratch copy of
    the game (``ai_rehearsal.rehearse``) the way `activate_chosen_ability`
    carries it out — the planned lands tapped, the ability put on the stack —
    against the same copy with the same lands tapped and nothing activated.
    *through_combat* fights the turn's combat on both copies first, for an
    ability whose good is gone by the end of the turn.

    *cost_neutral* also taps the source on the copy with nothing activated
    when the ability's cost is {T}: what is read is then what the **effect**
    did, the question :func:`_moves_something` asks — a "{T}: … until end of
    turn" whose source stays tapped is otherwise a change that lasts, and a
    creature tapped is a body missing *now*, neither of which the effect
    did."""

    def perform(table):
        return _queue_activation(table, seat, action)

    source_taps = cost_neutral and _taps_its_source(game, seat, action)

    def paid_for(table, _carried) -> None:
        pool = table.players[seat].mana_pool
        floating = dict(pool)
        tap_planned_lands(table, seat, action)
        pool.clear()
        pool.update(floating)
        if source_taps:
            source = table.permanent_at(seat, action.permanent_index)
            if source is not None:
                source.tapped = True

    taps = bool(action.land_tap_indices) or source_taps
    rehearsal = rehearse(
        game, seat, perform, spell_name=None, leaves_hand=False,
        label=f"{action.permanent_name}'s ability",
        key=(
            "activation", seat, action.permanent_name, action.permanent_index,
            action.ability_index, action.target_player_index,
            repr(action.target_permanent_index), repr(action.target_role_refs),
            action.land_tap_indices, action.land_tap_colors,
        ) + (
            ("keyword", action.chosen_keyword) if action.chosen_keyword else ()
        ) + (
            ("x", action.x_value) if action.x_value is not None else ()
        ) + (
            ("words", action.old_color, action.new_color)
            if action.old_color or action.new_color else ()
        ) + (("through_combat",) if through_combat else ()) + (
            ("source_tapped",) if source_taps else ()
        ),
        without=paid_for if taps else None,
        without_key=(
            ("paid", action.land_tap_indices, action.land_tap_colors)
            + ((("source_tapped", seat, action.permanent_index),) if source_taps else ())
            if taps else None
        ),
        through_combat=through_combat,
    )
    return _with_the_words_aimed(game, seat, action, rehearsal)


def _taps_its_source(game: Game, seat: int, action: ActivationAction) -> bool:
    """Whether the ability *action* names (on the seat's own permanent) has
    {T} in its cost."""
    if action.source_controller_index is not None:
        return False
    source = game.permanent_at(seat, action.permanent_index)
    usable = game.usable_abilities_of(source) if source is not None else []
    index = action.ability_index or 0
    return 0 <= index < len(usable) and bool(getattr(usable[index].cost, "requires_tap", False))


def _with_the_words_aimed(
    game: Game, seat: int, action: ActivationAction, rehearsal: "Rehearsal | None",
) -> "Rehearsal | None":
    """*rehearsal* of a text-changing ability with what its two words aim at
    added (``ai_text_changes.ability_text_change_worth``): a Circle of
    Protection's colour is a standing's same number whichever word it names,
    as on the cast side (``ai_scoring._rehearse_announcement``)."""
    from dataclasses import replace

    if rehearsal is None or not rehearsal.accepted or not (
        action.old_color and action.new_color
    ):
        return rehearsal
    source = game.permanent_at(
        seat if action.source_controller_index is None else action.source_controller_index,
        action.permanent_index,
    )
    usable = game.usable_abilities_of(source) if source is not None else []
    index = action.ability_index or 0
    if not 0 <= index < len(usable):
        return rehearsal
    named = game.permanent_at(action.target_player_index, action.target_permanent_index)
    now, lasting = ability_text_change_worth(
        game, seat, usable[index].instruction, game.permanent_id_of(named),
        action.old_color, action.new_color,
    )
    if not (now or lasting):
        return rehearsal
    return replace(rehearsal, now=rehearsal.now + now, lasting=rehearsal.lasting + lasting)


def _text_change_activation(
    game: Game, seat: int, candidate: ActivationAction, choices: list,
) -> ActivationAction | None:
    """*candidate* aimed at the best of *choices* (``ai_text_changes.
    ObjectChoice``: a permanent and the two words for it), or None when none
    is worth making: each rehearsed with its words aimed
    (:func:`_land_ability_worth`), the one leaving the seat furthest ahead
    once the turn is over taken, and only at or above the floor a text
    change cast is held to (``ai_text_changes.WORTH_FLOOR``) — every change of
    a word that is written reads as *a* change."""
    from dataclasses import replace

    best: ActivationAction | None = None
    best_worth = WORTH_FLOOR - 1e-9
    for choice in choices:
        aimed = replace(
            candidate, target_player_index=choice.seat,
            target_permanent_index=choice.permanent_index,
            old_color=choice.old_color, new_color=choice.new_color,
        )
        worth = _land_ability_worth(game, seat, aimed)
        if worth is not None and worth > best_worth:
            best, best_worth = aimed, worth
    return best


def _queue_activation(table: Game, seat: int, action: ActivationAction):
    """*action* paid for and put on *table*'s stack — the queue form, which
    leaves it there for the table to answer (CR 117.3c)."""
    planned = tap_planned_lands(table, seat, action)
    return table.queue_permanent_ability(
        seat, planned.permanent_name, **activation_announcement(planned),
    )


def _land_ability_worth(
    game: Game, seat: int, action: ActivationAction,
) -> float | None:
    """What activating a land's non-mana ability (*action*) leaves *seat*
    once the turn is over, or None when that is not a reason to tap the land.

    Rehearsed (:func:`_rehearse_activation`), never scored by the effect's
    family alone: a land tapped for its ability is a mana not made, and the
    heuristic score the chooser ranks with prices nothing — so the gate is the
    measure. Proposed only where the engine took it, it changed something that
    outlasts the turn, and the lasting swing is positive: Krosan Verge's two
    lands for one, a ping, a token. **What is gone by the end of the turn is
    read again through the fight** (``ai_rehearsal.priced_by_the_fight``)
    before a combat or a declared attack's blocks: a manland's animation is
    worth the attack or block it makes, and nothing with no combat ahead.

    Unlike a cast, an ability nobody could rehearse is not proposed — no land
    ability was before, and "could not be weighed" is no reason to start.
    """
    rehearsal = _rehearse_activation(game, seat, action)
    if rehearsal is None or not (rehearsal.accepted and rehearsal.changed):
        return None
    rehearsal = _read_through_the_fight(game, seat, action, rehearsal)
    if rehearsal is None or not _worth_proposing(rehearsal) or rehearsal.lasting <= 0.0:
        return None
    return rehearsal.lasting


def _moves_something(game: Game, seat: int, action: ActivationAction) -> bool:
    """Whether *action* — an ability the main-phase chooser would propose by
    its flat score alone — is one to propose: the cast rule (CLAUDE.md, "a
    cast that moves nothing, or leaves its caster worse off, is not
    proposed"; ``ai_scoring._worth_proposing``), asked of the activation
    carried out on a copy (:func:`_rehearse_activation`) and read through the
    fight where its good is gone by the end of the turn
    (:func:`_read_through_the_fight`).

    **Every ability, not the shapes named.** The chooser rehearsed a land's
    ability, a hamper, a rewrite of its source, an armed draw, a shield, a
    source given up and an effect reaching both sides, each because a seat had
    been seen spending its mana on one for nothing; every other ability was
    proposed at its flat 2.5 whatever it did — a firebreathing pump in the
    second main phase, a "{T}: Untap target land" with every land untapped, a
    "can't block" on a creature with nothing to block, a looter's draw with
    nothing to discard (kg4: `tests/ai/test_kg4_aiact_moves_nothing.py`).
    An ability nobody could rehearse is proposed as it always was.

    Read **cost-neutral** (:func:`_rehearse_activation`): the {T} the cost
    pays is on both copies, so what is judged is the effect — the cost is
    this chooser's other floors' to price, as it always was. And an ability
    that turns its own source into an Aura (the Licids) is asked only whether
    it moves something that lasts: what such an Aura is worth is the
    restriction it puts on its host ("can't attack"), which no standing
    reads, against the creature its source stops being, which one does."""
    rehearsal = _rehearse_activation(game, seat, action, cost_neutral=True)
    if rehearsal is None:
        return True
    if rehearsal.accepted and rehearsal.changed:
        rehearsal = _read_through_the_fight(
            game, seat, action, rehearsal, cost_neutral=True,
        )
        if rehearsal is None:
            return False
    if rehearsal.accepted and rehearsal.changed and _becomes_an_aura(game, seat, action):
        return not _leaves_nothing(rehearsal)
    return _worth_proposing(rehearsal)


def _becomes_an_aura(game: Game, seat: int, action: ActivationAction) -> bool:
    """Whether the ability *action* names turns its own source into an Aura
    (``ai_valuation.source_becomes_an_aura``)."""
    source = game.permanent_at(seat, action.permanent_index)
    usable = game.usable_abilities_of(source) if source is not None else []
    index = action.ability_index or 0
    return 0 <= index < len(usable) and source_becomes_an_aura(usable[index].instruction)


def _read_through_the_fight(
    game: Game, seat: int, action: ActivationAction, rehearsal: Rehearsal,
    *, cost_neutral: bool = False,
) -> "Rehearsal | None":
    """*rehearsal* read again **with the fight fought** where its good is gone
    by the end of the turn (``ai_rehearsal.priced_by_the_fight``) and a
    combat or a declared attack's blocks are ahead — or None for an ability
    that **can wait for the blocks** (:func:`_waits_for_the_blocks`).

    Made in the seat's own main phase before its combat, an ability whose
    worth is the fight is made there only for a **declaration it changes**
    (``Rehearsal.declarations_changed``): a manland animated to attack, a
    creature shielded so that it attacks at all, a blocker tapped or told it
    cannot block, a block deterred. One under which the attack and the blocks
    are the same as without it can be made in the declare-blockers step, with
    the blocks known (``ai_priority.instant_speed_window``'s ``"combat"``) —
    and there only where it pays. Zealous Inquisitor's redirect was bought in the first
    main phase wherever the fight it was read through went better for it, and
    the mana was spent whether or not anything then blocked it (SCG Phase 5).
    """
    from .ai_rehearsal import (blocks_still_to_come, combat_is_still_to_come,
                               priced_by_the_fight)

    precombat = combat_is_still_to_come(game, seat)
    if priced_by_the_fight(rehearsal.now, rehearsal.lasting, rehearsal.fleeting) and (
        precombat or blocks_still_to_come(game)
    ):
        fought = _rehearse_activation(
            game, seat, action, through_combat=True, cost_neutral=cost_neutral,
        )
        if fought is not None and fought.accepted:
            if precombat and not fought.declarations_changed and _waits_for_the_blocks(
                game, seat, action,
            ):
                return None
            rehearsal = fought
    return rehearsal


def _waits_for_the_blocks(game: Game, seat: int, action: ActivationAction) -> bool:
    """Whether *action*'s ability could as well be activated in the coming
    declare-blockers step: its source is the seat's own permanent, its cost
    taps nothing of its own (an attacker is tapped, CR 508.1f, and a {T}
    ability of one that did not attack is one an untapped creature's body
    spends), and its line prints no timing restriction (CR 602.5b: "Activate
    only as a sorcery", "only during your upkeep") — read off the ability the
    action names, so it names no card."""
    from .activation_restrictions import prints_activation_restriction

    if action.source_controller_index is not None:
        return False
    source = game.permanent_at(seat, action.permanent_index)
    usable = game.usable_abilities_of(source) if source is not None else []
    index = action.ability_index or 0
    if not 0 <= index < len(usable):
        return False
    ability = usable[index]
    if getattr(ability.cost, "requires_tap", False):
        return False
    return not prints_activation_restriction(ability.source_line or "")


#: The largest X `_sized_x_activation` rehearses. Each size is a copy of the
#: game run out to the end of the turn, and past eight the effects in the pool
#: ("X damage to each creature with flying") have long since done everything
#: they will do on a limited board.
X_ACTIVATION_SIZES = 8


def _sized_x_activation(
    game: Game, seat: int, permanent, ability, candidate: ActivationAction,
    x_symbols: int,
) -> ActivationAction | None:
    """*candidate* with the X its "{X}…:" cost announces (CR 107.3a), or None
    when no X is worth activating for.

    Every X from 1 up to what the board pays (and :data:`X_ACTIVATION_SIZES`)
    is planned — {X} charged as generic, or as the colour "Spend only red mana
    on X" names, as the activation path charges it — and rehearsed through
    `_land_ability_worth`; the X leaving the seat furthest ahead is proposed,
    the smaller of two equals. So Silklash Spider pays enough to kill the
    opponent's fliers, and nothing where it would kill more of its own.
    """
    from dataclasses import replace

    from .oracle_types import x_spend_colors_from_text

    player = game.players[seat]
    colors = x_spend_colors_from_text(ability.source_line or "")
    x_symbol = colors[0] if len(colors) == 1 else "generic"
    best: ActivationAction | None = None
    best_worth = 0.0
    for x_value in range(1, X_ACTIVATION_SIZES + 1):
        taps: tuple[int, ...] = ()
        tap_colors: tuple[str, ...] = ()
        if game.enforce_mana_costs:
            required = {
                symbol: int(amount or 0) for symbol, amount in ability.cost.mana.items()
            }
            required[x_symbol] = required.get(x_symbol, 0) + x_value * x_symbols
            plan = _plan_land_taps(game, player, required, paying_for=permanent)
            if plan is None:
                break
            taps, tap_colors = plan
        sized = replace(
            candidate, x_value=x_value, land_tap_indices=taps, land_tap_colors=tap_colors,
        )
        worth = _land_ability_worth(game, seat, sized)
        if worth is not None and worth > best_worth + 1e-9:
            best, best_worth = sized, worth
    return best
