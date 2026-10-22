"""Base power/toughness rewrites (CR 613.4b) created by resolving abilities.

The Legends template — "change …'s base [power and] toughness to <value>" —
in the three shapes that resolve through ``EFFECT_HANDLERS``: a chosen
creature's characteristics read onto the source (Sentinel's toughness from a
power, Sworn Defender's *both* stats from the other one's, crossed), a
graveyard count read into it (Wall of Tombstones), and a sweep over the
creatures the damage record says hurt the source this turn (Brine Hag). The
fourth printing,
Halfdane, is a targeted upkeep trigger and resolves through the registry in
``engine/phases/upkeep_effects.py``; its scheduled revert is the
``BASE_PT_REVERT_KEY`` stamp ``engine/pt.py`` documents.

All of these are layer-7b writes through :func:`engine.pt.set_base_pt`, and
7c modifications (counters, pumps) keep applying on top of the new base. Most
have no expiry — "(This effect lasts indefinitely.)" is reminder text for
CR 611.2a's "permanently" — and the one that does prints the words (Sworn
Defender's "until end of turn"), which is why the duration is payload rather
than a property of the family.

Its own module rather than more of ``pump.py``, which sat at the thousand-line
boundary the grammar's size guard named as the stop-absorbing signal. The two
until-end-of-turn setters stayed there — a target's base power and toughness
(Sorceress Queen, Singing Tree) and every creature its controller controls
(Jolrael) — on the argument that they shared a duration with the pumps more
than a template with these. They came here at the 2,000-line cap's split
round: what they write is the same layer-7b base that is this module's
subject, and their duration is payload like Sworn Defender's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..oracle_types import BASE_PT_SET_PERMANENTS, OracleInstruction
from ..pt import set_base_pt
from ._amounts import count_from_payload, resolve_amount
from ._targets import resolve_target_permanent
from .registry import effect_handler

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..models import Permanent


#: How a stat's ``{"characteristic", "offset"}`` payload is read off the chosen
#: creature. Named here because the parse admits exactly these two words and the
#: refusal for a third is written in the grammar — a table with one entry per
#: word is what keeps the two ends agreeing about which they are.
_CHARACTERISTIC_READERS = {
    "power": lambda perm: perm.effective_power,
    "toughness": lambda perm: perm.effective_toughness,
}


@effect_handler("set_source_base_pt_from_target")
def set_source_base_pt_from_target(
    game: "Game", instruction: OracleInstruction, context: "OracleExecutionContext"
) -> tuple[bool, str]:
    """Sentinel: "{0}: Change this creature's base toughness to 1 plus the
    power of target creature blocking or blocked by this creature."
    Sworn Defender: "{1}: This creature's power becomes the toughness of target
    creature blocking or being blocked by this creature minus 1 until end of
    turn, and its toughness becomes 1 plus the power of that creature until end
    of turn."

    One handler, because they are one effect with the payload changed: which
    stats are set, which characteristic each reads, what constant it carries and
    whether the write expires. Sworn Defender is the card that showed the
    single-stat, single-characteristic, no-duration version was three
    assumptions rather than one shape.

    **Both stats are read before either is written.** They are read off the same
    creature and the source is not that creature on any board this pool can
    make — but a card that pointed the ability at itself would otherwise have
    its second read see the first write, which is not what a single resolution
    does (CR 608.2: the effect's values are determined as it resolves).

    The in-combat relation is checked here as well as at activation
    (``legality_abilities.activation_target_refusal`` asks the same question through
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
    written: dict[str, int] = {}
    for stat in ("power", "toughness"):
        read = instruction.payload.get(stat)
        if not read:
            continue
        reader = _CHARACTERISTIC_READERS.get(str(read.get("characteristic")))
        if reader is None:
            return False, f"no reader for {read.get('characteristic')!r}"
        written[stat] = reader(target) + int(read.get("offset", 0))
    if not written:
        return False, "this rewrite sets no characteristic"
    set_base_pt(
        source,
        written.get("power"),
        written.get("toughness"),
        until_eot=bool(instruction.payload.get("until_eot")),
    )
    game.log.append(
        f"{context.card.name}: base "
        + " and ".join(f"{stat} becomes {value}" for stat, value in written.items())
        + f" (read off {target.card.name})"
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


@effect_handler("set_base_pt_target_until_eot")
def set_base_pt_target_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Sorceress Queen ("has base power and toughness 0/2") / Singing Tree
    ("has base power 0", toughness untouched). ``payload["toughness"]`` is
    None when the ability only sets power."""
    card = context.card
    source_permanent = context.source_permanent
    exclude_self = bool(instruction.payload.get("exclude_self"))
    attacking_only = bool(instruction.payload.get("attacking_only"))
    flying_only = bool(instruction.payload.get("flying_only"))

    from ..subject_filters import subject_matches

    # The narrowings the picker applied, re-asked at resolution through the
    # one reader of a printed noun phrase: CR 608.2b asks a target's legality
    # again, and a restriction enforced only by the picker is one a
    # non-interactive seat walks straight past.
    described = {
        key: value
        for key, value in instruction.payload.items()
        if key in ("controller", "cast_by_you_this_turn")
    }
    observer = (
        game.players.index(context.caster)
        if context.caster in game.players else None
    )

    def _eligible(perm: Permanent) -> bool:
        if not perm.is_creature:
            return False
        if exclude_self and source_permanent is not None and perm is source_permanent:
            return False
        if attacking_only and not perm.attacking:
            return False
        if flying_only and not game._has_keyword(perm, "flying"):
            return False
        if described and not subject_matches(
            game, perm, described, observer=observer, source=source_permanent,
        ):
            return False
        return True

    target_perm = resolve_target_permanent(game, context, predicate=_eligible)
    if target_perm is None:
        game.log.append(f"{card.name}: no valid creature target")
        return True, "resolved"

    power = instruction.payload.get("power")
    toughness = instruction.payload.get("toughness")
    # "…**until your next upkeep**" (Cycle of Life). A different moment, not a
    # different layer, so it rides the persistent 7b channel with the stamp the
    # upkeep step's sweep reads — and the seat is CR 109.5's controller of the
    # ability, never the affected permanent's, which is the rule every other
    # `your_next_upkeep` sweep already follows.
    # What the rewrite chose, for the sentence behind it — a delayed ability a
    # turn later, which names "that creature" and picks nothing itself. Written
    # for every duration, because which one the card printed is not something
    # the later sentence can see.
    context.results[BASE_PT_SET_PERMANENTS] = [target_perm.permanent_id]
    duration = instruction.payload.get("duration")
    if duration == "your_next_upkeep":
        caster = context.caster
        seat = game.players.index(caster) if caster in game.players else 0
        set_base_pt(
            target_perm, power, toughness,
            reverts_at_next_upkeep_of=seat, turn=game.turn,
        )
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base power and toughness "
            f"{power}/{toughness} until {caster.name}'s next upkeep"
        )
        return True, "resolved"
    set_base_pt(target_perm, power, toughness, until_eot=True)
    # The log names the half the card printed. "…has base **toughness** 1"
    # (Chariot of the Sun) leaves the power standing, which ``set_base_pt``'s
    # None already expresses — reading the pair unconditionally printed a
    # "None/1" nobody could have cast.
    if toughness is None:
        game.log.append(f"{card.name}: {target_perm.card.name} has base power {power} until end of turn")
    elif power is None:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base toughness {toughness} until end of turn"
        )
    else:
        game.log.append(
            f"{card.name}: {target_perm.card.name} has base power and toughness {power}/{toughness} until end of turn"
        )
    return True, "resolved"


@effect_handler("set_team_base_pt_until_eot")
def set_team_base_pt_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"Until end of turn, creatures you control have base power and toughness
    X/X, where X is the number of cards in your hand." (Jolrael, Mwonvuli
    Recluse.)

    CR 613 layer 7b applied to a *set* rather than to a chosen permanent, which
    is why it is its own kind: the targeted handler beside it asks a picker which
    permanent, and this one asks the board which permanents.

    **X is fixed once, as the ability resolves.** CR 608.2's value is calculated
    on resolution and does not track the hand afterwards — drawing a card later
    in the turn does not grow the team, and a continuous recompute would say it
    does. That is the whole reason the amount is resolved here and stamped,
    rather than carried as a spec for the layer refresh to re-evaluate.

    The set is snapshotted for the same reason: a creature entering after this
    resolves was never affected (CR 611.2c).
    """
    x_value = context.x_value
    x_count = instruction.payload.get("x_from_count")
    if x_count is not None:
        x_value = count_from_payload(game, context, x_count)
    power = resolve_amount(instruction.payload.get("power", 0), x_value)
    toughness = resolve_amount(instruction.payload.get("toughness", 0), x_value)
    seat = game.players.index(context.caster)
    affected = [perm for perm in game.controlled_by(seat) if perm.is_creature]
    for perm in affected:
        set_base_pt(perm, power, toughness, until_eot=True)
    game.log.append(
        f"{context.card.name}: {len(affected)} creature(s) have base power and "
        f"toughness {power}/{toughness} until end of turn"
    )
    return True, "resolved"
