"""Lord buffs: "other Goblins you control get +1/+1" (CR 611.3a, layers 6 and 7c).

What each source gives and whom it reaches is derived from its own printed
sentence by ``engine/lord_buffs.py``; ``_recalculate_lord_buffs`` reads that
table and honours every field of it, rebuilding every channel it writes from
the current board, so removal is the absence of a contribution rather than
a delta someone has to subtract (CR 611.3b).

``_lord_buff_matches`` is the one answer to "does this lord reach this
permanent?", asked through the CR 613 accessors. It has two readers: the
refresh here, and the protection reader (``ProtectionMixin``) that derives a
granted quality from the same buff. ``_lord_buff_condition`` and the table
of named conditions (``_LORD_BUFF_CONDITIONS``, held to ``engine/lord_buffs.py``
by ``tests/engine/test_lord_buff_table.py``) are what a buff may hang on.
"""

from __future__ import annotations

from dataclasses import replace

from ..auras import auras_attached_to, conditional_ability_lines_for
from ..named_counters import counters_on
from ..granted_abilities import bind_granter
from ..keywords import (add_derived_ability_line, add_derived_grant,
                        add_derived_removal, clear_derived_grants)
from ..land_animation import LAND_ANIMATIONS_REACHING
from ..layer_bridge import QUALIFIED_BUFFS
from ..lord_buffs import LORD_BUFF_KIND, LordBuff, lord_buff_from_payload
from ..handlers._targets import attached_host
from ..search_filters import name_key
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..static_bonuses import (condition_is_per_recipient,
                              conditional_static_holds)


class LordBuffsMixin:
    def _chosen_color_permanent_condition(self, source_perm: Permanent) -> bool:
        """Jihad: whether "the chosen player controls a nontoken permanent of
        the chosen color" currently holds for *source_perm*'s stored choices."""
        seat = source_perm.metadata.get("chosen_player_index")
        color = source_perm.metadata.get("chosen_color")
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)) or not color:
            return False
        return any(
            not perm.metadata.get("is_token") and color in self._effective_colors(perm)
            for perm in self.controlled_by(seat)
        )

    def _chosen_color_most_common_condition(self, source_perm: Permanent) -> bool:
        """Call to Arms: whether "the chosen color is the most common color
        among nontoken permanents the chosen player controls **but isn't tied
        for most common**" holds for *source_perm*'s stored choices.

        A strict maximum, which is what the second half of the clause says and
        why it is one predicate rather than a superlative plus a rider. A
        multicoloured permanent is counted once for every colour it is
        (CR 105.2 makes it one object of several colours, not several objects),
        and a colourless board has no most common colour at all — every colour
        is tied at nothing, so the answer is False rather than vacuously True.

        The sibling condition beside this one asks "controls **a**"; the census
        is the only difference, which is why the two live in one table.
        """
        seat = source_perm.metadata.get("chosen_player_index")
        color = source_perm.metadata.get("chosen_color")
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)) or not color:
            return False
        # The census itself is ``engine/color_census.py``'s — the one count the
        # Invasion Djinns, Barrin's Unmaking and Tsabo's Assassin also ask, over
        # "all permanents" where this card names a narrower set. What is this
        # card's own is the set and the strictness (``tied=False``).
        from ..color_census import color_is_most_common

        return color_is_most_common(
            self, color, tied=False,
            permanents=[
                perm for perm in self.controlled_by(seat)
                if not perm.metadata.get("is_token")
            ],
        )

    def _lord_buff_matches(self, target_perm, source_perm, buff) -> bool:
        """Whether *buff*, contributed by *source_perm*, reaches *target_perm*.

        Every field of the derived filter, checked through the CR 613 accessors
        — an animated Swamp is a creature by layer 4 before a creature anthem is
        considered in layer 7c, and the printed type line is not the authority on
        either that or the subtype.

        A method rather than a local because two readers ask it now: the layer-7c
        refresh that applies the P/T, and the protection reader that derives a
        granted quality from the same buff. Two copies would be two answers to
        "does this lord reach this creature?".
        """
        filt = buff.filter
        # Which card type the anthem is about, read off the sentence rather
        # than assumed. This was `is_creature`, asked above every field of the
        # filter — and CR 613 has never said "creature": layers 6 and 7c apply
        # to every permanent, so "noncreature artifacts have shroud" (Spectral
        # Guardian) was unreachable for want of a question nobody was asking.
        # Through `has_type` (CR 613 layer 4) like every other type read here,
        # so an animated Swamp is a creature before a creature anthem considers
        # it.
        if not any(target_perm.has_type(word) for word in filt.card_types):
            return False
        # "**Non**creature artifacts" — the exclusion, OR'd the way every other
        # negative type test in this engine is: a permanent naming any excluded
        # type is out.
        if any(target_perm.has_type(word) for word in filt.excluded_types):
            return False
        if filt.other_than_source and (
            target_perm is source_perm
            # "**Other** creatures you control get -1/-1." (Vampirism.) On an
            # Aura the word is measured from the creature it enchants - the
            # Aura is no creature, so there is nothing else for it to mean -
            # and the host was taking its own Aura's penalty.
            or target_perm is attached_host(self, source_perm, last_known=False)
        ):
            return False
        # "Creatures **you control**" / "creatures your opponents control".
        # CR 109.5: "you" is the seat controlling the permanent whose static
        # ability this is, which is *source_perm*'s — not the reader's and not
        # the buffed permanent's.
        #
        # This was the layer-7c caller's alone, applied by narrowing the set of
        # battlefields it walked. Then a second reader arrived
        # (:meth:`_protection_qualities`, for a lord that grants protection
        # from a quality) and asked this predicate without the narrowing, so
        # Feline Sovereign's "Other Cats **you control** … have protection from
        # Dogs" shielded an opponent's Cats too: the P/T half of one sentence
        # was scoped and the keyword half was not. The seat is part of "does
        # this lord reach this permanent?", so it is answered here, once —
        # which is this method's whole reason for being a method.
        if filt.controller in ("you", "opponent"):
            source_seat = self.controller_index_of(source_perm)
            target_seat = self.controller_index_of(target_perm)
            if source_seat is None or target_seat is None:
                return False
            same_seat = source_seat == target_seat
            if filt.controller == "you" and not same_seat:
                return False
            if filt.controller == "opponent" and same_seat:
                return False
        if filt.colors and not (set(filt.colors) & self._effective_colors(target_perm)):
            return False
        # "**Nonblack** creatures get -1/-1." (Ascendant Evincar.) The same
        # layer-5 reader the other way round: a creature in any excluded colour
        # is out, and a colourless one is in (CR 105.2c).
        if filt.excluded_colors and (
            set(filt.excluded_colors) & self._effective_colors(target_perm)
        ):
            return False
        if any(not target_perm.has_type(subtype) for subtype in filt.subtypes):
            return False
        # "…**and other Treefolk creatures**" as the second half of a union
        # (Verdeloth the Ancient): a creature of any excluded type is out,
        # through the same layer-4 reader the positive test above asks.
        if any(target_perm.has_type(subtype) for subtype in filt.excluded_subtypes):
            return False
        # "**Legendary** creatures you control have …" (Legends' five banding
        # lands). A supertype is not a type: ``has_type`` answers about card
        # types and creature types and would say no to every legend, so this
        # reads the type line through the same helper
        # ``permanent_matches_filter`` uses for the ``supertypes`` payload key.
        # ``effective_card``, so a copy answers with the line it copied
        # (CR 707.2) and a text change is folded in.
        if filt.supertypes:
            held = target_perm.effective_supertypes
            if not all(word in held for word in filt.supertypes):
                return False
        # "…with a +1/+1 counter on it" (Pridemalkin): the counter record, not
        # the P/T bonus — a pump writes power_bonus and places no counter, so
        # reading the bonus would buff the wrong creatures.
        if filt.with_plus1_counter and int(
            target_perm.metadata.get("plus_counters", 0)
        ) <= 0:
            return False
        # "Creatures named Kobolds of Kher Keep" (Rohgahh of Kher Keep). By
        # *name*, never identity — a second copy and a token wearing the name
        # both match, and the buffing lord matches itself when it shares it
        # (Ivory Guardians prints no "other"). ``effective_card``, so a copy
        # answers with the name it copied (CR 707.2); ``name_key`` on both
        # sides, so the parser's lowercase rendering equals Oracle's spelling
        # — the same comparison ``permanent_matches_filter`` makes for the
        # payload key this field mirrors.
        if filt.named and name_key(
            target_perm.effective_card.name
        ) != name_key(str(filt.named)):
            return False
        # "Creatures **with flying** get +1/+1." (Serra Aviary.) Layer 6 asked
        # from layer 7c — ``has_keyword``, never ``card.keywords``, so a
        # creature wearing an Aura's flying is in the anthem (CR 613.1f) and one
        # a removal took it from is out. The reads-not-recompute direction is
        # what makes that free: this predicate runs on every recompute and the
        # answer is derived each time, so a word gained or lost moves the
        # creature in or out with nothing to add back or subtract (CR 613.5).
        if any(not target_perm.has_keyword(word) for word in filt.with_keywords):
            return False
        # "Creatures **without flying** have reach." (Chaosphere.) The same
        # layer-6 question negated, through the same accessor -- so a creature
        # given flying leaves the anthem on the next read and one that lost it
        # joins, with nothing to add back or subtract (CR 613.5).
        if any(target_perm.has_keyword(word) for word in filt.without_keywords):
            return False
        # "Each land **of the chosen type** has phasing." (Shimmer.) The one
        # field of this filter whose word is not in the sentence: it was chosen
        # as *source_perm* entered (CR 614.1c) and recorded there, so this is
        # the only reader that can answer it — which is exactly why the pure
        # matcher one file over refuses the key outright.
        #
        # Through ``has_type`` like every other type read here (CR 613 layer 4),
        # so a land Phantasmal Terrain turned into an Island is an Island. No
        # word recorded yet means the anthem reaches nothing, which is the safe
        # direction: dropping the narrowing would phase out every land there is.
        if filt.chosen_land_type:
            word = getattr(source_perm, "metadata", {}).get("chosen_land_type")
            if not word or not target_perm.has_type(str(word)):
                return False
        # "All creatures **of the chosen type** get -1/-1." (Engineered
        # Plague.) The branch above one card type over, and read the same way:
        # the word was chosen as *source_perm* entered (CR 614.1c, CR 205.3m)
        # and recorded on it, so this is the only reader that can answer it —
        # which is why ``subject_filters`` refuses the key for a caller holding
        # no source.
        #
        # Through ``has_type`` (CR 613 layer 4) like every other type read
        # here, so a creature an effect made a Zombie is a Zombie and one whose
        # types were replaced is not. No word recorded yet reaches nothing,
        # which is the safe direction: a dropped narrowing would put -1/-1 on
        # every creature on the battlefield.
        if filt.chosen_creature_type:
            word = getattr(source_perm, "metadata", {}).get("chosen_creature_type")
            if not word or not target_perm.has_type(str(word)):
                return False
        # "…as long as **that player** controls three or fewer lands." (Sheltering
        # Prayers.) A condition whose pronoun is the permanent being reached, so
        # it is part of "does this lord reach this permanent?" — asked here, once,
        # for every reader of that question, while the source-level gates
        # (``_lord_buff_condition`` with no recipient) let it through. The seat
        # handed in is the source's (CR 109.5), and is not what the clause reads:
        # "that player" is the *recipient's* controller.
        if condition_is_per_recipient(buff.condition):
            source_seat = self.controller_index_of(source_perm)
            if source_seat is None or not self._lord_buff_condition(
                source_seat, source_perm, buff.condition, recipient=target_perm
            ):
                return False
        return True

    def _recalculate_lord_buffs(self) -> None:
        """Apply every lord buff on the battlefield (CR 611.3a, layers 6 and 7c).

        A static ability is not locked in: it applies whenever its criteria are
        met, so this is recomputed from the current board rather than adjusted
        incrementally. What each source gives and who it reaches is derived from
        its own printed sentence by ``engine/lord_buffs.py`` — this method reads
        that table and honours every field of it. Before the table it read the
        colour and the controller off a bare ``static_line`` and nothing else,
        with the subtype lords re-parsed by a second regex further down, so a
        subtype, an "other", or a state qualifier had to become either a new
        instruction kind or a silently dropped restriction.

        Nothing accumulates. Every channel written below is cleared by this same
        function immediately before it is rebuilt, which is what makes removal
        the absence of a contribution rather than a delta someone has to
        remember and subtract (CR 611.3b).
        """
        all_perms = list(self.all_permanents())

        # Step 1: clear the derived channels this function owns.
        for perm in all_perms:
            perm.metadata.pop("static_buff_power", None)
            perm.metadata.pop("static_buff_toughness", None)
            perm.metadata.pop(QUALIFIED_BUFFS, None)
            # Clears the *three* layer-6 derived channels together — the
            # granted words, the removed words and the granted printed lines.
            clear_derived_grants(perm)

        def _add_static_buff(
            perm: Permanent, buff: LordBuff, observer: "int | None"
        ) -> None:
            if not (buff.power or buff.toughness):
                return
            qualifiers = buff.filter.qualifiers
            if not qualifiers:
                perm.metadata["static_buff_power"] = (
                    int(perm.metadata.get("static_buff_power", 0)) + buff.power
                )
                perm.metadata["static_buff_toughness"] = (
                    int(perm.metadata.get("static_buff_toughness", 0)) + buff.toughness
                )
                return
            # A qualified buff is contributed here but *evaluated* when P/T is
            # read (layer_bridge.qualifier_holds), so it tracks a creature
            # tapping or attacking between recomputes.
            # Keyed by the whole tuple of states, so two buffs are summed
            # together only when they answer to the same description. Keying by
            # one word would merge "untapped" with "untapped and not attacking"
            # and apply the stricter buff on the looser test.
            # Keyed by the states **and the contributing lord's seat**: one
            # qualifier ("attacking you") is a relation to CR 109.5's "you",
            # so two opposing Watchdogs describe two different sets and their
            # contributions must not be summed into one entry.
            qualified = perm.metadata.setdefault(QUALIFIED_BUFFS, {})
            key = (qualifiers, observer)
            power, toughness = qualified.get(key, (0, 0))
            qualified[key] = (power + buff.power, toughness + buff.toughness)


        # A copy uses the copied creature's copiable card (types + abilities), so
        # lord static abilities and subtype checks resolve against it (CR 707.2).
        # ``Permanent.effective_card`` is that answer, and it also applies the
        # CR 613 layer-3 text change — a local re-implementation of the copy half
        # silently skipped the text half, which is the second-opinion bug this
        # whole pass exists to remove.
        def _eff_card(perm: Permanent):
            return perm.effective_card

        # A Magical Hack land-word swap on the lord itself needs nothing here.
        # It rewrites the walk in the lord's *text* (mountainwalk ->
        # islandwalk on Goblin King), so the buff this loop derives is compiled
        # from the changed line and already says islandwalk. Patching the
        # derived keywords a second time was the layer-3-at-each-reader shape.

        _matches = self._lord_buff_matches

        # Step 2: re-apply from every permanent currently on the battlefield.
        #
        # **Gathered first, then applied in two passes, in CR 613's own order.**
        # A lord contributes to two layers — 6 (the keyword grants and removals)
        # and 7c (the P/T delta) — and layer 6 is applied first (CR 613.3,
        # CR 613.4). That was invisible while every filter asked only about
        # printed characteristics; "Creatures **with flying** get +1/+1" (Serra
        # Aviary) makes the 7c pass ask a layer-6 question, so a single pass
        # would answer it off a half-built layer 6 and the anthem would reach
        # or miss a creature depending on the order the battlefield happens to
        # hold its lords in.
        #
        # A keyword-filtered buff that itself *grants* a keyword is CR 613.8b's
        # dependency loop, and it gets 613.8b's answer: pass 2a reads layer 6 as
        # it stood when the recompute began, which is timestamp order.
        gathered: list[tuple] = []
        for ctrl_seat, source_perm in self.permanents_with_controller():
            program = compile_card_oracle(_eff_card(source_perm))
            for instr in program.instructions:
                if instr.kind != LORD_BUFF_KIND:
                    continue
                buff = lord_buff_from_payload(instr.payload)
                if buff.condition and not self._lord_buff_condition(
                    ctrl_seat, source_perm, buff.condition
                ):
                    continue
                if buff.per_counter:
                    # "All creatures get +1/+0 **for each time counter on this
                    # artifact**." (Infinite Hourglass.) The delta is read off
                    # the *source* at every recompute, which is what CR 613.4b
                    # asks of a value that keeps changing — and why the counter
                    # word travels on the buff rather than the size being
                    # frozen when the sentence compiled. Zero counters is no
                    # contribution at all, not a zero one: the buff carries only
                    # a P/T delta (``lord_buffs.LordBuff.per_counter`` refuses
                    # the combination with anything else), so there is nothing
                    # else it could still be giving.
                    scale = counters_on(source_perm, buff.per_counter)
                    if scale <= 0:
                        continue
                    buff = replace(
                        buff, power=buff.power * scale, toughness=buff.toughness * scale
                    )
                gathered.append((source_perm, buff))

        def _reached_by(source_perm, buff):
            # Every permanent on every battlefield, because "creatures you
            # control" is a question the matcher answers (CR 109.5, see
            # ``_lord_buff_matches``). This loop used to pre-narrow the
            # battlefields it walked, which made the seat the *caller's*
            # answer — and the second caller of that predicate did not have
            # it, so a protection grant scoped to one seat reached both.
            for target_perm in self.all_permanents():
                if _matches(target_perm, source_perm, buff):
                    yield target_perm

        # Pass 2a — layer 6 (CR 613.3): every ability this board's lords grant
        # or take away ("Other Goblins … have mountainwalk", Gravity Sphere's
        # "All creatures lose flying").
        for source_perm, buff in gathered:
            if not (buff.keywords or buff.lost_keywords or buff.granted_ability):
                continue
            for target_perm in _reached_by(source_perm, buff):
                for keyword in buff.keywords:
                    # Stamped with the lord's own timestamp (CR 613.7a), which
                    # is what orders the grant against a "loses all abilities".
                    add_derived_grant(
                        target_perm, keyword, timestamp=source_perm.timestamp
                    )
                for keyword in buff.lost_keywords:
                    add_derived_removal(target_perm, keyword)
                # …and the sentence half of the same layer (CR 113.3): a quoted
                # ability is granted here rather than in pass 2b because it is
                # layer 6 like the words beside it, and because a granted
                # ability can *be* one of the words a 7c filter asks about —
                # '"Sliver creatures have \"...\"" gets +1/+1' is not printed
                # today, and putting the grant in the later pass would be the
                # ordering bug the two passes exist to prevent, waiting.
                if buff.granted_ability:
                    add_derived_ability_line(
                        target_perm, buff.granted_ability,
                        timestamp=source_perm.timestamp,
                    )

        # Pass 2b — layer 7c (CR 613.4c), over a board whose layer 6 is
        # complete.
        for source_perm, buff in gathered:
            observer = self.controller_index_of(source_perm)
            for target_perm in _reached_by(source_perm, buff):
                if buff.per_shared_creature_type:
                    # "Each creature gets +1/+1 **for each other creature on
                    # the battlefield that shares at least one creature type
                    # with it**." (Coat of Arms.) The one scale in this family
                    # counted **per buffed creature** rather than off the
                    # source: the set it counts is defined by a relation to the
                    # creature being buffed, so two creatures under the same
                    # Coat of Arms take different numbers and the multiply
                    # cannot be lifted out of this loop the way
                    # ``per_counter``'s is.
                    #
                    # Zero shared types is no contribution rather than a zero
                    # one, exactly as the per-counter branch above treats an
                    # empty artifact: the buff carries only a P/T delta, so
                    # there is nothing else it could still be giving.
                    scale = self._creatures_sharing_a_type_with(target_perm)
                    if scale <= 0:
                        continue
                    _add_static_buff(
                        target_perm,
                        replace(
                            buff,
                            power=buff.power * scale,
                            toughness=buff.toughness * scale,
                        ),
                        observer,
                    )
                    continue
                _add_static_buff(target_perm, buff, observer)

        # Step 3: conditional self-grants — the keyword half of "…as long as
        # <condition>" (Sigiled Contender's lifelink, Gnarled Sage's
        # vigilance). Written in this pass because it owns the derived-grant
        # channel's clear/rebuild: a grant written by any other pass would be
        # wiped whenever this one runs alone. The P/T half is contributed by
        # _refresh_dynamic_creatures into its own derived channel.
        for cs_seat, cs_perm in self.permanents_with_controller():
            for cs in compile_card_oracle(_eff_card(cs_perm)).instructions:
                if cs.kind != "conditional_static":
                    continue
                cs_keywords = cs.payload.get("keywords") or ()
                # …and the *sentence* half of the same layer: an ability the
                # static hands over as a printed line — "…this creature has
                # "At the beginning of your upkeep, sacrifice a creature.""
                # (Wayward Angel), "…and can't block" (Childhood Horror, read
                # as the sentence it abbreviates). On the derived-ability
                # channel the quoted lord grant in pass 2a and the Aura's
                # criterion grant in step 4 already use, and here for this
                # step's own reason: the pass owns that channel's clear and
                # rebuild, so the line is gone with the condition (CR 611.3a)
                # and there is nothing to undo.
                cs_lines = cs.payload.get("ability_lines") or ()
                if not (cs_keywords or cs_lines):
                    continue
                if not conditional_static_holds(
                    self, cs_seat, cs_perm, cs.payload.get("condition") or {}
                ):
                    continue
                # "Enchanted creature has first strike as long as it's blocking
                # and you control a snow land." (Snow Devil.) The same
                # instruction with the grant landing on the host, read off the
                # same ``subject`` key ``_refresh_dynamic_creatures`` already
                # reads for the P/T half — one sentence, one instruction, one
                # answer about which permanent it is about.
                #
                # The seat stays the Aura's (CR 109.5), so "you control a snow
                # land" is measured from whoever controls the Aura even when
                # the creature belongs to somebody else.
                #
                # **Here rather than in ``layer_bridge``**, where the
                # unconditional Aura keyword grants live and where the CR 613.7e
                # attach timestamp is available. ``collect_ability_effects`` is
                # deliberately game-free — the board half of this condition
                # needs both the game and a seat, and giving a layer collector a
                # game handle is the read `tests/engine/test_layer_reads.py`
                # exists to keep out. The cost is the timestamp: this grant
                # sorts with the derived channel rather than at the Aura's
                # attach time. Nothing in the pool orders two contending
                # keyword grants, and a keyword granted twice is granted once.
                recipient = cs_perm
                if cs.payload.get("subject") == "attached":
                    recipient = attached_host(self, cs_perm, last_known=False)
                    if recipient is None:
                        continue
                for keyword in cs_keywords:
                    # The granting object's stamp (CR 613.7a/e): the permanent
                    # itself, or the Aura that says "enchanted creature has …".
                    add_derived_grant(
                        recipient, keyword, timestamp=cs_perm.timestamp
                    )
                for line in cs_lines:
                    if recipient is not cs_perm:
                        # An Aura's quote on its host names the Aura as the
                        # one object granting it (CR 201.5a) — the binding
                        # ``aura_granted_ability_lines`` makes for the
                        # unconditional quote.
                        line = bind_granter(
                            line, _eff_card(cs_perm).name, cs_perm.permanent_id
                        )
                    add_derived_ability_line(
                        recipient, line, timestamp=cs_perm.timestamp
                    )

        # Step 3b: the keywords a land animator gives the lands it animates —
        # "Lands you control are 2/2 creatures **with first strike**." (Natural
        # Emergence.) Layer 6, and written here for step 3's reason: this pass
        # owns the derived-grant channel's clear and rebuild, so a grant made
        # by the layer-4 refresh would be wiped the next time this ran alone.
        # Which lands is **the layer-4 pass's answer**, read off the record
        # it left on each land (``LAND_ANIMATIONS_REACHING``), and not the
        # noun phrase asked again here. CR 613.6: the effect started to apply
        # in layer 4 and "will continue to be applied to the same set of
        # objects" in this one — a set decided against that layer's
        # intermediate state, which the finished layer this pass could ask
        # may no longer describe. So a land cannot have the keyword without
        # being one the animator made a creature, by construction.
        for target_perm in all_perms:
            for animator, animation in (
                target_perm.metadata.get(LAND_ANIMATIONS_REACHING) or ()
            ):
                for keyword in animation.keywords:
                    # The **animator's** timestamp (CR 613.7a). This read
                    # ``source_perm`` — a name left over from the loops above,
                    # holding whichever permanent they happened to visit last
                    # — so a Natural Emergence older than a Humility kept its
                    # lands' first strike whenever a newer permanent was last
                    # in that walk.
                    add_derived_grant(
                        target_perm, keyword, timestamp=animator.timestamp
                    )

        # Step 4: an ability an **Aura** grants its host in quotes *while the
        # host answers a criterion* — 'As long as enchanted permanent is red or
        # green, it has "At the beginning of your upkeep, sacrifice this
        # permanent unless you pay its mana cost."' (Essence Leak.)
        #
        # On the derived-ability channel the quoted lord grant in step 2 uses,
        # and in this pass for step 3's reason: the pass owns that channel's
        # clear and rebuild, so the line is re-derived from the board every
        # time and a host that stops being red simply is not handed it again
        # (CR 611.3a). The unconditional Aura quote is folded in by
        # ``Permanent.effective_card`` itself; this one cannot be, because the
        # criterion is a layer-5 question and needs the game.
        for _host_seat, host in self.permanents_with_controller():
            for aura in auras_attached_to(host):
                # CR 109.5: the Aura's controller, not the host's — the two
                # part company whenever one is cast on an opponent's permanent,
                # which is what this card is for.
                aura_seat = self.controller_index_of(aura)
                if aura_seat is None:
                    continue
                for line in conditional_ability_lines_for(
                    self, aura, aura_seat, host
                ):
                    add_derived_ability_line(host, line, timestamp=aura.timestamp)

    # Conditions a lord buff may hang on, keyed by what engine/lord_buffs.py
    # derives. A condition that table can name with no predicate here would be a
    # buff applied unconditionally, which is the failure this whole family had;
    # tests/engine/test_lord_buff_table.py holds the two lists to each other.
    _LORD_BUFF_CONDITIONS = {
        "chosen_color_permanent": "_chosen_color_permanent_condition",
        "chosen_color_most_common": "_chosen_color_most_common_condition",
    }

    def _creatures_sharing_a_type_with(self, permanent: Permanent) -> int:
        """How many *other* creatures on the battlefield share a creature type
        with *permanent* (Coat of Arms).

        Types through the layer accessor, not the printed line: a Clone, an
        animated land given a creature type and a Magical Hack's rewritten word
        are all CR 613 layer 4, and Coat of Arms counts what a permanent *is*
        rather than what it was printed as. ``computed_types`` is the same
        reader ``has_type`` goes through, so the answer here and the answer to
        "is this a Goblin?" cannot disagree.

        Every battlefield, because the printed phrase names no controller — the
        sentence says "on the battlefield", which in a two-seat game is both of
        them.

        A creature with no creature types at all shares nothing and is counted
        by nobody, which is the printed card: a typeless token under a Coat of
        Arms gets +0/+0.
        """
        # Function-level, like the LAND_TYPES read in
        # ``entry_choices._default_chosen_land_type``: the vocabulary is loaded
        # from `data/vocabulary/` and this module is imported by the grammar's
        # own consumers.
        from ..grammar.vocabulary import CREATURE_TYPES as CREATURE_TYPE_WORDS
        from ..layer_bridge import computed_types

        mine = {
            subtype for subtype in computed_types(permanent)[1]
            if subtype in CREATURE_TYPE_WORDS
        }
        if not mine:
            return 0
        total = 0
        for other in self.all_permanents():
            if other is permanent or not other.is_creature:
                continue
            if mine & {
                subtype for subtype in computed_types(other)[1]
                if subtype in CREATURE_TYPE_WORDS
            }:
                total += 1
        return total

    def _lord_buff_condition(
        self,
        seat: int,
        source_perm: Permanent,
        condition: str | dict,
        recipient: Permanent | None = None,
    ) -> bool:
        # A dict is a lowered condition payload from the grammar's statics
        # production ("as long as an opponent controls a nontoken red
        # permanent", Ivory Guardians), answered by the same evaluator every
        # ``conditional_static`` payload gets — the lowering refused anything
        # that evaluator does not test. A string is a key into the legacy
        # table above (Jihad, whose stored choices no payload can express).
        #
        # A **per-recipient** condition ("…as long as that player controls
        # three or fewer lands", Sheltering Prayers) is not answered here at
        # source level: it is the buffed permanent's question, asked by
        # ``_lord_buff_matches`` with *recipient* named. Asked here without one
        # it holds, so the source-level gate does not drop the buff before the
        # per-permanent question is ever put.
        if isinstance(condition, dict):
            if condition_is_per_recipient(condition) and recipient is None:
                return True
            return conditional_static_holds(
                self, seat, source_perm, condition, recipient=recipient
            )
        return getattr(self, self._LORD_BUFF_CONDITIONS[condition])(source_perm)
