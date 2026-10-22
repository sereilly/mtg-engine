"""A spell cast, moded or aimed by a prompt.

Casts made from inside a prompt: madness's offer to cast the exiled card (CR
702.35a, during the trigger's resolution), Illusionary Mask's face-down cast,
and Word of Command's card played under the caster's control. And a spell's
announcement finished by a prompt: a mode an opponent chooses (CR 700.2e) and
the targets the caster then names for it, a new target for a spell being
re-aimed (CR 115.7), and the choice CR 707.10 gives a copy's controller.
"""

from __future__ import annotations

from ....faces import castable_faces, is_multi_face, spell_named
from ....grammar.lowering._events import EVENT_SUBJECT_PLAYER
from ....models import CardDefinition, Permanent
from ....pending_choices import PendingChoice


class SpellChoicesMixin:
    # -- A mode an opponent chooses, and its targets (CR 700.2e) --------------

    def confirm_opponent_mode_choice(self, player_index: int, mode_index: int) -> bool:
        return self.resolve_pending_choice(
            "opponent_mode_choice", player_index, mode_index=mode_index
        )

    def _resolve_opponent_mode_choice(self, choice, mode_index) -> bool:
        """CR 700.2e: record the mode the *other* player picked onto the spell
        that is already on the stack.

        Recorded rather than performed. The spell has not resolved — the cast is
        what this decision is part of (CR 601.2b) — so the answer goes onto the
        stack item exactly where an ordinary caster's announcement would have
        put it, and resolution reads one field however the mode was chosen.
        """
        from ....game_types import ChosenMode

        item = choice.data.get("_item")
        labels = choice.data.get("labels") or []
        if item is None or not isinstance(mode_index, int):
            return False
        if not 0 <= mode_index < len(labels):
            return False
        item.chosen_mode_index = mode_index
        item.chosen_modes = (ChosenMode(index=mode_index),)
        # **Who chose** is a fact about this cast that nothing on a board can
        # answer, and the mode's own text refers back to it: "…each creature
        # **that player** controls", "…deals 4 damage to **that player**"
        # (Misfortune), "**That player** draws up to three cards" (Fatal Lore).
        # Frozen here, under the key every fire site freezes a seat under, so
        # `handlers/_targets.frozen_that_player_seat` and the damage/draw
        # recipients read one answer rather than three. In a duel it happens to
        # equal the resolution's default opposing seat; with three players it
        # does not, which is why it is recorded rather than re-derived.
        item.trigger_context = {
            **(item.trigger_context or {}),
            EVENT_SUBJECT_PLAYER: choice.player_index,
        }
        self.discard_pending_choice(choice)
        self.log.append(
            f"{self.players[choice.player_index].name} chose "
            f"{labels[mode_index]!r} for {choice.data.get('card_name')}"
        )
        # CR 601.2c comes after 601.2b, and on these three cards the two steps
        # belong to different players — so the caster names the mode's targets
        # here, knowing at last which mode they are naming them for. Armed by
        # the answer, the way a chain of decisions inside one announcement is
        # (CR 601.2i: nobody has priority until the cast is finished, and both
        # prompts block every seat).
        self.arm_modal_mode_targets(item, choice.player_index)
        return True

    def _default_opponent_mode_choice(self, choice) -> None:
        """The first printed mode — a stated policy, not a valuation.

        The same answer ``mode_choice`` takes (``triggers.py``), and for its
        reason: an unanswered prompt inside an announcement would hold the cast
        open forever, and the seat that owes this one is by definition not the
        caster, so there is nobody else to ask.
        """
        if not self._resolve_opponent_mode_choice(choice, 0):
            self.discard_pending_choice(choice)

    def confirm_modal_mode_targets(self, player_index: int, permanent_ids: list) -> bool:
        """Name the targets of the mode an opponent chose. An empty list is a
        legal answer wherever the mode says "up to"."""
        return self.resolve_pending_choice(
            "modal_mode_targets", player_index, permanent_ids=permanent_ids
        )

    def _resolve_modal_mode_targets(self, choice, permanent_ids) -> bool:
        """Record the caster's targets onto the mode already on the stack.

        Checked against the list that was **offered**, never against the board:
        targets are chosen once, at announcement (CR 601.2c), so a permanent
        that became legal a moment later is not a legal answer — the rule
        ``_resolve_trigger_target`` states (``triggers.py``) and for the same
        reason.

        Validated whole before anything is recorded, which is the two
        list-shaped pickers' rule: one bad id rejects the answer and leaves the
        prompt queued, so a malformed request cannot record half an
        announcement.
        """
        from dataclasses import replace as _replace

        item = choice.data.get("_item")
        if item is None or not item.chosen_modes:
            return False
        offered = {
            entry["permanent_id"]: entry
            for entry in (choice.data.get("targets") or ())
        }
        ids = [pid for pid in (permanent_ids or []) if isinstance(pid, int)]
        if len(ids) != len(permanent_ids or []) or len(set(ids)) != len(ids):
            return False
        if len(ids) > int(choice.data.get("max_targets", 1)):
            return False
        if any(pid not in offered for pid in ids):
            return False
        mode = item.chosen_modes[0]
        seats = {offered[pid]["seat"] for pid in ids}
        item.chosen_modes = (
            _replace(
                mode,
                target_permanent_id=list(ids),
                target_permanent_index=[offered[pid]["permanent_index"] for pid in ids],
                # One seat when every target sits on one battlefield, which is
                # every card in the pool that reaches here; several leaves the
                # mode's seat alone and the ids do the addressing, which is what
                # `StackItem` records about its own pair.
                target_player_index=(
                    next(iter(seats)) if len(seats) == 1 else mode.target_player_index
                ),
            ),
        )
        self.discard_pending_choice(choice)
        names = ", ".join(offered[pid]["name"] for pid in ids) if ids else "nothing"
        self.log.append(
            f"{self.players[choice.player_index].name} targets {names} "
            f"({choice.data.get('card_name')})"
        )
        return True

    def _default_modal_mode_targets(self, choice) -> None:
        """The offered candidates in board order, up to the printed ceiling.

        A stated policy rather than a valuation, and the same one
        ``_default_permanent_set_choice`` states: seed-determinism is what AI
        and headless play need, and a card that should choose cleverly wants a
        weight in ``engine/ai_valuation.py`` rather than a branch here. There is
        no *side* to decide — the printed noun phrase already narrowed the
        candidates to one player's board — so board order is the whole policy.
        """
        offered = list(choice.data.get("targets") or ())
        ceiling = int(choice.data.get("max_targets", 1))
        ids = [entry["permanent_id"] for entry in offered[:ceiling]]
        if not self._resolve_modal_mode_targets(choice, ids):
            self.discard_pending_choice(choice)

    # -- Madness's cast offer (CR 702.35a, CR 608.2g) -------------------------

    def confirm_madness_cast(
        self, player_index: int, accept: bool, *, perform=None,
        card_name: str | None = None, outcome: list | None = None,
        **announcement,
    ) -> bool:
        """Answer the ``madness_cast`` prompt: cast the exiled card for its
        madness cost (*accept*), announced by *announcement* — the keywords
        ``queue_from_hand`` takes — or by *perform*, a callable making that
        call; or decline, which puts the card into its owner's graveyard.

        False when there is no such prompt or the engine refused the cast; the
        refusal's ``SimulationResult`` is appended to *outcome* when given. See
        ``engine/madness.py``."""
        return self.resolve_pending_choice(
            "madness_cast", player_index, accept=bool(accept), perform=perform,
            card_name=card_name, outcome=outcome, announcement=announcement,
        )

    # -- The new target of a spell being re-aimed (CR 115.7a) ----------------

    def arm_retarget_choice(
        self,
        player_index: int,
        *,
        card_name: str,
        prompt: str,
        result_key: str,
        options,
        context,
    ) -> PendingChoice | None:
        """Queue "choose the new target" for *player_index* (Deflection).

        Its own kind rather than ``player_choice`` because the candidates are
        **heterogeneous**: "Change the target of target spell with a single
        target" offers whatever that spell could legally have chosen, which for
        a Lightning Bolt is every creature *and* every face. A seat-shaped
        prompt cannot say "that Grizzly Bears", and one that could only say a
        seat would silently drop half the card.

        Answered by **position in the offered list**, the shape ``cast_choice``
        uses, because a target descriptor is not a JSON scalar and the list is
        the one thing both ends already agree on. Each option carries its
        ``permanent_id`` rather than a slot: the prompt suspends the resolution
        but the id is what survives a board that moved anyway (CR 400.7).
        """
        offered = [dict(option) for option in options]
        return self.arm_pending_choice(
            "retarget_choice", player_index,
            card_name=card_name,
            prompt=prompt,
            result_key=result_key,
            options=offered,
            names=[str(option.get("name", "")) for option in offered],
            _context=context,
        )

    def live_retarget_choices(self, choice: PendingChoice) -> list[int]:
        """The offered positions still legal to answer with (CR 800.4a).

        A face drops out when its player has left the game; an object drops out
        when it has left the battlefield. Both are re-asked here rather than
        remembered, because the whole reason this prompt exists is that the
        answer arrives later than the question.
        """
        live: list[int] = []
        for position, option in enumerate(choice.data.get("options") or ()):
            if option.get("kind") == "player":
                seat = option.get("seat")
                if isinstance(seat, int) and 0 <= seat < len(self.players) and not self.players[seat].lost:
                    live.append(position)
            elif option.get("kind") == "keep":
                # "…**may** change the target or targets": leaving them as they
                # are is one of the answers, and it cannot stop being legal.
                live.append(position)
            elif option.get("kind") == "stack":
                # "Change the target or targets" of a counterspell (Psychic
                # Battle): the candidate is another object on the stack, and it
                # is live while it is still there.
                if any(waiting is option.get("_stack_item") for waiting in self.stack):
                    live.append(position)
            elif option.get("kind") == "graveyard":
                # …and of a Raise Dead: a card in a graveyard, live while a
                # copy of it is still in that pile (``graveyard_index_of``).
                if self.graveyard_index_of(option.get("_stamp")) is not None:
                    live.append(position)
            elif self.permanent_by_id(option.get("permanent_id")) is not None:
                live.append(position)
        return live

    def _record_retarget_choice(self, choice: PendingChoice, value) -> None:
        choice.data["_context"].results[choice.data["result_key"]] = value
        self.discard_pending_choice(choice)

    def confirm_retarget_choice(self, player_index: int, target_index) -> bool:
        return self.resolve_pending_choice(
            "retarget_choice", player_index, target_index=target_index
        )

    def _resolve_retarget_choice(self, choice: PendingChoice, target_index) -> bool:
        live = self.live_retarget_choices(choice)
        if not live:
            # Everything the effect offered has gone. CR 115.7a: the original
            # target is then unchanged, which the step behind this reads off a
            # ``None`` rather than staying owed a prompt nobody can answer.
            self._record_retarget_choice(choice, None)
            return True
        if not isinstance(target_index, int) or target_index not in live:
            return False
        option = dict((choice.data.get("options") or ())[target_index])
        self._record_retarget_choice(choice, option)
        self.log.append(
            f"{choice.data.get('card_name', 'Effect')}: chose "
            f"{option.get('name', 'a new target')}"
        )
        return True

    def _default_retarget_choice(self, choice: PendingChoice) -> None:
        """The stated policy: the **first** live candidate offered, in board
        order. Deterministic rather than clever, for ``_default_player_choice``'s
        reason."""
        live = self.live_retarget_choices(choice)
        if not live or not self._resolve_retarget_choice(choice, live[0]):
            self._record_retarget_choice(choice, None)

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
        self, caster_index: int, hand_index: int | None, defer_resolution: bool = False,
        spell_name: str | None = None,
    ) -> bool:
        """Record the caster's card choice for a pending Word of Command.
        ``hand_index`` < 0 (or None) declines.

        *spell_name* is which **half** of a split card the target is to cast
        (CR 709.3: the player casting chooses, and CR 723.5 gives every choice
        the controlled player would make to the one controlling them). It is
        required for a multi-face card — a split card named whole names no
        spell, and there is no pick the engine could make that is not it
        choosing for the caster — and ignored for a card with one face.

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
            spell_name=spell_name,
        )

    def _resolve_word_of_command(
        self, choice: PendingChoice, hand_index: int | None, defer_resolution: bool,
        spell_name: str | None = None,
    ) -> bool:
        pending = choice.data
        caster_index = choice.player_index
        chosen = -1 if hand_index is None or hand_index < 0 else hand_index
        target = self.players[pending["target_index"]]
        if chosen >= 0 and chosen >= len(target.hand):
            return False
        if chosen >= 0 and is_multi_face(target.hand[chosen]):
            # CR 709.3: which half is part of the choice, and it is the
            # caster's (CR 723.5). An answer naming no half is not an answer;
            # the prompt stays up.
            if spell_named(target.hand[chosen], spell_name or "") is None:
                return False
            pending["chosen_spell_name"] = spell_name
        else:
            pending.pop("chosen_spell_name", None)
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
        # …and its first half, for a split card: the same deterministic
        # default one level down (`castable_faces` is the card itself when
        # it has one face).
        spell_name = castable_faces(target.hand[0])[0].name if target.hand else None
        if not self._resolve_word_of_command(
            choice, 0 if target.hand else -1, defer_resolution=False,
            spell_name=spell_name,
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
            self._bin_spell_card(
                spell_caster, spell_card,
                exile_instead=bool(pending.get("_spell_exile_instead")),
                verb="resolved",
            )
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
        held = target.hand[hand_index]
        # The spell the card is cast as: the half the caster named for a
        # split card (CR 709.3), the card itself otherwise. A caller that
        # finishes without a recorded half (the headless paths) gets the
        # first one, as the default answer does.
        spell = spell_named(held, pending.get("chosen_spell_name") or held.name)
        card_name = (spell or castable_faces(held)[0]).name
        result = self.queue_from_hand(target_index, card_name, target_player_index=target_index)
        if result.supported and auto_resolve_forced and self.stack:
            self.resolve_stack()
        if result.supported:
            self.log.append(f"Word of Command: {target.name} was forced to play {card_name}")
        else:
            self.log.append(f"Word of Command: {target.name} could not play {card_name} ({result.details})")
        return True

    # -- "You may choose a new target for that copy" (CR 707.10) ------------

    def arm_copy_spell_target(self, player_index: int, copy_item) -> None:
        """Offer the copy's controller the re-aiming CR 707.10 gives them.

        The candidate list is the *same* one the caster's picker would be shown
        for the card — ``derive_cast_spec`` plus ``_enumerate_targets`` — so the
        engine and the picker cannot disagree about what is a legal target; the
        answer is checked back against this list rather than against the board.

        Nothing is armed when there is nothing to change to: a card with no
        derivable target spec, or a board offering a single candidate, is a
        choice with one answer, and a prompt with one answer is a stall rather
        than a decision.
        """
        from ....legality import cast_spec_of

        # The same one question the caster's own picker asks, through the same
        # helper — so the copy is offered exactly the targets the original was.
        spec = cast_spec_of(copy_item.card)
        if spec.get("kind") in (None, "none"):
            return
        offered: list[dict] = []
        for candidate in self._enumerate_targets(
            player_index, copy_item.card, spec, for_cast=True
        ):
            if candidate.get("kind") == "player":
                seat = candidate.get("seat")
                offered.append({
                    "kind": "player",
                    "seat": seat,
                    "name": self.players[seat].name,
                })
                continue
            # An index is not an identity (CR 400.7): the offer sits on the
            # queue across a priority window, so each slot is resolved to a
            # stable id here and the id is what the answer is checked against.
            perm = self.permanent_at(candidate.get("seat"), candidate.get("index"))
            if perm is None:
                continue
            offered.append({
                "kind": "permanent",
                "seat": candidate.get("seat"),
                "index": candidate.get("index"),
                "permanent_id": self.permanent_id_of(perm),
                "name": perm.card.name,
            })
        if len(offered) < 2:
            return
        self.arm_pending_choice(
            "copy_spell_target", player_index,
            card_name=copy_item.card.name,
            targets=offered,
            _copy=copy_item,
        )

    def confirm_copy_spell_target(
        self, player_index: int, permanent_id: int | None = None,
        target_seat: int | None = None,
    ) -> bool:
        """Answer the copy's target choice with a permanent's id or a seat."""
        return self.resolve_pending_choice(
            "copy_spell_target", player_index,
            permanent_id=permanent_id, seat=target_seat,
        )

    def _resolve_copy_spell_target(self, choice: PendingChoice, response: dict) -> bool:
        """Aim the waiting copy at the answer, if the answer was offered."""
        match = self._select_trigger_mode_target(
            {"valid_targets": choice.data.get("targets") or ()}, response
        )
        copy_item = choice.data.get("_copy")
        if match is None or copy_item is None:
            return False
        from ....stack_targets import chosen_targets

        before = chosen_targets(self, copy_item)
        if match.get("kind") == "player":
            copy_item.target_player_index = match.get("seat")
            copy_item.target_permanent_index = None
            copy_item.target_permanent_id = None
            label = self.players[match["seat"]].name
        else:
            perm = self.permanent_by_id(match.get("permanent_id"))
            if perm is None:
                return False
            copy_item.target_player_index = self.controller_index_of(perm)
            copy_item.target_permanent_index = self.battlefield_index_of(perm)
            copy_item.target_permanent_id = self.permanent_id_of(perm)
            label = perm.card.name
        self.discard_pending_choice(choice)
        self.log.append(
            f"{choice.data.get('card_name', 'Copy')} (copy) targets {label}"
        )
        # CR 707.10c: "you may choose new targets for the copy". Keeping the
        # original's target is declining the offer — nothing was chosen — so
        # only an answer that moved the copy announces a choice.
        if chosen_targets(self, copy_item) != before:
            self.announce_targets_chosen(
                copy_item, chooser=choice.player_index, newly_targeted=True,
            )
        return True

    def _default_copy_spell_target(self, choice: PendingChoice) -> None:
        """The stated policy: **decline** — keep the original's target.

        Every other picker in this engine defaults to the first candidate
        offered, and each of those is a target the ability *must* have. This one
        is CR 707.10's *offer*, so it has a real decline, and declining is the
        answer that changes nothing. A copy whose original target has since
        become illegal keeps pointing at it and is countered on resolution
        (CR 608.2b), which is what declining means there too — re-aiming it at
        whatever the enumerator happened to list first would be a decision
        nobody made. A card whose copy should be aimed cleverly needs a
        valuation in `engine/ai_valuation.py`, not a branch here.
        """
        copy_item = choice.data.get("_copy")
        targets = list(choice.data.get("targets") or ())
        if copy_item is None or not targets:
            self.discard_pending_choice(choice)
            return
        from ....stack_targets import chosen_targets

        # What the copy is aimed at **now**, through the one reader of a stack
        # object's announcement. An original announced by id alone - the
        # wire's spelling, ``target_permanent_id=[id]`` with no slot - read
        # off its missing slot as a *player* target, so "keep the original"
        # re-aimed the copy of a spell pointed at a creature at that
        # creature's controller: the answer that changes nothing moved the
        # copy (Chain Lightning, 3 to the face where it had been aimed at a
        # creature).
        held_now = chosen_targets(self, copy_item) or ()
        if len(held_now) == 1 and held_now[0].kind == "permanent":
            current = {"permanent_id": held_now[0].permanent_id}
        elif copy_item.target_permanent_index is None:
            current = {"seat": copy_item.target_player_index}
        else:
            # The id is what the answer is checked against, and a cast that
            # never stamped one still has a slot — resolved through the control
            # seam rather than left as None, which would make "keep the
            # original" silently fall through to "take the first offered".
            held = copy_item.target_permanent_id
            if held is None:
                perm = self.permanent_at(
                    copy_item.target_player_index, copy_item.target_permanent_index
                )
                held = self.permanent_id_of(perm) if perm is not None else None
            current = {"permanent_id": held}
        if not self._resolve_copy_spell_target(choice, current):
            self.discard_pending_choice(choice)
