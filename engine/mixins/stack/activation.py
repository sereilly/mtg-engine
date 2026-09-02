"""Activating an ability of a permanent (CR 602): pay its cost and put it
on the stack.

The sibling of ``casting`` — same shape, different object. ``queue_permanent_ability``
is the large one: it resolves which of a multi-ability card's abilities was
chosen, checks the activation window, pays the cost, and either queues the
ability or (for a mana ability, CR 605.1a) performs it without using the stack.
"""

from __future__ import annotations

import random

from ...activation_permissions import (activation_permission_denial,
                                        card_widens_activation)
from ...restricted_mana import ACTIVATE, PaymentPurpose
from ...activation_restrictions import (
    activation_denial,
    activations_allowed_each_turn,
    at_activation_limit,
    printed_activation_caps,
    mark_activated_this_turn,
    mark_once_only_activation,
    prints_once_only_restriction,
    reads_activation_tally,
)
from ...auras import attached_ability_cost_reduction, aura_restriction_active
from ...cost_modifiers import (ability_cost_tax, ability_self_reduction_amount,
                                sacrifice_taxes)
from ...cost_tap_records import record_tapped_to_pay
from ...cost_x_definitions import cost_x_is_defined, cost_x_value
from ...mana_payment import is_mana_ability, mana_cost_from_symbols
from ...events import emit
from ...game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from ...handlers._common import _card_matches_filter, attached_host
from ...oracle import LOYALTY_ANY_TIME_STATIC, OracleInstruction, compile_card_oracle
from ...subject_filters import card_matches_any, filter_head_noun, subject_matches

# Instruction kinds whose handler performs the sacrifice its own cost clause
# names. Diamond Valley's "{T}, Sacrifice a creature: You gain life equal to
# the sacrificed creature's toughness" is one resolution: the handler picks the
# creature *because* it has to read the toughness it had on the battlefield
# (CR 608.2h, last-known information). Charging the cost generically as well
# would sacrifice two creatures for one activation. Kinds here pay it
# themselves; everything else pays through the cost path below.
#: Instruction kinds whose *handler* performs the sacrifice itself, so the
#: activation path must not also pay it — two creatures for one ability.
#:
#: `sacrifice_creature_for_mana` used to be listed here and does not belong:
#: its handler reads back what the cost ate (`sacrificed_for_cost`) and
#: sacrifices nothing. That was harmless while only Metamorphosis and Sacrifice
#: produced it — both sorceries, whose cost the *casting* path pays, so this
#: set never saw them — and it silently stopped paying the cost the moment an
#: activated ability produced the same kind (Priest of Yawgmoth).
#:
#: **Empty today, and that is the resting state.** The one entry was
#: `sacrifice_creature_gain_life_by_toughness`, Diamond Valley's fused hook: it
#: sacrificed the creature itself, so the cost path had to be told to stand
#: down. Life Chisel prints the same sentence with a different cost clause, so
#: the sentence became a production ("equal to the sacrificed creature's
#: toughness") that reads the cost's own record and sacrifices nothing — and a
#: handler that only reads does not belong here. The set survives because the
#: next fused kind will, and an empty frozenset says so more clearly than a
#: comment on an absence.
COST_PERFORMING_KINDS: frozenset[str] = frozenset()


class AbilityActivationMixin:
    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        # "…replacing all instances of one color word with another" (Balduvian
        # Shaman). A text change names *two* words, and `mana_color` is only
        # ever the second — the key an any-colour mana ability and Alchor's
        # Tomb also use. The word being replaced arrives here, on the same key
        # the cast side already carries it on, so `mark_text_modified` reads
        # one pair whether a spell or an ability asked the question.
        old_color: str | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them
        # (the web layer resolves them off the wire). Several targets may sit
        # on different battlefields, which one `target_player_index` cannot
        # express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
        # Which permanent / which card in hand pays a non-mana cost. The payer
        # chooses (CR 601.2b), so the choice arrives with the action that pays
        # it rather than through the pending-choice queue: a cost is paid during
        # activation, and a queued prompt would put the ability on the stack
        # before its cost was collected. A seat that names neither gets the
        # deterministic pick below, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        # "Tap two untapped Spirits you control" — several permanents pay one
        # cost, which one index cannot say. By id, because the list is chosen
        # before anything taps and a slot renumbers as soon as one does.
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        source_seat: int | None = None,
        source_permanent_index: int | None = None,
        source_stack_index: int | None = None,
        source_controller_index: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_permanent_ability(
            controller_index,
            permanent_name,
            target_player_index=target_player_index,
            permanent_index=permanent_index,
            mana_color=mana_color,
            old_color=old_color,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_stack_index=target_stack_index,
            ability_index=ability_index,
            x_value=x_value,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_index=cost_hand_index,
            source_seat=source_seat,
            source_permanent_index=source_permanent_index,
            source_stack_index=source_stack_index,
            source_controller_index=source_controller_index,
        )
        if not queued.supported:
            return queued
        if queued.details == "queued":
            self._settle()
            self.clear_priority_window()
            return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")
        return queued
    def activate_prevent_one_emblem(self, controller_index: int, emblem_index: int = 0) -> SimulationResult:
        """Activate a Guardian Angel emblem: pay {1} to prevent the next 1 damage to
        the emblem's stored target (the original spell's "that permanent or player").
        Repeatable while the emblem exists."""
        from ...handlers.prevention import apply_prevention_shield

        label = "Prevention Emblem"
        controller = self.players[controller_index]
        emblems = controller.prevent_one_damage_emblems
        if not (0 <= emblem_index < len(emblems)):
            return SimulationResult(label, False, "unsupported", "no prevention emblem available")
        entry = emblems[emblem_index]

        target_idx = entry.get("target_player_index")
        if target_idx is None or not (0 <= target_idx < len(self.players)):
            return SimulationResult(label, False, "unsupported", "emblem target is no longer valid")
        target_player = self.players[target_idx]
        target_perm_idx = entry.get("target_permanent_index")
        # "That permanent" — if the original creature target has left play, the
        # ability has no legal target and does nothing.
        if isinstance(target_perm_idx, int):
            if not (0 <= target_perm_idx < len(target_player.battlefield)
                    and target_player.battlefield[target_perm_idx].is_creature):
                return SimulationResult(label, False, "unsupported", "emblem target is no longer in play")

        if self.enforce_mana_costs:
            required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 1}
            # An emblem is not an artifact, so "only to activate abilities of
            # artifacts" mana cannot pay for one — a purpose with no source is
            # that answer rather than a missing argument.
            if not self._pay_mana_cost(
                controller, required, purpose=PaymentPurpose(ACTIVATE)
            ):
                return SimulationResult(label, False, "unsupported", "insufficient mana to activate emblem")

        apply_prevention_shield(self, target_player, target_perm_idx, 1)
        return SimulationResult(label, True, "activated_prevent_one", "resolved")
    def queue_permanent_ability(self, *args, **kwargs) -> SimulationResult:
        """Activate an ability — CR 602, start to finish.

        The same wrapper, for the same rule, as ``queue_from_hand``: CR 602.2b
        routes activation through CR 601.2b–i, so an ability's costs are paid
        inside one announcement and a trigger they fire waits for the end of it.
        Witch's Cauldron eats a creature to pay for itself, and Havoc Jester's
        ping belongs above the Cauldron's ability rather than under it. See
        ``deferring_triggers``.
        """
        with self.deferring_triggers():
            return self._activate_onto_stack(*args, **kwargs)

    def _activate_onto_stack(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        # "…replacing all instances of one color word with another" (Balduvian
        # Shaman). A text change names *two* words, and `mana_color` is only
        # ever the second — the key an any-colour mana ability and Alchor's
        # Tomb also use. The word being replaced arrives here, on the same key
        # the cast side already carries it on, so `mark_text_modified` reads
        # one pair whether a spell or an ability asked the question.
        old_color: str | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them
        # (the web layer resolves them off the wire). Several targets may sit
        # on different battlefields, which one `target_player_index` cannot
        # express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
        # Which permanent / which card in hand pays a non-mana cost. The payer
        # chooses (CR 601.2b), so the choice arrives with the action that pays
        # it rather than through the pending-choice queue: a cost is paid during
        # activation, and a queued prompt would put the ability on the stack
        # before its cost was collected. A seat that names neither gets the
        # deterministic pick below, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        source_seat: int | None = None,
        source_permanent_index: int | None = None,
        source_stack_index: int | None = None,
        source_controller_index: int | None = None,
    ) -> SimulationResult:
        controller = self.players[controller_index]
        # Ifh-Bíff Efreet: "Any player may activate this ability." The activator
        # (controller of the ability, payer of its cost) may differ from the
        # permanent's controller; source_controller_index names whose
        # battlefield holds the permanent.
        source_owner = (
            controller
            if source_controller_index is None
            else self.players[source_controller_index]
        )
        resolved = self._find_controlled_permanent(source_owner, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved
        # CR 602.1a: a permanent's abilities are its controller's to activate,
        # unless the card prints a permission that says otherwise. This is the
        # *reachability* half — may this seat touch this permanent at all —
        # asked of `engine/activation_permissions.py` rather than of two
        # substrings written out here, which is what it was. Which of the
        # permanent's abilities the seat may then activate is the per-ability
        # question below, read off that ability's own printed line.
        if source_owner is not controller and not card_widens_activation(
            permanent.effective_card
        ):
            details = f"{permanent.card.name}'s abilities can only be activated by its controller"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Loses all abilities" (Titania's Song) means the activated ones too.
        # Layer 6 removes keyword abilities, but an activated ability is read
        # from the compiled program rather than the ability channel, so removal
        # has to be enforced where activation is authorised. Without this the
        # card would be half-implemented: a Jayemdae Tome under Titania's Song
        # would lose nothing it visibly had and keep drawing cards.
        from ...global_statics import global_statics_applying_to

        if any(static.removes_abilities for static in global_statics_applying_to(permanent)):
            details = f"{permanent.card.name} has lost all abilities"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # CR 305.7, for the same reason and at the same place: a land whose
        # subtype an effect *set* to basic land types loses the abilities its
        # rules text generated. Layer 6 drops the keywords; an activated ability
        # is read off the compiled program, so it has to be refused here or the
        # rule is half-implemented — a Mishra's Factory under Blood Moon read as
        # a Mountain and still animated itself.
        #
        # It does not touch tapping for mana: that path is `tap_land_for_mana`,
        # which reads `effective_produced_mana` and already gives the land the
        # mana ability of its new type, which is 305.7's other half.
        from ...land_types import lost_abilities_to_type_change

        if lost_abilities_to_type_change(permanent):
            details = (
                f"{permanent.card.name} lost its abilities when its land type "
                "was set (CR 305.7)"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Through the seam rather than off the card directly: Conspicuous Snoop
        # has the activated abilities of whatever is on top of its controller's
        # library, and that is a grant no read of the permanent alone can see.
        program = compile_card_oracle(self.playable_card_of(permanent))

        # "Activate only if you've controlled this artifact continuously since
        # the beginning of your most recent turn" (Rocket Launcher). CR 302.6's
        # clause applied to an artifact, so it reuses the same marker rather
        # than inventing a second notion of "arrived too recently".
        for ability in program.activated_abilities:
            if ability.instruction is None:
                continue
            if not ability.instruction.payload.get("requires_control_since_turn_start"):
                continue
            if not self._controlled_since_turn_start(permanent):
                details = (
                    f"{permanent.card.name} has not been controlled continuously "
                    "since the beginning of your most recent turn"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

        # CR 601.2c (reached through 602.2b) chooses targets **before** CR 601.2h
        # pays the costs, and this ability's cost may remove a permanent — which
        # renumbers every battlefield slot after it. Stamping the identity now is
        # what keeps the two apart.
        #
        # Dwarven Weaponsmith is the card: "{T}, Sacrifice an artifact: Put a
        # +1/+1 counter on target creature." With the artifact sitting before the
        # target on its controller's battlefield, paying the cost slid the target
        # down a slot, and the index the caller chose then named something else —
        # the source itself, in the case that ships. A caller that already sends
        # ids (the whole web layer does, which is why no game ever showed this)
        # is left exactly as it was.
        if target_permanent_ids is None and isinstance(target_permanent_index, int):
            stable = self.permanent_at(target_player, target_permanent_index)
            if stable is not None:
                target_permanent_ids = [stable.permanent_id]

        # An explicitly chosen spell on the stack (e.g. Deathgrip: "{B}{B}: Counter
        # target green spell"). target_stack_index indexes self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]

        # "A source of your choice" (Jade Monolith): a chosen battlefield
        # permanent, or a spell on the stack (its card stands in for the source).
        chosen_source = None
        if source_seat is not None and source_permanent_index is not None:
            if 0 <= source_seat < len(self.players):
                source_bf = self.players[source_seat].battlefield
                if 0 <= source_permanent_index < len(source_bf):
                    chosen_source = source_bf[source_permanent_index]
        elif source_stack_index is not None and 0 <= source_stack_index < len(self.stack):
            chosen_source = self.stack[source_stack_index].card



        # Which of the card's abilities is being activated. An explicit
        # ability_index names one (Rock Hydra's {R} prevention vs its {R}{R}{R}
        # pump); otherwise the default is the first ability this permanent can
        # actually pay for *in its current state*, not simply the first printed.
        #
        # CR 107.5: "A permanent that's already tapped can't be tapped again to
        # pay the cost", so an ability costing {T} is simply not among the ones
        # a tapped permanent can begin to activate (CR 602.5). A card with both a {T}
        # ability and an untap ability — Basalt Monolith's "{T}: Add {C}{C}{C}"
        # plus "{3}: Untap this artifact" — therefore has exactly one payable
        # ability in each state, and choosing it needs no knowledge of which
        # card it is. This was `permanent.card.name == "Basalt Monolith"`, and
        # an identically-worded card under any other name tapped for mana once
        # and was then stuck tapped for good, its untap ability unreachable.
        usable = [
            item
            for item in program.activated_abilities
            if item.supported and item.instruction is not None
        ]
        if ability_index is not None:
            ability = usable[ability_index] if 0 <= ability_index < len(usable) else None
        else:
            # The fallback to the first usable ability keeps refusals specific:
            # a permanent whose only ability costs {T} still reports "already
            # tapped" from the cost check below, rather than the vaguer "no
            # implemented activated ability" a None here would produce.
            ability = next(
                (
                    item
                    for item in usable
                    if not (item.cost.requires_tap and permanent.tapped)
                ),
                None,
            ) or next(iter(usable), None)

        if ability is None or ability.instruction is None:
            # Zombie Master grants other Zombies '{B}: Regenerate this permanent.'
            # The granted ability still costs {B} to activate.
            if permanent.metadata.get("granted_regen_ability"):
                if self.enforce_mana_costs and not self._pay_mana_cost(
                    controller, self._parse_mana_cost("{B}", x_value=0),
                    purpose=PaymentPurpose(ACTIVATE, source=permanent),
                ):
                    details = f"insufficient mana to activate {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)
                permanent.regeneration_shield += 1
                self.log.append(f"{permanent.card.name} regenerates (ability granted by lord)")
                return SimulationResult(permanent.card.name, True, "activated_regenerate", "resolved")
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

        # CR 602.2b/601.2c, once, before any cost is paid: an ability that
        # targets is unactivatable with no legal target, and a named target
        # must be legal. Derived from the same valid_targets the web picker
        # gets (engine/legality.py), so the list offered and the list enforced
        # are one. This replaced a per-kind if-chain here — banding, the
        # counterspell, destroy-target, equip — that checked four instruction
        # kinds by hand and let every other object-targeted ability (Silent
        # Dart, Royal Assassin, Xenic Poltergeist, …) pay its cost with nothing
        # to target and then deal to the face or no-op.
        target_refusal = self.activation_target_refusal(
            controller_index, permanent, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_stack_item=target_stack_item,
        )
        if target_refusal is not None:
            self.log.append(target_refusal)
            return SimulationResult(permanent.card.name, False, "unsupported", target_refusal)

        # "Remove a <kind> counter from this creature" (Scavenging Ghoul; the
        # ability Life Matrix grants) - CR 602.1a: a counter removal is an
        # activation cost, so it is checked and charged before the ability goes
        # on the stack, and an ability whose source has none may not be
        # activated at all.
        #
        # This was a substring test for the words "remove a **corpse** counter
        # from this creature" beside a check that the ability regenerated. Both
        # halves were the first card that reached it: the counter's kind is
        # payload (CR 122.1's kinds are open), and what the ability *does* is
        # not the cost's business. An ability granted with any other counter's
        # word paid nothing and could be activated for ever.
        # **Counted here, charged with the other costs below.** This block used
        # to take the counters off at this point, which is *above* CR 602.5's
        # timing gate -- so Trade Caravan, activated outside an opponent's
        # upkeep, was refused with two currency counters already gone. CR 602.2b
        # reverses an activation that turns out to be illegal, and the rest of
        # this function is arranged that way already: every other cost checks
        # its payability here and pays further down.
        counters_removed_for_cost = 0
        if ability.cost.remove_counter:
            from ...named_counters import counters_on

            kind = ability.cost.remove_counter
            held = counters_on(permanent, kind)
            wanted = ability.cost.remove_counter_count
            if wanted == "any":
                # "Remove **any number of** charge counters from this artifact"
                # (the Mana Batteries). The payer announces how many as the
                # ability is activated (CR 601.2b), through the same channel
                # every other announced number travels on; a seat that announces
                # nothing removes every counter, which is deterministic and the
                # only answer that is never worse on a card whose effect scales
                # with the count. Zero is a legal payment — "any number"
                # includes none — so this half can never make the ability
                # unactivatable.
                counters_removed_for_cost = (
                    held if x_value is None else max(0, min(held, int(x_value)))
                )
            else:
                if held < int(wanted):
                    details = f"{permanent.card.name} has no {kind} counters to remove"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)
                counters_removed_for_cost = int(wanted)

        # Per-ability timing restrictions are scoped to the *selected* ability's
        # own clause, not the whole card. Rock Hydra's "Activate only during your
        # upkeep" sits on its {R}{R}{R} pump line only, so its {R} prevention
        # ability (ability_index 0) must stay usable at any time.
        ability_lower = (ability.source_line or permanent.effective_card.oracle_text).lower()

        # CR 606.3: a loyalty ability may be activated only during a main phase
        # of its controller's own turn with the stack empty — unless the
        # permanent itself widens the window ("You may activate loyalty
        # abilities of ~ on any player's turn any time you could cast an
        # instant", Teferi, Master of Time). The once-per-permanent-per-turn
        # half of the rule is not part of that static and is never widened.
        # CR 606.6: a negative cost needs at least that many counters on it.
        loyalty_delta = 0
        if ability.cost.is_loyalty:
            any_time = LOYALTY_ANY_TIME_STATIC in program.static_lines
            if not any_time and not (
                self.active_player_index == controller_index
                and self.current_turn_phase in ("precombat_main", "postcombat_main")
                and not self.stack
            ):
                details = (
                    f"{permanent.card.name}'s loyalty abilities can only be activated "
                    "during a main phase of your turn with the stack empty (CR 606.3)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.metadata.get("loyalty_ability_used_turn") == self.turn:
                details = (
                    f"a loyalty ability of {permanent.card.name} has already been "
                    "activated this turn (CR 606.3)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            loyalty_delta = (
                ability.cost.loyalty_x_sign * int(x_value or 0)
                if ability.cost.loyalty_x_sign is not None
                else ability.cost.loyalty
            )
            if loyalty_delta < 0 and int(permanent.metadata.get("loyalty_counters", 0)) < -loyalty_delta:
                details = (
                    f"{permanent.card.name} does not have enough loyalty counters "
                    "to pay that cost (CR 606.6)"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Every printed "Activate only …" clause on *this* ability line
        # (engine/activation_restrictions.py, CR 602.5). One table, read here and
        # by the support gate, replacing a hand-written if-chain whose branches
        # were substring tests: everything the chain did not list was silently
        # unenforced, which is how Caged Zombie drained two life on an empty
        # graveyard while reporting supported.
        denial = activation_denial(self, controller_index, permanent, ability.source_line or "")
        if denial is not None:
            details = f"{permanent.card.name}: {denial}"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Every printed "…may activate this ability" permission on *this* line
        # (engine/activation_permissions.py, CR 602.1a). Asked per ability for
        # the reason the restriction above is: a permanent with two abilities
        # prints the clause on one of them, and the card-wide reachability test
        # further up deliberately cannot tell them apart. This is also the
        # direction the old substring pair never had — "Only your opponents may
        # activate this ability" (Clergy of the Holy Nimbus) *denies* the
        # controller, and a permission that only ever widened would have left
        # the ability working for the one player the card forbids.
        permission = activation_permission_denial(
            self, controller_index, permanent, ability.source_line or ""
        )
        if permission is not None:
            self.log.append(permission)
            return SimulationResult(permanent.card.name, False, "unsupported", permission)

        # "…and its activated abilities can't be activated unless they're mana
        # abilities." (Faith's Fetters.) CR 605.1a decides which abilities the
        # exception leaves open, asked through the one predicate rather than
        # re-read here — a second reading would shut off an ability the rules
        # leave open, which for a land is the difference between a shut-down
        # permanent and a player locked out of casting anything.
        if aura_restriction_active(permanent, "activated_abilities_shut_off") and not is_mana_ability(ability):
            details = (
                f"{permanent.card.name}'s activated abilities can't be activated"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Only this creatures owner may activate this ability." (Personal
        # Incarnation.) The owner — not whoever controls it — is the only legal
        # activator, so a thief who stole it with Control Magic can't use it.
        if (
            "only this creatures owner may activate this ability" in ability_lower
            and self.owner_index_of(permanent) != controller_index
        ):
            details = f"only {permanent.card.name}'s owner may activate this ability"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "X can't be 0." (Aladdin's Lamp.)
        if "x can't be 0" in ability_lower and not x_value:
            details = f"{permanent.card.name}: X can't be 0"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # The timing half of "Activate only during your turn and only once each
        # turn" is in the restriction table above; the *count* half is
        # per-permanent state rather than a property of the game, so the tally
        # stays here with the state it reads. **How limited a line is, is the
        # table's answer**, not a substring test beside it: the bare clause
        # (Dream Coat), the tails, and Vampire Bats' "no more than twice" all
        # come back from one reader, and a reader here spelling the words itself
        # is the second representation that lets a refusal and a tally disagree
        # about the same sentence.
        # **Whether** the line is capped is a fact about the sentence;
        # **how much** it is capped by can be a fact about the board (Withering
        # Wisps counts snow Swamps), so the tally below asks the first question
        # and the refusal here asks the second. One text-only reader answering
        # both would have to call a counted cap "no cap", which is the value
        # that stops the tally.
        activation_caps = printed_activation_caps(ability_lower)
        if at_activation_limit(self, controller_index, permanent, ability_lower):
            details = (
                f"{permanent.card.name}'s ability can only be activated "
                f"{activations_allowed_each_turn(ability_lower, self, controller_index, permanent)}"
                f" time(s) each turn"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Northern Paladin: "{W}{W}, {T}: Destroy target black permanent." /
        # Dwarven Demolition Team / Tunnel: "Destroy target Wall." / King
        # Suleiman: "Destroy target Djinn or Efreet." The chosen target must
        # satisfy the ability's color/type/subtype filter (601.2c) — an
        # illegal target makes the ability impossible to activate, so it's
        # rejected before any cost is paid rather than silently fizzling.
        # Jandor's Ring: "Discard the last card you drew this turn" is an
        # additional cost — unpayable (so the ability can't be activated) if no
        # card drawn this turn is still in hand. Checked before any cost is paid;
        # the discard itself happens below, once every cost has been cleared.
        discard_cost_card = None
        if ability.cost.discard_last_drawn:
            discard_cost_card = controller.last_card_drawn_this_turn()
            if discard_cost_card is None:
                details = (
                    f"{permanent.card.name}: no card drawn this turn remains in hand to discard"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Discard a card" (Seasoned Hallowblade). Unpayable with too few cards,
        # and CR 602.5c makes an unpayable cost an *unactivatable* ability
        # rather than a free one. Resolved to card objects, not indices: the
        # indices shift as each card leaves the hand.
        discard_cost_cards: list = []
        if ability.cost.discard_cards:
            hand = controller.hand
            # "Discard a **land card or Shrine card**" (Sanctum of Shattered
            # Heights): the payment is drawn from the cards the printed phrase
            # names, not from the hand. Matched through the same reader the
            # picker in `engine/legality.py` offers from, so what is offered and
            # what is accepted cannot disagree — and an empty filter list means
            # the unrestricted "Discard a card", where the whole hand pays.
            payable = [
                card for card in hand
                if card_matches_any(card, ability.cost.discard_filters)
            ]
            if len(payable) < ability.cost.discard_cards:
                # Naming the phrase when there is one. "Not enough cards in
                # hand" is the truth for a bare "Discard a card" and a plain
                # falsehood for Niambi's, where the hand may be full of cards
                # that simply are not legendary — a message that sends a player
                # looking for the wrong problem.
                shortfall = (
                    "no card in hand answers this cost"
                    if ability.cost.discard_filters
                    else "not enough cards in hand to discard"
                )
                details = f"{permanent.card.name}: {shortfall}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            # An index that names no card is an error, not a request for a
            # different one. It used to become a bare `0`, so a stale click
            # discarded the first card in hand — the same silent repointing the
            # cast side did, and the reason both now refuse instead. Naming
            # nothing at all is still the deterministic default.
            #
            # A named card that does not answer the phrase is the same error, not
            # a cheaper cost: it is refused rather than quietly slid onto a legal
            # one, so a stale click cannot discard the land the player meant to
            # keep.
            # "Discard a card **at random**" (Coral Helm). The payer names
            # nothing — a cost the payer picks is a strictly better cost than
            # one chance picks, which is the whole difference between this card
            # and one that says "discard a card". Any index a caller sent is
            # ignored rather than honoured, because honouring it would hand the
            # choice back.
            #
            # Through the module RNG, like every other randomiser here, so a
            # seeded run reproduces the discard (the determinism invariant).
            if ability.cost.discard_at_random:
                discard_cost_cards = random.sample(
                    payable, min(ability.cost.discard_cards, len(payable))
                )
                cost_hand_index = None
            elif cost_hand_index is not None and (
                not 0 <= cost_hand_index < len(hand)
                or hand[cost_hand_index] not in payable
            ):
                details = (
                    f"{permanent.card.name}: no card at hand position "
                    f"{cost_hand_index} to discard for its cost"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if not ability.cost.discard_at_random:
                named = hand[cost_hand_index] if isinstance(cost_hand_index, int) else payable[0]
                discard_cost_cards = [named]
                for card in payable:
                    if len(discard_cost_cards) >= ability.cost.discard_cards:
                        break
                    if card is not named:
                        discard_cost_cards.append(card)

        # "Exile the top card of your library" (Royal Herbalist), "…the top four
        # cards…" (Seasoned Tactician). CR 118.3: a player cannot pay a cost
        # without the resources to pay it **fully**, so a library holding fewer
        # cards than the printed count pays nothing at all and CR 602.5c makes
        # the ability unactivatable rather than free. Checked here with the
        # other costs and paid below with them, so a refusal further down does
        # not leave a library already shorter.
        if ability.cost.exile_top_of_library > len(controller.library):
            details = (
                f"{permanent.card.name}: {controller.name} has "
                f"{len(controller.library)} card(s) left and its cost exiles "
                f"{ability.cost.exile_top_of_library}"
            )
            self.log.append(details)
            return SimulationResult(
                permanent.card.name, False, "unsupported", details
            )

        # "Discard your hand" (Subira). Never unpayable — discarding nothing is
        # discarding your hand — so there is no check beside the others above,
        # only the payment below.
        # "Pay 3 life" (Tavern Swindler). CR 119.4: a player may pay life only
        # if their life total is at least the amount — so exactly 3 life pays a
        # 3-life cost and 2 does not, and paying down to 0 is legal. CR 602.5c
        # then makes an unpayable cost an *unactivatable* ability rather than a
        # free one, which is why this refuses here instead of clamping at the
        # payment below. Checked before anything is spent, like every other cost.
        if ability.cost.pay_life and controller.life < ability.cost.pay_life:
            details = (
                f"{permanent.card.name}: {controller.name} cannot pay "
                f"{ability.cost.pay_life} life with {controller.life} remaining"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Sacrifice another creature" (Hobblefiend) / "Sacrifice a creature with
        # defender" (Portcullis Vine). The victim is chosen by identity and never
        # by index — an index held across the removals below names whichever
        # permanent slid into the slot — and "another" excludes the source
        # itself, so a lone Hobblefiend has no legal payment and cannot activate
        # at all. That exclusion is `exclude_self` inside the filter, which is
        # why the source is handed to the matcher rather than tested here.
        sacrifice_cost_permanent = None
        sacrifice_cost_set: list = []
        if (
            ability.cost.sacrifice_count == "any"
            and ability.cost.sacrifice_filter is not None
        ):
            # "Sacrifice this artifact **and any number of creatures you
            # control**" (Sword of the Ages). The payer names the set as the
            # ability is activated (CR 601.2b) — through `cost_permanent_ids`,
            # the same channel every other chosen cost permanent arrives on —
            # and naming none is a legal payment, because zero is a number. So
            # there is no default pick here: unlike a "sacrifice a creature"
            # cost, which must eat something or the ability is unactivatable,
            # this one has a legal answer that costs nothing, and choosing
            # creatures for a seat that named none would sacrifice a board to
            # pay a cost of zero.
            described = ability.cost.sacrifice_filter
            for permanent_id in cost_permanent_ids or []:
                found = self.permanent_by_id(permanent_id)
                if (
                    found is not None
                    and found is not permanent
                    and self.controls(controller_index, found)
                    and subject_matches(
                        self, found, described,
                        observer=controller_index, source=permanent,
                    )
                    and not any(found is already for already in sacrifice_cost_set)
                ):
                    sacrifice_cost_set.append(found)
        elif ability.cost.sacrifice_filter is not None and ability.instruction is not None and (
            ability.instruction.kind not in COST_PERFORMING_KINDS
        ):
            described = ability.cost.sacrifice_filter
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(
                    self, perm, described,
                    observer=controller_index, source=permanent,
                )
            ]
            if not candidates:
                details = (
                    f"{permanent.card.name}: no "
                    f"{filter_head_noun(described)} available to sacrifice"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            # "Sacrifice **two** Goblins" (Goblin Warrens). A printed count
            # greater than one, which is a different payability question from
            # every other sacrifice cost here: two of them must exist, and one
            # Goblin is no more a payment than none (CR 601.2h). Checked before
            # anything is spent, like the singular beside it.
            wanted = ability.cost.sacrifice_count
            wanted = wanted if isinstance(wanted, int) else 1
            if len(candidates) < wanted:
                details = (
                    f"{permanent.card.name}: not enough "
                    f"{filter_head_noun(described)}s to sacrifice for its cost"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            # Through the seam, which bounds-checks and turns an index arriving
            # from the wire into a permanent exactly once.
            named_permanent = (
                self.permanent_at(controller, cost_permanent_index)
                if isinstance(cost_permanent_index, int)
                else None
            )
            if any(perm is named_permanent for perm in candidates) and not any(
                perm is named_permanent for perm in named
            ):
                named = [named_permanent, *named]
            if wanted > 1:
                # The payer's own picks first, then the deterministic default
                # for the rest — the same arrangement the tap cost below makes,
                # so a seat that names none is never blocked and a seat that
                # names some has them honoured.
                chosen_victims: list = []
                for perm in [*named, *candidates]:
                    if len(chosen_victims) >= wanted:
                        break
                    if not any(perm is already for already in chosen_victims):
                        chosen_victims.append(perm)
                sacrifice_cost_set = chosen_victims
            else:
                # `in` compares Permanents by value and would match a look-alike, so
                # membership is tested by identity.
                sacrifice_cost_permanent = (
                    named_permanent
                    if any(perm is named_permanent for perm in candidates)
                    # An id names the victim as well as an index does — the wire
                    # carries both — so a seat that named one is honoured rather
                    # than given the deterministic default. The index channel
                    # keeps precedence, because that is the one the sacrifice
                    # picker has always answered on.
                    else named[0] if named
                    # A permanent whose death loses the game is kept for last, then
                    # the smallest — one rule, shared with the cast-side additional
                    # cost and the forced-sacrifice default (`default_sacrifice_pick`).
                    else self.default_sacrifice_pick(candidates)
                )

        # "Tap two untapped Spirits you control" (Shacklegeist). Chosen by the
        # payer through `cost_permanent_ids`, and defaulted deterministically for
        # a seat that names none — the same arrangement the sacrifice cost above
        # makes, and for the same reason: a cost is paid during activation, so a
        # queued prompt would put the ability on the stack before it was
        # collected.
        tap_cost_permanents: list = []
        if ability.cost.tap_count:
            described = ability.cost.tap_filter or {}
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                # Untapped by construction — a tap cost can only be paid with a
                # permanent that is not already tapped — and the source is
                # eligible only if the printed phrase names it, which "another"
                # would have excluded.
                if not perm.tapped and subject_matches(self, perm, described)
            ]
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            # Deduplicated by identity: two references to one permanent do not
            # pay a two-permanent cost.
            chosen: list = []
            for perm in named:
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            for perm in candidates:
                if len(chosen) >= ability.cost.tap_count:
                    break
                if not any(perm is already for already in chosen):
                    chosen.append(perm)
            if len(chosen) < ability.cost.tap_count:
                details = (
                    f"{permanent.card.name}: not enough untapped "
                    f"{filter_head_noun(described)}s to tap for its cost"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            tap_cost_permanents = chosen[:ability.cost.tap_count]

        # "{B}, **Put a -1/-1 counter on a creature you control**: …"
        # (Wandering Mage). The one counter-placing cost that can be *unpayable*
        # — CR 601.2h, and a payer with no creature has nowhere to put it — so
        # unlike Mazemind Tome's marker on its own source this is collected here
        # with the other chosen costs and refuses the activation with nothing
        # paid. Picked through `cost_permanent_ids`, the same channel the
        # sacrifice and tap costs above arrive on, and defaulted with
        # `default_sacrifice_pick` for a seat that names none: a -1/-1 counter
        # is a shrinking, so "the one you would give up" is the same ranking.
        counter_cost_permanent = None
        if ability.cost.put_counter_filter is not None:
            described = ability.cost.put_counter_filter
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(
                    self, perm, described,
                    observer=controller_index, source=permanent,
                )
            ]
            if not candidates:
                details = (
                    f"{permanent.card.name}: no "
                    f"{filter_head_noun(described)} to put a "
                    f"{ability.cost.put_counter} counter on"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            named = [
                found
                for found in (
                    self.permanent_by_id(pid) for pid in (cost_permanent_ids or [])
                )
                if found is not None and any(c is found for c in candidates)
            ]
            counter_cost_permanent = (
                named[0] if named else self.default_sacrifice_pick(candidates)
            )

        # "**Tap enchanted land**: …" (Earthlore). The host, collected beside
        # the picked tap cost above and paid with it below — one payment moment
        # (CR 601.2h). Nothing is picked: the attachment record is the whole
        # answer, so the only way this can fail is the Aura having no host or a
        # host already tapped, and both refuse the activation with nothing paid
        # (CR 602.2b) rather than tapping the Aura for nothing.
        if ability.cost.tap_attached:
            host = permanent.metadata.get("attached_to")
            if host is None or not self.is_on_battlefield(host) or host.tapped:
                details = (
                    f"{permanent.card.name}: the permanent it is attached to "
                    "cannot be tapped to pay its cost"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
            tap_cost_permanents = [*tap_cost_permanents, host]

        # "Exile a creature you control" (City of Shadows) / "Exile a creature
        # card from your graveyard" (Necropolis) — a *chosen* object rather than
        # the source. **A cost is not a target** (CR 601.2b, idiom 10), so
        # nothing here consults shroud or protection; what it consults is the
        # printed noun phrase, through the same reader the picker uses.
        #
        # Charged with the rest of the costs and **before the tap**, so an
        # ability with nothing to pay it is not activated at all (CR 602.2b)
        # rather than refused with the source already tapped for nothing. It
        # also runs ahead of the source's own exile further down, so a card
        # printing both eats the chosen object while the source is still there.
        exiled_for_cost = None
        exiled_set_for_cost: list = []
        if ability.cost.exile_filter is not None:
            exiled_set_for_cost = self._pay_exile_cost(
                ability.cost, controller, controller_index, permanent,
                cost_permanent_index,
            )
            if not exiled_set_for_cost:
                details = (
                    f"{permanent.card.name}: nothing available to exile as a cost"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
            # The single-object channel every reader of an exile cost already
            # asks (Necropolis' "the exiled card's mana value"), kept as the
            # first of them, so a counted cost adds a record rather than moving
            # one.
            exiled_for_cost = exiled_set_for_cost[0]

        # The counter-removal cost, charged here rather than where it was
        # counted: every gate between the two can still refuse the activation,
        # and a refusal after the counters came off is a cost paid for nothing
        # (CR 602.2b). Through the one removal seam, so a cost that takes the
        # last counter off is the same event as an effect that does.
        if counters_removed_for_cost:
            from ...named_counters import remove_counters

            remove_counters(
                permanent, ability.cost.remove_counter, counters_removed_for_cost
            )

        required_cost = dict(ability.cost.mana)
        # "**Pay enchanted creature's mana cost**: …" (Merseine.) The symbols
        # are the *host's* and cannot be known when the card compiles, so the
        # cost dict is built here, at the one moment there is a host to read
        # (CR 202.1 — a permanent's mana cost is what is printed in its upper
        # right corner, whatever the copy and text-change layers have made of
        # the object).
        #
        # An Aura with no host, or a host whose printed cost carries a symbol
        # this engine cannot spend, refuses the activation with nothing paid
        # (CR 602.2b). Never a fallback to the empty dict beside it: an
        # unreadable cost read as zero is an ability activated for free, which
        # is the failure every cost reader in this engine is written against.
        if ability.cost.mana_from_attached:
            host = attached_host(self, permanent, last_known=False)
            printed = None if host is None else (
                getattr(host.card, "mana_cost", "") or ""
            )
            symbols = None if host is None else mana_cost_from_symbols(printed)
            if host is None or (symbols is None and printed.strip()):
                details = (
                    f"{permanent.card.name}: the mana cost it charges is the "
                    "attached permanent's, and there is none to read"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
            for symbol, count in (symbols or {}).items():
                required_cost[symbol] = required_cost.get(symbol, 0) + count
        requires_tap = ability.cost.requires_tap
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        #
        # **Per printed symbol, and only in the cost clause.** Voodoo Doll's
        # cost is "{X}{X}" — two of them, so it charges 2X — and a card whose
        # *effect* mentions X ("deals X damage") is not charging a second one.
        # A single substring test read both as one X, which is half the cost on
        # the one card in the pool that prints the double.
        x_symbols = (ability.source_line or "").lower().split(":", 1)[0].count("{x}")
        # "X is the number of pin counters on this artifact." (Voodoo Doll.)
        # The card *defines* X, so the activator does not announce it
        # (CR 601.2b) — and the definition is read from the same table the
        # grammar consumed the sentence through, because an X consumed by one
        # reader and unknown to the other is a cost nobody charges.
        # The chosen spell is handed over because a definition may read it:
        # "X is twice the mana value of **that spell**" (Reflecting Mirror) is
        # priced off the object the ability targets, not off the board.
        defined_x = cost_x_value(
            self, permanent, ability.source_line or "", target=target_stack_item
        )
        if defined_x is not None:
            x_value = defined_x
        elif cost_x_is_defined(ability.source_line or ""):
            # The card defines X and this activation cannot compute it — no
            # target was named, most often. **Not zero**: an {X} nobody charges
            # is a free ability, which is exactly the failure
            # ``engine/cost_x_definitions.py`` exists to prevent, so the
            # activation is refused with nothing paid (CR 601.2b via 602.2b).
            details = (
                f"{permanent.card.name}: the value of X is defined by the card "
                "and nothing here determines it"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)
        if x_value and x_symbols:
            required_cost["generic"] = (
                required_cost.get("generic", 0) + int(x_value) * x_symbols
            )
        # "Activated abilities cost an additional "Sacrifice a Swamp" to
        # activate for each black mana symbol in their activation costs."
        # (Drought.) The cast path's twin, asked of the *printed* activation
        # cost — CR 601.2f determines an additional cost from the cost as
        # printed, before any of the increases and reductions below touch the
        # generic part. Refused with nothing paid when it cannot be met, which
        # is CR 602.2b routing through CR 601.2h.
        sacrifice_demands = sacrifice_taxes(
            self, controller_index, ability.cost.mana, "activate"
        )
        sacrifice_tax_victims = self._sacrifice_tax_victims(
            controller_index, sacrifice_demands
        )
        if isinstance(sacrifice_tax_victims, str):
            details = (
                f"{permanent.card.name}: {sacrifice_tax_victims} (CR 601.2h)"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)
        # Ability cost taxes (Gloom: "Activated abilities of white enchantments
        # cost {3} more to activate"; the white-spell cast tax is applied
        # separately in cast_from_hand).
        extra_ability_tax, taxing_names = ability_cost_tax(self, controller_index, permanent)
        if extra_ability_tax:
            required_cost["generic"] = required_cost.get("generic", 0) + extra_ability_tax
            self.log.append(f"{permanent.card.name}'s ability is taxed by {', '.join(taxing_names)}")
        # "This ability costs {1} less to activate for each Shrine you control."
        # (Sanctum of Tranquil Light.) After the tax, because CR 601.2f applies
        # increases before reductions, and clamped at zero because a cost cannot
        # go below {0} — the same clamp `reduce_cost` makes for a spell.
        discount = ability_self_reduction_amount(self, controller_index, permanent)
        if discount:
            before = required_cost.get("generic", 0)
            required_cost["generic"] = max(0, before - discount)
            self.log.append(
                f"{permanent.card.name}'s ability costs "
                f"{{{before - required_cost['generic']}}} less to activate"
            )
        # "Enchanted artifact's activated abilities cost {2} less to activate.
        # **This effect can't reduce the mana in that cost to less than one
        # mana.**" (Power Artifact.) The reduction is on the *Aura*, not on the
        # permanent whose ability it is, so it is read off what is attached
        # rather than off this card's own text.
        #
        # The floor is over the *whole* cost, coloured pips included — "the
        # mana in that cost", not the generic part of it — which is why it is
        # applied after the subtraction rather than as a clamp inside it. A {2}
        # ability reduced by {2} pays {1}, not nothing; a {B} ability is
        # already at the floor and pays {B}.
        aura_discount, floor = attached_ability_cost_reduction(permanent)
        if aura_discount:
            before_total = sum(required_cost.values())
            generic = required_cost.get("generic", 0)
            coloured = before_total - generic
            reduced_generic = max(0, generic - aura_discount)
            if reduced_generic + coloured < floor:
                reduced_generic = max(0, floor - coloured)
            required_cost["generic"] = reduced_generic
            if before_total != reduced_generic + coloured:
                self.log.append(
                    f"{permanent.card.name}'s ability costs "
                    f"{{{before_total - reduced_generic - coloured}}} less to activate"
                )
        # "Note the type of mana spent to pay this activation cost." (Jeweled
        # Amulet, Ice Cauldron.) CR 107.4b's symbols, measured as the difference
        # the payment made to the pool rather than predicted from the cost: a
        # generic pip says how *much* is owed and never which symbol pays it,
        # and the payer's own choice — and any restricted bucket it drew on — is
        # only visible afterwards. Empty when nothing was charged, which is a
        # note of nothing and not an absent note.
        pool_before = dict(controller.mana_pool)
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(
                controller, required_cost,
                purpose=PaymentPurpose(ACTIVATE, source=permanent),
            ):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
        mana_spent_for_cost = {
            symbol: spent
            for symbol in ("W", "U", "B", "R", "G", "C")
            if (spent := pool_before.get(symbol, 0)
                - controller.mana_pool.get(symbol, 0)) > 0
        }

        if requires_tap:
            if self._is_summoning_sick(permanent):
                details = f"{permanent.card.name} has summoning sickness"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            if permanent.tapped:
                details = f"{permanent.card.name} is already tapped"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            self.become_tapped(permanent)
            # The {T} symbol is a permanent tapped to pay for its *own*
            # ability, which is what the phrase says too — recorded beside the
            # spelled-out cost rather than only there, so the record answers the
            # question the words ask rather than the subset one card needs.
            record_tapped_to_pay(permanent, permanent)

        # The spelled-out tap cost, collected above and paid here — beside the
        # {T} symbol, because both are the same payment and CR 601.2h pays every
        # cost at one moment.
        for tapped_for_cost in tap_cost_permanents:
            self.become_tapped(tapped_for_cost)
            # "…destroy all Merfolk **tapped this turn to pay for its
            # abilities**" (Vodalian War Machine). Nothing on the board can be
            # asked how a permanent came to be tapped, so the answer is written
            # down here, where the cost is paid — the one place an activation
            # cost taps anything other than the source (engine/cost_tap_records.py).
            record_tapped_to_pay(permanent, tapped_for_cost)
        if tap_cost_permanents:
            self.log.append(
                f"{permanent.card.name}: tapped "
                + ", ".join(p.card.name for p in tap_cost_permanents)
                + " to pay its cost"
            )

        # The activation half of "…becomes tapped **or** a player activates an
        # artifact's ability without {T} in its activation cost" (Haunting
        # Wind, Powerleech). "Without {T} in its activation cost" is exactly
        # `requires_tap` being false — an ability that *does* tap has already
        # announced the same condition through `become_tapped` above, so
        # emitting here as well would fire it twice for one activation.
        #
        # Here rather than at the legality gate, which returns early: every
        # guard and cost has passed at this point, so the trigger sees only
        # activations the rules allowed. That is the same placement, and the
        # same reason, as the loyalty event below.
        if not requires_tap:
            emit(
                self, "permanent_tapped_or_ability_activated",
                subject=permanent, seat=controller_index,
                # The other announcement of this condition stamps the same key
                # (``become_tapped``), because "that artifact's controller"
                # (Haunting Wind) reads the subject's seat whichever half of the
                # printed ability fired. It is the *artifact's* controller, not
                # the activating seat above — those differ whenever an ability
                # is activated on a permanent someone else controls.
                event_subject_controller=self.controller_index_of(permanent),
            )

        # All guards/costs passed — tally an activation of a capped ability,
        # and of one whose own effect reads the tally ("If this ability has been
        # activated four or more times this turn, …", Farrelite Priest). Two
        # questions about one ledger: the first is asked of the printed clause,
        # because a cap is a refusal and is enforced before anything is paid;
        # the second is asked of the compiled program, because that sentence is
        # an effect the grammar has already read and a second reader of it would
        # be free to disagree.
        if activation_caps or reads_activation_tally(ability.instruction):
            mark_activated_this_turn(self, permanent)
        # The same stamp for the cap with no turn in it ("Activate only once",
        # Touch of Vitae's granted ability). Beside the per-turn one and in the
        # same position, because both are budgets spent by an activation the
        # rules allowed — and asked of the table rather than of the words here,
        # so the refusal and the stamp read one sentence the same way.
        if prints_once_only_restriction(ability_lower):
            mark_once_only_activation(permanent, ability_lower)

        # CR 606.4: a loyalty symbol is a cost to put on or remove that many
        # loyalty counters, paid as the ability is activated — so the walker's
        # loyalty has already moved while the ability is on the stack, and a
        # minus ability that empties it kills the walker before resolution
        # (704.5i). The sufficiency of a removal was checked above (606.6).
        if ability.cost.is_loyalty:
            loyalty_now = int(permanent.metadata.get("loyalty_counters", 0))
            permanent.metadata["loyalty_counters"] = loyalty_now + loyalty_delta
            permanent.metadata["loyalty_ability_used_turn"] = self.turn
            self.log.append(
                f"{controller.name} activated {permanent.card.name} "
                f"({loyalty_delta:+d} loyalty, now {loyalty_now + loyalty_delta})"
            )
            # "Whenever you activate a loyalty ability of …" (Keral Keep
            # Disciples). CR 606.4's payment *is* the activation, so this is the
            # event — and it is announced here rather than at the legality gate
            # above, which returns early: announcing there would fire the trigger
            # on activations the rules refused. The walker is still on the
            # battlefield at this point, which is what lets a minus ability that
            # bins it (CR 704.5i) still be something the trigger saw.
            # `queue_permanent_ability` holds the batch until the ability is on
            # the stack, so CR 603.3 puts this above it.
            emit(
                self, "you_activate_loyalty_ability",
                subject=permanent, seat=controller_index,
            )

        # Pay the discard additional cost. Costs are paid on activation, before
        # the ability goes on the stack, so the discarded card is the one drawn
        # before this activation rather than the card it draws.
        if discard_cost_card is not None:
            self.take_card_from_hand(controller, discard_cost_card)
            self._discard_card(controller, discard_cost_card)
            self.log.append(
                f"{controller.name} discarded {discard_cost_card.name} "
                f"(the last card they drew this turn) to activate {permanent.card.name}"
            )

        # Pay the chosen discard. Same ordering rule as the Ring's above: the
        # cost is collected before the ability is on the stack, so an ability
        # that draws cannot discard what it drew.
        for cost_card in discard_cost_cards:
            self.take_card_from_hand(controller, cost_card)
            self._discard_card(controller, cost_card)
            self.log.append(
                f"{controller.name} discarded {cost_card.name} "
                f"to activate {permanent.card.name}"
            )

        # "Put a page counter on this artifact" (Mazemind Tome). A cost that
        # *adds* rather than spends, so there was nothing to check above — and
        # paid here with the rest, before the ability is on the stack, because
        # CR 602.2b puts every cost at the same moment.
        if ability.cost.put_counter:
            from ...named_counters import add_counters

            # The chosen permanent when the card named one (Wandering Mage),
            # and the source otherwise (Mazemind Tome). One payment either way:
            # what differs is only which permanent it lands on, which is the
            # whole of `put_counter_filter`.
            from ...pt import pt_counter_deltas

            recipient = counter_cost_permanent or permanent
            if pt_counter_deltas(ability.cost.put_counter) is not None:
                # A P/T counter is CR 122.1a's, and every P/T write in this
                # engine goes through `engine/pt.py` — `add_counters` keeps the
                # *named* markers, which have no layer-7 meaning at all.
                self.place_pt_counters(recipient, ability.cost.put_counter)
                self.log.append(
                    f"{recipient.card.name} gets a "
                    f"{ability.cost.put_counter} counter "
                    f"({permanent.card.name}'s cost)"
                )
            else:
                total = add_counters(recipient, ability.cost.put_counter)
                self.log.append(
                    f"{recipient.card.name} has {total} "
                    f"{ability.cost.put_counter} counter(s)"
                )

        # "Discard your hand" (Subira). Every card, snapshotted before the loop
        # because `_discard_card` may itself put something into the hand (Library
        # of Leng's replacement offers the top of the library instead) — iterating
        # the live list would then skip or revisit a card.
        if ability.cost.discard_whole_hand:
            emptied = list(controller.hand)
            controller.hand = []
            for cost_card in emptied:
                self._discard_card(controller, cost_card)
            self.log.append(
                f"{controller.name} discarded their hand "
                f"({len(emptied)} card(s)) to activate {permanent.card.name}"
            )

        # Pay the life (CR 118.3b: the payment is subtracted from the life total,
        # which CR 119.4 also makes a loss of that much life). Sufficiency was
        # checked above. No `check_state_based_actions()` call: activation's
        # `_settle()` already sweeps, CR 704.3 puts the sweep at the next
        # priority rather than mid-cost, and every other cost payment here omits
        # it — measured, a card activated at exactly 3 life ends at life 0 and
        # lost either way.
        if ability.cost.pay_life:
            controller.life -= ability.cost.pay_life
            self.log.append(
                f"{controller.name} paid {ability.cost.pay_life} life to activate "
                f"{permanent.card.name}"
            )

        # Drought's imposed sacrifices, paid with the printed ones and at the
        # same moment (CR 602.2b). Picked before any mana left the pool, so a
        # board unchanged since pays exactly what the gate measured.
        self._pay_sacrifice_tax(
            sacrifice_tax_victims, f"to activate {permanent.card.name}"
        )
        # Pay the chosen sacrifice (CR 601.2h) — the creature is gone before the
        # ability goes on the stack, so Hobblefiend's counter lands on a board
        # that has already lost it.
        if sacrifice_cost_permanent is not None:
            name = sacrifice_cost_permanent.card.name
            self.sacrifice_permanent(sacrifice_cost_permanent)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
            )
        # …and the "any number of" set beside it (Sword of the Ages), paid the
        # same way and at the same moment. Each is sacrificed by identity — an
        # index held across the removals would name whichever permanent slid
        # into the slot — and the list survives on the resolution's choices,
        # because by the time the effect reads their total power they are cards
        # in a graveyard (CR 608.2h).
        for victim in sacrifice_cost_set:
            name = victim.card.name
            self.sacrifice_permanent(victim)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
            )

        # "Exile the top card of your library" — paid here with the rest
        # (CR 602.2b puts every cost at one moment), and the cards recorded on
        # the two channels every other exile cost already writes: the resolution
        # asks "the exiled card's mana value" (Phyrexian Devourer) and "if the
        # exiled card is a snow land" (Storm Elemental) when the cards are
        # already in exile, so the record is the only sound answer (CR 608.2h).
        #
        # ``exiled_for_cost`` is the single-object channel every existing reader
        # asks and takes the *first* card off the top, with the whole payment
        # beside it under ``exiled_set_for_cost`` — the same pairing the chosen
        # exile above keeps, rather than a third shape for one channel.
        if ability.cost.exile_top_of_library:
            from_library = [
                controller.library.pop(0)
                for _ in range(ability.cost.exile_top_of_library)
            ]
            controller.exile.extend(from_library)
            exiled_set_for_cost = [*exiled_set_for_cost, *from_library]
            if exiled_for_cost is None:
                exiled_for_cost = from_library[0]
            self.log.append(
                f"{controller.name} exiled "
                + ", ".join(card.name for card in from_library)
                + f" from the top of their library to activate {permanent.card.name}"
            )

        # Ring of Ma'rûf: "Exile this artifact" is part of the cost, so the
        # permanent leaves before the ability goes on the stack — and the ability
        # still resolves from exile (CR 603.6 / 608.2: the source leaving doesn't
        # counter it). The stack item keeps its source_permanent reference.
        if ability.cost.exile_self:
            self.remove_from_battlefield(permanent)
            controller.exile.append(permanent.card)
            self.log.append(
                f"{controller.name} exiled {permanent.card.name} to activate its ability"
            )

        # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman) is likewise
        # a cost, paid now — the ability still resolves from the graveyard.
        if ability.cost.sacrifice_self:
            self.sacrifice_permanent(permanent)
            self.log.append(
                f"{controller.name} sacrificed {permanent.card.name} to activate its ability"
            )

        instruction = ability.instruction
        if (
            instruction.kind in {"sacrifice_self_for_mana", "add_mana_from_text"}
            and (
                instruction.payload.get("any_color", False)
                # "Add {B} or {R}": the chosen alternative rides the same
                # ``color`` key the any-colour shape uses; the handler holds it
                # to the printed alternatives.
                or instruction.payload.get("pips_choice")
                # "Add three mana in any combination of {R} and/or {G}" (Orcish
                # Lumberjack). The same channel again: the seat names one of the
                # printed symbols and the handler makes every unit that symbol.
                # Left off, the ability would always produce the first printed
                # colour however the seat answered.
                or instruction.payload.get("combination")
            )
        ):
            selected_color = self._normalize_mana_color(mana_color)
            if selected_color is not None:
                instruction = OracleInstruction(
                    instruction.kind,
                    instruction.value,
                    {**instruction.payload, "color": selected_color},
                )


        mana_like_kinds = {
            "add_mana_from_text",
            "sacrifice_self_for_mana",
            "sacrifice_creature_for_mana",
        }
        if instruction.kind in mana_like_kinds:
            # A second `card.name == "Basalt Monolith"` branch stood here,
            # refusing add_mana_from_text while the permanent was untapped. It
            # was unreachable: the {T} cost above has already run
            # `become_tapped`, which sets `tapped` unconditionally (helpers.py),
            # so a mana ability that pays {T} is always tapped by this point.
            # Confirmed by making it raise and running the suite.
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=controller,
                    target=target_player,
                    card=permanent.card,
                    source_permanent=permanent,
                    # The same last-known-information channel the queued path
                    # below records. An ability that resolves without touching
                    # the stack still had its cost paid, and an effect reading
                    # back what the cost ate must not depend on which of the
                    # two paths it came down.
                    choices={
                        "exiled_for_cost": exiled_for_cost,
                        "exiled_set_for_cost": list(exiled_set_for_cost),
                        "counters_removed_for_cost": counters_removed_for_cost,
                        "mana_spent_for_cost": mana_spent_for_cost,
                        "sacrificed_set_for_cost": list(sacrifice_cost_set),
                        "sacrificed_for_cost": sacrifice_cost_permanent,
                        "discarded_for_cost": (
                            list(discard_cost_cards)
                            + (
                                [discard_cost_card]
                                if discard_cost_card is not None else []
                            )
                        ),
                    },
                ),
            )
            supported, details = state_machine.run(instruction)
            return SimulationResult(permanent.card.name, supported, ability.effect_kind, details)

        self._stack_push(
            # CR 602.2b: an activated ability's targets were chosen when it
            # was activated, so it does not choose again here.
            targets_already_chosen=True,
            item=StackItem(
                card=permanent.card,
                caster_index=controller_index,
                target_player_index=target_idx,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_ids,
                x_value=x_value,
                ability_instruction=instruction,
                ability_effect_kind=ability.effect_kind,
                source_permanent=permanent,
                ability_text=ability.source_line,
                target_stack_item=target_stack_item,
                # What the ability's own sacrifice cost ate (CR 601.2h), for
                # an effect that reads it back — "Add an amount of {B} equal
                # to **the sacrificed artifact's** mana value" (Priest of
                # Yawgmoth). The permanent is off the battlefield by now, so
                # this is the only place it survives (CR 608.2h last-known
                # information), exactly as the casting path already records an
                # additional cost's sacrifice.
                choices={
                    "chosen_source": chosen_source,
                    # …and what an **exile** cost ate, on the same channel and
                    # for the same reason: the object is out of the game
                    # before this item is on the stack, so nothing else holds
                    # it (CR 608.2h).
                    "exiled_for_cost": exiled_for_cost,
                    "exiled_set_for_cost": list(exiled_set_for_cost),
                    # How many counters the cost's "remove any number of …"
                    # actually took (the Mana Batteries), on the same
                    # last-known-information channel as the sacrifice beside
                    # it: the counters are off the permanent before the ability
                    # is on the stack, so the number survives nowhere else.
                    "counters_removed_for_cost": counters_removed_for_cost,
                    # …and CR 107.4b's symbols the mana cost actually consumed
                    # ("Note the type of mana spent to pay this activation
                    # cost", Jeweled Amulet), measured off the pool rather than
                    # predicted from the cost: a generic pip never says which
                    # symbol paid it.
                    "mana_spent_for_cost": mana_spent_for_cost,
                    # …and the permanents an "any number of" sacrifice cost ate
                    # (Sword of the Ages), whose total power the effect reads
                    # back once they are cards in a graveyard.
                    "sacrificed_set_for_cost": list(sacrifice_cost_set),
                    "sacrificed_for_cost": sacrifice_cost_permanent,
                    # …and what its discard cost ate, for the same reason and
                    # on the same channel: "If the discarded card was a land
                    # card" (Land's Edge) is asked once the card is already in
                    # a graveyard. Both spellings of the cost feed it — the
                    # chosen cards and Jandor's Ring's history-named one — so
                    # the record does not depend on which clause charged it.
                    "discarded_for_cost": (
                        list(discard_cost_cards)
                        + ([discard_cost_card] if discard_cost_card is not None else [])
                    ),
                    # "…the color of your choice" (Alchor's Tomb): the colour
                    # arrives with the activation, on the same `mana_color` key
                    # an any-colour mana ability uses, and rides to resolution
                    # on the stack item — which is where the cast side already
                    # carries a spell's chosen colour (`resolution.py` reads
                    # `item.choices["new_color"]` for the Lace cycle). One key,
                    # so a handler need not know whether a spell or an ability
                    # asked the question.
                    "new_color": self._normalize_mana_color(mana_color),
                    # The word a text change replaces, beside the one it
                    # replaces it with. See the parameter's note above.
                    "old_color": self._normalize_mana_color(old_color),
                },
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        # "Whenever a player activates an ability of enchanted creature with
        # {T} in its activation cost that isn't a mana ability" (Imprison).
        #
        # Announced **after** the push, and that is the whole of why it is a
        # separate site from the tap event above: CR 603.3 puts the trigger on
        # the stack over the ability it fired on, and a card that counters
        # "that ability" needs the object to be there to be found. The item is
        # carried on the event so the counter resolves the one activation that
        # fired it rather than whatever is on top by then.
        #
        # Everything reaching this line is an ability that uses the stack —
        # this engine resolves its mana abilities inline above, which is
        # CR 605.3a — so the printed "that isn't a mana ability" is satisfied
        # by the site rather than by a second reading of the ability.
        emit(
            self, "nonmana_ability_activated",
            subject=permanent, seat=controller_index,
            requires_tap=bool(requires_tap),
            activated_ability_item=self.stack[-1] if self.stack else None,
        )
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")
    def _pay_exile_cost(
        self, cost, controller, controller_index: int, permanent,
        cost_permanent_index,
    ) -> list:
        """Charge an "Exile <noun phrase>" activation cost, returning the cards
        it ate — or an **empty list** when nothing in the named zone could pay,
        which makes the ability unactivatable (CR 602.2b) with nothing else
        spent.

        Two zones, one rule. The battlefield enumerates the *permanents the
        payer controls* through the control seam and asks ``subject_matches``,
        the same predicate the picker offers by. A graveyard enumerates the
        payer's own pile and asks the card matcher instead, because a card in a
        zone has no computed characteristics at all (CR 613.1).

        **Idiom 11**: in a graveyard, two copies of a card are literally one
        object, so the chosen slot is resolved to its card *before* anything
        leaves the zone and removed by index — a scan by value takes whichever
        copy comes first.

        The named choice is honoured where it is legal and otherwise the first
        eligible object is taken, which is what every other cost payment in this
        file does for a non-interactive seat.
        """
        described = cost.exile_filter or {}
        wanted = max(1, int(getattr(cost, "exile_count", 1) or 1))
        if cost.exile_zone == "graveyard":
            # Whose pile. "your graveyard" (Necropolis) is one seat;
            # ``exile_zone_owner`` of None is "a graveyard" — anybody's — and
            # then **one** of them has to hold the whole payment: "from a
            # single graveyard" (Night Soil) is a fact about the set, so the
            # piles are tried whole rather than pooled. Pooled, the cost would
            # be payable with one card from each of two graveyards, which is
            # strictly cheaper than the card prints.
            owner = getattr(cost, "exile_zone_owner", "you")
            piles = (
                [controller] if owner == "you"
                # The payer's own pile first, then the rest in seat order, so a
                # seat that names nothing is deterministic — the rule every
                # other default pick in this file follows.
                else [
                    controller,
                    *(seat for seat in self.players if seat is not controller),
                ]
            )
            for pile in piles:
                slots = [
                    index for index, card in enumerate(pile.graveyard)
                    if _card_matches_filter(card, described)
                ]
                if len(slots) < wanted:
                    continue
                named = (
                    [cost_permanent_index]
                    if isinstance(cost_permanent_index, int)
                    and cost_permanent_index in slots
                    else []
                )
                chosen_slots: list[int] = []
                for slot in [*named, *slots]:
                    if len(chosen_slots) >= wanted:
                        break
                    if slot not in chosen_slots:
                        chosen_slots.append(slot)
                # Resolved to *cards* before anything leaves, then removed
                # highest slot first: every pop renumbers the slots behind it,
                # and a graveyard holds several copies of a popular card under
                # one name, so a scan by value would take the wrong one
                # (idiom 11).
                taken = [pile.graveyard[slot] for slot in chosen_slots]
                for slot in sorted(chosen_slots, reverse=True):
                    pile.graveyard.pop(slot)
                controller.exile.extend(taken)
                self.log.append(
                    f"{controller.name} exiled "
                    + ", ".join(card.name for card in taken)
                    + f" from the graveyard of {pile.name} to activate "
                    f"{permanent.card.name}"
                )
                return taken
            return []
        candidates = [
            perm for perm in self.controlled_by(controller_index)
            if subject_matches(
                self, perm, described, observer=controller_index, source=permanent,
            )
        ]
        if len(candidates) < wanted:
            return []
        named = (
            self.permanent_at(controller, cost_permanent_index)
            if isinstance(cost_permanent_index, int) else None
        )
        victim = (
            named if any(named is option for option in candidates) else candidates[0]
        )
        # A counted battlefield exile would take *wanted* of them; no card in
        # the pool prints one, so the picks after the first follow the same
        # deterministic order the branch above uses.
        picked = [victim]
        for option in candidates:
            if len(picked) >= wanted:
                break
            if not any(option is already for already in picked):
                picked.append(option)
        taken = []
        for chosen in picked:
            owner_index = self.owner_index_of(chosen)
            card = chosen.card
            self.remove_from_battlefield(chosen)
            self.players[
                owner_index if owner_index is not None else controller_index
            ].exile.append(card)
            taken.append(card)
        self.log.append(
            f"{controller.name} exiled "
            + ", ".join(card.name for card in taken)
            + f" to activate {permanent.card.name}"
        )
        return taken

    def activate_from_hand(
        self,
        controller_index: int,
        card_name: str,
        ability_index: int = 0,
        hand_index: int | None = None,
    ) -> SimulationResult:
        """Activate an ability of a card **in hand** (Waker of Waves).

        CR 113.6: an ability functions only from the battlefield unless
        something says otherwise, and a cost the card can only pay from hand —
        "Discard this card" — is what says otherwise. So this refuses any
        ability without that cost rather than opening the hand generally: an
        ability activatable from anywhere would let a creature card tap for its
        own {T} ability before it was ever cast.

        A parallel entry point rather than a branch in
        ``activate_permanent_ability``, because almost everything that function
        does is about a permanent — the controller check, the summoning
        sickness, the "loses all abilities" read, the tap. None of it applies to
        a card in a hand, and threading a None permanent through all of it would
        make every one of those reads answer a question about nothing.
        """
        controller = self.players[controller_index]
        matches = [
            index for index, card in enumerate(controller.hand)
            if card.name == card_name
        ]
        if hand_index is not None and hand_index in matches:
            matches = [hand_index]
        if not matches:
            details = f"{card_name} is not in {controller.name}'s hand"
            self.log.append(details)
            return SimulationResult(card_name, False, "unsupported", details)
        index = matches[0]
        card = controller.hand[index]

        program = compile_card_oracle(card)
        if not 0 <= ability_index < len(program.activated_abilities):
            details = f"{card.name} has no ability {ability_index}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        ability = program.activated_abilities[ability_index]
        if not ability.cost.discard_self:
            details = f"{card.name}'s ability can only be activated from the battlefield"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if not ability.supported or ability.instruction is None:
            details = f"{card.name}: ability not implemented"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # CR 601.2h: an unpayable cost makes the ability unactivatable, checked
        # before anything is spent — the same order every other activation keeps.
        # The source is the *card* in hand, not a permanent: an ability
        # activated from a hand has no permanent, and its card is what a
        # restriction narrowing by type would be asking about.
        if self.enforce_mana_costs and not self._pay_mana_cost(
            controller, ability.cost.mana,
            purpose=PaymentPurpose(ACTIVATE, source=card),
        ):
            details = f"{controller.name} cannot pay for {card.name}'s ability"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # The card leaves the hand as the cost is paid (CR 602.2b), before the
        # ability is on the stack — so an effect that looks at the hand during
        # resolution does not see the card that paid for it.
        del controller.hand[index]
        self._discard_card(controller, card)
        self.log.append(f"{controller.name} discarded {card.name} to activate its ability")

        self._stack_push(
            # CR 602.2b: an activated ability's targets were chosen when it
            # was activated, so it does not choose again here.
            targets_already_chosen=True,
            item=StackItem(
                card=card,
                caster_index=controller_index,
                target_player_index=None,
                target_permanent_index=None,
                x_value=None,
                ability_instruction=ability.instruction,
                ability_effect_kind=ability.effect_kind,
                # No source permanent: the object is a card in a graveyard by
                # now, and an ability activated from hand has none by
                # construction. A handler that needs one refuses on its own.
                source_permanent=None,
                ability_text=ability.source_line,
            )
        )
        self.log.append(f"{card.name} ability added to stack")
        return SimulationResult(card.name, True, ability.effect_kind, "queued")

    def activate_from_graveyard(
        self,
        controller_index: int,
        card_name: str,
        ability_index: int = 0,
        graveyard_index: int | None = None,
        cost_permanent_id: int | None = None,
    ) -> SimulationResult:
        """Activate an ability of a card **in a graveyard** (Ashen Ghoul,
        Whiteout).

        CR 113.6m: an ability whose effect moves the card it is on out of a
        zone functions **only** from that zone. So the gate is not a list of
        cards and not a cost shape -- it is the compiled instruction's own
        ``functions_from`` key, the same derived fact ``engine/events.py`` reads
        to decide which graveyard triggers may fire. An ability without it is
        refused here, because opening the graveyard generally would let a
        creature card in the pile tap for its own {T} ability.

        A parallel entry point rather than a branch in
        ``activate_permanent_ability``, for ``activate_from_hand``'s reason:
        almost everything that function does -- the controller check, summoning
        sickness, the "loses all abilities" read, the tap -- is about a
        permanent, and a card in a graveyard is not one.

        **Two cost shapes, and any third is refused rather than waived.** Mana
        (Ashen Ghoul's {B}) and one sacrificed permanent named by a printed noun
        phrase (Whiteout's "Sacrifice a snow land"). A cost this cannot charge
        makes the ability unactivatable (CR 602.5c) -- the alternative is an
        ability activated for free, which is the silent direction.
        """
        controller = self.players[controller_index]
        matches = [
            index for index, card in enumerate(controller.graveyard)
            if card.name == card_name
        ]
        if graveyard_index is not None and graveyard_index in matches:
            matches = [graveyard_index]
        if not matches:
            details = f"{card_name} is not in {controller.name}'s graveyard"
            self.log.append(details)
            return SimulationResult(card_name, False, "unsupported", details)
        index = matches[0]
        card = controller.graveyard[index]

        program = compile_card_oracle(card)
        if not 0 <= ability_index < len(program.activated_abilities):
            details = f"{card.name} has no ability {ability_index}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        ability = program.activated_abilities[ability_index]
        if not ability.supported or ability.instruction is None:
            details = f"{card.name}: ability not implemented"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if ability.instruction.payload.get("functions_from") != "graveyard":
            details = (
                f"{card.name}'s ability does not function from a graveyard "
                "(CR 113.6)"
            )
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # Every printed "Activate only ..." clause on this line (CR 602.5), read
        # from the one table the support gate reads. The *card* is the source:
        # there is no permanent, and "three or more creature cards are above
        # this card" is a question about the card's place in the pile.
        denial = activation_denial(
            self, controller_index, card, ability.source_line or ""
        )
        if denial is not None:
            details = f"{card.name}: {denial}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        cost = ability.cost
        unchargeable = _graveyard_cost_refusal(cost)
        if unchargeable is not None:
            details = f"{card.name}: {unchargeable}"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)

        # CR 601.2h/602.5c: the whole cost is checked before any of it is spent,
        # so an ability with an unpayable half does not pay the other half.
        sacrifice_victim = None
        if cost.sacrifice_filter is not None:
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(
                    self, perm, cost.sacrifice_filter, observer=controller_index,
                )
            ]
            if not candidates:
                details = (
                    f"{card.name}: no {filter_head_noun(cost.sacrifice_filter)} "
                    "available to sacrifice"
                )
                self.log.append(details)
                return SimulationResult(card.name, False, "unsupported", details)
            named = (
                self.permanent_by_id(cost_permanent_id)
                if cost_permanent_id is not None else None
            )
            sacrifice_victim = (
                named if any(perm is named for perm in candidates)
                else self.default_sacrifice_pick(candidates)
            )

        if self.enforce_mana_costs and not self._pay_mana_cost(
            controller, cost.mana, purpose=PaymentPurpose(ACTIVATE, source=card),
        ):
            details = f"{controller.name} cannot pay for {card.name}'s ability"
            self.log.append(details)
            return SimulationResult(card.name, False, "unsupported", details)
        if sacrifice_victim is not None:
            self.sacrifice_permanent(sacrifice_victim)
            self.log.append(
                f"{controller.name} sacrificed {sacrifice_victim.card.name} "
                f"to activate {card.name}"
            )

        # The card leaves the graveyard only when the *effect* moves it
        # (CR 608.2), not as the cost is paid -- so it stays in the pile while
        # the ability is on the stack, which is what lets a second Ashen Ghoul
        # count it as a card above.
        self._stack_push(
            targets_already_chosen=True,
            item=StackItem(
                card=card,
                caster_index=controller_index,
                target_player_index=None,
                target_permanent_index=None,
                x_value=None,
                ability_instruction=ability.instruction,
                ability_effect_kind=ability.effect_kind,
                # No source permanent: the object is a card in a graveyard.
                source_permanent=None,
                ability_text=ability.source_line,
            )
        )
        self.log.append(f"{card.name} ability added to stack from the graveyard")
        return SimulationResult(card.name, True, ability.effect_kind, "queued")

    def tap_permanent(
        self,
        controller_index: int,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> bool:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        permanent = resolved[1] if resolved else None
        if permanent is None or permanent.tapped:
            return False

        self.become_tapped(permanent)
        self._turn_face_up(permanent)
        self.log.append(f"{controller.name} tapped {permanent_name}")
        return True


def _graveyard_cost_refusal(cost) -> str | None:
    """Why this activation cost cannot be charged from a graveyard, or None.

    Written as a *deny list over every field* rather than an allow list of the
    two shapes charged, because ``ActivatedAbilityCost`` grows: a field added
    later and not listed here would be a cost silently waived, which is the
    failure `engine/activation_restrictions.py` exists to prevent wearing
    another hat. Anything this names refuses the activation entirely.
    """
    if cost.requires_tap:
        # The tap symbol names the source permanent, and a card in a graveyard
        # is not one (CR 107.5).
        return "a tap symbol cannot be paid by a card in a graveyard"
    for field, label in (
        ("discard_last_drawn", "a discard cost"),
        ("exile_self", "an exile-this cost"),
        ("sacrifice_self", "a sacrifice-this cost"),
        ("exile_filter", "a chosen exile cost"),
        ("discard_cards", "a discard cost"),
        ("discard_at_random", "a random discard cost"),
        ("discard_whole_hand", "a discard-your-hand cost"),
        ("discard_self", "a discard-this cost"),
        ("put_counter", "a counter cost"),
        ("put_counter_filter", "a counter cost on a chosen permanent"),
        ("remove_counter", "a counter-removal cost"),
        ("tap_count", "a tap-other-permanents cost"),
        ("tap_attached", "a tap-the-attached-permanent cost"),
        ("mana_from_attached", "a cost read off an attached permanent"),
        ("exile_top_of_library", "a library-exile cost"),
        ("pay_life", "a life cost"),
        ("loyalty", "a loyalty cost"),
        ("loyalty_x_sign", "a loyalty cost"),
    ):
        if getattr(cost, field, None):
            return f"{label} is not charged from a graveyard"
    if cost.sacrifice_filter is not None and cost.sacrifice_count != 1:
        return "only a one-permanent sacrifice cost is charged from a graveyard"
    return None
