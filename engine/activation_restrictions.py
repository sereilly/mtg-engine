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
* **A sentence conjoining restrictions is several restrictions**, split by
  `_conjuncts` and all of them required. CR 602.5 puts no limit on how many a
  clause states, and the cards print them as one sentence: "Activate only during
  combat **and only if** defending player controls a snow land" is two rules, and
  Grizzled Wolverine prints three. This was an optional
  ``(?: and only once each turn)?`` tail on three rows -- one row per *pairing*,
  which is quadratic in the clauses that exist and left Speaker of the Heavens as
  a single row reading two rules under one name. A conjunct no row reads makes
  the whole clause unreadable, so a card cannot be admitted with half its
  sentence enforced.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
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
    #: Whether the clause's *payload* is one this file can act on, asked of the
    #: match alone. A row whose capture ends in `.+` matches more sentences than
    #: it implements -- "controls a snow land" and "controls the highest life
    #: total" are one pattern -- and a clause admitted here with a phrase the
    #: predicate then cannot read would be a restriction that answers "no" for
    #: every board: silent over-restriction, which is this file's own failure
    #: mode pointed the other way. A row that declares one is unmatched where it
    #: says no, so its card is unsupported naming the sentence.
    payload_readable: "Callable[[re.Match[str]], bool] | None" = None


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


@lru_cache(maxsize=None)
def _controlled_board_phrase(phrase: str) -> "tuple[dict, bool] | None":
    """"a creature with flying" / "no snow lands" as ``(filter, present)``.

    The noun phrase is read by **the grammar's noun parser**, exactly as
    `static_bonuses._controls_noun_condition` reads the identical phrase after
    "as long as you control": `subject_matches` is what answers this clause at
    every activation, and a second reader of "a snow land" would be free to
    disagree with it about what a snow land is.

    The article is the quantifier and it is what the clause means: "**a** snow
    land" is a presence test and "**no** snow lands" its negation. Anything else
    -- "two or more", "three" -- is a threshold this does not read, and it
    refuses rather than answering as presence, because a threshold silently read
    as "at least one" is a restriction lifted on a board the card does not name.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    article, _, rest = phrase.strip().partition(" ")
    if article not in ("a", "an", "no") or not rest:
        return None
    stream = TokenStream(tokenize(rest).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload, article != "no"


def _readable_controlled_board(match: "re.Match[str]") -> bool:
    """Whether the noun phrase in a "controls …" clause is one this can test."""
    return _controlled_board_phrase(match.group("board")) is not None


@lru_cache(maxsize=None)
def _counted_board_phrase(phrase: str) -> "dict | None":
    """"snow Swamps" as a filter payload, for a clause that *counts* them.

    The plural twin of :func:`_controlled_board_phrase` and the same noun
    parser, because "a snow Swamp" and "snow Swamps" name the same set and a
    second reader of either would be free to disagree about what a snow Swamp
    is. What differs is only the quantifier: that one reads an article and
    answers presence, this one reads a bare plural and answers how many.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    stream = TokenStream(tokenize(phrase.strip()).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload


def _readable_counted_board(match: "re.Match[str]") -> bool:
    """Whether the noun phrase a counted cap is measured against is testable."""
    return _counted_board_phrase(match.group("board")) is not None


def _board_count(game: "Game", seat: int, source, phrase: str) -> int | None:
    """How many permanents *seat* controls that *phrase* names, or None.

    `subject_matches` answers the phrase, so a text-changed land type counts
    here as it counts everywhere, and CR 109.5's observer is the seat whose
    ability this is.
    """
    described = _counted_board_phrase(phrase)
    if described is None:
        return None
    from .subject_filters import subject_matches

    return sum(
        1
        for perm in game.controlled_by(seat)
        if subject_matches(
            game, perm, described, observer=seat, source=source
        )
    )


def _defending_seat(game: "Game") -> int | None:
    """The seat "defending player" names right now, or None when nothing does.

    CR 506.2 defines the defending player *during the combat phase*, so outside
    combat the clause has nothing to ask about and is unanswerable rather than
    vacuously true. ``_resolve_defending_player_index`` is the engine's one
    answer to "which single seat is defending": the other player in a duel, and
    in a CR 802 multi-defender combat only once exactly one opponent is under
    attack. A clause printed in the singular that no single seat answers refuses
    the activation -- the same direction `legality._enumerate_targets` takes for
    ``defending_player_only`` with no seat beside it, because a narrowing nobody
    can answer must never widen.
    """
    if getattr(game, "current_turn_phase", None) != "combat":
        return None
    return game._resolve_defending_player_index()


def _controls_the_printed_noun(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if you control a snow Mountain." (Goblin Ski Patrol.)
    "…only if defending player controls a snow land." (Arcum's Sleigh.)
    "…only if defending player controls no snow lands." (Kjeldoran Guard.)

    One row: the seat and the noun phrase are both payload, which is the same
    choice `combat_restrictions.py` makes about its land type and for the same
    reason -- a card printed with another seat, another noun or the other
    polarity is this clause, not a new one, and baking any of the three into the
    pattern made every variation a row, a predicate and a gate entry.

    `subject_matches` answers the phrase, so a text-changed land type (Magical
    Hack) counts here as it counts everywhere, and CR 109.5's observer is the
    *activating* seat even when the board being scanned is the defender's: "you"
    inside the noun phrase would mean the ability's controller.
    """
    read = _controlled_board_phrase(match.group("board"))
    if read is None:
        return False
    described, present = read
    if match.group("who") == "you":
        seat: int | None = controller_index
    else:
        seat = _defending_seat(game)
    if seat is None:
        return False
    from .subject_filters import subject_matches

    held = any(
        subject_matches(
            game, perm, described, observer=controller_index, source=source
        )
        for perm in game.controlled_by(seat)
    )
    return held is present


def _blocked_by_at_least(game: "Game", controller_index: int, source, match) -> bool:
    """"Activate only if at least one creature is blocking this creature."
    (Grizzled Wolverine.)

    ``creatures_blocking`` is the engine's one reader of that relation, so a
    band-propagated block (CR 702.22h) counts here exactly as it counts in the
    damage step. The number is payload; a source that has left the battlefield
    is blocked by nothing.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    if source is None:
        return False
    needed = NUMBER_WORDS.get(match.group("count"))
    if needed is None:
        return False
    return len(game.creatures_blocking(source)) >= needed


def _seven_life_above_starting(game: "Game", controller_index: int, source) -> bool:
    """"Activate only if you have at least 7 life more than your starting life
    total…" (Speaker of the Heavens.)

    The life half alone. The card prints "…and only as a sorcery" after it, and
    this used to read both halves because the clause arrived here whole; a
    conjoined clause is now split into the restrictions it conjoins, so the
    sorcery half is the sorcery row's business and this one stops being two
    rules with one name.
    """
    player = game.players[controller_index]
    starting = int(getattr(game, "starting_life_total", 20) or 20)
    return player.life >= starting + 7


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


def _before_attackers_are_declared(game: "Game", controller_index: int, source) -> bool:
    """Norritt -- the window on its own, with no seat attached.

    Split out of the pair below rather than duplicated, because the two clauses
    are one window and one extra condition: Nettling Imp prints "during an
    opponent's turn, before attackers are declared" and Norritt prints only the
    second half. Two predicates spelling the same window would be two answers to
    when attackers stop being declarable, and the one that was updated later
    would decide which card could be activated.
    """
    if game.current_turn_phase in ("beginning", "precombat_main"):
        return True
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
        and not game.combat_attackers_locked
    )


def _opponents_turn_before_attackers(game: "Game", controller_index: int, source) -> bool:
    """Nettling Imp -- the same window `cast_restrictions.py` reads for the same
    printed phrase, narrowed to an opponent's turn."""
    if game.active_player_index == controller_index:
        return False
    return _before_attackers_are_declared(game, controller_index, source)


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
        for cap in printed_activation_caps(ability_text)
        if (value := cap.resolve(game, controller_index, source)) is not None
    ]
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


def at_activation_limit(
    game: "Game", controller_index: int, source, ability_text: str
) -> bool:
    """Whether this line's per-turn cap is already spent.

    Asked of the line, the seat and the permanent together: the cap is stated on
    the line, a counted one is measured on the seat's board, and the tally is
    state on the permanent.
    """
    limit = activations_allowed_each_turn(
        ability_text, game, controller_index, source
    )
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


def _readable_cards_above(match) -> bool:
    """Whether the noun phrase in "…N or more <phrase> cards are above this
    card" is one this file can count.

    The same pairing every `.+` row here makes: the pattern matches more
    sentences than the predicate implements, so a phrase the card matcher
    cannot test leaves the clause unmatched and the card unsupported, rather
    than admitted with a restriction that answers "no" to every board.
    """
    from .grammar.vocabulary import NUMBER_WORDS

    if NUMBER_WORDS.get(match.group("count")) is None:
        return False
    return _cards_above_filter(match.group("kind")) is not None


@lru_cache(maxsize=None)
def _cards_above_filter(phrase: str) -> "dict | None":
    """"creature" / "creature card" as the search-filter payload that tests one
    card in a graveyard.

    Read by `search_filters.search_matches`, which is the engine's one answer to
    "may this card be found", and the only reader that works on a card in a
    hidden or open zone at all: CR 613.1 gives a card outside the battlefield no
    computed characteristics, so the printed type line is the whole of what
    there is to ask. A phrase it cannot test returns None and the clause goes
    unmatched.
    """
    word = " ".join((phrase or "").strip().lower().split())
    # One card type and nothing else, spelled the way `search_matches` takes it.
    # Widening this means widening what that predicate can answer, and the two
    # are one change.
    if word in ("creature", "artifact", "enchantment", "instant", "sorcery", "land"):
        return {"card_type": word}
    return None


def _enough_cards_above_in_graveyard(
    game: "Game", controller_index: int, source, match
) -> bool:
    """"Activate only if three or more creature cards are above this card."
    (Ashen Ghoul.)

    CR 404.1 makes a graveyard an ordered pile and puts each arriving card *on
    top* of it, so "above this card" names the cards that got there later. The
    engine appends, so those are the entries at a higher index -- and the index
    is found by **identity**, because two copies of one card in a graveyard are
    literally the same immutable ``CardDefinition`` and a name or value match
    finds whichever copy is first.

    *source* is the card itself rather than a permanent: this clause only ever
    appears on an ability that functions from a graveyard (CR 113.6m), where
    there is no permanent to be the source. A permanent reaching here answers
    False, which is the honest reading -- a card on the battlefield has nothing
    above it in any graveyard.
    """
    from .grammar.vocabulary import NUMBER_WORDS
    from .search_filters import search_matches

    needed = NUMBER_WORDS.get(match.group("count"))
    described = _cards_above_filter(match.group("kind"))
    if source is None or needed is None or described is None:
        return False
    graveyard = game.players[controller_index].graveyard
    for index, held in enumerate(graveyard):
        if held is source:
            above = graveyard[index + 1:]
            return sum(1 for card in above if search_matches(card, described)) >= needed
    return False


#: Matched whole, and no pattern is a prefix of another -- held by
#: `tests/rules/test_activation_restrictions.py`.
ACTIVATION_RESTRICTIONS: tuple[ActivationRestriction, ...] = (
    ActivationRestriction(
        re.compile(r"^activate only if a creature died this turn$"),
        _a_creature_died_this_turn,
        "no creature died this turn",
    ),
    ActivationRestriction(
        # "Activate only if **you control** a creature with flying" (Celestial
        # Enforcer), "…**defending player controls** a snow land" (Arcum's
        # Sleigh), "…**no** snow lands" (Kjeldoran Guard). One row where the
        # first of those was a row with a hand-written predicate: the seat, the
        # noun phrase and the polarity are all payload, so the next card to
        # print the clause about another board or another noun costs nothing.
        # The phrase is read by the grammar's noun parser and validated here —
        # a row ending in `.+` that admitted a phrase its predicate could not
        # read would refuse every activation, silently.
        re.compile(
            r"^activate only if (?P<who>you|defending player) controls? (?P<board>.+)$"
        ),
        _controls_the_printed_noun,
        "that clause's board condition is not met",
        reads_payload=True,
        payload_readable=_readable_controlled_board,
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if at least (?P<count>\w+) creatures? "
            r"(?:is|are) blocking this creature$"
        ),
        _blocked_by_at_least,
        "not enough creatures are blocking it",
        reads_payload=True,
    ),
    ActivationRestriction(
        re.compile(
            r"^activate only if you have at least 7 life more than your "
            r"starting life total$"
        ),
        _seven_life_above_starting,
        "you need 7 life above your starting total",
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
        re.compile(r"^activate only during your upkeep$"),
        _during_your_upkeep,
        "only during your upkeep",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during your turn$"),
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
    # "Activate only before attackers are declared." (Norritt.) The same window
    # without the seat, and the reason it is a row here rather than an optional
    # tail on the one above: the two are different restrictions, not one clause
    # written two ways -- Norritt may point its own creature at an attack on its
    # controller's turn and Nettling Imp may not.
    ActivationRestriction(
        re.compile(r"^activate only before attackers are declared$"),
        _before_attackers_are_declared,
        "only before attackers are declared",
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
    # "Activate no more times each turn than the number of snow Swamps you
    # control." (Withering Wisps.) The second cap shape in the pool and the
    # first whose number is not printed anywhere on the card -- see
    # `ActivationCap`. The noun phrase is payload and is read by the grammar's
    # noun parser, so the clause is one row rather than one row per noun; a
    # phrase that parser cannot read leaves it unmatched, and the card is
    # unsupported naming the sentence rather than admitted with an uncapped
    # ability.
    ActivationRestriction(
        re.compile(_COUNTED_LIMIT),
        _below_counted_activation_limit,
        "already activated as many times as it may be this turn",
        reads_payload=True,
        payload_readable=_readable_counted_board,
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
    # "Activate only if three or more creature cards are above this card."
    # (Ashen Ghoul.) The one clause in the pool that asks about a graveyard's
    # *order*, and the only kind of clause that can: an ability functioning
    # from a graveyard (CR 113.6m) is printed on a card that is itself in the
    # pile. Number and noun are payload, like every other row here.
    ActivationRestriction(
        re.compile(
            r"^activate only if (?P<count>[a-z]+) or more (?P<kind>.+?) cards "
            r"are above this card$"
        ),
        _enough_cards_above_in_graveyard,
        "not enough cards are above it in the graveyard",
        reads_payload=True,
        payload_readable=_readable_cards_above,
    ),
)


#: Where one printed sentence stops being one restriction. "Activate only during
#: combat **and only** if defending player controls a snow land" and "Activate
#: only during the declare blockers step**, only** if at least one creature is
#: blocking this creature**, and only** once each turn" are lists, joined the
#: three ways English joins them. The lookahead is what keeps the comma in
#: "Activate only during an opponent's turn, before attackers are declared" from
#: being a separator: only a comma or "and" *followed by another "only"* opens a
#: new conjunct.
_CONJUNCTION = re.compile(r",?\s+and\s+(?=only\b)|,\s+(?=only\b)")


def _conjuncts(clause: str) -> list[str]:
    """One printed restriction sentence as the restrictions it conjoins.

    CR 602.5 puts no limit on how many restrictions a clause states, and the
    cards print them as one sentence: every conjunct is a rule of its own, and
    the activation is legal only when all of them are.

    This replaced an optional ``(?: and only once each turn)?`` tail on three
    rows -- one row per *pairing*, which is quadratic in the clauses that exist
    and left "Activate only if you have at least 7 life more than your starting
    life total and only as a sorcery" as a single row reading two rules under
    one name. A conjunct that no row reads leaves the whole clause unreadable,
    so a card cannot be admitted with half its sentence enforced.

    The verb travels to the tail: the conjuncts after the first are printed
    without it ("…and only if…"), and every pattern here is anchored on the
    sentence as it would be printed alone.

    **Punctuation is normalised here because two callers spell it differently.**
    `_clauses` splits the printed text and keeps "step, only"; the grammar
    rebuilds the sentence by joining its tokens and produces "step , only", the
    comma having been a token of its own. The rows are written the printed way,
    so a clause with a comma in it matched from one caller and not the other --
    latent until now only because Nettling Imp, the single shipped card printing
    one, is unsupported for reasons three sentences earlier.
    """
    cleaned = re.sub(r"\s+([,;])", r"\1", " ".join((clause or "").split()))
    parts = [part for part in _CONJUNCTION.split(cleaned) if part]
    if len(parts) < 2:
        return [cleaned] if cleaned else []
    verb = "activate " if parts[0].startswith("activate ") else ""
    return [parts[0]] + [verb + part for part in parts[1:]]


def _matching_entry(clause: str) -> "tuple[ActivationRestriction, re.Match[str]] | None":
    """The one row that reads *clause*, with its match, or None.

    One lookup for the gate and the enforcement, so a clause the gate calls
    readable is the same clause -- and the same row -- the activation path then
    asks. They used to loop the table separately, which is two answers to "which
    rule is this sentence?" waiting to differ.
    """
    for entry in ACTIVATION_RESTRICTIONS:
        match = entry.pattern.match(clause)
        if match is None:
            continue
        if entry.payload_readable is not None and not entry.payload_readable(match):
            continue
        return entry, match
    return None


def _clauses(text: str) -> list[str]:
    """Every printed "Activate only ..." restriction in *text*, one per rule.

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
                # Split here rather than at each of the three call sites: the
                # gate, the enforcement and the per-turn cap all want the same
                # list, and a sentence conjoining two rules is two entries in it.
                found.extend(_conjuncts(cleaned))
    return found


def activation_restriction_line(sentence: str) -> bool:
    """Whether one printed sentence is a restriction this module enforces.

    Read by the support gate and by `scripts/parse_coverage.py`, so what is
    enforced and what is claimed cannot drift.

    **Every** conjunct, because a sentence conjoining two restrictions is two
    restrictions: reading one and consuming the line would leave the other
    unenforced, which is the failure this module was written for arriving
    through the joining word instead of through a missing row.
    """
    cleaned = (sentence or "").strip().lower().rstrip(".")
    conjuncts = _conjuncts(cleaned)
    return bool(conjuncts) and all(
        _matching_entry(clause) is not None for clause in conjuncts
    )


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
        found = _matching_entry(clause.rstrip("."))
        if found is None:
            continue
        entry, match = found
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
    "ActivationCap",
    "ActivationRestriction",
    "activation_denial",
    "activation_restriction_line",
    "already_activated_this_turn",
    "limits_to_once_each_turn",
    "mark_activated_this_turn",
    "printed_activation_caps",
    "unreadable_activation_clauses",
]
