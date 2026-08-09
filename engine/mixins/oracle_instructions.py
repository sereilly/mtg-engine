from __future__ import annotations

import re

from ..card_hooks import ON_SELF_RESOLVED
from ..events import emit
from ..game_types import OracleExecutionContext, OracleStateMachine
from ..handlers import EFFECT_HANDLERS
from ..models import CardDefinition, Permanent, PlayerState
from ..auras import attach_aura, aura_keyword_grants
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle
from ..keywords import grant_keyword, remove_keyword


# Attachment bookkeeping, not a granted characteristic. `aura_granted_meta` is
# captured as "every key that appeared on the target while this Aura attached",
# which sweeps up the attachment record itself — and popping `attached_auras`
# on removal detached every *other* Aura too. The capture-anything heuristic is
# the next thing phase 6 replaces with owned effects; until then it must at
# least not eat its own bookkeeping.
_ATTACHMENT_KEYS = frozenset({"attached_aura", "attached_auras"})


class OracleInstructionsMixin:
    def _execute_oracle_instruction(
        self,
        instruction: OracleInstruction,
        context: OracleExecutionContext,
    ) -> tuple[bool, str]:
        handler = EFFECT_HANDLERS.get(instruction.kind)
        if handler is not None:
            return handler(self, instruction, context)
        self.log.append(f"Resolved supported pattern for {context.card.name} without state mutation")
        return True, "resolved"

    def _apply_spell_text(
        self,
        caster: PlayerState,
        target: PlayerState,
        card: CardDefinition,
        target_permanent_index: int | None = None,
        x_value: int | None = None,
        new_color: str | None = None,
        stack_target=None,
        mode_index: int | None = None,
        old_color: str | None = None,
        divided_targets: list[tuple[int, int | None]] | None = None,
    ) -> None:
        instruction = self._select_executable_instruction(card, mode_index)
        if instruction is None:
            self.log.append(f"Resolved supported pattern for {card.name} without state mutation")
            return

        # CR 702.16b / 702.18: a spell that targets a permanent with shroud, or with
        # protection from the spell's color, has an illegal target. On resolution it
        # does nothing (608.3b — removed from the stack with no effect).
        if isinstance(target_permanent_index, int) and 0 <= target_permanent_index < len(target.battlefield):
            chosen = target.battlefield[target_permanent_index]
            if chosen.is_creature and not self._can_be_targeted(chosen, card):
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
                x_value=x_value,
                divided_targets=divided_targets,
                new_color=new_color,
                old_color=old_color,
                stack_target=stack_target,
            ),
        )
        state_machine.run(instruction)

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire triggers that respond to this spell's *controller* casting it.

        Announced on the event bus rather than looked up by card name: the
        oracle compiler already recognizes these conditions, so a card written
        "whenever you cast an enchantment spell" needs no registry entry.
        """
        emit(self, "you_cast_spell", subject=card, caster_index=caster_index)
        emit(self, "enchantment_cast", subject=card, caster_index=caster_index)

    def _apply_spell_cast_any_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire "whenever a player casts a [color] spell" triggers on any
        player's battlefield (the Rod/Cup/Sphere cycle).

        Called as the spell is put on the stack, so the trigger goes on the
        stack above it (CR 603.3). The colour narrowing comes from each
        trigger's own parsed condition, which is why one call covers the whole
        cycle instead of five name-keyed hooks.
        """
        emit(self, "spell_cast", subject=card, caster_index=caster_index)
        emit(self, "opponent_casts_spell", subject=card, caster_index=caster_index)

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
            if instr.kind == "animate_all_swamps":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "animate_all_forests":
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "buff_attacking_creatures":
                # Static ability (Orcish Oriflamme: "Attacking creatures you control
                # get +1/+0"). Applied dynamically to *attacking* creatures only via
                # _refresh_dynamic_creatures / effective P/T, never as a flat buff to
                # every creature the controller has.
                self._refresh_dynamic_creatures()
                return
            if instr.kind == "buff_untapped_creatures":
                # Castle-style static buff. Dynamically recalculated (611.3a) so it
                # tracks tap state and is removed when the source leaves (611.3b).
                self._recalculate_lord_buffs()
                return
            if instr.kind == "buff_creatures_global":
                # Static ability: dynamically recalculated (611.3a). Use
                # static_buff_power / static_buff_toughness so the buff can
                # be removed when the lord leaves (611.3b) and applied to new
                # creatures as they enter (611.3c).
                self._recalculate_lord_buffs()
                return

            if instr.kind == "static_line" and instr.value.startswith("other ") and " get +" in instr.value:
                # Lord-style "Other [Subtype] get +A/+B [and have <landwalk>]."
                # Recalculated dynamically so the buff (and any granted landwalk)
                # reaches creatures entering later and ends when the lord leaves.
                self._recalculate_lord_buffs()
                return

            # Zombie Master style: "Other Zombie creatures have swampwalk." /
            # 'Other Zombies have "{B}: Regenerate this permanent."' Recalculated
            # dynamically so the grants reach Zombies entering later and end when
            # the lord leaves the battlefield (611.3a/611.3b).
            if instr.kind == "static_line" and instr.value.startswith("other ") and " have " in instr.value:
                self._recalculate_lord_buffs()
                continue

    def _apply_aura_effect(
        self,
        caster_index: int,
        aura_permanent: Permanent,
        target_player_index: int | None,
        target_permanent_index: int | None = None,
    ) -> None:
        program = compile_card_oracle(aura_permanent.card)
        text = program.normalized_text
        if not any(instr.kind == "spell_pattern" and instr.value.startswith("enchant") for instr in program.instructions) and not text.startswith("enchant enchantment"):
            return

        target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
        target_player = self.players[target_idx]

        if text.startswith("enchant creature"):
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
                    return

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
                return

            # Normal enchant-creature behavior: attach to the creature chosen at cast time.
            # If the chosen target is no longer a legal creature (it left the battlefield
            # while the spell was on the stack), do not attach — the caller moves the
            # unattached Aura to the graveyard.
            target_creature = None
            if isinstance(target_permanent_index, int):
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.is_creature:
                        target_creature = candidate
            else:
                target_creature = next(
                    (perm for perm in target_player.battlefield if perm.is_creature),
                    None,
                )
            if not target_creature:
                return

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
            if aura_keyword_grants(aura_permanent.card.oracle_text):
                self.log.append(
                    f"{target_creature.card.name} gains "
                    f"{', '.join(aura_keyword_grants(aura_permanent.card.oracle_text))}"
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

            # Paralyze: tap enchanted creature on enter and mark it as prevented from untapping
            if "tap enchanted creature" in text and "doesn't untap during its controller's untap step" in text:
                self.become_tapped(target_creature)
                self._turn_face_up(target_creature)
                self.log.append(f"{aura_permanent.card.name} tapped {target_creature.card.name} and prevents it from untapping")

            # Control effect: steal creature to caster's battlefield (e.g. Control Magic)
            if "you control enchanted creature" in text:
                if target_creature in target_player.battlefield:
                    target_player.battlefield.remove(target_creature)
                    self.players[caster_index].battlefield.append(target_creature)
                    # Remember the original controller so control reverts when the
                    # Aura leaves the battlefield (CR 611.3 / 805.4a).
                    aura_permanent.metadata["stolen_permanent"] = target_creature
                    aura_permanent.metadata["stolen_owner_index"] = self.players.index(target_player)
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

        elif text.startswith("enchant land"):
            target_land = None
            if target_permanent_index is not None and 0 <= target_permanent_index < len(target_player.battlefield):
                candidate = target_player.battlefield[target_permanent_index]
                if candidate.card.primary_type == "land":
                    target_land = candidate
            if target_land is None and target_permanent_index is None:
                target_land = next((p for p in target_player.battlefield if p.card.primary_type == "land"), None)
            if target_land is None:
                self.log.append(f"{aura_permanent.card.name} found no land target")
                return
            attach_aura(aura_permanent, target_land)
            # Record every metadata key this Aura grants so _remove_aura_effects
            # undoes it when the Aura leaves (CR 611.3) — e.g. Phantasmal Terrain /
            # Evil Presence's land-type change reverts to the printed type.
            granted_meta: list[str] = []
            # Consecrate Land's indestructible and can't-be-enchanted both
            # derive from the Aura now (engine/auras.py), so neither is stamped
            # and neither needs undoing when it leaves.
            if "enchanted land is a swamp" in text:
                target_land.metadata["land_type_override"] = "swamp"
                # The type change ends with the Aura, even though the override may
                # be (re)set later for the chosen-type variant (confirm_land_type).
                granted_meta.append("land_type_override")
            elif "enchanted land is the chosen type" in text:
                granted_meta.append("land_type_override")
                # Phantasmal Terrain: "As this Aura enters, choose a basic land type."
                # The land's type is NOT changed yet — we arm a pending choice and the
                # controller picks the type (a human via the prompt, an AI via the
                # auto-resolver). Only then is land_type_override set (confirm_land_type),
                # so the spell never visibly "resolves" the land change before the
                # player finishes the choice.
                self.pending_land_type_choice = {
                    "player_index": caster_index,
                    "card_name": aura_permanent.card.name,
                    "land_owner_index": target_idx,
                    "land_index": target_player.battlefield.index(target_land),
                }
            if granted_meta:
                aura_permanent.metadata["aura_granted_meta"] = granted_meta
            self.log.append(f"{aura_permanent.card.name} enchants {target_land.card.name}")
        elif text.startswith("enchant wall"):
            target_wall = None
            if isinstance(target_permanent_index, int):
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if "wall" in candidate.card.type_line.lower():
                        target_wall = candidate
            else:
                target_wall = next(
                    (perm for perm in target_player.battlefield if "wall" in perm.card.type_line.lower()),
                    None,
                )
            if target_wall:
                attach_aura(aura_permanent, target_wall)
                # Record the granted flag so it is undone when the Aura leaves
                # (CR 611.3 — the Wall stops being able to attack). Otherwise the
                # Wall could keep attacking after Animate Wall is removed.
                self.log.append(f"{target_wall.card.name} can attack as though it didn't have defender")
        elif text.startswith("enchant artifact"):
            # Attach this Aura to the specified artifact (or first artifact found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_artifact = None
            if target_permanent_index is not None:
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "artifact":
                        target_artifact = candidate
            if target_artifact is None and target_permanent_index is None:
                target_artifact = next((perm for perm in target_player.battlefield if perm.card.primary_type == "artifact"), None)

            if target_artifact is None:
                return

            # Attach metadata links
            attach_aura(aura_permanent, target_artifact)

            # Control effect: steal artifact to caster's battlefield (e.g. Steal Artifact)
            if "you control enchanted artifact" in text:
                if target_artifact in target_player.battlefield:
                    target_player.battlefield.remove(target_artifact)
                    self.players[caster_index].battlefield.append(target_artifact)
                    # Remember the original controller so control reverts when the
                    # Aura leaves the battlefield (CR 611.3 / 805.4a).
                    aura_permanent.metadata["stolen_permanent"] = target_artifact
                    aura_permanent.metadata["stolen_owner_index"] = self.players.index(target_player)
                    self.log.append(f"{aura_permanent.card.name} took control of {target_artifact.card.name}")

            # Only animate if this Aura explicitly makes the artifact a creature (e.g. Animate Artifact)
            if ("it's an artifact creature" in text or "becomes an artifact creature" in text) and target_artifact.card.primary_type != "creature":
                new_type_line = target_artifact.card.type_line
                if "creature" not in new_type_line.lower():
                    new_type_line = (new_type_line + " Creature").strip()

                new_raw = dict(target_artifact.card.raw)
                power = toughness = max(1, int(target_artifact.card.cmc))
                new_raw["power"] = str(power)
                new_raw["toughness"] = str(toughness)

                new_card = CardDefinition(
                    name=target_artifact.card.name,
                    mana_cost=target_artifact.card.mana_cost,
                    cmc=target_artifact.card.cmc,
                    type_line=new_type_line,
                    oracle_text=target_artifact.card.oracle_text,
                    colors=target_artifact.card.colors,
                    color_identity=target_artifact.card.color_identity,
                    keywords=target_artifact.card.keywords,
                    produced_mana=target_artifact.card.produced_mana,
                    raw=new_raw,
                )

                # Snapshot the original (non-creature) card so the animation can be
                # undone when this Aura leaves the battlefield (CR 611.3). Without
                # this the artifact would keep its granted creature type and P/T —
                # the UI would still show stale power/toughness labels.
                target_artifact.metadata["pre_animate_card"] = target_artifact.card
                target_artifact.card = new_card
                self.log.append(f"{aura_permanent.card.name} animated {target_artifact.card.name} into an artifact creature")
        elif text.startswith("enchant enchantment"):
            # Attach this Aura to the specified enchantment (or first enchantment found)
            target_idx = target_player_index if target_player_index is not None else (1 - caster_index)
            target_player = self.players[target_idx]

            target_enchantment = None
            if target_permanent_index is not None:
                if 0 <= target_permanent_index < len(target_player.battlefield):
                    candidate = target_player.battlefield[target_permanent_index]
                    if candidate.card.primary_type == "enchantment":
                        target_enchantment = candidate
            if target_enchantment is None and target_permanent_index is None:
                target_enchantment = next((perm for perm in target_player.battlefield if perm.card.primary_type == "enchantment"), None)

            if target_enchantment is None:
                self.log.append(f"{aura_permanent.card.name} found no enchantment target")
                return
            attach_aura(aura_permanent, target_enchantment)
            self.log.append(f"{aura_permanent.card.name} enchants {target_enchantment.card.name}")
