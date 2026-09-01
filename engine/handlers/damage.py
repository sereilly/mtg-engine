from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage_events import (DAMAGE_DENIES_REGENERATION,
                             DAMAGE_EXILES_INSTEAD)
from ..damage_redirects import DamageRedirect, add_redirect
from ..divided_damage import (
    DIVIDED_TARGETS, EVENLY, divide, divided_entry,
)
from ..dexterity import flip_lands_on
from ..models import Permanent
from ..named_counters import counters_on
from ..resumption import run_resumable
from ._common import (
    apply_damage_to_creature, apply_temp_pt_boost, attached_host, evaluate_count,
    flip_coin,
    frozen_that_player_seat, permanent_matches_filter, resolve_amount,
    resolve_target_permanent, resolve_target_permanents,
)
from ..oracle_types import X_FROM_COUNT_PER_RECIPIENT
from .registry import effect_handler
from ..mana_payment import generic_cost

if TYPE_CHECKING:
    from ..game import Game
    from ..game_types import OracleExecutionContext
    from ..oracle import OracleInstruction


def _record_damage_recipient(context, permanent, player=None) -> None:
    """Note who is about to be damaged, and how much they could absorb.

    Read **before** the damage, because that is what the card that asks says:
    "…but not more life than the player's life total **before the damage was
    dealt**, the planeswalker's loyalty before the damage was dealt, or the
    creature's toughness" (Drain Life, Soul Burn). A player's life and a
    planeswalker's loyalty are exactly what the damage is about to change, so
    reading them afterwards answers a different question; a creature's
    toughness carries no such qualifier and is read at the same moment for want
    of a difference — nothing in this pool changes a toughness as part of
    damaging the creature.

    ``kind`` travels with the number because the three printed terms are about
    three different kinds of recipient, and a card may print only some of them
    (``lowering/game._life_gain_cap_payload``).
    """
    if permanent is not None and permanent.is_creature:
        kind, capacity = "creature", permanent.effective_toughness
    elif permanent is not None and permanent.has_type("planeswalker"):
        kind = "planeswalker"
        capacity = int(permanent.metadata.get("loyalty_counters", 0) or 0)
    elif player is not None:
        kind, capacity = "player", int(player.life)
    else:
        return
    context.results["damage_recipient"] = {
        "kind": kind, "capacity": max(0, int(capacity)),
    }


def _damage_reporter(game: Game, card, permanent):
    """What a divided-damage site does once one creature's share is dealt: log
    it and fire "dealt damage" triggers.

    Handed to `_mark_damage_on_permanent` as its `then` rather than run after
    it, because a damage event can stop to ask the affected player which effect
    applies first — and while it waits, nothing has been dealt to report."""

    def report(dealt: int) -> None:
        game.log.append(f"{card.name} dealt {dealt} damage to {permanent.card.name}")
        # See apply_damage_to_creature: the trigger is not gated on survival.
        if dealt > 0:
            game._fire_dealt_damage_triggers(permanent, dealt)

    return report


@effect_handler("deal_damage")
def deal_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    source_permanent = context.source_permanent
    x_value = context.x_value

    # Rocket Launcher: "Destroy this artifact at the beginning of the next end
    # step." A consequence of having activated, so it is marked here rather
    # than sequenced — the end step's existing delayed-destruction sweep does
    # the rest (phases/end_step.py:_delayed_eot_removal).
    if instruction.payload.get("destroys_source_at_end_step") and source_permanent is not None:
        source_permanent.metadata["destroy_at_next_end_step"] = True

    # "…it deals **that much** damage" (Brash Taunter): the number is the firing
    # event's, frozen into the trigger's context by the fire site. An absent
    # record deals nothing rather than falling back to an amount the card never
    # printed — the same rule target_loses_life follows.
    # "…deals damage equal to **that Wall's mana value**" (Word of Blasting).
    # The number an earlier step of this same resolution recorded — the destroy
    # reads it off the permanent before destroying it (CR 608.2h), because by
    # now the Wall is a card in a graveyard. The scratchpad channel every other
    # "equal to <back-reference>" already uses, and the same rule the trigger
    # channel below follows: an absent record deals nothing rather than an
    # amount the card never printed.
    from_results = instruction.payload.get("amount_from")
    from_trigger = instruction.payload.get("amount_from_trigger")
    if from_results is not None:
        damage = max(0, int((context.results or {}).get(from_results, 0) or 0))
    elif from_trigger is not None:
        damage = max(0, int((context.trigger_context or {}).get(from_trigger, 0)))
    elif (named_counter := instruction.payload.get("amount_from_named_counters")) is not None:
        # "…deals damage equal to the number of doom counters on it…"
        # (Armageddon Clock). Counted at resolution off the permanent, so a
        # counter added or removed while the trigger was on the stack counts —
        # and read through engine/named_counters.py rather than off a metadata
        # key spelled out here, which is the one store CR 122.1 counters live in.
        damage = counters_on(source_permanent, str(named_counter)) if source_permanent else 0
    elif instruction.payload.get("amount_from_source_power"):
        # "…deals damage equal to **its power**" (Leafkin Avenger). Read at
        # resolution off the permanent, so a pump between activation and
        # resolution counts — and read off the `Permanent`, not the card, so it
        # is the computed power (CR 613) rather than the printed one.
        damage = max(0, source_permanent.effective_power) if source_permanent else 0
    else:
        damage = resolve_amount(instruction.payload.get("amount", 0), x_value)
    # "…deals **X plus 3** damage to you" (Hellfire). The printed constant, kept
    # off the amount so the where-clause in front of it still says what X is.
    # Added after every branch above rather than inside one, because the sum is
    # a property of the printed quantity and not of where its left half came
    # from.
    damage = max(0, damage + int(instruction.payload.get("amount_bonus", 0) or 0))
    # "…deals **half X damage, rounded down**, to any target, and half X damage,
    # **rounded up**, to you." (Banshee; Eternal Flame prints the second half.)
    # Applied here — after every branch above and after the printed addend —
    # because the halving is the last arithmetic the sentence does, and the two
    # roundings in one sentence are the whole point of the card: an announced
    # X of 5 is 2 to the target and 3 to its controller.
    #
    # A count that halves does *not* arrive here. It carries `half` on its own
    # spec and is halved inside the count evaluator, where the number is
    # computed; halving twice is what a second reader of the same rider buys.
    halving = instruction.payload.get("amount_half")
    if halving:
        damage = -(-damage // 2) if halving == "up" else damage // 2

    # "If Lava Burst would deal damage to a creature, that damage can't be
    # prevented or dealt instead to another permanent or player." A property of
    # *this* damage event, so it rides the event rather than being stamped on
    # the creature the way the two riders further down are: Whippoorwill's
    # marker lasts the turn and would lock the next source's damage too.
    # Emitted by the lowering only for a single-recipient clause, which is the
    # single-target branch below and the object branch beside it.
    unpreventable = bool(instruction.payload.get("unpreventable_to_creature"))

    # "…deals damage to each opponent equal to the number of Islands **that
    # player** controls" (Typhoon). One number per seat, so it cannot have been
    # folded into `context.x_value` — there is one of those and this phrase has
    # one answer per recipient. The loops below ask this instead of reading
    # `damage`; every other branch never sees the key, and the lowering refuses
    # to emit it anywhere but at a looping recipient.
    per_recipient_spec = instruction.payload.get(X_FROM_COUNT_PER_RECIPIENT)

    def _amount_for(face) -> int:
        if per_recipient_spec is None:
            return damage
        # "…equal to 3 minus the number of cards **they** discarded this way"
        # (Mind Bomb). A per-seat number too, but one an earlier step of this
        # same resolution recorded rather than one the board can be asked for —
        # so it is read out of the scratchpad here instead of going to
        # `evaluate_count`, which counts objects. A seat the record never
        # mentions discarded nothing, which is the printed base.
        record = per_recipient_spec.get("resolution_record")
        if record is not None:
            recorded = context.results.get(record) or {}
            seat = game.players.index(face)
            return max(
                0,
                int(per_recipient_spec.get("base", 0))
                - int(recorded.get(seat, 0)),
            )
        return max(0, evaluate_count(
            game, face, per_recipient_spec,
            exclude=source_permanent, source=source_permanent,
        ))

    def _record_and_log(dealt: int, face) -> None:
        """What a multi-seat damage loop does with each seat's result.

        The *sum* is recorded, because a sweep's back-reference is about the
        whole effect: "You gain life equal to the damage dealt this way"
        (Syphon Soul) means every point of it, and in a free-for-all that is
        three events rather than one. Recorded at all because the category
        table names `deal_damage` a producer of `damage_dealt` — the loops
        never wrote the key, so the second half of that sentence read a zero
        and Syphon Soul would have gained no life while reporting itself
        resolved.

        Nothing is logged for zero: CR 120.8 makes a source that would deal 0
        damage deal none at all, so a line about it is a line about an event
        that did not happen.
        """
        context.results["damage_dealt"] = (
            int(context.results.get("damage_dealt", 0) or 0) + max(0, int(dealt))
        )
        if dealt:
            game.log.append(f"{card.name} dealt {dealt} damage to {face.name}")

    target_perm_idx = context.target_permanent_index
    # "…deals 6 damage to each of **up to two** target creatures and/or
    # planeswalkers." (Volcanic Salvo.) The several-targets description says a
    # list was collected. Resolved strictly — a departed target is dropped
    # (CR 608.2b) rather than replaced by whatever a scan reaches first, which
    # for "up to two" would be a creature the player never chose — and each
    # surviving one takes the full amount, because the card divides nothing.
    several = instruction.payload.get("targets") or {}
    if (
        isinstance(several, dict)
        and isinstance(several.get("count"), int)
        and several["count"] > 1
    ):
        filters = several.get("filter") or {}
        chosen = resolve_target_permanents(
            game, context,
            predicate=lambda perm: permanent_matches_filter(perm, filters),
        )
        if not chosen:
            game.log.append(f"{card.name}: nothing to deal damage to")
            return True, "resolved"
        for perm in chosen:
            apply_damage_to_creature(game, perm, damage, card)
        return True, "resolved"
    # "…to target creature or planeswalker **that player** controls."
    # (Chandra's Incinerator.) "That player" is a referent the *event* picked —
    # the opponent who was dealt the damage — so it is resolved here, where the
    # trigger's context is, and `subject_matches` refuses it rather than
    # reducing it to "any opponent". Two-player games make the two readings
    # agree; three do not.
    described = (instruction.payload.get("targets") or {}).get("filter") or {}
    if described.get("controller") == "that_player":
        # One key for "who took the damage", not two: the noncombat
        # announcement used to call it `damaged_seat` and the combat one
        # `defending_player_index`, which is a second name for one thing and the
        # reason a handler could only be written against one of them. There is
        # one announcement now and one key — read through the one reader of the
        # printed phrase, so a *fourth* handler cannot be written against a key
        # this one does not know about.
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(f"{card.name}: no player for 'that player' to name")
            return True, "resolved"
        narrowed = {k: v for k, v in described.items() if k != "controller"}
        perm = resolve_target_permanent(
            game, context,
            player=game.players[seat],
            predicate=lambda p: permanent_matches_filter(p, narrowed),
            fallback_on_invalid_choice=False,
        )
        if perm is None:
            game.log.append(f"{card.name}: nothing of theirs to damage")
            return True, "resolved"
        apply_damage_to_creature(game, perm, damage, card)
        return True, "resolved"
    # "…and N damage to you": a second damage instruction in the same sequence
    # aimed at the source's controller rather than the spell's target. Reads the
    # same "recipient" key target_gains_life has always used. Without it, "deal
    # damage and also damage yourself" would need its own fused instruction kind
    # (which is exactly what deal_damage_and_self_damage was).
    if instruction.payload.get("recipient") == "source":
        # "…and 3 damage to itself" (Psionic Entity). The ability's own source,
        # named by the clause rather than inferred from the absence of a target
        # index — the second half of a two-clause damage sentence resolves with
        # the first half's target still in the context, so an inference would
        # deal this damage to whatever the player pointed at.
        #
        # A source that has already left the battlefield takes nothing (CR
        # 608.2b's spirit: the object the effect names is gone), and says so
        # rather than falling through to a face.
        if source_permanent is None or not game.is_on_battlefield(source_permanent):
            game.log.append(f"{card.name}: its source is gone, no damage to itself")
            return True, "resolved"
        game._mark_damage_on_permanent(
            source_permanent, damage, source=source_permanent, asks=True,
            then=_damage_reporter(game, card, source_permanent),
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "caster":
        def _report(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            game.log.append(f"{card.name} dealt {dealt} damage to {caster.name}")

        game._deal_damage_to_player(
            caster, damage, source=source_permanent or card, then=_report, asks=True
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "event_subject_player":
        # "…deals 1 damage to **that player**" where the trigger's subject *is*
        # a seat (Underworld Dreams, under "whenever an opponent draws a
        # card"). The seat the fire site froze (CR 603.10) — the trigger has no
        # target, so `context.target` is whatever a targetless resolution
        # defaults to, which in a three-player game is not the seat that drew.
        # No record means the words named nobody and no damage is dealt, the
        # same rule the controller branch below follows.
        seat = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded player, no damage dealt")
            return True, "resolved"
        drawer = game.players[seat]

        def _report_player(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {drawer.name}")

        game._deal_damage_to_player(
            drawer, damage, source=source_permanent or card,
            then=_report_player, asks=True,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "event_subject_controller":
        # "…deals that much damage to **that creature's controller**"
        # (Backfire). The controller of the object the trigger's event was
        # about, frozen by the fire site (CR 603.10) — a board read cannot
        # answer it, because the creature may have left and Control Magic makes
        # controller and owner differ. No record means the words named nobody,
        # and the damage does not happen rather than landing on a guess.
        seat = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded controller, no damage dealt")
            return True, "resolved"
        victim = game.players[seat]

        def _report_subject(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {victim.name}")

        game._deal_damage_to_player(
            victim, damage, source=source_permanent or card,
            then=_report_subject, asks=True,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "chosen_player":
        # "Choose a player who cast one or more sorcery spells this turn.
        # Backdraft deals damage to **that player** …" The seat an earlier step
        # of this same resolution chose, read out of the scratchpad rather than
        # off `context.target`: nothing was targeted, so the target slot holds
        # whatever a targetless resolution defaults to — which in a
        # three-player game is not the player who was chosen. No record means
        # the sentence in front chose nobody, and no damage is dealt rather
        # than a guess being damaged.
        seat = context.results.get("chosen_player")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no player was chosen, no damage dealt")
            return True, "resolved"
        chosen = game.players[seat]

        def _report_chosen(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {chosen.name}")

        game._deal_damage_to_player(
            chosen, damage, source=source_permanent or card,
            then=_report_chosen, asks=True,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "target_player":
        # "…to target player" / "…to that artifact's controller" — the seat the
        # resolution context carries, taken *because the clause names a player*
        # rather than because no permanent index happens to be set. The two
        # readings differ exactly once: a sequence whose earlier step targeted a
        # permanent (Detonate), where the index is set and means something else
        # entirely.
        def _report_face(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            # Nothing logged for zero: CR 120.8 makes a source that would deal 0
            # damage deal none at all, and Detonate for X=0 says it every time.
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {target.name}")

        game._deal_damage_to_player(
            target, damage, source=source_permanent or card, then=_report_face, asks=True
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "each_player":
        # "…deals N damage to each player" (Armageddon Clock): every living seat
        # in turn order, the source's controller included. One player-damage
        # event each, resumable so a shield or replacement that stops to ask
        # carries the rest of the loop with it — the same shape each_opponent
        # takes below, differing only in who is in the list.
        #
        # Nothing is logged for a seat dealt nothing: CR 120.8 says a source
        # that would deal 0 damage does not deal damage at all, so "dealt 0
        # damage to P2" is a line about an event that did not happen. An
        # Armageddon Clock with no counters yet says it twice a turn.
        def _hit_player(player_index: int) -> None:
            face = game.players[player_index]
            game._deal_damage_to_player(
                face, _amount_for(face), source=source_permanent or card, asks=True,
                then=lambda dealt, face=face: _record_and_log(dealt, face),
            )

        run_resumable(
            game,
            [i for i, p in enumerate(game.players) if not p.lost],
            _hit_player,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "each_opponent":
        # "…deals N damage to each opponent": one player-damage event per
        # living opponent, in seat order, resumable so a shield or replacement
        # that stops to ask carries the rest of the loop with it.
        def _hit_opponent(opponent_index: int) -> None:
            face = game.players[opponent_index]
            game._deal_damage_to_player(
                face, _amount_for(face), source=source_permanent or card, asks=True,
                then=lambda dealt, face=face: _record_and_log(dealt, face),
            )

        run_resumable(game, game.opponents_of(game.players.index(caster)), _hit_opponent)
        return True, "resolved"
    # A divided spell's cross-seat list: any mix of creatures and player faces
    # on both sides. How much each one gets is `engine/divided_damage.py` —
    # the caster's announced division (CR 601.2d) for "divided as you choose",
    # and "divided evenly, rounded down" otherwise. It was `damage // n` for
    # both, so four cards printing the second sentence were played as the first.
    divided = context.choices.get(DIVIDED_TARGETS)
    if divided:
        entries = [
            entry
            for entry in divided
            for seat, index, _share in (divided_entry(entry),)
            if 0 <= seat < len(game.players)
            and (index is None or 0 <= index < len(game.players[seat].battlefield))
        ]
        if not entries:
            game.log.append(f"{card.name} had no remaining targets")
            return True, "resolved"
        # A target that has left keeps its share out of the event — CR 608.2b
        # makes it an illegal target, and nothing redistributes what was
        # assigned to it. Dividing over the survivors is what the *even* split
        # has always done and is what an unannounced division still means.
        division = (instruction.payload.get("targets") or {}).get("division", EVENLY)
        assigned = divide(damage, entries, division=division)
        # Creatures first (highest index first so removals can't shift earlier
        # indices), then faces. One resumable list rather than two loops: a
        # target that stops to ask the player something has to take the targets
        # behind it with it, and "behind it" spans both groups.
        ordered = sorted(
            (e for e in assigned if e[1] is not None), key=lambda e: e[1], reverse=True
        ) + [e for e in assigned if e[1] is None]

        def hit(entry) -> None:
            seat, index, share = entry
            if index is None:
                face = game.players[seat]
                game._deal_damage_to_player(
                    face, share, source=card, asks=True,
                    then=lambda dealt: game.log.append(
                        f"{card.name} dealt {dealt} damage to {face.name}"
                    ),
                )
                return
            target_perm = game.players[seat].battlefield[index]
            game._mark_damage_on_permanent(
                target_perm, share, source=source_permanent or card, asks=True,
                then=_damage_reporter(game, card, target_perm),
            )

        run_resumable(game, ordered, hit)
        return True, "resolved"
    # Support multiple target indices for spells like Fireball
    if isinstance(target_perm_idx, list):
        # `_stack_push` stamped an id per chosen index, positionally and
        # None-padded, so the two lists pair up. Resolving each through the seam
        # means a target that survived is still hit even if an earlier one died
        # and shifted every later slot — which is precisely what a multi-target
        # spell waiting on the stack is exposed to.
        ids = context.target_permanent_id
        if not isinstance(ids, list):
            ids = [None] * len(target_perm_idx)
        chosen = []
        for position, idx in enumerate(target_perm_idx):
            permanent_id = ids[position] if position < len(ids) else None
            found = game.chosen_permanent(target, idx, permanent_id)
            if found is not None:
                chosen.append(found)
        n = len(chosen)
        if n == 0:
            # CR 608.2b: every chosen creature target is gone, so the spell
            # does nothing — it must not fall back to damaging the player.
            game.log.append(f"{card.name}: no remaining legal targets (CR 608.2b)")
            return True, "resolved"
        per_target = damage // n if n > 0 else 0
        # Highest slot first, so a death here cannot shift a target this loop
        # has not reached yet. Kept even though each target is now resolved up
        # front: `_mark_damage_on_permanent` reads the battlefield itself.
        for target_perm in sorted(
            chosen, key=lambda perm: game.battlefield_index_of(perm) or 0, reverse=True
        ):
            game._mark_damage_on_permanent(
                target_perm, per_target, source=source_permanent or card,
                then=_damage_reporter(game, card, target_perm),
            )
        return True, "resolved"
    if isinstance(target_perm_idx, int):
        # Damage targets a creature permanent, not the player.
        #
        # The id is asked *first*, and the CR 608.2b refusal below is what the
        # bounds check became. Order matters here and it is easy to get wrong:
        # a standalone `not 0 <= idx < len(battlefield)` guard in front of this
        # returned "target is gone" for a target that had merely been
        # *renumbered* — every creature below it dying shortens the list — so
        # the id lookup behind it could never run. Resolving first and refusing
        # on None means the spell fizzles when the target is genuinely gone and
        # finds it when it only moved.
        target_perm = game.chosen_permanent(
            target, target_perm_idx, context.target_permanent_id
        )
        if target_perm is None:
            # CR 608.2b: a creature was targeted but is no longer on the
            # battlefield — the spell does nothing rather than hitting the player.
            game.log.append(f"{card.name}: target creature is gone, no effect (CR 608.2b)")
            return True, "resolved"
        # 115.4: "any target" is limited to creatures, players, planeswalkers, and battles.
        # Noncreature artifacts (and other noncreature non-planeswalker permanents) are not
        # valid "any target" targets — the spell fizzles against them.
        targets = instruction.payload.get("targets") or {}
        if targets.get("quantifier") == "any_target":
            # is_creature / has_type (not the printed type line) so animated
            # lands — Kormus Bell swamps, Living Lands forests — count as
            # creatures here, and a layer-4 type change is honored.
            if not target_perm.is_creature and not target_perm.has_type("planeswalker"):
                game.log.append(
                    f"{card.name}: '{target_perm.card.name}' is not a valid 'any target' target (115.4)"
                )
                return True, "resolved"
        # A Jade Monolith redirect (source-aware) is handled inside
        # _mark_damage_on_permanent so combat and spell damage share one path.
        # Disintegrate-style riders: the damaged creature can't be regenerated
        # this turn, and if it would die this turn it is exiled instead (a
        # replacement effect honored by _destroy_marked_creatures / _permanent_to_graveyard).
        if target_perm.is_creature:
            if instruction.payload.get("no_regen"):
                target_perm.metadata["cant_be_regenerated_this_turn"] = True
            if instruction.payload.get("exile_if_dies"):
                target_perm.metadata["exile_if_dies_this_turn"] = True
        _record_damage_recipient(context, target_perm)
        apply_damage_to_creature(
            game, target_perm, damage, source_permanent or card,
            log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {target_perm.card.name}",
            # Recorded so a later instruction in the same resolution can read it
            # ("You gain life equal to the damage dealt").
            then=lambda dealt: context.results.__setitem__("damage_dealt", dealt),
            asks=True,
            unpreventable=unpreventable,
        )
    elif several.get("kind") == "object":
        from ..subject_filters import subject_matches
        # "…deals N damage to target creature" (Silent Dart), activated with no
        # index named — a headless or AI caller. The target is an object, so a
        # legal one is scanned for the way every other single-target handler
        # does; the face is never the fallback for an object target, which is
        # how the ability came to deal to the player when no creature was
        # chosen. None left → CR 608.2b, the ability does nothing.
        victim = resolve_target_permanent(
            game, context,
            predicate=lambda perm: subject_matches(game, perm, described),
        )
        if victim is None:
            game.log.append(f"{card.name}: no legal target, no effect (CR 608.2b)")
            return True, "resolved"
        if victim.is_creature:
            if instruction.payload.get("no_regen"):
                victim.metadata["cant_be_regenerated_this_turn"] = True
            if instruction.payload.get("exile_if_dies"):
                victim.metadata["exile_if_dies_this_turn"] = True
        _record_damage_recipient(context, victim)
        apply_damage_to_creature(
            game, victim, damage, source_permanent or card,
            log_message=lambda dealt: f"{card.name} dealt {dealt} damage to {victim.card.name}",
            then=lambda dealt: context.results.__setitem__("damage_dealt", dealt),
            asks=True,
            unpreventable=unpreventable,
        )
    else:
        def _report(damage: int) -> None:
            context.results["damage_dealt"] = damage
            if source_permanent is not None:
                game.log.append(f"{card.name} dealt {damage} damage")
            else:
                game.log.append(f"{target.name} took {damage} damage")

        _record_damage_recipient(context, None, target)
        game._deal_damage_to_player(
            target, damage, source=source_permanent or card, then=_report, asks=True
        )
    return True, "resolved"


@effect_handler("deal_damage_to_player")
def deal_damage_to_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A triggered ability that deals a fixed amount of damage to a player, resolving
    off the stack. Used by triggers that previously dealt damage inline at fire time:
    Dingus Egg (land dies), the land-enters 2-damage trigger, and Aura death damage.
    The victim and amount are carried in ``trigger_context`` so a synthetic instruction
    (no parsed payload) is enough."""
    tctx = context.trigger_context or {}
    victim_idx = tctx.get("victim_player_index")
    amount = int(tctx.get("amount", 0))
    if victim_idx is None or not (0 <= victim_idx < len(game.players)) or amount <= 0:
        return True, "resolved"
    victim = game.players[victim_idx]
    game._deal_damage_to_player(
        victim, amount, source=context.source_permanent,
        then=lambda dealt: game.log.append(
            f"{context.card.name} dealt {dealt} damage to {victim.name}"
        ),
    )
    return True, "resolved"


@effect_handler("simulacrum_redirect")
def simulacrum_redirect(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    # Simulacrum: caster gains life equal to the damage dealt to them this turn,
    # then deals that much damage to a target creature they control.
    caster = context.caster
    card = context.card
    amount = max(0, caster.damage_taken_this_turn)

    if amount > 0:
        game._gain_life(caster, amount, card.name)

    target_perm = resolve_target_permanent(game, context, player=caster)
    if target_perm is None:
        game.log.append(f"{card.name}: no creature to deal damage to")
        return True, "resolved"

    apply_damage_to_creature(
        game, target_perm, amount, card,
        log_message=lambda dealt: (
            f"{card.name} dealt {dealt} damage to {target_perm.card.name} and {caster.name} gained {amount} life"
        ),
    )
    return True, "resolved"


def _sweep_amount(instruction: OracleInstruction, context: OracleExecutionContext) -> int:
    """How much a board sweep deals — a printed number, an announced X, the
    counters on the ability's own source, or a record an earlier step of the
    same effect wrote.

    The third is Time Bomb's ("deals damage equal to the number of time
    counters on it to each creature and each player"), and it is here rather
    than in one of the four sweep handlers because the question is the *amount*
    and not the shape of the sweep. `deal_damage` reads the same key one
    function up; a sweep that could not read it refused the whole line, which
    is what left Time Bomb's only ability doing nothing.

    The fourth is Volcanic Eruption's ("…equal to the number of Mountains put
    into a graveyard this way"): ``amount_from`` names a scratchpad key exactly
    as it does on `deal_damage`, and an absent record deals nothing rather than
    an amount the card never printed.
    """
    from_results = instruction.payload.get("amount_from")
    if from_results is not None:
        return max(0, int((context.results or {}).get(from_results, 0) or 0))
    named = instruction.payload.get("amount_from_named_counters")
    if named is not None:
        source = context.source_permanent
        return counters_on(source, str(named)) if source is not None else 0
    return resolve_amount(instruction.payload.get("amount", 0), context.x_value)


@effect_handler("deal_damage_each_creature_and_player")
def deal_damage_each_creature_and_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    amount = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(game, card, amount, lambda perm: True)
    game.log.append(f"{card.name} dealt {amount} damage to each creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_and_self_damage")
def deal_damage_and_self_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    caster = context.caster
    target = context.target
    card = context.card
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    self_damage = int(instruction.payload.get("self_damage", 0))
    target_perm_idx = context.target_permanent_index
    target_perm = game.chosen_permanent(
        target, target_perm_idx, context.target_permanent_id
    )
    if target_perm is not None:
        game._mark_damage_on_permanent(
            target_perm, amount, source=card,
            then=lambda dealt: game.log.append(
                f"{card.name} dealt {dealt} damage to {target_perm.card.name}"
            ),
        )
    else:
        game._deal_damage_to_player(
            target, amount, source=card,
            then=lambda damage: game.log.append(
                f"{card.name} dealt {damage} damage to {target.name}"
            ),
        )
    game._deal_damage_to_player(
        caster, self_damage, source=card,
        then=lambda dealt: game.log.append(
            f"{card.name} dealt {dealt} damage to {caster.name} (self-damage)"
        ),
    )
    return True, "resolved"


def _has_flying(perm: Permanent) -> bool:
    """Flying from any source — printed, granted, or granted then removed.
    Reading the grant flags directly would miss whichever route a future card
    uses and would get grant-after-removal backwards (CR 613.9)."""
    return perm.has_keyword("flying")


def _mass_damage_players_and_creatures(game: Game, card, damage: int, creature_predicate) -> None:
    """Earthquake/Hurricane sweep: damage every player, then every creature
    passing the predicate, then destroy the lethally damaged as one SBA batch.

    Through ``apply_damage_to_creature``, never ``_mark_damage_on_permanent``:
    the marking is only half of a damage event, and the other half is
    ``_fire_dealt_damage_triggers``. Every sweep in this file reached for the
    lower call and so dealt damage that nothing could notice — Fungusaur took a
    point from Earthquake and grew no counter across five shipped sets. The
    per-creature triggers are correct here rather than batched: CR 603.2 puts
    one on the stack per creature dealt to, and the state-based sweep that kills
    them still runs once, after."""
    for player in game.players:
        game._deal_damage_to_player(player, damage, source=card)
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and creature_predicate(perm):
                apply_damage_to_creature(game, perm, damage, card)


@effect_handler("earthquake_damage")
def earthquake_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(game, card, damage, lambda perm: not _has_flying(perm))
    game.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
    return True, "resolved"


@effect_handler("hurricane_damage")
def hurricane_damage(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    card = context.card
    damage = _sweep_amount(instruction, context)
    _mass_damage_players_and_creatures(game, card, damage, _has_flying)
    game.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
    return True, "resolved"


@effect_handler("deal_damage_to_random_creatures")
def deal_damage_to_random_creatures(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Damage a randomly chosen handful of creatures, optionally tapping them.

    Falling Star: the creatures a flipped card "lands on" are chosen by
    ``engine.dexterity``, which is where that substitution is explained. Only
    the *count* is this card's — the payload carries it, so a card landing on a
    different number needs no code here.

    The damage goes through ``apply_damage_to_creature`` like any other
    non-combat damage, so shields, replacements, lifelink and "dealt damage"
    triggers all see it, and death is left to the state-based sweep. Tapping
    reads what was **actually dealt**: a creature whose damage was fully
    prevented was not "dealt damage by" the source (CR 615.1), so it does not
    tap.
    """
    card = context.card
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    minimum = int(instruction.payload.get("minimum", 0))
    maximum = int(instruction.payload.get("maximum", 1))
    tap_damaged = bool(instruction.payload.get("tap_damaged", False))

    candidates = [perm for _seat, perm in game.permanents_with_controller() if perm.is_creature]
    hits = flip_lands_on(candidates, minimum=minimum, maximum=maximum)
    if not hits:
        game.log.append(f"{card.name} landed on no creatures")
        return True, "resolved"

    def _hit(perm: Permanent) -> None:
        def _after(dealt: int) -> None:
            if dealt > 0 and tap_damaged:
                game.become_tapped(perm)

        apply_damage_to_creature(
            game, perm, amount, card,
            log_message=lambda dealt: (
                f"{card.name} landed on {perm.card.name} and dealt {dealt} damage"
            ),
            then=_after,
        )

    for perm in hits:
        _hit(perm)
    return True, "resolved"


@effect_handler("deal_damage_each_attacking_creature")
def deal_damage_each_attacking_creature(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Sandstorm: "deals 1 damage to each attacking creature." Creature-only
    sweep across every battlefield — no player damage — resolved as one SBA
    batch so simultaneous lethal damage kills together."""
    card = context.card
    damage = _sweep_amount(instruction, context)
    struck = 0
    for player in game.players:
        for perm in list(player.battlefield):
            if perm.is_creature and perm.attacking:
                apply_damage_to_creature(game, perm, damage, card)
                struck += 1
    game.log.append(f"{card.name} dealt {damage} damage to each of {struck} attacking creatures")
    return True, "resolved"


@effect_handler("coin_flip_damage_loop")
def coin_flip_damage_loop(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Mana Clash: "You and target opponent each flip a coin. … deals 1 damage
    to each player whose coin comes up tails. Repeat this process until both
    players' coins come up heads on the same flip."

    Two flips a round (CR 705.1), one per player, because "both players' coins"
    is two coins — one flip read twice would make the exit condition a 1-in-2
    rather than a 1-in-4 and would never let one player take damage alone.

    **This damage deliberately does not ask CR 616.1's ordering question.** The
    mechanism behind an ask is a *restart*: the event is re-run once the seat has
    answered (see `engine/resumption.py`). Re-running anything inside this loop
    would re-flip its coins, so the answer would be applied to a different
    random outcome than the one it was asked about — a worse failure than not
    asking. Every other damage path in the engine is re-runnable and does ask.

    The round cap is not a rule. CR 705 makes this terminate with probability 1
    (a quarter of rounds end it), and a seeded RNG that failed to is a bug in
    the RNG rather than a game state anyone should hang on.
    """
    caster = context.caster
    opponent = context.target
    card = context.card
    if opponent is None or opponent is caster:
        game.log.append(f"{card.name}: no opponent to flip against")
        return True, "resolved"
    damage = resolve_amount(instruction.payload.get("amount", 1), context.x_value)
    rounds = 0
    while rounds < 1000:
        rounds += 1
        caster_heads = flip_coin()
        opponent_heads = flip_coin()
        game.log.append(
            f"{card.name}: {caster.name} flipped "
            f"{'heads' if caster_heads else 'tails'}, {opponent.name} flipped "
            f"{'heads' if opponent_heads else 'tails'}"
        )
        if not caster_heads:
            game._deal_damage_to_player(caster, damage, source=card)
        if not opponent_heads:
            game._deal_damage_to_player(opponent, damage, source=card)
        if caster_heads and opponent_heads:
            break
    game.log.append(f"{card.name}: both coins came up heads after {rounds} flip(s)")
    return True, "resolved"


@effect_handler("deal_damage_to_those_damaged_this_game")
def deal_damage_to_those_damaged_this_game(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"At the beginning of your upkeep, this creature deals 1 damage to each
    opponent and planeswalker **it has dealt damage to this game**." (The
    Fallen.)

    The recipients come off the record the damage seam keeps on this permanent
    (``engine/damage_events.DAMAGED_THIS_GAME``), never off the board: a board
    read cannot tell an opponent this creature has hurt from one it has not.

    Everything in the record is an identity rather than a position — a seat
    index and a ``permanent_id`` — so a planeswalker that left and came back is
    a different object and is not damaged (CR 400.7), and one that is simply
    gone is skipped rather than resolved onto whatever slid into its slot. A
    seat recorded while it was an opponent that is no longer one is skipped too:
    the card says "each **opponent**", asked now.
    """
    from ..damage_events import DAMAGED_THIS_GAME

    card = context.card
    source = context.source_permanent
    if source is None:
        game.log.append(f"{card.name}: its source is gone, no damage dealt")
        return True, "resolved"
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    classes = set(instruction.payload.get("classes") or ())
    record = source.metadata.get(DAMAGED_THIS_GAME) or {}
    controller = game.controller_index_of(source)
    struck = []
    if "opponent" in classes:
        for seat in list(record.get("seats") or ()):
            if seat == controller or not (0 <= seat < len(game.players)):
                continue
            victim = game.players[seat]
            game._deal_damage_to_player(victim, damage, source=source, asks=True)
            struck.append(victim.name)
    if "planeswalker" in classes:
        for permanent_id in list(record.get("permanents") or ()):
            walker = game.permanent_by_id(permanent_id)
            if walker is None or not walker.has_type("planeswalker"):
                continue
            apply_damage_to_creature(game, walker, damage, source)
            struck.append(walker.card.name)
    game.log.append(
        f"{card.name} dealt {damage} damage to {', '.join(struck)}"
        if struck else f"{card.name} has dealt damage to nobody yet"
    )
    return True, "resolved"


@effect_handler("deal_damage_to_recorded_permanents")
def deal_damage_to_recorded_permanents(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Tap X target creatures. Winter Blast deals 2 damage to each of **those
    creatures with flying**."

    Not a sweep and not a target: the recipients are whatever an earlier step of
    this same effect recorded (CR 611.2c fixed the set when the effect began),
    narrowed by the printed adjective. By id, because a permanent may have left
    in between (CR 400.7) and a slot would by then address whichever creature
    slid into it; one that has left is simply not damaged, which is what an
    empty record means.
    """
    from ..subject_filters import subject_matches

    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    described = instruction.payload.get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    recorded = (context.results or {}).get(
        str(instruction.payload.get("permanents_from", ""))
    ) or ()
    struck = []
    for permanent_id in recorded:
        permanent = game.permanent_by_id(permanent_id)
        if permanent is None:
            continue
        if not subject_matches(
            game, permanent, described,
            observer=observer, source=context.source_permanent,
        ):
            continue
        apply_damage_to_creature(game, permanent, damage, card)
        struck.append(permanent.card.name)
    game.log.append(
        f"{card.name} dealt {damage} damage to {', '.join(struck)}"
        if struck else f"{card.name} found none of those permanents to damage"
    )
    return True, "resolved"


@effect_handler("self_damage_unless_pay")
def self_damage_unless_pay(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Hasran Ogress: "Whenever this creature attacks, it deals 3 damage to
    you unless you pay {2}." Arms a pending optional-pay entry for the
    controller (the same prompt flow as the color rods); declining — or being
    unable to pay — deals the damage. Headless/AI paths resolve it via
    auto_resolve_pending_optional_pays."""
    caster = context.caster
    card = context.card
    amount = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    cost = int(instruction.payload.get("cost", 0))
    seat = game.players.index(caster)
    if instruction.payload.get("payer") == "event_subject_player":
        # "…deals 2 damage to **that player** unless they pay {2}" (Soul
        # Barrier, Seizures). The seat the fire site froze (CR 603.10) — the
        # trigger has no target, so `context.caster` is the ability's controller
        # and offering *them* the cost would charge and damage the wrong player.
        #
        # No record means the words named nobody, and nothing happens: the same
        # rule the "deals damage to that player" branch above follows, and the
        # safe one — a prompt aimed at a guessed seat is a card doing something
        # it never says.
        recorded = (context.trigger_context or {}).get("event_subject_player")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card.name}: no recorded player, nothing offered")
            return True, "resolved"
        seat = recorded
    elif instruction.payload.get("payer") == "event_subject_controller":
        # "…deals 3 damage to **that creature's controller** unless that player
        # pays {3}" (Seizures). The branch above one question over: the seat
        # that controlled the object the event was about, frozen by the tap
        # announcement under its own key. Read the same way, and refused the
        # same way — a prompt aimed at a guessed seat is a card doing something
        # it never says.
        recorded = (context.trigger_context or {}).get("event_subject_controller")
        if not isinstance(recorded, int) or not (0 <= recorded < len(game.players)):
            game.log.append(f"{card.name}: no recorded player, nothing offered")
            return True, "resolved"
        seat = recorded
    record = instruction.payload.get("payer_seat_record")
    if record is not None:
        # "For each land destroyed this way, <source> deals 1 damage to **that
        # land's controller** unless they pay {2}." (Stench of Evil.) The seat
        # an earlier step of this same resolution wrote down about the object
        # the loop is currently on — `for_each` resolves the record to this
        # iteration's entry before running the step, so the lookup is by the
        # record's name and never by the object.
        #
        # No entry means the loop is not running or recorded nothing about this
        # object, and nothing is offered: the same rule the frozen-event branch
        # above follows, and the safe one.
        found = context.iteration_seats.get(str(record))
        if not isinstance(found, int) or not (0 <= found < len(game.players)):
            game.log.append(f"{card.name}: no recorded controller, nothing offered")
            return True, "resolved"
        seat = found
    payer = game.players[seat]
    game.arm_pending_choice(
        "optional_pay", seat,
        card_name=card.name, cost=generic_cost(cost), life=0, damage=amount,
        _source_permanent=context.source_permanent,
    )
    game.log.append(
        f"{payer.name} may pay {{{cost}}} or {card.name} deals {amount} damage to them"
    )
    return True, "resolved"


@effect_handler("deal_damage_and_opponent_choice")
def deal_damage_and_opponent_choice(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """Cuombajj Witches: "{T}: This creature deals 1 damage to any target and
    1 damage to any target of an opponent's choice." The controller's chosen
    target rides the normal context targeting (handled by deal_damage); the
    opposing choice becomes a pending prompt for a human chooser, or a
    deterministic pick (kill a creature of the activator's if able, else the
    activator's face) for AI/headless play."""
    deal_damage(game, instruction, context)

    caster_index = game.players.index(context.caster)
    chooser_index = next(
        (i for i, p in enumerate(game.players) if i != caster_index and not p.lost), None
    )
    if chooser_index is None:
        return True, "resolved"
    amount = int(instruction.payload.get("opponent_amount", instruction.payload.get("amount", 0)))
    # An interactive chooser is prompted; every other seat takes the kind's
    # deterministic default the moment this is armed.
    if game.arm_pending_choice(
        "opponent_damage", chooser_index,
        caster_index=caster_index, amount=amount, card_name=context.card.name,
        _source_permanent=context.source_permanent,
    ) is not None:
        game.log.append(
            f"{game.players[chooser_index].name} chooses any target for {context.card.name}'s {amount} damage"
        )
    return True, "resolved"


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


@effect_handler("source_bites_target")
def source_bites_target(game, instruction, context):
    """"It deals damage equal to its power to target creature or planeswalker."
    (Heartfire Immolator.)

    The source paid for this by being **sacrificed**, so by the time it resolves
    it is in a graveyard. Its power is last-known information (CR 608.2), and
    the ``Permanent`` object still carries it: the layer state is recomputed
    without the permanent, but the metadata the bonuses live in belongs to the
    object and nothing off the battlefield touches it. A prowess-pumped
    Immolator therefore deals three, which is the case that makes the
    distinction observable — and its test.
    """
    card = context.card
    source = context.source_permanent
    # ``biter: "attached"`` — the permanent the source is attached to deals the
    # damage (Farrel's Mantle). CR 113.7a leaves the ability the Aura's, so the
    # source is still the Aura and only the dealer moves; read off the source
    # rather than off the target, because an Aura that has fallen off has no
    # creature to bite with and must deal nothing rather than bite with itself.
    if instruction.payload.get("biter") == "attached":
        source = attached_host(game, source)
    if source is None:
        game.log.append(f"{card.name}: nothing to deal the damage")
        return True, "resolved"
    filters = instruction.payload.get("filter") or {}
    victim = resolve_target_permanent(
        game, context,
        # "…to **another** target creature": re-checked here rather than
        # trusted from the picker, the rule every narrowed handler follows —
        # and it is the *biter* that is excluded, which for an Aura is not the
        # ability's source.
        predicate=lambda perm: (
            perm is not source and permanent_matches_filter(perm, filters)
        ),
    )
    # What the sentence after this one means by "that creature" (Tracker), by
    # stable id and recorded on **every** path — a producer `_PRODUCES` names
    # that writes only when it hits would leave the next sentence silently
    # acting on nothing. Written before the damage, not after: the damage is
    # resumable (a replacement may ask a question mid-event), and a record
    # stamped after the loop is a record stamped after the resumption returns.
    context.results["damaged_permanents"] = (
        (victim.permanent_id,) if victim is not None else ()
    )
    if victim is None:
        game.log.append(f"{card.name}: no valid target")
        return True, "resolved"
    # "…equal to its power **plus 2**" (Farrel's Mantle). CR 107.3's printed
    # constant, added here rather than folded into the power: what the creature
    # *has* is still its power, and a lord counting it must not see the bonus.
    amount = source.effective_power + int(instruction.payload.get("power_bonus", 0))
    apply_damage_to_creature(
        game, victim, amount, source,
        log_message=lambda dealt: (
            f"{source.card.name} deals {dealt} damage to {victim.card.name}"
        ),
        asks=True,
    )
    return True, "resolved"


@effect_handler("bound_bites_source")
def bound_bites_source(game, instruction, context):
    """"That creature deals damage equal to its power to this creature."
    (Tracker's second sentence.)

    The mirror of the bite above with the two ends swapped: the biter is the
    creature the sentence in front of this one chose — read out of the
    resolution scratchpad, never chosen again — and the bitten is the ability's
    own source.

    Not CR 701.14's fight, which this pair looks like. A fight is
    all-or-nothing (701.14b): if either creature has left the battlefield,
    *neither* deals damage. These are two printed sentences, so the first one
    has already happened, and a source that is gone by now simply takes
    nothing.

    The biter's power is read now rather than when the first half resolved,
    which is what the printed order says: a creature that lost the exchange's
    first half is still on the battlefield here (CR 704.3 checks state-based
    actions only when a player would receive priority) and bites back at full
    strength.
    """
    key = instruction.payload.get("permanents_from")
    recorded = context.results.get(key) or ()
    target = context.source_permanent
    if target is None or not game.is_on_battlefield(target):
        game.log.append(f"{context.card.name}: nothing left to bite back")
        return True, "resolved"
    for permanent_id in recorded:
        biter = game.permanent_by_id(permanent_id)
        if biter is None or not biter.is_creature:
            # It left the battlefield, or stopped being a creature. A dead
            # creature deals no damage (CR 608.2's last-known information is
            # about *reading* it, not about acting from a graveyard).
            continue
        apply_damage_to_creature(
            game, target, biter.effective_power, biter,
            log_message=lambda dealt, biter=biter: (
                f"{biter.card.name} deals {dealt} damage to {target.card.name}"
            ),
            asks=True,
        )
    return True, "resolved"


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


@effect_handler("target_bites_target")
def target_bites_target(game, instruction, context):
    """"Target creature you control deals damage equal to its power to another
    target creature." (Garruk, Savage Herald's -2.) Two chosen targets resolved
    positionally: the biter first, the bitten second. Both are resolved by id
    without an owner constraint - the biter must be the caster's, the bitten
    anyone's, and the two must differ (the printed "another")."""
    ids = context.target_permanent_id
    if not isinstance(ids, list):
        ids = [ids, None]
    resolved = [game.permanent_by_id(pid) if isinstance(pid, int) else None for pid in ids]
    biter = resolved[0] if resolved else None
    bitten = resolved[1] if len(resolved) > 1 else None
    caster_index = game.players.index(context.caster)
    if biter is None or not biter.is_creature or not game.controls(caster_index, biter):
        game.log.append(f"{context.card.name}: no creature you control to deal the damage")
        return True, "resolved"
    if bitten is None or not bitten.is_creature or bitten is biter:
        game.log.append(f"{context.card.name}: no other target creature to damage")
        return True, "resolved"
    amount = biter.effective_power
    apply_damage_to_creature(
        game, bitten, amount, biter,
        log_message=lambda dealt: (
            f"{biter.card.name} deals {dealt} damage to {bitten.card.name}"
        ),
        asks=True,
    )
    return True, "resolved"


@effect_handler(
    "redirect_damage_from_target_until_eot",
    "redirect_damage_from_chosen_source_until_eot",
)
def redirect_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Arm a CR 614.9 redirection on this ability's controller.

    Shimian Night Stalker: "All damage that would be dealt to you this turn by
    target attacking creature is dealt to this creature instead."
    Nova Pentacle: "The next time a source of your choice would deal damage to
    you this turn, that damage is dealt to target creature of an opponent's
    choice instead."

    One handler for both kinds, because what differs is only how the moved
    damage's source was named — a target the picker ran over, or the chosen
    source recorded at activation. The record itself
    (``engine/damage_redirects.py``) says nothing about which card armed it.

    **Nothing is armed unless every piece of the sentence resolved.** A record
    with no source watches *every* source and a record with no new recipient
    watches for nothing; both are strictly wider or strictly emptier than the
    card, and either one would report a card working while it does something
    else. The one deliberate exception is a chosen source that was never
    recorded — AI and headless activations pick no source at all — where the
    record falls back to the next damage from any source, exactly as Reverse
    Damage's and Jade Monolith's fallbacks do, because the effect is spent on
    one instance either way.
    """
    payload = instruction.payload
    caster = context.caster
    card_name = getattr(context.card, "name", "")
    targets_source = instruction.kind == "redirect_damage_from_target_until_eot"

    if payload.get("new_recipient") == "source":
        new_recipient = context.source_permanent
    else:
        chosen_id = context.results.get(payload.get("result_key"))
        new_recipient = (
            game.permanent_by_id(chosen_id) if isinstance(chosen_id, int) else None
        )
    if new_recipient is None or not game.is_on_battlefield(new_recipient):
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"

    if targets_source:
        described = (payload.get("targets") or {}).get("filter") or {}
        moved_source = resolve_target_permanent(
            game,
            context,
            predicate=lambda perm: permanent_matches_filter(perm, described),
            # No scan-the-board fallback: a redirect armed on a creature nobody
            # named moves damage the player never chose to move.
            fallback_players=(),
        )
        if moved_source is None:
            game.log.append(f"{card_name}: its target is gone, nothing is redirected")
            return True, "resolved"
    else:
        moved_source = context.choices.get("chosen_source")

    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=new_recipient,
            source=moved_source,
            uses=payload.get("uses"),
            source_name=card_name or None,
        ),
    )
    source_name = getattr(
        getattr(moved_source, "card", moved_source), "name", "any source"
    )
    game.log.append(
        f"{card_name}: damage {source_name} would deal to {caster.name} this turn "
        f"is dealt to {new_recipient.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_matching_damage_to_you_until_eot")
def redirect_matching_damage_to_you_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Blood of the Martyr: "Until end of turn, if damage would be dealt to any
    creature, you may have that damage dealt to you instead."

    The record hangs off the **caster**, and it is the one record in the family
    that does not live on the recipient it watches. The recipients are a printed
    noun phrase — every creature, including the ones that enter after this
    resolves — so there is no object to hang it on and nothing to update when
    one arrives. Hanging it on the taker instead means the cleanup sweep that
    already clears a player's redirects clears this one too, with no new
    lifetime and no new field
    (see ``engine/damage_redirects.class_redirects``).
    """
    caster = context.caster
    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=caster,
            recipients=dict(instruction.payload.get("recipients") or {}),
            optional=bool(instruction.payload.get("optional")),
            source_name=getattr(context.card, "name", None),
        ),
    )
    game.log.append(
        f"{getattr(context.card, 'name', 'an effect')}: {caster.name} may take "
        "damage dealt to any creature this turn"
    )
    return True, "resolved"


@effect_handler("redirect_source_class_damage_until_eot")
def redirect_source_class_damage_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Kjeldoran Royal Guard: "{T}: All combat damage that would be dealt to you
    by unblocked creatures this turn is dealt to this creature instead."

    The record hangs off the **caster**, which is the recipient it protects, so
    the cleanup sweep that already clears a player's redirects ends it — no new
    lifetime and no new field. What it answers to is the printed noun phrase
    rather than one chosen object: ``sources`` is re-asked of each damage source
    when the damage would be dealt (CR 614.9 fixes nothing when the ability
    resolves), so a creature that is still unblocked in the combat damage step
    is covered and one that got blocked is not.

    The Guard itself is the new recipient, read off ``source_permanent`` rather
    than described — and if it has left the battlefield by the time the damage
    would be dealt, ``live_recipient`` makes the redirect do nothing, which is
    CR 614.9 rather than a failure here.
    """
    caster = context.caster
    guard = context.source_permanent
    card_name = getattr(context.card, "name", None)
    if guard is None:
        game.log.append(f"{card_name}: nothing is there to take the damage")
        return True, "resolved"
    add_redirect(
        caster,
        DamageRedirect(
            new_recipient=guard,
            sources=dict(instruction.payload.get("sources") or {}),
            combat_only=bool(instruction.payload.get("combat_only")),
            uses=None,
            source_name=card_name,
        ),
    )
    game.log.append(
        f"{card_name}: {'combat ' if instruction.payload.get('combat_only') else ''}"
        f"damage matching sources would deal to {caster.name} this turn is dealt "
        f"to {guard.card.name} instead"
    )
    return True, "resolved"


@effect_handler("redirect_damage_from_target_spell_until_eot")
def redirect_damage_from_target_spell_until_eot(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """Reverberation: "All damage that would be dealt this turn by target
    sorcery spell is dealt to that spell's controller instead."

    The record hangs off the **stack item**, not off a recipient and not off the
    card, and that is the whole of what makes this card possible. A spell's
    damage source is its printed ``CardDefinition`` (CR 109.5) — one object per
    card, handed out once per copy by the deck builder — so a record matching on
    the source would move a *second* copy's damage too. A ``StackItem`` is one
    object per cast, and ``Game.resolving_items`` is where the damage paths can
    reach it (see ``engine/damage_redirects.resolving_object_redirects``).

    The chosen spell's type is re-checked here rather than trusted from the
    cast: CR 608.2b asks whether the target is still legal when the spell
    resolves, and a spell that has changed type in between is one this card no
    longer names.
    """
    item = context.stack_target
    card_name = getattr(context.card, "name", "")
    if item is None or not any(entry is item for entry in game.stack):
        game.log.append(f"{card_name}: the spell it named is no longer on the stack")
        return True, "resolved"
    wanted = instruction.payload.get("card_types") or ()
    if wanted and getattr(item.card, "primary_type", None) not in wanted:
        game.log.append(
            f"{card_name}: {item.card.name} is no longer "
            f"{'/'.join(str(t) for t in wanted)} spell it named"
        )
        return True, "resolved"
    controller = game.players[item.caster_index]
    add_redirect(
        item,
        DamageRedirect(
            new_recipient=controller,
            # The spell's own card, so that damage *another* source deals while
            # this one resolves — a sorcery that has a creature deal it — stays
            # where it was dealt. The cast is what the record is found by; the
            # card is what it answers to.
            source=item.card,
            source_name=card_name or None,
        ),
    )
    game.log.append(
        f"{card_name}: damage {item.card.name} would deal is dealt to "
        f"{controller.name} instead"
    )
    return True, "resolved"


@effect_handler("deal_damage_each_matching")
def deal_damage_each_matching(
    game: Game, instruction: OracleInstruction, context: OracleExecutionContext
) -> tuple[bool, str]:
    """"Goblin Shrine deals 1 damage to each Goblin creature."

    A sweep over a *described* set, not a chosen one: nothing is targeted and
    nobody picks, so every permanent the printed noun phrase names is dealt to
    (CR 611.2c fixes that set when the effect begins). The set resolves through
    ``subject_matches`` — the one answer for what a printed noun phrase means —
    with the resolving controller as the observer, because "you control" is
    that seat's "you" (CR 109.5). The lowering admits only payloads that matcher
    tests in full, so nothing here can quietly burn a wider board than the card
    prints.

    Resolved as one batch, like the attacking-creature sweep above, so
    simultaneous lethal damage kills together.
    """
    from ..subject_filters import subject_matches

    card = context.card
    damage = resolve_amount(instruction.payload.get("amount", 0), context.x_value)
    described = instruction.payload.get("filter") or {}
    caster = context.caster
    observer = game.players.index(caster) if caster in game.players else None
    struck = []
    for perm in list(game.all_permanents()):
        if not subject_matches(
            game, perm, described, observer=observer, source=context.source_permanent
        ):
            continue
        apply_damage_to_creature(game, perm, damage, card)
        struck.append(perm.card.name)
    game.log.append(
        f"{card.name} dealt {damage} damage to {', '.join(struck)}"
        if struck
        else f"{card.name} found nothing to damage"
    )
    return True, "resolved"


@effect_handler("grant_damage_riders_until_eot")
def grant_damage_riders_until_eot(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """"If the creature deals damage to a creature this turn, the creature
    dealt damage can't be regenerated this turn. If a creature dealt damage by
    the targeted creature would die this turn, exile that creature instead."
    (Runesword.)

    Two markers on the creature this ability targeted, saying what the damage
    it deals for the rest of the turn will do. Not a damage event and not a
    trigger: a trigger resolves after state-based actions have already buried
    whatever it killed, and by then there is nothing left to exile — so the
    riders are read at the damage seam itself
    (``damage_events._apply_dealer_riders``) and travel to the victim there.

    The riders are the same two Disintegrate applies to one event of its own;
    what differs is that the marker sits on the dealer. Cleared with the turn
    by ``mixins/_constants._EOT_METADATA_KEYS``.
    """
    creature = resolve_target_permanent(game, context)
    if creature is None:
        game.log.append(f"{context.card.name}: no creature to grant it to")
        return True, "resolved"
    granted: list[str] = []
    if instruction.payload.get("no_regen"):
        creature.metadata[DAMAGE_DENIES_REGENERATION] = True
        granted.append("can't be regenerated")
    if instruction.payload.get("exile_if_dies"):
        creature.metadata[DAMAGE_EXILES_INSTEAD] = True
        granted.append("is exiled if it would die")
    if granted:
        game.log.append(
            f"{context.card.name}: what {creature.card.name} damages this turn "
            + " and ".join(granted)
        )
    return True, "resolved"
