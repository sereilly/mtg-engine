from __future__ import annotations

import re

from ..card_hooks import ON_LEAVE_BATTLEFIELD
from ..models import CardDefinition, Permanent, PlayerState
from ..oracle import compile_card_oracle
from ..replacements import apply_replacements
from ..trigger_utils import make_trigger_event, matching_triggers
from ._constants import _MANA_SYMBOLS, _NO_PRIORITY_STEPS

class GameHelpersMixin:
    def _find_controlled_permanent(
        self,
        controller: PlayerState,
        permanent_name: str,
        permanent_index: int | None = None,
    ) -> tuple[int, Permanent] | None:
        if permanent_index is not None:
            if permanent_index < 0 or permanent_index >= len(controller.battlefield):
                return None
            permanent = controller.battlefield[permanent_index]
            if permanent.card.name != permanent_name:
                return None
            return permanent_index, permanent

        for idx, permanent in enumerate(controller.battlefield):
            if permanent.card.name == permanent_name:
                return idx, permanent
        return None

    @staticmethod
    def _stack_item_colors(item) -> tuple[str, ...]:
        """Effective color symbols of a spell on the stack, honoring a color
        change applied by a Lace card (StackItem.new_color)."""
        if getattr(item, "new_color", None):
            return (item.new_color,)
        return tuple(item.card.colors or ())

    @staticmethod
    def _remap_color_filter(permanent, color_filter):
        """Apply a Sleight of Mind color-word remap to a color-word filter baked
        into ``permanent``'s compiled ability. Lifeforce's '{G}: Counter target
        black spell' compiles ``color_filter='B'`` once per process; changing its
        text to "red" stores ``color_word_remap={'B': 'R'}`` on the permanent, so
        the effective filter becomes 'R'. Returns ``color_filter`` unchanged when
        the permanent has no remap for it."""
        if not color_filter or permanent is None:
            return color_filter
        remap = permanent.metadata.get("color_word_remap")
        if remap:
            return remap.get(color_filter, color_filter)
        return color_filter

    def _is_creature(self, permanent: Permanent) -> bool:
        """A permanent is a creature if its printed type says so or an effect has
        turned it into one (e.g. Kormus Bell / Living Lands animated lands, or
        Jade Statue animated until end of combat)."""
        return permanent.is_creature

    def _is_summoning_sick(self, permanent: Permanent) -> bool:
        if not self._is_creature(permanent):
            return False
        if self._has_keyword(permanent, "Haste"):
            return False
        return permanent.metadata.get("summoning_sickness_turn") == self.turn

    def _advance_summoning_sickness(self, active_player_index: int) -> None:
        """Carry summoning sickness across other players' turns (CR 302.6).

        ``self.turn`` advances on *every* player's turn, but a creature only sheds
        summoning sickness once *its controller's* most recent turn begins. A sick
        creature is marked with ``summoning_sickness_turn == self.turn``; left
        untouched, the marker would no longer match once an opponent's turn bumps
        the counter, clearing sickness a full turn early.

        Called at the start of each turn (untap step), this re-stamps the marker on
        every *non-active* player's still-sick creatures so it keeps tracking the
        current turn. The active player's own creatures are deliberately left stale
        so their marker falls behind ``self.turn`` — that is how they shed sickness
        as their turn begins.
        """
        for index, player in enumerate(self.players):
            if index == active_player_index:
                continue
            for permanent in player.battlefield:
                if (
                    self._is_creature(permanent)
                    and permanent.metadata.get("summoning_sickness_turn") == self.turn - 1
                ):
                    permanent.metadata["summoning_sickness_turn"] = self.turn

    def _public_phase_name(self, phase: str, step: str) -> str:
        if phase in {"precombat_main", "postcombat_main"}:
            return "main"
        if phase == "combat":
            return "combat"
        if phase == "ending" and step in {"end", "cleanup"}:
            return step
        if phase == "beginning" and step in {"untap", "upkeep", "draw"}:
            return step
        return step

    def _receives_priority(self, step: str) -> bool:
        return step not in _NO_PRIORITY_STEPS

    def _make_expiry_tag(self, edge: str, phase: str, step: str) -> str:
        return f"{edge}:{phase}:{step}"

    def _expire_tagged_effects(self, tag: str) -> None:
        for player in self.players:
            for permanent in player.battlefield:
                expires = permanent.metadata.get("expires_at")
                if expires != tag:
                    continue
                key = permanent.metadata.get("expires_key")
                if isinstance(key, str):
                    permanent.metadata.pop(key, None)
                permanent.metadata.pop("expires_at", None)
                permanent.metadata.pop("expires_key", None)

    def _on_step_or_phase_begin(self, phase: str, step: str) -> None:
        # 500.4
        self._expire_tagged_effects(self._make_expiry_tag("begin_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("begin_phase", phase, step))

    def _on_step_or_phase_end(self, phase: str, step: str) -> None:
        # 500.5 and 500.5a
        self._expire_tagged_effects(self._make_expiry_tag("end_step", phase, step))
        self._expire_tagged_effects(self._make_expiry_tag("end_phase", phase, step))
        if phase == "combat" and step == "end_of_combat":
            self._expire_tagged_effects("end_of_combat")
        self.clear_mana_pools()

    def _normalize_mana_color(self, mana_color: str | None) -> str | None:
        if mana_color is None:
            return None
        color = mana_color.strip().upper()
        if color not in {"W", "U", "B", "R", "G"}:
            raise ValueError(f"Invalid mana color: {mana_color}")
        return color

    def clear_mana_pools(self) -> None:
        for player in self.players:
            for symbol in _MANA_SYMBOLS:
                player.mana_pool[symbol] = 0
            player.creature_only_mana.clear()

    def _recompute_continuous_effects(self) -> None:
        """Recalculate all static/continuous P/T effects (611.3). Call after any
        permanent leaves the battlefield so lord buffs (Crusade, Gauntlet of Might,
        Lord of Atlantis, Castle) and dynamic P/T (Nightmare) reflect the new board."""
        self._recalculate_lord_buffs()
        self._refresh_dynamic_creatures()

    def _remove_aura_effects(self, aura: Permanent) -> None:
        """Undo the continuous effects an Aura granted to the permanent it was
        attached to (CR 611.3 — the effect ends when the Aura leaves). The grants
        were recorded on the Aura by _apply_aura_effect."""
        attached = aura.metadata.get("attached_to")
        if attached is None:
            return
        power_delta = int(aura.metadata.get("aura_granted_power", 0) or 0)
        toughness_delta = int(aura.metadata.get("aura_granted_toughness", 0) or 0)
        if power_delta:
            attached.power_bonus -= power_delta
        if toughness_delta:
            attached.toughness_bonus -= toughness_delta
        for key in aura.metadata.get("aura_granted_meta", []) or []:
            attached.metadata.pop(key, None)
        # Animate Artifact (and similar) replaced the permanent's card with an
        # animated artifact-creature version. Restore the original card so it stops
        # being a creature and the UI drops its power/toughness labels (CR 611.3).
        pre_animate_card = attached.metadata.pop("pre_animate_card", None)
        if pre_animate_card is not None:
            attached.card = pre_animate_card
        if attached.metadata.get("attached_aura") is aura:
            attached.metadata.pop("attached_aura", None)
        # Control effects (Control Magic, Steal Artifact) revert when the Aura leaves
        # — return the stolen permanent to its original controller (CR 611.3 / 805.4a).
        self._revert_stolen_permanent(aura)
        # Animate Dead: "When this Aura leaves the battlefield, that creature's
        # controller sacrifices it." A sacrifice can't be replaced by
        # regeneration (CR 701.15e).
        if aura.metadata.get("sacrifice_attached_on_leave"):
            controller_index = self.controller_index_of(attached)
            if controller_index is not None:
                controller = self.players[controller_index]
                controller.battlefield = [p for p in controller.battlefield if p is not attached]
                self._permanent_to_graveyard(controller, attached)
                self.log.append(
                    f"{controller.name} sacrificed {attached.card.name} ({aura.card.name} left the battlefield)"
                )

    def controller_index_of(self, permanent: Permanent) -> int | None:
        """Index of the player whose battlefield currently holds *permanent*, or
        None if it is on no battlefield (already left / phased out).

        Matches by identity, not ``in``: Permanent is a dataclass with value
        equality, so ``in`` would match a look-alike (an opponent's copy of the
        same card in the same state) after this object has left the battlefield."""
        return next(
            (
                i
                for i, p in enumerate(self.players)
                if any(perm is permanent for perm in p.battlefield)
            ),
            None,
        )

    def owner_index_of(self, permanent: Permanent) -> int | None:
        """Index of the player who owns *permanent*'s card (CR 108.3), for
        routing it to the right graveyard/hand when it leaves the battlefield
        (CR 400.3). The engine doesn't track ownership on the Permanent; every
        control effect in the supported pool is linked and records the
        pre-theft controller on its source (``stolen_owner_index``), which is
        the owner whenever owner and controller differ."""
        # Reanimation (Animate Dead on an opponent's creature card) records the
        # owner directly on the permanent.
        meta_owner = permanent.metadata.get("owner_player_index")
        if isinstance(meta_owner, int) and 0 <= meta_owner < len(self.players):
            return meta_owner
        for player in self.players:
            for perm in player.battlefield:
                if perm.metadata.get("stolen_permanent") is permanent:
                    idx = perm.metadata.get("stolen_owner_index")
                    if isinstance(idx, int) and 0 <= idx < len(self.players):
                        return idx
        return self.controller_index_of(permanent)

    def _take_control_linked(
        self,
        source: Permanent,
        target_perm: Permanent,
        new_controller: PlayerState,
        *,
        extra_meta: dict | None = None,
    ) -> bool:
        """Move *target_perm* under *new_controller* and record the theft on
        *source* (``stolen_permanent``/``stolen_owner_index``) so
        :meth:`_revert_stolen_permanent` can undo it when the linked duration
        ends. The inverse of that revert. Returns False (a no-op) if the target
        is on no battlefield. ``extra_meta`` tags the steal with a caller's own
        revert-condition marker (e.g. Old Man of the Sea's tapped-and-weaker)."""
        owner_index = self.controller_index_of(target_perm)
        if owner_index is None:
            return False
        self.players[owner_index].battlefield.remove(target_perm)
        new_controller.battlefield.append(target_perm)
        # CR 302.6: a creature has summoning sickness since it came under its
        # controller's control, not since it entered the battlefield — a stolen
        # creature can't attack or use {T} abilities the turn it changes hands
        # (and counts as not "controlled continuously since the turn began" for
        # effects like Siren's Call).
        if self._is_creature(target_perm):
            target_perm.metadata["summoning_sickness_turn"] = self.turn
        source.metadata["stolen_permanent"] = target_perm
        source.metadata["stolen_owner_index"] = owner_index
        if extra_meta:
            source.metadata.update(extra_meta)
        return True

    def _revert_stolen_permanent(self, source: Permanent) -> None:
        """Return whatever *source* stole (via ``stolen_permanent``/
        ``stolen_owner_index`` metadata) to its original controller. Shared by
        Aura-based control effects (Control Magic, Steal Artifact — reverted
        when the Aura leaves) and Aladdin's linked-duration ability (reverted
        by the ON_LEAVE_BATTLEFIELD hook when Aladdin itself leaves)."""
        stolen = source.metadata.get("stolen_permanent")
        owner_index = source.metadata.get("stolen_owner_index")
        if stolen is None or not (isinstance(owner_index, int) and 0 <= owner_index < len(self.players)):
            return
        for player in self.players:
            if stolen in player.battlefield:
                if player is not self.players[owner_index]:
                    player.battlefield.remove(stolen)
                    self.players[owner_index].battlefield.append(stolen)
                    # CR 302.6: returning to the owner is another control
                    # change, so the creature is summoning-sick again.
                    if self._is_creature(stolen):
                        stolen.metadata["summoning_sickness_turn"] = self.turn
                    self.log.append(
                        f"{stolen.card.name} returns to {self.players[owner_index].name}'s control "
                        f"({source.card.name} left the battlefield)"
                    )
                break

    def _permanent_to_graveyard(self, player: PlayerState, permanent: Permanent) -> None:
        """Move a permanent to the graveyard. Tokens (704.5d) cease to exist instead."""
        if "Aura" in permanent.card.type_line:
            self._remove_aura_effects(permanent)
        # CR 614 would-die replacements (Disintegrate's "exile it instead"):
        # a consumed event never reaches the graveyard, so no dies-triggers fire.
        consumed, _ = apply_replacements(
            self, "would_die", {"player": player, "permanent": permanent}
        )
        if consumed:
            return
        if not permanent.metadata.get("is_token", False):
            # CR 400.3: the card goes to its owner's graveyard, which differs
            # from the controller's when the permanent was stolen (Control Magic).
            owner_idx = self.owner_index_of(permanent)
            owner = self.players[owner_idx] if owner_idx is not None else player
            owner.graveyard.append(permanent.card)
        # is_creature (not the printed type) so an animated land (Kormus Bell /
        # Living Lands) dying counts as a creature death (Scavenging Ghoul).
        if permanent.is_creature:
            self.creatures_died_this_turn = getattr(self, "creatures_died_this_turn", 0) + 1
            # Sandals of Abdallah: "When that creature dies this turn, destroy
            # this artifact." Flag the linked artifact(s); the state-based
            # sweep destroys them (a battlefield rebuild here could race the
            # sweep loop that is moving this creature)."""
            linked = permanent.metadata.pop("on_death_destroy_permanents", None)
            for artifact in linked or ():
                artifact.metadata["destroy_linked_death"] = True
            if next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"dies"},
                instruction_kinds={"owner_loses_half_life"},
            ), None) is not None:
                loss = max(0, (player.life + 1) // 2)
                player.life -= loss
                self.log.append(
                    f"{permanent.card.name} died: {player.name} loses {loss} life (half, rounded up)"
                )
            # Rukh Egg: "When this creature dies, create a 4/4 red Bird
            # creature token with flying at the beginning of the next end
            # step." The source is gone by the time the token appears, so the
            # obligation is queued at the Game level (pending_end_step_tokens)
            # rather than tracked on the permanent, matching how "dies"
            # triggers are handled inline rather than via the stack.
            arm_trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"dies"},
                instruction_kinds={"arm_end_step_token"},
            ), None)
            if arm_trig is not None:
                payload = arm_trig.instruction.payload
                self.pending_end_step_tokens.append({
                    "controller_index": self.players.index(player),
                    "name": payload.get("name", "Token"),
                    "power": int(payload.get("power", 1)),
                    "toughness": int(payload.get("toughness", 1)),
                    "type_line": payload.get("type_line", "Creature — Token"),
                    "colors": tuple(payload.get("colors") or ()),
                    "keywords": tuple(payload.get("keywords") or ()),
                })
                self.log.append(
                    f"{permanent.card.name}: a {payload.get('name', 'token')} will appear at the next end step"
                )
        text = permanent.card.oracle_text.lower()
        if (
            "when this enchantment is put into a graveyard from the battlefield, you lose the game"
            in text
            and not player.lost
        ):
            player.lost = True
            self.log.append(
                f"{player.name} lost the game ({permanent.card.name} was put into a graveyard from the battlefield)"
            )

        if permanent.card.primary_type == "creature":
            self._fire_creature_dies_triggers(permanent)

        leave_hook = ON_LEAVE_BATTLEFIELD.get(permanent.card.name)
        if leave_hook is not None:
            leave_hook(self, player, permanent)

    def _destroy_swept_permanents(
        self,
        player: PlayerState,
        matches,
        *,
        allow_regeneration: bool = True,
        respect_indestructible: bool = True,
        on_regenerate=None,
        on_destroy=None,
    ) -> list[Permanent]:
        """Destroy every permanent on *player*'s battlefield that ``matches``,
        rebuilding the battlefield in place. Indestructible permanents survive
        (when respected); a creature's regeneration shield is consumed instead of
        destruction (when allowed). Each destruction routes through
        ``_permanent_to_graveyard`` while the permanent is still listed, matching
        the sweep loops this consolidates. Returns the destroyed permanents."""
        survivors: list[Permanent] = []
        destroyed: list[Permanent] = []
        for permanent in player.battlefield:
            if not matches(permanent):
                survivors.append(permanent)
                continue
            # Pyramids: a shielded land survives its next destruction this turn.
            if self._consume_land_destruction_shield(permanent):
                survivors.append(permanent)
                continue
            if respect_indestructible and self._is_indestructible(permanent):
                survivors.append(permanent)
                continue
            if (
                allow_regeneration
                and permanent.is_creature
                and permanent.regeneration_shield > 0
                # A "can't be regenerated this turn" rider makes the shield inert
                # (CR 701.19c) — it doesn't save the creature from a sweeper.
                and not permanent.metadata.get("cant_be_regenerated_this_turn")
            ):
                permanent.regeneration_shield -= 1
                permanent.tapped = True
                if on_regenerate is not None:
                    on_regenerate(permanent)
                survivors.append(permanent)
                continue
            self._permanent_to_graveyard(player, permanent)
            if on_destroy is not None:
                on_destroy(permanent)
            destroyed.append(permanent)
        player.battlefield = survivors
        return destroyed

    def _fire_creature_dies_triggers(self, dead_permanent: Permanent) -> None:
        """Put "whenever a creature dies" triggers (e.g. Soul Net) onto the stack.

        Observers may be controlled by any player. Triggers are enqueued here (in
        APNAP order) and resolve later through the stack — never inline (CR 603.3).
        Soul Net's "you may pay {N}" is offered when its trigger resolves, so no life
        is gained until the player answers the pay-prompt. Sengir Vampire's
        "creature dealt damage by this creature dies" condition is evaluated now (at
        fire time) because the dead permanent is gone by the time the trigger
        resolves; it is enqueued only when it qualifies.
        """
        events: list[dict] = []
        for controller in self.players:
            controller_index = self.players.index(controller)
            for observer in list(controller.battlefield):
                if observer is dead_permanent:
                    continue
                program = compile_card_oracle(observer.card)
                for trig in program.triggered_abilities:
                    # Sengir Vampire: "Whenever a creature dealt damage by this
                    # creature this turn dies, put a +1/+1 counter on this creature."
                    if (
                        trig.condition.kind == "creature_dealt_damage_by_self_dies"
                        and trig.instruction is not None
                        and trig.instruction.kind == "add_counter_to_self"
                    ):
                        damagers = dead_permanent.metadata.get("damaged_by_sources_this_turn", [])
                        if observer in damagers:
                            events.append(make_trigger_event(controller_index, observer, trig))
                        continue
                    if trig.condition.kind != "creature_dies" or trig.instruction is None:
                        continue
                    instr = trig.instruction
                    obs_text = observer.card.oracle_text.lower()
                    pay_match = re.search(r"you may pay \{(\d+)\}", obs_text)
                    if instr.kind == "target_gains_life":
                        amount = int(instr.payload.get("amount", 1))
                        ctx: dict = {"life": amount, "dead_name": dead_permanent.card.name}
                        if pay_match:
                            ctx["optional_pay_cost"] = int(pay_match.group(1))
                        events.append(make_trigger_event(
                            controller_index, observer, trig,
                            effect_kind="triggered_target_gains_life",
                            trigger_context=ctx,
                        ))
                    break
        self._enqueue_triggered_batch(events)

    def _put_permanent_onto_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
    ) -> None:
        self.players[controller_index].battlefield.append(permanent)
        self._initialize_permanent_state(permanent, controller_index, target_player_index)
        # 611.3a/611.3c: static abilities apply as permanents enter. Recalculate
        # lord buffs so the new permanent immediately receives applicable bonuses,
        # and so any new lord immediately buffs existing matching permanents.
        self._recompute_continuous_effects()
