"""Casting a spell (CR 601): put it on the stack, having chosen targets,
modes and X, and paid its cost.

Everything here runs *before* the spell resolves. ``cast_from_hand`` is the
entry point and ``queue_from_hand`` does the work, through
``_cast_onto_stack``: CR 601.2a–i in order, every refusal before any payment,
and the push that finishes the cast (CR 601.2i).

What the cast asks on the way is a mixin each, composed onto ``Game``
directly after this one, and ``_cast_onto_stack`` calls its steps there in
CR order — each moved out of it whole at the 2,000-line cap:

* ``cast_announcement`` — where the spell is cast from and under what
  permission (CR 601.2a, 601.3), its modes (CR 601.2b, 700.2) and each
  announced mode's target gates (CR 601.2c);
* ``cast_additional_costs`` — the printed additional costs (CR 601.2b,
  601.2f–h), the optional ones a cast announces (kicker, buyback), the
  sacrifices a board tax adds (Drought), and whether every cost of the cast
  can be paid;
* ``cast_alternative_costs`` — the printed alternative cost (CR 118.9);
* ``cast_target_validation`` — the target gate (CR 601.2c), the count and
  the division (CR 601.2d), and the Aura enchant-noun helpers;
* ``pool_payment`` — the X a cast is for (CR 107.3) and the mana payment
  (CR 601.2g–h).
"""

from __future__ import annotations

import re

from ...cast_permissions import consume as consume_permission
from ...bare_announcements import (announced_fields, default_cast_target,
                                   names_an_object, seat_of_unseated_slot)
from ...cast_costs import (additional_costs, buyback_cost, cast_announces_x,
                           kicked, optional_x_offers)
from ...cast_prohibitions import cast_prohibition
from ...cast_restrictions import check_cast_timing
from ...cast_timing import (CAST_AT_INSTANT_SPEED, a_sorcery_could_be_cast,
                            sacrifices_at_cleanup_if_cast_at_instant_speed)
from ...damage_ledger import record_cast
from ...counter_conditions import spend_next_spell_promises
from ...divided_damage import divided_entry, stamped_entry
from ...faces import choose_a_face_refusal, spell_named
from ...classifier import classify_card
from ...cost_modifiers import (CostReduction, buyback_cost_reduction,
                               cost_reduction_for_cast, reduce_cost,
                               self_per_target_tax, spell_cost_tax,
                               spell_life_tax, spell_symbol_tax)
from ...flashback import is_flashback
from ...game_types import SimulationResult, StackItem, chosen_damage_source
from ...models import CardDefinition
from ...oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ...targeting import graveyard_target_spec, derive_cast_spec
from ...target_roles import ROLE_SEATS
from .cast_additional_costs import (_optional_cost_announcement,
                                    _optional_cost_totals, _taken_offers,
                                    optional_cost_taken)
from .cast_announcement import _mode_announcements


class SpellCastingMixin:
    def cast_from_hand(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        # The same announcement **one entry per role** — the shape
        # `activate_permanent_ability` has taken since Goblin Welder: each a
        # dict naming a ``permanent_id``, a ``seat``, or ``{"stack": True}``
        # (the spell `target_stack_index` names). The only spelling that can
        # say **two players** ("…target player controls … another target
        # player controls", Cultural Exchange): `target_player_index` is one
        # seat. Where given it is the announcement, and the two fields above
        # are derived from it (`_role_announcement_stamps`).
        target_role_refs: list[dict] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts shaped like ``ChosenMode``'s
        # fields (``index`` plus optional ``target_player_index`` /
        # ``target_permanent_index`` / ``target_stack_index``). None or one entry
        # behaves exactly as ``mode_index`` alone always has.
        mode_choices: list[dict] | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        # The same choice for a cost that eats **more than one** permanent
        # (Phyrexian Tribute's "sacrifice two creatures"): one index cannot name
        # two victims. By id, never by slot, because each sacrifice renumbers
        # the battlefield behind it -- the same channel and the same reason
        # `activate_permanent_ability` takes them.
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        # Which cards in the caster's graveyard pay "exile X cards from your
        # graveyard" (Skeletal Scrying, Haunting Misery), by graveyard slot,
        # the whole set at once -- the channel `activate_permanent_ability`
        # takes the same choice on. None is the deterministic pick.
        cost_graveyard_indices: list[int] | None = None,
        # "Buyback—Discard **two** cards" (Forbid): the cards after the one
        # `cost_hand_index` names, by position in the hand the caster is
        # looking at — the shape `alternative_cost_other_hand_indices` below
        # announces "and another card" on. None is the deterministic pick.
        cost_other_hand_indices: list[int] | None = None,
        # CR 118.9's choice, forwarded whole for the reason the cost fields
        # above are: dropping it here would resolve the spell having quietly
        # paid the mana cost the caller said they were replacing.
        alternative_cost: bool | None = None,
        alternative_cost_hand_index: int | None = None,
        # Which permanents pay the alternative cost's sacrifice / return / tap
        # half ("you may sacrifice a creature …", Mind Swords), by id. Its own
        # channel rather than `cost_permanent_ids`, because CR 118.9d keeps the
        # additional costs in force beside an alternative one and the two
        # payments would otherwise read one list.
        alternative_cost_permanent_ids: list[int] | None = None,
        # "You may discard an Island card **and another card** …" (Foil): which
        # further cards in hand pay the discard beyond the one
        # `alternative_cost_hand_index` names, by position in the hand the
        # caster is looking at. The caster's choice (CR 601.2h), so it is
        # announced; None is the deterministic pick, as for every cost choice
        # here.
        alternative_cost_other_hand_indices: list[int] | None = None,
        # CR 601.2b's *optional* additional cost, and how many times each offer
        # was taken: ``{"{1}{R}": 2, "{1}{G}": 1}``. Announced with the cast for
        # the reason every other cost choice here is — 601.2b is one step, and a
        # queued prompt would put the spell on the stack before its price was
        # known. Absent means the offers were declined, which is what an
        # *optional* cost means and the only default that cannot overcharge.
        optional_cost_payments: dict[str, int] | None = None,
        # CR 601.2b's *choice-shaped* additional cost: "As an additional cost
        # to cast this spell, choose a creature type" (Caller of the Hunt).
        # Announced with the cast for the reason every cost choice here is —
        # CR 601.2b is one step, and this one has nowhere else to go at all: the
        # spell's own P/T is defined by the answer (CR 604.3), so a queued
        # prompt would put a creature spell on the stack with no power. A seat
        # that names nothing gets `_default_cast_creature_type`, which keeps AI
        # and headless play unblocked exactly as the cost pickers above do.
        chosen_creature_type: str | None = None,
        # CR 609.7a's "a source of your choice", announced with the cast. Not a
        # target (CR 115.1) and not a cost, so it is its own trio of fields: a
        # battlefield permanent by seat and slot, or a spell on the stack by a
        # bottom-first index, exactly as `activate_permanent_ability` has taken
        # them since Jade Monolith.
        #
        # Prefixed `chosen_` where the activation path says plain `source_`,
        # because `source_seat` is already a local here — it is the seat whose
        # zone the spell is *leaving* (Grinning Totem's exile is not the
        # caster's), and a parameter of that name would be silently clobbered
        # by the zone lookup a hundred lines down.
        chosen_source_seat: int | None = None,
        chosen_source_permanent_index: int | None = None,
        chosen_source_stack_index: int | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_role_refs=target_role_refs,
            x_value=x_value,
            new_color=new_color,
            target_stack_index=target_stack_index,
            mode_index=mode_index,
            mode_choices=mode_choices,
            old_color=old_color,
            divided_targets=divided_targets,
            from_zone=from_zone,
            use_free_permission=use_free_permission,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_index=cost_hand_index,
            cost_graveyard_indices=cost_graveyard_indices,
            cost_other_hand_indices=cost_other_hand_indices,
            alternative_cost=alternative_cost,
            alternative_cost_hand_index=alternative_cost_hand_index,
            alternative_cost_permanent_ids=alternative_cost_permanent_ids,
            alternative_cost_other_hand_indices=alternative_cost_other_hand_indices,
            optional_cost_payments=optional_cost_payments,
            chosen_creature_type=chosen_creature_type,
            chosen_source_seat=chosen_source_seat,
            chosen_source_permanent_index=chosen_source_permanent_index,
            chosen_source_stack_index=chosen_source_stack_index,
        )
        if not queued.supported:
            return queued

        # Resolve the spell, then drain any triggers it (or the deaths it causes)
        # put on the stack, interleaving state-based-action checks (CR 704.3/603.3).
        self._settle()
        self.clear_priority_window()
        return SimulationResult(queued.card_name, True, queued.effect_kind, "resolved")

    def queue_from_hand(self, *args, **kwargs) -> SimulationResult:
        """Cast a spell — CR 601, start to finish — leaving it on the stack.

        A wrapper around the whole process for one reason, and the reason is the
        wrapper's shape: **everything CR 601.2 describes is one announcement**,
        and a trigger that fires part-way through it waits for the end of that
        announcement rather than going on the stack in the middle. Goremand
        sacrifices a creature to be cast; Havoc Jester's answer to that belongs
        *above* the Demon, not under it. See ``deferring_triggers``.
        """
        with self.deferring_triggers():
            result = self._cast_onto_stack(*args, **kwargs)
        if result.supported:
            # CR 704.3, the cast side of the sweep ``queue_permanent_ability``
            # runs for the same reason: CR 117.3c gives the caster priority
            # again the moment the spell is on the stack, and a cost paid on the
            # way there (a sacrifice, a life payment, a discard) is a state
            # change with no resolution behind it. ``_settle`` covers the
            # headless caller; the interactive path had nothing.
            self.check_state_based_actions()
        return result

    def _cast_onto_stack(
        self,
        caster_index: int,
        card_name: str,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # The chosen targets' stable ids, when the caller already knows them.
        # A pair of targets may sit on two battlefields, which one
        # `target_player_index` cannot express — see `_stack_push`.
        target_permanent_ids: list[int | None] | None = None,
        # The same announcement **one entry per role** — the shape
        # `activate_permanent_ability` has taken since Goblin Welder: each a
        # dict naming a ``permanent_id``, a ``seat``, or ``{"stack": True}``
        # (the spell `target_stack_index` names). The only spelling that can
        # say **two players** ("…target player controls … another target
        # player controls", Cultural Exchange): `target_player_index` is one
        # seat. Where given it is the announcement, and the two fields above
        # are derived from it (`_role_announcement_stamps`).
        target_role_refs: list[dict] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts shaped like ``ChosenMode``'s
        # fields (``index`` plus optional ``target_player_index`` /
        # ``target_permanent_index`` / ``target_stack_index``). None or one entry
        # behaves exactly as ``mode_index`` alone always has.
        mode_choices: list[dict] | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        from_zone: str = "hand",
        use_free_permission: bool | None = None,
        # Which permanent / which card in hand pays a printed additional cost
        # (CR 601.2b). The same shape `activate_permanent_ability` takes, and
        # for the same reason: the payer chooses, a cost is paid *during*
        # casting, and a queued prompt would put the spell on the stack before
        # its cost was collected. A seat that names neither gets the
        # deterministic pick, which keeps AI and headless play unblocked.
        cost_permanent_index: int | None = None,
        # The same choice for a cost that eats **more than one** permanent
        # (Phyrexian Tribute's "sacrifice two creatures"): one index cannot name
        # two victims. By id, never by slot, because each sacrifice renumbers
        # the battlefield behind it -- the same channel and the same reason
        # `activate_permanent_ability` takes them.
        cost_permanent_ids: list[int] | None = None,
        cost_hand_index: int | None = None,
        # …and which graveyard cards pay an "exile X cards from your
        # graveyard" cost, by slot (see `cast_from_hand`).
        cost_graveyard_indices: list[int] | None = None,
        # …and the further cards a "discard two cards" cost names (see
        # `cast_from_hand`). None is the deterministic pick.
        cost_other_hand_indices: list[int] | None = None,
        # CR 118.9's choice: whether to pay the spell's printed *alternative*
        # cost rather than its mana cost, and which card in hand pays the exile
        # half of it. Announced with the cast for the reason the additional
        # costs' choices are (CR 601.2b announces both, before targets and long
        # before payment), and defaulting to None — "pay the mana cost" — because
        # CR 118.9b makes an alternative cost optional and a default that took
        # it would cast every Force of Will for a life and a card.
        alternative_cost: bool | None = None,
        alternative_cost_hand_index: int | None = None,
        # …and which permanents pay its sacrifice / return / tap half, by id
        # (see `cast_from_hand`). None is the deterministic pick.
        alternative_cost_permanent_ids: list[int] | None = None,
        # …and which further cards pay its "and another card" (Foil), by hand
        # position (see `cast_from_hand`). None is the deterministic pick.
        alternative_cost_other_hand_indices: list[int] | None = None,
        # CR 601.2b's *optional* additional cost, and how many times each offer
        # was taken: ``{"{1}{R}": 2, "{1}{G}": 1}``. Announced with the cast for
        # the reason every other cost choice here is — 601.2b is one step, and a
        # queued prompt would put the spell on the stack before its price was
        # known. Absent means the offers were declined, which is what an
        # *optional* cost means and the only default that cannot overcharge.
        optional_cost_payments: dict[str, int] | None = None,
        # CR 601.2b's *choice-shaped* additional cost: "As an additional cost
        # to cast this spell, choose a creature type" (Caller of the Hunt).
        # Announced with the cast for the reason every cost choice here is —
        # CR 601.2b is one step, and this one has nowhere else to go at all: the
        # spell's own P/T is defined by the answer (CR 604.3), so a queued
        # prompt would put a creature spell on the stack with no power. A seat
        # that names nothing gets `_default_cast_creature_type`, which keeps AI
        # and headless play unblocked exactly as the cost pickers above do.
        chosen_creature_type: str | None = None,
        # CR 609.7a's "a source of your choice", announced with the cast. Not a
        # target (CR 115.1) and not a cost, so it is its own trio of fields: a
        # battlefield permanent by seat and slot, or a spell on the stack by a
        # bottom-first index, exactly as `activate_permanent_ability` has taken
        # them since Jade Monolith.
        #
        # Prefixed `chosen_` where the activation path says plain `source_`,
        # because `source_seat` is already a local here — it is the seat whose
        # zone the spell is *leaving* (Grinning Totem's exile is not the
        # caster's), and a parameter of that name would be silently clobbered
        # by the zone lookup a hundred lines down.
        chosen_source_seat: int | None = None,
        chosen_source_permanent_index: int | None = None,
        chosen_source_stack_index: int | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        # CR 601.2c, said one role at a time. Turned **here**, before anything
        # below reads a target field, into the channels a cast has always had:
        # the id list positional in role order (``None`` where the slot is not
        # a permanent), the scalar seat (the first player named) and — only
        # where two or more players were named — every seat by slot
        # (``targeting.ROLE_SEATS``), which is what the gate, the stack item
        # and the resolution read slot 1's player from. One translation, the
        # activation path's own, where each caller used to make it for itself
        # (the wire did, onto one seat).
        role_seats: "list | None" = None
        if target_role_refs:
            (
                target_permanent_ids, _role_indices, _role_stamps,
                role_seat, role_seats,
            ) = self._role_announcement_stamps(target_role_refs)
            if role_seat is not None:
                target_player_index = role_seat

        # CR 601.2a, 601.3: where the spell is cast from, and under what.
        located = self._spell_source(
            alternative_cost=alternative_cost, card_name=card_name,
            caster=caster, caster_index=caster_index, from_zone=from_zone,
        )
        if isinstance(located, SimulationResult):
            return located
        hand_index, permission, source_seat, source_zone = located

        # **Which face is this spell** (CR 709.3), settled here and nowhere
        # else: "a player chooses which half of a split card they are casting
        # before putting it onto the stack", and CR 709.3a has only that half
        # evaluated for whether it can be cast. So `held` is the card as its
        # zone holds it — the object the departure, the permission and the
        # commander record are keyed to, by identity — and `card` is the spell:
        # the half the caster named (`engine/faces.py`), or the card itself
        # when it has one face. Every gate, cost and target below reads `card`
        # and is therefore about the half, with nothing else to remember.
        #
        # A split card asked for by its whole spelling names no half, and is
        # refused rather than defaulted: there is no deterministic pick that is
        # not the engine choosing a different spell from the one that was meant.
        held = source_zone[hand_index]
        card = spell_named(held, card_name)
        if card is None:
            details = choose_a_face_refusal(held) or f"{card_name} is not a spell"
            self.log.append(details)
            return SimulationResult(card_name, False, None, details)
        classification = classify_card(card)
        # **An Aura announced by id alone** (CR 601.2c, CR 400.7). The id names
        # the object and its battlefield, so it is the whole announcement; the
        # slot every gate and the attachment below still read is derived from
        # it here, before any of them runs. See `Game.announced_target_slot` —
        # until this, every Aura in the pool was refused "requires a target"
        # when its host was named the way this engine asks for.
        #
        # Only where no slot was given: an index beside an id is the same
        # choice said twice, and the caller's own spelling is left alone.
        if (
            target_permanent_index is None
            and target_permanent_ids
            and "Aura" in card.type_line
            and card.primary_type not in ("instant", "sorcery")
        ):
            slot = self.announced_target_slot(target_permanent_ids)
            if slot is not None:
                target_player_index, target_permanent_index = slot
        extra_generic_tax = 0
        # The *coloured* half of the same taxes (Derelor's "{B}"). Its own
        # total because it is its own resource: a generic pip is payable with
        # anything and a coloured one is not (CR 202.1), so the two cannot
        # share a number without the tax becoming cheaper than the card.
        extra_pip_tax: dict[str, int] = {}

        if self.enforce_mana_costs and card.primary_type == "land":
            refusal = self._land_play_refusal(caster_index)
            if refusal is not None:
                details = refusal
                self.log.append(details)
                return SimulationResult(card.name, False, classification.effect_kind, details)

        # **CR 601.3: no rule or effect prohibits this player from casting
        # it** (and CR 305.1's twin for a land being played). One predicate,
        # `engine/cast_prohibitions.py`, asked here before any cost is
        # determined or paid — and asked by exactly two other readers, the
        # AI's proposal gate and the web's castable highlight, so what this
        # refuses is never proposed and never glows.
        #
        # This was a run of thirteen `if` blocks, each naming its own predicate
        # and each returning before anything was spent. The predicates are
        # unchanged and are asked in the order they stood here; what moved is
        # the *list*, because the two other readers kept their own shorter
        # copies of it (seven and two) and every ban added to this one alone
        # was a card whose owner was offered a cast that could not be made.
        # A new prohibition is a row in that module's table, never a block here.
        prohibition = cast_prohibition(self, caster_index, card, from_zone=from_zone)
        if prohibition is not None:
            self.log.append(prohibition.details)
            return SimulationResult(
                card.name, False, classification.effect_kind, prohibition.details
            )

        if (
            not mode_choices
            and target_player_index is None
            and target_permanent_ids is None
            and card.primary_type in ("instant", "sorcery")
            and graveyard_target_spec(
                card, compile_card_oracle(card), mode_index=mode_index
            ) is None
        ):
            # CR 601.2c, completed before CR 601.2f determines the cost: a
            # slot named beside **no seat** that the opposing seat does not
            # have is the caster's own (`seat_of_unseated_slot`) — the reading
            # `cast_target_refusal` judges it under, written onto the
            # announcement so the object carries the permanent it names.
            unseated = seat_of_unseated_slot(
                self, caster_index, target_permanent_index,
                self._spell_default_seat(caster_index),
            )
            if unseated is not None:
                target_player_index = unseated
                target_permanent_ids = [
                    self.permanent_at(
                        self.players[unseated], target_permanent_index
                    ).permanent_id
                ]
        # **A cast that owes a target and named none names the first one its
        # picker offers** (``engine/bare_announcements.py``) — here, because
        # CR 601.2c chooses the targets before CR 601.2f determines the cost,
        # and the taxes below are scoped to what the spell *targets*. A
        # headless caller's omission used to be answered at resolution by
        # whichever handler ran, from its own scan of a battlefield: the scan
        # knows what the sentence names and nothing of what may be targeted
        # (Ray of Command took a creature with shroud), the stack object
        # carried no target for CR 608.2b to re-check or for anything to
        # respond to, and a target nobody announced paid no targeting tax.
        #
        # The default is an entry of the list `cast_target_refusal` judges a
        # named target by, so every gate below sees an announcement it would
        # have accepted from a caller who named it. A "choose one or more"
        # cast names its targets on each mode, and is defaulted there.
        no_target_answers_x = False
        if not mode_choices and not names_an_object(
            target_permanent_index, target_permanent_ids,
            target_stack_index
            if target_stack_index is not None
            and 0 <= target_stack_index < len(self.stack) else None,
            None, divided_targets,
        ):
            default, no_target_answers_x = default_cast_target(
                self, caster_index, card,
                named_seat=target_player_index,
                optional_cost_payments=_taken_offers(optional_cost_payments),
                x_value=x_value, mode_index=mode_index,
            )
            named = announced_fields(self, default) if default is not None else {}
            if "target_player_index" in named:
                target_player_index = named["target_player_index"]
            if "target_permanent_index" in named:
                target_permanent_index = named["target_permanent_index"]
            if named.get("target_permanent_ids"):
                target_permanent_ids = named["target_permanent_ids"]
            if "target_stack_index" in named:
                target_stack_index = named["target_stack_index"]

        # What the spell points at, computed once: both taxes whose scope is
        # "that target this creature" need it, and the mana one is charged at
        # CR 601.2f while the life one is charged at 601.2h — the same fact,
        # asked at two moments.
        aimed_at = [
            found
            for found in (
                self.permanent_by_id(pid)
                for pid in (target_permanent_ids or [])
                if isinstance(pid, int)
            )
            if found is not None
        ]
        if not aimed_at and target_permanent_index is not None:
            found = self.permanent_at(
                target_player_index
                if target_player_index is not None else caster_index,
                target_permanent_index,
            )
            if found is not None:
                aimed_at = [found]

        # …and what it points at **on the stack** (Counterspell naming a
        # Kaervek's Torch). Resolved here rather than beside the target
        # validation below, because a static ability of an object on the stack
        # (CR 113.6b) can tax the spell that targets it and CR 601.2f charges
        # that before anything is paid. The validation reads this same local.
        target_stack_item = None
        if target_stack_index is not None and 0 <= target_stack_index < len(self.stack):
            target_stack_item = self.stack[target_stack_index]
        aimed_at_stack = [target_stack_item] if target_stack_item is not None else []

        spell_tax, taxing_names = spell_cost_tax(
            self, caster_index, card, aimed_at, aimed_at_stack
        )
        if spell_tax:
            extra_generic_tax += spell_tax
            self.log.append(f"{card.name} is taxed by {', '.join(taxing_names)}")

        # "Black spells you cast cost {B} more to cast." (Derelor.) Charged
        # beside the generic tax and at the same moment (CR 601.2f), into the
        # coloured part of the cost — so a caster with only Forests cannot pay
        # it, which is the whole difference between this and a {1}.
        pip_tax, pip_taxing_names = spell_symbol_tax(
            self, caster_index, card, aimed_at
        )
        if pip_tax:
            for symbol, count in pip_tax.items():
                extra_pip_tax[symbol] = extra_pip_tax.get(symbol, 0) + count
            self.log.append(
                f"{card.name} is taxed by {', '.join(pip_taxing_names)}"
            )

        # CR 903.8: the commander tax, {2} per previous cast of this commander
        # from the command zone. An additional cost like any other (CR 601.2f),
        # so it joins the same generic total rather than getting a payment path
        # of its own — which is what makes it interact correctly with the cost
        # increases above and with a cost reduction below.
        if from_zone == "command":
            commander_tax = self.commander_tax(caster_index, held)
            if commander_tax:
                extra_generic_tax += commander_tax
                self.log.append(
                    f"{card.name} costs an additional {{{commander_tax}}} "
                    f"(CR 903.8: commander tax)"
                )

        # "…that target this creature cost an additional 3 life to cast."
        # (Terror of the Peaks.) A tax in life rather than mana, scoped to what
        # the spell *targets* — so it is **determined** here, where the chosen
        # targets are known (CR 601.2c chooses them before 601.2f calculates the
        # cost), and refused rather than clamped when the caster cannot pay:
        # CR 119.4 caps the payment at the payer's life total and CR 601.2h
        # makes an unpayable cost an uncastable spell, not a free one.
        #
        # **Determined and not yet paid**, which is the correction. The life
        # used to come off right here, above the support gate, the timing gate,
        # the target gates, the additional costs and the mana — so every one of
        # those refusals left the caster having paid life for a spell that was
        # never cast, which CR 601.2 makes a rewind rather than a purchase. The
        # payment is now down with the mana, and everything between the two
        # points spends nothing.
        life_owed, life_taxing_names = spell_life_tax(self, caster_index, aimed_at)
        if life_owed and caster.life < life_owed:
            details = (
                f"{caster.name} cannot pay {life_owed} life to cast {card.name} "
                f"({', '.join(life_taxing_names)})"
            )
            self.log.append(details)
            return SimulationResult(
                card.name, False, classification.effect_kind, details
            )

        # CR 601.2f: increases first, then reductions.
        cost_reduction, reducing_names = cost_reduction_for_cast(self, caster_index, card)
        if cost_reduction:
            self.log.append(f"{card.name} costs less to cast ({', '.join(reducing_names)})")

        # Accept cards with supported triggered abilities (match classifier logic)
        if not classification.supported:
            if classification.reason == "unsupported triggered ability":
                # `compile_card_oracle` is imported at module level. The
                # function-level `from .oracle import ...` that stood here
                # resolved to `engine.mixins.stack.oracle`, which does not
                # exist — a leftover from the stack decomposition that raised
                # ModuleNotFoundError on every card reaching this branch.
                # Nothing caught it because it is only reachable for an
                # *unsupported* card, and every card in the pool was supported
                # until M21 arrived with 33 of them.
                program = compile_card_oracle(card)
                if any(getattr(program, "triggered_abilities", ())):
                    if any(t.supported for t in program.triggered_abilities):
                        return SimulationResult(card.name, True, program.effect_kind, "supported triggered ability")
            self.log.append(f"Unsupported card: {card.name} ({classification.reason})")
            return SimulationResult(card.name, False, classification.effect_kind, classification.reason)

        timing_denial = check_cast_timing(self, caster_index, card.oracle_text.lower())
        if timing_denial is not None:
            self.log.append(timing_denial)
            return SimulationResult(card.name, False, classification.effect_kind, timing_denial)

        # A printed additional cost (CR 601.2b). Only the costs this *zone*
        # charges: Demonic Embrace prints one card with two prices —
        # {1}{B}{B} from the hand and {1}{B}{B} plus 3 life plus a card from the
        # graveyard — so a cost naming a zone applies to that zone alone, and
        # an unmarked cost ("as an additional cost to cast this spell") applies
        # wherever the spell is cast from.
        #
        # Gathered here and *checked* below, once X has been announced. See the
        # gate's own note for why the check moved.
        cast_costs = tuple(
            cost for cost in additional_costs(card)
            if cost.from_zone is None or cost.from_zone == from_zone
        )

        # CR 601.2b's optional additional costs, announced now and folded into
        # the mana below. **Not** part of `_unpayable_additional_cost`: an offer
        # is not a price, so declining one cannot make a spell uncastable, and
        # taking one past what the pool holds is refused by the mana payment
        # itself — which is where CR 601.2h puts an unpayable mana cost, and
        # which spends nothing on the way to refusing.
        optional_paid, optional_denial = _optional_cost_announcement(
            card, cast_costs, optional_cost_payments,
        )
        if optional_denial is not None:
            self.log.append(optional_denial)
            return SimulationResult(
                card.name, False, classification.effect_kind, optional_denial,
            )
        # CR 601.2b's choice-shaped price, announced here — beside the optional
        # offers above and before any mana is spent, which is where CR 601.2b
        # puts every choice a cast makes. It charges nothing, so there is no
        # CR 601.2h gate to pass: every creature type is a legal answer.
        #
        # Refused rather than repaired when the word is not a creature type
        # (idiom 9): a picker's list is only true if the engine declines what is
        # not on it, and a silently-corrected answer would make the spell's own
        # P/T disagree with what the player chose.
        chosen_type_word: str | None = None
        if any(cost.choose_creature_type for cost in cast_costs):
            from ...grammar.vocabulary import CREATURE_TYPES

            if chosen_creature_type is not None:
                chosen_type_word = str(chosen_creature_type).strip().lower()
                if chosen_type_word not in CREATURE_TYPES:
                    denial = (
                        f"{chosen_creature_type} is not a creature type "
                        f"(CR 601.2b, CR 205.3m)"
                    )
                    self.log.append(denial)
                    return SimulationResult(
                        card.name, False, classification.effect_kind, denial,
                    )
            else:
                chosen_type_word = self._default_cast_creature_type(
                    caster_index, card
                )
            self.log.append(
                f"{caster.name} chose {chosen_type_word} to cast {card.name}"
            )

        # "Buyback costs cost {2} less." (Memory Crystal.) CR 601.2f applied to
        # CR 702.27a's offer, so it is read here — where the offer's symbols
        # become mana this cast owes — and nowhere near the spell's own mana
        # cost, which this modifier says nothing about.
        #
        # Only the buyback offer is reduced, never every optional cost this
        # spell prints: Primitive Justice's "you may pay {1}{R} and/or {1}{G}"
        # is CR 601.2b's repeated offer and no keyword at all, and reducing it
        # would be a card Memory Crystal does not print. The offer is picked out
        # by asking ``cast_costs.buyback_cost`` for this card's key — the same
        # reader ``buyback_paid`` uses at resolution, so the offer this
        # discounts is exactly the offer that buys the card back.
        buyback_key = buyback_cost(card.oracle_text or "")
        buyback_off, buyback_by = (
            buyback_cost_reduction(self) if buyback_key is not None else (0, [])
        )
        # "Kicker {X}" (Verdeloth the Ancient), "Kicker {X}{2}" (Kangee). An X
        # that lives in an *offer* (CR 107.3a's "additional cost with an {X} in
        # it"), so CR 601.2b's two announcements depend on each other: a caster
        # who took the offer names a number and pays for it just below, and one
        # who declined names none. The number is settled here, before anything
        # reads it, so a stray X sent with a declined kicker cannot reach the
        # permanent ("create X Saprolings") by another road -- and an X nobody
        # announced for a kicker that *was* taken is the 0 it reads as.
        if optional_x_offers(card, from_zone=from_zone):
            if cast_announces_x(card, from_zone=from_zone, taken=optional_paid):
                x_value = max(0, int(x_value or 0))
            else:
                x_value = None
        # "Spend only colored mana on X. No more than one mana of each color
        # may be spent this way." (Emblazoned Golem's "Kicker {X}".) The X of
        # such an offer is not generic mana: it is one unit of each of X
        # colours, and *which* colours is the payer's CR 601.2h choice. So the
        # offer contributes only its non-X part to the taxes below, and the
        # candidate colourings travel to the payment, which takes the first
        # the pool can pay with real units of those colours.
        #
        # ``((),)`` -- one choice, of nothing -- for every other cast, so the
        # payment below makes exactly one pass and sets nothing aside.
        offer_x_colorings: tuple[tuple[str, ...], ...] = ((),)
        for offer, times in _optional_cost_totals(cast_costs, optional_paid):
            colorings = offer.x_colorings(x_value)
            if colorings is None:
                charged = offer.cost_at(x_value)
            elif not colorings:
                # There are five colours, so no X above five can be paid one
                # mana of each. Refused here -- before any cost is paid, and
                # whether or not this game charges mana -- because the sentence
                # bounds the announcement itself: an X the cost cannot be paid
                # at is not one the caster may name (CR 601.2h, CR 601.2e).
                refusal = (
                    f"{card.name}: X can't be {x_value} -- no more than one "
                    f"mana of each color may be spent on X"
                )
                self.log.append(refusal)
                return SimulationResult(
                    card.name, False, classification.effect_kind, refusal,
                )
            else:
                charged = offer.cost_at(0)
                offer_x_colorings = colorings
            if buyback_off and offer.symbols == buyback_key:
                # Through ``reduce_cost``, the one place CR 118.7's arithmetic
                # lives: a generic reduction touches only the generic component
                # and clamps at zero, so a buyback of {1} under two Crystals is
                # free rather than negative.
                charged = reduce_cost(charged, CostReduction(generic=buyback_off))
                self.log.append(
                    f"{card.name}'s buyback costs {{{buyback_off}}} less "
                    f"({', '.join(sorted(set(buyback_by)))})"
                )
            for symbol, count in charged.items():
                if symbol == "generic":
                    extra_generic_tax += count * times
                else:
                    extra_pip_tax[symbol] = (
                        extra_pip_tax.get(symbol, 0) + count * times
                    )
        # "Kicker—**{2}{B}**, Discard a creature card." (Dralnu's Pet.) The
        # mana clause of an optional price that is not only mana: folded into
        # the same payment as the offers above, and only for the caster who
        # took the price — through the one reader the gate and the collector
        # below skip an untaken offer by, so the mana and the discard are
        # charged together or not at all.
        for cost in cast_costs:
            if cost.mana_symbols and optional_cost_taken(cost, optional_paid):
                for symbol, count in cost.mana_cost.items():
                    if symbol == "generic":
                        extra_generic_tax += count
                    else:
                        extra_pip_tax[symbol] = extra_pip_tax.get(symbol, 0) + count

        # Resolve the named discard **here**, while `cost_hand_index` still
        # indexes the hand the caster was looking at. The spell leaves that hand
        # further down, and every card after it slides up a slot — so an index
        # read afterwards names the neighbour, and one past the shortened end
        # fell through to a bare `0` and discarded the *first* card in hand. A
        # cast that names a card it cannot pay with is refused rather than
        # silently repointed, before any mana is spent.
        cost_hand_cards, cost_denial = self._resolve_discard_cost_cards(
            caster_index, card, cast_costs,
            cost_hand_index=cost_hand_index,
            cost_other_hand_indices=cost_other_hand_indices,
            spell_hand_index=hand_index if from_zone == "hand" else None,
            x_value=x_value,
        )
        if cost_denial is not None:
            self.log.append(cost_denial)
            return SimulationResult(card.name, False, classification.effect_kind, cost_denial)

        # The **alternative** cost (CR 118.9), announced in the same step as the
        # additional costs above (CR 601.2b) and resolved here for the same
        # reason the discard is: the card that pays it is named by an index into
        # the hand the caster is looking at, and that hand still holds the spell.
        # A cast that names a card it cannot pay with is refused before anything
        # is spent, never repointed at a neighbour.
        chosen_alternative, alternative_card, alternative_denial = (
            self._resolve_alternative_cost(
                caster_index, card,
                taking_it=alternative_cost,
                named_hand_index=alternative_cost_hand_index,
                spell_hand_index=hand_index if from_zone == "hand" else None,
                # CR 118.9b: the permission this cast is made under may
                # *require* an alternative cost — flashback's (CR 702.34a).
                # Then that cost is the announcement, whatever the caller
                # said, and CR 118.9a leaves no room for a second.
                required=permission.cost if permission is not None else None,
            )
        )
        if alternative_denial is None:
            # …and which permanents pay its sacrifice / return / tap half, named
            # by id and checked now, for the hand card's reason above: a named
            # permanent that cannot pay is a refusal with nothing spent, never
            # a quiet slide onto the default pick.
            alternative_permanents, alternative_denial = (
                self._resolve_alternative_cost_permanents(
                    caster_index, card, chosen_alternative,
                    alternative_cost_permanent_ids,
                )
            )
        alternative_others: "list[CardDefinition]" = []
        if alternative_denial is None:
            # …and which further cards pay its "and another card" (Foil),
            # resolved to cards now for the hand card's reason above.
            alternative_others, alternative_denial = (
                self._resolve_alternative_cost_others(
                    caster_index, card, chosen_alternative,
                    named_hand_index=alternative_cost_hand_index,
                    named_others=alternative_cost_other_hand_indices,
                    spell_hand_index=hand_index if from_zone == "hand" else None,
                )
            )
        if alternative_denial is not None:
            self.log.append(alternative_denial)
            return SimulationResult(
                card.name, False, classification.effect_kind, alternative_denial
            )

        # "Choose one or more —": the modes are chosen as the spell is cast
        # (CR 601.2b) and are checked here, before any mana leaves the pool, so
        # a card that does not print the head cannot be handed two modes.
        chosen_modes, mode_denial = self._resolve_chosen_modes(card, mode_choices)
        if mode_denial is not None:
            self.log.append(mode_denial)
            return SimulationResult(card.name, False, classification.effect_kind, mode_denial)
        for mode in chosen_modes:
            # …and the same default for each mode of a "choose one or more"
            # cast that owes a target and named none (CR 601.2c, per mode).
            if names_an_object(
                mode.target_permanent_index, None, mode.target_stack_item,
            ):
                continue
            default, _unanswerable = default_cast_target(
                self, caster_index, card,
                named_seat=mode.target_player_index,
                optional_cost_payments=optional_paid,
                x_value=x_value, mode_index=mode.index,
            )
            named = announced_fields(self, default) if default is not None else {}
            if "target_player_index" in named:
                mode.target_player_index = named["target_player_index"]
            if "target_permanent_index" in named:
                mode.target_permanent_index = named["target_permanent_index"]
            if "target_stack_item" in named:
                mode.target_stack_item = named["target_stack_item"]
        if chosen_modes:
            # Everything that reads one mode reads the first chosen one
            # (CR 608.2c resolves them in printed order, and the list is held in
            # that order), so a single-mode reader sees a mode this spell really
            # has rather than None.
            mode_index = chosen_modes[0].index

        # The explicitly chosen target spell on the stack (Counterspell, Fork)
        # was resolved with the cost above — CR 601.2f charges a tax imposed by
        # an object on the stack before any mana is paid, so the answer is
        # needed there and one reading of `target_stack_index` is what keeps
        # the tax and the validation talking about the same object.

        # CR 601.2c, once per announced mode: the target gates.
        mode_refusal = self._mode_target_refusal(
            card=card, caster_index=caster_index, chosen_modes=chosen_modes,
            classification=classification, divided_targets=divided_targets,
            from_zone=from_zone, mode_index=mode_index,
            no_target_answers_x=no_target_answers_x,
            optional_paid=optional_paid, role_seats=role_seats,
            target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index,
            target_player_index=target_player_index,
            target_stack_item=target_stack_item, x_value=x_value,
        )
        if mode_refusal is not None:
            return mode_refusal

        # A divided spell's cross-seat target list: sanity-check every entry so a
        # stale battlefield index can't crash resolution.
        #
        # Whether the caller sent the list **empty** is kept, because the
        # cleaning below folds an empty list into "no list": for the one shape
        # that may name nobody ("each of up to three targets") an explicit
        # empty list is that announcement, and the division gate reads it.
        named_no_division_targets = (
            divided_targets is not None and not divided_targets
        )
        if divided_targets is not None:
            cleaned: list[tuple] = []
            for entry in divided_targets:
                seat, index, share = divided_entry(entry)
                if not (isinstance(seat, int) and 0 <= seat < len(self.players)):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target seat")
                if index is not None and not (
                    isinstance(index, int) and 0 <= index < len(self.players[seat].battlefield)
                ):
                    return SimulationResult(card.name, False, classification.effect_kind, "invalid divided target")
                # **The chosen permanent's id, resolved now.** An index is not
                # an address: the battlefield renumbers as soon as anything
                # leaves it, so an index carried from CR 601.2c's announcement
                # to the resolution can name a *different* permanent — and the
                # handlers' bounds check is satisfied by it, so the spell hits
                # the wrong creature rather than fizzling. Pyrotechnics
                # announced 3 damage to the second of two creatures, the first
                # left in response, and the survivor took the 1 the departed one
                # had been assigned.
                #
                # Resolved here because this is the last moment the index and
                # the board agree (CR 400.7 gives the id its meaning), which is
                # the same reason `_stack_push` stamps one for the older
                # multi-target list.
                #
                # The share stays ``None`` where none was announced: it is what
                # every evenly-divided spell and every non-interactive caller
                # sends, and a 0 there would say a division of nothing was
                # announced.
                chosen = (
                    self.permanent_at(self.players[seat], index)
                    if index is not None else None
                )
                cleaned.append(stamped_entry(
                    seat, index, share,
                    None if chosen is None else chosen.permanent_id,
                ))
            divided_targets = cleaned or None

        # CR 601.2c under a requirement an *opponent's permanent* prints about
        # this announcement: "While an opponent is choosing targets as part of
        # casting a spell they control…, that player must choose at least one
        # Flagbearer on the battlefield if able." (Standard Bearer.) Asked of
        # the whole announcement — every mode's targets and the division
        # together — because with more than one slot the rule is about the set
        # and not about any one target, and asked here, after every gate above
        # has said each named target is legal and before anything is paid.
        # Free on every board with no such permanent on it.
        required_refusal = self.cast_target_requirement_refusal(
            caster_index, card,
            announcements=_mode_announcements(
                chosen_modes, mode_index, target_player_index,
                target_permanent_index, target_permanent_ids, target_stack_item,
            ),
            divided_targets=divided_targets,
            from_zone=from_zone,
            optional_cost_payments=optional_paid,
        )
        if required_refusal is not None:
            self.log.append(required_refusal)
            return SimulationResult(
                card.name, False, classification.effect_kind, required_refusal
            )

        # "This spell costs {1} more to cast for each target beyond the first."
        # (Fireball) / "This spell costs 3 life more to cast for each target."
        # (Phyrexian Purge.) A spell's own increase, sized by how many targets it
        # chose — CR 601.2c settles the targets before CR 601.2f calculates the
        # cost, which is what makes the sentence answerable at all.
        #
        # Read off `cost_modifiers.self_per_target_tax`, the table the support
        # gate and the parse census also ask, rather than off a substring here:
        # this used to be Fireball's own sentence written out in this function
        # and again as a literal in parse_coverage, and Phyrexian Purge is the
        # second card that shares the shape.
        per_target = self_per_target_tax(card.oracle_text or "")
        if per_target is not None:
            # The chosen targets: the cross-seat divided list, a list of
            # creature indices, the same list by id, or a single one.
            if divided_targets is not None:
                num_targets = len(divided_targets)
            elif isinstance(target_permanent_index, list):
                num_targets = len([i for i in target_permanent_index if isinstance(i, int)])
            elif target_permanent_ids:
                num_targets = len(
                    [i for i in target_permanent_ids if isinstance(i, int)]
                )
            elif target_permanent_index is not None:
                num_targets = 1
            else:
                # A seat and nothing else. For a spell whose target list is
                # **open-ended** — "Destroy any number of target creatures" —
                # that is an announcement of no targets at all, and CR 601.2c
                # allows it: the caster is charged nothing and the spell
                # destroys nothing. For every other spell the seat *is* the
                # target (Fireball to the face), so one it is. Read off
                # `derive_cast_spec`'s `unbounded_targets`, which is the general
                # shape rather than a card, and asked only in this branch so
                # every named-target path stays exactly what it was.
                spec = derive_cast_spec(card, compile_card_oracle(card)) or {}
                num_targets = 0 if spec.get("unbounded_targets") else 1
            owed = per_target.owed(num_targets)
            if per_target.life:
                # CR 118.3b: life is not mana, so it joins the life the board's
                # taxes owe rather than the generic total — a {R} cannot pay it.
                life_owed += owed
                if owed:
                    life_taxing_names = [*life_taxing_names, card.name]
                if caster.life < life_owed:
                    details = (
                        f"{caster.name} cannot pay {life_owed} life to cast "
                        f"{card.name} for {num_targets} target(s)"
                    )
                    self.log.append(details)
                    return SimulationResult(
                        card.name, False, classification.effect_kind, details,
                    )
            else:
                extra_generic_tax += owed

        # CR 107.3, 601.2b: the X this cast is for.
        x_settled = self._resolved_cast_x(
            card=card, caster=caster, caster_index=caster_index,
            classification=classification, cost_reduction=cost_reduction,
            extra_generic_tax=extra_generic_tax, extra_pip_tax=extra_pip_tax,
            mode_index=mode_index, target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index,
            target_player_index=target_player_index,
            target_stack_item=target_stack_item, x_value=x_value,
        )
        if isinstance(x_settled, SimulationResult):
            return x_settled
        announced_x, resolved_x_value, x_colors, x_mana_spent = x_settled

        # CR 601.2c–d, X now a number: the target count and the division.
        divided = self._settled_cast_division(
            announced_x=announced_x, card=card, caster_index=caster_index,
            chosen_modes=chosen_modes, classification=classification,
            divided_targets=divided_targets, from_zone=from_zone,
            mode_index=mode_index,
            named_no_division_targets=named_no_division_targets,
            optional_paid=optional_paid, resolved_x_value=resolved_x_value,
            target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index,
            target_player_index=target_player_index,
            target_stack_item=target_stack_item, x_value=x_value,
        )
        if isinstance(divided, SimulationResult):
            return divided
        divided_targets, target_player_index = divided

        # CR 601.2h: can every cost of this cast be paid? Nothing is spent yet.
        costs_checked = self._checked_cast_costs(
            card=card, cast_costs=cast_costs, caster_index=caster_index,
            chosen_alternative=chosen_alternative,
            classification=classification,
            cost_graveyard_indices=cost_graveyard_indices,
            cost_permanent_ids=cost_permanent_ids,
            cost_permanent_index=cost_permanent_index, from_zone=from_zone,
            hand_index=hand_index, life_owed=life_owed,
            optional_paid=optional_paid, resolved_x_value=resolved_x_value,
            source_seat=source_seat,
        )
        if isinstance(costs_checked, SimulationResult):
            return costs_checked
        owed, resolved_x_value, spell_graveyard_slot = costs_checked

        # CR 601.2g–h: the mana payment, or the waiver.
        mana_paid = self._pay_cast_mana(
            card=card, caster=caster, caster_index=caster_index,
            chosen_alternative=chosen_alternative,
            classification=classification, cost_reduction=cost_reduction,
            extra_generic_tax=extra_generic_tax, extra_pip_tax=extra_pip_tax,
            from_zone=from_zone, held=held,
            offer_x_colorings=offer_x_colorings, permission=permission,
            resolved_x_value=resolved_x_value,
            use_free_permission=use_free_permission, x_colors=x_colors,
            x_mana_spent=x_mana_spent,
        )
        if isinstance(mana_paid, SimulationResult):
            return mana_paid
        permission, resolved_x_value, x_mana_spent = mana_paid

        # A card played out of exile leaves it deliberately (CR 400.7 makes it a
        # new object wherever it lands), so the record that said it was face
        # down stops speaking for it — otherwise the *next* effect to exile the
        # same card would find that record alive and hide it from the table.
        # That retirement is the departure seam's, which is why this is not a
        # ``pop``: one transition out of exile, thirteen sites, one place for
        # anything that must happen when a card leaves.
        if from_zone == "exile":
            self.take_card_from_exile(source_seat, held)
        else:
            del source_zone[hand_index]
        # Now, and not before: the spell is no longer in the hand, so it cannot
        # be discarded to pay for itself, and the creature it eats is gone from
        # the battlefield before the spell is on the stack.
        # CR 118.9d keeps the additional costs in force alongside an
        # alternative one, so both are paid, in the order CR 601.2h leaves free.
        self._pay_alternative_cost(
            caster_index, card, chosen_alternative, alternative_card,
            named_permanents=alternative_permanents,
            other_cards=alternative_others,
        )
        # CR 601.2f's increases, in life. Gated far above, where the targets
        # settle what they come to, and paid here with every other cost —
        # nothing between the two points spends anything, so a refusal up there
        # costs the caster exactly nothing.
        if life_owed:
            caster.life -= life_owed
            self.log.append(
                f"{caster.name} paid {life_owed} life to cast {card.name} "
                f"({', '.join(life_taxing_names)})"
            )
        cost_spoils = self._pay_additional_costs(
            caster_index, card, cast_costs,
            cost_permanent_index=cost_permanent_index,
            cost_permanent_ids=cost_permanent_ids,
            cost_hand_cards=cost_hand_cards,
            x_value=resolved_x_value,
            taken=optional_paid,
            # Re-counted for a spell that has just left the same pile: the
            # gate above refused the spell's own slot, and every slot above it
            # slid down one when it went to the stack.
            cost_graveyard_indices=(
                cost_graveyard_indices
                if cost_graveyard_indices is None or spell_graveyard_slot is None
                else [
                    slot - 1 if slot > spell_graveyard_slot else slot
                    for slot in cost_graveyard_indices
                ]
            ),
        )
        sacrificed_for_cost = cost_spoils["sacrificed_for_cost"]
        exiled_for_cost = cost_spoils["exiled_for_cost"]
        # Drought's imposed sacrifices, paid with the printed ones and at the
        # same moment. The victims were picked before the mana was spent, so a
        # board that has not changed since pays exactly what the gate measured.
        self._pay_sacrifice_tax(owed, f"to cast {card.name}")
        if permission is not None:
            consume_permission(self, permission, held)
        if from_zone == "command":
            # CR 903.8's "each previous time" is counted once the cast is
            # announced and paid for, so the tax charged above is the one this
            # cast owed and the next one is {2} higher. A cast that failed
            # anywhere above returned before here and costs nothing.
            self.record_commander_cast(caster_index, held)
        if from_zone != "hand":
            # Whose pile it left, which is not always the caster's: a grant may
            # open somebody else's exile (Grinning Totem). The permission is the
            # only thing that knows, so it is asked rather than assumed.
            pile_seat = (
                permission.zone_seat if permission is not None else caster_index
            )
            self.log.append(
                f"{card.name} cast from {self.players[pile_seat].name}'s {from_zone}"
            )

        if card.primary_type != "land":
            # Determine which stack spell this one targets. An explicit choice
            # (target_stack_item) wins; otherwise fall back to the topmost legal
            # spell so AI and untargeted casts still work.
            target_stack_item_val = target_stack_item
            enumerated = False
            if target_stack_item_val is None:
                # The gate's own enumeration first (`default_stack_target`):
                # the topmost object the printed phrase admits, so the default
                # is a target `cast_stack_target_refusal` would have accepted
                # by name. The text reading below is what is left for the
                # shape that gate declines — a permanent spell, whose "counter
                # target spell" is an entry trigger's — and it is not consulted
                # where the enumeration answered, an answer of "nothing"
                # included. A modal spell is always answered, for the mode it
                # announced.
                enumerated, target_stack_item_val = self.default_stack_target(
                    caster_index, card, from_zone=from_zone,
                    mode_index=mode_index,
                )
            if (
                not enumerated
                and target_stack_item_val is None
                and self.stack
                and "counter target" in card.oracle_text.lower()
            ):
                color_match = re.search(r"counter target (\w+) spell", card.oracle_text.lower())
                color_filter: str | None = None
                if color_match:
                    color_filter = _COLOR_WORD_TO_SYMBOL.get(color_match.group(1))
                # The spell's colours through ``object_colors``, so a stack
                # object Celestial Dawn has made white is what "counter target
                # white spell" finds — the same reading `_shares_a_color`
                # twenty lines up already makes for the other half of CR 105.
                from ...object_colors import object_colors

                matching = [
                    it for it in self.stack
                    if not color_filter
                    or color_filter in object_colors(
                        self, it.card, getattr(it, "caster_index", None)
                    )
                ]
                if matching:
                    target_stack_item_val = matching[-1]
            spell_item = StackItem(
                    card=card,
                    caster_index=caster_index,
                    # CR 108.3/400.3: the seat whose pile the card left owns
                    # it — the caster's for a hand, a command zone or their own
                    # graveyard, the opponent's for Grinning Totem's exile — and
                    # that seat's zones are where it goes when it leaves the
                    # stack, whoever cast it.
                    owner_index=source_seat,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_ids,
                    x_value=resolved_x_value,
                    target_stack_item=target_stack_item_val,
                    chosen_mode_index=mode_index,
                    chosen_modes=chosen_modes,
                    cast_from_zone=from_zone,
                    exile_instead_of_graveyard=bool(
                        permission is not None and permission.exile_instead
                    ),
                    # CR 702.34a: "If the flashback cost was paid, exile this
                    # card instead of putting it anywhere else any time it
                    # would leave the stack." Whether it was paid is this
                    # cast's own fact — the cost it was announced under — and
                    # the stack object is the only thing that outlives the
                    # announcement to say so.
                    flashback=is_flashback(chosen_alternative),
                    choices={
                        "divided_targets": divided_targets,
                        "new_color": new_color,
                        "old_color": old_color,
                        # What the additional cost ate, for the spell whose
                        # effect asks about it ("…equal to the sacrificed
                        # creature's mana value"). The Permanent is off the
                        # battlefield by now, so this is last-known information
                        # (CR 608.2h) held on the stack item rather than a
                        # second lookup that could not succeed.
                        # How many times each CR 601.2b optional additional
                        # cost was taken. The pool is empty by resolution
                        # (CR 500.5) and the spell is on the stack, so nothing
                        # in the game state can answer "for each additional
                        # {1}{R} you paid" — this is where the announcement
                        # survives, beside the other costs' spoils and for the
                        # same reason.
                        "additional_costs_paid": optional_paid,
                        # CR 609.7a's chosen damage source, resolved to the
                        # object it names. On the same channel the activation
                        # path writes, because the handler behind it is the same
                        # handler: `handlers/prevention.chosen_shield_source`
                        # reads this key first, ahead of every fallback that
                        # reads a target slot instead. Without it a *spell* that
                        # names a source could only be given one by spending one
                        # of its own target slots, which is what kept Honorable
                        # Passage sourceless and Kor Chant unsupported.
                        "chosen_source": chosen_damage_source(
                            self,
                            seat=chosen_source_seat,
                            permanent_index=chosen_source_permanent_index,
                            stack_index=chosen_source_stack_index,
                        ),
                        "sacrificed_for_cost": sacrificed_for_cost,
                        # …the cards a *discard* cost took, on the channel the
                        # activation path records them on and for its reason:
                        # the card is in a graveyard by now (CR 400.7: a
                        # different object), so the announcement is the only
                        # thing that can say which of that pile's cards it was.
                        "discarded_for_cost": cost_spoils["discarded_for_cost"],
                        # …and what an *exile* cost ate, on the channel the
                        # activation path already records it on. Last-known
                        # information for the same reason (CR 608.2h): the
                        # permanent left the battlefield before the spell was
                        # on the stack, so nothing on the board can be asked
                        # what it was.
                        "exiled_for_cost": exiled_for_cost,
                        # CR 601.2h's answer to "the amount of {B} spent on X"
                        # (Soul Burn). Decided as the cost was built rather than
                        # measured as a pool delta afterwards: this card costs
                        # {X}{2}{B}, so a black unit missing from the pool may
                        # have paid the mandatory pip, the generic {2} or X, and
                        # a delta cannot tell those apart. The allocation is the
                        # cost, so the number is exact.
                        "x_mana_spent": x_mana_spent,
                        # The word CR 601.2b made the caster choose. Here
                        # rather than nowhere because the spell has no
                        # permanent yet and the permanent it becomes is a new
                        # object (CR 400.7), so the announcement is the only
                        # place the answer survives the trip to resolution —
                        # the cost spoils above are on this channel for exactly
                        # that reason. `_resolve_card` copies it onto the
                        # permanent as it is built.
                        "chosen_creature_type": chosen_type_word,
                        # Every seat the announcement named, by role, where it
                        # named two or more (`targeting.ROLE_SEATS`) — beside
                        # `target_player_index` above, which then holds the
                        # first. None for every other cast.
                        ROLE_SEATS: role_seats,
                        # "If you cast it any time a sorcery couldn't have been
                        # cast, …" (Mirage's five flash Auras). Answered *here*
                        # because here is the only moment it can be: CR 601.3d's
                        # timing is about the game state as the spell is
                        # announced, and by resolution the stack has emptied
                        # down to this spell and the step may have moved on.
                        # Stamped only for a card whose text asks — see
                        # `cast_permissions`, whose whole rider this feeds.
                        CAST_AT_INSTANT_SPEED: (
                            sacrifices_at_cleanup_if_cast_at_instant_speed(
                                card.oracle_text or ""
                            )
                            and not a_sorcery_could_be_cast(self, caster_index)
                        ),
                    },
            )
            if from_zone == "graveyard":
                self._rebase_graveyard_targets(spell_item, source_seat, hand_index)
            self._stack_push(spell_item)
            self.log.append(f"{card.name} added to stack")
            if any(cost.choose_number is not None for cost in cast_costs):
                # "As an additional cost to cast this spell, choose a number
                # between 0 and 5." (Liquid Fire.) Said in the log for the
                # reason a kick is, one block down: CR 601.2b makes the choice
                # part of the announcement so that an opponent deciding whether
                # to respond knows which spell this is — five damage to the
                # creature or five to its controller's face.
                self.log.append(
                    f"{caster.name} chose {int(resolved_x_value or 0)} "
                    f"for {card.name}"
                )
            if kicked(card, spell_item.choices):
                # CR 702.33d: the spell is kicked from the moment its
                # controller declared the intention to pay, which is now. Said
                # in the log because nothing else on the table shows it -- the
                # mana is spent either way, and an opponent deciding whether to
                # counter Kavu Titan needs to know which Kavu Titan it is.
                self.log.append(
                    f"{caster.name} kicked {card.name}"
                    + (f" (X={resolved_x_value})" if optional_x_offers(
                        card, from_zone=from_zone
                    ) else "")
                )
            # "Whenever a player casts a [color] spell" triggers (Rod/Cup/Sphere)
            # and "whenever you cast an X spell" triggers (Verduran Enchantress)
            # fire now, as the spell is put on the stack, and go on the stack above
            # it (CR 603.3) — so the trigger resolves while the triggering spell is
            # still on the stack, not after it has already resolved.
            # The record every ordinal reads — "you've cast an instant or
            # sorcery spell this turn" (Stormwing Entity), "their second spell
            # each turn" (Mangara), "other than the first instant spell that
            # player casts each turn" (Ichneumon Druid). CR 601.2i finishes the
            # casting before anything can respond, so the spell is on the list
            # before *any* of the announcements below, not just the ones that
            # used to follow it: it was appended inside `_apply_cast_triggers`,
            # which runs second, so an opponent-scoped ordinal counted a list
            # missing the very spell that fired it and every such trigger was
            # one cast late.
            if 0 <= caster_index < len(self.players):
                self.players[caster_index].spells_cast_this_turn.append(card)
            # The same record, by the identity that list cannot carry: a
            # `CardDefinition` is shared by every copy in every deck, so two
            # casts of one sorcery are one entry there and two here. Backdraft's
            # "one of those sorcery spells" is a choice **between** them.
            record_cast(self, spell_item)
            # "The next instant or sorcery spell you cast this turn can't be
            # countered." (Overmaster.) Spent here, where CR 601.2i makes the
            # spell cast — the next matching spell is this one, before any
            # counter can be announced at it.
            spend_next_spell_promises(self, spell_item)
            self._apply_spell_cast_any_triggers(
                caster_index, card, from_zone, item=spell_item
            )
            self._apply_cast_triggers(caster_index, card, item=spell_item)
            # "An opponent chooses one —" (CR 700.2e): the other player chooses
            # "when the spell's controller normally would", which is CR 601.2b.
            # Armed here rather than earlier because CR 601.2i finishes the
            # casting first — the spell is on the stack and the cast triggers
            # are announced, and the prompt holds priority, so nobody acts
            # between the two. A non-interactive chooser takes the default where
            # this stands (`default_at_arm`), which is what keeps AI and
            # headless play from stopping on a decision nobody will make.
            self._arm_opponent_mode_choice(caster_index, card, spell_item)
            return SimulationResult(card.name, True, classification.effect_kind, "queued")

        self._resolve_card(
            caster_index=caster_index,
            card=card,
            classification=classification,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            x_value=resolved_x_value,
            choices=dict(cost_spoils),
            # A land played out of another seat's exile (Grinning Totem) enters
            # under its player's control and stays its owner's card (CR 108.3).
            owner_index=source_seat,
        )
        return SimulationResult(card.name, True, classification.effect_kind, "resolved")
    def _rebase_graveyard_targets(
        self, item: StackItem, pile_seat: int, left_slot: int
    ) -> None:
        """Re-count *item*'s graveyard target slots now that the spell itself
        has left *pile_seat*'s graveyard from *left_slot*.

        A graveyard target is announced as a slot, and the announcement is
        made against the pile **the caster is looking at** — the spell still
        in it, which is the list the picker enumerated and the list the
        announcement gates above just checked the slot against. The card then
        leaves that pile (CR 601.2a), every later slot slides down one, and
        ``_stack_push`` names the target by the slot it is handed. Read
        unshifted, Morgue Theft flashed back from under two creature cards
        returned the *other* one, and a slot past the shortened end named
        nothing and fell back to the first legal card.

        Only where the slot counts into the pile the spell left: the same
        ``graveyard_target_seat`` the stamp is about to ask, so the two cannot
        disagree about whose pile an index is into. The spell's own slot never
        arrives here — the picker does not offer it and
        ``cast_target_refusal`` has refused it (``targeting.CAST_FROM_GRAVEYARD``).
        """
        spec = graveyard_target_spec(
            item.card, compile_card_oracle(item.card),
            mode_index=item.chosen_mode_index,
        )
        if spec is None or self.graveyard_target_seat(item, spec) != pile_seat:
            return

        def rebased(slot):
            return slot - 1 if isinstance(slot, int) and slot > left_slot else slot

        chosen = item.target_permanent_index
        item.target_permanent_index = (
            [rebased(slot) for slot in chosen] if isinstance(chosen, list)
            else rebased(chosen)
        )
