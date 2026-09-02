from __future__ import annotations

"""Declare attackers step (CR 508).

The active player declares attackers (and any attacking bands) as a turn-based
action, taps the attackers CR 508.1f taps, puts any attack triggers on the stack
(CR 508.2), then receives priority (CR 508.4) so the triggers resolve as players
pass. Also holds the attack-legality query (``can_attack``),
"must attack if able" enforcement, and the banding-declaration validation.
"""

from ..attack_tapping import attacking_causes_tap
from ..auras import attached_combat_restrictions, aura_restriction_active
from ..combat_permissions import ATTACK_AS_THOUGH_NO_DEFENDER
from ..combat_restrictions import declaration_company_required, participation_cap
from ..mana_payment import mana_cost_label, plan_payment, untapped_mana_lands
from ..subject_filters import subject_matches
from ..events import emit
from ..models import Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..static_bonuses import conditional_static_holds
from ..trigger_utils import matching_triggers
from ..turn_state import attacked_during_seats_last_turn, record_attack


class DeclareAttackersStepMixin:
    def declare_attackers(
        self,
        controller_index: int,
        attacker_indices: list[int],
        defending_player_index: int | None = None,
        bands: list[list[int]] | None = None,
        attacker_targets: dict[int, int] | None = None,
        attacker_planeswalker_ids: dict[int, int] | None = None,
    ) -> tuple[bool, str]:
        """Declare attackers (CR 508). Under CR 802 (attack multiple players), each
        attacker may name its own defending player via ``attacker_targets`` (attacker
        battlefield idx -> defending player idx). Any attacker not present in
        ``attacker_targets`` falls back to the shared ``defending_player_index`` —
        the original 2-player/back-compat shorthand of "everyone attacks this one
        opponent", still exactly how every existing (2-player) caller behaves.

        CR 508.1b: an attacker may instead attack a planeswalker an opponent
        controls — ``attacker_planeswalker_ids`` maps attacker battlefield idx to
        the attacked planeswalker's ``permanent_id``. Such an attacker's
        defending *player* (for blocks, restrictions and CR 508.5) is the
        planeswalker's controller, derived here rather than asked for twice."""
        if self.current_turn_phase != "combat" or self.current_step != "declare_attackers":
            return False, "attackers can only be declared during declare_attackers"
        if controller_index != self.active_player_index:
            return False, "only the active player may declare attackers"

        controller = self.players[controller_index]
        unique_indices = sorted(set(attacker_indices))
        living_opponents = self.opponents_of(controller_index)

        attacker_targets = dict(attacker_targets or {})
        attacker_planeswalker_ids = dict(attacker_planeswalker_ids or {})
        per_attacker_walker: dict[int, int] = {}
        for idx, walker_id in attacker_planeswalker_ids.items():
            if idx not in unique_indices:
                return False, f"planeswalker target given for non-attacker {idx}"
            walker = self.permanent_by_id(walker_id)
            if walker is None or not walker.has_type("planeswalker"):
                return False, "attacked planeswalker is not on the battlefield"
            walker_seat = self.controller_index_of(walker)
            if walker_seat is None or walker_seat == controller_index:
                return False, "a creature can only attack an opponent's planeswalker"
            # The walker names the defending player (CR 508.5); a contradictory
            # explicit seat for the same attacker is a malformed declaration.
            stated = attacker_targets.get(idx)
            if stated is not None and stated != walker_seat:
                return False, "attacker's defending player contradicts its attacked planeswalker"
            attacker_targets[idx] = walker_seat
            per_attacker_walker[idx] = walker_id

        per_attacker_defender: dict[int, int] = {}
        for idx in unique_indices:
            target = attacker_targets.get(idx, defending_player_index)
            if target is None:
                # No explicit target for this attacker: with exactly one living
                # opponent (2-player games, always) that's unambiguous — attack
                # them, exactly as every existing caller already assumes. Only a
                # genuine 3+ player choice requires an explicit target.
                if len(living_opponents) == 1:
                    target = living_opponents[0]
                else:
                    return False, f"no defending player chosen for attacker {idx}"
            per_attacker_defender[idx] = target

        living_opponents_set = set(living_opponents)
        for target in per_attacker_defender.values():
            if target < 0 or target >= len(self.players) or target == controller_index:
                return False, "invalid defending player"
            if target not in living_opponents_set:
                return False, "that player has already left the game"

        # "No more than two creatures can attack each combat." (Caverns of
        # Despair.) CR 508.1c is a restriction on the *declaration*, not on any
        # one creature, so it cannot live in `can_attack` — a per-creature
        # predicate has no way to say "and no more of you". Read off the board
        # rather than off the attacker, because the enchantment is a permanent
        # nobody is attacking with.
        attack_cap = participation_cap(self.all_permanents(), "attack")
        if attack_cap is not None and len(unique_indices) > attack_cap:
            return False, (
                f"no more than {attack_cap} creature(s) can attack each combat"
            )

        required_attackers: list[str] = []
        for idx, attacker in enumerate(controller.battlefield):
            if not self._is_creature(attacker) or attacker.tapped:
                continue
            if idx in unique_indices:
                continue
            if self._must_attack_if_able(attacker) and any(
                self.can_attack(attacker, opp) for opp in living_opponents
            ):
                required_attackers.append(attacker.card.name)
        # CR 508.1d: requirements are obeyed to the maximum **subject to** the
        # restrictions. A declaration already sitting at the cap has obeyed as
        # many "attacks each combat if able" requirements as it legally can, so
        # a further one is not violated — Primordial Ooze under Caverns of
        # Despair is exactly this, and enforcing the requirement anyway would
        # make a legal declaration impossible.
        if attack_cap is not None and len(unique_indices) >= attack_cap:
            required_attackers = []
        if required_attackers:
            if len(required_attackers) == 1:
                return False, f"{required_attackers[0]} must attack if able"
            names = ", ".join(required_attackers)
            return False, f"{names} must attack if able"

        declared_attackers: list[Permanent] = []
        for idx in unique_indices:
            if idx < 0 or idx >= len(controller.battlefield):
                return False, "attacker index out of range"
            attacker = controller.battlefield[idx]
            declared_attackers.append(attacker)
            if not self._is_creature(attacker):
                return False, "only creatures can attack"
            if attacker.tapped:
                return False, f"{attacker.card.name} is tapped"
            if not self.can_attack(
                attacker,
                per_attacker_defender[idx],
                # CR 508.5: this attacker attacks the planeswalker, and its
                # defending player is derived — so a restriction scoped to
                # attacking "a player" (Arboria) must know the difference.
                attacking_planeswalker=idx in per_attacker_walker,
            ):
                return False, f"{attacker.card.name} cannot attack"

        # The restrictions that are about the **set** (CR 508.1c) rather than
        # about any one creature — the same reason the attack cap above is
        # checked here. They live behind one named predicate because the AI asks
        # it too; see `attack_declaration_refusal`.
        refusal = self.attack_declaration_refusal(declared_attackers)
        if refusal is not None:
            return False, refusal[1]

        # CR 702.22c: validate any declared attacking bands before committing.
        validated_bands, band_error = self._validate_attacking_bands(
            bands, unique_indices, controller
        )
        if band_error is not None:
            return False, band_error

        # CR 508.1g, the mana half: the costs of every declared attacker are one
        # payment, planned here - before anything is tapped and before anything
        # is committed - so the gate and the charge below read the same board.
        declaration_mana, mana_plan = self._declaration_mana_plan(
            controller_index,
            declared_attackers,
            # Who each attacker is attacking, in the order the attackers are
            # listed — CR 508.5's planeswalker attacks contribute None, because
            # a toll on attacking a *player* (Koskun Falls) is not owed by a
            # creature attacking that player's planeswalker.
            [
                None if idx in per_attacker_walker else per_attacker_defender[idx]
                for idx in unique_indices
            ],
        )
        if declaration_mana and mana_plan is None:
            return False, (
                f"cannot pay {mana_cost_label(declaration_mana)} to declare "
                "these attackers"
            )
        # The sacrifice half of the same rule, planned for the same reason:
        # several attackers' costs draw on one board, and `can_attack` answers
        # for one creature at a time.
        sacrifice_plan = self._declaration_sacrifice_plan(
            controller_index, declared_attackers
        )
        if sacrifice_plan is None:
            return False, "cannot pay the sacrifice cost to declare these attackers"

        self.combat_attackers = dict(per_attacker_defender)
        self.combat_attacked_planeswalkers = dict(per_attacker_walker)
        self.combat_defending_player_index = self._resolve_defending_player_index()
        self.combat_blockers = {}
        self.combat_blockers_declared_by = set()
        self.combat_bands = validated_bands
        self.combat_band_blocks = {}
        self.combat_banding_damage = {}
        self.combat_multiblock_damage = {}
        self.combat_damage_resolved = False
        self.combat_first_strike_done = False
        self.combat_attackers_locked = True
        self.combat_blockers_locked = False
        self.combat_unblocked_triggers_fired = False
        self._prune_combat_state()

        declared: list[Permanent] = []
        for idx in unique_indices:
            attacker = controller.battlefield[idx]
            declared.append(attacker)
            # CR 508.1f, and the one place the question is asked: vigilance
            # (CR 702.20b) and an effect that prints the same exemption the long
            # way round (Johan) are both `attacking_causes_tap`'s business.
            if attacking_causes_tap(self, attacker):
                self.become_tapped(attacker)
                self._turn_face_up(attacker)
            attacker.metadata["attacked_this_turn"] = True
            # The **per-combat** half of the same record, the mirror of the
            # ``blocked_this_combat`` mark the blockers step writes and
            # ``end_combat`` sweeps. "…if this creature attacked or blocked
            # **this combat**" (the Clockwork cycle, Kjeldoran Home Guard) needs
            # both, and neither of the two records already here answers it: the
            # turn mark above is still set in a turn's *second* combat phase,
            # and the ``combat_attackers`` map lets go of a creature removed
            # from combat (Maze of Ith) that did attack this combat all the
            # same. CR 506.4 removes a creature from combat; it does not unmake
            # the declaration.
            attacker.metadata["attacked_this_combat"] = True
            # The durable half of that record: which seat's turn it attacked
            # on, by that seat's own turn ordinal. `attacked_this_turn` is
            # swept at cleanup, and "it attacked during your last turn" (Giant
            # Turtle) is a question asked one turn later — so this key is
            # deliberately not in `_EOT_METADATA_KEYS`, and it dies with the
            # permanent instead (CR 400.7: a Turtle that leaves and returns is
            # a new object with no record). Overwritten on each attack; only
            # the latest one can be "your last turn".
            record_attack(
                attacker,
                controller_index,
                self.seat_turn_counts.get(controller_index, 0),
            )

        if declared:
            # CR 508.1: the seat that declared them attacked this turn. Stamped
            # here, once, beside the per-creature record — "target player who
            # attacked this turn" (Fire and Brimstone) asks about the player,
            # and the creature that carried the attack may be gone by the time
            # the question is asked.
            controller.attacked_this_turn = True

        # CR 508.1g: the additional costs are paid once the declaration is
        # legal, and after the attackers are locked in — so the sacrifices go
        # through `Game.sacrifice_permanent` (the one seam every sacrifice
        # passes through) and the combat maps follow their creatures through
        # `remove_from_battlefield`'s renumbering. `can_attack` has already
        # refused a declaration whose cost cannot be paid, off the same reader,
        # so nothing here can be half-charged.
        self._pay_declaration_sacrifices(controller_index, sacrifice_plan)
        # The mana half of the same rule, spending the plan made above - never a
        # second `plan_payment`, which would read a board the attackers have
        # since been tapped on.
        self._pay_declaration_mana(controller_index, declaration_mana, mana_plan)

        self._prune_combat_state()
        self.log.append(f"{controller.name} declared {len(unique_indices)} attacker(s)")
        if validated_bands:
            self.log.append(f"{controller.name} declared {len(validated_bands)} band(s)")
        if unique_indices:
            self._fire_attack_triggers(controller_index)
            self._fire_creature_attacks_triggers(controller_index, unique_indices)
            self._fire_matching_creature_attacks_triggers(declared)
            self._announce_attack_declaration(controller_index, declared)
            self._fire_delayed_attack_triggers(controller_index, unique_indices)
        # CR 508.4: once attackers have been declared (the turn-based action of the
        # declare attackers step), the active player receives priority.
        self.start_priority_window(self.active_player_index)
        return True, "declared attackers"

    def _fire_delayed_attack_triggers(
        self, controller_index: int, attacker_indices: list[int]
    ) -> None:
        """Delayed "whenever … creature(s) attack this turn" triggers created
        by a resolved loyalty ability (CR 603.7 — Basri Ket's −2, Basri,
        Devoted Paladin's −1). A batch entry fires once per attack with the
        count of matching attackers; a per-creature entry fires once per
        matching attacker, with that attacker as the trigger's source so its
        "on it" resolves to the creature. Entries stay armed for every combat
        this turn — cleanup clears them.

        This is the one delayed event whose firing is not one announcement per
        object, so it keeps its own site rather than calling
        ``fire_delayed_triggers``: an attack is a single event about a *set* of
        creatures, and the batch spelling turns that set into one number.
        The entry object, the trigger-event builder and the expiry rule are
        still the shared ones.
        """
        if not self.delayed_triggers:
            return
        controller = self.players[controller_index]
        attackers = [
            perm
            for idx in attacker_indices
            if (perm := self.permanent_at(controller, idx)) is not None
        ]
        if not attackers:
            return
        defending = next(iter(sorted(self.combat_defending_players())), None)
        events: list[dict] = []
        for entry in list(self.delayed_triggers):
            if entry.instruction is None:
                continue
            # "…whenever **a creature you control with power 2 or less**
            # attacks" (Subira's shape, on the attack event). `matches` asks
            # the entry's own narrowing through `subject_matches`, because
            # "you control" is a seat comparison the object alone cannot
            # answer (CR 109.5). `nontoken` stays its own key: it predates
            # this and the two payloads are not the same shape.
            matching = [
                perm for perm in attackers
                if not (entry.nontoken and perm.metadata.get("is_token"))
                and entry.matches(self, "creatures_attack", perm)
            ]
            if not matching:
                continue
            if entry.batch:
                events.append(entry.trigger_event(trigger_context={
                    "trigger_count": len(matching),
                    "trigger_defending_player_index": defending,
                }))
            else:
                for perm in matching:
                    events.append(entry.trigger_event(
                        source_permanent=perm,
                        trigger_context={
                            "trigger_defending_player_index": defending,
                        },
                    ))
        if events:
            self._enqueue_triggered_batch(events)

    def _declaration_sacrifice_plan(
        self, controller_index: int, attackers: list[Permanent]
    ) -> "list[Permanent] | None":
        """Which permanents pay the whole declaration's CR 508.1g sacrifices,
        or None when the board cannot pay them all.

        The sacrifice twin of :meth:`_declaration_mana_plan`, and it exists for
        that method's reason exactly: the costs of *every* declared attacker are
        one payment, and `can_attack` is a per-creature predicate that can say
        "there is a land for this one" and cannot say "and another for the next".
        Two green creatures under Flooded Woodlands with one Forest were each
        gated as payable, declared, and then charged once — a card doing less
        than it prints, on a board it should have kept home. Leviathan has had
        the same hole for as long as it has been implemented; nothing in the
        pool ever had two of them out at once.

        A **matching**, not a greedy pass, for `plan_payment`'s reason one rule
        over: costs can overlap ("a land" beside "two Islands"), and a greedy
        assignment that spends the Island on "a land" under-reports a board that
        could pay. CR 508.1g asks what the player is able to do.

        Candidates are ordered by ``sacrifice_preference_key`` so the policy
        every other forced sacrifice follows decides *which* permanent answers a
        cost whenever more than one could; the matching only decides which cost
        each one answers.
        """
        units: list[tuple[dict, Permanent]] = []
        for attacker in attackers:
            for cost in self._attack_costs_of(attacker):
                described = dict(cost.get("filter") or {})
                units.extend(
                    [(described, attacker)] * max(0, int(cost.get("count", 1)))
                )
        if not units:
            return []
        candidates = sorted(
            self.controlled_by(controller_index),
            key=self.sacrifice_preference_key,
        )
        # Kuhn's algorithm. The attacker a cost is paid *for* is never eaten by
        # it — it is the creature the cost buys the attack for — which is the
        # exclusion the per-cost charge made, kept here as part of what a unit
        # may match.
        paid_by: dict[int, int] = {}

        def _assign(unit: int, seen: set[int]) -> bool:
            described, attacker = units[unit]
            for slot, candidate in enumerate(candidates):
                if slot in seen or candidate is attacker:
                    continue
                if not subject_matches(self, candidate, described):
                    continue
                seen.add(slot)
                if slot not in paid_by or _assign(paid_by[slot], seen):
                    paid_by[slot] = unit
                    return True
            return False

        for unit in range(len(units)):
            if not _assign(unit, set()):
                return None
        return [candidates[slot] for slot in sorted(paid_by)]

    def _pay_declaration_sacrifices(
        self, controller_index: int, plan: list[Permanent]
    ) -> None:
        """Sacrifice what :meth:`_declaration_sacrifice_plan` chose (CR 508.1g).

        The plan is spent rather than re-derived, for the reason the mana half
        is: a second pass would read a board the first sacrifices have already
        changed. By identity through ``sacrifice_permanent``, the one transition
        every sacrifice passes through, so nothing here has to know that each one
        renumbers the battlefield behind it.
        """
        if not plan:
            return
        player = self.players[controller_index]
        for permanent in plan:
            if self.is_on_battlefield(permanent):
                self.sacrifice_permanent(permanent)
        self.log.append(
            f"{player.name} paid the declaration's attack costs "
            f"({len(plan)} sacrificed)"
        )

    def _attack_mana_costs_of(
        self, attacker: Permanent, attacked_seat: int | None = None
    ) -> list[dict[str, int]]:
        """The mana costs *attacker* owes to be declared (CR 508.1g).

        "Enchanted creature can't attack unless its controller pays {3}."
        (Brainwash.) Three channels, one reader: the restriction printed on the
        creature itself, which reaches its compiled program as an instruction;
        the one printed on an Aura *about* the creature, which does not - that
        text is on the Aura, so it is read through
        ``auras.attached_combat_restrictions``; and the one printed on a
        permanent the **defending player** controls ("Creatures can't attack you
        unless their controller pays {2} for each creature they control that's
        attacking you", Koskun Falls). All three come from one table
        (``combat_restrictions._PATTERNS``), which is why a card printing any of
        those wordings needs nothing here.

        *attacked_seat* is the player this attacker is attacking, or None when
        it attacks a planeswalker instead (CR 508.5 - it still has a defending
        player, but it is not attacking that **player**, and Koskun Falls' toll
        is on attacking one). None is also what a caller with no combat in view
        passes, and it costs only the third channel.

        One reader for the gate in ``can_attack`` and the charge in
        ``declare_attackers``, exactly as ``_attack_costs_of`` below is: a cost
        checked by one rule and paid by another is how a declaration gets
        accepted and then left unpaid.
        """
        costs: list[dict[str, int]] = []
        sources = [
            instruction.payload
            for instruction in compile_card_oracle(attacker.effective_card).instructions
            if instruction.kind == "cant_attack_unless_pay"
        ]
        sources += [
            restriction.payload
            for restriction in attached_combat_restrictions(attacker)
            if restriction.kind == "cant_attack_unless_pay"
        ]
        if attacked_seat is not None:
            # Once per attacker, which is what "for each creature they control
            # that's attacking you" prints: the declaration sums every
            # attacker's costs into one payment
            # (``_declaration_mana_plan``), so the multiplication is the sum
            # rather than a number in the payload.
            sources += [
                instruction.payload
                for permanent in self.controlled_by(attacked_seat)
                for instruction in compile_card_oracle(
                    permanent.effective_card
                ).instructions
                if instruction.kind == "creatures_cant_attack_you_unless_pay"
            ]
        for payload in sources:
            cost = {
                symbol: int(amount)
                for symbol, amount in (payload.get("mana") or {}).items()
            }
            if cost:
                costs.append(cost)
        return costs

    def _declaration_mana_plan(
        self,
        controller_index: int,
        attackers: list[Permanent],
        attacked_seats: list[int | None] | None = None,
    ):
        """How the whole declaration's CR 508.1g mana is paid, or None.

        The costs of *every* declared attacker add up into one payment, and that
        is the difference between this and ``can_attack``: a per-creature
        predicate can say "you could pay {3} for this one" and cannot say "and
        {3} again for the next", so a player with three mana would declare two
        Brainwashed creatures and be charged for one. The same reason
        ``participation_cap`` is enforced where the declaration is assembled.

        The plan is made **before** anything is tapped, so the gate and the
        charge read one board - and the declared attackers are excluded from
        what may pay, because CR 508.1f is about to tap them and an animated
        land would otherwise be spent twice.
        """
        total: dict[str, int] = {}
        seats = attacked_seats or [None] * len(attackers)
        for attacker, attacked_seat in zip(attackers, seats):
            for cost in self._attack_mana_costs_of(attacker, attacked_seat):
                for symbol, amount in cost.items():
                    total[symbol] = total.get(symbol, 0) + amount
        if not total:
            return {}, None
        controller = self.players[controller_index]
        available = [
            land
            for land in untapped_mana_lands(self.controlled_by(controller))
            if not any(land is attacker for attacker in attackers)
        ]
        return total, plan_payment(controller.mana_pool, available, total)

    def _pay_declaration_mana(
        self, controller_index: int, total: dict[str, int], plan
    ) -> None:
        """Spend the plan ``_declaration_mana_plan`` made (CR 508.1g).

        Floating mana first and then untapped lands - the stated policy every
        cost with no priority window behind it takes in this engine, because
        declaring an attacker gives its controller no window in which to tap.
        """
        if plan is None:
            return
        controller = self.players[controller_index]
        for symbol, amount in plan.from_pool.items():
            controller.mana_pool[symbol] = int(controller.mana_pool.get(symbol, 0)) - amount
        for land in plan.tapped:
            self.become_tapped(land)
        self.log.append(
            f"{controller.name} paid {mana_cost_label(total)} to declare attackers"
        )

    def _attack_costs_of(self, attacker: Permanent) -> list[dict]:
        """The additional costs *attacker* must pay to be declared (CR 508.1g).

        One reader for the gate in ``can_attack`` and the charge in
        ``declare_attackers``: a cost checked by one rule and paid by another is
        how a declaration gets accepted and then left unpaid.

        Two sources, and the difference is only where the sentence is printed.
        The creature's own clause names itself ("This creature can't attack
        unless you sacrifice two Islands", Leviathan). A **board** clause names
        a class ("Green creatures can't attack unless their controller
        sacrifices a land of their choice for each green creature they control
        that's attacking", Flooded Woodlands) — and its "for each" is what makes
        it belong here rather than over the declaration: one land per attacking
        member *is* a per-attacker cost, so the sum the declaration charges is
        the sum the card asks for, with no second adder to keep in step.
        """
        costs = [
            instruction.payload
            for instruction in compile_card_oracle(attacker.effective_card).instructions
            if instruction.kind == "cant_attack_unless_sacrifice"
        ]
        attacker_seat = self.controller_index_of(attacker)
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(source_perm.effective_card).instructions:
                if instr.kind != "creatures_cant_attack_unless_sacrifice":
                    continue
                # CR 109.5 for the printed noun phrase: "you control" inside it
                # would mean the seat controlling the *enchantment*, which is
                # what scopes a one-sided printing. The cost is owed by the
                # attacker's controller either way — "their controller" — and
                # that is the seat `_pay_attack_cost` charges.
                if subject_matches(
                    self, attacker, dict(instr.payload.get("subject") or {}),
                    observer=source_seat, source=source_perm,
                ):
                    costs.append(instr.payload)
        return costs

    def can_attack(
        self,
        attacker: Permanent,
        defending_player_index: int,
        *,
        attacking_planeswalker: bool = False,
    ) -> bool:
        # *attacking_planeswalker* is CR 508.5's distinction: an attacker aimed
        # at a planeswalker still has a defending player (that planeswalker's
        # controller — passed as *defending_player_index*), but it is not
        # attacking that **player**, so a restriction scoped to attacking a
        # player (Arboria) does not reach it. Defaulted False because every
        # other restriction in this function restricts *attacking*, whichever
        # object is attacked.
        #
        # "Can attack as though it had haste" (Instill Energy) lifts CR 302.6's
        # attack clause only — not its {T}-ability clause, which is why it is a
        # restriction here rather than a haste grant.
        program = compile_card_oracle(attacker.effective_card)
        instr_kinds = {i.kind for i in program.instructions}

        if self._is_summoning_sick(attacker) and not aura_restriction_active(
            attacker, "attacks_as_though_hasty"
        ):
            # "This creature can attack as though it had haste **unless it
            # entered this turn**." (Chaos Lord.) The creature's own printed
            # permission, beside the Aura-granted one (Instill Energy) — and
            # the exception is read off the *entry* stamp, never off summoning
            # sickness: this card changes controller every upkeep and
            # `_sync_control` rewrites that stamp, so asking it would answer
            # "it entered this turn" because of the control change the ability
            # exists to cause, and the permission would never once apply.
            if not (
                "attacks_as_though_hasty_unless_it_entered" in instr_kinds
                and not self.entered_this_turn(attacker)
            ):
                return False

        # What the defending player controls, and which answer forbids the
        # attack. Both are *data*: "unless … an Island" (Sea Serpent) and "if …
        # an untapped creature with power 3 or greater" (Goblin Mutant) are one
        # question under two polarities, and the noun is a whole printed phrase
        # rather than the five basic land words this used to hold. That
        # narrowing was the enforcement's, not the card's — the scan matched a
        # land by name — so a creature naming anything else had nowhere to go.
        #
        # `subject_matches` is the one reader of a filter payload, so a text
        # changed land type (Magical Hack, Phantasmal Terrain) counts here for
        # the same reason it counts everywhere else, and no re-scoping to lands
        # is needed: CR 205.3i puts a land subtype only on a land.
        #
        # CR 508.1c makes restrictions cumulative — "if any restrictions are
        # being disobeyed, the declaration is illegal" — so satisfying this
        # one answers only this one. This used to `return` the answer, which
        # let a Sea Serpent attack a player under Island Sanctuary the moment
        # they controlled an Island; Sea Serpent's own clause *requires* that
        # Island, so the two cards contradict each other on exactly the board
        # where both are played, and they have shipped together since Alpha.
        # It also skipped the defender check below, so a Wall printed with
        # this clause could attack at all.
        defender_board = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_unless_defender_controls"
            ),
            None,
        )
        if defender_board is not None:
            described = dict(defender_board.payload.get("subject") or {})
            held = any(
                subject_matches(
                    self, perm, described,
                    # CR 109.5: "you" inside the noun phrase would be the
                    # ability's controller, which is the attacker's seat — not
                    # the defender whose board is being scanned. The scan picks
                    # the board; the observer answers the phrase.
                    observer=self.controller_index_of(attacker),
                    source=attacker,
                )
                for perm in self.controlled_by(defending_player_index)
            )
            if held is not bool(defender_board.payload.get("required", True)):
                return False

        # "…unless you control four or more artifacts" (Gadrak). The attacker's
        # *own* controller is counted, which is the difference from the land
        # clause above — and CR 508.1c keeps it cumulative for the same reason
        # that one is: satisfying this restriction answers only this one.
        without_count = next(
            (
                i for i in program.instructions
                if i.kind == "cant_attack_without_controlled_count"
            ),
            None,
        )
        if without_count is not None:
            wanted = int(without_count.payload.get("count", 0))
            card_type = str(without_count.payload.get("controlled_type") or "")
            # `has_type`, so an animated artifact land counts as the artifact it
            # currently is (CR 613 layer 4) — the same rule the land clause
            # above follows for a text-changed type.
            held = sum(
                1 for perm in self.controlled_by(self.controller_index_of(attacker))
                if perm.has_type(card_type)
            )
            if held < wanted:
                return False

        # The creature's own printed clause, and the one an Aura imposes
        # (Faith's Fetters). Asked of the Auras attached right now, so the
        # restriction ends when the Aura does without anything clearing a flag —
        # the arrangement every other entry in that table already uses.
        if "cant_attack" in instr_kinds or aura_restriction_active(
            attacker, "cant_attack"
        ):
            return False

        # The board-reaching restrictions, asked of every permanent's compiled
        # program rather than of the attacker's own — a restriction printed on
        # one permanent that reaches creatures it does not name. Asked at
        # declaration, the read that matters, so each begins and ends with the
        # permanent carrying it. CR 508.1c keeps every branch cumulative:
        # passing one restriction answers only that one.
        #
        # - "Except for creatures named Akron Legionnaire and artifact
        #   creatures, creatures you control can't attack." — scoped to the
        #   carrier's controller, exempting an exception union.
        # - "Creatures without flying can't attack." (Moat) / "Non-Eye
        #   creatures you control can't attack." (Evil Eye of Orms-by-Gore) —
        #   a described set, carried as one `subject` filter payload.
        # - Arboria's "creatures can't attack a player unless that player cast
        #   a spell or put a nontoken permanent onto the battlefield during
        #   their last turn" — a fact about the *defending player*, read off
        #   the per-seat record the turn boundary folds.
        #
        # Every noun phrase is tested by `subject_matches`, the one reader of
        # a filter payload, so a member means here exactly what it means on a
        # blocker whitelist.
        attacker_seat = self.controller_index_of(attacker)
        for source_seat, source_perm in self.permanents_with_controller():
            for instr in compile_card_oracle(source_perm.effective_card).instructions:
                if instr.kind == "controlled_creatures_cant_attack":
                    if source_seat != attacker_seat:
                        continue
                    exceptions = instr.payload.get("exceptions") or ()
                    if not any(
                        subject_matches(
                            self, attacker, dict(member),
                            observer=source_seat, source=source_perm,
                        )
                        for member in exceptions
                    ):
                        return False
                elif instr.kind == "creatures_cant_attack":
                    described = dict(instr.payload.get("subject") or {})
                    # "You control" inside the subject is relative to the
                    # permanent *carrying* the restriction (CR 109.5), which is
                    # what scopes Evil Eye to its own controller's creatures
                    # while Moat, with no controller key, reaches every seat's.
                    if subject_matches(
                        self, attacker, described,
                        observer=source_seat, source=source_perm,
                    ):
                        return False
                elif instr.kind == "creatures_that_attacked_last_turn_cant_attack":
                    # "Creatures that attacked during their controller's last
                    # turn can't attack." (Halls of Mist.) Giant Turtle's
                    # question asked of the board rather than of one creature,
                    # so it is read here in the scan rather than off the
                    # attacker's own program — and asked of the **attacker's**
                    # seat, not the Halls' controller's, because "their
                    # controller" is whose creature it is. One reader with the
                    # self form (`turn_state.attacked_during_seats_last_turn`),
                    # so a creature that attacked under a thief is answered the
                    # same way both cards ask it.
                    if attacker_seat is not None and attacked_during_seats_last_turn(
                        self, attacker, attacker_seat
                    ):
                        return False
                elif instr.kind == "cant_attack_unless_defender_acted":
                    if attacking_planeswalker:
                        # "…can't attack **a player**": a planeswalker is not
                        # one (CR 508.5), so this restriction says nothing.
                        continue
                    if not self.last_own_turn_activity.get(
                        defending_player_index, False
                    ):
                        return False

        # "This creature can't attack if it attacked during your last turn."
        # (Giant Turtle.) The record is the stamp `declare_attackers` writes on
        # every attacker — which seat attacked with it, on that seat's own turn
        # ordinal — and "your last turn" is ordinal arithmetic against the
        # current controller: the stamp names *this* seat's previous turn
        # exactly when its ordinal is one less than the seat's current one. A
        # Turtle that attacked under a thief compares against the thief's
        # seat, not yours, and attacks freely once home (the stamp's seat is
        # part of the record, not just its turn).
        if "cant_attack_if_attacked_last_turn" in instr_kinds:
            if attacked_during_seats_last_turn(self, attacker, attacker_seat):
                return False

        # "This creature can't attack unless you sacrifice two Islands."
        # (Leviathan.) CR 508.1g: an additional cost to attack. This is the
        # *gate* half — a cost its controller cannot pay makes the attack
        # illegal — and `_attack_costs_of` is the one reader, shared with the
        # charge in `declare_attackers`, so the declaration can never be
        # accepted and then left unpaid (or paid and then rejected).
        for cost in self._attack_costs_of(attacker):
            if len(self._sacrifice_candidate_indices(
                self.players[attacker_seat], dict(cost.get("filter") or {}), attacker
            )) < int(cost.get("count", 1)):
                return False

        # "Enchanted creature can't attack unless its controller pays {3}."
        # (Brainwash.) The mana twin, and asked here as well as over the whole
        # declaration because this predicate is what "attacks each combat **if
        # able**" reads: a creature whose cost its controller cannot cover is
        # not able, and enforcing a requirement against it would make a legal
        # declaration impossible. The declaration-wide check in
        # `declare_attackers` is what adds several attackers' costs together;
        # this one answers only for this creature, which is all a per-creature
        # predicate can honestly say.
        for cost in self._attack_mana_costs_of(
            attacker,
            None if attacking_planeswalker else defending_player_index,
        ):
            if plan_payment(
                self.players[attacker_seat].mana_pool,
                [
                    land
                    for land in untapped_mana_lands(self.controlled_by(attacker_seat))
                    if land is not attacker
                ],
                cost,
            ) is None:
                return False

        # One-shot blanket restrictions ("Creatures can't attack this turn",
        # Festival), the attack twin of `blocking_restrictions_until_eot`.
        # Asked here rather than stamped on each creature so a creature that
        # entered after the spell resolved is caught too, and tested through
        # `subject_matches` — the one reader of a filter payload — so the noun
        # phrase means here exactly what it means anywhere else. CR 508.1c
        # keeps it cumulative: passing every other restriction answers only
        # those.
        for entry in self.attack_restrictions_until_eot:
            if subject_matches(self, attacker, dict(entry.get("filter") or {})):
                return False

        # "That creature can't attack during its controller's next turn."
        # (Wall of Dust's block trigger.) The stamp names a seat and that
        # seat's next turn ordinal, written when the trigger resolved; the
        # restriction holds exactly while that turn is the current one, and a
        # later turn walks past it with nothing to sweep. On the permanent
        # rather than the game because the sentence restricts one creature,
        # and a creature that leaves and returns is a new object with no
        # stamp (CR 400.7).
        stamp = attacker.metadata.get("cant_attack_on_seat_turn")
        if (
            isinstance(stamp, dict)
            and stamp.get("seat") == self.active_player_index
            and stamp.get("seat_turn")
            == self.seat_turn_counts.get(self.active_player_index, 0)
        ):
            return False

        # Defender is asked of layer 6, not of the printed keyword list: a Clone
        # copying a Wall has the ability through layer 1 and a Primal Clay that
        # entered on its 1/6 Wall body has it through a layer-6 grant, and
        # neither prints the word. Both could attack while this read the card.
        # Animate Wall grants the exemption while attached
        # (auras.aura_restrictions).
        if self._has_keyword(attacker, "defender") and not self._ignores_defender(
            attacker
        ):
            return False

        # Island Sanctuary: defending player is protected from non-flying,
        # non-islandwalk attackers. Both keywords are asked through layer 6, so
        # islandwalk granted by a lord counts — reading the metadata flag and
        # the printed keyword list separately missed every other route to the
        # ability, which is the bug class tests/engine/test_layer_reads.py
        # guards.
        defending = self.players[defending_player_index]
        if defending.island_sanctuary_protected:
            if not (
                self._has_keyword(attacker, "flying")
                or self._has_keyword(attacker, "islandwalk")
            ):
                return False

        return True

    def _ignores_defender(self, attacker: Permanent) -> bool:
        """Whether *attacker* may attack "as though it didn't have defender".

        CR 609.4: an "as though" effect applies **only** to the stated effect —
        the creature still has defender for every other purpose, so this is a
        permission read here rather than a keyword the layers remove. Removing it
        would also change what a defender-narrowed filter matches
        (``subject_filters``), what layer 6 reports to the web payload, and what
        "creatures with defender" counts, none of which the card says.

        Two sources, both asked live. An attached Aura (Animate Wall) is asked of
        the Auras attached right now, and the permanent's own conditional static
        (Drowsing Tyrannodon) is asked of the board right now — the condition can
        change between layer recomputes, and declaring attackers is the read that
        matters. It is the exact twin of the ``cant_be_blocked`` conditional
        static the declare blockers step asks at block time.
        """
        if aura_restriction_active(attacker, "ignores_defender"):
            return True
        # The third source: a resolving ability that granted the permission for
        # this turn (Wall of Wonder). A flag rather than a keyword removal for
        # the reason above, and swept by the cleanup step.
        if attacker.metadata.get(ATTACK_AS_THOUGH_NO_DEFENDER):
            return True
        seat = self.controller_index_of(attacker)
        if seat is None:
            return False
        return any(
            i.kind == "conditional_static"
            and i.payload.get("ignores_defender")
            and conditional_static_holds(
                self, seat, attacker, i.payload.get("condition") or {}
            )
            for i in compile_card_oracle(attacker.effective_card).instructions
        )

    def _must_attack_if_able(self, attacker: Permanent) -> bool:
        if attacker.metadata.get("must_attack_until_eot"):
            return True
        # An Aura can impose the requirement too (Furor of the Bitten). Asked of
        # the attached Auras rather than stamped on the creature, so the
        # requirement ends when the Aura leaves and nothing has to undo it —
        # the model every other Aura restriction already follows.
        if aura_restriction_active(attacker, "must_attack_each_combat"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        return any(i.kind == "must_attack_each_combat" for i in program.instructions)

    def attack_declaration_refusal(
        self, declared_attackers: list[Permanent]
    ) -> "tuple[Permanent, str] | None":
        """Which declared attacker's restriction this **set** disobeys, and why.

        CR 508.1c asks its restrictions of the declaration as a whole — "if any
        restrictions are being disobeyed, the declaration is illegal" — so
        neither of these can live in `can_attack`, a per-creature predicate with
        no way to say "and nobody else" (Errantry's "can only attack alone") or
        "and at least two more of you" (Orcish Conscripts).

        **Public, and returning the offending permanent, because the AI asks it
        too.** `ai_policy.choose_attackers` builds its set out of
        `legal_attackers`, which is that per-creature predicate — so it happily
        proposed a set the declaration then refused *whole*, and a Conscripts
        beside one Bear grounded the Bear as well. A second reading of the rule
        inside the AI would drift from this one; the permanent is what lets the
        AI drop the creature it named instead.

        Asked of the collected `Permanent` objects rather than of indices: an
        index is unstable, and both callers have the objects already.
        """
        if len(declared_attackers) > 1:
            for lone in declared_attackers:
                if self._can_only_attack_alone(lone):
                    return lone, f"{lone.card.name} can only attack alone"
        for attacker in declared_attackers:
            needed = declaration_company_required(attacker, "attack")
            if needed is not None and len(declared_attackers) - 1 < needed:
                return attacker, (
                    f"{attacker.card.name} needs at least {needed} other "
                    "attacking creature(s)"
                )
        return None

    def _can_only_attack_alone(self, attacker: Permanent) -> bool:
        """CR 506.5 — whether *attacker* may attack only as the sole attacker.

        Printed on the creature (a `combat_restrictions` row) or granted by an
        Aura (Errantry), and read through the same two seams every other combat
        restriction here goes through, so neither spelling is enforced without
        the other.
        """
        if aura_restriction_active(attacker, "can_only_attack_alone"):
            return True
        program = compile_card_oracle(attacker.effective_card)
        return any(i.kind == "can_only_attack_alone" for i in program.instructions)

    def _fire_attack_triggers(self, controller_index: int) -> None:
        """Put "whenever one or more creatures you control attack" triggers on the stack.

        Covers Raging River and similar enchantments whose ability triggers once
        when the controller declares one or more attackers (CR 508.2/508.4, 603.3).
        Per CR 508.2 these abilities are placed on the stack as the declare attackers
        step's turn-based action completes — they don't resolve immediately; the
        active player then receives priority (the caller opens that window) and the
        triggers resolve as players pass priority with the stack non-empty.
        """
        from ..game_types import StackItem

        controller = self.players[controller_index]
        # CR 802.3a: a trigger not tied to a specific defending player applies once
        # across the whole attacking group; use the first attacker's defender as a
        # deterministic representative target (the only defender in the common
        # single-defender/2-player case).
        target_index = next(iter(self.combat_attackers.values()), controller_index)
        for permanent in list(controller.battlefield):
            for trig in matching_triggers(
                permanent.effective_card, condition_kinds={"one_or_more_attack"}
            ):
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        target_player_index=target_index,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")

    def _fire_creature_attacks_triggers(self, controller_index: int, attacker_indices: list[int]) -> None:
        """Put each attacker's own "whenever this creature attacks" triggers on
        the stack (e.g. Mijae Djinn's coin flip) — one per attacking creature
        that has the trigger, unlike _fire_attack_triggers' once-per-declaration
        team-wide version."""
        from ..auras import attached_subject_triggers
        from ..game_types import StackItem

        controller = self.players[controller_index]
        for idx in attacker_indices:
            if not (0 <= idx < len(controller.battlefield)):
                continue
            permanent = controller.battlefield[idx]
            # "attacks or blocks" (Elder Gargaroth) is the same per-creature
            # firing on each half of its union — this is the attack half, the
            # blocker-side twin in declare_blockers_step is the other.
            for trig in matching_triggers(
                permanent.effective_card,
                condition_kinds={"creature_attacks", "creature_attacks_or_blocks"},
            ):
                # "Whenever this creature attacks AND ISN'T BLOCKED" (Merchant
                # Ship, Pirate Ship riders) can't be evaluated until blockers
                # exist — deferred to _fire_unblocked_attack_triggers at the
                # combat damage step.
                if "isn't blocked" in (trig.source_line or "").lower():
                    continue
                self._stack_push(
                    StackItem(
                        card=permanent.card,
                        caster_index=controller_index,
                        # The attacker's own controller/index, so the coin-flip
                        # handler can remove IT from combat without re-deriving
                        # who owns it.
                        target_player_index=controller_index,
                        target_permanent_index=idx,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=permanent,
                        ability_text=trig.source_line,
                        # "…**defending player** may draw a card" (Sibilant
                        # Spirit). CR 506.2's seat, and it is *this attacker's*
                        # — a multi-defender combat (CR 802) has one per
                        # attacking creature, so it is read off the declaration
                        # map rather than from a single scalar. Frozen now
                        # (CR 603.10) because the trigger resolves after the
                        # step, and the same key the delayed attack triggers
                        # and the resolution-time picker already read.
                        trigger_context={
                            "trigger_defending_player_index":
                                self.combat_attackers.get(idx),
                        },
                    )
                )
                self.log.append(f"{permanent.card.name} triggered on attack (added to stack)")
            # "Whenever **enchanted creature** attacks or blocks" (Imprison).
            # The same event, watched by something attached to the attacker
            # rather than by the attacker itself — invisible to the scan above,
            # because an Aura's ability is the Aura's and not a granted ability
            # of its host (CR 113.7a). The attack half; the blocker-side twin
            # is in declare_blockers_step.
            for seat, attachment, trig in attached_subject_triggers(
                self, permanent, {"creature_attacks_or_blocks"}, "combatant_attached",
            ):
                self._stack_push(
                    StackItem(
                        card=attachment.card,
                        # CR 603.3a: the ability's controller is the
                        # attachment's controller, which is who "you may pay
                        # {1}" is offered to — never the attacking creature's.
                        caster_index=seat,
                        target_player_index=seat,
                        target_permanent_index=None,
                        x_value=None,
                        ability_instruction=trig.instruction,
                        ability_effect_kind=trig.effect_kind,
                        source_permanent=attachment,
                        ability_text=trig.source_line,
                    )
                )
                self.log.append(
                    f"{attachment.card.name} triggered on "
                    f"{permanent.card.name}'s attack (added to stack)"
                )

    def _announce_attack_declaration(
        self, controller_index: int, declared: list[Permanent]
    ) -> None:
        """The declaration itself (CR 508.1), once, carrying *who* attacked.

        The fourth attack-trigger shape and the only one that is about the
        *group*: "whenever you attack with two or more creatures with flying"
        (Tide Skimmer) and "whenever this creature and at least two other
        creatures attack" (Makeshift Battalion) both ask how many attackers
        there were, which no per-creature announcement can answer — the other
        three fire once per declaration for one card's ability, once per
        attacker's own ability, and once per attacker to the whole board.

        The attackers ride the payload rather than being re-derived from
        ``combat_attackers`` at the filter: the trigger is about the declaration
        as it was announced, and a later removal renumbers that map.
        """
        emit(
            self, "attackers_declared",
            seat=controller_index, attackers=list(declared),
            # Who attacked, under the key every "that player" in this engine
            # reads (`lowering/_events.EVENT_SUBJECT_PLAYER`). "Whenever a
            # player attacks …, destroy all creatures **that player** controls"
            # (Total War) is the seat the *event* picked, and the seat-narrowed
            # readings of this same announcement have always had it implicitly
            # in `seat` — spelled under the shared name so the effect half can
            # find it without knowing which fire site it came from.
            event_subject_player=controller_index,
        )
        # "Whenever an **opponent** attacks with creatures" (Mangara). The same
        # declaration asked from the other side, so it is announced here rather
        # than given a site of its own — and it carries, per seat, how many of
        # the batch are aimed at that seat, because CR 603.4's intervening-if
        # asks about the declaration and a recount at resolution would see a
        # combat that had moved on.
        aimed: dict[int, int] = {}
        for attacker in declared:
            defender = self._defender_seat_of(attacker)
            if defender is not None:
                aimed[defender] = aimed.get(defender, 0) + 1
        emit(
            self, "opponent_attackers_declared",
            seat=controller_index, attackers=list(declared), aimed_by_seat=aimed,
        )

    def _defender_seat_of(self, attacker: "Permanent") -> int | None:
        """Which seat *attacker* is attacking — the player, or the controller of
        the planeswalker it is aimed at.

        Both count as attacking that player for Mangara's purposes, which is
        what its "you and/or planeswalkers you control" says, so one lookup
        answers both halves.
        """
        index = next(
            (i for i, perm in enumerate(self.controlled_by(
                self.controller_index_of(attacker) or 0
            )) if perm is attacker),
            None,
        )
        if index is None:
            return None
        walker_id = self.combat_attacked_planeswalkers.get(index)
        if walker_id is not None:
            walker = self.permanent_by_id(walker_id)
            return self.controller_index_of(walker) if walker is not None else None
        return self.combat_attackers.get(index)

    def _fire_matching_creature_attacks_triggers(
        self, declared: list[Permanent]
    ) -> None:
        """"Whenever a creature you control with deathtouch attacks …" (Hooded
        Blightfang) — once for each declared attacker that answers the trigger's
        own subject filter.

        The third of the three attack-trigger shapes, and the only one whose
        source need not be attacking: ``_fire_attack_triggers`` fires once for
        the whole declaration, ``_fire_creature_attacks_triggers`` fires an
        attacker's own ability, and this one announces *each attacker* to the
        whole board. That is what the event bus is for — the announcement is
        game-wide and the narrowing is the trigger's own noun phrase, so no
        card is named here.
        """
        for attacker in declared:
            emit(self, "matching_creature_attacks", subject=attacker)

    # ------------------------------------------------------------------
    # Banding declaration (CR 702.22)
    # ------------------------------------------------------------------

    def _creature_has_banding(self, permanent: Permanent) -> bool:
        """Whether a creature currently has banding (printed or granted)."""
        if permanent.has_keyword("banding"):
            return True
        return self._has_keyword(permanent, "banding")

    def _creature_band_qualities(self, permanent: Permanent) -> tuple[str, ...]:
        """The "bands with other [quality]" abilities *permanent* currently has.

        Through the layer system like plain banding above, because a band can be
        granted (Legends' five lands grant one to a colour of legendary
        creatures) and taken away (Shelkin Brownie) — so the printed line is not
        the answer at either end of a combat.
        """
        from ..banding import abilities_of, computed_abilities_of

        return abilities_of(computed_abilities_of(permanent))

    def _bands_with_other_band(self, creatures: list[Permanent]) -> bool:
        """CR 702.22c's second form: may *creatures* attack as one band?"""
        from ..banding import bands_with_other_band

        return bands_with_other_band(self, creatures)

    def _validate_attacking_bands(
        self,
        bands: list[list[int]] | None,
        attacker_indices: list[int],
        controller: PlayerState,
    ) -> tuple[list[list[int]], str | None]:
        """Validate declared attacking bands (CR 702.22c). Returns (bands, error).

        A band is one or more attacking creatures with banding plus up to one
        attacking creature without banding; each creature may join only one band.
        """
        if not bands:
            return [], None
        attacker_set = set(attacker_indices)
        seen: set[int] = set()
        validated: list[list[int]] = []
        for group in bands:
            members = sorted(set(group))
            if len(members) < 2:
                return [], "a band must contain at least two creatures"
            banding_count = 0
            nonbanding_count = 0
            member_perms: list[Permanent] = []
            for idx in members:
                if idx not in attacker_set:
                    return [], "every band member must be a declared attacker"
                if idx in seen:
                    return [], "a creature may belong to only one band"
                seen.add(idx)
                member = controller.battlefield[idx]
                member_perms.append(member)
                if self._creature_has_banding(member):
                    banding_count += 1
                else:
                    nonbanding_count += 1
            # CR 702.22c has **two** band forms, and the second is not a
            # relaxation of the first. The plain form is "one or more attacking
            # creatures with banding and up to one attacking creature without
            # banding"; the "bands with other" form is "one or more attacking
            # [quality] creatures with 'bands with other [quality]' and any
            # number of other [quality] creatures" — no cap on the members, and
            # in exchange every member must be a [quality] creature. Checked as
            # an alternative rather than by loosening the counts, because
            # loosening them would let a legendary band recruit a Grizzly Bear.
            #
            # Note what the plain form's parenthetical says and what this does
            # not do: a creature with "bands with other" and no banding is a
            # creature *without* banding for the plain form's count, which is
            # why `_creature_has_banding` stays a question about the word.
            plain = banding_count >= 1 and nonbanding_count <= 1
            if not plain and not self._bands_with_other_band(member_perms):
                if banding_count < 1:
                    return [], "a band needs at least one creature with banding"
                return [], "a band may include at most one creature without banding"
            validated.append(members)
        return validated, None
