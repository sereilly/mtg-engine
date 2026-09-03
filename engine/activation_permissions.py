"""Who may activate a permanent's activated ability (CR 602.1a and its
exceptions).

The default is one sentence of the rules: only the permanent's controller may
activate its activated abilities. A handful of cards print a permission that
says otherwise, and each is a whole printed sentence:

* "Any player may activate this ability." (Ifh-Biff Efreet, Armageddon Clock)
* "Only this creature's owner may activate this ability." (Personal Incarnation)
* "Only your opponents may activate this ability." (Clergy of the Holy Nimbus)

This is the twin of ``engine/activation_restrictions.py`` and exists for the
same reason, in the opposite direction: that file *narrows* when an ability may
be activated, and this one changes *who* may. The two are separate tables
because they are separate questions -- a card can print both on one line, and
Armageddon Clock does ("Any player may activate this ability but only during any
upkeep step"), which is why the restriction file already had to split that
sentence in half.

**What it replaces is four copies of two literals.** Before this module the
permission was a substring test written out in ``mixins/stack/activation.py``
(twice, once per spelling), in ``web/actions.py`` (so the API could find the
permanent on another seat's battlefield), in ``web/static/app.js`` (so a click
on an opponent's permanent was not refused), and a fourth time in the grammar's
``_parse_activation_restriction``, which listed the two spellings as literal
token sequences so the line would consume. Four copies of a permission is four
chances for the answer to differ by client, and adding a third spelling meant
finding all four.

**A permission is only done when something enforces it in both directions.**
The old arrangement only ever *widened*: no code refused an activation, so a
card whose permission is a restriction on its own controller -- which is exactly
what Clergy of the Holy Nimbus prints -- would have had its ability work for the
one player the card forbids. So the table carries a predicate rather than a
flag, and the support gate reads the same table: a permission-shaped sentence no
row here implements makes the card unsupported instead of admitted with the
clause dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game
    from .models import CardDefinition, Permanent

#: (game, activator_seat, permanent) -> True when that seat may activate.
PermissionPredicate = Callable[["Game", int, "Permanent"], bool]


@dataclass(frozen=True)
class ActivationPermission:
    """One printed permission sentence, and who it lets activate."""

    pattern: "re.Pattern[str]"
    may_activate: PermissionPredicate
    denial: str


def _anyone(game: "Game", seat: int, permanent: "Permanent") -> bool:
    return True


def _owner_only(game: "Game", seat: int, permanent: "Permanent") -> bool:
    """"Only this creature's owner may activate this ability." (Personal
    Incarnation.)

    Ownership, not control (CR 108.3): the whole point of the sentence is that
    it still holds when an opponent has taken the creature.
    """
    return game.owner_index_of(permanent) == seat


def _opponents_only(game: "Game", seat: int, permanent: "Permanent") -> bool:
    """"Only your opponents may activate this ability." (Clergy of the Holy
    Nimbus.)

    "Your" on a permanent's own text is its controller (CR 109.5), so this both
    opens the ability to every other seat *and* closes it to the one seat that
    could already reach it.
    """
    controller = game.controller_index_of(permanent)
    return controller is not None and seat != controller


def _attached_controller_only(game: "Game", seat: int, permanent: "Permanent") -> bool:
    """"Only the controller of the enchanted creature may activate this
    ability." (Merseine.)

    The seat that controls the permanent this Aura is *attached to*, which none
    of the three rows beside it can say: they name the Aura's own controller,
    its owner, or everyone else. Here the ability is printed on the Aura and
    reachable only by the player whose creature it is holding down — which on
    Merseine is normally an opponent, so this row both opens the ability to a
    seat CR 602.1a closes and closes it to the one seat that could already
    reach it.

    Read off the live attachment record, never last-known information: this
    answers "may you activate right now", and an Aura with no host is about to
    leave the battlefield (CR 704.5m) with nobody able to activate it in the
    meantime.
    """
    from .handlers._common import attached_host

    host = attached_host(game, permanent, last_known=False)
    if host is None:
        return False
    controller = game.controller_index_of(host)
    return controller is not None and seat == controller


#: The clause :func:`_granting_seat_only` looks for on a granted line, spelled
#: once because the row's pattern and the record scan are two readers of it.
_GRANTING_SEAT_CLAUSE = "only you may activate this ability"


def _granting_seat_only(game: "Game", seat: int, permanent: "Permanent") -> bool:
    """"Only **you** may activate this ability." (Martyrdom.)

    "You" is CR 109.5's controller of the *ability's source* — and on the one
    card in the pool that prints this clause the source is a **spell**, which
    granted the ability to a creature and then left. So the seat cannot be read
    off the permanent: Martyrdom's creature is one you control when the spell
    resolves, and the whole reason the sentence is printed is that control can
    change afterwards. Read off the permanent's controller it would be no rule
    at all — CR 602.1a already says exactly that — and an opponent who took the
    creature would inherit the ability the card forbids them.

    So the seat travels with the grant: ``keywords.grant_ability_line`` records
    the granting seat on the entry, and this reads it back off the entry whose
    line carries the clause. A permanent holding two such grants from two seats
    admits both, which is each grant working as printed rather than a tie
    broken here.

    Printed on a card rather than granted, "you" *is* the permanent's
    controller, and that fallback is what the branch below says. No card in the
    pool prints it that way; the branch exists so the answer does not depend on
    a record's absence meaning something else.
    """
    from .keywords import GRANTED_ABILITY_LINES

    granting_seats = {
        entry.get("seat")
        for entry in (permanent.metadata.get(GRANTED_ABILITY_LINES) or [])
        if _GRANTING_SEAT_CLAUSE in str(entry.get("line") or "").lower()
        and isinstance(entry.get("seat"), int)
    }
    if not granting_seats:
        controller = game.controller_index_of(permanent)
        return controller is not None and seat == controller
    return seat in granting_seats


ACTIVATION_PERMISSIONS: tuple[ActivationPermission, ...] = (
    ActivationPermission(
        pattern=re.compile(r"^any player may activate this ability$"),
        may_activate=_anyone,
        denial="",  # nothing to deny: this row only widens
    ),
    ActivationPermission(
        # The apostrophe is normalized away upstream ("this creatures owner"),
        # so both spellings are admitted rather than relying on which reader got
        # there first.
        pattern=re.compile(r"^only this creature'?s owner may activate this ability$"),
        may_activate=_owner_only,
        denial="only this creature's owner may activate this ability",
    ),
    ActivationPermission(
        pattern=re.compile(r"^only your opponents may activate this ability$"),
        may_activate=_opponents_only,
        denial="only your opponents may activate this ability",
    ),
    ActivationPermission(
        pattern=re.compile(r"^only you may activate this ability$"),
        may_activate=_granting_seat_only,
        denial="only the player who granted this ability may activate it",
    ),
    ActivationPermission(
        # CR 301.5f puts "equipped" and "enchanted" on the same footing, so both
        # words are read: an Equipment printing the clause names the same seat.
        pattern=re.compile(
            r"^only the controller of the (?:enchanted|equipped) [a-z]+ "
            r"may activate this ability$"
        ),
        may_activate=_attached_controller_only,
        denial="only the controller of the enchanted permanent may activate this ability",
    ),
)

#: The *shape* of a permission sentence, matched before any row is. A sentence
#: that looks like one and matches no row is a permission the engine does not
#: implement, and its card has to be refused -- admitting it would leave the
#: clause silently dropped, which for a permission means an ability reachable by
#: a player the card forbids.
_PERMISSION_SHAPE = re.compile(
    r"^(?:any player|only [a-z' ]+) may activate this ability$"
)


def _sentences(text: str) -> list[str]:
    """Every printed sentence of *text*, normalized as the rows match them.

    Split the way ``activation_restrictions._clauses`` splits, and for the same
    reason: the permission is the tail of an ability line, so a line-level
    reader would never see it alone.
    """
    found: list[str] = []
    for raw_line in (text or "").splitlines():
        for sentence in raw_line.split("."):
            cleaned = sentence.strip().strip('"“”').strip().lower()
            # Armageddon Clock joins the permission and a timing restriction
            # with "but": the head is this file's sentence and the tail is
            # `activation_restrictions`'. Split here as well, so each table sees
            # its own half anchored at both ends.
            if " but only " in cleaned:
                cleaned = cleaned.split(" but only ", 1)[0].strip()
            if cleaned:
                found.append(cleaned)
    return found


def activation_permission_line(sentence: str) -> bool:
    """Whether one printed sentence is a permission this module implements.

    Read by the grammar production that consumes the sentence and by the support
    gate, so what is consumed, what is claimed and what is enforced are one
    answer.
    """
    cleaned = (sentence or "").strip().lower().rstrip(".")
    return any(entry.pattern.match(cleaned) for entry in ACTIVATION_PERMISSIONS)


def permission_clause_readable(sentence: str) -> bool:
    """Whether a whole trailing sentence is a permission this module implements
    -- optionally joined by "but" to a timing restriction
    ``engine/activation_restrictions.py`` owns.

    Armageddon Clock prints both halves in one sentence ("Any player may
    activate this ability **but only during any upkeep step**"), so the reader
    that decides whether the grammar may consume the sentence has to ask both
    tables. Asking only this one refused the card; asking neither -- which is
    what the hand-written token sequences in the grammar did -- consumed any
    sentence that started with the right words.
    """
    from .activation_restrictions import activation_restriction_line

    cleaned = (sentence or "").strip().lower().rstrip(".")
    head, joined, tail = cleaned.partition(" but only ")
    if not activation_permission_line(head):
        return False
    if joined and not activation_restriction_line(f"only {tail}"):
        return False
    return True


def permission_shaped_line(sentence: str) -> bool:
    """Whether one sentence *reads* as a "who may activate" permission."""
    cleaned = (sentence or "").strip().lower().rstrip(".")
    return bool(_PERMISSION_SHAPE.match(cleaned))


def unreadable_activation_permissions(oracle_text: str) -> list[str]:
    """The permission sentences in *oracle_text* no row above implements."""
    return [
        sentence
        for sentence in _sentences(oracle_text)
        if permission_shaped_line(sentence) and not activation_permission_line(sentence)
    ]


def _rows_for(ability_text: str) -> list[ActivationPermission]:
    rows: list[ActivationPermission] = []
    for sentence in _sentences(ability_text):
        cleaned = sentence.rstrip(".")
        for entry in ACTIVATION_PERMISSIONS:
            if entry.pattern.match(cleaned):
                rows.append(entry)
    return rows


def card_widens_activation(card: "CardDefinition") -> bool:
    """Whether any ability on *card* may be activated by a seat other than its
    controller.

    The **reachability** question, asked card-wide because that is the shape of
    the question its three askers have: the engine deciding whether to look for
    the permanent on another player's battlefield, the API doing the same, and
    the UI deciding whether a click on an opponent's permanent is a mistake.
    Whether the *particular* ability then admits that seat is
    :func:`activation_permission_denial`, which reads the ability's own line --
    a permanent with two abilities prints its permission on one of them.
    """
    return any(
        activation_permission_line(sentence)
        for sentence in _sentences(getattr(card, "oracle_text", "") or "")
    )


def activation_permission_denial(
    game: "Game", activator_seat: int, permanent: "Permanent", ability_text: str
) -> str | None:
    """Why *activator_seat* may not activate this ability, or None when it may.

    With no permission printed on the line this is CR 602.1a: the controller and
    nobody else. With one or more printed, every one of them must admit the seat
    -- a card printing two contradictory permissions refuses rather than picking
    a winner.
    """
    rows = _rows_for(ability_text)
    if not rows:
        controller = game.controller_index_of(permanent)
        if controller is not None and activator_seat != controller:
            return (
                f"{permanent.card.name}'s abilities can only be activated by "
                "its controller"
            )
        return None
    for entry in rows:
        if not entry.may_activate(game, activator_seat, permanent):
            return f"{permanent.card.name}: {entry.denial}"
    return None


__all__ = [
    "ACTIVATION_PERMISSIONS",
    "ActivationPermission",
    "activation_permission_denial",
    "activation_permission_line",
    "permission_clause_readable",
    "card_widens_activation",
    "permission_shaped_line",
    "unreadable_activation_permissions",
]
