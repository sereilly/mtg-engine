from __future__ import annotations

import re


from ..enter_effects import (
    CHOOSE_COLOR_AND_OPPONENT_ON_ENTER,
    CHOOSE_OPPONENT_ON_ENTER,
    COPY_ARTIFACT_ON_ENTER,
    COPY_CREATURE_ON_ENTER,
    ENTERS_TAPPED,
    ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS,
    ENTERS_WITH_X_PLUS_1_1_COUNTERS,
    LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER,
    NO_MAXIMUM_HAND_SIZE,
    choosable_bodies,
    SPEND_WHITE_AS_RED,
)
from ..auras import aura_protection_colors, auras_attached_to
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ..pt import clear_base_pt, set_base_pt


# Characteristic-defining P/T (CR 604.3 / layer 7a). There is no registry to
# add to: the instruction describes what to count, so a card printed with one
# of these templates needs no code here at all.
def _count_dynamic_pt(
    game, player: PlayerState, permanent: Permanent, payload: dict
) -> int:
    """Tally the objects a ``dynamic_pt_count`` instruction describes.

    One counter for every characteristic-defining P/T, because they differ only
    in *what* they count and *whose* battlefield they count it on — both of
    which arrive on the payload (engine/characteristic_defining.py). The four
    functions this replaced each hardcoded one card's answer to those two
    questions.

    Types are read through ``has_type``/``is_creature`` (CR 613 layer 4), so an
    animated land counts as a creature and a land turned into a Swamp counts as
    a Swamp — the printed type line is not the authority on either.
    """
    scope = payload.get("scope", "you")
    if scope == "all":
        battlefields = [p.battlefield for p in game.players]
    elif (
        scope == "defender_when_attacking"
        and permanent.attacking
        and permanent.defending_player_index is not None
    ):
        battlefields = [game.players[permanent.defending_player_index].battlefield]
    else:
        battlefields = [player.battlefield]

    what = payload.get("count")
    excluded = payload.get("exclude_type")
    land_type = payload.get("land_type")

    total = 0
    for battlefield in battlefields:
        for perm in battlefield:
            if what == "land":
                total += bool(land_type and perm.has_type(str(land_type)))
            elif what == "creature":
                if perm.is_creature and not (excluded and perm.has_type(str(excluded))):
                    total += 1
            elif what == "same_name":
                total += perm.card.name == permanent.card.name
    return total


def _add_static_pt(permanent: Permanent, power: int, toughness: int) -> None:
    """Contribute a layer-7c modification to the *derived* buff channel.

    ``derived_buff_power``/``derived_buff_toughness`` are cleared and rebuilt
    from scratch by ``_refresh_dynamic_creatures`` on every recompute, so a
    contribution here needs no record of itself. That is the difference from
    adding to ``power_bonus``, which persists: anything written there has to be
    subtracted again later, and a subtraction that does not exactly match its
    addition compounds on every refresh — and CR 611.3a means the refresh runs
    constantly. Aspect of Wolf shipped exactly that bug; see
    tests/regressions/test_batch17.py.

    The channel is cleared by the same function that rebuilds it. Splitting
    those across two functions is how this class of bug gets back in: whoever
    calls only the rebuilding half then doubles every contribution.
    """
    if power:
        permanent.metadata["derived_buff_power"] = (
            int(permanent.metadata.get("derived_buff_power", 0)) + power
        )
    if toughness:
        permanent.metadata["derived_buff_toughness"] = (
            int(permanent.metadata.get("derived_buff_toughness", 0)) + toughness
        )


def _apply_conditional_bonus(
    permanent: Permanent, metadata_key: str, active: bool, power: int, toughness: int
) -> None:
    """A "gets +N/+N as long as <condition>" static ability
    (conditional_land_bonus, conditional_untapped_bonus, …).

    Derived, not accumulated: when the condition holds the bonus is contributed
    to the recomputed channel, and when it stops holding nothing has to be
    undone — the next recompute simply does not contribute it.
    """
    if active:
        _add_static_pt(permanent, power, toughness)
    else:
        permanent.metadata[metadata_key] = (0, 0)


class PermanentStateMixin:
    def _initialize_permanent_state(
        self,
        permanent: Permanent,
        caster_index: int,
        target_player_index: int | None,
    ) -> None:
        if permanent.card.primary_type in ("creature", "land", "artifact"):
            # Lands are stamped too: if a land later becomes a creature (Kormus Bell,
            # Living Lands) it must respect summoning sickness based on when it came
            # under control (CR 302.6). The marker is ignored for non-creature lands.
            permanent.metadata["summoning_sickness_turn"] = self.turn
        program = compile_card_oracle(permanent.card)
        text = program.normalized_text

        # enters tapped (static creature/permanent lines or normalized text).
        # The phrases probed for here live in engine/enter_effects.py, which
        # engine/grammar/registries.py also reads to tell the parser these lines
        # are already implemented — one string, two readers, so they cannot
        # drift apart.
        if any(line for line in program.static_lines if ENTERS_TAPPED in line) or (
            ENTERS_TAPPED in text and "unless" not in text
        ):
            permanent.tapped = True

        # "As this creature enters, it becomes your choice of <body>, <body>,
        # or <body>." (Primal Clay.) A body is applied immediately so headless
        # and AI play never blocks, and an interactive controller is offered the
        # choice; confirm_enter_body_choice replaces it.
        #
        # The default is the FIRST body printed, not the biggest: the card lists
        # them in a fixed order and picking "best" would be this code deciding
        # strategy on the player's behalf, differently from how the prompt they
        # are about to answer is ordered.
        bodies = choosable_bodies(text)
        if bodies:
            # Options first: _apply_chosen_body clears the keywords of the
            # *other* bodies before granting the chosen one's, and the card's
            # text mentions every body's keyword — so the compiler reads
            # "with flying" off Primal Clay and grants it. Applying a body
            # before the options are recorded leaves that stray grant in place.
            permanent.metadata["body_options"] = list(bodies)
            self._apply_chosen_body(permanent, bodies[0])
            if len(bodies) > 1:
                self.arm_pending_choice(
                    "body_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    options=list(bodies),
                )

        # "As this artifact enters, choose an opponent." (Black Vise) /
        # "As this enchantment enters, choose a color and an opponent." (Jihad)
        # Deterministic defaults are stamped immediately (the cast target, else
        # the first living opponent; the color the opponent controls most among
        # nontoken permanents) so headless/AI play never blocks. An interactive
        # caster with a genuine choice — several opponents, or a color to pick —
        # gets a prompt whose confirm_enter_choice overwrites the defaults
        # before anything consults them.
        needs_color = CHOOSE_COLOR_AND_OPPONENT_ON_ENTER in text
        if needs_color or CHOOSE_OPPONENT_ON_ENTER in text:
            opponents = [
                i for i, p in enumerate(self.players) if i != caster_index and not p.lost
            ]
            if target_player_index in opponents:
                chosen = target_player_index
            elif opponents:
                chosen = opponents[0]
            else:
                chosen = 1 - caster_index
            permanent.metadata["chosen_player_index"] = chosen
            default_color = None
            if needs_color:
                default_color = self._dominant_nontoken_color(self.players[chosen]) if 0 <= chosen < len(self.players) else "W"
                permanent.metadata["chosen_color"] = default_color
                # Jihad's anthem is conditioned on the stored choices, and the
                # entry recalculation ran before they were stamped — recompute.
                self._recalculate_lord_buffs()
            if needs_color or len(opponents) > 1:
                self.arm_pending_choice(
                    "enter_choice", caster_index,
                    card_name=permanent.card.name, permanent=permanent,
                    needs_color=needs_color, opponents=opponents,
                    default_seat=chosen, default_color=default_color,
                )

        # enters with fixed counters (Clockwork Beast). Track the counter count so
        # the end-of-combat trigger and the upkeep activated ability can adjust it.
        if any(ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS == line for line in program.static_lines) or ENTERS_WITH_SEVEN_PLUS_1_0_COUNTERS in text:
            permanent.power_bonus += 7
            permanent.metadata["plus_1_0_counters"] = 7

        # enters with X +1/+1 counters
        if any(ENTERS_WITH_X_PLUS_1_1_COUNTERS == line for line in program.static_lines) or ENTERS_WITH_X_PLUS_1_1_COUNTERS in text:
            x_value = permanent.metadata.get("cast_x_value")
            if isinstance(x_value, int) and x_value > 0:
                permanent.power_bonus += x_value
                permanent.toughness_bonus += x_value

        # copy-as-enter creature
        if any(COPY_CREATURE_ON_ENTER == line for line in program.static_lines) or COPY_CREATURE_ON_ENTER in text:
            source = self._resolve_copy_target(permanent, "creature")
            if source is None:
                source = next(
                    (
                        perm
                        for player in self.players
                        for perm in player.battlefield
                        if perm is not permanent and perm.card.primary_type == "creature"
                    ),
                    None,
                )
            if source is not None:
                self._apply_creature_copy(permanent, source)

        # copy-as-enter enchantment
        if COPY_ARTIFACT_ON_ENTER in text:
            # Honor the artifact the player chose when casting (Copy Artifact);
            # fall back to the first artifact for AI/untargeted casts.
            source = self._resolve_copy_target(permanent, "artifact")
            if source is None:
                source = next(
                    (
                        perm
                        for player in self.players
                        for perm in player.battlefield
                        if perm is not permanent and perm.card.primary_type == "artifact"
                    ),
                    None,
                )
            if source is not None:
                # CR 707.2 / 706.10c: become a copy of the artifact (its name, types,
                # abilities, produced mana) "except it's an enchantment in addition to
                # its other types." Like the creature copiers (Clone / Vesuvan
                # Doppelganger) the copy is a runtime overlay: ``permanent.card``
                # stays Copy Artifact and ``copied_card`` carries the copied
                # characteristics, so the overlay evaporates when the permanent
                # changes zones and the card reverts to Copy Artifact.
                src = source.effective_card
                src_type = src.type_line
                new_type = src_type if "enchantment" in src_type.lower() else (src_type + " Enchantment").strip()
                copied_card = CardDefinition(
                    name=src.name,
                    mana_cost=src.mana_cost,
                    cmc=src.cmc,
                    type_line=new_type,
                    oracle_text=src.oracle_text,
                    colors=src.colors,
                    color_identity=src.color_identity,
                    keywords=src.keywords,
                    produced_mana=src.produced_mana,
                    raw=dict(src.raw) if isinstance(src.raw, dict) else src.raw,
                )
                permanent.metadata["copied_from"] = src.name
                permanent.metadata["copied_card"] = copied_card
                if src.keywords:
                    permanent.metadata["copied_keywords"] = list(src.keywords)
                if src.colors:
                    permanent.metadata["copied_colors"] = list(src.colors)
                if "power" in src.raw and str(src.raw.get("power", "")).isdigit():
                    permanent.metadata["absolute_power"] = source.effective_power
                if "toughness" in src.raw and str(src.raw.get("toughness", "")).isdigit():
                    permanent.metadata["absolute_toughness"] = source.effective_toughness

        if any(instr.kind == "spell_pattern" and instr.value == NO_MAXIMUM_HAND_SIZE for instr in program.instructions) or NO_MAXIMUM_HAND_SIZE in text:
            self.players[caster_index].has_no_max_hand_size = True

        if SPEND_WHITE_AS_RED in text:
            self.players[caster_index].can_spend_white_as_red = True

        if LOSE_LIFE_EQUAL_TO_TOTAL_ON_ENTER in text:
            controller = self.players[caster_index]
            life_loss = controller.life
            controller.life -= life_loss
            self.log.append(f"{permanent.card.name}: {controller.name} lost {life_loss} life on entry")

    def _apply_creature_copy(self, permanent: Permanent, source: Permanent) -> None:
        """Make *permanent* a copy of *source* (CR 707.2): P/T, types/abilities
        (via ``copied_card``) and printed keywords. Used both when a copier
        enters (Clone / Vesuvan Doppelganger) and when Vesuvan's upkeep ability
        re-copies a different creature.

        Color is copied only when the copier's own text doesn't exclude it —
        Vesuvan's "except it doesn't copy that creature's color" keeps it blue.
        """
        copier_text = compile_card_oracle(permanent.card).normalized_text
        permanent.metadata["copied_from"] = source.card.name
        # CR 707.2: a copy takes on the copied creature's copiable values —
        # including its types/subtypes and abilities. Keep the source card so
        # subtype checks and static abilities (e.g. copying Lord of Atlantis:
        # the copy is a Merfolk and itself grants islandwalk to other Merfolk)
        # resolve against the copied creature, not the copier's own card.
        permanent.metadata["copied_card"] = source.card
        # Copiable P/T is the PRINTED value (or what the source itself copied) —
        # never counters, auras or lord buffs on the source (CR 707.2). Static
        # buffs then re-apply dynamically to the copy based on its own qualities.
        permanent.metadata["absolute_power"] = int(
            source.metadata.get("absolute_power", source._base_stat("power"))
        )
        permanent.metadata["absolute_toughness"] = int(
            source.metadata.get("absolute_toughness", source._base_stat("toughness"))
        )
        # CR 707.2 / 711.10: a copy gains the copied creature's printed
        # keyword abilities (first strike, flying, trample, …). Stamp them
        # so _has_keyword reports them even though permanent.card is still
        # the copier's own (Clone / Vesuvan Doppelganger) definition.
        if source.card.keywords:
            permanent.metadata["copied_keywords"] = list(source.card.keywords)
        else:
            permanent.metadata.pop("copied_keywords", None)
        if "doesn't copy that creature's color" in copier_text:
            permanent.metadata.pop("copied_colors", None)
        else:
            permanent.metadata["copied_colors"] = list(source.card.colors)
        # Vesuvan Doppelganger's granted upkeep ability ("you may have this
        # creature become a copy of target creature ... and it has this
        # ability") persists across every re-copy.
        if "become a copy of target creature" in copier_text:
            permanent.metadata["may_recopy_each_upkeep"] = True
        self._recalculate_lord_buffs()

    def _resolve_copy_target(self, permanent: Permanent, primary_type: str) -> Permanent | None:
        """Return the player-chosen permanent for a "copy as it enters" effect.

        The chosen target is recorded as ``copy_target = (player_index, perm_index)``
        when the spell is cast. Returns None if no legal choice was recorded so the
        caller can fall back to an arbitrary legal permanent.
        """
        copy_target = permanent.metadata.pop("copy_target", None)
        if copy_target is None:
            return None
        player_index, perm_index = copy_target
        if not isinstance(player_index, int) or not isinstance(perm_index, int):
            return None
        if not (0 <= player_index < len(self.players)):
            return None
        battlefield = self.players[player_index].battlefield
        if not (0 <= perm_index < len(battlefield)):
            return None
        candidate = battlefield[perm_index]
        if candidate is permanent or candidate.card.primary_type != primary_type:
            return None
        return candidate

    def _refresh_static_land_types(self, all_permanents: list[Permanent]) -> None:
        """Apply static basic-land-type changes (e.g. Conversion: "All Mountains
        are Plains."). Recomputed every call so a land reverts to its printed type
        the moment the source enchantment leaves the battlefield (CR 611.3a/b).

        The applied override is tagged with ``static_land_type_source`` so it can be
        reverted without clobbering a one-shot override from another effect (e.g.
        Phantasmal Terrain), which leaves that tag unset.
        """
        changes: list[tuple[str, str]] = []
        for perm in all_permanents:
            for instr in compile_card_oracle(perm.effective_card).instructions:
                if instr.kind == "static_land_type_change":
                    changes.append(
                        (instr.payload.get("from_type", ""), instr.payload.get("to_type", ""))
                    )
        for perm in all_permanents:
            if perm.card.primary_type != "land":
                continue
            new_type = None
            for from_type, to_type in changes:
                if from_type and from_type in perm.card.type_line.lower():
                    new_type = to_type
                    break
            if new_type:
                perm.metadata["land_type_override"] = new_type
                perm.metadata["static_land_type_source"] = True
            elif perm.metadata.get("static_land_type_source"):
                perm.metadata.pop("land_type_override", None)
                perm.metadata.pop("static_land_type_source", None)

    def _refresh_aspect_of_wolf(self) -> None:
        """Aspect of Wolf: enchanted creature gets +X/+Y where X/Y are half the
        aura controller's Forest count (down/up). Recomputed continuously so it
        tracks Forests entering and leaving the battlefield (CR 611.3a).

        Contributed to the derived buff channel, so several Aspects on one
        creature simply add up and nothing needs unwinding.
        """
        for controller in self.players:
            forests = sum(
                1
                for perm in controller.battlefield
                if perm.card.primary_type == "land" and perm.has_type("forest")
            )
            x, y = forests // 2, (forests + 1) // 2
            for aura in controller.battlefield:
                if "half the number of forests you control" not in aura.card.oracle_text.lower():
                    continue
                creature = aura.metadata.get("attached_to")
                if creature is None or creature.card.primary_type != "creature":
                    continue
                _add_static_pt(creature, x, y)

    def _refresh_dynamic_creatures(self) -> None:
        # TODO(card-hooks): Kormus Bell / Living Lands are the only two land
        # animators today (an "animate all <type>" registry, keyed by name,
        # would be the extension point once a third one is added).
        all_permanents = [perm for player in self.players for perm in player.battlefield]
        # Clear the derived layer-7c channel this method rebuilds. Everything
        # contributed below is a *conditional* continuous effect, so it is
        # recomputed from the current board rather than adjusted incrementally.
        for perm in all_permanents:
            perm.metadata.pop("derived_buff_power", None)
            perm.metadata.pop("derived_buff_toughness", None)
        kormus_active = any(perm.card.name == "Kormus Bell" for perm in all_permanents)
        living_lands_active = any(perm.card.name == "Living Lands" for perm in all_permanents)
        self._refresh_global_statics(all_permanents)
        self._refresh_static_land_types(all_permanents)
        # Layer 4 before layer 7: a characteristic-defining P/T that counts
        # creatures must see the lands this pass animates, not last pass's.
        self._refresh_land_animation(all_permanents, kormus_active, living_lands_active)
        self._refresh_aspect_of_wolf()

        for player in self.players:
            # Static "Attacking creatures you control get +X/+Y" sources (Orcish
            # Oriflamme). The bonus only applies while a creature is attacking, so it
            # is stored in metadata and added by effective_power/toughness when the
            # creature has attacking == True.
            attacking_buff_power = 0
            attacking_buff_toughness = 0
            for perm in player.battlefield:
                for instr in compile_card_oracle(perm.effective_card).instructions:
                    if instr.kind == "buff_attacking_creatures":
                        attacking_buff_power += int(instr.payload.get("power", 0))
                        attacking_buff_toughness += int(instr.payload.get("toughness", 0))
            for perm in player.battlefield:
                if perm.card.primary_type == "creature":
                    perm.metadata["attacking_buff_power"] = attacking_buff_power
                    perm.metadata["attacking_buff_toughness"] = attacking_buff_toughness

            for permanent in player.battlefield:
                prog = compile_card_oracle(permanent.effective_card)
                instr_kinds = {instr.kind for instr in prog.instructions}

                # Characteristic-defining P/T (CR 604.3, layer 7a). The
                # instruction says what to count; there is one counter, and a
                # new CDA card adds no code here at all.
                dynamic_pt = next(
                    (i for i in prog.instructions if i.kind == "dynamic_pt_count"), None
                )
                if dynamic_pt is not None:
                    value = _count_dynamic_pt(self, player, permanent, dynamic_pt.payload)
                    set_base_pt(permanent, value, value)

                land_bonus_instr = next(
                    (i for i in prog.instructions if i.kind == "conditional_land_bonus"), None
                )
                if land_bonus_instr is not None:
                    land_type = land_bonus_instr.payload["land_type"]
                    has_land = any(
                        perm.card.primary_type == "land" and perm.has_type(land_type)
                        for perm in player.battlefield
                    )
                    _apply_conditional_bonus(
                        permanent, "conditional_land_bonus", has_land,
                        int(land_bonus_instr.payload["power"]), int(land_bonus_instr.payload["toughness"]),
                    )

                untapped_bonus_instr = next(
                    (i for i in prog.instructions if i.kind == "conditional_untapped_bonus"), None
                )
                if untapped_bonus_instr is not None:
                    _apply_conditional_bonus(
                        permanent, "conditional_untapped_bonus", not permanent.tapped,
                        int(untapped_bonus_instr.payload["power"]), int(untapped_bonus_instr.payload["toughness"]),
                    )

    @staticmethod
    def _apply_chosen_body(permanent: Permanent, body: dict) -> None:
        """Set a "your choice of" creature's P/T and granted keyword.

        Base P/T through engine/pt.py (layer 7b) and the keyword through the
        layer-6 grant API, so the body is the object's characteristics rather
        than a rewritten card — the mistake Animate Artifact used to make.
        """
        from ..keywords import grant_keyword, remove_keyword

        for option in permanent.metadata.get("body_options") or ():
            if option.get("keyword"):
                remove_keyword(permanent, option["keyword"])
        set_base_pt(permanent, int(body["power"]), int(body["toughness"]))
        if body.get("keyword"):
            grant_keyword(permanent, body["keyword"])

    def confirm_enter_body_choice(self, player_index: int, option_index: int) -> bool:
        """Answer a pending "your choice of <body>" prompt."""
        return self.resolve_pending_choice("body_choice", player_index, option_index=option_index)

    def _resolve_body_choice(self, choice, option_index: int) -> bool:
        options = choice.data["options"]
        if not (0 <= option_index < len(options)):
            return False
        permanent = choice.data["permanent"]
        chosen = options[option_index]
        self._apply_chosen_body(permanent, chosen)
        self.log.append(
            f"{permanent.card.name} entered as a "
            f"{chosen['power']}/{chosen['toughness']}"
            + (f" with {chosen['keyword']}" if chosen["keyword"] else "")
        )
        self.discard_pending_choice(choice)
        return True

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
        """
        from ..global_statics import global_static_for

        sources = [
            (perm, static)
            for perm in all_permanents
            if (static := global_static_for(perm.card.oracle_text)) is not None
        ]

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
        for perm in all_permanents:
            applying = [
                source
                for source, static in sources
                if source is not perm and self._global_static_applies(static, perm)
            ]
            if applying:
                perm.metadata["global_static_sources"] = applying
            else:
                perm.metadata.pop("global_static_sources", None)

    @staticmethod
    def _global_static_applies(static, permanent: Permanent) -> bool:
        """Whether *static* covers *permanent*.

        "Noncreature artifact" reads the **printed** type line for the creature
        half: asking whether it is currently a creature would include the type
        this very effect adds, and the answer would then depend on whether it
        had already been asked.
        """
        if static.applies_to == "artifact":
            return permanent.has_type("artifact")
        if static.applies_to == "noncreature_artifact":
            printed = permanent.card.type_line.lower()
            return "artifact" in printed and "creature" not in printed
        return False

    def _refresh_land_animation(
        self, all_permanents: list[Permanent], kormus_active: bool, living_lands_active: bool
    ) -> None:
        """Kormus Bell / Living Lands animate basic lands into 1/1 creatures
        while the source is on the battlefield (CR 613 layer 4).

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
        for permanent in all_permanents:
            is_animated_swamp = (
                kormus_active
                and permanent.card.primary_type == "land"
                and permanent.has_type("swamp")
            )
            is_animated_forest = (
                living_lands_active
                and permanent.card.primary_type == "land"
                and permanent.has_type("forest")
            )
            if is_animated_swamp or is_animated_forest:
                permanent.metadata["land_animated"] = True
                set_base_pt(permanent, 1, 1)
                if is_animated_swamp:
                    permanent.metadata["color_override"] = "B"
            elif permanent.metadata.get("land_animated"):
                # The animating source is gone: the land is no longer a creature.
                permanent.metadata.pop("land_animated", None)
                clear_base_pt(permanent)
                permanent.metadata.pop("color_override", None)

    def _has_keyword(self, permanent: Permanent, keyword: str) -> bool:
        """Whether *permanent* currently has a keyword ability.

        Printed abilities are part of the object's copiable values and so are
        seeded before layer 1; grants and removals are continuous effects
        sharing CR 613's layer 6, resolved by timestamp. That means a removal
        can take a *printed* ability away and a later grant can put it back —
        neither of which the previous per-keyword if-chain could express, since
        it checked removals first and fell back to scanning oracle text.
        """
        return permanent.has_keyword(keyword)

    def _effective_colors(self, permanent: Permanent) -> set[str]:
        """The color symbols a permanent currently has (honoring color overrides
        and copied colors). Delegates to the shared handler helper."""
        from ..handlers._common import permanent_effective_colors

        return permanent_effective_colors(permanent)

    def _dominant_nontoken_color(self, player: PlayerState) -> str:
        """The color *player* controls most of among nontoken permanents — the
        deterministic default for Jihad's "choose a color" (a color the chosen
        opponent actually controls keeps the enchantment alive)."""
        counts: dict[str, int] = {}
        for perm in player.battlefield:
            if perm.metadata.get("is_token"):
                continue
            for color in self._effective_colors(perm):
                counts[color] = counts.get(color, 0) + 1
        if not counts:
            return "W"
        return max(sorted(counts), key=lambda c: counts[c])

    def _chosen_color_permanent_condition(self, source_perm: Permanent) -> bool:
        """Jihad: whether "the chosen player controls a nontoken permanent of
        the chosen color" currently holds for *source_perm*'s stored choices."""
        seat = source_perm.metadata.get("chosen_player_index")
        color = source_perm.metadata.get("chosen_color")
        if not isinstance(seat, int) or not (0 <= seat < len(self.players)) or not color:
            return False
        return any(
            not perm.metadata.get("is_token") and color in self._effective_colors(perm)
            for perm in self.players[seat].battlefield
        )

    def _protection_colors(self, permanent: Permanent) -> set[str]:
        """Color symbols this permanent has protection from (CR 702.16).

        Sourced from a printed "protection from [color]" static line or from a
        ``protection_from_<color>`` metadata flag granted by an Aura. Only color
        qualities are modeled — Limited Edition Alpha protection is always from a
        single color (e.g. Black Knight's "protection from white").
        """
        colors: set[str] = set()
        program = compile_card_oracle(permanent.effective_card)
        for instr in program.instructions:
            if instr.kind == "static_line" and instr.value.startswith("protection from "):
                clause = instr.value[len("protection from "):].strip()
                # CR 702.16g/h/i: "protection from [A] and from [B]" (and comma
                # separated variants) is shorthand for several separate protection
                # abilities. Pull every color word out of the remaining clause.
                for word in re.split(r",|\band from\b|\band\b", clause):
                    symbol = _COLOR_WORD_TO_SYMBOL.get(word.strip())
                    if symbol:
                        colors.add(symbol)
        # Two sources with different lifetimes, which is why both exist.
        #
        # An Aura's protection lasts exactly as long as it is attached, so it is
        # read off the Aura (the Ward cycle) and ends when the Aura leaves with
        # nothing having to remove it. That grant used to be stamped into the
        # metadata channel below and cleaned up by name on removal.
        for aura in auras_attached_to(permanent):
            for word in aura_protection_colors(aura.card.oracle_text):
                symbol = _COLOR_WORD_TO_SYMBOL.get(word)
                if symbol:
                    colors.add(symbol)
        # The metadata channel remains for protection granted with a lifetime of
        # its own (a spell granting it until end of turn). No card in the pool
        # uses it today; it is how such a grant would be expressed, and CR
        # 702.16c does not care where the protection came from.
        for key in permanent.metadata:
            if key.startswith("protection_from_"):
                symbol = _COLOR_WORD_TO_SYMBOL.get(key[len("protection_from_"):])
                if symbol:
                    colors.add(symbol)
        # Sleight of Mind: a color-word remap on this permanent replaces the color
        # words in its text, so "protection from blue" becomes "protection from red".
        remap = permanent.metadata.get("color_word_remap")
        if remap:
            colors = {remap.get(c, c) for c in colors}
        return colors

    def _is_protected_from(self, victim: Permanent, source: Permanent) -> bool:
        """True if *victim* has protection from a color *source* has (CR 702.16e/f)."""
        protection = self._protection_colors(victim)
        return bool(protection and protection & self._effective_colors(source))

    def _can_be_targeted(
        self, target: Permanent, source_card: CardDefinition | None
    ) -> bool:
        """Whether *target* is a legal target for *source_card* (CR 702.16b/702.18).

        Shroud forbids any targeting; protection forbids targeting by sources of
        the protected color. A ``None`` source is treated as colorless.
        """
        if self._has_keyword(target, "shroud"):
            return False
        protection = self._protection_colors(target)
        if protection and source_card is not None:
            if protection & set(source_card.colors):
                return False
        return True

    def _recalculate_lord_buffs(self) -> None:
        """Recalculate static-ability buffs from all lords on the battlefield.

        Per rule 611.3a, static abilities are not 'locked in' — they apply
        dynamically whenever their criteria are met. This method resets and
        recomputes all static_buff_power / static_buff_toughness values so that
        newly-entered creatures immediately receive relevant lord buffs, and
        creatures whose lords have left the battlefield lose those buffs.
        """
        # Step 1: Clear all existing static-ability-derived bonuses. Lord-granted
        # landwalk flags are tracked per permanent so they can be cleared and
        # recomputed too (611.3b — the grant ends when the lord leaves), without
        # disturbing landwalk granted by an Aura or printed on the card.
        for player in self.players:
            for perm in player.battlefield:
                perm.metadata.pop("static_buff_power", None)
                perm.metadata.pop("static_buff_toughness", None)
                lord_walks = perm.metadata.pop("_lord_walk_flags", None)
                if lord_walks:
                    for flag in lord_walks:
                        perm.metadata.pop(flag, None)
                # A lord-granted activated ability (Zombie Master's regenerate)
                # ends when the lord leaves, exactly like lord-granted landwalk.
                if perm.metadata.pop("_lord_granted_regen", None):
                    perm.metadata.pop("granted_regen_ability", None)

        def _add_static_buff(perm: Permanent, power: int, toughness: int) -> None:
            perm.metadata["static_buff_power"] = (
                int(perm.metadata.get("static_buff_power", 0)) + power
            )
            perm.metadata["static_buff_toughness"] = (
                int(perm.metadata.get("static_buff_toughness", 0)) + toughness
            )

        def _grant_lord_walk(perm: Permanent, walk: str) -> None:
            flag = f"has_{walk}"
            perm.metadata[flag] = True
            tracked = perm.metadata.setdefault("_lord_walk_flags", [])
            if flag not in tracked:
                tracked.append(flag)

        # A copy uses the copied creature's copiable card (types + abilities), so
        # lord static abilities and subtype checks resolve against it (CR 707.2).
        # ``Permanent.effective_card`` is that answer, and it also applies the
        # CR 613 layer-3 text change — a local re-implementation of the copy half
        # silently skipped the text half, which is the second-opinion bug this
        # whole pass exists to remove.
        def _eff_card(perm: Permanent):
            return perm.effective_card

        # A Magical Hack land-word swap on the lord itself rewrites the walks its
        # text grants (mountainwalk -> islandwalk on Goblin King makes other
        # Goblins islandwalkers).
        def _remap_walks(source_perm: Permanent, walks: list[str]) -> list[str]:
            remap = source_perm.metadata.get("land_word_remap") or {}
            if not remap:
                return walks
            return [f"{remap.get(w[: -len('walk')], w[: -len('walk')])}walk" for w in walks]

        # Step 2: Re-apply static buffs from every permanent currently on battlefield
        for ctrl_player in self.players:
            for source_perm in ctrl_player.battlefield:
                prog = compile_card_oracle(_eff_card(source_perm))
                for instr in prog.instructions:
                    if instr.kind == "buff_creatures_global":
                        # Jihad: "as long as the chosen player controls a
                        # nontoken permanent of the chosen color."
                        if instr.payload.get(
                            "requires_chosen_color_permanent"
                        ) and not self._chosen_color_permanent_condition(source_perm):
                            continue
                        color_sym = instr.payload.get("color")
                        power = int(instr.payload.get("power", 0))
                        toughness = int(instr.payload.get("toughness", 0))
                        target_players = self.players if instr.payload.get("all") else [ctrl_player]
                        for tp in target_players:
                            for target_perm in tp.battlefield:
                                if target_perm.card.primary_type != "creature":
                                    continue
                                # Honors color overrides (Lace) and copied colors
                                # (Clone), and keeps Vesuvan Doppelganger blue.
                                actual_colors = self._effective_colors(target_perm)
                                if color_sym and color_sym not in actual_colors:
                                    continue
                                _add_static_buff(target_perm, power, toughness)

                    # Castle-style "Untapped creatures you control get +X/+Y." The
                    # bonus is recomputed every call so it tracks tap state and ends
                    # when the source leaves (611.3a/611.3b).
                    elif instr.kind == "buff_untapped_creatures":
                        power = int(instr.payload.get("power", 0))
                        toughness = int(instr.payload.get("toughness", 0))
                        for target_perm in ctrl_player.battlefield:
                            if target_perm.card.primary_type != "creature":
                                continue
                            if target_perm.tapped:
                                continue
                            _add_static_buff(target_perm, power, toughness)

                    # Lord-style "Other [Subtype] get +A/+B [and have <landwalk>]."
                    # (e.g. Lord of Atlantis, Goblin King). Applied dynamically so it
                    # reaches creatures entering later and is removed when the lord
                    # leaves the battlefield.
                    elif (
                        instr.kind == "static_line"
                        and instr.value.startswith("other ")
                        and " get +" in instr.value
                    ):
                        lord_match = re.search(
                            r"other (\w+)s? get \+(\d+)/\+(\d+)(.*)", instr.value
                        )
                        if not lord_match:
                            continue
                        subtype_raw = lord_match.group(1).lower()
                        subtype = subtype_raw[:-1] if subtype_raw.endswith("s") else subtype_raw
                        power = int(lord_match.group(2))
                        toughness = int(lord_match.group(3))
                        rest = lord_match.group(4).lower()
                        granted_walks = _remap_walks(source_perm, [
                            w
                            for w in ("islandwalk", "mountainwalk", "swampwalk", "forestwalk", "plainswalk")
                            if w in rest
                        ])
                        for player in self.players:
                            for target_perm in player.battlefield:
                                if target_perm.card.primary_type != "creature":
                                    continue
                                if subtype not in _eff_card(target_perm).type_line.lower():
                                    continue
                                if target_perm is source_perm:  # "other"
                                    continue
                                _add_static_buff(target_perm, power, toughness)
                                for walk in granted_walks:
                                    _grant_lord_walk(target_perm, walk)

                    # "Other [Subtype] ... have <landwalk / activated ability>"
                    # with no +X/+X buff (Zombie Master: "Other Zombie creatures
                    # have swampwalk." / 'Other Zombies have "{B}: Regenerate
                    # this permanent."').
                    elif (
                        instr.kind == "static_line"
                        and instr.value.startswith("other ")
                        and " have " in instr.value
                        and (
                            "regenerate this permanent" in instr.value
                            or any(w in instr.value for w in
                                   ("islandwalk", "mountainwalk", "swampwalk", "forestwalk", "plainswalk"))
                        )
                    ):
                        sub_match = re.search(r"other (\w+?)s?\b", instr.value)
                        if not sub_match:
                            continue
                        subtype = sub_match.group(1).lower()
                        granted_walks = _remap_walks(source_perm, [
                            w
                            for w in ("islandwalk", "mountainwalk", "swampwalk", "forestwalk", "plainswalk")
                            if w in instr.value
                        ])
                        grants_regen = "regenerate this permanent" in instr.value
                        for player in self.players:
                            for target_perm in player.battlefield:
                                if target_perm.card.primary_type != "creature":
                                    continue
                                if subtype not in _eff_card(target_perm).type_line.lower():
                                    continue
                                if target_perm is source_perm:  # "other"
                                    continue
                                for walk in granted_walks:
                                    _grant_lord_walk(target_perm, walk)
                                if grants_regen:
                                    target_perm.metadata["granted_regen_ability"] = True
                                    target_perm.metadata["_lord_granted_regen"] = True
