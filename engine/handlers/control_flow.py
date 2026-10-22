"""Control-flow instructions: sequencing, conditions, optional costs, iteration.

These are what let an effect be *composed* rather than fused into a bespoke
instruction kind. The legacy compiler delivered exactly one instruction per
spell, so every "do X and also Y" card needed its own kind —
``deal_damage_and_gain_life``, ``deal_damage_and_self_damage``,
``grant_target_keyword_until_eot`` fused with a linked destroy, and 25 more,
which is combinatorial in
the number of base effects and was the single largest driver of kind growth.
The first of those is gone as of Soul Burn: Drain Life's whole sentence,
life-gain cap and all, is now a ``deal_damage`` and a ``target_gains_life`` in
a ``sequence``, and the kind it used to need has no producer left.

With ``sequence`` in the IR, "X and Y" is two ordinary instructions and no new
kind at all. ``if_then`` / ``may`` / ``for_each`` wrap nested sequences the same
way, so conditions and optional costs stop being baked into effect kinds too.

Nested steps travel in the payload as tuples of ``OracleInstruction`` and are
dispatched back through ``EFFECT_HANDLERS`` — the same O(1) dict every other
effect uses.

**What is here is the composition itself**, since the 2,000-line cap's split
round: the step runner (``_run``) and the role each step of a several-role
announcement spends, the four composers — ``sequence``, ``if_then``, ``may``
and ``for_each`` — with the modal ``choose_one``, the coin flip and the count a
conditional branches on, and ``evaluate_condition``, the one entry point every
condition in the engine is asked through. What the composers *ask* left for
modules named after the question, each the handler twin of a lowering module:

* ``_conditions``, ``_record_conditions``, ``_color_conditions`` — what a
  condition payload means: the game now, a record of something done, a
  colour. ``evaluate_condition`` hands every kind but the two joiners to them.
* ``offers`` — who an offer is made to, whether they could take it, what it
  charges, and the two offers that are instructions of their own.
* ``value_choices`` — a number, a colour or a type chosen as the effect
  resolves.
* ``repeats`` — "repeat this process": the one of them that imports this
  module, because a round's steps run through ``_run``.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..oracle_types import (COIN_FLIPS_MADE, COIN_FLIPS_WON,
                            PER_OBJECT_SEAT_RECORDS, OracleInstruction,
                            STACK_TARGET_CONTROLLER)
from ..resumption import run_resumable
from ..mana_payment import mana_cost_label
from ._color_conditions import evaluate_color_condition
from ._common import flip_coin, flip_coin_for
from ._conditions import evaluate_state_condition
from ._filters import permanent_matches_filter
from ._record_conditions import evaluate_record_condition
from .offers import (_action_is_takeable, _derived_cost_is_unpayable,
                     _exiled_cards_still_in_exile, _narrow_to_takeable_actions,
                     _offered_seats, _resolved_cost, _resolved_life_cost)
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


def _steps(instruction: OracleInstruction, key: str) -> tuple:
    value = instruction.payload.get(key) or ()
    return tuple(value)


def _run(game: Game, steps: tuple, context: OracleExecutionContext) -> tuple[bool, str]:
    """Execute nested instructions in order against the shared context.

    The context is deliberately *not* copied: results recorded by one step
    ("damage_dealt") must be visible to the next.

    Run through ``run_resumable`` so a step that stops to ask the player
    something (CR 616.1e) takes the steps behind it with it: they are recorded
    and run when the answer arrives, rather than executing against a step that
    has not happened yet. That is also why the loop is the last thing here —
    ``resolved`` is folded in as each step goes, not tallied afterwards.
    """
    outcome = {"resolved": False}
    # The roles description of the nearest earlier step that spent one role of
    # a several-role announcement — the antecedent of a back-reference behind
    # it (see ``_antecedent_scoped``).
    antecedent: dict = {"spent": None}

    def run_step(step) -> None:
        scoped = _role_scoped(game, step, context)
        if scoped is context:
            scoped = _antecedent_scoped(game, step, context, antecedent["spent"])
        if scoped is None:
            # CR 608.2b's last sentence: the announcement named this step's
            # object and it is no longer there, so the step does nothing while
            # the rest of the effect goes on. Skipped rather than run against a
            # context with a hole in it, which is how a damage step whose
            # creature had died came to hit a face instead.
            return
        antecedent["spent"] = _spent_role(step) or antecedent["spent"]
        supported, _ = game._execute_oracle_instruction(step, scoped)
        outcome["resolved"] = outcome["resolved"] or supported

    run_resumable(game, steps, run_step)
    return True, "resolved" if outcome["resolved"] else "no effect"


def _spent_role(step: OracleInstruction) -> dict | None:
    """The several-role description *step* carries, marked with the one role
    it acts on, or None for a step that spends no role.

    Two spellings of "which role is mine" exist and both are read: the key
    inside the description (``target_roles.payload_own_role``, a step of a
    sentence spent a role at a time) and ``subject_role`` beside it (a
    one-instruction roles sentence whose handler asks for its role by name —
    "Put X glyph counters on target creature that target Wall blocked").
    """
    from ..targeting import spec_roles
    from ..target_roles import payload_own_role

    payload = step.payload if isinstance(step.payload, dict) else {}
    described = payload.get("targets")
    if not isinstance(described, dict) or not spec_roles(described):
        return None
    role = payload_own_role(payload) or payload.get("subject_role")
    if not isinstance(role, str):
        return None
    return {**described, "role": role}


def _antecedent_scoped(
    game: Game, step: OracleInstruction, context: OracleExecutionContext,
    spent: dict | None,
):
    """*context* for a **back-reference** behind a step that spent one role of
    a several-role announcement: narrowed to that role's object. *context*
    itself for every other step.

    "Put X glyph counters on target creature that target Wall blocked this
    turn… **The creature** gains "This creature doesn't untap…"" (Glyph of
    Delusion). The second sentence names no target of its own — its "the
    creature" is the first sentence's — so its step carries no description,
    and against the unscoped announcement its handler read slot 0: the
    *Wall*. The grant landed on the right creature anyway, and only by
    accident: the Wall sits on the other battlefield, the resolver declined
    it, and its fall-through scan took the first creature on the seat it was
    looking at. An announced object has no scan
    (``_targets.pick_target_permanent``), so the antecedent is said here
    instead: a step with no ``targets`` and no steps of its own, behind a step
    that spent a role, is about that role's object.

    None where that object has left (CR 608.2b), exactly as ``_role_scoped``
    answers for a step naming the role itself.
    """
    from ..targeting import _nested_steps

    payload = step.payload if isinstance(step.payload, dict) else {}
    if spent is None or "targets" in payload or _nested_steps(step):
        return context
    return _role_scoped(
        game, dataclasses.replace(step, payload={"targets": spent}), context
    )


def _role_scoped(
    game: Game, step: OracleInstruction, context: OracleExecutionContext
):
    """*context* narrowed to the one **role** *step* spends, or *context*.

    A sentence whose targets are announced together and spent a step at a time
    — "Lunge deals 2 damage to target creature **and** 2 damage to target
    player or planeswalker" — puts the whole ordered ``roles`` list on every
    step and names each step's own slot beside it
    (``grammar/lowering/_roles.describe_sequence_target_roles``). What each
    step then needs is the context a one-target effect would have had: its own
    object in the target channels, and nothing of its neighbour's.

    **Here rather than in each handler**, which is the difference between one
    reader and a dozen. A step's handler is an ordinary ``deal_damage`` or
    ``may`` that has never heard of roles; scoping the context is what lets it
    go on reading ``context.target`` and ``context.target_permanent_id`` and be
    right, where a per-handler ``resolve_role_*`` call would be the same fact
    spelled once per effect family — and the family that forgot would silently
    resolve against whichever target the previous step left behind, which is
    precisely the defect this fixes.

    Returns *context* unchanged for every step that names no role, which is
    every other instruction in the pool: the narrowing is inert until a
    lowering writes the key. Returns None where the role no longer resolves,
    which the caller reads as "skip this step" (CR 608.2b).

    **A wrapper is scoped to the one role its branches spend.** "Then return
    another target creature to its owner's hand **unless its controller pays
    {1}**" (Withdraw) puts the role on the bounce inside the offer, and the
    offer itself names none — so ``_offered_seats("controller")`` read the
    *first* creature off the unscoped list and asked the wrong player. Scoped
    here, the offer asks the second creature's controller. A wrapper whose
    branches spend two roles (or none) is left alone; each of its steps is
    scoped when it runs.

    **A scoped context remembers the announcement it was cut from**
    (``announced_targets``), and every role is resolved against that rather
    than against whatever an enclosing scope left in the channels. A wrapper's
    branch may spend a *different* role from the wrapper's own: Crooked Scales'
    toll, scoped to "target creature you control", buys "repeat this process",
    which runs the won arm's "target creature an opponent controls" again under
    the toll's context — and resolved against the scoped channels that arm
    would have read the payer's own creature.
    """
    from ..targeting import spec_roles
    from ..target_roles import (payload_own_role, payload_role_slot,
                                role_is_seat)
    from ._targets import resolve_role_permanent, resolve_role_player

    payload = step.payload
    role = payload_own_role(payload)
    # A wrapper is never *skipped* for its branch's object having gone: what
    # it decides for itself may not be about that object at all ("…unless
    # **you** pay {3} and repeat this process", Crooked Scales, is still an
    # offer). Only the steps that spend the role are CR 608.2b's to skip.
    wrapper = role is None
    if wrapper:
        spent = _role_its_branches_spend(step)
        if spent is None:
            return context
        role, payload = spent
    entry = next(
        (
            described for described in spec_roles(payload.get("targets"))
            if described.get("role") == role
        ),
        None,
    )
    if entry is None:  # pragma: no cover - a payload with a name and no list
        return context
    announced = _announced_context(context)
    remembered = (
        announced.target, announced.target_permanent_id,
        announced.target_permanent_index,
    )
    if entry.get("kind") == "spell":
        # "Counter **target spell** and Suffocating Blast deals 3 damage to
        # target creature." A role whose object is on the stack, which is the
        # one channel the three saved above do not carry — a counter has read
        # ``context.stack_target`` since Counterspell, and no scope here ever
        # narrows it. So this scope takes the *neighbour's* permanent out of
        # the other channels and leaves the spell where it was.
        #
        # A spell that has left the stack is CR 608.2b's illegal target: the
        # step is skipped and the half beside it still happens. Asked here
        # rather than left to the handler, whose own answer for "nothing
        # named" is the top of the stack — right for a caller that named
        # nothing and wrong for an announcement whose spell is gone. By
        # identity, because ``StackItem`` compares by value.
        named = context.stack_target
        if named is None or not any(obj is named for obj in game.stack):
            return context if wrapper else None
        return dataclasses.replace(
            context, target_permanent_index=None, target_permanent_id=None,
            announced_targets=remembered,
        )
    if role_is_seat(entry):
        seat = resolve_role_player(game, announced, payload, role)
        if seat is None or game.players[seat].lost:
            return context if wrapper else None
        return dataclasses.replace(
            context, target=game.players[seat],
            target_permanent_index=None, target_permanent_id=None,
            announced_targets=remembered,
        )
    permanent = resolve_role_permanent(game, announced, payload, role)
    if permanent is None or not game.is_on_battlefield(permanent):
        if not wrapper:
            return None
        # The wrapper runs naming the **departed** object: an id recorded for
        # a permanent that has left is the one choice every resolver reads as
        # gone (``pick_target_permanent``'s step 0b), so "its controller" is
        # offered nothing (Withdraw) and the step spending the role skips
        # itself — while an offer that was never about the object still is
        # made. With no id recorded there is nothing to name it by, and the
        # wrapper is skipped rather than handed a context a scan could fill.
        slot = payload_role_slot(payload, role)
        ids = announced.target_permanent_id
        recorded = (
            ids[slot] if isinstance(ids, list) and slot is not None
            and 0 <= slot < len(ids) else None
        )
        if not isinstance(recorded, int):
            return None
        return dataclasses.replace(
            context, target_permanent_index=None, target_permanent_id=recorded,
            announced_targets=remembered,
        )
    seat = game.controller_index_of(permanent)
    return dataclasses.replace(
        context,
        # The seat whose battlefield the object is on, because that is what a
        # one-target announcement's ``target`` means to every index-reading
        # resolver beneath this. Never the announced *player* role's seat: the
        # two slots of one announcement may sit on two battlefields, and an
        # index read against the wrong one addresses a different permanent.
        target=game.players[seat] if seat is not None else context.target,
        target_permanent_index=game.battlefield_index_of(permanent),
        target_permanent_id=game.permanent_id_of(permanent),
        announced_targets=remembered,
    )


def _announced_context(context: OracleExecutionContext) -> OracleExecutionContext:
    """*context* with its target channels as the announcement left them.

    The identity for every context no role has scoped yet; for one that has, the
    three channels it saved before narrowing (see :func:`_role_scoped`).
    """
    saved = context.announced_targets
    if saved is None:
        return context
    target, ids, indices = saved
    return dataclasses.replace(
        context, target=target, target_permanent_id=ids,
        target_permanent_index=indices,
    )


#: Where a wrapper's nested steps sit, for :func:`_role_its_branches_spend`.
#: The lowering's own walk over the same announcement
#: (``grammar/lowering/_roles._ANNOUNCEMENT_BRANCH_KEYS``) — a role stamped
#: under any of these is one the resolution can reach. ``reflexive`` is absent
#: for that table's reason: CR 603.12 makes it a separate ability with its own
#: targets.
_ROLE_BRANCH_KEYS = ("steps", "then", "else", "action", "otherwise")


def _role_its_branches_spend(step: OracleInstruction):
    """``(role, payload)`` for the one role *step*'s nested steps spend, or None.

    None when no nested step names a role (every wrapper in the pool but the
    ones a roles lowering built) or when they name more than one — a wrapper
    over two roles has no single object to be about.
    """
    from ..target_roles import payload_own_role

    found: dict[str, dict] = {}

    def walk(instruction) -> None:
        payload = getattr(instruction, "payload", None) or {}
        own = payload_own_role(payload)
        if own is not None:
            found.setdefault(own, payload)
        for key in _ROLE_BRANCH_KEYS:
            branch = payload.get(key)
            if isinstance(branch, (list, tuple)):
                for nested in branch:
                    walk(nested)

    for key in _ROLE_BRANCH_KEYS:
        branch = (step.payload or {}).get(key)
        if isinstance(branch, (list, tuple)):
            for nested in branch:
                walk(nested)
    if len(found) != 1:
        return None
    return next(iter(found.items()))


@effect_handler("sequence")
def sequence(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Perform each step in order (CR 608.2: a spell's instructions resolve in
    the order written)."""
    return _run(game, _steps(instruction, "steps"), context)


def evaluate_condition(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    """Evaluate a lowered condition payload.

    Kept small on purpose: an unrecognized condition returns False rather than
    guessing, and the grammar refuses to lower conditions it cannot describe, so
    an unknown condition never reaches here from a grammar-compiled card.
    """
    kind = payload.get("kind")

    if kind == "all_of":
        # Every part, and an empty list is False rather than the vacuous True
        # `all([])` would give: a conjunction that lowered to nothing is a
        # condition nobody wrote, and answering True would run the effect
        # unconditionally.
        parts = payload.get("conditions") or []
        return bool(parts) and all(
            evaluate_condition(game, context, part) for part in parts
        )

    if kind == "any_of":
        # Any part, and an empty list is False for ``all_of``'s reason one
        # clause up: a disjunction that lowered to nothing is a condition nobody
        # wrote, and `any([])` is already False — the emptiness is stated here so
        # the two joiners read the same way rather than agreeing by accident.
        parts = payload.get("conditions") or []
        return bool(parts) and any(
            evaluate_condition(game, context, part) for part in parts
        )

    # Every other kind is answered by one of three families, each the handler
    # twin of the lowering module that produces its kinds: the game as it is
    # **now** (``_conditions``), a **record** of something already done
    # (``_record_conditions``) and a **colour** (``_color_conditions``). A family
    # answers ``NotImplemented`` for a kind that is not its own. Every branch in
    # all three tests ``kind`` alone and returns, and no two test the same kind,
    # so the order the families are asked in cannot change an answer.
    for family in (
        evaluate_state_condition, evaluate_record_condition,
        evaluate_color_condition,
    ):
        answer = family(game, context, payload, kind)
        if answer is not NotImplemented:
            return answer
    return False


@effect_handler("count_objects")
def count_objects(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Count the number of permanents." (Chaos Moon.) CR 107.1's number, taken
    once and written into this resolution's scratchpad.

    Nothing on any board changes. The two sentences after it read the record
    through ``if_then``'s ``counted_number`` condition, which is what makes
    "If the number is odd, … If the number is even, …" *one* count rather than
    two — and, on this card, what keeps the second branch from being read as
    CR 603.4's intervening "if" and gating the whole ability on the first.

    Every battlefield, not the controller's: "permanents" names every object in
    the zone whoever controls it (CR 110.1). A narrower phrase travels as the
    filter payload and is asked through ``subject_matches``, with the ability's
    controller as CR 109.5's observer, so a narrowing that needs the layers is
    answered rather than dropped.

    A control-flow handler rather than a board one for ``flip_coin``'s reason:
    the count has no effect of its own — it is the value the conditionals behind
    it branch on.
    """
    from ..subject_filters import subject_matches

    filters = instruction.payload.get("filter") or {}
    observer = game.players.index(context.caster) if context.caster in game.players else None
    counted = sum(
        1 for perm in game.all_permanents()
        if subject_matches(game, perm, filters, observer=observer,
                           source=context.source_permanent)
    )
    context.results[str(instruction.payload.get("result_key") or "counted_number")] = counted
    game.log.append(
        f"{getattr(context.card, 'name', 'an effect')}: counted {counted}"
    )
    return True, "resolved"


@effect_handler("flip_coin")
def flip_a_coin(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Flip a coin." (CR 705.1.)

    One draw from the RNG, recorded in this resolution's scratchpad. The
    sentences after it read that record through ``if_then``'s ``coin_flip``
    condition, which is what makes "If you win the flip, … If you lose the flip,
    …" (Bottle of Suleiman) *one* coin rather than two: CR 705.2 says only the
    player who flipped wins or loses that flip, so there is one result and both
    sentences read it.

    A control-flow handler rather than a board one because the flip has no
    effect of its own — it is the randomiser the conditionals branch on, and it
    lives beside ``if_then`` for the same reason ``sequence`` does.
    """
    won = flip_coin_for(game, context.caster, flip=flip_coin)
    context.results["coin_flip"] = won
    game.log.append(
        f"{context.card.name}: {'won' if won else 'lost'} the coin flip"
    )
    return True, "resolved"


@effect_handler("flip_coins_until_loss")
def flip_coins_until_loss(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Flip a coin that many times or until you lose a flip, whichever comes
    first." (Squee's Revenge.)

    ``flip_coin`` in a loop with the two bounds the sentence prints: the number
    an earlier step of this resolution recorded, and the first loss. Each flip
    is CR 705.1's own — one draw from the seeded RNG, logged in the words the
    single flip logs, so a run reads as that many flips rather than as one
    event — and CR 705.2's: the resolving player's, won or lost by nobody else.

    Two records for the two questions the sentence behind it asks. ``coin_flip``
    is whether the run **lost no flip**, which is what "if you win all the
    flips" means and why the ordinary flip conditional can read it; a run of
    zero flips lost none (and pays for none). ``COIN_FLIPS_MADE`` is how many
    coins were actually flipped — a loss ends the run, so it can be fewer than
    the number chosen, and "for each flip" counts these.

    The loop is bounded by its own arithmetic and not by the number: a seat may
    name any number at all (CR 107.1), and the run still ends at the first
    loss.

    **No** ``amount_from`` is "flip a coin **until you lose a flip**" (Crazed
    Firecat): the first loss is the only bound. A third record says how many
    flips were won (``COIN_FLIPS_WON``), which "for each flip you won" reads.
    A run that has not lost by :data:`_UNBOUNDED_FLIP_GUARD` flips stops
    there: the rules put no ceiling on it, but a coin a test or a future
    effect rigs to always win must not hang the game.
    """
    bounded = instruction.payload.get("amount_from") is not None
    limit = (
        max(0, int(context.results.get(str(instruction.payload["amount_from"]), 0) or 0))
        if bounded else _UNBOUNDED_FLIP_GUARD
    )
    card_name = getattr(context.card, "name", "an effect")
    made = 0
    clean = True
    while made < limit and clean:
        clean = flip_coin_for(game, context.caster, flip=flip_coin)
        made += 1
        game.log.append(
            f"{card_name}: {'won' if clean else 'lost'} the coin flip"
        )
    context.results["coin_flip"] = clean
    context.results[COIN_FLIPS_MADE] = made
    context.results[COIN_FLIPS_WON] = made if clean else made - 1
    if bounded:
        game.log.append(
            f"{card_name}: {made} of {limit} flip(s) made, "
            + ("every one won" if clean else "the last one lost")
        )
    else:
        game.log.append(
            f"{card_name}: won {context.results[COIN_FLIPS_WON]} flip(s) "
            "before losing one"
        )
    return True, "resolved"


#: Where an unbounded run of flips ("until you lose a flip") gives up. Not a
#: rule — CR 705 sets no ceiling — but the probability of a fair coin reaching
#: it is 2**-1000, so only a rigged coin ever does.
_UNBOUNDED_FLIP_GUARD = 1000


@effect_handler("coin_flip_stakes_loop")
def coin_flip_stakes_loop(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Game of Chaos: one round of the flip, and the offer that buys the next.

    CR 705.2: the flip is the *caster's*, and who it names is what makes the two
    halves different — winning gains the caster the stake and takes it off the
    target, losing does the reverse, and the player the round went **against**
    is not the one who decides whether it happens again. The winner decides.

    The next round is armed by *answering* that offer rather than by a loop
    here, for the reason ``offers.unless_player_pays`` chains the same way: the
    two seats answer alternately and neither answer exists while the other is
    being asked. The stake the next round runs at rides the re-armed
    instruction's payload, which is where the doubling lives — the same
    ``{**payload, …}`` shape the chain beside it uses for its seat counter.

    A resolution with no opponent to point at does nothing: "target opponent"
    is chosen at announcement (CR 601.2c), and a spell whose only target is
    gone has nobody to stake against.
    """
    caster = context.caster
    opponent = context.target
    card_name = getattr(context.card, "name", "an effect")
    if opponent is None or opponent is caster:
        game.log.append(f"{card_name}: no opponent to play against")
        return True, "resolved"
    stake = max(0, int(instruction.payload.get("stake", 1)))
    won = flip_coin_for(game, caster, flip=flip_coin)
    context.results["coin_flip"] = won
    if won:
        game._gain_life(caster, stake, card_name)
        opponent.life -= stake
        decider = caster
    else:
        caster.life -= stake
        game._gain_life(opponent, stake, card_name)
        decider = opponent
    game.log.append(
        f"{card_name}: {caster.name} {'won' if won else 'lost'} the flip "
        f"for {stake} life"
    )
    # "Double the life stakes with each flip." Applied to what the *next* round
    # would run at, not to this one: the first flip is for the printed number.
    next_stake = stake * 2 if instruction.payload.get("doubling") else stake
    game.arm_pending_choice(
        "flip_again", game.players.index(decider),
        card_name=card_name,
        stake=next_stake,
        _again=OracleInstruction(
            instruction.kind, "", {**instruction.payload, "stake": next_stake}
        ),
        _context=context,
    )
    return True, "resolved"


@effect_handler("if_then")
def if_then(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If <condition>, <then>" — including CR 603.4 intervening-if conditions,
    which the legacy compiler dropped, so conditional triggers always fired."""
    condition = instruction.payload.get("condition") or {}
    if evaluate_condition(game, context, condition):
        return _run(game, _steps(instruction, "then"), context)
    return _run(game, _steps(instruction, "else"), context)


@effect_handler("may")
def may(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"You may pay {N}. If you do, …" / "You may <action>."

    Offers an optional cost or action to its controller and, when taken, runs
    the consequence as an ordinary instruction sequence. That is what lets an
    optional cost sit in front of *any* effect: the previous mechanism could
    only express "gain N life", "draw N cards" or "take N damage", so every card
    outside that vocabulary needed its own name-keyed hook.

    The prompt is an ``optional_pay`` entry on the generic pending-choice queue,
    and the *consequence* has no fixed shape.

    **The actor may name more than one seat.** "Each player may ante the top
    card of their library" (Rebirth) is one decision per player, and each of
    them is an ordinary prompt on that queue — so the same three loops in
    ``web/prompts.py`` render, gate and default them, and the spell stays on the
    stack until the last one is answered (CR 608.2, CR 117.3b).
    """
    actor = instruction.payload.get("actor", "you")
    seats = _offered_seats(game, actor, context)

    if not seats and actor in ("event_subject_player", "event_subject_controller"):
        # The event froze a seat and that player has since left the game.
        # CR 800.4f: a cost a departed player would pay or choose to pay **is
        # not paid** — so the offer is never made and its decline branch still
        # applies, exactly as an unaffordable offer's does below ("destroy
        # that land unless that player pays {1} or 1 life", Erosion, with the
        # payer already gone). Only the lost seat takes this branch: a seat
        # nobody *recorded* is a phrase that named nobody, and no consequence
        # of an offer that was never printed for anyone applies.
        seat = (context.trigger_context or {}).get(actor)
        if (
            isinstance(seat, int)
            and 0 <= seat < len(game.players)
            and game.players[seat].lost
        ):
            on_decline = _steps(instruction, "otherwise")
            if on_decline:
                _run(game, on_decline, context)
            return True, "resolved"

    # A named seat rebinds for the same reason every member of `_EACH_ACTORS`
    # does: the offer is made to somebody the resolution was not already
    # holding, so "that player" and every bare imperative inside the offer mean
    # the seat that took it. Tariff's decline branch sacrifices out of that
    # seat's own board.
    rebind = (
        isinstance(actor, int)
        or actor in _EACH_ACTORS
        # An offer the *event's* seat takes and then carries out — see
        # `_EVENT_ACTORS`. The action is the evidence: a `may` with only a cost
        # names a payer, and its consequence prints its own subject.
        or (actor in _EVENT_ACTORS and bool(_steps(instruction, "action")))
    )

    def offer(player_index: int) -> None:
        _offer_to_seat(
            game, instruction, context, player_index, rebind=rebind,
            aim=actor in _NAMED_SEAT_ACTORS,
        )

    # Through ``run_resumable`` like every other loop in this file, and for the
    # reason ``engine/resumption.py`` states: the offer suspends on an
    # interactive seat's answer, and a bare ``for`` here would lose every seat
    # behind the one that stopped ("each player may ante the top card of their
    # library" — Rebirth). The loop is the last thing this handler does, which
    # is the other half of that rule.
    run_resumable(game, seats, offer)
    return True, "resolved"


#: The actors whose offered seat is **not** the one the resolution already
#: holds. Only these rebind ``context.target`` below: an offer to "you" or to
#: "that player" is made to a seat the spell or ability already chose, and
#: overwriting it would point every "target" in the accept branch at the wrong
#: object (Niambi's bounce, Tolarian Kraken's reflexive tap).
#:
#: "Defending player" is one seat and still belongs here, which is what the set
#: is actually about: CR 506.2 makes it somebody the *combat* named, so a bare
#: imperative inside the offer ("defending player may **draw a card**",
#: Sibilant Spirit) means that seat and not the attacker's controller.
_EACH_ACTORS = frozenset({
    "each_player", "each_opponent", "defending_player",
    # "The player who reveals the card with the greatest mana value **may
    # change the target or targets**" (Psychic Battle). One seat, and somebody
    # the *reveal* named rather than somebody the resolution was holding — so
    # the bare imperative inside the offer is that seat's to perform, exactly
    # as "defending player may draw a card" is the defender's.
    "revealed_greatest_mana_value",
})

#: …and the actors named by the **firing event** (CR 603.10), which are the same
#: kind of seat as "defending player" above: somebody the event picked, not
#: somebody the resolution was already holding.
#:
#: They rebind only when the offer carries an **action**, and that is the whole
#: distinction the printed sentences draw. "That player may pay {4}" names a
#: *payer*, and what happens next has its own printed subject ("you may draw a
#: card" — Mystic Remora); "that player may **sacrifice a creature of their
#: choice**" (Pillar Tombs of Aku) and "that player may **discard a card at
#: random**" (Apathy) name somebody who *performs*, and CR 601.2b makes the seat
#: that takes an offer the seat that does what it says. Both of those cards
#: sacrificed and discarded out of the **enchantment controller's** board and
#: hand — the opposite player from the one printed — because the offer moved and
#: the performer did not.
#:
#: Conditional rather than unconditional, so the cost-only offers above are
#: untouched: rebinding one of those would hand Mystic Remora's draw to the
#: opponent who declined to pay for it.
_EVENT_ACTORS = frozenset({"event_subject_player", "event_subject_controller"})


#: The actors that name **one seat the resolution's target channel does not
#: hold**, and whose offer therefore *aims* the branches at it: ``target``
#: becomes the offered seat, so a player word inside the offer ("has Molten
#: Influence deal 4 damage to **them**") means the seat that was asked.
#:
#: Narrower than the rebind the two sets above make, and on purpose. Those
#: move ``caster`` too, because their offered seat *performs* the action
#: (sacrifices, discards, draws). Here nobody but the effect's controller
#: performs anything: the spell deals the damage, and the spell's controller
#: is who "a source you control" must go on naming (CR 109.5) - moved, a
#: punisher's damage would be a source the punished player controls.
_NAMED_SEAT_ACTORS = frozenset({STACK_TARGET_CONTROLLER})


#: The instruction kinds that act on **an object on the stack** - which, by
#: the time a queued answer is drained on the headless path, has resolved and
#: left. See the last step of :func:`_offer_to_seat`.
_STACK_OBJECT_KINDS = frozenset({"counter_top_stack_spell", "counter_stack_ability"})


def _offer_to_seat(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    player_index: int, rebind: bool = False, aim: bool = False,
) -> None:
    """Arm one seat's copy of the offer.

    With *rebind*, ``context.target`` becomes the offered seat — which is what
    makes "that player" inside the offer and inside its if-you-do branch mean
    the player who took it. Only an offer made to a *set* of seats rebinds:
    everywhere else the target is the one the spell or ability already chose,
    and overwriting it would aim the accept branch at the wrong object.

    ``context.caster`` is deliberately **not** moved without it, and the note
    here used to call that a known limit no card in the pool printed. **Two
    did.** "At the beginning of each player's upkeep, that player may sacrifice
    a creature of their choice" (Pillar Tombs of Aku) and "…that player may
    discard a card at random" (Apathy) are exactly the pair: an action inside
    the offer addressing the effect's controller, so the *enchantment's*
    controller sacrificed and discarded while ``offers._action_is_takeable`` had
    tested the offered player's board and hand. Both are now rebinding offers —
    see ``_EVENT_ACTORS`` — and Mind Bomb, the card the note said would have
    been the third, is still collapsed into a per-seat prompt before it reaches
    here (``grammar/lowering/_collapses._each_player_optional_discard``).
    """
    player = game.players[player_index]
    # **The offer is about the board as it stands now**, and the entry outlives
    # this call: an ``optional_pay`` does not suspend its loop, so "for each of
    # those creatures, its controller may pay …" (Winter's Chill) arms every
    # prompt before any is answered, and by then the loop has moved on and
    # restored the iteration it was on. The context is a dataclass, so a replace
    # freezes the per-iteration binding while leaving the resolution's
    # scratchpad shared by reference — which is exactly CR 608.2h's split
    # between what an offer was about and what the resolution knows.
    context = dataclasses.replace(context)
    if aim:
        # See ``_NAMED_SEAT_ACTORS``: the player word inside the offer names
        # the offered seat, and the performer does not move.
        context = dataclasses.replace(context, target=player)
    if rebind:
        # **Both ends of the sentence move to the offered seat.** ``target`` is
        # what a back-reference to a player reads ("that player's life total
        # becomes 20", Rebirth), and ``caster`` is who is *performing* the
        # branch — a bare imperative inside the offer ("any player may
        # **sacrifice two lands of their choice**", Worms of the Earth) means
        # the seat that took it, and CR 601.2b makes that seat the one who
        # picks between printed alternatives. Rebinding only the first left the
        # ability's controller sacrificing their own lands for every other
        # player's answer, and choosing, out of their own board, which
        # alternative each other player was offered.
        #
        # **Except a target the announcement already chose.** "…**may** have it
        # deal damage equal to its power to **any target** of their choice"
        # (Pandemonium) is an offer whose action carries a target picked as the
        # ability went on the stack (CR 603.3d), and ``target`` is where a
        # player-shaped one is held — so rebinding it aims the damage at the
        # seat that was *offered* rather than at the one they chose, silently
        # and in that player's favour. The performer still moves: who has the
        # creature deal the damage is the offered seat, which is what ``caster``
        # says.
        #
        # Derived from the compiled program rather than declared as a payload
        # key, through the same reader the trigger picker used to announce it —
        # so "did this line print a target?" has one answer at both moments.
        # Ten of the eleven cards in the pool that reach this rebind print no
        # target at all and are untouched.
        from ..targeting import announces_a_target

        if announces_a_target(_steps(instruction, "action"), described_only=True):
            context = dataclasses.replace(context, caster=player)
        else:
            context = dataclasses.replace(context, target=player, caster=player)
    # The whole printed cost, symbol by symbol — "you may pay {1}{B}" (Liliana's
    # Devotee) is a dict, not the number 2, because a payment that counted to a
    # number could only ever collect generic mana.
    cost = _resolved_cost(instruction.payload.get("cost"), context, game)
    # "…unless you pay {1} **for each card in your hand**." (Extravagant
    # Spirit, Megatherium.) The printed price times a count taken **now**
    # (CR 608.2), through the one evaluator every computed amount in this
    # engine goes through — so "for each card in your hand" means here what it
    # means in a damage amount or a draw.
    #
    # A count of zero is a cost of nothing, and that is the rule rather than an
    # edge case: an empty hand makes the toll {0}, which its payer can always
    # cover, so the creature stays. The dict is emptied rather than left with
    # zero-valued pips, because ``_player_can_pay_optional`` and the prompt both
    # read "no cost" off emptiness.
    per_each = instruction.payload.get("cost_per")
    if per_each is not None and cost:
        from ._amounts import count_from_payload

        times = max(0, count_from_payload(game, context, dict(per_each)))
        cost = {symbol: amount * times for symbol, amount in cost.items()}
        cost = {symbol: amount for symbol, amount in cost.items() if amount}
    on_accept = _steps(instruction, "action") + _steps(instruction, "then")
    on_decline = _steps(instruction, "otherwise")
    # CR 603.12: a *separate* ability the payment creates, so it is carried
    # separately and never folded into the accept branch. The difference is its
    # targets: it chooses them when it is created, where the accept branch has
    # only the ones this resolution already has — and this trigger fired on a
    # card being drawn, which named nothing at all.
    on_reflexive = _steps(instruction, "reflexive")

    # CR 118.6: a cost based on the mana cost of an object that has none is
    # unpayable, so the offer is not made and the penalty applies — the same
    # outcome as the unaffordable offer below, reached before an empty cost can
    # be read as a free one.
    if _derived_cost_is_unpayable(instruction.payload.get("cost"), context, game):
        if on_decline:
            _run(game, on_decline, context)
        return

    # An offer the player cannot afford is never made; its decline branch (a
    # "…unless you pay" penalty) still applies. The alternative payment is part
    # of the same question — a player with the life but not the mana can still
    # take this offer — so it is asked through the one predicate rather than by
    # a second test here.
    # "… unless its controller pays **life equal to its toughness**" (Essence
    # Vortex). A life cost with no mana half, read at resolution because the
    # number can be a computed characteristic (CR 613) — through the same
    # evaluator every other resolution-time count goes through, so "its
    # toughness" means here what it means anywhere else.
    life_cost = _resolved_life_cost(game, instruction.payload.get("life_cost"), context)
    # "…unless they pay {B} **or {3}**" (Lim-Dûl's Hex). Resolved like the cost
    # itself, so a printed {X} in an alternative means what it means in the
    # first one.
    alternatives = [
        _resolved_cost(alternative, context, game)
        for alternative in (instruction.payload.get("cost_alternatives") or ())
    ]
    # "Cannot afford" is the plan's answer for a seat the engine answers for.
    # A person is still asked whenever they hold mana the plan does not tap
    # (`Game.payment_may_be_offered`): the choice in "unless" is theirs.
    if (cost or life_cost) and not game.payment_may_be_offered(player, {
        "cost": cost,
        "cost_alternatives": alternatives,
        "life_cost": life_cost,
        "life_alternative": int(instruction.payload.get("life_alternative", 0) or 0),
    }):
        if on_decline:
            _run(game, on_decline, context)
        return

    # The same rule for an *action* cost ("you may sacrifice another
    # creature", Dire Fleet Warmonger): with nothing legal to sacrifice, the
    # offer is never made — otherwise accepting would run the if-you-do branch
    # against a cost that never happens.
    #
    # "…sacrifice a creature **or** discard a creature card" (Crypt Lurker) is
    # the same question asked of each alternative: a mode the player cannot take
    # is dropped from the offer, and only when *none* of them is takeable does
    # the whole offer go unmade. Rebuilding the accept branch is what carries
    # that through to the prompt — an unofferable mode left in the list is one
    # the player can pick and then not get.
    on_accept, offerable = _narrow_to_takeable_actions(game, player, on_accept, context)
    if not offerable:
        if on_decline:
            _run(game, on_decline, context)
        return

    # "…may pay {1} **or {2}**. If that player doesn't, … If that player pays
    # only {1}, …" (Winter's Chill.) What each option buys, index-aligned with
    # `[cost] + cost_alternatives`. Private, because the values are
    # instructions; the prompt renders the *costs*, which are already public.
    option_effects = [
        tuple(steps) for steps in (instruction.payload.get("option_effects") or ())
    ]
    entry = {
        "card_name": context.card.name,
        "cost": cost,
        "cost_alternatives": alternatives,
        "_option_effects": option_effects,
        "life_cost": life_cost,
        "life": 0,
        "_source_permanent": context.source_permanent,
        # Instructions to run on accept/decline, with the resolution context
        # they belong to. _pay_optional executes these when present.
        "_on_accept": on_accept,
        "_on_decline": on_decline,
        "_on_reflexive": on_reflexive,
        "_context": context,
        # Who the card offers this to, as printed: one seat's answer is read
        # differently when every seat is being asked the same question
        # (``ai_prompts.offer_buys_own_drawback``).
        "_offered_actor": instruction.payload.get("actor", "you"),
    }
    # "…**If you do**, untap this land." (Forsaken City.) Where the offered
    # action is a pick the seat may still not make, the lowering names what
    # "do" has to mean (``then_if``) and where the if-you-do steps start; the
    # accept branch itself stays the plain steps every reader of it expects,
    # and ``_pay_optional`` applies the gate as it runs them.
    if instruction.payload.get("then_if") is not None:
        entry["_then_if"] = dict(instruction.payload["then_if"])
        entry["_then_from"] = len(_steps(instruction, "action"))
    # CR 118.8's alternative payment ("…pays {1} **or 1 life**", Erosion): one
    # offer the payer may cover either way, so it rides the same entry rather
    # than arming a second prompt whose decline would apply the penalty twice.
    life_alternative = int(instruction.payload.get("life_alternative", 0) or 0)
    if life_alternative:
        entry["life_alternative"] = life_alternative
    if option_effects:
        # The payer is *choosing* between the printed costs rather than covering
        # one offer whichever way they can, so the prompt has to offer them one
        # by one and send back which. The labels are what the client shows; the
        # index is the answer, and it means the same thing on both sides because
        # `pending_choices.optional_pay_options` builds the list in printed order
        # for every reader.
        entry["graded_options"] = [
            mana_cost_label(option) for option in (cost, *alternatives)
        ]
    # "**Look at the top two cards of your library.** You may sacrifice this
    # enchantment and pay {2}{G}{G}." (Preferred Selection.) CR 701.20e's look,
    # carried out here rather than by a step in front of the offer: the seat
    # being shown the cards is the seat being asked, and the whole point of the
    # first sentence is that the decision is not made blind. The names ride the
    # prompt, which is the one channel this engine has for telling one player
    # something without also asking them a second question.
    #
    # Read off the library **now** rather than frozen at lowering time, because
    # a look is what is there when it happens — and the offer holds priority
    # (`ChoiceSpec.holds_priority`), so nothing can change the pile between the
    # look and the pick behind it.
    looked = int(instruction.payload.get("looked_at_library_top", 0) or 0)
    seen = [card.name for card in player.library[:looked]] if looked > 0 else []
    if seen:
        entry["looked_at"] = seen
    preamble = f"Top of your library: {', '.join(seen)}. " if seen else ""
    if cost:
        printed = " or ".join(
            mana_cost_label(option) for option in (cost, *alternatives)
        )
        entry["prompt"] = preamble + (
            f"Pay {printed} or {life_alternative} life?"
            if life_alternative
            else f"Pay {printed}?"
        )
    elif life_cost:
        entry["prompt"] = f"{preamble}Pay {life_cost} life?"
    elif (
        on_accept
        and on_accept[0].kind == "put_exiled_cards_into_zone"
        and on_accept[0].payload.get("zone", "hand") == "hand"
    ):
        # "You may put **that card** into your hand" (Tainted Pact). A free
        # offer says nothing about itself, and this one is a decision about a
        # particular card — so the prompt names it. Public: the card is face up
        # in exile and the exile's own log line has already said what it is.
        offered = _exiled_cards_still_in_exile(game, context)
        if offered:
            entry["prompt"] = (
                f"{preamble}Put {', '.join(card.name for card in offered)} "
                "into your hand?"
            )
    # Mirror a plain "gain N life" consequence into the legacy `life` field so
    # the prompt UI keeps describing what accepting does. Display only —
    # _pay_optional runs the instruction branch and returns before reading it.
    # This goes away when the pending-choice queue carries its own description.
    if len(on_accept) == 1 and on_accept[0].kind == "target_gains_life":
        amount = on_accept[0].payload.get("amount")
        if isinstance(amount, int):
            entry["life"] = amount
    choice = game.arm_pending_choice("optional_pay", player_index, **entry)
    # **An offer about something on the stack cannot outlive the resolution
    # that made it.** "Counter target instant or sorcery spell unless its
    # controller has Molten Influence deal 4 damage to them": the spell the
    # decline branch counters is the next object to resolve. An interactive
    # game holds this resolution open until the seat answers
    # (``resolving_stack_item``, CR 608.2). A headless one does not - the
    # object pops and the queue is drained when the stack is empty
    # (``StackMixin._settle``) - which for every other offer is a harmless
    # reordering and for this one is the whole card: the answer arrived after
    # the spell it was about had resolved, so a declined punisher countered
    # nothing and a paid Imprison bought a counter of an ability that had
    # already happened. So where nothing is holding the resolution, the seat
    # nobody is asking answers where the offer stands. Three cards print the
    # shape (Imprison, Mana Vortex, Molten Influence).
    if (
        choice is not None
        and game.resolving_stack_item is None
        and player_index not in game.interactive_seats
        and any(
            step.kind in _STACK_OBJECT_KINDS
            for step in (*on_accept, *on_decline)
        )
    ):
        game._default_optional_pay(choice)


@effect_handler("choose_one")
def choose_one(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A ``choose_one`` reached at *resolution*: alternatives that are a step of
    an effect already running ("that creature gains flying or first strike").

    Not a modal **ability**. A modal triggered ability chooses its mode as it is
    put on the stack (CR 700.2b), which
    ``mixins/stack/trigger_targets._choose_trigger_mode`` does, and by the time such
    an ability resolves ``_chosen_trigger_instruction`` has already substituted
    the chosen mode — so a modal head never arrives here with a mode still to
    pick. What does arrive is every choice CR 608.2d makes "while applying the
    effect": the nested form, **and a whole ability whose effect is one "A or
    B"** — Urborg's "loses first strike or swampwalk", Dwarven Armorer's "a
    +0/+1 counter or a +1/+0 counter", Gabriel Angelfire's "choose flying, first
    strike, trample, or rampage 3". Those are not modal (CR 700.2 is a bulleted
    list), so they went on the stack with nothing chosen and are asked here,
    after the opponent has had the chance to respond. Which ``choose_one`` is
    which is ``modal_triggers.MODAL_HEAD_KEY``. There is no announcement to hang
    the choice on and the branch simply runs against this same context — the
    targets the ability was activated with included (CR 602.2b).

    The pick is a ``mode_choice`` pending prompt for an interactive controller;
    every other seat takes the default (the first printed mode - a stated
    policy, not a valuation) the moment it is armed, because the resolution has
    to finish.
    """
    modes = tuple(instruction.payload.get("modes") or ())
    if not modes:
        return True, "resolved"
    # **Whoever is performing the alternatives picks between them** (CR 601.2b).
    # Absent, that is the effect's own controller, which is every printed
    # "gains flying or first strike" in the pool. ``chooser`` names the other
    # case: an offer made to a seat that is not the controller — "unless **that
    # player** sacrifices a permanent of their choice or discards a card"
    # (Forbidden Ritual) — where ``_offer_to_seat`` deliberately leaves
    # ``context.caster`` alone, so without this the caster would choose which
    # price the opponent pays out of the opponent's own board.
    #
    # Read through ``_offered_seats``, the same function that decided who was
    # being offered the price: two readers of one printed word, so the seat
    # asked to choose and the seat the price is charged to cannot differ.
    chooser = instruction.payload.get("chooser")
    if chooser is None:
        performer = context.caster
    else:
        seats = _offered_seats(game, str(chooser), context)
        if not seats:
            # Nobody to ask. The honest outcome, and the one every branch of
            # ``_offered_seats`` already gives for a seat that has left or that
            # nothing recorded: the offer around this step was never made.
            game.log.append(
                f"{context.card.name}: there is nobody to choose an alternative"
            )
            return True, "resolved"
        performer = game.players[seats[0]]
    # CR 601.2b/119.4: a player chooses among the alternatives they are *able*
    # to take. The same predicate ``may``'s offer narrows through, asked here
    # too — a bare ``choose_one`` reached mid-resolution had no narrowing at
    # all, so "pay 4 life or …" was offered to a player at 2 life as a mode
    # they could pick and then not perform. One table, both readers.
    #
    # A narrowing that removes *every* mode leaves nothing to choose, and the
    # step is over: that is CR 608.2's "as much as possible" and not a prompt
    # with an empty list.
    takeable = tuple(
        mode for mode in modes
        if _action_is_takeable(
            game, performer, mode["instruction"], context.source_permanent
        )
    )
    if not takeable:
        game.log.append(
            f"{context.card.name}: no alternative can be taken"
        )
        return True, "resolved"
    modes = takeable
    player_index = game.players.index(performer)
    game.arm_pending_choice(
        "mode_choice", player_index,
        card_name=context.card.name,
        labels=[mode["label"] for mode in modes],
        _modes=tuple(mode["instruction"] for mode in modes),
        _context=context,
    )
    return True, "resolved"


@dataclasses.dataclass(frozen=True)
class _Seat:
    """One turn of a loop over *players* — "for each player, …" (Lim-Dûl's
    Hex). A wrapper rather than a bare index, so the loop body can tell a seat
    from a permanent without asking what type it is."""

    index: int


#: One turn of a **counted** loop — "for each 1 life you lost" (Oath of
#: Lim-Dûl). A sentinel rather than None, because None is a legitimate absent
#: object elsewhere in this file and the two must not collapse: one is "run the
#: body again", the other is "there was nothing here".
_A_REPETITION = object()

#: The last item :func:`for_each` walks: not a permanent, the *end* of the loop.
#: It exists because the restore of ``iteration_target`` has to be a step of the
#: loop rather than a line after it — see the handler's docstring.
_END_OF_ITERATION = object()


@effect_handler("for_each")
def for_each(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"For each <objects>, <effect>." The matching set is snapshotted before
    the first iteration so an effect that removes objects cannot shorten its own
    loop.

    Two kinds of set, and the payload says which. A **filter** names what the
    board holds right now. ``produced_by`` names what an earlier step of this
    same resolution recorded — "for each creature that **died this way**"
    (Glyph of Reincarnation), whose objects are in graveyards by the time this
    runs and cannot be found by any read of the battlefield.

    Around each iteration the per-object records an earlier step wrote are
    resolved to *this* object's entry (see
    ``OracleExecutionContext.iteration_seats``), so an inner effect asking
    "whose graveyard" asks by name and never has to know either the loop's
    object or the record's shape.

    Run through ``run_resumable``, like every other loop in this file. A step
    that stops to ask the player a question — a scry, a search, a CR 616.1e
    ordering — used to lose every iteration behind it here: this was a bare
    ``for``, so the handler returned "resolved" with half the sentence undone
    and nothing recorded the rest. ``engine/resumption.py`` states the rule the
    fix follows, and the rule's other half is why the restore below rides on a
    sentinel *item* rather than sitting after the call: work written after a
    resumable loop does not run when a step suspends.
    """
    filters = instruction.payload.get("iterator") or {}
    steps = _steps(instruction, "effect")
    produced_by = filters.get("produced_by")
    # "For each **1 life you lost**" (Oath of Lim-Dûl) — an iterator that is a
    # *number*, not a set: the loop has no objects, only the count the firing
    # event froze. Read first, because the two branches below both build a list
    # of permanents and this one has none to build.
    repeat_key = filters.get("repeat_from_trigger")
    # "For each **card less than two a player draws this way**" (Truce) — the
    # same shape one channel over: a number, not a set, and one number per seat.
    # It comes out of the *resolution scratchpad* rather than the firing event,
    # because the count is what an earlier step of this same effect recorded,
    # and it is a shortfall — the printed base minus what that seat did — so a
    # seat the record never mentions did none of it and is short by the whole
    # base. Read beside the counted form above and before the branches that
    # build a list of permanents, neither of which has a board to scan for it.
    repeat_record = filters.get("repeat_from_record")
    # "**For each player,** …" (Lim-Dûl's Hex) — a loop over *seats*. Read
    # beside the counted form and before the two object branches for the same
    # reason: neither of them has a board to scan for this.
    # "For each **additional {1}{R} you paid**" (Primitive Justice, Taste of
    # Paradise) — a number again, off the *cast* rather than off an event or the
    # scratchpad. CR 601.2b's optional additional cost was announced before this
    # spell was ever on the stack, and the pool that paid it emptied at the end
    # of that step (CR 500.5), so the announcement on the stack item's choices
    # is the only thing that can answer. Read beside the two counted forms
    # above, before either branch that wants a board to scan.
    repeat_cost = filters.get("repeat_from_cost")
    # "For each **delay counter removed this way**" (Delaying Shield) — the
    # fourth number, and the plainest: a count an earlier step of this same
    # effect wrote into the resolution scratchpad, with no seat and no base.
    # Read once, before the first repetition, for the snapshot rule above: a
    # body that removed more counters must not lengthen its own loop.
    repeat_result = filters.get("repeat_from_result")
    seat_set = filters.get("players")
    if repeat_result is not None:
        times = int(context.results.get(str(repeat_result), 0) or 0)
        matched = [_A_REPETITION] * max(0, times)
    elif repeat_cost is not None:
        paid = (context.choices or {}).get("additional_costs_paid") or {}
        times = int(paid.get(str(repeat_cost), 0) or 0)
        matched = [_A_REPETITION] * max(0, times)
    elif repeat_key is not None:
        times = int((context.trigger_context or {}).get(repeat_key, 0) or 0)
        matched = [_A_REPETITION] * max(0, times)
    elif repeat_record is not None:
        # Whose shortfall: the seat the loop *around* this one is on, which the
        # seat branch below binds as ``context.target``. Outside such a loop
        # there is no seat and the record is not a number about anybody, so the
        # body runs no times rather than against a seat nobody named.
        recorded = context.results.get(repeat_record.get("record")) or {}
        seat = (
            game.players.index(context.target)
            if context.target in game.players else None
        )
        times = (
            int(repeat_record.get("base", 0)) - int(recorded.get(seat, 0) or 0)
            if seat is not None else 0
        )
        matched = [_A_REPETITION] * max(0, times)
    elif seat_set is not None:
        # Through the same reader every multi-seat offer uses, so "each player"
        # names the same seats in the same order here as it does there — CR
        # 101.4's turn order from the active player, minus anyone who has left
        # the game (CR 800.4a).
        matched = [
            _Seat(index) for index in _offered_seats(game, str(seat_set), context)
        ]
    elif produced_by is not None:
        # The printed noun rides beside the record's name and is applied to it.
        # "For each **land** destroyed this way" after a sweep that destroyed
        # lands is a restatement — but a restatement checked is a restatement,
        # and one taken on trust is a loop over whatever the earlier step
        # happened to record.
        narrowing = {
            key: value for key, value in filters.items() if key != "produced_by"
        }
        matched = [
            item for item in (context.results.get(produced_by) or ())
            if not narrowing or permanent_matches_filter(item, narrowing)
        ]
    else:
        # "For each attacking creature **without flying**, …" (Tidal Flats).
        # Through ``subject_matches`` rather than the pure matcher, because a
        # loop over the board is the one iterator whose phrase is a live noun
        # phrase and can therefore ask a layer question: a creature *granted*
        # flying is a creature with flying (CR 613.1f), and the pure matcher —
        # which has no game — would have offered Tidal Flats' toll to it.
        from ..subject_filters import subject_matches

        observer = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        matched = [
            permanent
            for permanent in game.all_permanents()
            if subject_matches(
                game, permanent, filters, observer=observer,
                source=context.source_permanent,
            )
        ]
    previous = context.iteration_target
    previous_seats = context.iteration_seats

    def run_one(item) -> None:
        if item is _END_OF_ITERATION:
            context.iteration_target = previous
            context.iteration_seats = previous_seats
            return
        if item is _A_REPETITION:
            # A counted repetition names no object, so nothing rebinds: the
            # body means what it would mean written once, run again.
            _run(game, steps, context)
            return
        if isinstance(item, _Seat):
            # The seat this iteration is about becomes "that player" for the
            # length of it — the same rebinding ``_offer_to_seat`` makes for a
            # multi-seat offer, and the only way one printed sentence can name
            # a different player each time round. ``caster`` moves with it, for
            # that function's stated reason: a bare imperative inside the loop
            # means the seat the loop is on.
            seated = game.players[item.index]
            _run(
                game, steps,
                dataclasses.replace(context, target=seated, caster=seated),
            )
            return
        context.iteration_target = item
        context.iteration_seats = {
            **previous_seats,
            **_per_object_seats(context, item),
        }
        _run(game, steps, context)

    run_resumable(game, matched + [_END_OF_ITERATION], run_one)
    return True, "resolved"


def _per_object_seats(context: OracleExecutionContext, permanent) -> dict:
    """The seats an earlier step recorded about *permanent*, by record name.

    Read off ``PER_OBJECT_SEAT_RECORDS`` rather than by scanning the scratchpad
    for anything dict-shaped, because that table is what the grammar's lowering
    turns a printed referent into: one table, both readers, and no chance of a
    tally that happens to be keyed by number being read as a seat.

    An object with no entry contributes no binding at all, rather than a
    default. A seat guessed here is a graveyard nobody named, and the reader
    that finds nothing already knows what to do with that.
    """
    permanent_id = getattr(permanent, "permanent_id", None)
    if permanent_id is None:
        return {}
    seats: dict = {}
    for name in PER_OBJECT_SEAT_RECORDS.values():
        record = context.results.get(name)
        if isinstance(record, dict):
            seat = record.get(permanent_id)
            if isinstance(seat, int):
                seats[name] = seat
    return seats
