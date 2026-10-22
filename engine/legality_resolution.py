"""CR 608.2b: as an object resolves, are the targets it chose still legal?

The other end of the announcement gates. Those ask "may this be announced?"
before a cost is paid; this asks "are the targets it announced still legal?"
as it begins to resolve — and if **every** target is illegal, the object
leaves the stack unresolved, above the instructions rather than inside each
handler (:meth:`ResolutionTargetsMixin.illegal_targets_refusal`). In an object
that still resolves, each illegal slot is blanked before any instruction runs
(:meth:`ResolutionTargetsMixin.blank_illegal_resolution_targets`), and a
target that is still legal is still the target wherever it now is
(:meth:`ResolutionTargetsMixin.resettle_announced_target_seats`).

The question is asked of every object whose targets somebody **chose**
(``legality.announced_by_a_choice``): a spell, an activated ability, and a
triggered ability whose target was chosen through its own picker — each
through the predicate that judged it at announcement, so a target that would
have been refused then is refused now.
"""

from __future__ import annotations

from .oracle import compile_card_oracle
from .resolution_overrides import resolves_with_illegal_targets
from .modal_triggers import modal_trigger_modes
from .targeting import (
    derive_cast_spec,
    derive_instruction_spec,
    role_is_stack,
    spec_offers_a_player,
    spec_roles,
)
from .target_roles import ROLES_TARGET_KIND
from .cost_pickers import spec_is_a_cost
from .legality import (
    _UNFIZZLABLE_TARGET_KINDS,
    _STACK_TARGET_KINDS,
    _resolution_rechecks_description,
    _ability_target_quantifiers,
    cast_target_obligation,
    announced_by_a_choice,
)


class ResolutionTargetsMixin:
    """CR 608.2b: whether a resolving object's targets are still legal.
    Composed onto ``Game`` beside ``LegalityMixin``."""

    def illegal_targets_refusal(self, item) -> str | None:
        """CR 608.2b: whether *item* must leave the stack without resolving.

        The other end of :meth:`activation_target_refusal`. That one asks
        "may this be announced?" (CR 601.2c/602.2b) before a cost is paid;
        this asks "are the targets it announced still legal?" at the moment it
        would resolve, and the rule is all-or-nothing — if **every** target,
        for every instance of the word "target", is illegal, the object does
        not resolve at all. Returns the reason, or None to resolve normally.

        **An object may print the exception on itself** ("This ability still
        resolves if its target becomes illegal", Gilded Drake). That is read
        first, through `engine/resolution_overrides.py`, because an exception
        applied only where the rule would have applied anyway is not one.

        This is not the same as a handler finding nothing to do. Each handler
        already re-checks its own target and skips its own effect, which is
        CR 608.2b's *last* sentence ("illegal targets won't be affected by
        parts of the effect for which they're illegal") — and with a per-handler
        answer, everything printed **after** that sentence still ran. Divine
        Offering ("Destroy target artifact. You gain life equal to its mana
        value") gained the life for destroying nothing, which is the rule's own
        worked example inverted (CR 608.2b's Sorin's Thirst: "Its controller
        doesn't gain any life"). The check has to be about the object, so it
        lives here and runs once, above the instructions.

        **Targets are read by identity, never by index.** The ids are what
        ``_stack_push_object`` stamped as the object was announced, for the
        reason it stamps them: a slot renumbers while the object waits, and an
        index that has come to mean a different permanent would answer this
        question about the wrong one.

        **"Legal" is the announcement's question, asked again.** A permanent
        target is legal when it is still on the battlefield, still targetable,
        *and still among what CR 601.2c would let the caster name now* —
        :meth:`_described_cast_target_slots`, the same enumeration
        :meth:`cast_target_refusal` checked it against. "Nonblack", "tapped",
        "you control", "attacking", "with flying", "with the greatest power"
        (Topple): every narrowing the picker enforced is re-enforced here
        without being re-read. The shapes that question does not cover are
        named in :func:`_resolution_rechecks_description`. A spell with several
        targets still resolves while **any** one is legal, and the illegal ones
        are blanked out of its announcement before any instruction runs
        (:meth:`blank_illegal_resolution_targets`, 608.2b's last sentence).
        This paragraph used to say each was "left alone by its handler's own
        resolver, which is what the census over the pool's multi-target spells
        found every one of them already doing" — true of a target that had
        *left* or stopped answering a description the handler re-read, and
        never asked of one that had merely become untargetable: 42 of the 48
        acted on a first target given shroud in response.

        **A spell that can target a player is answered too** — "any target", a
        divided one, a player-targeted one — through
        :meth:`_player_target_legality`. It was this gate's one deliberate
        exclusion, because a seat and a *chosen player* reach a stack item
        through the same ``target_player_index`` field; the announcement's own
        reader (``stack_targets``) tells them apart, and the gate asks it. What
        is still declined there is a mode an opponent chose (CR 700.2e).

        **A graveyard target is answered here too, in its answerable half.**
        The stamp ``_stack_push_object`` recorded (``GraveyardTarget``) is the
        chosen card's identity, and a stamp ``graveyard_index_of`` can no
        longer resolve — no copy of that card left in that pile — is a target
        the data model can establish is *gone*, so it counts as illegal like a
        departed permanent does. The **ambiguous** half stays out on purpose:
        two copies of one card in one graveyard are literally one
        ``CardDefinition``, so while any copy survives the stamp still
        resolves (clamped to the last surviving copy) and the target is legal
        — the engine cannot know *which* copy left, and a fizzle there would
        be a guess dressed as a rule.
        """
        card = item.card
        # "**This ability still resolves if its target becomes illegal.**"
        # (Gilded Drake.) CR 608.2b's exception, printed on the object itself,
        # so it is asked before every reason this engine has for declining the
        # question — an exception that only applies where the rule would have
        # applied anyway is not an exception.
        #
        # Read through `engine/resolution_overrides.py`, the table the grammar's
        # claim also goes through, so the sentence cannot be consumed by one and
        # unknown to the other. It is asked of the *ability's own line* where
        # there is one: the sentence is a rider on one ability, and a card whose
        # second ability targets without printing it must not inherit it.
        if resolves_with_illegal_targets(card, item.ability_text):
            return None
        if item.ability_instruction is not None:
            # **Spells only, and the reason is a different bug.** A spell's
            # targets are a player's choice, made at announcement through
            # ``cast_target_refusal`` against the enumerated legal ones, so an
            # id recorded on a spell is a choice that was legal when it was
            # made and this rule is exactly the question to ask of it later.
            #
            # A triggered ability's may be **stamped at its fire site**: the
            # object its event was about, threaded through the target fields
            # so the resolution can find it again, and the death sweep
            # enqueues a dies-trigger *while the dying permanent is still
            # listed* (``_destroy_swept_permanents``). An id like that is one
            # nobody chose — CR 603.3d would never have offered it — and
            # asking 608.2b of it counters an ability the engine mis-targeted
            # and reports that as a rules-correct fizzle, which buries the
            # targeting bug under a rule.
            #
            # **An activated ability has no such excuse**, and is asked. Its
            # targets were chosen by the player who activated it (CR 602.2b),
            # held to the picker's list before a cost was paid and recorded on
            # the item, and ``StackItem.activated`` is the positive mark that
            # tells the two apart — set by the three activation paths and by
            # nothing else.
            #
            # **Nor has a triggered ability whose target was chosen for it**
            # (CR 603.3d) rather than stamped: ``StackItem.targets_chosen``,
            # set where the choice is made out of the list
            # ``_trigger_target_candidates`` enumerates — the ``trigger_target``
            # prompt's answer and its default, an entry trigger's accepted
            # cast announcement, an upkeep prompt's accepted pick. The bound
            # is that distinction — chosen against stamped — and not
            # "triggered".
            #
            # Blazing Effigy's dies-trigger, the card this decline was first
            # written about, shows where the line falls. Its picker chooses
            # now (a stamp of its own source is read as a reference), and a
            # **person's** answer is a choice like any other. A seat with
            # nobody to ask takes its default *inside* the death sweep, off a
            # board that still lists the dying Effigy — which that default
            # can therefore be — so that one is not recorded as a choice
            # (``Game.departing``, ``_trigger_target_was_a_choice``) and is
            # not asked the rule.
            if announced_by_a_choice(item):
                return self.ability_targets_refusal(item)
            return None
        if card.primary_type not in ("instant", "sorcery"):
            # The same reason the announcement gate is instants and sorceries
            # only: a permanent spell's derived spec belongs to a triggered
            # ability that has not been put on the stack yet, so an id stamped
            # beside it says nothing about what *this* object targets. An Aura
            # whose enchant target has left is CR 608.2b too, and today it
            # enters attached to nothing and is binned by CR 704.5m one sweep
            # later — the same destination by a different rule, so moving it is
            # a decision for the round that can verify it.
            return None
        program = compile_card_oracle(card)
        legality: list[bool] = []
        for spec, holder, mode_index in self._resolving_announcements(item, program):
            verdict = self._announcement_target_legality(
                item, program, spec, holder, mode_index
            )
            if verdict is None:
                return None
            legality.extend(verdict)
        if not legality or any(legality):
            return None
        return f"{card.name} was removed from the stack: every target is illegal (608.2b)"

    def resolving_targets_all_legal(self) -> bool:
        """Whether **every** target the spell now resolving announced is still
        legal (CR 608.2b), by the per-target verdicts
        :meth:`illegal_targets_refusal` takes its all-or-nothing answer from.

        For the one kind of sentence that needs them one at a time: an effect
        that reads information **about** its targets. CR 608.2b's last line —
        "If part of the effect requires information about an illegal target, it
        fails to determine any such information" — means a comparison between
        two targets ("unless either one is a color the other isn't", Dead
        Ringers) has no answer once either is illegal, even though the other
        is still there to be read; a target given protection in response is
        the ordinary way to get there.

        True where the question is not asked: nothing resolving, an ability
        (declined for the reason ``illegal_targets_refusal`` gives), or an
        announcement that gate cannot judge. A reader then falls back on what
        it can see for itself, which is no worse than it had.
        """
        item = self.resolving_items[-1] if self.resolving_items else None
        if item is None or item.ability_instruction is not None:
            return True
        program = compile_card_oracle(item.card)
        for spec, holder, mode_index in self._resolving_announcements(item, program):
            verdict = self._announcement_target_legality(
                item, program, spec, holder, mode_index
            )
            if verdict is not None and not all(verdict):
                return False
        return True

    def _resolving_announcements(self, item, program) -> list[tuple]:
        """``(spec, holder, mode_index)`` for every announcement the spell
        *item* made: one for an ordinary spell, one **per chosen mode** for a
        modal one.

        *holder* is where that announcement's targets are recorded — the item
        itself, or the ``ChosenMode`` a "choose one or more" cast named them on
        (both carry ``target_permanent_id`` and ``target_stack_item`` under the
        same names, which is what lets one loop read either). *spec* is derived
        for that mode through ``targeting.derive_cast_spec(mode_index=)``, the
        derivation the announcement itself was gated by, so CR 601.2c and
        CR 608.2b stay one predicate for a Charm as they are for a Terror.

        A cast that named no mode resolves mode 0
        (``Game._select_executable_instruction``), and its spec is mode 0's by
        the same rule.

        …and under the **kicker the cast paid** (CR 702.33g), which is the
        other half of "the derivation the announcement was gated by": a target
        printed only in a kicked part is a target of a kicked spell alone. Read
        as the card's every arm, an unkicked Probe ("If this spell was kicked,
        target player discards two cards") had a player target at resolution
        that its own announcement never had — harmless while a player target
        was never judged, and a spell countered for a target it does not have
        the moment one is.
        """
        card = item.card
        paid = (getattr(item, "choices", None) or {}).get("additional_costs_paid") or {}
        if not program.modes:
            return [(
                derive_cast_spec(card, program, optional_cost_payments=paid),
                item, None,
            )]
        chosen = tuple(getattr(item, "chosen_modes", ()) or ())
        if chosen:
            return [
                (
                    derive_cast_spec(
                        card, program, mode_index=mode.index,
                        optional_cost_payments=paid,
                    ),
                    mode, mode.index,
                )
                for mode in chosen
            ]
        mode_index = getattr(item, "chosen_mode_index", None)
        return [(
            derive_cast_spec(
                card, program, mode_index=mode_index, optional_cost_payments=paid,
            ),
            item, mode_index,
        )]

    def _announcement_target_legality(
        self, item, program, spec, holder, mode_index, *,
        addresses: "list | None" = None,
    ) -> "list[bool] | None":
        """Whether each target one announcement of *item* recorded is still
        legal (CR 608.2b) — or None when "every target" cannot be answered for
        the whole object, and it must simply resolve.

        *addresses*, where a caller passes a list, is filled in step with the
        verdicts: for each one, ``(kind, channel, position, permanent_id)`` —
        where on *holder* that target is recorded — or None for a target no
        caller rewrites (a graveyard stamp, a stack object).
        :meth:`blank_illegal_resolution_targets` is the reader, and it is an
        out-parameter rather than a second walk so that "which targets are
        illegal" and "which slots to blank" cannot be two readings of one
        announcement.

        The body :meth:`illegal_targets_refusal` had, asked once per
        announcement so a modal spell is judged against **the mode that was
        chosen**. It was judged against mode 0's spec and then excluded from
        the description re-check altogether ("Active Volcano's 'return target
        Island' re-asked as 'target blue permanent' countered every Island
        bounce"); with the spec derived per mode the exclusion has nothing left
        to protect, and a Crosis's Charm whose target was turned black in
        response is countered by the rule instead of falling to its handler.
        """
        card = item.card
        if spec is None or spec.get("kind") in ("none", "modal", "hand_card"):
            # This announcement does not target at all — a creature spell whose
            # caller passed a stray index still gets an id stamped, a mode that
            # only draws names nobody — and countering the object on its
            # account would be inventing a target the card never printed.
            return []
        if spec.get("kind") in _UNFIZZLABLE_TARGET_KINDS and not spec_is_a_cost(spec):
            # …or its target **may be a player**. This returned None — "the
            # object has a target this loop cannot read" — and the reading it
            # lacked exists now: see :meth:`_player_target_legality`.
            return self._player_target_legality(
                item, program, spec, holder, mode_index, addresses=addresses,
            )
        if spec_is_a_cost(spec):
            # …and the second spelling of "does not target at all": a spell
            # whose whole derived spec is a **payment** picker ("As an
            # additional cost to cast this spell, sacrifice a creature. Draw
            # two cards.", Village Rites). ``derive_cast_spec`` answers with
            # the cost when there is no target beside it, so the test above
            # did not see "no target" — and an id stamped on the item was then
            # judged as one. The AI names the permanent it means to pay with on
            # the target channel, that permanent is in the graveyard by the
            # time the spell is on the stack, and every such spell paid its
            # cost and was then "countered by the rules" for a target it never
            # printed: 15 of 15 in the pool, Diabolic Intent in a simulated
            # game. A payment is not a target (CR 601.2b vs 601.2c), which is
            # what a cost flag at the top of a spec says.
            return []
        if any(
            role.get("kind") in _UNFIZZLABLE_TARGET_KINDS
            for role in spec_roles(spec)
        ):
            # …and the same exclusion one shape up. "**Target player** gains
            # control of target permanent you control" (Donate) prints the word
            # twice and one instance names a seat, so CR 608.2b's all-or-nothing
            # question has an answer this loop cannot reach: the permanent
            # leaving makes *one* target illegal and the spell still resolves,
            # doing nothing for the slot that is gone (608.2b's last sentence,
            # which each handler already applies). Counted as illegal here it
            # would counter a spell whose player target is perfectly legal —
            # the wrong "yes" the table above is named for, arriving through a
            # role instead of through a kind.
            #
            # **Answered where the announcement recorded its seats per role**
            # (``targeting.ROLE_SEATS``): "…creatures **target player** controls
            # … creatures **another target player** controls" (Cultural
            # Exchange). There the reading this branch lacked exists — each
            # player is on a slot of its own, so each has a verdict of its own
            # and the object-level question is answerable.
            seated = self._role_seat_target_legality(
                item, spec, holder, addresses=addresses,
            )
            if seated is None:
                # …and where it recorded one seat on the scalar (Donate, Lunge,
                # Shower of Sparks), ``stack_targets.announcement_targets`` says
                # which role named a seat and which an object, so each is
                # judged as what it is — see :meth:`_role_target_legality`.
                return self._role_target_legality(item, spec, holder)
            legality: list[bool] = list(seated)
        else:
            legality = []

        # **The printed description is re-asked too** (CR 608.2b: "Other
        # changes to the game state may cause a target to no longer be legal;
        # for example, its characteristics may have changed"). This loop
        # asked only "still there, still targetable", so a spell whose
        # target stopped answering its description resolved anyway: Sever Soul
        # whose target was made black in response gained its life, Vendetta and
        # Reckless Spite cost theirs, Spinning Darkness dealt its damage to the
        # now-black creature — and where the handler's own resolver refused the
        # id, its fall-through scan acted on a permanent nobody named (Ritual of
        # the Machine stole the creature *beside* its recoloured target).
        #
        # The question is the announcement's, asked again through
        # ``_described_cast_target_slots`` — not a second reading of the words.
        # Computed lazily, once per resolution, only for a target that survived
        # the two cheaper tests.
        #
        # **For a modal spell, the chosen mode's description** (*mode_index*).
        # Where **an opponent** chose the mode (CR 700.2e, Fatal Lore) this
        # used not to be asked at all: its targets were named after the
        # choice, against a spec carrying the chooser's seat ("…creatures
        # **that player** controls"), and re-asked without that seat the
        # enumeration offers nothing, so every such target would read illegal.
        described = _resolution_rechecks_description(spec)
        offered: set[tuple[int, int]] | None = None
        if described and program.modes and program.mode_chooser is not None:
            # **That seat is on the stack item**, and has been since the mode's
            # own text needed it ("**That player** draws up to three cards"):
            # ``_resolve_opponent_mode_choice`` freezes who chose under the key
            # every fire site freezes a seat under. The paragraph above was
            # written before anything read it here, so a Fatal Lore whose two
            # named creatures changed controller in response — neither any
            # longer "a creature that player controls" — resolved, destroyed
            # nothing and still let the opponent draw three, where every target
            # is illegal and the spell does not resolve.
            #
            # Re-asked through the announcement's own call
            # (``arm_modal_mode_targets``): the same spec, the same seat, the
            # same enumeration. With no seat recorded the description is left
            # unasked, as it was — the direction that never invents a fizzle.
            chooser = self._mode_chooser_seat(item)
            if chooser is None:
                described = False
            elif spec.get("that_player_only"):
                offered = {
                    (entry["seat"], entry["index"])
                    for entry in self._enumerate_targets(
                        item.caster_index, card,
                        {**spec, "that_player_index": chooser}, for_cast=True,
                    )
                    if entry.get("kind") == "permanent"
                }
        ids = getattr(holder, "target_permanent_id", None)
        for position, permanent_id in enumerate(
            ids if isinstance(ids, (list, tuple)) else [ids]
        ):
            if not isinstance(permanent_id, int):
                continue
            target = self.permanent_by_id(permanent_id)
            legal = (
                target is not None
                and self.is_on_battlefield(target)
                # CR 608.2b's "other changes to the game state": protection or
                # shroud gained in response is the rule's own second example,
                # and it is the same predicate the cast gate asked.
                and self._can_be_targeted(
                    target, card, caster_index=item.caster_index,
                )
            )
            if legal and described:
                if offered is None:
                    offered = self._described_cast_target_slots(
                        item.caster_index, card, spec, mode_index=mode_index,
                        # The announcement *spec* was derived under
                        # (``_resolving_announcements``, CR 702.33g), handed on
                        # for the reason the cast gate hands it on: the
                        # per-candidate probe re-derives the spec, and read as
                        # the card's every arm an unkicked Rushing River ("If
                        # this spell was kicked, return **another** target…")
                        # is a two-target spell that refuses each lone slot —
                        # so its one legal target read as illegal and the spell
                        # was countered.
                        optional_cost_payments=(
                            getattr(item, "choices", None) or {}
                        ).get("additional_costs_paid") or {},
                    )
                legal = (
                    self.controller_index_of(target),
                    self.battlefield_index_of(target),
                ) in offered
            legality.append(legal)
            if addresses is not None:
                addresses.append(("permanent", "item", position, permanent_id))
        # A graveyard stamp is recorded on the item alone — a "choose one or
        # more" mode carries no such field — so it is read for the item's own
        # announcement and for nothing else.
        stamps = item.target_graveyard_card if holder is item else None
        for stamp in (stamps if isinstance(stamps, list) else [stamps]):
            if stamp is None:
                continue
            # The stamp resolving to no slot means no copy of the chosen card
            # remains in that graveyard — the unambiguous "gone", per the
            # docstring above. While a copy survives, `graveyard_index_of`
            # answers a slot (clamping where it must) and the target is legal.
            # …and legal only while a card in a graveyard may be targeted at
            # all (Ground Seal arriving in response): one reader for both.
            legality.append(self.graveyard_target_is_legal(stamp))
            if addresses is not None:
                addresses.append(None)
        stack_target = getattr(holder, "target_stack_item", None)
        if stack_target is not None and (
            not program.modes
            or spec.get("kind") in _STACK_TARGET_KINDS
            or any(role_is_stack(role) for role in spec_roles(spec))
        ):
            # A countered or already-resolved spell has left the zone it was
            # targeted in, which is CR 608.2b's first sentence.
            #
            # **Of a modal spell, only where the chosen mode's target is on the
            # stack.** A stack object recorded beside a mode that names a
            # creature is not something that mode announced, and counting it
            # would keep a spell whose one real target is gone "partly legal".
            still_there = any(obj is stack_target for obj in self.stack)
            if still_there:
                # …and its second: "that targets a land you control" stops
                # being true when the land leaves or the object is re-aimed
                # (Teferi's Response), "red" when the spell is recoloured in
                # response, "with a single target" when it is not one any
                # more. Re-asked through the announcement's own enumeration —
                # for **every** stack spec, as the announcement is, where it
                # was four keys: a description the handler re-read for itself
                # was a description only its own sentence honoured, and the
                # sentence behind it ran regardless (Exclude drew its card
                # for countering nothing).
                admitted = self._offered_stack_targets(
                    item.caster_index, card, spec
                )
                if admitted is not None:
                    still_there = any(
                        obj is stack_target for obj in admitted
                    )
            legality.append(still_there)
            if addresses is not None:
                addresses.append(None)
        return legality

    def _mode_chooser_seat(self, item) -> int | None:
        """The seat that chose *item*'s mode where the card gave that choice
        to another player (CR 700.2e), or None if none is recorded.

        Read off the stack item, where ``_resolve_opponent_mode_choice`` wrote
        it as the mode was chosen — under the frozen-seat key the mode's own
        "that player" is read through, so the gate and the effect cannot name
        two different players.
        """
        from .grammar.lowering._events import EVENT_SUBJECT_PLAYER

        seat = (getattr(item, "trigger_context", None) or {}).get(EVENT_SUBJECT_PLAYER)
        if isinstance(seat, int) and 0 <= seat < len(self.players):
            return seat
        return None

    def _player_target_legality(
        self, item, program, spec, holder, mode_index, *,
        addresses: "list | None" = None,
    ) -> "list[bool] | None":
        """CR 608.2b for an announcement whose target **may be a player** —
        "target player", "any target", "player or planeswalker", a division —
        or None where it still cannot be answered.

        These were the kinds this rule declined outright, on a reason that was
        true of the stack item's fields and not of the announcement: a seat and
        a chosen player ride one field, "so a Fireball split between a creature
        and its controller is indistinguishable from one aimed at the creature
        alone". ``stack_targets`` has told them apart since Psychic Battle
        needed to — a division records every target on its own entry, a face
        where the slot is None, and outside a division the ids decide, the seat
        being a chosen player only where no object was named. That reader
        (``announcement_targets``) is what this asks, so which targets there
        are is one answer here and at ``announce_targets_chosen``.

        **Legal is the announcement's question, asked again**, as it is for a
        permanent target in :meth:`_announcement_target_legality`: still among
        what ``_enumerate_targets``
        would offer the caster now. So a player who gained shroud in response
        (Ivory Mask, CR 702.18a) or left the game (CR 800.4a) is an illegal
        target by the same list that would have refused naming them, and a
        spell whose only target that was does not resolve — 118 of 119 did,
        Mind Rot discarding from behind the Mask. A creature named for "any
        target" is judged the same way, which is what stops a burn spell whose
        creature has left from running the sentence printed after its damage.

        A cast that **named nobody** is judged at the seat it resolves at
        (``_spell_default_seat``) where it owed a target, for the reason the
        announcement gate judges it there: the default is a target too.

        None, still, where **an opponent** chose the mode (CR 700.2e): the
        seat its targets were enumerated against was held by the prompt that
        asked, as the description re-check above says of the same spells.
        """
        if program.modes and program.mode_chooser is not None:
            return None
        if any(spec.get(flag) for flag in ("source_of_choice", "optional")):
            # A chosen source and an optional copy are picked, not targeted.
            return []
        from .stack_targets import ChosenTarget, announcement_targets

        card = item.card
        paid = (getattr(item, "choices", None) or {}).get("additional_costs_paid") or {}
        chosen = list(announcement_targets(self, item, spec, holder))
        if not chosen:
            if holder is not item or not spec_offers_a_player(spec):
                return []
            if cast_target_obligation(
                card, program, optional_cost_payments=paid,
                x_value=item.x_value, mode_index=mode_index,
            ) is None:
                # "Up to one target player", "X target …" at X = 0: naming
                # nobody was the announcement, and there is nothing to judge.
                return []
            standing = self._spell_default_seat(item.caster_index)
            if not 0 <= standing < len(self.players):
                return None
            chosen = [ChosenTarget("player", seat=standing)]
        offered = self._enumerate_targets(
            item.caster_index, card, dict(spec), for_cast=True,
            optional_cost_payments=paid, mode_index=mode_index,
        )
        faces = {t["seat"] for t in offered if t.get("kind") == "player"}
        slots = {
            (t["seat"], t["index"]) for t in offered if t.get("kind") == "permanent"
        }
        legality: list[bool] = []
        found: list = []
        for target in chosen:
            if target.kind == "player":
                legality.append(target.seat in faces)
            elif target.kind == "permanent":
                permanent = self.permanent_by_id(target.permanent_id)
                legality.append(
                    permanent is not None
                    and self.is_on_battlefield(permanent)
                    and (
                        self.controller_index_of(permanent),
                        self.battlefield_index_of(permanent),
                    ) in slots
                )
            else:
                # A stack object or a graveyard card is not a target these
                # kinds describe; an announcement carrying one is not one this
                # can count.
                return None
            found.append(
                (target.kind, target.channel, target.position, target.permanent_id)
            )
        if addresses is not None:
            addresses.extend(found)
        return legality

    def stale_comparison_refusal(self, item) -> str | None:
        """CR 608.2b for **a printed comparison between two seats**, and for
        nothing else.

        "Choose target opponent **who has more life than you do** as you
        activate this ability" (the Exodus Keepers); "that player chooses target
        player **who controls more creatures than they do and is their
        opponent**" (the Oaths). ``legality``'s seat loop enforces the clause at
        announcement, which is where a restriction on who may be chosen has to
        be enforced or it does nothing — and until this, that was the *only*
        moment it was asked. A Keeper of the Light activated while an opponent
        was ahead on life gained its 3 life anyway if that life total dropped in
        response, and the ability the rules would have countered instead
        resolved in full.

        **This is deliberately not "608.2b widened to abilities."** That is its
        own round, blocked on a different bug, and ``ROADMAP.md`` records the
        three shapes it would still not answer — a triggered ability's targets
        (mis-stamped at the fire site), a target that may be a player face, an
        Aura's and a graveyard's. A partial version of it that *looked* general
        would be worse than nothing, because the next reader would take the
        cover for granted. So this gate says what it covers in its name: one
        printed clause, re-asked through :func:`player_comparisons.
        seat_answers_comparison` — the same function the picker was built from,
        so the two moments cannot come to disagree about what the words mean.

        Two conditions bound it, and both are the rule rather than caution:

        * the announced target is a **seat**, and the clause is the one this
          object printed about it. A comparison the derivation does not carry is
          a comparison nothing announced;
        * that seat is the object's **only** target. CR 608.2b is all-or-nothing
          — an object with a second, still-legal target resolves, and its
          illegal target is merely not affected — so an object printing two
          instances of the word cannot be countered on the strength of one of
          them. Keeper of the Dead is exactly that card ("…Destroy target
          nonblack creature that player controls"), and it is left alone;
          the other nine cards printing the clause name one target each.
        """
        instruction = getattr(item, "ability_instruction", None)
        seat = getattr(item, "target_player_index", None)
        if instruction is None or not isinstance(seat, int):
            # A spell reaches ``illegal_targets_refusal`` above; nothing in the
            # pool prints this clause on one, and an object that announced no
            # seat has no comparison to have gone stale.
            return None
        if not 0 <= seat < len(self.players):
            return None
        spec = derive_instruction_spec([instruction])
        compared = (spec or {}).get("compared")
        if not compared:
            return None
        if len(_ability_target_quantifiers(instruction)) != 1:
            return None
        from .player_comparisons import seat_answers_comparison

        if seat_answers_comparison(
            self, seat, compared,
            caster_index=item.caster_index,
            # "…than **they** do" is the seat the firing event froze, read
            # through the one accessor the picker read it through — a second
            # reading here would be a gate answering about a different player
            # from the one the announcement was made about.
            that_player_seat=self._that_player_seat(item),
        ):
            return None
        return (
            f"{item.card.name} was removed from the stack: "
            f"{self.players[seat].name} no longer answers the printed "
            "comparison, so its only target is illegal (608.2b)"
        )

    def vanished_graveyard_target_refusal(self, item) -> str | None:
        """CR 608.2b for **an object whose every target was a card in a
        graveyard that is no longer there** — an activated ability, a
        triggered one that chose its target, or an Aura spell whose enchant
        target was the card (see the bound below) — and for nothing else.

        "A target that's no longer in the zone it was in when it was targeted
        is illegal. … If all its targets … are now illegal, the spell or
        ability doesn't resolve." For a spell :meth:`illegal_targets_refusal`
        answers this from the stamp ``_stack_push_object`` recorded. An ability
        never reached that gate, so its resolution found the stamp re-located
        to nothing — which the handlers read as *no card was announced*, the
        headless caller's bare activation — and took their own pick: exile the
        card Adun Oakenshield was activated at in response and it returned the
        creature card beside it, a card nobody named. Every graveyard handler
        behind an activated ability did the same, because the decision was
        each handler's and none of them could tell the two cases apart.

        Asked above the instructions, like the gates beside it, so the answer
        is the object's: nothing printed after the targeted sentence runs
        either.

        Three bounds, each the rule or the data model rather than caution:

        * an **activated** ability (``StackItem.activated``), or a triggered
          one whose target was **chosen for it as it went on the stack**
          (``StackItem.targets_chosen``, CR 603.3d) — together
          :func:`announced_by_a_choice`. A trigger's target fields
          are also where a fire site threads a slot the *event* named, and a
          slot nobody chose is not a target that can become illegal — that is
          ROADMAP's first decline under this rule, and it stands for every
          trigger without the mark. The mark is what a graveyard-card trigger
          gets now that it chooses (Gravedigger, Karmic Guide): exile the card
          it named in response and it returned the creature card beside it —
          all fourteen targeted graveyard entry triggers did, on a table with
          a second card of the kind to take;
        * every target the object chose is a graveyard card — read through
          ``stack_targets.chosen_targets``, the one reader of what an object
          announced. An object that also chose a permanent or a player
          (Goblin Welder) has a target this cannot judge, so "every target" is
          not answerable and the handlers' per-slot answers stand;
        * the stamp resolves to **no** slot: no copy of that card is left in
          that pile. Two copies of one card are one ``CardDefinition``, so
          while any copy survives the target is legal — the ambiguity
          ``Game.graveyard_index_of`` documents and deliberately clamps.

        An activation that owed a card and named none had the picker's first
        one named for it as it was announced, so it carries a stamp like any
        other and is judged like any other.
        """
        # **…and an Aura spell**, which is the fourth object this rule is about
        # and the one that fell between the gates. "Enchant creature card in a
        # graveyard" (Animate Dead, Dance of the Dead) is a target a player
        # chose as the spell was cast (CR 115.1b, CR 601.2c) — none of the
        # trigger's "a slot nobody chose" applies — but
        # :meth:`illegal_targets_refusal` answers for instants and sorceries
        # only, on the reasoning that an Aura whose host has left "enters
        # attached to nothing and is binned by CR 704.5m one sweep later — the
        # same destination by a different rule". True of an Aura that enchants
        # a permanent. Not of these two: their attach reads a vanished card as
        # *no card was named* and goes looking, so with the Grizzly Bears it
        # named exiled in response, Animate Dead returned the Craw Wurm in its
        # caster's own graveyard.
        #
        # Bounded to a **permanent** spell so that nothing this method says
        # about an instant or sorcery changes: those are judged one gate up,
        # including the shapes that gate declines on purpose. A permanent
        # spell that is not an Aura targets nothing (``chosen_targets`` is
        # empty for it), so in practice this is the Auras.
        # The object is a spell (its card is the cast object, CR 709.3b), not
        # a permanent, so its printed type is the question.
        spell = item.card
        aura_spell = (
            item.ability_instruction is None
            and not getattr(item, "is_ability", False)
            and spell.primary_type not in ("instant", "sorcery")
        )
        if not (announced_by_a_choice(item) or aura_spell):
            return None
        if resolves_with_illegal_targets(item.card, item.ability_text):
            return None
        from .stack_targets import chosen_targets

        chosen = chosen_targets(self, item)
        if not chosen:
            return None
        if any(target.kind != "graveyard" for target in chosen):
            return None
        if any(self.graveyard_target_is_legal(target.stamp) for target in chosen):
            return None
        if any(self.graveyard_index_of(target.stamp) is not None for target in chosen):
            # Still in its pile and no longer targetable: "Cards in graveyards
            # can't be the targets of spells or abilities" arrived in response
            # (Ground Seal). Said in its own words, because "no longer in the
            # graveyard" would be false of a card anyone can see there.
            from .target_immunity import graveyard_cards_untargetable

            return (
                f"{item.card.name}{'' if aura_spell else ' ability'} was "
                f"removed from the stack: its target can't be targeted "
                f"({graveyard_cards_untargetable(self)}, 608.2b)"
            )
        if aura_spell:
            return (
                f"{item.card.name} was removed from the stack: its target "
                "is no longer in the graveyard (608.2b)"
            )
        return (
            f"{item.card.name} ability was removed from the stack: its target "
            "is no longer in the graveyard (608.2b)"
        )

    def sealed_graveyard_target_refusal(self, item) -> str | None:
        """Why the **ability** *item* cannot have its one target — a card in a
        graveyard — while "Cards in graveyards can't be the targets of spells
        or abilities" (Ground Seal) is on the battlefield, or None.

        The half of that sentence the target enumeration cannot reach. A cast
        and an activation name their target through
        ``_enumerate_graveyard_creatures``, which offers nothing under the
        Seal, so CR 601.2c / 602.2b refuse them before anything is paid. A
        **triggered** ability has no picker for a card in a graveyard at all —
        the kind is not one ``_trigger_target_candidates`` chooses — so its
        handler scans the pile for itself as it resolves, and a scan asks
        nobody whether the card may be targeted: Karmic Guide went on
        returning a creature card and Monk Idealist an enchantment card with
        the Seal in play. (A bare, headless activation takes the same scan.)

        Asked at both ends of the rule by the two callers: as a trigger is put
        on the stack (CR 603.3d — no legal target, so it is removed) and as
        any ability resolves (CR 608.2b — the Seal arrived in response).

        What makes the scan's pick a **target** is not in the compiled
        program: "you may return target creature card from your graveyard"
        (Gravedigger) and "…unless you return a basic land card from your
        graveyard" (Harvest Wurm) lower to one instruction with one payload,
        and the card's ruling protects exactly the second ("abilities that
        don't target cards in graveyards … can still affect those cards"). So
        the evidence is the one this engine already keeps for CR 115.3 —
        ``stack_targets._printed_target_instances``, how many times the
        ability's own printed line says "target" — and the bounds are:

        * an **ability** (a spell's target is announced and stamped, and
          ``illegal_targets_refusal`` judges it);
        * its derived spec is the graveyard target kind and not a cost;
        * its line prints the word **exactly once**, so its one target is
          that card. Two instances are two targets, one of which this cannot
          judge (Goblin Welder), and none is a choice that is not a target;
        * it does not say "up to" — zero targets is then a legal announcement
          (CR 601.2c) and the ability stays to do whatever else it prints.
        """
        from .target_immunity import graveyard_cards_untargetable

        sealed = graveyard_cards_untargetable(self)
        if sealed is None or not getattr(item, "is_ability", False):
            return None
        instruction = item.ability_instruction
        if instruction is None or item.hook_key is not None:
            return None
        if modal_trigger_modes(instruction):
            return None
        if resolves_with_illegal_targets(item.card, item.ability_text):
            return None
        from .targeting import graveyard_target_spec

        spec = graveyard_target_spec(
            item.card, compile_card_oracle(item.card), instruction=instruction,
        )
        if spec is None or spec_is_a_cost(spec):
            return None
        from .stack_targets import _printed_target_instances

        if _printed_target_instances(item) != 1:
            return None
        if "up to" in (item.ability_text or "").lower():
            return None
        return (
            f"{item.card.name} ability was removed from the stack: its "
            f"target can't be targeted ({sealed}, 608.2b)"
        )

    def ability_target_verdicts(
        self, item, *, recorded_only: bool = False,
    ) -> "list[tuple] | None":
        """Every target the **ability** *item* announced, each paired with
        whether it is still legal as the ability resolves (CR 608.2b) — or
        None where "is every target illegal?" cannot be answered for the whole
        object, and it must simply resolve as it always has.

        ``[(ChosenTarget, legal), …]`` in announcement order. Which targets
        there are is ``stack_targets``' answer, the one reader of what a stack
        object announced; whether each is legal is **the announcement's own
        question, asked again** — still among what ``_enumerate_targets`` would
        offer this ability now, through the instruction's own narrowing, with
        its source (CR 608.2b: "if the source of an ability has left the zone
        it was in, its last known information is used") and for the card the
        activation gate enumerated it for. That is the list
        :meth:`activation_target_refusal` held the announcement to and the
        list the browser's picker was handed, so a target is illegal here by
        exactly the predicate that would have refused naming it: it has left,
        it gained shroud or protection from the source, it stopped being the
        printed noun, colour, tapped state or controller, it left the combat
        the phrase names, its player gained shroud or left the game, the spell
        it named has left the stack or stopped answering the phrase.

        The shapes this declines, each named:

        * an object ``stack_targets`` cannot read (a hook-keyed one) or whose
          legal targets cannot be enumerated (``_candidates`` answers None: a
          "that player controls" with no frozen seat, a triggered ability's
          controller narrowing the spec does not carry);
        * an ability that prints **more than one instance** of the word and is
          not a roles announcement (Keeper of the Dead: "Choose target opponent
          … Destroy target nonblack creature that player controls"). The spec
          describes the first slot only and the second is the handler's pick as
          it resolves, so "every target" is not something the stack object
          records — :meth:`stale_comparison_refusal` leaves the same card alone
          for the same reason;
        * a **roles** announcement with a role that is not a permanent (Goblin
          Welder's graveyard card), for the reason the spell side gives of a
          player role. A roles announcement of permanents is judged the way a
          roles *spell* is — still there and still targetable; each role's
          description and relation is ``handlers/_common.roles_still_legal``'s.

        A **graveyard** target is legal while any copy of the chosen card is
        left in that pile, the deliberately ambiguous case
        ``Game.graveyard_index_of`` documents.

        *recorded_only* asks a narrower question, and the second shape above
        can answer it: whether each target the object **records** is still
        legal, not whether every target it has is. An ability printing a
        second instance records the first instance's choice alone (the second
        is its handler's pick as it resolves), and the spec in hand is that
        first instance's — so a verdict about the recorded target is exactly
        as good as one about a single-instance ability's. Cuombajj Witches'
        "1 damage to any target and 1 damage to any target of an opponent's
        choice" is the shape. :meth:`resettle_announced_target_seats` is the
        reader: it follows a recorded target that changed controller, and has
        no use for an "every target" it does not ask.
        """
        from .stack_targets import (_candidates, _printed_target_instances,
                                    _read, announcements)

        announced = announcements(item)
        if announced is None:
            return None
        source = getattr(item, "source_permanent", None)
        verdicts: list[tuple] = []
        for announcement in announced:
            targets = _read(self, item, announcement)
            if not targets:
                continue
            spec = announcement.spec
            if spec.get("kind") == ROLES_TARGET_KIND:
                if any(target.kind != "permanent" for target in targets):
                    return None
                # The card the announcement was enumerated for: an activation
                # reads its permanent's **effective** card (a Clone's abilities
                # are the copied creature's, CR 707.2), a trigger the card on
                # its stack object — ``stack_targets._candidates`` draws the
                # same line for the flat announcement below.
                card = item.card
                if getattr(item, "activated", False):
                    card = getattr(source, "effective_card", None) or item.card
                role_specs = spec_roles(spec)
                for target in targets:
                    permanent = self.permanent_by_id(target.permanent_id)
                    role = (
                        role_specs[target.position]
                        if 0 <= target.position < len(role_specs) else None
                    )
                    verdicts.append((target, bool(
                        permanent is not None
                        and self.is_on_battlefield(permanent)
                        and self._can_be_targeted(
                            permanent, card, caster_index=item.caster_index,
                            ability_source=source, source_spec=role,
                        )
                    )))
                continue
            instances = _printed_target_instances(item)
            if instances is not None and instances != 1 and not recorded_only:
                return None
            candidates = _candidates(self, item, announcement, targets[0])
            if candidates is None:
                return None
            for target in targets:
                if target.kind == "graveyard":
                    legal = self.graveyard_target_is_legal(target.stamp)
                else:
                    legal = any(candidate.same_object(target) for candidate in candidates)
                verdicts.append((target, legal))
        return verdicts

    def ability_targets_refusal(self, item) -> str | None:
        """CR 608.2b for an **ability whose targets were chosen**: the reason
        it leaves the stack without resolving, or None.

        :meth:`illegal_targets_refusal`'s answer for the abilities whose
        targets are an announcement (:func:`announced_by_a_choice`): an
        **activated** one — chosen by a player as the ability was activated
        (CR 602.2b), held to the picker's list by
        :meth:`activation_target_refusal` before any cost was paid, recorded on
        the stack item and marked (``StackItem.activated``) — and a
        **triggered** one whose own picker chose them as it went on the stack
        (CR 603.3d, ``StackItem.targets_chosen``). The reason that method gives
        for declining a trigger's *stamped* target — a fire site records an id
        nobody chose — is not true of either, so the rule's two halves are
        both asked of them:

        * **every** target illegal → the ability does not resolve. Nothing
          printed behind the targeted sentence happens ("Target creature gets
          -3/-3 until end of turn. **Draw a card.**" — Savage Gorilla's ruling:
          no card), nothing is acted on that has become illegal, and nothing
          that was not named is acted on in its place. Costs stay paid; the
          rule refunds nothing.
        * some target still legal → it resolves, and the illegal ones are
          blanked out of the announcement first
          (:meth:`blank_illegal_resolution_targets`).

        "Legal" is :meth:`ability_target_verdicts`. An ability that named no
        target — a bare activation, the headless caller's standing convention,
        or an "up to one" that chose none — has nothing to judge and resolves
        on its handler's pick.

        A bare activation whose only recorded target is the **default seat** a
        player-targeted ability resolves at is judged like any other target:
        the default is the target (``stack_targets``' reading), and a seat
        that could not have been named is not one the ability may reach.
        """
        verdicts = self.ability_target_verdicts(item)
        if not verdicts or any(legal for _target, legal in verdicts):
            return None
        if all(target.kind == "graveyard" for target, _legal in verdicts):
            # Every target was a card in a graveyard and none is left there:
            # :meth:`vanished_graveyard_target_refusal` is asked one call
            # later and says so in its own words. The same answer from the
            # same reader (``graveyard_index_of``); left to the gate that has
            # been giving it so its log line stays the one players and tests
            # already read.
            return None
        return (
            f"{item.card.name} ability was removed from the stack: "
            "every target is illegal (608.2b)"
        )

    def blank_illegal_resolution_targets(self, item) -> int:
        """Rewrite each **illegal** slot of an object that is about to resolve
        so that it names nothing, and return how many were rewritten.

        CR 608.2b's last sentences, applied to the announcement once instead of
        being left to each handler: "Illegal targets, if any, won't be affected
        by parts of a resolving spell's effect for which they're illegal … If
        part of the effect requires information about an illegal target, it
        fails to determine any such information."
        :meth:`illegal_targets_refusal` has already let the object through, so
        at least one target is legal and what is left to decide is the rest.

        The verdicts are the ones that gate read — this method asks the same
        two readers for the same object (:meth:`_announcement_target_legality`
        for a spell, :meth:`ability_target_verdicts` for an ability),
        so "illegal enough to be left out" and "illegal enough to count toward
        every target" are one opinion.

        The same bounds as the gate, for the same reasons: an instant or a
        sorcery, or an ability whose targets were chosen
        (:func:`announced_by_a_choice`). A target a fire site stamped is not
        judged, and an announcement the readers decline is left exactly as it
        is.
        """
        from .stack_targets import (ChosenTarget, blank_illegal_targets,
                                    names_several_targets)

        # An object that named one target has nothing left to blank: the gate
        # either removed it or found that target legal. Asked first, off the
        # item's own fields, so the common resolution pays for one enumeration
        # and not two.
        #
        # **Unless the object prints the exception** ("This ability still
        # resolves if its target becomes illegal", Gilded Drake). The gate let
        # it through *with* its one target illegal, so that target is exactly
        # what is left to blank: the sentence waives the fizzle, not the
        # target's illegality, and "if you don't or can't make an exchange,
        # sacrifice this creature" is printed for the resolution in which the
        # exchange cannot be made. Unblanked, the Drake swapped itself for a
        # creature given shroud in response — or, when its target had left,
        # for whichever creature had slid into that battlefield slot.
        if not names_several_targets(item) and not resolves_with_illegal_targets(
            item.card, item.ability_text
        ):
            return 0
        illegal: list = []
        if item.ability_instruction is not None:
            if not announced_by_a_choice(item):
                return 0
            verdicts = self.ability_target_verdicts(item)
            if not verdicts:
                return 0
            illegal = [target for target, legal in verdicts if not legal]
        else:
            # A spell, so the card *is* the object and its printed type is the
            # question — the bound ``illegal_targets_refusal`` draws in the
            # same words, for the reason it gives.
            card = item.card
            if card.primary_type not in ("instant", "sorcery"):
                return 0
            program = compile_card_oracle(card)
            chosen_modes = tuple(getattr(item, "chosen_modes", ()) or ())
            for spec, holder, mode_index in self._resolving_announcements(item, program):
                addresses: list = []
                verdict = self._announcement_target_legality(
                    item, program, spec, holder, mode_index, addresses=addresses,
                )
                if verdict is None or len(addresses) != len(verdict):
                    continue
                mode = next(
                    (
                        position for position, chosen in enumerate(chosen_modes)
                        if chosen is holder
                    ),
                    None,
                )
                for address, legal in zip(addresses, verdict):
                    if legal or address is None:
                        continue
                    kind, channel, position, permanent_id = address
                    illegal.append(ChosenTarget(
                        kind, permanent_id=permanent_id, channel=channel,
                        position=position, mode=mode,
                    ))
        if not illegal:
            return 0
        return blank_illegal_targets(item, illegal)

    def resettle_announced_target_seats(self, item) -> int:
        """CR 608.2b's other direction: **a target that is still legal is
        still the target, wherever it now is.** Write, onto each announcement
        of *item* whose live permanent targets have changed controller, the
        seat their ids name now; return how many announcements were rewritten.

        "A target that's no longer in the zone it was in when it was targeted
        is illegal", and a battlefield is one zone however many players control
        what is on it. So the rule's question about a permanent that changed
        hands while the object waited is only its description's: "target
        creature" is still a target creature under its new controller, and
        "target creature **an opponent controls**" is not one once its caster
        controls it.

        An announced permanent is recorded twice — by ``permanent_id``, and by
        the seat whose battlefield it stood on (``target_player_index``, the
        slot beside it). The id is the choice (CR 601.2c, CR 400.7); the seat
        is *where the choice stood*, settled from the id as the object went on
        the stack (:meth:`announced_target_seat`, through
        ``_settle_announced_target_seat``). Every resolver looks the id up **on
        that seat** — ``handlers/_common.pick_target_permanent``'s first step,
        ``bare_announcements.announced_slots``, every "its controller" read off
        ``context.target`` — and that scoping is deliberate: a resolver has no
        description to test a permanent against, and many of them say "you
        control" by the battlefield they pass. So nothing noticed when the seat
        went stale. Measured on ``e67196d6`` (the census in
        ``tests/regressions/test_target_changed_controller_census.py``): of
        1,761 casts and activations whose description still admitted a target
        that changed hands in response, 1,417 missed it — Boomerang "returned
        nothing", Terror logged its target gone of a creature that had gone
        nowhere — 195 changed a permanent nobody named, and 6 charged "that
        creature's controller" to the seat it had left (Liquid Fire). Of 141
        triggered abilities whose chosen target did the same, 111 missed it
        and 100 hit a bystander: a trigger reads the slot beside the id, on
        the old battlefield, and Nekrataal destroyed the Hill Giant that had
        slid into the slot of the Bears it named.

        So the seat is settled **from the id again as the object resolves**,
        by the same query that settled it as the object was announced, and the
        resolvers' scoping stands: what moved is the record, once, rather than
        every reader's opinion of it. Under one condition, which is the rule:
        **the gate above judged the target still legal**. The verdicts are the
        ones :meth:`illegal_targets_refusal` and
        :meth:`blank_illegal_resolution_targets` read
        (:meth:`_announcement_target_legality` for a spell,
        :meth:`ability_target_verdicts` for an ability) — the announcement's
        own enumeration asked again, which offers a permanent on its new
        controller's battlefield exactly where its printed description admits
        it there. A controller word, a colour, protection gained in response:
        whatever made it illegal has already removed the object or blanked the
        slot, and a target the gate could not judge keeps the seat it had.
        An ability is asked about the targets it **records**
        (``recorded_only``): one printing a second instance of the word records
        the first instance's choice alone, and is judged on that — the gate
        cannot say whether *every* target is illegal there, but this does not
        ask (Cuombajj Witches' "1 damage to any target and 1 damage to any
        target of an opponent's choice", whose first target was missed).

        The same bounds as those gates, for their reasons: an instant or a
        sorcery (a copy included — CR 707.10 gives it the original's targets,
        and the gate judges it), or an ability whose targets were chosen
        (:func:`announced_by_a_choice`). A target a fire site stamped is not
        judged, so it is not followed either. Only the plain channel — the ids
        on the item or on a chosen mode: a division records a seat per entry
        and a roles announcement reads its ids without one, so neither is
        scoped by the field this rewrites. Several targets move only together,
        all on one battlefield (:meth:`announced_target_seat` answers None for
        two), because the field is one seat.
        """
        modes = tuple(getattr(item, "chosen_modes", ()) or ())

        def live_ids(holder) -> list:
            ids = getattr(holder, "target_permanent_id", None)
            return [
                permanent_id
                for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids])
                if isinstance(permanent_id, int) and not isinstance(permanent_id, bool)
                and self.permanent_by_id(permanent_id) is not None
            ]

        # Asked first, off the fields alone, so a resolution whose targets
        # stayed where they were pays for no enumeration: every live id is
        # still on the seat its announcement recorded.
        if not any(
            any(
                self.controller_index_of(self.permanent_by_id(permanent_id))
                != getattr(holder, "target_player_index", None)
                for permanent_id in live_ids(holder)
            )
            for holder in (item, *modes)
        ):
            return 0
        judged: list[tuple] = []
        if item.ability_instruction is not None:
            if not announced_by_a_choice(item):
                return 0
            verdicts = self.ability_target_verdicts(item, recorded_only=True)
            if not verdicts:
                return 0
            judged.append((item, [
                (target.permanent_id, legal) for target, legal in verdicts
                if target.kind == "permanent" and target.channel == "item"
                and target.mode is None
            ]))
        else:
            card = item.card
            if card.primary_type not in ("instant", "sorcery"):
                return 0
            program = compile_card_oracle(card)
            for spec, holder, mode_index in self._resolving_announcements(item, program):
                addresses: list = []
                verdict = self._announcement_target_legality(
                    item, program, spec, holder, mode_index, addresses=addresses,
                )
                if verdict is None or len(addresses) != len(verdict):
                    continue
                judged.append((holder, [
                    (address[3], legal) for address, legal in zip(addresses, verdict)
                    if address is not None and address[0] == "permanent"
                    and address[1] == "item"
                ]))
        moved = 0
        for holder, verdicts in judged:
            live = [
                (permanent_id, legal) for permanent_id, legal in verdicts
                if isinstance(permanent_id, int)
                and self.permanent_by_id(permanent_id) is not None
            ]
            if not live or not all(legal for _permanent_id, legal in live):
                continue
            seat = self.announced_target_seat([permanent_id for permanent_id, _ in live])
            if seat is None or seat == holder.target_player_index:
                continue
            holder.target_player_index = seat
            # …and the slot beside each id, for the handlers that read the
            # slot alone (a spell's and an activation's are re-read off the
            # ids anyway, ``bare_announcements.resolving_slots``; a trigger's
            # are not). A blanked or departed id keeps no slot. In the shape
            # the slot field already had, which is the shape
            # ``announced_slots`` keeps: a one-target announcement whose ids
            # are a list of one still has a scalar slot, and a handler that
            # reads only an ``int`` there (Swords to Plowshares) would read a
            # list as no slot at all and go scanning.
            ids = holder.target_permanent_id
            slots = []
            for permanent_id in (ids if isinstance(ids, (list, tuple)) else [ids]):
                permanent = (
                    self.permanent_by_id(permanent_id)
                    if isinstance(permanent_id, int) else None
                )
                slots.append(
                    None if permanent is None else self.battlefield_index_of(permanent)
                )
            listed = isinstance(holder.target_permanent_index, (list, tuple))
            holder.target_permanent_index = (
                slots if listed or len(slots) > 1 else slots[0]
            )
            moved += 1
        return moved
