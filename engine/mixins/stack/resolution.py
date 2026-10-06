"""Resolving the top of the stack (CR 608), and putting triggered abilities
onto it (CR 603).

The other end of the pipeline: whatever ``casting`` and ``activation`` queued
comes back here to be executed, its targets re-checked for legality
(CR 608.2b — a spell whose every target is illegal is countered), and its card
put wherever it goes afterwards.
"""

from __future__ import annotations

from contextlib import contextmanager

from ...auras import aura_enchant_clause
from ...cast_costs import (CAST_COST_DISCARD_MANA_VALUE, KICKED,
                           KICKED_WITH, buyback_paid, kicked,
                           kickers_paid)
from ...cast_timing import CAST_AT_INSTANT_SPEED
from ...classifier import CardClassification, classify_card
from ...enter_effects import copy_on_enter_type
from ...events import emit
from ...extra_triggers import additional_triggers
from ...faces import whole_card
from ...game_types import OracleExecutionContext, OracleStateMachine, StackItem
from ...handlers.control_flow import evaluate_condition
from ...models import CardDefinition, Permanent
from ...oracle import OracleInstruction, compile_card_oracle
from ...modal_triggers import ENTRY_TRIGGER_CONDITIONS, modal_trigger_modes
from ...resumption import run_resumable
# Both owned by ``engine/targeting.py``: two callers ask whether a compiled
# program announced a target — this picker (CR 603.3d) and the ``may``
# handler deciding whether an offer may rebind the target its own trigger
# announced — and a second copy of the word list is how the two would come
# to disagree about what counts as an announcement.
from ...targeting import ANNOUNCED_PLAYER_WORDS, announces_a_target

#: How a printed controller narrowing reaches the target spec. A key here is a
#: narrowing `legality._enumerate_targets` performs; a controller word absent
#: from it is one the enumerator cannot answer, and
#: `_choose_trigger_targets` declines rather than offering a wider list than
#: the card prints.
_CONTROLLER_SPEC_FLAGS = {
    "you": "own_only",
    "opponent": "opponent_only",
    "defending_player": "defending_player_only",
    # "...target creature or planeswalker **that player** controls" (Chandra's
    # Incinerator); "destroy up to one target artifact or enchantment **that
    # player** controls" (Feline Sovereign). A seat the *event* picked, which
    # `_enumerate_targets` narrows on exactly as it narrows the defending
    # player's — given the seat, which the fire site froze into the trigger's
    # context (CR 603.10) and `_that_player_seat` below reads back.
    #
    # Absent from this table the picker declined the ability entirely, so the
    # target was never announced and the handler fell through to "the first
    # permanent on the default opponent's battlefield that matches". At two
    # seats that is a legal permanent nobody chose; at three it is the wrong
    # board, where the printed narrowing then matches nothing and the ability
    # silently does nothing at all.
    "that_player": "that_player_only",
}


def _target_filter_controller(payload) -> str | None:
    """The ``controller`` word of an instruction's printed target phrase.

    Walked rather than read off one key because the phrase is carried in two
    shapes: a destroy lifts it to the payload's top level, while a damage
    instruction keeps it under ``targets.filter`` — and a ``may`` or a
    ``sequence`` wraps either of them. One walk rather than a list of the
    kinds, for the reason every registry in this engine gives.
    """
    if isinstance(payload, dict):
        described = payload.get("filter")
        if isinstance(described, dict) and described.get("controller"):
            return described["controller"]
        if payload.get("controller"):
            return payload["controller"]
        for value in payload.values():
            found = _target_filter_controller(value)
            if found is not None:
                return found
        return None
    if isinstance(payload, (list, tuple)):
        for entry in payload:
            found = _target_filter_controller(entry)
            if found is not None:
                return found
        return None
    inner = getattr(payload, "payload", None)
    return None if inner is None else _target_filter_controller(inner)


def _controller_narrowing_is_in(spec: dict, instruction) -> bool:
    """Whether *spec* carries the controller narrowing *instruction* prints."""
    controller = _target_filter_controller(getattr(instruction, "payload", None))
    if controller is None:
        return True
    # "...put a rust counter on each artifact **target opponent** controls."
    # (Corrosion.) Here the controller word *is* the announcement rather than a
    # narrowing of a list of objects: the spec picks a seat, the enumerator
    # offers seats, and the sweep over that seat's permanents is the
    # resolution's own work (CR 611.2c fixes the set as the ability resolves).
    # Read as a narrowing it looked for a spec flag no seat picker carries, and
    # so declined the one card the pronoun is printed on.
    if controller in ANNOUNCED_PLAYER_WORDS and spec.get("kind") == "player":
        return True
    flag = _CONTROLLER_SPEC_FLAGS.get(controller)
    return bool(flag and spec.get(flag))


def _target_is_up_to(payload) -> bool:
    """Whether an instruction's printed target is "**up to** one target …".

    Walked for :func:`_target_filter_controller`'s reason: the ``targets``
    description sits under a ``sequence``'s steps or a ``may``'s body as often
    as at the top. CR 601.2c lets such an announcement name **zero** targets,
    so "no legal target" is a choice that can be made rather than CR 603.3c's
    "no legal choices can be made" — Gilded Drake's "exchange control of this
    creature and up to one target creature an opponent controls" against an
    empty board still resolves, and its "if you don't or can't make an
    exchange, sacrifice this creature" is the whole point of that.
    """
    if isinstance(payload, dict):
        targets = payload.get("targets")
        if isinstance(targets, dict) and targets.get("quantifier") == "up_to":
            return True
        return any(_target_is_up_to(value) for value in payload.values())
    if isinstance(payload, (list, tuple)):
        return any(_target_is_up_to(entry) for entry in payload)
    inner = getattr(payload, "payload", None)
    return False if inner is None else _target_is_up_to(inner)


class StackResolutionMixin:
    def counter_stack_object(self, item: StackItem) -> None:
        """CR 701.6a: cancel *item*, taking it off the stack, and announce it.

        The one place a spell or an ability is **countered**. It was three —
        ``handlers/stack.counter_top_stack_spell``, ``counter_stack_ability``
        and the pay-or-be-countered prompt's declined branch — each spelling out
        its own ``stack.remove``, which is the ``become_tapped`` problem again:
        anything that has to happen when an object is countered had three places
        to be forgotten, and "whenever a spell you've cast is countered" was
        forgotten in all three.

        **Removal by identity.** ``StackItem`` is a plain dataclass and a deck
        repeats one immutable ``CardDefinition`` per copy, so two casts of the
        same card with the same target compare **equal** — ``list.remove`` would
        take whichever sits lower on the stack. The same look-alike the control
        seam bans ``battlefield.remove`` for, and ``exile_target_spell`` one
        module over already walks the stack by ``is`` for it.

        **What is not a counter.** Two neighbouring paths cancel a resolution
        and deliberately do not come here, because CR does not call either one
        countering: a spell **exiled** off the stack (``exile_target_spell`` —
        "can't be countered" does not stop it), and CR 608.2b's spell whose
        every target has become illegal, which "doesn't resolve" and is
        "removed from the stack and, if it's a spell, put into its owner's
        graveyard" without the word ever appearing. That second one reads
        "countered by the rules" in this engine's log, which is the pre-M2010
        wording; the log line is left alone and the announcement is not made,
        because Multani's Presence must not draw off a fizzle.

        The announcement is made for a **spell** only. ``is_ability`` is CR
        113.3's question and the pool prints no trigger watching a countered
        ability; a copy is excluded because CR 707.10 puts it on the stack
        without it ever having been *cast*, which is the word the only condition
        watching this event prints.

        Where the card goes afterwards stays the caller's business: CR 701.6a's
        graveyard, an "exile it instead" rider, Memory Lapse's library. This is
        the cancel, not the destination.
        """
        for index, obj in enumerate(self.stack):
            if obj is item:
                del self.stack[index]
                break
        if item.is_ability or item.is_copy:
            return
        emit(
            self, "your_spell_countered",
            seat=item.caster_index, subject=item.card,
        )

    def _bin_spell_card(
        self, owner, card: CardDefinition, *, exile_instead: bool, verb: str,
        hand_instead: bool = False,
    ) -> None:
        """Where a spell's card goes as it leaves the stack (CR 608.2n): the
        owner's graveyard, unless the cast carried the "if that spell would be
        put into your graveyard, exile it instead" rider — which covers
        resolving and being countered alike, so every leave-the-stack site
        routes through here rather than deciding for itself.

        *hand_instead* is CR 702.27a's second static ability: "If the buyback
        cost was paid, put this spell into its owner's hand instead of into that
        player's graveyard **as it resolves**." A parameter rather than a
        question this function asks, because the seam is shared with the
        countering path and that rule's "as it resolves" excludes it — a bought
        back spell that is countered goes to the graveyard like any other. Only
        the resolution site passes it, off ``cast_costs.buyback_paid``.

        Through ``put_card_into_hand``, so CR 903.9b is asked at the one place
        it has to be asked (CLAUDE.md's "every put this card into a hand goes
        through" seam) — a commander bought back returns to the command zone if
        its owner says so.

        **Order when two of these apply.** ``exile_instead`` covers two things:
        an opponent's "exile it instead of putting it into its owner's
        graveyard" rider, and CR 724.1b's end-the-turn exile, which is not a
        replacement at all — it removes the object from the stack, so the
        resolution buyback's clause is about never finishes and the exile has to
        win. Between buyback and the *rider*, CR 616.1 makes it the affected
        object's controller's choice, and the buyback payer is that controller
        and has just paid for the return; taking it for them is the only reading
        that does not make the payment pointless. The end-the-turn half reaches
        here with ``hand_instead`` False, because the resolution never got as
        far as asking.
        """
        # CR 709.4: the *spell* was one half of a split card and the card that
        # leaves the stack is the whole of it. ``card`` stays the half for the
        # log lines — that is the spell that resolved — and ``leaving`` is what
        # lands in a zone. The hand and graveyard seams ask the same question
        # themselves; exile has no seam, so it is asked here.
        leaving = whole_card(card)
        if hand_instead and not exile_instead:
            arrived = self.put_card_into_hand(owner, leaving)
            if arrived:
                self.log.append(
                    f"{card.name} {verb} and returned to its owner's hand "
                    "(buyback) instead of going to the graveyard"
                )
            return
        if exile_instead:
            owner.exile.append(leaving)
            self.log.append(f"{card.name} {verb} and was exiled instead of going to the graveyard")
        else:
            self.put_card_into_graveyard(owner, leaving)
            self.log.append(f"{card.name} {verb} and moved to graveyard")

    def _default_opposing_seat(self, caster_index: int) -> int:
        """The seat a triggered ability affects when nothing chose one.

        A trigger that prints "target player" now chooses one where CR 603.3d
        puts the choice — :meth:`_choose_trigger_targets`, as the ability goes
        on the stack — and this is what is left underneath: an ability whose
        seat the *firing event* named rather than its controller, and one whose
        printed line names no player at all but whose effect still has to reach
        somebody ("target opponent loses that much life" on Vito, whose lowering
        records no target description for the picker to narrow).

        Where nothing chose, that someone was ``1 - caster_index``: right for
        two players, and at seat 2 of a three-handed game ``players[-1]``, which
        is the caster itself. A player is never their own opponent (CR 102.3),
        so Vito would have drained himself.

        It is also the **answer a non-interactive seat gives the new picker**
        (``_default_trigger_target``), which is what makes announcing a target a
        change to what a player is asked and to nothing else.

        The first living opponent in seat order instead. The old answer is kept
        as the fallback for a table with no living opponent left, so nothing
        that reaches here mid-teardown changes.
        """
        opponents = self.opponents_of(caster_index)
        if opponents:
            return opponents[0]
        fallback = 1 - caster_index
        return fallback if 0 <= fallback < len(self.players) else caster_index

    def _enqueue_triggered_ability(
        self,
        *,
        controller_index: int,
        source_permanent: Permanent | None = None,
        card: CardDefinition | None = None,
        instruction: OracleInstruction | None = None,
        effect_kind: str | None = None,
        ability_text: str | None = None,
        target_player_index: int | None = None,
        target_permanent_index: int | None = None,
        # A trigger that acts on the object its event was about ("destroy that
        # planeswalker") is stamped with that object's id by the fire site. The
        # index is unstable across a removal; the id is the identity (CR 400.7).
        target_permanent_id: int | None = None,
        trigger_context: dict | None = None,
        # CR 603.7d's frozen scratchpad -- see ``StackItem.captured_results``.
        captured_results: dict | None = None,
        hook_key: str | None = None,
        hook_event: dict | None = None,
        # CR 107.3m: an entry trigger that refers to X uses the X chosen for
        # the spell that became its permanent. None for every other trigger.
        x_value: int | None = None,
        # The target fields above were announced by the permanent spell this
        # trigger's source was cast as, not chosen for this object -- see
        # ``_stack_push``.
        announced_at_cast: bool = False,
    ) -> None:
        """Put a single triggered ability onto the stack as a StackItem (CR 603.3).

        Mirrors the attack/block trigger model (declare_attackers_step._fire_attack_triggers).
        The trigger resolves later through resolve_top_of_stack — never inline at the
        moment it fires. ``card`` defaults to the source permanent's card (used as the
        stack object's display name).

        Mid-cast, it is *held* instead — see ``deferring_triggers``. The check
        belongs on this end rather than on the batch above it because the batch
        is not the only fire site: a dies-trigger enqueues from
        ``_permanent_to_graveyard`` one ability at a time, and a creature
        sacrificed to pay a cost dies exactly there."""
        if self.deferred_triggers is not None:
            self.deferred_triggers.append(dict(
                controller_index=controller_index,
                source_permanent=source_permanent,
                card=card,
                instruction=instruction,
                effect_kind=effect_kind,
                ability_text=ability_text,
                target_player_index=target_player_index,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
                trigger_context=trigger_context,
                captured_results=captured_results,
                hook_key=hook_key,
                hook_event=hook_event,
                x_value=x_value,
                announced_at_cast=announced_at_cast,
            ))
            return
        stack_card = card if card is not None else (source_permanent.card if source_permanent is not None else None)
        if stack_card is None:
            return
        # CR 603.2d: "rather than simply determining that such an ability has
        # triggered, determine how many times it should trigger, then that
        # ability triggers that many times" (Sanctum of All). Counted here
        # because this is the moment an ability triggers — one site, so a fire
        # site added later is covered by construction, and counting once rather
        # than recursing is what the rule's "doesn't invoke itself repeatedly"
        # asks for. Each instance is its own stack object and so chooses its own
        # targets; it is not a copy (CR 707), which would inherit them.
        for _ in range(1 + additional_triggers(
            self, source_permanent, controller_index,
            delayed=effect_kind == "triggered_delayed",
        )):
            self._stack_push(
                StackItem(
                    card=stack_card,
                    caster_index=controller_index,
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_id,
                    x_value=x_value,
                    ability_instruction=instruction,
                    ability_effect_kind=effect_kind,
                    source_permanent=source_permanent,
                    ability_text=ability_text,
                    trigger_context=trigger_context,
                    captured_results=dict(captured_results or {}),
                    hook_key=hook_key,
                    hook_event=hook_event,
                ),
                announced_at_cast=announced_at_cast,
            )

    def _ability_execution_context(self, item: StackItem) -> OracleExecutionContext:
        """The context an ability on the stack runs in.

        One builder because CR 603.4 asks its condition **twice** — once as the
        ability triggers (:meth:`trigger_condition_holds`, from ``_stack_push``)
        and once as it resolves — and the two answers have to be about the same
        reading of the same object. A second construction here would be two
        contexts that can disagree about what "you" and "that creature" mean,
        which is exactly the shape of bug the rule's own wording invites: it is
        the *same* condition, asked at two moments.
        """
        target_idx = (
            item.target_player_index
            if item.target_player_index is not None
            else self._default_opposing_seat(item.caster_index)
        )
        return OracleExecutionContext(
            caster=self.players[item.caster_index],
            target=self.players[target_idx],
            card=item.card,
            target_permanent_index=item.target_permanent_index,
            target_permanent_id=item.target_permanent_id,
            # The graveyard half of the same announcement, for a roles
            # instruction whose slots sit in two zones (Goblin Welder). Every
            # other graveyard target reads the index this method has already
            # re-located; that one needs the stamp itself, because the index
            # cannot say whose pile a slot counts into.
            target_graveyard_card=item.target_graveyard_card,
            x_value=item.x_value,
            source_permanent=item.source_permanent,
            ability_text=item.ability_text,
            stack_target=item.target_stack_item,
            trigger_context=item.trigger_context,
            choices=item.choices,
            # CR 603.7d: a delayed ability resolves with the scratchpad
            # its creating effect had, because the step that recorded
            # what "that creature" names ran a turn ago. Empty for every
            # other trigger, which is the scratchpad they already had.
            results=dict(item.captured_results),
        )

    def trigger_condition_holds(self, item: StackItem) -> bool:
        """CR 603.4's **first** check: does this ability trigger at all?

        "When/Whenever/At [trigger event], **if [condition]**, [effect]" is
        asked when the trigger event occurs, and the ability "triggers only if
        it is [true]; otherwise it does nothing" — it never reaches the stack.
        The rule then asks the same condition again on resolution, which is the
        read in ``_resolve_ability``.

        Only that second half existed, which made the outcome right for the
        wrong reason: a false condition produced an ability that went on the
        stack, sat there and then removed itself. That is observable rather
        than untidy — the object can be countered, every player has to pass
        priority on it, and anything watching for an ability being put onto the
        stack sees one that never triggered. Spectral Bears and Wall of
        Caltrops are the two it is easiest to watch happen on.

        Asked at ``_stack_push``, which is *the* one place an object goes on
        the stack, rather than at a fire site: five fire sites (the upkeep,
        draw and end steps, and the two delayed-trigger scans) had each grown
        their own copy of the check and the rest had none — which is why Chrome
        Replicator's entry trigger correctly never announced while Spectral
        Bears' attack trigger always did. The seam is the only place the next
        fire site cannot forget.

        Scoped by the **payload key**, which is a trigger's alone: no activated
        ability and no spell instruction in the pool carries ``intervening_if``
        because the grammar lowers it only under a trigger, so the presence of
        the key is itself the discriminator and no second list of kinds is
        needed. A **copy** is exempt (CR 707.10: copying an ability on the
        stack is not that ability triggering, so 603.4's first check either has
        already happened or never applied).
        """
        if item is None or item.is_copy:
            return True
        instruction = item.ability_instruction
        if instruction is None:
            return True
        gate = (instruction.payload or {}).get("intervening_if")
        if gate is None:
            return True
        if evaluate_condition(self, self._ability_execution_context(item), gate):
            return True
        self.log.append(
            f"{item.card.name} didn't trigger: its condition wasn't met (CR 603.4)"
        )
        return False

    def _choose_trigger_mode(
        self, item: StackItem, *, targets_already_chosen: bool = False
    ) -> None:
        """Choose *item*'s mode and that mode's targets, as it goes on the
        stack (CR 700.2b / CR 603.3c-d).

        The rule is explicit about **when**: the modes of a modal triggered
        ability are chosen "as part of putting that ability on the stack", and
        CR 603.3d then routes the rest through CR 601.2c, which is where the
        targets are chosen. So the two decisions are one decision, made here,
        at the one moment they are allowed — and not, as this engine did until
        now, at resolution, where nothing collects a target and a targeted mode
        would run against a target nobody picked.

        CR 700.2b's other half is the empty case: "If no mode is chosen, the
        ability is removed from the stack." A mode with no legal target can't
        be chosen, so an ability whose every mode is in that state never
        resolves — it is taken back off the stack here rather than resolving
        into a no-op, which is a different observable game state (nothing
        responds to it, and nothing counts it as having resolved).

        The offered list is ``legality.trigger_mode_options``, which is also
        what decides the empty case one line above: the gate and the picker are
        one call, not two tables.
        """
        instruction = item.ability_instruction
        if not modal_trigger_modes(instruction):
            return
        options = self.trigger_mode_options(
            item.caster_index, item.card, instruction, item.source_permanent,
        )
        if not options:
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "no mode could be chosen (700.2b)"
            )
            return
        self.arm_pending_choice(
            "mode_choice", item.caster_index,
            card_name=item.card.name,
            labels=[option["label"] for option in options],
            _options=tuple(options),
            _trigger_item=item,
            # An object announced with its targets already made — a copy
            # (CR 707.10), or an activated modal ability (CR 602.2b) — keeps
            # them, so the mode picker must not ask again. Same rule as the twin
            # flag one method up: asking again replaces a choice a player has
            # made with one they have not.
            #
            # Dwarven Armorer used to be the card that showed why, and no longer
            # reaches here at all: "a +0/+1 counter **or** a +1/+0 counter" is
            # not modal (CR 700.2 needs a bulleted list), so it is chosen while
            # the effect is applied (CR 608.2d) — see
            # ``modal_triggers.MODAL_HEAD_KEY``. A printed modal *activated*
            # ability is rewritten one ability per bullet before it compiles,
            # so the flag's live reader today is the copy.
            _keep_targets=targets_already_chosen,
        )

    #: Object target kinds :meth:`_choose_trigger_targets` picks for.
    #: Permanents on the battlefield: the kinds whose printed noun phrase can
    #: *narrow* ("target artifact defending player controls"), so a fire site
    #: that names one by position rather than by choice is naming something the
    #: card may not permit. A spell on the stack and a card in a zone reach the
    #: resolution through their own paths and are left exactly as they were.
    _CHOOSABLE_TRIGGER_TARGET_KINDS = frozenset({
        "permanent", "creature", "artifact", "enchantment", "land",
        "planeswalker",
    })

    #: ...and the kinds whose candidates include a **player's face**. The note
    #: above used to say a player "is left exactly as it was", and that was the
    #: whole gap: a trigger printing "target opponent" announced nothing, so the
    #: resolution fell through to ``_default_opposing_seat`` — the first living
    #: opponent. Right in a two-player game by coincidence, because there is
    #: only one of those; unchosen at three seats, where CR 601.2c says the
    #: ability's controller picks and the engine picked for them.
    #:
    #: ``divided`` is deliberately not here. "Divided as you choose among any
    #: number of targets" announces a *set* with an assignment attached
    #: (CR 601.2d), which is the pile-division prompt rather than this one, and
    #: no trigger in the pool prints it.
    _CHOOSABLE_TRIGGER_PLAYER_KINDS = frozenset({
        "player", "player_or_planeswalker", "any",
    })

    def _choose_trigger_targets(self, item: StackItem) -> None:
        """Choose *item*'s target as it goes on the stack (CR 603.3d/601.2c).

        The non-modal twin of :meth:`_choose_trigger_mode`, and it exists for
        the same reason at the same moment: a triggered ability chooses its
        targets as it is put on the stack, not when it resolves.

        Most fire sites in this engine already name the object their event was
        about — "destroy **that Wall**" (Battering Ram) is bound by the block
        that fired it, and CR 603.3d has nothing to choose. This is for the
        ability whose printed noun phrase is a *choice* the event does not
        make: Floral Spuzzem's "target artifact defending player controls" is
        any of the defender's artifacts, and the fire site had been stamping
        the attacking creature's own slot into the target field — so the
        ability resolved against whatever permanent sat at that index on the
        *controller's* battlefield.

        Three ways out, all of them the safe direction:

        * the ability names no target — nothing to choose;
        * the fire site already bound one (``target_permanent_id`` for an
          object, ``target_player_index`` for a seat) — the event made
          the choice and CR 603.3d has none left to make;
        * no legal target exists — CR 603.3c removes the ability from the
          stack rather than resolving it into a no-op, which is the same rule
          :meth:`_choose_trigger_mode` applies to a mode that cannot be chosen.

        The candidates come from ``_enumerate_targets``, the one list the web
        picker is handed and the one list the answer is checked against.

        A **player** is chosen here on the same rule and through the same list,
        and it is the half this method did not have. What gates it is
        :func:`announces_a_target` rather than the spec alone: the spec comes from
        a kind table that answers "player" for a whole family of instructions,
        including the ones whose seat the firing event already fixed.
        """
        from ...targeting import derive_instruction_spec

        instruction = item.ability_instruction
        if instruction is None or modal_trigger_modes(instruction):
            return
        if item.target_stack_item is not None:
            return
        # A stamped target means the event made the choice — **unless what the
        # fire site stamped is the ability's own source**. The two combat fire
        # sites that announce a permanent's trigger about itself thread the
        # permanent's own controller and slot through ``target_player_index`` /
        # ``target_permanent_index`` so that ``resolve_own_combatant`` can find
        # it again (Mijae Djinn removes *itself* from combat, Ydwen Efreet
        # *itself* from the block). That is a reference, not a choice, and this
        # method could not tell the two apart: three shipped cards printing
        # "target" had CR 603.3d's choice skipped and resolved against the
        # attacker or blocker instead. Sidar Jabari found nothing to tap
        # (its "defending player controls" narrowing correctly refused itself),
        # Seasoned Marshal tapped **itself**, and Elite Javelineer dealt its 1
        # damage to **itself**.
        #
        # ``announces_a_target`` is the second half and the safe direction: it
        # is the lowering's own record that the printed line said the word, so
        # a trigger the same fire site announces about an object the *event*
        # named — Mindbender Spores' "put four fungus counters on **that
        # creature**" — keeps the reference it has always had. Asked only in
        # this branch, never as a general gate: for an unstamped trigger the
        # record is evidence rather than proof, and a False there would take a
        # real target away (Man-o'-War's bounce answers False today).
        if item.target_permanent_id is not None and not (
            item.source_permanent is not None
            and item.target_permanent_id == item.source_permanent.permanent_id
            and announces_a_target(instruction)
        ):
            return
        spec = derive_instruction_spec([instruction])
        if spec is None:
            return
        picks_a_player = spec.get("kind") in self._CHOOSABLE_TRIGGER_PLAYER_KINDS
        if (
            not picks_a_player
            and spec.get("kind") not in self._CHOOSABLE_TRIGGER_TARGET_KINDS
        ):
            return
        if picks_a_player:
            # The printed line has to have said "target". See
            # :func:`announces_a_target`: the spec's "player" may be a kind
            # table's default over a sentence whose seat the event already
            # named, and offering that is a prompt whose answer nothing reads
            # — or, for a phrase the default does not narrow, a prompt
            # offering a seat the card excludes.
            if not announces_a_target(instruction):
                return
            # ...and the fire site must not have bound the seat already, which
            # is the player half of the ``target_permanent_id`` early-out above:
            # a fire site that stamps the seat its event was about has made the
            # choice, and asking again would replace it with one nobody made.
            if item.target_player_index is not None:
                return
        # **Only pick what the enumerator can narrow.** A printed noun phrase's
        # controller reaches the spec as a flag ("you control" → `own_only`,
        # "an opponent controls" → `opponent_only`, "defending player controls"
        # → `defending_player_only`); one that did not is one the enumerator
        # would ignore, and offering a wider list than the card prints is the
        # single thing a picker must never do.
        #
        # "…that **that player** controls" (Chandra's Incinerator) is that
        # case, and deliberately so: the seat is one the *event* picked, known
        # only to the handler holding the trigger's context, which does the
        # narrowing itself as it resolves. Left to this picker it would offer
        # every permanent on the board and stamp the first.
        if not _controller_narrowing_is_in(spec, instruction):
            return
        spec = dict(spec)
        # "Defending player controls" is a seat the *combat* knows and the
        # enumerator does not, so it travels with the spec. The fire site froze
        # it into the trigger's context when the ability triggered (CR 603.10),
        # which is the same key the attack triggers already use.
        defending = (item.trigger_context or {}).get("trigger_defending_player_index")
        if isinstance(defending, int):
            spec["defending_player_index"] = defending
        # "That player" travels the same way and for the same rule, read
        # through the *same key list* the resolution reads it through
        # (`handlers/_common._THAT_PLAYER_CONTEXT_KEYS`). One list, because the
        # picker and the handler must agree about which seat the words name:
        # a second copy here would be a picker offering one board while
        # `subject_matches` tested another, and the difference would show as an
        # ability that resolves against nothing.
        that_player = self._that_player_seat(item)
        if that_player is not None:
            spec["that_player_index"] = that_player
        elif spec.get("that_player_only"):
            # Nothing froze the seat, so there is no board to offer. Declining
            # is the safe direction the three early-outs above take: an
            # unnarrowed list would offer every permanent in the game for a
            # phrase that names one player's.
            return
        # "**That player** chooses target player who…" (the Exodus Oaths).
        # CR 601.2c gives the choice to the ability's controller unless the
        # card says otherwise, and these say otherwise: the seat that picks is
        # the one whose upkeep it is. Only the prompt moves — the candidate
        # list is enumerated from the announcing seat exactly as before,
        # because every narrowing these cards print carries its own reference
        # (`compared.than`) and the lowering refuses a printed chooser beside
        # one that does not.
        #
        # A chooser the fire site never froze cannot be asked, and the ability
        # then announces nothing rather than falling back to the controller —
        # the same safe direction the three early-outs above take.
        chooser_index = item.caster_index
        if spec.get("chooser") is not None:
            chooser_index = self._trigger_chooser_seat(item, spec["chooser"])
            if chooser_index is None:
                return
        candidates = self._enumerate_targets(
            item.caster_index, item.card, spec, for_cast=False,
            ability_instruction=instruction,
            source_permanent=item.source_permanent,
            ability_source=item.source_permanent,
            triggered=True,
        )
        offered = []
        for candidate in candidates:
            if candidate.get("kind") == "player":
                seat = candidate.get("seat")
                if not isinstance(seat, int) or not 0 <= seat < len(self.players):
                    continue
                offered.append({
                    "kind": "player",
                    "seat": seat,
                    "name": self.players[seat].name,
                })
                continue
            if candidate.get("kind") != "permanent":
                continue
            perm = self.permanent_at(candidate["seat"], candidate["index"])
            if perm is None:
                continue
            offered.append({
                # Stamped on every entry, not only the new ones: the prompt
                # carries two shapes now, and a reader telling them apart by
                # which keys happen to be missing would be guessing.
                "kind": "permanent",
                "seat": candidate["seat"],
                "permanent_index": candidate["index"],
                "permanent_id": perm.permanent_id,
                "name": perm.card.name,
            })
        if not offered:
            # "Up to one" with nothing to name is an announcement of zero
            # targets (CR 601.2c), not a choice that cannot be made — the
            # ability stays on the stack with no target and resolves.
            if _target_is_up_to(getattr(instruction, "payload", None)):
                return
            self.stack = [existing for existing in self.stack if existing is not item]
            self.log.append(
                f"{item.card.name}'s triggered ability was removed from the stack: "
                "it has no legal target (603.3c)"
            )
            return
        self.arm_pending_choice(
            "trigger_target", chooser_index,
            card_name=item.card.name,
            targets=offered,
            _trigger_item=item,
        )

    def _trigger_chooser_seat(self, item: StackItem, chooser: str) -> int | None:
        """Which seat announces *item*'s target when the card names one, or
        None when nothing froze that seat.

        Two printed words reach here and each reads its own frozen key, because
        they are two different facts about one event:

        * ``that_player`` — the seat the event *was about* (the Exodus Oaths'
          "**that player** chooses target player who…"), through
          :meth:`_that_player_seat` and so through the same key list the
          resolution reads it through;
        * ``event_subject_controller`` — the seat that controlled the *object*
          the event was about ("**that creature's controller** may have it deal
          damage … to any target **of their choice**", Pandemonium). One step
          further out, and a different key: ``matching_permanent_enters``
          freezes the entering permanent's controller and freezes no
          ``event_subject_player`` at all, so reading one for the other would
          announce nothing on every card that prints this.

        A word with no row is declined rather than defaulted, which is the safe
        direction every early-out in :meth:`_choose_trigger_targets` takes: the
        ability announces no target and never reaches the stack's target field,
        where falling back to the controller would hand the pick to precisely
        the seat the card says must not make it.
        """
        if chooser == "event_subject_controller":
            seat = (item.trigger_context or {}).get("event_subject_controller")
            if isinstance(seat, int) and 0 <= seat < len(self.players):
                return seat
            return None
        if chooser == "that_player":
            return self._that_player_seat(item)
        return None

    def _that_player_seat(self, item: StackItem) -> int | None:
        """The seat *item*'s printed "that player" names, or None if the firing
        event froze none.

        The picker's half of ``handlers/_common.frozen_that_player_seat``, and
        deliberately reading that module's key tuple rather than a list of its
        own: the two answer the same question at two moments, and a phrase the
        picker resolved differently from the resolution is an ability offered
        one board and applied to another.
        """
        from ...handlers._common import _THAT_PLAYER_CONTEXT_KEYS

        frozen = item.trigger_context or {}
        for key in _THAT_PLAYER_CONTEXT_KEYS:
            seat = frozen.get(key)
            if isinstance(seat, int) and 0 <= seat < len(self.players):
                return seat
        return None

    def _default_trigger_mode_target(self, option: dict, controller_index: int) -> dict | None:
        """Which candidate a non-interactive seat takes for *option*.

        A stated policy, like the "first printed mode" beside it, and derived
        rather than named: ``ai_valuation.activation_target_side`` reads the
        mode's own instruction kind through ``INSTRUCTION_CATEGORIES`` and says
        whether an effect of that family wants an opponent's side or its own.
        A family with no answer falls back to the first candidate offered,
        which is what every prompt in this engine does when nothing
        distinguishes the options.
        """
        from ...ai_valuation import activation_target_side

        candidates = option.get("valid_targets") or []
        if not candidates:
            return None
        side = activation_target_side(option["instruction"])
        if side is not None:
            opponents = set(self.opponents_of(controller_index))
            wanted = opponents if side == "opponent" else {controller_index}
            for candidate in candidates:
                if candidate.get("seat") in wanted:
                    return candidate
        return candidates[0]

    def _enqueue_triggered_batch(self, events: list[dict]) -> None:
        """Put a batch of triggered abilities that fired from one event onto the stack
        in APNAP order (CR 603.3b): the active player's triggers are enqueued first
        (so they resolve last), then each other player's in turn order. Each player's
        own triggers keep their collection (battlefield-scan) order. The sort key is
        total and index-tie-broken, so enqueue order is fully seed-deterministic."""
        if not events:
            return
        n = len(self.players)
        active = self.active_player_index if self.active_player_index is not None else 0

        def _key(indexed):
            order, event = indexed
            controller = int(event["controller_index"])
            turn_distance = (controller - active) % n if n else 0
            return (turn_distance, controller, order)

        for _, event in sorted(enumerate(events), key=_key):
            self._enqueue_triggered_ability(**event)

    @contextmanager
    def deferring_triggers(self):
        """Hold triggers fired inside this block until the block ends.

        CR 601.2a puts a spell on the stack **first** and CR 601.2h pays its
        costs afterwards; CR 602.2a/602.2b say the same of an activated ability.
        A trigger that fires while a cost is being paid therefore belongs
        *above* the object being cast — and CR 601.2c's parenthetical spells out
        the mechanism: such abilities "wait to be put on the stack until the
        spell has finished being cast".

        This engine pays first and pushes second, because a payment that cannot
        be made has to leave nothing behind — the rewind CR 601.2 describes,
        done by never having built the stack item. That inverted the order for
        every trigger a cost fires. Holding them here restores it without
        touching the rewind: the buffer is flushed after the push, so the
        observable sequence is the rule's, whatever the internal order was.

        Nothing in the pool could see this until the sacrifice seam gave
        "whenever you sacrifice a permanent" a fire site — Havoc Jester's ping
        resolved *after* Witch's Cauldron's draw, and after Village Rites'.

        Re-entrant by design: an inner block joins the outer buffer rather than
        starting a second one, so a nested announcement still flushes exactly
        once, at the point the outermost object is on the stack.
        """
        if self.deferred_triggers is not None:
            yield
            return
        self.deferred_triggers = []
        try:
            yield
        finally:
            held, self.deferred_triggers = self.deferred_triggers, None
            for event in held:
                self._enqueue_triggered_ability(**event)
    def _settle(self) -> None:
        """Run state-based actions, then resolve the stack one item at a time,
        re-checking SBAs between each resolution (CR 704.3 + 603.3). Triggers that
        fire during an SBA check are enqueued (never resolved) there, so this loop
        is what actually drains them in the headless/AI path. Terminates when the
        stack is empty and SBAs report no further change.

        **Whether a resolution may stop to ask is derived, not assumed.** This
        loop is reached from the two "do the whole thing now" entry points
        (``cast_from_hand``, ``activate_permanent_ability``), and it resolved
        with ``pause_for_choices`` left False whoever was playing — so a prompt
        armed part-way through a resolution was queued against an *empty
        stack*: nothing recorded the object (``_stack_item`` is stamped from
        ``resolving_stack_item``, which only the pausing path sets), so the
        object never came back, ``_release_stack_item`` never ran, and CR 704.3's
        sweep and CR 117.3b's priority hand-off were applied to a resolution
        that had not finished. Measured over the shipped pool: of the 296
        prompt-armings a resolution makes on this path, **267 across 255 cards**
        had nothing holding them. The other 29 structurally cannot have one — a
        mana ability uses no stack (CR 605.3a), a mode chosen at announcement
        records ``_trigger_item`` instead, and a land play puts no object on the
        stack at all — and those same 29, and only those, are what the priority
        path leaves unheld. That is what named this loop as the seam.

        The condition is ``bool(self.interactive_seats)`` — the same derivation
        ``_resolve_priority_window`` already makes, and for the same reason: with
        nobody to stop for, headless and AI play queue the same prompts and drain
        them deterministically afterwards, so a seeded run resolves exactly as it
        did.

        **What it does not do is answer anything.** A prompt owed by a seat the
        engine plays still holds the object here, exactly as it does on the
        priority path, and the caller drains it — ``_auto_resolve_ai_pending``
        in the web layer, ``auto_resolve_pending_choices`` in a test. Draining
        inside this loop was tried and is a *different* change: it takes the
        AI's answer before the caller can see what was asked, which is what
        forty tests read the queue for.

        Power Sink's payment is where that shows on a shipped card. It used to
        be answered from inside ``resolve_top_of_stack`` on the ``not
        pause_for_choices`` branch, so ``cast_from_hand`` finished it; now it is
        queued like every other prompt, held with its object, and answered by
        whoever drains. Invoke Prejudice ("counter that spell unless that player
        pays {X}{X}") is the card that reaches it in an ordinary duel.
        """
        # CR 608.2 / CR 117.3b, only where there is somebody to wait for.
        pause_for_choices = bool(self.interactive_seats)
        iterations = 0
        while True:
            self.check_state_based_actions()
            # A table whose prompts a driver answers (`Game.prompt_driver`, the
            # AI simulator): what the object just resolved asked is answered
            # *here*, before the next object resolves, rather than after this
            # whole loop has returned. Inert for every other game, so the
            # sentence above about not answering anything still holds for them.
            if self.drive_owed_prompts():
                iterations += 1
                if iterations > self.MAX_SETTLE_ITERS:
                    break
                continue
            if not self.stack:
                break
            if not self.resolve_top_of_stack(pause_for_choices=pause_for_choices):
                # Top item is paused on a pending choice (Word of Command).
                break
            # A resolution that stopped to ask holds its object on the stack
            # (CR 608.2). Break *here* rather than letting the loop come round:
            # the next iteration's SBA check would run mid-resolution, which is
            # a sweep at a moment CR 704.3 does not name. The caller resumes
            # when the last of the object's prompts is answered — the answer
            # path releases it (`_release_stack_item`).
            if (
                pause_for_choices
                and self.stack
                and self.stack[-1].resolution_held
                and self.stack_item_is_waiting(self.stack[-1])
            ):
                break
            iterations += 1
            if iterations > self.MAX_SETTLE_ITERS:
                self.log.append(
                    f"_settle aborted after {self.MAX_SETTLE_ITERS} iterations (possible loop)"
                )
                break
    def resolve_stack(self, pause_for_choices: bool = False) -> None:
        while self.stack:
            if not self.resolve_top_of_stack(pause_for_choices=pause_for_choices):
                # The top item is paused on a decision somebody owes; it finishes
                # when the choice is confirmed.
                break
    def resolve_top_of_stack(self, pause_for_choices: bool = False) -> bool:
        """Resolve (and remove) the top stack object. Returns True if an object was
        resolved, False if the stack was empty or its top is mid-resolution.

        ``pause_for_choices`` is used by the human priority path (pass_priority).
        CR 608.2 — a resolution is not over until its last instruction is done —
        and CR 117.3b — nobody receives priority until then. So a resolution that
        stops to ask somebody something ("you may search your library …",
        Sanctum of All; "you may pay {2}", the colour Rods) keeps its object on
        the stack, with every prompt it armed recording that object
        (``_stack_item``, stamped in ``arm_pending_choice``). The object leaves
        through ``_release_stack_item`` when the last of those prompts is
        answered — and *only* then, because answering one prompt is how the next
        step of the same resolution arms its own.

        Headless/auto paths leave this False, so the object resolves and pops
        immediately and the caller drains the prompts deterministically,
        preserving seeded behaviour."""
        if not self.stack:
            return False
        top = self.stack[-1]
        # **A choice made as the object went on the stack, not yet answered.**
        # CR 601.2b-c and CR 603.3c-d put a modal trigger's mode and a targeted
        # ability's targets *before* the object is announced, so an object with
        # one of those still owed has not finished being put on the stack and
        # cannot resolve. Those prompts record the object as ``_trigger_item``
        # rather than ``_stack_item``, because nothing was resolving when they
        # were armed — which is exactly why the two checks below, which read
        # ``_stack_item``, never saw them.
        #
        # Only an interactive seat can ever be here: every announcement prompt
        # is registered ``default_at_arm``, so a headless or AI seat has already
        # answered by the time this runs and nothing waits.
        if self.announcement_choice_for(top) is not None:
            return False
        # A Word of Command paused mid-resolution stays on the stack until its
        # card choice is confirmed. Once the choice has been recorded (deferred
        # confirm), releasing priority lands here and finishes the resolution:
        # the forced card is played and the spell heads to the graveyard. The
        # forced spell is left on the stack on the interactive path
        # (pause_for_choices) so it gets its own priority round; headless loops
        # drain it on their next iteration. It is the one prompt that outlives
        # its own answer, which is why it finishes here rather than through the
        # generic release below.
        waiting_woc = self.pending_choice_of("word_of_command")
        if waiting_woc is not None and waiting_woc.data.get("_stack_item") is top:
            if "chosen_hand_index" not in waiting_woc.data:
                return False
            self.discard_pending_choice(waiting_woc)
            self._finish_word_of_command(
                waiting_woc.data, waiting_woc.data["chosen_hand_index"],
                auto_resolve_forced=False, caster_index=waiting_woc.player_index,
            )
            return True
        # Anything else that has already run its instructions is never run
        # again: it waits while it still owes somebody a decision, and otherwise
        # simply leaves. The second half is the backstop — an answer path that
        # returns without releasing the object strands it here, and re-resolving
        # it would apply the whole ability twice.
        if top.resolution_held:
            if self.stack_item_is_waiting(top):
                return False
            self._release_stack_item(top, force=True)
            return True

        item = self.stack.pop()
        woc_before = self.pending_choice_of("word_of_command")
        previous_resolving = self.resolving_stack_item
        self.resolving_stack_item = item if pause_for_choices else None
        # `resolving_items` is which *cast* is running (see Game), pushed here
        # for the same reason `resolving_seats` is pushed around an instruction:
        # this is the one place that knows, and everything below reaches the
        # damage paths with a bare CardDefinition that cannot say.
        self.resolving_items.append(item)
        try:
            self._run_stack_item_resolution(item)
        finally:
            self.resolving_items.pop()
            self.resolving_stack_item = previous_resolving
        # Power Sink armed a pending "pay {X} or be countered" for the targeted
        # spell's controller. On the human priority path leave it for the prompt;
        # headless/AI resolves it deterministically (pay if able, else countered).
        payment = self.pending_choice_of("mana_payment")
        if payment is not None and payment.data.get("_new"):
            payment.data.pop("_new", None)
            if not pause_for_choices:
                self._auto_resolve_mana_payment()
        # Still resolving: hold the object on the stack until every prompt it
        # armed has been answered.
        if self.choices_for_stack_item(item):
            item.resolution_held = True
            self.stack.append(item)
            return True
        # Word of Command pauses mid-resolution for the caster's card choice
        # (CR 608.2: the spell is still resolving). Keep it on the stack until
        # confirm_word_of_command finishes the resolution and removes it. The
        # headless path gets no stamp above, so this is where it is linked there.
        woc_after = self.pending_choice_of("word_of_command")
        if (
            woc_after is not None
            and woc_after is not woc_before
            and "_stack_item" not in woc_after.data
        ):
            self.stack.append(item)
            woc_after.data["_stack_item"] = item
        return True
    def _chosen_trigger_instruction(self, item: StackItem):
        """What a triggered ability actually runs — its chosen mode, if it had
        one to choose.

        The mode was picked as the object went on the stack (CR 700.2b), so by
        the time it resolves there is nothing left to ask: the ability behaves
        exactly like an unmodal one whose targets were chosen at the same
        moment. This is where that recorded index is spent.

        A modal item that reaches here with no recorded mode falls through to
        the ``choose_one`` instruction itself, which asks at resolution the way
        the engine used to. That is a backstop for a prompt discarded by
        something other than an answer, not a second policy: it cannot happen
        through the arming path, because the prompt blocks the seat until it is
        answered, and it does the only safe thing if it ever does.
        """
        instruction = item.ability_instruction
        modes = modal_trigger_modes(instruction)
        if not modes or item.chosen_mode_index is None:
            return instruction
        if not 0 <= item.chosen_mode_index < len(modes):
            return instruction
        return modes[item.chosen_mode_index]["instruction"]

    def _log_ability_outcome(self, item: StackItem, supported: bool, details: str) -> None:
        """What the game log says an ability's resolution did.

        "Resolved" is a claim about a resolution that is *over*. One that armed a
        prompt is not — the search has not been made, the life has not been
        gained — and saying so anyway was the visible half of the bug this link
        fixes: Sanctum of All read "ability resolved" in the log with its "you
        may search your library" prompt still unanswered on screen. The
        completion line is ``_release_stack_item``'s to write, once the last
        answer arrives."""
        if not supported:
            self.log.append(f"{item.card.name} ability fizzled: {details}")
        elif self.choices_for_stack_item(item):
            self.log.append(f"{item.card.name} ability is resolving, awaiting a choice")
        else:
            self.log.append(f"{item.card.name} ability resolved")

    def _run_stack_item_resolution(self, item: StackItem) -> None:
        # **An index is not an identity** (ROADMAP idiom #11) and a graveyard is
        # the zone with no identity to fall back on, so what ``_stack_push``
        # stamped is turned back into a slot *here* — once, at the top, so every
        # reader below (a spell, an ability, an Aura's reanimation, an
        # enters-the-battlefield trigger) sees a live index without knowing this
        # happened. The stamp itself is never overwritten: an item pushed back
        # on for a pending choice re-locates from the same name next time.
        if item.target_graveyard_card is not None:
            item.target_permanent_index = self.chosen_graveyard_index(
                item.target_graveyard_card, item.target_permanent_index
            )
            # And which pile the slot counts into. For a graveyard target that
            # *is* what `target_player_index` means, and leaving it to be
            # re-derived below is how the two halves of one choice came apart:
            # every reader defaults it differently (`1 - caster` here, the
            # caster there), so a spell was validated against one graveyard and
            # resolved against another.
            # ``[]`` is a real announcement, not a missing one: "Return **up
            # to X** target cards…" with X counted at 0 (Reap against an
            # opponent with no black permanents) names no target and is a legal
            # cast, and so is any "up to" spell announced empty. Indexing a
            # stamp list without asking whether it has one raised IndexError
            # from inside the resolution, which is a crash where CR 601.2c has
            # an answer.
            stamps = item.target_graveyard_card
            first = (
                (stamps[0] if stamps else None)
                if isinstance(stamps, list)
                else stamps
            )
            if first is not None:
                item.target_player_index = first.seat
        # CR 608.2b, asked once for the whole object before any of it runs.
        # This module's docstring has claimed since it was written that a
        # resolution re-checks its targets, and until now nothing did: each
        # handler checked its *own* target and skipped its own effect, so the
        # sentences printed after the targeted one carried on regardless.
        # The gate is `legality.illegal_targets_refusal` — the sibling of the
        # announcement gate, so the same identities decide both ends.
        illegal = self.illegal_targets_refusal(item)
        if illegal is None:
            # ...and the same rule for the one restriction that is not about a
            # target still *existing* but about it still *answering what the
            # card printed*: "target opponent who has more life than you do".
            # A second call rather than a branch inside the gate above, because
            # that gate is CR 608.2b for spells and this is CR 608.2b for one
            # printed clause — folding them would advertise a cover over
            # abilities that does not exist. `legality.stale_comparison_refusal`
            # states its own bounds.
            illegal = self.stale_comparison_refusal(item)
        if illegal is not None:
            self.log.append(illegal)
            if item.ability_instruction is None and not item.is_copy:
                # CR 608.2b: removed from the stack and, if it is a spell, put
                # into its owner's graveyard — the ordinary destination, so it
                # goes through the same binning as a resolved spell. An ability
                # and a token copy have no card to put anywhere.
                self._bin_spell_card(
                    self.players[item.owner_index], item.card,
                    exile_instead=item.exile_instead_of_graveyard,
                    verb="was countered by the rules",
                )
            return
        # A triggered ability with a name-keyed resolve-time hook (Rod/Cup/Sphere,
        # Verduran Enchantress, Guardian Angel deferred onto the stack).
        if item.hook_key is not None:
            from ...card_hooks import TRIGGER_HOOKS

            handler = TRIGGER_HOOKS.get(item.hook_key)
            if handler is not None:
                handler(self, item)
                self._log_ability_outcome(item, True, "")
            return
        if item.ability_instruction is not None:
            context = self._ability_execution_context(item)
            # CR 603.4's **second** check: an intervening-if is asked again as
            # the ability resolves, and the ability is removed from the stack
            # and does nothing if it is false. 102 supported cards compile the
            # key; the comment that stood here said no card in the shipped pool
            # did, which was the reason the rule's *first* check went unbuilt
            # for as long as it did.
            gate = (item.ability_instruction.payload or {}).get("intervening_if")
            if gate is not None and not evaluate_condition(self, context, gate):
                self.log.append(
                    f"{item.card.name} ability did nothing: its condition is no longer true"
                )
                return
            state_machine = OracleStateMachine(self, context)
            supported, details = state_machine.run(
                self._chosen_trigger_instruction(item)
            )
            self._log_ability_outcome(item, supported, details)
            return

        # A copy of an instant/sorcery (Fork) resolves like the original but is a
        # token spell: it ceases to exist afterward (no graveyard) and was never
        # cast, so it skips the cast/graveyard bookkeeping in _resolve_card.
        if item.is_copy and item.card.primary_type in ("instant", "sorcery"):
            caster = self.players[item.caster_index]
            target_idx = item.target_player_index if item.target_player_index is not None else (1 - item.caster_index)
            target = self.players[target_idx] if 0 <= target_idx < len(self.players) else caster
            self._apply_spell_text(
                caster,
                target,
                item.card,
                target_permanent_index=item.target_permanent_index,
                target_permanent_id=item.target_permanent_id,
                x_value=item.x_value,
                new_color=item.choices.get("new_color"),
                stack_target=item.target_stack_item,
                mode_index=item.chosen_mode_index,
                old_color=item.choices.get("old_color"),
                choices=item.choices,
            )
            self.log.append(f"{item.card.name} (copy) resolved")
            return

        classification = classify_card(item.card)
        self._resolve_card(
            caster_index=item.caster_index,
            card=item.card,
            classification=classification,
            target_player_index=item.target_player_index,
            target_permanent_index=item.target_permanent_index,
            target_permanent_id=item.target_permanent_id,
            x_value=item.x_value,
            new_color=item.choices.get("new_color"),
            stack_target=item.target_stack_item,
            chosen_mode_index=item.chosen_mode_index,
            chosen_modes=item.chosen_modes,
            old_color=item.choices.get("old_color"),
            divided_targets=item.choices.get("divided_targets"),
            exile_instead_of_graveyard=item.exile_instead_of_graveyard,
            cast_from_zone=item.cast_from_zone,
            choices=item.choices,
            trigger_context=item.trigger_context,
            owner_index=item.owner_index,
        )
        return
    def _resolve_card(
        self,
        caster_index: int,
        card: CardDefinition,
        classification: CardClassification,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        target_permanent_id: int | list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        chosen_mode_index: int | None = None,
        # Every chosen mode of a "Choose one or more —" spell, each with its own
        # targets, in printed order (CR 608.2c). Empty for every other spell,
        # which is what keeps the single-mode path below untouched.
        chosen_modes: tuple = (),
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        exile_instead_of_graveyard: bool = False,
        cast_from_zone: str = "hand",
        choices: dict | None = None,
        # What the *announcement* froze that this spell's own text refers back
        # to. A trigger's context (CR 603.10) has always ridden the stack item;
        # a spell had none to carry until CR 700.2e gave one a seat nobody on a
        # board can name — "**an opponent** chooses one —", and then "that
        # player" in the mode they chose. Same key, same reader
        # (`handlers/_common.frozen_that_player_seat`), so the phrase has one
        # answer whether a trigger or a mode choice bound it.
        trigger_context: dict | None = None,
        # CR 108.3: who owns the card, when that is not its caster — see
        # ``StackItem.owner_index``. The spell's card goes to *this* seat's
        # zones as it leaves the stack (CR 400.3, CR 608.2n), and a permanent
        # it becomes is this seat's card under the caster's control.
        owner_index: int | None = None,
    ) -> None:
        caster = self.players[caster_index]
        owner_seat = caster_index if owner_index is None else owner_index
        owner = self.players[owner_seat]
        primary_type = card.primary_type

        if primary_type in {"land", "creature", "artifact", "enchantment", "planeswalker"}:
            permanent = Permanent(card=card)
            if x_value is not None:
                permanent.metadata["cast_x_value"] = x_value
            # A "copy as it enters" permanent (Clone) records the chosen copy
            # target so initialization can copy the player-selected creature
            # rather than an arbitrary one — with the id the stack stamped
            # beside the slot, because the slot is a position the board may
            # have renumbered since the cast (``_resolve_copy_target``).
            if target_permanent_index is not None:
                chosen_id = (
                    target_permanent_id[0]
                    if isinstance(target_permanent_id, list) and target_permanent_id
                    else target_permanent_id
                )
                permanent.metadata["copy_target"] = (
                    target_player_index if target_player_index is not None else caster_index,
                    target_permanent_index,
                    chosen_id if isinstance(chosen_id, int) else None,
                )
            # The one entry site in the engine that *is* a cast (CR 701.5a):
            # a permanent spell resolving. Every other path puts a permanent
            # onto the battlefield without casting it, which is what
            # Containment Priest reads.
            # "…or you cast it **from your graveyard**" (Archfiend's Vessel).
            # The zone the spell was cast from, which for a permanent spell is
            # also the zone the permanent came from — one call, two records,
            # because a later card may ask either question and they are not the
            # same one: a reanimation stamps the first and not the second.
            permanent.metadata["cast_from_zone"] = cast_from_zone
            # "If this creature **was kicked**, it enters with …" / "When this
            # creature enters, **if it was kicked**, …" / "…if this creature
            # **wasn't kicked**, sacrifice it" (Skizzik, turns later). CR
            # 702.33d settled the answer at the announcement and the stack item
            # carried it; it is copied onto the permanent here because the
            # permanent is what all three sentences are asked of and the stack
            # item is gone by the time the last of them is.
            #
            # Stamped **before** the permanent enters, for the creature type's
            # reason below: an entry replacement (CR 614.1c) reads it as the
            # permanent arrives. And only here, the one entry that is a cast
            # (CR 701.5a) -- a reanimated, blinked or token-copied permanent
            # never passes this line, which is the rule rather than an
            # omission: it was not cast, so it was not kicked.
            if kicked(card, choices):
                permanent.metadata[KICKED] = True
                # ...and **which** of its kicker costs paid for it
                # (CR 702.33b: a Battlemage prints two). "If it was kicked with
                # its {1}{G} kicker" is CR 702.33f's question about one of
                # them, asked of the permanent for the same reason the flag
                # above is. A tuple of the recorded keys, so the entry trigger
                # and the announcement that paid name a cost by one string.
                permanent.metadata[KICKED_WITH] = kickers_paid(card, choices)
            # "…where X is **the discarded card's mana value**." (Dralnu's
            # Pet.) What the spell's cost discarded, as the one number an entry
            # replacement may read back — see
            # ``cast_costs.CAST_COST_DISCARD_MANA_VALUE`` for why it is the
            # number and why it is stamped here. Exactly one card, or no
            # stamp: "the discarded card" names nothing else.
            cost_discards = (choices or {}).get("discarded_for_cost") or ()
            if len(cost_discards) == 1:
                permanent.metadata[CAST_COST_DISCARD_MANA_VALUE] = int(
                    getattr(cost_discards[0], "cmc", 0) or 0
                )
            # "…the controller of **the permanent it becomes** sacrifices it at
            # the beginning of the next cleanup step" (Mirage's flash Auras).
            # The answer was frozen as the spell was announced, because that is
            # the only moment CR 601.3d's timing can be read; carried onto the
            # permanent here because the permanent is what the sentence acts on
            # and the stack item is gone by the time the cleanup step looks.
            if (choices or {}).get(CAST_AT_INSTANT_SPEED):
                permanent.metadata[CAST_AT_INSTANT_SPEED] = True
            # "As an additional cost to cast this spell, choose a creature
            # type." (Caller of the Hunt.) The word was chosen at CR 601.2b and
            # rode the stack item; it is copied onto the permanent here because
            # the permanent is what the card's other line reads it off
            # ("creatures of the chosen type"), through the same
            # ``chosen_creature_type`` metadata key An-Zerrin Ruins' *entry*
            # choice writes — one key, so `subject_filters` has one reader
            # whichever step of CR 601 or CR 614 made the choice.
            #
            # Stamped **before** the permanent enters, which is the whole of
            # what makes this a cast-time cost rather than an entry effect: the
            # characteristic-defining P/T is computed from the moment the
            # permanent is on the battlefield (CR 604.3, CR 613.1), and a
            # creature that arrived without its word would be a 0/0 that
            # CR 704.5f bins before anyone could answer a prompt. It is also
            # why a Caller of the Hunt put onto the battlefield *without being
            # cast* is that 0/0 — correctly: no cast, no CR 601.2b, no type.
            chosen_creature_type = (choices or {}).get("chosen_creature_type")
            if chosen_creature_type:
                permanent.metadata["chosen_creature_type"] = chosen_creature_type
            # CR 108.3: a permanent spell cast out of another seat's zone
            # (Grinning Totem) enters under its caster's control and is still
            # its owner's card. ``owner_index_of`` otherwise answers with the
            # seat it entered under, so it would die into the caster's
            # graveyard (CR 400.3). The channel reanimation and Desertion
            # already write for the same reason; stamped before the entry so an
            # entry replacement that sends it "to its owner's graveyard instead"
            # reads the right owner too.
            if owner_seat != caster_index:
                permanent.metadata["owner_player_index"] = owner_seat
            self._put_permanent_onto_battlefield(
                caster_index, permanent, target_player_index,
                was_cast=True, from_zone=cast_from_zone,
            )
            # CR 614: an entry replacement may have consumed the event, and then
            # the permanent is on no battlefield at all - Frankenstein's Monster
            # cast for an X its graveyard cannot pay goes to its owner's
            # graveyard "instead of onto the battlefield".
            #
            # Everything below this line is something that watches a permanent
            # *enter*: the log line, the global buff, the enters-the-battlefield
            # trigger, the Aura's attach. Running any of them for an entry that
            # did not happen is the "when it enters, do X instead" reading that
            # engine/replacements.py exists to avoid, one layer up from the
            # interceptor - and the log line saying the permanent was put onto
            # the battlefield is the same claim in the one place a player reads.
            if not self.is_on_battlefield(permanent):
                return
            self.log.append(f"{caster.name} put {card.name} onto battlefield")
            self._apply_global_buff(caster, card)
            is_aura = "Aura" in card.type_line
            if not is_aura and copy_on_enter_type(
                compile_card_oracle(card).normalized_text or ""
            ) is not None:
                # **The cast's target was the object to copy.** A permanent
                # that offers a copy choice as it enters (Clone, Vesuvan
                # Doppelganger, Copy Artifact — CR 707.5's "as a copy", a
                # CR 614.1c replacement) announces *that* at cast:
                # ``targeting._cast_target_spec`` raises the copy picker in
                # place of an entry trigger's. So whatever entry trigger the
                # copied object brings (CR 707.5) was announced by nobody, and
                # handing it the cast's target would aim it at the creature
                # that was copied — a Clone of Man-o'-War bouncing the
                # Man-o'-War. It chooses its own as it is put on the stack
                # (CR 603.3d), exactly as the same trigger does on an entry
                # nothing cast.
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, None, None, None,
                    targets_announced=False,
                )
            elif not is_aura:
                # ...and a cast that announced **nothing** — a headless or
                # scripted cast with no picker in front of it — is the same
                # "nobody chose" as an entry nothing cast. Handed in as if it
                # were an announcement, the inline path fell back to scanning
                # the *caster's* board: a bare Nekrataal destroyed its
                # caster's Savannah Lions and a bare Ravenous Rats made its
                # caster discard.
                announced = any(
                    value is not None
                    for value in (
                        target_player_index, target_permanent_index,
                        target_permanent_id,
                    )
                )
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                    targets_announced=announced,
                )
            ran_entry_text = self._apply_aura_effect(
                caster_index,
                permanent,
                target_player_index,
                target_permanent_index,
                target_permanent_id,
            )
            # An Aura's own "when this Aura enters" trigger, for every Aura whose
            # entry text `_apply_aura_effect` did *not* perform itself.
            #
            # This used to be skipped for all of them, on the strength of the two
            # it does perform bespokely (Animate Dead's reanimation, Earthbind's
            # conditional damage) — so an Aura whose entry trigger compiled to an
            # ordinary instruction did nothing at all while reporting supported.
            # Three cards were in that state.
            #
            # After the attach rather than before it, which is the order the rest
            # of the engine already keeps: "when this Aura enters, tap enchanted
            # creature" has nothing to tap until the Aura is attached.
            if is_aura and not ran_entry_text:
                self._apply_self_enters_battlefield_triggers(
                    caster_index, permanent, target_player_index,
                    target_permanent_index, target_permanent_id,
                )
            # An Aura that failed to attach (its target left the battlefield while the
            # spell was on the stack) goes to its owner's graveyard instead of
            # remaining on the battlefield unattached (MTG Rule 303.4g)
            if (
                "Aura" in card.type_line
                and aura_enchant_clause(card.oracle_text) is not None
                and permanent.metadata.get("attached_to") is None
            ):
                holder = self.controller_index_of(permanent)
                if holder is not None:
                    self.remove_from_battlefield(permanent)
                self.put_card_into_graveyard(owner, card)
                self.log.append(f"{card.name} had no legal target and was put into {owner.name}'s graveyard")
                self._refresh_dynamic_creatures()
                return
            self._refresh_dynamic_creatures()
            if primary_type == "land":
                if self.enforce_mana_costs:
                    self.lands_played_this_turn[caster_index] = self.lands_played_this_turn.get(caster_index, 0) + 1
                    if self.lands_played_this_turn.get(caster_index, 0) > 1:
                        # "…if it wasn't the first land you played this turn,
                        # ~ deals N damage to you". The rider is read off each
                        # source's own text alongside the allowance it came
                        # with, so the sources name themselves in the log
                        # instead of the engine naming one of them.
                        sources = [
                            (permanent, allowance)
                            for permanent, allowance in self._land_play_allowances(caster_index)
                            if allowance.damage_per_extra_land
                        ]
                        if sources:
                            total = sum(a.damage_per_extra_land for _, a in sources)
                            names = ", ".join(
                                dict.fromkeys(permanent.card.name for permanent, _ in sources)
                            )
                            self._deal_damage_to_player(
                                caster, total,
                                then=lambda damage: self.log.append(
                                    f"{names} dealt {damage} damage to {caster.name}"
                                ),
                            )
                self._process_land_enters(caster_index)
                # "Whenever an opponent **plays** a land" (Dirtcowl Wurm).
                # CR 305.1's special action, announced here because here is
                # where it happens — `_process_land_enters` above is the
                # *entry*, which a land put onto the battlefield by an effect
                # also makes and this one does not.
                #
                # ``event_subject_player`` beside ``seat``: the first is the
                # one key every reader of a printed "**that player**" asks for
                # (CR 603.10) and the second is what this event's own filter
                # compares against the observer. Horn of Greed's "that player
                # draws a card" is a different seat on every land drop, and
                # nothing on a board records who played one — so the freeze has
                # to happen here, where it is known.
                # ``played_permanent_id`` is what "**another** land" (City of
                # Traitors) is compared against. The entry above has already
                # happened, so a land whose own trigger watches land drops is
                # on the battlefield and observing by the time this is
                # announced — and the exclusion cannot be answered from
                # ``card``, because a deck repeats one immutable
                # ``CardDefinition`` per copy and a second printing of the same
                # land would read as the first. CR 400.7's id is the identity.
                emit(
                    self, "land_played", subject=card, seat=caster_index,
                    event_subject_player=caster_index,
                    played_permanent_id=permanent.permanent_id,
                )
                # "When **you play a card**" (Juju Bubble). CR 701.18b's other
                # half: a land is played rather than cast, so the cast
                # announcement never reaches it. Beside `_process_land_enters`
                # rather than beside the `lands_played_this_turn` bump above,
                # because that bump is inside the cost-enforcement branch and
                # a land played in a game with costs off is still a land
                # played.
                emit(self, "you_play_card", subject=card, caster_index=caster_index)
            return

        # Sorceries and instants resolve immediately in this basic engine.
        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target = self.players[target_idx]

        def apply_text() -> None:
            # "Choose one **or more** —" (Sublime Epiphany, CR 700.2d). Each
            # chosen mode is its own application, with the targets it chose
            # (CR 601.2c) and the seat those targets sit on — two modes may name
            # objects on two different boards, which the spell's single
            # ``target_player_index`` cannot say. Printed order, because
            # CR 608.2c resolves the modes in the order the card writes them
            # rather than the order the caster named them; the list arrives
            # sorted from ``_resolve_chosen_modes``.
            #
            # Any non-empty list takes this path, one mode included: a caller
            # that named modes named their targets on them, and the branch below
            # reads the *item's* target fields, which such a cast never sets.
            # A cast that named no modes at all — the legacy `mode_index=`
            # spelling, and every non-modal spell — leaves the list empty and
            # takes the branch below exactly as it always has.
            if chosen_modes:
                for mode in chosen_modes:
                    seat = (
                        mode.target_player_index
                        if mode.target_player_index is not None else target_idx
                    )
                    if not 0 <= seat < len(self.players):
                        seat = target_idx
                    self._apply_spell_text(
                        caster,
                        self.players[seat],
                        card,
                        target_permanent_index=mode.target_permanent_index,
                        target_permanent_id=mode.target_permanent_id,
                        x_value=x_value,
                        new_color=new_color,
                        stack_target=mode.target_stack_item,
                        mode_index=mode.index,
                        old_color=old_color,
                        divided_targets=divided_targets,
                        cast_from_zone=cast_from_zone,
                        choices=choices,
                        trigger_context=trigger_context,
                    )
                return
            self._apply_spell_text(
                caster,
                target,
                card,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
                x_value=x_value,
                new_color=new_color,
                stack_target=stack_target,
                mode_index=chosen_mode_index,
                old_color=old_color,
                divided_targets=divided_targets,
                cast_from_zone=cast_from_zone,
                choices=choices,
                trigger_context=trigger_context,
            )

        # ``finish`` may run twice: once at the end of the resolution, and — if
        # a prompt this resolution armed was still queued then — again from
        # ``_release_stack_item`` when the last answer lands. The hook and the
        # end-the-turn flag are read on the first pass only.
        first_pass = {"ends_turn": None}

        def finish() -> None:
            if first_pass["ends_turn"] is None:
                self._apply_self_resolved_hook(caster_index, card, target_idx, target_permanent_index)
                pending_woc = self.pending_choice_of("word_of_command")
                if (
                    pending_woc is not None
                    and "_spell_card" not in pending_woc.data
                    and pending_woc.data.get("card_name") == card.name
                ):
                    # Word of Command is still resolving while the caster chooses a
                    # card from the target's hand; it goes to the graveyard only when
                    # confirm_word_of_command finishes the resolution.
                    pending_woc.data["_spell_card"] = card
                    # The seat the card is binned to: its owner's (CR 608.2n),
                    # under the key the finishing step has always read.
                    pending_woc.data["_spell_caster_index"] = owner_seat
                    pending_woc.data["_spell_exile_instead"] = exile_instead_of_graveyard
                    return
                # CR 724.1b: "End the turn" exiles every object on the stack
                # *including the object that's resolving*. That object was popped
                # before its handler ran, so the process flags it here instead of
                # reaching back into a list it is no longer in.
                first_pass["ends_turn"] = bool(getattr(self, "exile_resolving_spell", False))
                self.exile_resolving_spell = False
            # CR 608.2n makes the graveyard the *last* step, and a resolution
            # that armed a prompt still queued is not at its last step: a
            # discard, a Power Sink payment, Balance's removals. Binning here
            # put the card in two zones at once — held on the stack and in the
            # graveyard, with the log already reading "moved to graveyard" while
            # the decision was owed. The step is handed to the held object
            # instead, and ``_release_stack_item`` runs it with the last answer.
            # A suspending prompt (a search, a scry) never reaches here early —
            # ``run_resumable`` holds this step back for it — so this is the
            # non-suspending half of the same rule.
            held = self.resolving_stack_item
            if held is not None and held.card is card and self.choices_for_stack_item(held):
                held.finish_resolution = finish
                self._log_spell_awaiting_choice(card)
                return
            # CR 608.2n: "into its **owner's** graveyard" — the caster's only
            # when the caster owns it.
            self._bin_spell_card(
                owner, card,
                exile_instead=exile_instead_of_graveyard or first_pass["ends_turn"],
                verb="resolved",
                # CR 702.27a's second static ability, asked here because "as it
                # resolves" is exactly this step and nowhere else. The answer is
                # the announcement this cast made, which by now survives only on
                # the stack item's own record (CR 500.5 emptied the pool).
                hand_instead=buyback_paid(card, choices),
            )

        # CR 608.2n puts the card into the graveyard as the *last* part of
        # resolution, which matters once a spell's effect can stop to ask the
        # player something: finishing here regardless would bin the card while
        # its damage was still waiting on an answer. Word of Command already
        # needed the same care for its own reason, and is the reason `finish`
        # was a separable step to begin with.
        run_resumable(self, [apply_text, finish], lambda step: step())
        # The one thing that may legitimately follow a resumable loop: a note
        # that it *stopped*. ``finish`` is where a held spell says so, and a
        # suspending prompt (a scry, a search, and since discards suspend, a
        # Mind Rot) never reaches ``finish`` — ``run_resumable`` holds it back
        # until the answer lands. Without this the log went quiet exactly where
        # the player is being asked something. It runs only on the suspended
        # path, so it cannot double up with ``finish``'s line, and it records
        # nothing the resumption needs to redo.
        if self.effect_suspended:
            held = self.resolving_stack_item
            if held is not None and held.card is card and self.choices_for_stack_item(held):
                self._log_spell_awaiting_choice(card)

    def _log_spell_awaiting_choice(self, card) -> None:
        """CR 608.2: the spell is still resolving while a prompt it armed is
        owed. The ability half of this line is ``_log_ability_outcome``; both
        exist so "resolved" is never claimed of a resolution that has not
        finished."""
        self.log.append(f"{card.name} is resolving, awaiting a choice")

    def _apply_self_enters_battlefield_triggers(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None,
        target_permanent_id: int | list[int | None] | None = None,
        *,
        targets_announced: bool = True,
    ) -> None:
        """Put a just-entered permanent's own "when this enters" triggered
        abilities on the stack (CR 603.6a, CR 603.3).

        **Each one is a stack object, and nothing of it happens here.** CR 603.3:
        "Once an ability has triggered, its controller puts it on the stack as
        an object that's not a card the next time a player would receive
        priority." Until Planeshift this method *executed* the trigger, inside
        the event that put the permanent onto the battlefield — an
        approximation that went in with Arabian Nights (Oubliette), whose stated
        reason was that the engine had no window in which a trigger's target
        could be chosen. ``_choose_trigger_targets`` has been that window since,
        and the approximation outlived its reason by eleven sets: 265 of the
        pool's 278 entry triggers resolved with no object on the stack, so
        nothing could respond to one. Cavern Harpy ("When this creature enters,
        return a blue or black creature you control to its owner's hand. / Pay
        1 life: Return this creature to its owner's hand.") could not be
        returned in response to its own gate, which is the best-known play with
        the card.

        Measured before it was changed: run both ways over every entry trigger
        in both manifest roles on three roads onto the battlefield (807
        scenarios), the two paths ended in the same game state everywhere but
        four cards, and three of those were the inline path being wrong — see
        the seat below. ``tests/engine/test_entry_trigger_stack_census.py``
        holds the invariant.

        **Order.** The triggers of one permanent trigger together, and CR
        603.3b lets their controller put them on the stack in any order. This
        engine has no prompt for that choice anywhere (every batch takes its
        collection order), so the stated policy is the printed one: the *first
        printed resolves first*, which is the order they ran in inline, and so
        the last printed is pushed first. Each resolves alone — Sawtooth Loon's
        gate is asked, answered and finished before its "draw two cards, then
        put two cards … on the bottom" begins, where inline the second ran into
        the first's unanswered prompt.

        **The cast's announcement rides the object.** This engine names an
        entry trigger's target as the permanent is cast (the standing
        approximation ``targeting._cast_target_spec`` documents; CR 603.3d
        would choose it here), so the seat, slot and id the cast handed in are
        stamped on the stack object, flagged ``announced_at_cast`` so the push
        neither asks again nor announces the same choice twice. The id travels
        with the index because an index is unstable: anything leaving the
        battlefield renumbers every later slot, and the trigger now waits
        through a priority round of its own.

        **The seat is the one the cast named, or none.** Inline, a trigger
        nobody named a player for ran with its *controller* as "the target
        player"; every other trigger in the engine defaults that to the first
        opponent (``_ability_execution_context``), and the stack object takes
        that default like the rest. The difference was three shipped cards,
        all wrong inline: Rishadan Brigand, Cutpurse and Footpad ("each
        opponent sacrifices a permanent of their choice unless they pay {N}")
        charged the toll to their own controller.

        **Whose triggers** is what the permanent *has*, which is
        ``effective_card`` and not ``card``. CR 707.5: an object that enters as
        a copy "becomes a copy as it enters the battlefield", and "any
        enters-the-battlefield triggered abilities of the copy will have a
        chance to trigger"; CR 603.6d checks an entering permanent as it exists
        after the event. Reading the printed card, every copy in the pool —
        Clone, Vesuvan Doppelganger, Copy Artifact and the token copies of
        Dance of Many, Dual Nature, Echo Chamber and Sublime Epiphany — fired
        nothing on arrival. The death half of the same question
        (``_permanent_to_graveyard``) already read the effective card.

        *targets_announced* says whether the targets handed in were chosen
        *for these triggers*. True for a cast whose picker was derived from the
        entry trigger (``targeting._cast_target_spec``'s last branch). False
        for an entry nothing cast (a token, a reanimation), for a cast that
        announced nothing, and for a copy, whose cast announced the object to
        copy instead: nothing chose a target for the trigger at all, so one
        that has a target to choose chooses it as it is put on the stack
        (CR 603.3d; a non-interactive seat takes the picker's stated default).

        **An announcement is spent by the one trigger it was made for.** The
        cast's picker is derived from the *first* entry trigger that describes
        a target (``targeting._first_described_slot``, over the triggers a cast
        kicked this way will fire -- CR 702.33g), so that trigger is the only
        one anybody chose for. A second trigger with a target of its own was
        announced by nobody, exactly as on an entry nothing cast, and handing
        it the first one's target is two wrong answers: "destroy target land"
        handed two creatures finds its target gone and does nothing, and
        "destroy target enchantment" handed a *player* falls to the handler's
        fallback scan and destroys whichever enchantment that seat controls.
        So once a choosing trigger has taken the announcement, every later
        choosing trigger chooses for itself (CR 603.3d). Planeshift's
        Battlemages ("Kicker {2}{U} and/or {2}{R}", one trigger per cost) are
        the cards that reach it.

        **A modal trigger takes nothing from the cast.** CR 603.3c: its mode,
        and then that mode's targets, are chosen as it is put on the stack —
        ``_choose_trigger_mode`` — and the cast's picker derives nothing for a
        bulleted head, so there is no announcement that could be its.
        """
        program = compile_card_oracle(permanent.effective_card)
        if target_player_index is not None and not (
            0 <= target_player_index < len(self.players)
        ):
            target_player_index = None
        handed_over = any(
            value is not None
            for value in (
                target_player_index, target_permanent_index, target_permanent_id,
            )
        )
        announcement_spent = False
        triggered: list[dict] = []
        for trig in program.triggered_abilities:
            if (
                trig.condition.kind not in ENTRY_TRIGGER_CONDITIONS
                or not trig.supported
                or trig.instruction is None
            ):
                continue
            event = dict(
                controller_index=controller_index,
                source_permanent=permanent,
                card=permanent.card,
                instruction=trig.instruction,
                effect_kind=trig.effect_kind,
                ability_text=trig.source_line,
                # CR 107.3m: the cast's X, stamped on the permanent by
                # `_resolve_card`. "When this Aura enters, … put X sleep
                # counters on it" (Venarian Gold) reads it, and without it
                # every amount in an entry trigger resolved "x" to zero.
                x_value=permanent.metadata.get("cast_x_value"),
            )
            chooses = self._entry_trigger_chooses_a_target(trig.instruction)
            chooses_on_the_stack = bool(modal_trigger_modes(trig.instruction)) or (
                chooses and (not targets_announced or announcement_spent)
            )
            if handed_over and not chooses_on_the_stack:
                event.update(
                    target_player_index=target_player_index,
                    target_permanent_index=target_permanent_index,
                    target_permanent_id=target_permanent_id,
                    announced_at_cast=True,
                )
            # CR 603.4: an ability whose "if" is false as the event occurs does
            # not trigger at all. Asked here as well as at the push, because
            # only a trigger that *fired* spends the announcement: one whose
            # "if" was false (a Battlemage kicked with its second cost alone)
            # was never the trigger the picker described.
            if not self._entry_trigger_triggers(event):
                continue
            if not chooses_on_the_stack:
                announcement_spent = announcement_spent or chooses
            triggered.append(event)
        # Last printed first, so the first printed is on top and resolves
        # first (CR 603.3b's order, at the stated policy above).
        for event in reversed(triggered):
            self._enqueue_triggered_ability(**event)

    def _entry_trigger_triggers(self, event: dict) -> bool:
        """CR 603.4's first check for one entry trigger, before it is queued.

        Asked through :meth:`trigger_condition_holds`, of an object built the
        way the push will build it, so the answer is the one ``_stack_push``
        will reach a moment later: the rule's two checks, and this early read
        of the first, all go through the one context builder
        (:meth:`_ability_execution_context`). Nothing is put on the stack here.
        """
        if (event["instruction"].payload or {}).get("intervening_if") is None:
            return True
        return self.trigger_condition_holds(StackItem(
            card=event["card"],
            caster_index=event["controller_index"],
            target_player_index=event.get("target_player_index"),
            target_permanent_index=event.get("target_permanent_index"),
            x_value=event.get("x_value"),
            target_permanent_id=event.get("target_permanent_id"),
            ability_instruction=event["instruction"],
            ability_effect_kind=event["effect_kind"],
            source_permanent=event["source_permanent"],
            ability_text=event["ability_text"],
        ))

    def _entry_trigger_chooses_a_target(self, instruction: OracleInstruction) -> bool:
        """Whether CR 603.3d has a target for :meth:`_choose_trigger_targets`
        to choose on this entry trigger.

        The picker's own gate, asked before the push rather than after it: the
        same spec derivation, the same two kind sets, and the same
        :func:`announces_a_target` requirement on a player. A trigger it would
        decline — a graveyard card, a spell, a seat nobody prints "target" for —
        has no choice that picker could make, so it goes on the stack carrying
        whatever the cast announced, exactly as it was handed it inline.
        """
        from ...targeting import derive_instruction_spec

        if modal_trigger_modes(instruction):
            return False
        spec = derive_instruction_spec([instruction])
        if spec is None:
            return False
        kind = spec.get("kind")
        if kind in self._CHOOSABLE_TRIGGER_TARGET_KINDS:
            return True
        return (
            kind in self._CHOOSABLE_TRIGGER_PLAYER_KINDS
            and announces_a_target(instruction)
        )

    def _select_executable_instruction(
        self, card: CardDefinition, mode_index: int | None = None
    ) -> OracleInstruction | None:
        """What the stack runs for one spell — **all** of its effect lines, in
        the order written (CR 608.2c).

        This took the *first* non-``spell_pattern`` instruction and stopped,
        which is only ever right by accident. A card that prints its clauses on
        one line already compiles to a single ``sequence``; a card that prints
        them on two gets one instruction per line
        (``oracle._noncreature_line_instructions``), and every line after the
        first was silently dropped. Opt scried and never drew, Revitalize gained
        life and never drew — supported cards playing as a strictly smaller card,
        which is the first standing invariant. It survived because no shipped
        instant or sorcery has two effect lines.

        Fusing here rather than in the compiler is deliberate: for a *permanent*
        that same list is a mirror of everything the card does, scanned by kind
        by the layer bridge and the AI, and fusing it would make the mirror
        unreadable. Only an instant or sorcery reaches this function, and only
        for it is the list a program.

        Composing through ``sequence`` also buys the resumption behaviour for
        free — a step that stops to ask (a scry, a search) takes the steps behind
        it with it, which is exactly what "Scry 1. Draw a card." needs.
        """
        program = compile_card_oracle(card)
        # A modal spell resolves the player's chosen mode; fall back to the first
        # instruction (mode 0) when no mode was chosen (e.g. AI casts).
        if mode_index is not None and program.modes and 0 <= mode_index < len(program.modes):
            mode = program.modes[mode_index]
            if mode.instruction is not None:
                return mode.instruction
        # ``spell_pattern`` is a marker recording that a whitelist substring
        # matched, not an effect; everything else in an instant's list is one.
        steps = tuple(
            instruction for instruction in program.instructions
            if instruction.kind != "spell_pattern"
        )
        if not steps:
            return None
        if len(steps) == 1:
            return steps[0]
        return OracleInstruction("sequence", "", {"steps": steps})
