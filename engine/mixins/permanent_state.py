from __future__ import annotations

import re

from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle

class PermanentStateMixin:
    def _initialize_permanent_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        if permanent.card.primary_type == "creature":
            permanent.metadata["summoning_sickness_turn"] = self.turn
        program = compile_card_oracle(permanent.card)
        text = program.normalized_text

        # enters tapped (static creature/permanent lines or normalized text)
        if any(line for line in program.static_lines if "enters tapped" in line) or (
            "enters tapped" in text and "unless" not in text
        ):
            permanent.tapped = True

        # choose opponent on enter
        if "as this artifact enters, choose an opponent" in text:
            chosen = target_player_index if target_player_index is not None else (1 - caster_index)
            permanent.metadata["chosen_player_index"] = chosen

        # enters with fixed counters (Clockwork Beast). Track the counter count so
        # the end-of-combat trigger and the upkeep activated ability can adjust it.
        if any("enters with seven +1/+0 counters on it" == line for line in program.static_lines) or "enters with seven +1/+0 counters on it" in text:
            permanent.power_bonus += 7
            permanent.metadata["plus_1_0_counters"] = 7

        # enters with X +1/+1 counters
        if any("enters with x +1/+1 counters on it" == line for line in program.static_lines) or "enters with x +1/+1 counters on it" in text:
            x_value = permanent.metadata.get("cast_x_value")
            if isinstance(x_value, int) and x_value > 0:
                permanent.power_bonus += x_value
                permanent.toughness_bonus += x_value

        # copy-as-enter creature
        if any("you may have this creature enter as a copy of any creature on the battlefield" == line for line in program.static_lines) or "you may have this creature enter as a copy of any creature on the battlefield" in text:
            source = self._resolve_copy_target(permanent, "creature")
            if source is None:
                source = next(
                    (
                        perm
                        for player in self.players
                        for perm in player.battlefield
                        if perm is not permanent and perm.card.primary_type == "creature"
                    ),
                    None,
                )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                permanent.metadata["absolute_power"] = source.effective_power
                permanent.metadata["absolute_toughness"] = source.effective_toughness

        # copy-as-enter enchantment
        if "you may have this enchantment enter as a copy of any artifact on the battlefield" in text:
            source = next(
                (
                    perm
                    for player in self.players
                    for perm in player.battlefield
                    if perm is not permanent and perm.card.primary_type == "artifact"
                ),
                None,
            )
            if source is not None:
                permanent.metadata["copied_from"] = source.card.name
                if "power" in source.card.raw and str(source.card.raw.get("power", "")).isdigit():
                    permanent.metadata["absolute_power"] = source.effective_power
                if "toughness" in source.card.raw and str(source.card.raw.get("toughness", "")).isdigit():
                    permanent.metadata["absolute_toughness"] = source.effective_toughness

        if any(instr.kind == "spell_pattern" and instr.value == "you have no maximum hand size" for instr in program.instructions) or "you have no maximum hand size" in text:
            self.players[caster_index].has_no_max_hand_size = True

        if "you may spend white mana as though it were red mana" in text:
            self.players[caster_index].can_spend_white_as_red = True

        if "as this enchantment enters, you lose life equal to your life total" in text:
            controller = self.players[caster_index]
            life_loss = controller.life
            controller.life -= life_loss
            self.log.append(f"{permanent.card.name}: {controller.name} lost {life_loss} life on entry")

    def _resolve_copy_target(self, permanent: Permanent, primary_type: str) -> Permanent | None:
        """Return the player-chosen permanent for a "copy as it enters" effect.

        The chosen target is recorded as ``copy_target = (player_index, perm_index)``
        when the spell is cast. Returns None if no legal choice was recorded so the
        caller can fall back to an arbitrary legal permanent.
        """
        copy_target = permanent.metadata.pop("copy_target", None)
        if copy_target is None:
            return None
        player_index, perm_index = copy_target
        if not isinstance(player_index, int) or not isinstance(perm_index, int):
            return None
        if not (0 <= player_index < len(self.players)):
            return None
        battlefield = self.players[player_index].battlefield
        if not (0 <= perm_index < len(battlefield)):
            return None
        candidate = battlefield[perm_index]
        if candidate is permanent or candidate.card.primary_type != primary_type:
            return None
        return candidate

    def _refresh_dynamic_creatures(self) -> None:
        all_permanents = [perm for player in self.players for perm in player.battlefield]
        kormus_active = any(perm.card.name == "Kormus Bell" for perm in all_permanents)
        living_lands_active = any(perm.card.name == "Living Lands" for perm in all_permanents)

        for player in self.players:
            # Static "Attacking creatures you control get +X/+Y" sources (Orcish
            # Oriflamme). The bonus only applies while a creature is attacking, so it
            # is stored in metadata and added by effective_power/toughness when the
            # creature has attacking == True.
            attacking_buff_power = 0
            attacking_buff_toughness = 0
            for perm in player.battlefield:
                for instr in compile_card_oracle(perm.card).instructions:
                    if instr.kind == "buff_attacking_creatures":
                        attacking_buff_power += int(instr.payload.get("power", 0))
                        attacking_buff_toughness += int(instr.payload.get("toughness", 0))
            for perm in player.battlefield:
                if perm.card.primary_type == "creature":
                    perm.metadata["attacking_buff_power"] = attacking_buff_power
                    perm.metadata["attacking_buff_toughness"] = attacking_buff_toughness

            non_wall_creatures = sum(
                1
                for perm in player.battlefield
                if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
            )
            swamp_count = sum(
                1
                for perm in player.battlefield
                if "swamp" in perm.card.type_line.lower() or perm.metadata.get("land_type_override") == "swamp"
            )
            plague_rats_total = sum(
                1 for p in self.players for perm in p.battlefield if perm.card.name == "Plague Rats"
            )

            for permanent in player.battlefield:
                prog = compile_card_oracle(permanent.card)
                instr_kinds = {instr.kind for instr in prog.instructions}

                if "dynamic_pt_non_wall_creatures" in instr_kinds:
                    permanent.metadata["absolute_power"] = non_wall_creatures
                    permanent.metadata["absolute_toughness"] = non_wall_creatures

                if "dynamic_pt_plague_rats" in instr_kinds:
                    permanent.metadata["absolute_power"] = plague_rats_total
                    permanent.metadata["absolute_toughness"] = plague_rats_total

                if "dynamic_pt_swamps" in instr_kinds:
                    permanent.metadata["absolute_power"] = swamp_count
                    permanent.metadata["absolute_toughness"] = swamp_count

                if "dynamic_pt_forests_gaea" in instr_kinds:
                    # Not attacking: forests its controller controls; attacking:
                    # forests the defending player controls.
                    if permanent.attacking and permanent.defending_player_index is not None:
                        reference_player = self.players[permanent.defending_player_index]
                    else:
                        reference_player = player
                    forest_count = sum(
                        1
                        for perm in reference_player.battlefield
                        if "forest" in perm.card.type_line.lower()
                        or perm.metadata.get("land_type_override") == "forest"
                    )
                    permanent.metadata["absolute_power"] = forest_count
                    permanent.metadata["absolute_toughness"] = forest_count

                if "conditional_swamp_bonus" in instr_kinds:
                    previous = int(permanent.metadata.get("conditional_swamp_bonus", 0))
                    if previous:
                        permanent.power_bonus -= previous
                        permanent.toughness_bonus -= previous
                    current = 1 if swamp_count > 0 else 0
                    if current:
                        permanent.power_bonus += current
                        permanent.toughness_bonus += current
                    permanent.metadata["conditional_swamp_bonus"] = current

                if kormus_active and "swamp" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1
                    permanent.metadata["color_override"] = "B"

                if living_lands_active and "forest" in permanent.card.type_line.lower() and permanent.card.primary_type == "land":
                    permanent.metadata["land_animated"] = True
                    permanent.metadata["absolute_power"] = 1
                    permanent.metadata["absolute_toughness"] = 1

    def _has_keyword(self, permanent: Permanent, keyword: str) -> bool:
        lower_keyword = keyword.lower()
        # "Loses flying" (e.g. Earthbind's granted ability) removes flying
        # regardless of its source — printed keyword or a granting effect.
        if lower_keyword == "flying" and (
            permanent.metadata.get("loses_flying", False)
            or permanent.metadata.get("loses_flying_until_eot", False)
        ):
            return False
        if any(item.lower() == lower_keyword for item in permanent.card.keywords):
            return True
        if lower_keyword == "flying" and permanent.metadata.get("gains_flying_until_eot", False):
            return True
        if lower_keyword == "first strike" and permanent.metadata.get("gains_first_strike", False):
            return True
        if lower_keyword == "fear" and permanent.metadata.get("gains_fear", False):
            return True
        if lower_keyword == "reach" and permanent.metadata.get("gains_reach", False):
            return True
        if lower_keyword == "haste" and permanent.metadata.get("gains_haste", False):
            return True
        if lower_keyword == "deathtouch" and permanent.metadata.get("has_deathtouch", False):
            return True
        # Fall back to oracle program static lines (e.g. test cards that put keyword in oracle_text)
        program = compile_card_oracle(permanent.card)
        return any(
            i.kind in ("keyword_line", "static_line") and lower_keyword in i.value
            for i in program.instructions
        )

    def _effective_colors(self, permanent: Permanent) -> set[str]:
        """The color symbols a permanent currently has (honoring color overrides)."""
        override = permanent.metadata.get("color_override")
        if override:
            return {override}
        return set(permanent.card.colors)

    def _protection_colors(self, permanent: Permanent) -> set[str]:
        """Color symbols this permanent has protection from (CR 702.16).

        Sourced from a printed "protection from [color]" static line or from a
        ``protection_from_<color>`` metadata flag granted by an Aura. Only color
        qualities are modeled — Limited Edition Alpha protection is always from a
        single color (e.g. Black Knight's "protection from white").
        """
        colors: set[str] = set()
        program = compile_card_oracle(permanent.card)
        for instr in program.instructions:
            if instr.kind == "static_line" and instr.value.startswith("protection from "):
                clause = instr.value[len("protection from "):].strip()
                # CR 702.16g/h/i: "protection from [A] and from [B]" (and comma
                # separated variants) is shorthand for several separate protection
                # abilities. Pull every color word out of the remaining clause.
                for word in re.split(r",|\band from\b|\band\b", clause):
                    symbol = _COLOR_WORD_TO_SYMBOL.get(word.strip())
                    if symbol:
                        colors.add(symbol)
        for key in permanent.metadata:
            if key.startswith("protection_from_"):
                symbol = _COLOR_WORD_TO_SYMBOL.get(key[len("protection_from_"):])
                if symbol:
                    colors.add(symbol)
        return colors

    def _is_protected_from(self, victim: Permanent, source: Permanent) -> bool:
        """True if *victim* has protection from a color *source* has (CR 702.16e/f)."""
        protection = self._protection_colors(victim)
        return bool(protection and protection & self._effective_colors(source))

    def _can_be_targeted(
        self, target: Permanent, source_card: CardDefinition | None
    ) -> bool:
        """Whether *target* is a legal target for *source_card* (CR 702.16b/702.18).

        Shroud forbids any targeting; protection forbids targeting by sources of
        the protected color. A ``None`` source is treated as colorless.
        """
        if self._has_keyword(target, "shroud"):
            return False
        protection = self._protection_colors(target)
        if protection and source_card is not None:
            if protection & set(source_card.colors):
                return False
        return True

    def _recalculate_lord_buffs(self) -> None:
        """Recalculate static-ability buffs from all lords on the battlefield.

        Per rule 611.3a, static abilities are not 'locked in' — they apply
        dynamically whenever their criteria are met. This method resets and
        recomputes all static_buff_power / static_buff_toughness values so that
        newly-entered creatures immediately receive relevant lord buffs, and
        creatures whose lords have left the battlefield lose those buffs.
        """
        # Step 1: Clear all existing static-ability-derived bonuses
        for player in self.players:
            for perm in player.battlefield:
                perm.metadata.pop("static_buff_power", None)
                perm.metadata.pop("static_buff_toughness", None)

        # Step 2: Re-apply static buffs from every permanent currently on battlefield
        for ctrl_player in self.players:
            for source_perm in ctrl_player.battlefield:
                prog = compile_card_oracle(source_perm.card)
                for instr in prog.instructions:
                    if instr.kind == "buff_creatures_global":
                        color_sym = instr.payload.get("color")
                        power = int(instr.payload.get("power", 0))
                        toughness = int(instr.payload.get("toughness", 0))
                        target_players = self.players if instr.payload.get("all") else [ctrl_player]
                        for tp in target_players:
                            for target_perm in tp.battlefield:
                                if target_perm.card.primary_type != "creature":
                                    continue
                                actual_colors = set(target_perm.card.colors)
                                if "color_override" in target_perm.metadata:
                                    actual_colors = {target_perm.metadata["color_override"]}
                                if color_sym and color_sym not in actual_colors:
                                    continue
                                target_perm.metadata["static_buff_power"] = (
                                    int(target_perm.metadata.get("static_buff_power", 0)) + power
                                )
                                target_perm.metadata["static_buff_toughness"] = (
                                    int(target_perm.metadata.get("static_buff_toughness", 0)) + toughness
                                )
