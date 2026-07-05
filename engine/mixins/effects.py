from __future__ import annotations

import random
import re

from ..card_hooks import UNTAPPED_ARTIFACT_PROTECTORS
from ..handlers._common import permanent_matches_filter, pick_target_permanent
from ..models import CardDefinition, Permanent, PlayerState
from ..replacements import apply_replacements
from ..oracle import OracleInstruction, compile_card_oracle, lex_oracle_text
from ..trigger_utils import iter_triggered_abilities, make_trigger_event, matching_triggers

class EffectsMixin:
    def _trigger_aura_death_effects(self, dead_permanent: Permanent, controller: PlayerState) -> None:
        """Put an Aura's death-trigger effect onto the stack when the creature it
        enchants leaves the battlefield (e.g. an Aura that deals damage equal to the
        creature's toughness). The toughness is captured now (the creature is gone by
        resolution); the trigger resolves off the stack (CR 603.3)."""
        aura = dead_permanent.metadata.get("attached_aura")
        if aura is None:
            return
        prog = compile_card_oracle(aura.card)
        text = prog.normalized_text
        if not text.startswith("enchant creature"):
            return
        controller_index = self.players.index(controller)
        for trig in prog.triggered_abilities:
            if trig.condition.kind == "dies" and trig.condition.trigger == "when":
                toughness = dead_permanent.effective_toughness
                self._enqueue_triggered_ability(
                    controller_index=controller_index,
                    card=aura.card,
                    instruction=OracleInstruction("deal_damage_to_player", None, {}),
                    effect_kind="triggered_damage",
                    ability_text=trig.source_line,
                    trigger_context={"victim_player_index": controller_index, "amount": toughness},
                )
                break

    def _fire_combat_damage_to_player_triggers(
        self, attacker: Permanent, defending_player: PlayerState, amount: int = 0
    ) -> None:
        """Put an attacker's "whenever this creature deals (combat) damage to a
        player/opponent" triggers (e.g. Hypnotic Specter, El-Hajjaj) onto the
        stack. They resolve through the post-combat priority window (CR 603.3),
        like attack/block triggers. The defending player and dealt amount are
        captured in trigger_context.

        El-Hajjaj's "whenever this creature deals damage" is bare (not
        player-only), so CR-accurately it should also fire when this creature
        deals combat damage to a blocking/blocked creature — that path isn't
        wired up (a documented gap, not silent; the player-damage case below
        covers the common unblocked scenario)."""
        controller_index = self._controller_index_of(attacker)
        defending_index = self.players.index(defending_player)
        events = [
            make_trigger_event(
                controller_index, attacker, trig,
                trigger_context={"defending_player_index": defending_index, "amount": amount},
            )
            for trig in matching_triggers(
                attacker.effective_card,
                condition_kinds={
                    "creature_deals_damage",
                    "hypnotic_specter_deals_damage",
                    "deals_damage_to_player",
                    "creature_deals_combat_damage",
                },
                instruction_kinds={
                    "opponent_discards_random_card_on_damage",
                    "gain_life_equal_to_damage_dealt",
                    "arm_draw_step_life_loss_unless_pay",
                },
            )
        ]
        self._enqueue_triggered_batch(events)

    def _fire_dealt_damage_triggers(self, permanent: Permanent) -> None:
        """Put 'whenever this creature is dealt damage' triggers (e.g. Fungusaur) onto
        the stack; they resolve off the stack (CR 603.3) rather than inline."""
        controller_index = self._controller_index_of(permanent)
        events = [
            make_trigger_event(controller_index, permanent, trig)
            for trig in matching_triggers(
                permanent.effective_card,
                condition_kinds={"creature_dealt_damage"},
                instruction_kinds={"add_counter_to_self"},
            )
        ]
        self._enqueue_triggered_batch(events)

    def _controller_index_of(self, permanent: Permanent) -> int:
        """Index of the player who currently controls *permanent* (0 if not found —
        e.g. a permanent already removed from the battlefield)."""
        for i, player in enumerate(self.players):
            if permanent in player.battlefield:
                return i
        return 0

    def _is_indestructible(self, permanent: Permanent) -> bool:
        """CR 700.4: a permanent with indestructible can't be destroyed by 'destroy'
        effects or lethal damage. In LEA, Consecrate Land grants this to a land."""
        return bool(permanent.metadata.get("is_indestructible")) or self._untapped_artifact_protector_active(permanent)

    def _untapped_artifact_protector_active(self, permanent: Permanent) -> bool:
        """Guardian Beast-style: "As long as this creature is untapped,
        noncreature artifacts you control can't be enchanted, have
        indestructible, and other players can't gain control of them."
        Checked inline (mirrors Veteran Bodyguard's "as long as untapped"
        redirect) rather than precomputed, since it tracks the protector's
        tapped state continuously. Auras already attached when it enters
        aren't removed — callers that check "already attached" separately
        are unaffected. Protector names live in
        card_hooks.UNTAPPED_ARTIFACT_PROTECTORS, not here (CLAUDE.md: no
        card names outside card_hooks.py)."""
        if not permanent.has_type("artifact") or permanent.is_creature:
            return False
        controller = next(
            (p for p in self.players if permanent in p.battlefield), None
        )
        if controller is None:
            return False
        return any(
            perm.card.name in UNTAPPED_ARTIFACT_PROTECTORS and not perm.tapped
            for perm in controller.battlefield
        )

    def _set_lockout_banning_card(self, card: CardDefinition) -> str | None:
        """City in a Bottle: whether some permanent's compiled
        ``ban_and_sacrifice_set_permanents`` instruction bans *card* (its
        ``raw["set"]`` matches the locked-out set code). Returns the banning
        permanent's name, or None if unbanned. Shared by the cast/land-play
        gate (queue_from_hand) and the battlefield-sacrifice state check
        (game_ending.py)."""
        card_set = str(card.raw.get("set", "")) if isinstance(card.raw, dict) else ""
        if not card_set:
            return None
        for player in self.players:
            for perm in player.battlefield:
                for instr in compile_card_oracle(perm.effective_card).instructions:
                    if instr.kind == "ban_and_sacrifice_set_permanents" and instr.payload.get("set_code") == card_set:
                        return perm.card.name
        return None

    def _destroy_target_permanent(
        self,
        target: PlayerState,
        type_filter: str | None = None,
        color_filter: str | None = None,
        target_permanent_index: int | None = None,
        exclude_colors: list[str] | None = None,
        exclude_types: list[str] | None = None,
        bypass_regeneration: bool = False,
        subtype_filter: str | None = None,
        tapped_only: bool = False,
    ) -> CardDefinition | None:
        target_player_index = next(
            (i for i, p in enumerate(self.players) if p is target), None
        )

        # Shared filter evaluation (handlers/_common.py) so resolution can
        # never disagree with cast validation / legality enumeration about
        # what a target filter means.
        filter_payload = {
            "type_filter": type_filter,
            "subtype_filter": subtype_filter,
            "tapped_only": tapped_only,
            "color_filter": color_filter,
            "exclude_colors": exclude_colors,
            "exclude_types": exclude_types,
        }

        def _is_legal_target(perm) -> bool:
            return permanent_matches_filter(perm, filter_payload)

        def _do_destroy(perm: "Permanent", idx: int) -> "CardDefinition":
            if self._is_indestructible(perm):
                self.log.append(f"{perm.card.name} can't be destroyed (indestructible)")
                return None  # type: ignore[return-value]
            if not bypass_regeneration and perm.regeneration_shield > 0:
                perm.regeneration_shield -= 1
                perm.tapped = True
                perm.damage_marked = 0
                self.log.append(f"{perm.card.name} regenerated")
                return None  # type: ignore[return-value]
            target.battlefield.pop(idx)
            self._permanent_to_graveyard(target, perm)
            self._trigger_aura_death_effects(perm, target)
            if perm.card.primary_type == "land" and target_player_index is not None:
                self._process_land_dies(target_player_index)
            # 611.3b: a destroyed permanent's static buffs / dynamic P/T (Castle,
            # Gauntlet of Might, Lord of Atlantis, Nightmare's swamp count) must be
            # recomputed now that it has left the battlefield.
            self._recompute_continuous_effects()
            return perm.card

        if target_permanent_index is not None:
            if 0 <= target_permanent_index < len(target.battlefield):
                permanent = target.battlefield[target_permanent_index]
                if not _is_legal_target(permanent):
                    return None
                return _do_destroy(permanent, target_permanent_index)
            return None

        for idx, permanent in enumerate(target.battlefield):
            if not _is_legal_target(permanent):
                continue
            return _do_destroy(permanent, idx)

        return None

    def _tap_or_untap_target(
        self, target: PlayerState, make_tapped: bool, target_permanent_index: int | None = None
    ) -> bool:
        # Honor an explicitly chosen permanent (Twiddle: "tap or untap target
        # artifact, creature, or land" — the player picks which one, on either
        # battlefield). Fall back to the first permanent only when no explicit
        # choice was supplied (AI/headless).
        chosen = pick_target_permanent(target, target_permanent_index, predicate=lambda p: True)
        if chosen is None:
            return False
        chosen.tapped = make_tapped
        return True

    def _grant_regeneration_shield(
        self,
        target: PlayerState,
        target_permanent_index: int | None = None,
        subtype_filter: str | None = None,
    ) -> bool:
        # Honor an explicitly chosen creature (e.g. Death Ward's "Regenerate target
        # creature" — the player picks which one; an explicit illegal choice
        # fizzles). Fall back to the first creature only with no explicit choice.
        # Elephant Graveyard restricts the pool to a subtype ("target Elephant").
        def _eligible(perm: Permanent) -> bool:
            if not perm.is_creature:
                return False
            if subtype_filter and subtype_filter not in perm.effective_card.type_line.lower():
                return False
            return True

        chosen = pick_target_permanent(
            target, target_permanent_index, predicate=_eligible, fallback_on_invalid_choice=False
        )
        if chosen is None:
            return False
        chosen.regeneration_shield += 1
        return True

    def _source_colors(self, source) -> tuple[str, ...]:
        """Color symbols of a damage source — a Permanent (honoring a color
        override), a CardDefinition (spell), or None."""
        if source is None:
            return ()
        meta = getattr(source, "metadata", None)
        if isinstance(meta, dict) and meta.get("color_override"):
            return (str(meta["color_override"]),)
        card = getattr(source, "card", source)
        return tuple(getattr(card, "colors", ()) or ())

    def _match_reverse_damage_source(self, target: PlayerState, source):
        """The chosen Reverse Damage source matching this damage's source, or None.
        A chosen permanent matches the dealing Permanent by identity; a chosen spell
        matches by its CardDefinition (the same object the spell deals damage with)."""
        if source is None or not target.reverse_damage_sources:
            return None
        source_card = getattr(source, "card", source)
        for chosen in target.reverse_damage_sources:
            chosen_card = getattr(chosen, "card", chosen)
            if chosen is source or chosen is source_card or chosen_card is source_card:
                return chosen
        return None

    def _clear_reverse_damage_badge(self, target: PlayerState) -> None:
        # Drop the life-pill shield badge once no Reverse Damage shield remains.
        if not target.reverse_damage_sources and target.reverse_damage_charges <= 0:
            target.damage_prevention_source = None

    def _prevent_damage(self, target: PlayerState, damage: int, source=None) -> int:
        # Forcefield: prevent all but 1 of the next combat damage from the chosen
        # unblocked attacker (source-specific, consumed once).
        if damage > 1 and source is not None and source in target.forcefield_capped_sources:
            target.forcefield_capped_sources.remove(source)
            damage = 1
        if damage > 1 and target.combat_damage_cap_one_charges > 0:
            target.combat_damage_cap_one_charges -= 1
            damage = 1
        if damage <= 0:
            return damage
        # Reverse Damage: the next damage event from the chosen source ("a source of
        # your choice") is fully prevented and the player gains that much life. A
        # chosen source (permanent or spell) matches by identity; a generic charge
        # (no source picked) shields the next event from any source. Consumed here.
        matched = self._match_reverse_damage_source(target, source)
        if matched is not None:
            target.reverse_damage_sources.remove(matched)
            self._clear_reverse_damage_badge(target)
            self.log.append(f"Reverse Damage prevented {damage} damage to {target.name}")
            self._gain_life(target, damage, source_name="Reverse Damage")
            return 0
        if target.reverse_damage_charges > 0:
            target.reverse_damage_charges -= 1
            self._clear_reverse_damage_badge(target)
            self.log.append(f"Reverse Damage prevented {damage} damage to {target.name}")
            self._gain_life(target, damage, source_name="Reverse Damage")
            return 0
        # Circle of Protection: a color-scoped shield prevents the whole next damage
        # event from a source of that color ("prevent that damage").
        if target.color_prevention_shields:
            for color in self._source_colors(source):
                if color in target.color_prevention_shields:
                    target.color_prevention_shields.remove(color)
                    if not target.color_prevention_shields:
                        target.damage_prevention_color = None
                        target.damage_prevention_source = None
                    self.log.append(
                        f"Circle of Protection prevented {damage} damage to {target.name} from a {color} source"
                    )
                    return 0
        if target.damage_prevention_pool <= 0:
            return damage
        prevented = min(damage, target.damage_prevention_pool)
        target.damage_prevention_pool -= prevented
        if target.damage_prevention_pool <= 0:
            target.damage_prevention_source = None
        return damage - prevented

    def _prevent_permanent_damage(self, permanent, damage: int) -> int:
        """Reduce *damage* about to be dealt to a creature by its prevention pool
        (Healing Salve prevention mode, Samite Healer, …). Returns the unprevented
        remainder, consuming the shield as it goes."""
        if damage <= 0 or permanent.damage_prevention_pool <= 0:
            return max(0, damage)
        prevented = min(damage, permanent.damage_prevention_pool)
        permanent.damage_prevention_pool -= prevented
        if permanent.damage_prevention_pool <= 0:
            permanent.damage_prevention_source = None
        if prevented > 0:
            self.log.append(f"Prevented {prevented} damage to {permanent.card.name}")
        return damage - prevented

    def _damage_source_matches(self, chosen, source) -> bool:
        """Whether an incoming damage *source* is the *chosen* one (Jade Monolith's
        "a source of your choice"). No recorded choice matches anything (legacy /
        AI activations); an unknown incoming source never consumes a specific
        choice — the shield keeps waiting for its source."""
        if chosen is None:
            return True
        if source is None:
            return False
        if chosen is source:
            return True
        chosen_card = getattr(chosen, "card", chosen)
        source_card = getattr(source, "card", source)
        return chosen_card is source_card

    def _turn_face_up(self, permanent) -> None:
        """Illusionary Mask: a face-down creature is turned face up any time it
        would deal damage, damage would be dealt to it, or it becomes tapped.
        Restores the real card stashed at cast time (P/T, types, abilities)."""
        metadata = getattr(permanent, "metadata", None)
        if not metadata or not metadata.get("face_down"):
            return
        real = metadata.pop("face_down_real_card", None)
        metadata.pop("face_down", None)
        if real is not None:
            permanent.card = real
            self.log.append(f"{real.name} was turned face up")
            self._recalculate_lord_buffs()

    def _mark_damage_on_permanent(self, permanent, amount: int, source=None) -> int:
        """Mark *amount* damage on a creature after applying its prevention pool.
        Returns the damage actually marked (0 if fully prevented)."""
        # Illusionary Mask: turn a face-down creature face up when damage would
        # be dealt to it or it would deal damage (before prevention, CR 613/614).
        if amount > 0:
            self._turn_face_up(permanent)
            self._turn_face_up(source)
        # CR 614 replacement effects (Jade Monolith full redirect, Personal
        # Incarnation 1-point redirect) run before the prevention pool.
        consumed, payload = apply_replacements(
            self, "damage_to_creature",
            {"permanent": permanent, "amount": amount, "source": source},
        )
        if consumed:
            return 0
        amount = payload["amount"]
        dealt = self._prevent_permanent_damage(permanent, amount)
        if dealt > 0:
            permanent.damage_marked += dealt
        return dealt

    def _record_damage_source(self, victim: Permanent, source: Permanent) -> None:
        """Remember that *source* dealt damage to *victim* this turn, so that a
        "whenever a creature dealt damage by this creature this turn dies" trigger
        (e.g. Sengir Vampire) can recognize the kill. References are cleared at
        cleanup. Sources are deduped by identity."""
        sources = victim.metadata.setdefault("damaged_by_sources_this_turn", [])
        if source not in sources:
            sources.append(source)

    def _player_controls_text(self, player: PlayerState, phrase: str) -> bool:
        return any(phrase in perm.card.oracle_text.lower() for perm in player.battlefield)

    def _discard_card(self, player: PlayerState, card) -> None:
        """Move a discarded card to the graveyard, or — if the player controls
        Library of Leng — apply its optional CR 701.8e replacement. Use for
        random/forced discards (combat damage, "discards X cards at random",
        cleanup) where the player can't pick the card but Library of Leng still
        lets them keep it. The replacement is optional ("you may"), so a human
        controller gets a per-card prompt (pending_leng_discards, resolved by
        confirm_leng_discard); AI/headless play takes the beneficial
        top-of-library route inline.

        TODO(card-hooks): this is an interactive-prompt flow, not a plain
        replacement effect, so it doesn't fit engine/replacements.py as-is;
        migrate to a hook registry if a second interactive discard-replacement
        card appears."""
        if any(perm.card.name == "Library of Leng" for perm in player.battlefield):
            player_index = self.players.index(player)
            if player_index in self.interactive_seats:
                self.pending_leng_discards.append({"player_index": player_index, "card": card})
                self.log.append(
                    f"{player.name} discarded {card.name} — Library of Leng: "
                    "choose graveyard or top of library"
                )
                return
            player.library.insert(0, card)
            self.log.append(
                f"{player.name} discarded {card.name} to the top of their library (Library of Leng)"
            )
        else:
            player.graveyard.append(card)

    def _gain_life(self, target: PlayerState, amount: int, source_name: str | None = None) -> None:
        """Apply a life gain, honoring 'If you would gain life, draw that many cards
        instead' replacement effects (e.g. Lich, CR 614)."""
        if amount <= 0:
            return
        consumed, payload = apply_replacements(
            self, "life_gain",
            {"player": target, "amount": amount, "source_name": source_name},
        )
        if consumed:
            return
        amount = payload["amount"]
        source = f" from {source_name}" if source_name else ""
        before = target.life
        target.life += amount
        self.log.append(f"{target.name} gained {amount} life{source} ({before} -> {target.life})")

    def _deal_damage_to_player(self, target: PlayerState, amount: int, source=None) -> int:
        """Apply damage to a player (after prevention) and fire 'whenever you're
        dealt damage' triggers (e.g. Lich). ``source`` (a Permanent or spell
        CardDefinition) lets color-scoped prevention (Circle of Protection) match
        the source's color. Returns the damage actually dealt."""
        # Illusionary Mask: a face-down creature that would deal damage (e.g.
        # unblocked combat damage to a player) is turned face up first.
        if amount > 0:
            self._turn_face_up(source)
        damage = self._prevent_damage(target, amount, source=source)
        if damage > 0:
            # CR 614 replacement (Ali from Cairo's life floor) adjusts how much
            # of the damage actually reduces life.
            _, payload = apply_replacements(self, "damage_to_player", {"player": target, "amount": damage})
            damage = payload["amount"]
            target.life -= damage
            self._on_player_dealt_damage(target, damage)
        return damage

    def _on_player_dealt_damage(self, target: PlayerState, damage: int) -> None:
        # Track total damage dealt to each player this turn (Simulacrum, etc.).
        if damage > 0:
            target.damage_taken_this_turn += damage
        # Living Artifact: "Whenever you're dealt damage, put that many vitality
        # counters on this Aura." Counters accumulate on the enchantment so its
        # upkeep ability can later trade them for life (and the UI can show them).
        if damage > 0:
            for perm in target.battlefield:
                if "put that many vitality counters" in perm.card.oracle_text.lower():
                    perm.metadata["vitality_counters"] = int(perm.metadata.get("vitality_counters", 0)) + damage
                    self.log.append(
                        f"{perm.card.name} got {damage} vitality counter(s) "
                        f"(now {perm.metadata['vitality_counters']})"
                    )
        if not self._player_controls_text(
            target, "whenever you're dealt damage, sacrifice that many nontoken permanents"
        ):
            return
        # CR 701.16b: the sacrificing player chooses which nontoken permanents to
        # give up (a human is prompted; AI/headless resolves inline). "If you can't,
        # you lose the game." Multiple damage events this step accumulate the count.
        self.arm_forced_sacrifice(
            self.players.index(target),
            damage,
            filter="nontoken",
            reason="Lich",
            on_short={"kind": "lose"},
        )

    def _add_mana_from_text(self, controller: PlayerState, text: str, preferred_color: str | None = None) -> None:
        # Prefer lexing the oracle text for mana symbols
        try:
            tokens = lex_oracle_text(text)
        except Exception:
            tokens = ()

        mana_tokens = [t.value for t in tokens if t.kind == "mana"]
        if mana_tokens:
            for raw in mana_tokens:
                sym = raw.strip("{}")
                if sym in {"W", "U", "B", "R", "G", "C"}:
                    controller.mana_pool[sym] += 1
            return

        normalized = re.sub(r"\s+", " ", str(text or "").strip().lower())
        if "one mana of any color" in normalized:
            selected_color = self._normalize_mana_color(preferred_color) or "G"
            controller.mana_pool[selected_color] += 1

    def _return_creature_from_graveyard(self, caster: PlayerState) -> bool:
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                caster.hand.append(caster.graveyard.pop(idx))
                return True
        return False

    def _reanimate_creature_to_battlefield(
        self,
        caster: PlayerState,
        target: PlayerState | None = None,
        target_permanent_index: int | None = None,
    ) -> bool:
        controller_index = self.players.index(caster)
        # "Return target creature card from your graveyard" (Resurrection): honor the
        # creature the caster chose (Rule 601.2c) instead of always grabbing the
        # first one. target is the graveyard's owner; for Resurrection that is the
        # caster, but a chosen index is respected for any reanimation source.
        source = target if target is not None else caster
        if (
            isinstance(target_permanent_index, int)
            and 0 <= target_permanent_index < len(source.graveyard)
            and source.graveyard[target_permanent_index].primary_type == "creature"
        ):
            revived = source.graveyard.pop(target_permanent_index)
            self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
            return True
        # Fallback (AI / legacy callers with no explicit choice): first creature.
        for idx, card in enumerate(caster.graveyard):
            if card.primary_type == "creature":
                revived = caster.graveyard.pop(idx)
                self._put_permanent_onto_battlefield(controller_index, Permanent(card=revived), None)
                return True
        return False

    def _bounce_target_creature(
        self, target: PlayerState, target_permanent_index: int | None = None
    ) -> bool:
        # Respect the chosen target when one was declared; otherwise fall back to
        # the first creature so AI / legacy callers still resolve.
        chosen = pick_target_permanent(target, target_permanent_index)
        if chosen is None:
            return False
        target.hand.append(chosen.card)
        target.battlefield.remove(chosen)
        return True

    def _sacrifice_creature_for_mana(self, caster: PlayerState, chosen_index: int | None = None) -> CardDefinition | None:
        # Sacrifice: the caster chooses which creature to sacrifice for the cost.
        # Honor an explicit choice; otherwise sacrifice the first creature.
        chosen = pick_target_permanent(caster, chosen_index)
        if chosen is None:
            return None
        caster.battlefield.remove(chosen)
        caster.graveyard.append(chosen.card)
        return chosen.card

    def _apply_color_override(
        self,
        target: PlayerState,
        symbol: str,
        target_permanent_index: int | None = None,
    ) -> bool:
        if not symbol:
            return False
        chosen = pick_target_permanent(target, target_permanent_index, predicate=lambda p: True)
        if chosen is None:
            return False
        chosen.metadata["color_override"] = symbol
        return True

    def _process_land_enters(self, land_controller_index: int) -> None:
        """Put "whenever a land enters the battlefield, deal 2 damage" triggers onto
        the stack; they resolve off the stack (CR 603.3)."""
        events = [
            make_trigger_event(
                controller_index, permanent, trig,
                instruction=OracleInstruction("deal_damage_to_player", None, {}),
                effect_kind="triggered_damage",
                ability_text=None,
                trigger_context={"victim_player_index": land_controller_index, "amount": 2},
            )
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"land_enters"}
            )
        ]
        self._enqueue_triggered_batch(events)

    def _process_land_dies(self, land_controller_index: int) -> None:
        """Put land_dies triggered abilities (e.g. Dingus Egg) onto the stack when a
        land is put into a graveyard; they resolve off the stack (CR 603.3)."""
        events = [
            make_trigger_event(
                controller_index, permanent, trig,
                instruction=OracleInstruction("deal_damage_to_player", None, {}),
                effect_kind="triggered_damage",
                trigger_context={
                    "victim_player_index": land_controller_index,
                    "amount": int(trig.instruction.payload.get("amount", 2)),
                },
            )
            for controller_index, permanent, trig in iter_triggered_abilities(
                self, condition_kinds={"land_dies"}, first_match_only=False
            )
        ]
        self._enqueue_triggered_batch(events)

    def _fastbond_count(self, player_index: int) -> int:
        # TODO(card-hooks): single-card bespoke site; migrate if a second
        # "extra land drops for damage" card appears.
        if player_index < 0 or player_index >= len(self.players):
            return 0
        return sum(1 for permanent in self.players[player_index].battlefield if permanent.card.name == "Fastbond")
