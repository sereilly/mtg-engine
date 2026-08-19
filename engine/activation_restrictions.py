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


@dataclass(frozen=True)
class ActivationRestriction:
    """One printed clause, what it permits, and what to say when it does not."""

    pattern: "re.Pattern[str]"
    is_legal: ActivationPredicate
    denial: str


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
        re.compile(r"^only during any upkeep step$"),
        _during_any_upkeep,
        "only during an upkeep step",
    ),
    ActivationRestriction(
        re.compile(r"^activate only during your upkeep$"),
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
            cleaned = sentence.strip().lower()
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
            if cleaned.startswith("activate only") or cleaned.startswith("only during"):
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
            if entry.pattern.match(cleaned) and not entry.is_legal(
                game, controller_index, source
            ):
                return entry.denial
    return None


__all__ = [
    "ACTIVATION_RESTRICTIONS",
    "ActivationRestriction",
    "activation_denial",
    "activation_restriction_line",
    "unreadable_activation_clauses",
]
