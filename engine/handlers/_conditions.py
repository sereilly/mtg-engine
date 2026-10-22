"""What a condition payload means when it asks about the game **now**.

``control_flow.evaluate_condition`` is the one entry point every condition is
asked through — an intervening-if (CR 603.4), a sentence's own "if", a static's
condition, an activation restriction — and this is the largest of the three
families it hands a kind to: a board count, a zone's height, a life total, a
permanent's characteristics or state, whose turn it is. The handler twin of
``engine/grammar/lowering/conditions.py``, which produces exactly these kinds
and draws the line in its own docstring: what is left there "is answered by
looking at the game *now*". A condition answered by a record of something
already done is ``_record_conditions``'; a colour is ``_color_conditions``'.

Split out of ``control_flow.py`` at the 2,000-line cap's split round, where
``evaluate_condition`` was one 1,847-line chain of ``if kind == …`` branches.
Every branch tests ``kind`` alone and returns, and no kind is tested twice, so
the chain divides into families without any branch answering differently: the
branches moved verbatim, and :func:`evaluate_state_condition` answers
``NotImplemented`` for a kind that is not its own.

The readers those branches share came with them, and three are read outside
the conditions as well, because an effect one clause later asks the question
its condition did: :func:`most_life_seat` and :func:`most_controlling_seat`
name the seat that gains control (Wild Dogs, Wild Mammoth —
``control_changes``), :func:`most_permanents_seat` the seat Damping Engine
stops (``cast_bans``). :func:`_compare_count` is the counted comparison a
static bonus makes too (``static_bonuses``), and the record half's two counted
conditions read it from here. It registers no handler, hence the underscore
(``_common``'s convention).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..faces import has_name
from ..exiled_records import is_live, record_in_context, source_object
from ..named_counters import counters_on
from ._filters import permanent_matches_filter, permanent_state_holds
from ._targets import attached_host, defending_player_seat

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


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


def evaluate_state_condition(
    game: Game, context: OracleExecutionContext, payload: dict,
    kind: str | None,
) -> object:
    """A condition answered by looking at the game **now** — a board count, a
    zone's height, a life total, a permanent's characteristics or state, whose
    turn it is — or ``NotImplemented`` when *kind* is not one of them.

    Asked by ``control_flow.evaluate_condition``, which has already read
    *kind* off *payload* and answered the two joiners (``all_of``,
    ``any_of``) itself, since each asks it again of every part.
    """

    if kind == "same_named_object":
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
            from ._targets import resolve_target_permanent

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
        if payload.get("same_name_as") == "record":
            # "…put that card onto the battlefield if **it has the same name
            # as a permanent**." (Retraced Image.) "It" is the one card the
            # hand reveal in front of it recorded; "a permanent" is any
            # permanent on the battlefield, either side's, tokens included
            # unless the card says "nontoken". CR 201.2a over CR 709.4a: a
            # split card has both halves' names, so either may be matched —
            # ``has_name`` asks both; ``effective_card`` on the permanent's
            # side because a copy's name is the copied one (CR 707.2).
            recorded = context.results.get(str(payload.get("record"))) or ()
            if not isinstance(recorded, (list, tuple)) or len(recorded) != 1:
                return False
            (card,) = recorded
            nontoken = bool(payload.get("nontoken"))
            return any(
                has_name(card, permanent.effective_card.name)
                and not (nontoken and permanent.metadata.get("is_token"))
                for permanent in game.all_permanents()
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

    if kind == "self_only_card_of_type_in_graveyard":
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

    if kind == "controls":
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

    # "if two or more of those creatures are attacking you and/or planeswalkers
    # you control" (Mangara). The number the *declaration* had, frozen by the
    # fire site: recounting here would ask about a combat that may have changed.
    if kind == "attackers_aimed_at_you":
        aimed = int((context.trigger_context or {}).get("attackers_aimed", 0))
        return aimed >= int(payload.get("count", 0))

    if kind == "subject_characteristic_is":
        # "If this creature's power is 1 or more" (Lesser Werewolf), "If target
        # creature has toughness 5 or greater" (Blood Lust). CR 613's computed
        # characteristic, read through the layer accessors rather than off the
        # printed card: Lesser Werewolf's gate exists because the ability
        # shrinks its own source, and Blood Lust must see a creature another
        # spell already pumped. Nothing to ask about answers False — a source
        # that has left (CR 608.2b) and a target that is no longer legal both.
        from ._filters import _comparison_holds
        from ._targets import resolve_target_permanent

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
            from ._amounts import count_from_payload

            bound = count_from_payload(game, context, counted)
        return _comparison_holds(
            {"op": payload.get("op", "eq"), "value": bound}, value,
        )

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

    if kind == "source_is_type":
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

    if kind == "source_on_battlefield":
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

    if kind == "zone_card_count":
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

    if kind == "player_life":
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

    if kind in ("cards_in_zones", "distinct_among"):
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
        from ._amounts import count_from_payload

        return _compare_count(
            count_from_payload(game, context, dict(payload.get("count") or {})),
            str(payload.get("op", "")),
            payload.get("value"),
        )

    if kind == "life_total_difference":
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

    if kind == "target_has_keyword":
        # "If it doesn't have rampage" (Rapid Fire). Asked of the same target
        # the grant beside it resolves against, and through the same resolver,
        # so the branch and the effect cannot disagree about which creature the
        # pronoun meant. Layer 6 is what answers (CR 613.1f): a creature *given*
        # rampage has it, exactly as a printed one does.
        from ._targets import resolve_target_permanent

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

    if kind == "source_exiled":
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

    if kind == "attached_counter_count":
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

    if kind == "your_turn":
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

    # Not a kind of this family: ``control_flow.evaluate_condition`` asks the
    # next one, and answers False when none of them claims it.
    return NotImplemented
