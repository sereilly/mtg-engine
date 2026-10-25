"""Face-down permanents acted on by an effect (CR 708): turned face down,
turned face up, and looked at.

The status itself is ``engine/face_down.py``'s — a face-down permanent's card
*is* the blank 2/2 with the real card riding on it — and so are the two seams
these handlers call, :func:`~engine.face_down.turn_face_down` and
:func:`~engine.face_down.turn_face_up`. What is here is the effect half: which
permanent the sentence names (the target the picker offered, re-asked at
resolution through ``subject_matches`` so "target face-down creature an
opponent controls" is held to every word, CR 608.2b), and what a look shows to
whom (CR 708.5's exception for an effect that lets a player look).

``engine.face_down`` is imported inside each handler rather than at the top:
it registers a special action as it loads, and this package loads far earlier
than it does, so a top-level import would move it in the load order
(``engine/late_modules.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent
    from ..oracle import OracleInstruction


def _named_target(game: "Game", instruction: "OracleInstruction",
                  context: "OracleExecutionContext") -> "Permanent | None":
    """The permanent a "turn target …" / "look at target …" sentence names,
    held to its printed noun phrase as it resolves.

    Through ``subject_matches`` with the resolving seat as the observer, the
    reader ``tap_or_untap_target`` uses for its reason: "an opponent controls"
    (Break Open) is a seat comparison, and "face-down" is a status that can
    change while the object waits on the stack — Nosy Goblin's 2004-10-04
    ruling, "If the target is turned face up before the ability resolves, the
    creature is no longer a legal target", is this test failing. A chosen
    permanent that no longer answers resolves to nobody rather than sliding
    onto another one.
    """
    from ..subject_filters import subject_matches

    described = {
        key: value for key, value in instruction.payload.items() if key != "targets"
    }
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    return resolve_target_permanent(
        game, context,
        predicate=lambda p: subject_matches(
            game, p, described, observer=observer, source=context.source_permanent,
        ),
        fallback_on_invalid_choice=False,
    )


@effect_handler("turn_target_face_down")
def turn_target_face_down(game: "Game", instruction: "OracleInstruction",
                          context: "OracleExecutionContext") -> tuple[bool, str]:
    """"Turn target creature with a morph ability face down." (Backslide.)

    CR 708.2a: a 2/2 with no text, no name, no subtypes and no mana cost, and
    the same object — counters, damage, Auras and tapped state all stay. Its
    morph cost turns it face up again (CR 702.37e), which the special action
    offers off the hidden card.
    """
    from ..face_down import turn_face_down

    permanent = _named_target(game, instruction, context)
    if permanent is None:
        game.log.append(f"{context.card.name}: no creature to turn face down")
        return True, "resolved"
    if not turn_face_down(game, permanent):
        # CR 708.2b: "If a spell or ability attempts to turn a face-down
        # permanent face down, nothing happens."
        game.log.append(f"{context.card.name}: it is already face down")
    return True, "resolved"


@effect_handler("turn_self_face_down")
def turn_self_face_down(game: "Game", instruction: "OracleInstruction",
                        context: "OracleExecutionContext") -> tuple[bool, str]:
    """"…turn this creature face down." (Skittish Valesk.)

    The ability's own source, if it is still the permanent the ability came
    from (CR 400.7: one that left and returned is a new object the ability
    knows nothing of). Already face down, nothing happens (CR 708.2b).
    """
    from ..face_down import turn_face_down

    permanent = context.source_permanent
    if permanent is None or not game.is_on_battlefield(permanent):
        game.log.append(f"{context.card.name}: it is no longer on the battlefield")
        return True, "resolved"
    if not turn_face_down(game, permanent):
        game.log.append(f"{context.card.name}: it is already face down")
    return True, "resolved"


@effect_handler("turn_target_face_up")
def turn_target_face_up(game: "Game", instruction: "OracleInstruction",
                        context: "OracleExecutionContext") -> tuple[bool, str]:
    """"Turn target face-down creature face up." (Ixidor, Reality Sculptor;
    Break Open's "an opponent controls".)

    Without paying anything — Break Open (2004-10-04): "The player does not
    have to pay the Morph cost (if any) of the creature"; Ixidor (2004-10-04):
    "its controller does not have to pay its Morph cost" — so a face-down
    permanent with no morph cost at all (Illusionary Mask's) turns face up too
    (CR 708.7 is about the rules that *allow* a controller to turn it; an
    effect that says to is not one of them). The reveal is public: what turns
    face up is face up for the whole table.
    """
    from ..face_down import turn_face_up

    permanent = _named_target(game, instruction, context)
    if permanent is None:
        game.log.append(f"{context.card.name}: no face-down creature to turn face up")
        return True, "resolved"
    if not turn_face_up(game, permanent, how=context.card.name):
        game.log.append(f"{context.card.name}: it is already face up")
    return True, "resolved"



def _show_face_down(game: "Game", context: "OracleExecutionContext", permanents,
                    whose: str) -> None:
    """Arm the looker's private look at *permanents* and say that it happened —
    never what was seen (CR 708.5; ``game.log`` is sent to every seat)."""
    viewer = context.caster
    viewer_index = game.players.index(viewer)
    game.arm_face_down_look(viewer_index, permanents, source_name=context.card.name)
    game.log.append(
        f"{context.card.name}: {viewer.name} looked at {len(permanents)} "
        f"face-down creature(s) {whose} controls"
    )


@effect_handler("look_at_target_face_down")
def look_at_target_face_down(game: "Game", instruction: "OracleInstruction",
                             context: "OracleExecutionContext") -> tuple[bool, str]:
    """"Look at target face-down creature." (Aven Soulgazer.)

    The target re-asked as it resolves (CR 608.2b), so one turned face up in
    response is no longer a face-down creature and there is nothing to show —
    it is face up for everybody already.
    """
    permanent = _named_target(game, instruction, context)
    if permanent is None:
        game.log.append(f"{context.card.name}: no face-down creature to look at")
        return True, "resolved"
    seat = game.controller_index_of(permanent)
    whose = game.players[seat].name if seat is not None else "nobody"
    _show_face_down(game, context, [permanent], whose)
    return True, "resolved"


@effect_handler("look_at_face_down_creatures")
def look_at_face_down_creatures(game: "Game", instruction: "OracleInstruction",
                                context: "OracleExecutionContext") -> tuple[bool, str]:
    """"…and any face-down creatures they control." (Spy Network.)

    Every face-down creature the player the sentence targeted controls, read
    off the control seam as it resolves. "Any" admits none: a player with no
    face-down creature shows nothing and nothing is armed.
    """
    from ..face_down import is_face_down

    target = context.target
    if target is None or target not in game.players:
        return True, "resolved"
    seat = game.players.index(target)
    permanents = [
        permanent for permanent in game.controlled_by(seat)
        if is_face_down(permanent) and game._is_creature(permanent)
    ]
    if not permanents:
        game.log.append(
            f"{context.card.name}: {target.name} controls no face-down creatures"
        )
        return True, "resolved"
    _show_face_down(game, context, permanents, target.name)
    return True, "resolved"
