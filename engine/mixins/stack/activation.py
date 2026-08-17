"""Activating an ability of a permanent (CR 602): pay its cost and put it
on the stack.

The sibling of ``casting`` — same shape, different object. ``queue_permanent_ability``
is the large one: it resolves which of a multi-ability card's abilities was
chosen, checks the activation window, pays the cost, and either queues the
ability or (for a mana ability, CR 605.1a) performs it without using the stack.
"""

from __future__ import annotations

from ...cost_modifiers import ability_cost_tax, ability_self_reduction_amount
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
COST_PERFORMING_KINDS = frozenset({
    "sacrifice_creature_gain_life_by_toughness",   # Diamond Valley
    "sacrifice_creature_for_mana",                 # Metamorphosis / Sacrifice
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
        # Personal Incarnation: "Only this creatures owner may activate this
        # ability." grants the owner activation rights even while an opponent
        # controls the creature (CR 118.9a-style permission override).
        owner_may_activate = (
            "only this creatures owner may activate this ability" in permanent.effective_card.oracle_text.lower()
            and self.owner_index_of(permanent) == controller_index
        )
        if (
            source_owner is not controller
            and not owner_may_activate
            and "any player may activate this ability" not in permanent.effective_card.oracle_text.lower()
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

        program = compile_card_oracle(permanent.effective_card)

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

        if ability.instruction.kind == "grant_banding_to_target":
            # Helm of Chatzuk targets any creature (the chosen target_player; falls
            # back to any creature on the battlefield when no target was supplied).
            has_valid_target = any(perm.is_creature for perm in self.all_permanents())
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if ability.instruction.kind == "counter_top_stack_spell":
            # Already text-changed: the ability came from
            # ``compile_card_oracle(permanent.effective_card)`` above, so layer 3
            # has been applied once and must not be applied again here.
            color_filter = ability.instruction.payload.get("color_filter")
            if target_stack_item is not None:
                # A specific spell was chosen — it must itself be a legal target.
                if target_stack_item not in self.stack or (
                    color_filter and color_filter not in self._stack_item_colors(target_stack_item)
                ):
                    details = f"no valid target for {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)
            else:
                has_valid_target = any(
                    not color_filter or color_filter in self._stack_item_colors(item)
                    for item in self.stack
                )
                if not has_valid_target:
                    details = f"no valid target for {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)

        # Scavenging Ghoul: 'Remove a corpse counter from this creature: Regenerate
        # this creature.' — the counter removal is the activation cost.
        if (
            ability.instruction.kind == "grant_regeneration_to_self"
            and "remove a corpse counter from this creature" in program.normalized_text
        ):
            corpse_counters = int(permanent.metadata.get("corpse_counters", 0))
            if corpse_counters <= 0:
                details = f"{permanent.card.name} has no corpse counters to remove"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            permanent.metadata["corpse_counters"] = corpse_counters - 1

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

        # "Only during any upkeep step." (Armageddon Clock.) A window scoped to
        # a *step* rather than to a player's own step — the "any player may
        # activate" permission is checked separately above, and the two
        # together are what let an opponent wind the Clock back down.
        if "only during any upkeep step" in ability_lower:
            if self.current_step != "upkeep":
                details = f"{permanent.card.name} can only be activated during an upkeep step"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Activate only during your upkeep." (Cyclopean Tomb, the Clockwork
        # creatures, Rock Hydra's pump). Legal only on the controller's own upkeep.
        if "activate only during your upkeep" in ability_lower:
            if not (self.current_step == "upkeep" and self.active_player_index == controller_index):
                details = f"{permanent.card.name} can only be activated during your upkeep"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Activate only as a sorcery." (Illusionary Mask) — your turn, a main
        # phase, and an empty stack (CR 118.2a wording shortcut).
        if "activate only as a sorcery" in ability_lower:
            if not (
                self.active_player_index == controller_index
                and self.current_turn_phase in ("precombat_main", "postcombat_main")
                and not self.stack
            ):
                details = f"{permanent.card.name} can only be activated as a sorcery"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Activate only during combat." (Jade Statue) / "Activate only during
        # the end of combat step." (Desert).
        if "activate only during the end of combat step" in ability_lower:
            if self.current_step != "end_of_combat":
                details = f"{permanent.card.name} can only be activated during the end of combat step"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
        elif "activate only during combat" in ability_lower:
            if self.current_turn_phase != "combat":
                details = f"{permanent.card.name} can only be activated during combat"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Activate only during an opponent's turn, before attackers are
        # declared." (Nettling Imp; mirrors cast_restrictions' same phrase.)
        if "activate only during an opponent's turn, before attackers are declared" in ability_lower:
            legal = self.active_player_index != controller_index and (
                self.current_turn_phase in ("beginning", "precombat_main")
                or (
                    self.current_turn_phase == "combat"
                    and self.current_step in ("beginning_of_combat", "declare_attackers")
                    and not self.combat_attackers_locked
                )
            )
            if not legal:
                details = (
                    f"{permanent.card.name} can only be activated during an opponent's turn, "
                    "before attackers are declared"
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

        # "Activate only if you have exactly seven cards in hand." (Library of
        # Alexandria's draw ability.)
        if "activate only if you have exactly seven cards in hand" in ability_lower and len(controller.hand) != 7:
            details = f"{permanent.card.name} can only be activated with exactly seven cards in hand"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)

        # "Activate only during your turn and only once each turn." (Instill Energy)
        oracle_lower = ability_lower
        if "only during your turn" in oracle_lower and self.active_player_index != controller_index:
            details = f"{permanent.card.name} can only be activated during your turn"
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)
        once_each_turn = "once each turn" in oracle_lower
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
        if ability.instruction.kind == "destroy_target_permanent" and isinstance(target_permanent_index, int):
            bf = target_player.battlefield
            legal = 0 <= target_permanent_index < len(bf) and permanent_matches_filter(
                bf[target_permanent_index], ability.instruction.payload
            )
            if not legal:
                details = f"no valid target for {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)

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
                details = f"{permanent.card.name}: not enough cards in hand to discard"
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
            if cost_hand_index is not None and (
                not 0 <= cost_hand_index < len(hand)
                or hand[cost_hand_index] not in payable
            ):
                details = (
                    f"{permanent.card.name}: no card at hand position "
                    f"{cost_hand_index} to discard for its cost"
                )
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
            named = hand[cost_hand_index] if isinstance(cost_hand_index, int) else payable[0]
            discard_cost_cards = [named]
            for card in payable:
                if len(discard_cost_cards) >= ability.cost.discard_cards:
                    break
                if card is not named:
                    discard_cost_cards.append(card)

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
            and instruction.payload.get("any_color", False)
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
                choices={"chosen_source": chosen_source},
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")
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
