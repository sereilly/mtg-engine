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
from ...activation_restrictions import activation_denial
from ...auras import attached_ability_cost_reduction, aura_restriction_active
from ...cost_modifiers import ability_cost_tax, ability_self_reduction_amount
from ...mana_payment import is_mana_ability
from ...events import emit
from ...game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from ...handlers._common import permanent_matches_filter
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
#: activated ability produced the same kind (Priest of Yawgmoth). The listed
#: kind is the one whose handler really does call
#: `_sacrifice_creature_for_mana` (Diamond Valley).
COST_PERFORMING_KINDS = frozenset({
    "sacrifice_creature_gain_life_by_toughness",   # Diamond Valley
})


class AbilityActivationMixin:
    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
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
            if not self._pay_mana_cost(controller, required):
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
                    controller, self._parse_mana_cost("{B}", x_value=0)
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
        if ability.cost.remove_counter:
            from ...named_counters import counters_key, counters_on

            kind = ability.cost.remove_counter
            held = counters_on(permanent, kind)
            if held <= 0:
                details = f"{permanent.card.name} has no {kind} counters to remove"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.metadata[counters_key(kind)] = held - 1

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
        # turn" is in the restriction table above; the *once* half is
        # per-permanent state rather than a property of the game, so it stays
        # here with the state it reads.
        once_each_turn = "once each turn" in ability_lower
        if once_each_turn and permanent.metadata.get("ability_used_turn") == self.turn:
            details = f"{permanent.card.name}'s ability can only be activated once each turn"
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
        if ability.cost.sacrifice_filter is not None and ability.instruction is not None and (
            ability.instruction.kind not in COST_PERFORMING_KINDS
        ):
            described = ability.cost.sacrifice_filter
            candidates = [
                perm
                for perm in self.controlled_by(controller_index)
                if subject_matches(self, perm, described, source=permanent)
            ]
            if not candidates:
                details = (
                    f"{permanent.card.name}: no "
                    f"{filter_head_noun(described)} available to sacrifice"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            # Through the seam, which bounds-checks and turns an index arriving
            # from the wire into a permanent exactly once.
            named_permanent = (
                self.permanent_at(controller, cost_permanent_index)
                if isinstance(cost_permanent_index, int)
                else None
            )
            # `in` compares Permanents by value and would match a look-alike, so
            # membership is tested by identity.
            sacrifice_cost_permanent = (
                named_permanent
                if any(perm is named_permanent for perm in candidates)
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

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        if x_value and "{x}" in (ability.source_line or "").lower():
            required_cost["generic"] = required_cost.get("generic", 0) + int(x_value)
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
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(controller, required_cost):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

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

        # The spelled-out tap cost, collected above and paid here — beside the
        # {T} symbol, because both are the same payment and CR 601.2h pays every
        # cost at one moment.
        for tapped_for_cost in tap_cost_permanents:
            self.become_tapped(tapped_for_cost)
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
            )

        # All guards/costs passed — mark a "once each turn" ability as used.
        if once_each_turn:
            permanent.metadata["ability_used_turn"] = self.turn

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
            controller.hand = [c for c in controller.hand if c is not discard_cost_card]
            self._discard_card(controller, discard_cost_card)
            self.log.append(
                f"{controller.name} discarded {discard_cost_card.name} "
                f"(the last card they drew this turn) to activate {permanent.card.name}"
            )

        # Pay the chosen discard. Same ordering rule as the Ring's above: the
        # cost is collected before the ability is on the stack, so an ability
        # that draws cannot discard what it drew.
        for cost_card in discard_cost_cards:
            controller.hand = [c for c in controller.hand if c is not cost_card]
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

            total = add_counters(permanent, ability.cost.put_counter)
            self.log.append(
                f"{permanent.card.name} has {total} "
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

        # Pay the chosen sacrifice (CR 601.2h) — the creature is gone before the
        # ability goes on the stack, so Hobblefiend's counter lands on a board
        # that has already lost it.
        if sacrifice_cost_permanent is not None:
            name = sacrifice_cost_permanent.card.name
            self.sacrifice_permanent(sacrifice_cost_permanent)
            self.log.append(
                f"{controller.name} sacrificed {name} to activate {permanent.card.name}"
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
            StackItem(
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
                },
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")
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
        if self.enforce_mana_costs and not self._pay_mana_cost(controller, ability.cost.mana):
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
            StackItem(
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
