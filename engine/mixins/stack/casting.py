"""Casting a spell (CR 601): put it on the stack, having chosen targets,
modes and X, and paid its cost.

Everything here runs *before* the spell resolves. ``cast_from_hand`` is the
entry point and ``queue_from_hand`` does the work, through
``_cast_onto_stack``: CR 601.2a–i in order, every refusal before the mana
payment that is its hinge, every payment from it on, and the push that
finishes the cast (CR 601.2i).

What the cast asks on the way is a mixin each, composed onto ``Game``
directly after this one, and ``_cast_onto_stack`` calls its steps there in
CR order — each moved out of it whole at the 2,000-line cap, or at the
pre-Fifth-Dawn split:

* ``cast_announcement`` — where the spell is cast from and under what
  permission (CR 601.2a, 601.3), the costs it announces and the choices
  beside them (CR 601.2b), its modes (CR 601.2b, 700.2) and each announced
  mode's target gates (CR 601.2c);
* ``cast_additional_costs`` — the printed additional costs (CR 601.2b,
  601.2f–h), the optional ones a cast announces (kicker, buyback), the
  sacrifices a board tax adds (Drought), and whether every cost of the cast
  can be paid;
* ``cast_alternative_costs`` — the printed alternative cost (CR 118.9);
* ``cast_target_validation`` — the target gate (CR 601.2c), the count and
  the division (CR 601.2d), and the Aura enchant-noun helpers;
* ``pool_payment`` — the X a cast is for (CR 107.3) and the mana payment
  (CR 601.2g–h);
* ``cast_completion`` — below the hinge, where nothing refuses: every other
  cost paid at one moment (CR 601.2h), and the stack object built from the
  announcement, pushed, and cast (CR 601.2i).
"""

from __future__ import annotations

from ...bare_announcements import (announced_fields, announced_seat,
                                   default_cast_target,
                                   names_an_object, seat_of_unseated_slot)
from ...cast_prohibitions import cast_prohibition
from ...cast_restrictions import check_cast_timing
from ...divided_damage import divided_entry, stamped_entry
from ...entwine import entwined_mode_choices
from ...face_down import announced_morph_cost, face_down_card
from ...faces import choose_a_face_refusal, spell_named
from ...mana_combination import split_refusal
from ...classifier import classify_card
from ...cost_modifiers import (cost_reduction_for_cast, spell_cost_tax,
                               spell_life_tax, spell_symbol_tax)
from ...self_cost_modifiers import self_per_target_tax
from ...target_keywords import (ANTE, GRAVEYARD, announced_slot,
                                cast_target_zone)
from ...game_types import as_target_slots, SimulationResult
from ...models import CardDefinition
from ...oracle import compile_card_oracle
from ...targeting import graveyard_target_spec, derive_cast_spec
from .cast_additional_costs import _taken_offers
from .cast_announcement import _mode_announcements
from ...mana_payment import mana_cost_label
from ...refusals import refuse, take_back_refused_attempt


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
        # A card in a graveyard by its place in the pile, a card in the ante by
        # its place there: each zone's own keyword (``engine/target_keywords``).
        target_graveyard_indices: list[int] | None = None,
        target_ante_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        # "Add X mana in any combination of {B} and/or {R}" (Burnt Offering):
        # the producer's split, ``{symbol: count}`` (``engine/mana_combination.py``).
        mana_combination: dict | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts (``index`` plus optional
        # ``target_player_index`` / ``target_permanent_ids`` /
        # ``target_graveyard_indices`` / ``target_stack_index``, each zone its
        # own keyword as the cast's are). None or one entry behaves exactly as
        # ``mode_index`` alone always has.
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
        # CR 118.9a: *which* alternative cost, when more than one applies — a
        # position in ``applicable_alternative_costs`` (a morph card under
        # Dream Halls: face down for {3}, or a discard). None where one is
        # offered; with two and none named the cast is refused, never guessed.
        alternative_cost_index: int | None = None,
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
        # "**You may** have this creature enter as a copy of any creature on
        # the battlefield" (Clone, Sculpting Steel) answered *no*: the
        # permanent enters as itself (the rulings: "You can choose not to
        # copy anything"). The cast is where the copy target is announced
        # (``cast_targets._cast_target_spec``'s optional picker), so the
        # decline is announced beside it; absent, a cast naming no target
        # copies the first permanent of the type, which is what keeps an AI
        # and a headless cast copying. Ignored for a card offering no copy.
        decline_copy: bool | None = None,
    ) -> SimulationResult:
        queued = self.queue_from_hand(
            caster_index,
            card_name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            target_permanent_ids=target_permanent_ids,
            target_role_refs=target_role_refs,
            target_graveyard_indices=target_graveyard_indices,
            target_ante_index=target_ante_index,
            x_value=x_value,
            new_color=new_color,
            mana_combination=mana_combination,
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
            alternative_cost_index=alternative_cost_index,
            optional_cost_payments=optional_cost_payments,
            chosen_creature_type=chosen_creature_type,
            chosen_source_seat=chosen_source_seat,
            chosen_source_permanent_index=chosen_source_permanent_index,
            chosen_source_stack_index=chosen_source_stack_index,
            decline_copy=decline_copy,
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

        A refusal is CR 733.1's reversal, and the announcement goes with it:
        whatever the attempt wrote to the shared log before it was refused
        ("chose Human to cast …", "… costs less to cast") is taken back
        (``engine/refusals.py``), so the other seats learn nothing of a card
        that never left its hidden zone.
        """
        log_mark = len(self.log)
        with self.deferring_triggers():
            result = self._cast_onto_stack(*args, **kwargs)
            # Inside the window: what it flushes on the way out is not the
            # attempt's to take back.
            take_back_refused_attempt(self, log_mark, result)
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
        # A card in a graveyard by its place in the pile, a card in the ante by
        # its place there: each zone's own keyword (``engine/target_keywords``).
        target_graveyard_indices: list[int] | None = None,
        target_ante_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        # "Add X mana in any combination of {B} and/or {R}" (Burnt Offering):
        # the producer's split, ``{symbol: count}`` (``engine/mana_combination.py``).
        mana_combination: dict | None = None,
        target_stack_index: int | None = None,
        mode_index: int | None = None,
        # "Choose one **or more** —" (Sublime Epiphany). Every chosen mode, with
        # each one's own targets: a list of dicts (``index`` plus optional
        # ``target_player_index`` / ``target_permanent_ids`` /
        # ``target_graveyard_indices`` / ``target_stack_index``, each zone its
        # own keyword as the cast's are). None or one entry behaves exactly as
        # ``mode_index`` alone always has.
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
        # CR 118.9a: *which* alternative cost, when more than one applies — a
        # position in ``applicable_alternative_costs`` (a morph card under
        # Dream Halls: face down for {3}, or a discard). None where one is
        # offered; with two and none named the cast is refused, never guessed.
        alternative_cost_index: int | None = None,
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
        # "**You may** have this creature enter as a copy of any creature on
        # the battlefield" (Clone, Sculpting Steel) answered *no*: the
        # permanent enters as itself (the rulings: "You can choose not to
        # copy anything"). The cast is where the copy target is announced
        # (``cast_targets._cast_target_spec``'s optional picker), so the
        # decline is announced beside it; absent, a cast naming no target
        # copies the first permanent of the type, which is what keeps an AI
        # and a headless cast copying. Ignored for a card offering no copy.
        decline_copy: bool | None = None,
    ) -> SimulationResult:
        caster = self.players[caster_index]
        # CR 601.2c, said one role at a time. Turned **here**, before anything
        # below reads a target field, into the channels a cast has always had:
        # the id list positional in role order (``None`` where the slot is not
        # a permanent), the scalar seat (the first player named) and — only
        # where two or more players were named — every seat by slot
        # (``target_roles.ROLE_SEATS``), which is what the gate, the stack item
        # and the resolution read slot 1's player from. One translation, the
        # activation path's own, where each caller used to make it for itself
        # (the wire did, onto one seat).
        role_seats: "list | None" = None
        # …and a role answered by a **card in a graveyard** ("Destroy target
        # non-Zombie creature. … Return up to one target Zombie card from your
        # graveyard to your hand.", Cruel Revival): the stamp the translation
        # takes for that slot, positional in role order with ``None`` in every
        # other slot, as an activation's has always been
        # (``target_graveyard_card``). Taken here, at CR 601.2c and before any
        # cost moves a card, so the slot still means what the caster chose.
        # None for every cast that names no graveyard role.
        role_graveyard_stamps: "list | None" = None
        if target_role_refs:
            (
                target_permanent_ids, _role_indices, role_graveyard_stamps,
                role_seat, role_seats,
            ) = self._role_announcement_stamps(target_role_refs)
            if role_seat is not None:
                target_player_index = role_seat
            if not any(stamp is not None for stamp in role_graveyard_stamps):
                role_graveyard_stamps = None

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
            return refuse(card_name, None, details)
        # **A morph cast turns the card face down before anything reads it**
        # (CR 702.37c: "turn it face down and announce that you're using a
        # morph ability … Any effects or prohibitions that would apply to
        # casting a card with these characteristics (and not the face-up
        # card's characteristics) are applied"; CR 708.4, CR 601.3e). So the
        # spell *is* the face-down 2/2 from here on, the way a split card's
        # spell is its half one step up: every prohibition, tax, reduction,
        # timing gate and target gate below reads `card` and sees a colourless
        # nameless creature with mana value 0, and the stack object the push
        # makes is that card. `held` stays the card the zone holds, which is
        # what leaves it. The cost is the morph's own {3}, announced as the
        # cast's alternative cost (CR 118.9a) below.
        morph_cost = announced_morph_cost(
            self, caster_index, held,
            alternative_cost=alternative_cost, permission=permission,
            chosen_index=alternative_cost_index,
        )
        if morph_cost is not None:
            card = face_down_card(held)
        # CR 601.2c, said in each zone's own keyword (``engine/target_keywords``):
        # a graveyard card by its place in the pile, an ante card by its place
        # there, a permanent by id — turned **here**, before any gate reads a
        # target field, into the slot those gates read beside the ids.
        target_zone = cast_target_zone(card, mode_index=mode_index)
        if target_role_refs and role_graveyard_stamps and target_zone == GRAVEYARD:
            # …and a **lone graveyard role** ("Return target creature card from
            # your graveyard", announced one role at a time) is that keyword:
            # its stamp's place in its pile, judged by the gates like any
            # other slot and stamped at the push from it, never left beside a
            # default the bare-cast answer below would have written over it.
            stamps = [stamp for stamp in role_graveyard_stamps if stamp is not None]
            target_graveyard_indices = [
                self.graveyard_index_of(stamp) for stamp in stamps
            ]
            if target_player_index is None:
                target_player_index = stamps[0].seat
            role_graveyard_stamps = None
        target_player_index, target_permanent_index, keyword_refusal = announced_slot(
            self, target_zone, name=card.name,
            target_player_index=target_player_index,
            target_permanent_index=target_permanent_index,
            # A roles announcement's ids are positional and read as ids by the
            # roles walk; no slot is derived from them.
            target_permanent_ids=None if target_role_refs else target_permanent_ids,
            target_graveyard_indices=target_graveyard_indices,
            target_ante_index=target_ante_index,
        )
        if keyword_refusal is not None:
            return refuse(card.name, None, keyword_refusal)
        # A card in the ante rides the announcement's choices, never the slot
        # channel the push consumes into ids (``target_keywords.ANTE_INDEX``).
        ante_index = None
        if target_zone == ANTE:
            ante_index, target_permanent_index = target_permanent_index, None
        # The split of an "any combination" spell, checked whole before
        # anything is paid (``engine/mana_combination.py``).
        combination_refusal = split_refusal(
            compile_card_oracle(card).instructions, mana_combination,
        ) if mana_combination is not None else None
        if combination_refusal is not None:
            return refuse(card_name, None, combination_refusal)
        classification = classify_card(card)
        # CR 702.42a: a paid entwine **is** the choice of every mode, so a cast
        # that paid it and named none is given every mode here — before the
        # bare-cast default below, which defaults a *cast-level* target only
        # where no mode was listed (``entwine.entwined_mode_choices``).
        mode_choices, entwine_denial = entwined_mode_choices(
            card, mode_choices, _taken_offers(optional_cost_payments),
            names_cast_targets=target_player_index is not None or names_an_object(
                target_permanent_index, target_permanent_ids,
                target_stack_index, target_role_refs, divided_targets,
            ),
            mode_index=mode_index,
        )
        if entwine_denial is not None:
            return refuse(card.name, classification.effect_kind, entwine_denial)
        # The roles announcement's seats **by slot** where several roles may
        # each be answered by a player ("Choose any number of target players
        # or planeswalkers", Kaboom!), even when one was named: the scalar
        # cannot say which slot its seat answers
        # (``target_roles.several_seat_roles``).
        if role_seats is None:
            role_seats = self.several_seat_role_seats(
                card, mode_index=mode_index, target_role_refs=target_role_refs,
                target_permanent_ids=target_permanent_ids,
                target_player_index=target_player_index,
            )
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
        # What moved this cast's price, for the payment's refusal to say: the
        # log lines below announce each change as the cast is priced (CR
        # 601.2f), and a refused cast takes them back with the rest of the
        # attempt (CR 733.1, ``refusals.take_back_refused_attempt``), so the
        # actor's "insufficient mana" carries them instead (``refusals.noting``).
        price_notes: list[str] = []

        if self.enforce_mana_costs and card.primary_type == "land":
            refusal = self._land_play_refusal(caster_index)
            if refusal is not None:
                details = refusal
                return refuse(card.name, classification.effect_kind, details)
        if card.primary_type == "land":
            # A land a "can't" stops (Worms of the Earth's "Lands can't enter
            # the battlefield", CR 614.17) is not played and stays in the hand
            # — the question every road asks before it takes the card
            # (``permanent_cards``). Worms' other line refuses the play above
            # wherever costs are enforced; this is the answer where they are
            # not, which took the land out of the hand into no zone.
            from ...permanent_cards import cant_enter_sources

            stopping = cant_enter_sources(self, card, caster_index)
            if stopping:
                return refuse(
                    card.name, classification.effect_kind,
                    f"{card.name} can't enter the battlefield ({', '.join(stopping)})",
                )

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
            return refuse(
                card.name, classification.effect_kind, prohibition.details,
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
            # A roles announcement names what it names, a card in a graveyard
            # included — the activation path has always asked it so.
            target_role_refs, divided_targets,
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
        # …and a seat the spell announces beside its own slots (the owner of
        # the pile, the opponent a count is taken on, the opponent beside a
        # division — ``target_descriptions.ANNOUNCED_SEAT``): named, or — for
        # a cast naming nobody, or its caster where the description cannot
        # admit them — the first one the description admits, written onto the
        # announcement so the gates, the X counted and the stack object all
        # read one seat (``bare_announcements.announced_seat``).
        seat_beside = announced_seat(
            self, caster_index, card, target_player_index, mode_index=mode_index,
        )
        if seat_beside is not None:
            target_player_index = seat_beside

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
            price_notes.append(f"costs {{{spell_tax}}} more: {', '.join(taxing_names)}")

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
            price_notes.append(
                f"costs {mana_cost_label(pip_tax)} more: "
                f"{', '.join(pip_taxing_names)}"
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
                price_notes.append(f"costs {{{commander_tax}}} more: commander tax")

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
            return refuse(
                card.name, classification.effect_kind, details,
            )

        # CR 601.2f: increases first, then reductions.
        cost_reduction, reducing_names = cost_reduction_for_cast(self, caster_index, card)
        if cost_reduction:
            self.log.append(f"{card.name} costs less to cast ({', '.join(reducing_names)})")
            price_notes.append(
                f"costs {mana_cost_label(cost_reduction.symbols())}"
                f" less: {', '.join(reducing_names)}"
            )

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
            return refuse(card.name, classification.effect_kind, classification.reason)

        timing_denial = check_cast_timing(self, caster_index, card.oracle_text.lower())
        if timing_denial is not None:
            return refuse(card.name, classification.effect_kind, timing_denial)

        # CR 601.2b: the costs this cast announces, and the choices beside them.
        announced = self._announced_cast_costs(
            card=card, caster=caster, caster_index=caster_index,
            chosen_creature_type=chosen_creature_type,
            classification=classification, cost_hand_index=cost_hand_index,
            cost_other_hand_indices=cost_other_hand_indices,
            decline_copy=decline_copy, extra_generic_tax=extra_generic_tax,
            extra_pip_tax=extra_pip_tax, from_zone=from_zone,
            hand_index=hand_index,
            optional_cost_payments=optional_cost_payments,
            target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index, x_value=x_value,
        )
        if isinstance(announced, SimulationResult):
            return announced
        (
            cast_costs, chosen_type_word, copy_declined, cost_hand_cards,
            extra_generic_tax, offer_x_colorings, optional_paid, x_value,
        ) = announced

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
                chosen_index=alternative_cost_index,
                named_hand_index=alternative_cost_hand_index,
                spell_hand_index=hand_index if from_zone == "hand" else None,
                # CR 118.9b: the permission this cast is made under may
                # *require* an alternative cost — flashback's (CR 702.34a).
                # Then that cost is the announcement, whatever the caller
                # said, and CR 118.9a leaves no room for a second.
                #
                # …and a morph cast's {3} (CR 702.37c) is the cost already
                # announced above: the card is face down now and prints no
                # cost for the lookup to find.
                required=(
                    morph_cost if morph_cost is not None
                    else permission.cost if permission is not None else None
                ),
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
                    # "Sacrifice X Mountains" (Firecat Blitz): how many to
                    # name is the X announced with the cast (CR 601.2b).
                    x_value=x_value,
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
            return refuse(
                card.name, classification.effect_kind, alternative_denial,
            )

        # "Choose one or more —": the modes are chosen as the spell is cast
        # (CR 601.2b) and are checked here, before any mana leaves the pool, so
        # a card that does not print the head cannot be handed two modes.
        chosen_modes, mode_denial = self._resolve_chosen_modes(
            card, mode_choices, optional_paid=optional_paid,
        )
        if mode_denial is not None:
            return refuse(card.name, classification.effect_kind, mode_denial)
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
                mode.target_permanent_index = as_target_slots(
                    named["target_permanent_index"]
                )
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
            role_graveyard_stamps=role_graveyard_stamps,
            target_permanent_ids=target_permanent_ids,
            target_permanent_index=target_permanent_index,
            target_player_index=target_player_index,
            target_stack_item=target_stack_item, x_value=x_value,
            # CR 601.2b's type, under which CR 601.2c's targets were chosen
            # (Aphetto Dredging); None for every cast that announces none.
            chosen_creature_type=chosen_type_word,
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
                    return refuse(card.name, classification.effect_kind, "invalid divided target seat")
                if index is not None and not (
                    isinstance(index, int) and 0 <= index < len(self.players[seat].battlefield)
                ):
                    return refuse(card.name, classification.effect_kind, "invalid divided target")
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
            return refuse(
                card.name, classification.effect_kind, required_refusal,
            )

        # "This spell costs {1} more to cast for each target beyond the first."
        # (Fireball) / "This spell costs 3 life more to cast for each target."
        # (Phyrexian Purge.) A spell's own increase, sized by how many targets it
        # chose — CR 601.2c settles the targets before CR 601.2f calculates the
        # cost, which is what makes the sentence answerable at all.
        #
        # Read off `self_cost_modifiers.self_per_target_tax`, the table the support
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
                    return refuse(
                        card.name, classification.effect_kind, details,
                    )
            else:
                extra_generic_tax += owed
                if owed:
                    price_notes.append(
                        f"costs {{{owed}}} more: {card.name} for "
                        f"{num_targets} target(s)"
                    )

        # CR 107.3, 601.2b: the X this cast is for.
        x_settled = self._resolved_cast_x(
            card=card, caster=caster, caster_index=caster_index,
            chosen_alternative=chosen_alternative,
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
        # CR 202.3e: on the stack X is the number announced for it, so a
        # reduction narrowed by the spell's mana value ("with mana value 6 or
        # greater", Krosan Drover) is asked again now that X is one. An X the
        # caster left to the pool is inferred again under the larger
        # reduction — the bound is "or greater" only, so the reduction can
        # only grow with X and the second answer is final.
        if "{X}" in (card.mana_cost or "").upper():
            for _ in range(2):
                restated, restated_names = cost_reduction_for_cast(
                    self, caster_index, card, x_value=resolved_x_value,
                )
                if restated == cost_reduction:
                    break
                cost_reduction, reducing_names = restated, restated_names
                if x_value is None:
                    # Inferred again under the larger reduction — which also
                    # comes off X itself where the rest of the cost is too
                    # small to take it (``_x_reduction_credit``) — before the
                    # price is said, so the line names the X that is cast.
                    x_settled = self._resolved_cast_x(
                        card=card, caster=caster, caster_index=caster_index,
                        chosen_alternative=chosen_alternative,
                        classification=classification,
                        cost_reduction=cost_reduction,
                        extra_generic_tax=extra_generic_tax,
                        extra_pip_tax=extra_pip_tax, mode_index=mode_index,
                        target_permanent_ids=target_permanent_ids,
                        target_permanent_index=target_permanent_index,
                        target_player_index=target_player_index,
                        target_stack_item=target_stack_item, x_value=x_value,
                    )
                    if isinstance(x_settled, SimulationResult):
                        return x_settled
                    announced_x, resolved_x_value, x_colors, x_mana_spent = x_settled
                self.log.append(
                    f"{card.name} costs less to cast at X={resolved_x_value} "
                    f"({', '.join(reducing_names)})"
                )
                price_notes.append(
                    f"costs {mana_cost_label(cost_reduction.symbols())} less at "
                    f"X={resolved_x_value}: {', '.join(reducing_names)}"
                )
                if x_value is not None:
                    break

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
            x_mana_spent=x_mana_spent, price_notes=price_notes,
        )
        if isinstance(mana_paid, SimulationResult):
            return mana_paid
        permission, resolved_x_value, x_mana_spent, mana_spent_to_cast = mana_paid

        # CR 601.2h: every other cost, paid at one moment.
        (
            cost_spoils, exiled_for_cost, sacrificed_for_cost,
        ) = self._pay_cast_costs(
            alternative_card=alternative_card,
            alternative_others=alternative_others,
            alternative_permanents=alternative_permanents, card=card,
            cast_costs=cast_costs, caster=caster, caster_index=caster_index,
            chosen_alternative=chosen_alternative,
            cost_graveyard_indices=cost_graveyard_indices,
            cost_hand_cards=cost_hand_cards,
            cost_permanent_ids=cost_permanent_ids,
            cost_permanent_index=cost_permanent_index, from_zone=from_zone,
            hand_index=hand_index, held=held, life_owed=life_owed,
            life_taxing_names=life_taxing_names, optional_paid=optional_paid,
            owed=owed, permission=permission,
            resolved_x_value=resolved_x_value, source_seat=source_seat,
            source_zone=source_zone, spell_graveyard_slot=spell_graveyard_slot,
        )

        # CR 601.2i: the spell is put on the stack, and is cast.
        if card.primary_type != "land":
            return self._put_cast_spell_on_stack(
                ante_index=ante_index, card=card, cast_costs=cast_costs,
                caster=caster, caster_index=caster_index,
                chosen_alternative=chosen_alternative,
                chosen_modes=chosen_modes,
                chosen_source_permanent_index=chosen_source_permanent_index,
                chosen_source_seat=chosen_source_seat,
                chosen_source_stack_index=chosen_source_stack_index,
                chosen_type_word=chosen_type_word,
                classification=classification, copy_declined=copy_declined,
                cost_spoils=cost_spoils, divided_targets=divided_targets,
                exiled_for_cost=exiled_for_cost, from_zone=from_zone,
                hand_index=hand_index, mana_combination=mana_combination,
                mode_index=mode_index, new_color=new_color,
                old_color=old_color, optional_paid=optional_paid,
                permission=permission, resolved_x_value=resolved_x_value,
                role_graveyard_stamps=role_graveyard_stamps,
                role_seats=role_seats, sacrificed_for_cost=sacrificed_for_cost,
                source_seat=source_seat,
                target_permanent_ids=target_permanent_ids,
                target_permanent_index=target_permanent_index,
                target_player_index=target_player_index,
                target_stack_item=target_stack_item, x_mana_spent=x_mana_spent,
                mana_spent_to_cast=mana_spent_to_cast,
            )

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
