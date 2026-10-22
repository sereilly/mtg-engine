"""Board-wide statics, and the layer-4 pass they are applied by (CR 613).

"All Mountains are Plains", "All lands are no longer snow", "All Swamps are
1/1 black creatures that are still lands", Opalescence, Humility, Conspiracy:
a static that reaches every permanent of a description is recorded here as
*which source reaches which permanents*, rebuilt from the board on every
recompute (CR 611.3a), so a source leaving ends its effect by dropping out of
the list (``_refresh_global_statics``).

Its layer-4 parts are applied once for the whole board, with dependency
(``engine/type_statics.py``, CR 613.8): ``_board_type_statics`` hands that
pass every board-wide static with a type-changing part, and what this mixin
owns is **what each scope means** - ``_global_static_applies`` and the five
``_*_static`` builders, each asked of the layer's intermediate state rather
than of the permanent's finished answer. ``_refresh_land_animation`` writes
an animated land's colour and size (layers 5 and 7b) for the lands the pass
reached.

A permanent enters as the board will make it (CR 614.12):
``fold_board_statics_onto_entering`` and
``fold_land_type_statics_onto_entering`` run the same records with the
entering permanent in the list, before any entry reader asks.
"""

from __future__ import annotations

from ..auras import aura_animates_artifact
from ..color_changes import (add_derived_color_change,
                             clear_derived_color_changes)
from ..land_animation import (LAND_ANIMATION_KIND, LAND_ANIMATIONS_REACHING,
                              LandAnimation, land_animation_from_payload,
                              land_animation_reaches_types)
from ..land_types import (STATIC_LAND_TYPE_KIND, STATIC_SUPERTYPE_REMOVAL_KIND,
                          add_derived_land_type, clear_derived_land_types,
                          lost_abilities_to_type_change,
                          resolve_static_land_type_change,
                          static_land_type_change_applies,
                          static_supertype_removal_applies)
from ..layer_bridge import (attached_animation_type_effect,
                            global_static_type_effect,
                            land_animation_type_effect, land_type_effect,
                            lost_supertype_effect, seed_characteristics)
from ..type_changes import (LAND_ANIMATION_ORDER, add_derived_lost_supertype,
                            clear_derived_type_changes, set_animates_host,
                            set_static_type_order)
from ..type_statics import TypeStatic, apply_type_statics
from ..handlers._targets import attached_host
from ..subject_filters import subject_matches
from ..models import Permanent
from ..oracle import compile_card_oracle
from ..static_bonuses import conditional_static_holds


class BoardStaticsMixin:
    def _board_type_statics(
        self, all_permanents: list[Permanent], global_sources: list[tuple],
    ) -> tuple[list[TypeStatic], dict[int, TypeStatic]]:
        """Every board-wide static with a **layer-4** part, as the board-wide
        pass applies it (``engine/type_statics.py``).

        Five families, one list, because CR 613.7 and 613.8 order the *layer*
        and not each kind of card in it:

        * "All Mountains are Plains." (Conversion.) "Nonbasic lands are
          Mountains." (Blood Moon.) CR 305.7's replacement of a land's land
          types, or — with the printed rider — an addition (Blanket of Night).
        * "All lands are no longer snow." (Melting.) CR 205.4a's half of the
          type line, its contributions on their own channel because a
          supertype removal is not a land-type replacement.
        * "All Swamps are 1/1 black creatures that are still lands." (Kormus
          Bell.) The creature type; the colour and the size are layers 5 and
          7b and are written by ``_refresh_land_animation`` for the lands this
          reached.
        * the global statics that change a type (``global_statics
          .changes_types``): Titania's Song, Opalescence, Conspiracy, Dralnu's
          Crusade. *global_sources* is the caller's list, lingering ones
          included, so the two cannot disagree about which are out.
        * "As long as enchanted artifact **isn't a creature**, it's an artifact
          creature…" (Animate Artifact.) One permanent's, and here all the
          same: the condition is a scope over a type, so whether the Aura
          applies is a question about the intermediate state like the rest.

        What this method owns is **what each scope means**, read where it has
        always been read: ``land_types.py``'s two predicates,
        ``land_animation_reaches_types`` and ``_global_static_applies`` — each
        handed the layer's *intermediate* state by the pass rather than asking
        the permanent for its finished one. That is the whole change: the three
        refreshes this replaces each asked a finished or a previous-pass
        answer, and which permanents a type-scoped static reaches is a
        question about the moment it applies.

        Every static carries its **source's** timestamp (CR 613.7a, 613.7d) —
        ``Permanent.timestamp``, the one clock. The land-type ones carried a
        stand-in stamped the first time a refresh saw them
        (``land_types.static_source_timestamp``), which ordered them correctly
        against each other and only by coincidence against a Conspiracy.

        Returns the statics and, beside them, which of them is each global
        source's — keyed by ``id(source)`` — so the caller can turn the pass's
        reach back into its per-permanent source lists.
        """
        statics: list[TypeStatic] = []
        for source in all_permanents:
            # **The source's text before layer 6** (its ``card_before_layer_6``),
            # not ``effective_card``. These are layer-4 effects, applied while
            # the ability that generates them is still there (CR 613.1: layer
            # 4, then 5, then 6) and carried through their later layers
            # whatever becomes of it (CR 613.6). Read off the finished text,
            # a Blood Moon that Opalescence and Humility had made a creature
            # with no abilities stopped making Mountains, and a Kormus Bell
            # under Titania's Song stopped waking Swamps — twelve statics,
            # every one this loop gathers.
            source_card = source.card_before_layer_6
            for instr in compile_card_oracle(source_card).instructions:
                if instr.kind == STATIC_LAND_TYPE_KIND:
                    # "Basic lands of **the first chosen type** are **the
                    # second chosen type**." (Illusionary Terrain.) The
                    # sentence names no land type at all: both come from the
                    # ordered pair its controller chose as it entered.
                    # Resolved once, against the source, and then read like
                    # any other payload — a source that has not chosen yet
                    # resolves to None and contributes nothing, which is the
                    # honest answer rather than a static over every land or
                    # none.
                    payload = resolve_static_land_type_change(instr.payload, source)
                    if payload is not None:
                        statics.append(self._land_type_static(source, payload))
                elif instr.kind == STATIC_SUPERTYPE_REMOVAL_KIND:
                    statics.append(self._supertype_removal_static(source, instr.payload))
                elif instr.kind == LAND_ANIMATION_KIND:
                    statics.append(self._land_animation_static(
                        source, land_animation_from_payload(instr.payload),
                    ))
            host = source.metadata.get("attached_to")
            if host is not None and aura_animates_artifact(source_card.oracle_text):
                statics.append(self._attached_animation_static(source, host))
        from ..global_statics import changes_types

        by_source: dict[int, TypeStatic] = {}
        for source, static in global_sources:
            if not changes_types(static):
                continue
            # "Creatures you control are the chosen type" with no type chosen
            # yet (the source is still entering) is no effect at all, and so
            # not one for another to depend on.
            if global_static_type_effect(0, source, static, timestamp=0) is None:
                continue
            by_source[id(source)] = self._global_type_static(source, static)
            statics.append(by_source[id(source)])
        return statics, by_source

    def fold_land_type_statics_onto_entering(
        self, permanent: Permanent, controller_index: int
    ) -> None:
        """Write onto *permanent* — a land about to enter under
        *controller_index* — what the board's land-type statics will make of
        it once it is there.

        CR 614.12: an effect that modifies how a permanent enters is checked
        against "the characteristics of the permanent **as it would exist on
        the battlefield**, taking into account … continuous effects that
        already exist and would apply to the permanent". With Blood Moon out
        a nonbasic land enters as a Mountain: it does not enter tapped, pays
        no toll and enters with no counters, whatever it prints (CR 305.7, and
        each of those is a static ability of the land's own — CR 603.6d).

        The board-wide pass (``_refresh_global_statics``) is what decides that
        for a land on the battlefield, and it runs as the last thing an entry
        does — after the entry replacements were asked and the entry state
        was read, each of them of a land still reading as printed. So a
        Karoo entered tapped under a Blood Moon, a Lotus Vale ate two lands,
        and a Gemstone Mine came in with three counters for an ability it
        did not have.

        This is that pass for the one permanent, before any of those reads:
        the land-type statics on the battlefield, applied by
        ``engine/type_statics.py`` in its own order, with *controller_index*
        standing in for the controller the permanent does not have yet. What
        it writes is the derived contribution every reader already asks about
        (``land_types.lost_abilities_to_type_change``, through
        ``Permanent.effective_card``), and the entry's own recompute rebuilds
        it from the board a moment later like any other.

        Land types only. Whether an entering permanent is *also* something
        else by then (a creature under Kormus Bell) changes nothing about the
        abilities it has.
        """
        if "land" not in seed_characteristics(permanent).card_types:
            return
        clear_derived_land_types(permanent)
        statics = []
        for source in self.all_permanents():
            for instr in compile_card_oracle(source.effective_card).instructions:
                if instr.kind != STATIC_LAND_TYPE_KIND:
                    continue
                payload = resolve_static_land_type_change(instr.payload, source)
                if payload is not None:
                    statics.append(self._land_type_static(
                        source, payload, entering=(permanent, controller_index),
                    ))
        if statics:
            apply_type_statics([permanent], statics)

    def fold_board_statics_onto_entering(
        self, permanent: Permanent, controller_index: int
    ) -> bool:
        """Write onto *permanent* — about to enter under *controller_index* —
        what **every** board-wide static will make of it once it is there.
        Returns whether there was any to ask.

        CR 614.12 again, and the rest of it: the land-type fold above covers
        one family of static, and the rule names none. "Check the
        characteristics of the permanent as it would exist on the battlefield,
        taking into account … continuous effects that already exist and would
        apply to the permanent." So:

        * under **Humility** a creature enters with no ability — it does not
          enter tapped, enters with no counters, makes no "as this enters"
          choice (a Clone copies nothing) and pays no entry toll, whatever it
          prints; under **Titania's Song** a noncreature artifact likewise;
        * under Titania's Song, **Opalescence** or a land animator (Living
          Lands, Kormus Bell) the permanent is a *creature* as it enters — so
          a Containment Priest exiles one that was not cast, a played Forest
          included, and "creatures … enter tapped" reaches it.

        Every reader of an entry already asks the permanent through the CR 613
        accessors (``effective_card``, ``has_type``, ``is_creature``); what
        was missing is the contributions those accessors read, which
        ``_refresh_global_statics`` writes for a permanent on the battlefield
        as the **last** thing an entry does. This runs that same pass with the
        entering permanent in its list, before any of those reads — the pass
        itself, not a second reading of each family, so a static it learns
        tomorrow is folded here the same day. ``controller_index_of`` answers
        the entering seat for the one permanent while it runs.

        The entry's own recompute rebuilds everything from the real board a
        moment later; if the entry is *replaced* instead, the caller does
        (``_put_permanent_onto_battlefield``). What the pass remembers about
        which statics were out — Titania's Song lingers when it leaves — is
        put back as it was, because a permanent that has not arrived cannot
        have left.

        Not asked (no entry reader in the pool reads them): what a lord will
        grant the permanent, and its layer-7 size.
        """
        from ..global_statics import global_static_sources

        board = list(self.all_permanents())
        # Is there any static to ask? Nearly every entry in nearly every game
        # finds none, and pays for one walk of the board rather than a pass.
        judging = (
            bool(self.lingering_global_statics)
            or bool(global_static_sources(board))
            or any(
                instr.kind in (LAND_ANIMATION_KIND, STATIC_SUPERTYPE_REMOVAL_KIND)
                for source in board
                for instr in compile_card_oracle(source.effective_card).instructions
            )
        )
        if not judging:
            return False
        remembered = list(self._global_static_sources_last)
        lingering = list(self.lingering_global_statics)
        self._entering_under = (permanent, controller_index)
        try:
            self._refresh_global_statics(board + [permanent])
        finally:
            self._entering_under = None
            self._global_static_sources_last = remembered
            self.lingering_global_statics[:] = lingering
        return True

    def _land_type_static(
        self, source: Permanent, payload: dict, *,
        entering: tuple[Permanent, int] | None = None,
    ) -> TypeStatic:
        """"All Mountains are Plains." — one land-type static, for the pass.

        *entering* is a permanent that is on no battlefield yet and the seat
        it is about to enter under (:meth:`fold_land_type_statics_onto_
        entering`): "lands **you control**" is asked of that seat, because the
        control seam has no answer for it until it has arrived.
        """
        to_type = str(payload.get("to_type", ""))
        additive = bool(payload.get("additive"))

        def holder(permanent: Permanent) -> int | None:
            if entering is not None and permanent is entering[0]:
                return entering[1]
            return self.controller_index_of(permanent)

        def reaches(permanent: Permanent, types) -> bool:
            # Which lands a source reaches is `land_types.py`'s question, not
            # this method's: Conversion names a land type and Blood Moon names
            # a missing supertype, and a second reading of either here would
            # be the gate/dispatch split this engine keeps finding.
            return "land" in types.card_types and static_land_type_change_applies(
                payload, types,
                # "Lands **you control** are Plains" (Celestial Dawn). The one
                # fact about a candidate that is not a characteristic, read
                # through the control seam so a land the source's controller
                # has taken is one of theirs and a land they have lost is not.
                # Computed only when the payload asks, because
                # `controller_index_of` resolves layer 2 and this runs on
                # every refresh over every permanent.
                same_controller=(
                    holder(permanent) == self.controller_index_of(source)
                    if payload.get("controller_only") else None
                ),
            )

        return TypeStatic(
            source=source, timestamp=source.timestamp, label=source.card.name,
            reaches=reaches,
            effect=lambda permanent, stamp, order: land_type_effect(
                permanent, id(permanent), to_type, additive=additive,
                timestamp=stamp, sequence=order,
            ),
            record=lambda permanent, stamp, order: add_derived_land_type(
                permanent, to_type, timestamp=stamp, label=source.card.name,
                additive=additive, order=order,
            ),
        )

    def _supertype_removal_static(self, source: Permanent, payload: dict) -> TypeStatic:
        """"All lands are no longer snow." — Melting, for the pass."""
        word = str(payload.get("supertype") or "")
        return TypeStatic(
            source=source, timestamp=source.timestamp, label=source.card.name,
            reaches=lambda permanent, types: bool(word)
            and static_supertype_removal_applies(payload, types),
            effect=lambda permanent, stamp, order: lost_supertype_effect(
                id(permanent), word, timestamp=stamp, sequence=order,
            ),
            record=lambda permanent, stamp, order: add_derived_lost_supertype(
                permanent, word, timestamp=stamp, order=order,
                label=source.card.name,
            ),
        )

    def _land_animation_static(
        self, source: Permanent, animation: LandAnimation
    ) -> TypeStatic:
        """"All Swamps are 1/1 black creatures that are still lands." — the
        layer-4 half of a land animator, for the pass."""
        return TypeStatic(
            source=source, timestamp=source.timestamp, label=source.card.name,
            payload=animation,
            reaches=lambda permanent, types: land_animation_reaches_types(
                self, source, animation, permanent,
                types.card_types, types.subtypes,
            ),
            effect=lambda permanent, stamp, order: land_animation_type_effect(
                id(permanent), timestamp=stamp, sequence=order,
            ),
            record=lambda permanent, stamp, order: set_static_type_order(
                permanent, LAND_ANIMATION_ORDER, timestamp=stamp, order=order,
            ),
        )

    def _attached_animation_static(self, aura: Permanent, host: Permanent) -> TypeStatic:
        """"As long as enchanted artifact isn't a creature, it's an artifact
        creature…" — Animate Artifact's layer-4 half, for the pass.

        Its reach is one permanent and a condition on it, and the condition is
        why it is here: Titania's Song asks the same question of the same
        artifact from the other side, each changes the other's answer, and
        CR 613.8b applies such a loop in timestamp order — so the older of the
        two is the one that animates the artifact, and only the Song also
        takes its abilities.

        An Aura's timestamp is the moment it became attached (CR 613.7e).
        """
        return TypeStatic(
            source=aura,
            timestamp=int(aura.metadata.get("aura_timestamp", aura.timestamp)),
            label=aura.card.name,
            payload=host,
            reaches=lambda permanent, types: (
                permanent is host and "creature" not in types.card_types
            ),
            effect=lambda permanent, stamp, order: attached_animation_type_effect(
                id(permanent), timestamp=stamp, sequence=order,
            ),
            record=lambda permanent, stamp, order: set_static_type_order(
                permanent, aura.permanent_id, timestamp=stamp, order=order,
            ),
        )

    def _global_type_static(self, source: Permanent, static) -> TypeStatic:
        """A global static's layer-4 half (Conspiracy, Dralnu's Crusade,
        Titania's Song, Opalescence), for the pass."""
        return TypeStatic(
            source=source, timestamp=source.timestamp,
            label=f"{source.card.name} ({static.name})",
            reaches=lambda permanent, types: self._global_static_applies(
                static, permanent, source, self, types=types,
            ),
            effect=lambda permanent, stamp, order: global_static_type_effect(
                id(permanent), source, static, timestamp=stamp, sequence=order,
            ),
            record=lambda permanent, stamp, order: set_static_type_order(
                permanent, source.permanent_id, timestamp=stamp, order=order,
            ),
        )

    def _refresh_global_statics(self, all_permanents: list[Permanent]) -> None:
        """Record which permanents each board-wide static currently applies to.

        The list holds the **source permanents**, not a materialised effect, so
        `layer_bridge` derives the characteristics from the source's text on
        every recompute — and a source leaving the battlefield ends its effect
        by dropping out of this list. That is the same shape attached Auras use,
        and it is why there is no flag here to clear.

        Rebuilt from scratch each pass rather than adjusted, for the reason
        recorded on `_add_static_pt`: an adjustment that does not exactly match
        what it undid compounds, and CR 611.3a means this runs constantly.

        **Layer 4 first, and as one application** (``engine/type_statics.py``).
        A static that changes types (``global_statics.changes_types`` — and
        beside them every land-type static, supertype removal and land
        animator) starts to apply in layer 4, so which permanents it reaches is
        a question about that layer's *intermediate* state, in the order
        CR 613.7 gives and CR 613.8 rearranges; CR 613.6 then keeps it on "the
        same set of objects" in every later layer, which is why the reach the
        pass decides is recorded here as the static applying, whole. Every
        other static is judged afterwards, against the layer 4 the pass has
        just finished writing.

        It used to judge them all in one loop against whatever layer 4 the
        *previous* refresh had left: Dralnu's Crusade found the Goblin a
        Conspiracy had just made one refresh late, and a Conspiracy could not
        wait behind the effect that made a land a creature.
        """
        from ..global_statics import (STACK_STATICS_KEY, changes_types,
                                      global_static_sources,
                                      record_stack_statics)
        from ..stack_statics import stack_static_grant_sources

        # Both derived layer-4 channels are cleared before anything is judged,
        # so no candidate can read a previous pass's contribution as this
        # pass's board (CR 611.3b: a static's effect lasts exactly as long as
        # the rebuild keeps putting it back) — and before the sources are
        # gathered, because *whether a land is a source at all* reads one of
        # them: a land whose type an effect set has lost the ability that made
        # it one (CR 305.7, ``global_static_sources``). Gathered first, as
        # they were, a land Blood Moon had just stopped reaching stayed a
        # non-source for a pass.
        for perm in all_permanents:
            clear_derived_land_types(perm)
            clear_derived_type_changes(perm)
        sources = global_static_sources(all_permanents)
        # The same statics from the other zone (CR 113.6b): "As long as Torrent
        # of Lava is on the stack, each creature has …". Rebuilt from the stack
        # on every pass exactly as the battlefield half is, so a spell that has
        # resolved or been countered takes its grant with it — there is no flag
        # to clear, which is the whole reason both halves are recomputed rather
        # than adjusted.
        stack_sources = stack_static_grant_sources(getattr(self, "stack", ()))

        # A static that outlives its source (Titania's Song: "if this
        # enchantment leaves the battlefield, this effect continues until end of
        # turn"). Detected here rather than on a leave-battlefield hook because
        # this method already knows which sources were applying: one that was in
        # the list and is no longer on a battlefield has left, whichever way it
        # went. The cleanup step drops the lingering list (CR 514.2).
        on_battlefield = {id(perm) for perm, _ in sources}
        for perm, static in self._global_static_sources_last:
            if static.continues_until_eot and id(perm) not in on_battlefield:
                if not any(existing is perm for existing, _ in self.lingering_global_statics):
                    self.lingering_global_statics.append((perm, static))
        self._global_static_sources_last = list(sources)
        sources = sources + [
            (perm, static) for perm, static in self.lingering_global_statics
        ]
        type_statics, type_static_of = self._board_type_statics(all_permanents, sources)
        reach = apply_type_statics(all_permanents, type_statics)
        # **CR 305.7, now that layer 4 is this pass's.** The pass has just
        # written which lands a board-wide static sets the type of ("Nonbasic
        # lands are Mountains"), and such a land has lost every ability its
        # text gave it — the one that made it a source of a board-wide static
        # among them. So the sources are asked again here, of the same one
        # predicate, before any of them is judged against a permanent: The
        # Tabernacle at Pendrell Vale under Blood Moon grants nothing.
        #
        # Only the statics judged below. One with a layer-4 part was already
        # placed by the pass above, and whether *that* exists is a question
        # the pass would have to answer inside layer 4 (Blood Moon beside a
        # land that says "each land is a Swamp" — CR 613.8a's dependency on an
        # effect's existence); no land in the pool prints one, and
        # ``type_statics.py`` does not probe for it.
        sources = [
            (perm, static) for perm, static in sources
            if changes_types(static) or not lost_abilities_to_type_change(perm)
        ]
        for found in type_statics:
            # An attached animating Aura: whether it reached its host is the
            # answer every later layer reads (``auras.animating_auras``), so a
            # *no* is written down as carefully as a yes.
            # (Its payload is the host; no other static's is a permanent.)
            if isinstance(found.payload, Permanent):
                set_animates_host(found.source, any(
                    applied is found for applied in reach.get(id(found.payload), ())
                ))
        self._refresh_land_animation(all_permanents, reach)
        # "As long as there are seven or more cards in your graveyard, this
        # creature **is white** …" (Repentant Vampire; Wayward Angel's "is
        # black"). CR 613 layer 5 of a static, so a *derived* contribution on
        # the channel the animator's colour just above uses — and written
        # here, straight after that refresh, because it is what clears the
        # channel. Stamped with the permanent the ability is on (CR 613.7a):
        # the moment it entered, not the moment its condition last became
        # true, so a Lace cast at the creature afterwards still wins and a
        # Darkest Hour that was already there still loses.
        for cs_seat, cs_perm in self.permanents_with_controller():
            for cs in compile_card_oracle(cs_perm.effective_card).instructions:
                if cs.kind != "conditional_static" or not cs.payload.get("colors"):
                    continue
                if not conditional_static_holds(
                    self, cs_seat, cs_perm, cs.payload.get("condition") or {}
                ):
                    continue
                recipient = cs_perm
                if cs.payload.get("subject") == "attached":
                    recipient = attached_host(self, cs_perm, last_known=False)
                    if recipient is None:
                        continue
                add_derived_color_change(
                    recipient, list(cs.payload["colors"]),
                    timestamp=cs_perm.timestamp,
                    label=f"conditional colour ({cs_perm.card.name})",
                )
        # **Layer 5 before a scope that asks about colour.** "**Green**
        # creatures have …" (Breath of Dreams) reads what colour a permanent
        # is, and part of that answer is the list this loop writes: "All
        # creatures are black" (Darkest Hour) is on a creature as a source
        # recorded here. Judged in the one loop, the colour scope read the
        # list the *previous* refresh had left — so a Bears a Darkest Hour had
        # just stopped reaching was still black to the Breath for a pass, and
        # went without its upkeep.
        #
        # Not a dependency: CR 613.8a holds one only between two effects "in
        # the same layer", and the granted ability is layer 6 reading a layer
        # 5 that is finished by then. It is the order the refresh writes in.
        # So the statics whose scope asks about colour are judged in a second
        # walk, after the first has recorded every static that *sets* one —
        # none of which has a colour scope of its own (held to the pool by
        # ``tests/rules/test_color_effects_timestamp_order.py``), so one
        # deferral is the whole order.
        def asks_colour(static) -> bool:
            return bool(static.colors) and not changes_types(static)

        colour_scoped = any(asks_colour(static) for _source, static in sources)
        colour_scoped_on_stack = any(
            asks_colour(static) for _item, static in stack_sources
        )
        for perm in all_permanents:
            reached_by = reach.get(id(perm), ())
            # **A static's own source is not exempt.** The scope is whatever
            # the printed sentence says, and none of these templates says
            # "other" — "Creatures you control attack each combat if able" (the
            # Pirate token Pursued Whale gives each opponent) is a creature its
            # controller controls, so CR 508.1d compels the token itself along
            # with the rest of that seat's board. Skipping the source silently
            # exempted exactly the permanent the card is printed on, which for
            # this one is half the drawback the Whale's controller is paid for.
            #
            # The blanket skip cost the other two templates nothing and so hid
            # this: Energy Flux and The Tabernacle at Pendrell Vale are
            # enchantments and a land, and Titania's Song asks for a noncreature
            # *artifact* — each of them is excluded by
            # `_global_static_applies` on its own merits, which is where a
            # scope belongs.
            applying = [
                source
                for source, static in sources
                if not asks_colour(static)
                and (
                    # A type-changing static applies to exactly what the
                    # layer-4 pass found it reaching (CR 613.6)…
                    any(found is type_static_of.get(id(source)) for found in reached_by)
                    if changes_types(static)
                    # …and every other one to what its scope describes now
                    # that layer 4 is this pass's.
                    else self._global_static_applies(static, perm, source, self)
                )
            ]
            if applying:
                perm.metadata["global_static_sources"] = applying
            else:
                perm.metadata.pop("global_static_sources", None)
            # …and the same statics from a **spell on the stack** (CR 113.6b,
            # Torrent of Lava). The derived static is recorded rather than its
            # source, because a stack object's printed text carries the "as long
            # as … is on the stack" prefix `global_static_for` refuses — see
            # `global_statics.STACK_STATICS_KEY`.
            #
            # `source=None`: `_global_static_applies` needs one only for a scope
            # that is *relative* to its source's controller, and a spell on the
            # stack is not a permanent to compare seats with. That scope is
            # refused where the clause is read (`stack_statics._global_static`),
            # so nothing reaching here needs it.
            #
            # Each with the stack object's own timestamp (CR 613.7a, 613.7d —
            # ``StackItem.timestamp``), which is what a reader that orders
            # the granted ability against a loss of all abilities compares.
            record_stack_statics(perm, [
                (static, getattr(item, "timestamp", None) or 0)
                for item, static in stack_sources
                if not asks_colour(static)
                and self._global_static_applies(static, perm, None, self)
            ])
        # **Layer 6 before a static that is all layer 6 or later.** The walk
        # above has recorded which permanents "All creatures lose all
        # abilities" reaches, so whether a *source* still has the ability that
        # makes it one can be asked now — of this pass, not the last.
        #
        # A static with a layer-4 or layer-5 part is past caring: its effect
        # began to apply while the ability was there, and CR 613.6 carries it
        # through every later layer "even if the ability generating the effect
        # is removed during this process" (Titania's Song, Opalescence,
        # Conspiracy, Darkest Hour — and ``_board_type_statics`` reads the
        # land-type family the same way). One whose *whole* effect is layer 6
        # or later is the opposite case. "All artifacts have "…sacrifice this
        # artifact unless you pay {2}"" (Energy Flux) meets Humility in the
        # same layer, and applying Humility would end the Flux's effect
        # altogether — CR 613.8a's dependency on an effect's *existence* — so
        # the removal applies first whichever is older, and the Flux grants
        # nothing. The printed text said otherwise for as long as the source
        # stayed on the battlefield: an Energy Flux that Opalescence and
        # Humility had made a 1/1 with no abilities went on taxing artifacts.
        #
        # The remover itself is not asked. Humility under Opalescence strips
        # its own ability and applies all the same (an effect cannot depend on
        # itself), and two of them strip each other to the same board.
        from ..global_statics import removes_all_abilities
        from ..keywords import all_abilities_removed

        def later_layers_only(static) -> bool:
            return not (
                changes_types(static) or static.sets_colors is not None
                or static.sets_chosen_color or static.removes_abilities
            )

        gone = {
            id(source) for source, static in sources
            if later_layers_only(static)
            and (removes_all_abilities(source) or all_abilities_removed(source))
        }
        if gone:
            sources = [pair for pair in sources if id(pair[0]) not in gone]
            for perm in all_permanents:
                recorded = perm.metadata.get("global_static_sources")
                if not recorded:
                    continue
                kept = [source for source in recorded if id(source) not in gone]
                if kept:
                    perm.metadata["global_static_sources"] = kept
                else:
                    perm.metadata.pop("global_static_sources", None)
        # The second walk: every colour-setting static is on the permanents it
        # reaches, so layer 5 is this pass's and a colour scope can be asked.
        # Each list is rebuilt in the sources' own order rather than appended
        # to, so which static is recorded first does not come to depend on
        # which walk judged it.
        if colour_scoped:
            for perm in all_permanents:
                recorded = perm.metadata.get("global_static_sources") or ()
                applying = [
                    source
                    for source, static in sources
                    if (
                        self._global_static_applies(static, perm, source, self)
                        if asks_colour(static)
                        else any(source is held for held in recorded)
                    )
                ]
                if applying:
                    perm.metadata["global_static_sources"] = applying
                else:
                    perm.metadata.pop("global_static_sources", None)
        if colour_scoped_on_stack:
            for perm in all_permanents:
                recorded = perm.metadata.get(STACK_STATICS_KEY) or ()
                record_stack_statics(perm, [
                    (static, getattr(item, "timestamp", None) or 0)
                    for item, static in stack_sources
                    if (
                        self._global_static_applies(static, perm, None, self)
                        if asks_colour(static)
                        else any(static is held for held in recorded)
                    )
                ])

    #: The printed colour word a ``GlobalStatic``'s scope carries, as the symbol
    #: every filter payload in the engine spells a colour with. One map rather
    #: than a symbol in the table, because the *table* holds what the card
    #: prints.
    _COLOR_SYMBOLS = {
        "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
    }

    @staticmethod
    def _global_static_applies(
        static, permanent: Permanent, source=None, game=None, *, types=None,
    ) -> bool:
        """Whether *static* covers *permanent*.

        *types* is the layer-4 state to ask the **type** words of: the layer's
        intermediate ``Characteristics`` when the board-wide pass is deciding a
        type-changing static's reach (``engine/type_statics.py``), and absent —
        the permanent's finished answer — for every static that starts to
        apply in a later layer. One reading of each scope for both moments, so
        the pass and the refresh cannot disagree about a word.

        "Noncreature artifact" is the scope that needed the distinction. It
        read the **printed** type line for the creature half, because asking
        whether the permanent is *currently* a creature would include the type
        this very effect adds, and the answer would then depend on whether it
        had already been asked. The intermediate state is the rule's own answer
        to that (CR 613.6's example: the effect "is applied to all noncreature
        artifacts in layer 4 … even though those permanents aren't noncreature
        artifacts by then"): a Howling Mine is a noncreature artifact as
        Titania's Song starts to apply, and one Karn has already animated is
        not — the Song depends on that effect (CR 613.8a) and passes it by,
        abilities and all. Animate Artifact's own "as long as enchanted
        artifact isn't a creature" is the same question asked from the other
        side (``_attached_animation_static``); the two form a dependency loop,
        and the pass settles it by timestamp (CR 613.8b). The printed line
        still answers a caller with no intermediate state to offer, of which
        there is none for a type-changing static.

        *source* and *game* are needed only by a scope that is **relative** —
        "creatures **you** control" is a comparison between two seats (CR 109.5),
        which no read of the affected permanent alone can answer. A scope that
        needs them and is handed neither answers False, which is the safe
        direction: a board-wide effect applying to the wrong side is worse than
        one that does not apply.
        """
        # "**Other** enchantments have …" (Aura Flux). CR 109.5's exclusion,
        # asked in front of every scope rather than inside one, because the word
        # is a quantifier over whatever noun follows it and not part of the
        # noun. Read here and nowhere else, which is where the comment in
        # ``_apply_global_statics`` says a scope belongs.
        #
        # A static that says "other" and is handed no source cannot answer the
        # question at all, so it answers False — the safe direction this
        # docstring already states for a relative scope, and unreachable today:
        # the sourceless caller is the stack half, and ``stack_statics`` reads
        # only the "as long as this spell is on the stack" spellings, none of
        # which prints the word.
        if getattr(static, "other_than_source", False):
            if source is None or permanent is source:
                return False

        def has_type(word: str) -> bool:
            # ``Permanent.has_type``'s reading of a type word — a card type or
            # a subtype — over whichever state the caller is asking about.
            if types is None:
                return permanent.has_type(word)
            return word in types.card_types or word in types.subtypes

        if static.applies_to in ("artifact", "creature", "enchantment"):
            # Through the layer-6/4 accessors rather than the printed line, so
            # an animated land is a creature to The Tabernacle at Pendrell Vale
            # and a Clone of an artifact is an artifact to Energy Flux.
            if not has_type(static.applies_to):
                return False
            # "**Green** creatures have …" (Breath of Dreams). Asked through
            # ``subject_matches``, the one reader of what a printed noun phrase
            # means, so "green" here is the same question a targeting line or a
            # trigger's subject asks — and layer 5 for the same reason the type
            # word above is layer 4: a creature a lace has turned green is a
            # green creature, and one that stops being green stops paying the
            # upkeep with nothing to undo.
            if static.colors:
                from ..subject_filters import subject_matches

                if game is None:
                    return False
                return all(
                    subject_matches(
                        game, permanent,
                        {"color_filter": BoardStaticsMixin._COLOR_SYMBOLS[colour]},
                    )
                    for colour in static.colors
                )
            return True
        if static.applies_to == "noncreature_artifact":
            if types is not None:
                return has_type("artifact") and not has_type("creature")
            printed = permanent.card.type_line.lower()
            return "artifact" in printed and "creature" not in printed
        if static.applies_to == "non_aura_enchantment":
            # "Each other **non-Aura** enchantment …" (Opalescence.) Both halves
            # through the layer-4 accessor, which is the *opposite* choice from
            # the printed read one branch up and for a reason that is about the
            # sentence rather than about taste: the artifact row's creature half
            # names the very type its own static adds, so asking the layers
            # would make the answer depend on whether it had already been asked.
            # Nothing here is self-referential -- this static adds "creature",
            # and neither "enchantment" nor "aura" is a type it can grant -- so
            # the layers are safe and are what the words mean. A Licid that has
            # become an Aura is out while it is one, and an enchantment an
            # effect has turned into something else is judged on what it is now.
            return has_type("enchantment") and not has_type("aura")
        if static.applies_to == "nonland_permanent_you_control":
            # "**Nonland** permanents you control are white." (Celestial Dawn.)
            # The type half through the layer accessor, so a land this very
            # board has animated is still a land and stays out -- CR 305.7's
            # replacement does not stop a Plains being a land, and the printed
            # line would have said so wrongly for an animated one.
            if source is None or game is None or has_type("land"):
                return False
            return (
                game.controller_index_of(permanent)
                == game.controller_index_of(source)
            )
        if static.applies_to == "creature_type":
            # "All **Goblins** are black and are Zombies …" (Dralnu's Crusade.)
            # Through the layer-4 accessor, so a creature another effect has
            # made a Goblin is one and a Goblin that has lost the type is not.
            # Not self-referential the way the artifact row above is: the type
            # this static adds is never the type its own scope names.
            return bool(static.subtypes) and all(
                has_type(subtype) for subtype in static.subtypes
            )
        if static.applies_to == "nonland_permanent":
            # "All **nonland** permanents are the chosen color." (Shifting Sky.)
            # The branch above with no seat to compare: every battlefield's
            # nonland permanents, through the same layer accessor and for the
            # same reason — an animated land is still a land and stays out.
            return not has_type("land")
        if static.applies_to == "permanent":
            # "**All permanents** are colorless." (Thran Lens.) The widest noun
            # this table prints, and the one scope with nothing to test:
            # CR 109.2's description names every object on every battlefield,
            # its own source included -- which is what the comment in
            # ``_apply_global_statics`` means by a scope answering on its own
            # merits rather than by a blanket skip of the source.
            return True
        if static.applies_to == "creature_you_control":
            if source is None or game is None or not has_type("creature"):
                return False
            return (
                game.controller_index_of(permanent)
                == game.controller_index_of(source)
            )
        return False

    def _refresh_land_animation(
        self, all_permanents: list[Permanent], reach: dict[int, list[TypeStatic]],
    ) -> None:
        """Land animators turn lands of a named type into creatures while the
        source is on the battlefield (CR 613 layer 4).

        **Which lands is not decided here.** *reach* is the board-wide layer-4
        pass's answer (``engine/type_statics.py``): the statics that reached
        each permanent, in the order they applied. An animator's scope is a
        land type, so it depends on whatever makes a land that type (CR 613.8a)
        and its reach is a question about the layer's intermediate state —
        which is why this method no longer asks it of the finished layer after
        the fact. What is written here is everything an animation says that is
        *not* its place in layer 4: the flag the collector reads, the record
        of which animators reached the land, and the colour (layer 5). **The
        size (layer 7b) is not written at all**: ``layer_bridge
        .collect_pt_effects`` reads it off that record, one effect per
        animator at the animator's own timestamp (CR 613.7a), so it is ordered
        against a Humility, a Humble or a second animator by when each
        arrived. Nothing here knows which cards the animators are: Kormus
        Bell's colour and Living Lands' silence about colour are both payload
        (engine/land_animation.py).

        Its own pass, ahead of everything that asks "is this a creature?".
        This ran inside the same per-permanent loop as the layer-7a
        characteristic-defining P/T below, so within a single refresh a CDA
        counting creatures saw whatever the animation state had been at the
        *end of the previous pass* — a land animated this pass counted only
        from the next one. CR 613.1 applies layer 4 before layer 7 in one
        application, not across successive ones.

        Recomputed every call so the lands revert the moment the animating
        enchantment leaves (CR 611.3a/b). A land-type override (Evil Presence /
        Phantasmal Terrain) REPLACES the printed type (CR 305.7), so an
        overridden land animates by its override, not its printed type line.
        """
        position = {id(perm): index for index, perm in enumerate(all_permanents)}
        for permanent in all_permanents:
            # Every animator the pass found reaching this land, recorded for
            # the layers after this one (CR 613.6: "the same set of objects in
            # each other applicable layer") — the layer-6 keyword pass in
            # ``_recalculate_lord_buffs`` reads it rather than asking the noun
            # phrase a second time of a layer 4 that has moved on.
            reaching = [
                (static.source, static.payload)
                for static in reach.get(id(permanent), ())
                if isinstance(static.payload, LandAnimation)
            ]
            if reaching:
                permanent.metadata[LAND_ANIMATIONS_REACHING] = reaching
            else:
                permanent.metadata.pop(LAND_ANIMATIONS_REACHING, None)
            # The first animator, in battlefield order, of those the pass found
            # reaching this land: its colour is the one written. (Two
            # animators reaching one land both make it a creature; whose size
            # it then has is layer 7b's question, answered by timestamp in
            # ``layer_bridge.collect_pt_effects``.)
            animator, animation = min(
                reaching,
                key=lambda pair: position.get(id(pair[0]), len(position)),
                default=(None, None),
            )
            # "…are 1/1 **black** creatures" (Kormus Bell): CR 613 layer 5 of a
            # static, so it is a *derived* contribution — cleared and rebuilt
            # here on every pass, stamped with the animator's own timestamp
            # (CR 613.7a). It was written into the indefinite recolour slot,
            # which made the Bell overwrite a lace that was on the Swamp first,
            # win against one cast afterwards, and take either away with it
            # when it left.
            clear_derived_color_changes(permanent)
            if animation is not None:
                permanent.metadata["land_animated"] = True
                if animation.color:
                    add_derived_color_change(
                        permanent, animation.color,
                        timestamp=animator.timestamp,
                        label=f"animated ({animator.card.name})",
                    )
            elif permanent.metadata.get("land_animated"):
                # The animating source is gone: the land is no longer a
                # creature. Its size went with the record above — and nothing
                # else is cleared, because nothing else was this method's: the
                # persistent 7b slot it used to wipe here could by then hold a
                # resolved effect's write ("becomes 0/2 until your next
                # upkeep"), which outlives the animator.
                permanent.metadata.pop("land_animated", None)
