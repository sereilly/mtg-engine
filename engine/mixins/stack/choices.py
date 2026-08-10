"""Choices a player has to make part-way through casting or resolving.

Each is the same shape: something *arms* a choice on ``game.pending_choices``,
an interactive seat answers it through a ``confirm_*`` method the web layer
calls, and every other seat takes the kind's recorded default. Both paths
finish through the one registered resolver, so there is a single completion
path to keep correct rather than an inline branch and a ``confirm_`` method
that must agree forever.

The registration table at the bottom of this module is the index of every
prompt in the engine: what answers it, what a non-interactive seat does
instead, and how the web layer renders, gates and refuses around it. See
``engine/pending_choices.py`` for what each field means and why the table
exists. ``tests/engine/test_pending_choices.py`` fails if a kind is armed with
no spec, or registered with a part missing.

Covered here: paying for an optional effect, discarding, sacrificing, naming a
land type, choosing a body as a permanent enters, Balance's removals, Word of
Command's borrowed turn, Kudzu's reattachment, and reordering a library.
"""

from __future__ import annotations

import random

from ...auras import attach_aura
from ...models import CardDefinition, Permanent
from ...pending_choices import CHOICE_SPECS, PendingChoice, register_choice, spec_for
from ...replacement_choices import pending_choices_for

class PendingChoicesMixin:
    # -- The queue ----------------------------------------------------------
    #
    # One list holds every decision a seat owes. ``kind`` selects the spec that
    # says how to answer it; nothing here knows what any particular prompt is.

    def arm_pending_choice(self, kind: str, player_index: int, **data) -> PendingChoice | None:
        """Queue a choice for *player_index*, or take its default now.

        Returns the queued choice, or None when the seat is not interactive and
        the kind is one whose default is taken at once (``default_at_arm``) —
        the prompts that interrupt a resolution which has to finish. Every other
        kind stays queued for every seat and is drained by
        ``auto_resolve_pending_choices``."""
        spec = spec_for(kind)
        choice = PendingChoice(kind=kind, player_index=player_index, data=dict(data))
        if spec.default_at_arm and player_index not in self.interactive_seats:
            spec.default(self, choice)
            return None
        self.pending_choices.append(choice)
        return choice

    def pending_choices_of(self, kind: str, player_index: int | None = None) -> list[PendingChoice]:
        """Queued choices of *kind*, oldest first, optionally for one seat."""
        return [
            choice
            for choice in self.pending_choices
            if choice.kind == kind
            and (player_index is None or choice.player_index == player_index)
        ]

    def pending_choice_of(self, kind: str, player_index: int | None = None) -> PendingChoice | None:
        """The oldest queued choice of *kind*, or None."""
        found = self.pending_choices_of(kind, player_index)
        return found[0] if found else None

    def discard_pending_choice(self, choice: PendingChoice) -> None:
        """Drop *choice* from the queue — the answer has been applied, or the
        thing it was about is gone. Identity, not equality: two seats can owe
        the same-looking choice."""
        self.pending_choices = [c for c in self.pending_choices if c is not choice]

    def clear_pending_choices(self, kind: str, player_index: int | None = None) -> None:
        for choice in self.pending_choices_of(kind, player_index):
            self.discard_pending_choice(choice)

    def resolve_pending_choice(self, kind: str, player_index: int, **response) -> bool:
        """Answer the oldest pending choice of *kind* owed by *player_index*.

        False means there was nothing to answer or the answer was rejected; a
        rejected answer leaves the prompt queued, so a malformed request can
        never silently drop one."""
        choice = self.pending_choice_of(kind, player_index)
        if choice is None:
            return False
        return bool(spec_for(kind).resolve(self, choice, response))

    def take_choice_default(self, choice: PendingChoice) -> None:
        """Apply the deterministic answer a non-interactive seat gives."""
        spec_for(choice.kind).default(self, choice)

    def auto_resolve_pending_choices(
        self, only_player_index: int | None = None, kinds=None
    ) -> None:
        """Take the default for queued choices — the AI / headless path.

        ``kinds`` restricts and *orders* the drain. Order is load-bearing where
        a default consumes randomness (a library search shuffles), so the
        seeded simulator names the kinds it drains rather than taking queue
        order. Draining repeats while it makes progress, because answering one
        choice can arm the next."""
        wanted = tuple(kinds) if kinds is not None else None
        for _ in range(self.MAX_SETTLE_ITERS):
            progressed = False
            for kind in wanted if wanted is not None else self._queued_kinds():
                for choice in self.pending_choices_of(kind, only_player_index):
                    self.take_choice_default(choice)
                    # Every default takes its choice off the queue; dropping it
                    # here as well is what guarantees this loop terminates even
                    # if one ever forgets.
                    self.discard_pending_choice(choice)
                    progressed = True
            if not progressed:
                return

    def iter_pending_prompts(self):
        """Every decision anyone currently owes, as ``(spec, choice)`` pairs in
        registration order.

        Spans both queues: a replacement effect suspended on a decision (CR 614)
        is a prompt like any other, and ``ReplacementChoice`` carries the same
        kind / player_index / data attributes, so nothing downstream needs to
        know which queue an entry came from."""
        for kind, spec in CHOICE_SPECS.items():
            for choice in self.pending_choices_of(kind):
                yield spec, choice
            for choice in pending_choices_for(self, kind):
                yield spec, choice

    def auto_resolve_choice(self, choice) -> None:
        """Take one queued choice's default, whichever queue it came from."""
        self.take_choice_default(choice)
        self.discard_pending_choice(choice)

    def _queued_kinds(self) -> list[str]:
        """The kinds currently queued, in first-queued order."""
        seen: list[str] = []
        for choice in self.pending_choices:
            if choice.kind not in seen:
                seen.append(choice.kind)
        return seen

    # -- Legacy views -------------------------------------------------------
    #
    # The shapes the web layer and the tests read. Each derives its seat from
    # the queued choice rather than storing it twice, so the two cannot drift.

    @property
    def pending_search_library(self) -> dict | None:
        return self._choice_view("search_library", "caster_index")

    @property
    def pending_reorder_library(self) -> dict | None:
        return self._choice_view("reorder_library", "caster_index")

    @property
    def pending_discard(self) -> dict | None:
        return self._choice_view("discard", "player_index")

    @property
    def pending_sacrifice(self) -> dict | None:
        return self._choice_view("sacrifice", "player_index")

    @property
    def pending_hand_reveal(self) -> dict | None:
        return self._choice_view("hand_reveal", "viewer_index")

    @property
    def pending_land_type_choice(self) -> dict | None:
        return self._choice_view("land_type_choice", "player_index")

    @property
    def pending_mana_payment(self) -> dict | None:
        return self._choice_view("mana_payment", "player_index")

    @property
    def pending_kudzu_reattach(self) -> dict | None:
        return self._choice_view("kudzu_reattach", "player_index")

    @property
    def pending_face_down_cast(self) -> dict | None:
        return self._choice_view("face_down_cast", "player_index")

    @property
    def pending_word_of_command(self) -> dict | None:
        return self._choice_view("word_of_command", "caster_index")

    @property
    def pending_opponent_damage(self) -> dict | None:
        return self._choice_view("opponent_damage", "chooser_index")

    @property
    def pending_enter_choice(self) -> dict | None:
        return self._choice_view("enter_choice", "controller_index")

    @property
    def pending_body_choice(self) -> dict | None:
        return self._choice_view("body_choice", "controller_index")

    @property
    def pending_least_power_choice(self) -> dict | None:
        return self._choice_view("least_power_choice", "controller_index")

    @property
    def pending_optional_pays(self) -> list[dict]:
        return [
            {**choice.data, "player_index": choice.player_index}
            for choice in self.pending_choices_of("optional_pay")
        ]

    @property
    def pending_balance(self) -> dict | None:
        """Balance is owed by several seats at once, so it is several queued
        choices; the legacy view is the plan table they add up to."""
        choices = self.pending_choices_of("balance")
        if not choices:
            return None
        return {"plans": {choice.player_index: choice.data["plan"] for choice in choices}}

    def _choice_view(self, kind: str, seat_key: str) -> dict | None:
        choice = self.pending_choice_of(kind)
        if choice is None:
            return None
        return {**choice.data, seat_key: choice.player_index}

    # -- Library search -----------------------------------------------------

    def confirm_search_library(self, caster_index: int, library_index: int) -> bool:
        return self.resolve_pending_choice(
            "search_library", caster_index, library_index=library_index
        )

    def _resolve_search_library(self, choice: PendingChoice, library_index: int) -> bool:
        caster = self.players[choice.player_index]
        if library_index < 0 or library_index >= len(caster.library):
            return False
        card = caster.library.pop(library_index)
        caster.hand.append(card)
        random.shuffle(caster.library)
        self.discard_pending_choice(choice)
        self.log.append(f"{caster.name} searched library and put {card.name} into hand")
        return True

    def _default_search_library(self, choice: PendingChoice) -> None:
        """The AI's search policy, and a shuffle-and-find-nothing when it
        declines — the library is searched either way (CR 701.19b)."""
        from ...ai_policy import choose_search_library_index

        caster = self.players[choice.player_index]
        index = choose_search_library_index(
            self, choice.player_index, card_type=choice.data.get("card_type", "any")
        )
        if index is None or not self._resolve_search_library(choice, index):
            random.shuffle(caster.library)
            self.discard_pending_choice(choice)
            self.log.append(f"{caster.name} searched their library and found nothing")

    # -- Library reorder ----------------------------------------------------

    def confirm_reorder_library(self, caster_index: int, new_order: list, shuffle: bool = False) -> bool:
        return self.resolve_pending_choice(
            "reorder_library", caster_index, new_order=new_order, shuffle=shuffle
        )

    def _resolve_reorder_library(self, choice: PendingChoice, new_order: list, shuffle: bool) -> bool:
        target = self.players[choice.data["target_index"]]
        top_count = choice.data["top_count"]
        top = target.library[:top_count]
        rest = target.library[top_count:]
        if len(new_order) != top_count or sorted(new_order) != list(range(top_count)):
            return False
        target.library = [top[i] for i in new_order] + rest
        # "You may have that player shuffle" (Natural Selection): only honored when
        # the effect allows it.
        if shuffle and choice.data.get("may_shuffle"):
            random.shuffle(target.library)
            self.log.append(f"{target.name}'s library was shuffled")
        else:
            self.log.append(f"Top {top_count} cards of {target.name}'s library reordered")
        self.discard_pending_choice(choice)
        return True

    def _default_reorder_library(self, choice: PendingChoice) -> None:
        from ...ai_policy import choose_reorder_library_order

        order = choose_reorder_library_order(
            self, choice.player_index, choice.data["target_index"], choice.data["top_count"]
        )
        if not self._resolve_reorder_library(choice, order, shuffle=False):
            self.discard_pending_choice(choice)

    # -- Discard ------------------------------------------------------------

    def confirm_discard(self, player_index: int, hand_indices: list[int], to_library: bool = False) -> bool:
        """Resolve a pending non-random discard (Disrupting Scepter) with the
        player's chosen cards. ``to_library`` puts them on top of the library
        instead of the graveyard, but only if Library of Leng allows it."""
        return self.resolve_pending_choice(
            "discard", player_index, hand_indices=hand_indices, to_library=to_library
        )

    def _resolve_discard(self, choice: PendingChoice, hand_indices: list[int], to_library: bool) -> bool:
        from ...handlers.zones import _resolve_one_discard

        count = int(choice.data["count"])
        chosen = [i for i in dict.fromkeys(hand_indices)][:count]
        if len(chosen) != count:
            return False
        # Remove in descending order so earlier indices stay valid as we pop.
        for hand_index in sorted(chosen, reverse=True):
            if not _resolve_one_discard(self, choice.player_index, hand_index, to_library):
                return False
        self.discard_pending_choice(choice)
        return True

    def _default_discard(self, choice: PendingChoice) -> None:
        """Discard the lowest-index cards, keeping them in the graveyard."""
        from ...handlers.zones import _resolve_one_discard

        for _ in range(int(choice.data["count"])):
            if not _resolve_one_discard(self, choice.player_index, 0, to_library=False):
                break
        self.discard_pending_choice(choice)

    def auto_resolve_pending_discard(self) -> None:
        """Resolve a pending discard with a default choice (the lowest-index cards,
        kept in the graveyard). Used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(kinds=("discard",))

    def confirm_leng_discard(self, player_index: int, to_library: bool) -> bool:
        """Resolve the oldest pending Library of Leng destination choice for
        *player_index*: the discarded card goes on top of their library (the
        optional CR 701.9c replacement) or into their graveyard."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_library else 1, kind="leng_discard"
        )

    # -- Phantasmal Terrain's land type -------------------------------------

    _BASIC_LAND_TYPES = ("plains", "island", "swamp", "mountain", "forest")

    def confirm_land_type(self, player_index: int, land_type: str) -> bool:
        """Resolve a pending Phantasmal Terrain choice with the controller's chosen
        basic land type, overriding the provisional default on the enchanted land."""
        return self.resolve_pending_choice("land_type_choice", player_index, land_type=land_type)

    def _resolve_land_type(self, choice: PendingChoice, land_type: str) -> bool:
        land_type = str(land_type or "").strip().lower()
        if land_type not in self._BASIC_LAND_TYPES:
            return False
        owner = self.players[choice.data["land_owner_index"]]
        idx = choice.data["land_index"]
        if 0 <= idx < len(owner.battlefield):
            land = owner.battlefield[idx]
            land.metadata["land_type_override"] = land_type
            self.log.append(
                f"{choice.data['card_name']}: enchanted land becomes a {land_type.title()}"
            )
        self.discard_pending_choice(choice)
        return True

    # -- "As this enters, choose an opponent [and a color]" -------------------

    def confirm_enter_choice(
        self, player_index: int, opponent_index: int, mana_color: str | None = None
    ) -> bool:
        """Resolve a pending "as this enters, choose an opponent [and a color]"
        prompt (Black Vise / Jihad), overwriting the provisional defaults
        stamped on the permanent at ETB."""
        return self.resolve_pending_choice(
            "enter_choice", player_index, opponent_index=opponent_index, mana_color=mana_color
        )

    def _resolve_enter_choice(
        self, choice: PendingChoice, opponent_index: int, mana_color: str | None
    ) -> bool:
        player_index = choice.player_index
        if opponent_index not in choice.data["opponents"]:
            return False
        permanent = choice.data["permanent"]
        color = None
        if choice.data["needs_color"]:
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
            self.log.append(f"{choice.data['card_name']}: {chose}")
            if color is not None:
                # Jihad's anthem is conditioned on the chosen color/player.
                self._recalculate_lord_buffs()
        self.discard_pending_choice(choice)
        self.check_state_based_actions()
        return True

    # -- Power Sink's "unless its controller pays {X}" ----------------------

    def confirm_mana_payment(self, player_index: int, pay: bool) -> bool:
        """Resolve a pending Power Sink payment (CR 701.x / "unless its controller
        pays {X}"). The targeted spell's controller pays {X} from their mana pool to
        keep their spell, or declines (or can't afford it) and the spell is countered
        with Power Sink's rider applied."""
        return self.resolve_pending_choice("mana_payment", player_index, pay=bool(pay))

    def _auto_resolve_mana_payment(self) -> None:
        """Deterministic headless/AI resolution of a pending Power Sink payment: pay
        from the controller's mana pool if able, otherwise let the spell be
        countered. Keeps seeded simulations and the headless resolve path unchanged."""
        choice = self.pending_choice_of("mana_payment")
        if choice is not None:
            self._default_mana_payment(choice)

    def _default_mana_payment(self, choice: PendingChoice) -> None:
        controller = self.players[choice.player_index]
        available = sum(controller.mana_pool.get(s, 0) for s in controller.mana_pool)
        self._resolve_mana_payment(choice, available >= int(choice.data["amount"]))

    def _resolve_mana_payment(self, choice: PendingChoice, pay: bool) -> bool:
        controller = self.players[choice.player_index]
        data = choice.data
        amount = int(data["amount"])
        target = data.get("stack_item")
        counter_card = data.get("counter_card")
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
                    self.log.append(f"{data['card_name']} countered {target.card.name} (copy), which ceases to exist")
                else:
                    controller.graveyard.append(target.card)
                    self.log.append(f"{data['card_name']} countered {target.card.name}")
                if counter_card is not None:
                    from ...card_hooks import ON_SPELL_COUNTERED
                    hook = ON_SPELL_COUNTERED.get(data["card_name"])
                    if hook is not None:
                        hook(self, counter_card, target)
        self.discard_pending_choice(choice)
        return True

    # -- Kudzu's reattachment ------------------------------------------------

    def confirm_kudzu_reattach(self, player_index: int, land_index: int) -> bool:
        """Resolve a pending Kudzu reattach by moving the detached Aura onto the
        controller's chosen land."""
        return self.resolve_pending_choice("kudzu_reattach", player_index, land_index=land_index)

    def _resolve_kudzu_reattach(self, choice: PendingChoice, land_index: int) -> bool:
        player = self.players[choice.player_index]
        if not (0 <= land_index < len(player.battlefield)):
            return False
        new_land = player.battlefield[land_index]
        if new_land.card.primary_type != "land":
            return False
        attach_aura(choice.data["aura"], new_land)
        self.log.append(f"Kudzu attached to {new_land.card.name}")
        self.discard_pending_choice(choice)
        return True

    def _default_kudzu_reattach(self, choice: PendingChoice) -> None:
        """Re-attach to the first land the controller has, deterministically."""
        player = self.players[choice.player_index]
        index = next(
            (i for i, p in enumerate(player.battlefield) if p.card.primary_type == "land"),
            None,
        )
        if index is None or not self._resolve_kudzu_reattach(choice, index):
            self.discard_pending_choice(choice)

    # -- Illusionary Mask's face-down cast -----------------------------------

    def confirm_face_down_cast(self, player_index: int, hand_index: int | None) -> bool:
        """Resolve a pending Illusionary Mask face-down cast. ``hand_index`` < 0 (or
        None) declines (the choice is "you may"). Otherwise the chosen creature card
        (mana value <= the pending max) is cast face down as a 2/2, keeping the real
        card so it can later be turned face up."""
        return self.resolve_pending_choice("face_down_cast", player_index, hand_index=hand_index)

    def _resolve_face_down_cast(self, choice: PendingChoice, hand_index: int | None) -> bool:
        player_index = choice.player_index
        player = self.players[player_index]
        if hand_index is None or hand_index < 0:
            self.discard_pending_choice(choice)
            return True
        if not (0 <= hand_index < len(player.hand)):
            return False
        creature_card = player.hand[hand_index]
        max_cmc = int(choice.data.get("max_cmc", 0))
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
        self.discard_pending_choice(choice)
        return True

    def _default_face_down_cast(self, choice: PendingChoice) -> None:
        """Cast the first eligible hand creature (mana value within X)."""
        player = self.players[choice.player_index]
        max_cmc = int(choice.data.get("max_cmc", 0))
        index = next(
            (i for i, c in enumerate(player.hand)
             if c.primary_type == "creature" and int(c.cmc or 0) <= max_cmc),
            None,
        )
        if not self._resolve_face_down_cast(choice, index if index is not None else -1):
            self.discard_pending_choice(choice)

    # -- Word of Command -----------------------------------------------------

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
        return self.resolve_pending_choice(
            "word_of_command", caster_index,
            hand_index=hand_index, defer_resolution=defer_resolution,
        )

    def _resolve_word_of_command(
        self, choice: PendingChoice, hand_index: int | None, defer_resolution: bool
    ) -> bool:
        pending = choice.data
        caster_index = choice.player_index
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
        self.discard_pending_choice(choice)
        return self._finish_word_of_command(pending, chosen, caster_index=caster_index)

    def _default_word_of_command(self, choice: PendingChoice) -> None:
        """Force the first card in the target's hand (deterministic)."""
        target = self.players[choice.data["target_index"]]
        if not self._resolve_word_of_command(
            choice, 0 if target.hand else -1, defer_resolution=False
        ):
            self.discard_pending_choice(choice)

    def _finish_word_of_command(
        self, pending: dict, hand_index: int, auto_resolve_forced: bool = True,
        caster_index: int | None = None,
    ) -> bool:
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
            spell_caster = self.players[pending.get("_spell_caster_index", caster_index or 0)]
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

    # -- Glasses of Urza's revealed hand -------------------------------------

    def dismiss_hand_reveal(self, viewer_index: int) -> bool:
        """The viewer has seen the revealed hand; take the prompt down."""
        return self.resolve_pending_choice("hand_reveal", viewer_index)

    def _dismiss_hand_reveal(self, choice: PendingChoice) -> bool:
        self.discard_pending_choice(choice)
        return True

    # -- Balance -------------------------------------------------------------

    def _balance_remove(self, player_index: int, land_indices, creature_indices, hand_indices) -> bool:
        """Remove the chosen lands/creatures (to graveyard) and hand cards (discard)
        for one player's Balance plan. Validates the counts against the plan."""
        choice = self.pending_choice_of("balance", player_index)
        if choice is None:
            return False
        return self._resolve_balance(choice, land_indices, creature_indices, hand_indices)

    def _resolve_balance(self, choice: PendingChoice, land_indices, creature_indices, hand_indices) -> bool:
        player_index = choice.player_index
        plan = choice.data["plan"]
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
        self.discard_pending_choice(choice)
        self.log.append(f"{player.name} resolved their Balance sacrifices")
        return True

    def _default_balance(self, choice: PendingChoice) -> None:
        """Keep the lowest-index permanents and cards."""
        plan = choice.data["plan"]
        player = self.players[choice.player_index]
        land_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "land"][-plan["lands"]:] if plan["lands"] else []
        creature_idx = [i for i, p in enumerate(player.battlefield) if p.card.primary_type == "creature"][-plan["creatures"]:] if plan["creatures"] else []
        hand_idx = list(range(len(player.hand)))[-plan["hand"]:] if plan["hand"] else []
        if not self._resolve_balance(choice, land_idx, creature_idx, hand_idx):
            self.discard_pending_choice(choice)

    def confirm_balance(self, player_index: int, land_indices=None, creature_indices=None, hand_indices=None) -> bool:
        """Resolve one player's Balance plan with their chosen sacrifices/discards."""
        return self.resolve_pending_choice(
            "balance", player_index,
            land_indices=land_indices, creature_indices=creature_indices, hand_indices=hand_indices,
        )

    def auto_resolve_pending_balance(self, only_player_index: int | None = None) -> None:
        """Resolve Balance plans with a default choice (keep the lowest-index
        permanents/cards). Used for AI players and headless simulation. When
        ``only_player_index`` is given, resolve just that player's plan."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("balance",))

    # -- Optional "you may pay {N}" ------------------------------------------

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

    def _pay_optional(self, player_index: int, entry: dict) -> None:
        """Spend the entry's generic mana cost (floating mana first, then by tapping
        untapped lands) from its player and gain the life if fully paid."""
        player = self.players[player_index]
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

    def _apply_optional_pay_decline(self, player_index: int, entry: dict) -> None:
        """The consequence of NOT paying an optional-pay prompt. Plain "may pay"
        riders (the color rods) have none; "unless you pay" entries (Hasran
        Ogress) carry a ``damage`` amount dealt to the player instead."""
        player = self.players[player_index]
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
        choice = next(
            (
                c for c in self.pending_choices_of("optional_pay", player_index)
                if card_name is None or c.data["card_name"] == card_name
            ),
            None,
        )
        if choice is None:
            return False
        return self._resolve_optional_pay(choice, accept)

    def _resolve_optional_pay(self, choice: PendingChoice, accept: bool) -> bool:
        player_index = choice.player_index
        entry = choice.data
        self.discard_pending_choice(choice)
        if accept and self._player_can_pay_generic(self.players[player_index], int(entry["cost"])):
            self._pay_optional(player_index, entry)
        else:
            self._apply_optional_pay_decline(player_index, entry)
        # The trigger ability that raised this prompt was held on the stack (human
        # priority path); now that the choice is made, it leaves the stack.
        self._remove_optional_pay_stack_item(entry)
        return True

    def _default_optional_pay(self, choice: PendingChoice) -> None:
        """Pay when the floating mana is already there; an unpayable "unless you
        pay" entry applies its decline consequence (Hasran Ogress' damage)."""
        entry = choice.data
        player = self.players[choice.player_index]
        available = sum(player.mana_pool.get(s, 0) for s in player.mana_pool)
        self.discard_pending_choice(choice)
        if available >= int(entry["cost"]):
            self._pay_optional(choice.player_index, entry)
        elif int(entry.get("damage", 0) or 0) > 0:
            self._apply_optional_pay_decline(choice.player_index, entry)
        self._remove_optional_pay_stack_item(entry)

    def _remove_optional_pay_stack_item(self, entry: dict) -> None:
        """Remove the triggered-ability stack object an optional-pay prompt was linked
        to, now that the prompt has been answered. No-op for entries created on the
        headless/auto path (where the ability already left the stack)."""
        stack_item = entry.get("_stack_item")
        if stack_item is not None and stack_item in self.stack:
            self.stack.remove(stack_item)

    def auto_resolve_pending_optional_pays(self, only_player_index: int | None = None) -> None:
        """Pay every pending optional "pay {N}" trigger when able — the
        deterministic default used for AI players and headless simulation."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("optional_pay",))

    # -- Forced sacrifice of the player's choice (Lich, Lord of the Pit) ---------
    #
    # A single mechanism drives every "sacrifice a permanent you choose" effect so
    # they behave uniformly. ``arm_forced_sacrifice`` either arms an interactive
    # prompt (human seat) or resolves the sacrifice inline with a deterministic
    # heuristic (AI / headless). The choice's payload is
    #   {"count", "filter", "exclude", "reason", "on_short"}
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
        A human seat is prompted to choose which; AI / headless play resolves it
        inline. Multiple calls to the same player during one step accumulate onto
        the existing prompt (e.g. two combat-damage events feeding Lich)."""
        player = self.players[player_index]
        if not self._sacrifice_candidate_indices(player, filter, exclude):
            self._apply_sacrifice_shortfall(player_index, count, on_short, reason)
            return
        queued = self.pending_choice_of("sacrifice", player_index)
        if queued is not None:
            if queued.data["filter"] == filter and queued.data["exclude"] is exclude:
                queued.data["count"] += count
            else:
                # A differently-shaped sacrifice is already owed; this one can't be
                # folded into that prompt, so it resolves inline.
                self._resolve_sacrifice_inline(player_index, count, filter, exclude, reason, on_short)
            return
        self.arm_pending_choice(
            "sacrifice", player_index,
            count=count, filter=filter, exclude=exclude, reason=reason, on_short=on_short,
        )

    def pending_sacrifice_state(self) -> dict | None:
        """The active sacrifice prompt as valid battlefield indices + count, or
        None. Used by the web layer to render/highlight the choice."""
        choice = self.pending_choice_of("sacrifice")
        if choice is None:
            return None
        return self._sacrifice_prompt(choice)

    def _sacrifice_prompt(self, choice: PendingChoice) -> dict:
        player = self.players[choice.player_index]
        valid = self._sacrifice_candidate_indices(
            player, choice.data["filter"], choice.data["exclude"]
        )
        return {
            "player_index": choice.player_index,
            "valid_indices": valid,
            "count": min(int(choice.data["count"]), len(valid)),
            "reason": choice.data["reason"],
        }

    def confirm_sacrifice(self, player_index: int, indices: list[int]) -> bool:
        """Resolve the pending forced sacrifice with the player's chosen battlefield
        indices. Requires exactly ``min(count, eligible permanents)`` distinct
        eligible permanents; if the player owed more than they could sacrifice, the
        shortfall consequence applies (Lich loses; Lord of the Pit deals damage)."""
        return self.resolve_pending_choice("sacrifice", player_index, indices=indices)

    def _resolve_sacrifice(self, choice: PendingChoice, indices: list[int]) -> bool:
        player_index = choice.player_index
        player = self.players[player_index]
        data = choice.data
        valid = self._sacrifice_candidate_indices(player, data["filter"], data["exclude"])
        count = int(data["count"])
        need = min(count, len(valid))
        chosen = list(dict.fromkeys(indices or []))
        if len(chosen) != need or any(i not in valid for i in chosen):
            return False
        reason = data["reason"]
        # Remove highest index first so the earlier indices stay valid mid-loop.
        removed: list[str] = []
        for i in sorted(chosen, reverse=True):
            perm = player.battlefield.pop(i)
            self._permanent_to_graveyard(player, perm)
            removed.append(perm.card.name)
        for name in reversed(removed):
            self.log.append(f"{player.name} sacrificed {name} ({reason})")
        self.discard_pending_choice(choice)
        if count > len(valid):
            self._apply_sacrifice_shortfall(player_index, count - len(valid), data["on_short"], reason)
        self.check_state_based_actions()
        return True

    def _default_sacrifice(self, choice: PendingChoice) -> None:
        self.discard_pending_choice(choice)
        data = choice.data
        self._resolve_sacrifice_inline(
            choice.player_index, int(data["count"]), data["filter"],
            data["exclude"], data["reason"], data["on_short"],
        )

    def auto_resolve_pending_sacrifice(self, only_player_index: int | None = None) -> None:
        """Resolve a pending forced sacrifice inline with the deterministic
        heuristic. Used for AI seats and headless simulation."""
        self.auto_resolve_pending_choices(only_player_index=only_player_index, kinds=("sacrifice",))

    # Upper bound on resolve/SBA cycles in one _settle() call. A genuine infinite
    # loop (a pathological card pool) is bounded here so the seeded simulator can
    # never hang; we log and break rather than raise.
    MAX_SETTLE_ITERS = 2000


# ---------------------------------------------------------------------------
# The prompt table
# ---------------------------------------------------------------------------
#
# One row per interactive decision in the engine. ``resolve`` applies the
# answering seat's response, ``default`` is what every other seat does, and the
# rest is what the web layer needs to render the prompt, gate the actions
# around it and route the action that answers it. A kind whose behaviour lives
# in another mixin is registered here anyway, so this stays the one index.

register_choice(
    "search_library",
    resolve=lambda game, choice, r: game._resolve_search_library(choice, r["library_index"]),
    default=lambda game, choice: game._default_search_library(choice),
    action="search_library_confirm",
    prompt_key="search_library",
    blocked_detail="complete library search before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
    # A search is armed for AI seats too and drained by the auto-resolver; the
    # prompt is rendered for whoever still owes it.
    hidden_for_ai=False,
)

register_choice(
    "reorder_library",
    resolve=lambda game, choice, r: game._resolve_reorder_library(choice, r["new_order"], r["shuffle"]),
    default=lambda game, choice: game._default_reorder_library(choice),
    action="reorder_library_confirm",
    prompt_key="reorder_library",
    blocked_detail="complete library reorder before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
)

register_choice(
    "discard",
    resolve=lambda game, choice, r: game._resolve_discard(choice, r["hand_indices"], r["to_library"]),
    default=lambda game, choice: game._default_discard(choice),
    action="discard_confirm",
    prompt_key="discard_select",
    blocked_detail="complete discard before other actions",
    blocks_every_seat=True,
    spectator_visible=True,
)

register_choice(
    "balance",
    resolve=lambda game, choice, r: game._resolve_balance(
        choice, r["land_indices"], r["creature_indices"], r["hand_indices"]
    ),
    default=lambda game, choice: game._default_balance(choice),
    action="balance_confirm",
    prompt_key="balance_select",
    blocked_detail="complete Balance sacrifices before other actions",
)

register_choice(
    "sacrifice",
    resolve=lambda game, choice, r: game._resolve_sacrifice(choice, r["indices"]),
    default=lambda game, choice: game._default_sacrifice(choice),
    action="sacrifice_confirm",
    prompt_key="sacrifice_select",
    blocked_detail="complete forced sacrifice before other actions",
    default_at_arm=True,
    spectator_visible=True,
)

register_choice(
    "optional_pay",
    resolve=lambda game, choice, r: game._resolve_optional_pay(choice, r["accept"]),
    default=lambda game, choice: game._default_optional_pay(choice),
    action="resolve_optional_pay",
    prompt_key="optional_pay",
    blocked_detail="resolve the pay-for-life trigger before other actions",
)

register_choice(
    "hand_reveal",
    resolve=lambda game, choice, r: game._dismiss_hand_reveal(choice),
    default=lambda game, choice: game._dismiss_hand_reveal(choice),
    action="dismiss_hand_reveal",
    prompt_key="hand_reveal",
    # Not a decision — the viewer has already seen the hand. Nothing waits on it.
    blocked_detail=None,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "land_type_choice",
    resolve=lambda game, choice, r: game._resolve_land_type(choice, r["land_type"]),
    # The provisional default stamped when the Aura attached is an Island, so
    # taking it again is what a non-interactive controller does.
    default=lambda game, choice: game._resolve_land_type(choice, "island"),
    action="land_type_confirm",
    prompt_key="land_type_choice",
)

register_choice(
    "mana_payment",
    resolve=lambda game, choice, r: game._resolve_mana_payment(choice, r["pay"]),
    default=lambda game, choice: game._default_mana_payment(choice),
    action="confirm_mana_payment",
    prompt_key="mana_payment",
)

register_choice(
    "kudzu_reattach",
    resolve=lambda game, choice, r: game._resolve_kudzu_reattach(choice, r["land_index"]),
    default=lambda game, choice: game._default_kudzu_reattach(choice),
    action="kudzu_reattach_confirm",
    prompt_key="kudzu_reattach",
    # Whether the controller is asked at all is the caller's ``defer_choice``,
    # not the seat's interactivity: a tap that already names the land re-attaches
    # inline. So an armed Kudzu choice queues for every seat and is drained by
    # the auto-resolver, rather than defaulting the moment it is armed.
)

register_choice(
    "face_down_cast",
    resolve=lambda game, choice, r: game._resolve_face_down_cast(choice, r["hand_index"]),
    default=lambda game, choice: game._default_face_down_cast(choice),
    action="face_down_cast_confirm",
    prompt_key="face_down_cast",
)

register_choice(
    "word_of_command",
    resolve=lambda game, choice, r: game._resolve_word_of_command(
        choice, r["hand_index"], r["defer_resolution"]
    ),
    default=lambda game, choice: game._default_word_of_command(choice),
    action="word_of_command_confirm",
    prompt_key="word_of_command",
    blocked_detail="choose the Word of Command card before other actions",
    # The caster's answer is recorded while the spell keeps waiting on the
    # stack, so the object outlives the decision it carries.
    is_open=lambda game, choice: "chosen_hand_index" not in choice.data,
)

register_choice(
    "opponent_damage",
    resolve=lambda game, choice, r: game._resolve_opponent_damage_choice(
        choice, r["target_seat"], r["target_permanent_index"]
    ),
    default=lambda game, choice: game._default_opponent_damage_choice(choice),
    action="opponent_damage_choose",
    prompt_key="opponent_damage_choice",
    blocked_detail="choose a target for the opponent-choice damage before other actions",
    default_at_arm=True,
)

register_choice(
    "enter_choice",
    resolve=lambda game, choice, r: game._resolve_enter_choice(
        choice, r["opponent_index"], r["mana_color"]
    ),
    # Black Vise / Jihad stamp their deterministic defaults on the permanent as
    # it enters, so a non-interactive controller has nothing left to apply.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="enter_choice_confirm",
    prompt_key="enter_choice",
    blocked_detail="choose an opponent (and color) for the entering permanent before other actions",
    default_at_arm=True,
)

register_choice(
    "body_choice",
    resolve=lambda game, choice, r: game._resolve_body_choice(choice, r["option_index"]),
    # Primal Clay's first printed body is applied as it enters, so the default
    # is already in place; the prompt only offers to replace it.
    default=lambda game, choice: game.discard_pending_choice(choice),
    action="body_choice_confirm",
    prompt_key="body_choice",
    blocked_detail="choose the entering creature's body before other actions",
    default_at_arm=True,
)

register_choice(
    "least_power_choice",
    resolve=lambda game, choice, r: game._resolve_least_power_choice(
        choice, r["target_seat"], r["target_permanent_index"]
    ),
    default=lambda game, choice: game._default_least_power_choice(choice),
    action="least_power_choice_confirm",
    prompt_key="least_power_choice",
    blocked_detail="choose which creature tied for least power is destroyed before other actions",
    default_at_arm=True,
)

# Replacement effects that suspend on a decision (CR 614) keep their own queue —
# see engine/replacement_choices.py — but they are prompts like any other, so
# they are described here too and the web layer treats both queues alike.
# ``ReplacementChoice`` carries the same kind / player_index / data attributes,
# which is why no adapter is needed.

def _resolve_replacement(game, choice, response) -> bool:
    return bool(game.resolve_replacement_choice(
        choice.player_index, response["option"], kind=choice.kind
    ))


def _default_replacement(game, choice) -> None:
    game.resolve_replacement_choice(
        choice.player_index, choice.default_option, kind=choice.kind
    )


register_choice(
    "leng_discard",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="leng_discard_confirm",
    prompt_key="leng_discard",
    blocked_detail="choose where the discarded card goes (Library of Leng) before other actions",
    default_at_arm=True,
    spectator_visible=True,
    hidden_for_ai=False,
)

register_choice(
    "lamp_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="lamp_draw_confirm",
    prompt_key="lamp_draw",
    blocked_detail="choose a card for Aladdin's Lamp before other actions",
    default_at_arm=True,
)

register_choice(
    "outside_game_draw",
    resolve=_resolve_replacement,
    default=_default_replacement,
    action="outside_game_draw_confirm",
    prompt_key="outside_game_draw",
    blocked_detail="choose a card from outside the game before other actions",
    default_at_arm=True,
)
