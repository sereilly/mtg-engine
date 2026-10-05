"""Text-keyed casting restrictions ("Cast this spell only ...", CR 601.3).

These are genuinely textual (not name-keyed): the restriction is the same for
any card printed with the phrase, so a data table keyed by canonical phrase —
not a per-card hook — is the right extension point. cast_from_hand loops this
table once; a new timing-restricted card is one entry.

Two families, because two things can finish the sentence. Most of the pool
names a **moment** ("only during your declare attackers step"), which is a
whole phrase and a predicate over the turn structure. Blizzard names a
**board** instead — "Cast this spell only if you control a snow land" — and
there the noun phrase is payload: a card printed about an artifact, a creature
with flying or an opponent's Island is this restriction with one phrase
changed, so the phrase is read by the grammar's own noun parser and answered by
``subject_matches``, exactly as `activation_restrictions._controlled_board_phrase`
reads the identical clause after "Activate only if you control".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from .game import Game

# (game, caster_index) -> True if casting is currently legal.
TimingPredicate = Callable[["Game", int], bool]


@dataclass(frozen=True)
class CastRestriction:
    phrase: str                # canonical lowercase oracle-text phrase
    is_legal: TimingPredicate
    denial_message: str
    #: The seat this window **names**, for the printed "that player" that refers
    #: back to it. "Cast this spell only during an opponent's turn. Tap target
    #: creature **that player** controls." (Delirium.) The pronoun's antecedent
    #: is in the timing clause and nowhere else — the effect line that reads it
    #: produces no player of its own — so the table that owns the phrase is
    #: what says who it means.
    #:
    #: ``"active"`` is the only value today and the only one these phrases can
    #: have: every window naming a player names *whose turn or step it is*.
    #: None for a window that names nobody ("only before blockers are
    #: declared"), which is most of them.
    names_seat: str | None = None


def _during_own_declare_attackers(game: "Game", caster_index: int) -> bool:
    return game.current_step == "declare_attackers" and game.active_player_index == caster_index


def _during_declare_attackers(game: "Game", caster_index: int) -> bool:
    # Teleport: "the declare attackers step", not "your" — whoever is the
    # active player, the window is that step. The seat is deliberately not
    # consulted; the sibling above reads it because its own line says "your".
    return game.current_step == "declare_attackers"


def _before_blockers_are_declared(game: "Game", caster_index: int) -> bool:
    # Rapid Fire: no phase floor at all — anything earlier in the turn than the
    # declare blockers step qualifies, so the test is that the turn has not
    # reached it. (`_during_combat_before_blockers` is the *narrower* sibling:
    # its line says "during combat before blockers are declared", which adds a
    # combat-phase floor this one does not have.)
    #
    # The **step's arrival** is the deadline, not `combat_blockers_locked`, and
    # that is CR 509.1: blockers are declared as a turn-based action when the
    # step begins, before anybody receives priority. So no castable moment of
    # that step is "before blockers are declared".
    # `activation_restrictions._before_blockers_are_declared` reads the lock
    # instead, and the difference is deliberate rather than drift: this engine
    # declares blocks as an action inside the step, and the window between the
    # step opening and the declaration is one in which `_advance_combat_state`
    # starts no priority window at all — so the two readings differ only where
    # neither a spell nor an ability can actually be played.
    past_blockers = (
        game.current_turn_phase in ("postcombat_main", "ending")
        or (
            game.current_turn_phase == "combat"
            and game.current_step in ("declare_blockers", "combat_damage", "end_of_combat")
        )
    )
    return not past_blockers


def _combat_after_blockers(game: "Game", caster_index: int) -> bool:
    """Aleatory: "only during combat **after** blockers are declared".

    CR 506.7's window one point later than every other row here, and written as
    the *complement* of the row above rather than as its own list of steps:
    "before blockers are declared" and "after blockers are declared" partition
    the turn between them, and no moment may fall into both or into neither.
    Spelling the steps out again is how that guarantee would be lost -- the same
    reason ``activation_restrictions`` gives for keeping one predicate per point
    in combat.

    The combat-phase floor is this card's own word ("during combat"), and it is
    exactly what the complement does not carry: the sibling is True in the
    precombat main phase, which is before the declaration and not during combat.

    Where the point *is* -- the declare blockers step's arrival, per CR 509.1's
    turn-based action -- is stated once, in the sibling, and never here. One
    artifact of the engine's step model rides along with that: CR 508.8 skips
    the declare blockers step outright when nothing attacked, so the window this
    card names does not exist in that combat at all, and the engine keeps the
    step. The difference is confined to a window in which no priority is given.
    """
    return (
        game.current_turn_phase == "combat"
        and not _before_blockers_are_declared(game, caster_index)
    )


def _during_combat(game: "Game", caster_index: int) -> bool:
    """Angelic Favor: "only during combat" — the whole combat phase, any of its
    five steps, on anybody's turn (CR 506.7c).

    The widest of the combat windows and the one the three "during combat
    <before/after> blockers are declared" rows each narrow, so it names no step
    and no seat: the card prints neither.
    """
    return game.current_turn_phase == "combat"


def _after_combat(game: "Game", caster_index: int) -> bool:
    # Glyph of Reincarnation: after the combat *phase* has ended, so the
    # postcombat main phase and the ending phase. The end of combat step is
    # still combat.
    return game.current_turn_phase in ("postcombat_main", "ending")


def _during_declare_blockers(game: "Game", caster_index: int) -> bool:
    return game.current_turn_phase == "combat" and game.current_step == "declare_blockers"


def _during_combat_before_blockers(game: "Game", caster_index: int) -> bool:
    # Blaze of Glory: legal during beginning-of-combat and declare-attackers
    # (attackers may still be declared / blockers not yet declared).
    return (
        game.current_turn_phase == "combat"
        and game.current_step in ("beginning_of_combat", "declare_attackers")
    )


def _own_combat_before_blockers(game: "Game", caster_index: int) -> bool:
    # Melee: the window `_during_combat_before_blockers` names, plus the seat
    # its line prints and that one's does not ("during combat **on your turn**
    # before blockers are declared"). The same pairing `_during_own_declare_attackers`
    # and `_during_declare_attackers` already are a few rows up: one clause says
    # whose turn and the other deliberately does not, so the seat is read in one
    # and never consulted in the other.
    return (
        game.active_player_index == caster_index
        and _during_combat_before_blockers(game, caster_index)
    )


def _before_combat_damage_step(game: "Game", caster_index: int) -> bool:
    # Berserk: illegal once the turn has reached the combat damage step —
    # during it, after it (end of combat, postcombat main), or in the ending phase.
    past_combat_damage = (
        game.current_turn_phase in ("postcombat_main", "ending")
        or (
            game.current_turn_phase == "combat"
            and game.current_step in ("combat_damage", "end_of_combat")
        )
    )
    return not past_combat_damage


def _during_an_opponents_turn(game: "Game", caster_index: int) -> bool:
    """Delirium: legal only while it is not this player's turn.

    The whole turn, which is what separates it from the two narrower windows
    below — those name a *step* as well, and this one names none. The seat test
    is the only test there is, and it is the right one in a multiplayer game
    too: CR 102.1 gives every seat its own turn, so "an opponent's turn" is
    every turn but the caster's.
    """
    return game.active_player_index != caster_index


def _opponents_turn_before_attackers(game: "Game", caster_index: int) -> bool:
    if game.active_player_index == caster_index:
        return False
    if game.current_turn_phase == "combat":
        return (
            game.current_step in ("beginning_of_combat", "declare_attackers")
            and not game.combat_attackers_locked
        )
    return game.current_turn_phase in ("beginning", "precombat_main")


def _opponents_turn_after_upkeep(game: "Game", caster_index: int) -> bool:
    # Reset: legal only during an opponent's turn, and only once that player's
    # upkeep step has ended — "after their upkeep step" excludes the upkeep
    # itself, so the window opens at their draw step. A skipped upkeep still
    # opens it: what is tested is that the turn has moved past the beginning
    # phase's untap/upkeep steps, not that an upkeep happened.
    if game.active_player_index == caster_index:
        return False
    return not (
        game.current_turn_phase == "beginning"
        and game.current_step in ("untap", "upkeep")
    )


def _during_your_end_step(game: "Game", caster_index: int) -> bool:
    # Necrologia: the end step of the caster's own turn (CR 513.1), not the
    # cleanup step after it and not an opponent's. "Your" is the seat check;
    # the step check is the phase and step pair the ending phase reports,
    # because the ending phase also contains the cleanup step.
    return (
        game.active_player_index == caster_index
        and game.current_turn_phase == "ending"
        and game.current_step == "end"
    )


def _during_an_opponents_upkeep(game: "Game", caster_index: int) -> bool:
    # Festival: legal only while an opponent's upkeep step is the current step.
    # Both halves are asked — the seat *and* the step — because either alone is
    # a window the card does not print: "an opponent's turn" is most of the
    # turn, and "the upkeep step" would let a player cast it in their own.
    if game.active_player_index == caster_index:
        return False
    return game.current_turn_phase == "beginning" and game.current_step == "upkeep"


CAST_RESTRICTIONS: tuple[CastRestriction, ...] = (
    CastRestriction(
        "cast this spell only during an opponent's upkeep",
        _during_an_opponents_upkeep,
        "can only be cast during an opponent's upkeep",
        names_seat="active",
    ),
    CastRestriction(
        "cast this spell only during your end step",
        _during_your_end_step,
        "can only be cast during your end step",
    ),
    CastRestriction(
        "cast this spell only during your declare attackers step",
        _during_own_declare_attackers,
        "can only be cast during your declare attackers step",
    ),
    CastRestriction(
        "cast this spell only during the declare attackers step",
        _during_declare_attackers,
        "can only be cast during the declare attackers step",
    ),
    CastRestriction(
        "cast this spell only before blockers are declared",
        _before_blockers_are_declared,
        "can only be cast before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only after combat",
        _after_combat,
        "can only be cast after combat",
    ),
    CastRestriction(
        "cast this spell only during the declare blockers step",
        _during_declare_blockers,
        "can only be cast during the declare blockers step",
    ),
    CastRestriction(
        "cast this spell only during combat before blockers are declared",
        _during_combat_before_blockers,
        "can only be cast during combat before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only during combat on your turn before blockers are declared",
        _own_combat_before_blockers,
        "can only be cast during combat on your turn before blockers are declared",
    ),
    CastRestriction(
        "cast this spell only during combat after blockers are declared",
        _combat_after_blockers,
        "can only be cast during combat after blockers are declared",
    ),
    CastRestriction(
        "cast this spell only before the combat damage step",
        _before_combat_damage_step,
        "can only be cast before the combat damage step",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn, before attackers are declared",
        _opponents_turn_before_attackers,
        "can only be cast during an opponent's turn, before attackers are declared",
        names_seat="active",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn after their upkeep step",
        _opponents_turn_after_upkeep,
        "can only be cast during an opponent's turn after their upkeep step",
        names_seat="active",
    ),
    # **After the three rows it is a strict prefix of**, for the reason the last
    # row in this table gives: `check_cast_timing` reports the *first* violated
    # restriction, so above "during combat before blockers are declared" this
    # would answer Blaze of Glory with a window wider than the one it prints.
    # Enforcement is unaffected either way — a card printing a longer clause
    # violates this row only when it also violates its own.
    CastRestriction(
        "cast this spell only during combat",
        _during_combat,
        "can only be cast during combat",
    ),
    # **Last, and the order is load-bearing.** This phrase is a strict prefix of
    # the two above it, and `check_cast_timing` reports the *first* violated
    # restriction it finds — so above them it would answer Siren's Call and
    # Reset with a message naming a window wider than the one they print. The
    # enforcement is unaffected either way (a card printing the longer clause
    # violates both rows together), which is exactly why the ordering has to be
    # stated: the failure is a message, and a message is not something a
    # behavioural test looks at unless it is told to.
    CastRestriction(
        "cast this spell only during an opponent's turn",
        _during_an_opponents_turn,
        "can only be cast during an opponent's turn",
        names_seat="active",
    ),
)


# ---------------------------------------------------------------------------
# The board condition: "Cast this spell only if you control <noun phrase>"
# ---------------------------------------------------------------------------

#: Anchored at both ends against one printed line. The noun phrase is
#: everything after "you control", read below rather than enumerated here — the
#: whole reason this is one row and not one row per printable board.
_CONTROLS_RE = re.compile(
    r"^cast this spell only if you control (?P<board>.+)$"
)


@lru_cache(maxsize=None)
def cast_condition_line(line: str) -> "tuple[dict, str] | None":
    """"Cast this spell only if you control a snow land." (Blizzard.)

    Returns ``(filter payload, the printed noun phrase)``, or None when the
    line is not this restriction or names a board the matcher cannot test.

    The noun phrase goes through **the grammar's noun parser**, because
    ``subject_matches`` is what answers it at every cast and a second reader of
    "a snow land" would be free to disagree with it about what one is. A phrase
    carrying a key ``subject_matches`` cannot test is refused rather than
    approximated: a dropped restriction here is a spell castable on a board the
    card forbids, which is the direction this table exists to prevent.

    "**a**" and nothing else. "no snow lands" and "two or more" are different
    conditions — a negation and a threshold — and reading either as presence is
    a restriction lifted on a board the card does not name.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    match = _CONTROLS_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    board = match.group("board")
    article, _, rest = board.partition(" ")
    if article not in ("a", "an") or not rest:
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
    return payload, board


#: "Cast this spell only if **no permanents named Tidal Influence are on the
#: battlefield**." (Tidal Influence.) The negative twin of the row above, and
#: two things separate them rather than one: the quantifier is a negation, and
#: the zone named is **the** battlefield rather than the caster's own share of
#: it (CR 400.1 — there is one battlefield, and every player's permanents are
#: on it). A card that stopped its second copy only on *your* side would be a
#: different, strictly weaker card, so the two are different rows with
#: different scans rather than one row with a flag.
#:
#: The noun phrase is payload, exactly as it is above: "permanents named X" is
#: what this card prints and "artifacts", "black creatures" or any other phrase
#: the noun parser reads is the same restriction on a different board.
_ABSENT_RE = re.compile(
    r"^cast this spell only if no (?P<board>.+) are on the battlefield$"
)


@lru_cache(maxsize=None)
def cast_absence_line(line: str) -> "tuple[dict, str] | None":
    """``(filter payload, the printed noun phrase)`` for the absence row, or None.

    Through **the grammar's noun parser** for :func:`cast_condition_line`'s
    reason: ``subject_matches`` answers this at every cast, and a second reader
    of "permanents named Tidal Influence" would be free to disagree with it
    about what one is. A phrase carrying a key that matcher cannot test refuses
    rather than being approximated — a dropped narrowing here is a spell
    *refused* on a board the card allows, which is the direction that costs a
    player a card they may legally cast.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import untestable_filter_keys

    match = _ABSENT_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    board = match.group("board")
    stream = TokenStream(tokenize(board).tokens)
    try:
        described = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = described.to_payload()
    if not payload or untestable_filter_keys(payload):
        return None
    return payload, board


#: "Cast this spell only if **you were dealt damage this turn by a red instant
#: or sorcery spell**." (Suffocation.) The third condition row, and the first
#: whose question is about a *window* rather than about a board: the two above
#: scan permanents that are there now, and this one asks what already happened.
#:
#: It needs no record of its own. ``engine/damage_ledger.py`` has kept every
#: damage event of the turn beside the cast that dealt it since Backdraft, and
#: joining "who was hit" to "which cast hit them" is the whole of the question —
#: so this row is a reader, not a new history. The noun phrase is payload for
#: :func:`cast_condition_line`'s reason: a card printed about a *blue* instant
#: or sorcery spell, or about an artifact source, is this restriction with one
#: word changed and needs no second row.
_DAMAGED_BY_RE = re.compile(
    r"^cast this spell only if you were dealt damage this turn by (?P<source>.+)$"
)


@lru_cache(maxsize=None)
def cast_damage_source_line(line: str) -> "tuple[dict, str] | None":
    """``(filter payload, the printed noun phrase)`` for the damage-source row.

    Through **the grammar's noun parser** and then through
    ``subject_filters.card_only_filter``, which is the gate here rather than
    ``untestable_filter_keys``: what this restriction asks about is a *spell*,
    and a spell is not a permanent — CR 613.1 gives it no computed
    characteristics, so the printed face is the whole of what is testable and
    the permanent matcher's keys would promise answers nobody can give.

    A phrase reaching outside that set leaves the line unclaimed rather than
    admitted with the narrowing dropped, which is the direction every row in
    this file refuses in: a restriction quietly widened is a spell castable when
    the card forbids it.

    "**a**"/"**an**" and nothing else, exactly as :func:`cast_condition_line`
    reads its article — "no red spell" and "two or more" are different
    conditions, and reading either as presence lifts the restriction on a turn
    the card does not name.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import card_only_filter

    match = _DAMAGED_BY_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    described = match.group("source")
    article, _, rest = described.partition(" ")
    if article not in ("a", "an") or not rest:
        return None
    stream = TokenStream(tokenize(rest).tokens)
    try:
        parsed = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = parsed.to_payload()
    if not payload:
        return None
    testable = card_only_filter(payload)
    if not testable:
        return None
    return testable, described


#: "Cast this spell only if **an opponent cast a creature spell this turn**."
#: (Lure of Prey.) The fourth condition row, and the second whose question is
#: about a *window* rather than a board: what it asks about is gone by the time
#: it is asked -- the spell it names has resolved, been countered or is still on
#: the stack, and none of those states is on any battlefield.
#:
#: It needs no record of its own. ``PlayerState.spells_cast_this_turn`` has held
#: every cast of the turn beside the seat that made it since Stormwing Entity's
#: ordinal, and ``turn_management`` empties it at the turn boundary with the
#: rest of the turn's history -- which is the half that matters here, because a
#: record that outlived its turn would be a restriction that stopped applying,
#: and a restriction lifted is a spell castable when the card forbids it.
#:
#: The noun phrase is payload, for :func:`cast_condition_line`'s reason: a card
#: printed about an *artifact* spell, or a black one, is this restriction with
#: one word changed and needs no second row.
_OPPONENT_CAST_RE = re.compile(
    r"^cast this spell only if an opponent cast (?P<spell>.+) this turn$"
)


@lru_cache(maxsize=None)
def cast_opponent_cast_line(line: str) -> "tuple[dict, str] | None":
    """``(filter payload, the printed noun phrase)`` for the opponent-cast row.

    Through **the grammar's noun parser** and then through
    ``subject_filters.card_only_filter``, which is the gate here rather than
    ``untestable_filter_keys`` for the reason :func:`cast_damage_source_line`
    gives one row up: what this asks about is a *spell*, and a spell is not a
    permanent -- CR 613.1 gives it no computed characteristics, so the printed
    face is the whole of what is testable and the permanent matcher's keys would
    promise answers nobody can give.

    A phrase reaching outside that set leaves the line unclaimed rather than
    admitted with the narrowing dropped, which is the direction every row in
    this file refuses in: a restriction quietly widened is a spell castable when
    the card forbids it. "**a**"/"**an**" and nothing else, exactly as the two
    rows above read their article.
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import card_only_filter

    match = _OPPONENT_CAST_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    described = match.group("spell")
    article, _, rest = described.partition(" ")
    if article not in ("a", "an") or not rest:
        return None
    stream = TokenStream(tokenize(rest).tokens)
    try:
        parsed = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = parsed.to_payload()
    if not payload:
        return None
    testable = card_only_filter(payload)
    if not testable:
        return None
    return testable, described


#: "Cast this spell only if **you've cast another spell this turn**."
#: (Skyshroud Condor.) The row above with the seat turned around, and its own
#: row rather than a seat flag on that one because the two scans are different:
#: that one walks ``opponents_of``, this one walks the caster's own record, and
#: a flag would put the choice between them inside a predicate that is otherwise
#: pure about *which spell*.
#:
#: **"Another" is honoured by construction, not dropped.** The word means "a
#: spell other than this one", and CR 601.3 asks this gate as part of announcing
#: the spell — before ``casting`` appends it to ``spells_cast_this_turn``, which
#: it does only once the cast has succeeded. So the record this reads can never
#: contain the spell being cast, and a non-empty record *is* "another spell".
#: Reading the word as an unnarrowed "spell" without that reasoning would be the
#: dropped-rider bug this file exists to refuse, so the article is admitted by
#: name below rather than by falling through.
_YOU_CAST_RE = re.compile(
    r"^cast this spell only if you(?:'ve|’ve| have) cast (?P<spell>.+) this turn$"
)


@lru_cache(maxsize=None)
def cast_spell_filter(phrase: str) -> "dict | None":
    """What "a creature spell" / "another spell" names, as a card filter.

    ``{}`` for a phrase that narrows nothing — a real answer, meaning "every
    spell" — and ``None`` for one this cannot read. The two are distinguished
    because each caller decides whether the unnarrowed reading is a sentence its
    card prints: Skyshroud Condor's "another spell" is, and no card in the pool
    prints an unnarrowed *opponent*-scoped one, so that row refuses it rather
    than admitting a reading nothing tests.

    **One reader for two tables.** The clause is one fact — "has a spell the
    phrase names been cast this turn" — and Tempest prints it twice, once as a
    casting gate (Skyshroud Condor, CR 601.3) and once as a combat restriction
    (Mogg Conscripts, CR 506), so ``engine/combat_restrictions.py`` asks this
    rather than reading the phrase again. Two readers of one printed phrase
    drift, and a *restriction* drifts in the direction of applying more or less
    often than the card says.

    Through **the grammar's noun parser** and then through
    ``subject_filters.card_only_filter``: what this asks about is a *spell*, and
    a spell is not a permanent — CR 613.1 gives it no computed characteristics,
    so the printed face is the whole of what is testable and the permanent
    matcher's keys would promise answers nobody can give.

    "a"/"an"/"another" and nothing else. "no spell" and "two or more" are
    different conditions, and reading either as presence lifts the restriction
    on a turn the card does not name. (The two rows above predate this helper
    and still inline its body; adopting them is a tidy-up, not a fix, because
    they refuse the unnarrowed phrase where this returns it.)
    """
    from .grammar.errors import GrammarError
    from .grammar.lexer import tokenize
    from .grammar.nouns import parse_object_filter
    from .grammar.stream import TokenStream
    from .subject_filters import card_only_filter

    article, _, rest = phrase.strip().partition(" ")
    if article not in ("a", "an", "another") or not rest:
        return None
    stream = TokenStream(tokenize(rest).tokens)
    try:
        parsed = parse_object_filter(stream)
    except GrammarError:
        return None
    if not stream.exhausted:
        return None
    payload = parsed.to_payload()
    if not payload:
        return {}
    return card_only_filter(payload) or None


@lru_cache(maxsize=None)
def cast_own_cast_line(line: str) -> "tuple[dict, str] | None":
    """``(filter payload, the printed noun phrase)`` for the own-cast row.

    The tuple is what distinguishes "read, no narrowing" from "not my
    sentence" — ``cast_spell_filter`` returns ``{}`` for the first and this
    returns None for the second, so a caller can never mistake one for the
    other.
    """
    match = _YOU_CAST_RE.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    described = match.group("spell")
    payload = cast_spell_filter(described)
    return None if payload is None else (payload, described)


def spells_cast_matching(game: "Game", seat: int, payload: dict) -> bool:
    """Whether *seat* has already cast a spell :func:`cast_spell_filter` names.

    The **one reader of the record**, for :func:`cast_spell_filter`'s reason one
    function up: Skyshroud Condor asks it as a casting gate and Mogg Conscripts
    asks it as a combat restriction (``phases/declare_attackers_step``), and the
    two must not come to disagree about which casts count.

    *seat* is whose "you" it is: the caster for a casting gate (CR 109.5's
    observer for a spell being cast is its controller), the attacker's current
    controller for a creature's own text.

    An empty payload admits every spell in the record, which is what an
    unnarrowed "another spell" says. The card is tested with
    ``_card_matches_filter``, the matcher ``card_only_filter`` gates for: the
    record holds ``CardDefinition``s, the printed faces, which is exactly what
    there is to ask about a spell that is no longer anywhere.
    """
    from .handlers._common import _card_matches_filter

    if not 0 <= seat < len(game.players):
        return False
    cast = game.players[seat].spells_cast_this_turn
    if not payload:
        return bool(cast)
    return any(_card_matches_filter(spell, payload) for spell in cast)


def _an_opponent_cast(game: "Game", caster_index: int, payload: dict) -> bool:
    """Whether any opponent of *caster_index* has cast a spell the phrase names.

    ``opponents_of`` rather than "every other seat", because CR 800.4a says a
    player who has left the game is nobody's opponent any more -- and the same
    reading every other seat comparison in the engine makes.

    The card is tested with ``_card_matches_filter``, which is the matcher
    ``card_only_filter`` gates for: the record holds ``CardDefinition``s, the
    printed faces, which is exactly what there is to ask about a spell that is
    no longer anywhere.
    """
    from .handlers._common import _card_matches_filter

    return any(
        _card_matches_filter(spell, payload)
        for seat in game.opponents_of(caster_index)
        for spell in game.players[seat].spells_cast_this_turn
    )


def _was_dealt_damage_by(game: "Game", caster_index: int, payload: dict) -> bool:
    """Whether a spell the phrase names has dealt *caster_index* damage this turn.

    The same reader the damage handler's recipient arm uses
    (``damage_ledger.last_cast_that_damaged_seat``), so the gate and the effect
    it admits cannot disagree about which spell the sentence names — a
    disagreement would either refuse a cast the effect would have resolved or
    admit one it then does nothing for.
    """
    from .damage_ledger import last_cast_that_damaged_seat

    return last_cast_that_damaged_seat(game, caster_index, payload) is not None


def _nothing_matches(game: "Game", caster_index: int, payload: dict) -> bool:
    """Whether *no* permanent anywhere matches the phrase.

    Every battlefield, not the caster's: see :data:`_ABSENT_RE`. CR 109.5's
    observer is still the casting seat, so a "you" *inside* the noun phrase
    would mean the same player the caster is.
    """
    from .subject_filters import subject_matches

    return not any(
        subject_matches(game, perm, payload, observer=caster_index)
        for perm in game.all_permanents()
    )


def _condition_holds(game: "Game", caster_index: int, payload: dict) -> bool:
    """Whether *caster_index* controls a permanent the phrase names.

    CR 109.5's observer is the casting seat, so a "you" inside the noun phrase
    means the same player the outer "you control" does.
    """
    from .subject_filters import subject_matches

    return any(
        subject_matches(game, perm, payload, observer=caster_index)
        for perm in game.controlled_by(caster_index)
    )


def cast_timing_claims_line(line: str) -> bool:
    """Whether this table reads *line* as a gate the casting card prints about
    itself (CR 601.3).

    The **table's own** answer to "is this my sentence?", asked by the support
    gate in ``engine/oracle.py`` — the same seam ``cast_costs``'s
    ``cast_cost_claims_line`` and ``enter_effects.enter_effect_line`` are, and
    for their reason: what the engine enforces and what it claims to have read
    cannot be two lists.

    It exists because **Skyshroud Condor is the first creature in the pool to
    print one of these clauses**. Every other card carrying one is an instant or
    an enchantment, and those classifiers do not require every line to be read —
    so the clause has never had to make a card supported, only to be enforced.
    A creature is refused for any line nothing reads, which meant a card the
    table gates perfectly reported "text too complex".

    Only the rows a card prints *about its own cast*. The board-wide bans
    further down this file ("Creature spells can't be cast.") are a permanent's
    sentence about everybody else's spells, claimed by their own names in
    ``_derived_static_claims``, and folding them in here would let a creature's
    own timing gate be satisfied by a reader that has nothing to do with it.

    A run of readers rather than a list of phrases, so a row added above is a
    row this answers for; the corpus-wide check that no printed "Cast this spell
    only …" escapes it lives in ``tests/rules/test_cast_restrictions.py``.
    """
    normalized = line.strip().lower().rstrip(".")
    if any(restriction.phrase == normalized for restriction in CAST_RESTRICTIONS):
        return True
    return any(
        reader(normalized) is not None
        for reader in (
            cast_condition_line,
            cast_absence_line,
            cast_damage_source_line,
            cast_opponent_cast_line,
            cast_own_cast_line,
        )
    )


def check_cast_timing(game: "Game", caster_index: int, oracle_text_lower: str) -> str | None:
    """The denial message for the first violated casting restriction present in
    *oracle_text_lower*, or None if every restriction present is satisfied."""
    for restriction in CAST_RESTRICTIONS:
        if restriction.phrase in oracle_text_lower and not restriction.is_legal(game, caster_index):
            return restriction.denial_message
    # Per line rather than by substring: the board condition ends at the end of
    # its sentence, and a phrase read out of the middle of a longer one would
    # be a restriction the card does not print.
    for line in oracle_text_lower.split("\n"):
        read = cast_condition_line(line)
        if read is None:
            continue
        payload, board = read
        if not _condition_holds(game, caster_index, payload):
            return f"can only be cast if you control {board}"
    for line in oracle_text_lower.split("\n"):
        absent = cast_absence_line(line)
        if absent is None:
            continue
        payload, board = absent
        if not _nothing_matches(game, caster_index, payload):
            return f"can only be cast if no {board} are on the battlefield"
    # Per line for the reason the two loops above are: the phrase ends with
    # its sentence, and a window read out of the middle of a longer one would
    # be a restriction the card does not print.
    for line in oracle_text_lower.split("\n"):
        damaged = cast_damage_source_line(line)
        if damaged is None:
            continue
        payload, described = damaged
        if not _was_dealt_damage_by(game, caster_index, payload):
            return (
                "can only be cast if you were dealt damage this turn by "
                f"{described}"
            )
    # Per line for the three loops above's reason: the phrase ends with its
    # sentence, and a window read out of the middle of a longer one would be a
    # restriction the card does not print.
    for line in oracle_text_lower.split("\n"):
        opponent_cast = cast_opponent_cast_line(line)
        if opponent_cast is None:
            continue
        payload, described = opponent_cast
        if not _an_opponent_cast(game, caster_index, payload):
            return f"can only be cast if an opponent cast {described} this turn"
    # Per line for the four loops above's reason: the phrase ends with its
    # sentence, and a window read out of the middle of a longer one would be a
    # restriction the card does not print.
    for line in oracle_text_lower.split("\n"):
        own_cast = cast_own_cast_line(line)
        if own_cast is None:
            continue
        payload, described = own_cast
        if not spells_cast_matching(game, caster_index, payload):
            return f"can only be cast if you've cast {described} this turn"
    return None


def timing_fixed_seat(game: "Game", caster_index: int, card) -> "int | None":
    """The seat this spell's own timing clause names, or None when none does.

    CR 601.2c chooses targets as the spell is announced, and "target creature
    **that player** controls" has to know which player before it can offer one.
    On a trigger the seat is the firing event's, frozen at the fire site; on a
    modal spell it is the seat that chose the mode. A **spell** printing the
    phrase in its own text has neither, and the only place the word can point
    is the sentence in front of it — which for every card in the pool that
    prints one is the timing clause above.

    The seat is checked against CR 102.3 rather than trusted: every window that
    names a player names an *opponent's* turn, so the active player being the
    caster means the spell is being asked about outside its own window, and the
    honest answer is that the phrase names nobody. The picker then offers
    nothing, which is what an unanswerable target means (the same direction
    ``defending_player_only`` takes with no combat).

    The **card** rather than its text, so the one printed-text read lives here,
    beside ``check_cast_timing``'s callers, which make the identical read of the
    identical clause. There is no ``effective_card`` to prefer: that is a
    ``Permanent``'s accessor for what a *permanent* says (CR 707.2, CR 612.1),
    and the object this asks about is a card on its way to the stack.

    Asked twice — once by the picker at CR 601.2c and once at resolution — and
    the two cannot disagree: the window is an opponent's *turn*, and a turn
    cannot end while the spell that named it is still on the stack.
    """
    oracle_text_lower = (getattr(card, "oracle_text", "") or "").lower()
    for restriction in CAST_RESTRICTIONS:
        if restriction.names_seat is None:
            continue
        if restriction.phrase not in oracle_text_lower:
            continue
        seat = game.active_player_index
        if seat == caster_index or not 0 <= seat < len(game.players):
            return None
        return seat
    return None


# --- The board half of CR 601.3: a prohibition a *permanent* imposes ---------
#
# Everything above is read off the **casting card's own text** — a gate the
# spell prints about itself. "Creature spells can't be cast." (Aether Storm) is
# the other direction entirely: the sentence is printed on a permanent, it names
# no seat, and it stops *every* player casting spells of a type (CR 601.3a).
# So it is a scan of the battlefields rather than a scan of the spell, and its
# own reader for that reason.
#
# The card **type** is payload, for `auras.aura_controller_cast_ban`'s reason:
# "Artifact spells can't be cast." is the same sentence and must need no second
# row. That reader is deliberately *not* widened into this one — what differs
# between them is the **scope**, and a scope taken from the wrong half of a
# sentence bans the wrong players. Aether Storm's ban reaches its own
# controller; Brand of Ill Omen's reaches only the enchanted creature's.
_BANNABLE_SPELL_TYPES = (
    r"(?:artifact|creature|enchantment|instant|sorcery|planeswalker|battle)"
)
_GLOBAL_CAST_BAN = re.compile(
    rf"^(?P<type>{_BANNABLE_SPELL_TYPES}) spells can't be cast$"
)


@lru_cache(maxsize=None)
def global_cast_ban_line(line: str) -> str | None:
    """The card type *line* forbids anybody from casting, or None.

    One reader, two callers, exactly as :func:`auras.aura_controller_cast_ban`
    has: ``engine/grammar/registries.py`` asks it so the printed line is
    *claimed*, and ``mixins/stack/casting.py`` asks it at CR 601.2 so the line
    is *enforced*. A restriction that is claimed and not enforced is an
    enchantment that reports supported and lets every creature through, which is
    the one failure this seam exists to make impossible.
    """
    match = _GLOBAL_CAST_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type") if match is not None else None


#: "**You** can't cast creature spells." (Steel Golem.) The third scope this
#: prohibition is printed in, and the reason it is a third reader rather than a
#: widening of :data:`_GLOBAL_CAST_BAN` above: what differs between the three is
#: **whom the sentence binds**, and a scope taken from the wrong half of a
#: sentence bans the wrong players. Aether Storm's "Creature spells can't be
#: cast" binds everybody; Brand of Ill Omen's binds the enchanted creature's
#: controller (``auras.aura_controller_cast_ban``); this one binds the seat that
#: controls the permanent printing it, and nobody else — an opponent who steals
#: the Golem is stopped and its former controller is freed, which is exactly what
#: CR 109.5 makes of the word "you".
#:
#: The card type is payload for the reason every printed word in this table is
#: one: "…can't cast artifact spells" is the same sentence and must need no
#: second row.
_OWN_CAST_BAN = re.compile(
    rf"^you can't cast (?P<type>{_BANNABLE_SPELL_TYPES}) spells$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, not ``"cast_restrictions"``, for
#: :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason: that claim says *when this card*
#: may be cast, and this sentence is a standing prohibition on a player.
OWN_CAST_BAN_CLAIM = "own_cast_ban"


@lru_cache(maxsize=None)
def own_cast_ban_line(line: str) -> str | None:
    """The card type *line* forbids its own controller from casting, or None.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    ``engine/oracle.py``'s two support gates ask it so the card is admitted on
    the strength of a restriction that exists, and ``mixins/stack/casting.py``
    asks it at CR 601.2 so the line is *enforced*. A restriction claimed and not
    enforced is a permanent that reports supported while its controller keeps
    casting the spells it forbids — and on Steel Golem, whose drawback is the
    whole of what pays for a 3/3 for {3}, that is not a card doing less but a
    card doing something else.
    """
    match = _OWN_CAST_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type") if match is not None else None


def own_cast_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent *caster_index* controls forbidding *card*, or None.

    Only that seat's own battlefield is asked, which is the whole difference
    from :func:`global_cast_ban` beside it — an opponent's Steel Golem says
    nothing about your creature spells.

    ``effective_card`` rather than the printed face, for that function's reason:
    what a permanent says is what layer 1 and layer 3 have made of it (CR 707.2,
    CR 612.1). The type test is :func:`search_filters.card_has_type` for its
    reason too — a card has **every** type its line names (CR 205.2), so an
    artifact creature is stopped by a ban on either word.
    """
    from .search_filters import card_has_type

    for seat, permanent in game.permanents_with_controller():
        if seat != caster_index:
            continue
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            banned = own_cast_ban_line(raw_line)
            if banned is not None and card_has_type(card, banned):
                return permanent.card.name
    return None


#: Where a permanent records the names two seats chose as it entered (Null
#: Chamber). A list, and the order is the choosers' — it is read as a *set* by
#: the ban below, but recorded in order because each slot belongs to one seat
#: and a prompt answering into the wrong one would swap the two players'
#: choices.
CHOSEN_CARD_NAMES = "chosen_card_names"

#: "Spells with the chosen names can't be cast and lands with the chosen names
#: can't be played." (Null Chamber.) The *name*-keyed twin of the type-keyed ban
#: above, and its own row rather than a widening of that one: what a card is
#: called is not a characteristic anything else in this table tests, and the
#: names are not in the sentence at all — they were chosen as the permanent
#: entered (CR 614.1c) and live on it.
#:
#: Both halves of the printed sentence are one row on purpose. A spell and a
#: land drop are the same action to `cast_from_hand`, so one gate covers both —
#: and claiming only the casting half would ship an enchantment that stops a
#: Wrath of God and lets its Island through, which is not the card.
_CHOSEN_NAME_BAN = re.compile(
    r"^spells with the chosen names can't be cast and lands with the chosen "
    r"names can't be played$"
)


@lru_cache(maxsize=None)
def chosen_name_ban_line(line: str) -> bool:
    """Whether *line* is the chosen-name prohibition.

    One reader, two callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and ``mixins/stack/casting.py`` asks it at CR 601.3 so the line is
    *enforced*. A restriction claimed and not enforced is an enchantment that
    reports supported and stops nothing.
    """
    return _CHOSEN_NAME_BAN.match(line.strip().lower().rstrip(".")) is not None


def chosen_name_ban(game: "Game", card) -> str | None:
    """The name of a permanent whose chosen names forbid *card*, or None.

    Every battlefield and no seat comparison: the sentence names nobody, so it
    binds everybody including the enchantment's own controller (CR 601.3a) —
    which for Null Chamber is the whole design, since one of the two names is
    its controller's own choice and the other is an opponent's.

    Compared through ``search_filters.name_key`` on both sides, so a printing
    with different punctuation is the same name — the comparison every other
    name test in the engine makes.
    """
    from .search_filters import name_key

    wanted = name_key(getattr(card, "name", "") or "")
    if not wanted:
        return None
    for _seat, permanent in game.permanents_with_controller():
        chosen = permanent.metadata.get(CHOSEN_CARD_NAMES) or ()
        if not chosen:
            continue
        if not any(
            chosen_name_ban_line(raw_line)
            for raw_line in (permanent.effective_card.oracle_text or "").splitlines()
        ):
            continue
        if any(name_key(str(name)) == wanted for name in chosen if name):
            return permanent.card.name
    return None


#: "Players can't cast spells with the same name as a nontoken permanent." /
#: "Players can't play nonbasic lands with the same name as a nontoken
#: permanent." (Cornered Market.)
#:
#: Null Chamber's ban one screen up, with the names read off the **board**
#: instead of off the permanent: nothing was chosen, so what the sentence
#: forbids changes every time a permanent enters or leaves. Its own row rather
#: than a widening of that one, because the two differ in where the name set
#: comes from — a chosen name is a record and this is a question about the
#: table, and a reader that took either would have to be told which every time.
#:
#: **Two printed lines, and each is claimed on its own**, which is the opposite
#: arrangement from Null Chamber's single sentence: there one line states both
#: rules, and here the card spends a line on each. The alternation is what makes
#: them one row — the noun after "can't" is the only word that differs — and
#: which half a line stated is returned, because the halves forbid different
#: sets: the land line exempts a **basic** land and the spell line has no such
#: word.
#:
#: "Nontoken" is a real narrowing on the *permanent* side and CR 111.1's reason
#: it is printed: a token copy of a creature would otherwise lock its own name
#: out of every hand at the table.
_SAME_NAME_AS_PERMANENT_BAN = re.compile(
    r"^players can't (?P<half>cast spells|play nonbasic lands) with the same "
    r"name as a nontoken permanent$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above, its own for :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason.
SAME_NAME_AS_PERMANENT_BAN_CLAIM = "same_name_as_permanent_ban"


@lru_cache(maxsize=None)
def same_name_as_permanent_ban_line(line: str) -> str | None:
    """Which half of Cornered Market *line* states, or None.

    ``"cast spells"`` or ``"play nonbasic lands"`` — the words themselves, so a
    caller cannot invent a third value and the enforcement below reads the
    printed distinction rather than a flag somebody has to keep in step.

    One reader, two callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and ``mixins/stack/casting.py`` asks it at CR 601.3 / CR 305.1 so the line
    is *enforced*. A restriction claimed and not enforced is an enchantment that
    reports supported and stops nothing.
    """
    match = _SAME_NAME_AS_PERMANENT_BAN.match(line.strip().lower().rstrip("."))
    return match.group("half") if match is not None else None


def same_name_as_permanent_ban(game: "Game", card) -> str | None:
    """The name of a permanent whose ban stops *card* being played, or None.

    Every battlefield and no seat comparison: the sentence names nobody, so it
    binds everybody including the enchantment's own controller (CR 601.3a) —
    which on this card is the whole design, since the names it locks out are
    whatever anybody has already resolved.

    **Which half applies is decided by the card, not by the caller.** A land is
    never cast (CR 305.1 makes playing one a special action), so the spell line
    cannot reach it and the land line cannot reach anything else; and the land
    line exempts a basic land, which the spell line does not say and must not be
    given. Read the other way round, a Forest would stop being playable the
    moment anybody resolved one.

    The comparison goes through ``search_filters.name_key`` on both sides, so a
    printing with different punctuation is the same name — the comparison every
    other name test in the engine makes. The permanent's **effective** name is
    what counts (CR 707.2): a Clone that copied a Bear really is called Grizzly
    Bears, and it is the name the card asks about.
    """
    from .search_filters import card_has_type, name_key

    wanted = name_key(getattr(card, "name", "") or "")
    if not wanted:
        return None
    is_land = card_has_type(card, "land")
    if is_land and "basic" in (getattr(card, "type_line", "") or "").lower():
        # The land half's own word. A basic land is exempt however many of it
        # are on the table, which is what keeps this from ending the game.
        return None
    half = "play nonbasic lands" if is_land else "cast spells"
    for _seat, permanent in game.permanents_with_controller():
        if permanent.metadata.get("is_token"):
            continue
        for raw_line in (
            permanent.effective_card.oracle_text or ""
        ).splitlines():
            if same_name_as_permanent_ban_line(raw_line) != half:
                continue
            # The banning permanent is not what has to share the name — any
            # nontoken permanent on the table does, this one included.
            if _a_nontoken_permanent_is_named(game, wanted):
                return permanent.card.name
    return None


def _a_nontoken_permanent_is_named(game: "Game", wanted: str) -> bool:
    """Whether any **nontoken** permanent on any battlefield answers to *wanted*.

    Its own two lines because the ban above walks the board twice for two
    different questions — which permanents impose the prohibition, and which
    ones supply the names — and folding them into one loop is how a card would
    come to forbid only its own name.
    """
    from .search_filters import name_key

    for _seat, permanent in game.permanents_with_controller():
        if permanent.metadata.get("is_token"):
            continue
        if name_key(permanent.effective_card.name) == wanted:
            return True
    return False


#: "Players can cast spells and activate abilities only during their own
#: turns." (City of Solitude.) The **timing** half of CR 601.3a and CR 602.5,
#: read off the board rather than off the object being played: nothing about
#: the spell or the ability decides it, only whose turn it is.
#:
#: One row, two gates. Both halves of the printed sentence are one rule for
#: ``_CHOSEN_NAME_BAN``'s reason one screen up — claiming the casting half
#: alone would ship an enchantment that stops an opponent's Counterspell and
#: lets their Icy Manipulator through, which is not the card — and the two
#: enforcement sites (``mixins/stack/casting.py``, ``mixins/stack/activation.py``)
#: both ask :func:`global_play_timing`.
#:
#: "Their own turns" is the seat's, so the question is whether the player
#: acting is the active player. No exception for mana abilities: the sentence
#: names none, and CR 605.1a's exception is a thing *other* cards print
#: (Faith's Fetters) rather than a rule about restrictions in general.
_GLOBAL_PLAY_TIMING = re.compile(
    r"^players can cast spells and activate abilities only during their own "
    r"turns$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, not ``"cast_restrictions"``: that claim says *when
#: this card* may be cast, and this sentence is the whole of what the permanent
#: does and is about everybody else's turns — the same distinction
#: ``global_activation_ban`` records one file over.
GLOBAL_PLAY_TIMING_CLAIM = "global_play_timing"

#: "**During combat**, players can't cast instant spells or activate abilities
#: that aren't mana abilities." (Hand to Hand.)
#:
#: The row above with a *phase* in place of a turn, and the same two gates read
#: it for the same reason: one printed sentence stating one rule about both
#: ways of acting, so claiming the casting half alone would ship an enchantment
#: that stops a combat trick and lets an Icy Manipulator through.
#:
#: The spell type is payload, like every other printed word in this table. The
#: mana-ability exception is **not** optional: CR 605.1a's exception is
#: something a card prints rather than a rule about prohibitions in general
#: (``_GLOBAL_PLAY_TIMING`` above names none and so stops mana abilities too),
#: so a sentence without those words is a different, stricter card and must not
#: be read as this one.
_COMBAT_PLAY_BAN = re.compile(
    rf"^during combat, players can't cast (?P<type>{_BANNABLE_SPELL_TYPES}) "
    r"spells or activate abilities that aren't mana abilities$"
)

#: The claim name for the row above, its own for
#: :data:`GLOBAL_PLAY_TIMING_CLAIM`'s reason.
COMBAT_PLAY_BAN_CLAIM = "combat_play_ban"


@lru_cache(maxsize=None)
def combat_play_ban_line(line: str) -> str | None:
    """The spell type *line* forbids during combat, or None.

    One reader, three callers, exactly as :func:`global_play_timing_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and the casting and activation gates ask it so the line is *enforced*.
    """
    match = _COMBAT_PLAY_BAN.match(line.strip().lower().rstrip("."))
    return match.group("type") if match is not None else None


def combat_play_ban(game: "Game") -> tuple[str, str] | None:
    """``(the permanent's name, the spell type it stops)`` while combat is on,
    or None.

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence names nobody, so it binds its own controller as
    thoroughly as anybody (CR 601.3a).

    "During combat" is CR 506.1's phase — every step of it, from the beginning
    of combat through end of combat — which is what ``current_turn_phase``
    answers. Asked of the *phase* rather than of a step, because a card naming
    a step would say so.
    """
    if getattr(game, "current_turn_phase", None) != "combat":
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            banned = combat_play_ban_line(raw_line)
            if banned is not None:
                return permanent.card.name, banned
    return None


@lru_cache(maxsize=None)
def global_play_timing_line(line: str) -> bool:
    """Whether *line* is the board-wide own-turn-only restriction.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    and the casting and activation gates ask it so the line is *enforced*. A
    restriction that is claimed and not enforced is an enchantment that reports
    supported while every player keeps playing on every turn.
    """
    return _GLOBAL_PLAY_TIMING.match(line.strip().lower().rstrip(".")) is not None


def global_play_timing(game: "Game", actor_index: int) -> str | None:
    """The name of a permanent forbidding *actor_index* from acting now, or None.

    Every battlefield and no seat comparison against the permanent's own
    controller: the sentence names nobody, so it binds its controller too — on
    an opponent's turn the enchantment stops its own player as thoroughly as
    anybody (CR 601.3a).

    ``effective_card`` rather than the printed face, for
    :func:`global_cast_ban`'s reason: what a permanent says is what layer 1 and
    layer 3 have made of it (CR 707.2, CR 612.1).
    """
    if actor_index == game.active_player_index:
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if global_play_timing_line(raw_line):
                return permanent.card.name
    return None


#: "Players can't cast spells **that share a color with the spell most recently
#: cast this turn**." (Mana Maze.) CR 601.3a again, and a scope none of the rows
#: above reads it in: what is forbidden is decided by a *relation* between the
#: spell being announced and another spell — CR 105.2's shared colour — and the
#: other spell is whichever was cast last, by anybody.
#:
#: It needs no record of its own, for the spell cap's reason one row down. The
#: turn's ledger (``engine/damage_ledger.py``) has held every cast in order, by
#: its per-cast identity, since Backdraft — and ``begin_turn_bookkeeping``
#: clears it at the turn boundary, which is the printed "this turn": the first
#: spell of a turn is compared against nothing.
#:
#: The whole sentence is the pattern. Nothing in it is payload, because nothing
#: in it is a word another card could print differently and mean this rule.
_LAST_CAST_COLOR_BAN = re.compile(
    r"^players can't cast spells that share a color with the spell most "
    r"recently cast this turn$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`SPELL_CAP_CLAIM`'s reason: no other ban
#: here compares two spells.
LAST_CAST_COLOR_BAN_CLAIM = "last_cast_color_ban"


@lru_cache(maxsize=None)
def last_cast_color_ban_line(line: str) -> bool:
    """Whether *line* is, in full, Mana Maze's prohibition.

    One reader, four callers: ``engine/grammar/registries.py`` asks it so the
    printed line is *claimed*, ``engine/oracle.py``'s support gate so the card
    is admitted on the strength of a restriction that exists,
    ``mixins/stack/casting.py`` at CR 601.2 so it is *enforced*, and
    ``ai_policy`` so a seat stops proposing what the cast path will refuse.
    """
    return _LAST_CAST_COLOR_BAN.match(line.strip().lower().rstrip(".")) is not None


def most_recent_cast_colors(game: "Game") -> frozenset[str] | None:
    """The colours of the spell most recently cast this turn, or None when no
    spell has been cast this turn.

    ``frozenset()`` — empty, and **not** None — is a colourless spell, which is
    a real answer: after an artifact every spell is castable, because a
    colourless object shares a colour with nothing (CR 105.2c).

    Read off the ledger's per-cast ``StackItem`` through the one reader of a
    spell's colour (``Game._stack_item_colors``), so a spell a Lace recoloured
    on the stack is the colour it became — and the item is kept by the ledger
    after it has left the stack, which is the common case: "most recently
    cast" is usually a spell that has already resolved or been countered, and
    what it was is its last-known information (CR 608.2h).

    Cast, not copied and not put onto the stack some other way: the ledger is
    written at CR 601.2i and nowhere else.
    """
    from .damage_ledger import ledger

    casts = ledger(game).casts
    if not casts:
        return None
    return frozenset(game._stack_item_colors(casts[-1].item))


def last_cast_color_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent whose Maze stops *card* being cast, or None.

    Every battlefield and no seat comparison, for :func:`global_cast_ban`'s
    reason: the sentence says "players", so it binds its own controller as
    thoroughly as anybody (CR 601.3a).

    The spell being announced is read through ``object_colors.card_colors``
    with the seat casting it — the layer-5 reading every colour question about
    a card in a hand takes — so a gold card is stopped by either of its colours
    (CR 105.2b) and a card a Celestial Dawn has made white is white.

    A land is never cast (CR 305.1), so the sentence cannot reach one: this
    function is asked from a path that land drops also take.
    """
    from .object_colors import card_colors, share_a_color
    from .search_filters import card_has_type

    if card_has_type(card, "land"):
        return None
    previous = most_recent_cast_colors(game)
    if not previous:
        return None
    if not share_a_color(previous, card_colors(game, card, caster_index)):
        return None
    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            if last_cast_color_ban_line(raw_line):
                return permanent.card.name
    return None


#: "Each player can't cast more than one spell each turn." (Arcane Laboratory;
#: Rule of Law is the same sentence.) CR 601.3a again, and the fourth scope this
#: file reads it in — the three above ask *what* may be cast and this one asks
#: **how many**, which is why it is its own row rather than a payload on any of
#: them: nothing in those patterns counts, and a count is not a card type.
#:
#: The number is payload, for every other printed word in this table's reason: a
#: card printed "more than two spells" is this restriction and must need no
#: second row. Printed as a **word** on every card that prints it at all, so it
#: is read through a number table, and a word with no number behind it leaves
#: the line unclaimed rather than reaching the comparison as a string — where it
#: would compare unequal to every count and stop nobody.
#:
#: It needs no record of its own. ``PlayerState.spells_cast_this_turn`` has held
#: every cast of the turn since Stormwing Entity's ordinal, and
#: ``turn_management`` empties it at the turn boundary — which is the half that
#: matters, because a record outliving its turn is a restriction that stops
#: applying, and a cap lifted is a spell castable when the card forbids it.
#:
#: **Who is capped is payload too.** "**You** can't cast more than one spell
#: each turn." (Yawgmoth's Agenda) is the same count over one seat — CR 109.5's
#: "you", the permanent's controller — where "each player" binds the table.
#: Read as one row so the two cannot drift, and recorded rather than matched
#: and dropped: an Agenda read as Arcane Laboratory caps its controller's
#: opponents as well, which is a drawback turned into a lock.
_SPELL_CAP_PER_TURN = re.compile(
    r"^(?P<who>each player|you) can't cast more than (?P<count>[a-z]+) "
    r"spells? each turn$"
)

#: Printed number words a cap can be written with. Its own table for the reason
#: ``combat_restrictions._NUMBER_WORDS`` is its own: what the two have in common
#: is English, not a rule.
_CAP_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`OWN_CAST_BAN_CLAIM`'s reason: that claim
#: says which *types* a seat may not cast, and this sentence caps how many
#: spells of any type everybody may cast.
SPELL_CAP_CLAIM = "spell_cap"


@lru_cache(maxsize=None)
def spell_cap_line(line: str) -> int | None:
    """How many spells a turn *line* caps every player at, or None.

    One reader, three callers, exactly as :func:`global_cast_ban_line` has:
    ``engine/grammar/registries.py`` asks it so the printed line is *claimed*,
    ``engine/oracle.py``'s support gate asks it so the card is admitted on the
    strength of a restriction that exists, and ``mixins/stack/casting.py`` asks
    it at CR 601.2 so the line is *enforced*. A restriction claimed and not
    enforced is an enchantment that reports supported while every player casts
    as many spells as they like — which on this card is the whole of what it
    does.
    """
    match = _SPELL_CAP_PER_TURN.match(line.strip().lower().rstrip("."))
    if match is None:
        return None
    return _CAP_NUMBER_WORDS.get(match.group("count"))


@lru_cache(maxsize=None)
def spell_cap_binds_controller_only(line: str) -> bool:
    """Whether *line*'s cap is printed on "**you**" rather than "each player".

    Beside :func:`spell_cap_line` rather than folded into its answer, so the
    three callers that ask only "is this a cap, and of how many" keep the int
    they read — and the one that enforces it asks this as well.
    """
    match = _SPELL_CAP_PER_TURN.match(line.strip().lower().rstrip("."))
    return match is not None and match.group("who") == "you"


def spell_cap_ban(game: "Game", caster_index: int) -> str | None:
    """The name of a permanent whose per-turn cap *caster_index* has reached.

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence says "each player", so it binds its own controller as
    thoroughly as anybody (CR 601.3a). The one comparison is the printed
    "**you**" (Yawgmoth's Agenda), which binds the permanent's controller and
    nobody else.

    The count read is the seat's **own** record, not a shared one: CR 601.3a
    restricts the player who is casting, and one table-wide tally would let an
    opponent's turn-one Ornithopter spend everybody's allowance. The record is
    appended to further down the cast (``mixins/stack/casting.py``), so a seat
    that has already cast *cap* spells is at its limit and the spell being
    announced is the one too many.

    ``effective_card`` rather than the printed face, for :func:`global_cast_ban`'s
    reason: what a permanent says is what layer 1 and layer 3 have made of it
    (CR 707.2, CR 612.1).
    """
    if not (0 <= caster_index < len(game.players)):
        return None
    cast_so_far = len(game.players[caster_index].spells_cast_this_turn)
    for seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            cap = spell_cap_line(raw_line)
            if cap is None or cast_so_far < cap:
                continue
            if spell_cap_binds_controller_only(raw_line) and seat != caster_index:
                continue
            return permanent.card.name
    return None


#: A printed run of card types: "artifact, creature, or enchantment"
#: (Damping Engine). Any number of alternatives with any of the printed
#: separators, because the count and the punctuation are facts about one card
#: rather than about the template -- the reading
#: ``cost_modifiers._TYPE_LIST`` already makes of the same English one file
#: over.
_BANNABLE_TYPE_LIST = (
    rf"{_BANNABLE_SPELL_TYPES}(?:,? (?:and |or )?{_BANNABLE_SPELL_TYPES})*"
)

#: "**A player who controls more permanents than each other player** can't play
#: lands or cast artifact, creature, or enchantment spells." (Damping Engine.)
#: The fifth scope this file reads CR 601.3a in, and the first whose subject is
#: not a seat any sentence names but one *derived from the board*: whoever is
#: strictly ahead on permanents right now, which may be nobody and may change
#: between one spell and the next.
#:
#: One row for both halves of the printed sentence, for ``_CHOSEN_NAME_BAN``'s
#: reason: a land drop and a cast are one prohibition here, and claiming the
#: casting half alone would ship an artifact that stops a Wrath of God and lets
#: the same player's Island through -- which on a card that exists to slow the
#: player who is ahead is not a card doing less, it is a card doing something
#: else.
#:
#: The types are payload, like every other printed word in this table.
_MOST_PERMANENTS_PLAY_BAN = re.compile(
    r"^a player who controls more permanents than each other player can't "
    rf"play lands or cast (?P<types>{_BANNABLE_TYPE_LIST}) spells$"
)

#: The claim name the support gate and ``engine/grammar/registries.py`` use for
#: the row above. Its own, for :data:`OWN_CAST_BAN_CLAIM`'s reason: those bans
#: name the seat in the sentence and this one derives it from the board.
MOST_PERMANENTS_PLAY_BAN_CLAIM = "most_permanents_play_ban"

#: Where the permanent records the seats that have bought a turn off its
#: prohibition (CR 116.2d). On the **source**, not on the player, because the
#: offer is the source's and a second Damping Engine is a second prohibition to
#: buy off -- and swept by the cleanup step like every other "until end of
#: turn" record in this engine, which is what the printed duration is.
IGNORED_PLAY_BAN_SEATS = "ignored_play_ban_seats_until_eot"


def _types_in(clause: str) -> tuple[str, ...]:
    """The card types a printed run names, in order.

    Split here rather than in the pattern so the count stays payload: a card
    printing four would need no change.
    """
    parts = re.split(r",| and | or ", clause or "")
    return tuple(word for part in parts if (word := part.strip()))


@lru_cache(maxsize=None)
def most_permanents_play_ban_sentence(sentence: str) -> tuple[str, ...] | None:
    """The spell types one printed *sentence* forbids the leading player, or
    None.

    The **sentence**, where every other reader in this file takes a line,
    because this prohibition is printed with its CR 116.2d escape hatch behind
    it on the same line -- and the two are read by two tables, so the line
    reader below asks this one and ``special_actions`` for the other half.
    """
    match = _MOST_PERMANENTS_PLAY_BAN.match(
        sentence.strip().lower().rstrip(".")
    )
    if match is None:
        return None
    return _types_in(match.group("types"))


@lru_cache(maxsize=None)
def most_permanents_play_ban_line(line: str) -> tuple[str, ...] | None:
    """The spell types a whole printed *line* forbids the leading player.

    Both sentences must be accounted for, for ``_ABILITY_REDUCTION``'s reason
    in ``cost_modifiers``: the offer behind the prohibition is not decoration,
    it is what the player who is ahead can do about it, and a reader claiming
    only the first sentence would ship a permanent that stops a player with no
    way out. The second is read by the table that *performs* it
    (``special_actions``) rather than by a copy of its sentence here, so the
    claim and the offer cannot describe different words.

    A line carrying only the prohibition is a complete, harsher effect and is
    read as one -- the arrangement the Celestial Dawn row in
    ``global_statics`` makes of its own optional second sentence.
    """
    from .special_actions import permanent_special_action_sentence

    sentences = [
        part.strip() for part in (line or "").split(".") if part.strip()
    ]
    if not sentences:
        return None
    banned = most_permanents_play_ban_sentence(sentences[0])
    if banned is None:
        return None
    for extra in sentences[1:]:
        found = permanent_special_action_sentence(extra)
        if found is None or found[0] != IGNORE_BOARD_STATIC:
            return None
    return banned


def _most_permanents_ban_sources(game: "Game", seat: int):
    """Every permanent currently forbidding *seat* to play, with what it stops.

    Yields ``(permanent, banned types)``. A permanent stops *seat* only while
    that seat is the one the sentence describes — strictly ahead of every other
    living player on permanents — and only while that seat has not bought the
    turn off it (CR 116.2d).

    Every battlefield and no seat comparison, for :func:`global_play_timing`'s
    reason: the sentence names nobody's side, so a Damping Engine stops its own
    controller exactly as readily as anybody else.

    The board is asked for a *source* before anybody is asked who is ahead.
    This runs at every cast and at every land drop in every game, and counting
    two players' permanents to discover that nobody printed the sentence is a
    tally taken on every board that has never seen the card.
    """
    from .handlers.control_flow import most_permanents_seat

    sources = [
        (permanent, banned)
        for _controller, permanent in game.permanents_with_controller()
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines()
        if (banned := most_permanents_play_ban_line(raw_line)) is not None
    ]
    if not sources or most_permanents_seat(game) != int(seat):
        return
    for permanent, banned in sources:
        if int(seat) in (permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ()):
            continue
        yield permanent, banned


def most_permanents_cast_ban(game: "Game", caster_index: int, card) -> str | None:
    """The name of a permanent forbidding *caster_index* to cast *card*, or None.

    The type test is :func:`search_filters.card_has_type` for
    :func:`global_cast_ban`'s reason: a card has **every** type its line names
    (CR 205.2), so an artifact creature is stopped by a ban on either word.
    """
    from .search_filters import card_has_type

    for permanent, banned in _most_permanents_ban_sources(game, caster_index):
        if any(card_has_type(card, wanted) for wanted in banned):
            return permanent.card.name
    return None


def most_permanents_land_ban(game: "Game", seat: int) -> str | None:
    """The name of a permanent forbidding *seat* to play a land, or None.

    The other half of the same printed sentence, asked by ``_land_play_refusal``
    — the one gate every land drop goes through — for ``_CHOSEN_NAME_BAN``'s
    reason: one sentence, one reader, two gates, and neither half able to be
    enforced without the other.
    """
    for permanent, _banned in _most_permanents_ban_sources(game, seat):
        return permanent.card.name
    return None


# --- CR 116.2d: what the player who is ahead may do about it ----------------

#: The kind of battlefield special action the offer below registers.
#: ``auras.py`` holds the *attached* twin ("that creature's controller may
#: sacrifice…", Volrath's Curse); this is the board-wide one, and they are two
#: kinds rather than one because what makes the offer is different — an Aura
#: asks its host who controls it, and this asks the board who is ahead.
IGNORE_BOARD_STATIC = "ignore_board_static_until_eot"


@lru_cache(maxsize=None)
def _line_prints_the_escape_hatch(line: str) -> bool:
    """Whether *line* carries CR 116.2d's offer sentence as well as the
    prohibition.

    Asked separately from :func:`most_permanents_play_ban_line`, which accepts
    a line printing the prohibition **alone** — a complete and harsher effect,
    read as one for the reason the Celestial Dawn row in ``global_statics``
    reads its own optional second sentence. The offer must not be inferred from
    the restriction: a card printing only the first sentence gives the player
    who is ahead no way out, and offering one would be this module handing back
    what that card took.
    """
    from .special_actions import permanent_special_action_sentence

    if most_permanents_play_ban_line(line) is None:
        return False
    return any(
        (found := permanent_special_action_sentence(part.strip())) is not None
        and found[0] == IGNORE_BOARD_STATIC
        for part in (line or "").split(".") if part.strip()
    )


def _ignore_board_static_offer(game, permanent):
    """What *permanent* is offering the leading player right now, or None."""
    from .handlers.control_flow import most_permanents_seat
    from .special_actions import SpecialActionOffer

    if not any(
        _line_prints_the_escape_hatch(raw_line)
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines()
    ):
        return None
    seat = most_permanents_seat(game)
    if seat is None:
        return None
    if seat in (permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ()):
        # Already bought this turn. Offering it again would let a seat pay
        # twice for one turn's relief, which the printed duration does not do —
        # ``auras._ignore_static_offer``'s rule, and the same one.
        return None
    # "…**a permanent** of their choice", which is CR 110.1's whole noun: an
    # empty filter is every permanent, and a narrower phrase on a later card is
    # the same field with data in it.
    return SpecialActionOffer(seat=seat, sacrifice={})


def _take_ignore_board_static(game, seat: int, permanent) -> None:
    kept = set(permanent.metadata.get(IGNORED_PLAY_BAN_SEATS) or ())
    permanent.metadata[IGNORED_PLAY_BAN_SEATS] = sorted(kept | {int(seat)})
    game.log.append(
        f"{game.players[seat].name} ignores {permanent.card.name}'s effect "
        "until end of turn (CR 116.2d)"
    )


def clear_ignored_play_bans(permanent) -> bool:
    """CR 514.2's cleanup: an "until end of turn" suspension ends.

    Beside ``auras.clear_ignored_restrictions`` in the same sweep, because that
    is what the printed duration is and the two records are one rule bought in
    two shapes. Returns whether anything was cleared.
    """
    return permanent.metadata.pop(IGNORED_PLAY_BAN_SEATS, None) is not None


def _register_board_static_special_action() -> None:
    """Register CR 116.2d's board-wide offer, once.

    Guarded rather than bare, exactly as ``auras`` guards its own:
    ``engine/special_actions.py`` imports this module from inside its seam to
    make sure the registration has happened, and a duplicate kind raises there
    by design.
    """
    from .special_actions import (PERMANENT_SPECIAL_ACTIONS,
                                  PermanentSpecialAction,
                                  register_permanent_special_action)

    if IGNORE_BOARD_STATIC in PERMANENT_SPECIAL_ACTIONS:
        return
    register_permanent_special_action(PermanentSpecialAction(
        kind=IGNORE_BOARD_STATIC,
        offer=_ignore_board_static_offer,
        take=_take_ignore_board_static,
    ))


_register_board_static_special_action()


def global_cast_ban(game: "Game", card) -> str | None:
    """The name of a permanent forbidding *card* from being cast, or None.

    Every battlefield, and no seat comparison: the sentence names nobody, so it
    binds everybody including the permanent's own controller (CR 601.3a).

    ``effective_card`` rather than the printed face, for the reason the cost-tax
    scan reads it: a type word rewritten by a text-changing effect (CR 613 layer
    3) changes which spells the line stops, and this table should not have to
    know that text can change.

    The type test is :func:`search_filters.card_has_type`, not ``primary_type``:
    a card has **every** type its line names (CR 205.2), so an artifact creature
    is a creature spell and Aether Storm stops it.
    """
    from .search_filters import card_has_type

    for _seat, permanent in game.permanents_with_controller():
        for raw_line in (permanent.effective_card.oracle_text or "").splitlines():
            banned = global_cast_ban_line(raw_line)
            if banned is not None and card_has_type(card, banned):
                return permanent.card.name
    return None
