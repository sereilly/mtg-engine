"""Putting an object on the stack, and announcing what it targets (CR 601.2c, CR 603.2).

``_stack_push`` is the one place an object goes on the stack. Before the push
CR 603.4's intervening-if may refuse a trigger; as it is pushed, the identity
behind every index the object carries is stamped (``_stamp_stack_targets``),
so a target is the permanent named and never whichever one later slides into
its slot; and after it, a triggered ability chooses its mode and targets (CR
700.2b, 603.3c-d) — at once, or, pushed inside a unit of play's trigger
window, when that window closes (``_trigger_choice_waits``, CR 117.5).

Every way an object comes to have targets is announced once, here:
"becomes the target of a spell or ability" for a permanent and for a player
(``_announce_targeting``, ``_announce_targeted_player``), and Psychic
Battle's "whenever a player chooses one or more targets"
(``announce_targets_chosen``). A permanent spell that is not an Aura targets
nothing (CR 115.1, ``spell_targets_nothing``), and an "up to" that named
nobody says so (``record_no_target_named``).

``announced_target_seat`` is the seat an announcement made by
``permanent_id`` already names - asked where an announcement's seat is
settled, which for an activation is before its cost is paid (CR 601.2c
precedes 601.2h); ``stack_target_seat`` is its twin for an object whose every
chosen target is a spell.
"""

from __future__ import annotations

from contextlib import contextmanager

from ..continuous import next_timestamp
from ..game_types import as_graveyard_stamps, as_target_ids, target_ids
from ..events import emit
from ..oracle import compile_card_oracle
from ..targeting import graveyard_target_spec
from ..trigger_order import is_triggered_object


class TargetAnnouncementsMixin:
    def _stack_push(
        self, item=None, *, targets_already_chosen: bool = False,
        announced_at_cast: bool = False, announce: bool = True,
    ):
        """Put *item* on the stack and finish announcing it, then return it.

        Two steps, because the second is only meaningful once the first has
        happened: :meth:`_stack_push_object` records the targets' identities
        and appends the object, and then a **modal triggered ability** chooses
        its mode and that mode's targets, which CR 700.2b and CR 603.3c place
        exactly here — "as part of putting that ability on the stack".

        It hangs off this method rather than off ``_enqueue_triggered_ability``
        for the reason this method exists at all: it is *the* one place an
        object goes on the stack, and the enqueue helper is not — the attack
        and block trigger fire sites in ``phases/declare_attackers_step.py``
        build their own ``StackItem`` and push it here directly. A choice armed
        one layer up covered the enqueued triggers and quietly missed those,
        which is the fire-site problem in miniature.

        **And one thing happens before the push rather than after it.** CR
        603.4's intervening-if is asked when the trigger event occurs, and an
        ability whose condition is false "does nothing" — it never goes on the
        stack at all. So :meth:`trigger_condition_holds` is the one gate that
        can refuse this method, and it returns ``None`` when it does. Every
        caller ignores the return except the fire sites that log "added to the
        stack", which now say so only if it was.

        *announced_at_cast* is an entry trigger carrying what its permanent
        spell announced (``_apply_self_enters_battlefield_triggers``): this
        engine names an entry trigger's target as the permanent is cast, so the
        choice was made, and **announced**, by the spell — where it is a
        choice the trigger could have made (``cast_announcement_fault``; one
        that is not is set aside below and the trigger is pushed as if nobody
        had announced for it). The trigger therefore
        asks for nothing here, and neither announcement is made a second time —
        "becomes the target of a spell or ability" and "whenever a player
        chooses one or more targets" each heard about it from the cast. Made
        again, a Sleeping Potion ("When enchanted creature becomes the target
        of a spell or ability, sacrifice this Aura") sacrificed itself to its
        own "tap enchanted creature", whose stack object carries the enchanted
        creature it was cast on.

        *announce* False is a **copy** whose controller has not yet decided
        what its targets will be (CR 707.10c: "Once the player has decided
        what the copy's targets will be, the copy is put onto the stack with
        those targets"). Nothing is announced for it here — not "becomes the
        target", not "is put onto the stack" — and it is marked
        ``announcement_owed`` until the decision is settled
        (:meth:`announce_copy_put_onto_stack`). Announced at the push, a
        storm copy of Scattershot told Daru Spiritualist it was targeted by
        the original's target before it was re-aimed, and again for the new
        target after (Scourge's post-promotion session).
        """
        if not self.trigger_condition_holds(item):
            return None
        # CR 603.3b: a triggered object pushed while a window is open is one
        # its controller may order against the others pushed in the same
        # window (``engine/trigger_order.py``). Recorded here, the one place an
        # object goes on the stack, for this method's own reason: the attack
        # and block fire sites build their objects and push them directly.
        # Whether it is still there when the window closes is asked then — the
        # choices below can remove it (CR 603.3c-d).
        if self.collected_triggers is not None and is_triggered_object(item):
            # …and which round of CR 603.3b's repeating process it is: one
            # after the triggered ability whose being put on the stack set it
            # off (``_announcing``), 0 for one the unit of play set off.
            item.trigger_round = self.announcing_trigger_round
            self.collected_triggers.append(item)
        fault = self.cast_announcement_fault(item) if announced_at_cast else None
        if fault is not None:
            # **The cast's announcement is a pre-answer to this trigger's own
            # choice, and it has to be one the choice would accept** (CR
            # 603.3d; ``cast_announcement_fault``). One that is not — a
            # creature with protection from this permanent, a player who gained
            # shroud while the spell waited, a target that has left — is set
            # aside, and the trigger is put on the stack as one nobody chose
            # for: it chooses below (a prompt for a seat that can be asked, the
            # picker's default otherwise), announces that choice, and is
            # removed if nothing is legal (CR 603.3c).
            if fault == "illegal":
                self.log.append(
                    f"{item.card.name}'s triggered ability can't target what "
                    "was named as it was cast; it chooses again (603.3d)"
                )
            item.target_player_index = None
            item.target_permanent_index = None
            item.target_permanent_id = None
            item.target_graveyard_card = None
            item.target_stack_item = None
            announced_at_cast = False
        elif announced_at_cast and self._trigger_target_candidates(
            item, announced=True
        ) is not None:
            # …and a pre-answer that **was** held to the trigger's own list
            # and passed is a target chosen for this ability (CR 603.3d), by
            # the same list the prompt would have offered — so it is one CR
            # 608.2b may be asked about as the ability resolves
            # (``StackItem.targets_chosen``). Not where the picker had no list
            # to hold the announcement to: that one rides the object unjudged,
            # at the push and at resolution alike.
            item.targets_chosen = True
        self._stack_push_object(item, announce=announce and not announced_at_cast)
        if not announce and item is not None:
            item.announcement_owed = True
        if announced_at_cast:
            # **The trigger is what targets, and now is when** (CR 115.1d,
            # CR 603.3d). The permanent spell that named this target was not
            # targeted (CR 115.1 lists what is: an instant or sorcery spell, an
            # Aura spell, an activated ability, a triggered ability) and
            # announced nothing as it was cast — ``spell_targets_nothing`` — so
            # "becomes the target" is announced here, for the object that does
            # the targeting, the first moment that object exists.
            #
            # Asked of the trigger's own evidence (``has_targets``: its spec
            # targets and its printed line says the word), not of the fields
            # being filled in: an Aura's "tap enchanted creature" carries the
            # creature the Aura spell was cast on and targets nothing, and
            # announcing that is how a Sleeping Potion ("when enchanted
            # creature becomes the target of a spell or ability, sacrifice
            # this Aura") came to sacrifice itself to its own entry trigger.
            from ..stack_targets import has_targets

            if has_targets(self, item):
                self._announce_targeting(item)
        # "Up to one target …" activated with nothing named: the announcement
        # is complete and names nobody (CR 601.2c). After the stamping, which
        # is what turns an announced slot into the id this reads.
        self._note_empty_announcement(item)
        # CR 113.6b: an ability that functions while the card is **on the
        # stack** starts functioning the moment the object is put there, and
        # Torrent of Lava's grants an activated ability to every creature — so
        # the layer pass has to run before the next player could use it, not at
        # the next state-based check.
        #
        # Guarded on the card's own text so this costs a cached substring test
        # for every other spell and every trigger. The *end* of the ability
        # needs no hook: the object leaves the stack by resolving, by being
        # countered or with its controller, and the CR 704.3 sweep recomputes
        # continuous effects before anybody receives priority again — which is
        # the same argument that lets a permanent leaving the battlefield end
        # its own board-wide static.
        from ..stack_statics import grants_stack_static

        if item is not None and grants_stack_static(getattr(item, "card", None)):
            # …and it starts **now**: the object's timestamp is the moment it
            # entered this zone (CR 613.7d), which is its static ability's
            # effect's (CR 613.7a) — what orders the ability it grants against
            # a "loses all abilities" that arrives while it is still here.
            if getattr(item, "timestamp", None) is None:
                item.timestamp = next_timestamp()
            self._recompute_continuous_effects()
        # **A triggered ability's choices wait for the unit of play that set
        # it off to finish** (CR 603.3c-d, CR 117.5): see
        # :meth:`_trigger_choice_waits`.
        if self._trigger_choice_waits(
            item, targets_already_chosen=targets_already_chosen,
            announced_at_cast=announced_at_cast,
        ):
            self.unannounced_triggers.append(item)
            return item
        self._finish_announcement(
            item, targets_already_chosen=targets_already_chosen,
            announced_at_cast=announced_at_cast,
        )
        return item

    def _trigger_choice_waits(
        self, item, *, targets_already_chosen: bool, announced_at_cast: bool,
    ) -> bool:
        """Whether *item*'s mode and targets are chosen when the outermost
        trigger window closes rather than now.

        CR 603.3: a triggered ability is put on the stack "the next time a
        player would receive priority", and CR 117.5 puts that after the
        state-based check; CR 603.3c-d choose its mode and targets as it is put
        there. This engine pushes the object at its **fire site**, and chose
        there too — with the event that set it off still under way and the
        state-based check still to come. So a death in a sweep offered every
        creature the sweep was about to take, itself included (Festering
        Goblin's "target creature gets -1/-1" was named onto a creature already
        in the graveyard, where CR 603.3d removes it), Celestial Gatekeeper
        dying to Wrath of God beside a Cleric could return the Cleric only if
        the Cleric had died first, and Scion of Darkness could not name the
        blocker it trampled over and killed, which its 2004-10-04 ruling says
        it may.

        Every unit of play that sets triggers off is already a window
        (``putting_triggers_on_stack``: a resolution, a batch, an entry, a
        state-based sweep, each turn-based action), and the outermost one
        closes before anything could resolve what it collected — after the
        resolution has finished, and, for a step's turn-based action, after the
        state-based check the step makes inside it (combat damage, CR 510.2 /
        704.3). That is when the waiting choices are made
        (:meth:`_announce_waiting_triggers`), in the order the objects were
        pushed. Outside a window nothing waits: a fire site with no unit around
        it chooses as it pushes, as every one did.

        Only what still has a choice to make waits — a modal trigger, or one
        whose target the picker chooses and nothing has recorded
        (``_entry_trigger_chooses_a_target``, the gate the push already asks
        for an entry trigger). A copy and an activated ability arrive with
        their targets (*targets_already_chosen*), and an entry trigger carrying
        its permanent spell's announcement has had it judged by
        ``cast_announcement_fault`` above.
        """
        if self.collected_triggers is None or item is None:
            return False
        if targets_already_chosen or announced_at_cast:
            return False
        if not is_triggered_object(item):
            return False
        instruction = item.ability_instruction
        if instruction is None:
            return False
        from ..modal_triggers import modal_trigger_modes

        if modal_trigger_modes(instruction):
            return True
        if (
            item.target_permanent_id is not None
            or item.about_permanent_id is not None
            or item.target_stack_item is not None
        ):
            return False
        return self._entry_trigger_chooses_a_target(instruction, item.ability_text)

    def _announce_waiting_triggers(self) -> None:
        """Make the choices :meth:`_trigger_choice_waits` held back, oldest
        first, for every waiting object still on the stack.

        Asked as the outermost trigger window closes, while it is still open:
        an announcement can set off another trigger ("becomes the target of",
        "whenever a player chooses one or more targets"), and that one belongs
        to the same unit — it waits behind the others and is chosen in this
        same loop — but to the **next round** of CR 603.3b's process
        (``StackItem.trigger_round``, :meth:`_announcing`): it goes on above
        the objects whose announcement set it off and is ordered only with its
        own round (``engine/trigger_order.py``). Asked too before
        anything resolves (``resolve_top_of_stack``), so an object can never
        resolve with a choice it has not made.
        """
        while self.unannounced_triggers:
            item = self.unannounced_triggers.pop(0)
            if not any(entry is item for entry in self.stack):
                continue
            self._finish_announcement(
                item, targets_already_chosen=False, announced_at_cast=False,
            )

    def _finish_announcement(
        self, item, *, targets_already_chosen: bool, announced_at_cast: bool,
    ) -> None:
        """The rest of :meth:`_stack_push` once the object is on the stack: a
        triggered ability's mode and targets (CR 603.3c-d), then "whenever a
        player chooses one or more targets"."""
        self._choose_trigger_mode(
            item, targets_already_chosen=targets_already_chosen or announced_at_cast
        )
        # …and its non-modal twin: an ability whose printed noun phrase is a
        # *choice* the event did not make chooses it now, at the same moment
        # and for the same rule (CR 603.3d/601.2c). Both are reached only from
        # ``_stack_push`` — directly, or once the window the push was made in
        # closes — for the reason that method gives: it is the one place an
        # object goes on the stack, and a fire site that builds its own
        # StackItem still passes through there.
        #
        # *targets_already_chosen* is the one exception, and it is a rule
        # rather than a list of callers: an **activated** ability chose its
        # targets when it was activated (CR 602.2b, gated once in
        # `legality_abilities.activation_target_refusal`), and a **copy** inherits the
        # original's (CR 707.10). Both were announced with their targets
        # already made, so asking again would replace a choice a player has
        # made with one they have not.
        if not targets_already_chosen and not announced_at_cast:
            self._choose_trigger_targets(item)
        # "Whenever a player chooses one or more targets" (CR 601.2c / 602.2b /
        # 603.3d). Last, because this is the first moment the announcement is
        # whole: the ids are stamped, and a triggered ability's own choice has
        # been made if a non-interactive seat made it. Three exclusions, each a
        # rule rather than a list of callers:
        #
        # * a **copy** inherits the original's targets (CR 707.10) -- nobody
        #   chose anything, and the copy's re-aiming prompt announces for
        #   itself if its controller takes it;
        # * an object whose target prompt is **still owed** has not chosen yet;
        #   the answer announces (``_resolve_trigger_target``);
        # * an object the stack no longer holds was removed for having no legal
        #   target (CR 603.3d) or mode (CR 700.2b).
        #
        # There was a fourth: an entry trigger carrying its permanent spell's
        # announcement (*announced_at_cast*) said nothing here, "the cast
        # announced that choice". The cast no longer does — a permanent spell
        # is not targeted (``spell_targets_nothing``) — so this is where the
        # choice is announced, for the trigger, like any other trigger's.
        # ``announce_targets_chosen`` asks whether there is anything to
        # announce, so a trigger that carries the cast's fields and targets
        # nothing still says nothing.
        if (
            item is not None
            and not item.is_copy
            and self.announcement_choice_for(item) is None
            and any(waiting is item for waiting in self.stack)
        ):
            self.announce_targets_chosen(item)
        # A copy whose targets are still being decided announces nothing yet
        # (CR 707.10c; ``announce_copy_put_onto_stack``).
        if item is not None and item.announcement_owed:
            return
        # "Whenever a spell or ability is put onto the stack" (CR 601.2i,
        # 602.2b, 603.3) — every object, a copy included (CR 707.10: it is
        # created on the stack), once its announcement is whole. The same
        # two exclusions as above: a target prompt still owed announces when
        # it is answered (``_announce_answered_targets``), and an object the
        # stack no longer holds was removed as it was put there (CR 603.3d).
        if (
            item is not None
            and self.announcement_choice_for(item) is None
            and any(waiting is item for waiting in self.stack)
        ):
            self.announce_put_onto_stack(item)

    def announce_put_onto_stack(self, item) -> int:
        """"Whenever a spell or ability is put onto the stack" (Grip of Chaos):
        the event, with the object riding **by identity** under the key
        Psychic Battle's event uses (``stack_targets.TARGETS_CHOSEN_ITEM``) —
        several look-alikes may be on the stack at once and a ``StackItem``
        compares by value. Returns how many abilities triggered.

        Made for every object, targeted or not: "if it has a single target"
        is the card's intervening-if (CR 603.4), asked of the object by the
        trigger, and not a narrowing of the event. An ability that triggers
        here is itself put onto the stack and announced in its turn, which is
        no loop for Grip: its own trigger targets nothing, so its condition
        fails and it never triggers (CR 603.4).
        """
        from ..events import emit
        from ..stack_targets import TARGETS_CHOSEN_ITEM

        if item is None:
            return 0
        with self._announcing(item):
            return emit(
                self, "spell_or_ability_put_onto_stack", subject=None,
                **{TARGETS_CHOSEN_ITEM: item, "event_subject_player": item.caster_index},
            )

    @contextmanager
    def _announcing(self, item):
        """While *item* — a **triggered** ability being put on the stack — has
        its announcements made, what they set off belongs to the next round of
        CR 603.3b's process (``Game.announcing_trigger_round``):

            … Then the game once again checks for and performs state-based
            actions until none are performed, then abilities that triggered
            during this process go on the stack. This process repeats …

        Grip of Chaos's "whenever a spell or ability is put onto the stack"
        set off by Bladewing the Risen's entry trigger was offered in the same
        "order your triggered abilities" prompt as that trigger, so it could be
        put underneath the ability it reselects the target of. A spell's or an
        activated ability's announcements set off nothing of a later round:
        they are not triggered abilities being put on the stack.
        """
        if item is None or not is_triggered_object(item):
            yield
            return
        outer = self.announcing_trigger_round
        self.announcing_trigger_round = max(outer, int(item.trigger_round) + 1)
        try:
            yield
        finally:
            self.announcing_trigger_round = outer

    def announce_copy_put_onto_stack(
        self, item, *, chooser: int | None = None, chose: bool = False,
    ) -> None:
        """Make the announcements a copy pushed with ``announce=False`` owes,
        now that its controller has decided what its targets will be (CR
        707.10c) — once, for the targets it now has.

        "…becomes the target" (CR 603.2e) for each of them; "whenever a player
        chooses one or more targets" (Psychic Battle) only when *chose* — the
        controller changed a target, CR 707.10c's "may" taken (keeping the
        original's targets is the offer declined, and a copy inherits its
        targets, CR 707.10: nobody chose them); and "whenever a spell or
        ability is put onto the stack" (Grip of Chaos — CR 707.10: to copy a
        spell is to put a copy of it onto the stack), whose "if it has a single
        target" (CR 603.4) is so asked of the targets the copy has.

        A no-op for an object that owes nothing (announced already, or never
        held back), so every settle point may call it; and nothing for a copy
        the stack no longer holds.
        """
        if item is None or not getattr(item, "announcement_owed", False):
            return
        item.announcement_owed = False
        if not any(entry is item for entry in self.stack):
            return
        self._announce_targeting(item)
        if chose:
            self.announce_targets_chosen(item, chooser=chooser)
        self.announce_put_onto_stack(item)

    def spell_targets_nothing(self, item) -> bool:
        """Whether *item* is a **permanent spell that is not an Aura** — the
        one kind of stack object CR 115.1 leaves untargeted whatever its fields
        hold.

        CR 115.1a–d list what is targeted: an instant or sorcery spell, an
        Aura spell, an activated ability and a triggered ability. A creature,
        artifact, enchantment or planeswalker spell is none of them, and CR
        115.1d says when its entry trigger's target is chosen: "as the ability
        is put on the stack".

        This engine *names* that target as the permanent is cast (a standing
        convention; ROADMAP, "Entry triggers are stack objects"), so the spell
        carries it in the fields a targeted spell uses — and until this was
        asked, the cast **announced** it too. Every "becomes the target of a
        spell or ability" watcher heard about a target the spell does not
        have: at the wrong time (the trigger did not exist yet), as the wrong
        thing ("a spell", so Forsaken Wastes charged 5 life for a Man-o'-War),
        for a spell that was then countered and whose trigger never existed,
        and for a creature the trigger could not choose at all — with
        Cowardice out, a White Knight named for a Nekrataal went back to its
        owner's hand. Measured over the 32 permanents that name a permanent
        this way: 32, 32, 32 of 32 countered, and 128 of 128.

        Read by :meth:`_announce_targeting`, which emits off the stamped ids;
        :meth:`announce_targets_chosen` reaches the same answer through
        ``stack_targets.has_targets``. The trigger makes both announcements as
        it is pushed.
        """
        # One definition, and it is the reader's: ``stack_targets
        # .announcements`` answers "no targets" for exactly these objects, so
        # what is announced and what is read cannot disagree about them.
        from ..stack_targets import permanent_spell_targets_nothing

        return permanent_spell_targets_nothing(item)

    def _stack_push_object(self, item, *, announce: bool = True) -> None:
        """Put *item* on the stack, recording its target's identity (CR 601.2c),
        then announce the targeting (CR 603.2).

        Three statements, because the announcement is a *consequence* of the
        push and not of one way of reaching it. It used to sit at the end of the
        stamping below, which has three exits — a graveyard target, a caller
        that already knows the identities, and the ordinary one — so only the
        third announced. The second is the path **the web layer always takes**
        (it resolves `target_permanent_ids` off the wire), which meant Warden of
        the Woods never triggered in the running app and Forsaken Wastes would
        never have. Same shape as `become_tapped`: one event, several ways in,
        and the fire site wired into one of them.

        The stamping is :meth:`_stamp_stack_targets`, and the reason it is one
        place: a stack object is the engine's only structure that outlives the
        moment it was built. Everything else that holds a battlefield index
        uses it within the same step, where the list cannot renumber
        underneath it; a spell waits for priority to pass, for responses to be
        cast, and for everything above it to resolve — and any of those can
        take a permanent off the battlefield and shift every later slot down.

        So the index the caller chose is stamped into an id *here*, at the
        boundary, while it is still known to mean what it said. Resolution
        reads the id (``engine/handlers/_targets.py``) and only falls back to
        the index when the id no longer resolves, which is exactly the
        situation the old code was already in.

        **A graveyard target is stamped here too, and first.** Its index is a
        slot in a different list, so the battlefield stamping below answers a
        question the item never asked: Raise Dead naming graveyard slot 1 was
        handed the id of whatever permanent sat in battlefield slot 1."""
        self._stamp_stack_targets(item)
        self.stack.append(item)
        if announce:
            self._announce_targeting(item)

    def _stamp_stack_targets(self, item) -> None:
        """Record the identity behind every index *item* carries (CR 601.2c).

        Split out of :meth:`_stack_push_object` so the push and the
        announcement happen once each — see that method for what the three
        exits below cost. Nothing here appends to the stack.
        """
        # Each chosen mode of a multi-mode spell names its own object, so each
        # one is stamped here for the same reason the item's own target is: the
        # index was chosen while it still meant what it said, and this is the
        # boundary it stops being safe to hold one across (CR 400.7).
        for mode in item.chosen_modes:
            if mode.target_permanent_index is None or mode.target_permanent_id is not None:
                continue
            seat = mode.target_player_index
            if seat is None:
                seat = (
                    1 - item.caster_index if len(self.players) == 2
                    else item.caster_index
                )
            if 0 <= seat < len(self.players):
                mode.target_permanent_id = as_target_ids(self.permanent_ids_at(
                    seat, mode.target_permanent_index
                ))
        spec = graveyard_target_spec(
            item.card,
            compile_card_oracle(item.card),
            mode_index=item.chosen_mode_index,
            instruction=item.ability_instruction,
        )
        if spec is not None:
            stamped = self.stamp_graveyard_targets(
                self.graveyard_target_seat(item, spec), item.target_permanent_index
            )
            # A stamp the builder already took is kept where the slot names
            # nothing now: an activation whose own cost exiled the card it
            # targets (Cabal Surgeon, CR 601.2h after 601.2c) hands over the
            # card it named and no slot, so CR 608.2b finds the target gone —
            # where re-stamping from no slot would leave no target at all and a
            # handler free to scan for a stand-in.
            if stamped is not None or item.target_graveyard_card is None:
                item.target_graveyard_card = as_graveyard_stamps(stamped)
            # The slot was the announcement's address for the card, and the
            # stamp is the card: from here on a graveyard target is read off
            # the stamp (``Game.chosen_graveyard_index``), and the slot
            # channel — a battlefield's — holds nothing for it.
            item.target_permanent_index = None
            return
        if item.target_permanent_id is not None:
            # The caller already knows the identities. The web layer does: it
            # resolves `target_permanent_ids` off the wire and then used to
            # throw them away here, so a pair of targets on *two* battlefields
            # was re-derived against the single `target_player_index` and the
            # second slot resolved to whatever sat at that index on the wrong
            # board. Garruk, Savage Herald's -2 names one creature you control
            # and then anyone's, so it is the shape that needed this.
            #
            # **The seat is settled here too, and it is the same announcement.**
            # An id says which battlefield it is on and a seat does not, so an
            # announcement carrying ids and no seat is complete — but every
            # reader downstream defaults the missing seat to the *opponent*
            # (`_ability_execution_context`, `_resolve_card`), and
            # `handlers/_targets.pick_target_permanent` scopes the id lookup to
            # that player on purpose. So an id naming a permanent the activator
            # controls was rejected by the very resolver that was handed it,
            # and the fallback scan below it picked whichever permanent it met
            # first: War Barge, aimed by id at its controller's own creature,
            # gave islandwalk to an opposing one and logged success.
            #
            # This is the graveyard fix in ``_run_stack_item_resolution`` one
            # zone over (that one writes ``item.target_player_index =
            # first.seat`` off a stamped graveyard card, for the same reason),
            # and it is the web layer's own ``if len(seats) == 1`` rule read
            # back into the engine — which is why no game ever showed this and
            # every headless caller did.
            self._settle_announced_target_seat(item)
            return
        seat = item.target_player_index
        if seat is None:
            # The convention resolution uses when no target player was named.
            seat = 1 - item.caster_index if len(self.players) == 2 else item.caster_index
        if 0 <= seat < len(self.players):
            item.target_permanent_id = as_target_ids(
                self.permanent_ids_at(seat, item.target_permanent_index)
            )

    def announced_target_seat(self, permanent_ids) -> int | None:
        """The seat an announcement made by ``permanent_id`` already names, or
        None where the ids do not settle one (CR 601.2c, CR 400.7).

        An announcement made by id is complete: CR 400.7 makes the id one
        object for one stay on the battlefield, and that object knows whose
        battlefield it is on. A seat is not part of the choice, so a caller
        naming ids has nothing to add, and every headless caller — a test, the
        AI, ``scripts/run_duel.py`` — leaves it out.

        Downstream, though, "no seat named" is not "no seat". Every reader of
        ``StackItem.target_player_index`` supplies the *opposing* seat as its
        default (:meth:`_ability_execution_context`, ``_resolve_card``), and
        ``handlers/_targets.pick_target_permanent`` scopes its id lookup to
        exactly that player — on purpose, so that widening a target's
        battlefield is never something a resolver does by itself. Each half is
        defensible; together they discard the announcement. Every activated
        ability aimed by id at a permanent its own activator controls resolved
        against the wrong battlefield: the id was rejected by the resolver it
        was handed to, and the scan beneath it took whichever permanent it met
        first. War Barge gave islandwalk to an opposing creature and logged
        success, and 209 shipped cards did the same shape of thing.

        So the seat is *derived from the choice* rather than defaulted around
        it. One query, asked wherever an announcement's seat is being settled —
        :meth:`_stamp_stack_targets` for an item built with ids,
        ``_activate_onto_stack`` where the default is applied before the item
        exists, and **again as the object resolves**
        (``ResolutionTargetsMixin.resettle_announced_target_seats``): a target that
        changed controller while the object waited is still the target where
        CR 608.2b's gate judged it legal, and the seat it was announced on is
        no longer the one it stands on.

        None unless every live named permanent agrees, for the reason
        ``web/actions.py`` writes ``target_seat`` back only for a single-seat
        list: a pair of targets on two battlefields (Garruk, Savage Herald's
        -2) has no one seat to be on, and those resolutions read the ids
        anyway. Naming either seat would invent a fact about the other slot.
        """
        # An announcement's own argument as well as the field it is stamped
        # into, so either arity a caller holds (``as_target_ids``).
        listed = as_target_ids(permanent_ids) or []
        seats = {
            self.controller_index_of(permanent)
            for permanent in (
                self.permanent_by_id(permanent_id)
                for permanent_id in listed
                if isinstance(permanent_id, int)
            )
            if permanent is not None
        }
        return seats.pop() if len(seats) == 1 else None

    def stack_target_seat(self, item) -> int | None:
        """The seat an announcement that chose **only objects on the stack**
        already names: their controller (CR 112.2, CR 113.8), or None where
        the object chose anything else, nothing, or two objects two players
        control.

        :meth:`announced_target_seat`'s twin for the one kind of target that
        has no battlefield. A permanent's id names whose board it is on; a
        spell names the player who cast it, and that is the only player
        "Counter target spell. **Its controller** loses 3 life" can be about.
        Nothing said so. A stack target was recorded by identity
        (``StackItem.target_stack_item``) and the *seat* field beside it kept
        whatever it was sent — nothing from a headless caller, the opposing
        seat from the web route, which rides a default on every cast — so
        every resolution read "the player this is about" as the caster's
        opponent. Right whenever the spell being countered was an opponent's,
        which is nearly always, and that is how it survived: countering your
        own spell aimed its rider at the other player, and at three seats the
        rider landed on ``1 - caster`` whoever had cast the spell.

        Read off :func:`engine.stack_targets.chosen_targets`, never off
        ``target_player_index is None``: that field cannot tell a player the
        caster chose from a default that rode along, and the spec is what says
        which channel was a target. A spell that names a spell *and* a
        permanent or a player (Suffocating Blast's roles) answers None and
        keeps the seat its other target settled.

        The controller, not the owner (CR 108.3 is the owner; CR 112.2 makes
        the player who cast a spell its controller): a spell cast out of
        another player's pile is controlled by the seat that cast it.
        """
        from ..stack_targets import chosen_targets

        chosen = chosen_targets(self, item)
        if not chosen:
            return None
        seats: set[int] = set()
        for target in chosen:
            named = target.stack_item if target.kind == "stack" else None
            if named is None:
                return None
            seats.add(named.caster_index)
        if len(seats) != 1:
            return None
        seat = seats.pop()
        return seat if 0 <= seat < len(self.players) else None

    def _settle_announced_target_seat(self, item) -> None:
        """Write :meth:`announced_target_seat`'s answer onto *item*.

        Only where the item names no seat of its own: a caller that supplied
        one made a choice — a targeted **player** rides this same field, and so
        does the battlefield a bare index counts into — and overwriting it
        would be this method causing the class it exists to close.
        """
        if item.target_player_index is not None:
            return
        seat = self.announced_target_seat(item.target_permanent_id)
        if seat is not None:
            item.target_player_index = seat

    def announced_target_slot(self, permanent_ids) -> "tuple[int, int] | None":
        """The ``(seat, battlefield index)`` a **single** announced id names
        right now, or None where the ids do not name exactly one live
        permanent (CR 601.2c, CR 400.7).

        :meth:`announced_target_seat` with the slot beside it, for the one
        announcement the engine still carries to resolution as a slot: an
        **Aura spell's** enchant target. Every gate in that spell's arm of
        ``_validate_cast_targets`` — the enchant noun, "you control", the
        can't-be-enchanted and protection checks — is asked of
        ``permanent_at(seat, index)``, and so is the attachment at resolution;
        an announcement made by id reached none of them, so
        ``cast_from_hand(seat, "Holy Strength", target_permanent_ids=[id])``
        was refused "requires a target" for every Aura in the pool while the
        index spelling of the same choice was accepted. The id is the complete
        announcement (it names the object *and* its battlefield); the slot is
        derived from it here, once, at the moment the board and the id agree —
        which is what ``web/actions.py`` does for the wire and what a headless
        caller was left to do by hand.

        None for a list of several ids: an Aura has one target, and a caller
        naming two is announcing something this cannot settle.
        """
        named = [
            permanent_id for permanent_id in as_target_ids(permanent_ids) or []
            if isinstance(permanent_id, int)
        ]
        if len(named) != 1:
            return None
        permanent = self.permanent_by_id(named[0])
        if permanent is None:
            return None
        seat = self.controller_index_of(permanent)
        index = self.battlefield_index_of(permanent)
        if seat is None or index is None:
            return None
        return seat, index

    def _announce_targeting(self, item) -> None:
        """"…becomes the target of a spell or ability" (CR 603.2, Warden of the
        Woods).

        Announced here because here is where the targets exist: CR 601.2c has a
        spell choose them as it is cast and CR 602.2b an ability as it is
        activated, which is exactly the moment an object is put on the stack.
        Reading the ids the stamping above just settled means a target that has
        already changed hands or left is not announced against a stale slot.

        One event per targeted permanent, and the announcement carries *who* did
        the targeting — the narrowing "an opponent controls" is about the spell's
        controller, which nothing downstream could recover from the permanent.

        It carries **what** did the targeting for the same reason: "becomes the
        target of a spell" (Forsaken Wastes) is a narrower condition than
        "…of a spell or ability" (Warden of the Woods), and by the time the
        trigger resolves the object may have left the stack. `spell` / `ability`
        is the split `web/serialization.py` already draws for the client, asked
        of the one predicate rather than re-spelled here.

        And the targeting seat rides under ``event_subject_player`` as well as
        under its own key, because "**that spell's controller** loses 5 life"
        is the same seat read by the ordinary "that player" machinery — the key
        every frozen-seat reader in ``handlers/`` already asks for.
        """
        # CR 115.1: a permanent spell that is not an Aura is not targeted, so
        # nothing "becomes the target" of it — whatever it carries is its
        # entry trigger's, announced when that trigger is put on the stack.
        if self.spell_targets_nothing(item):
            return
        with self._announcing(item):
            self._announce_targeting_now(item)

    def _announce_targeting_now(self, item) -> None:
        """:meth:`_announce_targeting`'s announcements, inside its round."""
        from ..events import emit

        self._announce_targeted_player(item)
        for permanent_id in target_ids(item.target_permanent_id):
            if not isinstance(permanent_id, int):
                continue
            targeted = self.permanent_by_id(permanent_id)
            if targeted is None:
                continue
            emit(
                self, "self_becomes_target",
                subject=targeted,
                # The targeted permanent by **id**, under the key every
                # object-subject event freezes its object under — "return
                # **that creature** to its owner's hand" (Cowardice) is a
                # third-party observer that has no other way to name it, and by
                # resolution an index is not an identity (CR 400.7 / 603.10).
                # Stamped for every scope of this condition, because "that
                # creature" means the targeted one under all of them.
                event_subject_permanent_id=targeted.permanent_id,
                source_seat=item.caster_index,
                targeted_by="an ability" if item.is_ability else "a spell",
                # "…the target of **an Aura spell**" (Fugitive Druid). Which
                # class of spell, which the word above cannot say: the split it
                # draws is the one the client is shown, and a narrowing on the
                # spell's own subtype has to read the card. Carried rather than
                # re-derived at resolution, because by then the spell has left
                # the stack (CR 603.10).
                targeted_by_card=item.card,
                event_subject_player=item.caster_index,
            )

    def _announce_targeted_player(self, item) -> None:
        """The **player** half of CR 603.2's "becomes the target of".

        "Whenever **you** or a permanent you control becomes the target of a
        spell or ability an opponent controls, you may draw a card." (Rayne,
        Academy Chancellor.) CR 115.1 lets a spell or ability target a player,
        and until this existed the engine announced targeting for permanents
        alone — so a card watching for a seat being targeted had no event at
        all, however well its condition compiled.

        Announced beside the permanent loop rather than inside it, because the
        two are different objects: a seat has no ``permanent_id`` and nothing
        downstream could recover one. The seat rides its own key, so the filter
        that reads it cannot mistake it for a targeted permanent.

        **Whether the seat is a target at all is asked, never assumed.**
        ``target_player_index`` doubles as a *battlefield* index beside a
        permanent index — the hazard ``spell_targets`` documents one module over
        — so a removal spell aimed at a creature carries a seat that targets
        nobody. Read without the check, Rayne would draw a card off every spell
        an opponent pointed at anything. The compiled program is what answers:
        a spec whose kind is a player kind is a spell or ability that CR 601.2c
        actually let choose a face.

        Asked through ``stack_object_target_spec``, which answers for an
        **ability** as well as a spell — ``spell_targets`` deliberately returns
        nothing for one, because its caller (Reparations) watches casts. This
        condition says "a spell **or ability**", so the ability half is half the
        card.
        """
        from ..events import emit
        from ..targeting import (_PLAYER_TARGET_SPEC_KINDS, announces_a_target,
                                 stack_object_target_spec)
        from ..target_roles import ROLES_TARGET_KIND

        spec = stack_object_target_spec(item)
        if spec is not None and spec.get("kind") == ROLES_TARGET_KIND:
            # **A player named for one role of several is targeted too.**
            # "Target player gains control of target permanent you control"
            # (Donate), "…2 damage to target player or planeswalker" (Lunge),
            # "…creatures target player controls … creatures another target
            # player controls" (Cultural Exchange). The kind test below reads a
            # roles spec as "not a player kind" and returned, so no seat a
            # roles announcement named ever became the target of anything —
            # Rayne's controller, Donated a permanent, drew no card.
            #
            # Which seats are targets is ``stack_targets``' answer, the one
            # reader of what a stack object announced: one event per player
            # role, each its own seat where the announcement recorded several
            # (``target_roles.ROLE_SEATS``).
            from ..stack_targets import chosen_targets

            for target in chosen_targets(self, item) or ():
                if target.kind != "player" or target.channel != "role":
                    continue
                emit(
                    self, "self_becomes_target",
                    subject=None,
                    targeted_seat=target.seat,
                    source_seat=item.caster_index,
                    targeted_by="an ability" if item.is_ability else "a spell",
                    targeted_by_card=item.card,
                    event_subject_player=item.caster_index,
                )
            return
        # **A trigger's seat is a target only if its line printed one.** A fire
        # site may stamp a seat it already knows — the unblocked-attack site
        # stamps its controller's — and the kind table answers "player" for a
        # sentence that names its seat without targeting it: "…defending player
        # discards three cards" (Mindstab Thrull) announced its own controller
        # as targeted. ``announces_a_target`` is the record the trigger picker
        # asks before choosing (CR 603.3d), so the two agree.
        if item.ability_kind == "triggered" and not announces_a_target(
            item.ability_instruction
        ):
            return
        seat = getattr(item, "target_player_index", None)
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)):
            return
        if spec is None or spec.get("kind") not in _PLAYER_TARGET_SPEC_KINDS:
            return
        if spec.get("land_filter"):
            # Volcanic Eruption's "X target Mountains": the seat beside them is
            # a battlefield, exactly as it is above.
            return
        # **…and so it is beside any object this announcement named.** "Any
        # target" and "player or planeswalker" may choose a face *or* a
        # permanent, and when a permanent is chosen the seat field holds whose
        # battlefield it is on. ``stack_targets._read`` has said so since
        # Psychic Battle ("the permanent ids decide, and only without any is
        # the seat a chosen player") and this announcement never asked: a
        # Lightning Bolt aimed at a Grizzly Bears announced the Bears *and* its
        # controller, so Rayne, Academy Chancellor drew twice for one target.
        #
        # A spec that is a player and nothing else never reads an id as its
        # target (a fire site may thread a reference through the field), so
        # for that kind the seat is still the announcement.
        if spec.get("kind") != "player" and any(
            isinstance(permanent_id, int)
            for permanent_id in target_ids(item.target_permanent_id)
        ):
            return
        emit(
            self, "self_becomes_target",
            # No subject: a seat is not an object, and the two scopes that read
            # ``event.subject`` by identity must not be handed a permanent that
            # was never targeted.
            subject=None,
            targeted_seat=seat,
            source_seat=item.caster_index,
            targeted_by="an ability" if item.is_ability else "a spell",
            targeted_by_card=item.card,
            event_subject_player=item.caster_index,
        )

    def announce_targets_chosen(
        self, item, *, chooser: int | None = None,
        silently_for: str | None = None,
        newly_targeted: bool = False,
        at_random: bool = False,
    ) -> int:
        """"Whenever a player chooses one or more targets" (Psychic Battle) --
        the one announcement of CR 601.2c's choice, for every way a stack
        object comes to have targets. Returns how many abilities triggered.

        **One seam, because the choice has several ways in** and a fire site
        wired into one of them is this engine's recurring defect
        (``_stack_push_object``'s own docstring tells that story about
        ``self_becomes_target``). The callers are the whole census:

        * ``_stack_push`` -- a spell as it is cast (CR 601.2c), an ability as
          it is activated (CR 602.2b), and a triggered ability whose target its
          fire site bound or a non-interactive seat chose on the spot;
        * ``_resolve_trigger_target`` / ``_resolve_mode_choice`` -- a triggered
          ability whose controller was asked (CR 603.3d, CR 700.2b);
        * ``_resolve_copy_spell_target`` and ``copy_top_stack_spell`` -- a copy
          whose controller chose new targets (CR 707.10c);
        * ``change_target_spell_target`` and ``change_event_object_targets``
          -- a target changed by an effect (CR 115.7).

        **Whether there is anything to announce is asked, never assumed**:
        ``stack_targets.chosen_targets`` reads the object's own compiled
        program and printed line, so a creature spell with a stray index, a
        sacrificed cost, a "source of your choice" and an "up to one" naming
        nobody all announce nothing (CR 115.6: an object is targeted only if
        one or more targets have been chosen for it).

        *chooser* is the seat that made the choice, where it is not the
        object's controller (a changed target is chosen by whoever the changing
        effect says). *silently_for* is "Changing targets this way doesn't
        trigger abilities of permanents named <name>": the announcement still
        happens -- another card watching the same event would see it -- and
        carries the name that must not answer. The caller reads it off the
        changing permanent's **effective** card, so a copy of that permanent is
        silenced with it (CR 707.2); nothing here knows a name.

        The object rides the event **by identity** (``TARGETS_CHOSEN_ITEM``):
        CR 603.10's "looks back" for this event is at the object the targets
        were chosen for, several look-alikes may be on the stack at once, and a
        ``StackItem`` compares by value.

        *newly_targeted* is the other announcement the same moment owes, for
        every caller but the first: "…**becomes the target** of a spell or
        ability" (CR 603.2, Skulking Ghost). ``_stack_push_object`` announces
        that for the targets an object is *pushed* with, and until this seam
        existed that was the only site — so a triggered ability whose
        controller was asked for its target, a copy that was re-aimed and a
        spell Deflection moved all pointed at a permanent that never heard
        about it. A Man-o'-War entering from a graveyard bounced a Skulking
        Ghost it should have made its controller sacrifice. Same shape as the
        defect that method's docstring records, one layer up: one event,
        several ways in, the fire site wired into one of them.

        *at_random* is a target **no player chose**: "reselect its target at
        random" (Grip of Chaos). CR 115.7 is about effects that let a *player*
        change or choose targets, and Psychic Battle listens for "a player
        chooses one or more targets" — a draw the effect makes is neither. The
        new target still "becomes the target" (CR 603.2, *newly_targeted*);
        only the choice is not announced.
        """
        from ..events import emit
        from ..stack_targets import TARGETS_CHOSEN_ITEM, TARGETS_CHANGED_SILENTLY_FOR, has_targets

        if item is None:
            return 0
        if newly_targeted:
            self._announce_targeting(item)
        if at_random:
            return 0
        # ``has_targets`` is also what answers for a permanent spell that is
        # not an Aura: it chose none (CR 115.1), though it carries the one its
        # entry trigger will choose.
        if not has_targets(self, item):
            return 0
        seat = item.caster_index if chooser is None else chooser
        payload = {
            TARGETS_CHOSEN_ITEM: item,
            # "That player" under this event is the seat that chose.
            "event_subject_player": seat,
        }
        if silently_for is not None:
            payload[TARGETS_CHANGED_SILENTLY_FOR] = silently_for
        with self._announcing(item):
            return emit(self, "player_chooses_targets", subject=None, **payload)

    def record_no_target_named(self, item) -> None:
        """Write down that *item*'s announcement chose **zero targets**, which
        "up to one target …" allows (CR 601.2c; CR 115.6: the object is then
        not targeted).

        The one writer of ``oracle_types.NAMED_NO_TARGET`` — see that
        constant for why the empty target fields cannot carry the fact. Three
        callers, each a way an "up to" announcement comes to name nobody:

        * ``_arm_trigger_target_choice`` — a triggered ability going on the
          stack with nothing it could legally name (CR 603.3d does not remove
          it: zero is a choice that can be made);
        * ``_resolve_trigger_targets`` — its controller was offered targets and
          named none;
        * :meth:`_note_empty_announcement` — an activated ability announced
          with none.

        Nothing is announced: "becomes the target" and "chooses one or more
        targets" are both about a target that was chosen.
        """
        from ..oracle_types import NAMED_NO_TARGET

        if item is None:
            return
        item.choices[NAMED_NO_TARGET] = True

    def _note_empty_announcement(self, item) -> None:
        """An **activated** ability whose printed target is "up to …" and that
        was announced naming nothing has named nobody (CR 602.2b through
        CR 601.2c) — record it, so its resolution does not go looking.

        The activated half of the record :meth:`record_no_target_named` keeps,
        and the half with no prompt behind it: an activation's targets arrive
        with the action, so "none arrived" is the whole announcement. Until
        this was written the resolution could not tell that from a target it
        was expected to find, and the scan under every single-target handler
        found one — the +1 of Basri Ket, of Basri, Devoted Paladin and of
        Garruk, Unleashed put its counter or its +3/+3 on a creature with
        shroud while the picker, correctly, offered nothing.

        Bounded three ways, each the safe direction:

        * ``item.activated`` — a triggered ability's announcement is made by
          the push (``_choose_trigger_targets``), which knows whether it was
          offered anything; a **spell** is left alone because every "up to"
          spell in the pool prints a *count* and so resolves through the
          several-slot readers, which already treat nothing named as nothing
          chosen (``tests/engine/test_up_to_names_nobody_census.py`` pins all
          of them);
        * the printed target must be "up to" — an ability that owes a target
          and names none is the activation gate's question, not this one's;
        * ``stack_targets.chosen_targets`` must answer the empty tuple — None
          is "this engine cannot say", and is not nobody.
        """
        from .stack.trigger_targets import _target_is_up_to
        from ..stack_targets import chosen_targets

        if item is None or not getattr(item, "activated", False) or item.is_copy:
            return
        instruction = item.ability_instruction
        if instruction is None or not _target_is_up_to(instruction.payload):
            return
        if chosen_targets(self, item) != ():
            return
        self.record_no_target_named(item)
