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
                damage = self._prevent_damage(controller, toughness)
                if damage > 0:
                    controller.life -= damage
                self.log.append(
                    f"{aura.card.name} dealt {damage} damage to {controller.name} (death of {dead_permanent.card.name})"
                )
                break

    def _destroy_target_permanent(
        self,
        target: PlayerState,
        type_filter: str | None = None,
        color_filter: str | None = None,
        target_permanent_index: int | None = None,
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

        if target_permanent_index is not None:
            if 0 <= target_permanent_index < len(target.battlefield):
                permanent = target.battlefield[target_permanent_index]
                if not _passes_type(permanent.card, type_filter):
                    return None
                if color_filter and color_filter not in permanent.card.colors:
                    return None
                # 614.8: regeneration is a destruction-replacement effect
                if permanent.regeneration_shield > 0:
                    permanent.regeneration_shield -= 1
                    permanent.tapped = True
                    permanent.damage_marked = 0
                    self.log.append(f"{permanent.card.name} regenerated")
                    return None
                removed = target.battlefield.pop(target_permanent_index)
                target.graveyard.append(removed.card)
                self._trigger_aura_death_effects(removed, target)
                if removed.card.primary_type == "land" and target_player_index is not None:
                    self._process_land_dies(target_player_index)
                return removed.card
            return None

        for idx, permanent in enumerate(target.battlefield):
            if not _passes_type(permanent.card, type_filter):
                continue
            if color_filter and color_filter not in permanent.card.colors:
                continue
            # 614.8: regeneration is a destruction-replacement effect
            if permanent.regeneration_shield > 0:
                permanent.regeneration_shield -= 1
                permanent.tapped = True
                permanent.damage_marked = 0
                self.log.append(f"{permanent.card.name} regenerated")
                return None
            removed = target.battlefield.pop(idx)
            target.graveyard.append(removed.card)
            self._trigger_aura_death_effects(removed, target)
            if removed.card.primary_type == "land" and target_player_index is not None:
                self._process_land_dies(target_player_index)
            return removed.card

        return None

    def _tap_or_untap_target(self, target: PlayerState, make_tapped: bool) -> bool:
        for permanent in target.battlefield:
            permanent.tapped = make_tapped
            return True
        return False

    def _grant_regeneration_shield(self, target: PlayerState) -> bool:
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
        return damage - prevented

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

    def _bounce_target_creature(self, target: PlayerState) -> bool:
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
                damage = self._prevent_damage(victim, 2)
                if damage > 0:
                    victim.life -= damage
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
                    damage = self._prevent_damage(victim, amount)
                    if damage > 0:
                        victim.life -= damage
                    self.log.append(f"{permanent.card.name} triggered for {damage} damage")

    def _fastbond_count(self, player_index: int) -> int:
        if player_index < 0 or player_index >= len(self.players):
            return 0
        return sum(1 for permanent in self.players[player_index].battlefield if permanent.card.name == "Fastbond")
