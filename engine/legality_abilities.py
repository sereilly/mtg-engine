"""What an ability may name as it is announced (CR 602.2b, CR 601.2c, CR 603.3c).

The ability twin of ``engine/legality_cast_spec.py`` and
``engine/legality_cast_gates.py`` together, for the reason CR 602.2b gives:
an activation goes through the cast process, so the offer and the gate are one
subject, and an ability's are asked of one *ability* rather than one card — a
permanent may carry several that target differently
(``targeting.derive_activation_spec``).

* :meth:`AbilityTargetsMixin.activation_target_spec` /
  :meth:`AbilityTargetsMixin.activation_offer` — the picker an ability is
  activated through, every legal target enumerated, and the abilities a
  permanent has to activate at all (:meth:`AbilityTargetsMixin.usable_abilities_of`,
  :meth:`AbilityTargetsMixin.lost_abilities_refusal`);
* :meth:`AbilityTargetsMixin.activation_target_refusal` — **the** gate, read
  once in ``mixins/stack/activation.py`` before any cost is paid, over the
  same list the picker was handed, so what is offered and what is enforced
  cannot disagree;
* :meth:`AbilityTargetsMixin.trigger_mode_options` — a modal *triggered*
  ability's modes, each with what it could target, asked as the trigger is put
  on the stack.
"""

from __future__ import annotations

from .handlers._common import evaluate_count
from .models import CardDefinition
from .divided_damage import divided_entry
from .oracle import compile_card_oracle
from .modal_triggers import modal_trigger_mode_spec, modal_trigger_modes
from .target_requirements import (
    announcement_refusal,
    narrow_offer,
    requirements_binding,
)
from .targeting import (
    GRAVEYARD_TARGET_KIND,
    ROLES_TARGET_KIND,
    activation_target_slot,
    role_is_stack,
    spec_is_a_cost,
    spec_roles,
    usable_activated_abilities,
)
from .legality import (
    _unnamed_single_pile_refusal,
    _iter_instruction_tree,
    _ability_picker_is_a_target,
    targeting_instruction,
    _activation_spec,
    _SEAT_TARGET_SPEC_KINDS,
    exact_target_count,
    _UNOBLIGED_ACTIVATION_KINDS,
    spec_chooses_a_source,
    activation_target_obligation,
)


class AbilityTargetsMixin:
    """What an ability may name, and whether it may be activated with
    that announcement. Composed onto ``Game`` beside ``LegalityMixin``."""

    def _size_activation_x_targets(
        self, controller_index: int, spec: dict, ability, source_permanent
    ) -> None:
        """Fill in what an ability's **defined** X makes knowable: CR 601.2c's
        number of targets, and CR 601.2d's quantity to divide.

        "Destroy up to **X** target nonblack creatures, where X is the number of
        verse counters on this enchantment." (Vile Requiem, Recantation, and the
        rest of Urza's Saga's verse cycle.) ``x_targets`` means "however many the
        X pays for" — a question with no answer on the cast side until the
        caster announces X, which is why that side leaves the flag alone until
        ``announced_cast_x`` resolves it.

        An ability's X comes from one of **two** places, and only one of them is
        answerable here. Candelabra of Tawnos ("{X}, {T}: Untap X target lands")
        prints the X in its *cost*: the player announces it at CR 601.2b and
        nothing but the client can say what it will be, which is exactly what
        the flag is for — it survives untouched, and the browser asks for X
        before it offers a picker.

        The verse cycle prints it in the *text* instead ("…where X is the number
        of verse counters on this enchantment"). Nobody announces that one: the
        where-clause defines it off a board the game can already read, and
        CR 602.2b routes an activation through CR 601.2b–i so the number is
        settled at 601.2c — with the source still on the battlefield, because a
        sacrifice cost is not paid until 601.2h.

        So the presence of an ``x_from_count`` spec is the whole test, and its
        absence leaves the flag exactly as it was rather than guessing a
        ceiling. Left unresolved for the *defined* kind, ``x_targets`` is an
        unbounded picker in front of a handler that destroys everything it is
        handed: Vile Requiem with one verse counter destroyed three creatures,
        which is the wrong-in-the-player's-favour, silent failure a printed
        restriction has to be *enforced* to avoid.

        Writes ``max_targets`` and drops the flag, exactly as the cast side does
        one question over, so everything downstream reads one key.

        **And the same number sizes a division.** "Prevent the next X damage …
        to any number of targets, divided as you choose, where X is the number
        of verse counters on this enchantment." (Serra's Hymn.) CR 601.2d's
        announcement needs the total *before* the shares are named, and the
        client's own reader (``dividedDivisionTotal``) asks the spec for it —
        so an ability whose X is defined has to say it here or the browser falls
        back to the X box it was never shown and divides nothing. One method for
        both, because it is one question: what is this ability's X, now, off the
        board the where-clause names.
        """
        instruction = targeting_instruction(getattr(ability, "instruction", None))
        counted = (getattr(instruction, "payload", None) or {}).get("x_from_count")
        if not isinstance(counted, dict):
            return
        defined = max(0, evaluate_count(
            self, self.players[controller_index], counted,
            source=source_permanent,
        ))
        if spec.get("x_targets"):
            spec.pop("x_targets", None)
            spec["max_targets"] = defined
        # ``division_total`` and not ``defined_x``: the client reads the total
        # first and the announced X only as a fallback, and this X is not
        # announced at all — an ``defined_x`` here would also make the picker
        # stop asking for an X on abilities that legitimately want one.
        if (
            spec.get("kind") == "divided"
            and "division_total" not in spec
            and (getattr(instruction, "payload", None) or {}).get("amount") == "x"
        ):
            spec["division_total"] = defined

    def lost_abilities_refusal(
        self, permanent, ability_index: int | None = None
    ) -> str | None:
        """Why *permanent* has no activated ability to activate at all, or
        None: an effect took them away.

        *ability_index* is the ability a door was asked for, when it was asked
        for one by number. A land whose type was set and which another effect
        granted an ability has a list again — a shorter one — and an index
        past its end is one of the land's **own** abilities, named by a caller
        still counting the printed card: refused for the same reason, rather
        than answered as "no ability named" (which on the wire is a plain tap
        for mana — the request asked for the Factory's animation and got {R}).

        Two rules, one answer, because every reader needs both or neither:

        * "**loses all abilities**" (Titania's Song on a noncreature artifact).
          Layer 6 removes the keywords; an activated ability is read off the
          compiled program rather than the ability channel, so the removal has
          to be asked for;
        * CR 305.7 — a land whose subtype an effect **set** to a basic land
          type "loses all abilities generated from its rules text". A Mishra's
          Factory under Blood Moon is a Mountain: it taps for {R} (the tap
          seam gives it its new type's mana ability, the rule's other half)
          and does not animate.

        This was two inline checks at the top of ``_activate_onto_stack`` and
        a different subset of them at each place that *lists* abilities — the
        foreign chooser asked the first, the land tap seam the second, the
        picker and the wire neither. So both doors refused what the lists
        still offered: a dead button in the ability menu and a proposal the AI
        made every turn. One predicate, and :meth:`usable_abilities_of` is the
        list that asks it.

        **CR 305.7 keeps what another effect granted**, and the second arm
        answers only for a land that has nothing left: "this doesn't remove
        any abilities that were granted to the land by other effects". The
        land's *own* text is struck where it is read
        (``Permanent.effective_card``), so the program the door and every list
        compile holds exactly what the land was granted — an Aura's quoted
        ability, a board-wide static's, an until-end-of-turn grant — and a
        land with one is not refused here; an ability of its own is simply
        not in the list to be named. This arm used to refuse the land whole,
        granted abilities and all, at the door and in every list.

        **And so does the first arm, for the abilities granted afterwards.**
        "Loses all abilities" is a layer-6 effect with a timestamp (CR 613.7):
        it takes what the permanent has when it applies, and
        ``effective_card`` strikes exactly that — the printed text and every
        line an *older* effect granted — and keeps a newer grant
        (``keywords.abilities_lost_at``). So this arm too answers only for a
        permanent with nothing left, or for an index past what is. It refused
        the permanent whole: a Grizzly Bears under Humility given Hermetic
        Study had the Study's ability on every list's source and a door that
        would not open for it.

        Both of the layer-6 channels now, where it asked only the board-wide
        one: a creature a Humble or a Soul Sculptor named was refused by the
        empty list further in, in other words.
        """
        from .keywords import abilities_lost_at
        from .land_types import lost_abilities_to_type_change

        by_effect = abilities_lost_at(permanent) is not None
        by_type = lost_abilities_to_type_change(permanent)
        if not (by_effect or by_type):
            return None
        left = usable_activated_abilities(
            compile_card_oracle(self.playable_card_of(permanent))
        )
        if left and (ability_index is None or 0 <= ability_index < len(left)):
            return None
        if by_effect:
            return f"{permanent.card.name} has lost all abilities"
        return (
            f"{permanent.card.name} lost its abilities when its land "
            "type was set (CR 305.7)"
        )

    def usable_abilities_of(self, permanent, *, card=None) -> list:
        """The activated abilities *permanent* has to activate from the
        battlefield **now** — ``targeting.usable_activated_abilities`` over its
        program, or none where an effect took them (:meth:`lost_abilities_
        refusal`).

        The permanent's answer rather than the program's. A compiled program
        is the card as it reads; whether that text is still the permanent's is
        a question about the board, and a reader that listed the program's
        abilities listed some the activation path refuses on sight. This list
        *is* the index — the web layer, the AI and
        ``queue_permanent_ability`` address an ability by its position in it —
        so it is empty or whole, never renumbered.

        *card* is the caller's reading of the permanent where it has one in
        hand (the picker reads ``effective_card``); otherwise the playable
        card, which is what the activation path compiles.
        """
        if self.lost_abilities_refusal(permanent) is not None:
            return []
        return usable_activated_abilities(
            compile_card_oracle(
                card if card is not None else self.playable_card_of(permanent)
            )
        )

    def activation_target_spec(
        self, controller_index: int, permanent_index: int, ability_index: int | None = None
    ) -> dict:
        """Target spec for activating the ability of the permanent at
        ``permanent_index`` on ``controller_index``'s battlefield: the target
        kind plus every legal target. With ``ability_index`` (multi-ability
        cards whose abilities target differently — Pyramids), the spec is that
        one ability's; without it, the first ability that chooses anything.

        Derived from the compiled program (engine/targeting.py), per ability
        rather than per card — the question "what does this ability target?" has
        one answer per ability and a card-level classifier could only give one
        answer for all of them."""
        player = self.players[controller_index]
        if not (0 <= permanent_index < len(player.battlefield)):
            return {"kind": "none", "requires_target": False, "valid_targets": []}
        source_permanent = player.battlefield[permanent_index]
        # effective_card so a copy (Clone / Vesuvan Doppelganger) offers the
        # copied creature's activated abilities (CR 707.2).
        card = source_permanent.effective_card
        # Through the permanent's own list: a land whose type was set (CR
        # 305.7) and a permanent that lost all abilities have none to describe,
        # and a spec derived for one was a picker in front of a refusal.
        usable = self.usable_abilities_of(source_permanent, card=card)
        if ability_index is not None:
            usable = usable[ability_index:ability_index + 1] if 0 <= ability_index < len(usable) else []
        spec, spec_ability = _activation_spec(usable)
        # A Sleight of Mind text change retargets a color-word counter
        # (Lifeforce black -> red) with no step here: the spec was derived from
        # the effective card, whose text layer 3 already rewrote, so the UI is
        # offered the new colour's spells by construction.
        # The narrowing the *spec* does not carry, taken from the same ability's
        # instruction: Royal Assassin's tapped-only, King Suleiman's subtype,
        # Pyramids' "attached to a land". Reading it off the ability that
        # supplied the spec is what keeps a two-ability permanent from narrowing
        # one ability's prompt with the other ability's filter.
        ability_instruction = targeting_instruction(
            getattr(spec_ability, "instruction", None)
        )
        self._size_activation_x_targets(
            controller_index, spec, spec_ability, source_permanent
        )
        spec["requires_target"] = spec["kind"] != "none"
        # "**Choose flying, first strike, trample, or shadow**:" (Phyrexian
        # Splicer). A choice announced with the activation (CR 601.2b through
        # CR 602.2b) and *before* the targets — so it rides the same spec the
        # picker is built from, and the client asks for it before it asks for a
        # target. Emitted only when there is a list, so every other ability's
        # payload is unchanged.
        #
        # The list is the printed one, which is the same list
        # ``_announce_chosen_ability`` refuses to go outside: the picker cannot
        # offer a word the announcement would decline.
        offered = tuple(
            getattr(getattr(spec_ability, "cost", None), "chosen_keyword_options", ())
            or ()
        )
        if offered:
            spec["keyword_options"] = list(offered)
        if spec["kind"] == ROLES_TARGET_KIND:
            # An **ability** whose targets are of different kinds, chosen in
            # dependency order (CR 602.2b reaches CR 601.2c). The same walk the
            # cast side runs, and it has to be the same one: `_enumerate_targets`
            # has no arm for a roles spec, so an ability described this way was
            # handed an empty list and refused for want of a target it could
            # not enumerate.
            spec["valid_targets"] = self._role_target_walk(
                controller_index, card, spec, (), for_cast=False,
                source_permanent=source_permanent,
                ability_instruction=ability_instruction,
                ability_source=source_permanent,
            )
            if _ability_picker_is_a_target(spec_ability):
                narrow_offer(self, controller_index, spec)
            return spec
        spec["valid_targets"] = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source_permanent,
            # The *ability's* targets, which is a narrower claim than
            # "source_permanent is set": the cost picker below is handed the
            # same permanent and chooses no target at all (CR 601.2b), and Jade
            # Monolith's source picker chooses a source rather than a target.
            ability_source=source_permanent,
        )
        # Dwarven Weaponsmith: an ability with a target *and* a choosable cost
        # carries two pickers, and each enumerates its own candidates — the cost
        # over the payer's own permanents with no targeting legality, the target
        # through everything above.
        if spec.get("cost_spec"):
            cost_spec = dict(spec["cost_spec"])
            cost_spec["valid_targets"] = self._enumerate_targets(
                controller_index, card, cost_spec, for_cast=False,
                source_permanent=source_permanent,
            )
            self._attach_more_cost_targets(
                controller_index, card, cost_spec, source_permanent
            )
            spec["cost_spec"] = cost_spec
        else:
            self._attach_more_cost_targets(
                controller_index, card, spec, source_permanent
            )
        self._attach_chosen_source_targets(controller_index, card, spec)
        # What this activator may announce *now* (CR 602.2b through
        # CR 601.2c): a requirement an opponent's permanent prints about the
        # announcement — "…must choose at least one Flagbearer … if able" —
        # is in the list, exactly as on the cast picker.
        if _ability_picker_is_a_target(spec_ability):
            narrow_offer(self, controller_index, spec)
        return spec

    def activation_offer(
        self, controller_index: int, source_permanent, ability, *, x_value=None,
    ) -> dict:
        """*ability*'s target spec with **every legal target** enumerated —
        the list :meth:`activation_target_refusal` checks a named target
        against, as one value.

        :meth:`activation_target_spec` without the board address (a permanent
        slot and an ability index, which an ability activated from another
        seat's permanent or out of a graveyard does not have) and without the
        announcement requirements, which is what the requirement gate has to
        measure "if able" against.
        """
        card = getattr(source_permanent, "effective_card", source_permanent)
        source = source_permanent if hasattr(
            source_permanent, "permanent_id"
        ) else None
        spec, _ = _activation_spec([ability])
        spec = dict(spec)
        self._size_activation_x_targets(controller_index, spec, ability, source)
        if spec.get("x_targets") and x_value is not None:
            spec.pop("x_targets", None)
            spec["max_targets"] = max(0, int(x_value))
        instruction = targeting_instruction(getattr(ability, "instruction", None))
        if spec.get("kind") == ROLES_TARGET_KIND:
            spec["valid_targets"] = self._role_target_walk(
                controller_index, card, spec, (), for_cast=False,
                source_permanent=source,
                ability_instruction=instruction,
                ability_source=source,
            )
            return spec
        spec["valid_targets"] = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=instruction,
            source_permanent=source,
            ability_source=source,
        )
        return spec

    def activation_target_requirement_refusal(
        self, controller_index: int, source_permanent, ability, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, target_role_refs=None, divided_targets=None,
        x_value=None,
    ) -> str | None:
        """CR 602.2b under a requirement an opponent's permanent prints: why
        this activation's whole announcement is not one the activator may
        make, or None. The activation twin of
        :meth:`cast_target_requirement_refusal`, over
        :meth:`activation_offer`.
        """
        if not requirements_binding(self, controller_index):
            return None
        if not _ability_picker_is_a_target(ability):
            return None
        spec = self.activation_offer(
            controller_index, source_permanent, ability, x_value=x_value
        )
        if spec.get("kind") in _UNOBLIGED_ACTIVATION_KINDS or spec.get("also_stack"):
            return None
        named: set = set()
        for ref in target_role_refs or ():
            if isinstance(ref, dict) and isinstance(ref.get("permanent_id"), int):
                named.add(ref["permanent_id"])
        listed = [
            pid for pid in (
                target_permanent_ids
                if isinstance(target_permanent_ids, (list, tuple))
                else [target_permanent_ids]
            )
            if isinstance(pid, int) and not isinstance(pid, bool)
        ]
        named.update(listed)
        if not listed and spec.get("kind") != GRAVEYARD_TARGET_KIND:
            seats = (
                [target_player_index] if isinstance(target_player_index, int)
                else list(range(len(self.players)))
            )
            for index in (
                target_permanent_index
                if isinstance(target_permanent_index, list)
                else [target_permanent_index]
            ):
                if not isinstance(index, int) or isinstance(index, bool):
                    continue
                for seat in seats:
                    permanent = self.permanent_at(seat, index)
                    if permanent is not None:
                        named.add(permanent.permanent_id)
        for entry in divided_targets or ():
            seat, index, _share = divided_entry(entry)
            if index is None:
                continue
            permanent = self.permanent_at(seat, index)
            if permanent is not None:
                named.add(permanent.permanent_id)
        card = getattr(source_permanent, "effective_card", source_permanent)
        return announcement_refusal(
            self, controller_index, card.name, [spec], named
        )

    def _attach_more_cost_targets(
        self, controller_index: int, card: CardDefinition, cost_spec: dict,
        source_permanent,
    ) -> None:
        """Enumerate the pickers a cost asks *after* its first (``more_costs``:
        Viscerid Drone's Swamp after its creature), each over its own candidates
        and with no targeting legality, exactly as the first is. A no-op for
        every cost that hands its payer one choice.

        Copied rather than written into, because the entries are the derived
        spec's own dicts and a list of candidates is a fact about this board.
        """
        chained = cost_spec.get("more_costs")
        if not chained:
            return
        enumerated = []
        for entry in chained:
            entry = dict(entry)
            entry["valid_targets"] = self._enumerate_targets(
                controller_index, card, entry, for_cast=False,
                source_permanent=source_permanent,
            )
            enumerated.append(entry)
        cost_spec["more_costs"] = enumerated

    def _attach_chosen_source_targets(
        self, controller_index: int, card: CardDefinition, spec: dict
    ) -> None:
        """Fill in ``source_targets`` for a spec that asks for CR 609.7a's
        "a source of your choice" — any permanent on either battlefield, or any
        spell on the stack. A no-op for every spec that does not.

        Called from **three** places and written once, which is the whole point
        of it: Jade Monolith announces its source with an activation, and Kor
        Chant and Honorable Passage announce theirs with a *cast* — one of them
        after a roles walk that returns early. This lived inline on the
        activation path alone, so every cast carrying ``requires_source`` was
        handed a spec with no source list, and the browser's source stage (which
        refuses when the list is empty) could not run at all. Honorable Passage
        has been castable-but-sourceless since it shipped for exactly that
        reason; it is bounded at one instance either way, which is why nobody
        saw it.

        Enumerated with ``for_cast=False`` on every path, including the cast
        one, and that is deliberate rather than an oversight carried across: a
        chosen source is **not a target** (CR 115.1), so shroud, protection and
        the rest of the targeting gate have no bearing on whether it may be
        chosen — CR 609.7a adds only that it "doesn't need to be capable of
        dealing damage".
        """
        if not spec.get("requires_source"):
            return
        spec["source_targets"] = self._enumerate_targets(
            controller_index, card, {"kind": "permanent", "also_stack": True},
            for_cast=False,
        )

    def trigger_mode_options(
        self, controller_index: int, card: CardDefinition, instruction, source_permanent=None,
    ) -> list[dict]:
        """Every mode of a modal triggered ability that *can* be chosen, each
        with the targets it could choose (CR 700.2b, CR 603.3c/603.3d).

        One call, asked at the one moment the rule allows the choice — as the
        ability is put on the stack — and asked by **both** halves of that
        moment: ``_choose_trigger_mode`` reads it to decide whether the ability
        may go on the stack at all (an empty list means no mode is legal, and
        the ability is removed), and the prompt it arms offers exactly these
        entries. That is the same shape ``activation_target_refusal`` already
        gives an activated ability, and for the same reason: a gate and a
        picker with two tables between them is this engine's recurring defect.

        A mode that targets and has no legal target is **omitted**, not offered
        and refused — CR 700.2b says it "can't be chosen". A mode that targets
        nothing is always choosable and carries an empty candidate list.

        The candidates come from ``_enumerate_targets``, so a mode is offered
        the same list an activated ability with that same effect would be — the
        protection, shroud and per-kind narrowing all included.
        """
        options: list[dict] = []
        for index, mode in enumerate(modal_trigger_modes(instruction)):
            mode_instruction = mode["instruction"]
            spec = dict(modal_trigger_mode_spec(mode) or {"kind": "none"})
            spec["requires_target"] = spec["kind"] != "none"
            valid = self._enumerate_targets(
                controller_index, card, spec, for_cast=False,
                ability_instruction=targeting_instruction(mode_instruction),
                source_permanent=source_permanent,
                ability_source=source_permanent,
            )
            if spec["requires_target"] and not valid:
                continue
            options.append({
                "index": index,
                "label": mode["label"],
                "instruction": mode_instruction,
                "spec": spec,
                "valid_targets": valid,
            })
        return options

    def activation_target_refusal(
        self, controller_index: int, source_permanent, ability, *,
        target_player_index=None, target_permanent_index=None,
        target_permanent_ids=None, target_stack_item=None,
        target_role_refs=None, x_value=None,
    ) -> str | None:
        """CR 602.2b/601.2c enforced once, before any cost is paid: an ability
        that targets cannot be activated unless a legal target exists, and a
        *named* target must itself be legal.

        The same ``valid_targets`` the web picker is handed (engine derives it
        from the compiled program), so the list offered and the list enforced
        are one list. This replaced a per-kind if-chain in ``activation.py``
        that checked four instruction kinds by hand and let every other
        object-targeted ability be activated with nothing to target — paying
        the cost (tapping the source, most often) and then dealing to the face
        or doing nothing. Returns the refusal text, or None when the ability
        does not target (so nothing is gated).
        """
        # The source is a permanent on almost every path and a **card in a
        # graveyard** on one (Carrionette, CR 113.6m). Both answer "which card
        # is this", and only a permanent can be a *referent* — "another
        # creature", "a creature other than this one" are questions about an
        # object on the battlefield — so the card is read either way and the
        # permanent is passed on only when there is one. Handing a
        # ``CardDefinition`` to ``_enumerate_targets`` instead would make every
        # source-relative filter ask a card a permanent's question.
        card = getattr(source_permanent, "effective_card", source_permanent)
        source = source_permanent if hasattr(
            source_permanent, "permanent_id"
        ) else None
        # CR 602.3's legality half, asked first because it is asked of an
        # ability this gate otherwise has no spec for: the target is announced
        # by an **opponent**, so ``derive_activation_spec`` describes no picker
        # for the activator and every check below is skipped.
        announced = self._announced_choice_refusal(
            controller_index, card, getattr(ability, "instruction", None), source
        )
        if announced is not None:
            return announced
        spec, _ = _activation_spec([ability])
        kind = spec.get("kind")
        # Above every early return below, because the two shapes that accepted
        # a stray stack object are the two that return first.
        stray = self.stray_activation_stack_target_refusal(
            card, spec, target_stack_item,
            names_a_permanent=(
                target_permanent_index is not None
                or any(isinstance(pid, int) for pid in target_permanent_ids or ())
            ),
        )
        if stray is not None:
            return stray
        if kind in _UNOBLIGED_ACTIVATION_KINDS:
            return None
        # A cost payment (Sacrifice) and a chosen *source* (Circle of
        # Protection) are not targets — CR 601.2b/601.2c — so an empty board
        # does not make them unactivatable. Their own paths validate them.
        #
        # Every cost flag, through the one reader of them (PCY W3G5): this was a
        # list of four, and a cost flag it does not name is asked a target's
        # question — Benthic Explorers' untap the day it had a picker, and an
        # exile cost already.
        #
        # ``requires_source`` used to return here as well, and it is not the
        # same answer: it says a source is chosen *beside* a target ("the next
        # time a source of your choice would deal damage to **target
        # creature**", Jade Monolith, Charm Peddler), so the spec it rides is a
        # real target's and the creature was never checked at all. The source
        # half has its own list (``source_targets``) and is not asked here.
        #
        # **A chosen source used to return here too** (``also_stack``), which
        # was half right. It owes no target, so an empty board does not make
        # the ability unactivatable and a bare activation is still accepted —
        # ``activation_target_obligation`` answers None for it and the
        # nothing-owed-nothing-named return below is where that happens. But
        # the return was above everything, so a source that **was named** was
        # never compared with the list its own picker offers: a Grizzly Bears
        # was accepted as Circle of Protection: Red's "red source of your
        # choice", a green spell was, and so were two sources at once. A named
        # source falls through to the comparison every named object gets.
        if spec_is_a_cost(spec):
            return None
        if spec_chooses_a_source(spec):
            # "…**a** source of your choice": one. Counted here because the
            # ceiling below reads ``max_targets``, which a choice does not
            # carry, and because a permanent and a spell named together reach
            # two different branches of the comparison.
            named_sources = len([
                pid for pid in (target_permanent_ids or ()) if pid is not None
            ]) or len([
                idx for idx in (
                    target_permanent_index
                    if isinstance(target_permanent_index, list)
                    else [target_permanent_index]
                )
                if idx is not None
            ])
            if named_sources + (target_stack_item is not None) > 1:
                return f"{card.name} chooses one source, not several"
        instruction = getattr(ability, "instruction", None)
        if kind == ROLES_TARGET_KIND:
            # An ability naming several targets of *different* kinds, chosen in
            # dependency order (Sorrow's Path's two blockers, the second settled
            # by whose creature the first is). There is no second gate behind
            # this one — the cast side defers a roles announcement to
            # ``_validate_cast_targets`` and an activation has nothing of the
            # sort — so the whole announcement is checked here, through the very
            # walk the picker was built from.
            ability_instruction = targeting_instruction(instruction)
            refused = f"no valid target for {card.name}"
            named = self.named_role_objects(
                target_permanent_ids, target_role_refs,
                roles=spec_roles(spec), target_stack_item=target_stack_item,
            )
            if named:
                legal = self._role_targets_legal(
                    controller_index, card, spec, named, for_cast=False,
                    source_permanent=source,
                    ability_instruction=ability_instruction,
                    ability_source=source,
                )
                return None if legal else refused
            if target_stack_item is not None or any(
                role_is_stack(role) for role in spec_roles(spec)
            ):
                # A stack object named with no slot list beside it is half an
                # announcement, and there is no reading of it as "nothing
                # named": the spell would ride the stack item into a
                # resolution whose other role nobody chose.
                #
                # …and with a stack role, nothing named at all is refused too,
                # as a roles *cast* naming nothing is ("requires 2 targets").
                # The bare activation every other roles ability is allowed is
                # the headless convention of letting the resolution pick; a
                # role-scoped step picks nothing (``_role_scoped`` skips it),
                # so here the cost would be paid for an effect that cannot
                # happen.
                return refused
            # Nothing named. CR 602.2b's half of the question first — could
            # the whole announcement be made at all? An empty walk means no,
            # and the cost is never paid.
            walked = self._role_target_walk(
                controller_index, card, spec, (), for_cast=False,
                source_permanent=source,
                ability_instruction=ability_instruction,
                ability_source=source,
            )
            if not walked:
                return refused
            # …and where it could be, it has to be: CR 601.2c announces "an
            # appropriate object or player for **each** target", so a roles
            # announcement naming none of them is not one. The cast side has
            # refused it since `_validate_cast_targets` counted roles
            # ("requires N targets"); an activation was accepted, paid for,
            # and resolved with every role unfilled — the strict role
            # resolvers found nothing, and a seat role fell to the default
            # seat whether or not the picker offered it. Refused rather than
            # defaulted, for the reason a printed count is: which chain of
            # several objects a seat that named none "meant" is not one answer
            # drawn from one list. An announcement that owes nothing ("up to"
            # roles) may still name nobody.
            if activation_target_obligation(ability, x_value=x_value) is not None:
                return f"{card.name} requires {len(spec_roles(spec))} targets"
            return None
        # CR 601.2c's count, asked of an **activation** — the twin of the
        # ``max_targets`` gate ``_cast_refusal`` makes above every per-kind arm,
        # and it was missing here entirely. Above the "no mandatory target"
        # return below, because "up to X target" is precisely a non-mandatory
        # announcement with a printed ceiling: an ability may legally name none
        # of them and may never name more than X.
        #
        # Only a *list* is checked, which is what keeps the per-candidate probe
        # inside ``_enumerate_targets`` from tripping over it: that probe
        # re-enters with one slot, never several.
        self._size_activation_x_targets(
            controller_index, spec, ability, source
        )
        # …and the *announced* X, the half that method leaves alone because
        # only the activation knows it. "{X}{U}, {T}, Discard two cards: Return
        # **X target creatures** to their owners' hands." (Alexi, Zephyr Mage.)
        # CR 601.2c fixes the number of targets from the X announced at
        # CR 601.2b, and the handler returns every slot it is handed — so an X
        # of one naming three creatures bounced all three until this was
        # asked, an ability activated for a third of its printed price. The
        # cast side sizes the same flag from ``announced_cast_x``; this is the
        # activation's twin.
        if spec.get("x_targets") and x_value is not None:
            spec.pop("x_targets", None)
            spec["max_targets"] = max(0, int(x_value))
        maximum = spec.get("max_targets")
        # A card in a graveyard is named by **slot** and has no id (the
        # graveyard branch below says why the stamped ids are not read), so
        # for that kind the list counted is the slot list. It was the id list
        # for every kind, which no graveyard announcement fills: "Exile up to
        # **two** target cards from a single graveyard" (Famished Ghoul) named
        # at three was accepted, paid for — the Ghoul sacrificed — and resolved
        # the first two.
        named_list = (
            target_permanent_index
            if spec.get("kind") == GRAVEYARD_TARGET_KIND
            else target_permanent_ids
        )
        if (
            isinstance(maximum, int)
            and isinstance(named_list, list)
            and len(named_list) > maximum
        ):
            return f"too many targets for {card.name}"
        # CR 115.3's twin on this side, beside the count gate for the same
        # reason the count gate is here: an activation announces its targets
        # (CR 602.2b routes through CR 601.2c), so a repeat is refused before
        # any cost is paid rather than dropped at resolution. Only a *list* is
        # checked, which is what keeps ``_enumerate_targets``' per-candidate
        # probe out of it — that probe re-enters with one slot, never several.
        if isinstance(target_permanent_ids, list):
            repeated = self._repeated_target_refusal(
                card, spec, target_permanent_ids, [], None
            )
            if repeated is not None:
                return repeated
        # **One question, asked of every ability: does it owe a target, and was
        # one named?** (:func:`activation_target_obligation`.) This used to be
        # "does the mandatory-target walk find the word" — and where it did
        # not, the gate returned here without looking at what was named. A
        # named target has to be legal whether or not one is owed: "up to one
        # target creature" may name nobody and may not name an Island.
        obligation = activation_target_obligation(ability, x_value=x_value)
        named_ids = [
            pid for pid in (target_permanent_ids or ()) if pid is not None
        ]
        named_indices = [
            idx for idx in (
                target_permanent_index
                if isinstance(target_permanent_index, list)
                else [target_permanent_index]
            )
            if idx is not None
        ]
        named_object = bool(
            named_ids or named_indices or target_stack_item is not None
        )
        # CR 601.2c's **count**, the other half of the ceiling above:
        # "{T}: Untap **two** target lands" (Argothian Elder) names two, and
        # "{X}, {T}: Untap **X** target lands" (Candelabra of Tawnos) names
        # the X it announced — not one, and not none. The cast side has asked
        # this since ``cast_target_count_refusal``; an activation was held to
        # the ceiling alone, so "two target lands" naming one was accepted
        # and untapped one, and "X target creatures" at X = 3 naming two paid
        # for three. The same question of the same slot
        # (:func:`exact_target_count`), so a printed "up to" and "any number
        # of" stay the ceilings they are.
        #
        # A caller that announced no X (None — the AI's proposal filter, a
        # picker's probe) is not counted against one: a number nobody said is
        # not a number to hold their targets to. ``_activate_onto_stack``
        # hands the gate the X it will resolve with, zero included.
        slot = activation_target_slot(ability)
        required = (
            exact_target_count(spec, slot[1], x_value) if slot is not None else None
        )
        if required is not None:
            named_count = len(named_ids) if named_ids else len(named_indices)
            if named_count != required:
                return (
                    f"{card.name} needs {required} target"
                    + ("s" if required != 1 else "")
                    + f", not {named_count}"
                )
        # A seat is this ability's *target* only where its spec says a player
        # may be one. Everywhere else ``target_player_index`` is the seat a
        # targeted **permanent** sits on (the index branch below reads it
        # exactly that way), and comparing it against the legal players would
        # refuse a legal announcement.
        names_a_seat = (
            target_player_index is not None
            and kind in _SEAT_TARGET_SPEC_KINDS
            and not named_object
        )
        if obligation is None and not named_object and not names_a_seat:
            # Nothing owed and nothing named: an all-"up to" announcement that
            # chose none, an "X target" at X = 0, a chosen source the handler
            # defaults.
            return None
        ability_instruction = targeting_instruction(instruction)
        valid = self._enumerate_targets(
            controller_index, card, spec, for_cast=False,
            ability_instruction=ability_instruction,
            source_permanent=source,
            ability_source=source,
        )
        legal_perm = {
            (t["seat"], t["index"]) for t in valid if t.get("kind") == "permanent"
        }
        legal_grave = {
            (t["seat"], t["index"]) for t in valid if t.get("kind") == "graveyard"
        }
        legal_stack = [t for t in valid if t.get("kind") == "stack"]
        refused = f"no valid target for {card.name}"

        # **A named player has to be one of the legal ones.** "Target
        # **opponent**" strikes the activator's own seat out (CR 102.2/102.3)
        # and a player with shroud cannot be chosen at all (CR 702.18a);
        # ``_enumerate_targets`` already leaves both out of the offered list,
        # and nothing compared the seat the caller named against that list.
        # The picker never offered it; a script, the AI and a test could all
        # name it, and the ability resolved.
        if names_a_seat:
            legal_seats = {
                entry["seat"] for entry in valid if entry.get("kind") == "player"
            }
            if target_player_index not in legal_seats:
                return refused
            return None

        if kind == GRAVEYARD_TARGET_KIND:
            # A card in a graveyard is named by **slot**, in the pile the seat
            # beside it names — or in either pile when no seat was given. Never
            # by the id ``_activate_onto_stack`` stamps off the *battlefield*
            # slot of the same number: that is a permanent the ability never
            # targeted, and comparing its seat against a list of graveyard
            # slots answered about a different zone.
            if named_indices:
                unnamed_pile = _unnamed_single_pile_refusal(
                    card, spec, target_player_index
                )
                if unnamed_pile is not None:
                    return unnamed_pile
                # CR 115.3 for slots, as the cast gate asks it: the repeat
                # check above this branch reads only the id list, which a card
                # in a graveyard never fills, so one slot named twice was
                # accepted and quietly resolved once.
                repeated = self._repeated_target_refusal(
                    card, spec, [], named_indices, target_player_index
                )
                if repeated is not None:
                    return repeated
                seats = (
                    [target_player_index] if target_player_index is not None
                    else list(range(len(self.players)))
                )
                for idx in named_indices:
                    if not any((seat, idx) in legal_grave for seat in seats):
                        return refused
                return None
        elif named_ids:
            # A named target must be legal. The web layer sends ids; a test or
            # the AI may send an index on a seat, which ``_activate_onto_stack``
            # has already turned into the id of the permanent it named.
            for pid in named_ids:
                perm = self.permanent_by_id(pid)
                if perm is None:
                    return refused
                seat = self.controller_index_of(perm)
                idx = self.battlefield_index_of(perm)
                if (seat, idx) not in legal_perm:
                    return refused
            return None
        elif named_indices:
            # A bare index carries no seat, so it is legal if it names a legal
            # target on the seat the caller gave — or, when none was given, on
            # either battlefield (Xenic Poltergeist may animate your own
            # artifact; the resolution finds it by index without a seat).
            seats = (
                [target_player_index] if target_player_index is not None
                else list(range(len(self.players)))
            )
            for idx in named_indices:
                if not any((seat, idx) in legal_perm for seat in seats):
                    return refused
            return None
        if target_stack_item is not None:
            # A named stack spell (Deathgrip, Goblin Artisans): re-locate the
            # legal items by their top-first index, the convention
            # _enumerate_stack_targets emits, and compare by identity.
            depth = len(self.stack)
            legal_items = [
                self.stack[depth - 1 - t["stack_index"]]
                for t in legal_stack
                if 0 <= depth - 1 - t["stack_index"] < depth
            ]
            if not any(item is target_stack_item for item in legal_items):
                return refused
            return None

        # Nothing was named, and a target is owed: the ability is activatable
        # only if some legal target exists (CR 602.2b). This is the census case
        # — an empty board for a "destroy target creature" / "deals N damage to
        # target creature" ability, which used to pay the cost and no-op (or,
        # with an opponent creature present but none chosen, hit the face).
        #
        # With a legal target on the table the bare activation is accepted,
        # and ``_activate_onto_stack`` then makes the announcement for it:
        # the first entry of this same list in standing order
        # (``bare_announcements.default_activation_target``), stamped like a
        # named target. That is the headless caller's default — a test, a
        # scripted duel — and not what a browser may send:
        # :meth:`unannounced_activation_target` is what the wire asks.
        if not valid:
            return refused
        return None

    def unannounced_activation_target(
        self, controller_index: int, source_permanent, ability, *,
        seat_announced: bool,
        target_permanent_index=None, target_permanent_ids=None,
        target_stack_item=None, target_role_refs=None, divided_targets=None,
        x_value=None,
    ) -> str | None:
        """Why an activation that **named no target** may not be accepted from
        a seat that has to name one, or None.

        CR 602.2b sends an activation through CR 601.2c, which is an
        announcement: "the player announces their choice of an appropriate
        object or player for each target". The engine's own API accepts an
        activation that names none while a legal one exists and names the
        picker's first entry for it (``engine/bare_announcements.py``) — a
        stated default, for a scripted duel and the test corpus. A **person**
        is not that caller: the browser runs a picker for every ability whose
        spec asks for one and cannot send the activation without an answer,
        so a bare ``activate`` over the wire is a request no client makes and
        the default behind it is a target nobody chose (Samite Pilgrim's
        shield went to the *opponent*).

        One predicate rather than a test in the route: it is
        :func:`activation_target_obligation` — the gate's own "does this owe a
        target?" — so the wire and the engine cannot come to disagree about
        which abilities are meant. *seat_announced* is the caller's, because
        only the caller knows whether a seat was sent or defaulted (the route
        fills in an opposing seat for every activation); a seat alone is an
        announcement only for an ability whose target may be a player.
        """
        spec = activation_target_obligation(ability, x_value=x_value)
        if spec is None:
            return None
        indices = (
            target_permanent_index
            if isinstance(target_permanent_index, list)
            else [target_permanent_index]
        )
        if (
            any(pid is not None for pid in (target_permanent_ids or ()))
            or any(idx is not None for idx in indices)
            or target_stack_item is not None
            or target_role_refs
            or divided_targets
        ):
            return None
        if seat_announced and spec.get("kind") in _SEAT_TARGET_SPEC_KINDS:
            return None
        card = getattr(source_permanent, "effective_card", source_permanent)
        return f"{card.name}: this ability needs a target (CR 602.2b)"

    def _announced_choice_refusal(
        self, controller_index: int, card, instruction, source
    ) -> str | None:
        """CR 602.3: a target one of the controller's **opponents** chooses.

        "Some abilities specify that one of their controller's opponents does
        something the controller would normally do while it's being activated,
        such as choose a mode or **choose targets**. In these cases, the
        opponent does so when the ability's controller normally would do so."

        Echo Chamber is the pool's one activated printing — "An opponent chooses
        target creature they control" — and the word "target" is what brings
        CR 601.2c with it: an ability whose announced target has no legal object
        cannot be activated at all. It could be, and paid {4} and {T} into a
        choice with no candidates, because the pick is modelled as a
        resolution-time value and so has no spec for the gate above to read.

        **This is the rule's legality half and not the whole rule.** The choice
        is still made as the ability resolves rather than in the announcement,
        so it cannot be responded to and CR 608.2b never re-checks it; that is
        recorded in ROADMAP.md with what closing it needs. What is fixed here is
        the half that costs a player their mana for nothing.

        Deliberately narrow, and silent about every payload it cannot answer
        *exactly*: the resolution's candidate rule reads relative objects,
        recorded sets and Aura legality, and a gate that guessed at those would
        refuse an activation the resolution would have found a choice for. Only
        a plain filter scoped to the chooser's own battlefield is judged here,
        which is the shape both printings have.
        """
        from .subject_filters import subject_matches

        for step in _iter_instruction_tree(instruction):
            payload = step.payload if isinstance(step.payload, dict) else {}
            if step.kind != "choose_permanent" or not payload.get("announced_target"):
                continue
            if payload.get("controlled_by") != "chooser":
                # "…chooses **target creature**", unscoped (Mogg Assassin's
                # second half). The candidates are every creature on the table,
                # which cannot be empty while the ability's own source is one —
                # and the chooser is a seat an earlier step of the resolution
                # records, so there is nothing to resolve here yet either.
                continue
            if payload.get("among_record") or payload.get("legal_host_for_source"):
                continue
            seat = next(
                (
                    index
                    for index, player in enumerate(self.players)
                    if index != controller_index and not player.lost
                ),
                None,
            )
            # The same seat ``handlers/permanent_choices._chooser_seat`` will
            # pick, so the gate and the resolution cannot disagree about whose
            # board was asked. No opponent at all is a choice nobody can make,
            # which the resolution already reports and this must not turn into
            # a refusal.
            if seat is None:
                continue
            described = payload.get("filter") or {}
            if any(
                subject_matches(
                    self, perm, described, observer=seat, source=source
                )
                for perm in self.controlled_by(seat)
            ):
                continue
            return f"no valid target for {getattr(card, 'name', '')}"
        return None

    def _repeated_target_refusal(
        self,
        card,
        spec: dict,
        named_ids: list,
        indices: list,
        target_player_index: int | None,
    ) -> str | None:
        """CR 115.3: one object may not fill two slots of a single announcement.

        "The same target can't be chosen multiple times for any one instance of
        the word 'target'" — so a sentence printing the word once and pluralised
        ("**two** target nonartifact creatures") wants two different objects,
        and a sentence printing it twice may name one object once per instance
        unless the card says "**another**". Which of the two a description is
        was decided in ``targeting.py``; ``distinct_targets`` is that answer,
        and this gate only enforces it.

        Asked of the *announcement*, above the enumeration, because a repeat is
        illegal however legal each named object is on its own — the per-candidate
        walk below says yes to the same creature twice and is right to. Refused
        rather than deduplicated: with a single creature on the battlefield,
        naming it twice is how Ashes to Ashes ("exile **two** target nonartifact
        creatures") came to be castable at all, exiling that one creature and
        charging its printed 5 life for a spell that had no legal announcement.

        Both channels, in their own vocabulary: an id addresses a permanent
        across seats (CR 400.7) and an index is a slot on one player's
        battlefield or in one player's graveyard, so a bare index is only the
        same target as another when the seat beside it agrees.
        """
        if not spec.get("distinct_targets"):
            return None
        keys: list = (
            list(named_ids) if named_ids
            else [(target_player_index, index) for index in indices]
        )
        if len(set(keys)) == len(keys):
            return None
        return f"{card.name} can't name the same target twice"
