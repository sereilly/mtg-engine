"""Conditions: what a lowered ``condition`` payload asks, one handler per kind.

``evaluate_condition`` was a single function of 1,815 lines — seventy-two
``if kind == …`` arms in a module whose own rule is that adding a card means
adding entries, not editing dispatch. It was also where a wave's branches met:
a new condition was a new arm in the middle of one function that six or seven
groups a set were editing. Each arm is a registered handler now, in the order
the arms had, and a duplicate kind raises at import.

**An unregistered kind answers False**, as it always did: the grammar refuses
to lower a condition it cannot describe, so an unknown kind never arrives from
a grammar-compiled card. ``tests/engine/test_condition_registry.py`` holds
that both ways against the compiled pool — a kind the pool carries with no
handler, and a handler nothing in the pool produces.

Conditional *statics* ("as long as …") have their own, smaller vocabulary in
``engine/static_bonuses.py``; that guard names the kinds only it evaluates.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ..damage_deaths import DAMAGED_BY_SOURCE_DIED
from ..exiled_records import is_live, record_in_context, source_object
from ..faces import has_name
from ..named_counters import counters_on
from ..oracle_types import (BIDDING_WINNER, CHOSEN_COLOR_THIS_WAY,
                            CHOSEN_NUMBER_THIS_WAY, DISCARDED_THIS_WAY,
                            MILLED_THIS_WAY, PROCESS_ROUNDS_SO_FAR,
                            REVEALED_HAND_CARDS, REVEALED_TOP_CARDS_BY_SEAT)
from ..turn_state import started_the_turn
from ._common import (_card_matches_filter, attached_host,
                      defending_player_seat, permanent_matches_filter,
                      permanent_state_holds)

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext

ConditionHandler = Callable[["Game", "OracleExecutionContext", dict], bool]

#: ``{condition kind: its handler}``. Filled by :func:`condition` below.
CONDITIONS: dict[str, ConditionHandler] = {}


def condition(*kinds: str):
    """Register the decorated function as the handler for each of *kinds*."""
    def register(handler: ConditionHandler) -> ConditionHandler:
        for kind in kinds:
            if kind in CONDITIONS:
                raise ValueError(f"condition kind {kind!r} is registered twice")
            CONDITIONS[kind] = handler
        return handler
    return register


def evaluate_condition(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    """Evaluate a lowered condition payload.

    Kept small on purpose: an unrecognized condition returns False rather than
    guessing, and the grammar refuses to lower conditions it cannot describe, so
    an unknown condition never reaches here from a grammar-compiled card.
    """
    kind = payload.get("kind")
    handler = CONDITIONS.get(kind) if isinstance(kind, str) else None
    if handler is None:
        return False
    return handler(game, context, payload)


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


def _strict_leader(game: Game, score) -> "int | None":
    """The living seat *score* puts strictly ahead of every other, or None.

    The arithmetic behind every "more <something> than each other player" this
    engine reads, in one place because the *rule* is one: "more than" is strict,
    so a tie names nobody, and players who have lost are not in the comparison
    at all (CR 800.4a). Written twice, the two copies would be free to disagree
    about a tie — and a superlative that quietly picks the first of two leaders
    is a card that answers on a board where the sentence names no one.

    *score* is called with the seat index and reads whatever the sentence
    counts: a life total, or the permanents that seat controls.
    """
    living = [
        index for index, player in enumerate(game.players) if not player.lost
    ]
    if not living:
        return None
    scores = {index: int(score(index)) for index in living}
    best = max(scores.values())
    leaders = [index for index in living if scores[index] == best]
    return leaders[0] if len(leaders) == 1 else None


def most_life_seat(game: Game) -> "int | None":
    """The seat strictly ahead of every other living one on life, or None.

    "…**the player with the most life** gains control of this creature." (Wild
    Dogs, whose intervening-if asks the same question one clause earlier.) One
    reader for both, so the gate and the hand-over cannot disagree about
    whether there is a leader — read apart, the trigger could fire on a board
    where the effect then found nobody to name.

    A tie names nobody, and that is the printed reading: "more life than each
    other player" is strict, and CR 104.3b's "the player with the most life"
    has no answer when two are level.
    """
    return _strict_leader(game, lambda index: game.players[index].life)


def most_permanents_seat(game: Game) -> "int | None":
    """The seat controlling strictly more permanents than each other, or None.

    "**A player who controls more permanents than each other player** can't
    play lands or cast artifact, creature, or enchantment spells." (Damping
    Engine.) The same superlative as :func:`most_life_seat` over a different
    count, which is why both are one arithmetic: a tie names nobody, so the
    Engine stops nobody on a level board — and that is the card, not a corner
    of it.

    Counted through the control seam (CR 613 layer 2), never off
    ``player.battlefield``: the lists are the *projection* of the derived
    controller, so a raw read is a second opinion about who controls what — and
    on a card whose whole effect is a comparison of two such counts, a stolen
    permanent counted on both sides is the card pointing at the wrong player.
    """
    return _strict_leader(
        game, lambda index: sum(1 for _ in game.controlled_by(index))
    )


def most_controlling_seat(game: Game, filters: dict) -> "int | None":
    """The seat controlling strictly more of a printed phrase than each other.

    "At the beginning of your upkeep, **if a player controls more creatures
    than each other player, the player who controls the most creatures** gains
    control of this creature." (Wild Mammoth.) :func:`most_permanents_seat`
    with the noun phrase as data — the intervening-if and the hand-over behind
    it both ask this one reader, so the gate cannot open on a board where the
    hand-over then names nobody, which is the pairing :func:`most_life_seat`
    already keeps for Wild Dogs.

    Counted through the control seam, and each seat's phrase is answered by
    ``subject_matches`` with that seat as the observer: "creatures" is a layer
    question (an animated land counts, CR 613 layer 4), and the one reader of a
    printed noun phrase is what the lowering held the phrase to.
    """
    from ..subject_filters import subject_matches

    return _strict_leader(
        game,
        lambda index: sum(
            1 for permanent in game.controlled_by(index)
            if subject_matches(game, permanent, filters, observer=index)
        ),
    )


def _condition_player(game: Game, context: OracleExecutionContext, whose):
    """The single seat a condition's ``player`` word names, or None.

    Three payload words reach here — "you", a target reference, and the
    ``event_subject_player`` the fire site froze — and one reader answers all
    three, because a clause that fell back to the caster where the printed word
    said "that player" asks about the wrong life total or the wrong hand and
    says nothing about having done so. The lowering resolves the *pronoun*
    (`lowering/conditions._condition_seat`); this resolves the *seat*.

    None when the reference names nobody, which every caller reads as a
    condition that does not hold — the same direction CR 603.4 takes for an
    intervening-if it cannot check.
    """
    word = str(whose or "you")
    if word == "you":
        return context.caster
    if word == "event_subject_player":
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return None
        return game.players[seat]
    return context.target


def _any_opponent(game: Game, context: OracleExecutionContext, holds) -> bool:
    """Whether *holds* is true of **some** opponent of the asking seat.

    "If **an opponent** has no cards in hand" (Avatar of Will): the article is
    an existential over the seats CR 102.2 makes opponents, and only living ones
    (CR 800.4a — ``Game.opponents_of``). Not :func:`_condition_player`, which
    names one seat: a duel cannot tell the two readings apart, and a
    free-for-all table answers them differently.
    """
    if context.caster not in game.players:
        return False
    return any(
        holds(game.players[seat])
        for seat in game.opponents_of(game.players.index(context.caster))
    )


@condition("additional_cost_paid")
def _condition_additional_cost_paid(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "**If this spell's additional cost was paid**, …" (Undergrowth.)
    # CR 601.2b's optional additional cost, asked at resolution about an
    # announcement made while the spell was being cast. The mana pool that
    # paid it emptied at the end of that step (CR 500.5), so the count the
    # casting path recorded on the stack item is the only record there is —
    # and a resolution with no record answers False, which is what
    # declining the offer means.
    paid = (context.choices or {}).get("additional_costs_paid") or {}
    wanted = payload.get("symbols")
    if wanted is None:
        return any(int(times or 0) > 0 for times in paid.values())
    return int(paid.get(str(wanted), 0) or 0) > 0


@condition("was_kicked")
def _condition_was_kicked(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If **this spell was kicked**" / "if **it was kicked**" / "if this
    # creature **wasn't kicked**" (CR 702.33d). One question with two places
    # the answer is kept, picked by what is asking:
    #
    # * a **permanent**'s ability (an entry trigger, Skizzik's end-step
    #   trigger) reads the stamp ``resolution._resolve_card`` left on the
    #   permanent that spell became -- the stack item is long gone, and a
    #   permanent nothing cast has no stamp, which is the rule's answer;
    # * a **spell** resolving reads its own stack record.
    #
    # Both come from ``cast_costs.kicked``, the reader keyed by the offer
    # the kicker rewrite produced.
    #
    # "…kicked **with its {1}{G} kicker**" (the Battlemages, CR 702.33f) is
    # the same question about one of the card's two kicker costs
    # (CR 702.33b): ``kicker`` is that cost's recorded key, and the two
    # places answer it the same way -- the permanent off
    # ``KICKED_WITH``, the tuple of keys ``_resolve_card`` stamped beside
    # the flag, and the spell off its own record through
    # ``cast_costs.kicked_with``. A permanent stamped by nothing (not cast,
    # CR 400.7) was kicked with none of them.
    from ..cast_costs import KICKED, KICKED_WITH, kicked, kicked_with

    wanted = payload.get("kicker")
    source = context.source_permanent
    if source is not None:
        if wanted is None:
            answer = bool(source.metadata.get(KICKED))
        else:
            answer = str(wanted) in tuple(
                source.metadata.get(KICKED_WITH) or ()
            )
    elif context.card is None:
        answer = False
    elif wanted is None:
        answer = kicked(context.card, context.choices)
    else:
        answer = kicked_with(context.card, context.choices, str(wanted))
    return answer != bool(payload.get("negated"))


@condition("target_was_kicked")
def _condition_target_was_kicked(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Counter target spell **if it was kicked**." (Ertai's Trickery.)
    # CR 702.33d's fact about *another* spell: the one this effect targets,
    # which the lowering settled off the branch this guards -- the
    # ``target_is_color`` arrangement, read through the same half of the
    # context a counter reads (``context.stack_target``).
    #
    # Asked of that spell's own stack record through ``cast_costs.kicked``,
    # so it is any of its kicker costs (a Battlemage that paid only its
    # second is a kicked spell) and never an unrelated optional cost: a
    # bought-back Capsize was not kicked. A spell that has left the stack
    # answers no to both polarities, for the reason the colour clause
    # gives -- the negated reading must not say yes about nothing.
    from ..cast_costs import kicked, kicked_with

    chosen = context.stack_target
    if (
        payload.get("target") != "spell"
        or chosen is None
        or chosen not in game.stack
        or chosen.card is None
    ):
        return False
    wanted = payload.get("kicker")
    answer = (
        kicked(chosen.card, chosen.choices) if wanted is None
        else kicked_with(chosen.card, chosen.choices, str(wanted))
    )
    return answer != bool(payload.get("negated"))


@condition("all_of")
def _condition_all_of(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # Every part, and an empty list is False rather than the vacuous True
    # `all([])` would give: a conjunction that lowered to nothing is a
    # condition nobody wrote, and answering True would run the effect
    # unconditionally.
    parts = payload.get("conditions") or []
    return bool(parts) and all(
        evaluate_condition(game, context, part) for part in parts
    )


@condition("any_of")
def _condition_any_of(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # Any part, and an empty list is False for ``all_of``'s reason one
    # clause up: a disjunction that lowered to nothing is a condition nobody
    # wrote, and `any([])` is already False — the emptiness is stated here so
    # the two joiners read the same way rather than agreeing by accident.
    parts = payload.get("conditions") or []
    return bool(parts) and any(
        evaluate_condition(game, context, part) for part in parts
    )


@condition("same_named_object")
def _condition_same_named_object(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…if **a card with the same name** is in a graveyard or **a nontoken
    # permanent with the same name** is on the battlefield." (Bazaar of
    # Wonders.) CR 201.2: two objects have the same name when their names
    # are identical, and the name compared against is the *spell the trigger
    # fired on* — frozen by the cast fire site, because by the time this
    # ability resolves the spell may have left the stack.
    #
    # The spell itself is never one of the objects it is compared with: it
    # is on the stack, and neither zone this searches is the stack. A
    # permanent that entered from that spell **is** one, which is what makes
    # the enchantment's own second half read the way the card is printed.
    if payload.get("same_name_as") == "target":
        # "…if **another** permanent with the same name is on the
        # battlefield." (Winnow.) The name is the *targeted permanent's*,
        # read as CR 608.2c reads everything — while the instruction is
        # followed — and through ``effective_card`` on both sides, because
        # CR 707.2 makes a copy's name the copied one. "Another" is
        # identity, never value: two Grizzly Bears are equal objects to a
        # dataclass comparison and are exactly the board this asks about.
        from ._common import resolve_target_permanent

        target = resolve_target_permanent(
            game, context,
            predicate=lambda perm: True,
            fallback_players=(),
            fallback_on_invalid_choice=False,
        )
        if target is None:
            return False
        target_name = target.effective_card.name
        nontoken = bool(payload.get("nontoken"))
        return bool(target_name) and any(
            other is not target
            and other.effective_card.name == target_name
            and not (nontoken and other.metadata.get("is_token"))
            for other in game.all_permanents()
        )
    cast_card = (context.trigger_context or {}).get("cast_card")
    name = getattr(cast_card, "name", None)
    if not name:
        # No event froze one. The lowering refuses this condition outside a
        # cast trigger, so reaching here means the fire site recorded
        # nothing — False, rather than a scan for the empty name that every
        # object would fail anyway.
        return False
    if payload.get("zone") == "graveyard":
        return any(
            # CR 201.2a over CR 709.4a: a split card in a graveyard has
            # both halves' names, so it shares a name with either half.
            has_name(card, name)
            for player in game.players
            for card in player.graveyard
        )
    nontoken = bool(payload.get("nontoken"))
    return any(
        # ``effective_card`` rather than the printed one: CR 707.2 makes a
        # copy's name the copied name, so a Clone of the spell being cast
        # really is an object with the same name (CR 201.2).
        permanent.effective_card.name == name
        and not (nontoken and permanent.metadata.get("is_token"))
        for permanent in game.all_permanents()
    )


@condition("self_in_graveyard_with_cards_above")
def _condition_self_in_graveyard_with_cards_above(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("self_only_card_of_type_in_graveyard")
def _condition_self_only_card_of_type_in_graveyard(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…if **this card is the only creature card in your graveyard**"
    # (Nether Spirit). CR 603.4's re-check, asked of the pile as it stands
    # now — the ability fired at the start of the upkeep and anything may
    # have reached the graveyard since.
    #
    # **The identity is half the test.** A count of one is a different
    # question: a graveyard holding one creature card that is some *other*
    # creature satisfies "exactly one" and satisfies nothing this card says.
    # Two copies of one card are the same immutable object, so the
    # comparison is `is` against every entry rather than a name match — and
    # a graveyard holding two of them has two creature cards in it and
    # answers False, which is what the card says.
    #
    # "Your" graveyard is the ability's controller's, and CR 108.4a makes
    # that the owner for a card nobody controls — the seat the graveyard
    # scan enqueued the trigger under, so ``context.caster`` is already
    # right.
    from ..graveyard_order import is_printed_type

    if context.caster is None or context.card is None:
        return False
    wanted = str(payload.get("card_type", "creature"))
    matching = [
        held for held in context.caster.graveyard
        if is_printed_type(held, wanted)
    ]
    return len(matching) == 1 and matching[0] is context.card


@condition("destroyed_target_was")
def _condition_destroyed_target_was(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("blockers_of_bound_creature")
def _condition_blockers_of_bound_creature(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("on_battlefield")
def _condition_on_battlefield(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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
    filters = dict(payload.get("filter") or {})
    # "if there are two or more **other** creatures on the battlefield"
    # (Portcullis), under "whenever a creature enters". The word excludes
    # the object the *firing event* was about, not the ability's source —
    # which the lowering decided, because that is the one place the trigger's
    # noun phrase and the condition's are both in view. Carried out here
    # rather than by the matcher for ``exclude_self``'s reason two branches
    # up: the excluded object is a permanent the caller holds, not a
    # characteristic a filter can test.
    #
    # An event that froze no id excludes nothing, which is the loud
    # direction: it counts one *more* permanent than the card means, so a
    # trigger whose threshold this decides fires where it should not — and
    # every event this key is emitted under stamps the id.
    excluded_id = (
        (context.trigger_context or {}).get("event_subject_permanent_id")
        if filters.pop("exclude_event_subject", None)
        else None
    )
    count = sum(
        1
        for permanent in game.all_permanents()
        if permanent.permanent_id != excluded_id
        and subject_matches(
            game,
            permanent,
            filters,
            observer=observer,
            source=context.source_permanent,
        )
    )
    return _compare_count(count, payload.get("op", "ge"), payload.get("count"))


@condition("controls")
def _condition_controls(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    who = payload.get("who", "you")
    if who == "any_player":
        # "if **a player** controls more creatures than each other player"
        # (Wild Mammoth). An existential over a superlative: is *anybody*
        # strictly ahead of everybody else? Answered before the per-seat
        # reads below, which would read "any player" as every seat at once
        # and then refuse the superlative for naming more than one — and
        # through the reader the hand-over asks, so the two cannot disagree
        # about a tie. The lowering admits the word under the superlative
        # and nothing else; any other op here is a payload nobody built.
        if payload.get("op") != "more_than_each_other_player":
            return False
        return most_controlling_seat(
            game, dict(payload.get("filter") or {})
        ) is not None
    players = [context.caster] if who == "you" else list(game.players)
    if who in ("each_opponent", "opponent"):
        players = [p for p in game.players if p is not context.caster]
    # **The pooled tally below is a trap for "each opponent" with a
    # number**, and it is held shut at the lowering rather than answered
    # here. "if **your opponents** control no creatures" (Kezzerdrix) and
    # "if **each opponent** controls …" both parse to ``each_opponent``
    # (`grammar/seats.py` aliases them on purpose), but with a count they
    # are two questions: the plural is one total across every opponent's
    # board, the "each" is a test every opponent must pass on their own.
    # The payload cannot say which was printed, so
    # `lowering/conditions.py` admits the seat only under "no" / zero —
    # the one comparison where the sum and every-one-of-them agree — and
    # refuses any other count rather than guessing. That is the only shape
    # the pool prints; the day a card prints the other, the refusal names
    # it.
    if who in ("target_opponent", "target_player"):
        # "If **target opponent** controls …": the seat the announcement
        # chose (CR 601.2c), not every opponent at the table — the same
        # narrowing ``more_than_you`` below already applies for Tithe.
        # Pooled, a three-seat game would have counted the boards of
        # players the spell never named. No shipped card prints a counted
        # one; this keeps the seat honest for the first that does.
        players = [context.target] if context.target in game.players else []
    if who == "defending_player":
        # "…if **defending player** controls no black nontoken permanents"
        # (Spectral Bears). The seat combat named (CR 506.2), through the
        # one reader every handler asks, which prefers what the attack
        # trigger froze (CR 603.10). This word used to fall through to the
        # every-player list above, so the attacker's *own* black permanent
        # counted: Spectral Bears with a Black Knight beside it never
        # triggered, and untapped every turn the card says it should not.
        seat = defending_player_seat(game, context)
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            return False
        players = [game.players[seat]]
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
    if payload.get("of_each_color"):
        # "you control a permanent **of each color**" (Spirit of
        # Resistance; "a creature of each color", Coalition Victory). Not a
        # count at all: the five colours must each be found among the
        # matching permanents, one gold permanent answering for each of its
        # own (CR 105.2b). One reader with the static evaluator one file
        # over (``static_bonuses.conditional_static_holds``), so the clause
        # means the same on a spell's "if" as on a standing "as long as".
        from ..object_colors import of_each_color

        return of_each_color(game, matched)
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
    # "if **that player** controls more lands than **each other player**"
    # (Greener Pastures). The superlative: the asked seat must beat every
    # other living one. Its own branch beside "more_than_you" rather than a
    # flag on it, because the two compare different sets — that one asks
    # whether *any* opponent beats the caster, this asks whether *one named
    # seat* beats all the rest — and reading either as the other is the
    # card answering about the wrong players.
    #
    # `players` above is already the seat the clause named (the trigger's
    # frozen "that player", or the caster). A tie fails: "more than" is
    # strict, which is what leaves the card idle on a mirrored board.
    if op == "more_than_each_other_player":
        if len(players) != 1:
            return False
        asked = players[0]
        return all(
            sum(
                1
                for permanent in game.controlled_by(other)
                if permanent_matches_filter(permanent, filters)
            ) < count
            for other in game.players
            if other is not asked and not other.lost
        )
    if op == "more_than_you":
        filters = payload.get("filter") or {}
        own = sum(
            1
            for permanent in game.controlled_by(context.caster)
            if permanent_matches_filter(permanent, filters)
        )
        # "…controls **at least four** more creatures than you" (Avatar of
        # Might). ``count`` is the printed margin, and the bare "more" rides
        # as 0 — a lead of one, which is what "more" means. So every payload
        # written before the margin existed reads exactly as it did.
        lead = max(1, int(payload.get("count") or 0))
        rivals = [
            player for player in game.players
            if player is not context.caster and not player.lost
        ]
        if who == "target_opponent":
            # "If **target opponent** controls more lands than you" (Tithe).
            # The seat the cast announced (its picker asks for an opponent),
            # not any of them: at a three-seat table another opponent's
            # lands are not the target's. No announced opponent holds for
            # nobody.
            rivals = [p for p in rivals if p is context.target]
        return any(
            sum(
                1
                for permanent in game.controlled_by(player)
                if permanent_matches_filter(permanent, filters)
            ) - own >= lead
            for player in rivals
        )
    if who == "opponent" and wanted is not None and not payload.get("shared_name"):
        # "if **an opponent** controls three or more creatures" (Defense of
        # the Heart) / "…seven or more lands" (Avatar of Fury). The article
        # is an existential over seats: *one* opponent must hold the count.
        # The pooled tally above reads the union of every opponent's board,
        # which a duel cannot tell apart and a free-for-all table can — two
        # opponents with two creatures each are not "an opponent controls
        # three", and answering yes makes the card fire, or cost less, on a
        # board it does not name. A presence test ("an opponent controls a
        # Swamp") is the same answer either way and keeps the pooled read.
        return any(
            _compare_count(
                sum(
                    1
                    for permanent in game.controlled_by(player)
                    if permanent is not source
                    and permanent_matches_filter(permanent, filters)
                ),
                op,
                wanted,
            )
            for player in players
            if not player.lost
        )
    return _compare_count(count, op, wanted)


@condition("revealed_card_is")
def _condition_revealed_card_is(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If it's a creature or land card" (Track Down). Reads the card an
    # earlier step of this same resolution revealed, never the library:
    # the branch below this one draws, and a re-read would then be asking
    # about whichever card the draw uncovered.
    revealed = context.results.get("revealed_card")
    if revealed is None:
        return False
    wanted = [str(t) for t in (payload.get("card_types") or ())]
    line = (revealed.type_line or "").lower()
    # "If it's a **nonland** card" (Wand of Denial). The printed exclusion,
    # asked before the union below because it is the whole of what these
    # phrases say: "nonland card" names no type at all, so a reader that
    # needed one answered False for every card and the clause was a gate
    # nothing could pass.
    excluded = [str(t) for t in (payload.get("excluded_types") or ())]
    if excluded and any(t in line for t in excluded):
        return bool(payload.get("negated"))
    if not wanted:
        # An exclusion on its own is satisfied by anything the exclusion
        # did not name, which is what "nonland card" means.
        answer = bool(excluded)
        return (not answer) if payload.get("negated") else answer
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
@condition("attackers_aimed_at_you")
def _condition_attackers_aimed_at_you(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    aimed = int((context.trigger_context or {}).get("attackers_aimed", 0))
    return aimed >= int(payload.get("count", 0))


@condition("entered_from")
def _condition_entered_from(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    source = context.source_permanent
    if source is None:
        return False
    wanted = payload.get("zone")
    if source.metadata.get("entered_from_zone") == wanted:
        return True
    return bool(payload.get("or_cast")) and (
        source.metadata.get("cast_from_zone") == wanted
    )


@condition("sacrificed_this_way_matches")
def _condition_sacrificed_this_way_matches(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If you sacrifice a **snow** Forest this way, …" (Gargantuan Gorilla),
    # "…an **Island** this way, …" (Serendib Djinn). The narrowed reading of
    # "if you do": the sacrifice happened and the branch still runs only if
    # what went matches the tighter phrase.
    #
    # Against the **cards** the sacrifice recorded, never the board: what
    # went is in a graveyard by now and is a different object (CR 400.7),
    # and a board read would answer about whatever is still there. An empty
    # record is False — an offer declined, or a mandatory sacrifice that
    # could not be paid, is not a sacrifice of anything.
    given = list(context.results.get(payload.get("key")) or ())
    described = payload.get("filter") or {}
    return any(_card_matches_filter(card, described) for card in given)


@condition("exiled_this_way_share_a_name")
def _condition_exiled_this_way_share_a_name(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…unless **it has the same name as another card exiled this way**" /
    # "…until **you exile two cards with the same name**" (Tainted Pact).
    # CR 201.2a over the cards this effect has exiled so far: the step in
    # front of the clause wrote this round's, and a repeated process files
    # the rounds before it under ``PROCESS_ROUNDS_SO_FAR``. By *position*
    # (``cards_sharing_a_name``), because "another" cannot be asked by
    # identity — two copies of a card in a library are one object.
    from ..counted_names import cards_sharing_a_name

    earlier = list(
        (context.results.get(PROCESS_ROUNDS_SO_FAR) or {}).get("exiled_cards")
        or ()
    )
    latest = list(context.results.get("exiled_cards") or ())
    sharing = cards_sharing_a_name(earlier + latest)
    if payload.get("of_latest"):
        return any(index >= len(earlier) for index in sharing)
    return bool(sharing)


@condition("it_happened")
def _condition_it_happened(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    happened = bool(context.results.get(payload.get("key")))
    # "If you **can't**" (Cocoon) is the same record read the other way. An
    # absent record is "it did not happen", which is also the honest answer
    # when the recording step itself could not run — an Aura that left
    # before its upkeep trigger resolved removed nothing (CR 608.2b), so
    # the can't-branch is exactly what should run.
    return not happened if payload.get("negated") else happened


@condition("counted_number")
def _condition_counted_number(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("won_bidding")
def _condition_won_bidding(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If **you** win the bidding, …" (Mages' Contest.) The auction wrote
    # the seat its high bid stood for; "you" is the resolving seat
    # (CR 109.5). An absent record is False rather than a guess — the
    # auction did not run (its spell's controller was gone), so nobody won.
    winner = context.results.get(BIDDING_WINNER)
    return winner is not None and winner == game.players.index(context.caster)


@condition("coin_flip")
def _condition_coin_flip(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # CR 705.2. The flip recorded its result; asking again would flip a
    # second coin, so a card printing both branches could win *and* lose.
    # An absent record is False for either branch rather than a guess — the
    # grammar refuses to lower a flip condition with no flip in front of it,
    # so this is unreachable from a compiled card.
    if "coin_flip" not in context.results:
        return False
    return bool(context.results["coin_flip"]) is bool(payload.get("won", True))


@condition("subject_characteristic_is")
def _condition_subject_characteristic_is(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If this creature's power is 1 or more" (Lesser Werewolf), "If target
    # creature has toughness 5 or greater" (Blood Lust). CR 613's computed
    # characteristic, read through the layer accessors rather than off the
    # printed card: Lesser Werewolf's gate exists because the ability
    # shrinks its own source, and Blood Lust must see a creature another
    # spell already pumped. Nothing to ask about answers False — a source
    # that has left (CR 608.2b) and a target that is no longer legal both.
    from ._common import _comparison_holds, resolve_target_permanent

    characteristic = payload.get("characteristic")
    if payload.get("target") == "spell":
        # "Counter target spell **if its mana value is 2 or less**."
        # (Prohibit.) CR 608.2c: asked while the instruction is followed,
        # of the spell the counter beside it will act on — the reader that
        # effect uses, so the two mean one object. CR 202.3b: on the stack
        # an X in the cost is the announced value, which is
        # ``stack_object_mana_value``'s whole difference from a card's
        # printed number. A target that has left the stack has no mana
        # value to ask about and answers False.
        from ..targeting import stack_object_mana_value

        chosen = context.stack_target
        if chosen is None or chosen not in game.stack:
            return False
        value = stack_object_mana_value(chosen)
    else:
        if payload.get("target") == "permanent":
            # "Destroy target artifact **if its mana value is 2 or less**."
            # (Overload.) The pronoun spelling, whose target is whatever
            # permanent the effect beside it chose — so no type is asked
            # here (the resolver's default predicate is "a creature", which
            # answered None for every artifact and made the spell do
            # nothing) and no other battlefield is scanned for a stand-in:
            # the same call the colour clauses make, for their reason.
            subject = resolve_target_permanent(
                game, context,
                predicate=lambda perm: True,
                fallback_players=(),
                fallback_on_invalid_choice=False,
            )
        elif payload.get("subject") == "target":
            # Through the same resolver the arms use, so the branch and the
            # effect cannot disagree about which creature the sentence
            # meant.
            subject = resolve_target_permanent(
                game, context, fallback_on_invalid_choice=False
            )
        else:
            subject = context.source_permanent
        if subject is None:
            return False
        if characteristic == "mana_value":
            # CR 202.3: off the mana cost, read through layer 1 so a copy
            # has the copied card's; a token's is 0. The number the
            # "with mana value N or less" filter key reads.
            value = int(getattr(subject.effective_card, "cmc", 0) or 0)
        elif characteristic == "toughness":
            value = subject.effective_toughness
        else:
            value = subject.effective_power
    # "…less than or equal to **the number of cards in your graveyard**"
    # (Ghastly Demise). A bound that is a count, taken now — as the
    # instruction is followed (CR 608.2c) — through the evaluator every
    # counted amount goes through. The spell itself is still on the stack
    # while it resolves (CR 608.2n puts it in the graveyard as the last
    # step), so it does not count itself: the card's own ruling.
    bound = int(payload.get("count", 0))
    counted = payload.get("count_from")
    if isinstance(counted, dict):
        from ._common import count_from_payload

        bound = count_from_payload(game, context, counted)
    return _comparison_holds(
        {"op": payload.get("op", "eq"), "value": bound}, value,
    )


@condition("is_state")
def _condition_is_state(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("source_is_type")
def _condition_source_is_type(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "if this permanent is an enchantment" (the Hidden / Opal / Veiled
    # cycle). CR 205.2's card type asked of the ability's own source and
    # answered by CR 613 layer 4 — ``has_type``, never ``type_line``:
    # the whole cycle turns on the animation having *replaced* the
    # enchantment type (CR 205.1a), which the printed line still shows.
    #
    # A source that has left answers False, the direction CR 603.4 takes
    # for an intervening-if it cannot check.
    source = context.source_permanent
    if source is None:
        return False
    wanted = [str(word) for word in (payload.get("card_types") or ())]
    answer = bool(wanted) and all(source.has_type(word) for word in wanted)
    return (not answer) if payload.get("negated") else answer


@condition("source_on_battlefield")
def _condition_source_on_battlefield(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "if this enchantment is on the battlefield" (Tombstone Stairwell) —
    # CR 603.4 checked again at resolution, which is the whole reason the
    # clause is printed: the trigger goes on the stack, the enchantment is
    # destroyed in response, and the ability then does nothing.
    #
    # Through the control seam's `is_on_battlefield`, never a truth test on
    # the permanent: a `Permanent` that has left is still a live Python
    # object (the leaves-the-battlefield trigger beside this one depends on
    # that), so "we have one" is not "it is there".
    source = context.source_permanent
    there = source is not None and game.is_on_battlefield(source)
    return (not there) if payload.get("negated") else there


@condition("started_turn_state")
def _condition_started_turn_state(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("exiled_card_was")
def _condition_exiled_card_was(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("zone_card_count")
def _condition_zone_card_count(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If your library has ten or more cards in it" (Phyrexian Portal); "if
    # that player has five or more cards in hand" (Misers' Cage). Read when
    # the instruction is followed (CR 608.2c), not when the ability was
    # activated: a pile that changed in between is the pile this asks about.
    zone = str(payload.get("zone") or "library")

    def pile_holds(player) -> bool:
        pile = getattr(player, zone, None)
        return pile is not None and _compare_count(
            len(pile), str(payload.get("op", "")), payload.get("value")
        )

    if payload.get("player") == "opponent":
        # "If **an opponent** has no cards in hand" (Avatar of Will). The
        # article is an existential over seats, which `_condition_player`
        # cannot answer — it names one seat, and for this word it named the
        # resolution's *target*, which a cast-time cost and an untargeted
        # trigger do not have.
        return _any_opponent(game, context, pile_holds)
    player = _condition_player(game, context, payload.get("player"))
    if player is None:
        return False
    return pile_holds(player)


@condition("player_life")
def _condition_player_life(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If that player has 5 or less life" (Razor Pendulum). The twin of the
    # zone count above and the same reader for the seat, which is the whole
    # of why it is a branch rather than a zone name: a life total is not a
    # pile, and `getattr(player, "life")` returning an int where the branch
    # above expects a list is the kind of near-miss that answers rather than
    # failing.
    # "if **a player** has more life than each other player" (Wild Dogs).
    # A superlative over an existential seat: is *anybody* strictly ahead
    # of everybody else? Answered before the single-seat read below,
    # because there is no seat to read — and strictly, so a tie says no,
    # which is what leaves the Dogs where they are on a level board.
    if str(payload.get("op", "")) == "more_than_each_other_player":
        return most_life_seat(game) is not None

    def life_holds(player) -> bool:
        return _compare_count(
            int(player.life), str(payload.get("op", "")), payload.get("value")
        )

    if payload.get("player") == "opponent":
        # "if **an opponent** has 10 or less life" — the existential the
        # zone count above answers for the same word, for its reason.
        return _any_opponent(game, context, life_holds)
    player = _condition_player(game, context, payload.get("player"))
    if player is None:
        return False
    return life_holds(player)


@condition("cards_in_zones", "distinct_among")
def _condition_cards_in_zones(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If there are **ten or more creature cards total in all graveyards**"
    # (Avatar of Woe). The count is a ``count_spec`` — the one a
    # where-clause over the same noun phrase builds — so it is answered by
    # the one evaluator every such count goes through, and the narrowings a
    # card in a graveyard can carry are the ones that one tests.
    #
    # "If there are **four or more basic land types among lands that player
    # controls**" (Mask of Intolerance) is the same comparison over the
    # same kind of spec, with the aggregate naming what is counted — two
    # kinds because the two are admitted in different places (a cast-time
    # cost gate reads piles, never a seat an event froze), one branch
    # because nothing about answering them differs.
    from ._common import count_from_payload

    return _compare_count(
        count_from_payload(game, context, dict(payload.get("count") or {})),
        str(payload.get("op", "")),
        payload.get("value"),
    )


@condition("life_total_difference")
def _condition_life_total_difference(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If the difference between your life total and target player's life
    # total is 5 or less" (Psychic Transfer). Both seats through the same
    # reader the one-seat gate above uses, so "that player" and a target
    # mean here exactly what they mean there.
    #
    # ``abs``: CR 107.1 has no negative quantities and "the difference
    # between" is unsigned, so the card reads the same whichever player is
    # ahead. A signed subtraction would make Psychic Transfer castable only
    # while its controller was behind.
    #
    # A seat that resolves to nobody is False, which is the direction
    # CR 603.4 takes for a check it cannot make — and here it is also the
    # direction that stops an untargeted cast from swapping totals.
    player = _condition_player(game, context, payload.get("player"))
    other = _condition_player(game, context, payload.get("other"))
    if player is None or other is None:
        return False
    return _compare_count(
        abs(int(player.life) - int(other.life)),
        str(payload.get("op", "")),
        payload.get("value"),
    )


@condition("shared_color_milled_this_way")
def _condition_shared_color_milled_this_way(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "**If two cards that share a color were milled this way**, repeat
    # this process." (Grindstone.) The record the mill in front of this
    # wrote, never the graveyard: a graveyard holds whatever else has gone
    # there, and the words say "this way".
    #
    # A *shared* colour, so a colourless card can never satisfy it however
    # many are milled — Grindstone's famous stop. The test is over every
    # subset of the printed size, which for two is "some colour appears in
    # at least two of them"; written as a count per colour rather than as
    # pairs, because the printed number is a field and pairs would only
    # answer for two.
    from collections import Counter

    wanted = max(2, int(payload.get("count", 2) or 2))
    milled = tuple(context.results.get(MILLED_THIS_WAY) or ())
    if len(milled) < wanted:
        return False
    counts: Counter = Counter()
    for card in milled:
        for color in getattr(card, "colors", ()) or ():
            counts[color] += 1
    return any(seen >= wanted for seen in counts.values())


@condition("revealed_chosen_color_count")
def _condition_revealed_chosen_color_count(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "**If that opponent reveals exactly the chosen number of cards of the
    # chosen color**, you draw a card." (Scrying Glass.) Three records, all
    # written by earlier steps of this same resolution: the number a seat
    # named, the colour they named beside it, and the hand the reveal showed.
    #
    # The **record**, never the hand as it stands now. "Reveals" is what the
    # step in front of this one did, and by the time a longer card asked the
    # question the hand could have changed — the same rule every "this way"
    # test above follows.
    #
    # An absent record is not zero. With no reveal at all the count is not
    # "no cards of that colour", it is a question that was never asked, and
    # answering it False is the only honest reading — otherwise a chosen
    # number of zero would draw a card off a reveal that never happened.
    # (The lowering refuses the clause without all three producers, so this
    # is the belt to that braces.)
    wanted = context.results.get(CHOSEN_NUMBER_THIS_WAY)
    color = context.results.get(CHOSEN_COLOR_THIS_WAY)
    revealed = context.results.get(REVEALED_HAND_CARDS)
    if wanted is None or not color or revealed is None:
        return False
    # Whose cards these are, for the colour read: CR 105 is answered for an
    # object outside the battlefield by ``object_colors.card_colors``, which
    # needs the owner because a board-wide static can recolour a hand
    # (Celestial Dawn). The seat is the one the reveal named — the same
    # ``context.target`` that handler read — and never the printed noun
    # phrase, which restates it.
    owner = context.target if context.target is not None else context.caster
    described = {"color_filter": str(color)}
    count = sum(
        1 for card in revealed
        if _card_matches_filter(card, described, game=game, owner=owner)
    )
    return _compare_count(count, str(payload.get("op", "eq")), int(wanted))


@condition("revealed_card_has_chosen_name")
def _condition_revealed_card_has_chosen_name(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "**If that card has the chosen name**, this artifact deals 2 damage
    # to any target." (Cursed Scroll.) The two records an earlier step of
    # this same resolution wrote: the name a seat chose, and the one card a
    # random reveal turned up.
    #
    # Compared on printed names through the same ``name_key`` the milled
    # question below uses, so "Æther Vial" and "Aether Vial" are one card
    # in both places. A card in a hand is not a permanent and cannot be
    # copying anything (CR 707.2), so the printed name is the only name it
    # has. An empty name matches nothing and an empty hand revealed
    # nothing, and both are False rather than an error.
    from ..search_filters import name_key

    named = str(context.results.get("chosen_card_name") or "").strip()
    revealed = context.results.get("revealed_card")
    if not named or revealed is None:
        return False
    return name_key(revealed.name) == name_key(named)


@condition("chosen_name_milled_this_way")
def _condition_chosen_name_milled_this_way(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "**If a card with the chosen name was milled this way**, you draw a
    # card." (Foreshadow.) Two records, both written by earlier steps of
    # this same resolution — the name a seat chose, and the cards a mill
    # actually put into a graveyard. Never a read of the pile: a graveyard
    # holds whatever else has gone there, and the words say "this way".
    #
    # Compared against each card's own printed name, because nothing in a
    # library is a permanent and nothing there can be copying anything
    # (CR 707.2). An empty name matches nothing, which is the honest
    # answer for a seat that named nothing.
    from ..search_filters import name_key

    named = str(context.results.get("chosen_card_name") or "").strip()
    if not named:
        return False
    wanted = name_key(named)
    return any(
        name_key(card.name) == wanted
        for card in (context.results.get(MILLED_THIS_WAY) or ())
    )


@condition("milled_this_way")
def _condition_milled_this_way(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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
    cards = context.results.get(MILLED_THIS_WAY) or []
    wanted = tuple(payload.get("card_types") or ())
    return any(
        any(name in card.type_line.lower() for name in wanted)
        for card in cards
    )


@condition("target_is_color")
def _condition_target_is_color(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("target_shares_most_common_color")
def _condition_target_shares_most_common_color(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Destroy target creature **if it shares a color with the most common
    # color among all permanents** or a color tied for most common."
    # (Tsabo's Assassin, Barrin's Unmaking.) CR 608.2c again: the census is
    # taken while the instruction is followed, so a permanent that entered
    # or was recoloured in response is counted, and the target itself is one
    # of "all permanents" — a lone coloured target is always most common.
    #
    # The picker offers every permanent the noun phrase admits: the clause
    # is a condition on the *effect*, not a targeting restriction, so a
    # target that fails it is a legal target the spell simply does nothing
    # to (CR 608.2b reads the printed target phrase, which says no colour).
    #
    # The same resolver the colour clause above uses, for its reason: the
    # branch and the effect beside it must mean one permanent. A target
    # that is gone shares a colour with nothing.
    from ..color_census import shares_most_common_color
    from ._common import resolve_target_permanent

    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: True,
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    return shares_most_common_color(game, target)


@condition("target_shares_color_with_chosen")
def _condition_target_shares_color_with_chosen(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Prevent all combat damage target creature would deal this turn **if
    # it shares a color with that permanent**." (Guard Dogs.) CR 105.2's
    # relation between the effect's target and the permanent a step earlier
    # in this resolution chose — both read now, while the instruction is
    # followed (CR 608.2h), and both through layer 5: a target a response
    # recoloured is judged on the colour it has, not the one it was aimed
    # at for.
    #
    # ``object_colors.share_a_color`` is the one reading of the relation:
    # a colourless object on either side shares nothing, and so does a
    # choice that was never made or whose permanent has gone.
    from ..object_colors import share_a_color
    from ._common import resolve_target_permanent

    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: True,
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    recorded = context.results.get(str(payload.get("permanent_from") or ""))
    chosen = (
        game.permanent_by_id(recorded) if isinstance(recorded, int) else None
    )
    if target is None or chosen is None:
        return False
    return share_a_color(
        game._effective_colors(target), game._effective_colors(chosen)
    )


@condition("target_shares_color_with_matching")
def _condition_target_shares_color_with_matching(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Counter target spell **if it shares a color with a creature you
    # control**." (Jaded Response.) CR 105.2's relation between the spell
    # this effect targets and every permanent the printed phrase admits —
    # both read now, while the instruction is followed (CR 608.2c): a
    # creature that entered, left or was recoloured in response is judged
    # as it stands, and so is a spell a Lace or a Vodalian Mystic changed.
    #
    # The picker offers every spell: the clause is a condition on the
    # *effect*, not a targeting restriction ("target spell" is the whole of
    # the printed target phrase, CR 608.2b), so a spell that fails it is a
    # legal target the counter does nothing to.
    #
    # The spell's colours through ``_stack_item_colors`` — the one reader
    # of what colour a stack object is — and each permanent's through layer
    # 5. ``share_a_color`` is the one reading of the relation: a colourless
    # object on either side shares nothing (CR 105.2c), and a spell that
    # has left the stack answers no, like every clause beside this one.
    from ..object_colors import share_a_color
    from ..subject_filters import subject_matches

    chosen = context.stack_target
    if (
        payload.get("target") != "spell"
        or chosen is None
        or chosen not in game.stack
        or context.caster not in game.players
    ):
        return False
    colors = game._stack_item_colors(chosen)
    if not colors:
        return False
    described = dict(payload.get("filter") or {})
    observer = game.players.index(context.caster)
    return any(
        share_a_color(colors, game._effective_colors(permanent))
        for permanent in game.all_permanents()
        if subject_matches(
            game, permanent, described, observer=observer,
            source=context.source_permanent,
        )
    )


@condition("targets_differ_in_color")
def _condition_targets_differ_in_color(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…unless **either one is a color the other isn't**." (Dead Ringers.)
    # CR 105.2 over the two targets' colour *sets*, read now, while the
    # instruction is followed (CR 608.2h) and through layer 5: equal sets
    # are the only way not to differ, so two colourless creatures do not
    # (CR 105.2c — the card's ruling says so) and a white-blue creature
    # beside a blue one does.
    #
    # **A pair this cannot read differs.** CR 608.2b: "If part of the
    # effect requires information about an illegal target, it fails to
    # determine any such information" — so with one target gone, or made
    # illegal in response (protection from black is the ordinary way), the
    # comparison has no answer, and the sentence that needs one does not
    # happen. The clause is printed behind "unless", where "they differ" is
    # the answer under which nothing is destroyed — the survivor is not
    # destroyed alone on the strength of a comparison nobody could make.
    from ._common import resolve_target_slots

    first, second = resolve_target_slots(game, context, 2)
    if (
        first is None or second is None or first is second
        or not game.is_on_battlefield(first)
        or not game.is_on_battlefield(second)
        or not game.resolving_targets_all_legal()
    ):
        return True
    return frozenset(game._effective_colors(first)) != frozenset(
        game._effective_colors(second)
    )


@condition("color_is_most_common")
def _condition_color_is_most_common(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…white is the most common color among all permanents or is tied for
    # most common." The Djinns print it on a static, where
    # ``static_bonuses.conditional_static_holds`` answers it; this is the
    # same payload reaching an intervening-if or a sentence-level "if", and
    # the same census answers it so the two cannot disagree about a tie.
    from ..color_census import color_is_most_common

    return color_is_most_common(
        game, str(payload.get("color") or ""),
        tied=bool(payload.get("tied", True)),
    )


@condition("target_is_type")
def _condition_target_is_type(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Untap target Griffin. **If it's a creature**, it gets +1/+1 until
    # end of turn." (Griffin Canyon.) The type twin of the colour clause
    # above, asked of the same object through the same resolver so the
    # branch and the effect beside it cannot disagree about which permanent
    # the pronoun meant.
    #
    # CR 613 answers it, not the printed type line: a Griffin land animated
    # into a creature is one, and a creature that has stopped being one is
    # not — which is the whole reason the card prints the question at all,
    # since "target Griffin" is a phrase a non-creature can satisfy.
    #
    # CR 608.2c: read while the instruction is followed, not when the target
    # was chosen. An object that is gone answers no to both readings — the
    # same call the two clauses either side of this one make.
    from ._common import resolve_target_permanent

    target = resolve_target_permanent(
        game, context,
        predicate=lambda perm: True,
        fallback_players=(),
        fallback_on_invalid_choice=False,
    )
    if target is None:
        return False
    wanted = [str(t) for t in (payload.get("card_types") or ())]
    if not wanted:
        return False
    matches = [t for t in wanted if target.has_type(t)]
    # "artifact creature" is one object that is both; "creature or land" is
    # a union. The same distinction `type_match` draws everywhere else.
    if payload.get("type_match") == "all":
        answer = len(matches) == len(wanted)
    else:
        answer = bool(matches)
    return (not answer) if payload.get("negated") else answer


@condition("target_has_keyword")
def _condition_target_has_keyword(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("target_card_shares_type_with_cost_card")
def _condition_target_card_shares_type_with_cost_card(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "Return target card from your graveyard to your hand **if it shares
    # a card type with the card exiled this way**." (Holistic Wisdom.) Two
    # cards and no permanent: the target is the graveyard slot the
    # activation announced (the handler beside this reads the same one),
    # and the other is what the ability's own cost ate, off the payment
    # path's record (CR 608.2h). Compared by **printed** card types
    # (CR 205.2a; a card in a zone has no computed ones, CR 613.1), any one
    # in common answering — an Artifact Creature shares with an artifact
    # and with a creature both.
    #
    # No target or no record answers False: there is then nothing "it"
    # names, and the return this guards must not happen.
    from ..layer_bridge import printed_shape

    slot = context.target_permanent_index
    pile = context.caster.graveyard
    if not isinstance(slot, int) or isinstance(slot, bool) or not 0 <= slot < len(pile):
        return False
    recorded = (context.choices or {}).get(str(payload.get("channel")))
    if recorded is None:
        return False
    paid = recorded if isinstance(recorded, (list, tuple)) else (recorded,)
    target_types = printed_shape(pile[slot])[0]
    return any(
        target_types & printed_shape(getattr(entry, "card", entry))[0]
        for entry in paid
    )


@condition("cost_object_was")
def _condition_cost_object_was(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("discarded_this_way")
def _condition_discarded_this_way(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "If you discard a creature card this way" (Aether Rift). The record
    # the discard in front of it wrote, not the graveyard: the pile also
    # holds cards this effect never touched. The printed type *line*, as
    # the two readers beside this one ask it — CR 608.2h's last-known
    # information about a card that was in a hand a moment ago.
    cards = context.results.get(DISCARDED_THIS_WAY) or []
    wanted = tuple(payload.get("card_types") or ())
    match = all if payload.get("type_match") == "all" else any
    return any(
        match(name in card.type_line.lower() for name in wanted)
        for card in cards
    )


@condition("discarded_card_was")
def _condition_discarded_card_was(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("destroyed_this_way")
def _condition_destroyed_this_way(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition(DAMAGED_BY_SOURCE_DIED)
def _condition_damaged_by_source_died(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…if a creature dealt damage by this creature this turn died"
    # (Krovikan Vampire). The ledger the source carries, not the game-wide
    # death counter beside it: the counter cannot say *which* creature died
    # or who damaged it, and reading it here would fire this trigger on
    # every end step of every game with a trade in it.
    from ..damage_deaths import creatures_it_damaged_that_died

    return bool(creatures_it_damaged_that_died(context.source_permanent))


@condition("died_this_turn")
def _condition_died_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0


@condition("had_plus1_counter")
def _condition_had_plus1_counter(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "if it had a +1/+1 counter on it" (Basri's Lieutenant). The creature
    # is already in the graveyard by the time this resolves, so the only
    # legal source is the last-known information the fire site recorded
    # (CR 603.10). No record means nothing observed the death — False,
    # rather than a guess at a board that no longer holds the answer.
    return bool((context.trigger_context or {}).get("had_plus1_counter"))


@condition("had_named_counter")
def _condition_had_named_counter(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…exile it **if it had a death counter on it**" (Bogardan Phoenix).
    # The named-counter twin of the clause above, and last-known information
    # for its reason: the Phoenix is in a graveyard by the time this
    # resolves, and a graveyard card carries no counters. No record means
    # nothing observed the death — False, rather than a guess at a board
    # that no longer holds the answer, which for this card is the reading
    # that brings it back rather than the one that exiles it forever.
    frozen = (context.trigger_context or {}).get("dead_counters") or {}
    return int(frozen.get(str(payload.get("counter", "")), 0) or 0) > 0


@condition("source_exiled")
def _condition_source_exiled(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…**if that card is exiled**, remove a delay counter from it."
    # (Ertai's Meddling.) The zone half of the clause below on its own,
    # asked of the register for that clause's reason: an ability on the
    # stack is independent of its source (CR 608.2), so between the upkeep
    # that fired it and this resolution anything at all could have taken the
    # card out of exile.
    #
    # And the ability outlives the card here, which is what makes the gate
    # the whole card: it has no stated duration (CR 603.7b), so it goes on
    # triggering after the card has left — and a resolution that skipped
    # this would put a card that is no longer in exile onto the stack every
    # upkeep for the rest of the game.
    record = record_in_context(context)
    return record is not None and is_live(game, record)


@condition("source_exiled_with_counter")
def _condition_source_exiled_with_counter(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("source_counter_count")
def _condition_source_counter_count(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("attached_counter_count")
def _condition_attached_counter_count(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "if that creature has three or more +1/+0 counters on it" (Consuming
    # Ferocity). The permanent the Aura is attached to, not the Aura — the
    # clause one branch up asks the source and this one asks its host, and
    # an enchantment counting its own +1/+0 counters is always counting
    # zero.
    host = attached_host(game, context.source_permanent)
    if host is None:
        # Nothing is attached, so the clause is about no object at all —
        # the same False the source branch above answers with when its own
        # holder has gone.
        return False
    held = counters_on(host, str(payload.get("counter", "")))
    wanted = int(payload.get("count", 0))
    if str(payload.get("comparison", "exactly")) == "at_least":
        return held >= wanted
    return held == wanted


@condition("source_ability_activations")
def _condition_source_ability_activations(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("mana_added_with_this_ability")
def _condition_mana_added_with_this_ability(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…**if you haven't added mana with this ability this turn**, …"
    # (Carpet of Flowers.) CR 603.4 asks this twice — once as the trigger
    # would fire and once as it resolves — and the note it reads is written
    # by ``add_mana_from_text`` at the one moment mana is actually added, so
    # the two checks read the same fact and a trigger that added mana in the
    # precombat main phase does not fire again in the postcombat one.
    #
    # A source that has left the battlefield (CR 400.7) has no note, and the
    # negated clause therefore reads **true** — which is the card: an
    # enchantment that is gone adds nothing, and the ability is removed from
    # the stack for having no source long before this matters.
    from ..mana_ability_records import added_mana_this_turn

    added = added_mana_this_turn(
        game, context.source_permanent, str(payload.get("record", ""))
    )
    return (not added) if payload.get("negated", True) else added


@condition("creatures_attacked_this_turn")
def _condition_creatures_attacked_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…**if no creatures attacked this turn**" (Keldon Twilight). CR
    # 603.4's intervening-if, read off the per-seat record the
    # declare-attackers step stamps (``PlayerState.attacked_this_turn``,
    # CR 508.1) and never off the board: an attacker that has died, left
    # or untapped since is still a creature that attacked this turn, and
    # reading the creatures would forget exactly that one.
    #
    # Every seat is asked, because the sentence names none — in a
    # multiplayer game a creature another player attacked *with* during
    # this turn is still one that attacked (CR 508.1 makes only the active
    # player an attacker, so in practice this is that seat's stamp; asking
    # all of them is what keeps it true if that ever stops being so).
    attacked = any(player.attacked_this_turn for player in game.players)
    return (not attacked) if payload.get("negated") else attacked


@condition("returned_to_hand_this_turn")
def _condition_returned_to_hand_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "a permanent was put into your hand from the battlefield this turn"
    # (Barrin). "Your" is the ability's controller; the bounce paths feed
    # the per-seat counter.
    seat = game.players.index(context.caster)
    return int(game.permanents_to_hand_this_turn.get(seat, 0)) > 0


@condition("attacked_or_blocked_this_combat")
def _condition_attacked_or_blocked_this_combat(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("came_under_your_control_this_turn")
def _condition_came_under_your_control_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…if this creature didn't attack **or come under your control this
    # turn**" (Mad Dog). CR 302.6's own record, read through the predicate
    # summoning sickness asks: a permanent not controlled continuously
    # since its controller's turn began came under that control during it —
    # by entering or by changing hands, which Erg Raiders' ruling says are
    # both "coming under your control". The lowering admits the clause only
    # under a trigger of the controller's own turn, which is when that
    # reading holds.
    #
    # A source that has left answers False for the *positive* clause — the
    # direction CR 603.4 takes for an intervening-if it cannot check — so
    # the negated one is what answers True and lets a "sacrifice it" find
    # nothing to sacrifice.
    source = context.source_permanent
    came = (
        source is not None
        and game.is_on_battlefield(source)
        and not game._controlled_since_turn_start(source)
    )
    return (not came) if payload.get("negated") else came


@condition("came_under_your_control_since_your_last_upkeep")
def _condition_came_under_your_control_since_your_last_upkeep(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # CR 702.30a's intervening-if — echo's whole condition, and the reason
    # an echo creature pays once and never again. Read off the record the
    # upkeep step writes, for the block clause below's reason: the moment it
    # asks about may have been an opponent's turn ago and nothing on the
    # board records when a permanent changed hands.
    #
    # "Your" is the ability's controller (CR 109.5), which is also the seat
    # the record names — a permanent under a thief's control has seen the
    # thief's upkeeps, and its old controller's window holds nothing about
    # it. A missing source answers False, the direction that stops the
    # ability rather than the one that sacrifices on a guess.
    from ..turn_state import came_under_control_since_seats_last_upkeep

    source = context.source_permanent
    if source is None or context.caster not in game.players:
        return False
    return came_under_control_since_seats_last_upkeep(
        game, source, game.players.index(context.caster)
    )


@condition("in_a_block_since_your_last_upkeep")
def _condition_in_a_block_since_your_last_upkeep(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("dealt_damage_this_turn")
def _condition_dealt_damage_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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


@condition("seat_cast_spell_this_turn")
def _condition_seat_cast_spell_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "At the beginning of each player's end step, **if that player didn't
    # cast a spell this turn**, this enchantment deals 2 damage to that
    # player." (Impatience.) CR 603.4's intervening-if, read off the
    # per-seat per-turn record the casting path writes
    # (`PlayerState.spells_cast_this_turn`) and the turn boundary clears —
    # never off the board, because a resolved spell has left the stack and a
    # permanent that entered from a cast is indistinguishable from one that
    # was reanimated.
    #
    # Whose record is payload. "That player" is the seat the firing event
    # named, frozen into the trigger's context by the end step (CR 603.10)
    # under the same key the damage's own recipient reads — so the condition
    # and the effect can never be about two different players, which on this
    # card is the whole of what it does.
    seats: list[int] = []
    who = payload.get("who")
    if who == "that_player":
        frozen = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(frozen, int):
            # The words name a seat nothing recorded. Reported unmet rather
            # than guessed, exactly as the ledger clause below does: the
            # lowering is what keeps this clause off an event that freezes
            # no seat, and answering either way here would make Impatience
            # fire on every end step or on none.
            return False
        seats = [frozen]
    elif who == "an_opponent":
        if context.caster not in game.players:
            return False
        seats = list(game.opponents_of(game.players.index(context.caster)))
    else:
        if context.caster not in game.players:
            return False
        seats = [game.players.index(context.caster)]
    if not seats:
        return False
    cast = any(
        bool(game.players[seat].spells_cast_this_turn)
        for seat in seats
        if 0 <= seat < len(game.players)
    )
    return (not cast) if payload.get("negated") else cast


@condition("all_revealed_top_cards_are")
def _condition_all_revealed_top_cards_are(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…**if all cards revealed this way are creature cards**…" (Game
    # Preserve.) The per-seat map the reveal in front of this wrote
    # (CR 608.2h), never a re-read of the libraries: CR 701.20a moved
    # nothing, so a second look would find the same cards only until
    # something else touched a deck — and would say nothing about which of
    # them this sentence is about.
    #
    # **An empty record is False**, which is ``all_of``'s rule above and
    # its reason: a universal over nothing is vacuously true, and answering
    # true here would run the effect behind it over an empty set. It is
    # also the honest reading of the card — with every library empty
    # nothing was revealed, so there is nothing to put onto the
    # battlefield.
    from ..graveyard_order import is_printed_type

    revealed = context.results.get(REVEALED_TOP_CARDS_BY_SEAT) or {}
    wanted = str(payload.get("card_type", "creature"))
    return bool(revealed) and all(
        is_printed_type(card, wanted) for card in revealed.values()
    )


@condition("seat_played_land_this_turn")
def _condition_seat_played_land_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "At the beginning of your end step, **if you didn't play a land this
    # turn**, you may draw a card." (Mercadian Atlas.) CR 603.4's
    # intervening-if, read off the per-seat per-turn tally the land-play
    # path writes (``Game.lands_played_this_turn``, bumped in
    # ``mixins/stack/resolution.py`` and cleared by ``turn_management``) —
    # never off the board, because by the end step a land played this turn
    # is an ordinary permanent and says nothing about how it got there.
    #
    # Whose tally is payload, exactly as the cast record above: "you" is the
    # ability's controller (CR 109.5, ``context.caster`` for a triggered
    # ability as much as for a spell) and "that player" the seat the firing
    # event named. A seat the words name and nothing recorded answers False
    # rather than guessing, which is that clause's rule and its reason.
    who = payload.get("who")
    if who == "that_player":
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int):
            return False
    elif who == "an_opponent":
        if context.caster not in game.players:
            return False
        seats = list(game.opponents_of(game.players.index(context.caster)))
        played = any(
            int(game.lands_played_this_turn.get(other, 0) or 0) > 0
            for other in seats
        )
        return (not played) if payload.get("negated") else played
    else:
        if context.caster not in game.players:
            return False
        seat = game.players.index(context.caster)
    if not (0 <= seat < len(game.players)):
        return False
    played = int(game.lands_played_this_turn.get(seat, 0) or 0) > 0
    return (not played) if payload.get("negated") else played


@condition("seat_dealt_damage_this_turn")
def _condition_seat_dealt_damage_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "…unless **one of their opponents was dealt damage this turn**"
    # (Antagonism). The turn's damage ledger, never a read of a life total:
    # a life total is the turn's *net*, so a player dealt 4 who then gained
    # 4 has been dealt damage and has lost no life, and the card asks about
    # the damage.
    #
    # Whose opponents is payload. "Their" is the seat the firing event was
    # about — frozen into the trigger's context (CR 603.10) by the end step,
    # under the same key the damage recipient beside it reads, so the
    # condition and the effect can never be about two different players.
    from ..damage_ledger import damage_dealt_to_seat

    if context.caster not in game.players:
        return False
    seat = game.players.index(context.caster)
    if payload.get("opponents_of") == "that_player":
        frozen = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(frozen, int):
            # The words name a seat nothing recorded. Answering False would
            # let Antagonism fire on every end step; answering True would
            # silence it for ever. Refusing to answer is neither: the
            # condition is reported as unmet, and the lowering is what keeps
            # the clause off an event that freezes no seat.
            return False
        seat = frozen
    return any(
        damage_dealt_to_seat(game, opponent) > 0
        for opponent in game.opponents_of(seat)
    )


@condition("your_turn")
def _condition_your_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
    # "At the beginning of each end step, **if it's an opponent's turn**, …"
    # (Discordant Spirit.) Whose turn it is, asked as a CR 603.4
    # intervening-if. The lowering has produced this payload since Vibrating
    # Sphere and only ``static_bonuses.conditional_static_holds`` answered
    # it — so a *trigger* gated on the clause would have reached this
    # function, fallen through to the ``return False`` below and never
    # fired. One lowered condition, two front ends, one of them silent.
    #
    # The seat is the ability's controller (CR 109.5), which is
    # ``context.caster`` for a triggered ability as much as for a spell, and
    # the comparison is the one that other reader makes.
    if payload.get("whose") == "event_subject_player":
        # "…if it's not **that player's** turn" (Price of Glory). The seat
        # the fire site froze. No record is a clause about nobody, and
        # answers False either way round — the direction that stops the
        # ability rather than the one that destroys on a guess.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int):
            return False
        theirs = game.active_player_index == seat
        return (not theirs) if payload.get("negated") else theirs
    if context.caster not in game.players:
        return False
    mine = game.active_player_index == game.players.index(context.caster)
    return (not mine) if payload.get("negated") else mine


@condition("life_gained_this_turn")
def _condition_life_gained_this_turn(game: Game, context: OracleExecutionContext, payload: dict) -> bool:
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
