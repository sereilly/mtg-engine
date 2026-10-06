"""May this ability be activated at all?  (CR 602.5)

"A player can't begin to activate an ability that's prohibited from being
activated." The activation path refused a prohibited ability through a run of
ten inline checks, each logging its own sentence, part-way down
``_activate_onto_stack``. Nothing else could ask them as one question, so
every other reader kept a list of its own — and a list of somebody else's
gates is the thing that falls behind:

* the **AI**'s activation chooser asked four of the ten (the printed
  restriction, the printed permission and the two board-wide bans). City of
  Solitude's "…and activate abilities only during their own turns", Hand to
  Hand's "during combat", an Abeyance, an Interdict, the two Aura clauses and
  Katabatic Winds it proposed straight through, and the engine refused each
  one — the seat's only activation of the turn, every turn;
* the **wire** said nothing at all, so the client's ability menu offered every
  ability the text prints and the click was a 400;
* the **castable highlight**, once it counts a Llanowar Elves or a Sol Ring as
  mana a seat could tap (``engine/board_payment.py``), has to know that a
  Cursed Totem or a Null Rod has shut that mana off;
* and an ability activated **from a hand or a graveyard** asked none of them —
  it never came down the permanent's road — so a card was cycled on an
  opponent's turn under a City of Solitude.

This module is the fold: one table, in the order the activation path asked
them, behind :func:`activation_prohibition`. It is ``engine/cast_
prohibitions.py`` one seam over, for the same reason and in the same shape.

**What is a row and what is not.** A row is a rule or an effect that says an
ability *can't be activated*: a board-wide sentence, an Aura's clause, a
resolved effect's turn-long record, the "Activate only …" printed on the line
itself. Not here, because none of them is a prohibition and each has its own
home: whether the permanent *has* the ability (``Game.lost_abilities_
refusal``), the {T} symbol's own two refusals (CR 602.5a, CR 107.5), loyalty
timing (CR 606.3), a per-turn activation count, and whether a target or a cost
exists (CR 601.2c, CR 601.2h).

Each row says what kind of source it binds. An ability of a card in a hand or
a graveyard has no permanent, so a sentence about *permanents* ("activated
abilities of creatures can't be activated") does not reach it — a creature
card in a hand is not a creature (CR 109.2) — while a sentence about *players*
does.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .game import Game

#: Where the ability's source is: a permanent on the battlefield, or a card in
#: another zone (a hand's cycling, a graveyard's "exile this card:").
PERMANENT = "permanent"
CARD = "card"


@dataclass(frozen=True)
class ActivationProhibition:
    """What forbids an activation: the row that answered and the sentence the
    activation path logs for it."""

    kind: str
    details: str


@dataclass(frozen=True)
class ProhibitionRow:
    kind: str
    #: Which sources the row is about (:data:`PERMANENT`, :data:`CARD`).
    binds: frozenset
    #: ``(game, seat, source, ability) -> details or None``.
    ask: Callable


def _name(source) -> str:
    card = getattr(source, "card", None)
    return (card if card is not None else source).name


def _is_mana(ability) -> bool:
    # CR 605.1a decides which abilities a printed "…unless they're mana
    # abilities" leaves open — a mana ability is defined by what it *does*,
    # so the test is ``mana_payment.is_mana_ability``, the activation path's
    # own reader, for all three rows that print the exception (Abeyance, Hand
    # to Hand, Faith's Fetters).
    #
    # **Not the same-named function in ``ai_valuation``**, which is a strictly
    # weaker answer to the same question: it takes a bare instruction, tests
    # membership of a smaller kind set, and answers False for the twelve
    # painlands and depletion lands whose mana ability lowers to a
    # ``sequence``. Reached for here it would shut off a mana ability the card
    # leaves open — it once did exactly that to Faith's Fetters, by a
    # function-level import rebinding the name for a whole function.
    from .mana_payment import is_mana_ability

    return is_mana_ability(ability)


def _permanent_shut_off_this_turn(game, seat, source, ability):
    # "**That permanent's** activated abilities can't be activated this turn."
    # (Interdict, CR 602.5c.) No mana-ability exception: the card prints none.
    from .spell_prohibitions import permanent_activations_forbidden

    if not permanent_activations_forbidden(game, source):
        return None
    return f"{_name(source)}'s activated abilities can't be activated this turn"


def _nonmana_shut_off_this_turn(game, seat, source, ability):
    # "Until end of turn, … that player can't activate abilities that aren't
    # mana abilities." (Abeyance.) A record on the seat, so it reaches an
    # ability wherever its source is.
    from .spell_prohibitions import nonmana_activations_forbidden

    if not nonmana_activations_forbidden(game, seat) or _is_mana(ability):
        return None
    return (
        f"{_name(source)}'s ability can't be activated: "
        f"{game.players[seat].name} can't activate "
        "abilities that aren't mana abilities this turn"
    )


def _own_turn_only(game, seat, source, ability):
    # "Players can cast spells and activate abilities only during their own
    # turns." (City of Solitude.) The activation half of the one sentence
    # ``cast_prohibitions`` reads for its casting half, through the same
    # reader. No mana-ability exception: the sentence names none.
    from .cast_restrictions import global_play_timing

    wrong_turn = global_play_timing(game, seat)
    if wrong_turn is None:
        return None
    return (
        f"{_name(source)}'s abilities can't be activated on "
        f"another player's turn ({wrong_turn})"
    )


def _combat_ban(game, seat, source, ability):
    # "During combat, players can't cast instant spells or **activate
    # abilities that aren't mana abilities**." (Hand to Hand.)
    from .cast_restrictions import combat_play_ban

    ban = combat_play_ban(game)
    if ban is None or _is_mana(ability):
        return None
    return f"{_name(source)}'s ability can't be activated during combat ({ban[0]})"


def _global_ban(game, seat, source, ability):
    # "Activated abilities of creatures can't be activated." (Cursed Totem.)
    # "Activated abilities of artifacts can't be activated." (Null Rod.)
    from .activation_restrictions import global_activation_ban

    banned_by = global_activation_ban(game, source)
    if banned_by is None:
        return None
    return f"{_name(source)}'s activated abilities can't be activated ({banned_by})"


def _printed_restriction(game, seat, source, ability):
    # Every printed "Activate only …" clause on *this* ability line
    # (``engine/activation_restrictions.py``).
    from .activation_restrictions import activation_denial

    denial = activation_denial(game, seat, source, ability.source_line or "")
    if denial is None:
        return None
    return f"{_name(source)}: {denial}"


def _printed_permission(game, seat, source, ability):
    # "Only your opponents may activate this ability" (Clergy of the Holy
    # Nimbus) and the rest of ``engine/activation_permissions.py``.
    from .activation_permissions import activation_permission_denial

    return activation_permission_denial(game, seat, source, ability.source_line or "")


def _aura_nonmana_shut_off(game, seat, source, ability):
    # "…and its activated abilities can't be activated unless they're mana
    # abilities." (Faith's Fetters.)
    from .auras import aura_restriction_active

    if not aura_restriction_active(source, "activated_abilities_shut_off"):
        return None
    if _is_mana(ability):
        return None
    return f"{_name(source)}'s activated abilities can't be activated"


def _aura_all_shut_off(game, seat, source, ability):
    # "…and its activated abilities can't be activated." (Volrath's Curse.)
    # The clause above with CR 605.1a's exception **not** printed.
    from .auras import aura_restriction_active

    if not aura_restriction_active(source, "all_activated_abilities_shut_off"):
        return None
    return f"{_name(source)}'s activated abilities can't be activated"


def _tap_abilities_shut_off(game, seat, source, ability):
    # "…and their activated abilities **with {T} in their costs** can't be
    # activated." (Katabatic Winds.) The narrowing is on the cost.
    from .oracle import compile_card_oracle
    from .subject_filters import subject_matches

    if not ability.cost.requires_tap:
        return None
    for source_seat, watcher in game.permanents_with_controller():
        for instr in compile_card_oracle(watcher.effective_card).instructions:
            if instr.kind != "tap_abilities_cant_be_activated":
                continue
            if not subject_matches(
                game, source, dict(instr.payload.get("subject") or {}),
                observer=source_seat, source=watcher,
            ):
                continue
            return (
                f"{_name(source)}'s activated abilities with {{T}} in "
                f"their costs can't be activated ({watcher.card.name})"
            )
    return None


_ON_THE_BATTLEFIELD = frozenset({PERMANENT})
_ANYWHERE = frozenset({PERMANENT, CARD})

#: Every CR 602.5 prohibition the engine enforces, **in the order the
#: activation path asks them**. Adding one is adding a row: the activation
#: path (all three of its doors), the AI's chooser, the wire's ability lists
#: and the payment preview read this table and nothing else.
#: ``tests/engine/test_activation_prohibition_readers.py`` holds a scenario
#: per row and fails on a row without one.
ACTIVATION_PROHIBITIONS: tuple[ProhibitionRow, ...] = (
    ProhibitionRow("permanent_shut_off_this_turn", _ON_THE_BATTLEFIELD, _permanent_shut_off_this_turn),
    ProhibitionRow("nonmana_shut_off_this_turn", _ANYWHERE, _nonmana_shut_off_this_turn),
    ProhibitionRow("global_play_timing", _ANYWHERE, _own_turn_only),
    ProhibitionRow("combat_play_ban", _ANYWHERE, _combat_ban),
    ProhibitionRow("global_activation_ban", _ON_THE_BATTLEFIELD, _global_ban),
    ProhibitionRow("printed_restriction", _ANYWHERE, _printed_restriction),
    ProhibitionRow("printed_permission", _ON_THE_BATTLEFIELD, _printed_permission),
    ProhibitionRow("aura_nonmana_shut_off", _ON_THE_BATTLEFIELD, _aura_nonmana_shut_off),
    ProhibitionRow("aura_all_shut_off", _ON_THE_BATTLEFIELD, _aura_all_shut_off),
    ProhibitionRow("tap_abilities_shut_off", _ON_THE_BATTLEFIELD, _tap_abilities_shut_off),
)


def activation_prohibition(
    game: "Game", seat: int, source, ability
) -> ActivationProhibition | None:
    """What forbids *seat* activating *ability* of *source* now, or None.

    *source* is the permanent the ability is on, or — for an ability that
    functions in another zone (CR 113.6) — the card itself. The first row of
    :data:`ACTIVATION_PROHIBITIONS` that binds that kind of source and
    refuses: the same prohibition, in the same words, the activation path
    logs. Pure: it reads the board and the turn's records and changes neither,
    so the AI may ask it of every ability on a battlefield and the wire on
    every poll.
    """
    where = PERMANENT if hasattr(source, "card") else CARD
    for row in ACTIVATION_PROHIBITIONS:
        if where not in row.binds:
            continue
        details = row.ask(game, seat, source, ability)
        if details is not None:
            return ActivationProhibition(row.kind, details)
    return None


__all__ = [
    "ACTIVATION_PROHIBITIONS", "ActivationProhibition", "CARD", "PERMANENT",
    "ProhibitionRow", "activation_prohibition",
]
