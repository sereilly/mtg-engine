"""Text-keyed activation restrictions ("Activate only ...", CR 602.5).

The twin of `engine/cast_restrictions.py`, and genuinely textual for the same
reason: the restriction reads the same for any card printed with the phrase, so
it is a table keyed by the printed clause rather than a per-card hook. The
activation path loops it once; a new restricted card is one entry, or none at
all when it prints a clause already here.

What this replaced was two hard-coded phrase checks inside
`mixins/stack/activation.py`, written for two LEA cards. Everything else printed
with the words was **unenforced** -- Caged Zombie's "Activate only if a creature
died this turn" let its controller drain two life on an empty graveyard, and the
card still reported supported, because an unenforced restriction is not a dead
ability. It is an ability that works more often than the card allows, which is
the harder failure to see: nothing crashes, nothing is missing, the game is just
wrong in the player's favour.

Two things follow and are load-bearing:

* **The support gate reads this same table**, so a clause it cannot read makes
  the card unsupported rather than supported-and-unenforced. Every derivation
  table in this engine is arranged that way, and the failure above is why.
* **A clause is matched whole.** Each pattern is anchored, so "Activate only if
  you control a creature with flying" cannot be satisfied by a rule written for
  "Activate only if you control a creature": a restriction matching a prefix
  would be a *weaker* restriction wearing the card's words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game
    from .models import Permanent

#: (game, controller_index, source) -> True when activating is currently legal.
ActivationPredicate = Callable[["Game", int, "Permanent | None"], bool]

#: The same, plus the clause's own match. A clause whose *parameters* are
#: printed -- which step, how many counters of which word -- has to read them,
#: and reading them off the match is what keeps a parameter data instead of
#: baking it into the pattern and needing a row per printing. The same choice
#: `combat_restrictions.py` makes about its land type.
ParameterisedActivationPredicate = Callable[
    ["Game", int, "Permanent | None", "re.Match[str]"], bool
]


@dataclass(frozen=True)
class ActivationRestriction:
    """One printed clause, what it permits, and what to say when it does not."""

    pattern: "re.Pattern[str]"
    is_legal: "ActivationPredicate | ParameterisedActivationPredicate"
    denial: str
    #: Whether `is_legal` takes the match as a fourth argument. Declared rather
    #: than sniffed: a signature guessed by introspection is a signature that
    #: silently stops being guessed right.
    reads_payload: bool = False


def _as_a_sorcery(game: "Game", controller_index: int, source) -> bool:
    """CR 601.3d's timing: your own main phase, with an empty stack."""
    return (
        game.active_player_index == controller_index
        and game.current_turn_phase in ("precombat_main", "postcombat_main")
        and not game.stack
    )


def _a_creature_died_this_turn(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if a creature died this turn." (Caged Zombie.)

    Any creature, anyone's -- the printed phrase says "a creature", where the
    per-seat tally beside it says "under your control". Reading the narrower one
    would refuse an activation the card allows.
    """
    return int(getattr(game, "creatures_died_this_turn", 0) or 0) > 0


def _control_a_creature_with_flying(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if you control a creature with flying." (Celestial
    Enforcer.)

    Through `is_creature` and `has_keyword`, not the printed line: a granted
    flying counts (CR 613 layer 6) and an animated land is a creature.
    """
    return any(
        perm.is_creature and perm.has_keyword("flying")
        for perm in game.controlled_by(controller_index)
    )


def _seven_life_above_starting(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if you have at least 7 life more than your starting life
    total and only as a sorcery." (Speaker of the Heavens.)

    Both halves, because the card prints both -- the life comparison *and* the
    sorcery timing. Reading one would be a restriction the card does not have.
    """
    player = game.players[controller_index]
    starting = int(getattr(game, "starting_life_total", 20) or 20)
    return player.life >= starting + 7 and _as_a_sorcery(game, controller_index, source)


def _during_any_upkeep(game: "Game", controller_index: int, source) -> bool:
    """"Only during any upkeep step." (Armageddon Clock.) A window scoped to a
    *step* rather than to a player's own step -- the "any player may activate"
    permission is a separate question, and the two together are what let an
    opponent wind the Clock back down."""
    return game.current_step == "upkeep"


def _during_your_upkeep(game: "Game", controller_index: int, source) -> bool:
    """Cyclopean Tomb, the Clockwork creatures, Rock Hydra's pump."""
    return game.current_step == "upkeep" and game.active_player_index == controller_index


def _during_your_turn(game: "Game", controller_index: int, source) -> bool:
    """Disrupting Scepter, Instill Energy. The "only once each turn" half of
    Instill Energy's clause is *not* here: it is per-permanent state, not a
    property of the game, and it stays where that state lives."""
    return game.active_player_index == controller_index


def _during_combat(game: "Game", controller_index: int, source) -> bool:
    """Jade Statue."""
    return game.current_turn_phase == "combat"


def _during_declare_blockers(game: "Game", controller_index: int, source) -> bool:
    """Lesser Werewolf. A window scoped to a *step* and to neither player's
    turn: blockers are declared on the defending player's behalf during the
    attacker's turn, so the seat is not part of the question."""
    return game.current_step == "declare_blockers"


def _during_end_of_combat(game: "Game", controller_index: int, source) -> bool:
    """Desert."""
    return game.current_step == "end_of_combat"


def _opponents_turn_before_attackers(game: "Game", controller_index: int, source) -> bool:
    """Nettling Imp -- the same window `cast_restrictions.py` reads for the same
    printed phrase."""
    if game.active_player_index == controller_index:
        return False
    if game.current_turn_phase in ("beginning", "precombat_main"):
        return True
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
        and not game.combat_attackers_locked
    )


def _exactly_seven_cards_in_hand(game: "Game", controller_index: int, source) -> bool:
    """Library of Alexandria's draw ability."""
    return len(game.players[controller_index].hand) == 7


def _controlled_since_your_last_turn(game: "Game", controller_index: int, source) -> bool:
    """Rocket Launcher. "Continuously since the beginning of your most recent
    turn" is a property of the *permanent*, so the source is what answers -- and
    a source that is gone answers no."""
    if source is None:
        return False
    return bool(game._controlled_since_turn_start(source))


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


#: The clause shapes that cap how often one permanent's ability may be activated
#: in a turn, as ``(pattern, group)``. The bare "once" spellings carry no group
#: and mean one; the "no more than" spelling names its own number. Read by
#: :func:`activations_allowed_each_turn`, which is the *only* answer to "is this
#: line capped, and at what" -- the refusal, the tally and the rows below all
#: come through it.
_ACTIVATION_LIMIT_SHAPES: tuple[tuple["re.Pattern[str]", "str | None"], ...] = (
    # The bare clause (Dream Coat) and the tail on a timing clause (Instill
    # Energy's "during your turn and only once each turn", Gate to Phyrexia's
    # upkeep one). Searched rather than anchored because the tail really is one.
    (re.compile(r"once each turn"), None),
    (re.compile(r"^activate no more than " + _PRINTED_FREQUENCY + r" each turn$"), "freq"),
)


def activations_allowed_each_turn(ability_text: str) -> int | None:
    """How many times a turn this printed ability line may be activated.

    ``None`` is not zero and not one: it means the card prints no cap at all,
    which is every ability in the pool but these. The lowest cap wins when a
    line prints more than one, because two caps on one line are both true.

    `mixins/stack/activation.py` asks this both to refuse an activation past the
    cap and to tally the ones it allows, so the rows below and the tally cannot
    disagree about which lines are limited or about how limited they are.
    """
    limits: list[int] = []
    for clause in _clauses(ability_text):
        for pattern, group in _ACTIVATION_LIMIT_SHAPES:
            found = pattern.search(clause)
            if found is None:
                continue
            value = 1 if group is None else _frequency_value(found.group(group))
            if value is not None:
                limits.append(value)
    return min(limits) if limits else None


def activations_this_turn(game: "Game", source) -> int:
    """How many capped activations *source* has already made this turn.

    The one read of the tally :func:`mark_activated_this_turn` writes, shared by
    the rows below and by `mixins/stack/activation.py`'s refusal -- so the key is
    spelled once and the two cannot drift. A permanent that is gone has made
    none (CR 400.7: what comes back is a new object).
    """
    if source is None:
        return 0
    tally = source.metadata.get(ACTIVATION_TALLY_MARK)
    if not isinstance(tally, dict) or tally.get("turn") != game.turn:
        return 0
    return int(tally.get("count", 0))


def already_activated_this_turn(game: "Game", source) -> bool:
    """Whether *source* has used a capped ability at all this turn."""
    return activations_this_turn(game, source) >= 1


def at_activation_limit(game: "Game", source, ability_text: str) -> bool:
    """Whether this line's printed per-turn cap is already spent.

    Asked of the line and the permanent together, because the cap is printed on
    the line and the tally is state on the permanent.
    """
    limit = activations_allowed_each_turn(ability_text)
    return limit is not None and activations_this_turn(game, source) >= limit


def _not_yet_activated_this_turn(game: "Game", controller_index: int, source) -> bool:
    """"Activate only once each turn." (Dream Coat.)

    Per-*permanent* state, so the source is what answers -- and a source that is
    gone answers yes, for the mirror of the reason
    `_controlled_since_your_last_turn` answers no: there is no permanent to have
    already used its ability.
    """
    return not already_activated_this_turn(game, source)


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
    limit = _frequency_value(match.group("freq"))
    return limit is not None and activations_this_turn(game, source) < limit


def mark_activated_this_turn(game: "Game", source) -> None:
    """Tally one activation of a permanent whose ability prints a per-turn cap."""
    if source is None:
        return
    already = activations_this_turn(game, source)
    source.metadata[ACTIVATION_TALLY_MARK] = {
        "turn": game.turn, "count": already + 1,
    }


def _turn_positions() -> dict[str, int]:
    """Every step of a turn, printed name -> how far through the turn it is.

    Built from the engine's own turn structure rather than listed here, so a
    step this engine grows is orderable the moment it exists and a step it does
    not have cannot be named by a card this table admits. The printed spelling
    is the step key with its underscores opened out -- "combat damage", "end of
    combat" -- which is how the CR prints them.
    """
    from .mixins._constants import _PHASE_STEPS, _TURN_PHASES

    positions: dict[str, int] = {}
    for phase in _TURN_PHASES:
        for step in _PHASE_STEPS.get(phase, (phase,)):
            positions.setdefault(step.replace("_", " "), len(positions))
    return positions


_TURN_POSITIONS = _turn_positions()


def _current_turn_position(game: "Game") -> int | None:
    step = str(getattr(game, "current_step", "") or "").replace("_", " ")
    return _TURN_POSITIONS.get(step)


def _before_step(game: "Game", controller_index: int, source, match) -> bool:
    """"Activate only before the combat damage step." (Angus Mackenzie.)

    A window bounded by a *point in the turn* and by neither player's seat:
    Angus prevents all combat damage this turn, and the damage it is racing is
    dealt on whichever turn it is -- the same reason the seat is not part of
    `_during_declare_blockers`.

    The step is payload. A card printed "only before the end step" needs no code
    here, and a card printed with a step this engine does not have never reaches
    this predicate at all: the pattern is built from the same turn structure, so
    an unreadable step leaves the clause unmatched and its card unsupported.
    """
    here = _current_turn_position(game)
    if here is None:
        return False
    return here < _TURN_POSITIONS[match.group("step")]


def _at_least_that_many_counters(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if there are two or more hatchling counters on this
    artifact." (Triassic Egg.)

    Number and counter word are both payload, read off the match: the sentence
    is the same sentence with any other word in it, and `named_counters` already
    stores an invented kind without knowing which. Asked of the *source*,
    because "on this artifact" names the permanent carrying the ability -- and a
    source that has left answers no, a permanent that is gone having no counters
    (CR 400.7).
    """
    from .grammar.vocabulary import NUMBER_WORDS
    from .named_counters import counters_on

    if source is None:
        return False
    needed = NUMBER_WORDS.get(match.group("count"))
    if needed is None:
        return False
    return counters_on(source, match.group("counter")) >= needed


#: Matched whole, and no pattern is a prefix of another -- held by
#: `tests/rules/test_activation_restrictions.py`.
ACTIVATION_RESTRICTIONS: tuple[ActivationRestriction, ...] = (
    ActivationRestriction(
        re.compile(r"^activate only if a creature died this turn$"),
        _a_creature_died_this_turn,
        "no creature died this turn",
    ),
    ActivationRestriction(
        re.compile(r"^activate only if you control a creature with flying$"),
        _control_a_creature_with_flying,
        "you control no creature with flying",
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if you have at least 7 life more than your "
            r"starting life total and only as a sorcery$"
        ),
        _seven_life_above_starting,
        "you need 7 life above your starting total, and sorcery timing",
    ),
    ActivationRestriction(
        re.compile(r"^activate only as a sorcery$"),
        _as_a_sorcery,
        "this ability is sorcery-speed",
    ),
    # --- the eight the shipped pool already printed --------------------------
    # These were a hand-written if-chain in `mixins/stack/activation.py`, each
    # branch a substring test against the ability line. They are here now for
    # the reason this module exists: one declaration per printed clause, read by
    # the activation path *and* by the support gate, so a clause nobody enforces
    # cannot also report as understood.
    ActivationRestriction(
        # Both printed spellings of one clause. Armageddon Clock drops the verb
        # ("Any player may activate this ability but only during any upkeep
        # step"), Tolaria keeps it ("Activate only during any upkeep step") —
        # and the verbless spelling was the only one here, so Tolaria's ability
        # was **unenforced**: usable in any step, with nothing to notice. That
        # is the failure this module was written for, arriving on the second
        # card to print the clause.
        re.compile(r"^(?:activate )?only during any upkeep step$"),
        _during_any_upkeep,
        "only during an upkeep step",
    ),
    ActivationRestriction(
        # "…**and only once each turn**" (Gate to Phyrexia) is the same optional
        # tail the "your turn" row below carries, and for the same reason: the
        # once-a-turn half is per-permanent state rather than a property of the
        # game, so it stays in mixins/stack/activation.py where that state lives
        # and this row reads the timing half. Without the tail the whole clause
        # matched nothing and the timing went unenforced.
        re.compile(r"^activate only during your upkeep(?: and only once each turn)?$"),
        _during_your_upkeep,
        "only during your upkeep",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during your turn(?: and only once each turn)?$"),
        _during_your_turn,
        "only during your turn",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during the end of combat step$"),
        _during_end_of_combat,
        "only during the end of combat step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during the declare blockers step$"),
        _during_declare_blockers,
        "only during the declare blockers step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during combat$"),
        _during_combat,
        "only during combat",
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only during an opponent's turn, before attackers are declared$"
        ),
        _opponents_turn_before_attackers,
        "only during an opponent's turn, before attackers are declared",
    ),
    ActivationRestriction(
        re.compile(r"^activate only if you have exactly seven cards in hand$"),
        _exactly_seven_cards_in_hand,
        "only with exactly seven cards in hand",
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if you've controlled this artifact continuously "
            r"since the beginning of your most recent turn$"
        ),
        _controlled_since_your_last_turn,
        "only if you have controlled it since your most recent turn began",
    ),
    # --- the three Legends prints on their own -------------------------------
    # "Activate only once each turn" (Dream Coat) standing *alone*, where the
    # two rows above carry it as an optional tail. The refusal was already
    # enforced -- `mixins/stack/activation.py` substring-matched the words --
    # but the clause was unreadable *here*, which is the gate half: a card whose
    # only restriction is this sentence was admitted by a table that could not
    # say what the sentence means, and the next such card would inherit that.
    # Both halves ask `limits_to_once_each_turn` now.
    ActivationRestriction(
        re.compile(r"^activate only once each turn$"),
        _not_yet_activated_this_turn,
        "only once each turn",
    ),
    # "Activate no more than twice each turn." (Vampire Bats.) The *only* clause
    # in the pool that does not begin "Activate only", and the one that showed
    # `_clauses` was collecting by that prefix rather than by the verb: the
    # sentence was not a clause here, so the support gate had nothing to refuse
    # and the grammar consumed it verbatim -- a {B} pump with no cap at all,
    # supported, silent, and wrong in its controller's favour every turn. The
    # frequency is payload, so this row is "no more than <n> each turn".
    ActivationRestriction(
        re.compile(r"^activate no more than " + _PRINTED_FREQUENCY + r" each turn$"),
        _below_printed_activation_limit,
        "already activated as many times as it may be this turn",
        reads_payload=True,
    ),
    # "Activate only before the combat damage step." (Angus Mackenzie.) The step
    # alternation is built from the engine's own turn structure, so the step is
    # payload and a step the engine does not have leaves the clause unmatched.
    ActivationRestriction(
        re.compile(
            r"^activate only before the (?P<step>"
            + "|".join(sorted(map(re.escape, _TURN_POSITIONS), key=len, reverse=True))
            + r") step$"
        ),
        _before_step,
        "only before that step",
        reads_payload=True,
    ),
    # "Activate only if there are two or more hatchling counters on this
    # artifact." (Triassic Egg.) Number and counter word are both payload.
    ActivationRestriction(
        re.compile(
            r"^activate only if there are (?P<count>[a-z]+) or more "
            r"(?P<counter>[a-z]+) counters on this [a-z]+$"
        ),
        _at_least_that_many_counters,
        "not enough counters on it yet",
        reads_payload=True,
    ),
)


def _clauses(text: str) -> list[str]:
    """Every printed "Activate only ..." sentence in *text*.

    Sentences rather than lines: the clause is the tail of an ability line
    ("{1}{B}, {T}: Each opponent loses 2 life. Activate only if ..."), so a
    line-level reader would never see it on its own.
    """
    found: list[str] = []
    for raw_line in (text or "").splitlines():
        for sentence in raw_line.split("."):
            # Quotation marks are stripped with the whitespace, because a
            # sentence boundary can fall immediately after a closing quote:
            # "…gains "Remove a matrix counter from this creature: Regenerate
            # this creature." **Activate only during your upkeep.**" (Life
            # Matrix) prints its full stop *inside* the quotes, so the split
            # leaves the next sentence starting with the quote character. Left
            # in, the clause matched nothing and the timing went unenforced --
            # which is this module's own opening paragraph, in the one shape
            # anchoring the pattern cannot catch.
            cleaned = sentence.strip().strip('"“”').strip().lower()
            # "Any player may activate this ability **but** only during any
            # upkeep step." (Armageddon Clock.) The permission and the timing
            # share a sentence, joined by "but"; the tail is the restriction and
            # the head is a different rule, checked elsewhere. Split rather than
            # matched loosely, so the clause is still anchored at both ends.
            if " but only " in cleaned:
                cleaned = cleaned.split(" but only ", 1)[1].strip()
                cleaned = f"only {cleaned}"
            # "**Only** during any upkeep step" (Armageddon Clock) drops the
            # verb; every other printed clause keeps it. Both spellings are the
            # same kind of sentence, so both are collected.
            # By the **verb**, not by "activate only": "Activate no more than
            # twice each turn" (Vampire Bats) is the same kind of sentence and
            # the prefix test did not collect it, so neither the support gate
            # nor `activation_denial` ever saw it. Collecting it is what lets a
            # printed clause with no row here refuse its card instead of being
            # dropped.
            if cleaned.startswith("activate ") or cleaned.startswith("only during"):
                found.append(cleaned)
    return found


def activation_restriction_line(sentence: str) -> bool:
    """Whether one printed sentence is a restriction this module enforces.

    Read by the support gate and by `scripts/parse_coverage.py`, so what is
    enforced and what is claimed cannot drift.
    """
    cleaned = (sentence or "").strip().lower().rstrip(".")
    return any(entry.pattern.match(cleaned) for entry in ACTIVATION_RESTRICTIONS)


def unreadable_activation_clauses(oracle_text: str) -> list[str]:
    """The "Activate only ..." sentences this module does *not* implement.

    The support gate's question: a card with one of these is refused rather than
    admitted with the clause unenforced.
    """
    return [
        clause for clause in _clauses(oracle_text)
        if not activation_restriction_line(clause)
    ]


def activation_denial(game, controller_index: int, source, ability_text: str) -> str | None:
    """Why this activation is illegal, or None when it is not.

    *ability_text* is the whole printed ability line, because the clause is its
    tail. Only the clauses on *that* line apply: a permanent with two abilities
    prints its restrictions per ability, and testing the card's whole text would
    gate one ability with the other's rule.
    """
    for clause in _clauses(ability_text):
        cleaned = clause.rstrip(".")
        for entry in ACTIVATION_RESTRICTIONS:
            match = entry.pattern.match(cleaned)
            if match is None:
                continue
            legal = (
                entry.is_legal(game, controller_index, source, match)
                if entry.reads_payload
                else entry.is_legal(game, controller_index, source)
            )
            if not legal:
                return entry.denial
    return None


__all__ = [
    "ACTIVATION_RESTRICTIONS",
    "ONCE_EACH_TURN_MARK",
    "ActivationRestriction",
    "activation_denial",
    "activation_restriction_line",
    "already_activated_this_turn",
    "limits_to_once_each_turn",
    "mark_activated_this_turn",
    "unreadable_activation_clauses",
]
