"""What a cast announces about the spell itself (CR 601.2a–c): where it is
cast from, its modes, and each mode's targets.

``_spell_source`` finds the card in the zone it is cast from and the
permission that lets it be (CR 601.3). The mode methods carry CR 601.2b's
choice of modes, and CR 700.2e's when an opponent makes it
(``_arm_opponent_mode_choice``, ``arm_modal_mode_targets``);
``_mode_announcements`` is every announcement a cast makes, one per chosen
mode, and ``_mode_target_refusal`` asks CR 601.2c's target gates of each.

Split out of ``casting.py`` at the 2,000-line cap, and composed onto ``Game``
with the other parts of ``SpellCastingMixin``; the steps of
``_cast_onto_stack`` here are moved out of it whole and called from it in its
order.
"""

from __future__ import annotations

from ...cast_permissions import permission_for
from ...classifier import classify_card
from ...faces import holds_spell_named, spell_named
from ...game_types import SimulationResult
from ...hand_locks import hand_lock_reason, playable_hand_index
from ...oracle import compile_card_oracle


def _mode_announcements(
    chosen_modes, mode_index, target_player_index, target_permanent_index,
    target_permanent_ids, target_stack_item,
) -> list[tuple]:
    """``(mode_index, seat, slot, ids, stack_item)`` for every announcement a
    cast makes (CR 601.2b–c).

    One row for an ordinary spell and for the single-mode ``mode_index=``
    spelling, read off the cast's own target fields. One row **per chosen
    mode** for a "choose one or more" cast (``mode_choices``), read off the
    mode that named them: two modes of Sublime Epiphany may name two objects
    on two boards, and the cast's own fields name neither. A mode's targets
    travel as a slot beside its seat, never as ids — ``ChosenMode`` is stamped
    with ids only as it reaches the stack.
    """
    if chosen_modes:
        return [
            (
                mode.index, mode.target_player_index,
                mode.target_permanent_index, None, mode.target_stack_item,
            )
            for mode in chosen_modes
        ]
    return [(
        mode_index, target_player_index, target_permanent_index,
        target_permanent_ids, target_stack_item,
    )]


class CastAnnouncementMixin:
    def _spell_source(
        self, *, alternative_cost, card_name, caster, caster_index, from_zone,
    ):
        """Where the spell is cast from, and under what (CR 601.2a, CR 601.3).

        A hand is the rule — the first copy that may be played (Firestorm
        Phoenix's held copy is not); a command zone is CR 903.8's, for the
        caster's own commander; a graveyard, an exile or a library top needs an
        effect, asked of the permission seam across every seat's pile (Grinning
        Totem leaves the card in the searched player's exile), the permission
        an announced alternative cost requires looked for first (CR 118.9b).

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or ``(hand_index, permission, source_seat,
        source_zone)``.
        """
        # Casting from the hand is a rule; casting from anywhere else is an
        # effect (CR 601.3), asked of the permission seam. The lookup prefers a
        # covered occurrence so a duplicate without permission cannot shadow
        # the copy that has it.
        permission = None
        # Whose pile ``source_zone`` turns out to be. The caster's on every
        # path but one — Grinning Totem leaves the card in the *searched*
        # player's exile — and the departure below needs the seat, not just the
        # list, because leaving exile goes through a seam that takes one.
        source_seat = caster_index
        if from_zone == "hand":
            source_zone = caster.hand
            # A card in hand can be *held* and not playable — Firestorm Phoenix
            # returns itself "revealed in their hand and can't play it" until
            # its owner's next turn. The lookup asks for the first copy that may
            # be played rather than the first copy at all, the same preference
            # the permission lookup below makes and for the same reason: two
            # copies of one card are indistinguishable, so a restriction on one
            # of them is a restriction on how *many* may be played.
            hand_index = playable_hand_index(self, caster_index, card_name)
            if hand_index is None:
                if not any(holds_spell_named(card, card_name) for card in caster.hand):
                    raise ValueError(f"Card not in hand: {card_name}")
                denial = hand_lock_reason(self, caster_index, card_name) or (
                    f"{card_name} can't be played"
                )
                self.log.append(denial)
                return SimulationResult(card_name, False, None, denial)
        elif from_zone == "command":
            # CR 903.8 is a *rule*, not an effect: "a player may cast a
            # commander they own from the command zone". So it needs no
            # CastPermission — the permission seam is CR 601.3's "an effect
            # allows it", and asking it here would refuse the one cast the rules
            # themselves grant. What it does need is the ownership test, which
            # is the whole of the rule's restriction.
            source_zone = caster.command_zone
            hand_index = next(
                (
                    i for i, card in enumerate(source_zone)
                    if holds_spell_named(card, card_name)
                ),
                None,
            )
            if hand_index is None:
                raise ValueError(f"Card not in command zone: {card_name}")
            if not self.may_cast_from_command_zone(caster_index, source_zone[hand_index]):
                details = (
                    f"{card_name} is not {caster.name}'s commander and cannot be cast "
                    f"from the command zone (CR 903.8)"
                )
                self.log.append(details)
                return SimulationResult(
                    card_name, False,
                    classify_card(source_zone[hand_index]).effect_kind, details,
                )
        else:
            if from_zone not in ("graveyard", "exile", "library"):
                raise ValueError(f"cannot cast from {from_zone!r}")
            # "You may cast Goblin spells from the top of your library."
            # (Conspicuous Snoop, since M21.) The permission seam has answered
            # for the library since that card landed and this gate refused it,
            # so the grant existed and nothing could ever spend it — the loud
            # half of the same hole ``playable_from_zones`` had on the quiet
            # side. The loop below needs no library branch of its own: every
            # library permission is scoped to one card by identity
            # (``library_top.top_castable`` compares ``library[0]``), so only
            # the top card can match and the seat scan finds nothing in anybody
            # else's deck.
            # Whose copy of the zone. The caster's own on every grant but one:
            # "Search target opponent's library for a card and exile it. … you
            # may play that card" (Grinning Totem) leaves the card in the
            # *searched* player's exile (CR 400.3) and gives the permission to
            # the searcher, so the pile and the player come apart. Own pile
            # first, so a card the caster could already play is still found in
            # the order it was found before.
            seats = [caster_index] + [
                seat for seat in range(len(self.players)) if seat != caster_index
            ]
            source_zone = getattr(caster, from_zone)
            hand_index = None
            # **Which permission**, when a card is covered by more than one
            # (CR 601.2b). A flashback card under Yawgmoth's Will may be cast
            # for its mana cost under the Will or for its flashback cost under
            # its own keyword, and those are two casts: the caster who
            # announces an alternative cost is asking for the permission that
            # *requires* one (CR 118.9b, `CastPermission.cost`), so that kind
            # is looked for first and across every pile. Finding none, the
            # announcement is about the card's own printed alternative cost
            # (Force of Will out of an opened graveyard) and the ordinary
            # lookup stands. A caster who announces nothing gets the first
            # permission of either kind, which for a card only its own
            # flashback covers is the flashback — there is no other way to
            # cast it, so there is nothing to choose.
            for wanted in ((True, None) if alternative_cost else (None,)):
                for seat in seats:
                    pile = getattr(self.players[seat], from_zone)
                    for i, candidate in enumerate(pile):
                        if not holds_spell_named(candidate, card_name):
                            continue
                        if hand_index is None and seat == caster_index:
                            # The fallback that names the refusal below, and
                            # only out of the caster's own pile: "no effect
                            # allows playing that card from *your* exile" is
                            # what the player asked about.
                            hand_index = i
                        grant = permission_for(
                            self, caster_index, candidate, from_zone,
                            as_land=candidate.primary_type == "land",
                            # Judged as the spell it is being cast as — the
                            # named half of a split card (CR 709.3a).
                            spell=spell_named(candidate, card_name),
                            costed=wanted,
                        )
                        if grant is not None and grant.zone_seat == seat:
                            source_zone, hand_index, permission = pile, i, grant
                            source_seat = seat
                            break
                    if permission is not None:
                        break
                if permission is not None:
                    break
            if hand_index is None:
                raise ValueError(f"Card not in {from_zone}: {card_name}")
            if permission is None:
                details = (
                    f"no effect allows playing {card_name} from "
                    f"{caster.name}'s {from_zone} (CR 601.3)"
                )
                self.log.append(details)
                return SimulationResult(
                    card_name, False,
                    classify_card(source_zone[hand_index]).effect_kind, details,
                )
        return hand_index, permission, source_seat, source_zone

    def _resolve_chosen_modes(
        self, card, mode_choices: list[dict] | None
    ) -> tuple[tuple, str | None]:
        """The ``ChosenMode`` list for this cast, or a refusal naming the fault.

        CR 601.2b: the modes are chosen as the spell is cast, and how many is
        what the head printed. Three things are checked, because each is a way a
        caller could otherwise get a spell the card does not describe:

        * a card whose head is not "one **or more**" gets at most one mode —
          otherwise any modal spell would perform every bullet;
        * every index names a real mode of *this* card;
        * no mode is chosen twice (CR 700.2d: the same mode may be chosen again
          only if the card says so, and none in this pool does).

        The list comes back in **printed** order whatever order it arrived in,
        because that is the order the modes resolve in (CR 608.2c) — sorting
        once here is what lets the resolution loop be a loop rather than a sort.
        """
        from ...game_types import ChosenMode

        program = compile_card_oracle(card)
        # "**An opponent** chooses one —" (CR 700.2e). The choice is made at the
        # same moment (CR 601.2b) but by somebody else, so an announcement that
        # names a mode is not a legal announcement — it is the caster taking the
        # half of the card that suits them, which on all three cards printing
        # this head is the opposite of what the card does. Refused rather than
        # ignored: a dropped mode choice is a client quietly getting a different
        # spell from the one it asked for.
        if program.mode_chooser is not None:
            if mode_choices:
                return (), (
                    f"{card.name}: an opponent chooses this spell's mode"
                )
            return (), None
        if not mode_choices:
            return (), None
        if not program.modes:
            return (), f"{card.name} has no modes to choose"
        if len(mode_choices) > 1 and not program.modes_at_least:
            return (), f"{card.name} chooses one mode, not {len(mode_choices)}"
        seen: set[int] = set()
        chosen: list[ChosenMode] = []
        for entry in mode_choices:
            index = entry.get("index")
            if not isinstance(index, int) or not 0 <= index < len(program.modes):
                return (), f"{card.name}: no mode {index!r}"
            if index in seen:
                return (), f"{card.name}: mode {index} was chosen twice"
            seen.add(index)
            stack_index = entry.get("target_stack_index")
            stack_item = (
                self.stack[stack_index]
                if isinstance(stack_index, int) and 0 <= stack_index < len(self.stack)
                else None
            )
            chosen.append(ChosenMode(
                index=index,
                target_player_index=entry.get("target_player_index"),
                target_permanent_index=entry.get("target_permanent_index"),
                target_stack_item=stack_item,
            ))
        chosen.sort(key=lambda mode: mode.index)
        return tuple(chosen), None

    def _mode_target_refusal(
        self, *, card, caster_index, chosen_modes, classification,
        divided_targets, from_zone, mode_index, no_target_answers_x,
        optional_paid, role_seats, target_permanent_ids,
        target_permanent_index, target_player_index, target_stack_item,
        x_value,
    ):
        """CR 601.2c, asked once per announced mode (CR 601.2b chooses the
        modes first): the per-kind target gate, whether any legal target exists
        at all, the target the caster named, a target on the stack, and a stack
        target named for an announcement that has none there. Nothing has been
        spent.

        A step of ``_cast_onto_stack``, moved out of it whole and called from
        it in its place: "above" and "below" in its comments are places in the
        cast as that method runs it.

        Returns the refusal, or None.
        """
        # **Once per announced mode** (CR 601.2b chooses the modes, then
        # CR 601.2c chooses each mode's targets). An ordinary spell and the
        # `mode_index=` spelling make one announcement, on the cast's own
        # target fields; a "choose one or more" cast (`mode_choices`) makes one
        # per chosen mode, each carrying the targets it named — which were
        # checked by nobody, because every gate below was handed the cast's
        # own (empty) fields beside the first chosen mode's index.
        for (
            announced_mode, mode_seat, mode_slot, mode_ids, mode_stack_item,
        ) in _mode_announcements(
            chosen_modes, mode_index, target_player_index,
            target_permanent_index, target_permanent_ids, target_stack_item,
        ):
            target_ok, target_reason = self._validate_cast_targets(
                card, caster_index, mode_seat, mode_slot, mode_stack_item,
                mode_index=announced_mode, x_value=x_value,
                target_permanent_ids=mode_ids,
                # CR 601.2b is answered above; CR 702.33g makes the targets this
                # gate counts depend on it.
                optional_cost_payments=optional_paid,
                # The cast's own announcement only: a "choose one or more"
                # mode names its targets on the mode, which has one seat.
                target_role_seats=None if chosen_modes else role_seats,
            )
            if not target_ok:
                self.log.append(target_reason)
                return SimulationResult(card.name, False, classification.effect_kind, target_reason)

            # CR 601.2c's other half, asked before what was *named*: a spell that
            # must announce a target cannot be cast while no legal target exists.
            # The arms above ask it of the kinds they name; this asks it of every
            # spell, through the list the picker is handed — so "Destroy target
            # artifact or enchantment. Draw two cards." on an empty board is an
            # illegal announcement rather than a two-mana cantrip. Nothing has been
            # spent yet.
            #
            # **And of every mode**, by the mode announced: Chaos Charm's "deals
            # 1 damage to target creature" was castable at an empty board, and
            # Treva's Charm's "exile target attacking creature" outside combat.
            unaimed = self.no_legal_cast_target_refusal(
                caster_index, card,
                optional_cost_payments=optional_paid, x_value=x_value,
                mode_index=announced_mode,
                # A spell cast out of a graveyard is not a card in it by the
                # time targets are chosen (CR 601.2a), so it cannot be the
                # legal target that lets itself be cast.
                from_zone=from_zone,
            )
            if unaimed is None and no_target_answers_x:
                # …and the one shape of "nothing to name" that list cannot
                # show: entries, and an announced X none of them answers
                # ("destroy target artifact with mana value X", Detonate, cast
                # bare for an X no artifact has — `bare_announcements.
                # default_cast_target`). It was accepted, paid for and
                # resolved onto nothing.
                unaimed = f"no valid target for {card.name}"
            if unaimed is not None and mode_stack_item is None:
                self.log.append(unaimed)
                return SimulationResult(card.name, False, classification.effect_kind, unaimed)

            # CR 601.2c for the target the caller *named*, beside the per-kind arms
            # above rather than inside them: a spell whose primary instruction is a
            # `sequence` wrapper reaches no arm at all, so "Destroy target artifact.
            # You gain life equal to its mana value" could be cast on a Grizzly
            # Bears — the destroy then found nothing and the life was gained anyway.
            # Still before any mana leaves the pool.
            named_refusal = self.cast_target_refusal(
                caster_index, card,
                target_player_index=mode_seat,
                target_permanent_index=mode_slot,
                target_permanent_ids=mode_ids,
                from_zone=from_zone,
                # CR 601.2b is announced above; CR 601.2c's target count follows
                # from it for a spell that prints "for each additional <cost> you
                # paid, … another target …". The gate is the only reader that can
                # see both announcements at once.
                optional_cost_payments=optional_paid,
                mode_index=announced_mode,
                # CR 601.2d's list, whose every entry is a target too — and it
                # is the cast's own, never one mode's: a "choose one or more"
                # mode names its targets on the mode (`_mode_announcements`).
                divided_targets=None if chosen_modes else divided_targets,
                # …and the two things that say whether a cast naming no player
                # named *nothing* (a spell on the stack is a target) and whether
                # it owed a target at all ("X target …" at an announced X).
                target_stack_item=mode_stack_item,
                x_value=x_value,
            )
            if named_refusal is not None:
                self.log.append(named_refusal)
                return SimulationResult(card.name, False, classification.effect_kind, named_refusal)
            # …and the same rule for a target **on the stack**, which the gate
            # above does not read (its slots are battlefield slots). One call
            # where Invasion's first wave left two: see
            # `legality.cast_stack_target_refusal`. Without it "counter target
            # creature spell" was announceable at any spell, paid for, and then
            # declined by its own handler — and a bare cast was accepted with
            # nothing on the stack its phrase admits.
            stack_refusal = self.cast_stack_target_refusal(
                caster_index, card, mode_stack_item, from_zone=from_zone,
                mode_index=announced_mode,
            )
            if stack_refusal is not None:
                self.log.append(stack_refusal)
                return SimulationResult(card.name, False, classification.effect_kind, stack_refusal)
            # …and the rule's other side: a stack object named for an
            # announcement that has no target there (a Lightning Bolt, a Terror,
            # a Wrath of God), or beside a permanent for "target spell **or**
            # permanent". It was accepted, recorded and ignored.
            stray_refusal = self.stray_stack_target_refusal(
                caster_index, card, mode_stack_item, from_zone=from_zone,
                mode_index=announced_mode,
                optional_cost_payments=optional_paid,
                names_a_permanent=bool(
                    [pid for pid in (mode_ids or ()) if isinstance(pid, int)]
                    or mode_slot is not None
                ),
            )
            if stray_refusal is not None:
                self.log.append(stray_refusal)
                return SimulationResult(card.name, False, classification.effect_kind, stray_refusal)

    def _arm_opponent_mode_choice(self, caster_index: int, card, spell_item) -> None:
        """CR 700.2e: hand the mode choice to a player other than the caster.

        Nothing is armed for an ordinary modal spell — the caster already named
        its mode as part of the announcement — so this is a no-op for every card
        but the three that print the head.

        **Which opponent** is the caster's choice when there is more than one
        (CR 700.2e's second sentence), and this takes the first living one
        instead of asking. That is a decision the engine does not model yet and
        it is recorded as such rather than hidden: in a duel, the rule's
        "if there is more than one" clause never applies and the seat is the
        only opponent there is.
        """
        program = compile_card_oracle(card)
        if program.mode_chooser is None or not program.modes:
            return
        chooser = next(
            (
                seat for seat in self.opponents_of(caster_index)
                if not self.players[seat].lost
            ),
            None,
        )
        if chooser is None:
            # CR 700.2e names a player who has to exist; with none left the
            # spell has nobody to ask and the first printed mode stands, which
            # is the same stated policy the non-interactive default takes.
            from ...game_types import ChosenMode

            spell_item.chosen_mode_index = 0
            spell_item.chosen_modes = (ChosenMode(index=0),)
            return
        self.arm_pending_choice(
            "opponent_mode_choice", chooser,
            card_name=card.name,
            labels=[mode.label for mode in program.modes],
            _item=spell_item,
        )
        self.log.append(
            f"{self.players[chooser].name} chooses a mode for {card.name}"
        )

    def arm_modal_mode_targets(self, spell_item, chooser_seat: int) -> None:
        """CR 601.2c for a mode somebody else chose (CR 700.2e).

        The rules order is modes (601.2b) then targets (601.2c), and for these
        spells the two belong to different players — so the caster cannot name a
        target while casting: they do not yet know which mode they are naming it
        for, and a mode the opponent then declines to pick would have published
        the caster's intentions for nothing.

        So the targets are asked for *after* the answer, and the prompt is armed
        by that answer. The spell is on the stack by then, which is a departure
        from the rules' internal order and not from anything observable:
        `opponent_mode_choice` and this prompt both block every seat, so no
        player has had priority between CR 601.2i and this — the whole
        announcement is still one uninterruptible moment.

        The picker is the one `legality._enumerate_targets` builds for every
        other spell, with the chooser's seat supplied beside the
        ``that_player_only`` flag the mode's own noun phrase produced ("up to
        two target creatures **that player** controls"). Nothing else can supply
        it: the seat came into existence when the mode was chosen.

        A mode that targets nothing arms nothing, which is every mode of every
        other card that prints this head.
        """
        from ...targeting import _from_instructions

        program = compile_card_oracle(spell_item.card)
        index = spell_item.chosen_mode_index
        if index is None or not 0 <= index < len(program.modes):
            return
        instruction = program.modes[index].instruction
        if instruction is None:
            return
        spec = _from_instructions((instruction,))
        if spec is None:
            return
        if spec.get("that_player_only"):
            spec = {**spec, "that_player_index": chooser_seat}
        candidates = self._enumerate_targets(
            spell_item.caster_index, spell_item.card, spec, for_cast=True,
        )
        offered = []
        for candidate in candidates:
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
            })
        if not offered:
            # CR 601.2c names as many targets as the spell requires and no more.
            # "**Up to** two" requires none, so a board with nothing to destroy
            # is a legal announcement and not a refusal — the mode simply
            # destroys nothing. A mode with a *mandatory* target and no legal
            # one could not have been chosen at all (CR 700.2a), which is a
            # gate on the choice rather than on this prompt; no card in the pool
            # prints one, and the refusal it would need is named in ROADMAP.md.
            self.log.append(
                f"{spell_item.card.name}: the chosen mode has no legal target"
            )
            return
        self.arm_pending_choice(
            "modal_mode_targets", spell_item.caster_index,
            card_name=spell_item.card.name,
            mode_label=program.modes[index].label,
            targets=offered,
            max_targets=int(spec.get("max_targets") or 1),
            _item=spell_item,
        )
