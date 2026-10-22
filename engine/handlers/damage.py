"""A source dealing damage (CR 120): the generic ``deal_damage`` and the
single-shot sentences beside it.

``deal_damage`` is the kind nearly every damage sentence lowers to — a printed
amount, a counted one, a divided one (CR 601.2d), to a target, a player, a role
of a several-target announcement, a creature an earlier step recorded — and it
is most of this module. Beside it are the damage sentences that share its
recipients and its records without being a sweep: damage to a player, to the
creatures an earlier step recorded (Winter Blast) or the ones this creature has
damaged this game (The Fallen), a source damaging its own controller (Hasran
Ogress's toll), Simulacrum's turned-around damage, Mana Clash's flips, and
Runesword's riders on what a creature's damage does for the rest of the turn.

Split at the 2,000-line cap's split round, along the lines the lowering side
had already drawn one family at a time: a **sweep** — damage to every member of
a set the game describes — is ``damage_sweeps``; a **fight** (CR 701.14) is
``fighting``; a **bite**, one object dealing damage equal to its own power, is
``bites``; and CR 614.9's **redirections**, with the other replacements on a
damage event, are ``redirection``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage_events import DAMAGE_DENIES_REGENERATION, DAMAGE_EXILES_INSTEAD
from ..divided_damage import (DIVIDED_TARGETS, EVENLY, announced_no_targets,
                              divide, divided_entry)
from ..destruction_events import mark_delayed_destruction
from ..models import Permanent
from ..named_counters import counters_on
from ..resumption import run_resumable
from ..oracle_types import (single_chosen_id, ATTACHED_PERMANENT_CONTROLLER,
                            EVENT_SUBJECT_LAST_KNOWN, LAST_DAMAGER_CONTROLLER,
                            X_FROM_COUNT_PER_RECIPIENT)
from ..mana_payment import generic_cost
from ._amounts import per_recipient_amount, resolve_amount
from ._common import apply_damage_to_creature, damage_dealer, flip_coin
from ._filters import (permanent_matches_filter, seats_controlling,
                       seats_matching_deed)
from ._targets import (divided_target_permanent, recorded_permanent_ids,
                       attached_host, frozen_that_player_seat,
                       resolve_target_permanent, resolve_target_permanents)
from .registry import effect_handler

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
    (``lowering/_counted_life._life_gain_cap_payload``).
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
    # The permanent the *sentence is printed on*, kept apart from
    # ``source_permanent`` — which from here down means the **dealer** and can
    # be moved off it by a printed subject (``biter`` below). The two were one
    # variable while every moved dealer aimed its damage somewhere else; "That
    # artifact deals damage … **to this creature**" (Goblin Tinkerer) is the
    # first sentence whose recipient is the object the dealer was moved off.
    own_permanent = context.source_permanent
    x_value = context.x_value

    # ``biter: "attached"`` — "**Enchanted creature** deals 1 damage to target
    # creature with flying" (Dizzying Gaze). The same key
    # ``source_bites_target`` has read since Farrel's Mantle and for the same
    # reason: CR 113.7a leaves the ability the Aura's and CR 120.7 makes the
    # *host* the damage's source, so only the dealer moves. Read here rather
    # than at each of this handler's dozen `source=` call sites, because the
    # source is chosen once and spent everywhere.
    #
    # An Aura that has fallen off has no host, and deals nothing rather than
    # falling back to biting as itself — which is the branch above's rule and
    # the one that keeps the wrong source from coming back by another door.
    if instruction.payload.get("biter") == "attached":
        host = attached_host(game, source_permanent)
        if host is None:
            game.log.append(f"{card.name}: nothing to deal the damage")
            return True, "resolved"
        source_permanent = host
        # …and the *log* moves with it. Every message below names ``card``, and
        # for every other card in the pool that is the object dealing the
        # damage; here it is the Aura, so leaving it would have this handler
        # report a source the rule says is not the source. ``card`` is read for
        # nothing else once ``source_permanent`` is known non-None, which the
        # early return above guarantees.
        card = host.card
    elif instruction.payload.get("biter") == "event_subject":
        # ``biter: "event_subject"`` — "Whenever a creature has four or more
        # fuse counters on it, … destroy it. **That creature** deals 4 damage
        # to its controller." (Bomb Squad.) The dealer is the object the
        # trigger's own event was about. CR 608.2h: "If an ability states that
        # an object does something, it's the object as it exists—or as it most
        # recently existed—that does it, not the ability" — so the permanent
        # itself while the id still resolves, and otherwise the object the fire
        # site froze beside the id, which is that creature as it last existed.
        # That second read is the card's ruling: with two Bomb Squads the
        # second trigger still deals 4 after the first has destroyed the
        # creature.
        #
        # The damage is the creature's own (CR 120.7): its colours for a
        # protection or a Circle, its lifelink for its controller, and never
        # Bomb Squad's. With neither read there is nothing to deal it, for the
        # reason an Aura with no host deals none.
        tctx = context.trigger_context or {}
        dealer = game.permanent_by_id(tctx.get("event_subject_permanent_id"))
        if dealer is None:
            last_known = tctx.get(EVENT_SUBJECT_LAST_KNOWN)
            dealer = last_known if isinstance(last_known, Permanent) else None
        if dealer is None:
            game.log.append(f"{card.name}: nothing to deal the damage")
            return True, "resolved"
        source_permanent = dealer
        card = dealer.effective_card
    elif (dealer_record := instruction.payload.get("biter")) is not None:
        # ``biter: "destroyed_target"`` — "Destroy target artifact. **That
        # artifact** deals damage equal to its mana value to this creature."
        # (Goblin Tinkerer.) The dealer is the object an earlier step of this
        # same resolution named, read from the record that step froze before
        # it acted (CR 608.2h) — the ``Permanent`` itself, so the damage has
        # the artifact's colours, types, keywords and controller whether the
        # artifact is in a graveyard by now or regenerated and still here
        # (CR 120.7: the source is the object that dealt it).
        #
        # No record means the step named nothing — its target was gone
        # (CR 608.2b) — and then nothing deals the damage, for the reason an
        # Aura with no host deals none: falling back to the ability's own
        # source is the wrong dealer coming back by another door.
        dealer = (context.results or {}).get(dealer_record)
        if dealer is None or not hasattr(dealer, "effective_card"):
            game.log.append(f"{card.name}: nothing to deal the damage")
            return True, "resolved"
        source_permanent = dealer
        card = dealer.effective_card

    # Rocket Launcher: "Destroy this artifact at the beginning of the next end
    # step." A consequence of having activated, so it is marked here rather
    # than sequenced — the end step's existing delayed-destruction sweep does
    # the rest (phases/end_step.py:_delayed_eot_removal).
    if instruction.payload.get("destroys_source_at_end_step") and own_permanent is not None:
        mark_delayed_destruction(game, own_permanent, "destroy_at_next_end_step")

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
    elif instruction.payload.get("amount_from_attached_power"):
        # "…**it** deals damage equal to **its power** to its controller"
        # (Consuming Ferocity), where "it" is the creature the Aura enchants.
        # The same read one object over, and the object is what matters: the
        # Aura has no power, so routed through the branch above the card would
        # deal nothing at all while compiling clean.
        #
        # The power is computed (CR 613), which is the whole card — the counter
        # this same trigger placed a step earlier is what pushes it over the
        # line.
        #
        # (``attached_host`` used to be re-imported here. It is already bound at
        # module level, and a function-level import of a name the module has —
        # harmless while it was the only reader — made the whole name *local*,
        # so the attached-dealer read added above it raised `UnboundLocalError`
        # before this line ever ran. Python scopes a name per function, not per
        # statement.)
        host = attached_host(game, source_permanent)
        damage = max(0, host.effective_power) if host is not None else 0
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
    # "…and the damage can't be prevented." (Urza's Rage.) The narrower lock —
    # prevention only — and the wider recipient: a player as much as a
    # creature. Threaded to the three branches that deal to **one chosen
    # recipient** (the two below and the face at the end), which is exactly
    # what the lowering admits the rider on.
    cant_be_prevented = bool(instruction.payload.get("cant_be_prevented"))

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
        # "…equal to the number of artifacts **they controlled** that were put
        # into a graveyard this way" (Builder's Bane). One earlier step of this
        # same resolution froze a ``{permanent_id: seat}`` map about what it
        # took, and this seat's share of it is the number. Counted off that map
        # rather than off a per-seat tally recorded beside it, because a tally
        # would be a second copy of one fact -- and the map is what the readers
        # of "its controller" already ask, so a destroy step has one thing to
        # remember rather than two that can drift.
        #
        # A seat the map never mentions lost nothing and takes nothing, which
        # is also what the words say.
        return per_recipient_amount(
            game, context, per_recipient_spec, face, source=source_permanent,
        )

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
            apply_damage_to_creature(game, perm, damage, source_permanent or card)
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
        apply_damage_to_creature(game, perm, damage, source_permanent or card)
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
        #
        # The recipient is the permanent the sentence is printed on; the
        # *dealer* is ``source_permanent``, which is the same object unless a
        # printed subject moved it (Goblin Tinkerer's destroyed artifact).
        if own_permanent is None or not game.is_on_battlefield(own_permanent):
            game.log.append(f"{card.name}: its source is gone, no damage to itself")
            return True, "resolved"
        game._mark_damage_on_permanent(
            own_permanent, damage, source=source_permanent or own_permanent,
            asks=True, then=_damage_reporter(game, card, own_permanent),
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "bound_permanent":
        # "This creature deals 2 damage to **that creature** at end of combat."
        # (Dwarven Sea Clan.) The object the creating ability bound (CR 603.7c),
        # carried by id in the trigger's context — `destroy_bound_permanent`'s
        # twin one family over, and the same reason it is its own recipient:
        # the delayed ability chose nothing when it fired, so a fall-through
        # would deal the damage to whatever the resolution context happened to
        # be carrying.
        #
        # A creature already gone is damaged by nothing, which is CR 608.2b
        # doing as much as it can rather than a failure.
        bound = (context.trigger_context or {}).get("bound_permanent_id")
        victim = (
            game.permanent_by_id(bound) if isinstance(bound, int) else None
        )
        if victim is None or not game.is_on_battlefield(victim):
            game.log.append(f"{card.name}: the creature it named is gone")
            return True, "resolved"
        apply_damage_to_creature(game, victim, damage, source_permanent or card)
        return True, "resolved"
    if instruction.payload.get("recipient") == "event_subject":
        # "Whenever a creature without flying attacks you, this enchantment
        # deals 1 damage to **it**." (Barbed Foliage.) The object the *trigger's
        # event* was about, frozen by the fire site (CR 603.10) — the sibling
        # of the bound-object branch above it, and its own recipient for the
        # same reason: the trigger chose nothing, so a fall-through would deal
        # the damage to whatever the resolution context was carrying, which for
        # a targetless trigger is a player's face.
        #
        # The printed narrowing is re-checked here rather than trusted from the
        # announcement, so a word the lowering carried is a word the resolution
        # reads.
        from ..subject_filters import subject_matches

        bound = (context.trigger_context or {}).get("event_subject_permanent_id")
        victim = (
            game.permanent_by_id(bound) if isinstance(bound, int) else None
        )
        if victim is None or not game.is_on_battlefield(victim):
            game.log.append(f"{card.name}: the creature it named is gone")
            return True, "resolved"
        described = instruction.payload.get("filter")
        if described and not subject_matches(
            game, victim, described,
            observer=game.players.index(caster), source=source_permanent,
        ):
            game.log.append(
                f"{card.name}: {victim.card.name} no longer answers the clause"
            )
            return True, "resolved"
        apply_damage_to_creature(game, victim, damage, source_permanent or card)
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
    if instruction.payload.get("recipient") == "damaged_player":
        # "Whenever Darigaaz deals combat damage to a player, … Darigaaz deals
        # damage to **the player** equal to …" (Darigaaz, the Igniter.) The seat
        # this trigger's own damage event hit, frozen by the damage seam
        # (CR 603.10) and read through the one reader of a printed "that
        # player" — the same seat ``reveal_hand`` and ``discard_hand`` resolve
        # under this word. No record means the words named nobody, and the
        # damage does not happen rather than landing on a guess.
        seat = frozen_that_player_seat(game, context)
        if seat is None:
            game.log.append(f"{card.name}: no recorded player, no damage dealt")
            return True, "resolved"
        struck = game.players[seat]

        def _report_struck(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {struck.name}")

        game._deal_damage_to_player(
            struck, damage, source=source_permanent or card,
            then=_report_struck, asks=True,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == "damaged_permanent_controller":
        # "…deals 3 damage to **that creature's controller**" (Bellowing Fiend).
        # The seat that controlled the permanent this trigger's damage event
        # *hit*, frozen by the one damage seam — the other end from
        # `event_subject_controller` directly below, which is the damager's.
        #
        # Two families read it: this one, and the life-loss handler for Death
        # Charmer's "that creature's controller loses 2 life" — both produced by
        # lowerings that ask `damage_trigger_names_damaged_end`, so a key with
        # no sentence behind it cannot appear. No record means the words named
        # nobody, and the damage does not happen rather than landing on a guess.
        seat = (context.trigger_context or {}).get("damaged_permanent_controller")
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded controller, no damage dealt")
            return True, "resolved"
        victim = game.players[seat]

        def _report_damaged(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {victim.name}")

        game._deal_damage_to_player(
            victim, damage, source=source_permanent or card,
            then=_report_damaged, asks=True,
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
    if instruction.payload.get("recipient") == "biter_controller":
        # "That creature deals 4 damage to **its controller**." (Bomb Squad.)
        # The controller of the object dealing the damage — the dealer the
        # ``biter`` key moved this handler onto, above — read as the damage is
        # dealt: whoever controls it now, or whoever controlled it as it last
        # existed on the battlefield (CR 608.2h). Not a seat frozen when the
        # ability triggered: a creature stolen in response burns the thief,
        # and one destroyed a sentence earlier burns whoever lost it.
        #
        # ``bound_bites_player`` has read the same key off a recorded biter
        # since Delirium; this is that reading for a dealer an *event* named.
        # No dealer was named, or no seat can be found for it, and nobody is
        # damaged — never the ability's own controller by default. (The dealer
        # may *be* the ability's source: Bomb Squad is a creature and can
        # light its own fuse.)
        seat = (
            game.controller_or_last_known(source_permanent)
            if source_permanent is not None
            and instruction.payload.get("biter") is not None else None
        )
        if seat is None:
            game.log.append(f"{card.name}: no controller to deal the damage to")
            return True, "resolved"
        burned = game.players[seat]

        def _report_burned(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(f"{card.name} dealt {dealt} damage to {burned.name}")

        game._deal_damage_to_player(
            burned, damage, source=source_permanent,
            then=_report_burned, asks=True,
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
    if instruction.payload.get("recipient") == ATTACHED_PERMANENT_CONTROLLER:
        # "Destroy enchanted land and this Aura deals 2 damage to **that land's
        # controller**." (Orcish Mine.) The seat the destroy step in front of
        # this one recorded about the permanent it destroyed — the sentence's
        # own antecedent rather than a target or a frozen event subject. By now
        # the land is a card in a graveyard, which CR 400.7 makes a different
        # object with no controller to ask. No record means the step in front
        # destroyed nothing, and no damage is dealt rather than a guess being
        # damaged — the same rule the two branches above follow.
        seat = context.results.get(ATTACHED_PERMANENT_CONTROLLER)
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(f"{card.name}: no recorded controller, no damage dealt")
            return True, "resolved"
        host_controller = game.players[seat]

        def _report_host(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(
                    f"{card.name} dealt {dealt} damage to {host_controller.name}"
                )

        game._deal_damage_to_player(
            host_controller, damage, source=source_permanent or card,
            then=_report_host, asks=True,
        )
        return True, "resolved"
    if instruction.payload.get("recipient") == LAST_DAMAGER_CONTROLLER:
        # "Suffocation deals 4 damage to **the controller of the last red
        # instant or sorcery spell that dealt damage to you this turn**."
        # A seat read out of the turn's damage ledger at resolution: nothing
        # chose it and no event froze it, and by now the spell it names has
        # left the stack — which is exactly why the ledger keeps the cast.
        #
        # "You" is the seat resolving this spell (CR 109.5), so the record read
        # is the caster's own.
        #
        # An empty record deals nothing rather than falling through to a face,
        # the same rule the three branches above follow. The cast gate
        # (`cast_restrictions.cast_damage_source_line`) makes that unreachable
        # from a hand — but CR 608.2b lets everything change between
        # announcement and resolution, and a copy of this spell was never
        # announced at all.
        seat = None
        described = instruction.payload.get("last_damager_filter") or {}
        if described:
            from ..damage_ledger import last_cast_that_damaged_seat

            found = last_cast_that_damaged_seat(
                game, game.players.index(caster), described
            )
            seat = found.seat if found is not None else None
        if not isinstance(seat, int) or not (0 <= seat < len(game.players)):
            game.log.append(
                f"{card.name}: nothing it names has dealt {caster.name} damage "
                "this turn, no damage dealt"
            )
            return True, "resolved"
        damager = game.players[seat]

        def _report_damager(dealt: int) -> None:
            context.results["damage_dealt"] = dealt
            if dealt:
                game.log.append(
                    f"{card.name} dealt {dealt} damage to {damager.name}"
                )

        game._deal_damage_to_player(
            damager, damage, source=source_permanent or card,
            then=_report_damager, asks=True,
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
            # "…deals 2 damage to **each player who sacrificed a Plains this
            # way**." (Desolation.) The printed relative clause, narrowing the
            # loop's list — never the amount and never the event, so a seat the
            # clause does not name is dealt no damage at all rather than zero
            # (CR 120.8 makes those the same thing, and a loop that visited it
            # would still ask every shield and replacement it has).
            # "…to **each player who controls a white creature**" (Disorder).
            # The board narrowing, applied to the same list the deed clause
            # narrows and for the same reason: a seat the clause does not name
            # is dealt no damage at all rather than zero, because a loop that
            # visited it would still ask every shield and replacement it has.
            seats_controlling(
                game,
                seats_matching_deed(
                    game, context,
                    [i for i, p in enumerate(game.players) if not p.lost],
                    instruction.payload.get("recipient_did"),
                ),
                instruction.payload.get("recipient_controls"),
            ),
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

        run_resumable(
            game,
            seats_controlling(
                game,
                seats_matching_deed(
                    game, context,
                    game.opponents_of(game.players.index(caster)),
                    instruction.payload.get("recipient_did"),
                ),
                instruction.payload.get("recipient_controls"),
            ),
            _hit_opponent,
        )
        return True, "resolved"
    # A divided spell's cross-seat list: any mix of creatures and player faces
    # on both sides. How much each one gets is `engine/divided_damage.py` —
    # the caster's announced division (CR 601.2d) for "divided as you choose",
    # and "divided evenly, rounded down" otherwise. It was `damage // n` for
    # both, so four cards printing the second sentence were played as the first.
    divided = context.choices.get(DIVIDED_TARGETS)
    if announced_no_targets(divided, instruction.payload.get("targets")):
        # "…to each of **up to** three targets", cast naming nobody (CR 115.6:
        # such a spell "is targeted only if one or more targets have been
        # chosen for it"). The cast path wrote the empty list onto the
        # announcement; with nothing on it nothing is dealt — and in
        # particular nothing falls through to the single-target path below,
        # whose default is the opposing player's face.
        game.log.append(f"{card.name} was cast with no targets")
        return True, "resolved"
    if divided:
        # Each entry is turned into the permanent it *named* once, through the
        # one resolver, and carried as the object from there. It was resolved by
        # index at the point of use, and an index is not an address: a target
        # that left renumbered every later slot, so the survivor took the share
        # announced against the departed one and the bounds check never noticed.
        live = []
        for entry in divided:
            seat, index, _share = divided_entry(entry)
            if not (isinstance(seat, int) and 0 <= seat < len(game.players)):
                continue
            if index is None:
                live.append((entry, None))
                continue
            permanent = divided_target_permanent(game, entry)
            if permanent is not None:
                live.append((entry, permanent))
        if not live:
            game.log.append(f"{card.name} had no remaining targets")
            return True, "resolved"
        # A target that has left keeps its share out of the event — CR 608.2b
        # makes it an illegal target, and nothing redistributes what was
        # assigned to it. Dividing over the survivors is what the *even* split
        # has always done and is what an unannounced division still means.
        division = (instruction.payload.get("targets") or {}).get("division", EVENLY)
        assigned = divide(damage, [entry for entry, _who in live], division=division)
        # Creatures first, highest slot first, then the faces. One resumable
        # list rather than two loops: a target that stops to ask the player
        # something has to take the targets behind it with it, and "behind it"
        # spans both groups.
        #
        # The ordering is kept now that each target is held as an *object* and
        # not as a slot, because it is still rules-visible: it is the order the
        # damage events happen in, and CR 616.1e asks the affected player which
        # effect applies as each one arrives. What it is no longer *for* is
        # safety -- an object cannot be renumbered out from under the loop.
        paired = [
            (who, seat, share)
            for (_entry, who), (seat, _index, share) in zip(live, assigned)
        ]
        ordered = sorted(
            (p for p in paired if p[0] is not None),
            key=lambda p: game.battlefield_index_of(p[0]) or 0, reverse=True
        ) + [p for p in paired if p[0] is None]

        def hit(entry) -> None:
            target_perm, seat, share = entry
            if target_perm is None:
                face = game.players[seat]
                game._deal_damage_to_player(
                    face, share, source=source_permanent or card, asks=True,
                    then=lambda dealt: game.log.append(
                        f"{card.name} dealt {dealt} damage to {face.name}"
                    ),
                )
                return
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
    if isinstance(target_perm_idx, int) or single_chosen_id(
        context.target_permanent_id
    ) is not None:
        # Damage targets a creature permanent, not the player.
        #
        # **Either address gets in.** The gate asked for the index alone, and
        # ``_stack_push`` is what stamps both — so a caller that named its
        # target the only stable way there is (CR 400.7's id, the address
        # CLAUDE.md says to prefer) fell straight past this branch to the face
        # and burned the *player*. ``web/actions.py`` fills an index in and
        # masked it; the AI, a headless driver and a test do not. The sibling
        # ``object``-quantified branch below never had the hole, because it
        # scans for a legal target rather than reading a slot — this is the
        # ``any_target`` half catching up.
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
            cant_be_prevented=cant_be_prevented,
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
            cant_be_prevented=cant_be_prevented,
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
            target, damage, source=source_permanent or card, then=_report, asks=True,
            cant_be_prevented=cant_be_prevented,
        )
    return True, "resolved"


@effect_handler("deal_damage_to_player")
def deal_damage_to_player(game: Game, instruction: OracleInstruction, context: OracleExecutionContext) -> tuple[bool, str]:
    """A triggered ability that deals a fixed amount of damage to a player,
    resolving off the stack, with victim and amount carried in
    ``trigger_context`` so a synthetic instruction (no parsed payload) is
    enough.

    One fire site builds one: the upkeep registry's ``_enqueue_upkeep_damage``,
    whose pay-or-consequence handlers compute the amount interactively. The
    Aura death-damage dispatcher in ``mixins/effects.py`` was the other, on the
    grounds that the dead creature's toughness was a number no compiled payload
    carried — which was true of its fire site rather than of the rule. The
    death site freezes ``dead_toughness`` now, so that sentence compiles like
    any other and the dispatcher is gone. The land-enters and land-dies triggers used to be
    routed here too, replacing Ankh of Mishra's and Dingus Egg's compiled
    instructions outright — they now execute those instructions against the
    seat their fire sites freeze (``event_subject_controller``)."""
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
        game, target_perm, amount, damage_dealer(context),
        log_message=lambda dealt: (
            f"{card.name} dealt {dealt} damage to {target_perm.card.name} and {caster.name} gained {amount} life"
        ),
    )
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
            target_perm, amount, source=damage_dealer(context),
            then=lambda dealt: game.log.append(
                f"{card.name} dealt {dealt} damage to {target_perm.card.name}"
            ),
        )
    else:
        game._deal_damage_to_player(
            target, amount, source=damage_dealer(context),
            then=lambda damage: game.log.append(
                f"{card.name} dealt {damage} damage to {target.name}"
            ),
        )
    game._deal_damage_to_player(
        caster, self_damage, source=damage_dealer(context),
        then=lambda dealt: game.log.append(
            f"{card.name} dealt {dealt} damage to {caster.name} (self-damage)"
        ),
    )
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
            game._deal_damage_to_player(caster, damage, source=damage_dealer(context))
        if not opponent_heads:
            game._deal_damage_to_player(opponent, damage, source=damage_dealer(context))
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
    recorded = recorded_permanent_ids(
        context, instruction.payload.get("permanents_from")
    )
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
        apply_damage_to_creature(game, permanent, damage, damage_dealer(context))
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
    per_counter = instruction.payload.get("cost_per_counter")
    if per_counter:
        # "…unless they pay {1} **for each vortex counter on this
        # enchantment**." (Energy Vortex.) CR 608.2: the price is read now,
        # not when the ability went on the stack — the counters are what the
        # rest of the card is about, and its own upkeep trigger removes them
        # all a step earlier on its controller's turn.
        #
        # A source that has left takes its counters with it (CR 122.2), which
        # leaves the price at zero — the offer is free and the damage does not
        # happen, which is CR 608.2's "as much as possible" rather than a
        # reason to skip the prompt.
        from ..named_counters import counters_on

        source = context.source_permanent
        cost *= counters_on(source, str(per_counter)) if source is not None else 0
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
