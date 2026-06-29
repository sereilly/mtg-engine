from __future__ import annotations

import random
import re

from ..classifier import CardClassification, classify_card
from ..game_types import OracleExecutionContext, OracleStateMachine, SimulationResult, StackItem
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle, lex_oracle_text
from ._constants import _MANA_SYMBOLS

# Maps an "enchant X" noun to a predicate matching legal battlefield targets.
_ENCHANT_TARGET_MATCHERS = {
    "artifact": lambda perm: "artifact" in perm.card.type_line.lower(),
    "creature": lambda perm: perm.card.primary_type == "creature",
    "land": lambda perm: perm.card.primary_type == "land",
    "enchantment": lambda perm: "enchantment" in perm.card.type_line.lower(),
    "wall": lambda perm: "wall" in perm.card.type_line.lower(),
}


def aura_enchant_noun(card: CardDefinition) -> str | None:
    """Return the battlefield enchant noun for an Aura card, or None.

    Returns None for non-Auras and for Auras that don't enchant battlefield
    permanents (e.g. Animate Dead's "enchant creature card in a graveyard").
    """
    if "Aura" not in card.type_line:
        return None
    first_line = card.oracle_text.lower().split("\n")[0]
    first_line = re.sub(r"\([^)]*\)", "", first_line).strip()  # drop reminder text
    if not first_line.startswith("enchant "):
        return None
    noun = first_line[len("enchant "):].strip()
    if "graveyard" in noun:
        return None
    return noun


def permanent_matches_enchant_noun(permanent: Permanent, noun: str) -> bool:
    matcher = _ENCHANT_TARGET_MATCHERS.get(noun)
    if matcher is None:
        return True  # unknown enchant type — treat any permanent as legal
    return matcher(permanent)


class StackCastingMixin:
    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        old_color: str | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
            new_color=new_color,
            target_stack_index=target_stack_index,
            mode_index=mode_index,
            old_color=old_color,
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")

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
        from ..handlers.prevention import apply_prevention_shield

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
                    and target_player.battlefield[target_perm_idx].card.primary_type == "creature"):
                return SimulationResult(label, False, "unsupported", "emblem target is no longer in play")

        if self.enforce_mana_costs:
            required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 1}
            if not self._pay_mana_cost(controller, required):
                return SimulationResult(label, False, "unsupported", "insufficient mana to activate emblem")

        apply_prevention_shield(self, target_player, target_perm_idx, 1)
        return SimulationResult(label, True, "activated_prevent_one", "resolved")

    def confirm_search_library(self, caster_index: int, library_index: int) -> bool:
        pending = self.pending_search_library
        if pending is None or pending["caster_index"] != caster_index:
            return False
        caster = self.players[caster_index]
        if library_index < 0 or library_index >= len(caster.library):
            return False
        card = caster.library.pop(library_index)
        caster.hand.append(card)
        random.shuffle(caster.library)
        self.pending_search_library = None
        self.log.append(f"{caster.name} searched library and put {card.name} into hand")
        return True

    def confirm_discard(self, player_index: int, hand_indices: list[int], to_library: bool = False) -> bool:
        """Resolve a pending non-random discard (Disrupting Scepter) with the
        player's chosen cards. ``to_library`` puts them on top of the library
        instead of the graveyard, but only if Library of Leng allows it."""
        from ..handlers.zones import _resolve_one_discard

        pending = self.pending_discard
        if pending is None or pending["player_index"] != player_index:
            return False
        count = int(pending["count"])
        chosen = [i for i in dict.fromkeys(hand_indices)][:count]
        if len(chosen) != count:
            return False
        # Remove in descending order so earlier indices stay valid as we pop.
        for hand_index in sorted(chosen, reverse=True):
            if not _resolve_one_discard(self, player_index, hand_index, to_library):
                return False
        self.pending_discard = None
        return True

    _BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

    def confirm_land_type(self, player_index: int, land_type: str) -> bool:
        """Resolve a pending Phantasmal Terrain choice with the controller's chosen
        basic land type, overriding the provisional default on the enchanted land."""
        pending = self.pending_land_type_choice
        if pending is None or pending["player_index"] != player_index:
            return False
        land_type = str(land_type or "").strip().lower()
        if land_type not in self._BASIC_LAND_TYPES:
            return False
        owner = self.players[pending["land_owner_index"]]
        idx = pending["land_index"]
        if 0 <= idx < len(owner.battlefield):
            land = owner.battlefield[idx]
            land.metadata["land_type_override"] = land_type
            self.log.append(
                f"{pending['card_name']}: enchanted land becomes a {land_type.title()}"
            )
        self.pending_land_type_choice = None
        return True

    def confirm_kudzu_reattach(self, player_index: int, land_index: int) -> bool:
        """Resolve a pending Kudzu reattach by moving the detached Aura onto the
        controller's chosen land."""
        pending = self.pending_kudzu_reattach
        if pending is None or pending["player_index"] != player_index:
            return False
        player = self.players[player_index]
        if not (0 <= land_index < len(player.battlefield)):
            return False
        new_land = player.battlefield[land_index]
        if new_land.card.primary_type != "land":
            return False
        aura = pending["aura"]
        aura.metadata["attached_to"] = new_land
        new_land.metadata["attached_aura"] = aura
        self.log.append(f"Kudzu attached to {new_land.card.name}")
        self.pending_kudzu_reattach = None
        return True

    def confirm_face_down_cast(self, player_index: int, hand_index: int | None) -> bool:
        """Resolve a pending Illusionary Mask face-down cast. ``hand_index`` < 0 (or
        None) declines (the choice is "you may"). Otherwise the chosen creature card
        (mana value <= the pending max) is cast face down as a 2/2, keeping the real
        card so it can later be turned face up."""
        pending = self.pending_face_down_cast
        if pending is None or pending["player_index"] != player_index:
            return False
        player = self.players[player_index]
        if hand_index is None or hand_index < 0:
            self.pending_face_down_cast = None
            return True
        if not (0 <= hand_index < len(player.hand)):
            return False
        creature_card = player.hand[hand_index]
        max_cmc = int(pending.get("max_cmc", 0))
        if creature_card.primary_type != "creature" or int(creature_card.cmc or 0) > max_cmc:
            return False
        player.hand.pop(hand_index)
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
        perm.metadata["face_down_real_card"] = creature_card
        self._put_permanent_onto_battlefield(player_index, perm, None)
        self.log.append(f"Illusionary Mask cast {creature_card.name} face down as a 2/2")
        self.pending_face_down_cast = None
        return True

    def confirm_word_of_command(self, caster_index: int, hand_index: int | None) -> bool:
        """Resolve a pending Word of Command: the target player plays the caster's
        chosen card from their hand, if able. ``hand_index`` < 0 (or None) declines.

        MVP: the forced spell defaults its target to the forced player themselves
        (so e.g. their burn/removal is turned on them). Caster-chosen targets for
        the forced spell are a future enhancement."""
        pending = self.pending_word_of_command
        if pending is None or pending["caster_index"] != caster_index:
            return False
        target_index = pending["target_index"]
        target = self.players[target_index]
        self.pending_word_of_command = None
        if hand_index is None or hand_index < 0:
            return True  # declined — nothing is played
        if not (0 <= hand_index < len(target.hand)):
            return False
        card_name = target.hand[hand_index].name
        result = self.queue_from_hand(target_index, card_name, target_player_index=target_index)
        if result.supported and self.stack:
            self.resolve_stack()
        if result.supported:
            self.log.append(f"Word of Command: {target.name} was forced to play {card_name}")
        else:
            self.log.append(f"Word of Command: {target.name} could not play {card_name} ({result.details})")
        return True

    def _balance_remove(self, player_index: int, land_indices, creature_indices, hand_indices) -> bool:
        """Remove the chosen lands/creatures (to graveyard) and hand cards (discard)
        for one player's Balance plan. Validates the counts against the plan."""
        pending = self.pending_balance
        if pending is None:
            return False
        plan = pending["plans"].get(player_index)
        if plan is None:
            return False
        player = self.players[player_index]
        lands = [i for i in dict.fromkeys(land_indices or [])]
        creatures = [i for i in dict.fromkeys(creature_indices or [])]
        hand = [i for i in dict.fromkeys(hand_indices or [])]
        if len(lands) != plan["lands"] or len(creatures) != plan["creatures"] or len(hand) != plan["hand"]:
            return False
        # Validate the chosen battlefield indices are the right card type.
        for i in lands:
            if not (0 <= i < len(player.battlefield)) or player.battlefield[i].card.primary_type != "land":
                return False
        for i in creatures:
            if not (0 <= i < len(player.battlefield)) or player.battlefield[i].card.primary_type != "creature":
                return False
        for i in hand:
            if not (0 <= i < len(player.hand)):
                return False
        # Remove battlefield permanents (highest index first) and hand cards.
        for i in sorted(set(lands) | set(creatures), reverse=True):
            perm = player.battlefield.pop(i)
            self._permanent_to_graveyard(player, perm)
        for i in sorted(hand, reverse=True):
            player.graveyard.append(player.hand.pop(i))
        del pending["plans"][player_index]
        if not pending["plans"]:
            self.pending_balance = None
        self.log.append(f"{player.name} resolved their Balance sacrifices")
        return True

    def _player_can_pay_generic(self, player, amount: int) -> bool:
        """Whether *player* can pay a generic cost of ``amount`` — counting both
        floating mana and untapped mana-producing lands. (The "you may pay {1}"
        rod/cup triggers fire on any player's spell, when the controller usually
        has no floating mana and must tap a land.)"""
        floating = sum(player.mana_pool.values())
        if floating >= amount:
            return True
        untapped_land_mana = sum(
            1
            for perm in player.battlefield
            if perm.card.primary_type == "land" and not perm.tapped and perm.effective_produced_mana
        )
        return floating + untapped_land_mana >= amount

    def _pay_optional(self, entry: dict) -> None:
        """Spend the entry's generic mana cost (floating mana first, then by tapping
        untapped lands) from its player and gain the life if fully paid."""
        player = self.players[entry["player_index"]]
        # A free optional "you may draw a card" rider (Verduran Enchantress): no
        # cost to pay, just draw on accept.
        if entry.get("draw"):
            drawn = player.draw(int(entry["draw"]))
            self.log.append(f"{player.name} drew {drawn} card(s) from {entry['card_name']}")
            return
        remaining = int(entry["cost"])
        for sym in list(player.mana_pool):
            while remaining > 0 and player.mana_pool.get(sym, 0) > 0:
                player.mana_pool[sym] -= 1
                remaining -= 1
        # Tap untapped lands to cover any generic remainder ({1}).
        if remaining > 0:
            for perm in player.battlefield:
                if remaining <= 0:
                    break
                if perm.card.primary_type == "land" and not perm.tapped and perm.effective_produced_mana:
                    perm.tapped = True
                    remaining -= 1
        if remaining == 0:
            self._gain_life(player, int(entry["life"]), entry["card_name"])

    def confirm_optional_pay(self, player_index: int, card_name: str | None = None, accept: bool = True) -> bool:
        """Resolve the first pending optional "pay {1}: gain N life" trigger for a
        player (the color rods). ``accept`` pays it; otherwise it is declined."""
        idx = next(
            (
                i for i, e in enumerate(self.pending_optional_pays)
                if e["player_index"] == player_index and (card_name is None or e["card_name"] == card_name)
            ),
            None,
        )
        if idx is None:
            return False
        entry = self.pending_optional_pays.pop(idx)
        if accept and self._player_can_pay_generic(self.players[player_index], int(entry["cost"])):
            self._pay_optional(entry)
        else:
            self.log.append(f"{self.players[player_index].name} declined {entry['card_name']}'s pay-for-life trigger")
        # The trigger ability that raised this prompt was held on the stack (human
        # priority path); now that the choice is made, it leaves the stack.
        self._remove_optional_pay_stack_item(entry)
        return True

    def _remove_optional_pay_stack_item(self, entry: dict) -> None:
        """Remove the triggered-ability stack object an optional-pay prompt was linked
        to, now that the prompt has been answered. No-op for entries created on the
        headless/auto path (where the ability already left the stack)."""
        stack_item = entry.get("_stack_item")
        if stack_item is not None and stack_item in self.stack:
            self.stack.remove(stack_item)

    def auto_resolve_pending_optional_pays(self, only_player_index: int | None = None) -> None:
        """Pay every pending optional "pay {1}: gain N life" trigger when able — the
        deterministic default used for AI players and headless simulation."""
        remaining: list[dict] = []
        for entry in self.pending_optional_pays:
            if only_player_index is not None and entry["player_index"] != only_player_index:
                remaining.append(entry)
                continue
            player = self.players[entry["player_index"]]
            available = sum(player.mana_pool.get(s, 0) for s in player.mana_pool)
            if available >= int(entry["cost"]):
                self._pay_optional(entry)
            self._remove_optional_pay_stack_item(entry)
        self.pending_optional_pays = remaining

    def confirm_balance(self, player_index: int, land_indices=None, creature_indices=None, hand_indices=None) -> bool:
        """Resolve one player's Balance plan with their chosen sacrifices/discards."""
        return self._balance_remove(player_index, land_indices, creature_indices, hand_indices)

    def auto_resolve_pending_balance(self, only_player_index: int | None = None) -> None:
        """Resolve Balance plans with a default choice (keep the lowest-index
        permanents/cards). Used for AI players and headless simulation. When
        ``only_player_index`` is given, resolve just that player's plan."""
        pending = self.pending_balance
        if pending is None:
            return
        for player_index in list(pending["plans"].keys()):
            if only_player_index is not None and player_index != only_player_index:
                continue
            plan = pending["plans"][player_index]
            player = self.players[player_index]
            land_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "land"][-plan["lands"]:] if plan["lands"] else []
            creature_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "creature"][-plan["creatures"]:] if plan["creatures"] else []
            hand_idx = list(range(len(player.hand)))[-plan["hand"]:] if plan["hand"] else []
            self._balance_remove(player_index, land_idx, creature_idx, hand_idx)

    def auto_resolve_pending_discard(self) -> None:
        """Resolve a pending discard with a default choice (the lowest-index cards,
        kept in the graveyard). Used for AI players and headless simulation."""
        from ..handlers.zones import _resolve_one_discard

        pending = self.pending_discard
        if pending is None:
            return
        player_index = pending["player_index"]
        count = int(pending["count"])
        for _ in range(count):
            if not _resolve_one_discard(self, player_index, 0, to_library=False):
                break
        self.pending_discard = None

    def confirm_reorder_library(self, caster_index: int, new_order: list, shuffle: bool = False) -> bool:
        pending = self.pending_reorder_library
        if pending is None or pending["caster_index"] != caster_index:
            return False
        target = self.players[pending["target_index"]]
        top_count = pending["top_count"]
        top = target.library[:top_count]
        rest = target.library[top_count:]
        if len(new_order) != top_count or sorted(new_order) != list(range(top_count)):
            return False
        target.library = [top[i] for i in new_order] + rest
        # "You may have that player shuffle" (Natural Selection): only honored when
        # the effect allows it.
        if shuffle and pending.get("may_shuffle"):
            random.shuffle(target.library)
            self.log.append(f"{target.name}'s library was shuffled")
        else:
            self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        self.pending_reorder_library = None
        return True

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
    ) -> SimulationResult:
        controller = self.players[controller_index]
        resolved = self._find_controlled_permanent(controller, permanent_name, permanent_index)
        if resolved is None:
            raise ValueError(f"Permanent not found: {permanent_name}")
        _, permanent = resolved

        program = compile_card_oracle(permanent.card)
        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

        # An explicitly chosen spell on the stack (e.g. Deathgrip: "{B}{B}: Counter
        # target green spell"). target_stack_index indexes self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]



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
            if permanent.metadata.get("granted_regen_ability"):
                permanent.regeneration_shield += 1
                self.log.append(f"{permanent.card.name} regenerates (ability granted by lord)")
                return SimulationResult(permanent.card.name, True, "activated_regenerate", "resolved")
            self.log.append(f"No implemented activated ability for {permanent.card.name}")
            return SimulationResult(permanent.card.name, False, "unsupported", "ability not implemented")

        if ability.instruction.kind == "grant_banding_to_target":
            # Helm of Chatzuk targets any creature (the chosen target_player; falls
            # back to any creature on the battlefield when no target was supplied).
            has_valid_target = any(
                perm.card.primary_type == "creature"
                for player in self.players
                for perm in player.battlefield
            )
            if not has_valid_target:
                details = "no valid creature target for banding effect"
                self.log.append("No valid creature target for banding effect")
                return SimulationResult(permanent.card.name, False, "unsupported", details)

        if ability.instruction.kind == "counter_top_stack_spell":
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
        ability_lower = (ability.source_line or permanent.card.oracle_text).lower()

        # "Activate only during your upkeep." (Cyclopean Tomb, the Clockwork
        # creatures, Rock Hydra's pump). Legal only on the controller's own upkeep.
        if "activate only during your upkeep" in ability_lower:
            if not (self.current_step == "upkeep" and self.active_player_index == controller_index):
                details = f"{permanent.card.name} can only be activated during your upkeep"
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

        # Northern Paladin: "{W}{W}, {T}: Destroy target black permanent." The
        # chosen target must satisfy the ability's color/type filter (601.2c) — an
        # illegal target makes the ability impossible to activate, so it's rejected
        # before any cost is paid rather than silently fizzling.
        if ability.instruction.kind == "destroy_target_permanent":
            color_filter = ability.instruction.payload.get("color_filter")
            type_filter = ability.instruction.payload.get("type_filter")
            # Dwarven Demolition Team / Tunnel: "Destroy target Wall." The subtype
            # filter must be enforced too — a non-Wall creature is an illegal target.
            subtype_filter = ability.instruction.payload.get("subtype_filter")
            if (color_filter or type_filter or subtype_filter) and isinstance(target_permanent_index, int):
                bf = target_player.battlefield
                legal = 0 <= target_permanent_index < len(bf)
                if legal and color_filter and color_filter not in bf[target_permanent_index].card.colors:
                    legal = False
                if legal and type_filter and type_filter not in bf[target_permanent_index].card.type_line.lower():
                    legal = False
                if legal and subtype_filter and subtype_filter not in bf[target_permanent_index].card.type_line.lower():
                    legal = False
                if not legal:
                    details = f"no valid target for {permanent.card.name}"
                    self.log.append(details)
                    return SimulationResult(permanent.card.name, False, "unsupported", details)

        required_cost = dict(ability.cost.mana)
        requires_tap = ability.cost.requires_tap
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        if x_value and "{x}" in (ability.source_line or "").lower():
            required_cost["generic"] = required_cost.get("generic", 0) + int(x_value)
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
            permanent.tapped = True

        # All guards/costs passed — mark a "once each turn" ability as used.
        if once_each_turn:
            permanent.metadata["ability_used_turn"] = self.turn

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
                target_stack_name=target_stack_item.card.name if target_stack_item is not None else None,
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

        permanent.tapped = True
        self.log.append(f"{controller.name} tapped {permanent_name}")
        return True

    def queue_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        old_color: str | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        try:
            hand_index = next(i for i, card in enumerate(caster.hand) if card.name == card_name)
        except StopIteration as exc:
            raise ValueError(f"Card not in hand: {card_name}") from exc

        card = caster.hand[hand_index]
        classification = classify_card(card)
        extra_generic_tax = 0

        if self.enforce_mana_costs and card.primary_type == "land":
            lands_played = self.lands_played_this_turn.get(caster_index, 0)
            if lands_played >= 1 and self._fastbond_count(caster_index) <= 0:
                details = "already played a land this turn"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "W" in card.colors:
            has_gloom = any(
                perm.card.name == "Gloom"
                for player in self.players
                for perm in player.battlefield
            )
            if has_gloom:
                extra_generic_tax = 3
                self.log.append(f"{card.name} is taxed by Gloom")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                from .oracle import compile_card_oracle
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        if "cast this spell only during your declare attackers step" in card.oracle_text.lower():
            if self.current_step != "declare_attackers" or self.active_player_index != caster_index:
                details = "can only be cast during your declare attackers step"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "cast this spell only during the declare blockers step" in card.oracle_text.lower():
            if self.current_turn_phase != "combat" or self.current_step != "declare_blockers":
                details = "can only be cast during the declare blockers step"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        # Blaze of Glory: "Cast this spell only during combat before blockers are
        # declared" — legal during the beginning-of-combat and declare-attackers
        # steps (while attackers may still be declared / blockers not yet declared).
        if "cast this spell only during combat before blockers are declared" in card.oracle_text.lower():
            before_blockers = (
                self.current_turn_phase == "combat"
                and self.current_step in ("beginning_of_combat", "declare_attackers")
            )
            if not before_blockers:
                details = "can only be cast during combat before blockers are declared"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        if "cast this spell only during an opponent's turn, before attackers are declared" in card.oracle_text.lower():
            if self.current_turn_phase == "combat":
                before_attackers = (
                    self.current_step in ("beginning_of_combat", "declare_attackers")
                    and not self.combat_attackers_locked
                )
            else:
                before_attackers = self.current_turn_phase in ("beginning", "precombat_main")
            if self.active_player_index == caster_index or not before_attackers:
                details = "can only be cast during an opponent's turn, before attackers are declared"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        # Resolve an explicitly chosen target spell on the stack (Counterspell,
        # Fork). target_stack_index indexes into self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]

        target_ok, target_reason = self._validate_cast_targets(
            card, caster_index, target_player_index, target_permanent_index, target_stack_item,
            mode_index=mode_index,
        )
        if not target_ok:
            self.log.append(target_reason)
            return SimulationResult(card.name, False, classification.effect_kind, target_reason)

        # Fireball-style spells cost {1} more to cast for each target beyond the
        # first. Count the chosen targets (a list of creature indices, or a
        # single creature/player) and tax the extras as generic mana.
        if "costs {1} more to cast for each target beyond the first" in card.oracle_text.lower():
            if isinstance(target_permanent_index, list):
                num_targets = len([i for i in target_permanent_index if isinstance(i, int)])
            else:
                num_targets = 1
            extra_generic_tax += max(0, num_targets - 1)

        resolved_x_value = x_value
        if resolved_x_value is None and "{X}" in card.mana_cost.upper():
            resolved_x_value = self._infer_x_value(caster, card.mana_cost, extra_generic_tax)

        if self.enforce_mana_costs and card.primary_type != "land":
            cost = self._parse_mana_cost(card.mana_cost, x_value=resolved_x_value, extra_generic=extra_generic_tax)
            if not self._pay_mana_cost(caster, cost):
                details = f"insufficient mana for {card.name}"
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        card = caster.hand.pop(hand_index)

        if card.primary_type != "land":
            # Determine which stack spell this one targets. An explicit choice
            # (target_stack_item) wins; otherwise fall back to the topmost legal
            # spell so AI and untargeted casts still work.
            target_stack_item_val = target_stack_item
            if target_stack_item_val is None and self.stack and "counter target" in card.oracle_text.lower():
                color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
                color_filter: str | None = None
                if color_match:
                    color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
                matching = [it for it in self.stack if not color_filter or color_filter in it.card.colors]
                if matching:
                    target_stack_item_val = matching[-1]
            target_stack_name_val = target_stack_item_val.card.name if target_stack_item_val is not None else None
            self.stack.append(
                StackItem(
                    card=card,
                    caster_index=caster_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    x_value=resolved_x_value,
                    target_stack_name=target_stack_name_val,
                    target_stack_item=target_stack_item_val,
                    new_color=new_color,
                    old_color=old_color,
                    chosen_mode_index=mode_index,
                )
            )
            self.log.append(f"{card.name} added to stack")
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")

    def _destroy_target_legal(self, payload: dict, perm: Permanent) -> bool:
        """Whether *perm* satisfies a ``destroy_target_permanent`` instruction's
        target filters (type/subtype/colour/tapped + exclusions). Shared by cast
        validation and the legality enumerator so a destroy ability (Royal
        Assassin's "target tapped creature", Northern Paladin's "target black
        permanent") offers exactly the permanents it can legally destroy."""
        type_filter = payload.get("type_filter")
        subtype_filter = payload.get("subtype_filter")
        color_filter = payload.get("color_filter")
        tapped_only = payload.get("tapped_only", False)
        exclude_colors = payload.get("exclude_colors") or []
        exclude_types = payload.get("exclude_types") or []

        if type_filter:
            if type_filter == "artifact_or_enchantment":
                if perm.card.primary_type not in ("artifact", "enchantment"):
                    return False
            elif type_filter not in perm.card.type_line.lower():
                return False
        if subtype_filter and subtype_filter not in perm.card.type_line.lower():
            return False
        if tapped_only and not perm.tapped:
            return False
        if color_filter and color_filter not in perm.card.colors:
            return False
        if exclude_colors and any(c in perm.card.colors for c in exclude_colors):
            return False
        if exclude_types and any(t in perm.card.type_line.lower() for t in exclude_types):
            return False
        return True

    def _validate_cast_targets(
        self,
        card: CardDefinition,
        caster_index: int,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        target_stack_item=None,
        mode_index: int | None = None,
    ) -> tuple[bool, str]:
        """Return (True, 'valid') if all required targets exist, else (False, reason).

        Only instants and sorceries execute effects at cast time; permanents enter
        the battlefield regardless of whether their activated abilities have targets.

        For a "Choose one —" modal spell, the chosen mode's instruction (not the
        first one) determines what the spell targets.
        """
        if card.primary_type not in ("instant", "sorcery"):
            # Aura spells are always targeted: a legal enchant target must be
            # chosen when the spell is cast (MTG Rules 115.1b, 601.2c)
            if "Aura" in card.type_line:
                enchant_noun = aura_enchant_noun(card)
                if enchant_noun is not None:
                    if not isinstance(target_permanent_index, int):
                        return False, f"{card.name} requires a target"
                    target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
                    if target_idx < 0 or target_idx >= len(self.players):
                        target_idx = 1 - caster_index
                    battlefield = self.players[target_idx].battlefield
                    if not (0 <= target_permanent_index < len(battlefield)) or not permanent_matches_enchant_noun(
                        battlefield[target_permanent_index], enchant_noun
                    ):
                        return False, f"no valid target for {card.name}"
                    # A permanent that "can't be enchanted by other Auras" (Consecrate
                    # Land) is an illegal target for any other Aura spell.
                    if battlefield[target_permanent_index].metadata.get("cant_be_enchanted_by_auras"):
                        return False, f"{battlefield[target_permanent_index].card.name} can't be enchanted by other Auras"
                    # CR 702.16b/c: an Aura with a quality can't be cast targeting a
                    # permanent with protection from that quality.
                    if not self._can_be_targeted(battlefield[target_permanent_index], card):
                        return False, f"no valid target for {card.name}"
                else:
                    first_line = card.oracle_text.lower().split("\n")[0].strip()
                    if first_line.startswith("enchant ") and "graveyard" in first_line:
                        # e.g. "enchant creature card in a graveyard" (Animate Dead).
                        # If the player chose a specific graveyard card, validate that
                        # choice; otherwise require at least one legal creature card.
                        if isinstance(target_permanent_index, int):
                            gy_idx = target_player_index if target_player_index is not None else caster_index
                            if gy_idx < 0 or gy_idx >= len(self.players):
                                gy_idx = caster_index
                            graveyard = self.players[gy_idx].graveyard
                            if not (0 <= target_permanent_index < len(graveyard)) or (
                                graveyard[target_permanent_index].primary_type != "creature"
                            ):
                                return False, f"no valid target for {card.name}"
                        else:
                            has_target = any(
                                c.primary_type == "creature"
                                for player in self.players
                                for c in player.graveyard
                            )
                            if not has_target:
                                return False, f"no valid target for {card.name}"
            return True, "valid"

        program = compile_card_oracle(card)
        if (
            mode_index is not None
            and program.modes
            and 0 <= mode_index < len(program.modes)
            and program.modes[mode_index].instruction is not None
        ):
            primary = program.modes[mode_index].instruction
        else:
            primary = next(
                (instr for instr in program.instructions if instr.kind != "spell_pattern"),
                None,
            )
        if primary is None:
            return True, "valid"

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        if target_idx < 0 or target_idx >= len(self.players):
            target_idx = 1 - caster_index
        target = self.players[target_idx]

        # CR 702.16b: a spell can't be cast targeting a creature with protection
        # from the spell's quality (or with shroud). Reject the illegal target at
        # cast time, mirroring the resolution-time check, so it is never offered.
        if isinstance(target_permanent_index, int) and 0 <= target_permanent_index < len(target.battlefield):
            chosen = target.battlefield[target_permanent_index]
            if chosen.card.primary_type == "creature" and not self._can_be_targeted(chosen, card):
                return False, f"{chosen.card.name} is an illegal target for {card.name}"

        if primary.kind == "destroy_target_permanent":
            if isinstance(target_permanent_index, int):
                # A specific target was chosen — it must itself be legal (601.2c).
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not self._destroy_target_legal(
                    primary.payload, battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            else:
                # No specific choice: destruction can target a permanent controlled
                # by anyone, so a legal target on the caster's own battlefield (e.g.
                # Disenchant on one's own artifact) is enough to make the cast legal.
                has_target = any(
                    self._destroy_target_legal(primary.payload, p)
                    for pl in self.players
                    for p in pl.battlefield
                )
                if not has_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind == "counter_top_stack_spell":
            color_filter = primary.payload.get("color_filter")
            if not self.stack:
                return False, f"no valid target for {card.name}"
            if target_stack_item is not None:
                # A specific spell was chosen — it must itself be a legal target.
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
                if color_filter and color_filter not in self._stack_item_colors(target_stack_item):
                    return False, f"no valid target for {card.name}"
            elif color_filter and not any(color_filter in self._stack_item_colors(item) for item in self.stack):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "bounce_target_creature":
            # "Return target creature to its owner's hand" (Unsummon) can target a
            # creature controlled by ANY player. When a specific target is chosen it
            # must itself be a creature; otherwise any creature on any battlefield
            # makes the cast legal.
            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    battlefield[target_permanent_index].card.primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                p.card.primary_type == "creature"
                for pl in self.players
                for p in pl.battlefield
            ):
                return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "pump_target_creature_until_eot",
            "grant_target_flying_until_eot",
            "grant_regeneration_to_target_creature",
            "berserk_pump",
            "grant_unlimited_blocking",
            "exile_target_creature_until_eot",
            "exile_creature_gain_life_equal_to_power",
        ):
            # These spells can target a creature controlled by ANY player (Death
            # Ward regenerates your own creature; Swords to Plowshares exiles any
            # creature). A specific choice must itself be a creature; otherwise any
            # creature on any battlefield makes the cast legal.
            blocking_only = bool(primary.payload.get("blocking_only"))

            def _legal_pump_target(p) -> bool:
                if p.card.primary_type != "creature":
                    return False
                # Righteousness only targets a creature that is currently blocking.
                if blocking_only and not self._is_blocking_creature(p):
                    return False
                return True

            if isinstance(target_permanent_index, int):
                battlefield = target.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or not _legal_pump_target(
                    battlefield[target_permanent_index]
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(
                _legal_pump_target(p)
                for pl in self.players
                for p in pl.battlefield
            ):
                return False, f"no valid target for {card.name}"

        elif primary.kind in ("tap_target_permanent", "untap_target_permanent"):
            if not target.battlefield:
                return False, f"no valid target for {card.name}"

        elif primary.kind == "recolor_target_from_text":
            # "Target spell or permanent becomes [color]" (the Lace cards). A spell
            # on the stack is a legal target, as is any permanent on any battlefield.
            if target_stack_item is not None:
                if target_stack_item not in self.stack:
                    return False, f"no valid target for {card.name}"
            else:
                any_target = bool(self.stack) or any(p.battlefield for p in self.players)
                if not any_target:
                    return False, f"no valid target for {card.name}"

        elif primary.kind in (
            "return_creature_from_graveyard_to_hand",
            "reanimate_creature_to_battlefield",
            "reanimate_creature",
        ):
            # Raise Dead / Resurrection target a creature card in *your* graveyard,
            # so an opponent's graveyard is never a legal target. Only enforce the
            # ownership/index check when the caster made an explicit graveyard pick;
            # an untargeted cast just needs a creature in the caster's graveyard.
            caster = self.players[caster_index]
            if isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                if not (0 <= target_permanent_index < len(caster.graveyard)) or (
                    caster.graveyard[target_permanent_index].primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(c.primary_type == "creature" for c in caster.graveyard):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "simulacrum_redirect":
            # Simulacrum deals damage to "target creature you control" — only a
            # creature the caster controls is a legal target. A specific choice must
            # be one of the caster's creatures (targeting an opponent's creature is
            # illegal); with no explicit choice, the caster just needs one creature.
            caster = self.players[caster_index]
            if isinstance(target_permanent_index, int):
                if target_player_index is not None and target_player_index != caster_index:
                    return False, f"no valid target for {card.name}"
                battlefield = caster.battlefield
                if not (0 <= target_permanent_index < len(battlefield)) or (
                    battlefield[target_permanent_index].card.primary_type != "creature"
                ):
                    return False, f"no valid target for {card.name}"
            elif not any(p.card.primary_type == "creature" for p in caster.battlefield):
                return False, f"no valid target for {card.name}"

        elif primary.kind == "copy_top_stack_spell":
            # Fork copies a target instant or sorcery spell, so it requires one on
            # the stack (excluding Fork itself, which isn't on the stack yet).
            if target_stack_item is not None:
                if target_stack_item not in self.stack or target_stack_item.card.primary_type not in ("instant", "sorcery"):
                    return False, f"no valid target for {card.name}"
            elif not any(item.card.primary_type in ("instant", "sorcery") for item in self.stack):
                return False, f"no valid target for {card.name}"

        return True, "valid"

    def _infer_x_value(self, player: PlayerState, mana_cost: str, extra_generic: int = 0) -> int:
        required = self._parse_mana_cost(mana_cost, x_value=0, extra_generic=extra_generic)
        temp = {symbol: player.mana_pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}

        if temp.get("W", 0) < required["W"]:
            return 0
        if temp.get("U", 0) < required["U"]:
            return 0
        if temp.get("B", 0) < required["B"]:
            return 0
        if temp.get("G", 0) < required["G"]:
            return 0
        if temp.get("C", 0) < required["C"]:
            return 0

        available_red = temp.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += temp.get("W", 0)
        if available_red < required["R"]:
            return 0

        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return 0
            if temp.get("W", 0) < red_to_pay:
                return 0
            temp["W"] -= red_to_pay

        available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
        if available_generic < required["generic"]:
            return 0

        return available_generic - required["generic"]

    def _parse_mana_cost(self, mana_cost: str, x_value: int | None, extra_generic: int = 0) -> dict[str, int]:
        required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": max(0, extra_generic)}
        if not mana_cost:
            return required

        for token in re.findall(r"\{([^}]+)\}", mana_cost.upper()):
            if token.isdigit():
                required["generic"] += int(token)
                continue
            if token == "X":
                required["generic"] += max(0, x_value or 0)
                continue
            if token in {"W", "U", "B", "R", "G", "C"}:
                required[token] += 1
        return required

    def _pay_mana_cost(self, player: PlayerState, required: dict[str, int]) -> bool:
        pool = player.mana_pool

        if pool.get("W", 0) < required["W"]:
            return False
        if pool.get("U", 0) < required["U"]:
            return False
        if pool.get("B", 0) < required["B"]:
            return False
        if pool.get("G", 0) < required["G"]:
            return False
        if pool.get("C", 0) < required["C"]:
            return False

        available_red = pool.get("R", 0)
        if player.can_spend_white_as_red:
            available_red += pool.get("W", 0)
        if available_red < required["R"]:
            return False

        temp = {symbol: pool.get(symbol, 0) for symbol in ("W", "U", "B", "R", "G", "C")}
        temp["W"] -= required["W"]
        temp["U"] -= required["U"]
        temp["B"] -= required["B"]
        temp["G"] -= required["G"]
        temp["C"] -= required["C"]

        red_to_pay = required["R"]
        from_red = min(temp.get("R", 0), red_to_pay)
        temp["R"] -= from_red
        red_to_pay -= from_red
        if red_to_pay > 0:
            if not player.can_spend_white_as_red:
                return False
            if temp.get("W", 0) < red_to_pay:
                return False
            temp["W"] -= red_to_pay

        generic = required["generic"]
        if generic > 0:
            available_generic = sum(max(0, temp.get(sym, 0)) for sym in ("C", "W", "U", "B", "R", "G"))
            if available_generic < generic:
                return False

            for sym in ("C", "W", "U", "B", "R", "G"):
                spend = min(temp.get(sym, 0), generic)
                temp[sym] -= spend
                generic -= spend
                if generic == 0:
                    break

        player.mana_pool = temp
        return True

    def _enqueue_triggered_ability(
        self,
        *,
        controller_index: int,
        source_permanent: Permanent | None = None,
        card: CardDefinition | None = None,
        instruction: OracleInstruction | None = None,
        effect_kind: str | None = None,
        ability_text: str | None = None,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        trigger_context: dict | None = None,
        hook_key: str | None = None,
        hook_event: dict | None = None,
    ) -> None:
        """Put a single triggered ability onto the stack as a StackItem (CR 603.3).

        Mirrors the attack/block trigger model (declare_attackers_step._fire_attack_triggers).
        The trigger resolves later through resolve_top_of_stack — never inline at the
        moment it fires. ``card`` defaults to the source permanent's card (used as the
        stack object's display name)."""
        stack_card = card if card is not None else (source_permanent.card if source_permanent is not None else None)
        if stack_card is None:
            return
        self.stack.append(
            StackItem(
                card=stack_card,
                caster_index=controller_index,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                x_value=None,
                ability_instruction=instruction,
                ability_effect_kind=effect_kind,
                source_permanent=source_permanent,
                ability_text=ability_text,
                trigger_context=trigger_context,
                hook_key=hook_key,
                hook_event=hook_event,
            )
        )

    def _enqueue_triggered_batch(self, events: list[dict]) -> None:
        """Put a batch of triggered abilities that fired from one event onto the stack
        in APNAP order (CR 603.3b): the active player's triggers are enqueued first
        (so they resolve last), then each other player's in turn order. Each player's
        own triggers keep their collection (battlefield-scan) order. The sort key is
        total and index-tie-broken, so enqueue order is fully seed-deterministic."""
        if not events:
            return
        n = len(self.players)
        active = self.active_player_index if self.active_player_index is not None else 0

        def _key(indexed):
            order, event = indexed
            controller = int(event["controller_index"])
            turn_distance = (controller - active) % n if n else 0
            return (turn_distance, controller, order)

        for _, event in sorted(enumerate(events), key=_key):
            self._enqueue_triggered_ability(**event)

    # Upper bound on resolve/SBA cycles in one _settle() call. A genuine infinite
    # loop (a pathological card pool) is bounded here so the seeded simulator can
    # never hang; we log and break rather than raise.
    MAX_SETTLE_ITERS = 2000

    def _settle(self) -> None:
        """Run state-based actions, then resolve the stack one item at a time,
        re-checking SBAs between each resolution (CR 704.3 + 603.3). Triggers that
        fire during an SBA check are enqueued (never resolved) there, so this loop
        is what actually drains them in the headless/AI path. Terminates when the
        stack is empty and SBAs report no further change."""
        iterations = 0
        while True:
            self.check_state_based_actions()
            if not self.stack:
                break
            self.resolve_top_of_stack()
            iterations += 1
            if iterations > self.MAX_SETTLE_ITERS:
                self.log.append(
                    f"_settle aborted after {self.MAX_SETTLE_ITERS} iterations (possible loop)"
                )
                break

    def resolve_stack(self) -> None:
        while self.stack:
            self.resolve_top_of_stack()

    def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
        """Resolve (and remove) the top stack object. Returns True if an object was
        resolved, False if the stack was empty.

        ``pause_for_choices`` is used by the human priority path (pass_priority): when
        a triggered ability resolves into an optional "you may pay {N} / draw" choice
        (Soul Net, the color Rods, Verduran Enchantress), the ability is kept on the
        stack and its pay-prompt is linked to it, so the ability stays visible on the
        stack until the player submits the prompt (CR 603.3 — the choice is made as the
        ability resolves). confirm_optional_pay / auto_resolve_pending_optional_pays
        then removes the ability from the stack. Headless/auto paths leave this False,
        so the ability resolves and pops immediately (the pending pay is auto-resolved
        by the caller, preserving deterministic behavior)."""
        if not self.stack:
            return False

        item = self.stack.pop()
        pays_before = len(self.pending_optional_pays)
        self._run_stack_item_resolution(item)
        if pause_for_choices and len(self.pending_optional_pays) > pays_before:
            # The ability raised an optional pay/draw choice — keep it on the stack
            # until the choice is submitted (the only effect so far is registering the
            # prompt; the life gain / draw happens on confirm). Link each new prompt
            # entry to this stack item so confirming it removes the ability.
            self.stack.append(item)
            for entry in self.pending_optional_pays[pays_before:]:
                entry["_stack_item"] = item
        return True

    def _run_stack_item_resolution(self, item: StackItem) -> None:
        # A triggered ability with a name-keyed resolve-time hook (Rod/Cup/Sphere,
        # Verduran Enchantress, Guardian Angel deferred onto the stack).
        if item.hook_key is not None:
            from ..card_hooks import TRIGGER_HOOKS

            handler = TRIGGER_HOOKS.get(item.hook_key)
            if handler is not None:
                handler(self, item)
                self.log.append(f"{item.card.name} ability resolved")
            return
        if item.ability_instruction is not None:
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx]
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=caster,
                    target=target,
                    card=item.card,
                    target_permanent_index=item.target_permanent_index,
                    x_value=item.x_value,
                    source_permanent=item.source_permanent,
                    stack_target=item.target_stack_item,
                    trigger_context=item.trigger_context,
                ),
            )
            supported, details = state_machine.run(item.ability_instruction)
            if supported:
                self.log.append(f"{item.card.name} ability resolved")
            else:
                self.log.append(f"{item.card.name} ability fizzled: {details}")
            return

        # A copy of an instant/sorcery (Fork) resolves like the original but is a
        # token spell: it ceases to exist afterward (no graveyard) and was never
        # cast, so it skips the cast/graveyard bookkeeping in _resolve_card.
        if item.is_copy and item.card.primary_type in ("instant", "sorcery"):
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx] if 0 <= target_idx < len(self.players) else caster
            self._apply_spell_text(
                caster,
                target,
                item.card,
                target_permanent_index=item.target_permanent_index,
                x_value=item.x_value,
                new_color=item.new_color,
                stack_target=item.target_stack_item,
                mode_index=item.chosen_mode_index,
                old_color=item.old_color,
            )
            self.log.append(f"{item.card.name} (copy) resolved")
            return

        classification = classify_card(item.card)
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            target_permanent_index=item.target_permanent_index,
            x_value=item.x_value,
            new_color=item.new_color,
            stack_target=item.target_stack_item,
            chosen_mode_index=item.chosen_mode_index,
            old_color=item.old_color,
        )
        return

    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        chosen_mode_index: int | None = None,
        old_color: str | None = None,
    ) -> None:
        caster = self.players[caster_index]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            # A "copy as it enters" permanent (Clone) records the chosen copy
            # target so initialization can copy the player-selected creature
            # rather than an arbitrary one.
            if target_permanent_index is not None:
                permanent.metadata["copy_target"] = (
                    target_player_index if target_player_index is not None else caster_index,
                    target_permanent_index,
                )
            self._put_permanent_onto_battlefield(caster_index, permanent, target_player_index)
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            self._apply_aura_effect(caster_index, permanent, target_player_index, target_permanent_index)
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and card.oracle_text.lower().split("\n")[0].strip().startswith("enchant")
                and permanent.metadata.get("attached_to") is None
            ):
                for player in self.players:
                    if permanent in player.battlefield:
                        player.battlefield.remove(permanent)
                        break
                caster.graveyard.append(card)
                self.log.append(f"{card.name} had no legal target and was put into {caster.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._apply_cast_triggers(caster_index, card)
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        fastbond_count = self._fastbond_count(caster_index)
                        if fastbond_count > 0:
                            damage = self._deal_damage_to_player(caster, fastbond_count)
                            self.log.append(f"Fastbond dealt {damage} damage to {caster.name}")
                self._process_land_enters(caster_index)
            else:
                # A resolving permanent spell (creature/artifact/enchantment) is
                # still a spell that was cast, so it triggers "whenever a player
                # casts a [color] spell" effects like the Rod/Cup/Sphere cycle.
                self._apply_spell_resolved_triggers(caster_index, card)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        self._apply_spell_text(
            caster,
            target,
            card,
            target_permanent_index=target_permanent_index,
            x_value=x_value,
            new_color=new_color,
            stack_target=stack_target,
            mode_index=chosen_mode_index,
            old_color=old_color,
        )
        self._apply_spell_resolved_triggers(caster_index, card)
        self._apply_self_resolved_hook(caster_index, card, target_idx, target_permanent_index)
        caster.graveyard.append(card)
        self.log.append(f"{card.name} resolved and moved to graveyard")

    def _select_executable_instruction(
        self, card: CardDefinition, mode_index: int | None = None
    ) -> OracleInstruction | None:
        program = compile_card_oracle(card)
        # A modal spell resolves the player's chosen mode; fall back to the first
        # instruction (mode 0) when no mode was chosen (e.g. AI casts).
        if mode_index is not None and program.modes and 0 <= mode_index < len(program.modes):
            mode = program.modes[mode_index]
            if mode.instruction is not None:
                return mode.instruction
        return next((instruction for instruction in program.instructions if instruction.kind != "spell_pattern"), None)
