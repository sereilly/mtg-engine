"""Answers to the offers the replacement machinery makes, and CR 616.1e's order.

A replacement effect that suspends on a decision (CR 614) keeps its own queue,
``engine/replacement_choices.py``. Each ``confirm_*`` here is the web layer's
way of answering the oldest such offer a seat owes — a commander's return to
the command zone, "you may have that damage dealt to you instead", an entry's
discard toll, and the draw replacements — by turning a yes/no or an index into
the option the interceptor offered. Which option a seat nobody asks takes is
the interceptor's to say, not this module's.

Every one of them is answered through ``resolve_replacement_choice`` - the
oldest offer of a kind a seat owes, applied inside the draw that armed it when
a draw did (``answering_draw_prompt``, CR 121.2) - and
``auto_resolve_pending_replacement_choices`` takes every default for a seat
that stops being interactive. The ``pending_*`` properties are views over the
queue in the shapes the web layer reads. They were ``EffectsMixin``'s until the
2,000-line split moved them here, the module whose subject they are.

Beside them, the one ``pending_choices`` kind the replacement and prevention
machinery arms itself: when several effects would modify one event, which
applies first (CR 616.1e, armed by ``engine/effect_ordering.py``).
"""

from __future__ import annotations

from ....pending_choices import PendingChoice
from ....replacement_choices import pending_choices_for, resolve_choice


class ReplacementChoicesMixin:
    # ------------------------------------------------------------------
    # Suspended replacement choices (engine/replacement_choices.py)
    # ------------------------------------------------------------------

    def resolve_replacement_choice(
        self, player_index: int, option_index: int, kind: str | None = None
    ) -> bool:
        """Answer the oldest replacement choice queued for *player_index*
        (optionally of one *kind*) with the chosen option.

        Returns False when there is no such choice or the option is out of
        range, so a stale or malformed client answer is rejected rather than
        applied to whatever happens to be queued.
        """
        entry = next(
            (
                (i, choice)
                for i, choice in enumerate(self.pending_replacement_choices)
                if choice.player_index == player_index
                and (kind is None or choice.kind == kind)
            ),
            None,
        )
        if entry is None:
            return False
        index, choice = entry
        if not (0 <= option_index < len(choice.options)):
            return False
        self.pending_replacement_choices.pop(index)
        # Inside the draw it belongs to, when a draw armed it: what the answer
        # arms is that draw's too, and the draws parked behind it are released
        # once it is applied (CR 121.2, ``answering_draw_prompt``).
        with self.answering_draw_prompt(choice):
            resolve_choice(self, choice, option_index)
        return True

    def auto_resolve_pending_replacement_choices(self) -> None:
        """Take the default on every queued choice (safety net for a seat that
        stops being interactive, e.g. a human seat handed to the AI)."""
        while self.pending_replacement_choices:
            choice = self.pending_replacement_choices[0]
            self.resolve_replacement_choice(
                choice.player_index, choice.default_option, kind=choice.kind
            )

    # Compatibility views over the queue, in the shapes the web layer and its
    # tests already read. The state itself is generic; these only name the three
    # prompts it currently carries.

    @property
    def pending_lamp_draw(self) -> dict | None:
        choices = pending_choices_for(self, "lamp_draw")
        if not choices:
            return None
        choice = choices[0]
        return {
            "player_index": choice.player_index,
            "card_names": list(choice.options),
            "remaining_draws": choice.data.get("remaining_draws", 0),
        }

    @property
    def pending_outside_game_draw(self) -> dict | None:
        choices = pending_choices_for(self, "outside_game_draw")
        if not choices:
            return None
        choice = choices[0]
        return {
            "player_index": choice.player_index,
            "card_names": list(choice.options),
            "sideboard_indices": choice.data.get("sideboard_indices"),
            "remaining_draws": choice.data.get("remaining_draws", 0),
        }

    @property
    def pending_commander_zone_changes(self) -> list[dict]:
        """CR 903.9's outstanding offers, oldest first — one per commander
        waiting on its owner's "command zone or not?"."""
        return [
            {
                "player_index": choice.player_index,
                "card": choice.data["card"],
                "destination": choice.data["destination"],
                "rule": choice.data["rule"],
            }
            for choice in pending_choices_for(self, "commander_zone_change")
        ]

    @property
    def pending_entry_discard_tolls(self) -> list[dict]:
        """Mox Diamond's outstanding CR 614.1a offers - one per permanent whose
        entry is waiting on the choice."""
        return [
            {
                "player_index": choice.player_index,
                "card_name": choice.data["permanent"].card.name,
                "hand_indices": list(choice.data.get("hand_indices") or []),
            }
            for choice in pending_choices_for(self, "entry_discard_toll")
        ]

    @property
    def pending_draw_becomes_counters(self) -> list[dict]:
        """Pursuit of Knowledge's outstanding CR 614.1 offers - one per draw a
        permanent whose text prints the substitution would replace."""
        return [
            {
                "player_index": choice.player_index,
                "counter": choice.data["counter"],
                "source_id": choice.data["source_id"],
            }
            for choice in pending_choices_for(self, "draw_becomes_counter")
        ]

    @property
    def pending_reveal_until_kind_draws(self) -> list[dict]:
        """Abundance's outstanding CR 614.1 offers - one per draw a permanent
        whose text prints the substitution would replace.

        Beside ``pending_draw_becomes_counters`` above and shaped like it: the
        offer is per *draw*, so a seven-card draw queues seven of them and the
        client answers one at a time."""
        return [
            {
                "player_index": choice.player_index,
                "options": list(choice.options),
                "source_id": choice.data["source_id"],
            }
            for choice in pending_choices_for(self, "reveal_until_kind_draw")
        ]

    @property
    def pending_skip_draws(self) -> list[dict]:
        """Obstinate Familiar's outstanding CR 614.1 offers - one per draw a
        permanent printing "you may skip that draw instead" would replace.
        Shaped like the two views above."""
        return [
            {
                "player_index": choice.player_index,
                "options": list(choice.options),
                "source_id": choice.data["source_id"],
            }
            for choice in pending_choices_for(self, "skip_draw")
        ]

    @property
    def pending_optional_damage_redirects(self) -> list[dict]:
        """CR 614.9's outstanding optional offers — one per damage event whose
        recipient a class-scoped redirect watches (Blood of the Martyr)."""
        return [
            {
                "player_index": choice.player_index,
                "amount": choice.data["amount"],
                "from_name": choice.data["from_name"],
            }
            for choice in pending_choices_for(self, "optional_damage_redirect")
        ]

    @property
    def pending_leng_discards(self) -> list[dict]:
        return [
            {"player_index": choice.player_index, "card": choice.data["card"]}
            for choice in pending_choices_for(self, "leng_discard")
        ]

    def confirm_outside_game_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Ring of Ma'rûf choice with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        return self.resolve_replacement_choice(
            player_index, chosen_index, kind="outside_game_draw"
        )

    def confirm_lamp_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Aladdin's Lamp draw with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        return self.resolve_replacement_choice(player_index, chosen_index, kind="lamp_draw")

    # -- Answering a replacement suspended on a decision (CR 614) -------------

    def confirm_commander_zone_change(self, player_index: int, to_command_zone: bool) -> bool:
        """Resolve the oldest pending CR 903.9 offer for *player_index*: the
        commander goes into the command zone, or on to where it was headed."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_command_zone else 1, kind="commander_zone_change"
        )

    def confirm_optional_damage_redirect(
        self, player_index: int, take_the_damage: bool
    ) -> bool:
        """Resolve the oldest pending CR 614.9 "you may have that damage dealt
        to you instead" offer for *player_index*."""
        return self.resolve_replacement_choice(
            player_index, 0 if take_the_damage else 1, kind="optional_damage_redirect"
        )

    def confirm_entry_discard_toll(
        self, player_index: int, hand_index: int | None = None
    ) -> bool:
        """Resolve the oldest pending "you may discard a card instead" entry
        offer for *player_index* (Mox Diamond).

        *hand_index* is a slot in the player's own hand; the offer lists only
        the slots the printed phrase admits, so an index outside them declines
        - which is the same answer ``None`` gives.
        """
        choice = next(
            (
                pending
                for pending in pending_choices_for(self, "entry_discard_toll")
                if pending.player_index == player_index
            ),
            None,
        )
        if choice is None:
            return False
        indices = list(choice.data.get("hand_indices") or [])
        option = (
            indices.index(hand_index)
            if hand_index is not None and hand_index in indices
            else len(indices)
        )
        return self.resolve_replacement_choice(
            player_index, option, kind="entry_discard_toll"
        )

    def confirm_draw_becomes_counter(
        self, player_index: int, take_the_counter: bool
    ) -> bool:
        """Resolve the oldest pending "you may put a counter on this instead of
        drawing" offer for *player_index* (Pursuit of Knowledge).

        Index 0 is the draw, which is the default a non-interactive seat takes
        - see the interceptor for why that is the choice a player would make.
        """
        return self.resolve_replacement_choice(
            player_index, 1 if take_the_counter else 0, kind="draw_becomes_counter"
        )

    def confirm_reveal_until_kind_draw(
        self, player_index: int, option_index: int
    ) -> bool:
        """Resolve the oldest pending Abundance offer for *player_index*.

        The answer is an index into the offered options ("Nonland", "Land",
        "Draw a card") rather than a boolean, because the sentence asks two
        things at once - whether to replace the draw, and which kind to reveal
        until - and CR 614.1 makes them one announcement.
        """
        return self.resolve_replacement_choice(
            player_index, int(option_index), kind="reveal_until_kind_draw"
        )

    def confirm_skip_draw(self, player_index: int, skip: bool) -> bool:
        """Resolve the oldest pending "you may skip that draw instead" offer
        for *player_index* (Obstinate Familiar).

        Index 0 is the draw and index 1 the skip, the order the interceptor
        offers them in; which of the two a non-interactive seat takes is the
        interceptor's to say (it depends on whether there is a card to draw).
        """
        return self.resolve_replacement_choice(
            player_index, 1 if skip else 0, kind="skip_draw"
        )

    def confirm_leng_discard(self, player_index: int, to_library: bool) -> bool:
        """Resolve the oldest pending Library of Leng destination choice for
        *player_index*: the discarded card goes on top of their library (the
        optional CR 701.9c replacement) or into their graveyard."""
        return self.resolve_replacement_choice(
            player_index, 0 if to_library else 1, kind="leng_discard"
        )

    # ------------------------------------------------------------------
    # CR 616.1e — which of several applicable effects applies first
    # ------------------------------------------------------------------

    def _record_effect_order(self, choice: PendingChoice, option_index: int) -> None:
        """Store the picked effect ahead of the rest, in their default order.

        The answer is one pick, not a full ordering, because that is all CR
        616.1e needs from the player each round — but the process may reach a
        second contended round on its way through, and by then it is past the
        point where it can ask again. Recording the pick *followed by* the
        default order gives every later round an answer that is consistent with
        the one the player gave.
        """
        keys = list(choice.data["_keys"])
        picked = keys[option_index]
        self.effect_order_answers[(choice.data["event_kind"], choice.player_index)] = tuple(
            [picked] + [key for key in keys if key != picked]
        )

    def _resolve_effect_order(self, choice: PendingChoice, option_index: int) -> bool:
        keys = choice.data["_keys"]
        if not (0 <= option_index < len(keys)):
            return False
        self.discard_pending_choice(choice)
        self._record_effect_order(choice, option_index)
        self.log.append(
            f"{self.players[choice.player_index].name} applies "
            f"{choice.data['options'][option_index]} first"
        )
        # Nothing was applied when the prompt was armed, so the event is re-run
        # rather than resumed — and it reaches the same round, finds the
        # recorded answer, and carries on. The suspension was lifted by
        # ``resolve_pending_choice`` before this ran (the kind is ``suspends``),
        # and the loops waiting on the event are unwound by it afterwards.
        choice.data["_restart"]()
        return True

    def _default_effect_order(self, choice: PendingChoice) -> None:
        """The documented default (the first option, which the asker listed in
        default order). Reached when a seat stops being interactive with the
        prompt still queued."""
        self._resolve_effect_order(choice, 0)
