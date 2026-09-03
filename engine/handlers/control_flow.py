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

from ..damage_deaths import DAMAGED_BY_SOURCE_DIED
from ..exiled_records import is_live, record_in_context, source_object
from ..named_counters import counters_on
from ..oracle_types import PER_OBJECT_SEAT_RECORDS, OracleInstruction
from ..turn_state import started_the_turn
from ..repeated_offers import OFFER_TAKEN_RESULTS
from ..resumption import run_resumable
from ._common import (_card_matches_filter, attached_host, flip_coin,
                      permanent_matches_filter, permanent_state_holds)
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
    # "…if the number of permanents is **even**" (Chaos Lord). A parity is a
    # comparison with no second operand at all, which is why it is answered
    # before the absent-number default below: that default means "at least
    # one", and an even board of zero is a board this condition holds on.
    if op in ("even", "odd"):
        return (count % 2 == 0) == (op == "even")
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

    if kind == "self_in_graveyard_with_cards_above":
        # "…if **this card is in your graveyard with a creature card directly
        # above it**" (Death Spark, Krovikan Horror). CR 404.3's order, read
        # through the one module that knows what "above" means.
        #
        # "Your" graveyard is the ability's controller's, and for a card in a
        # graveyard CR 108.4a makes that its owner — which is the seat the
        # graveyard scan enqueued the trigger under, so ``context.caster`` is
        # already the right player and no second reading of ownership is needed.
        #
        # Asked as "is there *a* position that qualifies" rather than about one
        # remembered index: this is CR 603.4's re-check as the ability resolves,
        # and by then something may have been put on the graveyard. Two copies
        # of the card are the same object, so an index frozen at fire time is
        # not an identity either (the same reason the fire site carries indices
        # instead of cards).
        from ..graveyard_order import positions_satisfying

        if context.caster is None or context.card is None:
            return False
        return bool(
            positions_satisfying(context.caster.graveyard, context.card, payload)
        )

    if kind == "destroyed_target_was":
        # "Destroy target land. **If that land was a snow land**, …" (Icequake,
        # Thermokarst.) The permanent the destroy in front of this chose,
        # recorded by that handler *before* it destroyed anything — CR 608.2h's
        # last-known information, because by now the land is a card in a
        # graveyard and has no characteristics to ask about at all.
        #
        # Asked through the one matcher, with no observer and no source: the
        # question is about the object itself, and the lowering refuses any
        # narrowing that would need either.
        from ..subject_filters import subject_matches

        victim = context.results.get("destroyed_target")
        if victim is None:
            # The spell resolved with its target gone (CR 608.2b leaves a
            # legal-target check to the resolution). Nothing was destroyed, so
            # the clause asking what it was is False rather than a guess.
            return False
        return subject_matches(game, victim, payload.get("filter") or {})

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

    if kind == "on_battlefield":
        # "if no creatures are on the battlefield" (Pestilence, Withering
        # Wisps). The zone's own count: every battlefield permanent, whoever
        # controls it. The clause beside it (`controls`) starts from a list of
        # players for exactly the reason this one cannot — a per-seat count
        # compared against a threshold answers a different question from the
        # board's.
        #
        # Asked through `subject_matches` rather than the pure matcher, so a
        # narrowing that needs layer 6 or the ability's own source ("no *other*
        # creatures", "no creatures with flying") is answered rather than
        # dropped. The observer is the ability's controller, CR 109.5's seat.
        from ..subject_filters import subject_matches

        observer = (
            game.players.index(context.caster)
            if context.caster in game.players else None
        )
        count = sum(
            1
            for permanent in game.all_permanents()
            if subject_matches(
                game,
                permanent,
                payload.get("filter") or {},
                observer=observer,
                source=context.source_permanent,
            )
        )
        return _compare_count(count, payload.get("op", "ge"), payload.get("count"))

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
            answer = len(matches) == len(wanted)
        else:
            answer = bool(matches)
        # "If it **isn't** a land card" (Wand of Ith) — the same reading turned
        # over at the end, after the union rule above has been applied, because
        # negating each type separately would ask a different question.
        return (not answer) if payload.get("negated") else answer

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

    if kind == "counted_number":
        # "**If the number** is odd, …" (Chaos Moon.) The number the count in
        # front of this recorded, never a second count of the board: the two
        # branches are one question asked once, and re-counting here would let a
        # board that changed between them answer both or neither.
        #
        # An absent record is False for either parity rather than a guess — the
        # lowering refuses a back-reference with no count in front of it, so
        # this is unreachable from a compiled card.
        if "counted_number" not in context.results:
            return False
        return _compare_count(
            int(context.results["counted_number"]), str(payload.get("op", "")), None
        )

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
        if payload.get("subject") == "attached":
            # "…if **it** didn't attack this turn", printed on an Aura and
            # asked of the creature it enchants (Aggression). CR 613/303.4: the
            # Aura's own state is not what the sentence is about, and with the
            # host gone there is nothing to ask — False, which is the direction
            # that does not destroy anything.
            source = attached_host(game, source)
        if source is None:
            return False
        state = payload.get("state")
        if not state:
            return False
        # Through the one table that says what a printed state word asks of a
        # permanent, never `getattr`: "blocking" is not a field (it is
        # `blocking_attacker_index`) and "attacked this turn" is a mark in
        # metadata, so a direct read answers False forever for both.
        value = permanent_state_holds(source, state)
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

    if kind == "zone_card_count":
        # "If your library has ten or more cards in it" (Phyrexian Portal).
        # Read when the instruction is followed (CR 608.2c), not when the
        # ability was activated: a library that shrank in between is the
        # library this asks about.
        whose = str(payload.get("player") or "you")
        player = context.caster if whose == "you" else context.target
        if player is None:
            return False
        pile = getattr(player, str(payload.get("zone") or "library"), None)
        if pile is None:
            return False
        return _compare_count(
            len(pile), str(payload.get("op", "")), payload.get("value")
        )

    if kind == "milled_this_way":
        # "If one or more creature cards were put into that graveyard this
        # way." (Helm of Obedience.) The record the loop wrote, not the
        # graveyard: the pile also holds cards this effect never touched, and
        # the sentence asks about the ones it did. No record means the loop
        # never ran, which is False rather than a guess at a pile it did not
        # fill — the same rule ``exiled_card_was`` states above.
        #
        # ``any``, not ``all``: the printed floor is "one or more", where the
        # exiled-card test one branch up asks about a set the sentence in front
        # of it defined in full.
        cards = context.results.get("milled_this_way") or []
        wanted = tuple(payload.get("card_types") or ())
        return any(
            any(name in card.type_line.lower() for name in wanted)
            for card in cards
        )

    if kind == "target_is_color":
        # "Counter target spell **if it's red**." (Hydroblast, Pyroblast.)
        # CR 608.2c: the colour is read while the instruction is followed, not
        # when the target was chosen — so a spell that was red at announcement
        # and is not now goes uncountered, and the picker offers every spell
        # because "target spell" is the whole of the printed restriction
        # (CR 608.2b).
        #
        # Which object the pronoun names was decided at lowering, off the
        # effect this guards, and the two halves are resolved by the readers
        # those effects use: a counter reads `context.stack_target`, a destroy
        # resolves the chosen permanent. Asking one and falling back to the
        # other would answer about whatever object happened to be in reach.
        wanted = payload.get("color")
        if payload.get("target") == "spell":
            chosen = context.stack_target
            colors = (
                game._stack_item_colors(chosen)
                if chosen is not None and chosen in game.stack
                else ()
            )
        else:
            from ._common import permanent_effective_colors, resolve_target_permanent

            target = resolve_target_permanent(
                game, context,
                predicate=lambda perm: True,
                fallback_players=(),
                fallback_on_invalid_choice=False,
            )
            colors = permanent_effective_colors(target) if target is not None else ()
        # An object that is gone answers no to both readings, rather than
        # letting the negated one say yes about something that is not there —
        # the same call the keyword condition below makes.
        if not colors and payload.get("negated"):
            return False
        matched = wanted in colors
        return (not matched) if payload.get("negated") else matched

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

    if kind == "cost_object_was":
        # "…**if the exiled creature was a Thrull**" (Soul Exchange). The object
        # the *cost* ate (CR 601.2b / 602.2b), which left its zone before the
        # spell or ability was ever on the stack — so the only honest source is
        # the record the payment path kept (CR 608.2h), on the same channel
        # every other reader of a cost's spoils uses.
        #
        # The channels carry two shapes and both are answered: the cast and
        # activation sacrifice records hold a `Permanent`, whose *effective*
        # types are what CR 608.2h remembers, and the graveyard exile holds a
        # `CardDefinition`, which has no computed characteristics at all
        # (CR 613.1). Nothing recorded is False, which is also what the words
        # say: no creature was exiled, so the exiled creature was not a Thrull.
        from ..models import Permanent

        paid = (context.choices or {}).get(str(payload.get("channel")))
        if paid is None:
            return False
        described = payload.get("filter") or {}
        if isinstance(paid, Permanent):
            return permanent_matches_filter(paid, described)
        return _card_matches_filter(paid, described)

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

    if kind == "destroyed_this_way":
        # "…**if that creature was destroyed this way**" (Infinite Authority).
        # Two records meet here and neither can answer alone: the scratchpad the
        # creating effect froze (CR 608.2h) says which creature the earlier step
        # marked, and the game's end-of-combat sweep says which permanents it
        # actually destroyed. Absence from the second is regeneration, a
        # creature that left first, or a mark that was never set — all of which
        # the card treats the same way.
        marked = (context.trigger_context or {}).get(payload.get("key")) or {}
        victim_ids = marked.get("victim_ids") or ()
        destroyed = set(game.destroyed_at_end_of_combat_this_turn)
        return any(victim_id in destroyed for victim_id in victim_ids)
    if kind == DAMAGED_BY_SOURCE_DIED:
        # "…if a creature dealt damage by this creature this turn died"
        # (Krovikan Vampire). The ledger the source carries, not the game-wide
        # death counter beside it: the counter cannot say *which* creature died
        # or who damaged it, and reading it here would fire this trigger on
        # every end step of every game with a trade in it.
        from ..damage_deaths import creatures_it_damaged_that_died

        return bool(creatures_it_damaged_that_died(context.source_permanent))
    if kind == "died_this_turn":
        return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0

    if kind == "had_plus1_counter":
        # "if it had a +1/+1 counter on it" (Basri's Lieutenant). The creature
        # is already in the graveyard by the time this resolves, so the only
        # legal source is the last-known information the fire site recorded
        # (CR 603.10). No record means nothing observed the death — False,
        # rather than a guess at a board that no longer holds the answer.
        return bool((context.trigger_context or {}).get("had_plus1_counter"))

    if kind == "source_exiled_with_counter":
        # "if this card is exiled with a scream counter on it" (All Hallow's
        # Eve). Both halves of the sentence, in the order it prints them: the
        # source is in exile, *and* it carries one of the named counters.
        #
        # The zone half is asked of the register rather than assumed from the
        # trigger having fired: an ability on the stack is independent of its
        # source (CR 608.2), so between the upkeep scan and this resolution
        # anything at all could have taken the card out of exile — and a gate
        # that answered off the trigger would be no gate.
        record = record_in_context(context)
        if record is None or not is_live(game, record):
            return False
        return counters_on(record, str(payload.get("counter", ""))) > 0

    if kind == "source_counter_count":
        # "if there are no more scream counters on it" (All Hallow's Eve),
        # asked after the removal that may have taken the last one off. The
        # source is a permanent or a card in exile, and one reader answers for
        # both — see ``engine/exiled_records.source_object``.
        holder = source_object(context)
        if holder is None:
            return False
        held = counters_on(holder, str(payload.get("counter", "")))
        wanted = int(payload.get("count", 0))
        # "five **or more**" (Fasting) against All Hallow's Eve's exact zero.
        # The comparison is read off the payload rather than assumed, because
        # an at-least test answered as an equality is a card that destroys
        # itself on the fifth counter and never again.
        if str(payload.get("comparison", "exactly")) == "at_least":
            return held >= wanted
        return held == wanted

    if kind == "source_ability_activations":
        # "If this ability has been activated four or more times this turn, …"
        # (Farrelite Priest, Initiates of the Ebon Hand.) The ledger the
        # activation path stamps on the permanent, read through its own module
        # so this question and CR 602.5's refusal count the same activations.
        #
        # The activation that is resolving has already been counted — the stamp
        # goes on once every cost and guard has passed — so the fourth use is
        # the one that sees four, which is what the card says.
        from ..activation_restrictions import activations_this_turn

        source = context.source_permanent
        if source is None:
            # The permanent left between activation and resolution (CR 400.7
            # makes anything that comes back a different object), so there is
            # no ledger to read and no creature the clause could be about.
            return False
        used = activations_this_turn(game, source)
        wanted = int(payload.get("count", 0))
        if str(payload.get("comparison", "at_least")) == "exactly":
            return used == wanted
        return used >= wanted

    if kind == "returned_to_hand_this_turn":
        # "a permanent was put into your hand from the battlefield this turn"
        # (Barrin). "Your" is the ability's controller; the bounce paths feed
        # the per-seat counter.
        seat = game.players.index(context.caster)
        return int(game.permanents_to_hand_this_turn.get(seat, 0)) > 0

    if kind == "attacked_or_blocked_this_combat":
        # "…if this creature attacked or blocked this combat" (the Clockwork
        # cycle, Kjeldoran Home Guard). **Read off the trigger's context, never
        # the board.** The end-of-combat step announces this batch and then
        # sweeps the combat record before the priority window that resolves it,
        # so by CR 603.4's second check "blocked this combat" is already gone
        # — a board read here would answer False for every blocker and the
        # ability would do nothing on exactly half the cards that print it.
        # The fire site freezes the answer (CR 603.10), which is the same
        # discipline it already takes with ``combat_opponents``.
        #
        # A missing key means this condition was asked under some other trigger,
        # where nothing froze an answer: False, which is the direction that does
        # nothing rather than the one that acts on a guess.
        return bool(
            (context.trigger_context or {}).get("attacked_or_blocked_this_combat")
        )

    if kind == "in_a_block_since_your_last_upkeep":
        # "…if it has blocked or been blocked since your last upkeep" (Wiitigo).
        # A window that outlives every per-turn combat record, so the
        # declare-blockers step stamps a seat-turn ordinal on both sides of each
        # declared block and `turn_state` does the arithmetic.
        #
        # "Your" is the ability's controller (CR 109.5), which is also the seat
        # the stamp has to name: a creature that blocked under a thief blocked
        # during the thief's turn, and its own controller's window is empty.
        from ..turn_state import in_a_block_since_seats_last_upkeep

        source = context.source_permanent
        if source is None or context.caster not in game.players:
            return False
        return in_a_block_since_seats_last_upkeep(
            game, source, game.players.index(context.caster)
        )

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
    won = flip_coin()
    context.results["coin_flip"] = won
    game.log.append(
        f"{context.card.name}: {'won' if won else 'lost'} the coin flip"
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
    won = flip_coin()
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


@effect_handler("choose_color")
def choose_color(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Choose a color." (Chromatic Armor's activated ability.)

    Beside ``choose_number`` above and for the same reason: the sentence
    produces a *value* and no effect of its own, and what reads it back is a
    separate sentence on the card — here the Aura's static shield, which
    answers to "sources of the last chosen color". So the colour is recorded on
    the permanent rather than in this resolution's scratchpad, and "last" is
    what overwriting means.

    The **same** prompt CR 614.1c's entry-state version arms, on the same
    metadata key: a card may print both (this one does), and two prompts writing
    two keys would be a permanent with two chosen colours and a shield reading
    whichever one its author remembered.

    A deterministic default is stamped first — the colour the controller's
    opponents hold most of among nontoken permanents, the same policy the entry
    state applies — so a headless or AI seat is never blocked and never left
    with a colour nobody controls, which is a legal choice no player would make.
    """
    permanent = context.source_permanent
    card_name = getattr(context.card, "name", "an effect")
    if permanent is None:
        game.log.append(f"{card_name}: no permanent to record a colour on")
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    if seat is None:
        return True, "resolved"
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
    permanent.metadata["chosen_color"] = default_color
    game.arm_pending_choice(
        "enter_choice", seat,
        card_name=permanent.card.name, permanent=permanent,
        needs_color=True, opponents=[], default_seat=None,
        default_color=default_color,
    )
    game.log.append(f"{card_name}: {game.players[seat].name} chooses a color")
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
    # "…unless the player **puts a -1/-1 counter on a creature they control**"
    # (Thelon's Chant, Tourach's Chant). A price paid out of the offered seat's
    # own board, so a seat with no creature cannot pay it — and accepting anyway
    # would buy off the damage for nothing, which is the same failure the
    # sacrifice above is gated on. Only the pick *from the offered seat's own
    # battlefield* is asked: a choice drawn from anywhere else is not a price
    # this player pays, and answering False for it would withdraw an offer the
    # card makes.
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
    # underneath treats "nothing attached" as a no-op. Read off the source's own
    # attachment, the same field the handler reads.
    if instruction.kind == "sacrifice_attached_permanent":
        return source is not None and source.metadata.get("attached_to") is not None
    # "**Pay 4 life** or put the card on top of your library." (Sylvan
    # Library.) CR 119.4: a player may pay life only with a life total at least
    # the amount, so at 3 life the payment is not one of the two things this
    # sentence lets its controller choose between. Asked through the handler's
    # own predicate, so the alternative that is offered and the alternative
    # that is performed are decided by one rule.
    if instruction.kind == "pay_life":
        from .life_and_game import can_pay_life

        return can_pay_life(player, int(instruction.payload.get("amount", 0)))
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

    def offer(player_index: int) -> None:
        _offer_to_seat(
            game, instruction, context, player_index, rebind=actor in _EACH_ACTORS
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
_EACH_ACTORS = frozenset({"each_player", "each_opponent", "defending_player"})


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

    ``context.caster`` is deliberately **not** moved, and that is a known
    limit rather than a decision: an action inside the offer that addresses the
    effect's controller — the "you" form of a discard, say — would act on the
    caster while ``_action_is_takeable`` above tested the *offered* player's
    hand. No card in the pool prints that pair (Rebirth's ante and life-set both
    read the target), and the one that would have, Mind Bomb, is collapsed into
    a per-seat prompt before it reaches here
    (``grammar/lowering/control_flow._each_player_optional_discard``).
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
        context = dataclasses.replace(context, target=player, caster=player)
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
        _resolved_cost(alternative, context)
        for alternative in (instruction.payload.get("cost_alternatives") or ())
    ]
    if (cost or life_cost) and not game._player_can_pay_optional(player, {
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
    if cost:
        printed = " or ".join(
            mana_cost_label(option) for option in (cost, *alternatives)
        )
        entry["prompt"] = (
            f"Pay {printed} or {life_alternative} life?"
            if life_alternative
            else f"Pay {printed}?"
        )
    elif life_cost:
        entry["prompt"] = f"Pay {life_cost} life?"
    # Mirror a plain "gain N life" consequence into the legacy `life` field so
    # the prompt UI keeps describing what accepting does. Display only —
    # _pay_optional runs the instruction branch and returns before reading it.
    # This goes away when the pending-choice queue carries its own description.
    if len(on_accept) == 1 and on_accept[0].kind == "target_gains_life":
        amount = on_accept[0].payload.get("amount")
        if isinstance(amount, int):
            entry["life"] = amount
    game.arm_pending_choice("optional_pay", player_index, **entry)


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
    """
    payload = dict(instruction.payload)
    unpaid = tuple(payload.get("unpaid") or ())
    cost = dict(payload.get("cost") or {})
    caster = context.caster
    if caster is None or caster not in game.players:
        return True, "resolved"
    caster_index = game.players.index(caster)
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
    count = len(game.players)
    active = game.active_player_index or 0
    seats = [
        index
        for index in sorted(
            range(count), key=lambda i: ((i - active) % count, i)
        )
        if not getattr(game.players[index], "lost", False)
        and (payload.get("payer") == "any_player" or index != caster_index)
    ]
    asked = int(payload.get("asked_seats", 0))
    if asked >= len(seats):
        # Everyone declined (or there was nobody to ask), so the clause is not
        # bought off and the effect happens.
        for step in unpaid:
            game._execute_oracle_instruction(step, context)
        return True, "resolved"
    seat = seats[asked]
    game.arm_pending_choice(
        "optional_pay", seat,
        card_name=context.card.name if context.card is not None else "",
        cost=cost,
        life=0,
        _source_permanent=context.source_permanent,
        # Paying ends the chain: nothing runs, and no later opponent is asked.
        _on_accept=(),
        _on_decline=(
            OracleInstruction(
                "unless_player_pays", "", {**payload, "asked_seats": asked + 1}
            ),
        ),
        _on_reflexive=(),
        _context=context,
        prompt=f"Pay {mana_cost_label(cost)}?" if cost else "Pay?",
    )
    return True, "resolved"


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
            game, context.caster, mode["instruction"], context.source_permanent
        )
    )
    if not takeable:
        game.log.append(
            f"{context.card.name}: no alternative can be taken"
        )
        return True, "resolved"
    modes = takeable
    player_index = game.players.index(context.caster)
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
    seat_set = filters.get("players")
    if repeat_key is not None:
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
