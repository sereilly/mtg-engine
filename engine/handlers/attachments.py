"""Attaching one permanent to another (CR 701.3) — the equip keyword's effect.

One handler for the instruction the grammar lowers "Attach this permanent to
target creature you control" to, which is the text CR 702.6a gives every equip
ability. Everything about *whether* the attachment is legal and *what* attaching
does lives in ``engine/equipment.py``; this module is the seam between a
resolving stack item and those two functions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..equipment import attach_equipment, equip_refusal
from ..oracle_types import OracleInstruction
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext


@effect_handler("attach_source_to_target")
def attach_source_to_target(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Attach this permanent to target creature you control." (CR 702.6a.)

    The target is re-checked as the ability resolves (CR 608.2b): it must still
    be on the battlefield, still match the printed filter ("creature you
    control", or CR 702.6c's narrower "legendary creature you control"), and
    still be something the Equipment may legally equip (CR 301.5, 702.16d).
    A target that fails any of these is illegal and the ability does nothing —
    there is **no fallback** to another creature, because an attach that landed
    on a creature the player never chose is the silent wrongness every
    targeted effect here refuses.

    "You" is the ability's controller (CR 109.5), read off ``context.caster``
    rather than ``context.target``: the activation path defaults the latter to
    an opponent for an ability that names no seat, and an equip names none.

    The source must still be on the battlefield too. CR 702.6a's ability is of
    the Equipment; if the Equipment was destroyed in response the ability still
    resolves (CR 113.7a) but there is nothing to move, and the effect does
    nothing rather than attaching a card in a graveyard.
    """
    if instruction.payload.get("subject_from") == "target":
        return _attach_chosen_to_chosen(game, instruction, context)

    # Function-level, as every handler that asks it does: subject_filters
    # imports handlers._common, so the package cannot import it at the top.
    from ..subject_filters import subject_matches

    equipment = context.source_permanent
    if equipment is None or not game.is_on_battlefield(equipment):
        game.log.append(f"{context.card.name}: nothing to attach — it has left the battlefield")
        return True, "resolved"
    caster = context.caster
    caster_index = game.players.index(caster)
    described = {
        key: value for key, value in instruction.payload.items() if key != "targets"
    }

    def legal(candidate) -> bool:
        return (
            subject_matches(game, candidate, described, observer=caster_index, source=equipment)
            and equip_refusal(game, equipment, candidate) is None
        )

    target_id = context.target_permanent_id
    if isinstance(target_id, list):
        target_id = target_id[0] if target_id else None
    target_index = context.target_permanent_index
    if isinstance(target_index, list):
        target_index = target_index[0] if target_index else None
    # Strictly the chosen permanent. The id is the identity (CR 400.7) and the
    # activation path stamps one whenever an index was named, so when there is
    # an id it is the *only* thing consulted: falling back to the index after
    # the id failed to resolve is how a dead target's slot — renumbered onto
    # the next creature down — would get the Equipment instead. The bare index
    # is for callers that recorded no id at all, and it is tested against the
    # activator's own battlefield because that is whose creature was named.
    chosen = None
    if isinstance(target_id, int):
        candidate = game.permanent_by_id(target_id)
        if candidate is not None and legal(candidate):
            chosen = candidate
    elif isinstance(target_index, int):
        candidate = game.permanent_at(caster, target_index)
        if candidate is not None and legal(candidate):
            chosen = candidate
    if chosen is None:
        game.log.append(
            f"{equipment.card.name}'s equip ability did nothing: its target is no longer legal"
        )
        return True, "resolved"
    attach_equipment(game, equipment, chosen)
    return True, "resolved"


def _attach_chosen_to_chosen(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Attach **target Aura** attached to a creature or land to another
    permanent of that type." (Enchantment Alteration.)

    The same keyword action as the equip above (CR 701.3) with both ends chosen
    rather than one: the thing that moves is the spell's target, and the thing
    it moves onto is the permanent recorded by the ``choose_permanent`` step in
    front of this one — by id, so a permanent that left and a look-alike that
    slid into its slot are told apart (CR 400.7).

    CR 303.4j is the whole of the failure mode and is re-asked here rather than
    trusted from the choice: an Aura that can't legally enchant the chosen
    permanent **doesn't move**. It stays where it is, which is not the same as
    falling off — dropping it would put it in a graveyard on the next
    state-based check for a card that never said to destroy it.
    """
    from ..auras import attach_aura, aura_attach_refusal, detach_aura

    card_name = getattr(context.card, "name", "")
    target_id = context.target_permanent_id
    if isinstance(target_id, list):
        target_id = target_id[0] if target_id else None
    aura = game.permanent_by_id(target_id) if isinstance(target_id, int) else None
    if aura is None or not game.is_on_battlefield(aura):
        game.log.append(f"{card_name}: its target is no longer on the battlefield")
        return True, "resolved"
    host_id = context.results.get(instruction.payload.get("host_from"))
    host = game.permanent_by_id(host_id) if isinstance(host_id, int) else None
    refusal = aura_attach_refusal(game, aura, host) if host is not None else "nothing was chosen"
    if refusal is not None:
        game.log.append(f"{card_name}: {aura.card.name} does not move — {refusal}")
        return True, "resolved"
    previous = aura.metadata.get("attached_to")
    if previous is host:
        game.log.append(f"{card_name}: {aura.card.name} is already attached to {host.card.name}")
        return True, "resolved"
    if previous is not None:
        detach_aura(aura, previous)
    attach_aura(aura, host)
    game.log.append(f"{card_name}: {aura.card.name} now enchants {host.card.name}")
    game.check_state_based_actions()
    return True, "resolved"

