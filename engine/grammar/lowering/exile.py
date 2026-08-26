"""Lowering exile (CR 406): the objects a spell puts *outside* the game state.

Split out of `lowering/zones.py` at the thousand-line guard, the round two
branches both added to it. A family rather than an arbitrary cut, on the same
reasoning the parent file gives for its own split from `board`: exile is the one
zone whose lowering has to decide not just *where* an object goes but whether it
comes back, under what event, and carrying what with it — the linked-exile
record (`engine/linked_exile.py`), the until-leaves and until-untaps forms, and
the fused shapes that pair an exile with something done to its controller. None
of that touches the hand/library/battlefield movement the rest of `zones` reads.

Like its parent it has no twin in `effects/`, and for the same stated reason:
the parse side is one `exile` production in `effects/board.py`, while the work
here is choosing among handlers and refusing the shapes none of them implement.
"""

from __future__ import annotations

import dataclasses
from ...oracle_types import OracleInstruction
from ...subject_filters import OBJECT_ONLY_FILTER_KEYS
from .. import ast
from ..errors import LoweringError
from ._events import CREATED_TOKEN
from ._common import (
    _PAYLOAD_HONOURED_FILTER_FIELDS, _describe_targets, _filter_payload,
    _is_created_token, _is_source, _restrictions_beyond, dropped_narrowings,
)


_EXILED_CREATURE = ast.ObjectFilter(card_types=("creature",))


def _lower_exile(
    node: ast.Exile, produced: frozenset[str] = frozenset()
) -> tuple[OracleInstruction, ...]:
    """"Exile target creature until end of turn." — and nothing else.

    ``exile_target_creature_until_eot`` is the one exile handler that stands on
    its own: it moves the creature to exile and records the return
    (CR 406.1/400.7), so the whole sentence is what it performs. Every part of
    the clause is checked against that rather than dropped —

    * **the duration.** Without it the sentence is a *permanent* exile, which
      this handler does not perform: it would return the creature at cleanup.
    * **the subject.** A chosen creature, not a sweep and not the source: the
      handler resolves one target permanent.

    A duration this file does not implement is refused rather than falling
    through to the permanent exile below. "Exile it until this creature leaves
    the battlefield" is a different effect, and lowering it onto a permanent
    exile would be the loudest possible mis-play: the card would never come
    back.

    With no duration the sentence is a permanent exile, and *which* handler
    performs it is a question about the zone the subject names:

    * **the battlefield** — ``exile_target_permanent``. The permanent leaves
      through ``remove_from_battlefield`` and its card goes to its owner's
      exile (CR 400.3, CR 406.1).
    * **a graveyard** — ``exile_target_graveyard_card``. No permanent is
      involved, so the battlefield-scoped filter payload would point both the
      handler and engine/targeting.py at the wrong zone; ``_filter_payload``
      already refuses that shape, which is why this branch comes first.

    ``exile_creature_gain_life_equal_to_power`` stays unreachable from here: it
    performs *both* halves of Swords to Plowshares' sentence, so a bare
    ``Exile`` lowering onto it would gain life the card never offered.
    """
    if node.duration.kind in ("until_end_of_turn", "this_turn"):
        subject = node.subject
        if (
            isinstance(subject, ast.TargetSpec)
            and subject.quantifier == "target"
            and subject.count == 1
            and subject.filter == _EXILED_CREATURE
        ):
            payload: dict[str, object] = {}
            _describe_targets(payload, subject)
            return (OracleInstruction("exile_target_creature_until_eot", "", payload),)
        raise LoweringError(
            "the temporary-exile handler resolves one targeted creature", node=node
        )
    if node.duration.kind is not None:
        raise LoweringError(
            f"no handler exiles for the duration {node.duration.kind!r}", node=node
        )

    subject = node.subject
    if isinstance(subject, ast.TargetSpec) and subject.quantifier in ("each", "all"):
        # "Exile each permanent with mana value X or less that's one or more
        # colors." (Ugin, the Spirit Dragon's −X.) The payload is hand-rolled:
        # ``to_payload`` cannot carry a *variable* mana-value bound, and
        # dropping the bound would widen the sweep to every mana value.
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError("the exile sweep reads battlefield permanents", node=node)
        payload: dict[str, object] = {}
        # Two keys the ordinary filter payload has no form for, lifted off the
        # filter before the rest of it is read the way every other sweep reads
        # one. ``mana_value`` because the bound may be the spell's **X**, which
        # is not a number until the ability resolves; ``colored`` because
        # "that's one or more colors" is a question about the computed colours
        # rather than about a named one.
        if filt.colored:
            payload["colored_only"] = True
        if filt.mana_value is not None:
            bound = filt.mana_value.value
            payload["mana_value"] = {
                "op": filt.mana_value.op,
                "value": bound.value if isinstance(bound, ast.Fixed) else bound.name,
            }
        rest = dataclasses.replace(filt, colored=False, mana_value=None)
        # Everything else the noun phrase printed — "exile all **Sand
        # Warriors**" (Hazezon Tamar). The sweep used to hand-roll a
        # ``type_filter`` and refuse every other narrowing, which cost Hazezon
        # its second ability; the honest widening is to carry the payload the
        # matcher already answers and refuse only what it cannot test.
        #
        # ``OBJECT_ONLY_FILTER_KEYS``, not the full testable set: the handler
        # sweeps every battlefield with no observer seat and no source
        # permanent, so "you control" and "another" have nothing to be relative
        # to and would be dropped where they are tested.
        narrowings = _filter_payload(rest)
        unusable = sorted(set(narrowings) - OBJECT_ONLY_FILTER_KEYS)
        leftovers = _restrictions_beyond(
            rest, _PAYLOAD_HONOURED_FILTER_FIELDS | {"zone"}
        ) + dropped_narrowings(rest, narrowings) + tuple(unusable)
        if leftovers:
            raise LoweringError(
                f"the exile sweep does not honour {leftovers[0]!r}", node=node
            )
        payload.update(narrowings)
        return (OracleInstruction("exile_all_matching", "", payload),)
    if isinstance(subject, ast.TargetSpec) and subject.quantifier == "any_number":
        # "Exile **any number of** tokens created with this creature."
        # (Tetravus.) Not a sweep and not a target: the controller says how
        # many, at resolution (CR 115.1b — nothing is chosen until then), and
        # the sentence after it reads the number back.
        filt = subject.filter
        if filt.zone != "battlefield" or filt.is_card:
            raise LoweringError(
                "the counted exile reads battlefield permanents", node=node
            )
        if not filt.token_only or not filt.created_with_source:
            # Deliberately narrow. The handler resolves the set itself, and the
            # only set it knows how to find is "the tokens this permanent made"
            # — a wider phrase admitted here would be exiled from a list the
            # handler never narrowed.
            raise LoweringError(
                "the counted exile knows only the tokens this permanent created",
                node=node,
            )
        leftovers = _restrictions_beyond(
            filt, frozenset({"token_only", "created_with_source", "zone"})
        )
        if leftovers:
            raise LoweringError(
                f"the counted exile does not honour {leftovers[0]!r}", node=node
            )
        return (OracleInstruction("exile_any_number_of_own_tokens", "", {}),)
    # "Exile it." / "Exile this creature." (Archfiend's Vessel.) The ability's
    # own source, which is not a chosen target at all — nothing is picked, so
    # there is no picker, no legality check and nothing to re-resolve if it has
    # moved. It gets its own instruction kind for that reason rather than a
    # payload flag on the targeted exile: a handler that resolves a target and
    # one that reads ``context.source_permanent`` share no code beyond the move.
    if _is_source(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of the source has no handler", node=node
            )
        return (OracleInstruction("exile_self", "", {}),)
    # "Exile **that token**…" (Stangg). The token this same effect created,
    # addressed by the id the token maker wrote to the scratchpad — not a
    # chosen target and not the source, so it gets its own kind for the reason
    # ``exile_self`` has one: a handler that reads a recorded id and one that
    # resolves a target share nothing beyond the move.
    #
    # ``produced`` is the whole gate. With no token maker in front of it there
    # is no id to read, and an exile that silently found nothing would be a
    # card that reports itself supported and does nothing.
    if _is_created_token(subject):
        if node.duration.kind is not None:
            raise LoweringError(
                "a timed exile of a created token has no handler", node=node
            )
        if CREATED_TOKEN not in produced:
            raise LoweringError(
                "back-reference to a created token with no token maker in "
                "this effect",
                node=node,
            )
        return (OracleInstruction("exile_created_token", "", {}),)
    if (
        not isinstance(subject, ast.TargetSpec)
        or subject.quantifier != "target"
        or subject.count != 1
    ):
        # A sweep with no handler and a bare "exile it" are separate effects;
        # only the shapes above are implemented.
        raise LoweringError(
            "only a single chosen permanent or card is exiled", node=node
        )

    filt = subject.filter
    if filt.zone == "graveyard" and filt.is_card:
        if filt.zone_owner is not None or filt.card_types or filt.subtypes or filt.colors:
            # The picker this lowers onto enumerates *any* card in *any*
            # graveyard. Narrowing it is a payload-derived spec, not something
            # to fake by dropping the narrowing here.
            raise LoweringError(
                "no graveyard picker narrows to this card or this player yet",
                node=node,
            )
        return (
            OracleInstruction("exile_target_graveyard_card", "", {"any_card": True}),
        )

    exile_payload = _filter_payload(filt)
    _describe_targets(exile_payload, subject)
    return (OracleInstruction("exile_target_permanent", "", exile_payload),)


def _lower_exile_until_leaves_or_untaps(
    node: "ast.ExileUntilLeavesOrUntaps",
) -> tuple[OracleInstruction, ...]:
    """Tawnos's Coffin. Everything the sentence says is fixed by the production
    that read it, so the payload carries only the picker's description."""
    payload: dict[str, object] = {"type_filter": "creature"}
    _describe_targets(payload, node.subject)
    return (OracleInstruction("exile_until_leaves_or_untaps", "", payload),)


def _fused_exile_then_controller_life(
    steps: tuple[ast.Statement, ...]
) -> tuple[OracleInstruction, ...] | None:
    """"Exile target creature. Its controller gains life equal to its power."
    (Swords to Plowshares.)

    Fused because the handler is: it pops the creature off the battlefield and
    reads ``effective_power`` from the object it just removed, which no pair of
    independent instructions can do — the second one would be looking for a
    permanent that is no longer there. Every part of the shape is checked
    against what that handler implements, so a card exiling something else, or
    paying the life to someone else, falls through and is refused by
    :func:`_lower_exile` rather than borrowing this.

    Returning None rather than raising leaves a near miss to be reported
    against the effect it actually failed on.
    """
    if len(steps) != 2:
        return None
    exile, gain = steps
    if not isinstance(exile, ast.Exile) or not isinstance(gain, ast.GainLife):
        return None
    subject = exile.subject
    if not isinstance(subject, ast.TargetSpec) or subject.quantifier != "target":
        return None
    if subject.filter != _EXILED_CREATURE:
        return None
    if gain.player.kind != "controller":
        return None
    if gain.amount != ast.ThatMuch("its_power"):
        return None
    return (OracleInstruction("exile_creature_gain_life_equal_to_power", "", {}),)
