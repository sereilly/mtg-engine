"""Choices a player has to make part-way through casting or resolving.

Each is the same two-part shape: something *arms* a pending choice on the game,
an interactive seat answers it through a ``confirm_*`` method the web layer
calls, and an ``auto_resolve_pending_*`` takes the default for every seat that
is not interactive. Keeping them together is what makes that pattern visible —
they were interleaved with the casting and resolution code that arms them.

Covered here: paying for an optional effect, discarding, sacrificing, naming a
land type, choosing a body as a permanent enters, Balance's removals, Word of
Command's borrowed turn, Kudzu's reattachment, and reordering a library.
"""

from __future__ import annotations

import random

from ...auras import attach_aura
from ...models import CardDefinition, Permanent

class PendingChoicesMixin:
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
        from ...handlers.zones import _resolve_one_discard

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
    def confirm_leng_discard(self, player_index: int, to_library: bool) -> bool:
        """Resolve the oldest pending Library of Leng destination choice for
        *player_index*: the discarded card goes on top of their library (the
        optional CR 701.9c replacement) or into their graveyard."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_library else 1, kind="leng_discard"
        )
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
    def confirm_enter_choice(
        self, player_index: int, opponent_index: int, mana_color: str | None = None
    ) -> bool:
        """Resolve a pending "as this enters, choose an opponent [and a color]"
        prompt (Black Vise / Jihad), overwriting the provisional defaults
        stamped on the permanent at ETB."""
        pending = self.pending_enter_choice
        if pending is None or pending["controller_index"] != player_index:
            return False
        if opponent_index not in pending["opponents"]:
            return False
        permanent = pending["permanent"]
        color = None
        if pending["needs_color"]:
            try:
                color = self._normalize_mana_color(mana_color)
            except ValueError:
                return False
            if color is None:
                return False
        # The permanent may already be gone (e.g. destroyed at instant speed);
        # the choice then has nothing to apply to, but the prompt still clears.
        if any(perm is permanent for p in self.players for perm in p.battlefield):
            permanent.metadata["chosen_player_index"] = opponent_index
            chose = f"{self.players[player_index].name} chose {self.players[opponent_index].name}"
            if color is not None:
                permanent.metadata["chosen_color"] = color
                chose += f" and {color}"
            self.log.append(f"{pending['card_name']}: {chose}")
            if color is not None:
                # Jihad's anthem is conditioned on the chosen color/player.
                self._recalculate_lord_buffs()
        self.pending_enter_choice = None
        self.check_state_based_actions()
        return True
    def confirm_mana_payment(self, player_index: int, pay: bool) -> bool:
        """Resolve a pending Power Sink payment (CR 701.x / "unless its controller
        pays {X}"). The targeted spell's controller pays {X} from their mana pool to
        keep their spell, or declines (or can't afford it) and the spell is countered
        with Power Sink's rider applied."""
        pending = self.pending_mana_payment
        if pending is None or pending["player_index"] != player_index:
            return False
        self._resolve_mana_payment(bool(pay))
        return True
    def _auto_resolve_mana_payment(self) -> None:
        """Deterministic headless/AI resolution of a pending Power Sink payment: pay
        from the controller's mana pool if able, otherwise let the spell be
        countered. Keeps seeded simulations and the headless resolve path unchanged."""
        pending = self.pending_mana_payment
        if pending is None:
            return
        controller = self.players[pending["player_index"]]
        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
        self._resolve_mana_payment(available >= int(pending["amount"]))
    def _resolve_mana_payment(self, pay: bool) -> None:
        pending = self.pending_mana_payment
        if pending is None:
            return
        controller = self.players[pending["player_index"]]
        amount = int(pending["amount"])
        target = pending.get("stack_item")
        counter_card = pending.get("counter_card")
        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
        if pay and available >= amount:
            remaining = amount
            for sym in list(controller.mana_pool):
                while remaining > 0 and controller.mana_pool.get(sym, 0) > 0:
                    controller.mana_pool[sym] -= 1
                    remaining -= 1
            name = target.card.name if target is not None else "the spell"
            self.log.append(f"{controller.name} paid {{{amount}}}; {name} is not countered")
        else:
            # Declined or unable to pay: the spell is countered and Power Sink's rider
            # (tap all the controller's lands, drain their mana) applies.
            if target is not None and target in self.stack:
                self.stack.remove(target)
                if target.is_copy:
                    # 704.5e: a countered copy of a spell ceases to exist.
                    self.log.append(f"{pending['card_name']} countered {target.card.name} (copy), which ceases to exist")
                else:
                    controller.graveyard.append(target.card)
                    self.log.append(f"{pending['card_name']} countered {target.card.name}")
                if counter_card is not None:
                    from ...card_hooks import ON_SPELL_COUNTERED
                    hook = ON_SPELL_COUNTERED.get(pending["card_name"])
                    if hook is not None:
                        hook(self, counter_card, target)
        self.pending_mana_payment = None
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
        attach_aura(aura, new_land)
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
    def confirm_word_of_command(
        self, caster_index: int, hand_index: int | None, defer_resolution: bool = False
    ) -> bool:
        """Record the caster's card choice for a pending Word of Command.
        ``hand_index`` < 0 (or None) declines.

        With ``defer_resolution`` (the interactive priority path) the choice is
        only recorded: the spell stays on the stack and finishes resolving —
        forcing the target to play the chosen card — when priority is next
        released (resolve_top_of_stack). Headless/AI callers leave it False, so
        confirming finishes the resolution immediately.

        MVP: the forced spell defaults its target to the forced player themselves
        (so e.g. their burn/removal is turned on them). Caster-chosen targets for
        the forced spell are a future enhancement."""
        pending = self.pending_word_of_command
        if pending is None or pending["caster_index"] != caster_index:
            return False
        chosen = -1 if hand_index is None or hand_index < 0 else hand_index
        target = self.players[pending["target_index"]]
        if chosen >= 0 and chosen >= len(target.hand):
            return False
        if defer_resolution and pending.get("_stack_item") in self.stack:
            pending["chosen_hand_index"] = chosen
            if chosen >= 0:
                # The target may play cards in response before this resolves, so
                # remember the chosen card by name and re-find it at resolution.
                pending["chosen_card_name"] = target.hand[chosen].name
                self.log.append(
                    f"Word of Command: {self.players[caster_index].name} chose "
                    f"{target.hand[chosen].name}; the spell waits on the stack"
                )
            else:
                self.log.append(f"Word of Command: {self.players[caster_index].name} declined to force a card")
            # The caster just acted mid-resolution; make sure a priority window is
            # open so the spell can be responded to and then resolved by passing.
            if self.priority_player_index is None:
                self.start_priority_window(caster_index)
            return True
        self.pending_word_of_command = None
        return self._finish_word_of_command(pending, chosen)
    def _finish_word_of_command(self, pending: dict, hand_index: int, auto_resolve_forced: bool = True) -> bool:
        """Finish a Word of Command's resolution: the spell leaves the stack for
        the graveyard and the target plays the chosen card, if able.
        ``auto_resolve_forced`` immediately resolves the forced spell (headless/AI
        paths); the interactive path leaves it on the stack for a priority round."""
        target_index = pending["target_index"]
        target = self.players[target_index]
        stack_item = pending.get("_stack_item")
        if stack_item is not None and stack_item in self.stack:
            self.stack.remove(stack_item)
        spell_card = pending.get("_spell_card")
        if spell_card is not None:
            spell_caster = self.players[pending.get("_spell_caster_index", pending["caster_index"])]
            spell_caster.graveyard.append(spell_card)
            self.log.append(f"{spell_card.name} resolved and moved to graveyard")
        if hand_index < 0:
            return True  # declined — nothing is played
        chosen_name = pending.get("chosen_card_name")
        if chosen_name is not None:
            # Deferred choice: the hand may have changed since the caster chose
            # (the target could respond while the spell waited), so locate the
            # chosen card by name; if it left the hand it can't be played.
            hand_index = next(
                (i for i, c in enumerate(target.hand) if c.name == chosen_name), -1
            )
            if hand_index < 0:
                self.log.append(
                    f"Word of Command: {target.name} no longer has {chosen_name} to play"
                )
                return True
        if not (0 <= hand_index < len(target.hand)):
            return False
        card_name = target.hand[hand_index].name
        result = self.queue_from_hand(target_index, card_name, target_player_index=target_index)
        if result.supported and auto_resolve_forced and self.stack:
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
                    self.become_tapped(perm)
                    remaining -= 1
        if remaining != 0:
            return
        # A grammar-lowered "may" carries its consequence as instructions rather
        # than as one of the three fixed fields above, so any effect can sit
        # behind an optional cost.
        if self._run_optional_branch(entry, "_on_accept"):
            return
        if int(entry.get("life", 0) or 0) > 0:
            self._gain_life(player, int(entry["life"]), entry["card_name"])
    def _run_optional_branch(self, entry: dict, key: str) -> bool:
        """Execute an optional-pay entry's instruction branch, if it has one.

        Returns whether anything ran, so the legacy life/draw/damage fields stay
        the fallback for entries that predate instruction branches.
        """
        steps = entry.get(key) or ()
        context = entry.get("_context")
        if not steps or context is None:
            return False
        for step in steps:
            self._execute_oracle_instruction(step, context)
        return True
    def _apply_optional_pay_decline(self, entry: dict) -> None:
        """The consequence of NOT paying an optional-pay prompt. Plain "may pay"
        riders (the color rods) have none; "unless you pay" entries (Hasran
        Ogress) carry a ``damage`` amount dealt to the player instead."""
        player = self.players[entry["player_index"]]
        if self._run_optional_branch(entry, "_on_decline"):
            return
        damage = int(entry.get("damage", 0) or 0)
        if damage > 0:
            source = entry.get("_source_permanent")
            dealt = self._deal_damage_to_player(player, damage, source=source)
            self.log.append(f"{entry['card_name']} dealt {dealt} damage to {player.name}")
        else:
            self.log.append(f"{player.name} declined {entry['card_name']}'s pay-for-life trigger")
    def confirm_optional_pay(self, player_index: int, card_name: str | None = None, accept: bool = True) -> bool:
        """Resolve the first pending optional "pay {N}" trigger for a player (the
        color rods' gain-life riders, Hasran Ogress' pay-or-take-damage).
        ``accept`` pays it; otherwise the decline consequence (if any) applies."""
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
            self._apply_optional_pay_decline(entry)
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
        """Pay every pending optional "pay {N}" trigger when able — the
        deterministic default used for AI players and headless simulation. An
        unpayable "unless you pay" entry applies its decline consequence
        (Hasran Ogress' damage)."""
        remaining: list[dict] = []
        for entry in self.pending_optional_pays:
            if only_player_index is not None and entry["player_index"] != only_player_index:
                remaining.append(entry)
                continue
            player = self.players[entry["player_index"]]
            available = sum(player.mana_pool.get(s, 0) for s in player.mana_pool)
            if available >= int(entry["cost"]):
                self._pay_optional(entry)
            elif int(entry.get("damage", 0) or 0) > 0:
                self._apply_optional_pay_decline(entry)
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
        from ...handlers.zones import _resolve_one_discard

        pending = self.pending_discard
        if pending is None:
            return
        player_index = pending["player_index"]
        count = int(pending["count"])
        for _ in range(count):
            if not _resolve_one_discard(self, player_index, 0, to_library=False):
                break
        self.pending_discard = None
    # -- Forced sacrifice of the player's choice (Lich, Lord of the Pit) ---------
    #
    # A single mechanism drives every "sacrifice a permanent you choose" effect so
    # they behave uniformly. ``arm_forced_sacrifice`` either arms an interactive
    # prompt (human seat) or resolves the sacrifice inline with a deterministic
    # heuristic (AI / headless). ``pending_sacrifice`` shape:
    #   {"player_index", "count", "filter", "exclude", "reason", "on_short"}
    # where ``filter`` is "nontoken" or "creature", ``exclude`` is a Permanent that
    # can't be chosen (Lord of the Pit excludes itself), and ``on_short`` is the
    # effect applied when the player owes more sacrifices than they can make
    # (None, {"kind": "lose"}, or {"kind": "damage", "amount": N}).

    def _sacrifice_candidate_indices(self, player, filter: str, exclude=None) -> list[int]:
        """Battlefield indices of ``player``'s permanents eligible for a forced
        sacrifice under ``filter`` (excluding ``exclude`` if given)."""
        out: list[int] = []
        for i, perm in enumerate(player.battlefield):
            if exclude is not None and perm is exclude:
                continue
            if filter == "nontoken" and perm.metadata.get("is_token", False):
                continue
            if filter == "creature" and perm.card.primary_type != "creature":
                continue
            out.append(i)
        return out
    def _apply_sacrifice_shortfall(self, player_index: int, owed: int, on_short, reason: str) -> None:
        """Apply the consequence for a player who can't sacrifice all they owe."""
        if not on_short or owed <= 0:
            return
        player = self.players[player_index]
        if on_short.get("kind") == "lose":
            player.lost = True
            self.log.append(
                f"{player.name} couldn't sacrifice a nontoken permanent and lost the game ({reason})"
            )
        elif on_short.get("kind") == "damage":
            dealt = self._deal_damage_to_player(player, int(on_short.get("amount", 0)))
            self.log.append(f"{reason} dealt {dealt} damage to {player.name}")
    def _resolve_sacrifice_inline(self, player_index: int, count: int, filter: str, exclude, reason: str, on_short) -> None:
        """Sacrifice ``count`` of the player's permanents with the deterministic
        heuristic (permanents whose death loses the game are kept for last)."""
        player = self.players[player_index]
        for _ in range(count):
            valid = self._sacrifice_candidate_indices(player, filter, exclude)
            if not valid:
                self._apply_sacrifice_shortfall(player_index, 1, on_short, reason)
                return
            idx = min(
                valid,
                key=lambda i: "you lose the game" in player.battlefield[i].card.oracle_text.lower(),
            )
            perm = player.battlefield.pop(idx)
            self._permanent_to_graveyard(player, perm)
            self.log.append(f"{player.name} sacrificed {perm.card.name} ({reason})")
    def arm_forced_sacrifice(
        self,
        player_index: int,
        count: int,
        *,
        filter: str = "nontoken",
        exclude=None,
        reason: str = "Sacrifice",
        on_short=None,
    ) -> None:
        """Force a player to sacrifice ``count`` permanents matching ``filter``.
        A human seat is prompted to choose which (``pending_sacrifice``); AI /
        headless play resolves it inline. Multiple calls to the same player during
        one step accumulate onto the existing prompt (e.g. two combat-damage
        events feeding Lich)."""
        player = self.players[player_index]
        valid = self._sacrifice_candidate_indices(player, filter, exclude)
        if not valid:
            self._apply_sacrifice_shortfall(player_index, count, on_short, reason)
            return
        if player_index in self.interactive_seats and (
            self.pending_sacrifice is None
            or (
                self.pending_sacrifice.get("player_index") == player_index
                and self.pending_sacrifice.get("filter", "nontoken") == filter
                and self.pending_sacrifice.get("exclude") is exclude
            )
        ):
            if self.pending_sacrifice is not None:
                self.pending_sacrifice["count"] += count
            else:
                self.pending_sacrifice = {
                    "player_index": player_index,
                    "count": count,
                    "filter": filter,
                    "exclude": exclude,
                    "reason": reason,
                    "on_short": on_short,
                }
            return
        self._resolve_sacrifice_inline(player_index, count, filter, exclude, reason, on_short)
    def pending_sacrifice_state(self) -> dict | None:
        """The active sacrifice prompt as valid battlefield indices + count, or
        None. Used by the web layer to render/highlight the choice."""
        pending = self.pending_sacrifice
        if pending is None:
            return None
        player = self.players[pending["player_index"]]
        valid = self._sacrifice_candidate_indices(
            player, pending.get("filter", "nontoken"), pending.get("exclude")
        )
        return {
            "player_index": pending["player_index"],
            "valid_indices": valid,
            "count": min(int(pending["count"]), len(valid)),
            "reason": pending.get("reason", "Sacrifice"),
        }
    def confirm_sacrifice(self, player_index: int, indices: list[int]) -> bool:
        """Resolve the pending forced sacrifice with the player's chosen battlefield
        indices. Requires exactly ``min(count, eligible permanents)`` distinct
        eligible permanents; if the player owed more than they could sacrifice, the
        shortfall consequence applies (Lich loses; Lord of the Pit deals damage)."""
        pending = self.pending_sacrifice
        if pending is None or pending.get("player_index") != player_index:
            return False
        player = self.players[player_index]
        filter = pending.get("filter", "nontoken")
        exclude = pending.get("exclude")
        valid = self._sacrifice_candidate_indices(player, filter, exclude)
        count = int(pending["count"])
        need = min(count, len(valid))
        chosen = list(dict.fromkeys(indices or []))
        if len(chosen) != need or any(i not in valid for i in chosen):
            return False
        reason = pending.get("reason", "sacrifice")
        # Remove highest index first so the earlier indices stay valid mid-loop.
        removed: list[str] = []
        for i in sorted(chosen, reverse=True):
            perm = player.battlefield.pop(i)
            self._permanent_to_graveyard(player, perm)
            removed.append(perm.card.name)
        for name in reversed(removed):
            self.log.append(f"{player.name} sacrificed {name} ({reason})")
        self.pending_sacrifice = None
        if count > len(valid):
            self._apply_sacrifice_shortfall(player_index, count - len(valid), pending.get("on_short"), reason)
        self.check_state_based_actions()
        return True
    def auto_resolve_pending_sacrifice(self, only_player_index: int | None = None) -> None:
        """Resolve a pending forced sacrifice inline with the deterministic
        heuristic. Used for AI seats and headless simulation."""
        pending = self.pending_sacrifice
        if pending is None:
            return
        player_index = pending["player_index"]
        if only_player_index is not None and player_index != only_player_index:
            return
        self.pending_sacrifice = None
        self._resolve_sacrifice_inline(
            player_index,
            int(pending["count"]),
            pending.get("filter", "nontoken"),
            pending.get("exclude"),
            pending.get("reason", "sacrifice"),
            pending.get("on_short"),
        )
        self.check_state_based_actions()
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
    # Upper bound on resolve/SBA cycles in one _settle() call. A genuine infinite
    # loop (a pathological card pool) is bounded here so the seeded simulator can
    # never hang; we log and break rather than raise.
    MAX_SETTLE_ITERS = 2000
