"""How often an ability has been activated, and how often it may be (CR 602.5b/c).

"Activate only once each turn" (Dream Coat), "Activate no more than twice each
turn" (Vampire Bats), "Activate no more times each turn than the number of snow
Swamps you control" (Withering Wisps), "Activate only once" (Goblin Ski Patrol,
and Touch of Vitae's granted line) — and the abilities that *read* the same
ledger as an effect ("If this ability has been activated four or more times
this turn, …", Farrelite Priest).

Two halves that must agree, which is why they are one module:

* **the cap**, read off the printed clause — :func:`printed_activation_caps` is
  the only answer to "is this line capped, and by what", and
  :func:`at_activation_limit` compares each cap against its own tally;
* **the tally**, state on the permanent — :data:`ACTIVATION_TALLY_MARK` per
  permanent (per turn and over its life) and :data:`ONCE_ONLY_TALLY_MARK` per
  printed line (CR 602.5c: a budget belongs to the ability as acquired), written
  by :func:`mark_activated_this_turn` / :func:`mark_once_only_activation` from
  the activation path and read by the refusal and the rows.

The four row predicates the restriction table calls for these clauses live
here with the ledger they read; the table stays one table in
``engine/activation_restrictions.py``. The clauses are found by the same reader
the table uses (``engine/activation_clauses.py``), so a capped line and a
restricted line cannot be split differently.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from .activation_clauses import _clauses
from .activation_conditions import _board_count, _counted_board_phrase

if TYPE_CHECKING:
    from .game import Game


#: The metadata key a per-turn-limited activation tallies on its permanent, and
#: the one every reader of that clause shares. The refusal and the stamp used to
#: agree by both spelling the words, which is one fact with two representations
#: -- the shape this whole module exists to collapse.
#:
#: The value is ``{"turn": <turn>, "count": <activations>}`` rather than a bare
#: turn number, because "once" is not the only cap a card prints: Vampire Bats
#: says "Activate no more than **twice** each turn", and a stamp that can only
#: record *that* it happened cannot answer how often. Both entries are plain
#: ints, so the value survives the Debug Menu's raw-state round trip.
#:
#: A third entry, ``"ever"``, is the same count with no turn on it: "Activate
#: only **once**" (Goblin Ski Patrol) is a cap on the permanent's whole life on
#: the battlefield rather than on a turn, and a tally that resets cannot answer
#: it. One key rather than two, because both numbers are written by the same
#: stamp at the same moment and a second key is a second chance to write only
#: one of them. A permanent that leaves and comes back is a new object
#: (CR 400.7) and its metadata goes with the old one, which is exactly the
#: reading CR 602.5's "only once" has.
ACTIVATION_TALLY_MARK = "ability_activations_this_turn"

#: How a printed frequency reads as a number. Two irregular spellings and a
#: numbered family -- "once", "twice", "three times" -- which is all English
#: prints for this clause.
_FREQUENCY_WORDS = {"once": 1, "twice": 2}

#: "Activate no more than twice each turn." (Vampire Bats.) The frequency is
#: payload, exactly like the step in `_before_step` and the counter word in
#: `_at_least_that_many_counters`: a card printed "no more than three times"
#: needs no row of its own.
_PRINTED_FREQUENCY = r"(?P<freq>once|twice|[a-z0-9]+ times)"


def _frequency_value(word: str) -> int | None:
    """A printed frequency as a number, or None when it is not one this reads."""
    from .oracle_types import _NUMBER_WORDS

    cleaned = " ".join((word or "").lower().split())
    if cleaned in _FREQUENCY_WORDS:
        return _FREQUENCY_WORDS[cleaned]
    if cleaned.endswith(" times"):
        head = cleaned[: -len(" times")]
        count = int(head) if head.isdigit() else _NUMBER_WORDS.get(head)
        if count:
            return count
    return None


@dataclass(frozen=True)
class ActivationCap:
    """One printed per-turn cap on one ability line (CR 602.5).

    Two shapes, and the difference is *when* the number exists. A printed one
    ("no more than twice each turn") is a fact about the sentence and can be
    read off the text alone; a counted one ("no more times each turn than the
    number of snow Swamps you control", Withering Wisps) is a fact about the
    board and has no value until a game and a seat are named.

    That is why "is this line capped" and "what is the cap" are two questions
    with two readers -- :func:`printed_activation_caps` and
    :func:`activations_allowed_each_turn`. Fusing them, as one text-only
    function did while every cap in the pool was printed, means a counted cap
    can only be answered by returning None, which is the value that means *no
    cap at all*: the tally would stop, and the ability would be uncapped on
    every board.
    """

    #: The number the sentence names, or None when it names a noun phrase.
    printed: int | None = None
    #: The noun phrase the cap counts, controlled by the activating seat.
    counted: str | None = None
    #: Whether the cap is over the permanent's whole life rather than over one
    #: turn ("Activate only once", Goblin Ski Patrol). It changes *which tally*
    #: the cap is compared against, never how the number is read — which is why
    #: it is a field here rather than a second cap class: `resolve` answers the
    #: same question either way, and only :func:`at_activation_limit` cares.
    lifetime: bool = False

    def resolve(self, game=None, controller_index=None, source=None) -> int | None:
        """This cap as a number on the board in front of it, or None.

        None means "not answerable here", never "uncapped": a counted cap asked
        with no game is unanswered, and the caller that can refuse an activation
        is the caller that has one.
        """
        if self.printed is not None:
            return self.printed
        if self.counted is None or game is None or controller_index is None:
            return None
        return _board_count(game, controller_index, source, self.counted)


def _printed_frequency_cap(match: "re.Match[str]") -> "ActivationCap | None":
    value = _frequency_value(match.group("freq"))
    return None if value is None else ActivationCap(printed=value)


def _counted_board_cap(match: "re.Match[str]") -> "ActivationCap | None":
    """"…than the number of snow Swamps you control" (Withering Wisps).

    Unreadable noun phrase, no cap -- which leaves the clause unmatched and its
    card unsupported, rather than admitting a sentence whose number nothing can
    work out.
    """
    phrase = match.group("board")
    return ActivationCap(counted=phrase) if _counted_board_phrase(phrase) else None


#: "…no more times each turn than the number of **snow Swamps you control**."
#: The noun phrase is payload for the reason every printed noun phrase in this
#: file is: a card counting Islands prints this clause, not a new one.
_COUNTED_LIMIT = (
    r"^activate no more times each turn than the number of "
    r"(?P<board>.+) you control$"
)


#: The clause shapes that cap how often one permanent's ability may be activated
#: in a turn, as ``(pattern, build)``. Read by
#: :func:`printed_activation_caps`, which is the *only* answer to "is this line
#: capped, and by what" -- the refusal, the tally and the rows below all come
#: through it.
_ACTIVATION_LIMIT_SHAPES: tuple[
    tuple["re.Pattern[str]", "Callable[[re.Match[str]], ActivationCap | None]"], ...
] = (
    # The bare clause (Dream Coat) and the tail on a timing clause (Instill
    # Energy's "during your turn and only once each turn", Gate to Phyrexia's
    # upkeep one). Searched rather than anchored because the tail really is one.
    (re.compile(r"once each turn"), lambda match: ActivationCap(printed=1)),
    (
        re.compile(r"^activate no more than " + _PRINTED_FREQUENCY + r" each turn$"),
        _printed_frequency_cap,
    ),
    (re.compile(_COUNTED_LIMIT), _counted_board_cap),
    # "Activate only **once**." (Goblin Ski Patrol.) Anchored where the row at
    # the top of this tuple is searched, and that is the whole difference
    # between the two sentences: "once each turn" is a cap that comes back every
    # turn and this one never does. Anchoring is what keeps this row off Dream
    # Coat's clause, and the missing "each turn" is what keeps that row off this
    # one.
    (re.compile(r"^activate only once$"),
     lambda match: ActivationCap(printed=1, lifetime=True)),
)


def printed_activation_caps(ability_text: str) -> tuple[ActivationCap, ...]:
    """Every per-turn cap this printed ability line states.

    Text only, and the question the *tally* asks: an activation is counted
    because the line is capped, whatever the cap works out to on the board at
    the time. An empty tuple is every ability in the pool but these.
    """
    caps: list[ActivationCap] = []
    for clause in _clauses(ability_text):
        for pattern, build in _ACTIVATION_LIMIT_SHAPES:
            found = pattern.search(clause)
            if found is None:
                continue
            cap = build(found)
            if cap is not None:
                caps.append(cap)
    return tuple(caps)


def activations_allowed_each_turn(
    ability_text: str, game=None, controller_index: int | None = None, source=None
) -> int | None:
    """How many times a turn this ability line may be activated *right now*.

    ``None`` is not zero and not one: it means nothing here bounds the line --
    either it prints no cap at all, or the only cap it prints is counted off a
    board this caller did not name. :func:`printed_activation_caps` is the
    question to ask when what you need is whether the line is capped.

    The lowest cap wins when a line states more than one, because two caps on
    one line are both true.
    """
    limits = [
        value
        # A lifetime cap is not a per-turn one and this function's name is the
        # contract: folding "only once" in here would report Goblin Ski Patrol
        # as a once-a-turn ability, which is what the denial message beside the
        # caller would then say. :func:`at_activation_limit` is where both kinds
        # are compared, each against its own tally.
        for cap in printed_activation_caps(ability_text) if not cap.lifetime
        if (value := cap.resolve(game, controller_index, source)) is not None
    ]
    return min(limits) if limits else None


def activations_this_turn(game: "Game", source) -> int:
    """How many capped activations *source* has already made this turn.

    The one read of the tally :func:`mark_activated_this_turn` writes, shared by
    the rows below and by `mixins/stack/activation_checks.py`'s refusal -- so the key is
    spelled once and the two cannot drift. A permanent that is gone has made
    none (CR 400.7: what comes back is a new object).
    """
    if source is None:
        return 0
    tally = source.metadata.get(ACTIVATION_TALLY_MARK)
    if not isinstance(tally, dict) or tally.get("turn") != game.turn:
        return 0
    return int(tally.get("count", 0))


def activations_ever(game: "Game", source) -> int:
    """How many capped activations *source* has made since it entered.

    The turn-free twin of :func:`activations_this_turn`, off the same stamp:
    "Activate only once" is a cap on the permanent, and CR 400.7 makes a
    permanent that left and returned a different one — so a fresh object with
    no metadata has made none, which is the rule rather than a shortcut.
    """
    if source is None:
        return 0
    tally = source.metadata.get(ACTIVATION_TALLY_MARK)
    if not isinstance(tally, dict):
        return 0
    return int(tally.get("ever", 0))


def already_activated_this_turn(game: "Game", source) -> bool:
    """Whether *source* has used a capped ability at all this turn."""
    return activations_this_turn(game, source) >= 1


def already_activated_ever(game: "Game", source) -> bool:
    """Whether *source* has used a capped ability at all since it entered."""
    return activations_ever(game, source) >= 1


def at_activation_limit(
    game: "Game", controller_index: int, source, ability_text: str
) -> bool:
    """Whether this line's per-turn cap is already spent.

    Asked of the line, the seat and the permanent together: the cap is stated on
    the line, a counted one is measured on the seat's board, and the tally is
    state on the permanent.
    """
    for cap in printed_activation_caps(ability_text):
        limit = cap.resolve(game, controller_index, source)
        if limit is None:
            continue
        # Each cap against its own tally. A single ``min`` over both kinds was
        # the shape before "only once" existed, and it cannot survive one: a
        # lifetime cap of 1 compared against the per-turn count would come back
        # unspent every new turn, which is the ability working more often than
        # the card allows — this module's own failure mode.
        spent = (
            activations_ever(game, source) if cap.lifetime
            else activations_this_turn(game, source)
        )
        if spent >= limit:
            return True
    return False


def _not_yet_activated_this_turn(game: "Game", controller_index: int, source) -> bool:
    """"Activate only once each turn." (Dream Coat.)

    Per-*permanent* state, so the source is what answers -- and a source that is
    gone answers yes, for the mirror of the reason
    `_controlled_since_your_last_turn` answers no: there is no permanent to have
    already used its ability.
    """
    return not already_activated_this_turn(game, source)


def _not_yet_activated_ever(game: "Game", controller_index: int, source) -> bool:
    """"Activate only once." (Goblin Ski Patrol.)

    Per-*permanent* state with no turn on it, so it answers off the lifetime
    half of the tally — and a source that is gone answers yes for the reason
    `_not_yet_activated_this_turn` does: there is no permanent to have used its
    ability.
    """
    return not already_activated_ever(game, source)


def _below_printed_activation_limit(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate no more than twice each turn." (Vampire Bats.)

    The number is read off the match, so this row is every printed frequency of
    the clause rather than the one Legends happens to print. A frequency the
    reader above cannot turn into a number never reaches here: the pattern only
    delimits the word, and an unreadable one leaves the clause unmatched and its
    card unsupported.
    """
    cap = _printed_frequency_cap(match)
    limit = None if cap is None else cap.resolve(game, controller_index, source)
    return limit is not None and activations_this_turn(game, source) < limit


def _below_counted_activation_limit(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate no more times each turn than the number of snow Swamps you
    control." (Withering Wisps.)

    The board is the number, so the cap is re-measured at every activation
    rather than fixed when the permanent entered: a Swamp that arrives between
    two activations raises it, and one that leaves lowers it. Both readings
    come through :class:`ActivationCap`, so this refusal and the tally beside it
    cannot disagree about how many the seat is allowed.
    """
    cap = _counted_board_cap(match)
    limit = None if cap is None else cap.resolve(game, controller_index, source)
    return limit is not None and activations_this_turn(game, source) < limit


#: The metadata key a **once-only** activation tallies on its permanent, keyed
#: by the printed ability line rather than by the turn.
#:
#: "Until end of turn, target creature gains haste and "{0}: Untap this
#: creature. Activate only once."" (Touch of Vitae.) The clause beside it in
#: this file -- "Activate only once each turn" -- is a per-turn budget and
#: `ACTIVATION_TALLY_MARK` holds it; this one is not bounded by a turn at all,
#: so a tally that reset with the turn would be a restriction the card does not
#: have. It is per *line* rather than per permanent because CR 602.5c says the
#: budget belongs to the ability as acquired, not to the object: a permanent
#: holding two differently worded once-only abilities has two of them.
ONCE_ONLY_TALLY_MARK = "once_only_ability_activations"

#: The clause itself, spelled once. The table's row
#: (``activation_restrictions.ACTIVATION_RESTRICTIONS``) matches it and
#: :func:`prints_once_only_restriction` asks the write site about it, so the
#: refusal and the tally cannot come to disagree about which lines are budgeted
#: -- the same arrangement `printed_activation_caps` makes for the per-turn cap.
_ONCE_ONLY_CLAUSE = re.compile(r"^activate only once$")


def _once_only_key(ability_text: str) -> str:
    """One spelling of an ability line, for comparing two of them.

    The granted-ability channel's normalization, imported rather than restated:
    the line this tally is keyed by is the line `Permanent.effective_card`
    folded in, and two spellings of "the same sentence" is how a budget comes to
    be spent against a line nobody activated.
    """
    from .keywords import normalized_ability_line

    return normalized_ability_line(ability_text)


def prints_once_only_restriction(ability_text: str) -> bool:
    """Whether *ability_text* prints "Activate only once"."""
    return any(
        _ONCE_ONLY_CLAUSE.match(clause.rstrip("."))
        for clause in _clauses(ability_text)
    )


def once_only_activations(source, ability_text: str) -> int:
    """How many times this once-only line has already been activated."""
    if source is None:
        return 0
    tally = source.metadata.get(ONCE_ONLY_TALLY_MARK)
    if not isinstance(tally, dict):
        return 0
    return int(tally.get(_once_only_key(ability_text), 0))


def mark_once_only_activation(source, ability_text: str) -> None:
    """Spend this line's one use."""
    if source is None:
        return
    key = _once_only_key(ability_text)
    tally = source.metadata.setdefault(ONCE_ONLY_TALLY_MARK, {})
    tally[key] = int(tally.get(key, 0)) + 1


def clear_once_only_tally(source, ability_text: str) -> None:
    """Give this line a fresh use budget (CR 602.5c).

    Called when the line is *granted*, not when it is activated: the rule says a
    restriction on an acquired ability applies "only to that ability as acquired
    from that object", so a second grant of the same sentence is a second
    ability with a budget of its own. Without this, a creature enchanted by two
    Touch of Vitae in different turns would untap once and refuse forever after.

    Two grants of the same line standing at once share the one budget, which is
    stricter than the rule and never looser -- the direction a missing
    restriction must never fail in.
    """
    if source is None:
        return
    tally = source.metadata.get(ONCE_ONLY_TALLY_MARK)
    if isinstance(tally, dict):
        tally.pop(_once_only_key(ability_text), None)
        if not tally:
            source.metadata.pop(ONCE_ONLY_TALLY_MARK, None)


def _not_yet_activated_at_all(
    game: "Game", controller_index: int, source, ability_text: str
) -> bool:
    """"Activate only once." (Touch of Vitae's granted ability.)

    Per-*line* state on the permanent, so a control change carries it
    (CR 602.5b) and a differently worded ability on the same permanent keeps its
    own budget (CR 602.5c). A source that is gone has spent nothing, for the
    reason `_not_yet_activated_this_turn` gives one clause up.
    """
    return once_only_activations(source, ability_text) < 1


#: The lowered condition kind that *reads* the per-turn tally rather than
#: bounding it: "If this ability has been activated four or more times this
#: turn, …" (Farrelite Priest, Initiates of the Ebon Hand). Spelled once,
#: because `engine/grammar/lowering/conditions.py` writes it and
#: :func:`reads_activation_tally` looks for it.
ACTIVATION_TALLY_CONDITION = "source_ability_activations"


def reads_activation_tally(instruction) -> bool:
    """Whether this compiled ability asks how often it has been activated.

    The other half of :func:`mark_activated_this_turn`'s question. A cap is a
    *refusal* and is read off the printed clause; this is an ability that reads
    the same ledger as an ordinary effect, and one that is not tallied would
    find it empty on every activation and never fire its drawback — supported,
    silent, and free.

    Asked of the **compiled program**, not of the printed words. The grammar has
    already read that sentence once; a regex here would be a second reader of
    it, free to disagree about a printing neither author had in mind. Walking
    the payload for nested instructions rather than a list of the keys that hold
    them is the same choice for the same reason — a key list is a list that goes
    stale, and every value that *is* an instruction is one wherever it sits.
    """
    from .oracle_types import OracleInstruction

    if not isinstance(instruction, OracleInstruction):
        return False
    payload = instruction.payload or {}
    if instruction.kind == "if_then":
        condition = payload.get("condition") or {}
        if condition.get("kind") == ACTIVATION_TALLY_CONDITION:
            return True
    for value in payload.values():
        if isinstance(value, OracleInstruction):
            if reads_activation_tally(value):
                return True
        elif isinstance(value, (tuple, list)):
            for item in value:
                # A `choose_one` carries its alternatives as dicts with the
                # instruction under a key, so both shapes are walked.
                nested = (
                    item.get("instruction") if isinstance(item, dict) else item
                )
                if reads_activation_tally(nested):
                    return True
    return False


def mark_activated_this_turn(game: "Game", source) -> None:
    """Tally one activation of a permanent whose ability prints a per-turn cap
    or reads the per-turn count."""
    if source is None:
        return
    already = activations_this_turn(game, source)
    source.metadata[ACTIVATION_TALLY_MARK] = {
        "turn": game.turn, "count": already + 1,
        # Written by the same stamp rather than by a second one: the two numbers
        # are the same activation counted two ways, and a caller that had to
        # remember both would eventually remember one.
        "ever": activations_ever(game, source) + 1,
    }


__all__ = [
    "ACTIVATION_TALLY_MARK",
    "ACTIVATION_TALLY_CONDITION",
    "reads_activation_tally",
    "ONCE_ONLY_TALLY_MARK",
    "clear_once_only_tally",
    "mark_once_only_activation",
    "once_only_activations",
    "prints_once_only_restriction",
    "ActivationCap",
    "activations_ever",
    "already_activated_ever",
    "already_activated_this_turn",
    "at_activation_limit",
    "mark_activated_this_turn",
    "printed_activation_caps",
]
