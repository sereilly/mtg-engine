from __future__ import annotations

import re

from ..card_hooks import ON_SELF_RESOLVED, ON_SPELL_CAST, ON_SPELL_RESOLVED
from ..game_types import OracleExecutionContext, OracleStateMachine
from ..handlers import EFFECT_HANDLERS
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import OracleInstruction, _COLOR_WORD_TO_SYMBOL, compile_card_oracle


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
            if chosen.card.primary_type == "creature" and not self._can_be_targeted(chosen, card):
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
                new_color=new_color,
                stack_target=stack_target,
            ),
        )
        state_machine.run(instruction)

    def _apply_cast_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire permanent triggers that respond to the controller casting a spell."""
        caster = self.players[caster_index]
        for permanent in caster.battlefield:
            cast_hook = ON_SPELL_CAST.get(permanent.card.name)
            if cast_hook is not None:
                cast_hook(self, caster, permanent, card)

    def _apply_spell_resolved_triggers(self, caster_index: int, card: CardDefinition) -> None:
        """Fire permanent triggers that respond to a spell resolving (e.g. Crystal Rod)."""
        for controller in self.players:
            for permanent in controller.battlefield:
                resolved_hook = ON_SPELL_RESOLVED.get(permanent.card.name)
                if resolved_hook is not None:
                    resolved_hook(self, controller, permanent, card)

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
            # 'Other Zombies have "{B}: Regenerate this permanent."'
            if instr.kind == "static_line" and instr.value.startswith("other ") and " have " in instr.value:
                lord_match = re.search(r"other (\w+?)s?(?: creatures?)? have (.+)", instr.value)
                if lord_match:
                    subtype = lord_match.group(1).lower()
                    granted = lord_match.group(2).lower()
                    for player in self.players:
                        for permanent in player.battlefield:
                            if permanent.card.primary_type != "creature":
                                continue
                            if subtype not in permanent.card.type_line.lower():
                                continue
                            if permanent.card is source:
                                continue
                            for walk_word in ("swampwalk", "mountainwalk", "islandwalk", "forestwalk", "plainswalk"):
                                if walk_word in granted:
                                    permanent.metadata[f"has_{walk_word}"] = True
                            if "regenerate this permanent" in granted:
                                permanent.metadata["granted_regen_ability"] = True
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
                                break
                        if revived_card is not None:
                            break
                if revived_card is None:
                    return

                # Put the revived creature onto the battlefield under the caster's control
                revived_perm = Permanent(card=revived_card)
                self._put_permanent_onto_battlefield(caster_index, revived_perm, None)
                # Attach the Aura to the revived permanent (store references in metadata)
                aura_permanent.metadata["attached_to"] = revived_perm
                revived_perm.metadata["attached_aura"] = aura_permanent
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
                    if candidate.card.primary_type == "creature":
                        target_creature = candidate
            else:
                target_creature = next(
                    (perm for perm in target_player.battlefield if perm.card.primary_type == "creature"),
                    None,
                )
            if not target_creature:
                return

            # Snapshot the creature's pre-grant state so the continuous effects this
            # Aura grants can be reversed when the Aura leaves the battlefield
            # (CR 611.3 — a granted continuous effect ends when its source is gone).
            _pre_power_bonus = target_creature.power_bonus
            _pre_toughness_bonus = target_creature.toughness_bonus
            _pre_meta_keys = set(target_creature.metadata.keys())

            # Handle numeric static buffs/debuffs like "gets +2/+1" or "gets -2/-1".
            # Skip "+X/+Y until end of turn" buffs: those come from an *activated*
            # ability (e.g. Firebreathing "{R}: ... +1/+0 until end of turn",
            # Blessing "{W}: ... +1/+1 until end of turn") and only apply when the
            # ability is activated — not when the Aura is attached.
            buff_match = None
            for _m in re.finditer(r"gets ([+-]\d+)/([+-]\d+)", text):
                if text[_m.end():].lstrip().startswith("until end of turn"):
                    continue
                buff_match = _m
                break
            if buff_match:
                target_creature.power_bonus += int(buff_match.group(1))
                target_creature.toughness_bonus += int(buff_match.group(2))

            # Aspect of Wolf: "Enchanted creature gets +X/+Y, where X is half the
            # number of Forests you control (rounded down) and Y is half (rounded
            # up)." This is a characteristic-defining continuous value, recomputed in
            # _refresh_dynamic_creatures so it tracks Forests entering/leaving (CR
            # 611.3a) rather than being locked in at cast time. No flat bonus here.

            # Landwalk/protection patterns are recognized in the compiled program;
            # fall back to normalized-text checks for logging when necessary.
            _walk_instrs = [instr for instr in program.instructions if instr.kind == "spell_pattern" and instr.value.startswith("has ") and "walk" in instr.value]
            if _walk_instrs or ("has " in text and "walk" in text):
                self.log.append(f"{target_creature.card.name} gains landwalk from {aura_permanent.card.name}")
                for _wi in _walk_instrs:
                    # e.g. "has mountainwalk" -> metadata key "has_mountainwalk"
                    _meta_key = _wi.value.replace(" ", "_")
                    target_creature.metadata[_meta_key] = True
                if not _walk_instrs:
                    for _walk_word in ("swampwalk", "mountainwalk", "islandwalk", "forestwalk", "plainswalk"):
                        if f"has {_walk_word}" in text:
                            target_creature.metadata[f"has_{_walk_word}"] = True

            if any("protection from" in instr.value for instr in program.instructions if instr.kind == "spell_pattern") or ("has protection from" in text):
                # Parse the specific color and stamp metadata on the creature
                _prot_match = re.search(r"protection from (\w+)", text)
                if _prot_match:
                    _prot_color = _COLOR_WORD_TO_SYMBOL.get(_prot_match.group(1).lower())
                    if _prot_color:
                        target_creature.metadata[f"protection_from_{_prot_match.group(1).lower()}"] = True
                self.log.append(f"{target_creature.card.name} gains protection from aura")

            if "has first strike" in text or "enchanted creature has first strike" in text or "gains first strike" in text:
                target_creature.metadata["gains_first_strike"] = True
                self.log.append(f"{target_creature.card.name} gains first strike from {aura_permanent.card.name}")

                # Fear: enchanted creature can't be blocked except by artifact creatures and/or black creatures
            if "has fear" in text or "enchanted creature has fear" in text or "gains fear" in text:
                target_creature.metadata["gains_fear"] = True
                self.log.append(f"{target_creature.card.name} gains fear from {aura_permanent.card.name}")

            # Flying: some Auras grant flying to the enchanted creature.
            # Exclude "if enchanted creature has flying" which is a conditional check, not a grant.
            _flying_conditional = "if enchanted creature has flying" in text or "if this creature has flying" in text
            _grants_flying = (
                ("has flying" in text and not _flying_conditional)
                or ("enchanted creature has flying" in text and not _flying_conditional)
                or "gains flying" in text
            )
            if _grants_flying:
                target_creature.metadata["gains_flying"] = True
                self.log.append(f"{target_creature.card.name} gains flying from {aura_permanent.card.name}")

            # Reach: e.g. Web's "Enchanted creature gets +0/+2 and has reach."
            if "has reach" in text or "gains reach" in text:
                target_creature.metadata["gains_reach"] = True
                self.log.append(f"{target_creature.card.name} gains reach from {aura_permanent.card.name}")

            # Haste: enchanted creature can attack as though it had haste
            if "can attack as though it had haste" in text:
                target_creature.metadata["gains_haste"] = True
                self.log.append(f"{target_creature.card.name} gains haste from {aura_permanent.card.name}")

            # Invisibility: enchanted creature can't be blocked except by Walls
            if "can't be blocked except by walls" in text:
                target_creature.metadata["only_blockable_by_walls"] = True
                self.log.append(f"{target_creature.card.name} can only be blocked by Walls")

            # Attach the aura to the creature
            aura_permanent.metadata["attached_to"] = target_creature
            target_creature.metadata["attached_aura"] = aura_permanent

            # Lure: all creatures able to block this creature must do so
            if "all creatures able to block enchanted creature do so" in text:
                target_creature.metadata["lure_active"] = True
                self.log.append(f"{target_creature.card.name} must be blocked by all able creatures (Lure)")

            # Earthbind: on enter, if creature has flying, deal 2 damage and strip flying
            if "if enchanted creature has flying" in text and "deals 2 damage" in text:
                has_flying = (
                    "Flying" in target_creature.card.keywords
                    or target_creature.metadata.get("gains_flying")
                    or target_creature.metadata.get("gains_flying_until_eot")
                )
                if has_flying:
                    self._mark_damage_on_permanent(target_creature, 2)
                    target_creature.metadata["loses_flying"] = True
                    self.log.append(f"{aura_permanent.card.name} dealt 2 damage to {target_creature.card.name} and stripped flying")

            # Paralyze: tap enchanted creature on enter and mark it as prevented from untapping
            if "tap enchanted creature" in text and "doesn't untap during its controller's untap step" in text:
                target_creature.tapped = True
                target_creature.metadata["aura_prevents_untap"] = True
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

            # Record what continuous effects this Aura granted so they can be undone
            # when the Aura leaves the battlefield (see _remove_aura_effects).
            aura_permanent.metadata["aura_granted_power"] = (
                target_creature.power_bonus - _pre_power_bonus
            )
            aura_permanent.metadata["aura_granted_toughness"] = (
                target_creature.toughness_bonus - _pre_toughness_bonus
            )
            aura_permanent.metadata["aura_granted_meta"] = [
                key
                for key in target_creature.metadata
                if key not in _pre_meta_keys and key != "attached_aura"
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
            aura_permanent.metadata["attached_to"] = target_land
            target_land.metadata["attached_aura"] = aura_permanent
            if "indestructible" in text:
                target_land.metadata["is_indestructible"] = True
            if "can't be enchanted by other auras" in text:
                target_land.metadata["cant_be_enchanted_by_auras"] = True
            if "enchanted land is a swamp" in text:
                target_land.metadata["land_type_override"] = "swamp"
            elif "enchanted land is the chosen type" in text:
                # Phantasmal Terrain: "choose a basic land type." Apply a provisional
                # default (island) so headless/AI play stays deterministic, then arm a
                # pending choice so a human controller can pick the actual type.
                target_land.metadata["land_type_override"] = "island"
                self.pending_land_type_choice = {
                    "player_index": caster_index,
                    "card_name": aura_permanent.card.name,
                    "land_owner_index": target_idx,
                    "land_index": target_player.battlefield.index(target_land),
                }
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
                aura_permanent.metadata["attached_to"] = target_wall
                target_wall.metadata["attached_aura"] = aura_permanent
                target_wall.metadata["can_attack_as_though_no_defender"] = True
                # Record the granted flag so it is undone when the Aura leaves
                # (CR 611.3 — the Wall stops being able to attack). Otherwise the
                # Wall could keep attacking after Animate Wall is removed.
                aura_permanent.metadata["aura_granted_meta"] = ["can_attack_as_though_no_defender"]
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
            aura_permanent.metadata["attached_to"] = target_artifact
            target_artifact.metadata["attached_aura"] = aura_permanent

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

            aura_permanent.metadata["attached_to"] = target_enchantment
            target_enchantment.metadata["attached_aura"] = aura_permanent
            self.log.append(f"{aura_permanent.card.name} enchants {target_enchantment.card.name}")
