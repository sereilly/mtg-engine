"""Base power/toughness rewrites (CR 613.4b) created by resolving abilities.

The Legends template — "change …'s base [power and] toughness to <value>" —
in the three shapes that resolve through ``EFFECT_HANDLERS``: a chosen
creature's power read into the source's toughness (Sentinel), a graveyard
count read into it (Wall of Tombstones), and a sweep over the creatures the
damage record says hurt the source this turn (Brine Hag). The fourth printing,
Halfdane, is a targeted upkeep trigger and resolves through the registry in
``engine/phases/upkeep_effects.py``; its scheduled revert is the
``BASE_PT_REVERT_KEY`` stamp ``engine/pt.py`` documents.

All of these are layer-7b *writes* with no expiry — "(This effect lasts
indefinitely.)" is reminder text for CR 611.2a's "permanently" — so every one
goes through :func:`engine.pt.set_base_pt` with no ``until_eot``, and 7c
modifications (counters, pumps) keep applying on top of the new base.

Its own module rather than more of ``pump.py``: that file sits at the
thousand-line boundary the grammar's size guard names as the stop-absorbing
signal, and these handlers share a subject (the rewrite template) rather than
a duration with the until-end-of-turn setters there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import OracleInstruction
from ..pt import set_base_pt
from ._common import count_from_payload, resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent


@effect_handler("set_source_base_toughness_from_target_power")
def set_source_base_toughness_from_target_power(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """Sentinel: "{0}: Change this creature's base toughness to 1 plus the
    power of target creature blocking or blocked by this creature."

    The in-combat relation is checked here as well as at activation
    (``legality.activation_target_refusal`` asks the same question through
    ``_ability_target_legal``), because CR 608.2b re-checks a target's
    legality on resolution — a creature that left combat in response makes
    the ability do nothing rather than read a bystander's power.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    in_combat_only = bool(instruction.payload.get("in_combat_with_source"))

    def _eligible(perm: "Permanent") -> bool:
        if not perm.is_creature:
            return False
        if in_combat_only and not any(
            perm is opponent for opponent in game.creatures_in_combat_with(source)
        ):
            return False
        return True

    target = resolve_target_permanent(
        game, context, predicate=_eligible, fallback_on_invalid_choice=False
    )
    if target is None:
        game.log.append(f"{context.card.name}: no valid creature target")
        return True, "resolved"
    bonus = int(instruction.payload.get("bonus", 0))
    toughness = bonus + target.effective_power
    set_base_pt(source, None, toughness)
    game.log.append(
        f"{context.card.name}: base toughness becomes {toughness} "
        f"({bonus} plus {target.card.name}'s power)"
    )
    return True, "resolved"


@effect_handler("set_source_base_toughness_from_count")
def set_source_base_toughness_from_count(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """Wall of Tombstones: "…change this creature's base toughness to 1 plus
    the number of creature cards in your graveyard."

    The count is taken once, as the trigger resolves (CR 608.2) — the rewrite
    then holds still however the graveyard moves, until the next upkeep's
    trigger takes a fresh count. That is what separates this from a
    characteristic-defining ability, and why it is a handler rather than a
    ``dynamic_pt_count`` registration.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    bonus = int(instruction.payload.get("bonus", 0))
    count = count_from_payload(game, context, instruction.payload.get("count") or {})
    toughness = bonus + count
    set_base_pt(source, None, toughness)
    game.log.append(
        f"{context.card.name}: base toughness becomes {toughness} "
        f"({bonus} plus {count})"
    )
    return True, "resolved"


@effect_handler("set_base_pt_of_creatures_that_damaged_source")
def set_base_pt_of_creatures_that_damaged_source(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """Brine Hag: "When this creature dies, change the base power and
    toughness of all creatures that dealt damage to it this turn to 0/2."

    Reads the ``damaged_by_sources_this_turn`` record the damage seam keeps on
    the victim — the source permanent here, dead by the time this resolves,
    which is why the record rides its metadata (CR 603.10 last-known
    information) rather than being recounted from a battlefield it has left.
    Each damager is affected only if it is still on the battlefield (by
    identity — a look-alike is a different permanent, CR 400.7) and still a
    creature.
    """
    source = context.source_permanent
    if source is None:
        return False, "ability not implemented"
    power = int(instruction.payload.get("power", 0))
    toughness = int(instruction.payload.get("toughness", 0))
    damagers = source.metadata.get("damaged_by_sources_this_turn") or []
    rewritten = 0
    for perm in damagers:
        if not game.is_on_battlefield(perm) or not perm.is_creature:
            continue
        set_base_pt(perm, power, toughness)
        rewritten += 1
        game.log.append(
            f"{context.card.name}: {perm.card.name}'s base power and toughness "
            f"become {power}/{toughness}"
        )
    if rewritten == 0:
        game.log.append(f"{context.card.name}: nothing dealt damage to it this turn")
    return True, "resolved"
