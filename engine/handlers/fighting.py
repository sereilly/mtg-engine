"""The fight (CR 701.14), and the prepare-then-interact pair.

The handler twin of ``engine/grammar/lowering/fighting.py``, split from damage
along the line the CR draws: CR 120 is a source dealing damage to a recipient,
CR 701.14 is a **keyword action** — two creatures dealing damage to *each
other*, atomically (CR 701.14b: if either has left the battlefield or stopped
being a creature, neither deals any). ``_exchange_fight_damage`` is that
exchange, written once for the three ways a fight is announced: this creature
and a target (Brash Taunter), two targets, and a pump that sets up the fight
behind it (Primal Might).

A one-way exchange — one creature dealing damage equal to its power and
receiving none — is a bite, and ``bites.py``'s.

Split out of ``damage.py`` at the 2,000-line cap's split round.
"""

from __future__ import annotations

from ._amounts import resolve_amount
from ._common import apply_damage_to_creature, apply_temp_pt_boost
from ._filters import permanent_matches_filter
from ._targets import resolve_target_permanent, resolve_target_permanents
from .registry import effect_handler


@effect_handler("source_fights_target")
def source_fights_target(game, instruction, context):
    """"This creature fights another target creature." (CR 701.14 — Brash
    Taunter; Primal Might's second sentence prints the same exchange.)

    All four of the rule, because each of them is a way to get this wrong:

    - **701.14a** each deals damage equal to its power to the other, and both
      amounts are read *before* either is dealt — a fighter that dies to the
      first half still dealt its own damage.
    - **701.14b** if either is no longer on the battlefield or no longer a
      creature, **neither** fights. That is why this is one instruction and not
      two damage steps: written as two, the first would resolve and the second
      would not.
    - **701.14c** a creature that fights itself deals twice its power to
      itself, which falls out of dealing both halves to the same permanent.
    - **701.14d** the damage is not combat damage, so it goes through the
      ordinary creature-damage path.
    """
    card = context.card
    fighter = context.source_permanent
    filters = (instruction.payload.get("targets") or {}).get("filter") or {}

    def eligible(perm) -> bool:
        if not perm.is_creature:
            return False
        if instruction.payload.get("exclude_self") and perm is fighter:
            return False
        return permanent_matches_filter(perm, filters)

    opponent = resolve_target_permanent(game, context, predicate=eligible)
    # CR 701.14b, checked as one condition: either fighter missing means no
    # damage at all, from either side.
    if (
        fighter is None
        or opponent is None
        or not game.is_on_battlefield(fighter)
        or not fighter.is_creature
        or not opponent.is_creature
    ):
        game.log.append(f"{card.name}: the fight needs two creatures, so neither deals damage")
        return True, "resolved"

    _exchange_fight_damage(game, fighter, opponent)
    return True, "resolved"


def _exchange_fight_damage(game, fighter, opponent) -> None:
    """The CR 701.14a exchange itself, shared by every card that prints one.

    Both powers are read *before* either is dealt: a fighter killed by the
    first half has still dealt its own damage.
    """
    fighter_power = fighter.effective_power
    opponent_power = opponent.effective_power
    game.log.append(f"{fighter.card.name} fights {opponent.card.name}")
    apply_damage_to_creature(
        game, opponent, fighter_power, fighter,
        log_message=lambda dealt: (
            f"{fighter.card.name} deals {dealt} damage to {opponent.card.name}"
        ),
        asks=True,
    )
    apply_damage_to_creature(
        game, fighter, opponent_power, opponent,
        log_message=lambda dealt: (
            f"{opponent.card.name} deals {dealt} damage to {fighter.card.name}"
        ),
        asks=True,
    )


@effect_handler("prepare_then_interact")
def prepare_then_interact(game, instruction, context):
    """"Target creature you control gets +X/+X until end of turn. Then it
    fights up to one target creature you don't control." (Primal Might; Hunter's
    Edge prints the one-way half.)

    Two chosen targets resolved positionally, the prepared one first. The
    preparation happens whether or not the second slot answered — "up to one"
    may legally name none (CR 601.2c), and the pump is not conditional on the
    fight. The fight itself is CR 701.14b's all-or-nothing exchange, which is
    why the two sentences are one instruction.
    """
    card = context.card
    targets = instruction.payload.get("targets") or {}
    slot_filters = targets.get("filters") or [targets.get("filter") or {}] * 2
    caster_index = game.players.index(context.caster)

    def slot_predicate(index: int):
        wanted = slot_filters[index] if index < len(slot_filters) else {}

        def eligible(perm) -> bool:
            if not perm.is_creature or not permanent_matches_filter(perm, wanted):
                return False
            controller = wanted.get("controller")
            if controller == "you":
                return game.controls(caster_index, perm)
            if controller == "not_you":
                return not game.controls(caster_index, perm)
            return True

        return eligible

    chosen = resolve_target_permanents(game, context, predicate=lambda perm: True)
    first = chosen[0] if len(chosen) > 0 and slot_predicate(0)(chosen[0]) else None
    second = chosen[1] if len(chosen) > 1 and slot_predicate(1)(chosen[1]) else None

    if first is None:
        game.log.append(f"{card.name}: no legal creature to affect")
        return True, "resolved"

    prepare = instruction.payload.get("prepare") or {}
    if prepare.get("kind") == "pump":
        power = resolve_amount(prepare.get("power", 0), context.x_value)
        toughness = resolve_amount(prepare.get("toughness", 0), context.x_value)
        apply_temp_pt_boost(first, power, toughness)
        game.log.append(
            f"{card.name} gives {first.card.name} +{power}/+{toughness} until end of turn"
        )
    elif prepare.get("kind") == "counter":
        game.place_plus1_counters(first)
        game.log.append(f"{first.card.name} gets a +1/+1 counter ({card.name})")

    if second is None:
        # "Up to one" may legally name none, and a slot that stopped answering
        # is dropped (CR 608.2b) — the preparation above still happened.
        game.log.append(f"{card.name}: no second creature, so no damage is exchanged")
        return True, "resolved"

    if instruction.payload.get("mode") == "fight":
        _exchange_fight_damage(game, first, second)
    else:
        apply_damage_to_creature(
            game, second, first.effective_power, first,
            log_message=lambda dealt: (
                f"{first.card.name} deals {dealt} damage to {second.card.name}"
            ),
            asks=True,
        )
    return True, "resolved"


@effect_handler("target_fights_target")
def target_fights_target(game, instruction, context):
    """"Target creature you control fights target creature an opponent
    controls." (Triangle of War.)

    CR 701.14's exchange between two creatures the ability announced
    *independently* (CR 601.2c), neither of them its own source — which is the
    whole difference from ``source_fights_target`` beside it, where one fighter
    is read off the context and only the other is picked.

    Both slots are re-checked here rather than trusted from the picker, the
    rule every narrowed damage handler follows: a target that stopped
    matching between announcement and resolution is not one this ability may
    use (CR 608.2b), and the narrowings are what keep the artifact from
    fighting two of its own controller's creatures against each other. They go
    through ``subject_matches`` — the one matcher — because the seat words
    "you control" and "an opponent controls" are exactly what the pure
    ``permanent_matches_filter`` cannot answer.

    CR 701.14b's all-or-nothing is checked across both fighters together, as it
    is for the source-shaped kind: either slot missing means neither deals any
    damage, and ``_exchange_fight_damage`` is the shared body that reads both
    powers before dealing either (CR 701.14a).
    """
    from ..subject_filters import subject_matches

    card = context.card
    targets = instruction.payload.get("targets") or {}
    slot_filters = targets.get("filters") or [targets.get("filter") or {}] * 2
    observer = game.players.index(context.caster)
    ids = context.target_permanent_id
    if not isinstance(ids, list):
        ids = [ids, None]
    resolved = [
        game.permanent_by_id(pid) if isinstance(pid, int) else None for pid in ids
    ]

    def slot(index: int):
        perm = resolved[index] if index < len(resolved) else None
        if perm is None or not perm.is_creature:
            return None
        wanted = slot_filters[index] if index < len(slot_filters) else {}
        if not subject_matches(
            game, perm, wanted,
            observer=observer, source=context.source_permanent,
        ):
            return None
        return perm

    first, second = slot(0), slot(1)
    # CR 701.14b as one condition, for ``source_fights_target``'s reason: a
    # fighter that has left the battlefield or stopped being a creature stops
    # *both* halves, so this cannot be two independent damage steps.
    if first is None or second is None or first is second:
        game.log.append(
            f"{card.name}: the fight needs two legal creatures, so neither "
            "deals damage"
        )
        return True, "resolved"
    _exchange_fight_damage(game, first, second)
    return True, "resolved"
