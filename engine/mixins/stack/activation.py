"""Activating an ability of a permanent (CR 602): pay its cost and put it
on the stack.

The sibling of ``casting`` — same shape, different object. ``queue_permanent_ability``
is the large one: it resolves which of a multi-ability card's abilities was
chosen, checks the activation window, pays the cost, and either queues the
ability or (for a mana ability, CR 605.1a) performs it without using the stack.

``_activate_onto_stack`` is CR 602.2 in order, and calls its steps from the
mixins beside it, each moved out of it whole at the 2,000-line cap:
``activation_checks`` (the source, the ability, the announcement settled and
the CR 602.5 window — every refusal before a cost is touched) and
``activation_charges`` (the payers chosen, and the payment). The hinge
between them, the mana payment, stays here, with the mana ability that
resolves at once (CR 605.3b) and the push.

Also beside it: ``activation_payment`` (whether a cost paid in anything but
mana can be paid at all, and what may pay each part of it) and
``card_activation`` (an ability of a *card*, in a hand or a graveyard, rather
than of a permanent).
"""

from __future__ import annotations


from ...restricted_mana import ACTIVATE, PaymentPurpose
from ...aura_grants import attached_ability_cost_reduction
from ...bare_announcements import (announced_fields, default_activation_target,
                                   names_an_object, seat_of_unseated_slot)
from ...cost_modifiers import (ability_cost_reduction, ability_cost_tax,
                                sacrifice_taxes)
from ...self_cost_modifiers import ability_self_reduction_amount
from ...divided_damage import DIVIDED_TARGETS
from ...cost_x_definitions import cost_x_is_defined, cost_x_value
from ...oracle_types import x_spend_colors_from_text
from ...targeting import GRAVEYARD_TARGET_KIND, derive_activation_spec
from ...target_roles import ROLE_SEATS
from ...mana_payment import (answer_color_choices, is_mana_ability,
                             mana_cost_from_symbols)
from ...events import emit
from ...game_types import (OracleExecutionContext, OracleStateMachine,
                           SimulationResult, StackItem, chosen_damage_source)
from ...handlers._chosen import CHOSEN_ABILITY
from ...handlers._targets import attached_host
from ...oracle import OracleInstruction
from .activation_payment import activation_mana_per_counter


class AbilityActivationMixin:
    def activate_permanent_ability(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        # "…replacing all instances of one color word with another" (Balduvian
        # Shaman). A text change names *two* words, and `mana_color` is only
        # ever the second — the key an any-colour mana ability also uses. The
        # word being replaced arrives here, on the same key
        # the cast side already carries it on, so `mark_text_modified` reads
        # one pair whether a spell or an ability asked the question.
        old_color: str | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them
        # (the web layer resolves them off the wire). Several targets may sit
        # on different battlefields, which one `target_player_index` cannot
        # express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        # **A roles announcement whose slots sit in two zones.** "Choose target
        # artifact a player controls **and target artifact card in that
        # player's graveyard**" (Goblin Welder): one slot is a permanent, named
        # by id like every other target, and the other is a card in a
        # graveyard, which has no id to name it by — two copies of one card in
        # one pile are literally one ``CardDefinition``.
        #
        # So when this is supplied it describes **every** slot, in role order,
        # each entry naming either a ``permanent_id`` or a
        # ``graveyard_seat``/``graveyard_index`` pair. ``target_permanent_ids``
        # above stays exactly what it was and is what every roles ability
        # before this one still sends; the two are never mixed positionally,
        # because "which list does slot 1 come from?" is a question a wire
        # cannot be left to answer.
        target_role_refs: "list[dict] | None" = None,
        # "Prevent the next X damage that would be dealt this turn **to any
        # number of targets, divided as you choose**." (Serra's Hymn.) CR
        # 601.2d's announcement, reached through CR 602.2b like every other
        # step of 601.2 — and the first *ability* in the pool to print one, so
        # this channel is new here while the cast side has carried it since
        # Fireball. ``(seat, index, share)`` per chosen recipient; a face is
        # ``index=None``.
        divided_targets: list[tuple] | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
        # Which permanent / which card in hand pays a non-mana cost. The payer
        # chooses (CR 601.2b), so the choice arrives with the action that pays
        # it rather than through the pending-choice queue: a cost is paid during
        # activation, and a queued prompt would put the ability on the stack
        # before its cost was collected. A seat that names neither gets the
        # deterministic pick below, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        # "Tap two untapped Spirits you control" — several permanents pay one
        # cost, which one index cannot say. By id, because the list is chosen
        # before anything taps and a slot renumbers as soon as one does.
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        # "Discard **two** cards" (the Prophecy spellshapers): the cards after
        # the one ``cost_hand_index`` names, by hand position — the shape the
        # cast side's "and another card" announces on. None is the
        # deterministic pick, as for every cost choice here.
        cost_other_hand_indices: list[int] | None = None,
        # "Exile **two** cards from your graveyard" (Psychatog), "Exile **any
        # number of** cards from your graveyard" (Painbringer): which cards,
        # by graveyard slot. A card in a graveyard has no id — two copies of
        # one card in one pile are one ``CardDefinition`` — so the set is named
        # by position, all of it at once and before anything leaves the pile.
        # ``cost_permanent_index`` stays the one-card spelling every earlier
        # caller sends; where this is given it is the whole answer. For "any
        # number of", None and ``[]`` both name no cards, which pays the cost.
        cost_graveyard_indices: list[int] | None = None,
        # "**Choose flying, first strike, trample, or shadow**:" (Phyrexian
        # Splicer). A choice printed in the *cost* clause, so CR 602.2b sends it
        # through CR 601.2b and it is announced with the activation — before
        # CR 601.2c chooses targets, which matters because the sentence behind
        # it says "target creature **with the chosen ability**". It arrives with
        # the action for the reason ``cost_permanent_index`` above does: a
        # queued prompt would put the ability on the stack before its
        # announcement was finished.
        chosen_keyword: str | None = None,
        source_seat: int | None = None,
        source_permanent_index: int | None = None,
        source_stack_index: int | None = None,
        source_controller_index: int | None = None,
        seat_announced: bool | None = None,
    ) -> SimulationResult:
        queued = self.queue_permanent_ability(
            controller_index,
            permanent_name,
            target_player_index=target_player_index,
            permanent_index=permanent_index,
            mana_color=mana_color,
            old_color=old_color,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_role_refs=target_role_refs,
            divided_targets=divided_targets,
            target_stack_index=target_stack_index,
            ability_index=ability_index,
            x_value=x_value,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_index=cost_hand_index,
            cost_other_hand_indices=cost_other_hand_indices,
            cost_graveyard_indices=cost_graveyard_indices,
            chosen_keyword=chosen_keyword,
            source_seat=source_seat,
            source_permanent_index=source_permanent_index,
            source_stack_index=source_stack_index,
            source_controller_index=source_controller_index,
            seat_announced=seat_announced,
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
        from ...handlers.prevention import apply_prevention_shield

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
                    and target_player.battlefield[target_perm_idx].is_creature):
                return SimulationResult(label, False, "unsupported", "emblem target is no longer in play")

        if self.enforce_mana_costs:
            required = {"W": 0, "U": 0, "B": 0, "R": 0, "G": 0, "C": 0, "generic": 1}
            # An emblem is not an artifact, so "only to activate abilities of
            # artifacts" mana cannot pay for one — a purpose with no source is
            # that answer rather than a missing argument.
            if not self._pay_mana_cost(
                controller, required, purpose=PaymentPurpose(ACTIVATE)
            ):
                return SimulationResult(label, False, "unsupported", "insufficient mana to activate emblem")

        apply_prevention_shield(self, target_player, target_perm_idx, 1)
        return SimulationResult(label, True, "activated_prevent_one", "resolved")

    def queue_permanent_ability(self, *args, **kwargs) -> SimulationResult:
        """Activate an ability — CR 602, start to finish.

        The same wrapper, for the same rule, as ``queue_from_hand``: CR 602.2b
        routes activation through CR 601.2b–i, so an ability's costs are paid
        inside one announcement and a trigger they fire waits for the end of it.
        Witch's Cauldron eats a creature to pay for itself, and Havoc Jester's
        ping belongs above the Cauldron's ability rather than under it. See
        ``deferring_triggers``.
        """
        # CR 733.1, reached through CR 601.2 and CR 602.2b: an activation that
        # turns out to be illegal is *reversed* — "the entire action is
        # reversed and any payments already made are canceled". The rest of
        # ``_activate_onto_stack`` obeys that by construction, checking every
        # cost where it is announced and paying it further down, so a refusal
        # has nothing to give back. CR 601.2b's announced choice is the one
        # exception, because the target gate has to read it; this ledger is how
        # it is taken back. Undone here and in no other place: a refusal can
        # come from forty returns inside that function, and thirty-nine of them
        # would be a place to forget.
        ledger: list = []
        with self.deferring_triggers():
            result = self._activate_onto_stack(
                *args, reversal_ledger=ledger, **kwargs
            )
        if not result.supported:
            for permanent, had_record, prior in reversed(ledger):
                if had_record:
                    permanent.metadata[CHOSEN_ABILITY] = prior
                else:
                    permanent.metadata.pop(CHOSEN_ABILITY, None)
            return result
        # CR 704.3: state-based actions are checked **whenever a player would
        # receive priority**, and CR 117.3c hands priority straight back to the
        # activator once the ability is on the stack. Paying a cost is a state
        # change with no resolution behind it, so nothing else in the
        # interactive path would sweep: ``_settle`` sweeps for the headless
        # caller and ``pass_priority`` sweeps only *after a resolution*, which
        # CR 116.1 says a special action is not. Measured before it was added —
        # Greed activated at 2 life left the player at 0, not lost, with
        # ``is_game_over`` False, and a `pass_priority` did not fix it either.
        #
        # After the deferral block, never inside it: a trigger the sweep fires
        # (a dies trigger from a sacrificed cost) belongs on the stack above the
        # ability that was just announced (CR 603.3b), which is where an
        # ordinary enqueue puts it — and inside the block it would be held back
        # into the announcement it comes after.
        self.check_state_based_actions()
        return result

    def _activate_onto_stack(
        self,
        controller_index: int,
        permanent_name: str,
        target_player_index: int | None = None,
        permanent_index: int | None = None,
        mana_color: str | None = None,
        # "…replacing all instances of one color word with another" (Balduvian
        # Shaman). A text change names *two* words, and `mana_color` is only
        # ever the second — the key an any-colour mana ability also uses. The
        # word being replaced arrives here, on the same key
        # the cast side already carries it on, so `mark_text_modified` reads
        # one pair whether a spell or an ability asked the question.
        old_color: str | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them
        # (the web layer resolves them off the wire). Several targets may sit
        # on different battlefields, which one `target_player_index` cannot
        # express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        # **A roles announcement whose slots sit in two zones.** "Choose target
        # artifact a player controls **and target artifact card in that
        # player's graveyard**" (Goblin Welder): one slot is a permanent, named
        # by id like every other target, and the other is a card in a
        # graveyard, which has no id to name it by — two copies of one card in
        # one pile are literally one ``CardDefinition``.
        #
        # So when this is supplied it describes **every** slot, in role order,
        # each entry naming either a ``permanent_id`` or a
        # ``graveyard_seat``/``graveyard_index`` pair. ``target_permanent_ids``
        # above stays exactly what it was and is what every roles ability
        # before this one still sends; the two are never mixed positionally,
        # because "which list does slot 1 come from?" is a question a wire
        # cannot be left to answer.
        target_role_refs: "list[dict] | None" = None,
        # "Prevent the next X damage that would be dealt this turn **to any
        # number of targets, divided as you choose**." (Serra's Hymn.) CR
        # 601.2d's announcement, reached through CR 602.2b like every other
        # step of 601.2 — and the first *ability* in the pool to print one, so
        # this channel is new here while the cast side has carried it since
        # Fireball. ``(seat, index, share)`` per chosen recipient; a face is
        # ``index=None``.
        divided_targets: list[tuple] | None = None,
        target_stack_index: int | None = None,
        ability_index: int | None = None,
        x_value: int | None = None,
        # Which permanent / which card in hand pays a non-mana cost. The payer
        # chooses (CR 601.2b), so the choice arrives with the action that pays
        # it rather than through the pending-choice queue: a cost is paid during
        # activation, and a queued prompt would put the ability on the stack
        # before its cost was collected. A seat that names neither gets the
        # deterministic pick below, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        cost_other_hand_indices: list[int] | None = None,
        cost_graveyard_indices: list[int] | None = None,
        # "**Choose flying, first strike, trample, or shadow**:" (Phyrexian
        # Splicer). A choice printed in the *cost* clause, so CR 602.2b sends it
        # through CR 601.2b and it is announced with the activation — before
        # CR 601.2c chooses targets, which matters because the sentence behind
        # it says "target creature **with the chosen ability**". It arrives with
        # the action for the reason ``cost_permanent_index`` above does: a
        # queued prompt would put the ability on the stack before its
        # announcement was finished.
        chosen_keyword: str | None = None,
        source_seat: int | None = None,
        source_permanent_index: int | None = None,
        source_stack_index: int | None = None,
        source_controller_index: int | None = None,
        # **Whether the caller is a seat that has to announce** (CR 601.2c,
        # through CR 602.2b). None is every headless caller — a test, a
        # scripted duel, the AI simulator — for whom a target left unnamed is
        # the picker's first, named below. A bool is the wire: a person at a
        # client, who is asked for every target the ability owes and cannot
        # send the activation without one, so an owed target left unnamed is
        # refused rather than defaulted. The value is whether a *seat* was sent, which
        # only the route knows — it fills in an opposing seat for every
        # activation, and the engine cannot tell that default from a choice.
        seat_announced: bool | None = None,
        # Where CR 601.2b's announced choice records how to take itself back.
        # Supplied by ``queue_permanent_ability``, this function's only caller
        # and the one place a refused activation is reversed (CR 733.1).
        reversal_ledger: list | None = None,
    ) -> SimulationResult:
        # CR 602.1a/602.2a: the source, and whether this seat may activate it.
        source = self._activation_source(
            ability_index=ability_index, controller_index=controller_index,
            permanent_index=permanent_index, permanent_name=permanent_name,
            source_controller_index=source_controller_index,
        )
        if isinstance(source, SimulationResult):
            return source
        controller, permanent, program = source

        target_idx = target_player_index if target_player_index is not None else (1 - controller_index)
        target_player = self.players[target_idx]

        # CR 601.2c (reached through 602.2b) chooses targets **before** CR 601.2h
        # pays the costs, and this ability's cost may remove a permanent — which
        # renumbers every battlefield slot after it. Stamping the identity now is
        # what keeps the two apart.
        #
        # Dwarven Weaponsmith is the card: "{T}, Sacrifice an artifact: Put a
        # +1/+1 counter on target creature." With the artifact sitting before the
        # target on its controller's battlefield, paying the cost slid the target
        # down a slot, and the index the caller chose then named something else —
        # the source itself, in the case that ships. A caller that already sends
        # ids (the whole web layer does, which is why no game ever showed this)
        # is left exactly as it was.
        if target_permanent_ids is None and isinstance(target_permanent_index, int):
            stable = self.permanent_at(target_player, target_permanent_index)
            if stable is not None:
                target_permanent_ids = [stable.permanent_id]

        # …and the *seat* of that same announcement, settled at the same moment
        # and for the same reason. ``target_idx`` above answers a different
        # question — "which battlefield does a bare index count into" — which
        # has to have an answer even when nothing named one.
        # ``StackItem.target_player_index`` is read as "which seat is this
        # object pointed at", and ``handlers/_targets.pick_target_permanent``
        # scopes an announced id to exactly that player. So where the activator
        # named ids and no seat, this function's working default stood in front
        # of a choice somebody had made, and every id on the activator's own
        # battlefield was thrown away behind it.
        #
        # **Here rather than at the push below**, which is the obvious place and
        # the wrong one for the reason the id stamping above is here: CR 601.2c
        # chooses the target and CR 601.2h then pays the cost, and this
        # ability's cost may *eat the permanent that was named*. Goblin
        # Bombardment sacrifices a creature and Skull Catapult sacrifices the
        # one it is aimed at — by the time the item is built there is no live
        # permanent for the ids to name, so the seat could not be recovered and
        # the default came back. Settled before the costs, the announcement
        # survives the cost that destroys it, and CR 608.2b then fizzles the
        # ability at resolution, which is the rule's own answer rather than a
        # resolution against the wrong board.
        #
        # Asked of the seam rather than derived inline: ``_stamp_stack_targets``
        # settles the same question for every item built elsewhere (the cast
        # path, ``activate_from_graveyard``, a fire site), and two spellings of
        # "which seat did the ids name" is how the two ends of one announcement
        # come apart in the first place.
        announced_target_idx = target_idx
        if target_player_index is None:
            from_ids = self.announced_target_seat(target_permanent_ids)
            if from_ids is not None:
                announced_target_idx = from_ids

        # An explicitly chosen spell on the stack (e.g. Deathgrip: "{B}{B}: Counter
        # target green spell"). target_stack_index indexes self.stack (bottom-first).
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]

        # "A source of your choice" (Jade Monolith): a chosen battlefield
        # permanent, or a spell on the stack (its card stands in for the source).
        # One resolver, shared with the casting path since Kor Chant gave a
        # *spell* the same announcement — see ``game_types.chosen_damage_source``.
        chosen_source = chosen_damage_source(
            self,
            seat=source_seat,
            permanent_index=source_permanent_index,
            stack_index=source_stack_index,
        )

        # CR 602.2a: which of its abilities — one that functions here (CR 113.6).
        which = self._chosen_activated_ability(
            ability_index=ability_index, permanent=permanent, program=program,
        )
        if isinstance(which, SimulationResult):
            return which
        ability = which

        # "**Choose flying, first strike, trample, or shadow**" (Phyrexian
        # Splicer). CR 601.2b's choices, announced now — **before** the target
        # gate below, because the phrase that gate enumerates is "target
        # creature with the chosen ability" and a word chosen after it would
        # narrow nothing.
        #
        # Recorded on the ability's own source, which is where CR 614.1c's entry
        # choices live and where `_resolve_chosen_keyword` looks. A note here
        # used to argue the record could not go stale, because the ability costs
        # {T} and a second announcement therefore needs an untap step in between
        # — true of an activation that *happened*, and the whole point is the
        # one that did not. A refusal below pays no {T}, so the permanent stayed
        # untapped and kept a word nobody ended up choosing. It is taken back on
        # the ledger threaded through `queue_permanent_ability` (CR 733.1).
        keyword_refusal = self._announce_chosen_ability(
            permanent, ability, chosen_keyword, reversal_ledger
        )
        if keyword_refusal is not None:
            self.log.append(keyword_refusal)
            return SimulationResult(
                permanent.card.name, False, "unsupported", keyword_refusal
            )

        # CR 602.2b/601.2c, once, before any cost is paid: an ability that
        # targets is unactivatable with no legal target, and a named target
        # must be legal. Derived from the same valid_targets the web picker
        # gets (engine/legality.py), so the list offered and the list enforced
        # are one. This replaced a per-kind if-chain here — banding, the
        # counterspell, destroy-target, equip — that checked four instruction
        # kinds by hand and let every other object-targeted ability (Silent
        # Dart, Royal Assassin, Xenic Poltergeist, …) pay its cost with nothing
        # to target and then deal to the face or no-op.
        target_refusal = self.activation_target_refusal(
            controller_index, permanent, ability,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_role_refs=target_role_refs,
            target_stack_item=target_stack_item,
            # CR 601.2c sizes "X target …" from the X announced at CR 601.2b.
            # An activation that announced none announced zero — this
            # function's stated default for a headless or AI seat (see the
            # "Remove X counters" branch below) — so it may name no target.
            x_value=int(x_value or 0),
        )
        if target_refusal is not None:
            self.log.append(target_refusal)
            return SimulationResult(permanent.card.name, False, "unsupported", target_refusal)
        if seat_announced is not None:
            # The wire's half of the same rule: a client names every target an
            # ability owes, so one left unnamed is not an activation a browser
            # can send — and the default behind it is a target nobody chose.
            # Above the default below for that reason: "exactly one legal
            # target" is still a target the player has to click.
            unannounced = self.unannounced_activation_target(
                controller_index, permanent, ability,
                seat_announced=seat_announced,
                target_permanent_index=target_permanent_index,
                target_permanent_ids=target_permanent_ids,
                target_stack_item=target_stack_item,
                target_role_refs=target_role_refs,
                divided_targets=divided_targets,
                x_value=int(x_value or 0),
            )
            if unannounced is not None:
                self.log.append(unannounced)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", unannounced
                )

        # **An activation that owes a target and named none names the first
        # one its picker offers** (``engine/bare_announcements.py``), here,
        # where CR 601.2c makes the announcement — before the costs, from the
        # list the gate above just read. A headless caller's omission used to
        # be answered at resolution, by whichever handler ran and whatever its
        # own scan met first: Burning Palm Efreet took flying from a creature
        # without it, Soul Sculptor and Angelic Shield reached a creature with
        # protection from them, and the stack object carried no target for
        # anything to respond to or for CR 608.2b to re-check. The default is
        # an entry of the picker's list, so it is a target the gate would have
        # accepted by name, and it is stamped below exactly as a named one is.
        #
        # This replaced ``sole_legal_activation_target``, which made the same
        # announcement only where exactly one target was legal (Tahngarth,
        # Talruum Hero alone on the battlefield) and left every other board to
        # the handlers.
        #
        # A seat the caller sent with no object beside it names no object (it
        # is the battlefield an index would have counted into), so it does not
        # stand in the way — it is where the default is looked for first. A
        # seat named for a **player** target is a target, and is kept.
        if (
            target_player_index is None
            and target_permanent_ids is None
            and (derive_activation_spec(ability) or {}).get("kind")
            != GRAVEYARD_TARGET_KIND
        ):
            # …and a slot named beside **no seat** that the opposing seat does
            # not have is the activator's own (`seat_of_unseated_slot`): the
            # reading the gate above just accepted it under, written onto the
            # announcement so the object carries the permanent it names.
            unseated = seat_of_unseated_slot(
                self, controller_index, target_permanent_index, target_idx,
            )
            if unseated is not None:
                target_player_index = unseated
                target_idx = announced_target_idx = unseated
                target_player = self.players[unseated]
                target_permanent_ids = [
                    self.permanent_at(target_player, target_permanent_index).permanent_id
                ]
        if not names_an_object(
            target_permanent_index, target_permanent_ids, target_stack_item,
            target_role_refs, divided_targets,
        ):
            default = default_activation_target(
                self, controller_index, permanent, ability,
                named_seat=target_player_index, x_value=int(x_value or 0),
            )
            named = announced_fields(self, default) if default is not None else {}
            if "target_player_index" in named:
                target_player_index = named["target_player_index"]
                target_idx = announced_target_idx = target_player_index
                target_player = self.players[target_idx]
            if "target_permanent_index" in named:
                target_permanent_index = named["target_permanent_index"]
            if named.get("target_permanent_ids"):
                target_permanent_ids = named["target_permanent_ids"]
            if "target_stack_item" in named:
                target_stack_item = named["target_stack_item"]

        # CR 601.2d (through 602.2b): the division, once the targets are named.
        division = self._settled_activation_division(
            ability=ability, controller_index=controller_index,
            divided_targets=divided_targets, permanent=permanent,
            target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index,
            target_player_index=target_player_index,
            target_role_refs=target_role_refs, x_value=x_value,
        )
        if isinstance(division, SimulationResult):
            return division
        divided_targets = division

        # CR 602.5: may it be activated now? Every refusal before any cost.
        window = self._activation_window(
            ability=ability, controller_index=controller_index,
            permanent=permanent, program=program, x_value=x_value,
        )
        if isinstance(window, SimulationResult):
            return window
        (
            ability_lower, activation_caps, counters_removed_for_cost,
            loyalty_delta,
        ) = window

        # CR 601.2h's choices: what pays each part of the cost that is not mana.
        payers = self._choose_activation_cost_payers(
            ability=ability, announced_target_idx=announced_target_idx,
            controller=controller, controller_index=controller_index,
            cost_graveyard_indices=cost_graveyard_indices,
            cost_hand_index=cost_hand_index,
            cost_other_hand_indices=cost_other_hand_indices,
            cost_permanent_ids=cost_permanent_ids,
            cost_permanent_index=cost_permanent_index,
            counters_removed_for_cost=counters_removed_for_cost,
            permanent=permanent, target_permanent_index=target_permanent_index,
            target_role_refs=target_role_refs, x_value=x_value,
        )
        if isinstance(payers, SimulationResult):
            return payers
        (
            alternative_mana, cost_hand_index, counter_cost_permanent,
            counter_removal_permanent, counters_removed_for_cost,
            discard_cost_card, discard_cost_cards, exile_cost_choice,
            exiled_for_cost, exiled_set_for_cost, graveyard_target_before_cost,
            graveyard_target_stamp_after_cost, life_owed,
            return_cost_permanents, sacrifice_also_permanent,
            sacrifice_attached_permanent, sacrifice_cost_permanent,
            sacrifice_cost_set, sacrificed_for_cost, tap_cost_permanents,
            untap_cost_permanent,
        ) = payers

        required_cost = dict(ability.cost.mana)
        # "Pay {1} **for each +1/+1 counter on this creature**" (Skeleton
        # Scavengers). CR 601.2f computes the cost as the ability is
        # activated, so the rate is multiplied here -- the same moment
        # ``activation_life_cost`` reads its own counter, and by the same
        # count, so a card printing both would price them off one board.
        for symbol, count in activation_mana_per_counter(
            ability.cost, permanent
        ).items():
            required_cost[symbol] = required_cost.get(symbol, 0) + int(count)
        # "…**or {2}**" when the pool covered it. Folded into the ordinary
        # payment rather than charged beside it, so every tax, reduction and
        # restricted-bucket rule below applies to it exactly as to a printed
        # mana cost.
        for symbol, count in alternative_mana.items():
            required_cost[symbol] = required_cost.get(symbol, 0) + int(count)
        # "**Pay enchanted creature's mana cost**: …" (Merseine.) The symbols
        # are the *host's* and cannot be known when the card compiles, so the
        # cost dict is built here, at the one moment there is a host to read
        # (CR 202.1 — a permanent's mana cost is what is printed in its upper
        # right corner, whatever the copy and text-change layers have made of
        # the object).
        #
        # An Aura with no host, or a host whose printed cost carries a symbol
        # this engine cannot spend, refuses the activation with nothing paid
        # (CR 602.2b). Never a fallback to the empty dict beside it: an
        # unreadable cost read as zero is an ability activated for free, which
        # is the failure every cost reader in this engine is written against.
        if ability.cost.mana_from_attached:
            host = attached_host(self, permanent, last_known=False)
            printed = None if host is None else (
                getattr(host.card, "mana_cost", "") or ""
            )
            symbols = None if host is None else mana_cost_from_symbols(printed)
            if host is None or (symbols is None and printed.strip()):
                details = (
                    f"{permanent.card.name}: the mana cost it charges is the "
                    "attached permanent's, and there is none to read"
                )
                self.log.append(details)
                return SimulationResult(
                    permanent.card.name, False, "unsupported", details
                )
            for symbol, count in (symbols or {}).items():
                required_cost[symbol] = required_cost.get(symbol, 0) + count
        requires_tap = ability.cost.requires_tap
        # Abilities with an "{X}" in their cost (e.g. Clockwork Beast's
        # "{X}, {T}: Put up to X +1/+0 counters") charge X generic mana on top of
        # the printed symbols, where X is the amount the player chose.
        #
        # **Per printed symbol, and only in the cost clause.** Voodoo Doll's
        # cost is "{X}{X}" — two of them, so it charges 2X — and a card whose
        # *effect* mentions X ("deals X damage") is not charging a second one.
        # A single substring test read both as one X, which is half the cost on
        # the one card in the pool that prints the double.
        x_symbols = (ability.source_line or "").lower().split(":", 1)[0].count("{x}")
        # "X is the number of pin counters on this artifact." (Voodoo Doll.)
        # The card *defines* X, so the activator does not announce it
        # (CR 601.2b) — and the definition is read from the same table the
        # grammar consumed the sentence through, because an X consumed by one
        # reader and unknown to the other is a cost nobody charges.
        # The chosen spell is handed over because a definition may read it:
        # "X is twice the mana value of **that spell**" (Reflecting Mirror) is
        # priced off the object the ability targets, not off the board.
        defined_x = cost_x_value(
            self, permanent, ability.source_line or "", target=target_stack_item
        )
        if defined_x is not None:
            x_value = defined_x
        elif cost_x_is_defined(ability.source_line or ""):
            # The card defines X and this activation cannot compute it — no
            # target was named, most often. **Not zero**: an {X} nobody charges
            # is a free ability, which is exactly the failure
            # ``engine/cost_x_definitions.py`` exists to prevent, so the
            # activation is refused with nothing paid (CR 601.2b via 602.2b).
            details = (
                f"{permanent.card.name}: the value of X is defined by the card "
                "and nothing here determines it"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)
        if x_value and x_symbols:
            # "Spend only red mana on X." (Crimson Hellkite.) The X pips are
            # charged as that colour rather than as generic, which is the whole
            # of the restriction: a generic pip is payable from any source, so
            # a clause consumed by the grammar and dropped here would be an
            # ability that works from a pool the card forbids.
            #
            # Read off the raw ability line, the same text
            # ``_parse_x_spend_restriction`` handed to this reader, so the
            # sentence the grammar consumed and the cost this charges cannot
            # come apart. Exactly one colour reaches here: the grammar refuses
            # the "and/or" pair, whose split is a choice this path cannot ask.
            x_colors = x_spend_colors_from_text(ability.source_line or "")
            if len(x_colors) == 1:
                symbol = x_colors[0]
                required_cost[symbol] = (
                    required_cost.get(symbol, 0) + int(x_value) * x_symbols
                )
            else:
                required_cost["generic"] = (
                    required_cost.get("generic", 0) + int(x_value) * x_symbols
                )
        # "Activated abilities cost an additional "Sacrifice a Swamp" to
        # activate for each black mana symbol in their activation costs."
        # (Drought.) The cast path's twin, asked of the *printed* activation
        # cost — CR 601.2f determines an additional cost from the cost as
        # printed, before any of the increases and reductions below touch the
        # generic part. Refused with nothing paid when it cannot be met, which
        # is CR 602.2b routing through CR 601.2h.
        # "Activated abilities of nontoken Rebels cost an additional
        # "Sacrifice a land"" (Brutal Suppression) asks what the *source* is,
        # so it is handed over.
        sacrifice_demands = sacrifice_taxes(
            self, controller_index, ability.cost.mana, "activate",
            source=permanent,
        )
        sacrifice_tax_victims = self._sacrifice_tax_victims(
            controller_index, sacrifice_demands
        )
        if isinstance(sacrifice_tax_victims, str):
            details = (
                f"{permanent.card.name}: {sacrifice_tax_victims} (CR 601.2h)"
            )
            self.log.append(details)
            return SimulationResult(permanent.card.name, False, "unsupported", details)
        # Ability cost taxes (Gloom: "Activated abilities of white enchantments
        # cost {3} more to activate"; the white-spell cast tax is applied
        # separately in cast_from_hand).
        extra_ability_tax, taxing_names = ability_cost_tax(
            self, controller_index, permanent, ability
        )
        if extra_ability_tax:
            required_cost["generic"] = required_cost.get("generic", 0) + extra_ability_tax
            self.log.append(f"{permanent.card.name}'s ability is taxed by {', '.join(taxing_names)}")
        # "This ability costs {1} less to activate for each Shrine you control."
        # (Sanctum of Tranquil Light.) After the tax, because CR 601.2f applies
        # increases before reductions, and clamped at zero because a cost cannot
        # go below {0} — the same clamp `reduce_cost` makes for a spell.
        discount = ability_self_reduction_amount(self, controller_index, permanent)
        if discount:
            before = required_cost.get("generic", 0)
            required_cost["generic"] = max(0, before - discount)
            self.log.append(
                f"{permanent.card.name}'s ability costs "
                f"{{{before - required_cost['generic']}}} less to activate"
            )
        # "Enchanted artifact's activated abilities cost {2} less to activate.
        # **This effect can't reduce the mana in that cost to less than one
        # mana.**" (Power Artifact.) The reduction is on the *Aura*, not on the
        # permanent whose ability it is, so it is read off what is attached
        # rather than off this card's own text.
        #
        # The floor is over the *whole* cost, coloured pips included — "the
        # mana in that cost", not the generic part of it — which is why it is
        # applied after the subtraction rather than as a clamp inside it. A {2}
        # ability reduced by {2} pays {1}, not nothing; a {B} ability is
        # already at the floor and pays {B}.
        aura_discount, aura_floor = attached_ability_cost_reduction(permanent)
        # "Activated abilities of creatures cost {1} less to activate. This
        # effect can't reduce the mana in that cost to less than one mana."
        # (Heartstone.) The identical rider from a permanent that enchants
        # nothing, so it is read off the board rather than off what is attached
        # -- and folded into the *same* application, because CR 601.2f applies
        # every reduction to one cost. Two applications would each measure the
        # floor against a cost the other had already cut.
        board_discount, reducing_names, board_floor = ability_cost_reduction(
            self, controller_index, permanent, ability
        )
        aura_discount += board_discount
        # The **highest** floor, for ``attached_ability_cost_reduction``'s
        # reason: two reductions must not cancel each other's protection
        # against a free ability.
        floor = max(aura_floor, board_floor)
        if reducing_names:
            self.log.append(
                f"{permanent.card.name}'s ability is cheapened by "
                f"{', '.join(reducing_names)}"
            )
        if aura_discount:
            before_total = sum(required_cost.values())
            generic = required_cost.get("generic", 0)
            coloured = before_total - generic
            reduced_generic = max(0, generic - aura_discount)
            if reduced_generic + coloured < floor:
                reduced_generic = max(0, floor - coloured)
            required_cost["generic"] = reduced_generic
            if before_total != reduced_generic + coloured:
                self.log.append(
                    f"{permanent.card.name}'s ability costs "
                    f"{{{before_total - reduced_generic - coloured}}} less to activate"
                )
        # "Note the type of mana spent to pay this activation cost." (Jeweled
        # Amulet, Ice Cauldron.) CR 107.4b's symbols, measured as the difference
        # the payment made to the pool rather than predicted from the cost: a
        # generic pip says how *much* is owed and never which symbol pays it,
        # and the payer's own choice — and any restricted bucket it drew on — is
        # only visible afterwards. Empty when nothing was charged, which is a
        # note of nothing and not an absent note.
        pool_before = dict(controller.mana_pool)
        if self.enforce_mana_costs and any(required_cost.values()):
            if not self._pay_mana_cost(
                controller, required_cost,
                purpose=PaymentPurpose(ACTIVATE, source=permanent),
            ):
                details = f"insufficient mana to activate {permanent.card.name}"
                self.log.append(details)
                return SimulationResult(permanent.card.name, False, "unsupported", details)
        mana_spent_for_cost = {
            symbol: spent
            for symbol in ("W", "U", "B", "R", "G", "C")
            if (spent := pool_before.get(symbol, 0)
                - controller.mana_pool.get(symbol, 0)) > 0
        }

        # **Nothing below this line refuses.** The mana payment above is the
        # last gate and is all-or-nothing (``_pay_mana_cost`` leaves the pool
        # untouched when it cannot pay), so from here on every cost collected
        # above is paid and the activation happens. A new refusal belongs above
        # the payment, with the others; a new cost belongs below it.

        # CR 601.2h: every other cost, paid at one moment.
        (
            exiled_for_cost, exiled_set_for_cost,
            graveyard_target_stamp_after_cost, milled_for_cost,
            target_permanent_index,
        ) = self._pay_activation_costs(
            ability=ability, ability_lower=ability_lower,
            activation_caps=activation_caps, controller=controller,
            controller_index=controller_index, cost_hand_index=cost_hand_index,
            counter_cost_permanent=counter_cost_permanent,
            counter_removal_permanent=counter_removal_permanent,
            counters_removed_for_cost=counters_removed_for_cost,
            discard_cost_card=discard_cost_card,
            discard_cost_cards=discard_cost_cards,
            exile_cost_choice=exile_cost_choice,
            exiled_for_cost=exiled_for_cost,
            exiled_set_for_cost=exiled_set_for_cost,
            graveyard_target_before_cost=graveyard_target_before_cost,
            graveyard_target_stamp_after_cost=graveyard_target_stamp_after_cost,
            life_owed=life_owed, loyalty_delta=loyalty_delta,
            permanent=permanent, requires_tap=requires_tap,
            return_cost_permanents=return_cost_permanents,
            sacrifice_also_permanent=sacrifice_also_permanent,
            sacrifice_attached_permanent=sacrifice_attached_permanent,
            sacrifice_cost_permanent=sacrifice_cost_permanent,
            sacrifice_cost_set=sacrifice_cost_set,
            sacrifice_tax_victims=sacrifice_tax_victims,
            tap_cost_permanents=tap_cost_permanents,
            target_permanent_index=target_permanent_index,
            untap_cost_permanent=untap_cost_permanent,
        )

        instruction = ability.instruction
        if (
            instruction.kind in {"sacrifice_self_for_mana", "add_mana_from_text"}
            and (
                instruction.payload.get("any_color", False)
                # "Add {B} or {R}": the chosen alternative rides the same
                # ``color`` key the any-colour shape uses; the handler holds it
                # to the printed alternatives.
                or instruction.payload.get("pips_choice")
                # "Add three mana in any combination of {R} and/or {G}" (Orcish
                # Lumberjack). The same channel again: the seat names one of the
                # printed symbols and the handler makes every unit that symbol.
                # Left off, the ability would always produce the first printed
                # colour however the seat answered.
                or instruction.payload.get("combination")
            )
        ):
            # Through ``_chosen_mana_color``, not the raising normaliser: the
            # wire's ``mana_color`` is a *symbol* and may be {C} — what every
            # land pays under Ritual of Subdual, and so what the AI's plan and
            # the client's colour fan send. "{C}" is no answer to "{B} or {R}"
            # (CR 105.1), so it names nothing and the handler's own default
            # stands; it used to raise ``ValueError`` out of the activation.
            selected_color = self._chosen_mana_color(mana_color)
            if selected_color is not None:
                instruction = OracleInstruction(
                    instruction.kind,
                    instruction.value,
                    {**instruction.payload, "color": selected_color},
                )


        # **CR 605.3b: an activated mana ability does not use the stack.** Which
        # abilities those are is CR 605.1a, and CR 605.1a is a question about
        # what the whole ability *does* — so it is asked of
        # ``mana_payment.is_mana_ability``, the one reader the five CR 602.5
        # gates at the top of this method already ask.
        #
        # It used to be a three-name set of instruction **kinds**
        # (``add_mana_from_text``, ``sacrifice_self_for_mana``,
        # ``sacrifice_creature_for_mana``), which is the same question answered
        # off the *first* step instead of the effect. Every "Add mana. ⟨rider⟩"
        # lowers to a ``sequence`` and every "…add {C}{C} instead" to an
        # ``if_then``, so **43 abilities in the pool** that CR 605.1a admits
        # went on the stack: the five Ice Age and five Tempest painlands, the
        # five Mercadian Masques depletion lands, the five Ice Age depletion
        # lands, the five Mana Batteries, the Urza tri-land cycle, Gemstone
        # Mine, Ancient Tomb, Elves of Deep Shadow and the rest.
        #
        # Three consequences, none of them a crash. The mana did not arrive
        # until the ability resolved, so it could not be produced during a cost
        # payment (CR 605.3a) — a seat mid-cast simply had no way to reach it.
        # The ability could be responded to and **countered** (CR 605.3b):
        # Imprison's "activates an ability … that isn't a mana ability" fired on
        # Elves of Deep Shadow and Metalworker, because the ``emit`` at the
        # bottom of this method derives that clause from *the site* on the
        # strength of the comment there — which was true of the kind set's three
        # kinds and false of the rule. And CR 605.3c's "can't be activated again
        # until it has resolved" had a window it should not have.
        #
        # The reverse direction was measured too, and is empty: nothing the kind
        # set admitted is outside CR 605.1a. This is a widening, not a swap.
        if is_mana_ability(ability):
            # "Choose a color. Add one mana of that color unless any player
            # pays {1}." (Rhystic Cave.) The choice is made as the ability
            # resolves (CR 608.2d), which for a mana ability is now (CR
            # 605.3b), so the colour named with this activation answers it —
            # delivered onto the choosing step, which the outer injection above
            # cannot reach. The tap seam does the same through the same helper.
            instruction = answer_color_choices(
                instruction, self._chosen_mana_color(mana_color)
            )
            # A second `card.name == "Basalt Monolith"` branch stood here,
            # refusing add_mana_from_text while the permanent was untapped. It
            # was unreachable: the {T} cost above has already run
            # `become_tapped`, which sets `tapped` unconditionally (helpers.py),
            # so a mana ability that pays {T} is always tapped by this point.
            # Confirmed by making it raise and running the suite.
            state_machine = OracleStateMachine(
                self,
                OracleExecutionContext(
                    caster=controller,
                    target=target_player,
                    card=permanent.card,
                    source_permanent=permanent,
                    # **And the X the activator announced** (CR 601.2b), for
                    # that same reason one field over: this context was built
                    # without it, so an announced X was readable from the queued
                    # path and simply absent from the inline one. Kyren Toy's
                    # "Add an amount of {C} equal to X plus one" removed the
                    # right number of counters and then made one mana, however
                    # many the seat announced — a mana ability being the *only*
                    # kind that comes down here, and the kind whose whole output
                    # the number decides.
                    x_value=x_value,
                    # The same last-known-information channel the queued path
                    # below records. An ability that resolves without touching
                    # the stack still had its cost paid, and an effect reading
                    # back what the cost ate must not depend on which of the
                    # two paths it came down.
                    choices={
                        "exiled_for_cost": exiled_for_cost,
                        "exiled_set_for_cost": list(exiled_set_for_cost),
                        "milled_for_cost": list(milled_for_cost),
                        "counters_removed_for_cost": counters_removed_for_cost,
                        "mana_spent_for_cost": mana_spent_for_cost,
                        "sacrificed_set_for_cost": list(sacrifice_cost_set),
                        "sacrificed_for_cost": sacrificed_for_cost,
                        "untapped_for_cost": untap_cost_permanent,
                        "tapped_for_cost": (
                            tap_cost_permanents[0] if tap_cost_permanents else None
                        ),
                        "discarded_for_cost": (
                            list(discard_cost_cards)
                            + (
                                [discard_cost_card]
                                if discard_cost_card is not None else []
                            )
                        ),
                        # **The colour the activator chose**, on the key every
                        # mana handler's choice branch already falls back to.
                        # The payload injection a hundred lines up delivers it
                        # by rewriting ``instruction.payload["color"]`` and is
                        # keyed on the **outer** kind — which was right while
                        # only three kinds came down here and blind the moment a
                        # ``sequence`` did, because a painland's ``pips_choice``
                        # sits on the nested ``add_mana_from_text``. Without
                        # this key an Adarkar Wastes asked for {U} would have
                        # produced the first printed alternative whatever the
                        # seat said. The queued path below has carried it as
                        # ``new_color`` since the Lace cycle; this is the same
                        # channel, so a handler still need not know which path
                        # resolved it.
                        "new_color": self._chosen_mana_color(mana_color),
                    },
                ),
            )
            # **CR 106.12: a land's mana ability with {T} in its cost is the
            # land being tapped for mana**, whatever else the cost asks for.
            # "{1}, {T}: Add {U}{B}" (Darkwater Catacombs), "{T}, Sacrifice
            # this land: Add {B}{B}" (Ebon Stronghold), "{T}, Remove a
            # depletion counter" (Peat Bog) are refused by the tap seam, which
            # runs only an ability whose whole cost is the tap — so they came
            # down here, and here nothing was announced: no Manabarbs damage,
            # no Mana Flare mana, no Wild Growth, no Contamination, and
            # Desolation never learned the seat had tapped a land for mana.
            # The same event the seam announces, around the same production
            # (``Game._land_tapped_for_mana``). A creature's mana ability is
            # not a land's, and a land's mana ability without {T} (a
            # sacrifice-only one) is not a tap.
            if ability.cost.requires_tap and permanent.has_type("land"):
                outcome: list = []

                def produce():
                    outcome.append(state_machine.run(instruction))
                    return self._chosen_mana_color(mana_color)

                self._land_tapped_for_mana(
                    controller_index, permanent, mana_color, produce,
                )
                supported, details = outcome[0]
            else:
                supported, details = state_machine.run(instruction)
            return SimulationResult(permanent.card.name, supported, ability.effect_kind, details)

        # A mixed-zone roles announcement becomes the three positional lists a
        # stack item already carries — ids for the battlefield slots, stamps for
        # the graveyard ones, and one index list beside them. Built here rather
        # than at the wire because the stamp has to be taken while the slot
        # still means what the activator chose (CR 601.2c): the cost above this
        # line may have put a card into the very pile the second slot counts
        # into.
        graveyard_stamps = graveyard_target_stamp_after_cost
        # Every seat the announcement named, where it named more than one
        # (``target_roles.ROLE_SEATS``); None for every roles ability the pool
        # holds today, each of which names at most one.
        role_seats = None
        if target_role_refs:
            (
                target_permanent_ids, target_permanent_index, graveyard_stamps,
                role_seat, role_seats,
            ) = self._role_announcement_stamps(target_role_refs)
            # A roles announcement's ids are settled *here* (the cost above may
            # have moved the graveyard slot the second role counts into), so its
            # seat is settled here too — the one case where CR 601.2c's identity
            # genuinely is not known before the cost is paid, and so the one case
            # that has to re-ask.
            #
            # Two announcements can answer "which seat", and they are asked in
            # the order of how directly the player said it. A **player role** is
            # the seat, named outright, and it goes on the one field that already
            # means it rather than beside it — a second arity there would leave
            # the resolution two answers to one question. Only where no role
            # named a seat does the seat come back off the ids, which is the
            # fallback every other item-building site uses through the same
            # seam. Two groups of one wave wrote these two arms independently
            # and neither is the other's special case.
            if role_seat is not None:
                announced_target_idx = role_seat
            elif target_player_index is None:
                from_ids = self.announced_target_seat(target_permanent_ids)
                if from_ids is not None:
                    announced_target_idx = from_ids
        self._stack_push(
            # CR 602.2b: an activated ability's targets were chosen when it
            # was activated, so it does not choose again here.
            targets_already_chosen=True,
            item=StackItem(
                activated=True,
                card=permanent.card,
                caster_index=controller_index,
                target_player_index=announced_target_idx,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_ids,
                target_graveyard_card=graveyard_stamps,
                x_value=x_value,
                ability_instruction=instruction,
                ability_effect_kind=ability.effect_kind,
                source_permanent=permanent,
                ability_text=ability.source_line,
                target_stack_item=target_stack_item,
                # What the ability's own sacrifice cost ate (CR 601.2h), for
                # an effect that reads it back — "Add an amount of {B} equal
                # to **the sacrificed artifact's** mana value" (Priest of
                # Yawgmoth). The permanent is off the battlefield by now, so
                # this is the only place it survives (CR 608.2h last-known
                # information), exactly as the casting path already records an
                # additional cost's sacrifice.
                choices={
                    "chosen_source": chosen_source,
                    # …and what an **exile** cost ate, on the same channel and
                    # for the same reason: the object is out of the game
                    # before this item is on the stack, so nothing else holds
                    # it (CR 608.2h).
                    "exiled_for_cost": exiled_for_cost,
                    "exiled_set_for_cost": list(exiled_set_for_cost),
                    # …and what a **mill** cost put into the graveyard
                    # (Charmed Pendant's "the milled card's mana cost").
                    "milled_for_cost": list(milled_for_cost),
                    # How many counters the cost's "remove any number of …"
                    # actually took (the Mana Batteries), on the same
                    # last-known-information channel as the sacrifice beside
                    # it: the counters are off the permanent before the ability
                    # is on the stack, so the number survives nowhere else.
                    "counters_removed_for_cost": counters_removed_for_cost,
                    # …and CR 107.4b's symbols the mana cost actually consumed
                    # ("Note the type of mana spent to pay this activation
                    # cost", Jeweled Amulet), measured off the pool rather than
                    # predicted from the cost: a generic pip never says which
                    # symbol paid it.
                    "mana_spent_for_cost": mana_spent_for_cost,
                    # …and the permanents an "any number of" sacrifice cost ate
                    # (Sword of the Ages), whose total power the effect reads
                    # back once they are cards in a graveyard.
                    "sacrificed_set_for_cost": list(sacrifice_cost_set),
                    "sacrificed_for_cost": sacrificed_for_cost,
                    # …and the land an **untap** cost paid with (Benthic
                    # Explorers), whose mana types the effect reads back. It is
                    # still on the battlefield, unlike every other record on
                    # this channel — but it is carried rather than re-found,
                    # because "that land" names the one the cost untapped and a
                    # board scan at resolution would name whichever one matches
                    # now (CR 608.2h).
                    "untapped_for_cost": untap_cost_permanent,
                    # "…deals damage equal to **the tapped creature's** power"
                    # (Unerring Sling). Beside the untap record and for its
                    # reason exactly: still on the battlefield, carried rather
                    # than re-found, because a board scan at resolution would
                    # name whichever creature its controller tapped since.
                    #
                    # The first of the chosen set, because the printed cost taps
                    # one; a card taping several and then naming "the tapped
                    # creature" is a sentence nobody has printed, and the
                    # lowering is what would have to decide which it meant.
                    "tapped_for_cost": (
                        tap_cost_permanents[0] if tap_cost_permanents else None
                    ),
                    # …and what its discard cost ate, for the same reason and
                    # on the same channel: "If the discarded card was a land
                    # card" (Land's Edge) is asked once the card is already in
                    # a graveyard. Both spellings of the cost feed it — the
                    # chosen cards and Jandor's Ring's history-named one — so
                    # the record does not depend on which clause charged it.
                    "discarded_for_cost": (
                        list(discard_cost_cards)
                        + ([discard_cost_card] if discard_cost_card is not None else [])
                    ),
                    # CR 601.2d's announced division, on the very key the
                    # cast side stamps it under — the shield handler reads
                    # ``context.choices[DIVIDED_TARGETS]`` and does not know
                    # whether a spell or an ability announced it (Serra's Hymn
                    # is the pool's first ability to print one). Each entry's
                    # chosen permanent is resolved to its **id** as it is
                    # stamped, for the reason the cast path gives: an index is
                    # not an address, and the battlefield renumbers the moment
                    # anything leaves it.
                    DIVIDED_TARGETS: divided_targets,
                    # The word a text-changing ability writes (Balduvian
                    # Shaman), on the key the cast side carries a text change's
                    # word on. Never "the color of your choice": that is not
                    # announced (CR 602.2b) but asked while the ability resolves
                    # (CR 608.2d, the ``choose_color`` step), and nothing reads
                    # it here for it any more.
                    "new_color": self._chosen_mana_color(mana_color),
                    # The word a text change replaces, beside the one it
                    # replaces it with. See the parameter's note above.
                    "old_color": self._normalize_mana_color(old_color),
                    # A seat per player role, where the announcement named two
                    # or more — beside the scalar above, which then holds the
                    # first. See ``target_roles.ROLE_SEATS``.
                    ROLE_SEATS: role_seats,
                },
            )
        )
        self.log.append(f"{permanent.card.name} ability added to stack")
        # "Whenever a player activates an ability of enchanted creature with
        # {T} in its activation cost that isn't a mana ability" (Imprison).
        #
        # Announced **after** the push, and that is the whole of why it is a
        # separate site from the tap event above: CR 603.3 puts the trigger on
        # the stack over the ability it fired on, and a card that counters
        # "that ability" needs the object to be there to be found. The item is
        # carried on the event so the counter resolves the one activation that
        # fired it rather than whatever is on top by then.
        #
        # Everything reaching this line is an ability that uses the stack —
        # this engine resolves its mana abilities inline above, which is
        # CR 605.3b — so the printed "that isn't a mana ability" is satisfied
        # by the site rather than by a second reading of the ability.
        #
        # **That sentence is load-bearing and it was false for a year.** The
        # inline branch above keyed on three instruction kinds where the rule
        # asks CR 605.1a, so 43 mana abilities reached this line and Imprison
        # fired on the ones with {T} in their cost. Deriving the clause from the
        # site is still right — it is exactly one reading of the rule rather
        # than two — but only because the site now asks the rule.
        emit(
            self, "nonmana_ability_activated",
            subject=permanent, seat=controller_index,
            requires_tap=bool(requires_tap),
            activated_ability_item=self.stack[-1] if self.stack else None,
        )
        return SimulationResult(permanent.card.name, True, ability.effect_kind, "queued")
    def _chosen_mana_color(self, mana_color: str | None) -> str | None:
        """The colour an activation announced, or None where it named none.

        ``_normalize_mana_color`` **raises** on anything outside WUBRG, which is
        right for every other caller: a text change that must replace a colour
        word has no honest answer but an error. This channel is different, and
        the difference is one symbol. ``ActionRequest.mana_color`` is a
        ``Literal[..., "C"]`` because the same wire field carries a *symbol* for
        the land-tap action (``chosen_color``) and a *colour* for the choice
        channel here — and CR 105.1 is explicit that colourless is not a colour,
        so ``"C"`` can never be an answer to "choose a color".

        Sent for an ability that offers no choice at all — clicking an Urza's
        Mine, a Sol Ring, any ``{T}: Add {C}`` — it reached the unconditional
        ``new_color`` normalisation below and raised ``ValueError`` out of the
        route, which the web layer turns into a 500. Read here as "no colour
        named", which is what it means.
        """
        if mana_color is None:
            return None
        if mana_color.strip().upper() not in {"W", "U", "B", "R", "G"}:
            return None
        return self._normalize_mana_color(mana_color)

    def _role_announcement_stamps(self, target_role_refs):
        """One mixed-zone roles announcement as ``(ids, indices, stamps, seat,
        seats)``.

        Three lists, all positional in role order, because that is what a
        ``StackItem`` already carries: an id per battlefield slot
        (``target_permanent_id``), a :class:`GraveyardTarget` per graveyard slot
        (``target_graveyard_card``), and one index list beside them that the
        resolution re-locates from. ``None`` fills each list wherever the other
        one answers, which is what keeps the three readable against each other —
        a reader holding slot 1 asks both and exactly one replies.

        The index is derived from the id rather than sent, for the reason ids
        exist: the activator chose a permanent, and where it sits is a fact
        about the board at this moment.

        A **player** slot answers with none of the three and with the scalar
        beside them instead: a stack item has carried the one player an
        announcement names under ``target_player_index`` since the first
        announcement to name one, and the resolution reads it back as
        ``context.target``. Returned as a fourth value rather than squeezed into
        a list, because it is the field every reader of "the player this
        targets" already reads.

        **Two player slots answer with a fifth value as well**: every seat
        named, positional in role order with ``None`` in the other slots
        (``target_roles.ROLE_SEATS``) — the list the item's ``choices`` carries so
        that slot 1's player is not read off slot 0's scalar. None where the
        announcement names at most one seat, which is every roles ability and
        spell the pool held before "target player … another target player"
        (Cultural Exchange) and leaves each of them exactly as it was. The
        scalar is then the **first** seat named. Both announcement paths call
        this — an activation always has, and a cast handed ``target_role_refs``
        does (``casting._cast_onto_stack``) — so a seat per role has one
        spelling going in and one coming out.
        """
        ids: list = []
        indices: list = []
        stamps: list = []
        seat: int | None = None
        seats: list = []
        for ref in target_role_refs:
            ref = ref if isinstance(ref, dict) else {}
            permanent_id = ref.get("permanent_id")
            if isinstance(permanent_id, int):
                found = self.find_permanent_by_id(permanent_id)
                ids.append(permanent_id)
                indices.append(
                    self.battlefield_index_of(found[1]) if found else None
                )
                stamps.append(None)
                seats.append(None)
                continue
            named_seat = ref.get("seat")
            if isinstance(named_seat, int) and not isinstance(named_seat, bool):
                if seat is None:
                    seat = named_seat
                ids.append(None)
                indices.append(None)
                stamps.append(None)
                seats.append(named_seat)
                continue
            seats.append(None)
            if ref.get("stack"):
                # A **stack** slot answers with none of the three either: the
                # spell it names rides ``target_stack_item``, the scalar an
                # activation has carried since Deathgrip, and every reader
                # fills the slot from there (``legality_roles.named_role_objects``).
                ids.append(None)
                indices.append(None)
                stamps.append(None)
                continue
            index = ref.get("graveyard_index")
            ids.append(None)
            indices.append(index if isinstance(index, int) else None)
            stamps.append(
                self.graveyard_target_at(ref.get("graveyard_seat"), index)
            )
        several = len([named for named in seats if named is not None]) > 1
        return ids, indices, stamps, seat, (seats if several else None)

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

        self.become_tapped(permanent)
        self._turn_face_up(permanent)
        self.log.append(f"{controller.name} tapped {permanent_name}")
        return True
