from __future__ import annotations

import random

from ..game_types import SimulationResult
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle

class TurnManagementMixin:
    def select_starting_player(
        self, rng: random.Random | None = None
    ) -> int:
        """Rule 103.1: Simulate a coin flip to choose who takes the first turn.

        *rng* – optional seeded :class:`random.Random` instance.  Pass one to
        make the flip deterministic (e.g. derived from a session seed).  Omit
        to use the module-level global RNG.

        Returns the index of the player who wins the flip and chooses to go
        first.  In this simulator the flip winner always chooses themselves.
        """
        source: random.Random = rng if rng is not None else random  # type: ignore[assignment]
        winner = source.randrange(len(self.players))
        self.log.append(
            f"Coin flip: {self.players[winner].name} wins and chooses to go first"
        )
        return winner

    def deal_opening_hands(self, starting_player_index: int) -> None:
        """Rule 103.5: Shuffle each player's library and draw opening hands of 7 cards.

        Hands are dealt starting with *starting_player_index* and proceeding
        in turn order.
        """
        order = list(range(starting_player_index, len(self.players))) + list(
            range(0, starting_player_index)
        )
        for i in order:
            player = self.players[i]
            random.shuffle(player.library)
            drawn = player.draw(7)
            self.log.append(f"{player.name} drew opening hand of {drawn} card(s)")

    def take_mulligan(
        self,
        player_index: int,
        bottom_card_indices: list[int] | None = None,
    ) -> bool:
        """Rule 103.5: Player takes a mulligan.

        The player shuffles their hand into their library, draws 7 cards, then
        puts a number of cards equal to their new mulligan count on the bottom
        of their library.

        *bottom_card_indices* – indices into the freshly drawn hand of the
        cards to place on the bottom.  Defaults to the last N cards drawn.

        Returns True if the mulligan was taken, False if the player cannot
        take further mulligans (they already have 0 cards).
        """
        player = self.players[player_index]
        if player.mulligans_taken >= 7:
            self.log.append(
                f"{player.name} cannot take further mulligans (hand would be 0 cards)"
            )
            return False

        # Shuffle hand back into library.
        player.library.extend(player.hand)
        player.hand.clear()
        random.shuffle(player.library)

        player.mulligans_taken += 1
        n = player.mulligans_taken

        # Draw a new hand of starting hand size (7).
        player.draw(7)

        # Put n cards on the bottom.
        if bottom_card_indices is None:
            cards_to_bottom = [player.hand.pop() for _ in range(min(n, len(player.hand)))]
        else:
            indices_sorted = sorted(set(bottom_card_indices), reverse=True)
            cards_to_bottom = [player.hand.pop(i) for i in indices_sorted]

        player.library.extend(cards_to_bottom)

        self.log.append(
            f"{player.name} took mulligan #{n}, drew 7, put {len(cards_to_bottom)}"
            f" card(s) on the bottom, keeping {len(player.hand)}"
        )
        return True

    def keep_hand(self, player_index: int) -> None:
        """Rule 103.5: Player declares to keep their current hand."""
        player = self.players[player_index]
        suffix = (
            f" ({player.mulligans_taken} mulligan(s) taken)"
            if player.mulligans_taken > 0
            else ""
        )
        self.log.append(
            f"{player.name} keeps opening hand of {len(player.hand)} card(s){suffix}"
        )

    def pregame_mulligan_draw(self, player_index: int) -> bool:
        """Pregame mulligan: shuffle hand back into library and draw 7 fresh cards.

        Bottom selection is deferred until the player keeps (web pregame flow only).
        Returns False if the player cannot take another mulligan (already at 7).
        """
        player = self.players[player_index]
        if player.mulligans_taken >= 7:
            return False
        player.library.extend(player.hand)
        player.hand.clear()
        random.shuffle(player.library)
        player.mulligans_taken += 1
        player.draw(7)
        self.log.append(
            f"{player.name} took mulligan #{player.mulligans_taken}, redrew 7 cards"
        )
        return True

    def start_turn(self, player_index: int) -> None:
        self.active_player_index = player_index
        self.lands_played_this_turn[player_index] = 0
        self.creatures_died_this_turn = 0
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        self._enter_main_phase(precombat=True)

    def start_next_turn(self) -> int:
        self.turn += 1
        next_player = self._compute_next_active_player()
        self.start_turn(next_player)
        return next_player

    def resolve_draw_step(self, player_index: int, sanctuary_choice: bool | None = None) -> int:
        phase = "beginning"
        step = "draw"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]

        # 614.1b/614.10: skip step is a replacement effect
        if self._consume_skip(self.skip_step_counts, step):
            self.log.append(f"{player.name} skipped draw step")
            if self._receives_priority(step):
                self._resolve_priority_window()
            self._on_step_or_phase_end(phase, step)
            return 0

        # Island Sanctuary: sanctuary_choice=None means auto-skip (AI); True=skip (human chose);
        # False=draw normally (human chose to draw instead of gaining protection)
        has_sanctuary = any(perm.card.name == "Island Sanctuary" for perm in player.battlefield)
        if has_sanctuary and sanctuary_choice is not False:
            player.island_sanctuary_protected = True
            self.log.append(f"{player.name} skipped draw (Island Sanctuary active)")
            if self._receives_priority(step):
                self._resolve_priority_window()
            self._on_step_or_phase_end(phase, step)
            return 0

        bonus = 0
        for controller in self.players:
            for permanent in controller.battlefield:
                if permanent.card.name == "Howling Mine" and not permanent.tapped:
                    bonus += 1
        drawn = player.draw(1 + bonus)
        self.log.append(f"{player.name} drew {drawn} card(s) in draw step")
        if self._receives_priority(step):
            self._resolve_priority_window()
        self._on_step_or_phase_end(phase, step)
        return drawn

    def get_untap_land_selection_options(self, player_index: int) -> dict[str, object] | None:
        player = self.players[player_index]
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            return None

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        if max_untap_lands >= 999:
            return None

        candidate_indices = [
            idx
            for idx, permanent in enumerate(player.battlefield)
            if permanent.card.primary_type == "land" and permanent.tapped
        ]
        if len(candidate_indices) <= max_untap_lands:
            return None

        return {
            "max_count": max_untap_lands,
            "candidate_indices": candidate_indices,
        }

    def resolve_untap_step(self, player_index: int, selected_land_indices: list[int] | None = None) -> int:
        phase = "beginning"
        step = "untap"
        self._set_phase_and_step(phase, step)
        self._on_step_or_phase_begin(phase, step)
        player = self.players[player_index]
        # Record untapped lands before untap step (used by Power Surge upkeep trigger)
        self.untapped_lands_at_turn_start[player_index] = sum(
            1 for perm in player.battlefield
            if perm.card.primary_type == "land" and not perm.tapped
        )
        # Island Sanctuary protection lasts until the player's next turn begins
        player.island_sanctuary_protected = False
        all_permanents = [perm for pl in self.players for perm in pl.battlefield]

        if any(perm.card.name == "Stasis" for perm in all_permanents):
            self.log.append(f"{player.name} skipped untap due to Stasis")
            return 0

        max_untap_creatures = 999
        if any(perm.card.name == "Smoke" for perm in all_permanents):
            max_untap_creatures = 1

        max_untap_lands = 999
        if any(perm.card.name == "Winter Orb" and not perm.tapped for perm in all_permanents):
            max_untap_lands = 1

        selected_lands: set[int] | None = None
        if selected_land_indices is not None:
            selected_lands = set()
            for idx in selected_land_indices:
                if idx < 0 or idx >= len(player.battlefield):
                    raise ValueError("selected land index out of range")
                permanent = player.battlefield[idx]
                if permanent.card.primary_type != "land":
                    raise ValueError("selected permanent is not a land")
                if not permanent.tapped:
                    continue
                selected_lands.add(idx)

            if max_untap_lands < 999 and len(selected_lands) > max_untap_lands:
                raise ValueError(f"cannot untap more than {max_untap_lands} land(s)")

        meekstone_active = any(perm.card.name == "Meekstone" for perm in all_permanents)

        untapped = 0
        creatures_untapped = 0
        lands_untapped = 0
        for idx, permanent in enumerate(player.battlefield):
            if not permanent.tapped:
                continue

            if permanent.card.primary_type == "creature":
                if meekstone_active and permanent.effective_power >= 3:
                    continue
                if creatures_untapped >= max_untap_creatures:
                    continue
                if permanent.metadata.get("aura_prevents_untap"):
                    continue
                creatures_untapped += 1

            if permanent.card.primary_type == "land":
                if selected_lands is not None and idx not in selected_lands:
                    continue
                if lands_untapped >= max_untap_lands:
                    continue
                lands_untapped += 1

            permanent.tapped = False
            untapped += 1

        self.log.append(f"{player.name} untapped {untapped} permanent(s)")
        self._on_step_or_phase_end(phase, step)
        return untapped

    def use_channel_mana(self, player_index: int, amount: int) -> SimulationResult:
        """Pay `amount` life via an active Channel effect to add that many {C} mana."""
        player = self.players[player_index]
        if not player.channel_active_until_eot:
            return SimulationResult("Channel", False, "spell_pattern", "Channel is not active")
        if amount <= 0:
            return SimulationResult("Channel", False, "spell_pattern", "Amount must be positive")
        player.life -= amount
        player.mana_pool["C"] = player.mana_pool.get("C", 0) + amount
        self.log.append(f"{player.name} paid {amount} life via Channel for {amount} {{C}}")
        return SimulationResult("Channel", True, "spell_pattern", f"added {amount} C")

    def tap_land_for_mana(
        self,
        player_index: int,
        land_name: str,
        chosen_color: str = "G",
        permanent_index: int | None = None,
    ) -> bool:
        player = self.players[player_index]
        resolved = self._find_controlled_permanent(player, land_name, permanent_index)
        land = resolved[1] if resolved else None
        if land is not None and land.card.primary_type != "land":
            land = None
        if land is None or land.tapped:
            return False

        land.tapped = True
        mana_symbol = chosen_color
        if land.card.produced_mana:
            if chosen_color in land.card.produced_mana:
                mana_symbol = chosen_color
            else:
                mana_symbol = land.card.produced_mana[0]
        else:
            land_types = [str(land.metadata.get("land_type_override", "")).lower(), land.card.type_line.lower()]
            if any("plains" in value for value in land_types):
                mana_symbol = "W"
            elif any("island" in value for value in land_types):
                mana_symbol = "U"
            elif any("swamp" in value for value in land_types):
                mana_symbol = "B"
            elif any("mountain" in value for value in land_types):
                mana_symbol = "R"
            elif any("forest" in value for value in land_types):
                mana_symbol = "G"
        player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        all_permanents = [perm for pl in self.players for perm in pl.battlefield]
        if any(perm.card.name == "Mana Flare" for perm in all_permanents):
            player.mana_pool[mana_symbol] = player.mana_pool.get(mana_symbol, 0) + 1

        land_type_line = land.card.type_line.lower()
        land_type_override = str(land.metadata.get("land_type_override", "")).lower()
        is_mountain = "mountain" in land_type_line or "mountain" in land_type_override
        if is_mountain and any(perm.card.name == "Gauntlet of Might" for perm in all_permanents):
            player.mana_pool["R"] = player.mana_pool.get("R", 0) + 1

        is_forest = "forest" in land_type_line or "forest" in land_type_override
        if is_forest:
            for i, controller in enumerate(self.players):
                if i != player_index:
                    for perm in controller.battlefield:
                        if perm.card.name == "Lifetap":
                            self._gain_life(controller, 1, "Lifetap")

        self.log.append(f"{player.name} tapped {land_name} for mana")

        # Kudzu: destroy enchanted land when tapped, then re-attach to another land
        aura = land.metadata.get("attached_aura")
        if aura is not None and aura.card.name == "Kudzu":
            land_idx = resolved[0]
            player.battlefield.pop(land_idx)
            player.graveyard.append(land.card)
            aura.metadata.pop("attached_to", None)
            land.metadata.pop("attached_aura", None)
            self.log.append(f"Kudzu destroyed {land_name}")
            next_land = next((p for p in player.battlefield if p.card.primary_type == "land"), None)
            if next_land is not None:
                aura.metadata["attached_to"] = next_land
                next_land.metadata["attached_aura"] = aura
                self.log.append(f"Kudzu attached to {next_land.card.name}")

        # Aura attached to this land: fire enchanted_land_tapped triggers (e.g. Psychic Venom)
        attached_aura = land.metadata.get("attached_aura")
        if attached_aura is not None and attached_aura.card.name != "Kudzu":
            aura_prog = compile_card_oracle(attached_aura.card)
            for trig in aura_prog.triggered_abilities:
                if trig.condition.kind == "enchanted_land_tapped" and trig.instruction is not None:
                    amount = int(trig.instruction.payload.get("amount", 0))
                    damage = self._deal_damage_to_player(player, amount)
                    self.log.append(f"{attached_aura.card.name} dealt {damage} damage to {player.name}")

        for controller in self.players:
            for perm in controller.battlefield:
                prog = compile_card_oracle(perm.card)
                for trig in prog.triggered_abilities:
                    if trig.condition.kind == "land_tapped_for_mana" and trig.instruction is not None:
                        amount = int(trig.instruction.payload.get("amount", 1))
                        damage = self._deal_damage_to_player(player, amount)
                        self.log.append(f"{perm.card.name} triggered: {player.name} took {damage} damage")

        return True
