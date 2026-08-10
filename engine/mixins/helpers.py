from __future__ import annotations

import re
from typing import Iterator

from ..card_hooks import ON_LEAVE_BATTLEFIELD
from ..auras import detach_aura
from ..control import (
    base_controller,
    change_control,
    control_changes,
    end_control_change,
    has_control_change,
    set_base_controller,
)
from ..events import emit
from ..layer_bridge import computed_controller
from ..land_types import end_land_type_change
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
        # Positional, deliberately: the web layer addresses a permanent by its
        # *slot* on its controller's battlefield, so this returns the index into
        # that list and not just the permanent. It is the one question the
        # control seam cannot answer, because the seam has no slots.
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
        change applied by a Lace card (StackItem.choices["new_color"])."""
        recolored = getattr(item, "choices", {}).get("new_color")
        if recolored:
            return (recolored,)
        return tuple(item.card.colors or ())

    def _is_creature(self, permanent: Permanent) -> bool:
        """A permanent is a creature if its printed type says so or an effect has
        turned it into one (e.g. Kormus Bell / Living Lands animated lands, or
        Jade Statue animated until end of combat)."""
        return permanent.is_creature

    def _controlled_since_turn_start(self, permanent: Permanent) -> bool:
        """Whether *permanent* has been under its controller's control since
        their most recent turn began (CR 302.6's condition).

        The condition itself, separated from summoning sickness. CR 302.6 uses
        it for creatures, and a card can name it directly for any permanent —
        Rocket Launcher's "activate only if you've controlled this artifact
        continuously since the beginning of your most recent turn" is the same
        question about an artifact, and asking `_is_summoning_sick` would have
        answered "no" purely because an artifact is not a creature.
        """
        return permanent.metadata.get("summoning_sickness_turn") != self.turn

    def _is_summoning_sick(self, permanent: Permanent) -> bool:
        if not self._is_creature(permanent):
            return False
        if self._has_keyword(permanent, "Haste"):
            return False
        return not self._controlled_since_turn_start(permanent)

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
        for index, permanent in self.permanents_with_controller():
            if index == active_player_index:
                continue
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
        for permanent in self.all_permanents():
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
        """End the continuous effects an Aura applied (CR 611.3).

        The Aura's P/T contribution is *derived* while it is attached
        (auras.aura_static_pt_grant via layer_bridge), so detaching it is the
        whole removal — there is no delta to subtract. What is still undone
        here are the metadata flags _apply_aura_effect stamps directly, plus
        the linked one-shots (control theft, animation, Animate Dead's
        sacrifice) that are not characteristics at all.
        """
        attached = aura.metadata.get("attached_to")
        if attached is None:
            return
        for key in aura.metadata.get("aura_granted_meta", []) or []:
            attached.metadata.pop(key, None)
        # A land-type change (Evil Presence, Phantasmal Terrain) is a layer-4
        # contribution keyed on this Aura, so ending it drops that one and
        # leaves anything else still making the land a type. Unconditional: an
        # Aura that recorded none has none to end.
        end_land_type_change(attached, source=aura)
        # Animate Artifact (and similar) replaced the permanent's card with an
        # animated artifact-creature version. Restore the original card so it stops
        # being a creature and the UI drops its power/toughness labels (CR 611.3).
        pre_animate_card = attached.metadata.pop("pre_animate_card", None)
        if pre_animate_card is not None:
            attached.card = pre_animate_card
        detach_aura(aura, attached)
        # Control effects (Control Magic, Steal Artifact) end when the Aura
        # leaves (CR 611.3 / 805.4a). Dropping the contribution is the whole
        # removal: whatever other layer-2 effect is still on the permanent
        # decides where it goes, and if none is, it returns to its base
        # controller.
        self.end_control_changes_from(aura)
        # Animate Dead: "When this Aura leaves the battlefield, that creature's
        # controller sacrifices it." Sacrificing isn't destroying, so
        # regeneration and other destruction replacements can't affect it
        # (CR 701.21a).
        if aura.metadata.get("sacrifice_attached_on_leave"):
            controller_index = self.controller_index_of(attached)
            if controller_index is not None:
                controller = self.players[controller_index]
                controller.battlefield = [p for p in controller.battlefield if p is not attached]
                self._permanent_to_graveyard(controller, attached)
                self.log.append(
                    f"{controller.name} sacrificed {attached.card.name} ({aura.card.name} left the battlefield)"
                )

    def _holding_seat(self, permanent: Permanent) -> int | None:
        """The seat whose battlefield list physically holds *permanent*, or None.

        The **zone** question, not the control one. Only the seam and the code
        that writes the zone may ask it; everything else wants
        :meth:`controller_index_of`, which applies layer 2 on top of this.

        Matches by identity, not ``in``: Permanent is a dataclass with value
        equality, so ``in`` would match a look-alike (an opponent's copy of the
        same card in the same state) after this object has left the battlefield.
        """
        return next(
            (
                i
                for i, p in enumerate(self.players)
                if any(perm is permanent for perm in p.battlefield)
            ),
            None,
        )

    def controller_index_of(self, permanent: Permanent) -> int | None:
        """Who controls *permanent* — CR 613 layer 2 — or None if it is on no
        battlefield (already left / phased out).

        Computed, not stored: the base controller (whoever put it onto the
        battlefield) with every recorded control-changing effect applied in
        timestamp order. ``_sync_control`` keeps the battlefield lists as the
        projection of this answer, so ``controlled_by`` and the web payload see
        the same thing without each applying the layer themselves.
        """
        seat = self._holding_seat(permanent)
        if seat is None:
            return None
        if not has_control_change(permanent):
            return seat
        base = base_controller(permanent)
        return computed_controller(permanent, seat if base is None else base)

    def owner_index_of(self, permanent: Permanent) -> int | None:
        """Index of the player who owns *permanent*'s card (CR 108.3), for
        routing it to the right graveyard/hand when it leaves the battlefield
        (CR 400.3).

        The base controller is the owner whenever the two differ, because every
        way a permanent enters play in this pool puts it under its owner's
        control. That used to be read off the *thief* (``stolen_owner_index``),
        which meant a second theft overwrote the first one's answer."""
        # Reanimation (Animate Dead on an opponent's creature card) records the
        # owner directly on the permanent.
        meta_owner = permanent.metadata.get("owner_player_index")
        if isinstance(meta_owner, int) and 0 <= meta_owner < len(self.players):
            return meta_owner
        base = base_controller(permanent)
        if base is not None and 0 <= base < len(self.players):
            return base
        return self.controller_index_of(permanent)

    def take_control(
        self,
        permanent: Permanent,
        seat,
        *,
        source: Permanent,
        extra_meta: dict | None = None,
    ) -> bool:
        """Record *source*'s CR 613 layer-2 effect giving *seat* control of
        *permanent*, then project it onto the battlefield lists.

        Returns False (a no-op) if the target is on no battlefield.
        ``extra_meta`` tags the *source* with its own revert-condition marker
        (Old Man of the Sea's tapped-and-weaker), which is a condition to check
        and not a value to restore.
        """
        holding = self._holding_seat(permanent)
        if holding is None:
            return False
        # A board built by hand (a test, a debug menu) never recorded a base, so
        # the seat it is sitting on now is the base — captured before the
        # contribution, which is the whole point of keeping the two apart.
        if base_controller(permanent) is None:
            set_base_controller(permanent, holding)
        change_control(permanent, self.seat_index(seat), source=source)
        if extra_meta:
            source.metadata.update(extra_meta)
        self._sync_control()
        return True

    def end_control_changes_from(self, source: Permanent) -> None:
        """Drop every control effect *source* recorded, and re-project.

        The inverse of :meth:`take_control`, and deliberately not an *undo*:
        it removes one contribution and lets whatever is left decide. Control
        Magic ending while Aladdin still holds the artifact leaves Aladdin's
        effect applying; both ending returns the permanent to its base
        controller. The old remember-the-previous-controller version could
        express neither, and handed the permanent to whoever the thief happened
        to have recorded — a player that by then controlled nothing giving it.
        """
        dropped = [
            (seat, permanent)
            for seat, permanent in list(self.permanents_with_controller())
            if end_control_change(permanent, source=source)
        ]
        self._sync_control()
        for seat, permanent in dropped:
            now = self.controller_index_of(permanent)
            if now is not None and now != seat:
                self.log.append(
                    f"{permanent.card.name} returns to {self.players[now].name}'s control "
                    f"({source.card.name} left the battlefield)"
                )

    def permanents_controlled_via(self, source: Permanent) -> list[Permanent]:
        """Every permanent *source* currently has a control effect on."""
        return [
            permanent
            for permanent in self.all_permanents()
            if any(entry["source"] is source for entry in control_changes(permanent))
        ]

    def _sync_control(self) -> None:
        """Move every permanent whose battlefield list disagrees with layer 2.

        The battlefield lists are a *projection* of the derived controller, not
        the storage for it. Keeping them in step here is what lets the 164
        migrated readers — and the whole web payload, which addresses a
        permanent by its slot on a controller's battlefield — keep asking the
        seam without any of them applying the layer themselves.

        It is also the single place CR 302.6 is stamped: a permanent changes
        hands exactly when this moves it, so "summoning sick since it came
        under your control" cannot be applied by one control path and forgotten
        by another.
        """
        for holding, permanent in list(self.permanents_with_controller()):
            base = base_controller(permanent)
            if base is None or not (0 <= base < len(self.players)):
                # Nothing has ever taken control of it and it never recorded a
                # base: it is where it belongs, whatever list that is.
                if not has_control_change(permanent):
                    continue
                base = holding
                set_base_controller(permanent, holding)
            derived = computed_controller(permanent, base)
            if derived == holding or not (0 <= derived < len(self.players)):
                continue
            self.players[holding].battlefield = [
                p for p in self.players[holding].battlefield if p is not permanent
            ]
            self.players[derived].battlefield.append(permanent)
            # CR 302.6: a creature is summoning-sick since it came under its
            # controller's control, not since it entered the battlefield — a
            # permanent that changes hands can't attack or use {T} abilities
            # this turn, in either direction.
            if self._is_creature(permanent):
                permanent.metadata["summoning_sickness_turn"] = self.turn

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
            # Abu Ja'far: "When this creature dies, destroy all creatures
            # blocking or blocked by it." The combat relationship is gone once
            # the battlefield is rebuilt, so it is captured here (CR 603.10)
            # and the trigger resolves off the stack (CR 603.3).
            combat_trig = next(matching_triggers(
                permanent.effective_card,
                condition_kinds={"dies"},
                instruction_kinds={"destroy_creatures_in_combat_with_source"},
            ), None)
            if combat_trig is not None:
                opponents = self.creatures_in_combat_with(permanent)
                self._enqueue_triggered_ability(
                    controller_index=self.players.index(player),
                    source_permanent=permanent,
                    card=permanent.card,
                    instruction=combat_trig.instruction,
                    effect_kind=combat_trig.effect_kind,
                    ability_text=combat_trig.source_line,
                    trigger_context={"combat_opponents": opponents},
                )
                self.log.append(f"{permanent.card.name} triggered (died in combat)")
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

    def become_tapped(self, permanent: "Permanent") -> bool:
        """Turn *permanent* from untapped to tapped, firing "becomes tapped"
        triggers (CR 701.26a). Returns whether it actually changed.

        The single place a permanent becomes tapped. Before this the engine set
        ``perm.tapped = True`` in seventeen places, so a trigger could only see
        whichever of them its implementer happened to wire into — Lifetap
        ("Whenever a Forest an opponent controls becomes tapped") was registered
        on the tapped-for-mana path and silently missed every other way a Forest
        gets tapped.

        A permanent that *enters* the battlefield tapped never becomes tapped —
        it was never untapped on the battlefield — so the enters-tapped path in
        permanent_state.py deliberately does not come through here. Neither does
        re-tapping something already tapped: CR 701.26a, "only untapped
        permanents can be tapped", so there is no state change and no trigger.

        The triggers go on the stack (CR 603.3). A "becomes tapped" trigger is
        not a mana ability — CR 605.1b requires that one *could add mana*, and
        605.5a says an ability that triggers on anything else follows the normal
        rules — so it may not resolve inline, which is what Lifetap's name-keyed
        hook used to do.
        """
        if permanent.tapped:
            return False
        permanent.tapped = True
        emit(self, "permanent_becomes_tapped", subject=permanent)
        return True

    # ------------------------------------------------------------------
    # The control seam (CR 613 layer 2)
    #
    # "Which permanents are on the battlefield", "which does this player
    # control" and "is this permanent still there" are asked all over the
    # engine, and each of them used to be answered by opening
    # ``player.battlefield`` by hand. That is not a zone question with an
    # incidental control answer — it *is* the control question, because this
    # engine models control as which battlefield list a permanent sits in.
    #
    # Everything below is the one place that reads zone membership. Wiring
    # layer 2 means changing these four methods and nothing else; a reader that
    # goes around them is a second opinion about who controls what, which is the
    # bug class ``tests/engine/test_control_reads.py`` guards.
    #
    # Each iterator snapshots the list it walks, so a caller may destroy or
    # steal permanents while iterating without skipping the next one.
    # ------------------------------------------------------------------

    def all_permanents(self) -> "Iterator[Permanent]":
        """Every permanent on the battlefield, in seat order."""
        for player in self.players:
            yield from list(player.battlefield)

    def permanents_with_controller(self) -> "Iterator[tuple[int, Permanent]]":
        """Every permanent paired with its controller's seat index."""
        for index, player in enumerate(self.players):
            for permanent in list(player.battlefield):
                yield index, permanent

    def seat_index(self, seat) -> int:
        """*seat* as a seat index, whether it arrived as one or as a
        :class:`PlayerState`. By identity: ``self.players.index(player)`` is an
        equality search over a mutable dataclass, so two seats that happen to
        hold equal state would resolve to the same index."""
        if isinstance(seat, int):
            return seat
        return next(i for i, player in enumerate(self.players) if player is seat)

    def controlled_by(self, seat) -> "Iterator[Permanent]":
        """Every permanent *seat* controls. Takes a seat index or a
        :class:`PlayerState`, because both spellings are already in use and the
        question is the same one either way."""
        player = self.players[seat] if isinstance(seat, int) else seat
        return iter(list(player.battlefield))

    def controls(self, seat, permanent: Permanent) -> bool:
        """Whether *seat* controls *permanent*, by identity — the replacement
        for ``permanent in player.battlefield``, which compares by value."""
        return self.controller_index_of(permanent) == self.seat_index(seat)

    def permanents_matching(self, predicate) -> "Iterator[Permanent]":
        """Every permanent satisfying *predicate*, across all battlefields."""
        return (perm for perm in self.all_permanents() if predicate(perm))

    def is_on_battlefield(self, permanent: Permanent) -> bool:
        """Whether *permanent* is on the battlefield, **by identity**.

        ``permanent in player.battlefield`` is the shape this replaces, and it
        was wrong: :class:`Permanent` is a dataclass with value equality, so
        ``in`` answers yes for a look-alike — an opponent's untouched copy of
        the same card — after this object has left. That made an Aura whose
        enchanted creature had died survive CR 704.5m as long as some other
        player had an identical creature in an identical state."""
        return any(perm is permanent for perm in self.all_permanents())

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
                self.become_tapped(permanent)
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
        for controller_index, observer in self.permanents_with_controller():
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
                if instr.kind == "may":
                    # A grammar-lowered optional action carries its own cost
                    # and consequence, so there is nothing to re-derive here.
                    events.append(make_trigger_event(
                        controller_index, observer, trig,
                        trigger_context={"dead_name": dead_permanent.card.name},
                    ))
                    continue
                if instr.kind == "target_gains_life":
                    # Legacy shape: the optional cost lives in the card's
                    # text rather than the instruction, so it has to be
                    # re-read here and passed along as context.
                    obs_text = observer.card.oracle_text.lower()
                    pay_match = re.search(r"you may pay \{(\d+)\}", obs_text)
                    amount = int(instr.payload.get("amount", 1))
                    ctx: dict = {"life": amount, "dead_name": dead_permanent.card.name}
                    if pay_match:
                        ctx["optional_pay_cost"] = int(pay_match.group(1))
                    events.append(make_trigger_event(
                        controller_index, observer, trig,
                        effect_kind="triggered_target_gains_life",
                        trigger_context=ctx,
                    ))
        self._enqueue_triggered_batch(events)

    def _put_permanent_onto_battlefield(
        self,
        controller_index: int,
        permanent: Permanent,
        target_player_index: int | None,
    ) -> None:
        self.players[controller_index].battlefield.append(permanent)
        # CR 613.1: the value layer 2 starts from. Recorded on entry and never
        # written again, so an ending control effect reverts to the seat that
        # put the permanent into play rather than to whichever seat held it
        # most recently.
        set_base_controller(permanent, controller_index)
        self._initialize_permanent_state(permanent, controller_index, target_player_index)
        # 611.3a/611.3c: static abilities apply as permanents enter. Recalculate
        # lord buffs so the new permanent immediately receives applicable bonuses,
        # and so any new lord immediately buffs existing matching permanents.
        self._recompute_continuous_effects()
