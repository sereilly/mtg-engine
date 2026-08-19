"""Lowering mana production: "Add {G}." and the tapped-land mana trigger.

The two kinds here are the whole of the "mana" migration category. They part
company at dispatch, which is why the trigger keeps its own kind: an activated
"{T}: Add {G}" resolves through EFFECT_HANDLERS, while the triggered mana
ability on a land being tapped (CR 605.1b) is resolved inline by
``Game.tap_land_for_mana``, because CR 605.4a says a triggered mana ability
never uses the stack.
"""

from ...oracle_types import OracleInstruction
from ...subject_filters import object_only_filter
from .. import ast
from ..errors import LoweringError
from ._common import (
    _amount_payload,
    _filter_payload,
)


def _lower_add_mana(node: ast.AddMana) -> tuple[OracleInstruction, ...]:
    """Emit the mana as structured pips rather than clause text.

    "Add one mana of any color" (Birds of Paradise, Celestial Prism) is the one
    player-chosen shape that lowers, and it is the exception that keeps the
    text. ``add_mana_from_text``'s any-colour branch is ``_add_mana_from_text``
    probing for the literal phrase "one mana of any color"; the chosen symbol
    arrives separately as ``color``, injected by mixins/stack/activation when
    ``any_color`` is set. Structured pips would say nothing the handler could
    read, so the clause rides along in ``oracle_text`` exactly as the legacy
    rule wrote it — which is what :attr:`ast.AddMana.source_text` exists for,
    and what keeps this payload byte-identical while the handler stays
    text-keyed.

    Any other count refuses. That probe recognizes *one* mana and no other
    number, so Black Lotus's "Add three mana of any one color" lowered here
    would add nothing while reporting success; it keeps its own fused
    ``sacrifice_self_for_mana`` handler on the legacy path.
    """
    if node.pips:
        # A printed "or" ships under its own key, never as bare ``pips``: a
        # reader that has not learned ``pips_choice`` then adds *nothing*
        # rather than every alternative, which is the failing-safe direction —
        # "Add {B} or {R}" making two mana is strictly worse than making none.
        key = "pips_choice" if node.choice else "pips"
        payload: dict[str, object] = {key: node.pips}
        if node.spend_only is not None:
            payload["spend_only"] = node.spend_only
        if node.per_each is not None:
            # The count is taken at resolution through the one evaluator every
            # computed amount shares, so "creature with power 4 or greater you
            # control" means the same set here as it does anywhere else.
            if node.per_each.controller != "you":
                raise LoweringError(
                    "the mana multiplier counts the producer's own board", node=node
                )
            described = _filter_payload(node.per_each)
            # "You control" is performed by the count's `owner`, which scans one
            # seat's battlefield — so it is carried rather than tested, the
            # arrangement `carried_separately` exists to name. Everything else
            # has to be answerable about a permanent alone, because that is what
            # the evaluator's matcher is.
            carried = object_only_filter(
                described, carried_separately=frozenset({"controller"})
            )
            if carried is None:
                raise LoweringError(
                    "the mana multiplier cannot count this restriction", node=node
                )
            payload["per_each"] = {
                "zone": "battlefield", "owner": "you", "filter": carried,
            }
        return (OracleInstruction("add_mana_from_text", "", payload),)
    # The any-colour branch keeps its clause text for a *text-keyed* handler
    # probe, so a restriction folded onto it would be carried in the payload and
    # ignored by the branch that reads the text. No card prints the pair; it
    # refuses rather than adding unrestricted mana.
    if node.spend_only is not None:
        raise LoweringError(
            "no handler restricts what any-colour mana may pay for", node=node
        )
    # ``any_color`` is a *count* now, not a flag. The handler used to probe the
    # clause text for the literal "one mana of any color", which is why every
    # other number had to refuse; it reads the number, so "add two mana of any
    # one color" and "add X mana" are the same instruction with different data.
    #
    # The clause text still rides along: ``activation.py`` keys the colour
    # injection on the ``any_color`` payload key, and the AI's mana valuation
    # reads the text. Both are the same string the legacy rule wrote.
    amount = _amount_payload(node.any_color)
    return (
        OracleInstruction(
            "add_mana_from_text", "",
            {
                "oracle_text": node.source_text,
                "any_color": True,
                "any_color_count": amount,
            },
        ),
    )


# Which player the mana goes to, from the clause's own subject. Both spellings
# name the same seat in this engine — a player can only tap lands they control,
# so the tapping player *is* the land's controller — but they are different
# referents on the card and the handler resolves each one by name rather than
# assuming they coincide.
_TAPPED_LAND_MANA_RECIPIENTS = {
    "that_player": "that_player",   # Mana Flare: "that player"
    "controller": "land_controller",  # Gauntlet of Might: "its controller"
}


def _lower_add_mana_for_tapped_land(
    node: ast.AddManaForTappedLand, event: str | None
) -> tuple[OracleInstruction, ...]:
    """Mana Flare / Gauntlet of Might's mana, as one parameterised instruction.

    ``add_mana_for_tapped_land`` is resolved inline by
    ``Game.tap_land_for_mana`` rather than through the stack, which is what
    CR 605.4a requires of a triggered mana ability.

    The event is checked rather than assumed. "That player" and "any type that
    land produced" are bound by the trigger, so under any other condition there
    is no land and no tapping player for the handler to read — it would add
    mana of an arbitrary type to an arbitrary seat. Refusing here keeps the
    clause unclaimed and visible instead.
    """
    if event != "land_tapped_for_mana":
        raise LoweringError(
            "'that land'/'that player' are bound by a land_tapped_for_mana "
            f"trigger; {event!r} binds neither",
            node=node,
        )
    recipient = _TAPPED_LAND_MANA_RECIPIENTS.get(node.recipient.kind)
    if recipient is None:
        raise LoweringError(
            f"no tapped-land mana recipient for {node.recipient.kind!r}", node=node
        )
    payload: dict[str, object] = {"recipient": recipient}
    if node.pips:
        payload["pips"] = node.pips
    if node.of_type_produced:
        payload["of_type_produced"] = node.of_type_produced
    if node.additional:
        payload["additional"] = True
    return (OracleInstruction("add_mana_for_tapped_land", "", payload),)
