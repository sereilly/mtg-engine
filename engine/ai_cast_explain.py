"""Why the AI casts what it casts: every candidate one cast decision weighs for
a card, its score broken into the terms it was summed from, which one won,
and why each one that was not proposed was dropped.

::

    from engine.ai_cast_explain import explain_cast

    explanation = explain_cast(game, seat, card)   # the decision, right now
    print(explanation)                             # the breakdown, as text
    explanation.candidates                         # every TracedCandidate
    explanation.winner                             # this card's, if it won
    explanation.decision                           # what the chooser returned

**It asks the real chooser** — ``ai_policy.choose_cast_action`` in the seat's
own main phase with an empty stack, ``choose_combat_instant_cast_action``
anywhere else, as the simulator and the web AI seat ask them (``speed=``
names one) — with the decision's trace listening
(``ai_cast_trace.listening``). Every number printed is one the builders
recorded as they summed it (``ai_cast_score.finished_cast_candidate``,
``ai_scoring.cast_score_terms``), and every reason a candidate was dropped is
the gate's own (``ai_cast_trace.dropped`` at the gate's ``return``), so the
explanation cannot drift from the decision: there is no second reading.

The whole decision runs, every card the seat could cast included, because a
card's candidates are only half the answer — the other half is what beat it.
The chooser draws nothing from the seeded random generator (its rehearsals
restore what their copies draw); the generator's state is put back after the
explanation all the same, so a script may explain a decision part-way through
a seeded game and play on as if it had not asked.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import ai_cast_trace as cast_trace
from .ai_cast_trace import TracedCandidate, TracedEntry

#: The steps a seat's sorcery-speed casts are asked in (``web/game_flow``'s
#: and the simulator's main-phase door).
MAIN_STEPS = ("precombat_main", "postcombat_main")
#: How much of a mode's printed words a label carries.
_LABEL_WIDTH = 46


@dataclass
class CastExplanation:
    """One cast decision, explained for one card (:func:`explain_cast`)."""

    card: object
    seat: int
    #: ``"main"`` or ``"instant"``.
    speed: str
    chooser: str
    #: The moment, as the chooser's callers read it.
    context: "list[str]" = field(default_factory=list)
    #: Every place this card was weighed from, in the chooser's order.
    entries: "list[TracedEntry]" = field(default_factory=list)
    #: What the chooser returned — this card's cast, another card's, or None.
    decision: object = None
    #: How many places, of every card, the decision weighed.
    places_weighed: int = 0
    _game: object = field(default=None, repr=False)

    @property
    def candidates(self) -> "list[TracedCandidate]":
        """Every candidate begun for this card, entry by entry."""
        return [candidate for entry in self.entries for candidate in entry.candidates]

    @property
    def winner(self) -> "TracedCandidate | None":
        """The candidate the chooser returned, when it is this card's."""
        return next(
            (c for c in self.candidates if c.action is not None and c.action is self.decision),
            None,
        )

    def picks(self) -> "list[TracedCandidate | None]":
        """Each entry's pick: the candidate the builder returned for it."""
        return [_pick_of(entry) for entry in self.entries]

    def render(self) -> str:
        return _render(self)

    def __str__(self) -> str:
        return self.render()


def explain_cast(game, seat: int, card, *, speed: "str | None" = None) -> CastExplanation:
    """Every candidate the AI's cast decision builds for *card* from *seat*
    right now, scored term by term, with the decision it came to.

    *speed* is ``"main"`` (``ai_policy.choose_cast_action``) or ``"instant"``
    (``ai_policy.choose_combat_instant_cast_action``); None reads the moment:
    the main-phase chooser in *seat*'s own main phase with an empty stack, the
    instant-speed one anywhere else.
    """
    from . import ai_policy
    from .ai_player_control import plays_for_another

    if speed is None:
        speed = (
            "main"
            if game.active_player_index == seat
            and game.current_step in MAIN_STEPS
            and not game.stack
            else "instant"
        )
    if speed not in ("main", "instant"):
        raise ValueError(f"speed is 'main' or 'instant', not {speed!r}")
    chooser = (
        ai_policy.choose_cast_action if speed == "main"
        else ai_policy.choose_combat_instant_cast_action
    )
    explanation = CastExplanation(
        card=card, seat=seat, speed=speed,
        chooser=f"ai_policy.{chooser.__name__}", _game=game,
    )
    explanation.context.extend(_moment(game, seat, speed))
    if plays_for_another(game, seat):
        explanation.context.append(
            "another player decides for this seat (CR 723.5): it casts nothing"
        )
    state = random.getstate()
    try:
        with cast_trace.listening(game, seat, speed) as trace:
            explanation.decision = chooser(game, seat)
    finally:
        random.setstate(state)
    names = _names_of(card)
    explanation.places_weighed = len(trace.entries)
    explanation.entries = [
        entry for entry in trace.entries
        if entry.card is card or getattr(entry.card, "name", None) in names
    ]
    if not explanation.entries:
        explanation.context.append(_why_unweighed(game, seat, card, speed))
    return explanation


def _names_of(card) -> "set[str]":
    """*card*'s name and, for a split card, each half's (CR 709.3)."""
    from .faces import castable_faces

    return {card.name} | {face.name for face in castable_faces(card)}


def _moment(game, seat: int, speed: str) -> "list[str]":
    """What the moment is, as the chooser's callers decide to ask it."""
    lines = [
        f"turn {game.turn}, {game.current_step}, seat {game.active_player_index} active,"
        f" stack {len(game.stack)}"
    ]
    if speed == "instant":
        from .ai_policy import holds_an_instant_it_could_pay_for
        from .ai_priority import instant_speed_window
        from .ai_scratch_copy import mid_resolution

        window = instant_speed_window(game, seat)
        lines.append(
            f"priority window {window!r}; mid-resolution {mid_resolution(game)};"
            f" holds an instant it could pay for {holds_an_instant_it_could_pay_for(game, seat)}"
            " (ai_priority.act_at_priority asks the chooser only in a window, never"
            " mid-resolution, and only when it holds one)"
        )
    return lines


def _why_unweighed(game, seat: int, card, speed: str) -> str:
    if speed == "instant":
        from .ai_policy import _weighed_at_instant_speed_now

        if not _weighed_at_instant_speed_now(game, seat, card):
            return (
                "the chooser never weighed this card: not one it weighs at instant"
                " speed now (ai_policy._weighed_at_instant_speed_now)"
            )
    if card.primary_type == "land":
        return "the chooser never weighed this card: a land is a land drop (choose_land_drop)"
    return (
        "the chooser never weighed this card: it is in no zone this seat may cast"
        " it from now"
    )


def _pick_of(entry: TracedEntry) -> "TracedCandidate | None":
    return next(
        (c for c in entry.candidates if c.action is not None and c.action is entry.result),
        None,
    )


# --- the text --------------------------------------------------------------------


def _render(explanation: CastExplanation) -> str:
    game = explanation._game
    card = explanation.card
    lines = [
        f"{card.name} - seat {explanation.seat}, {explanation.speed} speed:"
        f" {explanation.chooser}",
    ]
    lines += [f"  {line}" for line in explanation.context]
    decision = explanation.decision
    winner = explanation.winner
    if decision is None:
        lines.append("decision: cast nothing")
    elif winner is not None:
        lines.append(
            f"decision: THIS CARD - {_label(card, winner)} from {decision.from_zone},"
            f" score {decision.score:.2f}"
        )
    else:
        lines.append(
            f"decision: {decision.card_name} from {decision.from_zone},"
            f" score {decision.score:.2f}"
        )
    lines.append(
        f"({len(explanation.entries)} of the {explanation.places_weighed} places the"
        " decision weighed were this card's)"
    )
    for number, entry in enumerate(explanation.entries, 1):
        lines.append("")
        lines.append(f"[{number}] {_entry_heading(entry)}")
        if entry.skipped:
            lines.append(f"    SKIPPED: {entry.skipped}")
            continue
        for text in entry.notes:
            lines.append(f"    note: {text}")
        if not entry.candidates and not entry.notes:
            lines.append("    no candidate begun")
        pick = _pick_of(entry)
        for candidate in entry.candidates:
            lines += _candidate_lines(game, card, entry, candidate, pick, decision)
    return "\n".join(lines)


def _entry_heading(entry: TracedEntry) -> str:
    where = f"{entry.from_zone} #{entry.zone_index}"
    permission = entry.permission
    if permission is not None:
        granted = getattr(permission.permission, "source_name", None) or "an effect"
        how = []
        if getattr(permission, "waives_mana_cost", False):
            how.append("mana cost waived")
        if permission.cost is not None:
            how.append("its alternative cost")
        if getattr(permission, "expires", False):
            how.append("a permission that ends")
        where += f", under {granted}" + (f" ({', '.join(how)})" if how else "")
        if permission.owner_seat != entry.seat:
            where += f", seat {permission.owner_seat}'s pile"
    if entry.extra_generic:
        where += f", tax {{{entry.extra_generic}}}"
    if entry.withdrawn:
        where += f" - WITHDRAWN: {entry.withdrawn}"
    return where


def _label(card, candidate: TracedCandidate) -> str:
    parts = []
    if candidate.variant == "single":
        if candidate.mode_index is not None:
            modes = _modes(card)
            words = (
                modes[candidate.mode_index].label or ""
                if 0 <= candidate.mode_index < len(modes) else ""
            )
            if len(words) > _LABEL_WIDTH:
                words = words[: _LABEL_WIDTH - 3] + "..."
            parts.append(f'mode {candidate.mode_index} "{words}"')
        else:
            parts.append("cast")
    else:
        parts.append(candidate.variant)
    if candidate.offers:
        parts.append(f"offers {candidate.offers}")
    if candidate.life_x is not None:
        parts.append(f"X={candidate.life_x} in life")
    return ", ".join(parts)


def _modes(card):
    from .oracle import compile_card_oracle

    return compile_card_oracle(card).modes


def _candidate_lines(game, card, entry, candidate, pick, decision) -> "list[str]":
    lines = [f"    - {_label(card, candidate)}"]
    if candidate.score is not None:
        shown = [f"{name} {value:+.2f}" for name, value in candidate.terms if value]
        zero = [name for name, value in candidate.terms if not value]
        lines.append(
            f"        score {candidate.score:.2f} = " + (" ".join(shown) or "0")
            + (f"   (zero: {', '.join(zero)})" if zero else "")
        )
    if candidate.action is not None:
        lines.append(f"        announces: {describe_action(game, card, candidate.action)}")
    rehearsal = candidate.rehearsal
    if rehearsal is not None:
        text = (
            f"        rehearsal: now {rehearsal.now:+.2f}, lasting {rehearsal.lasting:+.2f},"
            f" swing {rehearsal.swing:+.2f}"
        )
        if rehearsal.through_combat:
            text += ", read through the fight"
        if candidate.rehearsal_parts:
            text += " (of which " + ", ".join(
                f"{name} now {now:+.2f} lasting {lasting:+.2f}"
                for name, now, lasting in candidate.rehearsal_parts
            ) + ")"
        lines.append(text)
    elif candidate.score is not None and candidate.variant != "every mode":
        lines.append("        rehearsal: none run (a permanent is scored by what it is)")
    for text in candidate.notes:
        lines.append(f"        weighed: {text}")
    lines.append(f"        => {_verdict(card, entry, candidate, pick, decision)}")
    return lines


def _verdict(card, entry, candidate, pick, decision) -> str:
    if candidate.dropped is not None:
        return f"DROPPED: {candidate.dropped}"
    if candidate.action is None:
        return "DROPPED: no reason recorded (a builder returned None without naming why)"
    if candidate is pick:
        if entry.withdrawn:
            return f"PICKED for this place, then WITHDRAWN: {entry.withdrawn}"
        if decision is not None and candidate.action is decision:
            return "PICKED - this is the decision"
        if decision is None:
            return "PICKED for this place; the chooser cast nothing"
        return (
            f"PICKED for this place; lost to the decision ({decision.card_name} from"
            f" {decision.from_zone}, {decision.score:.2f})"
        )
    if pick is not None and pick.variant == "every mode" and candidate.variant == "single":
        return "folded into the every-mode cast"
    if pick is not None:
        relation = "tied with, and came after," if candidate.score == pick.score else "lost to"
        return f"{relation} {_label(card, pick)} ({candidate.score:.2f} vs {pick.score:.2f})"
    return "not picked: nothing was picked for this place"


def describe_action(game, card, action) -> str:
    """What *action* announces, in words: its seat, the objects by name, its
    modes, X, offers, alternative cost and the lands it taps."""
    parts = [f"seat {action.target_player_index}"]
    named = _objects_named(game, action)
    if named:
        parts.append("naming " + ", ".join(named))
    if action.target_stack_index is not None:
        parts.append(f"stack #{action.target_stack_index}")
    if action.divided_targets:
        parts.append(f"divided {list(action.divided_targets)}")
    if action.mode_choices:
        parts.append("modes " + ", ".join(
            _mode_choice(game, choice) for choice in action.mode_choices
        ))
    if action.x_value is not None:
        parts.append(f"X={action.x_value}")
    if action.optional_cost_payments:
        parts.append(f"offers {action.optional_cost_payments}")
    if action.alternative_cost:
        parts.append(
            "alternative cost"
            + (f" #{action.alternative_cost_index}" if action.alternative_cost_index is not None else "")
        )
    if action.cost_permanent_ids:
        parts.append("paying with " + ", ".join(
            _permanent_name(game, pid) for pid in action.cost_permanent_ids
        ))
    parts.append(f"taps {len(action.land_tap_indices or ())}")
    return "; ".join(parts)


def _objects_named(game, action) -> "list[str]":
    ids = [pid for pid in (action.target_permanent_ids or ()) if isinstance(pid, int)]
    if ids:
        return [_permanent_name(game, pid) for pid in ids]
    return [
        _graveyard_card_name(game, action.target_player_index, index)
        for index in (getattr(action, "target_graveyard_indices", None) or ())
    ]


def _graveyard_card_name(game, seat, index) -> str:
    pile = game.players[seat].graveyard if isinstance(seat, int) else []
    if isinstance(index, int) and 0 <= index < len(pile):
        return f"{pile[index].name} (seat {seat}'s graveyard)"
    return f"graveyard slot {index} of seat {seat}"


def _permanent_name(game, permanent_id: int) -> str:
    permanent = game.permanent_by_id(permanent_id)
    if permanent is None:
        return f"permanent {permanent_id}"
    return f"{permanent.card.name} (seat {game.controller_index_of(permanent)})"


def _mode_choice(game, choice: dict) -> str:
    text = f"{choice.get('index')}"
    ids = [pid for pid in (choice.get("target_permanent_ids") or ()) if isinstance(pid, int)]
    graveyard = choice.get("target_graveyard_indices") or ()
    if ids:
        text += "->" + ", ".join(_permanent_name(game, pid) for pid in ids)
    elif graveyard:
        text += "->" + ", ".join(
            _graveyard_card_name(game, choice.get("target_player_index"), index)
            for index in graveyard
        )
    elif choice.get("target_stack_index") is not None:
        text += f"->stack #{choice['target_stack_index']}"
    return text


__all__ = ["CastExplanation", "describe_action", "explain_cast"]
