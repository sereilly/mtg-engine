from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle, lex_oracle_text

class EffectsMixin:
    def _trigger_aura_death_effects(self, dead_permanent: Permanent, controller: PlayerState) -> None:
        """Fire death-trigger aura effects for a creature that just left the battlefield."""
        aura = dead_permanent.metadata.get("attached_aura")
        if aura is None:
            return
        prog = compile_card_oracle(aura.card)
        text = prog.normalized_text
        if not text.startswith("enchant creature"):
            return
        for trig in prog.triggered_abilities:
            if trig.condition.kind == "dies" and trig.condition.trigger == "when":
                toughness = dead_permanent.effective_toughness
                damage = self._deal_damage_to_player(controller, toughness)
                self.log.append(
                    f"{aura.card.name} dealt {damage} damage to {controller.name} (death of {dead_permanent.card.name})"
                )
                break

    def _fire_dealt_damage_triggers(self, permanent: Permanent) -> None:
        """Fire 'whenever this creature is dealt damage' triggers (e.g. Fungusaur)."""
        program = compile_card_oracle(permanent.card)
        for trig in program.triggered_abilities:
            if trig.condition.kind != "creature_dealt_damage" or trig.instruction is None:
                continue
            if trig.instruction.kind == "add_counter_to_self":
                permanent.power_bonus += int(trig.instruction.payload.get("power", 1))
                permanent.toughness_bonus += int(trig.instruction.payload.get("toughness", 1))
                self.log.append(f"{permanent.card.name} gets a +1/+1 counter (dealt damage)")

    def _is_indestructible(self, permanent: Permanent) -> bool:
        """CR 700.4: a permanent with indestructible can't be destroyed by 'destroy'
        effects or lethal damage. In LEA, Consecrate Land grants this to a land."""
        return bool(permanent.metadata.get("is_indestructible"))

    def _destroy_target_permanent(
        self,
        target: PlayerState,
        type_filter: str | None = None,
        color_filter: str | None = None,
        target_permanent_index: int | None = None,
        exclude_colors: list[str] | None = None,
        exclude_types: list[str] | None = None,
        bypass_regeneration: bool = False,
        subtype_filter: str | None = None,
        tapped_only: bool = False,
    ) -> CardDefinition | None:
        target_player_index = next(
            (i for i, p in enumerate(self.players) if p is target), None
        )

        def _passes_type(card, tf):
            if not tf:
                return True
            if tf == "artifact_or_enchantment":
                return card.primary_type in ("artifact", "enchantment")
            return card.primary_type == tf

        def _is_legal_target(perm) -> bool:
            card = perm.card
            effective_colors = [perm.metadata.get("color_override")] if perm.metadata.get("color_override") else list(card.colors)
            if not _passes_type(card, type_filter):
                return False
            if subtype_filter and subtype_filter not in card.type_line.lower():
                return False
            if tapped_only and not perm.tapped:
                return False
            if color_filter and color_filter not in effective_colors:
                return False
            if exclude_colors and any(c in effective_colors for c in exclude_colors):
                return False
            if exclude_types:
                type_line_lower = card.type_line.lower()
                if any(et in type_line_lower for et in exclude_types):
                    return False
            return True

        def _do_destroy(perm: "Permanent", idx: int) -> "CardDefinition":
            if self._is_indestructible(perm):
                self.log.append(f"{perm.card.name} can't be destroyed (indestructible)")
                return None  # type: ignore[return-value]
            if not bypass_regeneration and perm.regeneration_shield > 0:
                perm.regeneration_shield -= 1
                perm.tapped = True
                perm.damage_marked = 0
                self.log.append(f"{perm.card.name} regenerated")
                return None  # type: ignore[return-value]
            target.battlefield.pop(idx)
            self._permanent_to_graveyard(target, perm)
            self._trigger_aura_death_effects(perm, target)
            if perm.card.primary_type == "land" and target_player_index is not None:
                self._process_land_dies(target_player_index)
            return perm.card

        if target_permanent_index is not None:
            if 0 <= target_permanent_index < len(target.battlefield):
                permanent = target.battlefield[target_permanent_index]
                if not _is_legal_target(permanent):
                    return None
                return _do_destroy(permanent, target_permanent_index)
            return None

        for idx, permanent in enumerate(target.battlefield):
            if not _is_legal_target(permanent):
                continue
            return _do_destroy(permanent, idx)

        return None

    def _tap_or_untap_target(self, target: PlayerState, make_tapped: bool) -> bool:
        for permanent in target.battlefield:
            permanent.tapped = make_tapped
            return True
        return False

    def _grant_regeneration_shield(
        self, target: PlayerState, target_permanent_index: int | None = None
    ) -> bool:
        # Honor an explicitly chosen creature (e.g. Death Ward's "Regenerate target
        # creature" — the player picks which one). Fall back to the first creature.
        if isinstance(target_permanent_index, int) and 0 <= target_permanent_index < len(target.battlefield):
            chosen = target.battlefield[target_permanent_index]
            if chosen.card.primary_type == "creature":
                chosen.regeneration_shield += 1
                return True
            return False
        for permanent in target.battlefield:
            if permanent.card.primary_type == "creature":
                permanent.regeneration_shield += 1
                return True
        return False

    def _prevent_damage(self, target: PlayerState, damage: int) -> int:
        if damage > 1 and target.combat_damage_cap_one_charges > 0:
            target.combat_damage_cap_one_charges -= 1
            damage = 1
        if damage <= 0 or target.damage_prevention_pool <= 0:
            return damage
        prevented = min(damage, target.damage_prevention_pool)
        target.damage_prevention_pool -= prevented
        if target.damage_prevention_pool <= 0:
            target.damage_prevention_source = None
        return damage - prevented

    def _prevent_permanent_damage(self, permanent, damage: int) -> int:
        """Reduce *damage* about to be dealt to a creature by its prevention pool
        (Healing Salve prevention mode, Samite Healer, …). Returns the unprevented
        remainder, consuming the shield as it goes."""
        if damage <= 0 or permanent.damage_prevention_pool <= 0:
            return max(0, damage)
        prevented = min(damage, permanent.damage_prevention_pool)
        permanent.damage_prevention_pool -= prevented
        if permanent.damage_prevention_pool <= 0:
            permanent.damage_prevention_source = None
        if prevented > 0:
            self.log.append(f"Prevented {prevented} damage to {permanent.card.name}")
        return damage - prevented

    def _mark_damage_on_permanent(self, permanent, amount: int) -> int:
        """Mark *amount* damage on a creature after applying its prevention pool.
        Returns the damage actually marked (0 if fully prevented)."""
        dealt = self._prevent_permanent_damage(permanent, amount)
        if dealt > 0:
            permanent.damage_marked += dealt
        return dealt

    def _player_controls_text(self, player: PlayerState, phrase: str) -> bool:
        return any(phrase in perm.card.oracle_text.lower() for perm in player.battlefield)

    def _gain_life(self, target: PlayerState, amount: int, source_name: str | None = None) -> None:
        """Apply a life gain, honoring 'If you would gain life, draw that many cards
        instead' replacement effects (e.g. Lich, CR 614)."""
        if amount <= 0:
            return
        source = f" from {source_name}" if source_name else ""
        if self._player_controls_text(target, "if you would gain life, draw that many cards instead"):
            drawn = target.draw(amount)
            self.log.append(
                f"{target.name} would gain {amount} life{source}; drew {drawn} card(s) instead (Lich)"
            )
            return
        before = target.life
        target.life += amount
        self.log.append(f"{target.name} gained {amount} life{source} ({before} -> {target.life})")

    def _deal_damage_to_player(self, target: PlayerState, amount: int) -> int:
        """Apply damage to a player (after prevention) and fire 'whenever you're
        dealt damage' triggers (e.g. Lich). Returns the damage actually dealt."""
        damage = self._prevent_damage(target, amount)
        if damage > 0:
            target.life -= damage
            self._on_player_dealt_damage(target, damage)
        return damage

    def _on_player_dealt_damage(self, target: PlayerState, damage: int) -> None:
        # Track total damage dealt to each player this turn (Simulacrum, etc.).
        if damage > 0:
            target.damage_taken_this_turn += damage
        if not self._player_controls_text(
            target, "whenever you're dealt damage, sacrifice that many nontoken permanents"
        ):
            return
        for _ in range(damage):
            candidates = [
                perm for perm in target.battlefield if not perm.metadata.get("is_token", False)
            ]
            if not candidates:
                target.lost = True
                self.log.append(
                    f"{target.name} couldn't sacrifice a nontoken permanent and lost the game (Lich)"
                )
                return
            # Sacrifice permanents whose death would lose the game (e.g. Lich itself) last.
            choice = min(
                candidates,
                key=lambda perm: "you lose the game" in perm.card.oracle_text.lower(),
            )
            target.battlefield.remove(choice)
            self._permanent_to_graveyard(target, choice)
            self.log.append(f"{target.name} sacrificed {choice.card.name} (Lich)")

    def _add_mana_from_text(self, controller: PlayerState, text: str, preferred_color: str | None = None) -> None:
        # Prefer lexing the oracle text for mana symbols
        try:
            tokens = lex_oracle_text(text)
        except Exception:
            tokens = ()

        mana_tokens = [t.value for t in tokens if t.kind == "mana"]
        if mana_tokens:
            for raw in mana_tokens:
                sym = raw.strip("{}")
                if sym in {"W", "U", "B", "R", "G", "C"}:
                    controller.mana_pool[sym] += 1
            return

        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if "one mana of any color" in normalized:
            selected_color = self._normalize_mana_color(preferred_color) or "G"
            controller.mana_pool[selected_color] += 1

    def _return_creature_from_graveyard(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                caster.hand.append(caster.graveyard.pop(idx))
                return True
        return False

    def _reanimate_creature_to_battlefield(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                revived = caster.graveyard.pop(idx)
                controller_index = self.players.index(caster)
                self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
                return True
        return False

    def _bounce_target_creature(
        self, target: PlayerState, target_permanent_index: int | None = None
    ) -> bool:
        # Respect the chosen target when one was declared; otherwise fall back to
        # the first creature so AI / legacy callers still resolve.
        if isinstance(target_permanent_index, int) and 0 <= target_permanent_index < len(
            target.battlefield
        ):
            candidate = target.battlefield[target_permanent_index]
            if candidate.card.primary_type == "creature":
                target.hand.append(candidate.card)
                target.battlefield.pop(target_permanent_index)
                return True
        for idx, permanent in enumerate(target.battlefield):
            if permanent.card.primary_type == "creature":
                target.hand.append(permanent.card)
                target.battlefield.pop(idx)
                return True
        return False

    def _sacrifice_creature_for_mana(self, caster: PlayerState) -> CardDefinition | None:
        for idx, permanent in enumerate(caster.battlefield):
            if permanent.card.primary_type == "creature":
                removed = caster.battlefield.pop(idx)
                caster.graveyard.append(removed.card)
                return removed.card
        return None

    def _apply_color_override(
        self,
        target: PlayerState,
        symbol: str,
        target_permanent_index: int | None = None,
    ) -> bool:
        if not symbol:
            return False
        if target_permanent_index is not None and 0 <= target_permanent_index < len(target.battlefield):
            target.battlefield[target_permanent_index].metadata["color_override"] = symbol
            return True
        if target.battlefield:
            target.battlefield[0].metadata["color_override"] = symbol
            return True
        return False

    def _process_land_enters(self, land_controller_index: int) -> None:
        for controller in self.players:
            for permanent in controller.battlefield:
                program = compile_card_oracle(permanent.card)
                if not any(t.condition.kind == "land_enters" for t in program.triggered_abilities):
                    continue
                victim = self.players[land_controller_index]
                damage = self._deal_damage_to_player(victim, 2)
                self.log.append(f"{permanent.card.name} triggered for {damage} damage")

    def _process_land_dies(self, land_controller_index: int) -> None:
        """Fire land_dies triggered abilities (e.g. Dingus Egg) when a land is put into a graveyard."""
        for controller in self.players:
            for permanent in list(controller.battlefield):
                program = compile_card_oracle(permanent.card)
                for trig in program.triggered_abilities:
                    if trig.condition.kind != "land_dies" or trig.instruction is None:
                        continue
                    victim = self.players[land_controller_index]
                    amount = int(trig.instruction.payload.get("amount", 2))
                    damage = self._deal_damage_to_player(victim, amount)
                    self.log.append(f"{permanent.card.name} triggered for {damage} damage")

    def _fastbond_count(self, player_index: int) -> int:
        if player_index < 0 or player_index >= len(self.players):
            return 0
        return sum(1 for permanent in self.players[player_index].battlefield if permanent.card.name == "Fastbond")
