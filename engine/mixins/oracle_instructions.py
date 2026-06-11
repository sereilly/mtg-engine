from __future__ import annotations

import random
import re

from ..game_types import OracleExecutionContext, OracleStateMachine
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ._constants import _COLOR_ROD_TRIGGERS, _EOT_METADATA_KEYS, _MANA_SYMBOLS

class OracleInstructionsMixin:
    def _execute_oracle_instruction(
        self,
        instruction: OracleInstruction,
        context: OracleExecutionContext,
    ) -> tuple[bool, str]:
        caster = context.caster
        target = context.target
        card = context.card
        source_permanent = context.source_permanent
        x_value = context.x_value

        if instruction.kind == "untap_self":
            if source_permanent is None:
                return False, "ability not implemented"
            if not source_permanent.tapped:
                return False, f"{card.name} is already untapped"
            source_permanent.tapped = False
            self.log.append(f"{card.name} untapped itself")
            return True, "resolved"
        target = context.target
        card = context.card
        source_permanent = context.source_permanent
        x_value = context.x_value

        if instruction.kind == "draw_target_cards":
            amount = instruction.payload.get("amount", 0)
            count = max(0, x_value or 0) if amount == "x" else int(amount)
            drawn = target.draw(count)
            self.log.append(f"{target.name} drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "discard_hand_ante_then_draw_seven":
            while caster.hand:
                caster.graveyard.append(caster.hand.pop(0))
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
            drawn = caster.draw(7)
            self.log.append(f"{card.name} resolved: discarded hand and drew {drawn} cards")
            return True, "resolved"

        if instruction.kind == "each_player_antes_top_card":
            anted = 0
            for player in self.players:
                if player.library:
                    player.graveyard.append(player.library.pop(0))
                    anted += 1
            self.log.append(f"{card.name} anted {anted} card(s) in simplified model")
            return True, "resolved"

        if instruction.kind == "exchange_ante_with_top_library":
            if caster.library:
                caster.graveyard.append(caster.library.pop(0))
                self.log.append(f"{card.name} exchanged top library card with simulated ante zone")
            else:
                self.log.append(f"{card.name} resolved with no library card to exchange")
            return True, "resolved"

        if instruction.kind == "copy_top_stack_spell":
            if self.stack:
                copied = self.stack[-1]
                self._apply_spell_text(caster, target, copied.card, x_value=copied.x_value)
                self.log.append(f"{card.name} copied {copied.card.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to copy")
            return True, "resolved"

        if instruction.kind == "balance_resources":
            min_lands = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "land") for player in self.players)
            min_creatures = min(sum(1 for perm in player.battlefield if perm.card.primary_type == "creature") for player in self.players)
            min_hand = min(len(player.hand) for player in self.players)
            for player in self.players:
                lands_kept = 0
                creatures_kept = 0
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        if lands_kept < min_lands:
                            lands_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    if permanent.card.primary_type == "creature":
                        if creatures_kept < min_creatures:
                            creatures_kept += 1
                            survivors.append(permanent)
                        else:
                            player.graveyard.append(permanent.card)
                        continue
                    survivors.append(permanent)
                player.battlefield = survivors
                while len(player.hand) > min_hand:
                    player.graveyard.append(player.hand.pop(0))
            self.log.append("Balance normalized lands, creatures, and hands")
            return True, "resolved"

        if instruction.kind == "grant_unlimited_blocking":
            blocker = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if blocker is not None:
                blocker.metadata["must_block_all_until_eot"] = True
            self.log.append(f"{card.name} created a forced blocking assignment")
            return True, "resolved"

        if instruction.kind == "randomize_blockers":
            self.log.append(f"{card.name} set up random pile blocking this turn")
            return True, "resolved"

        if instruction.kind == "remove_creature_from_combat":
            removed = next((perm for perm in target.battlefield if perm.card.primary_type == "creature"), None)
            if removed is not None:
                removed.metadata["removed_from_combat"] = True
            self.log.append(f"{card.name} removed a blocker from combat")
            return True, "resolved"

        if instruction.kind == "left_right_combat_division":
            self.log.append(f"{card.name} established left/right combat division")
            return True, "resolved"

        if instruction.kind == "deal_damage":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            target_perm_idx = context.target_permanent_index
            # Support multiple target indices for spells like Fireball
            if isinstance(target_perm_idx, list):
                indices = [i for i in target_perm_idx if isinstance(i, int) and 0 <= i < len(target.battlefield)]
                n = len(indices)
                if n == 0:
                    # No valid creature targets; treat as player damage
                    damage = self._prevent_damage(target, damage)
                    if damage > 0:
                        target.life -= damage
                    self.log.append(f"{target.name} took {damage} damage")
                    return True, "resolved"
                per_target = damage // n if n > 0 else 0
                for idx in sorted(indices, reverse=True):
                    target_perm = target.battlefield[idx]
                    target_perm.damage_marked += per_target
                    effective_toughness = target_perm.effective_toughness
                    self.log.append(f"{card.name} dealt {per_target} damage to {target_perm.card.name}")
                    if target_perm.damage_marked >= effective_toughness:
                        target_perm.metadata["no_regenerate"] = True
                        target.battlefield.pop(idx)
                        self._permanent_to_graveyard(target, target_perm)
                        self.log.append(f"{target_perm.card.name} died from damage dealt by {card.name}")
                return True, "resolved"
            if target_perm_idx is not None and isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
                # Damage targets a creature permanent, not the player
                target_perm = target.battlefield[target_perm_idx]
                # 115.4: "any target" is limited to creatures, players, planeswalkers, and battles.
                # Noncreature artifacts (and other noncreature non-planeswalker permanents) are not
                # valid "any target" targets — the spell fizzles against them.
                if "any target" in card.oracle_text.lower():
                    type_line = target_perm.card.type_line.lower()
                    if "creature" not in type_line and "planeswalker" not in type_line:
                        self.log.append(
                            f"{card.name}: '{target_perm.card.name}' is not a valid 'any target' target (115.4)"
                        )
                        return True, "resolved"
                redirect_idx = target_perm.metadata.pop("redirect_damage_to_player", None)
                if redirect_idx is not None and 0 <= redirect_idx < len(self.players):
                    redirect_player = self.players[redirect_idx]
                    d = self._prevent_damage(redirect_player, damage)
                    if d > 0:
                        redirect_player.life -= d
                    self.log.append(f"Jade Monolith redirected {d} damage to {redirect_player.name}")
                    return True, "resolved"
                target_perm.damage_marked += damage
                effective_toughness = target_perm.effective_toughness
                self.log.append(f"{card.name} dealt {damage} damage to {target_perm.card.name}")
                if target_perm.damage_marked >= effective_toughness:
                    target_perm.metadata["no_regenerate"] = True
                    target.battlefield.pop(target_perm_idx)
                    self._permanent_to_graveyard(target, target_perm)
                    self.log.append(f"{target_perm.card.name} died from damage dealt by {card.name}")
            else:
                damage = self._prevent_damage(target, damage)
                if damage > 0:
                    target.life -= damage
                if source_permanent is not None:
                    self.log.append(f"{card.name} dealt {damage} damage")
                else:
                    self.log.append(f"{target.name} took {damage} damage")
            return True, "resolved"

        if instruction.kind == "deal_damage_each_creature_and_player":
            amount = int(instruction.payload.get("amount", 1))
            for player in self.players:
                d = self._prevent_damage(player, amount)
                if d > 0:
                    player.life -= d
            dead: list[tuple[PlayerState, Permanent]] = []
            for player in self.players:
                for perm in player.battlefield:
                    if perm.card.primary_type == "creature":
                        perm.damage_marked += amount
                        if perm.damage_marked >= perm.effective_toughness:
                            dead.append((player, perm))
            for player, perm in dead:
                if perm in player.battlefield:
                    player.battlefield.remove(perm)
                    player.graveyard.append(perm.card)
                    self.log.append(f"{perm.card.name} died from {card.name}")
            self.log.append(f"{card.name} dealt {amount} damage to each creature and each player")
            return True, "resolved"

        if instruction.kind == "deal_damage_and_self_damage":
            amount = int(instruction.payload.get("amount", 0))
            self_damage = int(instruction.payload.get("self_damage", 0))
            target_perm_idx = context.target_permanent_index
            if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
                target_perm = target.battlefield[target_perm_idx]
                target_perm.damage_marked += amount
                self.log.append(f"{card.name} dealt {amount} damage to {target_perm.card.name}")
                if target_perm.damage_marked >= target_perm.effective_toughness:
                    target_perm.metadata["no_regenerate"] = True
                    target.battlefield.pop(target_perm_idx)
                    self._permanent_to_graveyard(target, target_perm)
                    self.log.append(f"{target_perm.card.name} died from damage dealt by {card.name}")
            else:
                damage = self._prevent_damage(target, amount)
                if damage > 0:
                    target.life -= damage
                self.log.append(f"{card.name} dealt {damage} damage to {target.name}")
            caster.life -= self_damage
            self.log.append(f"{card.name} dealt {self_damage} damage to {caster.name} (self-damage)")
            return True, "resolved"

        if instruction.kind == "deal_damage_and_gain_life":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            damage = self._prevent_damage(target, damage)
            if damage > 0:
                target.life -= damage
            caster.life += damage
            self.log.append(f"{card.name} dealt {damage} damage and {caster.name} gained {damage} life")
            return True, "resolved"

        if instruction.kind == "earthquake_damage":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            # Deal damage to each player
            for player in self.players:
                d = self._prevent_damage(player, damage)
                if d > 0:
                    player.life -= d
            # Deal damage to each creature without flying on every battlefield
            for player in self.players:
                for perm in list(player.battlefield):
                    if perm.card.primary_type != "creature":
                        continue
                    has_flying = (
                        "Flying" in perm.card.keywords
                        or perm.metadata.get("gains_flying")
                        or perm.metadata.get("gains_flying_until_eot")
                    )
                    if has_flying:
                        continue
                    perm.damage_marked += damage
            self._destroy_marked_creatures()
            self.log.append(f"{card.name} dealt {damage} earthquake damage to each non-flying creature and each player")
            return True, "resolved"

        if instruction.kind == "hurricane_damage":
            amount = instruction.payload.get("amount", 0)
            damage = max(0, x_value or 0) if amount == "x" else int(amount)
            for player in self.players:
                d = self._prevent_damage(player, damage)
                if d > 0:
                    player.life -= d
            for player in self.players:
                for perm in list(player.battlefield):
                    if perm.card.primary_type != "creature":
                        continue
                    has_flying = (
                        "Flying" in perm.card.keywords
                        or perm.metadata.get("gains_flying")
                        or perm.metadata.get("gains_flying_until_eot")
                    )
                    if not has_flying:
                        continue
                    perm.damage_marked += damage
            self._destroy_marked_creatures()
            self.log.append(f"{card.name} dealt {damage} hurricane damage to each flying creature and each player")
            return True, "resolved"

        if instruction.kind == "drain_target_lands_mana":
            # Tap each of target's untapped lands and collect the mana they would produce
            mana_gained: dict[str, int] = {}
            for perm in target.battlefield:
                if perm.card.primary_type != "land" or perm.tapped:
                    continue
                perm.tapped = True
                if perm.card.produced_mana:
                    sym = perm.card.produced_mana[0].upper()
                else:
                    land_type = str(perm.metadata.get("land_type_override", "")).lower() or perm.card.type_line.lower()
                    if "plains" in land_type:
                        sym = "W"
                    elif "island" in land_type:
                        sym = "U"
                    elif "swamp" in land_type:
                        sym = "B"
                    elif "mountain" in land_type:
                        sym = "R"
                    elif "forest" in land_type:
                        sym = "G"
                    else:
                        sym = "C"
                mana_gained[sym] = mana_gained.get(sym, 0) + 1
            # Drain any existing unspent mana from target's pool too
            for sym in ("W", "U", "B", "R", "G", "C"):
                pool_amount = target.mana_pool.get(sym, 0)
                if pool_amount > 0:
                    mana_gained[sym] = mana_gained.get(sym, 0) + pool_amount
                    target.mana_pool[sym] = 0
            # Add all drained mana to caster
            for sym, amount_gained in mana_gained.items():
                caster.mana_pool[sym] = caster.mana_pool.get(sym, 0) + amount_gained
            total = sum(mana_gained.values())
            self.log.append(f"{card.name} drained {total} mana from {target.name}")
            return True, "resolved"

        if instruction.kind == "reanimate_creature":
            reanimated = self._reanimate_creature_to_battlefield(caster)
            self.log.append("Reanimated creature to battlefield" if reanimated else "No creature to reanimate")
            return True, "resolved"

        if instruction.kind == "bounce_target_creature":
            bounced = self._bounce_target_creature(target)
            self.log.append("Returned creature to hand" if bounced else "No creature to return")
            return True, "resolved"

        if instruction.kind == "exile_target_creature_until_eot":
            # 610.3: zone-change one-shot "until" EOT; second one-shot returns at cleanup
            target_perm_idx = context.target_permanent_index
            exiled_perm: Permanent | None = None
            if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
                candidate = target.battlefield[target_perm_idx]
                if candidate.card.primary_type == "creature":
                    exiled_perm = candidate
                    target.battlefield.pop(target_perm_idx)
            if exiled_perm is None:
                for idx, perm in enumerate(target.battlefield):
                    if perm.card.primary_type == "creature":
                        exiled_perm = perm
                        target.battlefield.pop(idx)
                        break
            if exiled_perm is not None:
                target.exile.append(exiled_perm.card)
                owner_idx = self.players.index(target)
                self.exile_until_eot.append((owner_idx, exiled_perm.card))
                self.log.append(f"{exiled_perm.card.name} exiled until end of turn by {card.name}")
            else:
                self.log.append(f"{card.name}: no valid creature to exile")
            return True, "resolved"

        if instruction.kind == "exile_creature_gain_life_equal_to_power":
            # Swords to Plowshares: exile target creature; its controller gains life = its power
            target_perm_idx = context.target_permanent_index
            exiled_perm: Permanent | None = None
            if isinstance(target_perm_idx, int) and 0 <= target_perm_idx < len(target.battlefield):
                candidate = target.battlefield[target_perm_idx]
                if candidate.card.primary_type == "creature":
                    exiled_perm = candidate
                    target.battlefield.pop(target_perm_idx)
            if exiled_perm is None:
                for idx, perm in enumerate(target.battlefield):
                    if perm.card.primary_type == "creature":
                        exiled_perm = perm
                        target.battlefield.pop(idx)
                        break
            if exiled_perm is not None:
                target.exile.append(exiled_perm.card)
                life_gain = exiled_perm.effective_power
                target.life += life_gain
                self.log.append(f"{exiled_perm.card.name} exiled by {card.name}; {target.name} gains {life_gain} life")
            else:
                self.log.append(f"{card.name}: no valid creature to exile")
            return True, "resolved"

        if instruction.kind == "prevent_all_combat_damage":
            self.combat_damage_prevented_until_eot = True
            self.log.append("Combat damage prevented until end of turn")
            return True, "resolved"

        if instruction.kind == "wheel_of_fortune":
            for player in self.players:
                while player.hand:
                    player.graveyard.append(player.hand.pop(0))
                player.draw(7)
            self.log.append("Wheel effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "timetwister":
            for player in self.players:
                pool = player.library + player.hand + player.graveyard
                player.library = list(pool)
                player.hand = []
                player.graveyard = []
                player.draw(7)
            self.log.append("Timetwister effect resolved for all players")
            return True, "resolved"

        if instruction.kind == "search_library":
            caster_index = self.players.index(caster)
            self.pending_search_library = {
                "caster_index": caster_index,
                "count": instruction.payload.get("count", 1),
                "card_type": instruction.payload.get("card_type", "any"),
            }
            self.log.append(f"{caster.name} is searching their library")
            return True, "pending_search_library"

        if instruction.kind == "grant_extra_turn":
            caster_index = self.players.index(caster)
            self.add_extra_turn(caster_index)
            self.log.append(f"{caster.name} gained an extra turn")
            return True, "resolved"

        if instruction.kind == "reorder_target_library_top":
            caster_index = self.players.index(caster)
            target_index = self.players.index(target)
            top_count = min(3, len(target.library))
            self.pending_reorder_library = {
                "caster_index": caster_index,
                "target_index": target_index,
                "top_count": top_count,
            }
            self.log.append(f"{caster.name} is looking at the top {top_count} cards of {target.name}'s library")
            return True, "pending_reorder_library"

        if instruction.kind == "mark_text_modified":
            perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
            # Always mark text_modified for the target permanent (backward compat).
            if perm_idx is not None and 0 <= perm_idx < len(target.battlefield):
                target.battlefield[perm_idx].metadata["text_modified"] = True
            elif target.battlefield:
                target.battlefield[0].metadata["text_modified"] = True
            # Also apply a color override when the caster specified a new color.
            symbol = context.new_color or ""
            if symbol:
                self._apply_color_override(target, symbol, target_permanent_index=perm_idx)
                self.log.append(f"{card.name} changed target's color to {symbol}")
            else:
                self.log.append(f"{card.name} applied a text change effect")
            return True, "resolved"

        if instruction.kind == "peek_hand_and_force_play":
            seen = len(target.hand)
            if target.hand:
                played = target.hand.pop(0)
                target.graveyard.append(played)
                self.log.append(f"{card.name} forced {target.name} to play {played.name}")
            else:
                self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "sacrifice_creature_for_black_mana":
            sacrificed = self._sacrifice_creature_for_mana(caster)
            if sacrificed is not None:
                caster.mana_pool["B"] += int(sacrificed.cmc)
                self.log.append(f"{caster.name} sacrificed {sacrificed.name} for {int(sacrificed.cmc)} black mana")
            else:
                self.log.append(f"{caster.name} had no creature to sacrifice")
            return True, "resolved"

        if instruction.kind == "recolor_target_from_text":
            symbol = str(instruction.payload.get("target_color", ""))
            perm_idx = context.target_permanent_index if isinstance(context.target_permanent_index, int) else None
            changed = self._apply_color_override(target, symbol, target_permanent_index=perm_idx) if symbol else False
            self.log.append("Changed target color" if changed else "No valid permanent to recolor")
            return True, "resolved"

        if instruction.kind == "destroy_all_creatures":
            bypass_regen = instruction.payload.get("bypass_regeneration", False)
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "creature" and not bypass_regen and permanent.regeneration_shield > 0:
                        permanent.regeneration_shield -= 1
                        permanent.tapped = True
                        survivors.append(permanent)
                    elif permanent.card.primary_type == "creature":
                        self._permanent_to_graveyard(player, permanent)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All creatures were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_artifacts_creatures_enchantments":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    primary_type = permanent.card.primary_type
                    if primary_type == "creature" and permanent.regeneration_shield > 0:
                        permanent.regeneration_shield -= 1
                        permanent.tapped = True
                        survivors.append(permanent)
                    elif primary_type in {"artifact", "creature", "enchantment"}:
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All artifacts, creatures, and enchantments were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_enchantments":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "enchantment":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All enchantments were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_lands":
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        player.graveyard.append(permanent.card)
                    else:
                        survivors.append(permanent)
                player.battlefield = survivors
            self.log.append("All lands were destroyed")
            return True, "resolved"

        if instruction.kind == "destroy_all_lands_of_type":
            land_type = str(instruction.payload.get("land_type", "")).lower().rstrip("s")
            for player in self.players:
                survivors: list[Permanent] = []
                for permanent in player.battlefield:
                    if permanent.card.primary_type == "land":
                        # Determine printed or overridden land type
                        perm_type_line = (permanent.metadata.get("land_type_override") or permanent.card.type_line or "").lower()
                        if land_type in perm_type_line:
                            player.graveyard.append(permanent.card)
                            continue
                    survivors.append(permanent)
                player.battlefield = survivors
            self.log.append(f"All {land_type}s were destroyed")
            return True, "resolved"

        if instruction.kind == "chaos_orb_flip":
            # Collect all permanents from all players except Chaos Orb itself
            candidates: list[tuple[PlayerState, Permanent]] = [
                (player, perm)
                for player in self.players
                for perm in player.battlefield
                if perm is not source_permanent
            ]
            num_to_destroy = random.randint(0, min(2, len(candidates)))
            chosen = random.sample(candidates, num_to_destroy) if num_to_destroy > 0 else []
            for victim_player, victim_perm in chosen:
                victim_player.graveyard.append(victim_perm.card)
                victim_player.battlefield = [p for p in victim_player.battlefield if p is not victim_perm]
                self.log.append(f"Chaos Orb flip destroyed {victim_perm.card.name}")
            # Always destroy Chaos Orb itself
            if source_permanent is not None:
                for player in self.players:
                    if source_permanent in player.battlefield:
                        player.graveyard.append(source_permanent.card)
                        player.battlefield = [p for p in player.battlefield if p is not source_permanent]
                        break
            self.log.append("Chaos Orb was destroyed after flip")
            return True, "resolved"

        if instruction.kind == "destroy_target_permanent":
            destroyed = self._destroy_target_permanent(
                target,
                type_filter=instruction.payload.get("type_filter"),
                color_filter=instruction.payload.get("color_filter"),
                target_permanent_index=context.target_permanent_index,
                exclude_colors=instruction.payload.get("exclude_colors"),
                exclude_types=instruction.payload.get("exclude_types"),
                bypass_regeneration=instruction.payload.get("bypass_regeneration", False),
            )
            if destroyed:
                if source_permanent is not None:
                    self.log.append(f"{card.name} destroyed {destroyed.name}")
                else:
                    self.log.append(f"Destroyed {destroyed.name}")
            else:
                self.log.append("No valid target permanent found")
            return True, "resolved"

        if instruction.kind == "return_creature_from_graveyard_to_hand":
            returned = self._return_creature_from_graveyard(caster)
            self.log.append("Returned creature from graveyard" if returned else "No creature to return")
            return True, "resolved"

        if instruction.kind == "discard_target_cards":
            actual = min(int(instruction.payload.get("amount", 0)), len(target.hand))
            for _ in range(actual):
                discarded = target.hand.pop(0)
                target.graveyard.append(discarded)
            self.log.append(f"{target.name} discarded {actual} cards")
            return True, "resolved"

        if instruction.kind == "discard_x_target_cards":
            x = max(0, x_value or 0)
            actual = min(x, len(target.hand))
            indices = random.sample(range(len(target.hand)), actual)
            for i in sorted(indices, reverse=True):
                discarded = target.hand.pop(i)
                target.graveyard.append(discarded)
            self.log.append(f"{target.name} discarded {actual} cards at random")
            return True, "resolved"

        if instruction.kind == "tap_target_player_lands_and_drain_mana":
            for perm in target.battlefield:
                if perm.card.primary_type == "land":
                    perm.tapped = True
            for sym in ("W", "U", "B", "R", "G", "C"):
                target.mana_pool[sym] = 0
            self.log.append(f"{card.name} tapped all lands and drained mana from {target.name}")
            return True, "resolved"

        # Rule 104.3e: effect that states a player loses the game
        if instruction.kind in ("target_player_loses_game", "player_loses_game"):
            # "you lose the game" triggers apply to caster; targeted spells apply to target
            loser = target if instruction.kind == "target_player_loses_game" else caster
            if not loser.lost:
                loser.lost = True
                self.log.append(f"{card.name}: {loser.name} lost the game (104.3e)")
            return True, "resolved"

        # Rule 104.2b: effect that states caster wins the game
        if instruction.kind == "player_wins_game":
            # 104.3f: if caster would also lose simultaneously, they lose instead
            if not caster.lost:
                # Mark all opponents as lost so caster is last standing (104.2a)
                for player in self.players:
                    if player is not caster and not player.lost:
                        player.lost = True
                        self.log.append(f"{card.name}: {player.name} lost (104.2b: opponent loses)")
                self.log.append(f"{card.name}: {caster.name} wins the game (104.2b)")
            return True, "resolved"

        # Rule 104.4c: effect that states the game is a draw
        if instruction.kind == "game_is_draw":
            if not self.is_draw:
                self.is_draw = True
                for player in self.players:
                    player.lost = True
                self.log.append(f"{card.name}: the game is a draw (104.4c)")
            return True, "resolved"

        if instruction.kind == "target_loses_life":
            amount = int(instruction.payload.get("amount", 0))
            before = target.life
            target.life -= amount
            self.log.append(f"{card.name}: {target.name} lost {amount} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "target_gains_life":
            amount = instruction.payload.get("amount", 0)
            life_gain = max(0, x_value or 0) if amount == "x" else int(amount)
            before = target.life
            target.life += life_gain
            self.log.append(f"{card.name}: {target.name} gained {life_gain} life ({before} -> {target.life})")
            return True, "resolved"

        if instruction.kind == "untap_target_land":
            untapped = False
            for perm in target.battlefield:
                if perm.card.primary_type == "land":
                    perm.tapped = False
                    untapped = True
                    break
            self.log.append("Untapped target land" if untapped else "No land to untap")
            return True, "resolved"

        if instruction.kind == "untap_target_permanent":
            untapped = self._tap_or_untap_target(target, make_tapped=False)
            self.log.append("Untapped target permanent" if untapped else "No valid permanent to untap")
            return True, "resolved"

        if instruction.kind == "untap_enchanted_creature":
            if source_permanent is None:
                return False, "ability not implemented"
            attached_to = source_permanent.metadata.get("attached_to")
            if attached_to is not None:
                attached_to.tapped = False
                self.log.append(f"Untapped {attached_to.card.name} via {card.name}")
            return True, "resolved"

        if instruction.kind == "tap_target_permanent":
            tapped = self._tap_or_untap_target(target, make_tapped=True)
            self.log.append("Tapped target permanent" if tapped else "No valid permanent to tap")
            return True, "resolved"

        if instruction.kind == "grant_prevention_shield":
            raw_amount = instruction.payload.get("amount", 0)
            amount = max(0, x_value or 0) if raw_amount == "x" else int(raw_amount)
            # CoP-style abilities say "prevent damage to you" — protection_kind="color"
            # means the caster/controller is always the beneficiary.
            # All other prevention (Samite Healer, etc.) goes to the designated target.
            if instruction.payload.get("protection_kind") == "color":
                recipient = caster
                self.log.append("Color protection shield granted")
            else:
                recipient = target
                self.log.append(f"{recipient.name} gains prevention shield for {amount} damage")
            recipient.damage_prevention_pool += amount
            return True, "resolved"

        if instruction.kind == "grant_forcefield_shield":
            caster.combat_damage_cap_one_charges += 1
            self.log.append("Forcefield shield granted")
            return True, "resolved"

        if instruction.kind == "berserk_pump":
            target_perm: Permanent | None = None
            if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
                candidate = target.battlefield[context.target_permanent_index]
                if candidate.card.primary_type == "creature":
                    target_perm = candidate
            if target_perm is None:
                target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is not None:
                boost = target_perm.effective_power
                target_perm.power_bonus += boost
                target_perm.metadata["gains_trample_until_eot"] = True
                self.log.append(f"{card.name} pumped {target_perm.card.name} by +{boost}/+0 and granted trample")
            else:
                self.log.append(f"{card.name}: no valid creature target")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_target_creature":
            regenerated = self._grant_regeneration_shield(target)
            self.log.append("Regeneration shield granted" if regenerated else "No valid creature to regenerate")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.regeneration_shield += 1
            self.log.append(f"{card.name} gains regeneration shield")
            return True, "resolved"

        if instruction.kind == "grant_regeneration_to_enchanted_creature":
            if source_permanent is None:
                return False, "ability not implemented"
            enchanted = source_permanent.metadata.get("attached_to")
            if enchanted is None:
                return False, "aura not attached to a creature"
            enchanted.regeneration_shield += 1
            self.log.append(f"{card.name} grants regeneration shield to {enchanted.card.name}")
            return True, "resolved"

        if instruction.kind == "pump_enchanted_creature":
            if source_permanent is None:
                return False, "ability not implemented"
            enchanted = source_permanent.metadata.get("attached_to")
            if enchanted is None:
                return False, "aura not attached to a creature"
            power_delta = int(instruction.payload.get("power", 0))
            toughness_delta = int(instruction.payload.get("toughness", 0))
            enchanted.power_bonus += power_delta
            enchanted.toughness_bonus += toughness_delta
            enchanted.metadata["temporary_power_bonus_until_eot"] = int(
                enchanted.metadata.get("temporary_power_bonus_until_eot", 0)
            ) + power_delta
            enchanted.metadata["temporary_toughness_bonus_until_eot"] = int(
                enchanted.metadata.get("temporary_toughness_bonus_until_eot", 0)
            ) + toughness_delta
            self.log.append(f"{card.name} grants {enchanted.card.name} +{power_delta}/+{toughness_delta} until end of turn")
            return True, "resolved"

        if instruction.kind == "pump_self":
            if source_permanent is None:
                return False, "ability not implemented"
            power_delta = int(instruction.payload.get("power", 0))
            toughness_delta = int(instruction.payload.get("toughness", 0))
            source_permanent.power_bonus += power_delta
            source_permanent.toughness_bonus += toughness_delta
            source_permanent.metadata["temporary_power_bonus_until_eot"] = int(
                source_permanent.metadata.get("temporary_power_bonus_until_eot", 0)
            ) + power_delta
            source_permanent.metadata["temporary_toughness_bonus_until_eot"] = int(
                source_permanent.metadata.get("temporary_toughness_bonus_until_eot", 0)
            ) + toughness_delta
            self.log.append(
                f"{card.name} gets +{int(instruction.payload.get('power', 0))}/+{int(instruction.payload.get('toughness', 0))} until end of turn"
            )
            return True, "resolved"

        if instruction.kind == "pump_self_with_sacrifice_condition":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.power_bonus += 1
            source_permanent.metadata["temporary_power_bonus_until_eot"] = int(
                source_permanent.metadata.get("temporary_power_bonus_until_eot", 0)
            ) + 1
            activation_count = int(source_permanent.metadata.get("pump_activation_count", 0)) + 1
            source_permanent.metadata["pump_activation_count"] = activation_count
            if activation_count >= 4:
                source_permanent.metadata["sacrifice_at_next_end_step"] = True
            self.log.append(
                f"{card.name} gets +1/+0 until end of turn (activation {activation_count})"
            )
            return True, "resolved"

        if instruction.kind == "grant_self_flying_until_eot":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["gains_flying_until_eot"] = True
            self.log.append(f"{card.name} gains flying until end of turn")
            return True, "resolved"

        if instruction.kind == "grant_target_flying_until_eot":
            target_perm_idx = context.target_permanent_index
            target_creature = None
            if target_perm_idx is not None and 0 <= target_perm_idx < len(target.battlefield):
                candidate = target.battlefield[target_perm_idx]
                if candidate.card.primary_type == "creature":
                    target_creature = candidate
            if target_creature is None:
                target_creature = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_creature is not None:
                target_creature.metadata["gains_flying_until_eot"] = True
                self.log.append(f"{target_creature.card.name} gains flying until end of turn from {card.name}")
            return True, "resolved"

        if instruction.kind == "jade_monolith_redirect":
            target_creature = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_creature is not None:
                caster_idx = self.players.index(caster)
                target_creature.metadata["redirect_damage_to_player"] = caster_idx
                self.log.append(f"Jade Monolith marks {target_creature.card.name} for damage redirect to {caster.name}")
            return True, "resolved"

        if instruction.kind == "grant_banding_to_target":
            # Banding is granted to one of the controller's own creatures, not the opponent's.
            target_creature = next((perm for perm in caster.battlefield if perm.card.primary_type == "creature"), None)
            if target_creature is None:
                self.log.append("No valid creature target for banding effect")
                return False, "no valid creature target for banding effect"
            target_creature.metadata["gains_banding_until_eot"] = True
            self.log.append(f"{target_creature.card.name} gains banding until end of turn")
            return True, "resolved"

        if instruction.kind == "add_counter_to_self":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.power_bonus += int(instruction.payload.get("power", 0))
            source_permanent.toughness_bonus += int(instruction.payload.get("toughness", 0))
            self.log.append(f"{card.name} gets a +1/+1 counter")
            return True, "resolved"

        if instruction.kind == "sacrifice_self_for_mana":
            if source_permanent is None:
                return False, "ability not implemented"
            caster.mana_pool[str(instruction.payload.get("color", "G"))] += int(instruction.payload.get("amount", 0))
            caster.graveyard.append(source_permanent.card)
            caster.battlefield = [perm for perm in caster.battlefield if perm is not source_permanent]
            self.log.append(f"{card.name} sacrificed for mana")
            return True, "resolved"

        if instruction.kind == "draw_controller_cards":
            drawn = caster.draw(int(instruction.payload.get("amount", 0)))
            self.log.append(f"{card.name} drew {drawn} card")
            return True, "resolved"

        if instruction.kind == "grant_unblockable_to_low_power_target":
            target_creature = next(
                (perm for perm in target.battlefield if perm.card.primary_type == "creature" and perm.effective_power <= 2),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["cant_be_blocked_until_eot"] = True
                self.log.append(f"{target_creature.card.name} can't be blocked this turn")
            else:
                self.log.append("No valid low-power creature for unblockable effect")
            return True, "resolved"

        if instruction.kind == "change_target_land_type":
            target_land = next((perm for perm in target.battlefield if perm.card.primary_type == "land"), None)
            if target_land is not None:
                target_land.metadata["land_type_override"] = str(instruction.payload.get("land_type", "forest"))
                self.log.append(f"{target_land.card.name} became a Forest")
            else:
                self.log.append("No target land for Forest effect")
            return True, "resolved"

        if instruction.kind == "mark_non_wall_target_to_attack":
            target_creature = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "creature" and "wall" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["must_attack_until_eot"] = True
                target_creature.metadata["destroy_if_did_not_attack_eot"] = True
                self.log.append(f"{target_creature.card.name} marked to attack this turn")
            else:
                self.log.append("No non-Wall target for Nettling Imp effect")
            return True, "resolved"

        if instruction.kind == "grant_flying_and_delayed_destruction":
            if source_permanent is None:
                return False, "ability not implemented"
            target_creature = next(
                (
                    perm
                    for perm in caster.battlefield
                    if perm.card.primary_type == "creature" and perm.effective_toughness < source_permanent.effective_power
                ),
                None,
            )
            if target_creature is not None:
                target_creature.metadata["gains_flying_until_eot"] = True
                target_creature.metadata["destroy_at_next_end_step"] = True
                self.log.append(f"{target_creature.card.name} gains temporary flying and delayed destruction")
            else:
                self.log.append("No valid target for Stone Giant effect")
            return True, "resolved"

        if instruction.kind == "redirect_one_damage_to_owner":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["redirect_one_damage_to_owner_until_eot"] = int(
                source_permanent.metadata.get("redirect_one_damage_to_owner_until_eot", 0)
            ) + 1
            self.log.append(f"{card.name} will redirect next 1 damage to its owner")
            return True, "resolved"

        if instruction.kind == "animate_self_until_end_of_combat":
            if source_permanent is None:
                return False, "ability not implemented"
            source_permanent.metadata["absolute_power"] = int(instruction.payload.get("power", 0))
            source_permanent.metadata["absolute_toughness"] = int(instruction.payload.get("toughness", 0))
            source_permanent.metadata["animate_until_end_of_combat"] = True
            self.log.append(f"{card.name} is animated until end of combat")
            return True, "resolved"

        if instruction.kind == "create_wasp_token":
            controller_index = self.players.index(caster)
            wasp = CardDefinition(
                name="Wasp",
                mana_cost="",
                cmc=0.0,
                type_line="Artifact Creature — Insect",
                oracle_text="Flying",
                colors=(),
                color_identity=(),
                keywords=("Flying",),
                produced_mana=(),
                raw={"name": "Wasp", "type_line": "Artifact Creature — Insect", "power": "1", "toughness": "1"},
            )
            self._put_permanent_onto_battlefield(controller_index, Permanent(card=wasp), None)
            self.log.append(f"{card.name} created a Wasp token")
            return True, "resolved"

        if instruction.kind == "cast_face_down_creature":
            controller_index = self.players.index(caster)
            creature_card = next(
                (c for c in caster.hand if c.primary_type == "creature"),
                None,
            )
            if creature_card is None:
                self.log.append(f"{card.name}: no creature in hand to cast face-down")
                return True, "resolved"
            caster.hand.remove(creature_card)
            face_down = CardDefinition(
                name=creature_card.name,
                mana_cost="",
                cmc=0.0,
                type_line="Creature",
                oracle_text="",
                colors=(),
                color_identity=(),
                keywords=(),
                produced_mana=(),
                raw={"name": creature_card.name, "type_line": "Creature", "power": "2", "toughness": "2"},
            )
            perm = Permanent(card=face_down)
            perm.metadata["face_down"] = True
            self._put_permanent_onto_battlefield(controller_index, perm, None)
            self.log.append(f"{card.name} cast {creature_card.name} face-down as a 2/2 creature")
            return True, "resolved"

        if instruction.kind == "look_at_target_hand":
            seen = len(target.hand)
            self.log.append(f"{card.name} looked at {target.name}'s hand ({seen} cards)")
            return True, "resolved"

        if instruction.kind == "add_mire_counter_to_target_land":
            target_land = next(
                (
                    perm
                    for perm in target.battlefield
                    if perm.card.primary_type == "land"
                    and "swamp" not in perm.card.type_line.lower()
                ),
                None,
            )
            if target_land is not None:
                target_land.metadata["land_type_override"] = "swamp"
                target_land.metadata["mire_counter"] = True
                self.log.append(f"{target_land.card.name} became a Swamp due to mire counter")
            else:
                self.log.append("No valid non-Swamp land for mire counter")
            return True, "resolved"

        if instruction.kind == "add_mana_from_text":
            self._add_mana_from_text(
                caster,
                str(instruction.payload.get("oracle_text", card.oracle_text)),
                preferred_color=str(instruction.payload.get("color", "")) or None,
            )
            self.log.append(f"{card.name} produced mana")
            return True, "resolved"

        if instruction.kind == "counter_top_stack_spell":
            color_filter = instruction.payload.get("color_filter")
            if self.stack:
                top = self.stack[-1]
                if color_filter and color_filter not in (top.card.colors or ()):
                    self.log.append(f"{card.name}: top spell is not color {color_filter}, cannot counter")
                    return True, "resolved"
                countered = self.stack.pop()
                self.players[countered.caster_index].graveyard.append(countered.card)
                self.log.append(f"{card.name} countered {countered.card.name}")
                if card.name == "Power Sink":
                    ctrl = self.players[countered.caster_index]
                    for perm in ctrl.battlefield:
                        if perm.card.primary_type == "land":
                            perm.tapped = True
                    ctrl.mana_pool = {k: 0 for k in ctrl.mana_pool}
                    self.log.append(f"{card.name} tapped all lands and drained mana from {ctrl.name}")
            else:
                self.log.append(f"{card.name} resolved with no spell to counter")
            return True, "resolved"

        if instruction.kind == "channel_life_for_mana":
            caster.channel_active_until_eot = True
            self.log.append(f"{caster.name} may pay life for {{C}} mana until end of turn (Channel)")
            return True, "resolved"

        if instruction.kind == "pump_target_creature_until_eot":
            raw_power = instruction.payload.get("power", 0)
            raw_toughness = instruction.payload.get("toughness", 0)
            power_delta = max(0, x_value or 0) if raw_power == "x" else int(raw_power)
            toughness_delta = max(0, x_value or 0) if raw_toughness == "x" else int(raw_toughness)
            target_perm: Permanent | None = None
            if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
                candidate = target.battlefield[context.target_permanent_index]
                if candidate.card.primary_type == "creature":
                    target_perm = candidate
            if target_perm is None:
                target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is None:
                target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is not None:
                target_perm.power_bonus += power_delta
                target_perm.toughness_bonus += toughness_delta
                target_perm.metadata["temporary_power_bonus_until_eot"] = int(
                    target_perm.metadata.get("temporary_power_bonus_until_eot", 0)
                ) + power_delta
                target_perm.metadata["temporary_toughness_bonus_until_eot"] = int(
                    target_perm.metadata.get("temporary_toughness_bonus_until_eot", 0)
                ) + toughness_delta
                self.log.append(f"{card.name} gives {target_perm.card.name} +{power_delta}/+{toughness_delta} until end of turn")
            return True, "resolved"

        # buff_creatures_global from a SPELL (sorcery/instant): locks in the set of
        # affected creatures at resolution (611.2c). Uses power_bonus so it is NOT
        # recalculated dynamically (unlike static abilities which use static_buff_*).
        if instruction.kind == "buff_creatures_global":
            color_sym = instruction.payload.get("color")
            power_delta = int(instruction.payload.get("power", 0))
            toughness_delta = int(instruction.payload.get("toughness", 0))
            target_players = self.players if instruction.payload.get("all") else [caster]
            for player in target_players:
                for perm in list(player.battlefield):
                    if perm.card.primary_type != "creature":
                        continue
                    actual_colors = set(perm.card.colors)
                    if "color_override" in perm.metadata:
                        actual_colors = {perm.metadata["color_override"]}
                    if color_sym and color_sym not in actual_colors:
                        continue
                    perm.power_bonus += power_delta
                    perm.toughness_bonus += toughness_delta
                    perm.metadata["temporary_power_bonus_until_eot"] = (
                        int(perm.metadata.get("temporary_power_bonus_until_eot", 0)) + power_delta
                    )
                    perm.metadata["temporary_toughness_bonus_until_eot"] = (
                        int(perm.metadata.get("temporary_toughness_bonus_until_eot", 0)) + toughness_delta
                    )
            self.log.append(f"{card.name} buffed matching creatures")
            return True, "resolved"

        # switch_pt: switches a target creature's power and toughness (613.4d)
        if instruction.kind == "switch_pt":
            target_perm: Permanent | None = None
            if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
                candidate = target.battlefield[context.target_permanent_index]
                if candidate.card.primary_type == "creature":
                    target_perm = candidate
            if target_perm is None:
                target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is None:
                target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is not None:
                target_perm.metadata["pt_switched"] = not target_perm.metadata.get("pt_switched", False)
                self.log.append(f"{card.name} switched power/toughness of {target_perm.card.name}")
            return True, "resolved"

        # become_pt_until_eot: sets absolute power/toughness (layer 7b) until EOT
        if instruction.kind == "become_pt_until_eot":
            new_power = int(instruction.payload.get("power", 0))
            new_toughness = int(instruction.payload.get("toughness", 0))
            target_perm = None
            if context.target_permanent_index is not None and 0 <= context.target_permanent_index < len(target.battlefield):
                candidate = target.battlefield[context.target_permanent_index]
                if candidate.card.primary_type == "creature":
                    target_perm = candidate
            if target_perm is None:
                target_perm = next((p for p in target.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is None:
                target_perm = next((p for p in caster.battlefield if p.card.primary_type == "creature"), None)
            if target_perm is not None:
                target_perm.metadata["absolute_power_until_eot"] = new_power
                target_perm.metadata["absolute_toughness_until_eot"] = new_toughness
                self.log.append(f"{card.name} set {target_perm.card.name} to {new_power}/{new_toughness} until EOT")
            return True, "resolved"

        self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
        return True, "resolved"

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
    ) -> None:
        instruction = self._select_executable_instruction(card)
        if instruction is None:
            self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
            return

        state_machine = OracleStateMachine(
            self,
            OracleExecutionContext(
                caster=caster,
                target=target,
                card=card,
                target_permanent_index=target_permanent_index,
                x_value=x_value,
                new_color=new_color,
            ),
        )
        state_machine.run(instruction)

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        if card.primary_type != "enchantment":
            return

        caster = self.players[caster_index]
        for permanent in caster.battlefield:
            if permanent.card.name == "Verduran Enchantress":
                drawn = caster.draw(1)
                self.log.append(f"Verduran Enchantress trigger: {caster.name} drew {drawn} card")

    def _apply_spell_resolved_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire permanent triggers that respond to a spell resolving (e.g. Crystal Rod)."""
        for controller in self.players:
            for permanent in controller.battlefield:
                entry = _COLOR_ROD_TRIGGERS.get(permanent.card.name)
                if entry is None:
                    continue
                trigger_color, life_amount = entry
                if trigger_color in card.colors:
                    controller.life += life_amount
                    self.log.append(
                        f"{permanent.card.name} trigger: {controller.name} gained {life_amount} life"
                    )

    def _apply_global_buff(self, caster: PlayerState, source: CardDefinition) -> None:
        program = compile_card_oracle(source)
        for instr in program.instructions:
            if instr.kind == "animate_all_swamps":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "animate_all_forests":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "buff_attacking_creatures":
                for permanent in caster.battlefield:
                    if permanent.card.primary_type == "creature":
                        permanent.power_bonus += int(instr.payload.get("power", 0))
                return
            if instr.kind == "buff_untapped_creatures":
                for permanent in caster.battlefield:
                    if permanent.card.primary_type == "creature" and not permanent.tapped:
                        permanent.toughness_bonus += int(instr.payload.get("toughness", 0))
                return
            if instr.kind == "buff_creatures_global":
                # Static ability: dynamically recalculated (611.3a). Use
                # static_buff_power / static_buff_toughness so the buff can
                # be removed when the lord leaves (611.3b) and applied to new
                # creatures as they enter (611.3c).
                self._recalculate_lord_buffs()
                return

            if instr.kind == "static_line" and instr.value.startswith("other ") and " get +" in instr.value:
                lord_match = re.search(r"other (\w+)s? get \+(\d+)/\+(\d+)(.*)", instr.value)
                if lord_match:
                    subtype_raw = lord_match.group(1).lower()
                    subtype = subtype_raw[:-1] if subtype_raw.endswith("s") else subtype_raw
                    power_bonus = int(lord_match.group(2))
                    toughness_bonus = int(lord_match.group(3))
                    rest = lord_match.group(4).lower()
                    for player in self.players:
                        for permanent in player.battlefield:
                            if permanent.card.primary_type != "creature":
                                continue
                            if subtype not in permanent.card.type_line.lower():
                                continue
                            if permanent.card is source:
                                continue
                            permanent.power_bonus += power_bonus
                            permanent.toughness_bonus += toughness_bonus
                            if "mountainwalk" in rest:
                                permanent.metadata["has_mountainwalk"] = True
                            if "islandwalk" in rest:
                                permanent.metadata["has_islandwalk"] = True
                return

    def _apply_aura_effect(
        self,
        caster_index: int,
        aura_permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
    ) -> None:
        program = compile_card_oracle(aura_permanent.card)
        text = program.normalized_text
        if not any(instr.kind == "spell_pattern" and instr.value.startswith("enchant") for instr in program.instructions) and not text.startswith("enchant enchantment"):
            return

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target_player = self.players[target_idx]

        if text.startswith("enchant creature"):
            # Special-case reanimation-style Auras (e.g., Animate Dead) which target a
            # creature card in a graveyard and return it to the battlefield attached
            # to this Aura. Detect the presence of the reanimation language and
            # handle it by moving a creature card from the target player's
            # graveyard to the caster's battlefield and attaching the Aura.
            # Prefer the parsed instruction if available
            has_reanimate = any(instr.kind == "reanimate_creature" for instr in program.instructions)
            if has_reanimate or ("creature card in a graveyard" in text and "return enchanted creature card to the battlefield" in text):
                # Search all players' graveyards for a creature card.
                # Prefer the caster's own graveyard first, then the target player's,
                # then any other player — so Animate Dead works when the owner's
                # graveyard is the only one that holds a creature.
                revived_card = None
                caster_player = self.players[caster_index]
                search_order = [caster_player, target_player] + [
                    p for p in self.players if p is not caster_player and p is not target_player
                ]
                for source_player in search_order:
                    for idx, card in enumerate(source_player.graveyard):
                        if card.primary_type == "creature":
                            revived_card = source_player.graveyard.pop(idx)
                            break
                    if revived_card is not None:
                        break
                if revived_card is None:
                    return

                # Put the revived creature onto the battlefield under the caster's control
                revived_perm = Permanent(card=revived_card)
                self._put_permanent_onto_battlefield(caster_index, revived_perm, None)
                # Attach the Aura to the revived permanent (store references in metadata)
                aura_permanent.metadata["attached_to"] = revived_perm
                revived_perm.metadata["attached_aura"] = aura_permanent
                # Apply the -1/-0 penalty from Animate Dead's text if present
                if "enchanted creature gets -1/-0" in text or "enchanted creature gets -1/ -0" in text:
                    revived_perm.power_bonus += -1

                self.log.append(f"{aura_permanent.card.name} reanimated {revived_card.name} and attached to aura")
                return

            # Normal enchant-creature behavior: attach to the creature chosen at cast time.
            # If the chosen target is no longer a legal creature (it left the battlefield
            # while the spell was on the stack), do not attach — the caller moves the
            # unattached Aura to the graveyard.
            target_creature = None
            if isinstance(target_permanent_index, int):
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "creature":
                        target_creature = candidate
            else:
                target_creature = next(
                    (perm for perm in target_player.battlefield if perm.card.primary_type == "creature"),
                    None,
                )
            if not target_creature:
                return

            # Handle numeric static buffs/debuffs like "gets +2/+1" or "gets -2/-1"
            buff_match = re.search(r"gets ([+-]\d+)/([+-]\d+)", text)
            if buff_match:
                target_creature.power_bonus += int(buff_match.group(1))
                target_creature.toughness_bonus += int(buff_match.group(2))

            # Handle Aspect of Wolf style dynamic buff text:
            # "Enchanted creature gets +X/+Y, where X is half the number of Forests you control, rounded down, and Y is half the number of Forests you control, rounded up."
            # Compute forest count controlled by the aura's controller (caster_index)
            if "half the number of forests you control" in text:
                caster_controller = self.players[caster_index]
                forests = sum(
                    1
                    for perm in caster_controller.battlefield
                    if perm.card.primary_type == "land"
                    and (
                        "forest" in perm.card.type_line.lower()
                        or perm.metadata.get("land_type_override") == "forest"
                    )
                )
                x = forests // 2
                y = (forests + 1) // 2
                target_creature.power_bonus += int(x)
                target_creature.toughness_bonus += int(y)

            # Landwalk/protection patterns are recognized in the compiled program;
            # fall back to normalized-text checks for logging when necessary.
            _walk_instrs = [instr for instr in program.instructions if instr.kind == "spell_pattern" and instr.value.startswith("has ") and "walk" in instr.value]
            if _walk_instrs or ("has " in text and "walk" in text):
                self.log.append(f"{target_creature.card.name} gains landwalk from {aura_permanent.card.name}")
                for _wi in _walk_instrs:
                    # e.g. "has mountainwalk" -> metadata key "has_mountainwalk"
                    _meta_key = _wi.value.replace(" ", "_")
                    target_creature.metadata[_meta_key] = True
                if not _walk_instrs:
                    for _walk_word in ("swampwalk", "mountainwalk", "islandwalk", "forestwalk", "plainswalk"):
                        if f"has {_walk_word}" in text:
                            target_creature.metadata[f"has_{_walk_word}"] = True

            if any("protection from" in instr.value for instr in program.instructions if instr.kind == "spell_pattern") or ("has protection from" in text):
                # Parse the specific color and stamp metadata on the creature
                _prot_match = re.search(r"protection from (\w+)", text)
                if _prot_match:
                    _prot_color = _COLOR_WORD_TO_SYMBOL.get(_prot_match.group(1).lower())
                    if _prot_color:
                        target_creature.metadata[f"protection_from_{_prot_match.group(1).lower()}"] = True
                self.log.append(f"{target_creature.card.name} gains protection from aura")

            if "has first strike" in text or "enchanted creature has first strike" in text or "gains first strike" in text:
                target_creature.metadata["gains_first_strike"] = True
                self.log.append(f"{target_creature.card.name} gains first strike from {aura_permanent.card.name}")

                # Fear: enchanted creature can't be blocked except by artifact creatures and/or black creatures
            if "has fear" in text or "enchanted creature has fear" in text or "gains fear" in text:
                target_creature.metadata["gains_fear"] = True
                self.log.append(f"{target_creature.card.name} gains fear from {aura_permanent.card.name}")

            # Flying: some Auras grant flying to the enchanted creature.
            # Exclude "if enchanted creature has flying" which is a conditional check, not a grant.
            _flying_conditional = "if enchanted creature has flying" in text or "if this creature has flying" in text
            _grants_flying = (
                ("has flying" in text and not _flying_conditional)
                or ("enchanted creature has flying" in text and not _flying_conditional)
                or "gains flying" in text
            )
            if _grants_flying:
                target_creature.metadata["gains_flying"] = True
                self.log.append(f"{target_creature.card.name} gains flying from {aura_permanent.card.name}")

            # Haste: enchanted creature can attack as though it had haste
            if "can attack as though it had haste" in text:
                target_creature.metadata["gains_haste"] = True
                self.log.append(f"{target_creature.card.name} gains haste from {aura_permanent.card.name}")

            # Invisibility: enchanted creature can't be blocked except by Walls
            if "can't be blocked except by walls" in text:
                target_creature.metadata["only_blockable_by_walls"] = True
                self.log.append(f"{target_creature.card.name} can only be blocked by Walls")

            # Attach the aura to the creature
            aura_permanent.metadata["attached_to"] = target_creature
            target_creature.metadata["attached_aura"] = aura_permanent

            # Lure: all creatures able to block this creature must do so
            if "all creatures able to block enchanted creature do so" in text:
                target_creature.metadata["lure_active"] = True
                self.log.append(f"{target_creature.card.name} must be blocked by all able creatures (Lure)")

            # Earthbind: on enter, if creature has flying, deal 2 damage and strip flying
            if "if enchanted creature has flying" in text and "deals 2 damage" in text:
                has_flying = (
                    "Flying" in target_creature.card.keywords
                    or target_creature.metadata.get("gains_flying")
                    or target_creature.metadata.get("gains_flying_until_eot")
                )
                if has_flying:
                    target_creature.damage_marked += 2
                    target_creature.metadata["loses_flying"] = True
                    self.log.append(f"{aura_permanent.card.name} dealt 2 damage to {target_creature.card.name} and stripped flying")

            # Paralyze: tap enchanted creature on enter and mark it as prevented from untapping
            if "tap enchanted creature" in text and "doesn't untap during its controller's untap step" in text:
                target_creature.tapped = True
                target_creature.metadata["aura_prevents_untap"] = True
                self.log.append(f"{aura_permanent.card.name} tapped {target_creature.card.name} and prevents it from untapping")

            # Control effect: steal creature to caster's battlefield (e.g. Control Magic)
            if "you control enchanted creature" in text:
                if target_creature in target_player.battlefield:
                    target_player.battlefield.remove(target_creature)
                    self.players[caster_index].battlefield.append(target_creature)
                    self.log.append(f"{aura_permanent.card.name} took control of {target_creature.card.name}")

        elif text.startswith("enchant land"):
            target_land = None
            if target_permanent_index is not None and 0 <= target_permanent_index < len(target_player.battlefield):
                candidate = target_player.battlefield[target_permanent_index]
                if candidate.card.primary_type == "land":
                    target_land = candidate
            if target_land is None and target_permanent_index is None:
                target_land = next((p for p in target_player.battlefield if p.card.primary_type == "land"), None)
            if target_land is None:
                self.log.append(f"{aura_permanent.card.name} found no land target")
                return
            aura_permanent.metadata["attached_to"] = target_land
            target_land.metadata["attached_aura"] = aura_permanent
            if "indestructible" in text:
                target_land.metadata["is_indestructible"] = True
            if "enchanted land is a swamp" in text:
                target_land.metadata["land_type_override"] = "swamp"
            elif "enchanted land is the chosen type" in text:
                # Phantasmal Terrain: simulation defaults to island (blue enchantment)
                target_land.metadata["land_type_override"] = "island"
            self.log.append(f"{aura_permanent.card.name} enchants {target_land.card.name}")
        elif text.startswith("enchant wall"):
            target_wall = None
            if isinstance(target_permanent_index, int):
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if "wall" in candidate.card.type_line.lower():
                        target_wall = candidate
            else:
                target_wall = next(
                    (perm for perm in target_player.battlefield if "wall" in perm.card.type_line.lower()),
                    None,
                )
            if target_wall:
                aura_permanent.metadata["attached_to"] = target_wall
                target_wall.metadata["attached_aura"] = aura_permanent
                target_wall.metadata["can_attack_as_though_no_defender"] = True
                self.log.append(f"{target_wall.card.name} can attack as though it didn't have defender")
        elif text.startswith("enchant artifact"):
            # Attach this Aura to the specified artifact (or first artifact found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_artifact = None
            if target_permanent_index is not None:
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "artifact":
                        target_artifact = candidate
            if target_artifact is None and target_permanent_index is None:
                target_artifact = next((perm for perm in target_player.battlefield if perm.card.primary_type == "artifact"), None)

            if target_artifact is None:
                return

            # Attach metadata links
            aura_permanent.metadata["attached_to"] = target_artifact
            target_artifact.metadata["attached_aura"] = aura_permanent

            # Control effect: steal artifact to caster's battlefield (e.g. Steal Artifact)
            if "you control enchanted artifact" in text:
                if target_artifact in target_player.battlefield:
                    target_player.battlefield.remove(target_artifact)
                    self.players[caster_index].battlefield.append(target_artifact)
                    self.log.append(f"{aura_permanent.card.name} took control of {target_artifact.card.name}")

            # Only animate if this Aura explicitly makes the artifact a creature (e.g. Animate Artifact)
            if ("it's an artifact creature" in text or "becomes an artifact creature" in text) and target_artifact.card.primary_type != "creature":
                new_type_line = target_artifact.card.type_line
                if "creature" not in new_type_line.lower():
                    new_type_line = (new_type_line + " Creature").strip()

                new_raw = dict(target_artifact.card.raw)
                power = toughness = max(1, int(target_artifact.card.cmc))
                new_raw["power"] = str(power)
                new_raw["toughness"] = str(toughness)

                new_card = CardDefinition(
                    name=target_artifact.card.name,
                    mana_cost=target_artifact.card.mana_cost,
                    cmc=target_artifact.card.cmc,
                    type_line=new_type_line,
                    oracle_text=target_artifact.card.oracle_text,
                    colors=target_artifact.card.colors,
                    color_identity=target_artifact.card.color_identity,
                    keywords=target_artifact.card.keywords,
                    produced_mana=target_artifact.card.produced_mana,
                    raw=new_raw,
                )

                target_artifact.card = new_card
                self.log.append(f"{aura_permanent.card.name} animated {target_artifact.card.name} into an artifact creature")
        elif text.startswith("enchant enchantment"):
            # Attach this Aura to the specified enchantment (or first enchantment found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_enchantment = None
            if target_permanent_index is not None:
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "enchantment":
                        target_enchantment = candidate
            if target_enchantment is None and target_permanent_index is None:
                target_enchantment = next((perm for perm in target_player.battlefield if perm.card.primary_type == "enchantment"), None)

            if target_enchantment is None:
                self.log.append(f"{aura_permanent.card.name} found no enchantment target")
                return

            aura_permanent.metadata["attached_to"] = target_enchantment
            target_enchantment.metadata["attached_aura"] = aura_permanent
            self.log.append(f"{aura_permanent.card.name} enchants {target_enchantment.card.name}")
