"""A triggered ability's order, targets and mode, chosen as it is put on the stack.

CR 603.3b: a seat orders the triggers it puts on the stack together
(``engine/trigger_order.py`` arms the prompt when its window closes). CR
603.3c-d: a triggered ability's mode and targets are announced as it goes on
the stack, so a prompt answers them — one target, several, a division, a card
in a graveyard — and the answer is checked against the list that was offered,
never against the board. The defaults a seat nobody asks takes are here too,
with the side of the table each aims at.
"""

from __future__ import annotations

from .... import piles
from ....pending_choices import PendingChoice
from ....trigger_order import ORDER_TRIGGERS, apply_trigger_order


class TriggerChoicesMixin:
    # -- A triggered ability's "Choose one —" (CR 603.3c) ---------------------

    def _resolve_mode_choice(
        self, choice: PendingChoice, mode_index: int, target: dict | None = None,
    ) -> bool:
        """Answer a "Choose one —" prompt with the *mode_index*'th offered mode.

        Two arming sites, one answer, and the difference between them is
        **when** rather than what:

        * A **modal triggered ability** (Relic Bind, Trufflesnout, Elder
          Gargaroth) is armed by ``_choose_trigger_mode`` as the ability is put
          on the stack, which is where CR 700.2b and CR 603.3c/603.3d put the
          choice. The answer — the mode *and*, per CR 601.2c, its target — is
          recorded onto that stack object; the ability resolves later, as an
          ability with a mode and a target already chosen.
        * A ``choose_one`` **nested inside a larger effect** ("that creature
          gains flying or first strike") is not a modal ability at all: the
          alternatives are a step of a resolution that is already running, so
          the chosen branch runs against the context it was armed with.

        ``_trigger_item`` is which of the two, and it is on the prompt rather
        than in a list of kinds here for the reason every registry in this
        engine exists: a second arming site added later says which one it is by
        the data it arms with.

        An index outside the offered list is refused and the prompt stays owed,
        the optional-pay shape. So is a mode that needs a target with no legal
        target named — CR 601.2c chooses the targets as part of the same
        announcement, and a mode announced without them was never legally
        chosen.
        """
        item = choice.data.get("_trigger_item")
        options = tuple(choice.data.get("_options") or ())
        legacy_modes = tuple(choice.data.get("_modes") or ())
        count = len(options) if item is not None else len(legacy_modes)
        if not 0 <= mode_index < count:
            return False
        labels = choice.data.get("labels") or ()
        label = labels[mode_index] if 0 <= mode_index < len(labels) else "a mode"
        card_name = choice.data.get("card_name", "Ability")
        if item is None:
            context = choice.data.get("_context")
            if context is None:
                return False
            self.discard_pending_choice(choice)
            self.log.append(f'{card_name}: chose "{label}"')
            self._execute_oracle_instruction(legacy_modes[mode_index], context)
            self.check_state_based_actions()
            return True
        option = options[mode_index]
        queued = self._choice_is_queued(choice)
        if option["spec"].get("requires_target") and not choice.data.get("_keep_targets"):
            target = (
                self._select_trigger_mode_target(option, target) if target is not None
                else self._default_trigger_mode_target(option, choice.player_index)
            )
            if target is None:
                return False
        else:
            target = None
        self.discard_pending_choice(choice)
        item.chosen_mode_index = option["index"]
        if target is not None:
            item.target_player_index = target.get("seat")
            if target.get("kind") == "permanent":
                item.target_permanent_index = target.get("index")
                item.target_permanent_id = self.permanent_ids_at(
                    target.get("seat"), target.get("index")
                )
            else:
                item.target_permanent_index = None
                item.target_permanent_id = None
        chosen_for = ""
        if target is not None:
            chosen_for = (
                f" targeting {target['name']}" if target.get("kind") == "permanent"
                else f" targeting {self.players[target['seat']].name}"
            )
        self.log.append(f'{card_name}: chose "{label}"{chosen_for}')
        # CR 700.2b / CR 603.3d: the mode and its targets are one announcement,
        # and this answer is the moment it is complete. A copy keeps the
        # targets it inherited (``_keep_targets``, CR 707.10) and chose none.
        if not choice.data.get("_keep_targets"):
            self._announce_answered_targets(item, choice, queued)
        return True

    # -- CR 603.3b: the order a seat puts its simultaneous triggers on in ----
    #
    # Armed by ``engine/trigger_order.offer_trigger_order`` when a window
    # (``putting_triggers_on_stack``) closes; see that module for what a
    # window is and why the objects are already on the stack.

    def confirm_order_triggers(self, player_index: int, order: list) -> bool:
        """Answer an ``order_triggers`` prompt: *order* lists the offered
        triggers by index, **the first to resolve first**."""
        return self.resolve_pending_choice(
            ORDER_TRIGGERS, player_index, order=list(order or ()),
        )

    def _resolve_order_triggers(self, choice: PendingChoice, order) -> bool:
        if not apply_trigger_order(self, choice, order):
            return False
        self.discard_pending_choice(choice)
        offered = list(choice.data.get("triggers") or ())

        def _label(entry: dict) -> str:
            text = entry.get("text") or ""
            if len(text) > 48:
                text = text[:47].rstrip() + "…"
            return f"{entry['card_name']} ({text})" if text else entry["card_name"]

        chosen = [_label(offered[int(index)]) for index in order]
        self.log.append(
            f"{self.players[choice.player_index].name} ordered their triggered "
            f"abilities (603.3b), first to resolve first: {'; '.join(chosen)}"
        )
        return True

    def _default_order_triggers(self, choice: PendingChoice) -> None:
        """The order the fire sites pushed them in, which is the order every
        game had before anybody was asked — so a seat nobody asks plays
        exactly as it did. Nothing moves and nothing is logged."""
        self.discard_pending_choice(choice)

    def confirm_trigger_target(
        self, player_index: int, permanent_id: int | None = None,
        seat: int | None = None, permanent_ids: list[int] | None = None,
        graveyard_index: int | None = None,
        stack_item=None,
        amounts: list[int] | None = None,
        graveyard_indices: list[int] | None = None,
    ) -> bool:
        """Answer a triggered ability's target choice.

        An object is named by its stable id and a player by their seat index,
        which is the shape every other mixed picker in this engine takes
        (``_select_trigger_mode_target`` one method down reads exactly these two
        keys). One of the two, never both: an answer carrying an id is about a
        permanent whatever seat it sits on.

        *permanent_ids* is the answer for an ability that prints **several**
        targets ("up to two target creatures"): every object named at once,
        because CR 601.2c makes them one announcement. An empty list names
        nobody, which an "up to" allows.

        *graveyard_index* with *seat* is a **card in a graveyard**: which pile
        and which slot of it, as the prompt listed them. A graveyard card has
        no id to be named by. *graveyard_indices* with *seat* is **several**
        of them out of that one pile ("exile up to two target cards from a
        single graveyard", Gravegouger) — one announcement, as
        *permanent_ids* is for objects.

        *stack_item* is the answer for an ability whose target is a **spell**
        ("When this creature enters, counter target spell", Mystic Snake): the
        stack object itself, because a spell has no id and its position is only
        true until the stack next moves. The wire names it by position
        (``trigger_target_stack_item``) and this is what that resolves to.

        *amounts* is CR 601.2d's division for a prompt armed with a
        ``division_total`` ("distribute three -1/-1 counters among one, two,
        or three target creatures", Shambling Swarm): one share per id in
        *permanent_ids*, in the same order. It may be left out only where the
        division is forced — one target takes the whole total, and as many
        targets as the total take one apiece — or where the game divides
        evenly.
        """
        return self.resolve_pending_choice(
            "trigger_target", player_index, permanent_id=permanent_id, seat=seat,
            permanent_ids=permanent_ids, graveyard_index=graveyard_index,
            stack_item=stack_item, amounts=amounts,
            graveyard_indices=graveyard_indices,
        )

    def trigger_target_stack_item(self, player_index: int, top_first_index: int):
        """The stack object *player_index*'s pending ``trigger_target`` prompt
        offers at *top_first_index* — the position a client sees it at, topmost
        being 0 — or None when the prompt offers no spell there.

        Resolved against the prompt's own candidates and never against the
        stack alone, so a position naming a spell the picker did not offer is
        no answer at all rather than a counter aimed at something the printed
        phrase excludes.
        """
        choice = self.pending_choice_of("trigger_target", player_index)
        if choice is None or not isinstance(top_first_index, int):
            return None
        position = len(self.stack) - 1 - top_first_index
        if not 0 <= position < len(self.stack):
            return None
        named = self.stack[position]
        for target in choice.data.get("targets") or ():
            if target.get("kind") == "stack" and target.get("stack_item") is named:
                return named
        return None

    def _resolve_trigger_targets(
        self, choice: PendingChoice, permanent_ids, amounts=None,
    ) -> bool:
        """Record **several** chosen targets on the stack object (CR 601.2c).

        The answer for a prompt armed with ``max_targets`` — "each of up to two
        other target creatures you control" (Basri's Acolyte). Checked the way
        the one-target answer is, against the list that was offered: each id
        once (CR 115.3: the same object is not chosen twice for one instance
        of "target") and no more of them than the ability prints. An **empty**
        list is the answer "nobody", accepted only from a prompt armed
        ``up_to`` — and it is the answer for a one-target "up to" as well as a
        several-target one, which is why a single-target prompt is answered
        through here when it is declined.

        Written in the shape a *cast* writes the same announcement
        (``target_permanent_id`` a list, the seat settled only where every
        named object shares one), so every handler that already reads a
        several-target spell reads this.
        """
        item = choice.data.get("_trigger_item")
        if item is None:
            return False
        ceiling = int(choice.data.get("max_targets") or 1)
        named = list(permanent_ids or ())
        offered = {
            target.get("permanent_id")
            for target in choice.data.get("targets") or ()
            if target.get("kind", "permanent") == "permanent"
        }
        if not named:
            # **Nobody**, which only an "up to" may answer (CR 601.2c). The
            # sentence above was written when the prompt could not be answered
            # this way at all: it holds priority, so "needs no answer" left a
            # seat that wanted to name nobody with no way to say so and no way
            # to do anything else. The answer is recorded on the object
            # (``record_no_target_named``) because its empty target fields
            # would otherwise send the resolution looking for a target.
            if not choice.data.get("up_to"):
                return False
            self.discard_pending_choice(choice)
            item.target_permanent_id = None
            item.target_permanent_index = None
            self.record_no_target_named(item)
            self.log.append(
                f"{choice.data.get('card_name', 'Ability')}: names no target"
            )
            return True
        if len(named) > ceiling or len(set(named)) != len(named):
            return False
        # "…exile **two** target lands" (Petradon): a printed count with no
        # "up to" is owed whole (CR 601.2c), so a short answer is refused and
        # the prompt stays owed. The arming side removed the ability where the
        # board could not meet the count, so the ceiling here is the count.
        if choice.data.get("exact_targets") and len(named) != ceiling:
            return False
        if any(permanent_id not in offered for permanent_id in named):
            return False
        permanents = [self.permanent_by_id(permanent_id) for permanent_id in named]
        if any(permanent is None for permanent in permanents):
            return False
        division = None
        if choice.data.get("division_total") is not None:
            division = self._trigger_division_entries(choice, permanents, amounts)
            if division is None:
                return False
        queued = self._choice_is_queued(choice)
        self.discard_pending_choice(choice)
        item.target_permanent_id = named
        item.target_permanent_index = None
        item.target_player_index = self.announced_target_seat(named)
        item.targets_chosen = self._trigger_target_was_a_choice()
        if division is not None:
            # On the key a divided *spell* and a divided activation carry it
            # (``divided_damage.DIVIDED_TARGETS``), so the placement handler,
            # ``stack_targets``' reader and CR 608.2b's blanking read a
            # trigger's division exactly as they read Bounty of the Hunt's.
            from ....divided_damage import DIVIDED_TARGETS

            item.choices[DIVIDED_TARGETS] = division
        labels = [permanent.card.name for permanent in permanents]
        if division is not None:
            labels = [
                label if entry[2] is None else f"{label} ({entry[2]})"
                for label, entry in zip(labels, division)
            ]
        self.log.append(
            f"{choice.data.get('card_name', 'Ability')}: targets "
            + ", ".join(labels)
        )
        self._announce_answered_targets(item, choice, queued)
        return True

    def _trigger_division_entries(self, choice: PendingChoice, permanents, amounts):
        """CR 601.2d's announcement for a divided trigger's chosen
        *permanents*, as ``divided_targets`` entries — or None when the
        division is not one the rules allow.

        *amounts* is the announcer's division, one share per permanent. Left
        out it is taken only where nobody had a choice to make
        (``divided_damage.forced_division``: one target takes the total, as
        many targets as the total take one apiece) or where the game divides
        (``evenly``); otherwise a missing division is refused rather than
        invented, because 2+1 and 1+2 are the announcer's to pick. The answer
        is held to ``division_refusal``, the gate a divided spell and a
        divided activation are held to, so a share of 0, a wrong total or a
        repeated target is refused the same way.
        """
        from ....divided_damage import (CHOSEN, EVENLY, division_refusal,
                                       forced_division, stamped_entry)

        total = int(choice.data["division_total"])
        how = choice.data.get("division", EVENLY)
        if how != CHOSEN:
            if amounts is not None:
                return None
            shares = [None] * len(permanents)
        elif amounts is None:
            shares = forced_division(total, len(permanents))
            if shares is None:
                return None
        else:
            shares = list(amounts)
            if len(shares) != len(permanents) or not all(
                isinstance(share, int) and not isinstance(share, bool)
                for share in shares
            ):
                return None
        entries = []
        for permanent, share in zip(permanents, shares):
            seat = self.controller_index_of(permanent)
            if seat is None:
                return None
            entries.append(stamped_entry(
                seat, self.battlefield_index_of(permanent), share,
                permanent.permanent_id,
            ))
        if division_refusal(
            total, entries, division=how,
            max_targets=choice.data.get("max_targets"),
        ) is not None:
            return None
        return entries

    def _resolve_trigger_graveyard_target(
        self, choice: PendingChoice, seat, graveyard_index: int,
    ) -> bool:
        """Record a chosen **card in a graveyard** on the stack object
        (CR 603.3d, CR 115.2).

        The answer names a pile and a slot, and is checked against the list
        that was offered — by the stamp each offer carries, not by the slot
        number, so a pile that renumbered between the offer and the answer
        cannot turn the answer into a different card.

        Written in the shape a cast writes the same announcement
        (``_stack_push_object``): the stamp is the identity, the slot beside it
        is where the stamp sits now, and ``target_player_index`` is the pile —
        which is what every graveyard handler reads, and what
        ``_run_stack_item_resolution`` re-locates the slot from as the ability
        resolves.
        """
        item = choice.data.get("_trigger_item")
        if item is None:
            return False
        offered = any(
            target.get("kind") == "graveyard"
            and target.get("seat") == seat
            and target.get("graveyard_index") == graveyard_index
            for target in choice.data.get("targets") or ()
        )
        stamp = (choice.data.get("_graveyard_stamps") or {}).get((seat, graveyard_index))
        if not offered or stamp is None:
            return False
        slot = self.graveyard_index_of(stamp)
        if slot is None:
            return False
        queued = self._choice_is_queued(choice)
        self.discard_pending_choice(choice)
        item.target_graveyard_card = stamp
        item.target_permanent_index = slot
        item.target_player_index = stamp.seat
        item.target_permanent_id = None
        item.targets_chosen = self._trigger_target_was_a_choice()
        self.log.append(
            f"{choice.data.get('card_name', 'Ability')}: targets {stamp.card.name} "
            f"in {self.players[stamp.seat].name}'s graveyard"
        )
        self._announce_answered_targets(item, choice, queued)
        return True

    def _resolve_trigger_graveyard_targets(
        self, choice: PendingChoice, seat, graveyard_indices,
    ) -> bool:
        """Record **several** chosen cards in one graveyard on the stack object
        (CR 603.3d, CR 601.2c).

        "When this creature enters, exile **up to two** target cards from **a
        single graveyard**." (Gravegouger.) The plural of
        :meth:`_resolve_trigger_graveyard_target`, checked the way both the
        one-card answer and the several-object answer are: every slot named is
        one the prompt offered **in the one pile named** (*seat* — which is
        what makes "a single graveyard" true by construction), by the stamp it
        was offered under; each once (CR 115.3); no more than the ability
        prints and, for a count printed without "up to", exactly that many. An
        empty list is the "up to" answer "nobody", which the several-object
        answer already records.

        Written in the shape a spell's announcement of the same sentence is
        (Decompose): ``target_graveyard_card`` a list of stamps, the slots
        beside them, ``target_player_index`` the pile — so the handler's
        announced branch (``exile_cards_from_graveyard``), CR 608.2b's
        re-check and ``stack_targets`` read a trigger's exactly as a spell's.
        """
        item = choice.data.get("_trigger_item")
        if item is None:
            return False
        indices = list(graveyard_indices or ())
        if not indices:
            return self._resolve_trigger_targets(choice, [])
        ceiling = int(choice.data.get("max_targets") or 1)
        if len(indices) > ceiling or len(set(indices)) != len(indices):
            return False
        if choice.data.get("exact_targets") and len(indices) != ceiling:
            return False
        offered = {
            (target.get("seat"), target.get("graveyard_index"))
            for target in choice.data.get("targets") or ()
            if target.get("kind") == "graveyard"
        }
        stamps_offered = choice.data.get("_graveyard_stamps") or {}
        stamps, slots = [], []
        for index in indices:
            stamp = stamps_offered.get((seat, index))
            if (seat, index) not in offered or stamp is None:
                return False
            slot = self.graveyard_index_of(stamp)
            if slot is None or slot in slots:
                return False
            stamps.append(stamp)
            slots.append(slot)
        queued = self._choice_is_queued(choice)
        self.discard_pending_choice(choice)
        item.target_graveyard_card = stamps
        item.target_permanent_index = slots
        item.target_player_index = seat
        item.target_permanent_id = None
        item.targets_chosen = self._trigger_target_was_a_choice()
        self.log.append(
            f"{choice.data.get('card_name', 'Ability')}: targets "
            + ", ".join(stamp.card.name for stamp in stamps)
            + f" in {self.players[seat].name}'s graveyard"
        )
        self._announce_answered_targets(item, choice, queued)
        return True

    def _resolve_trigger_target(
        self, choice: PendingChoice, permanent_id: int | None = None,
        seat: int | None = None, permanent_ids: list[int] | None = None,
        graveyard_index: int | None = None,
        stack_item=None,
        amounts: list[int] | None = None,
        graveyard_indices: list[int] | None = None,
    ) -> bool:
        """Record the chosen target on the stack object that asked (CR 601.2c).

        The ability stays on the stack and resolves later, with a target it now
        names — the same shape as a modal trigger's answer, and different from
        ``_resolve_reflexive_target``, which runs its steps immediately because
        a reflexive ability was never on the stack at all.

        The answer is checked against the list that was offered rather than
        against the board: targets are chosen once, at announcement, so a
        permanent or a seat that became legal a moment later is not a legal
        answer. A **player** answer clears the permanent fields rather than
        leaving whatever was there, because "target opponent" and "target
        creature" write the same two slots on the stack object and a stale id
        would resolve as an object target.
        """
        item = choice.data.get("_trigger_item")
        if item is None:
            return False
        if choice.data.get("division_total") is not None:
            # A division (CR 601.2d) is a list of targets with a share each,
            # even when the list is one long: a single id is that list, and
            # every other shape of answer names nothing this prompt offered.
            if permanent_ids is None and permanent_id is not None:
                permanent_ids = [permanent_id]
            if permanent_ids is None:
                return False
            return self._resolve_trigger_targets(choice, permanent_ids, amounts)
        if amounts is not None:
            return False
        if graveyard_indices is not None:
            return self._resolve_trigger_graveyard_targets(
                choice, seat, graveyard_indices
            )
        if graveyard_index is not None and int(choice.data.get("max_targets") or 1) > 1:
            # One card named for an ability that may name several (Gravegouger
            # with one card chosen): the several-card answer's own check.
            return self._resolve_trigger_graveyard_targets(
                choice, seat, [graveyard_index]
            )
        if permanent_ids is not None:
            return self._resolve_trigger_targets(choice, permanent_ids)
        if permanent_id is not None and choice.data.get("exact_targets"):
            # One object named for an ability that owes several (Petradon):
            # the several-target answer's own check, which refuses it.
            return self._resolve_trigger_targets(choice, [permanent_id])
        if graveyard_index is not None:
            return self._resolve_trigger_graveyard_target(choice, seat, graveyard_index)
        targets = choice.data.get("targets") or ()
        card_name = choice.data.get("card_name", "Ability")
        # "…counter target **spell**" (Mystic Snake). A prompt offers spells or
        # it offers permanents and players, never both — the spec that armed it
        # is one kind — so an answer in the other vocabulary names nothing this
        # prompt offered and is refused rather than read as a seat.
        offered_spells = [
            target["stack_item"] for target in targets
            if target.get("kind") == "stack"
        ]
        if offered_spells or stack_item is not None:
            if not any(offered is stack_item for offered in offered_spells):
                return False
            # Still on the stack: a spell that has left is nobody's target.
            if not any(existing is stack_item for existing in self.stack):
                return False
            queued = self._choice_is_queued(choice)
            self.discard_pending_choice(choice)
            item.target_stack_item = stack_item
            self.log.append(f"{card_name}: targets {stack_item.card.name}")
            self._announce_answered_targets(item, choice, queued)
            return True
        if permanent_id is None:
            offered_seats = {
                target.get("seat")
                for target in targets
                if target.get("kind") == "player"
            }
            if seat not in offered_seats:
                return False
            queued = self._choice_is_queued(choice)
            self.discard_pending_choice(choice)
            item.target_player_index = seat
            item.target_permanent_index = None
            item.target_permanent_id = None
            item.targets_chosen = self._trigger_target_was_a_choice()
            self.log.append(f"{card_name}: targets {self.players[seat].name}")
            self._announce_answered_targets(item, choice, queued)
            return True
        offered = {
            target.get("permanent_id")
            for target in targets
            if target.get("kind", "permanent") == "permanent"
        }
        if permanent_id not in offered:
            return False
        perm = self.permanent_by_id(permanent_id)
        if perm is None:
            return False
        controller = self.controller_index_of(perm)
        if controller is None:
            return False
        queued = self._choice_is_queued(choice)
        self.discard_pending_choice(choice)
        item.target_player_index = controller
        item.target_permanent_index = self.battlefield_index_of(perm)
        item.target_permanent_id = permanent_id
        item.targets_chosen = self._trigger_target_was_a_choice()
        self.log.append(f"{card_name}: targets {perm.card.name}")
        self._announce_answered_targets(item, choice, queued)
        return True

    def _trigger_target_was_a_choice(self) -> bool:
        """Whether the target a triggered ability has just been given counts
        as **chosen** for CR 608.2b (``StackItem.targets_chosen``).

        Yes, with one exception: an answer given while a permanent is on its
        way to a graveyard (``Game.departing``). The death sweep announces a
        dies-trigger while the dying permanent is still listed, so the list
        the picker offered then is the board *before* the event the trigger is
        about — Blazing Effigy's "it deals X damage to target creature" is
        offered the dying Effigy, and a seat with nobody to ask takes its
        default there and then. CR 603.3d would never have offered that
        permanent, and asking CR 608.2b of it would counter the ability for a
        target the engine mis-chose: the decline ROADMAP has carried since
        Nemesis, and it stands for exactly this moment and no wider.

        A **person's** answer is given after the sweep has finished, names a
        permanent that is still there (the answer is refused otherwise), and
        counts.
        """
        return not self.departing

    def _choice_is_queued(self, choice: PendingChoice) -> bool:
        """Whether *choice* is sitting on the queue rather than being answered
        the moment it was armed (``ChoiceSpec.default_at_arm``).

        Asked by the two answers that finish a triggered ability's
        announcement, and it is what makes "a player chose targets" fire
        exactly once: a default taken at arm runs **inside** ``_stack_push``,
        which announces at its own end, while a queued prompt is answered after
        that method returned without announcing — because the choice was still
        owed.
        """
        return any(waiting is choice for waiting in self.pending_choices)

    def _announce_answered_targets(self, item, choice: PendingChoice, queued: bool) -> None:
        """CR 603.3d's choice, announced when the answer is what made it.

        Only for an answer that arrived off the queue (see
        :meth:`_choice_is_queued`); the seat that answered is the chooser,
        which is the ability's controller unless the card names another
        ("**that player** chooses target player who…", the Exodus Oaths).

        **"Becomes the target" is announced either way** (CR 603.2). The object
        was pushed before this answer existed, so ``_stack_push_object``'s
        announcement saw no target on it at all — whether the answer then came
        from a player or from a default taken at arm. What it must not do twice
        is the *choice* announcement, which ``_stack_push`` makes at its own
        end for the at-arm case.
        """
        self._announce_targeting(item)
        if queued:
            self.announce_targets_chosen(item, chooser=choice.player_index)

    def _default_trigger_target(self, choice: PendingChoice) -> bool:
        """What a non-interactive seat answers with: the seat the resolution
        would have used anyway, and otherwise the **first** target offered.

        Two policies, and the split is the difference between a choice and a
        consequence.

        For an **object** it is the first candidate *on the side the effect
        wants* (:meth:`_default_trigger_target_side`), and the first candidate
        when the effect does not say — the reading
        ``_default_trigger_mode_target`` next door has always taken for a mode,
        applied to the trigger's own ``item.ability_instruction``. It used to be
        the first candidate outright, on the stated ground that valuing it would
        move every seeded AI regression; when entry triggers with nothing
        announced began choosing here (PCY W3G3: a copy's, a reanimation's), it
        was measured instead and no test in the suite moved — while the
        unvalued answer had a seat-0 Clone of Nekrataal destroying its
        controller's own creature whenever that creature came first in seat
        order.

        For a **player** it is not a policy at all. Before the announcement
        existed the resolution read ``_default_opposing_seat`` — the first
        living opponent — out of ``target_player_index`` being None. Answering
        with that same seat is what makes announcing the target a change to what
        a *player* is asked and to nothing else: headless play, AI play and
        every two-player game resolve exactly where they resolved before.

        **Whose first living opponent** is ``choice.player_index``, the seat the
        prompt was armed for, and never the ability's controller. On every
        ordinary trigger those are one seat, which is why reading either looked
        the same; the Exodus Oaths print "**that player** chooses target
        player…" and separate them, and the answer had gone on being computed
        from the controller. At two seats that is invisible — there is one
        opponent and every rule agrees — and at three it made the *owner of the
        enchantment* decide which player a third party's default named: the same
        board, the same enumerated candidates, and Oath of Mages burning P1 when
        seat 0 controlled it and P0 when seat 1 did. The seat that is asked a
        question is the seat its default is computed from.
        """
        targets = choice.data.get("targets") or ()
        if not targets:
            self.discard_pending_choice(choice)
            return True
        item = choice.data.get("_trigger_item")
        if choice.data.get("division_total") is not None:
            return self._default_trigger_division(choice, item)
        # "…counter target **spell**" (Mystic Snake): the topmost spell on the
        # side the effect wants — a counter is aimed at an opponent's — and the
        # topmost offered when that side has none, because the target is
        # mandatory. The candidates were armed topmost first
        # (``_choose_trigger_stack_target``).
        spells = [target for target in targets if target.get("kind") == "stack"]
        if spells:
            wanted = (
                self._default_trigger_target_side(item, choice.player_index)
                if item is not None else set()
            )
            chosen = next(
                (
                    target for target in spells
                    if target["stack_item"].caster_index in wanted
                ),
                spells[0],
            )
            return self._resolve_trigger_target(
                choice, stack_item=chosen["stack_item"]
            )
        if item is not None:
            standing = self._default_opposing_seat(choice.player_index)
            for target in targets:
                if target.get("kind") == "player" and target.get("seat") == standing:
                    return self._resolve_trigger_target(choice, seat=standing)
            # **A card in a graveyard**: the one the resolution took before
            # anybody was asked, for the player half's reason above — choosing
            # the target here is then a change to what a *player* is asked and
            # to nothing a seat nobody asks does. That pick was the first card
            # the phrase admits in the pile the handler read, and the pile was
            # the ability's "target player": the standing opposing seat, where
            # the phrase reaches any graveyard (Necromancy, Iridescent Drake),
            # and otherwise the only pile on offer ("from **your** graveyard").
            # So: the first offer in the standing seat's pile, else the first
            # offer at all, which for a pile the standing seat has nothing in
            # is a card where the old scan found none.
            cards = [target for target in targets if target.get("kind") == "graveyard"]
            if cards and int(choice.data.get("max_targets") or 1) > 1:
                # **Several cards out of a single graveyard** (Gravegouger):
                # what the resolution took before the cards were announced —
                # ``_default_graveyard_pile_choice``'s pile (another seat's
                # first, its own only when no other is offered) and
                # ``_default_graveyard_exile_pick``'s cards (the most the
                # ability allows, the cards their owner could still cast from
                # there first, else in pile order). So announcing them changes
                # what a *player* is asked and nothing an unasked seat does.
                from ....ai_prompt_readers import (denied_graveyard_pile,
                                                   graveyard_denial_order)

                piles = list(dict.fromkeys(target["seat"] for target in cards))
                pile = denied_graveyard_pile(choice.player_index, piles)
                slots = [
                    target["graveyard_index"] for target in cards
                    if target["seat"] == pile
                ]
                if pile != choice.player_index:
                    slots = graveyard_denial_order(self, pile, slots)
                ceiling = int(choice.data["max_targets"])
                return self._resolve_trigger_graveyard_targets(
                    choice, pile, slots[:ceiling]
                )
            if cards:
                pick = next(
                    (target for target in cards if target.get("seat") == standing),
                    cards[0],
                )
                return self._resolve_trigger_target(
                    choice, seat=pick["seat"], graveyard_index=pick["graveyard_index"],
                )
            # **The other half of the combat pair**, when the event froze one
            # and it is on offer. "Whenever this creature becomes blocked, you
            # may have it deal damage equal to its power to **target
            # creature**" (the Laccoliths) used to have its blocker stamped into
            # the target field by the fire site, which skipped the choice
            # CR 603.3d gives the controller; the choice is asked now, and this
            # is the player half's argument above applied to an object: the
            # answer a seat that is not asked gives is the one the resolution
            # used anyway, so headless and AI play resolve where they always
            # did and only the *asking* changed.
            partners = set(
                (item.trigger_context or {}).get("blocked_permanent_ids") or ()
            )
            for target in targets:
                if (
                    target.get("kind") == "permanent"
                    and target.get("permanent_id") in partners
                ):
                    return self._resolve_trigger_target(
                        choice, permanent_id=target["permanent_id"]
                    )
            wanted = self._default_trigger_target_side(item, choice.player_index)
            # "Up to two": as many as the ability prints, on the side the
            # effect wants. A seat nobody asks takes what the card offers it —
            # one counter where the card prints two is a card playing as half
            # of itself. Where the effect names no side the single first
            # candidate below is unchanged: with nothing to say whose creatures
            # an effect wants, "as many as possible" is not a policy.
            ceiling = int(choice.data.get("max_targets") or 1)
            if ceiling > 1:
                several = [
                    target["permanent_id"] for target in targets
                    if target.get("kind") == "permanent"
                    and target.get("seat") in wanted
                ][:ceiling]
                if choice.data.get("exact_targets"):
                    # "…exile **two** target lands" (Petradon) owes both, so a
                    # side the effect wants that holds one is topped up from
                    # the rest of the offer, in the offer's order — a short
                    # answer is not one this prompt accepts.
                    several += [
                        target["permanent_id"] for target in targets
                        if target.get("kind") == "permanent"
                        and target["permanent_id"] not in several
                    ][: ceiling - len(several)]
                if several:
                    return self._resolve_trigger_targets(choice, several)
            for target in targets:
                if target.get("kind") == "permanent" and target.get("seat") in wanted:
                    return self._resolve_trigger_target(
                        choice, permanent_id=target["permanent_id"]
                    )
        first = targets[0]
        if first.get("kind") == "player":
            return self._resolve_trigger_target(choice, seat=first["seat"])
        return self._resolve_trigger_target(choice, permanent_id=first["permanent_id"])

    def _default_trigger_division(self, choice: PendingChoice, item) -> bool:
        """A non-interactive seat's announcement for a **divided** trigger
        (CR 603.3d, CR 601.2d): which targets, and each one's share.

        The policy a divided *spell* is proposed with
        (``ai_divisions.choose_divided_targets``), applied to the trigger's own
        candidates: on the side the effect wants
        (:meth:`_default_trigger_target_side` — Shambling Swarm's ``-1/-1``
        reads as an opponent's), **spread** as far as the ceiling allows, with
        the total split by ``divided_damage.spread_shares``. A side with nothing
        on it leaves the mandatory target to the other side, and there the
        division is concentrated on one creature: an effect aimed at the
        wrong board does least harm in one place.

        **Counters that lower toughness are split by what they kill**
        (``ai_divisions.divided_shrink_shares``), and concentrated where they
        harm least when they land on the wrong board
        (``ai_divisions.least_harmed_permanent``) — Shambling Swarm's come back off
        at the next end step, so a share that kills nothing is a share
        wasted. Reviewed at Torment's promotion rehearsal, by running it: the
        spread killed nothing over four creatures with an X/1 among them, and
        on its controller's own board it killed the Savannah Lions it was
        offered first beside a Hill Giant that would have lived.
        """
        from ....ai_divisions import (divided_shrink_shares,
                                      least_harmed_permanent)
        from ....divided_damage import CHOSEN, EVENLY, divided_instruction, spread_shares

        permanents = [
            target["permanent_id"] for target in choice.data.get("targets") or ()
            if target.get("kind") == "permanent"
        ]
        wanted = (
            self._default_trigger_target_side(item, choice.player_index)
            if item is not None else set()
        )
        preferred = [
            target["permanent_id"] for target in choice.data.get("targets") or ()
            if target.get("kind") == "permanent"
            and (not wanted or target.get("seat") in wanted)
        ]
        ceiling = max(1, int(choice.data.get("max_targets") or 1))
        chosen = choice.data.get("division", EVENLY) == CHOSEN
        divided = divided_instruction(
            (getattr(item, "ability_instruction", None),)
            if getattr(item, "ability_instruction", None) is not None else ()
        )
        counter = str((divided.payload.get("counter") if divided is not None else "") or "")
        if chosen and wanted and preferred:
            shares = divided_shrink_shares(
                self, preferred, int(choice.data["division_total"]), ceiling, counter,
            )
            if shares:
                return self._resolve_trigger_targets(
                    choice, [permanent_id for permanent_id, _ in shares],
                    [share for _, share in shares],
                )
        if chosen and not preferred and permanents:
            least_harmed = least_harmed_permanent(
                self, permanents, int(choice.data["division_total"]), counter,
            )
            if least_harmed is not None:
                permanents = [least_harmed]
        picked = preferred[:ceiling] if preferred else permanents[:1]
        if not picked:
            self.discard_pending_choice(choice)
            return True
        amounts = None
        if chosen:
            amounts = spread_shares(int(choice.data["division_total"]), len(picked))
        return self._resolve_trigger_targets(choice, picked, amounts)

    def _default_trigger_target_side(self, item, chooser: int) -> set:
        """The seats whose permanent a non-interactive *chooser* aims *item*
        at, or the empty set when the effect does not say.

        ``ai_target_sides.ability_target_side`` reads the ability step by step with
        its wrappers opened ("you may return target land" is still a bounce),
        and ``activation_target_side`` answers from the top-level kind's family
        where no step carries a ``targets`` description (Man-o'-War's bounce) —
        the readings ``_default_trigger_mode_target`` (the second) and the
        foreign-activation chooser (the first) already take, so a trigger is
        aimed the way a mode and an activated ability of the same effect are.
        """
        from ....ai_target_sides import (ability_target_side,
                                         activation_target_side)

        instruction = getattr(item, "ability_instruction", None)
        if instruction is None:
            return set()
        side = ability_target_side(instruction) or activation_target_side(instruction)
        if side == "opponent":
            return set(self.opponents_of(chooser))
        if side == "you":
            return {chooser}
        return set()

    def _select_trigger_mode_target(self, option: dict, target: dict) -> dict | None:
        """The offered candidate *target* names, or None if it names none.

        *target* is what a caller could say over a wire: ``permanent_id`` for
        an object (the stable identity, never a battlefield slot - CR 400.7,
        and an index chosen a moment ago can address a different permanent),
        ``seat`` for a player. It is resolved **against the option's own
        candidate list**, so an answer naming something the picker never
        offered is refused rather than quietly performed - the engine and the
        picker agree on what is a legal target because they are reading the
        same list.
        """
        for candidate in option.get("valid_targets") or []:
            if candidate.get("kind") == "permanent":
                if target.get("permanent_id") is None:
                    continue
                permanent = self.permanent_at(candidate["seat"], candidate["index"])
                if permanent is not None and permanent.permanent_id == target["permanent_id"]:
                    return candidate
            elif target.get("permanent_id") is None and candidate.get("seat") == target.get("seat"):
                return candidate
        return None

    def _offered_mode_instructions(self, choice: PendingChoice) -> tuple:
        """The instruction behind each offered mode, whichever site armed it.

        ``_resolve_mode_choice`` already distinguishes the two by the data on
        the prompt rather than by a list of kinds; this reads the same two keys
        so a third arming site is a data question there and here alike.
        """
        if choice.data.get("_trigger_item") is None:
            return tuple(choice.data.get("_modes") or ())
        return tuple(
            getattr(option, "instruction", None)
            for option in (choice.data.get("_options") or ())
        )

    def _first_unpriced_mode(self, choice: PendingChoice) -> int:
        """The first offered mode that does not spend the chooser's own
        resources, or 0 when every one of them does.

        ``_default_optional_pay``'s policy one layer in: "pay 4 life **or** put
        the card on top of your library" (Sylvan Library) offers a price beside
        a free alternative, and printed order put the price first. A seat
        nobody asked drew two extra cards every draw step and paid 8 life for
        them — dead on the third one, out of a card whose whole design is that
        the player decides how much life it is worth.

        All-priced alternatives keep printed order: "sacrifice a creature or
        discard a creature card" (Crypt Lurker) is a choice between two prices
        and picking the smaller is valuation, exactly as it is for a toll.

        Among the free ones, a choice asked **at resolution** (CR 608.2d — a
        prompt carrying the resolution's ``_context``) skips an alternative that
        would change nothing on the board as it now stands
        (``ai_prompt_readers.offered_alternative_changes_nothing``): Urborg aimed at
        a swampwalker takes swampwalk, not the first strike it does not have.
        Printed order is still the answer whenever no alternative is a no-op.
        """
        from ....ai_prompt_readers import (offered_action_is_a_payment,
                                           offered_alternative_changes_nothing)

        seat = self.players[choice.player_index]
        context = choice.data.get("_context")
        # The printed player references that resolve to the chooser. With no
        # resolution context — the modal-trigger site — the chooser *is* the
        # ability's controller, which is what "caster" names.
        self_recipients = {"caster"}
        if context is not None:
            if getattr(context, "caster", None) is not seat:
                self_recipients.discard("caster")
            if getattr(context, "target", None) is seat:
                self_recipients.update(("target", "target_player"))
        offered = self._offered_mode_instructions(choice)
        unpriced = [
            index for index, instruction in enumerate(offered)
            if instruction is not None
            and not offered_action_is_a_payment((instruction,), self_recipients)
        ]
        if context is not None:
            for index in unpriced:
                if not offered_alternative_changes_nothing(
                    self, offered[index], context
                ):
                    return index
        return unpriced[0] if unpriced else 0

    def _default_mode_choice(self, choice: PendingChoice) -> bool:
        """What a non-interactive seat answers a "Choose one —" prompt with:
        the first *offered* mode that is not a price paid out of its own
        resources, and the first offered mode when they all are.

        A stated policy, not a valuation, and "offered" rather than "printed"
        because CR 700.2b has already removed from the list any mode whose
        targets could not be chosen. The target inside that mode is
        ``_default_trigger_mode_target``'s, which is derived from the mode's
        own effect family rather than named per card.

        It was plain printed order, which is a policy nobody chose for the one
        card in the pool where the alternatives are not alike — see
        ``_first_unpriced_mode``.

        **A modal triggered ability's mode is weighed** (CR 700.2b: Relic
        Bind, Elder Gargaroth, Trufflesnout — the prompts that carry the
        ability, ``_trigger_item``). The stated answer above is what
        ``ai_prompts.choose_trigger_mode`` starts from and falls back to; where
        another offered mode is measured to do more, that one is taken. The
        valuation is the policy's and so are its weights; that it is consulted
        here is the registry's decision, as it is for every default that asks
        the policy something.
        """
        from ....ai_prompts import choose_trigger_mode

        stated = self._first_unpriced_mode(choice)
        return self._resolve_mode_choice(
            choice, choose_trigger_mode(self, choice, stated)
        )
