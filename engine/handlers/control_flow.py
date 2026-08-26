"""Control-flow instructions: sequencing, conditions, optional costs, iteration.

These are what let an effect be *composed* rather than fused into a bespoke
instruction kind. The legacy compiler delivered exactly one instruction per
spell, so every "do X and also Y" card needed its own kind —
``deal_damage_and_gain_life``, ``deal_damage_and_self_damage``,
``grant_islandwalk_and_linked_destroy`` and 25 more, which is combinatorial in
the number of base effects and was the single largest driver of kind growth.

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

from ..oracle_types import PER_OBJECT_SEAT_RECORDS, OracleInstruction
from ..turn_state import started_the_turn
from ..resumption import run_resumable
from ._common import flip_coin, permanent_matches_filter
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
        supported, _ = game._execute_oracle_instruction(step, context)
        outcome["resolved"] = outcome["resolved"] or supported

    run_resumable(game, steps, run_step)
    return True, "resolved" if outcome["resolved"] else "no effect"


@effect_handler("sequence")
def sequence(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Perform each step in order (CR 608.2: a spell's instructions resolve in
    the order written)."""
    return _run(game, _steps(instruction, "steps"), context)



def _compare_count(count: int, op: str, wanted: int | None) -> bool:
    """A counted condition's printed comparison, in one place.

    Every condition that counts objects prints the same three operators and the
    same unwritten fourth: no number at all ("if you control an Island") means
    "at least one". Two copies of this answered slightly different questions the
    first time a second counting clause was added, which is the second-copy bug
    this engine keeps finding — an unknown operator is False in both, but the
    absent-number default is the half that would have silently disagreed.
    """
    if wanted is None:
        return count > 0
    if op == "eq":
        return count == wanted
    if op == "le":
        return count <= wanted
    if op == "ge":
        return count >= wanted
    return False


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

    if kind == "blockers_of_bound_creature":
        # "if at least one other Wall creature is blocking that creature"
        # (Wall of Caltrops). CR 509.1a's relation, asked of the creature the
        # firing block event named: the fire site stamped its id into the
        # trigger context, because by resolution the ability's own target
        # indices name the *blocker* and nothing else could say what it blocked.
        blocked_ids = (context.trigger_context or {}).get("blocked_permanent_ids") or []
        blocked = [
            perm for perm in (game.permanent_by_id(i) for i in blocked_ids)
            if perm is not None
        ]
        if not blocked:
            # Nothing named, or what was named has left (CR 400.7). Either way
            # there is no creature for the clause to count the blockers of, and
            # False is the honest answer — never a scan that would count the
            # blockers of some other attacker.
            return False
        filters = payload.get("filter") or {}
        # "another Wall" — the asking permanent never satisfies its own
        # condition. Relative, so outside the matcher's vocabulary; asked here,
        # the same split the `controls` clause below makes.
        source = context.source_permanent if filters.get("exclude_self") else None
        wanted = payload.get("count", 0)
        op = payload.get("op", "ge")

        def _holds(attacker) -> bool:
            count = sum(
                1
                for blocker in game.creatures_blocking(attacker)
                if blocker is not source
                and permanent_matches_filter(blocker, filters)
            )
            return _compare_count(count, op, wanted)

        # Every creature the event named must satisfy it. A narrowed block
        # trigger fires once per blocked creature (CR 509.3d), so this is one
        # attacker in practice; an unnarrowed one names several, and picking
        # arbitrarily among them is the reading no printed sentence supports.
        return all(_holds(attacker) for attacker in blocked)

    if kind == "controls":
        who = payload.get("who", "you")
        players = [context.caster] if who == "you" else list(game.players)
        if who in ("each_opponent", "target_opponent", "opponent"):
            players = [p for p in game.players if p is not context.caster]
        if who == "event_subject_player":
            # The seat the firing event named, frozen by the fire site — "if
            # **that player** controls a Plains" under "at the beginning of each
            # player's upkeep" (Spiritual Sanctuary). Without this the clause
            # fell through to the every-player list above and asked whether
            # *anybody* controlled one, which is a different card.
            seat = (context.trigger_context or {}).get("event_subject_player")
            if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
                return False
            players = [game.players[seat]]
        filters = payload.get("filter") or {}
        # "another creature…" (Turret Ogre): the asking ability's own source
        # never satisfies its own condition. Outside the matcher's vocabulary
        # — it answers about a permanent alone — so it is asked here, the same
        # split the counter handler makes.
        source = context.source_permanent if filters.get("exclude_self") else None
        matched = [
            permanent
            for player in players
            for permanent in game.controlled_by(player)
            if permanent is not source and permanent_matches_filter(permanent, filters)
        ]
        if payload.get("shared_name"):
            # "…with the same name as one another" (Chrome Replicator). The
            # threshold bounds the largest group sharing a name, not the
            # matching set — three permanents with three different names satisfy
            # nothing. The name is read off the *effective* card, so a Clone
            # counts under the name it copied (CR 707.2), which is also the name
            # printed on the board a player is looking at.
            by_name: dict = {}
            for permanent in matched:
                name = permanent.effective_card.name
                by_name[name] = by_name.get(name, 0) + 1
            count = max(by_name.values(), default=0)
        else:
            count = len(matched)
        wanted = payload.get("count")
        op = payload.get("op", "eq")
        # "if an opponent controls more creatures than you" (Garruk,
        # Unleashed's −2): the bound is the asker's own matching count, and
        # "an opponent" means any single opponent beating it.
        if op == "more_than_you":
            filters = payload.get("filter") or {}
            own = sum(
                1
                for permanent in game.controlled_by(context.caster)
                if permanent_matches_filter(permanent, filters)
            )
            return any(
                sum(
                    1
                    for permanent in game.controlled_by(player)
                    if permanent_matches_filter(permanent, filters)
                ) > own
                for player in game.players
                if player is not context.caster and not player.lost
            )
        return _compare_count(count, op, wanted)

    if kind == "revealed_card_is":
        # "If it's a creature or land card" (Track Down). Reads the card an
        # earlier step of this same resolution revealed, never the library:
        # the branch below this one draws, and a re-read would then be asking
        # about whichever card the draw uncovered.
        revealed = context.results.get("revealed_card")
        if revealed is None:
            return False
        wanted = [str(t) for t in (payload.get("card_types") or ())]
        if not wanted:
            return False
        line = (revealed.type_line or "").lower()
        matches = [t for t in wanted if t in line]
        # "creature **or** land card" is a union; "artifact creature" is one
        # object that is both. The same distinction `type_match` draws
        # everywhere else, carried here so the two cannot disagree.
        if payload.get("type_match") == "all":
            return len(matches) == len(wanted)
        return bool(matches)

    # "Exile it. **If you do**, create a … token." (Archfiend's Vessel.) Whether
    # the step before this one actually took place, read from the record that
    # step wrote. An absent record is False, which is the honest reading: the
    # handler writes it only on the path where the action happened.
    # "if it entered from your graveyard or you cast it from your graveyard"
    # (Archfiend's Vessel). Two records, because they are two events: the entry
    # seam stamps where the permanent came from, and the cast stamps the zone
    # the spell was cast from. A permanent that entered any other way answers
    # False, which is the reading that leaves the Vessel a plain 1/1.
    # "if two or more of those creatures are attacking you and/or planeswalkers
    # you control" (Mangara). The number the *declaration* had, frozen by the
    # fire site: recounting here would ask about a combat that may have changed.
    if kind == "attackers_aimed_at_you":
        aimed = int((context.trigger_context or {}).get("attackers_aimed", 0))
        return aimed >= int(payload.get("count", 0))

    if kind == "entered_from":
        source = context.source_permanent
        if source is None:
            return False
        wanted = payload.get("zone")
        if source.metadata.get("entered_from_zone") == wanted:
            return True
        return bool(payload.get("or_cast")) and (
            source.metadata.get("cast_from_zone") == wanted
        )

    if kind == "it_happened":
        happened = bool(context.results.get(payload.get("key")))
        # "If you **can't**" (Cocoon) is the same record read the other way. An
        # absent record is "it did not happen", which is also the honest answer
        # when the recording step itself could not run — an Aura that left
        # before its upkeep trigger resolved removed nothing (CR 608.2b), so
        # the can't-branch is exactly what should run.
        return not happened if payload.get("negated") else happened

    if kind == "coin_flip":
        # CR 705.2. The flip recorded its result; asking again would flip a
        # second coin, so a card printing both branches could win *and* lose.
        # An absent record is False for either branch rather than a guess — the
        # grammar refuses to lower a flip condition with no flip in front of it,
        # so this is unreachable from a compiled card.
        if "coin_flip" not in context.results:
            return False
        return bool(context.results["coin_flip"]) is bool(payload.get("won", True))

    if kind == "subject_characteristic_is":
        # "If this creature's power is 1 or more" (Lesser Werewolf), "If target
        # creature has toughness 5 or greater" (Blood Lust). CR 613's computed
        # characteristic, read through the layer accessors rather than off the
        # printed card: Lesser Werewolf's gate exists because the ability
        # shrinks its own source, and Blood Lust must see a creature another
        # spell already pumped. Nothing to ask about answers False — a source
        # that has left (CR 608.2b) and a target that is no longer legal both.
        from ._common import resolve_target_permanent

        if payload.get("subject") == "target":
            # Through the same resolver the arms use, so the branch and the
            # effect cannot disagree about which creature the sentence meant.
            subject = resolve_target_permanent(
                game, context, fallback_on_invalid_choice=False
            )
        else:
            subject = context.source_permanent
        if subject is None:
            return False
        value = (
            subject.effective_toughness
            if payload.get("characteristic") == "toughness"
            else subject.effective_power
        )
        wanted = int(payload.get("count", 0))
        op = payload.get("op", "eq")
        if op == "eq":
            return value == wanted
        if op == "le":
            return value <= wanted
        if op == "ge":
            return value >= wanted
        return False

    if kind == "is_state":
        source = context.source_permanent
        if source is None:
            return False
        state = payload.get("state")
        value = bool(getattr(source, state, False)) if state else False
        return (not value) if payload.get("negated") else value

    if kind == "started_turn_state":
        # "If this creature started the turn untapped" (Rasputin Dreamweaver).
        # The board cannot answer this at an upkeep — the untap step has already
        # run — so the untap step records it before untapping anything
        # (`phases/untap_step.py`), and this reads that record. A permanent with
        # no record for the current turn did not start it: it entered part-way
        # through, which is False either way round and never a guess.
        source = context.source_permanent
        if source is None:
            return False
        value = started_the_turn(source, payload.get("state") or "", game.turn)
        if value is None:
            # It was not on the battlefield when the turn began, so it started
            # the turn neither way and both spellings of the clause are false.
            return False
        return (not value) if payload.get("negated") else value

    if kind == "exiled_card_was":
        # "If it was a creature card" (Scavenging Ooze). The card is in exile by
        # now, and CR 400.7 makes that a new object, so the only honest source
        # is the record the exiling step wrote (CR 608.2h). No record means
        # nothing was exiled — False, not a guess at a pile this effect did not
        # fill.
        cards = context.results.get("exiled_cards") or []
        # The printed type *line*, not the primary type: an Ornithopter is an
        # artifact creature card and CR 205.2 says it is a creature card too.
        wanted = tuple(payload.get("card_types") or ())
        return bool(cards) and all(
            any(name in card.type_line.lower() for name in wanted) for card in cards
        )

    if kind == "target_has_keyword":
        # "If it doesn't have rampage" (Rapid Fire). Asked of the same target
        # the grant beside it resolves against, and through the same resolver,
        # so the branch and the effect cannot disagree about which creature the
        # pronoun meant. Layer 6 is what answers (CR 613.1f): a creature *given*
        # rampage has it, exactly as a printed one does.
        from ._common import resolve_target_permanent

        target = resolve_target_permanent(
            game, context, fallback_on_invalid_choice=False
        )
        if target is None:
            # No object to ask about — False either way, rather than letting the
            # negated reading answer yes about a creature that is not there.
            return False
        wanted = tuple(payload.get("keywords") or ())
        has = bool(wanted) and all(target.has_keyword(word) for word in wanted)
        return (not has) if payload.get("negated") else has

    if kind == "discarded_card_was":
        # "If the discarded card was a land card" (Land's Edge). The card is in
        # a graveyard by the time this is asked and CR 400.7 makes that a new
        # object, so the only honest source is the record the *cost payment*
        # wrote (CR 608.2h) — the same last-known-information channel the
        # sacrifice cost already rides. No record means the ability discarded
        # nothing, which is False rather than a guess.
        cards = context.choices.get("discarded_for_cost") or []
        # The printed type *line*, exactly as the exile twin above reads it: an
        # artifact land is a land card (CR 205.2), and `primary_type` would say
        # otherwise.
        wanted = tuple(payload.get("card_types") or ())
        return bool(cards) and all(
            any(name in card.type_line.lower() for name in wanted) for card in cards
        )

    if kind == "died_this_turn":
        return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0

    if kind == "had_plus1_counter":
        # "if it had a +1/+1 counter on it" (Basri's Lieutenant). The creature
        # is already in the graveyard by the time this resolves, so the only
        # legal source is the last-known information the fire site recorded
        # (CR 603.10). No record means nothing observed the death — False,
        # rather than a guess at a board that no longer holds the answer.
        return bool((context.trigger_context or {}).get("had_plus1_counter"))

    if kind == "returned_to_hand_this_turn":
        # "a permanent was put into your hand from the battlefield this turn"
        # (Barrin). "Your" is the ability's controller; the bounce paths feed
        # the per-seat counter.
        seat = game.players.index(context.caster)
        return int(game.permanents_to_hand_this_turn.get(seat, 0)) > 0

    if kind == "dealt_damage_this_turn":
        # "if this creature dealt damage to an opponent this turn" (Whirling
        # Dervish). Answered from the record the damage seam keeps on the
        # source permanent, because nothing on the board can be read for it
        # — the damaged player's life total says only what the whole turn did
        # to them. An absent record means this permanent damaged nobody, which
        # is the reading that leaves the Dervish uncountered.
        source = context.source_permanent
        if source is None:
            return False
        seats = source.metadata.get("dealt_damage_to_seats_this_turn") or []
        who = payload.get("who", "a player")
        if who == "a player":
            return bool(seats)
        controller_seat = game.players.index(context.caster)
        if who == "you":
            return controller_seat in seats
        return any(seat != controller_seat for seat in seats)

    if kind == "life_gained_this_turn":
        # Per player, because the counter is: "you" is the ability's
        # controller, which is context.caster for a triggered ability too.
        who = payload.get("who", "you")
        players = (
            [context.caster] if who == "you"
            else [p for p in game.players if p is not context.caster]
        )
        wanted = int(payload.get("amount", 0))
        return any(
            int(getattr(p, "life_gained_this_turn", 0) or 0) >= wanted
            for p in players
        )

    return False


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
    won = flip_coin()
    context.results["coin_flip"] = won
    game.log.append(
        f"{context.card.name}: {'won' if won else 'lost'} the coin flip"
    )
    return True, "resolved"


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
    """
    permanent = context.source_permanent
    if permanent is None:
        game.log.append(f"{context.card.name}: no permanent to choose a number for")
        return True, "resolved"
    low = int(instruction.payload.get("minimum", 0))
    high = int(instruction.payload.get("maximum", 0))
    seat = game.controller_index_of(permanent)
    if seat is None:
        return True, "resolved"
    game.arm_pending_choice(
        "number_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        minimum=low, maximum=high,
        default_number=int(permanent.metadata.get("chosen_number", low)),
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


def _action_is_takeable(game: Game, player, instruction: OracleInstruction, source) -> bool:
    """Whether *player* could actually perform this instruction right now.

    Two kinds are asked, because two kinds are the ones an optional action gives
    something up for; everything else answers True, which is what the engine did
    for all of them before this existed. A kind added here has to be one whose
    "nothing to give" case is real and checkable — not a guess, because a
    wrongly-False answer withdraws an offer the card makes.
    """
    from ._common import _card_matches_filter

    if instruction.kind == "sacrifice_matching_permanent":
        exclude = source if instruction.payload.get("exclude_self") else None
        # The printed count, not merely "at least one": "unless you sacrifice
        # **two** Swamps" (Mold Demon) is an offer a player with one Swamp
        # cannot take, and accepting it would run the cost half-paid and skip
        # the penalty the card prints for not paying it.
        return len(game._sacrifice_candidate_indices(
            player, dict(instruction.payload.get("filter") or {}), exclude
        )) >= int(instruction.payload.get("count", 1))
    if instruction.kind == "discard_controller_cards":
        described = dict(instruction.payload.get("filter") or {})
        return any(_card_matches_filter(card, described) for card in player.hand)
    # "You may remove a vitality counter from this Aura. **If you do**, you gain
    # 1 life." (Living Artifact.) With no counter there is nothing to remove, so
    # the offer is not made and the if-you-do branch never runs. The handler
    # underneath already treats removing from zero as a no-op — which is right
    # for a mandatory removal and, on its own, would have let this card gain
    # life off an empty Aura for as long as it stayed on the battlefield.
    if instruction.kind == "remove_counter_from_self":
        if source is None:
            return False
        counter = str(instruction.payload.get("counter", "doom"))
        return int(source.metadata.get(f"{counter}_counters", 0)) > 0
    # "Each player **may** ante the top card of their library. If a player does,
    # that player's life total becomes 20." (Rebirth.) An empty library has no
    # top card, so there is no ante to offer — and taking the offer anyway would
    # run the if-you-do branch off an ante that never happened, handing a player
    # 20 life for nothing. The offered seat is the anting seat: the offer names
    # one player and the ante comes off that player's own library (CR 407.4).
    if instruction.kind == "ante_top_card":
        return bool(player.library)
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
    source = context.source_permanent
    narrowed = []
    for step in steps:
        if step.kind == "choose_one":
            modes = tuple(
                mode for mode in (step.payload.get("modes") or ())
                if _action_is_takeable(game, player, mode["instruction"], source)
            )
            if not modes:
                return (), False
            narrowed.append(
                OracleInstruction(step.kind, step.value, {**step.payload, "modes": modes})
            )
            continue
        if not _action_is_takeable(game, player, step, source):
            return (), False
        narrowed.append(step)
    return tuple(narrowed), True


def _resolved_cost(printed, context: OracleExecutionContext) -> dict:
    """An offered cost with its variable amount read at resolution.

    "You may pay {X}, where X is the number of +1/+1 counters on it."
    (Primordial Ooze.) The where-clause has already become ``context.x_value``
    by the time any handler runs, so the cost is a symbol dict like every other
    — one of whose amounts is the string "x" until here. Resolved in the
    handler rather than at lowering because CR 608.2 takes the count when the
    ability *resolves*: a counter added between the trigger and its resolution
    changes the number.
    """
    resolved = {}
    for symbol, amount in dict(printed or {}).items():
        if amount == "x":
            amount = max(0, int(context.x_value or 0))
        resolved[symbol] = int(amount)
    return {symbol: amount for symbol, amount in resolved.items() if amount}


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
    for player_index in seats:
        _offer_to_seat(game, instruction, context, player_index, rebind=actor in _EACH_ACTORS)
    return True, "resolved"


#: The actors that name a *set* of seats. Only these rebind ``context.target``
#: below: a single-seat offer's target is whatever the spell or ability already
#: chose, and overwriting it with the offered player would point every "target"
#: in the accept branch at the wrong object (Niambi's bounce, Tolarian Kraken's
#: reflexive tap).
_EACH_ACTORS = frozenset({"each_player", "each_opponent"})


def _offered_seats(game: Game, actor: str, context: OracleExecutionContext) -> list[int]:
    """Which seats the offer is made to, in the order they answer it.

    "Each player may …" (Rebirth) is one decision per player, not one decision
    somebody makes for everybody — so the actor is a *set* of seats and the
    handler below arms one prompt for each. CR 101.4: the seats are asked in
    turn order starting with the active player, which is also the order the
    queue drains them in.

    A player who has already left the game is nobody (CR 800.4a).
    """
    if actor == "each_player":
        count = len(game.players)
        active = game.active_player_index or 0
        return sorted(
            (i for i, p in enumerate(game.players) if not p.lost),
            key=lambda i: ((i - active) % count, i),
        )
    if actor == "each_opponent":
        return [
            i for i in game.opponents_of(game.players.index(context.caster))
            if not game.players[i].lost
        ]
    return [game.players.index(context.caster if actor == "you" else context.target)]


def _offer_to_seat(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext,
    player_index: int, rebind: bool = False,
) -> None:
    """Arm one seat's copy of the offer.

    With *rebind*, ``context.target`` becomes the offered seat — which is what
    makes "that player" inside the offer and inside its if-you-do branch mean
    the player who took it. Only an offer made to a *set* of seats rebinds:
    everywhere else the target is the one the spell or ability already chose,
    and overwriting it would aim the accept branch at the wrong object.
    """
    player = game.players[player_index]
    if rebind:
        context = dataclasses.replace(context, target=player)
    # The whole printed cost, symbol by symbol — "you may pay {1}{B}" (Liliana's
    # Devotee) is a dict, not the number 2, because a payment that counted to a
    # number could only ever collect generic mana.
    cost = _resolved_cost(instruction.payload.get("cost"), context)
    on_accept = _steps(instruction, "action") + _steps(instruction, "then")
    on_decline = _steps(instruction, "otherwise")
    # CR 603.12: a *separate* ability the payment creates, so it is carried
    # separately and never folded into the accept branch. The difference is its
    # targets: it chooses them when it is created, where the accept branch has
    # only the ones this resolution already has — and this trigger fired on a
    # card being drawn, which named nothing at all.
    on_reflexive = _steps(instruction, "reflexive")

    # An offer the player cannot afford is never made; its decline branch (a
    # "…unless you pay" penalty) still applies.
    if cost and not game._player_can_pay_optional(player, {"cost": cost}):
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

    entry = {
        "card_name": context.card.name,
        "cost": cost,
        "life": 0,
        "_source_permanent": context.source_permanent,
        # Instructions to run on accept/decline, with the resolution context
        # they belong to. _pay_optional executes these when present.
        "_on_accept": on_accept,
        "_on_decline": on_decline,
        "_on_reflexive": on_reflexive,
        "_context": context,
    }
    if cost:
        entry["prompt"] = f"Pay {mana_cost_label(cost)}?"
    # Mirror a plain "gain N life" consequence into the legacy `life` field so
    # the prompt UI keeps describing what accepting does. Display only —
    # _pay_optional runs the instruction branch and returns before reading it.
    # This goes away when the pending-choice queue carries its own description.
    if len(on_accept) == 1 and on_accept[0].kind == "target_gains_life":
        amount = on_accept[0].payload.get("amount")
        if isinstance(amount, int):
            entry["life"] = amount
    game.arm_pending_choice("optional_pay", player_index, **entry)


@effect_handler("choose_one")
def choose_one(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A ``choose_one`` reached at *resolution*: alternatives that are a step of
    an effect already running ("that creature gains flying or first strike").

    Not a modal **ability**. A modal triggered ability chooses its mode as it is
    put on the stack (CR 700.2b), which
    ``mixins/stack/resolution._choose_trigger_mode`` does, and by the time such
    an ability resolves ``_chosen_trigger_instruction`` has already substituted
    the chosen mode — so a modal head never arrives here with a mode still to
    pick. What does arrive is the nested form, where there is no announcement to
    hang the choice on and the branch simply runs against this same context.

    The pick is a ``mode_choice`` pending prompt for an interactive controller;
    every other seat takes the default (the first printed mode - a stated
    policy, not a valuation) the moment it is armed, because the resolution has
    to finish.
    """
    modes = tuple(instruction.payload.get("modes") or ())
    if not modes:
        return True, "resolved"
    player_index = game.players.index(context.caster)
    game.arm_pending_choice(
        "mode_choice", player_index,
        card_name=context.card.name,
        labels=[mode["label"] for mode in modes],
        _modes=tuple(mode["instruction"] for mode in modes),
        _context=context,
    )
    return True, "resolved"


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
    """
    filters = instruction.payload.get("iterator") or {}
    steps = _steps(instruction, "effect")
    produced_by = filters.get("produced_by")
    if produced_by is not None:
        matched = list(context.results.get(produced_by) or ())
    else:
        matched = [
            permanent
            for player in game.players
            for permanent in list(player.battlefield)
            if permanent_matches_filter(game, permanent, filters)
        ]
    previous = context.iteration_target
    previous_seats = context.iteration_seats
    for permanent in matched:
        context.iteration_target = permanent
        context.iteration_seats = {
            **previous_seats,
            **_per_object_seats(context, permanent),
        }
        _run(game, steps, context)
    context.iteration_target = previous
    context.iteration_seats = previous_seats
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
