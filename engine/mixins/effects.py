from __future__ import annotations

import random
import re

from ..card_hooks import TOP_OF_LIBRARY_DISCARD_SOURCES, UNTAPPED_ARTIFACT_PROTECTORS
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

    def _cant_be_enchanted(self, permanent: Permanent) -> bool:
        """Whether an Aura can't be attached to *permanent* — either a per-permanent
        flag set by an effect, or Guardian Beast's continuous grant to the
        noncreature artifacts its controller controls while it's untapped."""
        return bool(
            permanent.metadata.get("cant_be_enchanted_by_auras")
        ) or self._untapped_artifact_protector_active(permanent)

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

    def _controls_top_of_library_discard(self, player: PlayerState) -> bool:
        """Whether *player* controls a Library of Leng-style permanent that lets
        them redirect a discard to the top of their library (CR 701.8e). The
        single point of truth for the ``allow_top_of_library`` discard option;
        source names live in card_hooks.TOP_OF_LIBRARY_DISCARD_SOURCES."""
        return any(
            perm.card.name in TOP_OF_LIBRARY_DISCARD_SOURCES for perm in player.battlefield
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
        attached_to_land: bool = False,
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
            "attached_to_land": attached_to_land,
        }

        def _is_legal_target(perm) -> bool:
            return permanent_matches_filter(perm, filter_payload)

        def _do_destroy(perm: "Permanent", idx: int) -> "CardDefinition":
            # Pyramids: a shielded land's destruction is replaced — remove all
            # damage marked on it instead.
            if self._consume_land_destruction_shield(perm):
                return None  # type: ignore[return-value]
            if self._is_indestructible(perm):
                self.log.append(f"{perm.card.name} can't be destroyed (indestructible)")
                return None  # type: ignore[return-value]
            if (
                not bypass_regeneration
                and perm.regeneration_shield > 0
                # Disintegrate / Hurr Jackal: the shield is still on the creature
                # but does nothing while the "can't be regenerated" rider is up
                # (CR 701.19c), same as the combat-damage path.
                and not perm.metadata.get("cant_be_regenerated_this_turn")
            ):
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
        if make_tapped:
            # Illusionary Mask: a face-down creature that becomes tapped is
            # turned face up (no-op for everything else).
            self._turn_face_up(chosen)
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

    def _match_chosen_damage_source(self, chosen_sources, source):
        """The entry of *chosen_sources* matching this damage's source, or None.
        A chosen permanent matches the dealing Permanent by identity; a chosen spell
        matches by its CardDefinition (the same object the spell deals damage with)."""
        if source is None or not chosen_sources:
            return None
        source_card = getattr(source, "card", source)
        for chosen in chosen_sources:
            chosen_card = getattr(chosen, "card", chosen)
            if chosen is source or chosen is source_card or chosen_card is source_card:
                return chosen
        return None

    def _match_reverse_damage_source(self, target: PlayerState, source):
        """The chosen Reverse Damage source matching this damage's source, or None."""
        return self._match_chosen_damage_source(target.reverse_damage_sources, source)

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

    def _consume_land_destruction_shield(self, perm: Permanent) -> bool:
        """Pyramids: "The next time target land would be destroyed this turn,
        remove all damage marked on it instead." Consumes the one-shot shield
        and reports True when the destruction was replaced."""
        if (
            perm.card.primary_type == "land"
            and perm.metadata.pop("land_destruction_shield_this_turn", None)
        ):
            perm.damage_marked = 0
            self.log.append(
                f"{perm.card.name}'s destruction was replaced: all damage marked on it was removed"
            )
            return True
        return False

    def _apply_opponent_damage_choice(
        self, pending: dict, target_seat: int, target_permanent_index: int | None
    ) -> None:
        """Deal a pending opponent-chosen damage packet (Cuombajj Witches) to the
        chosen player face (index None) or creature."""
        from ..handlers._common import apply_damage_to_creature

        amount = int(pending["amount"])
        source = pending.get("_source_permanent") or pending.get("card_name")
        card_name = pending["card_name"]
        victim_player = self.players[target_seat]
        if target_permanent_index is None:
            dealt = self._deal_damage_to_player(victim_player, amount, source=source)
            self.log.append(f"{card_name} dealt {dealt} damage to {victim_player.name} (opponent's choice)")
            return
        if not (0 <= target_permanent_index < len(victim_player.battlefield)):
            self.log.append(f"{card_name}: chosen target is gone, no effect")
            return
        perm = victim_player.battlefield[target_permanent_index]
        if not perm.is_creature:
            self.log.append(f"{card_name}: '{perm.card.name}' is not a valid 'any target' target (115.4)")
            return
        apply_damage_to_creature(
            self, perm, amount, source,
            log_message=lambda dealt: f"{card_name} dealt {dealt} damage to {perm.card.name} (opponent's choice)",
        )

    def confirm_opponent_damage_choice(
        self, chooser_index: int, target_seat: int, target_permanent_index: int | None = None
    ) -> bool:
        """Resolve the pending opponent-chosen damage (Cuombajj Witches) with the
        chooser's pick. Returns False when no such choice is pending for them."""
        pending = self.pending_opponent_damage
        if pending is None or pending["chooser_index"] != chooser_index:
            return False
        if not (0 <= target_seat < len(self.players)):
            return False
        self.pending_opponent_damage = None
        self._apply_opponent_damage_choice(pending, target_seat, target_permanent_index)
        return True

    def _auto_resolve_opponent_damage_choice(self, pending: dict) -> None:
        """Deterministic chooser policy for AI/headless play: kill one of the
        activator's creatures if the damage is lethal to it (largest power
        first), otherwise hit the activator's face."""
        chooser_index = pending["chooser_index"]
        amount = int(pending["amount"])
        target_seat = pending.get("caster_index")
        if not (isinstance(target_seat, int) and 0 <= target_seat < len(self.players)):
            target_seat = next(
                (i for i, p in enumerate(self.players) if i != chooser_index and not p.lost),
                None,
            )
        if target_seat is None:
            return
        victim = self.players[target_seat]
        best_index: int | None = None
        best_power = -1
        for idx, perm in enumerate(victim.battlefield):
            if not perm.is_creature:
                continue
            if perm.effective_toughness - perm.damage_marked <= amount and perm.effective_power > best_power:
                best_index = idx
                best_power = perm.effective_power
        self._apply_opponent_damage_choice(pending, target_seat, best_index)

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

    def _draw_with_lamp(self, player: PlayerState, count: int) -> int:
        """Draw ``count`` cards for *player*, applying an armed draw replacement
        to the first draw (CR 614): Aladdin's Lamp's "look at the top X, draw one
        of them, put the rest on the bottom in a random order", or Ring of
        Ma'rûf's "put a card you own from outside the game into your hand". A
        human chooser pauses on ``pending_lamp_draw`` /
        ``pending_outside_game_draw`` (the rest of the draws resolve after the
        choice); AI/headless play chooses deterministically."""
        player_index = self.players.index(player)
        if player_index in self.outside_game_draw_replacements and count > 0:
            return self._draw_from_outside_the_game(player, player_index, count)
        x = self.lamp_draw_replacements.get(player_index)
        if not x or count <= 0:
            return player.draw(count)
        self.lamp_draw_replacements.pop(player_index, None)
        x = min(int(x), len(player.library))
        if x <= 0:
            return player.draw(count)
        if player_index in self.interactive_seats:
            self.pending_lamp_draw = {
                "player_index": player_index,
                "card_names": [c.name for c in player.library[:x]],
                "remaining_draws": count - 1,
            }
            self.log.append(
                f"{player.name} looks at the top {x} card(s) of their library (Aladdin's Lamp)"
            )
            return 0
        drawn = self._finish_lamp_draw(player_index, 0, x)
        return drawn + player.draw(count - 1)

    def _finish_lamp_draw(self, player_index: int, chosen_index: int, x: int) -> int:
        """Complete a lamp-replaced draw: the chosen card of the top ``x`` goes
        to hand, the rest go to the bottom of the library in a random order."""
        player = self.players[player_index]
        top = list(player.library[:x])
        chosen = top.pop(chosen_index)
        del player.library[:x]
        random.shuffle(top)
        player.library.extend(top)
        player.hand.append(chosen)
        # The replacement still ends in "then draw a card", so the chosen card is
        # the last card drawn this turn (Jandor's Ring's cost can discard it).
        player.cards_drawn_this_turn.append(chosen)
        self.log.append(
            f"{player.name} drew 1 card (Aladdin's Lamp) and put {len(top)} card(s) "
            "on the bottom of their library in a random order"
        )
        return 1

    def _draw_from_outside_the_game(self, player: PlayerState, player_index: int, count: int) -> int:
        """Ring of Ma'rûf's replaced draw: the player puts a card they own from
        outside the game (their sideboard) into their hand instead of drawing.

        Returns 0 drawn cards — nothing is drawn from the library, so a
        "draw a card"-triggered effect correctly sees no draw. With an empty
        sideboard there is no card to take and the replacement is spent anyway
        (CR 614.1: a replacement effect applies even when it does nothing)."""
        self.outside_game_draw_replacements.discard(player_index)
        if not player.sideboard:
            self.log.append(
                f"{player.name} has no cards outside the game to take (Ring of Ma'rûf)"
            )
            player.draw(count - 1)
            return 0
        if player_index in self.interactive_seats:
            self.pending_outside_game_draw = {
                "player_index": player_index,
                "card_names": [c.name for c in player.sideboard],
                "remaining_draws": count - 1,
            }
            self.log.append(
                f"{player.name} looks through the cards they own from outside the game (Ring of Ma'rûf)"
            )
            return 0
        self._finish_outside_game_draw(player_index, 0)
        player.draw(count - 1)
        return 0

    def _finish_outside_game_draw(self, player_index: int, chosen_index: int) -> None:
        """Move the chosen sideboard card into hand."""
        player = self.players[player_index]
        if not (0 <= chosen_index < len(player.sideboard)):
            return
        card = player.sideboard.pop(chosen_index)
        player.hand.append(card)
        self.log.append(
            f"{player.name} put {card.name} into their hand from outside the game (Ring of Ma'rûf)"
        )

    def confirm_outside_game_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Ring of Ma'rûf choice with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        pending = self.pending_outside_game_draw
        if pending is None or pending["player_index"] != player_index:
            return False
        if not (0 <= chosen_index < len(pending["card_names"])):
            return False
        self.pending_outside_game_draw = None
        self._finish_outside_game_draw(player_index, chosen_index)
        remaining = int(pending.get("remaining_draws", 0))
        if remaining > 0:
            self.players[player_index].draw(remaining)
        return True

    def confirm_lamp_draw(self, player_index: int, chosen_index: int) -> bool:
        """Resolve a pending Aladdin's Lamp draw with the player's chosen card,
        then make any draws that were queued behind the replaced one."""
        pending = self.pending_lamp_draw
        if pending is None or pending["player_index"] != player_index:
            return False
        x = len(pending["card_names"])
        if not (0 <= chosen_index < x):
            return False
        self.pending_lamp_draw = None
        self._finish_lamp_draw(player_index, chosen_index, min(x, len(self.players[player_index].library)))
        remaining = int(pending.get("remaining_draws", 0))
        if remaining > 0:
            self.players[player_index].draw(remaining)
        return True

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
        if self._controls_top_of_library_discard(player):
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
            # Eye for an Eye: the damage still happens, and its source's
            # controller is dealt the same amount. The caster picks "a source of
            # your choice", so only damage from a matching source mirrors; a
            # generic charge (no source picked) mirrors the next event from any
            # source. One entry per damage event, and entries are finite, so a
            # mirrored mirror can't loop forever.
            matched_mirror = self._match_chosen_damage_source(target.mirror_damage_sources, source)
            if damage > 0 and (matched_mirror is not None or target.mirror_damage_charges > 0):
                if matched_mirror is not None:
                    target.mirror_damage_sources.remove(matched_mirror)
                else:
                    target.mirror_damage_charges -= 1
                mirror_index = (
                    self.controller_index_of(source)
                    if isinstance(source, Permanent)
                    else None
                )
                if mirror_index is None:
                    # A spell (or unknown) source: fall back to the first living
                    # opponent — its caster in every two-player game.
                    target_index = self.players.index(target)
                    mirror_index = next(
                        (i for i, p in enumerate(self.players) if i != target_index and not p.lost),
                        None,
                    )
                if mirror_index is not None:
                    victim = self.players[mirror_index]
                    dealt = self._deal_damage_to_player(victim, damage, source=None)
                    self.log.append(
                        f"Eye for an Eye dealt {dealt} damage to {victim.name} "
                        f"(mirroring the damage dealt to {target.name})"
                    )
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
        # CR 400.3: the card returns to its owner's hand, not its controller's
        # (they differ when the creature was stolen, e.g. by Control Magic).
        owner_idx = self.owner_index_of(chosen)
        owner = self.players[owner_idx] if owner_idx is not None else target
        owner.hand.append(chosen.card)
        target.battlefield.remove(chosen)
        return True

    def _sacrifice_creature_for_mana(self, caster: PlayerState, chosen_index: int | None = None) -> CardDefinition | None:
        # Sacrifice: the caster chooses which creature to sacrifice for the cost.
        # Honor an explicit choice; otherwise sacrifice the first creature.
        chosen = pick_target_permanent(caster, chosen_index)
        if chosen is None:
            return None
        # CR 400.3: a sacrificed stolen creature's card still goes to its
        # owner's graveyard. Resolve the owner before leaving the battlefield.
        owner_idx = self.owner_index_of(chosen)
        owner = self.players[owner_idx] if owner_idx is not None else caster
        caster.battlefield.remove(chosen)
        owner.graveyard.append(chosen.card)
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
