from __future__ import annotations

import random
import re

from ..game_types import SimulationResult
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
        for player in self.players:
            player.damage_taken_this_turn = 0
        self.resolve_untap_step(player_index)
        self.resolve_upkeep(player_index)
        self.resolve_draw_step(player_index)
        self._enter_main_phase(precombat=True)

    def start_next_turn(self) -> int:
        self.turn += 1
        next_player = self._compute_next_active_player()
        self.start_turn(next_player)
        return next_player

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
        kudzu_reattach_index: int | None = None,
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
        produced = land.effective_produced_mana
        if produced:
            if chosen_color in produced:
                mana_symbol = chosen_color
            else:
                mana_symbol = produced[0]
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

        # Kudzu: destroy enchanted land when tapped, then re-attach to a land of
        # the controller's choice ("That land's controller may attach this Aura to
        # a land of their choice"). The caller passes the chosen land via
        # kudzu_reattach_index; absent a choice it defaults to the first other land
        # (deterministic for AI). The chosen land must not be the one being destroyed.
        aura = land.metadata.get("attached_aura")
        if aura is not None and aura.card.name == "Kudzu":
            land_idx = resolved[0]
            player.battlefield.pop(land_idx)
            player.graveyard.append(land.card)
            aura.metadata.pop("attached_to", None)
            land.metadata.pop("attached_aura", None)
            self.log.append(f"Kudzu destroyed {land_name}")
            new_land = None
            if (
                isinstance(kudzu_reattach_index, int)
                and 0 <= kudzu_reattach_index < len(player.battlefield)
                and player.battlefield[kudzu_reattach_index].card.primary_type == "land"
            ):
                new_land = player.battlefield[kudzu_reattach_index]
            if new_land is None:
                new_land = next((p for p in player.battlefield if p.card.primary_type == "land"), None)
            if new_land is not None:
                aura.metadata["attached_to"] = new_land
                new_land.metadata["attached_aura"] = aura
                self.log.append(f"Kudzu attached to {new_land.card.name}")

        # Aura attached to this land: fire enchanted_land_tapped triggers (e.g. Psychic Venom)
        attached_aura = land.metadata.get("attached_aura")
        if attached_aura is not None and attached_aura.card.name != "Kudzu":
            aura_prog = compile_card_oracle(attached_aura.card)
            for trig in aura_prog.triggered_abilities:
                if trig.condition.kind == "enchanted_land_tapped" and trig.instruction is not None:
                    amount = int(trig.instruction.payload.get("amount", 0))
                    damage = self._deal_damage_to_player(player, amount)
                    self.log.append(f"{attached_aura.card.name} dealt {damage} damage to {player.name}")
            # Wild Growth: "Whenever enchanted land is tapped for mana, its controller
            # adds an additional {G}." The "for mana" phrasing isn't compiled as a
            # generic trigger, so read the produced mana from the Aura's text here.
            aura_text = attached_aura.card.oracle_text.lower()
            mana_match = re.search(
                r"enchanted land is tapped for mana, its controller adds an additional \{([wubrgc])\}",
                aura_text,
            )
            if mana_match:
                extra = mana_match.group(1).upper()
                player.mana_pool[extra] = player.mana_pool.get(extra, 0) + 1
                self.log.append(f"{attached_aura.card.name}: {player.name} added an additional {{{extra}}}")

        for controller in self.players:
            for perm in controller.battlefield:
                prog = compile_card_oracle(perm.card)
                for trig in prog.triggered_abilities:
                    if trig.condition.kind == "land_tapped_for_mana" and trig.instruction is not None:
                        amount = int(trig.instruction.payload.get("amount", 1))
                        damage = self._deal_damage_to_player(player, amount)
                        self.log.append(f"{perm.card.name} triggered: {player.name} took {damage} damage")

        return True
