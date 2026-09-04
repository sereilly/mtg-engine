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
    past_blockers = (
        game.current_turn_phase in ("postcombat_main", "ending")
        or (
            game.current_turn_phase == "combat"
            and game.current_step in ("declare_blockers", "combat_damage", "end_of_combat")
        )
    )
    return not past_blockers


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
        "cast this spell only before the combat damage step",
        _before_combat_damage_step,
        "can only be cast before the combat damage step",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn, before attackers are declared",
        _opponents_turn_before_attackers,
        "can only be cast during an opponent's turn, before attackers are declared",
    ),
    CastRestriction(
        "cast this spell only during an opponent's turn after their upkeep step",
        _opponents_turn_after_upkeep,
        "can only be cast during an opponent's turn after their upkeep step",
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
