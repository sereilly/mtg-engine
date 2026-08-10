"""Activating an ability of a permanent (CR 602): pay its cost and put it
on the stack.

The sibling of ``casting`` — same shape, different object. ``queue_permanent_ability``
is the large one: it resolves which of a multi-ability card's abilities was
chosen, checks the activation window, pays the cost, and either queues the
ability or (for a mana ability, CR 605.1a) performs it without using the stack.
"""

from __future__ import annotations

from ...cost_modifiers import ability_cost_tax
from ...game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from ...handlers._common import permanent_matches_filter
from ...oracle import OracleInstruction, compile_card_oracle

class AbilityActivationMixin:
    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        target_permanent_index: int | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
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
            target_stack_index=target_stack_index,
            ability_index=ability_index,
            x_value=x_value,
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
    def queue_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        target_permanent_index: int | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
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
            "only this creatures owner may activate this ability" in permanent.card.oracle_text.lower()
            and self.owner_index_of(permanent) == controller_index
        )
        if (
            source_owner is not controller
            and not owner_may_activate
            and "any player may activate this ability" not in permanent.card.oracle_text.lower()
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



        # TODO(card-hooks): bespoke untap-cost plumbing, single card — migrate
        # to a card_hooks registry if a second card needs this shape.
        # Special handling for Basalt Monolith: only allow tap if untapped, untap if tapped
        if permanent.card.name == "Basalt Monolith" and len(program.activated_abilities) == 2:
            tap_ability = None
            untap_ability = None
            for ab in program.activated_abilities:
                if ab.cost.requires_tap:
                    tap_ability = ab
                elif ab.cost.mana.get("generic", 0) == 3 and not ab.cost.requires_tap:
                    untap_ability = ab
            if not permanent.tapped:
                ability = tap_ability
            else:
                ability = untap_ability
            # If trying to tap when tapped, or untap when untapped, block
            if ability is None:
                self.log.append(f"No implemented activated ability for {permanent.card.name} in current state")
                return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")
            if ability == tap_ability and permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith when already tapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already tapped")
            if ability == untap_ability and not permanent.tapped:
                self.log.append(f"Cannot untap Basalt Monolith when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
        elif ability_index is not None:
            # The caller chose which ability to activate (cards with more than one
            # activated ability, e.g. Rock Hydra's {R} prevention vs {R}{R}{R} pump).
            usable = [
                item
                for item in program.activated_abilities
                if item.supported and item.instruction is not None
            ]
            ability = usable[ability_index] if 0 <= ability_index < len(usable) else None
        else:
            ability = next((item for item in program.activated_abilities if item.supported and item.instruction is not None), None)

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
            has_valid_target = any(
                perm.is_creature
                for player in self.players
                for perm in player.battlefield
            )
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if ability.instruction.kind == "counter_top_stack_spell":
            color_filter = self._remap_color_filter(
                permanent, ability.instruction.payload.get("color_filter")
            )
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
        ability_lower = (ability.source_line or permanent.card.oracle_text).lower()

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

        # Ring of Ma'rûf: "Exile this artifact" is part of the cost, so the
        # permanent leaves before the ability goes on the stack — and the ability
        # still resolves from exile (CR 603.6 / 608.2: the source leaving doesn't
        # counter it). The stack item keeps its source_permanent reference.
        if ability.cost.exile_self:
            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
            controller.exile.append(permanent.card)
            self.log.append(
                f"{controller.name} exiled {permanent.card.name} to activate its ability"
            )

        # "Sacrifice this artifact" (Black Lotus, Bottle of Suleiman) is likewise
        # a cost, paid now — the ability still resolves from the graveyard.
        if ability.cost.sacrifice_self:
            controller.battlefield = [p for p in controller.battlefield if p is not permanent]
            self._permanent_to_graveyard(controller, permanent)
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
            "sacrifice_creature_for_black_mana",
        }
        if instruction.kind in mana_like_kinds:
            # For Basalt Monolith, block add_mana_from_text if untapped is required and it's already untapped
            if permanent.card.name == "Basalt Monolith" and instruction.kind == "add_mana_from_text" and not permanent.tapped:
                self.log.append(f"Cannot tap Basalt Monolith for mana when already untapped")
                return SimulationResult(permanent.card.name, False, "unsupported", "already untapped")
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

        self.stack.append(
            StackItem(
                card=permanent.card,
                caster_index=controller_index,
                target_player_index=target_idx,
                target_permanent_index=target_permanent_index,
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
