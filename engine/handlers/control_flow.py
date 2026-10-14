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
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from ..exiled_records import source_object
from ..named_counters import counters_on
from ..oracle_types import (CHOSEN_CARD_TYPE_THIS_WAY, CHOSEN_COLOR_THIS_WAY,
                            CHOSEN_NUMBER_THIS_WAY, CLAIMABLE_EXILED_CARDS,
                            COIN_FLIPS_MADE, EXILED_THIS_WAY_OBJECTS,
                            MANA_PAID_BY_SEAT, SWEPT_OWNER_SEATS,
                            REVEALED_TOP_CARDS_BY_SEAT,
                            PER_OBJECT_SEAT_RECORDS, PROCESS_ROUNDS_SO_FAR,
                            OracleInstruction)
from ..oracle_types import SECRET_NUMBERS_BY_SEAT
from ..oracle_types import (EVENT_SPELL_MANA_COST,
                            OTHER_THAN_EVENT_SUBJECT_PLAYER,
                            STACK_TARGET_CONTROLLER)
from ..repeated_offers import OFFER_TAKEN_RESULTS
from ..resumption import run_resumable
from ._common import (CHOSEN_CARD_TYPE, _card_matches_filter, attached_host,
                      flip_coin, flip_coin_for, permanent_matches_filter,
                      triggering_spell)
from .conditions import evaluate_condition
from .registry import effect_handler
from ..mana_payment import mana_cost_label

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


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

    def run_step(step) -> None:
        scoped = _role_scoped(game, step, context)
        if scoped is None:
            # CR 608.2b's last sentence: the announcement named this step's
            # object and it is no longer there, so the step does nothing while
            # the rest of the effect goes on. Skipped rather than run against a
            # context with a hole in it, which is how a damage step whose
            # creature had died came to hit a face instead.
            return
        supported, _ = game._execute_oracle_instruction(step, scoped)
        outcome["resolved"] = outcome["resolved"] or supported

    run_resumable(game, steps, run_step)
    return True, "resolved" if outcome["resolved"] else "no effect"


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
    from ..targeting import (payload_own_role, payload_role_slot, role_is_seat,
                             spec_roles)
    from ._common import resolve_role_permanent, resolve_role_player

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
    from ..targeting import payload_own_role

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
    """
    limit = max(
        0, int(context.results.get(str(instruction.payload.get("amount_from")), 0) or 0)
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
    game.log.append(
        f"{card_name}: {made} of {limit} flip(s) made, "
        + ("every one won" if clean else "the last one lost")
    )
    return True, "resolved"


@effect_handler("coin_flip_stakes_loop")
def coin_flip_stakes_loop(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Game of Chaos: one round of the flip, and the offer that buys the next.

    CR 705.2: the flip is the *caster's*, and who it names is what makes the two
    halves different — winning gains the caster the stake and takes it off the
    target, losing does the reverse, and the player the round went **against**
    is not the one who decides whether it happens again. The winner decides.

    The next round is armed by *answering* that offer rather than by a loop
    here, for the reason ``unless_player_pays`` above chains the same way: the
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


def _most_telling_mana_value(game: Game, seat: int, low: int, high) -> int:
    """The number a seat that is not asked names for a spell's "choose a
    number": the mana value borne by the most nonland permanents its opponents
    control, net of its own, within the printed range. Ties go to the larger
    number; a board that offers nothing names the floor.

    A stated policy over public information (CR 400.2 — the battlefield),
    deliberately blind to hands: a number chosen by reading one would be the
    seat looking at hidden cards.
    """
    tally: dict[int, int] = {}
    for controller, permanent in game.permanents_with_controller():
        if permanent.has_type("land"):
            continue
        value = int(getattr(permanent.effective_card, "cmc", 0) or 0)
        if value < low or (high is not None and value > high):
            continue
        tally[value] = tally.get(value, 0) + (-1 if controller == seat else 1)
    if not tally:
        return low
    return max(tally, key=lambda value: (tally[value], value))


@effect_handler("choose_number")
def choose_number(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a number between 0 and 7." (Shapeshifter.)

    Beside the coin flip for the same reason: it produces a *value* and no
    effect of its own, and what reads the value is a separate sentence on the
    card. The value is recorded on the permanent rather than in this
    resolution's scratchpad, because the sentence that reads it back is a
    characteristic-defining ability (CR 604.3) that keeps asking long after this
    resolution is over.

    The choice goes on the pending-choice queue, so an interactive controller is
    asked and every other seat takes the default the queue's resolver applies —
    which for a "you may" upkeep is *not changing the number*, the honest
    reading of declining the offer.

    **And into the resolution's scratchpad as well**, because a permanent is not
    the only kind of reader. "Choose a number greater than 0 and a color. …If
    that opponent reveals exactly **the chosen number** of cards of the chosen
    color, you draw a card." (Scrying Glass.) That reader is a later step of
    *this* resolution and asks once, so the permanent's standing answer is the
    wrong record for it twice over: the number this activation asked for is not
    necessarily the number the last one did, and the question is over before a
    permanent can be consulted again. Both records are written by this one step
    — the same discipline the colour handler below states — because a step that
    wrote only one of them would leave the other reader with nothing and no
    error, which is the shape this repo keeps finding.

    ``maximum`` may be None, which is a printed range with no ceiling ("greater
    than 0", CR 107.1) and not a missing bound. It travels as None to the prompt
    and to its resolver rather than being repaired into a number here: an
    invented ceiling is an answer the card would have accepted and the prompt
    would refuse.
    """
    permanent = context.source_permanent
    low = int(instruction.payload.get("minimum", 0))
    printed_high = instruction.payload.get("maximum")
    high = None if printed_high is None else int(printed_high)
    ceiling = instruction.payload.get("maximum_from_count")
    if ceiling is not None:
        # "Discard **any number** of cards at random." (Rites of Initiation.)
        # A number with no printed range: its ceiling is a count only the
        # resolution knows (the cards in the chooser's hand), and its reader is
        # the next step of this same resolution — so it is recorded in the
        # scratchpad alone, whatever the source is. A permanent's standing
        # ``chosen_number`` is a different record with a different reader, and
        # an ability printing this sentence must not overwrite it.
        if context.caster not in game.players:
            game.log.append(f"{context.card.name}: nobody to choose a number")
            return True, "resolved"
        seat = game.players.index(context.caster)
        from ._common import count_from_payload

        high = max(low, count_from_payload(game, context, dict(ceiling), instruction))
        # The policy for a seat nobody asks is the whole offer — the one
        # ``_default_discard`` states for the chosen form of this same
        # sentence ("discard any number of cards"), so the two spellings of
        # one decision default alike.
        context.results[CHOSEN_NUMBER_THIS_WAY] = high
        if high <= low:
            # One legal answer is not a choice, so nobody is asked.
            return True, "resolved"
        game.arm_pending_choice(
            "number_choice", seat,
            card_name=context.card.name if context.card is not None else "",
            permanent=None, minimum=low, maximum=high, default_number=high,
            result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
        )
        return True, "resolved"
    if permanent is None:
        # "Choose a number. Destroy all artifacts and creatures with mana value
        # equal to that number." (Void.) A *spell* choosing a number: there is
        # no permanent to keep a standing answer on and nothing reads one — the
        # only reader is a later step of this same resolution, which asks the
        # scratchpad. The same prompt, the same record, and the default a seat
        # that is not asked takes is the number that names the most of what the
        # other players control and the least of its own.
        if context.caster not in game.players:
            game.log.append(f"{context.card.name}: nobody to choose a number")
            return True, "resolved"
        seat = game.players.index(context.caster)
        default = _most_telling_mana_value(game, seat, low, high)
        # …unless the number is not a mana value at all. "Flip a coin **that
        # many times** or until you lose a flip" (Squee's Revenge): what the
        # value is for is the sentence behind the choice, read off the compiled
        # program where every such question is, and the length a seat nobody
        # asks takes is a weight beside it.
        from ..ai_valuation import (FLIP_RUN_LENGTH,
                                    chosen_number_bounds_flip_run)

        if context.card is not None and chosen_number_bounds_flip_run(
            context.card, instruction
        ):
            default = max(low, FLIP_RUN_LENGTH if high is None else min(high, FLIP_RUN_LENGTH))
        context.results[CHOSEN_NUMBER_THIS_WAY] = default
        game.arm_pending_choice(
            "number_choice", seat,
            card_name=context.card.name if context.card is not None else "",
            permanent=None, minimum=low, maximum=high, default_number=default,
            result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
        )
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    if seat is None:
        return True, "resolved"
    default = int(permanent.metadata.get("chosen_number", low))
    # Stamped **before** the prompt is armed, the discipline every other choice
    # in this file follows: a headless or AI seat is never blocked and the step
    # behind this always has a number to spend.
    context.results[CHOSEN_NUMBER_THIS_WAY] = default
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        minimum=low, maximum=high,
        default_number=default,
        result_key=CHOSEN_NUMBER_THIS_WAY, _context=context,
    )
    return True, "resolved"


@effect_handler("secretly_choose_numbers")
def secretly_choose_numbers(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Each player hides at least one item, then all players reveal them
    simultaneously." (Goblin Game.)

    ``choose_number``'s value once per seat, with the one thing that handler
    cannot give it: **no seat's answer exists for anybody else until every
    seat has one.** One ``secret_number`` prompt per seat, armed together in
    turn order (CR 101.4); the prompt's resolver writes
    ``SECRET_NUMBERS_BY_SEAT`` and says nothing, and the answer that completes
    the map is what logs the reveal — one line, every number at once. CR 101.4b
    is the default this card's words set aside: ordinarily "a player knows the
    choices made by the previous players when making their choice", and
    "hides … reveal them simultaneously" is the sentence saying these are not
    known.

    Nothing is stamped before the prompts are armed, which is the opposite of
    the discipline ``choose_number`` states and for a reason: a provisional
    number is a number, and the sentences behind this one would lose life by
    it if anything let them run early. A seat nobody asks is answered where
    the prompt is armed (``default_at_arm``) by ``ai_policy.choose_secret_number``,
    which reads life totals and never this map — so a seat the engine plays
    commits before any other answer exists and cannot be told one.

    The sentences behind this one wait for the last answer: the kind
    suspends, so the losses run once and against the whole map (CR 608.2).
    """
    low = max(0, int(instruction.payload.get("minimum", 0)))
    who = str(instruction.payload.get("who", "each_player"))
    seats = _offered_seats(game, who, context)
    card_name = context.card.name if context.card is not None else "Effect"
    # A fresh map per resolution: a copy of the spell, or the same ability
    # resolving twice, must not complete itself on the last one's answers.
    context.results[SECRET_NUMBERS_BY_SEAT] = {}
    if not seats:
        return True, "resolved"
    game.log.append(
        f"{card_name}: each {'opponent' if who == 'each_opponent' else 'player'} "
        f"secretly chooses a number of at least {low}"
    )
    for seat in seats:
        game.arm_pending_choice(
            "secret_number", seat,
            card_name=card_name, minimum=low, seats=list(seats),
            record=SECRET_NUMBERS_BY_SEAT, _results=context.results,
        )
    return True, "resolved"


@effect_handler("choose_color")
def choose_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a color." (Chromatic Armor's activated ability.)

    Beside ``choose_number`` above and for the same reason: the sentence
    produces a *value* and no effect of its own, and what reads it back is a
    separate sentence on the card — here the Aura's static shield, which
    answers to "sources of the last chosen color". So the colour is recorded on
    the permanent rather than in this resolution's scratchpad, and "last" is
    what overwriting means.

    The same metadata key CR 614.1c's entry-state version writes: a card may
    print both (this one does), and two keys would be a permanent with two
    chosen colours and a shield reading whichever one its author remembered.

    Its **own prompt** rather than that version's, though, for the reason
    ``choose_card_type`` beside it states one characteristic over: a choice made
    while an ability resolves may be read back by a later step of the *same*
    resolution, so it has to hold that resolution open until it is answered.
    ``enter_choice`` does not suspend and must not start — its readers are
    continuous effects that re-read the record on every recompute, so a late
    answer there really does take effect. This one is ``color_choice``, and the
    two cards already in the pool lose nothing by the move: Chromatic Armor's
    choose is the last step of its ability, and Hall of Gemstone's mana swap
    follows the permanent rather than snapshotting its answer.

    **And the answer is recorded in the resolution's scratchpad as well**, which
    is what the second kind of reader asks. "…If that opponent reveals exactly
    the chosen number of cards of **the chosen color**, you draw a card."
    (Scrying Glass.) That reader runs once, inside this resolution, and asking a
    permanent for its standing answer would be asking about whichever activation
    last set it. One step writes both records, because a step that wrote only
    one of them would leave the other reader with nothing and no error.

    A deterministic default is stamped first — the colour of the opposing object
    on the stack this choice is answering (``ai_valuation.threatening_color``),
    and failing one the colour the chooser's opponents hold most of among
    nontoken permanents, the policy the entry state applies — so a headless or
    AI seat is never blocked and never left with a colour nobody controls,
    which is a legal choice no player would make.
    """
    permanent = context.source_permanent
    card_name = getattr(context.card, "name", "an effect")
    chooser = instruction.payload.get("chooser")
    records_on = permanent
    # "Choose a color **of a permanent you control**." (Meteor Crater.) The
    # sentence narrows *which* colours may be named, so the set is computed
    # once the choosing seat is known (``_offered_colors`` below) and every
    # exit after that is held to it: an announced colour outside it is not an
    # answer, the default is one of its members, and the prompt offers nothing
    # else. None is CR 105.1's five.
    among = instruction.payload.get("among")
    offered: "tuple[str, ...] | None" = None
    if permanent is None or chooser == "you":
        # "Choose a color. X target creatures gain protection from the chosen
        # color until end of turn." (Prismatic Boon.) / "…gains protection from
        # **the color of your choice**" (Mother of Runes, Feat of Resistance —
        # the step ``_chosen_color_prelude`` puts in front of the grant.)
        # CR 109.5's "you": the controller of this spell or ability, which for
        # an activated one is the player who activated it rather than whoever
        # controls the permanent now.
        #
        # **Asked**, here, while the effect is applied (CR 608.2d). Both of
        # these used to read the colour off the announcement —
        # ``choices["new_color"]``, the wire field an any-colour *mana* ability
        # names its colour on — which CR 601.2b–c and 602.2b do not announce:
        # an interactive seat was never asked, an announcement without one did
        # nothing, and the player had to name the colour before the opponent
        # responded rather than after.
        #
        # The answer goes to this resolution's scratchpad alone. A spell has no
        # permanent to hold a standing record, and "the color of your choice" on
        # a permanent names a colour for this resolution's grant, not for a
        # continuous ability of the permanent's own (Chromatic Armor's shield is
        # what ``chosen_color`` is for) — a standing record would be a second,
        # staler answer, which is Wishmonger's reason below.
        if context.caster not in game.players:
            game.log.append(f"{card_name}: nobody to choose a colour")
            return True, "resolved"
        seat = game.players.index(context.caster)
        records_on = None
    else:
        seat = game.controller_index_of(permanent)
        # **A mana ability's choice is answered by its activation** (CR 605.3b).
        # "{T}: Choose a color. Add one mana of that color unless any player pays
        # {1}." (Rhystic Cave.) The ability resolves the moment it is activated, so
        # the colour its activator named with the activation *is* the choice CR
        # 608.2d asks for — the same channel every other colour a mana ability
        # makes already arrives on (``choices["new_color"]``, read by the "any
        # color", "{B} or {R}" and combination branches of ``add_mana_from_text``).
        # Stamped as ``color`` by the two sites that run a mana ability inline
        # (``mana_payment.answer_color_choices``), and only onto a choice the
        # controller makes, so nothing on the stack path is ever pre-answered.
        #
        # Without it the activator's named colour was ignored and the prompt's
        # deterministic default — the colour the *opponents* hold most of — was the
        # mana: an invented "{T}: Choose a color. Add one mana of the chosen
        # color." land asked for {R} made {W}.
        if among is not None and seat is not None:
            offered = _offered_colors(game, among, seat, permanent)
        announced = instruction.payload.get("color")
        if announced and not chooser and (
            offered is None
            or game._normalize_mana_color(str(announced)) in offered
        ):
            named = game._normalize_mana_color(str(announced))
            permanent.metadata["chosen_color"] = named
            context.results[CHOSEN_COLOR_THIS_WAY] = named
            game.log.append(
                f"{card_name}: {game.players[seat].name} chose {named}"
                if seat is not None else f"{card_name}: {named} chosen"
            )
            return True, "resolved"
    if chooser == "event_subject_player":
        # "At the beginning of each player's upkeep, **that player** chooses a
        # color." (Hall of Gemstone.) The seat the fire site froze (CR 603.10),
        # which is a different player every turn and never the enchantment's
        # controller except on their own turn. No record means the words named
        # nobody, and nothing is asked — the same rule every other reading of
        # this key follows, and the safe one.
        recorded = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card_name}: no recorded player to choose a colour")
            return True, "resolved"
        seat = recorded
    # "Target creature gains protection from the color of **its controller's**
    # choice until end of turn." (Wishmonger.) The third seat this sentence can
    # name, and the one that is not on either end of the ability: not the seat
    # that activated it — which is the ability's own controller and what "you"
    # would mean (CR 602.2a, CR 109.5) — and not the controller of the permanent
    # the ability is on, who under CR 602.2's "unless the object specifically
    # says otherwise" need not be the activator at all. The creature's
    # controller is asked, and CR 608.2d puts the question inside this
    # resolution — which is why the grant
    # is the *step behind* this one rather than a handler that arms its own
    # prompt: a prompt that suspends is answered after the handler that armed it
    # has returned.
    #
    # Through the same reader the grant resolves its own target with, over the
    # same ``targets`` description the lowering copies onto both steps: two
    # readings of one announcement is how a chooser and a grantee come apart.
    if chooser == "target_controller":
        from ._common import resolve_target_permanent
        from .pump import granted_target_legal

        chosen = resolve_target_permanent(
            game, context,
            predicate=granted_target_legal(game, instruction, context),
        )
        if chosen is None:
            game.log.append(f"{card_name}: no creature was chosen to choose a colour")
            return True, "resolved"
        seat = game.controller_index_of(chosen)
        # And **nothing standing is recorded**. ``chosen_color`` on a permanent
        # is the colour that permanent's own continuous ability keeps asking
        # about (Chromatic Armor's shield, Hall of Gemstone's mana swap); this
        # card has no such ability, and the source it would otherwise be written
        # on is the granting creature rather than the one being protected. The
        # scratchpad key below is the whole of the answer, and the step behind
        # it is its only reader.
        records_on = None
    if seat is None:
        return True, "resolved"
    if among is not None:
        if offered is None:
            offered = _offered_colors(game, among, seat, permanent)
        if not offered:
            # No permanent the phrase names has a colour, so there is no colour
            # to choose (CR 105.2c: colourless is the absence of one) and the
            # sentence behind this adds nothing. The slot is written **empty**
            # rather than left alone: "that color" must not read a colour some
            # earlier resolution of the same context chose.
            context.results[CHOSEN_COLOR_THIS_WAY] = None
            game.log.append(f"{card_name}: there is no color to choose")
            return True, "resolved"
        if len(offered) == 1:
            # One colour on offer is not a question (CR 608.2d asks for a
            # choice only where there is one to make).
            if records_on is not None:
                records_on.metadata["chosen_color"] = offered[0]
            context.results[CHOSEN_COLOR_THIS_WAY] = offered[0]
            game.log.append(
                f"{card_name}: {game.players[seat].name} chose {offered[0]}"
            )
            return True, "resolved"
    from ..ai_valuation import threatening_color

    default_color = None if offered is not None else threatening_color(game, seat)
    if offered is not None:
        # The first colour on offer, in WUBRG order: a deterministic member of
        # the set, where the unnarrowed default below is a colour the
        # *opponents* hold — which this sentence may not let anyone name.
        default_color = offered[0]
    if default_color is None:
        counts: dict[str, int] = {}
        for other in range(len(game.players)):
            if other == seat or game.players[other].lost:
                continue
            for perm in game.controlled_by(other):
                if perm.metadata.get("is_token"):
                    continue
                for color in game._effective_colors(perm):
                    counts[color] = counts.get(color, 0) + 1
        default_color = max(sorted(counts), key=lambda c: counts[c]) if counts else "W"
    if records_on is not None:
        records_on.metadata["chosen_color"] = default_color
    context.results[CHOSEN_COLOR_THIS_WAY] = default_color
    game.arm_color_choice(
        seat,
        card_name=card_name, permanent=records_on,
        result_key=CHOSEN_COLOR_THIS_WAY, context=context,
        default=default_color,
        colors=offered,
    )
    game.log.append(f"{card_name}: {game.players[seat].name} chooses a color")
    return True, "resolved"


def _offered_colors(game: Game, among: dict, seat: int, source) -> tuple[str, ...]:
    """The colours a narrowed "choose a color of <permanents>" offers *seat*.

    ``object_colors.colors_among_described`` — the layers' colours over the set
    the one subject matcher admits — so the handler, the payment planner and
    the client's colour picker (``mana_could_produce.ability_colors_on_offer``)
    are one reading of the phrase.
    """
    from ..object_colors import colors_among_described

    return colors_among_described(game, among, observer=seat, source=source)


@effect_handler("choose_card_type")
def choose_card_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"At the beginning of each player's upkeep, that player chooses artifact,
    creature, land, or non-Aura enchantment." (Teferi's Realm.)

    ``choose_color``'s sibling one characteristic over, and written the same
    way for the same reasons: the sentence produces a value and no effect, the
    value is recorded on the ability's own source (which is where the next
    sentence of the same ability looks for it), and a deterministic default is
    stamped **first** so a headless or AI seat is never blocked.

    The default is the option that would phase out the most of the *chooser's
    opponents'* nontoken permanents — a real answer rather than the first item,
    because the first item is a choice no player would make when a better one is
    on the list, and the card is one a seat faces every upkeep.

    The options come from the printed sentence rather than from the card-type
    catalog: the prompt is bounded by what the card offered, and a player who
    could answer "instant" would name a type no permanent has.
    """
    permanent = context.source_permanent
    card_name = getattr(context.card, "name", "an effect")
    options = [str(word) for word in (instruction.payload.get("options") or ())]
    if not options:
        game.log.append(f"{card_name}: no options were printed to choose from")
        return True, "resolved"
    if permanent is None:
        # "Choose artifact, creature, or land. Tap all untapped permanents of
        # the chosen type…" (Turnabout.) A **spell**'s choice, which has no
        # permanent to be recorded on and needs none: the sentence that reads it
        # back is the next step of this same resolution, and CR 608.2d puts both
        # of them in it. The word goes to the resolution scratchpad — the
        # channel ``choose_creature_type`` and ``choose_color`` already use for
        # the identical question one characteristic over.
        #
        # The default is stamped **before** the prompt is armed, exactly as the
        # permanent branch below stamps its own: a headless or AI seat is never
        # blocked, and the sweep behind this always has an answer to spend.
        if context.caster not in game.players:
            game.log.append(f"{card_name}: nobody to choose a type")
            return True, "resolved"
        seat = game.players.index(context.caster)
        default = _fewest_own_permanents_type(game, seat, options)
        context.results[CHOSEN_CARD_TYPE_THIS_WAY] = default
        game.arm_pending_choice(
            "card_type_choice", seat,
            card_name=card_name, options=list(options),
            default_card_type=default,
            result_key=CHOSEN_CARD_TYPE_THIS_WAY, _context=context,
        )
        game.log.append(
            f"{card_name}: {game.players[seat].name} chooses a type "
            f"({', '.join(options)})"
        )
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    if instruction.payload.get("chooser") == "event_subject_player":
        # The seat the fire site froze (CR 603.10) — a different player every
        # upkeep, and never the enchantment's controller except on their own
        # turn. No record means the words named nobody and nothing is asked,
        # which is the rule every other reading of this key follows.
        recorded = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card_name}: no recorded player to choose a type")
            return True, "resolved"
        seat = recorded
    if seat is None:
        return True, "resolved"
    default = _fewest_own_permanents_type(game, seat, options)
    permanent.metadata[CHOSEN_CARD_TYPE] = default
    game.arm_pending_choice(
        "card_type_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        options=list(options), default_card_type=default,
    )
    game.log.append(
        f"{card_name}: {game.players[seat].name} chooses a type "
        f"({', '.join(options)})"
    )
    return True, "resolved"


@effect_handler("choose_creature_type")
def choose_creature_type(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Destroy all creatures **of the creature type of your choice**."
    (Extinction.)

    ``choose_card_type``'s sibling one catalog over, with one difference that
    changes where the answer goes: this card is a **sorcery**, so there is no
    source permanent to record on and no permanent for a later turn to read.
    The word lives in the resolution scratchpad and is spent by the next step of
    the same sentence, which is what ``result_key`` names.

    The default is stamped **first**, so a headless or AI seat is never blocked
    and the sweep behind this always has an answer. It is a real one rather than
    the first catalog entry: the type that kills the most of the chooser's
    opponents' creatures and the fewest of their own, which is the choice a
    player would make. ``None`` when no creature is on the battlefield at all —
    and the sweep reads that as destroying nothing, never as destroying
    everything.
    """
    key = str(instruction.payload["result_key"])
    context.results[key] = None
    card_name = getattr(context.card, "name", "an effect")
    if context.caster not in game.players:
        game.log.append(f"{card_name}: nobody to choose a creature type")
        return True, "resolved"
    seat = game.players.index(context.caster)
    # "Choose a creature type **other than Wall**." (Unnatural Selection.) The
    # printed exclusion, applied to all three places a type can come from: the
    # default stamped here, the list the prompt offers and the answer the
    # resolver accepts (``arm_creature_type_choice`` carries it to the last
    # two). Absent for every other card, whose default and prompt are
    # byte-identical to what they were.
    excluded = tuple(
        str(word).strip().lower()
        for word in (instruction.payload.get("excluded") or ())
    )
    default = _best_creature_type_to_sweep(game, seat, excluded=excluded)
    context.results[key] = default
    game.arm_creature_type_choice(
        seat, card_name=card_name, result_key=key, context=context,
        default=default, excluded=excluded,
    )
    game.log.append(
        f"{card_name}: {game.players[seat].name} chooses a creature type"
        + (f" other than {', '.join(word.title() for word in excluded)}" if excluded else "")
    )
    return True, "resolved"


def _best_creature_type_to_sweep(
    game: Game, seat: int, excluded: tuple[str, ...] = (),
) -> str | None:
    """The creature type a sweep would most like to name, from *seat*'s side.

    The type maximising (opponents' creatures of it − own creatures of it), ties
    broken by the alphabetically first word, which keeps the answer
    deterministic — the property the AI-simulation regressions depend on.

    Only types actually on the battlefield are considered, and ``None`` comes
    back when there are none. Naming a type nothing has would be an answer that
    reads as a choice and destroys nothing; ``None`` says outright that no
    choice was made, which is what the sweep behind this checks.

    The subtypes are read through the CR 613 accessor, so a creature Artificial
    Evolution or an animated land has become a Zombie counts as one.

    *excluded* is a printed "other than <type>": a word in it is never the
    answer, so the default is one the resolver would accept. Only **creature**
    types are scored — an animated Forest's "forest" is a subtype of the
    permanent and no answer to "choose a creature type".
    """
    from ..grammar.vocabulary import CREATURE_TYPES
    from ..layer_bridge import computed_types

    scores: dict[str, int] = {}
    for owner, perm in game.permanents_with_controller():
        if not perm.is_creature:
            continue
        for subtype in computed_types(perm)[1]:
            word = str(subtype).lower()
            if word in excluded or word not in CREATURE_TYPES:
                continue
            scores[word] = scores.get(word, 0) + (-1 if owner == seat else 1)
    if not scores:
        return None
    return max(sorted(scores), key=lambda word: scores[word])


def _fewest_own_permanents_type(game: Game, seat: int, options: list[str]) -> str:
    """The offered option that costs *seat* least and their opponents most.

    Teferi's Realm phases out **every** nontoken permanent of the chosen type,
    the chooser's included, so the choice is a real one: the option maximising
    (opponents' permanents − own permanents). Ties keep the printed order, which
    keeps the answer deterministic — the property the AI-simulation regressions
    depend on.
    """
    from ..subject_filters import subject_matches
    from ._common import chosen_card_type_filter

    best, best_score = options[0], None
    for word in options:
        described = chosen_card_type_filter(word)
        if described is None:
            continue
        described = {**described, "nontoken": True}
        score = 0
        for other in range(len(game.players)):
            if game.players[other].lost:
                continue
            hit = sum(
                1 for perm in game.controlled_by(other)
                if subject_matches(game, perm, described, observer=other)
            )
            score += -hit if other == seat else hit
        if best_score is None or score > best_score:
            best, best_score = word, score
    return best


@effect_handler("if_then")
def if_then(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If <condition>, <then>" — including CR 603.4 intervening-if conditions,
    which the legacy compiler dropped, so conditional triggers always fired."""
    condition = instruction.payload.get("condition") or {}
    if evaluate_condition(game, context, condition):
        return _run(game, _steps(instruction, "then"), context)
    return _run(game, _steps(instruction, "else"), context)


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
    from ._common import _card_matches_filter

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
        from ._common import graveyard_card_matches

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
        from ._common import graveyard_card_matches

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
        return any(
            graveyard_card_matches(instruction.payload, card)
            for card in player.graveyard
        )
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
    # is the card SET_PLAYBOOK.md's Known gaps names: accepting over an empty
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
        from ._common import count_from_payload

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


def _offered_seats(
    game: Game, actor: str, context: OracleExecutionContext,
    start_seat: int | None = None,
) -> list[int]:
    """Which seats the offer is made to, in the order they answer it.

    "Each player may …" (Rebirth) is one decision per player, not one decision
    somebody makes for everybody — so the actor is a *set* of seats and the
    handler below arms one prompt for each. CR 101.4: the seats are asked in
    turn order starting with the active player, which is also the order the
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
        from ._common import bound_permanent

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
        from ._common import attached_host

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
        # counter has run (``_common.stack_target_controller_seat``).
        from ._common import stack_target_controller_seat

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
    controller sacrificed and discarded while ``_action_is_takeable`` above had
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
        from ._common import count_from_payload

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
    }
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
    (``_common.triggering_spell``), so the price and the counter behind it are
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


#: The last item :func:`repeat_offer_round` walks: the end of one round, where
#: whether there is another one is decided.
_END_OF_ROUND = object()


@effect_handler("repeat_offer_round")
def repeat_offer_round(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Starting with you, each player may put a permanent card from their hand
    onto the battlefield. **Repeat this process until no one puts a card onto
    the battlefield.**" (Eureka.)

    One round is the offer made to every seat in turn (CR 101.4), and the round
    happens again whenever anybody took it. What "anybody took it" reads is the
    record the offered act leaves — see ``engine/repeated_offers.py``, which is
    the one table this and the lowering that admitted the clause both ask.

    Both loops are ``run_resumable``: an interactive seat's pick suspends the
    resolution, and the seats behind it — and the rounds behind *that* — are the
    work still owed. The decision about the next round therefore cannot sit
    after the loop, where it would not run at all once a seat stopped to think;
    it is the loop's own last step, which is what ``_END_OF_ROUND`` is for.

    Termination is a property of the act, not a counter: every offer taken moves
    a card out of a hand, so the rounds are bounded by the cards there were.
    """
    steps = _steps(instruction, "action")
    actor = instruction.payload.get("actor", "each_player")
    start_seat = (
        game.players.index(context.caster)
        if instruction.payload.get("offer_order") == "you"
        else None
    )
    taken = context.results.setdefault(OFFER_TAKEN_RESULTS, [])

    def run_round() -> None:
        # Re-asked each round: a seat that has left the game is nobody
        # (CR 800.4a), and a round is not a snapshot of who was there first.
        seats = _offered_seats(game, actor, context, start_seat=start_seat)
        at_round_start = len(taken)

        def offer(item) -> None:
            if item is _END_OF_ROUND:
                if len(taken) > at_round_start:
                    run_round()
                return
            # The offered seat is "their hand" and "that player" inside the act,
            # exactly as ``_offer_to_seat`` rebinds it for a one-shot offer. The
            # replacement shares this context's ``results``, which is how every
            # seat of every round appends to the one record above.
            _run(game, steps, dataclasses.replace(context, target=game.players[item]))

        run_resumable(game, [*seats, _END_OF_ROUND], offer)

    run_round()
    return True, "resolved"


def _claimable_exile_pile(game: Game, context) -> list[tuple[int, object]]:
    """The pile "one of the exiled cards" names, as ``(owner_seat, card)`` pairs.

    Read off ``EXILED_THIS_WAY_OBJECTS``, whose element type is a property of the
    zone the exile emptied — see that key. Both shapes are named here rather
    than told apart by a type test that happens to work: a battlefield sweep
    records ``Permanent``s, whose owner is the one thing CR 400.7 makes
    unanswerable once the card is in exile, and an exile out of a graveyard
    records the cards, whose owner is the seat whose pile they came out of.

    The seat is resolved **now**, while the record still says who each object
    belonged to, and carried on the pile: several decks share one
    ``CardDefinition`` object, so a scan of the exile zones later would answer
    with whichever seat was asked first.
    """
    owners = context.results.get(SWEPT_OWNER_SEATS) or {}
    pile: list[tuple[int, object]] = []
    for entry in context.results.get(EXILED_THIS_WAY_OBJECTS) or ():
        card = getattr(entry, "card", None)
        if card is not None:
            # Off the record the sweep wrote, never off the permanent: by the
            # time this runs the object has left the battlefield, so
            # ``owner_index_of`` has nothing but a metadata key a hand-built
            # board never stamps — and it would answer None for exactly the
            # permanents the sweep routed correctly a moment earlier.
            seat = owners.get(entry.permanent_id)
            if seat is None:
                seat = game.owner_index_of(entry)
        else:
            card = entry
            seat = next(
                (
                    index for index, player in enumerate(game.players)
                    if any(held is card for held in player.exile)
                ),
                None,
            )
        if seat is None or card is None:
            continue
        pile.append((seat, card))
    return pile


@effect_handler("claim_exiled_cards_in_turn")
def claim_exiled_cards_in_turn(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile all nontoken permanents. **Starting with you, each player chooses
    one of the exiled cards and puts it onto the battlefield tapped under their
    control. Repeat this process until all cards exiled this way have been
    chosen.**" (Thieves' Auction.)

    One round is the pick offered to every seat in turn (CR 101.4), and the
    rounds go on while the pile has cards in it. ``repeat_offer_round``'s shape
    one decision over, with two differences that are the whole of why it is its
    own handler: the pick is **mandatory**, so there is no record of takers to
    end on, and the bound is the pile rather than the round — four cards among
    three players is two passes, and the second stops after the first seat.

    The loop is ``run_resumable`` for that handler's stated reason: an
    interactive seat's pick suspends the resolution, and the seats behind it —
    and the rounds behind *that* — are the work still owed, so the question of
    whether there is another round has to be the loop's own last step rather
    than a line after it (``_END_OF_ROUND``).

    Termination is a property of the act: every answered pick takes a card off
    the pile, so the rounds are bounded by the cards there were. A round that
    took **nothing** ends the loop outright rather than being repeated — a
    prompt whose answer was refused would otherwise hand the same pile round
    for ever, which is a hang rather than a wrong number.
    """
    pile = context.results.get(CLAIMABLE_EXILED_CARDS)
    if pile is None:
        pile = _claimable_exile_pile(game, context)
        context.results[CLAIMABLE_EXILED_CARDS] = pile
    tapped = bool(instruction.payload.get("tapped"))
    repeat = bool(instruction.payload.get("until_pile_empty"))
    # "Starting with you" — the seat that put the spell on the stack. Without
    # the words CR 101.4's default stands, which is the active player.
    start_seat = (
        game.players.index(context.caster)
        if instruction.payload.get("claim_order") == "you"
        and context.caster in game.players
        else None
    )
    card_name = getattr(context.card, "name", "an effect")

    def run_round() -> None:
        # Re-asked each round: a seat that has left the game is nobody
        # (CR 800.4a), and a round is not a snapshot of who was there first.
        seats = _offered_seats(game, "each_player", context, start_seat=start_seat)
        at_round_start = len(pile)

        def claim(item) -> None:
            if item is _END_OF_ROUND:
                if repeat and pile and len(pile) < at_round_start:
                    run_round()
                return
            if not pile:
                # The pile ran out part-way through the round. The seats behind
                # this one are asked nothing at all, which is what "until all
                # cards have been chosen" means when the cards run out first.
                return
            game.arm_pending_choice(
                "exiled_pile_claim", item,
                card_name=card_name,
                options=[card.name for _, card in pile],
                tapped=tapped,
                _context=context,
            )

        run_resumable(game, [*seats, _END_OF_ROUND], claim)

    run_round()
    return True, "resolved"


#: The last item :func:`repeat_optional_process` walks: the end of one round,
#: where the seat is asked whether there is another. A sentinel and not a step,
#: because the question is not an effect — and it has to be *inside* the loop,
#: for ``engine/resumption.py``'s standing rule: a round that stopped to ask
#: something would never reach a line written after the loop.
_ASK_TO_REPEAT = object()


@effect_handler("repeat_optional_process")
def repeat_optional_process(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Sacrifice a nontoken permanent. If you do, target opponent loses 2 life
    unless that player sacrifices a permanent of their choice or discards a
    card. **You may repeat this process any number of times.**" (Forbidden
    Ritual.)

    One round is every step of the printed process, and the round happens again
    whenever this effect's controller says so. That is the whole difference
    from ``repeat_offer_round`` beside it, which reads a *record* to decide: an
    unbounded "any number of times" has no record and no bound, so the decision
    is a prompt and the loop ends on the answer.

    The next round is run by the prompt's own resolver, holding this same
    instruction — the shape ``coin_flip_stakes_loop`` already uses for Game of
    Chaos's "flip again?", and for that shape's reason: what runs next is a
    whole instruction rather than a branch, so nothing here has to know how many
    rounds there will be.

    Both loops are ``run_resumable``. A step of the round suspends whenever an
    interactive seat is asked something (the sacrifice prompt is the first
    thing this card does), and the steps behind it — and the question about the
    next round — are the work still owed. The loop is the last thing this
    handler does, which is the other half of that rule.
    """
    steps = _steps(instruction, "steps")
    seat = game.players.index(context.caster)

    def step(item) -> None:
        if item is _ASK_TO_REPEAT:
            game.arm_pending_choice(
                "repeat_process", seat,
                card_name=getattr(context.card, "name", "Effect"),
                _again=instruction,
                _context=context,
            )
            return
        game._execute_oracle_instruction(item, context)

    run_resumable(game, [*steps, _ASK_TO_REPEAT], step)
    return True, "resolved"


#: The loop a round is running under, for the step inside it that asks for
#: another. In the resolution's own scratchpad because that is the one thing
#: every step of a resolution shares, and because the asking step is not
#: reached by the loop at all: it runs from an ``optional_pay`` prompt's
#: resolver, after the round that armed it has finished.
REPEAT_PROCESS = "repeat_process_this_way"


@effect_handler("request_process_repeat")
def request_process_repeat(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"…unless you pay {3} **and repeat this process**." (Crooked Scales.)

    What the toll bought, as the offer's "if you do" branch — and the thing
    that *runs* the next round, rather than a flag some loop reads afterwards.

    That is the shape ``repeat_optional_process`` and ``coin_flip_stakes_loop``
    already have, and here it is forced rather than chosen: an ``optional_pay``
    does not suspend the resolution that armed it, so by the time the seat has
    answered, the round — and every loop around it — has returned. A record
    read between rounds would be read before the payment existed, and Crooked
    Scales would flip exactly once however much its controller paid.

    So the round hands its own instruction down the scratchpad
    (:data:`REPEAT_PROCESS`) and this step runs it again. The dispatch is
    ``_execute_oracle_instruction``'s, not a direct call, so the next round
    goes through the same door as the first, and it is the last thing this
    handler does — ``engine/resumption.py``'s rule, since the round it starts
    can suspend on the very next toll.
    """
    again = context.results.get(REPEAT_PROCESS)
    if again is None:
        # Nothing to repeat. Only reachable if the marker outlived the wrapper
        # its lowering puts round the line, which no compiled program does —
        # said rather than assumed, because a silent no-op here is a card that
        # charges its controller {3} for nothing.
        game.log.append(
            f"{getattr(context.card, 'name', 'Effect')}: no process to repeat"
        )
        return True, "resolved"
    game.log.append(
        f"{getattr(context.card, 'name', 'Effect')}: repeating the process"
    )
    game._execute_oracle_instruction(again, context)
    return True, "resolved"


@effect_handler("repeat_process_on_request")
def repeat_process_on_request(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Flip a coin. If you win the flip, destroy target creature an opponent
    controls. If you lose the flip, destroy target creature you control
    **unless you pay {3} and repeat this process**." (Crooked Scales.)

    The fourth repeat in this file and the fourth mechanism.
    ``repeat_offer_round`` ends on a round nobody took,
    ``repeat_optional_process`` on a seat's answer to a question printed as its
    own sentence, ``repeat_process_while`` on a condition asked of what the
    round did — and this one on a **price inside the round**, charged on one
    arm of a coin flip that may not even have been taken.

    So the loop is round the *line*: what repeats is the flip and both of its
    arms, and the sentence that charges for another round is two branches down
    inside the third of them. All this handler does is run the round and say,
    in the scratchpad, which instruction another round would be — the asking is
    :func:`request_process_repeat`'s, because the answer arrives after this has
    returned.

    Through ``_run`` like every other wrapper here, so a step naming its own
    role of a shared announcement is scoped to it (``_role_scoped``) and a
    round that stops to ask something takes the rest of itself with it.

    Termination is the card's. Every round costs its controller {3} out of a
    finite pool and a round nobody pays for asks for nothing, so declining —
    or being unable to pay — ends it, as does winning the flip.
    """
    steps = _steps(instruction, "steps")
    if not steps:
        return True, "resolved"
    context.results[REPEAT_PROCESS] = instruction
    return _run(game, steps, context)


@effect_handler("repeat_process_while")
def repeat_process_while(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Target player mills two cards. **If two cards that share a color were
    milled this way, repeat this process.**" (Grindstone.)

    The third repeat in this file and the third mechanism: ``repeat_offer_round``
    ends on a round nobody took, ``repeat_optional_process`` on a seat's
    answer, and this one on a **condition asked of what the round just did**.

    ``resets`` is the whole reason the loop terminates on a real board. The
    condition reads records the round writes, and those records accumulate
    across an effect by design ("what did this whole resolution mill?") — so
    each round clears exactly the keys its own steps write, which is what makes
    "milled **this way**" mean this round's cards. Without it Grindstone would
    be asked about every card it had milled so far, find a shared colour among
    them for ever, and mill until the library was empty on any two coloured
    cards at all.

    **No ``run_resumable``**, unlike the two loops above, and that is a
    property of this shape rather than an omission: the condition is asked
    *between* rounds, so a round that suspended part-way would leave the
    question about a round that had not happened. The lowering keeps that
    honest by refusing a condition whose records the round does not write —
    a round with nothing to ask about cannot be a round this repeats.

    Termination is the card's, not a cap here: the round has to write the
    record the condition reads, and a round that writes an empty one answers
    False. Grindstone's mill shrinks a finite library every time round, and an
    empty library mills nothing, which is exactly that.
    """
    steps = _steps(instruction, "steps")
    condition = dict(instruction.payload.get("condition") or {})
    resets = tuple(instruction.payload.get("resets") or ())
    if not steps or not condition:
        return True, "resolved"
    while True:
        for key in resets:
            context.results.pop(key, None)
        for item in steps:
            game._execute_oracle_instruction(item, context)
        if not evaluate_condition(game, context, condition):
            return True, "resolved"
        game.log.append(f"{getattr(context.card, 'name', 'Effect')}: repeating")


#: The loop a round is running under, for :func:`end_process_round` — the step
#: that is the end of that round and may run long after the loop has returned.
#: ``REPEAT_PROCESS``'s arrangement and for its reason.
PROCESS_UNTIL = "repeat_process_until_this_way"

#: Whether :func:`repeat_process_until` is on the Python stack *right now*, and
#: what the round that just ended inside it asked for. A round that ends
#: inline is repeated by the loop that ran it; one that ends on a seat's answer
#: finds no loop there and starts the next round itself.
_PROCESS_LOOP_LIVE = "repeat_process_until_live"
_PROCESS_ROUND_AGAIN = "repeat_process_until_again"


@effect_handler("repeat_process_until")
def repeat_process_until(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Exile the top card of your library. You may put that card into your
    hand unless it has the same name as another card exiled this way. **Repeat
    this process until you put a card into your hand or you exile two cards
    with the same name, whichever comes first.**" (Tainted Pact.)

    One more repeat in this file and one more mechanism: a loop that ends on
    conditions asked **when the round is over** — and whose round may end in
    an offer, so "over" can be an answer away. ``repeat_process_while`` asks
    its condition on the line after the round and says why it cannot be
    resumable; this one's question is a *step* of the round instead
    (:func:`end_process_round`, which the lowering puts on every way out of
    the round's last sentence), so it is asked wherever the round really ends:
    here, inline, or in the resolver of the prompt the round stopped on.

    That is why there are two ways to start the next round. A round that ended
    inline says so in the scratchpad and this loop runs it — a ``while``, so a
    process of sixty prompt-free rounds is sixty turns of a loop and not sixty
    nested resolutions. A round that ended on an answer finds this function
    long returned, and :func:`end_process_round` dispatches the instruction
    again, which is ``request_process_repeat``'s shape.

    ``resets`` are the records the round's own steps write. Before each round
    their lists are filed under ``PROCESS_ROUNDS_SO_FAR`` and the keys cleared:
    "that card" is this round's card, and "another card exiled this way" is
    every round's.

    The round is the last thing each turn of the loop does, which is
    ``engine/resumption.py``'s rule — after it there is only the read of what
    the round's own end step recorded.
    """
    steps = _steps(instruction, "steps")
    if not steps:
        return True, "resolved"
    results = context.results
    results[PROCESS_UNTIL] = instruction
    while True:
        earlier = results.setdefault(PROCESS_ROUNDS_SO_FAR, {})
        for key in instruction.payload.get("resets") or ():
            written = results.pop(key, None)
            if isinstance(written, (list, tuple)) and written:
                earlier.setdefault(key, []).extend(written)
        results[_PROCESS_ROUND_AGAIN] = False
        results[_PROCESS_LOOP_LIVE] = True
        try:
            _run(game, steps, context)
        finally:
            results[_PROCESS_LOOP_LIVE] = False
        if not results.pop(_PROCESS_ROUND_AGAIN, False):
            return True, "resolved"


@effect_handler("end_process_round")
def end_process_round(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """The end of one round of :func:`repeat_process_until`, and the only
    place its stopping clauses are asked.

    Three answers. **A stopping clause holds**: the process is over. **The
    round did nothing** — not one record its steps write was written: a
    process that can no longer be performed is not repeated (CR 101.3: any
    part of an instruction that is impossible to perform is ignored). That is
    Tainted Pact on an empty library, where exiling the top card exiles
    nothing; nobody loses, because nothing was drawn. It is also what keeps a
    loop whose clauses can no longer come true from being a hang. **Otherwise**
    the process happens again.

    The stopping clauses come first, so a round that both ended the process
    and emptied the library reports the reason the card printed.
    """
    loop = context.results.get(PROCESS_UNTIL)
    name = getattr(context.card, "name", "Effect")
    if loop is None:
        # Only reachable if the step outlived the wrapper its lowering puts
        # round it, which no compiled program does — said rather than assumed.
        game.log.append(f"{name}: no process to repeat")
        return True, "resolved"
    if any(
        evaluate_condition(game, context, dict(condition))
        for condition in loop.payload.get("until") or ()
    ):
        game.log.append(f"{name}: the process ends")
        return True, "resolved"
    if not any(context.results.get(key) for key in loop.payload.get("resets") or ()):
        game.log.append(f"{name}: the process cannot continue")
        return True, "resolved"
    game.log.append(f"{name}: repeating the process")
    if context.results.get(_PROCESS_LOOP_LIVE):
        context.results[_PROCESS_ROUND_AGAIN] = True
        return True, "resolved"
    game._execute_oracle_instruction(loop, context)
    return True, "resolved"


@effect_handler("choose_one")
def choose_one(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A ``choose_one`` reached at *resolution*: alternatives that are a step of
    an effect already running ("that creature gains flying or first strike").

    Not a modal **ability**. A modal triggered ability chooses its mode as it is
    put on the stack (CR 700.2b), which
    ``mixins/stack/resolution._choose_trigger_mode`` does, and by the time such
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
