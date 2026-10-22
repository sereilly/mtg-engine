"""A draw replaced (CR 121.6, CR 614.11), and the queue of draws a suspended
one holds.

``draw`` is an *interactive* kind: most of its interceptors offer a
``ReplacementChoice`` and a registered resolver finishes the draw once the
chooser answers, so a draw that waits on an answer parks the draws behind it
(``QUEUED_EXCLUDES``, ``draws_behind``) and each resolver here hands them back.
The replacements: two cards for one (a draw past the first in each draw step),
a card from outside the game (Ring of Ma'rûf), an armed one-shot run in place
of the draw, the draw given to another player, a counter put on a permanent
instead, the draw skipped, a discard (or a mill) in its place (Chains of
Mephistopheles), a card returned from a graveyard instead — and Lich's life
gain drawn as cards, a ``life_gain`` replacement whose result is draws that go
back through all of these.

Split out of ``replacements.py`` at the 2,000-line cap's split round. A draw
replaced by a look at, or a reveal of, the library's top is
``revealed_draws.py``'s.
"""

from __future__ import annotations

import re

from ..replacement_choices import (
    ReplacementChoice,
    offer_replacement_choice,
    replacement_choice,
)
from .registry import (DRAW_ARMED_REPLACEMENT, DRAW_BECOMES_COUNTER,
                       DRAW_DISCARD_INSTEAD, DRAW_DOUBLED, DRAW_FROM_OUTSIDE,
                       DRAW_GIVEN_TO_ANOTHER, DRAW_MAY_BE_SKIPPED,
                       DRAW_RETURNS_FROM_GRAVEYARD, LIFE_GAIN_TO_DRAW,
                       ReplacementOutcome, replacement_effect)


# The oracle phrases the interceptors below self-select on are named constants
# rather than inline literals because ``lines.py``'s claim reader needs the
# *exact* string (see its docstring).
LIFE_GAIN_TO_DRAW_TEXT = "if you would gain life, draw that many cards instead"


def _applies_life_gain_to_draw(game, payload: dict) -> bool:
    return game._player_controls_text(payload["player"], LIFE_GAIN_TO_DRAW_TEXT)


@replacement_effect("life_gain", LIFE_GAIN_TO_DRAW, applies=_applies_life_gain_to_draw)
def _draw_instead_of_life_gain(game, payload: dict) -> ReplacementOutcome | None:
    """Lich: "If you would gain life, draw that many cards instead."

    The draw this creates is a draw like any other, so it goes back through the
    draw replacements (CR 616.2: an effect can become applicable *because*
    another replacement modified the event). This pairing is the rule's own
    worked example, and taking cards off the library directly would silently
    skip a Ring of Ma'rûf or an Aladdin's Lamp the player had armed.
    """
    player = payload["player"]
    amount = payload["amount"]
    drawn = game._draw_with_replacements(player, amount)
    source = f" from {payload['source_name']}" if payload.get("source_name") else ""
    game.log.append(
        f"{player.name} would gain {amount} life{source}; drew {drawn} card(s) instead (Lich)"
    )
    return ReplacementOutcome(replaced=True)


#: The key a suspended draw's prompt carries for **the draws queued behind
#: it**: the sources those draws are already excluded from (CR 614.5).
#:
#: Not the prompt's own ``exclude_sources``. That one is about the draw the
#: prompt was asked of and includes the asker (a declined Pursuit of
#: Knowledge is not offered the same draw twice); the draws *behind* are
#: later draws of the same event, which the asker has not seen and whatever
#: modified the whole event has (the doubler that made them).
QUEUED_EXCLUDES = "queued_exclude_sources"


def queued_excludes(payload: dict) -> tuple:
    """What the draws behind the first of *payload*'s are excluded from: what
    the event itself has been excluded from so far, and nothing the
    replacement taking that first draw adds for it."""
    return tuple(payload.get("exclude_sources") or ())


def draws_behind(game, player, count: int, excludes=()) -> int:
    """Make the draws queued behind one a replacement took (CR 121.2).

    One spelling for every tail that makes them, because what they carry is
    the same wherever they are made from: they are draws of the *same event*
    as the one in front, so the replacements that event has already been
    through stay excluded (CR 614.5) — and through the seam, which parks
    them while the draw in front is still waiting on its player
    (``Game._draw_prompt_open``).
    """
    if count <= 0:
        return 0
    return game._draw_with_replacements(
        player, int(count), exclude_sources=tuple(excludes)
    )
DOUBLE_DRAW_TEXT = (
    "if you would draw a card except the first one you draw in each of your "
    "draw steps, draw two cards instead"
)


def _doubled_draw_count(game, payload: dict) -> int:
    """How many cards this draw event should take, once the doublers have had
    it — the same number back when none apply.

    Two things the arithmetic has to keep apart. CR 121.2 makes an event of
    ``count`` draws *that many individual draws*, and the rider exempts **one
    draw**, not one event: a draw step with a Howling Mine out draws 1 + 1, and
    only the first of those two is the one you drew first in your draw step. And
    CR 614.5 stops a doubler applying to the draws it created, so each affected
    draw becomes two rather than dividing forever.

    Copies multiply, for the reason ``_damage_multiplier`` records: an effect
    applies once per event, so counting the sources is the only way a second
    doubler is not silently dropped. Teferi's Ageless Insight is legendary and
    Alhammarret's Archive is not in this pool, so today the count is one — the
    legend rule is round 49's open block, and "there can only be one" is exactly
    the kind of claim about the pool that expires without anyone editing it.
    """
    count = int(payload.get("count", 0))
    exempt = 1 if payload.get("turn_based") else 0
    affected = max(0, count - exempt)
    return exempt + affected * (2 ** len(_draw_doublers(game, payload)))


def _draw_doublers(game, payload: dict) -> list:
    """The doublers that have not had this event yet (CR 614.5).

    "A replacement effect … gets only one opportunity to affect an event **or
    any modified events resulting from that event**." The two draws a doubler
    makes of one are that event modified, so it is excluded from them by the
    key every other draw replacement here reads — and the exclusion has to
    ride ``exclude_sources`` rather than rest on "an effect applies once per
    event", because the draws do not stay one event: a replacement that takes
    the first of them hands the rest back to the seam as a fresh one.
    """
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.controlled_by(payload["player"])
        if perm.permanent_id not in exclude
        and DOUBLE_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
    ]


def _applies_double_draw(game, payload: dict) -> bool:
    return _doubled_draw_count(game, payload) > int(payload.get("count", 0))


@replacement_effect("draw", DRAW_DOUBLED, applies=_applies_double_draw)
def _draw_two_cards_instead(game, payload: dict) -> ReplacementOutcome | None:
    """Teferi's Ageless Insight: "If you would draw a card except the first one
    you draw in each of your draw steps, draw two cards instead."

    A *modifying* replacement, like Conclave Mentor's extra counter and unlike
    the two below it: the event still happens, with a bigger number, so nothing
    is consumed and the draws stay ordinary draws — a Ring of Ma'rûf or an
    Aladdin's Lamp armed alongside still gets one of them (CR 616.1f re-asks
    against the raised count).

    **The doubler is then excluded from every draw of the event it made**
    (CR 614.5). It used not to be: with an Abundance beside it, the draw
    Abundance took left one "queued behind", the seam met that one as a new
    event, doubled it, Abundance took the first of *those* — and one card
    drawn was a library revealed to the bottom and a ``RecursionError``.
    """
    player = payload["player"]
    before = int(payload["count"])
    doublers = _draw_doublers(game, payload)
    payload["count"] = _doubled_draw_count(game, payload)
    payload["exclude_sources"] = tuple(payload.get("exclude_sources") or ()) + tuple(
        perm.permanent_id for perm in doublers
    )
    game.log.append(
        f"{player.name} draws {payload['count']} instead of {before} "
        "(Teferi's Ageless Insight)"
    )
    return ReplacementOutcome()


def _applies_outside_game_draw(game, payload: dict) -> bool:
    return game.players.index(payload["player"]) in game.outside_game_draw_replacements


@replacement_effect("draw", DRAW_FROM_OUTSIDE, applies=_applies_outside_game_draw)
def _draw_from_outside_the_game(game, payload: dict) -> ReplacementOutcome | None:
    """Ring of Ma'rûf: the next draw is replaced by putting a card you own from
    outside the game into your hand.

    Nothing is drawn from the library, so this reports 0 cards drawn and a
    "whenever you draw a card" effect correctly sees no draw. With no eligible
    card there is nothing to take and the replacement is spent anyway
    (CR 614.1). CR 407.3 keeps ante cards out of a game not played for ante.
    """
    player = payload["player"]
    player_index = game.players.index(player)
    game.outside_game_draw_replacements.discard(player_index)
    available = game._outside_game_choices(player_index)
    remaining = payload["count"] - 1
    if not available:
        game.log.append(
            f"{player.name} has no cards outside the game to take (Ring of Ma'rûf)"
        )
        draws_behind(game, player, remaining, queued_excludes(payload))
        payload["drawn"] = 0
        return ReplacementOutcome(replaced=True)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="outside_game_draw",
            player_index=player_index,
            options=tuple(player.sideboard[i].name for i in available),
            default_option=0,
            # Sideboard positions behind each offered name, so a choice made
            # against the filtered list still pulls the right card.
            data={
                "sideboard_indices": available,
                "remaining_draws": remaining,
                QUEUED_EXCLUDES: queued_excludes(payload),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} looks through the cards they own from outside the game (Ring of Ma'rûf)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("outside_game_draw")
def _resolve_outside_game_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    indices = choice.data.get("sideboard_indices") or list(range(len(choice.options)))
    game._finish_outside_game_draw(choice.player_index, indices[option_index])
    draws_behind(
        game, game.players[choice.player_index],
        int(choice.data.get("remaining_draws", 0)),
        choice.data.get(QUEUED_EXCLUDES) or (),
    )
    return 0


def _armed_draw_replacement(game, payload: dict):
    """The oldest armed replacement this seat has, or None.

    Armed, not "will do something", for ``_applies_lamp_draw``'s reason (in
    ``revealed_draws.py``): CR 614.1 spends a one-shot on the next event whether or not the
    effect behind it finds anything to do, so an empty pile has to be handled
    *inside* the effect rather than in front of it. A predicate that declined
    there would leave the charge armed for the rest of the turn.

    Oldest first, because two activations are two effects and the player who
    armed them expects them spent in the order they were paid for.
    """
    seat = game.players.index(payload["player"])
    for entry in getattr(game, "armed_draw_replacements", ()):
        if entry.get("player_index") == seat:
            return entry
    return None


def _applies_armed_draw_replacement(game, payload: dict) -> bool:
    return _armed_draw_replacement(game, payload) is not None


@replacement_effect(
    "draw", DRAW_ARMED_REPLACEMENT, applies=_applies_armed_draw_replacement
)
def _run_armed_draw_replacement(game, payload: dict) -> ReplacementOutcome | None:
    """Mangara's Tome: "The next time you would draw a card this turn, instead
    put the top card of the exiled pile into its owner's hand."

    One draw, because that is what "the next time" replaces (CR 121.2 makes a
    multi-card instruction that many draws): the charge is spent, the armed
    instruction is carried out, and the draws queued behind this one go back
    through the seam so a second armed replacement gets its own.

    Nothing is drawn, so this reports 0 and a "whenever you draw a card" effect
    correctly sees no draw for the replaced one.

    The armed instruction runs with the arming permanent as its source, which
    is what lets it read a pile recorded there (CR 610.3) — and it runs even
    when that permanent has left the battlefield, because the effect is the
    resolved ability's rather than the object's (CR 611.2).
    """
    from ..game_types import OracleExecutionContext

    player = payload["player"]
    entry = _armed_draw_replacement(game, payload)
    game.armed_draw_replacements.remove(entry)
    source = entry.get("source")
    card = getattr(source, "card", None)
    game._execute_oracle_instruction(
        entry["instruction"],
        OracleExecutionContext(
            caster=player, target=player, card=card, source_permanent=source
        ),
    )
    payload["drawn"] = draws_behind(
        game, player, int(payload["count"]) - 1, queued_excludes(payload)
    )
    return ReplacementOutcome(replaced=True)


def _turn_draw_records(game, payload: dict) -> list:
    """The turn-long draw replacements a resolution armed over the drawing
    seat (Plagiarize), oldest first, less the ones this event has already been
    through (CR 614.5). Pure."""
    from ..turn_replacements import DRAW, armed_turn_replacements

    seat = game.players.index(payload["player"])
    excluded = set(payload.get("exclude_sources") or ())
    return [
        record for record in armed_turn_replacements(game, DRAW)
        if record.affected_seat == seat and record.key not in excluded
    ]


def _applies_turn_draw_replacement(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(_turn_draw_records(game, payload))


@replacement_effect(
    "draw", DRAW_GIVEN_TO_ANOTHER, applies=_applies_turn_draw_replacement
)
def _draw_given_to_another(game, payload: dict) -> ReplacementOutcome | None:
    """Plagiarize: "Until end of turn, if target player would draw a card,
    instead that player skips that draw and you draw a card."

    One draw at a time (CR 121.2): the first is taken, the effect's controller
    draws one card in its place, and the draws queued behind go back through
    the seam — so each of them is taken in turn.

    **The substitute is a draw of its own**, made through the seam, so another
    replacement may take it — and **not this one** (CR 614.5: "a replacement
    effect gets only one opportunity to affect an event or any modified events
    that may replace it"), nor any the replaced draw had already been through.
    The record's key joins the event's exclusions for exactly that. It is what
    the card's rulings describe (2007-07-15): two Plagiarizes cast at each
    other "effectively cancel each other out" — the drawer's draw goes to the
    other player, whose substitute draw the second Plagiarize hands back, and
    the draw that comes back has been through both — and one aimed at its own
    caster (2004-10-04) "has no useful effect", because the draw it makes is
    the one it may not replace.

    Nothing is drawn by the player who skipped, so this reports 0 for them,
    and a library they could not have drawn from loses them nothing (the
    2007-07-15 ruling on an empty library): the draw never happens.
    """
    player = payload["player"]
    record = _turn_draw_records(game, payload)[0]
    beneficiary = game.players[record.seat]
    game.log.append(
        f"{player.name} skips a draw and {beneficiary.name} draws instead "
        f"({record.source_name})"
    )
    game._draw_with_replacements(
        beneficiary, 1,
        exclude_sources=queued_excludes(payload) + (record.key,),
    )
    payload["drawn"] = draws_behind(
        game, player, int(payload["count"]) - 1, queued_excludes(payload)
    )
    return ReplacementOutcome(replaced=True)


DISCARD_INSTEAD_OF_DRAW_TEXT = (
    "if a player would draw a card except the first one they draw in each of "
    "their draw steps, that player discards a card instead. if the player "
    "discards a card this way, they draw a card. if the player doesn't discard "
    "a card this way, they mill a card"
)


def _chains_sources(game, payload: dict) -> list:
    """Every permanent whose text is this replacement and that has not already
    had its opportunity on this event (CR 614.5).

    Scanned over the whole board, not one seat's: the sentence says "a player",
    so the enchantment replaces its own controller's draws as well as their
    opponents'. Reading ``_player_controls_text`` here would have made it a
    one-sided card, which is the narrowing this pool keeps producing.
    """
    exclude = set(payload.get("exclude_sources") or ())
    return [
        perm
        for perm in game.all_permanents()
        if DISCARD_INSTEAD_OF_DRAW_TEXT in (perm.effective_card.oracle_text or "").lower()
        and perm.permanent_id not in exclude
    ]


#: "If you would draw a card, you may put a **study** counter on this
#: **enchantment** instead." (Pursuit of Knowledge.)
#:
#: Matched by shape rather than listed as a constant, because both the counter
#: kind and the noun the card calls itself are payload: a creature printing the
#: same sentence with a page counter is printing the same replacement, and a
#: literal would buy exactly one card. The self-reference is already normalized
#: to "this <noun>" before a line reaches any reader here.
#:
#: One reader for the interceptor and for the support gate
#: (``replacement_claims_line``, in ``lines.py``), which is the pairing every text-keyed
#: table in this engine keeps.
_DRAW_BECOMES_COUNTER_RE = re.compile(
    r"^if you would draw a card, you may put a (?P<counter>[a-z][a-z'-]*) "
    r"counter on this (?:creature|artifact|enchantment|land|permanent) instead$"
)


def draw_becomes_counter(line: str) -> str | None:
    """The counter kind *line* offers in place of a draw, or None."""
    match = _DRAW_BECOMES_COUNTER_RE.match(line.strip().lower().rstrip("."))
    return match.group("counter") if match is not None else None


def _draw_becomes_counter_sources(game, payload: dict) -> list:
    """Every permanent offering this substitution for *this* draw.

    "**You**" is the ability's controller (CR 109.5), so only the drawing seat's
    own permanents are in contention - an opponent's copy offers its own
    controller the choice about their own draws and says nothing about this one.

    CR 614.5's exclusion is honoured through the same ``exclude_sources`` key
    every other draw replacement here reads: the draw a declined offer leaves
    behind goes back through the seam, and a source already asked must not ask
    again.

    Read off ``effective_card``, because a Clone of one has the sentence
    (CR 707.2) and one whose text was changed does not.

    Pure, like every applicability predicate in this file: ``effect_ordering``
    counts the contenders before any of them runs.
    """
    exclude = set(payload.get("exclude_sources") or ())
    seat = game.players.index(payload["player"])
    return [
        perm
        for controller, perm in game.permanents_with_controller()
        if controller == seat
        and perm.permanent_id not in exclude
        and any(
            draw_becomes_counter(line) is not None
            for line in (perm.effective_card.oracle_text or "").splitlines()
        )
    ]


def _applies_draw_becomes_counter(game, payload: dict) -> bool:
    return (
        int(payload.get("count", 0)) > 0
        and bool(_draw_becomes_counter_sources(game, payload))
    )


@replacement_effect(
    "draw", DRAW_BECOMES_COUNTER, applies=_applies_draw_becomes_counter
)
def _counter_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Pursuit of Knowledge: "If you would draw a card, you may put a study
    counter on this enchantment instead."

    One draw at a time, because that is what the sentence replaces (CR 121.2
    makes a multi-card instruction that many draws). The draws queued behind
    this one go back through the seam so a second source gets its own offer.

    **Optional**, so it is a :class:`ReplacementChoice` rather than an applied
    effect: ``apply_replacements`` returns synchronously and the answer arrives
    from a human on a later request. Both answers finish through the one
    registered resolver, which is what keeps the accepted and the declined path
    from being two implementations of one sentence.

    The declining answer still *replaces* the event as far as this function is
    concerned - the draw it leaves is remade through the seam with this source
    excluded (CR 614.5), which is how the offer is not put twice.
    """
    player = payload["player"]
    seat = game.players.index(player)
    source = min(
        _draw_becomes_counter_sources(game, payload),
        key=lambda perm: perm.permanent_id,
    )
    kind = next(
        counter
        for counter in (
            draw_becomes_counter(line)
            for line in (source.effective_card.oracle_text or "").splitlines()
        )
        if counter is not None
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="draw_becomes_counter",
            player_index=seat,
            # Declining first, and that is the default a non-interactive seat
            # takes. CR 614.1 leaves the choice to the affected player, and the
            # engine's rule for an unconstrained one is the choice a player
            # would make (idiom 8) - a seat that accepted every offer would
            # never draw another card, in exchange for counters no AI policy
            # spends. A human seat is asked and may say yes; a headless one
            # keeps playing.
            options=("draw the card", f"put a {kind} counter on {source.card.name}"),
            default_option=0,
            data={
                "counter": kind,
                "source_id": source.permanent_id,
                "remaining_draws": int(payload["count"]) - 1,
                "exclude_sources": excludes,
                QUEUED_EXCLUDES: queued_excludes(payload),
                "turn_based": bool(payload.get("turn_based")),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} may put a {kind} counter on {source.card.name} "
            "instead of drawing"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("draw_becomes_counter")
def _resolve_draw_becomes_counter(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Apply Pursuit of Knowledge's offer, either way.

    Option 0 declines: the draw this function was asked about is remade through
    ``_draw_with_replacements`` with the offering permanent excluded, so every
    *other* draw replacement still gets its turn and this one is not asked
    twice (CR 614.5).

    Option 1 accepts: the counter goes on and no card is drawn, so a "whenever
    you draw a card" effect correctly sees one fewer draw.

    The source is addressed by ``permanent_id``: it can leave the battlefield
    while the offer is queued, and a counter placed on whatever slid into its
    slot would be a counter on the wrong permanent.
    """
    player = game.players[choice.player_index]
    data = choice.data
    excludes = tuple(data.get("exclude_sources") or ())
    remaining = int(data.get("remaining_draws", 0))
    drawn = 0
    if option_index == 0:
        drawn += game._draw_with_replacements(
            player, 1,
            turn_based=bool(data.get("turn_based")),
            exclude_sources=excludes,
        )
    else:
        source = game.permanent_by_id(int(data["source_id"]))
        if source is None:
            # The enchantment left while the offer was queued. Nothing to put a
            # counter on, and the draw was already replaced - CR 614.1's
            # substitution happened, and this is the "does as much as it can"
            # end of it.
            game.log.append(
                f"{player.name}: the counter had nowhere to go and no card was drawn"
            )
        else:
            from ..named_counters import add_counters

            add_counters(source, str(data["counter"]), 1)
            game.log.append(
                f"{player.name} put a {data['counter']} counter on "
                f"{source.card.name} instead of drawing"
            )
    # Behind this draw, and parked by the seam while the draw a decline
    # remade is waiting on another replacement's offer (CR 121.2).
    drawn += draws_behind(game, player, remaining, data.get(QUEUED_EXCLUDES) or ())
    return drawn


#: "If you would draw a card, you may skip that draw instead." (Obstinate
#: Familiar.) Pursuit of Knowledge's sentence with nothing where the counter
#: was: an optional replacement of one draw by **no event at all** (CR 614.10:
#: "'Skip [something]' is the same as 'Instead of doing [something], do
#: nothing.'").
#:
#: The whole line, with no payload: the sentence names the draw, the seat and
#: the option and nothing else. A printing that added a condition or a rider
#: would be a different rule and stays unmatched.
SKIP_DRAW_TEXT = "if you would draw a card, you may skip that draw instead"


def skip_draw_line(line: str) -> bool:
    """Whether *line* is, in full, the optional skip. One reader for the
    interceptor and for the claim (``REPLACEMENT_LINES``)."""
    return " ".join((line or "").split()).strip().lower().rstrip(".") == SKIP_DRAW_TEXT


def _skip_draw_sources(game, payload: dict) -> list:
    """Every permanent offering to skip *this* draw.

    "If **you** would draw a card" is CR 109.5's seat, so only the drawing
    player's own permanents offer it. CR 614.5's exclusion is honoured through
    the ``exclude_sources`` key every draw replacement here reads — the draw a
    declined offer leaves is remade through the seam, and a source already
    asked must not ask again. Read off ``effective_card`` (CR 707.2, CR 612.1),
    and pure, like every applicability predicate in this file.
    """
    exclude = set(payload.get("exclude_sources") or ())
    seat = game.players.index(payload["player"])
    return [
        perm
        for perm in game.controlled_by(seat)
        if perm.permanent_id not in exclude
        and any(
            skip_draw_line(line)
            for line in (perm.effective_card.oracle_text or "").splitlines()
        )
    ]


def _applies_skip_draw(game, payload: dict) -> bool:
    return int(payload.get("count", 0)) > 0 and bool(
        _skip_draw_sources(game, payload)
    )


@replacement_effect("draw", DRAW_MAY_BE_SKIPPED, applies=_applies_skip_draw)
def _skip_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Obstinate Familiar: "If you would draw a card, you may skip that draw
    instead."

    One draw at a time (CR 121.2 makes a multi-card instruction that many
    draws), and **optional**, so it is a :class:`ReplacementChoice` — the
    shape Pursuit of Knowledge's offer above has, for its reasons: the answer
    arrives from a human on a later request, and both answers finish through
    one registered resolver.

    The default a non-interactive seat takes is the choice a player would
    make: draw the card — unless the library is **empty**, where the draw
    would lose the game at the next state-based check (CR 704.5b) and skipping
    it is the whole reason the card is played. A seat that always skipped
    would never draw again; one that never did would deck itself beside the
    permanent that prevents it.
    """
    player = payload["player"]
    seat = game.players.index(player)
    source = min(
        _skip_draw_sources(game, payload), key=lambda perm: perm.permanent_id
    )
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="skip_draw",
            player_index=seat,
            options=("draw the card", "skip the draw"),
            default_option=0 if player.library else 1,
            data={
                "source_id": source.permanent_id,
                "remaining_draws": int(payload["count"]) - 1,
                "exclude_sources": excludes,
                QUEUED_EXCLUDES: queued_excludes(payload),
                "turn_based": bool(payload.get("turn_based")),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} may skip that draw ({source.card.name})"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("skip_draw")
def _resolve_skip_draw(game, choice: ReplacementChoice, option_index: int) -> int:
    """Carry out the answer to Obstinate Familiar's offer.

    Option 0 declines: the draw is remade through ``_draw_with_replacements``
    with the offering permanent excluded, so every *other* draw replacement
    still gets its turn and this one is not asked twice (CR 614.5).

    Option 1 skips: nothing happens and no card is drawn, so "whenever you
    draw a card" sees one fewer draw and an empty library is never drawn from.

    Nothing here reads the source again, so a Familiar that left the
    battlefield while the offer was queued changes neither answer: the
    replacement was applied when it was offered (CR 614.1), and the two
    options are what it offered.
    """
    player = game.players[choice.player_index]
    data = choice.data
    remaining = int(data.get("remaining_draws", 0))
    drawn = 0
    if option_index == 0:
        drawn += game._draw_with_replacements(
            player, 1,
            turn_based=bool(data.get("turn_based")),
            exclude_sources=tuple(data.get("exclude_sources") or ()),
        )
    else:
        source = game.permanent_by_id(int(data["source_id"]))
        game.log.append(
            f"{player.name} skipped a draw"
            + (f" ({source.card.name})" if source is not None else "")
        )
    # The draws queued behind this one are their own draws (CR 121.2) and are
    # offered on their own — including by this source again — once the draw
    # in front of them is finished (the seam parks them until then).
    drawn += draws_behind(game, player, remaining, data.get(QUEUED_EXCLUDES) or ())
    return drawn


def _chains_affected_draws(payload: dict) -> int:
    """How many of this event's draws the exemption leaves.

    The same arithmetic ``_doubled_draw_count`` sets out: CR 121.2 makes an
    event of ``count`` draws that many individual draws, and "except the first
    one they draw in each of their draw steps" exempts **one draw**, not one
    event — a draw step with a Howling Mine out draws 1 + 1, and only the first
    of the two is exempt.
    """
    exempt = 1 if payload.get("turn_based") else 0
    return max(0, int(payload.get("count", 0)) - exempt)


def _applies_discard_instead_of_draw(game, payload: dict) -> bool:
    return _chains_affected_draws(payload) > 0 and bool(_chains_sources(game, payload))


@replacement_effect(
    "draw", DRAW_DISCARD_INSTEAD, applies=_applies_discard_instead_of_draw
)
def _discard_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Chains of Mephistopheles: "If a player would draw a card except the first
    one they draw in each of their draw steps, that player discards a card
    instead. If the player discards a card this way, they draw a card. If the
    player doesn't discard a card this way, they mill a card."

    One draw at a time, because that is what the sentence replaces. The event is
    consumed; the exempt draw in front of it and the draws queued behind it are
    made through the seam again, so a second replacement armed alongside still
    gets its own.

    The three branches are the printed three. Which card is discarded is the
    player's choice, so it goes through the ordinary ``discard`` prompt with the
    draw hung on it as the prompt's follow-on — a human picks, an AI takes the
    default, and either way the draw happens *after* the discard rather than
    before it. The only way not to discard is to have nothing to discard
    (CR 701.9a), and that is the branch that mills.
    """
    player = payload["player"]
    seat = game.players.index(player)
    count = int(payload["count"])
    exempt = 1 if payload.get("turn_based") else 0
    drawn = 0
    if exempt:
        # Not replaced, and still a draw like any other: it goes back through
        # the seam so an Aladdin's Lamp armed for the draw step still takes it.
        # The draws behind it are this event without its first draw — so they
        # go back as one, and this replacement meets the first of *them* there.
        # One at a time (CR 121.2): were the discard armed here, it would sit
        # beside whatever the exempt draw is still waiting on.
        drawn += game._draw_with_replacements(
            player, exempt, turn_based=True,
            exclude_sources=queued_excludes(payload),
        )
        drawn += draws_behind(
            game, player, count - exempt, queued_excludes(payload)
        )
        payload["drawn"] = drawn
        return ReplacementOutcome(replaced=True)
    remaining = count - 1
    source = min(_chains_sources(game, payload), key=lambda perm: perm.permanent_id)
    # CR 614.5: the draw this effect creates is not replaced by this effect
    # again. A *second* copy is a different effect and still applies, which is
    # why the exclusion names the source rather than the wording.
    excludes = tuple(payload.get("exclude_sources") or ()) + (source.permanent_id,)
    if player.hand:
        game.arm_pending_choice(
            "discard",
            seat,
            count=1,
            filter={},
            draw_that_many=True,
            draw_exclude_sources=excludes,
            queued_draws=max(0, remaining),
            queued_exclude_sources=queued_excludes(payload),
        )
        game.log.append(
            f"{player.name} discards a card instead of drawing ({source.card.name})"
        )
    else:
        milled = _mill_cards(game, player, 1)
        game.log.append(
            f"{player.name} had no card to discard and milled {milled} card(s) "
            f"({source.card.name})"
        )
        drawn += draws_behind(game, player, remaining, queued_excludes(payload))
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


def _mill_cards(game, player, count: int) -> int:
    """CR 701.17a: put the top *count* cards of *player*'s library into their
    graveyard, stopping at whatever is there.

    Milling is not a draw and never has been — CR 704.5b's loss is about
    *attempting to draw* from an empty library — so an empty library mills
    nothing and costs nothing.
    """
    milled = 0
    for _ in range(count):
        if not player.library:
            break
        game.put_card_into_graveyard(
            player, player.library.pop(0), from_zone="library"
        )
        milled += 1
    return milled


RETURN_FROM_GRAVEYARD_INSTEAD_OF_DRAW_TEXT = (
    "if you would draw a card, return a card from your graveyard to your hand "
    "instead. if you can\'t, you lose the game"
)


def _applies_return_from_graveyard_instead_of_draw(game, payload: dict) -> bool:
    return game._player_controls_text(
        payload["player"], RETURN_FROM_GRAVEYARD_INSTEAD_OF_DRAW_TEXT
    )


@replacement_effect(
    "draw", DRAW_RETURNS_FROM_GRAVEYARD,
    applies=_applies_return_from_graveyard_instead_of_draw,
)
def _return_from_graveyard_instead_of_drawing(game, payload: dict) -> ReplacementOutcome | None:
    """Forbidden Crypt: "If you would draw a card, return a card from your
    graveyard to your hand instead. If you can\'t, you lose the game."

    Both printed sentences, because the second is this replacement\'s *decline*
    branch rather than a separate ability: CR 614.6\'s "as much as possible" has
    nothing to say here — the card names what happens when the replacement
    cannot be carried out, and what it names is CR 104.3e.

    One draw at a time (CR 121.2). The draws queued behind this one are their
    own events and go back through the seam, which is what makes a two-card
    draw under an empty Crypt lose the game on the first of them rather than on
    the second.

    Which card comes back is the player\'s choice, so it is offered rather than
    picked: an interactive seat is queued and the draw suspends, every other
    seat takes the default at once, and both finish through the one resolver
    below.
    """
    player = payload["player"]
    remaining = int(payload["count"]) - 1
    if not player.graveyard:
        # "If you can\'t, you lose the game." CR 104.3e — an effect that states
        # a player loses the game, applied here and not left to a state-based
        # action, exactly as the `player_loses_game` handler applies it.
        if not player.lost:
            player.lost = True
            game.log.append(
                f"{player.name} had no card to return from their graveyard and "
                f"lost the game (104.3e)"
            )
        payload["drawn"] = 0
        return ReplacementOutcome(replaced=True)
    suspended, drawn = offer_replacement_choice(
        game,
        ReplacementChoice(
            kind="return_from_graveyard_instead_of_draw",
            player_index=game.players.index(player),
            options=tuple(card.name for card in player.graveyard),
            # Option 0 like every other choice in this file. The offer is
            # between *cards*, not between outcomes, and which card is worth
            # more is a valuation question that belongs in
            # ``engine/ai_valuation.py`` rather than in a replacement effect.
            default_option=0,
            data={
                "remaining_draws": max(0, remaining),
                QUEUED_EXCLUDES: queued_excludes(payload),
            },
        ),
    )
    if suspended:
        game.log.append(
            f"{player.name} returns a card from their graveyard instead of "
            f"drawing (Forbidden Crypt)"
        )
    payload["drawn"] = drawn
    return ReplacementOutcome(replaced=True)


@replacement_choice("return_from_graveyard_instead_of_draw")
def _resolve_return_from_graveyard_instead_of_draw(
    game, choice: ReplacementChoice, option_index: int
) -> int:
    """Move the chosen card, then make the draws queued behind this one.

    Through ``put_card_into_hand`` rather than a bare append, so CR 903.9b sees
    a commander coming back and offers its command zone — the reason that seam
    exists at all. Zero cards drawn either way: the draw was replaced, so a
    "whenever you draw a card" effect correctly sees none.
    """
    player = game.players[choice.player_index]
    if 0 <= option_index < len(player.graveyard):
        card = player.graveyard.pop(option_index)
        game.put_card_into_hand(player, card)
        game.log.append(
            f"{player.name} returned {card.name} from their graveyard to their "
            f"hand instead of drawing (Forbidden Crypt)"
        )
    draws_behind(
        game, player, int(choice.data.get("remaining_draws", 0)),
        choice.data.get(QUEUED_EXCLUDES) or (),
    )
    return 0
