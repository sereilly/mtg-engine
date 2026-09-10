"""Lowering CR 701.12's **exchange** of control: two sides swapping at once.

Split out of ``control_changes`` when that module crossed the thousand-line
guard at Mercadian Masques' wave 1, and the seam is the one that module's own
first line already draws — "CR 613 layer 2, **and** CR 701.12's exchange". Two
subjects, named in a title, and the half that grows with the pool is the layer-2
one: every new steal, duration and link lands in ``_lower_gain_control``, while
these three have been stable since Exodus.

The two are one *subject* — an exchange of control is a control change made
atomic (CR 701.12a), which is why ``control_changes`` took Juxtapose's paragraph
in rather than leaving it in ``board`` — and one subject is what a family is,
not what a file is. ``lowering/ownership.py`` is the same move one rule over:
CR 108.3's exchange left ``zones`` while still answering "where does this card
end up", and it is deliberately **not** where these belong, because ownership is
not control (CR 400.3 — control moves and ownership never did).

What every function here has that ``control_changes`` has none of is the
**atomicity**: CR 701.12a makes a whole exchange happen or none of it, so each
lowering describes *both* sides in one payload and refuses a sentence whose two
halves it cannot carry together. A one-sided hand-over has nothing to be atomic
about.

The parse half stays whole in ``effects/control_changes.py`` (329 lines,
crossing nothing), which is the arrangement ``zones``, ``library``, ``mana`` and
``redirection`` already have: a lowering family may outgrow its parse family
without the parse family having to split with it.
"""

from __future__ import annotations

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (_optional_slot_key, _describe_targets, _filter_payload,
                      _is_source, _is_target)


def _lower_exchange_control(node: ast.ExchangeControl) -> tuple[OracleInstruction, ...]:
    """"Exchange control of target artifact, creature, or land you control and
    target permanent an opponent controls…" (Gauntlets of Chaos, CR 701.12b.)

    Two chosen slots, described the way the two-target pump describes its pair:
    ``filters`` carries one filter per slot so the picker can enumerate both
    halves and the handler can re-check each at resolution (CR 608.2b), while
    ``filter`` stays the shape every one-slot reader already expects.

    ``shares_type`` and the printed type list travel as payload rather than as
    part of the kind, because a card exchanging (say) two enchantments would be
    this same effect with a different noun phrase.
    """
    # "Exchange control of **this creature** and up to one target creature an
    # opponent controls." (Gilded Drake.) The first side is not chosen at all:
    # it is the ability's own source, which the resolution already holds. So
    # there is **one** chosen slot, and describing it as one is the whole of
    # what this branch is for — a two-slot description would raise a two-step
    # picker for a card that prints one "target", and the announcement gate
    # would then ask for a permanent the card never named.
    #
    # Everything downstream is the same effect: CR 701.12b's exchange, with
    # CR 701.12a's atomicity, the cross-slot Guardian Beast check and the
    # same-controller early exit all unchanged. Which permanent fills slot 0 is
    # payload, exactly as ``shares_a_type`` and the printed type list are — a
    # second card exchanging itself for something would be this same sentence
    # with a different noun phrase on the far side.
    if (
        isinstance(node.first, ast.TargetSpec)
        and _is_source(node.first)
        and isinstance(node.second, ast.TargetSpec)
        and _is_target(node.second)
    ):
        described: dict[str, object] = {
            "first": "source",
            # The printed noun on the source's side, re-checked at resolution
            # for the reason the two-slot branch re-checks both of its own:
            # CR 701.12a makes the exchange atomic, so a side that no longer
            # answers its own noun phrase means no part of it happens.
            "first_filter": _filter_payload(node.first.filter),
            "shares_a_type": bool(node.shares_a_type),
            "destroy_attached_auras": bool(node.destroy_attached_auras),
        }
        # The ordinary one-target description, so the picker, the announcement
        # gate and ``engine/targeting.py`` all read this slot the way they read
        # every other single target — including the "up to" that lets it be
        # left empty (CR 601.2c), which on this card is what the sentence
        # behind the exchange is about.
        _describe_targets(described, node.second)
        if "targets" not in described:
            raise LoweringError(
                "an exchange with the source on one side needs a chosen "
                "permanent on the other", node=node,
            )
        return (OracleInstruction("exchange_control_of_targets", "", described),)
    if not isinstance(node.first, ast.TargetSpec) or not _is_target(node.first):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    if not isinstance(node.second, ast.TargetSpec) or not _is_target(node.second):
        raise LoweringError(
            "an exchange of control needs a chosen permanent on each side", node=node
        )
    first = _filter_payload(node.first.filter)
    second = _filter_payload(node.second.filter)
    payload: dict[str, object] = {
        "targets": {
            "quantifier": "target",
            "kind": "object",
            "filter": first,
            "filters": [first, second],
            "count": 2,
            **_optional_slot_key((node.first, node.second)),
            # Two permanents on two battlefields are distinct by construction,
            # but saying so is what stops one player's own permanent filling
            # both slots if a later card drops the controller words.
            "distinct": True,
        },
        # The relation between the slots (see the node's docstring), and the
        # types it is measured over — "one of **those** types" is the first
        # slot's printed list, so it is read off that filter rather than
        # spelled out again here.
        "shares_a_type": bool(node.shares_a_type),
        "destroy_attached_auras": bool(node.destroy_attached_auras),
    }
    return (OracleInstruction("exchange_control_of_targets", "", payload),)


#: The seat words the mutual control change can resolve at run time. Each is a
#: seat the *announcement* settled — the spell chose it (CR 601.2c) or the
#: sentence in front of this one did — which is what the handler's two-step
#: reader answers. A word outside this set names a seat nothing in the
#: resolution holds, and admitting one would swap creatures with whichever
#: player the resolution happened to be carrying.
_MUTUAL_CONTROL_SEATS = frozenset({
    "that_player", "target_player", "target_opponent",
})


def _lower_mutual_control_of_sets(
    node: ast.MutualControlOfSets,
) -> tuple[OracleInstruction, ...]:
    """``You and <player> each gain control of all <noun> the other controls
    until end of turn.`` (Reins of Power.)

    One instruction rather than two ``gain_control_until_eot`` steps, because
    CR 611.2c fixes both sets when the effect begins: run in sequence the second
    step would read a board the first had already changed and hand back the very
    creatures it had just taken. This is Sands of Time's "simultaneously" one
    effect over, and the same answer — the handler gathers both sides before it
    records anything.

    The duration is a *kind*, exactly as it is for the single steal beside this
    one: cleanup drops a contribution stamped ``until_eot`` and leaves any other
    alone (CR 611.2a), and a payload flag would let a lowering that forgot it
    record a swap that quietly ends at cleanup. There is one kind here because
    there is one lifetime implemented; the untimed printing refuses by name
    rather than borrowing this one.
    """
    if node.duration != "until_end_of_turn":
        raise LoweringError(
            "a mutual control change is implemented only until end of turn",
            node=node,
        )
    seat = node.other.kind
    if seat not in _MUTUAL_CONTROL_SEATS:
        raise LoweringError(
            f"no seat the resolution holds answers to {seat!r}", node=node
        )
    described = _filter_payload(node.filter)
    # The noun phrase is asked of both boards, so it must be a phrase the
    # matcher can test about a permanent alone: the seat halves are the two the
    # node already names, and a printed "you control" inside the phrase would be
    # a third seat the reciprocity has no room for.
    if object_only_filter(described) is None:
        raise LoweringError(
            "the mutual control change cannot test this restriction", node=node
        )
    return (
        OracleInstruction(
            "exchange_control_of_sets_until_eot", "",
            {"filter": described, "other_seat": seat},
        ),
    )


# Juxtapose's paragraph joined this family at Exodus's second wave, when
# ``lowering/board.py`` crossed the thousand-line guard. It is the mirror
# re-forming rather than a new home: ``ExchangeGreatestManaValue`` moved to
# ``ast/control_changes.py`` in the same commit, and ``_lower_exchange_control``
# has sat here since the family existed — an exchange of control is a control
# change made atomic (CR 701.12a), which is this module's subject and not
# ``board``'s.


def _lower_exchange_greatest_mana_value(
    node: ast.ExchangeGreatestManaValue,
) -> tuple[OracleInstruction, ...]:
    """Juxtapose's paragraph → a ``sequence`` of ordinary instructions.

    Three steps per printed type, and none of them is new machinery: each side
    of the exchange is a ``choose_permanent`` narrowed to "the <type> that seat
    controls with the greatest mana value", and the exchange itself reads the
    two ids those steps recorded. Writing it as one fused kind would have hidden
    the tie-break sentence inside a handler; written this way the sentence *is*
    the prompt, and ``only_on_tie`` is the printed condition under which it is
    asked — with one candidate there is nothing to choose and no prompt is made.

    The two seats are the spell's controller and its chosen player, which is why
    the second choice's ``chooser`` is ``target``: CR 701.12 leaves the pick to
    each permanent's own controller, and the card says so.
    """
    steps: list[OracleInstruction] = []
    for card_type in node.card_types:
        keys = []
        for side, chooser in (("you", "you"), ("target", "target")):
            key = f"exchanged_{card_type}_{side}"
            keys.append(key)
            steps.append(
                OracleInstruction(
                    "choose_permanent", "",
                    {
                        "result_key": key,
                        "filter": {"type_filter": card_type},
                        "controlled_by": chooser,
                        # CR 202.3's "greatest mana value", as the two payload words
                        # ``ast.Superlative`` gives every printed superlative. It was
                        # ``greatest_mana_value: True`` — one corner of the phrase
                        # spelled into a flag of its own, which a card printing
                        # "least toughness" could not reuse.
                        "superlative": {"extreme": "greatest", "characteristic": "mana_value"},
                        "only_on_tie": True,
                        "chooser": chooser,
                        "prompt": (
                            f"Choose which {card_type} with the greatest mana "
                            "value to exchange."
                        ),
                    },
                )
            )
        steps.append(
            OracleInstruction(
                "exchange_control_of_bound", "",
                {"first_from": keys[0], "second_from": keys[1]},
            )
        )
    return (OracleInstruction("sequence", "", {"steps": tuple(steps)}),)
