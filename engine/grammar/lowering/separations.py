"""Lowering for "separate … into two piles" (CR 700.3).

One instruction, ``separate_into_piles``, however the paragraph was printed:
what is separated, whose it is, who separates, who chooses and the two fates are
all payload, and ``engine/piles.py`` is the one procedure that reads them. The
split, the choice and the fates stay one step for the reason
``_lower_reveal_top_opponent_chooses`` gives one family over — the choice is
made **between** the piles the split made and the fates are what the choice was
for — while the *pick of an opponent* in front of them is an ordinary step of
its own (``choose_opponent``), because a pick with one answer at two seats is a
prompt at four and a handler that has to stop and ask cannot also finish the
sentence.

Everything this module refuses is a word the procedure has no seat for. A
refused seat on a pile is not a card that does less: the piles would be made
out of the wrong player's permanents.
"""

from __future__ import annotations

import dataclasses

from ...oracle_types import OracleInstruction
from .. import ast
from ..errors import LoweringError
from ._common import _amount_payload, testable_filter_payload
from ._events import _EVENT_SUBJECT_PLAYERS
from ._filters import chargeable_card_filter
from ._record_keys import CHOSEN_PLAYER


#: What a pile may be sent to do, by what it is a pile *of*. Closed, and held
#: equal to what ``engine/piles.py`` performs: a fate named here with no
#: performer there would be admitted and then dropped.
_FATES: dict[str, frozenset[str]] = {
    "library_top": frozenset({"hand", "graveyard"}),
    "graveyard": frozenset({"exile", "battlefield"}),
    "battlefield": frozenset({"destroy", "tap", "only_attackers", "only_blockers"}),
}

#: Whose permanents a battlefield split may name, and what each word needs.
_BATTLEFIELD_SEATS = frozenset({
    "target_player", "that_player", "each_player", "each_defending_player",
})

_SEPARATORS = frozenset({"you", "an_opponent", "owner"})
_CHOOSERS = frozenset({"you", "an_opponent", "owner", "owner_opponent"})


def _lower_separate_into_piles(
    node: "ast.SeparateIntoPiles", event: str | None,
) -> tuple[OracleInstruction, ...]:
    """The whole CR 700.3 paragraph, as one instruction plus the opponent pick
    it may need in front of it.

    Fact or Fiction, Do or Die, Death or Glory, Bend or Break, Fight or Flight
    and Stand or Fall — six printings, one payload shape.
    """
    if node.separator not in _SEPARATORS:
        raise LoweringError(
            f"no pile split is separated by {node.separator!r}", node=node
        )
    if node.chooser not in _CHOOSERS:
        raise LoweringError(
            f"no pile split is chosen between by {node.chooser!r}", node=node
        )
    fates = _FATES.get(node.what)
    if fates is None:
        raise LoweringError(f"nothing separates {node.what!r} into piles", node=node)
    for fate in (node.chosen_fate, node.other_fate):
        if fate is not None and fate not in fates:
            raise LoweringError(
                f"a pile of {node.what} objects has no {fate!r} fate", node=node
            )
    if node.no_regeneration and node.chosen_fate != "destroy":
        raise LoweringError(
            "'can't be regenerated' follows a pile that is not destroyed",
            node=node,
        )
    payload: dict[str, object] = {
        "what": node.what,
        "whose": node.whose,
        "separator": node.separator,
        "chooser": node.chooser,
        "chosen": node.chosen_fate,
    }
    if node.other_fate is not None:
        payload["other"] = node.other_fate
    if node.no_regeneration:
        payload["no_regeneration"] = True

    if node.what == "library_top":
        count = _amount_payload(node.count) if node.count is not None else None
        if not isinstance(count, int) or count <= 0:
            raise LoweringError(
                "the revealed pile is a fixed number of cards", node=node
            )
        if node.whose != "you":
            raise LoweringError(
                "only the controller's own library is separated", node=node
            )
        payload["count"] = count
    elif node.what == "graveyard":
        if node.whose != "you" or node.filter is None:
            raise LoweringError(
                "only the controller's own graveyard is separated", node=node
            )
        # The zone words have been read into ``what`` / ``whose`` above, so
        # they are honoured rather than dropped; what is left is the card
        # phrase the graveyard matcher answers.
        described = chargeable_card_filter(
            dataclasses.replace(node.filter, zone="battlefield", zone_owner=None)
        )
        if described is None:
            raise LoweringError(
                "no graveyard matcher can test the separated cards", node=node
            )
        payload["filter"] = described
    else:
        if node.whose not in _BATTLEFIELD_SEATS or node.filter is None:
            raise LoweringError(
                f"no pile split names {node.whose or 'nobody'!r}'s permanents",
                node=node,
            )
        if node.whose == "that_player" and event not in _EVENT_SUBJECT_PLAYERS:
            # "That player" is the seat a trigger's event names (CR 603.10).
            # With no such event there is nobody the phrase means, and reading
            # it as the controller would separate the wrong board.
            raise LoweringError(
                "'that player' names no seat outside a trigger about a player",
                node=node,
            )
        # The seat word has been read into ``whose``; the rest of the phrase
        # is asked of each permanent, with CR 109.5's observer.
        payload["filter"] = testable_filter_payload(
            dataclasses.replace(node.filter, controller=None),
            refusal="the pile split cannot test this restriction",
            node=node,
            require_narrowing=False,
        )
        if node.whose == "target_player":
            payload["targets"] = {"quantifier": "target", "kind": "player"}

    steps: list[OracleInstruction] = []
    if "an_opponent" in (node.separator, node.chooser):
        # CR 608.2d: an opponent nobody named is the controller's pick, made
        # as the effect is applied — the step every "an opponent …" sentence
        # in this grammar puts in front of itself, writing the key the pile
        # procedure then reads.
        steps.append(
            OracleInstruction(
                "choose_opponent", "",
                {
                    "result_key": CHOSEN_PLAYER,
                    "prompt": (
                        "Choose an opponent to separate the piles."
                        if node.separator == "an_opponent"
                        else "Choose an opponent to choose a pile."
                    ),
                },
            )
        )
    steps.append(OracleInstruction("separate_into_piles", "", payload))
    return tuple(steps)
