from __future__ import annotations

import dataclasses

from ..card_hooks import ON_SELF_RESOLVED
from ..control import BASE_CONTROLLER, CONTROL_EFFECTS
from ..events import emit
from ..game_types import OracleExecutionContext, OracleStateMachine
from ..handlers import EFFECT_HANDLERS
from ..handlers._common import count_from_payload
from ..oracle_types import X_FROM_COUNT
from ..models import CardDefinition, Permanent, PlayerState
from ..auras import attach_aura, aura_animates_artifact, aura_keyword_grants
from ..auras import aura_enchant_clause, aura_enchants
from ..mixins.stack import aura_enchant_noun, permanent_matches_enchant_noun
from ..oracle import OracleInstruction, compile_card_oracle
from ..keywords import remove_keyword
from ..land_animation import LAND_ANIMATION_KIND
from ..land_types import change_land_type
from ..lord_buffs import LORD_BUFF_KIND
from ..pt import add_pt_modifier
from ..targeting import graveyard_target_spec


# Attachment bookkeeping, not a granted characteristic. `aura_granted_meta` is
# captured as "every key that appeared on the target while this Aura attached",
# which sweeps up the attachment record itself — and popping `attached_auras`
# on removal detached every *other* Aura too. The capture-anything heuristic is
# the next thing phase 6 replaces with owned effects; until then it must at
# least not eat its own bookkeeping.
# Keys ``aura_granted_meta`` must never claim: an attachment link, and the
# CR 613 layer-2 control channel, which belongs to every source that recorded a
# contribution and not to whichever Aura happened to write last.
_ATTACHMENT_KEYS = frozenset({
    "attached_aura", "attached_auras", CONTROL_EFFECTS, BASE_CONTROLLER,
})


class OracleInstructionsMixin:
    def _execute_oracle_instruction(
        self,
        instruction: OracleInstruction,
        context: OracleExecutionContext,
    ) -> tuple[bool, str]:
        # "…, where X is the number of Shrines you control." The clause *defines
        # X*, so it is resolved into the context's X here rather than by each
        # handler: every amount path already resolves the string "x" against
        # `context.x_value`, so one substitution at the single dispatch point
        # gives the clause to every effect family at once. Doing it per handler
        # is how the pump ended up the only sentence that could carry one.
        count_spec = instruction.payload.get(X_FROM_COUNT)
        if count_spec:
            context = dataclasses.replace(
                context, x_value=count_from_payload(self, context, count_spec)
            )
        handler = EFFECT_HANDLERS.get(instruction.kind)
        if handler is None:
            self.log.append(
                f"Resolved supported pattern for {context.card.name} without state mutation"
            )
            return True, "resolved"
        # CR 109.5: while this instruction runs, the object doing things is
        # controlled by the caster. That is knowable *here* and nowhere
        # downstream — a spell reaches the damage paths as a bare
        # `CardDefinition`, which no seat controls — so the seat is recorded for
        # the duration rather than threaded through the 45 call sites that would
        # each have to remember it. Idiom 3: a list of sites is only ever as
        # complete as the last card that touched it.
        self.resolving_seats.append(self.players.index(context.caster))
        try:
            return handler(self, instruction, context)
        finally:
            self.resolving_seats.pop()

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        target_permanent_index: int | None = None,
        target_permanent_id: int | list[int | None] | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
        cast_from_zone: str = "hand",
        # Everything else the stack item recorded (CHOICE_KEYS). The three
        # spelled-out parameters above predate it and stay for their callers;
        # anything a *cost* recorded arrives here, because a parameter per
        # choice is the shape `CHOICE_KEYS` exists to avoid.
        choices: dict | None = None,
    ) -> None:
        instruction = self._select_executable_instruction(card, mode_index)
        if instruction is None:
            self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
            return

        # CR 702.16b / 702.18: a spell that targets a permanent with shroud, or with
        # protection from the spell's color, has an illegal target. On resolution it
        # does nothing (608.3b — removed from the stack with no effect).
        #
        # Asked only of a *battlefield* index, for the reason the cast-time copy
        # of this check is: a reanimation spell's index counts into a graveyard,
        # and answering it from ``target.battlefield`` made Raise Dead fizzle
        # against a permanent that merely arrived in that slot while the spell
        # was on the stack.
        chosen = (
            None
            if graveyard_target_spec(card, compile_card_oracle(card), mode_index=mode_index)
            is not None
            else self.chosen_permanent(target, target_permanent_index, target_permanent_id)
        )
        if chosen is not None:
            if chosen.is_creature and not self._can_be_targeted(
                chosen, card, caster_index=self.players.index(caster)
            ):
                self.log.append(
                    f"{card.name} does nothing: {chosen.card.name} is an illegal target"
                )
                return

        state_machine = OracleStateMachine(
            self,
            OracleExecutionContext(
                caster=caster,
                target=target,
                card=card,
                target_permanent_index=target_permanent_index,
                target_permanent_id=target_permanent_id,
                x_value=x_value,
                choices={
                    **(choices or {}),
                    "divided_targets": divided_targets,
                    "new_color": new_color,
                    "old_color": old_color,
                },
                stack_target=stack_target,
                cast_from_zone=cast_from_zone,
            ),
        )
        state_machine.run(instruction)

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire triggers that respond to this spell's *controller* casting it.

        Announced on the event bus rather than looked up by card name: the
        oracle compiler already recognizes these conditions, so a card written
        "whenever you cast an enchantment spell" needs no registry entry.
        """
        # The record "you've cast an instant or sorcery spell this turn"
        # (Stormwing Entity) reads, kept here rather than at the payment site
        # because this is where the *cast* is announced: a spell that is
        # countered was still cast, and CR 601.2i finishes the casting before
        # anything can respond.
        if 0 <= caster_index < len(self.players):
            self.players[caster_index].spells_cast_this_turn.append(card)
        emit(self, "you_cast_spell", subject=card, caster_index=caster_index)
        # The ordinal form (Double Vision) is the *same* event asked a different
        # question, so it is announced from the same place rather than given a
        # fire site of its own — the filter is where "is this the first one?"
        # is decided, because that is where the caster's record is.
        emit(
            self, "you_cast_first_spell_each_turn",
            subject=card, caster_index=caster_index,
            # "Copy **that spell**": the effect needs the object, not just the
            # fact of the cast, so the card rides the trigger's captured context
            # and the handler finds it on the stack by identity.
            cast_card=card,
        )
        # "Whenever an opponent casts their **second** spell each turn"
        # (Mangara). Round 123's ordinal asked by the other seat: the same
        # event, the same question, a different player's record — and its own
        # kind because this one is announced to every seat where that one is
        # only for the caster's own permanents.
        emit(
            self, "opponent_casts_nth_spell_each_turn",
            subject=card, caster_index=caster_index,
        )
        emit(self, "enchantment_cast", subject=card, caster_index=caster_index)
        # Prowess (CR 702.108a): each creature the caster controls with the
        # keyword gets +1/+1 until end of turn on a noncreature cast. Asked of
        # the computed keyword rather than of a card list, so a printed and a
        # granted prowess answer alike, and the CR's own trigger word decides
        # the type test — a creature card anywhere in the type line is a
        # creature spell, however it is also an artifact.
        if "creature" not in card.type_line.lower():
            for perm in self.controlled_by(self.players[caster_index]):
                if perm.is_creature and self._has_keyword(perm, "prowess"):
                    add_pt_modifier(perm, 1, 1, until_eot=True)
                    self.log.append(
                        f"{perm.card.name} gets +1/+1 until end of turn (prowess)"
                    )

    def _apply_spell_cast_any_triggers(
        self, caster_index: int, card: CardDefinition, cast_from_zone: str = "hand",
    ) -> None:
        """Fire "whenever a player casts a [color] spell" triggers on any
        player's battlefield (the Rod/Cup/Sphere cycle).

        Called as the spell is put on the stack, so the trigger goes on the
        stack above it (CR 603.3). The colour narrowing comes from each
        trigger's own parsed condition, which is why one call covers the whole
        cycle instead of five name-keyed hooks.
        """
        # `cast_card` rides the event for the same reason it rides the
        # first-spell one above: a trigger whose effect is *about* that spell
        # ("counter it", "where X is its mana value") needs the object, not
        # just the fact of the cast, and by the time the trigger resolves the
        # stack top is something else.
        emit(
            self, "spell_cast", subject=card, caster_index=caster_index,
            cast_card=card,
        )
        # The zone rides along so "…from anywhere other than their hand"
        # (Ghostly Pilferer) has something to test. Every cast announces it;
        # only a trigger that narrows on it reads it.
        emit(
            self, "opponent_casts_spell", subject=card, caster_index=caster_index,
            cast_from_zone=cast_from_zone,
        )

    def _apply_self_resolved_hook(
        self,
        caster_index: int,
        card: CardDefinition,
        target_player_index: int,
        target_permanent_index: int | None,
    ) -> None:
        """Fire a bespoke hook for an instant/sorcery resolving itself (e.g. Guardian
        Angel), passing the spell's resolved target so the hook can reference it."""
        self_hook = ON_SELF_RESOLVED.get(card.name)
        if self_hook is not None:
            self_hook(self, self.players[caster_index], card, target_player_index, target_permanent_index)

    def _apply_global_buff(self, caster: PlayerState, source: CardDefinition) -> None:
        program = compile_card_oracle(source)
        for instr in program.instructions:
            if instr.kind == LAND_ANIMATION_KIND:
                # Every "All <type>s are P/T creatures that are still lands"
                # printing. Two branches keyed by land type stood here, one per
                # card the engine happened to know (engine/land_animation.py).
                self._refresh_dynamic_creatures()
                return
            if instr.kind == LORD_BUFF_KIND:
                # Every "<some creatures> get +X/+Y [and have <keyword>]" static
                # ability, whatever it names: colour anthem, subtype lord, or one
                # qualified by a state. Recalculated dynamically (611.3a) so the
                # buff and any granted ability reach creatures entering later and
                # end when the source leaves (611.3b). Four branches keyed by
                # instruction kind and by two `static_line` text probes stood
                # here, one per shape the consumer happened to implement.
                self._recalculate_lord_buffs()
                return

    def _apply_aura_effect(
        self,
        caster_index: int,
        aura_permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
        target_permanent_id: int | list[int | None] | None = None,
    ) -> bool:
        """Attach a resolving Aura to what it targeted, and run its enter text.

        Returns whether it ran the Aura's **own** "when this Aura enters" text.
        Two of them are performed here by bespoke text matching — Animate Dead's
        reanimation and Earthbind's conditional damage — and the caller fires
        the ordinary triggered-ability path for every Aura it says no to.

        That answer used to be assumed rather than reported: the caller skipped
        the generic path for *every* Aura, on the strength of these two, so an
        Aura whose entry trigger compiled to a perfectly ordinary instruction
        silently did nothing. Rousing Read drew no cards, Setessan Training drew
        none, and Faith's Fetters gained no life — all three reporting supported.
        

        *target_permanent_id* is the same choice as *target_permanent_index*,
        recorded when the Aura was cast (CR 601.2c). An Aura is the longest gap
        in the engine between choosing a target and using it — the spell waits
        for priority, for responses, and for everything above it on the stack —
        so it is the case where a battlefield slot is most likely to have been
        renumbered underneath the index by the time this runs.
        """
        ran_entry_text = False
        program = compile_card_oracle(aura_permanent.effective_card)
        text = program.normalized_text
        # The enchant clause is asked of the *printed* text: it is a line,
        # and `normalized_text` has already joined the lines into one blob.
        printed = aura_permanent.effective_card.oracle_text
        # "Does this Aura have an enchant clause?" asked of the one function that
        # answers it. This was a search for a ``spell_pattern`` instruction whose
        # value begins "enchant" — a third reading of the clause, and one that
        # depends on the *rest* of the card: Faith's Fetters' text compiles to a
        # life-gain trigger, so its spell patterns are about gaining life and
        # this returned before the cascade below could attach anything. The Aura
        # entered play unattached and went to the graveyard as though its target
        # had left.
        # ``aura_enchant_clause`` and not ``aura_enchant_noun``: the noun reader
        # answers a *battlefield* question and returns None for "enchant creature
        # card in a graveyard" (Animate Dead), which is still very much an Aura
        # with an enchant clause. The clause reader is the one that asks whether
        # the line exists at all — the same function `resolution.py` uses two
        # calls later to decide whether an unattached Aura goes to the graveyard.
        if aura_enchant_clause(printed) is None and not aura_enchants(
            printed, "enchantment"
        ):
            return ran_entry_text

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target_player = self.players[target_idx]

        # The enchant clause is *found* rather than assumed to be the first
        # thing in the text — Capture Sphere prints "Flash" above it, and
        # every branch below used to answer no for it (engine/auras.py).
        if aura_enchants(printed, "creature"):
            # Special-case reanimation-style Auras (e.g., Animate Dead) which target a
            # creature card in a graveyard and return it to the battlefield attached
            # to this Aura. Detect the presence of the reanimation language and
            # handle it by moving a creature card from the target player's
            # graveyard to the caster's battlefield and attaching the Aura.
            # Prefer the parsed instruction if available
            has_reanimate = any(instr.kind == "reanimate_creature" for instr in program.instructions)
            if has_reanimate or ("creature card in a graveyard" in text and "return enchanted creature card to the battlefield" in text):
                revived_card = None
                revived_owner_index = None
                caster_player = self.players[caster_index]
                # The player chooses which creature card in a graveyard to target
                # (Rule 601.2c). target_player_index identifies the graveyard's
                # owner and target_permanent_index is the index into that graveyard.
                if (
                    isinstance(target_permanent_index, int)
                    and 0 <= target_permanent_index < len(target_player.graveyard)
                    and target_player.graveyard[target_permanent_index].primary_type == "creature"
                ):
                    revived_card = target_player.graveyard.pop(target_permanent_index)
                    revived_owner_index = target_idx
                else:
                    # Fallback (e.g. AI with no explicit choice): search graveyards,
                    # preferring the caster's own, then the target's, then others.
                    search_order = [caster_player, target_player] + [
                        p for p in self.players if p is not caster_player and p is not target_player
                    ]
                    for source_player in search_order:
                        for idx, card in enumerate(source_player.graveyard):
                            if card.primary_type == "creature":
                                revived_card = source_player.graveyard.pop(idx)
                                revived_owner_index = self.players.index(source_player)
                                break
                        if revived_card is not None:
                            break
                if revived_card is None:
                    return ran_entry_text

                # Put the revived creature onto the battlefield under the caster's control
                revived_perm = Permanent(card=revived_card)
                # CR 400.3: when it later leaves the battlefield, the card goes
                # to its OWNER's graveyard — remember whose it was.
                if revived_owner_index is not None and revived_owner_index != caster_index:
                    revived_perm.metadata["owner_player_index"] = revived_owner_index
                self._put_permanent_onto_battlefield(caster_index, revived_perm, None)
                # Attach the Aura to the revived permanent (store references in metadata)
                attach_aura(aura_permanent, revived_perm)
                # "When this Aura leaves the battlefield, that creature's
                # controller sacrifices it." — honored by _remove_aura_effects.
                if "that creature's controller sacrifices it" in text:
                    aura_permanent.metadata["sacrifice_attached_on_leave"] = True
                # Apply the -1/-0 penalty from Animate Dead's text if present
                if "enchanted creature gets -1/-0" in text or "enchanted creature gets -1/ -0" in text:
                    revived_perm.power_bonus += -1

                self.log.append(f"{aura_permanent.card.name} reanimated {revived_card.name} and attached to aura")
                ran_entry_text = True
                return ran_entry_text

            # Normal enchant-creature behavior: attach to the creature chosen at cast time.
            # If the chosen target is no longer a legal creature (it left the battlefield
            # while the spell was on the stack), do not attach — the caller moves the
            # unattached Aura to the graveyard.
            target_creature = None
            if isinstance(target_permanent_index, int):
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                if candidate is not None and candidate.is_creature:
                    target_creature = candidate
            else:
                target_creature = next(
                    (perm for perm in self.controlled_by(target_player) if perm.is_creature),
                    None,
                )
            if not target_creature:
                return ran_entry_text

            # Snapshot the creature's pre-grant state so the continuous effects this
            # Aura grants can be reversed when the Aura leaves the battlefield
            # (CR 611.3 — a granted continuous effect ends when its source is gone).
            _pre_meta_keys = set(target_creature.metadata.keys())

            # Handle numeric static buffs/debuffs like "gets +2/+1" or "gets -2/-1".
            # Skip "+X/+Y until end of turn" buffs: those come from an *activated*
            # ability (e.g. Firebreathing "{R}: ... +1/+0 until end of turn",
            # Blessing "{W}: ... +1/+1 until end of turn") and only apply when the
            # ability is activated — not when the Aura is attached.
            # The grant is NOT applied here. It is derived from the Aura's own
            # text every time characteristics are computed
            # (auras.aura_static_pt_grant, collected by
            # layer_bridge.collect_pt_effects at layer 7c with the Aura's
            # attach timestamp). Adding it into the enchanted creature's
            # power_bonus meant removal had to subtract a remembered delta —
            # the shape that shipped the Aspect of Wolf compounding bug — and
            # gave every Aura on the board the same derived timestamp instead
            # of the moment it actually became attached (CR 613.7b).

            # Aspect of Wolf: "Enchanted creature gets +X/+Y, where X is half the
            # number of Forests you control (rounded down) and Y is half (rounded
            # up)." This is a characteristic-defining continuous value, recomputed in
            # _refresh_dynamic_creatures so it tracks Forests entering/leaving (CR
            # 611.3a) rather than being locked in at cast time. No flat bonus here.

            # Landwalk is a keyword like any other and reaches layer 6 through
            # auras.aura_keyword_grants, so nothing is stamped here. It used to
            # write a `has_<walk>` flag straight onto the creature, which meant
            # the grant lived outside the layer system and had to be undone by
            # name when the Aura left.
            if aura_keyword_grants(aura_permanent.effective_card.oracle_text):
                self.log.append(
                    f"{target_creature.card.name} gains "
                    f"{', '.join(aura_keyword_grants(aura_permanent.effective_card.oracle_text))}"
                    f" from {aura_permanent.card.name}"
                )

            if any("protection from" in instr.value for instr in program.instructions if instr.kind == "spell_pattern") or ("has protection from" in text):
                # Parse the specific color and stamp metadata on the creature
                # The colour is read off the Aura by
                # permanent_state._protection_colors while it is attached, so
                # nothing is stamped on the creature and nothing has to be
                # unstamped when the Aura leaves.
                self.log.append(f"{target_creature.card.name} gains protection from aura")


                # Fear: enchanted creature can't be blocked except by artifact creatures and/or black creatures

            # Flying: some Auras grant flying to the enchanted creature.
            # Exclude "if enchanted creature has flying" which is a conditional check, not a grant.
            _flying_conditional = "if enchanted creature has flying" in text or "if this creature has flying" in text
            _grants_flying = (
                ("has flying" in text and not _flying_conditional)
                or ("enchanted creature has flying" in text and not _flying_conditional)
                or "gains flying" in text
            )

            # Reach: e.g. Web's "Enchanted creature gets +0/+2 and has reach."

            # "Can attack as though it had haste" is a restriction derived from
            # the Aura (auras.aura_restrictions), not a haste grant — granting
            # the keyword also let a summoning-sick creature use its {T}
            # abilities, which CR 302.6/702.10b do not permit.
            if "can attack as though it had haste" in text:
                self.log.append(
                    f"{target_creature.card.name} can attack as though hasty "
                    f"({aura_permanent.card.name})"
                )

            # Invisibility: enchanted creature can't be blocked except by Walls
            if "can't be blocked except by walls" in text:
                self.log.append(f"{target_creature.card.name} can only be blocked by Walls")

            # Attach the aura to the creature
            attach_aura(aura_permanent, target_creature)

            # Lure: all creatures able to block this creature must do so
            if "all creatures able to block enchanted creature do so" in text:
                self.log.append(f"{target_creature.card.name} must be blocked by all able creatures (Lure)")

            # Earthbind: on enter, if creature has flying, deal 2 damage and strip flying
            if "if enchanted creature has flying" in text and "deals 2 damage" in text:
                if target_creature.has_keyword("flying"):
                    self._mark_damage_on_permanent(target_creature, 2, source=aura_permanent)
                    remove_keyword(target_creature, "flying")
                    self.log.append(f"{aura_permanent.card.name} dealt 2 damage to {target_creature.card.name} and stripped flying")
                ran_entry_text = True

            # Paralyze: tap enchanted creature on enter and mark it as prevented from untapping
            if "tap enchanted creature" in text and "doesn't untap during its controller's untap step" in text:
                self.become_tapped(target_creature)
                self._turn_face_up(target_creature)
                self.log.append(f"{aura_permanent.card.name} tapped {target_creature.card.name} and prevents it from untapping")

            # Control effect: a CR 613 layer-2 contribution from this Aura
            # (e.g. Control Magic). Recorded, not performed — the Aura leaving
            # drops the contribution rather than restoring a remembered seat.
            if "you control enchanted creature" in text:
                if self.take_control(target_creature, caster_index, source=aura_permanent):
                    self.log.append(f"{aura_permanent.card.name} took control of {target_creature.card.name}")

            # P/T is no longer recorded here: it is derived from the Aura on
            # every recompute, so removal has nothing to subtract. What remains
            # are the metadata flags the if-chain above stamps directly
            # (keyword grants, only_blockable_by_walls, lure_active, ...),
            # which _remove_aura_effects still pops. Those are the next thing
            # to become owned effects; see ROADMAP phase 6.
            aura_permanent.metadata["aura_granted_meta"] = [
                key
                for key in target_creature.metadata
                if key not in _pre_meta_keys and key not in _ATTACHMENT_KEYS
            ]

        elif aura_enchants(printed, "land"):
            target_land = None
            if target_permanent_index is not None:
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                if candidate is not None and candidate.card.primary_type == "land":
                    target_land = candidate
            if target_land is None and target_permanent_index is None:
                target_land = next(
                    (p for p in self.controlled_by(target_player) if p.card.primary_type == "land"),
                    None,
                )
            if target_land is None:
                self.log.append(f"{aura_permanent.card.name} found no land target")
                return ran_entry_text
            attach_aura(aura_permanent, target_land)
            # Nothing is stamped on the land any more, so there is no
            # `aura_granted_meta` to record here. The land-type change is a
            # layer-4 contribution keyed on this Aura (engine/land_types.py) and
            # _remove_aura_effects ends it by source, leaving whatever *else*
            # still says the land is a type; Consecrate Land's indestructible
            # and can't-be-enchanted both derive from the Aura (engine/auras.py).
            if "enchanted land is a swamp" in text:
                change_land_type(
                    target_land, "swamp",
                    source=aura_permanent, label=aura_permanent.card.name,
                )
            elif "enchanted land is the chosen type" in text:
                # Phantasmal Terrain: "As this Aura enters, choose a basic land type."
                # The land's type is NOT changed yet — we arm a pending choice and the
                # controller picks the type (a human via the prompt, an AI via the
                # auto-resolver). Only then is the contribution recorded
                # (confirm_land_type), so the spell never visibly "resolves" the
                # land change before the player finishes the choice.
                self.arm_pending_choice(
                    "land_type_choice", caster_index,
                    # The Aura resolved and is on the battlefield; the prompt
                    # holds priority (below) but holds no spell on the stack.
                    _stack_item=None,
                    card_name=aura_permanent.card.name,
                    land_owner_index=target_idx,
                    # Identity: ``list.index`` compares by value, so two
                    # untapped Forests would resolve to the same slot and the
                    # chosen land type would land on the wrong one.
                    land_index=self.battlefield_index_of(target_land),
                    _aura=aura_permanent,
                )
            self.log.append(f"{aura_permanent.card.name} enchants {target_land.card.name}")
        elif aura_enchants(printed, "wall"):
            target_wall = None
            if isinstance(target_permanent_index, int):
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                # `has_type`, so Animate Wall may enchant a creature that
                # *became* a Wall (Primal Clay's third body) and may not enchant
                # a printed Wall that stopped being one. "Enchant Wall" is a
                # question about the permanent, not about its card.
                if candidate is not None and candidate.has_type("wall"):
                    target_wall = candidate
            else:
                target_wall = next(
                    (
                        perm
                        for perm in self.controlled_by(target_player)
                        if perm.has_type("wall")
                    ),
                    None,
                )
            if target_wall:
                attach_aura(aura_permanent, target_wall)
                # Record the granted flag so it is undone when the Aura leaves
                # (CR 611.3 — the Wall stops being able to attack). Otherwise the
                # Wall could keep attacking after Animate Wall is removed.
                self.log.append(f"{target_wall.card.name} can attack as though it didn't have defender")
        elif aura_enchants(printed, "artifact"):
            # Attach this Aura to the specified artifact (or first artifact found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_artifact = None
            if target_permanent_index is not None:
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                if candidate is not None and candidate.card.primary_type == "artifact":
                    target_artifact = candidate
            if target_artifact is None and target_permanent_index is None:
                target_artifact = next(
                    (
                        perm
                        for perm in self.controlled_by(target_player)
                        if perm.card.primary_type == "artifact"
                    ),
                    None,
                )

            if target_artifact is None:
                return ran_entry_text

            # Attach metadata links
            attach_aura(aura_permanent, target_artifact)

            # Control effect: a CR 613 layer-2 contribution from this Aura
            # (e.g. Steal Artifact). Same shape as Control Magic's above.
            if "you control enchanted artifact" in text:
                if self.take_control(target_artifact, caster_index, source=aura_permanent):
                    self.log.append(f"{aura_permanent.card.name} took control of {target_artifact.card.name}")

            # Animation is NOT applied here. Animate Artifact adds the
            # creature type at CR 613 layer 4 and sets P/T at layer 7b, both
            # derived from the attached Aura (engine/auras.animating_auras,
            # collected by layer_bridge). This used to rebuild the artifact's
            # CardDefinition with "Creature" spliced into its type line and P/T
            # baked into raw, swap it onto the permanent, and stash the original
            # to restore on removal — remember-and-undo applied to the object's
            # identity, and it clamped a mana value of 0 up to 1/1 so an
            # animated Mox never died to CR 704.5f.
            if aura_animates_artifact(aura_permanent.effective_card.oracle_text):
                self.log.append(
                    f"{aura_permanent.card.name} animated {target_artifact.card.name} "
                    "into an artifact creature"
                )

        elif aura_enchants(printed, "enchantment"):
            # Attach this Aura to the specified enchantment (or first enchantment found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_enchantment = None
            if target_permanent_index is not None:
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                if candidate is not None and candidate.card.primary_type == "enchantment":
                    target_enchantment = candidate
            if target_enchantment is None and target_permanent_index is None:
                target_enchantment = next(
                    (
                        perm
                        for perm in self.controlled_by(target_player)
                        if perm.card.primary_type == "enchantment"
                    ),
                    None,
                )

            if target_enchantment is None:
                self.log.append(f"{aura_permanent.card.name} found no enchantment target")
                return ran_entry_text
            attach_aura(aura_permanent, target_enchantment)
            self.log.append(f"{aura_permanent.card.name} enchants {target_enchantment.card.name}")

        elif aura_enchant_noun(aura_permanent.effective_card) is not None:
            # "Enchant **permanent**" (Faith's Fetters) — and every other noun
            # this cascade does not name.
            #
            # The five branches above each re-derive "does this permanent answer
            # the enchant clause?" from the noun they are written for, which is
            # why a sixth noun needed a sixth branch and Faith's Fetters
            # attached to nothing at all. The cast has already asked that exact
            # question, through ``permanent_matches_enchant_noun`` — so this
            # asks the same function rather than a sixth copy of it, and a
            # seventh noun needs no code.
            #
            # Placed last so the branches above keep their bespoke behaviour
            # (Animate Dead's reanimation, the land and Wall special cases);
            # this is the general attach, not a replacement for them.
            noun = aura_enchant_noun(aura_permanent.effective_card)
            chosen = None
            if target_permanent_index is not None:
                candidate = self.chosen_permanent(
                    target_player, target_permanent_index, target_permanent_id
                )
                if candidate is not None and permanent_matches_enchant_noun(candidate, noun):
                    chosen = candidate
            elif target_permanent_index is None:
                chosen = next(
                    (
                        perm
                        for perm in self.controlled_by(target_player)
                        if permanent_matches_enchant_noun(perm, noun)
                    ),
                    None,
                )
            if chosen is None:
                self.log.append(f"{aura_permanent.card.name} found no {noun} target")
                return ran_entry_text
            attach_aura(aura_permanent, chosen)
            self.log.append(f"{aura_permanent.card.name} enchants {chosen.card.name}")
        return ran_entry_text
