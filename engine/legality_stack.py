"""Targets on the stack: which spells and abilities a phrase may aim at, and
the gates that hold a named one to that list (CR 115.1, CR 113.7a, CR 601.2c).

A stack object is a target of its own kind — an index into the stack rather
than a battlefield slot, an object that may be a spell or an ability (which
has no card of its own), narrowed by who controls it and by what *it* targets
("…with a single target", Deflection). So the enumeration is its own:
:meth:`StackTargetsMixin._enumerate_stack_targets` and
:meth:`StackTargetsMixin._enumerate_stack_ability_targets`, read by the general
enumerator for a ``stack`` spec and by
:meth:`StackTargetsMixin._offered_stack_targets`, the one list every question
about a spell's stack target asks.

The gates beside it are that list asked again: a named stack target must be
one it offers (:meth:`StackTargetsMixin.cast_stack_target_refusal`), a stack
object named for a spell or ability that targets nothing there is refused
(:meth:`StackTargetsMixin.stray_stack_target_refusal`,
:meth:`StackTargetsMixin.stray_activation_stack_target_refusal`), and a bare
cast is taken to name the topmost one it admits
(:meth:`StackTargetsMixin.default_stack_target`).
"""

from __future__ import annotations

from .models import CardDefinition
from .oracle import compile_card_oracle
from .targeting import (
    derive_cast_spec,
    role_is_stack,
    spec_names_the_stack,
    spec_roles,
)
from .legality import _STACK_TARGET_KINDS, _single_target_is


class StackTargetsMixin:
    """Targets on the stack: what may be aimed at and the gates that hold
    a named one to it. Composed onto ``Game`` beside ``LegalityMixin``."""

    def _offered_stack_targets(
        self, caster_index: int, card: CardDefinition, spec: dict,
    ) -> "list | None":
        """The stack objects *spec*'s printed target phrase admits, by
        identity and in stack order (bottom first), or None when *spec* names
        nothing on the stack.

        **The one enumeration** every question about a spell's stack target is
        asked through — the picker's own (``_enumerate_stack_targets``, which
        the client is handed), turned back from top-first indices into the
        objects. Three callers, and they are the three moments the rule has:
        :meth:`cast_stack_target_refusal` (CR 601.2c, at announcement),
        :meth:`default_stack_target` for a caller that named nothing, and
        :meth:`illegal_targets_refusal` (CR 608.2b, at resolution). A fourth
        reading of the phrase is how the first three come to disagree.

        ``spell_or_permanent`` is in it for its stack half (the Laces,
        Unsubstantiate): "target **spell** or creature" admits a spell and
        nothing else on the stack, and the enumeration already says so — an
        ability is not a spell (CR 113.7a). Its permanent half is
        :meth:`cast_target_refusal`'s.

        A **roles** spec with a stack role (Suffocating Blast's "target spell"
        beside its "target creature") answers for that role — the role is the
        description of its slot, so it is the spec to enumerate.
        """
        if spec.get("kind") not in _STACK_TARGET_KINDS:
            spec = next(
                (role for role in spec_roles(spec) if role_is_stack(role)), None
            )
            if spec is None:
                return None
        depth = len(self.stack)
        chosen: set[int] = set()
        for entry in self._enumerate_stack_targets(caster_index, card, spec):
            index = entry.get("stack_index")
            if (
                entry.get("kind") == "stack"
                and isinstance(index, int)
                and 0 <= depth - 1 - index < depth
            ):
                chosen.add(depth - 1 - index)
        return [self.stack[index] for index in sorted(chosen)]

    def _stack_target_spec(
        self, card: CardDefinition, *, from_zone: str = "hand",
        mode_index: int | None = None,
    ) -> dict | None:
        """*card*'s cast spec where :meth:`_offered_stack_targets` is the
        question to ask of it, else None.

        Instants and sorceries, for :meth:`cast_target_refusal`'s reason: a
        permanent spell's derived spec is its trigger's. A modal spell answers
        for the mode it was announced with (*mode_index*) — Blue Elemental
        Blast cast in its *destroy* mode is not asked for a red spell, and
        Dromar's Charm cast in its *counter* mode is asked for a spell, where
        both used to be declined for being modal at all.
        """
        if card.primary_type not in ("instant", "sorcery"):
            return None
        program = compile_card_oracle(card)
        if program.modes and program.mode_chooser is not None:
            return None
        spec = derive_cast_spec(
            card, program, from_zone=from_zone, mode_index=mode_index,
        )
        if spec is None or spec.get("kind") not in _STACK_TARGET_KINDS:
            return None
        return spec

    def cast_stack_target_refusal(
        self, caster_index: int, card: CardDefinition, target_stack_item,
        *, from_zone: str = "hand", mode_index: int | None = None,
    ) -> str | None:
        """CR 601.2c for a spell whose target is **an object on the stack**:
        the one named must be one the printed target phrase admits, and with
        none named there must be one to name. Returns the refusal, or None.

        The stack half of :meth:`cast_target_refusal`, which leaves ``stack``
        specs alone (``_UNCHECKED_CAST_TARGET_KINDS``) because it compares
        battlefield slots. What stood in its place was the counter arm of
        ``_validate_cast_targets``, and that arm asks one question — the
        colour. Every other narrowing a counterspell prints was enforced by the
        picker (which never offered the wrong spell) and by the handler (which
        declined to counter it), and by nothing in between: "Counter target
        **creature** spell" could be announced at a Lightning Bolt, the mana
        was spent, the card went to the graveyard and the Bolt resolved. Found
        on Spite, the pool's first *spell* to print "target noncreature spell";
        twenty shipped spells carried a narrowing the arm did not ask.

        **One gate, where Invasion's first wave left two.** W1G2 built this
        for a *named* spell over the picker's whole list; W1G8 built
        ``described_stack_target_refusal`` beside it for four spec keys
        (Teferi's Response), with two behaviours the first lacked — a bare
        announcement is refused when there is nothing to name, and the
        description is re-asked at resolution. The second was scoped narrowly
        because the picker then read a spell's card type off ``primary_type``
        where the handler reads every printed type; that is fixed
        (``_spell_is_one_of``, held by ``test_announced_stack_target``), and
        with it the reason for two scopes. Both behaviours are kept, for every
        key, because both are the rule rather than Teferi's Response:

        * **nothing named, nothing to name** is CR 601.2c's own first half —
          a spell that targets cannot be cast without a legal target. The
          counter arm asked it as "is the stack empty", which let Remove Soul
          be cast bare at a lone Lightning Bolt and Counterspell at a lone
          activated ability, and no arm asked it at all of a spell whose
          counter sits in a ``sequence`` (Arcane Denial, Absorb, Rewind: cast
          onto an empty stack, the trailing sentence resolving for free).
        * **the resolution re-check** is CR 608.2b, in
          :meth:`illegal_targets_refusal`.

        The answer is :meth:`_offered_stack_targets` — the picker's own list —
        so the gate and the picker are one enumeration rather than two readings
        of one phrase (idiom #9: the picker's list is a hint and the engine
        re-checks the answer). Compared by identity: ``StackItem`` compares by
        value, and two casts of one card at one target are equal.

        A ``spell_or_permanent`` spec is asked only what was **named** on the
        stack: with nothing named its legal target may be a permanent, and
        "is there any legal target at all" across both zones is the bare-cast
        question :meth:`cast_target_refusal` owns.
        """
        spec = self._stack_target_spec(
            card, from_zone=from_zone, mode_index=mode_index,
        )
        if spec is None:
            return None
        refused = f"no valid target for {card.name}"
        offered = self._offered_stack_targets(caster_index, card, spec)
        if target_stack_item is None:
            if spec.get("kind") != "stack":
                return None
            return None if offered else refused
        if not any(item is target_stack_item for item in offered):
            return refused
        return None

    def stray_stack_target_refusal(
        self, caster_index: int, card: CardDefinition, target_stack_item, *,
        from_zone: str = "hand", mode_index: int | None = None,
        optional_cost_payments: dict | None = None,
        names_a_permanent: bool = False,
    ) -> str | None:
        """CR 601.2c from the other side: an announcement chooses "an
        appropriate object or player **for each target the spell requires**" —
        and a stack object named for a spell that requires none there is not a
        choice the rule has a place for. Returns the refusal, or None.

        :meth:`cast_stack_target_refusal` asks whether the spell that was named
        is one the printed phrase admits, and returns None for every spell with
        no stack target to ask about — which is how a ``target_stack_index`` on
        a Lightning Bolt, a Terror or a Wrath of God came to be accepted,
        recorded on the stack item and ignored: 888 of 888 casts in a census of
        the pool's instants and sorceries. No client sends one and nothing was
        countered by it, but the record is not inert — CR 608.2b counts a
        recorded stack object as one of the spell's targets
        (:meth:`_announcement_target_legality`), so a Terror whose creature had
        left stayed "partly legal" for as long as the stray spell was on the
        stack.

        A stack object is announceable where the derived spec says the stack is
        where a target (or CR 609.7a's chosen source, ``also_stack``) may be:
        :func:`spec_names_the_stack`. For "target spell **or** permanent" it is
        one target in one of two zones, so naming a permanent beside it
        (*names_a_permanent*) is two answers to one question and is refused
        too.

        Asked of every card type, because the spec is: a permanent spell's is
        its entry trigger's, and the engine names that trigger's target as the
        permanent is cast — Mystic Snake's "counter target spell" takes a stack
        index and a Grizzly Bears does not. Where **an opponent** chooses the
        mode (CR 700.2e) the caster names no target at all as it casts, so the
        question is asked of every mode at once: a stack object is stray unless
        some mode could have named one.
        """
        if target_stack_item is None:
            return None
        program = compile_card_oracle(card)
        if program.modes and program.mode_chooser is not None:
            specs = [
                derive_cast_spec(
                    card, program, from_zone=from_zone,
                    optional_cost_payments=optional_cost_payments,
                    mode_index=index,
                )
                for index in range(len(program.modes))
            ]
            if any(spec_names_the_stack(spec) for spec in specs):
                return None
            spec = None
        else:
            spec = derive_cast_spec(
                card, program, from_zone=from_zone,
                optional_cost_payments=optional_cost_payments,
                mode_index=mode_index,
            )
        if not spec_names_the_stack(spec):
            return (
                f"{card.name} targets nothing on the stack, so it cannot name "
                "a spell there (CR 601.2c)"
            )
        if names_a_permanent and spec.get("kind") == "spell_or_permanent":
            return (
                f"{card.name} has one target: a spell or a permanent, not one "
                "of each (CR 601.2c)"
            )
        return None

    def stray_activation_stack_target_refusal(
        self, card: CardDefinition, spec: dict, target_stack_item, *,
        names_a_permanent: bool = False,
    ) -> str | None:
        """:meth:`stray_stack_target_refusal` for an **activation** (CR 602.2b
        sends it through CR 601.2c): a stack object named for an ability whose
        announcement has no target there, or beside a permanent for "target
        spell **or** permanent" (Blind Seer). Returns the refusal, or None.

        *spec* is the ability's own derived spec, which the activation gate
        already holds. The two shapes that accepted one were an ability that
        targets nothing at all — 881 in a census of the pool's abilities, the
        gate returning before it looked — and one whose permanent target was
        named beside it (429), where the ids were checked and the stack object
        was recorded unread: 1,311 of 1,458 activations examined.
        """
        if target_stack_item is None:
            return None
        if not spec_names_the_stack(spec):
            return (
                f"{card.name}'s ability targets nothing on the stack, so it "
                "cannot name a spell there (CR 602.2b)"
            )
        if names_a_permanent and spec.get("kind") == "spell_or_permanent":
            return (
                f"{card.name}'s ability has one target: a spell or a "
                "permanent, not one of each (CR 602.2b)"
            )
        return None

    def default_stack_target(
        self, caster_index: int, card: CardDefinition, *, from_zone: str = "hand",
        mode_index: int | None = None,
    ) -> tuple[bool, object]:
        """``(answered, item)``: the object a **bare** cast of *card* is taken
        to name — the topmost one its target phrase admits.

        *answered* is False where the question is not this gate's (see
        :meth:`_stack_target_spec`; a ``spell_or_permanent`` spec too, whose
        unnamed target may be a permanent), and the caller keeps whatever it
        did before. Where it is True the item is the whole answer, None
        included: nothing admitted means nothing is named.

        A caller that names nothing — the AI's fallback, a script, a test — is
        owed *a legal* choice, and until this the choice was a fourth reading
        of the phrase: a regex over the oracle text that knew the colour word
        and nothing else, so a bare Remove Soul above a creature spell and an
        instant was aimed at whichever was on top.

        **A modal instant or sorcery is always answered** (*mode_index*; none
        named is mode 0). The mode decides whether the stack is where its
        target is, so a mode that names nothing there — Dromar's Charm giving
        -2/-2 — is answered "nothing", and the caller's text fallback must not
        hand it the topmost spell for printing "counter target spell" in a
        mode nobody chose: a stack target the object never announced is one
        CR 608.2b would then count as a still-legal target.
        """
        spec = self._stack_target_spec(
            card, from_zone=from_zone, mode_index=mode_index,
        )
        if spec is None or spec.get("kind") != "stack":
            if card.primary_type in ("instant", "sorcery"):
                program = compile_card_oracle(card)
                if program.modes and program.mode_chooser is None:
                    return True, None
            return False, None
        offered = self._offered_stack_targets(caster_index, card, spec)
        return True, (offered[-1] if offered else None)

    def _enumerate_stack_targets(
        self, caster_index: int, card: CardDefinition, spec: dict, source=None
    ) -> list[dict]:
        """The spells on the stack this spec may point at.

        *caster_index* is the seat doing the pointing, needed because a
        narrowing can be *relative* to it ("that targets a permanent **you**
        control"). It is the same seat ``subject_matches`` calls the observer,
        and CR 109.5 is why it is the counter's controller rather than the
        controller of the spell being looked at.

        *source* is the ability's own permanent, for the one narrowing that is
        an identity rather than a description: "…that targets **this creature**"
        (Mistfolk). A spell is offered only while it is still pointing at that
        permanent, which is what keeps the {U} from being paid for nothing.
        """
        targets: list[dict] = []
        color_filter = spec.get("stack_color_filter")
        instant_sorcery_only = spec.get("stack_instant_sorcery_only")
        # "Counter target **activated ability** from an artifact source" (Rust,
        # Ayesha Tanaka). A spec that asks for abilities offers abilities and
        # nothing else: an ability is not a spell (CR 113.7a) and the two are
        # never interchangeable targets, so this is a different list rather than
        # a wider one.
        ability_kinds = spec.get("stack_ability_kinds")
        if ability_kinds:
            return self._enumerate_stack_ability_targets(
                spec, ability_kinds, caster_index=caster_index, source=source
            )
        depth = len(self.stack)
        for i, item in enumerate(self.stack):
            # Only spells are legal targets — activated/triggered abilities on the
            # stack (which carry an ability_instruction) can't be countered/copied.
            if getattr(item, "ability_instruction", None) is not None:
                continue
            item_card = getattr(item, "card", None)
            if item_card is None:
                continue
            if instant_sorcery_only and item_card.primary_type not in ("instant", "sorcery"):
                continue
            # Miscast: "target instant or sorcery spell" — the union the
            # compiled counter carries, tested here so the picker offers only
            # what the handler would counter.
            #
            # Through the handler's own reader (``_spell_is_one_of``, CR 205.2:
            # a card has every type its line names). This asked
            # ``primary_type``, which picks one type off the line — "creature"
            # for an artifact creature — so Annul ("artifact or enchantment
            # spell") was never offered an Ornithopter while its handler would
            # have countered one. That was a picker short of a legal target for
            # as long as the picker was only a hint; it became a legal cast
            # **refused** the day `cast_stack_target_refusal` made this list
            # the announcement gate (INV W1G2), which is what found it. The
            # complement below already asked the handler's reader for exactly
            # this reason.
            from .handlers.stack import _spell_is_one_of

            stack_card_types = spec.get("stack_card_types")
            if stack_card_types and not _spell_is_one_of(item_card, stack_card_types):
                continue
            # Null Brooch: "target **noncreature** spell" — the complement,
            # asked through ``_spell_is_one_of`` rather than through
            # ``primary_type`` above it. That is the handler's own reader, and
            # the difference is load-bearing here in a way it is not for the
            # union: CR 205.2 gives an artifact creature spell *both* types, so
            # a ``primary_type`` test would offer it ("artifact" is not
            # "creature") and the handler would then decline — the whole hand
            # discarded for nothing. The union above asks the same reader now.
            stack_excluded_types = spec.get("stack_excluded_types")
            if stack_excluded_types:
                if _spell_is_one_of(item_card, stack_excluded_types):
                    continue
            # "…spell **with mana value 3 or less**" (Liquify). The spell's
            # mana value *as it is on the stack* (CR 202.3b: an X in its cost
            # counts at the announced value), so a spell whose X makes it
            # bigger is not offered and, re-asked here at CR 608.2b, is not
            # countered.
            stack_mana_value = spec.get("stack_mana_value")
            if stack_mana_value:
                from .handlers._common import _comparison_holds
                from .targeting import stack_object_mana_value

                if not _comparison_holds(stack_mana_value, stack_object_mana_value(item)):
                    continue
            # "target instant or **Aura** spell" (Avoid Fate, Ring of
            # Immortals): the same cross-axis union the handler tests, asked
            # through the same reader, so the picker offers exactly what the
            # counter would counter.
            any_classes = spec.get("stack_any_classes")
            if any_classes:
                from .handlers.stack import _spell_is_one_of_classes

                if not _spell_is_one_of_classes(
                    item_card, [tuple(entry) for entry in any_classes]
                ):
                    continue
            # "…that targets a permanent you control" — asked of the recorded
            # targets of the spell being offered, against the seat whose spell
            # or ability is doing the countering.
            targets_filter = spec.get("stack_targets_filter")
            targets_source = source if spec.get("stack_targets_source") else None
            if targets_filter or targets_source is not None:
                from .handlers.stack import _spell_targets_matching

                if not _spell_targets_matching(
                    self, item, dict(targets_filter or {}), caster_index,
                    source=targets_source,
                ):
                    continue
            # "…**with a single target** [if that target is you]" (Deflection,
            # Reflecting Mirror — CR 115.7a / CR 115.9a). Asked through the one
            # reader the retarget handler asks at resolution, against the same
            # seat every other narrowing here is measured against (CR 109.5) —
            # so a spell the effect could not actually re-aim is never offered,
            # and the mana it would cost is never paid for nothing.
            #
            # A spell whose target set the engine cannot establish answers None
            # and is simply not offered: under-offering is a narrower card,
            # over-offering is a card redirecting spells it was never allowed to.
            #
            # The count and the "is you" are **two** gates because two cards
            # print them separately: Deflection carries only the first.
            if not self._stack_single_target_ok(item, spec, caster_index, source):
                continue
            if not _stack_controller_ok(item, spec, caster_index):
                continue
            if color_filter and color_filter not in self._stack_item_colors(item):
                continue
            stack_any_colors = spec.get("stack_any_colors")
            if stack_any_colors:
                item_colors = self._stack_item_colors(item)
                if not any(colour in item_colors for colour in stack_any_colors):
                    continue
            # The UI (and the cast/activate action) index the stack top-first, the
            # reverse of the engine's bottom-first list — emit the top-first index.
            targets.append({"kind": "stack", "stack_index": depth - 1 - i, "name": item_card.name})
        # "Change the target of target spell **or ability** that targets only
        # this creature." (Silver Wyvern.) CR 113.7a keeps the two apart, so the
        # ability half is a second list folded in rather than a widening of this
        # loop, which would have to gate every card question it asks — the same
        # shape ``also_stack`` takes for Circle of Protection's chosen source.
        if spec.get("stack_include_abilities"):
            targets += self._enumerate_stack_ability_targets(
                spec, None, caster_index=caster_index, source=source
            )
        return targets

    def _stack_single_target_ok(
        self, item, spec: dict, caster_index: int, source
    ) -> bool:
        """"...**with a single target** [if that target is you]" (Deflection,
        Reflecting Mirror -- CR 115.7a / CR 115.9a), and what the card asks
        about that one target.

        Asked through the one reader the retarget handler asks at resolution,
        against the same seat every other narrowing is measured against
        (CR 109.5) -- so an object the effect could not actually re-aim is never
        offered, and the mana it would cost is never paid for nothing.

        An object whose target set the engine cannot establish answers None and
        is simply not offered: under-offering is a narrower card, over-offering
        is a card redirecting spells it was never allowed to.

        The count and the "is you" are **two** gates because two cards print
        them separately: Deflection carries only the first. Its own method
        because the ability list asks it too (Silver Wyvern) -- these three are
        the only narrowings an ability can be asked, every other key in
        ``_enumerate_stack_targets`` being a question about a *card*.
        """
        if not spec.get("stack_single_target"):
            return True
        from .targeting import single_spell_target

        chosen = single_spell_target(self, item)
        if chosen is None:
            return False
        single_target_is = spec.get("stack_single_target_is")
        if single_target_is is not None and not (
            single_target_is == "you"
            and chosen.get("kind") == "player"
            and chosen.get("seat") == caster_index
        ):
            return False
        # "...and **that target is a creature**" (Meddle), "...that targets only
        # **this creature**" (Silver Wyvern). The object half of the same
        # question, asked through `is_creature` -- CR 613's answer rather than
        # the printed type line, so an animated land a spell is aimed at is a
        # creature here exactly as it is everywhere else. A permanent that has
        # left is not one.
        wanted_type = spec.get("stack_single_target_type")
        if wanted_type is not None and not _single_target_is(
            self, chosen, wanted_type, source=source
        ):
            return False
        return True

    def _enumerate_stack_ability_targets(
        self, spec: dict, ability_kinds: "list[str] | None",
        *, caster_index: int = 0, source=None,
    ) -> list[dict]:
        """The **abilities** on the stack this spec may point at (CR 113.7a).

        Its own enumeration rather than a widening of the spell one above: an
        ability has no card of its own, so every narrowing a counterspell asks
        of a spell — colour, card type, what it targets — is a question this
        list cannot be asked, and the two it *is* asked (which kind of ability,
        and what kind of permanent it came from) mean nothing to a spell.

        Both are answered through the handler's own readers
        (``_stack_ability_kind``, ``_spell_is_one_of``), so an ability offered
        here is one ``counter_stack_ability`` would counter. Offering one it
        would refuse is not a cosmetic slip: the activation cost is paid before
        the counter resolves, so the tap buys nothing and nothing on screen says
        why.

        A mana ability is never here to be excluded (CR 605.3a: it does not use
        the stack), which is what the printed reminder text says.

        ``ability_kinds`` of None is "any ability", which is what "target spell
        **or ability**" says (Silver Wyvern) -- CR 113.3a-c leaves only static
        abilities out, and those never use the stack. It is distinct from an
        empty list, which no caller passes and which would mean "no kind at
        all"; the counterspells that name their kinds pass them.
        """
        from .handlers.stack import _spell_is_one_of, _stack_ability_kind

        source_types = tuple(spec.get("stack_ability_source_types") or ())
        depth = len(self.stack)
        targets: list[dict] = []
        for i, item in enumerate(self.stack):
            if getattr(item, "ability_instruction", None) is None:
                continue
            kind = _stack_ability_kind(item)
            if kind is None or (
                ability_kinds is not None and kind not in ability_kinds
            ):
                continue
            if source_types:
                # A **local**: ``source`` is this method's own argument, the
                # permanent whose ability is doing the looking, and rebinding
                # it here pointed every later question in this loop — and every
                # later iteration — at whatever permanent the last candidate
                # came from. No card in the pool prints both narrowings, so
                # nothing has read the wrong one yet; the "…that targets a
                # creature" gate below is the second reader that would.
                from_permanent = item.source_permanent
                if from_permanent is None or not _spell_is_one_of(
                    from_permanent.effective_card, source_types
                ):
                    continue
            # "…**that targets a creature**" (Diplomatic Escort). The same
            # narrowing the spell loop above asks, through the same reader: an
            # ability announced its targets at CR 602.2b exactly as a spell
            # announced them at CR 601.2c, so "what did this object choose" is
            # one question with one answer for both kinds. Without it the union
            # offers every ability on the stack, the {U} and the card are spent,
            # and the counter then declines — the printed rider dropped on
            # exactly the half of the offer it was added for.
            targets_filter = spec.get("stack_targets_filter")
            targets_source = source if spec.get("stack_targets_source") else None
            if targets_filter or targets_source is not None:
                from .handlers.stack import _spell_targets_matching

                if not _spell_targets_matching(
                    self, item, dict(targets_filter or {}), caster_index,
                    source=targets_source,
                ):
                    continue
            # CR 115.9a's count and what the card asks about that one target,
            # through the same gate the spell loop above uses. An ability
            # announced its targets at CR 602.2b exactly as a spell announced
            # them at CR 601.2c, so it is the same question -- and a retarget
            # that skipped it here would offer every ability on the stack,
            # including ones aimed at something the card never named.
            if not self._stack_single_target_ok(item, spec, caster_index, source):
                continue
            # "…an opponent controls" (Teferi's Response): CR 113.8's
            # controller, the gate the spell loop above asks through the same
            # reader.
            if not _stack_controller_ok(item, spec, caster_index):
                continue
            item_card = getattr(item, "card", None)
            name = item_card.name if item_card is not None else "ability"
            # Top-first, the convention the spell enumeration above emits and
            # the cast/activate action resolves by.
            targets.append({
                "kind": "stack",
                "stack_index": depth - 1 - i,
                "name": f"{name}'s {kind} ability",
            })
        return targets


def _stack_controller_ok(item, spec: dict, caster_index: int) -> bool:
    """Whether a stack object's controller is the one *spec* names.

    "counter target artifact spell **you control**" (Goblin Artisans),
    "…spell or ability **an opponent controls**" (Teferi's Response). The seat
    that put the object on the stack — a spell's controller by CR 112.2, an
    ability's by CR 113.8 — measured against the seat doing the looking, which
    is the reading ``handlers/stack._counter_controller_refusal`` makes at
    resolution. One function for both stack enumerations, because the question
    is the same for a spell and an ability and it was asked of neither: the
    handler declined after the cost was paid.
    """
    wanted = spec.get("stack_controller")
    if wanted is None:
        return True
    mine = getattr(item, "caster_index", None) == caster_index
    return mine if wanted == "you" else (not mine if wanted == "opponent" else False)
